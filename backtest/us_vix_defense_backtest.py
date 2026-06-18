#!/usr/bin/env python3
"""
七星美股版 VIX防守回退回测
当 VIX > 阈值时切换至防守池 (GLD/TLT/IEF/SHY/XLU/XLP/XLV/USMV/IAU/AGG)
防守池内仍按动量排名选股，同等权7只
"""
import sys, os, math, json, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUTPUT_DIR = PROJECT_ROOT / 'backtest' / 'results_us100'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STRATEGY_NAME = '七星美股版 VIX防守回退'
START_DATE = '2023-06-01'
END_DATE = '2026-04-23'

# 进攻池 (35只)
AGGRESSIVE_POOL = [
    'NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','AAPL','TSM','LITE',
    'META','AMZN','NFLX','GOOGL','MSFT','CRM','NOW','CRWD','ORCL',
    'PLTR','DDOG','SNPS','XOM','CVX','COP','EOG','OKE',
    'NEM','FCX','LIN','CAT','GE','RTX','PLD','AMT',
]

# 防守池 (10只 ETFs — 黄金/债券/低波/公共事业/消费防御/医疗)  
DEFENSIVE_POOL = [
    'GLD',   # 黄金
    'IAU',   # 黄金备选
    'TLT',   # 20年+美债
    'IEF',   # 7-10年美债
    'SHY',   # 1-3年短期国债
    'AGG',   # 综合债券
    'XLU',   # 公用事业
    'XLP',   # 必需消费品
    'XLV',   # 医疗保健
    'USMV',  # 低波动
]

PARAMS = {
    'lookback_days': 25, 'holdings_num': 7, 'min_money': 500,
    'slippage': 0.0005, 'comm_per_share': 0.005,
}

# VIX 阈值列表
VIX_THRESHOLDS = [20, 25, 30, 35]

print("=" * 60)
print(f"  {STRATEGY_NAME}")
print(f"  区间: {START_DATE} ~ {END_DATE}")
print(f"  VIX阈值: {VIX_THRESHOLDS}")
print("=" * 60)

# ============================================================
# Step 1: 加载数据
# ============================================================
print(f"\n加载数据...")
all_data = {}
all_symbols = list(set(AGGRESSIVE_POOL + DEFENSIVE_POOL + ['VIX']))

for sym in all_symbols:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists():
        continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={
            'Date': 'date', 'Open': 'open', 'High': 'high',
            'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        })
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        mask = (df.index >= START_DATE) & (df.index <= END_DATE)
        df = df[mask]
        if len(df) >= 25:
            all_data[sym] = df
    except Exception:
        pass

print(f"  进攻池: {sum(1 for s in AGGRESSIVE_POOL if s in all_data)}/{len(AGGRESSIVE_POOL)}")
print(f"  防守池: {sum(1 for s in DEFENSIVE_POOL if s in all_data)}/{len(DEFENSIVE_POOL)}")
print(f"  VIX: {'✅' if 'VIX' in all_data else '❌'}")

if 'VIX' not in all_data:
    print("[FATAL] VIX data not found")
    sys.exit(1)

# ============================================================
# Step 2: 提取交易日
# ============================================================
trade_dates = sorted(set().union(*[
    df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()
]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]
print(f"  交易日: {len(trade_dates)} 天")

# ============================================================
# Step 3: 回测引擎
# ============================================================
class USPortfolio:
    def __init__(self, cash=10000, comm=0.005, slippage=0.0005):
        self.initial_cash = cash; self.cash = cash; self.comm = comm
        self.slippage = slippage
        self.positions = {}; self.trade_log = []; self.daily_values = []
    
    @property
    def total_value(self):
        pv = sum(p['shares'] * p.get('last_price', p['cost_price']) for p in self.positions.values())
        return self.cash + pv
    
    def update_prices(self, pdict):
        for c, p in pdict.items():
            if c in self.positions: self.positions[c]['last_price'] = p
    
    def buy(self, code, shares, price, date, reason=''):
        price = price * (1 + self.slippage)
        tv = shares * price; comm = shares * self.comm; total = tv + comm
        if total > self.cash + 0.01: return False
        self.cash -= total
        if code in self.positions:
            o = self.positions[code]; ts = o['shares'] + shares
            self.positions[code] = {
                'shares': ts, 'cost_price': (o['shares']*o['cost_price']+shares*price)/ts,
                'last_price': price, 'buy_date': o.get('buy_date', date)
            }
        else:
            self.positions[code] = {
                'shares': shares, 'cost_price': price, 'last_price': price, 'buy_date': date
            }
        self.trade_log.append({
            'date': str(date)[:10], 'code': code, 'action': 'BUY', 'price': round(price, 4),
            'shares': int(shares), 'amount': round(tv, 2), 'commission': round(comm, 2), 'reason': reason,
        })
        return True
    
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        price = price * (1 - self.slippage)
        pos = self.positions[code]
        actual = min(shares, pos['shares'])
        if actual <= 0: return False
        tv = actual * price; comm = actual * self.comm
        self.cash += tv - comm
        pos['shares'] -= actual
        pnl = (price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares'] <= 0: del self.positions[code]
        self.trade_log.append({
            'date': str(date)[:10], 'code': code, 'action': 'SELL', 'price': round(price, 4),
            'shares': int(actual), 'amount': round(tv, 2), 'commission': round(comm, 2),
            'pnl_pct': round(pnl, 4), 'reason': reason,
        })
        return True
    
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions: return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)
    
    def record_daily_value(self, date):
        v = self.total_value
        self.daily_values.append({
            'date': str(date)[:10], 'value': round(v, 2),
            'returns': round((v-self.initial_cash)/self.initial_cash, 6),
        })
    
    def get_position_codes(self):
        return list(self.positions.keys())


def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope * x + intercept)) ** 2)
    sst = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann * r2


def get_ranked(all_data, prices, date, pool_subset):
    """动量排名: 仅使用 date 之前(不含当日)数据, 防未来函数"""
    ranked = []
    lb = 25
    for code in pool_subset:
        if code not in all_data or code not in prices:
            continue
        df = all_data[code]
        mask = df.index < pd.Timestamp(date)
        hist = df[mask]
        if len(hist) < lb + 10:
            continue
        cp = prices[code]
        if cp <= 0:
            continue
        score = calc_score(hist['close'].values, lb)
        ranked.append({'code': code, 'score': score, 'price': cp})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


def run_backtest(vix_threshold):
    """运行指定 VIX 阈值的回测"""
    pf = USPortfolio(cash=10000, comm=PARAMS['comm_per_share'], slippage=PARAMS['slippage'])
    hn = PARAMS['holdings_num']
    
    current_regime = 'aggressive'  # 当前模式
    regime_switch_count = 0
    defense_days = 0
    
    for td in trade_dates:
        tds = pd.Timestamp(td)
        
        # 获取当日收盘价
        prices = {}
        for code, df in all_data.items():
            m = df.index <= tds
            if m.any():
                prices[code] = float(df.loc[m, 'close'].iloc[-1])
        pf.update_prices(prices)
        
        # VIX 行情判断 (用前一日 VIX 收盘价)
        vix_df = all_data['VIX']
        vix_mask = vix_df.index < tds
        if vix_mask.any():
            prev_vix = float(vix_df.loc[vix_mask, 'close'].iloc[-1])
        else:
            prev_vix = vix_threshold  # 数据不足时默认正常
        
        new_regime = 'defensive' if prev_vix > vix_threshold else 'aggressive'
        if new_regime != current_regime:
            regime_switch_count += 1
            current_regime = new_regime
        
        if current_regime == 'defensive':
            defense_days += 1
        
        # 选择当前池
        pool = DEFENSIVE_POOL if current_regime == 'defensive' else AGGRESSIVE_POOL
        ranked = get_ranked(all_data, prices, td, pool)
        
        if not ranked:
            pf.record_daily_value(td)
            continue
        
        targets = [r['code'] for r in ranked[:hn]]
        
        # 换池时全部卖出
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                pf.sell_all(code, prices[code], td, reason='调出目标')
        
        # 等权调仓
        tv = pf.total_value
        each = tv / len(targets)
        for idx, code in enumerate(targets):
            if code not in prices:
                continue
            price = prices[code]
            cv = 0
            if code in pf.positions:
                cv = pf.positions[code]['shares'] * pf.positions[code]['last_price']
            diff = each - cv
            if abs(diff) < each * 0.05 and cv > 0:
                continue
            if diff > 0:
                sh = int(diff / price)
                if sh > 0 and sh * price >= PARAMS['min_money']:
                    pf.buy(code, sh, price, td, reason=f'排名{idx+1}')
        
        pf.record_daily_value(td)
    
    return pf, regime_switch_count, defense_days


# ============================================================
# Step 4: 运行所有阈值
# ============================================================
# 先跑基线 (无VIX过滤)
print(f"\n{'='*60}")
print(f"  基线: 无VIX过滤 (纯进攻池)")
print(f"{'='*60}")
baseline_pf, _, _ = run_backtest(999)  # VIX阈值极大 → 永不触发防守

results = {'baseline': baseline_pf}
for vt in VIX_THRESHOLDS:
    print(f"\n{'='*60}")
    print(f"  VIX阈值: > {vt}")
    print(f"{'='*60}")
    pf, switches, def_days = run_backtest(vt)
    results[f'vix{vt}'] = pf
    print(f"  防守天数: {def_days}/{len(trade_dates)} ({def_days/len(trade_dates)*100:.1f}%)")
    print(f"  模式切换: {switches} 次")

# ============================================================
# Step 5: 汇总对比
# ============================================================
def calc_metrics(pf):
    dv = pf.daily_values
    vals = [d['value'] for d in dv]
    fv = vals[-1]
    tr = (fv - pf.initial_cash) / pf.initial_cash
    peak, mdd = vals[0], 0
    for v in vals:
        if v > peak: peak = v
        dd = (peak-v)/peak if peak>0 else 0
        if dd>mdd: mdd=dd
    sh = 0
    if len(vals)>1:
        dr = np.diff(vals)/vals[:-1]
        sh = (np.mean(dr)/np.std(dr)*np.sqrt(252)) if np.std(dr)>0 else 0
    cm = abs(tr*252/len(trade_dates))/mdd if mdd>0 else 0
    trades = pf.trade_log
    buys = sum(1 for t in trades if t['action']=='BUY')
    sells = sum(1 for t in trades if t['action']=='SELL')
    st = [t for t in trades if t['action']=='SELL' and 'pnl_pct' in t]
    wins = [t for t in st if t['pnl_pct']>0]
    wr = len(wins)/len(st)*100 if st else 0
    return {
        'final_value': fv, 'total_return': tr*100,
        'annualized': tr*252/len(trade_dates)*100,
        'max_dd': mdd*100, 'sharpe': sh, 'calmar': cm,
        'trades': len(trades), 'buy': buys, 'sell': sells,
        'win_rate': wr, 'daily_values': dv, 'trade_log': trades,
    }

print(f"\n{'='*80}")
print(f"  VIX防守对比汇总")
print(f"{'='*80}")
print(f"{'策略':<20} {'累计收益':>10} {'年化':>8} {'回撤':>8} {'夏普':>8} {'交易':>6} {'胜率':>6}")
print("-" * 80)

all_metrics = {}
labels_map = {'baseline': '无VIX过滤'}
for vt in VIX_THRESHOLDS:
    labels_map[f'vix{vt}'] = f'VIX>{vt}'

for key in ['baseline'] + [f'vix{vt}' for vt in VIX_THRESHOLDS]:
    m = calc_metrics(results[key])
    all_metrics[key] = m
    label = labels_map[key]
    r = m['total_return']
    a = m['annualized']
    d = m['max_dd']
    s = m['sharpe']
    t = m['trades']
    w = m['win_rate']
    print(f"{label:<20} {r:+9.2f}% {a:7.1f}% {d:7.1f}% {s:8.4f} {t:6d} {w:5.1f}%")

baseline_ret = all_metrics['baseline']['total_return']
print("-" * 80)
for vt in VIX_THRESHOLDS:
    diff = all_metrics[f'vix{vt}']['total_return'] - baseline_ret
    print(f"  VIX>{vt} vs 基线: {diff:+.2f}%")

# ============================================================
# Step 6: 生成对比报告
# ============================================================
now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
now_tag = datetime.now().strftime('%Y%m%d_%H%M')

# 汇总表
comparison_rows = ""
for key in ['baseline'] + [f'vix{vt}' for vt in VIX_THRESHOLDS]:
    m = all_metrics[key]
    label = labels_map[key]
    diff_ret = m['total_return'] - baseline_ret
    diff_color = '#28A745' if diff_ret > 0 else '#DC3545'
    bg = '#FFF' if key == 'baseline' else ('#E8F5E9' if diff_ret > 0 else '#FFEBEE')
    r_color = '#28A745' if m['total_return'] > 0 else '#DC3545'
    comparison_rows += f"""<tr style="background:{bg};">
        <td style="font-weight:bold;">{label}</td>
        <td style="text-align:right;font-weight:bold;color:{r_color};">{m['total_return']:+.2f}%</td>
        <td style="text-align:right;">{m['annualized']:.1f}%</td>
        <td style="text-align:right;">{m['max_dd']:.1f}%</td>
        <td style="text-align:right;">{m['sharpe']:.4f}</td>
        <td style="text-align:right;">{m['trades']}</td>
        <td style="text-align:right;">{m['win_rate']:.1f}%</td>
        <td style="text-align:right;font-weight:bold;color:{diff_color};">{diff_ret:+.2f}%</td></tr>"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>七星美股版 VIX防守回退对比</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:1000px;margin:0 auto;padding:20px;background:#f8f9fa;}}
h1{{font-size:22px;color:#1F4E79;text-align:center;margin:0 0 5px;}}
.subtitle{{text-align:center;font-size:13px;color:#888;margin-bottom:20px;}}
.card{{background:#fff;padding:15px 20px;border-radius:8px;margin-bottom:15px;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.card h2{{font-size:16px;color:#1F4E79;margin:0 0 12px;padding-bottom:8px;border-bottom:2px solid #E3F2FD;}}
.config-box{{background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:15px;font-size:13px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{background:#1F4E79;color:#fff;padding:8px;text-align:left;}}
td{{padding:7px 8px;border-bottom:1px solid #eee;}}
.conclusion-box{{background:#E8F5E9;border:2px solid #4CAF50;padding:16px 20px;border-radius:8px;margin:15px 0;}}
.conclusion-box.warn-bg{{background:#FFF3CD;border-color:#FFC107;}}
.conclusion-box.danger-bg{{background:#FFEBEE;border-color:#F44336;}}
.footer{{text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;}}
.best{{background:#C8E6C9 !important;font-weight:bold;}}
</style></head><body>

<h1>七星美股版 · VIX防守回退对比</h1>
<div class="subtitle">{now_str} | 回测区间: {START_DATE} ~ {END_DATE} ({len(trade_dates)}天) | 修复后引擎(防未来函数+滑点)</div>

<div class="config-box">
    <b>进攻池:</b> 35只高成长美股 | <b>防守池:</b> 10只ETF (GLD/TLT/IEF/SHY/AGG/XLU/XLP/XLV/USMV/IAU)<br>
    <b>规则:</b> VIX前日收盘 > 阈值 → 切换至防守池做动量排名(同7只等权) | VIX ≤ 阈值 → 恢复进攻池<br>
    <b>引擎:</b> 动量排除当日(防未来函数) | 滑点 0.05% | 佣金 $0.005/股 | 评分: exp(slope×250)×R²
</div>

<div class="card"><h2>回测对比</h2>
<table>
<tr><th>策略</th><th>累计收益</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>交易</th><th>胜率</th><th>vs基线</th></tr>
{comparison_rows}
</table></div>

<div class="card"><h2>VIX 统计</h2>
<table>
<tr><th>指标</th><th>数值</th></tr>
"""

# VIX stats
vix_vals = all_data['VIX']['close'].values
html += f"""<tr><td>均值</td><td>{np.mean(vix_vals):.2f}</td></tr>
<tr><td>中位数</td><td>{np.median(vix_vals):.2f}</td></tr>
<tr><td>P80</td><td>{np.percentile(vix_vals, 80):.2f}</td></tr>
<tr><td>P90</td><td>{np.percentile(vix_vals, 90):.2f}</td></tr>
<tr><td>最大值</td><td>{np.max(vix_vals):.2f}</td></tr>
<tr><td>最小值</td><td>{np.min(vix_vals):.2f}</td></tr>
"""

for vt in VIX_THRESHOLDS:
    days = sum(1 for v in vix_vals if v > vt)
    pct = days / len(vix_vals) * 100
    html += f"<tr><td>VIX > {vt} 天数</td><td>{days} ({pct:.1f}%)</td></tr>"

html += """</table></div>
<div class="footer">七星美股版 · Blakever Trade · """ + now_str + """<br>本报告仅供研究参考，不构成投资建议。</div>
</body></html>"""

fp_html = OUTPUT_DIR / f'七星美股版_VIX防守对比_{now_tag}.html'
with open(fp_html, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'\n报告: {fp_html}')
print(f"\n{'='*80}")
print(f"  全部完成!")
print(f"{'='*80}")
