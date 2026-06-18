#!/usr/bin/env python3
"""七星美股版: 7独立子账户 vs x7等权单池 对比"""
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
    """独立子账户：每次满仓排名对应的那一个标的"""
    def __init__(self, cash=10000):
        self.ic = cash
        self.c = cash
        self.holding = None
        self.cost = 0
        self.shares = 0
        self.tl = []
        self.dv = []

    def record(self, prices):
        v = self.c
        if self.holding and self.holding in prices:
            v += self.shares * prices[self.holding]
        self.dv.append(v)

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


class PF:
    """等权再平衡单池"""
    def __init__(self, c=10000):
        self.ic = c
        self.c = c
        self.pos = {}
        self.tl = []
        self.dv = []

    @property
    def tv(self):
        return self.c + sum(p['s'] * p.get('lp', p['cp']) for p in self.pos.values())

    def record(self):
        self.dv.append(self.tv)

    def up(self, pd):
        for c, p in pd.items():
            if c in self.pos:
                self.pos[c]['lp'] = p

    def buy(self, cd, sh, pr, dt, r=''):
        tvv = sh * pr
        t = tvv + sh * 0.005
        if t > self.c + 0.01:
            return False
        self.c -= t
        if cd in self.pos:
            o = self.pos[cd]
            ts = o['s'] + sh
            self.pos[cd] = {'s': ts, 'cp': (o['s'] * o['cp'] + sh * pr) / ts, 'lp': pr, 'bd': o.get('bd', dt)}
        else:
            self.pos[cd] = {'s': sh, 'cp': pr, 'lp': pr, 'bd': dt}
        return True

    def sell(self, cd, sh, pr, dt, r=''):
        if cd not in self.pos:
            return False
        po = self.pos[cd]
        a = min(sh, po['s'])
        if a <= 0:
            return False
        tvv = a * pr
        self.c += tvv - a * 0.005
        pnl = (pr - po['cp']) / po['cp'] if po['cp'] > 0 else 0
        po['s'] -= a
        if po['s'] <= 0:
            del self.pos[cd]
        self.tl.append({'d': str(dt)[:10], 'code': cd, 'a': 'SELL', 'pr': pr, 's': a, 'pnl': round(pnl, 4), 'r': r})
        return True

    def sa(self, cd, pr, dt, r=''):
        if cd not in self.pos:
            return False
        return self.sell(cd, self.pos[cd]['s'], pr, dt, r)


# ===============================================================
# 方案A: 7个独立子账户
# ===============================================================
HN = 7
accounts = [Account(10000) for _ in range(HN)]
print(f'方案A: 7个独立子账户, 每户$10,000 = 总本金$70,000')

for td in td_list:
    tds = pd.Timestamp(td)
    prices = {}
    for cd, df in all_data.items():
        m = df.index <= tds
        if m.any():
            prices[cd] = float(df.loc[m, 'close'].iloc[-1])

    rk = rankings(prices, td)
    if not rk:
        for acct in accounts:
            acct.record(prices)
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

# 计算方案A绩效
combined_vals = []
for j in range(len(td_list)):
    tv = sum(accounts[i].dv[j] for i in range(HN))
    combined_vals.append(tv)

combined_fv = combined_vals[-1]
combined_tr = (combined_fv - 70000) / 70000
peak, mdd = 70000, 0
for v in combined_vals:
    if v > peak:
        peak = v
    dd = (peak - v) / peak if peak > 0 else 0
    if dd > mdd:
        mdd = dd
dr = np.diff(combined_vals) / combined_vals[:-1]
sh = (np.mean(dr) / np.std(dr) * np.sqrt(252)) if np.std(dr) > 0 else 0
n_days = len(td_list)
ann = combined_tr * 252 / n_days * 100

all_trades = []
for a in accounts:
    all_trades.extend(a.tl)
all_trades.sort(key=lambda x: x['d'])
st = [t for t in all_trades if t['a'] == 'SELL' and 'pnl' in t]
wr = len([t for t in st if t['pnl'] > 0]) / len(st) * 100 if st else 0

print(f'  合计: +{combined_tr*100:.1f}%  年化{ann:.1f}%  回撤{mdd*100:.1f}%  夏普{sh:.4f}  交易{len(all_trades)}次  胜率{wr:.1f}%')
for i, a in enumerate(accounts):
    fv_a = a.dv[-1]
    tr_a = (fv_a - 10000) / 10000
    print(f'  子账户{i+1}: ${fv_a:,.0f} ({tr_a*100:+.1f}%)')

# ===============================================================
# 方案B: x7等权单池 (基准)
# ===============================================================
p = PF(10000)
prices_last = {}
print(f'\n方案B: x7等权单池, $10,000')

for td in td_list:
    tds = pd.Timestamp(td)
    prices = {}
    for cd, df in all_data.items():
        m = df.index <= tds
        if m.any():
            prices[cd] = float(df.loc[m, 'close'].iloc[-1])
    prices_last = prices
    p.up(prices)

    rk = rankings(prices, td)
    if not rk:
        p.record()
        continue

    tgs = [r['code'] for r in rk if r['score'] > -999][:HN]
    if not tgs:
        for cd in list(p.pos.keys()):
            if cd in prices:
                p.sa(cd, prices[cd], td, '调出(无目标)')
        p.record()
        continue

    for cd in list(p.pos.keys()):
        if cd not in tgs and cd in prices:
            p.sa(cd, prices[cd], td, '调出目标')

    tv = p.tv
    each = tv / len(tgs)
    for idx, cd in enumerate(tgs):
        if cd not in prices:
            continue
        pr = prices[cd]
        cv = 0
        if cd in p.pos:
            cv = p.pos[cd]['s'] * p.pos[cd]['lp']
        diff = each - cv
        if abs(diff) < each * 0.05 and cv > 0:
            continue
        if diff > 0:
            sh = int(diff / pr)
            if sh > 0 and sh * pr >= 500:
                p.buy(cd, sh, pr, td, f'排名{idx+1}')
    p.record()

vals = p.dv
fv = vals[-1]
tr = (fv - p.ic) / p.ic
peak, mdd2 = vals[0], 0
for v in vals:
    if v > peak:
        peak = v
    dd = (peak - v) / peak if peak > 0 else 0
    if dd > mdd2:
        mdd2 = dd
dr2 = np.diff(vals) / vals[:-1]
sh2 = (np.mean(dr2) / np.std(dr2) * np.sqrt(252)) if np.std(dr2) > 0 else 0
ann2 = tr * 252 / n_days * 100
st2 = [t for t in p.tl if t['a'] == 'SELL' and 'pnl' in t]
wr2 = len([t for t in st2 if t['pnl'] > 0]) / len(st2) * 100 if st2 else 0

print(f'  合计: +{tr*100:.1f}%  年化{ann2:.1f}%  回撤{mdd2*100:.1f}%  夏普{sh2:.4f}  交易{len(p.tl)}次  胜率{wr2:.1f}%')

# ===============================================================
# 对比
# ===============================================================
print(f'\n{"="*70}')
print(f'{"指标":20s} {"7独立子账户($70K)":>20s} {"x7等权单池($10K)":>20s}')
print(f'{"-"*70}')
print(f'{"总收益":20s} {combined_tr*100:+18.1f}% {tr*100:+18.1f}%')
print(f'{"年化收益":20s} {ann:18.1f}% {ann2:18.1f}%')
print(f'{"最大回撤":20s} {mdd*100:18.1f}% {mdd2*100:18.1f}%')
print(f'{"夏普比率":20s} {sh:18.4f} {sh2:18.4f}')
print(f'{"交易次数":20s} {len(all_trades):18d} {len(p.tl):18d}')
print(f'{"胜率":20s} {wr:18.1f}% {wr2:18.1f}%')
print(f'{"归一化收益($10K)":20s} ${combined_fv/7:>18,.0f} ${fv:>18,.0f}')
