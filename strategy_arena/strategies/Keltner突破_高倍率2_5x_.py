#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keltner通道突破策略
====================
Keltner Channel突破策略，ATR驱动的通道突破。
比布林带更适应趋势市场，减少震荡市的假信号。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Keltner通道突破策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'ema_period': 20, 'atr_period': 20, 'atr_multiplier': 2.5}


def generate_signals(close, high, low, open_prices,
                     ema_period=20, atr_period=20, atr_multiplier=2.5):
    """Keltner通道突破策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # EMA中轨
    ema = c.ewm(span=ema_period, adjust=False).mean()

    # ATR
    atr = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=atr_period),
                     index=c.index)

    # Keltner通道
    upper = ema + atr_multiplier * atr
    lower = ema - atr_multiplier * atr

    # 入场: 收盘价突破上轨
    # 出场: 收盘价跌破下轨或EMA
    in_position = pd.Series(False, index=c.index)
    for i in range(1, n):
        if not in_position.iloc[i-1]:
            # 入场条件
            if c.iloc[i] > upper.iloc[i]:
                in_position.iloc[i] = True
        else:
            # 出场条件
            if c.iloc[i] < lower.iloc[i]:
                in_position.iloc[i] = False
            else:
                in_position.iloc[i] = True

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
