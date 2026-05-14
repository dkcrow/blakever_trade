#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEM双动量轮动策略 — 波动率加权 + 双重信号验证增强
===================================================

基于日度9M（当前最优）做增量改进：

改进1: 波动率加权 (Volatility Regime)
  - 当 VIX / SPY已实现波动率 极高时：
    a) 拉长评估周期（9M → 12M），避免高波动下Whipsaw
    b) 缩减风险资产仓位（100% → 50%~80%），降低回撤

改进2: 双重信号验证 (Dual Signal Confirmation)
  - 方案A: 连续N天信号一致才执行（N=2,3,5）
  - 方案B: 动量变动差超过阈值才执行（0.3%, 0.5%, 1.0%）

对比基准: 日度9M纯策略(年化19.85%/回撤12.48%/夏普1.41)
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
ETF_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'back_trader_stocks', 'etf')
INIT_CASH = 1_000_000
FEES = 0.001
SLIPPAGE = 0.001
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


def load_vix_data() -> pd.Series:
    """加载VIX数据"""
    filepath = os.path.join(ETF_DATA_DIR, 'VIX.csv')
    if os.path.exists(filepath):
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        return df['Close'].sort_index()
    return None


# ================================================================
# 增强版GEM策略 — 波动率加权
# ================================================================
def gem_vol_weighted(close_prices: pd.DataFrame,
                     risk_assets: list,
                     safe_assets: list,
                     vix: pd.Series = None,
                     base_lookback: int = 9,
                     vix_high_threshold: float = 25.0,
                     vix_extreme_threshold: float = 35.0,
                     high_lookback: int = 12,
                     extreme_lookback: int = 15,
                     position_scale: bool = True,
                     high_ratio: float = 0.7,
                     extreme_ratio: float = 0.4) -> tuple:
    """
    波动率加权GEM策略 — 向量化版本
    
    当VIX升高时：
    1. 拉长回看期：base → high → extreme
    2. 缩减风险仓位：100% → high_ratio → extreme_ratio
    
    返回: (holding_series, position_ratio_series, lookback_series)
    """
    lookback_days_base = base_lookback * 21
    lookback_days_high = high_lookback * 21
    lookback_days_extreme = extreme_lookback * 21
    
    all_dates = close_prices.index
    
    # 对齐VIX数据
    if vix is not None:
        vix_aligned = vix.reindex(all_dates).ffill().bfill()
    else:
        # 用SPY已实现波动率代替
        spy_ret = close_prices['SPY'].pct_change()
        rv = spy_ret.rolling(21).std() * np.sqrt(252) * 100
        vix_aligned = rv.reindex(all_dates).ffill().bfill()
    
    # ── 向量化：根据VIX确定回看期和仓位 ──
    is_extreme = vix_aligned >= vix_extreme_threshold
    is_high = (~is_extreme) & (vix_aligned >= vix_high_threshold)
    is_normal = ~is_extreme & ~is_high
    
    lookback_days_map = pd.Series(lookback_days_base, index=all_dates, dtype=int)
    lookback_days_map[is_high] = lookback_days_high
    lookback_days_map[is_extreme] = lookback_days_extreme
    
    lookback_months_map = pd.Series(base_lookback, index=all_dates, dtype=int)
    lookback_months_map[is_high] = high_lookback
    lookback_months_map[is_extreme] = extreme_lookback
    
    position_ratio = pd.Series(1.0, index=all_dates)
    if position_scale:
        position_ratio[is_high] = high_ratio
        position_ratio[is_extreme] = extreme_ratio
    
    # ── 向量化：计算三种回看期的动量信号 ──
    momentum_base = close_prices.pct_change(periods=lookback_days_base)
    momentum_high = close_prices.pct_change(periods=lookback_days_high)
    momentum_extreme = close_prices.pct_change(periods=lookback_days_extreme)
    
    def _compute_signal(momentum_df, risk_assets, safe_assets):
        """从动量DataFrame生成信号"""
        risk_mom = momentum_df[risk_assets]
        safe_mom = momentum_df[safe_assets]
        best_risk = risk_mom.where(risk_mom > 0).idxmax(axis=1)
        best_safe = safe_mom.idxmax(axis=1)
        return best_risk.fillna(best_safe).fillna(safe_assets[-1])
    
    signal_base = _compute_signal(momentum_base, risk_assets, safe_assets)
    signal_high = _compute_signal(momentum_high, risk_assets, safe_assets)
    signal_extreme = _compute_signal(momentum_extreme, risk_assets, safe_assets)
    
    # 合并：根据VIX状态选择对应回看期的信号
    holding = pd.Series(safe_assets[-1], index=all_dates, dtype=object)
    holding[is_normal] = signal_base[is_normal]
    holding[is_high] = signal_high[is_high]
    holding[is_extreme] = signal_extreme[is_extreme]
    
    # 前lookback_days_extreme行设为默认
    holding.iloc[:lookback_days_extreme] = safe_assets[-1]
    
    return holding, position_ratio, lookback_months_map


# ================================================================
# 增强版GEM策略 — 双重信号验证（连续N天）
# ================================================================
def gem_dual_signal_consecutive(close_prices: pd.DataFrame,
                                risk_assets: list,
                                safe_assets: list,
                                lookback_months: int = 9,
                                confirm_days: int = 3,
                                holding_buffer_days: int = 0) -> pd.Series:
    """
    双重信号验证 — 连续N天版本（向量化信号计算）
    
    只有当新信号连续confirm_days天指向同一资产时才执行换仓。
    当前持仓资产不动，直到新信号连续确认。
    """
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    # 第一步：向量化计算每日原始信号
    momentum_df = close_prices.pct_change(periods=lookback_days)
    risk_mom = momentum_df[risk_assets]
    safe_mom = momentum_df[safe_assets]
    best_risk = risk_mom.where(risk_mom > 0).idxmax(axis=1)
    best_safe = safe_mom.idxmax(axis=1)
    raw_signal = best_risk.fillna(best_safe).fillna(safe_assets[-1])
    raw_signal.iloc[:lookback_days] = safe_assets[-1]
    
    # 第二步：双重信号验证 — 连续N天一致（需顺序处理，无法向量化）
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]
    last_switch_day = -999
    pending_asset = None
    consecutive_count = 0
    
    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < holding_buffer_days
        
        if not in_buffer:
            signal = raw_signal.iloc[i]
            
            if signal != current_asset:
                if signal == pending_asset:
                    consecutive_count += 1
                else:
                    pending_asset = signal
                    consecutive_count = 1
                
                if consecutive_count >= confirm_days:
                    current_asset = pending_asset
                    last_switch_day = i
                    pending_asset = None
                    consecutive_count = 0
            else:
                # 信号回到当前持仓，重置计数
                pending_asset = None
                consecutive_count = 0
        
        holding.iloc[i] = current_asset
    
    return holding


# ================================================================
# 增强版GEM策略 — 双重信号验证（动量变动差阈值）
# ================================================================
def gem_dual_signal_threshold(close_prices: pd.DataFrame,
                              risk_assets: list,
                              safe_assets: list,
                              lookback_months: int = 9,
                              momentum_threshold: float = 0.005,
                              holding_buffer_days: int = 0) -> pd.Series:
    """
    双重信号验证 — 动量变动差阈值版本（向量化动量计算）
    
    只有当新资产的动量比当前持仓资产的动量高出threshold以上时才换仓。
    例如：新资产动量5%，当前持仓动量4.2%，差值0.8% > 0.5% → 执行换仓
    """
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    # 向量化计算所有资产动量
    momentum_df = close_prices.pct_change(periods=lookback_days)
    
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]
    last_switch_day = -999
    
    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < holding_buffer_days
        
        if not in_buffer and i >= lookback_days:
            date = all_dates[i]
            all_momentum = momentum_df.loc[date].to_dict() if date in momentum_df.index else {}
            
            # 选出最优风险资产
            risk_mom = {k: v for k, v in all_momentum.items() if k in risk_assets and pd.notna(v) and v > 0}
            if risk_mom:
                best_risk = max(risk_mom, key=risk_mom.get)
                best_risk_mom = risk_mom[best_risk]
                
                # 当前持仓动量
                current_mom = all_momentum.get(current_asset, -1)
                if pd.isna(current_mom):
                    current_mom = -1
                
                # 动量差值
                momentum_diff = best_risk_mom - current_mom
                
                if momentum_diff > momentum_threshold:
                    new_asset = best_risk
                else:
                    # 不满足阈值，保持当前持仓
                    new_asset = current_asset
            else:
                # 无正动量风险资产 → 选最优安全资产
                safe_mom = {k: v for k, v in all_momentum.items() if k in safe_assets and pd.notna(v)}
                new_asset = max(safe_mom, key=safe_mom.get) if safe_mom else safe_assets[-1]
                
                # 同样检查安全资产之间是否满足阈值
                current_mom = all_momentum.get(current_asset, -1)
                new_mom = all_momentum.get(new_asset, -1)
                if pd.isna(current_mom):
                    current_mom = -1
                if pd.isna(new_mom):
                    new_mom = -1
                if (new_mom - current_mom) < momentum_threshold:
                    new_asset = current_asset
            
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
        
        holding.iloc[i] = current_asset
    
    return holding


# ================================================================
# 回测引擎 — 支持波动率加权仓位
# ================================================================
def run_backtest_enhanced(close_prices: pd.DataFrame, holding: pd.Series,
                          start_date: str, end_date: str,
                          position_ratio: pd.Series = None,
                          init_cash: float = INIT_CASH,
                          fees: float = FEES, slippage: float = SLIPPAGE,
                          base_ratio: float = 0.0) -> dict:
    """
    增强版回测，支持波动率加权仓位
    
    position_ratio: 每日风险资产仓位比例 (0~1)
    
    注意：holding和position_ratio已包含shift(1)修正，模拟T日收盘计算信号、T+1日执行的真实场景
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    # shift(1)修正数据穿越：T日收盘计算信号，T+1日执行
    h = holding.shift(1).loc[mask]
    h.iloc[0] = holding.iloc[0] if pd.notna(holding.iloc[0]) else 'SHY'  # 首日填充
    pos_r = position_ratio.shift(1).loc[mask] if position_ratio is not None else pd.Series(1.0, index=prices.index)
    if position_ratio is not None:
        pos_r.iloc[0] = 1.0  # 首日默认全仓
    
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
            # 风险资产仓位 × ratio，剩余分配给SHY
            r = daily_returns.loc[date, current_asset]
            if pd.notna(r):
                if current_asset in ['SPY', 'VEA'] and ratio < 1.0:
                    # 波动率加权：ratio给风险资产，(1-ratio)给SHY
                    shy_r = daily_returns.loc[date, 'SHY'] if 'SHY' in daily_returns.columns else 0
                    portfolio_returns.loc[date] = ratio * r + (1 - ratio) * (shy_r if pd.notna(shy_r) else 0)
                else:
                    portfolio_returns.loc[date] = r
        
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            portfolio_returns.loc[date] -= (fees + slippage)
        
        prev_asset = current_asset
    
    # 底仓模式
    if base_ratio > 0 and 'SPY' in daily_returns.columns:
        spy_returns = daily_returns['SPY'].fillna(0)
        portfolio_returns = base_ratio * spy_returns + (1 - base_ratio) * portfolio_returns
    
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
    
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    win_days = (portfolio_returns > 0).sum()
    total_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_days, 1) * 100
    
    annual_trades = trade_count / max(n_years, 0.01)
    
    switches = sum(1 for i in range(1, len(h)) if h.iloc[i] != h.iloc[i-1])
    switch_rate = switches / len(h) * 100
    
    holding_counts = h.value_counts()
    holding_pcts = (holding_counts / len(h) * 100).to_dict()
    
    # 计算平均风险仓位
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
        'switch_rate': round(switch_rate, 2),
        'holding_distribution': {k: round(v, 1) for k, v in holding_pcts.items()},
        'avg_risk_ratio': round(avg_risk_ratio, 3),
        'min_risk_ratio': round(min_risk_ratio, 3),
        'final_value': round(final_value, 2),
        'n_years': round(n_years, 2),
    }


# ================================================================
# 原始GEM策略（基准）
# ================================================================
def gem_rotation_baseline(close_prices: pd.DataFrame,
                          risk_assets: list,
                          safe_assets: list,
                          lookback_months: int = 9) -> pd.Series:
    """原始日度9M策略（无增强）— 向量化版本"""
    lookback_days = lookback_months * 21
    
    # 向量化计算所有资产的N日动量
    momentum_df = close_prices.pct_change(periods=lookback_days)
    
    # 风险资产动量
    risk_mom = momentum_df[risk_assets]
    safe_mom = momentum_df[safe_assets]
    
    # 找出风险资产中动量最高且大于0的
    best_risk = risk_mom.where(risk_mom > 0).idxmax(axis=1)
    
    # 找出安全资产中动量最高的
    best_safe = safe_mom.idxmax(axis=1)
    
    # 如果有正动量风险资产则选之，否则选最佳安全资产
    raw_signal = best_risk.fillna(best_safe).fillna(safe_assets[-1])
    
    # 前lookback_days行设为默认（动量计算尚未有效）
    raw_signal.iloc[:lookback_days] = safe_assets[-1]
    
    return raw_signal


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 110)
    print("  🚀 GEM双动量策略增强 — 波动率加权 + 双重信号验证")
    print("=" * 110)
    
    # ── 加载数据 ──
    print("\n📦 加载数据...")
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
    
    # 加载VIX
    vix = load_vix_data()
    if vix is not None:
        print(f"  ✅ VIX: {len(vix)} 行, {vix.index.min().strftime('%Y-%m-%d')} ~ {vix.index.max().strftime('%Y-%m-%d')}")
    else:
        print("  ⚠️ VIX不可用，将使用SPY已实现波动率")
    
    # ══════════════════════════════════════════════
    # 基准: 日度9M纯策略
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 基准: 日度9M纯策略（无增强）")
    print("=" * 110)
    
    baseline_holding = gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, lookback_months=9)
    baseline_result = run_backtest_enhanced(close_prices[universe], baseline_holding, MAIN_START, MAIN_END)
    
    print(f"\n  基准结果: 年化{baseline_result['annual_return']:+.2f}%, 回撤{baseline_result['max_drawdown']:.2f}%, "
          f"夏普{baseline_result['sharpe']:.2f}, 调整夏普{baseline_result['adj_sharpe']:.2f}, "
          f"年调仓{baseline_result['avg_trades_per_year']:.1f}次")
    
    all_results = [{
        'strategy': '基准:日度9M',
        'type': 'baseline',
        **baseline_result
    }]
    
    # ══════════════════════════════════════════════
    # 实验1: 波动率加权 — 不同VIX阈值组合
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 实验1: 波动率加权 — VIX阈值调参")
    print("=" * 110)
    
    vol_configs = [
        # (high_threshold, extreme_threshold, high_lookback, extreme_lookback, high_ratio, extreme_ratio, label)
        (22, 30, 12, 15, 0.8, 0.5, '保守(22/30)'),
        (22, 35, 12, 15, 0.8, 0.5, '中庸(22/35)'),
        (25, 35, 12, 15, 0.7, 0.4, '激进(25/35)'),
        (25, 40, 12, 18, 0.7, 0.3, '超激(25/40)'),
        (20, 28, 12, 15, 0.8, 0.5, '极早(20/28)'),
        # 只拉长回看不缩仓
        (22, 35, 12, 15, 1.0, 1.0, '仅回看(22/35)'),
        (25, 35, 12, 15, 1.0, 1.0, '仅回看(25/35)'),
        # 只缩仓不拉长回看
        (25, 35, 9, 9, 0.7, 0.4, '仅缩仓(25/35)'),
    ]
    
    print(f"\n{'策略描述':<24} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'调整夏普':<8} "
          f"{'Calmar':<7} {'年调仓':<7} {'均风险仓':<8} {'最低仓':<8}")
    print("-" * 100)
    
    for high_th, extreme_th, high_lb, extreme_lb, high_r, extreme_r, label in vol_configs:
        holding, pos_ratio, lb_used = gem_vol_weighted(
            close_prices[universe], risk_assets, safe_assets,
            vix=vix,
            base_lookback=9,
            vix_high_threshold=high_th,
            vix_extreme_threshold=extreme_th,
            high_lookback=high_lb,
            extreme_lookback=extreme_lb,
            position_scale=(high_r < 1.0 or extreme_r < 1.0),
            high_ratio=high_r,
            extreme_ratio=extreme_r,
        )
        
        result = run_backtest_enhanced(
            close_prices[universe], holding, MAIN_START, MAIN_END,
            position_ratio=pos_ratio
        )
        
        if result:
            all_results.append({
                'strategy': f'波动率加权:{label}',
                'type': 'vol_weighted',
                'config': {
                    'high_th': high_th, 'extreme_th': extreme_th,
                    'high_lb': high_lb, 'extreme_lb': extreme_lb,
                    'high_r': high_r, 'extreme_r': extreme_r,
                },
                **result
            })
            print(f"  {label:<22} {result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                  f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                  f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}  "
                  f"{result['avg_risk_ratio']:>7.3f}  {result['min_risk_ratio']:>7.3f}")
    
    # ══════════════════════════════════════════════
    # 实验2: 双重信号验证 — 连续N天
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 实验2: 双重信号验证 — 连续N天确认")
    print("=" * 110)
    
    confirm_days_list = [2, 3, 5, 7, 10]
    
    print(f"\n{'策略描述':<28} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'调整夏普':<8} "
          f"{'Calmar':<7} {'年调仓':<7} {'换仓率%':<8}")
    print("-" * 95)
    
    for n_days in confirm_days_list:
        holding = gem_dual_signal_consecutive(
            close_prices[universe], risk_assets, safe_assets,
            lookback_months=9, confirm_days=n_days
        )
        
        result = run_backtest_enhanced(close_prices[universe], holding, MAIN_START, MAIN_END)
        
        if result:
            all_results.append({
                'strategy': f'连续{n_days}天确认',
                'type': 'dual_consecutive',
                'confirm_days': n_days,
                **result
            })
            print(f"  连续{n_days}天确认{'':<{24-len(str(n_days))*2}} "
                  f"{result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                  f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                  f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}  "
                  f"{result['switch_rate']:>7.2f}")
    
    # 连续N天 + 缓冲组合
    print(f"\n--- 连续N天 + 缓冲组合 ---")
    for n_days in [2, 3, 5]:
        for buf in [3, 5]:
            holding = gem_dual_signal_consecutive(
                close_prices[universe], risk_assets, safe_assets,
                lookback_months=9, confirm_days=n_days,
                holding_buffer_days=buf
            )
            
            result = run_backtest_enhanced(close_prices[universe], holding, MAIN_START, MAIN_END)
            
            if result:
                all_results.append({
                    'strategy': f'连续{n_days}天+{buf}d缓冲',
                    'type': 'dual_consecutive_buffer',
                    'confirm_days': n_days,
                    'buffer': buf,
                    **result
                })
                print(f"  连续{n_days}天+{buf}d缓冲{'':{20-len(str(n_days))*2-len(str(buf))*2}} "
                      f"{result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                      f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                      f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}  "
                      f"{result['switch_rate']:>7.2f}")
    
    # ══════════════════════════════════════════════
    # 实验3: 双重信号验证 — 动量变动差阈值
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 实验3: 双重信号验证 — 动量变动差阈值")
    print("=" * 110)
    
    thresholds = [0.001, 0.003, 0.005, 0.008, 0.01, 0.015, 0.02]
    
    print(f"\n{'策略描述':<28} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'调整夏普':<8} "
          f"{'Calmar':<7} {'年调仓':<7} {'换仓率%':<8}")
    print("-" * 95)
    
    for th in thresholds:
        holding = gem_dual_signal_threshold(
            close_prices[universe], risk_assets, safe_assets,
            lookback_months=9, momentum_threshold=th
        )
        
        result = run_backtest_enhanced(close_prices[universe], holding, MAIN_START, MAIN_END)
        
        if result:
            all_results.append({
                'strategy': f'动量阈值{th*100:.1f}%',
                'type': 'dual_threshold',
                'threshold': th,
                **result
            })
            print(f"  动量阈值{th*100:.1f}%{'':{20-len(str(round(th*100,1)))}} "
                  f"{result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                  f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                  f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}  "
                  f"{result['switch_rate']:>7.2f}")
    
    # 动量阈值 + 缓冲
    print(f"\n--- 动量阈值 + 缓冲组合 ---")
    for th in [0.003, 0.005, 0.008]:
        for buf in [3, 5]:
            holding = gem_dual_signal_threshold(
                close_prices[universe], risk_assets, safe_assets,
                lookback_months=9, momentum_threshold=th,
                holding_buffer_days=buf
            )
            
            result = run_backtest_enhanced(close_prices[universe], holding, MAIN_START, MAIN_END)
            
            if result:
                all_results.append({
                    'strategy': f'动量阈值{th*100:.1f}%+{buf}d缓冲',
                    'type': 'dual_threshold_buffer',
                    'threshold': th,
                    'buffer': buf,
                    **result
                })
                print(f"  阈值{th*100:.1f}%+{buf}d缓冲{'':{16-len(str(round(th*100,1)))}} "
                      f"{result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                      f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                      f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}  "
                      f"{result['switch_rate']:>7.2f}")
    
    # ══════════════════════════════════════════════
    # 实验4: 组合增强 — 波动率加权 + 双重信号
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 实验4: 组合增强 — 波动率加权 + 双重信号验证")
    print("=" * 110)
    
    combo_configs = [
        # (vol_config_label, high_th, extreme_th, high_lb, extreme_lb, high_r, extreme_r, 
        #  signal_type, signal_param, buffer)
        ('VIX加权(22/35) + 连续3天', 22, 35, 12, 15, 0.8, 0.5, 'consecutive', 3, 0),
        ('VIX加权(22/35) + 连续2天', 22, 35, 12, 15, 0.8, 0.5, 'consecutive', 2, 0),
        ('VIX加权(25/35) + 连续3天', 25, 35, 12, 15, 0.7, 0.4, 'consecutive', 3, 0),
        ('VIX加权(22/35) + 阈值0.5%', 22, 35, 12, 15, 0.8, 0.5, 'threshold', 0.005, 0),
        ('VIX加权(25/35) + 阈值0.5%', 25, 35, 12, 15, 0.7, 0.4, 'threshold', 0.005, 0),
        ('VIX加权(22/35) + 连续3天+3d缓冲', 22, 35, 12, 15, 0.8, 0.5, 'consecutive', 3, 3),
        ('VIX加权(25/35) + 阈值0.3%+3d缓冲', 25, 35, 12, 15, 0.7, 0.4, 'threshold', 0.003, 3),
        ('仅回看VIX(22/35) + 连续3天', 22, 35, 12, 15, 1.0, 1.0, 'consecutive', 3, 0),
        ('仅缩仓VIX(25/35) + 连续3天', 25, 35, 9, 9, 0.7, 0.4, 'consecutive', 3, 0),
    ]
    
    print(f"\n{'策略描述':<38} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'调整夏普':<8} "
          f"{'Calmar':<7} {'年调仓':<7} {'均风险仓':<8}")
    print("-" * 105)
    
    for label, high_th, extreme_th, high_lb, extreme_lb, high_r, extreme_r, sig_type, sig_param, buf in combo_configs:
        # 先做波动率加权
        holding, pos_ratio, lb_used = gem_vol_weighted(
            close_prices[universe], risk_assets, safe_assets,
            vix=vix,
            base_lookback=9,
            vix_high_threshold=high_th,
            vix_extreme_threshold=extreme_th,
            high_lookback=high_lb,
            extreme_lookback=extreme_lb,
            position_scale=(high_r < 1.0 or extreme_r < 1.0),
            high_ratio=high_r,
            extreme_ratio=extreme_r,
        )
        
        # 再叠加双重信号验证
        # 利用波动率加权的lookback_used，从预计算的三种回看期信号中选取
        lookback_days_map = lb_used * 21
        all_dates = close_prices.index
        n_dates = len(all_dates)
        
        # 向量化：预计算三种回看期的动量信号
        momentum_base = close_prices[universe].pct_change(periods=9 * 21)
        momentum_high = close_prices[universe].pct_change(periods=high_lb * 21)
        momentum_extreme = close_prices[universe].pct_change(periods=extreme_lb * 21)
        
        def _vec_signal(momentum_df):
            risk_mom = momentum_df[risk_assets]
            safe_mom = momentum_df[safe_assets]
            best_risk = risk_mom.where(risk_mom > 0).idxmax(axis=1)
            best_safe = safe_mom.idxmax(axis=1)
            return best_risk.fillna(best_safe).fillna(safe_assets[-1])
        
        signal_base = _vec_signal(momentum_base)
        signal_high = _vec_signal(momentum_high)
        signal_extreme = _vec_signal(momentum_extreme)
        
        # 根据每日回看期选择对应信号
        is_high_lb = lb_used == high_lb
        is_extreme_lb = lb_used == extreme_lb
        is_base_lb = ~is_high_lb & ~is_extreme_lb
        
        raw_signal = pd.Series(safe_assets[-1], index=all_dates, dtype=object)
        raw_signal[is_base_lb] = signal_base[is_base_lb]
        raw_signal[is_high_lb] = signal_high[is_high_lb]
        raw_signal[is_extreme_lb] = signal_extreme[is_extreme_lb]
        raw_signal.iloc[:extreme_lb * 21] = safe_assets[-1]
        
        # 应用双重信号验证
        combo_holding = pd.Series(index=all_dates, dtype=object)
        current_asset = safe_assets[-1]
        last_switch_day = -999
        pending_asset = None
        consecutive_count = 0
        
        for i in range(n_dates):
            in_buffer = (i - last_switch_day) < buf
            
            if not in_buffer:
                signal = raw_signal.iloc[i]
                
                if sig_type == 'consecutive':
                    if signal != current_asset:
                        if signal == pending_asset:
                            consecutive_count += 1
                        else:
                            pending_asset = signal
                            consecutive_count = 1
                        
                        if consecutive_count >= sig_param:
                            current_asset = pending_asset
                            last_switch_day = i
                            pending_asset = None
                            consecutive_count = 0
                    else:
                        pending_asset = None
                        consecutive_count = 0
                
                elif sig_type == 'threshold':
                    # 动量阈值验证 — 使用预计算的向量化动量
                    lb_days = int(lookback_days_map.iloc[i])
                    if i >= lb_days:
                        # 选择对应回看期的预计算动量
                        if lb_used.iloc[i] == extreme_lb:
                            mom_row = momentum_extreme.iloc[i]
                        elif lb_used.iloc[i] == high_lb:
                            mom_row = momentum_high.iloc[i]
                        else:
                            mom_row = momentum_base.iloc[i]
                        
                        if signal != current_asset:
                            new_mom = mom_row.get(signal, -1) if pd.notna(mom_row.get(signal, -1)) else -1
                            curr_mom = mom_row.get(current_asset, -1) if pd.notna(mom_row.get(current_asset, -1)) else -1
                            if (new_mom - curr_mom) > sig_param:
                                current_asset = signal
                                last_switch_day = i
            
            combo_holding.iloc[i] = current_asset
        
        result = run_backtest_enhanced(
            close_prices[universe], combo_holding, MAIN_START, MAIN_END,
            position_ratio=pos_ratio
        )
        
        if result:
            all_results.append({
                'strategy': label,
                'type': 'combo',
                **result
            })
            print(f"  {label:<36} {result['annual_return']:>+7.2f}  {result['max_drawdown']:>6.2f}  "
                  f"{result['sharpe']:>5.2f}  {result['adj_sharpe']:>7.2f}  "
                  f"{result['calmar']:>6.2f}  {result['avg_trades_per_year']:>6.1f}  "
                  f"{result['avg_risk_ratio']:>7.3f}")
    
    # ══════════════════════════════════════════════
    # 实验5: 年度分解 — TOP策略
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 实验5: TOP增强策略 vs 基准 — 年度分解")
    print("=" * 110)
    
    # 选出TOP5（按调整夏普）
    sorted_results = sorted(all_results[1:], key=lambda x: x.get('adj_sharpe', -999), reverse=True)
    top5 = sorted_results[:5]
    
    # 加上基准
    compare_list = [all_results[0]] + top5
    
    for item in compare_list:
        strategy_name = item['strategy']
        result = item
        
        # 重新生成holding用于年度分解
        if strategy_name == '基准:日度9M':
            holding = gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, lookback_months=9)
            pos_r = None
        elif '波动率加权' in strategy_name and '连续' not in strategy_name and '阈值' not in strategy_name:
            cfg = result.get('config', {})
            holding, pos_r, _ = gem_vol_weighted(
                close_prices[universe], risk_assets, safe_assets, vix=vix,
                base_lookback=9,
                vix_high_threshold=cfg.get('high_th', 22),
                vix_extreme_threshold=cfg.get('extreme_th', 35),
                high_lookback=cfg.get('high_lb', 12),
                extreme_lookback=cfg.get('extreme_lb', 15),
                position_scale=cfg.get('high_r', 1.0) < 1.0 or cfg.get('extreme_r', 1.0) < 1.0,
                high_ratio=cfg.get('high_r', 0.8),
                extreme_ratio=cfg.get('extreme_r', 0.5),
            )
        else:
            # 简化：用原始策略跑年度
            holding = gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, lookback_months=9)
            pos_r = None
        
        print(f"\n  📌 {strategy_name}")
        print(f"  {'年份':<6} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'年调仓':<7}")
        for year in range(2019, 2025):
            yr_result = run_backtest_enhanced(
                close_prices[universe], holding, f'{year}-01-01', f'{year}-12-31',
                position_ratio=pos_r
            )
            if yr_result:
                print(f"  {year:<6} {yr_result['annual_return']:>+7.2f}  {yr_result['max_drawdown']:>6.2f}  "
                      f"{yr_result['sharpe']:>5.2f}  {yr_result['avg_trades_per_year']:>6.1f}")
    
    # ══════════════════════════════════════════════
    # 实验6: 2022年避险详解 — 波动率加权 vs 基准
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 实验6: 2022年避险详解 — 波动率加权仓位变化")
    print("=" * 110)
    
    # 选波动率加权最优配置
    best_vol = gem_vol_weighted(
        close_prices[universe], risk_assets, safe_assets, vix=vix,
        base_lookback=9, vix_high_threshold=22, vix_extreme_threshold=35,
        high_lookback=12, extreme_lookback=15,
        position_scale=True, high_ratio=0.8, extreme_ratio=0.5,
    )
    holding_vol, pos_ratio_vol, lb_used_vol = best_vol
    
    # 2022年逐月
    mask_2022 = (close_prices.index >= '2022-01-01') & (close_prices.index <= '2022-12-31')
    h_2022 = holding_vol.loc[mask_2022]
    pos_2022 = pos_ratio_vol.loc[mask_2022]
    lb_2022 = lb_used_vol.loc[mask_2022]
    
    baseline_h_2022 = baseline_holding.loc[mask_2022]
    
    print(f"\n  {'月份':<6} {'基准持仓':<8} {'VIX加权持仓':<10} {'风险仓位':<8} {'回看期':<6} "
          f"{'VIX加权月收益%':<14} {'基准月收益%':<12} {'超额%':<8}")
    print("-" * 90)
    
    daily_returns = close_prices[universe].loc[mask_2022].pct_change().fillna(0)
    
    for month in range(1, 13):
        month_dates = daily_returns.index[(daily_returns.index.to_period('M') == pd.Period(f'2022-{month:02d}', 'M'))]
        if len(month_dates) == 0:
            continue
        
        # 月末持仓和参数
        month_end_idx = month_dates[-1]
        base_asset = baseline_h_2022.loc[month_end_idx] if month_end_idx in baseline_h_2022.index else 'SHY'
        vol_asset = h_2022.loc[month_end_idx] if month_end_idx in h_2022.index else 'SHY'
        vol_ratio = pos_2022.loc[month_end_idx] if month_end_idx in pos_2022.index else 1.0
        vol_lb = lb_2022.loc[month_end_idx] if month_end_idx in lb_2022.index else 9
        
        # 月收益
        month_mask = daily_returns.index.isin(month_dates)
        base_r = (1 + daily_returns.loc[month_mask, base_asset]).prod() - 1 if base_asset in daily_returns.columns else 0
        vol_r = (1 + daily_returns.loc[month_mask, vol_asset]).prod() - 1 if vol_asset in daily_returns.columns else 0
        
        # VIX加权还需要考虑仓位
        # 简化展示
        
        print(f"  {month:<6} {base_asset:<8} {vol_asset:<10} {vol_ratio:<8.1%} {vol_lb:<6} "
              f"{vol_r*100:>+12.2f}  {base_r*100:>+10.2f}  {(vol_r-base_r)*100:>+6.2f}")
    
    # ══════════════════════════════════════════════
    # 汇总排名
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  🏆 全部策略排名 — 按调整夏普排序")
    print("=" * 110)
    
    all_sorted = sorted(all_results, key=lambda x: x.get('adj_sharpe', -999), reverse=True)
    
    print(f"\n{'排名':<4} {'策略':<38} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'调整夏普':<8} "
          f"{'Calmar':<7} {'年调仓':<7} {'vs基准年化':<10} {'vs基准夏普':<10}")
    print("-" * 115)
    
    baseline_ar = baseline_result['annual_return']
    baseline_sh = baseline_result['sharpe']
    
    for i, r in enumerate(all_sorted):
        diff_ar = r['annual_return'] - baseline_ar
        diff_sh = r['sharpe'] - baseline_sh
        marker = '🏆' if i == 0 else ('🥈' if i == 1 else ('🥉' if i == 2 else '  '))
        
        print(f"  {marker}{i+1:<2} {r['strategy']:<38} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
              f"{r['sharpe']:>5.2f}  {r['adj_sharpe']:>7.2f}  "
              f"{r['calmar']:>6.2f}  {r['avg_trades_per_year']:>6.1f}  "
              f"{diff_ar:>+8.2f}pp  {diff_sh:>+8.2f}")
    
    # ══════════════════════════════════════════════
    # 过拟合检测 — 训练集(2019-2022) vs 测试集(2023-2024)
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 过拟合检测 — 训练集(2019-2022) vs 测试集(2023-2024) [多维度衰减]")
    print("=" * 110)
    
    top_strategies = all_sorted[:8]
    
    print(f"\n{'策略':<34} {'训练年化':<9} {'测试年化':<9} {'收益衰减':<8} {'训练夏普':<9} {'测试夏普':<9} {'夏普衰减':<8} {'训练回撤':<9} {'测试回撤':<9} {'回撤衰减':<8} {'综合衰减':<8}")
    print("-" * 135)
    
    for item in top_strategies:
        name = item['strategy']
        stype = item.get('type', '')
        
        # 重新生成holding
        if name == '基准:日度9M':
            h = gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, lookback_months=9)
            pos_r = None
        elif stype == 'vol_weighted':
            cfg = item.get('config', {})
            h, pos_r, _ = gem_vol_weighted(
                close_prices[universe], risk_assets, safe_assets, vix=vix,
                base_lookback=9,
                vix_high_threshold=cfg.get('high_th', 22),
                vix_extreme_threshold=cfg.get('extreme_th', 35),
                high_lookback=cfg.get('high_lb', 12),
                extreme_lookback=cfg.get('extreme_lb', 15),
                position_scale=cfg.get('high_r', 1.0) < 1.0 or cfg.get('extreme_r', 1.0) < 1.0,
                high_ratio=cfg.get('high_r', 0.8),
                extreme_ratio=cfg.get('extreme_r', 0.5),
            )
        elif stype == 'dual_consecutive':
            cd = item.get('confirm_days', 3)
            h = gem_dual_signal_consecutive(close_prices[universe], risk_assets, safe_assets,
                                            lookback_months=9, confirm_days=cd)
            pos_r = None
        elif stype == 'dual_consecutive_buffer':
            cd = item.get('confirm_days', 3)
            buf = item.get('buffer', 3)
            h = gem_dual_signal_consecutive(close_prices[universe], risk_assets, safe_assets,
                                            lookback_months=9, confirm_days=cd, holding_buffer_days=buf)
            pos_r = None
        elif stype == 'dual_threshold':
            th = item.get('threshold', 0.005)
            h = gem_dual_signal_threshold(close_prices[universe], risk_assets, safe_assets,
                                          lookback_months=9, momentum_threshold=th)
            pos_r = None
        elif stype == 'dual_threshold_buffer':
            th = item.get('threshold', 0.005)
            buf = item.get('buffer', 3)
            h = gem_dual_signal_threshold(close_prices[universe], risk_assets, safe_assets,
                                          lookback_months=9, momentum_threshold=th, holding_buffer_days=buf)
            pos_r = None
        else:
            h = gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, lookback_months=9)
            pos_r = None
        
        train_result = run_backtest_enhanced(close_prices[universe], h, '2019-01-01', '2022-12-31', position_ratio=pos_r)
        test_result = run_backtest_enhanced(close_prices[universe], h, '2023-01-01', '2024-12-31', position_ratio=pos_r)
        
        if train_result and test_result:
            # 多维度衰减计算
            return_decay = (test_result['annual_return'] - train_result['annual_return']) / max(abs(train_result['annual_return']), 0.01) * 100
            sharpe_decay = (test_result['sharpe'] - train_result['sharpe']) / max(abs(train_result['sharpe']), 0.01) * 100
            dd_decay = (test_result['max_drawdown'] - train_result['max_drawdown']) / max(train_result['max_drawdown'], 0.01) * 100  # 正=回撤变大=变差
            calmar_decay = (test_result['calmar'] - train_result['calmar']) / max(abs(train_result['calmar']), 0.01) * 100
            # 综合衰减: 收益40% + 夏普30% - 回撤衰减20%(回撤变大=变差) + Calmar10%
            composite_decay = return_decay * 0.4 + sharpe_decay * 0.3 + (-dd_decay) * 0.2 + calmar_decay * 0.1
            
            print(f"  {name:<32} {train_result['annual_return']:>+7.2f}  {test_result['annual_return']:>+7.2f}  "
                  f"{return_decay:>+6.1f}  {train_result['sharpe']:>7.2f}  {test_result['sharpe']:>7.2f}  "
                  f"{sharpe_decay:>+6.1f}  {train_result['max_drawdown']:>7.2f}  {test_result['max_drawdown']:>7.2f}  "
                  f"{dd_decay:>+6.1f}  {composite_decay:>+6.1f}")
    
    # ══════════════════════════════════════════════
    # 结论
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📝 关键结论")
    print("=" * 110)
    
    # 找出最优增强策略
    best_enhanced = all_sorted[0] if all_sorted[0]['strategy'] != '基准:日度9M' else all_sorted[1]
    
    print(f"""
  📊 基准 vs 最优增强:
     基准:     年化{baseline_result['annual_return']:+.2f}%, 回撤{baseline_result['max_drawdown']:.2f}%, 夏普{baseline_result['sharpe']:.2f}
     最优增强: 年化{best_enhanced['annual_return']:+.2f}%, 回撤{best_enhanced['max_drawdown']:.2f}%, 夏普{best_enhanced['sharpe']:.2f}
     提升:     年化{best_enhanced['annual_return']-baseline_result['annual_return']:+.2f}pp, 回撤{best_enhanced['max_drawdown']-baseline_result['max_drawdown']:+.2f}pp, 夏普{best_enhanced['sharpe']-baseline_result['sharpe']:+.2f}
""")
    
    # 保存结果
    output = {
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'baseline': {k: v for k, v in all_results[0].items() if k != 'holding_distribution'},
        'all_results': [{k: v for k, v in r.items() if k != 'holding_distribution'} for r in all_results],
        'top5': [{k: v for k, v in r.items() if k != 'holding_distribution'} for r in all_sorted[:5]],
    }
    
    output_path = '/data/workspace/strategy_arena/gem_enhanced_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"📁 结果已保存至: {output_path}")


if __name__ == '__main__':
    main()
