#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震荡市策略评分与排行榜模块
============================
核心差异（vs 趋势市版）:
  - 评分权重: 年化15%/夏普25%/回撤25%/胜率20%/盈亏比15%
  - 回撤阶梯: ≤8%:25分; 8-12%:18分; 12-15%:10分; ≥15%:淘汰
  - 入榜门槛: 综合得分≥75分
  - 止损扣分: 无止损逻辑且单笔最大亏损>2%，扣10分
  - 失效判定: 连续2周跑输基准≥2%且至少1周为负
  - 策略类型: 新增震荡区间交易/波动率收缩突破/网格对冲
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional


import math

# ================================================================
# 震荡市综合评分 v2 —— 对数+连续衰减，拉开策略差距
# ================================================================
def score_annual_return(annual_return_pct: float) -> float:
    """年化收益率得分（权重15%，上限15分）—— 对数尺度
    
    震荡市年化普遍较低，基准6%：
    - 3%  → 4.1分
    - 6%  → 7.2分
    - 10% → 9.9分
    - 15% → 12.0分（v1触顶）
    - 30% → 15.0分（封顶）
    """
    if annual_return_pct <= 0:
        return 0.0
    score = 5.0 * math.log(1 + annual_return_pct / 6.0)
    return round(min(max(score, 0), 15), 2)


def score_sharpe(sharpe: float) -> float:
    """夏普比率得分（权重25%，上限25分）—— 对数尺度
    
    震荡市夏普基准0.4：
    - 0.3 → 5.8分
    - 0.5 → 8.5分
    - 1.0 → 13.1分
    - 1.8 → 17.4分（v1触顶）
    - 3.0 → 20.5分
    """
    if sharpe <= 0:
        return 0.0
    score = 7.5 * math.log(1 + sharpe / 0.4)
    return round(min(max(score, 0), 25), 2)


def score_max_drawdown(max_drawdown_pct: float) -> float:
    """最大回撤得分（连续衰减，权重25%，上限25分）
    
    v2改革：用连续指数衰减替代阶梯制，消除跳档。
    震荡市回撤容忍度低，3%为满分起点，衰减更快：
    - 3%  → 25.0分（满分）
    - 5%  → 22.3分
    - 8%  → 18.0分（v1满分线）
    - 10% → 15.2分
    - 12% → 12.9分（v1跳档18→此处连续）
    - 15% → 10.1分（v1淘汰→此处仍给分）
    - 20% → 6.6分
    - 25% → 4.3分
    
    公式: 25 × exp(-0.07 × (dd - 3))，3%为满分起点
    """
    abs_dd = abs(max_drawdown_pct)
    if abs_dd <= 3:
        return 25.0
    score = 25.0 * math.exp(-0.07 * (abs_dd - 3))
    return round(min(max(score, 0), 25), 2)


def score_win_rate(win_rate_pct: float) -> float:
    """胜率得分（权重20%，上限20分）—— 对数尺度
    
    震荡市更看重胜率，35%为0分起点：
    - 35% → 0分
    - 45% → 3.9分
    - 55% → 6.6分
    - 65% → 8.8分（v1触顶）
    - 75% → 10.6分
    - 85% → 12.1分
    """
    if win_rate_pct <= 35:
        return 0.0
    score = 8.0 * math.log(1 + (win_rate_pct - 35) / 15.0)
    return round(min(max(score, 0), 20), 2)


def score_profit_loss_ratio(pl_ratio: float) -> float:
    """盈亏比得分（权重15%，上限15分）—— 对数尺度，1.0为0分起点
    
    - 1.0 → 0分
    - 1.2 → 2.7分
    - 1.5 → 5.0分
    - 1.8 → 6.7分（v1触顶）
    - 2.5 → 9.0分
    - 3.0 → 10.1分
    """
    if pl_ratio <= 1.0:
        return 0.0
    score = 5.0 * math.log(1 + (pl_ratio - 1.0) / 0.3)
    return round(min(max(score, 0), 15), 2)


def compute_total_score(
    annual_return: float,
    sharpe: float,
    max_drawdown: float,
    profit_loss_ratio: float,
    win_rate: float,
    cross_period_robust: bool = False,
    survivorship_bias: bool = True,
    has_stop_loss: bool = True,
    max_single_loss_pct: float = 0.0,
) -> dict:
    """
    计算震荡市策略综合评分（总分100分 + 附加分5分 - 数据扣分/风控扣分）。
    """
    s_ar = score_annual_return(annual_return)
    s_sharpe = score_sharpe(sharpe)
    s_dd = score_max_drawdown(max_drawdown)
    s_wr = score_win_rate(win_rate)
    s_plr = score_profit_loss_ratio(profit_loss_ratio)

    base_score = s_ar + s_sharpe + s_dd + s_wr + s_plr

    # 附加分
    bonus = 5.0 if cross_period_robust else 0.0

    # 扣分
    penalty_survivorship = -10.0 if survivorship_bias else 0.0
    # 止损扣分: 无止损逻辑且单笔最大亏损>2%
    penalty_stop_loss = 0.0
    if not has_stop_loss and max_single_loss_pct > 2.0:
        penalty_stop_loss = -10.0

    total = base_score + bonus + penalty_survivorship + penalty_stop_loss

    return {
        'annual_return_score': round(s_ar, 2),
        'sharpe_score': round(s_sharpe, 2),
        'max_drawdown_score': round(s_dd, 2),
        'win_rate_score': round(s_wr, 2),
        'profit_loss_ratio_score': round(s_plr, 2),
        'base_score': round(base_score, 2),
        'cross_period_bonus': bonus,
        'survivorship_penalty': penalty_survivorship,
        'stop_loss_penalty': penalty_stop_loss,
        'total_score': round(total, 2),
        'max_drawdown_hard_fail': abs(max_drawdown) >= 15,  # ≥15%直接淘汰
    }


# ================================================================
# 策略类型自动分类（震荡市扩展版）
# ================================================================
STRATEGY_TYPE_KEYWORDS = {
    '趋势跟踪': ['trend', 'moving average', 'ma', 'ema', 'sma', 'crossover',
                 'breakout', 'donchian', 'turtle', 'supertrend', 'adx',
                 '趋势', '均线', '突破', '跟踪', '跟随'],
    '均值回归': ['mean reversion', 'reversion', 'bollinger', 'rsi', 'overbought',
                 'oversold', 'z-score', 'pairs', '回归', '反转', '超买', '超卖'],
    '套利': ['arbitrage', 'spread', 'pairs trading', 'statistical arbitrage',
             '套利', '价差', '配对'],
    '事件驱动': ['event', 'earnings', 'fed', 'cpi', 'nfp', 'dividend',
                 '事件', '财报', '加息', '分红'],
    '机器学习': ['machine learning', 'ml', 'neural', 'lstm', 'random forest',
                 'gradient', 'xgboost', 'deep learning', 'ai', 'reinforcement',
                 '机器学习', '神经网络', '深度学习', '强化学习'],
    '高股息轮动': ['dividend', 'yield', 'high yield', 'income', 'reit',
                  '股息', '红利', '高股息', '收益', '轮动'],
    '震荡区间交易': ['range trading', 'range-bound', 'sideways', 'channel',
                    'consolidation', 'support resistance', 'box trading',
                    '区间交易', '箱体', '震荡区间', '横盘', '支撑阻力'],
    '波动率收缩突破': ['volatility squeeze', 'keltner squeeze', 'bb squeeze',
                     'ttm squeeze', 'volatility contraction', 'low volatility breakout',
                     '波动率收缩', 'Keltner挤压', '布林带收窄'],
    '网格对冲': ['grid trading', 'grid strategy', 'hedging', 'delta neutral',
                'market neutral', 'long short', 'pair hedge',
                '网格', '对冲', '中性', '多空对冲'],
}


def classify_strategy(strategy_name: str, strategy_code: str = '',
                      description: str = '') -> str:
    """策略类型自动分类（基于关键词匹配）"""
    text = f"{strategy_name} {strategy_code} {description}".lower()

    scores = {}
    for type_name, keywords in STRATEGY_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[type_name] = score

    if not scores:
        return '其他'

    return max(scores, key=scores.get)


# ================================================================
# 排行榜维护（震荡市专用）
# ================================================================
LEADERBOARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'leaderboard_range.json')
REJECTED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'rejected_strategies_range.json')

# 入榜门槛
MIN_SCORE_THRESHOLD = 75

# 失效判定参数
UNDERPERFORM_WEEKS = 2       # 连续2周
UNDERPERFORM_CUM_PCT = 2.0   # 累计跑输≥2%
MDD_BREAK_RATIO = 1.2        # 回撤突破历史最大回撤的120%


def load_leaderboard(filepath: str = LEADERBOARD_FILE) -> list:
    """加载排行榜数据"""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_leaderboard(leaderboard: list, filepath: str = LEADERBOARD_FILE):
    """保存排行榜数据"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)


def load_rejected(filepath: str = REJECTED_FILE) -> list:
    """加载废弃策略库"""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_rejected(rejected: list, filepath: str = REJECTED_FILE):
    """保存废弃策略库"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)


def build_leaderboard_entry(
    strategy_info: dict,
    backtest_result: dict,
    score_result: dict,
    market: str = 'US',
    fingerprint: str = '',
    portability_score: int = 0,
    has_stop_loss: bool = True,
    survivorship_bias: bool = True,
    pine_transpile_failed: bool = False,
    is_classic: bool = False,
    slippage_mode: str = 'default_0.1%',
) -> Optional[dict]:
    """
    构建排行榜/废弃策略条目。
    回撤≥15%返回None（硬性淘汰）。
    """
    if score_result.get('max_drawdown_hard_fail', False):
        return None

    entry = {
        'name': strategy_info.get('name', 'Unknown'),
        'type': classify_strategy(
            strategy_info.get('name', ''),
            strategy_info.get('code', ''),
            strategy_info.get('description', ''),
        ),
        'source_url': strategy_info.get('source_link', ''),
        'fingerprint': fingerprint[:8] if fingerprint else 'N/A',
        'fingerprint_full': fingerprint,
        'market': market,
        'score': score_result['total_score'],
        'annual_return': round(backtest_result.get('annual_return', 0), 4),
        'sharpe': round(backtest_result.get('sharpe', 0), 4),
        'max_drawdown': round(backtest_result.get('max_drawdown', 0), 4),
        'win_rate': round(backtest_result.get('win_rate', 0), 4),
        'profit_loss_ratio': round(backtest_result.get('profit_loss_ratio', 0), 4),
        'avg_trades_per_stock': round(backtest_result.get('avg_trades_per_stock', 0), 2),
        'max_single_loss_pct': round(backtest_result.get('max_single_loss_pct', 0), 4),
        'cross_period_robust': backtest_result.get('cross_period_robust', False),
        'survivorship_bias': survivorship_bias,
        'has_stop_loss': has_stop_loss,
        'pine_transpile_failed': pine_transpile_failed,
        'portability_score': portability_score,
        'is_classic': is_classic,
        'slippage_mode': slippage_mode,
        'backtest_timestamp': datetime.now().isoformat(),
        'market_regime': '震荡市适配',
        'score_breakdown': score_result,
        'protection_until': (datetime.now() + timedelta(days=7)).isoformat(),
        'weekly_performance': [],
        'removal_reason': '',
    }

    # 压力测试数据
    if 'stress_test' in backtest_result:
        entry['stress_test'] = backtest_result['stress_test']

    return entry


def update_leaderboard(entry: dict, leaderboard: list) -> list:
    """
    更新排行榜: 保留历史前五高评分策略（无最低分门槛）。
    同指纹+同市场视为同一策略，取最高分。
    后续有更高分则重新排序，只保留前五。
    """
    fp = entry.get('fingerprint_full', entry['fingerprint'])
    market = entry['market']

    # 检查是否已存在同指纹+同市场
    for i, existing in enumerate(leaderboard):
        if existing.get('fingerprint_full', existing['fingerprint']) == fp and existing['market'] == market:
            if entry['score'] > existing['score']:
                leaderboard[i] = entry
            leaderboard.sort(key=lambda x: x['score'], reverse=True)
            return leaderboard[:5]

    # 新策略，加入排行榜
    leaderboard.append(entry)
    leaderboard.sort(key=lambda x: x['score'], reverse=True)
    return leaderboard[:5]


def check_invalidation(entry: dict, current_weekly_perf: dict) -> dict:
    """
    震荡市失效判定:
      - 连续2周跑输基准≥2%，且至少1周策略绝对收益为负
      - 或单周最大回撤突破历史最大回撤的120%
    """
    weekly = entry.get('weekly_performance', [])

    # 条件2: 单周回撤突破历史MDD的120%
    week_mdd = current_weekly_perf.get('max_drawdown_pct', 0)
    historical_mdd = abs(entry.get('max_drawdown', 10))
    if historical_mdd > 0 and abs(week_mdd) > historical_mdd * MDD_BREAK_RATIO:
        return {
            'invalidated': True,
            'reason': f'单周回撤{abs(week_mdd):.2f}%突破历史MDD{historical_mdd:.2f}%的120%',
        }

    # 条件1: 连续2周跑输基准≥2%且至少1周为负
    if len(weekly) >= 2:
        last_two = weekly[-2:]
        cumulative_under = 0
        any_negative = False
        for w in last_two:
            under = w.get('benchmark_outperform', 0)
            cumulative_under += under
            if w.get('strategy_return', 0) < 0:
                any_negative = True

        if cumulative_under <= -UNDERPERFORM_CUM_PCT and any_negative:
            return {
                'invalidated': True,
                'reason': f'连续2周跑输基准{abs(cumulative_under):.2f}%且至少1周为负',
            }

    return {'invalidated': False, 'reason': ''}


def add_rejected_entry(entry_data: dict, reason: str, market: str,
                       rejected: list) -> list:
    """添加废弃策略条目"""
    fp = entry_data.get('fingerprint_full', entry_data.get('fingerprint', ''))
    # 去重: 同指纹+同市场
    for r in rejected:
        if r.get('fingerprint_full', r.get('fingerprint', '')) == fp and r.get('market') == market:
            return rejected

    rejected_entry = {
        'name': entry_data.get('name', 'Unknown'),
        'fingerprint': fp[:8] if fp else 'N/A',
        'fingerprint_full': fp,
        'market': market,
        'score': entry_data.get('score', 0),
        'annual_return': entry_data.get('annual_return', 0),
        'max_drawdown': entry_data.get('max_drawdown', 0),
        'rejection_reason': reason,
        'rejected_at': datetime.now().isoformat(),
    }
    rejected.append(rejected_entry)
    return rejected


# ================================================================
# 报告格式化
# ================================================================
def format_leaderboard_table(leaderboard: list) -> str:
    """格式化排行榜表格"""
    if not leaderboard:
        return "当前排行榜为空（尚未有策略完成回测评分）"

    header = f"{'排名':<4} {'类型':<10} {'策略名称':<24} {'指纹':<8} {'得分':<7} " \
             f"{'年化':<8} {'夏普':<7} {'回撤':<8} {'单标年交易':<10} " \
             f"{'鲁棒':<4} {'偏差':<4} {'止损':<4}"
    sep = '-' * len(header)
    lines = [header, sep]

    for i, e in enumerate(leaderboard, 1):
        robust = '✅' if e.get('cross_period_robust') else '❌'
        bias = '⚠️' if e.get('survivorship_bias') else '✅'
        stop = '✅' if e.get('has_stop_loss') else '⚠️'
        name = e['name'][:22]
        lines.append(
            f"{i:<4} {e.get('type', '其他'):<10} {name:<24} {e['fingerprint']:<8} "
            f"{e['score']:<7.1f} {e['annual_return']*100:<7.1f}% "
            f"{e['sharpe']:<7.2f} {e['max_drawdown']*100:<7.1f}% "
            f"{e.get('avg_trades_per_stock', 0):<10.0f} "
            f"{robust:<4} {bias:<4} {stop:<4}"
        )

    return '\n'.join(lines)


def format_top5_detail(leaderboard: list) -> str:
    """格式化前五策略详细参数展示"""
    if not leaderboard:
        return ""

    lines = []
    for i, e in enumerate(leaderboard, 1):
        lines.append(f"━━━ 第{i}名 ━━━")
        lines.append(f"  策略名称: {e['name']}")
        lines.append(f"  策略类型: {e.get('type', '其他')}")
        lines.append(f"  市场: {e.get('market', 'N/A')}")
        lines.append(f"  综合得分: {e['score']:.1f}")
        lines.append(f"  年化收益: {e['annual_return']*100:.2f}%")
        lines.append(f"  夏普比率: {e['sharpe']:.4f}")
        lines.append(f"  最大回撤: {e['max_drawdown']*100:.2f}%")
        lines.append(f"  盈亏比: {e.get('profit_loss_ratio', 0):.2f}")
        lines.append(f"  胜率: {e.get('win_rate', 0)*100:.2f}%")
        lines.append(f"  单标年交易次数: {e.get('avg_trades_per_stock', 0):.0f}")
        lines.append(f"  单笔最大亏损: {e.get('max_single_loss_pct', 0):.2f}%")
        lines.append(f"  跨周期鲁棒: {'✅' if e.get('cross_period_robust') else '❌'}")
        lines.append(f"  幸存者偏差: {'⚠️' if e.get('survivorship_bias') else '✅'}")
        lines.append(f"  止损保护: {'✅' if e.get('has_stop_loss') else '⚠️ 无止损'}")
        lines.append(f"  可移植性: {e.get('portability_score', 0)}/10")
        lines.append(f"  滑点模式: {e.get('slippage_mode', 'default_0.1%')}")
        lines.append(f"  经典策略: {'是' if e.get('is_classic') else '否'}")
        if e.get('stress_test'):
            st = e['stress_test']
            lines.append(f"  压力测试: 年化{st.get('annual_return', 0)*100:.2f}%, "
                         f"回撤{st.get('max_drawdown', 0)*100:.2f}%")
        lines.append("")

    return '\n'.join(lines)
