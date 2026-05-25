#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组合策略回测引擎 v1 — 支持多标的同时持仓+个股选股
================================================

扩展自 cross_regime_scheduler.py 的向量化回测引擎

核心扩展：
1. run_portfolio_backtest_vec: 支持多标的同时持仓的向量化回测
   - 输入: 每日持仓权重矩阵 (N日 × M标的) 而非单标的holding序列
   - 组合收益率 = Σ(权重_i × 日收益率_i)
   - 含换仓成本精确扣除
2. backtest_portfolio_strategy: 组合策略专用三层递进入口
3. A股全量个股数据加载

使用方式：
  from portfolio_backtest import backtest_portfolio_strategy, load_cn_all_stocks
  
  def my_portfolio_strategy(close_prices, stock_close, stock_volume, **kwargs):
      '''
      组合策略函数签名
      
      参数:
        close_prices: pd.DataFrame - ETF价格矩阵（6只基准ETF）
        stock_close: pd.DataFrame - 个股价格矩阵（可选，A股512只）
        stock_volume: pd.DataFrame - 个股成交量矩阵（可选）
      返回:
        pd.DataFrame - 每日持仓权重矩阵 (N日 × M标的)
                       列名必须在close_prices或stock_close的列中
                       每行之和应≈1.0（允许<1.0表示持有现金）
      '''
      weights = pd.DataFrame(0.0, index=close_prices.index, 
                             columns=close_prices.columns)
      weights['SPY'] = 0.5
      weights['AGG'] = 0.5
      return weights
  
  result = backtest_portfolio_strategy(
      strategy_func=my_portfolio_strategy,
      strategy_name='我的组合策略',
      market_scope=['CN'],  # 只在A股回测
  )
"""

import sys
import os
import time
import math
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable

warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(__file__))
from cross_regime_scheduler import (
    # 数据加载
    load_all_etf_data, load_all_market_data, load_cn_etf_data,
    fetch_risk_free_rate,
    # 常量
    INIT_CASH, FEES_US, FEES_HK, FEES_CN, SLIPPAGE,
    MAIN_START, MAIN_END, STRESS_START, STRESS_END,
    CN_MAIN_START, CN_MAIN_END, CN_STRESS_START, CN_STRESS_END,
    CN_RISK_FREE_RATE, HK_RISK_FREE_RATE,
    ALL_ASSETS_6, CN_ALL_ASSETS_6, HK_ALL_ASSETS_6,
    SAFE_ASSETS, RISK_ASSETS, CN_SAFE_ASSETS, CN_RISK_ASSETS,
    CN_ETF_MAP, LOCAL_CN_DIR,
    # 评分
    calculate_score,
    # 排行榜
    load_leaderboard, update_leaderboard_v3,
    # 邮件
    send_email,
)

LOCAL_CN_STOCKS_DIR = '/data/workspace/back_trader_stocks/a'

# A股个股交易费率
FEES_CN_STOCK = 0.001348  # 印花税+佣金 ≈ 0.1348%


# ================================================================
# 1. A股全量个股数据加载
# ================================================================
def load_cn_all_stocks(min_days: int = 500) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    加载A股全量个股数据（含成交量）
    
    Returns:
        (close_df, volume_df): 价格矩阵和成交量矩阵
    """
    stock_dir = Path(LOCAL_CN_STOCKS_DIR)
    
    if not stock_dir.exists():
        print(f"  ⚠️ A股个股目录不存在: {LOCAL_CN_STOCKS_DIR}")
        return pd.DataFrame(), pd.DataFrame()
    
    close_dict = {}
    volume_dict = {}
    loaded = 0
    skipped = 0
    
    for csv_file in sorted(stock_dir.glob('*.csv')):
        code = csv_file.stem  # e.g. 000001_XSHE
        try:
            df = pd.read_csv(csv_file, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            df.columns = [c.strip().capitalize() for c in df.columns]
            
            if len(df) < min_days:
                skipped += 1
                continue
            
            if 'Close' in df.columns:
                close_dict[code] = df['Close']
                volume_dict[code] = df.get('Volume', pd.Series(0, index=df.index))
                loaded += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    
    close_df = pd.DataFrame(close_dict).sort_index()
    volume_df = pd.DataFrame(volume_dict).sort_index()
    
    print(f"  📦 A股全量个股: 加载{loaded}只 (跳过{skipped}只, 门槛≥{min_days}天)")
    return close_df, volume_df


def load_cn_full_data() -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    加载A股完整数据（ETF + 全量个股）
    
    Returns:
        {
            'CN_ETF': {symbol: DataFrame, ...},
            'CN_STOCK': {symbol: DataFrame, ...},  # 全量512只
        }
    """
    result = {}
    
    # ETF
    cn_etf = load_cn_etf_data()
    if cn_etf:
        result['CN_ETF'] = cn_etf
    
    # 全量个股
    stock_dir = Path(LOCAL_CN_STOCKS_DIR)
    if stock_dir.exists():
        stock_data = {}
        for csv_file in sorted(stock_dir.glob('*.csv')):
            code = csv_file.stem
            try:
                df = pd.read_csv(csv_file, parse_dates=['Date'], index_col='Date')
                df = df.sort_index()
                df.columns = [c.strip().capitalize() for c in df.columns]
                if 'Volume' not in df.columns:
                    df['Volume'] = 0
                if len(df) >= 200:
                    stock_data[code] = df
            except Exception:
                continue
        result['CN_STOCK'] = stock_data
        print(f"  📦 A股全量: ETF {len(cn_etf)}只 + 个股 {len(stock_data)}只")
    
    return result


# ================================================================
# 2. 组合向量化回测引擎
# ================================================================
def run_portfolio_backtest_vec(
    etf_close: pd.DataFrame,
    stock_close: Optional[pd.DataFrame],
    stock_volume: Optional[pd.DataFrame],
    weights_df: pd.DataFrame,
    start_date: str,
    end_date: str,
    risk_free_rate: float = 0.02,
    market: str = 'CN',
    etf_fee_rate: float = FEES_CN,
    stock_fee_rate: float = FEES_CN_STOCK,
) -> Optional[Dict]:
    """
    组合策略向量化回测引擎
    
    与 run_backtest_vec 的核心区别：
    - run_backtest_vec: 每日只持有1只标的（holding: pd.Series of str）
    - run_portfolio_backtest_vec: 每日可持有多只标的（weights: pd.DataFrame of float）
    
    参数:
        etf_close: ETF价格矩阵 (N日 × M_ETF)
        stock_close: 个股价格矩阵 (N日 × M_Stock)，可选
        stock_volume: 个股成交量矩阵 (N日 × M_Stock)，可选（用于停牌过滤）
        weights_df: 每日持仓权重矩阵 (N日 × K标的)
                    列名必须在etf_close或stock_close的列中
                    每行之和应≈1.0
        start_date/end_date: 回测区间
        risk_free_rate: 无风险利率
        market: 市场标识
        etf_fee_rate: ETF交易费率
        stock_fee_rate: 个股交易费率
    
    返回:
        Dict: 回测结果（与run_backtest_vec格式兼容）
    """
    mask = (weights_df.index >= start_date) & (weights_df.index <= end_date)
    w = weights_df.loc[mask]
    
    if len(w) < 100:
        return None
    
    # T+1修正：权重使用前一天信号
    w = w.shift(1)
    w.iloc[0] = weights_df.iloc[0] if len(weights_df) > 0 else 0
    
    # 合并ETF和个股价格
    all_prices_dict = {}
    all_fee_map = {}  # 每列的费率
    
    if etf_close is not None:
        for col in etf_close.columns:
            all_prices_dict[col] = etf_close[col]
            all_fee_map[col] = etf_fee_rate
    
    if stock_close is not None:
        for col in stock_close.columns:
            all_prices_dict[col] = stock_close[col]
            all_fee_map[col] = stock_fee_rate
    
    all_prices = pd.DataFrame(all_prices_dict).sort_index()
    # 对齐到回测区间
    all_prices = all_prices.loc[all_prices.index.isin(w.index)]
    w = w.loc[w.index.isin(all_prices.index)]
    
    if len(w) < 100:
        return None
    
    # 计算日收益率
    daily_returns = all_prices.pct_change().fillna(0)
    
    # 停牌过滤：Volume=0的日子收益率设为0
    if stock_volume is not None:
        for col in stock_volume.columns:
            if col in daily_returns.columns:
                zero_vol_mask = stock_volume[col] == 0
                zero_vol_mask = zero_vol_mask.reindex(daily_returns.index, method='ffill').fillna(False)
                daily_returns.loc[zero_vol_mask, col] = 0.0
    
    # 涨跌停过滤：A股个股日收益>9.5%或<-9.5%视为涨跌停
    if market == 'CN' and stock_close is not None:
        for col in stock_close.columns:
            if col in daily_returns.columns:
                # 涨停不可买入 → 正收益cap在9.5%
                daily_returns[col] = daily_returns[col].clip(-0.095, 0.095)
    
    # 对齐列名
    common_cols = [c for c in w.columns if c in daily_returns.columns]
    if not common_cols:
        return None
    
    w_aligned = w[common_cols].fillna(0)
    ret_aligned = daily_returns[common_cols].fillna(0)
    
    # 组合日收益率 = Σ(权重_i × 日收益率_i)
    portfolio_returns = (w_aligned * ret_aligned).sum(axis=1)
    
    # ====== 换仓成本 ======
    # 每日权重变化 → 换仓量
    w_change = w_aligned.diff().abs().sum(axis=1) / 2  # 总换手率 = |Δw|/2
    w_change.iloc[0] = w_aligned.iloc[0].sum() / 2  # 首日建仓
    
    # 按ETF和个股分别计算换仓成本
    etf_cols = [c for c in common_cols if c in (etf_close.columns if etf_close is not None else [])]
    stock_cols = [c for c in common_cols if c in (stock_close.columns if stock_close is not None else [])]
    
    etf_change = w_aligned[etf_cols].diff().abs().sum(axis=1) / 2 if etf_cols else 0
    stock_change = w_aligned[stock_cols].diff().abs().sum(axis=1) / 2 if stock_cols else 0
    
    etf_change.iloc[0] = w_aligned[etf_cols].iloc[0].sum() / 2 if etf_cols else 0
    stock_change.iloc[0] = w_aligned[stock_cols].iloc[0].sum() / 2 if stock_cols else 0
    
    # 换仓成本 = ETF换手×ETF费率 + 个股换手×个股费率 + 滑点
    trading_cost = etf_change * (etf_fee_rate + SLIPPAGE) + stock_change * (stock_fee_rate + SLIPPAGE)
    portfolio_returns = portfolio_returns - trading_cost
    
    # ====== 核心指标 ======
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(w) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
    if n_years > 0 and total_return > -100:
        annual_return = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100
    else:
        annual_return = total_return
    
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100
    
    sharpe = (portfolio_returns.mean() - risk_free_rate / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    win_days = (portfolio_returns > 0).sum()
    total_active_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100
    
    # 年交易次数 = 年均换手率
    annual_turnover = w_change.sum() / max(n_years, 0.01)
    
    # 持仓分布
    avg_weights = w_aligned.mean()
    holding_distribution = (avg_weights / avg_weights.sum() * 100).to_dict() if avg_weights.sum() > 0 else {}
    
    # 年度收益
    yearly = {}
    for year, group in portfolio_returns.groupby(portfolio_returns.index.year):
        yr = (1 + group).prod() - 1
        yearly[year] = round(yr * 100, 2)
    
    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(annual_turnover, 1),
        'holding_distribution': {k: round(v, 1) for k, v in holding_distribution.items()},
        'yearly': yearly,
        'portfolio_returns': portfolio_returns,
        'n_years': round(n_years, 1),
    }


# ================================================================
# 3. 组合策略三层递进回测
# ================================================================
def backtest_portfolio_strategy(
    strategy_func: Callable,
    strategy_name: str = '组合策略',
    strategy_type: str = '组合策略',
    strategy_params: Dict = None,
    strategy_desc: str = '',
    source: str = '用户提交',
    market_scope: List[str] = None,
    strategy_kwargs: Dict = None,
) -> Dict:
    """
    组合策略专用回测入口 — 支持多标的同时持仓
    
    策略函数签名：
        def my_strategy(close_prices, stock_close=None, stock_volume=None, **kwargs) -> pd.DataFrame:
            '''
            参数:
                close_prices: ETF价格矩阵 (pd.DataFrame)
                stock_close: 个股价格矩阵 (pd.DataFrame, 可选)
                stock_volume: 个股成交量矩阵 (pd.DataFrame, 可选)
            返回:
                weights_df: 每日持仓权重矩阵 (pd.DataFrame)
                           index=日期, columns=标的代码, values=权重(0~1)
                           每行权重之和≈1.0
            '''
    
    三层递进架构：
        L1: 快速广筛 — ETF池6只+少量个股（50只），粗粒度权重
        L2: 中等验证 — ETF池+全量个股，完整权重，含交易成本
        L3: 高精度终验 — 与L2相同但增加压力测试
    """
    if strategy_params is None:
        strategy_params = {}
    if strategy_kwargs is None:
        strategy_kwargs = {}
    if market_scope is None:
        market_scope = ['CN']  # 组合策略默认只跑A股
    
    total_start = time.time()
    
    print(f"\n{'='*70}")
    print(f"  🔬 组合策略回测 - 三层递进架构")
    print(f"{'='*70}")
    print(f"  📋 策略名称: {strategy_name}")
    print(f"  📋 策略类型: {strategy_type}")
    print(f"  📋 策略来源: {source}")
    print(f"  📋 回测市场: {market_scope}")
    print(f"  🏗️  回测流程: L1快速广筛 → L2中等验证 → L3高精度终验")
    
    # ====== 加载数据 ======
    print(f"\n  📦 加载数据...")
    data_start = time.time()
    
    # ETF数据
    etf_close, _ = load_all_etf_data()
    risk_free_rate = fetch_risk_free_rate()
    
    # A股数据
    cn_etf_data = load_cn_etf_data()
    cn_etf_close = pd.DataFrame({sym: df['Close'] for sym, df in cn_etf_data.items()}).sort_index()
    
    # A股全量个股
    cn_stock_close, cn_stock_volume = load_cn_all_stocks(min_days=500)
    
    data_time = time.time() - data_start
    print(f"  ✅ 数据加载完成: {data_time:.1f}s")
    print(f"     A股ETF: {cn_etf_close.shape[1]}只")
    print(f"     A股个股: {cn_stock_close.shape[1]}只")
    
    # ====== 第1层：快速广筛 ======
    print(f"\n{'─'*70}")
    print(f"  ⚡ 第1层：快速广筛（ETF+少量个股，~10秒）")
    print(f"{'─'*70}")
    
    l1_start = time.time()
    
    # L1: 用ETF + 前50只个股（按成交额排序取前50，模拟大中盘）
    l1_stock_close = _select_top_stocks(cn_stock_close, cn_stock_volume, top_n=50)
    l1_stock_volume = cn_stock_volume[l1_stock_close.columns] if not l1_stock_close.empty else None
    
    l1_results = {}
    for market in market_scope:
        if market == 'CN':
            try:
                weights_df = strategy_func(
                    cn_etf_close, 
                    stock_close=l1_stock_close, 
                    stock_volume=l1_stock_volume,
                    **strategy_kwargs
                )
                result = run_portfolio_backtest_vec(
                    cn_etf_close, l1_stock_close, l1_stock_volume,
                    weights_df, CN_MAIN_START, CN_MAIN_END,
                    CN_RISK_FREE_RATE, 'CN'
                )
                if result:
                    l1_results[market] = result
                    print(f"     [A股] L1: 年化{result['annual_return']:+.2f}% | 回撤{result['max_drawdown']:.1f}% | 夏普{result['sharpe']:.2f}")
            except Exception as e:
                print(f"     [A股] L1异常: {e}")
                import traceback; traceback.print_exc()
    
    l1_time = time.time() - l1_start
    
    # L1淘汰判断
    any_l1_pass = False
    for market, r in l1_results.items():
        if r['annual_return'] >= -10 and r['max_drawdown'] <= 60:
            any_l1_pass = True
            break
    
    if not any_l1_pass:
        elapsed = time.time() - total_start
        print(f"\n  ❌ 第1层淘汰: 组合策略在所有市场均不达标")
        return {
            'passed': False,
            'eliminated_at': 'L1',
            'reason': '快速广筛未通过',
            'l1_time': l1_time,
            'total_time': elapsed,
            'strategy_name': strategy_name,
            'market_results': l1_results,
        }
    
    print(f"  ✅ 第1层通过 ({l1_time:.1f}s)")
    
    # ====== 第2层：中等精度验证 ======
    print(f"\n{'─'*70}")
    print(f"  🔍 第2层：中等精度验证（全量个股+评分，~60秒）")
    print(f"{'─'*70}")
    
    l2_start = time.time()
    
    # L2: 使用全量个股
    l2_results = {}
    for market in market_scope:
        if market == 'CN':
            try:
                weights_df = strategy_func(
                    cn_etf_close, 
                    stock_close=cn_stock_close, 
                    stock_volume=cn_stock_volume,
                    **strategy_kwargs
                )
                result = run_portfolio_backtest_vec(
                    cn_etf_close, cn_stock_close, cn_stock_volume,
                    weights_df, CN_MAIN_START, CN_MAIN_END,
                    CN_RISK_FREE_RATE, 'CN'
                )
                if result:
                    # 压力测试
                    stress_weights = strategy_func(
                        cn_etf_close, 
                        stock_close=cn_stock_close, 
                        stock_volume=cn_stock_volume,
                        **strategy_kwargs
                    )
                    stress_result = run_portfolio_backtest_vec(
                        cn_etf_close, cn_stock_close, cn_stock_volume,
                        stress_weights, CN_STRESS_START, CN_STRESS_END,
                        CN_RISK_FREE_RATE, 'CN'
                    )
                    
                    # 评分
                    score_result = calculate_score(result, stress_result, survivorship_bias=True)
                    
                    l2_results[market] = {
                        'main_result': result,
                        'stress_result': stress_result,
                        'score_result': score_result,
                    }
                    
                    print(f"     [A股] L2: 年化{result['annual_return']:+.2f}% | 回撤{result['max_drawdown']:.1f}% | "
                          f"夏普{result['sharpe']:.2f} | 评分{score_result['total_score']}分")
            except Exception as e:
                print(f"     [A股] L2异常: {e}")
                import traceback; traceback.print_exc()
    
    l2_time = time.time() - l2_start
    
    # L2淘汰判断
    any_l2_pass = False
    for market, mr in l2_results.items():
        score = mr['score_result']['total_score']
        hard_fail = mr['score_result'].get('hard_fail', False)
        if score > 0 and not hard_fail:
            any_l2_pass = True
            break
    
    if not any_l2_pass:
        elapsed = time.time() - total_start
        print(f"\n  ❌ 第2层淘汰: 组合策略评分未通过")
        return {
            'passed': False,
            'eliminated_at': 'L2',
            'reason': '中等验证未通过',
            'l1_time': l1_time,
            'l2_time': l2_time,
            'total_time': elapsed,
            'strategy_name': strategy_name,
            'market_results': l2_results,
        }
    
    print(f"  ✅ 第2层通过 ({l2_time:.1f}s)")
    
    # ====== 第3层：高精度终验 ======
    # 组合策略的L3与L2相同（已经是完整回测），但增加详细分析
    print(f"\n{'─'*70}")
    print(f"  🏅 第3层：高精度终验（详细分析+入榜评估）")
    print(f"{'─'*70}")
    
    l3_start = time.time()
    
    final_results = {}
    for market, mr in l2_results.items():
        main_result = mr['main_result']
        score_result = mr['score_result']
        stress_result = mr['stress_result']
        
        final_results[market] = mr
        
        # 年度收益展示
        if 'yearly' in main_result:
            print(f"\n  📊 [{market}] 年度收益:")
            for year, ret in sorted(main_result['yearly'].items()):
                bar = '█' * max(0, int(ret / 5))
                sign = '+' if ret >= 0 else ''
                print(f"     {year}: {sign}{ret:.2f}% {bar}")
        
        # 入榜
        passed_market = score_result['total_score'] > 0 and not score_result.get('hard_fail', False)
        if passed_market:
            strategy_entry = {
                'strategy_name': strategy_name,
                'strategy_params': strategy_params,
                'strategy_description': strategy_desc,
                'strategy_type': strategy_type,
                'source': source,
                'annual_return': main_result['annual_return'],
                'sharpe': main_result['sharpe'],
                'max_drawdown': main_result['max_drawdown'],
                'calmar': main_result['calmar'],
                'win_rate': main_result['win_rate'],
                'profit_factor': main_result['profit_factor'],
                'avg_trades_per_year': main_result['avg_trades_per_year'],
                'holding_distribution': main_result.get('holding_distribution', {}),
                'stress_test': {
                    'annual_return': stress_result['annual_return'] if stress_result else 0,
                    'max_drawdown': stress_result['max_drawdown'] if stress_result else 0,
                } if stress_result else None,
                'cross_robust': score_result.get('cross_robust', False),
                'survivorship_bias_flag': True,
                'pine_script_rejected': False,
                'portability_score': 5,  # 组合策略可移植性中等
                'market': market,
            }
            update_leaderboard_v3(strategy_entry, score_result, market)
            print(f"  🆕 [{market}] 已更新排行榜")
    
    l3_time = time.time() - l3_start
    total_time = time.time() - total_start
    
    # ====== 汇总 ======
    print(f"\n{'='*70}")
    print(f"  🏁 组合策略回测汇总")
    print(f"{'='*70}")
    print(f"  策略: {strategy_name}")
    any_passed = any(
        mr['score_result']['total_score'] > 0 and not mr['score_result'].get('hard_fail', False)
        for mr in final_results.values()
    )
    print(f"  结果: {'✅ 通过' if any_passed else '❌ 未通过'}")
    print(f"  耗时分布: L1={l1_time:.1f}s + L2={l2_time:.1f}s + L3={l3_time:.1f}s = {total_time:.1f}s")
    
    return {
        'passed': any_passed,
        'eliminated_at': None,
        'strategy_name': strategy_name,
        'strategy_type': strategy_type,
        'strategy_params': strategy_params,
        'market_summaries': {
            market: {
                'passed': mr['score_result']['total_score'] > 0 and not mr['score_result'].get('hard_fail', False),
                'score': mr['score_result']['total_score'],
                'annual_return': mr['main_result']['annual_return'],
                'sharpe': mr['main_result']['sharpe'],
                'max_drawdown': mr['main_result']['max_drawdown'],
                'calmar': mr['main_result']['calmar'],
                'win_rate': mr['main_result']['win_rate'],
                'profit_factor': mr['main_result']['profit_factor'],
                'avg_trades_per_year': mr['main_result']['avg_trades_per_year'],
                'stress_test': {
                    'annual_return': mr['stress_result']['annual_return'] if mr['stress_result'] else 0,
                    'max_drawdown': mr['stress_result']['max_drawdown'] if mr['stress_result'] else 0,
                } if mr['stress_result'] else None,
                'score_detail': mr['score_result'],
            }
            for market, mr in final_results.items()
        },
        'market_results': final_results,
        'l1_time': l1_time,
        'l2_time': l2_time,
        'l3_time': l3_time,
        'total_time': total_time,
    }


def _select_top_stocks(stock_close: pd.DataFrame, stock_volume: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """按平均成交额选取前N只个股（用于L1快速筛选）"""
    if stock_close.empty:
        return stock_close
    
    avg_turnover = (stock_close * stock_volume).mean()
    top_codes = avg_turnover.nlargest(min(top_n, len(avg_turnover))).index.tolist()
    return stock_close[top_codes]
