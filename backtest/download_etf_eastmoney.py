#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量下载ETF全量历史数据 — 直接调用东方财富API
绕过 akshare 限流问题，直接 HTTP 请求
"""

import sys, os, time, json, warnings
warnings.filterwarnings('ignore')

import pandas as pd
import requests
from pathlib import Path

DATA_DIR = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\data\storage\stock_data\etf')


def get_missing_codes():
    """返回需要补全数据的ETF: 数据不足200天或起始晚于2024年初"""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from backtest.dual_pool_momentum import DUAL_POOL_ETF, DEFENSIVE_ETF
    
    all_codes = list(set(DUAL_POOL_ETF + [DEFENSIVE_ETF]))
    need_update = []
    
    for code in all_codes:
        raw = code[2:]
        fp = DATA_DIR / f'{raw}.csv'
        
        if not fp.exists():
            need_update.append((code, raw))
            continue
        
        try:
            df = pd.read_csv(fp)
            df['date'] = pd.to_datetime(df['date'])
            # 数据量太少或起始太晚 → 需要补全
            if len(df) < 300 or df['date'].min() > pd.Timestamp('2024-06-01'):
                need_update.append((code, raw))
        except:
            need_update.append((code, raw))
    
    return need_update


def download_eastmoney(raw_code, market, start_date='20230101', end_date='20260603'):
    """
    直接调用东方财富API获取ETF日K线
    secid: 1.XXXXXX (沪市) / 0.XXXXXX (深市)
    """
    secid = f'1.{raw_code}' if market == 'sh' else f'0.{raw_code}'
    
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?'
           f'fields1=f1,f2,f3,f4,f5,f6&'
           f'fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&'
           f'ut=7eea3edcaed734bea9cbfce24459ed5&klt=101&fqt=1&'
           f'secid={secid}&beg={start_date}&end={end_date}&lmt=3000')
    
    try:
        r = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/'
        })
        data = r.json()
        if data.get('data') is None or data['data'].get('klines') is None:
            return None
        
        klines = data['data']['klines']
        if not klines:
            return None
        
        rows = []
        for line in klines:
            parts = line.split(',')
            rows.append({
                'date': pd.to_datetime(parts[0]),
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': int(parts[5]),
            })
        
        df = pd.DataFrame(rows)
        df = df.dropna(subset=['close'])
        return df
    except Exception:
        return None


def save_data(raw_code, df):
    fp = DATA_DIR / f'{raw_code}.csv'
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
        print("所有ETF已就绪")
        return
    
    print(f"=== 东方财富API批量下载 {len(missing)} 只ETF ===")
    
    success = 0
    failed = 0
    
    for i, (code, raw) in enumerate(sorted(missing, key=lambda x: x[1])):
        market = 'sh' if code.startswith('sh') else 'sz'
        label = f"{'沪' if market == 'sh' else '深'}{raw}"
        
        df = download_eastmoney(raw, market)
        
        if df is not None and len(df) > 0:
            n = save_data(raw, df)
            date_range = f"{df['date'].min().strftime('%Y-%m-%d')}~{df['date'].max().strftime('%Y-%m-%d')}"
            success += 1
            print(f"  [{i+1:3d}/{len(missing)}] {label} OK ({n}行, {date_range})")
        else:
            failed += 1
            print(f"  [{i+1:3d}/{len(missing)}] {label} FAILED")
        
        # 控制频率
        if (i + 1) % 30 == 0:
            time.sleep(1.5)
        else:
            time.sleep(0.25)
    
    print(f"\n=== 完成: 成功{success} / 失败{failed} ===")


if __name__ == '__main__':
    main()
