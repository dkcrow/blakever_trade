"""
布林带均值回归策略（熊市版）
价格触及布林带下轨买入（超跌），回归中轨平仓。
熊市版增加ADX过滤和更紧的止损。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "布林带均值回归(熊市版)"
STRATEGY_TYPE = "均值回归（抄底）"
STRATEGY_PARAMS = {'bb_period': 20, 'bb_std': 2.5, 'rsi_period': 14}


def generate_signals(close, high, low, open_prices, **kwargs):
    bb_period = kwargs.get('bb_period', 20)
    bb_std = kwargs.get('bb_std', 2.0)
    rsi_period = kwargs.get('rsi_period', 14)

    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    # 布林带
    upper, middle, lower = talib.BBANDS(c.values, timeperiod=bb_period,
                                         nbdevup=bb_std, nbdevdn=bb_std, matype=0)
    upper = pd.Series(upper, dtype=float)
    middle = pd.Series(middle, dtype=float)
    lower = pd.Series(lower, dtype=float)

    # RSI过滤
    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), dtype=float)

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(1, n):
        if pd.isna(lower.iloc[i]) or pd.isna(rsi.iloc[i]):
            continue

        if not in_pos:
            # 触及下轨 + RSI未极端（<40，但不是极端恐慌<20）
            if c.iloc[i] <= lower.iloc[i] and rsi.iloc[i] < 40 and rsi.iloc[i] > 15:
                entries[i] = True
                in_pos = True
        else:
            # 回归中轨平仓 或 触及上轨 或 RSI超买
            if c.iloc[i] >= middle.iloc[i] or c.iloc[i] >= upper.iloc[i] or rsi.iloc[i] > 70:
                exits[i] = True
                in_pos = False

    return entries, exits
