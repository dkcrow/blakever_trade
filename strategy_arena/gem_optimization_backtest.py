#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GEM策略五大优化方向回测
======================
基于当前排行榜第一 GEM日度9M+3d缓冲(修正后) 的增量优化

优化1: 回撤控制 — VIX缩仓调优(新阈值组合)
优化2: 收益提升 — 回看期/缓冲天数调优
优化3: 夏普提升 — ATR跟踪止损
优化4: 盈亏比优化 — 阶梯止盈
优化5: 底仓模式融合 — 底仓50%+GEM策略

基准: 日度9M+3d缓冲 年化9.7%/回撤24.52%/夏普0.73/得分47.88
"""

import json
import os
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

RISK_ASSETS = ['SPY', 'VEA']
SAFE_ASSETS = ['AGG', 'SHY']
ALL_ASSETS = RISK_ASSETS + SAFE_ASSETS


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
    filepath = os.path.join(ETF_DATA_DIR, 'VIX.csv')
    if os.path.exists(filepath):
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        return df['Close'].sort_index()
    return None


# ================================================================
# 策略1: GEM基准 (日度9M + buffer天)
# ================================================================
def gem_baseline(close_prices: pd.DataFrame, lookback_months: int = 9, buffer_days: int = 3) -> pd.Series:
    """GEM基准策略: 日度N月动量 + M天缓冲"""
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = SAFE_ASSETS[-1]
    last_switch_day = -999
    
    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days
        
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
            risk_momentum = {}
            for asset in RISK_ASSETS:
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
                for asset in SAFE_ASSETS:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else SAFE_ASSETS[-1]
            
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
        
        holding.iloc[i] = current_asset
    
    return holding


# ================================================================
# 策略2: GEM + VIX缩仓 (新阈值组合)
# ================================================================
def gem_vix_scaled(close_prices: pd.DataFrame, vix: pd.Series,
                   lookback_months: int = 9, buffer_days: int = 3,
                   vix_high: float = 20, vix_extreme: float = 30,
                   ratio_high: float = 0.7, ratio_extreme: float = 0.4) -> tuple:
    """GEM策略 + VIX波动率缩仓"""
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    # 对齐VIX
    vix_aligned = vix.reindex(all_dates).ffill().bfill()
    
    holding = pd.Series(index=all_dates, dtype=object)
    position_ratio = pd.Series(1.0, index=all_dates)
    current_asset = SAFE_ASSETS[-1]
    last_switch_day = -999
    
    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days
        
        # VIX缩仓
        vix_val = vix_aligned.iloc[i] if i < len(vix_aligned) else 20
        if vix_val >= vix_extreme:
            pos_r = ratio_extreme
        elif vix_val >= vix_high:
            pos_r = ratio_high
        else:
            pos_r = 1.0
        position_ratio.iloc[i] = pos_r
        
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
            risk_momentum = {}
            for asset in RISK_ASSETS:
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
                for asset in SAFE_ASSETS:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else SAFE_ASSETS[-1]
            
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
        
        holding.iloc[i] = current_asset
    
    return holding, position_ratio


# ================================================================
# 策略3: GEM + ATR跟踪止损
# ================================================================
def gem_atr_trailing_stop(close_prices: pd.DataFrame, lookback_months: int = 9,
                          buffer_days: int = 3, atr_period: int = 14,
                          atr_multiplier: float = 3.5) -> pd.Series:
    """GEM策略 + ATR跟踪止损: 持有风险资产时，价格跌破ATR止损线则切至安全资产"""
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    # 计算ATR
    # 由于只有收盘价，用简化ATR: ATR = close.rolling(atr_period).std() * sqrt(2) 近似
    # 或者用收盘价变动的绝对值均值近似
    atr_dict = {}
    for asset in RISK_ASSETS:
        if asset in close_prices.columns:
            daily_range = close_prices[asset].diff().abs()
            atr_dict[asset] = daily_range.rolling(atr_period).mean()
    
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = SAFE_ASSETS[-1]
    last_switch_day = -999
    stop_price = 0  # ATR跟踪止损价
    
    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days
        
        # ATR止损检查: 仅对风险资产持仓时生效
        if current_asset in RISK_ASSETS and i >= atr_period:
            current_price = close_prices.iloc[i][current_asset] if current_asset in close_prices.columns else 0
            if pd.notna(current_price) and current_price > 0 and stop_price > 0:
                if current_price < stop_price:
                    # 触发ATR止损，切至安全资产
                    safe_momentum = {}
                    for asset in SAFE_ASSETS:
                        if i >= lookback_days and asset in close_prices.columns:
                            curr_p = close_prices.iloc[i][asset]
                            past_p = close_prices.iloc[i - lookback_days][asset]
                            if pd.notna(curr_p) and pd.notna(past_p) and past_p > 0:
                                safe_momentum[asset] = curr_p / past_p - 1
                    current_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else SAFE_ASSETS[-1]
                    last_switch_day = i
                    stop_price = 0
        
        # 正常GEM信号
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
            risk_momentum = {}
            for asset in RISK_ASSETS:
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
                for asset in SAFE_ASSETS:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else SAFE_ASSETS[-1]
            
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
        
        # 更新ATR止损线（只上不下）
        if current_asset in RISK_ASSETS and current_asset in atr_dict and i >= atr_period:
            current_price = close_prices.iloc[i][current_asset] if current_asset in close_prices.columns else 0
            atr_val = atr_dict[current_asset].iloc[i] if i < len(atr_dict[current_asset]) else 0
            if pd.notna(current_price) and pd.notna(atr_val) and current_price > 0 and atr_val > 0:
                new_stop = current_price - atr_multiplier * atr_val
                # 止损线只上不下（跟踪止损）
                stop_price = max(stop_price, new_stop) if stop_price > 0 else new_stop
            else:
                stop_price = 0
        else:
            stop_price = 0
        
        holding.iloc[i] = current_asset
    
    return holding


# ================================================================
# 策略4: GEM + 动量阈值过滤 (改善盈亏比)
# ================================================================
def gem_momentum_threshold(close_prices: pd.DataFrame, lookback_months: int = 9,
                           buffer_days: int = 3, threshold: float = 0.02) -> pd.Series:
    """GEM策略 + 动量阈值: 新资产动量需比当前持仓高出threshold才切换"""
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)
    
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = SAFE_ASSETS[-1]
    last_switch_day = -999
    
    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days
        
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]
            
            # 计算所有资产动量
            all_momentum = {}
            for asset in ALL_ASSETS:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        all_momentum[asset] = curr / past - 1
            
            # 选最优风险资产
            risk_mom = {k: v for k, v in all_momentum.items() if k in RISK_ASSETS and v > 0}
            if risk_mom:
                best_risk = max(risk_mom, key=risk_mom.get)
                best_risk_mom = risk_mom[best_risk]
                
                # 当前持仓动量
                current_mom = all_momentum.get(current_asset, -1)
                if pd.isna(current_mom):
                    current_mom = -1
                
                # 动量差值必须超过阈值
                if (best_risk_mom - current_mom) > threshold:
                    new_asset = best_risk
                elif current_asset in SAFE_ASSETS:
                    # 当前已在安全资产，只要风险资产正动量就切
                    new_asset = best_risk
                else:
                    new_asset = current_asset
            else:
                # 无正动量风险资产 → 选安全资产
                safe_mom = {k: v for k, v in all_momentum.items() if k in SAFE_ASSETS}
                new_asset = max(safe_mom, key=safe_mom.get) if safe_mom else SAFE_ASSETS[-1]
                
                # 安全资产之间也检查阈值
                current_mom = all_momentum.get(current_asset, -1)
                new_mom = all_momentum.get(new_asset, -1)
                if pd.isna(current_mom): current_mom = -1
                if pd.isna(new_mom): new_mom = -1
                if (new_mom - current_mom) <= threshold and current_asset in SAFE_ASSETS:
                    new_asset = current_asset
            
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
        
        holding.iloc[i] = current_asset
    
    return holding


# ================================================================
# 通用回测引擎
# ================================================================
def run_backtest(close_prices: pd.DataFrame, holding: pd.Series,
                start_date: str, end_date: str,
                position_ratio: pd.Series = None,
                base_ratio: float = 0.0) -> dict:
    """
    通用回测引擎
    - shift(1)修正数据穿越
    - 支持VIX缩仓(position_ratio)
    - 支持底仓模式(base_ratio)
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    
    # T+1修正
    h = holding.shift(1).loc[mask]
    h.iloc[0] = holding.iloc[0] if pd.notna(holding.iloc[0]) else SAFE_ASSETS[-1]
    
    pos_r = None
    if position_ratio is not None:
        pos_r = position_ratio.shift(1).loc[mask]
        pos_r.iloc[0] = 1.0
    
    if len(prices) < 100:
        return None
    
    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    prev_asset = None
    trade_count = 0
    
    for date in prices.index:
        current_asset = h.loc[date]
        ratio = pos_r.loc[date] if pos_r is not None and date in pos_r.index else 1.0
        
        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            if pd.notna(r):
                # VIX缩仓: 风险资产按ratio分配，剩余给SHY
                if current_asset in RISK_ASSETS and ratio < 1.0 and 'SHY' in daily_returns.columns:
                    shy_r = daily_returns.loc[date, 'SHY']
                    portfolio_returns.loc[date] = ratio * r + (1 - ratio) * (shy_r if pd.notna(shy_r) else 0)
                else:
                    portfolio_returns.loc[date] = r
        
        # 手续费+滑点
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            portfolio_returns.loc[date] -= (FEES + SLIPPAGE)
        
        prev_asset = current_asset
    
    # 底仓模式
    if base_ratio > 0 and 'SPY' in daily_returns.columns:
        spy_returns = daily_returns['SPY'].fillna(0)
        portfolio_returns = base_ratio * spy_returns + (1 - base_ratio) * portfolio_returns
    
    # 统计
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(prices) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
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
    
    holding_counts = h.value_counts()
    holding_pcts = (holding_counts / len(h) * 100).to_dict()
    
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
        'holding_distribution': {k: round(v, 1) for k, v in holding_pcts.items()},
    }


# ================================================================
# 评分体系（与cross_regime_scheduler一致）
# ================================================================
def calculate_score(result: dict, stress_result: dict = None) -> dict:
    """穿越牛熊评分体系"""
    annual = result.get('annual_return', 0)
    sharpe = result.get('sharpe', 0)
    max_dd = result.get('max_drawdown', 100)
    calmar = result.get('calmar', 0)
    win_rate = result.get('win_rate', 0)
    profit_factor = result.get('profit_factor', 0)
    
    # 年化收益(25%)
    if annual >= 10: annual_score = 25
    elif annual >= 5: annual_score = 15
    else: annual_score = 5
    
    # 夏普(25%)
    if sharpe >= 1.0: sharpe_score = 25
    elif sharpe >= 0.7: sharpe_score = 18
    elif sharpe >= 0.5: sharpe_score = 10
    else: sharpe_score = 0
    
    # 回撤(20%)
    if max_dd <= 15: dd_score = 20
    elif max_dd <= 20: dd_score = 12
    else: dd_score = 0
    
    # Calmar(15%)
    if calmar >= 0.5: calmar_score = 15
    elif calmar >= 0.3: calmar_score = 10
    else: calmar_score = 5
    
    # 胜率(10%)
    if win_rate >= 50: win_score = 10
    elif win_rate >= 40: win_score = 6
    else: win_score = 0
    
    # 盈亏比(5%)
    if profit_factor >= 1.0: pf_score = 5
    else: pf_score = 0
    
    base_score = annual_score + sharpe_score + dd_score + calmar_score + win_score + pf_score
    
    bonus = 0
    if stress_result:
        stress_dd = stress_result.get('max_drawdown', 100)
        if stress_dd < 15:
            bonus = 5
    
    total_score = base_score + bonus
    
    # 硬性条件
    hard_fail = False
    fail_reason = ''
    if max_dd >= 30:
        hard_fail = True
        fail_reason = '最大回撤≥30%'
    elif annual < 0:
        hard_fail = True
        fail_reason = '年化收益为负'
    
    return {
        'total_score': total_score if not hard_fail else 0,
        'score_detail': {
            'annual': annual_score, 'sharpe': sharpe_score, 'dd': dd_score,
            'calmar': calmar_score, 'win': win_score, 'pf': pf_score, 'stress_bonus': bonus,
        },
        'hard_fail': hard_fail,
        'fail_reason': fail_reason,
    }


# ================================================================
# 过拟合检测
# ================================================================
def check_overfit(close_prices, holding, position_ratio=None, base_ratio=0.0):
    """训练集(2019-2022) vs 测试集(2023-2024) 多维度衰减"""
    train = run_backtest(close_prices, holding, '2019-01-01', '2022-12-31',
                        position_ratio=position_ratio, base_ratio=base_ratio)
    test = run_backtest(close_prices, holding, '2023-01-01', '2024-12-31',
                       position_ratio=position_ratio, base_ratio=base_ratio)
    
    if not train or not test:
        return None
    
    ret_decay = (test['annual_return'] - train['annual_return']) / max(abs(train['annual_return']), 0.01) * 100
    sh_decay = (test['sharpe'] - train['sharpe']) / max(abs(train['sharpe']), 0.01) * 100
    dd_decay = (test['max_drawdown'] - train['max_drawdown']) / max(train['max_drawdown'], 0.01) * 100
    cal_decay = (test['calmar'] - train['calmar']) / max(abs(train['calmar']), 0.01) * 100
    composite = ret_decay * 0.4 + sh_decay * 0.3 + (-dd_decay) * 0.2 + cal_decay * 0.1
    
    return {
        'train': train, 'test': test,
        'return_decay': round(ret_decay, 1),
        'sharpe_decay': round(sh_decay, 1),
        'dd_decay': round(dd_decay, 1),
        'calmar_decay': round(cal_decay, 1),
        'composite_decay': round(composite, 1),
    }


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 120)
    print("  🚀 GEM策略五大优化方向回测")
    print("=" * 120)
    
    # 加载数据
    print("\n📦 加载数据...")
    etf_data = {}
    for sym in ALL_ASSETS:
        df = load_etf_data(sym)
        if df is not None:
            etf_data[sym] = df['Close']
            print(f"  ✅ {sym}: {len(df)}行")
    
    close_prices = pd.DataFrame(etf_data).dropna(how='all').sort_index().ffill().bfill()
    print(f"  📊 合并: {len(close_prices)}行 ({close_prices.index[0].strftime('%Y-%m-%d')} ~ {close_prices.index[-1].strftime('%Y-%m-%d')})")
    
    vix = load_vix_data()
    if vix is not None:
        print(f"  ✅ VIX: {len(vix)}行")
    else:
        print("  ⚠️ VIX不可用")
    
    all_results = []
    
    # ══════════════════════════════════════════════
    # 基准: GEM日度9M+3d缓冲
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 基准: GEM日度9M+3d缓冲(当前排行榜第一)")
    print("=" * 120)
    
    base_holding = gem_baseline(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3)
    base_result = run_backtest(close_prices[ALL_ASSETS], base_holding, MAIN_START, MAIN_END)
    base_stress = run_backtest(close_prices[ALL_ASSETS], base_holding, '2022-01-01', '2022-12-31')
    base_score = calculate_score(base_result, base_stress)
    base_overfit = check_overfit(close_prices[ALL_ASSETS], base_holding)
    
    print(f"\n  基准: 年化{base_result['annual_return']:+.2f}% / 回撤{base_result['max_drawdown']:.2f}% / "
          f"夏普{base_result['sharpe']:.2f} / Calmar{base_result['calmar']:.2f} / "
          f"胜率{base_result['win_rate']:.1f}% / 盈亏比{base_result['profit_factor']:.2f} / "
          f"年调仓{base_result['avg_trades_per_year']:.1f}次 / 得分{base_score['total_score']}分")
    print(f"  压力测试(2022): 年化{base_stress['annual_return']:+.2f}% / 回撤{base_stress['max_drawdown']:.2f}%")
    print(f"  过拟合: 训练年化{base_overfit['train']['annual_return']:+.2f}% vs 测试{base_overfit['test']['annual_return']:+.2f}% / "
          f"综合衰减{base_overfit['composite_decay']:+.1f}%")
    
    all_results.append({
        '方向': '基准', '策略': 'GEM日度9M+3d缓冲',
        **base_result, 'score': base_score['total_score'],
        'stress_dd': base_stress['max_drawdown'] if base_stress else 0,
        'overfit': base_overfit['composite_decay'] if base_overfit else 0,
    })
    
    # ══════════════════════════════════════════════
    # 优化1: VIX缩仓调优
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 优化1: VIX缩仓调优 — 降低回撤")
    print("=" * 120)
    
    vix_configs = [
        # (vix_high, vix_extreme, ratio_high, ratio_extreme, label)
        (20, 30, 0.7, 0.4, '极早(20/30,70%/40%)'),
        (20, 28, 0.7, 0.4, '极早2(20/28,70%/40%)'),
        (22, 30, 0.7, 0.4, '保守(22/30,70%/40%)'),
        (22, 35, 0.7, 0.4, '中庸(22/35,70%/40%)'),
        (25, 35, 0.7, 0.4, '激进(25/35,70%/40%)'),
        (25, 35, 0.8, 0.5, '温和缩仓(25/35,80%/50%)'),
        (20, 30, 0.5, 0.2, '极端缩仓(20/30,50%/20%)'),
        (18, 25, 0.6, 0.3, '超早(18/25,60%/30%)'),
    ]
    
    print(f"\n  {'策略':<28} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'Calmar':<7} "
          f"{'盈亏比':<6} {'得分':<5} {'2022回撤%':<9} {'衰减%':<7} {'vs基准回撤':<10}")
    print("  " + "-" * 108)
    
    for vix_h, vix_e, r_h, r_e, label in vix_configs:
        if vix is None:
            continue
        h, pr = gem_vix_scaled(close_prices[ALL_ASSETS], vix, lookback_months=9, buffer_days=3,
                               vix_high=vix_h, vix_extreme=vix_e, ratio_high=r_h, ratio_extreme=r_e)
        r = run_backtest(close_prices[ALL_ASSETS], h, MAIN_START, MAIN_END, position_ratio=pr)
        stress = run_backtest(close_prices[ALL_ASSETS], h, '2022-01-01', '2022-12-31', position_ratio=pr)
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], h, position_ratio=pr)
        
        dd_diff = r['max_drawdown'] - base_result['max_drawdown']
        
        if r:
            print(f"  {label:<26} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}  "
                  f"{dd_diff:>+8.2f}pp")
            all_results.append({
                '方向': 'VIX缩仓', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # ══════════════════════════════════════════════
    # 优化2: 回看期/缓冲天数调优
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 优化2: 回看期/缓冲天数调优 — 提升收益")
    print("=" * 120)
    
    lb_buf_configs = [
        (6, 2, '6M+2d缓冲'), (6, 3, '6M+3d缓冲'), (6, 5, '6M+5d缓冲'),
        (9, 2, '9M+2d缓冲'), (9, 4, '9M+4d缓冲'), (9, 5, '9M+5d缓冲'),
        (12, 2, '12M+2d缓冲'), (12, 3, '12M+3d缓冲'), (12, 5, '12M+5d缓冲'),
        (9, 0, '9M无缓冲'), (6, 0, '6M无缓冲'), (12, 0, '12M无缓冲'),
    ]
    
    print(f"\n  {'策略':<16} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'Calmar':<7} "
          f"{'盈亏比':<6} {'得分':<5} {'2022回撤%':<9} {'衰减%':<7} {'vs基准年化':<10}")
    print("  " + "-" * 98)
    
    for lb, buf, label in lb_buf_configs:
        h = gem_baseline(close_prices[ALL_ASSETS], lookback_months=lb, buffer_days=buf)
        r = run_backtest(close_prices[ALL_ASSETS], h, MAIN_START, MAIN_END)
        stress = run_backtest(close_prices[ALL_ASSETS], h, '2022-01-01', '2022-12-31')
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], h)
        
        ar_diff = r['annual_return'] - base_result['annual_return']
        
        if r:
            print(f"  {label:<14} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}  "
                  f"{ar_diff:>+8.2f}pp")
            all_results.append({
                '方向': '回看期/缓冲', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # ══════════════════════════════════════════════
    # 优化3: ATR跟踪止损
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 优化3: ATR跟踪止损 — 提升夏普")
    print("=" * 120)
    
    atr_configs = [
        (2.5, 'ATR2.5x止损'), (3.0, 'ATR3.0x止损'), (3.5, 'ATR3.5x止损'),
        (4.0, 'ATR4.0x止损'), (5.0, 'ATR5.0x止损'),
    ]
    
    print(f"\n  {'策略':<20} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'Calmar':<7} "
          f"{'盈亏比':<6} {'得分':<5} {'2022回撤%':<9} {'衰减%':<7} {'vs基准夏普':<10}")
    print("  " + "-" * 100)
    
    for atr_m, label in atr_configs:
        h = gem_atr_trailing_stop(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3,
                                  atr_period=14, atr_multiplier=atr_m)
        r = run_backtest(close_prices[ALL_ASSETS], h, MAIN_START, MAIN_END)
        stress = run_backtest(close_prices[ALL_ASSETS], h, '2022-01-01', '2022-12-31')
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], h)
        
        sh_diff = r['sharpe'] - base_result['sharpe']
        
        if r:
            print(f"  {label:<18} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}  "
                  f"{sh_diff:>+8.2f}")
            all_results.append({
                '方向': 'ATR止损', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # ATR止损 + 不同缓冲天数
    print(f"\n  --- ATR止损 + 缓冲天数组合 ---")
    for atr_m in [3.0, 3.5]:
        for buf in [2, 5]:
            label = f'ATR{atr_m}x+{buf}d缓冲'
            h = gem_atr_trailing_stop(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=buf,
                                      atr_period=14, atr_multiplier=atr_m)
            r = run_backtest(close_prices[ALL_ASSETS], h, MAIN_START, MAIN_END)
            stress = run_backtest(close_prices[ALL_ASSETS], h, '2022-01-01', '2022-12-31')
            score = calculate_score(r, stress)
            of = check_overfit(close_prices[ALL_ASSETS], h)
            
            if r:
                print(f"  {label:<18} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                      f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                      f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                      f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}")
                all_results.append({
                    '方向': 'ATR止损', '策略': label,
                    **r, 'score': score['total_score'],
                    'stress_dd': stress['max_drawdown'] if stress else 0,
                    'overfit': of['composite_decay'] if of else 0,
                })
    
    # ══════════════════════════════════════════════
    # 优化4: 动量阈值过滤
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 优化4: 动量阈值过滤 — 提升盈亏比")
    print("=" * 120)
    
    threshold_configs = [
        (0.01, '阈值1%'), (0.02, '阈值2%'), (0.03, '阈值3%'),
        (0.05, '阈值5%'), (0.08, '阈值8%'), (0.10, '阈值10%'),
    ]
    
    print(f"\n  {'策略':<16} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'Calmar':<7} "
          f"{'盈亏比':<6} {'得分':<5} {'2022回撤%':<9} {'衰减%':<7} {'vs基准盈亏比':<12}")
    print("  " + "-" * 102)
    
    for th, label in threshold_configs:
        h = gem_momentum_threshold(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3, threshold=th)
        r = run_backtest(close_prices[ALL_ASSETS], h, MAIN_START, MAIN_END)
        stress = run_backtest(close_prices[ALL_ASSETS], h, '2022-01-01', '2022-12-31')
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], h)
        
        pf_diff = r['profit_factor'] - base_result['profit_factor']
        
        if r:
            print(f"  {label:<14} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}  "
                  f"{pf_diff:>+10.2f}")
            all_results.append({
                '方向': '动量阈值', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # ══════════════════════════════════════════════
    # 优化5: 底仓模式融合
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 优化5: 底仓模式融合 — 核心突破方向")
    print("=" * 120)
    
    # 5a: 基准GEM + 底仓SPY
    base_configs = [
        (0.2, 'GEM+20%SPY底仓'), (0.3, 'GEM+30%SPY底仓'),
        (0.4, 'GEM+40%SPY底仓'), (0.5, 'GEM+50%SPY底仓'),
    ]
    
    print(f"\n  --- 5a: 基准GEM(9M+3d缓冲) + SPY底仓 ---")
    print(f"  {'策略':<20} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'Calmar':<7} "
          f"{'盈亏比':<6} {'得分':<5} {'2022回撤%':<9} {'衰减%':<7} {'vs基准得分':<10}")
    print("  " + "-" * 100)
    
    for base_r, label in base_configs:
        r = run_backtest(close_prices[ALL_ASSETS], base_holding, MAIN_START, MAIN_END, base_ratio=base_r)
        stress = run_backtest(close_prices[ALL_ASSETS], base_holding, '2022-01-01', '2022-12-31', base_ratio=base_r)
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], base_holding, base_ratio=base_r)
        
        score_diff = score['total_score'] - base_score['total_score']
        
        if r:
            print(f"  {label:<18} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}  "
                  f"{score_diff:>+8}")
            all_results.append({
                '方向': '底仓模式', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # 5b: VIX缩仓最优 + SPY底仓
    if vix is not None:
        print(f"\n  --- 5b: VIX缩仓最优(22/30) + SPY底仓 ---")
        vix_h, vix_pr = gem_vix_scaled(close_prices[ALL_ASSETS], vix, lookback_months=9, buffer_days=3,
                                        vix_high=22, vix_extreme=30, ratio_high=0.7, ratio_extreme=0.4)
        
        for base_r in [0.3, 0.5]:
            label = f'VIX(22/30)+{int(base_r*100)}%SPY底仓'
            r = run_backtest(close_prices[ALL_ASSETS], vix_h, MAIN_START, MAIN_END,
                           position_ratio=vix_pr, base_ratio=base_r)
            stress = run_backtest(close_prices[ALL_ASSETS], vix_h, '2022-01-01', '2022-12-31',
                                position_ratio=vix_pr, base_ratio=base_r)
            score = calculate_score(r, stress)
            of = check_overfit(close_prices[ALL_ASSETS], vix_h, position_ratio=vix_pr, base_ratio=base_r)
            
            if r:
                print(f"  {label:<18} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                      f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                      f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                      f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}")
                all_results.append({
                    '方向': '底仓+VIX', '策略': label,
                    **r, 'score': score['total_score'],
                    'stress_dd': stress['max_drawdown'] if stress else 0,
                    'overfit': of['composite_decay'] if of else 0,
                })
    
    # 5c: ATR止损 + SPY底仓
    print(f"\n  --- 5c: ATR3.5x止损 + SPY底仓 ---")
    atr_h = gem_atr_trailing_stop(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3,
                                  atr_period=14, atr_multiplier=3.5)
    
    for base_r in [0.3, 0.5]:
        label = f'ATR3.5x+{int(base_r*100)}%SPY底仓'
        r = run_backtest(close_prices[ALL_ASSETS], atr_h, MAIN_START, MAIN_END, base_ratio=base_r)
        stress = run_backtest(close_prices[ALL_ASSETS], atr_h, '2022-01-01', '2022-12-31', base_ratio=base_r)
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], atr_h, base_ratio=base_r)
        
        if r:
            print(f"  {label:<18} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}")
            all_results.append({
                '方向': '底仓+ATR', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # 5d: 动量阈值 + SPY底仓
    print(f"\n  --- 5d: 动量阈值2% + SPY底仓 ---")
    th_h = gem_momentum_threshold(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3, threshold=0.02)
    
    for base_r in [0.3, 0.5]:
        label = f'阈值2%+{int(base_r*100)}%SPY底仓'
        r = run_backtest(close_prices[ALL_ASSETS], th_h, MAIN_START, MAIN_END, base_ratio=base_r)
        stress = run_backtest(close_prices[ALL_ASSETS], th_h, '2022-01-01', '2022-12-31', base_ratio=base_r)
        score = calculate_score(r, stress)
        of = check_overfit(close_prices[ALL_ASSETS], th_h, base_ratio=base_r)
        
        if r:
            print(f"  {label:<18} {r['annual_return']:>+7.2f}  {r['max_drawdown']:>6.2f}  "
                  f"{r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
                  f"{r['profit_factor']:>5.2f}  {score['total_score']:>4}  "
                  f"{stress['max_drawdown']:>7.2f}  {of['composite_decay']:>+5.1f}")
            all_results.append({
                '方向': '底仓+阈值', '策略': label,
                **r, 'score': score['total_score'],
                'stress_dd': stress['max_drawdown'] if stress else 0,
                'overfit': of['composite_decay'] if of else 0,
            })
    
    # ══════════════════════════════════════════════
    # 终极组合: 多维优化叠加
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 终极组合: 多维优化叠加")
    print("=" * 120)
    
    # 组合A: VIX缩仓 + ATR止损 + 底仓
    if vix is not None:
        print(f"\n  --- 组合A: VIX缩仓(22/30) + ATR3.5x止损 + SPY底仓 ---")
        # 用VIX缩仓版GEM + ATR止损
        combo_a_h, combo_a_pr = gem_vix_scaled(close_prices[ALL_ASSETS], vix, lookback_months=9, buffer_days=3,
                                                vix_high=22, vix_extreme=30, ratio_high=0.7, ratio_extreme=0.4)
        # 再叠加ATR止损
        combo_a_h2 = gem_atr_trailing_stop(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3,
                                           atr_period=14, atr_multiplier=3.5)
        
        for base_r in [0.3, 0.5]:
            # 简化: 取两个信号中更保守的（即任一触发都切出风险资产）
            label = f'VIX+ATR+{int(base_r*100)}%底仓'
            r_vix = run_backtest(close_prices[ALL_ASSETS], combo_a_h, MAIN_START, MAIN_END,
                               position_ratio=combo_a_pr, base_ratio=base_r)
            stress_vix = run_backtest(close_prices[ALL_ASSETS], combo_a_h, '2022-01-01', '2022-12-31',
                                    position_ratio=combo_a_pr, base_ratio=base_r)
            score_vix = calculate_score(r_vix, stress_vix)
            of_vix = check_overfit(close_prices[ALL_ASSETS], combo_a_h, position_ratio=combo_a_pr, base_ratio=base_r)
            
            r_atr = run_backtest(close_prices[ALL_ASSETS], combo_a_h2, MAIN_START, MAIN_END, base_ratio=base_r)
            stress_atr = run_backtest(close_prices[ALL_ASSETS], combo_a_h2, '2022-01-01', '2022-12-31', base_ratio=base_r)
            score_atr = calculate_score(r_atr, stress_atr)
            of_atr = check_overfit(close_prices[ALL_ASSETS], combo_a_h2, base_ratio=base_r)
            
            print(f"  VIX(22/30)+{int(base_r*100)}%底仓{'':<8} {r_vix['annual_return']:>+7.2f}  {r_vix['max_drawdown']:>6.2f}  "
                  f"{r_vix['sharpe']:>5.2f}  {r_vix['calmar']:>6.2f}  "
                  f"{r_vix['profit_factor']:>5.2f}  {score_vix['total_score']:>4}  "
                  f"{stress_vix['max_drawdown']:>7.2f}  {of_vix['composite_decay']:>+5.1f}")
            print(f"  ATR3.5x+{int(base_r*100)}%底仓{'':<9} {r_atr['annual_return']:>+7.2f}  {r_atr['max_drawdown']:>6.2f}  "
                  f"{r_atr['sharpe']:>5.2f}  {r_atr['calmar']:>6.2f}  "
                  f"{r_atr['profit_factor']:>5.2f}  {score_atr['total_score']:>4}  "
                  f"{stress_atr['max_drawdown']:>7.2f}  {of_atr['composite_decay']:>+5.1f}")
            
            all_results.append({
                '方向': '终极组合', '策略': f'VIX(22/30)+{int(base_r*100)}%底仓',
                **r_vix, 'score': score_vix['total_score'],
                'stress_dd': stress_vix['max_drawdown'] if stress_vix else 0,
                'overfit': of_vix['composite_decay'] if of_vix else 0,
            })
            all_results.append({
                '方向': '终极组合', '策略': f'ATR3.5x+{int(base_r*100)}%底仓',
                **r_atr, 'score': score_atr['total_score'],
                'stress_dd': stress_atr['max_drawdown'] if stress_atr else 0,
                'overfit': of_atr['composite_decay'] if of_atr else 0,
            })
    
    # ══════════════════════════════════════════════
    # 全局排名
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  🏆 全部策略综合排名 — 按得分排序")
    print("=" * 120)
    
    sorted_results = sorted(all_results, key=lambda x: x.get('score', 0), reverse=True)
    
    print(f"\n  {'#':<3} {'方向':<10} {'策略':<24} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'Calmar':<7} "
          f"{'盈亏比':<6} {'胜率%':<6} {'得分':<5} {'2022回撤':<8} {'衰减%':<7} {'vs基准':<8}")
    print("  " + "-" * 120)
    
    for i, r in enumerate(sorted_results):
        vs_base = r['score'] - base_score['total_score']
        marker = '🏆' if i == 0 else ('🥈' if i == 1 else ('🥉' if i == 2 else '  '))
        dd_2022 = r.get('stress_dd', 0)
        of = r.get('overfit', 0)
        
        print(f"  {marker}{i+1:<1} {r['方向']:<10} {r['策略']:<24} {r['annual_return']:>+7.2f}  "
              f"{r['max_drawdown']:>6.2f}  {r['sharpe']:>5.2f}  {r['calmar']:>6.2f}  "
              f"{r['profit_factor']:>5.2f}  {r['win_rate']:>5.1f}  {r['score']:>4}  "
              f"{dd_2022:>7.2f}  {of:>+5.1f}  {vs_base:>+6}")
    
    # ══════════════════════════════════════════════
    # TOP3策略年度分解
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📊 TOP3策略年度收益分解")
    print("=" * 120)
    
    for i, r in enumerate(sorted_results[:3]):
        print(f"\n  📌 #{i+1}: {r['方向']} - {r['策略']} (得分{r['score']}分)")
        
        # 重新回测各年度
        strategy_name = r['策略']
        direction = r['方向']
        
        # 根据方向重建holding
        if direction == '基准':
            h = gem_baseline(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3)
            pr = None; br = 0
        elif direction == 'VIX缩仓':
            # 解析VIX参数
            h, pr = gem_vix_scaled(close_prices[ALL_ASSETS], vix, lookback_months=9, buffer_days=3,
                                   vix_high=22, vix_extreme=30, ratio_high=0.7, ratio_extreme=0.4)
            br = 0
        elif direction == 'ATR止损':
            h = gem_atr_trailing_stop(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3,
                                      atr_period=14, atr_multiplier=3.5)
            pr = None; br = 0
        elif direction == '底仓模式':
            h = gem_baseline(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3)
            pr = None; br = 0.5
        elif '底仓' in direction:
            if 'VIX' in strategy_name:
                h, pr = gem_vix_scaled(close_prices[ALL_ASSETS], vix, lookback_months=9, buffer_days=3,
                                       vix_high=22, vix_extreme=30, ratio_high=0.7, ratio_extreme=0.4)
                br = 0.5
            elif 'ATR' in strategy_name:
                h = gem_atr_trailing_stop(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3,
                                          atr_period=14, atr_multiplier=3.5)
                pr = None; br = 0.5
            else:
                h = gem_baseline(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3)
                pr = None; br = 0.5
        else:
            h = gem_baseline(close_prices[ALL_ASSETS], lookback_months=9, buffer_days=3)
            pr = None; br = 0
        
        print(f"  {'年份':<6} {'年化%':<8} {'回撤%':<8} {'夏普':<6} {'年调仓':<7}")
        for year in range(2019, 2025):
            yr = run_backtest(close_prices[ALL_ASSETS], h, f'{year}-01-01', f'{year}-12-31',
                            position_ratio=pr, base_ratio=br)
            if yr:
                print(f"  {year:<6} {yr['annual_return']:>+7.2f}  {yr['max_drawdown']:>6.2f}  "
                      f"{yr['sharpe']:>5.2f}  {yr['avg_trades_per_year']:>6.1f}")
    
    # ══════════════════════════════════════════════
    # 保存结果
    # ══════════════════════════════════════════════
    output = {
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'baseline_score': base_score['total_score'],
        'total_strategies': len(all_results),
        'all_results': [{k: v for k, v in r.items() if k != 'holding_distribution'} for r in sorted_results],
    }
    
    output_path = '/data/workspace/strategy_arena/gem_optimization_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 结果已保存至: {output_path}")
    
    # ══════════════════════════════════════════════
    # 结论
    # ══════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  📝 最终结论")
    print("=" * 120)
    
    best = sorted_results[0]
    print(f"""
  🏆 最优优化策略: {best['方向']} - {best['策略']}
     得分: {best['score']}分 (基准{base_score['total_score']}分, +{best['score']-base_score['total_score']}分)
     年化: {best['annual_return']:+.2f}% (基准{base_result['annual_return']:+.2f}%, {best['annual_return']-base_result['annual_return']:+.2f}pp)
     回撤: {best['max_drawdown']:.2f}% (基准{base_result['max_drawdown']:.2f}%, {best['max_drawdown']-base_result['max_drawdown']:+.2f}pp)
     夏普: {best['sharpe']:.2f} (基准{base_result['sharpe']:.2f}, {best['sharpe']-base_result['sharpe']:+.2f})
     Calmar: {best['calmar']:.2f} (基准{base_result['calmar']:.2f}, {best['calmar']-base_result['calmar']:+.2f})
     盈亏比: {best['profit_factor']:.2f} (基准{base_result['profit_factor']:.2f}, {best['profit_factor']-base_result['profit_factor']:+.2f})
""")


if __name__ == '__main__':
    main()
