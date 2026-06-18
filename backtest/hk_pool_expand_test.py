"""七星港股版 池扩展回测: 当前27只 vs 当前+19新标的"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
import subprocess, csv
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/hk')
WESTOCK = str(Path.home() / '.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js')

# Download missing stocks
for code in ['01357','00522','01385']:
    fp = DATA_DIR / f'hk{code}.csv'
    if fp.exists(): continue
    result = subprocess.run(['node', WESTOCK, 'kline', f'hk{code}', '--period', 'day', '--limit', '1250'],
        capture_output=True, text=True, timeout=30, cwd=str(Path(WESTOCK).parent))
    with open(fp, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date','Open','Close','High','Low','Volume'])
        for line in reversed(result.stdout.strip().split('\n')[2:]):
            if '---' in line: continue
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) < 6: continue
            try:
                dt=parts[0]; o=float(parts[1]); c=float(parts[2]); h=float(parts[3]); l=float(parts[4]); v=int(float(parts[5]))
                if c>0 and v>0: w.writerow([dt,o,h,l,c,v])
            except: pass
    df=pd.read_csv(fp); print(f'Downloaded {code}: {len(df)}行')

# Current pool
CURRENT = ['00700','09988','01810','03690','09999','02513','00100',
    '02162','02616','09688','09969','02418','00992',
    '00981','01347','01211','00175','03692','02338','02038',
    '00388','02388','00883','02899','09633','01929','00669']

# New candidates
NEW19 = ['09618','01024','09888','00020','01357','00268','03888','00522','01385',
    '01088','00857','02688','00916','00968','00005','01299','02318','03968','00939']

# Combined pool (current + new, dedup)
COMBINED = list(dict.fromkeys(CURRENT + NEW19))
print(f'当前: {len(CURRENT)}只 | 新增: {len(NEW19)}只 | 合并: {len(COMBINED)}只')

LB, HN, CASH = 25, 7, 1000000
SLIP = 0.001; COMM = 0.001; STAMP = 0.0013; FEE = 0.0000565
START, END = '2023-04-01', '2026-04-24'

def load(pool):
    d = {}
    for c in pool:
        fp = DATA_DIR / f'hk{c}.csv'
        if fp.exists():
            df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
            if len(df) > 60: d[c] = df
    return d

def cs(cl):
    x = np.arange(len(cl)); y = np.log(cl)
    m = ~np.isnan(y) & ~np.isinf(y); xm = x[m]; ym = y[m]
    if len(xm) < 5: return -999
    s = np.polyfit(xm, ym, 1)[0]; a = np.exp(s * 250)
    f = s * xm + np.polyfit(xm, ym, 1)[1]; r = ym - f
    ssr = np.sum(r**2); sst = np.sum((ym - np.mean(ym))**2)
    return a * (1 - ssr/sst) if sst > 0 else 0

def run(pool, start, end):
    data = load(pool)
    tdates = sorted(set().union(*[set(df.index) for df in data.values()]))
    tdates = [d for d in tdates if start <= d.strftime('%Y-%m-%d') <= end]
    cash = CASH; pos = {}; trades = []; dv = []
    for date in tdates:
        ds = date.strftime('%Y-%m-%d')
        prices = {c: float(data[c].loc[date, 'close']) for c in data if date in data[c].index}
        if len(prices) < 5: continue
        ranked = []
        for c in data:
            if c not in prices: continue
            h = data[c][data[c].index < pd.Timestamp(date)]
            if len(h) < LB + 10: continue
            hp = h['close'].values[-LB:].copy()
            if hp.min() <= 0: continue
            s = cs(hp)
            if s > 0: ranked.append({'c': c, 's': s, 'p': prices[c]})
        ranked.sort(key=lambda x: x['s'], reverse=True)
        tg = set(r['c'] for r in ranked[:HN])
        for c in list(pos.keys()):
            if c not in tg and c in prices:
                p = prices[c] * (1 - SLIP); val = p * pos[c]['sh']
                cash += val - max(val*COMM, 5) - val*STAMP - val*FEE
                pnl = (p - pos[c]['cost']) / pos[c]['cost'] * 100
                trades.append({'pnl': pnl})
                del pos[c]
        tv = cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())
        for r in ranked[:HN]:
            c = r['c']
            if c not in pos and c in prices:
                bp = prices[c] * (1 + SLIP); per = tv * 0.95 / HN
                sh = int(per / bp / 100) * 100
                if sh >= 100:
                    cash -= sh*bp + max(sh*bp*COMM, 5) + sh*bp*FEE
                    pos[c] = {'sh': sh, 'cost': bp}
        dv.append({'d': ds, 'v': cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())})
    dv2 = pd.DataFrame(dv); dr = dv2['v'].pct_change().dropna()
    tr = round((dv2['v'].iloc[-1] / CASH - 1) * 100, 1)
    cagr = round(((dv2['v'].iloc[-1] / CASH) ** (252 / max(len(dr), 1)) - 1) * 100, 1)
    md = round((dv2['v'] / dv2['v'].cummax() - 1).min() * 100, 1)
    sp = round(dr.mean() / dr.std() * np.sqrt(252), 2)
    sells = [t for t in trades if abs(t['pnl']) > 0.001]
    wr = round(sum(1 for t in sells if t['pnl'] > 0) / max(len(sells), 1) * 100, 1)
    return tr, cagr, md, sp, len(trades), wr, len(data)

print(f'\n3年回测: {START} ~ {END}')
hdr = f'{"池":25s} {"只":>3} {"累计":>8} {"CAGR":>7} {"回撤":>6} {"夏普":>5} {"交易":>5} {"胜率":>5}'
print(hdr)
print('-' * 70)
for name, pool in [('当前27只', CURRENT), ('当前+19新标的', COMBINED)]:
    tr, cg, md, sp, nt, wr, ld = run(pool, START, END)
    print(f'{name:25s} {ld:>3} {tr:>+7.1f}% {cg:>6.1f}% {md:>5.1f}% {sp:>5.2f} {nt:>5} {wr:>5.1f}%')
