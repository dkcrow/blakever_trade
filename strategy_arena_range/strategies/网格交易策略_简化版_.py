#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网格交易策略（简化版）
======================
震荡市核心策略: 在设定价格区间内按固定间隔高抛低吸。
简化版使用百分比网格。
"""

import numpy as np
import talib

STRATEGY_NAME = "网格交易策略(简化版)"
STRATEGY_TYPE = "网格对冲"
STRATEGY_PARAMS = {
    "grid_size_pct": 2.0,
    "grid_levels": 5,
    "atr_period": 14,
    "stop_loss_pct": 8.0,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    网格交易信号生成（简化版）。
    使用移动平均线作为网格中心，上下各设grid_levels层。
    """
    grid_size = kwargs.get('grid_size_pct', 2.0) / 100
    grid_levels = kwargs.get('grid_levels', 5)
    atr_period = kwargs.get('atr_period', 14)
    stop_loss_pct = kwargs.get('stop_loss_pct', 8.0) / 100

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    # 网格中心: 使用20日均线
    center = talib.SMA(c, timeperiod=20)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    entry_price = 0
    current_level = 0

    for i in range(21, n):
        if np.isnan(center[i]):
            continue

        if not in_position:
            # 价格在网格下半部分时买入（低吸）
            # 当价格跌破中心-1个网格时入场
            if c[i] <= center[i] * (1 - grid_size):
                entries[i] = True
                in_position = True
                entry_price = c[i]
                # 计算在哪一层网格
                for lev in range(1, grid_levels + 1):
                    if c[i] <= center[i] * (1 - lev * grid_size):
                        current_level = lev
        else:
            # 高抛: 价格涨到中心线以上
            if c[i] >= center[i]:
                exits[i] = True
                in_position = False
            # 止损
            elif c[i] <= entry_price * (1 - stop_loss_pct):
                exits[i] = True
                in_position = False
            # 到达更高网格层也可止盈
            elif current_level > 0 and c[i] >= center[i] * (1 - (current_level - 1) * grid_size):
                exits[i] = True
                in_position = False

    return entries, exits
