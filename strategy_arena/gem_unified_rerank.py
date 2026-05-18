#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一回测重评：牛市/全局排行榜策略 + GEM增强策略
================================================
对当前排行榜历史前5策略 + GEM增强策略统一回测，使用shift(1)修正后的真实数据，
按牛市评分体系重新排名，生成新排行榜。

策略清单：
  排行榜现有5个:
    1. GEM波动率加权-仅缩仓(25/35)
    2. GEM日度9M纯策略
    3. RSI回调买入策略(牛市专用)
    4. MACD金叉+趋势确认策略
    5. Dual Momentum双动量策略

  GEM增强策略(修正穿越后):
    6. 日度9M基准(shift(1)修正)
    7. VIX缩仓(25/35)
    8. VIX缩仓(20/28)极早版
    9. 连续2天+3d缓冲
    10. 日度9M+3d缓冲
    11. 简化GEM日度9M(SPY/AGG/SHY)
"""

import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# 导入GEM模块
from gem_enhanced_backtest import (
    load_etf_data, load_vix_data,
    gem_rotation_baseline, gem_vol_weighted,
    gem_dual_signal_consecutive, gem_dual_signal_threshold,
    run_backtest_enhanced,
    INIT_CASH, FEES, SLIPPAGE, RISK_FREE_RATE,
    MAIN_START, MAIN_END,
)

# 导入评分模块
from strategy_ranker import (
    compute_total_score, classify_strategy, build_leaderboard_entry,
    load_leaderboard, save_leaderboard, update_leaderboard
)


# ================================================================
# 配置
# ================================================================
RISK_ASSETS = ['SPY', 'VEA']
SAFE_ASSETS = ['AGG', 'SHY']
TRAIN_START = '2019-01-01'
TRAIN_END = '2022-12-31'
TEST_START = '2023-01-01'
TEST_END = '2024-12-31'


# ================================================================
# GEM ETF轮动策略回测 + 评分
# ================================================================
def backtest_gem_strategy(name, holding, close_prices, position_ratio=None,
                          description='', params=None, market='us'):
    """
    对GEM轮动策略执行完整回测+评分。
    run_backtest_enhanced内部已自动shift(1)修正数据穿越。
    """
    # 主回测
    main_result = run_backtest_enhanced(
        close_prices, holding, MAIN_START, MAIN_END,
        position_ratio=position_ratio
    )

    # 训练集回测
    train_result = run_backtest_enhanced(
        close_prices, holding, TRAIN_START, TRAIN_END,
        position_ratio=position_ratio
    )

    # 测试集回测
    test_result = run_backtest_enhanced(
        close_prices, holding, TEST_START, TEST_END,
        position_ratio=position_ratio
    )

    if not main_result:
        print(f"  ❌ {name}: 主回测失败")
        return None

    # 过拟合检测（多维度综合衰减）
    overfit_info = _check_overfit(train_result, test_result, main_result)

    # 跨周期鲁棒性
    cross_robust = overfit_info['composite_decay'] > -30  # 综合衰减>-30%即通过

    # 计算评分（V3.1：含月度稳定性）
    score = compute_total_score(
        annual_return=main_result['annual_return'],
        sharpe=main_result['sharpe'],
        max_drawdown=abs(main_result['max_drawdown']),
        profit_factor=main_result['profit_factor'],
        win_rate=main_result['win_rate'],
        cross_period_robust=cross_robust,
        survivorship_bias=True,
        monthly_positive_rate=main_result.get('monthly_positive_rate', None),
    )

    # 硬性条件：回撤>25%得0分
    if abs(main_result['max_drawdown']) > 25:
        score['total_score'] = 0

    entry = {
        'strategy_name': name,
        'source_link': 'local:gem_unified_rerank.py',
        'fingerprint': name,  # 简化：用名称做指纹
        'fingerprint_short': name[:8],
        'strategy_type': classify_strategy(name),
        'total_score': score['total_score'],
        'score_detail': score,
        'annual_return': round(main_result['annual_return'], 2),
        'sharpe': round(main_result['sharpe'], 2),
        'max_drawdown': round(main_result['max_drawdown'], 2),
        'profit_factor': round(main_result['profit_factor'], 2),
        'win_rate': round(main_result['win_rate'], 2),
        'avg_trades_per_year': round(main_result['avg_trades_per_year'], 1),
        'calmar': round(main_result.get('calmar', 0), 2),
        'strategy_params': params or {},
        'strategy_description': description,
        'cross_period_robust': cross_robust,
        'robust_tag': '✅' if cross_robust else '',
        'survivorship_bias': True,
        'bias_tag': '⚠️',
        'pine_script_rejected': False,
        'portability_score': 10,
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'first_listed_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'removal_reason': '',
        'stress_annual': round(test_result['annual_return'], 2) if test_result else 0,
        'stress_dd': round(abs(test_result['max_drawdown']), 2) if test_result else 0,
        'market': market,
        'n_stocks': len(close_prices.columns),
        'overfit_info': overfit_info,
    }

    return entry


def _check_overfit(train_result, test_result, main_result):
    """多维度综合过拟合检测"""
    if not train_result or not test_result:
        return {'composite_decay': 0, 'details': '数据不足'}

    # 收益衰减
    train_ar = train_result['annual_return']
    test_ar = test_result['annual_return']
    return_decay = (test_ar - train_ar) / max(abs(train_ar), 0.01) * 100

    # 夏普衰减
    train_sharpe = train_result['sharpe']
    test_sharpe = test_result['sharpe']
    sharpe_decay = (test_sharpe - train_sharpe) / max(abs(train_sharpe), 0.01) * 100

    # 回撤衰减（测试集回撤更大是负面的）
    train_dd = abs(train_result['max_drawdown'])
    test_dd = abs(test_result['max_drawdown'])
    dd_decay = -(test_dd - train_dd) / max(train_dd, 0.01) * 100  # 回撤增大的方向为负

    # Calmar衰减
    train_calmar = train_result.get('calmar', 0)
    test_calmar = test_result.get('calmar', 0)
    calmar_decay = (test_calmar - train_calmar) / max(abs(train_calmar), 0.01) * 100

    # 综合衰减（加权：收益40% + 夏普30% + 回撤20% + Calmar10%）
    composite = return_decay * 0.4 + sharpe_decay * 0.3 + dd_decay * 0.2 + calmar_decay * 0.1

    return {
        'return_decay': round(return_decay, 1),
        'sharpe_decay': round(sharpe_decay, 1),
        'dd_decay': round(dd_decay, 1),
        'calmar_decay': round(calmar_decay, 1),
        'composite_decay': round(composite, 1),
        'train_annual': round(train_ar, 2),
        'test_annual': round(test_ar, 2),
        'train_sharpe': round(train_sharpe, 2),
        'test_sharpe': round(test_sharpe, 2),
        'train_dd': round(train_dd, 2),
        'test_dd': round(test_dd, 2),
    }


# ================================================================
# 非GEM策略回测（通过run_backtest.py跑个股）
# ================================================================
def backtest_individual_stock_strategy(name, strategy_file, market='us', max_stocks=30):
    """对个股策略执行回测"""
    from strategy_scheduler import _execute_backtest

    result = _execute_backtest(strategy_file, market, max_stocks=max_stocks)

    if not result:
        print(f"  ❌ {name}: 回测失败")
        return None

    main = result.get('main_period', {})
    stress = result.get('stress_period', {})
    robust = result.get('cross_period_robust', False)
    bias = result.get('survivorship_bias_flag', True)

    if not main:
        print(f"  ❌ {name}: 无主回测结果")
        return None

    strategy_info = {
        'strategy_name': name,
        'source_link': f'local:{os.path.basename(strategy_file)}',
        'fingerprint': name,
        'fingerprint_short': name[:8],
        'strategy_code': '',
        'description': '',
        'portability_score': 10,
        'pine_script_rejected': False,
        'strategy_params': main.get('strategy_params', {}),
    }

    entry = build_leaderboard_entry(result, strategy_info)

    if entry is None:
        # 手动构建废弃条目
        annual = main.get('mean_annual_return', 0)
        sharpe = main.get('mean_sharpe', 0)
        dd = main.get('mean_max_drawdown', 0)
        pf = main.get('mean_profit_factor', 0)
        wr = main.get('mean_win_rate', 0)
        trades = main.get('mean_avg_trades_per_year', 0)
        score = compute_total_score(annual, sharpe, abs(dd), pf, wr, robust, bias, monthly_positive_rate=main.get('monthly_positive_rate', None))
        if abs(dd) > 25:
            score['total_score'] = 0

        entry = {
            'strategy_name': name,
            'source_link': strategy_info['source_link'],
            'fingerprint': name,
            'fingerprint_short': name[:8],
            'strategy_type': classify_strategy(name),
            'total_score': score['total_score'],
            'score_detail': score,
            'annual_return': round(annual, 2),
            'sharpe': round(sharpe, 2),
            'max_drawdown': round(dd, 2),
            'profit_factor': round(pf, 2),
            'win_rate': round(wr, 2),
            'avg_trades_per_year': round(trades, 1),
            'strategy_params': strategy_info['strategy_params'],
            'strategy_description': '',
            'cross_period_robust': robust,
            'robust_tag': '✅' if robust else '',
            'survivorship_bias': bias,
            'bias_tag': '⚠️' if bias else '',
            'pine_script_rejected': False,
            'portability_score': 10,
            'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'first_listed_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'removal_reason': '',
            'stress_annual': round(stress.get('mean_annual_return', 0), 2) if stress else 0,
            'stress_dd': round(abs(stress.get('mean_max_drawdown', 0)), 2) if stress else 0,
            'market': market,
            'n_stocks': main.get('n_stocks', 0),
        }

    return entry


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 110)
    print("  🔄 统一回测重评：牛市/全局排行榜策略 + GEM增强策略")
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

    vix = load_vix_data()
    if vix is not None:
        print(f"  ✅ VIX: {len(vix)} 行")
    else:
        print("  ⚠️ VIX不可用，将使用SPY已实现波动率")

    all_entries = []

    # 预加载旧排行榜（PART B复用）
    old_leaderboard = load_leaderboard()

    # ══════════════════════════════════════════════
    # PART A: GEM ETF轮动策略（修正穿越后重新回测）
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 PART A: GEM ETF轮动策略（shift(1)修正后）")
    print("=" * 110)

    gem_strategies = [
        {
            'name': 'GEM日度9M纯策略(修正后)',
            'func': lambda: gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, 9),
            'pos_ratio': None,
            'desc': '日度9M双动量轮动(修正穿越后)。绝对动量确认方向+相对动量选最强资产。',
            'params': {'lookback_months': 9, 'rebalance_freq_days': 1, 'shift1_fix': True},
        },
        {
            'name': 'GEM波动率加权-仅缩仓(25/35)(修正后)',
            'func': lambda: gem_vol_weighted(
                close_prices[universe], risk_assets, safe_assets, vix=vix,
                base_lookback=9, vix_high_threshold=25, vix_extreme_threshold=35,
                high_ratio=0.7, extreme_ratio=0.4
            ),
            'pos_ratio': True,  # 标记需要从返回值取
            'desc': '日度9M + VIX缩仓：VIX<25满仓，VIX≥25缩至70%，VIX≥35缩至40%。',
            'params': {'lookback_months': 9, 'vix_shrink_thresholds': '25/35', 'vix_shrink_ratios': '0.7/0.4', 'shift1_fix': True},
        },
        {
            'name': 'GEM波动率加权-极早版(20/28)(修正后)',
            'func': lambda: gem_vol_weighted(
                close_prices[universe], risk_assets, safe_assets, vix=vix,
                base_lookback=9, vix_high_threshold=20, vix_extreme_threshold=28,
                high_ratio=0.8, extreme_ratio=0.5
            ),
            'pos_ratio': True,
            'desc': '日度9M + VIX极早缩仓：VIX<20满仓，VIX≥20缩至80%，VIX≥28缩至50%。',
            'params': {'lookback_months': 9, 'vix_shrink_thresholds': '20/28', 'vix_shrink_ratios': '0.8/0.5', 'shift1_fix': True},
        },
        {
            'name': 'GEM日度9M+3d缓冲(修正后)',
            'func': lambda: gem_rotation_baseline(close_prices[universe], risk_assets, safe_assets, 9),
            'pos_ratio': None,
            'use_3d_buffer': True,
            'desc': '日度9M + 3天换仓缓冲期，减少Whipsaw。',
            'params': {'lookback_months': 9, 'rebalance_freq_days': 1, 'buffer_days': 3, 'shift1_fix': True},
        },
        {
            'name': 'GEM连续2天+3d缓冲(修正后)',
            'func': lambda: gem_dual_signal_consecutive(
                close_prices[universe], risk_assets, safe_assets,
                lookback_months=9, confirm_days=2, holding_buffer_days=3
            ),
            'pos_ratio': None,
            'desc': '日度9M + 连续2天信号确认 + 3天换仓缓冲，双重降噪。',
            'params': {'lookback_months': 9, 'confirm_days': 2, 'buffer_days': 3, 'shift1_fix': True},
        },
        {
            'name': 'GEM动量阈值0.5%(修正后)',
            'func': lambda: gem_dual_signal_threshold(
                close_prices[universe], risk_assets, safe_assets,
                lookback_months=9, momentum_threshold=0.005
            ),
            'pos_ratio': None,
            'desc': '日度9M + 动量变动差0.5%阈值，仅当新资产动量显著高于当前持仓才换仓。',
            'params': {'lookback_months': 9, 'momentum_threshold': '0.5%', 'shift1_fix': True},
        },
    ]

    # 简化GEM（SPY/AGG/SHY）
    simple_universe = ['SPY', 'AGG', 'SHY']
    simple_risk = ['SPY']
    simple_safe = ['AGG', 'SHY']
    gem_strategies.append({
        'name': '简化GEM日度9M(SPY/AGG/SHY)(修正后)',
        'func': lambda: gem_rotation_baseline(
            close_prices[simple_universe], simple_risk, simple_safe, 9
        ),
        'pos_ratio': None,
        'simple': True,
        'desc': '简化版3资产GEM：SPY/AGG/SHY轮动，去掉VEA。',
        'params': {'lookback_months': 9, 'assets': 'SPY/AGG/SHY', 'shift1_fix': True},
    })

    print(f"\n{'策略':<36} {'年化%':>8} {'回撤%':>8} {'夏普':>6} {'Calmar':>7} "
          f"{'盈亏比':>6} {'胜率%':>6} {'年调仓':>6} {'得分':>6} {'衰减%':>7}")
    print("-" * 110)

    for s in gem_strategies:
        name = s['name']
        result = s['func']()

        # 解析返回值
        use_3d_buffer = s.get('use_3d_buffer', False)
        is_simple = s.get('simple', False)

        if s['pos_ratio']:
            holding, pos_ratio, _ = result
        else:
            holding = result
            pos_ratio = None

        # 3d缓冲处理：在holding上加缓冲
        if use_3d_buffer:
            holding = _apply_holding_buffer(holding, buffer_days=3)

        prices = close_prices[simple_universe] if is_simple else close_prices[universe]

        entry = backtest_gem_strategy(
            name=name,
            holding=holding,
            close_prices=prices,
            position_ratio=pos_ratio,
            description=s['desc'],
            params=s['params'],
        )

        if entry:
            all_entries.append(entry)
            decay = entry.get('overfit_info', {}).get('composite_decay', '?')
            print(f"  {name:<34} {entry['annual_return']:>+7.2f}  {entry['max_drawdown']:>7.2f}  "
                  f"{entry['sharpe']:>5.2f}  {entry.get('calmar', 0):>6.2f}  "
                  f"{entry['profit_factor']:>5.2f}  {entry['win_rate']:>5.1f}  "
                  f"{entry['avg_trades_per_year']:>5.1f}  {entry['total_score']:>5.1f}  "
                  f"{decay:>+6.1f}")

    # ══════════════════════════════════════════════
    # PART B: 排行榜现有非GEM策略（复用旧数据+重新评分）
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 PART B: 排行榜现有非GEM策略（复用旧回测数据）")
    print("=" * 110)
    print("  注：非GEM个股策略回测数据不变，直接复用旧排行榜评分")

    # 从旧排行榜中提取非GEM策略
    for old_entry in old_leaderboard:
        name = old_entry['strategy_name']
        # GEM策略已在PART A中用shift(1)修正后重新回测，不再复用旧数据
        if 'GEM' in name or '波动率' in name or '日度9M' in name:
            continue
        # 非GEM策略直接复用
        all_entries.append(old_entry)
        print(f"  📋 复用: {name} - 得分{old_entry['total_score']}分, "
              f"年化{old_entry['annual_return']}%, 回撤{old_entry['max_drawdown']}%")

    # ══════════════════════════════════════════════
    # PART C: 统一排名
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  🏆 统一排名结果")
    print("=" * 110)

    # 按得分排序
    ranked = sorted(all_entries, key=lambda x: x['total_score'], reverse=True)

    print(f"\n{'排名':>4} {'策略名称':<38} {'得分':>6} {'年化%':>8} {'回撤%':>8} "
          f"{'夏普':>6} {'盈亏比':>6} {'胜率%':>6} {'年调仓':>6} {'跨周期':>6} {'衰减%':>7}")
    print("-" * 120)

    for i, e in enumerate(ranked, 1):
        # 处理decay字符串情况
        decay_val = e.get('overfit_info', {}).get('composite_decay', '?')
        if isinstance(decay_val, str):
            decay = decay_val
        else:
            decay = f"{decay_val:+.1f}"
        robust_tag = '✅' if e.get('cross_period_robust') else ''
        print(f"  {i:>2}. {e['strategy_name']:<36} {e['total_score']:>5.1f}  "
              f"{e['annual_return']:>+7.2f}  {e['max_drawdown']:>7.2f}  "
              f"{e['sharpe']:>5.2f}  {e['profit_factor']:>5.2f}  "
              f"{e['win_rate']:>5.1f}  {e['avg_trades_per_year']:>5.1f}  "
              f"{robust_tag:>4}  {decay:>6}")

    # ══════════════════════════════════════════════
    # 新排行榜（前5）
    # ══════════════════════════════════════════════
    top5 = ranked[:5]

    print("\n" + "=" * 110)
    print("  📋 新排行榜 TOP5")
    print("=" * 110)

    for i, e in enumerate(top5, 1):
        medal = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'][i-1]
        print(f"\n  {medal} 第{i}名: {e['strategy_name']}")
        print(f"     综合得分: {e['total_score']}分")
        print(f"     年化: {e['annual_return']}% | 夏普: {e['sharpe']} | 回撤: {e['max_drawdown']}%")
        print(f"     盈亏比: {e['profit_factor']} | 胜率: {e['win_rate']}% | 年交易: {e['avg_trades_per_year']}次")
        robust = '✅' if e.get('cross_period_robust') else '❌'
        print(f"     跨周期鲁棒: {robust} | 市场: {e.get('market', '?').upper()}")
        decay = e.get('overfit_info', {}).get('composite_decay', 'N/A')
        if isinstance(decay, (int, float)):
            print(f"     综合衰减: {decay:+.1f}%")

    # ══════════════════════════════════════════════
    # 与旧排行榜对比
    # ══════════════════════════════════════════════
    print("\n" + "=" * 110)
    print("  📊 新旧排行榜对比")
    print("=" * 110)

    print(f"\n  {'旧排名':>6} {'旧策略':<36} {'旧得分':>6} → {'新得分':>6} {'变化':>8}")
    print("  " + "-" * 80)

    for i, old in enumerate(old_leaderboard, 1):
        old_name = old['strategy_name']
        old_score = old['total_score']
        # 找新排名中对应策略
        new_score = '?'
        for e in ranked:
            if old_name in e['strategy_name'] or e['strategy_name'] in old_name:
                new_score = e['total_score']
                break
        change = ''
        if isinstance(new_score, (int, float)):
            diff = new_score - old_score
            change = f"{diff:+.1f}"
        print(f"  {i:>4}. {old_name:<36} {old_score:>6.1f} → {new_score:>6} {change:>8}")

    # ══════════════════════════════════════════════
    # 保存新排行榜
    # ══════════════════════════════════════════════
    # 为top5生成正式指纹
    for e in top5:
        if e.get('fingerprint', '') == e.get('strategy_name', ''):
            # 用名称生成哈希指纹
            import hashlib
            e['fingerprint'] = hashlib.sha256(
                (e['strategy_name'] + str(e.get('strategy_params', {}))).encode()
            ).hexdigest()
            e['fingerprint_short'] = e['fingerprint'][:8]

    # 保存
    new_lb_path = os.path.join(PROJECT_DIR, 'leaderboard_new.json')
    with open(new_lb_path, 'w', encoding='utf-8') as f:
        json.dump(top5, f, ensure_ascii=False, indent=2, default=str)

    # 也保存完整排名
    full_rank_path = os.path.join(PROJECT_DIR, 'unified_rerank_result.json')
    output = {
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'note': 'shift(1)修正后的真实回测数据',
        'total_strategies': len(ranked),
        'top5': top5,
        'full_ranking': ranked,
    }
    with open(full_rank_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n📁 新排行榜已保存至: {new_lb_path}")
    print(f"📁 完整排名已保存至: {full_rank_path}")

    # 询问是否覆盖旧排行榜
    print(f"\n⚠️ 如需用新排行榜覆盖旧排行榜，请手动执行:")
    print(f"  cp {new_lb_path} {os.path.join(PROJECT_DIR, 'leaderboard.json')}")

    return ranked


def _apply_holding_buffer(holding: pd.Series, buffer_days: int = 3) -> pd.Series:
    """给holding信号添加换仓缓冲期"""
    new_holding = holding.copy()
    n = len(holding)
    last_switch = -999

    for i in range(n):
        if i > 0 and holding.iloc[i] != holding.iloc[i - 1]:
            if (i - last_switch) < buffer_days:
                # 缓冲期内，保持旧持仓
                new_holding.iloc[i] = new_holding.iloc[i - 1]
            else:
                last_switch = i

    return new_holding


if __name__ == '__main__':
    main()
