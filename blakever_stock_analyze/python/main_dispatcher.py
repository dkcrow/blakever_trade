"""
主调度器（Blakever）
职责：协调所有子 Agent，发布最终《每日操作建议指南》。

调用顺序（与主Agent Prompt 对齐）：
1. Agent 2（宏观叙事）→ 获取情绪因子与流动性预警
2. Agent 1（市场行情判断）→ 获取行情定性和置信度
3. 低置信度限流（2026-04-23改造：Panic不再熔断，GEM Panic模式自动全仓安全资产；置信度<60%时CRO额外打×0.5折扣）
4. 调用统一GEM双动量轮动策略（贯穿牛熊），根据行情定性调整风险/安全资产配置权重
5. 将候选标的提交 Agent 0（CRO）计算最终仓位（含低置信度折扣）
6. 执行反向测试辩论庭
7. 评估是否触发左侧捡漏权限（Panic时也可触发）
8. 结合 Agent 7 经验库进行终审
9. 生成《每日操作建议指南》，发送给 Agent 6 执行

唯一安全阀：CRO的force_close_only（账户净值跌破强制空仓线）
"""

import logging
from datetime import datetime
from typing import Optional

from data_fetcher import fetch_ohlcv, fetch_vix_data, fetch_macro_data, extract_current_prices, extract_avg_daily_volumes
from market_analyze import analyze_market, analyze_market_with_confirmation
from cro_mgr import run_cro_full_check, check_force_close
from blakever_trade_strategy import execute_trade_strategy
from fool_trader import run_execution, paper_trader_positions, paper_trader_settle
from experience_review import run_experience_review

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 持仓价格刷新（核心修复：确保报告中的现价是最新的）
# ─────────────────────────────────────────────

def refresh_position_prices(current_positions: list,
                             current_prices: dict,
                             price_deviation_threshold: float = 0.02) -> list:
    """
    用最新行情价格刷新 current_positions 中的 current_price，并同步回写 paper-trader。

    修复根因：主Agent传入的 current_positions 可能包含过期价格（甚至编造的价格），
    导致报告中的"现价"严重偏离实际。此函数强制用从行情数据中提取的最新价格覆盖。

    Args:
        current_positions: 外部传入的持仓列表，可能包含过期价格
        current_prices: 从行情数据提取的最新价格字典 {'USMSFT': 420.5, ...}
        price_deviation_threshold: 价格偏差阈值(默认2%)，超过则报警

    Returns:
        刷新后的 current_positions（原地修改并返回）
    """
    if not current_positions or not current_prices:
        return current_positions

    refreshed_count = 0
    deviation_warnings = []

    for pos in current_positions:
        symbol = pos.get('symbol', '')
        old_price = float(pos.get('current_price', 0))

        # 尝试在 current_prices 中查找该标的的最新价格
        new_price = None

        # 直接匹配
        if symbol in current_prices:
            new_price = current_prices[symbol]
        # 去掉市场前缀匹配（如 USMSFT → MSFT）
        elif symbol.startswith('US') and symbol[2:] in current_prices:
            new_price = current_prices[symbol[2:]]
        elif symbol.startswith('HK') and symbol in current_prices:
            new_price = current_prices[symbol]

        if new_price is not None and new_price > 0:
            # 检测价格偏差
            if old_price > 0:
                deviation = abs(new_price - old_price) / old_price
                if deviation > price_deviation_threshold:
                    warning = (f"⚠️ {symbol} 价格偏差{deviation:.1%}: "
                               f"旧价={old_price:.2f} → 新价={new_price:.2f}")
                    deviation_warnings.append(warning)
                    logger.warning(f"[Dispatcher] {warning}")

            # 更新持仓中的现价
            pos['current_price'] = round(new_price, 2)

            # 重新计算浮盈和盈亏%
            entry_price = float(pos.get('entry_price', 0))
            quantity = float(pos.get('quantity', 0))
            if entry_price > 0 and quantity > 0:
                pos['pnl'] = round((new_price - entry_price) * quantity, 2)
                pos['pnl_pct'] = round((new_price - entry_price) / entry_price * 100, 2)
                pos['position_size'] = round(entry_price * quantity, 2)
                pos['current_value'] = round(new_price * quantity, 2)

            refreshed_count += 1

    if refreshed_count > 0:
        logger.info(f"[Dispatcher] ✅ 刷新了 {refreshed_count}/{len(current_positions)} 只持仓的最新价格")

    if deviation_warnings:
        logger.warning(f"[Dispatcher] 🚨 发现 {len(deviation_warnings)} 只持仓价格偏差超过阈值！")
        for w in deviation_warnings:
            logger.warning(f"  {w}")

    # 回写 paper-trader：用最新价格做一次结算（更新 positions.json 中的现价和P&L）
    try:
        settle_prices = {}
        for pos in current_positions:
            symbol = pos.get('symbol', '')
            cp = float(pos.get('current_price', 0))
            if cp > 0:
                settle_prices[symbol] = cp
        if settle_prices:
            settle_result = paper_trader_settle(settle_prices)
            if settle_result.get('has_critical_anomaly'):
                logger.warning("[Dispatcher] 🚨 paper-trader结算发现严重数据异常！")
            logger.info(f"[Dispatcher] ✅ 已将最新价格回写到 paper-trader ({len(settle_prices)}只)")
    except Exception as e:
        logger.warning(f"[Dispatcher] ⚠️ 回写 paper-trader 失败（不影响主流程）: {e}")

    return current_positions


# ─────────────────────────────────────────────
# Agent 2：宏观叙事分析（纯规则，无需独立模块）
# ─────────────────────────────────────────────

LIQUIDITY_KEYWORDS = [
    'FRA-OIS利差飙升', '美债流动性枯竭', '美联储紧急注入流动性', '信用利差急剧扩大',
    '流动性危机', '融资困难', '银行间利率飙升'
]

PANIC_KEYWORDS = [
    '暴跌', '崩盘', '恐慌性抛售', '黑天鹅', '紧急降息', '熔断'
]


def analyze_macro_narrative(vix_df, news_summary: str = '',
                             tnx_df=None) -> dict:
    """
    宏观叙事分析（Agent 2），纯规则判断。
    从 VIX 和新闻摘要中提取情绪因子与流动性预警。

    Returns:
        {
            'sentiment_factor': float,       # -1.0 ~ +1.0
            'macro_liquidity_warning': bool,
            'liquidity_keywords_detected': list,
            'key_events': str
        }
    """
    # 默认值
    sentiment_factor = 0.0
    vix_value = 0.0
    vix_change_pct = 0.0

    if vix_df is not None and not vix_df.empty:
        try:
            latest = vix_df.iloc[-1]
            vix_value = float(latest['close'])
            if len(vix_df) > 1:
                prev_vix = float(vix_df.iloc[-2]['close'])
                if prev_vix > 0:
                    vix_change_pct = (vix_value - prev_vix) / prev_vix * 100
        except Exception as e:
            logger.warning(f"[MacroNarrative] VIX 数据处理失败: {e}")

    # 情绪因子计算
    if vix_value > 35 or vix_change_pct > 20:
        sentiment_factor = -1.0
    elif vix_value > 25 or vix_change_pct > 10:
        sentiment_factor = -0.5
    elif vix_value < 15 and vix_change_pct < -5:
        sentiment_factor = 0.8
    elif vix_value < 20:
        sentiment_factor = 0.5
    else:
        sentiment_factor = 0.0

    # 新闻关键词扫描
    liquidity_detected = []
    panic_detected = []
    if news_summary:
        for kw in LIQUIDITY_KEYWORDS:
            if kw in news_summary:
                liquidity_detected.append(kw)
                sentiment_factor = min(sentiment_factor, -0.5)
        for kw in PANIC_KEYWORDS:
            if kw in news_summary:
                panic_detected.append(kw)
                sentiment_factor = min(sentiment_factor, -0.8)

    # 流动性预警
    macro_liquidity_warning = len(liquidity_detected) > 0 or vix_value > 30

    # 关键事件摘要
    key_events_parts = []
    if vix_value > 25:
        key_events_parts.append(f"VIX={vix_value:.1f}处于高位")
    if liquidity_detected:
        key_events_parts.append(f"流动性预警: {', '.join(liquidity_detected)}")
    if panic_detected:
        key_events_parts.append(f"恐慌信号: {', '.join(panic_detected)}")
    if not key_events_parts:
        key_events_parts.append("市场情绪平稳" if vix_value < 20 else "市场情绪偏谨慎")
    key_events = '；'.join(key_events_parts)

    return {
        'sentiment_factor': round(sentiment_factor, 2),
        'macro_liquidity_warning': macro_liquidity_warning,
        'liquidity_keywords_detected': liquidity_detected,
        'key_events': key_events
    }


# ─────────────────────────────────────────────
# 反向测试辩论庭
# ─────────────────────────────────────────────

def run_adversarial_debate(candidates: list, index_df=None) -> list:
    """
    反向测试辩论庭：针对 Top 3 候选标的，计算错误概率和最终置信度。

    错误概率精细规则：
    - 基础值 20%
    - 高位（价格>近60日高点90%分位）：+10%
    - 低位（价格<近60日低点10%分位）：-5%
    - 放量突破（成交量>1.5倍均量）：+5%
    - 缩量突破（成交量<0.7倍均量）：+10%
    - 财报发布周：额外+10%
    - 上限40%，下限10%
    """
    debatable = candidates[:3]  # Top 3
    results = []

    for candidate in debatable:
        df = candidate.get('df')
        confidence = candidate.get('confidence', 50)
        error_prob = 20  # 基础值20%

        if df is not None and not df.empty:
            try:
                latest = df.iloc[-1]
                close = latest['close']
                high_60 = df['high'].tail(60).max() if len(df) >= 60 else close
                low_60 = df['low'].tail(60).min() if len(df) >= 60 else close
                volume = latest.get('volume', 0)
                vol_ma20 = latest.get('volume_ma20', volume)

                # 高位检查
                if close > high_60 * 0.90:
                    error_prob += 10

                # 低位检查
                if close < low_60 * 1.10:
                    error_prob -= 5

                # 放量/缩量突破
                if vol_ma20 > 0:
                    vol_ratio = volume / vol_ma20
                    if vol_ratio > 1.5:
                        error_prob += 5
                    elif vol_ratio < 0.7:
                        error_prob += 10

                # 财报发布周（简化：无法自动检测，由外部传入）
                if candidate.get('earnings_week', False):
                    error_prob += 10

            except Exception as e:
                logger.warning(f"[Debate] {candidate.get('symbol')} 辩论计算失败: {e}")

        # 限制范围
        error_prob = max(10, min(40, error_prob))
        final_confidence = confidence * (1 - error_prob / 100)

        results.append({
            **{k: v for k, v in candidate.items() if k != 'df'},
            'error_probability': error_prob,
            'original_confidence': confidence,
            'final_confidence': round(final_confidence, 1),
            'debate_verdict': '通过' if final_confidence >= 50 else '否决'
        })

    return results


# ─────────────────────────────────────────────
# 左侧捡漏权限评估
# ─────────────────────────────────────────────

def evaluate_contrarian_entry(market_environment: dict, candidates: list,
                               account_equity: float) -> list:
    """
    左侧捡漏权限评估（需同时满足3个条件）：
    1. VIX > 35
    2. 当日 VIX 收盘低于开盘（长上影线）
    3. 候选标的当日成交量 ≥ 近20日均量的 2.0 倍

    批准后总额 ≤ 账户净值2%，且必须计入 CRO 组合层约束。
    """
    vix = float(market_environment.get('vix', 0))
    vix_open = float(market_environment.get('vix_open', 0))
    vix_close = float(market_environment.get('vix_close', vix))

    # 条件1：VIX > 35
    if vix <= 35:
        return []

    # 条件2：VIX 收盘低于开盘（长上影线）
    if vix_open <= 0 or vix_close >= vix_open:
        return []

    # 条件3：逐个检查候选标的
    contrarian_entries = []
    total_approved = 0.0
    max_total = account_equity * 0.02  # 总额不超过净值2%

    for candidate in candidates:
        df = candidate.get('df')
        if df is None or df.empty:
            continue

        try:
            latest = df.iloc[-1]
            volume = float(latest.get('volume', 0))
            vol_ma20 = float(latest.get('volume_ma20', 0))

            if vol_ma20 <= 0 or volume < vol_ma20 * 2.0:
                continue  # 成交量不足2倍

            # 满足所有条件，计算左侧仓位
            price = float(latest['close'])
            atr = float(latest.get('atr20', price * 0.02))
            single_limit = account_equity * 0.01  # 单票不超过1%
            remaining = max_total - total_approved
            if remaining <= 0:
                break

            amount = min(single_limit, remaining)
            stop_loss = price - 2.0 * atr  # 左侧止损更宽（2倍ATR）

            contrarian_entries.append({
                'symbol': candidate['symbol'],
                'direction': 'long',
                'action': 'buy',
                'current_price': round(price, 2),
                'approved_amount': round(amount, 2),
                'initial_stop_loss': round(stop_loss, 2),
                'entry_type': '左侧试探',
                'rationale': (f"VIX={vix:.1f}且出现长上影线，"
                              f"标的成交量={volume/vol_ma20:.1f}倍均量，满足左侧捡漏条件")
            })
            total_approved += amount

        except Exception as e:
            logger.warning(f"[Contrarian] {candidate.get('symbol')} 左侧评估失败: {e}")

    return contrarian_entries


# ─────────────────────────────────────────────
# 宏观因子一致性校验
# ─────────────────────────────────────────────

def check_macro_consistency(candidates: list, macro_narrative: dict) -> list:
    """
    检查各标的核心驱动逻辑是否存在宏观层面的隐性对冲。
    若同一市场内存在"商品周期逻辑"与"流动性成长逻辑"的分裂，
    标注 [宏观逻辑分裂预警]，可对双方仓位额外打折10%或放弃置信度较低的一方。
    """
    warnings = []

    # 简化实现：按行业标签分组，检查是否存在周期性 vs 成长性的对立
    cyclical_industries = {'能源', '材料', '工业', '航运', '钢铁', '有色', '煤炭'}
    growth_industries = {'科技', '通信', '消费', '医疗', '互联网'}

    cyclical_symbols = []
    growth_symbols = []

    for c in candidates:
        industry = c.get('industry', '未知')
        symbol = c.get('symbol', '未知')
        if industry in cyclical_industries:
            cyclical_symbols.append(symbol)
        elif industry in growth_industries:
            growth_symbols.append(symbol)

    if cyclical_symbols and growth_symbols:
        warning = (f"[宏观逻辑分裂预警] 候选标的中同时存在周期逻辑({cyclical_symbols})和"
                   f"成长逻辑({growth_symbols})，建议对置信度较低一方仓位额外打折10%")
        warnings.append(warning)
        logger.warning(f"[Dispatcher] {warning}")

    return warnings


# ─────────────────────────────────────────────
# 主调度完整流程
# ─────────────────────────────────────────────

def run_daily_decision(index_symbol: str = 'SPY',
                        stock_symbols: list = None,
                        account_equity: float = 100000000,
                        cash: float = 100000000,
                        inception_equity: float = 100000000,
                        current_positions: list = None,
                        news_summary: str = '',
                        recent_closed_trades: list = None,
                        industry_map: dict = None,
                        market_cap_map: dict = None,
                        beta_map: dict = None,
                        dividend_yield_map: dict = None,
                        avg_volume_map: dict = None,
                        pre_fetched_data: dict = None) -> dict:
    """
    Blakever 每日决策完整流程，与主Agent Prompt 调用顺序对齐。

    Args:
        pre_fetched_data: 可选，已获取的行情数据，避免重复请求 yfinance。
            格式: {'index_df': DataFrame, 'vix_df': DataFrame,
                   'macro_data': dict, 'stock_data': {symbol: DataFrame}}

    Returns:
        {
            'report': str,              # 《每日操作建议指南》Markdown
            'market_regime': str,
            'regime_confidence': float,
            'execution_orders': list,   # 发送给 Agent 6 的执行指令
            'cro_result': dict,         # CRO 完整输出
            'contrarian_entries': list, # 左侧试探仓位
            'risk_warnings': list       # 风险红线提醒
        }
    """
    current_positions = current_positions or []
    recent_closed_trades = recent_closed_trades or []
    risk_warnings = []

    # ── Step 1: 行情数据获取 ──
    logger.info("[Dispatcher] Step 1: 获取行情数据...")
    if pre_fetched_data:
        # 使用已获取的数据，避免重复请求 yfinance
        index_df = pre_fetched_data.get('index_df')
        vix_df = pre_fetched_data.get('vix_df')
        macro_data = pre_fetched_data.get('macro_data', {})
        stock_data = pre_fetched_data.get('stock_data', {})
        current_prices = extract_current_prices({index_symbol: index_df, **stock_data} if index_df is not None else stock_data)
        avg_daily_volumes = extract_avg_daily_volumes(stock_data)
        logger.info("[Dispatcher] 使用预获取的行情数据（跳过 yfinance 请求）")
    else:
        index_data = fetch_ohlcv(index_symbol, period='1y', add_indicators=True)
        index_df = index_data.get(index_symbol, None)
        vix_df = fetch_vix_data(period='1y')
        macro_data = fetch_macro_data(period='6mo')

        stock_data = {}
        if stock_symbols:
            stock_data = fetch_ohlcv(stock_symbols, period='1y', add_indicators=True)

        current_prices = extract_current_prices({**index_data, **stock_data})
        avg_daily_volumes = extract_avg_daily_volumes(stock_data)

    # ── Step 1.5: 刷新现有持仓价格（🔧 修复报告价格过期问题）──
    # 核心修复：强制用从行情数据提取的最新价格覆盖 current_positions 中的现价，
    # 避免主Agent传入的持仓数据包含过期/编造的价格
    if current_positions and current_prices:
        logger.info("[Dispatcher] Step 1.5: 刷新现有持仓价格...")
        current_positions = refresh_position_prices(current_positions, current_prices)
    else:
        # 如果外部未传入 current_positions，从 paper-trader 直接获取
        if not current_positions:
            try:
                pt_positions = paper_trader_positions()
                if pt_positions:
                    current_positions = pt_positions
                    logger.info(f"[Dispatcher] Step 1.5: 从 paper-trader 获取到 {len(current_positions)} 只持仓")
                    # 再次用最新价格刷新
                    if current_prices:
                        current_positions = refresh_position_prices(current_positions, current_prices)
            except Exception as e:
                logger.warning(f"[Dispatcher] Step 1.5: 从 paper-trader 获取持仓失败: {e}")

    # ── Step 2: Agent 2 宏观叙事分析 ──
    logger.info("[Dispatcher] Step 2: 宏观叙事分析...")
    macro_narrative = analyze_macro_narrative(
        vix_df, news_summary, macro_data.get('tnx'))

    # ── Step 3: Agent 1 市场行情判断（带确认期防抖）──
    logger.info("[Dispatcher] Step 3: 市场行情判断（带确认期防抖）...")
    market_result = analyze_market_with_confirmation(index_df, vix_df)
    regime = market_result['regime']
    regime_confidence = market_result['confidence']
    raw_regime = market_result.get('raw_regime', regime)
    raw_confidence = market_result.get('raw_confidence', regime_confidence)
    pending_switch = market_result.get('pending_switch')

    logger.info(f"[Dispatcher] 行情定性: {regime}（置信度{regime_confidence}%），"
                f"当日原始判断: {raw_regime}（{raw_confidence}%）"
                + (f"，待确认切换→{pending_switch['regime']}（{pending_switch['days']}/{pending_switch['required']}日）"
                   if pending_switch and regime != raw_regime else ""))

    # ── Step 4: 低置信度限流（2026-04-23改造：不再熔断）──
    # 核心变更：
    # - Panic不再终止选股 → GEM的Panic模式(risk_weight=0)自动全仓安全资产(SHY/AGG)
    # - 左侧捡漏不再被连带杀死 → VIX>35时evaluate_contrarian_entry可以触发
    # - 置信度<60%不再熔断 → CRO额外打×0.5折扣（"看不清就少做"而非"看不清就不做"）
    # - 唯一安全阀：CRO的force_close_only（账户净值跌破强制空仓线）
    low_confidence_discount = 1.0  # 默认不打折
    if regime_confidence < 60:
        low_confidence_discount = 0.5
        risk_warnings.append(f"置信度={regime_confidence}%<60%，CRO仓位额外打×0.5折扣（限流不熔断）")
        logger.warning(f"[Dispatcher] 低置信度限流: {regime_confidence}%，CRO折扣×0.5")

    if regime == 'Panic':
        risk_warnings.append(f"行情=Panic，GEM将全仓安全资产(SHY/AGG)避险，左侧捡漏可触发")
        logger.warning("[Dispatcher] Panic限流: GEM全仓安全资产，左侧捡漏可触发")

    # ── Step 5: 调用统一GEM策略（贯穿牛熊）──
    logger.info(f"[Dispatcher] Step 5: 调用GEM统一策略（行情: {regime}）...")
    strategy_candidates = execute_trade_strategy(
        stock_data, account_equity, regime=regime,
        regime_confidence=regime_confidence,
        top_n=5,
        industry_map=industry_map, market_cap_map=market_cap_map,
        beta_map=beta_map, dividend_yield_map=dividend_yield_map,
        avg_volume_map=avg_volume_map)
    candidate_type = regime.lower()  # 'bull', 'bear', 'range', 'panic'

    if not strategy_candidates:
        logger.warning("[Dispatcher] 策略未选出任何候选标的")
        risk_warnings.append("策略未选出候选标的，建议观望")
        return _build_wait_report(market_result, macro_narrative, risk_warnings,
                                   account_equity, cash, current_positions,
                                   recent_closed_trades, inception_equity)

    # ── Step 6: 反向测试辩论庭 ──
    logger.info("[Dispatcher] Step 6: 反向测试辩论庭...")
    debated_candidates = run_adversarial_debate(strategy_candidates, index_df)

    # 过滤掉辩论否决的标的
    approved_candidates = [c for c in debated_candidates
                           if c.get('debate_verdict') == '通过']
    vetoed_candidates = [c for c in debated_candidates
                          if c.get('debate_verdict') == '否决']

    if vetoed_candidates:
        for v in vetoed_candidates:
            logger.info(f"[Dispatcher] 辩论否决: {v['symbol']} "
                        f"(置信度={v.get('final_confidence', 0):.0f}%)")

    # ── Step 7: 左侧捡漏评估 ──
    logger.info("[Dispatcher] Step 7: 左侧捡漏评估...")
    vix_value = market_result.get('vix', 0)
    market_env = {
        'vix': vix_value,
        'vix_daily_change_pct': market_result.get('vix_change_pct', 0),
        'sentiment_factor': macro_narrative['sentiment_factor'],
        'macro_liquidity_warning': macro_narrative['macro_liquidity_warning'],
    }
    # VIX 开盘/收盘需从 vix_df 提取
    if vix_df is not None and not vix_df.empty:
        try:
            latest_vix = vix_df.iloc[-1]
            market_env['vix_open'] = float(latest_vix.get('open', latest_vix['close']))
            market_env['vix_close'] = float(latest_vix['close'])
        except Exception:
            pass

    contrarian_entries = evaluate_contrarian_entry(
        market_env, strategy_candidates, account_equity)

    # ── Step 8: 宏观因子一致性校验 ──
    logger.info("[Dispatcher] Step 8: 宏观因子一致性校验...")
    macro_warnings = check_macro_consistency(approved_candidates, macro_narrative)
    risk_warnings.extend(macro_warnings)

    # 宏观逻辑分裂时对低置信度一方打折10%
    if macro_warnings:
        for c in approved_candidates:
            if c.get('final_confidence', 100) < 60:
                c['approved_amount'] = c.get('approved_amount', 0) * 0.9

    # ── Step 8.5: 动态止损止盈更新 ──
    # 对已有持仓根据最新ATR/ADX动态更新吊灯止损、减仓价、清仓价等
    logger.info("[Dispatcher] Step 8.5: 动态止损止盈更新（吊灯止损+阶梯止盈）...")
    try:
        from fool_trader import (
            paper_trader_get_positions, paper_trader_update_stops,
            calculate_dynamic_stops
        )

        # 获取当前所有持仓
        all_positions = paper_trader_get_positions()
        if all_positions:
            # 构建动态止损计算所需的持仓数据
            positions_for_update = []
            for pos in all_positions:
                symbol = pos.get('代码', pos.get('symbol', ''))
                if not symbol:
                    continue

                # 从stock_data获取ATR/ADX/最高最低价等指标
                sym_data = stock_data.get(symbol)
                atr20_val = 0
                adx14_val = 0
                highest = float(pos.get('现价', pos.get('current_price', 0)))
                lowest = float(pos.get('建仓价', pos.get('entry_price', 0)))
                rsi14_val = 50

                if sym_data is not None and hasattr(sym_data, 'iloc') and len(sym_data) > 0:
                    latest = sym_data.iloc[-1]
                    atr20_val = float(latest.get('atr_20', latest.get('atr14', 0)))
                    adx14_val = float(latest.get('adx_14', latest.get('adx14', 0)))
                    rsi14_val = float(latest.get('rsi_14', latest.get('rsi14', 50)))

                    # 计算持仓期间最高最低价
                    entry_date = pos.get('建仓日期', pos.get('entry_date', ''))
                    if entry_date and hasattr(sym_data, 'index'):
                        try:
                            mask = sym_data.index >= entry_date
                            subset = sym_data[mask]
                            if len(subset) > 0:
                                highest = float(subset['high'].max())
                                lowest = float(subset['low'].min())
                        except Exception:
                            pass

                positions_for_update.append({
                    'symbol': symbol,
                    'direction': pos.get('方向', pos.get('direction', 'long')),
                    'entry_price': float(pos.get('建仓价', pos.get('entry_price', 0))),
                    'current_price': float(pos.get('现价', pos.get('current_price', 0))),
                    'pnl_pct': float(str(pos.get('盈亏%', pos.get('pnl_pct', 0))).replace('%', '')),
                    'max_profit_since_entry': float(pos.get('历史最大盈利', pos.get('max_profit_since_entry', 0))),
                    'atr20': atr20_val,
                    'adx14': adx14_val,
                    'highest_since_entry': highest,
                    'lowest_since_entry': lowest,
                    'strategy_type': 'gem',
                    'rsi14': rsi14_val,
                    'protection_period': int(pos.get('protection_period', 0)),
                    'entry_date': pos.get('建仓日期', pos.get('entry_date', '')),
                })

            # 计算动态止损止盈
            if positions_for_update:
                dynamic_updates = calculate_dynamic_stops(positions_for_update)
                if dynamic_updates:
                    # 回写到paper-trader
                    update_result = paper_trader_update_stops(dynamic_updates)
                    logger.info(f"   ✅ 动态止损止盈已更新: {len(dynamic_updates)}只持仓")
                    # 输出更新摘要
                    for sym, upd in dynamic_updates.items():
                        trailing = upd.get('trailing_stop_price', '')
                        reason = upd.get('update_reason', '')
                        logger.info(f"     {sym}: 吊灯止损={trailing}, 原因={reason}")
                else:
                    logger.info("   ℹ️ 无需更新（数据不足或ATR=0）")
            else:
                logger.info("   ℹ️ 无持仓需要更新")
        else:
            logger.info("   ℹ️ 当前无持仓，跳过动态止损更新")
    except Exception as e:
        logger.warning(f"   ⚠️ 动态止损止盈更新失败（不影响主流程）: {e}")

    # ── Step 9: Agent 0 CRO 风控 ──
    logger.info("[Dispatcher] Step 9: CRO 风控审核...")
    # 准备 CRO 输入
    proposed_trades = []
    for c in approved_candidates:
        proposed_trades.append({
            'symbol': c['symbol'],
            'direction': c.get('direction', 'long'),
            'entry_price': c.get('current_price', 0),
            'stop_loss': c.get('initial_stop_loss', 0),
            'suggested_amount': c.get('suggested_amount', c.get('approved_amount', 0)),
            'market_cap_type': c.get('market_cap_type', 'large'),
            'industry': c.get('industry', '未知'),
        })

    # 左侧试探也提交 CRO
    for entry in contrarian_entries:
        proposed_trades.append({
            'symbol': entry['symbol'],
            'direction': 'long',
            'entry_price': entry['current_price'],
            'stop_loss': entry['initial_stop_loss'],
            'suggested_amount': entry['approved_amount'],
            'market_cap_type': 'large',
            'industry': '未知',
        })

    cro_result = run_cro_full_check(
        account_equity=account_equity,
        current_positions=current_positions,
        proposed_trades=proposed_trades,
        market_environment=market_env,
        daily_pnl=0,
        prev_daily_pnl=0,
        low_confidence_discount=low_confidence_discount
    )

    if cro_result.get('force_close_only'):
        risk_warnings.extend(cro_result.get('triggered_rules', []))
        return _build_wait_report(market_result, macro_narrative, risk_warnings,
                                   account_equity, cash, current_positions,
                                   recent_closed_trades, inception_equity)

    # 收集 CRO 风险红线
    if cro_result.get('industry_concentration_warnings'):
        risk_warnings.extend(cro_result['industry_concentration_warnings'])
    if cro_result.get('hidden_correlation_warnings'):
        risk_warnings.extend(cro_result['hidden_correlation_warnings'])

    # ── Step 10: Agent 7 经验库终审 ──
    logger.info("[Dispatcher] Step 10: 经验库终审...")
    experience_result = run_experience_review(
        recent_closed_trades=recent_closed_trades,
        current_losing_positions=[p for p in current_positions
                                   if float(p.get('pnl_pct', 0)) < -5],
        current_market_regime=regime
    )

    # 收集知识效期预警
    if experience_result.get('expiration_warnings'):
        risk_warnings.extend([w['reason'] for w in experience_result['expiration_warnings']])

    # ── Step 11: 生成执行指令（含建仓regime标记和保护期）──
    execution_orders = []
    for approved in cro_result.get('approved_trades', []):
        # 从approved_candidates中查找保护期信息
        approved_detail = next((c for c in approved_candidates if c.get('symbol') == approved['symbol']), {})
        protection_period = approved_detail.get('protection_period', 0)
        protection_label = approved_detail.get('protection_label', '无保护期')
        
        execution_orders.append({
            'symbol': approved['symbol'],
            'direction': approved.get('direction', 'long'),
            'action': 'buy' if approved.get('direction', 'long') == 'long' else 'short',
            'amount': approved['approved_amount'],
            'reason': approved.get('intervention_reason', ''),
            'entry_regime': regime,  # 建仓时的市场状态（2026-04-22新增）
            'entry_regime_confidence': regime_confidence,  # 建仓时的regime置信度
            'protection_period': protection_period,  # 保护期天数（0=无保护期）
            'protection_label': protection_label,  # 保护期标签（如"🛡️3天保护期"）
        })

    # ── Step 12: 生成《每日操作建议指南》──
    report = _build_daily_report(
        market_result=market_result,
        macro_narrative=macro_narrative,
        cro_result=cro_result,
        approved_candidates=approved_candidates,
        contrarian_entries=contrarian_entries,
        experience_result=experience_result,
        risk_warnings=risk_warnings,
        account_equity=account_equity,
        cash=cash,
        current_positions=current_positions,
        inception_equity=inception_equity,
        regime=regime,
        hk_market_result=pre_fetched_data.get('hk_market_result') if pre_fetched_data else None
    )

    return {
        'report': report,
        'market_regime': regime,
        'regime_confidence': regime_confidence,
        'raw_regime': raw_regime,
        'raw_confidence': raw_confidence,
        'pending_switch': pending_switch,
        'execution_orders': execution_orders,
        'cro_result': cro_result,
        'contrarian_entries': contrarian_entries,
        'risk_warnings': risk_warnings,
        'experience_result': experience_result
    }


# ─────────────────────────────────────────────
# 报告生成
# ─────────────────────────────────────────────

def _build_wait_report(market_result, macro_narrative, risk_warnings,
                        account_equity, cash, current_positions,
                        recent_closed_trades, inception_equity) -> dict:
    """生成观望报告"""
    regime = market_result['regime']
    confidence = market_result['confidence']
    vix = market_result.get('vix', 0)
    sentiment = macro_narrative['sentiment_factor']

    # 市场定性中文标签
    regime_labels = {
        'Bull': '🐂 趋势牛市',
        'Bear': '🐻 趋势熊市',
        'Range': '🔄 震荡市',
        'Panic': '😱 恐慌崩盘'
    }
    regime_label = regime_labels.get(regime, regime)

    # 确认期防抖信息（2026-04-22新增）
    raw_regime = market_result.get('raw_regime', regime)
    raw_confidence = market_result.get('raw_confidence', confidence)
    pending_switch = market_result.get('pending_switch')
    confirm_info = ""
    if raw_regime != regime:
        confirm_info = f"\n- ⏳ 待确认切换→{regime_labels.get(raw_regime, raw_regime)}（{pending_switch['days']}/{pending_switch['required']}日确认）"
    elif pending_switch and pending_switch.get('days', 0) >= pending_switch.get('required', 1):
        confirm_info = f"\n- ✅ 切换已确认（连续{pending_switch['days']}日）"

    report = f"""# Blakever 每日操作建议指南 - 观望

## 📊 大盘仪表盘
- 行情定性: **{regime_label}**
- 置信度: {confidence}%（当日原始判断: {raw_regime} {raw_confidence}%）{confirm_info}
- VIX: {vix:.1f}
- 情绪因子: {sentiment}
- 流动性预警: {'⚠️ 是' if macro_narrative['macro_liquidity_warning'] else '否'}

## ⚠️ 风险红线
"""
    for w in risk_warnings:
        report += f"- {w}\n"

    report += f"""
## 📋 操作建议
**今日建议观望**（触发CRO强制空仓线或策略无候选标的）
"""

    # ── 持仓管理表（观望报告也展示持仓）──
    if current_positions:
        from stock_pool import HK_NAME_MAP, is_hk_symbol

        def _symbol_display_name_wait(sym: str) -> str:
            """将持仓代码转换为可读名称"""
            if sym.startswith('HK') and not sym.endswith('.HK'):
                num_part = sym[2:].lstrip('0') or '0'
                yf_code = f'{num_part.zfill(4)}.HK'
                cn_name = HK_NAME_MAP.get(yf_code, sym)
                return f'{cn_name}({sym})' if cn_name != sym else sym
            elif sym.endswith('.HK'):
                cn_name = HK_NAME_MAP.get(sym, sym)
                return f'{cn_name}({sym})' if cn_name != sym else sym
            else:
                return sym

        report += "\n## 📊 持仓管理表（傻瓜交易员）\n\n"
        report += "| 标的 | 方向 | 建仓价 | 现价 | 数量 | 持仓金额 | 浮盈亏 | 盈亏% | 止损价 | 建仓日期 | 状态 |\n"
        report += "|------|------|--------|------|------|----------|--------|-------|--------|----------|------|\n"

        total_pv = 0
        total_pnl_v = 0
        for pos in current_positions:
            sym = pos.get('symbol', '')
            direction = pos.get('direction', 'long')
            entry_price = float(pos.get('entry_price', 0))
            current_price = float(pos.get('current_price', 0))
            quantity = float(pos.get('quantity', 0))
            position_size = float(pos.get('position_size', 0))
            pnl = float(pos.get('pnl', 0))
            pnl_pct = float(pos.get('pnl_pct', 0))
            stop_loss = pos.get('stop_loss', 'N/A')
            entry_date = pos.get('entry_date', 'N/A')

            display_name = _symbol_display_name_wait(sym)
            dir_label = "多" if direction == 'long' else "空"
            pnl_sign = "+" if pnl >= 0 else ""
            pnl_pct_sign = "+" if pnl_pct >= 0 else ""

            # 简易状态判定
            status_label = "🟢信号健康"
            if pnl_pct < -5:
                status_label = "🔴浮亏超5%"
            elif stop_loss != 'N/A' and current_price > 0 and float(stop_loss) > 0:
                if (current_price - float(stop_loss)) / current_price < 0.05:
                    status_label = "🟡止损临界"

            report += (f"| {display_name} | {dir_label} | {entry_price:.2f} | {current_price:.2f} "
                       f"| {quantity:,.0f} | {position_size:,.0f} "
                       f"| {pnl_sign}{pnl:,.0f} | {pnl_pct_sign}{pnl_pct:.2f}% "
                       f"| {stop_loss} | {entry_date} | {status_label} |\n")
            total_pv += position_size
            total_pnl_v += pnl

        total_pnl_sign = "+" if total_pnl_v >= 0 else ""
        report += (f"| **合计** | | | | | **{total_pv:,.0f}** "
                   f"| **{total_pnl_sign}{total_pnl_v:,.0f}** | | | | |\n")
    else:
        report += "\n## 📊 持仓管理表（傻瓜交易员）\n\n> 当前无持仓\n"

    report += f"""
## 💰 净值简报
- 账户净值: {account_equity:,.0f}
- 现金: {cash:,.0f}
- 持仓数: {len(current_positions)}
"""
    return {
        'report': report,
        'market_regime': regime,
        'regime_confidence': confidence,
        'execution_orders': [],
        'cro_result': {},
        'contrarian_entries': [],
        'risk_warnings': risk_warnings
    }


def _build_daily_report(market_result, macro_narrative, cro_result,
                         approved_candidates, contrarian_entries,
                         experience_result, risk_warnings,
                         account_equity, cash, current_positions,
                         inception_equity, regime='Bull',
                         hk_market_result=None) -> str:
    """生成《每日操作建议指南》Markdown"""
    regime = market_result['regime']
    confidence = market_result['confidence']
    vix = market_result.get('vix', 0)
    sentiment = macro_narrative['sentiment_factor']
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 市场定性中文标签与解读
    regime_labels = {
        'Bull': '🐂 趋势牛市',
        'Bear': '🐻 趋势熊市',
        'Range': '🔄 震荡市',
        'Panic': '😱 恐慌崩盘'
    }
    regime_descriptions = {
        'Bull': '均线多头排列，ADX趋势确认，市场处于上升趋势，适合做多高动量个股',
        'Bear': '均线空头排列，趋势下行，适合做空破位标的或配置低Beta避险资产',
        'Range': '均线排列混乱，ADX低位，市场无明显趋势，适合区间交易低买高卖',
        'Panic': 'VIX飙升或暴涨，市场系统性风险极高，建议全面防御或观望'
    }
    regime_label = regime_labels.get(regime, regime)
    regime_desc = regime_descriptions.get(regime, '')

    # 确认期防抖信息（2026-04-22新增）
    raw_regime = market_result.get('raw_regime', regime)
    raw_confidence = market_result.get('raw_confidence', confidence)
    pending_switch = market_result.get('pending_switch')
    confirm_info = ""
    if raw_regime != regime:
        confirm_info = f"\n- ⏳ 待确认切换→{regime_labels.get(raw_regime, raw_regime)}（{pending_switch['days']}/{pending_switch['required']}日确认）"
    elif pending_switch and pending_switch.get('days', 0) >= pending_switch.get('required', 1):
        confirm_info = f"\n- ✅ 切换已确认（连续{pending_switch['days']}日）"

    report = f"""# Blakever 每日操作建议指南
> 生成时间: {now}

## 📊 大盘仪表盘

**🇺🇸 美股大盘**
- 行情定性: **{regime_label}**
- 定性解读: {regime_desc}
- 置信度: {confidence}%（当日原始判断: {raw_regime} {raw_confidence}%）{confirm_info}
- VIX: {vix:.1f}
- 情绪因子: {sentiment}
- 流动性预警: {'⚠️ 是' if macro_narrative['macro_liquidity_warning'] else '否'}
- 关键事件: {macro_narrative['key_events']}
"""

    # 港股大盘仪表盘
    if hk_market_result:
        hk_regime = hk_market_result['regime']
        hk_confidence = hk_market_result['confidence']
        hk_regime_label = regime_labels.get(hk_regime, hk_regime)
        hk_regime_desc = regime_descriptions.get(hk_regime, '')
        report += f"""
**🇭🇰 港股大盘**
- 行情定性: **{hk_regime_label}**
- 定性解读: {hk_regime_desc}
- 置信度: {hk_confidence}%
- VIX(参考): {hk_market_result.get('vix', 0):.1f}
"""

    report += f"""
## 🛡️ CRO 风控摘要
- 强制空仓线: {'⚠️ 已触发' if cro_result.get('force_close_only') else '✅ 未触发'}
- VIX风险等级: {cro_result.get('vix_risk_level', 'N/A')}
- 总敞口使用率: {cro_result.get('total_exposure_usage_pct', 0):.1f}%
- 行业集中度预警: {len(cro_result.get('industry_concentration_warnings', []))}项
- 隐性相关性预警: {len(cro_result.get('hidden_correlation_warnings', []))}项
"""

    # 今日指令表 — 合并 approved_candidates 的详细字段
    # 建立 symbol -> candidate 详细映射
    candidate_detail_map = {}
    for c in approved_candidates:
        candidate_detail_map[c.get('symbol', '')] = c

    report += "\n## 📋 今日指令表\n"
    if cro_result.get('approved_trades'):
        for t in cro_result['approved_trades']:
            sym = t['symbol']
            detail = candidate_detail_map.get(sym, {})
            current_price = detail.get('current_price', t.get('entry_price', 'N/A'))
            atr20 = detail.get('atr20', 'N/A')
            adx14 = detail.get('adx14', 'N/A')
            stop_loss = detail.get('initial_stop_loss', t.get('stop_loss', 'N/A'))
            take_profit = detail.get('take_profit_rule', 'N/A')
            final_conf = detail.get('final_confidence', 'N/A')
            rationale = detail.get('rationale', t.get('intervention_reason', ''))
            # 截断过长的文本
            if isinstance(take_profit, str) and len(take_profit) > 35:
                take_profit = take_profit[:35] + '...'
            if isinstance(rationale, str) and len(rationale) > 40:
                rationale = rationale[:40] + '...'
            direction = t.get('direction', 'long')
            # 获取中文名称（港股用中文名）
            from stock_pool import HK_NAME_MAP, is_hk_symbol
            display_name = HK_NAME_MAP.get(sym, sym) if is_hk_symbol(sym) else sym
            protection_label = t.get('protection_label', '无保护期')
            report += f"\n**{display_name}** ({direction})\n"
            report += f"- 当前价: {current_price} | ATR20: {atr20} | ADX14: {adx14}\n"
            report += f"- 止损价: {stop_loss} | 止盈: {take_profit}\n"
            report += f"- 批准金额: {t['approved_amount']:,.0f} | 置信度: {final_conf}% | {protection_label}\n"
            report += f"- 推荐理由: {rationale}\n"

        # 在指令表下方补充完整的止损止盈和吊灯止损细节
        report += "\n### 📐 止损止盈详细规则\n"
        for t in cro_result['approved_trades']:
            sym = t['symbol']
            detail = candidate_detail_map.get(sym, {})
            report += f"\n**{sym}**\n"
            report += f"- 当前价: {detail.get('current_price', 'N/A')}\n"
            report += f"- 初始止损: {detail.get('initial_stop_loss', 'N/A')}"
            if detail.get('stop_loss_pct'):
                report += f"（距入场 {detail['stop_loss_pct']:.1f}%）"
            report += "\n"
            report += f"- 止盈规则: {detail.get('take_profit_rule', 'N/A')}\n"
            report += f"- 吊灯止损: {detail.get('trailing_stop_rule', 'N/A')}\n"
            report += f"- CRO干预: {t.get('intervention_reason', 'OK')}\n"

        # 评分明细（统一GEM策略维度）
        dim_config = {
            'momentum': ('动量（绝对动量）', 30),
            'regime_fit': ('行情适配（regime权重）', 25),
            'trend': ('趋势质量（ADX/EMA）', 20),
            'volatility': ('波动率（ATR）', 15),
            'volume': ('资金面（成交量）', 10),
        }

        report += "\n### 🎯 GEM策略评分明细\n"
        for t in cro_result['approved_trades']:
            sym = t['symbol']
            detail = candidate_detail_map.get(sym, {})
            breakdown = detail.get('score_breakdown', {})
            total_score = detail.get('score', 'N/A')
            direction = detail.get('direction', t.get('direction', 'long'))

            # 统一使用GEM评分维度
            cur_dim_config = dim_config

            if breakdown:
                report += f"\n**{sym}**（总分: {total_score}）\n"
                for dim_key, (dim_label, max_val) in cur_dim_config.items():
                    score_val = breakdown.get(dim_key, 0)
                    bar_len = int(score_val / max_val * 10) if max_val > 0 else 0
                    bar_len = min(10, max(0, bar_len))
                    bar = '█' * bar_len + '░' * (10 - bar_len)
                    report += f"- {dim_label}: {bar} {score_val}/{max_val}\n"
            else:
                report += f"\n**{sym}**（综合评分: {total_score}，六维明细暂不可用）\n"

        # ── 保护期汇总 ──
        report += "\n### 🛡️ 保护期规则\n"
        report += "| 标的 | 评分 | 保护期 | 说明 |\n"
        report += "|------|------|--------|------|\n"
        for t in cro_result['approved_trades']:
            sym = t['symbol']
            detail = candidate_detail_map.get(sym, {})
            total_score = detail.get('score', 'N/A')
            protection_period = detail.get('protection_period', 0)
            if protection_period > 0:
                report += f"| {sym} | {total_score} | 🛡️{protection_period}天 | 评分≥60，保护期内止损放宽1个ATR |\n"
            else:
                report += f"| {sym} | {total_score} | 无 | 评分<60，无保护期，正常止损 |\n"
        report += "\n> 保护期规则：评分≥60分的策略配3天保护期，保护期内吊灯止损放宽1个ATR，避免建仓初期被正常波动洗出；评分<60分的策略无保护期，正常止损。\n"
    else:
        report += "无新开仓指令\n"

    # 辩论庭结果
    report += "\n## ⚖️ 反向测试辩论庭\n"
    for c in approved_candidates:
        report += (f"- **{c['symbol']}**: 原始置信度={c.get('original_confidence', 'N/A')}%，"
                   f"错误概率={c.get('error_probability', 'N/A')}%，"
                   f"最终置信度={c.get('final_confidence', 'N/A')}%\n")

    # 左侧试探仓位
    if contrarian_entries:
        report += "\n## 🎯 左侧试探仓位\n"
        for e in contrarian_entries:
            report += (f"- **{e['symbol']}**: 金额={e['approved_amount']:,.0f}，"
                       f"止损={e['initial_stop_loss']}，{e['rationale']}\n")

    # 知识效期预警
    exp_warnings = experience_result.get('expiration_warnings', [])
    if exp_warnings:
        report += "\n## ⏰ 知识效期预警\n"
        for w in exp_warnings:
            report += f"- {w['rule'][:50]}... → {w['action']}\n"

    # 风险红线
    if risk_warnings:
        report += "\n## 🚨 全局红线提醒\n"
        for w in risk_warnings:
            report += f"- ⚠️ {w}\n"

    # ── 持仓管理表（2026-04-24新增：展示傻瓜交易员的持仓和收益）──
    if current_positions:
        from stock_pool import HK_NAME_MAP, is_hk_symbol

        def _symbol_display_name(sym: str) -> str:
            """将持仓代码转换为可读名称"""
            # paper-trader 格式: HK00883 → yfinance 格式: 0883.HK
            if sym.startswith('HK') and not sym.endswith('.HK'):
                num_part = sym[2:].lstrip('0') or '0'
                yf_code = f'{num_part.zfill(4)}.HK'
                cn_name = HK_NAME_MAP.get(yf_code, sym)
                return f'{cn_name}({sym})' if cn_name != sym else sym
            elif sym.endswith('.HK'):
                cn_name = HK_NAME_MAP.get(sym, sym)
                return f'{cn_name}({sym})' if cn_name != sym else sym
            else:
                return sym
        report += "\n## 📊 持仓管理表（傻瓜交易员）\n\n"
        report += "| 标的 | 方向 | 建仓价 | 现价 | 数量 | 持仓金额 | 浮盈亏 | 盈亏% | 止损价 | 建仓日期 | 状态 |\n"
        report += "|------|------|--------|------|------|----------|--------|-------|--------|----------|------|\n"

        total_position_value_check = 0
        total_pnl_check = 0

        for pos in current_positions:
            sym = pos.get('symbol', '')
            direction = pos.get('direction', 'long')
            entry_price = float(pos.get('entry_price', 0))
            current_price = float(pos.get('current_price', 0))
            quantity = float(pos.get('quantity', 0))
            position_size = float(pos.get('position_size', 0))
            pnl = float(pos.get('pnl', 0))
            pnl_pct = float(pos.get('pnl_pct', 0))
            stop_loss = pos.get('stop_loss', 'N/A')
            entry_date = pos.get('entry_date', 'N/A')
            max_profit = float(pos.get('max_profit_since_entry', 0))

            # 显示名称（自动转换 HK00883 → 中海油(HK00883)）
            display_name = _symbol_display_name(sym)

            # 状态标签判定
            status_label = "🟢信号健康"
            if max_profit > 0 and pnl > 0:
                profit_drawdown = (max_profit - pnl) / max_profit if max_profit > 0 else 0
                if pnl > 0 and pnl / max_profit > 0.5:
                    if profit_drawdown > 0.5:
                        status_label = "🔴阶梯止盈中"
                    elif profit_drawdown > 0.3:
                        status_label = "🟡利润回吐"

            if stop_loss != 'N/A' and current_price > 0 and float(stop_loss) > 0:
                dist_to_stop = (current_price - float(stop_loss)) / current_price
                if dist_to_stop < 0.05:
                    status_label = "🟡止损临界"

            if pnl_pct < -5:
                status_label = "🔴浮亏超5%"

            # 方向标签
            dir_label = "多" if direction == 'long' else "空"

            # 盈亏颜色标记
            pnl_sign = "+" if pnl >= 0 else ""
            pnl_pct_sign = "+" if pnl_pct >= 0 else ""

            report += (f"| {display_name} | {dir_label} | {entry_price:.2f} | {current_price:.2f} "
                       f"| {quantity:,.0f} | {position_size:,.0f} "
                       f"| {pnl_sign}{pnl:,.0f} | {pnl_pct_sign}{pnl_pct:.2f}% "
                       f"| {stop_loss} | {entry_date} | {status_label} |\n")

            total_position_value_check += position_size
            total_pnl_check += pnl

        # 汇总行
        total_pnl_sign = "+" if total_pnl_check >= 0 else ""
        report += (f"| **合计** | | | | | **{total_position_value_check:,.0f}** "
                   f"| **{total_pnl_sign}{total_pnl_check:,.0f}** | | | | |\n")

        # 读取position_regime标记
        regimes = {}
        try:
            from fool_trader import get_position_regimes
            regimes = get_position_regimes()
        except Exception:
            pass

        if regimes:
            report += "\n### 📌 建仓Regime标记\n"
            for pos in current_positions:
                sym = pos.get('symbol', '')
                reg_info = regimes.get(sym, {})
                if reg_info:
                    display_name = _symbol_display_name(sym)
                    report += f"- **{display_name}**: 建仓时={reg_info.get('regime_at_entry', 'N/A')}（{reg_info.get('entry_date', 'N/A')}）\n"
    else:
        report += "\n## 📊 持仓管理表（傻瓜交易员）\n\n> 当前无持仓\n"

    # 🔧 持仓价格偏差检测（修复报告价格过期问题后的验证机制）
    price_deviation_warnings = []
    for pos in current_positions:
        symbol = pos.get('symbol', '')
        current_price = float(pos.get('current_price', 0))
        entry_price = float(pos.get('entry_price', 0))
        # 如果现价与入场价偏差超过50%，极可能是价格未刷新
        if entry_price > 0 and current_price > 0:
            deviation = abs(current_price - entry_price) / entry_price
            if deviation > 0.5:
                price_deviation_warnings.append(
                    f"{symbol}: 现价={current_price:.2f} vs 入场价={entry_price:.2f} "
                    f"(偏差{deviation:.0%})，价格可能未刷新"
                )

    if price_deviation_warnings:
        report += "\n## 🚨 持仓价格异常警告\n"
        report += "> **以下持仓的现价与入场价偏差超过50%，极可能是价格未实时刷新！**\n\n"
        for w in price_deviation_warnings:
            report += f"- ⚠️ {w}\n"

    # 净值简报
    total_position_value = sum(float(p.get('current_value', p.get('position_size', 0)))
                                for p in current_positions)
    total_pnl = sum(float(p.get('pnl', 0)) for p in current_positions)
    # 当有持仓时，总净值 = 现金 + 持仓市值 + 浮盈
    # 当空仓时，总净值 = account_equity（账户净值即现金）
    if current_positions:
        total_equity = cash + total_position_value + total_pnl
    else:
        total_equity = account_equity
    total_return = (total_equity - inception_equity) / inception_equity * 100 if inception_equity > 0 else 0

    report += f"""
## 💰 净值简报
- 账户净值: {total_equity:,.0f}
- 现金: {cash:,.0f}
- 持仓市值: {total_position_value:,.0f}
- 浮动盈亏: {total_pnl:,.0f}
- 总收益率: {total_return:.1f}%
- 持仓数: {len(current_positions)}

*本报告由 Blakever 多智能体投资决策系统自动生成*
"""
    return report
