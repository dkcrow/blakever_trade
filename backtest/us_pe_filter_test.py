#!/usr/bin/env python3
"""七星美股版 PE(TTM)过滤回测对比"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'us'
START, END = '2023-06-01', '2026-06-04'

POOL_35 = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')
REMOVE = {'DDOG', 'ARM', 'AMD', 'LITE', 'PLTR', 'SNPS', 'CRWD'}  # PE>100 or PE<0
POOL_28 = [s for s in POOL_35 if s not in REMOVE]

def calc_score(close_full):
    r = close_full[-26:]
    y = np.log(np.maximum(r, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    sl, ic = np.polyfit(x, y, 1, w=w)
    ann_ret = math.exp(sl * 250) - 1
    ssr = np.sum(w * (y - (sl * x + ic)) ** 2)
    sst = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann_ret * r2

def get_ranked(all_data, prices, date):
    rk = []
    for code, df in all_data.items():
        if code not in prices:
            continue
        hist = df[df.index <= pd.Timestamp(date)]
        if len(hist) < 35:
            continue
        cp = prices[code]
        if cp <= 0:
            continue
        rk.append({'code': code, 'score': calc_score(hist['close'].values), 'price': cp})
    rk.sort(key=lambda x: x['score'], reverse=True)
    return rk

class Portfolio:
    def __init__(self, cash=10000):
        self.ic = cash
        self.c = cash
        self.pos = {}
        self.tl = []
        self.dv = []

    @property
    def tv(self):
        return self.c + sum(p['s'] * p.get('lp', p['cp']) for p in self.pos.values())

    def record(self, dt):
        self.dv.append({'date': str(dt)[:10], 'value': round(self.tv, 2)})

    def up(self, pdict):
        for c, p in pdict.items():
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


def run_backtest(pool_syms):
    all_data = {}
    for sym in pool_syms:
        fp = DATA_DIR / f'{sym}.csv'
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp)
            df = df.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            mask = (df.index >= START) & (df.index <= END)
            df = df[mask]
            if len(df) >= 25:
                all_data[sym] = df
        except:
            pass

    td_list = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
    td_list = [d for d in td_list if START <= d <= END]

    p = Portfolio(10000)
    hn = 7

    for td in td_list:
        tds = pd.Timestamp(td)
        prices = {}
        for code, df in all_data.items():
            m = df.index <= tds
            if m.any():
                prices[code] = float(df.loc[m, 'close'].iloc[-1])
        p.up(prices)

        ranked = get_ranked(all_data, prices, td)
        if not ranked:
            continue
        tgs = [r['code'] for r in ranked if r['score'] > -999][:hn]
        if not tgs:
            for cd in list(p.pos.keys()):
                if cd in prices:
                    p.sa(cd, prices[cd], td, '调出(无目标)')
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
        p.record(td)

    # Use recorded daily values
    vals = [d['value'] for d in p.dv]

    fv = vals[-1]
    tr = (fv - p.ic) / p.ic
    peak, mdd = vals[0], 0
    for v in vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd

    sh = 0
    if len(vals) > 1:
        dr = np.diff(vals) / vals[:-1]
        sh = (np.mean(dr) / np.std(dr) * np.sqrt(252)) if np.std(dr) > 0 else 0

    n_days = len(td_list)
    ann = tr * 252 / n_days * 100
    st = [t for t in p.tl if t['a'] == 'SELL' and 'pnl' in t]
    wins = [t for t in st if t['pnl'] > 0]
    wr = len(wins) / len(st) * 100 if st else 0

    return tr * 100, ann, mdd * 100, sh, len(p.tl), wr, len(all_data)


if __name__ == '__main__':
    print(f'35只 → 剔除PE>100/亏损后: {len(POOL_28)}只 ({sorted(REMOVE)})')
    print()
    print(f'{"配置":12s} {"总收益":>8s} {"年化":>7s} {"回撤":>6s} {"夏普":>7s} {"胜率":>6s} {"交易":>5s} {"标数":>4s}')
    print('-' * 65)

    for pool_syms, label in [(POOL_35, '35只原池'), (POOL_28, 'PE过滤28只')]:
        tr, ann, mdd, sh, trades, wr, n_stocks = run_backtest(pool_syms)
        print(f'{label:12s} {tr:+7.1f}% {ann:6.1f}% {mdd:5.1f}% {sh:6.4f} {wr:5.1f}% {trades:4d}次 {n_stocks:4d}只')
