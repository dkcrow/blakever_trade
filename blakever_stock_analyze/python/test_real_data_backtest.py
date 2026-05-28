#!/usr/bin/env python3
"""
Supertrend + 50% 底仓策略 — 真实历史数据回测
使用 westock-data 获取真实历史K线数据进行回测验证。

策略参数：
- Supertrend period=10, multiplier=1.5
- 底仓 50%，机动仓 50%
- 美股出场：ATR 3.5x trailing stop
- 手续费：0.1%（仅开平仓日）
- 未来函数修正：T+1（信号次日生效）
"""

import sys
import os
import logging
import subprocess
import json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LOG_FORMAT = '%(asctime)s %(levelname)-8s [%(name)s] %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("RealDataBacktest")

# westock-data 脚本路径
WESTOCK_SCRIPT = "/data/workspace/.agent/skills/westock-data/scripts/index.js"
WESTOCK_CWD = "/data/workspace"


def fetch_kline_westock(symbol: str, period: str = 'day', limit: int = 1300) -> pd.DataFrame:
    """使用 westock-data 获取K线数据"""
    cmd = f'node {WESTOCK_SCRIPT} kline {symbol} --period {period} --limit {limit}'
    logger.info(f"正在获取 {symbol} K线数据（limit={limit}）...")
    result = subprocess.run(cmd, shell=True, cwd=WESTOCK_CWD,
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise ValueError(f"westock-data 获取失败: {result.stderr}")

    # 解析 Markdown 表格
    lines = result.stdout.strip().split('\n')
    if len(lines) < 3:
        raise ValueError(f"westock-data 返回数据不足: {result.stdout[:200]}")

    # 跳过表头和分隔行
    header = [c.strip() for c in lines[0].split('|')[1:-1]]
    data_rows = []
    for line in lines[2:]:
        cols = [c.strip() for c in line.split('|')[1:-1]]
        if len(cols) >= 5:
            data_rows.append(cols)

    if not data_rows:
        raise ValueError("未解析到有效K线数据")

    df = pd.DataFrame(data_rows, columns=header[:len(data_rows[0])])

    # 标准化列名（westock 用 'last' 代替 'close'）
    col_map = {'last': 'close', 'date': 'date', 'open': 'open',
               'high': 'high', 'low': 'low', 'volume': 'volume'}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 确保数值类型
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 日期排序（从旧到新）
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # 去除NaN行
    df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])

    logger.info(f"获取到 {len(df)} 行数据，日期范围: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    return df


def calc_supertrend(df: pd.DataFrame, period: int = 10,
                    multiplier: float = 1.5) -> pd.DataFrame:
    """计算 Supertrend 指标"""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(df)

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i - 1])
        tr3 = abs(low[i] - close[i - 1])
        tr[i] = max(tr1, tr2, tr3)

    # ATR Wilder 平滑
    atr = np.zeros(n)
    atr[0] = tr[0]
    alpha = 1 / period
    for i in range(1, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha

    # 中间价
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    st_direction = np.ones(n, dtype=int)
    supertrend = np.zeros(n)
    upper_band_final = np.zeros(n)
    lower_band_final = np.zeros(n)

    upper_band_final[0] = upper_band[0]
    lower_band_final[0] = lower_band[0]
    supertrend[0] = upper_band[0]
    st_direction[0] = 1

    for i in range(1, n):
        ub = upper_band[i]
        if close[i - 1] <= upper_band_final[i - 1]:
            ub = min(ub, upper_band_final[i - 1])
        upper_band_final[i] = ub

        lb = lower_band[i]
        if close[i - 1] >= lower_band_final[i - 1]:
            lb = max(lb, lower_band_final[i - 1])
        lower_band_final[i] = lb

        if supertrend[i - 1] == upper_band_final[i - 1] and close[i] > upper_band_final[i]:
            supertrend[i] = lower_band_final[i]
            st_direction[i] = 1
        elif supertrend[i - 1] == lower_band_final[i - 1] and close[i] < lower_band_final[i]:
            supertrend[i] = upper_band_final[i]
            st_direction[i] = -1
        else:
            supertrend[i] = supertrend[i - 1]
            st_direction[i] = st_direction[i - 1]

    result = df.copy()
    result['supertrend'] = supertrend
    result['st_direction'] = st_direction
    result['atr'] = atr
    return result


def run_supertrend_backtest(df: pd.DataFrame,
                             period: int = 10,
                             multiplier: float = 1.5,
                             base_position_pct: float = 0.50,
                             initial_capital: float = 100000,
                             is_hk: bool = False) -> dict:
    """
    运行 Supertrend + 50% 底仓策略回测。
    """
    df = calc_supertrend(df, period=period, multiplier=multiplier)

    st_direction = df['st_direction']
    close = df['close']
    open_price = df['open']
    high = df['high']
    low = df['low']
    atr_series = df['atr']

    # 交易信号：Supertrend 翻多 → 1，翻空 → 0
    signal = (st_direction == 1).astype(int)
    # T+1 修正：信号次日生效
    signal_shifted = signal.shift(1).fillna(0)

    # 仓位 = 底仓(50%) + 机动仓(50% × 信号)
    position = base_position_pct + (1 - base_position_pct) * signal_shifted

    # 止损出场（向量化）
    if not is_hk:
        # 美股：ATR 3.5x trailing stop
        in_long = st_direction == 1
        long_start = (st_direction == 1) & (st_direction.shift(1) != 1)
        group_id = long_start.cumsum()

        holding_high = high.where(in_long, np.nan).groupby(group_id).transform(
            lambda x: x.cummax()
        ).ffill()

        stop_line_raw = holding_high - 3.5 * atr_series
        stop_line = stop_line_raw.groupby(group_id).transform(
            lambda x: x.cummax()
        ).ffill()

        stop_triggered = (close < stop_line) & (position > base_position_pct + 0.01)
        position = position.where(~stop_triggered, base_position_pct)
    else:
        # 港股：EMA10/20 死叉出场（用 MA20/MA60 近似）
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        dead_cross = ma20 < ma60
        dead_cross_shifted = dead_cross.shift(1).fillna(False)
        position = position.where(~dead_cross_shifted, base_position_pct)

    # 计算策略收益
    returns = close.pct_change()
    base_returns = returns * base_position_pct
    tactical_returns = returns * (1 - base_position_pct) * signal_shifted
    strategy_returns = base_returns + tactical_returns

    # 手续费（仅开平仓日扣，0.1%）
    position_change = position.diff().fillna(0)
    trade_cost = abs(position_change) * 0.001
    strategy_returns = strategy_returns - trade_cost

    # 权益曲线
    equity = (1 + strategy_returns).cumprod() * initial_capital
    equity.iloc[0] = initial_capital

    # 绩效指标计算
    total_days = len(df)
    trading_days_per_year = 252
    years = total_days / trading_days_per_year
    final_equity = equity.iloc[-1]
    annual_return = (final_equity / initial_capital) ** (1 / years) - 1

    # 最大回撤
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak
    max_drawdown = abs(drawdown.min())

    # 夏普比率
    daily_returns = equity.pct_change().dropna()
    if len(daily_returns) < 20 or daily_returns.std() == 0:
        sharpe = 0.0
    else:
        sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(trading_days_per_year)

    # 交易统计
    significant_changes = position_change[abs(position_change) > 0.01]

    # 胜率和盈亏比
    trade_pnl_list = []
    entry_eq = None
    eq_arr = equity.values
    pos_change_arr = position_change.values

    for i in range(len(df)):
        if pos_change_arr[i] > 0.01:
            entry_eq = eq_arr[i]
        elif pos_change_arr[i] < -0.01 and entry_eq is not None:
            pnl = eq_arr[i] - entry_eq
            trade_pnl_list.append(pnl)
            entry_eq = None

    total_trades = max(1, len(trade_pnl_list))
    win_rate = sum(1 for p in trade_pnl_list if p > 0) / len(trade_pnl_list) if trade_pnl_list else 0

    if trade_pnl_list:
        avg_win = np.mean([p for p in trade_pnl_list if p > 0]) if any(p > 0 for p in trade_pnl_list) else 0
        avg_loss = abs(np.mean([p for p in trade_pnl_list if p < 0])) if any(p < 0 for p in trade_pnl_list) else 0.0001
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    else:
        profit_loss_ratio = 0

    # 满仓时间占比
    full_position_days = (position > base_position_pct + 0.01).sum()
    full_position_pct_of_time = full_position_days / total_days * 100

    # B&H 基准
    bh_equity = (1 + returns).cumprod() * initial_capital
    bh_equity.iloc[0] = initial_capital
    bh_annual = (bh_equity.iloc[-1] / initial_capital) ** (1 / years) - 1
    bh_max_dd = abs(((bh_equity - bh_equity.expanding().max()) / bh_equity.expanding().max()).min())
    bh_sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0

    return {
        'annual_return': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_drawdown * 100, 1),
        'win_rate': round(win_rate * 100, 1),
        'profit_loss_ratio': round(profit_loss_ratio, 2),
        'total_trades': int(total_trades),
        'final_equity': round(final_equity, 2),
        'initial_capital': initial_capital,
        'full_position_pct': round(full_position_pct_of_time, 1),
        'is_hk': is_hk,
        'bh_annual_return': round(bh_annual * 100, 2),
        'bh_max_drawdown': round(bh_max_dd * 100, 1),
        'bh_sharpe': round(bh_sharpe, 2),
        'data_days': total_days,
        'years': round(years, 2),
    }


def main():
    print("=" * 70)
    print("🚀 Supertrend + 50% 底仓策略 — 真实数据回测")
    print("=" * 70)
    print(f"策略参数: Supertrend(10, 1.5x) + 50%底仓")
    print(f"手续费: 0.1%（仅开平仓日）")
    print(f"未来函数: T+1修正（信号次日生效）")
    print(f"美股出场: ATR 3.5x trailing stop")
    print(f"港股出场: EMA20/60 死叉")
    print("=" * 70)

    results = []

    # ── 美股测试 ──
    us_symbols = {
        'usSPY': '标普500 ETF',
        'usAAPL': '苹果',
        'usQQQ': '纳指100 ETF',
        'usNVDA': '英伟达',
        'usTSLA': '特斯拉',
        'usMSFT': '微软',
    }

    print("\n📊 美股真实数据回测（Supertrend 1.5x ATR + 50% 底仓）：")
    print("-" * 80)
    print(f"{'标的':<12} {'年化':>8} {'夏普':>6} {'回撤':>8} {'胜率':>6} "
          f"{'盈亏比':>6} {'交易':>4} {'满仓%':>6} {'B&H年化':>8} {'B&H回撤':>8}")
    print("-" * 80)

    for symbol, name in us_symbols.items():
        try:
            df = fetch_kline_westock(symbol, period='day', limit=1300)
            result = run_supertrend_backtest(df, period=10, multiplier=1.5,
                                              base_position_pct=0.50,
                                              initial_capital=100000,
                                              is_hk=False)
            result['symbol'] = symbol
            result['name'] = name
            results.append(result)

            print(f"  {name:<10} {result['annual_return']:>7.1f}% {result['sharpe']:>6.2f} "
                  f"{result['max_drawdown']:>7.1f}% {result['win_rate']:>5.1f}% "
                  f"{result['profit_loss_ratio']:>6.2f} {result['total_trades']:>4} "
                  f"{result['full_position_pct']:>5.1f}% "
                  f"{result['bh_annual_return']:>7.1f}% {result['bh_max_drawdown']:>7.1f}%")
        except Exception as e:
            print(f"  {name:<10} ❌ 失败 - {e}")

    # ── 港股测试 ──
    hk_symbols = {
        'hk00700': '腾讯控股',
        'hk09988': '阿里巴巴',
        'hk00005': '汇丰控股',
        'hk01810': '小米集团',
    }

    print("\n📊 港股真实数据回测（Supertrend 1.5x ATR + 50% 底仓）：")
    print("-" * 80)
    print(f"{'标的':<12} {'年化':>8} {'夏普':>6} {'回撤':>8} {'胜率':>6} "
          f"{'盈亏比':>6} {'交易':>4} {'满仓%':>6} {'B&H年化':>8} {'B&H回撤':>8}")
    print("-" * 80)

    for symbol, name in hk_symbols.items():
        try:
            df = fetch_kline_westock(symbol, period='day', limit=1300)
            result = run_supertrend_backtest(df, period=10, multiplier=1.5,
                                              base_position_pct=0.50,
                                              initial_capital=100000,
                                              is_hk=True)
            result['symbol'] = symbol
            result['name'] = name
            results.append(result)

            print(f"  {name:<10} {result['annual_return']:>7.1f}% {result['sharpe']:>6.2f} "
                  f"{result['max_drawdown']:>7.1f}% {result['win_rate']:>5.1f}% "
                  f"{result['profit_loss_ratio']:>6.2f} {result['total_trades']:>4} "
                  f"{result['full_position_pct']:>5.1f}% "
                  f"{result['bh_annual_return']:>7.1f}% {result['bh_max_drawdown']:>7.1f}%")
        except Exception as e:
            print(f"  {name:<10} ❌ 失败 - {e}")

    # ── 参数对比 ──
    print("\n📊 参数对比（SPY，不同 Supertrend 倍数）：")
    print("-" * 80)
    try:
        for mult in [1.0, 1.5, 2.0, 2.5, 3.0]:
            df = fetch_kline_westock('usSPY', period='day', limit=1300)
            result = run_supertrend_backtest(df, period=10, multiplier=mult,
                                              base_position_pct=0.50,
                                              initial_capital=100000,
                                              is_hk=False)
            print(f"  ST({mult}x): 年化={result['annual_return']:.1f}%, "
                  f"夏普={result['sharpe']:.2f}, "
                  f"回撤={result['max_drawdown']:.1f}%, "
                  f"交易={result['total_trades']}, "
                  f"满仓={result['full_position_pct']:.1f}%")
    except Exception as e:
        print(f"  ❌ 参数对比失败 - {e}")

    # ── 底仓比例对比 ──
    print("\n📊 底仓比例对比（SPY，Supertrend 1.5x）：")
    print("-" * 80)
    try:
        for base_pct in [0.30, 0.50, 0.70, 1.00]:
            df = fetch_kline_westock('usSPY', period='day', limit=1300)
            result = run_supertrend_backtest(df, period=10, multiplier=1.5,
                                              base_position_pct=base_pct,
                                              initial_capital=100000,
                                              is_hk=False)
            print(f"  底仓{base_pct*100:.0f}%: 年化={result['annual_return']:.1f}%, "
                  f"夏普={result['sharpe']:.2f}, "
                  f"回撤={result['max_drawdown']:.1f}%, "
                  f"盈亏比={result['profit_loss_ratio']:.2f}, "
                  f"交易={result['total_trades']}")
    except Exception as e:
        print(f"  ❌ 底仓对比失败 - {e}")

    # ── 汇总 ──
    print("\n" + "=" * 70)
    print("📋 真实数据回测汇总")
    print("=" * 70)

    us_results = [r for r in results if not r['is_hk']]
    hk_results = [r for r in results if r['is_hk']]

    if us_results:
        avg_annual = np.mean([r['annual_return'] for r in us_results])
        avg_sharpe = np.mean([r['sharpe'] for r in us_results])
        avg_drawdown = np.mean([r['max_drawdown'] for r in us_results])
        avg_winrate = np.mean([r['win_rate'] for r in us_results])
        avg_plr = np.mean([r['profit_loss_ratio'] for r in us_results])
        avg_trades = np.mean([r['total_trades'] for r in us_results])
        avg_bh = np.mean([r['bh_annual_return'] for r in us_results])
        print(f"  🇺🇸 美股平均: 年化={avg_annual:.1f}%, 夏普={avg_sharpe:.2f}, "
              f"回撤={avg_drawdown:.1f}%, 胜率={avg_winrate:.1f}%, "
              f"盈亏比={avg_plr:.2f}, 交易次数={avg_trades:.0f}")
        print(f"           B&H平均年化={avg_bh:.1f}%")

    if hk_results:
        avg_annual = np.mean([r['annual_return'] for r in hk_results])
        avg_sharpe = np.mean([r['sharpe'] for r in hk_results])
        avg_drawdown = np.mean([r['max_drawdown'] for r in hk_results])
        avg_winrate = np.mean([r['win_rate'] for r in hk_results])
        avg_plr = np.mean([r['profit_loss_ratio'] for r in hk_results])
        avg_trades = np.mean([r['total_trades'] for r in hk_results])
        avg_bh = np.mean([r['bh_annual_return'] for r in hk_results])
        print(f"  🇭🇰 港股平均: 年化={avg_annual:.1f}%, 夏普={avg_sharpe:.2f}, "
              f"回撤={avg_drawdown:.1f}%, 胜率={avg_winrate:.1f}%, "
              f"盈亏比={avg_plr:.2f}, 交易次数={avg_trades:.0f}")
        print(f"           B&H平均年化={avg_bh:.1f}%")

    print("\n" + "=" * 70)
    print("📊 与记忆数据对比（修正后真实收益）")
    print("=" * 70)
    print("  记忆中（修正后，多只股票等权组合）：")
    print("    Supertrend(1.5x)+50%底仓: 年化11.64%, 夏普1.07")
    print("    美股ATR3.5x止损纯策略: 年化4.09%, 夏普0.56")
    print("    美股底仓50%组合: 年化8.45%, 夏普0.66")
    print("    港股宽松版: 年化-0.82%, 夏普-0.03")
    print("  当前回测（单只股票，5年真实数据）：")
    if us_results:
        print(f"    美股平均: 年化={np.mean([r['annual_return'] for r in us_results]):.1f}%, "
              f"夏普={np.mean([r['sharpe'] for r in us_results]):.2f}")
    if hk_results:
        print(f"    港股平均: 年化={np.mean([r['annual_return'] for r in hk_results]):.1f}%, "
              f"夏普={np.mean([r['sharpe'] for r in hk_results]):.2f}")
    print("  ⚠️ 单只股票 vs 等权组合有差异，但方向和量级应一致")

    print("\n✅ 真实数据回测验证完成！")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n❌ 回测失败: {e}")
        traceback.print_exc()
        sys.exit(1)
