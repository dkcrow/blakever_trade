#!/usr/bin/env python3
"""七星美股版 5年基线回测 + 防御标的持仓分析"""
import pandas as pd, numpy as np, warnings
from pathlib import Path
from collections import Counter
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/us')
OUT_DIR = Path('backtest/results_us100')
OUT_DIR.mkdir(parents=True, exist_ok=True)

POOL = ['NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','AAPL','TSM','LITE',
    'META','AMZN','NFLX','GOOGL','MSFT','CRM','NOW','CRWD','ORCL',
    'PLTR','DDOG','SNPS','XOM','CVX','COP','EOG','OKE',
    'NEM','FCX','LIN','CAT','GE','RTX','PLD','AMT']

all_data = {}
for s in POOL:
    fp = DATA_DIR / f'{s}.csv'
    if fp.exists():
        df = pd.read_csv(fp); df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date').sort_index()
        if len(df) > 30:
            all_data[s] = df

print(f'Loaded {len(all_data)} symbols')

START = '2021-06-07'; END = '2026-06-05'
trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START <= d.strftime('%Y-%m-%d') <= END]
print(f'Trade dates: {trade_dates[0].strftime("%Y-%m-%d")} ~ {trade_dates[-1].strftime("%Y-%m-%d")}, {len(trade_dates)} days')

HOLDINGS = 7; CASH = 100000; COMM = 0.005; SLIPPAGE = 0.0005; LB = 25

def calc_score(closes, lookback):
    if len(closes) < lookback + 5: return -999, 0
    recent = closes[-lookback:]
    x = np.arange(lookback); y = np.log(recent)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999, 0
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = (np.exp(slope * 250) - 1) * 100
    res = y_m - (slope * x_m + np.polyfit(x_m, y_m, 1)[1])
    ss_res = np.sum(res**2); ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    score = np.exp(slope * 250) * r2
    return score, ann

def get_ranked(prices, date):
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index < pd.Timestamp(date); hist = df[mask]
        if len(hist) < LB + 10: continue
        cp = prices[code]
        if cp <= 0: continue
        score, ann = calc_score(hist['Close'].values, LB)
        ranked.append({'code':code, 'score':score, 'price':cp, 'ann_ret':ann})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

class Portfolio:
    def __init__(self, cash=100000):
        self.cash = cash; self.positions = {}; self.trades = []
    def buy(self, code, shares, price, date, reason=''):
        price = price * (1 + SLIPPAGE)
        tv = shares * price; comm = shares * COMM
        if tv + comm > self.cash: return False
        self.cash -= tv + comm
        if code in self.positions:
            o = self.positions[code]; ts = o['shares']+shares
            self.positions[code] = {'shares':ts, 'cost':(o['shares']*o['cost']+shares*price)/ts, 'buy_date':o['buy_date']}
        else:
            self.positions[code] = {'shares':shares, 'cost':price, 'buy_date':date}
        self.trades.append({'date':date, 'action':'BUY', 'code':code, 'shares':shares, 'price':price, 'reason':reason})
        return True
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        price = price * (1 - SLIPPAGE)
        pos = self.positions[code]; actual = min(shares, pos['shares'])
        tv = actual * price; comm = actual * COMM
        self.cash += tv - comm
        pnl = (price - pos['cost']) / pos['cost'] * 100
        self.trades.append({'date':date, 'action':'SELL', 'code':code, 'shares':actual, 'price':price, 'pnl_pct':pnl, 'reason':reason})
        if actual >= pos['shares']:
            del self.positions[code]
        else:
            self.positions[code]['shares'] -= actual
        return True
    def total_value(self, prices):
        pv = sum(p['shares']*prices.get(c, p['cost']) for c,p in self.positions.items())
        return self.cash + pv

# 运行
pf = Portfolio(CASH)
daily_values = []

for i, date in enumerate(trade_dates):
    d_str = date.strftime('%Y-%m-%d')
    prices = {}
    for code in all_data:
        h = all_data[code]
        m = h.index == date
        if m.any():
            prices[code] = h.loc[date, 'Close']
    if not prices: continue

    ranked = get_ranked(prices, date)
    if len(ranked) < HOLDINGS: continue

    targets = [r for r in ranked[:HOLDINGS] if r['score'] > -999]
    target_codes = set(r['code'] for r in targets)
    current_codes = set(pf.positions.keys())

    to_sell = current_codes - target_codes
    for code in to_sell:
        pf.sell(code, pf.positions[code]['shares'], prices[code], d_str, '调出Top7')

    if targets:
        per_stock = pf.total_value(prices) * 0.95 / len(targets)
        for r in targets:
            if r['code'] in pf.positions: continue
            shares = int(per_stock / r['price'])
            if shares > 0:
                pf.buy(r['code'], shares, r['price'], d_str, '动量轮换')

    daily_values.append({'date': d_str, 'value': pf.total_value(prices)})

# ===== 汇总 =====
dv = pd.DataFrame(daily_values)
total_ret = (dv['value'].iloc[-1] / CASH - 1) * 100
daily_ret = dv['value'].pct_change().dropna()
ann_ret = (1 + daily_ret.mean())**252 - 1
mdd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0

print(f'\n=== 5年基线回测 ===')
print(f'总收益: {total_ret:.2f}% | 年化: {ann_ret*100:.1f}% | 回撤: {mdd:.1f}% | 夏普: {sharpe:.2f}')
print(f'交易笔数: {len(pf.trades)} (买{sum(1 for t in pf.trades if t["action"]=="BUY")}/卖{sum(1 for t in pf.trades if t["action"]=="SELL")})')

# ===== 板块分类 =====
sector_map = {
    '半导体': ['NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','TSM','LITE'],
    '科技大盘': ['AAPL','META','AMZN','NFLX','GOOGL','MSFT'],
    '软件/SaaS': ['CRM','NOW','CRWD','ORCL','PLTR','DDOG','SNPS'],
    '能源': ['XOM','CVX','COP','EOG','OKE'],
    '矿业/材料': ['NEM','FCX','LIN'],
    '工业/国防': ['CAT','GE','RTX'],
    '房地产/基建': ['PLD','AMT'],
}
code_sector = {}
for sec, codes in sector_map.items():
    for c in codes: code_sector[c] = sec

buy_sectors = Counter()
sell_sectors = Counter()
for t in pf.trades:
    sec = code_sector.get(t['code'], '未知')
    if t['action'] == 'BUY': buy_sectors[sec] += 1
    else: sell_sectors[sec] += 1

print(f'\n=== 板块交易统计 ===')
print(f'{"板块":<15} {"买入":>5} {"卖出":>5} {"占比(买)":>8}')
total_buy = sum(buy_sectors.values())
for sec in sorted(buy_sectors.keys()):
    pct = buy_sectors[sec] / total_buy * 100 if total_buy > 0 else 0
    print(f'{sec:<15} {buy_sectors[sec]:>5} {sell_sectors[sec]:>5} {pct:>7.1f}%')

# ===== 防御/价值标的持有分析 =====
defensive_codes = ['XOM','CVX','COP','EOG','OKE','NEM','FCX','LIN','PLD','AMT','RTX','CAT','GE']

# 重建持仓时间线
all_trade_dates = sorted(set(t['date'] for t in pf.trades))
current_holds = set()
holdings_snapshot = {}  # date -> set of codes held

for d_str in all_trade_dates:
    for t in pf.trades:
        if t['date'] == d_str:
            if t['action'] == 'BUY':
                current_holds.add(t['code'])
            elif t['action'] == 'SELL':
                current_holds.discard(t['code'])
    holdings_snapshot[d_str] = current_holds.copy()

# 找防御持仓段
def_segments = []
seg_start = None; seg_holds = set()

for d_str in all_trade_dates:
    holds = holdings_snapshot[d_str]
    def_in = holds & set(defensive_codes)
    if def_in and seg_start is None:
        seg_start = d_str; seg_holds = def_in.copy()
    elif def_in and seg_start:
        seg_holds |= def_in
    elif not def_in and seg_start:
        def_segments.append({'start': seg_start, 'end': d_str, 'holds': sorted(seg_holds)})
        seg_start = None; seg_holds = set()

if seg_start:
    def_segments.append({'start': seg_start, 'end': all_trade_dates[-1], 'holds': sorted(seg_holds)})

print(f'\n=== 防御/价值型标的持有 ====================')
print(f'定义: 能源(XOM CVX COP EOG OKE) + 矿业(NEM FCX) + 工业(CAT GE RTX) + 材料(LIN) + REIT(PLD AMT)')
print(f'共 {len(def_segments)} 段出现防御持仓:')
print()

total_def_trade_days = 0
for i, seg in enumerate(def_segments):
    start_d = pd.to_datetime(seg['start']); end_d = pd.to_datetime(seg['end'])
    days = (end_d - start_d).days
    total_def_trade_days += days
    
    # 这段时间持有的防御标的
    holds_str = ', '.join(seg['holds'])
    
    # 这段时间同时持有的所有标的
    all_holds = set()
    for h in seg['holds']:
        all_holds.add(h)
    # 还要看进攻标的
    for d_str in all_trade_dates:
        if seg['start'] <= d_str <= seg['end']:
            all_holds |= holdings_snapshot[d_str]
    
    # 防御标的在这段里的卖出盈亏
    def_pnls = []
    for t in pf.trades:
        if t['action'] == 'SELL' and seg['start'] <= t['date'] <= seg['end']:
            if t['code'] in defensive_codes:
                def_pnls.append((t['code'], t.get('pnl_pct', 0)))
    
    pnl_summary = ''
    if def_pnls:
        pnl_strs = [f'{c}({p:+.1f}%)' for c,p in def_pnls]
        pnl_summary = f' 盈亏: ' + ', '.join(pnl_strs)
    else:
        # 可能还在持有，算浮动盈亏
        pass
    
    print(f'  [{i+1}] {seg["start"]} ~ {seg["end"]} ({days}天)')
    print(f'      防御持仓: {holds_str}{pnl_summary}')
    
    unique_full = set()
    for d_str in all_trade_dates:
        if seg['start'] <= d_str <= seg['end']:
            unique_full |= holdings_snapshot.get(d_str, set())
    print(f'      全仓: {", ".join(sorted(unique_full))}')
    print()

print(f'防御持仓累计交易日: {total_def_trade_days} / {len(all_trade_dates)} ({total_def_trade_days/len(all_trade_dates)*100:.1f}%)')

# ===== 保存交易日志 =====
trades_df = pd.DataFrame(pf.trades)
trades_df.to_csv(OUT_DIR / 'us_5y_baseline_trades.csv', index=False)
print(f'交易日志: us_5y_baseline_trades.csv ({len(trades_df)}行)')

# ===== 防御标的首次买入时间 =====
print(f'\n=== 防御标的首次买入 ===')
first_def_buy = {}
for t in pf.trades:
    if t['action'] == 'BUY' and t['code'] in defensive_codes and t['code'] not in first_def_buy:
        first_def_buy[t['code']] = t['date']
for code in sorted(first_def_buy.keys()):
    print(f'  {code}: {first_def_buy[code]}')

print(f'\nDone.')
