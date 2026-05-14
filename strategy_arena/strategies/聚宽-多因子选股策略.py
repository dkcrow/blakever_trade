
# 策略: 聚宽-多因子选股策略
# 来源: multi:joinquant_template
# 自动生成时间: 2026-04-30 20:23:13

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "聚宽-多因子选股策略"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

# -*- coding: utf-8 -*-
"""
多因子选股策略 — 月度调仓，从指数成分股中按PE/市值/动量多因子打分选股
来源: joinquant-skill/templates/02-multi-factor.py
"""
from jqdata import *
from jqfactor import get_factor_values

INDEX = '000300.XSHG'   # 股票池来源（沪深300）
HOLD_NUM = 10            # 持仓股票数量


def initialize(context):
    set_benchmark(INDEX)
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.00246))
    run_monthly(rebalance, monthday=1, time='09:31')


def rebalance(context):
    stocks = get_index_stocks(INDEX)
    
    # 因子1: PE（低PE好）
    q_pe = query(valuation.code, valuation.pe_ratio).filter(valuation.code.in_(stocks))
    df_pe = get_fundamentals(q_pe).dropna()
    
    # 因子2: 市值（中市值好）
    q_cap = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(stocks))
    df_cap = get_fundamentals(q_cap).dropna()
    
    # 因子3: 动量（近期涨幅大好）
    q_mom = query(valuation.code).filter(valuation.code.in_(stocks))
    mom_scores = {}
    for code in stocks:
        prices = attribute_history(code, 20, '1d', ['close'])['close']
        mom_scores[code] = (prices.iloc[-1] / prices.iloc[0]) - 1
    
    # 合并打分
    df_pe['pe_rank'] = df_pe['pe_ratio'].rank(ascending=True)
    df_cap['cap_rank'] = df_cap['market_cap'].rank(ascending=False)
    
    combined = df_pe.merge(df_cap, on='code')
    combined['mom'] = combined['code'].map(mom_scores)
    combined['mom_rank'] = combined['mom'].rank(ascending=False)
    combined['total_rank'] = combined['pe_rank'] + combined['cap_rank'] + combined['mom_rank']
    
    # 选排名前N
    selected = combined.nsmallest(HOLD_NUM, 'total_rank')['code'].tolist()
    
    # 调仓
    for stock in context.portfolio.positions:
        if stock not in selected:
            order_target(stock, 0)
    
    weight = 1.0 / HOLD_NUM
    for stock in selected:
        order_target_value(stock, context.portfolio.total_value * weight)

