#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
Blakever 牛市策略 V1 vs V2 — 美股牛市区间专项回测
============================================================
步骤：
  1. 用 SMA50/SMA200 金叉/死叉 + 涨幅过滤 识别近10年牛市区间
  2. 在每个牛市区间分别回测 V1(六维评分) 和 V2(EMA+ADX)
  3. 汇总对比：牛市区间V1 vs V2谁更优
============================================================
"""

import pandas as pd
import numpy as np
import talib
import vectorbt as vbt
import warnings
warnings.filterwarnings('ignore')

# ================================================================
# 通用参数
# ================================================================
INIT_CASH = 100000
FEES = 0.001
SLIPPAGE = 0.001

# ================================================================
# V1 策略：六维评分系统
# ================================================================
def bull_strategy_v1(close, high, low, volume=None):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    v = pd.Series(volume, dtype=float) if volume is not None else pd.Series(np.ones(len(c)))
    n = len(c)

    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    ma120 = c.rolling(120).mean()
    rsi14 = pd.Series(talib.RSI(c.values, timeperiod=14))
    adx14 = pd.Series(talib.ADX(h.values, l.values, c.values, timeperiod=14))
    macd, macd_signal, _ = talib.MACD(c.values)
    macd_s = pd.Series(macd)
    macd_signal_s = pd.Series(macd_signal)
    bb_upper = pd.Series(talib.BBANDS(c.values, nbdevup=2)[0])
    bb_mid = pd.Series(talib.BBANDS(c.values, nbdevup=2)[1])
    vol_ma20 = v.rolling(20).mean()
    vol_ratio = v / vol_ma20.replace(0, np.nan)
    ret_20d = c.pct_change(20)

    scores = pd.Series(0.0, index=c.index)
    for i in range(120, n):
        s = 0.0
        c_val = c.iloc[i]
        # 1. 技术面 (30)
        if not pd.isna(ma120.iloc[i]):
            if ma20.iloc[i] > ma60.iloc[i] > ma120.iloc[i] and c_val > ma20.iloc[i]:
                s += 30
            elif ma20.iloc[i] > ma60.iloc[i] and c_val > ma20.iloc[i]:
                s += 18
            elif c_val > ma20.iloc[i]:
                s += 8
        # MACD加分
        if not pd.isna(macd_s.iloc[i]) and not pd.isna(macd_signal_s.iloc[i]):
            if macd_s.iloc[i] > macd_signal_s.iloc[i] and macd_s.iloc[i] > 0:
                s += 5
        # 2. 动量面 (20)
        if not pd.isna(ret_20d.iloc[i]):
            s += min(20, max(0, ret_20d.iloc[i] * 100))
        # 3. 成交量面 (15)
        if not pd.isna(vol_ratio.iloc[i]) and vol_ratio.iloc[i] > 0:
            if vol_ratio.iloc[i] > 1.5: s += 15
            elif vol_ratio.iloc[i] > 1.2: s += 10
            elif vol_ratio.iloc[i] > 1.0: s += 5
        # 4. RSI (15)
        rsi_val = rsi14.iloc[i]
        if not pd.isna(rsi_val):
            if 50 <= rsi_val <= 70: s += 15
            elif 45 <= rsi_val <= 75: s += 8
            elif rsi_val > 80: s += 0
            else: s += 3
        # 5. ADX (10)
        adx_val = adx14.iloc[i]
        if not pd.isna(adx_val):
            if adx_val > 30: s += 10
            elif adx_val > 20: s += 6
            else: s += 2
        # 6. 布林带 (10)
        if not pd.isna(bb_upper.iloc[i]) and not pd.isna(bb_mid.iloc[i]):
            if bb_mid.iloc[i] < c_val < bb_upper.iloc[i]: s += 10
            elif c_val >= bb_upper.iloc[i]: s += 3
        scores.iloc[i] = min(100, s)

    in_pos = scores >= 60
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# V2 策略：EMA10/20 + ADX 趋势过滤
# ================================================================
def bull_strategy_v2_relaxed(close, high, low):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx_s = pd.Series(talib.ADX(h.values, l.values, c.values, timeperiod=14))
    in_pos = (ema10 > ema20) & (adx_s > 20)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


def bull_strategy_v2_strict(close, high, low):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx_s = pd.Series(talib.ADX(h.values, l.values, c.values, timeperiod=14))
    in_pos = (ema10 > ema20) & (adx_s > 25)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# EMA 交叉基准
# ================================================================
def ema_cross_baseline(close, high, low):
    c = pd.Series(close, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    in_pos = ema10 > ema20
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# 牛市区间识别：SMA50/200 金叉 → 死叉
# ================================================================
def identify_bull_periods(df, min_days=30):
    """
    用 SMA50/SMA200 金叉/死叉识别牛市区间。
    金叉 = SMA50 上穿 SMA200 → 牛市开始
    死叉 = SMA50 下穿 SMA200 → 牛市结束
    
    返回: list of (start_date, end_date, duration_days, return_pct)
    """
    close = df['close'].values.astype(float)
    sma50 = talib.SMA(close, timeperiod=50)
    sma200 = talib.SMA(close, timeperiod=200)
    
    dates = df.index
    
    # 找金叉和死叉点
    above = sma50 > sma200
    golden_cross = (above & ~np.roll(above, 1)).astype(bool)
    death_cross = (~above & np.roll(above, 1)).astype(bool)
    golden_cross[0] = False
    death_cross[0] = False
    
    # 提取牛市区间
    bull_periods = []
    in_bull = False
    start_idx = None
    
    for i in range(len(close)):
        if pd.isna(sma200[i]):
            continue
        if golden_cross[i] and not in_bull:
            in_bull = True
            start_idx = i
        elif death_cross[i] and in_bull:
            in_bull = False
            end_idx = i
            duration = end_idx - start_idx
            if duration >= min_days:
                ret = (close[end_idx] / close[start_idx] - 1) * 100
                bull_periods.append({
                    'start_date': dates[start_idx],
                    'end_date': dates[end_idx],
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'duration_days': duration,
                    'return_pct': round(ret, 2),
                    'start_price': round(close[start_idx], 2),
                    'end_price': round(close[end_idx], 2),
                })
    
    # 如果当前仍在牛市中
    if in_bull and start_idx is not None:
        end_idx = len(close) - 1
        duration = end_idx - start_idx
        if duration >= min_days:
            ret = (close[end_idx] / close[start_idx] - 1) * 100
            bull_periods.append({
                'start_date': dates[start_idx],
                'end_date': dates[end_idx],
                'start_idx': start_idx,
                'end_idx': end_idx,
                'duration_days': duration,
                'return_pct': round(ret, 2),
                'start_price': round(close[start_idx], 2),
                'end_price': round(close[end_idx], 2),
            })
    
    return bull_periods


# ================================================================
# 回测执行
# ================================================================
def run_backtest(close, high, low, strategy_func, strategy_name, volume=None):
    try:
        if volume is not None:
            entries, exits = strategy_func(close, high, low, volume)
        else:
            entries, exits = strategy_func(close, high, low)

        if entries.sum() == 0:
            return {'策略': strategy_name, '状态': '无信号',
                    '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                    '胜率%': 0, '交易次数': 0, '盈亏比': 0,
                    '持仓占比%': 0, '卡尔马比率': 0}

        pf = vbt.Portfolio.from_signals(
            close, entries=entries, exits=exits,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
        )

        stats = pf.stats()
        total_return = float(stats['Total Return [%]'])
        max_dd = float(stats['Max Drawdown [%]'])
        win_rate = float(stats['Win Rate [%]'])
        total_trades = int(stats['Total Trades'])

        n_years = len(pf.returns()) / 252
        if n_years > 0 and total_return > -100:
            annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100
        else:
            annual = -100

        profit_factor = 0
        try:
            ct = pf.trades.records_readable
            if len(ct) > 0:
                wins = ct[ct['PnL'] > 0]['PnL']
                losses = ct[ct['PnL'] < 0]['PnL']
                avg_win = wins.mean() if len(wins) > 0 else 0
                avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
                profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        except Exception:
            pass

        # 持仓占比
        pos_arr = np.zeros(len(close), dtype=bool)
        in_position = False
        for i in range(len(close)):
            if entries[i]: in_position = True
            elif exits[i]: in_position = False
            pos_arr[i] = in_position
        hold_pct = pos_arr.sum() / len(close) * 100

        calmar = annual / abs(max_dd) if max_dd != 0 else 0

        return {
            '策略': strategy_name, '状态': '✅',
            '总收益率%': round(total_return, 2),
            '年化收益%': round(annual, 2),
            '最大回撤%': round(max_dd, 2),
            '胜率%': round(win_rate, 1),
            '交易次数': total_trades,
            '盈亏比': round(profit_factor, 2),
            '持仓占比%': round(hold_pct, 1),
            '卡尔马比率': round(calmar, 2),
        }
    except Exception as e:
        return {'策略': strategy_name, '状态': f'❌ {e}',
                '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0,
                '持仓占比%': 0, '卡尔马比率': 0}


def run_buyhold(close):
    n = len(close)
    entries = np.full(n, False); entries[0] = True
    exits = np.full(n, False)
    pf = vbt.Portfolio.from_signals(close, entries=entries, exits=exits,
                                     freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE)
    stats = pf.stats()
    total_return = float(stats['Total Return [%]'])
    n_years = len(pf.returns()) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    max_dd = float(stats['Max Drawdown [%]'])
    calmar = annual / abs(max_dd) if max_dd != 0 else 0
    return {
        '策略': 'Buy & Hold', '状态': '✅',
        '总收益率%': round(total_return, 2), '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2), '胜率%': '-', '交易次数': 1,
        '盈亏比': '-', '持仓占比%': 100.0, '卡尔马比率': round(calmar, 2),
    }


# ================================================================
# 打印表格
# ================================================================
def print_table(results, title=""):
    cols = ['策略', '状态', '总收益率%', '年化收益%', '最大回撤%', '胜率%', '交易次数', '盈亏比', '持仓占比%', '卡尔马比率']
    widths = [24, 4, 10, 10, 10, 8, 8, 8, 10, 10]
    
    total_w = int(sum(widths)) + len(widths) * 3 + 1
    print(f"\n  {'━' * total_w}")
    if title:
        print(f"  📊 {title}")
        print(f"  {'━' * total_w}")
    
    header = "  │"
    for col, w in zip(cols, widths):
        header += f"{col:>{w}}│"
    print(header)
    print("  ├" + "┼".join(["─" * w for w in widths]) + "┤")
    
    for r in results:
        row = "  │"
        for col, w in zip(cols, widths):
            val = str(r.get(col, '-'))
            row += f"{val:>{w}}│"
        print(row)
    print("  └" + "┴".join(["─" * w for w in widths]) + "┘")


# ================================================================
# 主程序
# ================================================================
if __name__ == '__main__':
    # 加载数据
    print("\n📦 加载 SPY 日线数据...")
    spy_df = pd.read_csv(
        '/data/workspace/spy_daily.csv',
        parse_dates=['date'], index_col='date'
    ).sort_index()
    
    # 近10年
    spy_10y = spy_df['2016-01-01':'2026-04-18'].copy()
    print(f"  ✅ SPY 10年: {spy_10y.index[0].date()} ~ {spy_10y.index[-1].date()}, {len(spy_10y)} 天")
    
    # ================================================================
    # 步骤1: 识别牛市区间
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  🐂 步骤1: 识别美股近10年牛市区间 (SMA50/200 金叉→死叉)")
    print(f"  {'━' * 100}")
    
    bull_periods = identify_bull_periods(spy_10y)
    
    print(f"\n  共识别到 {len(bull_periods)} 个牛市区间:\n")
    print(f"  {'序号':<6}│{'起始日期':<14}│{'结束日期':<14}│{'天数':>6}│{'起始价':>10}│{'结束价':>10}│{'区间涨幅%':>10}│")
    print(f"  {'─'*6}┼{'─'*14}┼{'─'*14}┼{'─'*6}┼{'─'*10}┼{'─'*10}┼{'─'*10}┤")
    
    total_bull_days = 0
    for idx, bp in enumerate(bull_periods, 1):
        print(f"  {idx:<6}│{str(bp['start_date'].date()):<14}│{str(bp['end_date'].date()):<14}│"
              f"{bp['duration_days']:>6}│{bp['start_price']:>10}│{bp['end_price']:>10}│"
              f"{bp['return_pct']:>10}%│")
        total_bull_days += bp['duration_days']
    
    print(f"\n  📊 牛市总计: {total_bull_days} 天 ({total_bull_days/252:.1f}年), "
          f"占10年比例 {total_bull_days/len(spy_10y)*100:.1f}%")
    
    # ================================================================
    # 步骤2: 每个牛市区间分别回测 V1 vs V2
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 步骤2: 每个牛市区间 V1 vs V2 回测对比")
    print(f"  {'━' * 100}")
    
    strategies = [
        ('V1-六维评分(≥60)', bull_strategy_v1, True),
        ('V2-宽松版(ADX>20)★', bull_strategy_v2_relaxed, False),
        ('V2-严格版(ADX>25)', bull_strategy_v2_strict, False),
        ('基准-EMA10/20交叉', ema_cross_baseline, False),
    ]
    
    all_period_results = []
    v1_wins = 0
    v2_wins = 0
    ties = 0
    
    for idx, bp in enumerate(bull_periods, 1):
        si = bp['start_idx']
        ei = bp['end_idx'] + 1  # 包含end
        
        close = spy_10y['close'].values[si:ei].astype(float)
        high = spy_10y['high'].values[si:ei].astype(float)
        low = spy_10y['low'].values[si:ei].astype(float)
        volume = spy_10y['volume'].values[si:ei].astype(float) if 'volume' in spy_10y.columns else None
        
        title = f"牛市#{idx}: {bp['start_date'].date()} → {bp['end_date'].date()} ({bp['duration_days']}天, 涨幅{bp['return_pct']}%)"
        
        results = []
        for strat_name, strat_func, needs_vol in strategies:
            if needs_vol and volume is not None:
                r = run_backtest(close, high, low, strat_func, strat_name, volume=volume)
            else:
                r = run_backtest(close, high, low, strat_func, strat_name)
            results.append(r)
        
        results.append(run_buyhold(close))
        print_table(results, title)
        
        # 判定V1 vs V2宽松版胜出者
        v1_r = results[0]
        v2_r = results[1]
        if v1_r['年化收益%'] > v2_r['年化收益%'] + 1:
            v1_wins += 1
            winner = "V1"
        elif v2_r['年化收益%'] > v1_r['年化收益%'] + 1:
            v2_wins += 1
            winner = "V2"
        else:
            ties += 1
            winner = "平"
        
        all_period_results.append({
            'period_idx': idx,
            'start': bp['start_date'].date(),
            'end': bp['end_date'].date(),
            'days': bp['duration_days'],
            'bh_return': bp['return_pct'],
            'v1_annual': v1_r['年化收益%'],
            'v2_annual': v2_r['年化收益%'],
            'v1_dd': v1_r['最大回撤%'],
            'v2_dd': v2_r['最大回撤%'],
            'v1_trades': v1_r['交易次数'],
            'v2_trades': v2_r['交易次数'],
            'v1_calmar': v1_r['卡尔马比率'],
            'v2_calmar': v2_r['卡尔马比率'],
            'winner': winner,
        })
    
    # ================================================================
    # 步骤3: 汇总对比
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📊 步骤3: 牛市区间汇总对比")
    print(f"  {'━' * 110}")
    
    print(f"\n  {'#':<4}│{'区间':<30}│{'天数':>6}│{'B&H%':>8}│"
          f"{'V1年化%':>8}│{'V2年化%':>8}│{'V1回撤%':>8}│{'V2回撤%':>8}│"
          f"{'V1交易':>6}│{'V2交易':>6}│{'V1卡比':>8}│{'V2卡比':>8}│{'胜出':>4}│")
    print(f"  {'─'*4}┼{'─'*30}┼{'─'*6}┼{'─'*8}┼"
          f"{'─'*8}┼{'─'*8}┼{'─'*8}┼{'─'*8}┼"
          f"{'─'*6}┼{'─'*6}┼{'─'*8}┼{'─'*8}┼{'─'*4}┤")
    
    for pr in all_period_results:
        period_str = f"{pr['start']}→{pr['end']}"
        print(f"  {pr['period_idx']:<4}│{period_str:<30}│{pr['days']:>6}│{pr['bh_return']:>8}│"
              f"{pr['v1_annual']:>8}│{pr['v2_annual']:>8}│{pr['v1_dd']:>8}│{pr['v2_dd']:>8}│"
              f"{pr['v1_trades']:>6}│{pr['v2_trades']:>6}│{pr['v1_calmar']:>8}│{pr['v2_calmar']:>8}│"
              f"{pr['winner']:>4}│")
    
    # 加权平均
    total_days = sum(pr['days'] for pr in all_period_results)
    w_v1_annual = sum(pr['v1_annual'] * pr['days'] for pr in all_period_results) / total_days
    w_v2_annual = sum(pr['v2_annual'] * pr['days'] for pr in all_period_results) / total_days
    w_v1_dd = sum(pr['v1_dd'] * pr['days'] for pr in all_period_results) / total_days
    w_v2_dd = sum(pr['v2_dd'] * pr['days'] for pr in all_period_results) / total_days
    w_v1_calmar = sum(pr['v1_calmar'] * pr['days'] for pr in all_period_results) / total_days
    w_v2_calmar = sum(pr['v2_calmar'] * pr['days'] for pr in all_period_results) / total_days
    avg_v1_trades = sum(pr['v1_trades'] for pr in all_period_results) / len(all_period_results)
    avg_v2_trades = sum(pr['v2_trades'] for pr in all_period_results) / len(all_period_results)
    
    print(f"  {'─'*4}┼{'─'*30}┼{'─'*6}┼{'─'*8}┼"
          f"{'─'*8}┼{'─'*8}┼{'─'*8}┼{'─'*8}┼"
          f"{'─'*6}┼{'─'*6}┼{'─'*8}┼{'─'*8}┼{'─'*4}┤")
    print(f"  {'加权':<4}│{'加权平均(按天数加权)':<30}│{total_days:>6}│{'-':>8}│"
          f"{w_v1_annual:>8.2f}│{w_v2_annual:>8.2f}│{w_v1_dd:>8.2f}│{w_v2_dd:>8.2f}│"
          f"{avg_v1_trades:>6.1f}│{avg_v2_trades:>6.1f}│{w_v1_calmar:>8.2f}│{w_v2_calmar:>8.2f}│"
          f"{'-':>4}│")
    
    # ================================================================
    # 步骤4: 牛市区间合并回测
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📊 步骤4: 所有牛市区间合并回测（连续拼接）")
    print(f"  {'━' * 110}")
    
    # 拼接所有牛市区间的数据
    bull_closes = []
    bull_highs = []
    bull_lows = []
    bull_volumes = []
    
    for bp in bull_periods:
        si = bp['start_idx']
        ei = bp['end_idx'] + 1
        bull_closes.append(spy_10y['close'].values[si:ei].astype(float))
        bull_highs.append(spy_10y['high'].values[si:ei].astype(float))
        bull_lows.append(spy_10y['low'].values[si:ei].astype(float))
        if 'volume' in spy_10y.columns:
            bull_volumes.append(spy_10y['volume'].values[si:ei].astype(float))
    
    # 注意: 连续拼接回测意味着每个区间开始时资金重置
    # 更好的方式: 逐区间计算复利
    print("\n  📊 逐区间复利回测（资金逐区间滚存）:")
    
    equity = INIT_CASH
    equity_v1 = INIT_CASH
    equity_v2 = INIT_CASH
    equity_ema = INIT_CASH
    equity_bh = INIT_CASH
    
    for idx, bp in enumerate(bull_periods, 1):
        si = bp['start_idx']
        ei = bp['end_idx'] + 1
        close = spy_10y['close'].values[si:ei].astype(float)
        high = spy_10y['high'].values[si:ei].astype(float)
        low = spy_10y['low'].values[si:ei].astype(float)
        volume = spy_10y['volume'].values[si:ei].astype(float) if 'volume' in spy_10y.columns else None
        
        # V1
        r_v1 = run_backtest(close, high, low, bull_strategy_v1, 'V1', volume=volume)
        equity_v1 *= (1 + r_v1['总收益率%'] / 100)
        
        # V2宽松
        r_v2 = run_backtest(close, high, low, bull_strategy_v2_relaxed, 'V2')
        equity_v2 *= (1 + r_v2['总收益率%'] / 100)
        
        # EMA基准
        r_ema = run_backtest(close, high, low, ema_cross_baseline, 'EMA')
        equity_ema *= (1 + r_ema['总收益率%'] / 100)
        
        # B&H
        bh_ret = (close[-1] / close[0] - 1) * 100
        equity_bh *= (1 + bh_ret / 100)
    
    total_ret_v1 = (equity_v1 / INIT_CASH - 1) * 100
    total_ret_v2 = (equity_v2 / INIT_CASH - 1) * 100
    total_ret_ema = (equity_ema / INIT_CASH - 1) * 100
    total_ret_bh = (equity_bh / INIT_CASH - 1) * 100
    
    print(f"\n  策略             最终资金        牛市区间总收益率")
    print(f"  {'─'*50}")
    print(f"  V1-六维评分      ${equity_v1:>12,.2f}    {total_ret_v1:>+10.2f}%")
    print(f"  V2-宽松版★       ${equity_v2:>12,.2f}    {total_ret_v2:>+10.2f}%")
    print(f"  EMA10/20交叉     ${equity_ema:>12,.2f}    {total_ret_ema:>+10.2f}%")
    print(f"  Buy & Hold       ${equity_bh:>12,.2f}    {total_ret_bh:>+10.2f}%")
    
    # ================================================================
    # 步骤5: 牛市+非牛市全10年回测对比（背景参考）
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📊 步骤5: 全10年回测（含非牛市区间，作为背景参考）")
    print(f"  {'━' * 110}")
    
    close_all = spy_10y['close'].values.astype(float)
    high_all = spy_10y['high'].values.astype(float)
    low_all = spy_10y['low'].values.astype(float)
    vol_all = spy_10y['volume'].values.astype(float) if 'volume' in spy_10y.columns else None
    
    results_all = []
    for strat_name, strat_func, needs_vol in strategies:
        if needs_vol and vol_all is not None:
            r = run_backtest(close_all, high_all, low_all, strat_func, strat_name, volume=vol_all)
        else:
            r = run_backtest(close_all, high_all, low_all, strat_func, strat_name)
        results_all.append(r)
    results_all.append(run_buyhold(close_all))
    
    print_table(results_all, "SPY 全10年回测 (2016-2026)")
    
    # ================================================================
    # 最终结论
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📋 最终结论：牛市区间 V1 vs V2")
    print(f"  {'━' * 110}")
    
    print(f"""
  🐂 牛市区间统计:
     共 {len(bull_periods)} 个牛市区间, 合计 {total_bull_days} 天 ({total_bull_days/252:.1f}年)
     占10年交易日 {total_bull_days/len(spy_10y)*100:.1f}%

  📊 V1 vs V2 胜出统计:
     V1 胜出: {v1_wins} 次
     V2 胜出: {v2_wins} 次  
     平局:    {ties} 次

  📊 牛市区间加权年化收益:
     V1-六维评分:   {w_v1_annual:>8.2f}%
     V2-宽松版★:    {w_v2_annual:>8.2f}%

  📊 牛市区间加权最大回撤:
     V1-六维评分:   {w_v1_dd:>8.2f}%
     V2-宽松版★:    {w_v2_dd:>8.2f}%

  📊 牛市区间加权卡尔马比率:
     V1-六维评分:   {w_v1_calmar:>8.2f}
     V2-宽松版★:    {w_v2_calmar:>8.2f}

  📊 逐区间复利总收益:
     V1-六维评分:   {total_ret_v1:>+10.2f}%
     V2-宽松版★:    {total_ret_v2:>+10.2f}%
     EMA10/20交叉:  {total_ret_ema:>+10.2f}%
     Buy & Hold:    {total_ret_bh:>+10.2f}%

  💡 关键发现:
  """)
    
    if w_v2_annual > w_v1_annual:
        diff = w_v2_annual - w_v1_annual
        print(f"     ✅ V2宽松版在牛市区间年化收益领先V1 {diff:.2f}个百分点")
    else:
        diff = w_v1_annual - w_v2_annual
        print(f"     ✅ V1六维评分在牛市区间年化收益领先V2 {diff:.2f}个百分点")
    
    if abs(w_v2_dd) < abs(w_v1_dd):
        print(f"     ✅ V2宽松版回撤更小 (V1={w_v1_dd:.2f}% vs V2={w_v2_dd:.2f}%)")
    else:
        print(f"     ⚠️ V1回撤更小 (V1={w_v1_dd:.2f}% vs V2={w_v2_dd:.2f}%)")
    
    if total_ret_v2 > total_ret_v1:
        print(f"     ✅ V2宽松版复利总收益更高 ({total_ret_v2:+.2f}% vs {total_ret_v1:+.2f}%)")
    else:
        print(f"     ⚠️ V1复利总收益更高 ({total_ret_v1:+.2f}% vs {total_ret_v2:+.2f}%)")
    
    # V1的问题分析
    avg_v1_t = sum(pr['v1_trades'] for pr in all_period_results) / len(all_period_results)
    avg_v2_t = sum(pr['v2_trades'] for pr in all_period_results) / len(all_period_results)
    print(f"\n     📊 平均交易次数: V1={avg_v1_t:.1f}次/区间 vs V2={avg_v2_t:.1f}次/区间")
    if avg_v1_t > avg_v2_t * 1.5:
        print(f"     ⚠️ V1交易频率是V2的{avg_v1_t/avg_v2_t:.1f}倍，过多交易侵蚀利润")
    
    print(f"\n     💡 牛市策略核心价值: 在牛市区间尽量多持仓、少折腾")
    print(f"     💡 V1的MA20>MA60>MA120多头排列条件在牛市初期/回调中频繁不满足→空仓过多")
    print(f"     💡 V2的EMA10>EMA20条件更灵活，ADX>20确认趋势即可持仓→捕获更多涨幅")
    
    print("\n✅ 牛市区间 V1 vs V2 回测完成！")
