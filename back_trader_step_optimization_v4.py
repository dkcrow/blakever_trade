#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
Blakever 牛市策略 — 第四轮：根因驱动优化回测
==========================================================================
根因发现: ADX>20过滤导致26%牛市交易日空仓，策略持仓仅34.7%（美股）
核心思路: 提高持仓占比的同时保持回撤控制

本轮测试的新优化方向:
A. 入场查ADX>20，持仓期间不查ADX（仅EMA死叉出场）
B. ADX阈值从20降至15
C. 完全去掉ADX，仅用EMA10/20持仓跟踪
D. 入场查ADX>20，用ATR3.5x止损替代EMA死叉出场
E. 入场查ADX>20，持仓不查ADX，ATR3.5x止损+EMA死叉双出场
F. 上述各方案+底仓模式组合

严格遵循Agent 8规范: 过拟合检测+一致性验证+收益回撤比提升>10%才采纳
==========================================================================
"""

import os, glob, warnings
import numpy as np, pandas as pd, talib, vectorbt as vbt
warnings.filterwarnings('ignore')

BASE_DIR = '/data/workspace/back_trader_stocks'
INIT_CASH = 100000; FEES = 0.001; SLIPPAGE = 0.001
TRAIN_RATIO = 0.7; MIN_DATA_DAYS = 250; MIN_BULL_DAYS = 50


def load_stock_data(filepath):
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date').sort_index()
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.dropna(subset=['close'])
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close'])
        return df
    except:
        return None


def load_all_stocks(market='us'):
    directory = os.path.join(BASE_DIR, 'hk' if market == 'hk' else 'us')
    files = sorted(glob.glob(os.path.join(directory, '*.csv')))
    stocks = {}
    for f in files:
        symbol = os.path.basename(f).replace('.csv', '')
        df = load_stock_data(f)
        if df is not None and len(df) >= MIN_DATA_DAYS:
            stocks[symbol] = df
    return stocks


def identify_bull_periods(close_series):
    close = close_series.copy()
    sma50 = talib.SMA(close.values, timeperiod=50)
    sma200 = talib.SMA(close.values, timeperiod=200)
    sma50_s = pd.Series(sma50, index=close.index)
    sma200_s = pd.Series(sma200, index=close.index)
    bull_mask = (close > sma200_s) & (sma50_s > sma200_s)
    early_mask = sma200_s.isna()
    if early_mask.any():
        sma20_early = close.rolling(20).mean()
        sma50_early = close.rolling(50).mean()
        early_bull = (close > sma50_early) & (sma20_early > sma50_early)
        bull_mask = bull_mask.fillna(early_bull)
    return bull_mask.fillna(False)


# ================================================================
# 策略函数
# ================================================================

def strat_baseline(close, high, low):
    """基线: EMA10/20+ADX>20 入场+持仓都查"""
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


def strat_entry_adx_hold_ema(close, high, low):
    """入场查ADX>20，持仓期间不查ADX（仅EMA死叉出场）"""
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)

    n = len(c)
    in_pos = np.full(n, False)
    holding = False
    for i in range(n):
        if not holding:
            if ema10.iloc[i] > ema20.iloc[i] and adx_s.iloc[i] > 20:
                in_pos[i] = True
                holding = True
        else:
            if ema10.iloc[i] < ema20.iloc[i]:
                holding = False
            else:
                in_pos[i] = True

    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if in_pos[i] and not in_pos[i-1]:
            entries[i] = True
        elif not in_pos[i] and in_pos[i-1]:
            exits[i] = True
    return entries, exits


def strat_adx15(close, high, low):
    """ADX>15（从20降至15）"""
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    in_pos = (ema10 > ema20) & (adx_s > 15)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


def strat_no_adx(close, high, low):
    """完全去掉ADX，仅EMA10/20持仓跟踪"""
    c = pd.Series(close, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    in_pos = ema10 > ema20
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


def strat_entry_adx_atr_exit(close, high, low, atr_mult=3.5):
    """入场查ADX>20，用ATR止损替代EMA死叉出场"""
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
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop
            if c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest = 0.0
                stop = 0.0
    return entries, exits


def strat_entry_adx_hold_ema_atr_exit(close, high, low, atr_mult=3.5):
    """入场查ADX>20，持仓不查ADX，ATR3.5x止损+EMA死叉双出场"""
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
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop
            if ema10.iloc[i] < ema20.iloc[i] or c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest = 0.0
                stop = 0.0
    return entries, exits


def strat_ema15_30_no_adx(close, high, low):
    """EMA15/30无ADX（更慢均线，减少假信号）"""
    c = pd.Series(close, dtype=float)
    ema15 = c.ewm(span=15, adjust=False).mean()
    ema30 = c.ewm(span=30, adjust=False).mean()
    in_pos = ema15 > ema30
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# 回测引擎
# ================================================================

def run_backtest(close, entries, exits):
    try:
        if entries.sum() == 0:
            return None
        pf = vbt.Portfolio.from_signals(close, entries=entries, exits=exits,
                                         freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE)
        return pf
    except:
        return None


def calc_stats(pf):
    if pf is None: return None
    stats = pf.stats()
    total_ret = float(stats['Total Return [%]'])
    max_dd = float(stats['Max Drawdown [%]'])
    n_years = len(pf.returns()) / 252
    annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else -100
    sharpe = float(stats.get('Sharpe Ratio', 0))
    if pd.isna(sharpe): sharpe = 0
    win_rate = float(stats['Win Rate [%]'])
    total_trades = int(stats['Total Trades'])
    return {'年化%': round(annual, 2), '回撤%': round(max_dd, 2), '夏普': round(sharpe, 2),
            '胜率%': round(win_rate, 1), '交易数': total_trades}


def overfit_test(close, high, low, strategy_func):
    n = len(close); split = int(n * TRAIN_RATIO)
    entries_t, exits_t = strategy_func(close[:split], high[:split], low[:split])
    entries_v, exits_v = strategy_func(close[split:], high[split:], low[split:])
    pf_t = run_backtest(close[:split], entries_t, exits_t)
    pf_v = run_backtest(close[split:], entries_v, exits_v)
    if pf_t is None or pf_v is None: return None
    st_t = calc_stats(pf_t); st_v = calc_stats(pf_v)
    if st_t is None or st_v is None: return None
    drop = (st_t['年化%'] - st_v['年化%']) / abs(st_t['年化%']) * 100 if st_t['年化%'] > 0 else 0
    return {'训练年化%': st_t['年化%'], '测试年化%': st_v['年化%'], '下降%': round(drop, 1), '过拟合': drop > 30}


def compute_equal_weight_portfolio(returns_dict):
    if not returns_dict: return None
    max_len = max(len(r) for r in returns_dict.values())
    port_rets = []
    for i in range(max_len):
        day_rets = [r[i] for r in returns_dict.values() if i < len(r)]
        if day_rets:
            port_rets.append(np.mean(day_rets))
    port_rets = np.array(port_rets)
    if len(port_rets) == 0: return None
    cum = np.cumprod(1 + port_rets)
    total_ret = (cum[-1] - 1) * 100
    n_years = len(port_rets) / 252
    annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else -100
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = abs(dd.min()) * 100
    sharpe = np.mean(port_rets) / np.std(port_rets) * np.sqrt(252) if np.std(port_rets) > 0 else 0
    return {'年化%': round(annual, 2), '回撤%': round(max_dd, 2), '夏普': round(sharpe, 2)}


def compute_base_position_portfolio(strat_returns_dict, bh_returns_dict, bp):
    if not strat_returns_dict or not bh_returns_dict: return None
    common = set(strat_returns_dict.keys()) & set(bh_returns_dict.keys())
    if not common: return None
    max_len = max(max(len(strat_returns_dict[s]) for s in common),
                  max(len(bh_returns_dict[s]) for s in common))
    port_rets = []
    for i in range(max_len):
        day_rets = []
        for s in common:
            sr = strat_returns_dict[s]
            br = bh_returns_dict[s]
            if i < len(sr) and i < len(br):
                day_rets.append(bp * br[i] + (1 - bp) * sr[i])
            elif i < len(br):
                day_rets.append(bp * br[i])
        if day_rets:
            port_rets.append(np.mean(day_rets))
    port_rets = np.array(port_rets)
    if len(port_rets) == 0: return None
    cum = np.cumprod(1 + port_rets)
    total_ret = (cum[-1] - 1) * 100
    n_years = len(port_rets) / 252
    annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else -100
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = abs(dd.min()) * 100
    sharpe = np.mean(port_rets) / np.std(port_rets) * np.sqrt(252) if np.std(port_rets) > 0 else 0
    return {'年化%': round(annual, 2), '回撤%': round(max_dd, 2), '夏普': round(sharpe, 2)}


# ================================================================
# 主流程
# ================================================================

def run_round4(market='us'):
    market_cn = '港股' if market == 'hk' else '美股'
    print(f"\n{'━' * 120}")
    print(f"  🔬 {market_cn} — 第四轮：根因驱动优化回测")
    print(f"{'━' * 120}")

    stocks = load_all_stocks(market)
    print(f"  ✅ 加载 {len(stocks)} 只股票\n")

    strategies = [
        ('A_基线EMA10/20+ADX>20', strat_baseline),
        ('B_入场查ADX持仓不查', strat_entry_adx_hold_ema),
        ('C_ADX>15', strat_adx15),
        ('D_无ADX纯EMA10/20', strat_no_adx),
        ('E_入场ADX+ATR3.5x止损出场', strat_entry_adx_atr_exit),
        ('F_入场ADX持仓不查+ATR3.5x+EMA双出场', strat_entry_adx_hold_ema_atr_exit),
        ('G_EMA15/30无ADX', strat_ema15_30_no_adx),
    ]

    all_stats = {s[0]: {} for s in strategies}
    all_overfit = {s[0]: {} for s in strategies}
    all_returns = {s[0]: {} for s in strategies}
    all_bh = {}
    all_hold_pct = {s[0]: {} for s in strategies}

    for symbol, df in stocks.items():
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)

        bull_mask = identify_bull_periods(df['close'])
        if bull_mask.sum() < MIN_BULL_DAYS: continue
        bc = close[bull_mask.values]
        bh_v = high[bull_mask.values]
        bl = low[bull_mask.values]
        if len(bc) < 50: continue

        # B&H
        entries_bh = np.full(len(bc), False); entries_bh[0] = True
        exits_bh = np.full(len(bc), False)
        pf_bh = run_backtest(bc, entries_bh, exits_bh)
        if pf_bh is not None:
            all_bh[symbol] = pf_bh.returns().values

        for sname, sfunc in strategies:
            entries, exits = sfunc(bc, bh_v, bl)
            pf = run_backtest(bc, entries, exits)
            if pf is not None:
                st = calc_stats(pf)
                if st: all_stats[sname][symbol] = st
                all_returns[sname][symbol] = pf.returns().values

                # 持仓占比
                in_pos = np.zeros(len(bc), dtype=bool)
                holding = False
                for i in range(len(bc)):
                    if entries[i]: holding = True
                    elif exits[i]: holding = False
                    in_pos[i] = holding
                all_hold_pct[sname][symbol] = in_pos.sum() / len(bc) * 100

            of = overfit_test(bc, bh_v, bl, sfunc)
            if of: all_overfit[sname][symbol] = of

    # ================================================================
    # 汇总
    # ================================================================
    print(f"\n{'━' * 120}")
    print(f"  📊 {market_cn} — 第四轮结果汇总")
    print(f"{'━' * 120}\n")

    header = f"{'策略':<42} {'股票':>4} {'持仓%':>6} {'年化%':>7} {'夏普':>6} {'回撤%':>7} {'交易':>5} {'胜B&H':>6} {'过拟合%':>7} {'等权年化':>8} {'等权夏普':>8} {'等权回撤':>8}"
    print(header)
    print("-" * 125)

    rows = []

    for sname in [s[0] for s in strategies]:
        stats = all_stats[sname]
        if not stats: continue

        n_stocks = len(stats)
        annuals = [r['年化%'] for r in stats.values()]
        sharps = [r['夏普'] for r in stats.values()]
        dds = [r['回撤%'] for r in stats.values()]
        trades = [r['交易数'] for r in stats.values() if r['交易数'] > 0]
        hold_pcts = list(all_hold_pct[sname].values())

        avg_annual = np.mean(annuals)
        avg_sharpe = np.mean(sharps)
        avg_dd = np.mean(dds)
        avg_trades = np.mean(trades) if trades else 0
        avg_hold = np.mean(hold_pcts) if hold_pcts else 0

        # 胜B&H
        beat_count = 0
        total_count = 0
        for s, r in stats.items():
            if s in all_bh and len(all_bh[s]) > 0:
                bh_cum = np.cumprod(1 + all_bh[s])
                bh_total = (bh_cum[-1] - 1) * 100
                bh_ny = len(all_bh[s]) / 252
                bh_annual = ((1 + bh_total / 100) ** (1 / bh_ny) - 1) * 100 if bh_ny > 0 else 0
                if r['年化%'] > bh_annual: beat_count += 1
                total_count += 1
        beat_pct = beat_count / total_count * 100 if total_count > 0 else 0

        # 过拟合
        of_results = all_overfit[sname]
        of_count = sum(1 for o in of_results.values() if o.get('过拟合', False))
        of_rate = of_count / len(of_results) * 100 if of_results else 0

        # 等权组合
        eq = compute_equal_weight_portfolio(all_returns[sname])

        row = {
            '策略': sname, '股票数': n_stocks, '持仓%': round(avg_hold, 1),
            '年化%': round(avg_annual, 2), '夏普': round(avg_sharpe, 2),
            '回撤%': round(avg_dd, 2), '交易数': round(avg_trades, 0),
            '胜B&H%': round(beat_pct, 1), '过拟合率%': round(of_rate, 1),
            '等权年化%': eq['年化%'] if eq else 0,
            '等权夏普': eq['夏普'] if eq else 0,
            '等权回撤%': eq['回撤%'] if eq else 0,
        }
        rows.append(row)

        eq_a = f"{eq['年化%']:.1f}" if eq else '-'
        eq_s = f"{eq['夏普']:.2f}" if eq else '-'
        eq_d = f"{eq['回撤%']:.1f}" if eq else '-'

        print(f"{sname:<42} {n_stocks:>4} {avg_hold:>5.1f}% {avg_annual:>6.2f}% {avg_sharpe:>5.2f} {avg_dd:>6.2f}% {avg_trades:>5.0f} {beat_pct:>5.1f}% {of_rate:>6.1f}% {eq_a:>8} {eq_s:>8} {eq_d:>8}")

    # B&H
    bh_eq = compute_equal_weight_portfolio(all_bh)
    if bh_eq:
        print(f"{'B&H基准':<42} {len(all_bh):>4} {'100%':>6} {'—':>7} {'—':>6} {'—':>7} {'—':>5} {'—':>6} {'—':>7} {bh_eq['年化%']:>8.1f} {bh_eq['夏普']:>8.2f} {bh_eq['回撤%']:>8.1f}")

    # ================================================================
    # 底仓模式组合
    # ================================================================
    print(f"\n{'━' * 120}")
    print(f"  📊 {market_cn} — 底仓模式组合（策略+B&H加权）")
    print(f"{'━' * 120}\n")

    header2 = f"{'组合':<50} {'等权年化':>8} {'等权夏普':>8} {'等权回撤':>8} {'收益回撤比':>10} {'vs基线提升':>10} {'过拟合%':>7} {'采纳':>4}"
    print(header2)
    print("-" * 110)

    baseline_eq = compute_equal_weight_portfolio(all_returns['A_基线EMA10/20+ADX>20'])
    baseline_dd = baseline_eq['回撤%'] if baseline_eq else 100
    baseline_ratio = baseline_eq['年化%'] / baseline_dd if baseline_eq and baseline_dd > 0 else 0

    adopted = []

    for sname in [s[0] for s in strategies]:
        if sname not in all_returns: continue
        for bp in [0.30, 0.50]:
            bp_name = f"{sname}+底仓{int(bp*100)}%"
            bp_eq = compute_base_position_portfolio(all_returns[sname], all_bh, bp)
            if bp_eq is None: continue

            of_rate = rows[[r['策略'] for r in rows].index(sname)]['过拟合率%'] if sname in [r['策略'] for r in rows] else 0
            ratio_new = bp_eq['年化%'] / bp_eq['回撤%'] if bp_eq['回撤%'] > 0 else 0
            ratio_imp = (ratio_new - baseline_ratio) / abs(baseline_ratio) * 100 if baseline_ratio != 0 else 0

            c1 = bp_eq['夏普'] > 0.5
            c2 = bp_eq['回撤%'] < 30
            c3 = of_rate < 50
            c4 = ratio_imp > 10

            adopt = c1 and c2 and c3 and c4
            if adopt: adopted.append(bp_name)

            print(f"{bp_name:<50} {bp_eq['年化%']:>7.1f}% {bp_eq['夏普']:>8.2f} {bp_eq['回撤%']:>7.1f}% {ratio_new:>10.3f} {ratio_imp:>+9.1f}% {of_rate:>6.1f}% {'✅' if adopt else '❌':>4}")

    # 纯策略（无底仓）
    print(f"\n  --- 纯策略（无底仓）---\n")
    for row in rows:
        sname = row['策略']
        eq = compute_equal_weight_portfolio(all_returns[sname])
        if eq is None: continue
        ratio_new = eq['年化%'] / eq['回撤%'] if eq['回撤%'] > 0 else 0
        ratio_imp = (ratio_new - baseline_ratio) / abs(baseline_ratio) * 100 if baseline_ratio != 0 else 0

        c1 = eq['夏普'] > 0.5
        c2 = eq['回撤%'] < 30
        c3 = row['过拟合率%'] < 50
        c4 = ratio_imp > 10
        adopt = c1 and c2 and c3 and c4
        if adopt: adopted.append(sname)

        print(f"{sname:<50} {eq['年化%']:>7.1f}% {eq['夏普']:>8.2f} {eq['回撤%']:>7.1f}% {ratio_new:>10.3f} {ratio_imp:>+9.1f}% {row['过拟合率%']:>6.1f}% {'✅' if adopt else '❌':>4}")

    # ================================================================
    # 采纳决策详情
    # ================================================================
    print(f"\n{'━' * 120}")
    print(f"  🎯 {market_cn} — 采纳决策详情")
    print(f"{'━' * 120}\n")

    print(f"  基线: 等权年化{baseline_eq['年化%'] if baseline_eq else '?'}% 夏普{baseline_eq['夏普'] if baseline_eq else '?'} 回撤{baseline_dd}% 收益回撤比{baseline_ratio:.3f}\n")

    for sname in [s[0] for s in strategies]:
        if sname == 'A_基线EMA10/20+ADX>20': continue

        eq = compute_equal_weight_portfolio(all_returns[sname])
        if eq is None: continue
        of_rate = rows[[r['策略'] for r in rows].index(sname)]['过拟合率%'] if sname in [r['策略'] for r in rows] else 0

        ratio_new = eq['年化%'] / eq['回撤%'] if eq['回撤%'] > 0 else 0
        ratio_imp = (ratio_new - baseline_ratio) / abs(baseline_ratio) * 100 if baseline_ratio != 0 else 0

        reasons = []
        if eq['夏普'] <= 0.5: reasons.append(f"夏普{eq['夏普']:.2f}≤0.5")
        if eq['回撤%'] >= 30: reasons.append(f"回撤{eq['回撤%']:.1f}%≥30%")
        if of_rate >= 50: reasons.append(f"过拟合{of_rate:.1f}%≥50%")
        if ratio_imp <= 10: reasons.append(f"收益回撤比提升{ratio_imp:.1f}%≤10%")

        icon = '✅' if len(reasons) == 0 else '❌'
        print(f"  {icon} {sname}")
        print(f"     年化{eq['年化%']:.1f}% 夏普{eq['夏普']:.2f} 回撤{eq['回撤%']:.1f}% 持仓{rows[[r['策略'] for r in rows].index(sname)]['持仓%'] if sname in [r['策略'] for r in rows] else '?'}% 收益回撤比{ratio_new:.3f}(+{ratio_imp:.1f}%)")
        if reasons:
            print(f"     拒绝: {', '.join(reasons)}")
        print()

    return adopted, bh_eq, rows


if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     🔬 Blakever 牛市策略 — 第四轮：根因驱动优化回测                        ║
║                                                                              ║
║     根因: ADX>20过滤导致26%牛市交易日空仓，策略持仓仅34.7%                ║
║                                                                              ║
║     测试方向:                                                                ║
║     A: 基线(EMA10/20+ADX>20)                                               ║
║     B: 入场查ADX,持仓不查ADX                                               ║
║     C: ADX阈值降至15                                                        ║
║     D: 完全去掉ADX(纯EMA10/20)                                             ║
║     E: 入场ADX+ATR3.5x止损出场                                             ║
║     F: 入场ADX持仓不查+ATR3.5x+EMA双出场                                  ║
║     G: EMA15/30无ADX                                                        ║
║     + 各方案+底仓30%/50%组合                                                ║
║                                                                              ║
║     采纳标准(Agent 8规范):                                                  ║
║     1. 等权夏普>0.5, 回撤<30%                                              ║
║     2. 过拟合率<50%                                                         ║
║     3. 收益/回撤比提升>10%                                                 ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    us_adopted, us_bh, us_rows = run_round4('us')
    hk_adopted, hk_bh, hk_rows = run_round4('hk')

    print(f"\n{'━' * 120}")
    print("  🏆 第四轮最终优化总结")
    print(f"{'━' * 120}")
    print(f"\n  📊 美股采纳: {us_adopted}")
    print(f"  📊 港股采纳: {hk_adopted}")
    print("\n✅ 第四轮回测完成！")
