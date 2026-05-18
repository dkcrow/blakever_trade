#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSI回调买入策略（牛市专用）
============================
在确认的牛市趋势中买回调，RSI从超卖区回升时入场。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "RSI回调买入策略(牛市专用)"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {'ema_period': 50, 'rsi_period': 14, 'rsi_oversold': 35, 'rsi_overbought': 70}


def generate_signals(close, high, low, open_prices,
                     ema_period=50, rsi_period=14, rsi_oversold=35, rsi_overbought=70):
    """RSI回调买入策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 趋势确认: 价格在EMA50上方
    ema = c.ewm(span=ema_period, adjust=False).mean()
    uptrend = c > ema

    # RSI
    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), index=c.index)

    # 入场: 趋势向上 + RSI从超卖区回升
    rsi_oversold_cross = (rsi > rsi_oversold) & (rsi.shift(1) <= rsi_oversold)
    entries = uptrend & rsi_oversold_cross

    # 出场: RSI超买或趋势破位
    rsi_overbought_cross = rsi > rsi_overbought
    trend_break = ~uptrend
    exit_signal = rsi_overbought_cross | trend_break

    # 转换为持仓状态
    in_position = pd.Series(False, index=c.index)
    for i in range(1, n):
        if entries.iloc[i]:
            in_position.iloc[i] = True
        elif exit_signal.iloc[i]:
            in_position.iloc[i] = False
        else:
            in_position.iloc[i] = in_position.iloc[i-1]

    entry_arr = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exit_arr = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entry_arr, exit_arr
