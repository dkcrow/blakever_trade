
# 策略: Trading Project
# 来源: multi:google_github
# 自动生成时间: 2026-04-30 20:13:02

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Trading Project"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Download data
sp500 = yf.download("^GSPC", start="2019-01-01")
nifty = yf.download("^NSEI", start="2019-01-01")

#Keep only Close Price
sp500 = sp500[["Close"]]
nifty = nifty[["Close"]]

#Calculate daily return: 
#Below pct_change() is Return = Today's Close - Yesterday's Close/Yesterday's Close
sp500['Return'] = sp500['Close'].pct_change()
nifty['Return'] = nifty['Close'].pct_change()

#Calculate annualized volatility
# Below standard deviation measures how much returns flucuate (Higher std = more volatile), and we multiply it by 252 because trading days are around 252 days a year
#To convert daily volatility to annual volatitlity: Daily std × square root of 252
sp500_vol = sp500['Return'].std() * np.sqrt(252)
nifty_vol = nifty['Return'].std() * np.sqrt(252)

print("S&P 500 Annualized Volatility: ", round(sp500_vol, 4))
print("NIFTY 50 Annualized Volatility: ", round(nifty_vol, 4))

#Function to calculate maximum drawdown
def max_drawdown(price_series):
    cumulative_max = price_series.cummax()
    drawdown = (price_series - cumulative_max) / cumulative_max
    return drawdown.min()

#calculate max drawdown
sp500_mdd = max_drawdown(sp500['Close']).iloc[0]
nifty_mdd = max_drawdown(nifty['Close']).iloc[0]

#print("\nMaximum Drawdown: ")
print("S&P 500 Maximum Drawdown:", round(sp500_mdd, 4))
print("NIFTY 50 Maximum Drawdown:", round(nifty_mdd, 4))

#Calculate annual returns
sp500_annual_return = sp500['Return'].mean() * 252
nifty_annual_return = nifty['Return'].mean() * 252

#Calmar Ratio: Annual Return/Maximum Drawdown
sp500_calmar = sp500_annual_return / abs (sp500_mdd)
nifty_calmar = nifty_annual_return / abs(nifty_mdd)

print("S&P 500 Calmar Ratio:", round(sp500_calmar, 4))
print("NIFTY 50 Calmar Ratio:", round(nifty_calmar, 4))

# Sharpe Ratio (Risk-free rate = 0)
sp500_sharpe = sp500_annual_return / sp500_vol
nifty_sharpe = nifty_annual_return / nifty_vol

print("S&P 500 Sharpe Ratio:", round(sp500_sharpe, 4))
print("NIFTY 50 Sharpe Ratio:", round(nifty_sharpe, 4))

#Downside deviation (Negative Returns only)
sp500_downside = sp500["Return"][sp500['Return']< 0]
nifty_downside = nifty["Return"][nifty['Return'] <0]

#Calculate Annual Downside Deviation (Downside Volatility)
sp500_downside_std = sp500_downside.std() * np.sqrt(252)
nifty_downside_std = nifty_downside.std() * np.sqrt(252)

#Sortino Ratio (Annual Return/Annual Downside Deviation)
sp500_sortino = sp500_annual_return / sp500_downside_std
nifty_sortino = nifty_annual_return / nifty_downside_std

print("S&P 500 Sortino Ratio:", round(sp500_sortino, 4))
print("NIFTY 50 Sortino Ratio:", round(nifty_sortino, 4))


#Cumulative Returns
sp500['Cumulative Return'] = (1 + sp500['Return']).cumprod()
nifty['Cumulative Return'] = (1 + nifty['Return']).cumprod()

plt.figure(figsize=(12,6))
plt.plot(sp500['Cumulative Return'], label='S&P 500')
plt.plot(nifty['Cumulative Return'], label = 'NIFTY 50')

plt.title("Cumulative Returns Comparison")
plt.legend()
plt.show()

def drawdown_series(price_series):
    cumulative_max = price_series.cummax()
    return(price_series - cumulative_max) / cumulative_max

sp500_dd = drawdown_series(sp500['Close'])
nifty_dd = drawdown_series(nifty['Close'])

plt.figure(figsize=(12,6))

plt.plot(sp500_dd, label='S&P 500')
plt.plot(nifty_dd, label='NIFTY 50')

plt.title("Drawdown Comparison")
plt.ylabel("Drawdown")
plt.xlabel("Date")

plt.axhline(0, linestyle='--')
plt.legend()
plt.grid(True)

plt.show()

#Moving Averages
sp500['MA_50'] = sp500['Close'].rolling(50).mean()
sp500['MA_200'] = sp500['Close'].rolling(200).mean()

#Created signals: 1 = Invested, 0 = Not Invested
sp500['Signal'] = 0
sp500.loc[sp500['MA_50'] > sp500['MA_200'], 'Signal'] = 1

#Strategy Return
sp500['Strategy Return'] = sp500['Return'] * sp500['Signal']

#Stratey Cumulative Growth
sp500['Strategy Cumulative'] = (1 + sp500['Strategy Return']).cumprod()
sp500['BuyHold Cumulative'] = (1 + sp500['Return']).cumprod()

#Graph Plotting
plt.figure(figsize=(12,6))
plt.plot(sp500['BuyHold Cumulative'], label = 'Buy & Hold')
plt.plot(sp500['Strategy Cumulative'], label = 'MA Strategy')
plt.title("Moving Average Strategy vs Buy & Hold (S&P 500)")
plt.legend()
plt.grid(True)
plt.show()

#Moving averages for NIFTY
nifty['MA_50'] = nifty['Close'].rolling(50).mean()
nifty['MA_200'] = nifty['Close'].rolling(200).mean()

# Created signal
nifty['Signal'] = 0
nifty.loc[nifty['MA_50'] > nifty['MA_200'], 'Signal'] = 1

#Strategy Return
nifty['Strategy Return'] = nifty['Return'] * nifty['Signal']

#Strategy Cumulative Growth
nifty['Strategy Cumulative'] = (1 + nifty['Strategy Return']).cumprod()
nifty['BuyHold Cumulative'] = (1 + nifty['Return']).cumprod()

plt.figure(figsize=(12,6))
plt.plot(nifty['BuyHold Cumulative'], label='NIFTY Buy & Hold')
plt.plot(nifty['Strategy Cumulative'], label='NIFTY MA Strategy')

plt.title("Moving Average Strategy vs Buy & Hold (NIFTY 50)")
plt.legend()
plt.grid(True)
plt.show()

#Strategy Annual Return
sp500_strategy_annual_return = sp500['Strategy Return'].mean() * 252
nifty_strategy_annual_return = nifty['Strategy Return'].mean() * 252 

#Strategy Volatility
sp500_strategy_vol = sp500['Strategy Return'].std() * np.sqrt(252)
nifty_strategy_vol = nifty['Strategy Return'].std() * np.sqrt(252)

#Strategy Sharpe
sp500_strategy_sharpe = sp500_strategy_annual_return / sp500_strategy_vol
nifty_strategy_sharpe = nifty_strategy_annual_return / nifty_strategy_vol

#Strategy Sortino
sp500_strategy_downside = sp500['Strategy Return'][sp500['Strategy Return'] < 0]
nifty_strategy_downside = nifty['Strategy Return'][nifty['Strategy Return'] < 0]

sp500_strategy_downside_std = sp500_strategy_downside.std() * np.sqrt(252)
nifty_strategy_downside_std = nifty_strategy_downside.std() * np.sqrt(252)

sp500_strategy_sortino = sp500_strategy_annual_return / sp500_strategy_downside_std
nifty_strategy_sortino = nifty_strategy_annual_return / nifty_strategy_downside_std

#Strategy Max Drawdown
sp500_strategy_mdd = max_drawdown(sp500['Strategy Cumulative'])
nifty_strategy_mdd = max_drawdown(nifty['Strategy Cumulative'])

#Strategy Calmar
sp500_strategy_calmar = sp500_strategy_annual_return / abs(sp500_strategy_mdd)
nifty_strategy_calmar = nifty_strategy_annual_return / abs(nifty_strategy_mdd)

summary_table = pd.DataFrame({
    "Metric": [
        "Annual Return",
        "Volatility",
        "Sharpe Ratio",
        "Sortino Ratio",
        "Max Drawdown",
        "Calmar Ratio"
    ],
    "S&P BuyHold": [
        sp500_annual_return,
        sp500_vol,
        sp500_sharpe,
        sp500_sortino,
        sp500_mdd,
        sp500_calmar
    ],
    "S&P Strategy": [
        sp500_strategy_annual_return,
        sp500_strategy_vol,
        sp500_strategy_sharpe,
        sp500_strategy_sortino,
        sp500_strategy_mdd,
        sp500_strategy_calmar
    ],
    "NIFTY BuyHold": [
        nifty_annual_return,
        nifty_vol,
        nifty_sharpe,
        nifty_sortino,
        nifty_mdd,
        nifty_calmar
    ],
    "NIFTY Strategy": [
        nifty_strategy_annual_return,
        nifty_strategy_vol,
        nifty_strategy_sharpe,
        nifty_strategy_sortino,
        nifty_strategy_mdd,
        nifty_strategy_calmar
    ]
})

summary_table


