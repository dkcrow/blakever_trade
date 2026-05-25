"""
MACD死叉做空策略
做空趋势策略：MACD柱状图从正转负(死叉)+价格在长期EMA下方时做空，
MACD金叉或价格突破EMA时平仓。
注意：当前版本在空头信号时空仓（等待做多信号），因为引擎做空支持有限。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "MACD死叉做空策略"
STRATEGY_TYPE = "做空趋势"
STRATEGY_PARAMS = {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'ema_period': 50}


def generate_signals(close, high, low, open_prices, **kwargs):
    macd_fast = kwargs.get('macd_fast', 12)
    macd_slow = kwargs.get('macd_slow', 26)
    macd_signal = kwargs.get('macd_signal', 9)
    ema_period = kwargs.get('ema_period', 50)

    c = pd.Series(close, dtype=float)
    n = len(c)

    # MACD
    macd, macd_signal_line, macd_hist = talib.MACD(c.values,
                                                     fastperiod=macd_fast,
                                                     slowperiod=macd_slow,
                                                     signalperiod=macd_signal)
    macd_hist = pd.Series(macd_hist, dtype=float)

    # 长期EMA
    ema = c.ewm(span=ema_period, adjust=False).mean()

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(ema_period + macd_slow, n):
        if pd.isna(macd_hist.iloc[i]) or pd.isna(ema.iloc[i]):
            continue

        # 做多条件：MACD金叉 + 价格在EMA上方（熊市中的反弹机会）
        golden_cross = (macd_hist.iloc[i] > 0) and (macd_hist.iloc[i - 1] <= 0)
        price_above_ema = c.iloc[i] > ema.iloc[i]

        # 做空信号（实际为空仓信号）：MACD死叉 或 价格在EMA下方
        death_cross = (macd_hist.iloc[i] < 0) and (macd_hist.iloc[i - 1] >= 0)
        price_below_ema = c.iloc[i] < ema.iloc[i]

        if not in_pos and golden_cross and price_above_ema:
            entries[i] = True
            in_pos = True
        elif in_pos and (death_cross or price_below_ema):
            exits[i] = True
            in_pos = False

    return entries, exits
