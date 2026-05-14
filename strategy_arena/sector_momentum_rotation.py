#!/usr/bin/env python3
"""
Sector Momentum Rotation Strategy - 三市场回测（本地全量数据版 v3）
====================================================================
Source: Quantpedia / Moskovitz & Grinblatt (1999)

数据源：本地全量CSV
- 🇺🇸 美股: 10只Sector ETF + SPY基准（1998-2026, 6800+交易日）
- 🇭🇰 港股: 7只蓝筹（2015-2026, 2600交易日）
- 🇨🇳 A股: 5只ETF（2015-2026, 2600交易日）

v3修复：
1. 交易成本从累计净值中扣除（而非日收益），避免复利放大
2. 去掉XLC（2018年上市，避免NaN偏差）
3. dropna只保留所有标的有数据的时段
4. 同时输出有/无趋势过滤器对比
"""

import os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

# ================================================================
# 全局配置
# ================================================================
LOCAL_DATA_DIR = '/data/workspace/back_trader_stocks'
LOCAL_ETF_DIR = os.path.join(LOCAL_DATA_DIR, 'etf')
LOCAL_HK_DIR = os.path.join(LOCAL_DATA_DIR, 'hk')
LOCAL_CN_DIR = os.path.join(LOCAL_DATA_DIR, 'a')

INIT_CASH = 1_000_000
FEES_US = 0.000528
FEES_HK = 0.001348
FEES_CN = 0.0006
SLIPPAGE = 0.001

PERIODS = {
    'full_long': ('超长周期(2004-24)', '2004-01-01', '2024-12-31', 21.0),
    'full':      ('全周期(2015-24)',    '2015-01-01', '2024-12-31', 10.0),
    'bull1':     ('牛市1(2019-21)',     '2019-01-01', '2021-12-31', 3.0),
    'bear':      ('熊市(2022)',         '2022-01-01', '2022-12-31', 1.0),
    'range':     ('震荡(2023)',         '2023-01-01', '2023-12-31', 1.0),
    'bull2':     ('牛市2(2024)',        '2024-01-01', '2024-12-31', 1.0),
}

# ================================================================
# 三市场标的映射
# ================================================================
US_SECTOR_ETFS = {
    'XLK': '科技', 'XLF': '金融', 'XLE': '能源', 'XLV': '医疗',
    'XLI': '工业', 'XLB': '材料', 'XLY': '可选消费', 'XLP': '必选消费',
    'XLU': '公用事业', 'VNQ': '房地产',
}
US_BENCHMARK = 'SPY'

HK_SECTOR_MAP = {
    'hk00700': '科技(腾讯)', 'hk09988': '电商(阿里)', 'hk00005': '金融(汇丰)',
    'hk00011': '银行(恒生)', 'hk00002': '公用(中电)', 'hk01810': '新经济(小米)',
    'hk00388': '能源(中石化)',
}
HK_BENCHMARK = 'hk00700'

CN_SECTOR_MAP = {
    '510300_XSHG': '大盘(沪深300)', '159915_XSHE': '成长(创业板)',
    '510500_XSHG': '中盘(中证500)', '511010_XSHG': '国债',
    '518880_XSHG': '黄金',
}
CN_BENCHMARK = '510300_XSHG'


# ================================================================
# 数据加载
# ================================================================
def load_csv_data(filepath: str) -> pd.DataFrame:
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        df = df.dropna(subset=['Close'])
        return df
    except:
        return None


def load_market_data(market: str, symbols: list, benchmark: str) -> dict:
    dir_map = {'US': LOCAL_ETF_DIR, 'HK': LOCAL_HK_DIR, 'CN': LOCAL_CN_DIR}
    data_dir = dir_map.get(market, LOCAL_ETF_DIR)
    all_symbols = list(symbols) + ([benchmark] if benchmark not in symbols else [])
    
    loaded = {}
    print(f"  📦 从本地CSV加载{market}市场全量数据...")
    for sym in all_symbols:
        filepath = os.path.join(data_dir, f'{sym}.csv')
        df = load_csv_data(filepath)
        if df is not None and len(df) > 100:
            loaded[sym] = df
            print(f"    ✅ {sym}: {len(df)}个交易日 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")
        else:
            print(f"    ❌ {sym}: 数据不可用")
    return loaded


# ================================================================
# 回测引擎（v3 - 修复交易成本计算）
# ================================================================
def run_sector_momentum_backtest(close_prices: pd.DataFrame,
                                  benchmark_prices: pd.Series,
                                  start_date: str, end_date: str, years: float,
                                  market: str = 'US',
                                  lookback_months: int = 12,
                                  top_n: int = 3,
                                  use_trend_filter: bool = True,
                                  trend_lookback: int = 200) -> dict:
    """行业动量轮换策略回测"""
    risk_free_rates = {'US': 0.045, 'HK': 0.035, 'CN': 0.02}
    risk_free_rate = risk_free_rates.get(market, 0.045)
    fees_rate = {'US': FEES_US, 'HK': FEES_HK, 'CN': FEES_CN}.get(market, FEES_US)
    
    lookback_days = lookback_months * 21
    
    # 对齐benchmark
    bench_aligned = None
    sma200 = None
    if use_trend_filter and benchmark_prices is not None:
        bench_aligned = benchmark_prices.reindex(close_prices.index).ffill().bfill()
        sma200 = bench_aligned.rolling(window=trend_lookback, min_periods=trend_lookback).mean()
    
    # ⚠️ 关键修复：用全量数据计算信号，避免短周期因lookback不足无信号
    n_dates = len(close_prices)
    portfolio_returns = pd.Series(0.0, index=close_prices.index)
    
    last_rebalance_month = -1
    current_selected = []
    rebalance_costs = []  # (index, cost_pct)
    
    for i in range(n_dates):
        dt = close_prices.index[i]
        current_month = dt.year * 100 + dt.month
        
        # 趋势过滤
        in_market = True
        if use_trend_filter and sma200 is not None and i < len(sma200):
            sma_val = sma200.iloc[i]
            bench_val = bench_aligned.iloc[i]
            if pd.notna(sma_val) and pd.notna(bench_val) and bench_val < sma_val:
                in_market = False
        
        # 每月再平衡
        if current_month != last_rebalance_month and i >= lookback_days:
            last_rebalance_month = current_month
            prev_selected = current_selected[:]
            
            if in_market:
                momentum_scores = {}
                for col in close_prices.columns:
                    curr = close_prices.iloc[i][col]
                    past = close_prices.iloc[i - lookback_days][col]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        momentum_scores[col] = (curr - past) / past
                
                if momentum_scores:
                    sorted_assets = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
                    current_selected = [s for s, _ in sorted_assets[:top_n]]
                else:
                    current_selected = []
            else:
                current_selected = []
            
            if prev_selected != current_selected:
                n_sell = len(set(prev_selected) - set(current_selected))
                n_buy = len(set(current_selected) - set(prev_selected))
                turnover = (n_sell + n_buy) / (2 * top_n)
                cost = (fees_rate + SLIPPAGE) * turnover
                rebalance_costs.append((i, cost))
        
        # 计算当日收益（不含费用）
        if i > 0:
            for sym in current_selected:
                if sym in close_prices.columns:
                    ret = (close_prices.iloc[i][sym] - close_prices.iloc[i-1][sym]) / close_prices.iloc[i-1][sym]
                    if pd.notna(ret):
                        portfolio_returns.iloc[i] += ret / top_n
    
    # 累计净值（全量）
    cum = (1 + portfolio_returns).cumprod()
    for idx, cost in rebalance_costs:
        if idx > 0 and idx < len(cum):
            cum.iloc[idx:] *= (1 - cost)
    
    # ==================== 截取目标周期 ====================
    mask = (cum.index >= start_date) & (cum.index <= end_date)
    period_cum = cum.loc[mask]
    
    if len(period_cum) < 50:
        return None
    
    # 反算含费用的日收益率（全量，用于月度统计）
    adjusted_returns = cum.pct_change().fillna(0)
    # 截取目标区间的日收益率
    adj_ret_period = adjusted_returns.loc[mask]
    
    # ==================== 指标计算 ====================
    # 用周期起点归一化累计净值
    # 用实际数据覆盖的年数计算年化（而非理论区间年数）
    actual_years = max((period_cum.index[-1] - period_cum.index[0]).days / 365.25, 0.01)
    total_return = (period_cum.iloc[-1] / period_cum.iloc[0] - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / actual_years) - 1) * 100
    
    running_max = period_cum.cummax()
    dd = (period_cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100
    
    vol = adj_ret_period.std() * np.sqrt(252) * 100
    
    sharpe = 0
    if adj_ret_period.std() > 0:
        sharpe = (adj_ret_period.mean() - risk_free_rate / 252) / adj_ret_period.std() * np.sqrt(252)
    
    monthly_returns = (1 + adj_ret_period).resample('ME').prod() - 1
    monthly_sharpe = 0
    if monthly_returns.std() > 0:
        monthly_sharpe = (monthly_returns.mean() - risk_free_rate / 12) / monthly_returns.std() * np.sqrt(12)
    
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    gains = adj_ret_period[adj_ret_period > 0]
    losses = adj_ret_period[adj_ret_period < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    win_days = (adj_ret_period > 0).sum()
    total_active_days = (adj_ret_period != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100
    
    monthly_win_rate = (monthly_returns > 0).mean() * 100
    
    # 换仓次数（在目标区间内）
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    period_rebalances = [(idx, c) for idx, c in rebalance_costs 
                          if close_prices.index[idx] >= start_ts and close_prices.index[idx] <= end_ts]
    annual_trades = len(period_rebalances) / actual_years
    
    total_cost = sum(c for _, c in period_rebalances) * 100
    
    final_value = INIT_CASH * (1 + total_return / 100)
    
    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'monthly_sharpe': round(monthly_sharpe, 2),
        'calmar': round(calmar, 2),
        'volatility': round(vol, 2),
        'win_rate': round(win_rate, 1),
        'monthly_win_rate': round(monthly_win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'annual_trades': round(annual_trades, 1),
        'final_value': round(final_value, 2),
        'n_trading_days': len(period_cum),
        'total_cost_pct': round(total_cost, 2),
        'n_rebalances': len(period_rebalances),
    }


# ================================================================
# 主流程
# ================================================================
def main():
    print(f"\n{'#'*75}")
    print(f"  Sector Momentum Rotation Strategy - 三市场回测 v3")
    print(f"  Source: Quantpedia / Moskowitz & Grinblatt (1999)")
    print(f"  策略: 12月动量 → Top3等权 → 月度再平衡")
    print(f"  数据: 本地全量CSV | 交易成本: 净值扣除法")
    print(f"{'#'*75}")
    
    markets_config = [
        ('US', US_SECTOR_ETFS, US_BENCHMARK, '🇺🇸 美股'),
        ('HK', HK_SECTOR_MAP, HK_BENCHMARK, '🇭🇰 港股'),
        ('CN', CN_SECTOR_MAP, CN_BENCHMARK, '🇨🇳 A股'),
    ]
    
    all_results = {}
    
    for market_key, sector_map, benchmark, market_name in markets_config:
        print(f"\n{'='*75}")
        print(f"  {market_name} 市场 - 行业动量轮换策略")
        print(f"  板块标的: {', '.join([f'{k}({v})' for k, v in sector_map.items()])}")
        print(f"  基准: {benchmark}")
        print(f"{'='*75}")
        
        data = load_market_data(market_key, list(sector_map.keys()), benchmark)
        available_symbols = [s for s in sector_map.keys() if s in data]
        
        if len(available_symbols) < 3:
            print(f"  ❌ 可用标的不足3只，跳过")
            continue
        
        close_dict = {}
        for sym in available_symbols:
            series = data[sym]['Close']
            series.name = sym
            close_dict[sym] = series
        
        close_prices = pd.DataFrame(close_dict).dropna()
        benchmark_series = data[benchmark]['Close'] if benchmark in data else None
        
        print(f"  ✅ 有效数据: {len(available_symbols)}只标的, {len(close_prices)}个交易日")
        print(f"     日期范围: {close_prices.index[0].strftime('%Y-%m-%d')} ~ {close_prices.index[-1].strftime('%Y-%m-%d')}")
        
        market_results = {}
        for period_key, (period_name, start, end, years) in PERIODS.items():
            # 跳过数据不覆盖的区间
            if close_prices.index[0] > pd.Timestamp(end) or close_prices.index[-1] < pd.Timestamp(start):
                continue
            
            print(f"\n  📊 周期: {period_name} ({start} ~ {end})")
            
            r_filter = run_sector_momentum_backtest(
                close_prices, benchmark_series,
                start, end, years, market=market_key,
                lookback_months=12, top_n=3,
                use_trend_filter=True, trend_lookback=200
            )
            
            r_no_filter = run_sector_momentum_backtest(
                close_prices, benchmark_series,
                start, end, years, market=market_key,
                lookback_months=12, top_n=3,
                use_trend_filter=False, trend_lookback=200
            )
            
            if r_filter and r_no_filter:
                market_results[period_key] = {
                    'filtered': r_filter,
                    'unfiltered': r_no_filter,
                }
                print(f"     🔹 有趋势过滤: 年化{r_filter['annual_return']:+.2f}% | "
                      f"夏普{r_filter['monthly_sharpe']:.2f}(月) | "
                      f"回撤{r_filter['max_drawdown']:.2f}% | "
                      f"月胜率{r_filter['monthly_win_rate']:.1f}% | "
                      f"成本{r_filter['total_cost_pct']:.2f}%")
                print(f"     🔸 无趋势过滤: 年化{r_no_filter['annual_return']:+.2f}% | "
                      f"夏普{r_no_filter['monthly_sharpe']:.2f}(月) | "
                      f"回撤{r_no_filter['max_drawdown']:.2f}% | "
                      f"月胜率{r_no_filter['monthly_win_rate']:.1f}% | "
                      f"成本{r_no_filter['total_cost_pct']:.2f}%")
        
        all_results[market_key] = market_results
    
    # ================================================================
    # 汇总报告
    # ================================================================
    print(f"\n\n{'='*110}")
    print(f"  📊 三市场汇总对比")
    print(f"{'='*110}")
    
    for period_key, (period_name, _, _, _) in PERIODS.items():
        has_data = False
        for mk in markets_config:
            if all_results.get(mk[0], {}).get(period_key):
                has_data = True
                break
        if not has_data:
            continue
            
        print(f"\n  📅 {period_name}")
        print(f"  {'市场':<12} {'过滤':>4} {'年化%':>10} {'总收益%':>10} {'夏普(月)':>10} {'回撤%':>8} {'月胜率%':>8} {'盈亏比':>8} {'波动%':>8} {'换仓/年':>8} {'成本%':>8} {'交易日':>8}")
        print(f"  {'─'*105}")
        
        for market_key, _, _, market_name in markets_config:
            mr = all_results.get(market_key, {}).get(period_key)
            if not mr:
                continue
            for label, key in [('✅', 'filtered'), ('🔸', 'unfiltered')]:
                r = mr.get(key)
                if r:
                    print(f"  {market_name:<12} {label:>4} {r['annual_return']:>+10.2f} {r['total_return']:>+10.2f} "
                          f"{r['monthly_sharpe']:>10.2f} {r['max_drawdown']:>8.2f} "
                          f"{r['monthly_win_rate']:>8.1f} {r['profit_factor']:>8.2f} "
                          f"{r['volatility']:>8.2f} {r['annual_trades']:>8.1f} "
                          f"{r['total_cost_pct']:>8.2f} {r['n_trading_days']:>8}")
    
    # ================================================================
    # 推荐决策
    # ================================================================
    print(f"\n\n{'='*100}")
    print(f"  🎯 三市场推荐决策评估")
    print(f"{'='*100}")
    
    for market_key, _, _, market_name in markets_config:
        for period_key in ['full_long', 'full']:
            full_result = all_results.get(market_key, {}).get(period_key)
            if full_result:
                break
        if not full_result:
            continue
        
        for label, key in [('🔸 无趋势过滤', 'unfiltered'), ('✅ 有趋势过滤', 'filtered')]:
            r = full_result.get(key)
            if not r:
                continue
            print(f"\n  {market_name} - {label}:")
            
            target = {'US': 11.3, 'HK': 8.0, 'CN': 7.0}.get(market_key, 10)
            checks = [
                (f'年化收益 > {target}%', r['annual_return'] > target, f"{r['annual_return']:.2f}%"),
                ('月度胜率 > 55%', r['monthly_win_rate'] > 55, f"{r['monthly_win_rate']:.1f}%"),
                ('最大回撤 < 40%', r['max_drawdown'] < 40, f"{r['max_drawdown']:.2f}%"),
                ('月度夏普 > 0.5', r['monthly_sharpe'] > 0.5, f"{r['monthly_sharpe']:.2f}"),
                ('盈亏比 > 1.0', r['profit_factor'] > 1.0, f"{r['profit_factor']:.2f}"),
            ]
            
            passed = sum(1 for _, ok, _ in checks if ok)
            status = "✅ 推荐" if passed >= 4 else ("⚠️ 有条件推荐" if passed >= 3 else "❌ 未达标")
            print(f"    综合评级: {passed}/5 通过 {status}")
            for name, ok, val in checks:
                mark = "✅" if ok else "❌"
                print(f"    {mark} {name}: {val}")
        
        # 趋势过滤器对比
        r_f = full_result.get('filtered')
        r_u = full_result.get('unfiltered')
        if r_f and r_u:
            dd_improvement = r_u['max_drawdown'] - r_f['max_drawdown']
            annual_diff = r_f['annual_return'] - r_u['annual_return']
            print(f"\n    📊 趋势过滤器增量效果:")
            print(f"       回撤改善: {dd_improvement:+.2f}% ({r_u['max_drawdown']:.1f}% → {r_f['max_drawdown']:.1f}%)")
            print(f"       年化差异: {annual_diff:+.2f}% ({r_u['annual_return']:.1f}% → {r_f['annual_return']:.1f}%)")
            if dd_improvement > 5 and annual_diff > -3:
                print(f"       ✅ 价值显著：大幅降回撤且年化损失可控")
            elif annual_diff < -5:
                print(f"       ⚠️ 代价过高：年化损失{abs(annual_diff):.1f}%")
            else:
                print(f"       📊 效果中等")
    
    # ================================================================
    # 与Quantpedia参考对比
    # ================================================================
    print(f"\n\n{'='*100}")
    print(f"  📖 与Quantpedia参考业绩对比")
    print(f"{'='*100}")
    print(f"  参考（美股Sector ETFs, 12M动量Top3等权月度再平衡）:")
    print(f"    年化: 11.30% | 波动率: 6.90% | 夏普: 1.37 | 最大回撤: 29.40% | 胜率: 71%")
    print(f"    注: 参考波动率6.9%极低，可能为月度收益年化或含更早期数据")
    
    for period_label in ['full_long', 'full']:
        mr = all_results.get('US', {}).get(period_label)
        if mr and mr.get('unfiltered'):
            r = mr['unfiltered']
            pn = PERIODS[period_label][0]
            print(f"\n  本次回测（美股10只Sector ETFs - {pn}, 无趋势过滤）:")
            print(f"    年化: {r['annual_return']:.2f}% | 波动率: {r['volatility']:.2f}% | "
                  f"月夏普: {r['monthly_sharpe']:.2f} | 最大回撤: {r['max_drawdown']:.2f}% | "
                  f"月胜率: {r['monthly_win_rate']:.1f}% | 交易日: {r['n_trading_days']}")
            
            diff_annual = r['annual_return'] - 11.3
            diff_sharpe = r['monthly_sharpe'] - 1.37
            diff_dd = r['max_drawdown'] - 29.4
            
            print(f"  差异: 年化{diff_annual:+.2f}% | 月夏普{diff_sharpe:+.2f} | 回撤{diff_dd:+.2f}%")
            
            if abs(diff_annual) < 3:
                print(f"  ✅ 年化收益与参考基本一致，回测验证通过")
            elif diff_annual > 0:
                print(f"  📈 年化超越参考，可能因数据区间或趋势过滤差异")
            else:
                print(f"  📉 年化低于参考{abs(diff_annual):.1f}%，差距来源：")
                print(f"     - 波动率差异({r['volatility']:.1f}% vs 参考6.9%)")
                print(f"     - 2008金融危机回撤影响")
                print(f"     - 参考可能包含1970s-1990s更早期牛市")
                print(f"     - 交易成本(本次含{r['total_cost_pct']:.2f}%累计成本)")
            
            if mr.get('filtered'):
                r_f = mr['filtered']
                print(f"\n  有趋势过滤版 - {pn}:")
                print(f"    年化: {r_f['annual_return']:.2f}% | 月夏普: {r_f['monthly_sharpe']:.2f} | "
                      f"回撤: {r_f['max_drawdown']:.2f}% | 月胜率: {r_f['monthly_win_rate']:.1f}%")
            break


if __name__ == '__main__':
    main()
