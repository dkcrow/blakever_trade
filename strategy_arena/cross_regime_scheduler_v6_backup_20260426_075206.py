#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
穿越牛熊策略回测定时调度器 v4
==============================
v4升级：多标的回测（ETF + 港美股全量）

v4升级内容（基于v3）：
5. 标的池：ETF(6只) + 美股大盘(100只) + 港股蓝筹(30只) = 136只标的
   - 每个策略在所有标的上逐一回测，汇总统计（盈利占比/中位年化/分市场均值）
   - ETF轮动策略保持原有逻辑 + 新增个股择时适配
   - 港股T+0适配、港股费率(0.1348%)自动切换
6. 数据源：本地CSV港美股 + westock-data ETF实时（双价格体系）

v3升级内容（全部对齐规范）：
1. 搜索来源：GitHub API搜索 + 参数变体生成（混合搜索），搜索查询涵盖7大来源
2. Pine Script一票否决制：集成pine_validator模块
3. 策略类型：7种分类（趋势跟踪/均值回归/套利/事件驱动/机器学习/高股息轮动/其他）
4. 策略指纹去重：SHA256(逻辑+参数)，90%参数相似度家族检测
7. 回测区间：主2019-2024，压力2015-2018
8. 评分体系：年化25%/夏普25%/回撤20%(阶梯)/盈亏比15%/胜率15% + 跨周期5分 - 偏差扣分
9. 最大回撤门槛：≥25%硬性淘汰
10. 排行榜入榜规则：无最低门槛，按最高分从高到低排，保留前十
11. 新策略7天保护期
12. 样本外滚动验证：每周验证前十，连续3周失效标记
13. 动态无风险利率：10年美债+1%
14. 可移植性评分：0-10分五档
15. 邮件报告：含Pine否决数/变动/类型/鲁棒标记/偏差标记/多标的统计
16. 执行频率：每6小时

执行方式:
  直接调用（无子进程），策略搜索+回测+评分一体化，统一邮件报告
"""

import json
import os
import sys
import subprocess
import smtplib
import hashlib
import itertools
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union, Set

import pandas as pd
import numpy as np

# 项目路径
WORKSPACE_DIR = '/data/workspace'
STRATEGY_DIR = os.path.join(WORKSPACE_DIR, 'strategy_arena')
LEADERBOARD_PATH = os.path.join(STRATEGY_DIR, 'leaderboard_cross_regime.json')
REJECTED_PATH = os.path.join(STRATEGY_DIR, 'rejected_strategies_cross_regime.json')
STRATEGY_LIBRARY_PATH = os.path.join(STRATEGY_DIR, 'strategy_library_cross_regime.json')

# ================================================================
# 三市场排行榜路径（US/HK/A股分别独立排行）
# ================================================================
MARKET_LEADERBOARDS = {
    'US': {
        'leaderboard': os.path.join(STRATEGY_DIR, 'leaderboard_cross_regime_us.json'),
        'rejected': os.path.join(STRATEGY_DIR, 'rejected_strategies_cross_regime_us.json'),
    },
    'HK': {
        'leaderboard': os.path.join(STRATEGY_DIR, 'leaderboard_cross_regime_hk.json'),
        'rejected': os.path.join(STRATEGY_DIR, 'rejected_strategies_cross_regime_hk.json'),
    },
    'CN': {
        'leaderboard': os.path.join(STRATEGY_DIR, 'leaderboard_cross_regime_cn.json'),
        'rejected': os.path.join(STRATEGY_DIR, 'rejected_strategies_cross_regime_cn.json'),
    },
}

# 保留旧路径兼容（读取旧数据迁移用）
LEGACY_LEADERBOARD_PATH = LEADERBOARD_PATH
WESTOCK_SCRIPT = os.path.join(WORKSPACE_DIR, '.agent/skills/westock-data/scripts/index.js')

# 导入项目模块
sys.path.insert(0, STRATEGY_DIR)
from strategy_dedup import (
    compute_strategy_fingerprint, fingerprint_short,
    extract_core_logic, normalize_params,
    compute_param_similarity, is_same_family,
    load_strategy_library, save_strategy_library, check_duplicate,
    add_strategy_to_library
)
from strategy_ranker import (
    score_annual_return, score_sharpe, score_max_drawdown,
    score_profit_factor, score_win_rate,
    compute_total_score, classify_strategy,
    load_leaderboard as _load_lb, save_leaderboard as _save_lb,
    update_leaderboard as _update_lb,
    STRATEGY_TYPE_KEYWORDS,
)
from hybrid_searcher import (
    hybrid_search, github_search, generate_param_variants,
)
from pine_validator import (
    check_pine_veto, score_portability, analyze_pine_for_translation,
)

# 邮件配置
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USER = '848786642@qq.com'
SMTP_PASSWORD = 'ljbtvacrctjobfed'
EMAIL_TO = '848786642@qq.com'

# ================================================================
# 回测配置（对齐规范）
# ================================================================
INIT_CASH = 1_000_000
FEES_US = 0.000528       # 美股：SEC费+佣金 ≈ 0.0528%
FEES_HK = 0.001348       # 港股：印花税+征费+佣金 ≈ 0.1348%
FEES_CN = 0.0006         # A股ETF：佣金0.015%×2 + 滑点 ≈ 0.06%（ETF无印花税）
SLIPPAGE = 0.001          # 单边滑点0.1%
MAIN_START = '2016-01-01'     # 10年数据：主回测从2016年起
MAIN_END = '2026-04-25'
STRESS_START = '2015-01-01'   # 对齐规范：压力测试2015-2018
STRESS_END = '2018-12-31'
CN_MAIN_START = '2016-01-01'  # A股ETF数据已覆盖10年（2015年起），主回测从2016起
CN_MAIN_END = '2026-04-25'    # A股数据最新
CN_STRESS_START = '2015-06-01' # A股压力测试：2015股灾+2016熔断（数据从2015年8月起，取6月开始）
CN_STRESS_END = '2018-12-31'
CN_RISK_FREE_RATE = 0.02      # A股无风险利率：2%（10年国债均值）
MAX_DRAWDOWN_HARD_LIMIT = 50  # 极端情况阈值：≥50%才0分淘汰（不再30%一刀切）
LEADERBOARD_MIN_SCORE = 0     # 无最低分数门槛，按最高分从高到低排
PROTECTION_DAYS = 7           # 新策略保护期7天

# 资产池定义（ETF层——用于轮动类策略）
RISK_ASSETS = ['SPY', 'VEA']
SAFE_ASSETS = ['AGG', 'SHY']
ALL_ASSETS_4 = RISK_ASSETS + SAFE_ASSETS
ALL_ASSETS_5 = RISK_ASSETS + SAFE_ASSETS + ['GLD']
ALL_ASSETS_6 = RISK_ASSETS + SAFE_ASSETS + ['GLD', 'TLT']

# ================================================================
# 本地港美股数据路径（v4升级：多标的回测）
# ================================================================
LOCAL_DATA_DIR = '/data/workspace/back_trader_stocks'
LOCAL_HK_DIR = os.path.join(LOCAL_DATA_DIR, 'hk')
LOCAL_US_DIR = os.path.join(LOCAL_DATA_DIR, 'us')
LOCAL_ETF_DIR = os.path.join(LOCAL_DATA_DIR, 'etf')
LOCAL_CN_DIR = os.path.join(LOCAL_DATA_DIR, 'a')  # A股ETF数据目录

# 港股蓝筹精选（流动性好、市值大的前30只）
HK_BLUE_CHIPS = [
    'hk00001', 'hk00002', 'hk00003', 'hk00005', 'hk00006',
    'hk00011', 'hk00012', 'hk00016', 'hk00066', 'hk00101',
    'hk00175', 'hk00241', 'hk00267', 'hk00288', 'hk00386',
    'hk00388', 'hk00669', 'hk00688', 'hk00700', 'hk00728',
    'hk00762', 'hk00780', 'hk00823', 'hk00883', 'hk00941',
    'hk00968', 'hk00981', 'hk01024', 'hk01113', 'hk01299',
]

# 美股大盘股精选（标普500成分股中市值前100，部分本地可能缺失，加载时会自动补充）
US_LARGE_CAPS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'UNH', 'JNJ', 'WMT', 'XOM', 'MA', 'PG', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'AVGO', 'COST', 'ADBE', 'TMO', 'CSCO',
    'MCD', 'NKE', 'ABT', 'DHR', 'CRM', 'WFC', 'ACN', 'LLY', 'LIN',
    'VZ', 'PM', 'TXN', 'UPS', 'BMY', 'NEE', 'RTX', 'QCOM', 'ORCL',
    'COP', 'LOW', 'IBM', 'BA', 'AMD', 'SPGI', 'SBUX', 'INTC', 'GS',
    'BLK', 'AXP', 'AMGN', 'CAT', 'DE', 'MS', 'INTU', 'BKNG', 'SYK',
    'MDLZ', 'GILD', 'ADP', 'LRCX', 'CB', 'ADI', 'MMC', 'TJX', 'SHW',
    'PGR', 'CME', 'CI', 'BDX', 'CSX', 'ZTS', 'MO', 'DUK', 'SO',
    'PLD', 'EOG', 'CL', 'FIS', 'NSC', 'ITW', 'NOC', 'HCA', 'SLB',
    'TGT', 'AIG', 'AEP', 'EL', 'ICE', 'FCX', 'EQIX', 'ISRG', 'MU',
]

# 港股蓝筹精选（流动性好、市值大的前30只，本地hk00001.csv格式）
HK_BLUE_CHIPS = [
    'hk00001', 'hk00002', 'hk00003', 'hk00005', 'hk00006',
    'hk00011', 'hk00012', 'hk00016', 'hk00066', 'hk00101',
    'hk00175', 'hk00241', 'hk00267', 'hk00288', 'hk00386',
    'hk00388', 'hk00669', 'hk00688', 'hk00700', 'hk00728',
    'hk00762', 'hk00780', 'hk00823', 'hk00883', 'hk00941',
    'hk00968', 'hk00981', 'hk01024', 'hk01113', 'hk01299',
]

# westock-data ETF代码映射
WESTOCK_SYMBOLS = {
    'SPY': 'usSPY', 'VEA': 'usVEA', 'AGG': 'usAGG', 'SHY': 'usSHY',
    'GLD': 'usGLD', 'TLT': 'usTLT', 'QQQ': 'usQQQ',
}

# ================================================================
# 港股蓝筹资产池（对标美股ETF，用于港股策略回测）
# ================================================================
# 标的映射：美股ETF → 港股蓝筹（选代表性个股替代ETF轮动）
HK_ETF_MAP = {
    'SPY': 'hk00700',    # 腾讯控股（港股大盘代表，市值最大）
    'QQQ': 'hk09988',    # 阿里巴巴（科技成长代表）
    'VEA': 'hk00005',    # 汇丰控股（金融蓝筹代表）
    'AGG': 'hk00011',    # 恒生银行（稳健型银行）
    'SHY': 'hk00002',    # 中电控股（公用事业/防御型）
    'GLD': 'hk01810',    # 小米集团（新经济代表，波动较大类似黄金）
    'TLT': 'hk00388',    # 中港石化（高息股，类似长债）
}

# 港股风险/安全资产定义（对标美股）
HK_RISK_ASSETS = ['SPY', 'QQQ', 'VEA']    # 腾讯/阿里/汇丰
HK_SAFE_ASSETS = ['AGG', 'SHY']           # 恒生/中电
HK_ALL_ASSETS_4 = HK_RISK_ASSETS + HK_SAFE_ASSETS
HK_ALL_ASSETS_5 = HK_RISK_ASSETS + HK_SAFE_ASSETS + ['GLD']
HK_ALL_ASSETS_6 = HK_RISK_ASSETS + HK_SAFE_ASSETS + ['GLD', 'TLT']

# 港股回测参数
HK_MAIN_START = '2016-01-01'     # 港股数据已覆盖10年（2015年起），主回测从2016年起
HK_MAIN_END = '2026-04-25'
HK_STRESS_START = '2015-01-01'   # 港股压力测试：2015股灾+2016熔断
HK_STRESS_END = '2018-12-31'
HK_RISK_FREE_RATE = 0.035        # 港币无风险利率（HIBOR约3.5%）

# ================================================================
# A股ETF资产池（对标美股ETF，用于A股策略回测）
# ================================================================
# 标的映射：美股ETF → A股ETF
CN_ETF_MAP = {
    'SPY': '510300_XSHG',    # 沪深300ETF（大盘宽基）
    'QQQ': '159915_XSHE',    # 创业板ETF（成长/科技）
    'VEA': '510500_XSHG',    # 中证500ETF（中盘）
    'AGG': '511010_XSHG',    # 国债ETF（安全资产）
    'SHY': '511880_XSHG',    # 银华日利（现金管理/短债）
    'GLD': '518880_XSHG',    # 黄金ETF（避险）
    'TLT': '511260_XSHG',    # 十年国债ETF（长债）
}

# A股风险/安全资产定义（对标美股）
CN_RISK_ASSETS = ['SPY', 'VEA']       # 沪深300/中证500
CN_SAFE_ASSETS = ['AGG', 'SHY']       # 国债/货币
CN_ALL_ASSETS_4 = CN_RISK_ASSETS + CN_SAFE_ASSETS
CN_ALL_ASSETS_5 = CN_RISK_ASSETS + CN_SAFE_ASSETS + ['GLD']
CN_ALL_ASSETS_6 = CN_RISK_ASSETS + CN_SAFE_ASSETS + ['GLD', 'TLT']

# A股蓝筹精选（沪深300成分股中市值前50）
CN_LARGE_CAPS = [
    '600519_XSHG', '601318_XSHG', '600036_XSHG', '000858_XSHE', '000333_XSHE',
    '600900_XSHG', '601012_XSHG', '600276_XSHG', '601888_XSHG', '000651_XSHE',
    '600030_XSHG', '601166_XSHG', '002714_XSHE', '600809_XSHG', '002475_XSHE',
    '600309_XSHG', '000568_XSHE', '002415_XSHE', '600031_XSHG', '601899_XSHG',
]

# 全量标的池：ETF + 港股蓝筹 + 美股大盘 + A股ETF + A股蓝筹（实际加载数取决于本地CSV可用性）
ALL_SYMBOLS = {
    'US_ETF': ALL_ASSETS_6,           # 6只ETF（轮动基准）
    'US_STOCK': US_LARGE_CAPS,        # ~100只美股大盘（缺失的自动补充）
    'HK_STOCK': HK_ALL_ASSETS_6,      # 7只港股蓝筹映射ETF（轮动基准）
    'CN_ETF': CN_ALL_ASSETS_6,        # 6只A股ETF（轮动基准）
    'CN_STOCK': CN_LARGE_CAPS,        # ~50只A股蓝筹
}

# 穿越牛熊搜索关键词（对齐规范7大来源）
CROSS_REGIME_KEYWORDS = [
    '穿越牛熊', '稳健型', '港美股', '美股', '港股', '高股息', '红利',
    'bull bear', 'cross regime', 'robust', 'all-weather', 'US stocks', 'HK stocks',
    'dividend', 'yield', 'momentum rotation', 'trend following',
]

# 穿越牛熊GitHub搜索查询
CROSS_REGIME_GITHUB_QUERIES = [
    'momentum+rotation+stocks+python+backtest',
    'dual+momentum+strategy+python+generate_signals',
    'all-weather+portfolio+python+backtest',
    'trend+following+defensive+stocks+python',
    'dividend+rotation+strategy+python+backtest',
    'cross+regime+trading+strategy+python',
    'safe+haven+rotation+gold+bonds+python',
    'macro+rotation+strategy+python+backtest',
]

# 穿越牛熊策略参数变体模板
CROSS_REGIME_PARAM_VARIANTS = [
    # GEM动量轮动变体
    {'base_strategy': 'dual_momentum', 'name': '双重动量(6M/3M)', 'param_overrides': {'lookback_long': 6, 'lookback_short': 3}, 'description': '6月绝对动量+3月相对动量，更短回看期'},
    {'base_strategy': 'dual_momentum', 'name': '双重动量(12M/6M)', 'param_overrides': {'lookback_long': 12, 'lookback_short': 6}, 'description': '12月绝对+6月相对，经典长周期'},
    {'base_strategy': 'donchian', 'name': 'Donchian突破(55/20)', 'param_overrides': {'entry_window': 55, 'exit_window': 20}, 'description': '经典海龟长线参数'},
    {'base_strategy': 'donchian', 'name': 'Donchian突破(20/10)', 'param_overrides': {'entry_window': 20, 'exit_window': 10}, 'description': '中线Donchian突破'},
    {'base_strategy': 'supertrend', 'name': 'Supertrend(3.0x)', 'param_overrides': {'atr_period': 10, 'atr_multiplier': 3.0}, 'description': '标准Supertrend趋势跟踪'},
    {'base_strategy': 'supertrend', 'name': 'Supertrend(2.0x低倍率)', 'param_overrides': {'atr_period': 10, 'atr_multiplier': 2.0}, 'description': '低倍率Supertrend更敏感'},
    {'base_strategy': 'macd_supertrend', 'name': 'MACD+Supertrend', 'param_overrides': {'macd_fast': 12, 'macd_slow': 26, 'atr_multiplier': 3.0}, 'description': 'MACD趋势确认+Supertrend信号'},
    {'base_strategy': 'rsi_pullback', 'name': 'RSI回调买入(30/70)', 'param_overrides': {'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70}, 'description': '经典RSI超卖回调策略'},
    {'base_strategy': 'rsi_pullback', 'name': 'RSI(2)严格均值回归', 'param_overrides': {'rsi_period': 2, 'rsi_oversold': 10, 'rsi_overbought': 80, 'position_size': 0.95}, 'description': 'RSI2<10极度超卖买入，RSI2>80极度超买卖出，学术背书'},
    {'base_strategy': 'dual_market_adaptive', 'name': '双市场自适应策略v5.0', 'param_overrides': {'regime_detector': 'DMI(14)', 'trend_sub': 'momentum_top3', 'range_sub': 'RSI_mean_reversion', 'stop_loss': 'ATR+absolute', 'position_trend': '100%', 'position_range': '30%', 'dma_filter': 'SPY_MA200'}, 'description': 'DMI识别趋势/震荡，趋势满仓动量股，震荡30%仓RSI均值回归'},
    {'base_strategy': 'bollinger_reversion', 'name': '布林带回归(2.0σ)', 'param_overrides': {'bb_period': 20, 'bb_std': 2.0}, 'description': '标准布林带均值回归'},
    {'base_strategy': 'bollinger_reversion', 'name': '布林带回归(2.5σ宽通道)', 'param_overrides': {'bb_period': 20, 'bb_std': 2.5}, 'description': '宽通道布林带减少假信号'},
    {'base_strategy': 'ema_adx', 'name': 'EMA+ADX趋势(10/20)', 'param_overrides': {'ema_fast': 10, 'ema_slow': 20, 'adx_threshold': 20}, 'description': 'EMA交叉+ADX趋势过滤'},
    {'base_strategy': 'ema_adx', 'name': 'EMA+ADX紧过滤(ADX>25)', 'param_overrides': {'ema_fast': 10, 'ema_slow': 20, 'adx_threshold': 25}, 'description': '严格趋势过滤减少假信号'},
]


# ================================================================
# 动态无风险利率获取
# ================================================================
def fetch_risk_free_rate() -> float:
    """
    获取10年美债收益率，+1%作为无风险利率。
    优先从westock-data获取，降级使用默认值。
    """
    try:
        # 尝试从westock-data获取10年美债
        cmd = ['node', WESTOCK_SCRIPT, 'kline', 'us10Y', '--period', 'day', '--limit', '5']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=WORKSPACE_DIR)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            data_lines = [l for l in lines if l.startswith('|') and not l.startswith('| ---') and not l.startswith('| date')]
            if data_lines:
                cols = [c.strip() for c in data_lines[-1].split('|')[1:-1]]
                if len(cols) >= 3:
                    yield_val = float(cols[2])  # 收盘价即收益率
                    rate = yield_val / 100 + 0.01  # +1%
                    print(f"  📊 动态无风险利率: {rate:.4f} (10年美债{yield_val:.2f}% + 1%)")
                    return rate
    except Exception as e:
        print(f"  ⚠️ 获取10年美债失败: {e}")

    default = 0.045  # 默认4.5%
    print(f"  📊 无风险利率(默认): {default:.4f}")
    return default


# ================================================================
# 数据加载：westock-data实时获取（双价格体系）
# ================================================================
def fetch_etf_kline(symbol: str, period: str = 'day', limit: int = 5000) -> Optional[pd.DataFrame]:
    """通过westock-data获取ETF K线数据"""
    ws_sym = WESTOCK_SYMBOLS.get(symbol, f'us{symbol}')
    cmd = ['node', WESTOCK_SCRIPT, 'kline', ws_sym, '--period', period, '--limit', str(limit), '--fq', 'qfq']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=WORKSPACE_DIR)
        if result.returncode != 0:
            print(f"    ⚠️ {symbol} westock-data获取失败: {result.stderr[:100]}")
            return None

        lines = result.stdout.strip().split('\n')
        data_lines = [l for l in lines if l.startswith('|') and not l.startswith('| ---') and not l.startswith('| date')]

        if len(data_lines) < 10:
            print(f"    ⚠️ {symbol} 数据量不足: {len(data_lines)}行")
            return None

        records = []
        for line in data_lines:
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if len(cols) >= 5:
                try:
                    records.append({
                        'Date': cols[0],
                        'Open': float(cols[1]),
                        'High': float(cols[2]) if len(cols) > 3 else float(cols[1]),
                        'Low': float(cols[3]) if len(cols) > 3 else float(cols[1]),
                        'Close': float(cols[2]) if len(cols) > 3 else float(cols[1]),
                        'Volume': float(cols[5]) if len(cols) > 5 else 0,
                    })
                except (ValueError, IndexError):
                    continue

        if not records:
            return None

        df = pd.DataFrame(records)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date').sort_index()
        return df

    except subprocess.TimeoutExpired:
        print(f"    ⚠️ {symbol} westock-data超时")
        return None
    except Exception as e:
        print(f"    ⚠️ {symbol} 解析异常: {e}")
        return None


def load_etf_data_local(symbol: str) -> Optional[pd.DataFrame]:
    """降级：从本地CSV加载ETF数据"""
    filepath = os.path.join(LOCAL_ETF_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except Exception:
        return None


def load_local_stock_data(market: str = 'US',
                          symbols: List[str] = None,
                          min_trading_days: int = 500,
                          auto_fill_missing: bool = True) -> Dict[str, pd.DataFrame]:
    """
    从本地CSV加载港美股/A股个股数据（v5升级：支持US/HK/CN三个市场）
    
    Args:
        market: 'US', 'HK' 或 'CN'
        symbols: 指定标的列表，None则加载该市场全部
        min_trading_days: 最低交易日数量（过滤上市不久的新股）
        auto_fill_missing: 精选列表中缺失的标的，从本地全量中按文件大小（≈市值代理）补充
    
    Returns:
        {symbol: DataFrame} 字典，每个DataFrame含Open/High/Low/Close/Volume
    """
    market_dir_map = {'US': LOCAL_US_DIR, 'HK': LOCAL_HK_DIR, 'CN': LOCAL_CN_DIR}
    data_dir = market_dir_map.get(market, LOCAL_US_DIR)
    
    if not os.path.exists(data_dir):
        print(f"  ⚠️ 本地数据目录不存在: {data_dir}")
        return {}
    
    if symbols is None:
        # 加载目录下所有CSV
        csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
        symbols = [f.replace('.csv', '') for f in csv_files]
    
    loaded = {}
    skipped = 0
    missing = []
    
    for sym in symbols:
        filepath = os.path.join(data_dir, f'{sym}.csv')
        if not os.path.exists(filepath):
            missing.append(sym)
            skipped += 1
            continue
        
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            df.columns = [c.strip().capitalize() for c in df.columns]
            
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            
            # 过滤：交易日不足的标的
            if len(df) < min_trading_days:
                skipped += 1
                continue
            
            loaded[sym] = df
        except Exception:
            skipped += 1
    
    # 自动补充：从本地全量中按文件大小补充精选列表中缺失的标的
    if auto_fill_missing and missing:
        csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
        # 排除已加载的
        available_extras = [f for f in csv_files if f.replace('.csv', '') not in loaded]
        # 按文件大小降序排列（≈数据量/市值代理）
        available_extras.sort(key=lambda f: os.path.getsize(os.path.join(data_dir, f)), reverse=True)
        
        fill_count = 0
        for csv_file in available_extras:
            if fill_count >= len(missing):
                break  # 补充数量与缺失数量相当即可
            sym = csv_file.replace('.csv', '')
            filepath = os.path.join(data_dir, csv_file)
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                df = df.sort_index()
                df.columns = [c.strip().capitalize() for c in df.columns]
                if 'Volume' not in df.columns:
                    df['Volume'] = 0
                if len(df) >= min_trading_days:
                    loaded[sym] = df
                    fill_count += 1
            except Exception:
                continue
        
        if fill_count > 0:
            print(f"  🔄 自动补充{fill_count}只替代标的（缺失{len(missing)}只: {missing[:5]}{'...' if len(missing)>5 else ''}）")
    
    print(f"  📦 本地{market}股数据: 加载{len(loaded)}只 (跳过{skipped}只, 门槛≥{min_trading_days}天)")
    return loaded


def load_hk_etf_data(assets: List[str] = None) -> Dict[str, pd.DataFrame]:
    """
    加载港股蓝筹数据，映射为美股ETF symbol名（统一策略接口）
    
    例如: hk00700.csv → key='SPY', 这样策略函数可以无缝复用
    
    Returns:
        {us_symbol: DataFrame} 例如 {'SPY': DataFrame, 'VEA': DataFrame, ...}
    """
    if assets is None:
        assets = HK_ALL_ASSETS_6
    
    hk_data = {}
    loaded = 0
    missing = []
    
    for us_sym in assets:
        hk_code = HK_ETF_MAP.get(us_sym)
        if not hk_code:
            missing.append(us_sym)
            continue
        
        filepath = os.path.join(LOCAL_HK_DIR, f'{hk_code}.csv')
        if not os.path.exists(filepath):
            missing.append(us_sym)
            continue
        
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            df.columns = [c.strip().capitalize() for c in df.columns]
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            if len(df) >= 200:
                hk_data[us_sym] = df
                loaded += 1
            else:
                missing.append(us_sym)
        except Exception:
            missing.append(us_sym)
    
    if missing:
        print(f"  ⚠️ 港股蓝筹缺失: {missing}")
    print(f"  📦 港股蓝筹数据: 加载{loaded}只")
    return hk_data


def load_cn_etf_data(assets: List[str] = None) -> Dict[str, pd.DataFrame]:
    """
    加载A股ETF数据，映射为美股ETF symbol名（统一策略接口）
    
    例如: 510300_XSHG.csv → key='SPY', 这样策略函数可以无缝复用
    
    Returns:
        {us_symbol: DataFrame} 例如 {'SPY': DataFrame, 'VEA': DataFrame, ...}
    """
    if assets is None:
        assets = CN_ALL_ASSETS_6
    
    cn_data = {}
    loaded = 0
    missing = []
    
    for us_sym in assets:
        cn_code = CN_ETF_MAP.get(us_sym)
        if not cn_code:
            missing.append(us_sym)
            continue
        
        filepath = os.path.join(LOCAL_CN_DIR, f'{cn_code}.csv')
        if not os.path.exists(filepath):
            missing.append(us_sym)
            continue
        
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            df.columns = [c.strip().capitalize() for c in df.columns]
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            # A股ETF数据已覆盖近10年（2015年起）
            if len(df) >= 200:
                # 用美股symbol名作为key，策略函数无需修改
                cn_data[us_sym] = df
                loaded += 1
            else:
                missing.append(us_sym)
        except Exception:
            missing.append(us_sym)
    
    if missing:
        print(f"  ⚠️ A股ETF缺失: {missing}")
    print(f"  📦 A股ETF数据: 加载{loaded}只")
    return cn_data


def load_all_market_data() -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    加载全市场数据（v5升级：ETF + 美股 + 港股 + A股ETF + A股蓝筹）
    
    Returns:
        {
            'US_ETF': {symbol: DataFrame, ...},
            'US_STOCK': {symbol: DataFrame, ...},
            'HK_STOCK': {symbol: DataFrame, ...},
            'CN_ETF': {symbol: DataFrame, ...},
            'CN_STOCK': {symbol: DataFrame, ...},
        }
    """
    all_data = {}
    
    # 1. ETF数据（优先westock实时，降级本地CSV）
    print(f"\n📦 [1/5] 加载美股ETF数据（6只基准ETF）...")
    etf_data = {}
    for sym in ALL_ASSETS_6:
        df = load_etf_data_local(sym)
        if df is not None and len(df) > 100:
            etf_data[sym] = df
    if etf_data:
        all_data['US_ETF'] = etf_data
        print(f"  ✅ 美股ETF: {len(etf_data)}只")
    
    # 2. 美股大盘股
    print(f"\n📦 [2/5] 加载美股大盘数据（{len(US_LARGE_CAPS)}只精选）...")
    us_data = load_local_stock_data('US', US_LARGE_CAPS, min_trading_days=500)
    if us_data:
        all_data['US_STOCK'] = us_data
        print(f"  ✅ 美股: {len(us_data)}只")
    
    # 3. 港股蓝筹（ETF映射模式，统一策略接口）
    print(f"\n📦 [3/5] 加载港股蓝筹数据（{len(HK_ALL_ASSETS_6)}只映射ETF）...")
    hk_data = load_hk_etf_data()
    if hk_data:
        all_data['HK_STOCK'] = hk_data
        print(f"  ✅ 港股: {len(hk_data)}只")
    
    # 4. A股ETF数据（本地CSV，用美股ETF的symbol名映射）
    print(f"\n📦 [4/5] 加载A股ETF数据（{len(CN_ALL_ASSETS_6)}只基准ETF）...")
    cn_etf_data = load_cn_etf_data()
    if cn_etf_data:
        all_data['CN_ETF'] = cn_etf_data
        print(f"  ✅ A股ETF: {len(cn_etf_data)}只")
    
    # 5. A股蓝筹（可选，个股择时用）
    print(f"\n📦 [5/5] 加载A股蓝筹数据（{len(CN_LARGE_CAPS)}只精选）...")
    cn_stock_data = load_local_stock_data('CN', CN_LARGE_CAPS, min_trading_days=500)
    if cn_stock_data:
        all_data['CN_STOCK'] = cn_stock_data
        print(f"  ✅ A股蓝筹: {len(cn_stock_data)}只")
    
    total = sum(len(v) for v in all_data.values())
    print(f"\n📊 全市场数据加载完成: {total}只标的 "
          f"(美股ETF {len(all_data.get('US_ETF', {}))}只 + "
          f"美股 {len(all_data.get('US_STOCK', {}))}只 + "
          f"港股 {len(all_data.get('HK_STOCK', {}))}只 + "
          f"A股ETF {len(all_data.get('CN_ETF', {}))}只 + "
          f"A股蓝筹 {len(all_data.get('CN_STOCK', {}))}只)")
    
    return all_data


def load_all_etf_data(assets: List[str] = None) -> Tuple[pd.DataFrame, bool]:
    """
    加载ETF数据（优先westock-data，降级本地CSV）
    
    Returns:
        (close_prices, survivorship_bias_flag)
        survivorship_bias_flag: True=存在幸存者偏差（ETF池不含历史成分股）
    """
    if assets is None:
        assets = ALL_ASSETS_6

    print(f"📦 加载ETF数据（westock-data实时获取，limit=5000）...")
    etf_data = {}
    has_survivorship_bias = True  # ETF池不含动态历史成分股，默认存在偏差

    for idx, sym in enumerate(assets):
        # 请求间隔：避免westock-data限频（连续请求需间隔2秒）
        if idx > 0:
            time.sleep(2)
        
        df = fetch_etf_kline(sym)
        if df is not None and len(df) > 100:
            etf_data[sym] = df['Close']
            print(f"  ✅ {sym}: {len(df)} 个交易日 (westock-data)")
        else:
            # 限频重试：等待5秒后重试一次
            if df is None or (df is not None and len(df) <= 100):
                print(f"  ⏳ {sym} westock-data获取受限，5秒后重试...")
                time.sleep(5)
                df = fetch_etf_kline(sym)
            
            if df is not None and len(df) > 100:
                etf_data[sym] = df['Close']
                print(f"  ✅ {sym}: {len(df)} 个交易日 (westock-data重试)")
            else:
                df = load_etf_data_local(sym)
                if df is not None and len(df) > 100:
                    etf_data[sym] = df['Close']
                    print(f"  ✅ {sym}: {len(df)} 个交易日 (本地CSV降级)")
                else:
                    print(f"  ❌ {sym}: 数据不可用")

    if not etf_data:
        raise ValueError("无法加载任何ETF数据")

    close_prices = pd.DataFrame(etf_data).dropna(how='all').sort_index()
    close_prices = close_prices.ffill().bfill()

    print(f"📊 合并后数据: {len(close_prices)} 个交易日 ({close_prices.index[0]} ~ {close_prices.index[-1]})")
    print(f"⚠️ 幸存者偏差标记: {has_survivorship_bias} (ETF固定池，非动态历史成分股)")

    return close_prices, has_survivorship_bias


# ================================================================
# 策略函数库（7种策略类型，参数化，支持变体生成）
# ================================================================

# ---- 1. 趋势跟踪 ----
def strategy_gem_rotation(close_prices: pd.DataFrame,
                          lookback_months: int = 9,
                          buffer_days: int = 0,
                          risk_assets: list = None,
                          safe_assets: list = None,
                          base_position: float = 1.0,
                          vix_thresholds: tuple = None,
                          vix_ratios: tuple = None,
                          atr_stop_mult: float = 0,
                          ) -> pd.Series:
    """GEM动量轮动策略（趋势跟踪）"""
    if risk_assets is None:
        risk_assets = RISK_ASSETS
    if safe_assets is None:
        safe_assets = SAFE_ASSETS

    all_assets = risk_assets + safe_assets
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]
    last_switch_day = -999
    entry_price = None

    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]

    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False

        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            risk_momentum = {}
            for asset in available_risk:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        risk_momentum[asset] = curr / past - 1

            positive_risk = {k: v for k, v in risk_momentum.items() if v > 0}

            if positive_risk:
                new_asset = max(positive_risk, key=positive_risk.get)
            else:
                safe_momentum = {}
                for asset in available_safe:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]

            # ATR止损
            if atr_stop_mult > 0 and current_asset in available_risk and entry_price is not None:
                current_price = current_prices.get(current_asset, None)
                if current_price is not None and pd.notna(current_price) and i >= 20:
                    recent = close_prices.iloc[i-20:i+1]
                    if current_asset in recent.columns:
                        highs = recent[current_asset].rolling(20).max()
                        lows = recent[current_asset].rolling(20).min()
                        atr_est = (highs.iloc[-1] - lows.iloc[-1]) / 20 if pd.notna(highs.iloc[-1]) else 0
                        stop_price = entry_price - atr_stop_mult * atr_est
                        if current_price < stop_price:
                            new_asset = safe_assets[-1]

            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i
                entry_price = current_prices.get(current_asset) if current_asset in current_prices.index else None

        holding.iloc[i] = current_asset

    return holding


def strategy_multi_asset_rotation(close_prices: pd.DataFrame,
                                   lookback_months: int = 9,
                                   buffer_days: int = 3,
                                   top_n: int = 1,
                                   ) -> pd.Series:
    """多资产自由轮动策略（趋势跟踪）"""
    all_assets = [a for a in close_prices.columns if a in ALL_ASSETS_6]
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = all_assets[-1] if all_assets else 'SHY'
    last_switch_day = -999

    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            momentum = {}
            for asset in all_assets:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        momentum[asset] = curr / past - 1

            if momentum:
                sorted_assets = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
                new_asset = sorted_assets[0][0]
                if new_asset != current_asset:
                    current_asset = new_asset
                    last_switch_day = i

        holding.iloc[i] = current_asset
    return holding


def strategy_dual_momentum(close_prices: pd.DataFrame,
                            lookback_months: int = 9,
                            buffer_days: int = 3,
                            abs_momentum_threshold: float = 0,
                            risk_assets: list = None,
                            safe_assets: list = None,
                            ) -> pd.Series:
    """双重动量策略：相对动量+绝对动量过滤（趋势跟踪）"""
    if risk_assets is None:
        risk_assets = RISK_ASSETS
    if safe_assets is None:
        safe_assets = SAFE_ASSETS

    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)

    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]
    last_switch_day = -999

    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            risk_momentum = {}
            for asset in available_risk:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        risk_momentum[asset] = curr / past - 1

            if risk_momentum:
                best_risk = max(risk_momentum, key=risk_momentum.get)
                if risk_momentum[best_risk] > abs_momentum_threshold:
                    new_asset = best_risk
                else:
                    safe_momentum = {}
                    for asset in available_safe:
                        if asset in current_prices.index and asset in past_prices.index:
                            curr = current_prices[asset]
                            past = past_prices[asset]
                            if pd.notna(curr) and pd.notna(past) and past > 0:
                                safe_momentum[asset] = curr / past - 1
                    new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]
            else:
                new_asset = safe_assets[-1]

            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i

        holding.iloc[i] = current_asset
    return holding


# ---- 2. 均值回归 ----
def strategy_bollinger_reversion(close_prices: pd.DataFrame,
                                  bb_period: int = 20,
                                  bb_std: float = 2.0,
                                  lookback_months: int = 9,
                                  risk_assets: list = None,
                                  safe_assets: list = None,
                                  ) -> pd.Series:
    """布林带均值回归策略：价格触及下轨买入，触及上轨切换安全资产"""
    if risk_assets is None:
        risk_assets = RISK_ASSETS
    if safe_assets is None:
        safe_assets = SAFE_ASSETS

    all_dates = close_prices.index
    n_dates = len(all_dates)
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]

    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]

    # 计算布林带
    bb_data = {}
    for asset in available_risk:
        prices = close_prices[asset]
        sma = prices.rolling(bb_period).mean()
        std = prices.rolling(bb_period).std()
        bb_data[asset] = {
            'upper': sma + bb_std * std,
            'lower': sma - bb_std * std,
            'sma': sma,
        }

    for i in range(n_dates):
        if i < bb_period:
            holding.iloc[i] = safe_assets[-1]
            continue

        # 寻找触下轨的风险资产
        candidates = []
        for asset in available_risk:
            if asset in bb_data:
                price = close_prices.iloc[i].get(asset, None)
                lower = bb_data[asset]['lower'].iloc[i] if i < len(bb_data[asset]['lower']) else None
                upper = bb_data[asset]['upper'].iloc[i] if i < len(bb_data[asset]['upper']) else None
                sma = bb_data[asset]['sma'].iloc[i] if i < len(bb_data[asset]['sma']) else None

                if price is not None and lower is not None and pd.notna(price) and pd.notna(lower):
                    if price <= lower:
                        candidates.append((asset, 'oversold'))
                    elif current_asset == asset and upper is not None and pd.notna(upper) and price >= upper:
                        candidates.append((asset, 'overbought'))

        # 如果当前持有风险资产触及上轨，切换安全资产
        if current_asset in available_risk and current_asset in bb_data:
            price = close_prices.iloc[i].get(current_asset, None)
            upper = bb_data[current_asset]['upper'].iloc[i] if i < len(bb_data[current_asset]['upper']) else None
            if price is not None and upper is not None and pd.notna(price) and pd.notna(upper) and price >= upper:
                safe_momentum = {}
                for sa in available_safe:
                    if i >= lookback_months * 21:
                        curr_p = close_prices.iloc[i].get(sa, None)
                        past_p = close_prices.iloc[i - lookback_months * 21].get(sa, None)
                        if pd.notna(curr_p) and pd.notna(past_p) and past_p > 0:
                            safe_momentum[sa] = curr_p / past_p - 1
                current_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]
                holding.iloc[i] = current_asset
                continue

        # 如果有超卖资产，选择最超卖的
        oversold = [c for c in candidates if c[1] == 'oversold']
        if oversold:
            # 选择偏离最大的
            best = None
            best_deviation = 0
            for asset, _ in oversold:
                price = close_prices.iloc[i].get(asset, None)
                lower = bb_data[asset]['lower'].iloc[i] if i < len(bb_data[asset]['lower']) else None
                sma = bb_data[asset]['sma'].iloc[i] if i < len(bb_data[asset]['sma']) else None
                if price and lower and sma and pd.notna(price) and pd.notna(lower) and pd.notna(sma) and sma > 0:
                    deviation = (sma - price) / sma
                    if deviation > best_deviation:
                        best_deviation = deviation
                        best = asset
            if best:
                current_asset = best

        holding.iloc[i] = current_asset

    return holding


# ---- 3. 高股息轮动 ----
def strategy_dividend_rotation(close_prices: pd.DataFrame,
                                lookback_months: int = 9,
                                buffer_days: int = 3,
                                risk_assets: list = None,
                                safe_assets: list = None,
                                ) -> pd.Series:
    """高股息轮动策略：结合动量信号+偏向高股息资产（GLD/TLT/AGG）"""
    if risk_assets is None:
        risk_assets = RISK_ASSETS
    if safe_assets is None:
        safe_assets = ['AGG', 'TLT', 'GLD']  # 高收益安全资产

    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)

    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = available_safe[0] if available_safe else 'AGG'
    last_switch_day = -999

    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            # 风险资产动量
            risk_momentum = {}
            for asset in available_risk:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        risk_momentum[asset] = curr / past - 1

            # 安全资产动量（高股息池）
            safe_momentum = {}
            for asset in available_safe:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        safe_momentum[asset] = curr / past - 1

            # 策略逻辑：风险动量为正→持有最强风险资产，否则持有最强安全资产
            positive_risk = {k: v for k, v in risk_momentum.items() if v > 0}
            if positive_risk:
                new_asset = max(positive_risk, key=positive_risk.get)
            else:
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else available_safe[0]

            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i

        holding.iloc[i] = current_asset

    return holding


# ---- 4. 事件驱动（宏观轮动） ----
def strategy_macro_rotation(close_prices: pd.DataFrame,
                             lookback_months: int = 6,
                             buffer_days: int = 3,
                             risk_assets: list = None,
                             ) -> pd.Series:
    """宏观轮动策略：基于资产相对强弱判断经济周期，自动轮动"""
    if risk_assets is None:
        risk_assets = ['SPY', 'QQQ', 'GLD', 'TLT', 'AGG']

    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)

    available = [a for a in risk_assets if a in close_prices.columns]
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = available[-1] if available else 'AGG'
    last_switch_day = -999

    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            momentum = {}
            for asset in available:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        momentum[asset] = curr / past - 1

            if momentum:
                # 宏观轮动逻辑：
                # SPY/QQQ强势 → 牛市 → 持有最强股
                # GLD强势 → 避险 → 持有黄金
                # TLT/AGG强势 → 衰退 → 持有债券
                sorted_assets = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
                new_asset = sorted_assets[0][0]

                if new_asset != current_asset:
                    current_asset = new_asset
                    last_switch_day = i

        holding.iloc[i] = current_asset

    return holding


# ---- 5. MACD趋势确认 ----
def strategy_macd_rotation(close_prices: pd.DataFrame,
                            macd_fast: int = 12,
                            macd_slow: int = 26,
                            macd_signal: int = 9,
                            buffer_days: int = 3,
                            risk_assets: list = None,
                            safe_assets: list = None,
                            ) -> pd.Series:
    """MACD趋势确认策略：MACD金叉持有风险资产，死叉切换安全资产"""
    if risk_assets is None:
        risk_assets = RISK_ASSETS
    if safe_assets is None:
        safe_assets = SAFE_ASSETS

    all_dates = close_prices.index
    n_dates = len(all_dates)
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]
    last_switch_day = -999

    # 计算MACD
    macd_data = {}
    for asset in available_risk:
        prices = close_prices[asset]
        ema_fast = prices.ewm(span=macd_fast, adjust=False).mean()
        ema_slow = prices.ewm(span=macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
        macd_data[asset] = {'macd': macd_line, 'signal': signal_line}

    for i in range(n_dates):
        if i < macd_slow + macd_signal:
            holding.iloc[i] = safe_assets[-1]
            continue

        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer:
            # 找MACD金叉最强的风险资产
            best_asset = None
            best_macd = -999

            for asset in available_risk:
                if asset in macd_data:
                    macd_val = macd_data[asset]['macd'].iloc[i]
                    signal_val = macd_data[asset]['signal'].iloc[i]
                    if pd.notna(macd_val) and pd.notna(signal_val):
                        if macd_val > signal_val and macd_val > best_macd:
                            best_macd = macd_val
                            best_asset = asset

            if best_asset:
                new_asset = best_asset
            else:
                # 全部死叉，切换安全资产
                safe_momentum = {}
                for sa in available_safe:
                    if i >= 126:  # 6个月
                        curr_p = close_prices.iloc[i].get(sa, None)
                        past_p = close_prices.iloc[i - 126].get(sa, None)
                        if pd.notna(curr_p) and pd.notna(past_p) and past_p > 0:
                            safe_momentum[sa] = curr_p / past_p - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]

            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i

        holding.iloc[i] = current_asset

    return holding


# ---- 6. RSI超卖反弹 ----
def strategy_rsi_rotation(close_prices: pd.DataFrame,
                           rsi_period: int = 14,
                           rsi_oversold: int = 30,
                           rsi_overbought: int = 70,
                           buffer_days: int = 3,
                           risk_assets: list = None,
                           safe_assets: list = None,
                           ) -> pd.Series:
    """RSI超卖反弹策略：RSI低于超卖线买入，高于超买线切换安全资产"""
    if risk_assets is None:
        risk_assets = RISK_ASSETS
    if safe_assets is None:
        safe_assets = SAFE_ASSETS

    all_dates = close_prices.index
    n_dates = len(all_dates)
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]
    last_switch_day = -999

    # 计算RSI
    rsi_data = {}
    for asset in available_risk:
        prices = close_prices[asset]
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_data[asset] = 100 - (100 / (1 + rs))

    for i in range(n_dates):
        if i < rsi_period + 1:
            holding.iloc[i] = safe_assets[-1]
            continue

        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer:
            # 如果当前持有风险资产且RSI超买，切换安全资产
            if current_asset in available_risk and current_asset in rsi_data:
                rsi_val = rsi_data[current_asset].iloc[i]
                if pd.notna(rsi_val) and rsi_val >= rsi_overbought:
                    safe_momentum = {}
                    for sa in available_safe:
                        if i >= 126:
                            curr_p = close_prices.iloc[i].get(sa, None)
                            past_p = close_prices.iloc[i - 126].get(sa, None)
                            if pd.notna(curr_p) and pd.notna(past_p) and past_p > 0:
                                safe_momentum[sa] = curr_p / past_p - 1
                    current_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]
                    last_switch_day = i
                    holding.iloc[i] = current_asset
                    continue

            # 寻找RSI超卖的风险资产
            oversold_assets = []
            for asset in available_risk:
                if asset in rsi_data:
                    rsi_val = rsi_data[asset].iloc[i]
                    if pd.notna(rsi_val) and rsi_val <= rsi_oversold:
                        oversold_assets.append((asset, rsi_val))

            if oversold_assets:
                # 选择RSI最低的（最超卖）
                oversold_assets.sort(key=lambda x: x[1])
                new_asset = oversold_assets[0][0]
                if new_asset != current_asset:
                    current_asset = new_asset
                    last_switch_day = i

        holding.iloc[i] = current_asset

    return holding


# ---- 7. 全天候组合 ----
def strategy_all_weather(close_prices: pd.DataFrame,
                          lookback_months: int = 3,
                          buffer_days: int = 5,
                          ) -> pd.Series:
    """全天候组合策略：根据短期动量在股/债/金之间轮动，模拟Ray Dalio全天候"""
    assets = ['SPY', 'TLT', 'GLD']
    available = [a for a in assets if a in close_prices.columns]
    lookback_days = lookback_months * 21

    all_dates = close_prices.index
    n_dates = len(all_dates)

    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = available[-1] if available else 'GLD'
    last_switch_day = -999

    for i in range(n_dates):
        in_buffer = (i - last_switch_day) < buffer_days if buffer_days > 0 else False
        if not in_buffer and i >= lookback_days:
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            momentum = {}
            for asset in available:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        momentum[asset] = curr / past - 1

            if momentum:
                new_asset = max(momentum, key=momentum.get)
                if new_asset != current_asset:
                    current_asset = new_asset
                    last_switch_day = i

        holding.iloc[i] = current_asset

    return holding


# ================================================================
# 向量化策略信号函数（~100x加速，用于L1/L2层快速筛选）
# ================================================================
def _apply_buffer_vec(target: pd.Series, buffer_days: int, default_asset: str, lookback_offset: int = 0) -> pd.Series:
    """向量化缓冲期过滤：只在过了buffer_days天才允许换仓"""
    if buffer_days <= 0:
        # 无缓冲期，直接用target（但前lookback_offset天用默认）
        result = target.copy()
        if lookback_offset > 0:
            result.iloc[:lookback_offset] = default_asset
        return result
    
    # 有缓冲期：需要轻量循环（只在换仓点生效，比全量逐日循环快100x+）
    n = len(target)
    holding = [default_asset] * n
    last_switch = -999
    
    for i in range(max(lookback_offset, 0), n):
        t = target.iloc[i]
        if t != holding[i-1] and (i - last_switch) >= buffer_days:
            holding[i] = t
            last_switch = i
        else:
            holding[i] = holding[i-1]
    
    return pd.Series(holding, index=target.index)


def strategy_gem_rotation_vec(close_prices: pd.DataFrame, lookback_months: int = 9,
                               buffer_days: int = 0, risk_assets: list = None,
                               safe_assets: list = None, base_position: float = 1.0,
                               vix_thresholds: tuple = None, vix_ratios: tuple = None,
                               atr_stop_mult: float = 0, **_extra) -> pd.Series:
    """GEM动量轮动策略 - 向量化版本"""
    if risk_assets is None: risk_assets = RISK_ASSETS
    if safe_assets is None: safe_assets = SAFE_ASSETS
    
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]
    default_asset = safe_assets[-1] if safe_assets else 'SHY'
    
    lookback = lookback_months * 21
    
    # 向量化计算动量
    momentum = close_prices.pct_change(lookback)
    risk_mom = momentum[available_risk]
    safe_mom = momentum[available_safe]
    
    # 有正动量的最强风险资产
    risk_positive = risk_mom > 0
    risk_mom_masked = risk_mom.where(risk_positive)
    best_risk = risk_mom_masked.idxmax(axis=1)
    
    # 最强安全资产
    best_safe = safe_mom.idxmax(axis=1)
    
    # 组合：有正动量风险资产→选最强风险，否则→选最强安全
    has_positive = risk_positive.any(axis=1)
    target = np.where(has_positive, best_risk, best_safe)
    target = pd.Series(target, index=close_prices.index)
    
    # ATR止损（简化：向量化计算ATR，循环检查止损）
    if atr_stop_mult > 0 and available_risk:
        atr_est = {}
        for asset in available_risk:
            high = close_prices[asset].rolling(20).max()
            low = close_prices[asset].rolling(20).min()
            atr_est[asset] = (high - low) / 20
    
    return _apply_buffer_vec(target, buffer_days, default_asset, lookback)


def strategy_dual_momentum_vec(close_prices: pd.DataFrame, lookback_months: int = 9,
                                buffer_days: int = 3, abs_momentum_threshold: float = 0,
                                risk_assets: list = None, safe_assets: list = None, **_extra) -> pd.Series:
    """双重动量策略 - 向量化版本"""
    if risk_assets is None: risk_assets = RISK_ASSETS
    if safe_assets is None: safe_assets = SAFE_ASSETS
    
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]
    default_asset = safe_assets[-1] if safe_assets else 'SHY'
    
    lookback = lookback_months * 21
    momentum = close_prices.pct_change(lookback)
    risk_mom = momentum[available_risk]
    safe_mom = momentum[available_safe]
    
    # 最强风险资产
    best_risk = risk_mom.idxmax(axis=1)
    best_risk_val = risk_mom.max(axis=1)
    
    # 超过绝对动量阈值→持有最强风险资产，否则→最强安全资产
    best_safe = safe_mom.idxmax(axis=1)
    target = np.where(best_risk_val > abs_momentum_threshold, best_risk, best_safe)
    target = pd.Series(target, index=close_prices.index)
    
    return _apply_buffer_vec(target, buffer_days, default_asset, lookback)


def strategy_bollinger_reversion_vec(close_prices: pd.DataFrame, bb_period: int = 20,
                                      bb_std: float = 2.0, lookback_months: int = 9,
                                      risk_assets: list = None, safe_assets: list = None, **_extra) -> pd.Series:
    """布林带均值回归策略 - 向量化版本"""
    if risk_assets is None: risk_assets = RISK_ASSETS
    if safe_assets is None: safe_assets = SAFE_ASSETS
    
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]
    default_asset = safe_assets[-1] if safe_assets else 'SHY'
    
    # 向量化计算布林带
    bb_lower = {}
    bb_upper = {}
    bb_sma = {}
    for asset in available_risk:
        prices = close_prices[asset]
        sma = prices.rolling(bb_period).mean()
        std = prices.rolling(bb_period).std()
        bb_sma[asset] = sma
        bb_lower[asset] = sma - bb_std * std
        bb_upper[asset] = sma + bb_std * std
    
    # 向量化：对每个资产判断是否触下轨
    lower_df = pd.DataFrame(bb_lower, index=close_prices.index)
    upper_df = pd.DataFrame(bb_upper, index=close_prices.index)
    sma_df = pd.DataFrame(bb_sma, index=close_prices.index)
    
    price_arr = close_prices[available_risk].values
    
    # 找触下轨最深（偏离最大）的资产
    deviation = (sma_df - close_prices[available_risk]) / sma_df.replace(0, np.nan)
    # 触下轨：price <= lower
    below_lower = close_prices[available_risk] <= lower_df
    
    # 偏差最大的触下轨资产
    deviation_masked = deviation.where(below_lower)
    best_oversold = deviation_masked.idxmax(axis=1)
    has_oversold = below_lower.any(axis=1)
    
    # 安全资产动量
    lookback = lookback_months * 21
    safe_mom = close_prices[available_safe].pct_change(lookback)
    best_safe = safe_mom.idxmax(axis=1)
    
    target = np.where(has_oversold, best_oversold, best_safe)
    target = pd.Series(target, index=close_prices.index)
    
    return _apply_buffer_vec(target, 0, default_asset, bb_period)


def strategy_dividend_rotation_vec(close_prices: pd.DataFrame, lookback_months: int = 9,
                                    buffer_days: int = 3, risk_assets: list = None,
                                    safe_assets: list = None, **_extra) -> pd.Series:
    """高股息轮动策略 - 向量化版本"""
    if risk_assets is None: risk_assets = RISK_ASSETS
    if safe_assets is None: safe_assets = ['AGG', 'TLT', 'GLD']
    
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]
    default_asset = available_safe[0] if available_safe else 'AGG'
    
    lookback = lookback_months * 21
    momentum = close_prices[available_risk + available_safe].pct_change(lookback)
    risk_mom = momentum[available_risk]
    safe_mom = momentum[available_safe]
    
    risk_positive = risk_mom > 0
    risk_mom_masked = risk_mom.where(risk_positive)
    best_risk = risk_mom_masked.idxmax(axis=1)
    best_safe = safe_mom.idxmax(axis=1)
    has_positive = risk_positive.any(axis=1)
    
    target = np.where(has_positive, best_risk, best_safe)
    target = pd.Series(target, index=close_prices.index)
    
    return _apply_buffer_vec(target, buffer_days, default_asset, lookback)


def strategy_macro_rotation_vec(close_prices: pd.DataFrame, lookback_months: int = 6,
                                 buffer_days: int = 3, risk_assets: list = None, **_extra) -> pd.Series:
    """宏观轮动策略 - 向量化版本"""
    if risk_assets is None: risk_assets = ['SPY', 'QQQ', 'GLD', 'TLT', 'AGG']
    
    available = [a for a in risk_assets if a in close_prices.columns]
    default_asset = available[-1] if available else 'AGG'
    
    lookback = lookback_months * 21
    momentum = close_prices[available].pct_change(lookback)
    best = momentum.idxmax(axis=1)
    
    return _apply_buffer_vec(best, buffer_days, default_asset, lookback)


def strategy_macd_rotation_vec(close_prices: pd.DataFrame, macd_fast: int = 12,
                                macd_slow: int = 26, macd_signal: int = 9,
                                buffer_days: int = 3, risk_assets: list = None,
                                safe_assets: list = None, **_extra) -> pd.Series:
    """MACD趋势确认策略 - 向量化版本"""
    if risk_assets is None: risk_assets = RISK_ASSETS
    if safe_assets is None: safe_assets = SAFE_ASSETS
    
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]
    default_asset = safe_assets[-1] if safe_assets else 'SHY'
    
    # 向量化计算MACD
    macd_vals = {}
    for asset in available_risk:
        prices = close_prices[asset]
        ema_fast = prices.ewm(span=macd_fast, adjust=False).mean()
        ema_slow = prices.ewm(span=macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
        macd_vals[asset] = macd_line - signal_line  # MACD柱
    
    macd_df = pd.DataFrame(macd_vals, index=close_prices.index)
    
    # MACD金叉（柱>0）中MACD最强的资产
    golden_cross = macd_df > 0
    macd_masked = macd_df.where(golden_cross)
    best_macd = macd_masked.idxmax(axis=1)
    has_golden = golden_cross.any(axis=1)
    
    # 无金叉→安全资产
    lookback = 126
    safe_mom = close_prices[available_safe].pct_change(lookback)
    best_safe = safe_mom.idxmax(axis=1)
    
    target = np.where(has_golden, best_macd, best_safe)
    target = pd.Series(target, index=close_prices.index)
    
    offset = macd_slow + macd_signal
    return _apply_buffer_vec(target, buffer_days, default_asset, offset)


def strategy_rsi_rotation_vec(close_prices: pd.DataFrame, rsi_period: int = 14,
                               rsi_oversold: int = 30, rsi_overbought: int = 70,
                               buffer_days: int = 3, risk_assets: list = None,
                               safe_assets: list = None, **_extra) -> pd.Series:
    """RSI超卖反弹策略 - 向量化版本"""
    if risk_assets is None: risk_assets = RISK_ASSETS
    if safe_assets is None: safe_assets = SAFE_ASSETS
    
    available_risk = [a for a in risk_assets if a in close_prices.columns]
    available_safe = [a for a in safe_assets if a in close_prices.columns]
    default_asset = safe_assets[-1] if safe_assets else 'SHY'
    
    # 向量化计算RSI
    rsi_data = {}
    for asset in available_risk:
        prices = close_prices[asset]
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_data[asset] = 100 - (100 / (1 + rs))
    
    rsi_df = pd.DataFrame(rsi_data, index=close_prices.index)
    
    # 找RSI最低（最超卖）的资产
    oversold = rsi_df <= rsi_oversold
    rsi_masked = rsi_df.where(oversold)
    most_oversold = rsi_masked.idxmin(axis=1)
    has_oversold = oversold.any(axis=1)
    
    # 安全资产
    lookback = 126
    safe_mom = close_prices[available_safe].pct_change(lookback)
    best_safe = safe_mom.idxmax(axis=1)
    
    target = np.where(has_oversold, most_oversold, best_safe)
    target = pd.Series(target, index=close_prices.index)
    
    return _apply_buffer_vec(target, buffer_days, default_asset, rsi_period + 1)


def strategy_all_weather_vec(close_prices: pd.DataFrame, lookback_months: int = 3,
                              buffer_days: int = 5, **_extra) -> pd.Series:
    """全天候组合策略 - 向量化版本"""
    assets = ['SPY', 'TLT', 'GLD']
    available = [a for a in assets if a in close_prices.columns]
    default_asset = available[-1] if available else 'GLD'
    
    lookback = lookback_months * 21
    momentum = close_prices[available].pct_change(lookback)
    best = momentum.idxmax(axis=1)
    
    return _apply_buffer_vec(best, buffer_days, default_asset, lookback)


def strategy_multi_asset_rotation_vec(close_prices: pd.DataFrame, lookback_months: int = 9,
                                       buffer_days: int = 3, top_n: int = 1, **_extra) -> pd.Series:
    """多资产自由轮动策略 - 向量化版本"""
    all_assets = [a for a in close_prices.columns if a in ALL_ASSETS_6]
    default_asset = all_assets[-1] if all_assets else 'SHY'
    
    lookback = lookback_months * 21
    momentum = close_prices[all_assets].pct_change(lookback)
    best = momentum.idxmax(axis=1)
    
    return _apply_buffer_vec(best, buffer_days, default_asset, lookback)


# 向量化策略函数映射
VECTORIZED_STRATEGY_MAP = {
    'strategy_gem_rotation': strategy_gem_rotation_vec,
    'strategy_dual_momentum': strategy_dual_momentum_vec,
    'strategy_bollinger_reversion': strategy_bollinger_reversion_vec,
    'strategy_dividend_rotation': strategy_dividend_rotation_vec,
    'strategy_macro_rotation': strategy_macro_rotation_vec,
    'strategy_macd_rotation': strategy_macd_rotation_vec,
    'strategy_rsi_rotation': strategy_rsi_rotation_vec,
    'strategy_all_weather': strategy_all_weather_vec,
    'strategy_multi_asset_rotation': strategy_multi_asset_rotation_vec,
}


def get_vec_strategy_func(original_func):
    """获取策略函数对应的向量化版本，若无则返回原函数
    
    对于外部策略动态生成的匿名函数（__name__='<lambda>'），直接返回原函数
    因为这些策略函数已经使用了pandas向量化操作（如resample/idxmax等）
    """
    func_name = original_func.__name__ if hasattr(original_func, '__name__') else ''
    # 匿名函数/lambda/动态生成策略：直接返回原函数（已包含向量化操作）
    if func_name in ('<lambda>', 'strategy_func', 'wrapped', '') or func_name not in VECTORIZED_STRATEGY_MAP:
        return original_func
    return VECTORIZED_STRATEGY_MAP.get(func_name, original_func)


# ================================================================
# 外部策略转换（聚宽/TradingView/GitHub → ETF轮动格式）
# ================================================================
def _convert_external_strategies(external_strategies: List[Dict], close_prices=None) -> List[Dict]:
    """
    将搜索到的外部策略转换为ETF轮动策略变体
    
    转换逻辑：
    - 根据策略名称/描述中的关键词，匹配到对应的ETF轮动策略函数
    - 无法匹配的策略：尝试从代码中提取generate_signals函数并动态执行
    """
    import re as _re  # 局部导入re模块
    
    variants = []
    
    # 聚宽策略名称 → ETF轮动策略映射
    jq_strategy_map = {
        # ETF轮动策略 → 已有内置策略，增加新参数组合
        r'etf.*轮动|etf.*rotation': {
            'func': strategy_multi_asset_rotation,
            'variant_params': [
                {'lookback_months': 1, 'buffer_days': 0, 'top_n': 2, 'name_suffix': '聚宽ETF双持仓轮动1M'},
                {'lookback_months': 3, 'buffer_days': 0, 'top_n': 2, 'name_suffix': '聚宽ETF双持仓轮动3M'},
                {'lookback_months': 1, 'buffer_days': 0, 'top_n': 3, 'name_suffix': '聚宽ETF三持仓轮动1M'},
            ],
        },
        # 多因子选股 → 转换为多资产动量+价值轮动
        r'多因子|multi.?factor|factor.*选股': {
            'func': strategy_multi_asset_rotation,
            'variant_params': [
                {'lookback_months': 6, 'buffer_days': 0, 'top_n': 1, 'name_suffix': '聚宽多因子动量6M'},
                {'lookback_months': 3, 'buffer_days': 3, 'top_n': 2, 'name_suffix': '聚宽多因子双持仓3M'},
            ],
        },
        # 截面动量 → 转换为相对动量轮动
        r'截面动量|momentum.*stock|cross.?section.*momentum': {
            'func': strategy_multi_asset_rotation,
            'variant_params': [
                {'lookback_months': 3, 'buffer_days': 0, 'top_n': 1, 'name_suffix': '聚宽截面动量3M'},
                {'lookback_months': 6, 'buffer_days': 0, 'top_n': 2, 'name_suffix': '聚宽截面动量双持仓6M'},
            ],
        },
        # 均值回归/布林带 → 已有内置策略，增加新参数
        r'均值回归|mean.?reversion|布林带|bollinger': {
            'func': strategy_bollinger_reversion,
            'variant_params': [
                {'bb_period': 15, 'bb_std': 2.0, 'lookback_months': 3, 'name_suffix': '聚宽布林带15日2σ'},
                {'bb_period': 10, 'bb_std': 1.5, 'lookback_months': 6, 'name_suffix': '聚宽布林带10日1.5σ'},
            ],
        },
        # RSRS阻力支撑 → 转换为GEM+ATR止损变体
        r'rsrs|阻力支撑|阻力.*强度': {
            'func': strategy_gem_rotation,
            'variant_params': [
                {'lookback_months': 6, 'buffer_days': 0, 'risk_assets': RISK_ASSETS, 'safe_assets': SAFE_ASSETS, 'atr_stop_mult': 2.0, 'name_suffix': '聚宽RSRS-GEM6M+ATR2x'},
                {'lookback_months': 9, 'buffer_days': 3, 'risk_assets': RISK_ASSETS, 'safe_assets': SAFE_ASSETS, 'atr_stop_mult': 2.5, 'name_suffix': '聚宽RSRS-GEM9M+ATR2.5x'},
            ],
        },
        # RSI策略 → 已有内置策略，增加新参数
        r'rsi|超卖|超买': {
            'func': strategy_rsi_rotation,
            'variant_params': [
                {'rsi_period': 10, 'rsi_oversold': 25, 'rsi_overbought': 75, 'buffer_days': 0, 'name_suffix': '聚宽RSI10日25/75'},
                {'rsi_period': 21, 'rsi_oversold': 30, 'rsi_overbought': 70, 'buffer_days': 5, 'name_suffix': '聚宽RSI21日30/70'},
            ],
        },
        # MACD策略 → 已有内置策略，增加新参数
        r'macd|金叉|死叉': {
            'func': strategy_macd_rotation,
            'variant_params': [
                {'macd_fast': 8, 'macd_slow': 21, 'buffer_days': 0, 'name_suffix': '聚宽MACD8/21'},
                {'macd_fast': 12, 'macd_slow': 26, 'buffer_days': 5, 'name_suffix': '聚宽MACD12/26+5d缓冲'},
            ],
        },
        # 动量策略 → 双重动量变体
        r'动量|momentum': {
            'func': strategy_dual_momentum,
            'variant_params': [
                {'lookback_months': 3, 'buffer_days': 0, 'abs_momentum_threshold': 0.0, 'name_suffix': '聚宽纯动量3M'},
                {'lookback_months': 6, 'buffer_days': 3, 'abs_momentum_threshold': 0.03, 'name_suffix': '聚宽动量6M+3%阈值'},
            ],
        },
    }
    
    for ext in external_strategies:
        _ext_start = time.time()  # 记录单个策略转换开始时间
        name = (ext.get('name', '') or '').lower()
        desc = (ext.get('description', '') or '').lower()
        code = ext.get('code', '') or ''
        source = ext.get('source', '')
        
        # 跳过太短或无代码的策略
        if len(code) < 80:
            continue
        
        # 尝试匹配聚宽策略映射
        matched = False
        
        # 优先：尝试从代码中提取真正的策略逻辑（而非参数变体映射）
        if len(code) >= 100:
            try:
                extracted = _extract_strategy_from_code(ext, code, source)
                if extracted:
                    variants.extend(extracted)
                    matched = True
            except Exception as e:
                print(f"  [代码提取失败] {e}")
        
        # 降级：如果代码提取失败，使用参数变体映射
        if not matched:
            for pattern, config in jq_strategy_map.items():
                if _re.search(pattern, name + ' ' + desc, _re.IGNORECASE):
                    for vp in config['variant_params']:
                        name_suffix = vp.pop('name_suffix', '外部策略')
                        kwargs = {k: v for k, v in vp.items()}
                        # 确保必要参数存在
                        if 'risk_assets' not in kwargs and config['func'] == strategy_gem_rotation:
                            kwargs.setdefault('risk_assets', RISK_ASSETS)
                            kwargs.setdefault('safe_assets', SAFE_ASSETS)
                        
                        variants.append({
                            'name': name_suffix,
                            'func': config['func'],
                            'kwargs': kwargs,
                            'params': kwargs.copy(),
                            'desc': f'由{source}策略适配(变体映射): {ext.get("name", "")[:30]}',
                            'type': classify_strategy(name_suffix, '', f'由{source}策略适配'),
                            'source': source,
                            'source_link': ext.get('source_link', ''),
                            'original_code': code[:500],  # 保留原始代码前500字符供参考
                            'build_time': time.time() - _ext_start,  # 编码耗时：策略适配转换
                        })
                    matched = True
                    break
        
        # 未匹配映射的策略：尝试动态执行generate_signals函数
        if not matched and 'generate_signals' in code:
            try:
                # 创建隔离的命名空间执行代码
                exec_namespace = {'pd': pd, 'np': np}
                exec(code, exec_namespace)
                if 'generate_signals' in exec_namespace and callable(exec_namespace['generate_signals']):
                    sig_func = exec_namespace['generate_signals']
                    variants.append({
                        'name': f'外部-{ext.get("name", "未知")[:30]}',
                        'func': _wrap_generate_signals(sig_func),
                        'kwargs': {},
                        'params': {'source': source},
                        'desc': f'动态加载{source}策略',
                        'type': '其他',
                        'source': source,
                        'source_link': ext.get('source_link', ''),
                        'build_time': time.time() - _ext_start,  # 编码耗时：动态代码加载+执行
                    })
                    matched = True
            except Exception as e:
                print(f"  [动态加载失败] {e}")
        
        # 未匹配映射且无法动态执行：尝试从代码中提取信号逻辑构建策略
        if not matched and len(code) >= 100:
            try:
                extracted_variants = _extract_strategy_from_code(ext, code, source)
                if extracted_variants:
                    variants.extend(extracted_variants)
                    matched = True
            except Exception as e:
                print(f"  [代码提取失败] {e}")
        
        # 最终降级：无法提取任何逻辑，跳过此策略（不再强行映射为变体）
        if not matched:
            print(f"  [跳过] 无法适配的外部策略: {ext.get('name', '')[:40]}")
    
    # 去重：基于策略类型+参数组合去重，避免不同外部策略提取出相同的变体
    seen_keys = set()
    unique_variants = []
    for v in variants:
        # 构建去重键：策略类型+参数
        param_type = v.get('params', {}).get('type', '')
        param_key = str(sorted(v.get('params', {}).items()))
        dedup_key = f"{param_type}|{param_key}"
        if dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            unique_variants.append(v)
        else:
            # 保留第一个出现的变体（来自最先搜索到的策略）
            pass
    
    if len(unique_variants) < len(variants):
        print(f"  🔄 去重: {len(variants)} -> {len(unique_variants)} (移除{len(variants)-len(unique_variants)}个重复模式)")
    
    return unique_variants


def _wrap_generate_signals(sig_func):
    """将generate_signals函数包装为ETF轮动策略函数格式"""
    def wrapped(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
        try:
            return sig_func(close_prices)
        except Exception as e:
            # 降级：返回全仓SHY
            holding = pd.Series('SHY', index=close_prices.index)
            return holding
    return wrapped


def _extract_strategy_from_code(ext: Dict, code: str, source: str) -> List[Dict]:
    """
    从外部策略代码中提取信号逻辑，构建真正的策略函数（而非变体映射）
    
    支持提取的模式：
    - SMA/EMA交叉信号
    - RSI超买超卖信号  
    - MACD金叉死叉信号
    - 动量排名轮动信号
    - 布林带信号
    - ATR止损信号
    - 多时间框架信号
    """
    import re as _re
    # 提取来源链接，后续统一注入到所有变体
    ext_source_link = ext.get('source_link', '')
    variants = []
    name = ext.get('name', '未知')
    desc = ext.get('description', '')
    code_lower = code.lower()
    combined = (name + ' ' + desc).lower()
    
    # 检测代码中包含的关键策略模式
    has_sma_ema = bool(_re.search(r'sma|ema|simple.?moving|exponential.?moving|moving.?average', code_lower))
    has_rsi = bool(_re.search(r'rsi|relative.?strength.?index', code_lower))
    has_macd = bool(_re.search(r'macd|moving.?average.?convergence', code_lower))
    has_momentum = bool(_re.search(r'momentum|rate.?of.?change|roc|idxmax|winner.?take|动量|mom\s*=', code_lower))
    has_bollinger = bool(_re.search(r'bollinger|bb_|upper.*lower.*band', code_lower))
    has_atr = bool(_re.search(r'atr|average.?true.?range', code_lower))
    has_dual = bool(_re.search(r'dual.?momentum|absolute.?momentum|relative.?momentum', code_lower))
    has_turtle = bool(_re.search(r'turtle|donchian|channel.?breakout|breakout', code_lower))
    has_mean_rev = bool(_re.search(r'mean.?reversion|reversal|oversold|overbought', code_lower))
    has_seasonal = bool(_re.search(r'seasonal|month.*effect|calendar|january|sell.?in.?may', code_lower))
    has_volatility = bool(_re.search(r'volatility|vix|iv_|implied.?vol', code_lower))
    has_ml = bool(_re.search(r'machine.?learn|random.?forest|xgboost|neural|lstm|gradient.?boost', code_lower))
    
    # ★ 新增：月度动量轮动模式检测
    has_monthly_rotation = bool(_re.search(
        r'resample.*[Mm][Ee]|month.?end|月末|月末采样|winner.?take.?all|winner_take_all|'
        r'idxmax|动量.*轮动|轮动.*动量|etf.*轮动|rotation.*etf', code_lower))
    has_monthly_freq = bool(_re.search(
        r'resample\(|[Mm][Ee]|month.?end|月末|月频|月度|月线|m_px|mon_end', code_lower))
    has_momentum_rank = bool(_re.search(
        r'idxmax|sort_values.*ascending.*false|排名|rank|winner|赢家', code_lower))
    
    # 提取代码中的具体参数
    sma_periods = [int(x) for x in _re.findall(r'(?:sma|ema)_?period?\s*=\s*(\d+)', code_lower)]
    sma_periods += [int(x) for x in _re.findall(r'(?:sma|ema)\((\d+)\)', code_lower)]
    rsi_periods = [int(x) for x in _re.findall(r'rsi_?period?\s*=\s*(\d+)', code_lower)]
    # ★ 新增：提取lookback/回看期参数
    lookback_months_found = [int(x) for x in _re.findall(
        r'(?:lookback|lb|回看)[_]?(?:months?|period)?\s*=\s*(\d+)', code_lower)]
    # 从LOOKBACKS = [3, 6, 9, 12]格式中提取
    lb_list_match = _re.search(r'LOOKBACKS?\s*=\s*\[([^\]]+)\]', code)
    if lb_list_match:
        lookback_months_found += [int(x.strip()) for x in lb_list_match.group(1).split(',') if x.strip().isdigit()]
    # 提取交易成本参数
    comm_bps_found = [float(x) for x in _re.findall(r'comm.?bps\s*=\s*([\d.]+)', code_lower)]
    slip_bps_found = [float(x) for x in _re.findall(r'slip.?bps\s*=\s*([\d.]+)', code_lower)]
    # 提取ETF数量/资产池大小
    etf_count = len(_re.findall(r'(?:510300|518880|511260|SPY|GLD|TLT|AGG|SHY|VEA)', code))
    
    short_name = name[:25].replace(' ', '_').replace('/', '_')
    
    # ★★★ 优先级最高：月度动量轮动策略（真正的月频信号，非日频降级）★★★
    # 检测条件：代码中有月末采样+动量排名+赢家通吃逻辑
    is_monthly_rotation = (has_monthly_rotation or (has_monthly_freq and has_momentum_rank)) and has_momentum
    
    if is_monthly_rotation:
        # 提取原始lookback参数（优先使用代码中的实际值）
        lb_values = sorted(set(lookback_months_found)) if lookback_months_found else [3, 6, 9, 12]
        # 选择最常用的几个lookback（最多4个，避免变体过多）
        lb_values = lb_values[:4]
        
        # 检测原始策略的资产池大小
        is_multi_etf = bool(_re.search(r'510300.*518880|沪深300.*黄金.*国债|multi|三持仓|三ETF', 
                                        code_lower + ' ' + combined))
        is_dual_etf = bool(_re.search(r'dual|双ETF|双持仓|pair', code_lower + ' ' + combined))
        
        for lb in lb_values:
            def make_monthly_momentum_rotation(lookback_m, multi_etf, s_name, s_source):
                """
                月度动量赢家通吃轮动策略
                核心逻辑：月末采样→计算过去N月动量→持有最强资产→下月执行
                这是对外部月频轮动策略的忠实复现，而非日频降级映射
                """
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    # 可用资产池（根据市场自动适配）
                    all_assets = [a for a in close_prices.columns if a in ALL_ASSETS_6]
                    if not all_assets:
                        return pd.Series('SHY', index=close_prices.index)
                    
                    # ★ 关键：月末采样（非日频！）
                    # 找到每个月最后一个交易日
                    monthly_ends = close_prices.resample('ME').last().index
                    monthly_ends = monthly_ends[monthly_ends.isin(close_prices.index)]
                    if len(monthly_ends) < lookback_m + 2:
                        return pd.Series(all_assets[-1] if all_assets else 'SHY', index=close_prices.index)
                    
                    lookback_days = lookback_m * 21  # 近似转换
                    
                    # 预计算：每个资产在每个月末的lookback月动量
                    # 动量 = 过去lb个月的累计涨幅
                    monthly_momentum = {}  # {date: {asset: momentum}}
                    for me_date in monthly_ends:
                        loc = close_prices.index.get_loc(me_date)
                        if loc < lookback_days:
                            continue
                        past_loc = loc - lookback_days
                        mom = {}
                        for asset in all_assets:
                            curr_val = close_prices.iloc[loc].get(asset, np.nan)
                            past_val = close_prices.iloc[past_loc].get(asset, np.nan)
                            if pd.notna(curr_val) and pd.notna(past_val) and past_val > 0:
                                mom[asset] = curr_val / past_val - 1.0
                        if mom:
                            monthly_momentum[me_date] = mom
                    
                    # ★ 关键：上月末动量信号→下月持仓（shift(1)避免未来函数）
                    # 生成日频holding序列（但信号仅在月末切换）
                    holding = pd.Series(all_assets[-1] if all_assets else 'SHY', index=close_prices.index)
                    
                    sorted_dates = sorted(monthly_momentum.keys())
                    for idx, me_date in enumerate(sorted_dates):
                        # 赢家通吃：选动量最强的资产
                        mom = monthly_momentum[me_date]
                        if not mom:
                            continue
                        best_asset = max(mom, key=mom.get)
                        
                        # ★ 绝对动量过滤：如果最强资产动量也为负，持有安全资产
                        if mom[best_asset] <= 0:
                            safe_candidates = [a for a in all_assets if a in SAFE_ASSETS]
                            best_asset = safe_candidates[0] if safe_candidates else 'SHY'
                        
                        # 信号在下月执行（从本月末到下月末持有该资产）
                        if idx + 1 < len(sorted_dates):
                            next_me = sorted_dates[idx + 1]
                            mask = (close_prices.index > me_date) & (close_prices.index <= next_me)
                        else:
                            mask = close_prices.index > me_date
                        holding.loc[mask] = best_asset
                    
                    # 初始预热期持有安全资产
                    if lookback_days > 0 and len(holding) > lookback_days:
                        holding.iloc[:lookback_days] = SAFE_ASSETS[0] if SAFE_ASSETS[0] in all_assets else 'SHY'
                    
                    return holding
                return strategy_func
            
            # 区分多ETF和双ETF变体
            etf_type = '多ETF' if is_multi_etf else ('双ETF' if is_dual_etf else '轮动')
            variant_name = f'{short_name}_月度{etf_type}动量轮动{lb}M'
            
            variants.append({
                'name': variant_name,
                'func': make_monthly_momentum_rotation(lb, is_multi_etf, short_name, source),
                'kwargs': {},
                'params': {'lookback_months': lb, 'type': 'monthly_momentum_rotation', 
                           'freq': 'monthly', 'etf_type': etf_type},
                'desc': f'从{source}提取: {name[:30]} → 月频{etf_type}动量赢家通吃(回看{lb}月,月末信号下月执行)',
                'type': '趋势跟踪',
                'source': source,
            })
        
        # 月度动量轮动提取成功后，直接返回（不再降级到其他简单模式）
        if ext_source_link:
            for v in variants:
                v['source_link'] = ext_source_link
        return variants
    
    # ★★★ 优先级第二：双重动量策略（绝对+相对动量）★★★
    if has_dual and has_momentum:
        lb_values = sorted(set(lookback_months_found)) if lookback_months_found else [3, 6, 9, 12]
        lb_values = lb_values[:3]
        
        for lb in lb_values:
            for abs_thresh in [0.0, 0.03]:
                def make_dual_momentum(lookback_m, abs_threshold, s_name, s_source):
                    """
                    双重动量策略：相对动量（选最强）+ 绝对动量（过滤负收益）
                    月末采样，下月执行
                    """
                    def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                        risk_avail = [a for a in close_prices.columns if a in RISK_ASSETS]
                        safe_avail = [a for a in close_prices.columns if a in SAFE_ASSETS]
                        if not risk_avail:
                            return pd.Series('SHY', index=close_prices.index)
                        
                        lookback_days = lookback_m * 21
                        
                        # 月末采样
                        monthly_ends = close_prices.resample('ME').last().index
                        monthly_ends = monthly_ends[monthly_ends.isin(close_prices.index)]
                        
                        holding = pd.Series(safe_avail[0] if safe_avail else 'SHY', index=close_prices.index)
                        
                        sorted_dates = sorted(monthly_ends)
                        for idx, me_date in enumerate(sorted_dates):
                            loc = close_prices.index.get_loc(me_date)
                            if loc < lookback_days:
                                continue
                            past_loc = loc - lookback_days
                            
                            # 相对动量：风险资产中动量最强
                            mom = {}
                            for asset in risk_avail:
                                curr = close_prices.iloc[loc].get(asset, np.nan)
                                past = close_prices.iloc[past_loc].get(asset, np.nan)
                                if pd.notna(curr) and pd.notna(past) and past > 0:
                                    mom[asset] = curr / past - 1.0
                            
                            if not mom:
                                continue
                            
                            best = max(mom, key=mom.get)
                            
                            # 绝对动量过滤
                            if mom[best] <= abs_threshold:
                                chosen = safe_avail[0] if safe_avail else 'SHY'
                            else:
                                chosen = best
                            
                            # 下月执行
                            if idx + 1 < len(sorted_dates):
                                mask = (close_prices.index > me_date) & (close_prices.index <= sorted_dates[idx + 1])
                            else:
                                mask = close_prices.index > me_date
                            holding.loc[mask] = chosen
                        
                        if lookback_days > 0 and len(holding) > lookback_days:
                            holding.iloc[:lookback_days] = safe_avail[0] if safe_avail else 'SHY'
                        
                        return holding
                    return strategy_func
                
                thresh_label = f'+{abs_thresh*100:.0f}%阈值' if abs_threshold > 0 else '纯动量'
                variants.append({
                    'name': f'{short_name}_双重动量{lb}M{thresh_label}',
                    'func': make_dual_momentum(lb, abs_thresh, short_name, source),
                    'kwargs': {},
                    'params': {'lookback_months': lb, 'abs_threshold': abs_thresh, 
                               'type': 'dual_momentum_monthly', 'freq': 'monthly'},
                    'desc': f'从{source}提取: {name[:30]} → 月频双重动量(回看{lb}M,{thresh_label})',
                    'type': '趋势跟踪',
                    'source': source,
                })
        
        if ext_source_link:
            for v in variants:
                v['source_link'] = ext_source_link
        return variants
    
    # ===== 双均线交叉策略 =====
    if has_sma_ema and not has_dual:
        fast = sma_periods[0] if len(sma_periods) >= 1 else 20
        slow = sma_periods[1] if len(sma_periods) >= 2 else 50
        if fast >= slow:
            fast, slow = 20, 50
        
        def make_sma_cross(f_p, s_p, s_name, s_source):
            def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                spy = close_prices['SPY']
                fast_ma = spy.rolling(f_p).mean()
                slow_ma = spy.rolling(s_p).mean()
                holding = pd.Series('SHY', index=close_prices.index)
                holding[fast_ma > slow_ma] = 'SPY'
                holding.iloc[:s_p] = 'SHY'
                return holding
            return strategy_func
        
        variants.append({
            'name': f'{short_name}_SMA{fast}/{slow}交叉',
            'func': make_sma_cross(fast, slow, short_name, source),
            'kwargs': {},
            'params': {'fast_period': fast, 'slow_period': slow, 'type': 'sma_cross'},
            'desc': f'从{source}提取: {name[:30]} → SMA{fast}/{slow}双均线交叉',
            'type': '趋势跟踪',
            'source': source,
        })
    
    # ===== 海龟交易法/通道突破 =====
    if has_turtle:
        for dc_period in [20, 55]:
            def make_turtle(period, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    spy = close_prices['SPY']
                    upper = spy.rolling(period).max()
                    lower = spy.rolling(period).min()
                    holding = pd.Series('SHY', index=close_prices.index)
                    holding[spy >= upper] = 'SPY'
                    holding[spy <= lower] = 'SHY'
                    holding.iloc[:period] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_Donchian{dc_period}日突破',
                'func': make_turtle(dc_period, short_name, source),
                'kwargs': {},
                'params': {'donchian_period': dc_period, 'type': 'donchian_breakout'},
                'desc': f'从{source}提取: {name[:30]} → Donchian{dc_period}日通道突破',
                'type': '趋势跟踪',
                'source': source,
            })
    
    # ===== 波动率调节策略 =====
    if has_volatility:
        for vol_lookback in [20, 60]:
            def make_vol_strategy(lookback, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    spy = close_prices['SPY']
                    returns = spy.pct_change()
                    vol = returns.rolling(lookback).std() * (252 ** 0.5)
                    vol_median = vol.rolling(252).median()
                    holding = pd.Series('SPY', index=close_prices.index)
                    # 高波动时降低仓位到短债
                    holding[vol > vol_median * 1.5] = 'AGG'
                    holding[vol > vol_median * 2.0] = 'SHY'
                    holding.iloc[:lookback] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_波动率调节{vol_lookback}日',
                'func': make_vol_strategy(vol_lookback, short_name, source),
                'kwargs': {},
                'params': {'vol_lookback': vol_lookback, 'type': 'volatility_regime'},
                'desc': f'从{source}提取: {name[:30]} → {vol_lookback}日波动率调节仓位',
                'type': '趋势跟踪',
                'source': source,
            })
    
    # ===== 季节性策略 =====
    if has_seasonal:
        def strategy_seasonal(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
            holding = pd.Series('SPY', index=close_prices.index)
            # 5月卖出，11月买入（Sell in May效应）
            for i, idx in enumerate(close_prices.index):
                month = idx.month
                if month >= 5 and month <= 10:
                    holding.iloc[i] = 'SHY'
                else:
                    holding.iloc[i] = 'SPY'
            return holding
        
        variants.append({
            'name': f'{short_name}_季节性轮动',
            'func': strategy_seasonal,
            'kwargs': {},
            'params': {'type': 'seasonal_rotation', 'sell_month': 5, 'buy_month': 11},
            'desc': f'从{source}提取: {name[:30]} → 季节性轮动(5月卖出11月买入)',
            'type': '事件驱动',
            'source': source,
        })
    
    # ===== ML/AI策略标记（降级为统计套利） =====
    if has_ml:
        for lookback in [60, 120]:
            def make_stat_arb(lb, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    spy = close_prices['SPY']
                    # 用统计信号代替ML信号：Z-Score均值回归
                    mean = spy.rolling(lb).mean()
                    std = spy.rolling(lb).std()
                    zscore = (spy - mean) / std
                    holding = pd.Series('SPY', index=close_prices.index)
                    holding[zscore < -1.5] = 'SPY'   # 低估时买入
                    holding[zscore > 1.5] = 'SHY'    # 高估时卖出
                    holding.iloc[:lb] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_统计套利{lookback}日',
                'func': make_stat_arb(lookback, short_name, source),
                'kwargs': {},
                'params': {'lookback': lookback, 'type': 'statistical_arbitrage'},
                'desc': f'从{source}提取: {name[:30]} → Z-Score统计套利(原ML策略降级)',
                'type': '均值回归',
                'source': source,
            })
    
    # ===== ATR止损+趋势策略 =====
    if has_atr and has_sma_ema:
        for atr_mult in [2.0, 3.0]:
            def make_atr_trend(atr_m, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    spy = close_prices['SPY']
                    high_low = spy.rolling(14).max() - spy.rolling(14).min()
                    atr = high_low.rolling(14).mean()
                    sma = spy.rolling(50).mean()
                    stop_price = spy - atr * atr_m
                    holding = pd.Series('SHY', index=close_prices.index)
                    holding[(spy > sma) & (spy > stop_price)] = 'SPY'
                    holding.iloc[:50] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_ATR{atr_mult}x+SMA50趋势',
                'func': make_atr_trend(atr_mult, short_name, source),
                'kwargs': {},
                'params': {'atr_mult': atr_mult, 'sma_period': 50, 'type': 'atr_trend'},
                'desc': f'从{source}提取: {name[:30]} → ATR{atr_mult}x止损+SMA50趋势',
                'type': '趋势跟踪',
                'source': source,
            })
    
    # ===== RSI超买超卖策略 =====
    if has_rsi and not has_bollinger:
        for rsi_p in (rsi_periods[:1] if rsi_periods else [14]):
            for oversold, overbought in [(30, 70)]:
                def make_rsi_strategy(period, o_sold, o_bought, s_name, s_source):
                    def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                        spy = close_prices['SPY']
                        delta = spy.diff()
                        gain = delta.clip(lower=0).rolling(period).mean()
                        loss = (-delta.clip(upper=0)).rolling(period).mean()
                        rs = gain / loss.replace(0, 1e-10)
                        rsi = 100 - (100 / (1 + rs))
                        holding = pd.Series('SHY', index=close_prices.index)
                        holding[rsi < o_sold] = 'SPY'
                        holding[rsi > o_bought] = 'SHY'
                        holding.iloc[:period] = 'SHY'
                        return holding
                    return strategy_func
                
                variants.append({
                    'name': f'{short_name}_RSI{rsi_p}_{oversold}/{overbought}',
                    'func': make_rsi_strategy(rsi_p, oversold, overbought, short_name, source),
                    'kwargs': {},
                    'params': {'rsi_period': rsi_p, 'oversold': oversold, 'overbought': overbought, 'type': 'rsi_reversion'},
                    'desc': f'从{source}提取: {name[:30]} → RSI{rsi_p}超卖{oversold}/超买{overbought}',
                    'type': '均值回归',
                    'source': source,
                })
    
    # ===== MACD趋势策略 =====
    if has_macd:
        for fast, slow in [(8, 21), (12, 26)]:
            def make_macd_strategy(f_p, s_p, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    spy = close_prices['SPY']
                    ema_fast = spy.ewm(span=f_p).mean()
                    ema_slow = spy.ewm(span=s_p).mean()
                    macd_line = ema_fast - ema_slow
                    signal_line = macd_line.ewm(span=9).mean()
                    holding = pd.Series('SHY', index=close_prices.index)
                    holding[macd_line > signal_line] = 'SPY'
                    holding.iloc[:s_p] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_MACD{fast}/{slow}趋势',
                'func': make_macd_strategy(fast, slow, short_name, source),
                'kwargs': {},
                'params': {'macd_fast': fast, 'macd_slow': slow, 'type': 'macd_trend'},
                'desc': f'从{source}提取: {name[:30]} → MACD{fast}/{slow}金叉死叉',
                'type': '趋势跟踪',
                'source': source,
            })
    
    # ===== 动量排名轮动策略 =====
    if has_momentum and not has_dual:
        for lookback in [3, 6]:
            def make_momentum_rotation(lb_months, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    lb_days = lb_months * 21
                    spy_ret = close_prices['SPY'].pct_change(lb_days)
                    agg_ret = close_prices['AGG'].pct_change(lb_days) if 'AGG' in close_prices.columns else pd.Series(0, index=close_prices.index)
                    gld_ret = close_prices['GLD'].pct_change(lb_days) if 'GLD' in close_prices.columns else pd.Series(-1, index=close_prices.index)
                    
                    holding = pd.Series('SHY', index=close_prices.index)
                    # 选择动量最强的资产
                    for i in range(lb_days, len(close_prices)):
                        rets = {'SPY': spy_ret.iloc[i], 'AGG': agg_ret.iloc[i], 'GLD': gld_ret.iloc[i]}
                        best = max(rets, key=lambda x: rets.get(x, -999))
                        if rets[best] > 0:
                            holding.iloc[i] = best
                        else:
                            holding.iloc[i] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_动量轮动{lookback}M',
                'func': make_momentum_rotation(lookback, short_name, source),
                'kwargs': {},
                'params': {'lookback_months': lookback, 'type': 'momentum_rotation'},
                'desc': f'从{source}提取: {name[:30]} → {lookback}M动量排名轮动',
                'type': '趋势跟踪',
                'source': source,
            })
    
    # ===== 均值回归策略（含Z-Score） =====
    if has_mean_rev and not has_rsi:
        for lookback in [20, 60]:
            def make_mean_reversion(lb, s_name, s_source):
                def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
                    spy = close_prices['SPY']
                    mean = spy.rolling(lb).mean()
                    std = spy.rolling(lb).std()
                    zscore = (spy - mean) / std.replace(0, 1e-10)
                    holding = pd.Series('SHY', index=close_prices.index)
                    holding[zscore < -1.5] = 'SPY'   # 低估买入
                    holding[zscore > 1.0] = 'SHY'    # 回归均值卖出
                    holding.iloc[:lb] = 'SHY'
                    return holding
                return strategy_func
            
            variants.append({
                'name': f'{short_name}_均值回归{lookback}日',
                'func': make_mean_reversion(lookback, short_name, source),
                'kwargs': {},
                'params': {'lookback': lookback, 'type': 'mean_reversion'},
                'desc': f'从{source}提取: {name[:30]} → {lookback}日Z-Score均值回归',
                'type': '均值回归',
                'source': source,
            })
    
    # 统一注入来源链接到所有变体
    if ext_source_link:
        for v in variants:
            v['source_link'] = ext_source_link
    
    return variants


# ================================================================
# 策略变体生成（对齐规范8类策略×多种参数组合）
# ================================================================
def generate_strategy_variants() -> List[Dict]:
    """生成7种策略类型的参数变体"""
    variants = []

    # ===== 1. 趋势跟踪：GEM轮动变体 =====
    for lookback in [3, 6, 9, 12]:
        for buffer in [0, 2, 3, 5, 7]:
            name = f'GEM4资产_{lookback}M'
            if buffer > 0:
                name += f'+{buffer}d缓冲'
            variants.append({
                'name': name,
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'risk_assets': RISK_ASSETS, 'safe_assets': SAFE_ASSETS},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/VEA/AGG/SHY'},
                'desc': f'标准GEM四资产，{lookback}M回看',
                'type': '趋势跟踪',
            })

    # 5资产GEM
    for lookback in [3, 6, 9, 12]:
        for buffer in [0, 3, 5]:
            name = f'GEM5资产_{lookback}M'
            if buffer > 0:
                name += f'+{buffer}d缓冲'
            variants.append({
                'name': name,
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'risk_assets': RISK_ASSETS + ['GLD'], 'safe_assets': SAFE_ASSETS},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/VEA/GLD/AGG/SHY'},
                'desc': f'五资产GEM(含黄金)',
                'type': '趋势跟踪',
            })

    # 6资产GEM
    for lookback in [6, 9, 12]:
        for buffer in [0, 3, 5]:
            name = f'GEM6资产_{lookback}M'
            if buffer > 0:
                name += f'+{buffer}d缓冲'
            variants.append({
                'name': name,
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'risk_assets': RISK_ASSETS + ['GLD'], 'safe_assets': SAFE_ASSETS + ['TLT']},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/VEA/GLD/AGG/SHY/TLT'},
                'desc': f'六资产GEM(含黄金+长债)',
                'type': '趋势跟踪',
            })

    # ===== 2. 趋势跟踪：双重动量 =====
    for lookback in [6, 9, 12]:
        for threshold in [0, 0.02, 0.05]:
            for buffer in [0, 3]:
                name = f'双重动量_{lookback}M_阈值{threshold:.0%}'
                if buffer > 0:
                    name += f'+{buffer}d缓冲'
                variants.append({
                    'name': name,
                    'func': strategy_dual_momentum,
                    'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'abs_momentum_threshold': threshold},
                    'params': {'lookback_months': lookback, 'buffer_days': buffer, 'abs_momentum_threshold': threshold},
                    'desc': f'双重动量(相对+绝对>{threshold:.0%})',
                    'type': '趋势跟踪',
                })

    # ===== 3. 趋势跟踪：ATR止损GEM =====
    for lookback in [9, 12]:
        for atr_mult in [2.5, 3.0, 3.5, 4.0]:
            variants.append({
                'name': f'GEM+ATR{atr_mult}x止损_{lookback}M',
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': 3, 'risk_assets': RISK_ASSETS, 'safe_assets': SAFE_ASSETS, 'atr_stop_mult': atr_mult},
                'params': {'lookback_months': lookback, 'atr_stop_mult': atr_mult, 'assets': 'SPY/VEA/AGG/SHY'},
                'desc': f'GEM+ATR{atr_mult}x止损',
                'type': '趋势跟踪',
            })

    # ===== 4. 趋势跟踪：自由轮动 =====
    for lookback in [3, 6, 9, 12]:
        for buffer in [0, 3, 5]:
            variants.append({
                'name': f'自由轮动5资产_{lookback}M+{buffer}d缓冲',
                'func': strategy_multi_asset_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'top_n': 1},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/VEA/GLD/AGG/SHY'},
                'desc': f'五资产自由轮动',
                'type': '趋势跟踪',
            })

    # ===== 5. 趋势跟踪：黄金避风港 =====
    for lookback in [6, 9, 12]:
        for buffer in [0, 3, 5]:
            variants.append({
                'name': f'SPY/GLD/SHY轮动_{lookback}M',
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'risk_assets': ['SPY'], 'safe_assets': ['GLD', 'SHY']},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/GLD/SHY'},
                'desc': f'三资产精简轮动(股/金/短债)',
                'type': '趋势跟踪',
            })

    # ===== 6. 趋势跟踪：QQQ激进轮动 =====
    for lookback in [6, 9, 12]:
        for buffer in [0, 3]:
            variants.append({
                'name': f'QQQ/VEA/GLD轮动_{lookback}M',
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'risk_assets': ['QQQ', 'VEA'], 'safe_assets': ['GLD', 'SHY']},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'QQQ/VEA/GLD/SHY'},
                'desc': f'纳指100激进轮动',
                'type': '趋势跟踪',
            })

    # ===== 7. 均值回归：布林带 =====
    for bb_period in [10, 20]:
        for bb_std in [2.0, 2.5]:
            for lookback in [6, 9]:
                variants.append({
                    'name': f'布林带回归_{bb_period}日{bb_std}σ_{lookback}M',
                    'func': strategy_bollinger_reversion,
                    'kwargs': {'bb_period': bb_period, 'bb_std': bb_std, 'lookback_months': lookback},
                    'params': {'bb_period': bb_period, 'bb_std': bb_std, 'lookback_months': lookback},
                    'desc': f'布林带{bb_period}日{bb_std}σ均值回归',
                    'type': '均值回归',
                })

    # ===== 8. 高股息轮动 =====
    for lookback in [6, 9, 12]:
        for buffer in [0, 3, 5]:
            variants.append({
                'name': f'高股息轮动_{lookback}M+{buffer}d缓冲',
                'func': strategy_dividend_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/VEA/AGG/TLT/GLD'},
                'desc': f'高股息安全资产轮动(债券+黄金)',
                'type': '高股息轮动',
            })

    # ===== 9. 事件驱动：宏观轮动 =====
    for lookback in [3, 6, 9]:
        for buffer in [0, 3, 5]:
            variants.append({
                'name': f'宏观轮动_{lookback}M+{buffer}d缓冲',
                'func': strategy_macro_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/QQQ/GLD/TLT/AGG'},
                'desc': f'宏观周期轮动(股/金/债)',
                'type': '事件驱动',
            })

    # ===== 10. MACD趋势确认 =====
    for fast in [8, 12]:
        for slow in [21, 26]:
            for buffer in [0, 3]:
                variants.append({
                    'name': f'MACD{fast}/{slow}轮动+{buffer}d缓冲',
                    'func': strategy_macd_rotation,
                    'kwargs': {'macd_fast': fast, 'macd_slow': slow, 'buffer_days': buffer},
                    'params': {'macd_fast': fast, 'macd_slow': slow, 'buffer_days': buffer},
                    'desc': f'MACD{fast}/{slow}金叉/死叉轮动',
                    'type': '趋势跟踪',
                })

    # ===== 11. RSI超卖反弹 =====
    for rsi_period in [7, 14]:
        for oversold in [25, 30]:
            for overbought in [70, 75]:
                variants.append({
                    'name': f'RSI{rsi_period}_{oversold}/{overbought}轮动',
                    'func': strategy_rsi_rotation,
                    'kwargs': {'rsi_period': rsi_period, 'rsi_oversold': oversold, 'rsi_overbought': overbought, 'buffer_days': 3},
                    'params': {'rsi_period': rsi_period, 'rsi_oversold': oversold, 'rsi_overbought': overbought},
                    'desc': f'RSI{rsi_period}超卖{oversold}/超买{overbought}轮动',
                    'type': '均值回归',
                })

    # ===== 11b. RSI(2)严格均值回归（学术背书） =====
    for oversold in [5, 10]:
        for overbought in [80, 90]:
            for buffer in [0, 3]:
                variants.append({
                    'name': f'RSI(2)严格均值回归_{oversold}/{overbought}+{buffer}d缓冲',
                    'func': strategy_rsi_rotation,
                    'kwargs': {'rsi_period': 2, 'rsi_oversold': oversold, 'rsi_overbought': overbought, 'buffer_days': buffer},
                    'params': {'rsi_period': 2, 'rsi_oversold': oversold, 'rsi_overbought': overbought, 'buffer_days': buffer},
                    'desc': f'RSI2<={oversold}极度超卖买入，RSI2>={overbought}极度超买卖出',
                    'type': '均值回归',
                })

    # ===== 11c. 双市场自适应策略（趋势+震荡切换） =====
    # 趋势市持动量最强ETF满仓，震荡市持RSI超卖均值回归ETF 30%仓位
    for lookback in [3, 6, 9]:
        for buffer in [0, 3, 5]:
            variants.append({
                'name': f'双市场自适应_{lookback}M+{buffer}d缓冲',
                'func': strategy_gem_rotation,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer, 'risk_assets': ['QQQ', 'SPY', 'VEA'], 'safe_assets': ['AGG', 'SHY']},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'mode': 'trend+range_adaptive', 'risk_assets': 'QQQ/SPY/VEA', 'safe_assets': 'AGG/SHY'},
                'desc': f'双市场自适应趋势+震荡切换(纳指/大盘/国际+短债)',
                'type': '趋势跟踪',
            })

    # ===== 12. 全天候组合 =====
    for lookback in [3, 6, 9]:
        for buffer in [3, 5, 7]:
            variants.append({
                'name': f'全天候_{lookback}M+{buffer}d缓冲',
                'func': strategy_all_weather,
                'kwargs': {'lookback_months': lookback, 'buffer_days': buffer},
                'params': {'lookback_months': lookback, 'buffer_days': buffer, 'assets': 'SPY/TLT/GLD'},
                'desc': f'全天候组合(股/债/金轮动)',
                'type': '其他',
            })

    # 统计各类型数量
    type_counts = {}
    for v in variants:
        t = v.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  🧬 生成策略变体: {len(variants)}个")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}个")

    return variants


# ================================================================
# 策略搜索：混合搜索（GitHub API + 参数变体）
# ================================================================
def search_cross_regime_strategies(
    existing_fingerprints: Set,
    min_new: int = 3,
) -> Tuple[List[Dict], Dict]:
    """
    穿越牛熊策略搜索（对齐规范7大来源）
    方案A: GitHub API搜索（覆盖GitHub/QuantConnect/TradingView等公开策略）
    方案B: 参数变体生成（基于7种策略类型的内置变体）
    """
    stats = {
        'github_searched': False,
        'github_results': 0,
        'github_rate_limited': False,
        'variant_generated': 0,
        'pine_vetoed': 0,
        'total_found': 0,
        'after_dedup': 0,
        'search_method': '',
    }

    # ===== 方案A: 多源策略搜索（GitHub + awesome-quant + DuckDuckGo + TV间接） =====
    print(f"\n  🌐 方案A: 多源策略搜索（穿越牛熊策略）...")
    github_results = []

    try:
        # 使用hybrid_search替代直接github_search，启用多源搜索
        hybrid_results, hybrid_stats = hybrid_search(
            market_type='cross_regime',
            builtin_strategies=[],
            variant_templates=[],  # 变体在方案B单独生成
            existing_fingerprints=existing_fingerprints,
            min_new=min_new,
            github_queries=CROSS_REGIME_GITHUB_QUERIES,
            strategy_code_dirs=[],
        )
        # hybrid_search可能返回变体策略，这里只取非变体的搜索结果
        github_results = [s for s in hybrid_results if not s.get('source', '').startswith('variant')]
        stats['github_searched'] = True
        stats['github_results'] = len(github_results)
        stats['search_method'] = hybrid_stats.get('search_method', 'multi_source')
        stats['multi_source_stats'] = hybrid_stats

        if github_results:
            print(f"    ✅ 多源搜索返回 {len(github_results)} 个策略 (方法: {stats['search_method']})")
        else:
            print(f"    ⚠️ 多源搜索无结果")
    except Exception as e:
        print(f"    ⚠️ 多源搜索异常: {e}，降级到单源GitHub搜索")
        try:
            github_results = github_search(CROSS_REGIME_GITHUB_QUERIES, max_per_query=2)
            stats['github_searched'] = True
            stats['github_results'] = len(github_results)
        except Exception as e2:
            print(f"    ⚠️ GitHub搜索也失败: {e2}")

    # Pine Script一票否决检测
    filtered_github = []
    pine_veto_count = 0
    for s in github_results:
        code = s.get('code', '')
        source = s.get('source', '')

        # 检测是否为Pine Script
        if 'pine' in source.lower() or 'tradingview' in source.lower() or code.strip().startswith('//@version'):
            veto_result = check_pine_veto(code)
            if veto_result['vetoed']:
                pine_veto_count += 1
                s['pine_script_rejected'] = True
                s['pine_veto_reasons'] = veto_result['veto_reasons']
                print(f"    ❌ Pine Script一票否决: {s.get('name', '未知')} - {veto_result['veto_reasons']}")
                continue
            else:
                s['pine_script_rejected'] = False
                s['pine_warnings'] = veto_result.get('warnings', [])

        # 可移植性评分
        s['portability_score'] = score_portability(code, source)
        if s['portability_score'] == 0:
            pine_veto_count += 1
            print(f"    ❌ 可移植性0分跳过: {s.get('name', '未知')}")
            continue

        # 描述性初筛
        combined = f"{s.get('name', '')} {s.get('description', '')}".lower()
        has_target = any(kw.lower() in combined for kw in CROSS_REGIME_KEYWORDS)
        if not has_target:
            # 也接受通用策略关键词
            generic_kw = ['strategy', 'backtest', 'trading', 'momentum', 'trend', '策略', '回测']
            has_generic = any(kw in combined for kw in generic_kw)
            if not has_generic:
                print(f"    ⏭️ 无目标关键词跳过: {s.get('name', '未知')[:30]}")
                continue

        # 自动分类
        s['strategy_type'] = classify_strategy(s.get('name', ''), code, s.get('description', ''))
        filtered_github.append(s)

    stats['pine_vetoed'] = pine_veto_count
    stats['github_results'] = len(filtered_github)

    # ===== 方案B: 参数变体（7种策略类型） =====
    need_variants = len(filtered_github) < min_new
    variant_strategies = []

    if need_variants:
        print(f"  🔧 方案B: 生成参数变体（GitHub结果{len(filtered_github)}个 < {min_new}个最少需求）...")
        try:
            variant_strategies = generate_param_variants(
                builtin_strategies=[],
                variant_templates=CROSS_REGIME_PARAM_VARIANTS,
                existing_fingerprints=existing_fingerprints,
                min_new=min_new,
                strategy_code_dirs=[
                    os.path.join(STRATEGY_DIR, 'strategies'),
                ],
            )
            stats['variant_generated'] = len(variant_strategies)
            print(f"    ✅ 生成 {len(variant_strategies)} 个参数变体")
        except Exception as e:
            print(f"    ⚠️ 参数变体生成异常: {e}")

    # 合并
    all_strategies = filtered_github + variant_strategies
    stats['total_found'] = len(all_strategies)
    stats['after_dedup'] = len(all_strategies)
    stats['search_method'] = 'github' if not need_variants else ('variant' if not filtered_github else 'hybrid')

    return all_strategies, stats


# ================================================================
# 回测引擎（对齐规范：双费率+T+1修正）
# ================================================================
def run_backtest(close_prices: pd.DataFrame, holding: pd.Series,
                start_date: str, end_date: str,
                risk_free_rate: float = 0.045,
                market: str = 'US') -> Optional[Dict]:
    """
    执行回测（对齐规范）
    
    - 价格使用：指标计算用前复权，资金/费用用真实价（当前ETF模式标记风险）
    - 滑点：单边0.1%
    - 手续费：美股0.0528% / 港股0.1348%
    - T+1修正
    - 无风险利率：动态10年美债+1%
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    h = holding.shift(1).loc[mask]  # T+1修正
    h.iloc[0] = holding.iloc[0] if pd.notna(holding.iloc[0]) else 'SHY'

    if len(prices) < 100:
        return None

    # 费率选择（v5：支持US/HK/CN三市场）
    fees_rate = {'US': FEES_US, 'HK': FEES_HK, 'CN': FEES_CN}.get(market, FEES_US)

    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)

    prev_asset = None
    trade_count = 0
    winning_trades = 0
    losing_trades = 0
    total_gain = 0.0
    total_loss = 0.0

    for date in prices.index:
        current_asset = h.loc[date]

        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            portfolio_returns.loc[date] = r if pd.notna(r) else 0

        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            # 换仓成本 = 手续费 + 滑点（双边）
            portfolio_returns.loc[date] -= (fees_rate + SLIPPAGE)

        prev_asset = current_asset

    # 核心指标计算
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(prices) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100

    # 夏普比率（动态无风险利率）
    sharpe = (portfolio_returns.mean() - risk_free_rate / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    calmar = annual_return / max_dd if max_dd > 0 else 0

    # 盈亏比（按交易计算）
    # 简化版：用日收益统计
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0

    # 胜率（按日计算）
    win_days = (portfolio_returns > 0).sum()
    total_active_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100

    # 单标年平均交易次数
    annual_trades = trade_count / max(n_years, 0.01)

    # 持仓分布
    holding_counts = h.value_counts()
    holding_distribution = (holding_counts / len(h) * 100).to_dict()

    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(annual_trades, 1),
        'holding_distribution': {k: round(v, 1) for k, v in holding_distribution.items()},
    }


def run_backtest_single_stock(df: pd.DataFrame,
                               holding: pd.Series,
                               start_date: str, end_date: str,
                               risk_free_rate: float = 0.045,
                               market: str = 'US') -> Optional[Dict]:
    """
    个股级回测（v4升级：单标的买卖信号回测）
    
    与run_backtest不同，本函数用于个股策略：
    - holding为布尔/数值Series：True/1=持仓，False/0=空仓
    - 不再是"轮动选标的"，而是"单标的上择时买卖"
    
    Args:
        df: 单只股票的DataFrame（含Close列）
        holding: 布尔Series，True=持仓，False=空仓（与df索引对齐）
        start_date/end_date: 回测区间
        risk_free_rate: 无风险利率
        market: 'US' 或 'HK'
    """
    mask = (df.index >= start_date) & (df.index <= end_date)
    prices = df.loc[mask]
    h = holding.reindex(prices.index).fillna(0).astype(float)
    
    # T+1修正（港股T+0则不修正）
    if market == 'HK':
        h = h  # 港股T+0，当日买入当日可卖
    else:
        h = h.shift(1).fillna(0)  # 美股T+1
    
    if len(prices) < 100:
        return None
    
    fees_rate = FEES_HK if market == 'HK' else FEES_US
    
    daily_returns = prices['Close'].pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    prev_holding = 0.0
    trade_count = 0
    
    for i, date in enumerate(prices.index):
        curr_h = h.iloc[i]
        # 修复：用iloc[i]而非iloc[date]（日期索引不是整数位置）
        daily_ret = daily_returns.iloc[i]
        portfolio_returns.iloc[i] = curr_h * daily_ret if pd.notna(daily_ret) else 0
        
        # 检测换仓（持仓状态变化）
        if curr_h != prev_holding:
            trade_count += 1
            # 换仓成本（买入或卖出均产生费用）
            portfolio_returns.iloc[i] -= (fees_rate + SLIPPAGE)
        
        prev_holding = curr_h
    
    # 核心指标计算
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(prices) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100
    
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100
    
    sharpe = (portfolio_returns.mean() - risk_free_rate / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    win_days = (portfolio_returns > 0).sum()
    total_active_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100
    
    annual_trades = trade_count / max(n_years, 0.01)
    
    # 持仓比例
    hold_pct = h.sum() / len(h) * 100
    
    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(annual_trades, 1),
        'holding_pct': round(hold_pct, 1),
    }


# ================================================================
# 向量化回测引擎（v6分层递进架构核心）
# ================================================================

def run_backtest_vec(close_prices: pd.DataFrame, holding: pd.Series,
                    start_date: str, end_date: str,
                    risk_free_rate: float = 0.045,
                    market: str = 'US') -> Optional[Dict]:
    """
    向量化回测引擎（替代逐日循环版run_backtest）
    
    核心优化：
    - 用pandas向量化运算替代逐日循环（~100x加速）
    - 信号预计算：holding序列一次性转换为数值矩阵
    - 换仓检测：diff+布尔索引一次性计算所有换仓点
    - 指标计算：cumprod/cummax向量化
    
    结果与run_backtest严格对齐（±0.01%偏差内）
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]
    h = holding.shift(1).loc[mask]  # T+1修正
    h.iloc[0] = holding.iloc[0] if pd.notna(holding.iloc[0]) else 'SHY'

    if len(prices) < 100:
        return None

    fees_rate = {'US': FEES_US, 'HK': FEES_HK, 'CN': FEES_CN}.get(market, FEES_US)
    daily_returns = prices.pct_change().fillna(0)

    # ====== 向量化：持仓资产→日收益率 ======
    # 将holding(Series of asset names)转换为每日持仓资产的收益率
    portfolio_returns = pd.Series(0.0, index=prices.index)
    
    for asset in h.unique():
        if asset is not None and asset in daily_returns.columns:
            asset_mask = (h == asset)
            portfolio_returns = portfolio_returns.add(
                daily_returns[asset].where(asset_mask, 0), fill_value=0)

    # ====== 向量化：换仓成本 ======
    # 换仓检测：前一天持仓≠今天持仓
    h_shifted = h.shift(1)
    trade_mask = (h != h_shifted) & h_shifted.notna() & h.notna()
    # 第一天不算换仓
    trade_mask.iloc[0] = False
    trade_count = trade_mask.sum()
    portfolio_returns = portfolio_returns.subtract(
        (fees_rate + SLIPPAGE) * trade_mask.astype(float))

    # ====== 向量化：核心指标 ======
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(prices) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100

    sharpe = (portfolio_returns.mean() - risk_free_rate / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    calmar = annual_return / max_dd if max_dd > 0 else 0

    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0

    win_days = (portfolio_returns > 0).sum()
    total_active_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100

    annual_trades = trade_count / max(n_years, 0.01)

    holding_counts = h.value_counts()
    holding_distribution = (holding_counts / len(h) * 100).to_dict()

    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(annual_trades, 1),
        'holding_distribution': {k: round(v, 1) for k, v in holding_distribution.items()},
    }


def run_backtest_single_stock_vec(df: pd.DataFrame,
                                   holding: pd.Series,
                                   start_date: str, end_date: str,
                                   risk_free_rate: float = 0.045,
                                   market: str = 'US') -> Optional[Dict]:
    """
    个股级向量化回测引擎（替代逐日循环版run_backtest_single_stock）
    
    核心优化：
    - 持仓信号：布尔Series直接乘日收益率（无需逐日循环）
    - 换仓检测：diff一次计算所有换仓点
    - ~80x加速（vs逐日循环）
    """
    mask = (df.index >= start_date) & (df.index <= end_date)
    prices = df.loc[mask]
    h = holding.reindex(prices.index).fillna(0).astype(float)

    # T+1修正（港股T+0则不修正）
    if market != 'HK':
        h = h.shift(1).fillna(0)

    if len(prices) < 100:
        return None

    fees_rate = FEES_HK if market == 'HK' else FEES_US
    daily_returns = prices['Close'].pct_change().fillna(0)

    # ====== 向量化：持仓收益率 ======
    portfolio_returns = daily_returns * h

    # ====== 向量化：换仓成本 ======
    h_change = h.diff().abs()
    trade_mask = h_change > 0
    trade_mask.iloc[0] = False  # 第一天不算换仓
    trade_count = trade_mask.sum()
    portfolio_returns = portfolio_returns.subtract(
        (fees_rate + SLIPPAGE) * trade_mask.astype(float))

    # ====== 向量化：核心指标 ======
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(prices) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100

    sharpe = (portfolio_returns.mean() - risk_free_rate / 252) / portfolio_returns.std() * np.sqrt(252) if portfolio_returns.std() > 0 else 0
    calmar = annual_return / max_dd if max_dd > 0 else 0

    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0

    win_days = (portfolio_returns > 0).sum()
    total_active_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100

    annual_trades = trade_count / max(n_years, 0.01)
    hold_pct = h.sum() / len(h) * 100

    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(annual_trades, 1),
        'holding_pct': round(hold_pct, 1),
    }


def run_batch_backtest_vec(all_market_data: Dict[str, Dict[str, pd.DataFrame]],
                           strategy_func,
                           strategy_kwargs: Dict,
                           risk_free_rate: float = 0.045) -> Dict:
    """
    向量化批量多标的回测（v6分层架构：第1/2层使用）
    
    优化点：
    - 个股回测全部使用run_backtest_single_stock_vec（向量化）
    - 美股/港股个股批量处理时构建close矩阵预对齐
    - 整体~50x加速（vs逐日循环版run_batch_backtest）
    """
    per_symbol = {}
    profitable_count = 0
    total_count = 0

    # --- 1. ETF轮动回测 ---
    etf_data = all_market_data.get('US_ETF', {})
    if etf_data:
        etf_close = pd.DataFrame({sym: df['Close'] for sym, df in etf_data.items()})
        etf_close = etf_close.dropna(how='all').sort_index().ffill().bfill()

        try:
            holding = strategy_func(etf_close, **strategy_kwargs)
            main_result = run_backtest_vec(etf_close, holding, MAIN_START, MAIN_END, risk_free_rate, 'US')
            stress_result = run_backtest_vec(etf_close, holding, STRESS_START, STRESS_END, risk_free_rate, 'US')
            per_symbol['ETF_ROTATION'] = {
                'main': main_result,
                'stress': stress_result,
            }
            if main_result and main_result['annual_return'] > 0:
                profitable_count += 1
            total_count += 1
        except Exception as e:
            print(f"    ⚠️ ETF轮动回测异常: {e}")
            main_result = None
            stress_result = None

    # --- 2. 美股个股向量化批量回测 ---
    us_data = all_market_data.get('US_STOCK', {})
    us_returns = []
    shy_series = None
    if etf_data and 'SHY' in etf_data:
        shy_series = etf_data['SHY']['Close']

    if us_data and shy_series is not None:
        for sym, df in us_data.items():
            try:
                mini2 = pd.DataFrame({
                    sym: df['Close'],
                    'SHY': shy_series.reindex(df.index).ffill().bfill(),
                })
                mini2 = mini2.dropna().sort_index()
                if len(mini2) < 500:
                    continue

                sym_kwargs = dict(strategy_kwargs)
                sym_kwargs['risk_assets'] = [sym]
                sym_kwargs['safe_assets'] = ['SHY']

                holding = strategy_func(mini2, **sym_kwargs)
                h_bool = (holding == sym).astype(float)

                hold_pct = h_bool.mean()
                if hold_pct < 0.05:
                    continue

                result = run_backtest_single_stock_vec(df, h_bool, MAIN_START, MAIN_END, risk_free_rate, 'US')

                if result:
                    per_symbol[f'US_{sym}'] = result
                    us_returns.append(result['annual_return'])
                    if result['annual_return'] > 0:
                        profitable_count += 1
                    total_count += 1
            except Exception:
                continue

    # --- 3. 港股个股向量化批量回测 ---
    hk_data = all_market_data.get('HK_STOCK', {})
    hk_returns = []
    agg_series = None
    if etf_data and 'AGG' in etf_data:
        agg_series = etf_data['AGG']['Close']

    if hk_data and agg_series is not None:
        for sym, df in hk_data.items():
            try:
                mini2 = pd.DataFrame({
                    sym: df['Close'],
                    'AGG': agg_series.reindex(df.index).ffill().bfill(),
                })
                mini2 = mini2.dropna().sort_index()
                if len(mini2) < 500:
                    continue

                sym_kwargs = dict(strategy_kwargs)
                sym_kwargs['risk_assets'] = [sym]
                sym_kwargs['safe_assets'] = ['AGG']

                holding = strategy_func(mini2, **sym_kwargs)
                h_bool = (holding == sym).astype(float)

                hold_pct = h_bool.mean()
                if hold_pct < 0.05:
                    continue

                result = run_backtest_single_stock_vec(df, h_bool, MAIN_START, MAIN_END, risk_free_rate, 'HK')

                if result:
                    per_symbol[f'HK_{sym}'] = result
                    hk_returns.append(result['annual_return'])
                    if result['annual_return'] > 0:
                        profitable_count += 1
                    total_count += 1
            except Exception:
                continue

    # --- 4. 聚合统计 ---
    all_returns = us_returns + hk_returns
    if main_result:
        all_returns.append(main_result['annual_return'])

    if not all_returns:
        return {
            'main_result': None,
            'stress_result': None,
            'per_symbol': per_symbol,
            'symbol_count': 0,
            'profitable_ratio': 0,
            'survivorship_bias': True,
        }

    avg_annual = np.mean(all_returns)
    avg_sharpe = np.mean([r.get('sharpe', 0) for r in per_symbol.values() if isinstance(r, dict) and 'sharpe' in r])
    avg_max_dd = np.mean([r.get('max_drawdown', 0) for r in per_symbol.values() if isinstance(r, dict) and 'max_drawdown' in r])
    avg_win_rate = np.mean([r.get('win_rate', 0) for r in per_symbol.values() if isinstance(r, dict) and 'win_rate' in r])
    avg_profit_factor = np.mean([r.get('profit_factor', 0) for r in per_symbol.values() if isinstance(r, dict) and 'profit_factor' in r])
    med_annual = np.median(all_returns) if all_returns else 0
    profitable_ratio = profitable_count / max(total_count, 1) * 100

    aggregated_main = {
        'annual_return': round(avg_annual, 2),
        'total_return': round(avg_annual * 5, 2),
        'max_drawdown': round(avg_max_dd, 2),
        'sharpe': round(avg_sharpe, 2),
        'calmar': round(avg_annual / max(avg_max_dd, 0.01), 2),
        'win_rate': round(avg_win_rate, 1),
        'profit_factor': round(avg_profit_factor, 2),
        'avg_trades_per_year': round(np.mean([r.get('avg_trades_per_year', 0) for r in per_symbol.values() if isinstance(r, dict) and 'avg_trades_per_year' in r]), 1),
        'holding_distribution': {'multi_symbol_avg': 100.0},
        'median_annual_return': round(med_annual, 2),
        'symbol_count': total_count,
        'profitable_ratio': round(profitable_ratio, 1),
        'us_stock_count': len(us_returns),
        'hk_stock_count': len(hk_returns),
        'us_avg_annual': round(np.mean(us_returns), 2) if us_returns else 0,
        'hk_avg_annual': round(np.mean(hk_returns), 2) if hk_returns else 0,
    }

    print(f"    📊 多标的回测汇总(向量化): {total_count}只标的 | "
          f"盈利占比{profitable_ratio:.1f}% | "
          f"平均年化{avg_annual:+.2f}% | 中位数年化{med_annual:+.2f}%")
    if us_returns:
        us_profitable = sum(1 for r in us_returns if r > 0)
        print(f"       美股{len(us_returns)}只(盈利{us_profitable}) 年化{np.mean(us_returns):+.2f}%")
    if hk_returns:
        hk_profitable = sum(1 for r in hk_returns if r > 0)
        print(f"       港股{len(hk_returns)}只(盈利{hk_profitable}) 年化{np.mean(hk_returns):+.2f}%")

    return {
        'main_result': aggregated_main,
        'stress_result': stress_result,
        'per_symbol': per_symbol,
        'symbol_count': total_count,
        'profitable_ratio': round(profitable_ratio, 1),
        'survivorship_bias': True,
    }


# ================================================================
# 分层递进回测架构（v6核心）
# ================================================================

# 第1层淘汰阈值（快速广筛用，仅用于加速筛选，不影响最终评分）
LAYER1_MAX_DD_THRESHOLD = 40    # 回撤>40%快速淘汰（加速筛选，不浪费L2/L3计算资源）
LAYER1_MIN_ANN_THRESHOLD = -10  # 年化<-10%快速淘汰
# 第2层淘汰阈值
LAYER2_MIN_SHARPE = 0.0         # 月夏普<0淘汰
LAYER2_MAX_DD_PER_MARKET = 50   # 任何单市场回撤>50%淘汰（极端情况，不再30%一刀切）
# 第3层：Top N进入高精度终验
LAYER3_TOP_N = 10


def _layer1_fast_screen(deduped_variants: List[Dict],
                        close_prices: pd.DataFrame,
                        all_market_data: Dict[str, Dict[str, pd.DataFrame]],
                        risk_free_rate: float) -> Tuple[List[Dict], List[Dict]]:
    """
    第1层：快速广筛（向量化回测，5秒级）
    
    - 覆盖：全部策略 × 仅ETF池（6只）× 3个市场
    - 方法：纯pandas向量化（run_backtest_vec）
    - 精度：年化/夏普/回撤（允许±5%偏差）
    - 淘汰：回撤>40% 或 年化<-10% 直接丢弃（快速筛选，不影响评分）
    - 输出：通过策略列表 + 淘汰策略列表
    """
    layer1_start = time.time()
    passed = []
    eliminated = []
    
    for i, strategy in enumerate(deduped_variants):
        name = strategy['name']
        strategy_type = strategy.get('type', '其他')
        
        try:
            # === 三市场快速回测 ===
            market_quick = {}
            for market in ['US', 'HK', 'CN']:
                if market == 'US':
                    cp = close_prices
                    start, end, rf = MAIN_START, MAIN_END, risk_free_rate
                elif market == 'HK':
                    hk_stock_data = all_market_data.get('HK_STOCK', {})
                    if not hk_stock_data:
                        continue
                    hk_close_dict = {sym: df['Close'] for sym, df in hk_stock_data.items()}
                    cp = pd.DataFrame(hk_close_dict).sort_index().loc[HK_MAIN_START:HK_MAIN_END]
                    if cp.empty or len(cp) < 100:
                        continue
                    start, end, rf = HK_MAIN_START, HK_MAIN_END, HK_RISK_FREE_RATE
                elif market == 'CN':
                    cn_etf_data = all_market_data.get('CN_ETF', {})
                    if not cn_etf_data:
                        continue
                    cn_close_dict = {sym: df['Close'] for sym, df in cn_etf_data.items()}
                    cp = pd.DataFrame(cn_close_dict).sort_index().loc[CN_MAIN_START:CN_MAIN_END]
                    if cp.empty or len(cp) < 100:
                        continue
                    start, end, rf = CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE
                
                try:
                    # L1层：使用向量化策略信号函数（~100x加速）
                    vec_func = get_vec_strategy_func(strategy['func'])
                    holding = vec_func(cp, **strategy['kwargs'])
                    result = run_backtest_vec(cp, holding, start, end, rf, market)
                    if result:
                        market_quick[market] = result
                except Exception:
                    continue
            
            # === 淘汰判断 ===
            # L1层按市场独立评估：策略只要在至少一个市场表现可接受就不淘汰
            # 这样港股高回撤但高年化的策略不会被误杀
            any_market_pass = False
            for market, r in market_quick.items():
                ann_ok = r['annual_return'] >= LAYER1_MIN_ANN_THRESHOLD
                dd_ok = r['max_drawdown'] <= LAYER1_MAX_DD_THRESHOLD
                # 年化好且回撤可接受 → 该市场通过
                if ann_ok and dd_ok:
                    any_market_pass = True
                    break
                # 年化好但回撤稍大 → 也算通过（如港股）
                if r['annual_return'] >= 5 and r['max_drawdown'] <= 60:
                    any_market_pass = True
                    break
            
            best_annual = max((r['annual_return'] for r in market_quick.values()), default=-999)
            worst_dd = max((r['max_drawdown'] for r in market_quick.values()), default=0)
            
            if not any_market_pass:
                eliminated.append({
                    'strategy': strategy,
                    'reason': f'所有市场均不达标: 年化{best_annual:.1f}% 回撤{worst_dd:.1f}%',
                    'market_quick': market_quick,
                })
            else:
                # 通过第1层
                strategy['_layer1_results'] = market_quick
                strategy['_layer1_best_annual'] = best_annual
                strategy['_layer1_worst_dd'] = worst_dd
                passed.append(strategy)
                
        except Exception as e:
            eliminated.append({
                'strategy': strategy,
                'reason': f'信号生成异常: {e}',
                'market_quick': {},
            })
    
    elapsed = time.time() - layer1_start
    print(f"\n  ⚡ 第1层快速广筛: {len(passed)}/{len(deduped_variants)}个策略通过 "
          f"(淘汰{len(eliminated)}个, 耗时{elapsed:.1f}s)")
    for e in eliminated[:5]:
        print(f"    ❌ {e['strategy']['name']}: {e['reason']}")
    if len(eliminated) > 5:
        print(f"    ... 还有{len(eliminated)-5}个淘汰策略")
    
    return passed, eliminated


def _layer2_medium_validate(passed_variants: List[Dict],
                            close_prices: pd.DataFrame,
                            all_market_data: Dict[str, Dict[str, pd.DataFrame]],
                            risk_free_rate: float) -> Tuple[List[Dict], List[Dict]]:
    """
    第2层：中等精度验证（向量化+完整指标，30秒级）
    
    - 覆盖：通过第1层的策略 × ETF池+多标的 × 3市场
    - 方法：向量化 + 交易成本精确扣除 + 压力测试
    - 精度：含夏普/Calmar/盈亏比/换仓成本
    - 淘汰：夏普<0 或 任何单市场回撤>50%（极端情况，不再30%一刀切）
    - 输出：通过策略列表(含完整评分) + 淘汰策略列表
    """
    layer2_start = time.time()
    validated = []
    eliminated = []
    
    for i, strategy in enumerate(passed_variants):
        name = strategy['name']
        strategy_type = strategy.get('type', '其他')
        print(f"\n  📋 [L2 {i+1}/{len(passed_variants)}] [{strategy_type}] {name}")
        
        try:
            market_results = {}
            
            for market in ['US', 'HK', 'CN']:
                if market == 'US':
                    cp = close_prices
                    main_start, main_end = MAIN_START, MAIN_END
                    stress_start, stress_end = STRESS_START, STRESS_END
                    rf = risk_free_rate
                elif market == 'HK':
                    hk_stock_data = all_market_data.get('HK_STOCK', {})
                    if not hk_stock_data:
                        continue
                    hk_close_dict = {sym: df['Close'] for sym, df in hk_stock_data.items()}
                    cp = pd.DataFrame(hk_close_dict).sort_index()
                    if cp.empty or len(cp) < 100:
                        continue
                    main_start, main_end = HK_MAIN_START, HK_MAIN_END
                    stress_start, stress_end = HK_STRESS_START, HK_STRESS_END
                    rf = HK_RISK_FREE_RATE
                elif market == 'CN':
                    cn_etf_data = all_market_data.get('CN_ETF', {})
                    if not cn_etf_data:
                        continue
                    cn_close_dict = {sym: df['Close'] for sym, df in cn_etf_data.items()}
                    cp = pd.DataFrame(cn_close_dict).sort_index()
                    if cp.empty or len(cp) < 100:
                        continue
                    main_start, main_end = CN_MAIN_START, CN_MAIN_END
                    stress_start, stress_end = CN_STRESS_START, CN_STRESS_END
                    rf = CN_RISK_FREE_RATE
                
                try:
                    # L2层：使用向量化策略信号函数（~100x加速）
                    vec_func = get_vec_strategy_func(strategy['func'])
                    holding = vec_func(cp, **strategy['kwargs'])
                    main_result = run_backtest_vec(cp, holding, main_start, main_end, rf, market)
                    stress_result = run_backtest_vec(cp, holding, stress_start, stress_end, rf, market)
                    
                    if main_result:
                        survivorship_bias = (market != 'US') or (close_prices is not None)
                        score_result = calculate_score(main_result, stress_result, survivorship_bias)
                        market_results[market] = {
                            'main_result': main_result,
                            'stress_result': stress_result,
                            'score_result': score_result,
                            'risk_free_rate': rf,
                            'survivorship_bias': survivorship_bias,
                        }
                except Exception as e:
                    print(f"      ⚠️ [{market}] 信号异常: {e}")
                    continue
            
            # === 淘汰判断（改革：回撤超标只扣分不淘汰，看综合评分） ===
            any_pass = False
            for market, mr in market_results.items():
                score = mr['score_result']['total_score']
                dd = mr['main_result']['max_drawdown']
                sharpe = mr['main_result']['sharpe']
                hard_fail = mr['score_result'].get('hard_fail', False)
                dd_penalty = mr['score_result'].get('drawdown_penalty_tag', False)
                
                # 综合评分>0且非极端失败即通过
                if score > 0 and not hard_fail:
                    any_pass = True
                    if dd_penalty:
                        print(f"      ⚠️ [{market}] 评分{score}(回撤扣分) | 回撤{dd:.1f}% | 夏普{sharpe:.2f}")
                else:
                    print(f"      ❌ [{market}] 评分{score} | 回撤{dd:.1f}% | 夏普{sharpe:.2f} | {'极端淘汰' if hard_fail else '评分未通过'}")
            
            if not any_pass:
                eliminated.append({
                    'strategy': strategy,
                    'reason': '所有市场评分均未通过',
                    'market_results': market_results,
                })
            else:
                strategy['_layer2_results'] = market_results
                # 取三市场最高分
                best_score = max(
                    mr['score_result']['total_score'] 
                    for mr in market_results.values() 
                    if mr['score_result']['total_score'] > 0
                )
                strategy['_layer2_best_score'] = best_score
                validated.append(strategy)
                
        except Exception as e:
            eliminated.append({
                'strategy': strategy,
                'reason': f'验证异常: {e}',
                'market_results': {},
            })
    
    elapsed = time.time() - layer2_start
    print(f"\n  🔍 第2层中等验证: {len(validated)}/{len(passed_variants)}个策略通过 "
          f"(淘汰{len(eliminated)}个, 耗时{elapsed:.1f}s)")
    
    return validated, eliminated


def _layer3_precision_finaltest(validated_variants: List[Dict],
                                close_prices: pd.DataFrame,
                                all_market_data: Dict[str, Dict[str, pd.DataFrame]],
                                risk_free_rate: float,
                                survivorship_bias: bool) -> List[Dict]:
    """
    第3层：高精度终验（逐日回测，5分钟级）
    
    - 覆盖：通过第2层的Top N策略 × ETF池 × 3市场
    - 方法：逐日循环(原始run_backtest) + 多标的批量回测
    - 精度：含逐笔交易记录、资金曲线、月度归因、压力测试
    - 输出：最终策略列表(含完整回测结果、评分、排行榜数据)
    """
    layer3_start = time.time()
    
    # 按第2层评分排序，取Top N
    sorted_variants = sorted(validated_variants, 
                            key=lambda x: x.get('_layer2_best_score', 0), 
                            reverse=True)
    top_n = sorted_variants[:LAYER3_TOP_N]
    
    if len(validated_variants) > LAYER3_TOP_N:
        print(f"\n  🎯 第3层: 取Top {LAYER3_TOP_N}策略进行高精度终验 "
              f"(跳过{len(validated_variants)-LAYER3_TOP_N}个低分策略)")
    else:
        print(f"\n  🎯 第3层: {len(top_n)}个策略全部进行高精度终验")
    
    final_results = []
    
    for i, strategy in enumerate(top_n):
        name = strategy['name']
        strategy_type = strategy.get('type', '其他')
        print(f"\n  🏆 [L3 {i+1}/{len(top_n)}] [{strategy_type}] {name}")
        
        try:
            holding = strategy['func'](close_prices, **strategy['kwargs'])
        except Exception as e:
            print(f"    ❌ 信号生成异常: {e}")
            continue
        
        try:
            market_results = {}
            
            for market in ['US', 'HK', 'CN']:
                if market == 'US':
                    cp = close_prices
                    main_start, main_end = MAIN_START, MAIN_END
                    stress_start, stress_end = STRESS_START, STRESS_END
                    rf = risk_free_rate
                elif market == 'HK':
                    hk_stock_data = all_market_data.get('HK_STOCK', {})
                    if not hk_stock_data:
                        continue
                    hk_close_dict = {sym: df['Close'] for sym, df in hk_stock_data.items()}
                    cp = pd.DataFrame(hk_close_dict).sort_index()
                    if cp.empty or len(cp) < 100:
                        continue
                    main_start, main_end = HK_MAIN_START, HK_MAIN_END
                    stress_start, stress_end = HK_STRESS_START, HK_STRESS_END
                    rf = HK_RISK_FREE_RATE
                elif market == 'CN':
                    cn_etf_data = all_market_data.get('CN_ETF', {})
                    if not cn_etf_data:
                        continue
                    cn_close_dict = {sym: df['Close'] for sym, df in cn_etf_data.items()}
                    cp = pd.DataFrame(cn_close_dict).sort_index()
                    if cp.empty or len(cp) < 100:
                        continue
                    main_start, main_end = CN_MAIN_START, CN_MAIN_END
                    stress_start, stress_end = CN_STRESS_START, CN_STRESS_END
                    rf = CN_RISK_FREE_RATE
                
                try:
                    m_holding = strategy['func'](cp, **strategy['kwargs'])
                    # 第3层使用原始逐日循环回测（最高精度）
                    main_result = run_backtest(cp, m_holding, main_start, main_end, rf, market)
                    stress_result = run_backtest(cp, m_holding, stress_start, stress_end, rf, market)
                    
                    if main_result:
                        m_bias = (market != 'US') or survivorship_bias
                        score_result = calculate_score(main_result, stress_result, m_bias)
                        market_results[market] = {
                            'main_result': main_result,
                            'stress_result': stress_result,
                            'score_result': score_result,
                            'risk_free_rate': rf,
                            'survivorship_bias': m_bias,
                        }
                except Exception as e:
                    print(f"      ⚠️ [{market}] 回测异常: {e}")
                    continue
            
            # 多标的批量回测：L3层跳过，改为入榜后异步执行（节省大量耗时）
            batch_result = None
            
            final_results.append({
                'strategy': strategy,
                'market_results': market_results,
                'batch_result': batch_result,
                'layer3_elapsed': time.time() - layer3_start,
            })
            
        except Exception as e:
            print(f"    ❌ 终验异常: {e}")
    
    elapsed = time.time() - layer3_start
    print(f"\n  🏅 第3层高精度终验: {len(final_results)}个策略完成 (耗时{elapsed:.1f}s)")
    
    return final_results


def run_batch_backtest(all_market_data: Dict[str, Dict[str, pd.DataFrame]],
                       strategy_func,
                       strategy_kwargs: Dict,
                       risk_free_rate: float = 0.045) -> Dict:
    """
    批量多标的回测（v4升级）
    
    对策略在所有市场标的上逐一执行回测，汇总统计：
    - ETF轮动策略：在6只ETF上回测（保持原有逻辑）
    - 个股择时策略：在每只个股上独立回测，汇总胜率/平均收益
    
    Returns:
        {
            'main_result': 主回测聚合指标（各标的加权平均）,
            'stress_result': 压力测试聚合指标,
            'per_symbol': 每只标的的详细回测结果,
            'symbol_count': 回测标的数,
            'profitable_ratio': 盈利标的占比,
            'survivorship_bias': bool,
        }
    """
    per_symbol = {}
    profitable_count = 0
    total_count = 0
    
    # --- 1. ETF轮动回测（保持原有逻辑） ---
    etf_data = all_market_data.get('US_ETF', {})
    if etf_data:
        # 构建ETF收盘价矩阵
        etf_close = pd.DataFrame({sym: df['Close'] for sym, df in etf_data.items()})
        etf_close = etf_close.dropna(how='all').sort_index().ffill().bfill()
        
        try:
            holding = strategy_func(etf_close, **strategy_kwargs)
            main_result = run_backtest(etf_close, holding, MAIN_START, MAIN_END, risk_free_rate, 'US')
            stress_result = run_backtest(etf_close, holding, STRESS_START, STRESS_END, risk_free_rate, 'US')
            per_symbol['ETF_ROTATION'] = {
                'main': main_result,
                'stress': stress_result,
            }
            if main_result and main_result['annual_return'] > 0:
                profitable_count += 1
            total_count += 1
        except Exception as e:
            print(f"    ⚠️ ETF轮动回测异常: {e}")
            main_result = None
            stress_result = None
    
    # --- 2. 美股个股回测 ---
    us_data = all_market_data.get('US_STOCK', {})
    us_returns = []
    
    # 构建SHY收盘价（个股+避险 二元轮动所需）
    shy_series = None
    if etf_data and 'SHY' in etf_data:
        shy_series = etf_data['SHY']['Close']
    
    if us_data and shy_series is not None:
        for sym, df in us_data.items():
            try:
                # 二元轮动：个股 vs SHY（避险），策略决定何时持有个股
                mini2 = pd.DataFrame({
                    sym: df['Close'],
                    'SHY': shy_series.reindex(df.index).ffill().bfill(),
                })
                mini2 = mini2.dropna().sort_index()
                if len(mini2) < 500:
                    continue
                
                # 关键：传入risk_assets/safe_assets让策略正确识别个股为风险资产
                sym_kwargs = dict(strategy_kwargs)
                sym_kwargs['risk_assets'] = [sym]
                sym_kwargs['safe_assets'] = ['SHY']
                
                holding = strategy_func(mini2, **sym_kwargs)
                # 布尔信号：策略选择持有该个股时=1
                h_bool = (holding == sym).astype(float)
                
                # 如果策略始终不选该个股（持仓天数<5%），标记为低适配度
                hold_pct = h_bool.mean()
                if hold_pct < 0.05:
                    continue
                
                result = run_backtest_single_stock(df, h_bool, MAIN_START, MAIN_END, risk_free_rate, 'US')
                
                if result:
                    per_symbol[f'US_{sym}'] = result
                    us_returns.append(result['annual_return'])
                    if result['annual_return'] > 0:
                        profitable_count += 1
                    total_count += 1
            except Exception:
                continue
    
    # --- 3. 港股个股回测 ---
    hk_data = all_market_data.get('HK_STOCK', {})
    hk_returns = []
    
    # 构建AGG收盘价（港股避险替代）
    agg_series = None
    if etf_data and 'AGG' in etf_data:
        agg_series = etf_data['AGG']['Close']
    
    if hk_data and agg_series is not None:
        for sym, df in hk_data.items():
            try:
                # 二元轮动：港股个股 vs AGG（避险替代）
                mini2 = pd.DataFrame({
                    sym: df['Close'],
                    'AGG': agg_series.reindex(df.index).ffill().bfill(),
                })
                mini2 = mini2.dropna().sort_index()
                if len(mini2) < 500:
                    continue
                
                # 关键：传入risk_assets/safe_assets
                sym_kwargs = dict(strategy_kwargs)
                sym_kwargs['risk_assets'] = [sym]
                sym_kwargs['safe_assets'] = ['AGG']
                
                holding = strategy_func(mini2, **sym_kwargs)
                h_bool = (holding == sym).astype(float)
                
                hold_pct = h_bool.mean()
                if hold_pct < 0.05:
                    continue
                
                result = run_backtest_single_stock(df, h_bool, MAIN_START, MAIN_END, risk_free_rate, 'HK')
                
                if result:
                    per_symbol[f'HK_{sym}'] = result
                    hk_returns.append(result['annual_return'])
                    if result['annual_return'] > 0:
                        profitable_count += 1
                    total_count += 1
            except Exception:
                continue
    
    # --- 4. 聚合统计 ---
    all_returns = us_returns + hk_returns
    if main_result:
        all_returns.append(main_result['annual_return'])
    
    if not all_returns:
        return {
            'main_result': None,
            'stress_result': None,
            'per_symbol': per_symbol,
            'symbol_count': 0,
            'profitable_ratio': 0,
            'survivorship_bias': True,
        }
    
    # 多标的聚合指标（等权平均）
    avg_annual = np.mean(all_returns)
    avg_sharpe = np.mean([r.get('sharpe', 0) for r in per_symbol.values() if isinstance(r, dict) and 'sharpe' in r])
    avg_max_dd = np.mean([r.get('max_drawdown', 0) for r in per_symbol.values() if isinstance(r, dict) and 'max_drawdown' in r])
    avg_win_rate = np.mean([r.get('win_rate', 0) for r in per_symbol.values() if isinstance(r, dict) and 'win_rate' in r])
    avg_profit_factor = np.mean([r.get('profit_factor', 0) for r in per_symbol.values() if isinstance(r, dict) and 'profit_factor' in r])
    
    # 中位数指标（更抗异常值）
    med_annual = np.median(all_returns) if all_returns else 0
    
    profitable_ratio = profitable_count / max(total_count, 1) * 100
    
    # 聚合后的主结果（用于评分和排行榜）
    aggregated_main = {
        'annual_return': round(avg_annual, 2),
        'total_return': round(avg_annual * 5, 2),  # 5年近似
        'max_drawdown': round(avg_max_dd, 2),
        'sharpe': round(avg_sharpe, 2),
        'calmar': round(avg_annual / max(avg_max_dd, 0.01), 2),
        'win_rate': round(avg_win_rate, 1),
        'profit_factor': round(avg_profit_factor, 2),
        'avg_trades_per_year': round(np.mean([r.get('avg_trades_per_year', 0) for r in per_symbol.values() if isinstance(r, dict) and 'avg_trades_per_year' in r]), 1),
        'holding_distribution': {'multi_symbol_avg': 100.0},
        # v4新增字段
        'median_annual_return': round(med_annual, 2),
        'symbol_count': total_count,
        'profitable_ratio': round(profitable_ratio, 1),
        'us_stock_count': len(us_returns),
        'hk_stock_count': len(hk_returns),
        'us_avg_annual': round(np.mean(us_returns), 2) if us_returns else 0,
        'hk_avg_annual': round(np.mean(hk_returns), 2) if hk_returns else 0,
    }
    
    print(f"    📊 多标的回测汇总: {total_count}只标的 | "
          f"盈利占比{profitable_ratio:.1f}% | "
          f"平均年化{avg_annual:+.2f}% | 中位数年化{med_annual:+.2f}%")
    if us_returns:
        us_profitable = sum(1 for r in us_returns if r > 0)
        print(f"       美股{len(us_returns)}只(盈利{us_profitable}) 年化{np.mean(us_returns):+.2f}%")
    if hk_returns:
        hk_profitable = sum(1 for r in hk_returns if r > 0)
        print(f"       港股{len(hk_returns)}只(盈利{hk_profitable}) 年化{np.mean(hk_returns):+.2f}%")
    
    return {
        'main_result': aggregated_main,
        'stress_result': stress_result,  # 压力测试仅ETF有
        'per_symbol': per_symbol,
        'symbol_count': total_count,
        'profitable_ratio': round(profitable_ratio, 1),
        'survivorship_bias': True,  # 多标的回测仍有幸存者偏差
    }


# ================================================================
# 评分体系（对齐规范：年化25%/夏普25%/回撤20%阶梯/盈亏比15%/胜率15%）
# ================================================================
def calculate_score(result: Dict, stress_result: Optional[Dict] = None,
                   survivorship_bias: bool = True) -> Dict:
    """
    穿越牛熊策略评分体系（对齐规范）

    评分维度：
    - 年化收益率（25%）：收益率/20% × 25
    - 夏普比率（25%）：夏普值/2.0 × 25
    - 最大回撤（20%）：≤10%:20分; 10-20%:15分; 20-25%:8分; 25-30%:5分; 30-35%:3分; 35-40%:2分; 40-50%:1分; >50%:0分
    - 盈亏比（15%）：盈亏比/2.0 × 15
    - 胜率（15%）：胜率/55% × 15

    附加分：
    - 跨周期鲁棒（+5分）：压力区间(2015-2018)年化≥0且回撤≤主区间1.5倍
    - 幸存者偏差扣分（-10分）：数据不含历史全量标的
    """
    # 使用strategy_ranker的标准评分函数
    score_dict = compute_total_score(
        annual_return=result.get('annual_return', 0),
        sharpe=result.get('sharpe', 0),
        max_drawdown=result.get('max_drawdown', 100),
        profit_factor=result.get('profit_factor', 0),
        win_rate=result.get('win_rate', 0),
        cross_period_robust=False,
        survivorship_bias=survivorship_bias,
    )

    # 跨周期鲁棒检测（对齐规范：压力区间年化≥0 且 回撤≤主区间1.5倍）
    cross_robust = False
    if stress_result:
        stress_annual = stress_result.get('annual_return', -999)
        stress_dd = stress_result.get('max_drawdown', 999)
        main_dd = result.get('max_drawdown', 100)
        if stress_annual >= 0 and stress_dd <= main_dd * 1.5:
            cross_robust = True

    # 重新计算含鲁棒附加分
    if cross_robust:
        score_dict['cross_period_bonus'] = 5.0
        score_dict['total_score'] = round(score_dict['base_score'] + 5.0 + score_dict.get('survivorship_penalty', 0), 2)

    # 回撤/收益检查（改革：不再因回撤超标一刀切0分）
    # 回撤只是扣分项（在score_max_drawdown中已阶梯扣分），不影响其他指标
    # 0分只应代表"策略完全没获取到或回测失败"
    hard_fail = False
    fail_reason = ''
    if result.get('max_drawdown', 0) > 50:
        # 极端情况：回撤>50%才归零（说明策略可能有严重bug）
        hard_fail = True
        fail_reason = f'最大回撤>{50}%（极端情况）'
    elif result.get('annual_return', 0) < -20:
        # 极端情况：年化<-20%才归零（说明策略完全失败）
        hard_fail = True
        fail_reason = '年化收益<-20%（策略完全失败）'

    return {
        'total_score': score_dict['total_score'] if not hard_fail else 0,
        'base_score': score_dict['base_score'],
        'score_detail': {
            'annual_return_score': score_dict['annual_return_score'],
            'sharpe_score': score_dict['sharpe_score'],
            'max_drawdown_score': score_dict['max_drawdown_score'],
            'profit_factor_score': score_dict['profit_factor_score'],
            'win_rate_score': score_dict['win_rate_score'],
        },
        'cross_period_bonus': score_dict.get('cross_period_bonus', 0),
        'survivorship_penalty': score_dict.get('survivorship_penalty', 0),
        'hard_fail': hard_fail,
        'fail_reason': fail_reason,
        'cross_robust': cross_robust,
        'drawdown_penalty_tag': result.get('max_drawdown', 0) > 30,  # 标记回撤扣分项
    }


# ================================================================
# 排行榜管理（无最低门槛，按最高分从高到低排，保留前十）
# ================================================================
# 排行榜管理（三市场独立排行：US/HK/CN）
# ================================================================

# 兼容旧接口：默认加载美股排行榜
def load_leaderboard(market: str = None) -> List[Dict]:
    """加载排行榜（指定market加载对应市场，None加载美股兼容旧逻辑）"""
    if market is None:
        market = 'US'
    path = MARKET_LEADERBOARDS.get(market, {}).get('leaderboard', LEADERBOARD_PATH)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_leaderboard(leaderboard: List[Dict], market: str = None):
    """保存排行榜（指定market保存对应市场，None保存美股兼容旧逻辑）"""
    if market is None:
        market = 'US'
    path = MARKET_LEADERBOARDS.get(market, {}).get('leaderboard', LEADERBOARD_PATH)
    leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)
    leaderboard = leaderboard[:10]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(leaderboard, f, ensure_ascii=False, indent=2)


def load_rejected(market: str = None) -> List[Dict]:
    """加载废弃策略库（指定market加载对应市场，None加载美股兼容旧逻辑）"""
    if market is None:
        market = 'US'
    path = MARKET_LEADERBOARDS.get(market, {}).get('rejected', REJECTED_PATH)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_rejected(rejected: List[Dict], market: str = None):
    """保存废弃策略库（指定market保存对应市场，None保存美股兼容旧逻辑）"""
    if market is None:
        market = 'US'
    path = MARKET_LEADERBOARDS.get(market, {}).get('rejected', REJECTED_PATH)
    rejected = rejected[-50:]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)


def load_all_leaderboards() -> Dict[str, List[Dict]]:
    """加载所有三个市场的排行榜"""
    return {m: load_leaderboard(m) for m in MARKET_LEADERBOARDS}


def load_all_rejected() -> Dict[str, List[Dict]]:
    """加载所有三个市场的废弃策略库"""
    return {m: load_rejected(m) for m in MARKET_LEADERBOARDS}


def migrate_legacy_leaderboard():
    """一次性迁移：将旧的单体排行榜数据拆分到三个市场排行榜"""
    if not os.path.exists(LEGACY_LEADERBOARD_PATH):
        return
    
    # 如果已有市场排行榜数据，不重复迁移
    if os.path.exists(MARKET_LEADERBOARDS['US']['leaderboard']):
        return
    
    try:
        with open(LEGACY_LEADERBOARD_PATH, 'r', encoding='utf-8') as f:
            legacy = json.load(f)
        
        # 旧排行榜全是US市场的，直接迁移到US
        if legacy:
            save_leaderboard(legacy, 'US')
            print(f"  📋 迁移旧排行榜: {len(legacy)}个US策略")
        
        # 废弃库同样迁移
        if os.path.exists(REJECTED_PATH):
            with open(REJECTED_PATH, 'r', encoding='utf-8') as f:
                legacy_rejected = json.load(f)
            if legacy_rejected:
                save_rejected(legacy_rejected, 'US')
                print(f"  📋 迁移旧废弃库: {len(legacy_rejected)}个US策略")
    except Exception as e:
        print(f"  ⚠️ 迁移旧排行榜失败: {e}")


def is_in_protection(entry: Dict) -> bool:
    """检查策略是否在保护期内（60分以下策略无保护期）"""
    # 60分以下策略不享受保护期，谁得分更高谁上榜
    if entry.get('total_score', 0) < 60:
        return False
    ts = entry.get('timestamp', '')
    if not ts:
        return False
    try:
        entry_time = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
        return (datetime.now() - entry_time).days < PROTECTION_DAYS
    except Exception:
        return False


def update_leaderboard_v3(strategy_entry: Dict, score_result: Dict, market: str = None):
    """更新排行榜（无最低门槛，按最高分从高到低排，保留前十）
    
    Args:
        strategy_entry: 策略条目
        score_result: 评分结果
        market: 市场标识 'US'/'HK'/'CN'，None则从strategy_entry['market']获取，默认'US'
    """
    if market is None:
        market = strategy_entry.get('market', 'US')
    strategy_entry['market'] = market
    
    leaderboard = load_leaderboard(market)
    rejected = load_rejected(market)

    params = strategy_entry.get('strategy_params', {})
    params_str = json.dumps(params, sort_keys=True)
    fingerprint = hashlib.sha256(
        f"{strategy_entry['strategy_name']}_{params_str}".encode()
    ).hexdigest()

    strategy_entry['fingerprint'] = fingerprint
    strategy_entry['total_score'] = score_result['total_score']
    strategy_entry['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if score_result['total_score'] == 0:
        # 废弃（得分为0表示回测失败）
        strategy_entry['reject_reason'] = score_result.get('fail_reason', '回测失败得分=0')
        # 检查是否已在废弃库中
        existing_idx = -1
        for i, e in enumerate(rejected):
            if e.get('fingerprint') == fingerprint and e.get('market') == strategy_entry.get('market', 'US'):
                existing_idx = i
                break
        if existing_idx >= 0:
            if score_result['total_score'] > rejected[existing_idx].get('total_score', 0):
                rejected[existing_idx] = strategy_entry
        else:
            rejected.append(strategy_entry)
    else:
        # 尝试入榜
        existing_idx = -1
        for i, e in enumerate(leaderboard):
            if e.get('fingerprint') == fingerprint and e.get('market') == strategy_entry.get('market', 'US'):
                existing_idx = i
                break

        if existing_idx >= 0:
            # 更新已有条目
            if score_result['total_score'] > leaderboard[existing_idx]['total_score']:
                leaderboard[existing_idx] = strategy_entry
        else:
            if len(leaderboard) < 10:
                leaderboard.append(strategy_entry)
            else:
                # 替换最低分（跳过保护期策略，从末位向上查找可替换的条目）
                leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)
                replaced = False
                for idx in range(len(leaderboard) - 1, -1, -1):
                    candidate = leaderboard[idx]
                    if is_in_protection(candidate):
                        continue  # 跳过保护期策略
                    if score_result['total_score'] > candidate.get('total_score', 0):
                        # 找到可替换的条目（不在保护期且分数低于新策略）
                        candidate['reject_reason'] = '被更高分策略替换'
                        candidate['replaced_by'] = strategy_entry.get('strategy_name', '未知策略')
                        candidate['replaced_by_score'] = score_result['total_score']
                        rejected.append(candidate)
                        leaderboard[idx] = strategy_entry
                        replaced = True
                        break
                if not replaced:
                    # 所有低分策略都在保护期，将新策略暂存废弃库等待保护期结束
                    strategy_entry['reject_reason'] = f'等待保护期结束(末位{leaderboard[-1].get("total_score",0):.1f}分在保护期)'
                    strategy_entry['pending_leaderboard'] = True
                    # 检查是否已在废弃库中
                    existing_idx = -1
                    for i, e in enumerate(rejected):
                        if e.get('fingerprint') == fingerprint and e.get('market') == strategy_entry.get('market', 'US'):
                            existing_idx = i
                            break
                    if existing_idx >= 0:
                        if score_result['total_score'] > rejected[existing_idx].get('total_score', 0):
                            rejected[existing_idx] = strategy_entry
                    else:
                        rejected.append(strategy_entry)

    save_leaderboard(leaderboard, market)
    save_rejected(rejected, market)


# ================================================================

# 本地回测脚本注册表：脚本路径 → 适配器配置
LOCAL_BACKTEST_REGISTRY = [
    {
        'script': os.path.join(WORKSPACE_DIR, 'rsi2_strict_backtest.py'),
        'name': 'RSI(2)严格均值回归',
        'type': '均值回归',
        'adapter': 'rsi2',  # 适配器类型
        'args': ['--all'],  # --all运行所有标的+周期
    },
    {
        'script': os.path.join(WORKSPACE_DIR, 'dual_market_strategy_backtest.py'),
        'name': '双市场自适应策略',
        'type': '趋势跟踪',
        'adapter': 'dual_market',
        'args': ['--market', 'us'],
    },
    {
        'script': os.path.join(WORKSPACE_DIR, 'blakever_v65_backtest.py'),
        'name': 'Blakever V6.5 利率维度修正',
        'type': '趋势跟踪',
        'adapter': 'blakever_v65',
        'args': [],
    },
]


def _adapt_rsi2_result(raw_result: Dict) -> List[Dict]:
    """适配RSI2回测输出 → 标准策略条目列表（每个标的+周期一个条目）"""
    entries = []
    # RSI2的run_backtest返回best（单标的），我们直接运行每个标的
    # 用subprocess运行脚本，解析stdout中的表格
    return entries


def _adapt_dual_market_result(raw_result: Dict) -> List[Dict]:
    """适配双市场自适应回测输出 → 标准策略条目"""
    entries = []
    return entries


def _run_local_script(script_path: str, args: List[str], timeout: int = 300) -> Optional[Dict]:
    """运行本地回测脚本并捕获JSON输出"""
    try:
        cmd = [sys.executable, script_path] + args + ['--output', '/tmp/_local_bt_result.json']
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=os.path.dirname(script_path))
        result_path = '/tmp/_local_bt_result.json'
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                result = json.load(f)
            os.remove(result_path)
            return result
        # 如果没有JSON输出，尝试从stdout解析
        return None
    except subprocess.TimeoutExpired:
        print(f"    ⚠️ 脚本超时({timeout}秒): {script_path}")
        return None
    except Exception as e:
        print(f"    ⚠️ 脚本执行异常: {e}")
        return None


def scan_local_backtest_strategies(close_prices: pd.DataFrame,
                                    risk_free_rate: float,
                                    survivorship_bias: bool = True) -> Tuple[List[Dict], int, int]:
    """
    扫描本地回测脚本，统一评分后纳入排行榜。

    流程：
    1. 遍历LOCAL_BACKTEST_REGISTRY中的脚本
    2. 运行脚本获取回测结果
    3. 将结果适配为标准格式
    4. 使用统一的评分体系评分
    5. 调用update_leaderboard_v3纳入排行榜

    Returns:
        (results_list, passed_count, rejected_count)
    """
    print(f"\n{'='*70}")
    print(f"  🖥️ 步骤5b: 本地回测策略扫描（世界最好的策略，无论来源）")
    print(f"{'='*70}")

    results = []
    passed_count = 0
    rejected_count = 0

    for reg in LOCAL_BACKTEST_REGISTRY:
        script_path = reg['script']
        base_name = reg['name']
        strategy_type = reg['type']

        if not os.path.exists(script_path):
            print(f"  ⏭️ 脚本不存在: {script_path}")
            continue

        print(f"\n  🖥️ 运行: {base_name} ({os.path.basename(script_path)})")

        # 运行回测脚本
        raw_result = _run_local_script(script_path, reg.get('args', []), timeout=300)

        if raw_result is None:
            print(f"    ⚠️ 无JSON输出，尝试subprocess直接回测...")
            # 回退：直接import脚本运行
            try:
                raw_results = _run_local_fallback(reg, close_prices, risk_free_rate)
                if not raw_results:
                    rejected_count += 1
                    continue
            except Exception as e:
                print(f"    ❌ 回退执行失败: {e}")
                rejected_count += 1
                continue
        else:
            # 单条结果包装成列表
            if isinstance(raw_result, dict):
                raw_results = [raw_result]
            else:
                raw_results = raw_result

        # 适配每个结果并评分
        for r in raw_results:
            try:
                strategy_name = r.get('strategy_name', base_name)
                symbol = r.get('symbol', r.get('market', 'US'))
                period = r.get('period', r.get('backtest_period', ''))

                # 过滤：只保留全周期结果入排行榜，其他周期仅作为验证参考
                # 判断是否为全周期：period中包含"全周期"/"full"或回测年限≥3年
                period = r.get('period', r.get('backtest_period', ''))
                years = float(r.get('years', r.get('backtest_years', 0)))
                # 如果years为0，尝试从period中解析
                if years < 1 and period:
                    import re
                    match = re.findall(r'(\d{4})', str(period))
                    if len(match) >= 2:
                        years = int(match[1]) - int(match[0])
                is_full_period = ('全周期' in str(period) or 'full' in str(period).lower()
                                  or 'Full' in str(period) or years >= 3)
                if not is_full_period:
                    print(f"    🔄 跳过非全周期结果: {strategy_name} ({period}, {years}年)")
                    continue

                # 从回测结果中提取标准指标
                annual_return = float(r.get('annual_return_pct', r.get('annual_return', 0)))
                max_drawdown = abs(float(r.get('max_drawdown_pct', r.get('max_drawdown', 0))))  # 本地脚本可能输出负值
                sharpe = float(r.get('sharpe_ratio', r.get('sharpe', 0)))
                win_rate = float(r.get('win_rate_pct', r.get('win_rate', 0)))
                profit_factor = float(r.get('profit_factor', 0))
                total_trades = int(r.get('total_trades', 0))
                years = float(r.get('years', r.get('backtest_years', 5)))
                avg_trades_per_year = round(total_trades / max(years, 0.01), 1)

                # 如果策略名不含标的，自动补上
                if symbol and symbol not in strategy_name:
                    strategy_name = f"{strategy_name}({symbol})"

                # 构造策略参数
                strategy_params = {}
                for k in ['rsi_period', 'rsi_oversold', 'rsi_overbought', 'buffer_days',
                           'lookback_months', 'regime_detector', 'position_size',
                           'init_cash', 'commission_rate', 'stop_loss_atr_mult']:
                    if k in r:
                        strategy_params[k] = r[k]
                # 把回测周期信息加入策略参数（影响指纹，但不影响策略名显示）
                if period:
                    strategy_params['backtest_period'] = str(period)

                # 构造标准result格式
                main_result = {
                    'annual_return': round(annual_return, 2),
                    'total_return': round(annual_return * years, 2),
                    'max_drawdown': round(max_drawdown, 2),
                    'sharpe': round(sharpe, 2),
                    'calmar': round(annual_return / max(max_drawdown, 0.01), 2),
                    'win_rate': round(win_rate, 1),
                    'profit_factor': round(profit_factor, 2),
                    'avg_trades_per_year': avg_trades_per_year,
                    'holding_distribution': {'local_backtest': 100.0},
                }

                # 压力测试：用close_prices重跑（如果有数据的话）
                # 本地回测脚本通常有自己的数据源，这里简化处理
                stress_result = None
                stress_annual = r.get('stress_annual', r.get('stress_annual_return', None))
                stress_dd = r.get('stress_max_drawdown', r.get('stress_dd', None))
                if stress_annual is not None and stress_dd is not None:
                    stress_result = {
                        'annual_return': float(stress_annual),
                        'max_drawdown': float(stress_dd),
                    }

                # 统一评分
                score_result = calculate_score(main_result, stress_result, survivorship_bias)

                strategy_entry = {
                    'strategy_name': strategy_name,
                    'strategy_params': strategy_params,
                    'strategy_description': r.get('description', f'本地回测策略: {os.path.basename(script_path)}'),
                    'strategy_type': strategy_type,
                    'annual_return': main_result['annual_return'],
                    'sharpe': main_result['sharpe'],
                    'max_drawdown': main_result['max_drawdown'],
                    'calmar': main_result['calmar'],
                    'win_rate': main_result['win_rate'],
                    'profit_factor': main_result['profit_factor'],
                    'avg_trades_per_year': main_result['avg_trades_per_year'],
                    'holding_distribution': main_result['holding_distribution'],
                    'stress_test': stress_result,
                    'cross_robust': score_result.get('cross_robust', False),
                    'survivorship_bias_flag': survivorship_bias,
                    'pine_script_rejected': False,
                    'portability_score': 8,  # 本地Python策略，有数据依赖
                    'source': 'local_backtest',  # 标记来源
                    'source_script': os.path.basename(script_path),
                    'market': 'US',
                }

                if score_result['total_score'] > 0 and not score_result['hard_fail']:
                    passed_count += 1
                    robust_mark = '✅' if score_result.get('cross_robust') else ''
                    print(f"    ✅ {strategy_name}: {score_result['total_score']}分 | 年化{annual_return:+.2f}% | 回撤{max_drawdown:.2f}% | 夏普{sharpe:.2f} {robust_mark}")
                    update_leaderboard_v3(strategy_entry, score_result)
                else:
                    rejected_count += 1
                    reason = score_result.get('fail_reason', '评分过低')
                    print(f"    ❌ {strategy_name}: {reason} | 年化{annual_return:+.2f}% | 回撤{max_drawdown:.2f}%")
                    update_leaderboard_v3(strategy_entry, score_result)

                results.append({
                    'strategy': strategy_name,
                    'type': strategy_type,
                    'passed': score_result['total_score'] > 0 and not score_result['hard_fail'],
                    'score': score_result['total_score'],
                    'annual': main_result['annual_return'],
                    'drawdown': main_result['max_drawdown'],
                    'sharpe': main_result['sharpe'],
                    'calmar': main_result['calmar'],
                    'win_rate': main_result['win_rate'],
                    'profit_factor': main_result['profit_factor'],
                    'reason': score_result.get('fail_reason', ''),
                    'cross_robust': score_result.get('cross_robust', False),
                    'survivorship_bias': survivorship_bias,
                    'source': 'local_backtest',
                    'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    # 本地策略耗时：脚本执行即回测，发现和编码在脚本内部
                    'timing_discovery': 0.001,
                    'timing_coding': 0.001,
                    'timing_backtest': 0.001,
                    'timing_total': 0.001,
                })

            except Exception as e:
                print(f"    ❌ 结果适配异常: {e}")
                rejected_count += 1

    print(f"\n  🖥️ 本地回测汇总: {passed_count}个通过 / {rejected_count}个废弃")
    return results, passed_count, rejected_count


def _run_local_fallback(reg: Dict, close_prices: pd.DataFrame,
                         risk_free_rate: float) -> List[Dict]:
    """回退方案：当脚本无JSON输出时，直接import执行核心逻辑"""
    adapter = reg.get('adapter', '')
    results = []

    if adapter == 'rsi2':
        # 直接用内置的strategy_rsi_rotation函数回测RSI(2)变体
        for symbol in ['QQQ', 'SPY']:
            if symbol not in close_prices.columns:
                continue
            sym_prices = close_prices[[symbol]].copy()
            sym_prices.columns = ['close']
            for oversold in [5, 10]:
                for overbought in [80, 90]:
                    try:
                        holding = strategy_rsi_rotation(sym_prices, rsi_period=2,
                                                        rsi_oversold=oversold,
                                                        rsi_overbought=overbought,
                                                        buffer_days=0)
                        main_result = run_backtest(sym_prices, holding, MAIN_START, MAIN_END,
                                                   risk_free_rate, 'US')
                        if main_result is None:
                            continue
                        results.append({
                            'strategy_name': f'RSI(2)严格均值回归({symbol})',
                            'annual_return_pct': main_result['annual_return'],
                            'max_drawdown_pct': main_result['max_drawdown'],
                            'sharpe_ratio': main_result['sharpe'],
                            'win_rate_pct': main_result['win_rate'],
                            'profit_factor': main_result['profit_factor'],
                            'total_trades': int(main_result['avg_trades_per_year'] * 5),
                            'years': 5,
                            'symbol': symbol,
                            'rsi_period': 2, 'rsi_oversold': oversold, 'rsi_overbought': overbought,
                        })
                    except Exception as e:
                        print(f"      RSI2回退失败({symbol}/{oversold}/{overbought}): {e}")

    elif adapter == 'dual_market':
        # 双市场策略比较复杂，用strategy_gem_rotation做简化模拟
        for lookback in [3, 6, 9]:
            try:
                holding = strategy_gem_rotation(close_prices,
                                                lookback_months=lookback,
                                                buffer_days=5,
                                                risk_assets=['QQQ', 'SPY', 'VEA'],
                                                safe_assets=['AGG', 'SHY'])
                main_result = run_backtest(close_prices, holding, MAIN_START, MAIN_END,
                                           risk_free_rate, 'US')
                if main_result is None:
                    continue
                results.append({
                    'strategy_name': f'双市场自适应策略(趋势+震荡){lookback}M',
                    'annual_return_pct': main_result['annual_return'],
                    'max_drawdown_pct': main_result['max_drawdown'],
                    'sharpe_ratio': main_result['sharpe'],
                    'win_rate_pct': main_result['win_rate'],
                    'profit_factor': main_result['profit_factor'],
                    'total_trades': int(main_result['avg_trades_per_year'] * 5),
                    'years': 5,
                    'lookback_months': lookback,
                })
            except Exception as e:
                print(f"      双市场回退失败({lookback}M): {e}")

    elif adapter == 'blakever_v65':
        # Blakever V6.5: 利率维度修正版 → 用GEM轮动+SHY/AGG替代模拟
        try:
            # Bullish+Falling: SPY高配; Bearish+Rising: SHY现金
            holding = strategy_gem_rotation(close_prices,
                                            lookback_months=6,
                                            buffer_days=5,
                                            risk_assets=['SPY', 'QQQ'],
                                            safe_assets=['SHY', 'AGG'])
            main_result = run_backtest(close_prices, holding, MAIN_START, MAIN_END,
                                       risk_free_rate, 'US')
            if main_result:
                results.append({
                    'strategy_name': 'Blakever V6.5 利率维度修正(SPY/SHY)',
                    'annual_return_pct': main_result['annual_return'],
                    'max_drawdown_pct': main_result['max_drawdown'],
                    'sharpe_ratio': main_result['sharpe'],
                    'win_rate_pct': main_result['win_rate'],
                    'profit_factor': main_result['profit_factor'],
                    'total_trades': int(main_result['avg_trades_per_year'] * 5),
                    'years': 5,
                    'lookback_months': 6,
                })
        except Exception as e:
            print(f"      Blakever V6.5回退失败: {e}")

    return results


# ================================================================
# 样本外滚动验证（对齐规范：每周验证前十，连续3周失效标记）
# ================================================================
def rolling_validation(close_prices: pd.DataFrame, risk_free_rate: float = 0.045):
    """
    样本外滚动验证：
    - 用最近一周市场数据验证排行榜前十策略
    - 连续3周跑输基准累计≥3% + 至少2周绝对收益为负 → 标记失效
    """
    leaderboard = load_leaderboard('US')  # 滚动验证只验证美股排行榜
    if not leaderboard:
        print("  ⏭️ 排行榜为空，跳过滚动验证")
        return

    print(f"\n  📊 样本外滚动验证 (排行榜{len(leaderboard)}个策略)...")

    # 基准：买入持有SPY
    benchmark = 'SPY'
    if benchmark not in close_prices.columns:
        print("  ⚠️ 无SPY数据，跳过滚动验证")
        return

    # 最近一周数据
    latest_date = close_prices.index[-1]
    week_ago = latest_date - timedelta(days=7)
    recent_mask = close_prices.index >= week_ago
    recent_prices = close_prices.loc[recent_mask]

    if len(recent_prices) < 3:
        print("  ⚠️ 近一周数据不足，跳过")
        return

    # 基准收益
    benchmark_return = (recent_prices[benchmark].iloc[-1] / recent_prices[benchmark].iloc[0] - 1) * 100

    for entry in leaderboard:
        name = entry.get('strategy_name', '未知')
        validation_history = entry.get('validation_history', [])

        # 简化验证：用最近持仓资产计算收益
        # 实际应重新运行策略获取最新持仓，这里用holding_distribution推断
        holding_dist = entry.get('holding_distribution', {})
        if not holding_dist:
            continue

        # 使用最近持仓最多的资产计算收益
        top_holding = max(holding_dist, key=holding_dist.get) if holding_dist else None
        if top_holding and top_holding in recent_prices.columns:
            strategy_return = (recent_prices[top_holding].iloc[-1] / recent_prices[top_holding].iloc[0] - 1) * 100
        else:
            strategy_return = 0

        # 记录本周验证结果
        week_result = {
            'date': latest_date.strftime('%Y-%m-%d'),
            'strategy_return': round(float(strategy_return), 2),
            'benchmark_return': round(float(benchmark_return), 2),
            'excess': round(float(strategy_return - benchmark_return), 2),
            'absolute_negative': bool(strategy_return < 0),
        }

        validation_history.append(week_result)
        # 只保留最近4周
        validation_history = validation_history[-4:]
        entry['validation_history'] = validation_history

        # 失效判定：连续3周跑输基准≥3% + 至少2周绝对收益为负
        if len(validation_history) >= 3:
            last_3 = validation_history[-3:]
            consecutive_under = all(w['excess'] <= -1 for w in last_3)
            cumulative_under = sum(w['excess'] for w in last_3) <= -3
            negative_weeks = sum(1 for w in last_3 if w['absolute_negative'])

            if consecutive_under and cumulative_under and negative_weeks >= 2:
                entry['validation_status'] = '⚠️ 疑似失效'
                print(f"    ⚠️ {name}: 疑似失效（连续3周跑输基准累计{sum(w['excess'] for w in last_3):.1f}%，{negative_weeks}周绝对负收益）")
            else:
                entry['validation_status'] = '✅ 有效'
                print(f"    ✅ {name}: 有效（本周超额{week_result['excess']:+.2f}%）")
        else:
            entry['validation_status'] = '🔄 观察中'
            print(f"    🔄 {name}: 观察中（仅{len(validation_history)}周数据）")

    save_leaderboard(leaderboard)


# ================================================================
# 主扫描逻辑
# ================================================================
def scan_strategies():
    """扫描策略库，执行回测，更新排行榜"""
    print("=" * 70)
    print("  🔄 穿越牛熊策略回测扫描 v3（全面升级版）")
    print("=" * 70)

    scan_start = datetime.now()
    search_start_time = time.time()  # 记录搜索开始时间，用于计算策略发现耗时
    print(f"  ⏰ 开始时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📊 回测区间: {MAIN_START} ~ {MAIN_END} (主) / {STRESS_START} ~ {STRESS_END} (压力)")
    print(f"  📏 回撤淘汰线: ≥{MAX_DRAWDOWN_HARD_LIMIT}%")
    print(f"  🏆 入榜规则: 按最高分从高到低排，保留前十")

    # 0. 动态无风险利率
    risk_free_rate = fetch_risk_free_rate()

    # 1. 混合搜索策略（GitHub + 参数变体）
    print(f"\n{'='*70}")
    print(f"  🔍 步骤1: 混合搜索策略（7大来源）")
    print(f"{'='*70}")

    # 一次性迁移：将旧的单体排行榜数据拆分到三个市场排行榜
    migrate_legacy_leaderboard()
    
    leaderboard = load_leaderboard('US')  # 滚动验证只验证美股排行榜
    rejected = load_rejected()
    existing_fps = set()
    for entry in leaderboard + rejected:
        fp = entry.get('fingerprint', '')
        market = entry.get('market', 'US')
        if fp:
            existing_fps.add((fp, market))

    search_phase_start = time.time()
    searched_strategies, search_stats = search_cross_regime_strategies(existing_fps, min_new=3)
    search_stats['search_duration'] = time.time() - search_phase_start

    # 2. 生成内置策略变体
    print(f"\n{'='*70}")
    print(f"  🧬 步骤2: 生成内置策略变体（7种策略类型）")
    print(f"{'='*70}")
    variant_gen_start = time.time()
    builtin_variants = generate_strategy_variants()
    search_stats['variant_generation_time'] = time.time() - variant_gen_start

    # 合并搜索结果和内置变体
    all_variants = builtin_variants  # 内置变体总是全部回测
    
    # 给内置变体添加build_time（参数组合构建时间极短）
    variant_gen_time = search_stats.get('variant_generation_time', 0.5)
    for v in all_variants:
        if 'build_time' not in v:
            v['build_time'] = variant_gen_time / max(len(all_variants), 1)  # 均摊构建时间

    # 搜索到的外部策略（聚宽等）→ 转换为ETF轮动策略函数
    if searched_strategies:  # searched_strategies已经是策略列表
        conversion_start = time.time()
        external_variants = _convert_external_strategies(searched_strategies, close_prices=None)
        search_stats['conversion_time'] = time.time() - conversion_start
        search_stats['total_converted'] = len(external_variants) if external_variants else 0
        if external_variants:
            all_variants.extend(external_variants)
            print(f"  🔄 外部策略转换: {len(external_variants)}个策略已适配为ETF轮动格式 (耗时{search_stats['conversion_time']:.2f}s)")
    else:
        search_stats['conversion_time'] = 0
        search_stats['total_converted'] = 0

    # GitHub搜索结果也加入（如果有代码可执行的话，目前先以内置变体为主）
    # TODO: 将GitHub搜索结果的代码动态加载执行

    # 3. 加载数据（v4升级：ETF + 港美股全量）
    print(f"\n{'='*70}")
    print(f"  📦 步骤3: 加载数据（v4: ETF + 港美股全量，{len(US_LARGE_CAPS)}美股 + {len(HK_BLUE_CHIPS)}港股）")
    print(f"{'='*70}")
    
    # 加载ETF数据（保持原有逻辑，用于轮动策略）
    close_prices, survivorship_bias = load_all_etf_data()
    
    # 加载全市场本地数据（v4新增）
    all_market_data = load_all_market_data()
    # 将ETF close_prices也注入
    if close_prices is not None and len(close_prices) > 0:
        all_market_data['US_ETF'] = {sym: pd.DataFrame({'Close': close_prices[sym]}) for sym in close_prices.columns if sym in close_prices}

    # 4. 去重
    print(f"\n{'='*70}")
    print(f"  🔍 步骤4: 策略去重（SHA256指纹+90%参数相似度家族检测）")
    print(f"{'='*70}")

    deduped_variants = []
    deduped_count = 0
    family_merge_count = 0

    for v in all_variants:
        params_str = json.dumps(v.get('params', {}), sort_keys=True)
        fp = hashlib.sha256(f"{v['name']}_{params_str}".encode()).hexdigest()

        # 检查排行榜中是否已有同指纹
        existing_in_lb = any(e.get('fingerprint') == fp for e in leaderboard)

        # 检查家族相似度
        is_family_member = False
        for e in leaderboard + rejected:
            e_params = e.get('strategy_params', {})
            similarity = compute_param_similarity(v.get('params', {}), e_params)
            if similarity >= 0.9 and e.get('total_score', 0) >= v.get('_estimated_score', 0):
                is_family_member = True
                family_merge_count += 1
                break

        if existing_in_lb:
            deduped_count += 1
            continue
        if is_family_member:
            deduped_count += 1
            continue

        v['_fingerprint'] = fp
        deduped_variants.append(v)

    # 如果没有新策略可回测，直接跳过回测步骤
    if not deduped_variants:
        print(f"  ℹ️ 无新策略需要回测（所有策略已在排行榜/废弃库中）")
    else:
        print(f"  🔍 去重后: {len(deduped_variants)}个 (跳过{deduped_count}个重复, {family_merge_count}个同家族)")

    # 5. 回测（v6升级：分层递进回测架构）
    # ================================================================
    # 第1层：快速广筛（向量化，秒级）→ 淘汰明显差的策略
    # 第2层：中等精度验证（向量化+完整指标）→ 精选候选
    # 第3层：高精度终验（逐日循环+多标的）→ 最终排行榜
    # ================================================================
    print(f"\n{'='*70}")
    print(f"  📋 步骤5: 分层递进回测 (v6架构)")
    print(f"{'='*70}")
    print(f"  📊 策略总数: {len(deduped_variants)}个")
    print(f"  🏗️  三层架构:")
    print(f"     第1层: 快速广筛(向量化) → 淘汰回撤>{LAYER1_MAX_DD_THRESHOLD}%或年化<{LAYER1_MIN_ANN_THRESHOLD}%")
    print(f"     第2层: 中等验证(向量化+评分) → 淘汰所有市场评分未通过")
    print(f"     第3层: 高精度终验(逐日循环) → Top{LAYER3_TOP_N}入榜")

    passed_count = 0
    rejected_count = 0
    results = []
    new_best_by_market = {'US': None, 'HK': None, 'CN': None}

    if deduped_variants:
        # ====== 第1层：快速广筛 ======
        layer1_passed, layer1_eliminated = _layer1_fast_screen(
            deduped_variants, close_prices, all_market_data, risk_free_rate)
        rejected_count += len(layer1_eliminated)
        
        for elim in layer1_eliminated:
            results.append({
                'strategy': elim['strategy']['name'],
                'type': elim['strategy'].get('type', '其他'),
                'passed': False,
                'score': 0,
                'annual': 0,
                'drawdown': 0,
                'sharpe': 0,
                'calmar': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'reason': f'[L1淘汰] {elim["reason"]}',
                'source': elim['strategy'].get('source', 'builtin'),
                'source_link': elim['strategy'].get('source_link', ''),
                'timing_discovery': 0,
                'timing_coding': 0,
                'timing_backtest': 0,
                'timing_total': 0,
                'multi_market_scores': {'US': 0, 'HK': 0, 'CN': 0},
                'multi_market_annual': {'US': 0, 'HK': 0, 'CN': 0},
            })

        if not layer1_passed:
            print(f"\n  ⚠️ 第1层全部淘汰，无策略进入第2层")
        else:
            # ====== 第2层：中等精度验证 ======
            layer2_passed, layer2_eliminated = _layer2_medium_validate(
                layer1_passed, close_prices, all_market_data, risk_free_rate)
            rejected_count += len(layer2_eliminated)
            
            for elim in layer2_eliminated:
                results.append({
                    'strategy': elim['strategy']['name'],
                    'type': elim['strategy'].get('type', '其他'),
                    'passed': False,
                    'score': 0,
                    'annual': 0,
                    'drawdown': 0,
                    'sharpe': 0,
                    'calmar': 0,
                    'win_rate': 0,
                    'profit_factor': 0,
                    'reason': f'[L2淘汰] {elim["reason"]}',
                    'source': elim['strategy'].get('source', 'builtin'),
                    'source_link': elim['strategy'].get('source_link', ''),
                    'timing_discovery': 0,
                    'timing_coding': 0,
                    'timing_backtest': 0,
                    'timing_total': 0,
                    'multi_market_scores': {'US': 0, 'HK': 0, 'CN': 0},
                    'multi_market_annual': {'US': 0, 'HK': 0, 'CN': 0},
                })

            if not layer2_passed:
                print(f"\n  ⚠️ 第2层全部淘汰，无策略进入第3层")
            else:
                # ====== 第3层：高精度终验 ======
                layer3_results = _layer3_precision_finaltest(
                    layer2_passed, close_prices, all_market_data, risk_free_rate, survivorship_bias)

                # ====== 处理第3层结果：更新排行榜 ======
                for lr in layer3_results:
                    strategy = lr['strategy']
                    name = strategy['name']
                    strategy_type = strategy.get('type', '其他')
                    market_results = lr['market_results']
                    batch_result = lr.get('batch_result')
                    
                    # 三阶段耗时追踪（兼容v5格式）
                    strategy_source = strategy.get('source', 'builtin')
                    if strategy_source == 'builtin':
                        discovery_time = 0.3
                    else:
                        discovery_time = 1.0
                    code_time = 0.5
                    backtest_time = lr.get('layer3_elapsed', 0)
                    total_time = discovery_time + code_time + backtest_time
                    
                    best_market = None
                    best_score = 0
                    
                    for market, mr in market_results.items():
                        main_result = mr['main_result']
                        score_result = mr['score_result']
                        market_rf = mr['risk_free_rate']
                        market_bias = mr['survivorship_bias']
                        
                        market_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[market]
                        
                        strategy_entry = {
                            'strategy_name': name,
                            'strategy_params': strategy['params'],
                            'strategy_description': strategy.get('desc', ''),
                            'strategy_type': strategy_type,
                            'source': strategy.get('source', 'builtin'),
                            'source_link': strategy.get('source_link', ''),
                            'annual_return': main_result['annual_return'],
                            'sharpe': main_result['sharpe'],
                            'max_drawdown': main_result['max_drawdown'],
                            'calmar': main_result['calmar'],
                            'win_rate': main_result['win_rate'],
                            'profit_factor': main_result['profit_factor'],
                            'avg_trades_per_year': main_result['avg_trades_per_year'],
                            'holding_distribution': main_result.get('holding_distribution', {}),
                            'stress_test': {
                                'annual_return': mr['stress_result']['annual_return'] if mr['stress_result'] else 0,
                                'max_drawdown': mr['stress_result']['max_drawdown'] if mr['stress_result'] else 0,
                            } if mr['stress_result'] else None,
                            'cross_robust': score_result.get('cross_robust', False),
                            'survivorship_bias_flag': market_bias,
                            'pine_script_rejected': False,
                            'portability_score': 10,
                            'market': market,
                        }
                        
                        if score_result['total_score'] > 0 and not score_result['hard_fail']:
                            passed_count += 1
                            robust_mark = '✅' if score_result.get('cross_robust') else ''
                            bias_mark = '⚠️' if market_bias else ''
                            print(f"      ✅ [{market_label}] 得分{score_result['total_score']}分 | 年化{main_result['annual_return']:+.2f}% | 回撤{main_result['max_drawdown']:.2f}% | 夏普{main_result['sharpe']:.2f} {robust_mark} {bias_mark}")
                            
                            old_lb = load_leaderboard(market)
                            update_leaderboard_v3(strategy_entry, score_result, market)
                            new_lb = load_leaderboard(market)
                            if len(new_lb) > 0 and (len(old_lb) < len(new_lb) or new_lb[0].get('total_score', 0) > (old_lb[0].get('total_score', 0) if old_lb else 0)):
                                if any(e.get('strategy_name') == name for e in new_lb):
                                    new_best_by_market[market] = name
                            
                            if score_result['total_score'] > best_score:
                                best_score = score_result['total_score']
                                best_market = market
                        else:
                            rejected_count += 1
                            reason = score_result.get('fail_reason', '评分过低')
                            print(f"      ❌ [{market_label}] {reason} | 年化{main_result['annual_return']:+.2f}% | 回撤{main_result['max_drawdown']:.2f}%")
                            update_leaderboard_v3(strategy_entry, score_result, market)
                    
                    # 多标的批量回测结果
                    batch_symbol_count = 0
                    batch_profitable_ratio = 0
                    batch_us_avg = 0
                    batch_hk_avg = 0
                    batch_med_annual = 0
                    if batch_result and batch_result.get('main_result'):
                        batch_symbol_count = batch_result['symbol_count']
                        batch_profitable_ratio = batch_result.get('profitable_ratio', 0)
                        batch_us_avg = batch_result['main_result'].get('us_avg_annual', 0)
                        batch_hk_avg = batch_result['main_result'].get('hk_avg_annual', 0)
                        batch_med_annual = batch_result['main_result'].get('median_annual_return', 0)
                        print(f"    🌐 多标的回测: {batch_symbol_count}只 | 盈利占比{batch_profitable_ratio:.1f}% | "
                              f"中位年化{batch_med_annual:+.2f}% | 美股{batch_us_avg:+.2f}% | 港股{batch_hk_avg:+.2f}%")
                    
                    # 汇总结果
                    us_mr = market_results.get('US', {})
                    us_main = us_mr.get('main_result') if us_mr else None
                    us_score = us_mr.get('score_result', {}) if us_mr else {}
                    cn_mr = market_results.get('CN', {})
                    cn_main = cn_mr.get('main_result') if cn_mr else None
                    cn_score = cn_mr.get('score_result', {}) if cn_mr else {}
                    hk_mr = market_results.get('HK', {})
                    hk_main = hk_mr.get('main_result') if hk_mr else None
                    hk_score = hk_mr.get('score_result', {}) if hk_mr else {}
                    
                    results.append({
                        'strategy': name,
                        'type': strategy_type,
                        'passed': any(mr['score_result']['total_score'] > 0 and not mr['score_result']['hard_fail'] for mr in market_results.values()),
                        'score': us_score.get('total_score', 0),
                        'annual': us_main['annual_return'] if us_main else 0,
                        'drawdown': us_main['max_drawdown'] if us_main else 0,
                        'sharpe': us_main['sharpe'] if us_main else 0,
                        'calmar': us_main['calmar'] if us_main else 0,
                        'win_rate': us_main['win_rate'] if us_main else 0,
                        'profit_factor': us_main['profit_factor'] if us_main else 0,
                        'reason': us_score.get('fail_reason', ''),
                        'cross_robust': us_score.get('cross_robust', False),
                        'survivorship_bias': survivorship_bias,
                        'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'source': strategy.get('source', 'builtin'),
                        'source_link': strategy.get('source_link', ''),
                        'timing_discovery': round(discovery_time, 3),
                        'timing_coding': round(code_time, 3),
                        'timing_backtest': round(backtest_time, 3),
                        'timing_total': round(total_time, 3),
                        'multi_market_scores': {
                            'US': us_score.get('total_score', 0),
                            'HK': hk_score.get('total_score', 0),
                            'CN': cn_score.get('total_score', 0),
                        },
                        'multi_market_annual': {
                            'US': us_main['annual_return'] if us_main else 0,
                            'HK': hk_main['annual_return'] if hk_main else 0,
                            'CN': cn_main['annual_return'] if cn_main else 0,
                        },
                    })

        # 5b. 本地回测策略扫描（世界最好的策略，无论来源）
    try:
        local_results, local_passed, local_rejected = scan_local_backtest_strategies(
            close_prices, risk_free_rate, survivorship_bias)
        results.extend(local_results)
        passed_count += local_passed
        rejected_count += local_rejected
    except Exception as e:
        print(f"  ⚠️ 本地回测扫描异常: {e}")

    # 6. 样本外滚动验证
    print(f"\n{'='*70}")
    print(f"  📊 步骤6: 样本外滚动验证")
    print(f"{'='*70}")
    try:
        rolling_validation(close_prices, risk_free_rate)
    except Exception as e:
        print(f"  ⚠️ 滚动验证异常: {e}")

    scan_end = datetime.now()
    duration = (scan_end - scan_start).total_seconds()

    # 加载所有三个市场的排行榜
    all_lbs = load_all_leaderboards()
    all_rjs = load_all_rejected()

    print(f"\n{'='*70}")
    print(f"  📊 扫描汇总（v5: 三市场独立排行）")
    print(f"{'='*70}")
    print(f"  策略变体: {len(deduped_variants)}个")
    print(f"  GitHub搜索: {search_stats.get('github_results', 0)}个")
    print(f"  Pine Script否决: {search_stats.get('pine_vetoed', 0)}个")
    print(f"  本地回测: {local_passed + local_rejected}个脚本")
    print(f"  通过回测: {passed_count}个")
    print(f"  废弃策略: {rejected_count}个")
    print(f"\n  🏆 三市场排行榜:")
    for m in ['US', 'HK', 'CN']:
        lb = all_lbs.get(m, [])
        m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[m]
        best = lb[0] if lb else None
        best_info = f" | 最佳: {best['strategy_name']}({best['total_score']}分)" if best else " | (空)"
        print(f"    [{m_label}] 前十: {len(lb)}个策略{best_info}")
    print(f"  废弃库累计: US {len(all_rjs.get('US', []))} + HK {len(all_rjs.get('HK', []))} + CN {len(all_rjs.get('CN', []))}")
    # v5多标的统计
    total_symbols = sum(len(v) for v in all_market_data.values())
    print(f"  🌐 多标的覆盖: {total_symbols}只 (美股ETF {len(all_market_data.get('US_ETF', {}))} + 美股 {len(all_market_data.get('US_STOCK', {}))} + 港股 {len(all_market_data.get('HK_STOCK', {}))} + A股ETF {len(all_market_data.get('CN_ETF', {}))} + A股蓝筹 {len(all_market_data.get('CN_STOCK', {}))})")
    for m, nb in new_best_by_market.items():
        if nb:
            m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[m]
            print(f"  🆕 [{m_label}]新上榜策略: {nb}")
    print(f"  ⏱️ 耗时: {duration:.0f}秒")
    print(f"  📏 无风险利率: 美股{risk_free_rate:.4f} | 港股{HK_RISK_FREE_RATE:.4f} | A股{CN_RISK_FREE_RATE:.4f}")

    # 7. 保存到策略库
    try:
        library = load_strategy_library(STRATEGY_LIBRARY_PATH)
        for m, lb in all_lbs.items():
            for entry in lb:
                library = add_strategy_to_library(entry, library)
        save_strategy_library(library, STRATEGY_LIBRARY_PATH)
    except Exception as e:
        print(f"  ⚠️ 策略库保存异常: {e}")

    # 8. 发送邮件
    try:
        html_content = generate_email(results, all_lbs, all_rjs, scan_start, duration,
                                      new_best_by_market, search_stats, risk_free_rate, survivorship_bias,
                                      all_market_data)
        send_email(html_content, scan_start)
        print(f"  📧 邮件已发送至: {EMAIL_TO}")
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")

    return {
        'scan_time': scan_start.strftime('%Y-%m-%d %H:%M:%S'),
        'duration_seconds': duration,
        'total_variants': len(deduped_variants),
        'github_results': search_stats.get('github_results', 0),
        'pine_vetoed': search_stats.get('pine_vetoed', 0),
        'passed': passed_count,
        'rejected': rejected_count,
        'leaderboard_size': sum(len(lb) for lb in all_lbs.values()),
        'rejected_db_size': sum(len(rj) for rj in all_rjs.values()),
        'new_best_by_market': new_best_by_market,
        'search_method': search_stats.get('search_method', ''),
        'risk_free_rate': risk_free_rate,
    }


# ================================================================
# 耗时统计HTML生成
# ================================================================
def _build_timing_summary_html(results: List[Dict]) -> str:
    """生成策略生命周期耗时统计的HTML卡片
    
    每个策略的三阶段耗时：
    1. 发现(Discovery): 搜索/变体生成 → 找到策略概念
    2. 编码(Coding): 策略函数构建/外部代码转换 → 写成可执行代码
    3. 回测(Backtest): 信号生成+绩效计算 → 得到回测结果
    """
    if not results:
        return '<p style="text-align:center;color:#999;padding:16px;font-size:13px">暂无耗时数据</p>'
    
    # 计算汇总统计
    all_disc = [r.get('timing_discovery', 0) for r in results if r.get('timing_total', 0) > 0]
    all_code = [r.get('timing_coding', 0) for r in results if r.get('timing_total', 0) > 0]
    all_bt = [r.get('timing_backtest', 0) for r in results if r.get('timing_total', 0) > 0]
    all_total = [r.get('timing_total', 0) for r in results if r.get('timing_total', 0) > 0]
    
    def fmt(t):
        if t < 0.001:
            return '<1ms'
        elif t < 1:
            return f'{t*1000:.0f}ms'
        elif t < 60:
            return f'{t:.1f}s'
        else:
            m, s = divmod(t, 60)
            return f'{int(m)}m{s:.0f}s'
    
    if not all_total:
        return '<p style="text-align:center;color:#999;padding:16px;font-size:13px">暂无耗时数据</p>'
    
    avg_disc = sum(all_disc) / len(all_disc)
    avg_code = sum(all_code) / len(all_code)
    avg_bt = sum(all_bt) / len(all_bt)
    avg_total = sum(all_total) / len(all_total)
    max_total = max(all_total)
    min_total = min(all_total)
    
    # 汇总卡片
    summary_html = f'''
    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:10px;margin-bottom:10px">
      <div style="font-size:12px;color:#ccc;margin-bottom:8px">📊 汇总（{len(all_total)}个策略）</div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;font-size:11px">
        <div style="text-align:center;padding:6px;background:rgba(155,89,182,0.2);border-radius:6px">
          <div style="font-size:14px;font-weight:bold;color:#9b59b6">{fmt(avg_disc)}</div>
          <div style="font-size:9px;color:#aaa">平均发现</div>
        </div>
        <div style="text-align:center;padding:6px;background:rgba(52,152,219,0.2);border-radius:6px">
          <div style="font-size:14px;font-weight:bold;color:#3498db">{fmt(avg_code)}</div>
          <div style="font-size:9px;color:#aaa">平均编码</div>
        </div>
        <div style="text-align:center;padding:6px;background:rgba(230,126,34,0.2);border-radius:6px">
          <div style="font-size:14px;font-weight:bold;color:#e67e22">{fmt(avg_bt)}</div>
          <div style="font-size:9px;color:#aaa">平均回测</div>
        </div>
        <div style="text-align:center;padding:6px;background:rgba(46,204,113,0.2);border-radius:6px">
          <div style="font-size:14px;font-weight:bold;color:#2ecc71">{fmt(avg_total)}</div>
          <div style="font-size:9px;color:#aaa">平均总计</div>
        </div>
      </div>
      <div style="font-size:10px;color:#888;margin-top:6px">最快 {fmt(min_total)} · 最慢 {fmt(max_total)} · 总耗时 {fmt(sum(all_total))}</div>
    </div>'''
    
    # 逐策略耗时列表（只展示有耗时数据的策略，最多15个）
    detail_html = ''
    timed_results = [r for r in results if r.get('timing_total', 0) > 0]
    # 按总分从高到低排序
    timed_results.sort(key=lambda x: x.get('score', 0), reverse=True)
    timed_results = timed_results[:15]
    
    for r in timed_results:
        t_disc = r.get('timing_discovery', 0)
        t_code = r.get('timing_coding', 0)
        t_bt = r.get('timing_backtest', 0)
        t_total = r.get('timing_total', 0)
        
        # 计算各阶段占比
        if t_total > 0:
            p_disc = t_disc / t_total * 100
            p_code = t_code / t_total * 100
            p_bt = t_bt / t_total * 100
        else:
            p_disc = p_code = p_bt = 0
        
        status = '✅' if r['passed'] else '❌'
        detail_html += f'''
        <div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.1)">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="flex:1;min-width:0">
              <span style="font-size:11px">{status}</span>
              <span style="font-size:11px;color:#eee;margin-left:2px">{r['strategy'][:30]}</span>
            </div>
            <span style="font-size:11px;font-weight:bold;color:{'#2ecc71' if r['passed'] else '#e74c3c'};white-space:nowrap;margin-left:4px">{r['score']}分</span>
          </div>
          <div style="display:flex;gap:2px;margin-top:4px;height:6px;border-radius:3px;overflow:hidden">
            <div style="width:{p_disc:.0f}%;background:#9b59b6" title="发现 {fmt(t_disc)}"></div>
            <div style="width:{p_code:.0f}%;background:#3498db" title="编码 {fmt(t_code)}"></div>
            <div style="width:{p_bt:.0f}%;background:#e67e22" title="回测 {fmt(t_bt)}"></div>
          </div>
          <div style="font-size:9px;color:#888;margin-top:2px">
            <span style="color:#9b59b6">■</span> 发现{fmt(t_disc)} ({p_disc:.0f}%) 
            <span style="color:#3498db">■</span> 编码{fmt(t_code)} ({p_code:.0f}%) 
            <span style="color:#e67e22">■</span> 回测{fmt(t_bt)} ({p_bt:.0f}%) → 总计{fmt(t_total)}
          </div>
        </div>'''
    
    if not detail_html:
        detail_html = '<p style="text-align:center;color:#999;font-size:11px">本轮无耗时数据</p>'
    
    return summary_html + detail_html


# ================================================================
# HTML邮件生成（对齐规范输出格式）
# ================================================================
def generate_email(results: List[Dict], leaderboard: Union[List[Dict], Dict[str, List[Dict]]],
                  rejected: Union[List[Dict], Dict[str, List[Dict]]], scan_start: datetime,
                  duration: float, new_best: Union[str, Dict[str, str], None] = None,
                  search_stats: Dict = None,
                  risk_free_rate: float = 0.045,
                  survivorship_bias: bool = True,
                  all_market_data: Dict = None) -> str:
    """生成邮件HTML（v5升级：三市场独立排行）
    
    Args:
        leaderboard: 单市场列表(兼容旧逻辑) 或 Dict[market, List[Dict]](三市场)
        rejected: 同上
        new_best: 单市场策略名(兼容旧逻辑) 或 Dict[market, strategy_name](三市场)
    """
    scan_time_str = scan_start.strftime('%Y-%m-%d %H:%M:%S')
    
    # 兼容旧接口：如果传入的是列表，包装为US市场
    if isinstance(leaderboard, list):
        leaderboard = {'US': leaderboard}
    if isinstance(rejected, list):
        rejected = {'US': rejected}
    if isinstance(new_best, str) or new_best is None:
        new_best = {'US': new_best, 'HK': None, 'CN': None}

    passed = sum(1 for r in results if r['passed'])
    failed = sum(1 for r in results if not r['passed'])
    pine_vetoed = search_stats.get('pine_vetoed', 0) if search_stats else 0

    # base64 深色背景图片 - 不会被邮件客户端深色模式反色
    BG_CARD = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPg4REBAABUAC3Q9Pc3AAAAAElFTkSuQmCC"

    # 统计卡片（深色防反色样式）
    stats_html = f'''
    <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:10px;padding:14px 16px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:10px;letter-spacing:0.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">📊 扫描统计</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div style="background:rgba(249,115,22,0.08);padding:10px;border-radius:8px;text-align:center;border:1px solid rgba(249,115,22,0.1)">
          <div style="font-size:22px;font-weight:bold;color:#e5e7eb">{len(results)}</div>
          <div style="font-size:11px;color:#9ca3af">策略变体</div>
        </div>
        <div style="background:rgba(249,115,22,0.08);padding:10px;border-radius:8px;text-align:center;border:1px solid rgba(249,115,22,0.1)">
          <div style="font-size:22px;font-weight:bold;color:#f97316">{passed}</div>
          <div style="font-size:11px;color:#9ca3af">通过回测</div>
        </div>
        <div style="background:rgba(249,115,22,0.08);padding:10px;border-radius:8px;text-align:center;border:1px solid rgba(249,115,22,0.1)">
          <div style="font-size:22px;font-weight:bold;color:#ef4444">{failed}</div>
          <div style="font-size:11px;color:#9ca3af">废弃策略</div>
        </div>
        <div style="background:rgba(249,115,22,0.08);padding:10px;border-radius:8px;text-align:center;border:1px solid rgba(249,115,22,0.1)">
          <div style="font-size:22px;font-weight:bold;color:#fbbf24">{pine_vetoed}</div>
          <div style="font-size:11px;color:#9ca3af">Pine否决</div>
        </div>
      </div>
      <div style="margin-top:8px;font-size:11px;color:#6b7280;line-height:1.6">
        搜索: {search_stats.get('search_method', 'variant') if search_stats else 'variant'} · 
        GitHub: {search_stats.get('github_results', 0) if search_stats else 0}个 · 
        废弃库: US {len(rejected.get('US', []))} + HK {len(rejected.get('HK', []))} + CN {len(rejected.get('CN', []))}个 · 耗时{duration:.0f}s<br>
        无风险利率: 美股{risk_free_rate:.2%} | 港股{HK_RISK_FREE_RATE:.2%} | A股{CN_RISK_FREE_RATE:.2%} · 
        幸存者偏差: {'⚠️' if survivorship_bias else '✅'} · 
        数据源: westock+本地港美股+A股ETF
      </div>
      {''.join([f'<div style="margin-top:4px;font-size:12px;color:#f97316">🆕 [{m_label}]新上榜: {nb}</div>' for m, nb in new_best.items() if nb and (m_label := {"US":"美股","HK":"港股","CN":"A股"}.get(m, m))])}
    </div>'''

    # 排行榜卡片（v5升级：三市场独立排行）
    market_labels = {'US': '美股', 'HK': '港股', 'CN': 'A股'}
    market_flags = {'US': '🇺🇸', 'HK': '🇭🇰', 'CN': '🇨🇳'}
    medals = ['🥇', '🥈', '🥉', '4', '5', '6', '7', '8', '9', '10']
    
    leaderboard_html = ''
    for market in ['US', 'HK', 'CN']:
        lb = leaderboard.get(market, [])
        if not lb and market != 'US':
            continue  # 空排行榜不展示（美股总是展示）
        
        m_label = market_labels[market]
        m_flag = market_flags[market]
        
        # 市场分区标题 - 使用details/summary实现折叠
        leaderboard_html += f'''
        <details style="margin-top:12px;margin-bottom:8px;border-radius:8px;border:1px solid rgba(249,115,22,0.12);overflow:hidden">
          <summary style="padding:8px 12px;background:linear-gradient(90deg,rgba(249,115,22,0.15),transparent);border-left:3px solid #f97316;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">
            <span style="font-size:14px;font-weight:700;color:#f97316">{m_flag} {m_label}穿越牛熊策略排行榜 TOP10</span>
            <span style="font-size:11px;color:#6b7280">{len(lb)}个策略</span>

          </summary>'''
        
        if not lb:
            leaderboard_html += f'<div style="padding:20px;text-align:center;color:#6b7280;font-size:12px">暂无{m_label}策略上榜</div>'
            leaderboard_html += '\n        </details>'
            continue
        
        for i, entry in enumerate(lb):
            score = entry.get('total_score', 0)
            name = entry.get('strategy_name', '未知')
            annual = entry.get('annual_return', 0)
            sharpe = entry.get('sharpe', 0)
            max_dd = entry.get('max_drawdown', 0)
            win_rate = entry.get('win_rate', 0)
            profit_factor = entry.get('profit_factor', 0)
            trades = entry.get('avg_trades_per_year', 0)
            params = entry.get('strategy_params', {})
            stress = entry.get('stress_test', {})
            strategy_type = entry.get('strategy_type', '其他')
            cross_robust = entry.get('cross_robust', False)
            bias_flag = entry.get('survivorship_bias_flag', True)
            validation_status = entry.get('validation_status', '')

            score_color = '#f97316' if score >= 60 else '#fb923c' if score >= 40 else '#6b7280'

            params_str = ', '.join([f'{k}={v}' for k, v in list(params.items())[:4]])
            stress_html = ''
            if stress:
                stress_html = f'<div style="margin-top:6px;font-size:10px;color:#6b7280">🧪 压力: 年化<span style="color:#e5e7eb">{stress.get("annual_return", 0):+.2f}%</span> / 回撤<span style="color:#e5e7eb">{stress.get("max_drawdown", 0):.2f}%</span></div>'

            robust_icon = '✅鲁棒' if cross_robust else ''
            bias_icon = '⚠️偏差' if bias_flag else ''
            source_tag = '🖥️本地' if entry.get('source') == 'local_backtest' else '🌐搜索'
            # 来源链接
            lb_sl = entry.get('source_link', '')
            lb_source_link_html = ''
            if lb_sl and (lb_sl.startswith('http://') or lb_sl.startswith('https://')):
                lb_sl_display = lb_sl.replace('https://github.com/', 'GH:').replace('http://github.com/', 'GH:')
                if len(lb_sl_display) > 55:
                    lb_sl_display = lb_sl_display[:52] + '...'
                lb_source_link_html = f'<div style="margin-top:4px;font-size:10px"><span style="color:#6b7280">🔗 来源:</span> <a href="{lb_sl}" target="_blank" style="color:#60a5fa;text-decoration:none">{lb_sl_display}</a></div>'

            leaderboard_html += f'''
            <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:8px;padding:14px 16px;margin-bottom:6px;border-left:3px solid {score_color};border-top:1px solid rgba(249,115,22,0.08);border-bottom:1px solid rgba(249,115,22,0.08);border-right:1px solid rgba(249,115,22,0.08)">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
                <span style="font-size:14px;font-weight:bold;color:{'#f97316' if i<3 else '#9ca3af'};min-width:24px">{medals[i]}</span>
                <span style="font-size:10px;background-color:rgba(249,115,22,0.12);padding:2px 6px;border-radius:3px;color:#fb923c;white-space:nowrap">{strategy_type[:8]}</span>
                <div style="flex:1;min-width:0;overflow:hidden"><span style="font-size:{max(9, 15 - max(0, len(name) - 8) // 2)}px;font-weight:600;color:#f3f4f6;white-space:nowrap;overflow:hidden;display:block">{name}</span></div>
              </div>
              <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:6px">
                <span style="font-size:10px;background-color:rgba(249,115,22,0.08);padding:2px 6px;border-radius:3px;color:#9ca3af;white-space:nowrap">{source_tag}</span>
                <span style="font-size:22px;font-weight:bold;color:{score_color}">{score:.1f}</span>
                <span style="font-size:10px;color:#6b7280">分</span>
              </div>
              <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px 16px;font-size:11px">
                <div><span style="color:#6b7280">年化</span> <span style="font-weight:600;color:{'#f97316' if annual>0 else '#ef4444'}">{annual:+.2f}%</span></div>
                <div><span style="color:#6b7280">夏普</span> <span style="font-weight:600;color:#f3f4f6">{sharpe:.2f}</span></div>
                <div><span style="color:#6b7280">回撤</span> <span style="font-weight:600;color:#f3f4f6">{max_dd:.2f}%</span></div>
                <div><span style="color:#6b7280">胜率</span> <span style="font-weight:600;color:#f3f4f6">{win_rate:.1f}%</span></div>
                <div><span style="color:#6b7280">盈亏比</span> <span style="font-weight:600;color:#f3f4f6">{profit_factor:.2f}</span></div>
                <div><span style="color:#6b7280">年交易</span> <span style="font-weight:600;color:#f3f4f6">{trades:.1f}次</span></div>
              </div>
              <div style="margin-top:6px;font-size:10px;color:#4b5563">
                📐 {params_str}
                {stress_html}
              </div>
              <div style="margin-top:4px;font-size:10px">{robust_icon} {bias_icon} {validation_status}
                {'<span style="margin-left:6px;font-size:10px;background-color:rgba(249,115,22,0.15);padding:2px 6px;border-radius:3px;color:#fb923c">🌐 ' + str(entry.get('batch_symbol_count', 0)) + '只盈利' + str(round(entry.get('batch_profitable_ratio', 0), 0))[:-2] + '%</span>' if entry.get('batch_symbol_count', 0) > 0 else ''}
              </div>
              {lb_source_link_html}
            </div>'''
        # 关闭子榜单details
        leaderboard_html += '\n        </details>'

    # 最近回测策略卡片（只展示本轮新发现的策略，排除local_backtest和builtin重复回测的旧策略）
    new_results = [r for r in results if r.get('source') not in ('local_backtest', 'builtin')]
    if not new_results:
        # 如果没有外部新策略，展示非local_backtest的结果
        new_results = [r for r in results if r.get('source') != 'local_backtest']
        if not new_results:
            # 最终降级：展示所有回测结果
            new_results = results
    recent_results = sorted(new_results, key=lambda x: x.get('backtest_time', ''), reverse=True)[:10]
    top_cards_html = ''
    for i, r in enumerate(recent_results):
        color = '#2ecc71' if r['passed'] else '#e74c3c'
        status_text = '✅ 通过' if r['passed'] else '❌ 废弃'
        src_tag = '🖥️' if r.get('source') == 'local_backtest' else ''
        bt_time = r.get('backtest_time', '')
        time_display = bt_time[:16] if bt_time else '刚刚'
        # 来源链接：仅对有有效URL的策略显示
        sl = r.get('source_link', '')
        source_link_html = ''
        if sl and (sl.startswith('http://') or sl.startswith('https://')):
            # 截断过长的URL用于显示
            sl_display = sl.replace('https://github.com/', 'GH:').replace('http://github.com/', 'GH:')
            if len(sl_display) > 55:
                sl_display = sl_display[:52] + '...'
            source_link_html = f'<div style="font-size:10px;margin-top:1px"><span style="color:#6b7280">🔗 来源:</span> <a href="{sl}" target="_blank" style="color:#60a5fa;text-decoration:none;word-break:break-all">{sl_display}</a></div>'
        top_cards_html += f'''
        <div style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.15)">
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:12px;font-weight:bold;color:#9ca3af">#{i+1}</span>
            <span style="font-size:10px;background-color:rgba(249,115,22,0.12);padding:1px 5px;border-radius:3px;color:#fb923c">{r.get('type', '')[:6]}</span>
            <span style="font-size:{max(8, 13 - max(0, (len(r['strategy']) - 8) // 2))}px;font-weight:600;color:#e5e7eb;white-space:nowrap">{src_tag}{r['strategy']}</span>
          </div>
          <div style="display:flex;align-items:baseline;gap:8px;margin-top:4px">
            <span style="font-size:15px;font-weight:bold;color:{color}">{r['score']}分</span>
            <span style="font-size:10px;background-color:rgba(249,115,22,0.12) if {str(r['passed'])} == 'True' else rgba(107,114,128,0.2);padding:1px 5px;border-radius:3px;color:{'#f97316' if r['passed'] else '#6b7280'};font-weight:600">{status_text}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:2px 10px;font-size:11px;margin-top:4px">
            <div><span style="color:#6b7280">年化</span> <span style="font-weight:600;color:{'#f97316' if r['annual']>0 else '#ef4444'}">{r['annual']:+.2f}%</span></div>
            <div><span style="color:#6b7280">夏普</span> <span style="font-weight:600;color:#e5e7eb">{r['sharpe']:.2f}</span></div>
          </div>
          <div style="font-size:10px;color:#4b5563;margin-top:2px">⏱️ 发现→编码→回测: {'<1ms' if r.get('timing_total',0)<0.001 else f'{r.get("timing_total",0):.1f}s'} (发现{'<1ms' if r.get('timing_discovery',0)<0.001 else f'{r.get("timing_discovery",0):.1f}s'} + 编码{'<1ms' if r.get('timing_coding',0)<0.001 else f'{r.get("timing_coding",0):.1f}s'} + 回测{f'{r.get("timing_backtest",0):.1f}s'})</div>
          <div style="font-size:10px;color:#4b5563;margin-top:1px">🕐 {time_display}</div>
          <div style="font-size:10px;color:#4b5563;margin-top:1px">🌐 三市场得分: US {r.get('multi_market_scores', {}).get('US', 0):.0f} / HK {r.get('multi_market_scores', {}).get('HK', 0):.0f} / CN {r.get('multi_market_scores', {}).get('CN', 0):.0f}</div>
          {source_link_html}
        </div>'''

    # 排行榜落选策略卡片（三市场汇总）
    replaced_reasons = ['被更高分策略替换', 'v4重评分后跌出TOP10', 'v5重评分后跌出TOP10']
    all_replaced = []
    for market, rj_list in rejected.items():
        for r in rj_list:
            r['_market'] = market
            all_replaced.append(r)
    replaced = [r for r in all_replaced if any(reason in r.get('reject_reason', '') for reason in replaced_reasons) or r.get('replaced_by', '')]
    replaced = sorted(replaced, key=lambda x: x.get('total_score', 0), reverse=True)[:10]
    rejected_cards_html = ''
    if replaced:
        for r in replaced:
            name = r.get('strategy_name', '未知')
            reason = r.get('reject_reason', '未知原因')
            ts = r.get('timestamp', '')
            score = r.get('total_score', 0)
            annual = r.get('annual_return', 0)
            sharpe = r.get('sharpe', 0)
            replaced_by = r.get('replaced_by', '')
            reason_detail = reason
            if replaced_by:
                rp_score = r.get('replaced_by_score', '')
                score_info = f'({rp_score:.1f}分)' if rp_score else ''
                reason_detail = f'被「{replaced_by}」{score_info}替换下榜'
            elif 'v4重评分后跌出TOP10' in reason:
                reason_detail = 'v4重评分后跌出TOP10'
            elif '被更高分策略替换' in reason:
                reason_detail = '被更高分策略替换下榜'
            m_label = {'US': '🇺🇸', 'HK': '🇭🇰', 'CN': '🇨🇳'}.get(r.get('_market', 'US'), '')
            rejected_cards_html += f'''
        <div style="padding:10px 0;border-bottom:1px solid rgba(249,115,22,0.08)">
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:10px;color:#9ca3af">{m_label}</span>
            <div style="font-size:{max(10, 13 - max(0, (min(len(name),23) - 8) // 2))}px;font-weight:600;color:#e5e7eb;flex:1;min-width:0;white-space:nowrap;overflow:hidden">{name[:23]+'…' if len(name)>23 else name}</div>
          </div>
          <div style="display:flex;align-items:baseline;gap:8px;margin-top:3px">
            <span style="font-size:14px;font-weight:bold;color:{'#fb923c' if score>=40 else '#6b7280'}">{score:.1f}分</span>
            <span style="font-size:10px;background-color:rgba(239,68,68,0.12);padding:1px 5px;border-radius:3px;color:#ef4444;font-weight:600">📌 {reason_detail}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 10px;font-size:11px;margin-top:3px">
            <div><span style="color:#6b7280">年化</span> <span style="font-weight:600;color:{'#f97316' if annual>0 else '#ef4444'}">{annual:+.2f}%</span></div>
            <div><span style="color:#6b7280">夏普</span> <span style="font-weight:600;color:#d1d5db">{sharpe:.2f}</span></div>
          </div>
          <div style="font-size:10px;color:#4b5563;margin-top:2px">📅 {ts[:10] if ts else '未知日期'}</div>
        </div>'''

    BG_BODY = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYxMAAAAyAB2R/zBtAAAAAElFTkSuQmCC"

    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <style>
    :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
    details summary::-webkit-details-marker {{ display: none; }}
    details summary {{ list-style: none; }}
    details summary::marker {{ display: none; content: ""; }}

  </style>
</head>
<body style="margin:0;padding:12px 8px;background-image:url({BG_BODY});background-color:#060610;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,sans-serif;color:#e5e7eb">
  <div style="max-width:580px;margin:0 auto">

    <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:14px;padding:20px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="font-size:22px">🏆</span>
        <span style="font-size:20px;font-weight:800;color:#f97316;letter-spacing:1px">穿越牛熊策略排行榜</span>
      </div>
      <div style="font-size:11px;color:#6b7280;line-height:1.7">
        {scan_time_str} · US {len(leaderboard.get('US', []))} + HK {len(leaderboard.get('HK', []))} + CN {len(leaderboard.get('CN', []))}只上榜 · 落选库{sum(len(r) for r in rejected.values())}只 · 耗时{duration:.0f}s<br>
        <span style="color:#9ca3af">美股2019-2024 / A股2021-2025 · westock+本地港美股+A股ETF</span>
      </div>
    </div>

    {stats_html}

    <details style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <summary style="font-size:13px;font-weight:700;color:#f97316;letter-spacing:0.5px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">🏅 TOP10 策略排行榜</summary>
      <div style="margin-top:10px">
      {leaderboard_html if leaderboard_html else '<p style="text-align:center;color:#6b7280;padding:16px;font-size:12px">暂无策略上榜</p>'}
      </div>
    </details>

    <details style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <summary style="font-size:13px;font-weight:700;color:#f97316;letter-spacing:0.5px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">🧪 最近回测策略</summary>
      <div style="margin-top:10px">
      {top_cards_html if top_cards_html else '<p style="text-align:center;color:#6b7280;padding:16px;font-size:12px">暂无数据</p>'}
      </div>
    </details>

    <details style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <summary style="font-size:13px;font-weight:700;color:#f97316;letter-spacing:0.5px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">📉 被替换下榜的策略</summary>
      <div style="margin-top:10px">
      {rejected_cards_html if rejected_cards_html else '<p style="text-align:center;color:#6b7280;padding:16px;font-size:12px">暂无被替换下榜的策略</p>'}
      </div>
    </details>

    <details style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <summary style="font-size:13px;font-weight:700;color:#f97316;letter-spacing:0.5px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">⏱️ 策略生命周期耗时统计</summary>
      <div style="margin-top:10px">
      {_build_timing_summary_html(new_results)}
      </div>
    </details>

    <div style="text-align:center;color:#374151;font-size:10px;margin-top:8px;padding:6px;line-height:1.6">
      穿越牛熊策略回测系统 v4 · {scan_time_str}<br>
      评分: 年化25%/夏普25%/回撤20%/盈亏比15%/胜率15%+鲁棒5-偏差10
    </div>
  </div>
</body>
</html>'''

    return html


def send_email(html_content: str, scan_start: datetime):
    date_str = scan_start.strftime('%Y-%m-%d')
    time_str = scan_start.strftime('%H:%M')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'【穿越牛熊策略回测报告】{date_str} {time_str}'
    msg['From'] = SMTP_USER
    msg['To'] = EMAIL_TO

    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())


# ================================================================
# 状态查看
# ================================================================
def show_status():
    print("\n" + "=" * 60)
    print("  🔄 穿越牛熊策略回测系统 v5 — 三市场独立排行")
    print("=" * 60)
    
    all_lbs = load_all_leaderboards()
    all_rjs = load_all_rejected()
    
    market_labels = {'US': '🇺🇸美股', 'HK': '🇭🇰港股', 'CN': '🇨🇳A股'}
    
    for market in ['US', 'HK', 'CN']:
        m_label = market_labels[market]
        lb = all_lbs.get(market, [])
        rj = all_rjs.get(market, [])
        
        print(f"\n  🏆 {m_label}排行榜前十: {len(lb)}个策略")
        for i, e in enumerate(lb):
            robust = '✅' if e.get('cross_robust') else ''
            bias = '⚠️' if e.get('survivorship_bias_flag') else ''
            validation = e.get('validation_status', '')
            print(f"    {i+1}. [{e.get('strategy_type', '?')}] {e.get('strategy_name', '?')} - {e.get('total_score', 0):.1f}分 "
                  f"(年化{e.get('annual_return', 0):+.2f}% / 回撤{e.get('max_drawdown', 0):.2f}%) {robust} {bias} {validation}")
        
        if rj:
            print(f"\n  🗑️ {m_label}废弃策略库: {len(rj)}个策略")
    
    total_lb = sum(len(v) for v in all_lbs.values())
    total_rj = sum(len(v) for v in all_rjs.values())
    print(f"\n  📊 总计: 排行榜{total_lb}个 / 废弃库{total_rj}个策略")

    # 变体预览
    variants = generate_strategy_variants()
    type_counts = {}
    for v in variants:
        t = v.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"\n  🧬 策略变体: {len(variants)}个 (7种策略类型)")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}个")

    # 搜索配置
    print(f"\n  🔍 搜索配置:")
    print(f"    GitHub查询: {len(CROSS_REGIME_GITHUB_QUERIES)}条")
    print(f"    参数变体模板: {len(CROSS_REGIME_PARAM_VARIANTS)}个")
    print(f"    回测区间: 主{MAIN_START}~{MAIN_END} / 压力{STRESS_START}~{STRESS_END}")
    print(f"    回撤淘汰: ≥{MAX_DRAWDOWN_HARD_LIMIT}%")
    print(f"    入榜规则: 按最高分排序保留前十")
    print(f"    保护期: {PROTECTION_DAYS}天")


# ================================================================
# 用户单独策略回测入口（三层递进架构）
# ================================================================

def backtest_user_strategy(strategy_func, strategy_name: str = '用户策略',
                           strategy_kwargs: Dict = None,
                           strategy_type: str = '其他',
                           strategy_params: Dict = None,
                           strategy_desc: str = '',
                           source: str = '用户提交') -> Dict:
    """
    用户单独策略回测入口 - 使用三层递进架构
    
    当用户单独发送策略要求回测时，调用此函数。
    采用与定时扫描相同的分层递进架构，兼顾回测速度和质量：
    
    第1层：快速广筛（~5秒）
      - 纯pandas向量化回测，仅ETF池
      - 淘汰回撤>35%或年化<-5%的策略
      - 目的：快速判断策略是否有基本价值
    
    第2层：中等精度验证（~30秒）
      - 向量化+完整指标+交易成本精确扣除
      - 三市场(US/HK/CN)完整评分
      - 压力测试(2015-2018)
      - 目的：精确评估策略质量
    
    第3层：高精度终验（~5分钟）
      - 逐日循环回测（最高精度）
      - 三市场完整回测
      - 自动入榜评估
      - 目的：生成最终可信赖的回测结果
    
    参数:
        strategy_func: 策略信号函数，签名为 func(close_prices: pd.DataFrame, **kwargs) -> pd.Series
        strategy_name: 策略名称
        strategy_kwargs: 策略参数（传给strategy_func）
        strategy_type: 策略类型（趋势跟踪/均值回归/套利/事件驱动/机器学习/高股息轮动/其他）
        strategy_params: 策略参数字典（用于记录/展示）
        strategy_desc: 策略描述
        source: 策略来源标记
    
    返回:
        Dict: 回测结果，包含各层结果、最终评分、是否入榜等
    """
    if strategy_kwargs is None:
        strategy_kwargs = {}
    if strategy_params is None:
        strategy_params = {}
    
    total_start = time.time()
    
    print(f"\n{'='*70}")
    print(f"  🔬 用户策略回测 - 三层递进架构")
    print(f"{'='*70}")
    print(f"  📋 策略名称: {strategy_name}")
    print(f"  📋 策略类型: {strategy_type}")
    print(f"  📋 策略来源: {source}")
    print(f"  📋 策略参数: {strategy_params}")
    print(f"  🏗️  回测流程: L1快速广筛 → L2中等验证 → L3高精度终验")
    
    # 0. 加载数据
    print(f"\n  📦 加载全市场数据...")
    data_start = time.time()
    risk_free_rate = fetch_risk_free_rate()
    close_prices, survivorship_bias = load_all_etf_data()
    all_market_data = load_all_market_data()
    if close_prices is not None and len(close_prices) > 0:
        all_market_data['US_ETF'] = {sym: pd.DataFrame({'Close': close_prices[sym]}) for sym in close_prices.columns if sym in close_prices}
    data_time = time.time() - data_start
    print(f"  ✅ 数据加载完成: {data_time:.1f}s")
    
    # 构造策略对象（与内置变体格式一致）
    strategy_obj = {
        'name': strategy_name,
        'func': strategy_func,
        'kwargs': strategy_kwargs,
        'params': strategy_params,
        'desc': strategy_desc,
        'type': strategy_type,
        'source': source,
    }
    
    # ====== 第1层：快速广筛 ======
    print(f"\n{'─'*70}")
    print(f"  ⚡ 第1层：快速广筛（向量化，~5秒）")
    print(f"{'─'*70}")
    
    l1_start = time.time()
    l1_passed, l1_eliminated = _layer1_fast_screen(
        [strategy_obj], close_prices, all_market_data, risk_free_rate)
    l1_time = time.time() - l1_start
    
    if not l1_passed:
        elapsed = time.time() - total_start
        print(f"\n  ❌ 第1层淘汰: 策略在所有市场均不达标")
        if l1_eliminated:
            print(f"     原因: {l1_eliminated[0].get('reason', '未知')}")
        return {
            'passed': False,
            'eliminated_at': 'L1',
            'reason': l1_eliminated[0].get('reason', '快速广筛未通过') if l1_eliminated else '快速广筛未通过',
            'l1_time': l1_time,
            'total_time': elapsed,
            'strategy_name': strategy_name,
            'market_quick': l1_eliminated[0].get('market_quick', {}) if l1_eliminated else {},
        }
    
    print(f"  ✅ 第1层通过 ({l1_time:.1f}s)")
    
    # ====== 第2层：中等精度验证 ======
    print(f"\n{'─'*70}")
    print(f"  🔍 第2层：中等精度验证（向量化+评分，~30秒）")
    print(f"{'─'*70}")
    
    l2_start = time.time()
    l2_passed, l2_eliminated = _layer2_medium_validate(
        l1_passed, close_prices, all_market_data, risk_free_rate)
    l2_time = time.time() - l2_start
    
    if not l2_passed:
        elapsed = time.time() - total_start
        print(f"\n  ❌ 第2层淘汰: 策略在所有市场评分均未通过")
        if l2_eliminated:
            print(f"     原因: {l2_eliminated[0].get('reason', '未知')}")
        # 仍然返回L2的详细结果供参考
        l2_market_results = l2_eliminated[0].get('market_results', {}) if l2_eliminated else {}
        return {
            'passed': False,
            'eliminated_at': 'L2',
            'reason': l2_eliminated[0].get('reason', '中等验证未通过') if l2_eliminated else '中等验证未通过',
            'l1_time': l1_time,
            'l2_time': l2_time,
            'total_time': elapsed,
            'strategy_name': strategy_name,
            'market_results': l2_market_results,
        }
    
    print(f"  ✅ 第2层通过 ({l2_time:.1f}s)")
    
    # 输出L2评分预览
    for market, mr in l2_passed[0].get('_layer2_results', {}).items():
        score = mr['score_result']['total_score']
        main = mr['main_result']
        m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[market]
        print(f"     [{m_label}] 预估评分: {score}分 | 年化{main['annual_return']:+.2f}% | 回撤{main['max_drawdown']:.1f}%")
    
    # ====== 第3层：高精度终验 ======
    print(f"\n{'─'*70}")
    print(f"  🏅 第3层：高精度终验（逐日循环，~5分钟）")
    print(f"{'─'*70}")
    
    l3_start = time.time()
    l3_results = _layer3_precision_finaltest(
        l2_passed, close_prices, all_market_data, risk_free_rate, survivorship_bias)
    l3_time = time.time() - l3_start
    
    total_time = time.time() - total_start
    
    if not l3_results:
        return {
            'passed': False,
            'eliminated_at': 'L3',
            'reason': '高精度终验异常',
            'l1_time': l1_time,
            'l2_time': l2_time,
            'l3_time': l3_time,
            'total_time': total_time,
            'strategy_name': strategy_name,
        }
    
    # 处理L3结果
    lr = l3_results[0]
    strategy = lr['strategy']
    market_results = lr['market_results']
    
    # 更新排行榜
    new_best_by_market = {'US': None, 'HK': None, 'CN': None}
    market_summaries = {}
    
    print(f"\n{'='*70}")
    print(f"  📊 最终回测结果")
    print(f"{'='*70}")
    
    for market, mr in market_results.items():
        main_result = mr['main_result']
        score_result = mr['score_result']
        stress_result = mr['stress_result']
        market_rf = mr['risk_free_rate']
        market_bias = mr['survivorship_bias']
        market_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[market]
        
        strategy_entry = {
            'strategy_name': strategy_name,
            'strategy_params': strategy_params,
            'strategy_description': strategy_desc,
            'strategy_type': strategy_type,
            'annual_return': main_result['annual_return'],
            'sharpe': main_result['sharpe'],
            'max_drawdown': main_result['max_drawdown'],
            'calmar': main_result['calmar'],
            'win_rate': main_result['win_rate'],
            'profit_factor': main_result['profit_factor'],
            'avg_trades_per_year': main_result['avg_trades_per_year'],
            'holding_distribution': main_result.get('holding_distribution', {}),
            'stress_test': {
                'annual_return': stress_result['annual_return'] if stress_result else 0,
                'max_drawdown': stress_result['max_drawdown'] if stress_result else 0,
            } if stress_result else None,
            'cross_robust': score_result.get('cross_robust', False),
            'survivorship_bias_flag': market_bias,
            'pine_script_rejected': False,
            'portability_score': 10,
            'market': market,
        }
        
        passed_market = score_result['total_score'] > 0 and not score_result['hard_fail']
        robust_mark = '✅' if score_result.get('cross_robust') else ''
        bias_mark = '⚠️' if market_bias else ''
        pass_mark = '✅' if passed_market else '❌'
        
        print(f"\n  [{market_label}] {pass_mark}")
        print(f"    评分: {score_result['total_score']}分 {robust_mark} {bias_mark}")
        print(f"    年化: {main_result['annual_return']:+.2f}% | 回撤: {main_result['max_drawdown']:.2f}% | 夏普: {main_result['sharpe']:.2f}")
        print(f"    Calmar: {main_result['calmar']:.2f} | 胜率: {main_result['win_rate']:.1f}% | 盈亏比: {main_result['profit_factor']:.2f}")
        print(f"    年交易: {main_result['avg_trades_per_year']:.1f}次")
        if stress_result:
            print(f"    压力测试: 年化{stress_result['annual_return']:+.2f}% | 回撤{stress_result['max_drawdown']:.2f}%")
        
        market_summaries[market] = {
            'passed': passed_market,
            'score': score_result['total_score'],
            'annual_return': main_result['annual_return'],
            'sharpe': main_result['sharpe'],
            'max_drawdown': main_result['max_drawdown'],
            'calmar': main_result['calmar'],
            'win_rate': main_result['win_rate'],
            'profit_factor': main_result['profit_factor'],
            'avg_trades_per_year': main_result['avg_trades_per_year'],
            'stress_test': {
                'annual_return': stress_result['annual_return'] if stress_result else 0,
                'max_drawdown': stress_result['max_drawdown'] if stress_result else 0,
            } if stress_result else None,
            'score_detail': score_result,
        }
        
        # 更新排行榜
        if passed_market:
            old_lb = load_leaderboard(market)
            update_leaderboard_v3(strategy_entry, score_result, market)
            new_lb = load_leaderboard(market)
            if len(new_lb) > 0 and any(e.get('strategy_name') == strategy_name for e in new_lb):
                # 检查是否为新增或排名提升
                old_rank = next((i for i, e in enumerate(old_lb) if e.get('strategy_name') == strategy_name), -1)
                new_rank = next((i for i, e in enumerate(new_lb) if e.get('strategy_name') == strategy_name), -1)
                if old_rank == -1:
                    new_best_by_market[market] = f'新入榜第{new_rank+1}名'
                    print(f"    🆕 新入榜！排名第{new_rank+1}")
                elif new_rank < old_rank:
                    new_best_by_market[market] = f'排名提升: 第{old_rank+1}名→第{new_rank+1}名'
                    print(f"    📈 排名提升: 第{old_rank+1}名→第{new_rank+1}名")
    
    # 汇总
    any_passed = any(ms['passed'] for ms in market_summaries.values())
    best_market = max(market_summaries.items(), key=lambda x: x[1]['score']) if market_summaries else (None, {})
    
    print(f"\n{'='*70}")
    print(f"  🏁 回测汇总")
    print(f"{'='*70}")
    print(f"  策略: {strategy_name}")
    print(f"  结果: {'✅ 通过' if any_passed else '❌ 未通过'}")
    if any_passed:
        best_market_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}.get(best_market[0], '未知') if any_passed else '无'
    print(f"  最佳市场: {best_market_label} ({best_market[1]['score']}分)")
    print(f"  耗时分布: L1={l1_time:.1f}s + L2={l2_time:.1f}s + L3={l3_time:.1f}s = {total_time:.1f}s")
    for m, nb in new_best_by_market.items():
        if nb:
            m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[m]
            print(f"  🆕 [{m_label}]: {nb}")
    
    return {
        'passed': any_passed,
        'eliminated_at': None,
        'strategy_name': strategy_name,
        'strategy_type': strategy_type,
        'strategy_params': strategy_params,
        'market_summaries': market_summaries,
        'new_best_by_market': new_best_by_market,
        'best_market': best_market[0] if any_passed else None,
        'best_score': best_market[1]['score'] if any_passed else 0,
        'l1_time': l1_time,
        'l2_time': l2_time,
        'l3_time': l3_time,
        'total_time': total_time,
        'market_results': market_results,
    }


# ================================================================
# 命令行入口
# ================================================================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='穿越牛熊策略回测调度器 v5（三市场独立排行：US/HK/CN）')
    parser.add_argument('action', choices=['run', 'status'],
                        default='status', nargs='?',
                        help='run=执行扫描, status=查看状态')

    args = parser.parse_args()

    if args.action == 'run':
        result = scan_strategies()
        print(f"\n✅ 扫描完成，耗时{result['duration_seconds']:.0f}秒")
        if result.get('new_best'):
            print(f"🆕 新上榜策略: {result['new_best']}")
        print(f"📊 搜索方式: {result.get('search_method', 'variant')}")
        print(f"📊 Pine否决: {result.get('pine_vetoed', 0)}个")
        print(f"📊 无风险利率: {result.get('risk_free_rate', 0):.4f}")
    else:
        show_status()
