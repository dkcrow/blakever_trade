#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Donchian通道突破策略（海龟交易法核心）
========================================
20日新高入场，10日新低出场。经典趋势突破策略。
适合港美股趋势跟踪。
"""

import numpy as np
import pandas as pd

STRATEGY_NAME = "Donchian通道突破(海龟交易法)"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'entry_window': 20, 'exit_window': 10}


def generate_signals(close, high, low, open_prices, entry_window=20, exit_window=10):
    """Donchian通道突破策略信号生成"""
    n = len(close)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # 入场: 收盘价突破N日最高价
    highest = h.rolling(entry_window).max().shift(1)
    # 出场: 收盘价跌破M日最低价
    lowest = l.rolling(exit_window).min().shift(1)

    c = pd.Series(close, dtype=float)

    # 信号
    long_entry = c > highest
    long_exit = c < lowest

    # 转换为持仓状态
    in_position = pd.Series(False, index=c.index)
    for i in range(1, n):
        if long_entry.iloc[i]:
            in_position.iloc[i] = True
        elif long_exit.iloc[i]:
            in_position.iloc[i] = False
        else:
            in_position.iloc[i] = in_position.iloc[i-1]

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
