#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD+Supertrend双重过滤策略
=============================
MACD柱状图确认大方向 + Supertrend精确触发。
双层过滤减少假信号。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "MACD+Supertrend双重过滤"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'atr_period': 10, 'atr_multiplier': 3.0, 'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9}


def generate_signals(close, high, low, open_prices,
                     atr_period=10, atr_multiplier=3.0,
                     macd_fast=12, macd_slow=26, macd_signal=9):
    """MACD+Supertrend双重过滤策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # --- MACD方向确认 ---
    macd_line, signal_line, hist = talib.MACD(
        c.values, fastperiod=macd_fast, slowperiod=macd_slow, signalperiod=macd_signal
    )
    hist = pd.Series(hist, index=c.index)
    macd_bullish = hist > 0  # MACD柱>0 → 多头方向

    # --- Supertrend触发 ---
    tr = pd.concat([
        h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    hl2 = (h + l) / 2
    upper_band = hl2 + atr_multiplier * atr
    lower_band = hl2 - atr_multiplier * atr

    direction = pd.Series(1, index=c.index)
    for i in range(1, n):
        if direction.iloc[i-1] == 1:
            if c.iloc[i] < lower_band.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = 1
        else:
            if c.iloc[i] > upper_band.iloc[i]:
                direction.iloc[i] = 1
            else:
                direction.iloc[i] = -1

    # --- 双重过滤: MACD多头 + Supertrend多头 ---
    in_position = macd_bullish & (direction == 1)

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
