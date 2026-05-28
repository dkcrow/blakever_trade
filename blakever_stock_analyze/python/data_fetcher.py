"""
行情数据获取模块（Agent 9）
职责：Blakever 系统唯一的行情数据入口。

核心功能：
1. 优先通过 westock-data 获取行情数据（无限流、速度快）
2. yfinance 作为降级备选（仅 westock-data 不可用或数据缺失时使用）
3. 调用 market_info 标准化封装
4. 分发给请求方 Agent

禁止在模块外直接返回未标准化的原始数据。
"""

import logging
import subprocess
import os
import pandas as pd
from typing import Optional, Union

logger = logging.getLogger(__name__)

# ── westock-data 配置 ──
WESTOCK_SCRIPT = "/data/workspace/.agent/skills/westock-data/scripts/index.js"
WESTOCK_CWD = "/data/workspace"
WESTOCK_AVAILABLE = os.path.exists(WESTOCK_SCRIPT)

if not WESTOCK_AVAILABLE:
    logger.warning("[DataFetcher] westock-data 脚本不存在，将使用 yfinance 备选")

# ── yfinance 备选 ──
try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False
    logger.warning("[DataFetcher] yfinance 未安装，行情获取功能不可用。请安装: pip install yfinance")

from market_info import standardize_ohlcv, standardize_quote

# ── 代码映射 ──
# westock-data 使用的代码格式与内部代码不同
# 美股: usAAPL, usSPY 等；指数: us.INX (S&P500)
WESTOCK_SYMBOL_MAP = {
    'SPY': 'usSPY',
    'QQQ': 'usQQQ',
    'AAPL': 'usAAPL',
    'MSFT': 'usMSFT',
    'GOOGL': 'usGOOGL',
    'AMZN': 'usAMZN',
    'NVDA': 'usNVDA',
    'JPM': 'usJPM',
    'JNJ': 'usJNJ',
    'PG': 'usPG',
    'XOM': 'usXOM',
    'TSLA': 'usTSLA',
    'VIXY': 'usVIXY.AM',     # VIX短期期货ETF（VIX指数代理）
    'IEF': 'usIEF.OQ',       # 7-10年国债ETF（TNX代理）
    '.INX': 'us.INX',        # S&P 500 指数
    # 港股指数 westock-data 不支持，不在此映射
    # HSI / HSTECH 会由 to_westock_symbol 返回 None，降级到 yfinance
}

# yfinance 使用的代码格式
YF_SYMBOL_MAP = {
    'SPY': 'SPY',
    'QQQ': 'QQQ',
    'HSI': '^HSI',
    'HSTECH': '^HSTECH',
    'VIX': '^VIX',
    'TNX': '^TNX',
    'IXIC': '^IXIC',
    'DJI': '^DJI',
}


def to_westock_symbol(internal_symbol: str) -> str:
    """
    将内部代码转换为 westock-data 代码格式。

    规则：
    - 已在 WESTOCK_SYMBOL_MAP 中的直接映射
    - 美股（无.HK后缀）: us{SYMBOL}，如 AAPL → usAAPL, BRK-B → usBRK-B
    - 港股（.HK后缀）: westock-data 不支持，返回 None（降级到 yfinance）
    - 港股指数（HSI/HSTECH）: westock-data 不支持，返回 None
    """
    if internal_symbol in WESTOCK_SYMBOL_MAP:
        return WESTOCK_SYMBOL_MAP[internal_symbol]
    # 港股指数和港股个股 westock-data 均不支持
    if internal_symbol.endswith('.HK') or internal_symbol in ('HSI', 'HSTECH'):
        return None
    return f'us{internal_symbol}'


def to_yfinance_symbol(internal_symbol: str) -> str:
    """
    将内部代码转换为 yfinance 代码格式。

    规则：
    - 已在 YF_SYMBOL_MAP 中的直接映射
    - 港股（.HK后缀）: 直接使用，如 0700.HK
    - 美股: 直接使用，如 AAPL
    """
    if internal_symbol in YF_SYMBOL_MAP:
        return YF_SYMBOL_MAP[internal_symbol]
    # 港股和美股内部代码即 yfinance 代码
    return internal_symbol


def _check_data_source():
    """检查是否有可用的数据源"""
    if not WESTOCK_AVAILABLE and not YF_AVAILABLE:
        raise RuntimeError("westock-data 和 yfinance 均不可用，无法获取行情数据")


# ══════════════════════════════════════════════════════════
# westock-data 数据获取（优先使用）
# ══════════════════════════════════════════════════════════

def _ws_fetch_kline(symbols: Union[str, list], period: str = 'day',
                    limit: int = 250) -> dict:
    """
    通过 westock-data CLI 获取K线数据，返回原始DataFrame字典。

    Args:
        symbols: 内部代码列表（如 ['SPY', 'AAPL']）
        period:  K线周期（day/week/month）
        limit:   数据条数

    Returns:
        {symbol: DataFrame, ...} 原始 DataFrame（列: date, open, close, high, low, volume, amount）
    """
    if isinstance(symbols, str):
        symbols = [symbols]

    # 转换为 westock-data 代码（港股返回 None，需降级）
    ws_symbols = [to_westock_symbol(s) for s in symbols]
    # 分离：westock-data 可获取 vs 需降级到 yfinance
    ws_supported = [(s, ws) for s, ws in zip(symbols, ws_symbols) if ws is not None]
    yf_needed = [s for s, ws in zip(symbols, ws_symbols) if ws is None]

    if not ws_supported:
        # 全部是港股或其他 westock 不支持的代码，直接走 yfinance
        logger.info(f"[DataFetcher] {symbols} 均不支持 westock-data，降级使用 yfinance")
        if YF_AVAILABLE:
            return _yf_fetch_ohlcv(symbols, period='1y', add_indicators=True)
        return {}

    ws_codes = ','.join(ws for _, ws in ws_supported)

    cmd = ['node', WESTOCK_SCRIPT, 'kline', ws_codes,
           '--period', period, '--limit', str(limit)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=WESTOCK_CWD, timeout=30)
    except subprocess.TimeoutExpired:
        logger.error("[DataFetcher] westock-data 请求超时")
        return {}
    except Exception as e:
        logger.error(f"[DataFetcher] westock-data 执行失败: {e}")
        return {}

    if result.returncode != 0:
        logger.error(f"[DataFetcher] westock-data 错误: {result.stderr.strip()}")
        return {}

    # 解析输出（只传入 westock 支持的代码）
    ws_supported_symbols = [s for s, _ in ws_supported]
    ws_supported_codes = [ws for _, ws in ws_supported]
    results = _parse_ws_kline_output(result.stdout, ws_supported_symbols, ws_supported_codes)

    # 对 westock 不支持的港股，降级到 yfinance
    if yf_needed and YF_AVAILABLE:
        logger.info(f"[DataFetcher] westock-data 不支持 {yf_needed}，降级使用 yfinance")
        yf_results = _yf_fetch_ohlcv(yf_needed, period='1y', add_indicators=True)
        results.update(yf_results)

    return results


def _parse_ws_kline_output(stdout: str, symbols: list, ws_symbols: list) -> dict:
    """解析 westock-data kline 的 Markdown 表格输出"""
    lines = stdout.strip().split('\n')

    # 检测是否为 Batch 模式输出
    is_batch = any('[Batch]' in line for line in lines[:5])

    results = {}
    if is_batch:
        # Batch 模式：数据按 symbol 列分组
        ws_to_internal = {ws: s for ws, s in zip(ws_symbols, symbols)}
        current_ws_symbol = None
        data_rows = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and 'symbol' in stripped.lower() and 'date' in stripped.lower():
                # 表头行，跳过
                continue
            elif stripped.startswith('|') and stripped.replace('|', '').replace('-', '').replace(' ', '') == '':
                # 分隔行，跳过
                continue
            elif stripped.startswith('|'):
                parts = [p.strip() for p in stripped.split('|') if p.strip()]
                if len(parts) >= 7:
                    # 判断是否有 symbol 列（Batch 模式第一列是 symbol）
                    first_part = parts[0]
                    if first_part in ws_to_internal:
                        # 新的 symbol 开始，保存之前的
                        if current_ws_symbol and data_rows:
                            internal_sym = ws_to_internal.get(current_ws_symbol, current_ws_symbol)
                            df = _build_kline_df(data_rows)
                            if df is not None and not df.empty:
                                results[internal_sym] = df
                        current_ws_symbol = first_part
                        data_rows = [parts[1:]]  # 剩余列是数据
                    else:
                        data_rows.append(parts)
            elif '[Batch]' in stripped:
                continue

        # 保存最后一组
        if current_ws_symbol and data_rows:
            internal_sym = ws_to_internal.get(current_ws_symbol, current_ws_symbol)
            df = _build_kline_df(data_rows)
            if df is not None and not df.empty:
                results[internal_sym] = df
    else:
        # 单股模式
        data_rows = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and ('date' in stripped.lower()):
                continue
            elif stripped.startswith('|') and stripped.replace('|', '').replace('-', '').replace(' ', '') == '':
                continue
            elif stripped.startswith('|'):
                parts = [p.strip() for p in stripped.split('|') if p.strip()]
                if len(parts) >= 6 and parts[0].startswith('20'):
                    data_rows.append(parts)

        if data_rows and len(symbols) == 1:
            df = _build_kline_df(data_rows)
            if df is not None and not df.empty:
                results[symbols[0]] = df

    return results


def _build_kline_df(data_rows: list) -> Optional[pd.DataFrame]:
    """将解析出的数据行构建为 DataFrame"""
    records = []
    for row in data_rows:
        try:
            if len(row) >= 6:
                records.append({
                    'date': pd.to_datetime(row[0]),
                    'open': float(row[1]),
                    'close': float(row[2]),  # westock 用 last，但解析时已统一
                    'high': float(row[3]),
                    'low': float(row[4]),
                    'volume': float(row[5]) if len(row) > 5 and row[5] not in ('0', '') else 0,
                    'amount': float(row[6]) if len(row) > 6 and row[6] not in ('0', '') else 0,
                })
        except (ValueError, IndexError) as e:
            continue

    if not records:
        return None

    df = pd.DataFrame(records).set_index('date').sort_index()
    return df


def _ws_fetch_quote(symbols: Union[str, list]) -> dict:
    """
    通过 westock-data quote 命令获取实时行情+基本面数据。

    Returns:
        {symbol: quote_dict, ...}  包含 price, market_cap, pe_ratio, dividend_ratio 等
    """
    if isinstance(symbols, str):
        symbols = [symbols]

    ws_symbols = [to_westock_symbol(s) for s in symbols]
    # 分离：westock-data 可获取 vs 需降级
    ws_supported = [(s, ws) for s, ws in zip(symbols, ws_symbols) if ws is not None]
    yf_needed = [s for s, ws in zip(symbols, ws_symbols) if ws is None]

    if not ws_supported:
        # 全部是港股，直接走 yfinance
        logger.info(f"[DataFetcher] quote: {symbols} 均不支持 westock-data，降级使用 yfinance")
        if YF_AVAILABLE:
            return _yf_fetch_quote_fallback(yf_needed)
        return {}

    ws_codes = ','.join(ws for _, ws in ws_supported)

    cmd = ['node', WESTOCK_SCRIPT, 'quote', ws_codes]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=WESTOCK_CWD, timeout=30)
    except Exception as e:
        logger.error(f"[DataFetcher] westock-data quote 执行失败: {e}")
        return {}

    if result.returncode != 0:
        logger.error(f"[DataFetcher] westock-data quote 错误: {result.stderr.strip()}")
        return {}

    ws_supported_symbols = [s for s, _ in ws_supported]
    ws_supported_codes = [ws for _, ws in ws_supported]
    results = _parse_ws_quote_output(result.stdout, ws_supported_symbols, ws_supported_codes)

    # 港股降级到 yfinance
    if yf_needed and YF_AVAILABLE:
        logger.info(f"[DataFetcher] quote: westock-data 不支持 {yf_needed}，降级使用 yfinance")
        yf_quote_results = _yf_fetch_quote_fallback(yf_needed)
        results.update(yf_quote_results)

    return results


def _parse_ws_quote_output(stdout: str, symbols: list, ws_symbols: list) -> dict:
    """解析 westock-data quote 的 Markdown 表格输出"""
    ws_to_internal = {ws: s for ws, s in zip(ws_symbols, symbols)}
    lines = stdout.strip().split('\n')

    # 找到表头
    headers = None
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith('|') and 'code' in line.lower():
            headers = [h.strip().lower() for h in line.split('|') if h.strip()]
            header_idx = i
            break

    if headers is None:
        return {}

    results = {}
    for line in lines[header_idx + 2:]:  # 跳过表头和分隔行
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if len(cells) < len(headers):
            continue

        row = dict(zip(headers, cells))
        ws_code = row.get('code', '')
        internal_sym = ws_to_internal.get(ws_code)

        if internal_sym:
            try:
                results[internal_sym] = {
                    'symbol': internal_sym,
                    'price': float(row.get('price', 0)) if row.get('price') else None,
                    'prev_close': float(row.get('prev_close', 0)) if row.get('prev_close') else None,
                    'volume': float(row.get('volume', 0)) if row.get('volume') else None,
                    'market_cap': float(row.get('total_market_cap', 0)) if row.get('total_market_cap') else None,
                    'pe_ratio': float(row.get('pe_ratio', 0)) if row.get('pe_ratio') and row.get('pe_ratio') != '0' else None,
                    'pe_fwd': float(row.get('pe_fwd', 0)) if row.get('pe_fwd') and row.get('pe_fwd') != '0' else None,
                    'pb_ratio': float(row.get('pb_ratio', 0)) if row.get('pb_ratio') and row.get('pb_ratio') != '0' else None,
                    'dividend_ratio_ttm': float(row.get('dividend_ratio_ttm', 0)) if row.get('dividend_ratio_ttm') and row.get('dividend_ratio_ttm') != '0' else None,
                    'high_52week': float(row.get('high_52week', 0)) if row.get('high_52week') else None,
                    'low_52week': float(row.get('low_52week', 0)) if row.get('low_52week') else None,
                    'chg_5d': float(row.get('chg_5d', 0)) if row.get('chg_5d') else None,
                    'chg_20d': float(row.get('chg_20d', 0)) if row.get('chg_20d') else None,
                    'chg_ytd': float(row.get('chg_ytd', 0)) if row.get('chg_ytd') else None,
                }
            except (ValueError, TypeError):
                pass

    return results


# ══════════════════════════════════════════════════════════
# yfinance 数据获取（降级备选）
# ══════════════════════════════════════════════════════════

def _yf_fetch_with_retry(yf_symbol: str, period: str, interval: str,
                          max_retries: int = 5, base_delay: float = 5.0) -> Optional[pd.DataFrame]:
    """
    带指数退避的 yfinance 数据获取（降级备选）。
    Yahoo Finance 对频繁请求会限流，需要自动重试。
    """
    if not YF_AVAILABLE:
        return None

    import time
    import random

    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(yf_symbol)
            raw_df = ticker.history(period=period, interval=interval)
            if raw_df is not None and not raw_df.empty:
                return raw_df
            return None
        except Exception as e:
            error_msg = str(e)
            is_rate_limit = 'Rate' in error_msg or 'Too Many' in error_msg or '429' in error_msg
            if is_rate_limit and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 2)
                logger.warning(f"[DataFetcher] {yf_symbol} 被限流，{delay:.1f}秒后重试 "
                               f"({attempt+1}/{max_retries})...")
                time.sleep(delay)
            else:
                raise
    return None


def _yf_fetch_ohlcv(symbols: list, period: str = '1y',
                     interval: str = '1d', add_indicators: bool = True) -> dict:
    """yfinance 降级获取 OHLCV 数据"""
    results = {}
    for i, symbol in enumerate(symbols):
        if i > 0:
            import time
            import random
            delay = random.uniform(1.5, 3.0)
            time.sleep(delay)

        yf_symbol = to_yfinance_symbol(symbol)
        try:
            raw_df = _yf_fetch_with_retry(yf_symbol, period=period,
                                           interval=interval, max_retries=5, base_delay=5.0)
            if raw_df is None or raw_df.empty:
                logger.warning(f"[DataFetcher] {symbol} (yfinance) 无数据返回")
                continue
            df = standardize_ohlcv(raw_df, symbol=symbol, add_indicators=add_indicators)
            results[symbol] = df
            logger.info(f"[DataFetcher] {symbol} (yfinance) 获取成功，{len(df)}行数据")
        except Exception as e:
            logger.error(f"[DataFetcher] {symbol} (yfinance) 获取失败: {e}")

    return results


def _yf_fetch_quote_fallback(symbols: list) -> dict:
    """yfinance 降级获取 quote 数据（主要用于港股）"""
    results = {}
    for symbol in symbols:
        yf_symbol = to_yfinance_symbol(symbol)
        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info
            results[symbol] = {
                'symbol': symbol,
                'price': info.get('regularMarketPrice') or info.get('currentPrice'),
                'prev_close': info.get('previousClose'),
                'volume': info.get('volume'),
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'pe_fwd': info.get('forwardPE'),
                'pb_ratio': info.get('priceToBook'),
                'dividend_ratio_ttm': info.get('dividendYield'),
                'high_52week': info.get('fiftyTwoWeekHigh'),
                'low_52week': info.get('fiftyTwoWeekLow'),
                'bid': info.get('bid'),
                'ask': info.get('ask'),
                'timestamp': info.get('regularMarketTime'),
                'close': info.get('previousClose'),
            }
            # 补充标准化格式
            results[symbol].setdefault('chg_5d', None)
            results[symbol].setdefault('chg_20d', None)
            results[symbol].setdefault('chg_ytd', None)
            logger.info(f"[DataFetcher] {symbol} (yfinance quote) 获取成功")
        except Exception as e:
            logger.error(f"[DataFetcher] {symbol} (yfinance quote) 获取失败: {e}")
            results[symbol] = {'symbol': symbol, 'price': None}
        # 增加延迟避免限流
        if YF_AVAILABLE:
            import time, random
            time.sleep(random.uniform(1.0, 2.5))
    return results


# ══════════════════════════════════════════════════════════
# 公共接口
# ══════════════════════════════════════════════════════════

def fetch_ohlcv(symbols: Union[str, list], period: str = '1y',
                interval: str = '1d', add_indicators: bool = True) -> dict:
    """
    获取一只或多只股票的 OHLCV 历史数据（标准化后）。

    优先使用 westock-data（无限流），yfinance 作为降级备选。

    Args:
        symbols:         股票代码（字符串或列表）
        period:          数据周期：1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max
        interval:        数据频率（westock-data 忽略此参数，始终为日K）
        add_indicators:  是否自动添加技术指标（默认 True）

    Returns:
        {symbol: DataFrame, ...} 标准化后的 DataFrame（含技术指标列）
    """
    _check_data_source()

    if isinstance(symbols, str):
        symbols = [symbols]

    # 将 period 转换为 westock-data 的 limit
    period_to_limit = {
        '3mo': 65, '6mo': 130, '1y': 260, '2y': 520, '5y': 1300, '10y': 2600, 'max': 4500
    }
    limit = period_to_limit.get(period, 260)

    # ── 优先：westock-data ──
    if WESTOCK_AVAILABLE:
        logger.info(f"[DataFetcher] 优先使用 westock-data 获取 {symbols}")
        raw_results = _ws_fetch_kline(symbols, period='day', limit=limit)

        results = {}
        failed_symbols = []

        for symbol in symbols:
            if symbol in raw_results and raw_results[symbol] is not None and not raw_results[symbol].empty:
                try:
                    # westock 输出列名中 last 已被 _build_kline_df 映射为 close
                    df = standardize_ohlcv(raw_results[symbol], symbol=symbol,
                                           add_indicators=add_indicators)
                    results[symbol] = df
                    logger.info(f"[DataFetcher] {symbol} (westock) 获取成功，{len(df)}行数据")
                except Exception as e:
                    logger.warning(f"[DataFetcher] {symbol} (westock) 标准化失败: {e}")
                    failed_symbols.append(symbol)
            else:
                failed_symbols.append(symbol)

        # 对 westock-data 获取失败的标的，降级到 yfinance
        if failed_symbols and YF_AVAILABLE:
            logger.info(f"[DataFetcher] westock-data 未覆盖 {failed_symbols}，降级使用 yfinance")
            yf_results = _yf_fetch_ohlcv(failed_symbols, period=period,
                                          interval=interval, add_indicators=add_indicators)
            results.update(yf_results)

        return results

    # ── 降级：yfinance ──
    if YF_AVAILABLE:
        return _yf_fetch_ohlcv(symbols, period=period,
                                interval=interval, add_indicators=add_indicators)

    raise RuntimeError("无可用数据源（westock-data 和 yfinance 均不可用）")


def fetch_quote(symbols: Union[str, list]) -> dict:
    """
    获取一只或多只股票的实时报价（标准化后）。

    优先使用 westock-data quote（含市值、PE等丰富数据），
    yfinance 作为降级备选。

    Returns:
        {symbol: quote_dict, ...}
    """
    _check_data_source()

    if isinstance(symbols, str):
        symbols = [symbols]

    # ── 优先：westock-data quote ──
    if WESTOCK_AVAILABLE:
        ws_results = _ws_fetch_quote(symbols)
        if ws_results:
            # 补充标准化格式（兼容旧接口）
            for sym, q in ws_results.items():
                q.setdefault('bid', None)
                q.setdefault('ask', None)
                q.setdefault('timestamp', None)
                q.setdefault('close', q.get('prev_close'))
            return ws_results

    # ── 降级：yfinance ──
    if YF_AVAILABLE:
        results = {}
        for symbol in symbols:
            yf_symbol = YF_SYMBOL_MAP.get(symbol, symbol)
            try:
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info
                raw_quote = {
                    'price': info.get('regularMarketPrice') or info.get('currentPrice'),
                    'close': info.get('previousClose'),
                    'bid': info.get('bid'),
                    'ask': info.get('ask'),
                    'volume': info.get('volume'),
                    'timestamp': info.get('regularMarketTime')
                }
                results[symbol] = standardize_quote(raw_quote, symbol)
            except Exception as e:
                logger.error(f"[DataFetcher] {symbol} 实时报价获取失败: {e}")
                results[symbol] = standardize_quote({}, symbol)
        return results

    raise RuntimeError("无可用数据源")


def fetch_vix_data(period: str = '3mo') -> pd.DataFrame:
    """
    获取 VIX 指数历史数据（标准化后）。

    westock-data 不直接支持 VIX 指数K线，
    优先使用 yfinance 获取 ^VIX，若不可用则使用 VIXY ETF 作为代理。
    """
    # 先尝试 yfinance（VIX指数数据最准确）
    if YF_AVAILABLE:
        try:
            result = _yf_fetch_ohlcv(['VIX'], period=period, add_indicators=True)
            if 'VIX' in result:
                logger.info("[DataFetcher] VIX 数据通过 yfinance 获取成功")
                return result['VIX']
        except Exception as e:
            logger.warning(f"[DataFetcher] VIX yfinance 获取失败: {e}")

    # 降级：使用 VIXY ETF 作为代理
    if WESTOCK_AVAILABLE:
        logger.info("[DataFetcher] VIX 降级使用 VIXY ETF 数据作为代理")
        result = fetch_ohlcv('VIXY', period=period, add_indicators=True)
        vixy_df = result.get('VIXY', pd.DataFrame())
        if not vixy_df.empty:
            # 重命名为 VIX（仅用于趋势参考，不用于精确VIX值）
            return vixy_df

    return pd.DataFrame()


def fetch_macro_data(period: str = '6mo') -> dict:
    """
    获取宏观经济指标数据。
    Returns: {'vix': DataFrame, 'tnx': DataFrame}
    """
    vix_df = fetch_vix_data(period=period)

    # TNX（10年期美债收益率）：westock-data 不支持，用 yfinance
    tnx_df = pd.DataFrame()
    if YF_AVAILABLE:
        try:
            result = _yf_fetch_ohlcv(['TNX'], period=period, add_indicators=False)
            tnx_df = result.get('TNX', pd.DataFrame())
        except Exception as e:
            logger.warning(f"[DataFetcher] TNX yfinance 获取失败: {e}")

    # yfinance 也失败时，用 IEF ETF 作为代理
    if tnx_df.empty and WESTOCK_AVAILABLE:
        logger.info("[DataFetcher] TNX 降级使用 IEF ETF 数据作为代理")
        result = fetch_ohlcv('IEF', period=period, add_indicators=False)
        tnx_df = result.get('IEF', pd.DataFrame())

    return {'vix': vix_df, 'tnx': tnx_df}


def extract_current_prices(ohlcv_dict: dict) -> dict:
    """
    从标准化的 OHLCV 数据中提取最新价格字典。
    Returns: {'AAPL': 175.5, ...}
    """
    prices = {}
    for symbol, df in (ohlcv_dict or {}).items():
        if df is not None and not df.empty:
            try:
                prices[symbol] = float(df.iloc[-1]['close'])
            except (IndexError, KeyError, TypeError) as e:
                logger.warning(f"[DataFetcher] {symbol} 价格提取失败: {e}")
    return prices


def extract_avg_daily_volumes(ohlcv_dict: dict, window: int = 20) -> dict:
    """
    从标准化的 OHLCV 数据中提取近N日日均成交额。
    Returns: {'AAPL': 5000000.0, ...}
    """
    volumes = {}
    for symbol, df in (ohlcv_dict or {}).items():
        if df is not None and not df.empty:
            try:
                if 'volume' in df.columns and 'close' in df.columns:
                    turnover = df['volume'] * df['close']
                    volumes[symbol] = float(turnover.tail(window).mean())
                elif 'volume_ma20' in df.columns and 'close' in df.columns:
                    volumes[symbol] = float(df.iloc[-1]['volume_ma20'] * df.iloc[-1]['close'])
            except (IndexError, KeyError, TypeError) as e:
                logger.warning(f"[DataFetcher] {symbol} 成交额提取失败: {e}")
    return volumes


def fetch_fundamentals(symbols: Union[str, list]) -> dict:
    """
    通过 westock-data quote 获取基本面数据（市值、PE、股息率等）。

    Returns:
        {symbol: {'market_cap': float, 'pe_ratio': float, 'dividend_ratio': float, ...}}
    """
    if isinstance(symbols, str):
        symbols = [symbols]

    if not WESTOCK_AVAILABLE:
        logger.warning("[DataFetcher] westock-data 不可用，无法获取基本面数据")
        return {}

    quotes = _ws_fetch_quote(symbols)
    fundamentals = {}
    for sym, q in quotes.items():
        fundamentals[sym] = {
            'market_cap': q.get('market_cap'),
            'pe_ratio': q.get('pe_ratio'),
            'pe_fwd': q.get('pe_fwd'),
            'pb_ratio': q.get('pb_ratio'),
            'dividend_ratio': q.get('dividend_ratio_ttm'),
            'high_52week': q.get('high_52week'),
            'low_52week': q.get('low_52week'),
            'chg_5d': q.get('chg_5d'),
            'chg_20d': q.get('chg_20d'),
            'chg_ytd': q.get('chg_ytd'),
        }
    return fundamentals