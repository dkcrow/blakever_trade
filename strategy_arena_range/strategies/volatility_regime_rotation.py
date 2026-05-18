#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波动率收缩-扩张轮动策略
========================
波动率策略: 低波动期持有（收窄期积攒利润），高波动期减仓避险。
使用ATR判断波动率状态，适合震荡市波动率周期轮动。
"""

import numpy as np
import talib

STRATEGY_NAME = "波动率收缩-扩张轮动策略"
STRATEGY_TYPE = "波动率收缩突破"
STRATEGY_PARAMS = {
    "vol_window": 20,
    "vol_low_pctile": 30,
    "vol_high_pctile": 70,
    "atr_period": 14,
    "atr_mult": 2.5,
    "lookback_vol": 60,
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    波动率轮动信号生成。
    低波动期（ATR在历史低位）: 积极入场
    高波动期（ATR在历史高位）: 减仓/空仓
    """
    vol_window = kwargs.get('vol_window', 20)
    vol_low_pctile = kwargs.get('vol_low_pctile', 30)
    vol_high_pctile = kwargs.get('vol_high_pctile', 70)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.5)
    lookback_vol = kwargs.get('lookback_vol', 60)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    atr = talib.ATR(h, l, c, timeperiod=atr_period)
    sma = talib.SMA(c, timeperiod=vol_window)

    # 波动率百分位
    vol_pctile = np.full(n, np.nan)
    for i in range(lookback_vol, n):
        window_atr = atr[i-lookback_vol+1:i+1]
        valid = window_atr[~np.isnan(window_atr)]
        if len(valid) > 10:
            vol_pctile[i] = np.sum(valid <= atr[i]) / len(valid) * 100

    entries = np.full(n, False)
    exits = np.full(n, False)

    in_position = False
    stop_price = np.nan

    for i in range(lookback_vol + 1, n):
        if np.isnan(vol_pctile[i]):
            continue

        if not in_position:
            # 低波动期 + 价格在均线上方: 入场
            if vol_pctile[i] < vol_low_pctile and c[i] > sma[i]:
                entries[i] = True
                in_position = True
                stop_price = c[i] - atr_mult * atr[i]
        else:
            # 更新止损
            new_stop = c[i] - atr_mult * atr[i]
            stop_price = max(new_stop, stop_price) if not np.isnan(stop_price) else new_stop

            # 高波动期: 出场避险
            if vol_pctile[i] > vol_high_pctile:
                exits[i] = True
                in_position = False
            # 价格跌破均线
            elif c[i] < sma[i]:
                exits[i] = True
                in_position = False
            # ATR止损
            elif c[i] <= stop_price:
                exits[i] = True
                in_position = False

    return entries, exits
