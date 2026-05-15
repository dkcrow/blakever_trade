
# 策略: 聚宽-截面动量选股策略
# 来源: multi:joinquant_template
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:25:34

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "聚宽-截面动量选股策略"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

# -*- coding: utf-8 -*-
"""
截面动量选股策略 — 周度调仓，从全A股中选近期涨幅最大的N只持有
来源: joinquant-skill/templates/04-momentum-stock.py
"""
from jqdata import *

UNIVERSE = '000905.XSHG'  # 股票池来源（中证500）
HOLD_NUM = 20              # 持仓数量
LOOKBACK = 20              # 动量回看天数
MIN_MARKET_CAP = 30        # 最低市值（亿元），过滤壳股


def initialize(context):
    set_benchmark(UNIVERSE)
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.00246))
    run_weekly(rebalance, weekday=1, time='09:31')


def rebalance(context):
    stocks = get_index_stocks(UNIVERSE)
    
    # 过滤: 剔除ST、停牌、次新
    current_data = get_current_data()
    stocks = [s for s in stocks if not current_data[s].paused and not current_data[s].is_st]
    
    # 过滤市值
    q = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(stocks))
    df = get_fundamentals(q).dropna()
    df = df[df['market_cap'] >= MIN_MARKET_CAP]
    stocks = df['code'].tolist()
    
    # 计算动量
    momentum = {}
    for code in stocks:
        prices = attribute_history(code, LOOKBACK + 1, '1d', ['close'])['close']
        momentum[code] = (prices.iloc[-1] / prices.iloc[0]) - 1
    
    # 选动量最强的
    ranked = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
    selected = [s for s, _ in ranked[:HOLD_NUM]]
    
    # 调仓
    for stock in context.portfolio.positions:
        if stock not in selected:
            order_target(stock, 0)
    
    weight = 1.0 / HOLD_NUM
    for stock in selected:
        order_target_value(stock, context.portfolio.total_value * weight)

