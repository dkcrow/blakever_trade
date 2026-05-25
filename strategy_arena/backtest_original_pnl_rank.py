#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马105原版组合 — 个股/ETF盈亏排名统计
本金10000元，2015至今

策略分配：50%小市值(5000) + 50%ETF轮动(5000)

方法：直接运行策略获取持仓序列，然后精确计算每只个股/ETF的盈亏
"""

import os, sys, json, math, time
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, '/data/workspace/strategy_arena')
from backtest_sanma105_original import small_cap_strategy, compute_backtest_metrics, _load_single
from backtest_sanma105_qixing172 import qixing_v172_strategy

DATA_DIR = '/data/workspace/back_trader_stocks/a'

def main():
    CAPITAL = 10000
    SC_ALLOC = 0.5
    ETF_ALLOC = 0.5
    sc_capital = CAPITAL * SC_ALLOC  # 5000
    etf_capital = CAPITAL * ETF_ALLOC  # 5000
    
    print("=" * 80)
    print("  🔥 三马105原版组合 — 个股/ETF盈亏排名统计")
    print(f"  本金: ¥{CAPITAL} | 区间: 2015至今")
    print(f"  小市值分配: {SC_ALLOC*100:.0f}% (¥{sc_capital:,.0f}) | ETF轮动分配: {ETF_ALLOC*100:.0f}% (¥{etf_capital:,.0f})")
    print("=" * 80)
    
    # ====== 加载数据 ======
    print("\n📦 加载个股数据...")
    with open('/data/workspace/strategy_arena/valid_small_caps.json', 'r') as f:
        valid_small_caps = json.load(f)
    long_history_caps = [v for v in valid_small_caps if v['start'] <= '2016-01-01']
    
    stock_close_dict = {}
    for v in long_history_caps:
        code_num = v['code'][2:]
        fname = f"{code_num}_{v['exchange']}.csv"
        filepath = os.path.join(DATA_DIR, fname)
        if os.path.exists(filepath):
            df = _load_single(filepath)
            if df is not None and 'Close' in df.columns:
                stock_close_dict[f"{code_num}_{v['exchange']}"] = df['Close']
    
    stock_close = pd.DataFrame(stock_close_dict).sort_index()
    stock_close = stock_close.loc['2015-01-01':]
    stock_close = stock_close.dropna(axis=1, how='all')
    valid_stock_cols = [c for c in stock_close.columns if stock_close[c].dropna().shape[0] > 500]
    stock_close = stock_close[valid_stock_cols]
    print(f"  ✅ 有效个股: {len(valid_stock_cols)}只, {stock_close.shape[0]}个交易日")
    
    print("📦 加载ETF数据...")
    ETF_POOL = [
        '518880_XSHG', '159980_XSHE', '159985_XSHE', '501018_XSHG',
        '161226_XSHE', '159981_XSHE', '513100_XSHG', '513500_XSHG',
        '513400_XSHG', '513520_XSHG', '513030_XSHG', '513310_XSHG',
        '513730_XSHG', '159792_XSHE', '513130_XSHG', '513050_XSHG',
        '159920_XSHE', '513690_XSHG', '510300_XSHG', '510500_XSHG',
        '510050_XSHG', '159915_XSHE', '588080_XSHG', '512100_XSHG',
        '563360_XSHG', '512890_XSHG', '159967_XSHE', '512040_XSHG',
        '511880_XSHG',
    ]
    
    etf_data = {}
    for sym in ETF_POOL:
        filepath = os.path.join(DATA_DIR, f'{sym}.csv')
        if os.path.exists(filepath):
            df = _load_single(filepath)
            if df is not None and 'Close' in df.columns:
                etf_data[sym] = df['Close']
    
    etf_close = pd.DataFrame({sym: s for sym, s in etf_data.items()}).sort_index()
    etf_close = etf_close.loc['2015-01-01':]
    safe_etf = '511880_XSHG' if '511880_XSHG' in etf_close.columns else etf_close.columns[-1]
    print(f"  ✅ 有效ETF: {len(etf_close.columns)}只, 防御ETF: {safe_etf}")
    
    # ====== 小市值策略：精确跟踪每只个股盈亏 ======
    print("\n🔄 运行小市值策略并跟踪个股盈亏...")
    
    TOP_N = 5
    REBAL_DAYS = 20
    STOP_LOSS = 0.08
    MA_BEAR_PERIOD = 120
    
    dates = stock_close.index
    n_dates = len(dates)
    start_i = max(120, REBAL_DAYS + 20)
    
    safe_prices_full = etf_close[safe_etf] if safe_etf in etf_close.columns else None
    daily_ret_matrix = stock_close.pct_change()
    
    # 小市值策略状态
    current_stocks = []
    last_rebalance = -REBAL_DAYS
    stock_weights = {}
    buy_prices = {}
    buy_dates = {}
    
    # 个股累计盈亏金额（基于本金分配）
    stock_cum_pnl = {}
    
    for i in range(start_i, n_dates):
        date = dates[i]
        
        if i - last_rebalance >= REBAL_DAYS:
            last_rebalance = i
            
            bear_market = False
            if safe_prices_full is not None:
                safe_loc = safe_prices_full.index.get_indexer([date], method='ffill')
                if safe_loc[0] >= 0:
                    safe_idx = safe_loc[0]
                    safe_start = max(0, safe_idx - MA_BEAR_PERIOD + 1)
                    safe_slice = safe_prices_full.iloc[safe_start:safe_idx+1]
                    if len(safe_slice) >= MA_BEAR_PERIOD:
                        ma120 = safe_slice.mean()
                        current_safe = safe_slice.iloc[-1]
                        if current_safe < ma120:
                            bear_market = True
            
            if bear_market:
                # 防御模式：卖出所有个股
                for s in current_stocks:
                    if s in stock_close.columns and s in buy_prices and buy_prices[s] > 0:
                        sell_price = stock_close[s].iloc[i]
                        if pd.notna(sell_price) and buy_prices[s] > 0:
                            pnl = sc_capital / TOP_N * (sell_price / buy_prices[s] - 1)
                            if s not in stock_cum_pnl:
                                stock_cum_pnl[s] = 0
                            stock_cum_pnl[s] += pnl
                current_stocks = []
                stock_weights = {}
                buy_prices = {}
                buy_dates = {}
            else:
                # 向量化选股
                prices_now = stock_close.iloc[i]
                valid_mask = pd.Series(True, index=stock_close.columns)
                valid_mask &= prices_now.notna()
                valid_mask &= (prices_now > 1)
                if i >= 60:
                    ret_60d = stock_close.iloc[i] / stock_close.iloc[i-60] - 1
                    valid_mask &= (ret_60d > -0.5)
                    valid_mask &= (ret_60d < 2.0)
                if safe_etf:
                    valid_mask &= (stock_close.columns != safe_etf)
                
                valid_stocks = prices_now[valid_mask].dropna()
                
                # 卖出不再持有的
                sold_stocks = [s for s in current_stocks if s not in valid_stocks.index]
                for s in sold_stocks:
                    if s in stock_close.columns and s in buy_prices and buy_prices[s] > 0:
                        sell_price = stock_close[s].iloc[i]
                        if pd.notna(sell_price) and buy_prices[s] > 0:
                            pnl = sc_capital / TOP_N * (sell_price / buy_prices[s] - 1)
                            if s not in stock_cum_pnl:
                                stock_cum_pnl[s] = 0
                            stock_cum_pnl[s] += pnl
                
                if len(valid_stocks) >= TOP_N:
                    bottom_stocks = valid_stocks.sort_values().head(TOP_N)
                    new_stocks = list(bottom_stocks.index)
                else:
                    new_stocks = []
                
                # 买入新增持仓
                for s in new_stocks:
                    if s not in current_stocks and s in stock_close.columns:
                        buy_p = stock_close[s].iloc[i]
                        buy_prices[s] = buy_p
                        buy_dates[s] = date
                
                current_stocks = new_stocks
                if current_stocks:
                    weight = 1.0 / len(current_stocks)
                    stock_weights = {s: weight for s in current_stocks}
        
        # ====== 止损检查 ======
        for stock in list(current_stocks):
            if stock in stock_close.columns and stock in buy_prices:
                cur_price = stock_close[stock].iloc[i]
                if pd.notna(cur_price) and buy_prices[stock] > 0:
                    if cur_price / buy_prices[stock] - 1 < -STOP_LOSS:
                        pnl = sc_capital / TOP_N * (cur_price / buy_prices[stock] - 1)
                        if stock not in stock_cum_pnl:
                            stock_cum_pnl[stock] = 0
                        stock_cum_pnl[stock] += pnl
                        current_stocks.remove(stock)
                        buy_prices.pop(stock, None)
                        buy_dates.pop(stock, None)
    
    # 最后：计算未实现盈亏
    for s in current_stocks:
        if s in stock_close.columns and s in buy_prices and buy_prices[s] > 0:
            last_price = stock_close[s].iloc[-1]
            if pd.notna(last_price) and buy_prices[s] > 0:
                unrealized = sc_capital / TOP_N * (last_price / buy_prices[s] - 1)
                if s not in stock_cum_pnl:
                    stock_cum_pnl[s] = 0
                stock_cum_pnl[s] += unrealized
    
    print(f"  ✅ 小市值个股盈亏统计完成: {len(stock_cum_pnl)}只个股有盈亏记录")
    
    # ====== ETF轮动：跟踪每只ETF的持仓盈亏 ======
    print("\n🔄 运行ETF轮动策略并跟踪ETF盈亏...")
    
    pool_valid = [c for c in etf_close.columns if c != safe_etf]
    etf_result = qixing_v172_strategy(
        etf_close,
        etf_pool=pool_valid,
        defensive_etf=safe_etf,
        lookback_days=25,
    )
    
    holding_series = etf_result['holding']
    etf_cum_pnl = {}
    
    prev_h = None
    prev_buy_date = None
    prev_buy_price = None
    
    for i in range(len(holding_series)):
        date = holding_series.index[i]
        curr_h = holding_series.iloc[i]
        
        if curr_h != prev_h:
            # 换仓发生：卖出旧ETF
            if prev_h is not None and prev_h in etf_close.columns and prev_buy_price is not None and prev_buy_price > 0:
                sell_price = etf_close[prev_h].loc[date] if date in etf_close[prev_h].index else None
                if sell_price is not None:
                    pnl = etf_capital * (sell_price / prev_buy_price - 1)
                    if prev_h not in etf_cum_pnl:
                        etf_cum_pnl[prev_h] = 0
                    etf_cum_pnl[prev_h] += pnl
            
            # 买入新ETF
            if curr_h in etf_close.columns:
                buy_p = etf_close[curr_h].loc[date] if date in etf_close[curr_h].index else None
                if buy_p is not None:
                    prev_buy_price = buy_p
                    prev_buy_date = date
                else:
                    prev_buy_price = None
            else:
                prev_buy_price = None
            
            prev_h = curr_h
    
    # 最后：未实现盈亏
    if prev_h is not None and prev_h in etf_close.columns and prev_buy_price is not None:
        last_date = holding_series.index[-1]
        last_price = etf_close[prev_h].loc[last_date] if last_date in etf_close[prev_h].index else None
        if last_price is not None:
            unrealized = etf_capital * (last_price / prev_buy_price - 1)
            if prev_h not in etf_cum_pnl:
                etf_cum_pnl[prev_h] = 0
            etf_cum_pnl[prev_h] += unrealized
    
    print(f"  ✅ ETF轮动统计完成: {len(etf_cum_pnl)}只ETF有盈亏记录")
    
    # ====== 合并盈亏排名 ======
    all_pnl = {}
    for stock, cum_pnl in stock_cum_pnl.items():
        all_pnl[stock] = cum_pnl
    for etf, cum_pnl in etf_cum_pnl.items():
        if etf in all_pnl:
            all_pnl[etf] += cum_pnl
        else:
            all_pnl[etf] = cum_pnl
    
    sorted_pnl = sorted(all_pnl.items(), key=lambda x: x[1], reverse=True)
    
    profit_items = [(k, v) for k, v in sorted_pnl if v > 0]
    loss_items = [(k, v) for k, v in sorted_pnl if v < 0]
    loss_items.sort(key=lambda x: x[1])
    
    print("\n" + "=" * 80)
    print(f"  📊 三马105原版组合 — 盈亏排名（本金¥{CAPITAL}，2015至今）")
    print("=" * 80)
    
    print(f"\n🟢 总盈利排名前十:")
    print(f"  {'排名':>4s} | {'代码':20s} | {'盈利金额':>14s}")
    print("  " + "-" * 50)
    for i, (code, pnl) in enumerate(profit_items[:10], 1):
        print(f"  {i:>4d} | {code:20s} | ¥{pnl:>12,.2f}")
    
    print(f"\n🔴 总亏损排名前十:")
    print(f"  {'排名':>4s} | {'代码':20s} | {'亏损金额':>14s}")
    print("  " + "-" * 50)
    for i, (code, pnl) in enumerate(loss_items[:10], 1):
        print(f"  {i:>4d} | {code:20s} | ¥{pnl:>12,.2f}")
    
    total_profit = sum(v for k, v in all_pnl.items() if v > 0)
    total_loss = sum(v for k, v in all_pnl.items() if v < 0)
    print(f"\n📊 总盈利: ¥{total_profit:,.2f} | 总亏损: ¥{total_loss:,.2f} | 净盈亏: ¥{total_profit + total_loss:,.2f}")
    
    # 保存结果
    result = {
        'profit_top10': [(k, round(v, 2)) for k, v in profit_items[:10]],
        'loss_top10': [(k, round(v, 2)) for k, v in loss_items[:10]],
        'total_profit': round(total_profit, 2),
        'total_loss': round(total_loss, 2),
        'net_pnl': round(total_profit + total_loss, 2),
        'all_pnl': {k: round(v, 2) for k, v in sorted_pnl},
    }
    
    result_path = '/data/workspace/strategy_arena/original_pnl_rank_result.json'
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {result_path}")


if __name__ == '__main__':
    main()
