"""
CRO仓位公式管理器
基于风险敞口计算最终执行仓位

核心职责：
1. 强制空仓线检查（生存第一）
2. 逐笔仓位计算（凯利公式 + 多重系数）
3. 组合层约束校验（总敞口、行业集中度）
4. 隐性相关性预警
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 1. 强制空仓线检查（最高优先级，生存第一）
# ─────────────────────────────────────────────

def check_force_close(vix: float, vix_daily_change_pct: float,
                      daily_pnl: float, prev_daily_pnl: float,
                      account_equity: float,
                      proposed_trades: list = None) -> dict:
    """
    检查是否触发强制空仓线。
    2026-04-23改造：VIX>35不再强制全部空仓，而是禁止风险资产开仓、允许安全资产(SHY/AGG)。
    只有连续2日回撤>3%才是真正的强制空仓（force_close=True）。

    触发条件：
    - 连续2日回撤均 > 3% → force_close=True（禁止一切开仓，包括安全资产）
    - VIX > 35 → risk_asset_close=True（禁止风险资产，允许安全资产）
    - VIX 单日涨幅 > 20% → risk_asset_close=True（禁止风险资产，允许安全资产）

    Returns:
        {
            'force_close': bool,          # True=禁止一切开仓（仅连续回撤触发）
            'risk_asset_close': bool,     # True=仅禁止风险资产开仓（VIX触发）
            'triggered_rules': list[str],
            'vix_risk_level': str
        }
    """
    triggered = []
    risk_asset_close = False

    # 规则1：VIX绝对值过高 → 仅禁止风险资产，允许安全资产
    if vix > 35:
        risk_asset_close = True
        triggered.append(f"VIX={vix:.1f} 超过35阈值，禁止风险资产开仓（安全资产仍可配置）")

    # 规则2：VIX单日暴涨 → 仅禁止风险资产
    if vix_daily_change_pct > 20:
        risk_asset_close = True
        triggered.append(f"VIX单日涨幅={vix_daily_change_pct:.1f}% 超过20%，禁止风险资产开仓")

    # 规则3：连续2日回撤 > 3% → 真正的强制空仓（唯一force_close触发条件）
    force_close_triggered = False
    threshold = account_equity * 0.03
    if account_equity > 0 and daily_pnl < -threshold and prev_daily_pnl < -threshold:
        d1_pct = abs(daily_pnl) / account_equity * 100
        d2_pct = abs(prev_daily_pnl) / account_equity * 100
        force_close_triggered = True
        triggered.append(
            f"连续2日回撤超3%（今日={d1_pct:.1f}%，昨日={d2_pct:.1f}%），触发强制空仓线"
        )

    # VIX风险等级
    if vix > 40:
        vix_risk_level = "极高"
    elif vix > 30:
        vix_risk_level = "高"
    elif vix > 20:
        vix_risk_level = "中"
    else:
        vix_risk_level = "低"

    result = {
        'force_close': force_close_triggered,
        'risk_asset_close': risk_asset_close,
        'triggered_rules': triggered,
        'vix_risk_level': vix_risk_level
    }
    if result['force_close']:
        logger.warning(f"[CRO] 强制空仓线触发: {triggered}")
    return result


# ─────────────────────────────────────────────
# 2. 逐笔仓位计算
# ─────────────────────────────────────────────

def calculate_position(account_equity: float, entry_price: float, stop_loss: float,
                       market_cap_type: str = 'large', sentiment_factor: float = 1.0,
                       fomo_factor: float = 1.0, is_short: bool = False,
                       current_industry_exposure: float = 0.0,
                       industry: Optional[str] = None) -> dict:
    """
    计算单笔交易的最终执行仓位上限。

    Args:
        account_equity:             账户净值
        entry_price:                入场价
        stop_loss:                  止损价
        market_cap_type:            市值类型 'large'/'mid'/'small'
        sentiment_factor:           情绪系数（来自 Agent 2，范围 0.5~1.5）
        fomo_factor:                踏空系数（主调度器根据行情强度设定，范围 0.8~1.2）
        is_short:                   是否做空
        current_industry_exposure:  当前该行业已有敞口金额
        industry:                   行业标签

    Returns:
        {
            'approved_amount': float,
            'kelly_raw': float,
            'risk_per_share': float,
            'impact_factor': float,
            'reason': str
        }
    """
    # ── 输入校验 ──
    try:
        account_equity = float(account_equity)
        entry_price = float(entry_price)
        stop_loss = float(stop_loss)
        sentiment_factor = float(sentiment_factor)
        fomo_factor = float(fomo_factor)
        current_industry_exposure = float(current_industry_exposure)
    except (TypeError, ValueError) as e:
        logger.error(f"[CRO] 参数类型错误: {e}")
        return {'approved_amount': 0, 'kelly_raw': 0, 'risk_per_share': 0,
                'impact_factor': 1.0, 'reason': f'参数类型错误: {e}'}

    if account_equity <= 0:
        return {'approved_amount': 0, 'kelly_raw': 0, 'risk_per_share': 0,
                'impact_factor': 1.0, 'reason': '账户净值必须为正'}
    if entry_price <= 0 or stop_loss <= 0:
        return {'approved_amount': 0, 'kelly_raw': 0, 'risk_per_share': 0,
                'impact_factor': 1.0, 'reason': '价格必须为正'}

    # 做多时止损必须低于入场价，做空时止损必须高于入场价
    if not is_short and stop_loss >= entry_price:
        return {'approved_amount': 0, 'kelly_raw': 0, 'risk_per_share': 0,
                'impact_factor': 1.0, 'reason': '多头止损价必须低于入场价'}
    if is_short and stop_loss <= entry_price:
        return {'approved_amount': 0, 'kelly_raw': 0, 'risk_per_share': 0,
                'impact_factor': 1.0, 'reason': '空头止损价必须高于入场价'}

    # ── 市场冲击系数 ──
    impact_map = {'large': 1.0, 'mid': 1.2, 'small': 1.5}
    impact = impact_map.get(market_cap_type, 1.2)

    risk_per_share = abs(entry_price - stop_loss) * impact
    if risk_per_share <= 0:
        return {'approved_amount': 0, 'kelly_raw': 0, 'risk_per_share': 0,
                'impact_factor': impact, 'reason': '无效止损价'}

    # ── 凯利公式：单笔风险敞口 = 净值2%，单票上限5% ──
    # 先计算可承受风险金额
    max_risk_amount = account_equity * 0.02  # 单笔最大亏损 = 净值2%
    max_position_amount = account_equity * 0.05  # 单票最大仓位 = 净值5%

    # 计算可买股数 = 可承受风险 / 每股风险
    kelly_shares = max_risk_amount / risk_per_share
    # 转换为金额
    kelly_amount = kelly_shares * entry_price

    # 金额上限约束
    kelly_amount = min(kelly_amount, max_position_amount, 1_000_000)  # 单票持仓市值硬性上限100万

    # ── 情绪系数和踏空系数（限制范围防止极端值） ──
    sentiment_factor = max(0.3, min(1.5, sentiment_factor))
    fomo_factor = max(0.5, min(1.5, fomo_factor))
    adjusted = kelly_amount * sentiment_factor * fomo_factor

    # ── 做空折价 ──
    if is_short:
        adjusted *= 0.7

    # ── 行业集中度约束（单一行业 ≤ 净值20%） ──
    max_industry_allowed = account_equity * 0.20
    industry_capped = False
    if industry and current_industry_exposure + adjusted > max_industry_allowed:
        adjusted = max(0.0, max_industry_allowed - current_industry_exposure)
        industry_capped = True
        logger.info(f"[CRO] {industry} 行业集中度约束触发，仓位削减至 {adjusted:.2f}")

    reason = '行业集中度超限，仓位已削减' if industry_capped else 'OK'
    if adjusted <= 0:
        reason = '行业集中度超限，无可用额度'

    return {
        'approved_amount': round(adjusted, 2),
        'kelly_raw': round(kelly_amount, 2),
        'risk_per_share': round(risk_per_share, 2),
        'impact_factor': impact,
        'kelly_shares': round(kelly_shares, 2),
        'reason': reason
    }


# ─────────────────────────────────────────────
# 3. 组合层约束校验
# ─────────────────────────────────────────────

def validate_portfolio_risk(account_equity: float,
                             proposed_trades: list,
                             current_positions: list) -> dict:
    """
    组合层风险校验，在逐笔计算完成后执行。

    校验规则：
    - 所有新开仓潜在亏损合计 ≤ 净值5%
    - 单一行业仓位（现有 + 新增）≤ 净值20%
    - 总敞口（现有 + 新增）≤ 净值80%

    Args:
        account_equity:    账户净值
        proposed_trades:   逐笔计算后的拟开仓列表，每项需含：
                           {'symbol', 'approved_amount', 'entry_price', 'stop_loss', 'industry'}
        current_positions: 当前持仓列表，每项需含：
                           {'symbol', 'industry', 'current_value'}

    Returns:
        {
            'passed': bool,
            'total_potential_loss': float,
            'total_potential_loss_pct': float,
            'total_exposure_pct': float,
            'industry_warnings': list[str],
            'rejected_symbols': list[str],   # 因组合层约束被拒绝的标的
            'notes': str
        }
    """
    if account_equity <= 0:
        return {'passed': False, 'total_potential_loss': 0, 'total_potential_loss_pct': 0,
                'total_exposure_pct': 0, 'industry_warnings': [], 'rejected_symbols': [],
                'notes': '账户净值无效'}

    # 统计现有持仓的行业敞口
    industry_exposure = {}
    total_current_exposure = 0.0
    for pos in (current_positions or []):
        ind = pos.get('industry', '未知')
        val = float(pos.get('current_value', 0))
        industry_exposure[ind] = industry_exposure.get(ind, 0) + val
        total_current_exposure += val

    # 逐笔计算新增潜在亏损和行业敞口
    total_potential_loss = 0.0
    total_new_exposure = 0.0
    industry_warnings = []
    rejected_symbols = []
    notes_list = []

    for trade in (proposed_trades or []):
        symbol = trade.get('symbol', '未知')
        amount = float(trade.get('approved_amount', 0))
        entry = float(trade.get('entry_price', 0))
        stop = float(trade.get('stop_loss', 0))
        ind = trade.get('industry', '未知')

        if amount <= 0 or entry <= 0:
            continue

        # 潜在亏损 = 仓位金额 × 止损幅度
        stop_pct = abs(entry - stop) / entry if entry > 0 else 0.02
        potential_loss = amount * stop_pct
        total_potential_loss += potential_loss
        total_new_exposure += amount

        # 行业集中度检查
        new_industry_total = industry_exposure.get(ind, 0) + amount
        if new_industry_total > account_equity * 0.20:
            warning = (f"{symbol}({ind}) 加入后行业敞口={new_industry_total:.0f}，"
                       f"超过净值20%={account_equity*0.20:.0f}")
            industry_warnings.append(warning)
            rejected_symbols.append(symbol)
            logger.warning(f"[CRO] 组合层行业集中度超限: {warning}")
        else:
            industry_exposure[ind] = new_industry_total

    # 总潜在亏损检查（≤ 净值5%）
    loss_pct = total_potential_loss / account_equity * 100
    if loss_pct > 5.0:
        notes_list.append(f"新开仓总潜在亏损={loss_pct:.1f}%，超过净值5%上限，建议削减仓位")
        logger.warning(f"[CRO] 组合层总潜在亏损超限: {loss_pct:.1f}%")

    # 总敞口检查（≤ 净值80%）
    total_exposure = total_current_exposure + total_new_exposure
    exposure_pct = total_exposure / account_equity * 100
    if exposure_pct > 80.0:
        notes_list.append(f"总敞口={exposure_pct:.1f}%，超过净值80%上限")
        logger.warning(f"[CRO] 组合层总敞口超限: {exposure_pct:.1f}%")

    passed = loss_pct <= 5.0 and exposure_pct <= 80.0 and len(rejected_symbols) == 0

    return {
        'passed': passed,
        'total_potential_loss': round(total_potential_loss, 2),
        'total_potential_loss_pct': round(loss_pct, 2),
        'total_exposure_pct': round(exposure_pct, 2),
        'industry_warnings': industry_warnings,
        'rejected_symbols': rejected_symbols,
        'notes': '；'.join(notes_list) if notes_list else 'OK'
    }


# ─────────────────────────────────────────────
# 4. 隐性相关性预警
# ─────────────────────────────────────────────

# 预定义的隐性相关性组（同组标的在极端行情下高度联动）
_CORRELATION_GROUPS = [
    {'name': '美股科技巨头', 'keywords': ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA']},
    {'name': '美股半导体', 'keywords': ['NVDA', 'AMD', 'INTC', 'QCOM', 'AMAT', 'AVGO', 'LRCX', 'KLAC', 'MRVL', 'ON']},
    {'name': '美股金融', 'keywords': ['JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK', 'SCHW', 'AXP', 'V', 'MA']},
    {'name': '港股科技', 'keywords': ['0700.HK', '9988.HK', '3690.HK', '9618.HK', '9888.HK', '9999.HK', '1024.HK', '1810.HK']},
    {'name': '港股金融', 'keywords': ['0005.HK', '1299.HK', '2388.HK', '0388.HK', '1398.HK', '3988.HK', '2628.HK', '1288.HK', '3328.HK', '0939.HK', '2318.HK', '3968.HK']},
    {'name': '港股互联网医疗', 'keywords': ['0241.HK', '6618.HK', '6060.HK']},
    {'name': '新能源汽车(港股)', 'keywords': ['1211.HK', '2015.HK', '9866.HK', '9868.HK', '0285.HK']},
    {'name': '港股房地产', 'keywords': ['0016.HK', '0012.HK', '0017.HK', '0101.HK', '0688.HK', '1109.HK', '1113.HK', '2007.HK', '0960.HK']},
    {'name': '港股石油能源', 'keywords': ['0883.HK', '0386.HK', '0857.HK']},
    {'name': '美股中概股', 'keywords': ['BABA', 'JD', 'PDD', 'BIDU', 'NIO', 'XPEV', 'LI']},
    {'name': '港股生物制药', 'keywords': ['2269.HK', '1177.HK', '1093.HK', '2359.HK']},
    {'name': '港股消费', 'keywords': ['2020.HK', '9633.HK', '6862.HK', '1876.HK', '0291.HK']},
]

def detect_hidden_correlation(proposed_symbols: list, current_symbols: list) -> dict:
    """
    检测拟开仓标的与现有持仓之间的隐性相关性。

    Args:
        proposed_symbols: 拟开仓标的代码列表
        current_symbols:  当前持仓标的代码列表

    Returns:
        {
            'warnings': list[str],
            'correlated_groups': list[dict]  # 触发预警的相关性组
        }
    """
    all_symbols = set(s.upper() for s in (proposed_symbols or []))
    existing_symbols = set(s.upper() for s in (current_symbols or []))
    combined = all_symbols | existing_symbols

    warnings = []
    correlated_groups = []

    for group in _CORRELATION_GROUPS:
        matched = [s for s in combined if any(k.upper() in s or s in k.upper() for k in group['keywords'])]
        # 新增标的中有属于该组的
        new_in_group = [s for s in all_symbols if any(k.upper() in s or s in k.upper() for k in group['keywords'])]
        existing_in_group = [s for s in existing_symbols if any(k.upper() in s or s in k.upper() for k in group['keywords'])]

        if new_in_group and existing_in_group:
            msg = (f"[隐性相关性预警] {group['name']}：拟新增 {new_in_group}，"
                   f"现有持仓已含 {existing_in_group}，极端行情下可能同向大幅波动")
            warnings.append(msg)
            correlated_groups.append({
                'group_name': group['name'],
                'new_symbols': new_in_group,
                'existing_symbols': existing_in_group
            })
            logger.warning(f"[CRO] {msg}")

    return {
        'warnings': warnings,
        'correlated_groups': correlated_groups
    }


# ─────────────────────────────────────────────
# 5. CRO 完整流程入口（供主调度器调用）
# ─────────────────────────────────────────────

def run_cro_full_check(account_equity: float,
                       current_positions: list,
                       proposed_trades: list,
                       market_environment: dict,
                       daily_pnl: float = 0.0,
                       prev_daily_pnl: float = 0.0,
                       low_confidence_discount: float = 1.0) -> dict:
    """
    CRO 完整风控流程：强制空仓线 → 逐笔计算 → 组合层校验 → 相关性预警。

    Args:
        account_equity:      账户净值
        current_positions:   当前持仓列表
        proposed_trades:     拟开仓列表（含 entry_price, stop_loss, market_cap_type,
                             industry, direction 等字段）
        market_environment:  {'vix', 'vix_daily_change_pct', 'sentiment_factor',
                              'macro_liquidity_warning', 'fomo_factor'(可选)}
        daily_pnl:           今日盈亏
        prev_daily_pnl:      昨日盈亏
        low_confidence_discount: 低置信度折扣系数（默认1.0不打折，置信度<60%时为0.5）

    Returns:
        完整 CRO 输出，与 Agent 0 Prompt 输出格式对齐
    """
    vix = float(market_environment.get('vix', 0))
    vix_change = float(market_environment.get('vix_daily_change_pct', 0))
    sentiment_factor = float(market_environment.get('sentiment_factor', 1.0))
    fomo_factor = float(market_environment.get('fomo_factor', 1.0))

    # Step 1: 强制空仓线检查（2026-04-23改造：区分force_close和risk_asset_close）
    force_check = check_force_close(vix, vix_change, daily_pnl, prev_daily_pnl, account_equity)
    if force_check['force_close']:
        # 连续2日回撤>3%：真正强制空仓，禁止一切开仓
        return {
            'force_close_only': True,
            'triggered_rules': force_check['triggered_rules'],
            'vix_risk_level': force_check['vix_risk_level'],
            'approved_trades': [],
            'total_exposure_usage_pct': 0,
            'industry_concentration_warnings': [],
            'hidden_correlation_warnings': [],
            'notes': '强制空仓线触发（连续回撤），禁止一切新开仓'
        }

    # risk_asset_close=True时，过滤掉风险资产，仅保留安全资产
    # 安全资产列表（与blakever_trade_strategy.py中的SAFE_ASSETS保持一致）
    SAFE_ASSETS = {'AGG', 'SHY', 'BND', 'TLT', 'IEF', 'VGIT', 'VGSH'}
    if force_check.get('risk_asset_close'):
        filtered_trades = []
        for trade in (proposed_trades or []):
            symbol = trade.get('symbol', '')
            # 安全资产放行
            if symbol in SAFE_ASSETS:
                filtered_trades.append(trade)
            # 左侧试探（entry_type='左侧试探'）也放行（额度已限制在净值2%以内）
            elif trade.get('entry_type') == '左侧试探':
                filtered_trades.append(trade)
            else:
                logger.info(f"[CRO] VIX>35风险资产限制: 跳过 {symbol}")
        proposed_trades = filtered_trades

    # Step 2: 逐笔仓位计算
    # 统计各行业现有敞口
    industry_exposure_map = {}
    for pos in (current_positions or []):
        ind = pos.get('industry', '未知')
        val = float(pos.get('current_value', 0))
        industry_exposure_map[ind] = industry_exposure_map.get(ind, 0) + val

    approved_trades = []
    for trade in (proposed_trades or []):
        ind = trade.get('industry', '未知')
        current_exp = industry_exposure_map.get(ind, 0)
        result = calculate_position(
            account_equity=account_equity,
            entry_price=float(trade.get('entry_price', 0)),
            stop_loss=float(trade.get('stop_loss', 0)),
            market_cap_type=trade.get('market_cap_type', 'large'),
            sentiment_factor=sentiment_factor,
            fomo_factor=fomo_factor,
            is_short=(trade.get('direction', 'long') == 'short'),
            current_industry_exposure=current_exp,
            industry=ind
        )
        suggested = float(trade.get('suggested_amount', result['approved_amount']))

        # 应用低置信度折扣（2026-04-23新增：限流不熔断）
        original_amount = result['approved_amount']
        discounted_amount = original_amount * low_confidence_discount
        if low_confidence_discount < 1.0:
            logger.info(f"[CRO] 低置信度折扣: {trade.get('symbol')} "
                        f"{original_amount:.0f} × {low_confidence_discount} = {discounted_amount:.0f}")

        intervention = None
        if discounted_amount < suggested * 0.95:
            reasons = []
            if low_confidence_discount < 1.0:
                reasons.append(f"低置信度×{low_confidence_discount}")
            if original_amount < suggested * 0.95:
                reasons.append(result['reason'])
            intervention = (f"风控干预：原建议 {suggested:.0f}，"
                            f"调整后 {discounted_amount:.0f}（{'；'.join(reasons)}）")

        approved_trades.append({
            'symbol': trade.get('symbol'),
            'direction': trade.get('direction', 'long'),
            'approved_amount': round(discounted_amount, 2),
            'kelly_raw': result['kelly_raw'],
            'risk_per_share': result['risk_per_share'],
            'intervention_reason': intervention or result['reason']
        })
        # 更新行业敞口（用于后续标的的约束计算）
        industry_exposure_map[ind] = current_exp + discounted_amount

    # Step 3: 组合层校验
    # 将 approved_trades 补充 entry_price/stop_loss/industry 供组合层使用
    trades_for_portfolio = []
    for i, trade in enumerate(proposed_trades or []):
        if i < len(approved_trades):
            trades_for_portfolio.append({
                **trade,
                'approved_amount': approved_trades[i]['approved_amount']
            })
    portfolio_check = validate_portfolio_risk(account_equity, trades_for_portfolio, current_positions)

    # Step 4: 隐性相关性预警
    proposed_symbols = [t.get('symbol') for t in (proposed_trades or [])]
    current_symbols = [p.get('symbol') for p in (current_positions or [])]
    correlation_check = detect_hidden_correlation(proposed_symbols, current_symbols)

    # 计算总敞口使用率
    total_current = sum(float(p.get('current_value', 0)) for p in (current_positions or []))
    total_new = sum(t['approved_amount'] for t in approved_trades)
    exposure_pct = (total_current + total_new) / account_equity * 100 if account_equity > 0 else 0

    return {
        'force_close_only': False,
        'vix_risk_level': force_check['vix_risk_level'],
        'approved_trades': approved_trades,
        'total_exposure_usage_pct': round(exposure_pct, 2),
        'portfolio_risk_check': portfolio_check,
        'industry_concentration_warnings': portfolio_check['industry_warnings'],
        'hidden_correlation_warnings': correlation_check['warnings'],
        'notes': portfolio_check['notes']
    }