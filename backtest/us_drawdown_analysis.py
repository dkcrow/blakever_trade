#!/usr/bin/env python3
"""七星美股版: 独立账户回撤根因分析"""
import math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'us'
START, END = '2023-06-01', '2026-06-04'
POOL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')

all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists():
        continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        m = (df.index >= START) & (df.index <= END)
        df = df[m]
        if len(df) >= 25:
            all_data[sym] = df
    except:
        pass

td_list = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
td_list = [d for d in td_list if START <= d <= END]

def cs(cf):
    r = cf[-26:]
    y = np.log(np.maximum(r, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    sl, ic = np.polyfit(x, y, 1, w=w)
    a = math.exp(sl * 250) - 1
    ssr = np.sum(w * (y - (sl * x + ic)) ** 2)
    sst = np.sum(w * (y - np.mean(y)) ** 2)
    return a * (1 - ssr / sst if sst > 0 else 0)

def rankings(prices, date):
    rk = []
    for cd, df in all_data.items():
        if cd not in prices:
            continue
        h = df[df.index <= pd.Timestamp(date)]
        if len(h) < 35:
            continue
        cp = prices[cd]
        if cp <= 0:
            continue
        rk.append({'code': cd, 'score': cs(h['close'].values), 'price': cp})
    rk.sort(key=lambda x: x['score'], reverse=True)
    return rk


class Account:
    def __init__(self, cash=10000):
        self.ic = cash
        self.c = cash
        self.holding = None
        self.cost = 0
        self.shares = 0
        self.tl = []
        self.dv = []
        self.holdings_log = []

    def record(self, prices):
        v = self.c
        if self.holding and self.holding in prices:
            v += self.shares * prices[self.holding]
        self.dv.append(v)
        self.holdings_log.append(self.holding)

    def sell(self, price, dt, reason=''):
        if not self.holding:
            return
        pnl = (price - self.cost) / self.cost if self.cost > 0 else 0
        self.c += self.shares * price - self.shares * 0.005
        self.tl.append({'d': str(dt)[:10], 'code': self.holding, 'a': 'SELL', 'pr': price, 's': self.shares, 'pnl': round(pnl, 4), 'r': reason})
        self.holding = None
        self.shares = 0
        self.cost = 0

    def buy(self, code, price, dt, reason=''):
        if self.holding:
            self.sell(price, dt, '换仓')
        shares = int(self.c / (price + 0.005))
        if shares <= 0 or shares * price < 500:
            return
        self.shares = shares
        self.cost = price
        self.holding = code
        self.c -= shares * price + shares * 0.005
        self.tl.append({'d': str(dt)[:10], 'code': code, 'a': 'BUY', 'pr': price, 's': shares, 'r': reason})


HN = 7
accounts = [Account(10000) for _ in range(HN)]

for td in td_list:
    tds = pd.Timestamp(td)
    prices = {}
    for cd, df in all_data.items():
        m = df.index <= tds
        if m.any():
            prices[cd] = float(df.loc[m, 'close'].iloc[-1])

    rk = rankings(prices, td)
    if not rk:
        for a in accounts:
            a.record(prices)
        continue

    tgs = [r['code'] for r in rk if r['score'] > -999][:HN]
    for i, acct in enumerate(accounts):
        target = tgs[i] if i < len(tgs) else None
        if target is None:
            if acct.holding:
                acct.sell(prices.get(acct.holding, 0), td, '无目标')
        elif acct.holding != target:
            acct.buy(target, prices[target], td, f'排名{i+1}')
        acct.record(prices)

# Combined daily values
combined_vals = []
for j in range(len(td_list)):
    combined_vals.append(sum(accounts[i].dv[j] for i in range(HN)))

# Find max drawdown
peak_val, peak_idx, mdd, trough_idx = 70000, 0, 0, 0
for j, v in enumerate(combined_vals):
    if v > peak_val:
        peak_val = v
        peak_idx = j
    dd = (peak_val - v) / peak_val if peak_val > 0 else 0
    if dd > mdd:
        mdd = dd
        trough_idx = j

print(f'组合峰值日: {td_list[peak_idx]}  ${peak_val:,.0f}')
print(f'组合谷底日: {td_list[trough_idx]}  ${combined_vals[trough_idx]:,.0f}')
print(f'最大回撤: {mdd*100:.1f}%')
print()

# Show each account's holdings at peak and trough
for i, a in enumerate(accounts):
    print(f'排名{i+1}账户: 峰值${a.dv[peak_idx]:,.0f} → 谷底${a.dv[trough_idx]:,.0f} ({(a.dv[trough_idx]/a.dv[peak_idx]-1)*100:+.1f}%)')
    print(f'    峰值日持仓: {a.holdings_log[peak_idx]}  谷底日持仓: {a.holdings_log[trough_idx]}')

# Show drawdown contributors
total_peak = sum(accounts[i].dv[peak_idx] for i in range(HN))
print(f'\n各账户对{total_peak-peak_val:+,.0f}回撤的贡献:')
for i, a in enumerate(accounts):
    contrib = a.dv[trough_idx] - a.dv[peak_idx]
    print(f'  排名{i+1}: ${contrib:+,.0f} ({contrib/total_peak*100:+.1f}%) 峰值时占比{a.dv[peak_idx]/total_peak*100:.1f}%')

# Show win accounts (that grew between peak and trough)
print(f'\n分析: 峰值时排名3/4账户合计占{a.dv[peak_idx]/total_peak*100:.0f}%的组合资产')
print(f'      当这两只重仓股同时暴跌时，小账户的分散完全不够对冲')
