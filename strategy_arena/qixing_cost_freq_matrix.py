#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易成本×调仓频率 组合回测"""
import pandas as pd, numpy as np, math, sys
sys.path.insert(0, 'strategy_arena')
from qixing_cross_market_v3 import qixing_rotation_strategy, load_etf_data, vectorized_backtest
from qixing_cross_market_v3 import CN_ETF_POOL, CN_SAFE, US_ETF_POOL, US_SAFE, HK_ETF_POOL, HK_SAFE

cost_configs = [
    ('标准(万10+0.1%滑)', 0.001, 0.001),
    ('低佣(万2.5+0.1%滑)', 0.00025, 0.001),
    ('聚宽(万2.5无滑)', 0.00025, 0),
    ('零成本', 0, 0),
]

freq_configs = [
    ('W-FRI', '周频'),
    ('2W-FRI', '双周'),
    ('ME', '月频'),
    ('2ME', '双月'),
]

for market, pool, safe, data_dir, rf, mlabel in [
    ('CN', list(CN_ETF_POOL.keys()), CN_SAFE, 'back_trader_stocks/a', 0.02, 'A股'),
    ('US', list(US_ETF_POOL.keys()), US_SAFE, 'back_trader_stocks/etf', 0.045, '美股'),
    ('HK', list(HK_ETF_POOL.keys()), HK_SAFE, 'back_trader_stocks/hk_etf', 0.035, '港股'),
]:
    raw = load_etf_data(pool, data_dir)
    if len(raw) < 3:
        continue
    close_df = pd.DataFrame({sym: df['Close'] for sym, df in raw.items()}).sort_index()
    close_df = close_df.loc['2019-01-01':'2026-04-25'].dropna(axis=1, how='all')
    valid_cols = [c for c in close_df.columns if close_df[c].dropna().shape[0] > 300]
    close_df = close_df[valid_cols]
    safe_valid = [a for a in safe if a in valid_cols]
    pool_valid = [a for a in pool if a in valid_cols]

    sep = '=' * 90
    print(f'\n{sep}')
    print(f'  {mlabel}市场 — 交易成本 x 调仓频率 组合回测')
    print(f'{sep}')
    header = f'{"调仓":6s} | {"成本配置":22s} | {"年化%":>8s} | {"夏普":>6s} | {"回撤%":>7s} | {"盈亏比":>6s} | {"评分":>6s} | {"等级":>4s}'
    print(header)
    print('-' * 90)

    for freq_code, freq_label in freq_configs:
        for cc_name, cc_fees, cc_slip in cost_configs:
            holding = qixing_rotation_strategy(close_df, pool_valid, safe_valid,
                short_lookback=25, long_lookback=250, drop_threshold=0.95, rebalance_freq=freq_code)
            result = vectorized_backtest(close_df, holding,
                fees_rate=cc_fees, slippage=cc_slip, risk_free_rate=rf)
            if result:
                ann = result['annual_return']
                sh = result['sharpe']
                dd = result['max_drawdown']
                pf = result['profit_factor']
                sc = result['total_score']
                gr = result['grade']
                print(f'{freq_label:6s} | {cc_name:22s} | {ann:8.1f} | {sh:6.2f} | {dd:7.1f} | {pf:6.2f} | {sc:6.1f} | {gr:4s}')
