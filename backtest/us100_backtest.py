#!/usr/bin/env python3
"""
七星美股版策略回测 (Nasdaq 100 动量策略)
基于七星QMT框架，成分股 = 高成长35只优化池 (无防御板块，PP关)
数据源: 本地CSV (data/storage/stock_data/us/)
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

STRATEGY_NAME = '七星美股版(最优) x7'
START_DATE = '2023-06-01'
END_DATE = '2026-04-23'  # 本地数据最新日期

# 七星美股版最优池 (35只, 8类 — 无防御板块)
# 精简27+SPCX (2026-06-16: +SPCX SpaceX)
POOL_SYMBOLS = [
    # 半导体 (7)
    'NVDA','AVGO','AMD','MU','LRCX','ARM','LITE',
    # 互联网/平台 (2)
    'NFLX','GOOGL',
    # 软件/SaaS (3)
    'NOW','CRWD','ORCL',
    # AI/数据 (2)
    'DDOG','SNPS',
    # 网络安全 (3)
    'PANW','ZS','NET',
    # 能源 (2)
    'EOG','OKE',
    # 材料/矿业 (2)
    'NEM','FCX',
    # 工业/国防 (3)
    'CAT','GE','RTX',
    # REITs (1)
    'AMT',
    # 新赛道 (3)
    'IONQ','RKLB','SPCX',
]

PARAMS = {
    'lookback_days': 25, 'holdings_num': 7, 'min_money': 500,
    'enable_profit_protection': False,
    'profit_protection_lookback': 1, 'profit_protection_threshold': 0.05,
}
MIN_HISTORY_DAYS = 126  # 最小历史天数(约半年), 过滤IPO初期噪声 (2026-07-01落地)

print("=" * 60)
print(f"  {STRATEGY_NAME} 回测")
print(f"  区间: {START_DATE} ~ {END_DATE}")
print("=" * 60)

# ============================================================
# Step 1: 加载本地数据
# ============================================================
print(f"\n加载本地美股数据...")
all_data = {}
missing = []

for sym in POOL_SYMBOLS:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists():
        missing.append(sym)
        continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={
            'Date': 'date', 'Open': 'open', 'High': 'high',
            'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        })
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        # 筛选回测区间
        mask = (df.index >= START_DATE) & (df.index <= END_DATE)
        df = df[mask]
        if len(df) >= 25:
            all_data[sym] = df
        else:
            missing.append(sym)
    except Exception:
        missing.append(sym)

print(f"  有效: {len(all_data)} 只, 缺失: {len(missing)} 只")
if missing:
    print(f"  缺失列表: {missing}")

if len(all_data) < 20:
    print(f"[FATAL] 数据不足: {len(all_data)}只")
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
    def __init__(self, cash=10000, comm_per_share=0.005, slippage=0.0005):
        self.initial_cash = cash
        self.cash = cash
        self.comm = comm_per_share
        self.slippage = slippage  # 滑点: 0.05% 买卖价差
        self.positions = {}
        self.trade_log = []
        self.daily_values = []
    
    @property
    def total_value(self):
        pv = sum(p['shares'] * p.get('last_price', p['cost_price'])
                 for p in self.positions.values())
        return self.cash + pv
    
    def update_prices(self, pdict):
        for c, p in pdict.items():
            if c in self.positions:
                self.positions[c]['last_price'] = p
    
    def buy(self, code, shares, price, date, reason=''):
        price = price * (1 + self.slippage)  # 买入滑点: 实际成交价略高于收盘价
        tv = shares * price
        comm = shares * self.comm
        total = tv + comm
        if total > self.cash + 0.01:
            return False
        self.cash -= total
        if code in self.positions:
            o = self.positions[code]
            ts = o['shares'] + shares
            self.positions[code] = {
                'shares': ts,
                'cost_price': (o['shares']*o['cost_price'] + shares*price)/ts,
                'last_price': price, 'buy_date': o.get('buy_date', date)
            }
        else:
            self.positions[code] = {
                'shares': shares, 'cost_price': price,
                'last_price': price, 'buy_date': date
            }
        self.trade_log.append({
            'date': str(date)[:10], 'code': code, 'name': code,
            'action': 'BUY', 'price': round(price, 4),
            'shares': int(shares), 'amount': round(tv, 2),
            'commission': round(comm, 2), 'reason': reason,
        })
        return True
    
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions:
            return False
        price = price * (1 - self.slippage)  # 卖出滑点: 实际成交价略低于收盘价
        pos = self.positions[code]
        actual = min(shares, pos['shares'])
        if actual <= 0:
            return False
        tv = actual * price
        comm = actual * self.comm
        self.cash += tv - comm
        pos['shares'] -= actual
        pnl = (price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares'] <= 0:
            del self.positions[code]
        self.trade_log.append({
            'date': str(date)[:10], 'code': code, 'name': code,
            'action': 'SELL', 'price': round(price, 4),
            'shares': int(actual), 'amount': round(tv, 2),
            'commission': round(comm, 2), 'pnl_pct': round(pnl, 4),
            'reason': reason,
        })
        return True
    
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions:
            return False
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
    return ann * r2, ann


def check_pp(code, cp, df, date, params):
    if not params.get('enable_profit_protection'):
        return False
    try:
        mask = df.index < pd.Timestamp(date)
        hist = df[mask]
        if len(hist) < params.get('profit_protection_lookback', 1):
            return False
        mx = hist['high'].tail(params['profit_protection_lookback']).max()
        return mx > 0 and cp <= mx * (1 - params.get('profit_protection_threshold', 0.05))
    except:
        return False


def get_ranked(all_data, prices, date, params):
    """动量排名：仅使用 date 之前（不含当日）的收盘数据，次日收盘调仓"""
    ranked = []
    lb = params['lookback_days']
    for code, df in all_data.items():
        if code not in prices:
            continue
        # 修复: < date (排除当日收盘价) — 用前一日数据计算动量，当日收盘价交易
        mask = df.index < pd.Timestamp(date)
        hist = df[mask]
        if len(hist) < max(lb + 10, MIN_HISTORY_DAYS):
            continue
        cp = prices[code]
        if cp <= 0:
            continue
        score, ann = calc_score(hist['close'].values, lb)
        filtered = check_pp(code, cp, df, date, params)
        ranked.append({
            'code': code, 'score': score, 'annualized': ann,
            'price': cp, 'filtered': filtered,
            'reasons': ['盈利保护'] if filtered else []
        })
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


# ============================================================
# Step 4: 执行回测
# ============================================================
pf = USPortfolio(cash=10000)
hn = PARAMS['holdings_num']

print(f"\n回测中: {len(trade_dates)} 天 | $10,000")
print("-" * 60)

for i, td in enumerate(trade_dates):
    tds = pd.Timestamp(td)
    prices = {}
    for code, df in all_data.items():
        m = df.index <= tds
        if m.any():
            prices[code] = float(df.loc[m, 'close'].iloc[-1])
    pf.update_prices(prices)
    
    # 盈利保护
    if PARAMS['enable_profit_protection']:
        for code in list(pf.get_position_codes()):
            if code in all_data and code in prices:
                if check_pp(code, prices[code], all_data[code], td, PARAMS):
                    pf.sell_all(code, prices[code], td, reason='盈利保护')
    
    ranked = get_ranked(all_data, prices, td, PARAMS)
    if not ranked:
        pf.record_daily_value(td)
        continue
    
    targets = [r['code'] for r in ranked if not r['filtered']][:hn]
    if not targets:
        for code in list(pf.get_position_codes()):
            if code in prices:
                pf.sell_all(code, prices[code], td, reason='调出(无目标)')
        pf.record_daily_value(td)
        continue
    
    for code in list(pf.get_position_codes()):
        if code not in targets and code in prices:
            pf.sell_all(code, prices[code], td, reason='调出目标')
    
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
    if i % 30 == 0:
        top3 = ", ".join([f"{r['code']}({r['score']:.4f})" for r in ranked[:3]])
        print(f'  [{td}] Top3: {top3} | ${pf.total_value:,.0f}')

# ============================================================
# Step 5: 生成结果
# ============================================================
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
losses = [t for t in st if t['pnl_pct']<=0]
wr = len(wins)/len(st)*100 if st else 0
aw = sum(t['pnl_pct'] for t in wins)/len(wins)*100 if wins else 0
al = sum(t['pnl_pct'] for t in losses)/len(losses)*100 if losses else 0

# 胜者榜/Top10
st_sorted = sorted(st, key=lambda x: x['pnl_pct'], reverse=True)
top10_wins = st_sorted[:10]
top10_losses = st_sorted[-10:][::-1]

print(f"\n{'='*60}")
print(f"  Top10 盈利交易")
print(f"{'='*60}")
for t in top10_wins:
    print(f"  {t['name']:6s} {t['date']} {t['pnl_pct']*100:+.2f}%  {t.get('reason','')}")

print(f"\n{'='*60}")
print(f"  Top10 亏损交易")
print(f"{'='*60}")
for t in top10_losses:
    print(f"  {t['name']:6s} {t['date']} {t['pnl_pct']*100:+.2f}%  {t.get('reason','')}")

# 按标的统计盈亏
by_symbol = {}
for t in st:
    s = t['code']
    if s not in by_symbol:
        by_symbol[s] = {'count': 0, 'wins': 0, 'total_pnl': 0}
    by_symbol[s]['count'] += 1
    if t['pnl_pct'] > 0:
        by_symbol[s]['wins'] += 1
    by_symbol[s]['total_pnl'] += t['pnl_pct'] * 100

print(f"\n{'='*60}")
print(f"  按标的统计 (交易次数Top15)")
print(f"{'='*60}")
for s, d in sorted(by_symbol.items(), key=lambda x: x[1]['count'], reverse=True)[:15]:
    avg = d['total_pnl'] / d['count'] if d['count'] > 0 else 0
    wr_s = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
    print(f"  {s:6s} {d['count']:3d}笔 胜率{wr_s:5.1f}% 累计{d['total_pnl']:+.1f}% 均{avg:+.2f}%")

results = {
    'strategy': STRATEGY_NAME,
    'backtest_period': f'{trade_dates[0]} ~ {trade_dates[-1]}',
    'trading_days': len(trade_dates),
    'initial_cash': pf.initial_cash,
    'final_value': round(fv,2),
    'total_return_pct': round(tr*100,2),
    'annualized_return_pct': round(tr*252/len(trade_dates)*100,2),
    'max_drawdown_pct': round(mdd*100,2),
    'sharpe_ratio': round(sh,4),
    'calmar_ratio': round(cm,4),
    'total_trades': len(trades), 'buy_trades': buys, 'sell_trades': sells,
    'win_rate_pct': round(wr,2),
    'avg_win_pct': round(aw,2),
    'avg_loss_pct': round(al,2),
    'daily_values': dv, 'trade_log': trades,
}

print(f"\n{'='*60}")
print(f"回测结果: {STRATEGY_NAME}")
print(f"{'='*60}")
print(f"  区间: {results['backtest_period']} ({results['trading_days']}天)")
print(f"  初始: ${results['initial_cash']:,.0f} -> 最终: ${results['final_value']:,.2f}")
print(f"  总收益: {results['total_return_pct']:+.2f}%  年化: {results['annualized_return_pct']:.2f}%")
print(f"  最大回撤: {results['max_drawdown_pct']:.2f}%  夏普: {results['sharpe_ratio']:.4f}  卡尔马: {results['calmar_ratio']:.4f}")
print(f"  交易: {results['total_trades']}次 (买{buys}/卖{sells})  胜率: {wr:.1f}%")
if wins: print(f"  平均盈利: +{aw:.2f}%")
if losses: print(f"  平均亏损: {al:.2f}%")
print(f"{'='*60}")

# 保存JSON
with open(OUTPUT_DIR / 'trades_us100.json', 'w', encoding='utf-8') as f:
    json.dump(trades, f, ensure_ascii=False, indent=2, default=str)
summary = {k:v for k,v in results.items() if k not in ('daily_values','trade_log')}
summary['daily_values'] = dv
with open(OUTPUT_DIR / 'summary_us100.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

# ============================================================
# Step 6: 生成报告 (QMT风格)
# ============================================================
now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
now_tag = datetime.now().strftime('%Y%m%d_%H%M')

trades_rows = ""
for t in trades[-50:]:
    d = '买入' if t['action']=='BUY' else '卖出'
    pnl = t.get('pnl_pct', None)
    ps = f'{pnl*100:+.2f}%' if pnl is not None else '-'
    bg = '#E2EFDA' if t['action']=='BUY' else '#FCE4D6'
    pc = '#28A745' if (pnl and pnl>0) else ('#DC3545' if (pnl and pnl<0) else '#888')
    trades_rows += f"""<tr style="background:{bg};">
        <td>{t['date']}</td><td style="font-weight:bold;">{d}</td><td>{t['name']}</td>
        <td style="text-align:right;">{t['price']:.4f}</td><td style="text-align:right;">{t.get('shares',0)}</td>
        <td style="text-align:right;">${t.get('amount',0):,.2f}</td>
        <td style="font-size:11px;color:#555;">{t.get('reason','')}</td>
        <td style="text-align:right;font-weight:bold;color:{pc};">{ps}</td></tr>"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{STRATEGY_NAME}</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:920px;margin:0 auto;padding:20px;background:#f8f9fa;}}
h1{{font-size:24px;color:#1F4E79;text-align:center;margin:0 0 5px;}}
.subtitle{{text-align:center;font-size:13px;color:#888;margin-bottom:25px;}}
.card{{background:#fff;padding:15px 20px;border-radius:8px;margin-bottom:15px;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.config-box{{background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:15px;font-size:13px;}}
.metrics-row{{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;}}
.metric-card{{flex:1;min-width:175px;background:#fff;padding:15px;border-radius:8px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.metric-label{{font-size:12px;color:#888;margin-bottom:6px;}}
.metric-value{{font-size:20px;font-weight:bold;color:#1F4E79;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#1F4E79;color:#fff;padding:8px;text-align:left;}}
td{{padding:6px 8px;border-bottom:1px solid #eee;}}
.footer{{text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;}}
</style></head><body>
<h1>{STRATEGY_NAME} · 回测报告</h1>
<div class="subtitle">{now_str} | {results['backtest_period']} ({results['trading_days']}天)</div>
<div class="config-box">
    <b>策略:</b> 七星美股版 | <b>成分股:</b> Nasdaq100 ({len(all_data)}只有效) | <b>周期:</b> 25日 | <b>佣金:</b> $0.005/股 | <b>滑点:</b> 0.05%<br>
    <b>过滤:</b> 盈利保护(开·回撤>5%) | 成交量(关) | 短期动量(关) | 动量计算排除当日收盘价(防未来函数)
    | 评分公式: exp(slope x 250) x R² (与七星172/QMT完全一致)
</div>
<div class="card"><h3 style="font-size:15px;color:#1F4E79;margin:0 0 12px;">回测绩效 (USD)</h3>
<div class="metrics-row">
    <div class="metric-card" style="background:{'#E8F5E9' if tr>0 else '#FFEBEE'}">
        <div class="metric-label">总收益率</div><div class="metric-value" style="color:{'#2E7D32' if tr>0 else '#C62828'}">{tr:+.2f}%</div></div>
    <div class="metric-card"><div class="metric-label">年化收益</div><div class="metric-value">{results['annualized_return_pct']:.2f}%</div></div>
    <div class="metric-card"><div class="metric-label">最大回撤</div><div class="metric-value">{results['max_drawdown_pct']:.2f}%</div></div>
    <div class="metric-card"><div class="metric-label">夏普比率</div><div class="metric-value">{results['sharpe_ratio']:.4f}</div></div>
</div>
<div class="metrics-row">
    <div class="metric-card"><div class="metric-label">初始资金</div><div class="metric-value">${results['initial_cash']:,.0f}</div></div>
    <div class="metric-card"><div class="metric-label">最终资产</div><div class="metric-value">${results['final_value']:,.2f}</div></div>
    <div class="metric-card"><div class="metric-label">胜率</div><div class="metric-value">{results['win_rate_pct']:.1f}%</div></div>
    <div class="metric-card"><div class="metric-label">总交易</div><div class="metric-value">{results['total_trades']}次(买{buys}/卖{sells})</div></div>
</div></div>
<div class="card"><h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px;">交易记录 (最近50条)</h3>
<div style="overflow-x:auto;"><table>
<tr><th>日期</th><th>方向</th><th>标的</th><th>价格</th><th>数量</th><th>金额</th><th>理由</th><th>盈亏</th></tr>
{trades_rows}</table></div></div>
<div class="footer">{STRATEGY_NAME} · Blakever Trade · {now_str}<br>本报告仅供研究参考，不构成投资建议。</div>
</body></html>"""

# Markdown
tmd = ""
for t in trades[-50:]:
    d = '买入' if t['action']=='BUY' else '卖出'
    pnl = t.get('pnl_pct', None)
    ps = f'{pnl*100:+.2f}%' if pnl is not None else '-'
    tmd += f"| {t['date']} | {d} | {t['name']} | ${t['price']:.4f} | {t.get('shares',0)} | ${t.get('amount',0):,.2f} | {t.get('reason','')} | {ps} |\n"

md = f"""# {STRATEGY_NAME} 回测报告 - {now_str}

## 策略配置
- **成分股**: Nasdaq100 ({len(all_data)}只有效, 7只缺失)
- **回测区间**: {results['backtest_period']} ({results['trading_days']}天)
- **佣金**: $0.005/股 | **周期**: 25日
- **过滤**: 盈利保护(开) | 成交量(关) | 短期动量(关)
- **评分**: exp(slope x 250) x R² (与七星172/QMT完全一致)

## 回测绩效 (USD)

| 指标 | 数值 |
|------|------|
| 初始资金 | ${results['initial_cash']:,.0f} |
| 最终资产 | ${results['final_value']:,.2f} |
| 总收益率 | {tr:+.2f}% |
| 年化收益 | {results['annualized_return_pct']:.2f}% |
| 最大回撤 | {results['max_drawdown_pct']:.2f}% |
| 夏普比率 | {results['sharpe_ratio']:.4f} |
| 卡尔马比率 | {results['calmar_ratio']:.4f} |
| 总交易 | {results['total_trades']} (买{buys}/卖{sells}) |
| 胜率 | {results['win_rate_pct']:.1f}% |
| 平均盈利 | +{results['avg_win_pct']:.2f}% |
| 平均亏损 | {results['avg_loss_pct']:.2f}% |

## 交易记录

| 日期 | 方向 | 标的 | 价格 | 数量 | 金额 | 理由 | 盈亏 |
|------|------|------|------|------|------|------|------|
{tmd}
---
*{STRATEGY_NAME} · Blakever Trade · {now_str}*
"""

html_path = OUTPUT_DIR / f'{STRATEGY_NAME}_回测报告_{now_tag}.html'
md_path = OUTPUT_DIR / f'{STRATEGY_NAME}_回测报告_{now_tag}.md'
with open(html_path, 'w', encoding='utf-8') as f: f.write(html)
with open(md_path, 'w', encoding='utf-8') as f: f.write(md)
print(f'\n报告已生成:')
print(f'  HTML: {html_path}')
print(f'  MD:   {md_path}')

# ============================================================
# Step 7: 发送邮件
# ============================================================
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

msg = MIMEMultipart("mixed")
msg["Subject"] = f"[回测报告] {STRATEGY_NAME} - {now_tag}"
msg["From"] = "848786642@qq.com"
msg["To"] = "848786642@qq.com"
msg.attach(MIMEText(html, "html", "utf-8"))
with open(md_path, 'r', encoding='utf-8') as f:
    att = MIMEText(f.read(), "plain", "utf-8")
    att.add_header("Content-Disposition", "attachment", filename=os.path.basename(md_path))
    msg.attach(att)

try:
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
        s.login("848786642@qq.com", "ljbtvacrctjobfed")
        s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
    print(f'[OK] 邮件已发送到 848786642@qq.com')
except Exception as e:
    print(f'[FAIL] 邮件发送失败: {e}')

print(f"\n{'='*60}")
print(f"  全部完成!")
print(f"{'='*60}")
