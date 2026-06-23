#!/usr/bin/env python3
"""七星港股版 空仓机制(动量门槛)网格回测
当前阈值=0.5; 测试提高到 0.6/0.8/1.0/1.2 — 弱市时门槛越高越倾向空仓持币。
引擎与 hk_live_report.py 完全一致: (exp-1)×R² + 线性加权linspace(1,2), 37池, 5只等权, 港股费率。
阈值同时作用买入门槛与持有卖出门槛(跌破即卖)。额外统计空仓占比/平均持仓/平均现金占比。
"""
import warnings
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

HK_POOL = [
    '00700','09988','01810','03690','09999',
    '02513','00100',
    '02162','02616','09969',
    '02418','01357',
    '00981','01347','00522',
    '01211',
    '01093','01177',
    '02338','02038','01378',
    '00388','02388','00005','02318','00939','02628','03988',
    '09888',
    '00883','02899','03993',
    '02618',
    '01929',
    '01113','06181',
    '00669',
]
HOLDINGS_NUM = 5
HK_COMM_RATE = 0.001
HK_STAMP_DUTY = 0.0013
HK_TRADE_FEE = 0.0000565
SLIPPAGE = 0.001
CASH = 1000000
DATA_DIR = Path('data/storage/stock_data/hk')
START_DATE = '2023-06-18'
END_DATE = datetime.now().strftime('%Y-%m-%d')

all_data = {}
for code in HK_POOL:
    fp = DATA_DIR / f'hk{code}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 35:
            all_data[code] = df
trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    w = np.linspace(1, 2, len(x_m))
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = np.exp(slope * 250)
    fitted = slope * x_m + intercept
    res = y_m - fitted
    ss_res = np.sum(w * res**2); ss_tot = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return (ann - 1) * r2

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

class HKPortfolio:
    def __init__(s, cash=CASH):
        s.initial_cash = cash; s.cash = cash
        s.positions = {}; s.trade_log = []; s.daily_values = []
    @property
    def total_value(s):
        pv = sum(p['shares']*p.get('last_price', p['cost_price']) for p in s.positions.values())
        return s.cash + pv
    def update_prices(s, pdict):
        for c, p in pdict.items():
            if c in s.positions: s.positions[c]['last_price'] = p
    def buy(s, code, shares, price, date):
        p = price * (1 + SLIPPAGE); tv = shares * p
        comm = max(tv * HK_COMM_RATE, 5); trade_fee = tv * HK_TRADE_FEE
        total = tv + comm + trade_fee
        if total > s.cash + 0.01: return False
        s.cash -= total
        if code in s.positions:
            o = s.positions[code]; ts = o['shares'] + shares
            s.positions[code] = {'shares': ts, 'cost_price': (o['shares']*o['cost_price']+shares*p)/ts, 'last_price': p, 'buy_date': o.get('buy_date', date)}
        else:
            s.positions[code] = {'shares': shares, 'cost_price': p, 'last_price': p, 'buy_date': date}
        s.trade_log.append({'date': date, 'action': 'BUY', 'code': code})
        return True
    def sell(s, code, shares, price, date):
        if code not in s.positions: return False
        p = price * (1 - SLIPPAGE); pos = s.positions[code]
        a = min(shares, pos['shares']); tv = a * p
        comm = max(tv * HK_COMM_RATE, 5); stamp = tv * HK_STAMP_DUTY; trade_fee = tv * HK_TRADE_FEE
        s.cash += tv - comm - stamp - trade_fee
        pnl = (p - pos['cost_price']) / pos['cost_price'] * 100
        s.trade_log.append({'date': date, 'action': 'SELL', 'code': code, 'pnl_pct': round(pnl, 2)})
        if a >= pos['shares']: del s.positions[code]
        else: s.positions[code]['shares'] -= a
        return True
    def get_position_codes(s):
        return list(s.positions.keys())

def run(threshold):
    pf = HKPortfolio(); hn = HOLDINGS_NUM
    empty_days = 0; pos_count_sum = 0; cash_ratio_sum = 0; n_days = 0
    for i, date in enumerate(trade_dates):
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < hn: continue
        ranked = get_ranked(prices, date)
        current_targets = [r for r in ranked if r['score'] >= threshold][:hn]
        target_codes = set(r['code'] for r in current_targets)
        current_codes = set(pf.get_position_codes())
        to_sell = current_codes - target_codes
        for code in list(current_codes):
            found = next((r for r in ranked if r['code'] == code), None)
            if found and found['score'] < threshold: to_sell.add(code)
        for code in to_sell:
            sp = prices.get(code, 0)
            if sp <= 0: sp = pf.positions[code].get('last_price', 0)
            if sp <= 0: sp = pf.positions[code].get('cost_price', 0)
            if sp > 0: pf.sell(code, pf.positions[code]['shares'], sp, d_str)
            elif code not in prices: pf.sell(code, pf.positions[code]['shares'], pf.positions[code].get('cost_price', 1), d_str)
        pf.update_prices(prices)
        new_targets = [r for r in current_targets if r['code'] not in pf.positions and r['code'] in prices]
        if new_targets:
            available = pf.cash * 0.95; per = available / len(new_targets)
            for r in new_targets:
                shares = int(per / r['price'] / 100) * 100
                if shares >= 100: pf.buy(r['code'], shares, r['price'], d_str)
        tv = pf.total_value
        pf.daily_values.append({'date': d_str, 'value': tv})
        # 空仓/现金统计
        nh = len(pf.positions)
        if nh == 0: empty_days += 1
        pos_count_sum += nh
        cash_ratio_sum += (pf.cash / tv if tv > 0 else 1)
        n_days += 1
    dv = pd.DataFrame(pf.daily_values)
    tr = (dv['value'].iloc[-1] / CASH - 1) * 100
    dr = dv['value'].pct_change().dropna()
    ann = (dv['value'].iloc[-1] / CASH) ** (252 / max(len(dr), 1)) - 1
    dd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
    sh = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    sells = [t for t in pf.trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl_pct', 0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    return dict(thr=threshold, tr=tr, ann=ann*100, dd=dd, sh=sh, n=len(pf.trade_log), wr=wr,
                final=dv['value'].iloc[-1],
                empty_pct=empty_days/n_days*100,
                avg_pos=pos_count_sum/n_days,
                avg_cash=cash_ratio_sum/n_days*100)

print(f"数据: {len(all_data)}只 | 交易日: {len(trade_dates)}天 | "
      f"{trade_dates[0].strftime('%Y-%m-%d')} ~ {trade_dates[-1].strftime('%Y-%m-%d')}")
print("引擎: (exp-1)×R² 线性加权 | 5只等权 | 港股费率\n")

results = []
for thr in [0.5, 0.6, 0.8, 1.0, 1.2]:
    print(f"  回测 阈值={thr} ...")
    results.append(run(thr))

print("\n" + "="*108)
print(f"  {'阈值':<5}{'累计':>9}{'年化':>8}{'回撤':>8}{'夏普':>7}{'交易':>6}{'胜率':>6}{'空仓占比':>9}{'平均持仓':>9}{'平均现金':>9}  备注")
print("-"*108)
for r in results:
    note = '← 当前基线' if abs(r['thr']-0.5)<1e-9 else ''
    print(f"  {r['thr']:<5.1f}{r['tr']:>+8.1f}%{r['ann']:>7.1f}%{r['dd']:>7.1f}%{r['sh']:>7.2f}"
          f"{r['n']:>6d}{r['wr']:>5.0f}%{r['empty_pct']:>8.1f}%{r['avg_pos']:>9.2f}{r['avg_cash']:>8.1f}%  {note}")
print("="*108)

base = results[0]
print(f"\n相对基线(阈值0.5)差异:")
for r in results[1:]:
    print(f"  阈值{r['thr']}: 累计{r['tr']-base['tr']:+.1f}pp | 年化{r['ann']-base['ann']:+.1f}pp | "
          f"回撤{r['dd']-base['dd']:+.1f}pp | 夏普{r['sh']-base['sh']:+.2f} | "
          f"空仓占比{r['empty_pct']-base['empty_pct']:+.1f}pp | 现金占比{r['avg_cash']-base['avg_cash']:+.1f}pp")
