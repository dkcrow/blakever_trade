import pandas as pd
import os

# V7 existing stocks
v7 = ['NVDA','AMD','MU','AVGO','TSLA','AAPL','GOOG','AMZN','KO','NEM','XOM','AEP','JPM','GS','BRK-B']

# Find new stocks from us directory
us_dir = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us'
results = []

for f in os.listdir(us_dir):
    if not f.endswith('.csv'):
        continue
    s = f.replace('.csv', '')
    if s in v7:
        continue
    try:
        df = pd.read_csv(os.path.join(us_dir, f))
        c = df['Close'] if 'Close' in df.columns else df['close']
        if len(c) < 500:
            continue
        ret = (c.iloc[-1] / c.iloc[0] - 1) * 100
        # filter extreme
        returns = c.pct_change().dropna()
        vol = returns.std() * (252**0.5) * 100
        if vol > 80 or vol < 15:
            continue
        results.append({'sym': s, 'ret': ret, 'vol': vol})
    except:
        continue

# Sort by return
results.sort(key=lambda x: x['ret'], reverse=True)
print('Top new stocks (10Y return, filtered vol 15-80%):')
for r in results[:25]:
    print(f"  {r['sym']}: {r['ret']:.1f}% (vol: {r['vol']:.1f}%)")
