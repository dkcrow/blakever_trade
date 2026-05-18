#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v4重评分脚本：用新版回测系统重新评估排行榜和落选策略

核心原则：
1. ETF轮动策略：在6只ETF上用v4系统回测，得分为主
2. 本地回测策略：直接运行原始脚本获取最新结果，不硬塞ETF轮动框架
3. 多标的回测：仅作为参考信息附加展示，不替代主评分
4. 允许每个策略有自己擅长的标的，综合得分高就行
"""

import sys, os, json, time, copy, inspect, subprocess
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cross_regime_scheduler import (
    load_all_etf_data, load_all_market_data,
    run_backtest, run_batch_backtest,
    calculate_score, generate_email, send_email,
    strategy_gem_rotation, strategy_multi_asset_rotation,
    strategy_dual_momentum, strategy_bollinger_reversion,
    strategy_rsi_rotation, strategy_macd_rotation,
    strategy_macro_rotation, strategy_dividend_rotation,
    strategy_all_weather,
    MAIN_START, MAIN_END, STRESS_START, STRESS_END,
    LEADERBOARD_PATH, REJECTED_PATH,
    fetch_risk_free_rate,
)

# ============================================================
# 策略名关键词 → 策略函数（仅用于ETF轮动策略）
# ============================================================
STRATEGY_MAP = {
    'GEM': strategy_gem_rotation,
    '双市场自适应': strategy_gem_rotation,
    'Gunbot': strategy_gem_rotation,
    '双重动量': strategy_dual_momentum,
    'QQQ/VEA/GLD': strategy_multi_asset_rotation,
    'RSI': strategy_rsi_rotation,
    'MACD': strategy_macd_rotation,
    '聚宽': strategy_macd_rotation,
    '布林带': strategy_bollinger_reversion,
    '宏观轮动': strategy_macro_rotation,
    '全天气': strategy_all_weather,
    '全天候': strategy_all_weather,
    '股息轮动': strategy_dividend_rotation,
    'Blakever': strategy_gem_rotation,
}

# ============================================================
# 本地回测脚本映射（source_script → 脚本路径）
# ============================================================
LOCAL_SCRIPTS = {
    'rsi2_strict_backtest.py': '/data/workspace/rsi2_strict_backtest.py',
    'dual_market_strategy_backtest.py': '/data/workspace/dual_market_strategy_backtest.py',
    'blakever_v65_backtest.py': '/data/workspace/blakever_v65_backtest.py',
}


def find_strategy_func(name):
    """根据策略名匹配ETF轮动策略函数"""
    for kw, func in STRATEGY_MAP.items():
        if kw.lower() in name.lower():
            return func
    return None


def extract_kwargs(entry, strategy_func):
    """根据策略函数签名，从entry的strategy_params中提取兼容参数"""
    sig = inspect.signature(strategy_func)
    valid = set(sig.parameters.keys()) - {'close_prices'}
    params = entry.get('strategy_params', {})
    kwargs = {}

    # 直接匹配
    for key in valid:
        if key in params:
            kwargs[key] = params[key]

    # RSI(2)特殊映射：rsi_buy_threshold → rsi_oversold, rsi_sell_threshold → rsi_overbought
    if 'rsi_buy_threshold' in params and 'rsi_oversold' in valid:
        kwargs['rsi_period'] = params.get('rsi_period', 2)
        kwargs['rsi_oversold'] = params.get('rsi_buy_threshold', 10)
        kwargs['rsi_overbought'] = params.get('rsi_sell_threshold', 80)

    # 波动率lookback → lookback_months（仅当策略不是Gunbot波动率类型时）
    # Gunbot的vol_lookback是波动率参数，不是GEM回看期，不应映射
    if 'vol_lookback' in params and 'lookback_months' in valid and 'lookback_months' not in kwargs:
        # 只有在策略名不含"波动率调节"时才映射
        strategy_name = entry.get('strategy_name', '')
        if '波动率调节' not in strategy_name:
            kwargs['lookback_months'] = max(1, params['vol_lookback'] // 21)

    # 资产池从assets字符串解析
    assets_str = params.get('assets', '')
    if assets_str and isinstance(assets_str, str):
        parts = [a.strip() for a in assets_str.split('/')]
        risk = [a for a in parts if a not in ('SHY', 'AGG', 'TLT')]
        safe = [a for a in parts if a in ('SHY', 'AGG', 'TLT')]
        if risk and 'risk_assets' in valid:
            kwargs['risk_assets'] = risk
        if safe and 'safe_assets' in valid:
            kwargs['safe_assets'] = safe

    # 修复：risk_assets/safe_assets如果是字符串（如'AGG/SHY'），需要split
    if 'risk_assets' in kwargs and isinstance(kwargs['risk_assets'], str):
        kwargs['risk_assets'] = [a.strip() for a in kwargs['risk_assets'].split('/')]
    if 'safe_assets' in kwargs and isinstance(kwargs['safe_assets'], str):
        kwargs['safe_assets'] = [a.strip() for a in kwargs['safe_assets'].split('/')]

    # 修复：如果risk_assets是单字符列表（如['Q','Q','Q','/','S','P','Y']），说明原始字符串被误拆了
    for key in ['risk_assets', 'safe_assets']:
        if key in kwargs and isinstance(kwargs[key], list):
            joined = ''.join(kwargs[key])
            if '/' in joined and len(kwargs[key]) > 3:
                kwargs[key] = [a.strip() for a in joined.split('/') if a.strip()]

    # 如果风险资产里有不在ETF池的标的（如QQQ），替换为SPY
    if 'risk_assets' in kwargs:
        kwargs['risk_assets'] = [a if a != 'QQQ' else 'SPY' for a in kwargs['risk_assets']]

    return {k: v for k, v in kwargs.items() if v is not None}


def rerank_etf_strategy(entry, close_prices, all_market_data, rf_rate, surv_bias):
    """对ETF轮动策略进行v4重评分"""
    name = entry.get('strategy_name', '?')
    func = find_strategy_func(name)
    if func is None:
        print(f"    ⚠️ 无法匹配策略函数: {name}")
        return None

    kwargs = extract_kwargs(entry, func)
    print(f"    参数: {kwargs}")

    # 1. ETF回测（主评分依据）
    try:
        holding = func(close_prices, **kwargs)
        main_res = run_backtest(close_prices, holding, MAIN_START, MAIN_END, rf_rate, 'US')
        stress_res = run_backtest(close_prices, holding, STRESS_START, STRESS_END, rf_rate, 'US')
    except Exception as e:
        print(f"    ❌ ETF回测失败: {e}")
        return None

    if main_res is None:
        return None

    # 2. 多标的批量回测（仅作参考，不影响主评分）
    batch_res = None
    try:
        batch_res = run_batch_backtest(all_market_data, func, kwargs, rf_rate)
    except Exception as e:
        print(f"    ⚠️ 多标的回测异常: {e}")

    # 3. 计算得分（基于ETF主回测结果）
    score = calculate_score(main_res, stress_res, surv_bias)

    # 4. 更新条目
    new_entry = copy.deepcopy(entry)
    for k in ['annual_return', 'sharpe', 'max_drawdown', 'calmar', 'win_rate',
              'profit_factor', 'avg_trades_per_year', 'holding_distribution']:
        if k in main_res:
            new_entry[k] = main_res[k]
    new_entry['total_score'] = score['total_score']
    new_entry['score_detail'] = score
    new_entry['stress_test'] = {
        'annual_return': stress_res['annual_return'] if stress_res else None,
        'max_drawdown': stress_res['max_drawdown'] if stress_res else None,
    } if stress_res else None
    new_entry['cross_robust'] = score.get('cross_robust', False)
    new_entry['rerank_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_entry['rerank_version'] = 'v4_multi_symbol'

    # 5. 多标的回测信息（参考维度，不参与评分）
    if batch_res and batch_res.get('main_result'):
        mr = batch_res['main_result']
        new_entry['batch_symbol_count'] = batch_res['symbol_count']
        new_entry['batch_profitable_ratio'] = batch_res['profitable_ratio']
        new_entry['batch_us_avg_annual'] = mr.get('us_avg_annual', 0)
        new_entry['batch_hk_avg_annual'] = mr.get('hk_avg_annual', 0)
        new_entry['batch_median_annual'] = mr.get('median_annual_return', 0)

    return new_entry


def rerank_local_strategy(entry):
    """
    对本地回测策略进行重评分
    重新运行原始回测脚本，获取最新结果
    """
    name = entry.get('strategy_name', '?')
    script_name = entry.get('source_script', '')
    script_path = LOCAL_SCRIPTS.get(script_name, '')

    if not script_path or not os.path.exists(script_path):
        print(f"    ⚠️ 脚本不存在: {script_name} → {script_path}")
        print(f"    → 保持原得分不变")
        return None  # 返回None表示保持原条目不变

    print(f"    🔄 运行本地回测: {script_path}")
    try:
        result = subprocess.run(
            ['python3', script_path],
            capture_output=True, text=True, timeout=300,
            cwd=os.path.dirname(script_path),
        )
        output = result.stdout + result.stderr

        # 尝试从输出中提取回测结果
        # 不同脚本格式不同，需要针对性解析
        return _parse_local_output(entry, name, output, script_name)

    except subprocess.TimeoutExpired:
        print(f"    ❌ 脚本超时(300s)")
        return None
    except Exception as e:
        print(f"    ❌ 脚本执行失败: {e}")
        return None


def _parse_local_output(entry, name, output, script_name):
    """解析本地回测脚本的输出"""
    import re

    # 尝试提取JSON格式的结果，用v4评分体系重新算分
    json_match = re.search(r'\{[^{}]*"annual_return"[^{}]*\}', output, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            print(f"    ✅ 解析到JSON结果: 年化{result.get('annual_return',0):+.2f}%")

            result_dict = {
                'annual_return': result.get('annual_return', 0),
                'sharpe': result.get('sharpe', 0),
                'max_drawdown': result.get('max_drawdown', 30),
                'profit_factor': result.get('profit_factor', 1),
                'win_rate': result.get('win_rate', 50),
            }
            score = calculate_score(result_dict, stress_result=None, survivorship_bias=False)
            print(f"    📊 v4得分: {score['total_score']:.1f}")

            new_entry = copy.deepcopy(entry)
            for k in ['annual_return', 'sharpe', 'max_drawdown', 'calmar', 'win_rate',
                      'profit_factor', 'avg_trades_per_year']:
                if k in result:
                    new_entry[k] = result[k]
            new_entry['total_score'] = score['total_score']
            new_entry['score_detail'] = score
            new_entry['cross_robust'] = score.get('cross_robust', False)
            new_entry['rerank_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            new_entry['rerank_version'] = 'v4_local_rerun'
            return new_entry
        except json.JSONDecodeError:
            pass

    # 针对RSI(2)脚本的解析
    if 'rsi2' in script_name.lower():
        return _parse_rsi2_output(entry, output)

    # 针对双市场策略脚本的解析
    if 'dual_market' in script_name.lower():
        return _parse_dual_market_output(entry, output)

    # 通用解析：尝试提取关键指标，用v4评分体系重新算分
    annual = re.search(r'年化收益[率]?\s*[:：]?\s*([-+]?[\d.]+)%', output)
    sharpe = re.search(r'夏普[比率]*\s*[:：]?\s*([-+]?[\d.]+)', output)
    mdd = re.search(r'最大回撤\s*[:：]?\s*-?([\d.]+)%', output)
    win_rate = re.search(r'胜率\s*[:：]?\s*([\d.]+)%', output)
    pf = re.search(r'盈亏比\s*[:：]?\s*([-+]?[\d.]+)', output)

    if annual:
        result_dict = {
            'annual_return': float(annual.group(1)),
            'sharpe': float(sharpe.group(1)) if sharpe else 0,
            'max_drawdown': float(mdd.group(1)) if mdd else 30,
            'profit_factor': float(pf.group(1)) if pf else 1,
            'win_rate': float(win_rate.group(1)) if win_rate else 50,
        }
        print(f"    ✅ 提取到: 年化{result_dict['annual_return']:+.2f}%")

        score = calculate_score(result_dict, stress_result=None, survivorship_bias=False)
        print(f"    📊 v4得分: {score['total_score']:.1f}")

        new_entry = copy.deepcopy(entry)
        for k, v in result_dict.items():
            new_entry[k] = v
        new_entry['total_score'] = score['total_score']
        new_entry['score_detail'] = score
        new_entry['cross_robust'] = score.get('cross_robust', False)
        new_entry['rerank_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_entry['rerank_version'] = 'v4_local_rerun'
        return new_entry

    print(f"    ⚠️ 无法解析本地脚本输出")
    return None


def _parse_rsi2_output(entry, output):
    """解析RSI(2)脚本输出，用v4评分体系重新算分"""
    import re
    # RSI(2)脚本输出：寻找最佳标的(QQQ)的全周期结果
    qqq_match = re.search(
        r'\[QQQ\]\s*年化收益:\s*([-+]?[\d.]+)%\s*\|\s*最大回撤:\s*-?([\d.]+)%\s*\|\s*夏普:\s*([-+]?[\d.]+)\s*\|\s*胜率:\s*([\d.]+)%\s*\|\s*盈亏比:\s*([-+]?[\d.]+)',
        output, re.DOTALL
    )
    if not qqq_match:
        # 回退到汇总行匹配
        qqq_match = re.search(
            r'年化收益:\s*([-+]?[\d.]+)%\s*\n\s*最大回撤:\s*-?([\d.]+)%\s*\n\s*夏普比率:\s*([-+]?[\d.]+)',
            output, re.DOTALL
        )

    if qqq_match:
        annual = float(qqq_match.group(1))
        mdd = float(qqq_match.group(2))
        sharpe = float(qqq_match.group(3))
        win_rate = float(qqq_match.group(4))
        pf = float(qqq_match.group(5))
        print(f"    ✅ RSI(2)@QQQ: 年化{annual:+.2f}% 夏普{sharpe:.3f} 回撤{mdd:.2f}% 胜率{win_rate:.1f}% 盈亏比{pf:.2f}")

        # 用v4评分体系重新算分（基于策略擅长标的的真实表现）
        result_dict = {
            'annual_return': annual,
            'sharpe': sharpe,
            'max_drawdown': mdd,
            'profit_factor': pf,
            'win_rate': win_rate,
        }
        # RSI(2)是单标的回测，不存在幸存者偏差（不是从ETF池中挑选标的）
        score = calculate_score(result_dict, stress_result=None, survivorship_bias=False)
        print(f"    📊 v4得分: {score['total_score']:.1f} (base={score['base_score']:.1f} 偏差{score.get('survivorship_penalty',0):.1f})")

        new_entry = copy.deepcopy(entry)
        new_entry['annual_return'] = annual
        new_entry['sharpe'] = sharpe
        new_entry['max_drawdown'] = mdd
        new_entry['win_rate'] = win_rate
        new_entry['profit_factor'] = pf
        new_entry['total_score'] = score['total_score']
        new_entry['score_detail'] = score
        new_entry['cross_robust'] = score.get('cross_robust', False)
        new_entry['rerank_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_entry['rerank_version'] = 'v4_local_rerun'
        new_entry['best_symbol'] = 'QQQ'  # 标记策略最擅长的标的
        return new_entry

    # 尝试更宽松的匹配
    annual_match = re.search(r'年化.*?([-+]?[\d.]+)%', output)
    if annual_match:
        print(f"    ✅ RSI(2)提取到年化: {annual_match.group(1)}%")
        new_entry = copy.deepcopy(entry)
        new_entry['annual_return'] = float(annual_match.group(1))
        new_entry['rerank_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_entry['rerank_version'] = 'v4_local_rerun'
        return new_entry

    return None


def _parse_dual_market_output(entry, output):
    """解析双市场自适应策略输出，用v4评分体系重新算分"""
    import re
    # 双市场策略输出格式：年化收益/回撤/夏普等
    annual = re.search(r'年化收益:\s*([-+]?[\d.]+)%', output)
    sharpe = re.search(r'夏普比率:\s*([-+]?[\d.]+)', output)
    mdd = re.search(r'最大回撤:\s*-?([\d.]+)%', output)
    win_rate = re.search(r'胜率:\s*([\d.]+)%', output)
    pf = re.search(r'盈亏比:\s*([-+]?[\d.]+)', output)

    if annual:
        result_dict = {
            'annual_return': float(annual.group(1)),
            'sharpe': float(sharpe.group(1)) if sharpe else 0,
            'max_drawdown': float(mdd.group(1)) if mdd else 30,
            'profit_factor': float(pf.group(1)) if pf else 1,
            'win_rate': float(win_rate.group(1)) if win_rate else 50,
        }
        print(f"    ✅ 双市场策略: 年化{result_dict['annual_return']:+.2f}% 夏普{result_dict['sharpe']:.2f} 回撤{result_dict['max_drawdown']:.2f}% 胜率{result_dict['win_rate']:.1f}% 盈亏比{result_dict['profit_factor']:.2f}")

        # 用v4评分体系重新算分
        score = calculate_score(result_dict, stress_result=None, survivorship_bias=False)
        print(f"    📊 v4得分: {score['total_score']:.1f}")

        new_entry = copy.deepcopy(entry)
        for k, v in result_dict.items():
            new_entry[k] = v
        new_entry['total_score'] = score['total_score']
        new_entry['score_detail'] = score
        new_entry['cross_robust'] = score.get('cross_robust', False)
        new_entry['rerank_timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_entry['rerank_version'] = 'v4_local_rerun'
        new_entry['best_symbol'] = 'US_STOCKS'
        return new_entry

    return None


def main():
    print("=" * 70)
    print("v4 多标的回测重评分")
    print("原则：每个策略在自己擅长的标的上回测，多标的仅作参考")
    print("=" * 70)

    # 加载数据
    print("\n📦 加载数据...")
    close_prices, surv_bias = load_all_etf_data()
    all_market_data = load_all_market_data()
    if close_prices is not None and len(close_prices) > 0:
        all_market_data['US_ETF'] = {
            sym: pd.DataFrame({'Close': close_prices[sym]})
            for sym in close_prices.columns if sym in close_prices
        }
    total_sym = sum(len(v) for v in all_market_data.values())
    print(f"  数据: {total_sym}只标的")

    rf_rate = fetch_risk_free_rate()
    print(f"  无风险利率: {rf_rate:.4f}")

    # 加载排行榜和落选库
    print("\n📊 加载策略...")
    with open(LEADERBOARD_PATH, 'r', encoding='utf-8') as f:
        leaderboard = json.load(f)
    with open(REJECTED_PATH, 'r', encoding='utf-8') as f:
        rejected = json.load(f)

    rejected_sorted = sorted(rejected, key=lambda x: x.get('total_score', 0), reverse=True)
    rejected_top10 = rejected_sorted[:10]
    print(f"  排行榜: {len(leaderboard)}只")
    print(f"  落选前10: {[e.get('strategy_name','?')[:25] for e in rejected_top10]}")

    # ========================================
    # 重评分排行榜
    # ========================================
    print("\n🔄 重评分排行榜...")
    new_lb_entries = []
    for i, entry in enumerate(leaderboard):
        name = entry.get('strategy_name', '?')
        old_score = entry.get('total_score', 0)
        source = entry.get('source', 'scheduler')
        print(f"\n  [{i+1}/{len(leaderboard)}] {name} (旧分={old_score:.1f}, 来源={source})")

        t0 = time.time()
        new_entry = None

        if source == 'local_backtest':
            # 本地回测策略：优先尝试重新运行原始脚本
            print(f"    📝 本地回测策略 → 尝试重新运行脚本")
            new_entry = rerank_local_strategy(entry)

            if new_entry is None:
                # 脚本无法运行或解析失败 → 尝试用ETF轮动框架（更宽容的参数映射）
                print(f"    → 回退到ETF轮动框架重评分")
                new_entry = rerank_etf_strategy(entry, close_prices, all_market_data, rf_rate, surv_bias)

            if new_entry is None:
                # 全部失败 → 保持原条目
                print(f"    → 保持原得分不变")
                new_entry = entry
        else:
            # ETF轮动策略：用v4系统重评分
            new_entry = rerank_etf_strategy(entry, close_prices, all_market_data, rf_rate, surv_bias)
            if new_entry is None:
                print(f"    → 保持原条目")
                new_entry = entry

        elapsed = time.time() - t0
        ns = new_entry.get('total_score', 0)
        diff = ns - old_score
        arrow = '↑' if diff > 0.5 else ('↓' if diff < -0.5 else '→')
        print(f"    结果: 新分={ns:.1f} ({arrow}{abs(diff):.1f}) | 年化{new_entry.get('annual_return',0):+.2f}% | {elapsed:.1f}s")
        if new_entry.get('batch_symbol_count'):
            print(f"    🌐 多标的参考: {new_entry['batch_symbol_count']}只 盈利{new_entry['batch_profitable_ratio']:.1f}% "
                  f"美股{new_entry.get('batch_us_avg_annual',0):+.2f}% 港股{new_entry.get('batch_hk_avg_annual',0):+.2f}%")

        new_lb_entries.append(new_entry)

    # ========================================
    # 重评分落选前10
    # ========================================
    print("\n🔄 重评分落选前10...")
    new_rej_entries = []
    for i, entry in enumerate(rejected_top10):
        name = entry.get('strategy_name', '?')
        old_score = entry.get('total_score', 0)
        source = entry.get('source', 'scheduler')
        print(f"\n  [落选{i+1}/10] {name} (旧分={old_score:.1f}, 来源={source})")

        t0 = time.time()
        new_entry = None

        if source == 'local_backtest':
            new_entry = rerank_local_strategy(entry)
            if new_entry is None:
                new_entry = rerank_etf_strategy(entry, close_prices, all_market_data, rf_rate, surv_bias)
            if new_entry is None:
                new_entry = entry
        else:
            new_entry = rerank_etf_strategy(entry, close_prices, all_market_data, rf_rate, surv_bias)
            if new_entry is None:
                new_entry = entry

        elapsed = time.time() - t0
        ns = new_entry.get('total_score', 0)
        diff = ns - old_score
        arrow = '↑' if diff > 0.5 else ('↓' if diff < -0.5 else '→')
        print(f"    结果: 新分={ns:.1f} ({arrow}{abs(diff):.1f}) | {elapsed:.1f}s")
        new_rej_entries.append(new_entry)

    # ========================================
    # 合并排名
    # ========================================
    print("\n🏆 重新排名...")
    all_entries = new_lb_entries + new_rej_entries
    all_entries.sort(key=lambda x: x.get('total_score', 0), reverse=True)

    final_lb = all_entries[:10]
    dropped_entries = all_entries[10:]

    # 构建旧排名映射
    old_rank_map = {}
    for i, e in enumerate(leaderboard):
        fp = e.get('fingerprint', '')
        old_rank_map[fp] = (i + 1, e.get('total_score', 0), e.get('strategy_name', '?'))

    # 打印排名变化
    print("\n" + "=" * 70)
    print("📊 新排行榜 & 排名变化")
    print("=" * 70)
    for i, entry in enumerate(final_lb):
        fp = entry.get('fingerprint', '')
        name = entry.get('strategy_name', '?')
        ns = entry.get('total_score', 0)
        if fp in old_rank_map:
            old_rank, old_score, _ = old_rank_map[fp]
            rd = old_rank - (i + 1)
            sd = ns - old_score
            ra = '↑' if rd > 0 else ('↓' if rd < 0 else '→')
            sa = '↑' if sd > 0.5 else ('↓' if sd < -0.5 else '→')
            print(f"  #{i+1} {name[:35]:35s} 分={ns:.1f}({sa}{abs(sd):.1f}) 排名{ra}{abs(rd) if rd else ''}")
        else:
            print(f"  #{i+1} 🆕 {name[:35]:35s} 分={ns:.1f} (从落选升级)")

    # 打印跌出TOP10
    new_fps = set(e.get('fingerprint', '') for e in final_lb)
    print("\n📉 跌出TOP10:")
    for i, entry in enumerate(leaderboard):
        if entry.get('fingerprint', '') not in new_fps:
            name = entry.get('strategy_name', '?')
            print(f"  旧#{i+1} {name[:35]:35s} 分={entry.get('total_score',0):.1f}")

    # ========================================
    # 保存（备份旧文件）
    # ========================================
    print("\n💾 保存结果...")
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    for path, data in [(LEADERBOARD_PATH, leaderboard), (REJECTED_PATH, rejected)]:
        bk = path.replace('.json', f'_backup_{ts}.json')
        with open(bk, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  备份: {bk}")

    # 保存新排行榜
    with open(LEADERBOARD_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_lb, f, ensure_ascii=False, indent=2)

    # 更新落选库
    rej_fps = set(e.get('fingerprint', '') for e in rejected_top10)
    other_rej = [e for e in rejected if e.get('fingerprint', '') not in rej_fps]

    # 排行榜中跌出TOP10的加入落选
    for e in new_lb_entries:
        if e.get('fingerprint', '') not in new_fps:
            e['reject_reason'] = "v4重评分后跌出TOP10"
            e['pending_leaderboard'] = True
            dropped_entries.append(e)

    # 给新落选的标记原因
    for e in dropped_entries:
        if 'reject_reason' not in e:
            e['reject_reason'] = f"v4重评分后排名>{len(final_lb)}（末位{final_lb[-1].get('total_score',0):.1f}分）"
            e['pending_leaderboard'] = True

    # 去重
    final_rej = other_rej + dropped_entries
    seen = set()
    deduped = []
    for e in final_rej:
        fp = e.get('fingerprint', '')
        if fp not in seen:
            deduped.append(e)
            seen.add(fp)

    with open(REJECTED_PATH, 'w', encoding='utf-8') as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 排行榜: {len(final_lb)}只")
    print(f"  ✅ 落选库: {len(deduped)}只")

    # ========================================
    # 发送邮件
    # ========================================
    print("\n📧 发送邮件报告...")
    try:
        html = generate_email(
            results=[], leaderboard=final_lb,
            rejected=deduped[:10], scan_start=datetime.now(),
            duration=0, new_best=False,
            search_stats={'total_searched': 0, 'new_strategies': 0, 'deduplicated': 0, 'backtested': 0},
            risk_free_rate=rf_rate, survivorship_bias=surv_bias,
            all_market_data=all_market_data,
        )
        send_email(html, datetime.now())
        print("  ✅ 邮件发送成功")
    except Exception as e:
        print(f"  ⚠️ 邮件失败: {e}")

    print("\n🏁 v4重评分完成！")


if __name__ == '__main__':
    main()
