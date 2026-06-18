"""七星港股版 池优化回测 — 27只 vs 精简15只, 3年期"""
import pandas as pd, numpy as np, math, json, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/hk')
OUT_DIR = Path('backtest/results_hk')
OUT_DIR.mkdir(parents=True, exist_ok=True)

HK_POOL_27 = [
    '00700','09988','09618','01810','09961','01024','03690','09999',
    '00981','02382','02018','01347','02015','01211','09866',
    '00388','01299','02388','00883','02899','09633','02020','01929',
    '02269','01801','00669','01919',
]

# 精简15只: 仅保留均盈亏>0的, 移除12只负贡献
HK_POOL_15 = [
    '00700','09988','01810','03690','09999',       # 互联网5
    '00981','01347',                                 # 半导体2
    '01211',                                         # 新能源车1
    '00388','02388',                                 # 金融2
    '00883','02899',                                 # 能源2
    '09633','01929',                                 # 消费2
    '00669',                                         # 工业1
]

LB, HN, CASH = 25, 7, 1000000
SLIP = 0.001
HK_COMM, HK_STAMP, HK_FEE = 0.001, 0.0013, 0.0000565

def load_data(pool):
    d = {}
    for code in pool:
        fp = DATA_DIR / f'hk{code}.csv'
        if fp.exists():
            df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
            if len(df) > 60: d[code] = df
    return d

def calc_score(closes):
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); xm = x[mask]; ym = y[mask]
    if len(xm) < 5: return -999
    slope = np.polyfit(xm, ym, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * xm + np.polyfit(xm, ym, 1)[1]
    r = ym - fitted
    ssr = np.sum(r**2); sst = np.sum((ym - np.mean(ym))**2)
    r2 = 1 - ssr/sst if sst > 0 else 0
    return ann * r2

def run(pool, start, end):
    data = load_data(pool)
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
            m = data[c].index < pd.Timestamp(date); h = data[c][m]
            if len(h) < LB + 10: continue
            hp = h['close'].values[-LB:].copy()
            if np.any(hp <= 0): continue
            s = calc_score(hp)
            if s > 0: ranked.append({'c': c, 's': s, 'p': prices[c]})
        ranked.sort(key=lambda x: x['s'], reverse=True)
        tg = set(r['c'] for r in ranked[:HN])
        for c in list(pos.keys()):
            if c not in tg and c in prices:
                p = prices[c] * (1 - SLIP)
                val = p * pos[c]['sh']
                cf = max(val * HK_COMM, 5)
                stamp = val * HK_STAMP
                fee = val * HK_FEE
                cash += val - cf - stamp - fee
                pnl = (p - pos[c]['cost']) / pos[c]['cost'] * 100
                trades.append({'d': ds, 'a': 'SELL', 'c': c, 'pnl': round(pnl, 2), 'r': '调出Top7'})
                del pos[c]
        tv = cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())
        for r in ranked[:HN]:
            c = r['c']
            if c not in pos and c in prices:
                bp = prices[c] * (1 + SLIP); per = tv * 0.95 / HN
                sh = int(per / bp / 100) * 100
                if sh >= 100:
                    val = sh * bp; cf = max(val * HK_COMM, 5); fee = val * HK_FEE
                    cash -= val + cf + fee
                    pos[c] = {'sh': sh, 'cost': bp}
        dv.append({'d': ds, 'v': cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())})
    dv_df = pd.DataFrame(dv)
    tr = (dv_df['v'].iloc[-1] / CASH - 1) * 100
    dr = dv_df['v'].pct_change().dropna()
    ar = (1 + dr.mean())**252 - 1
    md = (dv_df['v'] / dv_df['v'].cummax() - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    sells = [t for t in trades if t['a'] == 'SELL']
    wr = sum(1 for t in sells if t.get('pnl', 0) > 0) / max(len(sells), 1) * 100
    return {'total': tr, 'annual': ar*100, 'dd': md, 'sharpe': sp, 'trades': len(trades), 'wr': wr, 'loaded': len(data)}

START = '2023-04-01'; END = '2026-04-24'
print(f'3年回测: {START} ~ {END}')
print()

for name, pool in [('原池27只', HK_POOL_27), ('精简15只', HK_POOL_15)]:
    print(f'测试: {name} ({len(pool)}只)... ', end='', flush=True)
    r = run(pool, START, END)
    print(f'+{r["total"]:.1f}% 年化{r["annual"]:.1f}% 回撤{r["dd"]:.1f}% 夏普{r["sharpe"]:.2f} {r["trades"]}笔 胜率{r["wr"]:.1f}% 加载{r["loaded"]}只')

# 分年
print('\n=== 分年收益 ===')
for name, pool in [('原池27只', HK_POOL_27), ('精简15只', HK_POOL_15)]:
    data = load_data(pool)
    tdates = sorted(set().union(*[set(df.index) for df in data.values()]))
    tdates = [d for d in tdates if START <= d.strftime('%Y-%m-%d') <= END]
    cash = CASH; pos = {}; dv = []
    for date in tdates:
        ds = date.strftime('%Y-%m-%d')
        prices = {c: float(data[c].loc[date, 'close']) for c in data if date in data[c].index}
        if len(prices) < 5: continue
        ranked = []
        for c in data:
            if c not in prices: continue
            m = data[c].index < pd.Timestamp(date); h = data[c][m]
            if len(h) < LB + 10: continue
            hp = h['close'].values[-LB:].copy()
            if np.any(hp <= 0): continue
            s = calc_score(hp)
            if s > 0: ranked.append({'c': c, 's': s, 'p': prices[c]})
        ranked.sort(key=lambda x: x['s'], reverse=True)
        tg = set(r['c'] for r in ranked[:HN])
        for c in list(pos.keys()):
            if c not in tg and c in prices:
                p = prices[c] * (1 - SLIP); val = p * pos[c]['sh']
                cash += val - max(val * HK_COMM, 5) - val * HK_STAMP - val * HK_FEE
                del pos[c]
        tv = cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())
        for r in ranked[:HN]:
            c = r['c']
            if c not in pos and c in prices:
                bp = prices[c] * (1 + SLIP); per = tv * 0.95 / HN
                sh = int(per / bp / 100) * 100
                if sh >= 100: cash -= sh*bp + max(sh*bp*HK_COMM,5) + sh*bp*HK_FEE; pos[c] = {'sh': sh, 'cost': bp}
        dv.append({'d': ds, 'v': cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())})
    dv_df = pd.DataFrame(dv)
    print(f'\n{name}:')
    for yr in [2023, 2024, 2025, 2026]:
        yd = dv_df[dv_df['d'].str.startswith(str(yr))]
        if len(yd) < 2: continue
        yr_ret = (yd['v'].iloc[-1] / yd['v'].iloc[0] - 1) * 100
        print(f'  {yr}: {yr_ret:+.1f}% ({len(yd)}天)')
