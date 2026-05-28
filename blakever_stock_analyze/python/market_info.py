"""
行情标准化接口
接收原始行情数据（DataFrame或Dict），输出统一格式的DataFrame。

优化点：
- standardize_ohlcv 集成技术指标计算，确保下游所有模块拿到的数据都已含指标列
- 增加数据长度校验（至少120行才能保证MA120有效）
- 增加异常处理
"""

import logging
import pandas as pd
from index_calc_mgr import add_all_indicators

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ['open', 'high', 'low', 'close', 'volume']
MIN_ROWS_FOR_INDICATORS = 120  # MA120 需要至少120行数据


def standardize_ohlcv(data: pd.DataFrame, symbol: str = None,
                      add_indicators: bool = True) -> pd.DataFrame:
    """
    将原始OHLCV数据标准化为统一列名和格式，并可选地添加技术指标。

    Args:
        data:           原始 DataFrame，列名可为大写或小写
        symbol:         股票代码（可选，添加 symbol 列）
        add_indicators: 是否自动添加技术指标（默认 True）
                        设为 False 时仅做列名标准化，适用于只需原始数据的场景

    Returns:
        标准化后的 DataFrame（含技术指标列，如 ma20/ma60/atr20/rsi14 等）

    Raises:
        ValueError: 缺少必要列时抛出
    """
    if data is None or (hasattr(data, 'empty') and data.empty):
        raise ValueError(f"[{symbol}] 输入数据为空")

    df = data.copy()
    # 列名统一为小写
    df.columns = [c.lower() for c in df.columns]

    # 检查必要列
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"[{symbol}] 缺少必要列: {missing}")

    # 确保按日期排序
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
    elif df.index.name == 'date' or isinstance(df.index, pd.DatetimeIndex):
        df = df.sort_index()
        df = df.reset_index()

    # 确保数值列为 float
    for col in REQUIRED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    if symbol:
        df['symbol'] = symbol

    # 数据长度预警
    if len(df) < MIN_ROWS_FOR_INDICATORS:
        logger.warning(
            f"[{symbol}] 数据行数={len(df)}，少于{MIN_ROWS_FOR_INDICATORS}行，"
            f"MA120/MA60等长周期指标将含大量NaN，结果可能不可靠"
        )

    # 添加技术指标（统一在此处计算，下游策略模块无需重复调用）
    if add_indicators and len(df) >= 20:
        try:
            df = add_all_indicators(df)
        except Exception as e:
            logger.error(f"[{symbol}] 技术指标计算失败: {e}，返回原始数据")

    return df


def standardize_quote(quote_dict: dict, symbol: str) -> dict:
    """
    标准化单条报价数据。

    Args:
        quote_dict: 原始报价字典，支持多种字段名格式
        symbol:     股票代码

    Returns:
        标准化报价字典
    """
    if not quote_dict:
        logger.warning(f"[{symbol}] 报价数据为空")
        return {'symbol': symbol, 'price': None, 'bid': None, 'ask': None,
                'volume': None, 'timestamp': None}

    price = (quote_dict.get('price')
             or quote_dict.get('close')
             or quote_dict.get('last')
             or quote_dict.get('regularMarketPrice'))

    return {
        'symbol': symbol,
        'price': float(price) if price is not None else None,
        'bid': quote_dict.get('bid'),
        'ask': quote_dict.get('ask'),
        'volume': quote_dict.get('volume'),
        'timestamp': quote_dict.get('timestamp') or quote_dict.get('regularMarketTime')
    }


def validate_indicator_columns(df: pd.DataFrame, symbol: str = '') -> dict:
    """
    校验 DataFrame 是否包含策略所需的技术指标列。
    供策略模块在使用数据前调用，替代各模块内部重复调用 add_all_indicators。

    Returns:
        {'valid': bool, 'missing_cols': list[str], 'warning': str}
    """
    required_indicator_cols = [
        'ma20', 'ma60', 'ma120', 'atr20', 'adx14', 'rsi14',
        'volatility20', 'volume_ma20', 'bb_upper', 'bb_lower', 'macd', 'slope10'
    ]
    missing = [c for c in required_indicator_cols if c not in df.columns]
    if missing:
        warning = f"[{symbol}] 缺少技术指标列: {missing}，请确保数据经过 standardize_ohlcv(add_indicators=True) 处理"
        logger.warning(warning)
        return {'valid': False, 'missing_cols': missing, 'warning': warning}
    return {'valid': True, 'missing_cols': [], 'warning': ''}
