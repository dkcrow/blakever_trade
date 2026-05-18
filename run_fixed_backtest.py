#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正版回测脚本 — 修正 #1(手续费) #5(ATR止损只上不下) #6(未来函数)
输出: 年化、胜率、盈亏比、交易次数、最大回撤、最大连续止损、夏普
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
# 策略函数（已修正）
# ================================================================

def bull_strategy_relaxed(close, high, low):
    """宽松版 (ADX > 20)"""
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

def bull_strategy_us_atr_exit(close, high, low, atr_mult=3.5):
    """美股优化版 — 入场ADX>20 + ATR3.5x止损出场（修正#5: 止损线只上不下）"""
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
                # 修正#5: 止损线只上不下(Chandelier Exit铁律)
                stop = max(stop, new_stop)
            if c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest = 0.0
                stop = 0.0

    return entries, exits

def bull_strategy_hk_no_adx(close, high, low):
    """港股优化版 — 纯EMA10/20(无ADX)"""
    c = pd.Series(close, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    in_pos = ema10 > ema20
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

def ema_cross_strategy(close, high, low):
    """基准: EMA10/20无条件交叉"""
    c = pd.Series(close, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    in_pos = ema10 > ema20
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

# ================================================================
# 底仓模式（修正#1: 手续费仅在开平仓日扣除）
# ================================================================

def apply_base_position_fixed(close, entries, exits, open_prices, base_pct=0.50):
    """修正版底仓模式: 手续费仅在开平仓日扣除，信号次日生效"""
    n = len(close)

    # 信号T+1生效
    entries_shifted = np.roll(entries, 1)
    exits_shifted = np.roll(exits, 1)
    entries_shifted[0] = False
    exits_shifted[0] = False

    # B&H收益
    bh_returns = np.zeros(n)
    for i in range(1, n):
        bh_returns[i] = (close[i] - close[i-1]) / close[i-1]

    # 策略收益
    in_pos = np.full(n, False)
    current = False
    for i in range(n):
        if entries_shifted[i]:
            current = True
        elif exits_shifted[i]:
            current = False
        in_pos[i] = current

    strat_returns = np.zeros(n)
    for i in range(1, n):
        if in_pos[i-1]:
            daily_ret = (close[i] - close[i-1]) / close[i-1]
            # 修正#1: 仅在开仓/平仓日扣除手续费
            fee_adj = 0.0
            if entries_shifted[i-1]:  # 开仓日扣买入手续费
                fee_adj = FEES
            if exits_shifted[i]:  # 平仓日扣卖出手续费
                fee_adj += FEES
            strat_returns[i] = daily_ret - fee_adj

    # 组合收益
    combined_returns = base_pct * bh_returns + (1 - base_pct) * strat_returns
    combined_value = np.cumprod(1 + combined_returns) * INIT_CASH

    return {
        'base_returns': bh_returns,
        'strategy_returns': strat_returns,
        'combined_returns': combined_returns,
        'combined_value': combined_value,
        'base_pct': base_pct,
    }

# ================================================================
# 回测引擎（修正#6: 信号shift(1) + 次日开盘价成交）
# ================================================================

def run_backtest_fixed(close, high, low, open_prices, strategy_func, strategy_name):
    """修正版回测: 信号T+1生效 + 次日开盘价成交"""
    n = len(close)

    entries, exits = strategy_func(close, high, low)

    if entries.sum() == 0:
        return {'策略': strategy_name, '状态': '无交易信号',
                '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0,
                '夏普': 0, '最大连续止损': 0}

    # 修正#6: 信号shift(1)，次日生效
    entries = np.roll(entries, 1)
    exits = np.roll(exits, 1)
    entries[0] = False
    exits[0] = False

    if entries.sum() == 0:
        return {'策略': strategy_name, '状态': '无交易信号(T+1后)',
                '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0,
                '夏普': 0, '最大连续止损': 0}

    # 使用次日开盘价成交
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

    # 年化收益
    n_years = len(pf.returns()) / 252
    if n_years > 0 and total_return > -100:
        annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100
    else:
        annual = -100

    # 夏普比率
    try:
        sharpe = float(stats['Sharpe Ratio'])
    except (KeyError, TypeError):
        rets = pf.returns().dropna()
        if len(rets) > 0 and rets.std() > 0:
            sharpe = rets.mean() / rets.std() * np.sqrt(252)
        else:
            sharpe = 0

    # 盈亏比和最大连续止损
    max_consec_loss = 0
    profit_factor = 0
    try:
        closed_trades = pf.trades.records_readable
        if len(closed_trades) > 0:
            wins = closed_trades[closed_trades['PnL'] > 0]['PnL']
            losses = closed_trades[closed_trades['PnL'] < 0]['PnL']
            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

            # 最大连续止损
            is_loss = (closed_trades['PnL'] < 0).values
            consec = 0
            max_consec = 0
            for v in is_loss:
                if v:
                    consec += 1
                    max_consec = max(max_consec, consec)
                else:
                    consec = 0
            max_consec_loss = max_consec
    except Exception:
        pass

    return {
        '策略': strategy_name,
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '胜率%': round(win_rate, 1),
        '交易次数': total_trades,
        '盈亏比': round(profit_factor, 2),
        '夏普': round(sharpe, 2),
        '最大连续止损': max_consec_loss,
    }

# ================================================================
# 主程序
# ================================================================

if __name__ == '__main__':
    print("=" * 90)
    print("  🔧 修正版回测 — #1手续费 #5ATR止损只上不下 #6未来函数(T+1+次日开盘价)")
    print("=" * 90)

    # 加载数据
    print("\n📦 加载数据...")
    try:
        spy_df = pd.read_csv('/data/workspace/spy_daily.csv',
                             parse_dates=['date'], index_col='date').sort_index()
        hsi_df = pd.read_csv('/data/workspace/hsi_daily.csv',
                             parse_dates=['date'], index_col='date').sort_index()
    except FileNotFoundError:
        import yfinance as yf
        spy_df = yf.download('SPY', start='2007-01-01', end='2025-04-01')
        hsi_df = yf.download('^HSI', start='2007-01-01', end='2025-04-01')
        spy_df.columns = [c.lower() for c in spy_df.columns]
        hsi_df.columns = [c.lower() for c in hsi_df.columns]

    print(f"  ✅ SPY: {spy_df.index[0].date()} ~ {spy_df.index[-1].date()}, {len(spy_df)} 天")
    print(f"  ✅ HSI: {hsi_df.index[0].date()} ~ {hsi_df.index[-1].date()}, {len(hsi_df)} 天")

    # ── 定义策略 ──
    us_strategies = [
        ('宽松版(ADX>20)', bull_strategy_relaxed),
        ('美股最优(ATR3.5x止损)', bull_strategy_us_atr_exit),
        ('EMA10/20基准', ema_cross_strategy),
    ]
    hk_strategies = [
        ('宽松版(ADX>20)', bull_strategy_relaxed),
        ('港股最优(纯EMA10/20)', bull_strategy_hk_no_adx),
        ('EMA10/20基准', ema_cross_strategy),
    ]

    # ── 全周期回测 ──
    for market_name, df, strats in [
        ("SPY (美股)", spy_df, us_strategies),
        ("HSI (港股)", hsi_df, hk_strategies)
    ]:
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        open_p = df['open'].values.astype(float)

        print(f"\n{'━' * 90}")
        print(f"  📊 {market_name} 全周期回测（修正版）")
        print(f"{'━' * 90}")

        results = []
        for strat_name, strat_func in strats:
            r = run_backtest_fixed(close, high, low, open_p, strat_func, strat_name)
            results.append(r)

        # Buy & Hold
        n = len(close)
        entries_bh = np.full(n, False); entries_bh[0] = True
        exits_bh = np.full(n, False)
        pf_bh = vbt.Portfolio.from_signals(
            open=open_p, close=close,
            entries=entries_bh, exits=exits_bh,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
            upon_opposite_entry='reverse'
        )
        stats_bh = pf_bh.stats()
        n_years = len(pf_bh.returns()) / 252
        total_ret_bh = float(stats_bh['Total Return [%]'])
        annual_bh = ((1 + total_ret_bh / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
        try:
            sharpe_bh = float(stats_bh['Sharpe Ratio'])
        except:
            sharpe_bh = 0
        results.append({
            '策略': 'Buy & Hold',
            '状态': '✅',
            '总收益率%': round(total_ret_bh, 2),
            '年化收益%': round(annual_bh, 2),
            '最大回撤%': round(float(stats_bh['Max Drawdown [%]']), 2),
            '胜率%': '-',
            '交易次数': 1,
            '盈亏比': '-',
            '夏普': round(sharpe_bh, 2),
            '最大连续止损': '-',
        })

        # 打印表格
        hdr = "┌" + "─"*24 + "┬" + "─"*10 + "┬" + "─"*10 + "┬" + "─"*8 + "┬" + "─"*8 + "┬" + "─"*6 + "┬" + "─"*6 + "┬" + "─"*12 + "┐"
        sep = "├" + "─"*24 + "┼" + "─"*10 + "┼" + "─"*10 + "┼" + "─"*8 + "┼" + "─"*8 + "┼" + "─"*6 + "┼" + "─"*6 + "┼" + "─"*12 + "┤"
        ftr = "└" + "─"*24 + "┴" + "─"*10 + "┴" + "─"*10 + "┴" + "─"*8 + "┴" + "─"*8 + "┴" + "─"*6 + "┴" + "─"*6 + "┴" + "─"*12 + "┘"
        fmt = "│{:<24}│{:>10}│{:>10}│{:>8}│{:>8}│{:>6}│{:>6}│{:>12}│"

        print(hdr)
        print(fmt.format('策略', '年化收益%', '最大回撤%', '胜率%', '盈亏比', '交易数', '夏普', '最大连续止损'))
        print(sep)
        for r in results:
            print(fmt.format(
                r['策略'],
                str(r['年化收益%']) + '%',
                str(r['最大回撤%']) + '%',
                str(r['胜率%']) + '%' if isinstance(r['胜率%'], (int, float)) else r['胜率%'],
                str(r['盈亏比']),
                r['交易次数'],
                r['夏普'],
                r['最大连续止损']
            ))
        print(ftr)

    # ── 底仓组合模式回测（修正版） ──
    print(f"\n{'━' * 90}")
    print(f"  📊 底仓组合模式回测（修正版 — 手续费仅在开平仓日扣除）")
    print(f"{'━' * 90}")

    for market_name, df, strategy_func in [
        ("SPY (美股)", spy_df, bull_strategy_us_atr_exit),
        ("HSI (港股)", hsi_df, bull_strategy_hk_no_adx),
    ]:
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        open_p = df['open'].values.astype(float)

        entries, exits = strategy_func(close, high, low)

        for base_pct in [0.30, 0.50]:
            result = apply_base_position_fixed(close, entries, exits, open_p, base_pct=base_pct)

            # 计算组合绩效
            rets = result['combined_returns']
            n_years = len(rets) / 252
            total_ret = (result['combined_value'][-1] / INIT_CASH - 1) * 100
            annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

            # 最大回撤
            cumval = result['combined_value']
            peak = np.maximum.accumulate(cumval)
            dd = (cumval - peak) / peak * 100
            max_dd = abs(dd.min())

            # 夏普
            rets_clean = rets[rets != 0]
            sharpe = rets_clean.mean() / rets_clean.std() * np.sqrt(252) if len(rets_clean) > 1 and rets_clean.std() > 0 else 0

            print(f"\n  {market_name} | 底仓{int(base_pct*100)}% | {strategy_func.__doc__.split('★')[0].strip()}")
            print(f"    总收益率: {total_ret:.2f}%  |  年化: {annual:.2f}%  |  最大回撤: {max_dd:.2f}%  |  夏普: {sharpe:.2f}")

    print(f"\n{'━' * 90}")
    print("  ✅ 修正版回测完成！")
    print("  修正内容: #1手续费仅开平仓日扣 #5ATR止损线只上不下 #6信号T+1+次日开盘价成交")
    print(f"{'━' * 90}")
