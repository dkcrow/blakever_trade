#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Triple EMA三层均线策略
=======================
EMA10/EMA30/EMA50三线多头排列持仓，空头排列空仓。
三线系统比双线更稳定，过滤更多假信号。
"""

import numpy as np
import pandas as pd

STRATEGY_NAME = "Triple EMA三层均线策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'ema_short': 5, 'ema_mid': 15, 'ema_long': 30}


def generate_signals(close, high, low, open_prices,
                     ema_short=5, ema_mid=15, ema_long=30):
    """Triple EMA三层均线策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)

    # 三层EMA
    ema_s = c.ewm(span=ema_short, adjust=False).mean()
    ema_m = c.ewm(span=ema_mid, adjust=False).mean()
    ema_l = c.ewm(span=ema_long, adjust=False).mean()

    # 多头排列: 短>中>长
    bullish = (ema_s > ema_m) & (ema_m > ema_l)

    entries = (bullish & ~bullish.shift(1).fillna(False)).fillna(False).values
    exits = (~bullish & bullish.shift(1).fillna(False)).fillna(False).values

    return entries, exits
