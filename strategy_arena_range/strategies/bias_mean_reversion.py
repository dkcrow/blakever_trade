#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双均线乖离回归策略
==================
均值回归: 价格偏离短期均线超过阈值时反向交易。
乖离过大时高抛低吸，回归均线平仓。含ATR止损。
"""

import numpy as np
import talib

STRATEGY_NAME = "双均线乖离回归策略"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {
    "ema_fast": 10,
    "ema_slow": 30,
    "bias_threshold": 3.0,
    "atr_period": 14,
    "atr_mult": 2.0,
    "take_profit_bias": 1.0,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    双均线乖离回归信号生成。
    乖离率 = (价格 - EMA_fast) / EMA_fast * 100
    乖离率 < -threshold: 买入（超卖回归）
    乖离率 > +threshold: 不做空（简化版只做多）
    乖离率回归0附近: 平仓
    """
    ema_fast = kwargs.get('ema_fast', 10)
    ema_slow = kwargs.get('ema_slow', 30)
    bias_threshold = kwargs.get('bias_threshold', 3.0)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.0)
    tp_bias = kwargs.get('take_profit_bias', 1.0)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    ema_f = talib.EMA(c, timeperiod=ema_fast)
    ema_s = talib.EMA(c, timeperiod=ema_slow)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)

    # 乖离率
    bias = np.full(n, np.nan)
    for i in range(ema_fast, n):
        if ema_f[i] > 0:
            bias[i] = (c[i] - ema_f[i]) / ema_f[i] * 100

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    stop_price = np.nan

    for i in range(max(ema_fast, ema_slow) + 1, n):
        if np.isnan(bias[i]):
            continue

        if not in_position:
            # 负乖离过大 + 价格在长期均线上方（趋势不坏）
            if bias[i] < -bias_threshold and c[i] > ema_s[i]:
                entries[i] = True
                in_position = True
                stop_price = c[i] - atr_mult * atr[i]
        else:
            # 更新止损
            new_stop = c[i] - atr_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # 乖离回归0附近: 止盈
            if bias[i] > -tp_bias:
                exits[i] = True
                in_position = False
            # ATR止损
            elif c[i] <= stop_price:
                exits[i] = True
                in_position = False
            # 价格跌破长期均线: 趋势破坏
            elif c[i] < ema_s[i]:
                exits[i] = True
                in_position = False

    return entries, exits
