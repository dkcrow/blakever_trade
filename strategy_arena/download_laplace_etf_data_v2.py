#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download ETF data for Qixing Laplace Gaussian strategy (2016-2026, forward-adjusted)
Use Tencent Finance API (avoid yfinance rate limits)
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime

# 7 ETFs from original Juquant strategy
ETF_LIST = [
    '518880',  # Gold ETF
    '159980',  # Non-ferrous ETF
    '159985',  # Soybean meal ETF
    '501018',  # Southern Crude Oil
    '161226',  # Silver LOF
    '159981',  # Energy Chemical ETF
    '513100',  # Nasdaq ETF
]

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

def download_tencent_kline(code, start_date='2016-01-01', end_date='2026-05-20'):
    """
    Download K-line data using Tencent Finance API
    code: 6-digit ETF code, e.g. 518880
    """
    # Determine market: 5xxxx=Shanghai, 1xxxx=Shenzhen
    if code.startswith('5') or code.startswith('6'):
        market = 'sh'
    else:
        market = 'sz'
    
    # Tencent API
    url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    params = {
        'param': f'{market}{code},day,,,2500,{start_date},{end_date},qfq',
        '_var': 'kline_dayqfq'
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f'  [X] HTTP {resp.status_code}')
            return None
        
        # Parse response (JSONP format)
        text = resp.text
        if 'kline_dayqfq=' in text:
            json_str = text.split('kline_dayqfq=')[1]
            import json
            data = json.loads(json_str)
            
            # Extract K-line data
            if 'data' in data and 'qfqday' in data['data']:
                klines = data['data']['qfqday']
                if not klines:
                    return None
                
                # Convert to DataFrame
                df = pd.DataFrame(klines, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df = df.astype(float)
                df = df[['open', 'high', 'low', 'close', 'volume']]
                
                return df
    except Exception as e:
        print(f'  [X] {e}')
        return None

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    print("=" * 80)
    print("Downloading Qixing Laplace Gaussian ETF Data (2016-2026, Forward-Adjusted)")
    print("=" * 80)
    
    for code in ETF_LIST:
        print(f"\nDownloading {code}...")
        df = download_tencent_kline(code)
        
        if df is not None and len(df) > 100:
            # Save
            save_path = os.path.join(DATA_DIR, f'{code}.csv')
            df.to_csv(save_path, encoding='utf-8-sig')
            print(f"  [OK] Success: {len(df)} rows ({df.index[0].date()} ~ {df.index[-1].date()})")
            print(f"  Saved to: {save_path}")
        else:
            print(f"  [X] Failed or insufficient data")
        
        time.sleep(1)  # Avoid rate limits
    
    print("\n" + "=" * 80)
    print("Download Complete!")
    print("=" * 80)

if __name__ == '__main__':
    main()
