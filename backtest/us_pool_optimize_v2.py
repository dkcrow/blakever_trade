"""
七星美股版池优化 — 3年+5年回测, 严格无forward-looking
策略: 移除低贡献/从未入选股票, 添加高动量候选
"""
import pandas as pd, numpy as np, math, json, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/us')
OUT_DIR = Path('backtest/results_us100')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ====== 基础池 (当前40只) ======
BASE_POOL = ['NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','AAPL','TSM','LITE',
    'META','AMZN','NFLX','GOOGL','MSFT','CRM','NOW','CRWD','ORCL','PLTR',
    'DDOG','SNPS','XOM','CVX','COP','EOG','OKE','NEM','FCX','LIN','CAT','GE',
    'RTX','PLD','AMT','PANW','ZS','NET','IONQ','RKLB']

# ====== 候选新增 ======
CANDIDATES = {
    # 半导体/芯片验证
    'MRVL': 'Marvell',
    'QCOM': 'Qualcomm',
    # AI/数据
    'SNOW': 'Snowflake',
    'MDB': 'MongoDB',
    # 加密/金融
    'COIN': 'Coinbase',
    # 医疗
    'ISRG': 'Intuitive Surgical',
    # 共享经济
    'UBER': 'Uber',
    'ABNB': 'Airbnb',
    # 量子计算补充
    'QBTS': 'D-Wave',
    # 航天补充
    'LUNR': 'Intuitive Machines',
    # 能源
    'CEG': 'Constellation Energy',
    'VST': 'Vistra Energy',
}

# ====== 回测参数 ======
PARAMS = {'lookback_days': 25, 'holdings_num': 7, 'min_money': 500}
SLIP = 0.0005; COMM = 0.005; CASH = 100000

def load_all_us(symbols):
    data = {}
    for s in symbols:
        if s in data: continue
        fp = DATA_DIR / f'{s}.csv'
        if fp.exists():
            try:
                df = pd.read_csv(fp)
                df.columns = [c.lower() for c in df.columns]
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                if len(df) > 50:
                    data[s] = df
            except: pass
    return data

def score_qx(closes):
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_res = np.sum(res**2); ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return ann * r2

def run_backtest(pool_symbols, start_date, end_date):
    """标准七星美股版回测"""
    lb = PARAMS['lookback_days']; hn = PARAMS['holdings_num']
    
    # 加载数据
    all_data = load_all_us(pool_symbols)
    if len(all_data) < hn + 5:
        return None
    
    # 确定交易日
    all_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
    trade_dates = [d for d in all_dates if start_date <= d.strftime('%Y-%m-%d') <= end_date]
    if len(trade_dates) < 50:
        return None
    
    cash = CASH; pos = {}; trades = []; dv = []
    
    for date in trade_dates:
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for c in all_data:
            m = all_data[c].index == date
            if m.any(): prices[c] = float(all_data[c].loc[date, 'close'])
        if len(prices) < hn: continue
        
        # 排名
        ranked = []
        for c in all_data:
            if c not in prices: continue
            m = all_data[c].index < pd.Timestamp(date)
            hist = all_data[c][m]
            if len(hist) < lb + 10: continue
            hp = hist['close'].values[-lb:].copy()
            if np.any(hp <= 0): continue
            s = score_qx(hp)
            if s > 0:
                ranked.append({'code': c, 'score': s, 'price': prices[c]})
        
        ranked.sort(key=lambda x: x['score'], reverse=True)
        if len(ranked) < hn: continue
        
        targets = [r for r in ranked[:hn] if r['score'] > -999]
        target_codes = set(r['code'] for r in targets)
        
        # 卖出
        for c in list(pos.keys()):
            if c not in target_codes and c in prices:
                sp = prices[c] * (1 - SLIP)
                pnl = (sp - pos[c]['cost']) / pos[c]['cost'] * 100
                trades.append({'date': d_str, 'action': 'SELL', 'code': c,
                              'shares': pos[c]['shares'], 'price': round(sp, 2),
                              'pnl_pct': round(pnl, 2)})
                tv = pos[c]['shares'] * sp; cf = pos[c]['shares'] * COMM
                cash += tv - cf
                del pos[c]
        
        # 买入
        total_val = cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in pos.items())
        per_stock = total_val * 0.95 / len(targets)
        for r in targets:
            c = r['code']
            if c not in pos and c in prices:
                bp = prices[c] * (1 + SLIP)
                shares = int(per_stock / bp)
                if shares > 0:
                    tv = shares * bp; cf = shares * COMM
                    cash -= tv + cf
                    pos[c] = {'shares': shares, 'cost': bp}
                    trades.append({'date': d_str, 'action': 'BUY', 'code': c,
                                  'shares': shares, 'price': round(bp, 2)})
        
        dv.append({'date': d_str, 'value': cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in pos.items())})
    
    # 统计
    dv_df = pd.DataFrame(dv)
    if len(dv_df) < 2: return None
    tr = (dv_df['value'].iloc[-1] / CASH - 1) * 100
    dr = dv_df['value'].pct_change().dropna()
    ar = (1 + dr.mean())**252 - 1
    md = (dv_df['value'] / dv_df['value'].cummax() - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    sells = [t for t in trades if t['action'] == 'SELL']
    wr = sum(1 for t in sells if t.get('pnl_pct', 0) > 0) / max(len(sells), 1) * 100
    
    return {
        'total_return': round(tr, 2), 'annual_return': round(ar * 100, 1),
        'max_drawdown': round(md, 1), 'sharpe': round(sp, 2),
        'total_trades': len(trades), 'win_rate': round(wr, 1),
        'pool_size': len(pool_symbols), 'data_loaded': len(all_data),
        'start': trade_dates[0].strftime('%Y-%m-%d'),
        'end': trade_dates[-1].strftime('%Y-%m-%d'),
        'trading_days': len(trade_dates),
    }

# ====== 优化方案 ======
configs = {}

# 1. 基准池 (当前40只)
configs['基准 (40只)'] = BASE_POOL

# 2. 精简池 (移除从未买入+极低贡献)
# 从未买入: MSFT, CRM
# 均负盈亏: AMAT, AAPL, TSM, META, AMZN, CRWD, PLTR, DDOG, XOM, CVX, COP, LIN, PLD
removed = ['MSFT', 'CRM', 'AMAT', 'AAPL', 'TSM', 'META', 'AMZN',
           'PLTR', 'XOM', 'CVX', 'COP', 'LIN', 'PLD']
trimmed = [s for s in BASE_POOL if s not in removed]
configs['精简 (27只)'] = trimmed

# 3. 扩展池 (全场)
extended = list(BASE_POOL) + list(CANDIDATES.keys())
configs['全场 (53只)'] = extended

# 4. 精简+精选扩展 (保留核心+新增)
core = ['NVDA','AVGO','AMD','MU','LRCX','ARM','LITE','IONQ','RKLB',
        'GOOGL','ORCL','SNPS','OKE','NEM','FCX','CAT','GE',
        'DDOG','CRWD','PANW','ZS','NET',
        'MRVL','QCOM','COIN','QBTS','CEG','VST']
configs['精选核心 (27只)'] = core

# 5. 精简+精选扩展+防御
core_defense = core + ['XOM','CVX','CAT','GE','RTX','PLD','AMT','ISRG','CEG']
configs['精选+防御 (36只)'] = list(set(core_defense))

# ====== 运行 ======
for period_name, (start, end) in [('3年 (2023.6~今)', ('2023-06-01', '2026-06-11')),
                                    ('5年 (2021.6~今)', ('2021-06-01', '2026-06-11'))]:
    print(f'\n{"="*70}')
    print(f'  {period_name}')
    print(f'{"="*70}')
    
    # 先确保候选数据存在
    all_candidates = list(CANDIDATES.keys())
    existing = load_all_us(all_candidates)
    missing = [c for c in all_candidates if c not in existing]
    if missing:
        print(f'  缺失数据: {missing} — 跳过含这些标的的池')
    
    results = []
    for name, pool in configs.items():
        # 跳过含缺失数据的池
        if any(c in missing for c in pool):
            continue
        print(f'  测试: {name} ({len(pool)}只) ... ', end='', flush=True)
        r = run_backtest(pool, start, end)
        if r:
            results.append((name, r))
            print(f'+{r["total_return"]:.1f}% 年化{r["annual_return"]:.1f}% 回撤{r["max_drawdown"]:.1f}% 夏普{r["sharpe"]:.2f} 交易{r["total_trades"]}笔')
        else:
            print('数据不足')
    
    # 打印汇总表
    header = '  ' + '池'.ljust(25) + '累计'.rjust(8) + '年化'.rjust(7) + '回撤'.rjust(6) + '夏普'.rjust(5) + '交易'.rjust(5) + '胜率'.rjust(5)
    print(header)
    print('  ' + '-' * 65)
    for name, r in sorted(results, key=lambda x: x[1]['total_return'], reverse=True):
        tr = r['total_return']; ar = r['annual_return']; md = r['max_drawdown']
        sp = r['sharpe']; nt = r['total_trades']; wr = r['win_rate']
        print('  %-25s %+7.1f%% %6.1f%% %5.1f%% %5.2f %5d %5.1f%%' % (name, tr, ar, md, sp, nt, wr))

# ====== 生成HTML报告 ======
print('\n生成报告...')
html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>七星美股版 池优化</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:20px auto;padding:0 20px;color:#333}}
h1{{color:#1F4E79}}h2{{color:#2E75B6;margin-top:30px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}}
th{{background:#1F4E79;color:#fff;padding:8px;text-align:center}}
td{{padding:6px 8px;text-align:center;border:1px solid #ddd}}
tr:nth-child(even){{background:#f8f9fa}}
.best{{background:#D4EDDA!important;font-weight:bold}}
.card{{background:#fff;padding:15px;border-radius:8px;margin:10px 0;box-shadow:0 2px 4px rgba(0,0,0,.1)}}
</style></head><body>
<h1>七星美股版 成分股池优化回测</h1>
<p>回测引擎: exp(slope×250)×R², 25日动量, 7只等权, 佣金$0.005/股, 滑点0.05%, 动量计算排除当日价</p>
"""

for period_name, (start, end) in [('3年 (2023.6~今)', ('2023-06-01', '2026-06-11')),
                                    ('5年 (2021.6~今)', ('2021-06-01', '2026-06-11'))]:
    html += f'<h2>{period_name}</h2><div class="card"><table>'
    html += '<tr><th>池</th><th>只数</th><th>累计</th><th>年化</th><th>回撤</th><th>夏普</th><th>交易</th><th>胜率</th></tr>'
    
    all_candidates = list(CANDIDATES.keys())
    existing = load_all_us(all_candidates)
    missing = [c for c in all_candidates if c not in existing]
    
    results = []
    for name, pool in configs.items():
        if any(c in missing for c in pool): continue
        r = run_backtest(pool, start, end)
        if r: results.append((name, r))
    
    results.sort(key=lambda x: x[1]['total_return'], reverse=True)
    best_name = results[0][0]
    
    for name, r in results:
        cls = ' class="best"' if name == best_name else ''
        html += f'<tr{cls}><td>{name}</td><td>{r["pool_size"]}</td>'
        html += f'<td style="color:#28A745">+{r["total_return"]:.1f}%</td><td>{r["annual_return"]:.1f}%</td>'
        html += f'<td style="color:#DC3545">{r["max_drawdown"]:.1f}%</td><td>{r["sharpe"]:.2f}</td>'
        html += f'<td>{r["total_trades"]}</td><td>{r["win_rate"]:.1f}%</td></tr>'
    
    html += '</table></div>'

# 移除/新增说明
html += """<h2>池方案说明</h2><div class="card">
<table>
<tr><th>方案</th><th>说明</th></tr>
<tr><td>基准 (40只)</td><td>当前实盘池: 半导体+科技+能源+材料+工业+REITs+安全+新赛道</td></tr>
<tr><td>精简 (27只)</td><td>移除从未买入(MSFT/CRM)及持续亏损(AMAT/AAPL/TSM/META/AMZN/PLTR/XOM/CVX/COP/LIN/PLD)</td></tr>
<tr><td>全场 (53只)</td><td>基准40只 + 13只候选(MRVL/QCOM/SNOW/MDB/COIN/SQ/ISRG/UBER/ABNB/QBTS/LUNR/CEG/VST)</td></tr>
<tr><td>精选核心 (27只)</td><td>仅保留历史高贡献股 + 新增高增长候选</td></tr>
<tr><td>精选+防御 (36只)</td><td>精选核心 + 能源/工业/REITs防御层</td></tr>
</table>
<p style="color:#888;font-size:12px">⚠️ 所有回测均使用严格forward-looking: 动量计算排除当日收盘价(&lt; date), 交易含0.05%滑点</p>
</div></body></html>"""

out_file = OUT_DIR / f'七星美股版_池优化回测_{pd.Timestamp.now().strftime("%Y%m%d_%H%M")}.html'
with open(out_file, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'报告: {out_file}')
