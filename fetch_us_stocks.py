import yfinance as yf
import pandas as pd
import os

stocks = {
    'NVDA': '英伟达',
    'SNDK': 'Sandisk', 
    'AMD': '超微半导体',
    'MU': '美光科技',
    'AVGO': '博通',
    'TSLA': '特斯拉',
    'AAPL': '苹果',
    'GOOG': '谷歌',
    'AMZN': '亚马逊',
    'KO': '可口可乐',
    'NEM': '纽曼矿业',
    'XOM': '埃克森美孚',
    'AEP': '美国电力',
    'JPM': '摩根大通',
    'GS': '高盛',
    'BRK-B': '伯克希尔-B'
}

output_dir = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks'
os.makedirs(output_dir, exist_ok=True)

success_count = 0
fail_count = 0

for symbol, name in stocks.items():
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period='10y', auto_adjust=True)
        
        if len(df) > 100:
            filepath = os.path.join(output_dir, f'{symbol}.csv')
            df.to_csv(filepath)
            print(f'[OK] {symbol} ({name}): {len(df)} rows saved')
            success_count += 1
        else:
            print(f'[WARN] {symbol} ({name}): data insufficient ({len(df)} rows)')
            fail_count += 1
    except Exception as e:
        print(f'[FAIL] {symbol} ({name}): {str(e)[:60]}')
        fail_count += 1

print(f'\nTotal: {success_count} success, {fail_count} failed')
print(f'Saved to: {output_dir}')
