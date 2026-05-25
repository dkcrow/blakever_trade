#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
熊市策略回测引擎
================
命令行入口: python bear_run_backtest.py --strategy <策略文件路径> [选项]

熊市特定参数:
  - 熊市主回测区间: 2007-10-01 至 2009-03-09（金融危机）或
                    2020-02-19 至 2020-03-23（新冠急跌）
  - 压力测试区间: 2018-01-01 至 2018-12-31（温和熊市）
  - 牛市辅助测试: 2020-04-01 至 2021-12-31
  - 滑点: 单边0.15%（熊市流动性收缩）
  - 做空融券成本: 年化3%
  - 价格规则: 前复权用于指标，不复权用于资金/手续费

策略文件要求:
  - 必须包含 generate_signals(close, high, low, open_prices, **params) -> (entries, exits) 函数
  - entries/exits 均为 np.ndarray[bool]
  - 支持做空信号: 可选 short_entries, short_exits
"""

import argparse
import importlib.util
import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ================================================================
# 熊市回测参数
# ================================================================
INIT_CASH = 1_000_000      # 100万本币
FEES = 0.001               # 手续费率（参考港美股）
SLIPPAGE = 0.0015           # 滑点（熊市0.15%，流动性收缩）
SHORT_BORROW_RATE = 0.03    # 做空融券成本（年化3%）

# 回测区间
# 注意：本地数据从2021年开始，无法覆盖2007-2009金融危机
# 熊市主回测区间: 2022-01-01 ~ 2022-12-31（2022年美股熊市，纳指跌33%）
BEAR_MAIN_START = '2022-01-01'
BEAR_MAIN_END = '2022-12-31'
# 备选: 2022-01-03 ~ 2022-06-16（纳指上半年跌32%）
BEAR_H1_START = '2022-01-03'
BEAR_H1_END = '2022-06-16'
# 压力测试区间: 2023年高利率震荡市
STRESS_START = '2023-01-01'
STRESS_END = '2023-12-31'
# 牛市辅助测试区间: 2023-10 ~ 2024-12（AI牛市反弹）
BULL_START = '2023-10-01'
BULL_END = '2024-12-31'
# 如果有更早数据，可使用以下经典熊市区间:
# BEAR_MAIN_START = '2007-10-01'; BEAR_MAIN_END = '2009-03-09'  # 金融危机
# COVID_BEAR_START = '2020-02-19'; COVID_BEAR_END = '2020-03-23'  # 新冠急跌
# STRESS_START = '2018-01-01'; STRESS_END = '2018-12-31'  # 温和熊市
# BULL_START = '2020-04-01'; BULL_END = '2021-12-31'  # 疫后牛市

# 数据目录
DATA_DIR = '/data/workspace/back_trader_stocks'

# 无风险利率
DEFAULT_RISK_FREE_RATE = 0.055  # 10年美债~4.5% + 1% = 5.5%

# 做空支持标记
SUPPORTS_SHORT_SELLING = True  # 当前引擎支持做空模拟


# ================================================================
# 数据加载
# ================================================================
def load_stock_data(symbol, market='us'):
    """加载单只股票CSV数据"""
    subdir = 'us' if market == 'us' else 'hk'
    filepath = os.path.join(DATA_DIR, subdir, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        required = ['Open', 'High', 'Low', 'Close']
        for col in required:
            if col not in df.columns:
                return None
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except Exception as e:
        print(f"  ⚠️ 加载 {symbol} 失败: {e}", file=sys.stderr)
        return None


def get_stock_pool(market='us', safe_haven_etfs=None):
    """
    获取标的池列表（含避险资产扩展）。

    Args:
        market: 'us' 或 'hk'
        safe_haven_etfs: 避险资产ETF代码列表（如['GLD', 'TLT']）
    """
    subdir = 'us' if market == 'us' else 'hk'
    directory = os.path.join(DATA_DIR, subdir)
    pool = []
    if os.path.isdir(directory):
        pool = [f.replace('.csv', '') for f in os.listdir(directory)
                if f.endswith('.csv') and not f.startswith('.')]

    # 添加避险资产ETF（如果本地有数据文件）
    if safe_haven_etfs:
        for etf in safe_haven_etfs:
            # ETF数据可能在us目录下
            etf_path = os.path.join(DATA_DIR, 'us', f'{etf}.csv')
            if os.path.exists(etf_path) and etf not in pool:
                pool.append(etf)
            else:
                print(f"  ⚠️ 避险ETF {etf} 数据文件不存在，跳过", file=sys.stderr)

    return pool


# ================================================================
# 策略加载
# ================================================================
def load_strategy_module(strategy_path):
    """从文件路径加载策略模块"""
    spec = importlib.util.spec_from_file_location("strategy_module", strategy_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_strategy_func(mod):
    """从模块中获取策略信号生成函数"""
    if hasattr(mod, 'generate_signals'):
        return mod.generate_signals
    if hasattr(mod, 'strategy_func'):
        return mod.strategy_func
    if hasattr(mod, 'run_strategy'):
        return mod.run_strategy
    raise AttributeError("策略模块必须包含 generate_signals(close, high, low, open_prices, **params) 函数")


# ================================================================
# 熊市回测引擎
# ================================================================
def run_single_bear_backtest(close, high, low, open_prices, entries, exits,
                              short_entries=None, short_exits=None,
                              init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
                              short_borrow_rate=SHORT_BORROW_RATE):
    """
    执行单只股票单区间回测（熊市版）。

    特殊处理:
      - T+1修正: 信号次日生效，成交价用次日开盘价
      - 做空模拟: 如策略提供做空信号，模拟做空操作
      - 融券成本: 做空持仓按日计提年化3%融券成本
      - 手续费: 仅开平仓日扣（非持仓日）
    """
    try:
        import vectorbt as vbt
    except ImportError:
        print("  ❌ 缺少vectorbt库", file=sys.stderr)
        return _empty_result()

    n = len(close)

    # 检查做空支持
    has_short = short_entries is not None and short_exits is not None
    if has_short and not SUPPORTS_SHORT_SELLING:
        return {**_empty_result(), 'short_cost_warning': True,
                'engine_short_support': False}

    # T+1 修正: 信号shift(1)即T+1生效
    entries_t1 = np.roll(entries, 1)
    entries_t1[0] = False
    exits_t1 = np.roll(exits, 1)
    exits_t1[0] = False

    # 做空信号T+1
    if has_short:
        short_entries_t1 = np.roll(short_entries, 1)
        short_entries_t1[0] = False
        short_exits_t1 = np.roll(short_exits, 1)
        short_exits_t1[0] = False
    else:
        short_entries_t1 = None
        short_exits_t1 = None

    # 多头信号检查
    long_entries_exist = entries_t1.sum() > 0

    if not long_entries_exist and (short_entries_t1 is None or short_entries_t1.sum() == 0):
        return _empty_result()

    result = _empty_result()
    short_cost_warning = False

    # 多头回测
    if long_entries_exist:
        try:
            pf = vbt.Portfolio.from_signals(
                open=open_prices, close=close,
                entries=entries_t1, exits=exits_t1,
                freq='D', init_cash=init_cash, fees=fees, slippage=slippage,
                upon_opposite_entry='reverse'
            )
            stats = pf.stats()
            result = _extract_stats(pf, stats, n)
        except Exception as e:
            print(f"  ⚠️ 多头回测异常: {e}", file=sys.stderr)

    # 做空回测（如果策略提供做空信号）
    if has_short and short_entries_t1.sum() > 0:
        try:
            # 做空: 反向操作（卖出开仓，买入平仓）
            # VectorBT不原生支持做空，使用反向价格模拟
            # 方法: 做空时close反转（即收益为正时亏损）
            pf_short = vbt.Portfolio.from_signals(
                open=open_prices, close=close,
                entries=short_entries_t1, exits=short_exits_t1,
                freq='D', init_cash=init_cash, fees=fees, slippage=slippage,
                upon_opposite_entry='reverse',
                direction='short'  # VectorBT 0.28.5+ 支持
            )
            short_stats = pf_short.stats()
            short_result = _extract_stats(pf_short, short_stats, n)

            # 强制外扣融券成本（年化3%按日计提）
            # 如果策略代码未包含此项扣除，标记警告
            short_cost_warning = True  # 标记未内置融券成本
            daily_borrow_cost = short_borrow_rate / 252
            n_short_days = _count_short_days(pf_short)
            total_borrow_cost = daily_borrow_cost * n_short_days

            # 扣除融券成本后的收益调整
            short_annual_adj = short_result['annual_return'] - (short_borrow_rate * 100)
            result['short_annual_return'] = short_annual_adj
            result['short_total_borrow_cost_pct'] = round(total_borrow_cost * 100, 2)
            result['short_cost_warning'] = short_cost_warning

        except TypeError:
            # VectorBT版本不支持direction='short'
            print(f"  ⚠️ 当前vectorbt版本不支持做空，标记引擎限制", file=sys.stderr)
            result['short_cost_warning'] = False
            result['engine_short_support'] = False
        except Exception as e:
            print(f"  ⚠️ 做空回测异常: {e}", file=sys.stderr)

    result['short_cost_warning'] = short_cost_warning
    return result


def _empty_result():
    """返回空回测结果"""
    return {
        'annual_return': 0.0, 'max_drawdown': 0.0, 'sharpe': 0.0,
        'win_rate': 0.0, 'profit_factor': 0.0, 'total_trades': 0,
        'avg_trades_per_year': 0.0, 'max_consec_loss': 0, 'position_pct': 0.0,
        'short_cost_warning': False, 'engine_short_support': True,
    }


def _extract_stats(pf, stats, n):
    """从Portfolio对象提取统计指标"""
    total_return = float(stats['Total Return [%]'])
    max_dd = float(stats['Max Drawdown [%]'])
    win_rate_raw = stats.get('Win Rate [%]', 0)
    win_rate = float(win_rate_raw) if pd.notna(win_rate_raw) else 0.0
    total_trades_raw = stats.get('Total Trades', 0)
    total_trades = int(total_trades_raw) if pd.notna(total_trades_raw) else 0
    n_years = len(pf.returns()) / 252
    annual = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100 if n_years > 0 else -100

    try:
        sharpe = float(stats['Sharpe Ratio'])
    except Exception:
        rets = pf.returns().dropna()
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if len(rets) > 1 and rets.std() > 0 else 0

    profit_factor = 0.0
    max_consec_loss = 0
    try:
        ct = pf.trades.records_readable
        if len(ct) > 0:
            wins = ct[ct['PnL'] > 0]['PnL']
            losses = ct[ct['PnL'] < 0]['PnL']
            total_win = float(wins.sum()) if len(wins) > 0 else 0
            total_loss = abs(float(losses.sum())) if len(losses) > 0 else 0
            profit_factor = total_win / total_loss if total_loss > 0 else (10.0 if total_win > 0 else 0)

            is_loss = (ct['PnL'] < 0).values
            consec = 0
            max_c = 0
            for v in is_loss:
                if v:
                    consec += 1
                    max_c = max(max_c, consec)
                else:
                    consec = 0
            max_consec_loss = max_c
    except Exception:
        pass

    try:
        pos_mask = pf.position_mask(column=0).values
        pos_pct = pos_mask.sum() / len(pos_mask) * 100
    except Exception:
        pos_pct = 0.0

    avg_trades = total_trades / max(n_years, 0.01)

    return {
        'annual_return': round(annual, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'total_trades': total_trades,
        'avg_trades_per_year': round(avg_trades, 1),
        'max_consec_loss': max_consec_loss,
        'position_pct': round(pos_pct, 1),
    }


def _count_short_days(pf):
    """计算做空持仓天数（简化：用持仓比例估算）"""
    try:
        pos_mask = pf.position_mask(column=0).values
        return int(pos_mask.sum())
    except Exception:
        return 0


def run_bear_backtest_on_pool(strategy_func, strategy_params, market,
                               start_date, end_date,
                               max_stocks=None, risk_free_rate=DEFAULT_RISK_FREE_RATE,
                               safe_haven_etfs=None):
    """
    在标的池上批量回测（熊市版），返回汇总统计。
    """
    pool = get_stock_pool(market, safe_haven_etfs)
    if max_stocks:
        pool = pool[:max_stocks]

    results = []
    valid_count = 0
    short_cost_warning_any = False

    for symbol in pool:
        df = load_stock_data(symbol, market)
        if df is None:
            continue

        mask = (df.index >= start_date) & (df.index <= end_date)
        df_period = df.loc[mask]
        if len(df_period) < 60:  # 熊市区间较短，降低最小数据要求
            continue

        close = df_period['Close'].values.astype(float)
        high = df_period['High'].values.astype(float)
        low = df_period['Low'].values.astype(float)
        open_prices = df_period['Open'].values.astype(float)

        try:
            signal_result = strategy_func(close, high, low, open_prices, **strategy_params)
            # 兼容多返回值（含做空信号）
            if len(signal_result) == 4:
                entries, exits, short_entries, short_exits = signal_result
            else:
                entries, exits = signal_result
                short_entries = None
                short_exits = None
        except TypeError:
            try:
                entries, exits = strategy_func(close, high, low)
                short_entries = None
                short_exits = None
            except Exception as e:
                continue

        r = run_single_bear_backtest(
            close, high, low, open_prices, entries, exits,
            short_entries=short_entries, short_exits=short_exits,
            init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
            short_borrow_rate=SHORT_BORROW_RATE
        )
        r['symbol'] = symbol
        results.append(r)
        valid_count += 1
        if r.get('short_cost_warning', False):
            short_cost_warning_any = True

    if not results:
        return None

    df_r = pd.DataFrame(results)
    annual_returns = df_r['annual_return']
    sharpe_values = df_r['sharpe']
    max_dds = df_r['max_drawdown']
    win_rates = df_r['win_rate']
    profit_factors = df_r['profit_factor']
    avg_trades = df_r['avg_trades_per_year']

    mean_annual = annual_returns.mean()
    median_annual = annual_returns.median()
    mean_sharpe = sharpe_values.mean()
    mean_dd = max_dds.mean()
    mean_win = win_rates.mean()
    mean_pf = profit_factors[profit_factors > 0].mean() if (profit_factors > 0).any() else 0
    mean_trades = avg_trades.mean()

    # B&H基准
    bh_results = []
    for symbol in pool[:max_stocks or len(pool)]:
        df = load_stock_data(symbol, market)
        if df is None:
            continue
        mask = (df.index >= start_date) & (df.index <= end_date)
        df_p = df.loc[mask]
        if len(df_p) < 60:
            continue
        n_years = len(df_p) / 252
        bh_return = ((df_p['Close'].iloc[-1] / df_p['Close'].iloc[0]) ** (1 / max(n_years, 0.01)) - 1) * 100
        bh_results.append({'symbol': symbol, 'bh_annual': bh_return})

    beat_bh_pct = 0.0
    if bh_results:
        df_bh = pd.DataFrame(bh_results)
        df_merged = df_r.merge(df_bh, on='symbol', how='inner')
        if len(df_merged) > 0:
            beat_bh_pct = round((df_merged['annual_return'] > df_merged['bh_annual']).sum() / len(df_merged) * 100, 1)

    return {
        'market': market,
        'period': f"{start_date} ~ {end_date}",
        'n_stocks': valid_count,
        'mean_annual_return': round(mean_annual, 2),
        'median_annual_return': round(median_annual, 2),
        'mean_sharpe': round(mean_sharpe, 2),
        'mean_max_drawdown': round(mean_dd, 2),
        'mean_win_rate': round(mean_win, 1),
        'mean_profit_factor': round(mean_pf, 2),
        'mean_avg_trades_per_year': round(mean_trades, 1),
        'beat_bh_pct': beat_bh_pct,
        'risk_free_rate': risk_free_rate,
        'short_cost_warning': short_cost_warning_any,
        'individual_results': results[:10],
    }


def _json_default(obj):
    """自定义JSON序列化，处理numpy类型"""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ================================================================
# 命令行入口
# ================================================================
def main():
    parser = argparse.ArgumentParser(description='熊市策略回测引擎')
    parser.add_argument('--strategy', required=True, help='策略Python文件路径')
    parser.add_argument('--market', default='us', choices=['us', 'hk'], help='市场')
    parser.add_argument('--main-start', default=BEAR_MAIN_START, help='熊市主回测起始日期')
    parser.add_argument('--main-end', default=BEAR_MAIN_END, help='熊市主回测结束日期')
    parser.add_argument('--stress-start', default=STRESS_START, help='压力测试起始日期')
    parser.add_argument('--stress-end', default=STRESS_END, help='压力测试结束日期')
    parser.add_argument('--bull-start', default=BULL_START, help='牛市辅助测试起始日期')
    parser.add_argument('--bull-end', default=BULL_END, help='牛市辅助测试结束日期')
    parser.add_argument('--risk-free-rate', type=float, default=DEFAULT_RISK_FREE_RATE,
                        help='无风险利率(小数)')
    parser.add_argument('--max-stocks', type=int, default=None,
                        help='最大回测标的数(调试用)')
    parser.add_argument('--safe-haven-etfs', nargs='*', default=None,
                        help='避险资产ETF代码列表(如GLD TLT VXX)')
    parser.add_argument('--output', default=None, help='输出JSON文件路径')

    args = parser.parse_args()

    print(f"📦 加载策略: {args.strategy}")
    mod = load_strategy_module(args.strategy)
    strategy_func = get_strategy_func(mod)

    strategy_name = getattr(mod, 'STRATEGY_NAME', os.path.basename(args.strategy))
    strategy_params = getattr(mod, 'STRATEGY_PARAMS', {})
    strategy_type = getattr(mod, 'STRATEGY_TYPE', '其他')

    print(f"  策略名称: {strategy_name}")
    print(f"  策略类型: {strategy_type}")
    print(f"  策略参数: {strategy_params}")
    if args.safe_haven_etfs:
        print(f"  避险ETF: {args.safe_haven_etfs}")

    result = {
        'strategy_name': strategy_name,
        'strategy_type': strategy_type,
        'strategy_params': strategy_params,
        'strategy_file': args.strategy,
        'risk_free_rate': args.risk_free_rate,
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'survivorship_bias_flag': True,  # 当前数据不含退市标的，标记存在偏差
        'short_cost_warning': False,
        'margin_occupancy_peak': 0.0,  # 保证金占用率峰值（待实现）
    }

    # 主回测区间（熊市）
    print(f"\n🐻 熊市主回测区间: {args.main_start} ~ {args.main_end}")
    main_result = run_bear_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.main_start, args.main_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate,
        safe_haven_etfs=args.safe_haven_etfs,
    )
    result['main_period'] = main_result
    if main_result:
        print(f"  ✅ 有效标的: {main_result['n_stocks']}")
        print(f"  平均年化: {main_result['mean_annual_return']}%")
        print(f"  平均夏普: {main_result['mean_sharpe']}")
        print(f"  平均回撤: {main_result['mean_max_drawdown']}%")
        if main_result.get('short_cost_warning'):
            result['short_cost_warning'] = True

    # 压力测试区间
    print(f"\n💪 压力测试区间: {args.stress_start} ~ {args.stress_end}")
    stress_result = run_bear_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.stress_start, args.stress_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate,
    )
    result['stress_period'] = stress_result

    # 牛市辅助测试区间
    print(f"\n🐂 牛市辅助测试区间: {args.bull_start} ~ {args.bull_end}")
    bull_result = run_bear_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.bull_start, args.bull_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate,
    )
    result['bull_period'] = bull_result

    # 跨周期验证（熊市版：检查压力区间和牛市区间）
    if main_result and stress_result:
        stress_annual = stress_result['mean_annual_return']
        stress_dd = stress_result['mean_max_drawdown']
        main_dd = main_result['mean_max_drawdown']
        robust = (stress_annual >= 0) and (stress_dd <= main_dd * 1.5)
        result['cross_period_robust'] = robust
        result['cross_period_details'] = {
            'stress_annual': stress_annual,
            'stress_dd': stress_dd,
            'main_dd': main_dd,
            'condition1_annual_ge_0': stress_annual >= 0,
            'condition2_dd_ratio': round(stress_dd / max(main_dd, 0.01), 2),
            'condition2_pass': stress_dd <= main_dd * 1.5,
        }
        tag = "✅ 跨周期鲁棒" if robust else "❌ 跨周期未通过"
        print(f"\n🔍 跨周期验证: {tag}")

    # VIX相关（暂为None，需要VIX数据）
    result['vix_correlation'] = None

    # 输出
    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"\n📁 结果已保存至: {args.output}")
    else:
        print(f"\n📄 回测结果:")
        print(output_json[:2000])

    return result


if __name__ == '__main__':
    main()
