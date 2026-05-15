#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Donchian通道回归策略
====================
区间交易: 价格触及Donchian通道下轨买入，上轨卖出。
适合宽幅震荡行情，含固定比例止损。
"""

import numpy as np
import talib

STRATEGY_NAME = "Donchian通道回归策略"
STRATEGY_TYPE = "震荡区间交易"
STRATEGY_PARAMS = {
    "channel_period": 20,
    "atr_period": 14,
    "stop_loss_pct": 5.0,
    "take_profit_pct": 4.0,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    Donchian通道回归信号生成。
    """
    channel_period = kwargs.get('channel_period', 20)
    atr_period = kwargs.get('atr_period', 14)
    stop_loss_pct = kwargs.get('stop_loss_pct', 5.0) / 100
    take_profit_pct = kwargs.get('take_profit_pct', 4.0) / 100

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    # Donchian通道
    upper = talib.MAX(h, timeperiod=channel_period)
    lower = talib.MIN(l, timeperiod=channel_period)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    entry_price = 0

    for i in range(channel_period + 1, n):
        if not in_position:
            # 价格触及下轨附近买入
            if c[i] <= lower[i] + atr[i] * 0.5:
                entries[i] = True
                in_position = True
                entry_price = c[i]
        else:
            # 止盈: 到达通道中轨或上轨附近
            mid = (upper[i] + lower[i]) / 2
            if c[i] >= mid:
                exits[i] = True
                in_position = False
            # 固定比例止损
            elif c[i] <= entry_price * (1 - stop_loss_pct):
                exits[i] = True
                in_position = False
            # 固定比例止盈
            elif c[i] >= entry_price * (1 + take_profit_pct):
                exits[i] = True
                in_position = False

    return entries, exits
