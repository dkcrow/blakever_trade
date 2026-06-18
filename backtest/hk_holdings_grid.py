#!/usr/bin/env python3
"""七星港股版 持股数网格回测 (1/2/3/4/5只)"""
import sys, os, warnings, json
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

NOW = datetime.now()
END_DATE = NOW.strftime('%Y-%m-%d')
START_DATE = '2025-01-01'

# 港股池 (44只)
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

HK_COMM_RATE = 0.001
HK_STAMP_DUTY = 0.0013
HK_TRADE_FEE = 0.0000565
SLIPPAGE = 0.001
CASH = 1000000
DATA_DIR = Path('data/storage/stock_data/hk')

# ================================================================
# 数据加载
# ================================================================
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
print(f'数据加载: {len(all_data)}只 | 交易日: {len(trade_dates)}天 | {START_DATE} ~ {END_DATE}')
print(f'{"="*85}')

# ================================================================
# 动量评分
# ================================================================
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
        if len(hist) < 35: continue
        cp = prices[code]
        if cp <= 0: continue
        score = calc_score(hist['close'].values[-25:])
        ranked.append({'code': code, 'score': score, 'price': cp})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

# ================================================================
# 投资组合
# ================================================================
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
        comm = max(tv * HK_COMM_RATE, 5)
        trade_fee = tv * HK_TRADE_FEE
        total = tv + comm + trade_fee
        if total > s.cash + 0.01: return False
        s.cash -= total
        if code in s.positions:
            o = s.positions[code]; ts = o['shares'] + shares
            s.positions[code] = {'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*p)/ts,'last_price':p,'buy_date':o.get('buy_date',date)}
        else:
            s.positions[code] = {'shares':shares,'cost_price':p,'last_price':p,'buy_date':date}
        s.trade_log.append({'date':date,'action':'BUY','code':code,'shares':int(shares),
                            'price':round(p,4),'reason':reason})
        return True
    def sell(s, code, shares, price, date, reason=''):
        if code not in s.positions: return False
        p = price * (1 - SLIPPAGE); pos = s.positions[code]
        a = min(shares, pos['shares'])
        tv = a * p
        comm = max(tv * HK_COMM_RATE, 5)
        stamp = tv * HK_STAMP_DUTY
        trade_fee = tv * HK_TRADE_FEE
        s.cash += tv - comm - stamp - trade_fee
        pnl = (p - pos['cost_price']) / pos['cost_price'] * 100
        s.trade_log.append({'date':date,'action':'SELL','code':code,'shares':int(a),
                            'price':round(p,4),'pnl_pct':round(pnl,2),'reason':reason})
        if a >= pos['shares']: del s.positions[code]
        else: s.positions[code]['shares'] -= a
        return True
    def get_position_codes(s):
        return list(s.positions.keys())

# ================================================================
# 回测循环
# ================================================================
def run_backtest(hn):
    pf = HKPortfolio()
    for date_idx, date in enumerate(trade_dates):
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])

        if len(prices) < hn: continue

        ranked = get_ranked(prices, date)
        current_targets = [r for r in ranked[:hn] if r['score'] > -999]
        target_codes = set(r['code'] for r in current_targets)
        current_codes = set(pf.get_position_codes())

    to_sell = current_codes - target_codes
    for code in to_sell:
        sell_price = prices.get(code, 0)
        if sell_price <= 0:
            sell_price = pf.positions[code].get('last_price', 0)
        if sell_price <= 0:
            sell_price = pf.positions[code].get('cost_price', 0)
        if sell_price > 0:
            pf.sell(code, pf.positions[code]['shares'], sell_price, d_str, '调出')
        elif code not in prices:
            pf.sell(code, pf.positions[code]['shares'], pf.positions[code].get('cost_price', 1), d_str, '数据缺失_按成本清仓')

        total_val = pf.total_value
        pf.update_prices(prices)
        for r in current_targets:
            if r['code'] in pf.positions: continue
            if r['code'] not in prices: continue
            per_stock = total_val * 0.95 / hn
            shares = int(per_stock / r['price'] / 100) * 100
            if shares >= 100:
                pf.buy(r['code'], shares, r['price'], d_str, '')

        pf.daily_values.append({'date': d_str, 'value': pf.total_value})

        if date_idx % 100 == 0:
            print(f'  [{hn}只] {d_str} | HK$ {pf.total_value:,.0f}', flush=True)

    dv = pd.DataFrame(pf.daily_values)
    tr_total = (dv['value'].iloc[-1] / CASH - 1) * 100
    daily_ret = dv['value'].pct_change().dropna()
    ann_ret = (dv['value'].iloc[-1] / CASH) ** (252 / max(len(daily_ret), 1)) - 1
    max_dd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0

    sells = [t for t in pf.trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl_pct',0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    n_trades = len(pf.trade_log)

    return {
        'holdings': hn,
        'total_return': round(tr_total, 2),
        'annual_return': round(ann_ret * 100, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'win_rate': round(wr, 1),
        'final_value': pf.total_value,
        'n_trades': n_trades,
        'n_trading_days': len(trade_dates),
    }

# ================================================================
# 主循环
# ================================================================
results = []
for hn in [1, 2, 3, 4, 5]:
    print(f'\n>>> 回测 持股{hn}只...')
    r = run_backtest(hn)
    results.append(r)
    print(f'  完成: 总收益 {r["total_return"]:+.1f}% | 年化 {r["annual_return"]:+.1f}% | 回撤 {r["max_drawdown"]:.1f}% | 夏普 {r["sharpe"]:.2f}')

# ================================================================
# 输出表格
# ================================================================
print(f'\n{"="*90}')
print(f'{"七星港股版 持股数网格回测结果":^80}')
print(f'{START_DATE} ~ {END_DATE} | 44只池 | 25日动量 | 港币100万 | 日频调仓')
print(f'{"="*90}')
print(f'{"持有":>4} | {"总收益%":>9} | {"年化%":>8} | {"最大回撤%":>8} | {"夏普":>6} | {"胜率%":>6} | {"交易笔数":>7} | {"终值(HK$)":>14}')
print(f'{"-"*90}')
for r in results:
    print(f'{r["holdings"]:>4} | {r["total_return"]:>+8.1f} | {r["annual_return"]:>+7.1f} | {r["max_drawdown"]:>8.1f} | {r["sharpe"]:>6.2f} | {r["win_rate"]:>5.1f} | {r["n_trades"]:>7} | {r["final_value"]:>14,.0f}')
print(f'{"="*90}')

# 最佳持股数
best = max(results, key=lambda x: x['annual_return'])
print(f'\n最佳持股数: {best["holdings"]}只 (年化 {best["annual_return"]:+.1f}%)')

# 保存JSON
json_path = f'backtest/results_hk/holdings_grid_{NOW.strftime("%Y%m%d")}.json'
os.makedirs('backtest/results_hk', exist_ok=True)
with open(json_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f'结果已保存: {json_path}')
