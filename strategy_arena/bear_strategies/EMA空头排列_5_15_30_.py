"""
EMA空头排列做空策略
做空趋势策略：当EMA10/20/50形成空头排列（EMA10<EMA20<EMA50）时做空，
均线多头排列时平仓。经典趋势反转做空策略。
注意：当前版本在空头排列时空仓，多头排列时持仓（等待趋势确认）。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "EMA空头排列做空策略"
STRATEGY_TYPE = "做空趋势"
STRATEGY_PARAMS = {'ema_fast': 5, 'ema_mid': 15, 'ema_slow': 30, 'atr_period': 14, 'atr_mult': 2.5}


def generate_signals(close, high, low, open_prices, **kwargs):
    ema_fast = kwargs.get('ema_fast', 10)
    ema_mid = kwargs.get('ema_mid', 20)
    ema_slow = kwargs.get('ema_slow', 50)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.5)

    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    # 三层EMA
    ema10 = c.ewm(span=ema_fast, adjust=False).mean()
    ema20 = c.ewm(span=ema_mid, adjust=False).mean()
    ema50 = c.ewm(span=ema_slow, adjust=False).mean()

    # ATR止损
    atr = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=atr_period), dtype=float)

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(ema_slow, n):
        if pd.isna(ema50.iloc[i]) or pd.isna(atr.iloc[i]):
            continue

        # 多头排列：EMA10 > EMA20 > EMA50
        bullish = (ema10.iloc[i] > ema20.iloc[i]) and (ema20.iloc[i] > ema50.iloc[i])
        # 空头排列：EMA10 < EMA20 < EMA50
        bearish = (ema10.iloc[i] < ema20.iloc[i]) and (ema20.iloc[i] < ema50.iloc[i])

        if not in_pos and bullish:
            entries[i] = True
            in_pos = True
        elif in_pos:
            # 空头排列形成 → 出场
            if bearish:
                exits[i] = True
                in_pos = False
            # ATR止损
            elif c.iloc[i] < c.iloc[i - 1] - atr.iloc[i] * atr_mult:
                exits[i] = True
                in_pos = False

    return entries, exits
