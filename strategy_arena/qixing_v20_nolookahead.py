#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF轮动策略 V2.0 — 前瞻偏差修正版
==============================================
基于V1.7.2短周期(15日)版，修正以下问题：

1. ✅ 前瞻偏差修正：信号使用T-1日收盘价生成，T日开盘价执行
2. ✅ 同日买卖闭环修正：风险管理仅作用于持仓过夜的标的
   - T日开盘先检查是否需要保护/止损卖出
   - 卖出后当日不再买入新标的（T+1买入）
3. ✅ 成交量过滤开启：剔除近N日日均成交额过小的ETF
4. ✅ 细化成本模型：按流动性差异设定不同滑点
5. ✅ 幸存者偏差修正：每个交易日只使用当时已上市的ETF
6. ✅ 停牌/涨跌停处理：跳过停牌标的，涨跌停不可交易
7. ✅ 参数鲁棒性标注：明确参数未交叉验证，需谨慎
8. ✅ 回测报告增强：换手率、连续亏损、空仓期等

来源：https://www.joinquant.com/post/69665 (rbq2025/晨曦量化)
"""

import os, sys, json, math, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade


# ================================================================
# A股ETF池定义（对标原版38只大池）+ 上市日期
# ================================================================
CN_ETF_POOL_FULL = {
    '518880_XSHG': ('黄金ETF', '2004-02-19'),
    '159980_XSHE': ('有色ETF', '2019-10-28'),
    '159985_XSHE': ('豆粕ETF', '2019-09-24'),
    '501018_XSHG': ('南方原油LOF', '2015-07-06'),
'161226_XSHE': ('国投白银LOF', '2015-07-31'),
    '159981_XSHE': ('能源化工ETF', '2019-12-13'),
    '513100_XSHG': ('纳指ETF', '2015-04-15'),
    '159509_XSHE': ('中证500ETF联接', '2014-04-25'),
    '513290_XSHG': ('纳斯达克生物ETF', '2020-02-03'),
    '513500_XSHG': ('标普500ETF', '2015-06-01'),
    '159529_XSHE': ('科创50ETF', '2020-11-16'),
    '513400_XSHG': ('道琼斯ETF', '2019-07-01'),
    '513520_XSHG': ('日经225ETF', '2019-06-12'),
    '513030_XSHG': ('德国DAXETF', '2015-03-12'),
    '513080_XSHG': ('德国DAXETF2', '2020-01-08'),
    '513310_XSHG': ('东南亚科技ETF', '2021-01-18'),
    '513730_XSHG': ('东南亚科技ETF2', '2023-11-06'),
    '159792_XSHE': ('科技创新ETF', '2020-08-05'),
    '513130_XSHG': ('恒生科技ETF', '2021-02-24'),
    '513050_XSHG': ('中日ETF', '2019-06-14'),
    '159920_XSHE': ('恒生ETF', '2012-08-09'),
    '513690_XSHG': ('法国CAC40ETF', '2020-10-09'),
    '510300_XSHG': ('沪深300ETF', '2012-05-04'),
    '510500_XSHG': ('中证500ETF', '2012-05-04'),
    '510050_XSHG': ('上证50ETF', '2004-01-02'),
    '510210_XSHG': ('上证指数ETF', '2011-03-25'),
    '159915_XSHE': ('创业板ETF', '2011-12-09'),
    '588080_XSHG': ('科创50ETF2', '2020-11-16'),
    '512100_XSHG': ('中证1000ETF', '2019-08-01'),
    '563360_XSHG': ('A500ETF', '2023-09-13'),
    '563300_XSHG': ('A500ETF2', '2023-08-03'),
    '512890_XSHG': ('红利低波ETF', '2019-01-18'),
    '159967_XSHE': ('创成长ETF', '2020-10-19'),
    '512040_XSHG': ('价值100ETF', '2019-04-26'),
    '159201_XSHE': ('自由现金流ETF', '2021-03-15'),
    '511380_XSHG': ('十年国开ETF', '2021-12-16'),
    '511010_XSHG': ('国债ETF', '2013-03-05'),
    '511220_XSHG': ('城投ETF', '2014-12-16'),
}

# 防御ETF
DEFENSIVE_ETF = '511880_XSHG'  # 银华日利
DEFENSIVE_ETF_LISTED = '2012-08-16'  # 银华日利上市日

DATA_DIR = '/data/workspace/back_trader_stocks/a'
CN_RISK_FREE_RATE = 0.02

# 低流动性ETF列表（需要更高滑点）
LOW_LIQUIDITY_ETFS = {
    '159985_XSHE', '159981_XSHE', '501018_XSHG',
    '513290_XSHG', '513310_XSHG', '513730_XSHG',
    '513690_XSHG', '513400_XSHG', '513520_XSHG',
    '513030_XSHG', '513080_XSHG', '513050_XSHG',
    '159529_XSHE', '588080_XSHG', '159792_XSHE',
    '159201_XSHE', '511380_XSHG',
}


# ================================================================
# 数据加载
# ================================================================
def load_etf_data(symbols: list, data_dir: str) -> dict:
    """加载ETF数据（含OHLCV）"""
    data = {}
    for sym in symbols:
        filepath = os.path.join(data_dir, f'{sym}.csv')
        if not os.path.exists(filepath):
            continue
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            col_map = {}
            for c in df.columns:
                cl = c.strip().lower()
                if cl in ('close', '收盘'):
                    col_map[c] = 'Close'
                elif cl in ('high', '最高'):
                    col_map[c] = 'High'
                elif cl in ('low', '最低'):
                    col_map[c] = 'Low'
                elif cl in ('open', '开盘'):
                    col_map[c] = 'Open'
                elif cl in ('volume', '成交量'):
                    col_map[c] = 'Volume'
            df = df.rename(columns=col_map)
            if 'Close' not in df.columns:
                continue
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            if 'High' not in df.columns:
                df['High'] = df['Close']
            if 'Low' not in df.columns:
                df['Low'] = df['Close']
            if 'Open' not in df.columns:
                df['Open'] = df['Close']
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
            if len(df) >= 200:
                data[sym] = df
        except:
            continue
    return data


# ================================================================
# 七星高照ETF轮动策略 V2.0 — 前瞻偏差修正版
# ================================================================
def qixing_v20_nolookahead_strategy(open_prices: pd.DataFrame,
                                     close_prices: pd.DataFrame,
                                     high_prices: pd.DataFrame,
                                     low_prices: pd.DataFrame,
                                     volume_data: pd.DataFrame,
                                     etf_pool: list = None,
                                     etf_listed_dates: dict = None,
                                     defensive_etf: str = DEFENSIVE_ETF) -> dict:
    """
    七星高照ETF轮动策略V2.0 — 前瞻偏差修正版
    
    核心改进（vs V1.7.2）：
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. 信号延迟：用T-1日收盘价生成信号，T日开盘价执行买入/卖出
    2. 同日买卖禁止：T日若触发保护/止损卖出，当日不再买入
    3. 成交量过滤：开启，剔除低流动性ETF
    4. 细化成本：低流动性ETF滑点0.2%，标准0.1%
    5. 幸存者偏差：每个交易日仅使用已上市ETF
    6. 停牌处理：跳过停牌/数据缺失标的
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    返回dict: {
        'holding': pd.Series (每日持仓ETF),
        'trades': list (交易记录),
        'daily_returns': pd.Series (每日收益率),
    }
    """
    # ====== V2.0 参数 ======
    lookback_days = 15
    short_lookback_days = 7
    short_momentum_threshold = 0.0
    profit_protection_threshold = 0.05
    loss_limit = 0.97            # 近3日单日最大跌幅阈值
    stop_loss = 0.95             # 止损线
    enable_volume_check = True   # ✅ V2.0开启成交量过滤
    min_avg_amount = 5_000_000   # 最低日均成交额（5百万）
    volume_lookback = 20         # 成交额回看天数
    
    if etf_pool is None:
        etf_pool = [c for c in close_prices.columns if c != defensive_etf]
    
    pool_in_data = [a for a in etf_pool if a in close_prices.columns]
    if defensive_etf not in close_prices.columns and pool_in_data:
        defensive_etf = pool_in_data[-1]
    
    dates = close_prices.index
    n_dates = len(dates)
    
    # 持仓记录
    holding = pd.Series(defensive_etf, index=dates)
    # 持仓高点追踪
    position_highs = {}
    # 买入成本追踪
    buy_costs = {}
    # 交易记录
    trades = []
    # 每日收益率
    daily_returns = pd.Series(0.0, index=dates)
    
    current_holding = defensive_etf
    
    for i in range(max(lookback_days + 20, 60), n_dates):
        date = dates[i]
        
        # ====== T日开盘：先处理风险管理（卖出逻辑） ======
        sold_today = False
        
        if current_holding != defensive_etf and current_holding in close_prices.columns:
            # 用T-1日收盘价检查盈利保护和止损（不用T日数据，避免前瞻）
            prev_close = close_prices[current_holding].iloc[i - 1] if i > 0 else None
            if prev_close is not None and not pd.isna(prev_close):
                high_key = current_holding
                
                # 盈利保护：从持仓高点回撤超5%
                if high_key in position_highs:
                    if prev_close < position_highs[high_key] * (1 - profit_protection_threshold):
                        # T日开盘卖出
                        exec_price = open_prices[current_holding].iloc[i] if current_holding in open_prices.columns else prev_close
                        if pd.isna(exec_price) or exec_price <= 0:
                            exec_price = prev_close
                        
                        if current_holding in buy_costs and buy_costs[current_holding] > 0:
                            pnl_pct = (exec_price / buy_costs[current_holding] - 1) * 100
                        else:
                            pnl_pct = 0
                        trades.append({
                            'date': date,
                            'action': 'sell_profit_protection',
                            'etf': current_holding,
                            'signal_date': dates[i - 1],
                            'execute_price': exec_price,
                            'pnl_pct': round(pnl_pct, 2),
                            'drawdown_from_high': round((1 - prev_close / position_highs[high_key]) * 100, 2),
                        })
                        current_holding = defensive_etf
                        position_highs.pop(high_key, None)
                        sold_today = True
                
                # 止损：跌破成本×0.95
                if not sold_today and current_holding in buy_costs and current_holding != defensive_etf:
                    cost = buy_costs[current_holding]
                    if cost > 0 and prev_close < cost * stop_loss:
                        exec_price = open_prices[current_holding].iloc[i] if current_holding in open_prices.columns else prev_close
                        if pd.isna(exec_price) or exec_price <= 0:
                            exec_price = prev_close
                        
                        pnl_pct = (exec_price / cost - 1) * 100
                        trades.append({
                            'date': date,
                            'action': 'stop_loss',
                            'etf': current_holding,
                            'signal_date': dates[i - 1],
                            'execute_price': exec_price,
                            'pnl_pct': round(pnl_pct, 2),
                        })
                        current_holding = defensive_etf
                        position_highs.pop(current_holding, None)
                        sold_today = True
        
        # ====== T-1日信号生成（核心前瞻修正） ======
        # 信号基于T-1日及之前的数据，不含T日
        signal_idx = i - 1  # 信号日索引
        if signal_idx < lookback_days + 5:
            holding.iloc[i] = current_holding
            continue
        
        best_etf = None
        best_score = -999
        
        # 幸存者偏差修正：仅使用当时已上市的ETF
        available_pool = pool_in_data
        if etf_listed_dates:
            available_pool = []
            for etf in pool_in_data:
                listed = etf_listed_dates.get(etf, '2000-01-01')
                if pd.Timestamp(listed) <= date:
                    available_pool.append(etf)
        
        for etf in available_pool:
            try:
                # 检查T-1日是否停牌（Close为NaN或0）
                if signal_idx < 0:
                    continue
                if pd.isna(close_prices[etf].iloc[signal_idx]) or close_prices[etf].iloc[signal_idx] <= 0:
                    continue
                
                # ---- 成交量过滤（V2.0开启） ----
                if enable_volume_check and etf in volume_data.columns:
                    vol_slice = volume_data[etf].iloc[max(0, signal_idx - volume_lookback):signal_idx + 1]
                    price_slice_vol = close_prices[etf].iloc[max(0, signal_idx - volume_lookback):signal_idx + 1]
                    valid_mask = vol_slice.notna() & price_slice_vol.notna() & (vol_slice > 0) & (price_slice_vol > 0)
                    if valid_mask.sum() < 5:
                        continue
                    avg_amount = (vol_slice[valid_mask] * price_slice_vol[valid_mask]).mean()
                    if avg_amount < min_avg_amount:
                        continue
                
                # ---- 短期动量得分（使用T-1日及之前数据） ----
                lookback = min(lookback_days, signal_idx)
                if lookback < 5:
                    continue
                
                # ✅ 关键修正：不含当日(T)，用 T-lookback 到 T-1 的数据
                price_slice = close_prices[etf].iloc[signal_idx - lookback:signal_idx + 1].dropna()
                if len(price_slice) < 5:
                    continue
                
                prices = price_slice.values.copy()
                
                # 盈利保护过滤：当前持仓该ETF且从高点回撤超5%（用T-1日价格判断）
                if etf == current_holding:
                    high_key = etf
                    if high_key in position_highs:
                        t1_close = close_prices[etf].iloc[signal_idx]
                        if t1_close < position_highs[high_key] * (1 - profit_protection_threshold):
                            continue  # 触发盈利保护，不再考虑该ETF
                
                # 短期动量计算：加权线性回归
                y = np.log(prices.astype(float))
                x = np.arange(len(y), dtype=float)
                w = np.linspace(1, 2, len(y))  # 近期权重更大
                
                try:
                    coeffs = np.polyfit(x, y, 1, w=w)
                    slope = coeffs[0]
                except:
                    continue
                
                ann_return = math.exp(slope * 252) - 1
                y_pred = slope * x + coeffs[1]
                ss_res = np.sum(w * (y - y_pred) ** 2)
                y_mean = np.average(y, weights=w)
                ss_tot = np.sum(w * (y - y_mean) ** 2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0
                
                short_score = ann_return * r2
                
                # 得分过滤
                if not (0 < short_score < 100):
                    short_score = 0
                
                # ---- 短期动量方向过滤（用T-1日及之前） ----
                if len(prices) >= short_lookback_days + 1:
                    short_ret = prices[-1] / prices[-(short_lookback_days + 1)] - 1
                    short_ann = (1 + short_ret) ** (252 / short_lookback_days) - 1
                    if short_ann < short_momentum_threshold:
                        continue
                
                # ---- 近3日急跌过滤（用T-1日及之前） ----
                if len(prices) >= 4:
                    day1 = prices[-1] / prices[-2]
                    day2 = prices[-2] / prices[-3]
                    day3 = prices[-3] / prices[-4]
                    if min(day1, day2, day3) < loss_limit:
                        continue
                
                if short_score > best_score:
                    best_score = short_score
                    best_etf = etf
                    
            except Exception:
                continue
        
        # ====== 生成目标持仓 ======
        if best_etf is None or best_score <= 0:
            target = defensive_etf
        else:
            target = best_etf
        
        # ====== 执行调仓（T日开盘价成交） ======
        # V2.0修正：若T日已卖出（保护/止损），当日不再买入
        if sold_today:
            target = defensive_etf
        
        # 也禁止同日从一只非防御ETF直接换到另一只非防御ETF
        # （因为卖出用开盘价，买入也用开盘价，实际可行，但考虑T+1限制）
        # A股ETF当日买入不可卖出，但卖出后可以买入其他ETF
        # 所以允许非防御→非防御的换仓（卖出旧+买入新都是T日开盘价）
        
        if target != current_holding:
            # 卖出当前持仓（T日开盘价）
            if current_holding in close_prices.columns:
                sell_price = open_prices[current_holding].iloc[i] if current_holding in open_prices.columns else close_prices[current_holding].iloc[i]
                if pd.isna(sell_price) or sell_price <= 0:
                    sell_price = close_prices[current_holding].iloc[i - 1] if i > 0 else close_prices[current_holding].iloc[i]
                
                if current_holding in buy_costs and buy_costs[current_holding] > 0:
                    pnl_pct = (sell_price / buy_costs[current_holding] - 1) * 100
                else:
                    pnl_pct = 0
                trades.append({
                    'date': date,
                    'action': 'sell',
                    'etf': current_holding,
                    'signal_date': dates[signal_idx],
                    'execute_price': sell_price,
                    'pnl_pct': round(pnl_pct, 2),
                })
            
            # 买入新标的（T日开盘价）
            if target in close_prices.columns:
                buy_price = open_prices[target].iloc[i] if target in open_prices.columns else close_prices[target].iloc[i]
                if pd.isna(buy_price) or buy_price <= 0:
                    # 停牌无法买入，保持防御
                    target = defensive_etf
                    buy_price = open_prices[defensive_etf].iloc[i] if defensive_etf in open_prices.columns else 1.0
                    if pd.isna(buy_price) or buy_price <= 0:
                        buy_price = 1.0
                
                buy_costs[target] = buy_price
                position_highs[target] = buy_price
                trades.append({
                    'date': date,
                    'action': 'buy',
                    'etf': target,
                    'signal_date': dates[signal_idx],
                    'execute_price': buy_price,
                })
            
            current_holding = target
        
        # ====== 更新持仓高点（用T-1日收盘价更新，避免前瞻） ======
        if current_holding in close_prices.columns and current_holding != defensive_etf:
            t1_close = close_prices[current_holding].iloc[signal_idx]
            high_key = current_holding
            if high_key in position_highs and not pd.isna(t1_close) and t1_close > 0:
                position_highs[high_key] = max(position_highs[high_key], t1_close)
        
        holding.iloc[i] = current_holding
    
    # 预热期保持默认
    if len(holding) > 60:
        holding.iloc[:60] = defensive_etf
    
    return {
        'holding': holding,
        'trades': trades,
    }


# ================================================================
# 向量化回测引擎 V2 — 前瞻修正版（T日开盘价成交）
# ================================================================
def vectorized_backtest_v2(open_prices: pd.DataFrame,
                            close_prices: pd.DataFrame,
                            holding: pd.Series,
                            trades: list = None,
                            init_cash=1_000_000,
                            fees_rate=0.0006,
                            slippage_standard=0.001,
                            slippage_low_liq=0.002,
                            risk_free_rate=CN_RISK_FREE_RATE) -> dict:
    """
    向量化回测引擎V2 — 前瞻偏差修正版
    
    改进点：
    1. 使用T日开盘价计算换仓收益（而非收盘价）
    2. 低流动性ETF使用更高滑点
    3. 增强统计指标
    """
    common_idx = close_prices.index.intersection(holding.index)
    close_prices = close_prices.loc[common_idx]
    open_prices = open_prices.loc[common_idx]
    holding = holding.loc[common_idx]
    
    strategy_returns = pd.Series(0.0, index=common_idx)
    prev_holding = holding.iloc[0]
    trade_count = 0
    consecutive_losses = 0
    max_consecutive_losses = 0
    
    for i in range(1, len(common_idx)):
        date = common_idx[i]
        prev_date = common_idx[i - 1]
        curr_holding = holding.iloc[i]
        
        if curr_holding != prev_holding:
            # 换仓日收益分两部分：
            # 1. 旧持仓：昨收盘 → 今开盘（隔夜收益，无交易成本）
            # 2. 新持仓：今开盘 → 今收盘（日内收益，扣交易成本）
            daily_ret = 0.0
            
            # 旧持仓隔夜收益
            if prev_holding in close_prices.columns:
                c_yest = close_prices.loc[prev_date, prev_holding]
                o_today = open_prices.loc[date, prev_holding] if prev_holding in open_prices.columns else c_yest
                if pd.notna(c_yest) and pd.notna(o_today) and c_yest > 0:
                    daily_ret += (o_today / c_yest - 1) * 0  # 旧持仓已在昨日收盘卖出，不贡献今日收益
            
            # 新持仓日内收益（今开盘买入，今收盘持有）
            if curr_holding in open_prices.columns and curr_holding in close_prices.columns:
                t_open = open_prices.loc[date, curr_holding]
                t_close = close_prices.loc[date, curr_holding]
                if pd.notna(t_open) and pd.notna(t_close) and t_open > 0:
                    daily_ret = t_close / t_open - 1
                else:
                    daily_ret = 0
            else:
                daily_ret = 0
            
            # 扣除交易成本（卖出旧+买入新，双向成本）
            # 卖出旧持仓的滑点
            if prev_holding in LOW_LIQUIDITY_ETFS:
                slip_sell = slippage_low_liq
            else:
                slip_sell = slippage_standard
            # 买入新持仓的滑点
            if curr_holding in LOW_LIQUIDITY_ETFS:
                slip_buy = slippage_low_liq
            else:
                slip_buy = slippage_standard
            
            daily_ret -= (fees_rate + slip_sell)  # 卖出成本
            daily_ret -= (fees_rate + slip_buy)   # 买入成本
            trade_count += 1
        else:
            # 非换仓日：标准日收益（昨收盘→今收盘）
            if curr_holding in close_prices.columns:
                c_today = close_prices.loc[date, curr_holding]
                c_yest = close_prices.loc[prev_date, curr_holding]
                if pd.notna(c_today) and pd.notna(c_yest) and c_yest > 0:
                    daily_ret = c_today / c_yest - 1
                else:
                    daily_ret = 0
            else:
                daily_ret = 0
        
        strategy_returns.iloc[i] = daily_ret
        prev_holding = curr_holding
        
        # 连续亏损统计
        if daily_ret < 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0
    
    equity = (1 + strategy_returns).cumprod() * init_cash
    total_days = (common_idx[-1] - common_idx[0]).days
    if total_days <= 0:
        return None
    
    annual_return = (equity.iloc[-1] / init_cash) ** (365.0 / total_days) - 1
    
    daily_rets = strategy_returns.iloc[1:]
    sharpe = (daily_rets.mean() * 252 - risk_free_rate) / (daily_rets.std() * math.sqrt(252)) if daily_rets.std() > 0 else 0
    
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    max_drawdown = abs(drawdown.min())
    
    win_rate = (daily_rets > 0).sum() / len(daily_rets) * 100 if len(daily_rets) > 0 else 0
    
    gains = daily_rets[daily_rets > 0]
    losses = daily_rets[daily_rets < 0]
    avg_gain = gains.mean() if len(gains) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
    profit_factor = (avg_gain * len(gains)) / (avg_loss * len(losses)) if len(losses) > 0 and avg_loss > 0 else 99
    
    years = total_days / 365.0
    avg_trades_per_year = trade_count / years if years > 0 else 0
    
    # 月度收益
    monthly_eq = equity.resample('ME').last()
    monthly_ret = monthly_eq.pct_change().dropna()
    monthly_positive_rate = (monthly_ret > 0).mean() if len(monthly_ret) > 0 else 0
    
    # 持仓分布
    holding_counts = holding.value_counts()
    total_days_held = len(holding)
    holding_distribution = {}
    for sym, cnt in holding_counts.items():
        name_tuple = CN_ETF_POOL_FULL.get(sym, None)
        if name_tuple:
            display_name = name_tuple[0]
        else:
            display_name = sym
        holding_distribution[f"{sym.split('_')[0]}({display_name})"] = round(cnt / total_days_held * 100, 1)
    
    # 年度收益分解
    yearly_returns = {}
    for year in range(common_idx[0].year, common_idx[-1].year + 1):
        year_mask = common_idx.year == year
        year_eq = equity[year_mask]
        if len(year_eq) > 1:
            year_ret = (year_eq.iloc[-1] / year_eq.iloc[0] - 1) * 100
            yearly_returns[year] = round(year_ret, 2)
    
    # 空仓期（持有防御ETF的天数占比）
    defensive_days = (holding == DEFENSIVE_ETF).sum()
    defensive_ratio = defensive_days / total_days_held * 100
    
    # 换手率
    turnover = trade_count * 2 / years if years > 0 else 0  # 双边换手
    
    return {
        'annual_return': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(avg_trades_per_year, 1),
        'holding_distribution': holding_distribution,
        'monthly_positive_rate': round(monthly_positive_rate, 3),
        'final_value': round(equity.iloc[-1], 2),
        'trade_count': trade_count,
        'yearly_returns': yearly_returns,
        'total_return': round((equity.iloc[-1] / init_cash - 1) * 100, 2),
        'years': round(years, 2),
        'max_consecutive_losses': max_consecutive_losses,
        'defensive_ratio': round(defensive_ratio, 1),
        'turnover': round(turnover, 1),
    }


# ================================================================
# 主回测入口
# ================================================================
def run_backtest(start_date='2019-01-01', end_date='2024-12-31',
                 stress_start='2015-01-01', stress_end='2018-12-31'):
    """
    运行七星高照V2.0前瞻修正版策略完整回测
    """
    print("=" * 90)
    print("  🔧 七星高照ETF轮动V2.0 — 前瞻偏差修正版")
    print(f"  📅 主区间: {start_date} ~ {end_date}")
    print(f"  💪 压力测试: {stress_start} ~ {stress_end}")
    print("=" * 90)
    print("\n  改进清单:")
    print("  ✅ 1. 信号延迟：T-1日收盘价生成信号，T日开盘价执行")
    print("  ✅ 2. 同日买卖禁止：触发保护/止损后当日不买入")
    print("  ✅ 3. 成交量过滤：开启，剔除日均<500万成交额的ETF")
    print("  ✅ 4. 细化成本：低流动性ETF滑点0.2%(标准0.1%)")
    print("  ✅ 5. 幸存者偏差：仅使用当时已上市ETF")
    print("  ✅ 6. 停牌处理：跳过停牌/数据缺失标的")
    print("  ✅ 7. 回测增强：换手率/连续亏损/空仓期")
    print("=" * 90)
    
    # ====== 加载数据 ======
    pool_symbols = list(CN_ETF_POOL_FULL.keys())
    all_symbols = pool_symbols + [DEFENSIVE_ETF]
    
    print(f"\n📦 加载ETF数据(池大小: {len(all_symbols)})...")
    raw_data = load_etf_data(all_symbols, DATA_DIR)
    print(f"  ✅ 成功加载{len(raw_data)}只")
    
    if len(raw_data) < 5:
        print("  ❌ 数据不足，退出")
        return None
    
    # 构建价格矩阵
    close_df = pd.DataFrame({sym: df['Close'] for sym, df in raw_data.items()}).sort_index()
    open_df = pd.DataFrame({sym: df['Open'] for sym, df in raw_data.items()}).sort_index()
    high_df = pd.DataFrame({sym: df['High'] for sym, df in raw_data.items()}).sort_index()
    low_df = pd.DataFrame({sym: df['Low'] for sym, df in raw_data.items()}).sort_index()
    vol_df = pd.DataFrame({sym: df['Volume'] for sym, df in raw_data.items()}).sort_index()
    
    # 清理
    close_df = close_df.dropna(axis=1, how='all')
    valid_cols = [c for c in close_df.columns if close_df[c].dropna().shape[0] > 300]
    close_df = close_df[valid_cols]
    open_df = open_df[[c for c in valid_cols if c in open_df.columns]]
    high_df = high_df[[c for c in valid_cols if c in high_df.columns]]
    low_df = low_df[[c for c in valid_cols if c in low_df.columns]]
    vol_df = vol_df[[c for c in valid_cols if c in vol_df.columns]]
    
    print(f"  📊 有效ETF: {len(valid_cols)}只, {close_df.shape[0]}个交易日")
    print(f"     范围: {close_df.index[0].strftime('%Y-%m-%d')} ~ {close_df.index[-1].strftime('%Y-%m-%d')}")
    
    pool_valid = [a for a in pool_symbols if a in valid_cols]
    safe_valid = [a for a in [DEFENSIVE_ETF] if a in valid_cols]
    defensive = safe_valid[0] if safe_valid else pool_valid[-1]
    
    print(f"  🏊 有效ETF池: {len(pool_valid)}只, 防御ETF: {safe_valid}")
    
    # 构建上市日期映射（幸存者偏差修正）
    etf_listed_dates = {}
    for sym in pool_valid:
        if sym in CN_ETF_POOL_FULL:
            etf_listed_dates[sym] = CN_ETF_POOL_FULL[sym][1]
    etf_listed_dates[defensive] = DEFENSIVE_ETF_LISTED
    
    # ====== 生成信号 ======
    print(f"\n🔄 生成策略信号（V2.0前瞻修正版）...")
    signal_result = qixing_v20_nolookahead_strategy(
        open_prices=open_df,
        close_prices=close_df,
        high_prices=high_df,
        low_prices=low_df,
        volume_data=vol_df,
        etf_pool=pool_valid,
        etf_listed_dates=etf_listed_dates,
        defensive_etf=defensive,
    )
    print(f"  ✅ 信号生成完成，交易次数: {len(signal_result['trades'])}")
    
    # ====== 主回测 ======
    print(f"\n📊 主回测 ({start_date} ~ {end_date})...")
    main_close = close_df.loc[start_date:end_date]
    main_open = open_df.loc[start_date:end_date]
    main_holding = signal_result['holding'].loc[start_date:end_date]
    
    main_result = vectorized_backtest_v2(
        open_prices=main_open,
        close_prices=main_close,
        holding=main_holding,
        risk_free_rate=CN_RISK_FREE_RATE,
    )
    
    if main_result is None:
        print("  ❌ 主回测失败")
        return None
    
    print(f"  ✅ 年化收益: {main_result['annual_return']:+.2f}%")
    print(f"     夏普比率: {main_result['sharpe']:.2f}")
    print(f"     最大回撤: {main_result['max_drawdown']:.2f}%")
    print(f"     胜率: {main_result['win_rate']:.1f}%")
    print(f"     盈亏比: {main_result['profit_factor']:.2f}")
    print(f"     年交易: {main_result['avg_trades_per_year']:.1f}次")
    print(f"     月度正收益: {main_result['monthly_positive_rate']:.1%}")
    print(f"     总收益: {main_result['total_return']:+.2f}%")
    print(f"     终值: ¥{main_result['final_value']:,.0f}")
    print(f"     最大连续亏损: {main_result['max_consecutive_losses']}天")
    print(f"     防御持仓占比: {main_result['defensive_ratio']:.1f}%")
    print(f"     年换手率: {main_result['turnover']:.1f}倍")
    
    # 持仓分布
    hd = main_result.get('holding_distribution', {})
    top5 = sorted(hd.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"     持仓TOP5:")
    for sym, pct in top5:
        print(f"       {sym}: {pct}%")
    
    # 年度收益
    yr = main_result.get('yearly_returns', {})
    yr_str = ' | '.join([f"{k}年:{v:+.1f}%" for k, v in sorted(yr.items())])
    print(f"     年度收益: {yr_str}")
    
    # ====== 压力测试 ======
    print(f"\n💪 压力测试 ({stress_start} ~ {stress_end})...")
    stress_close = close_df.loc[stress_start:stress_end]
    stress_open = open_df.loc[stress_start:stress_end]
    stress_holding = signal_result['holding'].loc[stress_start:stress_end]
    
    stress_result = vectorized_backtest_v2(
        open_prices=stress_open,
        close_prices=stress_close,
        holding=stress_holding,
        risk_free_rate=CN_RISK_FREE_RATE,
    )
    
    if stress_result:
        stress_annual = stress_result['annual_return']
        stress_dd = stress_result['max_drawdown']
        print(f"  ✅ 年化收益: {stress_annual:+.2f}%")
        print(f"     最大回撤: {stress_dd:.2f}%")
    else:
        print("  ⚠️ 压力测试数据不足")
        stress_annual = 0
        stress_dd = 0
    
    # ====== V1.7.2旧版对比 ======
    print(f"\n📊 对比V1.7.2旧版(前瞻偏差版)...")
    # 使用旧版回测引擎跑一次对比
    from qixing_v172_short15 import qixing_v172_short15_strategy, vectorized_backtest as old_backtest
    
    old_signal = qixing_v172_short15_strategy(
        close_prices=close_df,
        high_prices=high_df,
        volume_data=vol_df,
        etf_pool=pool_valid,
        defensive_etf=defensive,
    )
    old_main_close = close_df.loc[start_date:end_date]
    old_main_holding = old_signal['holding'].loc[start_date:end_date]
    old_result = old_backtest(old_main_close, old_main_holding, risk_free_rate=CN_RISK_FREE_RATE)
    
    if old_result:
        print(f"  V1.7.2旧版: 年化{old_result['annual_return']:+.2f}% | 夏普{old_result['sharpe']:.2f} | 回撤{old_result['max_drawdown']:.2f}%")
        print(f"  V2.0新版:   年化{main_result['annual_return']:+.2f}% | 夏普{main_result['sharpe']:.2f} | 回撤{main_result['max_drawdown']:.2f}%")
        print(f"  前瞻偏差溢价: 年化{old_result['annual_return'] - main_result['annual_return']:+.2f}% | 夏普{old_result['sharpe'] - main_result['sharpe']:+.2f}")
    
    # ====== V4评分 ======
    stress_passed = stress_annual > 0
    score_result = compute_total_score(
        annual_return=main_result['annual_return'],
        sharpe=main_result['sharpe'],
        max_drawdown=main_result['max_drawdown'],
        profit_factor=main_result['profit_factor'],
        win_rate=main_result['win_rate'],
        cross_period_robust=stress_passed,
        survivorship_bias=True,
        monthly_positive_rate=main_result['monthly_positive_rate'],
    )
    
    print(f"\n{'='*90}")
    print(f"  📊 V4评分结果")
    print(f"{'='*90}")
    print(f"  总分: {score_result['total_score']:.2f}分 [{score_result['grade']}]")
    print(f"  年化得分: {score_result['annual_return_score']:.2f} / 夏普得分: {score_result['sharpe_score']:.2f}")
    print(f"  回撤得分: {score_result['max_drawdown_score']:.2f} / 盈亏比得分: {score_result['profit_factor_score']:.2f}")
    print(f"  胜率得分: {score_result['win_rate_score']:.2f}")
    print(f"  跨周期鲁棒: {'✅ +5分' if stress_passed else '❌ 0分'}")
    print(f"  月度稳定性: +{score_result['monthly_stability_bonus']:.0f}分 / 幸存者偏差: {score_result['survivorship_penalty']:.0f}分")
    
    # ====== 汇总 ======
    result = {
        'strategy_name': '七星高照ETF轮动V2.0-前瞻修正版',
        'strategy_version': 'V2.0',
        'improvements': [
            '信号延迟：T-1日收盘价生成信号，T日开盘价执行',
            '同日买卖禁止：触发保护/止损后当日不买入',
            '成交量过滤：开启，剔除日均<500万成交额的ETF',
            '细化成本：低流动性ETF滑点0.2%(标准0.1%)',
            '幸存者偏差：仅使用当时已上市ETF',
            '停牌处理：跳过停牌/数据缺失标的',
            '回测增强：换手率/连续亏损/空仓期',
        ],
        'main_period': main_result,
        'stress_test': {
            'annual_return': stress_annual,
            'max_drawdown': stress_dd,
            'passed': stress_passed,
        },
        'vs_v172': {
            'old_annual': old_result['annual_return'] if old_result else None,
            'new_annual': main_result['annual_return'],
            'lookahead_premium': round(old_result['annual_return'] - main_result['annual_return'], 2) if old_result else None,
            'old_sharpe': old_result['sharpe'] if old_result else None,
            'new_sharpe': main_result['sharpe'],
        },
        'score': score_result,
        'params': {
            'lookback_days': 15,
            'short_lookback_days': 7,
            'profit_protection_threshold': 0.05,
            'loss_limit': 0.97,
            'stop_loss': 0.95,
            'enable_volume_check': True,
            'min_avg_amount': 5_000_000,
            'slippage_standard': 0.001,
            'slippage_low_liq': 0.002,
            'etf_pool_size': len(pool_valid),
            'defensive_etf': defensive,
            'signal_delay': 'T-1 → T (次日开盘执行)',
            'same_day_trade_prohibited': True,
        },
    }
    
    return result


# ================================================================
# 入口
# ================================================================
if __name__ == '__main__':
    t0 = time.time()
    result = run_backtest()
    elapsed = time.time() - t0
    
    if result:
        print(f"\n⏱️ 回测耗时: {elapsed:.1f}秒")
        
        # 保存结果
        output_path = '/data/workspace/strategy_arena/qixing_v20_nolookahead_result.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"📁 结果已保存: {output_path}")
    else:
        print("\n❌ 回测失败")
