"""
Blakever 全流程集成测试
使用模拟数据运行完整决策链路，验证各模块接口兼容性。
"""

import sys
import os
import logging
import pandas as pd
import numpy as np

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s [%(name)s] %(message)s')
logger = logging.getLogger("IntegrationTest")

# ─────────────────────────────────────────────
# 1. 生成模拟行情数据
# ─────────────────────────────────────────────

def generate_mock_ohlcv(symbol: str, days: int = 300, trend: str = 'bull',
                         base_price: float = 100.0, volatility: float = 0.02) -> pd.DataFrame:
    """生成模拟 OHLCV 数据（含趋势特征）"""
    np.random.seed(hash(symbol) % 2**31)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=days)

    if trend == 'bull':
        drift = 0.0005
    elif trend == 'bear':
        drift = -0.0005
    else:  # range
        drift = 0.0

    returns = np.random.normal(drift, volatility, days)
    close = base_price * np.cumprod(1 + returns)
    close = np.maximum(close, 1.0)  # 防止负数

    high = close * (1 + np.abs(np.random.normal(0, volatility * 0.5, days)))
    low = close * (1 - np.abs(np.random.normal(0, volatility * 0.5, days)))
    open_price = close * (1 + np.random.normal(0, volatility * 0.3, days))
    volume = np.random.randint(5000000, 50000000, days).astype(float)

    df = pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })
    return df


def generate_mock_vix(days: int = 90, level: str = 'normal') -> pd.DataFrame:
    """生成模拟 VIX 数据"""
    np.random.seed(42)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=days)

    if level == 'panic':
        base_vix = 35.0
    elif level == 'high':
        base_vix = 25.0
    else:
        base_vix = 16.0

    vix_values = base_vix + np.random.normal(0, 2, days)
    vix_values = np.maximum(vix_values, 10.0)

    df = pd.DataFrame({
        'date': dates,
        'open': vix_values * (1 + np.random.normal(0, 0.02, days)),
        'high': vix_values * (1 + np.abs(np.random.normal(0, 0.05, days))),
        'low': vix_values * (1 - np.abs(np.random.normal(0, 0.05, days))),
        'close': vix_values,
        'volume': 0.0
    })
    return df


# ─────────────────────────────────────────────
# 2. 运行全流程
# ─────────────────────────────────────────────

def run_full_test():
    """运行完整 Blakever 决策流程"""
    from market_info import standardize_ohlcv
    from market_analyze import analyze_market
    from cro_mgr import run_cro_full_check, check_force_close
    from blakever_trade_strategy import execute_trade_strategy
    from fool_trader import run_execution
    from experience_review import run_experience_review
    from strategy_backtest import run_strategy_backtest
    from main_dispatcher import (
        analyze_macro_narrative, run_adversarial_debate,
        evaluate_contrarian_entry, check_macro_consistency
    )

    print("=" * 70)
    print("🚀 Blakever 全流程集成测试")
    print("=" * 70)

    # ── 准备模拟数据 ──
    print("\n📊 Step 0: 生成模拟数据...")

    # 指数数据（牛市趋势）
    index_raw = generate_mock_ohlcv('SPY', days=300, trend='bull', base_price=450, volatility=0.015)
    index_df = standardize_ohlcv(index_raw, symbol='SPY', add_indicators=True)
    print(f"   指数数据: {len(index_df)} 行, 最新价={index_df.iloc[-1]['close']:.2f}")

    # VIX 数据（正常水平）
    vix_raw = generate_mock_vix(days=90, level='normal')
    vix_df = standardize_ohlcv(vix_raw, symbol='VIX', add_indicators=True)
    print(f"   VIX数据: {len(vix_df)} 行, 最新VIX={vix_df.iloc[-1]['close']:.1f}")

    # 股票池数据
    stock_configs = [
        # (symbol, trend, base_price, industry, market_cap_billion_usd)
        ('AAPL', 'bull', 175, '科技', 2800),
        ('MSFT', 'bull', 380, '科技', 2700),
        ('GOOGL', 'bull', 140, '科技', 1700),
        ('AMZN', 'bull', 180, '消费', 1500),
        ('NVDA', 'bull', 800, '科技', 1200),
        ('JPM', 'range', 150, '金融', 500),
        ('JNJ', 'range', 165, '医疗', 400),
        ('PG', 'range', 155, '消费', 350),
        ('XOM', 'bear', 105, '能源', 450),
        ('TSLA', 'bull', 250, '科技', 800),
    ]

    stock_data = {}
    industry_map = {}
    market_cap_map = {}
    beta_map = {}
    dividend_yield_map = {}
    avg_volume_map = {}

    for symbol, trend, base_price, industry, mcap in stock_configs:
        raw = generate_mock_ohlcv(symbol, days=300, trend=trend, base_price=base_price, volatility=0.02)
        stock_data[symbol] = standardize_ohlcv(raw, symbol=symbol, add_indicators=True)
        industry_map[symbol] = industry
        market_cap_map[symbol] = mcap
        beta_map[symbol] = 0.5 if industry in ('医疗', '消费') else 1.2 if industry == '科技' else 0.9
        dividend_yield_map[symbol] = 0.035 if industry in ('医疗', '消费', '能源') else 0.01
        avg_volume_map[symbol] = 15_000_000  # 1500万股

    print(f"   股票池: {list(stock_data.keys())}")

    # 模拟账户参数
    account_equity = 100000000.0
    cash = 100000000.0
    inception_equity = 100000000.0
    current_positions = [
        {'symbol': 'AAPL', 'direction': 'long', 'industry': '科技',
         'entry_price': 170.0, 'current_price': 175.0, 'current_value': 5000.0,
         'position_size': 5000.0, 'pnl': 147.0, 'pnl_pct': 2.9}
    ]

    # ── Test 1: 市场行情判断 ──
    print("\n" + "─" * 50)
    print("📈 Test 1: 市场行情判断 (Agent 1)")
    market_result = analyze_market(index_df, vix_df)
    print(f"   行情定性: {market_result['regime']}")
    print(f"   置信度: {market_result['confidence']}%")
    print(f"   VIX: {market_result['vix']}")
    print(f"   摘要: {market_result['summary']}")

    # ── Test 2: 宏观叙事分析 ──
    print("\n" + "─" * 50)
    print("🌐 Test 2: 宏观叙事分析 (Agent 2)")
    macro_result = analyze_macro_narrative(vix_df, news_summary='市场情绪平稳，无重大事件')
    print(f"   情绪因子: {macro_result['sentiment_factor']}")
    print(f"   流动性预警: {macro_result['macro_liquidity_warning']}")
    print(f"   关键事件: {macro_result['key_events']}")

    # ── Test 3: 根据行情调用统一GEM策略 ──
    regime = market_result['regime']
    regime_confidence = market_result['confidence']
    print(f"\n{'─' * 50}")
    print(f"🎯 Test 3: GEM统一策略选股 (行情={regime}, 置信度={regime_confidence}%)")

    strategy_candidates = execute_trade_strategy(
        stock_data, account_equity, regime=regime,
        regime_confidence=regime_confidence,
        top_n=5,
        industry_map=industry_map, market_cap_map=market_cap_map,
        beta_map=beta_map, dividend_yield_map=dividend_yield_map,
        avg_volume_map=avg_volume_map)

    print(f"   选出候选标的: {len(strategy_candidates)} 只")
    for c in strategy_candidates:
        print(f"   - {c.get('symbol')}: 方向={c.get('direction', 'long')}, "
              f"评分={c.get('score', 'N/A')}, "
              f"仓位={c.get('suggested_pct', 0):.2%}")

    # ── Test 4: 反向测试辩论庭 ──
    print(f"\n{'─' * 50}")
    print("⚖️ Test 4: 反向测试辩论庭")
    debated = run_adversarial_debate(strategy_candidates, index_df)
    for d in debated:
        print(f"   - {d.get('symbol')}: 原始置信度={d.get('original_confidence', 'N/A')}%, "
              f"错误概率={d.get('error_probability', 'N/A')}%, "
              f"最终置信度={d.get('final_confidence', 'N/A')}%, "
              f"判决={d.get('debate_verdict', 'N/A')}")

    approved = [c for c in debated if c.get('debate_verdict') == '通过']
    print(f"   辩论通过: {len(approved)} 只")

    # ── Test 5: CRO 风控 ──
    print(f"\n{'─' * 50}")
    print("🛡️ Test 5: CRO 风控 (Agent 0)")

    proposed_trades = []
    for c in approved:
        proposed_trades.append({
            'symbol': c['symbol'],
            'direction': c.get('direction', 'long'),
            'entry_price': c.get('current_price', 0),
            'stop_loss': c.get('initial_stop_loss', 0),
            'suggested_amount': c.get('suggested_amount', c.get('approved_amount', 0)),
            'market_cap_type': c.get('market_cap_type', 'large'),
            'industry': c.get('industry', '未知'),
        })

    market_env = {
        'vix': market_result.get('vix', 0),
        'vix_daily_change_pct': market_result.get('vix_change_pct', 0),
        'sentiment_factor': macro_result['sentiment_factor'],
        'macro_liquidity_warning': macro_result['macro_liquidity_warning'],
    }

    cro_result = run_cro_full_check(
        account_equity=account_equity,
        current_positions=current_positions,
        proposed_trades=proposed_trades,
        market_environment=market_env,
        daily_pnl=0,
        prev_daily_pnl=0
    )
    print(f"   强制空仓线: {'⚠️ 触发' if cro_result.get('force_close_only') else '✅ 未触发'}")
    print(f"   VIX风险等级: {cro_result.get('vix_risk_level', 'N/A')}")
    print(f"   总敞口使用率: {cro_result.get('total_exposure_usage_pct', 0):.1f}%")
    print(f"   批准交易数: {len(cro_result.get('approved_trades', []))}")
    for t in cro_result.get('approved_trades', []):
        print(f"   - {t['symbol']}: 金额={t['approved_amount']:.0f}, "
              f"原因={t.get('intervention_reason', 'OK')[:50]}")
    if cro_result.get('industry_concentration_warnings'):
        print(f"   行业集中度预警: {cro_result['industry_concentration_warnings']}")
    if cro_result.get('hidden_correlation_warnings'):
        print(f"   隐性相关性预警: {cro_result['hidden_correlation_warnings']}")

    # ── Test 6: 经验库复盘 ──
    print(f"\n{'─' * 50}")
    print("📚 Test 6: 经验总结复盘 (Agent 7)")
    recent_trades = [
        {'symbol': 'META', 'direction': 'long', 'entry_price': 300,
         'exit_price': 330, 'pnl': 3000, 'pnl_pct': 10, 'exit_reason': '止盈',
         'duration_days': 15},
        {'symbol': 'XOM', 'direction': 'long', 'entry_price': 110,
         'exit_price': 100, 'pnl': -2000, 'pnl_pct': -9.1, 'exit_reason': '止损',
         'duration_days': 8},
    ]
    exp_result = run_experience_review(
        recent_closed_trades=recent_trades,
        current_losing_positions=[],
        current_market_regime=regime
    )
    print(f"   新经验数: {len(exp_result.get('new_insights', []))}")
    for insight in exp_result.get('new_insights', []):
        print(f"   - [{insight.get('regime_tag')}] {insight.get('content', '')[:60]}...")
    print(f"   知识库摘要: {exp_result.get('knowledge_base_summary', 'N/A')}")

    # ── Test 7: 策略回测 ──
    print(f"\n{'─' * 50}")
    print("📊 Test 7: 策略回测 (Agent 8)")
    backtest_result = run_strategy_backtest(
        df=index_df,
        strategy_name='bull',
        backtest_periods=['1y', '3y'],
        baseline_result={'annual_return': 8, 'max_drawdown': 15}
    )
    print(f"   过拟合检测: {'⚠️ 是' if backtest_result['overfit_detected'] else '✅ 否'}")
    print(f"   过拟合详情: {backtest_result['overfit_details'][:60] if backtest_result['overfit_details'] else 'N/A'}")
    print(f"   一致性验证: {backtest_result['consistency_check'].get('verdict', 'N/A')}")
    for period, result in backtest_result.get('period_results', {}).items():
        print(f"   - {period}: 夏普={result.get('sharpe', 0):.2f}, "
              f"最大回撤={result.get('max_drawdown', 0):.1f}%, "
              f"年化={result.get('annual_return', 0):.1f}%, "
              f"胜率={result.get('win_rate', 0):.1f}%")
    print(f"   采纳建议: {'✅ 推荐' if backtest_result.get('recommend_adoption') else '❌ 不推荐'}")
    print(f"   优化建议: {backtest_result.get('optimization_notes', 'N/A')[:80]}")

    # ── Test 8: 傻瓜交易员执行 ──
    print(f"\n{'─' * 50}")
    print("💹 Test 8: 傻瓜交易员执行 (Agent 6)")

    execution_orders = []
    for t in cro_result.get('approved_trades', []):
        execution_orders.append({
            'symbol': t['symbol'],
            'direction': t.get('direction', 'long'),
            'action': 'buy' if t.get('direction', 'long') == 'long' else 'short',
            'amount': t['approved_amount'],
            'reason': t.get('intervention_reason', '')
        })

    # 准备价格和成交量
    current_prices = {}
    avg_daily_volumes = {}
    for symbol, df in stock_data.items():
        if df is not None and not df.empty:
            current_prices[symbol] = float(df.iloc[-1]['close'])
            # 均量（股数）× 价格 = 日均成交额（金额），与 calculate_execution_cost 参数对齐
            vol_ma20 = df.iloc[-1].get('volume_ma20', df.iloc[-1].get('volume', 0))
            if pd.isna(vol_ma20) or vol_ma20 <= 0:
                vol_ma20 = df.iloc[-1].get('volume', 0)
            avg_daily_volumes[symbol] = float(vol_ma20) * current_prices[symbol]

    exec_result = run_execution(
        execution_orders=execution_orders,
        current_prices=current_prices,
        avg_daily_volumes=avg_daily_volumes,
        current_positions=current_positions,
        cash=cash,
        inception_equity=inception_equity,
        sentiment_factor=macro_result['sentiment_factor']
    )
    print(f"   执行结果数: {len(exec_result.get('execution_results', []))}")
    for r in exec_result.get('execution_results', []):
        print(f"   - {r['symbol']}: 状态={r['status']}, "
              f"价格={r.get('executed_price', 0):.2f}, "
              f"数量={r.get('quantity', 0):.0f}, "
              f"金额={r.get('amount', 0):.0f}")
    print(f"   流动性拒绝: {exec_result.get('liquidity_rejected_symbols', [])}")
    print(f"   数据冻结: {exec_result.get('data_frozen_symbols', [])}")
    summary = exec_result.get('account_summary', {})
    print(f"   账户净值: {summary.get('total_equity', 0):,.0f}")
    print(f"   总收益率: {summary.get('total_return_since_inception', 0):.2f}%")

    # ── Test 9: 左侧捡漏评估 ──
    print(f"\n{'─' * 50}")
    print("🎯 Test 9: 左侧捡漏评估")
    contrarian_env = {
        'vix': 38.0,  # 模拟 VIX>35
        'vix_open': 40.0,  # 模拟长上影线
        'vix_close': 38.0,
    }
    contrarian = evaluate_contrarian_entry(contrarian_env, strategy_candidates, account_equity)
    if contrarian:
        print(f"   左侧试探: {len(contrarian)} 只")
        for e in contrarian:
            print(f"   - {e['symbol']}: 金额={e['approved_amount']:.0f}, "
                  f"止损={e['initial_stop_loss']:.2f}")
    else:
        print("   无左侧试探机会（正常）")

    # ── Test 10: 宏观因子一致性校验 ──
    print(f"\n{'─' * 50}")
    print("🔍 Test 10: 宏观因子一致性校验")
    macro_warnings = check_macro_consistency(approved, macro_result)
    if macro_warnings:
        for w in macro_warnings:
            print(f"   ⚠️ {w[:80]}")
    else:
        print("   ✅ 无宏观逻辑分裂预警")

    # ── Test 11: 强制空仓线测试 ──
    print(f"\n{'─' * 50}")
    print("🚨 Test 11: 强制空仓线测试 (模拟恐慌场景)")
    panic_check = check_force_close(vix=40.0, vix_daily_change_pct=25.0,
                                     daily_pnl=-4000, prev_daily_pnl=-3500,
                                     account_equity=account_equity)
    print(f"   强制空仓: {'⚠️ 是' if panic_check['force_close'] else '否'}")
    for rule in panic_check.get('triggered_rules', []):
        print(f"   - {rule}")
    print(f"   VIX风险等级: {panic_check['vix_risk_level']}")

    # ── 总结 ──
    print("\n" + "=" * 70)
    print("✅ 全流程集成测试完成！")
    print("=" * 70)

    # 清理测试产生的持久化文件
    for f in ['trade_history.md', 'cur_holdings.md', 'finish_holdings.md', 'knowledge_base.json']:
        fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), f)
        if os.path.exists(fp):
            os.remove(fp)
            print(f"   🧹 清理测试文件: {f}")


if __name__ == '__main__':
    try:
        run_full_test()
    except Exception as e:
        import traceback
        print(f"\n❌ 测试失败: {e}")
        traceback.print_exc()
        sys.exit(1)
