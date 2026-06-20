"""优化版: 扫描495只美股候选, 批量正贡献筛选"""
import numpy as np, pandas as pd, time
from pathlib import Path

DATA_DIR = Path('data/storage/stock_data/us')
BASE = 'NVDA,AVGO,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,CSCO,HOOD'.split(',')
HN=7; CASH=1000000; COMM=0.005; SLIP=0.0005; TH=0.5

def load_data(sym):
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists(): return None
    df = pd.read_csv(fp)
    if 'Date' in df.columns:
        df.rename(columns={'Date':'date','Last':'close','Open':'open','High':'high','Low':'low','Volume':'volume'}, inplace=True)
    df.columns = [c.lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    if len(df) < 35: return None
    return df

def sc(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(np.maximum(closes, 0.01))
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
        d = load_data(sym)
        if d is not None: all_data[sym] = d
    
    tds = sorted(set().union(*[set(d.index) for d in all_data.values()]))
    tds = [d for d in tds if '2025-01-01' <= d.strftime('%Y-%m-%d') <= '2026-06-18']
    
    pf = PF()
    for date in tds:
        prices = {}
        for sym in pool:
            if sym in all_data:
                m = all_data[sym].index == date
                if m.any():
                    v = all_data[sym].loc[date, 'close']
                    if hasattr(v, 'iloc'): v = v.iloc[0]
                    if float(v) > 0: prices[sym] = float(v)
        if len(prices) < HN: continue
        
        ranked = []
        for sym in pool:
            if sym not in prices: continue
            d = all_data[sym]; mask = d.index < date; hist = d[mask]
            if len(hist) < 25: continue
            cp = prices[sym]
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
    
    return pf.tv

# Baseline
t0 = time.time()
base = run(BASE)
base_ann = (base / CASH) ** (252/366) - 1
print('基准: ${:,.0f} (年化{:.1f}%) | {:.1f}s'.format(base, base_ann*100, time.time()-t0))

# Candidates
candidates = []
for fp in sorted(DATA_DIR.glob('*.csv')):
    sym = fp.stem
    if sym in BASE: continue
    if len(sym) > 5: continue
    if sym.startswith('^') or sym.startswith('.'): continue
    candidates.append(sym)
print('候选: {}只'.format(len(candidates)))

# Scan
results = []
for i, sym in enumerate(candidates):
    test_pool = BASE + [sym]
    try:
        final = run(test_pool)
        ann = (final / CASH) ** (252/366) - 1
        diff = (ann - base_ann) * 100
        results.append({'sym': sym, 'diff': round(diff, 2)})
    except:
        results.append({'sym': sym, 'diff': 0})
    
    if (i+1) % 50 == 0:
        pos = sum(1 for r in results if r['diff'] > 0)
        print('进度: {}/{} | 正贡献: {}只 ({:.1f}s)'.format(i+1, len(candidates), pos, time.time()-t0), flush=True)

results.sort(key=lambda x: x['diff'], reverse=True)
positives = [r for r in results if r['diff'] > 0]

print()
print('扫描完成: {}只 | 正贡献: {}只 ({:.1f}s)'.format(len(results), len(positives), time.time()-t0))

# Top 20
print()
for i, r in enumerate(positives[:20]):
    print('  {:>2}. {:6s} +{:.1f}%'.format(i+1, r['sym'], r['diff']))

# Full list for review
print()
print('=== 完整正贡献列表 ({}只) ==='.format(len(positives)))
for r in positives:
    print('{:6s} +{:.2f}%'.format(r['sym'], r['diff']))
