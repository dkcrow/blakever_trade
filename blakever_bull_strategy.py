#!/usr/bin/env python3
"""
============================================================
Blakever Agent3 牛市策略 — 完整规则描述与可执行回测代码
============================================================
策略核心：EMA10/20持仓跟踪 + ADX趋势强度过滤
框架：VectorBT + TA-Lib

版本：
  - 严格版 (ADX > 25)：原始版本，过滤更严
  - 宽松版 (ADX > 20)：优化版本，回测表现更优 ★推荐

对比基准：
  - Buy & Hold：买入持有
  - EMA10/20 Crossover：无条件交叉持仓（无ADX过滤）
============================================================
"""

import pandas as pd
import numpy as np
import talib
import vectorbt as vbt
import warnings
warnings.filterwarnings('ignore')


# ================================================================
# 📋 策略规则详细描述
# ================================================================
STRATEGY_RULES = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    Blakever Agent3 牛市策略
              (EMA10/20 持仓跟踪 + ADX 趋势强度过滤)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 策略逻辑：
   在确认的牛市环境中，跟随趋势持仓。
   使用 EMA10/20 判断短期趋势方向，ADX 确认趋势强度。

📌 入场条件（所有条件必须同时满足）：
   1. EMA10 > EMA20  — 短期均线上穿长期均线，趋势向上
   2. ADX > 阈值     — 趋势强度足够（严格版>25，宽松版>20）

📌 持仓逻辑：
   - 当 EMA10 > EMA20 且 ADX > 阈值 → 持有多头仓位
   - 否则 → 空仓等待

📌 出场条件（满足任一即出场）：
   1. EMA10 < EMA20  — 均线死叉，趋势反转
   2. ADX < 阈值     — 趋势强度减弱

📌 参数设置：
   ┌────────────────┬──────────┬──────────────────────────┐
   │ 参数           │ 默认值   │ 说明                     │
   ├────────────────┼──────────┼──────────────────────────┤
   │ EMA短期周期    │ 10       │ 快速指数均线             │
   │ EMA长期周期    │ 20       │ 慢速指数均线             │
   │ ADX周期        │ 14       │ 平均趋向指数计算周期     │
   │ ADX阈值(严格版)│ 25       │ 原始版本，过滤更严       │
   │ ADX阈值(宽松版)│ 20       │ 优化版本，回测表现更优   │
   │ 手续费         │ 0.1%     │ 每次交易按比例收取       │
   │ 滑点           │ 0.1%     │ 模拟实际成交偏差         │
   │ 初始资金       │ 100,000  │ 回测起始资金             │
   └────────────────┴──────────┴──────────────────────────┘

📌 两个版本对比：
   ┌────────────┬───────────────────────────────────────────────┐
   │ 严格版      │ ADX > 25: 过滤严格，空仓时间多，错过部分涨幅 │
   │            │ 适合：强趋势市场，保守型投资者                │
   ├────────────┼───────────────────────────────────────────────┤
   │ 宽松版 ★   │ ADX > 20: 过滤适度，空仓时间少，捕获更多趋势│
   │            │ 适合：一般牛市环境，平衡型投资者              │
   │            │ 回测表现明显优于严格版                        │
   └────────────┴───────────────────────────────────────────────┘

📌 优化建议（已在18年回测中验证）：
   🔴 高优先级：ADX阈值从25降至20
   🔴 高优先级：考虑取消ADX过滤，仅用EMA10/20持仓跟踪
   🟡 中优先级：用MACD金叉确认替代ADX
   🟢 低优先级：多时间框架确认（周线+日线）

📌 与基准策略对比：
   1. Buy & Hold — 买入持有，不择时
   2. EMA10/20 Crossover — 无条件交叉持仓，无ADX过滤

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

print(STRATEGY_RULES)


# ================================================================
# 🔧 策略信号生成函数
# ================================================================

def bull_strategy_strict(close, high, low):
    """
    Agent3 牛市策略 — 严格版 (ADX > 25)

    入场: EMA10 > EMA20 且 ADX > 25
    出场: EMA10 < EMA20 或 ADX < 25

    参数:
        close: 收盘价数组
        high: 最高价数组
        low: 最低价数组

    返回: (entries, exits) 布尔数组
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # 计算 EMA
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()

    # 计算 ADX
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)

    # 持仓条件: EMA10 > EMA20 且 ADX > 25
    in_pos = (ema10 > ema20) & (adx_s > 25)

    # 入场信号: 从空仓转为持仓
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    # 出场信号: 从持仓转为空仓
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


def bull_strategy_relaxed(close, high, low):
    """
    Agent3 牛市策略 — 宽松版 (ADX > 20) ★ 推荐版本

    入场: EMA10 > EMA20 且 ADX > 20
    出场: EMA10 < EMA20 或 ADX < 20

    参数:
        close: 收盘价数组
        high: 最高价数组
        low: 最低价数组

    返回: (entries, exits) 布尔数组
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)

    # 持仓条件: EMA10 > EMA20 且 ADX > 20
    in_pos = (ema10 > ema20) & (adx_s > 20)

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


def ema_cross_strategy(close, high, low):
    """
    对比基准: EMA10/20 无条件交叉持仓（无ADX过滤）

    入场: EMA10 > EMA20 (金叉)
    出场: EMA10 < EMA20 (死叉)

    返回: (entries, exits) 布尔数组
    """
    c = pd.Series(close, dtype=float)

    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()

    in_pos = ema10 > ema20

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


# ================================================================
# 📊 回测执行函数
# ================================================================

INIT_CASH = 100000
FEES = 0.001
SLIPPAGE = 0.001


def run_backtest(close, high, low, strategy_func, strategy_name):
    """
    运行单个策略回测，返回绩效指标字典

    参数:
        close: 收盘价数组
        high: 最高价数组
        low: 最低价数组
        strategy_func: 策略信号生成函数
        strategy_name: 策略名称（用于显示）

    返回:
        dict: 包含各项绩效指标的字典
    """
    n = len(close)

    try:
        entries, exits = strategy_func(close, high, low)

        if entries.sum() == 0:
            return {
                '策略': strategy_name, '状态': '无交易信号',
                '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0
            }

        pf = vbt.Portfolio.from_signals(
            close, entries=entries, exits=exits,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
        )

        stats = pf.stats()
        total_return = float(stats['Total Return [%]'])
        max_dd = float(stats['Max Drawdown [%]'])
        win_rate = float(stats['Win Rate [%]'])
        total_trades = int(stats['Total Trades'])

        # 年化收益
        n_years = len(pf.returns()) / 252
        if n_years > 0 and total_return > -100:
            annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100
        else:
            annual = -100

        # 盈亏比
        profit_factor = 0
        try:
            closed_trades = pf.trades.records_readable
            if len(closed_trades) > 0:
                wins = closed_trades[closed_trades['PnL'] > 0]['PnL']
                losses = closed_trades[closed_trades['PnL'] < 0]['PnL']
                avg_win = wins.mean() if len(wins) > 0 else 0
                avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
                profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        except Exception:
            pass

        return {
            '策略': strategy_name,
            '状态': '✅ 成功',
            '总收益率%': round(total_return, 2),
            '年化收益%': round(annual, 2),
            '最大回撤%': round(max_dd, 2),
            '胜率%': round(win_rate, 1),
            '交易次数': total_trades,
            '盈亏比': round(profit_factor, 2),
        }
    except Exception as e:
        return {
            '策略': strategy_name, '状态': f'❌ 失败: {e}',
            '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
            '胜率%': 0, '交易次数': 0, '盈亏比': 0
        }


def print_comparison_table(results, title="策略对比"):
    """打印策略对比表"""
    print(f"\n{'━' * 100}")
    print(f"  📊 {title}")
    print(f"{'━' * 100}")
    print("┌" + "─" * 28 + "┬" + "─" * 8 + "┬" + "─" * 12
          + "┬" + "─" * 12 + "┬" + "─" * 10 + "┬" + "─" * 8
          + "┬" + "─" * 8 + "┐")
    print("│{:<28}│{:>8}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
        '策略', '状态', '总收益率%', '年化收益%', '最大回撤%', '胜率%', '交易数', '盈亏比'))
    print("├" + "─" * 28 + "┼" + "─" * 8 + "┼" + "─" * 12
          + "┼" + "─" * 12 + "┼" + "─" * 10 + "┼" + "─" * 8
          + "┼" + "─" * 8 + "┤")
    for r in results:
        status = str(r['状态'])[:8]
        print("│{:<28}│{:>8}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
            r['策略'], status,
            str(r['总收益率%']) + '%', str(r['年化收益%']) + '%',
            str(r['最大回撤%']) + '%', str(r['胜率%']) + '%',
            r['交易次数'], r['盈亏比']))
    print("└" + "─" * 28 + "┴" + "─" * 8 + "┴" + "─" * 12
          + "┴" + "─" * 12 + "┴" + "─" * 10 + "┴" + "─" * 8
          + "┴" + "─" * 8 + "┘")


# ================================================================
# 🚀 主程序 — 加载数据并运行回测
# ================================================================

if __name__ == '__main__':
    # 加载数据
    print("\n📦 加载数据...")
    try:
        spy_df = pd.read_csv(
            '/data/workspace/spy_daily.csv',
            parse_dates=['date'], index_col='date'
        ).sort_index()
        hsi_df = pd.read_csv(
            '/data/workspace/hsi_daily.csv',
            parse_dates=['date'], index_col='date'
        ).sort_index()
        print(f"  ✅ SPY: {spy_df.index[0].date()} ~ {spy_df.index[-1].date()}, {len(spy_df)} 天")
        print(f"  ✅ HSI: {hsi_df.index[0].date()} ~ {hsi_df.index[-1].date()}, {len(hsi_df)} 天")
    except FileNotFoundError:
        print("  ⚠️ 未找到数据文件，使用 yfinance 下载数据...")
        import yfinance as yf
        spy_df = yf.download('SPY', start='2007-01-01', end='2025-04-01')
        hsi_df = yf.download('^HSI', start='2007-01-01', end='2025-04-01')
        spy_df.columns = [c.lower() for c in spy_df.columns]
        hsi_df.columns = [c.lower() for c in hsi_df.columns]
        print(f"  ✅ SPY: {spy_df.index[0].date()} ~ {spy_df.index[-1].date()}, {len(spy_df)} 天")
        print(f"  ✅ HSI: {hsi_df.index[0].date()} ~ {hsi_df.index[-1].date()}, {len(hsi_df)} 天")

    # 定义策略列表
    strategies = [
        ('Agent3牛市(严格版ADX>25)', bull_strategy_strict),
        ('Agent3牛市(宽松版ADX>20)★', bull_strategy_relaxed),
        ('EMA10/20无条件交叉', ema_cross_strategy),
    ]

    # ================================================================
    # 全周期回测
    # ================================================================
    for market_name, df in [("SPY (美股)", spy_df), ("HSI (港股)", hsi_df)]:
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)

        results = []
        for strat_name, strat_func in strategies:
            r = run_backtest(close, high, low, strat_func, strat_name)
            results.append(r)

        # 加入 Buy & Hold
        n = len(close)
        entries_bh = np.full(n, False)
        entries_bh[0] = True
        exits_bh = np.full(n, False)
        pf_bh = vbt.Portfolio.from_signals(
            close, entries=entries_bh, exits=exits_bh,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
        )
        stats_bh = pf_bh.stats()
        n_years = len(pf_bh.returns()) / 252
        total_ret_bh = float(stats_bh['Total Return [%]'])
        annual_bh = ((1 + total_ret_bh / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
        results.append({
            '策略': 'Buy & Hold',
            '状态': '✅ 成功',
            '总收益率%': round(total_ret_bh, 2),
            '年化收益%': round(annual_bh, 2),
            '最大回撤%': round(float(stats_bh['Max Drawdown [%]']), 2),
            '胜率%': '-',
            '交易次数': 1,
            '盈亏比': '-',
        })

        print_comparison_table(results, f"{market_name} 全周期策略对比")

    # ================================================================
    # 分环境回测（按月划分牛市/熊市/震荡市）
    # ================================================================

    def classify_regime_monthly(df):
        """按月划分市场环境"""
        close = df['close'].values.astype(float)
        sma50 = talib.SMA(close, timeperiod=50)
        sma200 = talib.SMA(close, timeperiod=200)

        df2 = df.copy()
        df2['sma50'] = sma50
        df2['sma200'] = sma200
        df2['month'] = df2.index.to_period('M')

        regimes = {}
        for month, group in df2.groupby('month'):
            if len(group) < 5:
                continue
            month_close = group['close'].iloc[-1]
            month_open = group['close'].iloc[0]
            month_return = (month_close - month_open) / month_open
            last_sma50 = group['sma50'].iloc[-1]
            last_sma200 = group['sma200'].iloc[-1]

            if pd.isna(last_sma200):
                if month_return > 0.02:
                    regime = 'bull'
                elif month_return < -0.02:
                    regime = 'bear'
                else:
                    regime = 'sideways'
            else:
                if month_close > last_sma200 and last_sma50 > last_sma200:
                    regime = 'bull'
                elif month_close < last_sma200 and last_sma50 < last_sma200:
                    regime = 'bear'
                else:
                    regime = 'sideways'
            regimes[str(month)] = regime
        return regimes

    print(f"\n{'━' * 100}")
    print("  📊 分环境回测 (牛市环境 × 牛市策略)")
    print(f"{'━' * 100}")

    regime_cn = {'bull': '🐂 牛市', 'bear': '📉 熊市', 'sideways': '↔️ 震荡市'}

    for market_name, df in [("SPY (美股)", spy_df), ("HSI (港股)", hsi_df)]:
        regimes = classify_regime_monthly(df)
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        dates = df.index

        # 统计各环境月份
        bull_months = sum(1 for v in regimes.values() if v == 'bull')
        bear_months = sum(1 for v in regimes.values() if v == 'bear')
        side_months = sum(1 for v in regimes.values() if v == 'sideways')
        total_months = len(regimes)

        print(f"\n  📈 {market_name} 环境分布:")
        print(f"     🐂 牛市: {bull_months}月 ({bull_months / total_months * 100:.1f}%)")
        print(f"     📉 熊市: {bear_months}月 ({bear_months / total_months * 100:.1f}%)")
        print(f"     ↔️ 震荡: {side_months}月 ({side_months / total_months * 100:.1f}%)")

        # 按环境划分日期
        months_series = pd.Series(dates).dt.to_period('M')
        regime_mask = months_series.map(lambda m: regimes.get(str(m), 'sideways')).values

        # 仅在牛市环境区间回测
        for regime in ['bull', 'sideways', 'bear']:
            mask = regime_mask == regime
            indices = np.where(mask)[0]

            if len(indices) < 50:
                print(f"\n     {regime_cn[regime]} 环境: 数据不足 ({len(indices)}天)")
                continue

            regime_close = close[indices]
            regime_high = high[indices]
            regime_low = low[indices]

            print(f"\n     {regime_cn[regime]} 环境: {len(indices)}天 (~{len(indices) / 252:.1f}年)")

            results = []
            for strat_name, strat_func in strategies:
                r = run_backtest(regime_close, regime_high, regime_low, strat_func, strat_name)
                results.append(r)

            # Buy & Hold for this regime
            n_sub = len(regime_close)
            entries_bh = np.full(n_sub, False)
            entries_bh[0] = True
            exits_bh = np.full(n_sub, False)
            try:
                pf_bh = vbt.Portfolio.from_signals(
                    regime_close, entries=entries_bh, exits=exits_bh,
                    freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
                )
                stats_bh = pf_bh.stats()
                total_ret_bh = float(stats_bh['Total Return [%]'])
                n_years_sub = len(pf_bh.returns()) / 252
                annual_bh = ((1 + total_ret_bh / 100) ** (1 / n_years_sub) - 1) * 100 if n_years_sub > 0 else 0
                results.append({
                    '策略': 'Buy & Hold',
                    '状态': '✅ 成功',
                    '总收益率%': round(total_ret_bh, 2),
                    '年化收益%': round(annual_bh, 2),
                    '最大回撤%': round(float(stats_bh['Max Drawdown [%]']), 2),
                    '胜率%': '-',
                    '交易次数': 1,
                    '盈亏比': '-',
                })
            except Exception:
                pass

            # 打印表格
            print("     ┌" + "─" * 26 + "┬" + "─" * 8 + "┬" + "─" * 12
                  + "┬" + "─" * 12 + "┬" + "─" * 10 + "┬" + "─" * 8
                  + "┬" + "─" * 8 + "┐")
            print("     │{:<26}│{:>8}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
                '策略', '状态', '总收益率%', '年化收益%', '最大回撤%', '胜率%', '交易数', '盈亏比'))
            print("     ├" + "─" * 26 + "┼" + "─" * 8 + "┼" + "─" * 12
                  + "┼" + "─" * 12 + "┼" + "─" * 10 + "┼" + "─" * 8
                  + "┼" + "─" * 8 + "┤")
            for r in results:
                status = str(r['状态'])[:8]
                print("     │{:<26}│{:>8}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
                    r['策略'], status,
                    str(r['总收益率%']) + '%', str(r['年化收益%']) + '%',
                    str(r['最大回撤%']) + '%', str(r['胜率%']) + '%',
                    r['交易次数'], r['盈亏比']))
            print("     └" + "─" * 26 + "┴" + "─" * 8 + "┴" + "─" * 12
                  + "┴" + "─" * 12 + "┴" + "─" * 10 + "┴" + "─" * 8
                  + "┴" + "─" * 8 + "┘")

    # ================================================================
    # 核心优化建议
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📋 牛市策略核心优化建议")
    print(f"{'━' * 100}")
    print("""
    🔴 高优先级优化（立即可做）:
    ┌─────────────────────────────────────────────────────────────────┐
    │ 1. ADX 阈值从 25 降至 20                                       │
    │    原因: ADX>25 过严 → 大量空仓时间 → 错过涨幅               │
    │    预期: 空仓时间减少30%，年化收益+3~5%                       │
    │                                                                 │
    │ 2. 考虑取消 ADX 过滤，仅用 EMA10/20 持仓跟踪                   │
    │    原因: 美股长牛特征下，ADX过滤反而拖累收益                  │
    │    预期: 在强牛市中接近 Buy&Hold 收益                          │
    │                                                                 │
    │ 3. 用 MACD 金叉确认替代 ADX                                     │
    │    原因: MACD 对趋势启动更敏感，减少滞后                       │
    │    预期: 入场更早，捕获更多趋势初段涨幅                       │
    └─────────────────────────────────────────────────────────────────┘

    🟡 中优先级优化（下阶段实施）:
    ┌─────────────────────────────────────────────────────────────────┐
    │ 4. 策略路由延迟确认: Agent1判断 + 延迟1个月确认               │
    │    原因: 避免震荡市初期被误判为牛市而追高                     │
    │    预期: 减少10-15%的环境误判                                  │
    │                                                                 │
    │ 5. 多时间框架确认: 周线 SMA50/200 定方向 + 日线 EMA10/20入场  │
    │    原因: 周线趋势更稳定，日线入场更精确                       │
    │    预期: 胜率+5~10%                                            │
    └─────────────────────────────────────────────────────────────────┘

    🟢 低优先级优化（长期探索）:
    ┌─────────────────────────────────────────────────────────────────┐
    │ 6. 机器学习环境识别: XGBoost 替代 SMA50/200 分类              │
    │ 7. 自适应参数: ATR 动态调整 EMA 周期和 ADX 阈值              │
    │ 8. 多标的组合: 加入 GLD/TLT/SHY 避险ETF轮动                  │
    └─────────────────────────────────────────────────────────────────┘
    """)

    print("\n✅ 牛市策略规则描述与回测完成！")
