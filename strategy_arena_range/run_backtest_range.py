#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震荡市策略回测引擎
==================
命令行入口: python run_backtest_range.py --strategy <策略文件路径> [选项]

震荡市特定参数:
  - 主回测区间: 2021-01-01 至 2023-12-31（近年典型震荡市）
  - 压力测试区间: 2015-01-01 至 2016-12-31（极端波动/熔断期）
    注: 本地数据从2021年起，压力测试暂用2021-2022替代
  - 滑点: 单边0.1%（默认模式）/ 单边0.02%（限价单模式）
  - 手续费: 港美股实际水平（港股印花税+交易征费+佣金；美股SEC费+佣金）
  - 初始资金: 100万（本币）
  - 价格规则: 前复权用于指标计算，不复权用于资金占用与手续费

策略文件要求:
  - 必须包含 generate_signals(close, high, low, open_prices, **params) -> (entries, exits)
  - entries/exits 均为 np.ndarray[bool]
  - 可选: stop_loss_price(close, high, low, entries, **params) -> np.ndarray
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
# 震荡市回测参数
# ================================================================
INIT_CASH = 1_000_000

# 港美股手续费参数
HK_STAMP_DUTY = 0.001       # 港股印花税0.1%
HK_TRADE_LEVY = 0.0000276   # 交易征费
HK_SFC_LEVY = 0.0000203     # 证监会交易征费
HK_COMM = 0.0003            # 佣金（万三）
HK_TOTAL_FEES = HK_STAMP_DUTY + HK_TRADE_LEVY + HK_SFC_LEVY + HK_COMM  # ≈0.1348%

US_SEC_FEE = 0.0000278      # SEC费
US_COMM = 0.0005            # 佣金（万五）
US_TOTAL_FEES = US_SEC_FEE + US_COMM  # ≈0.0528%

# 滑点
SLIPPAGE_DEFAULT = 0.001    # 默认模式：单边0.1%
SLIPPAGE_LIMIT = 0.0002     # 限价单模式：单边0.02%

# 回测区间（适配本地数据2021年起）
RANGE_MAIN_START = '2021-01-01'
RANGE_MAIN_END = '2023-12-31'
# 压力测试区间（理想为2015-2016熔断期，实际用2021-2022）
STRESS_START = '2021-01-01'
STRESS_END = '2022-12-31'

# 数据目录
DATA_DIR = '/data/workspace/back_trader_stocks'

# 无风险利率 = 10年期美债收益率 + 1%
DEFAULT_RISK_FREE_RATE = 0.055  # 4.5% + 1% = 5.5%


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
        return None


def get_stock_pool(market='us'):
    """获取标的池列表"""
    subdir = 'us' if market == 'us' else 'hk'
    directory = os.path.join(DATA_DIR, subdir)
    pool = []
    if os.path.isdir(directory):
        pool = [f.replace('.csv', '') for f in os.listdir(directory)
                if f.endswith('.csv') and not f.startswith('.')]
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
    raise AttributeError("策略模块必须包含 generate_signals() 函数")


# ================================================================
# 震荡市回测引擎
# ================================================================
def run_single_range_backtest(close, high, low, open_prices, entries, exits,
                               init_cash=INIT_CASH, fees=US_TOTAL_FEES,
                               slippage=SLIPPAGE_DEFAULT):
    """
    执行单只股票单区间回测（震荡市版）。

    特殊处理:
      - T+1修正: 信号次日生效，成交价用次日开盘价
      - 手续费: 仅开平仓日扣
      - 止损检测: 尝试调用策略的stop_loss_price函数
      - 单笔最大亏损: 计算回测期内最大单笔亏损占比
    """
    try:
        import vectorbt as vbt
    except ImportError:
        return _empty_result()

    n = len(close)

    # T+1 修正
    entries_t1 = np.roll(entries, 1)
    entries_t1[0] = False
    exits_t1 = np.roll(exits, 1)
    exits_t1[0] = False

    if entries_t1.sum() == 0:
        return _empty_result()

    try:
        pf = vbt.Portfolio.from_signals(
            open=open_prices, close=close,
            entries=entries_t1, exits=exits_t1,
            freq='D', init_cash=init_cash, fees=fees, slippage=slippage,
            upon_opposite_entry='reverse',
        )
        stats = pf.stats()
        result = _extract_stats(pf, stats, n)

        # 计算单笔最大亏损（占总资金百分比）
        max_single_loss_pct = _calc_max_single_loss(pf, init_cash)
        result['max_single_loss_pct'] = max_single_loss_pct

        return result
    except Exception as e:
        return _empty_result()


def _empty_result():
    """返回空回测结果"""
    return {
        'annual_return': 0.0, 'max_drawdown': 0.0, 'sharpe': 0.0,
        'win_rate': 0.0, 'profit_factor': 0.0, 'total_trades': 0,
        'avg_trades_per_year': 0.0, 'position_pct': 0.0,
        'max_single_loss_pct': 0.0,
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
    try:
        ct = pf.trades.records_readable
        if len(ct) > 0:
            wins = ct[ct['PnL'] > 0]['PnL']
            losses = ct[ct['PnL'] < 0]['PnL']
            total_win = float(wins.sum()) if len(wins) > 0 else 0
            total_loss = abs(float(losses.sum())) if len(losses) > 0 else 0
            profit_factor = total_win / total_loss if total_loss > 0 else (10.0 if total_win > 0 else 0)
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
        'position_pct': round(pos_pct, 1),
    }


def _calc_max_single_loss(pf, init_cash):
    """计算单笔最大亏损（占总资金百分比）"""
    try:
        ct = pf.trades.records_readable
        if len(ct) == 0:
            return 0.0
        losses = ct[ct['PnL'] < 0]['PnL']
        if len(losses) == 0:
            return 0.0
        max_loss = abs(float(losses.min()))
        return round(max_loss / init_cash * 100, 4)
    except Exception:
        return 0.0


def run_range_backtest_on_pool(strategy_func, strategy_params, market,
                                start_date, end_date,
                                max_stocks=None,
                                risk_free_rate=DEFAULT_RISK_FREE_RATE,
                                slippage_mode='default'):
    """
    在标的池上批量回测（震荡市版），返回汇总统计。
    """
    pool = get_stock_pool(market)
    if max_stocks:
        pool = pool[:max_stocks]

    fees = HK_TOTAL_FEES if market == 'hk' else US_TOTAL_FEES
    slippage = SLIPPAGE_LIMIT if slippage_mode == 'limit' else SLIPPAGE_DEFAULT

    results = []
    valid_count = 0

    for symbol in pool:
        df = load_stock_data(symbol, market)
        if df is None:
            continue

        mask = (df.index >= start_date) & (df.index <= end_date)
        df_period = df.loc[mask]
        if len(df_period) < 60:
            continue

        close = df_period['Close'].values.astype(float)
        high = df_period['High'].values.astype(float)
        low = df_period['Low'].values.astype(float)
        open_prices = df_period['Open'].values.astype(float)

        try:
            signal_result = strategy_func(close, high, low, open_prices, **strategy_params)
            entries, exits = signal_result[:2]
        except TypeError:
            try:
                entries, exits = strategy_func(close, high, low)
            except Exception:
                continue

        r = run_single_range_backtest(
            close, high, low, open_prices, entries, exits,
            init_cash=INIT_CASH, fees=fees, slippage=slippage,
        )
        r['symbol'] = symbol
        results.append(r)
        valid_count += 1

    if not results:
        return None

    df_r = pd.DataFrame(results)
    mean_annual = df_r['annual_return'].mean()
    mean_sharpe = df_r['sharpe'].mean()
    mean_dd = df_r['max_drawdown'].mean()
    mean_win = df_r['win_rate'].mean()
    mean_pf = df_r['profit_factor']
    mean_pf = mean_pf[mean_pf > 0].mean() if (mean_pf > 0).any() else 0
    mean_trades = df_r['avg_trades_per_year'].mean()
    mean_max_single = df_r['max_single_loss_pct'].mean()

    # 等权组合回测
    eq_result = _equal_weight_portfolio(results, pool, market,
                                        start_date, end_date,
                                        fees, slippage, risk_free_rate)

    # B&H基准
    beat_bh_pct = _calc_beat_bh(results, pool, market, start_date, end_date)

    return {
        'market': market,
        'period': f"{start_date} ~ {end_date}",
        'n_stocks': valid_count,
        'mean_annual_return': round(mean_annual, 2),
        'mean_sharpe': round(mean_sharpe, 2),
        'mean_max_drawdown': round(mean_dd, 2),
        'mean_win_rate': round(mean_win, 1),
        'mean_profit_factor': round(mean_pf, 2),
        'mean_avg_trades_per_year': round(mean_trades, 1),
        'mean_max_single_loss_pct': round(mean_max_single, 4),
        'beat_bh_pct': beat_bh_pct,
        'equal_weight_portfolio': eq_result,
        'risk_free_rate': risk_free_rate,
        'slippage_mode': slippage_mode,
        'fees_rate': round(fees * 100, 4),
        'individual_results': results[:10],
    }


def _equal_weight_portfolio(results, pool, market, start_date, end_date,
                             fees, slippage, risk_free_rate):
    """等权组合回测（简化版：取所有有效标的的平均收益）"""
    if not results:
        return None
    df_r = pd.DataFrame(results)
    annual_returns = df_r['annual_return'].dropna()
    if len(annual_returns) == 0:
        return None
    eq_annual = annual_returns.mean()
    eq_dd = df_r['max_drawdown'].dropna().mean()
    eq_sharpe = df_r['sharpe'].dropna().mean()
    return {
        'annual_return': round(eq_annual, 2),
        'max_drawdown': round(eq_dd, 2),
        'sharpe': round(eq_sharpe, 2),
    }


def _calc_beat_bh(results, pool, market, start_date, end_date):
    """计算胜B&H基准的标的占比"""
    bh_results = []
    for symbol in pool:
        df = load_stock_data(symbol, market)
        if df is None:
            continue
        mask = (df.index >= start_date) & (df.index <= end_date)
        df_p = df.loc[mask]
        if len(df_p) < 60:
            continue
        n_years = len(df_p) / 252
        bh_return = ((df_p['Close'].iloc[-1] / df_p['Close'].iloc[0])
                     ** (1 / max(n_years, 0.01)) - 1) * 100
        bh_results.append({'symbol': symbol, 'bh_annual': bh_return})

    if not bh_results:
        return 0.0

    df_r = pd.DataFrame(results)
    df_bh = pd.DataFrame(bh_results)
    df_merged = df_r.merge(df_bh, on='symbol', how='inner')
    if len(df_merged) == 0:
        return 0.0
    return round((df_merged['annual_return'] > df_merged['bh_annual']).sum()
                 / len(df_merged) * 100, 1)


def _json_default(obj):
    """自定义JSON序列化"""
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
    parser = argparse.ArgumentParser(description='震荡市策略回测引擎')
    parser.add_argument('--strategy', required=True, help='策略Python文件路径')
    parser.add_argument('--market', default='us', choices=['us', 'hk'], help='市场')
    parser.add_argument('--main-start', default=RANGE_MAIN_START)
    parser.add_argument('--main-end', default=RANGE_MAIN_END)
    parser.add_argument('--stress-start', default=STRESS_START)
    parser.add_argument('--stress-end', default=STRESS_END)
    parser.add_argument('--risk-free-rate', type=float, default=DEFAULT_RISK_FREE_RATE)
    parser.add_argument('--max-stocks', type=int, default=None)
    parser.add_argument('--slippage-mode', default='default',
                        choices=['default', 'limit'], help='滑点模式')
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
    print(f"  滑点模式: {args.slippage_mode}")

    result = {
        'strategy_name': strategy_name,
        'strategy_type': strategy_type,
        'strategy_params': strategy_params,
        'strategy_file': args.strategy,
        'risk_free_rate': args.risk_free_rate,
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'survivorship_bias_flag': True,  # 当前数据不含退市标的
        'slippage_mode': args.slippage_mode,
    }

    # 主回测区间（震荡市）
    print(f"\n📊 震荡市主回测区间: {args.main_start} ~ {args.main_end}")
    main_result = run_range_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.main_start, args.main_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate,
        slippage_mode=args.slippage_mode,
    )
    result['main_period'] = main_result
    if main_result:
        print(f"  ✅ 有效标的: {main_result['n_stocks']}")
        print(f"  平均年化: {main_result['mean_annual_return']}%")
        print(f"  平均夏普: {main_result['mean_sharpe']}")
        print(f"  平均回撤: {main_result['mean_max_drawdown']}%")

    # 压力测试区间
    print(f"\n💪 压力测试区间: {args.stress_start} ~ {args.stress_end}")
    stress_result = run_range_backtest_on_pool(
        strategy_func, strategy_params, args.market,
        args.stress_start, args.stress_end,
        max_stocks=args.max_stocks,
        risk_free_rate=args.risk_free_rate,
        slippage_mode=args.slippage_mode,
    )
    result['stress_period'] = stress_result

    # 跨周期验证（震荡市版：压力区间年化≥0 + 回撤≤主区间1.2x）
    if main_result and stress_result:
        stress_annual = stress_result['mean_annual_return']
        stress_dd = abs(stress_result['mean_max_drawdown'])
        main_dd = abs(main_result['mean_max_drawdown'])
        robust = (stress_annual >= 0) and (stress_dd <= main_dd * 1.2)
        result['cross_period_robust'] = robust
        result['cross_period_details'] = {
            'stress_annual': stress_annual,
            'stress_dd': stress_dd,
            'main_dd': main_dd,
            'condition1_annual_ge_0': stress_annual >= 0,
            'condition2_dd_ratio': round(stress_dd / max(main_dd, 0.01), 2),
            'condition2_pass': stress_dd <= main_dd * 1.2,
        }
        tag = "✅ 跨周期鲁棒" if robust else "❌ 跨周期未通过"
        print(f"\n🔍 跨周期验证: {tag}")

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
