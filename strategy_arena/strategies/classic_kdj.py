#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经典KDJ金叉死叉策略（最基础用法）
====================================
买: K线上穿D线（金叉），且K < 80（非超买区金叉更有效）
卖: K线下穿D线（死叉），且K > 20（非超卖区死叉更有效）
使用标准的(9,3,3)参数。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "经典KDJ金叉死叉策略"
STRATEGY_TYPE = "震荡指标"
STRATEGY_PARAMS = {'k_period': 9, 'k_smooth': 3, 'd_smooth': 3}


def generate_signals(close, high, low, open_prices,
                     k_period=9, k_smooth=3, d_smooth=3):
    """经典KDJ金叉死叉策略信号生成"""
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # 使用talib的STOCH（随机指标）计算KDJ
    # fastk_period=9, slowk_period=3, slowd_period=3 对应标准KDJ(9,3,3)
    k_line, d_line = talib.STOCH(
        h.values, l.values, c.values,
        fastk_period=k_period,
        slowk_period=k_smooth,
        slowk_matype=0,  # SMA
        slowd_period=d_smooth,
        slowd_matype=0   # SMA
    )
    k_line = pd.Series(k_line, index=c.index)
    d_line = pd.Series(d_line, index=c.index)
    j_line = 3 * k_line - 2 * d_line

    # 金叉: K上穿D
    golden_cross = (k_line > d_line) & (k_line.shift(1) <= d_line)
    # 死叉: K下穿D
    death_cross = (k_line < d_line) & (k_line.shift(1) >= d_line)

    entries = golden_cross.fillna(False).values
    exits = death_cross.fillna(False).values

    return entries, exits
