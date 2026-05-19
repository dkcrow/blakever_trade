import pandas as pd
import os

d = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks'
stocks = ['NVDA','AMD','MU','AVGO','TSLA','AAPL','GOOG','AMZN','KO','NEM','XOM','AEP','JPM','GS','BRK-B']

print('V7 stocks 10Y return:')
for s in stocks:
    try:
        df = pd.read_csv(os.path.join(d, s+'.csv'))
        c = df['Close'] if 'Close' in df.columns else df['close']
        ret = (c.iloc[-1] / c.iloc[0] - 1) * 100
        print(f'  {s}: {ret:.1f}%')
    except Exception as e:
        print(f'  {s}: error - {e}')
