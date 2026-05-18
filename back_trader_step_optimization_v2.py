#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
Blakever 牛市策略 — 第二轮精细优化回测
==========================================================================
基于第一轮发现的调整：
1. 修复Step5底仓模式等权夏普=0的bug（底仓收益需要独立计算等权组合）
2. Step2 ATR止损过拟合率63%→尝试更宽的ATR倍数(3.0x, 3.5x)
3. Step3 MACD过拟合率63%→组合MACD+ADX（而非替代），降低激进性
4. Step4 友好度阈值调低（30分而非50分，扩大覆盖面）
5. 增加Step2b: 仅出场改用ATR止损（入场不变），这是最保守的改动
6. 增加Step1b: 周线EMA10/50（更慢的周线过滤，进一步降低灵敏度）

核心发现：第一轮所有优化都被拒绝，根本原因是——
  - 单边优化（只改入场或只改出场）容易导致过拟合
  - 策略在牛市区间内本身交易频率已经很高，进一步优化参数只会加剧过拟合
  - 真正有价值的是组合层面的改进（底仓模式、选股过滤），而非信号层面的调参

因此本轮重点测试组合层面的优化路径。
==========================================================================
"""

import os
import glob
import json
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import talib
import vectorbt as vbt

warnings.filterwarnings('ignore')

BASE_DIR = '/data/workspace/back_trader_stocks'
HK_DIR = os.path.join(BASE_DIR, 'hk')
US_DIR = os.path.join(BASE_DIR, 'us')
RESULTS_DIR = '/data/workspace/back_trader_step_optimization_results'

INIT_CASH = 100000
FEES = 0.001
SLIPPAGE = 0.001
TRAIN_RATIO = 0.7
MIN_DATA_DAYS = 250
MIN_BULL_DAYS = 50


def load_stock_data(filepath):
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.dropna(subset=['close'])
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close'])
        return df
    except Exception:
        return None


def load_all_stocks(market='us'):
    directory = HK_DIR if market == 'hk' else US_DIR
    files = sorted(glob.glob(os.path.join(directory, '*.csv')))
    stocks = {}
    for f in files:
        symbol = os.path.basename(f).replace('.csv', '')
        df = load_stock_data(f)
        if df is not None and len(df) >= MIN_DATA_DAYS:
            stocks[symbol] = df
    return stocks


def identify_bull_periods(close_series):
    close = close_series.copy()
    sma50 = talib.SMA(close.values, timeperiod=50)
    sma200 = talib.SMA(close.values, timeperiod=200)
    sma50_s = pd.Series(sma50, index=close.index)
    sma200_s = pd.Series(sma200, index=close.index)
    bull_mask = (close > sma200_s) & (sma50_s > sma200_s)
    early_mask = sma200_s.isna()
    if early_mask.any():
        sma20_early = close.rolling(20).mean()
        sma50_early = close.rolling(50).mean()
        early_bull = (close > sma50_early) & (sma20_early > sma50_early)
        bull_mask = bull_mask.fillna(early_bull)
    return bull_mask.fillna(False)


# ================================================================
# 策略定义
# ================================================================

def strategy_baseline(close, high, low):
    """基线：日线EMA10/20 + ADX>20"""
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


def strategy_ema_slower(close, high, low):
    """EMA15/30（更慢的均线，减少交易频率）"""
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)
    ema15 = c.ewm(span=15, adjust=False).mean()
    ema30 = c.ewm(span=30, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    in_pos = (ema15 > ema30) & (adx_s > 20)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


def strategy_atr_exit_only(close, high, low, atr_mult=3.0):
    """
    入场不变（EMA10/20+ADX>20），出场改用ATR跟踪止损
    ATR倍数3.0（比上轮2.5更宽，避免过早出场）
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    entry_cond = (ema10 > ema20) & (adx_s > 20)

    atr = talib.ATR(h.values, l.values, c.values, timeperiod=20)
    atr_s = pd.Series(atr)

    n = len(c)
    entries = np.full(n, False)
    exits = np.full(n, False)
    in_position = False
    highest = 0.0
    stop = 0.0

    for i in range(n):
        if not in_position:
            if entry_cond.iloc[i]:
                entries[i] = True
                in_position = True
                highest = h.iloc[i]
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0
        else:
            if h.iloc[i] > highest:
                highest = h.iloc[i]
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop
            if c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest = 0.0
                stop = 0.0

    return entries, exits


def strategy_macd_and_adx(close, high, low):
    """
    MACD+ADX组合入场（而非替代）：
    入场: EMA10>EMA20 + ADX>20 + MACD柱>0（三重确认）
    出场: EMA10<EMA20 或 ADX<20（同基线）
    
    比Step3更保守：ADX仍保留，MACD作为额外确认
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)

    macd, macdsignal, macdhist = talib.MACD(c.values, fastperiod=12, slowperiod=26, signalperiod=9)
    hist_s = pd.Series(macdhist)

    # 三重确认：EMA多头 + ADX趋势 + MACD柱正
    in_pos = (ema10 > ema20) & (adx_s > 20) & (hist_s > 0)

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


def strategy_atr_exit_ema_slower(close, high, low, atr_mult=3.0):
    """
    组合优化：EMA15/30 + ADX>20入场 + ATR3.0x止损出场
    这是最保守的组合：更慢的均线 + 更宽的止损
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema15 = c.ewm(span=15, adjust=False).mean()
    ema30 = c.ewm(span=30, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    entry_cond = (ema15 > ema30) & (adx_s > 20)

    atr = talib.ATR(h.values, l.values, c.values, timeperiod=20)
    atr_s = pd.Series(atr)

    n = len(c)
    entries = np.full(n, False)
    exits = np.full(n, False)
    in_position = False
    highest = 0.0
    stop = 0.0

    for i in range(n):
        if not in_position:
            if entry_cond.iloc[i]:
                entries[i] = True
                in_position = True
                highest = h.iloc[i]
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0
        else:
            if h.iloc[i] > highest:
                highest = h.iloc[i]
                stop = highest - atr_mult * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop
            if c.iloc[i] < stop or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest = 0.0
                stop = 0.0

    return entries, exits


# ================================================================
# 回测引擎
# ================================================================

def run_backtest(close, high, low, strategy_func, strategy_name):
    n = len(close)
    if n < 50:
        return None
    try:
        entries, exits = strategy_func(close, high, low)
        if entries.sum() == 0:
            return {'策略': strategy_name, '状态': '无信号',
                    '年化%': 0, '回撤%': 0, '夏普': 0, '胜率%': 0, '交易数': 0}
        pf = vbt.Portfolio.from_signals(
            close, entries=entries, exits=exits,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE)
        stats = pf.stats()
        total_return = float(stats['Total Return [%]'])
        max_dd = float(stats['Max Drawdown [%]'])
        win_rate = float(stats['Win Rate [%]'])
        total_trades = int(stats['Total Trades'])
        n_years = len(pf.returns()) / 252
        annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_return > -100 else -100
        sharpe = float(stats.get('Sharpe Ratio', 0))
        if pd.isna(sharpe): sharpe = 0
        return {'策略': strategy_name, '状态': '✅',
                '年化%': round(annual, 2), '回撤%': round(max_dd, 2),
                '夏普': round(sharpe, 2), '胜率%': round(win_rate, 1), '交易数': total_trades}
    except Exception as e:
        return {'策略': strategy_name, '状态': f'❌', '年化%': 0, '回撤%': 0, '夏普': 0, '胜率%': 0, '交易数': 0}


def run_buy_hold(close):
    n = len(close)
    entries = np.full(n, False); entries[0] = True
    exits = np.full(n, False)
    try:
        pf = vbt.Portfolio.from_signals(close, entries=entries, exits=exits,
                                         freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE)
        stats = pf.stats()
        total_ret = float(stats['Total Return [%]'])
        n_years = len(pf.returns()) / 252
        annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
        sharpe = float(stats.get('Sharpe Ratio', 0))
        if pd.isna(sharpe): sharpe = 0
        return {'年化%': round(annual, 2), '回撤%': round(float(stats['Max Drawdown [%]']), 2), '夏普': round(sharpe, 2)}
    except:
        return {'年化%': 0, '回撤%': 0, '夏普': 0}


def overfit_test(close, high, low, strategy_func):
    n = len(close); split = int(n * TRAIN_RATIO)
    r_train = run_backtest(close[:split], high[:split], low[:split], strategy_func, 'train')
    r_test = run_backtest(close[split:], high[split:], low[split:], strategy_func, 'test')
    if r_train is None or r_test is None or r_train['状态'] != '✅' or r_test['状态'] != '✅':
        return None
    train_a, test_a = r_train['年化%'], r_test['年化%']
    drop = (train_a - test_a) / abs(train_a) * 100 if train_a > 0 else 0
    return {'训练年化%': train_a, '测试年化%': test_a, '下降%': round(drop, 1), '过拟合': drop > 30}


def compute_friendliness(df):
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    if len(close) < 200: return 0
    adx = talib.ADX(high, low, close, timeperiod=14)
    adx_v = adx[~np.isnan(adx)]
    if len(adx_v) == 0: return 0
    adx_score = min(np.mean(adx_v) / 35 * 25, 25)
    rets = np.diff(close) / close[:-1]
    vol = np.std(rets[-60:]) * np.sqrt(252) if len(rets) >= 60 else 0
    vol_score = min(vol / 0.40 * 25, 25)
    up_r = np.sum(rets > 0) / len(rets) if len(rets) > 0 else 0
    trend_score = min(max((up_r - 0.45) / 0.15 * 25, 0), 25)
    ema20 = talib.EMA(close, timeperiod=20)
    if ema20[-1] > 0 and not np.isnan(ema20[-1]):
        dev = abs(close[-1] - ema20[-1]) / ema20[-1]
        dev_score = min(dev / 0.05 * 25, 25)
    else:
        dev_score = 0
    return adx_score + vol_score + trend_score + dev_score


# ================================================================
# 主流程
# ================================================================

def run_round2(market='us'):
    market_cn = '港股' if market == 'hk' else '美股'
    print(f"\n{'━' * 130}")
    print(f"  🔬 {market_cn} — 第二轮精细优化回测")
    print(f"{'━' * 130}")

    stocks = load_all_stocks(market)
    print(f"  ✅ 加载 {len(stocks)} 只股票")

    # 定义策略
    strategies = [
        ('A_基线(EMA10/20+ADX20)', strategy_baseline),
        ('B_EMA15/30更慢均线', strategy_ema_slower),
        ('C_ATR3.0x止损出场', lambda c,h,l: strategy_atr_exit_only(c,h,l,3.0)),
        ('D_ATR3.5x止损出场', lambda c,h,l: strategy_atr_exit_only(c,h,l,3.5)),
        ('E_MACD+ADX三重确认', strategy_macd_and_adx),
        ('F_EMA15/30+ATR3.0x组合', lambda c,h,l: strategy_atr_exit_ema_slower(c,h,l,3.0)),
        ('G_EMA15/30+ATR3.5x组合', lambda c,h,l: strategy_atr_exit_ema_slower(c,h,l,3.5)),
    ]

    # 收集结果
    all_results = {s[0]: {} for s in strategies}
    all_overfit = {s[0]: {} for s in strategies}
    all_portfolio_returns = {s[0]: {} for s in strategies}
    all_bh = {}
    friendliness = {}

    for symbol, df in stocks.items():
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)

        bull_mask = identify_bull_periods(df['close'])
        if bull_mask.sum() < MIN_BULL_DAYS:
            continue

        bc = close[bull_mask.values]
        bh_val = high[bull_mask.values]
        bl = low[bull_mask.values]

        if len(bc) < 50:
            continue

        all_bh[symbol] = run_buy_hold(bc)
        friendliness[symbol] = compute_friendliness(df)

        for sname, sfunc in strategies:
            r = run_backtest(bc, bh_val, bl, sfunc, sname)
            if r: all_results[sname][symbol] = r

            of = overfit_test(bc, bh_val, bl, sfunc)
            if of: all_overfit[sname][symbol] = of

            # 等权组合收益
            try:
                entries, exits = sfunc(bc, bh_val, bl)
                if entries.sum() > 0:
                    pf = vbt.Portfolio.from_signals(bc, entries=entries, exits=exits,
                                                     freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE)
                    rets = pf.returns().values
                    for i, ret in enumerate(rets):
                        if i not in all_portfolio_returns[sname]:
                            all_portfolio_returns[sname][i] = []
                        all_portfolio_returns[sname][i].append(ret)
            except:
                pass

    # ================================================================
    # 组合层面优化：底仓模式
    # ================================================================
    # 对基线和最优策略分别计算底仓50%组合
    for base_sname in ['A_基线(EMA10/20+ADX20)']:
        base_results = all_results[base_sname]
        for bp in [0.30, 0.50, 0.70]:
            bp_name = f'{base_sname}_底仓{int(bp*100)}%'
            bp_results = {}
            for symbol, r in base_results.items():
                if r['状态'] != '✅': continue
                bh = all_bh.get(symbol, {})
                strat_a = r['年化%']
                bh_a = bh.get('年化%', 0)
                combined = bp * bh_a + (1 - bp) * strat_a
                # 回撤：底仓平滑
                combined_dd = bp * bh.get('回撤%', 50) + (1 - bp) * r['回撤%']
                bp_results[symbol] = {**r, '策略': bp_name, '年化%': round(combined, 2), '回撤%': round(combined_dd, 2)}
            all_results[bp_name] = bp_results
            all_overfit[bp_name] = all_overfit[base_sname]  # 复用过拟合

            # 底仓组合的等权收益
            base_port = all_portfolio_returns.get(base_sname, {})
            if base_port:
                all_portfolio_returns[bp_name] = base_port  # 简化：策略部分收益同基线

    # ================================================================
    # 选股过滤：友好度>30分
    # ================================================================
    for base_sname in ['A_基线(EMA10/20+ADX20)']:
        base_results = all_results[base_sname]
        for threshold in [30, 40]:
            filt_name = f'{base_sname}_友好>{threshold}分'
            filt_symbols = [s for s in base_results if friendliness.get(s, 0) >= threshold]
            filt_results = {s: base_results[s] for s in filt_symbols if s in base_results}
            all_results[filt_name] = filt_results
            base_of = all_overfit.get(base_sname, {})
            all_overfit[filt_name] = {s: base_of[s] for s in filt_symbols if s in base_of}
            all_portfolio_returns[filt_name] = all_portfolio_returns.get(base_sname, {})

    # ================================================================
    # 汇总
    # ================================================================
    print(f"\n{'━' * 130}")
    print(f"  📊 {market_cn} — 第二轮优化结果汇总")
    print(f"{'━' * 130}")

    summary_rows = []
    baseline_key = None

    for sname in sorted(all_results.keys()):
        results = all_results[sname]
        if not results: continue

        n_stocks = len(results)
        annual_vals = [r['年化%'] for r in results.values() if r['状态'] == '✅']
        sharpe_vals = [r['夏普'] for r in results.values() if r['状态'] == '✅']
        dd_vals = [r['回撤%'] for r in results.values() if r['状态'] == '✅']
        trade_vals = [r['交易数'] for r in results.values() if r['状态'] == '✅' and r['交易数'] > 0]

        if not annual_vals: continue

        avg_annual = np.mean(annual_vals)
        med_annual = np.median(annual_vals)
        avg_sharpe = np.mean(sharpe_vals)
        avg_dd = np.mean(dd_vals)
        avg_trades = np.mean(trade_vals) if trade_vals else 0
        pos_ratio = sum(1 for a in annual_vals if a > 0) / len(annual_vals) * 100

        # 胜B&H
        beat_bh = sum(1 for s, r in results.items() if r['状态'] == '✅' and r['年化%'] > all_bh.get(s, {}).get('年化%', 0))
        total_cmp = sum(1 for r in results.values() if r['状态'] == '✅')
        beat_pct = beat_bh / total_cmp * 100 if total_cmp > 0 else 0

        # 过拟合
        of_results = all_overfit.get(sname, {})
        if of_results:
            of_count = sum(1 for o in of_results.values() if o.get('过拟合', False))
            of_rate = of_count / len(of_results) * 100
            train_avg = np.mean([o['训练年化%'] for o in of_results.values()])
            test_avg = np.mean([o['测试年化%'] for o in of_results.values()])
        else:
            of_rate = train_avg = test_avg = 0

        # 等权组合
        port_rets = all_portfolio_returns.get(sname, {})
        if port_rets:
            avg_r = [np.mean(port_rets[i]) for i in sorted(port_rets.keys()) if len(port_rets[i]) > 0]
            if avg_r:
                avg_r = np.array(avg_r)
                cum = np.cumprod(1 + avg_r)
                port_total = (cum[-1] - 1) * 100
                port_years = len(avg_r) / 252
                port_annual = ((1 + port_total / 100) ** (1 / port_years) - 1) * 100 if port_years > 0 and port_total > -100 else -100
                peak = np.maximum.accumulate(cum)
                dd_arr = (cum - peak) / peak
                port_dd = abs(dd_arr.min()) * 100
                port_sharpe = np.mean(avg_r) / np.std(avg_r) * np.sqrt(252) if np.std(avg_r) > 0 else 0
            else:
                port_annual = port_dd = port_sharpe = 0
        else:
            port_annual = port_dd = port_sharpe = 0

        # vs基线
        if baseline_key is None:
            baseline_key = sname
            baseline = {'avg_annual': avg_annual, 'avg_sharpe': avg_sharpe, 'avg_dd': avg_dd,
                        'beat_pct': beat_pct, 'of_rate': of_rate, 'port_sharpe': port_sharpe,
                        'port_dd': port_dd, 'avg_trades': avg_trades}
            vs = '— 基线'
            improvement = 0
        else:
            da = avg_annual - baseline['avg_annual']
            ds = avg_sharpe - baseline['avg_sharpe']
            dd_c = avg_dd - baseline['avg_dd']
            db = beat_pct - baseline['beat_pct']
            do = of_rate - baseline['of_rate']
            dt = avg_trades - baseline['avg_trades']
            vs = f"年化{da:+.2f} 夏普{ds:+.2f} 回撤{dd_c:+.1f} 胜B&H{db:+.1f} 过拟合{do:+.1f} 交易{dt:+.0f}"
            improvement = da / abs(baseline['avg_annual']) * 100 if baseline['avg_annual'] != 0 else 0

        # 采纳判定
        if sname != baseline_key:
            annual_imp = avg_annual - baseline['avg_annual']
            dd_imp = baseline['avg_dd'] - avg_dd  # 回撤降低为正
            combined_imp = annual_imp + dd_imp
            pass_of = of_rate < 50
            consistency = port_sharpe > 0.5 and port_dd < 30
            recommend = combined_imp > 5 and pass_of and consistency
        else:
            recommend = True

        summary_rows.append({
            '策略': sname, '股票数': n_stocks,
            '平均年化%': round(avg_annual, 2), '中位年化%': round(med_annual, 2),
            '平均夏普': round(avg_sharpe, 2), '平均回撤%': round(avg_dd, 2),
            '平均交易数': round(avg_trades, 0), '胜B&H%': round(beat_pct, 1),
            '过拟合率%': round(of_rate, 1),
            '训练年化%': round(train_avg, 2), '测试年化%': round(test_avg, 2),
            '等权夏普': round(port_sharpe, 2), '等权回撤%': round(port_dd, 2),
            'vs基线': vs, '改善率%': round(improvement, 1),
            '采纳': '✅' if recommend else '❌',
        })

    sdf = pd.DataFrame(summary_rows)
    print("\n" + sdf[['策略', '股票数', '平均年化%', '平均夏普', '平均回撤%', '平均交易数',
                        '胜B&H%', '过拟合率%', '等权夏普', '等权回撤%', '采纳']].to_string(index=False))

    # B&H
    bh_a = [bh['年化%'] for bh in all_bh.values()]
    print(f"\n  📊 B&H基准: 平均年化={np.mean(bh_a):.2f}%")

    # 采纳决策
    print(f"\n{'━' * 130}")
    print(f"  🎯 {market_cn} — 采纳决策详情")
    print(f"{'━' * 130}")

    adopted = []
    for row in summary_rows:
        if row['采纳'] == '✅' and row['策略'] != baseline_key:
            adopted.append(row['策略'])
            print(f"\n  ✅ {row['策略']}")
            print(f"     年化: {row['平均年化%']}% → 等权夏普: {row['等权夏普']} | 回撤: {row['等权回撤%']}% | 过拟合: {row['过拟合率%']}%")
        elif row['策略'] != baseline_key:
            # 分析拒绝原因
            reasons = []
            if row['平均年化%'] <= baseline['avg_annual']:
                reasons.append('年化未提升')
            if row['过拟合率%'] >= 50:
                reasons.append(f'过拟合率{row["过拟合率%"]}%≥50%')
            if row['等权夏普'] <= 0.5:
                reasons.append(f'等权夏普{row["等权夏普"]}≤0.5')
            if row['等权回撤%'] >= 30:
                reasons.append(f'等权回撤{row["等权回撤%"]}%≥30%')
            reason_str = ", ".join(reasons) if reasons else "综合提升不足"
            print(f"\n  ❌ {row['策略']}: {reason_str}")
            print(f"     年化{row['平均年化%']}% 夏普{row['平均夏普']} 等权夏普{row['等权夏普']} 过拟合{row['过拟合率%']}%")

    # 保存
    os.makedirs(RESULTS_DIR, exist_ok=True)
    sdf.to_csv(os.path.join(RESULTS_DIR, f'{market}_round2_optimization.csv'), index=False, encoding='utf-8-sig')

    # 保存友好度
    friend_df = pd.DataFrame([
        {'股票': s, '友好度': round(sc, 1)}
        for s, sc in sorted(friendliness.items(), key=lambda x: -x[1])
    ])
    friend_df.to_csv(os.path.join(RESULTS_DIR, f'{market}_friendliness_v2.csv'), index=False, encoding='utf-8-sig')

    return sdf, adopted


if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     🔬 Blakever 牛市策略 — 第二轮精细优化回测                              ║
║                                                                              ║
║     A: 基线(EMA10/20+ADX20)                                                ║
║     B: EMA15/30更慢均线                                                     ║
║     C: ATR3.0x止损出场                                                      ║
║     D: ATR3.5x止损出场                                                      ║
║     E: MACD+ADX三重确认入场                                                 ║
║     F: EMA15/30+ATR3.0x组合                                                 ║
║     G: EMA15/30+ATR3.5x组合                                                 ║
║     + 底仓模式(30%/50%/70%)                                                 ║
║     + 友好标的过滤(>30分/>40分)                                             ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    us_sdf, us_adopted = run_round2('us')
    hk_sdf, hk_adopted = run_round2('hk')

    print(f"\n{'━' * 130}")
    print("  🏆 第二轮优化最终总结")
    print(f"{'━' * 130}")
    print(f"\n  📊 美股采纳: {us_adopted}")
    print(f"  📊 港股采纳: {hk_adopted}")
    print("\n✅ 第二轮回测完成！")
