"""
高股息低波防御策略
高股息防御策略：选择低波动率+高股息标的持有，配合趋势过滤止损。
熊市中防御第一，利用股息收入缓冲下跌。
注意：此策略使用价格波动率作为低波代理指标，实际应使用股息率数据。
"""
import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "高股息低波防御策略"
STRATEGY_TYPE = "高股息防御"
STRATEGY_PARAMS = {'vol_lookback': 60, 'ema_period': 50, 'atr_period': 14, 'atr_mult': 2.0}


def generate_signals(close, high, low, open_prices, **kwargs):
    vol_lookback = kwargs.get('vol_lookback', 60)
    ema_period = kwargs.get('ema_period', 100)
    atr_period = kwargs.get('atr_period', 14)
    atr_mult = kwargs.get('atr_mult', 3.0)

    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    # 长期EMA趋势
    ema = c.ewm(span=ema_period, adjust=False).mean()

    # ATR止损
    atr = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=atr_period), dtype=float)

    # ATR止损线
    stop_loss = c.copy()
    stop_loss.iloc[0] = c.iloc[0] - atr.iloc[0] * atr_mult
    for i in range(1, n):
        new_stop = c.iloc[i] - atr.iloc[i] * atr_mult
        stop_loss.iloc[i] = max(stop_loss.iloc[i - 1], new_stop)

    # 历史波动率
    returns = c.pct_change()
    hist_vol = returns.rolling(vol_lookback).std() * np.sqrt(252)

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    in_pos = False
    for i in range(max(ema_period, vol_lookback), n):
        if pd.isna(hist_vol.iloc[i]) or pd.isna(ema.iloc[i]):
            continue

        # 低波动率条件（波动率低于自身中位数时认为低波）
        vol_median = hist_vol.iloc[max(0, i - vol_lookback):i].median()
        is_low_vol = hist_vol.iloc[i] < vol_median if not pd.isna(vol_median) else True

        if not in_pos:
            # 价格在长期EMA上方 + 低波动 → 入场
            if c.iloc[i] > ema.iloc[i] and is_low_vol:
                entries[i] = True
                in_pos = True
        else:
            # 跌破ATR止损线 → 出场
            if c.iloc[i] < stop_loss.iloc[i]:
                exits[i] = True
                in_pos = False

    return entries, exits
