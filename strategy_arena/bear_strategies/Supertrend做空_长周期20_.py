"""
Supertrend做空趋势策略
做空趋势策略：当Supertrend翻红时做空，翻绿时平仓。
在熊市趋势中捕捉下跌波段，含ATR止损保护。
注意：当前版本仅生成多头信号（做空需引擎支持），标记为做空逻辑。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Supertrend做空趋势策略"
STRATEGY_TYPE = "做空趋势"
STRATEGY_PARAMS = {'atr_period': 20, 'atr_mult': 3.0}


def generate_signals(close, high, low, open_prices, **kwargs):
    atr_period = kwargs.get('atr_period', 10)
    atr_mult = kwargs.get('atr_mult', 3.0)

    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    # 计算Supertrend
    atr = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=atr_period), dtype=float)
    hl2 = (h + l) / 2

    # 上轨和下轨
    upper_band = hl2 + atr_mult * atr
    lower_band = hl2 - atr_mult * atr

    # Supertrend方向（True=上升趋势，False=下降趋势）
    supertrend = pd.Series(True, index=c.index)
    final_upper = upper_band.copy()
    final_lower = lower_band.copy()

    for i in range(1, n):
        # 下轨只上不下
        if final_lower.iloc[i] < final_lower.iloc[i - 1] or c.iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = final_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        # 上轨只下不上
        if final_upper.iloc[i] > final_upper.iloc[i - 1] or c.iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = final_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        # 判断方向
        if supertrend.iloc[i - 1]:
            if c.iloc[i] < final_lower.iloc[i]:
                supertrend.iloc[i] = False
            else:
                supertrend.iloc[i] = True
        else:
            if c.iloc[i] > final_upper.iloc[i]:
                supertrend.iloc[i] = True
            else:
                supertrend.iloc[i] = False

    # 在熊市中：Supertrend翻绿(上升趋势)时做多（避险），翻红(下降趋势)时空仓
    # 由于引擎限制做空，这里在下降趋势时空仓，上升趋势时持仓
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(1, n):
        if not in_pos and supertrend.iloc[i] and not supertrend.iloc[i - 1]:
            # 趋势转升 → 暂时做多（熊市中的反弹）
            entries[i] = True
            in_pos = True
        elif in_pos and not supertrend.iloc[i] and supertrend.iloc[i - 1]:
            # 趋势转降 → 空仓
            exits[i] = True
            in_pos = False

    return entries, exits
