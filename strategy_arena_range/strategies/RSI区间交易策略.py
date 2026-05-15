#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSI区间交易策略
================
RSI均值回归: RSI跌破30超卖区买入，RSI升破70超买区卖出。
配合ATR止损和时间止损。
"""

import numpy as np
import talib

STRATEGY_NAME = "RSI区间交易策略"
STRATEGY_TYPE = "震荡区间交易"
STRATEGY_PARAMS = {
    "rsi_period": 14,
    "rsi_low": 30,
    "rsi_high": 70,
    "atr_period": 14,
    "atr_mult": 2.5,
    "max_holding_bars": 20,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    RSI区间交易信号生成。
    """
    rsi_period = kwargs.get('rsi_period', 14)
    rsi_low = kwargs.get('rsi_low', 30)
    rsi_high = kwargs.get('rsi_high', 70)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.5)
    max_holding = kwargs.get('max_holding_bars', 20)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    rsi = talib.RSI(c, timeperiod=rsi_period)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)

    entries = np.full(n, False)
    exits = np.full(n, False)

    holding_bars = 0
    in_position = False
    stop_price = np.nan

    for i in range(rsi_period + 1, n):
        if not in_position:
            # RSI超卖买入
            if rsi[i] < rsi_low and rsi[i-1] >= rsi_low:
                entries[i] = True
                in_position = True
                holding_bars = 0
                stop_price = c[i] - atr_mult * atr[i]
            # RSI超买卖出（反向：做空不在此策略范围）
        else:
            holding_bars += 1
            # 更新移动止损
            new_stop = c[i] - atr_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # RSI超买卖出
            if rsi[i] > rsi_high and rsi[i-1] <= rsi_high:
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
