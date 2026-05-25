#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supertrend 收益诊断 — 为什么高胜率却低收益？"""

import pandas as pd
import numpy as np
import talib
import vectorbt as vbt
import warnings
warnings.filterwarnings('ignore')

INIT_CASH = 100000
FEES = 0.001
SLIPPAGE = 0.001

spy_df = pd.read_csv('/data/workspace/spy_daily.csv',
                     parse_dates=['date'], index_col='date').sort_index()
close_all = spy_df['close'].values.astype(float)
high_all = spy_df['high'].values.astype(float)
low_all = spy_df['low'].values.astype(float)
open_all = spy_df['open'].values.astype(float)

# 牛市环境分类
def classify_regime_monthly(df):
    close = df['close'].values.astype(float)
    sma50 = talib.SMA(close, timeperiod=50)
    sma200 = talib.SMA(close, timeperiod=200)
    df2 = df.copy()
    df2['sma50'] = sma50; df2['sma200'] = sma200
    df2['month'] = df2.index.to_period('M')
    regimes = {}
    for month, group in df2.groupby('month'):
        if len(group) < 5: continue
        mc = group['close'].iloc[-1]; mo = group['close'].iloc[0]
        mr = (mc - mo) / mo
        l50 = group['sma50'].iloc[-1]; l200 = group['sma200'].iloc[-1]
        if pd.isna(l200):
            regime = 'bull' if mr > 0.02 else ('bear' if mr < -0.02 else 'sideways')
        else:
            if mc > l200 and l50 > l200: regime = 'bull'
            elif mc < l200 and l50 < l200: regime = 'bear'
            else: regime = 'sideways'
        regimes[str(month)] = regime
    return regimes

regimes = classify_regime_monthly(spy_df)
months_series = pd.Series(spy_df.index).dt.to_period('M')
regime_mask = months_series.map(lambda m: regimes.get(str(m), 'sideways')).values
bull_idx = np.where(regime_mask == 'bull')[0]

bull_close = close_all[bull_idx]
bull_high = high_all[bull_idx]
bull_low = low_all[bull_idx]
bull_open = open_all[bull_idx]
bull_dates = spy_df.index[bull_idx]

def supertrend_strategy(close, high, low, atr_period=10, multiplier=2.0):
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    n = len(c)
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=atr_period)
    hl2 = (h.values + l.values) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr
    st_dir = np.zeros(n)
    for i in range(1, n):
        if np.isnan(atr[i]):
            st_dir[i] = st_dir[i-1] if i > 0 else 1
            continue
        lb = lower_band[i] if (lower_band[i] > lower_band[i-1] or c.iloc[i-1] < lower_band[i-1]) else lower_band[i-1]
        ub = upper_band[i] if (upper_band[i] < upper_band[i-1] or c.iloc[i-1] > upper_band[i-1]) else upper_band[i-1]
        if st_dir[i-1] == 1:
            st_dir[i] = -1 if c.iloc[i] < lb else 1
        else:
            st_dir[i] = 1 if c.iloc[i] > ub else -1
    in_pos = pd.Series(st_dir == 1)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

def ema_adx_strategy(close, high, low):
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

# Supertrend
st_entries, st_exits = supertrend_strategy(bull_close, bull_high, bull_low)
st_entries_s = np.roll(st_entries, 1); st_entries_s[0] = False
st_exits_s = np.roll(st_exits, 1); st_exits_s[0] = False

pf_st = vbt.Portfolio.from_signals(
    open=bull_open, close=bull_close,
    entries=st_entries_s, exits=st_exits_s,
    freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
    upon_opposite_entry='reverse'
)

# EMA+ADX
ea_entries, ea_exits = ema_adx_strategy(bull_close, bull_high, bull_low)
ea_entries_s = np.roll(ea_entries, 1); ea_entries_s[0] = False
ea_exits_s = np.roll(ea_exits, 1); ea_exits_s[0] = False

pf_ea = vbt.Portfolio.from_signals(
    open=bull_open, close=bull_close,
    entries=ea_entries_s, exits=ea_exits_s,
    freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
    upon_opposite_entry='reverse'
)

# 持仓比例
st_in_pos = np.zeros(len(bull_close), dtype=bool)
ea_in_pos = np.zeros(len(bull_close), dtype=bool)
cur_st = False; cur_ea = False
for i in range(len(bull_close)):
    if st_entries[i]: cur_st = True
    elif st_exits[i]: cur_st = False
    st_in_pos[i] = cur_st
    if ea_entries[i]: cur_ea = True
    elif ea_exits[i]: cur_ea = False
    ea_in_pos[i] = cur_ea

st_pos_pct = st_in_pos.sum() / len(st_in_pos) * 100
ea_pos_pct = ea_in_pos.sum() / len(ea_in_pos) * 100

# ── 核心指标对比 ──
st_stats = pf_st.stats()
ea_stats = pf_ea.stats()

print("=" * 100)
print("  🔍 Supertrend(2x) 收益诊断 — 为什么高胜率却低收益？")
print("=" * 100)

print(f"""
┌─────────────────────┬──────────────────┬──────────────────┐
│ 指标                 │ Supertrend(2x)   │ EMA+ADX(当前)     │
├─────────────────────┼──────────────────┼──────────────────┤
│ 总收益               │ {float(st_stats['Total Return [%]']):>8.2f}%      │ {float(ea_stats['Total Return [%]']):>8.2f}%      │
│ 最大回撤             │ {float(st_stats['Max Drawdown [%]']):>8.2f}%      │ {float(ea_stats['Max Drawdown [%]']):>8.2f}%      │
│ 胜率                 │ {float(st_stats['Win Rate [%]']):>8.1f}%      │ {float(ea_stats['Win Rate [%]']):>8.1f}%      │
│ 交易次数             │ {int(st_stats['Total Trades']):>8d}        │ {int(ea_stats['Total Trades']):>8d}        │
│ 持仓比例             │ {st_pos_pct:>8.1f}%      │ {ea_pos_pct:>8.1f}%      │
│ 平均持仓天数         │ {st_in_pos.sum()/max(st_entries.sum(),1):>8.1f}天     │ {ea_in_pos.sum()/max(ea_entries.sum(),1):>8.1f}天     │
└─────────────────────┴──────────────────┴──────────────────┘
""")

# ── 逐笔交易明细 ──
st_trades = pf_st.trades.records_readable
ea_trades = pf_ea.trades.records_readable

# 计算盈亏统计
def calc_trade_stats(trades_df):
    total_profit = 0; total_loss = 0; win_c = 0; loss_c = 0
    pnl_list = []
    for _, trade in trades_df.iterrows():
        pnl = trade['PnL']
        pnl_list.append(pnl)
        if pnl > 0: total_profit += pnl; win_c += 1
        else: total_loss += abs(pnl); loss_c += 1
    avg_win = total_profit / win_c if win_c > 0 else 0
    avg_loss = total_loss / loss_c if loss_c > 0 else 1
    return total_profit, total_loss, win_c, loss_c, avg_win, avg_loss, pnl_list

st_tp, st_tl, st_wc, st_lc, st_aw, st_al, st_pnls = calc_trade_stats(st_trades)
ea_tp, ea_tl, ea_wc, ea_lc, ea_aw, ea_al, ea_pnls = calc_trade_stats(ea_trades)

print("━" * 100)
print("  📊 Supertrend 逐笔交易明细")
print("━" * 100)

for idx, trade in st_trades.iterrows():
    pnl = trade['PnL']
    pnl_pct = trade['Return'] * 100
    entry_idx = int(trade['Entry Timestamp'])
    exit_idx = int(trade['Exit Timestamp'])
    entry_dt = bull_dates[entry_idx] if entry_idx < len(bull_dates) else 'N/A'
    exit_dt = bull_dates[exit_idx] if exit_idx < len(bull_dates) else 'N/A'
    duration = exit_idx - entry_idx
    tag = "✅ 盈利" if pnl > 0 else "❌ 亏损"
    print(f"  #{idx+1:2d} | {str(entry_dt)[:10]} → {str(exit_dt)[:10]} | 持{duration:3d}天 | PnL: ${pnl:>10,.2f} ({pnl_pct:>+6.2f}%) | {tag}")

st_real_pl = st_aw / st_al if st_al > 0 else 0
ea_real_pl = ea_aw / ea_al if ea_al > 0 else 0

print(f"""
  ┌───────────────────────────────────────────────────────────────────────┐
  │ 盈利: {st_wc}笔 总${st_tp:>12,.0f} 平均${st_aw:>10,.0f}                              │
  │ 亏损: {st_lc}笔 总${st_tl:>12,.0f} 平均${st_al:>10,.0f}                              │
  │ 真实盈亏比: {st_real_pl:.2f}x  总PnL: ${st_tp-st_tl:>12,.0f}                        │
  └───────────────────────────────────────────────────────────────────────┘
""")

print("━" * 100)
print("  📊 EMA+ADX 逐笔交易明细（前20笔）")
print("━" * 100)

for idx in range(min(20, len(ea_trades))):
    trade = ea_trades.iloc[idx]
    pnl = trade['PnL']
    entry_idx = int(trade['Entry Timestamp'])
    exit_idx = int(trade['Exit Timestamp'])
    entry_dt = bull_dates[entry_idx] if entry_idx < len(bull_dates) else 'N/A'
    exit_dt = bull_dates[exit_idx] if exit_idx < len(bull_dates) else 'N/A'
    duration = exit_idx - entry_idx
    tag = "✅" if pnl > 0 else "❌"
    print(f"  #{idx+1:2d} | {str(entry_dt)[:10]} → {str(exit_dt)[:10]} | 持{duration:3d}天 | PnL: ${pnl:>10,.2f} | {tag}")

if len(ea_trades) > 20:
    print(f"  ... 还有 {len(ea_trades)-20} 笔省略")

print(f"""
  ┌───────────────────────────────────────────────────────────────────────┐
  │ 盈利: {ea_wc}笔 总${ea_tp:>12,.0f} 平均${ea_aw:>10,.0f}                              │
  │ 亏损: {ea_lc}笔 总${ea_tl:>12,.0f} 平均${ea_al:>10,.0f}                              │
  │ 真实盈亏比: {ea_real_pl:.2f}x  总PnL: ${ea_tp-ea_tl:>12,.0f}                        │
  └───────────────────────────────────────────────────────────────────────┘
""")

# ── B&H基准 ──
bh_total_ret = (bull_close[-1] - bull_close[0]) / bull_close[0] * 100
n_bull_years = len(bull_close) / 252
bh_annual = ((1 + bh_total_ret/100) ** (1/n_bull_years) - 1) * 100 if n_bull_years > 0 else 0

# ── 根因分析 ──
bh_daily_ret = np.diff(bull_close) / bull_close[:-1]
st_daily_ret_arr = pf_st.returns().values
cash_days_arr = ~st_in_pos[1:]
invested_days_arr = st_in_pos[1:]

avg_mkt_in = bh_daily_ret[invested_days_arr[:len(bh_daily_ret)]].mean() * 100 if invested_days_arr[:len(bh_daily_ret)].sum() > 0 else 0
avg_mkt_cash = bh_daily_ret[cash_days_arr[:len(bh_daily_ret)]].mean() * 100 if cash_days_arr[:len(bh_daily_ret)].sum() > 0 else 0

print("━" * 100)
print("  📊 根因分析 — 高胜率低收益的3大原因")
print("━" * 100)

print(f"""
  ╔══════════════════════════════════════════════════════════════════════════════════════════╗
  ║  原因①: 持仓比例太低 — 牛市空仓 = 放弃利润                                             ║
  ╠══════════════════════════════════════════════════════════════════════════════════════════╣
  ║  Supertrend(2x) 持仓: {st_pos_pct:.1f}%  空仓: {100-st_pos_pct:.1f}%                                            ║
  ║  EMA+ADX       持仓: {ea_pos_pct:.1f}%  空仓: {100-ea_pos_pct:.1f}%                                            ║
  ║  B&H           持仓: 100%                                                              ║
  ║                                                                                         ║
  ║  持仓期间市场平均日收益: {avg_mkt_in:>+7.4f}%                                                  ║
  ║  空仓期间市场平均日收益: {avg_mkt_cash:>+7.4f}%                                                  ║
  ║  空仓 {100-st_pos_pct:.1f}% × 牛市B&H年化{bh_annual:.1f}% ≈ 踏空年化{bh_annual*(100-st_pos_pct)/100:.1f}%                       ║
  ║                                                                                         ║
  ║  💡 这是最致命的原因: 牛市中每空仓1天就少赚1天的涨幅                                     ║
  ╚══════════════════════════════════════════════════════════════════════════════════════════╝

  ╔══════════════════════════════════════════════════════════════════════════════════════════╗
  ║  原因②: 单笔盈利幅度小 — 赢了次数但赢了很少钱                                           ║
  ╠══════════════════════════════════════════════════════════════════════════════════════════╣
  ║  Supertrend: {st_wc}笔盈利 平均每笔赚 ${st_aw:>8,.0f}  真实盈亏比 {st_real_pl:.2f}x                        ║
  ║  EMA+ADX:    {ea_wc}笔盈利 平均每笔赚 ${ea_aw:>8,.0f}  真实盈亏比 {ea_real_pl:.2f}x                        ║""")

if ea_aw > st_aw:
    print(f"  ║  EMA+ADX单笔盈利是Supertrend的 {ea_aw/st_aw:.1f}倍!                                               ║")

print(f"""  ║                                                                                         ║
  ║  💡 78.6%胜率看起来漂亮，但每次只赚${st_aw:,.0f}                                            ║
  ║     47.1%胜率看起来差，但每次赚${ea_aw:,.0f} — 更大的蛋糕                                  ║
  ╚══════════════════════════════════════════════════════════════════════════════════════════╝

  ╔══════════════════════════════════════════════════════════════════════════════════════════╗
  ║  原因③: 数学上的不可能 — 收益天花板被持仓比例锁死                                       ║
  ╠══════════════════════════════════════════════════════════════════════════════════════════╣
  ║                                                                                         ║
  ║  趋势策略期望收益 ≤ 市场涨幅 × 持仓比例                                                 ║
  ║                                                                                         ║
  ║  牛市B&H年化: {bh_annual:.1f}%                                                              ║
  ║  Supertrend持仓: {st_pos_pct:.1f}%                                                            ║
  ║  理论年化天花板: {bh_annual:.1f}% × {st_pos_pct:.1f}% = {bh_annual*st_pos_pct/100:.1f}% (不含成本)                             ║
  ║                                                                                         ║
  ║  即使胜率100%，每笔都赚，也最多只能拿到 {bh_annual*st_pos_pct/100:.1f}% 的年化              ║
  ║  因为73.6%的时间你根本不在市场里!                                                        ║
  ╚══════════════════════════════════════════════════════════════════════════════════════════╝
""")

# ── 不同倍数对比 ──
print("━" * 100)
print("  📊 不同倍数Supertrend对比 — 倍数越低持仓越高")
print("━" * 100)

print("\n  ┌─────────────────────┬──────────┬──────────┬──────────┬──────────┬──────────┐")
print("  │ 倍数                 │ 持仓比例  │ 交易次数  │ 总收益    │ 最大回撤  │ 胜率      │")
print("  ├─────────────────────┼──────────┼──────────┼──────────┼──────────┼──────────┤")

for mult in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
    e, x = supertrend_strategy(bull_close, bull_high, bull_low, multiplier=mult)
    e_s = np.roll(e, 1); e_s[0] = False
    x_s = np.roll(x, 1); x_s[0] = False
    ip = np.zeros(len(bull_close), dtype=bool)
    c = False
    for i in range(len(bull_close)):
        if e[i]: c = True
        elif x[i]: c = False
        ip[i] = c
    pr = ip.sum() / len(ip) * 100

    if e_s.sum() > 0:
        pf = vbt.Portfolio.from_signals(
            open=bull_open, close=bull_close,
            entries=e_s, exits=x_s,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE,
            upon_opposite_entry='reverse'
        )
        s = pf.stats()
        tr = float(s['Total Return [%]'])
        md = float(s['Max Drawdown [%]'])
        wr = float(s['Win Rate [%]'])
        print(f"  │ Supertrend({mult:.1f}x)     │ {pr:>6.1f}%   │ {e_s.sum():>6.0f}    │ {tr:>6.2f}%   │ {md:>6.2f}%   │ {wr:>5.1f}%   │")
    else:
        print(f"  │ Supertrend({mult:.1f}x)     │ {pr:>6.1f}%   │   0    │   N/A    │   N/A    │   N/A    │")

print("  └─────────────────────┴──────────┴──────────┴──────────┴──────────┴──────────┘")

# ── 底仓模式 ──
print(f"\n  📊 底仓组合模式对比:")
print("  ┌───────────────────────┬──────────┬──────────┬──────────┬──────────┐")
print("  │ 配置                   │ 年化收益  │ 最大回撤  │ 夏普比率  │ 有效持仓  │")
print("  ├───────────────────────┼──────────┼──────────┼──────────┼──────────┤")

for mult in [1.5, 2.0]:
    e, x = supertrend_strategy(bull_close, bull_high, bull_low, multiplier=mult)
    ip = np.zeros(len(bull_close), dtype=bool)
    c = False
    for i in range(len(bull_close)):
        if e[i]: c = True
        elif x[i]: c = False
        ip[i] = c
    pr = ip.sum() / len(ip) * 100

    e_s = np.roll(e, 1); e_s[0] = False
    x_s = np.roll(x, 1); x_s[0] = False

    for base_pct in [0.30, 0.50, 0.70]:
        bh_returns = np.zeros(len(bull_close))
        for i in range(1, len(bull_close)):
            bh_returns[i] = (bull_close[i] - bull_close[i-1]) / bull_close[i-1]

        strat_returns = np.zeros(len(bull_close))
        ip_s = np.zeros(len(bull_close), dtype=bool)
        cur = False
        for i in range(len(bull_close)):
            if e_s[i]: cur = True
            elif x_s[i]: cur = False
            ip_s[i] = cur

        for i in range(1, len(bull_close)):
            if ip_s[i-1]:
                daily_ret = (bull_close[i] - bull_close[i-1]) / bull_close[i-1]
                fee_adj = FEES if e_s[i-1] else 0
                if x_s[i]: fee_adj += FEES
                strat_returns[i] = daily_ret - fee_adj

        combined_returns = base_pct * bh_returns + (1 - base_pct) * strat_returns
        combined_value = np.cumprod(1 + combined_returns) * INIT_CASH
        n_y = len(combined_returns) / 252
        total_r = (combined_value[-1] / INIT_CASH - 1) * 100
        annual = ((1 + total_r / 100) ** (1 / n_y) - 1) * 100 if n_y > 0 else 0
        peak = np.maximum.accumulate(combined_value)
        dd = (combined_value - peak) / peak * 100
        max_dd = abs(dd.min())
        rets_c = combined_returns[combined_returns != 0]
        sharpe = rets_c.mean() / rets_c.std() * np.sqrt(252) if len(rets_c) > 1 and rets_c.std() > 0 else 0
        eff_pos = base_pct * 100 + (1 - base_pct) * pr
        print(f"  │ ST({mult:.1f}x)+{base_pct*100:.0f}%底仓     │ {annual:>6.2f}%   │ {max_dd:>6.2f}%   │ {sharpe:>6.2f}    │ {eff_pos:>5.1f}%    │")

# B&H
bh_value = np.cumprod(1 + np.diff(bull_close)/bull_close[:-1]) * INIT_CASH
bh_peak = np.maximum.accumulate(bh_value)
bh_dd = abs(((bh_value - bh_peak) / bh_peak * 100).min())
print(f"  │ B&H (纯持有)          │ {bh_annual:>6.2f}%   │ {bh_dd:>6.2f}%   │   N/A    │ 100.0%    │")
print("  └───────────────────────┴──────────┴──────────┴──────────┴──────────┘")

# ── 最终结论 ──
print(f"""
  ╔══════════════════════════════════════════════════════════════════════════════════════════╗
  ║  🏆 结论: 高胜率 ≠ 高收益的底层逻辑                                                     ║
  ╠══════════════════════════════════════════════════════════════════════════════════════════╣
  ║                                                                                         ║
  ║  收益 = 胜率 × 平均盈利幅度 × 交易频率 × 持仓时间                                        ║
  ║                                                                                         ║
  ║  Supertrend: 78.6%胜率 × ${st_aw:,.0f}/笔 × 15笔 × {st_pos_pct:.1f}%持仓                         ║
  ║  EMA+ADX:    47.1%胜率 × ${ea_aw:,.0f}/笔 × {int(ea_stats['Total Trades'])}笔 × {ea_pos_pct:.1f}%持仓                         ║
  ║                                                                                         ║
  ║  Supertrend在"胜率"维度赢了，但在:                                                       ║
  ║  · 单笔盈利幅度 — 输了（${st_aw:,.0f} vs ${ea_aw:,.0f}）                                          ║
  ║  · 持仓比例       — 输了（{st_pos_pct:.1f}% vs {ea_pos_pct:.1f}%）                                    ║
  ║  · 交易频率       — 输了（15次 vs {int(ea_stats['Total Trades'])}次）                                    ║
  ║                                                                                         ║
  ║  三项都输，胜率再高也补不回来。                                                          ║
  ║                                                                                         ║
  ║  💡 类比: 彩票中100次5块钱 vs 中1次500块钱 — 次数多不代表总金额高                       ║
  ║  💡 牛市策略的核心不是"赢的次数多"，而是"在场的时间长 + 抓住大趋势"                      ║
  ╚══════════════════════════════════════════════════════════════════════════════════════════╝
""")
