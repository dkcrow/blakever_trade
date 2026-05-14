
# 策略: 聚宽-ETF轮动策略
# 来源: multi:joinquant_template
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:25:33

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "聚宽-ETF轮动策略"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

# -*- coding: utf-8 -*-
"""
ETF 轮动策略 — 在N个ETF中按近期动量排名，持有最强的TOP_K个
来源: joinquant-skill/templates/03-etf-rotation.py
"""

ETF_POOL = [
    '510300.XSHG',  # 沪深300ETF
    '510500.XSHG',  # 中证500ETF
    '159915.XSHE',  # 创业板ETF
    '518880.XSHG',  # 黄金ETF
    '511010.XSHG',  # 国债ETF
    '513100.XSHG',  # 纳指ETF
]
TOP_K = 2                # 持有最强的几个
LOOKBACK = 20            # 动量回看天数
REBALANCE_WEEKDAY = 1    # 每周几调仓 (1=周一)


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)

    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='fund')
    set_slippage(PriceRelatedSlippage(0.00246))

    g.etf_pool = ETF_POOL
    g.top_k = TOP_K
    g.lookback = LOOKBACK

    run_weekly(rebalance, weekday=REBALANCE_WEEKDAY, time='09:31')


def rebalance(context):
    # 计算每个ETF的动量得分
    scores = {}
    for etf in g.etf_pool:
        prices = attribute_history(etf, g.lookback + 1, '1d', ['close'])['close']
        momentum = (prices.iloc[-1] / prices.iloc[0]) - 1
        scores[etf] = momentum

    # 按动量排名
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    targets = [etf for etf, _ in ranked[:g.top_k]]

    # 卖出不在目标中的持仓
    for etf in context.portfolio.positions:
        if etf not in targets and context.portfolio.positions[etf].closeable_amount > 0:
            order_target(etf, 0)

    # 买入目标ETF（等权）
    weight = 1.0 / len(targets)
    for etf in targets:
        order_target_value(etf, context.portfolio.total_value * weight)

