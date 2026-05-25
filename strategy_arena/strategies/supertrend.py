#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Supertrend ATR自适应趋势跟踪策略
=================================
ATR驱动自适应趋势跟踪，无需均线交叉，对趋势变化响应更快。
适合港美股牛市趋势跟随。

核心逻辑:
  - Supertrend = (HL2 ± ATR×Multiplier) 根据价格位置切换上下轨
  - 价格在Supertrend上方 → 持仓
  - 价格跌破Supertrend → 空仓
"""

import numpy as np
import pandas as pd

STRATEGY_NAME = "Supertrend ATR自适应趋势跟踪"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'atr_period': 10, 'atr_multiplier': 3.0}


def generate_signals(close, high, low, open_prices, atr_period=10, atr_multiplier=3.0):
    """Supertrend策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # 计算ATR
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()

    # HL2
    hl2 = (h + l) / 2

    # 上轨和下轨
    upper_band = hl2 + atr_multiplier * atr
    lower_band = hl2 - atr_multiplier * atr

    # Supertrend方向
    supertrend = pd.Series(np.nan, index=c.index)
    direction = pd.Series(1, index=c.index)  # 1=上涨, -1=下跌

    for i in range(1, n):
        # 上轨只能下移，下轨只能上移
        if upper_band.iloc[i] < upper_band.iloc[i-1] or c.iloc[i-1] > upper_band.iloc[i-1]:
            upper_band.iloc[i] = upper_band.iloc[i]
        else:
            upper_band.iloc[i] = upper_band.iloc[i-1]

        if lower_band.iloc[i] > lower_band.iloc[i-1] or c.iloc[i-1] < lower_band.iloc[i-1]:
            lower_band.iloc[i] = lower_band.iloc[i]
        else:
            lower_band.iloc[i] = lower_band.iloc[i-1]

        # 方向切换
        if direction.iloc[i-1] == 1:  # 之前上涨
            if c.iloc[i] < lower_band.iloc[i]:
                direction.iloc[i] = -1
                supertrend.iloc[i] = upper_band.iloc[i]
            else:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lower_band.iloc[i]
        else:  # 之前下跌
            if c.iloc[i] > upper_band.iloc[i]:
                direction.iloc[i] = 1
                supertrend.iloc[i] = lower_band.iloc[i]
            else:
                direction.iloc[i] = -1
                supertrend.iloc[i] = upper_band.iloc[i]

    # 入场/出场信号
    in_position = direction == 1
    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
