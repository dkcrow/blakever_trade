#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VWAP趋势跟踪策略
=================
利用VWAP(成交量加权平均价)作为日内趋势参考。
价格在VWAP上方持仓，下方空仓。
适合流动性好的港美股大盘股。
"""

import numpy as np
import pandas as pd

STRATEGY_NAME = "VWAP趋势跟踪策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'vwap_period': 20}


def generate_signals(close, high, low, open_prices, vwap_period=20, **kwargs):
    """VWAP趋势跟踪策略信号生成"""
    n = len(close)
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    v = kwargs.get('volume', None)

    # 典型价格
    typical_price = (h + l + c) / 3

    # 如果有成交量数据，计算真实VWAP
    if v is not None:
        v = pd.Series(v, dtype=float)
        cum_tp_vol = (typical_price * v).rolling(vwap_period).sum()
        cum_vol = v.rolling(vwap_period).sum()
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    else:
        # 无成交量时，用典型价格的SMA近似
        vwap = typical_price.rolling(vwap_period).mean()

    # 价格在VWAP上方 → 持仓
    in_position = c > vwap

    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values

    return entries, exits
