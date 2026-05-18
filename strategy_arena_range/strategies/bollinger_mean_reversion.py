#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布林带均值回归策略
==================
经典震荡市策略: 价格触及布林带下轨买入，回归中轨平仓。
使用ATR移动止损保护。
"""

import numpy as np
import talib

STRATEGY_NAME = "布林带均值回归策略"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "atr_period": 14,
    "atr_mult": 2.5,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    布林带均值回归信号生成。

    入场: 价格跌破下轨(RSI确认超卖)
    出场: 价格回归中轨 或 ATR移动止损
    """
    bb_period = kwargs.get('bb_period', 20)
    bb_std = kwargs.get('bb_std', 2.0)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.5)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    # 布林带
    upper, middle, lower = talib.BBANDS(c, timeperiod=bb_period, nbdevup=bb_std,
                                         nbdevdn=bb_std, matype=0)
    # ATR
    atr = talib.ATR(h, l, c, timeperiod=atr_period)
    # RSI辅助确认
    rsi = talib.RSI(c, timeperiod=14)

    entries = np.full(n, False)
    exits = np.full(n, False)

    # 止损线
    stop_loss_price = np.full(n, np.nan)

    for i in range(max(bb_period, atr_period, 14) + 1, n):
        # 入场: 价格跌破下轨 + RSI超卖确认
        if c[i] <= lower[i] and rsi[i] < 35:
            entries[i] = True
            stop_loss_price[i] = c[i] - atr_mult * atr[i]

        # 出场: 价格回归中轨 或 触发止损
        if entries[:i].any():
            # 找最近一次入场
            last_entry_idx = np.where(entries[:i])[0][-1]
            if i > last_entry_idx:
                # 更新移动止损线（只上不下）
                new_stop = c[i] - atr_mult * atr[i]
                prev_stop = stop_loss_price[last_entry_idx]
                stop_loss_price[i] = max(new_stop, prev_stop) if not np.isnan(prev_stop) else new_stop

                # 中轨出场
                if c[i] >= middle[i]:
                    exits[i] = True
                # 止损出场
                elif c[i] <= stop_loss_price[i]:
                    exits[i] = True

    return entries, exits
