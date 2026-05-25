#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经典RSI超买超卖策略（最基础用法）
====================================
买: RSI从超卖区回升（RSI上穿30）
卖: RSI进入超买区（RSI上穿70）
使用标准RSI(14)参数。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "经典RSI超买超卖策略"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {'rsi_period': 14, 'oversold': 30, 'overbought': 70}


def generate_signals(close, high, low, open_prices,
                     rsi_period=14, oversold=30, overbought=70):
    """经典RSI超买超卖策略信号生成"""
    c = pd.Series(close, dtype=float)

    # RSI指标
    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), index=c.index)

    # 入场: RSI从超卖区回升（上穿30）
    rsi_oversold_cross = (rsi > oversold) & (rsi.shift(1) <= oversold)
    entries = rsi_oversold_cross.fillna(False).values

    # 出场: RSI进入超买区（上穿70）
    rsi_overbought_cross = (rsi > overbought) & (rsi.shift(1) <= overbought)
    exits = rsi_overbought_cross.fillna(False).values

    return entries, exits
