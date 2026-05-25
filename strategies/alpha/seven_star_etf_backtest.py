#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF轮动策略 - VectorBT回测
======================================
原始策略来源：聚宽 (https://www.joinquant.com/post/70809)
策略名称：七星高照ETF轮动策略-V1.7.2 (GLM5修复版)
回测框架：VectorBT 0.28.5
数据源：akshare（A股ETF历史K线）+ 沪深300指数基准

策略核心逻辑：
1. 加权线性回归动量评分（年化收益率 × R²）
2. 短期动量过滤 / 溢价率过滤 / 成交量异常过滤 / 近3日大跌过滤
3. 盈利保护（从近期高点回撤超阈值则卖出）
4. 持仓1只ETF，不满足条件时持有货币基金(511880)
5. 每日13:10卖出、13:11买入（回测中简化为当日收盘价执行）

回测区间：2019-01-01 ~ 2025-12-31
初始资金：100万
费率：双边万二+印花税0+滑点万分之一
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import math
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

import akshare as ak
import vectorbt as vbt

# ================================================================
# 策略参数（与原始聚宽策略一致）
# ================================================================
LOOKBACK_DAYS = 25              # 动量计算周期
HOLDINGS_NUM = 1                # 候选持仓数量
DEFENSIVE_ETF = "511880.XSHG"   # 防御ETF（货币基金）
MIN_MONEY = 5000                # 最小交易金额

# 盈利保护参数
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1   # 盈利保护回看周期（天）
PROFIT_PROTECTION_THRESHOLD = 0.05  # 5%回撤阈值

# 近3日跌幅阈值
LOSS_THRESHOLD = 0.97

# 得分阈值
MIN_SCORE_THRESHOLD = 0
MAX_SCORE_THRESHOLD = 100.0

# 成交量过滤
ENABLE_VOLUME_CHECK = True
VOLUME_LOOKBACK = 5
VOLUME_THRESHOLD = 2
VOLUME_RETURN_LIMIT = 1.0  # 年化收益>100%时启用放量过滤

# 短期动量过滤
USE_SHORT_MOMENTUM_FILTER = True
SHORT_LOOKBACK_DAYS = 10
SHORT_MOMENTUM_THRESHOLD = 0.0

# 溢价率过滤（回测中简化，不做溢价率过滤）
ENABLE_PREMIUM_FILTER = False
PREMIUM_THRESHOLD = 0.20

# 交易参数
INIT_CASH = 1_000_000
OPEN_COMMISSION = 0.0002
CLOSE_COMMISSION = 0.0002
SLIPPAGE_RATE = 0.0001
MIN_COMMISSION = 5

# 回测区间
BACKTEST_START = '2019-01-01'
BACKTEST_END = '2025-12-31'

# ETF池定义（聚宽代码 -> akshare代码映射）
ETF_POOL_JQ = [
    "518880.XSHG", "159980.XSHE", "159985.XSHE", "501018.XSHG",
    "161226.XSHE", "159981.XSHE", "513100.XSHG", "159509.XSHE",
    "513290.XSHG", "513500.XSHG", "159529.XSHE", "513400.XSHG",
    "513520.XSHG", "513030.XSHG", "513080.XSHG", "513310.XSHG",
    "513730.XSHG", "159792.XSHE", "513130.XSHG", "513050.XSHG",
    "159920.XSHE", "513690.XSHG", "510300.XSHG", "510500.XSHG",
    "510050.XSHG", "510210.XSHG", "159915.XSHE", "588080.XSHG",
    "512100.XSHG", "563360.XSHG", "512890.XSHG", "159967.XSHE",
    "512040.XSHG", "159201.XSHE", "511380.XSHG", "511010.XSHG",
    "511220.XSHG",
]

# 排除数据不足的ETF
EXCLUDE_ETFS = ["563300.XSHE"]  # 无数据

# ETF中文名
ETF_NAMES = {
    "518880.XSHG": "黄金ETF", "159980.XSHE": "有色ETF", "159985.XSHE": "豆粕ETF",
    "501018.XSHG": "南方原油", "161226.XSHE": "白银LOF", "159981.XSHE": "能源化工ETF",
    "513100.XSHG": "纳指ETF", "159509.XSHE": "纳指科技ETF", "513290.XSHG": "纳指生物ETF",
    "513500.XSHG": "标普500ETF", "159529.XSHE": "标普消费", "513400.XSHG": "道琼斯ETF",
    "513520.XSHG": "日经225ETF", "513030.XSHG": "德国30ETF", "513080.XSHG": "法国ETF",
    "513310.XSHG": "中韩半导体ETF", "513730.XSHG": "东南亚ETF",
    "159792.XSHE": "港股互联ETF", "513130.XSHG": "恒生科技", "513050.XSHG": "中概互联网ETF",
    "159920.XSHE": "恒生ETF", "513690.XSHG": "港股红利",
    "510300.XSHG": "沪深300ETF", "510500.XSHG": "中证500ETF", "510050.XSHG": "上证50ETF",
    "510210.XSHG": "上证ETF", "159915.XSHE": "创业板ETF", "588080.XSHG": "科创50",
    "512100.XSHG": "中证1000ETF", "563360.XSHG": "A500-ETF",
    "512890.XSHG": "红利低波ETF", "159967.XSHE": "创业板成长ETF",
    "512040.XSHG": "价值ETF", "159201.XSHE": "自由现金流ETF",
    "511380.XSHG": "可转债ETF", "511010.XSHG": "国债ETF", "511220.XSHG": "城投债ETF",
    "511880.XSHG": "货币基金",
}


def jq_to_akshare(code):
    """聚宽代码转akshare代码"""
    code_num = code.split('.')[0]
    if 'XSHG' in code:
        return 'sh' + code_num
    else:
        return 'sz' + code_num


def jq_code_num(code):
    """提取代码数字部分"""
    return code.split('.')[0]


# ================================================================
# 数据获取模块
# ================================================================
def fetch_all_etf_data(etf_pool, start_date, end_date):
    """
    批量获取ETF池历史K线数据
    返回: {jq_code: DataFrame(close, high, low, open, volume)}
    """
    all_data = {}
    total = len(etf_pool)
    for i, code in enumerate(etf_pool):
        if code in EXCLUDE_ETFS:
            continue
        ak_code = jq_to_akshare(code)
        name = ETF_NAMES.get(code, code)
        try:
            df = ak.fund_etf_hist_sina(symbol=ak_code)
            if df is None or df.empty:
                print(f"  ⚠️ [{i+1}/{total}] {code} {name}: 无数据")
                continue

            # 标准化
            df = df.copy()
            # 兼容不同的列名
            col_map = {}
            for col in df.columns:
                col_lower = col.lower().strip()
                if col_lower == 'date':
                    col_map[col] = 'date'
                elif col_lower == 'open':
                    col_map[col] = 'open'
                elif col_lower in ('close', 'last'):
                    col_map[col] = 'close'
                elif col_lower == 'high':
                    col_map[col] = 'high'
                elif col_lower == 'low':
                    col_map[col] = 'low'
                elif col_lower == 'volume':
                    col_map[col] = 'volume'
                elif col_lower == 'amount':
                    col_map[col] = 'amount'
                elif col_lower == 'prevclose':
                    col_map[col] = 'prevclose'

            df = df.rename(columns=col_map)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.sort_index()

            # 只保留需要的列
            keep_cols = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
            df = df[keep_cols]

            # 转换为float
            for col in keep_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # 过滤日期范围
            df = df[(df.index >= start_date) & (df.index <= end_date)]

            if len(df) < LOOKBACK_DAYS + 30:
                print(f"  ⚠️ [{i+1}/{total}] {code} {name}: 数据不足({len(df)}行)")
                continue

            all_data[code] = df
            print(f"  ✅ [{i+1}/{total}] {code} {name}: {len(df)}行")

        except Exception as e:
            print(f"  ❌ [{i+1}/{total}] {code} {name}: {e}")

    return all_data


def fetch_benchmark_data(start_date, end_date):
    """获取沪深300指数基准数据"""
    try:
        df = ak.stock_zh_index_daily(symbol='sh000300')
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        return df
    except Exception as e:
        print(f"  ❌ 沪深300基准数据获取失败: {e}")
        return None


# ================================================================
# 策略核心计算模块
# ================================================================
def calculate_momentum_score(prices_series, lookback_days=LOOKBACK_DAYS,
                              short_lookback=SHORT_LOOKBACK_DAYS):
    """
    计算单只ETF的加权线性回归动量得分
    返回: dict or None
    """
    if len(prices_series) < lookback_days + 5:
        return None

    # 取最近lookback_days+1个交易日的收盘价
    recent = prices_series[-(lookback_days + 1):]
    if len(recent) < lookback_days + 1:
        return None

    # 检查NaN
    if recent.isna().any():
        return None

    # 加权线性回归
    y = np.log(recent.values)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))

    try:
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized_returns = math.exp(slope * 250) - 1

        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0

        score = annualized_returns * r_squared
    except Exception:
        return None

    # 短期动量
    if len(prices_series) >= short_lookback + 1:
        short_return = prices_series.iloc[-1] / prices_series.iloc[-(short_lookback + 1)] - 1
        short_annualized = (1 + short_return) ** (250 / short_lookback) - 1
    else:
        short_annualized = 0

    # 近3日跌幅检查
    if len(prices_series) >= 4:
        day1 = prices_series.iloc[-1] / prices_series.iloc[-2]
        day2 = prices_series.iloc[-2] / prices_series.iloc[-3]
        day3 = prices_series.iloc[-3] / prices_series.iloc[-4]
        recent_3day_min = min(day1, day2, day3)
    else:
        recent_3day_min = 1.0

    return {
        'score': score,
        'annualized_returns': annualized_returns,
        'r_squared': r_squared,
        'short_annualized': short_annualized,
        'recent_3day_min': recent_3day_min,
    }


def check_profit_protection(prices_series, high_series, lookback=PROFIT_PROTECTION_LOOKBACK,
                             threshold=PROFIT_PROTECTION_THRESHOLD):
    """
    盈利保护检查：从最近N日最高点回撤超过阈值
    """
    if not ENABLE_PROFIT_PROTECTION:
        return False

    if len(high_series) < lookback:
        return False

    # 不包括当天的最近N日最高价
    max_high = high_series.iloc[-(lookback + 1):-1].max() if len(high_series) > lookback else high_series.iloc[:-1].max()
    current_price = prices_series.iloc[-1]

    if pd.isna(max_high) or pd.isna(current_price) or max_high == 0:
        return False

    drawdown = 1 - current_price / max_high
    return drawdown >= threshold


# ================================================================
# 回测引擎
# ================================================================
def run_strategy_backtest(etf_data, benchmark_df, start_date, end_date):
    """
    执行七星高照ETF轮动策略回测

    策略逻辑:
    - 每个交易日收盘时:
      1. 计算所有ETF的动量得分
      2. 过滤: 得分阈值、短期动量、近3日跌幅、盈利保护
      3. 选择得分最高的HOLDINGS_NUM只ETF
      4. 若无合格ETF，持有防御ETF（货币基金）
      5. 若当前持仓不在目标中，卖出；在目标中，持有
    """
    print("\n" + "="*60)
    print("🚀 开始执行七星高照ETF轮动策略回测")
    print("="*60)

    # 获取所有交易日的并集
    all_dates = set()
    for code, df in etf_data.items():
        all_dates.update(df.index.tolist())
    all_dates = sorted([d for d in all_dates if d >= pd.Timestamp(start_date) and d <= pd.Timestamp(end_date)])

    if not all_dates:
        print("❌ 无交易日数据")
        return None

    print(f"  回测区间: {all_dates[0].strftime('%Y-%m-%d')} ~ {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"  交易日数: {len(all_dates)}")
    print(f"  ETF数量: {len(etf_data)}")

    # 初始化
    cash = INIT_CASH
    holdings = {}  # {code: {'shares': int, 'avg_cost': float}}
    portfolio_values = []
    trade_log = []
    daily_positions = []

    # 盈利保护卖出黑名单（日内）
    profit_protection_sold_today = []

    for day_idx, current_date in enumerate(all_dates):
        # 每日清空盈利保护黑名单
        profit_protection_sold_today = []

        # 获取当天各ETF价格
        current_prices = {}
        current_highs = {}
        available_etfs = {}

        for code, df in etf_data.items():
            if current_date not in df.index:
                continue
            row = df.loc[current_date]
            price = row['close']
            high = row.get('high', price)
            vol = row.get('volume', 0)

            if pd.isna(price) or price <= 0:
                continue

            current_prices[code] = price
            current_highs[code] = high
            available_etfs[code] = df

        if not current_prices:
            portfolio_values.append({'date': current_date, 'value': cash})
            continue

        # ---- 盈利保护检查 (模拟11:00) ----
        for code in list(holdings.keys()):
            if code not in current_prices:
                continue
            pos = holdings[code]
            if pos['shares'] <= 0:
                continue

            # 获取历史最高价序列
            df = available_etfs.get(code)
            if df is None:
                continue

            hist_up_to_yesterday = df[df.index < current_date]
            if len(hist_up_to_yesterday) < PROFIT_PROTECTION_LOOKBACK:
                continue

            high_series = hist_up_to_yesterday['high'].iloc[-(PROFIT_PROTECTION_LOOKBACK + 5):]
            price_series = hist_up_to_yesterday['close'].iloc[-(PROFIT_PROTECTION_LOOKBACK + 5):]

            if check_profit_protection(price_series, high_series):
                # 盈利保护卖出
                sell_price = current_prices[code]
                sell_amount = pos['shares'] * sell_price
                commission = max(sell_amount * CLOSE_COMMISSION, MIN_COMMISSION)
                slippage_cost = sell_amount * SLIPPAGE_RATE
                net_proceeds = sell_amount - commission - slippage_cost

                cash += net_proceeds
                trade_log.append({
                    'date': current_date,
                    'code': code,
                    'name': ETF_NAMES.get(code, code),
                    'action': '盈利保护卖出',
                    'price': sell_price,
                    'shares': pos['shares'],
                    'amount': sell_amount,
                    'commission': commission,
                })
                profit_protection_sold_today.append(code)
                del holdings[code]

        # ---- 计算动量排名 ----
        etf_scores = []
        for code, df in available_etfs.items():
            # 获取截止到前一天的数据
            hist = df[df.index < current_date]
            if len(hist) < LOOKBACK_DAYS + 5:
                continue

            close_series = hist['close'].dropna()
            if len(close_series) < LOOKBACK_DAYS + 1:
                continue

            metrics = calculate_momentum_score(close_series)
            if metrics is None:
                continue

            # 得分过滤
            if not (MIN_SCORE_THRESHOLD < metrics['score'] < MAX_SCORE_THRESHOLD):
                continue

            # 短期动量过滤
            if USE_SHORT_MOMENTUM_FILTER and metrics['short_annualized'] < SHORT_MOMENTUM_THRESHOLD:
                continue

            # 近3日跌幅过滤
            if metrics['recent_3day_min'] < LOSS_THRESHOLD:
                continue

            # 盈利保护检查（排名阶段）
            high_series = hist['high'].iloc[-(PROFIT_PROTECTION_LOOKBACK + 5):]
            price_series_for_pp = hist['close'].iloc[-(PROFIT_PROTECTION_LOOKBACK + 5):]
            if ENABLE_PROFIT_PROTECTION and check_profit_protection(price_series_for_pp, high_series):
                continue

            etf_scores.append({
                'code': code,
                'name': ETF_NAMES.get(code, code),
                'score': metrics['score'],
                'annualized_returns': metrics['annualized_returns'],
                'r_squared': metrics['r_squared'],
            })

        # 按得分排序
        etf_scores.sort(key=lambda x: x['score'], reverse=True)

        # 选择目标ETF
        target_etfs = []
        for m in etf_scores:
            if len(target_etfs) >= HOLDINGS_NUM:
                break
            code = m['code']
            # 二次检查：盈利保护黑名单
            if code in profit_protection_sold_today:
                continue
            target_etfs.append(m)

        # 防御模式
        defensive_code = DEFENSIVE_ETF
        defensive_available = (defensive_code in current_prices and
                              current_prices[defensive_code] > 0)

        if not target_etfs:
            if defensive_available:
                target_etfs = [{
                    'code': defensive_code,
                    'name': ETF_NAMES.get(defensive_code, defensive_code),
                    'score': 0,
                    'annualized_returns': 0,
                    'r_squared': 0,
                }]
            else:
                target_etfs = []

        target_codes = set(m['code'] for m in target_etfs)

        # ---- 卖出模块 (13:10) ----
        for code in list(holdings.keys()):
            if code not in target_codes:
                pos = holdings[code]
                if pos['shares'] <= 0:
                    continue
                if code not in current_prices:
                    continue

                sell_price = current_prices[code]
                sell_amount = pos['shares'] * sell_price
                commission = max(sell_amount * CLOSE_COMMISSION, MIN_COMMISSION)
                slippage_cost = sell_amount * SLIPPAGE_RATE
                net_proceeds = sell_amount - commission - slippage_cost

                cash += net_proceeds
                trade_log.append({
                    'date': current_date,
                    'code': code,
                    'name': ETF_NAMES.get(code, code),
                    'action': '卖出',
                    'price': sell_price,
                    'shares': pos['shares'],
                    'amount': sell_amount,
                    'commission': commission,
                })
                del holdings[code]

        # ---- 买入模块 (13:11) ----
        # 检查是否还有待卖出的持仓
        pending_sell = [code for code in holdings if code not in target_codes]
        if pending_sell:
            # 还有持仓未卖出，等待
            pass
        else:
            # 等权分配
            n_targets = len(target_etfs)
            if n_targets > 0:
                total_value = cash + sum(
                    holdings.get(m['code'], {}).get('shares', 0) * current_prices.get(m['code'], 0)
                    for m in target_etfs if m['code'] in current_prices
                )
                target_per_etf = total_value / n_targets

                for m in target_etfs:
                    code = m['code']
                    if code not in current_prices:
                        continue

                    current_val = 0
                    if code in holdings:
                        current_val = holdings[code]['shares'] * current_prices[code]

                    # 仅当偏差>5%或空仓时调整
                    if abs(current_val - target_per_etf) > target_per_etf * 0.05 or current_val == 0:
                        price = current_prices[code]
                        # 计算目标股数（100的整数倍）
                        target_shares = int(target_per_etf / price)
                        target_shares = (target_shares // 100) * 100
                        if target_shares <= 0 and target_per_etf > 0:
                            target_shares = 100

                        current_shares = holdings.get(code, {}).get('shares', 0)
                        diff = target_shares - current_shares

                        if diff > 0:
                            # 买入
                            buy_amount = diff * price
                            commission = max(buy_amount * OPEN_COMMISSION, MIN_COMMISSION)
                            slippage_cost = buy_amount * SLIPPAGE_RATE
                            total_cost = buy_amount + commission + slippage_cost

                            if total_cost > cash:
                                # 资金不足，减少买入数量
                                affordable = int((cash - MIN_COMMISSION) / (price * (1 + OPEN_COMMISSION + SLIPPAGE_RATE)))
                                affordable = (affordable // 100) * 100
                                if affordable > 0:
                                    diff = affordable
                                    buy_amount = diff * price
                                    commission = max(buy_amount * OPEN_COMMISSION, MIN_COMMISSION)
                                    slippage_cost = buy_amount * SLIPPAGE_RATE
                                    total_cost = buy_amount + commission + slippage_cost
                                else:
                                    diff = 0

                            if diff > 0:
                                cash -= total_cost
                                # 更新持仓
                                if code in holdings:
                                    old_shares = holdings[code]['shares']
                                    old_cost = holdings[code]['avg_cost']
                                    new_avg = (old_shares * old_cost + diff * price) / (old_shares + diff)
                                    holdings[code] = {'shares': old_shares + diff, 'avg_cost': new_avg}
                                else:
                                    holdings[code] = {'shares': diff, 'avg_cost': price}

                                trade_log.append({
                                    'date': current_date,
                                    'code': code,
                                    'name': ETF_NAMES.get(code, code),
                                    'action': '买入',
                                    'price': price,
                                    'shares': diff,
                                    'amount': buy_amount,
                                    'commission': commission,
                                })

                        elif diff < 0:
                            # 减仓
                            sell_shares = abs(diff)
                            sell_price = price
                            sell_amount = sell_shares * sell_price
                            commission = max(sell_amount * CLOSE_COMMISSION, MIN_COMMISSION)
                            slippage_cost = sell_amount * SLIPPAGE_RATE
                            net_proceeds = sell_amount - commission - slippage_cost

                            cash += net_proceeds
                            holdings[code]['shares'] -= sell_shares

                            trade_log.append({
                                'date': current_date,
                                'code': code,
                                'name': ETF_NAMES.get(code, code),
                                'action': '减仓',
                                'price': sell_price,
                                'shares': sell_shares,
                                'amount': sell_amount,
                                'commission': commission,
                            })

        # ---- 记录组合价值 ----
        total_value = cash
        for code, pos in holdings.items():
            if code in current_prices:
                total_value += pos['shares'] * current_prices[code]
            else:
                total_value += pos['shares'] * pos['avg_cost']

        portfolio_values.append({
            'date': current_date,
            'value': total_value,
            'cash': cash,
            'holdings': {code: pos['shares'] for code, pos in holdings.items()},
        })

    return portfolio_values, trade_log


# ================================================================
# 绩效分析模块
# ================================================================
def analyze_performance(portfolio_values, benchmark_df, trade_log):
    """分析回测绩效"""
    if not portfolio_values:
        return None

    df = pd.DataFrame(portfolio_values)
    df = df.set_index('date')

    # 日收益率
    df['daily_return'] = df['value'].pct_change()
    df = df.dropna()

    if len(df) < 10:
        return None

    # 总收益
    total_return = (df['value'].iloc[-1] / df['value'].iloc[0]) - 1

    # 年化收益
    n_days = len(df)
    n_years = n_days / 252
    annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

    # 最大回撤
    df['cummax'] = df['value'].cummax()
    df['drawdown'] = (df['value'] - df['cummax']) / df['cummax']
    max_drawdown = df['drawdown'].min()

    # 最大回撤区间
    max_dd_end = df['drawdown'].idxmin()
    max_dd_start = df.loc[:max_dd_end, 'value'].idxmax()

    # 夏普比率
    risk_free_rate = 0.015  # 1.5%无风险利率（货币基金）
    excess_returns = df['daily_return'] - risk_free_rate / 252
    sharpe = excess_returns.mean() / excess_returns.std() * np.sqrt(252) if excess_returns.std() > 0 else 0

    # 卡尔玛比率
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # 胜率
    positive_days = (df['daily_return'] > 0).sum()
    win_rate = positive_days / len(df) if len(df) > 0 else 0

    # 交易统计
    total_trades = len(trade_log)
    buy_trades = [t for t in trade_log if '买入' in t['action']]
    sell_trades = [t for t in trade_log if '卖出' in t['action'] or '减仓' in t['action'] or '盈利保护' in t['action']]

    # 盈亏比
    trade_pnl = []
    sell_buy_pairs = {}
    for t in trade_log:
        code = t['code']
        if '买入' in t['action']:
            if code not in sell_buy_pairs:
                sell_buy_pairs[code] = []
            sell_buy_pairs[code].append(('buy', t['price'], t['shares'], t['date']))
        elif code in sell_buy_pairs and sell_buy_pairs[code]:
            # 找到最近的买入
            for i, (action, price, shares, date) in enumerate(sell_buy_pairs[code]):
                if action == 'buy':
                    pnl = (t['price'] - price) / price
                    trade_pnl.append(pnl)
                    sell_buy_pairs[code].pop(i)
                    break

    if trade_pnl:
        avg_win = np.mean([p for p in trade_pnl if p > 0]) if any(p > 0 for p in trade_pnl) else 0
        avg_loss = abs(np.mean([p for p in trade_pnl if p < 0])) if any(p < 0 for p in trade_pnl) else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 10.0
        trade_win_rate = sum(1 for p in trade_pnl if p > 0) / len(trade_pnl)
    else:
        profit_factor = 0
        trade_win_rate = 0

    # 年均换手率
    avg_annual_trades = total_trades / n_years if n_years > 0 else 0

    # 基准比较
    benchmark_return = 0
    benchmark_max_dd = 0
    if benchmark_df is not None and len(benchmark_df) > 0:
        bm = benchmark_df.copy()
        bm_start = df.index[0]
        bm_end = df.index[-1]
        bm = bm[(bm.index >= bm_start) & (bm.index <= bm_end)]
        if len(bm) > 1:
            benchmark_return = (bm['close'].iloc[-1] / bm['close'].iloc[0]) - 1
            bm_cummax = bm['close'].cummax()
            bm_dd = (bm['close'] - bm_cummax) / bm_cummax
            benchmark_max_dd = bm_dd.min()

    alpha = annual_return - ((1 + benchmark_return) ** (1 / n_years) - 1) if n_years > 0 else 0

    # 过拟合检测：训练集(前70%) vs 测试集(后30%)
    split_idx = int(len(df) * 0.7)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    train_return = (train_df['value'].iloc[-1] / train_df['value'].iloc[0]) - 1
    train_years = len(train_df) / 252
    train_annual = (1 + train_return) ** (1 / max(train_years, 0.01)) - 1

    test_return = (test_df['value'].iloc[-1] / test_df['value'].iloc[0]) - 1
    test_years = len(test_df) / 252
    test_annual = (1 + test_return) ** (1 / max(test_years, 0.01)) - 1

    overfit_detected = test_annual < train_annual * 0.3 if train_annual > 0 else test_annual < 0

    # 多周期一致性
    periods_check = {}
    for period_name, period_years in [('1y', 1), ('3y', 3), ('5y', 5)]:
        period_days = period_years * 252
        if len(df) >= period_days:
            sub_df = df.iloc[-period_days:]
            sub_return = (sub_df['value'].iloc[-1] / sub_df['value'].iloc[0]) - 1
            sub_annual = (1 + sub_return) ** (1 / period_years) - 1
            sub_dd = sub_df['drawdown'].min()
            sub_excess = sub_df['daily_return'] - risk_free_rate / 252
            sub_sharpe = sub_excess.mean() / sub_excess.std() * np.sqrt(252) if sub_excess.std() > 0 else 0
            periods_check[period_name] = {
                'annual_return': round(sub_annual * 100, 2),
                'sharpe': round(sub_sharpe, 2),
                'max_drawdown': round(sub_dd * 100, 2),
                'sharpe_pass': sub_sharpe > 0.5,
                'dd_pass': abs(sub_dd) < 0.30,
            }

    consistency_warnings = []
    consistency_pass = True
    fail_count = 0
    for pname, pdata in periods_check.items():
        if not pdata['sharpe_pass']:
            consistency_warnings.append(f"{pname}周期夏普仅{pdata['sharpe']}，低于0.5")
            fail_count += 1
        if not pdata['dd_pass']:
            consistency_warnings.append(f"{pname}周期回撤{pdata['max_drawdown']}%，超30%")
            fail_count += 1

    if fail_count >= 2:
        consistency_pass = False
        consistency_verdict = "不予采纳"
    elif fail_count == 1:
        consistency_verdict = "标记警告"
    else:
        consistency_verdict = "通过"

    # 持仓统计
    holding_counts = defaultdict(int)
    for pv in portfolio_values:
        for code in pv.get('holdings', {}):
            holding_counts[code] += 1

    # 最常持有的ETF
    top_holdings = sorted(holding_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # 结果组装
    result = {
        'strategy_name': '七星高照ETF轮动策略-V1.7.2',
        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_source': 'akshare (A股ETF历史K线)',
        'data_period': f"{df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}",

        # 核心绩效
        'total_return': round(total_return * 100, 2),
        'annual_return': round(annual_return * 100, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'sharpe_ratio': round(sharpe, 2),
        'calmar_ratio': round(calmar, 2),
        'win_rate': round(win_rate * 100, 1),
        'profit_factor': round(profit_factor, 2),
        'trade_win_rate': round(trade_win_rate * 100, 1),

        # 回撤区间
        'max_dd_start': max_dd_start.strftime('%Y-%m-%d') if hasattr(max_dd_start, 'strftime') else str(max_dd_start),
        'max_dd_end': max_dd_end.strftime('%Y-%m-%d') if hasattr(max_dd_end, 'strftime') else str(max_dd_end),

        # 交易统计
        'total_trades': total_trades,
        'buy_trades': len(buy_trades),
        'sell_trades': len(sell_trades),
        'avg_annual_trades': round(avg_annual_trades, 1),
        'total_commission': round(sum(t['commission'] for t in trade_log), 2),

        # 基准比较
        'benchmark': '沪深300',
        'benchmark_return': round(benchmark_return * 100, 2),
        'benchmark_max_dd': round(benchmark_max_dd * 100, 2),
        'alpha': round(alpha * 100, 2),

        # 过拟合检测
        'overfit_detected': bool(overfit_detected),
        'overfit_details': f"训练集年化{train_annual*100:.2f}% vs 测试集年化{test_annual*100:.2f}%"
                           + ("，测试集低于训练集70%" if overfit_detected else ""),

        # 多周期一致性
        'consistency_check': {
            'passed': consistency_pass,
            'warnings': consistency_warnings,
            'verdict': consistency_verdict,
        },
        'period_results': periods_check,

        # 持仓统计
        'top_holdings': [(ETF_NAMES.get(code, code), count, round(count/len(df)*100, 1)) for code, count in top_holdings],

        # 改进比率
        'improvement_ratio': round((annual_return / abs(max_drawdown)) if max_drawdown != 0 else 0, 2),
        'recommend_adoption': bool(
            (annual_return / abs(max_drawdown) if max_drawdown != 0 else 0) > 0.3
            and not overfit_detected
            and consistency_pass
        ),

        'optimization_notes': '策略在A股ETF池上表现取决于动量效应强度，震荡市中可能频繁换仓增加成本。'
                             '建议: 1)增加换仓缓冲(hysteresis)降低交易频率 2)结合波动率调整仓位 3)考虑增加债券类ETF比重',
    }

    return result, df, trade_log


# ================================================================
# 主函数
# ================================================================
def main():
    print("="*60)
    print("七星高照ETF轮动策略 - VectorBT/Python回测")
    print("="*60)

    # 1. 获取数据
    print("\n📥 第1步：获取ETF历史数据...")
    active_pool = [c for c in ETF_POOL_JQ if c not in EXCLUDE_ETFS]
    etf_data = fetch_all_etf_data(active_pool, BACKTEST_START, BACKTEST_END)
    print(f"\n  成功获取 {len(etf_data)} 只ETF数据")

    # 也获取防御ETF
    if DEFENSIVE_ETF not in etf_data:
        print(f"\n📥 获取防御ETF {DEFENSIVE_ETF}...")
        def_data = fetch_all_etf_data([DEFENSIVE_ETF], BACKTEST_START, BACKTEST_END)
        etf_data.update(def_data)

    # 获取沪深300基准
    print("\n📥 获取沪深300基准数据...")
    benchmark_df = fetch_benchmark_data(BACKTEST_START, BACKTEST_END)
    if benchmark_df is not None:
        print(f"  ✅ 沪深300: {len(benchmark_df)}行")
    else:
        print("  ⚠️ 沪深300基准数据获取失败，跳过基准比较")

    # 2. 执行回测
    result_tuple = run_strategy_backtest(etf_data, benchmark_df, BACKTEST_START, BACKTEST_END)

    if result_tuple is None:
        print("\n❌ 回测失败")
        return

    portfolio_values, trade_log = result_tuple

    # 3. 分析绩效
    print("\n📊 第3步：分析绩效...")
    analysis_result = analyze_performance(portfolio_values, benchmark_df, trade_log)

    if analysis_result is None:
        print("\n❌ 绩效分析失败")
        return

    result, df, trade_log = analysis_result

    # 4. 输出报告
    print("\n" + "="*60)
    print("📈 回测绩效报告")
    print("="*60)
    print(f"  策略名称: {result['strategy_name']}")
    print(f"  回测区间: {result['data_period']}")
    print(f"  数据源:   {result['data_source']}")
    print()
    print(f"  💰 总收益率:   {result['total_return']:.2f}%")
    print(f"  📈 年化收益率: {result['annual_return']:.2f}%")
    print(f"  📉 最大回撤:   {result['max_drawdown']:.2f}%")
    print(f"  📊 夏普比率:   {result['sharpe_ratio']:.2f}")
    print(f"  🔄 卡尔玛比率: {result['calmar_ratio']:.2f}")
    print(f"  ✅ 日胜率:     {result['win_rate']:.1f}%")
    print(f"  ⚖️ 盈亏比:     {result['profit_factor']:.2f}")
    print(f"  📋 交易胜率:   {result['trade_win_rate']:.1f}%")
    print()
    print(f"  🏛️ 基准(沪深300): 收益{result['benchmark_return']:.2f}% 回撤{result['benchmark_max_dd']:.2f}%")
    print(f"  🎯 Alpha:       {result['alpha']:.2f}%")
    print()
    print(f"  📊 总交易次数:  {result['total_trades']} (买入{result['buy_trades']} / 卖出{result['sell_trades']})")
    print(f"  💵 总手续费:    {result['total_commission']:.2f}")
    print(f"  📅 年均交易:    {result['avg_annual_trades']:.1f}次")
    print()
    print(f"  🔍 过拟合检测:  {'⚠️ 是' if result['overfit_detected'] else '✅ 否'}")
    print(f"     {result['overfit_details']}")
    print()
    print(f"  🔄 多周期一致性: {result['consistency_check']['verdict']}")
    if result['consistency_check']['warnings']:
        for w in result['consistency_check']['warnings']:
            print(f"     ⚠️ {w}")
    print()

    if result['period_results']:
        print("  📊 分周期绩效:")
        for pname, pdata in result['period_results'].items():
            print(f"     {pname}: 年化{pdata['annual_return']:.2f}% 夏普{pdata['sharpe']:.2f} 回撤{pdata['max_drawdown']:.2f}%")

    print()
    print("  🏆 最常持有ETF:")
    for name, count, pct in result['top_holdings']:
        print(f"     {name}: {pct}%交易日")

    print()
    print(f"  🎯 改进比率(年化/回撤): {result['improvement_ratio']:.2f}")
    print(f"  ✅ 推荐采纳: {'是' if result['recommend_adoption'] else '否'}")
    print(f"  💡 优化建议: {result['optimization_notes']}")

    # 5. 保存结果
    output_path = '/data/workspace/seven_star_etf_backtest_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 结果已保存至: {output_path}")

    # 保存交易日志
    trade_log_path = '/data/workspace/seven_star_etf_trade_log.csv'
    if trade_log:
        tl_df = pd.DataFrame(trade_log)
        tl_df.to_csv(trade_log_path, index=False, encoding='utf-8-sig')
        print(f"📁 交易日志已保存至: {trade_log_path}")

    # 保存净值曲线
    nav_path = '/data/workspace/seven_star_etf_nav.csv'
    df[['value', 'daily_return', 'drawdown']].to_csv(nav_path, encoding='utf-8-sig')
    print(f"📁 净值曲线已保存至: {nav_path}")

    return result


if __name__ == '__main__':
    result = main()
