#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震荡市策略回测定时调度器
========================
主入口: python range_scheduler.py [run|status|report]

震荡市特定:
  - 回测区间: 2021-01-01 ~ 2023-12-31
  - 压力测试: 2021-01-01 ~ 2022-12-31
  - 滑点0.1%（默认）/ 0.02%（限价单模式）
  - 最大回撤硬性条件≤15%
  - 评分权重: 年化15%/夏普25%/回撤25%/胜率20%/盈亏比15%
  - 入榜门槛: ≥75分
"""

import json
import os
import subprocess
import sys
import re
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
STRATEGY_ARENA_DIR = '/data/workspace/strategy_arena' if sys.platform != 'win32' else os.path.join(WORKSPACE_DIR, 'strategy_arena')
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, STRATEGY_ARENA_DIR)

from range_searcher import (
    get_search_queries, initial_filter_range, detect_stop_loss,
)
from range_ranker import (
    compute_total_score, classify_strategy,
    build_leaderboard_entry, update_leaderboard,
    load_leaderboard, save_leaderboard,
    load_rejected, save_rejected, add_rejected_entry,
    format_leaderboard_table, format_top5_detail,
    MIN_SCORE_THRESHOLD,
)
from pine_validator import check_pine_veto, score_portability
from strategy_dedup import (
    compute_strategy_fingerprint, fingerprint_short,
    load_strategy_library, save_strategy_library, add_strategy_to_library,
)
from hybrid_searcher import (
    hybrid_search, RANGE_PARAM_VARIANTS, RANGE_GITHUB_QUERIES,
    generate_param_variants, github_search,
)

# 配置
RUN_BACKTEST_SCRIPT = os.path.join(PROJECT_DIR, 'run_backtest_range.py')
STRATEGY_CODE_DIR = os.path.join(PROJECT_DIR, 'strategies')
RISK_FREE_RATE_DEFAULT = 0.055
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USER = '848786642@qq.com'
SMTP_PASSWORD = 'ljbtvacrctjobfed'
EMAIL_TO = '848786642@qq.com'

os.makedirs(STRATEGY_CODE_DIR, exist_ok=True)
os.makedirs(os.path.join(PROJECT_DIR, 'reports'), exist_ok=True)


# ================================================================
# 内置震荡市策略
# ================================================================
def _get_builtin_range_strategies() -> list:
    builtin = [
        {'name': '布林带均值回归策略',
         'description': '经典震荡市策略: 价格触及布林带下轨买入，回归中轨平仓。使用ATR移动止损保护。',
         'source': 'builtin', 'source_link': 'generated:range_bollinger',
         'is_classic': True, 'filename': 'bollinger_mean_reversion'},
        {'name': 'RSI区间交易策略',
         'description': 'RSI均值回归: RSI跌破30超卖区买入，升破70超买区卖出。配合ATR止损和时间止损。',
         'source': 'builtin', 'source_link': 'generated:range_rsi',
         'is_classic': True, 'filename': 'rsi_range_trading'},
        {'name': 'Keltner通道挤压突破策略',
         'description': '波动率收缩突破: Keltner通道收窄后突破时入场，捕捉低波动后的方向性突破。',
         'source': 'builtin', 'source_link': 'generated:range_keltner',
         'is_classic': True, 'filename': 'keltner_squeeze'},
        {'name': '网格交易策略(简化版)',
         'description': '网格交易: 在设定价格区间内按固定间隔高抛低吸，震荡市核心策略。',
         'source': 'builtin', 'source_link': 'generated:range_grid',
         'is_classic': True, 'filename': 'grid_trading'},
        {'name': '配对交易均值回归策略',
         'description': '统计套利: 根据价差Z-Score交易，做多弱势+做空强势，市场中性。',
         'source': 'builtin', 'source_link': 'generated:range_pairs',
         'is_classic': True, 'filename': 'pairs_mean_reversion'},
        {'name': '支撑阻力区间交易策略',
         'description': '区间交易: 识别关键支撑/阻力位，在支撑位买入、阻力位卖出。',
         'source': 'builtin', 'source_link': 'generated:range_sr',
         'is_classic': False, 'filename': 'support_resistance_range'},
        {'name': 'MACD柱状图反转策略',
         'description': '均值回归: MACD柱状图从负转正买入，从正转负卖出，捕捉短期动量反转。',
         'source': 'builtin', 'source_link': 'generated:range_macd',
         'is_classic': False, 'filename': 'macd_histogram_reversal'},
        {'name': 'Donchian通道回归策略',
         'description': '区间交易: 价格触及Donchian通道下轨买入，上轨卖出，适合宽幅震荡。',
         'source': 'builtin', 'source_link': 'generated:range_donchian',
         'is_classic': False, 'filename': 'donchian_reversion'},
        {'name': '波动率收缩-扩张轮动策略',
         'description': '波动率策略: 低波动期持有，高波动期减仓避险，ATR判断波动率状态。',
         'source': 'builtin', 'source_link': 'generated:range_vol',
         'is_classic': False, 'filename': 'volatility_regime_rotation'},
        {'name': '双均线乖离回归策略',
         'description': '均值回归: 价格偏离短期均线超过阈值时反向交易，乖离过大高抛低吸。',
         'source': 'builtin', 'source_link': 'generated:range_bias',
         'is_classic': False, 'filename': 'bias_mean_reversion'},
    ]

    strategies = []
    for s in builtin:
        code = _read_builtin_strategy(s['filename'])
        if code and len(code.strip()) > 20:
            s['code'] = code
            s['update_time'] = datetime.now().strftime('%Y-%m-%d')
            strategies.append(s)
    return strategies


def _read_builtin_strategy(name: str) -> str:
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
    混合搜索震荡市策略代码。
    方案A: GitHub API搜索（优先）→ 方案B: 参数变体（降级）
    确保每次扫描至少找到3个新策略。
    """
    print("\n" + "=" * 80)
    print("  🔍 步骤1: 搜索震荡市策略（混合搜索 A+B）")
    print("=" * 80)

    found = []
    builtin = _get_builtin_range_strategies()
    found.extend(builtin)
    print(f"  📦 内置震荡市策略: {len(builtin)}个")

    # ---- 混合搜索: 方案A(GitHub) + 方案B(参数变体) ----
    range_library_path = os.path.join(PROJECT_DIR, 'range_strategy_library.json')
    library = load_strategy_library(range_library_path)
    existing_fps = {(s.get('fingerprint', ''), s.get('market', ''))
                    for s in library.get('strategies', [])}
    # 也从废弃策略库收集指纹
    rejected_list = load_rejected()
    for r in rejected_list:
        existing_fps.add((r.get('fingerprint', ''), r.get('market', '')))

    # 执行混合搜索
    hybrid_results, search_stats = hybrid_search(
        market_type='range',
        builtin_strategies=builtin,
        variant_templates=RANGE_PARAM_VARIANTS,
        existing_fingerprints=existing_fps,
        min_new=3,
        github_queries=RANGE_GITHUB_QUERIES,
        strategy_code_dirs=[STRATEGY_CODE_DIR],
    )

    if hybrid_results:
        found.extend(hybrid_results)
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
        found.extend(cached)
        print(f"  💾 搜索缓存: {len(cached)}个策略")

    print(f"\n  📊 本次发现策略数量: {len(found)}")
    return found


def _load_search_cache() -> list:
    cache_path = os.path.join(PROJECT_DIR, 'range_search_cache.json')
    if not os.path.exists(cache_path):
        return []
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


# ================================================================
# 步骤2: Pine Script一票否决
# ================================================================
def check_pine_veto_batch(strategies: list) -> tuple:
    print("\n" + "=" * 80)
    print("  🔒 步骤2: Pine Script一票否决检测")
    print("=" * 80)
    vetoed_count = 0
    pine_transpile_failed = 0
    passed = []
    for strategy in strategies:
        code = strategy.get('code', '')
        source = strategy.get('source', '')
        if source.lower() in ('tradingview', 'pine_script', 'pine') or 'pine' in code[:200].lower():
            veto_result = check_pine_veto(code)
            if veto_result['vetoed']:
                vetoed_count += 1
                strategy['pine_script_rejected'] = True
                continue
            strategy['pine_script_rejected'] = False
            strategy['pine_transpile_failed'] = False
        else:
            strategy['pine_script_rejected'] = False
            strategy['pine_transpile_failed'] = False
        passed.append(strategy)
    print(f"\n  📊 Pine Script一票否决数量: {vetoed_count}")
    print(f"  📊 Pine Script转译失败数量: {pine_transpile_failed}")
    print(f"  📊 通过检测数量: {len(passed)}")
    return passed, vetoed_count, pine_transpile_failed


# ================================================================
# 步骤3: 去重与指纹
# ================================================================
def deduplicate_strategies(strategies: list, market: str = 'us') -> tuple:
    print("\n" + "=" * 80)
    print("  🔑 步骤3: 策略去重与指纹计算")
    print("=" * 80)
    range_library_path = os.path.join(PROJECT_DIR, 'range_strategy_library.json')
    library = load_strategy_library(range_library_path)
    existing_fps = {(s.get('fingerprint', ''), s.get('market', ''))
                    for s in library.get('strategies', [])}
    print(f"  📚 震荡市策略库现有: {len(existing_fps)}个策略")
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
            print(f"  🔄 重复: {strategy['name']} [{market.upper()}]")
        else:
            new_strategies.append(strategy)
            print(f"  ✅ 新策略: {strategy['name']} [{market.upper()}]")
    print(f"\n  📊 去重数量: {dedup_count}")
    print(f"  📊 通过去重后新策略数量: {len(new_strategies)}")
    return new_strategies, dedup_count


def _extract_params_from_code(code: str) -> dict:
    params = {}
    pattern = r'(?:ema_fast|ema_slow|atr_period|atr_mult|rsi_period|bb_period|bb_std|rsi_low|rsi_high|grid_size|grid_levels|multiplier|period|window|threshold|stop_loss|take_profit|channel_period|z_threshold|bias_threshold|vol_window)\s*=\s*(\d+\.?\d*)'
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
def run_backtest_batch(strategies: list, market: str = 'us', max_stocks: int = None) -> list:
    print("\n" + "=" * 80)
    print("  🚀 步骤4: 震荡市回测验证")
    print("=" * 80)
    backtest_results = []
    for strategy in strategies:
        name = strategy.get('name', 'Unknown')
        code = strategy.get('code', '')
        if not code or len(code.strip()) < 20:
            print(f"  ⏭️ 跳过: {name} (无有效代码)")
            continue
        stop_loss_info = detect_stop_loss(code)
        strategy['stop_loss_info'] = stop_loss_info
        slippage_mode = 'limit' if _detect_limit_orders(code) else 'default'
        strategy_file = _generate_strategy_file(strategy)
        if not strategy_file:
            continue
        print(f"\n  🔄 回测: {name} (滑点模式: {slippage_mode})")
        result = _execute_backtest(strategy_file, market, max_stocks, slippage_mode)
        if result:
            strategy['backtest_result'] = result
            strategy['market'] = market
            strategy['slippage_mode'] = slippage_mode
            backtest_results.append(strategy)
            main = result.get('main_period', {})
            if main:
                print(f"    ✅ 年化: {main.get('mean_annual_return', '?')}% | "
                      f"回撤: {main.get('mean_max_drawdown', '?')}% | "
                      f"夏普: {main.get('mean_sharpe', '?')}")
        else:
            print(f"    ❌ 回测失败: {name}")
    print(f"\n  📊 通过回测验证数量: {len(backtest_results)}")
    return backtest_results


def _detect_limit_orders(code: str) -> bool:
    limit_indicators = ['limit_order', 'Limit Order', 'maker', 'limit_price', '限价单', '挂单']
    return any(ind in code for ind in limit_indicators)


def _generate_strategy_file(strategy: dict) -> str:
    name = strategy.get('name', 'Unknown')
    code = strategy.get('code', '')
    params = strategy.get('strategy_params', {})
    safe_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in name)
    filepath = os.path.join(STRATEGY_CODE_DIR, f'{safe_name}.py')
    if 'generate_signals' in code:
        content = code
    else:
        content = f'# 策略: {name}\n# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np\nimport talib\n\n' \
                  f'STRATEGY_NAME = "{name}"\nSTRATEGY_TYPE = "{classify_strategy(name, code)}"\n' \
                  f'STRATEGY_PARAMS = {params}\n\n{code}'
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath
    except Exception as e:
        print(f"  ⚠️ 策略文件生成失败: {e}", file=sys.stderr)
        return ''


def _execute_backtest(strategy_file: str, market: str = 'us',
                      max_stocks: int = None, slippage_mode: str = 'default') -> dict:
    output_file = strategy_file.replace('.py', '_result.json')
    cmd = [sys.executable, RUN_BACKTEST_SCRIPT, '--strategy', strategy_file,
           '--market', market, '--risk-free-rate', str(RISK_FREE_RATE_DEFAULT),
           '--slippage-mode', slippage_mode, '--output', output_file]
    if max_stocks:
        cmd.extend(['--max-stocks', str(max_stocks)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=PROJECT_DIR)
        if result.returncode != 0:
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
# 步骤5: 评分与排行榜
# ================================================================
def score_and_rank(backtest_results: list) -> tuple:
    print("\n" + "=" * 80)
    print("  📊 步骤5: 评分与排行榜更新（震荡市版）")
    print("=" * 80)
    leaderboard = load_leaderboard()
    range_library_path = os.path.join(PROJECT_DIR, 'range_strategy_library.json')
    library = load_strategy_library(range_library_path)
    rejected_list = load_rejected()
    scored_all = []

    for strategy in backtest_results:
        bt_result = strategy.get('backtest_result', {})
        if not bt_result or not bt_result.get('main_period'):
            continue
        main = bt_result.get('main_period', {})
        portability = score_portability(strategy.get('code', ''), strategy.get('source', ''))
        stop_loss_info = strategy.get('stop_loss_info', {'has_stop_loss': False, 'warning': '⚠️'})

        annual_return = main.get('mean_annual_return', 0)
        sharpe = main.get('mean_sharpe', 0)
        max_drawdown = main.get('mean_max_drawdown', 0)
        win_rate = main.get('mean_win_rate', 0)
        profit_factor = main.get('mean_profit_factor', 0)
        avg_trades = main.get('mean_avg_trades_per_year', 0)
        max_single_loss = main.get('mean_max_single_loss_pct', 0)
        cross_robust = bt_result.get('cross_period_robust', False)
        stress = bt_result.get('stress_period', {})

        score_result = compute_total_score(
            annual_return=annual_return, sharpe=sharpe,
            max_drawdown=max_drawdown, profit_loss_ratio=profit_factor,
            win_rate=win_rate, cross_period_robust=cross_robust,
            survivorship_bias=True,
            has_stop_loss=stop_loss_info.get('has_stop_loss', False),
            max_single_loss_pct=max_single_loss,
        )

        strategy_info = {
            'name': strategy.get('name', 'Unknown'),
            'source_link': strategy.get('source_link', ''),
            'code': strategy.get('code', ''),
            'description': strategy.get('description', ''),
        }

        entry = build_leaderboard_entry(
            strategy_info=strategy_info,
            backtest_result={
                'annual_return': annual_return / 100,
                'sharpe': sharpe, 'max_drawdown': max_drawdown / 100,
                'win_rate': win_rate / 100, 'profit_loss_ratio': profit_factor,
                'avg_trades_per_stock': avg_trades,
                'max_single_loss_pct': max_single_loss,
                'cross_period_robust': cross_robust,
                'stress_test': {'annual_return': stress.get('mean_annual_return', 0) / 100,
                                'max_drawdown': stress.get('mean_max_drawdown', 0) / 100} if stress else None,
            },
            score_result=score_result, market=strategy.get('market', 'us'),
            fingerprint=strategy.get('fingerprint', ''),
            portability_score=portability,
            has_stop_loss=stop_loss_info.get('has_stop_loss', False),
            survivorship_bias=True,
            pine_transpile_failed=strategy.get('pine_transpile_failed', False),
            is_classic=strategy.get('is_classic', False),
            slippage_mode=strategy.get('slippage_mode', 'default_0.1%'),
        )

        if entry:
            scored_all.append(entry)
            leaderboard = update_leaderboard(entry, leaderboard)
            library = add_strategy_to_library(entry, library)
            tag = '✅' if not score_result['max_drawdown_hard_fail'] else '❌'
            print(f"  {tag} {entry['name']}: 得分={score_result['total_score']}, "
                  f"年化={annual_return}%, 回撤={max_drawdown}%")
        else:
            print(f"  ❌ 淘汰: {strategy.get('name')} (回撤≥15%)")
            rejected_list = add_rejected_entry(
                {'name': strategy.get('name'), 'fingerprint': strategy.get('fingerprint', ''),
                 'fingerprint_full': strategy.get('fingerprint', ''),
                 'score': score_result['total_score'],
                 'annual_return': annual_return / 100, 'max_drawdown': max_drawdown / 100},
                f'最大回撤{abs(max_drawdown):.1f}%≥15%', strategy.get('market', 'us'), rejected_list)

        if entry and score_result['total_score'] < MIN_SCORE_THRESHOLD:
            # 记录低分策略但不再自动加入废弃库（排行榜已无门槛，前五即入榜）
            print(f"  ⚠️ 低分: {strategy.get('name')} 得分{score_result['total_score']}<75")

    save_leaderboard(leaderboard)
    save_strategy_library(library, range_library_path)
    save_rejected(rejected_list)
    return scored_all, leaderboard, rejected_list


# ================================================================
# 报告格式化
# ================================================================
def format_all_strategies_table(scored: list, market: str = 'us') -> str:
    if not scored:
        return "本次无策略完成回测评分。"
    lines = [
        f"\n### 📊 全部策略回测数据（震荡市·{market.upper()}）\n",
        "| # | 策略名称 | 类型 | 指纹 | 得分 | 年化 | 夏普 | 回撤 | 盈亏比 | 胜率 | 止损 | 通过 |",
        "|---|---------|------|------|------|------|------|------|--------|------|------|------|",
    ]
    for i, e in enumerate(scored, 1):
        name = e['name'][:22]
        fp = e['fingerprint']
        sc = e['score']
        ar = e.get('annual_return', 0) * 100
        sh = e.get('sharpe', 0)
        dd = e.get('max_drawdown', 0) * 100
        pf = e.get('profit_loss_ratio', 0)
        wr = e.get('win_rate', 0) * 100
        stop = '✅' if e.get('has_stop_loss') else '⚠️'
        passed = sc >= MIN_SCORE_THRESHOLD and not e.get('score_breakdown', {}).get('max_drawdown_hard_fail', False)
        lines.append(f"| {i} | {name} | {e.get('type', '其他')} | {fp} | {sc} | "
                      f"{ar:.1f}% | {sh:.2f} | {dd:.1f}% | {pf:.2f} | {wr:.1f}% | {stop} | {'✅' if passed else '❌'} |")
    return '\n'.join(lines)


def format_rejected_table(rejected_list: list, max_display: int = 10) -> str:
    if not rejected_list:
        return "  （废弃策略库为空）"
    lines = [
        "| # | 策略名称 | 市场 | 指纹 | 得分 | 年化 | 回撤 | 废弃原因 |",
        "|---|---------|------|------|------|------|------|---------|",
    ]
    sorted_list = sorted(rejected_list,
                         key=lambda x: x.get('rejected_time', ''), reverse=True)
    for i, e in enumerate(sorted_list[:max_display], 1):
        lines.append(f"| {i} | {e.get('name', '?')[:22]} | {e.get('market', '?').upper()} | "
                      f"{e.get('fingerprint', '')[:8]} | {e.get('score', 0)} | "
                      f"{e.get('annual_return', 0)*100:.1f}% | {e.get('max_drawdown', 0)*100:.1f}% | "
                      f"{e.get('rejection_reason', '得分<75')} |")
    return '\n'.join(lines)


# ================================================================
# 结构化JSON输出
# ================================================================
def generate_structured_json(scan_time: str, strategies: list) -> str:
    output = {'scan_time': scan_time, 'strategies': []}
    for e in strategies:
        output['strategies'].append({
            'name': e.get('name', 'Unknown'), 'source_url': e.get('source_url', ''),
            'fingerprint': e.get('fingerprint', ''), 'type': e.get('type', '其他'),
            'score': e.get('score', 0), 'annual_return': e.get('annual_return', 0),
            'sharpe': e.get('sharpe', 0), 'max_drawdown': e.get('max_drawdown', 0),
            'win_rate': e.get('win_rate', 0), 'profit_loss_ratio': e.get('profit_loss_ratio', 0),
            'avg_trades_per_stock': e.get('avg_trades_per_stock', 0),
            'cross_cycle_robust': e.get('cross_period_robust', False),
            'survivorship_bias': e.get('survivorship_bias', True),
            'has_stop_loss': e.get('has_stop_loss', False),
            'pine_transpile_failed': e.get('pine_transpile_failed', False),
            'slippage_mode': e.get('slippage_mode', 'default_0.1%'),
        })
    return json.dumps(output, ensure_ascii=False, indent=2)


# ================================================================
# 邮件发送
# ================================================================
def send_email_report(report_text: str, scan_time: str):
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        html = _markdown_to_html(report_text)
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"【震荡市策略回测报告】{scan_time}"
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        msg.attach(MIMEText(html, 'html', 'utf-8'))
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

    # 提取排行榜数据
    leaderboard_entries = _parse_range_leaderboard_from_md(md_text)
    # 提取废弃策略数据
    rejected_entries = _parse_range_rejected_from_md(md_text)
    # 提取扫描统计
    scan_stats = _parse_range_scan_stats_from_md(md_text)
    # 提取全部策略数据
    all_strategy_entries = _parse_range_all_strategies_from_md(md_text)

    cards_html = ''
    if leaderboard_entries:
        cards_html = _build_range_leaderboard_cards(leaderboard_entries)

    rejected_html = ''
    if rejected_entries:
        rejected_html = _build_range_rejected_section(rejected_entries)

    all_strategies_html = ''
    if all_strategy_entries:
        all_strategies_html = _build_range_all_strategies_section(all_strategy_entries)

    stats_html = _build_range_stats_section(scan_stats)

    email_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<style>
  body {{ margin:0; padding:0; background:#f0f2f5; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif; -webkit-text-size-adjust:100%; }}
  .container {{ max-width:600px; margin:0 auto; padding:12px; }}
  .header {{ background:linear-gradient(135deg,#667eea 0%,#764ba2 100%); padding:28px 24px; border-radius:12px 12px 0 0; text-align:center; }}
  .header h1 {{ color:#fff; margin:0; font-size:20px; letter-spacing:1px; }}
  .header p {{ color:rgba(255,255,255,0.8); margin:8px 0 0; font-size:12px; }}
  .stats {{ background:#fff; padding:16px 20px; border-bottom:1px solid #eee; }}
  .stat-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
  .stat-item {{ padding:8px 10px; background:#f8f9fa; border-radius:8px; }}
  .stat-label {{ font-size:11px; color:#999; display:block; }}
  .stat-value {{ font-size:16px; font-weight:700; color:#2c3e50; }}
  .stat-value.red {{ color:#e74c3c; }}
  .stat-value.green {{ color:#27ae60; }}
  .section-title {{ font-size:16px; font-weight:700; color:#2c3e50; margin:20px 0 12px; padding-left:4px; border-left:4px solid #764ba2; }}
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
  .card-header .score {{ font-size:20px; font-weight:800; color:#764ba2; }}
  .card-body {{ padding:0 16px 14px; }}
  .metric-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; }}
  .metric {{ text-align:center; padding:6px 4px; background:#f8f9fa; border-radius:6px; }}
  .metric .label {{ font-size:10px; color:#999; display:block; }}
  .metric .value {{ font-size:13px; font-weight:700; color:#2c3e50; }}
  .metric .value.good {{ color:#27ae60; }}
  .metric .value.bad {{ color:#e74c3c; }}
  .tag {{ display:inline-block; font-size:10px; padding:2px 6px; border-radius:8px; margin:1px 2px; }}
  .tag.compat {{ background:#d4edda; color:#155724; }}
  .tag.risk {{ background:#f8d7da; color:#721c24; }}
  .tag.type {{ background:#e2e3f1; color:#4a4a8a; }}
  .tag.stop {{ background:#fff3cd; color:#856404; }}
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
    <h1>📊 震荡市策略回测定时扫描报告</h1>
    <p>Strategy Arena Range · Oscillating Market Backtest</p>
  </div>
  {stats_html}
  <div class="section-title">🏆 历史前五排行榜</div>
  {cards_html}
  <div class="section-title">📊 全部策略回测数据</div>
  {all_strategies_html}
  <div class="section-title">🗑️ 废弃策略库（最近10个）</div>
  {rejected_html}
  <div class="footer">Blakever Quant System · Auto-generated Report</div>
</div>
</body></html>"""
    return email_html


def _parse_range_scan_stats_from_md(md_text: str) -> dict:
    """从震荡市Markdown报告中解析扫描统计"""
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
        elif '废弃策略库累计:' in line:
            stats['rejected_total'] = line.replace('个', '').split(':', 1)[1].strip()
    return stats


def _parse_range_leaderboard_from_md(md_text: str) -> list:
    """从震荡市Markdown报告中解析排行榜数据"""
    entries = []
    lines = md_text.split('\n')
    current = None
    in_top5 = False

    for line in lines:
        if '第1名' in line or '第2名' in line or '第3名' in line or '第4名' in line or '第5名' in line:
            in_top5 = True
            if current:
                entries.append(current)
            rank_match = __import__('re').search(r'第(\d)名', line)
            current = {
                'rank': int(rank_match.group(1)) if rank_match else 0,
                'name': '',
                'market': '?',
                'score': '0',
                'metrics': {},
                'tags': [],
            }
        elif in_top5 and current:
            stripped = line.strip()
            if '━' in stripped and not stripped.replace('━', '').strip():
                continue
            if ':' in stripped or '：' in stripped:
                sep = '：' if '：' in stripped else ':'
                key, _, val = stripped.partition(sep)
                key = key.strip()
                val = val.strip()
                if key == '策略名称':
                    current['name'] = val
                elif key == '策略类型':
                    current['type'] = val
                elif key == '市场':
                    current['market'] = val.upper()
                elif key == '综合得分':
                    current['score'] = val.replace('分', '')
                elif key == '年化收益':
                    current['metrics']['年化'] = val
                elif key == '夏普比率':
                    current['metrics']['夏普'] = val
                elif key == '最大回撤':
                    current['metrics']['回撤'] = val
                elif key == '盈亏比':
                    current['metrics']['盈亏比'] = val
                elif key == '胜率':
                    current['metrics']['胜率'] = val
                elif key == '单标年交易次数':
                    current['metrics']['年交易'] = val
                elif key == '单笔最大亏损':
                    current['metrics']['单笔亏损'] = val
                elif key == '压力测试':
                    current['metrics']['压力测试'] = val
                elif key == '跨周期鲁棒':
                    current['tags'].append(f"鲁棒:{val}")
                elif key == '幸存者偏差':
                    current['tags'].append(f"偏差:{val}")
                elif key == '止损保护':
                    current['tags'].append(f"止损:{val}")

    if current:
        entries.append(current)
    return entries


def _parse_range_rejected_from_md(md_text: str) -> list:
    """从震荡市Markdown报告中解析废弃策略表格数据"""
    entries = []
    lines = md_text.split('\n')
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and '策略名称' in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith('|'):
            if all(c in '|-–— ' for c in stripped):
                continue
            cells = [c.strip() for c in stripped.split('|') if c.strip()]
            if len(cells) >= 7:
                entries.append({
                    'name': cells[1] if len(cells) > 1 else '?',
                    'market': cells[2] if len(cells) > 2 else '?',
                    'score': cells[4] if len(cells) > 4 else '?',
                    'annual': cells[5] if len(cells) > 5 else '?',
                    'dd': cells[6] if len(cells) > 6 else '?',
                    'reason': cells[7] if len(cells) > 7 else '?',
                })
        elif in_table and not stripped.startswith('|'):
            in_table = False

    return entries[:10]


def _parse_range_all_strategies_from_md(md_text: str) -> list:
    """从震荡市Markdown报告中解析全部策略表格数据"""
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
                    'score': cells[4] if len(cells) > 4 else '?',
                    'annual': cells[5] if len(cells) > 5 else '?',
                    'sharpe': cells[6] if len(cells) > 6 else '?',
                    'dd': cells[7] if len(cells) > 7 else '?',
                    'pf': cells[8] if len(cells) > 8 else '?',
                    'wr': cells[9] if len(cells) > 9 else '?',
                    'passed': cells[11] if len(cells) > 11 else '?',
                })
        elif in_table and not stripped.startswith('|'):
            in_table = False

    return entries


def _build_range_stats_section(stats: dict) -> str:
    """构建震荡市扫描统计区域HTML"""
    if not stats:
        return ''
    items = []
    key_map = [
        ('total_found', '发现策略', ''),
        ('pine_veto', 'Pine否决', 'red'),
        ('new_dedup', '去重新策略', 'green'),
        ('backtest_passed', '回测通过', 'green'),
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


def _build_range_leaderboard_cards(entries: list) -> str:
    """构建震荡市排行榜卡片HTML"""
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

        metrics = e.get('metrics', {})
        metric_items = []
        for k, v in metrics.items():
            val_str = str(v).replace('%', '')
            try:
                val_num = float(val_str.replace('%', '').split(',')[0])
                if k in ('回撤', '单笔亏损'):
                    cls = 'bad' if abs(val_num) > 10 else 'good'
                elif k in ('年化', '盈亏比', '胜率', '夏普', '年交易'):
                    cls = 'good' if val_num > 0 else 'bad'
                else:
                    cls = ''
            except (ValueError, TypeError):
                cls = ''
            metric_items.append(f'<div class="metric"><span class="label">{k}</span><span class="value {cls}">{v}</span></div>')

        # 3列一排
        metrics_html = f'<div class="metric-grid">{"".join(metric_items[:3])}</div>'
        if len(metric_items) > 3:
            metrics_html += f'<div class="metric-grid" style="margin-top:6px;">{"".join(metric_items[3:6])}</div>'
        if len(metric_items) > 6:
            metrics_html += f'<div class="metric-grid" style="margin-top:6px;">{"".join(metric_items[6:])}</div>'

        # 标签
        tags_html = ''
        s_type = e.get('type', '')
        if s_type:
            tags_html += f'<span class="tag type">{s_type}</span>'
        for t in e.get('tags', []):
            if '⚠️' in t or '❌' in t:
                tags_html += f'<span class="tag risk">{t}</span>'
            else:
                tags_html += f'<span class="tag compat">{t}</span>'

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
  </div>
</div>''')

    return '\n'.join(cards)


def _build_range_rejected_section(entries: list, max_display: int = 10) -> str:
    """构建震荡市废弃策略区域HTML"""
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


def _build_range_all_strategies_section(entries: list) -> str:
    """构建震荡市全部策略回测数据区域HTML"""
    if not entries:
        return '<div style="padding:12px;color:#999;text-align:center;">无策略数据</div>'

    rows = []
    for i, e in enumerate(entries, 1):
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
  <td>{e.get('passed', '?')}</td>
</tr>''')

    return f'''<div class="card" style="overflow-x:auto;">
<table class="all-table">
<thead><tr><th>#</th><th>策略</th><th>得分</th><th>年化</th><th>回撤</th><th>盈亏比</th><th>胜率</th><th>通过</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>'''
    return email_html


# ================================================================
# 主流程
# ================================================================
def run_full_scan(market: str = 'us', max_stocks: int = None, send_email: bool = True):
    scan_start = datetime.now()
    print("=" * 80)
    print(f"  📊 震荡市策略回测定时调度器 — 扫描开始")
    print(f"  ⏰ 时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🌍 市场: {market}")
    print(f"  📐 回测区间: 2021-01-01 ~ 2023-12-31")
    print(f"  📏 排行榜: 保留前五高评分策略")
    print("=" * 80)

    strategies = search_strategies()
    total_found = len(strategies)

    strategies_after_veto, pine_veto_count, pine_transpile_fail = check_pine_veto_batch(strategies)
    new_strategies, dedup_count = deduplicate_strategies(strategies_after_veto, market=market)
    backtest_results = run_backtest_batch(new_strategies, market=market, max_stocks=max_stocks)
    scored_all, leaderboard, rejected_list = score_and_rank(backtest_results)

    scan_end = datetime.now()
    duration = (scan_end - scan_start).total_seconds()
    scan_time_str = scan_start.strftime('%Y-%m-%d %H:%M:%S')

    all_table = format_all_strategies_table(scored_all, market)
    top5 = format_top5_detail(leaderboard)
    lb_table = format_leaderboard_table(leaderboard)

    report = f"""
{'=' * 80}
  📋 震荡市策略执行报告
{'=' * 80}

  本次扫描时间: {scan_time_str}
  扫描耗时: {duration:.0f}秒
  本次发现策略数量: {total_found}
  Pine Script一票否决数量: {pine_veto_count}
  Pine Script转译失败数量: {pine_transpile_fail}
  通过去重后新策略数量: {len(new_strategies)}
  通过回测验证数量: {len(backtest_results)}
  🗑️ 废弃策略库累计: {len(rejected_list)}个

  当前本地策略排行榜:

{lb_table}

{all_table}

  🏆 震荡市策略排行榜（详细参数）:

{top5}

  废弃策略库（共{len(rejected_list)}个，展示最近10个）:

{format_rejected_table(rejected_list, max_display=10)}

{'=' * 80}
"""
    print(report)

    report_path = os.path.join(PROJECT_DIR, 'reports',
                                f'range_scan_{scan_start.strftime("%Y%m%d_%H%M%S")}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    structured_json = generate_structured_json(scan_time_str, scored_all)
    json_path = os.path.join(PROJECT_DIR, 'reports',
                              f'range_scan_{scan_start.strftime("%Y%m%d_%H%M%S")}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(structured_json)

    print(f"\n📁 报告: {report_path}")
    print(f"📁 JSON: {json_path}")
    print(f"\n```json\n{structured_json}\n```")

    # 注意：邮件由定时任务Agent统一合并发送（美股+港股为一份），此处不再自动发邮件

    return {
        'scan_time': scan_time_str, 'duration_seconds': duration,
        'total_found': total_found, 'pine_veto_count': pine_veto_count,
        'pine_transpile_failed': pine_transpile_fail,
        'new_after_dedup': len(new_strategies),
        'backtest_passed': len(backtest_results),
        'scored_count': len(scored_all),
        'total_rejected_in_db': len(rejected_list),
        'leaderboard': leaderboard, 'scored_all': scored_all,
        'report_text': report,
    }


def show_status():
    range_library_path = os.path.join(PROJECT_DIR, 'range_strategy_library.json')
    library = load_strategy_library(range_library_path)
    leaderboard = load_leaderboard()
    rejected_list = load_rejected()
    print(f"\n📊 震荡市策略库状态:")
    print(f"  策略总数: {len(library.get('strategies', []))}")
    print(f"  废弃策略库: {len(rejected_list)}个")
    print(f"  排行榜规则: 保留前五高评分策略")
    print(f"\n🏆 震荡市排行榜:")
    print(format_leaderboard_table(leaderboard))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='震荡市策略回测定时调度器')
    parser.add_argument('action', choices=['run', 'status', 'report'],
                        default='status', nargs='?')
    parser.add_argument('--market', default='us', choices=['us', 'hk', 'all'])
    parser.add_argument('--max-stocks', type=int, default=None)
    args = parser.parse_args()

    if args.action == 'run':
        if args.market == 'all':
            run_full_scan(market='us', max_stocks=args.max_stocks)
            run_full_scan(market='hk', max_stocks=args.max_stocks)
        else:
            run_full_scan(market=args.market, max_stocks=args.max_stocks)
    else:
        show_status()
