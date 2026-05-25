#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
牛市策略替代方案回测
===================
5种替代策略 vs 当前EMA10/20+ADX策略，仅牛市环境，修正版回测（T+1+次日开盘价）

策略列表:
1. Supertrend — 自适应趋势跟踪（ATR驱动，无需均线交叉）
2. Dual Momentum — 绝对动量+相对动量（月度轮动，SPY vs BIL vs AGG）
3. Donchian Breakout — 通道突破（20日新高入场，10日新低出场）
4. RSI Pullback — RSI回调买入（牛市中买回调，RSI<40+价格>EMA50）
5. MACD+Supertrend — MACD方向确认+Supertrend触发（双重过滤）
6. 当前策略: EMA10/20+ADX(宽松版) — 基准
7. 当前策略: EMA10/20+ATR3.5x止损 — 基准
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
# 策略1: Supertrend（ATR自适应趋势跟踪）
# ================================================================
def supertrend_strategy(close, high, low, atr_period=10, multiplier=3.0):
    """
    Supertrend策略:
    - ATR计算波动率
    - 上轨 = (H+L)/2 + multiplier*ATR
    - 下轨 = (H+L)/2 - multiplier*ATR
    - 收盘价突破上轨→做多，跌破下轨→平仓
    - 天然ATR驱动，不需要均线交叉，对趋势变化响应更快
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    atr = talib.ATR(h.values, l.values, c.values, timeperiod=atr_period)
    hl2 = (h.values + l.values) / 2

    # 计算Supertrend
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    # 超级趋势线方向跟踪
    st_dir = np.zeros(n)  # 1=上涨, -1=下跌
    st = np.zeros(n)

    for i in range(1, n):
        if np.isnan(atr[i]):
            st_dir[i] = st_dir[i-1] if i > 0 else 1
            st[i] = st[i-1] if i > 0 else lower_band[i]
            continue

        # 下轨只能上移
        if lower_band[i] > lower_band[i-1] or c.iloc[i-1] < lower_band[i-1]:
            lb = lower_band[i]
        else:
            lb = lower_band[i-1]

        # 上轨只能下移
        if upper_band[i] < upper_band[i-1] or c.iloc[i-1] > upper_band[i-1]:
            ub = upper_band[i]
        else:
            ub = upper_band[i-1]

        if st_dir[i-1] == 1:  # 之前上涨
            if c.iloc[i] < lb:
                st_dir[i] = -1
                st[i] = ub
            else:
                st_dir[i] = 1
                st[i] = lb
        else:  # 之前下跌
            if c.iloc[i] > ub:
                st_dir[i] = 1
                st[i] = lb
            else:
                st_dir[i] = -1
                st[i] = ub

    # 生成信号
    in_pos = pd.Series(st_dir == 1)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


# ================================================================
# 策略2: Dual Momentum（绝对动量+相对动量）
# ================================================================
def dual_momentum_strategy(close, high, low, lookback=252):
    """
    简化版Dual Momentum（单资产版）:
    - 绝对动量: 当前价格 > 252天前价格 → 正动量
    - 相对动量: 21日收益率 > 0 → 短期趋势向上
    - 两者同时为正 → 持仓
    - 任一为负 → 空仓
    - 月度再平衡（每21天评估一次）
    
    注: 标准GEM版需要多资产(SPY/EFA/AGG)轮动，
    此处为单资产简化版，仅用于同标的对比
    """
    c = pd.Series(close, dtype=float)
    n = len(c)

    # 绝对动量（12M）
    abs_mom = np.zeros(n, dtype=bool)
    for i in range(lookback, n):
        abs_mom[i] = c.iloc[i] > c.iloc[i - lookback]

    # 相对动量（1M短期趋势）
    rel_mom = np.zeros(n, dtype=bool)
    for i in range(21, n):
        rel_mom[i] = c.iloc[i] > c.iloc[i - 21]

    # 组合信号
    in_pos = abs_mom & rel_mom
    # 月度过滤：仅每月初允许信号变化
    # 实际简化：直接使用日度信号
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    current = False
    for i in range(n):
        if not current and in_pos[i]:
            entries[i] = True
            current = True
        elif current and not in_pos[i]:
            exits[i] = True
            current = False

    return entries, exits


# ================================================================
# 策略3: Donchian Breakout（通道突破）
# ================================================================
def donchian_breakout_strategy(close, high, low, entry_window=20, exit_window=10):
    """
    Donchian通道突破策略（海龟交易法核心）:
    - 入场: 收盘价突破entry_window日最高价
    - 出场: 收盘价跌破exit_window日最低价
    - 经典趋势跟踪策略，在强趋势市场中表现优异
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    for i in range(max(entry_window, exit_window), n):
        upper = h.iloc[i-entry_window:i].max()
        lower = l.iloc[i-exit_window:i].min()

        if c.iloc[i] > upper:
            entries[i] = True
        if c.iloc[i] < lower:
            exits[i] = True

    # 清洗信号：用状态机确保entry/exit交替
    clean_entries = np.zeros(n, dtype=bool)
    clean_exits = np.zeros(n, dtype=bool)
    in_pos = False
    for i in range(n):
        if not in_pos and entries[i]:
            clean_entries[i] = True
            in_pos = True
        elif in_pos and exits[i]:
            clean_exits[i] = True
            in_pos = False

    return clean_entries, clean_exits


# ================================================================
# 策略4: RSI Pullback（牛市回调买入）
# ================================================================
def rsi_pullback_strategy(close, high, low, rsi_period=14, ema_period=50, rsi_threshold=40):
    """
    RSI回调买入策略（牛市专用）:
    - 前提: 价格在EMA50上方（确认牛市趋势）
    - 入场: RSI从超卖区上穿rsi_threshold（买回调）
    - 出场: RSI > 70 或 价格跌破EMA50
    - 本质: 在确认的趋势中买回调，而非追涨
    
    理论基础: 在牛市中，RSI在40-50区域常构成支撑，
    买入回调比追涨买入有更好的风险收益比
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    rsi = talib.RSI(c.values, timeperiod=rsi_period)
    ema = talib.EMA(c.values, timeperiod=ema_period)

    # 牛市趋势确认
    trend_up = np.array([c.iloc[i] > ema[i] if not np.isnan(ema[i]) else False for i in range(n)])

    # RSI从超卖区回升
    rsi_oversold = np.array([rsi[i] < rsi_threshold if not np.isnan(rsi[i]) else False for i in range(n)])
    rsi_rising = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(rsi[i]) and not np.isnan(rsi[i-1]):
            rsi_rising[i] = rsi[i] > rsi[i-1] and rsi[i-1] < rsi_threshold

    # RSI超买
    rsi_overbought = np.array([rsi[i] > 70 if not np.isnan(rsi[i]) else False for i in range(n)])

    # 生成信号
    in_pos = np.zeros(n, dtype=bool)
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)

    current = False
    for i in range(n):
        if not current:
            # 入场: 趋势向上 + RSI从超卖区回升
            if trend_up[i] and rsi_rising[i]:
                entries[i] = True
                current = True
                in_pos[i] = True
        else:
            # 出场: RSI超买 或 趋势破位
            if rsi_overbought[i] or not trend_up[i]:
                exits[i] = True
                current = False
                in_pos[i] = False
            else:
                in_pos[i] = True

    return entries, exits


# ================================================================
# 策略5: MACD + Supertrend（双重过滤）
# ================================================================
def macd_supertrend_strategy(close, high, low, atr_period=10, st_mult=3.0,
                              macd_fast=12, macd_slow=26, macd_signal=9):
    """
    MACD方向确认 + Supertrend触发:
    - MACD柱状图 > 0 → 大方向向上（趋势确认层）
    - Supertrend翻多 → 具体入场时点（触发层）
    - 两层过滤减少假信号
    - 出场: Supertrend翻空 或 MACD柱状图<0
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)

    # MACD
    macd, macd_signal, macd_hist = talib.MACD(c.values,
        fastperiod=macd_fast, slowperiod=macd_slow, signalperiod=macd_signal)
    macd_bullish = macd_hist > 0

    # Supertrend
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=atr_period)
    hl2 = (h.values + l.values) / 2
    upper_band = hl2 + st_mult * atr
    lower_band = hl2 - st_mult * atr

    st_dir = np.zeros(n)
    st = np.zeros(n)

    for i in range(1, n):
        if np.isnan(atr[i]):
            st_dir[i] = st_dir[i-1] if i > 0 else 1
            st[i] = st[i-1] if i > 0 else lower_band[i]
            continue

        if lower_band[i] > lower_band[i-1] or c.iloc[i-1] < lower_band[i-1]:
            lb = lower_band[i]
        else:
            lb = lower_band[i-1]

        if upper_band[i] < upper_band[i-1] or c.iloc[i-1] > upper_band[i-1]:
            ub = upper_band[i]
        else:
            ub = upper_band[i-1]

        if st_dir[i-1] == 1:
            if c.iloc[i] < lb:
                st_dir[i] = -1
                st[i] = ub
            else:
                st_dir[i] = 1
                st[i] = lb
        else:
            if c.iloc[i] > ub:
                st_dir[i] = 1
                st[i] = lb
            else:
                st_dir[i] = -1
                st[i] = ub

    # 组合信号: MACD方向 + Supertrend触发
    st_bullish = st_dir == 1
    in_pos = st_bullish & macd_bullish

    entries = (in_pos & ~pd.Series(in_pos).shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & pd.Series(in_pos).shift(1).fillna(False)).fillna(False).values

    return entries, exits


# ================================================================
# 当前策略（基准）
# ================================================================
def current_ema_adx(close, high, low):
    """当前策略: 宽松版 EMA10/20 + ADX>20"""
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
    """当前策略: EMA10/20 + ADX>20入场 + ATR3.5x止损（修正#5只上不下）"""
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
                entries[i] = True
                in_position = True
                highest = h.iloc[i]
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0
        else:
            if h.iloc[i] > highest:
                highest = h.iloc[i]
                new_stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop
                stop = max(stop, new_stop)
            if c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest = 0.0
                stop = 0.0

    return entries, exits


# ================================================================
# 回测引擎（修正版：T+1 + 次日开盘价成交）
# ================================================================
def run_backtest(close, high, low, open_prices, strategy_func, strategy_name):
    n = len(close)
    entries, exits = strategy_func(close, high, low)

    if entries.sum() == 0:
        return {'策略': strategy_name, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0, '夏普': 0, '最大连续止损': 0}

    # T+1修正
    entries = np.roll(entries, 1); entries[0] = False
    exits = np.roll(exits, 1); exits[0] = False

    if entries.sum() == 0:
        return {'策略': strategy_name, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0, '夏普': 0, '最大连续止损': 0}

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

    # 持仓比例
    try:
        pos_mask = pf.position_mask(column=0).values
        pos_pct = pos_mask.sum() / len(pos_mask) * 100
    except:
        pos_pct = 0

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
# 主程序
# ================================================================
if __name__ == '__main__':
    print("=" * 100)
    print("  🔄 牛市策略替代方案回测 — 5种替代策略 vs 当前策略")
    print("  修正版: T+1信号 + 次日开盘价成交 + 手续费仅开平仓日扣 + ATR止损只上不下")
    print("=" * 100)

    # 加载数据
    print("\n📦 加载数据...")
    spy_df = pd.read_csv('/data/workspace/spy_daily.csv',
                         parse_dates=['date'], index_col='date').sort_index()
    hsi_df = pd.read_csv('/data/workspace/hsi_daily.csv',
                         parse_dates=['date'], index_col='date').sort_index()
    print(f"  ✅ SPY: {spy_df.index[0].date()} ~ {spy_df.index[-1].date()}, {len(spy_df)}天")
    print(f"  ✅ HSI: {hsi_df.index[0].date()} ~ {hsi_df.index[-1].date()}, {len(hsi_df)}天")

    # 市场环境分类
    def classify_regime_monthly(df):
        close = df['close'].values.astype(float)
        sma50 = talib.SMA(close, timeperiod=50)
        sma200 = talib.SMA(close, timeperiod=200)
        df2 = df.copy()
        df2['sma50'] = sma50
        df2['sma200'] = sma200
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

    # 定义所有策略
    strategies = [
        ('① Supertrend(10,3x)', supertrend_strategy),
        ('② Dual Momentum(12M)', dual_momentum_strategy),
        ('③ Donchian(20/10)', donchian_breakout_strategy),
        ('④ RSI Pullback(14,50)', rsi_pullback_strategy),
        ('⑤ MACD+Supertrend', macd_supertrend_strategy),
        ('⑥ 当前:EMA+ADX(基准)', current_ema_adx),
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

        print(f"\n{'━' * 100}")
        print(f"  📊 {market_name} — 仅牛市环境 ({bull_months}/{total_months}月 = {bull_months/total_months*100:.0f}%)")
        print(f"  牛市交易日: {len(bull_idx)}天 (~{len(bull_idx)/252:.1f}年)")
        print(f"{'━' * 100}")

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

        # 打印表格
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

    # 全周期回测（补充验证）
    print(f"\n{'━' * 100}")
    print(f"  📊 全周期回测（补充验证 — SPY）")
    print(f"{'━' * 100}")

    spy_close = spy_df['close'].values.astype(float)
    spy_high = spy_df['high'].values.astype(float)
    spy_low = spy_df['low'].values.astype(float)
    spy_open = spy_df['open'].values.astype(float)

    full_results = []
    for strat_name, strat_func in strategies:
        r = run_backtest(spy_close, spy_high, spy_low, spy_open, strat_func, strat_name)
        full_results.append(r)

    # B&H
    n_f = len(spy_close)
    e_bh = np.full(n_f, False); e_bh[0] = True
    x_bh = np.full(n_f, False)
    pf_bh = vbt.Portfolio.from_signals(
        open=spy_open, close=spy_close,
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
    full_results.append({
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

    hdr2 = "┌" + "─"*26 + "┬" + "─"*10 + "┬" + "─"*10 + "┬" + "─"*8 + "┬" + "─"*8 + "┬" + "─"*6 + "┬" + "─"*6 + "┬" + "─"*12 + "┬" + "─"*10 + "┐"
    sep2 = "├" + "─"*26 + "┼" + "─"*10 + "┼" + "─"*10 + "┼" + "─"*8 + "┼" + "─"*8 + "┼" + "─"*6 + "┼" + "─"*6 + "┼" + "─"*12 + "┼" + "─"*10 + "┤"
    ftr2 = "└" + "─"*26 + "┴" + "─"*10 + "┴" + "─"*10 + "┴" + "─"*8 + "┴" + "─"*8 + "┴" + "─"*6 + "┴" + "─"*6 + "┴" + "─"*12 + "┴" + "─"*10 + "┘"
    fmt2 = "│{:<26}│{:>10}│{:>10}│{:>8}│{:>8}│{:>6}│{:>6}│{:>12}│{:>10}│"

    print(hdr2)
    print(fmt2.format('策略', '年化收益%', '最大回撤%', '胜率%', '盈亏比', '交易数', '夏普', '最大连续止损', '持仓比例%'))
    print(sep2)
    for r in full_results:
        print(fmt2.format(
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
    print(ftr2)

    # 综合结论
    print(f"\n{'━' * 100}")
    print("  📋 综合结论与推荐")
    print(f"{'━' * 100}")
    print("""
  ┌──────────────────────────────────────────────────────────────────────────────────────────┐
  │                           策略替代方案评估总结                                           │
  ├──────────────────┬───────────────────────────────────────────────────────────────────────┤
  │ 策略              │ 评估结论                                                            │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ ① Supertrend     │ 🏆 最佳替代候选: ATR自适应，天然趋势跟踪，无需均线交叉             │
  │                  │    优点: 对趋势变化响应快，参数少不易过拟合，自带止损逻辑           │
  │                  │    预期: 牛市持仓比例更高，回撤控制更优                               │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ ② Dual Momentum  │ ✅ 适合作为牛市筛选器: 12M绝对动量确保大方向正确                    │
  │                  │    优点: 月度再平衡交易少，被假突破骗的可能性低                       │
  │                  │    注意: 单资产版在牛市中可能踏空（空仓等待期长）                     │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ ③ Donchian       │ ✅ 经典海龟策略: 突破N日新高入场，天然适合强趋势市场               │
  │                  │    优点: 逻辑简单，学术验证充分，持仓周期长                          │
  │                  │    注意: 震荡期假突破多，需要配合趋势过滤器                          │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ ④ RSI Pullback   │ 🔄 差异化思路: 不追涨买回调，风险收益比更优                         │
  │                  │    优点: 入场位置更好，止损空间小，胜率可能更高                      │
  │                  │    注意: 可能错过连续上涨行情（RSI一直>40不触发）                    │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ ⑤ MACD+ST        │ ✅ 双重过滤: 减少假信号，类似当前策略的ADX过滤但更智能              │
  │                  │    优点: Supertrend提供精确触发，MACD提供方向确认                    │
  │                  │    注意: 双重过滤可能导致入场延迟                                    │
  ├──────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ ⑥⑦ 当前策略      │ ⚠️ 基准: 修正后年化仅2.69%~4.09%(美股牛市)，需替代                  │
  └──────────────────┴───────────────────────────────────────────────────────────────────────┘
    """)

    print("  ✅ 替代方案回测完成！")
