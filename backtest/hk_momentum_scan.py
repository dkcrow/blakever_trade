"""扫描全部港股动量排名, 对比当前池"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/hk')
files = list(DATA_DIR.glob('hk*.csv'))
print(f'Total HK stocks: {len(files)}')

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); xm = x[mask]; ym = y[mask]
    if len(xm) < 5: return -999
    slope = np.polyfit(xm, ym, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * xm + np.polyfit(xm, ym, 1)[1]
    r = ym - fitted
    ssr = np.sum(r**2); sst = np.sum((ym - np.mean(ym))**2)
    r2 = 1 - ssr/sst if sst > 0 else 0
    return ann * r2, (ann-1)*100, r2

scores = []
for fp in files:
    try:
        code = fp.stem.replace('hk', '')
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) < 50: continue
        closes = df['close'].values[-25:]
        if closes.min() <= 0: continue
        score, ann, r2 = calc_score(closes)
        last_p = closes[-1]
        y1 = 0
        if len(df) >= 252:
            y1 = (closes[-1] / df['close'].values[-252] - 1) * 100
        if score > 0:
            scores.append({'code': code, 'score': score, 'ann': ann, 'r2': r2, 'price': last_p, 'y1': y1})
    except Exception as e:
        pass

scores.sort(key=lambda x: x['score'], reverse=True)

pool = ['00700','09988','01810','03690','09999','00981','01347','01211',
    '00388','02388','00883','02899','09633','01929','00669']

print(f'Top30 momentum stocks:')
for i, s in enumerate(scores[:30]):
    mark = 'IN' if s['code'] in pool else '  '
    print(f'{mark} #{i+1:2d} {s["code"]:>6s} score={s["score"]:8.1f} ann={s["ann"]:>+6.0f}% R2={s["r2"]:.3f} HK${s["price"]:.1f} 1Y={s["y1"]:>+6.0f}%')

in_top20 = sum(1 for s in scores[:20] if s['code'] in pool)
in_top10 = sum(1 for s in scores[:10] if s['code'] in pool)
print(f'\n池中在Top10: {in_top10}/10 | Top20: {in_top20}/20 | Top30: {sum(1 for s in scores[:30] if s["code"] in pool)}/30')
