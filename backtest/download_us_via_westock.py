#!/usr/bin/env python3
"""
使用 WeStock Data 下载缺失的标普500/纳指100成分股数据
"""

import subprocess, os, sys, time, re
from pathlib import Path
from io import StringIO
import pandas as pd

PROJECT_ROOT = Path('c:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
SKILL_DIR = Path('c:/Users/blakehao/.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data')
NODE = 'node'
SCRIPT = str(SKILL_DIR / 'scripts' / 'index.js')

os.makedirs(DATA_DIR, exist_ok=True)

# 71 missing symbols 按重要性排序
MISSING = [
    # 高优先级: 大盘+重要科技股
    'CSCO','NOW','UBER','TJX','DE','DOW','FCX','KKR','MCO','EBAY',
    'NSC','UAL','OTIS','SMCI','TT','VLTO','VMC','VTR','LEN','ZBRA',
    'DG','DLTR','WH','LOW',
    # 中等优先级
    'AES','AIZ','APTV','ARE','BG','CAG','CAH','CASY','COHR','CPT',
    'CRL','CSGP','DGX','DPZ','ERIE','EXPE','GEN','GIS','HBAN','HII',
    'HOOD','HST','IBKR','INVH','LDOS','LH','LITE','MRSH','MTB','MTD',
    'NCLH','NRG','NTAP','NWS','NWSA','PKG','PODD','PSKY','PTC','Q',
    'REG','RJF','SATS','SJM','STT','TECH','TKO','TYL','ULTA','WTW',
]

def download_one(sym):
    """下载单只股票K线数据"""
    fp = DATA_DIR / f'{sym}.csv'
    
    # 如果已有足够数据，跳过
    if fp.exists():
        try:
            df = pd.read_csv(fp)
            df['Date'] = pd.to_datetime(df['Date'])
            latest = df['Date'].max()
            target_start = pd.Timestamp('2023-06-01')
            rows = (df['Date'] >= target_start).sum()
            if latest >= pd.Timestamp('2026-04-01') and rows >= 400:
                return 'skip_ok', 0
        except:
            pass
    
    # 读取已有数据(用于增量)
    existing = {}
    if fp.exists():
        try:
            df_ex = pd.read_csv(fp)
            for _, row in df_ex.iterrows():
                existing[row['Date']] = row.to_dict()
        except:
            pass
    
    # 下载
    try:
        result = subprocess.run(
            [NODE, SCRIPT, 'kline', f'us{sym}', '--period', 'day', '--limit', '2000'],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        
        if result.returncode != 0:
            return f'err:{result.stderr[:80]}', 0
        
        # 解析Markdown表格
        lines = result.stdout.strip().split('\n')
        data_lines = []
        in_table = False
        for line in lines:
            line = line.strip()
            if line.startswith('|') and 'date' not in line.lower() and '---' not in line:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 6:
                    data_lines.append(parts)
        
        if not data_lines:
            return 'no_data', 0
        
        # 写入CSV
        new_count = 0
        mode = 'a' if fp.exists() else 'w'
        with open(fp, mode, encoding='utf-8') as f:
            if mode == 'w':
                f.write('Date,Open,High,Low,Close,Volume\n')
            
            for parts in data_lines:
                date = parts[0]
                if date in existing:
                    continue  # 跳过已有日期
                try:
                    dt_str = f'{date}'
                    open_p = round(float(parts[1]), 2)
                    high = round(float(parts[3]), 2)
                    low = round(float(parts[4]), 2)
                    close = round(float(parts[2]), 2)  # 'last' is close
                    vol = int(float(parts[5]))
                    f.write(f'{dt_str},{open_p},{high},{low},{close},{vol}\n')
                    new_count += 1
                except (ValueError, IndexError):
                    continue
        
        return 'ok', new_count
        
    except subprocess.TimeoutExpired:
        return 'timeout', 0
    except Exception as e:
        return f'error:{e}', 0


def main():
    print(f'下载 {len(MISSING)} 只缺失成分股 (WeStock Data)')
    print('=' * 60)
    
    ok = 0
    skip = 0
    fail = []
    total_new = 0
    
    for i, sym in enumerate(MISSING):
        status, new_rows = download_one(sym)
        
        if status == 'ok':
            ok += 1
            total_new += new_rows
            if new_rows > 0:
                print(f'  [{i+1}/{len(MISSING)}] {sym}: +{new_rows}行')
        elif status == 'skip_ok':
            skip += 1
        else:
            fail.append((sym, status))
            print(f'  [{i+1}/{len(MISSING)}] {sym}: FAIL ({status})')
        
        # 节流
        if (i + 1) % 10 == 0:
            time.sleep(0.5)
    
    print(f'\n{"="*60}')
    print(f'完成! 新增: {ok} | 跳过: {skip} | 失败: {len(fail)}')
    print(f'新增数据行: {total_new}')
    
    if fail:
        print(f'\n失败列表:')
        for s, r in fail:
            print(f'  {s}: {r}')
    
    # 最终统计
    print(f'\n最终状态:')
    import pandas as pd
    ok_count = 0
    bad_count = 0
    missing_count = 0
    for sym in sorted(set(MISSING)):
        fp = DATA_DIR / f'{sym}.csv'
        if fp.exists():
            try:
                df = pd.read_csv(fp)
                df['Date'] = pd.to_datetime(df['Date'])
                latest = df['Date'].max().strftime('%Y-%m-%d')
                rows_3yr = (df['Date'] >= '2023-06-01').sum()
                if rows_3yr >= 400:
                    ok_count += 1
                else:
                    bad_count += 1
                    print(f'  [数据不足] {sym}: end={latest}, rows_3yr={rows_3yr}')
            except:
                bad_count += 1
        else:
            missing_count += 1
            print(f'  [仍缺失] {sym}')
    
    print(f'  OK: {ok_count} | 数据不足: {bad_count} | 仍缺失: {missing_count}')

if __name__ == '__main__':
    main()
