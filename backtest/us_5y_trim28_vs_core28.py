"""精简27只 vs 精选核心28只 — 5年回测对比"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/us')
LB, HN, CASH, SLIP, COMM = 25, 7, 100000, 0.0005, 0.005

# 精简27只 (纯无偏见: 从40只删13只弱股)
TRIM27 = ['NVDA','AVGO','AMD','MU','LRCX','ARM','LITE',
    'NFLX','GOOGL','NOW','CRWD','ORCL',
    'DDOG','SNPS','EOG','OKE','NEM','FCX',
    'CAT','GE','RTX','AMT','PANW','ZS','NET','IONQ','RKLB']

# 精选核心28只 (含后视镜新增6只)
CORE28 = ['NVDA','AVGO','AMD','MU','LRCX','ARM','LITE','IONQ','RKLB',
    'GOOGL','ORCL','SNPS','OKE','NEM','FCX','CAT','GE',
    'DDOG','CRWD','PANW','ZS','NET',
    'MRVL','QCOM','COIN','QBTS','CEG','VST']

# 原40只基准
BASE40 = ['NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','AAPL','TSM','LITE',
    'META','AMZN','NFLX','GOOGL','MSFT','CRM','NOW','CRWD','ORCL','PLTR',
    'DDOG','SNPS','XOM','CVX','COP','EOG','OKE','NEM','FCX','LIN','CAT','GE',
    'RTX','PLD','AMT','PANW','ZS','NET','IONQ','RKLB']

def load(symbols):
    d = {}
    for s in symbols:
        fp = DATA_DIR / f'{s}.csv'
        if fp.exists():
            df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
            if len(df) > 60: d[s] = df
    return d

def calc(closes):
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); xm = x[mask]; ym = y[mask]
    if len(xm) < 5: return -999
    s = np.polyfit(xm, ym, 1)[0]; a = np.exp(s * 250)
    f = s * xm + np.polyfit(xm, ym, 1)[1]; r = ym - f
    ssr = np.sum(r**2); sst = np.sum((ym - np.mean(ym))**2)
    r2 = 1 - ssr/sst if sst > 0 else 0
    return a * r2

def run(pool, start, end, label=''):
    data = load(pool)
    tdates = sorted(set().union(*[set(df.index) for df in data.values()]))
    tdates = [d for d in tdates if start <= d.strftime('%Y-%m-%d') <= end]
    cash = CASH; pos = {}; trades = []; dv = []; dd_history = []
    for date in tdates:
        ds = date.strftime('%Y-%m-%d')
        prices = {c: float(data[c].loc[date, 'close']) for c in data if date in data[c].index}
        if len(prices) < 7: continue
        ranked = []
        for c in data:
            if c not in prices: continue
            m = data[c].index < pd.Timestamp(date); h = data[c][m]
            if len(h) < LB + 10: continue
            hp = h['close'].values[-LB:].copy()
            if np.any(hp <= 0): continue
            s = calc(hp)
            if s > 0: ranked.append({'c': c, 's': s, 'p': prices[c]})
        ranked.sort(key=lambda x: x['s'], reverse=True)
        tg = set(r['c'] for r in ranked[:HN])
        for c in list(pos.keys()):
            if c not in tg and c in prices:
                p = prices[c] * (1 - SLIP); val = p * pos[c]['sh']; cf = pos[c]['sh'] * COMM
                cash += val - cf; pnl = (p - pos[c]['cost']) / pos[c]['cost'] * 100
                trades.append({'d': ds, 'a': 'SELL', 'c': c, 'pnl': pnl})
                del pos[c]
        tv = cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())
        for r in ranked[:HN]:
            c = r['c']
            if c not in pos and c in prices:
                bp = prices[c] * (1 + SLIP); per = tv * 0.95 / HN
                sh = int(per / bp)
                if sh > 0:
                    cost = sh * bp + sh * COMM; cash -= cost
                    pos[c] = {'sh': sh, 'cost': bp}
        val = cash + sum(p['sh'] * prices.get(c, p['cost']) for c, p in pos.items())
        dv.append({'d': ds, 'v': val})
        dd_history.append((ds, val))

    dv_df = pd.DataFrame(dv)
    tr = (dv_df['v'].iloc[-1] / CASH - 1) * 100
    dr = dv_df['v'].pct_change().dropna()
    ar = (1 + dr.mean())**252 - 1
    cm = dv_df['v'].cummax()
    md = ((dv_df['v'] - cm) / cm * 100).min()
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    sells = [t for t in trades if t['a'] == 'SELL']
    wr = sum(1 for t in sells if t.get('pnl', 0) > 0) / max(len(sells), 1) * 100

    # 分年
    yearly = {}
    for yr in [2021, 2022, 2023, 2024, 2025, 2026]:
        yd = dv_df[dv_df['d'].str.startswith(str(yr))]
        if len(yd) < 2: continue
        yret = (yd['v'].iloc[-1] / yd['v'].iloc[0] - 1) * 100
        yearly[yr] = (yret, len(yd))

    # 最大回撤详情
    dd_idx = ((dv_df['v'] - cm) / cm * 100).idxmin()
    dd_date = dv_df.iloc[dd_idx]['d']
    peak_date = dv_df.iloc[:dd_idx]['v'].idxmax()
    peak_date_str = dv_df.iloc[peak_date]['d']

    return {
        'label': label, 'pool_size': len(pool), 'loaded': len(data),
        'total': tr, 'annual': ar * 100, 'dd': md, 'sharpe': sp,
        'trades': len(trades), 'wr': wr, 'tdays': len(tdates),
        'yearly': yearly, 'dd_date': dd_date, 'peak_date': peak_date_str,
        'start': tdates[0].strftime('%Y-%m-%d'), 'end': tdates[-1].strftime('%Y-%m-%d'),
    }

START, END = '2021-06-01', '2026-06-13'
pools = [('40只基准', BASE40), ('精简27只', TRIM27), ('精选核心28只', CORE28)]

results = []
for name, pool in pools:
    print(f'测试: {name} ({len(pool)}只)... ', end='', flush=True)
    r = run(pool, START, END, name)
    results.append(r)
    print(f'+{r["total"]:.1f}% | 年化{r["annual"]:.1f}% | 回撤{r["dd"]:.1f}% | 夏普{r["sharpe"]:.2f} | {r["trades"]}笔 | 胜率{r["wr"]:.1f}%')

# 汇总表
print(f'\n{"="*85}')
print(f'  {"池":<18} {"累计":>9} {"年化":>7} {"回撤":>6} {"夏普":>5} {"交易":>5} {"胜率":>5}')
print(f'  {"-"*60}')
for r in results:
    vs = f'+{r["total"]-results[0]["total"]:.0f}%' if r != results[0] else '基准'
    d = '+' if r['dd'] > results[0]['dd'] else ''
    arr = '↓' if r['dd'] > results[0]['dd'] else ('↑' if r['dd'] < results[0]['dd'] else '')
    print(f'  {r["label"]:<18} {r["total"]:>+8.1f}% {r["annual"]:>6.1f}% {r["dd"]:>5.1f}%{arr} {r["sharpe"]:>5.2f} {r["trades"]:>5} {r["wr"]:>5.1f}%')

# 分年
print(f'\n{"="*85}')
print(f'  {"池":<18} {"2021":>8} {"2022":>8} {"2023":>8} {"2024":>8} {"2025":>8} {"2026":>8}')
print(f'  {"-"*70}')
for r in results:
    yy = r['yearly']
    row = f'  {r["label"]:<18}'
    for yr in [2021, 2022, 2023, 2024, 2025, 2026]:
        v = yy.get(yr)
        if v: row += f' {v[0]:>+7.1f}%'
        else: row += '       -'
    print(row)

# 最大回撤详情
print(f'\n=== 最大回撤详情 ===')
for r in results:
    print(f'  {r["label"]}: {r["dd"]:.1f}% ({r["peak_date"]} → {r["dd_date"]})')
