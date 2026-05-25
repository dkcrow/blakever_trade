#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高股息轮动策略
===============
按动量+趋势过滤定期轮动到高动量标的。
结合趋势过滤避免价值陷阱，适合港美股稳健型投资者。

注意: 真正的高股息轮动需要股息率数据，本策略使用
      价格动量+趋势过滤作为简化替代。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "高股息轮动策略"
STRATEGY_TYPE = "高股息轮动"
STRATEGY_PARAMS = {'lookback': 63, 'ema_period': 100, 'rsi_period': 14}


def generate_signals(close, high, low, open_prices,
                     lookback=63, ema_period=100, rsi_period=14):
    """高股息轮动策略信号生成（简化版：动量+趋势过滤）"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 长期趋势确认: 价格在EMA100上方
    ema = c.ewm(span=ema_period, adjust=False).mean()
    long_trend_up = c > ema

    # 3个月动量
    momentum = c / c.shift(lookback) - 1
    momentum_positive = momentum > 0

    # RSI非超买（避免追高）
    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), index=c.index)
    not_overbought = rsi < 70

    # 入场: 趋势向上 + 动量正向 + 未超买
    in_position = long_trend_up & momentum_positive & not_overbought

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
