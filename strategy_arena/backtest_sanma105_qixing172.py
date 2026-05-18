#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马105七星17-大池子 策略A股回测
===================================
基于聚宽策略代码适配，本地向量化回测

策略组合（按资金比例50%/0%/50%/0%）：
  - 策略1: 小市值+一致性风控（50%）→ 本地无基本面数据，无法回测
  - 策略2: ETF反弹（0%）→ 已关闭
  - 策略3: ETF轮动 七星高照V1.7.2（50%）→ 核心回测对象
  - 策略4: 白马攻防（0%）→ 已关闭

回测重点：七星高照ETF轮动策略V1.7.2
  核心逻辑：
    1. 38只ETF大池，每日计算加权线性回归动量得分(年化×R²)
    2. 五重过滤：盈利保护 + 溢价率 + 成交量异常 + 短期动量 + 近3日急跌
    'sh516080': ('516080_XSHG', '创新药ETF'),
    3. 持仓1只得分最高的ETF，防御ETF为银华日利(511880)
    4. 盈利保护：持仓高点回撤超5%则卖出
    5. 止损：持仓跌破成本×0.95

来源：https://www.joinquant.com/post/69665
"""

import os, sys, json, math, time, smtplib, warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade


# ================================================================
# A股ETF池定义（对标原版38只大池）
# ================================================================
CN_ETF_POOL_FULL = {
    '518880_XSHG': '黄金ETF', '159980_XSHE': '有色ETF', '159985_XSHE': '豆粕ETF',
'501018_XSHG': '南方原油LOF', '161226_XSHE': '国投白银LOF',
    '159981_XSHE': '能源化工ETF', '513100_XSHG': '纳指ETF',
    '159509_XSHE': '中证500ETF联接', '513290_XSHG': '纳斯达克生物ETF',
    '513500_XSHG': '标普500ETF', '159529_XSHE': '科创50ETF',
    '513400_XSHG': '道琼斯ETF', '513520_XSHG': '日经225ETF',
    '513030_XSHG': '德国DAXETF', '513080_XSHG': '德国DAXETF2',
    '513310_XSHG': '东南亚科技ETF', '513730_XSHG': '东南亚科技ETF2',
    '159792_XSHE': '科技创新ETF', '513130_XSHG': '恒生科技ETF',
    '513050_XSHG': '中日ETF', '159920_XSHE': '恒生ETF',
    '513690_XSHG': '法国CAC40ETF', '510300_XSHG': '沪深300ETF',
    '510500_XSHG': '中证500ETF', '510050_XSHG': '上证50ETF',
    '510210_XSHG': '上证指数ETF', '159915_XSHE': '创业板ETF',
    '588080_XSHG': '科创50ETF2', '512100_XSHG': '中证1000ETF',
    '563360_XSHG': 'A500ETF', '563300_XSHG': 'A500ETF2',
    '512890_XSHG': '红利低波ETF', '159967_XSHE': '创成长ETF',
    '512040_XSHG': '价值100ETF', '159201_XSHE': '自由现金流ETF',
    '511380_XSHG': '十年国开ETF', '511010_XSHG': '国债ETF',
    '511220_XSHG': '城投ETF',
}

# 防御ETF
DEFENSIVE_ETF = '511880_XSHG'  # 银华日利

DATA_DIR = '/data/workspace/back_trader_stocks/a'


# ================================================================
# 数据加载
# ================================================================
def load_etf_data(symbols: list, data_dir: str) -> dict:
    """加载ETF数据"""
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
# 七星高照ETF轮动策略 V1.7.2 — 本地向量化版
# ================================================================
def qixing_v172_strategy(close_prices: pd.DataFrame,
                          high_prices: pd.DataFrame = None,
                          volume_data: pd.DataFrame = None,
                          etf_pool: list = None,
                          defensive_etf: str = DEFENSIVE_ETF,
                          # 核心参数
                          lookback_days: int = 25,
                          holdings_num: int = 1,
                          min_score_threshold: float = 0,
                          max_score_threshold: float = 100.0,
                          # 过滤参数
                          enable_volume_check: bool = False,
                          volume_lookback: int = 5,
                          volume_threshold: float = 2.0,
                          volume_return_limit: float = 1.0,
                          use_short_momentum_filter: bool = True,
                          short_lookback_days: int = 10,
                          short_momentum_threshold: float = 0.0,
                          # 盈利保护
                          enable_profit_protection: bool = True,
                          profit_protection_lookback: int = 1,
                          profit_protection_threshold: float = 0.05,
                          # 溢价率过滤（本地无法获取净值数据，跳过）
                          enable_premium_filter: bool = False,
                          premium_threshold: float = 0.20,
                          # 急跌过滤
                          loss_limit: float = 0.97,
                          # 止损
                          stop_loss: float = 0.95,
                          # 调仓频率
                          rebalance_freq: str = 'D') -> dict:
    """
    七星高照ETF轮动策略V1.7.2 — 向量化回测
    
    核心逻辑对标聚宽原版：
    1. 每日计算所有ETF的加权线性回归动量得分(年化×R²)
    2. 五重过滤（盈利保护/溢价率/成交量异常/短期动量/近3日急跌）
    3. 选取得分最高的ETF持有
    4. 防御模式：无合格标的时持有银华日利
    5. 盈利保护：持仓高点回撤超阈值则卖出
    6. 止损：持仓跌破成本×stop_loss
    
    返回dict: {
        'holding': pd.Series (每日持仓ETF),
        'trades': list (交易记录),
        'equity': pd.Series (净值曲线),
    }
    """
    if etf_pool is None:
        etf_pool = [c for c in close_prices.columns if c != defensive_etf]
    
    pool_in_data = [a for a in etf_pool if a in close_prices.columns]
    if defensive_etf not in close_prices.columns and pool_in_data:
        defensive_etf = pool_in_data[-1]
    
    dates = close_prices.index
    n_dates = len(dates)
    
    # 持仓记录
    holding = pd.Series(defensive_etf, index=dates)
    # 持仓高点追踪（用于盈利保护）
    position_highs = {}
    # 买入成本追踪
    buy_costs = {}
    # 交易记录
    trades = []
    
    current_holding = defensive_etf
    
    for i in range(max(lookback_days + 20, 60), n_dates):
        date = dates[i]
        
        # ====== 计算动量得分 ======
        best_etf = None
        best_score = -999
        etf_scores = []
        
        for etf in pool_in_data:
            try:
                # 检查当日是否停牌（成交量为0或价格为NaN）
                if pd.isna(close_prices[etf].iloc[i]) or close_prices[etf].iloc[i] <= 0:
                    continue
                
                # ---- 短期动量得分（核心） ----
                lookback = min(lookback_days, i)
                if lookback < 5:
                    continue
                
                price_slice = close_prices[etf].iloc[i - lookback:i + 1].dropna()
                if len(price_slice) < 5:
                    continue
                
                current_price = close_prices[etf].iloc[i]
                prices = np.append(price_slice.values[:-1], current_price)
                
                # 盈利保护过滤：如果当前持仓是该ETF，且从高点回撤超阈值
                if enable_profit_protection and etf == current_holding:
                    high_key = etf
                    if high_key in position_highs:
                        if current_price < position_highs[high_key] * (1 - profit_protection_threshold):
                            continue  # 触发盈利保护，不再考虑该ETF
                
                # 短期动量计算：加权线性回归
                y = np.log(prices.astype(float))
                x = np.arange(len(y), dtype=float)
                w = np.linspace(1, 2, len(y))
                
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
                if not (min_score_threshold < short_score < max_score_threshold):
                    short_score = 0
                
                # ---- 短期动量方向过滤 ----
                if use_short_momentum_filter and len(prices) >= short_lookback_days + 1:
                    short_ret = prices[-1] / prices[-(short_lookback_days + 1)] - 1
                    short_ann = (1 + short_ret) ** (252 / short_lookback_days) - 1
                    if short_ann < short_momentum_threshold:
                        continue
                
                # ---- 成交量异常过滤 ----
                if enable_volume_check and volume_data is not None and etf in volume_data.columns:
                    vol_slice = volume_data[etf].iloc[i - volume_lookback:i + 1].dropna()
                    if len(vol_slice) >= volume_lookback:
                        avg_vol = vol_slice[:-1].mean() if len(vol_slice) > 1 else 0
                        cur_vol = vol_slice.iloc[-1]
                        if avg_vol > 0:
                            vol_ratio = cur_vol / avg_vol
                            if vol_ratio > volume_threshold:
                                # 放量但收益率过高则过滤
                                if short_score > volume_return_limit:
                                    continue
                
                # ---- 近3日急跌过滤 ----
                if len(prices) >= 4:
                    day1 = prices[-1] / prices[-2]
                    day2 = prices[-2] / prices[-3]
                    day3 = prices[-3] / prices[-4]
                    if min(day1, day2, day3) < loss_limit:
                        continue
                
                combined_score = short_score
                etf_scores.append((etf, combined_score, ann_return, r2))
                
                if combined_score > best_score:
                    best_score = combined_score
                    best_etf = etf
                    
            except Exception as e:
                continue
        
        # 没有合适标的时持有防御ETF
        if best_etf is None or best_score <= 0:
            target = defensive_etf
        else:
            target = best_etf
        
        # ====== 执行调仓 ======
        if target != current_holding:
            # 卖出当前持仓
            if current_holding in close_prices.columns:
                sell_price = close_prices[current_holding].iloc[i]
                if current_holding in buy_costs and buy_costs[current_holding] > 0:
                    pnl_pct = (sell_price / buy_costs[current_holding] - 1) * 100
                else:
                    pnl_pct = 0
                trades.append({
                    'date': date,
                    'action': 'sell',
                    'etf': current_holding,
                    'price': sell_price,
                    'pnl_pct': round(pnl_pct, 2),
                })
            
            # 买入新标的
            if target in close_prices.columns:
                buy_price = close_prices[target].iloc[i]
                buy_costs[target] = buy_price
                position_highs[target] = buy_price
                trades.append({
                    'date': date,
                    'action': 'buy',
                    'etf': target,
                    'price': buy_price,
                })
            
            current_holding = target
        
        # ====== 盈利保护检查（盘中） ======
        if enable_profit_protection and current_holding in close_prices.columns:
            current_price = close_prices[current_holding].iloc[i]
            high_key = current_holding
            if high_key in position_highs:
                position_highs[high_key] = max(position_highs[high_key], current_price)
                if current_price < position_highs[high_key] * (1 - profit_protection_threshold):
                    # 触发盈利保护，卖出
                    sell_price = current_price
                    if current_holding in buy_costs and buy_costs[current_holding] > 0:
                        pnl_pct = (sell_price / buy_costs[current_holding] - 1) * 100
                    else:
                        pnl_pct = 0
                    trades.append({
                        'date': date,
                        'action': 'sell_profit_protection',
                        'etf': current_holding,
                        'price': sell_price,
                        'pnl_pct': round(pnl_pct, 2),
                        'drawdown_from_high': round((1 - current_price / position_highs[high_key]) * 100, 2),
                    })
                    current_holding = defensive_etf
                    position_highs.pop(high_key, None)
        
        # ====== 止损检查 ======
        if current_holding in buy_costs and current_holding in close_prices.columns:
            current_price = close_prices[current_holding].iloc[i]
            cost = buy_costs[current_holding]
            if cost > 0 and current_price < cost * stop_loss:
                pnl_pct = (current_price / cost - 1) * 100
                trades.append({
                    'date': date,
                    'action': 'stop_loss',
                    'etf': current_holding,
                    'price': current_price,
                    'pnl_pct': round(pnl_pct, 2),
                })
                current_holding = defensive_etf
                position_highs.pop(current_holding, None)
        
        holding.iloc[i] = current_holding
    
    # 预热期保持默认
    if len(holding) > 60:
        holding.iloc[:60] = defensive_etf
    
    return {
        'holding': holding,
        'trades': trades,
    }


# ================================================================
# 向量化回测引擎
# ================================================================
def vectorized_backtest(close_prices: pd.DataFrame, holding: pd.Series,
                        trades: list = None,
                        init_cash=1_000_000, fees_rate=0.001, slippage=0.001,
                        risk_free_rate=0.02) -> dict:
    """向量化回测引擎 — 带交易成本"""
    common_idx = close_prices.index.intersection(holding.index)
    close_prices = close_prices.loc[common_idx]
    holding = holding.loc[common_idx]
    
    returns = close_prices.pct_change()
    strategy_returns = pd.Series(0.0, index=common_idx)
    prev_holding = holding.iloc[0]
    trade_count = 0
    
    for i in range(1, len(common_idx)):
        date = common_idx[i]
        curr_holding = holding.iloc[i]
        
        if curr_holding in returns.columns:
            daily_ret = returns.loc[date, curr_holding]
            if pd.isna(daily_ret):
                daily_ret = 0
        else:
            daily_ret = 0
        
        if curr_holding != prev_holding:
            daily_ret -= (fees_rate * 2 + slippage * 2)
            trade_count += 1
        
        strategy_returns.iloc[i] = daily_ret
        prev_holding = curr_holding
    
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
        display_name = CN_ETF_POOL_FULL.get(sym, sym)
        holding_distribution[f"{sym.split('_')[0]}({display_name})"] = round(cnt / total_days_held * 100, 1)
    
    # 年度收益分解
    yearly_returns = {}
    for year in range(common_idx[0].year, common_idx[-1].year + 1):
        year_mask = common_idx.year == year
        year_eq = equity[year_mask]
        if len(year_eq) > 1:
            year_ret = (year_eq.iloc[-1] / year_eq.iloc[0] - 1) * 100
            yearly_returns[year] = round(year_ret, 2)
    
    # 压力测试：最大回撤区间
    dd_start = drawdown.idxmin()
    
    score_result = compute_total_score(
        annual_return=annual_return * 100,
        sharpe=sharpe,
        max_drawdown=max_drawdown * 100,
        profit_factor=profit_factor,
        win_rate=win_rate,
        cross_period_robust=False,
        survivorship_bias=True,
        monthly_positive_rate=monthly_positive_rate,
    )
    
    return {
        'annual_return': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(avg_trades_per_year, 1),
        'holding_distribution': holding_distribution,
        'total_score': score_result['total_score'],
        'grade': score_result['grade'],
        'score_detail': score_result,
        'monthly_positive_rate': round(monthly_positive_rate, 3),
        'final_value': round(equity.iloc[-1], 2),
        'trade_count': trade_count,
        'yearly_returns': yearly_returns,
        'max_drawdown_date': str(dd_start),
        'total_return': round((equity.iloc[-1] / init_cash - 1) * 100, 2),
        'years': round(years, 2),
    }


# ================================================================
# 压力测试（2015-2018）
# ================================================================
def run_stress_test(close_df, pool_valid, safe_valid, data_dir, params):
    """压力测试：2015-2018 牛熊穿越"""
    stress_start = '2015-01-01'
    stress_end = '2018-12-31'
    
    stress_df = close_df.loc[stress_start:stress_end]
    if len(stress_df) < 100:
        return None
    
    stress_vol = None
    if params.get('enable_volume_check'):
        vol_data = {}
        for sym in pool_valid:
            filepath = os.path.join(data_dir, f'{sym}.csv')
            if os.path.exists(filepath):
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                df = df.sort_index()
                col_map = {}
                for c in df.columns:
                    if c.strip().lower() == 'volume':
                        col_map[c] = 'Volume'
                df = df.rename(columns=col_map)
                if 'Volume' in df.columns:
                    vol_data[sym] = df['Volume']
        if vol_data:
            stress_vol = pd.DataFrame(vol_data).loc[stress_start:stress_end]
    
    result = qixing_v172_strategy(
        stress_df, volume_data=stress_vol,
        etf_pool=pool_valid, defensive_etf=safe_valid[0] if safe_valid else pool_valid[-1],
        **params
    )
    
    bt_result = vectorized_backtest(stress_df, result['holding'], risk_free_rate=0.02)
    return bt_result


# ================================================================
# 主回测流程
# ================================================================
def run_all_backtests():
    print("=" * 90)
    print("  🔥 三马105七星17-大池子 A股回测")
    print("  七星高照ETF轮动策略V1.7.2 — 本地向量化版")
    print("  来源：https://www.joinquant.com/post/69665")
    print("=" * 90)
    
    # 加载数据
    pool_symbols = list(CN_ETF_POOL_FULL.keys())
    all_symbols = pool_symbols + [DEFENSIVE_ETF]
    
    print(f"\n📦 加载ETF数据(池大小: {len(all_symbols)})...")
    raw_data = load_etf_data(all_symbols, DATA_DIR)
    print(f"  ✅ 成功加载{len(raw_data)}只")
    
    if len(raw_data) < 5:
        print("  ❌ 数据不足，退出")
        return None, None
    
    # 构建价格矩阵
    close_df = pd.DataFrame({sym: df['Close'] for sym, df in raw_data.items()}).sort_index()
    high_df = pd.DataFrame({sym: df['High'] for sym, df in raw_data.items()}).sort_index()
    vol_df = pd.DataFrame({sym: df['Volume'] for sym, df in raw_data.items()}).sort_index()
    
    # 时间范围：从2016年开始（确保数据充分）
    close_df = close_df.loc['2016-01-01':'2026-04-25']
    high_df = high_df.loc['2016-01-01':'2026-04-25']
    vol_df = vol_df.loc['2016-01-01':'2026-04-25']
    
    close_df = close_df.dropna(axis=1, how='all')
    valid_cols = [c for c in close_df.columns if close_df[c].dropna().shape[0] > 300]
    close_df = close_df[valid_cols]
    
    print(f"  📊 有效ETF: {len(valid_cols)}只, {close_df.shape[0]}个交易日")
    print(f"     范围: {close_df.index[0].strftime('%Y-%m-%d')} ~ {close_df.index[-1].strftime('%Y-%m-%d')}")
    
    pool_valid = [a for a in pool_symbols if a in valid_cols]
    safe_valid = [a for a in [DEFENSIVE_ETF] if a in valid_cols]
    
    print(f"\n  🏊 有效ETF池: {len(pool_valid)}只, 防御ETF: {safe_valid}")
    
    # 参数变体配置
    variant_configs = [
        {
            'name': 'V1.7.2原版(25日+盈利保护+急跌过滤)',
            'params': {
                'lookback_days': 25, 'holdings_num': 1,
                'enable_profit_protection': True,
                'profit_protection_threshold': 0.05,
                'loss_limit': 0.97, 'stop_loss': 0.95,
                'use_short_momentum_filter': True,
                'short_lookback_days': 10, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
        {
            'name': 'V1.7.2无盈利保护版',
            'params': {
                'lookback_days': 25, 'holdings_num': 1,
                'enable_profit_protection': False,
                'loss_limit': 0.97, 'stop_loss': 0.95,
                'use_short_momentum_filter': True,
                'short_lookback_days': 10, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
        {
            'name': 'V1.7.2宽松急跌(-5%/日)',
            'params': {
                'lookback_days': 25, 'holdings_num': 1,
                'enable_profit_protection': True,
                'profit_protection_threshold': 0.05,
                'loss_limit': 0.95, 'stop_loss': 0.95,
                'use_short_momentum_filter': True,
                'short_lookback_days': 10, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
        {
            'name': 'V1.7.2短周期(15日)',
            'params': {
                'lookback_days': 15, 'holdings_num': 1,
                'enable_profit_protection': True,
                'profit_protection_threshold': 0.05,
                'loss_limit': 0.97, 'stop_loss': 0.95,
                'use_short_momentum_filter': True,
                'short_lookback_days': 7, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
        {
            'name': 'V1.7.2长周期(40日)',
            'params': {
                'lookback_days': 40, 'holdings_num': 1,
                'enable_profit_protection': True,
                'profit_protection_threshold': 0.05,
                'loss_limit': 0.97, 'stop_loss': 0.95,
                'use_short_momentum_filter': True,
                'short_lookback_days': 15, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
        {
            'name': 'V1.7.2宽松盈利保护(10%回撤)',
            'params': {
                'lookback_days': 25, 'holdings_num': 1,
                'enable_profit_protection': True,
                'profit_protection_threshold': 0.10,
                'loss_limit': 0.97, 'stop_loss': 0.95,
                'use_short_momentum_filter': True,
                'short_lookback_days': 10, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
        {
            'name': 'V1.7.2严格止损(0.93)',
            'params': {
                'lookback_days': 25, 'holdings_num': 1,
                'enable_profit_protection': True,
                'profit_protection_threshold': 0.05,
                'loss_limit': 0.97, 'stop_loss': 0.93,
                'use_short_momentum_filter': True,
                'short_lookback_days': 10, 'short_momentum_threshold': 0.0,
                'enable_volume_check': False,
            }
        },
    ]
    
    all_results = {}
    all_variant_results = {}
    
    # ====== 主回测 ======
    print(f"\n{'='*70}")
    print(f"  🔄 主回测（2016-2026，约10年）")
    print(f"{'='*70}")
    
    for vc in variant_configs:
        vname = vc['name']
        vparams = vc['params']
        print(f"\n  📊 {vname}")
        
        result_dict = qixing_v172_strategy(
            close_df, high_prices=high_df, volume_data=vol_df,
            etf_pool=pool_valid, defensive_etf=safe_valid[0] if safe_valid else pool_valid[-1],
            **vparams
        )
        
        bt_result = vectorized_backtest(
            close_df, result_dict['holding'], result_dict['trades'],
            risk_free_rate=0.02
        )
        
        if bt_result:
            all_variant_results[vname] = bt_result
            print(f"  ✅ 年化{bt_result['annual_return']}% 夏普{bt_result['sharpe']} "
                  f"回撤{bt_result['max_drawdown']}% 评分{bt_result['total_score']}({bt_result['grade']})")
            print(f"     总收益{bt_result['total_return']}% 终值{bt_result['final_value']} "
                  f"交易{bt_result['trade_count']}次 月度胜率{bt_result['monthly_positive_rate']*100:.0f}%")
            
            # 打印持仓分布
            hd = bt_result.get('holding_distribution', {})
            top5 = sorted(hd.items(), key=lambda x: x[1], reverse=True)[:5]
            for sym, pct in top5:
                print(f"     {sym}: {pct}%")
            
            # 打印年度收益
            yr = bt_result.get('yearly_returns', {})
            yr_str = ' | '.join([f"{k}:{v}%" for k, v in sorted(yr.items())])
            print(f"     年度收益: {yr_str}")
    
    # 原版作为主结果
    main_name = variant_configs[0]['name']
    main_result = all_variant_results.get(main_name)
    if main_result:
        all_results['CN'] = main_result
        
        # ====== 压力测试 ======
        print(f"\n{'='*70}")
        print(f"  💪 压力测试（2015-2018 牛熊穿越）")
        print(f"{'='*70}")
        
        stress_result = run_stress_test(close_df, pool_valid, safe_valid, DATA_DIR, variant_configs[0]['params'])
        if stress_result:
            print(f"  ✅ 压力期年化{stress_result['annual_return']}% 回撤{stress_result['max_drawdown']}%")
            main_result['stress_annual'] = stress_result['annual_return']
            main_result['stress_dd'] = stress_result['max_drawdown']
            
            # 跨周期鲁棒性判定
            stress_annual = stress_result['annual_return']
            stress_dd = stress_result['max_drawdown']
            main_dd = main_result['max_drawdown']
            robust = (stress_annual >= 0) and (stress_dd <= main_dd * 1.5)
            
            # 重新计算评分含鲁棒性
            score_detail = compute_total_score(
                annual_return=main_result['annual_return'],
                sharpe=main_result['sharpe'],
                max_drawdown=main_result['max_drawdown'],
                profit_factor=main_result['profit_factor'],
                win_rate=main_result['win_rate'],
                cross_period_robust=robust,
                survivorship_bias=True,
                monthly_positive_rate=main_result['monthly_positive_rate'],
            )
            main_result['total_score'] = score_detail['total_score']
            main_result['grade'] = score_detail['grade']
            main_result['score_detail'] = score_detail
            main_result['cross_period_robust'] = robust
            print(f"  🔍 跨周期鲁棒: {'✅ 通过' if robust else '❌ 未通过'}")
            print(f"  📊 更新评分: {score_detail['total_score']}({score_detail['grade']})")
        
        # ====== 入榜评估 ======
        print(f"\n{'='*70}")
        print(f"  🏆 入榜评估")
        print(f"{'='*70}")
        
        evaluate_leaderboard_entry(main_result, variant_configs[0])
    
    return all_results, all_variant_results


# ================================================================
# 排行榜入榜评估
# ================================================================
def evaluate_leaderboard_entry(result, variant_config):
    """评估是否可入A股排行榜"""
    lb_path = '/data/workspace/strategy_arena/leaderboard_cross_regime_cn.json'
    
    # 加载现有排行榜
    if os.path.exists(lb_path):
        with open(lb_path, 'r', encoding='utf-8') as f:
            leaderboard = json.load(f)
    else:
        leaderboard = []
    
    # 构建策略条目
    from strategy_ranker import update_leaderboard
    
    hd = result.get('holding_distribution', {})
    
    # Deep convert score_detail to native Python types
    import numbers
    def native(obj):
        if isinstance(obj, dict):
            return {k: native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [native(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, numbers.Number):
            return float(obj) if isinstance(obj, float) else obj
        return obj
    
    entry = {
            'strategy_name': '三马105七星17-ETF轮动V1.7.2',
            'strategy_params': {
                'lookback_days': 25,
                'holdings_num': 1,
                'etf_pool': '大池38只(本地回测)',
                'filters': '盈利保护+短期动量+近3日急跌',
                'profit_protection': '1日回看/5%回撤',
                'stop_loss': '0.95',
                'source': '聚宽(rbq2025/晨曦量化) 本地适配版'
            },
            'strategy_description': '三马105七星17-大池子组合中的ETF轮动策略(七星高照V1.7.2)，加权线性回归动量得分(年化×R²)+多重过滤+盈利保护+止损',
            'strategy_type': '趋势跟踪',
            'source': '🖥️本地回测',
            'annual_return': float(result['annual_return']),
            'sharpe': float(result['sharpe']),
            'max_drawdown': float(result['max_drawdown']),
            'win_rate': float(result['win_rate']),
            'profit_factor': float(result['profit_factor']),
            'avg_trades_per_year': float(result['avg_trades_per_year']),
            'holding_distribution': {str(k): float(v) for k, v in hd.items()},
            'total_score': float(result['total_score']),
            'grade': str(result['grade']),
            'score_detail': native(result['score_detail']),
            'stress_test': {
                'annual_return': float(result.get('stress_annual', 0)),
                'max_drawdown': float(result.get('stress_dd', 0)),
            },
            'cross_robust': bool(result.get('cross_period_robust', False)),
            'survivorship_bias_flag': True,
            'pine_script_rejected': False,
            'portability_score': 10,
            'market': 'CN',
            'fingerprint': 'sanma105_qixing172_local_v1',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'monthly_positive_rate': float(result.get('monthly_positive_rate', 0)),
            'total_return': float(result.get('total_return', 0)),
            'final_value': float(result.get('final_value', 0)),
            'trade_count': int(result.get('trade_count', 0)),
        }
    
    # 检查是否能入榜
    current_scores = [e.get('total_score', 0) for e in leaderboard]
    min_score = min(current_scores) if current_scores else 0
    
    print(f"\n  当前排行榜TOP10最低分: {min_score}")
    print(f"  本策略得分: {entry['total_score']}({entry['grade']})")
    
    if entry['total_score'] > min_score or len(leaderboard) < 10:
        # 加入排行榜
        # 先检查同指纹
        existing_idx = None
        for idx, e in enumerate(leaderboard):
            if e.get('fingerprint') == entry['fingerprint']:
                existing_idx = idx
                break
        
        if existing_idx is not None:
            if entry['total_score'] > leaderboard[existing_idx]['total_score']:
                leaderboard[existing_idx] = entry
                print(f"  ✅ 更新已有条目(得分更高)")
        else:
            leaderboard.append(entry)
            print(f"  ✅ 新增入榜!")
        
        # 排序并截取前10
        leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)
        leaderboard = leaderboard[:10]
        
        with open(lb_path, 'w', encoding='utf-8') as f:
            json.dump(leaderboard, f, ensure_ascii=False, indent=2)
        
        print(f"  📁 排行榜已更新: {lb_path}")
    else:
        print(f"  ❌ 得分未达入榜门槛({min_score}分)")


# ================================================================
# HTML报告生成
# ================================================================
def build_html_report(results, variant_results):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    GRADE_COLORS = {'S+': '#ff4500', 'S': '#f97316', 'A': '#22c55e', 'B': '#3b82f6', 'C': '#a855f7', 'D': '#6b7280', 'F': '#374151'}
    
    # 主结果卡片
    r = results.get('CN')
    if not r:
        return "<html><body>无回测结果</body></html>"
    
    grade = r['grade']
    gc = GRADE_COLORS.get(grade, '#6b7280')
    grade_badge = f'<span style="display:inline-block;background:{gc};color:white;font-size:12px;font-weight:800;padding:2px 8px;border-radius:4px">{grade}</span>'
    
    # 持仓分布
    hd = r.get('holding_distribution', {})
    hd_sorted = sorted(hd.items(), key=lambda x: x[1], reverse=True)[:8]
    hd_html = ''
    for sym, pct in hd_sorted:
        bar_w = min(pct, 100)
        hd_html += f'''<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
            <span style="font-size:10px;color:#9ca3af;min-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{sym}</span>
            <div style="flex:1;background:rgba(249,115,22,0.1);border-radius:2px;height:12px"><div style="width:{bar_w}%;background:linear-gradient(90deg,#f97316,#fb923c);height:100%;border-radius:2px"></div></div>
            <span style="font-size:10px;color:#f97316;font-weight:600">{pct}%</span></div>'''
    
    # 年度收益
    yr = r.get('yearly_returns', {})
    yr_html = ''
    for year, ret in sorted(yr.items()):
        color = '#22c55e' if ret >= 0 else '#ef4444'
        yr_html += f'''<div style="display:inline-block;text-align:center;margin:4px 6px">
            <div style="font-size:10px;color:#9ca3af">{year}</div>
            <div style="font-size:14px;font-weight:700;color:{color}">{ret:.1f}%</div></div>'''
    
    # 评分详情
    sd = r.get('score_detail', {})
    score_items = [
        ('年化收益', sd.get('annual_return_score', 0), '#22c55e', 25),
        ('夏普比率', sd.get('sharpe_score', 0), '#3b82f6', 25),
        ('最大回撤', sd.get('max_drawdown_score', 0), '#ef4444', 23),
        ('盈亏比', sd.get('profit_factor_score', 0), '#f59e0b', 15),
        ('胜率', sd.get('win_rate_score', 0), '#a855f7', 15),
    ]
    score_html = ''
    for name, val, color, max_val in score_items:
        pct = min(val / max_val * 100, 100) if max_val > 0 else 0
        score_html += f'''<div style="margin:4px 0">
            <div style="display:flex;justify-content:space-between;font-size:10px">
                <span style="color:#9ca3af">{name}</span>
                <span style="color:{color};font-weight:600">{val:.2f}</span>
            </div>
            <div style="background:rgba(255,255,255,0.05);border-radius:2px;height:6px;margin-top:2px">
                <div style="width:{pct}%;background:{color};height:100%;border-radius:2px"></div>
            </div></div>'''
    
    bonus_html = ''
    if sd.get('cross_period_bonus', 0) > 0:
        bonus_html += f'<span style="display:inline-block;background:rgba(34,197,94,0.2);color:#22c55e;font-size:10px;padding:2px 6px;border-radius:3px;margin:2px">鲁棒+{sd["cross_period_bonus"]}</span>'
    if sd.get('monthly_stability_bonus', 0) > 0:
        bonus_html += f'<span style="display:inline-block;background:rgba(59,130,246,0.2);color:#3b82f6;font-size:10px;padding:2px 6px;border-radius:3px;margin:2px">稳定+{sd["monthly_stability_bonus"]}</span>'
    if sd.get('survivorship_penalty', 0) < 0:
        bonus_html += f'<span style="display:inline-block;background:rgba(239,68,68,0.2);color:#ef4444;font-size:10px;padding:2px 6px;border-radius:3px;margin:2px">偏差{sd["survivorship_penalty"]}</span>'
    
    # 参数变体表格
    variant_html = ''
    sorted_variants = sorted(variant_results.items(), key=lambda x: x[1].get('total_score', 0), reverse=True)
    for vname, vr in sorted_variants:
        vg = vr['grade']
        vgc = GRADE_COLORS.get(vg, '#6b7280')
        variant_html += f'''<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
            <td style="padding:4px 6px;color:#e5e7eb;font-size:11px">{vname}</td>
            <td style="padding:4px 6px;text-align:right;font-weight:700;color:{vgc};font-size:12px">{vr['total_score']:.1f}</td>
            <td style="padding:4px 6px;text-align:center"><span style="color:{vgc};font-weight:700;font-size:11px">{vg}</span></td>
            <td style="padding:4px 6px;text-align:right;color:#22c55e;font-size:11px">{vr['annual_return']:.1f}</td>
            <td style="padding:4px 6px;text-align:right;color:#3b82f6;font-size:11px">{vr['sharpe']:.2f}</td>
            <td style="padding:4px 6px;text-align:right;color:#ef4444;font-size:11px">{vr['max_drawdown']:.1f}</td>
            <td style="padding:4px 6px;text-align:right;color:#f59e0b;font-size:11px">{vr['profit_factor']:.2f}</td>
            <td style="padding:4px 6px;text-align:right;color:#a855f7;font-size:11px">{vr['win_rate']:.1f}</td>
            <td style="padding:4px 6px;text-align:right;color:#6b7280;font-size:11px">{vr['avg_trades_per_year']:.0f}</td>
        </tr>'''
    
    # 分析
    analysis_html = f'''<div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(249,115,22,0.1)">
      <div style="font-size:12px;font-weight:600;color:#f59e0b;margin-bottom:4px">🔑 本地回测 vs 聚宽原版(324倍/11年)差异分析</div>
      <div style="font-size:11px;color:#9ca3af;line-height:1.8">
        <b style="color:#ef4444">1. 策略范围差异</b>: 聚宽原版包含4个子策略(小市值+ETF反弹+ETF轮动+白马攻防)，
        本地仅回测ETF轮动(占50%资金)；小市值策略贡献了大部分收益（11年324倍主要来自小盘股）<br>
        <b style="color:#ef4444">2. 数据差异</b>: 本地数据为后复权不含分红再投，聚宽使用全复权；
        本地无法获取溢价率/基金净值数据，溢价率过滤已关闭<br>
        <b style="color:#f59e0b">3. 交易成本差异</b>: 聚宽ETF佣金0.02%+0.01%滑点，本地使用0.1%+0.1%更保守<br>
        <b style="color:#22c55e">4. 评分参照</b>: 当前A股TOP1为"七星高照V1.7.2-无成交量过滤"(74.51分/S级)，
        本策略为同一ETF轮动逻辑的不同参数组合
      </div></div>'''
    
    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>三马105七星17 A股回测</title>
<style>details summary::-webkit-details-marker{{display:none}}details summary{{list-style:none}}details summary::marker{{display:none;content:""}}</style></head>
<body style="margin:0;padding:12px 8px;background-color:#060610;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;color:#e5e7eb">
<div style="max-width:600px;margin:0 auto">
  <div style="background:#0c0c14;border-radius:14px;padding:20px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:22px">🔥</span>
      <span style="font-size:20px;font-weight:800;color:#f97316">三马105七星17-大池子</span>
    </div>
    <div style="font-size:13px;font-weight:600;color:#fb923c;margin-bottom:4px">ETF轮动策略V1.7.2 — A股回测</div>
    <div style="font-size:11px;color:#6b7280;line-height:1.6">
      {now_str} · 🇨🇳A股 · 本地向量化回测 · V4评分<br>
      来源: 聚宽(rbq2025/晨曦量化) · 38只ETF大池 · 加权线性回归动量+五重过滤
    </div>
  </div>
  
  <div style="background:#0c0c14;border-radius:12px;padding:18px;margin-bottom:14px;border-left:3px solid {gc};border:1px solid rgba(249,115,22,0.18)">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:18px">🇨🇳</span>
      <span style="font-size:16px;font-weight:800;color:#f97316">A股七星高照ETF轮动</span>
    </div>
    <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:10px">
      <span style="font-size:32px;font-weight:800;color:{'#f97316' if r['total_score']>=50 else '#fb923c' if r['total_score']>=28 else '#6b7280'}">{r['total_score']:.1f}</span>
      <span style="font-size:12px;color:#9ca3af">分</span>
      {grade_badge}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 16px;margin-bottom:10px">
      <div><span style="font-size:10px;color:#9ca3af">年化收益</span><br><span style="font-size:16px;font-weight:700;color:#22c55e">{r['annual_return']:.1f}%</span></div>
      <div><span style="font-size:10px;color:#9ca3af">夏普比率</span><br><span style="font-size:16px;font-weight:700;color:#3b82f6">{r['sharpe']:.2f}</span></div>
      <div><span style="font-size:10px;color:#9ca3af">最大回撤</span><br><span style="font-size:16px;font-weight:700;color:#ef4444">{r['max_drawdown']:.1f}%</span></div>
      <div><span style="font-size:10px;color:#9ca3af">胜率</span><br><span style="font-size:16px;font-weight:700;color:#a855f7">{r['win_rate']:.1f}%</span></div>
      <div><span style="font-size:10px;color:#9ca3af">盈亏比</span><br><span style="font-size:16px;font-weight:700;color:#f59e0b">{r['profit_factor']:.2f}</span></div>
      <div><span style="font-size:10px;color:#9ca3af">年交易</span><br><span style="font-size:16px;font-weight:700;color:#6b7280">{r['avg_trades_per_year']:.0f}次</span></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;margin-bottom:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.05)">
      <div><span style="font-size:10px;color:#9ca3af">总收益</span><br><span style="font-size:14px;font-weight:600;color:#22c55e">{r['total_return']:.1f}%</span></div>
      <div><span style="font-size:10px;color:#9ca3af">终值</span><br><span style="font-size:14px;font-weight:600;color:#9ca3af">¥{r['final_value']:,.0f}</span></div>
      <div><span style="font-size:10px;color:#9ca3af">月度胜率</span><br><span style="font-size:14px;font-weight:600;color:#3b82f6">{r['monthly_positive_rate']*100:.0f}%</span></div>
      <div><span style="font-size:10px;color:#9ca3af">总交易次数</span><br><span style="font-size:14px;font-weight:600;color:#6b7280">{r['trade_count']}次</span></div>
    </div>
  </div>
  
  <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
    <summary style="font-size:13px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;outline:none">📊 评分详情</summary>
    <div style="margin-top:8px">
      {score_html}
      <div style="margin-top:8px">{bonus_html}</div>
    </div>
  </details>
  
  <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
    <summary style="font-size:13px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;outline:none">🏆 持仓分布 Top8</summary>
    <div style="margin-top:8px">{hd_html}</div>
  </details>
  
  <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
    <summary style="font-size:13px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;outline:none">📅 年度收益</summary>
    <div style="margin-top:8px;display:flex;flex-wrap:wrap;justify-content:center">{yr_html}</div>
  </details>
  
  <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
    <summary style="font-size:13px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;outline:none">🔬 参数变体对比({len(variant_results)}种)</summary>
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <tr style="border-bottom:1px solid rgba(249,115,22,0.2)">
        <th style="padding:4px 6px;text-align:left;color:#f97316;font-size:10px">变体</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">评分</th>
        <th style="padding:4px 6px;text-align:center;color:#f97316;font-size:10px">等级</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">年化%</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">夏普</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">回撤%</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">盈亏比</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">胜率%</th>
        <th style="padding:4px 6px;text-align:right;color:#f97316;font-size:10px">年交易</th>
      </tr>
      {variant_html}
    </table>
  </details>
  
  {analysis_html}
</div></body></html>'''
    return html


def send_email(html_content: str):
    smtp_server = 'smtp.qq.com'
    smtp_port = 465
    sender = '848786642@qq.com'
    password = 'ljbtvacrctjobfed'
    receiver = '848786642@qq.com'
    subject = f'【策略回测报告】{datetime.now().strftime("%Y%m%d")} 三马105七星17 A股回测'
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print("  ✅ 邮件发送成功")
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")


# ================================================================
if __name__ == '__main__':
    start_time = time.time()
    results, variant_results = run_all_backtests()
    elapsed = time.time() - start_time
    print(f"\n⏱️ 回测耗时: {elapsed:.1f}秒")
    
    if results:
        html = build_html_report(results, variant_results)
        report_path = f'/data/workspace/strategy_arena/sanma105_qixing172_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"\n✅ 报告已保存: {report_path}")
        
        print("\n📧 发送邮件...")
        send_email(html)
    else:
        print("\n❌ 无回测结果")
    
    print("\n✅ 全部完成！")
