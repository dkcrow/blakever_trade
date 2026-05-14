
# 策略: Backtesting
# 来源: multi:google_github
# 自动生成时间: 2026-04-30 17:51:55

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Backtesting"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {'window': 14.0}

import pandas as pd
import numpy as np
import requests
import ta.momentum
import ta.trend
import matplotlib.pyplot as plt


capital = 10000
riskpt = 10 # risk per trade (only 1%);'
capital_history = []

def load_csv_data(filepath):
    df = pd.read_csv(filepath)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    df[["open", "high", "low", "close","volume"]] = df[["open", "high", "low", "close","volume"]].astype(float)
    return df

def fetch_binance_data(symbol="BTCUSDT", interval = "1m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    response = requests.get(url)
    data = response.json()
    
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", 
                                     "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", 
                                     "taker_buy_quote_asset_volume", "ignore"])
    
    df = df[["timestamp", "open", "high", "low", "close","volume"]]
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
    df[["open", "high", "low", "close","volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df

def plot_graph(capital_history):
    plt.figure(figsize=(10,6))
    plt.plot(capital_history, label = "Equity_Curve")
    plt.title("Equity curve over time")
    plt.xlabel("Number of trades")
    plt.ylabel("Capital")
    plt.legend()
    plt.show()

def calculate_ema(df, period, column="close"):
    return df[column].ewm(span=period, adjust=False).mean()

def backtest_ema_strategy(df_1m, df_15m, ema_short=7, ema_long=25, risk_reward=30):
    global capital, riskpt            

    # Compute EMAs for both timeframes
    df_1m["EMA7"] = calculate_ema(df_1m, ema_short)   ##### risk:reward = 1:20 sl = candle'low'/3
    df_1m["EMA25"] = calculate_ema(df_1m, ema_long)
    df_15m["EMA7"] = calculate_ema(df_15m, ema_short)
    df_15m["EMA25"] = calculate_ema(df_15m, ema_long)
    df_1m["volumeMA"] = calculate_ema(df_1m, 14, 'volume')  # periods ( 7 >14 >9 > 99)
    df_1m['rsi'] = ta.momentum.rsi(df_1m['close'], window=14).astype(float)
    
    # **Assign fixed 15m trend for every 1-minute candle**
    df_1m["fixed_15m_trend"] = None
    for i in range(len(df_15m) - 1):
        trend_time = df_15m["timestamp"].iloc[i]
        next_trend_time = df_15m["timestamp"].iloc[i + 1]
        
        # Assign the same trend for all 1-minute candles between `trend_time` and `next_trend_time`
        mask = (df_1m["timestamp"] >= trend_time) & (df_1m["timestamp"] < next_trend_time)
        df_1m.loc[mask, "fixed_15m_trend"] = (
            "bullish" if df_15m["EMA7"].iloc[i] > df_15m["EMA25"].iloc[i] else "bearish"
        )

    df_1m["signal"] = 0  # Default no trade

    # **Trade Logic**
    for i in range(1, len(df_1m)):
        if df_1m["fixed_15m_trend"].iloc[i] == "bullish":  # Only long trades in bullish trend
            if df_1m["EMA7"].iloc[i-1] > df_1m["EMA25"].iloc[i-1] and df_1m["close"].iloc[i-1] < df_1m["EMA25"].iloc[i-1] :#and df_1m['volume'].iloc[i-1] > df_1m['volumeMA'].iloc[i-1]:
                df_1m.at[df_1m.index[i], "signal"] = 2 # sell next candle
                position = True

        elif df_1m["fixed_15m_trend"].iloc[i] == "bearish":  # Only short trades in bearish trend
            if df_1m["EMA7"].iloc[i-1] < df_1m["EMA25"].iloc[i-1] and df_1m["close"].iloc[i-1] > df_1m["EMA25"].iloc[i-1] :#and df_1m['volume'].iloc[i-1] > df_1m['volumeMA'].iloc[i-1]:
                df_1m.at[df_1m.index[i], "signal"] = 1 # buy next candle
                position = True        

    # **Trade Execution (Same as your logic)**
    entry_prices, sl_prices, tp_prices = [], [], []
    wins, losses = 0, 0

    for i in range(len(df_1m)):
        if df_1m["signal"].iloc[i] == 1:  # Long trade
            entry_price = df_1m["open"].iloc[i]
            sl_price = df_1m["open"].iloc[i] -(df_1m["open"].iloc[i]- df_1m["low"].iloc[i - 1])/3
            tp_price = entry_price + (entry_price - sl_price) * risk_reward

            entry_prices.append(entry_price)
            sl_prices.append(sl_price)
            tp_prices.append(tp_price)

            for j in range(i + 1, len(df_1m)):
                if df_1m["low"].iloc[j] <= sl_price:
                    losses += 1
                    capital -= riskpt
                    break
                elif df_1m["high"].iloc[j] >= tp_price:
                    wins += 1
                    capital += riskpt * risk_reward
                    break

        elif df_1m["signal"].iloc[i] == 2:  # Short trade
            entry_price = df_1m["open"].iloc[i]
            sl_price = df_1m["open"].iloc[i] +(df_1m["high"].iloc[i]- df_1m["open"].iloc[i - 1])/3
            tp_price = entry_price - (sl_price - entry_price) * risk_reward

            entry_prices.append(entry_price)
            sl_prices.append(sl_price)
            tp_prices.append(tp_price)

            for j in range(i + 1, len(df_1m)):
                if df_1m["high"].iloc[j] >= sl_price:
                    losses += 1
                    capital -= riskpt
                    break
                elif df_1m["low"].iloc[j] <= tp_price:
                    wins += 1
                    capital += riskpt * risk_reward
                    break

        #capital_history.append(capital)   #updating the capital     

    win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0

    #plot_graph(capital_history)
    
    return {
        "Total Trades": wins + losses,
        "Wins": wins,
        "Losses": losses,
        "Win Rate": win_rate,
        "Capital + Return": capital
    }

# Fetch Data
df_1m = load_csv_data("BTCUSDT_1m_365.csv") 
df_15m = load_csv_data("BTCUSDT_15m_365.csv")
result = backtest_ema_strategy(df_1m, df_15m)
print(result)

