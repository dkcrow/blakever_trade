"""
经验总结复盘模块（Agent 7）
职责：分析历史交易，提炼可复用经验，维护知识库的"唯一真理"原则。

核心功能：
1. 亏损/盈利交易归因分析
2. 提炼 1-3 条情境化经验条目
3. 矛盾覆盖检查（语义相似度>85%但结论相反→归档旧规则）
4. 知识效期预警（高胜率规则近5笔适用交易连续失败3次→标记待审核降权）
5. 知识库持久化（JSON 文件）
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 知识库持久化路径
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_BASE_FILE = os.path.join(_BASE_DIR, "knowledge_base.json")

# 矛盾覆盖语义相似度阈值
CONFLICT_SIMILARITY_THRESHOLD = 0.85
# 效期预警：连续失败次数
EXPIRATION_CONSECUTIVE_FAILURES = 3
# 效期预警：最近适用交易次数
EXPIRATION_RECENT_TRADES = 5
# 高胜率规则阈值
HIGH_WIN_RATE_THRESHOLD = 0.55


def _load_knowledge_base() -> dict:
    """加载知识库（若不存在则初始化）"""
    if os.path.exists(KNOWLEDGE_BASE_FILE):
        try:
            with open(KNOWLEDGE_BASE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"[ExperienceReview] 知识库加载失败: {e}，重新初始化")

    return {
        'rules': [],
        'metadata': {
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
    }


def _save_knowledge_base(kb: dict):
    """保存知识库到磁盘"""
    kb['metadata']['last_updated'] = datetime.now().isoformat()
    try:
        with open(KNOWLEDGE_BASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"[ExperienceReview] 知识库保存失败: {e}")


def _compute_similarity(text_a: str, text_b: str) -> float:
    """
    简易语义相似度（基于字符级 Jaccard 相似度）。
    生产环境应替换为 embedding cosine similarity。
    """
    set_a = set(text_a.lower())
    set_b = set(text_b.lower())
    if not set_a and not set_b:
        return 1.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _matches_regime(rule: dict, regime: str) -> bool:
    """检查规则的适用行情标签是否匹配"""
    return rule.get('regime_tag', '') == regime


def _update_rule_stats(rule: dict, trade_result: str):
    """更新规则的统计信息（适用次数、胜率）"""
    rule.setdefault('applicable_count', 0)
    rule.setdefault('win_count', 0)
    rule.setdefault('recent_results', [])

    rule['applicable_count'] += 1
    if trade_result == 'win':
        rule['win_count'] += 1

    # 维护最近N笔交易结果
    rule['recent_results'].append(trade_result)
    max_recent = EXPIRATION_RECENT_TRADES
    if len(rule['recent_results']) > max_recent:
        rule['recent_results'] = rule['recent_results'][-max_recent:]

    # 更新胜率
    if rule['applicable_count'] > 0:
        rule['backtest_win_rate'] = round(rule['win_count'] / rule['applicable_count'] * 100, 1)


# ─────────────────────────────────────────────
# 1. 交易归因分析
# ─────────────────────────────────────────────

def analyze_trade_attribution(trade: dict, market_regime: str) -> dict:
    """
    对单笔交易进行归因分析。

    Args:
        trade: {'symbol', 'direction', 'entry_price', 'exit_price',
                'pnl', 'pnl_pct', 'exit_reason', 'duration_days',
                'max_profit_since_entry'(可选), 'atr_at_entry'(可选)}
        market_regime: 牛市/震荡/熊市/高波动恐慌

    Returns:
        {'attribution': str, 'lessons': list[str], 'is_win': bool}
    """
    pnl_pct = float(trade.get('pnl_pct', 0))
    is_win = pnl_pct > 0
    direction = trade.get('direction', 'long')
    exit_reason = trade.get('exit_reason', '未知')
    symbol = trade.get('symbol', '未知')
    duration = trade.get('duration_days', 0)

    lessons = []
    if is_win:
        attribution = f"{symbol} 盈利{pnl_pct:.1f}%（{direction}），持仓{duration}天"
        # 盈利交易归因
        if pnl_pct > 15:
            lessons.append(f"大盈利交易：{direction}方向持仓{duration}天获利{pnl_pct:.1f}%，趋势持有策略有效")
        elif duration < 3 and pnl_pct > 5:
            lessons.append(f"短持仓快速获利：可能是波动交易机会，需确认是否为噪音")
    else:
        attribution = f"{symbol} 亏损{abs(pnl_pct):.1f}%（{direction}），持仓{duration}天，原因={exit_reason}"
        # 亏损归因
        if exit_reason in ('止损', 'stop_loss', '吊灯止损'):
            lessons.append(f"止损触发：入场时机可能过早，需等待更优确认信号")
        elif exit_reason in ('时间止损', 'time_stop'):
            lessons.append(f"时间止损：趋势未如期发展，需重新审视入场逻辑")
        elif abs(pnl_pct) > 10:
            lessons.append(f"大亏损{abs(pnl_pct):.1f}%：风控可能不足或止损位过宽")

        # 方向性归因
        if direction == 'short' and market_regime in ('牛市', '震荡'):
            lessons.append(f"逆势做空：在{market_regime}中做空风险偏高，需更严格的确认")
        elif direction == 'long' and market_regime in ('熊市', '高波动恐慌'):
            lessons.append(f"逆势做多：在{market_regime}中做多需谨慎，考虑降低仓位")

    return {
        'attribution': attribution,
        'lessons': lessons,
        'is_win': is_win
    }


# ─────────────────────────────────────────────
# 2. 提炼经验条目
# ─────────────────────────────────────────────

def extract_insights(recent_trades_analysis: list, market_regime: str) -> list:
    """
    从归因分析中提炼 1-3 条情境化经验条目。

    Args:
        recent_trades_analysis: analyze_trade_attribution 的输出列表
        market_regime:          当前行情标签

    Returns:
        经验条目列表
    """
    # 汇总亏损归因
    loss_lessons = []
    win_lessons = []
    for analysis in recent_trades_analysis:
        if analysis['is_win']:
            win_lessons.extend(analysis.get('lessons', []))
        else:
            loss_lessons.extend(analysis.get('lessons', []))

    # 优先从亏损中提炼（亏损教训更有价值）
    insights = []
    all_lessons = loss_lessons[:2] + win_lessons[:1]  # 最多3条，亏损优先

    for i, lesson in enumerate(all_lessons[:3]):
        insight = {
            'regime_tag': market_regime,
            'content': lesson,
            'failure_condition': f"市场行情转为非{market_regime}状态",
            'backtest_win_rate': None,  # 新经验暂无胜率
            'applicable_count': 0,
            'win_count': 0,
            'recent_results': [],
            'status': '活跃',
            'created_at': datetime.now().isoformat()
        }
        insights.append(insight)

    return insights


# ─────────────────────────────────────────────
# 3. 矛盾覆盖检查
# ─────────────────────────────────────────────

def check_conflict_resolution(new_insights: list, kb: dict) -> list:
    """
    检查新经验与知识库中已有规则是否存在矛盾。
    若语义相似度>85%但结论相反→归档旧规则。

    Returns:
        conflict_resolutions: [{'archived_rule': str, 'new_rule': str}]
    """
    resolutions = []
    existing_rules = [r for r in kb.get('rules', []) if r.get('status') == '活跃']

    for new_rule in new_insights:
        new_content = new_rule.get('content', '')
        new_regime = new_rule.get('regime_tag', '')

        for existing in existing_rules:
            if existing.get('regime_tag') != new_regime:
                continue  # 不同行情标签，不冲突

            existing_content = existing.get('content', '')
            similarity = _compute_similarity(new_content, existing_content)

            if similarity > CONFLICT_SIMILARITY_THRESHOLD:
                # 语义高度相似，检查是否结论相反
                # 简化判断：如果新规则包含"不"/"避免"/"切勿"等否定词，而旧规则不包含→视为结论相反
                negation_words = ['不', '避免', '切勿', '禁止', '不要', '不可']
                new_has_negation = any(w in new_content for w in negation_words)
                old_has_negation = any(w in existing_content for w in negation_words)

                if new_has_negation != old_has_negation:
                    # 结论相反，归档旧规则
                    existing['status'] = '已废止'
                    existing['archived_at'] = datetime.now().isoformat()
                    existing['archived_reason'] = f'与新规则矛盾（相似度={similarity:.2f}）'

                    resolutions.append({
                        'archived_rule': existing_content,
                        'new_rule': new_content,
                        'similarity': round(similarity, 2)
                    })
                    logger.info(f"[ExperienceReview] 矛盾覆盖：归档旧规则「{existing_content[:30]}...」")

    return resolutions


# ─────────────────────────────────────────────
# 4. 知识效期预警
# ─────────────────────────────────────────────

def check_expiration_warnings(kb: dict) -> list:
    """
    检查高胜率规则是否在最近5笔适用交易中连续失败3次。
    若满足→标记 [待审核-疑似失效] 并降权。

    Returns:
        expiration_warnings: [{'rule': str, 'reason': str, 'action': str}]
    """
    warnings = []
    active_rules = [r for r in kb.get('rules', [])
                    if r.get('status') == '活跃'
                    and r.get('backtest_win_rate', 0) is not None
                    and float(r.get('backtest_win_rate', 0)) > HIGH_WIN_RATE_THRESHOLD * 100]

    for rule in active_rules:
        recent = rule.get('recent_results', [])
        if len(recent) >= EXPIRATION_CONSECUTIVE_FAILURES:
            # 检查最近N笔中是否有连续3次失败
            last_n = recent[-EXPIRATION_RECENT_TRADES:]
            consecutive = 0
            max_consecutive = 0
            for r in last_n:
                if r == 'loss':
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0

            if max_consecutive >= EXPIRATION_CONSECUTIVE_FAILURES:
                rule['status'] = '待审核'
                rule['expiration_warning'] = datetime.now().isoformat()

                warning_msg = (f"高胜率规则（胜率={rule.get('backtest_win_rate', '?')}%）"
                               f"近{EXPIRATION_RECENT_TRADES}笔适用交易连续失败{max_consecutive}次")
                warnings.append({
                    'rule': rule.get('content', ''),
                    'reason': warning_msg,
                    'action': '标记待审核并降权'
                })
                logger.warning(f"[ExperienceReview] 知识效期预警: {warning_msg}")

    return warnings


# ─────────────────────────────────────────────
# 5. 完整复盘流程入口
# ─────────────────────────────────────────────

def run_experience_review(recent_closed_trades: list,
                          current_losing_positions: list,
                          current_market_regime: str) -> dict:
    """
    经验总结复盘完整流程。

    Args:
        recent_closed_trades:     最近10笔清仓交易
        current_losing_positions: 当前浮亏超过5%的持仓
        current_market_regime:    牛市/震荡/熊市/高波动恐慌

    Returns:
        与 Agent 7 Prompt 输出格式对齐的完整结果
    """
    kb = _load_knowledge_base()

    # Step 1: 逐笔归因分析
    trade_analyses = []
    for trade in (recent_closed_trades or []):
        try:
            analysis = analyze_trade_attribution(trade, current_market_regime)
            trade_analyses.append(analysis)

            # 更新知识库中匹配规则的统计
            for rule in kb.get('rules', []):
                if rule.get('status') != '活跃':
                    continue
                if _matches_regime(rule, current_market_regime):
                    _update_rule_stats(rule, 'win' if analysis['is_win'] else 'loss')
        except Exception as e:
            logger.error(f"[ExperienceReview] 归因分析失败: {e}")

    # 也对当前亏损持仓做归因（未平仓，标记为 loss）
    for pos in (current_losing_positions or []):
        try:
            pos_trade = {**pos, 'exit_reason': '持仓浮亏中'}
            analysis = analyze_trade_attribution(pos_trade, current_market_regime)
            trade_analyses.append(analysis)
        except Exception as e:
            logger.error(f"[ExperienceReview] 亏损持仓归因失败: {e}")

    # Step 2: 提炼新经验
    new_insights = extract_insights(trade_analyses, current_market_regime)

    # Step 3: 矛盾覆盖检查
    conflict_resolutions = check_conflict_resolution(new_insights, kb)

    # Step 4: 知识效期预警
    expiration_warnings = check_expiration_warnings(kb)

    # Step 5: 将新经验写入知识库
    for insight in new_insights:
        kb.setdefault('rules', []).append(insight)

    # 统计
    active_count = sum(1 for r in kb.get('rules', []) if r.get('status') == '活跃')
    pending_count = sum(1 for r in kb.get('rules', []) if r.get('status') == '待审核')
    archived_count = sum(1 for r in kb.get('rules', []) if r.get('status') == '已废止')

    # 保存知识库
    _save_knowledge_base(kb)

    return {
        'new_insights': new_insights,
        'conflict_resolutions': conflict_resolutions,
        'expiration_warnings': expiration_warnings,
        'knowledge_base_summary': f"当前活跃规则数 {active_count} / 待审核规则数 {pending_count} / 已废止规则数 {archived_count}",
        'trade_analyses': trade_analyses
    }
