#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEM双动量轮动策略 — 调仓频率对比回测
=====================================
对比日度/周度/双周/月度调仓频率对GEM策略的影响

核心问题：月度调仓是否太迟钝？日度/周度能否更快捕捉趋势变化？

测试矩阵：
  - 调仓频率: 日度(1d) / 周度(5d) / 双周(10d) / 月度(21d) / 季度(63d)
  - 回看期: 3M/6M/9M/12M
  - 资产池: 标准GEM(SPY/VEA/AGG/SHY) + 简化GEM(SPY/AGG/SHY)
  - 底仓模式: 0%(纯策略) / 50% SPY底仓
  - 年度分解 + 2022重点分析
"""

import json
import os
import sys
import warnings
from datetime import datetime
from itertools import product

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ================================================================
# 配置
# ================================================================
ETF_DATA_DIR = '/data/workspace/back_trader_stocks/etf'
INIT_CASH = 1_000_000
FEES = 0.001       # 手续费率（单边）
SLIPPAGE = 0.001   # 滑点
RISK_FREE_RATE = 0.045
MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'


# ================================================================
# 数据加载
# ================================================================
def load_etf_data(symbol: str) -> pd.DataFrame:
    filepath = os.path.join(ETF_DATA_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except:
        return None


# ================================================================
# 通用GEM策略 — 支持任意调仓频率
# ================================================================
def gem_rotation_with_freq(close_prices: pd.DataFrame,
                           risk_assets: list,
                           safe_assets: list,
                           lookback_months: int = 12,
                           rebalance_freq: int = 21,
                           holding_buffer_days: int = 0) -> pd.Series:
    """
    GEM双动量轮动策略 — 支持任意调仓频率
    
    参数:
      close_prices: 多资产收盘价 DataFrame
      risk_assets: 风险资产列表
      safe_assets: 安全资产列表
      lookback_months: 动量回看月数
      rebalance_freq: 调仓频率（交易日数），1=日度, 5=周度, 21=月度
      holding_buffer_days: 持仓缓冲天数（调仓后至少持N天不换仓），0=无缓冲
    
    逻辑:
      每隔 rebalance_freq 个交易日重新计算动量并决策
      若 holding_buffer_days > 0，则换仓后至少持 N 天不评估
    """
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    # 预计算所有日期的索引映射
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    
    # 生成调仓评估日
    eval_dates = set()
    last_eval = -rebalance_freq  # 确保第一天就评估
    
    for i in range(n_dates):
        if i - last_eval >= rebalance_freq:
            eval_dates.add(i)
            last_eval = i
    
    # 计算每日持仓
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]  # 初始持有最安全资产
    last_switch_day = -999  # 上次换仓日
    
    for i in range(n_dates):
        # 是否到达调仓评估日
        is_eval_day = i in eval_dates
        # 是否在缓冲期内
        in_buffer = (i - last_switch_day) < holding_buffer_days
        
        if is_eval_day and not in_buffer and i >= lookback_days:
            # 计算动量
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
            # 风险资产绝对动量
            risk_momentum = {}
            for asset in risk_assets:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        risk_momentum[asset] = curr / past - 1
            
            positive_risk = {k: v for k, v in risk_momentum.items() if v > 0}
            
            if positive_risk:
                new_asset = max(positive_risk, key=positive_risk.get)
            else:
                safe_momentum = {}
                for asset in safe_assets:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]
            
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
        
        holding.iloc[i] = current_asset
    
    return holding


# ================================================================
# 回测引擎
# ================================================================
def run_backtest(close_prices: pd.DataFrame, holding: pd.Series,
                 start_date: str, end_date: str,
                 init_cash: float = INIT_CASH,
                 fees: float = FEES, slippage: float = SLIPPAGE,
                 base_ratio: float = 0.0) -> dict:
    """
    执行回测，支持底仓模式
    
    base_ratio: 底仓比例（0=纯策略, 0.5=50%SPY底仓）
    
    注意：holding已包含shift(1)修正，模拟T日收盘计算信号、T+1日执行的真实场景
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    # shift(1)修正数据穿越：T日收盘计算信号，T+1日执行
    h = holding.shift(1).loc[mask]
    h.iloc[0] = holding.iloc[0] if pd.notna(holding.iloc[0]) else 'SHY'  # 首日填充
    
    if len(prices) < 100:
        return None
    
    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    prev_asset = None
    trade_count = 0
    
    for date in prices.index:
        current_asset = h.loc[date]
        
        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            portfolio_returns.loc[date] = r if pd.notna(r) else 0
        
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            portfolio_returns.loc[date] -= (fees + slippage)
        
        prev_asset = current_asset
    
    # 底仓模式
    if base_ratio > 0 and 'SPY' in daily_returns.columns:
        spy_returns = daily_returns['SPY'].fillna(0)
        portfolio_returns = base_ratio * spy_returns + (1 - base_ratio) * portfolio_returns
        # 底仓不需要调仓成本
    
    # 统计
    cum = (1 + portfolio_returns).cumprod()
    final_value = init_cash * cum.iloc[-1]
    n_years = len(prices) / 252
    total_return = (final_value / init_cash - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100
    
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100
    
    sharpe = portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    adj_sharpe = (portfolio_returns.mean() - RISK_FREE_RATE / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    
    # Calmar比率
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    win_days = (portfolio_returns > 0).sum()
    total_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_days, 1) * 100
    
    annual_trades = trade_count / max(n_years, 0.01)
    
    # 净交易成本（年化）
    annual_cost = trade_count * (fees + slippage) / max(n_years, 0.01) * 100  # 粗略年化成本%
    
    holding_counts = h.value_counts()
    holding_pcts = (holding_counts / len(h) * 100).to_dict()
    
    # 换仓率（持仓变动频率）
    switches = sum(1 for i in range(1, len(h)) if h.iloc[i] != h.iloc[i-1])
    switch_rate = switches / len(h) * 100  # 每日换仓概率
    
    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'adj_sharpe': round(adj_sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'total_trades': trade_count,
        'avg_trades_per_year': round(annual_trades, 1),
        'switch_rate': round(switch_rate, 2),
        'holding_distribution': {k: round(v, 1) for k, v in holding_pcts.items()},
        'final_value': round(final_value, 2),
        'n_years': round(n_years, 2),
    }


def run_yearly_breakdown(close_prices: pd.DataFrame, holding: pd.Series,
                         base_ratio: float = 0.0) -> dict:
    """年度分解"""
    years = {}
    for year in range(2019, 2025):
        start = f'{year}-01-01'
        end = f'{year}-12-31'
        result = run_backtest(close_prices, holding, start, end, base_ratio=base_ratio)
        if result:
            years[year] = result
    return years


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 100)
    print("  🔄 GEM双动量策略 — 调仓频率对比回测")
    print("=" * 100)
    
    # 加载数据
    print("\n📦 加载ETF数据...")
    etf_symbols = ['SPY', 'VEA', 'AGG', 'SHY']
    etf_data = {}
    for sym in etf_symbols:
        df = load_etf_data(sym)
        if df is not None:
            etf_data[sym] = df['Close']
            print(f"  ✅ {sym}")
    
    close_prices = pd.DataFrame(etf_data).dropna(how='all').sort_index().ffill().bfill()
    
    risk_assets = ['SPY', 'VEA']
    safe_assets = ['AGG', 'SHY']
    universe = risk_assets + safe_assets
    
    # ══════════════════════════════════════════════
    # 实验1: 调仓频率 vs 回看期 全矩阵
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  📊 实验1: 调仓频率 × 回看期 — 纯GEM策略")
    print("=" * 100)
    
    freqs = {
        '日度(1d)': 1,
        '周度(5d)': 5,
        '双周(10d)': 10,
        '月度(21d)': 21,
        '季度(63d)': 63,
    }
    lookbacks = [3, 6, 9, 12]
    
    results_matrix = []
    
    print(f"\n{'调仓频率':<12} {'回看期':<6} {'年化%':<8} {'回撤%':<8} {'夏普':<6} "
          f"{'调整夏普':<8} {'Calmar':<7} {'年调仓':<7} {'换仓率%':<8} {'SPY占比%':<9}")
    print("-" * 90)
    
    for freq_name, freq_val in freqs.items():
        for lb in lookbacks:
            holding = gem_rotation_with_freq(
                close_prices[universe], risk_assets, safe_assets,
                lookback_months=lb, rebalance_freq=freq_val
            )
            result = run_backtest(close_prices[universe], holding, MAIN_START, MAIN_END)
            if result:
                spy_pct = result['holding_distribution'].get('SPY', 0)
                results_matrix.append({
                    'freq': freq_name,
                    'freq_val': freq_val,
                    'lookback': lb,
                    **result
                })
                print(f"{freq_name:<12} {lb:<6}M {result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                      f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  {result['calmar']:>6.2f}  "
                      f"{result['avg_trades_per_year']:>6.1f}  {result['switch_rate']:>7.2f}  {spy_pct:>8.1f}")
    
    # ══════════════════════════════════════════════
    # 实验2: 最优组合 + 底仓模式
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  📊 实验2: 高分组合 + 50%底仓模式")
    print("=" * 100)
    
    # 选出实验1中的top组合
    sorted_results = sorted(results_matrix, key=lambda x: x.get('adj_sharpe', 0), reverse=True)
    top_combos = []
    seen = set()
    for r in sorted_results[:8]:
        key = (r['freq'], r['lookback'])
        if key not in seen:
            seen.add(key)
            top_combos.append(r)
    
    base_results = []
    print(f"\n{'调仓频率':<12} {'回看期':<6} {'底仓%':<6} {'年化%':<8} {'回撤%':<8} {'夏普':<6} "
          f"{'调整夏普':<8} {'Calmar':<7} {'年调仓':<7}")
    print("-" * 85)
    
    for combo in top_combos:
        freq_val = combo['freq_val']
        lb = combo['lookback']
        
        holding = gem_rotation_with_freq(
            close_prices[universe], risk_assets, safe_assets,
            lookback_months=lb, rebalance_freq=freq_val
        )
        
        for base_ratio in [0.0, 0.5]:
            result = run_backtest(
                close_prices[universe], holding, MAIN_START, MAIN_END,
                base_ratio=base_ratio
            )
            if result:
                base_results.append({
                    'freq': combo['freq'],
                    'lookback': lb,
                    'base_ratio': base_ratio,
                    **result
                })
                print(f"{combo['freq']:<12} {lb:<6}M {int(base_ratio*100):<6} "
                      f"{result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                      f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                      f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}")
    
    # ══════════════════════════════════════════════
    # 实验3: 持仓缓冲 — 减少日/周度调仓的过频换仓
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  📊 实验3: 日/周度调仓 + 持仓缓冲（换仓后至少持N天）")
    print("=" * 100)
    
    buffer_results = []
    print(f"\n{'调仓频率':<12} {'回看期':<6} {'缓冲天':<6} {'年化%':<8} {'回撤%':<8} {'夏普':<6} "
          f"{'调整夏普':<8} {'年调仓':<7} {'换仓率%':<8}")
    print("-" * 85)
    
    for freq_name, freq_val in [('日度(1d)', 1), ('周度(5d)', 5)]:
        for lb in [6, 9, 12]:
            for buffer in [3, 5, 10]:
                holding = gem_rotation_with_freq(
                    close_prices[universe], risk_assets, safe_assets,
                    lookback_months=lb, rebalance_freq=freq_val,
                    holding_buffer_days=buffer
                )
                result = run_backtest(close_prices[universe], holding, MAIN_START, MAIN_END)
                if result:
                    buffer_results.append({
                        'freq': freq_name,
                        'lookback': lb,
                        'buffer': buffer,
                        **result
                    })
                    print(f"{freq_name:<12} {lb:<6}M {buffer:<6} "
                          f"{result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                          f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                          f"{result['avg_trades_per_year']:>6.1f}  {result['switch_rate']:>7.2f}")
    
    # ══════════════════════════════════════════════
    # 实验4: 年度分解 — 重点看2022年
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  📊 实验4: 关键组合年度分解（2022年避险效果对比）")
    print("=" * 100)
    
    key_combos = [
        ('月度(21d)', 21, 12, 0, '月度12M'),
        ('周度(5d)', 5, 12, 0, '周度12M'),
        ('日度(1d)', 1, 12, 0, '日度12M'),
        ('周度(5d)', 5, 6, 0, '周度6M'),
        ('日度(1d)', 1, 6, 5, '日度6M+5d缓冲'),
        ('月度(21d)', 21, 12, 0, '月度12M+50%底仓'),
        ('周度(5d)', 5, 12, 0, '周度12M+50%底仓'),
    ]
    
    for label, freq_val, lb, buffer, desc in key_combos:
        base_ratio = 0.5 if '底仓' in desc else 0.0
        
        holding = gem_rotation_with_freq(
            close_prices[universe], risk_assets, safe_assets,
            lookback_months=lb, rebalance_freq=freq_val,
            holding_buffer_days=buffer
        )
        
        yearly = run_yearly_breakdown(close_prices[universe], holding, base_ratio=base_ratio)
        
        print(f"\n  📌 {desc}")
        print(f"  {'年份':<6} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'年调仓':<7}")
        for year in range(2019, 2025):
            if year in yearly:
                r = yearly[year]
                print(f"  {year:<6} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                      f"{r['sharpe']:>5.2f}  {r['avg_trades_per_year']:>6.1f}")
    
    # ══════════════════════════════════════════════
    # 实验5: 2022年逐月持仓切换对比
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  📊 实验5: 2022年逐月持仓 — 月度 vs 周度 vs 日度")
    print("=" * 100)
    
    for label, freq_val, lb in [('月度12M', 21, 12), ('周度12M', 5, 12), ('日度12M', 1, 12)]:
        holding = gem_rotation_with_freq(
            close_prices[universe], risk_assets, safe_assets,
            lookback_months=lb, rebalance_freq=freq_val
        )
        
        mask = (close_prices.index >= '2022-01-01') & (close_prices.index <= '2022-12-31')
        h = holding.loc[mask]
        daily_returns = close_prices[universe].loc[mask].pct_change().fillna(0)
        
        # 月度统计
        monthly_holding = h.resample('ME').last()
        print(f"\n  📌 {label} — 2022年月末持仓:")
        for date, asset in monthly_holding.items():
            if pd.notna(asset):
                month_mask = daily_returns.index.to_period('M') == date.to_period('M')
                if asset in daily_returns.columns:
                    asset_month_ret = (1 + daily_returns.loc[month_mask, asset]).prod() - 1
                    spy_month_ret = (1 + daily_returns.loc[month_mask, 'SPY']).prod() - 1
                    print(f"    {date.strftime('%Y-%m')}: 持有{asset:4s}  "
                          f"策略{asset_month_ret*100:+6.2f}%  SPY{spy_month_ret*100:+6.2f}%  "
                          f"超额{(asset_month_ret-spy_month_ret)*100:+6.2f}%")
    
    # ══════════════════════════════════════════════
    # 汇总排名
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  🏆 汇总排名 — 按调整夏普排序 TOP 15")
    print("=" * 100)
    
    all_results = results_matrix + base_results + buffer_results
    all_sorted = sorted(all_results, key=lambda x: x.get('adj_sharpe', -999), reverse=True)
    
    # 去重（同参数只保留最优底仓版本）
    seen_keys = set()
    unique_results = []
    for r in all_sorted:
        key = (r.get('freq', ''), r.get('lookback', ''), 
               r.get('base_ratio', 0), r.get('buffer', 0))
        if key not in seen_keys:
            seen_keys.add(key)
            unique_results.append(r)
    
    print(f"\n{'排名':<4} {'策略描述':<28} {'年化%':<8} {'回撤%':<8} {'夏普':<6} "
          f"{'调整夏普':<8} {'Calmar':<7} {'年调仓':<7}")
    print("-" * 85)
    
    for i, r in enumerate(unique_results[:15]):
        freq = r.get('freq', '')
        lb = r.get('lookback', '')
        base = f"+{int(r.get('base_ratio', 0)*100)}%底仓" if r.get('base_ratio', 0) > 0 else ''
        buf = f"+{r.get('buffer', 0)}d缓冲" if r.get('buffer', 0) > 0 else ''
        desc = f"{freq} {lb}M{base}{buf}"
        
        print(f"  {i+1:<3} {desc:<28} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
              f"{r['sharpe']:>5.2f}  {r['adj_sharpe']:>7.2f}  {r['calmar']:>6.2f}  "
              f"{r['avg_trades_per_year']:>6.1f}")
    
    # ══════════════════════════════════════════════
    # 结论
    # ══════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  📝 关键结论")
    print("=" * 100)
    
    # 找出日度vs月度的差异
    daily_12m = [r for r in results_matrix if r['freq_val'] == 1 and r['lookback'] == 12]
    monthly_12m = [r for r in results_matrix if r['freq_val'] == 21 and r['lookback'] == 12]
    weekly_12m = [r for r in results_matrix if r['freq_val'] == 5 and r['lookback'] == 12]
    
    if daily_12m and monthly_12m:
        d = daily_12m[0]
        m = monthly_12m[0]
        print(f"""
  📊 日度12M vs 月度12M:
     日度: 年化{d['annual_return']:+.2f}%, 回撤{d['max_drawdown']:.2f}%, 夏普{d['sharpe']:.2f}, 年调仓{d['avg_trades_per_year']:.1f}次
     月度: 年化{m['annual_return']:+.2f}%, 回撤{m['max_drawdown']:.2f}%, 夏普{m['sharpe']:.2f}, 年调仓{m['avg_trades_per_year']:.1f}次
     差异: 年化{d['annual_return']-m['annual_return']:+.2f}pp, 回撤{d['max_drawdown']-m['max_drawdown']:+.2f}pp, 夏普{d['sharpe']-m['sharpe']:+.2f}
""")
    
    if weekly_12m and monthly_12m:
        w = weekly_12m[0]
        m = monthly_12m[0]
        print(f"""  📊 周度12M vs 月度12M:
     周度: 年化{w['annual_return']:+.2f}%, 回撤{w['max_drawdown']:.2f}%, 夏普{w['sharpe']:.2f}, 年调仓{w['avg_trades_per_year']:.1f}次
     月度: 年化{m['annual_return']:+.2f}%, 回撤{m['max_drawdown']:.2f}%, 夏普{m['sharpe']:.2f}, 年调仓{m['avg_trades_per_year']:.1f}次
     差异: 年化{w['annual_return']-m['annual_return']:+.2f}pp, 回撤{w['max_drawdown']-m['max_drawdown']:+.2f}pp, 夏普{w['sharpe']-m['sharpe']:+.2f}
""")
    
    # 保存结果
    output = {
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'freq_matrix': results_matrix,
        'base_combos': base_results,
        'buffer_results': buffer_results,
        'top15_ranking': unique_results[:15],
    }
    
    output_path = '/data/workspace/strategy_arena/gem_freq_comparison_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 结果已保存至: {output_path}")


if __name__ == '__main__':
    main()
