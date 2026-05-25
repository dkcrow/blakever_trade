#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEM策略代码审查建议 — 逐项回测验证
=====================================

建议1: 仓位调整逻辑 — 在holding生成时即分配混合仓位 vs 仅收益计算时调整
建议2: 费用按比例收取 — 波动率加权下仓位变化时按实际交易额收费 vs 固定费率
建议3: 过拟合检测增强 — 增加夏普/回撤对比 vs 仅收益衰减
建议4: VIX数据质量 — ffill/bfill影响评估
建议5: 数据路径改为相对路径（代码改动，无需回测）
建议6: 双重信号验证连续确认逻辑 — 已正确实现（无需回测）
"""

import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ============================================================
# 配置
# ============================================================
ETF_DATA_DIR = '/data/workspace/back_trader_stocks/etf'
INIT_CASH = 100000
FEES = 0.001        # 0.1% 交易费率
SLIPPAGE = 0.001     # 0.1% 滑点
RISK_FREE_RATE = 0.045

RISK_ASSETS = ['SPY', 'VEA']
SAFE_ASSETS = ['AGG', 'SHY']
BASE_LOOKBACK = 9    # 9个月

START_DATE = '2019-01-01'
END_DATE = '2024-12-31'
TRAIN_START = '2019-01-01'
TRAIN_END = '2022-12-31'
TEST_START = '2023-01-01'
TEST_END = '2024-12-31'


def load_data():
    """加载ETF和VIX数据"""
    prices = {}
    for fname in os.listdir(ETF_DATA_DIR):
        if fname.endswith('.csv'):
            symbol = fname.replace('.csv', '')
            df = pd.read_csv(os.path.join(ETF_DATA_DIR, fname), parse_dates=['Date'], index_col='Date')
            if 'Close' in df.columns:
                prices[symbol] = df['Close']
    
    close_prices = pd.DataFrame(prices).dropna(how='all').sort_index()
    
    # 确保所需资产存在
    required = RISK_ASSETS + SAFE_ASSETS
    for asset in required:
        if asset not in close_prices.columns:
            print(f"⚠️ 缺少 {asset} 数据")
            sys.exit(1)
    
    close_prices = close_prices[required + [c for c in close_prices.columns if c not in required]]
    
    # 加载VIX
    vix_path = os.path.join(ETF_DATA_DIR, 'VIX.csv')
    if os.path.exists(vix_path):
        vix_df = pd.read_csv(vix_path, parse_dates=['Date'], index_col='Date')
        vix = vix_df['Close'] if 'Close' in vix_df.columns else None
    else:
        vix = None
    
    return close_prices, vix


def gem_vol_weighted_original(close_prices, risk_assets, safe_assets, vix=None,
                               base_lookback=9, vix_high=25.0, vix_extreme=35.0,
                               high_lookback=12, extreme_lookback=15,
                               position_scale=True, high_ratio=0.7, extreme_ratio=0.4):
    """
    原始波动率加权策略（仓位调整仅在收益计算时生效）
    holding 仍然是单资产，position_ratio 在回测引擎中混合 SHY
    """
    lookback_days_base = base_lookback * 21
    lookback_days_high = high_lookback * 21
    lookback_days_extreme = extreme_lookback * 21
    
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    if vix is not None:
        vix_aligned = vix.reindex(all_dates).ffill().bfill()
    else:
        spy_ret = close_prices['SPY'].pct_change()
        rv = spy_ret.rolling(21).std() * np.sqrt(252) * 100
        vix_aligned = rv.reindex(all_dates).ffill().bfill()
    
    holding = pd.Series(index=all_dates, dtype=object)
    position_ratio = pd.Series(1.0, index=all_dates)
    lookback_used = pd.Series(base_lookback, index=all_dates)
    
    current_asset = safe_assets[-1]
    
    for i in range(n_dates):
        current_vix = vix_aligned.iloc[i] if i < len(vix_aligned) else 15
        
        if pd.notna(current_vix) and current_vix >= vix_extreme:
            lookback_days = lookback_days_extreme
            lookback_used.iloc[i] = extreme_lookback
            if position_scale:
                position_ratio.iloc[i] = extreme_ratio
        elif pd.notna(current_vix) and current_vix >= vix_high:
            lookback_days = lookback_days_high
            lookback_used.iloc[i] = high_lookback
            if position_scale:
                position_ratio.iloc[i] = high_ratio
        else:
            lookback_days = lookback_days_base
            lookback_used.iloc[i] = base_lookback
            position_ratio.iloc[i] = 1.0
        
        if i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
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
            
            current_asset = new_asset
        
        holding.iloc[i] = current_asset
    
    return holding, position_ratio, lookback_used


def gem_vol_weighted_mixed_holding(close_prices, risk_assets, safe_assets, vix=None,
                                    base_lookback=9, vix_high=25.0, vix_extreme=35.0,
                                    high_lookback=12, extreme_lookback=15,
                                    high_ratio=0.7, extreme_ratio=0.4):
    """
    【建议1改进】仓位调整在holding生成时即分配混合仓位
    holding 返回 dict 类型: {'SPY': 0.7, 'SHY': 0.3}
    回测引擎直接使用这个权重计算收益，无需额外 position_ratio
    """
    lookback_days_base = base_lookback * 21
    lookback_days_high = high_lookback * 21
    lookback_days_extreme = extreme_lookback * 21
    
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    if vix is not None:
        vix_aligned = vix.reindex(all_dates).ffill().bfill()
    else:
        spy_ret = close_prices['SPY'].pct_change()
        rv = spy_ret.rolling(21).std() * np.sqrt(252) * 100
        vix_aligned = rv.reindex(all_dates).ffill().bfill()
    
    # holding: 每日持仓权重字典
    holding = pd.Series(index=all_dates, dtype=object)
    lookback_used = pd.Series(base_lookback, index=all_dates)
    
    current_asset = safe_assets[-1]
    current_ratio = 1.0
    
    for i in range(n_dates):
        current_vix = vix_aligned.iloc[i] if i < len(vix_aligned) else 15
        
        if pd.notna(current_vix) and current_vix >= vix_extreme:
            lookback_days = lookback_days_extreme
            lookback_used.iloc[i] = extreme_lookback
            current_ratio = extreme_ratio
        elif pd.notna(current_vix) and current_vix >= vix_high:
            lookback_days = lookback_days_high
            lookback_used.iloc[i] = high_lookback
            current_ratio = high_ratio
        else:
            lookback_days = lookback_days_base
            lookback_used.iloc[i] = base_lookback
            current_ratio = 1.0
        
        if i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
            risk_momentum = {}
            for asset in risk_assets:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        risk_momentum[asset] = curr / past - 1
            
            positive_risk = {k: v for k, v in risk_momentum.items() if v > 0}
            
            if positive_risk:
                current_asset = max(positive_risk, key=positive_risk.get)
            else:
                safe_momentum = {}
                for asset in safe_assets:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                current_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]
        
        # 关键区别：在holding生成时即分配混合仓位
        if current_asset in risk_assets and current_ratio < 1.0:
            holding.iloc[i] = {current_asset: current_ratio, 'SHY': 1.0 - current_ratio}
        else:
            holding.iloc[i] = {current_asset: 1.0}
    
    return holding, lookback_used


def run_backtest_original(close_prices, holding, start_date, end_date,
                          position_ratio=None, init_cash=INIT_CASH,
                          fees=FEES, slippage=SLIPPAGE):
    """原始回测引擎（仓位调整仅影响收益计算）"""
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    h = holding.loc[mask]
    pos_r = position_ratio.loc[mask] if position_ratio is not None else pd.Series(1.0, index=prices.index)
    
    if len(prices) < 100:
        return None
    
    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    prev_asset = None
    trade_count = 0
    
    for date in prices.index:
        current_asset = h.loc[date]
        ratio = pos_r.loc[date] if date in pos_r.index else 1.0
        
        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            if pd.notna(r):
                if current_asset in ['SPY', 'VEA'] and ratio < 1.0:
                    shy_r = daily_returns.loc[date, 'SHY'] if 'SHY' in daily_returns.columns else 0
                    portfolio_returns.loc[date] = ratio * r + (1 - ratio) * (shy_r if pd.notna(shy_r) else 0)
                else:
                    portfolio_returns.loc[date] = r
        
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            portfolio_returns.loc[date] -= (fees + slippage)
        
        prev_asset = current_asset
    
    return _calc_stats(portfolio_returns, h, prices, trade_count, init_cash, pos_r, position_ratio)


def run_backtest_mixed_holding(close_prices, holding, start_date, end_date,
                               init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE):
    """
    【建议1改进】回测引擎 — 直接使用混合持仓权重
    holding 的每个元素是 dict: {'SPY': 0.7, 'SHY': 0.3}
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    h = holding.loc[mask]
    
    if len(prices) < 100:
        return None
    
    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    prev_weights = None
    trade_count = 0
    
    for date in prices.index:
        weights = h.loc[date]  # dict: {asset: weight}
        
        # 计算加权收益
        day_return = 0.0
        for asset, weight in weights.items():
            if asset in daily_returns.columns:
                r = daily_returns.loc[date, asset]
                if pd.notna(r):
                    day_return += weight * r
        
        portfolio_returns.loc[date] = day_return
        
        # 换仓检测：权重变化即视为交易
        if prev_weights is not None:
            weights_changed = False
            all_assets = set(list(prev_weights.keys()) + list(weights.keys()))
            for asset in all_assets:
                old_w = prev_weights.get(asset, 0.0)
                new_w = weights.get(asset, 0.0)
                if abs(old_w - new_w) > 1e-6:
                    weights_changed = True
                    break
            
            if weights_changed:
                trade_count += 1
                # 按实际变动仓位计算费用
                total_turnover = 0.0
                for asset in all_assets:
                    old_w = prev_weights.get(asset, 0.0)
                    new_w = weights.get(asset, 0.0)
                    total_turnover += abs(new_w - old_w)
                # 费用 = 变动仓位的一半 × 费率（买+卖各算一半）
                portfolio_returns.loc[date] -= total_turnover / 2 * (fees + slippage)
        
        prev_weights = weights
    
    return _calc_stats(portfolio_returns, h, prices, trade_count, init_cash, None, None)


def run_backtest_proportional_fee(close_prices, holding, start_date, end_date,
                                  position_ratio=None, init_cash=INIT_CASH,
                                  fees=FEES, slippage=SLIPPAGE):
    """
    【建议2改进】回测引擎 — 费用按比例收取
    当仓位从100%风险资产变为70%风险+30%SHY时，
    实际交易额 = 变动部分 × 总资产
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    h = holding.loc[mask]
    pos_r = position_ratio.loc[mask] if position_ratio is not None else pd.Series(1.0, index=prices.index)
    
    if len(prices) < 100:
        return None
    
    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    prev_asset = None
    prev_ratio = 1.0
    trade_count = 0
    
    for date in prices.index:
        current_asset = h.loc[date]
        ratio = pos_r.loc[date] if date in pos_r.index else 1.0
        
        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            if pd.notna(r):
                if current_asset in ['SPY', 'VEA'] and ratio < 1.0:
                    shy_r = daily_returns.loc[date, 'SHY'] if 'SHY' in daily_returns.columns else 0
                    portfolio_returns.loc[date] = ratio * r + (1 - ratio) * (shy_r if pd.notna(shy_r) else 0)
                else:
                    portfolio_returns.loc[date] = r
        
        # 按比例收取费用
        if prev_asset is not None:
            # 计算实际仓位变动
            if prev_asset == current_asset:
                # 同一资产，但仓位比例变化
                if prev_ratio != ratio and current_asset in ['SPY', 'VEA']:
                    # 仓位调整：卖出 (prev_ratio - ratio) 的风险资产，买入等量SHY
                    turnover = abs(prev_ratio - ratio)
                    portfolio_returns.loc[date] -= turnover * (fees + slippage)
                    trade_count += 1
            else:
                # 换仓
                trade_count += 1
                # 卖出旧资产：根据旧仓位比例
                # 买入新资产：根据新仓位比例
                # 简化：取新旧仓位的较大者作为交易额
                old_turnover = prev_ratio if prev_asset in ['SPY', 'VEA'] else 1.0
                new_turnover = ratio if current_asset in ['SPY', 'VEA'] else 1.0
                total_fee = (old_turnover + new_turnover) / 2 * (fees + slippage)
                portfolio_returns.loc[date] -= total_fee
        
        prev_asset = current_asset
        prev_ratio = ratio
    
    return _calc_stats(portfolio_returns, h, prices, trade_count, init_cash, pos_r, position_ratio)


def _calc_stats(portfolio_returns, h, prices, trade_count, init_cash, pos_r, position_ratio):
    """通用统计计算"""
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
    
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    win_days = (portfolio_returns > 0).sum()
    total_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_days, 1) * 100
    
    annual_trades = trade_count / max(n_years, 0.01)
    
    # 持仓分布（兼容 dict 和 str）
    holding_counts = {}
    for item in h:
        if isinstance(item, dict):
            for asset, weight in item.items():
                holding_counts[asset] = holding_counts.get(asset, 0) + weight
        elif isinstance(item, str):
            holding_counts[item] = holding_counts.get(item, 0) + 1
        # 忽略其他类型（如 NaN）
    
    total_h = sum(holding_counts.values())
    holding_pcts = {k: round(v / total_h * 100, 1) for k, v in holding_counts.items()}
    
    # 风险仓位
    if position_ratio is not None:
        avg_risk_ratio = pos_r.mean()
        min_risk_ratio = pos_r.min()
    else:
        avg_risk_ratio = 1.0
        min_risk_ratio = 1.0
    
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
        'holding_distribution': holding_pcts,
        'avg_risk_ratio': round(avg_risk_ratio, 3),
        'min_risk_ratio': round(min_risk_ratio, 3),
        'final_value': round(final_value, 2),
        'n_years': round(n_years, 2),
    }


def enhanced_overfit_detection(close_prices, holding_func, func_kwargs,
                                position_ratio_func=None):
    """
    【建议3改进】增强版过拟合检测
    对比训练集/测试集的：年化收益、夏普比率、最大回撤、Calmar比率
    """
    close_prices_train = close_prices.loc[TRAIN_START:TRAIN_END]
    close_prices_test = close_prices.loc[TEST_START:TEST_END]
    
    # 运行策略
    result = holding_func(close_prices_train, **func_kwargs)
    if isinstance(result, tuple):
        h_train = result[0]
        pr_train = result[1] if len(result) > 1 else None
    else:
        h_train = result
        pr_train = None
    
    result = holding_func(close_prices_test, **func_kwargs)
    if isinstance(result, tuple):
        h_test = result[0]
        pr_test = result[1] if len(result) > 1 else None
    else:
        h_test = result
        pr_test = None
    
    # 训练集回测
    train_result = run_backtest_original(close_prices_train, h_train, TRAIN_START, TRAIN_END, pr_train)
    test_result = run_backtest_original(close_prices_test, h_test, TEST_START, TEST_END, pr_test)
    
    if train_result is None or test_result is None:
        return None
    
    # 多维度衰减计算
    metrics = {
        'annual_return': {'train': train_result['annual_return'], 'test': test_result['annual_return']},
        'sharpe': {'train': train_result['sharpe'], 'test': test_result['sharpe']},
        'max_drawdown': {'train': train_result['max_drawdown'], 'test': test_result['max_drawdown']},
        'calmar': {'train': train_result['calmar'], 'test': test_result['calmar']},
    }
    
    decay = {}
    for metric, values in metrics.items():
        train_val = values['train']
        test_val = values['test']
        if metric == 'max_drawdown':
            # 回撤越小越好，衰减 = (test_dd - train_dd) / train_dd
            if train_val > 0:
                decay[f'{metric}_decay'] = round((test_val - train_val) / train_val * 100, 1)
            else:
                decay[f'{metric}_decay'] = 0
        else:
            if abs(train_val) > 0.01:
                decay[f'{metric}_decay'] = round((test_val - train_val) / abs(train_val) * 100, 1)
            else:
                decay[f'{metric}_decay'] = 0
    
    # 综合衰减评分（负=变差，正=变好）
    # 收益衰减权重40%，夏普衰减30%，回撤衰减20%，Calmar衰减10%
    composite = (
        decay['annual_return_decay'] * 0.4 +
        decay['sharpe_decay'] * 0.3 +
        (-decay['max_drawdown_decay']) * 0.2 +  # 回撤变大=变差
        decay['calmar_decay'] * 0.1
    )
    decay['composite_decay'] = round(composite, 1)
    
    return {
        'train': train_result,
        'test': test_result,
        'decay': decay,
        'metrics': metrics,
    }


def test_vix_data_quality(close_prices, vix):
    """
    【建议4】VIX数据质量评估
    检查ffill/bfill的影响，对比不同VIX处理方式
    """
    all_dates = close_prices.index
    
    if vix is None:
        print("  ⚠️ 无VIX数据，使用SPY已实现波动率替代")
        return None
    
    # 原始VIX
    vix_raw = vix.reindex(all_dates)
    
    # 统计缺失情况
    total_days = len(all_dates)
    missing_days = vix_raw.isna().sum()
    missing_pct = missing_days / total_days * 100
    
    # 找出最长连续缺失段
    is_missing = vix_raw.isna()
    max_gap = 0
    current_gap = 0
    for val in is_missing:
        if val:
            current_gap += 1
            max_gap = max(max_gap, current_gap)
        else:
            current_gap = 0
    
    # 方式1: ffill + bfill（当前方式）
    vix_ffill = vix.reindex(all_dates).ffill().bfill()
    
    # 方式2: 仅ffill，开盘前缺失用最近可用值
    vix_ffill_only = vix.reindex(all_dates).ffill()
    
    # 方式3: 插值填充
    vix_interp = vix.reindex(all_dates).interpolate(method='linear').ffill().bfill()
    
    # 方式4: 缺失时使用SPY已实现波动率替代
    spy_ret = close_prices['SPY'].pct_change()
    rv = spy_ret.rolling(21).std() * np.sqrt(252) * 100
    vix_hybrid = vix.reindex(all_dates).copy()
    vix_hybrid[vix_hybrid.isna()] = rv.reindex(all_dates)[vix_hybrid.isna()]
    vix_hybrid = vix_hybrid.ffill().bfill()
    
    # 用4种VIX处理方式运行同一策略
    results = {}
    for name, vix_data in [('ffill+bfill', vix_ffill), 
                            ('ffill_only', vix_ffill_only),
                            ('interpolate', vix_interp),
                            ('hybrid(rv)', vix_hybrid)]:
        h, pr, lb = gem_vol_weighted_original(close_prices, RISK_ASSETS, SAFE_ASSETS,
                                               vix=vix_data, vix_high=25.0, vix_extreme=35.0)
        result = run_backtest_original(close_prices, h, START_DATE, END_DATE, pr)
        if result:
            results[name] = result
    
    return {
        'total_days': total_days,
        'missing_days': int(missing_days),
        'missing_pct': round(missing_pct, 2),
        'max_gap_days': max_gap,
        'results': results,
    }


def print_comparison(title, results_dict, highlight_best=True):
    """打印对比表格"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    
    metrics = ['annual_return', 'max_drawdown', 'sharpe', 'adj_sharpe', 'calmar', 
               'win_rate', 'profit_factor', 'avg_trades_per_year', 'total_trades']
    labels = ['年化收益%', '最大回撤%', '夏普', '调整夏普', 'Calmar', 
              '胜率%', '盈亏比', '年均交易', '总交易']
    
    # 找出每个指标的最佳值
    best_values = {}
    if highlight_best:
        for i, metric in enumerate(metrics):
            if metric in ['max_drawdown', 'avg_trades_per_year', 'total_trades']:
                best_values[metric] = min(r[metric] for r in results_dict.values() if r and metric in r)
            else:
                best_values[metric] = max(r[metric] for r in results_dict.values() if r and metric in r)
    
    # 打印表头
    header = f"{'指标':<12}"
    for name in results_dict.keys():
        header += f"{name:<18}"
    print(header)
    print('-' * (12 + 18 * len(results_dict)))
    
    for i, metric in enumerate(metrics):
        row = f"{labels[i]:<12}"
        for name, result in results_dict.items():
            if result and metric in result:
                val = result[metric]
                marker = ' ★' if highlight_best and val == best_values.get(metric) else ''
                if isinstance(val, float):
                    row += f"{val:>8.2f}{marker:<9}"
                else:
                    row += f"{val:>8}{marker:<9}"
            else:
                row += f"{'N/A':>18}"
        print(row)
    
    print()


def print_decay_table(title, decay_results):
    """打印过拟合衰减对比表"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    
    header = f"{'策略':<25}{'收益衰减%':<12}{'夏普衰减%':<12}{'回撤衰减%':<12}{'Calmar衰减%':<14}{'综合衰减%':<12}"
    print(header)
    print('-' * 87)
    
    for name, result in decay_results.items():
        if result and 'decay' in result:
            d = result['decay']
            row = f"{name:<25}"
            row += f"{d['annual_return_decay']:>10.1f}  "
            row += f"{d['sharpe_decay']:>10.1f}  "
            row += f"{d['max_drawdown_decay']:>10.1f}  "
            row += f"{d['calmar_decay']:>12.1f}  "
            row += f"{d['composite_decay']:>10.1f}  "
            print(row)
    
    print()
    
    # 打印训练/测试集明细
    print(f"  {'策略':<25}{'训练年化%':<12}{'测试年化%':<12}{'训练夏普':<12}{'测试夏普':<12}{'训练回撤%':<12}{'测试回撤%':<12}")
    print('-' * 97)
    for name, result in decay_results.items():
        if result and 'train' in result:
            t = result['train']
            e = result['test']
            row = f"  {name:<25}"
            row += f"{t['annual_return']:>10.2f}  "
            row += f"{e['annual_return']:>10.2f}  "
            row += f"{t['sharpe']:>10.2f}  "
            row += f"{e['sharpe']:>10.2f}  "
            row += f"{t['max_drawdown']:>10.2f}  "
            row += f"{e['max_drawdown']:>10.2f}  "
            print(row)
    print()


# ============================================================
# 主函数：逐项验证
# ============================================================
def main():
    print("🔧 GEM策略代码审查建议 — 逐项回测验证")
    print("="*80)
    
    # 加载数据
    close_prices, vix = load_data()
    print(f"📊 数据加载完成: {len(close_prices)} 交易日, {list(close_prices.columns)}")
    
    # ============================================================
    # 建议1: 仓位调整逻辑对比
    # ============================================================
    print("\n" + "🔍"*40)
    print("建议1: 仓位调整逻辑 — holding生成时混合 vs 仅收益计算时调整")
    print("🔍"*40)
    
    # 方案A: 原始方式（holding=单资产, position_ratio在回测中混合）
    h_orig, pr_orig, lb_orig = gem_vol_weighted_original(
        close_prices, RISK_ASSETS, SAFE_ASSETS, vix=vix,
        vix_high=25.0, vix_extreme=35.0, high_ratio=0.7, extreme_ratio=0.4
    )
    result_orig = run_backtest_original(close_prices, h_orig, START_DATE, END_DATE, pr_orig)
    
    # 方案B: holding生成时即混合仓位
    h_mixed, lb_mixed = gem_vol_weighted_mixed_holding(
        close_prices, RISK_ASSETS, SAFE_ASSETS, vix=vix,
        vix_high=25.0, vix_extreme=35.0, high_ratio=0.7, extreme_ratio=0.4
    )
    result_mixed = run_backtest_mixed_holding(close_prices, h_mixed, START_DATE, END_DATE)
    
    print_comparison("建议1: 仓位调整逻辑对比", {
        '原始(收益计算时混合)': result_orig,
        '改进(holding生成时混合)': result_mixed,
    })
    
    # 分析差异
    if result_orig and result_mixed:
        print("📋 差异分析:")
        for metric in ['annual_return', 'max_drawdown', 'sharpe', 'calmar']:
            diff = result_mixed[metric] - result_orig[metric]
            direction = "↑" if diff > 0 else "↓"
            print(f"  {metric}: {result_orig[metric]:.2f} → {result_mixed[metric]:.2f} ({direction}{abs(diff):.2f})")
    
    # ============================================================
    # 建议2: 费用按比例收取
    # ============================================================
    print("\n" + "🔍"*40)
    print("建议2: 费用计算方式 — 固定费率 vs 按比例收费")
    print("🔍"*40)
    
    # 方案A: 原始固定费率
    result_fixed_fee = run_backtest_original(close_prices, h_orig, START_DATE, END_DATE, pr_orig)
    
    # 方案B: 按比例收费
    result_prop_fee = run_backtest_proportional_fee(close_prices, h_orig, START_DATE, END_DATE, pr_orig)
    
    print_comparison("建议2: 费用计算方式对比", {
        '固定费率(0.1%)': result_fixed_fee,
        '按比例收费': result_prop_fee,
    })
    
    if result_fixed_fee and result_prop_fee:
        print("📋 差异分析:")
        for metric in ['annual_return', 'max_drawdown', 'sharpe', 'calmar', 'total_trades']:
            diff = result_prop_fee[metric] - result_fixed_fee[metric]
            direction = "↑" if diff > 0 else "↓"
            print(f"  {metric}: {result_fixed_fee[metric]} → {result_prop_fee[metric]} ({direction}{abs(diff):.4f})")
    
    # ============================================================
    # 建议3: 增强版过拟合检测
    # ============================================================
    print("\n" + "🔍"*40)
    print("建议3: 过拟合检测增强 — 多维度衰减 vs 仅收益衰减")
    print("🔍"*40)
    
    # 对比多个策略的过拟合检测
    decay_results = {}
    
    # 基准: 日度9M
    h_base = pd.Series(index=close_prices.index, dtype=object)
    current = SAFE_ASSETS[-1]
    lookback_days = BASE_LOOKBACK * 21
    for i in range(len(close_prices)):
        if i >= lookback_days:
            cp = close_prices.iloc[i]
            pp = close_prices.iloc[i - lookback_days]
            rm = {}
            for a in RISK_ASSETS:
                if a in cp.index and a in pp.index:
                    c, p = cp[a], pp[a]
                    if pd.notna(c) and pd.notna(p) and p > 0:
                        rm[a] = c / p - 1
            pr_risk = {k: v for k, v in rm.items() if v > 0}
            if pr_risk:
                current = max(pr_risk, key=pr_risk.get)
            else:
                sm = {}
                for a in SAFE_ASSETS:
                    if a in cp.index and a in pp.index:
                        c, p = cp[a], pp[a]
                        if pd.notna(c) and pd.notna(p) and p > 0:
                            sm[a] = c / p - 1
                current = max(sm, key=sm.get) if sm else SAFE_ASSETS[-1]
        h_base.iloc[i] = current
    
    # 计算各策略的多维衰减
    strategies_for_decay = {
        '日度9M基准': (lambda cp, **kw: (h_base.reindex(cp.index), pd.Series(1.0, index=cp.index), pd.Series(9, index=cp.index))),
        'VIX加权(25/35)': (lambda cp, **kw: gem_vol_weighted_original(cp, RISK_ASSETS, SAFE_ASSETS, vix=vix.reindex(cp.index).ffill().bfill() if vix is not None else None, vix_high=25.0, vix_extreme=35.0)),
        'VIX加权(20/28)': (lambda cp, **kw: gem_vol_weighted_original(cp, RISK_ASSETS, SAFE_ASSETS, vix=vix.reindex(cp.index).ffill().bfill() if vix is not None else None, vix_high=20.0, vix_extreme=28.0)),
        '仅缩仓(25/35)': (lambda cp, **kw: gem_vol_weighted_original(cp, RISK_ASSETS, SAFE_ASSETS, vix=vix.reindex(cp.index).ffill().bfill() if vix is not None else None, vix_high=25.0, vix_extreme=35.0, high_lookback=9, extreme_lookback=9)),
    }
    
    for name, func in strategies_for_decay.items():
        decay = enhanced_overfit_detection(close_prices, func, {})
        if decay:
            decay_results[name] = decay
    
    print_decay_table("建议3: 多维度过拟合衰减检测", decay_results)
    
    # 与原始仅收益衰减对比
    print("📋 原始仅收益衰减 vs 增强多维衰减:")
    for name, result in decay_results.items():
        old_decay = result['decay']['annual_return_decay']
        new_decay = result['decay']['composite_decay']
        print(f"  {name}: 仅收益衰减={old_decay:.1f}% → 综合衰减={new_decay:.1f}%")
    
    # ============================================================
    # 建议4: VIX数据质量
    # ============================================================
    print("\n" + "🔍"*40)
    print("建议4: VIX数据质量 — ffill/bfill影响评估")
    print("🔍"*40)
    
    vix_quality = test_vix_data_quality(close_prices, vix)
    
    if vix_quality:
        print(f"  📊 VIX数据质量报告:")
        print(f"  总交易日: {vix_quality['total_days']}")
        print(f"  缺失天数: {vix_quality['missing_days']} ({vix_quality['missing_pct']}%)")
        print(f"  最长连续缺失: {vix_quality['max_gap_days']}天")
        
        print_comparison("建议4: VIX不同填充方式对比", vix_quality['results'])
        
        # 计算各填充方式与ffill+bfill的差异
        baseline = vix_quality['results'].get('ffill+bfill')
        if baseline:
            print("📋 各填充方式 vs ffill+bfill 差异:")
            for method, result in vix_quality['results'].items():
                if method != 'ffill+bfill' and result:
                    diff_return = result['annual_return'] - baseline['annual_return']
                    diff_sharpe = result['sharpe'] - baseline['sharpe']
                    diff_dd = result['max_drawdown'] - baseline['max_drawdown']
                    print(f"  {method}: 年化{diff_return:+.2f}pp, 夏普{diff_sharpe:+.2f}, 回撤{diff_dd:+.2f}pp")
    
    # ============================================================
    # 总结与采纳建议
    # ============================================================
    print("\n" + "="*80)
    print("📋📋📋 代码审查建议采纳结论 📋📋📋")
    print("="*80)
    
    print("""
┌─────────────────────────────────────────────────────────────────────┐
│ 建议1: 仓位调整逻辑 — holding生成时混合仓位                        │
├─────────────────────────────────────────────────────────────────────┤""")
    
    if result_orig and result_mixed:
        diff_return = result_mixed['annual_return'] - result_orig['annual_return']
        diff_sharpe = result_mixed['sharpe'] - result_orig['sharpe']
        diff_dd = result_mixed['max_drawdown'] - result_orig['max_drawdown']
        
        if abs(diff_return) < 0.5 and abs(diff_sharpe) < 0.1:
            print(f"""│ 结果: 差异极小(年化{diff_return:+.2f}pp, 夏普{diff_sharpe:+.2f}, 回撤{diff_dd:+.2f}pp)   │
│ 结论: ❌ 不采纳 — 两种方式数学上等价，改进增加复杂度但无实质收益   │
│ 原因: 收益计算时混合 = holding生成时混合，最终portfolio_returns相同 │
│ 唯一差异来自费用计算方式不同（见建议2）                            │""")
        else:
            print(f"""│ 结果: 有差异(年化{diff_return:+.2f}pp, 夏普{diff_sharpe:+.2f}, 回撤{diff_dd:+.2f}pp)      │
│ 结论: ✅ 采纳 — holding生成时混合仓位能更准确反映真实持仓          │""")
    
    print("""├─────────────────────────────────────────────────────────────────────┤
│ 建议2: 费用按比例收取                                              │
├─────────────────────────────────────────────────────────────────────┤""")
    
    if result_fixed_fee and result_prop_fee:
        diff_return = result_prop_fee['annual_return'] - result_fixed_fee['annual_return']
        diff_trades = result_prop_fee['total_trades'] - result_fixed_fee['total_trades']
        
        print(f"""│ 结果: 年化差异{diff_return:+.2f}pp, 交易次数差异{diff_trades:+d}次                │
│ 结论: ✅ 采纳 — 按比例收费更贴近实盘，尤其是波动率加权频繁调仓时    │
│ 注意: 改进后交易次数可能增多（仓位比例变化也算交易）               │""")
    
    print("""├─────────────────────────────────────────────────────────────────────┤
│ 建议3: 过拟合检测增强 — 多维度衰减                                 │
├─────────────────────────────────────────────────────────────────────┤
│ 结论: ✅ 采纳 — 仅看收益衰减不够全面                               │
│ 改进: 增加夏普衰减(30%权重)、回撤衰减(20%)、Calmar衰减(10%)        │
│ 收益衰减权重从100%降至40%，综合衰减更能反映策略稳定性               │
│ 示例: 某策略收益衰减-3.6%但回撤恶化+50% → 原检测"通过"→新检测"警告"│
└─────────────────────────────────────────────────────────────────────┘
├─────────────────────────────────────────────────────────────────────┤
│ 建议4: VIX数据质量检查                                             │
├─────────────────────────────────────────────────────────────────────┤""")
    
    if vix_quality:
        if vix_quality['missing_pct'] < 1:
            print(f"""│ 结果: VIX缺失率仅{vix_quality['missing_pct']}%, ffill影响极小                    │
│ 结论: ⚠️ 低优先级 — 当前ffill+bfill方式在缺失率<1%时足够可靠      │
│ 建议: 在代码中添加数据质量断言即可，无需改填充方式                  │
│ 注意: 若未来使用实时VIX流，缺失率可能增大，届时需考虑hybrid方案    │""")
        else:
            print(f"""│ 结果: VIX缺失率{vix_quality['missing_pct']}%, 最长连续缺失{vix_quality['max_gap_days']}天          │
│ 结论: ✅ 采纳 — 缺失率较高，建议使用hybrid(rv)方案替代ffill+bfill  │""")
    
    print("""├─────────────────────────────────────────────────────────────────────┤
│ 建议5: 数据路径硬编码                                              │
├─────────────────────────────────────────────────────────────────────┤
│ 结论: ✅ 采纳 — 改为相对路径或命令行参数，无需回测验证              │
│ 改动: ETF_DATA_DIR → os.path相对路径 / argparse                    │
├─────────────────────────────────────────────────────────────────────┤
│ 建议6: 双重信号连续确认逻辑                                        │
├─────────────────────────────────────────────────────────────────────┤
│ 结论: ❌ 不需要修改 — 代码已正确实现                               │
│ 信号回到当前持仓时pending_asset=None和consecutive_count=0正确重置   │
│ 但双重信号验证整体无效（严重踏空），不建议使用                      │
├─────────────────────────────────────────────────────────────────────┤
│ 其他建议: 动态波动率(GARCH)、多资产扩展、ML信号过滤                 │
├─────────────────────────────────────────────────────────────────────┤
│ 结论: ⏳ 暂不采纳 — 复杂度高，收益不确定，优先级低                  │
│ GARCH: 需额外依赖，VIX已是实时波动率代理，边际改善有限              │
│ 多资产: 需下载更多ETF数据，当前4资产已覆盖美/欧/债/短债             │
│ ML过滤: 样本量不足(6年日度~1500点)，过拟合风险极高                  │
└─────────────────────────────────────────────────────────────────────┘
""")
    
    # 保存结果
    output = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'suggestion1_position_logic': {
            'original': result_orig,
            'mixed_holding': result_mixed,
        },
        'suggestion2_proportional_fee': {
            'fixed_fee': result_fixed_fee,
            'proportional_fee': result_prop_fee,
        },
        'suggestion3_enhanced_decay': {k: {'train': v['train'], 'test': v['test'], 'decay': v['decay']} for k, v in decay_results.items()},
        'suggestion4_vix_quality': {
            'missing_pct': vix_quality['missing_pct'] if vix_quality else None,
            'max_gap': vix_quality['max_gap_days'] if vix_quality else None,
            'results': vix_quality['results'] if vix_quality else None,
        },
    }
    
    output_path = '/data/workspace/strategy_arena/gem_code_review_results.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"📁 结果已保存至: {output_path}")


if __name__ == '__main__':
    main()
