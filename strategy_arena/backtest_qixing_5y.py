#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股排行榜前二策略（七星高照V1.7.2）近5年回测
- 无成交量过滤版（排行榜#1，原年化212.51%）
- 大池完整版（排行榜#2，原年化164.11%）
"""
import sys, os, math, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from qixing_cross_market import (
    qixing_rotation_backtest, load_market_pool, load_csv_data,
    CN_BIG_POOL, CN_DIR, FEES_RATE, SLIPPAGE, INIT_CASH, RISK_FREE_RATE
)

# 近5年
START_5Y = '2021-04-27'
END_5Y = '2026-04-24'

# 全区间（对照组）
START_ALL = '2019-01-02'
END_ALL = '2026-04-24'


def run_cn_backtest(label, start, end, **kwargs):
    """运行A股大池回测"""
    print(f"\n{'='*70}")
    print(f"  📊 {label}")
    print(f"  区间: {start} ~ {end}")
    print(f"{'='*70}")
    
    # 加载A股38只大池
    cn_data, loaded, missing = load_market_pool(CN_BIG_POOL, CN_DIR)
    print(f"  加载A股ETF: {loaded}只")
    if missing:
        print(f"  缺失: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    
    if not cn_data:
        print("  ❌ 无数据")
        return None
    
    # 防御ETF: 511880(银华日利)
    safe = '511880_XSHG'
    if safe not in cn_data:
        safe = list(cn_data.keys())[-1]
        print(f"  ⚠️ 511880不可用，使用 {safe} 作为防御ETF")
    
    result = qixing_rotation_backtest(
        price_data=cn_data,
        safe_asset=safe,
        start_date=start,
        end_date=end,
        fees_rate=FEES_RATE,
        market_label='A股',
        **kwargs,
    )
    
    if result:
        print(f"\n  📈 回测结果:")
        print(f"     年化收益: {result['annual_return']:+.2f}%")
        print(f"     最大回撤: {result['max_drawdown']:.2f}%")
        print(f"     夏普比率: {result['sharpe']:.2f}")
        print(f"     Calmar:   {result['calmar']:.2f}")
        print(f"     胜率:     {result['win_rate']:.1f}%")
        print(f"     盈亏比:   {result['profit_factor']:.2f}")
        print(f"     年交易:   {result['avg_trades_per_year']:.1f}次")
        print(f"     V4评分:   {result['total_score']:.1f} ({result['grade']})")
        print(f"     持仓分布: {json.dumps(result['holding_distribution'], ensure_ascii=False, indent=6)}")
    else:
        print("  ❌ 回测失败")
    
    return result


if __name__ == '__main__':
    print("🌟 七星高照ETF轮动V1.7.2 — A股近5年回测")
    print("=" * 70)
    
    results = {}
    
    # ===== 策略1: 无成交量过滤（排行榜#1）=====
    # 全区间
    results['全量_无成交量'] = run_cn_backtest(
        '策略1: 七星高照-无成交量过滤 (全区间2019-2026)',
        START_ALL, END_ALL,
    )
    # 近5年
    results['5年_无成交量'] = run_cn_backtest(
        '策略1: 七星高照-无成交量过滤 (近5年)',
        START_5Y, END_5Y,
    )
    
    # ===== 参数变体（近5年）=====
    # 更宽松的急跌过滤
    results['5年_宽松急跌'] = run_cn_backtest(
        '策略1变种: 宽松急跌(-8%) (近5年)',
        START_5Y, END_5Y,
        drop_filter_threshold=-0.08,
    )
    
    # 短周期
    results['5年_短周期'] = run_cn_backtest(
        '策略1变种: 短周期(15日) (近5年)',
        START_5Y, END_5Y,
        lookback_days=15,
    )
    
    # 长周期
    results['5年_长周期'] = run_cn_backtest(
        '策略1变种: 长周期(40日) (近5年)',
        START_5Y, END_5Y,
        lookback_days=40,
    )
    
    # ===== 汇总 =====
    print(f"\n\n{'='*70}")
    print(f"  📊 汇总对比")
    print(f"{'='*70}")
    print(f"{'配置':30s} | {'年化%':>8s} | {'夏普':>6s} | {'回撤%':>7s} | {'胜率%':>6s} | {'盈亏比':>6s} | {'评分':>6s} | {'等级':>4s}")
    print('-' * 100)
    
    for name, r in results.items():
        if r:
            print(f"{name:30s} | {r['annual_return']:8.2f} | {r['sharpe']:6.2f} | {r['max_drawdown']:7.2f} | {r['win_rate']:6.1f} | {r['profit_factor']:6.2f} | {r['total_score']:6.1f} | {r['grade']:4s}")
    
    print(f"\n📋 对照：排行榜原始数据（聚宽回测，全区间）")
    print(f"{'#1 无成交量过滤':30s} | {'212.51':>8s} | {'4.09':>6s} | {'11.95':>7s} | {'62.9':>6s} | {'3.96':>6s} | {'74.51':>6s} | {'S':>4s}")
    print(f"{'#2 大池完整版':30s} | {'164.11':>8s} | {'3.67':>6s} | {'11.71':>7s} | {'63.2':>6s} | {'3.61':>6s} | {'71.88':>6s} | {'S':>4s}")
