"""
RSI超卖反弹策略
均值回归（抄底）策略：在熊市下跌中寻找RSI超卖后的反弹机会，
RSI从30以下回升时入场，RSI超买或再次下穿50时出场。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "RSI超卖反弹策略"
STRATEGY_TYPE = "均值回归（抄底）"
STRATEGY_PARAMS = {'rsi_period': 14, 'oversold': 30, 'overbought': 65, 'exit_rsi': 45}


def generate_signals(close, high, low, open_prices, **kwargs):
    rsi_period = kwargs.get('rsi_period', 14)
    oversold = kwargs.get('oversold', 30)
    overbought = kwargs.get('overbought', 65)
    exit_rsi = kwargs.get('exit_rsi', 45)

    c = pd.Series(close, dtype=float)
    n = len(c)

    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), dtype=float)

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    was_oversold = False

    for i in range(1, n):
        rsi_val = rsi.iloc[i] if not pd.isna(rsi.iloc[i]) else 50

        if rsi_val < oversold:
            was_oversold = True

        if not in_pos:
            # RSI从超卖区回升时入场
            if was_oversold and rsi_val > oversold and rsi_val < 45:
                entries[i] = True
                in_pos = True
                was_oversold = False
        else:
            # 出场条件：RSI超买 或 RSI再次下穿exit_rsi
            if rsi_val > overbought or (rsi_val < exit_rsi and rsi.iloc[i - 1] >= exit_rsi):
                exits[i] = True
                in_pos = False
                was_oversold = False

    return entries, exits
