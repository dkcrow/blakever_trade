#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD背离+趋势确认策略
=======================
MACD柱状图从负转正（金叉确认）+ 价格在长期EMA上方。
减少震荡市假信号，只在趋势方向上交易。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "MACD金叉+趋势确认策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'trend_ema': 100}


def generate_signals(close, high, low, open_prices,
                     macd_fast=12, macd_slow=26, macd_signal=9, trend_ema=100):
    """MACD金叉+趋势确认策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 长期趋势
    ema_trend = c.ewm(span=trend_ema, adjust=False).mean()
    uptrend = c > ema_trend

    # MACD
    macd_line, signal_line, hist = talib.MACD(
        c.values, fastperiod=macd_fast, slowperiod=macd_slow, signalperiod=macd_signal
    )
    hist = pd.Series(hist, index=c.index)

    # MACD金叉: 柱状图从负转正
    macd_cross_up = (hist > 0) & (hist.shift(1) <= 0)
    # MACD死叉: 柱状图从正转负
    macd_cross_down = (hist < 0) & (hist.shift(1) >= 0)

    # 入场: 趋势向上 + MACD金叉
    # 出场: MACD死叉 或 趋势破位
    in_position = pd.Series(False, index=c.index)
    for i in range(1, n):
        if not in_position.iloc[i-1]:
            if macd_cross_up.iloc[i] and uptrend.iloc[i]:
                in_position.iloc[i] = True
        else:
            if macd_cross_down.iloc[i] or not uptrend.iloc[i]:
                in_position.iloc[i] = False
            else:
                in_position.iloc[i] = True

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
