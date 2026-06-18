import subprocess, csv
from pathlib import Path
WESTOCK = str(Path.home() / '.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js')
HK_DIR = Path('data/storage/stock_data/hk')
import pandas as pd
for code in ['02513','00100']:
    result = subprocess.run(['node', WESTOCK, 'kline', f'hk{code}', '--period', 'day', '--limit', '500'],
        capture_output=True, text=True, timeout=30, cwd=str(Path(WESTOCK).parent))
    fp = HK_DIR / f'hk{code}.csv'
    with open(fp, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['Date','Open','Close','High','Low','Volume'])
        for line in reversed(result.stdout.strip().split('\n')[2:]):
            if '---' in line: continue
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) < 6: continue
            try:
                dt=parts[0]; o=float(parts[1]); c=float(parts[2])
                h=float(parts[3]); l=float(parts[4]); v=int(float(parts[5]))
                if c>0 and v>0: w.writerow([dt,o,h,l,c,v])
            except: pass
    df=pd.read_csv(fp); print(f'hk{code}: {len(df)}行, {df.iloc[0,0]} ~ {df.iloc[-1,0]}, 最新HK${df.iloc[-1,2]:.0f}')
