#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EMA交叉+ADX趋势强度过滤策略
==============================
经典EMA10/20交叉持仓 + ADX>20趋势强度过滤。
Blakever Agent3当前主力策略的宽松版实现。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "EMA交叉+ADX趋势强度过滤"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'ema_fast': 10, 'ema_slow': 20, 'adx_period': 14, 'adx_threshold': 20}


def generate_signals(close, high, low, open_prices,
                     ema_fast=10, ema_slow=20, adx_period=14, adx_threshold=20):
    """EMA交叉+ADX过滤策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # EMA
    ema_f = c.ewm(span=ema_fast, adjust=False).mean()
    ema_s = c.ewm(span=ema_slow, adjust=False).mean()

    # ADX
    adx = pd.Series(talib.ADX(h.values, l.values, c.values, timeperiod=adx_period),
                     index=c.index)

    # EMA多头排列 + ADX趋势强度
    ema_bullish = ema_f > ema_s
    adx_strong = adx > adx_threshold

    # 宽松模式: 两条件满足其一即可
    in_position = ema_bullish | adx_strong

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
