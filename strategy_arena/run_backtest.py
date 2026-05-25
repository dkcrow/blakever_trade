#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用策略回测引擎
================
命令行入口: python run_backtest.py --strategy <策略文件路径> [选项]

功能:
  - 加载策略Python模块，自动发现策略函数
  - 在港美股历史数据上执行回测
  - 输出JSON格式的完整回测报告

策略文件要求:
  - 必须包含 generate_signals(close, high, low, open_prices, **params) -> (entries, exits) 函数
  - entries/exits 均为 np.ndarray[bool]
  - 可选: STRATEGY_NAME, STRATEGY_PARAMS, STRATEGY_TYPE 常量
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
import talib
import vectorbt as vbt

warnings.filterwarnings('ignore')

# ================================================================
# 默认参数
# ================================================================
INIT_CASH = 1_000_000  # 100万本币
FEES = 0.001           # 手续费率
SLIPPAGE = 0.001       # 滑点

# 回测区间
MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'
STRESS_START = '2015-01-01'
STRESS_END = '2018-12-31'

# 数据目录
DATA_DIR = '/data/workspace/back_trader_stocks'

# 无风险利率（默认值，运行时从命令行覆盖）
DEFAULT_RISK_FREE_RATE = 0.045  # 10年美债 ~4.5% + 1%


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
        # 标准化列名
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


def get_stock_pool(market='us'):
    """获取标的池列表"""
    subdir = 'us' if market == 'us' else 'hk'
    directory = os.path.join(DATA_DIR, subdir)
    if not os.path.isdir(directory):
        return []
    return [f.replace('.csv', '') for f in os.listdir(directory)
            if f.endswith('.csv') and not f.startswith('.')]


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
    # 优先查找 generate_signals
    if hasattr(mod, 'generate_signals'):
        return mod.generate_signals
    # 兼容: 查找 strategy_func
    if hasattr(mod, 'strategy_func'):
        return mod.strategy_func
    # 兼容: 查找 run_strategy
    if hasattr(mod, 'run_strategy'):
        return mod.run_strategy
    raise AttributeError("策略模块必须包含 generate_signals(close, high, low, open_prices, **params) 函数")


# ================================================================
# 回测引擎
# ================================================================
def run_single_backtest(close, high, low, open_prices, entries, exits,
                        init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE):
    """执行单只股票单区间回测"""
    n = len(close)
    if entries.sum() == 0:
        return {
            'annual_return': 0.0, 'max_drawdown': 0.0, 'sharpe': 0.0,
            'win_rate': 0.0, 'profit_factor': 0.0, 'total_trades': 0,
            'avg_trades_per_year': 0.0, 'max_consec_loss': 0, 'position_pct': 0.0,
        }

    # T+1 修正: 信号次日生效
    entries_t1 = np.roll(entries, 1)
    entries_t1[0] = False
    exits_t1 = np.roll(exits, 1)
    exits_t1[0] = False

    if entries_t1.sum() == 0:
        return {
            'annual_return': 0.0, 'max_drawdown': 0.0, 'sharpe': 0.0,
            'win_rate': 0.0, 'profit_factor': 0.0, 'total_trades': 0,
            'avg_trades_per_year': 0.0, 'max_consec_loss': 0, 'position_pct': 0.0,
        }

    try:
        pf = vbt.Portfolio.from_signals(
            open=open_prices, close=close,
            entries=entries_t1, exits=exits_t1,
            freq='D', init_cash=init_cash, fees=fees, slippage=slippage,
            upon_opposite_entry='reverse'
        )

        stats = pf.stats()
        total_return = float(stats['Total Return [%]'])
        max_dd = float(stats['Max Drawdown [%]'])
        win_rate_raw = stats.get('Win Rate [%]', 0)
        win_rate = float(win_rate_raw) if pd.notna(win_rate_raw) else 0.0
        total_trades_raw = stats.get('Total Trades', 0)
        total_trades = int(total_trades_raw) if pd.notna(total_trades_raw) else 0
        n_years = len(pf.returns()) / 252
        annual = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100 if n_years > 0 else -100

        # 夏普比率
        try:
            sharpe = float(stats['Sharpe Ratio'])
        except Exception:
            rets = pf.returns().dropna()
            sharpe = rets.mean() / rets.std() * np.sqrt(252) if len(rets) > 1 and rets.std() > 0 else 0

        # 盈亏比
        profit_factor = 0.0
        max_consec_loss = 0
        try:
            ct = pf.trades.records_readable
            if len(ct) > 0:
                wins = ct[ct['PnL'] > 0]['PnL']
                losses = ct[ct['PnL'] < 0]['PnL']
                total_win = float(wins.sum()) if len(wins) > 0 else 0
                total_loss = abs(float(losses.sum())) if len(losses) > 0 else 0
                if total_loss > 0:
                    profit_factor = total_win / total_loss
                elif total_win > 0:
                    profit_factor = 10.0  # 全胜，上限10

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

        # 持仓比例
        try:
            pos_mask = pf.position_mask(column=0).values
            pos_pct = pos_mask.sum() / len(pos_mask) * 100
        except Exception:
            pos_pct = 0.0

        # 单标年平均交易次数
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
    except Exception as e:
        print(f"  ⚠️ 回测执行异常: {e}", file=sys.stderr)
        return {
            'annual_return': 0.0, 'max_drawdown': 100.0, 'sharpe': 0.0,
            'win_rate': 0.0, 'profit_factor': 0.0, 'total_trades': 0,
            'avg_trades_per_year': 0.0, 'max_consec_loss': 0, 'position_pct': 0.0,
        }


def run_backtest_on_pool(strategy_func, strategy_params, market, start_date, end_date,
                         max_stocks=None, risk_free_rate=DEFAULT_RISK_FREE_RATE):
    """在标的池上批量回测，返回汇总统计"""
    pool = get_stock_pool(market)
    if max_stocks:
        pool = pool[:max_stocks]

    results = []
    valid_count = 0

    for symbol in pool:
        df = load_stock_data(symbol, market)
        if df is None:
            continue

        # 截取时间区间
        mask = (df.index >= start_date) & (df.index <= end_date)
        df_period = df.loc[mask]
        if len(df_period) < 100:
            continue

        close = df_period['Close'].values.astype(float)
        high = df_period['High'].values.astype(float)
        low = df_period['Low'].values.astype(float)
        open_prices = df_period['Open'].values.astype(float)

        try:
            entries, exits = strategy_func(close, high, low, open_prices, **strategy_params)
        except TypeError:
            try:
                entries, exits = strategy_func(close, high, low)
            except Exception as e:
                print(f"  ⚠️ {symbol} 策略函数调用失败: {e}", file=sys.stderr)
                continue

        r = run_single_backtest(close, high, low, open_prices, entries, exits)
        r['symbol'] = symbol
        results.append(r)
        valid_count += 1

    if not results:
        return None

    # 汇总统计
    df_r = pd.DataFrame(results)
    annual_returns = df_r['annual_return']
    sharpe_values = df_r['sharpe']
    max_dds = df_r['max_drawdown']
    win_rates = df_r['win_rate']
    profit_factors = df_r['profit_factor']
    avg_trades = df_r['avg_trades_per_year']

    # 等权组合指标
    mean_annual = annual_returns.mean()
    median_annual = annual_returns.median()
    mean_sharpe = sharpe_values.mean()
    mean_dd = max_dds.mean()
    mean_win = win_rates.mean()
    mean_pf = profit_factors[profit_factors > 0].mean() if (profit_factors > 0).any() else 0
    mean_trades = avg_trades.mean()

    # 胜B&H占比
    bh_results = []
    for symbol in pool[:max_stocks or len(pool)]:
        df = load_stock_data(symbol, market)
        if df is None:
            continue
        mask = (df.index >= start_date) & (df.index <= end_date)
        df_p = df.loc[mask]
        if len(df_p) < 100:
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

    # 修正夏普（减去无风险利率）
    adj_sharpe = mean_sharpe  # VectorBT输出的夏普已考虑，此处暂用原始值

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
        'individual_results': results[:10],  # 保留前10只详细信息
    }


# ================================================================
# 命令行入口
# ================================================================
def main():
    parser = argparse.ArgumentParser(description='通用策略回测引擎')
    parser.add_argument('--strategy', required=True, help='策略Python文件路径')
    parser.add_argument('--market', default='us', choices=['us', 'hk'], help='市场')
    parser.add_argument('--main-start', default=MAIN_START, help='主回测起始日期')
    parser.add_argument('--main-end', default=MAIN_END, help='主回测结束日期')
    parser.add_argument('--stress-start', default=STRESS_START, help='压力测试起始日期')
    parser.add_argument('--stress-end', default=STRESS_END, help='压力测试结束日期')
    parser.add_argument('--risk-free-rate', type=float, default=DEFAULT_RISK_FREE_RATE,
                        help='无风险利率(小数)')
    parser.add_argument('--max-stocks', type=int, default=None,
                        help='最大回测标的数(调试用)')
    parser.add_argument('--output', default=None, help='输出JSON文件路径')

    args = parser.parse_args()

    # 加载策略
    print(f"📦 加载策略: {args.strategy}")
    mod = load_strategy_module(args.strategy)
    strategy_func = get_strategy_func(mod)

    strategy_name = getattr(mod, 'STRATEGY_NAME', os.path.basename(args.strategy))
    strategy_params = getattr(mod, 'STRATEGY_PARAMS', {})
    strategy_type = getattr(mod, 'STRATEGY_TYPE', '其他')

    print(f"  策略名称: {strategy_name}")
    print(f"  策略类型: {strategy_type}")
    print(f"  策略参数: {strategy_params}")

    result = {
        'strategy_name': strategy_name,
        'strategy_type': strategy_type,
        'strategy_params': strategy_params,
        'strategy_file': args.strategy,
        'risk_free_rate': args.risk_free_rate,
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'survivorship_bias_flag': bool(True),  # 当前数据不含退市标的，标记存在偏差
    }

    # 主回测区间
    print(f"\n🚀 主回测区间: {args.main_start} ~ {args.main_end}")
    main_result = run_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.main_start, args.main_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate
    )
    result['main_period'] = main_result
    if main_result:
        print(f"  ✅ 有效标的: {main_result['n_stocks']}")
        print(f"  平均年化: {main_result['mean_annual_return']}%")
        print(f"  平均夏普: {main_result['mean_sharpe']}")
        print(f"  平均回撤: {main_result['mean_max_drawdown']}%")
        print(f"  胜B&H: {main_result['beat_bh_pct']}%")

    # 压力测试区间
    print(f"\n💪 压力测试区间: {args.stress_start} ~ {args.stress_end}")
    stress_result = run_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.stress_start, args.stress_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate
    )
    result['stress_period'] = stress_result
    if stress_result:
        print(f"  ✅ 有效标的: {stress_result['n_stocks']}")
        print(f"  平均年化: {stress_result['mean_annual_return']}%")
        print(f"  平均夏普: {stress_result['mean_sharpe']}")
        print(f"  平均回撤: {stress_result['mean_max_drawdown']}%")

    # 跨周期验证
    if main_result and stress_result:
        stress_annual = stress_result['mean_annual_return']
        stress_dd = stress_result['mean_max_drawdown']
        main_dd = main_result['mean_max_drawdown']
        robust = (stress_annual >= 0) and (stress_dd <= main_dd * 1.5)
        result['cross_period_robust'] = bool(robust)
        result['cross_period_details'] = {
            'stress_annual': stress_annual,
            'stress_dd': stress_dd,
            'main_dd': main_dd,
            'condition1_annual_ge_0': bool(stress_annual >= 0),
            'condition2_dd_ratio': round(stress_dd / max(main_dd, 0.01), 2),
            'condition2_pass': bool(stress_dd <= main_dd * 1.5),
        }
        tag = "✅ 跨周期鲁棒" if robust else "❌ 跨周期未通过"
        print(f"\n🔍 跨周期验证: {tag}")

    # 输出
    # 自定义JSON编码器：处理numpy bool_等类型
    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.bool_, np.integer)):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)

    output_json = json.dumps(result, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"\n📁 结果已保存至: {args.output}")
    else:
        print(f"\n📄 回测结果:")
        print(output_json)

    return result


if __name__ == '__main__':
    main()
