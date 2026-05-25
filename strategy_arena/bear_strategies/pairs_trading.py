"""
配对交易均值回归策略
对冲/配对策略：选择高相关股票对，根据价差Z-Score进行配对交易，
做多弱势股+做空强势股，市场中性。
注意：简化版仅做单标的均值回归，真实配对需两只标的价差计算。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "配对交易均值回归策略"
STRATEGY_TYPE = "对冲/配对"
STRATEGY_PARAMS = {'lookback': 60, 'entry_zscore': 2.0, 'exit_zscore': 0.5}


def generate_signals(close, high, low, open_prices, **kwargs):
    lookback = kwargs.get('lookback', 60)
    entry_zscore = kwargs.get('entry_zscore', 2.0)
    exit_zscore = kwargs.get('exit_zscore', 0.5)

    c = pd.Series(close, dtype=float)
    n = len(c)

    # 计算价格Z-Score
    rolling_mean = c.rolling(lookback).mean()
    rolling_std = c.rolling(lookback).std()
    z_score = (c - rolling_mean) / rolling_std

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(lookback, n):
        if pd.isna(z_score.iloc[i]):
            continue

        if not in_pos:
            # Z-Score < -entry → 价格偏低，买入
            if z_score.iloc[i] < -entry_zscore:
                entries[i] = True
                in_pos = True
        else:
            # Z-Score回归到exit附近 → 平仓
            if abs(z_score.iloc[i]) < exit_zscore:
                exits[i] = True
                in_pos = False
            # 安全止损：Z-Score极端偏离
            elif z_score.iloc[i] < -4.0:
                exits[i] = True
                in_pos = False

    return entries, exits
