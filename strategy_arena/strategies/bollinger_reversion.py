#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布林带均值回归策略
====================
价格触及布林带下轨买入，上轨卖出，回归中轨平仓。
经典均值回归策略，适合震荡市和港美股回调行情。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "布林带均值回归策略"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {'bb_period': 20, 'bb_std': 2.0}


def generate_signals(close, high, low, open_prices, bb_period=20, bb_std=2.0):
    """布林带均值回归策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 布林带
    upper, middle, lower = talib.BBANDS(
        c.values, timeperiod=bb_period, nbdevup=bb_std, nbdevdn=bb_std, matype=0
    )
    upper = pd.Series(upper, index=c.index)
    middle = pd.Series(middle, index=c.index)
    lower = pd.Series(lower, index=c.index)

    # 入场: 收盘价触及下轨
    entry_signal = c <= lower

    # 出场: 收盘价触及上轨或回到中轨上方
    exit_signal = (c >= upper) | (c > middle)

    # 转换为持仓状态
    in_position = pd.Series(False, index=c.index)
    for i in range(1, n):
        if entry_signal.iloc[i] and not in_position.iloc[i-1]:
            in_position.iloc[i] = True
        elif exit_signal.iloc[i] and in_position.iloc[i-1]:
            in_position.iloc[i] = False
        else:
            in_position.iloc[i] = in_position.iloc[i-1]

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
