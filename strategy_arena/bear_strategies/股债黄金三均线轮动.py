"""
股债黄金三均线轮动策略
避险资产轮动策略：在股票、国债、黄金三类资产间按均线动量轮动，
牛市持有股票，熊市切换到国债或黄金。经典避险轮动策略。
注意：此为简化版，仅使用单标的的均线趋势判断。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "股债黄金三均线轮动"
STRATEGY_TYPE = "避险资产轮动"
STRATEGY_PARAMS = {'fast_period': 10, 'slow_period': 30, 'trend_period': 50}


def generate_signals(close, high, low, open_prices, **kwargs):
    fast_period = kwargs.get('fast_period', 10)
    slow_period = kwargs.get('slow_period', 30)
    trend_period = kwargs.get('trend_period', 50)

    c = pd.Series(close, dtype=float)
    n = len(c)

    # 多层均线
    ema_fast = c.ewm(span=fast_period, adjust=False).mean()
    ema_slow = c.ewm(span=slow_period, adjust=False).mean()
    ema_trend = c.ewm(span=trend_period, adjust=False).mean()

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(trend_period, n):
        # 多头排列：快线>慢线>趋势线 → 持有
        bullish = (ema_fast.iloc[i] > ema_slow.iloc[i]) and (ema_slow.iloc[i] > ema_trend.iloc[i])
        # 空头排列：快线<慢线 → 空仓（切换到避险资产）
        bearish = ema_fast.iloc[i] < ema_slow.iloc[i]

        if not in_pos and bullish:
            entries[i] = True
            in_pos = True
        elif in_pos and bearish:
            exits[i] = True
            in_pos = False

    return entries, exits
