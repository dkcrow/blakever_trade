import pandas as pd, numpy as np
from pathlib import Path
DATA_DIR = Path('data/storage/stock_data/hk')
codes = ['09866','09868','02015']
names = {'09866':'蔚来','09868':'小鹏','02015':'理想'}

def calc_score(closes):
    if len(closes) < 5: return -999
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

for code in codes:
    fp = DATA_DIR / f'hk{code}.csv'
    if not fp.exists():
        print(f'{code} {names[code]}: 无数据')
        continue
    df = pd.read_csv(fp)
    df.columns = [c.lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    last = df.index.max()
    closes = df['close'].values
    score = calc_score(closes[-25:]) if len(closes) >= 25 else -999
    last6m = df[df.index >= (df.index.max() - pd.Timedelta(days=180))]
    ret6m = (last6m['close'].iloc[-1] / last6m['close'].iloc[0] - 1) * 100 if len(last6m) > 1 else 0
    ytd = df[df.index >= '2026-01-01']
    ret_ytd = (ytd['close'].iloc[-1] / ytd['close'].iloc[0] - 1) * 100 if len(ytd) > 1 else 0
    print(f'{code} {names[code]}: 数据至{last.strftime("%Y-%m-%d")} | {len(df)}行 | 得分{score:.3f} | 6月{ret6m:+.1f}% | YTD{ret_ytd:+.1f}% | 现价HK${df["close"].iloc[-1]:.2f}')
