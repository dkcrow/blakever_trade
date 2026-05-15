#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配对交易均值回归策略
====================
统计套利: 选择高相关股票对，根据价差Z-Score交易。
做多弱势+做空强势，市场中性。
简化版: 单标的与均线偏差交易（模拟配对）。
"""

import numpy as np
import talib

STRATEGY_NAME = "配对交易均值回归策略"
STRATEGY_TYPE = "套利"
STRATEGY_PARAMS = {
    "lookback_period": 20,
    "z_entry": 2.0,
    "z_exit": 0.5,
    "atr_period": 14,
    "stop_loss_atr_mult": 3.0,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    配对交易均值回归信号生成（简化版）。
    使用价格与均线的偏差（Z-Score）作为交易信号。
    """
    lookback = kwargs.get('lookback_period', 20)
    z_entry = kwargs.get('z_entry', 2.0)
    z_exit = kwargs.get('z_exit', 0.5)
    atr_period = kwargs.get('atr_period', 14)
    sl_mult = kwargs.get('stop_loss_atr_mult', 3.0)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    # 计算滚动Z-Score（价格vs均线）
    sma = talib.SMA(c, timeperiod=lookback)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)
    std = talib.STDDEV(c, timeperiod=lookback, nbdev=1)

    z_score = np.full(n, np.nan)
    for i in range(lookback, n):
        if std[i] > 0:
            z_score[i] = (c[i] - sma[i]) / std[i]

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    stop_price = np.nan

    for i in range(lookback + 1, n):
        if np.isnan(z_score[i]):
            continue

        if not in_position:
            # Z-Score低于-2: 价格严重偏低，买入
            if z_score[i] < -z_entry:
                entries[i] = True
                in_position = True
                stop_price = c[i] - sl_mult * atr[i]
        else:
            # 更新止损
            new_stop = c[i] - sl_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # Z-Score回归到0附近: 平仓
            if z_score[i] > -z_exit:
                exits[i] = True
                in_position = False
            # 止损
            elif c[i] <= stop_price:
                exits[i] = True
                in_position = False

    return entries, exits
