#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MA5均线交叉策略
===============
核心逻辑（源自聚宽策略）:
  - 计算过去5天收盘价均值(MA5)
  - 当前价 > MA5 * 1.01 → 买入信号
  - 当前价 < MA5 → 卖出信号
  - 全仓进出

适配说明：
  - 原聚宽策略仅交易单只股票（平安银行000001.XSHE）
  - 此处改为在A股标的池上批量回测
  - T+1修正已由回测引擎处理
"""

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "MA5均线交叉"
STRATEGY_TYPE = "趋势跟踪"
STRATEGY_PARAMS = {'ma_period': 5, 'buy_threshold': 1.01}


def generate_signals(close, high, low, open_prices, ma_period=5, buy_threshold=1.01):
    """
    MA5均线交叉策略信号生成
    
    参数:
        close: np.ndarray - 收盘价序列
        high: np.ndarray - 最高价序列
        low: np.ndarray - 最低价序列
        open_prices: np.ndarray - 开盘价序列
        ma_period: int - 均线周期（默认5）
        buy_threshold: float - 买入阈值（默认1.01，即高于均线1%）
    
    返回:
        entries: np.ndarray[bool] - 入场信号
        exits: np.ndarray[bool] - 出场信号
    """
    n = len(close)
    c = pd.Series(close, dtype=float)
    
    # 计算MA5均线
    ma = c.rolling(window=ma_period).mean()
    
    # 持仓条件：价格高于MA5 * buy_threshold
    in_position = c > ma * buy_threshold
    
    # 生成入场信号：从空仓转为持仓
    entries = (in_position & ~in_position.shift(1).fillna(False)).fillna(False).values
    # 生成出场信号：从持仓转为空仓
    exits = (~in_position & in_position.shift(1).fillna(False)).fillna(False).values
    
    return entries, exits
