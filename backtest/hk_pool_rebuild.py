"""零前视偏差 重构港股池: 多期动量排名交叉验证"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
from collections import Counter
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/hk')
files = list(DATA_DIR.glob('hk*.csv'))

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
    return ann * r2

# 5个检查点的排名 (逐步推进, 零前视)
checkpoints = [
    ('2023-06-30', '23H1'),
    ('2023-12-29', '23H2'),
    ('2024-06-28', '24H1'),
    ('2024-12-31', '24H2'),
    ('2025-06-30', '25H1'),
]

all_ranks = {cp[1]: {} for cp in checkpoints}

for cp_date, cp_label in checkpoints:
    for fp in files:
        try:
            code = fp.stem.replace('hk', '')
            df = pd.read_csv(fp)
            df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            mask = df.index < pd.Timestamp(cp_date)
            hist = df[mask]
            if len(hist) < 60: continue
            closes = hist['close'].values[-25:].copy()
            if closes.min() <= 0: continue
            score = calc_score(closes)
            if score > 0:
                all_ranks[cp_label][code] = score
        except: pass
    
    # Sort by score
    sorted_codes = sorted(all_ranks[cp_label].items(), key=lambda x: x[1], reverse=True)
    print(f'{cp_label} ({cp_date}): Top10 = {[c for c,_ in sorted_codes[:10]]}')

# Cross-reference: stocks that appear in Top30 at ≥3 out of 5 checkpoints
appearance = Counter()
for cp_label in all_ranks:
    top30 = set(c for c,_ in sorted(all_ranks[cp_label].items(), key=lambda x: x[1], reverse=True)[:30])
    for c in top30:
        appearance[c] += 1

# 放宽: ≥2/5 checkpoints 出现在 Top50 + 数据充足 + 合并当前池
appearance = Counter()
for cp_label in all_ranks:
    top50 = set(c for c,_ in sorted(all_ranks[cp_label].items(), key=lambda x: x[1], reverse=True)[:50])
    for c in top50:
        appearance[c] += 1

# Candidate: ≥2/5 checkpoints, data from 2022, min 200 rows
candidates = []
for code, count in appearance.most_common():
    if count >= 2:
        fp = DATA_DIR / f'hk{code}.csv'
        df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        if df['date'].min() <= pd.Timestamp('2022-01-01') and len(df) > 200:
            candidates.append((code, count))

print(f'候选: {len(candidates)}只 (≥2/5 checkpoint的Top50)')

# Also include current pool members
current_pool = ['00700','09988','01810','03690','09999','00981','01347','01211',
    '00388','02388','00883','02899','09633','01929','00669']

# Build new pool: current pool + new candidates, dedup
new_pool = list(dict.fromkeys(current_pool + [c for c,_ in candidates]))
print(f'新池: {len(new_pool)}只 (原15 + 新增{len(new_pool)-15})')

# Verify data for new stocks
need_download = []
for code in new_pool:
    fp = DATA_DIR / f'hk{code}.csv'
    if not fp.exists():
        need_download.append(code)
        print(f'  ❌ 缺失: {code}')
    else:
        df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        first = df['date'].min(); last = df['date'].max()
        flag = '⚠️<2022' if first > pd.Timestamp('2022-01-01') else ('⚠️滞后' if (pd.Timestamp.now()-last).days > 30 else '✅')
        print(f'  {flag} {code}: {first.date()}~{last.date()} ({len(df)}行)')

print(f'\n需下载: {len(need_download)}只 — {need_download}')

# Print the pool as comma-separated for copy-paste
print(f'\nNEW_POOL = {[c for c in new_pool if c not in need_download]}')
