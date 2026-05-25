#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
熊市策略回测定时调度器
======================
主入口: python bear_strategy_scheduler.py [run|status|report]

职责:
  1. 搜索熊市策略（调用web_search获取公开策略代码）
  2. Pine Script一票否决检测
  3. 策略去重与指纹计算
  4. 调度本地回测脚本执行回测（熊市特定参数）
  5. 评分与排行榜更新（熊市调整版评分体系）
  6. 输出执行报告 + 邮件发送

执行频率: 每2小时一次

熊市特定:
  - 回测区间: 2007-10-01 ~ 2009-03-09 (金融危机) / 2020-02-19 ~ 2020-03-23 (新冠)
  - 压力测试: 2018-01-01 ~ 2018-12-31
  - 牛市辅助: 2020-04-01 ~ 2021-12-31
  - 滑点0.15%, 融券年化3%, 最大回撤硬性条件≤20%
  - 评分权重: 卡尔玛比率25%, 最大回撤30%
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = '/data/workspace' if sys.platform != 'win32' else r'C:\Users\blakehao\.qclaw\workspace\workspace_full_20260430'

sys.path.insert(0, PROJECT_DIR)

from bear_strategy_searcher import (
    get_bear_search_queries, bear_initial_filter, process_bear_search_results,
    detect_safe_haven_assets, extract_code_from_github_readme, extract_pine_script
)
from pine_validator import check_pine_veto, score_portability, analyze_pine_for_translation
from strategy_dedup import (
    compute_strategy_fingerprint, fingerprint_short,
    load_strategy_library, save_strategy_library, check_duplicate,
    add_strategy_to_library
)
from bear_strategy_ranker import (
    compute_bear_total_score, classify_bear_strategy,
    classify_volatility_correlation, check_bull_compatibility,
    build_bear_leaderboard_entry,
    load_bear_leaderboard, save_bear_leaderboard, update_bear_leaderboard,
    format_bear_leaderboard_table
)
from hybrid_searcher import (
    hybrid_search, BEAR_PARAM_VARIANTS, BEAR_GITHUB_QUERIES,
    generate_param_variants, github_search,
)


# ================================================================
# 配置
# ================================================================
RUN_BACKTEST_SCRIPT = os.path.join(PROJECT_DIR, 'bear_run_backtest.py')
STRATEGY_CODE_DIR = os.path.join(PROJECT_DIR, 'bear_strategies')
RISK_FREE_RATE_DEFAULT = 0.055  # 10年美债~4.5% + 1% = 5.5%

# 邮件配置
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USER = '848786642@qq.com'
SMTP_PASSWORD = 'ljbtvacrctjobfed'
EMAIL_TO = '848786642@qq.com'

os.makedirs(STRATEGY_CODE_DIR, exist_ok=True)


# ================================================================
# 废弃策略管理（熊市版）
# ================================================================
BEAR_REJECTED_DB_PATH = os.path.join(PROJECT_DIR, 'bear_rejected_strategies.json')


def load_bear_rejected_strategies(path: str = BEAR_REJECTED_DB_PATH) -> list:
    """加载废弃策略列表"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_bear_rejected_strategies(rejected: list, path: str = BEAR_REJECTED_DB_PATH):
    """保存废弃策略列表"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)


def add_bear_rejected_strategy(entry: dict, rejected_list: list) -> list:
    """添加策略到废弃列表（指纹+市场联合去重）"""
    new_fp = entry.get('fingerprint', '')
    new_market = entry.get('market', '')
    for i, existing in enumerate(rejected_list):
        if existing.get('fingerprint', '') == new_fp and existing.get('market', '') == new_market:
            if entry.get('total_score', 0) > existing.get('total_score', 0):
                rejected_list[i] = entry
            return rejected_list
    rejected_list.append(entry)
    return rejected_list


# ================================================================
# 内置熊市策略
# ================================================================
def _get_builtin_bear_strategies() -> list:
    """获取内置的熊市防御策略列表"""
    strategies = []

    builtin = [
        {
            'name': '保护性看跌期权策略(简化版)',
            'description': '熊市防御核心策略：持有标的的同时买入看跌期权对冲下行风险。'
                           '简化版使用止损替代期权，在趋势转弱时减仓避险。适合港美股熊市防御。',
            'source': 'builtin',
            'source_link': 'generated:bear_defensive',
            'code': _read_builtin_strategy('protective_put_simple'),
            'strategy_type': '高股息防御',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': 'RSI超卖反弹策略',
            'description': '均值回归（抄底）策略：在熊市下跌中寻找RSI超卖后的反弹机会，'
                           'RSI从30以下回升时入场，RSI超买或再次下穿50时出场。适合港美股超跌反弹。',
            'source': 'builtin',
            'source_link': 'generated:bear_mean_reversion',
            'code': _read_builtin_strategy('rsi_oversold_bounce'),
            'strategy_type': '均值回归（抄底）',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'Supertrend做空趋势策略',
            'description': '做空趋势策略：当Supertrend翻红时做空，翻绿时平仓。'
                           '在熊市趋势中捕捉下跌波段，含ATR止损保护。适合港美股熊市做空。',
            'source': 'builtin',
            'source_link': 'generated:bear_short_trend',
            'code': _read_builtin_strategy('supertrend_short'),
            'strategy_type': '做空趋势',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': '布林带均值回归(熊市版)',
            'description': '均值回归策略：价格触及布林带下轨买入（超跌），回归中轨平仓。'
                           '熊市版增加ADX过滤和更紧的止损。适合港美股熊市波动行情。',
            'source': 'builtin',
            'source_link': 'generated:bear_bollinger',
            'code': _read_builtin_strategy('bollinger_bear_reversion'),
            'strategy_type': '均值回归（抄底）',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': '高股息低波防御策略',
            'description': '高股息防御策略：选择低波动率+高股息标的持有，配合趋势过滤止损。'
                           '熊市中防御第一，利用股息收入缓冲下跌。适合港美股稳健防御。',
            'source': 'builtin',
            'source_link': 'generated:bear_dividend_defense',
            'code': _read_builtin_strategy('dividend_defense'),
            'strategy_type': '高股息防御',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': '股债黄金三均线轮动',
            'description': '避险资产轮动策略：在股票、国债、黄金三类资产间按均线动量轮动，'
                           '牛市持有股票，熊市切换到国债或黄金。经典避险轮动策略。适合港美股+避险ETF。',
            'source': 'builtin',
            'source_link': 'generated:bear_safe_haven_rotation',
            'code': _read_builtin_strategy('safe_haven_rotation'),
            'strategy_type': '避险资产轮动',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': 'MACD死叉做空策略',
            'description': '做空趋势策略：MACD柱状图从正转负(死叉)+价格在长期EMA下方时做空，'
                           'MACD金叉或价格突破EMA时平仓。适合港美股熊市趋势做空。',
            'source': 'builtin',
            'source_link': 'generated:bear_macd_short',
            'code': _read_builtin_strategy('macd_short'),
            'strategy_type': '做空趋势',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': '配对交易均值回归策略',
            'description': '对冲/配对策略：选择高相关股票对，根据价差Z-Score进行配对交易，'
                           '做多弱势股+做空强势股，市场中性。适合港美股配对对冲。',
            'source': 'builtin',
            'source_link': 'generated:bear_pairs_trading',
            'code': _read_builtin_strategy('pairs_trading'),
            'strategy_type': '对冲/配对',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': True,
        },
        {
            'name': '低波轮动策略',
            'description': '低波轮动策略：选择历史波动率最低的标的持有，定期轮动。'
                           '熊市中低波动标的往往抗跌，防御效果优异。适合港美股防御型投资者。',
            'source': 'builtin',
            'source_link': 'generated:bear_low_vol_rotation',
            'code': _read_builtin_strategy('low_vol_rotation'),
            'strategy_type': '低波轮动',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'VIX择时避险策略',
            'description': '避险资产轮动策略：当VIX指数突破阈值时切换到避险资产（国债/黄金），'
                           'VIX回落时恢复股票持仓。利用恐慌情绪择时切换。适合美股+避险ETF。',
            'source': 'builtin',
            'source_link': 'generated:bear_vix_timing',
            'code': _read_builtin_strategy('vix_timing'),
            'strategy_type': '避险资产轮动',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
        {
            'name': 'EMA空头排列做空策略',
            'description': '做空趋势策略：当EMA10/20/50形成空头排列（EMA10<EMA20<EMA50）时做空，'
                           '均线多头排列时平仓。经典趋势反转做空策略。',
            'source': 'builtin',
            'source_link': 'generated:bear_ema_short',
            'code': _read_builtin_strategy('ema_short'),
            'strategy_type': '做空趋势',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
        },
    ]

    for s in builtin:
        if s['code'] and len(s['code'].strip()) > 20:
            strategies.append(s)

    return strategies


def _read_builtin_strategy(name: str) -> str:
    """读取内置策略代码"""
    filepath = os.path.join(STRATEGY_CODE_DIR, f'{name}.py')
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ''


# ================================================================
# 步骤1: 搜索策略
# ================================================================
def search_strategies() -> list:
    """
    混合搜索熊市策略代码。
    方案A: GitHub API搜索（优先）→ 方案B: 参数变体（降级）
    确保每次扫描至少找到3个新策略。
    """
    print("\n" + "=" * 80)
    print("  🔍 步骤1: 搜索熊市策略（混合搜索 A+B）")
    print("=" * 80)

    found_strategies = []

    builtin = _get_builtin_bear_strategies()
    found_strategies.extend(builtin)
    print(f"  📦 内置熊市策略: {len(builtin)}个")

    # ---- 混合搜索: 方案A(GitHub) + 方案B(参数变体) ----
    bear_library_path = os.path.join(PROJECT_DIR, 'bear_strategy_library.json')
    library = load_strategy_library(bear_library_path)
    existing_fps = {(s.get('fingerprint', ''), s.get('market', ''))
                    for s in library.get('strategies', [])}
    # 也从废弃策略库收集指纹
    rejected_list = load_bear_rejected_strategies()
    for r in rejected_list:
        existing_fps.add((r.get('fingerprint', ''), r.get('market', '')))

    # 执行混合搜索
    hybrid_results, search_stats = hybrid_search(
        market_type='bear',
        builtin_strategies=builtin,
        variant_templates=BEAR_PARAM_VARIANTS,
        existing_fingerprints=existing_fps,
        min_new=3,
        github_queries=BEAR_GITHUB_QUERIES,
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

    cached = _load_search_cache()
    if cached:
        found_strategies.extend(cached)
        print(f"  💾 搜索缓存: {len(cached)}个策略")

    print(f"\n  📊 本次发现策略数量: {len(found_strategies)}")
    return found_strategies


def _load_search_cache() -> list:
    """加载搜索缓存"""
    cache_path = os.path.join(PROJECT_DIR, 'bear_search_cache.json')
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
    """批量检查Pine Script一票否决"""
    print("\n" + "=" * 80)
    print("  🔒 步骤2: Pine Script一票否决检测")
    print("=" * 80)

    vetoed_count = 0
    passed = []

    for strategy in strategies:
        code = strategy.get('code', '')
        source = strategy.get('source', '')

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
    """策略去重与指纹计算（熊市版独立策略库）"""
    print("\n" + "=" * 80)
    print("  🔑 步骤3: 策略去重与指纹计算")
    print("=" * 80)

    # 加载熊市策略库
    bear_library_path = os.path.join(PROJECT_DIR, 'bear_strategy_library.json')
    library = load_strategy_library(bear_library_path)
    existing_fps = {(s.get('fingerprint', ''), s.get('market', ''))
                    for s in library.get('strategies', [])}
    print(f"  📚 熊市策略库现有: {len(existing_fps)}个策略")

    new_strategies = []
    dedup_count = 0

    for strategy in strategies:
        code = strategy.get('code', '')
        params = strategy.get('params', {})
        if not params:
            params = _extract_params_from_code(code)

        fingerprint = compute_strategy_fingerprint(code, params)
        strategy['fingerprint'] = fingerprint
        strategy['fingerprint_short'] = fingerprint_short(fingerprint)
        strategy['strategy_params'] = params
        strategy['market'] = market

        fp_market_key = (fingerprint, market)
        if fp_market_key in existing_fps:
            dedup_count += 1
            existing_name = ''
            existing_score = 0
            for s in library.get('strategies', []):
                if s.get('fingerprint', '') == fingerprint and s.get('market', '') == market:
                    existing_name = s.get('strategy_name', '?')
                    existing_score = s.get('total_score', 0)
                    break
            print(f"  🔄 重复: {strategy['name']} [{market.upper()}] "
                  f"(已有: {existing_name}, 得分: {existing_score})")
        else:
            new_strategies.append(strategy)
            print(f"  ✅ 新策略: {strategy['name']} [{market.upper()}] "
                  f"(指纹: {fingerprint_short(fingerprint)})")

    print(f"\n  📊 去重数量: {dedup_count}")
    print(f"  📊 通过去重后新策略数量: {len(new_strategies)}")
    return new_strategies, dedup_count


def _extract_params_from_code(code: str) -> dict:
    """从策略代码中提取参数"""
    import re
    params = {}
    pattern = r'(?:ema_fast|ema_slow|atr_period|atr_mult|rsi_period|lookback|' \
              r'entry_window|exit_window|macd_fast|macd_slow|macd_signal|' \
              r'multiplier|period|window|threshold|bb_period|bb_std|' \
              r'vix_threshold|calmar_target|stop_loss|take_profit)\s*=\s*(\d+\.?\d*)'
    for match in re.finditer(pattern, code):
        try:
            val = float(match.group(1))
            params[match.group(0).split('=')[0].strip()] = val
        except ValueError:
            pass
    return params


# ================================================================
# 步骤4: 回测验证（熊市版）
# ================================================================
def run_backtest_batch(strategies: list, market: str = 'us',
                       max_stocks: int = None) -> list:
    """批量执行熊市回测验证"""
    print("\n" + "=" * 80)
    print("  🚀 步骤4: 熊市回测验证")
    print("=" * 80)

    backtest_results = []

    for strategy in strategies:
        name = strategy.get('name', 'Unknown')
        code = strategy.get('code', '')

        if not code or len(code.strip()) < 20:
            print(f"  ⏭️ 跳过: {name} (无有效代码)")
            continue

        # 检测做空需求
        has_short = _detect_short_signals(code)
        if has_short:
            print(f"  ⚠️ {name}: 检测到做空信号逻辑")

        # 生成策略文件
        strategy_file = _generate_strategy_file(strategy)
        if not strategy_file:
            print(f"  ⏭️ 跳过: {name} (策略文件生成失败)")
            continue

        # 检测避险资产需求
        haven_info = detect_safe_haven_assets(strategy)
        safe_haven_etfs = haven_info['etf_list'] if haven_info['etf_list'] else None

        # 调用回测脚本
        print(f"\n  🔄 回测: {name}" +
              (f" +避险ETF{safe_haven_etfs}" if safe_haven_etfs else ""))
        result = _execute_backtest(strategy_file, market, max_stocks, safe_haven_etfs)

        if result:
            strategy['backtest_result'] = result
            strategy['market'] = market
            backtest_results.append(strategy)
            main = result.get('main_period', {})
            if main:
                dd = main.get('mean_max_drawdown', 0)
                annual = main.get('mean_annual_return', 0)
                calmar = annual / abs(dd) if abs(dd) > 0 else 0
                print(f"    ✅ 年化: {annual}% | 回撤: {dd}% | "
                      f"卡尔玛: {calmar:.2f} | 夏普: {main.get('mean_sharpe', '?')}")
        else:
            print(f"    ❌ 回测失败: {name}")

    print(f"\n  📊 通过回测验证数量: {len(backtest_results)}")
    return backtest_results


def _detect_short_signals(code: str) -> bool:
    """检测策略代码中是否包含做空信号逻辑"""
    short_indicators = ['short_entries', 'short_exits', 'sell_short',
                        'short_entry', '做空', 'direction="short"',
                        'direction=\'short\'']
    return any(ind in code for ind in short_indicators)


def _generate_strategy_file(strategy: dict) -> str:
    """为策略生成独立的Python文件"""
    name = strategy.get('name', 'Unknown')
    code = strategy.get('code', '')
    params = strategy.get('strategy_params', {})

    safe_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in name)
    filepath = os.path.join(STRATEGY_CODE_DIR, f'{safe_name}.py')

    if 'generate_signals' in code:
        content = code
    elif 'def ' in code:
        content = f"""
# 策略: {name}
# 来源: {strategy.get('source', 'unknown')}
# 类型: 熊市策略
# 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "{name}"
STRATEGY_TYPE = "{strategy.get('strategy_type', '其他')}"
STRATEGY_PARAMS = {params}

{code}
"""
    else:
        content = f"""
# 策略: {name}
# 来源: {strategy.get('source', 'unknown')}
# 类型: 熊市策略
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
                      max_stocks: int = None, safe_haven_etfs: list = None) -> dict:
    """调用bear_run_backtest.py执行回测"""
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
    if safe_haven_etfs:
        cmd.extend(['--safe-haven-etfs'] + safe_haven_etfs)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=PROJECT_DIR,
        )
        if result.returncode != 0:
            print(f"    ⚠️ 回测脚本返回码: {result.returncode}")
            print(f"    stderr: {result.stderr[:500]}")
            return None

        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except subprocess.TimeoutExpired:
        print(f"    ⚠️ 回测超时(>600s)")
    except Exception as e:
        print(f"    ⚠️ 回测执行异常: {e}")

    return None


# ================================================================
# 步骤5: 评分与排行榜（熊市版）
# ================================================================
def _build_bear_rejected_entry(strategy: dict, bt_result: dict, main: dict,
                                reason_parts: list) -> dict:
    """为得分=0或回撤>20%的策略构建废弃条目"""
    try:
        annual = main.get('mean_annual_return', 0)
        sharpe = main.get('mean_sharpe', 0)
        dd = main.get('mean_max_drawdown', 0)
        pf = main.get('mean_profit_factor', 0)
        wr = main.get('mean_win_rate', 0)
        trades = main.get('mean_avg_trades_per_year', 0)
        abs_dd = abs(dd) if dd != 0 else 0.01
        calmar = annual / abs_dd if abs_dd > 0 else 0

        entry = {
            'strategy_name': strategy.get('name', 'Unknown'),
            'source_link': strategy.get('source_link', ''),
            'fingerprint': strategy.get('fingerprint', ''),
            'fingerprint_short': strategy.get('fingerprint_short', ''),
            'strategy_type': classify_bear_strategy(strategy.get('name', ''),
                                                     strategy.get('code', ''),
                                                     strategy.get('description', '')),
            'total_score': 0,
            'score_detail': {
                'annual_return_score': 0,
                'calmar_ratio_score': 0,
                'max_drawdown_score': 0,
                'profit_factor_score': 0,
                'win_rate_score': 0,
                'base_score': 0,
                'bull_compatible_bonus': 0,
                'survivorship_penalty': -10.0,
                'leverage_penalty': 0,
                'total_score': 0,
                'max_drawdown_hard_fail': True,
            },
            'annual_return': round(annual, 2) if annual else 0,
            'calmar_ratio': round(calmar, 2) if calmar else 0,
            'sharpe': round(sharpe, 2) if sharpe else 0,
            'max_drawdown': round(dd, 2) if dd else 0,
            'profit_factor': round(pf, 2) if pf else 0,
            'win_rate': round(wr, 2) if wr else 0,
            'avg_trades_per_year': round(trades, 2) if trades else 0,
            'cross_period_robust': False,
            'bull_compatible': False,
            'bull_compatible_tag': '⚠️ 仅限熊市',
            'survivorship_bias': True,
            'bias_tag': '⚠️',
            'pine_script_rejected': strategy.get('pine_script_rejected', False),
            'short_cost_warning': bt_result.get('short_cost_warning', False),
            'leverage_warning': False,
            'portability_score': score_portability(
                strategy.get('code', ''), strategy.get('source', '')),
            'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'first_listed_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'removal_reason': '',
            'stress_annual': 0,
            'stress_dd': 0,
            'bull_annual': 0,
            'bull_dd': 0,
            'market': strategy.get('market', 'unknown'),
            'n_stocks': main.get('n_stocks', 0),
            'volatility_feature': '❓ 依赖不明',
            'risk_tags': '⚠️幸存者偏差',
        }
        return entry
    except Exception as e:
        print(f"  ⚠️ 构建废弃条目异常: {e}")
        return None


def score_and_rank(backtest_results: list) -> tuple:
    """评分并更新熊市排行榜"""
    print("\n" + "=" * 80)
    print("  📊 步骤5: 评分与排行榜更新（熊市版）")
    print("=" * 80)

    leaderboard = load_bear_leaderboard()
    bear_library_path = os.path.join(PROJECT_DIR, 'bear_strategy_library.json')
    library = load_strategy_library(bear_library_path)
    rejected_list = load_bear_rejected_strategies()
    scored_all = []
    scored_passed = []
    scored_rejected = []

    for strategy in backtest_results:
        bt_result = strategy.get('backtest_result', {})
        if not bt_result or not bt_result.get('main_period'):
            continue

        main = bt_result.get('main_period', {})
        portability = score_portability(
            strategy.get('code', ''), strategy.get('source', ''))

        strategy_info = {
            'strategy_name': strategy.get('name', 'Unknown'),
            'source_link': strategy.get('source_link', ''),
            'fingerprint': strategy.get('fingerprint', ''),
            'strategy_code': strategy.get('code', '')[:500],
            'description': strategy.get('description', ''),
            'portability_score': portability,
            'pine_script_rejected': strategy.get('pine_script_rejected', False),
            'strategy_params': strategy.get('strategy_params', {}),
        }

        entry = build_bear_leaderboard_entry(bt_result, strategy_info)

        # 计算风险标记原因
        reason_parts = []
        if abs(main.get('mean_max_drawdown', 0)) > 20:
            reason_parts.append('回撤>20%')

        if entry:
            score = entry.get('total_score', 0)
            scored_all.append(entry)

            dd = entry.get('max_drawdown', 0)
            annual = entry.get('annual_return', 0)
            calmar = entry.get('calmar_ratio', 0)
            pf = entry.get('profit_factor', 0)
            wr = entry.get('win_rate', 0)
            trades = entry.get('avg_trades_per_year', 0)

            # 所有策略都进入排行榜（保留前十高评分，无最低门槛）
            scored_passed.append(entry)
            leaderboard = update_bear_leaderboard(entry, leaderboard)
            library = add_strategy_to_library(entry, library)

            tag = '✅' if score > 0 else '⚠️'
            print(f"  {tag} {entry['strategy_name']}: "
                  f"得分={score}, "
                  f"年化={annual}%, "
                  f"卡尔玛={calmar}, "
                  f"夏普={entry.get('sharpe', 0)}, "
                  f"回撤={dd}%, "
                  f"盈亏比={pf}, "
                  f"胜率={wr}%, "
                  f"年交易={trades}, "
                  f"兼容={entry.get('bull_compatible_tag', '')}")

            # 回撤>20%的策略同时记录到废弃库（标记风险但不阻止上榜）
            if reason_parts:
                reject_entry = _build_bear_rejected_entry(strategy, bt_result, main, reason_parts)
                if reject_entry:
                    reject_entry['rejection_reason'] = '; '.join(reason_parts)
                    reject_entry['rejected_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    rejected_list = add_bear_rejected_strategy(reject_entry, rejected_list)
        else:
            print(f"  ❌ 构建排行榜条目失败: {strategy.get('name', '?')}")

    save_bear_leaderboard(leaderboard)
    save_strategy_library(library, bear_library_path)
    save_bear_rejected_strategies(rejected_list)

    return scored_all, scored_passed, scored_rejected


# ================================================================
# 报告格式化
# ================================================================
def format_all_strategies_table(scored: list, market: str = 'us') -> str:
    """格式化所有策略回测数据表格（熊市版）"""
    if not scored:
        return "本次无策略完成回测评分。"

    lines = [
        f"\n### 📊 全部策略回测数据（熊市·{market.upper()}）\n",
        "| # | 策略名称 | 类型 | 波动率特征 | 指纹 | 得分 | 年化收益 | 卡尔玛 | 最大回撤 | 盈亏比 | 胜率 | 单标年交易 | 是否通过 | 未通过原因 |",
        "|---|---------|------|-----------|------|------|---------|-------|---------|--------|------|-----------|---------|-----------|",
    ]

    for i, entry in enumerate(scored, 1):
        name = entry.get('strategy_name', 'Unknown')[:24]
        s_type = entry.get('strategy_type', '其他')
        vol = entry.get('volatility_feature', '❓')
        fp = entry.get('fingerprint_short', '????????')
        score = entry.get('total_score', 0)
        annual = entry.get('annual_return', 0)
        calmar = entry.get('calmar_ratio', 0)
        dd = entry.get('max_drawdown', 0)
        pf = entry.get('profit_factor', 0)
        wr = entry.get('win_rate', 0)
        trades = entry.get('avg_trades_per_year', 0)
        passed = score > 0
        pass_tag = '✅' if passed else '❌'

        reasons = []
        if abs(dd) > 20:
            reasons.append('回撤>20%')
        if annual < 8:
            reasons.append('年化<8%')
        if calmar < 0.5:
            reasons.append('卡尔玛<0.5')
        if score < 80:
            reasons.append(f'得分{score}')
        reason_str = '; '.join(reasons) if not passed else '-'

        lines.append(
            f"| {i} | {name} | {s_type} | {vol} | {fp} | {score} | "
            f"{annual}% | {calmar} | {dd}% | {pf} | {wr}% | {trades} | {pass_tag} | {reason_str} |"
        )

    return '\n'.join(lines)


def format_rejected_table(rejected_list: list, max_display: int = 10) -> str:
    """格式化废弃策略库表格"""
    if not rejected_list:
        return "  （废弃策略库为空）"

    sorted_list = sorted(rejected_list,
                         key=lambda x: x.get('rejected_time', ''), reverse=True)
    display_list = sorted_list[:max_display]

    lines = [
        "| # | 策略名称 | 市场 | 类型 | 指纹 | 得分 | 年化 | 卡尔玛 | 回撤 | 废弃原因 | 废弃时间 |",
        "|---|---------|------|------|------|------|------|-------|------|---------|---------|",
    ]

    for i, entry in enumerate(display_list, 1):
        name = entry.get('strategy_name', 'Unknown')[:24]
        market = entry.get('market', '?').upper()
        s_type = entry.get('strategy_type', '其他')
        fp = entry.get('fingerprint_short', entry.get('fingerprint', '')[:8])
        score = entry.get('total_score', 0)
        annual = entry.get('annual_return', 0)
        calmar = entry.get('calmar_ratio', 0)
        dd = entry.get('max_drawdown', 0)
        reason = entry.get('rejection_reason', '得分<80')
        rej_time = entry.get('rejected_time', 'N/A')

        lines.append(
            f"| {i} | {name} | {market} | {s_type} | {fp} | {score} | "
            f"{annual}% | {calmar} | {dd}% | {reason} | {rej_time} |"
        )

    if len(sorted_list) > max_display:
        lines.append(f"\n  ... 还有 {len(sorted_list) - max_display} 个废弃策略未显示")

    return '\n'.join(lines)


def _format_top10_detail(leaderboard: list) -> str:
    """格式化前十排行榜详细参数展示（熊市版）"""
    if not leaderboard:
        return "  （排行榜为空）"

    lines = []
    for i, entry in enumerate(leaderboard, 1):
        name = entry.get('strategy_name', 'Unknown')
        s_type = entry.get('strategy_type', '其他')
        vol = entry.get('volatility_feature', '❓')
        market = entry.get('market', '?').upper()
        score = entry.get('total_score', 0)
        annual = entry.get('annual_return', 0)
        sharpe = entry.get('sharpe', 0)
        dd = entry.get('max_drawdown', 0)
        calmar = entry.get('calmar_ratio', 0)
        pf = entry.get('profit_factor', 0)
        wr = entry.get('win_rate', 0)
        trades = entry.get('avg_trades_per_year', 0)
        compat = entry.get('bull_compatible_tag', '⚠️仅限熊市')
        risk = entry.get('risk_tags', '')
        params = entry.get('strategy_params', {})
        desc = entry.get('strategy_description', '')
        stress_annual = entry.get('stress_annual', 0)
        stress_dd = entry.get('stress_dd', 0)
        bull_annual = entry.get('bull_annual', 0)
        bull_dd = entry.get('bull_dd', 0)
        bias = '⚠️' if entry.get('survivorship_bias') else '✅'

        lines.append(f"  ┌─ 🥇 第{i}名: {name} ({market}) ─────────────────")
        lines.append(f"  │ 策略类型: {s_type}")
        lines.append(f"  │ 波动率特征: {vol}")
        lines.append(f"  │ 综合得分: {score}分")
        lines.append(f"  │ ── 核心指标 ──")
        lines.append(f"  │ 年化收益率: {annual}%")
        lines.append(f"  │ 卡尔玛比率: {calmar}")
        lines.append(f"  │ 夏普比率:   {sharpe}")
        lines.append(f"  │ 最大回撤:   {dd}%")
        lines.append(f"  │ 盈亏比:     {pf}")
        lines.append(f"  │ 胜率:       {wr}%")
        lines.append(f"  │ 年交易次数: {trades}")
        lines.append(f"  │ ── 压力测试(2023高利率震荡市) ──")
        lines.append(f"  │ 压力期年化: {stress_annual}%")
        lines.append(f"  │ 压力期回撤: {stress_dd}%")
        lines.append(f"  │ ── 牛市辅助测试 ──")
        lines.append(f"  │ 牛市区间年化: {bull_annual}%")
        lines.append(f"  │ 牛市区间回撤: {bull_dd}%")
        lines.append(f"  │ 兼容标记: {compat}")
        lines.append(f"  │ 数据偏差: {bias}  风险标记: {risk}")
        if desc:
            lines.append(f"  │ 描述: {desc[:80]}")
        if params:
            lines.append(f"  │ ── 策略参数 ──")
            for k, v in params.items():
                lines.append(f"  │   {k} = {v}")
        lines.append(f"  └────────────────────────────────────")

    return '\n'.join(lines)


# ================================================================
# 邮件发送
# ================================================================
def send_email_report(report_text: str, scan_time: str):
    """发送HTML邮件报告"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        # 将Markdown转为简易HTML
        html_content = _markdown_to_html(report_text)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"【熊市策略回测报告】{scan_time}"
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO

        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())

        print(f"\n  📧 邮件已发送至 {EMAIL_TO}")
    except Exception as e:
        print(f"\n  ⚠️ 邮件发送失败: {e}")


def _markdown_to_html(md_text: str) -> str:
    """Markdown转精美手机适配HTML邮件，排行榜用卡片式设计"""
    import html as html_mod
    import re

    # 提取排行榜数据（从markdown中解析）
    leaderboard_entries = _parse_leaderboard_from_md(md_text)
    # 提取废弃策略数据
    rejected_entries = _parse_rejected_from_md(md_text)
    # 提取扫描统计信息
    scan_stats = _parse_scan_stats_from_md(md_text)
    # 提取全部策略数据
    all_strategy_entries = _parse_all_strategies_from_md(md_text)

    # 构建HTML
    cards_html = ''
    if leaderboard_entries:
        cards_html = _build_leaderboard_cards(leaderboard_entries)
    
    rejected_html = ''
    if rejected_entries:
        rejected_html = _build_rejected_section(rejected_entries)

    all_strategies_html = ''
    if all_strategy_entries:
        all_strategies_html = _build_all_strategies_section(all_strategy_entries)

    stats_html = _build_stats_section(scan_stats)

    email_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<style>
  body {{ margin:0; padding:0; background:#f0f2f5; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif; -webkit-text-size-adjust:100%; }}
  .container {{ max-width:600px; margin:0 auto; padding:12px; }}
  .header {{ background:linear-gradient(135deg,#8B0000 0%,#c0392b 50%,#e74c3c 100%); padding:28px 24px; border-radius:12px 12px 0 0; text-align:center; }}
  .header h1 {{ color:#fff; margin:0; font-size:20px; letter-spacing:1px; }}
  .header p {{ color:rgba(255,255,255,0.8); margin:8px 0 0; font-size:12px; }}
  .stats {{ background:#fff; padding:16px 20px; border-bottom:1px solid #eee; }}
  .stat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
  .stat-item {{ padding:8px 10px; background:#f8f9fa; border-radius:8px; }}
  .stat-label {{ font-size:11px; color:#999; display:block; }}
  .stat-value {{ font-size:16px; font-weight:700; color:#2c3e50; }}
  .stat-value.red {{ color:#e74c3c; }}
  .stat-value.green {{ color:#27ae60; }}
  .section-title {{ font-size:16px; font-weight:700; color:#2c3e50; margin:20px 0 12px; padding-left:4px; border-left:4px solid #c0392b; }}
  .card {{ background:#fff; border-radius:10px; margin:10px 0; box-shadow:0 1px 4px rgba(0,0,0,0.08); overflow:hidden; }}
  .card-header {{ padding:12px 16px; display:flex; align-items:center; justify-content:space-between; }}
  .card-header .rank {{ font-size:24px; font-weight:800; min-width:36px; }}
  .card-header .rank.r1 {{ color:#FFD700; }}
  .card-header .rank.r2 {{ color:#C0C0C0; }}
  .card-header .rank.r3 {{ color:#CD7F32; }}
  .card-header .rank.r4,.card-header .rank.r5 {{ color:#7f8c8d; }}
  .card-header .name {{ font-size:15px; font-weight:600; color:#2c3e50; flex:1; margin-left:10px; }}
  .card-header .market {{ font-size:11px; padding:2px 8px; border-radius:10px; background:#e8f4fd; color:#2980b9; font-weight:600; }}
  .card-header .market.hk {{ background:#fef3e2; color:#e67e22; }}
  .card-header .score {{ font-size:20px; font-weight:800; color:#c0392b; }}
  .card-body {{ padding:0 16px 14px; }}
  .metric-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }}
  .metric {{ text-align:center; padding:6px 4px; background:#f8f9fa; border-radius:6px; }}
  .metric .label {{ font-size:10px; color:#999; display:block; }}
  .metric .value {{ font-size:13px; font-weight:700; color:#2c3e50; }}
  .metric .value.good {{ color:#27ae60; }}
  .metric .value.bad {{ color:#e74c3c; }}
  .params {{ margin-top:8px; padding:8px 10px; background:#fafbfc; border-radius:6px; font-size:11px; color:#666; line-height:1.6; }}
  .params code {{ background:#e8ecf1; padding:1px 4px; border-radius:3px; font-size:10px; }}
  .tag {{ display:inline-block; font-size:10px; padding:2px 6px; border-radius:8px; margin:1px 2px; }}
  .tag.compat {{ background:#d4edda; color:#155724; }}
  .tag.risk {{ background:#f8d7da; color:#721c24; }}
  .tag.type {{ background:#e2e3f1; color:#4a4a8a; }}
  .tag.vol {{ background:#fff3cd; color:#856404; }}
  .rejected-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  .rejected-table th {{ background:#34495e; color:#fff; padding:8px 6px; text-align:left; font-size:11px; }}
  .rejected-table td {{ padding:6px; border-bottom:1px solid #eee; color:#555; }}
  .rejected-table tr:nth-child(even) {{ background:#f8f9fa; }}
  .all-table {{ width:100%; border-collapse:collapse; font-size:11px; }}
  .all-table th {{ background:#2c3e50; color:#fff; padding:6px 4px; text-align:left; font-size:10px; }}
  .all-table td {{ padding:5px 4px; border-bottom:1px solid #eee; color:#555; font-size:11px; }}
  .all-table tr:nth-child(even) {{ background:#f9fafb; }}
  .footer {{ text-align:center; padding:16px; color:#aaa; font-size:10px; }}
</style></head>
<body>
<div class="container">
  <div class="header">
    <h1>🐻 熊市策略回测定时扫描报告</h1>
    <p>Strategy Arena Bear · Oscillating Market Backtest</p>
  </div>
  {stats_html}
  <div class="section-title">🏆 历史前十排行榜</div>
  {cards_html}
  <div class="section-title">📊 全部策略回测数据</div>
  {all_strategies_html}
  <div class="section-title">🗑️ 废弃策略库（最近10个）</div>
  {rejected_html}
  <div class="footer">Blakever Quant System · Auto-generated Report</div>
</div>
</body></html>"""
    return email_html


def _parse_scan_stats_from_md(md_text: str) -> dict:
    """从Markdown报告中解析扫描统计信息"""
    stats = {}
    for line in md_text.split('\n'):
        line = line.strip()
        if '本次扫描时间:' in line:
            stats['scan_time'] = line.split(':', 1)[1].strip()
        elif '扫描耗时:' in line:
            stats['duration'] = line.split(':', 1)[1].strip()
        elif '本次发现策略数量:' in line:
            stats['total_found'] = line.split(':', 1)[1].strip()
        elif 'Pine Script一票否决数量:' in line:
            stats['pine_veto'] = line.split(':', 1)[1].strip()
        elif '通过去重后新策略数量:' in line:
            stats['new_dedup'] = line.split(':', 1)[1].strip()
        elif '通过回测验证数量:' in line:
            stats['backtest_passed'] = line.split(':', 1)[1].strip()
        elif '评分入库数量:' in line:
            stats['scored'] = line.split(':', 1)[1].strip()
        elif '有评分策略数量' in line:
            stats['scored_passed'] = line.split(':', 1)[1].strip()
        elif '零分策略数量' in line:
            stats['scored_zero'] = line.split(':', 1)[1].strip()
        elif '废弃策略库累计:' in line:
            stats['rejected_total'] = line.replace('个', '').split(':', 1)[1].strip()
    return stats


def _parse_leaderboard_from_md(md_text: str) -> list:
    """从Markdown报告中解析排行榜数据"""
    entries = []
    lines = md_text.split('\n')
    current = None
    in_top10 = False

    for line in lines:
        if any(f'第{i}名' in line for i in range(1, 11)):
            in_top10 = True
            if current:
                entries.append(current)
            # 解析排名和名称
            rank_match = __import__('re').search(r'第(\d)名:\s*(.+?)\s*\(', line)
            market_match = __import__('re').search(r'\((\w+)\)', line)
            current = {
                'rank': int(rank_match.group(1)) if rank_match else 0,
                'name': rank_match.group(2).strip() if rank_match else line,
                'market': market_match.group(1) if market_match else '?',
                'metrics': {},
                'params': {},
                'tags': [],
            }
        elif in_top10 and current:
            stripped = line.strip().lstrip('│').lstrip('┌').lstrip('└').strip()
            if '────' in line or not stripped:
                if '────' in line and '└' in line:
                    in_top10 = False
                continue
            if ':' in stripped or '：' in stripped:
                sep = '：' if '：' in stripped else ':'
                key, _, val = stripped.partition(sep)
                key = key.strip()
                val = val.strip()
                if key == '策略类型':
                    current['type'] = val
                elif key == '波动率特征':
                    current['vol_feature'] = val
                elif key == '综合得分':
                    current['score'] = val.replace('分', '')
                elif key == '年化收益率':
                    current['metrics']['年化'] = val
                elif key == '卡尔玛比率':
                    current['metrics']['卡尔玛'] = val
                elif key == '夏普比率':
                    current['metrics']['夏普'] = val
                elif key == '最大回撤':
                    current['metrics']['回撤'] = val
                elif key == '盈亏比':
                    current['metrics']['盈亏比'] = val
                elif key == '胜率':
                    current['metrics']['胜率'] = val
                elif key == '年交易次数':
                    current['metrics']['年交易'] = val
                elif key == '压力期年化':
                    current['metrics']['压力年化'] = val
                elif key == '压力期回撤':
                    current['metrics']['压力回撤'] = val
                elif key == '牛市区间年化':
                    current['metrics']['牛市年化'] = val
                elif key == '牛市区间回撤':
                    current['metrics']['牛市回撤'] = val
                elif key == '兼容标记':
                    current['compat'] = val
                elif key == '风险标记':
                    if val:
                        current['tags'].append(val)
                elif key == '描述':
                    current['desc'] = val[:60]
                elif '=' in val and not val.startswith('-'):
                    # 策略参数
                    pk, _, pv = val.partition('=')
                    current['params'][pk.strip()] = pv.strip()
                elif '=' in key:
                    pk, _, pv = key.partition('=')
                    current['params'][pk.strip()] = pv.strip()

    if current:
        entries.append(current)
    return entries


def _parse_rejected_from_md(md_text: str) -> list:
    """从Markdown报告中解析废弃策略表格数据"""
    entries = []
    lines = md_text.split('\n')
    in_rejected_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and ('废弃原因' in stripped or '策略名称' in stripped):
            in_rejected_table = True
            continue
        if in_rejected_table and stripped.startswith('|'):
            if all(c in '|-–— ' for c in stripped):
                continue
            cells = [c.strip() for c in stripped.split('|') if c.strip()]
            if len(cells) >= 7:
                entries.append({
                    'name': cells[1] if len(cells) > 1 else '?',
                    'market': cells[2] if len(cells) > 2 else '?',
                    'score': cells[5] if len(cells) > 5 else '?',
                    'annual': cells[6] if len(cells) > 6 else '?',
                    'dd': cells[8] if len(cells) > 8 else '?',
                    'reason': cells[9] if len(cells) > 9 else '?',
                })
        elif in_rejected_table and not stripped.startswith('|'):
            in_rejected_table = False

    return entries[:10]


def _parse_all_strategies_from_md(md_text: str) -> list:
    """从Markdown报告中解析全部策略表格数据"""
    entries = []
    lines = md_text.split('\n')
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and '策略名称' in stripped and '类型' in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith('|'):
            if all(c in '|-–— ' for c in stripped):
                continue
            cells = [c.strip() for c in stripped.split('|') if c.strip()]
            if len(cells) >= 10:
                entries.append({
                    'name': cells[1] if len(cells) > 1 else '?',
                    'type': cells[2] if len(cells) > 2 else '?',
                    'score': cells[5] if len(cells) > 5 else '?',
                    'annual': cells[6] if len(cells) > 6 else '?',
                    'dd': cells[8] if len(cells) > 8 else '?',
                    'pf': cells[9] if len(cells) > 9 else '?',
                    'wr': cells[10] if len(cells) > 10 else '?',
                    'passed': cells[12] if len(cells) > 12 else '?',
                    'reason': cells[13] if len(cells) > 13 else '-',
                })
        elif in_table and not stripped.startswith('|'):
            in_table = False

    return entries


def _build_stats_section(stats: dict) -> str:
    """构建扫描统计区域HTML"""
    if not stats:
        return ''
    items = []
    key_map = [
        ('total_found', '发现策略', ''),
        ('pine_veto', 'Pine否决', 'red'),
        ('new_dedup', '去重新策略', 'green'),
        ('backtest_passed', '回测通过', 'green'),
        ('scored_passed', '有评分✅', 'green'),
        ('scored_zero', '零分❌', 'red'),
        ('rejected_total', '废弃累计', 'red'),
        ('duration', '耗时', ''),
    ]
    for key, label, color in key_map:
        val = stats.get(key, '-')
        cls = f' {color}' if color else ''
        items.append(f'<div class="stat-item"><span class="stat-label">{label}</span><span class="stat-value{cls}">{val}</span></div>')

    scan_time = stats.get('scan_time', '')
    return f'''<div class="stats">
  <div style="font-size:12px;color:#999;margin-bottom:8px;">🕐 {scan_time}</div>
  <div class="stat-grid">{"".join(items)}</div>
</div>'''


def _build_leaderboard_cards(entries: list) -> str:
    """构建排行榜卡片HTML"""
    if not entries:
        return '<div style="text-align:center;padding:20px;color:#999;">暂无上榜策略</div>'

    cards = []
    for e in entries:
        rank = e.get('rank', 0)
        name = e.get('name', '?')
        market = e.get('market', '?').upper()
        score = e.get('score', '0')
        mkt_cls = 'hk' if market == 'HK' else ''
        rank_cls = f'r{rank}' if rank <= 5 else ''
        medal = ['', '🥇', '🥈', '🥉', '4️⃣', '5️⃣'][min(rank, 5)]

        # 核心指标
        metrics = e.get('metrics', {})
        metric_items = []
        for k, v in metrics.items():
            # 判断正负色
            val_str = str(v).replace('%', '')
            try:
                val_num = float(val_str)
                if k in ('回撤', '压力回撤', '牛市回撤'):
                    cls = 'bad' if abs(val_num) > 15 else 'good'
                elif k in ('年化', '盈亏比', '胜率', '卡尔玛', '夏普', '压力年化', '牛市年化', '年交易'):
                    cls = 'good' if val_num > 0 else 'bad'
                else:
                    cls = ''
            except (ValueError, TypeError):
                cls = ''
            metric_items.append(f'<div class="metric"><span class="label">{k}</span><span class="value {cls}">{v}</span></div>')

        metrics_html = f'<div class="metric-grid">{"".join(metric_items[:6])}</div>'
        metrics_html2 = ''
        if len(metric_items) > 6:
            metrics_html2 = f'<div class="metric-grid" style="margin-top:6px;">{"".join(metric_items[6:])}</div>'

        # 标签
        tags_html = ''
        s_type = e.get('type', '')
        vol = e.get('vol_feature', '')
        compat = e.get('compat', '')
        if s_type:
            tags_html += f'<span class="tag type">{s_type}</span>'
        if vol:
            tags_html += f'<span class="tag vol">{vol}</span>'
        if compat:
            tags_html += f'<span class="tag compat">{compat}</span>'
        for t in e.get('tags', []):
            if t:
                tags_html += f'<span class="tag risk">{t}</span>'

        # 参数
        params = e.get('params', {})
        params_html = ''
        if params:
            param_strs = [f'<code>{k}={v}</code>' for k, v in params.items()]
            params_html = f'<div class="params">⚙️ {" ".join(param_strs)}</div>'

        # 描述
        desc_html = ''
        desc = e.get('desc', '')
        if desc:
            desc_html = f'<div style="font-size:11px;color:#888;margin-top:6px;">💡 {desc}</div>'

        cards.append(f'''<div class="card">
  <div class="card-header">
    <span class="rank {rank_cls}">{medal}</span>
    <span class="name">{name}</span>
    <span class="market {mkt_cls}">{market}</span>
    <span class="score">{score}分</span>
  </div>
  <div class="card-body">
    <div style="margin-bottom:6px;">{tags_html}</div>
    {metrics_html}
    {metrics_html2}
    {params_html}
    {desc_html}
  </div>
</div>''')

    return '\n'.join(cards)


def _build_rejected_section(entries: list, max_display: int = 10) -> str:
    """构建废弃策略区域HTML"""
    if not entries:
        return '<div style="padding:12px;color:#999;text-align:center;">废弃策略库为空</div>'

    # 按废弃时间降序排列（最近的在前），只展示最近max_display个
    sorted_entries = sorted(entries, key=lambda x: x.get('rejected_time', ''), reverse=True)
    display_entries = sorted_entries[:max_display]

    rows = []
    for i, e in enumerate(display_entries, 1):
        rows.append(f'''<tr>
  <td>{i}</td>
  <td>{e.get('name', '?')}</td>
  <td>{e.get('market', '?')}</td>
  <td>{e.get('score', '?')}</td>
  <td>{e.get('dd', '?')}</td>
  <td>{e.get('reason', '?')}</td>
</tr>''')

    total = len(entries)
    extra_note = f'<p style="color:#888;font-size:11px;margin-top:8px;">共{total}个废弃策略，仅展示最近{max_display}个</p>' if total > max_display else ''

    return f'''<div class="card" style="overflow-x:auto;">
<h3 style="color:#2c3e50;margin-bottom:8px;">🗑️ 废弃策略 ({total}个，展示最近{max_display}个)</h3>
<table class="rejected-table">
<thead><tr><th>#</th><th>策略</th><th>市场</th><th>得分</th><th>回撤</th><th>废弃原因</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
{extra_note}
</div>'''


def _build_all_strategies_section(entries: list) -> str:
    """构建全部策略回测数据区域HTML"""
    if not entries:
        return '<div style="padding:12px;color:#999;text-align:center;">无策略数据</div>'

    rows = []
    for i, e in enumerate(entries, 1):
        passed = e.get('passed', '?')
        name = e.get('name', '?')
        if len(name) > 16:
            name = name[:16] + '..'
        rows.append(f'''<tr>
  <td>{i}</td>
  <td>{name}</td>
  <td>{e.get('score', '?')}</td>
  <td>{e.get('annual', '?')}</td>
  <td>{e.get('dd', '?')}</td>
  <td>{e.get('pf', '?')}</td>
  <td>{e.get('wr', '?')}</td>
  <td>{passed}</td>
</tr>''')

    return f'''<div class="card" style="overflow-x:auto;">
<table class="all-table">
<thead><tr><th>#</th><th>策略</th><th>得分</th><th>年化</th><th>回撤</th><th>盈亏比</th><th>胜率</th><th>通过</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>'''


# ================================================================
# 主流程
# ================================================================
def run_full_scan(market: str = 'us', max_stocks: int = None):
    """执行完整的熊市策略搜索、验证、去重与归档流程"""

    scan_start = datetime.now()
    print("=" * 80)
    print(f"  🐻 熊市策略回测定时调度器 — 扫描开始")
    print(f"  ⏰ 时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🌍 市场: {market}")
    print(f"  📐 回测区间: 2022-01-01 ~ 2022-12-31 (2022年美股熊市)")
    print(f"  💪 压力测试: 2023-01-01 ~ 2023-12-31")
    print(f"  🐂 牛市辅助: 2023-10-01 ~ 2024-12-31")
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

    leaderboard = load_bear_leaderboard()
    rejected_list = load_bear_rejected_strategies()

    all_strategies_table = format_all_strategies_table(scored_all, market)
    top10_detail = _format_top10_detail(leaderboard)

    report = f"""
{'=' * 80}
  📋 熊市策略执行报告
{'=' * 80}

  本次扫描时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}
  扫描耗时: {duration:.0f}秒
  本次发现策略数量: {total_found}
  Pine Script一票否决数量: {pine_veto_count}
  通过去重后新策略数量: {len(new_strategies)}
  通过回测验证数量: {len(backtest_results)}
  评分入库数量: {len(scored_all)}
  ✅ 有评分策略数量（得分>0）: {len(scored_passed)}
  ❌ 零分策略数量（回撤>20%）: {len(scored_rejected)}
  🗑️ 废弃策略库累计: {len(rejected_list)}个

{all_strategies_table}

  🏆 熊市策略排行榜（前十高评分）:

{format_bear_leaderboard_table(leaderboard)}

{top10_detail}

  废弃策略库（共{len(rejected_list)}个，展示最近10个）:

{format_rejected_table(rejected_list, max_display=10)}

{'=' * 80}
"""

    print(report)

    # 保存报告
    report_path = os.path.join(PROJECT_DIR, 'reports',
                                f'bear_scan_{scan_start.strftime("%Y%m%d_%H%M%S")}.md')
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    # 注意：邮件由调用方统一发送（合并美股+港股为一份报告），此处不再单独发邮件

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
    """显示当前熊市策略状态"""
    bear_library_path = os.path.join(PROJECT_DIR, 'bear_strategy_library.json')
    library = load_strategy_library(bear_library_path)
    leaderboard = load_bear_leaderboard()
    rejected_list = load_bear_rejected_strategies()

    print(f"\n🐻 熊市策略库状态:")
    print(f"  策略总数: {len(library.get('strategies', []))}")
    print(f"  最后更新: {library.get('last_updated', 'N/A')}")
    print(f"  废弃策略库: {len(rejected_list)}个")

    print(f"\n🏆 熊市排行榜:")
    print(format_bear_leaderboard_table(leaderboard))


# ================================================================
# 命令行入口
# ================================================================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='熊市策略回测定时调度器')
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
        sys.exit(0 if result.get('backtest_passed', 0) > 0 else 1)
    elif args.action == 'status':
        show_status()
    elif args.action == 'report':
        show_status()
