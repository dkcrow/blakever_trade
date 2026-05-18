#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
支撑阻力区间交易策略
====================
震荡区间交易: 识别关键支撑/阻力位，在支撑位买入、阻力位卖出。
使用滚动窗口计算支撑阻力，含ATR止损和时间止损。
"""

import numpy as np
import talib

STRATEGY_NAME = "支撑阻力区间交易策略"
STRATEGY_TYPE = "震荡区间交易"
STRATEGY_PARAMS = {
    "channel_period": 20,
    "atr_period": 14,
    "atr_mult": 2.0,
    "max_holding_bars": 15,
    "breakout_buffer_pct": 0.5,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    支撑阻力区间交易信号生成。
    支撑 = 滚动窗口最低价
    阻力 = 滚动窗口最高价
    """
    channel_period = kwargs.get('channel_period', 20)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.0)
    max_holding = kwargs.get('max_holding_bars', 15)
    buffer_pct = kwargs.get('breakout_buffer_pct', 0.5) / 100

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    atr = talib.ATR(h, l, c, timeperiod=atr_period)

    # 滚动支撑阻力
    support = talib.MIN(l, timeperiod=channel_period)
    resistance = talib.MAX(h, timeperiod=channel_period)

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    holding_bars = 0
    stop_price = np.nan

    for i in range(channel_period + 1, n):
        if not in_position:
            # 价格接近支撑位（在支撑+buffer范围内）
            support_threshold = support[i] * (1 + buffer_pct)
            if c[i] <= support_threshold and c[i] > support[i] * (1 - 0.03):
                entries[i] = True
                in_position = True
                holding_bars = 0
                stop_price = c[i] - atr_mult * atr[i]
        else:
            holding_bars += 1
            # 更新止损
            new_stop = c[i] - atr_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # 到达阻力位: 高抛
            resistance_threshold = resistance[i] * (1 - buffer_pct)
            if c[i] >= resistance_threshold:
                exits[i] = True
                in_position = False
            # ATR止损
            elif c[i] <= stop_price:
                exits[i] = True
                in_position = False
            # 时间止损
            elif holding_bars >= max_holding:
                exits[i] = True
                in_position = False

    return entries, exits
