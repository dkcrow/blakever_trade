#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股排行榜前二策略 近5年回测（使用原始策略代码）"""
import sys, os, json
sys.path.insert(0, '/data/workspace')
import numpy as np
import pandas as pd

# 修改原始脚本的回测区间
import seven_stars_etf_backtest as ss
ss.START_DATE = '2021-04-27'
ss.END_DATE = '2026-04-24'

from seven_stars_etf_backtest import (
    backtest_seven_stars, load_or_download_etf, load_all_etfs,
    DEFENSIVE_ETF, ETF_POOL_LARGE, ETF_NAMES
)

sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade

if __name__ == '__main__':
    print('🌟 七星高照ETF轮动 V1.7.2 — A股近5年回测(原始策略代码)')
    print('='*80)

    # 加载数据
    defensive_data = {}
    df = load_or_download_etf(DEFENSIVE_ETF)
    if not df.empty:
        defensive_data[DEFENSIVE_ETF] = df

    large_pool_unique = list(dict.fromkeys(ETF_POOL_LARGE))
    large_data = load_all_etfs(large_pool_unique)
    all_data_large = {**defensive_data, **large_data}
    actual_defensive = list(defensive_data.keys())[0] if defensive_data else None

    # 排行榜#1: 无成交量过滤
    print('\n📊 排行榜#1: 七星高照-大池-无成交量过滤')
    r1 = backtest_seven_stars(all_data_large, large_pool_unique,
        '七星高照-无成交量过滤(近5年)',
        use_volume_filter=False,
        defensive_etf_code=actual_defensive)

    # 排行榜#2: 大池完整版
    print('\n📊 排行榜#2: 七星高照-大池完整版')
    r2 = backtest_seven_stars(all_data_large, large_pool_unique,
        '七星高照-大池完整版(近5年)',
        defensive_etf_code=actual_defensive)

    # 额外变体
    print('\n📊 变体: 动量15天')
    r3 = backtest_seven_stars(all_data_large, large_pool_unique,
        '七星高照-动量15天(近5年)',
        lookback_days=15,
        defensive_etf_code=actual_defensive)

    print('\n📊 变体: 持仓2只')
    r4 = backtest_seven_stars(all_data_large, large_pool_unique,
        '七星高照-持仓2只(近5年)',
        holdings_num=2,
        defensive_etf_code=actual_defensive)

    # 汇总
    sep = '=' * 100
    print(f'\n\n{sep}')
    print('  📊 七星高照V1.7.2 A股近5年回测 — 最终汇总')
    print(sep)
    hdr = f'{"策略":35s} | {"年化%":>8s} | {"夏普":>6s} | {"回撤%":>7s} | {"胜率%":>6s} | {"盈亏比":>6s} | {"年交易":>5s} | {"评分":>6s} | {"等级":>4s}'
    print(hdr)
    print('-'*100)

    for r in [r1, r2, r3, r4]:
        if r:
            score = compute_total_score(
                annual_return=r['annual_return'],
                sharpe=r['sharpe'],
                max_drawdown=r['max_drawdown'],
                profit_factor=r['profit_factor'],
                win_rate=r['win_rate'],
                cross_period_robust=False,
                survivorship_bias=True,
                monthly_positive_rate=0.0,
            )
            print(f"{r['strategy_name']:35s} | {r['annual_return']:8.2f} | {r['sharpe']:6.2f} | {r['max_drawdown']:7.2f} | {r['win_rate']:6.1f} | {r['profit_factor']:6.2f} | {r['avg_trades_per_year']:5.1f} | {score['total_score']:6.1f} | {score['grade']:4s}")

    print(f"\n📋 对照：排行榜原始数据（2021-01-01~2025-04-24）")
    print(f"{'#1 无成交量过滤':35s} | {'212.51':>8s} | {'4.09':>6s} | {'11.95':>7s} | {'62.9':>6s} | {'3.96':>6s} | {'98.5':>5s} | {'74.51':>6s} | {'S':>4s}")
    print(f"{'#2 大池完整版':35s} | {'164.11':>8s} | {'3.67':>6s} | {'11.71':>7s} | {'63.2':>6s} | {'3.61':>6s} | {'98.5':>5s} | {'71.88':>6s} | {'S':>4s}")
