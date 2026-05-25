"""
策略参数配置 - Strategy Parameters Configuration
定义各策略的默认参数
"""

# ==================== EMA + ADX 策略参数 ====================
EMA_ADX_PARAMS = {
    'fast_ema': 12,
    'slow_ema': 26,
    'adx_period': 14,
    'adx_threshold': 25,
    'stop_loss': 0.05,
    'take_profit': 0.15,
}

# ==================== MACD 策略参数 ====================
MACD_PARAMS = {
    'fast_period': 12,
    'slow_period': 26,
    'signal_period': 9,
    'stop_loss': 0.05,
    'take_profit': 0.15,
}

# ==================== RSI 策略参数 ====================
RSI_PARAMS = {
    'rsi_period': 14,
    'oversold': 30,
    'overbought': 70,
    'stop_loss': 0.05,
    'take_profit': 0.10,
}

# ==================== 布林带策略参数 ====================
BOLLINGER_PARAMS = {
    'period': 20,
    'std_dev': 2,
    'stop_loss': 0.05,
    'take_profit': 0.12,
}

# ==================== SuperTrend 策略参数 ====================
SUPERTREND_PARAMS = {
    'atr_period': 10,
    'multiplier': 3.0,
    'stop_loss': 0.05,
    'take_profit': 0.15,
}

# ==================== Alpha因子策略参数 ====================
ALPHA_FACTOR_PARAMS = {
    'factors': {
        'value': ['pe', 'pb', 'ps', 'ev_ebitda'],
        'quality': ['roe', 'roa', 'roic', 'gross_margin'],
        'growth': ['revenue_growth', 'profit_growth', 'eps_growth'],
        'momentum': ['return_1m', 'return_3m', 'return_6m', 'return_12m'],
        'volatility': ['vol_3m', 'vol_6m', 'vol_12m', 'beta'],
        'liquidity': ['turnover', 'volume', 'amount'],
    },
    'weights': {
        'value': 0.20,
        'quality': 0.25,
        'growth': 0.20,
        'momentum': 0.15,
        'volatility': 0.10,
        'liquidity': 0.10,
    },
    'ic_threshold': 0.05,  # IC值阈值
    'top_n': 20,  # 选股数量
}

# ==================== 多因子策略参数 ====================
MULTI_FACTOR_PARAMS = {
    'factor_groups': ['value', 'quality', 'growth', 'momentum'],
    'weight_method': 'equal',  # 'equal', 'ic', 'ir'
    'rebalance_freq': '1w',  # 再平衡频率
    'stop_loss': 0.08,
    'take_profit': 0.20,
}

# ==================== Blakever 策略参数 ====================
BLAKEVER_PARAMS = {
    'v5': {
        'ema_fast': 12,
        'ema_slow': 26,
        'adx_threshold': 25,
        'regime_threshold': 0.60,
    },
    'v6': {
        'ema_fast': 12,
        'ema_slow': 26,
        'adx_threshold': 25,
        'regime_threshold': 0.60,
        'position_size': 0.10,
    },
    'v65': {
        'ema_fast': 12,
        'ema_slow': 26,
        'adx_threshold': 25,
        'regime_threshold': 0.60,
        'position_size': 0.10,
        'stop_loss': 0.05,
        'take_profit': 0.15,
    },
}

# ==================== 策略参数汇总 ====================
STRATEGY_PARAMS = {
    'ema_adx': EMA_ADX_PARAMS,
    'macd': MACD_PARAMS,
    'rsi': RSI_PARAMS,
    'bollinger': BOLLINGER_PARAMS,
    'supertrend': SUPERTREND_PARAMS,
    'alpha_factor': ALPHA_FACTOR_PARAMS,
    'multi_factor': MULTI_FACTOR_PARAMS,
    'blakever_v5': BLAKEVER_PARAMS['v5'],
    'blakever_v6': BLAKEVER_PARAMS['v6'],
    'blakever_v65': BLAKEVER_PARAMS['v65'],
}
