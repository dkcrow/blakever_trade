#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载缺失ETF日线数据 (akshare → 新浪财经兜底)

数据源优先级: akshare (全量) → 新浪财经 (最近50条兜底)
"""
import sys, os, time, json, re
warnings = __import__('warnings')
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\data\storage\stock_data\etf')
os.makedirs(DATA_DIR, exist_ok=True)

# 获取缺失列表
def get_missing_codes():
    """返回需要下载的ETF代码列表"""
    existing = set(f.replace('.csv', '') for f in os.listdir(DATA_DIR) if f.endswith('.csv'))
    
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from backtest.dual_pool_momentum import DUAL_POOL_ETF, DEFENSIVE_ETF
    
    all_codes = list(set(DUAL_POOL_ETF + [DEFENSIVE_ETF]))
    missing = []
    for code in all_codes:
        raw = code[2:]  # 去掉 sh/sz
        if raw not in existing:
            missing.append(code)
    return missing


def download_akshare(code, start_date='20240101', end_date='20260603'):
    """使用 akshare 下载ETF全量历史数据"""
    raw = code[2:]  # 纯数字代码，如 "159206"
    
    try:
        import akshare as ak
        df = ak.fund_etf_hist_em(symbol=raw, period="daily", 
                                  start_date=start_date, end_date=end_date, adjust="")
        if df is None or len(df) == 0:
            return None
        
        # 标准化列名
        df = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume',
        })
        df['date'] = pd.to_datetime(df['date'])
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        df = df.dropna(subset=['close'])
        return df
    except Exception as e:
        return None


def download_sina(code):
    """使用新浪财经API下载最近数据 (兜底)"""
    raw = code[2:]
    market = 'sh' if code.startswith('sh') else 'sz'
    symbol = f'{market}{raw}'
    
    try:
        import requests
        url = (f'https://quotes.sina.cn/cn/api/jsonp_v2.php/'
               f'data/CN_MarketDataService.getKLineData?'
               f'symbol={symbol}&scale=240&ma=no&datalen=200')
        r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        text = r.text
        m = re.search(r'\((.*)\)', text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(1))
        if not data:
            return None
        
        rows = []
        for bar in data:
            rows.append({
                'date': pd.to_datetime(bar['day']),
                'open': float(bar['open']),
                'high': float(bar['high']),
                'low': float(bar['low']),
                'close': float(bar['close']),
                'volume': int(float(bar['volume']))
            })
        return pd.DataFrame(rows)
    except:
        return None


def save_etf_data(code, df):
    """保存ETF数据到CSV"""
    raw = code[2:]
    fp = DATA_DIR / f'{raw}.csv'
    
    if fp.exists():
        df_old = pd.read_csv(fp)
        df_old['date'] = pd.to_datetime(df_old['date'])
        merged = pd.concat([df_old, df]).drop_duplicates(subset='date').sort_values('date')
        merged = merged[['date', 'open', 'high', 'low', 'close', 'volume']].dropna(subset=['close'])
    else:
        merged = df[['date', 'open', 'high', 'low', 'close', 'volume']].dropna(subset=['close'])
    
    merged.to_csv(fp, index=False)
    return len(merged)


def main():
    missing = get_missing_codes()
    if not missing:
        print("所有ETF数据已完整，无需下载")
        return
    
    print(f"=== 批量下载 {len(missing)} 只缺失ETF ===")
    print()
    
    success_ak = 0
    success_sina = 0
    failed = 0
    
    for i, code in enumerate(sorted(missing)):
        raw = code[2:]
        name = f"{'沪' if code.startswith('sh') else '深'}{raw}"
        
        # 方法1: akshare
        df = download_akshare(code, start_date='20230101', end_date='20260603')
        if df is not None and len(df) > 0:
            n = save_etf_data(code, df)
            success_ak += 1
            last_date = df['date'].max().strftime('%Y-%m-%d')
            print(f"  [{i+1:3d}/{len(missing)}] {name} akshare OK ({n}行, 至{last_date})")
            time.sleep(0.5)
            continue
        
        # 方法2: 新浪财经兜底
        df = download_sina(code)
        if df is not None and len(df) > 0:
            n = save_etf_data(code, df)
            success_sina += 1
            last_date = df['date'].max().strftime('%Y-%m-%d')
            print(f"  [{i+1:3d}/{len(missing)}] {name} 新浪OK ({n}行, 至{last_date})")
            time.sleep(0.3)
            continue
        
        failed += 1
        print(f"  [{i+1:3d}/{len(missing)}] {name} FAILED")
        time.sleep(0.3)
        
        # 进度汇报
        if (i + 1) % 20 == 0:
            print(f"\n  进度 {i+1}/{len(missing)}: akshare{success_ak} 新浪{success_sina} 失败{failed}\n")
    
    print()
    print(f"=== 下载完成 ===")
    print(f"akshare: {success_ak} | 新浪: {success_sina} | 失败: {failed}")


if __name__ == '__main__':
    main()
