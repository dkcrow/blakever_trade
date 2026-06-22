# -*- coding: utf-8 -*-
"""美股版/港股版 短期动量过滤消融实验
对比: 基准(无短期过滤) vs 短期动量过滤(5/10/15日, 剔除短期年化动量<0的标的)
引擎: calc_score(25日) + score>=0.5 + 方案B可用现金分配 + 持仓数HN
"""
import numpy as np, pandas as pd, sys
from pathlib import Path

END_DATE = '2026-06-22'
START_DATE = '2023-06-18'
CASH = 1000000
LOOKBACK = 25
TH = 0.5

US_POOL = 'NVDA,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,HOOD,WDC,ARM,STX'.split(',')
HK_POOL = ['00700','09988','01810','03690','09999','02513','00100','02162','02616','09969',
           '02418','01357','00981','01347','00522','01211','01093','01177','02338','02038',
           '01378','00388','02388','00005','02318','00939','02628','03988','09888','00883',
           '02899','03993','02618','01929','01113','06181','00669']


def calc_score(closes):
    if len(closes) < LOOKBACK: return -999
    c = closes[-LOOKBACK:]
    x = np.arange(len(c)); y = np.log(np.maximum(c, 1e-10))
    mask = ~np.isnan(y) & ~np.isinf(y); xm, ym = x[mask], y[mask]
    if len(xm) < 5: return -999
    sl = np.polyfit(xm, ym, 1)[0]; ann = np.exp(sl * 250)
    fit = sl * xm + np.polyfit(xm, ym, 1)[1]; res = ym - fit
    ssr = np.sum(res**2); sst = np.sum((ym - np.mean(ym))**2)
    r2 = 1 - ssr/sst if sst > 0 else 0
    return ann * r2


def short_mom_annual(closes, lb):
    if len(closes) < lb + 1: return 0.0
    r = closes[-1] / closes[-(lb+1)] - 1
    return (1 + r) ** (250.0 / lb) - 1


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


def run(market, all_data, use_short=False, short_lb=10):
    is_us = market == 'us'
    HN = 7 if is_us else 5
    COMM_US = 0.005; SLIP_US = 0.0005
    HK_COMM = 0.001; HK_STAMP = 0.0013; HK_FEE = 0.0000565; SLIP_HK = 0.001

    tds = sorted(set().union(*[set(df.index) for df in all_data.values()]))
    tds = [d for d in tds if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]

    cash = CASH; pos = {}; daily = []; wins = 0; sells = 0

    def total_val(prices):
        pv = sum(p['s'] * prices.get(c, p['lp']) for c, p in pos.items())
        return cash + pv

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
        # rank
        ranked = []
        for c in prices:
            hist = all_data[c][all_data[c].index < date]
            if len(hist) < LOOKBACK: continue
            sc = calc_score(hist['close'].values)
            sm = short_mom_annual(hist['close'].values, short_lb) if use_short else 1.0
            ranked.append({'c': c, 'sc': sc, 'sm': sm, 'p': prices[c]})
        ranked.sort(key=lambda x: x['sc'], reverse=True)
        # targets: score>=0.5 (+ 短期动量>=0 if use_short)
        def ok(r):
            if r['sc'] < TH: return False
            if use_short and r['sm'] < 0: return False
            return True
        targets = [r for r in ranked if ok(r)][:HN]
        tc = set(r['c'] for r in targets)
        # sells: 不在targets 或 跌破阈值/短期动量转负
        to_sell = set(pos.keys()) - tc
        for c in list(pos.keys()):
            f = next((r for r in ranked if r['c'] == c), None)
            if f and not ok(f): to_sell.add(c)
        for c in to_sell:
            if c not in pos: continue
            sp = prices.get(c, pos[c]['lp'])
            if is_us:
                p = sp * (1 - SLIP_US); tv = pos[c]['s'] * p; cash += tv - pos[c]['s'] * COMM_US
            else:
                p = sp * (1 - SLIP_HK); tv = pos[c]['s'] * p
                cash += tv - max(tv*HK_COMM, 5) - tv*HK_STAMP - tv*HK_FEE
            pnl = (p - pos[c]['cp']) / pos[c]['cp'] if pos[c]['cp'] > 0 else 0
            sells += 1; wins += 1 if pnl > 0 else 0
            del pos[c]
        # buys: 方案B 可用现金等分新目标
        tv_now = total_val(prices)
        new_t = [r for r in targets if r['c'] not in pos]
        if new_t:
            per = cash * 0.95 / len(new_t)
            for r in new_t:
                if r['c'] not in prices: continue
                if is_us:
                    sh = int(per / r['p'])
                    if sh >= 1:
                        p = r['p'] * (1 + SLIP_US); t = sh*p + sh*COMM_US
                        if t <= cash: cash -= t; pos[r['c']] = {'s': sh, 'cp': p, 'lp': p}
                else:
                    sh = int(per / r['p'] / 100) * 100
                    if sh >= 100:
                        p = r['p'] * (1 + SLIP_HK); tv = sh*p; t = tv + max(tv*HK_COMM,5) + tv*HK_FEE
                        if t <= cash: cash -= t; pos[r['c']] = {'s': sh, 'cp': p, 'lp': p}
        daily.append(total_val(prices))

    dv = pd.Series(daily)
    tr = (dv.iloc[-1] / CASH - 1) * 100
    dr = dv.pct_change().dropna()
    cagr = ((dv.iloc[-1] / CASH) ** (252.0 / max(len(dr), 1)) - 1) * 100
    dd = (dv / dv.cummax() - 1).min() * 100
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    wr = wins / sells * 100 if sells else 0
    return dict(tr=tr, cagr=cagr, dd=dd, sharpe=sharpe, sells=sells, wr=wr, fv=dv.iloc[-1])


for market in ['us', 'hk']:
    name = '七星美股版' if market == 'us' else '七星港股版'
    data = load(market)
    print(f'\n{"="*78}')
    print(f'  {name} 短期动量过滤消融 | {START_DATE}~{END_DATE} | {len(data)}只 | 持仓{7 if market=="us" else 5} | {CASH:,.0f}')
    print(f'{"="*78}')
    print(f'{"配置":>14} | {"累计%":>9} | {"年化CAGR%":>9} | {"回撤%":>7} | {"夏普":>6} | {"交易":>5} | {"胜率%":>5}')
    print('-' * 78)
    configs = [('基准·关闭', False, 0), ('短期5日', True, 5), ('短期10日', True, 10), ('短期15日', True, 15)]
    for label, us, lb in configs:
        r = run(market, data, use_short=us, short_lb=lb)
        print(f'{label:>14} | {r["tr"]:>+8.1f} | {r["cagr"]:>+8.1f} | {r["dd"]:>7.1f} | {r["sharpe"]:>6.2f} | {r["sells"]:>5} | {r["wr"]:>5.1f}')
        sys.stdout.flush()
print(f'\n{"="*78}\n完成')
