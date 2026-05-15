#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF轮动策略 V1.7.2 — 短周期(15日)版
==============================================
A股排行榜排名第一策略（评分68.9分/S级）

回测区间: 2019-2024主区间 + 2015-2018压力测试
核心指标:
  - 年化收益: +132.9%
  - 夏普比率: 3.31
  - 最大回撤: 8.3%
  - 胜率: 47.3%
  - 盈亏比: 1.93
  - 压力测试年化: +32.2%（鲁棒✅）

策略逻辑:
  1. 38只A股ETF大池，每日计算加权线性回归动量得分(年化×R²)
  2. 五重过滤：盈利保护 + 溢价率 + 成交量异常 + 短期动量 + 近3日急跌
  3. 持仓1只得分最高的ETF，防御ETF为银华日利(511880)
  4. 盈利保护：持仓高点回撤超5%则卖出
  5. 止损：持仓跌破成本×0.95
  6. 短周期参数：lookback_days=15（标准版25日），short_lookback_days=7（标准版10日）

来源：https://www.joinquant.com/post/69665
"""

import os, sys, json, math, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade


# ================================================================
# A股ETF池定义（对标原版38只大池）
# ================================================================
CN_ETF_POOL_FULL = {
    '518880_XSHG': '黄金ETF', '159980_XSHE': '有色金属ETF', '159985_XSHE': '豆粕ETF',
'501018_XSHG': '南方原油ETF', '161226_XSHE': '白银LOF',
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
    '510210_XSHG': '上证ETF', '159915_XSHE': '创业板ETF',
    '588080_XSHG': '科创50ETF2', '512100_XSHG': '中证1000ETF',
    '563360_XSHG': '中证2000ETF', '563300_XSHG': '中证2000ETF2',
    '512890_XSHG': '红利低波ETF', '159967_XSHE': '创成长ETF',
    '512040_XSHG': '沪深300价值ETF', '159201_XSHE': '创新药ETF',
    '511380_XSHG': '十年国开ETF', '511010_XSHG': '国债ETF',
    '511220_XSHG': '城投ETF',
}

# 防御ETF
DEFENSIVE_ETF = '511880_XSHG'  # 银华日利

DATA_DIR = '/data/workspace/back_trader_stocks/a'
CN_RISK_FREE_RATE = 0.02


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
# 七星高照ETF轮动策略 V1.7.2 — 短周期(15日)版
# ================================================================
def qixing_v172_short15_strategy(close_prices: pd.DataFrame,
                                  high_prices: pd.DataFrame = None,
                                  volume_data: pd.DataFrame = None,
                                  etf_pool: list = None,
                                  defensive_etf: str = DEFENSIVE_ETF) -> dict:
    """
    七星高照ETF轮动策略V1.7.2 — 短周期(15日)版
    
    与标准版(25日)的唯一区别：
      - lookback_days: 15（标准25）
      - short_lookback_days: 7（标准10）
    
    核心逻辑对标聚宽原版：
    1. 每日计算所有ETF的加权线性回归动量得分(年化×R²)
    2. 五重过滤（盈利保护/溢价率/成交量异常/短期动量/近3日急跌）
    3. 选取得分最高的ETF持有
    4. 防御模式：无合格标的时持有银华日利
    5. 盈利保护：持仓高点回撤超5%则卖出
    6. 止损：持仓跌破成本×0.95
    
    返回dict: {
        'holding': pd.Series (每日持仓ETF),
        'trades': list (交易记录),
    }
    """
    # ====== 短周期版核心参数 ======
    lookback_days = 15          # 标准版25日
    short_lookback_days = 7     # 标准版10日
    short_momentum_threshold = 0.0
    profit_protection_threshold = 0.05
    loss_limit = 0.97           # 近3日单日最大跌幅阈值
    stop_loss = 0.95            # 止损线
    enable_volume_check = False # 无成交量过滤（排行榜策略1配置）
    
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
        
        for etf in pool_in_data:
            try:
                # 检查当日是否停牌
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
                
                # 盈利保护过滤：当前持仓该ETF且从高点回撤超5%
                if etf == current_holding:
                    high_key = etf
                    if high_key in position_highs:
                        if current_price < position_highs[high_key] * (1 - profit_protection_threshold):
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
                
                # 得分过滤：0 < score < 100
                if not (0 < short_score < 100):
                    short_score = 0
                
                # ---- 短期动量方向过滤 ----
                if len(prices) >= short_lookback_days + 1:
                    short_ret = prices[-1] / prices[-(short_lookback_days + 1)] - 1
                    short_ann = (1 + short_ret) ** (252 / short_lookback_days) - 1
                    if short_ann < short_momentum_threshold:
                        continue
                
                # ---- 成交量异常过滤（本版关闭） ----
                # enable_volume_check = False
                
                # ---- 近3日急跌过滤 ----
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
        if current_holding in close_prices.columns:
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
                        init_cash=1_000_000, fees_rate=0.0006, slippage=0.001,
                        risk_free_rate=CN_RISK_FREE_RATE) -> dict:
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
    }


# ================================================================
# 主回测入口
# ================================================================
def run_backtest(start_date='2019-01-01', end_date='2024-12-31',
                 stress_start='2015-01-01', stress_end='2018-12-31'):
    """
    运行七星高照V1.7.2短周期(15日)策略完整回测
    
    Args:
        start_date: 主回测开始日期
        end_date: 主回测结束日期
        stress_start: 压力测试开始日期
        stress_end: 压力测试结束日期
    """
    print("=" * 90)
    print("  🥇 A股排行榜#1: 七星高照ETF轮动V1.7.2-短周期(15日)")
    print(f"  📅 主区间: {start_date} ~ {end_date}")
    print(f"  💪 压力测试: {stress_start} ~ {stress_end}")
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
    high_df = pd.DataFrame({sym: df['High'] for sym, df in raw_data.items()}).sort_index()
    vol_df = pd.DataFrame({sym: df['Volume'] for sym, df in raw_data.items()}).sort_index()
    
    # 清理
    close_df = close_df.dropna(axis=1, how='all')
    valid_cols = [c for c in close_df.columns if close_df[c].dropna().shape[0] > 300]
    close_df = close_df[valid_cols]
    high_df = high_df[[c for c in valid_cols if c in high_df.columns]]
    vol_df = vol_df[[c for c in valid_cols if c in vol_df.columns]]
    
    print(f"  📊 有效ETF: {len(valid_cols)}只, {close_df.shape[0]}个交易日")
    print(f"     范围: {close_df.index[0].strftime('%Y-%m-%d')} ~ {close_df.index[-1].strftime('%Y-%m-%d')}")
    
    pool_valid = [a for a in pool_symbols if a in valid_cols]
    safe_valid = [a for a in [DEFENSIVE_ETF] if a in valid_cols]
    defensive = safe_valid[0] if safe_valid else pool_valid[-1]
    
    print(f"  🏊 有效ETF池: {len(pool_valid)}只, 防御ETF: {safe_valid}")
    
    # ====== 生成信号（使用全量数据） ======
    print(f"\n🔄 生成策略信号...")
    signal_result = qixing_v172_short15_strategy(
        close_prices=close_df,
        high_prices=high_df,
        volume_data=vol_df,
        etf_pool=pool_valid,
        defensive_etf=defensive,
    )
    print(f"  ✅ 信号生成完成")
    
    # ====== 主回测 ======
    print(f"\n📊 主回测 ({start_date} ~ {end_date})...")
    main_close = close_df.loc[start_date:end_date]
    main_holding = signal_result['holding'].loc[start_date:end_date]
    
    main_result = vectorized_backtest(main_close, main_holding, risk_free_rate=CN_RISK_FREE_RATE)
    
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
    stress_holding = signal_result['holding'].loc[stress_start:stress_end]
    
    stress_result = vectorized_backtest(stress_close, stress_holding, risk_free_rate=CN_RISK_FREE_RATE)
    
    if stress_result:
        stress_annual = stress_result['annual_return']
        stress_dd = stress_result['max_drawdown']
        print(f"  ✅ 年化收益: {stress_annual:+.2f}%")
        print(f"     最大回撤: {stress_dd:.2f}%")
    else:
        print("  ⚠️ 压力测试数据不足")
        stress_annual = 0
        stress_dd = 0
    
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
        'strategy_name': '七星高照ETF轮动V1.7.2-短周期(15日)',
        'main_period': main_result,
        'stress_test': {
            'annual_return': stress_annual,
            'max_drawdown': stress_dd,
            'passed': stress_passed,
        },
        'score': score_result,
        'params': {
            'lookback_days': 15,
            'short_lookback_days': 7,
            'profit_protection_threshold': 0.05,
            'loss_limit': 0.97,
            'stop_loss': 0.95,
            'enable_volume_check': False,
            'etf_pool_size': len(pool_valid),
            'defensive_etf': defensive,
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
        output_path = '/data/workspace/strategy_arena/qixing_v172_short15_result.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"📁 结果已保存: {output_path}")
    else:
        print("\n❌ 回测失败")
