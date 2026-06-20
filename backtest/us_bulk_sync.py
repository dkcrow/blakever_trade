"""批量同步所有美股数据到最新 (WeStock → CSV)"""
import subprocess, os
from pathlib import Path
from datetime import datetime
import pandas as pd

WESTOCK_SCRIPT = str(Path.home() / '.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js')
WS_DIR = os.path.dirname(WESTOCK_SCRIPT)
DATA_DIR = Path('data/storage/stock_data/us')

files = sorted(DATA_DIR.glob('*.csv'))
total = len(files)
synced = 0
skipped = 0
errors = 0

for i, fp in enumerate(files):
    sym = fp.stem
    # Skip non-stock files (indices, ETFs with special chars)
    if len(sym) > 5 or sym.startswith('^') or sym.startswith('.'):
        skipped += 1
        continue
    
    # Check if stale
    try:
        df = pd.read_csv(fp)
        if 'Date' in df.columns:
            last = pd.to_datetime(df['Date'].iloc[-1])
        elif 'date' in df.columns:
            df.columns = [c.lower() for c in df.columns]
            last = pd.to_datetime(df['date'].max())
        else:
            last = pd.Timestamp('2000-01-01')
        days_old = (pd.Timestamp('2026-06-18') - last).days
        if days_old <= 3:
            skipped += 1
            continue
    except:
        pass
    
    # Fetch fresh data
    code = f'us{sym}'
    try:
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT, 'kline', code, '--period', 'day', '--limit', '600'],
            capture_output=True, text=True, timeout=40, cwd=WS_DIR)
        if result.returncode != 0:
            errors += 1
            continue
        
        lines = result.stdout.strip().split('\n')
        rows = []
        in_table = False
        for line in lines:
            line = line.strip()
            if line.startswith('| date'): in_table = True; continue
            if not line.startswith('|') or line.startswith('| --'): continue
            if in_table:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 5:
                    try: rows.append({'Date': parts[0], 'Open': float(parts[1]), 'Last': float(parts[2]), 'High': float(parts[3]), 'Low': float(parts[4]), 'Volume': int(float(parts[5])) if parts[5] else 0})
                    except: pass
        
        if rows:
            new_df = pd.DataFrame(rows).sort_values('Date')
            # Merge with existing
            if fp.exists():
                old_df = pd.read_csv(fp)
                cols = ['Date','Open','Last','High','Low','Volume']
                if set(cols).issubset(set(old_df.columns)):
                    combined = pd.concat([old_df[cols], new_df]).drop_duplicates(subset=['Date'], keep='last')
                    combined.sort_values('Date').to_csv(fp, index=False)
                else:
                    new_df.to_csv(fp, index=False)
            else:
                new_df.to_csv(fp, index=False)
            synced += 1
        else:
            errors += 1
    except Exception as e:
        errors += 1
    
    if (synced + skipped + errors) % 50 == 0:
        print('进度: {}/{} (同步{} 跳过{} 错误{})'.format(synced+skipped+errors, total, synced, skipped, errors), flush=True)

print('\n完成! 总计{} | 同步{} | 跳过{} | 错误{}'.format(total, synced, skipped, errors))
