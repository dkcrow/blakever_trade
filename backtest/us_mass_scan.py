"""扫描495只候选美股: 每只加入base池测试增量贡献"""
import numpy as np, pandas as pd
from pathlib import Path
import sys

DATA_DIR = Path('data/storage/stock_data/us')
BASE_POOL = 'NVDA,AVGO,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,CSCO,HOOD'.split(',')
HN=7; CASH=1000000; COMM=0.005; SLIP=0.0005; TH=0.5

# Pre-load base pool data
def sc(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    sl = np.polyfit(x_m, y_m, 1)[0]; ann = np.exp(sl * 250)
    fitted = sl * x_m + np.polyfit(x_m, y_m, 1)[1]; res = y_m - fitted
    ss = sum(res**2); st = sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss/st if st > 0 else 0
    return ann * r2

class PF:
    def __init__(s): s.c = CASH; s.pos = {}
    @property
    def tv(s): return s.c + sum(p['s'] * p.get('l', p['cp']) for p in s.pos.values())
    def up(s, d):
        for c, p in d.items():
            if c in s.pos: s.pos[c]['l'] = p
    def buy(s, x, sh, pr):
        p = pr*(1+SLIP); t = sh*p; c = sh*COMM
        if t+c > s.c+0.01: return False
        s.c -= t+c
        if x in s.pos: o = s.pos[x]; ts = o['s']+sh; s.pos[x] = {'s': ts, 'cp': (o['s']*o['cp']+sh*p)/ts, 'l': p}
        else: s.pos[x] = {'s': sh, 'cp': p, 'l': p}
        return True
    def sell(s, x, sh, pr):
        if x not in s.pos: return False
        p = pr*(1-SLIP); pos = s.pos[x]; a = min(sh, pos['s'])
        s.c += a*p - a*COMM
        if a >= pos['s']: del s.pos[x]
        else: s.pos[x]['s'] -= a
        return True
    def cs(s): return list(s.pos.keys())

def run(pool):
    all_data = {}
    for sym in pool:
        f = DATA_DIR / f'{sym}.csv'
        if f.exists():
            d = pd.read_csv(f)
            if 'Date' in d.columns:
                d.rename(columns={'Date': 'date', 'Last': 'close', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Volume': 'volume'}, inplace=True)
            d.columns = [c.lower() for c in d.columns]
            d['date'] = pd.to_datetime(d['date'])
            d = d.set_index('date').sort_index()
            if len(d) > 35: all_data[sym] = d
    
    tds = sorted(set().union(*[set(d.index) for d in all_data.values()]))
    tds = [d for d in tds if '2025-01-01' <= d.strftime('%Y-%m-%d') <= '2026-06-18']
    
    pf = PF()
    for date in tds:
        ds = date.strftime('%Y-%m-%d')
        prices = {}
        for sym in pool:
            if sym in all_data:
                m = all_data[sym].index == date
                if m.any(): prices[sym] = float(all_data[sym].loc[date, 'close'])
        if len(prices) < HN: continue
        
        ranked = []
        for sym in pool:
            if sym not in prices: continue
            d = all_data[sym]; mask = d.index < date; hist = d[mask]
            if len(hist) < 25: continue
            cp = prices[sym]
            if cp <= 0: continue
            score = sc(hist['close'].values[-25:])
            ranked.append({'code': sym, 'score': score, 'price': cp})
        ranked.sort(key=lambda x: x['score'], reverse=True)
        
        targets = [r for r in ranked if r['score'] >= TH][:HN]
        tc = set(r['code'] for r in targets)
        cc = set(pf.cs())
        ts = cc - tc
        for code in list(cc):
            f = next((r for r in ranked if r['code'] == code), None)
            if f and f['score'] < TH: ts.add(code)
        
        for code in ts:
            if code in prices: pf.sell(code, pf.pos[code]['s'], prices[code])
        
        tv = pf.tv; pf.up(prices)
        nq = max(len(targets), 1)
        for r in targets:
            if r['code'] in pf.pos: continue
            if r['code'] not in prices: continue
            ps = tv * 0.95 / nq; sh = int(ps / r['price'])
            if sh >= 1: pf.buy(r['code'], sh, r['price'])
    
    # Simple return calc
    daily_vals = []
    cash_tracker = CASH
    return pf.tv

# Run baseline once
print('计算基准...', end=' ', flush=True)
base_final = run(BASE_POOL)
base_ann = (base_final / CASH) ** (252/356) - 1
print(f'${base_final:,.0f} (年化{base_ann*100:.1f}%)')

# Scan candidates
candidates = []
for fp in sorted(DATA_DIR.glob('*.csv')):
    sym = fp.stem
    if sym in BASE_POOL: continue
    if len(sym) > 5: continue
    if sym.startswith('^') or sym.startswith('.'): continue
    candidates.append(sym)

print(f'候选: {len(candidates)}只')
print('扫描中...')

results = []
for i, sym in enumerate(candidates):
    test_pool = BASE_POOL + [sym]
    try:
        final = run(test_pool)
        ann = (final / CASH) ** (252/356) - 1
        diff = (ann - base_ann) * 100
        results.append({'sym': sym, 'diff': round(diff, 2), 'final': final})
    except:
        results.append({'sym': sym, 'diff': 0, 'final': 0})
    
    if (i+1) % 50 == 0:
        positives = [r for r in results if r['diff'] > 0]
        print(f'进度: {i+1}/{len(candidates)} | 正贡献: {len(positives)}只', flush=True)

# Sort by contribution
results.sort(key=lambda x: x['diff'], reverse=True)
positives = [r for r in results if r['diff'] > 0]
negatives = [r for r in results if r['diff'] <= 0]

print()
print(f'扫描完成: {len(positives)}只正贡献 | {len(negatives)}只非正')

# Show top 20 positives
print()
print('Top 20 正贡献候选:')
for i, r in enumerate(positives[:20]):
    print(f'  {i+1:>2}. {r["sym"]:<6} +{r["diff"]:+.1f}%')

# Save for review
import json
with open('backtest/results_us100/scan_results.json', 'w') as f:
    json.dump({'base': base_final, 'base_annual': round(base_ann*100,2), 'candidates': results[:100]}, f, indent=2)
print('\n结果已保存: backtest/results_us100/scan_results.json')
