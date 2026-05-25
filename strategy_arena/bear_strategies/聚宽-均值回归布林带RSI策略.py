
# 策略: 聚宽-均值回归布林带RSI策略
# 来源: multi:joinquant_template
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:25:34

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "聚宽-均值回归布林带RSI策略"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {'period': 14.0}

# -*- coding: utf-8 -*-
"""
均值回归策略 — 布林带 + RSI，价格偏离均值时反向操作
来源: joinquant-skill/templates/05-mean-reversion.py
"""
import numpy as np

STOCKS = ['000001.XSHE', '600036.XSHG']   # 交易池
BB_PERIOD = 20        # 布林带周期
BB_WIDTH = 2.0        # 布林带宽度（标准差倍数）
RSI_PERIOD = 14       # RSI 周期
RSI_OVERSOLD = 30     # RSI 超卖阈值（买入信号）
RSI_OVERBOUGHT = 70   # RSI 超买阈值（卖出信号）
MAX_POS_PER_STOCK = 0.4  # 单只股票最大仓位比例


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.00246))
    g.stocks = STOCKS
    run_daily(trade, time='09:31')


def compute_rsi(prices, period=14):
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    return 100 - (100 / (1 + rs))


def trade(context):
    for stock in g.stocks:
        prices = attribute_history(stock, BB_PERIOD + 5, '1d', ['close'])['close']
        
        # 布林带
        mid = prices.rolling(BB_PERIOD).mean().iloc[-1]
        std = prices.rolling(BB_PERIOD).std().iloc[-1]
        upper = mid + BB_WIDTH * std
        lower = mid - BB_WIDTH * std
        
        # RSI
        rsi = compute_rsi(prices.values, RSI_PERIOD)
        
        current_price = prices.iloc[-1]
        pos = context.portfolio.positions.get(stock, None)
        has_pos = pos and pos.total_amount > 0
        
        # 买入: 价格触及下轨 + RSI超卖
        if current_price <= lower and rsi <= RSI_OVERSOLD and not has_pos:
            order_value(stock, context.portfolio.available_cash * MAX_POS_PER_STOCK)
        # 卖出: 价格触及上轨 + RSI超买
        elif current_price >= upper and rsi >= RSI_OVERBOUGHT and has_pos:
            order_target(stock, 0)

