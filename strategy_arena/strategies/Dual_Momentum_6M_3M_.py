#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dual Momentum双动量策略
========================
绝对动量+相对动量月度轮动。
12M绝对动量确认大方向，1M相对动量确认短期趋势。
"""

import numpy as np
import pandas as pd

STRATEGY_NAME = "Dual Momentum双动量策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'lookback_long': 6, 'lookback_short': 3}


def generate_signals(close, high, low, open_prices, lookback_long=6, lookback_short=3):
    """双动量策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 长期动量（12M）
    mom_long = c / c.shift(lookback_long) - 1
    # 短期动量（1M）
    mom_short = c / c.shift(lookback_short) - 1

    # 入场条件: 长期动量>0 且 短期动量>0
    in_position = (mom_long > 0) & (mom_short > 0)

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
