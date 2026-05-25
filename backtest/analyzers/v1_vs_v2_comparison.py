#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blakever 牛市策略 V1 vs V2 近5年回测对比
==========================================
V1: 六维评分选股系统（技术面+动量+成交量+RSI+ADX+布林带），逐日评分驱动持仓
V2: EMA10/20 + ADX 趋势过滤信号策略，纯信号驱动

回测标的：SPY（美股）、HSI（港股）
回测区间：2021-01-01 ~ 2026-04-17（近5年）
框架：VectorBT + TA-Lib
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
START_DATE = '2021-01-01'
END_DATE = '2026-04-18'

# ================================================================
# V1 策略：六维评分系统 → 转化为信号
# ================================================================
def bull_strategy_v1(close, high, low, volume=None):
    """
    V1: 六维评分选股策略
    - 技术面(30分): 均线多头排列 + MACD金叉加分
    - 动量面(20分): 20日收益率
    - 成交量面(15分): 成交量放大
    - RSI健康度(15分): 50-70区间最佳
    - 趋势强度(10分): ADX
    - 布林带位置(10分): 价格在中轨以上但未超上轨
    
    评分>=60 → 持仓, <60 → 空仓
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    v = pd.Series(volume, dtype=float) if volume is not None else pd.Series(np.ones(len(c)))
    
    n = len(c)
    
    # 计算指标
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    ma120 = c.rolling(120).mean()
    rsi14 = pd.Series(talib.RSI(c.values, timeperiod=14))
    adx14 = pd.Series(talib.ADX(h.values, l.values, c.values, timeperiod=14))
    macd, macd_signal, macd_hist = talib.MACD(c.values)
    macd_s = pd.Series(macd)
    macd_signal_s = pd.Series(macd_signal)
    
    # 布林带
    bb_upper = pd.Series(talib.BBANDS(c.values, nbdevup=2)[0])
    bb_mid = pd.Series(talib.BBANDS(c.values, nbdevup=2)[1])
    bb_lower = pd.Series(talib.BBANDS(c.values, nbdevup=2)[2])
    
    # 成交量均线
    vol_ma20 = v.rolling(20).mean()
    vol_ratio = v / vol_ma20.replace(0, np.nan)
    
    # ATR
    atr20 = pd.Series(talib.ATR(h.values, l.values, c.values, timeperiod=20))
    
    # 20日收益率
    ret_20d = c.pct_change(20)
    
    # 逐日评分
    scores = pd.Series(0.0, index=c.index)
    
    for i in range(120, n):  # 从120日开始（确保MA120可用）
        s = 0.0
        
        # 1. 技术面 (30分)
        c_val = c.iloc[i]
        ma20_val = ma20.iloc[i]
        ma60_val = ma60.iloc[i]
        ma120_val = ma120.iloc[i]
        
        if not pd.isna(ma120_val):
            if ma20_val > ma60_val > ma120_val and c_val > ma20_val:
                s += 30
            elif ma20_val > ma60_val and c_val > ma20_val:
                s += 18
            elif c_val > ma20_val:
                s += 8
        
        # MACD金叉加分
        if not pd.isna(macd_s.iloc[i]) and not pd.isna(macd_signal_s.iloc[i]):
            if macd_s.iloc[i] > macd_signal_s.iloc[i] and macd_s.iloc[i] > 0:
                s += 5
        
        # 2. 动量面 (20分)
        if not pd.isna(ret_20d.iloc[i]):
            s += min(20, max(0, ret_20d.iloc[i] * 100))
        
        # 3. 成交量面 (15分)
        if not pd.isna(vol_ratio.iloc[i]) and vol_ratio.iloc[i] > 0:
            if vol_ratio.iloc[i] > 1.5:
                s += 15
            elif vol_ratio.iloc[i] > 1.2:
                s += 10
            elif vol_ratio.iloc[i] > 1.0:
                s += 5
        
        # 4. RSI健康度 (15分)
        rsi_val = rsi14.iloc[i]
        if not pd.isna(rsi_val):
            if 50 <= rsi_val <= 70:
                s += 15
            elif 45 <= rsi_val <= 75:
                s += 8
            elif rsi_val > 80:
                s += 0
            else:
                s += 3
        
        # 5. 趋势强度 ADX (10分)
        adx_val = adx14.iloc[i]
        if not pd.isna(adx_val):
            if adx_val > 30:
                s += 10
            elif adx_val > 20:
                s += 6
            else:
                s += 2
        
        # 6. 布林带位置 (10分)
        bb_u = bb_upper.iloc[i]
        bb_m = bb_mid.iloc[i]
        if not pd.isna(bb_u) and not pd.isna(bb_m):
            if bb_m < c_val < bb_u:
                s += 10
            elif c_val >= bb_u:
                s += 3
        
        scores.iloc[i] = min(100, s)
    
    # 持仓条件: 评分 >= 60
    in_pos = scores >= 60
    
    # 生成入场/出场信号
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    
    return entries, exits


# ================================================================
# V2 策略：EMA10/20 + ADX 趋势过滤（宽松版，推荐）
# ================================================================
def bull_strategy_v2_relaxed(close, high, low):
    """
    V2 宽松版: EMA10 > EMA20 且 ADX > 20 → 持仓
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)

    in_pos = (ema10 > ema20) & (adx_s > 20)

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


def bull_strategy_v2_strict(close, high, low):
    """
    V2 严格版: EMA10 > EMA20 且 ADX > 25 → 持仓
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)

    in_pos = (ema10 > ema20) & (adx_s > 25)

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


# ================================================================
# EMA交叉基准（无ADX过滤）
# ================================================================
def ema_cross_baseline(close, high, low):
    """EMA10/20 无条件交叉"""
    c = pd.Series(close, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    in_pos = ema10 > ema20
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# 回测执行
# ================================================================
def run_backtest(close, high, low, strategy_func, strategy_name, volume=None):
    """运行单个策略回测"""
    try:
        if volume is not None:
            entries, exits = strategy_func(close, high, low, volume)
        else:
            entries, exits = strategy_func(close, high, low)

        if entries.sum() == 0:
            return {
                '策略': strategy_name, '状态': '无交易信号',
                '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0,
                '持仓占比%': 0, '卡尔马比率': 0
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

        # 持仓占比
        positions = pf.asset_flow() != 0
        in_pos_count = (pf.asset_flow() == 0).sum()  # 近似
        # 更准确：用entries/exits计算
        pos_arr = np.zeros(len(close), dtype=bool)
        in_position = False
        for i in range(len(close)):
            if entries[i]:
                in_position = True
            elif exits[i]:
                in_position = False
            pos_arr[i] = in_position
        hold_pct = pos_arr.sum() / len(close) * 100

        # 卡尔马比率
        calmar = annual / abs(max_dd) if max_dd != 0 else 0

        return {
            '策略': strategy_name,
            '状态': '✅',
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
        return {
            '策略': strategy_name, '状态': f'❌ {e}',
            '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
            '胜率%': 0, '交易次数': 0, '盈亏比': 0,
            '持仓占比%': 0, '卡尔马比率': 0
        }


def run_buyhold(close):
    """Buy & Hold 基准"""
    n = len(close)
    entries = np.full(n, False)
    entries[0] = True
    exits = np.full(n, False)
    pf = vbt.Portfolio.from_signals(
        close, entries=entries, exits=exits,
        freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
    )
    stats = pf.stats()
    total_return = float(stats['Total Return [%]'])
    n_years = len(pf.returns()) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    max_dd = float(stats['Max Drawdown [%]'])
    calmar = annual / abs(max_dd) if max_dd != 0 else 0
    return {
        '策略': 'Buy & Hold',
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '胜率%': '-',
        '交易次数': 1,
        '盈亏比': '-',
        '持仓占比%': 100.0,
        '卡尔马比率': round(calmar, 2),
    }


def print_comparison_table(results, title="策略对比"):
    """打印策略对比表"""
    cols = ['策略', '状态', '总收益率%', '年化收益%', '最大回撤%', '胜率%', '交易次数', '盈亏比', '持仓占比%', '卡尔马比率']
    widths = [28, 6, 12, 12, 10, 8, 8, 8, 10, 10]
    
    total_w = int(sum(widths)) + len(widths) * 3 + 1
    print(f"\n{'━' * total_w}")
    print(f"  📊 {title}")
    print(f"{'━' * total_w}")
    
    header = "│"
    for col, w in zip(cols, widths):
        header += f"{col:>{w}}│"
    print(header)
    print("├" + "┼".join(["─" * w for w in widths]) + "┤")
    
    for r in results:
        row = "│"
        for col, w in zip(cols, widths):
            val = str(r.get(col, '-'))
            row += f"{val:>{w}}│"
        print(row)
    print("└" + "┴".join(["─" * w for w in widths]) + "┘")


# ================================================================
# 主程序
# ================================================================
if __name__ == '__main__':
    # 加载数据
    print("\n📦 加载数据...")
    spy_df = pd.read_csv(
        '/data/workspace/spy_daily.csv',
        parse_dates=['date'], index_col='date'
    ).sort_index()
    hsi_df = pd.read_csv(
        '/data/workspace/hsi_daily.csv',
        parse_dates=['date'], index_col='date'
    ).sort_index()
    
    # 截取近5年
    spy_df = spy_df[START_DATE:END_DATE]
    hsi_df = hsi_df[START_DATE:END_DATE]
    
    print(f"  ✅ SPY: {spy_df.index[0].date()} ~ {spy_df.index[-1].date()}, {len(spy_df)} 天")
    print(f"  ✅ HSI: {hsi_df.index[0].date()} ~ {hsi_df.index[-1].date()}, {len(hsi_df)} 天")
    
    # 策略列表
    strategies = [
        ('V1-六维评分(≥60持仓)', bull_strategy_v1, True),   # 需要volume
        ('V2-宽松版(ADX>20)★', bull_strategy_v2_relaxed, False),
        ('V2-严格版(ADX>25)', bull_strategy_v2_strict, False),
        ('基准-EMA10/20交叉', ema_cross_baseline, False),
    ]
    
    # ================================================================
    # 港美股分别回测
    # ================================================================
    all_results = {}
    
    for market_name, df in [("SPY (美股)", spy_df), ("HSI (港股)", hsi_df)]:
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        volume = df['volume'].values.astype(float) if 'volume' in df.columns else None
        
        results = []
        for strat_name, strat_func, needs_vol in strategies:
            print(f"  ⏳ 运行 {strat_name} @ {market_name}...")
            if needs_vol and volume is not None:
                r = run_backtest(close, high, low, strat_func, strat_name, volume=volume)
            else:
                r = run_backtest(close, high, low, strat_func, strat_name)
            results.append(r)
        
        # Buy & Hold
        results.append(run_buyhold(close))
        
        print_comparison_table(results, f"{market_name} 近5年策略对比")
        all_results[market_name] = results
    
    # ================================================================
    # V1 vs V2 深度对比分析
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📋 V1 vs V2 深度对比分析")
    print(f"{'━' * 110}")
    
    for market_name, results in all_results.items():
        print(f"\n  📈 {market_name}:")
        v1 = results[0]
        v2r = results[1]
        v2s = results[2]
        
        # 年化收益对比
        print(f"     年化收益: V1={v1['年化收益%']}% | V2宽松={v2r['年化收益%']}% | V2严格={v2s['年化收益%']}%")
        
        # 最大回撤对比
        print(f"     最大回撤: V1={v1['最大回撤%']}% | V2宽松={v2r['最大回撤%']}% | V2严格={v2s['最大回撤%']}%")
        
        # 卡尔马比率对比
        print(f"     卡尔马比: V1={v1['卡尔马比率']} | V2宽松={v2r['卡尔马比率']} | V2严格={v2s['卡尔马比率']}")
        
        # 持仓占比对比
        print(f"     持仓占比: V1={v1['持仓占比%']}% | V2宽松={v2r['持仓占比%']}% | V2严格={v2s['持仓占比%']}%")
        
        # 胜率对比
        print(f"     胜率:     V1={v1['胜率%']}% | V2宽松={v2r['胜率%']}% | V2严格={v2s['胜率%']}%")
        
        # 盈亏比对比
        print(f"     盈亏比:   V1={v1['盈亏比']} | V2宽松={v2r['盈亏比']} | V2严格={v2s['盈亏比']}")
        
        # 交易次数对比
        print(f"     交易次数: V1={v1['交易次数']} | V2宽松={v2r['交易次数']} | V2严格={v2s['交易次数']}")
        
        # 综合评价
        print(f"\n     ── 综合评价 ──")
        
        # 判断谁更优
        v1_score = 0
        v2r_score = 0
        
        if v1['年化收益%'] > v2r['年化收益%']:
            v1_score += 1
        else:
            v2r_score += 1
        
        if abs(v1['最大回撤%']) < abs(v2r['最大回撤%']):
            v1_score += 1
        else:
            v2r_score += 1
        
        if v1['卡尔马比率'] > v2r['卡尔马比率']:
            v1_score += 2
        else:
            v2r_score += 2
        
        if v1['胜率%'] != '-' and v2r['胜率%'] != '-':
            if v1['胜率%'] > v2r['胜率%']:
                v1_score += 1
            else:
                v2r_score += 1
        
        winner = "V1-六维评分" if v1_score > v2r_score else "V2-EMA+ADX(宽松)"
        print(f"     胜出者: {winner} (V1={v1_score}分, V2宽松={v2r_score}分)")
    
    # ================================================================
    # 分年度回测
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📊 分年度回测 (V1 vs V2宽松)")
    print(f"{'━' * 110}")
    
    for market_name, df in [("SPY", spy_df), ("HSI", hsi_df)]:
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        volume = df['volume'].values.astype(float) if 'volume' in df.columns else None
        dates = df.index
        
        print(f"\n  📈 {market_name} 分年度:")
        print(f"  {'年份':<8}│{'V1年化%':>10}│{'V2年化%':>10}│{'V1回撤%':>10}│{'V2回撤%':>10}│{'V1交易':>8}│{'V2交易':>8}│{'胜出':>8}│")
        print(f"  {'─'*8}┼{'─'*10}┼{'─'*10}┼{'─'*10}┼{'─'*10}┼{'─'*8}┼{'─'*8}┼{'─'*8}┤")
        
        for year in range(2021, 2027):
            mask = dates.year == year
            if mask.sum() < 50:
                continue
            
            yr_close = close[mask]
            yr_high = high[mask]
            yr_low = low[mask]
            yr_vol = volume[mask] if volume is not None else None
            
            r_v1 = run_backtest(yr_close, yr_high, yr_low, bull_strategy_v1, 'V1', volume=yr_vol)
            r_v2 = run_backtest(yr_close, yr_high, yr_low, bull_strategy_v2_relaxed, 'V2')
            
            winner = "V1" if r_v1['年化收益%'] > r_v2['年化收益%'] else "V2"
            if abs(r_v1['年化收益%'] - r_v2['年化收益%']) < 1:
                winner = "平"
            
            print(f"  {year:<8}│{r_v1['年化收益%']:>10}│{r_v2['年化收益%']:>10}│{r_v1['最大回撤%']:>10}│{r_v2['最大回撤%']:>10}│{r_v1['交易次数']:>8}│{r_v2['交易次数']:>8}│{winner:>8}│")
    
    # ================================================================
    # 总结
    # ================================================================
    print(f"\n{'━' * 110}")
    print("  📋 总结")
    print(f"{'━' * 110}")
    print("""
    V1 策略特点（六维评分系统）:
    ├─ 优点: 多维度综合评估，持仓条件更苛刻，在震荡/熊市中空仓更多，回撤可能更小
    ├─ 缺点: 评分阈值(≥60)缺乏弹性，均线多头排列条件过于严格导致空仓过多
    └─ 适用: 保守型投资者，更看重回撤控制

    V2 策略特点（EMA+ADX信号）:
    ├─ 优点: 逻辑简洁，信号明确，ADX>20宽松版在牛市中捕获更多涨幅
    ├─ 缺点: 单一维度过滤，在震荡市中可能频繁交易
    └─ 适用: 平衡型投资者，追求收益与回撤的平衡

    关键差异:
    ├─ V1依赖MA20>MA60>MA120多头排列，这在震荡市中很难满足 → 过度空仓
    ├─ V2仅要求EMA10>EMA20，更灵活，但也更容易在假突破中入场
    ├─ V2宽松版(ADX>20)在18年回测中已被验证优于严格版(ADX>25)
    └─ 建议: V2宽松版作为主力策略，V1评分系统作为辅助筛选工具
    """)

    print("\n✅ V1 vs V2 近5年回测对比完成！")
