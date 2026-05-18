"""
VIX择时避险策略
避险资产轮动策略：当波动率指标突破阈值时切换到避险模式（空仓），
波动率回落时恢复股票持仓。利用恐慌情绪择时切换。
注意：简化版使用ATR/价格波动率替代VIX。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "VIX择时避险策略"
STRATEGY_TYPE = "避险资产轮动"
STRATEGY_PARAMS = {'atr_period': 14, 'vol_lookback': 30, 'vol_threshold': 1.2, 'ema_period': 20}


def generate_signals(close, high, low, open_prices, **kwargs):
    atr_period = kwargs.get('atr_period', 14)
    vol_lookback = kwargs.get('vol_lookback', 60)
    vol_threshold = kwargs.get('vol_threshold', 1.5)
    ema_period = kwargs.get('ema_period', 20)

    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    # ATR波动率指标（替代VIX）
    atr = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=atr_period), dtype=float)
    atr_pct = atr / c  # ATR占价格比例

    # ATR%的滚动统计
    atr_pct_mean = atr_pct.rolling(vol_lookback).mean()
    atr_pct_std = atr_pct.rolling(vol_lookback).std()

    # 波动率Z-Score
    vol_zscore = (atr_pct - atr_pct_mean) / atr_pct_std

    # 趋势指标
    ema = c.ewm(span=ema_period, adjust=False).mean()

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(vol_lookback, n):
        if pd.isna(vol_zscore.iloc[i]) or pd.isna(ema.iloc[i]):
            continue

        # 波动率飙升 → 避险模式（空仓）
        high_vol = vol_zscore.iloc[i] > vol_threshold
        # 波动率回落 → 恢复持仓
        low_vol = vol_zscore.iloc[i] < 0  # 低于均值

        if not in_pos:
            # 低波动 + 价格反弹 → 入场
            if low_vol and c.iloc[i] > ema.iloc[i]:
                entries[i] = True
                in_pos = True
        else:
            # 高波动（恐慌） → 出场避险
            if high_vol:
                exits[i] = True
                in_pos = False
            # 趋势破位 → 出场
            elif c.iloc[i] < ema.iloc[i] * 0.95:
                exits[i] = True
                in_pos = False

    return entries, exits
