#!/usr/bin/env python3
"""七星港股版 score>=0.5 + 持股数网格 (1-7只)"""
import warnings; warnings.filterwarnings('ignore')
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd

NOW = datetime.now()
END_DATE = NOW.strftime('%Y-%m-%d')
START_DATE = '2025-01-01'

HK_POOL = [
    '00700','09988','01810','03690','09999',
    '02513','00100',
    '02162','02616','09688','09969',
    '02418','00992','01357',
    '00981','01347','00522',
    '01211','00175',
    '03692','01093','01177',
    '02338','02038','01378',
    '00388','02388','00005','02318','00939','02628','03988',
    '09888',
    '00883','02899','03993',
    '02618','02057',
    '09633','01929','06690',
    '01113','06181',
    '00669',
]

SCORE_THRESHOLD = 0.5
HK_COMM_RATE = 0.001; HK_STAMP_DUTY = 0.0013; HK_TRADE_FEE = 0.0000565
SLIPPAGE = 0.001; CASH = 1000000; DATA_DIR = Path('data/storage/stock_data/hk')

# Load
all_data = {}
for code in HK_POOL:
    fp = DATA_DIR / f'hk{code}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 35: all_data[code] = df

trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]
print(f'数据: {len(all_data)}只 | {len(trade_dates)}天 | score>={SCORE_THRESHOLD}')

def calc_score(closes):
    if len(closes) < 5: return -999
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

def get_ranked(prices, date):
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index < pd.Timestamp(date); hist = df[mask]
        if len(hist) < 25: continue
        cp = prices[code]
        if cp <= 0: continue
        score = calc_score(hist['close'].values[-25:])
        ranked.append({'code': code, 'score': score, 'price': cp})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

class HKPortfolio:
    def __init__(s, cash=CASH):
        s.initial_cash = cash; s.cash = cash
        s.positions = {}; s.trade_log = []; s.daily_values = []
    @property
    def total_value(s):
        pv = sum(p['shares']*p.get('last_price',p['cost_price']) for p in s.positions.values())
        return s.cash + pv
    def update_prices(s, pdict):
        for c,p in pdict.items():
            if c in s.positions: s.positions[c]['last_price'] = p
    def buy(s, code, shares, price, date, reason=''):
        p = price * (1 + SLIPPAGE); tv = shares * p
        comm = max(tv * HK_COMM_RATE, 5); trade_fee = tv * HK_TRADE_FEE
        if tv + comm + trade_fee > s.cash + 0.01: return False
        s.cash -= tv + comm + trade_fee
        if code in s.positions:
            o = s.positions[code]; ts = o['shares'] + shares
            s.positions[code] = {'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*p)/ts,'last_price':p,'buy_date':o.get('buy_date',date)}
        else:
            s.positions[code] = {'shares':shares,'cost_price':p,'last_price':p,'buy_date':date}
        s.trade_log.append({'date':date,'action':'BUY','code':code,'shares':int(shares),'price':round(p,4),'reason':reason})
        return True
    def sell(s, code, shares, price, date, reason=''):
        if code not in s.positions: return False
        p = price * (1 - SLIPPAGE); pos = s.positions[code]
        a = min(shares, pos['shares']); tv = a * p
        comm = max(tv * HK_COMM_RATE, 5); stamp = tv * HK_STAMP_DUTY; trade_fee = tv * HK_TRADE_FEE
        s.cash += tv - comm - stamp - trade_fee
        pnl = (p - pos['cost_price']) / pos['cost_price'] * 100
        s.trade_log.append({'date':date,'action':'SELL','code':code,'shares':int(a),'price':round(p,4),'pnl_pct':round(pnl,2),'reason':reason})
        if a >= pos['shares']: del s.positions[code]
        else: s.positions[code]['shares'] -= a
        return True
    def get_position_codes(s):
        return list(s.positions.keys())

def run_backtest(hn, th):
    pf = HKPortfolio()
    for date in trade_dates:
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < 1: continue

        ranked = get_ranked(prices, date)
        qualified = [r for r in ranked if r['score'] >= th][:hn]
        target_codes = set(r['code'] for r in qualified)
        current_codes = set(pf.get_position_codes())

        to_sell = current_codes - target_codes
        for code in list(current_codes):
            found = next((r for r in ranked if r['code'] == code), None)
            if found and found['score'] < th:
                to_sell.add(code)
        for code in to_sell:
            sell_price = prices.get(code, 0)
            if sell_price <= 0: sell_price = pf.positions[code].get('last_price', 0)
            if sell_price <= 0: sell_price = pf.positions[code].get('cost_price', 0)
            if sell_price > 0:
                pf.sell(code, pf.positions[code]['shares'], sell_price, d_str, '得分不足/调出')
            elif code not in prices:
                pf.sell(code, pf.positions[code]['shares'], pf.positions[code].get('cost_price',1), d_str, '数据缺失')

        total_val = pf.total_value
        pf.update_prices(prices)
        n_qual = max(len(qualified), 1)
        for r in qualified:
            if r['code'] in pf.positions: continue
            if r['code'] not in prices: continue
            per_stock = total_val * 0.95 / n_qual
            shares = int(per_stock / r['price'] / 100) * 100
            if shares >= 100:
                pf.buy(r['code'], shares, r['price'], d_str, '')

        pf.daily_values.append({'date': d_str, 'value': pf.total_value})

    dv = pd.DataFrame(pf.daily_values)
    tr_total = (dv['value'].iloc[-1] / CASH - 1) * 100
    daily_ret = dv['value'].pct_change().dropna()
    ann_ret = (dv['value'].iloc[-1] / CASH) ** (252 / max(len(daily_ret), 1)) - 1
    max_dd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
    sells = [t for t in pf.trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl_pct',0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    # avg holdings
    holding_counts = []
    for d in pf.daily_values:
        day_positions = len(pf.positions) if hasattr(pf, '_day_pos') else 0
    avg_hold = n_qual  # approximate
    return {'holdings': hn, 'threshold': th,
            'total_return': round(tr_total,2), 'annual_return': round(ann_ret*100,2),
            'max_drawdown': round(max_dd,2), 'sharpe': round(sharpe,2),
            'win_rate': round(wr,1), 'final_value': pf.total_value,
            'n_trades': len(pf.trade_log)}

# Run grid
results = []
for hn in [1, 2, 3, 4, 5, 6, 7]:
    print(f'>>> 持股{hn}只...', end=' ', flush=True)
    r = run_backtest(hn, SCORE_THRESHOLD)
    results.append(r)
    print(f'年化{r["annual_return"]:+.1f}% | 回撤{r["max_drawdown"]:.1f}% | 夏普{r["sharpe"]:.2f} | 交易{r["n_trades"]}次')

print()
print("=" * 85)
print(f"score>={SCORE_THRESHOLD} + 持股数网格 ({START_DATE} ~ {END_DATE})")
print("=" * 85)
print(f"{'持有':>4} | {'年化%':>8} | {'回撤%':>7} | {'夏普':>6} | {'胜率%':>5} | {'交易':>5} | {'终值(HK$)':>14}")
print("-" * 85)
for r in results:
    print(f'{r["holdings"]:>4} | {r["annual_return"]:>+7.1f} | {r["max_drawdown"]:>7.1f} | {r["sharpe"]:>6.2f} | {r["win_rate"]:>5.1f} | {r["n_trades"]:>5} | {r["final_value"]:>14,.0f}')
print("=" * 85)

best = max(results, key=lambda x: x['annual_return'])
best_sharpe = max(results, key=lambda x: x['sharpe'])
print(f'\n年化最优: {best["holdings"]}只 (+{best["annual_return"]:.1f}%)')
print(f'夏普最优: {best_sharpe["holdings"]}只 ({best_sharpe["sharpe"]:.2f})')
