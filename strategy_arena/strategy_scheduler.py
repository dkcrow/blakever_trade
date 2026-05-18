#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略回测定时调度器
==================
主入口: python strategy_scheduler.py [run|status|report]

职责:
  1. 搜索策略（调用web_search获取公开策略代码）
  2. Pine Script一票否决检测
  3. 策略去重与指纹计算
  4. 调度本地回测脚本执行回测
  5. 评分与排行榜更新
  6. 输出执行报告

执行频率: 每6小时一次（由外部cron调度或AI Agent定时触发）
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = '/data/workspace'

# 添加项目路径
sys.path.insert(0, PROJECT_DIR)

from strategy_searcher import (
    get_search_queries, process_search_results, initial_filter,
    extract_code_from_github_readme, extract_pine_script
)
from pine_validator import check_pine_veto, score_portability, analyze_pine_for_translation
from strategy_dedup import (
    compute_strategy_fingerprint, fingerprint_short,
    load_strategy_library, save_strategy_library, check_duplicate,
    add_strategy_to_library
)
from strategy_ranker import (
    compute_total_score, classify_strategy, build_leaderboard_entry,
    load_leaderboard, save_leaderboard, update_leaderboard,
    format_leaderboard_table
)
from hybrid_searcher import (
    hybrid_search, BULL_PARAM_VARIANTS, BULL_GITHUB_QUERIES,
    generate_param_variants, github_search,
)


# ================================================================
# 配置
# ================================================================
RUN_BACKTEST_SCRIPT = os.path.join(PROJECT_DIR, 'run_backtest.py')
STRATEGY_CODE_DIR = os.path.join(PROJECT_DIR, 'strategies')
RISK_FREE_RATE_DEFAULT = 0.045  # 10年美债~4.5% + 1%

# 确保目录存在
os.makedirs(STRATEGY_CODE_DIR, exist_ok=True)


# ================================================================
# 废弃策略管理
# ================================================================
REJECTED_DB_PATH = os.path.join(PROJECT_DIR, 'rejected_strategies.json')


def load_rejected_strategies(path: str = REJECTED_DB_PATH) -> list:
    """加载废弃策略列表"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_rejected_strategies(rejected: list, path: str = REJECTED_DB_PATH):
    """保存废弃策略列表"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)


def add_rejected_strategy(entry: dict, rejected_list: list) -> list:
    """
    添加策略到废弃列表。若同指纹+同市场已存在则更新（保留得分较高者），否则追加。
    注意：同一策略在不同市场（us/hk）的表现不同，需分别保存。
    """
    new_fp = entry.get('fingerprint', '')
    new_market = entry.get('market', '')
    for i, existing in enumerate(rejected_list):
        if existing.get('fingerprint', '') == new_fp and existing.get('market', '') == new_market:
            # 保留得分较高的
            if entry.get('total_score', 0) > existing.get('total_score', 0):
                rejected_list[i] = entry
            return rejected_list
    rejected_list.append(entry)
    return rejected_list


def format_all_strategies_table(scored: list, market: str = 'us') -> str:
    """格式化所有策略回测数据表格（包括未通过的）"""
    if not scored:
        return "本次无策略完成回测评分。"

    lines = [
        f"\n### 📊 全部策略回测数据（{market.upper()}）\n",
        "| # | 策略名称 | 类型 | 指纹 | 得分 | 年化收益 | 夏普 | 最大回撤 | 盈亏比 | 胜率 | 单标年交易 | 是否通过 | 未通过原因 |",
        "|---|---------|------|------|------|---------|------|---------|--------|------|-----------|---------|-----------|",
    ]

    for i, entry in enumerate(scored, 1):
        name = entry.get('strategy_name', 'Unknown')[:24]
        s_type = entry.get('strategy_type', '其他')
        fp = entry.get('fingerprint_short', '????????')
        score = entry.get('total_score', 0)
        annual = entry.get('annual_return', 0)
        sharpe = entry.get('sharpe', 0)
        dd = entry.get('max_drawdown', 0)
        pf = entry.get('profit_factor', 0)
        wr = entry.get('win_rate', 0)
        trades = entry.get('avg_trades_per_year', 0)
        passed = score >= 80
        pass_tag = '✅' if passed else '❌'

        # 未通过原因
        reasons = []
        if abs(dd) > 25:
            reasons.append('回撤>25%')
        if annual < 15:
            reasons.append('年化<15%')
        if sharpe < 0.5:
            reasons.append('夏普<0.5')
        if score < 80:
            reasons.append(f'得分{score}')
        reason_str = '; '.join(reasons) if not passed else '-'

        lines.append(
            f"| {i} | {name} | {s_type} | {fp} | {score} | "
            f"{annual}% | {sharpe} | {dd}% | {pf} | {wr}% | {trades} | {pass_tag} | {reason_str} |"
        )

    return '\n'.join(lines)


def format_rejected_table(rejected_list: list, max_display: int = 10) -> str:
    """格式化废弃策略库表格"""
    if not rejected_list:
        return "  （废弃策略库为空）"

    # 按废弃时间降序排列（最近的在前），只展示最近max_display个
    sorted_list = sorted(rejected_list,
                         key=lambda x: x.get('rejected_time', ''), reverse=True)
    display_list = sorted_list[:max_display]

    lines = [
        "| # | 策略名称 | 市场 | 类型 | 指纹 | 得分 | 年化 | 夏普 | 回撤 | 废弃原因 | 废弃时间 |",
        "|---|---------|------|------|------|------|------|------|------|---------|---------|",
    ]

    for i, entry in enumerate(display_list, 1):
        name = entry.get('strategy_name', 'Unknown')[:24]
        market = entry.get('market', '?').upper()
        s_type = entry.get('strategy_type', '其他')
        fp = entry.get('fingerprint_short', entry.get('fingerprint', '')[:8])
        score = entry.get('total_score', 0)
        annual = entry.get('annual_return', 0)
        sharpe = entry.get('sharpe', 0)
        dd = entry.get('max_drawdown', 0)
        reason = entry.get('rejection_reason', '得分<80')
        rej_time = entry.get('rejected_time', 'N/A')

        lines.append(
            f"| {i} | {name} | {market} | {s_type} | {fp} | {score} | "
            f"{annual}% | {sharpe} | {dd}% | {reason} | {rej_time} |"
        )

    if len(sorted_list) > max_display:
        lines.append(f"\n  ... 还有 {len(sorted_list) - max_display} 个废弃策略未显示")

    return '\n'.join(lines)


def _format_top10_detail(leaderboard: list) -> str:
    """格式化前十排行榜详细参数展示"""
    if not leaderboard:
        return "  （排行榜为空）"

    lines = []
    for i, entry in enumerate(leaderboard, 1):
        name = entry.get('strategy_name', 'Unknown')
        s_type = entry.get('strategy_type', '其他')
        market = entry.get('market', '?').upper()
        score = entry.get('total_score', 0)
        annual = entry.get('annual_return', 0)
        sharpe = entry.get('sharpe', 0)
        dd = entry.get('max_drawdown', 0)
        pf = entry.get('profit_factor', 0)
        wr = entry.get('win_rate', 0)
        trades = entry.get('avg_trades_per_year', 0)
        params = entry.get('strategy_params', {})
        desc = entry.get('strategy_description', '')
        robust = '✅' if entry.get('cross_period_robust') else '❌'
        bias = '⚠️' if entry.get('survivorship_bias') else '✅'
        stress_annual = entry.get('stress_annual', 0)
        stress_dd = entry.get('stress_dd', 0)

        lines.append(f"  ┌─ 🥇 第{i}名: {name} ({market}) ─────────────────")
        lines.append(f"  │ 策略类型: {s_type}")
        lines.append(f"  │ 综合得分: {score}分")
        lines.append(f"  │ ── 核心指标 ──")
        lines.append(f"  │ 年化收益率: {annual}%")
        lines.append(f"  │ 夏普比率:   {sharpe}")
        lines.append(f"  │ 最大回撤:   {dd}%")
        lines.append(f"  │ 盈亏比:     {pf}")
        lines.append(f"  │ 胜率:       {wr}%")
        lines.append(f"  │ 年交易次数: {trades}")
        lines.append(f"  │ ── 压力测试 ──")
        lines.append(f"  │ 压力期年化: {stress_annual}%")
        lines.append(f"  │ 压力期回撤: {stress_dd}%")
        lines.append(f"  │ 跨周期鲁棒: {robust}  数据偏差: {bias}")
        if desc:
            lines.append(f"  │ 描述: {desc[:80]}")
        if params:
            lines.append(f"  │ ── 策略参数 ──")
            for k, v in params.items():
                lines.append(f"  │   {k} = {v}")
        lines.append(f"  └────────────────────────────────────")

    return '\n'.join(lines)


# ================================================================
# 步骤1: 搜索策略
# ================================================================
def search_strategies() -> list:
    """
    混合搜索策略代码。
    方案A: GitHub API搜索（优先）→ 方案B: 参数变体（降级）
    确保每次扫描至少找到3个新策略。
    """
    print("\n" + "=" * 80)
    print("  🔍 步骤1: 搜索策略（混合搜索 A+B）")
    print("=" * 80)

    found_strategies = []

    # ---- 预置已知高质量策略（本地已有代码） ----
    builtin_strategies = _get_builtin_strategies()
    found_strategies.extend(builtin_strategies)
    print(f"  📦 内置策略: {len(builtin_strategies)}个")

    # ---- 混合搜索: 方案A(GitHub) + 方案B(参数变体) ----
    # 收集已有指纹用于去重
    library = load_strategy_library()
    existing_fps = {(s.get('fingerprint', ''), s.get('market', ''))
                    for s in library.get('strategies', [])}
    # 也从废弃策略库收集指纹
    rejected_list = load_rejected_strategies()
    for r in rejected_list:
        existing_fps.add((r.get('fingerprint', ''), r.get('market', '')))

    # 执行混合搜索
    hybrid_results, search_stats = hybrid_search(
        market_type='bull',
        builtin_strategies=builtin_strategies,
        variant_templates=BULL_PARAM_VARIANTS,
        existing_fingerprints=existing_fps,
        min_new=3,
        github_queries=BULL_GITHUB_QUERIES,
        strategy_code_dirs=[STRATEGY_CODE_DIR],
    )

    if hybrid_results:
        found_strategies.extend(hybrid_results)
        print(f"  🌐 混合搜索新增: {len(hybrid_results)}个 "
              f"(方法: {search_stats['search_method']}, "
              f"GitHub: {search_stats['github_results']}个, "
              f"变体: {search_stats['variant_generated']}个)")
        if search_stats['github_rate_limited']:
            print(f"  ⚠️ GitHub API被限流，已降级到参数变体模式")
    else:
        print(f"  ⚠️ 混合搜索未找到新策略")

    # 尝试从上次搜索缓存加载
    cached = _load_search_cache()
    if cached:
        found_strategies.extend(cached)
        print(f"  💾 搜索缓存: {len(cached)}个策略")

    print(f"\n  📊 本次发现策略数量: {len(found_strategies)}")

    return found_strategies


def _get_builtin_strategies() -> list:
    """获取内置的已知高质量策略列表"""
    strategies = []

    # 从已有的run_alternative_strategies.py中提取策略
    builtin = [
        {
            'name': 'Supertrend ATR自适应趋势跟踪',
            'description': 'ATR驱动自适应趋势跟踪策略，无需均线交叉，对趋势变化响应更快。适合港美股牛市趋势跟随。',
            'source': 'builtin',
            'source_link': 'local:run_alternative_strategies.py',
            'code': _read_builtin_strategy('supertrend'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'Donchian通道突破(海龟交易法)',
            'description': '经典海龟交易法核心策略，20日新高入场10日新低出场，在强趋势市场表现优异。适合港美股趋势跟踪。',
            'source': 'builtin',
            'source_link': 'local:run_alternative_strategies.py',
            'code': _read_builtin_strategy('donchian'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': 'Dual Momentum双动量策略',
            'description': '绝对动量+相对动量月度轮动策略，12M绝对动量确认大方向，1M相对动量确认短期趋势。稳健型港美股策略。',
            'source': 'builtin',
            'source_link': 'local:run_alternative_strategies.py',
            'code': _read_builtin_strategy('dual_momentum'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': 'RSI回调买入策略(牛市专用)',
            'description': '在确认的牛市趋势中买回调，RSI从超卖区回升时入场，RSI超买或趋势破位出场。风险收益比更优。',
            'source': 'builtin',
            'source_link': 'local:run_alternative_strategies.py',
            'code': _read_builtin_strategy('rsi_pullback'),
            'strategy_type': '均值回归',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'MACD+Supertrend双重过滤',
            'description': 'MACD柱状图确认大方向+Supertrend精确触发，双层过滤减少假信号。适合港美股趋势跟踪。',
            'source': 'builtin',
            'source_link': 'local:run_alternative_strategies.py',
            'code': _read_builtin_strategy('macd_supertrend'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        # 额外经典策略模板
        {
            'name': 'EMA交叉+ADX趋势强度过滤',
            'description': '经典EMA10/20交叉持仓+ADX>20趋势强度过滤，宽松版。Blakever Agent3当前主力策略。',
            'source': 'builtin',
            'source_link': 'local:blakever_bull_strategy.py',
            'code': _read_builtin_strategy('ema_adx'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': '布林带均值回归策略',
            'description': '价格触及布林带下轨买入，上轨卖出，回归中轨平仓。经典均值回归策略，适合震荡市和港美股回调行情。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('bollinger_reversion'),
            'strategy_type': '均值回归',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': '高股息轮动策略',
            'description': '按股息率排序定期轮动到高股息标的，结合趋势过滤避免价值陷阱。适合港美股稳健型投资者。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('dividend_rotation'),
            'strategy_type': '高股息轮动',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'Keltner通道突破策略',
            'description': 'ATR驱动的通道突破策略，比布林带更适应趋势市场，减少震荡市假信号。适合港美股趋势跟踪。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('keltner_breakout'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'MACD金叉+趋势确认策略',
            'description': 'MACD柱状图从负转正(金叉确认)+价格在长期EMA上方，减少震荡市假信号。适合港美股趋势跟踪。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('macd_trend_confirm'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'Triple EMA三层均线策略',
            'description': 'EMA10/30/50三线多头排列持仓，三线系统比双线更稳定，过滤更多假信号。经典趋势跟踪策略。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('triple_ema'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': 'VWAP趋势跟踪策略',
            'description': '利用VWAP作为趋势参考，价格在VWAP上方持仓。适合流动性好的港美股大盘股。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('vwap_trend'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'RSI趋势确认策略',
            'description': 'RSI在40-70区间+价格在EMA上方持仓，牛市趋势确认区域策略。比纯RSI超买超卖更稳健。',
            'source': 'builtin',
            'source_link': 'generated',
            'code': _read_builtin_strategy('rsi_trend_confirm'),
            'strategy_type': '趋势跟踪',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
    ]

    # 过滤有效代码
    for s in builtin:
        if s['code'] and len(s['code'].strip()) > 20:
            strategies.append(s)

    return strategies


def _read_builtin_strategy(name: str) -> str:
    """读取内置策略代码（从独立策略文件或模板生成）"""
    filepath = os.path.join(STRATEGY_CODE_DIR, f'{name}.py')
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ''


def _load_search_cache() -> list:
    """加载搜索缓存"""
    cache_path = os.path.join(PROJECT_DIR, 'search_cache.json')
    if not os.path.exists(cache_path):
        return []
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


# ================================================================
# 步骤2: Pine Script一票否决检测
# ================================================================
def check_pine_veto_batch(strategies: list) -> tuple:
    """
    批量检查Pine Script一票否决。
    返回 (通过策略列表, 否决数量)
    """
    print("\n" + "=" * 80)
    print("  🔒 步骤2: Pine Script一票否决检测")
    print("=" * 80)

    vetoed_count = 0
    passed = []

    for strategy in strategies:
        code = strategy.get('code', '')
        source = strategy.get('source', '')

        # 仅对TradingView/Pine Script来源检查
        if source.lower() in ('tradingview', 'pine_script', 'pine') or \
           'pine' in code[:200].lower():
            veto_result = check_pine_veto(code)
            if veto_result['vetoed']:
                vetoed_count += 1
                strategy['pine_script_rejected'] = True
                strategy['veto_reasons'] = veto_result['veto_reasons']
                print(f"  ❌ 否决: {strategy['name']} — {veto_result['veto_reasons']}")
                continue
            else:
                strategy['pine_script_rejected'] = False
                if veto_result['warnings']:
                    print(f"  ⚠️ 警告: {strategy['name']} — {veto_result['warnings']}")
        else:
            strategy['pine_script_rejected'] = False

        passed.append(strategy)

    print(f"\n  📊 Pine Script一票否决数量: {vetoed_count}")
    print(f"  📊 通过否决检测数量: {len(passed)}")

    return passed, vetoed_count


# ================================================================
# 步骤3: 去重与指纹
# ================================================================
def deduplicate_strategies(strategies: list, market: str = 'us') -> tuple:
    """
    策略去重与指纹计算。
    同一策略指纹在不同市场视为不同策略（表现不同），均需回测。
    返回 (新策略列表, 去重数量)
    """
    print("\n" + "=" * 80)
    print("  🔑 步骤3: 策略去重与指纹计算")
    print("=" * 80)

    library = load_strategy_library()
    existing_fps = {(s.get('fingerprint', ''), s.get('market', ''))
                    for s in library.get('strategies', [])}
    print(f"  📚 策略库现有: {len(existing_fps)}个策略（按指纹+市场联合去重）")

    new_strategies = []
    dedup_count = 0

    for strategy in strategies:
        code = strategy.get('code', '')
        params = strategy.get('params', {})

        # 提取参数（从代码中尝试提取）
        if not params:
            params = _extract_params_from_code(code)

        fingerprint = compute_strategy_fingerprint(code, params)
        strategy['fingerprint'] = fingerprint
        strategy['fingerprint_short'] = fingerprint_short(fingerprint)
        strategy['strategy_params'] = params
        strategy['market'] = market

        # 检查重复（指纹+市场联合去重）
        fp_market_key = (fingerprint, market)
        if fp_market_key in existing_fps:
            dedup_count += 1
            # 找到对应的已有策略名
            existing_name = ''
            for s in library.get('strategies', []):
                if s.get('fingerprint', '') == fingerprint and s.get('market', '') == market:
                    existing_name = s.get('strategy_name', '?')
                    break
            existing_score = 0
            for s in library.get('strategies', []):
                if s.get('fingerprint', '') == fingerprint and s.get('market', '') == market:
                    existing_score = s.get('total_score', 0)
                    break
            print(f"  🔄 重复: {strategy['name']} [{market.upper()}] (已有: {existing_name}, 得分: {existing_score})")
        else:
            new_strategies.append(strategy)
            print(f"  ✅ 新策略: {strategy['name']} [{market.upper()}] (指纹: {fingerprint_short(fingerprint)})")

    print(f"\n  📊 去重数量: {dedup_count}")
    print(f"  📊 通过去重后新策略数量: {len(new_strategies)}")

    return new_strategies, dedup_count


def _extract_params_from_code(code: str) -> dict:
    """从策略代码中提取参数"""
    import re
    params = {}
    # 匹配函数参数默认值
    pattern = r'(?:ema_fast|ema_slow|atr_period|atr_mult|rsi_period|lookback|'
    pattern += r'entry_window|exit_window|macd_fast|macd_slow|macd_signal|'
    pattern += r'multiplier|period|window|threshold)\s*=\s*(\d+\.?\d*)'
    for match in re.finditer(pattern, code):
        try:
            val = float(match.group(1))
            params[match.group(0).split('=')[0].strip()] = val
        except ValueError:
            pass
    return params


# ================================================================
# 步骤4: 回测验证
# ================================================================
def run_backtest_batch(strategies: list, market: str = 'us',
                       max_stocks: int = None) -> list:
    """
    批量执行回测验证。
    为每个策略生成独立的策略文件，然后调用run_backtest.py。
    """
    print("\n" + "=" * 80)
    print("  🚀 步骤4: 回测验证")
    print("=" * 80)

    backtest_results = []

    for strategy in strategies:
        name = strategy.get('name', 'Unknown')
        code = strategy.get('code', '')

        if not code or len(code.strip()) < 20:
            print(f"  ⏭️ 跳过: {name} (无有效代码)")
            continue

        # 生成策略文件
        strategy_file = _generate_strategy_file(strategy)
        if not strategy_file:
            print(f"  ⏭️ 跳过: {name} (策略文件生成失败)")
            continue

        # 调用回测脚本
        print(f"\n  🔄 回测: {name}")
        result = _execute_backtest(strategy_file, market, max_stocks)

        if result:
            strategy['backtest_result'] = result
            strategy['market'] = market
            backtest_results.append(strategy)
            main = result.get('main_period', {})
            if main:
                print(f"    ✅ 年化: {main.get('mean_annual_return', '?')}% | "
                      f"夏普: {main.get('mean_sharpe', '?')} | "
                      f"回撤: {main.get('mean_max_drawdown', '?')}%")
        else:
            print(f"    ❌ 回测失败: {name}")

    print(f"\n  📊 通过回测验证数量: {len(backtest_results)}")

    return backtest_results


def _generate_strategy_file(strategy: dict) -> str:
    """
    为策略生成独立的Python文件，符合run_backtest.py的接口要求。
    """
    name = strategy.get('name', 'Unknown')
    code = strategy.get('code', '')
    params = strategy.get('strategy_params', {})

    # 安全文件名
    safe_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in name)
    filepath = os.path.join(STRATEGY_CODE_DIR, f'{safe_name}.py')

    # 检查代码是否已有generate_signals函数
    if 'generate_signals' in code:
        # 直接写入
        content = code
    elif 'def ' in code:
        # 有函数定义，包装为generate_signals
        content = f"""
# 策略: {name}
# 来源: {strategy.get('source', 'unknown')}
# 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "{name}"
STRATEGY_TYPE = "{strategy.get('strategy_type', '其他')}"
STRATEGY_PARAMS = {params}

{code}
"""
    else:
        # 纯逻辑代码，包装为generate_signals
        content = f"""
# 策略: {name}
# 来源: {strategy.get('source', 'unknown')}
# 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "{name}"
STRATEGY_TYPE = "{strategy.get('strategy_type', '其他')}"
STRATEGY_PARAMS = {params}

def generate_signals(close, high, low, open_prices, **kwargs):
    \"\"\"
    {strategy.get('description', name)}
    \"\"\"
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    o = pd.Series(open_prices, dtype=float)
    n = len(c)

    # === 策略逻辑 ===
{chr(10).join('    ' + line for line in code.split(chr(10)))}

    # === 信号生成 ===
    # entries/exits 由策略逻辑决定
    entries = np.full(n, False)
    exits = np.full(n, False)
    return entries, exits
"""

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath
    except Exception as e:
        print(f"  ⚠️ 策略文件生成失败: {e}", file=sys.stderr)
        return ''


def _execute_backtest(strategy_file: str, market: str = 'us',
                      max_stocks: int = None) -> dict:
    """调用run_backtest.py执行回测"""
    output_file = strategy_file.replace('.py', '_result.json')

    cmd = [
        sys.executable, RUN_BACKTEST_SCRIPT,
        '--strategy', strategy_file,
        '--market', market,
        '--risk-free-rate', str(RISK_FREE_RATE_DEFAULT),
        '--output', output_file,
    ]
    if max_stocks:
        cmd.extend(['--max-stocks', str(max_stocks)])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,  # 10分钟超时
            cwd=PROJECT_DIR,
        )
        if result.returncode != 0:
            print(f"    ⚠️ 回测脚本返回码: {result.returncode}")
            print(f"    stderr: {result.stderr[:500]}")
            return None

        # 读取输出JSON
        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                return json.load(f)

    except subprocess.TimeoutExpired:
        print(f"    ⚠️ 回测超时(>600s)")
    except Exception as e:
        print(f"    ⚠️ 回测执行异常: {e}")

    return None


# ================================================================
# 步骤5: 评分与排行榜
# ================================================================
def _build_rejected_entry(strategy: dict, bt_result: dict, main: dict,
                          reason_parts: list) -> dict:
    """
    为得分=0或build_leaderboard_entry返回None的策略手动构建废弃条目。
    确保即使硬性条件不满足，策略数据也能完整展示和持久化。
    """
    try:
        annual = main.get('mean_annual_return', 0)
        sharpe = main.get('mean_sharpe', 0)
        dd = main.get('mean_max_drawdown', 0)
        pf = main.get('mean_profit_factor', 0)
        wr = main.get('mean_win_rate', 0)
        trades = main.get('mean_avg_trades_per_year', 0)

        entry = {
            'strategy_name': strategy.get('name', 'Unknown'),
            'source_link': strategy.get('source_link', ''),
            'fingerprint': strategy.get('fingerprint', ''),
            'fingerprint_short': strategy.get('fingerprint_short', ''),
            'strategy_type': classify_strategy(strategy.get('code', '')),
            'total_score': 0,
            'score_detail': {
                'annual_return_score': 0,
                'sharpe_score': 0,
                'max_drawdown_score': 0,
                'profit_factor_score': 0,
                'win_rate_score': 0,
                'base_score': 0,
                'cross_period_bonus': 0,
                'survivorship_penalty': -10.0,
                'total_score': 0,
                'max_drawdown_hard_fail': True,
            },
            'annual_return': round(annual, 2) if annual else 0,
            'sharpe': round(sharpe, 2) if sharpe else 0,
            'max_drawdown': round(dd, 2) if dd else 0,
            'profit_factor': round(pf, 2) if pf else 0,
            'win_rate': round(wr, 2) if wr else 0,
            'avg_trades_per_year': round(trades, 2) if trades else 0,
            'cross_period_robust': False,
            'robust_tag': '',
            'survivorship_bias': True,
            'bias_tag': '⚠️',
            'pine_script_rejected': strategy.get('pine_script_rejected', False),
            'portability_score': score_portability(
                strategy.get('code', ''), strategy.get('source', '')),
            'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'first_listed_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'removal_reason': '',
            'stress_annual': 0,
            'stress_dd': 0,
            'market': strategy.get('market', 'unknown'),
            'n_stocks': main.get('n_stocks', 0),
        }
        return entry
    except Exception as e:
        print(f"  ⚠️ 构建废弃条目异常: {e}")
        return None


def score_and_rank(backtest_results: list) -> tuple:
    """
    评分并更新排行榜。
    返回 (scored_all, scored_passed, scored_rejected)
      - scored_all: 所有评分过的策略（含通过和未通过）
      - scored_passed: 通过硬性条件的策略（得分>0）
      - scored_rejected: 未通过硬性条件的策略（得分=0或<80）
    """
    print("\n" + "=" * 80)
    print("  📊 步骤5: 评分与排行榜更新")
    print("=" * 80)

    leaderboard = load_leaderboard()
    library = load_strategy_library()
    rejected_list = load_rejected_strategies()
    scored_all = []
    scored_passed = []
    scored_rejected = []

    for strategy in backtest_results:
        bt_result = strategy.get('backtest_result', {})
        if not bt_result or not bt_result.get('main_period'):
            continue

        main = bt_result.get('main_period', {})
        # 可移植性评分
        portability = score_portability(
            strategy.get('code', ''),
            strategy.get('source', '')
        )

        # 构建排行榜条目
        strategy_info = {
            'strategy_name': strategy.get('name', 'Unknown'),
            'source_link': strategy.get('source_link', ''),
            'fingerprint': strategy.get('fingerprint', ''),
            'strategy_code': strategy.get('code', '')[:500],  # 截断
            'description': strategy.get('description', ''),
            'portability_score': portability,
            'pine_script_rejected': strategy.get('pine_script_rejected', False),
            'strategy_params': strategy.get('strategy_params', {}),
        }

        entry = build_leaderboard_entry(bt_result, strategy_info)

        # 计算未通过原因
        reason_parts = []
        if abs(main.get('mean_max_drawdown', 0)) > 25:
            reason_parts.append('回撤>25%')

        if entry and entry.get('total_score', 0) > 0:
            scored_all.append(entry)

            # 所有得分>0的策略都有机会进入排行榜（前十高评分，无最低分门槛）
            scored_passed.append(entry)
            print(f"  ✅ {entry['strategy_name']}: "
                  f"得分={entry['total_score']}, "
                  f"年化={entry['annual_return']}%, "
                  f"夏普={entry['sharpe']}, "
                  f"回撤={entry['max_drawdown']}%, "
                  f"盈亏比={entry['profit_factor']}, "
                  f"胜率={entry['win_rate']}%, "
                  f"年交易={entry['avg_trades_per_year']}次")

            # 更新排行榜
            leaderboard = update_leaderboard(entry, leaderboard)
            # 更新策略库
            library = add_strategy_to_library(entry, library)

        else:
            # entry为None或得分=0（回撤>25%硬性条件不满足），手动构建废弃条目
            reject_entry = _build_rejected_entry(strategy, bt_result, main, reason_parts)
            if reject_entry:
                scored_all.append(reject_entry)
                scored_rejected.append(reject_entry)
                reason_str = '; '.join(reason_parts) if reason_parts else '回撤>25%（硬性条件不满足）'
                reject_entry['rejection_reason'] = reason_str
                reject_entry['rejected_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                rejected_list = add_rejected_strategy(reject_entry, rejected_list)
                print(f"  ❌ {reject_entry['strategy_name']}: "
                      f"得分=0, 年化={reject_entry['annual_return']}%, "
                      f"回撤={reject_entry['max_drawdown']}% — {reason_str}")

    # 保存
    save_leaderboard(leaderboard)
    save_strategy_library(library)
    save_rejected_strategies(rejected_list)

    return scored_all, scored_passed, scored_rejected


# ================================================================
# 主流程
# ================================================================
def run_full_scan(market: str = 'us', max_stocks: int = None):
    """执行完整的策略搜索、验证、去重与归档流程"""

    scan_start = datetime.now()
    print("=" * 80)
    print(f"  🤖 策略回测定时调度器 — 扫描开始")
    print(f"  ⏰ 时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🌍 市场: {market}")
    print("=" * 80)

    # 步骤1: 搜索
    strategies = search_strategies()
    total_found = len(strategies)

    # 步骤2: Pine Script一票否决
    strategies_after_veto, pine_veto_count = check_pine_veto_batch(strategies)

    # 步骤3: 去重
    new_strategies, dedup_count = deduplicate_strategies(strategies_after_veto, market=market)

    # 步骤4: 回测
    backtest_results = run_backtest_batch(new_strategies, market=market, max_stocks=max_stocks)

    # 步骤5: 评分与排行榜
    scored_all, scored_passed, scored_rejected = score_and_rank(backtest_results)

    # 输出报告
    scan_end = datetime.now()
    duration = (scan_end - scan_start).total_seconds()

    leaderboard = load_leaderboard()
    rejected_list = load_rejected_strategies()

    # 构建全部策略回测数据表格
    all_strategies_table = format_all_strategies_table(scored_all, market)

    # 构建前十排行榜详细展示
    top10_detail = _format_top10_detail(leaderboard)

    report = f"""
{'=' * 80}
  📋 执行报告
{'=' * 80}

  本次扫描时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}
  扫描耗时: {duration:.0f}秒
  本次发现策略数量: {total_found}
  Pine Script一票否决数量: {pine_veto_count}
  通过去重后新策略数量: {len(new_strategies)}
  通过回测验证数量: {len(backtest_results)}
  评分入库数量: {len(scored_all)}
  ✅ 有评分策略数量（得分>0）: {len(scored_passed)}
  ❌ 零分策略数量（回撤>25%）: {len(scored_rejected)}
  🗑️ 废弃策略库累计: {len(rejected_list)}个

{all_strategies_table}

  🏆 历史前十高评分策略排行榜:

{format_leaderboard_table(leaderboard)}

{top10_detail}

  废弃策略库（共{len(rejected_list)}个，展示最近10个）:

{format_rejected_table(rejected_list, max_display=10)}

{'=' * 80}
"""

    print(report)

    # 保存报告
    report_path = os.path.join(PROJECT_DIR, 'reports',
                                f'scan_{scan_start.strftime("%Y%m%d_%H%M%S")}.md')
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    # 返回结构化结果
    return {
        'scan_time': scan_start.strftime('%Y-%m-%d %H:%M:%S'),
        'duration_seconds': duration,
        'total_found': total_found,
        'pine_veto_count': pine_veto_count,
        'new_after_dedup': len(new_strategies),
        'backtest_passed': len(backtest_results),
        'scored_count': len(scored_all),
        'passed_count': len(scored_passed),
        'rejected_count': len(scored_rejected),
        'total_rejected_in_db': len(rejected_list),
        'leaderboard': leaderboard,
        'scored_all': scored_all,
        'scored_rejected': scored_rejected,
    }


def show_status():
    """显示当前状态"""
    library = load_strategy_library()
    leaderboard = load_leaderboard()

    print(f"\n📊 策略库状态:")
    print(f"  策略总数: {len(library.get('strategies', []))}")
    print(f"  最后更新: {library.get('last_updated', 'N/A')}")

    print(f"\n🏆 排行榜:")
    print(format_leaderboard_table(leaderboard))


# ================================================================
# 命令行入口
# ================================================================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='策略回测定时调度器')
    parser.add_argument('action', choices=['run', 'status', 'report'],
                        default='status', nargs='?',
                        help='run=执行扫描, status=查看状态, report=查看报告')
    parser.add_argument('--market', default='us', choices=['us', 'hk'],
                        help='回测市场')
    parser.add_argument('--max-stocks', type=int, default=None,
                        help='最大回测标的数(调试用)')

    args = parser.parse_args()

    if args.action == 'run':
        result = run_full_scan(market=args.market, max_stocks=args.max_stocks)
        # 退出码
        sys.exit(0 if result.get('backtest_passed', 0) > 0 else 1)
    elif args.action == 'status':
        show_status()
    elif args.action == 'report':
        show_status()
