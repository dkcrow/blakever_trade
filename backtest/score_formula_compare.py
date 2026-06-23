# -*- coding: utf-8 -*-
"""评分公式对比: 美股版/港股版 native评分 vs 五福平方加权评分
控制变量: 同池+同持仓数+同score阈值+同方案B+同费率, 只换评分公式
native_us: 线性加权linspace(1,2) + (exp-1)*R²
native_hk: 无加权OLS + exp*R²(不减1)
wufu     : 平方加权linspace(1,2)^2 + (exp-1)*R²
"""
import numpy as np, math, pandas as pd, sys
from pathlib import Path

CASH = 1000000
LOOKBACK = 25
TH = 0.5

US_POOL = 'NVDA,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,HOOD,WDC,ARM,STX'.split(',')
HK_POOL = ['00700','09988','01810','03690','09999','02513','00100','02162','02616','09969',
           '02418','01357','00981','01347','00522','01211','01093','01177','02338','02038',
           '01378','00388','02388','00005','02318','00939','02628','03988','09888','00883',
           '02899','03993','02618','01929','01113','06181','00669']


def score(closes, mode):
    """mode: native_us / native_hk / wufu"""
    if len(closes) < LOOKBACK + 1: return -999
    recent = closes[-(LOOKBACK+1):]
    y = np.log(np.maximum(recent, 1e-10)); x = np.arange(len(y))
    if mode == 'native_hk':
        w = None
    elif mode in ('native_us', 'hk_lin'):
        w = np.linspace(1, 2, len(y))
    else:  # wufu, hk_sq
        w = np.linspace(1, 2, len(y)) ** 2
    if w is None:
        slope, intc = np.polyfit(x, y, 1)
        ssr = np.sum((y - (slope*x+intc))**2); sst = np.sum((y - np.mean(y))**2)
    else:
        slope, intc = np.polyfit(x, y, 1, w=w)
        ssr = np.sum(w*(y - (slope*x+intc))**2); sst = np.sum(w*(y - np.mean(y))**2)
    r2 = 1 - ssr/sst if sst > 0 else 0
    # 减1: native_us/wufu减1(美股QMT骨架); native_hk/hk_lin/hk_sq不减1(保港股原公式, 单独验证加权)
    minus = 1 if mode in ('native_us', 'wufu') else 0
    ann = math.exp(slope*250) - minus
    return ann * r2


def load(market):
    d = {}
    base = Path('data/storage/stock_data') / ('us' if market == 'us' else 'hk')
    pool = US_POOL if market == 'us' else HK_POOL
    for code in pool:
        fp = base / (f'{code}.csv' if market == 'us' else f'hk{code}.csv')
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'date', 'Last': 'close', 'Close': 'close'})
        df.columns = [c.lower() for c in df.columns]
        if 'date' not in df.columns or 'close' not in df.columns: continue
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]; df = df[df['close'] > 0]
        if len(df) > 35: d[code] = df
    return d


def run(market, all_data, mode, start):
    is_us = market == 'us'
    HN = 7 if is_us else 5
    COMM_US = 0.005; SLIP_US = 0.0005
    HK_COMM = 0.001; HK_STAMP = 0.0013; HK_FEE = 0.0000565; SLIP_HK = 0.001
    END = '2026-06-22'
    tds = sorted(set().union(*[set(df.index) for df in all_data.values()]))
    tds = [d for d in tds if start <= d.strftime('%Y-%m-%d') <= END]
    cash = CASH; pos = {}; daily = []; wins = sells = 0

    def tv_all(prices):
        return cash + sum(p['s']*prices.get(c, p['lp']) for c, p in pos.items())

    for date in tds:
        prices = {}
        for c, df in all_data.items():
            if date in df.index:
                v = df.loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[c] = float(v)
        if len(prices) < HN: continue
        for c in pos:
            if c in prices: pos[c]['lp'] = prices[c]
        ranked = []
        for c in prices:
            hist = all_data[c][all_data[c].index < date]
            if len(hist) < LOOKBACK: continue
            sc = score(hist['close'].values, mode)
            ranked.append({'c': c, 'sc': sc, 'p': prices[c]})
        ranked.sort(key=lambda x: x['sc'], reverse=True)
        targets = [r for r in ranked if r['sc'] >= TH][:HN]
        tc = set(r['c'] for r in targets)
        to_sell = set(pos) - tc
        for c in list(pos):
            f = next((r for r in ranked if r['c'] == c), None)
            if f and f['sc'] < TH: to_sell.add(c)
        for c in to_sell:
            if c not in pos: continue
            sp = prices.get(c, pos[c]['lp'])
            if is_us:
                p = sp*(1-SLIP_US); cash += pos[c]['s']*p - pos[c]['s']*COMM_US
            else:
                p = sp*(1-SLIP_HK); tv = pos[c]['s']*p
                cash += tv - max(tv*HK_COMM, 5) - tv*HK_STAMP - tv*HK_FEE
            pnl = (p-pos[c]['cp'])/pos[c]['cp'] if pos[c]['cp'] > 0 else 0
            sells += 1; wins += 1 if pnl > 0 else 0
            del pos[c]
        new_t = [r for r in targets if r['c'] not in pos]
        if new_t:
            per = cash*0.95/len(new_t)
            for r in new_t:
                if r['c'] not in prices: continue
                if is_us:
                    sh = int(per/r['p'])
                    if sh >= 1:
                        p = r['p']*(1+SLIP_US); t = sh*p + sh*COMM_US
                        if t <= cash: cash -= t; pos[r['c']] = {'s': sh, 'cp': p, 'lp': p}
                else:
                    sh = int(per/r['p']/100)*100
                    if sh >= 100:
                        p = r['p']*(1+SLIP_HK); tv = sh*p; t = tv + max(tv*HK_COMM, 5) + tv*HK_FEE
                        if t <= cash: cash -= t; pos[r['c']] = {'s': sh, 'cp': p, 'lp': p}
        daily.append(tv_all(prices))
    dv = pd.Series(daily)
    if len(dv) < 2: return None
    tr = (dv.iloc[-1]/CASH-1)*100
    dr = dv.pct_change().dropna()
    cagr = ((dv.iloc[-1]/CASH)**(252.0/max(len(dr), 1))-1)*100
    dd = (dv/dv.cummax()-1).min()*100
    sh = dr.mean()/dr.std()*np.sqrt(252) if dr.std() > 0 else 0
    wr = wins/sells*100 if sells else 0
    return dict(tr=tr, cagr=cagr, dd=dd, sh=sh, sells=sells, wr=wr)


data = load('hk')
print(f'\n{"="*80}')
print(f'  七星港股版 评分加权对比 | {len(data)}只 | 持仓5 | score>=0.5 | 控制变量:仅改加权,公式骨架不变(不减1)')
print(f'{"="*80}')
print(f'{"周期":>6} | {"评分权重":>14} | {"累计%":>9} | {"CAGR%":>8} | {"回撤%":>7} | {"夏普":>6} | {"交易":>5} | {"胜率%":>5}')
print('-'*80)
for plabel, start in [('1年', '2025-06-22'), ('3年', '2023-06-22')]:
    for slabel, mode in [('无加权(当前)', 'native_hk'), ('线性加权', 'hk_lin'), ('平方加权(五福式)', 'hk_sq')]:
        r = run('hk', data, mode, start)
        if r:
            print(f'{plabel:>6} | {slabel:>14} | {r["tr"]:>+8.1f} | {r["cagr"]:>+7.1f} | {r["dd"]:>7.1f} | {r["sh"]:>6.2f} | {r["sells"]:>5} | {r["wr"]:>5.1f}')
            sys.stdout.flush()
    print('-'*80)
print(f'{"="*80}\n完成')
