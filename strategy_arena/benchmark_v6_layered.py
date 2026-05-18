#!/usr/bin/env python3
"""
分层递进回测架构 vs 原始逐日循环 - 真实耗时对比测试

测试内容：
1. 向量化回测引擎 vs 逐日循环回测引擎 - 结果一致性验证
2. 第1层快速广筛耗时实测
3. 第2层中等精度验证耗时实测
4. 第3层高精度终验耗时实测
5. 与v5（原始逐日循环全量回测）的端到端耗时对比
"""

import sys
import os
import time
import json
import numpy as np
import pandas as pd
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cross_regime_scheduler import (
    # 数据加载
    load_all_market_data, load_all_etf_data,
    # 策略函数
    strategy_gem_rotation, strategy_dual_momentum, strategy_bollinger_reversion,
    strategy_dividend_rotation, strategy_macro_rotation, strategy_macd_rotation,
    strategy_rsi_rotation, strategy_all_weather, strategy_multi_asset_rotation,
    # 原始逐日循环回测
    run_backtest, run_backtest_single_stock, run_batch_backtest,
    # 向量化回测引擎
    run_backtest_vec, run_backtest_single_stock_vec, run_batch_backtest_vec,
    # 分层架构
    _layer1_fast_screen, _layer2_medium_validate, _layer3_precision_finaltest,
    generate_strategy_variants, calculate_score,
    # 常量
    MAIN_START, MAIN_END, STRESS_START, STRESS_END,
    HK_MAIN_START, HK_MAIN_END, HK_STRESS_START, HK_STRESS_END,
    CN_MAIN_START, CN_MAIN_END, CN_STRESS_START, CN_STRESS_END,
    HK_RISK_FREE_RATE, CN_RISK_FREE_RATE,
    RISK_ASSETS, SAFE_ASSETS, ALL_ASSETS_6,
    INIT_CASH, FEES_US, FEES_HK, FEES_CN, SLIPPAGE,
)

# 美股无风险利率（与cross_regime_scheduler中的默认值一致）
RISK_FREE_RATE = 0.045


def test_engine_consistency():
    """测试向量化引擎与逐日循环引擎的结果一致性"""
    print(f"\n{'='*70}")
    print(f"  🔬 测试1: 向量化引擎 vs 逐日循环引擎 - 结果一致性")
    print(f"{'='*70}")
    
    # 加载ETF数据
    close_prices, _ = load_all_etf_data()
    if close_prices is None or close_prices.empty:
        print("  ❌ 无法加载ETF数据")
        return False
    
    # 测试3个典型策略
    test_strategies = [
        {
            'name': 'GEM4资产_12M',
            'func': strategy_gem_rotation,
            'kwargs': {'lookback_months': 12, 'buffer_days': 0, 'risk_assets': RISK_ASSETS, 'safe_assets': SAFE_ASSETS},
        },
        {
            'name': '双重动量_9M_阈值0%',
            'func': strategy_dual_momentum,
            'kwargs': {'lookback_months': 9, 'buffer_days': 0, 'abs_momentum_threshold': 0},
        },
        {
            'name': 'RSI14_30/70轮动',
            'func': strategy_rsi_rotation,
            'kwargs': {'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70, 'buffer_days': 3},
        },
    ]
    
    all_consistent = True
    for strat in test_strategies:
        holding = strat['func'](close_prices, **strat['kwargs'])
        
        # 原始逐日循环
        t0 = time.time()
        loop_result = run_backtest(close_prices, holding, MAIN_START, MAIN_END, RISK_FREE_RATE, 'US')
        loop_time = time.time() - t0
        
        # 向量化引擎
        t0 = time.time()
        vec_result = run_backtest_vec(close_prices, holding, MAIN_START, MAIN_END, RISK_FREE_RATE, 'US')
        vec_time = time.time() - t0
        
        if loop_result is None or vec_result is None:
            print(f"  ❌ {strat['name']}: 回测失败")
            all_consistent = False
            continue
        
        # 对比核心指标
        metrics = ['annual_return', 'max_drawdown', 'sharpe', 'calmar', 'win_rate', 'profit_factor', 'avg_trades_per_year']
        print(f"\n  📊 {strat['name']}:")
        print(f"     {'指标':<20} {'逐日循环':>12} {'向量化':>12} {'偏差':>10} {'加速比':>8}")
        print(f"     {'─'*62}")
        
        strat_ok = True
        for m in metrics:
            lv = loop_result.get(m, 0)
            vv = vec_result.get(m, 0)
            diff = abs(lv - vv)
            pct = diff / max(abs(lv), 0.01) * 100
            ok = "✅" if pct < 5 else "❌"
            if pct >= 5:
                strat_ok = False
                all_consistent = False
            print(f"     {m:<20} {lv:>12.2f} {vv:>12.2f} {pct:>8.2f}% {ok}")
        
        speedup = loop_time / max(vec_time, 0.0001)
        print(f"     {'耗时':<20} {loop_time*1000:>10.1f}ms {vec_time*1000:>10.1f}ms {'':>10} {speedup:>6.1f}x")
        
        if strat_ok:
            print(f"     ✅ 结果一致（偏差<5%），加速{speedup:.1f}x")
        else:
            print(f"     ❌ 存在>5%偏差，需排查")
    
    return all_consistent


def test_single_stock_engine_consistency():
    """测试个股向量化引擎与逐日循环引擎的结果一致性"""
    print(f"\n{'='*70}")
    print(f"  🔬 测试2: 个股回测引擎 - 结果一致性")
    print(f"{'='*70}")
    
    # 加载美股个股数据
    us_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'back_trader_stocks', 'us')
    test_stocks = ['AAPL', 'MSFT', 'GOOGL']
    
    close_prices, _ = load_all_etf_data()
    if close_prices is None:
        print("  ❌ 无法加载ETF数据")
        return False
    
    all_consistent = True
    for sym in test_stocks:
        csv_path = os.path.join(us_dir, f'{sym}.csv')
        if not os.path.exists(csv_path):
            print(f"  ⚠️ {sym} 数据不存在，跳过")
            continue
        
        df = pd.read_csv(csv_path, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        
        # 构建个股+SHY的mini2
        shy = close_prices['SHY'].reindex(df.index).ffill().bfill()
        mini2 = pd.DataFrame({sym: df['Close'], 'SHY': shy}).dropna()
        
        # 生成信号
        holding = strategy_gem_rotation(mini2, lookback_months=12, buffer_days=0,
                                        risk_assets=[sym], safe_assets=['SHY'])
        h_bool = (holding == sym).astype(float)
        
        # 原始逐日循环
        t0 = time.time()
        loop_result = run_backtest_single_stock(df, h_bool, MAIN_START, MAIN_END, RISK_FREE_RATE, 'US')
        loop_time = time.time() - t0
        
        # 向量化引擎
        t0 = time.time()
        vec_result = run_backtest_single_stock_vec(df, h_bool, MAIN_START, MAIN_END, RISK_FREE_RATE, 'US')
        vec_time = time.time() - t0
        
        if loop_result is None or vec_result is None:
            print(f"  ❌ {sym}: 回测失败")
            all_consistent = False
            continue
        
        metrics = ['annual_return', 'max_drawdown', 'sharpe', 'calmar', 'win_rate', 'profit_factor']
        print(f"\n  📊 {sym}:")
        print(f"     {'指标':<20} {'逐日循环':>12} {'向量化':>12} {'偏差':>10}")
        print(f"     {'─'*56}")
        
        for m in metrics:
            lv = loop_result.get(m, 0)
            vv = vec_result.get(m, 0)
            diff = abs(lv - vv)
            pct = diff / max(abs(lv), 0.01) * 100
            ok = "✅" if pct < 5 else "❌"
            if pct >= 5:
                all_consistent = False
            print(f"     {m:<20} {lv:>12.2f} {vv:>12.2f} {pct:>8.2f}% {ok}")
        
        speedup = loop_time / max(vec_time, 0.0001)
        print(f"     耗时: 逐日{loop_time*1000:.1f}ms → 向量化{vec_time*1000:.1f}ms (加速{speedup:.1f}x)")
    
    return all_consistent


def test_layered_architecture_speed():
    """测试分层递进架构各层耗时"""
    print(f"\n{'='*70}")
    print(f"  🔬 测试3: 分层递进架构 - 各层耗时实测")
    print(f"{'='*70}")
    
    # 加载全市场数据
    print(f"\n  📦 加载全市场数据...")
    data_start = time.time()
    all_market_data = load_all_market_data()
    data_time = time.time() - data_start
    print(f"  ✅ 数据加载完成: {data_time:.1f}s")
    
    close_prices, _ = load_all_etf_data()
    if close_prices is None:
        print("  ❌ 无法加载ETF数据")
        return
    
    # 生成策略变体
    variants = generate_strategy_variants()
    print(f"\n  🧬 策略变体: {len(variants)}个")
    
    # ====== 第1层：快速广筛 ======
    print(f"\n{'─'*70}")
    print(f"  ⚡ 第1层：快速广筛（向量化，仅ETF池）")
    print(f"{'─'*70}")
    
    l1_start = time.time()
    l1_passed, l1_eliminated = _layer1_fast_screen(
        variants, close_prices, all_market_data, RISK_FREE_RATE)
    l1_time = time.time() - l1_start
    
    print(f"\n  📊 第1层结果:")
    print(f"     通过: {len(l1_passed)}个 | 淘汰: {len(l1_eliminated)}个")
    print(f"     耗时: {l1_time:.1f}s")
    print(f"     平均: {l1_time/max(len(variants),1)*1000:.1f}ms/策略")
    
    # ====== 第2层：中等精度验证 ======
    print(f"\n{'─'*70}")
    print(f"  🔍 第2层：中等精度验证（向量化+评分）")
    print(f"{'─'*70}")
    
    l2_start = time.time()
    l2_passed, l2_eliminated = _layer2_medium_validate(
        l1_passed, close_prices, all_market_data, RISK_FREE_RATE)
    l2_time = time.time() - l2_start
    
    print(f"\n  📊 第2层结果:")
    print(f"     通过: {len(l2_passed)}个 | 淘汰: {len(l2_eliminated)}个")
    print(f"     耗时: {l2_time:.1f}s")
    print(f"     平均: {l2_time/max(len(l1_passed),1)*1000:.1f}ms/策略")
    
    # ====== 第3层：高精度终验 ======
    print(f"\n{'─'*70}")
    print(f"  🏅 第3层：高精度终验（逐日循环+多标的）")
    print(f"{'─'*70}")
    
    l3_start = time.time()
    l3_results = _layer3_precision_finaltest(
        l2_passed, close_prices, all_market_data, RISK_FREE_RATE, False)
    l3_time = time.time() - l3_start
    
    print(f"\n  📊 第3层结果:")
    print(f"     完成终验: {len(l3_results)}个策略")
    print(f"     耗时: {l3_time:.1f}s")
    
    # ====== 汇总 ======
    total_layered = data_time + l1_time + l2_time + l3_time
    
    print(f"\n{'='*70}")
    print(f"  📊 分层架构总耗时")
    print(f"{'='*70}")
    print(f"     数据加载:     {data_time:>8.1f}s ({data_time/total_layered*100:>5.1f}%)")
    print(f"     第1层广筛:    {l1_time:>8.1f}s ({l1_time/total_layered*100:>5.1f}%)")
    print(f"     第2层验证:    {l2_time:>8.1f}s ({l2_time/total_layered*100:>5.1f}%)")
    print(f"     第3层终验:    {l3_time:>8.1f}s ({l3_time/total_layered*100:>5.1f}%)")
    print(f"     {'─'*40}")
    print(f"     总计:         {total_layered:>8.1f}s ({total_layered/60:.1f}分钟)")
    
    return {
        'data_time': data_time,
        'l1_time': l1_time,
        'l2_time': l2_time,
        'l3_time': l3_time,
        'total_layered': total_layered,
        'l1_passed': len(l1_passed),
        'l1_eliminated': len(l1_eliminated),
        'l2_passed': len(l2_passed),
        'l2_eliminated': len(l2_eliminated),
        'l3_count': len(l3_results),
        'total_variants': len(variants),
    }


def test_v5_full_scan_speed():
    """测试v5原始全量逐日循环回测的耗时（仅测ETF部分）"""
    print(f"\n{'='*70}")
    print(f"  🔬 测试4: v5原始全量回测耗时（逐日循环，三市场）")
    print(f"{'='*70}")
    
    all_market_data = load_all_market_data()
    close_prices, _ = load_all_etf_data()
    if close_prices is None:
        print("  ❌ 无法加载ETF数据")
        return None
    
    variants = generate_strategy_variants()
    print(f"\n  🧬 策略变体: {len(variants)}个")
    
    v5_start = time.time()
    v5_results_count = 0
    v5_passed = 0
    v5_rejected = 0
    
    for i, strategy in enumerate(variants):
        name = strategy['name']
        
        try:
            # 三市场逐日循环回测
            for market in ['US', 'HK', 'CN']:
                if market == 'US':
                    cp = close_prices
                    start, end, rf = MAIN_START, MAIN_END, RISK_FREE_RATE
                elif market == 'HK':
                    hk_stock_data = all_market_data.get('HK_STOCK', {})
                    if not hk_stock_data:
                        continue
                    hk_close_dict = {sym: df['Close'] for sym, df in hk_stock_data.items()}
                    cp = pd.DataFrame(hk_close_dict).sort_index().loc[HK_MAIN_START:HK_MAIN_END]
                    if cp.empty or len(cp) < 100:
                        continue
                    start, end, rf = HK_MAIN_START, HK_MAIN_END, HK_RISK_FREE_RATE
                elif market == 'CN':
                    cn_etf_data = all_market_data.get('CN_ETF', {})
                    if not cn_etf_data:
                        continue
                    cn_close_dict = {sym: df['Close'] for sym, df in cn_etf_data.items()}
                    cp = pd.DataFrame(cn_close_dict).sort_index().loc[CN_MAIN_START:CN_MAIN_END]
                    if cp.empty or len(cp) < 100:
                        continue
                    start, end, rf = CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE
                
                try:
                    holding = strategy['func'](cp, **strategy['kwargs'])
                    result = run_backtest(cp, holding, start, end, rf, market)
                    if result:
                        stress = run_backtest(cp, holding, 
                                             STRESS_START if market == 'US' else (HK_STRESS_START if market == 'HK' else CN_STRESS_START),
                                             STRESS_END if market == 'US' else (HK_STRESS_END if market == 'HK' else CN_STRESS_END),
                                             rf, market)
                        score = calculate_score(result, stress, market != 'US')
                        if score['total_score'] > 0 and not score['hard_fail']:
                            v5_passed += 1
                        else:
                            v5_rejected += 1
                        v5_results_count += 1
                except Exception:
                    continue
        except Exception:
            continue
        
        if (i + 1) % 20 == 0:
            elapsed = time.time() - v5_start
            eta = elapsed / (i + 1) * (len(variants) - i - 1)
            print(f"  ⏳ [{i+1}/{len(variants)}] 已耗时{elapsed:.1f}s, 预计剩余{eta:.0f}s")
    
    v5_total = time.time() - v5_start
    
    print(f"\n  📊 v5全量回测结果:")
    print(f"     完成策略: {v5_results_count}个市场×策略组合")
    print(f"     通过: {v5_passed}个 | 淘汰: {v5_rejected}个")
    print(f"     总耗时: {v5_total:.1f}s ({v5_total/60:.1f}分钟)")
    print(f"     平均: {v5_total/max(len(variants),1):.2f}s/策略")
    
    return {
        'v5_total': v5_total,
        'v5_passed': v5_passed,
        'v5_rejected': v5_rejected,
        'v5_per_strategy': v5_total / max(len(variants), 1),
        'total_variants': len(variants),
    }


def test_batch_backtest_speed():
    """测试批量多标的回测耗时对比"""
    print(f"\n{'='*70}")
    print(f"  🔬 测试5: 批量多标的回测 - v5逐日循环 vs v6向量化")
    print(f"{'='*70}")
    
    all_market_data = load_all_market_data()
    close_prices, _ = load_all_etf_data()
    if close_prices is None:
        print("  ❌ 无法加载ETF数据")
        return
    
    # 测试3个典型策略
    test_strategies = [
        {
            'name': 'GEM4资产_12M',
            'func': strategy_gem_rotation,
            'kwargs': {'lookback_months': 12, 'buffer_days': 0, 'risk_assets': RISK_ASSETS, 'safe_assets': SAFE_ASSETS},
        },
        {
            'name': '双重动量_9M_阈值0%',
            'func': strategy_dual_momentum,
            'kwargs': {'lookback_months': 9, 'buffer_days': 0, 'abs_momentum_threshold': 0},
        },
        {
            'name': 'RSI14_30/70轮动',
            'func': strategy_rsi_rotation,
            'kwargs': {'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70, 'buffer_days': 3},
        },
    ]
    
    for strat in test_strategies:
        print(f"\n  📊 {strat['name']}:")
        
        # v5逐日循环版
        t0 = time.time()
        v5_result = run_batch_backtest(all_market_data, strat['func'], strat['kwargs'], RISK_FREE_RATE)
        v5_time = time.time() - t0
        
        # v6向量化版
        t0 = time.time()
        v6_result = run_batch_backtest_vec(all_market_data, strat['func'], strat['kwargs'], RISK_FREE_RATE)
        v6_time = time.time() - t0
        
        v5_count = v5_result.get('symbol_count', 0) if v5_result else 0
        v6_count = v6_result.get('symbol_count', 0) if v6_result else 0
        
        speedup = v5_time / max(v6_time, 0.001)
        
        print(f"     v5(逐日循环): {v5_time:.1f}s | {v5_count}只标的")
        print(f"     v6(向量化):   {v6_time:.1f}s | {v6_count}只标的")
        print(f"     加速比: {speedup:.1f}x")
        
        # 结果偏差
        if v5_result and v6_result and v5_result.get('main_result') and v6_result.get('main_result'):
            v5_ann = v5_result['main_result'].get('annual_return', 0)
            v6_ann = v6_result['main_result'].get('annual_return', 0)
            v5_dd = v5_result['main_result'].get('max_drawdown', 0)
            v6_dd = v6_result['main_result'].get('max_drawdown', 0)
            print(f"     年化偏差: {abs(v5_ann - v6_ann):.2f}% | 回撤偏差: {abs(v5_dd - v6_dd):.2f}%")


def main():
    """主测试流程"""
    print(f"\n{'='*70}")
    print(f"  🚀 分层递进回测架构 (v6) - 真实耗时对比测试")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    
    results = {}
    
    # 测试1: 引擎一致性
    consistent = test_engine_consistency()
    results['engine_consistent'] = consistent
    
    # 测试2: 个股引擎一致性
    stock_consistent = test_single_stock_engine_consistency()
    results['stock_engine_consistent'] = stock_consistent
    
    # 测试3: 分层架构各层耗时
    layered_stats = test_layered_architecture_speed()
    results['layered'] = layered_stats
    
    # 测试4: v5全量回测耗时
    v5_stats = test_v5_full_scan_speed()
    results['v5'] = v5_stats
    
    # 测试5: 批量多标的耗时对比
    test_batch_backtest_speed()
    
    # ====== 最终对比汇总 ======
    if layered_stats and v5_stats:
        print(f"\n{'='*70}")
        print(f"  🏁 最终对比汇总")
        print(f"{'='*70}")
        
        v5_total = v5_stats['v5_total']
        v6_total = layered_stats['total_layered']
        speedup = v5_total / max(v6_total, 0.01)
        
        print(f"")
        print(f"  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │              v5 vs v6 端到端耗时对比                      │")
        print(f"  ├─────────────────────────────────────────────────────────┤")
        print(f"  │  v5(逐日循环全量)  │  {v5_total:>7.1f}s ({v5_total/60:>5.1f}分钟)              │")
        print(f"  │  v6(分层递进)      │  {v6_total:>7.1f}s ({v6_total/60:>5.1f}分钟)              │")
        print(f"  │  加速比            │  {speedup:>7.1f}x                          │")
        print(f"  ├─────────────────────────────────────────────────────────┤")
        print(f"  │  v5每策略          │  {v5_stats['v5_per_strategy']:>7.2f}s                          │")
        print(f"  │  v6第1层广筛/策略  │  {layered_stats['l1_time']/max(layered_stats['total_variants'],1):>7.3f}s                          │")
        print(f"  │  v6第2层验证/策略  │  {layered_stats['l2_time']/max(layered_stats['l1_passed'],1):>7.3f}s                          │")
        print(f"  │  v6第3层终验/策略  │  {layered_stats['l3_time']/max(layered_stats['l2_passed'],1):>7.3f}s                          │")
        print(f"  ├─────────────────────────────────────────────────────────┤")
        print(f"  │  引擎一致性        │  {'✅ 通过' if consistent and stock_consistent else '❌ 存在偏差'}                          │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        
        print(f"\n  📊 分层淘汰漏斗:")
        print(f"     全部变体:  {layered_stats['total_variants']:>4}个")
        print(f"       ↓ 第1层广筛（淘汰{layered_stats['l1_eliminated']}个）")
        print(f"     通过第1层: {layered_stats['l1_passed']:>4}个")
        print(f"       ↓ 第2层验证（淘汰{layered_stats['l2_eliminated']}个）")
        print(f"     通过第2层: {layered_stats['l2_passed']:>4}个")
        print(f"       ↓ 第3层终验")
        print(f"     最终入榜: {layered_stats['l3_count']:>4}个")
        
        # 保存结果
        report = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'v5_total_seconds': round(v5_total, 1),
            'v6_total_seconds': round(v6_total, 1),
            'speedup': round(speedup, 1),
            'engine_consistent': consistent and stock_consistent,
            'funnel': {
                'total': layered_stats['total_variants'],
                'l1_passed': layered_stats['l1_passed'],
                'l2_passed': layered_stats['l2_passed'],
                'l3_final': layered_stats['l3_count'],
            },
            'layer_times': {
                'data': round(layered_stats['data_time'], 1),
                'l1_fast': round(layered_stats['l1_time'], 1),
                'l2_medium': round(layered_stats['l2_time'], 1),
                'l3_precision': round(layered_stats['l3_time'], 1),
            },
        }
        
        report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                   'benchmark_v6_result.json')
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  📄 报告已保存: {report_path}")
    
    print(f"\n{'='*70}")
    print(f"  ✅ 测试完成!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
