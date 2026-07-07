#!/usr/bin/env python3
"""七星美股版 持仓回撤止损过滤回测: 从买入后最高价下跌X%→强制卖出"""
import sys, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT = Path(__file__).parent.parent
DATA_DIR = PROJECT / 'data' / 'storage' / 'stock_data' / 'us'

POOL = ['NVDA','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS',
        'EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB',
        'SPCX','COHR','HOOD','WDC','ARM','STX']
HN = 7; COMM = 0.005; SLIP = 0.0005; SCORE_THR = 0.5
MIN_HISTORY_DAYS = 126

def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback+1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y)); w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope*x + intercept))**2)
    sst = np.sum(w * (y - np.mean(y))**2)
    r2 = 1 - ssr/sst if sst>0 else 0
    return ann * r2

def get_ranked(all_data, prices, date):
    from datetime import datetime as _dt
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index < pd.Timestamp(date); hist = df[mask]
        if len(hist) < MIN_HISTORY_DAYS: continue
        cp = prices[code]
        if cp <= 0: continue
        long_score = calc_score(hist['close'].values, 25)
        ranked.append({'code':code,'score':long_score,'price':cp})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

def run(start, end, dd_threshold=None):
    all_data = {}
    for sym in POOL:
        fp = DATA_DIR / f'{sym}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        df.columns = [c.lower().strip() for c in df.columns]
        dc = [c for c in df.columns if c.lower()=='date'][0]
        df = df.rename(columns={dc: 'date'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= start) & (df.index <= end)
        df = df[m]
        if len(df) >= 25: all_data[sym] = df

    td = sorted(set().union(*[set(df.index) for df in all_data.values()]))
    td = [d for d in td if start <= d.strftime('%Y-%m-%d') <= end]

    cash = 1_000_000; pos = {}  # pos: {code: {'shares':N, 'cp':cost, 'peak':peak}}
    daily = [1_000_000]
    dd_sells = 0

    for date in td:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])
        if len(prices) < HN: continue

        # 1) Drawdown check: force-sell if any position exceeds threshold
        if dd_threshold:
            for code in list(pos.keys()):
                p = prices.get(code)
                if not p: continue
                # Update peak
                if p > pos[code].get('peak', pos[code]['cp']):
                    pos[code]['peak'] = p
                peak = pos[code].get('peak', pos[code]['cp'])
                dd = (p - peak) / peak * 100
                if dd <= -dd_threshold:
                    sp = p * (1 - SLIP)
                    tv2 = pos[code]['shares'] * sp
                    comm_cost = max(pos[code]['shares'] * COMM, 1)
                    cash += tv2 - comm_cost
                    del pos[code]
                    dd_sells += 1
                    continue

        if len(prices) < HN: continue

        ranked = get_ranked(all_data, prices, date)
        targets = [r for r in ranked if r['score'] >= SCORE_THR][:HN]
        tc = set(r['code'] for r in targets)

        # 2) Normal sell (no longer in target)
        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code)
                if not p: p = pos[code]['cp']
                sp = p * (1 - SLIP)
                tv2 = pos[code]['shares'] * sp
                comm_cost = max(pos[code]['shares'] * COMM, 1)
                cash += tv2 - comm_cost
                del pos[code]

        # 3) Buy
        new = [r for r in targets if r['code'] not in pos]
        if new:
            avail = cash * 0.95; per = avail / len(new)
            for r in new:
                bp = r['price'] * (1 + SLIP); sh = int(per / bp)
                if sh < 1: continue
                cost = sh * bp + max(sh * COMM, 1)
                cash -= cost
                pos[r['code']] = {'shares': sh, 'cp': bp, 'peak': r['price']}

        tv = cash + sum(p2['shares'] * prices.get(c, p2['cp']) for c, p2 in pos.items())
        daily.append(tv)

    tv = daily[-1]
    tr = (tv / 1_000_000 - 1) * 100
    cagr = ((tv / 1_000_000) ** (252 / max(len(daily), 1)) - 1) * 100
    peak_val = 1_000_000; mdd = 0
    for v in daily:
        if v > peak_val: peak_val = v
        d = (v - peak_val) / peak_val * 100
        if d < mdd: mdd = d
    rets = np.diff(daily) / daily[:-1]
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252) if len(rets)>0 and np.std(rets)>0 else 0
    return {'tr': round(tr,1), 'cagr': round(cagr,1), 'mdd': round(mdd,1), 'sh': round(sharpe,2), 'sells': dd_sells}


periods = [
    ('1年','2025-07-02','2026-07-02'),
    ('3年','2023-07-02','2026-07-02'),
    ('5年','2021-07-02','2026-07-02'),
]

thresholds = [None, 7, 10, 15, 20]
labels = {None: '关闭', 7: '7%', 10: '10%', 15: '15%', 20: '20%'}

for pn, start, end in periods:
    print(f'\n{"="*60}')
    print(f'[{pn}] {start} ~ {end}')
    print(f'{"配置":<12} {"累计":>8} {"CAGR":>8} {"回撤":>8} {"夏普":>6} {"止损":>6}')
    print('-'*50)
    
    baseline = None
    for t in thresholds:
        r = run(start, end, t)
        if t is None: baseline = r
        star = ' ★' if baseline and t is not None and r['tr'] > baseline['tr'] and abs(r['mdd']) < abs(baseline['mdd']) else ''
        print(f'{labels[t]+"止损":<12} {r["tr"]:>+7.1f}% {r["cagr"]:>7.1f}% {r["mdd"]:>7.1f}% {r["sh"]:>5.2f} {r["sells"]:>5}{star}')

print('\n★ = 累计>关闭 且 回撤<关闭')
print('完成!')
