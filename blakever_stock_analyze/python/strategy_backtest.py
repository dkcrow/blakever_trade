"""
策略回测模块（Agent 8）
职责：基于历史数据对给定策略进行回测，输出绩效报告。

核心功能：
1. 多周期回测（1y/3y/5y）
2. 过拟合检测（训练集70% vs 测试集30%）
3. 多周期一致性验证（夏普>0.5，最大回撤<30%）
4. 采纳建议判定（年化/最大回撤提升>10%且通过检测→推荐采纳）

注意：完整 Backtrader 集成需要额外依赖，本模块提供基于 pandas 的简化回测引擎，
生产环境可替换为 Backtrader 实现。
"""

import logging
import pandas as pd
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

# 一致性验证阈值
MIN_SHARPE_THRESHOLD = 0.5
MAX_DRAWDOWN_THRESHOLD = 0.30
TRAIN_TEST_SPLIT = 0.70
OVERFIT_UNDERPERFORM_THRESHOLD = 0.30
ADOPTION_IMPROVEMENT_THRESHOLD = 0.10


def _compute_max_drawdown(equity_curve: pd.Series) -> float:
    """计算最大回撤（返回小数，如 0.15 表示 15%）"""
    peak = equity_curve.expanding().max()
    drawdown = (equity_curve - peak) / peak
    return abs(drawdown.min())


def _compute_sharpe(returns: pd.Series, annual_factor: int = 252) -> float:
    """计算年化夏普比率（假设无风险利率=0）"""
    if returns.std() == 0:
        return 0.0
    return returns.mean() / returns.std() * np.sqrt(annual_factor)


def _compute_win_rate(returns: pd.Series) -> float:
    """计算胜率"""
    if len(returns) == 0:
        return 0.0
    return (returns > 0).sum() / len(returns)


def _simulate_strategy(df: pd.DataFrame, strategy_func: callable,
                        params: dict, initial_capital: float = 100000) -> pd.Series:
    """基于策略函数模拟交易，生成权益曲线"""
    signals = strategy_func(df, params)
    close = df['close']
    returns = close.pct_change()
    position = signals.shift(1).fillna(0)
    strategy_returns = returns * position
    trade_cost = abs(position.diff()).fillna(0) * 0.001
    strategy_returns = strategy_returns - trade_cost
    equity = (1 + strategy_returns).cumprod() * initial_capital
    equity.iloc[0] = initial_capital
    return equity


def _default_bull_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """默认牛市策略信号：MA20>MA60 且 收盘>MA20 → 1"""
    ma20 = df.get('ma20', df['close'].rolling(20).mean())
    ma60 = df.get('ma60', df['close'].rolling(60).mean())
    close = df['close']
    return ((ma20 > ma60) & (close > ma20)).astype(int)


def _default_bear_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """默认熊市策略信号：空仓"""
    return pd.Series(0, index=df.index)


def _default_range_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """默认震荡市策略信号：RSI<30买入，RSI>70卖出"""
    rsi = df.get('rsi14', pd.Series(50, index=df.index))
    signal = pd.Series(0, index=df.index)
    signal[rsi < 30] = 1
    signal[rsi > 70] = 0
    return signal.ffill().fillna(0)


def _supertrend_signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """
    Supertrend 策略信号：Supertrend 翻多（st_direction=1）→ 1（满仓），
    Supertrend 翻空（st_direction=-1）→ 0（空仓）。

    配合底仓模式使用时，信号=1代表追加机动仓，信号=0代表减至底仓。
    参数：
    - supertrend_period: ATR 周期（默认10）
    - supertrend_multiplier: ATR 倍数（默认1.5）
    """
    st_direction = df.get('st_direction', pd.Series(1, index=df.index))
    # st_direction=1 → 满仓；st_direction=-1 或其他 → 空仓
    return (st_direction == 1).astype(int)


STRATEGY_SIGNAL_MAP = {
    'bull': _default_bull_signal,
    'bear': _default_bear_signal,
    'range': _default_range_signal,
    'supertrend': _supertrend_signal,
}


def run_single_period_backtest(df: pd.DataFrame, strategy_name: str,
                                strategy_params: dict,
                                strategy_func: Optional[callable] = None,
                                initial_capital: float = 100000) -> dict:
    """
    执行单周期回测。
    Returns: {'sharpe', 'max_drawdown', 'annual_return', 'win_rate', 'total_trades'}
    """
    if df is None or df.empty:
        return {'sharpe': 0, 'max_drawdown': 1.0, 'annual_return': 0,
                'win_rate': 0, 'total_trades': 0}

    if strategy_func is None:
        strategy_func = STRATEGY_SIGNAL_MAP.get(strategy_name, _default_bull_signal)

    try:
        equity = _simulate_strategy(df, strategy_func, strategy_params, initial_capital)
        returns = equity.pct_change().dropna()

        if len(returns) < 20:
            return {'sharpe': 0, 'max_drawdown': 1.0, 'annual_return': 0,
                    'win_rate': 0, 'total_trades': 0}

        sharpe = _compute_sharpe(returns)
        max_dd = _compute_max_drawdown(equity)
        annual_return = (equity.iloc[-1] / equity.iloc[0]) ** (252 / len(returns)) - 1
        win_rate = _compute_win_rate(returns[returns != 0])
        signals = strategy_func(df, strategy_params)
        total_trades = abs(signals.diff()).fillna(0).astype(bool).sum() // 2

        return {
            'sharpe': round(sharpe, 2),
            'max_drawdown': round(max_dd * 100, 1),
            'annual_return': round(annual_return * 100, 1),
            'win_rate': round(win_rate * 100, 1),
            'total_trades': int(total_trades)
        }
    except Exception as e:
        logger.error(f"[Backtest] 单周期回测失败: {e}")
        return {'sharpe': 0, 'max_drawdown': 100, 'annual_return': 0,
                'win_rate': 0, 'total_trades': 0}


def detect_overfit(df: pd.DataFrame, strategy_name: str,
                    strategy_params: dict,
                    strategy_func: Optional[callable] = None) -> dict:
    """
    过拟合检测：训练集（前70%）vs 测试集（后30%）。
    """
    if df is None or len(df) < 60:
        return {'overfit_detected': True, 'overfit_details': '数据不足（<60行）',
                'train_return': 0, 'test_return': 0}

    split_idx = int(len(df) * TRAIN_TEST_SPLIT)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    train_result = run_single_period_backtest(train_df, strategy_name, strategy_params, strategy_func)
    test_result = run_single_period_backtest(test_df, strategy_name, strategy_params, strategy_func)

    train_return = train_result['annual_return']
    test_return = test_result['annual_return']

    overfit_detected = False
    overfit_details = ''

    if train_return > 0:
        underperformance = (train_return - test_return) / abs(train_return)
        if underperformance > OVERFIT_UNDERPERFORM_THRESHOLD:
            overfit_detected = True
            overfit_details = (f"测试集年化收益({test_return:.1f}%)低于训练集({train_return:.1f}%)"
                               f"达{underperformance*100:.0f}%，超过阈值")
    elif train_return <= 0 and test_return <= 0:
        overfit_details = "训练集和测试集均亏损，策略无效"

    return {
        'overfit_detected': overfit_detected,
        'overfit_details': overfit_details,
        'train_return': train_return,
        'test_return': test_result['annual_return']
    }


def check_consistency(period_results: dict) -> dict:
    """
    多周期一致性验证：夏普均>0.5，最大回撤均<30% → 通过；
    单周期不达标 → 标记警告；两周期不达标 → 不予采纳。
    """
    warnings = []
    failed_periods = 0

    for period_name, result in period_results.items():
        sharpe = result.get('sharpe', 0)
        max_dd = result.get('max_drawdown', 100)

        period_warnings = []
        if sharpe < MIN_SHARPE_THRESHOLD:
            period_warnings.append(f"{period_name}周期夏普仅{sharpe}，低于阈值{MIN_SHARPE_THRESHOLD}")
        if max_dd > MAX_DRAWDOWN_THRESHOLD * 100:
            period_warnings.append(f"{period_name}周期最大回撤{max_dd}%，超过阈值")

        if period_warnings:
            failed_periods += 1
            warnings.extend(period_warnings)

    if failed_periods == 0:
        verdict = '通过'
        passed = True
    elif failed_periods == 1:
        verdict = '标记警告'
        passed = True
    else:
        verdict = '不予采纳'
        passed = False

    return {'passed': passed, 'warnings': warnings, 'verdict': verdict}


def run_strategy_backtest(df: pd.DataFrame, strategy_name: str,
                           strategy_params: dict = None,
                           backtest_periods: list = None,
                           strategy_func: Optional[callable] = None,
                           baseline_result: dict = None) -> dict:
    """
    策略回测完整流程，与 Agent 8 Prompt 输出格式对齐。

    Args:
        df:               标准化 OHLCV + 指标 DataFrame
        strategy_name:    策略名称（bull/bear/range 或自定义）
        strategy_params:  策略参数
        backtest_periods: 回测周期列表 ['1y', '3y', '5y']
        strategy_func:    自定义策略信号函数（可选）
        baseline_result:  基准绩效 {'annual_return', 'max_drawdown'}
    """
    if df is None or df.empty:
        return {
            'overfit_detected': True, 'overfit_details': '输入数据为空',
            'period_results': {},
            'consistency_check': {'passed': False, 'warnings': [], 'verdict': '不予采纳'},
            'improvement_ratio': 0, 'recommend_adoption': False, 'optimization_notes': '无数据'
        }

    strategy_params = strategy_params or {}
    backtest_periods = backtest_periods or ['1y', '3y', '5y']

    # Step 1: 多周期回测
    period_results = {}
    period_map = {'1y': 252, '3y': 756, '5y': 1260}

    for period in backtest_periods:
        trading_days = period_map.get(period, 252)
        if len(df) < trading_days:
            logger.warning(f"[Backtest] 数据不足{period}，跳过")
            continue
        period_df = df.tail(trading_days)
        period_results[period] = run_single_period_backtest(
            period_df, strategy_name, strategy_params, strategy_func)

    # Step 2: 过拟合检测
    overfit_result = detect_overfit(df, strategy_name, strategy_params, strategy_func)

    # Step 3: 一致性验证
    consistency_result = check_consistency(period_results)

    # Step 4: 采纳建议
    improvement_ratio = 0.0
    recommend_adoption = False
    optimization_notes = []

    if baseline_result:
        baseline_return = baseline_result.get('annual_return', 0)
        baseline_dd = baseline_result.get('max_drawdown', 100)
        avg_return = np.mean([r['annual_return'] for r in period_results.values()]) if period_results else 0
        avg_dd = np.mean([r['max_drawdown'] for r in period_results.values()]) if period_results else 100

        return_imp = ((avg_return - baseline_return) / abs(baseline_return)) if baseline_return != 0 else 0
        dd_imp = ((baseline_dd - avg_dd) / baseline_dd) if baseline_dd != 0 else 0
        improvement_ratio = round((return_imp + dd_imp) / 2 * 100, 1)

        if (improvement_ratio > ADOPTION_IMPROVEMENT_THRESHOLD * 100
                and consistency_result['passed']
                and not overfit_result['overfit_detected']):
            recommend_adoption = True
        else:
            if overfit_result['overfit_detected']:
                optimization_notes.append("策略存在过拟合风险，建议增加正则化或简化参数")
            if not consistency_result['passed']:
                optimization_notes.append("多周期一致性未通过，策略稳定性不足")
            if improvement_ratio <= ADOPTION_IMPROVEMENT_THRESHOLD * 100:
                optimization_notes.append(f"改善比仅{improvement_ratio:.1f}%，未达阈值")
    else:
        optimization_notes.append("无基准绩效数据，无法计算改善比")

    for period, result in period_results.items():
        if result.get('win_rate', 0) < 45:
            optimization_notes.append(f"{period}周期胜率仅{result['win_rate']:.0f}%，建议优化入场条件")
        if result.get('sharpe', 0) < 0.3:
            optimization_notes.append(f"{period}周期夏普仅{result['sharpe']:.1f}，风险调整后收益不足")

    return {
        'overfit_detected': overfit_result['overfit_detected'],
        'overfit_details': overfit_result['overfit_details'],
        'period_results': period_results,
        'consistency_check': consistency_result,
        'improvement_ratio': improvement_ratio,
        'recommend_adoption': recommend_adoption,
        'optimization_notes': '；'.join(optimization_notes) if optimization_notes else '暂无优化建议'
    }
