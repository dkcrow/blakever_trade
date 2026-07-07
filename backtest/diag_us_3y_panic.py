# 诊断3年区间大盘恐慌触发
import pandas as pd, numpy as np
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')
import akshare as ak

DATA_DIR = Path('data/storage/stock_data/us')
POOL = ['NVDA','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS',
        'EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB',
        'SPCX','COHR','HOOD','WDC','ARM','STX']

all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        dcol = [c for c in df.columns if c.lower().strip()=='date'][0]
        df['date'] = pd.to_datetime(df[dcol])
        df = df.set_index('date').sort_index()
        all_data[sym] = df

spx = ak.index_us_stock_sina(symbol='.INX')
spx['date'] = pd.to_datetime(spx['date']); spx = spx.set_index('date').sort_index()
ndx = ak.index_us_stock_sina(symbol='.NDX')
ndx['date'] = pd.to_datetime(ndx['date']); ndx = ndx.set_index('date').sort_index()

trade_dates = sorted(set.union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if '2023-06-25' <= d.strftime('%Y-%m-%d') <= '2026-06-25']
print(f'3年交易日: {len(trade_dates)}')

# 每月检查
print('\n=== 月度恐慌状态 (MA25) ===')
for year in range(2023, 2027):
    for month in range(1, 13):
        if year == 2023 and month < 7: continue
        if year == 2026 and month > 6: continue
        dt = pd.Timestamp(f'{year}-{month:02d}-15')
        sm = spx.index <= dt; nm = ndx.index <= dt
        if sm.sum() < 25 or nm.sum() < 25: continue
        sc = spx.loc[sm, 'close'].iloc[-1]; sma = spx.loc[sm, 'close'].iloc[-25:].mean()
        nc = ndx.loc[nm, 'close'].iloc[-1]; nma = ndx.loc[nm, 'close'].iloc[-25:].mean()
        if sc < sma and nc < nma:
            print(f'  {year}-{month:02d}: PANIC  SPX={sc:.0f}<{sma:.0f}  NDX={nc:.0f}<{nma:.0f}')

# 统计
panic_count = 0
panic_by_year = {2023:0, 2024:0, 2025:0, 2026:0}
date_by_year = {2023:0, 2024:0, 2025:0, 2026:0}
for dt in trade_dates:
    sm = spx.index <= dt; nm = ndx.index <= dt
    if sm.sum() < 25 or nm.sum() < 25: continue
    sc = spx.loc[sm, 'close'].iloc[-1]; sma = spx.loc[sm, 'close'].iloc[-25:].mean()
    nc = ndx.loc[nm, 'close'].iloc[-1]; nma = ndx.loc[nm, 'close'].iloc[-25:].mean()
    date_by_year[dt.year] = date_by_year.get(dt.year,0) + 1
    if sc < sma and nc < nma:
        panic_count += 1
        panic_by_year[dt.year] = panic_by_year.get(dt.year,0) + 1

print(f'\n总恐慌天: {panic_count}/{len(trade_dates)} ({panic_count/len(trade_dates)*100:.1f}%)')
for y in [2023, 2024, 2025, 2026]:
    t = date_by_year.get(y,0)
    p = panic_by_year.get(y,0)
    if t: print(f'  {y}: {p}/{t} ({p/t*100:.1f}%)')

# 恐慌段
print('\n=== 恐慌段 ===')
segments = []
in_panic = False
for dt in trade_dates:
    sm = spx.index <= dt; nm = ndx.index <= dt
    if sm.sum() < 25 or nm.sum() < 25: continue
    sc = spx.loc[sm, 'close'].iloc[-1]; sma = spx.loc[sm, 'close'].iloc[-25:].mean()
    nc = ndx.loc[nm, 'close'].iloc[-1]; nma = ndx.loc[nm, 'close'].iloc[-25:].mean()
    is_panic = sc < sma and nc < nma
    if is_panic and not in_panic:
        segments.append({'start': dt, 'end': None, 'days': 0})
        in_panic = True
    if in_panic:
        segments[-1]['days'] += 1
        segments[-1]['end'] = dt
    if not is_panic and in_panic:
        in_panic = False

for seg in segments:
    s = seg['start'].strftime('%Y-%m-%d')
    e = seg['end'].strftime('%Y-%m-%d')
    print(f'  {s} ~ {e}: {seg["days"]}天')
