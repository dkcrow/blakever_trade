"""
市场配置文件 - Market Configuration
定义各市场的交易规则和参数
"""

# ==================== A股配置 ====================
A_STOCK_CONFIG = {
    'name': 'A股',
    'code_prefix': ['sh', 'sz', 'bj'],
    'trading_hours': {
        'morning': ('09:30', '11:30'),
        'afternoon': ('13:00', '15:00'),
    },
    't1_settlement': True,  # T+1结算
    'min_price_unit': 0.01,  # 最小价格单位
    'limit_up_pct': 0.10,  # 涨停幅度（主板）
    'limit_down_pct': 0.10,  # 跌停幅度（主板）
    '创业板_limit_up': 0.20,  # 创业板涨停幅度
    '创业板_limit_down': 0.20,  # 创业板跌停幅度
    '科创板_limit_up': 0.20,  # 科创板涨停幅度
    '科创板_limit_down': 0.20,  # 科创板跌停幅度
    'min_trade_unit': 100,  # 最小交易单位（手）
}

# ==================== 港股配置 ====================
HK_STOCK_CONFIG = {
    'name': '港股',
    'code_prefix': ['hk'],
    'trading_hours': {
        'morning': ('09:30', '12:00'),
        'afternoon': ('13:00', '16:00'),
    },
    't2_settlement': True,  # T+2结算
    'min_price_unit': 0.001,  # 最小价格单位
    'limit_up_pct': None,  # 无涨跌幅限制
    'limit_down_pct': None,
    'min_trade_unit': 1,  # 最小交易单位（股）
    'currency': 'HKD',  # 货币单位
}

# ==================== 美股配置 ====================
US_STOCK_CONFIG = {
    'name': '美股',
    'code_prefix': ['us'],
    'trading_hours': {
        'regular': ('09:30', '16:00'),  # 美东时间
        'pre_market': ('04:00', '09:30'),
        'after_hours': ('16:00', '20:00'),
    },
    't2_settlement': True,  # T+2结算
    'min_price_unit': 0.01,  # 最小价格单位
    'limit_up_pct': None,  # 无涨跌幅限制
    'limit_down_pct': None,
    'min_trade_unit': 1,  # 最小交易单位（股）
    'currency': 'USD',  # 货币单位
    'timezone': 'US/Eastern',  # 时区
}

# ==================== ETF配置 ====================
ETF_CONFIG = {
    'name': 'ETF',
    'code_prefix': ['sh', 'sz'],
    'min_trade_unit': 100,  # 最小交易单位（份）
    'commission': 0.0003,  # ETF交易佣金（万三）
}

# ==================== 市场配置汇总 ====================
MARKET_CONFIG = {
    'a_stock': A_STOCK_CONFIG,
    'hk_stock': HK_STOCK_CONFIG,
    'us_stock': US_STOCK_CONFIG,
    'etf': ETF_CONFIG,
}
