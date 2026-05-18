#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经典MACD金叉死叉策略（最基础用法）
====================================
买: DIF上穿DEA（金叉）
卖: DIF下穿DEA（死叉）
无任何过滤条件，最经典的MACD用法。
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "经典MACD金叉死叉策略"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'fast': 12, 'slow': 26, 'signal': 9}


def generate_signals(close, high, low, open_prices,
                     fast=12, slow=26, signal=9):
    """经典MACD金叉死叉策略信号生成"""
    c = pd.Series(close, dtype=float)

    # MACD指标
    macd_line, signal_line, hist = talib.MACD(
        c.values, fastperiod=fast, slowperiod=slow, signalperiod=signal
    )
    macd_line = pd.Series(macd_line, index=c.index)
    signal_line = pd.Series(signal_line, index=c.index)

    # 金叉: DIF上穿DEA
    golden_cross = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line)
    # 死叉: DIF下穿DEA
    death_cross = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line)

    entries = golden_cross.fillna(False).values
    exits = death_cross.fillna(False).values

    return entries, exits
