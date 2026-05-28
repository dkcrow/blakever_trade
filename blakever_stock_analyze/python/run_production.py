#!/usr/bin/env python3
"""
Blakever 生产运行脚本 — 真实数据模式
通过 yfinance 获取最新行情，运行完整决策链路，
生成《每日操作建议指南》并发送到指定邮箱。

使用方法：
  python run_production.py --email your@email.com

环境变量（可选，用于覆盖默认值）：
  BLAKEVER_INDEX_SYMBOL   大盘指数代码（默认 SPY）
  BLAKEVER_STOCK_SYMBOLS  股票池代码，逗号分隔（默认 AAPL,MSFT,GOOGL,AMZN,NVDA,JPM,JNJ,PG,XOM,TSLA）
  BLAKEVER_ACCOUNT_EQUITY 账户净值（默认 100000000）
  BLAKEVER_CASH           现金（默认 100000000）
  BLAKEVER_SMTP_SERVER    SMTP 服务器地址
  BLAKEVER_SMTP_PORT      SMTP 端口（默认 587）
  BLAKEVER_SMTP_USER      SMTP 登录用户名
  BLAKEVER_SMTP_PASSWORD  SMTP 登录密码
  BLAKEVER_EMAIL_FROM     发件人地址
"""

import sys
import os
import logging
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─────────────────────────────────────────────
# 日志配置
# ─────────────────────────────────────────────
LOG_FORMAT = '%(asctime)s %(levelname)-8s [%(name)s] %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("BlakeverProduction")

# 每步完成的标记
STEP_MARKERS = {
    'data_fetch': '❌ Step 1 失败',
    'macro_narrative': '❌ Step 2 失败',
    'market_analyze': '❌ Step 3 失败',
    'strategy': '❌ Step 4 失败',
    'debate': '❌ Step 5 失败',
    'cro': '❌ Step 6 失败',
    'experience': '❌ Step 7 失败',
    'backtest': '❌ Step 8 失败',
    'execution': '❌ Step 9 失败',
    'contrarian': '❌ Step 10 失败',
    'macro_consistency': '❌ Step 11 失败',
    'force_close': '❌ Step 12 失败',
    'report': '❌ Step 13 失败',
    'email': '❌ Step 14 失败',
}


def check_dependencies() -> bool:
    """检查运行依赖是否满足"""
    logger.info("🔍 检查运行依赖...")

    # 1. yfinance
    try:
        import yfinance
        logger.info(f"   ✅ yfinance {yfinance.__version__}")
    except ImportError:
        logger.error("   ❌ yfinance 未安装，请执行: pip install yfinance")
        return False

    # 2. pandas / numpy
    try:
        import pandas as pd
        import numpy as np
        logger.info(f"   ✅ pandas {pd.__version__}, numpy {np.__version__}")
    except ImportError:
        logger.error("   ❌ pandas/numpy 未安装，请执行: pip install pandas numpy")
        return False

    # 3. 项目模块
    required_modules = [
        'data_fetcher', 'market_info', 'market_analyze',
        'cro_mgr', 'fool_trader',
        'experience_review', 'strategy_backtest', 'main_dispatcher'
    ]
    for mod in required_modules:
        try:
            __import__(mod)
            logger.info(f"   ✅ {mod}")
        except ImportError as e:
            logger.error(f"   ❌ {mod} 导入失败: {e}")
            return False

    return True


def fetch_real_data(index_symbol: str, stock_symbols: list) -> dict:
    """
    Step 1: 通过 yfinance 获取真实行情数据。

    Returns:
        {
            'index_data': {symbol: DataFrame},
            'vix_df': DataFrame,
            'macro_data': dict,
            'stock_data': {symbol: DataFrame},
            'fetch_errors': list[str]
        }
    """
    from data_fetcher import (
        fetch_ohlcv, fetch_vix_data, fetch_macro_data,
        extract_current_prices, extract_avg_daily_volumes,
        YF_AVAILABLE
    )

    fetch_errors = []

    # 获取大盘指数数据
    logger.info(f"📈 获取大盘指数 {index_symbol} 数据...")
    index_data = {}
    index_df = None
    for attempt in range(3):
        try:
            index_data = fetch_ohlcv(index_symbol, period='1y', add_indicators=True)
            index_df = index_data.get(index_symbol, None)
            if index_df is not None and not index_df.empty:
                logger.info(f"   ✅ {index_symbol}: {len(index_df)} 行数据, "
                            f"最新价={index_df.iloc[-1]['close']:.2f}")
                break
            else:
                if attempt < 2:
                    logger.warning(f"   ⚠️ {index_symbol} 第{attempt+1}次尝试无数据，重试中...")
                    import time; time.sleep(3 * (attempt + 1))
        except Exception as e:
            logger.warning(f"   ⚠️ 尝试 {attempt+1}/3: {index_symbol} 获取失败: {e}")
            if attempt < 2:
                import time; time.sleep(3 * (attempt + 1))
    # 仅在最终仍无数据时才添加错误
    if index_df is None or index_df.empty:
        fetch_errors.append(f"指数 {index_symbol} 获取失败（3次尝试均无数据）")

    # 获取 VIX 数据
    logger.info("📉 获取 VIX 恐慌指数数据...")
    vix_df = None
    for attempt in range(3):
        try:
            vix_df = fetch_vix_data(period='1y')  # 使用1年期数据确保MA120有效
            if vix_df is not None and not vix_df.empty:
                vix_val = vix_df.iloc[-1]['close']
                logger.info(f"   ✅ VIX: {len(vix_df)} 行, 最新值={vix_val:.2f}")
                break
            else:
                if attempt < 2:
                    logger.warning(f"   ⚠️ VIX 第{attempt+1}次尝试无数据，重试中...")
                    import time; time.sleep(3 * (attempt + 1))
        except Exception as e:
            logger.warning(f"   ⚠️ 尝试 {attempt+1}/3: VIX 获取失败: {e}")
            if attempt < 2:
                import time; time.sleep(3 * (attempt + 1))
    if vix_df is None or vix_df.empty:
        fetch_errors.append("VIX 获取失败（3次尝试均无数据）")

    # 获取宏观数据（TNX 等）
    logger.info("🌐 获取宏观经济指标...")
    macro_data = {}
    try:
        macro_data = fetch_macro_data(period='6mo')
        tnx_df = macro_data.get('tnx', None)
        if tnx_df is not None and not tnx_df.empty:
            tnx_val = tnx_df.iloc[-1]['close']
            logger.info(f"   ✅ 10年期美债收益率: {tnx_val:.2f}%")
        else:
            logger.warning("   ⚠️ 美债收益率无数据")
    except Exception as e:
        fetch_errors.append(f"宏观数据获取失败: {e}")
        macro_data = {'vix': vix_df, 'tnx': None}
        logger.error(f"   ❌ 宏观数据获取失败: {e}")

    # 获取股票池数据（批量获取 + 降级策略）
    from stock_pool import is_hk_symbol, get_index_symbol_for_market
    total_count = len(stock_symbols)
    hk_count = sum(1 for s in stock_symbols if is_hk_symbol(s))
    us_count = total_count - hk_count
    logger.info(f"📊 获取股票池数据: 共 {total_count} 只 (美股 {us_count}, 港股 {hk_count})...")

    stock_data = {}
    fetch_count = 0

    # 尝试批量获取（westock-data 支持美股批量）
    if us_count > 0:
        us_symbols = [s for s in stock_symbols if not is_hk_symbol(s)]
        logger.info(f"   📡 批量获取美股数据 ({len(us_symbols)} 只)...")
        try:
            from data_fetcher import _ws_fetch_kline
            batch_result = _ws_fetch_kline(us_symbols)
            for sym, df in batch_result.items():
                if df is not None and not df.empty:
                    stock_data[sym] = df
                    fetch_count += 1
            logger.info(f"   ✅ 批量获取成功: {len(batch_result)} 只")
        except Exception as e:
            logger.warning(f"   ⚠️ 批量获取失败: {e}，降级逐个获取")

        # 逐个补充批量获取失败的
        for symbol in us_symbols:
            if symbol in stock_data:
                continue
            for attempt in range(3):
                try:
                    result = fetch_ohlcv(symbol, period='1y', add_indicators=True)
                    df = result.get(symbol, None)
                    if df is not None and not df.empty:
                        stock_data[symbol] = df
                        fetch_count += 1
                        logger.info(f"   ✅ {symbol}: {len(df)} 行, "
                                    f"最新价={df.iloc[-1]['close']:.2f}")
                        break
                    else:
                        if attempt < 2:
                            import time; time.sleep(2 * (attempt + 1))
                except Exception as e:
                    if attempt < 2:
                        import time; time.sleep(2 * (attempt + 1))
            if symbol not in stock_data:
                fetch_errors.append(f"{symbol} 获取失败（3次尝试均无数据）")

    # 港股逐个获取（yfinance）
    if hk_count > 0:
        hk_symbols = [s for s in stock_symbols if is_hk_symbol(s)]
        logger.info(f"   📡 获取港股数据 ({len(hk_symbols)} 只, yfinance)...")
        for symbol in hk_symbols:
            for attempt in range(3):
                try:
                    result = fetch_ohlcv(symbol, period='1y', add_indicators=True)
                    df = result.get(symbol, None)
                    if df is not None and not df.empty:
                        stock_data[symbol] = df
                        fetch_count += 1
                        latest_price = df.iloc[-1]['close']
                        logger.info(f"   ✅ {symbol}: {len(df)} 行, "
                                    f"最新价={latest_price:.2f}")
                        break
                    else:
                        if attempt < 2:
                            import time; time.sleep(3 * (attempt + 1))
                except Exception as e:
                    if attempt < 2:
                        import time; time.sleep(3 * (attempt + 1))
            if symbol not in stock_data:
                fetch_errors.append(f"{symbol} 获取失败（3次尝试均无数据）")
            # yfinance 限流保护
            if YF_AVAILABLE:
                import time, random
                time.sleep(random.uniform(1.0, 2.5))

    logger.info(f"   📊 获取完成: {fetch_count}/{total_count} 只成功")

    # ── 分层预筛选（减少策略计算量）──
    if args.pool_filter and args.pool_filter != 'none' and len(stock_data) > 0:
        from stock_pool import prefilter_by_volume_and_price
        original_count = len(stock_data)
        if args.pool_filter == 'volume':
            # 按成交额粗筛：剔除流动性不足和低价股
            passed = prefilter_by_volume_and_price(
                stock_data,
                min_price=5.0,
                min_avg_volume_usd=5_000_000,
                min_data_rows=60
            )
            stock_data = {s: stock_data[s] for s in passed if s in stock_data}
            logger.info(f"   🔍 成交额粗筛: {original_count} → {len(stock_data)} 只 "
                        f"(剔除 {original_count - len(stock_data)} 只流动性不足)")
        elif args.pool_filter == 'top50':
            # 按市值取前50只（使用降级市值映射）
            from stock_pool import HK_MARKET_CAP_MAP, is_hk_symbol
            # 美股市值降级映射
            US_MCAP_FALLBACK = {
                'AAPL': 2800, 'MSFT': 2700, 'GOOGL': 1700, 'AMZN': 1500, 'NVDA': 1200,
                'JPM': 500, 'JNJ': 400, 'PG': 350, 'XOM': 450, 'TSLA': 800,
                'META': 1200, 'BRK-B': 800, 'V': 500, 'UNH': 450, 'HD': 350,
                'WMT': 600, 'DIS': 200, 'BAC': 350, 'VZ': 180, 'ADBE': 220,
            }
            def _get_market_cap(sym):
                df = stock_data.get(sym)
                if df is not None and not df.empty:
                    try:
                        price = float(df.iloc[-1]['close'])
                        vol = float(df.iloc[-1].get('volume', 0))
                        vol_ma20 = df.iloc[-1].get('volume_ma20', vol)
                        if vol_ma20 and not __import__('pandas').isna(vol_ma20):
                            return price * float(vol_ma20) * 100
                    except:
                        pass
                # 降级到静态映射
                if is_hk_symbol(sym):
                    return HK_MARKET_CAP_MAP.get(sym, 0) * 1e9
                else:
                    return US_MCAP_FALLBACK.get(sym, 100) * 1e9
            sorted_syms = sorted(stock_data.keys(), key=_get_market_cap, reverse=True)
            top50 = sorted_syms[:50]
            stock_data = {s: stock_data[s] for s in top50 if s in stock_data}
            logger.info(f"   🔍 市值Top50筛选: {original_count} → {len(stock_data)} 只")

    if not stock_data:
        fetch_errors.append("股票池全部获取失败，无法继续")

    return {
        'index_data': index_data,
        'index_df': index_df,
        'vix_df': vix_df,
        'macro_data': macro_data,
        'stock_data': stock_data,
        'fetch_errors': fetch_errors,
    }


def build_auxiliary_maps(stock_data: dict, stock_symbols: list) -> dict:
    """
    从行情数据中构建行业、市值、Beta等映射字典。

    优先使用 westock-data quote/profile 获取真实数据，
    硬编码映射作为降级备选。
    """
    # ── 硬编码降级映射（来源：各公司2024年年报数据）──
    # 美股硬编码降级数据
    STATIC_INDUSTRY_MAP = {
        'AAPL': 'Consumer Electronics', 'MSFT': 'Software', 'GOOGL': 'Internet Services',
        'AMZN': 'E-Commerce', 'NVDA': 'Semiconductors', 'JPM': 'Banking',
        'JNJ': 'Pharmaceuticals', 'PG': 'Consumer Goods', 'XOM': 'Oil & Gas',
        'TSLA': 'Auto & EV', 'META': 'Social Media', 'BRK-B': 'Conglomerate',
        'V': 'Payments', 'UNH': 'Health Insurance', 'HD': 'Home Improvement',
        'WMT': 'Retail', 'DIS': 'Entertainment', 'BAC': 'Banking',
        'VZ': 'Telecom', 'ADBE': 'Software',
    }
    # 合入港股降级行业数据
    from stock_pool import HK_INDUSTRY_MAP
    STATIC_INDUSTRY_MAP.update(HK_INDUSTRY_MAP)

    STATIC_MARKET_CAP_MAP = {  # 十亿美元
        'AAPL': 2800, 'MSFT': 2700, 'GOOGL': 1700, 'AMZN': 1500, 'NVDA': 1200,
        'JPM': 500, 'JNJ': 400, 'PG': 350, 'XOM': 450, 'TSLA': 800,
        'META': 1200, 'BRK-B': 800, 'V': 500, 'UNH': 450, 'HD': 350,
        'WMT': 600, 'DIS': 200, 'BAC': 350, 'VZ': 180, 'ADBE': 220,
    }
    from stock_pool import HK_MARKET_CAP_MAP
    STATIC_MARKET_CAP_MAP.update(HK_MARKET_CAP_MAP)

    STATIC_BETA_MAP = {
        'AAPL': 1.2, 'MSFT': 0.9, 'GOOGL': 1.1, 'AMZN': 1.2, 'NVDA': 1.7,
        'JPM': 1.1, 'JNJ': 0.6, 'PG': 0.5, 'XOM': 0.8, 'TSLA': 2.0,
        'META': 1.3, 'BRK-B': 0.6, 'V': 1.0, 'UNH': 0.7, 'HD': 1.0,
        'WMT': 0.5, 'DIS': 1.2, 'BAC': 1.3, 'VZ': 0.4, 'ADBE': 1.2,
    }
    from stock_pool import HK_BETA_MAP
    STATIC_BETA_MAP.update(HK_BETA_MAP)

    STATIC_DIVIDEND_YIELD_MAP = {
        'AAPL': 0.005, 'MSFT': 0.007, 'GOOGL': 0.0, 'AMZN': 0.0, 'NVDA': 0.0003,
        'JPM': 0.023, 'JNJ': 0.03, 'PG': 0.024, 'XOM': 0.034, 'TSLA': 0.0,
        'META': 0.004, 'BRK-B': 0.0, 'V': 0.007, 'UNH': 0.014, 'HD': 0.024,
        'WMT': 0.013, 'DIS': 0.009, 'BAC': 0.026, 'VZ': 0.064, 'ADBE': 0.0,
    }
    from stock_pool import HK_DIVIDEND_YIELD_MAP
    STATIC_DIVIDEND_YIELD_MAP.update(HK_DIVIDEND_YIELD_MAP)

    industry_map = {}
    market_cap_map = {}
    beta_map = {}
    dividend_yield_map = {}
    avg_volume_map = {}

    logger.info("📋 构建辅助映射字典（行业、市值、Beta等）...")

    # ── 优先：通过 westock-data 获取真实基本面数据 ──
    ws_fundamentals = {}
    ws_profiles = {}
    try:
        from data_fetcher import fetch_fundamentals, WESTOCK_AVAILABLE
        if WESTOCK_AVAILABLE:
            logger.info("   优先使用 westock-data 获取基本面数据")
            ws_fundamentals = fetch_fundamentals(stock_symbols)

            # 获取行业信息（profile）— 仅对 westock 支持的代码
            import subprocess, os
            ws_script = "/data/workspace/.agent/skills/westock-data/scripts/index.js"
            ws_symbols = [to_westock_symbol(s) for s in stock_symbols]
            # 过滤掉 None（港股等不支持的代码）
            ws_supported_list = [(s, ws) for s, ws in zip(stock_symbols, ws_symbols) if ws is not None]
            ws_profiles = {}
            if ws_supported_list:
                ws_codes = ','.join(ws for _, ws in ws_supported_list)
            cmd = ['node', ws_script, 'profile', ws_codes]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd='/data/workspace', timeout=30)
            if result.returncode == 0:
                ws_to_internal = {ws: s for s, ws in ws_supported_list}
                lines = result.stdout.strip().split('\n')
                headers = None
                header_idx = None
                for i, line in enumerate(lines):
                    if line.startswith('|') and 'code' in line.lower():
                        headers = [h.strip().lower() for h in line.split('|') if h.strip()]
                        header_idx = i
                        break
                if headers:
                    for line in lines[header_idx + 2:]:
                        if not line.strip().startswith('|'):
                            continue
                        cells = [c.strip() for c in line.split('|') if c.strip()]
                        if len(cells) >= len(headers):
                            row = dict(zip(headers, cells))
                            ws_code = row.get('code', '')
                            internal_sym = ws_to_internal.get(ws_code)
                            if internal_sym:
                                ws_profiles[internal_sym] = {
                                    'industry': row.get('industry', ''),
                                    'sector': row.get('sector', ''),
                                }
    except Exception as e:
        logger.warning(f"   ⚠️ westock-data 基本面获取失败，使用硬编码降级: {e}")

    use_ws = bool(ws_fundamentals or ws_profiles)
    if use_ws:
        logger.info(f"   ✅ westock-data 获取到 {len(ws_fundamentals)} 只股票基本面 + {len(ws_profiles)} 只行业数据")
    else:
        logger.info("   使用硬编码基本面数据（westock-data 不可用）")

    for symbol in stock_symbols:
        fund = ws_fundamentals.get(symbol, {})
        profile = ws_profiles.get(symbol, {})

        # 行业：优先 westock profile -> 硬编码
        industry = profile.get('industry') or profile.get('sector')
        if not industry or industry == '未知':
            industry = STATIC_INDUSTRY_MAP.get(symbol, '未知')
        industry_map[symbol] = industry

        # 市值：优先 westock quote -> 硬编码
        ws_mcap = fund.get('market_cap')
        if ws_mcap and ws_mcap > 0:
            market_cap_map[symbol] = ws_mcap / 1e9  # 转换为十亿美元
        else:
            market_cap_map[symbol] = STATIC_MARKET_CAP_MAP.get(symbol, 100)

        # Beta：暂用硬编码（westock 不提供 Beta）
        beta_map[symbol] = STATIC_BETA_MAP.get(symbol, 1.0)

        # 股息率：优先 westock quote -> 硬编码
        ws_div = fund.get('dividend_ratio')
        if ws_div and ws_div > 0:
            dividend_yield_map[symbol] = ws_div / 100.0  # westock 返回百分比
        else:
            dividend_yield_map[symbol] = STATIC_DIVIDEND_YIELD_MAP.get(symbol, 0.01)

        # 日均成交量（近20日成交额，单位：美元）
        df = stock_data.get(symbol)
        if df is not None and not df.empty:
            try:
                import pandas as pd_inner
                vol_ma20 = df.iloc[-1].get('volume_ma20', None)
                close = float(df.iloc[-1]['close'])
                # 优先使用 volume_ma20，否则用 volume
                if vol_ma20 is not None and not pd_inner.isna(vol_ma20) and float(vol_ma20) > 0:
                    avg_volume_map[symbol] = float(vol_ma20) * close
                else:
                    vol = df.iloc[-1].get('volume', 0)
                    if vol is not None and not pd_inner.isna(vol) and float(vol) > 0:
                        avg_volume_map[symbol] = float(vol) * close
                    else:
                        avg_volume_map[symbol] = 1e7
            except Exception as e:
                logger.warning(f"   ⚠️ {symbol} 成交量提取失败: {e}")
                avg_volume_map[symbol] = 1e7
        else:
            avg_volume_map[symbol] = 1e7

        data_source = "ws" if (fund or profile) else "static"
        logger.info(f"   ✅ {symbol}: 行业={industry_map[symbol]}, "
                    f"市值={market_cap_map[symbol]:.0f}B, "
                    f"Beta={beta_map[symbol]}, "
                    f"股息率={dividend_yield_map[symbol]:.2%}, "
                    f"日均成交额={avg_volume_map.get(symbol, 0):,.0f}"
                    f" [{data_source}]")

    return {
        'industry_map': industry_map,
        'market_cap_map': market_cap_map,
        'beta_map': beta_map,
        'dividend_yield_map': dividend_yield_map,
        'avg_volume_map': avg_volume_map,
    }


def run_full_decision(data: dict, maps: dict, args: argparse.Namespace) -> dict:
    """
    Steps 2-12: 运行完整决策链路。

    Returns:
        main_dispatcher 的完整输出 + 每步状态
    """
    from main_dispatcher import (
        analyze_macro_narrative, run_adversarial_debate,
        evaluate_contrarian_entry, check_macro_consistency,
        run_daily_decision
    )
    from market_analyze import analyze_market
    from cro_mgr import check_force_close
    from experience_review import run_experience_review
    from strategy_backtest import run_strategy_backtest
    from fool_trader import run_execution
    from data_fetcher import extract_current_prices, extract_avg_daily_volumes

    index_df = data['index_df']
    vix_df = data['vix_df']
    macro_data = data['macro_data']
    stock_data = data['stock_data']
    stock_symbols = list(stock_data.keys())

    industry_map = maps['industry_map']
    market_cap_map = maps['market_cap_map']
    beta_map = maps['beta_map']
    dividend_yield_map = maps['dividend_yield_map']
    avg_volume_map = maps['avg_volume_map']

    account_equity = args.equity
    cash = args.cash
    inception_equity = account_equity

    # 模拟当前持仓（生产模式下默认空仓启动）
    current_positions = []
    recent_closed_trades = []

    # ── 双市场支持：当含港股时，额外获取恒生指数 ──
    from stock_pool import is_hk_symbol, get_hk_symbols
    has_hk = any(is_hk_symbol(s) for s in stock_symbols)
    hsi_df = None
    if has_hk and args.index_symbol != 'HSI':
        logger.info("🇭🇰 检测到港股标的，额外获取恒生指数数据...")
        try:
            from data_fetcher import fetch_ohlcv as _fetch_ohlcv
            hsi_result = _fetch_ohlcv('HSI', period='1y', add_indicators=True)
            hsi_df = hsi_result.get('HSI', None)
            if hsi_df is not None and not hsi_df.empty:
                logger.info(f"   ✅ HSI: {len(hsi_df)} 行数据")
            else:
                logger.warning("   ⚠️ HSI 数据获取失败，港股将使用美股大盘代理")
        except Exception as e:
            logger.warning(f"   ⚠️ HSI 获取失败: {e}")

    # Step 2: 宏观叙事分析
    logger.info("🌐 Step 2: 宏观叙事分析 (Agent 2)...")
    try:
        news_summary = ''  # 生产模式下无新闻输入
        tnx_df = macro_data.get('tnx', None)
        macro_narrative = analyze_macro_narrative(vix_df, news_summary, tnx_df)
        logger.info(f"   ✅ 情绪因子={macro_narrative['sentiment_factor']}, "
                    f"流动性预警={macro_narrative['macro_liquidity_warning']}, "
                    f"关键事件={macro_narrative['key_events']}")
    except Exception as e:
        logger.error(f"   ❌ 宏观叙事分析失败: {e}")
        raise

    # Step 3: 市场行情判断
    logger.info("📈 Step 3: 市场行情判断 (Agent 1)...")
    try:
        market_result = analyze_market(index_df, vix_df)
        regime = market_result['regime']
        confidence = market_result['confidence']
        logger.info(f"   ✅ 行情定性={regime}, 置信度={confidence}%, "
                    f"VIX={market_result['vix']:.1f}")
        logger.info(f"   📝 {market_result['summary']}")

        # 港股独立行情判断（使用恒生指数）
        hk_market_result = None
        if hsi_df is not None:
            hk_market_result = analyze_market(hsi_df, vix_df)
            logger.info(f"   🇭🇰 港股行情定性={hk_market_result['regime']}, "
                        f"置信度={hk_market_result['confidence']}%")
            logger.info(f"   🇭🇰 {hk_market_result['summary']}")
    except Exception as e:
        logger.error(f"   ❌ 行情判断失败: {e}")
        raise

    # Step 4: 高波动恐慌或低置信度 → 观望
    if regime == 'Panic' or confidence < 60:
        logger.warning(f"⚠️ 行情不稳定（{regime}, 置信度={confidence}%），生成观望报告")

    # Step 5-12: 调用主调度器完整流程
    logger.info("🔄 Step 5-12: 调用主调度器完整流程...")
    try:
        result = run_daily_decision(
            index_symbol=args.index_symbol,
            stock_symbols=stock_symbols,
            account_equity=account_equity,
            cash=cash,
            inception_equity=inception_equity,
            current_positions=current_positions,
            news_summary=news_summary,
            recent_closed_trades=recent_closed_trades,
            industry_map=industry_map,
            market_cap_map=market_cap_map,
            beta_map=beta_map,
            dividend_yield_map=dividend_yield_map,
            avg_volume_map=avg_volume_map,
            pre_fetched_data={
                'index_df': index_df,
                'vix_df': vix_df,
                'macro_data': macro_data,
                'stock_data': stock_data,
                'hsi_df': hsi_df,  # 港股大盘指数
                'hk_market_result': hk_market_result,  # 港股行情判断结果
            }
        )

        # 输出每步结果
        report = result.get('report', '')
        regime = result.get('market_regime', regime)
        confidence = result.get('regime_confidence', confidence)

        logger.info("=" * 70)
        logger.info("📊 决策流程完成")
        logger.info(f"   行情: {regime} (置信度 {confidence}%)")
        logger.info(f"   执行指令数: {len(result.get('execution_orders', []))}")
        logger.info(f"   左侧试探: {len(result.get('contrarian_entries', []))} 只")
        logger.info(f"   风险红线: {len(result.get('risk_warnings', []))} 条")

        if result.get('cro_result'):
            cro = result['cro_result']
            logger.info(f"   CRO 强制空仓: {'是' if cro.get('force_close_only') else '否'}")
            logger.info(f"   CRO 批准交易: {len(cro.get('approved_trades', []))} 笔")
            if cro.get('industry_concentration_warnings'):
                logger.warning(f"   ⚠️ 行业集中度预警: {cro['industry_concentration_warnings']}")
            if cro.get('hidden_correlation_warnings'):
                logger.warning(f"   ⚠️ 隐性相关性预警: {cro['hidden_correlation_warnings']}")

        if result.get('experience_result'):
            exp = result['experience_result']
            logger.info(f"   新经验: {len(exp.get('new_insights', []))} 条")
            for insight in exp.get('new_insights', []):
                logger.info(f"     - [{insight.get('regime_tag')}] {insight.get('content', '')[:60]}...")

        if result.get('risk_warnings'):
            logger.warning("🚨 全局红线提醒:")
            for w in result['risk_warnings']:
                logger.warning(f"   ⚠️ {w}")

        return result

    except Exception as e:
        logger.error(f"❌ 主调度器执行失败: {e}")
        raise


def _markdown_to_html_email(md_text: str, date_str: str) -> str:
    """
    将 Markdown 报告转换为精美的 HTML 邮件模板。
    包含专业投资报告样式：品牌色、卡片布局、响应式表格等。
    手机端优化：净值简报用大数字卡片，今日指令表用竖排彩色卡片。
    """
    import re
    import html as html_module

    def escape_html(text):
        """转义HTML特殊字符"""
        return html_module.escape(str(text))

    # ── 解析Markdown为结构化数据 ──
    lines = md_text.split('\n')

    # 提取标题
    title = 'Blakever 每日操作建议指南'
    for line in lines:
        if line.startswith('# '):
            title = line[2:].strip()
            break

    # 提取各Section
    sections = []
    current_section = {'title': '', 'content': [], 'level': 2}
    for line in lines:
        if line.startswith('### '):
            # 三级标题作为一个新的子section
            if current_section['title'] or current_section['content']:
                sections.append(current_section)
            current_section = {'title': line[4:].strip(), 'content': [], 'level': 3}
        elif line.startswith('## '):
            if current_section['title'] or current_section['content']:
                sections.append(current_section)
            current_section = {'title': line[3:].strip(), 'content': [], 'level': 2}
        elif line.startswith('> '):
            current_section['content'].append(('quote', line[2:].strip()))
        elif line.startswith('- '):
            current_section['content'].append(('list', line[2:].strip()))
        elif line.startswith('|'):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells:
                current_section['content'].append(('table_row', cells))
        else:
            text = line.strip()
            if text:
                # 不在解析阶段转换加粗，留给渲染阶段处理
                current_section['content'].append(('text', text))
    if current_section['title'] or current_section['content']:
        sections.append(current_section)

    # ── Section图标映射 ──
    section_icons = {
        '大盘仪表盘': '📊',
        'CRO 风控摘要': '🛡️',
        '今日指令表': '📋',
        '止损止盈详细规则': '📐',
        '反向测试辩论庭': '⚖️',
        '左侧试探仓位': '🎯',
        '知识效期预警': '⏰',
        '全局红线提醒': '🚨',
        '净值简报': '💰',
        '风险红线': '⚠️',
        '操作建议': '📝',
        '持仓明细': '📦',
        '今日执行记录': '📝',
    }

    def get_section_icon(title):
        for key, icon in section_icons.items():
            if key in title:
                return icon
        return '📌'

    # ── 渲染辅助函数 ──
    def render_bold(text):
        """处理加粗标记"""
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escape_html(text))

    def is_net_value_section(title):
        """判断是否为净值简报相关section"""
        return '净值' in title

    def is_order_section(title):
        """判断是否为今日指令表section"""
        return '指令表' in title

    def is_position_section(title):
        """判断是否为持仓明细section"""
        return '持仓明细' in title

    def render_net_value_card(table_rows):
        """将净值简报渲染为大数字卡片样式"""
        html = '<div class="net-value-grid">'
        labels_icons = {
            '账户净值': '💎', '现金': '💵', '持仓市值': '📈',
            '浮动盈亏': '📊', '总收益率': '🚀', '持仓数': '📂',
        }
        for i, (_, cells) in enumerate(table_rows):
            if i == 0:
                continue  # 跳过表头
            label = cells[0] if len(cells) > 0 else ''
            value = cells[1] if len(cells) > 1 else ''
            icon = labels_icons.get(label, '📌')
            # 判断是否为负值，着色
            value_class = ''
            if '盈亏' in label or '收益' in label:
                try:
                    num_val = float(value.replace('%', '').replace(',', '').replace('，', ''))
                    if num_val < 0:
                        value_class = ' value-negative'
                    elif num_val > 0:
                        value_class = ' value-positive'
                except (ValueError, AttributeError):
                    pass
            html += f'''<div class="net-value-card">
                <div class="nv-icon">{icon}</div>
                <div class="nv-label">{render_bold(label)}</div>
                <div class="nv-value{value_class}">{escape_html(value)}</div>
            </div>'''
        html += '</div>'
        return html

    def render_order_cards(table_rows):
        """将今日指令表渲染为竖排彩色卡片"""
        if not table_rows or len(table_rows) < 2:
            return ''
        headers = table_rows[0][1]  # 表头cells
        html = ''
        for i, (_, cells) in enumerate(table_rows):
            if i == 0:
                continue  # 跳过表头
            # 解析方向
            direction = cells[1] if len(cells) > 1 else 'long'
            is_long = direction in ('long', '做多', '买')
            card_class = 'order-card-long' if is_long else 'order-card-short'
            symbol = cells[0] if len(cells) > 0 else ''
            direction_label = '🟢 做多' if is_long else '🔴 做空'
            
            # 构建详情行
            detail_rows = ''
            field_labels = {
                '标的': '📌 标的', '方向': '📊 方向', '当前价': '💰 当前价',
                'ATR20': '📏 ATR20', 'ADX14': '📐 ADX14', '止损价': '🛡️ 止损价',
                '止盈规则': '🎯 止盈规则', '批准金额': '💵 批准金额',
                '最终置信度': '🔬 置信度', '推荐理由': '📝 推荐理由',
            }
            for j, cell in enumerate(cells):
                header = headers[j] if j < len(headers) else ''
                label = field_labels.get(header, header)
                # 标的和方向已在卡片头部显示，跳过
                if header in ('标的', '方向'):
                    continue
                # 特殊着色：止损价红色，止盈规则绿色
                value_class = ''
                if '止损' in header:
                    value_class = ' style="color:#f87171"'
                elif '止盈' in header:
                    value_class = ' style="color:#4ade80"'
                elif '置信度' in header:
                    value_class = ' style="color:#60a5fa"'
                elif '金额' in header:
                    value_class = ' style="color:#fbbf24"'
                detail_rows += f'<div class="order-detail-row"><span class="order-detail-label">{escape_html(label)}</span><span class="order-detail-value"{value_class}>{render_bold(cell)}</span></div>'

            html += f'''<div class="order-card {card_class}">
                <div class="order-card-header">
                    <span class="order-symbol">{escape_html(symbol)}</span>
                    <span class="order-direction">{direction_label}</span>
                </div>
                <div class="order-card-body">{detail_rows}</div>
            </div>'''
        return html

    def render_position_cards(table_rows):
        """将持仓明细渲染为竖排卡片"""
        if not table_rows or len(table_rows) < 2:
            return ''
        headers = table_rows[0][1]
        html = '<div class="position-cards">'
        for i, (_, cells) in enumerate(table_rows):
            if i == 0:
                continue
            symbol = cells[0] if len(cells) > 0 else ''
            direction = cells[1] if len(cells) > 1 else 'long'
            is_long = direction in ('long', '做多')
            direction_label = '🟢 多' if is_long else '🔴 空'
            
            # 盈亏着色
            pnl_pct = 0
            pnl_val = ''
            entry_price = ''
            cur_price = ''
            for j, cell in enumerate(cells):
                header = headers[j] if j < len(headers) else ''
                if '盈亏%' in header or '盈亏' in header and '%' in cell:
                    try:
                        pnl_pct = float(cell.replace('%', '').replace(',', ''))
                    except (ValueError, AttributeError):
                        pass
                    pnl_val = cell
                elif '建仓价' in header:
                    entry_price = cell
                elif '现价' in header:
                    cur_price = cell

            pnl_class = 'pnl-negative' if pnl_pct < 0 else ('pnl-positive' if pnl_pct > 0 else '')
            
            # 构建详情
            detail_rows = ''
            skip_headers = {'代码', '方向'}
            for j, cell in enumerate(cells):
                header = headers[j] if j < len(headers) else ''
                if header in skip_headers:
                    continue
                value_class = ''
                if '浮动盈亏' in header or '盈亏%' in header:
                    try:
                        nv = float(cell.replace('%', '').replace(',', ''))
                        value_class = ' style="color:#4ade80"' if nv > 0 else (' style="color:#f87171"' if nv < 0 else '')
                    except (ValueError, AttributeError):
                        pass
                detail_rows += f'<div class="pos-detail-row"><span class="pos-label">{escape_html(header)}</span><span class="pos-value"{value_class}>{render_bold(cell)}</span></div>'

            html += f'''<div class="position-card {pnl_class}">
                <div class="pos-card-header">
                    <span class="pos-symbol">{escape_html(symbol)}</span>
                    <span class="pos-direction">{direction_label}</span>
                    <span class="pos-pnl">{escape_html(pnl_val)}</span>
                </div>
                <div class="pos-card-body">{detail_rows}</div>
            </div>'''
        html += '</div>'
        return html

    # ── 渲染Section ──
    sections_html = ''
    for sec in sections:
        icon = get_section_icon(sec['title'])
        is_alert = '红线' in sec['title'] or '预警' in sec['title']
        is_summary = '净值' in sec['title'] or '风控' in sec['title']

        card_class = 'card-alert' if is_alert else ('card-summary' if is_summary else 'card-normal')

        section_html = f'<div class="card {card_class}">'
        section_html += f'<h2 class="section-title">{icon} {escape_html(sec["title"])}</h2>'

        # 解析表格
        table_rows = [item for item in sec['content'] if item[0] == 'table_row']
        other_items = [item for item in sec['content'] if item[0] != 'table_row']

        # 渲染非表格内容
        for item_type, item_text in other_items:
            if item_type == 'quote':
                section_html += f'<p class="quote">{escape_html(item_text)}</p>'
            elif item_type == 'list':
                section_html += f'<div class="list-item">• {render_bold(item_text)}</div>'
            elif item_type == 'text':
                section_html += f'<p>{render_bold(item_text)}</p>'

        # 渲染表格 — 根据section类型选择不同渲染方式
        if table_rows:
            if is_net_value_section(sec['title']):
                section_html += render_net_value_card(table_rows)
            elif is_order_section(sec['title']):
                section_html += render_order_cards(table_rows)
            elif is_position_section(sec['title']):
                section_html += render_position_cards(table_rows)
            else:
                # 默认表格渲染（适配手机端：可横向滚动）
                section_html += '<div class="table-scroll"><table>'
                for i, (_, cells) in enumerate(table_rows):
                    tag = 'th' if i == 0 else 'td'
                    processed_cells = []
                    for c in cells:
                        processed = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escape_html(c))
                        processed_cells.append(f'<{tag}>{processed}</{tag}>')
                    section_html += f'<tr>{"".join(processed_cells)}</tr>'
                section_html += '</table></div>'

        section_html += '</div>'
        sections_html += section_html

    # ── 组装完整HTML ──
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>{escape_html(title)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    line-height: 1.6;
    padding: 12px;
  }}
  .container {{
    max-width: 800px;
    margin: 0 auto;
  }}
  .header {{
    background: linear-gradient(135deg, #1e40af 0%, #7c3aed 100%);
    border-radius: 16px 16px 0 0;
    padding: 28px 20px;
    text-align: center;
  }}
  .header h1 {{
    font-size: 22px;
    color: #ffffff;
    font-weight: 700;
    letter-spacing: 1px;
  }}
  .header .date {{
    font-size: 14px;
    color: #c4b5fd;
    margin-top: 8px;
  }}
  .brand {{
    font-size: 11px;
    color: #93c5fd;
    margin-top: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
  }}
  .card {{
    background: #1e293b;
    border-radius: 12px;
    padding: 16px 18px;
    margin: 10px 0;
    border: 1px solid #334155;
  }}
  .card-alert {{
    border-left: 4px solid #ef4444;
    background: #1e293b;
  }}
  .card-summary {{
    border-left: 4px solid #3b82f6;
  }}
  .card-normal {{
    border-left: 4px solid #8b5cf6;
  }}
  .section-title {{
    font-size: 17px;
    color: #f1f5f9;
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid #334155;
    font-weight: 600;
  }}
  /* ── 净值简报：大数字卡片网格 ── */
  .net-value-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
  }}
  .net-value-card {{
    background: #0f172a;
    border-radius: 10px;
    padding: 12px 10px;
    text-align: center;
    border: 1px solid #334155;
  }}
  .nv-icon {{
    font-size: 20px;
    margin-bottom: 4px;
  }}
  .nv-label {{
    font-size: 11px;
    color: #94a3b8;
    margin-bottom: 4px;
    letter-spacing: 0.5px;
  }}
  .nv-value {{
    font-size: 16px;
    font-weight: 700;
    color: #f1f5f9;
    word-break: break-all;
  }}
  .value-positive {{
    color: #4ade80 !important;
  }}
  .value-negative {{
    color: #f87171 !important;
  }}
  /* ── 今日指令表：竖排彩色卡片 ── */
  .order-card {{
    background: #0f172a;
    border-radius: 10px;
    margin: 10px 0;
    overflow: hidden;
    border: 1px solid #334155;
  }}
  .order-card-long {{
    border-left: 4px solid #4ade80;
  }}
  .order-card-short {{
    border-left: 4px solid #f87171;
  }}
  .order-card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: linear-gradient(135deg, #1e3a5f 0%, #1e293b 100%);
  }}
  .order-symbol {{
    font-size: 18px;
    font-weight: 700;
    color: #f1f5f9;
    letter-spacing: 1px;
  }}
  .order-direction {{
    font-size: 14px;
    font-weight: 600;
  }}
  .order-card-body {{
    padding: 10px 16px;
  }}
  .order-detail-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
    border-bottom: 1px solid #1e293b;
  }}
  .order-detail-row:last-child {{
    border-bottom: none;
  }}
  .order-detail-label {{
    font-size: 12px;
    color: #94a3b8;
    flex-shrink: 0;
    margin-right: 12px;
  }}
  .order-detail-value {{
    font-size: 14px;
    color: #e2e8f0;
    font-weight: 500;
    text-align: right;
    word-break: break-all;
  }}
  /* ── 持仓明细：竖排卡片 ── */
  .position-cards {{
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .position-card {{
    background: #0f172a;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #334155;
  }}
  .position-card.pnl-negative {{
    border-left: 4px solid #f87171;
  }}
  .position-card.pnl-positive {{
    border-left: 4px solid #4ade80;
  }}
  .pos-card-header {{
    display: flex;
    align-items: center;
    padding: 10px 14px;
    background: #1e293b;
    gap: 10px;
  }}
  .pos-symbol {{
    font-size: 16px;
    font-weight: 700;
    color: #f1f5f9;
  }}
  .pos-direction {{
    font-size: 13px;
  }}
  .pos-pnl {{
    margin-left: auto;
    font-size: 14px;
    font-weight: 600;
  }}
  .pos-card-body {{
    padding: 8px 14px;
  }}
  .pos-detail-row {{
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
    border-bottom: 1px solid #1e293b;
  }}
  .pos-detail-row:last-child {{
    border-bottom: none;
  }}
  .pos-label {{
    font-size: 12px;
    color: #94a3b8;
  }}
  .pos-value {{
    font-size: 13px;
    color: #e2e8f0;
    font-weight: 500;
  }}
  /* ── 默认表格 ── */
  .table-scroll {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 13px;
  }}
  th {{
    background: #334155;
    color: #94a3b8;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }}
  td {{
    padding: 8px 10px;
    border-bottom: 1px solid #1e293b;
    color: #e2e8f0;
    white-space: nowrap;
  }}
  tr:hover td {{
    background: #263044;
  }}
  .list-item {{
    padding: 6px 0;
    color: #cbd5e1;
    font-size: 14px;
  }}
  .quote {{
    color: #94a3b8;
    font-style: italic;
    padding: 8px 0;
    font-size: 13px;
  }}
  p {{
    color: #cbd5e1;
    font-size: 14px;
    margin: 4px 0;
  }}
  strong {{
    color: #f1f5f9;
    font-weight: 600;
  }}
  .footer {{
    text-align: center;
    padding: 18px;
    color: #64748b;
    font-size: 11px;
    border-top: 1px solid #334155;
    margin-top: 14px;
    line-height: 1.8;
  }}
  /* ── 手机端响应式 ── */
  @media only screen and (max-width: 600px) {{
    body {{ padding: 6px; }}
    .header {{ padding: 18px 14px; border-radius: 12px 12px 0 0; }}
    .header h1 {{ font-size: 18px; }}
    .card {{ padding: 12px 14px; margin: 8px 0; border-radius: 10px; }}
    .section-title {{ font-size: 15px; margin-bottom: 10px; }}
    /* 净值简报手机端：2列 */
    .net-value-grid {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
    .nv-value {{ font-size: 14px; }}
    .nv-label {{ font-size: 10px; }}
    .nv-icon {{ font-size: 16px; }}
    /* 指令表卡片 */
    .order-symbol {{ font-size: 16px; }}
    .order-detail-label {{ font-size: 11px; }}
    .order-detail-value {{ font-size: 13px; }}
    /* 持仓卡片 */
    .pos-symbol {{ font-size: 15px; }}
    .pos-label {{ font-size: 11px; }}
    .pos-value {{ font-size: 12px; }}
    /* 表格 */
    table {{ font-size: 12px; }}
    th, td {{ padding: 6px 8px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📈 {escape_html(title)}</h1>
    <div class="date">{escape_html(date_str)}</div>
    <div class="brand">Blakever Multi-Agent Investment Decision System</div>
  </div>
  {sections_html}
  <div class="footer">
    本报告由 Blakever 多智能体投资决策系统自动生成<br>
    仅供投资参考，不构成投资建议。投资有风险，入市需谨慎。
  </div>
</div>
</body>
</html>"""


def send_email(report: str, recipient: str, args: argparse.Namespace) -> bool:
    """
    Step 14: 将报告发送到指定邮箱。

    优先使用环境变量中的 SMTP 配置，
    若无则提示用户手动发送。
    """
    smtp_server = os.environ.get('BLAKEVER_SMTP_SERVER', args.smtp_server)
    smtp_port = int(os.environ.get('BLAKEVER_SMTP_PORT', args.smtp_port))
    smtp_user = os.environ.get('BLAKEVER_SMTP_USER', args.smtp_user)
    smtp_password = os.environ.get('BLAKEVER_SMTP_PASSWORD', args.smtp_password)
    email_from = os.environ.get('BLAKEVER_EMAIL_FROM', args.email_from or smtp_user)

    if not smtp_server or not smtp_user or not smtp_password:
        logger.warning("📧 SMTP 配置不完整，无法自动发送邮件")
        logger.info("📧 请设置以下环境变量或命令行参数后重试：")
        logger.info("   BLAKEVER_SMTP_SERVER   (或 --smtp-server)")
        logger.info("   BLAKEVER_SMTP_PORT     (或 --smtp-port, 默认587)")
        logger.info("   BLAKEVER_SMTP_USER     (或 --smtp-user)")
        logger.info("   BLAKEVER_SMTP_PASSWORD (或 --smtp-password)")
        logger.info("   BLAKEVER_EMAIL_FROM    (或 --email-from)")
        logger.info("")
        logger.info("📄 报告内容已打印到上方控制台，您也可以手动复制发送。")
        return False

    logger.info(f"📧 发送报告到 {recipient}...")

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    subject = f"Blakever 每日操作建议指南 - {now}"

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = email_from
    msg['To'] = recipient

    # 纯文本版本
    text_part = MIMEText(report, 'plain', 'utf-8')
    msg.attach(text_part)

    # HTML版本 — 专业投资报告样式
    html_content = _markdown_to_html_email(report, now)
    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)

    try:
        # QQ邮箱等使用SSL（端口465），其他使用STARTTLS（端口587）
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.sendmail(email_from, recipient, msg.as_string())
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.sendmail(email_from, recipient, msg.as_string())
        logger.info(f"   ✅ 邮件发送成功！")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("   ❌ SMTP 认证失败：用户名或密码错误")
        return False
    except smtplib.SMTPConnectError:
        logger.error(f"   ❌ 无法连接 SMTP 服务器 {smtp_server}:{smtp_port}")
        return False
    except Exception as e:
        logger.error(f"   ❌ 邮件发送失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Blakever 生产运行脚本 — 真实数据模式')
    parser.add_argument('--email', required=True, help='报告接收邮箱地址')
    parser.add_argument('--index-symbol', default=os.environ.get('BLAKEVER_INDEX_SYMBOL', 'SPY'),
                        help='大盘指数代码（默认 SPY）')
    parser.add_argument('--market', default=os.environ.get('BLAKEVER_MARKET', 'all'),
                        choices=['us', 'hk', 'all'],
                        help='选股池市场范围: us(美股), hk(港股), all(全部，默认)')
    parser.add_argument('--stocks', default=os.environ.get('BLAKEVER_STOCK_SYMBOLS', ''),
                        help='股票池代码，逗号分隔（为空则使用内置选股池）')
    parser.add_argument('--pool-filter', default=os.environ.get('BLAKEVER_POOL_FILTER', 'volume'),
                        choices=['none', 'volume', 'top50'],
                        help='选股池预筛选策略: none(全量), volume(按成交额粗筛), top50(取市值前50)')
    parser.add_argument('--equity', type=float,
                        default=float(os.environ.get('BLAKEVER_ACCOUNT_EQUITY', '100000000')),
                        help='账户净值（默认 100000000）')
    parser.add_argument('--cash', type=float,
                        default=float(os.environ.get('BLAKEVER_CASH', '100000000')),
                        help='现金（默认 100000000，空仓启动时现金=净值）')
    parser.add_argument('--smtp-server', default='smtp.qq.com', help='SMTP 服务器地址（默认 smtp.qq.com）')
    parser.add_argument('--smtp-port', type=int, default=465, help='SMTP 端口（默认 465 SSL）')
    parser.add_argument('--smtp-user', default='848786642@qq.com', help='SMTP 用户名')
    parser.add_argument('--smtp-password', default='ljbtvacrctjobfed', help='SMTP 授权码')
    parser.add_argument('--email-from', default='848786642@qq.com', help='发件人地址')

    args = parser.parse_args()

    # ── 构建股票池 ──
    if args.stocks:
        # 用户显式指定了股票代码
        stock_symbols = [s.strip() for s in args.stocks.split(',') if s.strip()]
    else:
        # 使用内置选股池（标普500 + 纳指100 + 恒生科技 + 恒生指数）
        from stock_pool import get_pool_for_market, get_us_symbols, get_hk_symbols
        stock_symbols = get_pool_for_market(args.market)
        logger.info(f"📋 使用内置选股池 (market={args.market}): 标普500+纳指100+恒生科技+恒生指数")
        logger.info(f"   美股: {len(get_us_symbols())} 只, 港股: {len(get_hk_symbols())} 只, 总计: {len(stock_symbols)} 只")

    # 根据市场自动设置大盘指数
    if args.market == 'hk' and args.index_symbol == 'SPY':
        args.index_symbol = 'HSI'
        logger.info(f"   自动切换港股大盘指数: HSI")

    # ── 开场 ──
    logger.info("=" * 70)
    logger.info("🚀 Blakever 生产运行 — 真实数据模式")
    logger.info("=" * 70)
    logger.info(f"📧 报告将发送到: {args.email}")
    logger.info(f"📈 大盘指数: {args.index_symbol}")
    logger.info(f"📊 股票池: {stock_symbols}")
    logger.info(f"💰 账户净值: {args.equity:,.0f}, 现金: {args.cash:,.0f}")
    logger.info("")

    # ── 依赖检查 ──
    if not check_dependencies():
        logger.error("❌ 依赖检查未通过，请安装缺失的依赖后重试")
        sys.exit(1)

    # ── Step 1: 获取真实行情数据 ──
    logger.info("")
    logger.info("─" * 50)
    logger.info("📡 Step 1: 获取真实行情数据 (yfinance)")
    try:
        data = fetch_real_data(args.index_symbol, stock_symbols)
        if data['fetch_errors']:
            for err in data['fetch_errors']:
                logger.warning(f"   ⚠️ {err}")
        if not data['stock_data']:
            logger.error("❌ 股票池数据全部获取失败，无法继续")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 行情数据获取失败: {e}")
        sys.exit(1)

    # ── 构建辅助映射 ──
    logger.info("")
    logger.info("─" * 50)
    logger.info("📋 辅助映射构建（行业、市值、Beta等）")
    try:
        maps = build_auxiliary_maps(data['stock_data'], stock_symbols)
    except Exception as e:
        logger.error(f"❌ 辅助映射构建失败: {e}")
        sys.exit(1)

    # ── Steps 2-12: 完整决策链路 ──
    logger.info("")
    logger.info("─" * 50)
    logger.info("🧠 决策链路执行")
    try:
        result = run_full_decision(data, maps, args)
    except Exception as e:
        logger.error(f"❌ 决策链路执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # ── Step 13: 傻瓜交易员执行 ──
    logger.info("")
    logger.info("─" * 50)
    logger.info("💹 Step 13: 傻瓜交易员执行 (Agent 6)")
    execution_report_section = ''
    try:
        from fool_trader import run_execution
        from data_fetcher import extract_current_prices, extract_avg_daily_volumes

        execution_orders = result.get('execution_orders', [])
        stock_data = data.get('stock_data', {})
        all_data = {args.index_symbol: data.get('index_df')}
        all_data.update(stock_data)
        current_prices = extract_current_prices(all_data)
        avg_daily_volumes = extract_avg_daily_volumes(stock_data)

        # 读取上一次的持仓快照（如果有）
        import json as json_mod
        holdings_snapshot_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              'holdings_snapshot.json')
        prev_positions = []
        prev_cash = args.cash
        if os.path.exists(holdings_snapshot_file):
            try:
                with open(holdings_snapshot_file, 'r') as f:
                    snapshot = json_mod.load(f)
                prev_positions = snapshot.get('positions', [])
                prev_cash = snapshot.get('cash', args.cash)
                if prev_positions:
                    logger.info(f"   📂 恢复上次持仓快照: {len(prev_positions)} 只持仓, "
                                f"现金={prev_cash:,.0f}")
            except Exception as e:
                logger.warning(f"   ⚠️ 持仓快照读取失败，从空仓启动: {e}")

        # ── 每日操作去重：检查今天是否已执行过操作 ──
        today_str = datetime.now().strftime('%Y-%m-%d')
        trade_history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          'trade_history.md')
        today_trades = []
        if os.path.exists(trade_history_file):
            try:
                with open(trade_history_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith('|') and today_str in line:
                            cells = [c.strip() for c in line.split('|') if c.strip()]
                            if len(cells) >= 7 and cells[0] != '时间':
                                today_trades.append({
                                    'symbol': cells[1],
                                    'direction': cells[2],
                                    'action': cells[3],
                                    'price': float(cells[4]),
                                    'quantity': float(cells[5]),
                                    'amount': float(cells[6]),
                                    'reason': cells[7] if len(cells) > 7 else ''
                                })
            except Exception as e:
                logger.warning(f"   ⚠️ 交易历史读取失败: {e}")

        if today_trades:
            logger.info(f"   ⚠️ 检测到今天已有 {len(today_trades)} 笔操作，执行回滚后用最新指令替换")

            # 回滚：撤销今天的操作（反向操作）
            for trade in reversed(today_trades):
                sym = trade['symbol']
                action = trade['action']
                amount = trade['amount']
                quantity = trade['quantity']

                if action in ('buy',):
                    # 回滚买入：从持仓中移除或减仓
                    existing = next((p for p in prev_positions
                                    if p.get('symbol') == sym), None)
                    if existing:
                        old_size = float(existing.get('position_size', 0))
                        old_qty = float(existing.get('quantity', 0))
                        # 减去本次买入的数量
                        new_size = old_size - amount
                        new_qty = old_qty - quantity
                        if new_qty <= 0 or new_size <= 0:
                            # 完全移除
                            prev_positions = [p for p in prev_positions
                                             if p.get('symbol') != sym]
                            prev_cash += old_size  # 恢复全部持仓金额
                            logger.info(f"   🔄 回滚 {sym}: 移除持仓，恢复现金 {old_size:,.0f}")
                        else:
                            existing['position_size'] = round(new_size, 2)
                            existing['quantity'] = round(new_qty, 2)
                            prev_cash += amount  # 恢复本次买入的金额
                            logger.info(f"   🔄 回滚 {sym}: 减仓 {amount:,.0f}，剩余 {new_size:,.0f}")
                elif action in ('sell', 'cover'):
                    # 回滚卖出：恢复持仓
                    prev_cash -= amount
                    prev_positions.append({
                        'symbol': sym,
                        'direction': trade['direction'],
                        'entry_price': trade['price'],
                        'current_price': trade['price'],
                        'position_size': amount,
                        'quantity': quantity,
                        'pnl': 0,
                        'pnl_pct': 0,
                        'max_profit_since_entry': 0
                    })
                    logger.info(f"   🔄 回滚 {sym}: 恢复卖出持仓 {amount:,.0f}")

            # 清除今天的交易历史记录
            try:
                with open(trade_history_file, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                # 保留非今天的记录
                new_lines = [l for l in all_lines if today_str not in l]
                # 保留表头
                header_lines = [l for l in all_lines if l.strip().startswith('|') and '时间' in l]
                # 重写文件
                with open(trade_history_file, 'w', encoding='utf-8') as f:
                    if header_lines:
                        f.write(header_lines[0])
                    for l in new_lines:
                        if l.strip().startswith('|') and '时间' not in l:
                            f.write(l)
                logger.info(f"   ✅ 交易历史已清理今天 {len(today_trades)} 条旧记录")
            except Exception as e:
                logger.warning(f"   ⚠️ 交易历史清理失败: {e}")

        # 获取情绪因子
        sentiment_factor = 0.0
        if result.get('cro_result', {}).get('market_environment'):
            sentiment_factor = result['cro_result']['market_environment'].get('sentiment_factor', 0.0)

        # 执行交易
        exec_result = run_execution(
            execution_orders=execution_orders,
            current_prices=current_prices,
            avg_daily_volumes=avg_daily_volumes,
            current_positions=prev_positions,
            cash=prev_cash,
            inception_equity=args.equity,
            sentiment_factor=sentiment_factor
        )

        # 更新持仓和现金
        updated_positions = exec_result.get('updated_positions', [])
        account_summary = exec_result.get('account_summary', {})
        execution_results = exec_result.get('execution_results', [])

        # 将新执行的订单加入持仓
        new_cash = prev_cash
        for er in execution_results:
            if er['status'] == 'OK' and er['quantity'] > 0:
                order = next((o for o in execution_orders
                              if o['symbol'] == er['symbol']), None)
                direction = order.get('direction', 'long') if order else 'long'
                action = er['action']
                if action in ('buy',):
                    new_cash -= er['amount']
                    # 检查是否已存在同名持仓
                    existing = next((p for p in updated_positions
                                    if p.get('symbol') == er['symbol']), None)
                    if existing:
                        # 加仓：更新均价和数量
                        old_size = float(existing.get('position_size', 0))
                        old_entry = float(existing.get('entry_price', 0))
                        new_size = er['amount']
                        new_entry = er['executed_price']
                        total_size = old_size + new_size
                        avg_price = (old_size * old_entry + new_size * new_entry) / total_size if total_size > 0 else new_entry
                        existing['position_size'] = round(total_size, 2)
                        existing['entry_price'] = round(avg_price, 4)
                        existing['current_price'] = er['executed_price']
                    else:
                        # 新建仓
                        updated_positions.append({
                            'symbol': er['symbol'],
                            'direction': direction,
                            'entry_price': er['executed_price'],
                            'current_price': er['executed_price'],
                            'position_size': er['amount'],
                            'quantity': er['quantity'],
                            'pnl': 0,
                            'pnl_pct': 0,
                            'max_profit_since_entry': 0
                        })
                elif action in ('sell', 'cover'):
                    new_cash += er['amount']
                    # 移除已平仓的持仓
                    updated_positions = [p for p in updated_positions
                                         if p.get('symbol') != er['symbol']]

        # 重新计算账户汇总
        from fool_trader import calculate_account_summary, update_all_positions, update_holdings
        # 用最新价格更新所有持仓P&L
        updated_positions, _ = update_all_positions(updated_positions, current_prices)
        account_summary = calculate_account_summary(updated_positions, new_cash, args.equity)

        # 持久化持仓快照
        try:
            with open(holdings_snapshot_file, 'w') as f:
                json_mod.dump({
                    'positions': updated_positions,
                    'cash': new_cash,
                    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"   ⚠️ 持仓快照保存失败: {e}")

        # 持久化当前持仓到 cur_holdings.md
        try:
            update_holdings(updated_positions)
        except Exception as e:
            logger.warning(f"   ⚠️ 持仓文件更新失败: {e}")

        # 生成傻瓜交易员报告段落
        total_equity = account_summary['total_equity']
        total_return = account_summary['total_return_since_inception']
        total_pnl = account_summary['total_unrealized_pnl']
        position_value = account_summary['total_position_value']

        logger.info(f"   ✅ 账户净值={total_equity:,.0f}, 总收益率={total_return:.2f}%")
        logger.info(f"   ✅ 持仓市值={position_value:,.0f}, 浮动盈亏={total_pnl:,.0f}")
        logger.info(f"   ✅ 现金={new_cash:,.0f}, 持仓数={len(updated_positions)}")

        # 构建追加到报告的傻瓜交易员部分
        execution_report_section = f"""

## 💰 净值简报（傻瓜交易员实时）
| 指标 | 值 |
| 账户净值 | {total_equity:,.0f} |
| 现金 | {new_cash:,.0f} |
| 持仓市值 | {position_value:,.0f} |
| 浮动盈亏 | {total_pnl:,.0f} |
| 总收益率 | {total_return:.2f}% |
| 持仓数 | {len(updated_positions)} |
"""

        # 持仓明细
        if updated_positions:
            execution_report_section += """
### 📦 持仓明细
| 代码 | 方向 | 建仓价 | 现价 | 持仓金额 | 数量 | 浮动盈亏 | 盈亏% | 历史最大盈利 |
"""
            for p in updated_positions:
                sym = p.get('symbol', '')
                direction = p.get('direction', 'long')
                entry = p.get('entry_price', 0)
                cur = p.get('current_price', 0)
                size = p.get('position_size', 0)
                qty = p.get('quantity', p.get('position_size', 0))
                pnl = p.get('pnl', 0)
                pnl_pct = p.get('pnl_pct', 0)
                max_profit = p.get('max_profit_since_entry', 0)
                execution_report_section += (f"| {sym} | {direction} | {entry:.2f} | "
                                             f"{cur:.2f} | {size:,.0f} | {qty:.0f} | "
                                             f"{pnl:,.0f} | {pnl_pct:.1f}% | "
                                             f"{max_profit:,.0f} |\n")
        else:
            execution_report_section += "\n**当前空仓，无持仓**\n"

        # 今日执行记录
        if execution_results:
            ok_results = [r for r in execution_results if r['status'] == 'OK' and r['quantity'] > 0]
            if ok_results:
                execution_report_section += """
### 📝 今日执行记录
| 代码 | 动作 | 成交价 | 数量 | 金额 | 状态 |
"""
                for r in ok_results:
                    execution_report_section += (f"| {r['symbol']} | {r['action']} | "
                                                 f"{r['executed_price']:.2f} | "
                                                 f"{r['quantity']:.0f} | {r['amount']:,.0f} | "
                                                 f"{r['status']} |\n")
            rejected = [r for r in execution_results if r['status'] != 'OK']
            if rejected:
                execution_report_section += "\n**⚠️ 被拒绝/冻结的订单:**\n"
                for r in rejected:
                    execution_report_section += f"- {r['symbol']}: {r.get('message', r['status'])}\n"

        # 如果今天有回滚操作，增加说明
        if today_trades:
            execution_report_section += (f"\n> 🔄 本次运行检测到今天已有 {len(today_trades)} 笔操作，"
                                         f"已自动回滚并使用最新指令替换\n")

    except Exception as e:
        logger.error(f"❌ 傻瓜交易员执行失败: {e}")
        import traceback
        traceback.print_exc()
        execution_report_section = f"\n## 💰 净值简报\n⚠️ 傻瓜交易员执行失败: {e}\n"

    # ── Step 14: 生成最终报告 ──
    logger.info("")
    logger.info("─" * 50)
    logger.info("📄 报告生成")
    report = result.get('report', '（无报告生成）')
    # 用傻瓜交易员实时数据替换报告中的净值简报
    import re as _re
    report = _re.sub(
        r'## 💰 净值简报\n.*?\Z',
        execution_report_section,
        report,
        flags=_re.DOTALL
    )

    # ── Step 15: 发送邮件 ──
    logger.info("")
    logger.info("─" * 50)
    logger.info("📧 邮件发送")
    email_sent = send_email(report, args.email, args)

    # ── 完成 ──
    logger.info("")
    logger.info("=" * 70)
    logger.info("🏁 Blakever 生产运行完成")
    logger.info("=" * 70)
    if email_sent:
        logger.info(f"✅ 报告已发送到 {args.email}")
    else:
        logger.info("⚠️ 邮件未发送，报告已在上方打印")

    # 将报告也写入本地文件
    report_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"📄 报告已保存到: {report_file}")
    except Exception as e:
        logger.warning(f"⚠️ 报告文件保存失败: {e}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️ 用户中断执行")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ 运行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
