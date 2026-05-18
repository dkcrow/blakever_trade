#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD柱状图反转策略
==================
均值回归: MACD柱状图从负转正（底背离）买入，从正转负卖出。
震荡市中捕捉短期动量反转，含ATR止损。
"""

import numpy as np
import talib

STRATEGY_NAME = "MACD柱状图反转策略"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14,
    "atr_mult": 2.0,
    "rsi_filter_low": 40,
    "rsi_filter_high": 60,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    MACD柱状图反转信号生成。
    入场: MACD柱从负转正 + RSI在低位区域
    出场: MACD柱从正转负 或 ATR止损
    """
    fast = kwargs.get('macd_fast', 12)
    slow = kwargs.get('macd_slow', 26)
    signal = kwargs.get('macd_signal', 9)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.0)
    rsi_low = kwargs.get('rsi_filter_low', 40)
    rsi_high = kwargs.get('rsi_filter_high', 60)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    macd, macd_signal, macd_hist = talib.MACD(c, fastperiod=fast,
                                                slowperiod=slow,
                                                signalperiod=signal)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)
    rsi = talib.RSI(c, timeperiod=14)

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    stop_price = np.nan

    for i in range(slow + signal + 1, n):
        if np.isnan(macd_hist[i]) or np.isnan(atr[i]):
            continue

        if not in_position:
            # MACD柱从负转正 + RSI在低位（超卖反弹）
            if macd_hist[i] > 0 and macd_hist[i-1] <= 0 and rsi[i] < rsi_high:
                entries[i] = True
                in_position = True
                stop_price = c[i] - atr_mult * atr[i]
        else:
            # 更新止损
            new_stop = c[i] - atr_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # MACD柱从正转负: 卖出
            if macd_hist[i] < 0 and macd_hist[i-1] >= 0:
                exits[i] = True
                in_position = False
            # ATR止损
            elif c[i] <= stop_price:
                exits[i] = True
                in_position = False

    return entries, exits
