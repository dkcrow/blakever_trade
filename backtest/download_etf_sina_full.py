#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量补全ETF历史数据 — 使用新浪财经API (money.finance.sina.com.cn)
支持 datalen=2000, 覆盖完整历史
"""

import sys, os, time, json, warnings, requests
warnings.filterwarnings('ignore')

import pandas as pd
from pathlib import Path

DATA_DIR = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\data\storage\stock_data\etf')
SINA_URL = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
            'CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}')


def get_need_update():
    """返回需要补全的ETF: 数据起始晚于2024年7月"""
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
            if df['date'].min() > pd.Timestamp('2024-07-01'):
                need_update.append((code, raw))
        except:
            need_update.append((code, raw))
    
    return need_update


def download_sina_full(code, datalen=2000):
    """从新浪API下载完整历史数据"""
    raw = code[2:]
    market = 'sh' if code.startswith('sh') else 'sz'
    symbol = f'{market}{raw}'
    
    try:
        url = SINA_URL.format(symbol=symbol, datalen=datalen)
        r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
        data = json.loads(r.text)
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
        df = pd.DataFrame(rows)
        return df.dropna(subset=['close'])
    except Exception:
        return None


def save_data(raw_code, df):
    fp = DATA_DIR / f'{raw_code}.csv'
    df = df[['date', 'open', 'high', 'low', 'close', 'volume']].dropna(subset=['close'])
    df.to_csv(fp, index=False)
    return len(df)


def main():
    need_update = get_need_update()
    if not need_update:
        print("所有ETF数据已完整")
        return
    
    print(f"=== 新浪API批量补全 {len(need_update)} 只ETF ===")
    
    success = 0
    failed = 0
    
    for i, (code, raw) in enumerate(sorted(need_update, key=lambda x: x[1])):
        label = f"{'沪' if code.startswith('sh') else '深'}{raw}"
        
        df = download_sina_full(code, datalen=2000)
        
        if df is not None and len(df) > 0:
            n = save_data(raw, df)
            dr = f"{df['date'].min().strftime('%Y-%m-%d')}~{df['date'].max().strftime('%Y-%m-%d')}"
            success += 1
            status = f"OK ({n}行, {dr})"
        else:
            failed += 1
            status = "FAILED"
        
        print(f"  [{i+1:3d}/{len(need_update)}] {label} {status}")
        time.sleep(0.15)
        
        if (i + 1) % 25 == 0:
            print(f"  --- 进度: {success}成功 / {failed}失败 ---")
            time.sleep(0.5)
    
    print(f"\n=== 完成: 成功{success} / 失败{failed} ===")


if __name__ == '__main__':
    main()
