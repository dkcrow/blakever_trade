#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSI趋势确认策略
================
RSI在40-70区间+价格在EMA上方 → 持仓（牛市趋势确认区域）
RSI跌破40或超过80 → 出场
比纯RSI超买超卖更稳健的牛市策略。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "RSI趋势确认策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'rsi_period': 14, 'ema_period': 50, 'rsi_lower': 40, 'rsi_upper': 80}


def generate_signals(close, high, low, open_prices,
                     rsi_period=14, ema_period=50, rsi_lower=40, rsi_upper=80):
    """RSI趋势确认策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 趋势: 价格在EMA上方
    ema = c.ewm(span=ema_period, adjust=False).mean()
    uptrend = c > ema

    # RSI
    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), index=c.index)

    # RSI在牛市确认区域(40-70): 上升趋势中的正常回调区间
    rsi_bull_zone = (rsi >= rsi_lower) & (rsi <= rsi_upper)

    # 入场: 趋势向上 + RSI进入牛市确认区
    # 出场: 趋势破位 或 RSI跌破下限 或 RSI超买
    in_position = uptrend & rsi_bull_zone

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
