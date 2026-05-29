#!/usr/bin/env python3
"""
下载38只ETF历史净值数据，写入本地CSV文件
数据源: akshare fund_etf_fund_info_em()
纳入后: 七星172策略引擎新增溢价率过滤(Layer2)
"""
import os, sys, time, json
import pandas as pd
from pathlib import Path
import akshare as ak

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.etf.seven_star_base import ETF_POOL, ETF_NAMES

DATA_DIR = Path(__file__).parent / 'storage' / 'stock_data' / 'etf'
NAV_DIR = Path(__file__).parent / 'storage' / 'stock_data' / 'etf_nav'
NAV_DIR.mkdir(parents=True, exist_ok=True)

# ETF代码 → akshare基金代码映射(去掉sh/sz前缀)
def get_fund_code(etf_code):
    return etf_code.replace('sh', '').replace('sz', '')

def download_nav(fund_code, name, retries=3):
    """下载单只ETF的历史净值"""
    for attempt in range(retries):
        try:
            df = ak.fund_etf_fund_info_em(
                fund=fund_code,
                start_date='20150101',
                end_date='20301231'
            )
            if df is not None and len(df) > 0:
                # 标准化列名
                col_map = {
                    '净值日期': 'date',
                    '单位净值': 'unit_nav',
                    '累计净值': 'accumulated_nav',
                    '日增长率': 'daily_return',
                }
                df = df.rename(columns=col_map)
                # 只保留需要的列
                keep_cols = ['date', 'unit_nav']
                df = df[[c for c in keep_cols if c in df.columns]]
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                return df
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  FAIL {fund_code} {name}: {e}")
    return None

def main():
    print("=" * 60)
    print("下载38只ETF历史净值数据")
    print("=" * 60)
    
    success, failed, skipped = 0, 0, 0
    summary = {}
    
    for i, code in enumerate(ETF_POOL):
        fund_code = get_fund_code(code)
        name = ETF_NAMES.get(code, code)
        nav_file = NAV_DIR / f"{code}_nav.csv"
        
        print(f"[{i+1:2d}/38] {code} {name}...", end=" ", flush=True)
        
        # 检查是否已有数据且是最新的
        if nav_file.exists():
            existing = pd.read_csv(nav_file, parse_dates=['date'], index_col='date')
            last_date = existing.index.max()
            print(f"已有 {len(existing)} 条 (最新: {last_date.date()})", end=" ")
            # 如果数据截止到最近一周内，跳过
            from datetime import datetime, timedelta
            if pd.Timestamp(last_date) >= pd.Timestamp.now() - timedelta(days=7):
                print("SKIP")
                skipped += 1
                summary[code] = {'status': 'skip', 'records': len(existing), 'last_date': str(last_date.date())}
                continue
        
        # 下载
        df = download_nav(fund_code, name)
        if df is not None and len(df) > 0:
            df.to_csv(nav_file, encoding='utf-8')
            last_d = df.index.max().date()
            print(f"OK {len(df)}条 (截止{last_d})")
            success += 1
            summary[code] = {'status': 'ok', 'records': len(df), 'last_date': str(last_d)}
        else:
            print("FAILED")
            failed += 1
            summary[code] = {'status': 'failed'}
        
        time.sleep(1)  # 限速
    
    # 保存汇总
    summary_file = NAV_DIR / '_download_summary.json'
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            'download_time': str(pd.Timestamp.now()),
            'total': len(ETF_POOL),
            'success': success,
            'skipped': skipped,
            'failed': failed,
            'details': summary,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"完成: 成功{success} | 跳过{skipped} | 失败{failed}")
    print(f"净值目录: {NAV_DIR}")
    
    if failed > 0:
        print(f"\n失败列表:")
        for code, info in summary.items():
            if info['status'] == 'failed':
                print(f"  {code} {ETF_NAMES.get(code, code)}")

if __name__ == '__main__':
    main()
