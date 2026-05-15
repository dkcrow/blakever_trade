#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEM (Global Equities Momentum) 双动量轮动策略
===============================================
正宗 Gary Antonacci 的 Dual Momentum GEM 策略实现：
  - 相对动量：在多资产中选择12M收益率最高的标的
  - 绝对动量：若最优标的12M收益率<0，则持有现金等价物
  - 月度调仓，避免过度交易

资产池（美股版）：
  - SPY: 标普500（美股大盘）
  - VEA: 国际发达市场（替代EFA）
  - AGG: 美国综合债券
  - SHY: 短期国债（现金等价物）

扩展资产池（可选）：
  - GLD: 黄金
  - TLT: 长期国债
  - VWO: 新兴市场

回测区间（适配本地数据 2018-05 ~ 2026-04）：
  - 主回测: 2019-01-01 ~ 2024-12-31（6年）
  - 压力测试: 2019-01-01 ~ 2020-12-31（含疫情暴跌）
  - 牛市: 2023-01-01 ~ 2024-12-31

关键优势 vs 单资产版Dual Momentum：
  1. 多资产轮动避免完全空仓踏空
  2. 2022年股债双杀时自动切至短期国债
  3. 相对动量捕捉跨资产轮动机会
"""

import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ================================================================
# 配置
# ================================================================
ETF_DATA_DIR = '/data/workspace/back_trader_stocks/etf'
INIT_CASH = 1_000_000
FEES = 0.001       # 手续费率
SLIPPAGE = 0.001   # 滑点
RISK_FREE_RATE = 0.045  # 无风险利率

# 回测区间
MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'
STRESS_START = '2019-01-01'
STRESS_END = '2020-12-31'
BULL_START = '2023-01-01'
BULL_END = '2024-12-31'


# ================================================================
# 数据加载
# ================================================================
def load_etf_data(symbol: str) -> pd.DataFrame:
    """加载ETF CSV数据"""
    filepath = os.path.join(ETF_DATA_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        print(f"  ⚠️ {symbol} 数据文件不存在: {filepath}", file=sys.stderr)
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        for col in ['Open', 'High', 'Low', 'Close']:
            if col not in df.columns:
                return None
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except Exception as e:
        print(f"  ⚠️ 加载 {symbol} 失败: {e}", file=sys.stderr)
        return None


# ================================================================
# GEM 策略核心逻辑
# ================================================================
def gem_monthly_rotation(close_prices: pd.DataFrame, lookback_months: int = 12,
                         cash_symbol: str = 'SHY') -> pd.DataFrame:
    """
    GEM 月度轮动策略
    
    参数:
      close_prices: 多资产收盘价 DataFrame (index=Date, columns=symbols)
      lookback_months: 动量回看月数（默认12M）
      cash_symbol: 现金等价物标的
    
    逻辑:
      每月末调仓：
      1. 计算所有标的过去 lookback_months 个月收益率（绝对动量）
      2. 选出收益率最高的标的（相对动量）
      3. 若该标的收益率 < 0，则持有现金等价物
      4. 次月第一个交易日执行调仓
    """
    lookback_days = lookback_months * 21  # 近似交易日

    # 月末日期标记
    monthly = close_prices.resample('ME').last()

    # 为每个交易日确定"当前应持有的标的"
    all_dates = close_prices.index
    holding = pd.Series(index=all_dates, dtype=object)

    for i, date in enumerate(all_dates):
        # 找到当前日期之前的最近月末
        prior_month_ends = monthly.index[monthly.index <= date]
        if len(prior_month_ends) == 0:
            holding.iloc[i] = cash_symbol
            continue

        last_month_end = prior_month_ends[-1]

        # 需要至少 lookback_days 的历史数据
        ref_idx = close_prices.index.get_loc(last_month_end) if last_month_end in close_prices.index else -1
        if ref_idx < lookback_days:
            holding.iloc[i] = cash_symbol
            continue

        # 计算各标的动量（12M收益率）
        ref_date = close_prices.index[ref_idx - lookback_days] if ref_idx >= lookback_days else None
        if ref_date is None:
            holding.iloc[i] = cash_symbol
            continue

        # 使用月末价格和lookback前的价格
        current_prices = close_prices.loc[last_month_end]
        past_prices = close_prices.iloc[max(0, ref_idx - lookback_days)]

        momentum = (current_prices / past_prices - 1).dropna()

        if len(momentum) == 0:
            holding.iloc[i] = cash_symbol
            continue

        # 相对动量：选择收益率最高的
        best_asset = momentum.idxmax()
        best_momentum = momentum.max()

        # 绝对动量：若最优标的收益率<0，持有现金
        if best_momentum < 0:
            holding.iloc[i] = cash_symbol
        else:
            holding.iloc[i] = best_asset

    return holding


def gem_dual_momentum_rotation(close_prices: pd.DataFrame,
                                risk_assets: list,
                                safe_assets: list,
                                lookback_months: int = 12) -> pd.DataFrame:
    """
    改进版 GEM 双动量轮动策略
    
    标准GEM流程（更清晰的分层结构）：
    1. 绝对动量过滤：12M收益率>0的风险资产才能进入候选池
    2. 相对动量选择：在候选池中选择收益率最高的风险资产
    3. 若候选池为空（所有风险资产12M收益率<0），则持有安全资产中12M收益率最高者
    4. 次月第一个交易日执行调仓
    
    参数:
      close_prices: 多资产收盘价 DataFrame
      risk_assets: 风险资产列表（如SPY, VEA, VWO）
      safe_assets: 安全资产列表（如AGG, SHY, TLT）
      lookback_months: 动量回看月数
    """
    lookback_days = lookback_months * 21

    # 月末日期标记
    monthly = close_prices.resample('ME').last()

    all_dates = close_prices.index
    holding = pd.Series(index=all_dates, dtype=object)

    for i, date in enumerate(all_dates):
        prior_month_ends = monthly.index[monthly.index <= date]
        if len(prior_month_ends) == 0:
            holding.iloc[i] = safe_assets[-1]  # 默认持有最安全的资产
            continue

        last_month_end = prior_month_ends[-1]

        ref_idx = None
        for j, idx in enumerate(close_prices.index):
            if idx == last_month_end:
                ref_idx = j
                break
        if ref_idx is None or ref_idx < lookback_days:
            holding.iloc[i] = safe_assets[-1]
            continue

        past_idx = max(0, ref_idx - lookback_days)
        current_prices = close_prices.iloc[ref_idx]
        past_prices = close_prices.iloc[past_idx]

        # 步骤1: 绝对动量过滤（风险资产）
        risk_momentum = {}
        for asset in risk_assets:
            if asset in current_prices.index and asset in past_prices.index:
                curr = current_prices[asset]
                past = past_prices[asset]
                if pd.notna(curr) and pd.notna(past) and past > 0:
                    risk_momentum[asset] = curr / past - 1

        # 过滤：12M收益率>0
        positive_risk = {k: v for k, v in risk_momentum.items() if v > 0}

        if positive_risk:
            # 步骤2: 相对动量选择（选最优风险资产）
            best_risk = max(positive_risk, key=positive_risk.get)
            holding.iloc[i] = best_risk
        else:
            # 步骤3: 所有风险资产12M收益<0，持有安全资产中最强者
            safe_momentum = {}
            for asset in safe_assets:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        safe_momentum[asset] = curr / past - 1

            if safe_momentum:
                best_safe = max(safe_momentum, key=safe_momentum.get)
                holding.iloc[i] = best_safe
            else:
                holding.iloc[i] = safe_assets[-1]

    return holding


# ================================================================
# 回测引擎（多资产轮动专用）
# ================================================================
def run_gem_backtest(close_prices: pd.DataFrame, holding: pd.Series,
                     start_date: str, end_date: str,
                     init_cash: float = INIT_CASH,
                     fees: float = FEES, slippage: float = SLIPPAGE) -> dict:
    """
    执行GEM轮动策略回测
    
    模拟逻辑：
    - 月度调仓：月末决策，次月第一个交易日执行
    - T+1修正：调仓信号次日生效
    - 手续费：每次调仓按总资产0.1%
    - 滑点：每次调仓0.1%
    """
    # 截取区间
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    h = holding.loc[mask]

    if len(prices) < 100:
        return None

    # 计算每日收益率
    daily_returns = prices.pct_change().fillna(0)

    # 按持仓计算组合收益率
    portfolio_returns = pd.Series(0.0, index=prices.index)

    prev_asset = None
    trade_count = 0

    for date in prices.index:
        current_asset = h.loc[date]

        if current_asset is None or current_asset not in daily_returns.columns:
            portfolio_returns.loc[date] = 0.0
            continue

        # 获取当前持有资产的收益率
        if current_asset in daily_returns.columns:
            asset_return = daily_returns.loc[date, current_asset]
            if pd.notna(asset_return):
                portfolio_returns.loc[date] = asset_return
            else:
                portfolio_returns.loc[date] = 0.0

        # 检测调仓（持仓变动）
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            # 扣除调仓成本（手续费+滑点）
            cost = fees + slippage
            portfolio_returns.loc[date] -= cost

        prev_asset = current_asset

    # 计算累计净值
    cum_returns = (1 + portfolio_returns).cumprod()
    final_value = init_cash * cum_returns.iloc[-1]

    # 统计指标
    n_years = len(prices) / 252
    total_return = (final_value / init_cash - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    # 最大回撤
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max
    max_dd = abs(drawdown.min()) * 100

    # 夏普比率
    sharpe = portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    adj_sharpe = (portfolio_returns.mean() - RISK_FREE_RATE / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0

    # 胜率（日）
    win_days = (portfolio_returns > 0).sum()
    total_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_days, 1) * 100

    # 盈亏比
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0

    # 年交易次数
    annual_trades = trade_count / max(n_years, 0.01)

    # 持仓分布
    holding_counts = h.value_counts()
    holding_pcts = (holding_counts / len(h) * 100).to_dict()

    # 按月收益率
    monthly_returns = portfolio_returns.resample('ME').apply(lambda x: (1 + x).prod() - 1)

    # 最大连续亏损月数
    is_loss_month = monthly_returns < 0
    consec = 0
    max_consec = 0
    for v in is_loss_month:
        if v:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'adj_sharpe': round(adj_sharpe, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'total_trades': trade_count,
        'avg_trades_per_year': round(annual_trades, 1),
        'max_consec_loss_months': max_consec,
        'holding_distribution': {k: round(v, 1) for k, v in holding_pcts.items()},
        'final_value': round(final_value, 2),
        'n_years': round(n_years, 2),
        'init_cash': init_cash,
        'start_date': start_date,
        'end_date': end_date,
    }


# ================================================================
# B&H 基准
# ================================================================
def run_buy_hold_baseline(close_prices: pd.DataFrame, symbol: str,
                          start_date: str, end_date: str) -> dict:
    """计算单资产B&H基准"""
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]

    if symbol not in prices.columns or len(prices) < 100:
        return None

    series = prices[symbol].dropna()
    n_years = len(series) / 252
    total_return = (series.iloc[-1] / series.iloc[0] - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    daily_returns = series.pct_change().dropna()
    cum = (1 + daily_returns).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100
    sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0

    return {
        'symbol': symbol,
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
    }


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 80)
    print("  🌍 GEM (Global Equities Momentum) 双动量轮动策略回测")
    print("=" * 80)

    # ── 加载所有ETF数据 ──
    print("\n📦 加载ETF数据...")
    etf_symbols = ['SPY', 'VEA', 'AGG', 'SHY', 'TLT', 'IEF', 'VWO', 'GLD']
    etf_data = {}

    for sym in etf_symbols:
        df = load_etf_data(sym)
        if df is not None:
            etf_data[sym] = df['Close']
            start = df.index[0].strftime('%Y-%m-%d')
            end = df.index[-1].strftime('%Y-%m-%d')
            print(f"  ✅ {sym}: {len(df)} 行, {start} ~ {end}")
        else:
            print(f"  ❌ {sym}: 数据不可用")

    if len(etf_data) < 4:
        print("❌ 可用ETF不足4只，无法执行GEM策略")
        return

    # 合并为多资产DataFrame
    close_prices = pd.DataFrame(etf_data)
    close_prices = close_prices.dropna(how='all').sort_index()
    # 前向填充缺失值
    close_prices = close_prices.ffill().bfill()

    print(f"\n📊 多资产价格矩阵: {close_prices.shape[0]}天 x {close_prices.shape[1]}资产")

    # ══════════════════════════════════════════════
    # 策略1: 标准GEM (SPY/VEA/AGG/SHY)
    # ══════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  📋 策略1: 标准GEM轮动 (SPY/VEA/AGG/SHY)")
    print("=" * 80)

    standard_risk = ['SPY', 'VEA']
    standard_safe = ['AGG', 'SHY']
    standard_universe = standard_risk + standard_safe

    holding_std = gem_dual_momentum_rotation(
        close_prices[standard_universe],
        risk_assets=standard_risk,
        safe_assets=standard_safe,
        lookback_months=12
    )

    # 主回测
    print(f"\n🚀 主回测: {MAIN_START} ~ {MAIN_END}")
    result_std_main = run_gem_backtest(
        close_prices[standard_universe], holding_std,
        MAIN_START, MAIN_END
    )
    if result_std_main:
        print(f"  年化收益: {result_std_main['annual_return']}%")
        print(f"  总收益:   {result_std_main['total_return']}%")
        print(f"  最大回撤: {result_std_main['max_drawdown']}%")
        print(f"  夏普比率: {result_std_main['sharpe']}")
        print(f"  调整夏普: {result_std_main['adj_sharpe']}")
        print(f"  盈亏比:   {result_std_main['profit_factor']}")
        print(f"  胜率:     {result_std_main['win_rate']}%")
        print(f"  年调仓:   {result_std_main['avg_trades_per_year']}次")
        print(f"  持仓分布: {result_std_main['holding_distribution']}")
        print(f"  最终净值: {result_std_main['final_value']:,.0f}")

    # 压力测试（含2020疫情暴跌）
    print(f"\n💪 压力测试: {STRESS_START} ~ {STRESS_END}")
    result_std_stress = run_gem_backtest(
        close_prices[standard_universe], holding_std,
        STRESS_START, STRESS_END
    )
    if result_std_stress:
        print(f"  年化收益: {result_std_stress['annual_return']}%")
        print(f"  最大回撤: {result_std_stress['max_drawdown']}%")
        print(f"  夏普比率: {result_std_stress['sharpe']}")

    # 牛市区间
    print(f"\n🐂 牛市区间: {BULL_START} ~ {BULL_END}")
    result_std_bull = run_gem_backtest(
        close_prices[standard_universe], holding_std,
        BULL_START, BULL_END
    )
    if result_std_bull:
        print(f"  年化收益: {result_std_bull['annual_return']}%")
        print(f"  最大回撤: {result_std_bull['max_drawdown']}%")

    # ══════════════════════════════════════════════
    # 策略2: 扩展GEM (加入GLD/VWO/TLT)
    # ══════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  📋 策略2: 扩展GEM轮动 (SPY/VEA/VWO/AGG/TLT/IEF/SHY/GLD)")
    print("=" * 80)

    extended_risk = ['SPY', 'VEA', 'VWO', 'GLD']
    extended_safe = ['AGG', 'TLT', 'IEF', 'SHY']
    extended_universe = extended_risk + extended_safe
    available_extended = [s for s in extended_universe if s in close_prices.columns]

    holding_ext = gem_dual_momentum_rotation(
        close_prices[available_extended],
        risk_assets=[s for s in extended_risk if s in available_extended],
        safe_assets=[s for s in extended_safe if s in available_extended],
        lookback_months=12
    )

    print(f"\n🚀 主回测: {MAIN_START} ~ {MAIN_END}")
    result_ext_main = run_gem_backtest(
        close_prices[available_extended], holding_ext,
        MAIN_START, MAIN_END
    )
    if result_ext_main:
        print(f"  年化收益: {result_ext_main['annual_return']}%")
        print(f"  总收益:   {result_ext_main['total_return']}%")
        print(f"  最大回撤: {result_ext_main['max_drawdown']}%")
        print(f"  夏普比率: {result_ext_main['sharpe']}")
        print(f"  调整夏普: {result_ext_main['adj_sharpe']}")
        print(f"  盈亏比:   {result_ext_main['profit_factor']}")
        print(f"  胜率:     {result_ext_main['win_rate']}%")
        print(f"  年调仓:   {result_ext_main['avg_trades_per_year']}次")
        print(f"  持仓分布: {result_ext_main['holding_distribution']}")
        print(f"  最终净值: {result_ext_main['final_value']:,.0f}")

    print(f"\n💪 压力测试: {STRESS_START} ~ {STRESS_END}")
    result_ext_stress = run_gem_backtest(
        close_prices[available_extended], holding_ext,
        STRESS_START, STRESS_END
    )
    if result_ext_stress:
        print(f"  年化收益: {result_ext_stress['annual_return']}%")
        print(f"  最大回撤: {result_ext_stress['max_drawdown']}%")

    # ══════════════════════════════════════════════
    # 策略3: 简化GEM (SPY/AGG/SHY) — 最小化版本
    # ══════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  📋 策略3: 简化GEM轮动 (SPY/AGG/SHY)")
    print("=" * 80)

    simple_risk = ['SPY']
    simple_safe = ['AGG', 'SHY']
    simple_universe = simple_risk + simple_safe

    holding_simple = gem_dual_momentum_rotation(
        close_prices[simple_universe],
        risk_assets=simple_risk,
        safe_assets=simple_safe,
        lookback_months=12
    )

    print(f"\n🚀 主回测: {MAIN_START} ~ {MAIN_END}")
    result_simple_main = run_gem_backtest(
        close_prices[simple_universe], holding_simple,
        MAIN_START, MAIN_END
    )
    if result_simple_main:
        print(f"  年化收益: {result_simple_main['annual_return']}%")
        print(f"  总收益:   {result_simple_main['total_return']}%")
        print(f"  最大回撤: {result_simple_main['max_drawdown']}%")
        print(f"  夏普比率: {result_simple_main['sharpe']}")
        print(f"  持仓分布: {result_simple_main['holding_distribution']}")

    # ══════════════════════════════════════════════
    # B&H 基准对比
    # ══════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  📊 B&H 基准对比")
    print("=" * 80)

    bh_results = {}
    for sym in ['SPY', 'VEA', 'AGG', 'SHY', 'GLD', 'TLT', '60/40']:
        if sym == '60/40':
            # 60% SPY + 40% AGG
            spy_ret = close_prices['SPY'].pct_change().fillna(0)
            agg_ret = close_prices['AGG'].pct_change().fillna(0)
            combo_ret = 0.6 * spy_ret + 0.4 * agg_ret
            mask = (combo_ret.index >= MAIN_START) & (combo_ret.index <= MAIN_END)
            cr = combo_ret.loc[mask]
            n_years = len(cr) / 252
            cum = (1 + cr).cumprod()
            total_ret = (cum.iloc[-1] - 1) * 100
            annual_ret = ((1 + total_ret / 100) ** (1 / max(n_years, 0.01)) - 1) * 100
            running_max = cum.cummax()
            dd = (cum - running_max) / running_max
            max_dd = abs(dd.min()) * 100
            sharpe = cr.mean() / cr.std() * np.sqrt(252) if cr.std() > 0 else 0
            bh_results['60/40'] = {
                'annual_return': round(annual_ret, 2),
                'max_drawdown': round(max_dd, 2),
                'sharpe': round(sharpe, 2),
            }
            print(f"  60/40组合: 年化{annual_ret:.2f}%, 回撤{max_dd:.2f}%, 夏普{sharpe:.2f}")
        elif sym in close_prices.columns:
            bh = run_buy_hold_baseline(close_prices, sym, MAIN_START, MAIN_END)
            if bh:
                bh_results[sym] = bh
                print(f"  {sym} B&H: 年化{bh['annual_return']}%, 回撤{bh['max_drawdown']}%, 夏普{bh['sharpe']}")

    # ══════════════════════════════════════════════
    # 汇总输出
    # ══════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  📋 汇总对比")
    print("=" * 80)

    summary = []
    for label, result in [
        ('标准GEM(SPY/VEA/AGG/SHY)', result_std_main),
        ('扩展GEM(7资产)', result_ext_main),
        ('简化GEM(SPY/AGG/SHY)', result_simple_main),
    ]:
        if result:
            summary.append({
                '策略': label,
                '年化收益': f"{result['annual_return']}%",
                '最大回撤': f"{result['max_drawdown']}%",
                '夏普': result['sharpe'],
                '调整夏普': result['adj_sharpe'],
                '盈亏比': result['profit_factor'],
                '年调仓': result['avg_trades_per_year'],
            })

    for sym, bh in bh_results.items():
        summary.append({
            '策略': f'{sym} B&H',
            '年化收益': f"{bh['annual_return']}%",
            '最大回撤': f"{bh['max_drawdown']}%",
            '夏普': bh['sharpe'],
            '调整夏普': '-',
            '盈亏比': '-',
            '年调仓': '-',
        })

    df_summary = pd.DataFrame(summary)
    print(df_summary.to_string(index=False))

    # 保存结果JSON
    output = {
        'strategy_name': 'GEM双动量轮动策略',
        'strategy_type': '多资产轮动',
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'risk_free_rate': RISK_FREE_RATE,
        'fees': FEES,
        'slippage': SLIPPAGE,
        't_plus_1': True,
        'standard_gem': {
            'universe': standard_universe,
            'risk_assets': standard_risk,
            'safe_assets': standard_safe,
            'main_period': result_std_main,
            'stress_period': result_std_stress,
            'bull_period': result_std_bull,
        },
        'extended_gem': {
            'universe': available_extended,
            'risk_assets': [s for s in extended_risk if s in available_extended],
            'safe_assets': [s for s in extended_safe if s in available_extended],
            'main_period': result_ext_main,
            'stress_period': result_ext_stress,
        },
        'simple_gem': {
            'universe': simple_universe,
            'risk_assets': simple_risk,
            'safe_assets': simple_safe,
            'main_period': result_simple_main,
        },
        'buy_hold_baselines': bh_results,
        'comparison_table': summary,
    }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'gem_rotation_result.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 结果已保存至: {output_path}")

    return output


if __name__ == '__main__':
    main()
