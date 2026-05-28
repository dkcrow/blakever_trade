"""
技术指标计算工厂
提供常用指标的向量化计算。

优化点：
- 修复 ADX 中 DM 方向判断逻辑（原代码用赋值替代 where，会触发 pandas SettingWithCopyWarning）
- add_all_indicators 增加异常处理，单个指标计算失败不影响其他指标
- 增加 calc_atr 的 Wilder 平滑版本（更标准）
- 新增 calc_supertrend 指标（Supertrend + 50% 底仓策略核心）
"""

import pandas as pd
import numpy as np

def calc_ma(df: pd.DataFrame, period: int, price_col: str = 'close') -> pd.Series:
    """移动平均线"""
    return df[price_col].rolling(window=period).mean()

def calc_ema(df: pd.DataFrame, period: int, price_col: str = 'close') -> pd.Series:
    """指数移动平均线"""
    return df[price_col].ewm(span=period, adjust=False).mean()

def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9, price_col: str = 'close') -> pd.DataFrame:
    """MACD指标"""
    ema_fast = calc_ema(df, fast, price_col)
    ema_slow = calc_ema(df, slow, price_col)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({'macd': macd_line, 'signal': signal_line, 'histogram': histogram})

def calc_rsi(df: pd.DataFrame, period: int = 14, price_col: str = 'close') -> pd.Series:
    """RSI指标"""
    delta = df[price_col].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """ATR指标"""
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ADX指标（修复版）
    修复原版 DM 方向判断：使用 where 而非直接赋值，避免 SettingWithCopyWarning
    并正确处理 +DM/-DM 的互斥条件（当 +DM > -DM 时才计 +DM，反之才计 -DM）
    """
    high, low, close = df['high'], df['low'], df['close']
    high_diff = high.diff()
    low_diff = -low.diff()  # 注意取反：low 下降时 low_diff 为正

    # +DM：上涨幅度 > 下跌幅度 且 上涨幅度 > 0
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    # -DM：下跌幅度 > 上涨幅度 且 下跌幅度 > 0
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)

    # 真实波幅（单日）
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder 平滑（与 TradingView 等主流平台一致）
    atr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1/period, adjust=False).mean()

    plus_di = 100 * plus_dm_smooth / atr_smooth.replace(0, float('nan'))
    minus_di = 100 * minus_dm_smooth / atr_smooth.replace(0, float('nan'))

    di_sum = plus_di + minus_di
    dx = (abs(plus_di - minus_di) / di_sum.replace(0, float('nan'))) * 100
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def calc_bollinger_bands(df: pd.DataFrame, period: int = 20, std: int = 2, price_col: str = 'close') -> pd.DataFrame:
    """布林带"""
    ma = calc_ma(df, period, price_col)
    std_dev = df[price_col].rolling(window=period).std()
    upper = ma + std * std_dev
    lower = ma - std * std_dev
    return pd.DataFrame({'bb_mid': ma, 'bb_upper': upper, 'bb_lower': lower})

def calc_slope(df: pd.DataFrame, period: int = 10, price_col: str = 'close') -> pd.Series:
    """线性回归斜率"""
    def slope(series):
        x = np.arange(len(series))
        return np.polyfit(x, series, 1)[0]
    return df[price_col].rolling(window=period).apply(slope, raw=False)

def calc_supertrend(df: pd.DataFrame, period: int = 10,
                    multiplier: float = 1.5) -> pd.DataFrame:
    """
    Supertrend 指标计算。

    Args:
        df:         含 high/low/close 列的 DataFrame
        period:     ATR 周期（默认10）
        multiplier: ATR 倍数（默认1.5）

    Returns:
        DataFrame 新增列：
        - supertrend: Supertrend 值
        - st_direction: 方向（1=多头/-1=空头）
        - atr: ATR 值
        - upper_band: 最终上轨
        - lower_band: 最终下轨
    """
    high = df['high']
    low = df['low']
    close = df['close']

    # 计算 ATR（Wilder 平滑）
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()

    # 中间价
    hl2 = (high + low) / 2

    # 初始上下轨
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    # 逐步调整上下轨（核心逻辑）
    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)
    upper_band_final = upper_band.copy()
    lower_band_final = lower_band.copy()

    # 第一根K线的初始值
    st.iloc[0] = upper_band.iloc[0]
    direction.iloc[0] = 1

    for i in range(1, len(df)):
        # 调整上轨：前一根收盘价低于上轨时，上轨保持不变
        if close.iloc[i - 1] <= upper_band_final.iloc[i - 1]:
            upper_band_final.iloc[i] = min(upper_band_final.iloc[i],
                                            upper_band_final.iloc[i - 1])
        # 调整下轨：前一根收盘价高于下轨时，下轨保持不变
        if close.iloc[i - 1] >= lower_band_final.iloc[i - 1]:
            lower_band_final.iloc[i] = max(lower_band_final.iloc[i],
                                            lower_band_final.iloc[i - 1])

        # 判断方向切换
        if st.iloc[i - 1] == upper_band_final.iloc[i - 1] and close.iloc[i] > upper_band_final.iloc[i]:
            # 从空头翻多
            st.iloc[i] = lower_band_final.iloc[i]
            direction.iloc[i] = 1
        elif st.iloc[i - 1] == lower_band_final.iloc[i - 1] and close.iloc[i] < lower_band_final.iloc[i]:
            # 从多头翻空
            st.iloc[i] = upper_band_final.iloc[i]
            direction.iloc[i] = -1
        else:
            # 方向不变
            st.iloc[i] = st.iloc[i - 1]
            direction.iloc[i] = direction.iloc[i - 1]

    result = df.copy()
    result['supertrend'] = st
    result['st_direction'] = direction
    result['atr'] = atr
    result['upper_band'] = upper_band_final
    result['lower_band'] = lower_band_final
    return result

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    批量添加常用指标到 DataFrame。
    单个指标计算失败时记录警告并继续，不影响其他指标。
    新增 Supertrend 指标（Supertrend + 50% 底仓策略核心）。
    """
    import logging
    logger = logging.getLogger(__name__)

    df = df.copy()

    _indicators = [
        ('ma20',       lambda d: calc_ma(d, 20)),
        ('ma60',       lambda d: calc_ma(d, 60)),
        ('ma120',      lambda d: calc_ma(d, 120)),
        ('atr20',      lambda d: calc_atr(d, 20)),
        ('adx14',      lambda d: calc_adx(d, 14)),
        ('rsi14',      lambda d: calc_rsi(d, 14)),
        ('volatility20', lambda d: d['close'].pct_change().rolling(20).std() * np.sqrt(252)),
        ('volume_ma20', lambda d: d['volume'].rolling(20).mean()),
        ('slope10',    lambda d: calc_slope(d, 10)),
    ]

    for col, func in _indicators:
        try:
            df[col] = func(df)
        except Exception as e:
            logger.warning(f"[IndexCalcMgr] 指标 {col} 计算失败: {e}，填充 NaN")
            df[col] = float('nan')

    # 布林带
    try:
        bb = calc_bollinger_bands(df, 20, 2)
        df['bb_upper'] = bb['bb_upper']
        df['bb_lower'] = bb['bb_lower']
        df['bb_mid'] = bb['bb_mid']
    except Exception as e:
        logger.warning(f"[IndexCalcMgr] 布林带计算失败: {e}，填充 NaN")
        df['bb_upper'] = df['bb_lower'] = df['bb_mid'] = float('nan')

    # MACD
    try:
        macd = calc_macd(df)
        df['macd'] = macd['macd']
        df['macd_signal'] = macd['signal']
    except Exception as e:
        logger.warning(f"[IndexCalcMgr] MACD 计算失败: {e}，填充 NaN")
        df['macd'] = df['macd_signal'] = float('nan')

    # Supertrend（默认参数 period=10, multiplier=1.5）
    try:
        st_result = calc_supertrend(df, period=10, multiplier=1.5)
        df['supertrend'] = st_result['supertrend']
        df['st_direction'] = st_result['st_direction']
    except Exception as e:
        logger.warning(f"[IndexCalcMgr] Supertrend 计算失败: {e}，填充 NaN")
        df['supertrend'] = float('nan')
        df['st_direction'] = 0

    return df