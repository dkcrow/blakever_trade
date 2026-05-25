#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
Blakever Agent3 牛市策略 — 本地十年数据回测（仅牛市区间）
==========================================================================
策略核心：EMA10/20持仓跟踪 + ADX趋势强度过滤
数据源：back_trader_stocks/hk/ 和 back_trader_stocks/us/ 本地CSV
框架：VectorBT 0.28.5 + TA-Lib 0.6.8

回测逻辑：
1. 从本地CSV加载所有股票近10年日线数据
2. 使用SMA50/200划分市场环境，识别牛市区间
3. 仅在牛市区间内运行牛市策略，验证策略有效性
4. 输出：个股回测汇总 + 等权组合回测 + 过拟合检测
==========================================================================
"""

import os
import glob
import json
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import talib
import vectorbt as vbt

warnings.filterwarnings('ignore')

# ================================================================
# ⚙️ 配置参数
# ================================================================
BASE_DIR = '/data/workspace/back_trader_stocks'
HK_DIR = os.path.join(BASE_DIR, 'hk')
US_DIR = os.path.join(BASE_DIR, 'us')
RESULTS_DIR = '/data/workspace/back_trader_bull_backtest_results'

INIT_CASH = 100000
FEES = 0.001       # 手续费 0.1%
SLIPPAGE = 0.001   # 滑点 0.1%

# 策略参数
EMA_FAST = 10
EMA_SLOW = 20
ADX_PERIOD = 14
ADX_THRESHOLD_STRICT = 25
ADX_THRESHOLD_RELAXED = 20

# 牛市识别参数
REGIME_SMA_FAST = 50
REGIME_SMA_SLOW = 200

# 过拟合检测
TRAIN_RATIO = 0.7  # 训练集比例

# 最少数据天数（不足此数跳过）
MIN_DATA_DAYS = 250

# 汇总输出前N名
TOP_N = 20


# ================================================================
# 📂 数据加载
# ================================================================

def load_stock_data(filepath):
    """加载单个股票CSV，返回标准化的DataFrame"""
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        # 标准化列名
        df.columns = [c.lower().strip() for c in df.columns]
        # 去除NaN
        df = df.dropna(subset=['close'])
        # 确保数值类型
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close'])
        return df
    except Exception as e:
        return None


def load_all_stocks(market='us', max_stocks=None):
    """加载指定市场的所有股票数据"""
    if market == 'hk':
        directory = HK_DIR
    else:
        directory = US_DIR

    files = sorted(glob.glob(os.path.join(directory, '*.csv')))
    if max_stocks:
        files = files[:max_stocks]

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
    """
    使用SMA50/200识别牛市区间。
    
    规则：
    - 收盘价 > SMA200 且 SMA50 > SMA200 → 牛市
    - 返回布尔Series，True=牛市
    
    同时支持只用收盘价趋势判断（数据不足200天时）：
    - 近60日涨幅 > 5% 且 短期均线多头 → 牛市
    """
    close = close_series.copy()
    
    sma50 = talib.SMA(close.values, timeperiod=REGIME_SMA_FAST)
    sma200 = talib.SMA(close.values, timeperiod=REGIME_SMA_SLOW)
    
    sma50_s = pd.Series(sma50, index=close.index)
    sma200_s = pd.Series(sma200, index=close.index)
    
    # 牛市条件
    bull_mask = (close > sma200_s) & (sma50_s > sma200_s)
    
    # 对于SMA200尚未生成的早期数据，用SMA50趋势判断
    early_mask = sma200_s.isna()
    if early_mask.any():
        sma20_early = close.rolling(20).mean()
        sma50_early = close.rolling(50).mean()
        early_bull = (close > sma50_early) & (sma20_early > sma50_early)
        bull_mask = bull_mask.fillna(early_bull)
    
    return bull_mask.fillna(False)


def extract_bull_segments(bull_mask, min_segment_days=30):
    """
    从牛市掩码中提取连续的牛市片段。
    返回 [(start_idx, end_idx), ...] 列表。
    """
    segments = []
    in_bull = False
    start = 0
    
    for i in range(len(bull_mask)):
        if bull_mask.iloc[i] and not in_bull:
            start = i
            in_bull = True
        elif not bull_mask.iloc[i] and in_bull:
            if i - start >= min_segment_days:
                segments.append((start, i))
            in_bull = False
    
    # 处理尾部
    if in_bull and len(bull_mask) - start >= min_segment_days:
        segments.append((start, len(bull_mask)))
    
    return segments


# ================================================================
# 📈 策略信号生成
# ================================================================

def bull_strategy_relaxed(close, high, low, adx_threshold=ADX_THRESHOLD_RELAXED):
    """
    Agent3 牛市策略 — 宽松版 (ADX > 20) ★ 推荐版本
    入场: EMA10 > EMA20 且 ADX > adx_threshold
    出场: EMA10 < EMA20 或 ADX < adx_threshold
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=EMA_FAST, adjust=False).mean()
    ema20 = c.ewm(span=EMA_SLOW, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=ADX_PERIOD)
    adx_s = pd.Series(adx)

    in_pos = (ema10 > ema20) & (adx_s > adx_threshold)

    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values

    return entries, exits


def bull_strategy_strict(close, high, low):
    """Agent3 牛市策略 — 严格版 (ADX > 25)"""
    return bull_strategy_relaxed(close, high, low, adx_threshold=ADX_THRESHOLD_STRICT)


def ema_cross_only(close, high, low):
    """对比基准: EMA10/20 无条件交叉（无ADX过滤）"""
    c = pd.Series(close, dtype=float)
    ema10 = c.ewm(span=EMA_FAST, adjust=False).mean()
    ema20 = c.ewm(span=EMA_SLOW, adjust=False).mean()
    in_pos = ema10 > ema20
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


def macd_confirm_strategy(close, high, low):
    """
    MACD确认替代ADX版：
    入场: EMA10 > EMA20 且 MACD柱状图连续3天>0
    出场: EMA10 < EMA20
    """
    c = pd.Series(close, dtype=float)
    h = pd.Series(high, dtype=float)
    l = pd.Series(low, dtype=float)

    ema10 = c.ewm(span=EMA_FAST, adjust=False).mean()
    ema20 = c.ewm(span=EMA_SLOW, adjust=False).mean()

    macd, macdsignal, macdhist = talib.MACD(c.values, fastperiod=12, slowperiod=26, signalperiod=9)
    hist_s = pd.Series(macdhist)
    
    # MACD柱状图连续3天>0
    macd_confirm = (hist_s > 0) & (hist_s.shift(1) > 0) & (hist_s.shift(2) > 0)

    in_pos = (ema10 > ema20) & macd_confirm
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits


# ================================================================
# 📊 回测引擎
# ================================================================

def run_single_backtest(close, high, low, strategy_func, strategy_name):
    """运行单个策略回测，返回绩效指标字典"""
    n = len(close)
    if n < 50:
        return None

    try:
        entries, exits = strategy_func(close, high, low)

        if entries.sum() == 0:
            return {
                '策略': strategy_name, '状态': '无交易信号',
                '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
                '胜率%': 0, '交易次数': 0, '盈亏比': 0, '夏普比': 0
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

        # 夏普比
        sharpe = float(stats.get('Sharpe Ratio', 0))
        if pd.isna(sharpe):
            sharpe = 0

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
            '状态': '✅',
            '总收益率%': round(total_return, 2),
            '年化收益%': round(annual, 2),
            '最大回撤%': round(max_dd, 2),
            '胜率%': round(win_rate, 1),
            '交易次数': total_trades,
            '盈亏比': round(profit_factor, 2),
            '夏普比': round(sharpe, 2),
        }
    except Exception as e:
        return {
            '策略': strategy_name, '状态': f'❌ {str(e)[:30]}',
            '总收益率%': 0, '年化收益%': 0, '最大回撤%': 0,
            '胜率%': 0, '交易次数': 0, '盈亏比': 0, '夏普比': 0
        }


def run_buy_hold(close):
    """买入持有基准"""
    n = len(close)
    entries_bh = np.full(n, False)
    entries_bh[0] = True
    exits_bh = np.full(n, False)
    try:
        pf = vbt.Portfolio.from_signals(
            close, entries=entries_bh, exits=exits_bh,
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
            '策略': 'Buy&Hold',
            '状态': '✅',
            '总收益率%': round(total_ret, 2),
            '年化收益%': round(annual, 2),
            '最大回撤%': round(float(stats['Max Drawdown [%]']), 2),
            '胜率%': '-',
            '交易次数': 1,
            '盈亏比': '-',
            '夏普比': round(sharpe, 2),
        }
    except Exception:
        return None


# ================================================================
# 🔍 过拟合检测
# ================================================================

def overfit_test(close, high, low, strategy_func, strategy_name):
    """
    过拟合检测：训练集(前70%) vs 测试集(后30%)
    若测试集年化收益低于训练集30%以上，判定过拟合
    """
    n = len(close)
    split = int(n * TRAIN_RATIO)
    
    # 训练集
    train_close = close[:split]
    train_high = high[:split]
    train_low = low[:split]
    r_train = run_single_backtest(train_close, train_high, train_low, strategy_func, f"{strategy_name}(训练)")
    
    # 测试集
    test_close = close[split:]
    test_high = high[split:]
    test_low = low[split:]
    r_test = run_single_backtest(test_close, test_high, test_low, strategy_func, f"{strategy_name}(测试)")
    
    if r_train is None or r_test is None:
        return None
    
    train_annual = r_train['年化收益%']
    test_annual = r_test['年化收益%']
    
    # 判定过拟合
    if train_annual > 0:
        drop_pct = (train_annual - test_annual) / abs(train_annual) * 100
        overfit = drop_pct > 30
    else:
        drop_pct = 0
        overfit = False
    
    return {
        '训练集年化%': train_annual,
        '测试集年化%': test_annual,
        '下降幅度%': round(drop_pct, 1),
        '过拟合': '⚠️ 是' if overfit else '✅ 否',
    }


# ================================================================
# 🚀 主回测流程
# ================================================================

def backtest_market(market='us', max_stocks=None):
    """对指定市场进行完整回测"""
    
    market_cn = '港股' if market == 'hk' else '美股'
    print(f"\n{'━' * 120}")
    print(f"  📊 {market_cn}市场 — 牛市策略回测")
    print(f"{'━' * 120}")
    
    # 加载数据
    print(f"\n  📦 加载{market_cn}数据...")
    stocks = load_all_stocks(market, max_stocks)
    print(f"  ✅ 共加载 {len(stocks)} 只股票")
    
    if not stocks:
        print("  ❌ 无有效数据，跳过")
        return None
    
    # 策略列表
    strategies = [
        ('宽松版(ADX>20)★', bull_strategy_relaxed),
        ('严格版(ADX>25)', bull_strategy_strict),
        ('EMA10/20无ADX', ema_cross_only),
        ('MACD确认替代', macd_confirm_strategy),
    ]
    
    # 个股回测结果收集
    all_stock_results = []
    overfit_results = []
    skipped = 0
    no_bull = 0
    
    # 等权组合收益收集（宽松版）
    portfolio_daily_returns = {}
    
    for symbol, df in stocks.items():
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        
        # 识别牛市区间
        bull_mask = identify_bull_periods(df['close'])
        bull_days = bull_mask.sum()
        total_days = len(bull_mask)
        bull_pct = bull_days / total_days * 100 if total_days > 0 else 0
        
        if bull_days < 50:
            no_bull += 1
            continue
        
        # 提取牛市数据
        bull_close = close[bull_mask.values]
        bull_high = high[bull_mask.values]
        bull_low = low[bull_mask.values]
        
        if len(bull_close) < 50:
            skipped += 1
            continue
        
        # 运行各策略回测
        stock_result = {
            '股票': symbol,
            '牛市天数': bull_days,
            '牛市占比%': round(bull_pct, 1),
            '数据起始': str(df.index[0].date()),
            '数据结束': str(df.index[-1].date()),
        }
        
        for strat_name, strat_func in strategies:
            r = run_single_backtest(bull_close, bull_high, bull_low, strat_func, strat_name)
            if r:
                stock_result[f'{strat_name}_年化%'] = r['年化收益%']
                stock_result[f'{strat_name}_回撤%'] = r['最大回撤%']
                stock_result[f'{strat_name}_胜率%'] = r['胜率%']
                stock_result[f'{strat_name}_夏普'] = r['夏普比']
                stock_result[f'{strat_name}_交易数'] = r['交易次数']
        
        # Buy & Hold (牛市区间)
        bh = run_buy_hold(bull_close)
        if bh:
            stock_result['B&H_年化%'] = bh['年化收益%']
            stock_result['B&H_回撤%'] = bh['最大回撤%']
            stock_result['B&H_夏普'] = bh['夏普比']
        
        # 宽松版 vs B&H
        relaxed_annual = stock_result.get('宽松版(ADX>20)★_年化%', 0)
        bh_annual = stock_result.get('B&H_年化%', 0)
        stock_result['超额收益%'] = round(relaxed_annual - bh_annual, 2)
        
        all_stock_results.append(stock_result)
        
        # 过拟合检测（宽松版，使用完整牛市区间数据）
        of = overfit_test(bull_close, bull_high, bull_low, bull_strategy_relaxed, '宽松版')
        if of:
            of['股票'] = symbol
            overfit_results.append(of)
        
        # 收集等权组合日收益率（宽松版策略）
        try:
            entries, exits = bull_strategy_relaxed(bull_close, bull_high, bull_low)
            if entries.sum() > 0:
                pf = vbt.Portfolio.from_signals(
                    bull_close, entries=entries, exits=exits,
                    freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE
                )
                # 使用相对日期索引（因为牛市区间日期不连续）
                returns = pf.returns().values
                for i, ret in enumerate(returns):
                    if i not in portfolio_daily_returns:
                        portfolio_daily_returns[i] = []
                    portfolio_daily_returns[i].append(ret)
        except Exception:
            pass
    
    print(f"\n  📊 回测完成: 成功{len(all_stock_results)}只, 无牛市区间{no_bull}只, 跳过{skipped}只")
    
    if not all_stock_results:
        print("  ❌ 无有效回测结果")
        return None
    
    # ================================================================
    # 结果汇总
    # ================================================================
    results_df = pd.DataFrame(all_stock_results)
    
    # --- 1. 整体统计 ---
    print(f"\n{'━' * 120}")
    print(f"  📈 {market_cn} — 策略整体表现（{len(results_df)}只股票）")
    print(f"{'━' * 120}")
    
    summary_rows = []
    for strat_label in ['宽松版(ADX>20)★', '严格版(ADX>25)', 'EMA10/20无ADX', 'MACD确认替代', 'B&H']:
        annual_col = f'{strat_label}_年化%'
        dd_col = f'{strat_label}_回撤%'
        sharpe_col = f'{strat_label}_夏普'
        win_col = f'{strat_label}_胜率%'
        
        if annual_col not in results_df.columns:
            continue
        
        annual_vals = results_df[annual_col].replace(0, np.nan).dropna()
        dd_vals = results_df[dd_col].replace(0, np.nan).dropna()
        sharpe_vals = results_df[sharpe_col].replace(0, np.nan).dropna()
        win_vals = results_df[win_col].replace(0, np.nan).dropna() if win_col in results_df.columns else pd.Series()
        
        # 超越B&H的比例
        if strat_label != 'B&H' and 'B&H_年化%' in results_df.columns:
            bh_col = results_df['B&H_年化%']
            strat_col = results_df[annual_col]
            beat_bh = (strat_col > bh_col).sum()
            total_cmp = len(strat_col)
            beat_pct = beat_bh / total_cmp * 100 if total_cmp > 0 else 0
        else:
            beat_bh = 0
            beat_pct = 0
        
        summary_rows.append({
            '策略': strat_label,
            '平均年化%': round(annual_vals.mean(), 2) if len(annual_vals) > 0 else '-',
            '中位年化%': round(annual_vals.median(), 2) if len(annual_vals) > 0 else '-',
            '平均回撤%': round(dd_vals.mean(), 2) if len(dd_vals) > 0 else '-',
            '平均夏普': round(sharpe_vals.mean(), 2) if len(sharpe_vals) > 0 else '-',
            '平均胜率%': round(win_vals.mean(), 1) if len(win_vals) > 0 else '-',
            '正收益占比%': round((annual_vals > 0).sum() / len(annual_vals) * 100, 1) if len(annual_vals) > 0 else '-',
            '胜B&H占比%': round(beat_pct, 1),
        })
    
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))
    
    # --- 2. TOP N 个股 ---
    print(f"\n{'━' * 120}")
    print(f"  🏆 {market_cn} — 牛市策略(宽松版) TOP {TOP_N} 个股（按年化收益排序）")
    print(f"{'━' * 120}")
    
    top_col = '宽松版(ADX>20)★_年化%'
    if top_col in results_df.columns:
        top_df = results_df.nlargest(TOP_N, top_col)[
            ['股票', '牛市天数', '牛市占比%', top_col, 
             '宽松版(ADX>20)★_回撤%', '宽松版(ADX>20)★_夏普',
             '宽松版(ADX>20)★_胜率%', 'B&H_年化%', '超额收益%']
        ]
        print(top_df.to_string(index=False))
    
    # --- 3. 策略胜率分布 ---
    print(f"\n{'━' * 120}")
    print(f"  📊 {market_cn} — 策略 vs Buy&Hold 对比统计")
    print(f"{'━' * 120}")
    
    if '超额收益%' in results_df.columns:
        excess = results_df['超额收益%']
        print(f"  超额收益分布:")
        print(f"    均值: {excess.mean():.2f}%")
        print(f"    中位数: {excess.median():.2f}%")
        print(f"    策略胜B&H: {(excess > 0).sum()}/{len(excess)} ({(excess > 0).mean()*100:.1f}%)")
        print(f"    策略大幅胜出(>10%): {(excess > 10).sum()}只")
        print(f"    策略大幅落后(<-10%): {(excess < -10).sum()}只")
    
    # --- 4. 过拟合检测汇总 ---
    print(f"\n{'━' * 120}")
    print(f"  🔬 {market_cn} — 过拟合检测汇总（宽松版ADX>20）")
    print(f"{'━' * 120}")
    
    if overfit_results:
        of_df = pd.DataFrame(overfit_results)
        overfit_count = (of_df['过拟合'] == '⚠️ 是').sum()
        total_of = len(of_df)
        print(f"  过拟合股票: {overfit_count}/{total_of} ({overfit_count/total_of*100:.1f}%)")
        print(f"  训练集平均年化: {of_df['训练集年化%'].mean():.2f}%")
        print(f"  测试集平均年化: {of_df['测试集年化%'].mean():.2f}%")
        print(f"  平均下降幅度: {of_df['下降幅度%'].mean():.1f}%")
        
        # 过拟合最严重的TOP 10
        if overfit_count > 0:
            worst_of = of_df[of_df['过拟合'] == '⚠️ 是'].nlargest(10, '下降幅度%')
            print(f"\n  ⚠️ 过拟合最严重 TOP 10:")
            print(worst_of[['股票', '训练集年化%', '测试集年化%', '下降幅度%']].to_string(index=False))
    
    # --- 5. 等权组合回测 ---
    print(f"\n{'━' * 120}")
    print(f"  📊 {market_cn} — 等权组合回测（宽松版ADX>20）")
    print(f"{'━' * 120}")
    
    if portfolio_daily_returns:
        avg_returns = []
        for i in sorted(portfolio_daily_returns.keys()):
            rets = portfolio_daily_returns[i]
            if len(rets) > 0:
                avg_returns.append(np.mean(rets))
            else:
                avg_returns.append(0)
        
        avg_returns = np.array(avg_returns)
        cumulative = np.cumprod(1 + avg_returns)
        
        total_ret = (cumulative[-1] - 1) * 100 if len(cumulative) > 0 else 0
        n_years = len(avg_returns) / 252
        annual = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else -100
        
        # 最大回撤
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak
        max_dd = abs(drawdown.min()) * 100 if len(drawdown) > 0 else 0
        
        # 夏普
        sharpe = np.mean(avg_returns) / np.std(avg_returns) * np.sqrt(252) if np.std(avg_returns) > 0 else 0
        
        print(f"  等权组合绩效（{len(results_df)}只股票平均）:")
        print(f"    总收益率: {total_ret:.2f}%")
        print(f"    年化收益: {annual:.2f}%")
        print(f"    最大回撤: {max_dd:.2f}%")
        print(f"    夏普比: {sharpe:.2f}")
        print(f"    回测天数: {len(avg_returns)}")
    
    # --- 6. 一致性验证 ---
    print(f"\n{'━' * 120}")
    print(f"  ✅ {market_cn} — 一致性验证")
    print(f"{'━' * 120}")
    
    if top_col in results_df.columns:
        annual_vals = results_df[top_col].replace(0, np.nan).dropna()
        sharpe_vals = results_df['宽松版(ADX>20)★_夏普'].replace(0, np.nan).dropna()
        dd_vals = results_df['宽松版(ADX>20)★_回撤%'].replace(0, np.nan).dropna()
        
        sharpe_pass = (sharpe_vals > 0.5).sum()
        dd_pass = (dd_vals < 30).sum()
        total_valid = len(annual_vals)
        
        print(f"  夏普比>0.5: {sharpe_pass}/{total_valid} ({sharpe_pass/total_valid*100:.1f}%)")
        print(f"  最大回撤<30%: {dd_pass}/{total_valid} ({dd_pass/total_valid*100:.1f}%)")
        print(f"  两项均达标: {((sharpe_vals > 0.5) & (dd_vals < 30)).sum()}/{total_valid}")
        
        verdict = "✅ 通过" if sharpe_pass / total_valid > 0.5 and dd_pass / total_valid > 0.5 else "⚠️ 标记警告"
        print(f"  综合判定: {verdict}")
    
    # 保存结果
    os.makedirs(RESULTS_DIR, exist_ok=True)
    results_df.to_csv(os.path.join(RESULTS_DIR, f'{market}_bull_backtest.csv'), index=False, encoding='utf-8-sig')
    if overfit_results:
        pd.DataFrame(overfit_results).to_csv(
            os.path.join(RESULTS_DIR, f'{market}_overfit_test.csv'), index=False, encoding='utf-8-sig'
        )
    print(f"\n  💾 结果已保存至 {RESULTS_DIR}/")
    
    return results_df


# ================================================================
# 🏁 主程序入口
# ================================================================

if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     🐂 Blakever Agent3 牛市策略 — 本地十年数据回测（仅牛市区间）            ║
║                                                                              ║
║     策略: EMA10/20持仓跟踪 + ADX趋势强度过滤                               ║
║     数据: back_trader_stocks/hk/ + back_trader_stocks/us/                   ║
║     框架: VectorBT 0.28.5 + TA-Lib 0.6.8                                   ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    # 美股回测
    us_results = backtest_market('us')
    
    # 港股回测
    hk_results = backtest_market('hk')
    
    # ================================================================
    # 最终总结
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📋 最终总结与策略有效性判定")
    print(f"{'━' * 120}")
    
    for market_cn, results in [("美股", us_results), ("港股", hk_results)]:
        if results is None or len(results) == 0:
            print(f"\n  {market_cn}: 无有效回测结果")
            continue
        
        top_col = '宽松版(ADX>20)★_年化%'
        if top_col not in results.columns:
            continue
        
        annual_vals = results[top_col].replace(0, np.nan).dropna()
        bh_col = 'B&H_年化%'
        if bh_col in results.columns:
            bh_vals = results[bh_col].replace(0, np.nan).dropna()
            excess = results['超额收益%'].dropna()
            beat_pct = (excess > 0).mean() * 100 if len(excess) > 0 else 0
        else:
            bh_vals = pd.Series()
            beat_pct = 0
        
        print(f"\n  🐂 {market_cn}牛市策略(宽松版ADX>20)有效性总结:")
        print(f"  ┌────────────────────────────────────────────────────────────┐")
        print(f"  │ 回测股票数: {len(results):>6}                                       │")
        print(f"  │ 策略平均年化: {annual_vals.mean():>8.2f}%  (中位: {annual_vals.median():>8.2f}%)         │")
        if len(bh_vals) > 0:
            print(f"  │ B&H平均年化:  {bh_vals.mean():>8.2f}%  (中位: {bh_vals.median():>8.2f}%)         │")
        print(f"  │ 策略正收益占比: {(annual_vals > 0).mean()*100:>5.1f}%                              │")
        print(f"  │ 策略胜B&H占比:  {beat_pct:>5.1f}%                              │")
        
        # 有效性判定
        is_effective = (
            annual_vals.mean() > 0 and
            beat_pct > 40 and
            (annual_vals > 0).mean() > 0.5
        )
        
        if is_effective:
            print(f"  │                                                            │")
            print(f"  │ 🎯 判定: 策略有效 ✅                                       │")
            print(f"  │    牛市环境下策略平均正收益，且较大比例跑赢买入持有         │")
        else:
            print(f"  │                                                            │")
            print(f"  │ ⚠️ 判定: 策略需优化                                        │")
            print(f"  │    牛市环境下策略未能稳定跑赢买入持有                       │")
        print(f"  └────────────────────────────────────────────────────────────┘")
    
    print(f"\n✅ 回测完成！详细结果见 {RESULTS_DIR}/ 目录")
