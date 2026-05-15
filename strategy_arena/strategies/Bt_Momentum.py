
# 策略: Bt Momentum
# 来源: multi:google_github
# 自动生成时间: 2026-04-30 17:51:55

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Bt Momentum"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {'window': 20.0}

import pandas as pd
import numpy as np
import matplotlib.pyplot
import yfinance as yf

import yfinance as yf
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

class Momentum:
    def __init__(self, symbol, start, end, window=3):
        self.symbol = symbol
        self.start = start
        self.end = end
        self.window = window
        self.getData()
        self.createPositions()
        
    def getData(self):
        df = yf.download(self.symbol, start=self.start, end=self.end)
        df.drop(columns=["High", "Open", "Low", "Volume","Adj Close"], inplace=True)
        df.rename(columns={"Close": "price"}, inplace=True)
        self.data = df.copy()
        
    def createPositions(self, window=None):
        if window is None:
            window = self.window

        self.data["l_returns"] = np.log(self.data["price"] / self.data["price"].shift(1))
        self.data["rolling_mean"] = self.data["l_returns"].rolling(window).mean()
        self.data.dropna(subset=["l_returns", "rolling_mean"], inplace=True)
        
        self.data["position"] = -np.sign(self.data["rolling_mean"])
        self.data["strategy"] = self.data["position"].shift(1) * self.data["l_returns"]
        self.data.dropna(subset=["strategy"], inplace=True)
        
        self.data["creturns"] = self.data["l_returns"].cumsum().apply(np.exp)
        self.data["cstrategy"] = self.data["strategy"].cumsum().apply(np.exp)
        
        self.data.drop(columns=["rolling_mean"], inplace=True)

        # Ensure there is data to return
        if self.data["cstrategy"].empty:
            return None
        
        return self.data["cstrategy"].iloc[-1]

    def findOptimalWindow(self, min_window=2, max_window=20):
        best_window = min_window
        best_return = -np.inf
        
        for window in range(min_window, max_window + 1):
            strategy_return = self.createPositions(window=window)
            
            # Handle the case where strategy_return is None
            if strategy_return is None:
                continue
            
            if strategy_return > best_return:
                best_return = strategy_return
                best_window = window
        
        print(f"Optimal window size is {best_window} with a return of ${best_return:.2f}")
        self.getResultDeference()
        return best_window

    def getResultDeference(self):
        buy_and_hold_return = self.data["creturns"].iloc[-1]
        strategy_return = self.data["cstrategy"].iloc[-1]
        print(f"Result of our buy and hold is ${buy_and_hold_return:.2f}")
        print(f"Strategy return is ${strategy_return:.2f}")
        
    def plotResults(self):
        plt.figure(figsize=(14, 7))
        plt.plot(self.data.index, self.data["creturns"], label='Buy and Hold Returns')
        plt.plot(self.data.index, self.data["cstrategy"], label='Strategy Returns')
        plt.title('Cumulative Returns vs. Strategy Returns')
        plt.xlabel('Date')
        plt.ylabel('Cumulative Returns')
        plt.legend()
        plt.grid(True)
        plt.show()
        self.getResultDeference()
    
    def __repr__(self):
        return f"<Momentum(symbol={self.symbol}, start={self.start}, end={self.end}, window={self.window})>"

    def __str__(self):
        return f"Momentum Strategy Results:\n{self.data.tail()}"


test = Momentum("AAPL","2018-01-01","2019-11-01",5)
#print(test)
test.createPositions()
print(test)
print(test.getResultDeference())
test.findOptimalWindow()


