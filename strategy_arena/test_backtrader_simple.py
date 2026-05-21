import backtrader as bt
import pandas as pd
import numpy as np
import math
import os

# 加载数据
df = pd.read_csv(r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks\AAPL.csv')
df['Date'] = pd.to_datetime(df['Date'])
df = df.set_index('Date')
df = df.rename(columns={'Open':'open','Close':'close','High':'high','Low':'low','Volume':'volume'})
df = df.sort_index()

# 创建Cerebro
cerebro = bt.Cerebro()
cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(commission=0.001)

data = bt.feeds.PandasData(
    dataname=df, 
    name='AAPL', 
    fromdate=pd.Timestamp('2019-01-01'), 
    todate=pd.Timestamp('2024-12-31')
)
cerebro.adddata(data)

# 简单策略
class TestStrategy(bt.Strategy):
    def __init__(self):
        self.ma = bt.indicators.SMA(self.data.close, period=20)
    
    def next(self):
        if self.data.close[0] > self.ma[0] and not self.position:
            self.buy(size=100)
        elif self.data.close[0] < self.ma[0] and self.position:
            self.close()

cerebro.addstrategy(TestStrategy)
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)

results = cerebro.run()
strat = results[0]

# 结果
final = cerebro.broker.getvalue()
total_ret = (final / 100000 - 1) * 100
print(f"最终资产: ${final:,.2f}")
print(f"总收益率: {total_ret:+.2f}%")

returns = strat.analyzers.returns.get_analysis()
if 'rtot' in returns:
    ann = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
    print(f"年化收益率: {ann*100:.2f}%")

sharpe = strat.analyzers.sharpe.get_analysis()
if 'sharperatio' in sharpe:
    print(f"夏普比率: {sharpe['sharperatio']:.2f}")
