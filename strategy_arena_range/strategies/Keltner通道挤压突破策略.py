#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keltner通道挤压突破策略
========================
波动率收缩突破: 当Keltner通道收窄后突破时入场。
震荡市中捕捉低波动后的方向性突破。
"""

import numpy as np
import talib

STRATEGY_NAME = "Keltner通道挤压突破策略"
STRATEGY_TYPE = "波动率收缩突破"
STRATEGY_PARAMS = {
    "ema_period": 20,
    "atr_period": 10,
    "atr_mult": 1.5,
    "squeeze_period": 6,
    "stop_loss_atr_mult": 2.0,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    Keltner通道挤压突破信号生成。
    挤压: 布林带在Keltner通道内（低波动）
    突破: 布林带突破Keltner通道上/下轨（波动率扩张）
    """
    ema_period = kwargs.get('ema_period', 20)
    atr_period = kwargs.get('atr_period', 10)
    atr_mult = kwargs.get('atr_mult', 1.5)
    squeeze_period = kwargs.get('squeeze_period', 6)
    sl_mult = kwargs.get('stop_loss_atr_mult', 2.0)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    # Keltner通道
    ema = talib.EMA(c, timeperiod=ema_period)
    atr = talib.ATR(h, l, c, timeperiod=atr_period)
    kelt_upper = ema + atr_mult * atr
    kelt_lower = ema - atr_mult * atr

    # 布林带（用于判断挤压）
    bb_upper, bb_mid, bb_lower = talib.BBANDS(c, timeperiod=20, nbdevup=2.0,
                                                nbdevdn=2.0)

    # 挤压判断: 布林带在Keltner通道内
    squeeze = (bb_upper < kelt_upper) & (bb_lower > kelt_lower)

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    squeeze_count = 0
    stop_price = np.nan

    for i in range(max(ema_period, 20) + 1, n):
        if not in_position:
            # 统计连续挤压天数
            if squeeze[i]:
                squeeze_count += 1
            else:
                if squeeze_count >= squeeze_period:
                    # 挤压后突破方向入场
                    if c[i] > kelt_upper[i]:
                        entries[i] = True
                        in_position = True
                        stop_price = c[i] - sl_mult * atr[i]
                    elif c[i] < kelt_lower[i]:
                        # 简化版不做空
                        pass
                squeeze_count = 0
        else:
            # 更新移动止损
            new_stop = c[i] - sl_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # 出场: 回归EMA 或 止损
            if c[i] <= ema[i]:
                exits[i] = True
                in_position = False
            elif c[i] <= stop_price:
                exits[i] = True
                in_position = False

    return entries, exits
