
# 策略: Main2 Local
# 来源: multi:github
# 自动生成时间: 2026-04-30 17:51:52

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Main2 Local"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {'period': 26.0, 'multiplier': 2.0, 'window': 14.0}

def generate_signals(close, high, low, open_prices, **kwargs):
    """
    Multi-Asset Technical Signal Backtester This Python script downloads historical price data for a wid
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    o = pd.Series(open_prices, dtype=float)
    n = len(c)

    # === 策略逻辑 ===
    import pandas as pd
    import numpy as np
    import yfinance as yf
    from ta.momentum import RSIIndicator
    from ta.trend import EMAIndicator, MACD
    from ta.volatility import AverageTrueRange
    import warnings
    warnings.simplefilter(action='ignore', category=FutureWarning)
    # ---- 1. Asset Lists ----
    crypto_symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD"]
    tech_symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "TSM", "BABA"]
    energy_symbols = ["XOM", "CVX", "BP", "TOT", "COP", "SHEL"]
    fx_symbols = ["EURUSD=X", "JPY=X", "GBPUSD=X", "AUDUSD=X", "CAD=X", "EURJPY=X", "GBPJPY=X", "EURGBP=X"]
    all_symbols = crypto_symbols + tech_symbols + energy_symbols + fx_symbols
    # ---- 2. Parameters ----
    start_date = "2025-07-01"
    end_date = "2025-09-17"
    ema_short_period = 12
    ema_long_period = 26
    rsi_buy_top = 80
    rsi_buy_bot = 50
    rsi_sell_top = 90
    rsi_sell_bot = 40
    atr_multiplier = 2
    max_holding_days = 10
    
    # ---- 3. Download Data ----
    data = {}
    for symbol in all_symbols:
        df = yf.download(symbol, start=start_date, end=end_date)
        if df.empty:
            continue
        df['Symbol'] = symbol
        data[symbol] = df
    # ---- 4. Indicator Calculation ----
    signals = []
    for symbol, df in data.items():
        df = df.copy()
        # Skip if not enough data for indicators
        if len(df) < max(ema_long_period, 14):
            continue
        df['RSI'] = RSIIndicator(df['Close'].squeeze(), window=14).rsi()
        df['EMA_short'] = EMAIndicator(df['Close'].squeeze(), window=ema_short_period).ema_indicator()
        df['EMA_long'] = EMAIndicator(df['Close'].squeeze(), window=ema_long_period).ema_indicator()
        macd = MACD(df['Close'].squeeze(), window_slow=ema_long_period, window_fast=ema_short_period, window_sign=9)
        df['MACD_line'] = macd.macd()
        df['MACD_signal'] = macd.macd_signal()
        df['MACD_hist'] = df['MACD_line'] - df['MACD_signal']
        df['ATR'] = AverageTrueRange(
            df['High'].squeeze(),
            df['Low'].squeeze(),
            df['Close'].squeeze(),
            window=14
        ).average_true_range()
        # ---- 5. Simple Signal Logic ----
        position = None
        entry_date = None
        entry_price = None
        stop_loss = None
        trailing_stop = None
    
        for i in range(len(df)):
            row = df.iloc[i]
            date = row.name
            price = float(row['Close'])
            rsi = float(row['RSI'])
            ema_short = float(row['EMA_short'])
            ema_long = float(row['EMA_long'])
            macd_hist = float(row['MACD_hist'])
            atr = float(row['ATR'])
    
            # Entry condition
            if (
                position is None
                and pd.notna(ema_short)
                and pd.notna(ema_long)
                and pd.notna(rsi)
                and pd.notna(macd_hist)
                and pd.notna(atr)
            ):
                if (
                    ema_short > ema_long
                    and rsi >= rsi_buy_bot
                    and rsi <= rsi_buy_top
                    and macd_hist > 0
                ):
                    position = 'long'
                    entry_date = date
                    entry_price = price
                    stop_loss = price - atr_multiplier * atr
                    trailing_stop = price - 1.5 * atr
                    signals.append((date, symbol, 'BUY', price))
                    continue
    
            # Exit conditions
            if position == 'long':
                # Time-based stop-loss
                if (date - entry_date).days >= max_holding_days:
                    signals.append((date, symbol, 'SELL (time stop)', price))
                    position = None
                    continue
                # ATR-based stop-loss
                if price < stop_loss:
                    signals.append((date, symbol, 'SELL (ATR stop)', price))
                    position = None
                    continue
                # Trailing stop
                if price > entry_price:
                    trailing_stop = max(trailing_stop, price - 1.5 * atr)
                if price < trailing_stop:
                    signals.append((date, symbol, 'SELL (trailing stop)', price))
                    position = None
                    continue
        # Save signals for each symbol
        data[symbol] = df
    # ---- 6. Print Trade Signals ----
    for sig in signals:
        print(f"{sig[0].date()} | {sig[1]:10} | {sig[2]:20} | Price: {sig[3]:.2f}")
    

    # === 信号生成 ===
    # entries/exits 由策略逻辑决定
    entries = np.full(n, False)
    exits = np.full(n, False)
    return entries, exits
