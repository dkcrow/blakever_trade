#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch 513080 (法国ETF) and 513730 (东南亚ETF) 5-year K-line data
Using Tencent Finance public API (avoid westock SSE 404)
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime

ETF_LIST = [
    ('513080', 'sh'),  # 法国ETF - Shanghai
    ('513730', 'sh'),  # 东南亚ETF - Shanghai
]

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'
os.makedirs(DATA_DIR, exist_ok=True)

def fetch_tencent_kline(code, market_prefix, start_date='2016-01-01', end_date='2026-05-21'):
    """
    Fetch K-line via Tencent Finance API
    code: 6-digit ETF code
    market_prefix: 'sh' or 'sz'
    """
    url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    param_str = f'{market_prefix}{code},day,,,2500,{start_date},{end_date},qfq'
    
    params = {
        'param': param_str,
        '_var': 'kline_dayqfq'
    }
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            print(f'  [X] HTTP {resp.status_code}')
            return None
        
        text = resp.text
        if 'kline_dayqfq=' not in text:
            print(f'  [X] Invalid response')
            return None
        
        json_str = text.split('kline_dayqfq=')[1]
        import json
        data = json.loads(json_str)
        
        if 'data' not in data or 'qfqday' not in data['data']:
            print(f'  [X] No K-line data')
            return None
        
        klines = data['data']['qfqday']
        if not klines or len(klines) < 10:
            print(f'  [X] Insufficient data: {len(klines)} rows')
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df = df.astype(float)
        df = df[['open', 'high', 'low', 'close', 'volume']]
        
        return df
        
    except Exception as e:
        print(f'  [X] Error: {e}')
        return None

def main():
    print("="*80)
    print("Fetching 2 Missing ETFs (5-Year Data)")
    print("="*80)
    
    for code, market in ETF_LIST:
        print(f"\nFetching {code} (market={market})...")
        df = fetch_tencent_kline(code, market)
        
        if df is not None and len(df) >= 100:
            save_path = os.path.join(DATA_DIR, f'{code}.csv')
            df.to_csv(save_path, encoding='utf-8-sig')
            print(f"  [OK] {len(df)} rows ({df.index[0].date()} ~ {df.index[-1].date()})")
            print(f"  Saved: {save_path}")
        else:
            print(f"  [X] Failed to fetch sufficient data")
        
        time.sleep(1.5)  # Rate limit
    
    print("\n" + "="*80)
    print("Download Complete!")
    print("="*80)

if __name__ == '__main__':
    main()
