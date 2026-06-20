"""刷新25只美股数据: 从WeStock拉取K线并更新CSV"""
import subprocess, os, sys, json
from pathlib import Path
from datetime import datetime
import pandas as pd

WESTOCK_SCRIPT = str(Path.home() / '.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js')
DATA_DIR = Path('data/storage/stock_data/us')

POOL = 'NVDA,AVGO,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,CSCO,HOOD'.split(',')

for sym in POOL:
    code = f'us{sym}'
    print(f'刷新 {sym}...', end=' ', flush=True)
    try:
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT, 'kline', code, '--period', 'day', '--limit', '600'],
            capture_output=True, text=True, timeout=40,
            cwd=os.path.dirname(WESTOCK_SCRIPT))
        if result.returncode != 0:
            print(f'ERROR: {result.stderr[:100]}')
            continue
        
        # Parse markdown table
        lines = result.stdout.strip().split('\n')
        rows = []
        in_table = False
        for line in lines:
            line = line.strip()
            if line.startswith('| date'):
                in_table = True
                continue
            if not line.startswith('|') or line.startswith('| --'):
                continue
            if in_table:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 5:
                    try:
                        date = parts[0]
                        close = parts[3]  # 'last' column is the 4th
                        rows.append({'Date': date, 'Close': float(close)})
                    except: pass
        
        if rows:
            new_df = pd.DataFrame(rows)
            new_df = new_df.sort_values('Date')
            
            # Merge with existing if available
            fp = DATA_DIR / f'{sym}.csv'
            if fp.exists():
                old_df = pd.read_csv(fp)
                if 'Date' in old_df.columns:
                    # Combine and deduplicate
                    combined = pd.concat([old_df, new_df]).drop_duplicates(subset=['Date'], keep='last')
                    combined = combined.sort_values('Date')
                    combined.to_csv(fp, index=False)
                else:
                    new_df.to_csv(fp, index=False)
            else:
                new_df.to_csv(fp, index=False)
            
            print('OK (' + str(len(rows)) + '行, ' + rows[0]['Date'] + '~' + rows[-1]['Date'] + ')')
        else:
            print('无数据')
    except Exception as e:
        print(f'ERROR: {e}')

print('\n完成!')
