"""
低波轮动策略
低波轮动策略：选择历史波动率最低的标的持有，定期轮动。
熊市中低波动标的往往抗跌，防御效果优异。
注意：单标的版本使用自身波动率相对水平判断是否持有。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "低波轮动策略"
STRATEGY_TYPE = "低波轮动"
STRATEGY_PARAMS = {'vol_lookback': 40, 'ema_period': 30, 'vol_threshold': 0.3}


def generate_signals(close, high, low, open_prices, **kwargs):
    vol_lookback = kwargs.get('vol_lookback', 40)
    ema_period = kwargs.get('ema_period', 30)
    vol_threshold = kwargs.get('vol_threshold', 0.3)

    c = pd.Series(close, dtype=float)
    n = len(c)

    # 日收益率波动率
    returns = c.pct_change()
    hist_vol = returns.rolling(vol_lookback).std() * np.sqrt(252)

    # 波动率的中位数和阈值
    vol_median = hist_vol.rolling(252).median()

    # 价格趋势确认
    ema = c.ewm(span=ema_period, adjust=False).mean()

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(max(vol_lookback, 252), n):
        if pd.isna(hist_vol.iloc[i]) or pd.isna(vol_median.iloc[i]):
            continue

        # 低波动条件：当前波动率低于中位数的一定比例
        is_low_vol = hist_vol.iloc[i] < vol_median.iloc[i] * (1 + vol_threshold)

        if not in_pos:
            # 低波动 + 价格趋势向上 → 入场
            if is_low_vol and c.iloc[i] > ema.iloc[i]:
                entries[i] = True
                in_pos = True
        else:
            # 波动率飙升 或 趋势转弱 → 出场
            if hist_vol.iloc[i] > vol_median.iloc[i] * 1.5 or c.iloc[i] < ema.iloc[i] * 0.97:
                exits[i] = True
                in_pos = False

    return entries, exits
