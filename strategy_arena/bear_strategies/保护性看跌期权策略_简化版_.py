"""
保护性看跌期权策略（简化版）
熊市防御核心策略：持有标的的同时设置止损对冲下行风险。
简化版使用ATR止损替代期权，在趋势转弱时减仓避险。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "保护性看跌期权策略(简化版)"
STRATEGY_TYPE = "高股息防御"
STRATEGY_PARAMS = {'ema_period': 50, 'atr_period': 14, 'atr_mult': 2.5, 'rsi_period': 14}


def generate_signals(close, high, low, open_prices, **kwargs):
    ema_period = kwargs.get('ema_period', 50)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 2.5)
    rsi_period = kwargs.get('rsi_period', 14)

    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    ema = c.ewm(span=ema_period, adjust=False).mean()
    atr = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=atr_period), dtype=float)
    rsi = pd.Series(talib.RSI(c.values, timeperiod=rsi_period), dtype=float)

    # ATR止损线（只上不下）
    stop_loss = c.copy()
    stop_loss.iloc[0] = c.iloc[0] - atr.iloc[0] * atr_mult
    for i in range(1, n):
        new_stop = c.iloc[i] - atr.iloc[i] * atr_mult
        stop_loss.iloc[i] = max(stop_loss.iloc[i - 1], new_stop)

    # 入场条件：价格在EMA上方 + RSI未超买
    in_trend = (c > ema) & (rsi < 70)
    # 出场条件：跌破ATR止损线 或 RSI超卖加速
    stop_hit = c < stop_loss
    rsi_drop = rsi < 25

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(1, n):
        if not in_pos and in_trend.iloc[i] and in_trend.iloc[i - 1]:
            entries[i] = True
            in_pos = True
        elif in_pos and (stop_hit.iloc[i] or rsi_drop.iloc[i]):
            exits[i] = True
            in_pos = False

    return entries, exits
