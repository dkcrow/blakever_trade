#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略评分与排行榜模块
====================
职责:
  1. 计算核心指标（年化收益率、夏普比率、最大回撤、盈亏比、胜率等）
  2. 综合评分（基础分100 + 附加分10 - 扣分项）
  3. 策略等级标签（S+/S/A/B/C/D/F）
  4. 策略类型自动分类
  5. 排行榜维护（前10高评分策略）
  6. 样本外滚动验证与失效判定

评分表 v4（对数+安全区奖励，永不截断）—— 收益越高/夏普越高/盈亏比越高，得分越高:
  ┌──────────────────┬──────┬────────────────────────────────────────────────────────────┬──────┐
  │ 指标              │ 权重 │ 计算方式（v4）                                            │ 上限 │
  ├──────────────────┼──────┼────────────────────────────────────────────────────────────┼──────┤
  │ 年化收益率        │ 25%  │ 6.0 × ln(1 + annual/12)  对数函数，永不截断               │ 无   │
  │ 夏普比率          │ 25%  │ 8.0 × ln(1 + sharpe/0.5)  对数函数，永不截断              │ 无   │
  │ 最大回撤          │ 20%  │ 20×exp(-0.038×(dd-5)) + 安全区奖励3×(1-dd/15)            │ ~23  │
  │ 盈亏比            │ 15%  │ 5.5×ln(pf) + 1.5×(pf-1)^0.5  混合对数+幂函数，永不截断   │ 无   │
  │ 胜率              │ 15%  │ min(15, 1.35 × (wr-30)^0.65)  幂函数，30%为0分起点        │ 15分 │
  ├──────────────────┼──────┼────────────────────────────────────────────────────────────┼──────┤
  │ 月度稳定性附加分  │ +5   │ 月度盈利月份>70%加5分，50-70%加3分，<50%加0分              │ 5分  │
  │ 跨周期鲁棒附加分  │ +5   │ 压力区间通过则加分                                        │ 5分  │
  │ 幸存者偏差扣分    │ -5   │ 数据不含历史全量标的（v3从-10降为-5）                      │-5分  │
  └──────────────────┴──────┴────────────────────────────────────────────────────────────┴──────┘
  
  等级标签（v4适配对数分数区间）:
    S+(≥75): 超级传奇    S(≥62): 传奇    A(≥50): 优秀    B(≥40): 良好
    C(≥28): 一般         D(≥16): 较差    F(<16): 废策略

  v4 vs v3 核心改革:
    1. 天花板截断→对数函数: 年化/夏普/盈亏比永不撞顶，越高得分越高
       - v3问题: 年化80%和300%得分都是25分，无法区分！
       - v4解决: 6.0×ln(1+annual/12)，200%得分17.2，300%得分19.6，永远有区分度
    2. 回撤安全区奖励: 回撤≤15%时额外加分，低回撤策略获得更多奖励
       - v3问题: 回撤只做"扣分"，低回撤的优秀风险控制得不到足够认可
       - v4解决: 5%回撤→22分(基础20+奖励2)，12%回撤→15.9分(基础15.3+奖励0.6)
    3. 盈亏比混合函数: 5.5×ln(pf) + 1.5×(pf-1)^0.5
       - 低盈亏比区(1-2): 幂函数项主导，灵敏度好
       - 高盈亏比区(3+): 对数项主导，增长不停止

  v4 vs v3 对比示例:
    年化50%   → v3:24.1(接近截断)  v4:9.9  (中值区分)
    年化80%   → v3:25.0(✂️截断!)   v4:12.2 (继续增长)
    年化200%  → v3:25.0(✂️截断!)   v4:17.2 (差距拉开!)
    夏普3.0   → v3:21.7            v4:15.6
    夏普4.0   → v3:25.0(✂️截断!)   v4:17.6 (继续增长!)
    盈亏比4.0 → v3:15.0(✂️截断!)   v4:10.2 (继续增长!)
    盈亏比6.0 → v3:15.0(✂️截断!)   v4:13.2 (差距拉开!)
    
    A股TOP2（收益/夏普/盈亏比全面领先的第二名）:
      v3: 🥇93.6 vs 🥈93.4 → 第二名反低0.14分 ✗
      v4: 🥇71.9 vs 🥈74.5 → 第二名正确高2.6分 ✓
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional


import math

# ================================================================
# 综合评分 v4 —— 对数+安全区奖励（永不截断，越高越好）
# ================================================================

def score_annual_return(annual_return_pct: float) -> float:
    """年化收益率得分（权重25%，无上限截断）—— 对数函数尺度
    
    v4核心改革：用对数函数替代幂函数+天花板截断。
    v3的固有问题：min(25, 2.8×annual^0.55)在年化≥80%时撞天花板，
    导致年化80%和300%得分完全一样(25分)，无法区分优秀策略。
    
    对数函数6.0×ln(1+annual/12)特性：
    - 增长永不停止（没有天花板），越高越好但边际递减
    - 低-中值区增长快（好拿分），高值区增长慢（避免爆炸）
    - 年化164% vs 212%：得分16.1 vs 17.6 → 正确拉开差距！
    
    安全约束：annual_return_pct 必须 ≥0，ln要求参数>0。
    亏损策略此项直接得0分。
    
    - 0%   → 0分
    - 5%   → 2.1分
    - 8%   → 3.1分（及格线）
    - 15%  → 4.9分
    - 25%  → 6.8分（良好）
    - 35%  → 8.2分（优秀线）
    - 50%  → 9.9分
    - 80%  → 12.2分
    - 100% → 13.4分
    - 150% → 15.6分
    - 200% → 17.2分
    - 300% → 19.6分（永不封顶）
    """
    # 显式防御：负值/非数值直接得0分
    if not isinstance(annual_return_pct, (int, float)):
        return 0.0
    if annual_return_pct <= 0:
        return 0.0
    score = 6.0 * math.log(1 + annual_return_pct / 12.0)
    return round(max(score, 0), 2)


def score_sharpe(sharpe: float) -> float:
    """夏普比率得分（权重25%，无上限截断）—— 对数函数尺度
    
    v4核心改革：用对数函数替代幂函数+天花板截断。
    v3的固有问题：min(25, 9.5×sharpe^0.75)在夏普≥3.7时撞天花板。
    
    对数函数8.0×ln(1+sharpe/0.5)特性：
    - 夏普3.0 → 15.6分，夏普4.0 → 17.6分，夏普5.0 → 19.2分
    - 永远有区分度，高夏普策略不再被"一视同仁"
    
    安全约束：sharpe 必须 ≥0，负夏普策略此项直接得0分。
    
    - 0    → 0分
    - 0.3  → 3.7分
    - 0.5  → 5.5分（及格）
    - 0.8  → 7.8分
    - 1.0  → 8.8分
    - 1.3  → 10.2分
    - 1.5  → 11.1分（优秀）
    - 1.8  → 12.3分
    - 2.0  → 12.9分
    - 3.0  → 15.6分
    - 4.0  → 17.6分（v3截断为25=无区分，v4继续增长）
    - 5.0  → 19.2分（永不封顶）
    """
    # 显式防御：负值会导致数学错误
    if not isinstance(sharpe, (int, float)):
        return 0.0
    if sharpe <= 0:
        return 0.0
    score = 8.0 * math.log(1 + sharpe / 0.5)
    return round(max(score, 0), 2)


def score_max_drawdown(max_drawdown_pct: float) -> float:
    """最大回撤得分（权重20%，上限~23分）—— 指数衰减 + 安全区奖励
    
    v4核心改革：新增安全区奖励机制。
    v3的固有问题：回撤只做"扣分"（越低扣越少），低回撤的出色风险控制
    得不到足够认可。回撤5%和回撤12%之间只有4.7分差距。
    
    v4安全区奖励：回撤≤15%时，额外获得 3×(1-dd/15) 分
    - 这意味着：5%回撤 → 基础20 + 奖励2.0 = 22.0分
    - 10%回撤 → 基础16.5 + 奖励1.0 = 17.5分
    - 12%回撤 → 基础15.3 + 奖励0.6 = 15.9分
    - 15%回撤 → 基础13.7 + 奖励0 = 13.7分（安全区边界）
    - 20%回撤 → 基础11.3 + 奖励0 = 11.3分
    
    - 5%  → 22.0分（满分+奖励）
    - 8%  → 19.2分
    - 10% → 17.5分
    - 12% → 15.9分
    - 15% → 13.7分
    - 20% → 11.3分
    - 25% → 9.3分
    - 30% → 7.7分
    - 40% → 5.3分
    - 50% → 3.6分
    """
    abs_dd = abs(max_drawdown_pct)
    # 基础分：指数衰减（同v3.1）
    base = 20.0 * math.exp(-0.038 * (max(abs_dd, 5) - 5))
    # 安全区奖励：回撤≤15%时额外加分
    safe_bonus = 0.0
    if abs_dd <= 15:
        safe_bonus = 3.0 * (1.0 - abs_dd / 15.0)
    return round(min(max(base + safe_bonus, 0), 23), 2)


def score_profit_factor(profit_factor: float) -> float:
    """盈亏比得分（权重15%，无上限截断）—— 混合对数+幂函数
    
    v4核心改革：用混合函数 5.5×ln(pf) + 1.5×(pf-1)^0.5 替代幂函数+天花板截断。
    v3的固有问题：min(15, 8.0×(pf-1)^0.65)在盈亏比≥4.0时撞天花板，
    导致盈亏比4.0和6.0得分完全一样(15分)。
    
    混合函数特性：
    - 低盈亏比区(1-2): 幂函数项1.5×(pf-1)^0.5灵敏度好
    - 高盈亏比区(3+): 对数项5.5×ln(pf)主导，增长永不停止
    - 盈亏比3.0 → 8.2分, 4.0 → 10.2分, 5.0 → 11.9分, 6.0 → 13.2分
    
    安全约束：profit_factor 必须 ≥1.0，<1时得0分。
    盈亏比<1的策略为负期望，此项直接得0分。
    
    - 1.0 → 0分（盈亏平衡）
    - 1.2 → 1.6分
    - 1.5 → 3.3分
    - 1.8 → 4.7分
    - 2.0 → 5.3分
    - 2.5 → 6.9分
    - 3.0 → 8.2分（优秀）
    - 3.5 → 9.3分
    - 4.0 → 10.2分（v3截断为15=无区分，v4继续增长）
    - 5.0 → 11.9分
    - 6.0 → 13.2分（永不封顶）
    """
    # 显式防御：pf<1时得0分
    if not isinstance(profit_factor, (int, float)):
        return 0.0
    if profit_factor <= 1.0:
        return 0.0
    score = 5.5 * math.log(profit_factor) + 1.5 * ((profit_factor - 1.0) ** 0.5)
    return round(max(score, 0), 2)


def score_win_rate(win_rate_pct: float) -> float:
    """胜率得分（权重15%，上限15分）—— 幂函数尺度，30%为0分起点
    
    v3改革：用幂函数((wr-30)^0.65)替代对数函数，中等胜率得分提升。
    
    安全约束：win_rate_pct 必须 ≥30，<30时 (wr-30)^0.65 产生复数。
    胜率低于30%的策略此项直接得0分。
    
    - 30% → 0分
    - 35% → 3.8分
    - 40% → 6.0分
    - 45% → 7.8分
    - 50% → 9.5分
    - 55% → 10.9分
    - 60% → 12.3分
    - 65% → 13.6分
    - 70% → 14.8分
    - 75% → 15.0分（封顶）
    """
    # 显式防御：wr<30时 (wr-30)^0.65 产生复数，必须拦截
    if not isinstance(win_rate_pct, (int, float)):
        return 0.0
    if win_rate_pct <= 30:
        return 0.0
    score = 1.35 * ((win_rate_pct - 30) ** 0.65)
    return round(min(max(score, 0), 15), 2)


def score_monthly_stability(monthly_positive_rate: float) -> float:
    """月度收益稳定性附加分（0-5分）
    
    月度盈利月份占比越高，策略收益越稳定，过拟合概率越低。
    - <50% → 0分（收益极度不稳定）
    - 50-70% → 3分（一般稳定性）
    - >70% → 5分（高稳定性，每月大概率盈利）
    
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
    """根据总分返回策略等级标签（v4适配对数分数区间）
    
    v4对数函数使分数整体下移（相比v3幂函数+截断），等级门槛同步调整：
      v3: S+≥85  S≥75  A≥65  B≥55  C≥40  D≥25  F<25
      v4: S+≥75  S≥62  A≥50  B≥40  C≥28  D≥16  F<16
    
    典型映射（v4）:
      超神(200%/4.0/8%/5.0/65%)=84.5→S+    传奇(150%/3.0/10%/4.0/60%)=76.3→S+
      顶级(100%/2.5/10%/3.5/58%)=66.3→S    优秀(50%/1.8/12%/2.5/55%)=55.8→A
      良好(30%/1.3/15%/2.0/50%)=41.2→B     一般(15%/0.8/20%/1.5/45%)=30.0→C
      较差(8%/0.4/28%/1.2/40%)=18.8→D      废策略(3%/0.2/35%/1.05/35%)=9.9→F
    """
    if total_score >= 75:
        return 'S+'
    elif total_score >= 62:
        return 'S'
    elif total_score >= 50:
        return 'A'
    elif total_score >= 40:
        return 'B'
    elif total_score >= 28:
        return 'C'
    elif total_score >= 16:
        return 'D'
    else:
        return 'F'


def compute_total_score(
    annual_return: float,
    sharpe: float,
    max_drawdown: float,
    profit_factor: float,
    win_rate: float,
    cross_period_robust: bool = False,
    survivorship_bias: bool = True,  # True表示存在偏差
    monthly_positive_rate: float = 0.0,  # 月度正收益月份占比（0-1）
    var_95: float = None,  # 95% VaR（日度，负数）
    cvar_95: float = None,  # 95% CVaR（日度，负数）
    ulcer_index: float = None,  # Ulcer Index（回撤深度和持续时间的综合指标）
    walk_forward_score: float = None,  # Walk-Forward分析得分（0-1，1=完美无过拟合）
) -> dict:
    """
    计算策略综合评分（v4：对数+安全区奖励，永不截断）。
    
    v4核心改革：
    1. 年化/夏普/盈亏比用对数函数替代天花板截断 → 越高得分越高，永不撞顶
    2. 回撤新增安全区奖励(≤15%回撤额外加分) → 低回撤策略获得更多认可
    3. 解决v3问题：收益/夏普/盈亏比全面领先的第二名不再被截断"一视同仁"
    
    Args:
        annual_return: 年化收益率（%）
        sharpe: 夏普比率
        max_drawdown: 最大回撤（%，正数）
        profit_factor: 盈亏比
        win_rate: 胜率（%）
        cross_period_robust: 是否通过跨周期验证
        survivorship_bias: 是否存在幸存者偏差（True=存在偏差→扣分）
        monthly_positive_rate: 月度正收益月份占比（0-1），用于计算月度稳定性附加分
    
    Returns:
        评分详情字典（含等级标签）
    """
    s_ar = score_annual_return(annual_return)
    s_sharpe = score_sharpe(sharpe)
    s_dd = score_max_drawdown(max_drawdown)
    s_pf = score_profit_factor(profit_factor)
    s_wr = score_win_rate(win_rate)

    base_score = s_ar + s_sharpe + s_dd + s_pf + s_wr

    bonus_robust = 5.0 if cross_period_robust else 0.0
    bonus_monthly = score_monthly_stability(monthly_positive_rate)
    penalty = -5.0 if survivorship_bias else 0.0  # v3: 从-10降为-5

    # === v5新增：下行风险指标附加分/扣分 ===
    # VaR/CVaR下行风险扣分（极端尾部风险惩罚）
    # VaR(95%)日度：-1%以内不扣分，-1%~-2%扣1分，-2%~-3%扣2分，<-3%扣3分
    var_penalty = 0.0
    if var_95 is not None and var_95 < -0.01:
        var_penalty = min(3.0, max(0, (-var_95 - 0.01) / 0.01)) * -1
    
    # CVaR(95%)日度：比VaR更严格，衡量极端损失均值
    # CVaR -1.5%以内不扣分，-1.5%~-3%扣1分，-3%~-4%扣2分，<-4%扣3分
    cvar_penalty = 0.0
    if cvar_95 is not None and cvar_95 < -0.015:
        cvar_penalty = min(3.0, max(0, (-cvar_95 - 0.015) / 0.015)) * -1
    
    # Ulcer Index附加分/扣分
    # UI<5 优秀+2分, 5-10 良好+1分, 10-20 一般0分, >20 扣1分
    ulcer_bonus = 0.0
    if ulcer_index is not None:
        if ulcer_index < 5:
            ulcer_bonus = 2.0
        elif ulcer_index < 10:
            ulcer_bonus = 1.0
        elif ulcer_index > 20:
            ulcer_bonus = -1.0
    
    # Walk-Forward防过拟合附加分
    # wf_score > 0.7 → +3分（强泛化），0.5-0.7 → +1分（可接受），<0.5 → 0分（过拟合风险）
    wf_bonus = 0.0
    if walk_forward_score is not None:
        if walk_forward_score > 0.7:
            wf_bonus = 3.0
        elif walk_forward_score > 0.5:
            wf_bonus = 1.0

    total = base_score + bonus_robust + bonus_monthly + penalty + var_penalty + cvar_penalty + ulcer_bonus + wf_bonus

    # 硬性条件标记
    hard_fail = abs(max_drawdown) > 50
    drawdown_penalty_tag = abs(max_drawdown) > 30
    
    # 等级标签
    grade = get_grade(total)

    return {
        'annual_return_score': round(s_ar, 2),
        'sharpe_score': round(s_sharpe, 2),
        'max_drawdown_score': round(s_dd, 2),
        'profit_factor_score': round(s_pf, 2),
        'win_rate_score': round(s_wr, 2),
        'base_score': round(base_score, 2),
        'cross_period_bonus': bonus_robust,
        'monthly_stability_bonus': bonus_monthly,
        'monthly_positive_rate': round(monthly_positive_rate, 3) if monthly_positive_rate is not None else None,
        'survivorship_penalty': penalty,
        'var_penalty': round(var_penalty, 2),
        'cvar_penalty': round(cvar_penalty, 2),
        'ulcer_bonus': round(ulcer_bonus, 2),
        'walk_forward_bonus': round(wf_bonus, 2),
        'var_95': var_95,
        'cvar_95': cvar_95,
        'ulcer_index': ulcer_index,
        'walk_forward_score': walk_forward_score,
        'total_score': round(total, 2),
        'grade': grade,
        'max_drawdown_hard_fail': hard_fail,  # 极端情况（>50%）才标记hard_fail
        'drawdown_penalty_tag': drawdown_penalty_tag,  # 回撤>30%标记扣分项（不归零）
    }


# ================================================================
# 策略类型自动分类
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
}


def classify_strategy(strategy_name: str, strategy_code: str = '',
                      description: str = '') -> str:
    """
    策略类型自动分类。
    基于策略名称、代码和描述中的关键词匹配。
    """
    text = f"{strategy_name} {strategy_code} {description}".lower()

    scores = {}
    for type_name, keywords in STRATEGY_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[type_name] = score

    if not scores:
        return '其他'

    # 返回得分最高的类型
    return max(scores, key=scores.get)


# ================================================================
# 排行榜维护
# ================================================================
LEADERBOARD_PATH = '/data/workspace/strategy_arena/leaderboard.json'
MAX_LEADERBOARD_SIZE = 10
# 不再设最低分数门槛，保留历史前十高评分策略（无论分数高低）
PROTECTION_DAYS = 7  # 新策略保护期


def load_leaderboard(lb_path: str = LEADERBOARD_PATH) -> list:
    """加载排行榜"""
    if not os.path.exists(lb_path):
        return []
    try:
        with open(lb_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_leaderboard(leaderboard: list, lb_path: str = LEADERBOARD_PATH):
    """保存排行榜"""
    os.makedirs(os.path.dirname(lb_path), exist_ok=True)
    with open(lb_path, 'w', encoding='utf-8') as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)


def update_leaderboard(strategy_record: dict, leaderboard: list) -> list:
    """
    更新排行榜。
    
    规则:
      1. 保留历史前十高评分策略（不设最低分数门槛）
      2. 同指纹策略取最高分更新
      3. 新策略保护期7天
      4. 后续有更高分则重新排序，只保留前十
    """
    new_score = strategy_record.get('total_score', 0)
    new_fp = strategy_record.get('fingerprint', '')
    new_market = strategy_record.get('market', 'us')

    # 检查是否已在排行榜中（同指纹+同市场视为同一策略）
    updated = False
    for i, entry in enumerate(leaderboard):
        if entry.get('fingerprint') == new_fp and entry.get('market') == new_market:
            # 更新已有条目（保留得分较高的）
            if new_score > entry.get('total_score', 0):
                leaderboard[i] = strategy_record
            updated = True
            break

    if not updated:
        # 新策略
        if len(leaderboard) < MAX_LEADERBOARD_SIZE:
            leaderboard.append(strategy_record)
        else:
            # 排序后检查能否替换末尾
            leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)
            worst = leaderboard[-1]
            # 检查末尾是否在保护期内
            if is_in_protection(worst):
                # 保护期内，不替换
                pass
            elif new_score > worst.get('total_score', 0):
                leaderboard[-1] = strategy_record

    # 排序（得分降序）
    leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)

    # 裁剪至前十
    leaderboard = leaderboard[:MAX_LEADERBOARD_SIZE]

    return leaderboard


def is_in_protection(entry: dict) -> bool:
    """检查策略是否在保护期内（A级以下策略无保护期）"""
    # A级(≥50分)以下策略不享受保护期，谁得分更高谁上榜
    if entry.get('total_score', 0) < 50:
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
# 样本外滚动验证与失效判定
# ================================================================
def check_strategy_invalidation(weekly_returns: list) -> dict:
    """
    样本外滚动验证失效判定。
    
    Args:
        weekly_returns: 最近N周的周收益率列表（%）
    
    失效条件:
      连续3周跑输基准累计≥3%，且其中至少2周策略绝对收益为负
    
    Returns:
      {'invalidated': bool, 'details': str}
    """
    if len(weekly_returns) < 3:
        return {'invalidated': False, 'details': '数据不足（需至少3周）'}

    # 取最近3周
    last_3 = weekly_returns[-3:]

    # 检查条件1: 连续3周跑输基准累计≥3%
    # 这里假设weekly_returns已经是相对基准的超额收益
    cumulative = sum(last_3)

    # 检查条件2: 其中至少2周策略绝对收益为负
    negative_weeks = sum(1 for r in last_3 if r < 0)

    if cumulative <= -3.0 and negative_weeks >= 2:
        return {
            'invalidated': True,
            'details': f'连续3周累计{cumulative:.1f}%（≤-3%），{negative_weeks}周绝对收益为负'
        }

    return {'invalidated': False, 'details': f'最近3周累计{cumulative:.1f}%, {negative_weeks}周为负'}


# ================================================================
# 从回测结果构建排行榜条目
# ================================================================
def build_leaderboard_entry(backtest_result: dict, strategy_info: dict) -> dict:
    """
    从回测结果和策略信息构建排行榜条目。
    
    Args:
        backtest_result: run_backtest.py的输出结果
        strategy_info: 策略元信息（名称、来源、指纹等）
    """
    main = backtest_result.get('main_period', {})
    stress = backtest_result.get('stress_period', {})
    robust = backtest_result.get('cross_period_robust', False)
    bias = backtest_result.get('survivorship_bias_flag', True)

    if not main:
        return None

    # 使用主区间指标
    annual = main.get('mean_annual_return', 0)
    sharpe = main.get('mean_sharpe', 0)
    dd = main.get('mean_max_drawdown', 0)
    pf = main.get('mean_profit_factor', 0)
    wr = main.get('mean_win_rate', 0)
    trades = main.get('mean_avg_trades_per_year', 0)

    # 月度正收益占比（v3新增，回测引擎可能不提供，默认0）
    monthly_positive_rate = main.get('monthly_positive_rate', 0.0)
    # 如果回测结果中没有月度数据，尝试从月度收益序列计算
    monthly_returns = main.get('monthly_returns', None)
    if monthly_returns and len(monthly_returns) > 0 and monthly_positive_rate == 0.0:
        monthly_positive_rate = sum(1 for r in monthly_returns if r > 0) / len(monthly_returns)

    # 计算综合评分（v3）
    score_detail = compute_total_score(
        annual_return=annual,
        sharpe=sharpe,
        max_drawdown=dd,
        profit_factor=pf,
        win_rate=wr,
        cross_period_robust=robust,
        survivorship_bias=bias,
        monthly_positive_rate=monthly_positive_rate,
    )

    # 策略类型
    strategy_type = classify_strategy(
        strategy_info.get('strategy_name', ''),
        strategy_info.get('strategy_code', ''),
        strategy_info.get('description', ''),
    )

    # 硬性条件检查（改革：回撤超标不再一刀切0分，改为扣分标记）
    hard_fail = score_detail.get('max_drawdown_hard_fail', False)
    
    # 只有极端情况（回撤>50%）才归零
    if hard_fail:
        score_detail['total_score'] = 0

    entry = {
        'strategy_name': strategy_info.get('strategy_name', 'Unknown'),
        'source_link': strategy_info.get('source_link', ''),
        'fingerprint': strategy_info.get('fingerprint', ''),
        'fingerprint_short': strategy_info.get('fingerprint', '')[:8],
        'strategy_type': strategy_type,
        'total_score': score_detail['total_score'],
        'grade': score_detail.get('grade', 'F'),
        'score_detail': score_detail,
        # 核心指标
        'annual_return': annual,
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
        'robust_tag': '✅' if robust else '',
        'survivorship_bias': bias,
        'bias_tag': '⚠️' if bias else '',
        'pine_script_rejected': strategy_info.get('pine_script_rejected', False),
        # 元信息
        'portability_score': strategy_info.get('portability_score', 0),
        'backtest_time': backtest_result.get('backtest_time', ''),
        'first_listed_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'removal_reason': '',
        # 压力测试
        'stress_annual': stress.get('mean_annual_return', 0) if stress else 0,
        'stress_dd': stress.get('mean_max_drawdown', 0) if stress else 0,
        # 市场信息
        'market': main.get('market', 'us'),
        'n_stocks': main.get('n_stocks', 0),
    }

    return entry


# ================================================================
# 格式化排行榜表格
# ================================================================
def format_leaderboard_table(leaderboard: list) -> str:
    """格式化排行榜为Markdown表格（含等级标签和完整详细指标）"""
    if not leaderboard:
        return "当前排行榜为空，尚无策略完成回测评分。"

    lines = [
        "| 排名 | 等级 | 策略名称 | 类型 | 市场 | 得分 | 年化收益 | 夏普 | 最大回撤 | 盈亏比 | 胜率 | 年交易次数 | 鲁棒 |",
        "|------|------|---------|------|------|------|---------|------|---------|--------|------|-----------|------|",
    ]

    for i, entry in enumerate(leaderboard, 1):
        name = entry.get('strategy_name', 'Unknown')[:24]
        s_type = entry.get('strategy_type', '其他')
        market = entry.get('market', '?').upper()
        score = entry.get('total_score', 0)
        grade = entry.get('grade', get_grade(score))
        annual = entry.get('annual_return', 0)
        sharpe = entry.get('sharpe', 0)
        dd = entry.get('max_drawdown', 0)
        pf = entry.get('profit_factor', 0)
        wr = entry.get('win_rate', 0)
        trades = entry.get('avg_trades_per_year', 0)
        robust = entry.get('robust_tag', '') or ('✅' if entry.get('cross_period_robust') else '')

        lines.append(
            f"| {i} | {grade} | {name} | {s_type} | {market} | {score} | "
            f"{annual}% | {sharpe} | {dd}% | {pf} | {wr}% | {trades} | {robust} |"
        )

    return '\n'.join(lines)


# ================================================================
# 单元测试
# ================================================================
if __name__ == '__main__':
    # 测试评分
    score = compute_total_score(
        annual_return=22.3,
        sharpe=1.80,
        max_drawdown=15.2,
        profit_factor=1.8,
        win_rate=56.0,
        cross_period_robust=True,
        survivorship_bias=True,
        monthly_positive_rate=0.72,
    )
    print(f"综合评分: {score}")

    # 测试分类
    print(f"EMA交叉分类: {classify_strategy('EMA Crossover Trend Following', 'ema crossover trend')}")
    print(f"RSI回归分类: {classify_strategy('RSI Mean Reversion', 'rsi oversold')}")
    print(f"高股息分类: {classify_strategy('High Dividend Rotation', 'dividend yield rotation')}")

    # 测试排行榜
    lb = load_leaderboard()
    print(f"当前排行榜: {len(lb)}个策略")
    print(format_leaderboard_table(lb))

    # 测试失效判定
    print(f"失效判定(3周亏3%+): {check_strategy_invalidation([-1.5, -0.8, -1.2])}")
    print(f"失效判定(正常): {check_strategy_invalidation([0.5, -0.3, 0.8])}")


# ================================================================
# v5新增：下行风险指标计算
# ================================================================

def calculate_var_cvar(daily_returns: list, confidence: float = 0.95) -> dict:
    """
    计算VaR（在险价值）和CVaR（条件在险价值）
    
    VaR: 在给定置信水平下，投资组合在未来特定时间段内的最大可能损失。
    CVaR: 超过VaR损失的平均值，衡量极端尾部风险。
    
    Args:
        daily_returns: 日收益率列表/数组（小数形式，如0.01=1%）
        confidence: 置信水平（默认0.95，即95%）
    
    Returns:
        {
            'var': VaR值（负数，如-0.015表示95%概率日损失不超过1.5%），
            'cvar': CVaR值（负数，如-0.025表示极端情况平均损失2.5%），
        }
    """
    import numpy as np
    
    if not daily_returns or len(daily_returns) < 20:
        return {'var': None, 'cvar': None}
    
    returns = np.array(daily_returns)
    
    # 历史模拟法
    sorted_returns = np.sort(returns)
    index = int((1 - confidence) * len(sorted_returns))
    index = max(0, min(index, len(sorted_returns) - 1))
    
    var_value = sorted_returns[index]
    
    # CVaR: VaR以左的损失均值
    tail_returns = sorted_returns[:index + 1]
    cvar_value = np.mean(tail_returns) if len(tail_returns) > 0 else var_value
    
    return {
        'var': round(float(var_value), 6),
        'cvar': round(float(cvar_value), 6),
    }


def calculate_ulcer_index(daily_returns: list) -> float:
    """
    计算Ulcer Index（溃疡指数）
    
    衡量回撤的深度和持续时间。比最大回撤更全面，反映"投资者焦虑程度"。
    
    公式：UI = sqrt(sum(max(peak - current, 0)^2 / peak^2) / N) * 100
    
    - UI < 5: 低风险，投资者无需焦虑
    - UI 5-10: 中等风险
    - UI 10-20: 高风险
    - UI > 20: 极高风险
    
    Args:
        daily_returns: 日收益率列表（小数形式）
    
    Returns:
        Ulcer Index值
    """
    import numpy as np
    
    if not daily_returns or len(daily_returns) < 20:
        return None
    
    returns = np.array(daily_returns)
    
    # 构建净值曲线
    equity = np.cumprod(1 + returns)
    
    # 运行最高点
    running_max = np.maximum.accumulate(equity)
    
    # 回撤百分比
    drawdown_pct = (running_max - equity) / running_max
    drawdown_pct = np.nan_to_num(drawdown_pct, nan=0)
    
    # Ulcer Index
    ulcer = np.sqrt(np.mean(drawdown_pct ** 2)) * 100
    
    return round(float(ulcer), 4)


def calculate_walk_forward_score(
    close_prices_df,
    strategy_func,
    strategy_kwargs: dict,
    n_splits: int = 5,
    min_train_years: int = 3,
    market: str = 'US',
) -> dict:
    """
    Walk-Forward滚动窗口分析（防过拟合验证）
    
    将数据分为n_splits个窗口，每个窗口：
    - 训练期（前70%）：策略参数在此区间确定
    - 测试期（后30%）：策略在此区间验证
    
    最终得分 = 测试期平均收益 / 训练期平均收益（越接近1越好，>1说明泛化优秀）
    
    Args:
        close_prices_df: 收盘价DataFrame
        strategy_func: 策略信号函数
        strategy_kwargs: 策略参数
        n_splits: 滚动窗口数（默认5）
        min_train_years: 最小训练期年数（默认3）
        market: 市场代码
    
    Returns:
        {
            'wf_score': 0-1的Walk-Forward得分（1=完美泛化，0=严重过拟合），
            'train_avg_annual': 训练期平均年化，
            'test_avg_annual': 测试期平均年化，
            'train_avg_sharpe': 训练期平均夏普，
            'test_avg_sharpe': 测试期平均夏普，
            'degradation_ratio': 衰减比（test/train，>0.7优秀，0.3-0.7可接受，<0.3过拟合），
            'splits': 各窗口详细结果，
        }
    """
    import numpy as np
    import pandas as pd
    
    try:
        all_dates = close_prices_df.index
        n_total = len(all_dates)
        trading_days_per_year = 252
        min_train_days = min_train_years * trading_days_per_year
        
        if n_total < min_train_days * 2:
            return {'wf_score': None, 'degradation_ratio': None, 'splits': []}
        
        # 滚动窗口分割
        split_size = (n_total - min_train_days) // n_splits
        
        train_annuals = []
        test_annuals = []
        train_sharpes = []
        test_sharpes = []
        splits_detail = []
        
        for split_i in range(n_splits):
            # 训练期：从0到 train_end
            train_end_idx = min_train_days + split_i * split_size
            train_end_idx = min(train_end_idx, n_total - 60)  # 至少保留60天测试
            if train_end_idx >= n_total - 60:
                break
            
            train_dates = all_dates[:train_end_idx]
            test_start_idx = train_end_idx
            test_end_idx = min(test_start_idx + split_size, n_total)
            test_dates = all_dates[test_start_idx:test_end_idx]
            
            if len(test_dates) < 60:
                break
            
            # 训练期回测
            try:
                train_prices = close_prices_df.loc[train_dates]
                train_holding = strategy_func(train_prices, **strategy_kwargs)
                train_holding = train_holding.shift(1).fillna(method='bfill')
                train_returns = _calc_portfolio_returns(train_prices, train_holding, market)
                
                train_annual = _annualized_return(train_returns)
                train_sharpe_val = _sharpe_ratio(train_returns)
                train_annuals.append(train_annual)
                train_sharpes.append(train_sharpe_val)
            except Exception:
                train_annuals.append(0)
                train_sharpes.append(0)
            
            # 测试期回测
            try:
                test_prices = close_prices_df.loc[test_dates]
                test_holding = strategy_func(test_prices, **strategy_kwargs)
                test_holding = test_holding.shift(1).fillna(method='bfill')
                test_returns = _calc_portfolio_returns(test_prices, test_holding, market)
                
                test_annual = _annualized_return(test_returns)
                test_sharpe_val = _sharpe_ratio(test_returns)
                test_annuals.append(test_annual)
                test_sharpes.append(test_sharpe_val)
            except Exception:
                test_annuals.append(0)
                test_sharpes.append(0)
            
            splits_detail.append({
                'split': split_i + 1,
                'train_period': f"{train_dates[0].strftime('%Y-%m-%d') if hasattr(train_dates[0], 'strftime') else str(train_dates[0])} ~ {train_dates[-1].strftime('%Y-%m-%d') if hasattr(train_dates[-1], 'strftime') else str(train_dates[-1])}",
                'test_period': f"{test_dates[0].strftime('%Y-%m-%d') if hasattr(test_dates[0], 'strftime') else str(test_dates[0])} ~ {test_dates[-1].strftime('%Y-%m-%d') if hasattr(test_dates[-1], 'strftime') else str(test_dates[-1])}",
                'train_annual': round(train_annuals[-1], 2),
                'test_annual': round(test_annuals[-1], 2),
                'train_sharpe': round(train_sharpes[-1], 2),
                'test_sharpe': round(test_sharpes[-1], 2),
            })
        
        if not train_annuals:
            return {'wf_score': None, 'degradation_ratio': None, 'splits': []}
        
        # 计算衰减比
        avg_train_annual = np.mean(train_annuals)
        avg_test_annual = np.mean(test_annuals)
        avg_train_sharpe = np.mean(train_sharpes)
        avg_test_sharpe = np.mean(test_sharpes)
        
        # 年化衰减比
        if avg_train_annual > 0:
            degradation_annual = avg_test_annual / avg_train_annual
        else:
            degradation_annual = 0.0
        
        # 夏普衰减比
        if avg_train_sharpe > 0:
            degradation_sharpe = avg_test_sharpe / avg_train_sharpe
        else:
            degradation_sharpe = 0.0
        
        # 综合衰减比（取两者平均）
        degradation_ratio = (degradation_annual + degradation_sharpe) / 2
        degradation_ratio = max(0, min(degradation_ratio, 2.0))  # 限制在0-2之间
        
        # Walk-Forward得分：0-1映射
        # degradation > 0.7 → score=1.0（优秀泛化）
        # degradation 0.5-0.7 → score=0.7（可接受）
        # degradation 0.3-0.5 → score=0.4（轻微过拟合）
        # degradation < 0.3 → score=0.1（严重过拟合）
        if degradation_ratio > 0.7:
            wf_score = min(1.0, degradation_ratio)
        elif degradation_ratio > 0.5:
            wf_score = 0.5 + (degradation_ratio - 0.5) * 2.0  # 0.5-1.0
        elif degradation_ratio > 0.3:
            wf_score = 0.2 + (degradation_ratio - 0.3) * 1.5  # 0.2-0.5
        else:
            wf_score = max(0, degradation_ratio / 0.3 * 0.2)  # 0-0.2
        
        return {
            'wf_score': round(wf_score, 3),
            'train_avg_annual': round(avg_train_annual, 2),
            'test_avg_annual': round(avg_test_annual, 2),
            'train_avg_sharpe': round(avg_train_sharpe, 2),
            'test_avg_sharpe': round(avg_test_sharpe, 2),
            'degradation_ratio': round(degradation_ratio, 3),
            'splits': splits_detail,
        }
        
    except Exception as e:
        return {'wf_score': None, 'degradation_ratio': None, 'splits': [], 'error': str(e)}


# Walk-Forward辅助函数
def _calc_portfolio_returns(close_prices, holding, market='US'):
    """计算组合日收益率序列"""
    import pandas as pd
    
    fees_map = {'US': 0.000528, 'HK': 0.001348, 'CN': 0.0006}
    slippage = 0.001
    fees = fees_map.get(market, 0.000528) + slippage
    
    daily_returns = close_prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=close_prices.index)
    
    prev_asset = None
    for i, date in enumerate(close_prices.index):
        current_asset = holding.iloc[i] if i < len(holding) else None
        if current_asset is not None and current_asset in daily_returns.columns:
            portfolio_returns.iloc[i] = daily_returns.iloc[i].get(current_asset, 0)
        if prev_asset is not None and prev_asset != current_asset:
            portfolio_returns.iloc[i] -= fees
        prev_asset = current_asset
    
    return portfolio_returns


def _annualized_return(daily_returns):
    """计算年化收益率"""
    import numpy as np
    
    if len(daily_returns) < 20:
        return 0.0
    cum = (1 + daily_returns).prod()
    n_years = len(daily_returns) / 252
    if n_years <= 0 or cum <= 0:
        return 0.0
    return (cum ** (1 / n_years) - 1) * 100


def _sharpe_ratio(daily_returns, risk_free_rate=0.045):
    """计算夏普比率"""
    import numpy as np
    
    if len(daily_returns) < 20 or daily_returns.std() == 0:
        return 0.0
    return (daily_returns.mean() - risk_free_rate / 252) / daily_returns.std() * np.sqrt(252)