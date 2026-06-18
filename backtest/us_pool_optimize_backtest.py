#!/usr/bin/env python3
"""七星美股版 池优化对比回测: 原池 vs 优化池 (3年期)"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/us')

# 原池35只
POOL_ORIG = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')

# 优化池: 替换 NOW,NFLX,CRM,SNPS,AMT → PANW,ZS,NET,IONQ,RKLB (其他不变)
POOL_NEW = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,GOOGL,MSFT,CRWD,ORCL,PLTR,DDOG,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,PANW,ZS,NET,IONQ,RKLB'.split(',')

# 加载数据
def load_all(pool):
    data = {}
    for s in pool:
        fp = DATA_DIR / f'{s}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 30: data[s] = df
    return data

all_data_orig = load_all(POOL_ORIG)
all_data_new = load_all(POOL_NEW)

START='2023-06-11'; END='2026-06-06'
tdates = sorted(set().union(*[set(df.index) for df in all_data_new.values()]))
tdates = [d for d in tdates if START <= d.strftime('%Y-%m-%d') <= END]

LB=25; HN=7; CASH=100000; COMM=0.005; SLIP=0.0005

def score_qx(closes):
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

def run_backtest(all_data, label):
    valid_pool = list(all_data.keys())
    cash = CASH; pos = {}; trades = []; dv = []
    
    for date in tdates:
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for c in valid_pool:
            m = all_data[c].index == date
            if m.any(): prices[c] = float(all_data[c].loc[date, 'close'])
        if not prices: continue
        
        ranked = []
        for c in valid_pool:
            if c not in prices: continue
            mask = all_data[c].index < pd.Timestamp(date)
            hist = all_data[c][mask]
            if len(hist) < LB + 10: continue
            hp = hist['close'].values[-LB:].copy()
            if np.any(hp <= 0): continue
            s = score_qx(hp)
            if s > 0: ranked.append({'code': c, 'score': s, 'price': prices[c]})
        
        ranked.sort(key=lambda x: x['score'], reverse=True)
        if len(ranked) < HN: continue
        
        targets = [r for r in ranked[:HN] if r['score'] > 0]
        target_codes = set(r['code'] for r in targets)
        
        for c in list(pos.keys()):
            if c not in target_codes and c in prices:
                p = prices[c] * (1 - SLIP)
                tv = pos[c]['shares'] * p; cf = pos[c]['shares'] * COMM
                cash += tv - cf
                pnl = (p - pos[c]['cost']) / pos[c]['cost'] * 100
                trades.append({'date': d_str, 'code': c, 'pnl': pnl})
                del pos[c]
        
        total_val = cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in pos.items())
        for r in targets:
            c = r['code']
            if c not in pos and c in prices:
                per = total_val * 0.95 / len(targets)
                shares = int(per / prices[c])
                if shares > 0:
                    p_buy = prices[c] * (1 + SLIP)
                    tv = shares * p_buy; cf = shares * COMM
                    cash -= tv + cf
                    pos[c] = {'shares': shares, 'cost': p_buy}
        
        dv.append({'date': d_str, 'value': cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in pos.items())})
    
    dv_df = pd.DataFrame(dv)
    tr = (dv_df['value'].iloc[-1] / CASH - 1) * 100
    dr = dv_df['value'].pct_change().dropna()
    ar = (1 + dr.mean())**252 - 1
    md = (dv_df['value'] / dv_df['value'].cummax() - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
    return tr, ar*100, md, sp, len(trades), wr

# 运行
print(f'回测区间: {tdates[0].date()} ~ {tdates[-1].date()}, {len(tdates)}天')
print(f'原池: {len(all_data_orig)}只 | 优化池: {len(all_data_new)}只')
print()

results = []
for label, ad in [('原池(35只)', all_data_orig), ('优化池(35只)', all_data_new)]:
    print(f'Running {label}...')
    tr, ar, md, sp, nt, wr = run_backtest(ad, label)
    results.append((label, tr, ar, md, sp, nt, wr))

print()
hdr = f'{"池":<20} {"累计":>8} {"年化":>7} {"回撤":>6} {"夏普":>5} {"交易":>5} {"胜率":>5}'
print(hdr)
print('-' * 60)
for label, tr, ar, md, sp, nt, wr in results:
    print(f'{label:<20} {tr:>+7.2f}% {ar:>6.1f}% {md:>5.1f}% {sp:>5.2f} {nt:>5} {wr:>5.1f}%')

# 差异
tr_diff = results[1][1] - results[0][1]
print(f'\n差异: {tr_diff:+.2f}%')
if tr_diff > 0:
    print(f'优化池胜出 +{tr_diff:.2f}%')
else:
    print(f'原池胜出 {abs(tr_diff):.2f}%')

# 分年对比
print()
print('=== 年度收益 ===')
for task_idx, (label, ad) in enumerate([('原池', all_data_orig), ('优化池', all_data_new)]):
    dv = pd.DataFrame([])
    # 重新运行一次获取daily values
    cash = CASH; pos = {}
    for date in tdates:
        prices = {c: float(ad[c].loc[date,'close']) for c in ad if date in ad[c].index}
        if not prices: continue
        ranked = []
        for c in ad:
            if c not in prices: continue
            mask = ad[c].index < pd.Timestamp(date)
            hist = ad[c][mask]
            if len(hist) < LB+10: continue
            hp = hist['close'].values[-LB:].copy()
            if np.any(hp<=0): continue
            s = score_qx(hp)
            if s>0: ranked.append({'code':c,'score':s,'price':prices[c]})
        ranked.sort(key=lambda x:x['score'],reverse=True)
        if len(ranked)<HN: continue
        targets = [r for r in ranked[:HN] if r['score']>0]
        tc = set(r['code'] for r in targets)
        for c in list(pos.keys()):
            if c not in tc and c in prices:
                p = prices[c]*(1-SLIP); tv = pos[c]['shares']*p; cf = pos[c]['shares']*COMM
                cash += tv-cf; del pos[c]
        tv = cash + sum(p['shares']*prices.get(c,p['cost']) for c,p in pos.items())
        for r in targets:
            c = r['code']
            if c not in pos and c in prices:
                per = tv*0.95/len(targets); shares = int(per/prices[c])
                if shares>0:
                    pb = prices[c]*(1+SLIP); tv2 = shares*pb + shares*COMM
                    cash -= tv2; pos[c] = {'shares':shares,'cost':pb}
        dv.append({'date':date.strftime('%Y-%m-%d'), 'value':cash+sum(p['shares']*prices.get(c,p['cost']) for c,p in pos.items())})
    
    dv_df = pd.DataFrame(dv)
    for year in [2023,2024,2025,2026]:
        yd = dv_df[dv_df['date'].str.startswith(str(year))]
        if len(yd)<2: continue
        yr = (yd['value'].iloc[-1]/yd['value'].iloc[0]-1)*100
        print(f'  {label} {year}: {yr:+.2f}%')
    print()
