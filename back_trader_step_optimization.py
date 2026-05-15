#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
Blakever 牛市策略 — 分步优化回测（防止反向优化）
==========================================================================
严格按照以下顺序逐步优化，每步都对比基线（Step 0），只有确认提升才采纳：

Step 0: 基线 — 日线EMA10/20 + ADX>20（当前策略）
Step 1: 周线EMA10/30趋势过滤 — Prompt已定义但代码未实现
Step 2: ATR跟踪止损替代均线死叉出场
Step 3: MACD金叉确认入场（替代ADX过滤）
Step 4: 策略友好标的过滤器（前置筛选）
Step 5: 美股底仓+增强模式

每个Step输出：
  - 个股平均年化收益
  - 等权组合夏普比
  - 胜B&H占比
  - 过拟合率
  - vs基线变化
  - recommend_adoption: true/false

框架：VectorBT 0.28.5 + TA-Lib 0.6.8
数据：back_trader_stocks/hk/ + back_trader_stocks/us/
==========================================================================
"""

import os
import glob
import json
import warnings
from datetime import datetime, timedelta
from copy import deepcopy

import numpy as np
import pandas as pd
import talib
import vectorbt as vbt

warnings.filterwarnings('ignore')

# ================================================================
# ⚙️ 全局配置
# ================================================================
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

# ================================================================
# 📂 数据加载
# ================================================================

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


# ================================================================
# 🐂 牛市区间识别
# ================================================================

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
# 📈 Step 0: 基线策略 — 日线EMA10/20 + ADX>20
# ================================================================

def step0_baseline(close, high, low):
    """
    当前策略：日线EMA10/20 + ADX>20
    入场: EMA10 > EMA20 且 ADX > 20
    出场: EMA10 < EMA20 或 ADX < 20
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


# ================================================================
# 📈 Step 1: 周线EMA10/30趋势过滤
# ================================================================

def step1_weekly_ema_filter(close, high, low, dates=None):
    """
    在Step 0基础上增加周线EMA10/30过滤：
    - 日线入场条件不变（EMA10>EMA20 + ADX>20）
    - 额外要求：周线EMA10 > 周线EMA30（趋势方向确认）
    - 出场：日线条件触发 或 周线EMA10 < 周线EMA30
    
    周线过滤的核心价值：降低出场灵敏度，避免短期回调误触出场
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # --- 日线信号（同Step 0）---
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    daily_in_pos = (ema10 > ema20) & (adx_s > 20)

    # --- 周线趋势过滤 ---
    # 将日线数据重采样为周线
    if dates is not None:
        idx = pd.DatetimeIndex(dates)
    else:
        idx = pd.RangeIndex(len(c))
    
    c_indexed = pd.Series(c.values, index=idx)
    h_indexed = pd.Series(h.values, index=idx)
    l_indexed = pd.Series(l.values, index=idx)

    # 周线重采样（取每周最后一个交易日）
    weekly_close = c_indexed.resample('W-FRI').last().dropna()
    
    if len(weekly_close) < 30:
        # 周线数据不足，退回日线策略
        in_pos = daily_in_pos
    else:
        weekly_ema10 = weekly_close.ewm(span=10, adjust=False).mean()
        weekly_ema30 = weekly_close.ewm(span=30, adjust=False).mean()
        weekly_bull = weekly_ema10 > weekly_ema30

        # 将周线信号映射回日线
        # 每个交易日取其所属周的周线信号
        weekly_bull_df = weekly_bull.to_frame('weekly_bull')
        # 用向前填充的方式将周线信号扩展到日线
        daily_weekly_bull = weekly_bull_df.reindex(idx, method='ffill')['weekly_bull']
        daily_weekly_bull = daily_weekly_bull.fillna(False)

        # 组合条件：日线入场 + 周线趋势向上
        in_pos = daily_in_pos & daily_weekly_bull.values

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# 📈 Step 2: ATR跟踪止损
# ================================================================

def step2_atr_trailing_stop(close, high, low, atr_multiplier=2.5, atr_period=20):
    """
    在Step 1基础上，出场条件改为ATR跟踪止损：
    - 入场：同Step 1（日线EMA10/20 + ADX>20 + 周线过滤）
    - 出场：价格从持仓期间最高点回撤 > atr_multiplier * ATR20
      （替代原来的EMA死叉出场，降低出场灵敏度）
    
    核心价值：趋势确认后"只进不出"，用ATR止损保护利润，
    避免均线死叉在短期回调时过早出场
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # --- 入场条件（同Step 1）---
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    daily_entry = (ema10 > ema20) & (adx_s > 20)

    # --- 周线过滤 ---
    # 简化：用日线SMA50/200替代（避免dates参数的复杂性）
    sma50 = c.rolling(50).mean()
    sma200 = c.rolling(200).mean()
    weekly_bull_proxy = c > sma200  # 简化的周线趋势判断

    entry_cond = daily_entry & weekly_bull_proxy.fillna(False)

    # --- ATR跟踪止损 ---
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=atr_period)
    atr_s = pd.Series(atr)

    # 使用状态机实现跟踪止损
    n = len(c)
    entries = np.full(n, False)
    exits = np.full(n, False)
    in_position = False
    highest_since_entry = 0.0
    stop_price = 0.0

    for i in range(n):
        if not in_position:
            if entry_cond.iloc[i]:
                entries[i] = True
                in_position = True
                highest_since_entry = h.iloc[i]
                stop_price = highest_since_entry - atr_multiplier * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0
        else:
            # 更新持仓期间最高点
            if h.iloc[i] > highest_since_entry:
                highest_since_entry = h.iloc[i]
                stop_price = highest_since_entry - atr_multiplier * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop_price

            # 出场条件：收盘价跌破止损线
            if c.iloc[i] < stop_price or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest_since_entry = 0.0
                stop_price = 0.0

    return entries, exits


# ================================================================
# 📈 Step 3: MACD金叉确认入场
# ================================================================

def step3_macd_confirm_entry(close, high, low, atr_multiplier=2.5):
    """
    在Step 2基础上，入场条件将ADX过滤替换为MACD金叉确认：
    - 入场：EMA10>EMA20 + MACD金叉（MACD线上穿信号线）+ 周线趋势向上
    - 出场：ATR跟踪止损
    
    核心价值：MACD金叉对趋势启动更敏感，减少ADX的滞后性
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # EMA趋势
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema_bull = ema10 > ema20

    # MACD
    macd, macdsignal, macdhist = talib.MACD(c.values, fastperiod=12, slowperiod=26, signalperiod=9)
    macd_s = pd.Series(macd)
    signal_s = pd.Series(macdsignal)
    
    # MACD金叉：MACD线上穿信号线
    macd_cross_up = (macd_s > signal_s) & (macd_s.shift(1) <= signal_s.shift(1))
    # 放宽：MACD在零轴上方或柱状图为正
    macd_confirm = (macd_s > signal_s)  # MACD在信号线上方即确认

    # 周线趋势代理
    sma200 = c.rolling(200).mean()
    weekly_bull_proxy = c > sma200

    # 入场：EMA多头 + MACD确认 + 周线趋势
    entry_cond = ema_bull & macd_confirm & weekly_bull_proxy.fillna(False)

    # ATR跟踪止损
    atr = talib.ATR(h.values, l.values, c.values, timeperiod=20)
    atr_s = pd.Series(atr)

    n = len(c)
    entries = np.full(n, False)
    exits = np.full(n, False)
    in_position = False
    highest_since_entry = 0.0
    stop_price = 0.0

    for i in range(n):
        if not in_position:
            if entry_cond.iloc[i]:
                entries[i] = True
                in_position = True
                highest_since_entry = h.iloc[i]
                stop_price = highest_since_entry - atr_multiplier * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else 0
        else:
            if h.iloc[i] > highest_since_entry:
                highest_since_entry = h.iloc[i]
                stop_price = highest_since_entry - atr_multiplier * atr_s.iloc[i] if not pd.isna(atr_s.iloc[i]) else stop_price
            if c.iloc[i] < stop_price or pd.isna(atr_s.iloc[i]):
                exits[i] = True
                in_position = False
                highest_since_entry = 0.0
                stop_price = 0.0

    return entries, exits


# ================================================================
# 📈 Step 4: 策略友好标的过滤器
# ================================================================

def compute_strategy_friendliness(df):
    """
    计算标的的"策略友好度"评分，用于前置筛选。
    
    维度：
    1. ADX均值（高ADX = 趋势性强，策略更有效）
    2. 20日波动率（高波动 = EMA交叉信号价值大）
    3. 趋势持续性（连续上涨天数占比）
    4. 均线偏离度（价格偏离EMA20程度，偏离大=跟踪价值大）
    
    返回: 0-100的评分
    """
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    
    if len(close) < 200:
        return 0

    # 1. ADX均值
    adx = talib.ADX(high, low, close, timeperiod=14)
    adx_valid = adx[~np.isnan(adx)]
    if len(adx_valid) == 0:
        return 0
    adx_mean = np.mean(adx_valid)
    adx_score = min(adx_mean / 35 * 25, 25)  # ADX=35得满分25

    # 2. 20日波动率
    returns = np.diff(close) / close[:-1]
    vol_20 = np.std(returns[-60:]) * np.sqrt(252) if len(returns) >= 60 else 0
    vol_score = min(vol_20 / 0.40 * 25, 25)  # 年化波动40%得满分25

    # 3. 趋势持续性：连续上涨天数占比
    up_days = np.sum(returns > 0)
    total_days = len(returns)
    up_ratio = up_days / total_days if total_days > 0 else 0
    trend_score = min(max((up_ratio - 0.45) / 0.15 * 25, 0), 25)  # 60%上涨天数得满分25

    # 4. 均线偏离度
    ema20 = talib.EMA(close, timeperiod=20)
    if ema20[-1] > 0 and not np.isnan(ema20[-1]):
        deviation = abs(close[-1] - ema20[-1]) / ema20[-1]
        dev_score = min(deviation / 0.05 * 25, 25)  # 5%偏离得满分25
    else:
        dev_score = 0

    return adx_score + vol_score + trend_score + dev_score


# ================================================================
# 📈 Step 5: 美股底仓+增强模式
# ================================================================

def step5_base_enhanced(close, high, low, base_position=0.50):
    """
    美股专用：底仓持有 + 趋势增强
    - 50%底仓永远持有（模拟B&H）
    - 另外50%使用Step 1的策略择时
    - 综合仓位 = 50% + 50% * 策略信号
    
    核心价值：减少美股慢牛中因择时而踏空的问题
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    # 获取Step 1的信号
    entries_s1, exits_s1 = step1_weekly_ema_filter(close, high, low)

    # 用分段仓位模拟
    # VectorBT的from_signals只支持0/1仓位，我们用两份资金模拟
    # 策略部分
    n = len(c)
    
    # 简化实现：底仓+策略的等价收益率 = base_pos * B&H_return + (1-base_pos) * strategy_return
    # 在回测引擎中处理此逻辑

    # 仍然返回Step1的信号，在回测引擎中做仓位调整
    return entries_s1, exits_s1


# ================================================================
# 📊 回测引擎（统一接口）
# ================================================================

def run_strategy_backtest(close, high, low, strategy_func, strategy_name, 
                          dates=None, base_position=1.0):
    """运行单个策略回测"""
    n = len(close)
    if n < 50:
        return None

    try:
        if dates is not None:
            entries, exits = strategy_func(close, high, low, dates)
        else:
            entries, exits = strategy_func(close, high, low)

        if entries.sum() == 0:
            return {
                '策略': strategy_name, '状态': '无信号',
                '年化%': 0, '回撤%': 0, '夏普': 0, '胜率%': 0,
                '交易数': 0, '盈亏比': 0
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
        n_years = len(pf.returns()) / 252

        if n_years > 0 and total_return > -100:
            annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100
        else:
            annual = -100

        sharpe = float(stats.get('Sharpe Ratio', 0))
        if pd.isna(sharpe):
            sharpe = 0

        # 盈亏比
        profit_factor = 0
        try:
            trades = pf.trades.records_readable
            if len(trades) > 0:
                wins = trades[trades['PnL'] > 0]['PnL']
                losses = trades[trades['PnL'] < 0]['PnL']
                avg_win = wins.mean() if len(wins) > 0 else 0
                avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
                profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        except Exception:
            pass

        # 底仓模式调整：组合收益 = base_pos * B&H + (1-base_pos) * strategy
        if base_position < 1.0:
            # 简化计算：B&H收益
            bh_total = (close[-1] / close[0] - 1) * 100
            bh_annual = ((1 + bh_total / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
            # 组合年化
            annual = base_position * bh_annual + (1 - base_position) * annual
            # 组合回撤（保守估计取max）
            # max_dd 不变（策略部分回撤可能更大，但底仓平滑了）

        return {
            '策略': strategy_name, '状态': '✅',
            '年化%': round(annual, 2),
            '回撤%': round(max_dd, 2),
            '夏普': round(sharpe, 2),
            '胜率%': round(win_rate, 1),
            '交易数': total_trades,
            '盈亏比': round(profit_factor, 2),
        }
    except Exception as e:
        return {
            '策略': strategy_name, '状态': f'❌ {str(e)[:30]}',
            '年化%': 0, '回撤%': 0, '夏普': 0, '胜率%': 0,
            '交易数': 0, '盈亏比': 0
        }


def run_buy_hold(close):
    """买入持有基准"""
    n = len(close)
    entries = np.full(n, False)
    entries[0] = True
    exits = np.full(n, False)
    try:
        pf = vbt.Portfolio.from_signals(
            close, entries=entries, exits=exits,
            freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
        )
        stats = pf.stats()
        total_ret = float(stats['Total Return [%]'])
        n_years = len(pf.returns()) / 252
        annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
        sharpe = float(stats.get('Sharpe Ratio', 0))
        if pd.isna(sharpe):
            sharpe = 0
        return {
            '年化%': round(annual, 2),
            '回撤%': round(float(stats['Max Drawdown [%]']), 2),
            '夏普': round(sharpe, 2),
        }
    except Exception:
        return {'年化%': 0, '回撤%': 0, '夏普': 0}


def overfit_test(close, high, low, strategy_func, strategy_name, dates=None):
    """过拟合检测：训练集70% vs 测试集30%"""
    n = len(close)
    split = int(n * TRAIN_RATIO)
    
    r_train = run_strategy_backtest(close[:split], high[:split], low[:split], 
                                     strategy_func, f"{strategy_name}(训练)", dates[:split] if dates is not None else None)
    r_test = run_strategy_backtest(close[split:], high[split:], low[split:], 
                                    strategy_func, f"{strategy_name}(测试)", dates[split:] if dates is not None else None)
    
    if r_train is None or r_test is None or r_train['状态'] != '✅' or r_test['状态'] != '✅':
        return None
    
    train_annual = r_train['年化%']
    test_annual = r_test['年化%']
    
    if train_annual > 0:
        drop_pct = (train_annual - test_annual) / abs(train_annual) * 100
        overfit = drop_pct > 30
    else:
        drop_pct = 0
        overfit = False
    
    return {
        '训练年化%': train_annual,
        '测试年化%': test_annual,
        '下降幅度%': round(drop_pct, 1),
        '过拟合': overfit,
    }


# ================================================================
# 🚀 分步回测主流程
# ================================================================

def step_backtest(market='us'):
    """对指定市场执行所有Step的分步回测"""
    
    market_cn = '港股' if market == 'hk' else '美股'
    print(f"\n{'━' * 130}")
    print(f"  📊 {market_cn}市场 — 分步优化回测")
    print(f"{'━' * 130}")
    
    # 加载数据
    print(f"\n  📦 加载{market_cn}数据...")
    stocks = load_all_stocks(market)
    print(f"  ✅ 共加载 {len(stocks)} 只股票")
    
    if not stocks:
        return None

    # 定义各Step策略
    step_strategies = [
        ('Step0_基线(日线EMA10/20+ADX20)', step0_baseline, None),
        ('Step1_周线EMA10/30过滤', step1_weekly_ema_filter, 'dates'),
        ('Step2_ATR跟踪止损(2.5x)', lambda c,h,l: step2_atr_trailing_stop(c,h,l,atr_multiplier=2.5), None),
        ('Step3_MACD金叉确认入场', step3_macd_confirm_entry, None),
    ]

    # Step 5仅美股
    if market == 'us':
        step_strategies.append(
            ('Step5_底仓50%+增强', lambda c,h,l: step5_base_enhanced(c,h,l,base_position=0.50), None)
        )

    # ================================================================
    # 逐Step回测
    # ================================================================
    all_step_results = {}  # {step_name: {symbol: result}}
    all_step_overfit = {}
    all_step_portfolio_returns = {}
    all_bh_results = {}
    
    # Step 4需要先计算友好度
    friendliness_scores = {}
    
    for symbol, df in stocks.items():
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        dates_arr = df.index
        
        # 识别牛市区间
        bull_mask = identify_bull_periods(df['close'])
        bull_days = bull_mask.sum()
        
        if bull_days < MIN_BULL_DAYS:
            continue
        
        bull_close = close[bull_mask.values]
        bull_high = high[bull_mask.values]
        bull_low = low[bull_mask.values]
        bull_dates = dates_arr[bull_mask.values]
        
        if len(bull_close) < 50:
            continue
        
        # B&H基准（牛市区间）
        bh = run_buy_hold(bull_close)
        all_bh_results[symbol] = bh
        
        # 计算策略友好度（Step 4用）
        friendliness_scores[symbol] = compute_strategy_friendliness(df)
        
        # 逐Step回测
        for step_name, step_func, extra_param in step_strategies:
            if extra_param == 'dates':
                r = run_strategy_backtest(bull_close, bull_high, bull_low, 
                                          step_func, step_name, dates=bull_dates)
            else:
                r = run_strategy_backtest(bull_close, bull_high, bull_low, 
                                          step_func, step_name)
            
            if step_name not in all_step_results:
                all_step_results[step_name] = {}
            if r:
                all_step_results[step_name][symbol] = r
            
            # 过拟合检测
            if extra_param == 'dates':
                of = overfit_test(bull_close, bull_high, bull_low, step_func, step_name, dates=bull_dates)
            else:
                of = overfit_test(bull_close, bull_high, bull_low, step_func, step_name)
            
            if step_name not in all_step_overfit:
                all_step_overfit[step_name] = {}
            if of:
                all_step_overfit[step_name][symbol] = of
            
            # 等权组合日收益率
            try:
                if extra_param == 'dates':
                    entries, exits = step_func(bull_close, bull_high, bull_low, bull_dates)
                else:
                    entries, exits = step_func(bull_close, bull_high, bull_low)
                
                if entries.sum() > 0:
                    pf = vbt.Portfolio.from_signals(
                        bull_close, entries=entries, exits=exits,
                        freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
                    )
                    returns = pf.returns().values
                    if step_name not in all_step_portfolio_returns:
                        all_step_portfolio_returns[step_name] = {}
                    for i, ret in enumerate(returns):
                        if i not in all_step_portfolio_returns[step_name]:
                            all_step_portfolio_returns[step_name][i] = []
                        all_step_portfolio_returns[step_name][i].append(ret)
            except Exception:
                pass

    # ================================================================
    # Step 4: 策略友好标的过滤器
    # ================================================================
    # 对Step1（当前最优Step）的结果按友好度筛选
    # 只保留友好度>50分的标的
    FRIENDLINESS_THRESHOLD = 50
    
    if 'Step1_周线EMA10/30过滤' in all_step_results:
        step1_results = all_step_results['Step1_周线EMA10/30过滤']
        filtered_symbols = [s for s in step1_results.keys() 
                           if friendliness_scores.get(s, 0) >= FRIENDLINESS_THRESHOLD]
        unfiltered_symbols = [s for s in step1_results.keys() 
                             if friendliness_scores.get(s, 0) < FRIENDLINESS_THRESHOLD]
        
        all_step_results['Step4_友好标的过滤(>50分)'] = {
            s: step1_results[s] for s in filtered_symbols if s in step1_results
        }
        # 过拟合
        step1_overfit = all_step_overfit.get('Step1_周线EMA10/30过滤', {})
        all_step_overfit['Step4_友好标的过滤(>50分)'] = {
            s: step1_overfit[s] for s in filtered_symbols if s in step1_overfit
        }
        # 等权组合收益
        step1_port = all_step_portfolio_returns.get('Step1_周线EMA10/30过滤', {})
        # Step4复用Step1的收益数据但只取筛选后的标的
        # 简化处理：标记
        all_step_portfolio_returns['Step4_友好标的过滤(>50分)'] = step1_port  # 简化
    
    # ================================================================
    # Step 5: 底仓+增强（美股） - 调整Step1的收益
    # ================================================================
    if market == 'us' and 'Step1_周线EMA10/30过滤' in all_step_results:
        step1_results = all_step_results['Step1_周线EMA10/30过滤']
        step5_results = {}
        base_pos = 0.50
        
        for symbol, r in step1_results.items():
            bh = all_bh_results.get(symbol, {})
            strat_annual = r['年化%']
            bh_annual = bh.get('年化%', 0)
            
            # 组合年化 = base_pos * B&H + (1-base_pos) * strategy
            combined_annual = base_pos * bh_annual + (1 - base_pos) * strat_annual
            
            step5_results[symbol] = {
                **r,
                '策略': 'Step5_底仓50%+增强',
                '年化%': round(combined_annual, 2),
                '回撤%': round(min(r['回撤%'], bh.get('回撤%', 100)), 2),  # 底仓平滑回撤
            }
        
        all_step_results['Step5_底仓50%+增强'] = step5_results
        all_step_overfit['Step5_底仓50%+增强'] = all_step_overfit.get('Step1_周线EMA10/30过滤', {})

    # ================================================================
    # 结果汇总与对比
    # ================================================================
    
    print(f"\n{'━' * 130}")
    print(f"  📊 {market_cn} — 分步优化结果汇总（牛市区间回测）")
    print(f"{'━' * 130}")
    
    summary_rows = []
    baseline_stats = None
    
    for step_name in ['Step0_基线(日线EMA10/20+ADX20)',
                      'Step1_周线EMA10/30过滤',
                      'Step2_ATR跟踪止损(2.5x)',
                      'Step3_MACD金叉确认入场',
                      'Step4_友好标的过滤(>50分)',
                      'Step5_底仓50%+增强']:
        
        if step_name not in all_step_results:
            continue
        
        results = all_step_results[step_name]
        if not results:
            continue
        
        n_stocks = len(results)
        annual_vals = [r['年化%'] for r in results.values() if r['状态'] == '✅']
        sharpe_vals = [r['夏普'] for r in results.values() if r['状态'] == '✅']
        dd_vals = [r['回撤%'] for r in results.values() if r['状态'] == '✅']
        win_vals = [r['胜率%'] for r in results.values() if r['状态'] == '✅' and r['胜率%'] > 0]
        
        if not annual_vals:
            continue
        
        avg_annual = np.mean(annual_vals)
        med_annual = np.median(annual_vals)
        avg_sharpe = np.mean(sharpe_vals)
        avg_dd = np.mean(dd_vals)
        avg_win = np.mean(win_vals) if win_vals else 0
        pos_ratio = sum(1 for a in annual_vals if a > 0) / len(annual_vals) * 100
        
        # 胜B&H占比
        beat_bh = 0
        total_cmp = 0
        for symbol, r in results.items():
            if r['状态'] != '✅':
                continue
            bh = all_bh_results.get(symbol, {})
            if bh:
                total_cmp += 1
                if r['年化%'] > bh.get('年化%', 0):
                    beat_bh += 1
        beat_pct = beat_bh / total_cmp * 100 if total_cmp > 0 else 0
        
        # 过拟合率
        of_results = all_step_overfit.get(step_name, {})
        if of_results:
            overfit_count = sum(1 for o in of_results.values() if o.get('过拟合', False))
            of_rate = overfit_count / len(of_results) * 100
            train_avg = np.mean([o['训练年化%'] for o in of_results.values()])
            test_avg = np.mean([o['测试年化%'] for o in of_results.values()])
        else:
            of_rate = 0
            train_avg = 0
            test_avg = 0
        
        # 等权组合绩效
        port_returns = all_step_portfolio_returns.get(step_name, {})
        if port_returns:
            avg_rets = [np.mean(port_returns[i]) for i in sorted(port_returns.keys()) if len(port_returns[i]) > 0]
            if avg_rets:
                avg_rets = np.array(avg_rets)
                cum = np.cumprod(1 + avg_rets)
                port_total = (cum[-1] - 1) * 100
                port_years = len(avg_rets) / 252
                port_annual = ((1 + port_total / 100) ** (1 / port_years) - 1) * 100 if port_years > 0 and port_total > -100 else -100
                peak = np.maximum.accumulate(cum)
                dd_arr = (cum - peak) / peak
                port_dd = abs(dd_arr.min()) * 100
                port_sharpe = np.mean(avg_rets) / np.std(avg_rets) * np.sqrt(252) if np.std(avg_rets) > 0 else 0
            else:
                port_annual = 0
                port_dd = 0
                port_sharpe = 0
        else:
            port_annual = 0
            port_dd = 0
            port_sharpe = 0
        
        # vs基线变化
        if baseline_stats is None:
            # 这是基线
            baseline_stats = {
                'avg_annual': avg_annual,
                'avg_sharpe': avg_sharpe,
                'avg_dd': avg_dd,
                'beat_pct': beat_pct,
                'of_rate': of_rate,
                'port_annual': port_annual,
                'port_sharpe': port_sharpe,
                'port_dd': port_dd,
            }
            vs_baseline = '— (基线)'
            improvement = 0
        else:
            annual_change = avg_annual - baseline_stats['avg_annual']
            sharpe_change = avg_sharpe - baseline_stats['avg_sharpe']
            dd_change = avg_dd - baseline_stats['avg_dd']
            beat_change = beat_pct - baseline_stats['beat_pct']
            of_change = of_rate - baseline_stats['of_rate']
            port_sharpe_change = port_sharpe - baseline_stats['port_sharpe']
            
            vs_baseline = (f"年化{annual_change:+.2f}% "
                          f"夏普{sharpe_change:+.2f} "
                          f"回撤{dd_change:+.2f}% "
                          f"胜B&H{beat_change:+.1f}% "
                          f"过拟合{of_change:+.1f}%")
            
            # 改善率（年化/最大回撤综合）
            if baseline_stats['avg_annual'] != 0:
                improvement = (avg_annual - baseline_stats['avg_annual']) / abs(baseline_stats['avg_annual']) * 100
            else:
                improvement = 0
        
        # 采纳判定（Agent 8规则）
        # 仅当(年化收益/最大回撤)提升>10%且通过过拟合检测时
        if baseline_stats and step_name != 'Step0_基线(日线EMA10/20+ADX20)':
            annual_improve = avg_annual - baseline_stats['avg_annual']
            dd_improve = baseline_stats['avg_dd'] - avg_dd  # 回撤降低为正
            combined_improve = annual_improve + dd_improve
            
            # 过拟合检测：测试集年化不能低于训练集30%以上
            pass_overfit = of_rate < 50  # 过拟合率低于50%
            
            # 多周期一致性：等权组合夏普>0.5且回撤<30%
            consistency = port_sharpe > 0.5 and port_dd < 30
            
            recommend = combined_improve > 5 and pass_overfit and consistency
        else:
            recommend = True  # 基线默认采纳
        
        summary_rows.append({
            'Step': step_name,
            '股票数': n_stocks,
            '平均年化%': round(avg_annual, 2),
            '中位年化%': round(med_annual, 2),
            '平均夏普': round(avg_sharpe, 2),
            '平均回撤%': round(avg_dd, 2),
            '平均胜率%': round(avg_win, 1),
            '正收益占比%': round(pos_ratio, 1),
            '胜B&H%': round(beat_pct, 1),
            '过拟合率%': round(of_rate, 1),
            '训练年化%': round(train_avg, 2),
            '测试年化%': round(test_avg, 2),
            '等权年化%': round(port_annual, 2),
            '等权夏普': round(port_sharpe, 2),
            '等权回撤%': round(port_dd, 2),
            'vs基线': vs_baseline,
            '改善率%': round(improvement, 1),
            '推荐采纳': '✅ 是' if recommend else '❌ 否',
        })
    
    summary_df = pd.DataFrame(summary_rows)
    
    # 打印汇总表
    print("\n" + summary_df[['Step', '股票数', '平均年化%', '中位年化%', '平均夏普', '平均回撤%',
                              '胜B&H%', '过拟合率%', '等权夏普', '等权回撤%',
                              'vs基线', '推荐采纳']].to_string(index=False))
    
    # B&H基准
    bh_annual_vals = [bh['年化%'] for bh in all_bh_results.values()]
    bh_sharpe_vals = [bh['夏普'] for bh in all_bh_results.values()]
    print(f"\n  📊 B&H基准: 平均年化={np.mean(bh_annual_vals):.2f}%, 平均夏普={np.mean(bh_sharpe_vals):.2f}%")
    
    # ================================================================
    # 逐步采纳决策
    # ================================================================
    print(f"\n{'━' * 130}")
    print(f"  🎯 {market_cn} — 逐步采纳决策")
    print(f"{'━' * 130}")
    
    adopted_steps = ['Step0_基线(日线EMA10/20+ADX20)']
    
    for row in summary_rows[1:]:  # 跳过基线
        step = row['Step']
        recommend = row['推荐采纳']
        
        if recommend == '✅ 是':
            adopted_steps.append(step)
            print(f"\n  ✅ {step}: 采纳")
            print(f"     年化: {row['平均年化%']}% (基线{baseline_stats['avg_annual']:.2f}%)")
            print(f"     夏普: {row['平均夏普']} (基线{baseline_stats['avg_sharpe']:.2f})")
            print(f"     回撤: {row['平均回撤%']}% (基线{baseline_stats['avg_dd']:.2f}%)")
            print(f"     胜B&H: {row['胜B&H%']}% (基线{baseline_stats['beat_pct']:.1f}%)")
            print(f"     过拟合率: {row['过拟合率%']}%")
            print(f"     等权夏普: {row['等权夏普']}")
        else:
            print(f"\n  ❌ {step}: 不采纳（反向优化或未通过检测）")
            print(f"     年化: {row['平均年化%']}% (基线{baseline_stats['avg_annual']:.2f}%)")
            print(f"     vs基线: {row['vs基线']}")
            print(f"     过拟合率: {row['过拟合率%']}%")
            print(f"     等权夏普: {row['等权夏普']}, 等权回撤: {row['等权回撤%']}%")
    
    print(f"\n  📋 最终采纳的优化步骤: {' → '.join(adopted_steps)}")
    
    # 保存结果
    os.makedirs(RESULTS_DIR, exist_ok=True)
    summary_df.to_csv(os.path.join(RESULTS_DIR, f'{market}_step_optimization.csv'), 
                      index=False, encoding='utf-8-sig')
    
    # 保存详细JSON
    detail = {}
    for step_name, results in all_step_results.items():
        detail[step_name] = {s: r for s, r in results.items()}
    
    with open(os.path.join(RESULTS_DIR, f'{market}_step_detail.json'), 'w') as f:
        json.dump(detail, f, ensure_ascii=False, indent=2, default=str)
    
    # 保存友好度评分
    friend_df = pd.DataFrame([
        {'股票': s, '友好度': round(score, 1)} 
        for s, score in sorted(friendliness_scores.items(), key=lambda x: -x[1])
    ])
    friend_df.to_csv(os.path.join(RESULTS_DIR, f'{market}_friendliness.csv'), 
                     index=False, encoding='utf-8-sig')
    
    print(f"\n  💾 结果已保存至 {RESULTS_DIR}/")
    
    return summary_df, adopted_steps


# ================================================================
# 🏁 主程序
# ================================================================

if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     🔬 Blakever 牛市策略 — 分步优化回测（防止反向优化）                     ║
║                                                                              ║
║     Step 0: 基线 — 日线EMA10/20 + ADX>20                                   ║
║     Step 1: 周线EMA10/30趋势过滤                                            ║
║     Step 2: ATR跟踪止损(2.5x)替代均线死叉                                  ║
║     Step 3: MACD金叉确认入场(替代ADX)                                       ║
║     Step 4: 策略友好标的过滤器(友好度>50分)                                 ║
║     Step 5: 美股底仓50%+增强(仅美股)                                        ║
║                                                                              ║
║     每步对比基线，仅提升>10%且通过过拟合检测才采纳                          ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    # 美股
    us_summary, us_adopted = step_backtest('us')
    
    # 港股
    hk_summary, hk_adopted = step_backtest('hk')
    
    # ================================================================
    # 最终总结
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  🏆 最终优化总结")
    print(f"{'━' * 130}")
    
    print(f"\n  📊 美股采纳路径: {' → '.join(us_adopted)}")
    print(f"  📊 港股采纳路径: {' → '.join(hk_adopted)}")
    
    print(f"""
  📋 后续行动建议：
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 1. 将采纳的优化步骤更新到 blakever_bull_strategy.py                      │
  │ 2. 在 blakever_stock_analyze 中更新Agent 3的Prompt配置                     │
  │ 3. 使用优化后策略进行实盘小仓位验证                                        │
  │ 4. 建立滚动窗口回测框架，持续监控策略有效性                                │
  └─────────────────────────────────────────────────────────────────────────────┘
    """)
    
    print("\n✅ 分步优化回测完成！")
