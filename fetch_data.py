"""
数据获取脚本：获取SPY和恒生指数18年日线数据并保存为CSV
"""
import subprocess
import csv
import sys
import os

def fetch_kline(skill_path, code, period, limit, output_csv):
    """通过westock-data技能获取K线数据并保存为CSV"""
    cmd = f"node {skill_path}/scripts/index.js kline {code} --period {period} --limit {limit}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=os.path.dirname(skill_path))
    
    if result.returncode != 0:
        print(f"Error fetching {code}: {result.stderr}")
        return None
    
    # 解析Markdown表格
    lines = result.stdout.strip().split('\n')
    data_rows = []
    for line in lines:
        if line.startswith('|') and not line.startswith('| date') and not line.startswith('| ---'):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 7 and parts[0].startswith('20'):
                data_rows.append(parts)
    
    if not data_rows:
        print(f"No data for {code}")
        return None
    
    # 写入CSV
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])
        for row in data_rows:
            if len(row) >= 7:
                try:
                    writer.writerow([row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[6])])
                except:
                    pass
    
    print(f"  Saved {len(data_rows)} rows to {output_csv}")
    return data_rows

# 路径
skill_path = '/data/workspace/.agent/skills/westock-data'

# 获取SPY数据
print("Fetching SPY daily data (18 years)...")
spy_rows = fetch_kline(skill_path, 'usSPY', 'day', 4500, '/data/workspace/spy_daily.csv')

# 获取恒生指数数据
print("\nFetching HSI daily data (18 years)...")
hsi_rows = fetch_kline(skill_path, 'hkHSI', 'day', 4500, '/data/workspace/hsi_daily.csv')

print("\nData fetching complete!")
