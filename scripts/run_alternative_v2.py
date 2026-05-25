#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
牛市策略替代方案回测 — 优化版
=============================
修复持仓比例计算 + 增加Donchian和Supertrend的参数优化
增加底仓组合模式
"""

import pandas as pd
import numpy as np
import talib
import vectorbt as vbt
import warnings
warnings.filterwarnings('ignore')

INIT_CASH = 100000
FEES = 0.001
SLIPPAGE = 0.001

# ================================================================
# 策略实现
# ================================================================

def supertrend_strategy(close, high, low, atr_period=10, multiplier=3.0):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=atr_period)
    hl2 = (h.values + l.values) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    st_dir = np.zeros(n)
    for i in range(1, n):
        if np.isnan(atr[i]):
            st_dir[i] = st_dir[i-1] if i > 0 else 1
            continue
        lb = lower_band[i] if (lower_band[i] > lower_band[i-1] or c.iloc[i-1] < lower_band[i-1]) else lower_band[i-1]
        ub = upper_band[i] if (upper_band[i] < upper_band[i-1] or c.iloc[i-1] > upper_band[i-1]) else upper_band[i-1]
        if st_dir[i-1] == 1:
            st_dir[i] = -1 if c.iloc[i] < lb else 1
        else:
            st_dir[i] = 1 if c.iloc[i] > ub else -1

    in_pos = pd.Series(st_dir == 1)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

def dual_momentum_strategy(close, high, low, lookback=252):
    c = pd.Series(close, dtype=float)
    n = len(c)
    abs_mom = np.zeros(n, dtype=bool)
    for i in range(lookback, n):
        abs_mom[i] = c.iloc[i] > c.iloc[i - lookback]
    rel_mom = np.zeros(n, dtype=bool)
    for i in range(21, n):
        rel_mom[i] = c.iloc[i] > c.iloc[i - 21]
    in_pos_arr = abs_mom & rel_mom
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    current = False
    for i in range(n):
        if not current and in_pos_arr[i]:
            entries[i] = True; current = True
        elif current and not in_pos_arr[i]:
            exits[i] = True; current = False
    return entries, exits

def donchian_breakout_strategy(close, high, low, entry_window=20, exit_window=10):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)
    raw_entries = np.zeros(n, dtype=bool)
    raw_exits = np.zeros(n, dtype=bool)
    for i in range(max(entry_window, exit_window), n):
        upper = h.iloc[i-entry_window:i].max()
        lower = l.iloc[i-exit_window:i].min()
        if c.iloc[i] > upper: raw_entries[i] = True
        if c.iloc[i] < lower: raw_exits[i] = True
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    in_pos = False
    for i in range(n):
        if not in_pos and raw_entries[i]:
            entries[i] = True; in_pos = True
        elif in_pos and raw_exits[i]:
            exits[i] = True; in_pos = False
    return entries, exits

def rsi_pullback_strategy(close, high, low, rsi_period=14, ema_period=50, rsi_threshold=40):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)
    rsi = talib.RSI(c.values, timeperiod=rsi_period)
    ema = talib.EMA(c.values, timeperiod=ema_period)
    trend_up = np.array([c.iloc[i] > ema[i] if not np.isnan(ema[i]) else False for i in range(n)])
    rsi_rising = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(rsi[i]) and not np.isnan(rsi[i-1]):
            rsi_rising[i] = rsi[i] > rsi[i-1] and rsi[i-1] < rsi_threshold
    rsi_overbought = np.array([rsi[i] > 70 if not np.isnan(rsi[i]) else False for i in range(n)])
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    current = False
    for i in range(n):
        if not current:
            if trend_up[i] and rsi_rising[i]:
                entries[i] = True; current = True
        else:
            if rsi_overbought[i] or not trend_up[i]:
                exits[i] = True; current = False
    return entries, exits

def macd_supertrend_strategy(close, high, low, atr_period=10, st_mult=3.0):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)
    macd, macd_signal, macd_hist = talib.MACD(c.values, fastperiod=12, slowperiod=26, signalperiod=9)
    macd_bullish = macd_hist > 0
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=atr_period)
    hl2 = (h.values + l.values) / 2
    upper_band = hl2 + st_mult * atr
    lower_band = hl2 - st_mult * atr
    st_dir = np.zeros(n)
    for i in range(1, n):
        if np.isnan(atr[i]):
            st_dir[i] = st_dir[i-1] if i > 0 else 1
            continue
        lb = lower_band[i] if (lower_band[i] > lower_band[i-1] or c.iloc[i-1] < lower_band[i-1]) else lower_band[i-1]
        ub = upper_band[i] if (upper_band[i] < upper_band[i-1] or c.iloc[i-1] > upper_band[i-1]) else upper_band[i-1]
        if st_dir[i-1] == 1:
            st_dir[i] = -1 if c.iloc[i] < lb else 1
        else:
            st_dir[i] = 1 if c.iloc[i] > ub else -1
    st_bullish = st_dir == 1
    in_pos = st_bullish & macd_bullish
    entries = (in_pos & ~pd.Series(in_pos).shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & pd.Series(in_pos).shift(1).fillna(False)).fillna(False).values
    return entries, exits

def current_ema_adx(close, high, low):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    in_pos = (ema10 > ema20) & (adx_s > 20)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

def current_ema_atr_exit(close, high, low, atr_mult=3.5):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=20)
    atr_s = pd.Series(atr)
    n = len(c)
    entries = np.full(n, False)
    exits = np.full(n, False)
    in_position = False
    highest = 0.0
    stop = 0.0
    for i in range(n):
        if not in_position:
            if ema10.iloc[i] > ema20.iloc[i] and adx_s.iloc[i] > 20:
                entries[i] = True; in_position = True
                highest = h.iloc[i]
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0
        else:
            if h.iloc[i] > highest:
                highest = h.iloc[i]
                new_stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop
                stop = max(stop, new_stop)
            if c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True; in_position = False
                highest = 0.0; stop = 0.0
    return entries, exits

# ================================================================
# Donchian+趋势过滤版（改良版）
# ================================================================
def donchian_with_trend_filter(close, high, low, entry_window=20, exit_window=10, sma_period=100):
    """Donchian突破 + SMA100趋势过滤"""
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)
    sma = talib.SMA(c.values, timeperiod=sma_period)
    trend_up = np.array([c.iloc[i] > sma[i] if not np.isnan(sma[i]) else False for i in range(n)])

    raw_entries = np.zeros(n, dtype=bool)
    raw_exits = np.zeros(n, dtype=bool)
    for i in range(max(entry_window, exit_window), n):
        upper = h.iloc[i-entry_window:i].max()
        lower = l.iloc[i-exit_window:i].min()
        if c.iloc[i] > upper and trend_up[i]: raw_entries[i] = True
        if c.iloc[i] < lower: raw_exits[i] = True

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    in_pos = False
    for i in range(n):
        if not in_pos and raw_entries[i]:
            entries[i] = True; in_pos = True
        elif in_pos and raw_exits[i]:
            exits[i] = True; in_pos = False
    return entries, exits

# ================================================================
# Supertrend宽松版（更低倍数，更高持仓）
# ================================================================
def supertrend_loose(close, high, low, atr_period=10, multiplier=2.0):
    """宽松Supertrend(2x倍数) — 更高持仓比例"""
    return supertrend_strategy(close, high, low, atr_period=atr_period, multiplier=multiplier)

# ================================================================
# 回测引擎
# ================================================================
def run_backtest(close, high, low, open_prices, strategy_func, strategy_name):
    n = len(close)
    entries, exits = strategy_func(close, high, low)

    if entries.sum() == 0:
        return {'策略': strategy_name, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0, '夏普': 0, '最大连续止损': 0, '持仓比例%': 0}

    # 计算持仓比例（基于原始信号）
    in_pos_raw = np.zeros(n, dtype=bool)
    cur = False
    for i in range(n):
        if entries[i]: cur = True
        elif exits[i]: cur = False
        in_pos_raw[i] = cur
    pos_pct = in_pos_raw.sum() / n * 100

    # T+1修正
    entries = np.roll(entries, 1); entries[0] = False
    exits = np.roll(exits, 1); exits[0] = False

    if entries.sum() == 0:
        return {'策略': strategy_name, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0, '夏普': 0, '最大连续止损': 0, '持仓比例%': round(pos_pct, 1)}

    pf = vbt.Portfolio.from_signals(
        open=open_prices, close=close,
        entries=entries, exits=exits,
        freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
        upon_opposite_entry='reverse'
    )

    stats = pf.stats()
    total_return = float(stats['Total Return [%]'])
    max_dd = float(stats['Max Drawdown [%]'])
    win_rate = float(stats['Win Rate [%]'])
    total_trades = int(stats['Total Trades'])
    n_years = len(pf.returns()) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else -100

    try:
        sharpe = float(stats['Sharpe Ratio'])
    except:
        rets = pf.returns().dropna()
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if len(rets) > 1 and rets.std() > 0 else 0

    max_consec_loss = 0
    profit_factor = 0
    try:
        ct = pf.trades.records_readable
        if len(ct) > 0:
            wins = ct[ct['PnL'] > 0]['PnL']
            losses = ct[ct['PnL'] < 0]['PnL']
            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
            is_loss = (ct['PnL'] < 0).values
            consec = 0; max_c = 0
            for v in is_loss:
                if v: consec += 1; max_c = max(max_c, consec)
                else: consec = 0
            max_consec_loss = max_c
    except: pass

    return {
        '策略': strategy_name,
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '胜率%': round(win_rate, 1),
        '盈亏比': round(profit_factor, 2),
        '交易次数': total_trades,
        '夏普': round(sharpe, 2),
        '最大连续止损': max_consec_loss,
        '持仓比例%': round(pos_pct, 1),
    }


# ================================================================
# 底仓组合模式
# ================================================================
def run_base_combined(close, open_prices, entries, exits, base_pct=0.50):
    """底仓+策略组合"""
    n = len(close)
    # T+1修正
    entries_s = np.roll(entries, 1); entries_s[0] = False
    exits_s = np.roll(exits, 1); exits_s[0] = False

    bh_returns = np.zeros(n)
    for i in range(1, n):
        bh_returns[i] = (close[i] - close[i-1]) / close[i-1]

    in_pos = np.full(n, False)
    cur = False
    for i in range(n):
        if entries_s[i]: cur = True
        elif exits_s[i]: cur = False
        in_pos[i] = cur

    strat_returns = np.zeros(n)
    for i in range(1, n):
        if in_pos[i-1]:
            daily_ret = (close[i] - close[i-1]) / close[i-1]
            fee_adj = 0.0
            if entries_s[i-1]: fee_adj = FEES
            if exits_s[i]: fee_adj += FEES
            strat_returns[i] = daily_ret - fee_adj

    combined_returns = base_pct * bh_returns + (1 - base_pct) * strat_returns
    combined_value = np.cumprod(1 + combined_returns) * INIT_CASH

    n_years = len(combined_returns) / 252
    total_ret = (combined_value[-1] / INIT_CASH - 1) * 100
    annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    peak = np.maximum.accumulate(combined_value)
    dd = (combined_value - peak) / peak * 100
    max_dd = abs(dd.min())

    rets_clean = combined_returns[combined_returns != 0]
    sharpe = rets_clean.mean() / rets_clean.std() * np.sqrt(252) if len(rets_clean) > 1 and rets_clean.std() > 0 else 0

    return round(annual, 2), round(max_dd, 2), round(sharpe, 2)


# ================================================================
# 主程序
# ================================================================
if __name__ == '__main__':
    print("=" * 110)
    print("  🔄 牛市策略替代方案回测 — 优化版（修复持仓比例 + 参数优化 + 底仓模式）")
    print("  修正版: T+1信号 + 次日开盘价成交")
    print("=" * 110)

    spy_df = pd.read_csv('/data/workspace/spy_daily.csv',
                         parse_dates=['date'], index_col='date').sort_index()
    hsi_df = pd.read_csv('/data/workspace/hsi_daily.csv',
                         parse_dates=['date'], index_col='date').sort_index()

    def classify_regime_monthly(df):
        close = df['close'].values.astype(float)
        sma50 = talib.SMA(close, timeperiod=50)
        sma200 = talib.SMA(close, timeperiod=200)
        df2 = df.copy()
        df2['sma50'] = sma50; df2['sma200'] = sma200
        df2['month'] = df2.index.to_period('M')
        regimes = {}
        for month, group in df2.groupby('month'):
            if len(group) < 5: continue
            mc = group['close'].iloc[-1]
            mo = group['close'].iloc[0]
            mr = (mc - mo) / mo
            l50 = group['sma50'].iloc[-1]
            l200 = group['sma200'].iloc[-1]
            if pd.isna(l200):
                regime = 'bull' if mr > 0.02 else ('bear' if mr < -0.02 else 'sideways')
            else:
                if mc > l200 and l50 > l200: regime = 'bull'
                elif mc < l200 and l50 < l200: regime = 'bear'
                else: regime = 'sideways'
            regimes[str(month)] = regime
        return regimes

    # 策略列表（包含参数变体）
    strategies = [
        ('① Supertrend(10,3x)', supertrend_strategy),
        ('①b Supertrend(10,2x)', supertrend_loose),
        ('② Dual Momentum(12M)', dual_momentum_strategy),
        ('③ Donchian(20/10)', donchian_breakout_strategy),
        ('③b Donchian+SMA100', donchian_with_trend_filter),
        ('④ RSI Pullback(14,50)', rsi_pullback_strategy),
        ('⑤ MACD+Supertrend', macd_supertrend_strategy),
        ('⑥ 当前:EMA+ADX', current_ema_adx),
        ('⑦ 当前:EMA+ATR止损', current_ema_atr_exit),
    ]

    for market_name, df in [("SPY (美股)", spy_df), ("HSI (港股)", hsi_df)]:
        regimes = classify_regime_monthly(df)
        close_all = df['close'].values.astype(float)
        high_all = df['high'].values.astype(float)
        low_all = df['low'].values.astype(float)
        open_all = df['open'].values.astype(float)
        dates = df.index

        months_series = pd.Series(dates).dt.to_period('M')
        regime_mask = months_series.map(lambda m: regimes.get(str(m), 'sideways')).values
        bull_idx = np.where(regime_mask == 'bull')[0]
        bull_months = sum(1 for v in regimes.values() if v == 'bull')
        total_months = len(regimes)

        print(f"\n{'━' * 110}")
        print(f"  📊 {market_name} — 仅牛市环境 ({bull_months}/{total_months}月 = {bull_months/total_months*100:.0f}%)")
        print(f"  牛市交易日: {len(bull_idx)}天 (~{len(bull_idx)/252:.1f}年)")
        print(f"{'━' * 110}")

        if len(bull_idx) < 50:
            print("  ⚠️ 牛市数据不足，跳过")
            continue

        bull_close = close_all[bull_idx]
        bull_high = high_all[bull_idx]
        bull_low = low_all[bull_idx]
        bull_open = open_all[bull_idx]

        results = []
        for strat_name, strat_func in strategies:
            r = run_backtest(bull_close, bull_high, bull_low, bull_open, strat_func, strat_name)
            results.append(r)

        # B&H
        n_b = len(bull_close)
        e_bh = np.full(n_b, False); e_bh[0] = True
        x_bh = np.full(n_b, False)
        pf_bh = vbt.Portfolio.from_signals(
            open=bull_open, close=bull_close,
            entries=e_bh, exits=x_bh,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
            upon_opposite_entry='reverse'
        )
        stats_bh = pf_bh.stats()
        ny = len(pf_bh.returns()) / 252
        tr = float(stats_bh['Total Return [%]'])
        ar = ((1 + tr / 100) ** (1 / ny) - 1) * 100 if ny > 0 else 0
        try: sh = float(stats_bh['Sharpe Ratio'])
        except: sh = 0
        results.append({
            '策略': '⑧ Buy & Hold',
            '年化收益%': round(ar, 2),
            '最大回撤%': round(float(stats_bh['Max Drawdown [%]']), 2),
            '胜率%': '-',
            '盈亏比': '-',
            '交易次数': 1,
            '夏普': round(sh, 2),
            '最大连续止损': '-',
            '持仓比例%': 100.0,
        })

        hdr = "┌" + "─"*26 + "┬" + "─"*10 + "┬" + "─"*10 + "┬" + "─"*8 + "┬" + "─"*8 + "┬" + "─"*6 + "┬" + "─"*6 + "┬" + "─"*12 + "┬" + "─"*10 + "┐"
        sep = "├" + "─"*26 + "┼" + "─"*10 + "┼" + "─"*10 + "┼" + "─"*8 + "┼" + "─"*8 + "┼" + "─"*6 + "┼" + "─"*6 + "┼" + "─"*12 + "┼" + "─"*10 + "┤"
        ftr = "└" + "─"*26 + "┴" + "─"*10 + "┴" + "─"*10 + "┴" + "─"*8 + "┴" + "─"*8 + "┴" + "─"*6 + "┴" + "─"*6 + "┴" + "─"*12 + "┴" + "─"*10 + "┘"
        fmt = "│{:<26}│{:>10}│{:>10}│{:>8}│{:>8}│{:>6}│{:>6}│{:>12}│{:>10}│"

        print(hdr)
        print(fmt.format('策略', '年化收益%', '最大回撤%', '胜率%', '盈亏比', '交易数', '夏普', '最大连续止损', '持仓比例%'))
        print(sep)
        for r in results:
            print(fmt.format(
                r['策略'],
                str(r['年化收益%']) + '%',
                str(r['最大回撤%']) + '%',
                str(r['胜率%']) + '%' if isinstance(r['胜率%'], (int, float)) else str(r['胜率%']),
                str(r['盈亏比']),
                r['交易次数'],
                r['夏普'],
                str(r['最大连续止损']),
                str(r['持仓比例%']) + '%'
            ))
        print(ftr)

        # ── 底仓组合模式 ──
        print(f"\n  📊 {market_name} — 底仓50%组合模式")
        for strat_name, strat_func in strategies:
            entries, exits = strat_func(bull_close, bull_high, bull_low)
            annual, max_dd, sharpe = run_base_combined(bull_close, bull_open, entries, exits, base_pct=0.50)
            print(f"    {strat_name:26s} → 年化{annual:7.2f}% / 回撤{max_dd:7.2f}% / 夏普{sharpe:5.2f}")

    print(f"\n{'━' * 110}")
    print("  ✅ 替代方案回测完成！")
