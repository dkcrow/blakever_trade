#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download 10 years of ETF data using AKShare (from listing date)
Target: Qixing Laplace Gaussian 7 ETFs
"""

import akshare as ak
import pandas as pd
import time
import os
from datetime import datetime

# 7 ETFs from Juquant original strategy
ETF_LIST = [
    '518880',  # Gold ETF
    '159980',  # Non-ferrous ETF
    '159985',  # Soybean meal ETF
    '501018',  # Southern Crude Oil
    '161226',  # Silver LOF
    '159981',  # Energy Chemical ETF
    '513100',  # Nasdaq ETF
]

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing_akshare'
os.makedirs(DATA_DIR, exist_ok=True)

def get_listing_date(code):
    """Get ETF listing date (approximate)"""
    # Known listing dates (you can also try to fetch from AKShare)
    listing_dates = {
        '518880': '2013-07-18',
        '159980': '2019-12-24',
        '159985': '2019-12-05',
        '501018': '2018-02-09',
        '161226': '2018-02-09',
        '159981': '2020-01-17',
        '513100': '2013-04-25',
    }
    return listing_dates.get(code, '2016-01-01')

def download_etf_data_akshare(code, start_date):
    """
    Download ETF data using AKShare
    code: 6-digit ETF code
    start_date: listing date or '2016-01-01'
    """
    try:
        # Method 1: Use fund_etf_hist_em (East Money)
        # For Shenzhen ETFs (1xxxxx), use market='sz'
        # For Shanghai ETFs (5xxxxx), use market='sh'
        if code.startswith('5') or code.startswith('6'):
            market = 'sh'
        else:
            market = 'sz'
        
        # AKShare: fund_etf_hist_em
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date='20260520',
            adjust="qfq"  # qfq = forward adjusted
        )
        
        if df is None or len(df) < 10:
            print(f'  [X] No data returned')
            return None
        
        # Rename columns to standard format
        # AKShare columns: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        column_map = {
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
        }
        
        df = df.rename(columns=column_map)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # Keep only needed columns
        df = df[['open', 'high', 'low', 'close', 'volume']]
        df = df.dropna()
        
        return df
        
    except Exception as e:
        print(f'  [X] Error: {e}')
        return None

def main():
    print("="*80)
    print("Downloading 10-Year ETF Data using AKShare")
    print("Target: Qixing Laplace Gaussian 7 ETFs")
    print("="*80)
    
    for code in ETF_LIST:
        print(f"\nDownloading {code}...")
        listing_date = get_listing_date(code)
        print(f"  Listing date: {listing_date}")
        
        df = download_etf_data_akshare(code, listing_date)
        
        if df is not None and len(df) > 100:
            # Save
            save_path = os.path.join(DATA_DIR, f'{code}.csv')
            df.to_csv(save_path, encoding='utf-8-sig')
            print(f"  [OK] {len(df)} rows ({df.index[0].date()} ~ {df.index[-1].date()})")
            print(f"  Saved to: {save_path}")
        else:
            print(f"  [X] Failed or insufficient data")
        
        time.sleep(1)  # Rate limit
    
    print("\n" + "="*80)
    print("Download Complete!")
    print("="*80)

if __name__ == '__main__':
    main()
