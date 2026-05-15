#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
熊市策略评分与排行榜模块
========================
熊市调整版评分体系 v3（基础分100 + 附加分10 - 扣分5 - 杠杆扣5）

评分表（熊市调整版 v3）:
  ┌──────────────────┬──────┬──────────────────────────────────────────────────────┬──────┐
  │ 指标              │ 权重 │ 计算方式（v3）                                      │ 上限 │
  ├──────────────────┼──────┼──────────────────────────────────────────────────────┼──────┤
  │ 年化收益率        │ 15%  │ min(15, 2.5 × annual^0.55)  幂函数，5%基准          │ 15分 │
  │ 卡尔玛比率        │ 25%  │ min(25, 8.5 × calmar^0.70)  幂函数，0.3基准         │ 25分 │
  │ 最大回撤          │ 30%  │ 30 × exp(-0.055 × (dd-3))  连续衰减，3%满分起点     │ 30分 │
  │ 盈亏比            │ 15%  │ min(15, 8.0 × (pf-1)^0.65)  幂函数，1.0为0分起点    │ 15分 │
  │ 胜率              │ 15%  │ min(15, 1.35 × (wr-25)^0.65)  幂函数，25%为0分起点   │ 15分 │
  ├──────────────────┼──────┼──────────────────────────────────────────────────────┼──────┤
  │ 月度稳定性附加分  │ +5   │ 月度盈利月份>70%加5分，50-70%加3分，<50%加0分        │ 5分  │
  │ 牛熊兼容附加分    │ +5   │ 牛市区间回撤≤15%且收益≥0                            │ 5分  │
  │ 幸存者偏差扣分    │ -5   │ 数据不含历史全量标的（v3从-10降为-5）                │-5分  │
  │ 杠杆预警扣分      │ -5   │ 保证金占用率峰值≥70%                                │-5分  │
  └──────────────────┴──────┴──────────────────────────────────────────────────────┴──────┘

  等级标签（同趋势市）:
    S+(≥85): 超级传奇    S(≥75): 传奇    A(≥65): 优秀    B(≥55): 良好
    C(≥40): 一般         D(≥25): 较差    F(<25): 废策略

策略类型分类:
  做空趋势 / 均值回归（抄底） / 对冲/配对 / 高股息防御 /
  避险资产轮动 / 低波轮动 / 其他

附加波动率特征标记:
  相关系数 ≥ 0.3  → 📈 做多波动率
  相关系数 ≤ -0.3 → 📉 做空波动率
  介于 -0.3~0.3  → ⚖️ 波动率中性
  无法计算        → ❓ 依赖不明
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional


import math

# ================================================================
# 熊市调整版综合评分 v3 —— 幂函数+连续衰减+月度稳定性+等级制
# ================================================================
def score_annual_return_bear(annual_return_pct: float) -> float:
    """年化收益率得分（熊市权重15%，上限15分）—— 幂函数尺度
    
    v3改革：用幂函数替代对数函数，中等收益策略得分提升。
    熊市年化普遍很低，5%为基准线：
    
    安全约束：annual_return_pct 必须 ≥0，负值会导致幂函数产生复数。
    
    - 0%  → 0分
    - 2%  → 4.1分
    - 5%  → 7.2分（基准）
    - 10% → 10.7分
    - 15% → 13.1分
    - 20% → 15.0分（封顶）
    """
    # 显式防御：负值会导致 annual^0.55 产生复数
    if not isinstance(annual_return_pct, (int, float)):
        return 0.0
    if annual_return_pct <= 0:
        return 0.0
    score = 2.5 * (annual_return_pct ** 0.55)
    return round(min(max(score, 0), 15), 2)


def score_calmar_ratio(calmar_ratio: float) -> float:
    """卡尔玛比率得分（熊市核心权重25%，上限25分）—— 幂函数尺度
    
    v3改革：用幂函数替代对数函数，中等卡尔玛策略得分提升。
    
    安全约束：calmar_ratio 必须 ≥0，负值会导致幂函数产生复数。
    
    - 0    → 0分
    - 0.2  → 5.5分
    - 0.5  → 10.7分
    - 1.0  → 17.3分
    - 1.5  → 21.6分
    - 2.0  → 25.0分（封顶）
    """
    # 显式防御：负值会导致 calmar^0.70 产生复数
    if not isinstance(calmar_ratio, (int, float)):
        return 0.0
    if calmar_ratio <= 0:
        return 0.0
    score = 8.5 * (calmar_ratio ** 0.70)
    return round(min(max(score, 0), 25), 2)


def score_max_drawdown_bear(max_drawdown_pct: float) -> float:
    """最大回撤得分（熊市核心权重30%，连续衰减，上限30分）
    
    v3微调：衰减系数0.065保持不变（熊市回撤区分度本来就足够）
    - 3%  → 30.0分（满分）
    - 5%  → 26.6分
    - 8%  → 22.0分
    - 10% → 19.2分
    - 15% → 14.0分
    - 20% → 10.2分
    - 25% → 7.5分
    - 30% → 5.5分
    """
    abs_dd = abs(max_drawdown_pct)
    if abs_dd <= 3:
        return 30.0
    score = 30.0 * math.exp(-0.065 * (abs_dd - 3))
    return round(min(max(score, 0), 30), 2)


def score_profit_factor_bear(profit_factor: float) -> float:
    """盈亏比得分（熊市权重15%，上限15分）—— 幂函数尺度，1.0为0分起点
    
    v3改革：用幂函数替代对数函数。
    
    安全约束：profit_factor 必须 ≥1.0，<1时 (pf-1)^0.65 产生复数。
    盈亏比<1的策略为负期望，此项直接得0分。
    
    - 1.0 → 0分
    - 1.2 → 2.8分
    - 1.5 → 5.1分
    - 1.8 → 6.9分
    - 2.0 → 8.0分
    - 3.0 → 12.6分
    - 4.0 → 15.0分（封顶）
    """
    # 显式防御：pf<1时 (pf-1)^0.65 产生复数
    if not isinstance(profit_factor, (int, float)):
        return 0.0
    if profit_factor <= 1.0:
        return 0.0
    score = 8.0 * ((profit_factor - 1.0) ** 0.65)
    return round(min(max(score, 0), 15), 2)


def score_win_rate_bear(win_rate_pct: float) -> float:
    """胜率得分（熊市权重15%，上限15分）—— 幂函数尺度，25%为0分起点
    
    v3改革：用幂函数替代对数函数。熊市胜率普遍偏低，25%为0分起点：
    
    安全约束：win_rate_pct 必须 ≥25，<25时 (wr-25)^0.65 产生复数。
    
    - 25% → 0分
    - 30% → 2.6分
    - 35% → 4.5分
    - 40% → 6.0分
    - 45% → 7.3分
    - 50% → 8.5分
    - 55% → 9.7分
    - 60% → 10.7分
    - 70% → 12.7分
    - 80% → 15.0分（封顶）
    """
    # 显式防御：wr<25时 (wr-25)^0.65 产生复数
    if not isinstance(win_rate_pct, (int, float)):
        return 0.0
    if win_rate_pct <= 25:
        return 0.0
    score = 1.35 * ((win_rate_pct - 25) ** 0.65)
    return round(min(max(score, 0), 15), 2)


def score_monthly_stability_bear(monthly_positive_rate: float) -> float:
    """月度收益稳定性附加分（0-5分）—— 熊市版
    
    与趋势市相同逻辑：
    - <50% → 0分（收益极度不稳定）
    - 50-70% → 3分（一般稳定性）
    - >70% → 5分（高稳定性）
    
    Args:
        monthly_positive_rate: 月度正收益月份占比（0-1之间），None表示数据不可用
    """
    # 数据不可用时（旧排行榜策略可能无此字段），默认0分
    if monthly_positive_rate is None:
        return 0.0
    if monthly_positive_rate <= 0.5:
        return 0.0
    elif monthly_positive_rate <= 0.7:
        return 3.0
    else:
        return 5.0


def get_grade(total_score: float) -> str:
    """根据总分返回策略等级标签"""
    if total_score >= 85:
        return 'S+'
    elif total_score >= 75:
        return 'S'
    elif total_score >= 65:
        return 'A'
    elif total_score >= 55:
        return 'B'
    elif total_score >= 40:
        return 'C'
    elif total_score >= 25:
        return 'D'
    else:
        return 'F'


def compute_bear_total_score(
    annual_return: float,
    calmar_ratio: float,
    max_drawdown: float,
    profit_factor: float,
    win_rate: float,
    bull_compatible: bool = False,
    survivorship_bias: bool = True,
    leverage_warning: bool = False,
    monthly_positive_rate: float = 0.0,
) -> dict:
    """
    计算熊市策略综合评分（v3）。

    Args:
        annual_return: 年化收益率（%）
        calmar_ratio: 卡尔玛比率 = 年化收益率 / 最大回撤绝对值
        max_drawdown: 最大回撤（%，正数）
        profit_factor: 盈亏比
        win_rate: 胜率（%）
        bull_compatible: 牛熊兼容（牛市区间回撤≤15%且收益≥0）
        survivorship_bias: 是否存在幸存者偏差（True=存在偏差→扣分）
        leverage_warning: 是否存在高杠杆风险（保证金占用率峰值≥70%）
        monthly_positive_rate: 月度正收益月份占比（0-1）
    """
    s_ar = score_annual_return_bear(annual_return)
    s_calmar = score_calmar_ratio(calmar_ratio)
    s_dd = score_max_drawdown_bear(max_drawdown)
    s_pf = score_profit_factor_bear(profit_factor)
    s_wr = score_win_rate_bear(win_rate)

    base_score = s_ar + s_calmar + s_dd + s_pf + s_wr

    bonus_bull = 5.0 if bull_compatible else 0.0
    bonus_monthly = score_monthly_stability_bear(monthly_positive_rate)
    penalty_bias = -5.0 if survivorship_bias else 0.0  # v3: 从-10降为-5
    penalty_leverage = -5.0 if leverage_warning else 0.0

    total = base_score + bonus_bull + bonus_monthly + penalty_bias + penalty_leverage

    # 等级标签
    grade = get_grade(total)

    return {
        'annual_return_score': round(s_ar, 2),
        'calmar_ratio_score': round(s_calmar, 2),
        'max_drawdown_score': round(s_dd, 2),
        'profit_factor_score': round(s_pf, 2),
        'win_rate_score': round(s_wr, 2),
        'base_score': round(base_score, 2),
        'bull_compatible_bonus': bonus_bull,
        'monthly_stability_bonus': bonus_monthly,
        'monthly_positive_rate': round(monthly_positive_rate, 3),
        'survivorship_penalty': penalty_bias,
        'leverage_penalty': penalty_leverage,
        'total_score': round(total, 2),
        'grade': grade,
        'max_drawdown_hard_fail': abs(max_drawdown) > 20,  # 熊市硬性条件：回撤≤20%
    }


# ================================================================
# 策略类型自动分类（熊市版）
# ================================================================
BEAR_STRATEGY_TYPE_KEYWORDS = {
    '做空趋势': ['short', '做空', 'inverse', 'inverse etf', '空仓',
                'trend reversal', '趋势反转', '反手', 'bear trend',
                'short selling', 'sell short'],
    '均值回归（抄底）': ['mean reversion', 'oversold', '超跌反弹', '均值回归',
                      'rsi oversold', 'bounce', '底部', '抄底', 'regression'],
    '对冲/配对': ['hedge', 'pairs', 'pair trading', 'market neutral',
                'long-short', 'long short', '对冲', '配对', '套利',
                'spread', 'statistical arbitrage', 'hedging'],
    '高股息防御': ['dividend', 'yield', 'high yield', 'income',
                '股息', '红利', '高股息', 'aristocrats', 'defensive',
                'dividend aristocrats'],
    '避险资产轮动': ['gold', 'treasury', 'bond', 'flight to quality',
                  'safe haven', 'risk-off', '黄金', '国债', '债券',
                  'gld', 'tlt', 'vix', 'vxx', '恐慌', '避险',
                  'rotation', '轮动'],
    '低波轮动': ['low volatility', 'min variance', 'low vol',
              '低波动', '最小方差', 'risk parity', '风险平价',
              'minimum volatility'],
}


def classify_bear_strategy(strategy_name: str, strategy_code: str = '',
                           description: str = '') -> str:
    """策略类型自动分类（熊市版）"""
    text = f"{strategy_name} {strategy_code} {description}".lower()

    scores = {}
    for type_name, keywords in BEAR_STRATEGY_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[type_name] = score

    if not scores:
        return '其他'

    return max(scores, key=scores.get)


# ================================================================
# 波动率特征标记
# ================================================================
def classify_volatility_correlation(vix_correlation: float) -> str:
    """
    按策略收益与VIX的20日滚动相关系数判定波动率特征。

    Args:
        vix_correlation: 与VIX指数日收益率的20日滚动相关系数

    Returns:
        波动率特征标记字符串
    """
    if vix_correlation is None:
        return '❓ 依赖不明'

    if vix_correlation >= 0.3:
        return '📈 做多波动率'
    elif vix_correlation <= -0.3:
        return '📉 做空波动率'
    else:
        return '⚖️ 波动率中性'


# ================================================================
# 牛熊兼容性检查
# ================================================================
def check_bull_compatibility(bull_result: dict) -> dict:
    """
    牛市辅助测试区间验证。

    条件：
      - 牛市区间最大回撤 ≤ 15%
      - 牛市区间收益 ≥ 0
    满足 → "✅ 牛熊兼容"，附加分+5
    不满足 → "⚠️ 仅限熊市"
    """
    if not bull_result:
        return {'compatible': False, 'tag': '⚠️ 仅限熊市', 'detail': '无牛市区间数据'}

    bull_dd = abs(bull_result.get('mean_max_drawdown', 100))
    bull_annual = bull_result.get('mean_annual_return', -100)

    if bull_dd <= 15 and bull_annual >= 0:
        return {'compatible': True, 'tag': '✅ 牛熊兼容',
                'detail': f'牛市区间回撤{bull_dd:.1f}%≤15%, 年化{bull_annual:.1f}%≥0'}
    else:
        reasons = []
        if bull_dd > 15:
            reasons.append(f'回撤{bull_dd:.1f}%>15%')
        if bull_annual < 0:
            reasons.append(f'年化{bull_annual:.1f}%<0')
        return {'compatible': False, 'tag': '⚠️ 仅限熊市',
                'detail': '牛市区间: ' + '; '.join(reasons)}


# ================================================================
# 熊市排行榜维护
# ================================================================
BEAR_LEADERBOARD_PATH = '/data/workspace/strategy_arena/bear_leaderboard.json'
MAX_LEADERBOARD_SIZE = 10
PROTECTION_DAYS = 7


def load_bear_leaderboard(lb_path: str = BEAR_LEADERBOARD_PATH) -> list:
    """加载熊市策略排行榜"""
    if not os.path.exists(lb_path):
        return []
    try:
        with open(lb_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_bear_leaderboard(leaderboard: list, lb_path: str = BEAR_LEADERBOARD_PATH):
    """保存熊市策略排行榜"""
    os.makedirs(os.path.dirname(lb_path), exist_ok=True)
    with open(lb_path, 'w', encoding='utf-8') as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)


def update_bear_leaderboard(strategy_record: dict, leaderboard: list) -> list:
    """
    更新熊市排行榜。

    规则:
      1. 保留综合得分排名前十的高评分策略（无最低分数门槛）
      2. 同指纹+同市场策略取最高分更新
      3. 后续有更高分策略则替换末尾，重新排序只保留前十
    """
    new_score = strategy_record.get('total_score', 0)
    new_fp = strategy_record.get('fingerprint', '')
    new_market = strategy_record.get('market', 'us')

    # 检查是否已在排行榜中（指纹+市场联合去重）
    updated = False
    for i, entry in enumerate(leaderboard):
        if entry.get('fingerprint') == new_fp and entry.get('market') == new_market:
            if new_score > entry.get('total_score', 0):
                leaderboard[i] = strategy_record
            updated = True
            break

    if not updated:
        leaderboard.append(strategy_record)

    # 重新排序，只保留前十（高分优先，无最低门槛）
    leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)
    leaderboard = leaderboard[:MAX_LEADERBOARD_SIZE]

    return leaderboard


def is_in_protection(entry: dict) -> bool:
    """检查策略是否在保护期内（A级以下策略无保护期）"""
    # A级(≥65分)以下策略不享受保护期，谁得分更高谁上榜
    if entry.get('total_score', 0) < 65:
        return False
    first_listed = entry.get('first_listed_time', '')
    if not first_listed:
        return False
    try:
        listed_dt = datetime.strptime(first_listed, '%Y-%m-%d %H:%M:%S')
        return (datetime.now() - listed_dt) < timedelta(days=PROTECTION_DAYS)
    except Exception:
        return False


# ================================================================
# 从回测结果构建排行榜条目（熊市版）
# ================================================================
def build_bear_leaderboard_entry(backtest_result: dict, strategy_info: dict) -> dict:
    """
    从回测结果和策略信息构建熊市排行榜条目。
    """
    main = backtest_result.get('main_period', {})
    stress = backtest_result.get('stress_period', {})
    bull = backtest_result.get('bull_period', {})
    robust = backtest_result.get('cross_period_robust', False)
    bias = backtest_result.get('survivorship_bias_flag', True)

    if not main:
        return None

    annual = main.get('mean_annual_return', 0)
    sharpe = main.get('mean_sharpe', 0)
    dd = main.get('mean_max_drawdown', 0)
    pf = main.get('mean_profit_factor', 0)
    wr = main.get('mean_win_rate', 0)
    trades = main.get('mean_avg_trades_per_year', 0)

    # 卡尔玛比率
    abs_dd = abs(dd) if dd != 0 else 0.01
    calmar_ratio = annual / abs_dd if abs_dd > 0 else 0

    # 月度正收益占比（v3新增）
    monthly_positive_rate = main.get('monthly_positive_rate', 0.0)
    monthly_returns = main.get('monthly_returns', None)
    if monthly_returns and len(monthly_returns) > 0 and monthly_positive_rate == 0.0:
        monthly_positive_rate = sum(1 for r in monthly_returns if r > 0) / len(monthly_returns)

    # 牛熊兼容性
    bull_compat = check_bull_compatibility(bull)

    # 杠杆预警（保证金占用率峰值≥70%）
    leverage_warning = backtest_result.get('margin_occupancy_peak', 0) >= 0.70

    # 计算综合评分（熊市版v3）
    score_detail = compute_bear_total_score(
        annual_return=annual,
        calmar_ratio=calmar_ratio,
        max_drawdown=dd,
        profit_factor=pf,
        win_rate=wr,
        bull_compatible=bull_compat['compatible'],
        survivorship_bias=bias,
        leverage_warning=leverage_warning,
        monthly_positive_rate=monthly_positive_rate,
    )

    # 策略类型
    strategy_type = classify_bear_strategy(
        strategy_info.get('strategy_name', ''),
        strategy_info.get('strategy_code', ''),
        strategy_info.get('description', ''),
    )

    # 波动率特征
    vix_corr = backtest_result.get('vix_correlation', None)
    vol_feature = classify_volatility_correlation(vix_corr)

    # 硬性条件检查（仅标记风险，不清零得分——排行榜保留前十高评分）
    hard_fail = score_detail.get('max_drawdown_hard_fail', True)

    # 风险标记
    risk_tags = []
    if hard_fail:
        risk_tags.append('⚠️回撤>20%')
    if bias:
        risk_tags.append('⚠️幸存者偏差')
    if backtest_result.get('short_cost_warning', False):
        risk_tags.append('⚠️未内置融券成本')
    if leverage_warning:
        risk_tags.append('⚠️高杠杆风险')
    if not bull_compat['compatible']:
        risk_tags.append('⚠️仅限熊市')

    entry = {
        'strategy_name': strategy_info.get('strategy_name', 'Unknown'),
        'source_link': strategy_info.get('source_link', ''),
        'fingerprint': strategy_info.get('fingerprint', ''),
        'fingerprint_short': strategy_info.get('fingerprint', '')[:8],
        'strategy_type': strategy_type,
        'volatility_feature': vol_feature,
        'total_score': score_detail['total_score'],
        'grade': score_detail.get('grade', 'F'),
        'score_detail': score_detail,
        # 核心指标
        'annual_return': annual,
        'calmar_ratio': round(calmar_ratio, 2),
        'sharpe': sharpe,
        'max_drawdown': dd,
        'profit_factor': pf,
        'win_rate': wr,
        'avg_trades_per_year': trades,
        # 策略详细参数
        'strategy_params': strategy_info.get('strategy_params', {}),
        'strategy_description': strategy_info.get('description', ''),
        # 标记
        'cross_period_robust': robust,
        'bull_compatible': bull_compat['compatible'],
        'bull_compatible_tag': bull_compat['tag'],
        'risk_tags': ' '.join(risk_tags),
        'survivorship_bias': bias,
        'bias_tag': '⚠️' if bias else '',
        'pine_script_rejected': strategy_info.get('pine_script_rejected', False),
        'short_cost_warning': backtest_result.get('short_cost_warning', False),
        'leverage_warning': leverage_warning,
        'margin_occupancy_peak': backtest_result.get('margin_occupancy_peak', 0),
        # 元信息
        'portability_score': strategy_info.get('portability_score', 0),
        'backtest_time': backtest_result.get('backtest_time', ''),
        'first_listed_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'removal_reason': '',
        # 压力测试
        'stress_annual': stress.get('mean_annual_return', 0) if stress else 0,
        'stress_dd': stress.get('mean_max_drawdown', 0) if stress else 0,
        # 牛市测试
        'bull_annual': bull.get('mean_annual_return', 0) if bull else 0,
        'bull_dd': bull.get('mean_max_drawdown', 0) if bull else 0,
        # 市场信息
        'market': main.get('market', 'us'),
        'n_stocks': main.get('n_stocks', 0),
        # VIX相关
        'vix_correlation': vix_corr,
    }

    return entry


# ================================================================
# 格式化排行榜表格（熊市版）
# ================================================================
def format_bear_leaderboard_table(leaderboard: list) -> str:
    """格式化熊市排行榜为Markdown表格（含等级标签和详细参数）"""
    if not leaderboard:
        return "当前熊市排行榜为空，尚无策略完成回测评分。"

    lines = [
        "| 排名 | 等级 | 类型 | 波动率特征 | 策略名称 | 市场 | 得分 | 年化收益 | 夏普 | 最大回撤 | 盈亏比 | 胜率 | 年交易次数 | 兼容标记 | 风险标记 |",
        "|------|------|------|-----------|---------|------|------|---------|------|---------|--------|------|-----------|---------|---------|",
    ]

    for i, entry in enumerate(leaderboard, 1):
        name = entry.get('strategy_name', 'Unknown')[:24]
        s_type = entry.get('strategy_type', '其他')
        vol_feat = entry.get('volatility_feature', '❓')
        market = entry.get('market', '?').upper()
        score = entry.get('total_score', 0)
        grade = entry.get('grade', get_grade(score))
        annual = entry.get('annual_return', 0)
        sharpe = entry.get('sharpe', 0)
        dd = entry.get('max_drawdown', 0)
        pf = entry.get('profit_factor', 0)
        wr = entry.get('win_rate', 0)
        trades = entry.get('avg_trades_per_year', 0)
        compat = entry.get('bull_compatible_tag', '⚠️仅限熊市')
        risk = entry.get('risk_tags', '')

        lines.append(
            f"| {i} | {grade} | {s_type} | {vol_feat} | {name} | {market} | "
            f"{score} | {annual}% | {sharpe} | {dd}% | "
            f"{pf} | {wr}% | {trades} | {compat} | {risk} |"
        )

    return '\n'.join(lines)


# ================================================================
# 样本外滚动验证与失效判定（熊市放宽条件）
# ================================================================
def check_bear_strategy_invalidation(weekly_returns: list,
                                      market_in_downtrend: bool = True) -> dict:
    """
    熊市策略样本外滚动验证失效判定。

    熊市放宽条件:
      - 若市场进入牛市，允许策略小幅跑输
      - 若市场处于下跌趋势（指数周线MA20向下）时，
        策略绝对收益连续3周为负 且 累计亏损≥2% → "⚠️ 熊市防御失效"
        （v3.1修正：加入幅度门槛，避免横盘微震误杀优秀CTA策略）

    Args:
        weekly_returns: 最近N周的周收益率列表（%）
        market_in_downtrend: 当前市场是否处于下跌趋势
    """
    if len(weekly_returns) < 3:
        return {'invalidated': False, 'details': '数据不足（需至少3周）'}

    last_3 = weekly_returns[-3:]
    negative_weeks = sum(1 for r in last_3 if r < 0)

    if not market_in_downtrend:
        # 牛市环境：允许小幅跑输，不判定失效
        return {
            'invalidated': False,
            'details': f'当前牛市环境，熊市策略小幅跑输属正常。最近3周累计{sum(last_3):.1f}%'
        }

    # 熊市环境：连续3周绝对收益为负 且 累计亏损≥2% → 失效
    # v3.1修正：加入幅度门槛，避免横盘期微震（如每周-0.2%）误杀优秀CTA策略
    cumulative = sum(last_3)
    if negative_weeks >= 3 and cumulative <= -2.0:
        return {
            'invalidated': True,
            'details': f'熊市环境下连续3周绝对收益为负且累计{cumulative:.1f}%（≤-2%），防御失效（{last_3}）'
        }

    return {
        'invalidated': False,
        'details': f'最近3周: {last_3}，{negative_weeks}周为负，累计{cumulative:.1f}%'
    }


# ================================================================
# 单元测试
# ================================================================
if __name__ == '__main__':
    # 测试评分
    score = compute_bear_total_score(
        annual_return=13.8,
        calmar_ratio=1.52,
        max_drawdown=9.1,
        profit_factor=2.1,
        win_rate=48.0,
        bull_compatible=True,
        survivorship_bias=True,
        leverage_warning=False,
        monthly_positive_rate=0.65,
    )
    print(f"熊市综合评分: {score}")

    # 测试分类
    print(f"做空趋势: {classify_bear_strategy('Short Trend Reversal', 'short selling bear')}")
    print(f"避险轮动: {classify_bear_strategy('Gold Treasury Rotation', 'gold treasury bond')}")
    print(f"高股息: {classify_bear_strategy('Dividend Aristocrats Defense', 'dividend yield')}")

    # 测试牛熊兼容
    bull_ok = {'mean_max_drawdown': 12, 'mean_annual_return': 5}
    bull_bad = {'mean_max_drawdown': 25, 'mean_annual_return': -3}
    print(f"兼容检查(OK): {check_bull_compatibility(bull_ok)}")
    print(f"兼容检查(BAD): {check_bull_compatibility(bull_bad)}")

    # 测试波动率标记
    print(f"正相关: {classify_volatility_correlation(0.45)}")
    print(f"负相关: {classify_volatility_correlation(-0.35)}")
    print(f"中性: {classify_volatility_correlation(0.1)}")

    # 测试排行榜
    lb = load_bear_leaderboard()
    print(f"当前排行榜: {len(lb)}个策略")
    print(format_bear_leaderboard_table(lb))
