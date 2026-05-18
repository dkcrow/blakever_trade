#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合策略搜索模块
================
结合方案A(GitHub API搜索)和方案B(参数变体生成)的混合搜索器。

方案A: 使用GitHub Search API搜索公开量化策略代码
方案B: 当方案A被限流或返回不足时，基于内置策略生成参数变体

核心目标:
  - 每次扫描确保至少找到3个新策略（去重后）
  - 优先方案A，限流自动降级方案B
  - 参数变体产生不同指纹，避免重复搜索

指纹机制:
  策略指纹 = SHA256(逻辑代码哈希 + 参数哈希)
  相同逻辑 + 不同参数 = 不同指纹 → 可作为新策略
"""

import json
import os
import re
import copy
import time
import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# GitHub API 配置
GITHUB_API_BASE = 'https://api.github.com'
GITHUB_SEARCH_URL = f'{GITHUB_API_BASE}/search/code'
GITHUB_RATE_LIMIT_URL = f'{GITHUB_API_BASE}/rate_limit'

# 搜索限流检测
RATE_LIMIT_COOLDOWN_FILE = '/tmp/github_rate_limit_cooldown.json'

# ================================================================
# 方案A: GitHub API 搜索
# ================================================================

def _check_github_rate_limit() -> Tuple[bool, int]:
    """
    检查GitHub API剩余请求次数。
    Returns: (是否可用, 剩余次数)
    """
    try:
        import requests
        resp = requests.get(GITHUB_RATE_LIMIT_URL, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            remaining = data.get('resources', {}).get('search', {}).get('remaining', 0)
            reset_time = data.get('resources', {}).get('search', {}).get('reset', 0)
            if remaining > 2:
                return True, remaining
            else:
                # 记录冷却时间
                _save_rate_limit_cooldown(reset_time)
                return False, remaining
        return False, 0
    except Exception as e:
        logger.warning(f"GitHub API限流检查失败: {e}")
        return False, 0


def _save_rate_limit_cooldown(reset_timestamp: int):
    """保存限流冷却时间"""
    try:
        with open(RATE_LIMIT_COOLDOWN_FILE, 'w') as f:
            json.dump({'reset_time': reset_timestamp,
                       'detected_at': datetime.now().isoformat()}, f)
    except Exception:
        pass


def _is_in_cooldown() -> bool:
    """检查是否仍在限流冷却期"""
    if not os.path.exists(RATE_LIMIT_COOLDOWN_FILE):
        return False
    try:
        with open(RATE_LIMIT_COOLDOWN_FILE, 'r') as f:
            data = json.load(f)
        reset_time = data.get('reset_time', 0)
        if time.time() < reset_time:
            return True
        # 冷却期已过，删除文件
        os.remove(RATE_LIMIT_COOLDOWN_FILE)
        return False
    except Exception:
        return False


def _search_github_code(query: str, max_results: int = 5) -> List[dict]:
    """
    使用GitHub Search API搜索策略代码。
    
    Args:
        query: 搜索关键词
        max_results: 最大返回结果数
    
    Returns:
        策略信息列表
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests库未安装，跳过GitHub搜索")
        return []

    # 先检查冷却期
    if _is_in_cooldown():
        logger.info("GitHub API仍在限流冷却期，跳过搜索")
        return []

    # 检查限流
    available, remaining = _check_github_rate_limit()
    if not available:
        logger.info(f"GitHub API限流(剩余{remaining}次)，切换到方案B")
        return []

    params = {
        'q': query,
        'per_page': min(max_results, 10),
        'page': 1,
    }
    headers = {
        'Accept': 'application/vnd.github.v3+json',
    }

    try:
        resp = requests.get(GITHUB_SEARCH_URL, params=params, headers=headers, timeout=15)

        if resp.status_code == 403:
            # 限流
            reset_time = int(resp.headers.get('X-RateLimit-Reset', 0))
            _save_rate_limit_cooldown(reset_time)
            logger.warning(f"GitHub API限流(403)，冷却至{reset_time}")
            return []

        if resp.status_code == 429:
            # 请求过多
            retry_after = int(resp.headers.get('Retry-After', 60))
            _save_rate_limit_cooldown(int(time.time()) + retry_after)
            logger.warning(f"GitHub API请求过多(429)，冷却{retry_after}秒")
            return []

        if resp.status_code != 200:
            logger.warning(f"GitHub API返回{resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        items = data.get('items', [])
        strategies = []

        for item in items[:max_results]:
            repo = item.get('repository', {})
            repo_name = repo.get('full_name', '')
            repo_url = repo.get('html_url', '')
            file_name = item.get('name', '')
            file_url = item.get('html_url', '')
            raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/{item.get('path', '')}"

            strategy = {
                'name': file_name.replace('.py', '').replace('_', ' ').title(),
                'description': f"来自GitHub仓库 {repo_name} 的策略代码",
                'source': 'github',
                'source_link': file_url,
                'raw_url': raw_url,
                'repo_name': repo_name,
                'file_name': file_name,
                'update_time': datetime.now().strftime('%Y-%m-%d'),
            }
            strategies.append(strategy)

        return strategies

    except requests.exceptions.Timeout:
        logger.warning("GitHub API请求超时")
        return []
    except Exception as e:
        logger.warning(f"GitHub API搜索异常: {e}")
        return []


def _fetch_github_code(raw_url: str) -> Optional[str]:
    """从GitHub raw URL获取代码内容"""
    try:
        import requests
        resp = requests.get(raw_url, timeout=15)
        if resp.status_code == 200:
            code = resp.text
            # 验证是否包含策略相关内容
            if _is_valid_strategy_code(code):
                return code
        return None
    except Exception:
        return None


def _is_valid_strategy_code(code: str) -> bool:
    """验证代码是否是有效的策略代码（包含generate_signals或类似函数）"""
    if not code or len(code.strip()) < 50:
        return False
    # 检查关键函数/特征
    strategy_indicators = [
        'generate_signals', 'def signal', 'entries', 'exits',
        'backtest', 'strategy', 'moving_average', 'crossover',
        'supertrend', 'bollinger', 'rsi', 'macd', 'atr',
    ]
    code_lower = code.lower()
    return any(ind in code_lower for ind in strategy_indicators)


def github_search(queries: List[str], max_per_query: int = 3) -> List[dict]:
    """
    执行GitHub搜索（方案A主入口）。
    
    Args:
        queries: 搜索查询列表
        max_per_query: 每条查询最大结果数
    
    Returns:
        包含代码的策略列表
    """
    all_results = []
    rate_limited = False

    for query in queries[:5]:  # 最多5条查询
        if rate_limited:
            break
        results = _search_github_code(query, max_results=max_per_query)
        if results:
            # 尝试获取代码
            for result in results:
                raw_url = result.get('raw_url', '')
                if raw_url:
                    code = _fetch_github_code(raw_url)
                    if code:
                        result['code'] = code
                        all_results.append(result)
                    time.sleep(0.5)  # 礼貌延迟
        else:
            # 可能被限流了
            if _is_in_cooldown():
                rate_limited = True
                break

        time.sleep(1.0)  # 搜索间隔1秒

    return all_results


# ================================================================
# 方案B: 参数变体生成
# ================================================================

# 牛市策略参数变体模板
BULL_PARAM_VARIANTS = [
    {
        'base_strategy': 'ema_adx',
        'name': 'EMA交叉+ADX趋势过滤(快周期12)',
        'param_overrides': {'ema_fast': 12, 'ema_slow': 20, 'adx_threshold': 18},
        'description': 'EMA12/20交叉+ADX>18宽松过滤，更快响应短期趋势变化。',
    },
    {
        'base_strategy': 'ema_adx',
        'name': 'EMA交叉+ADX趋势过滤(慢周期30)',
        'param_overrides': {'ema_fast': 10, 'ema_slow': 30, 'adx_threshold': 20},
        'description': 'EMA10/30交叉+ADX>20，使用更长慢线过滤噪音信号。',
    },
    {
        'base_strategy': 'ema_adx',
        'name': 'EMA交叉+ADX趋势过滤(紧过滤)',
        'param_overrides': {'ema_fast': 10, 'ema_slow': 20, 'adx_threshold': 25},
        'description': 'EMA10/20交叉+ADX>25严格趋势过滤，减少震荡市假信号。',
    },
    {
        'base_strategy': 'supertrend',
        'name': 'Supertrend趋势(低倍率1.5x)',
        'param_overrides': {'atr_period': 10, 'atr_multiplier': 1.5},
        'description': 'Supertrend 1.5x ATR，对趋势变化更敏感，持仓时间更长。',
    },
    {
        'base_strategy': 'supertrend',
        'name': 'Supertrend趋势(高倍率4.0x)',
        'param_overrides': {'atr_period': 10, 'atr_multiplier': 4.0},
        'description': 'Supertrend 4.0x ATR，更宽松的趋势判断，减少震荡市止损。',
    },
    {
        'base_strategy': 'supertrend',
        'name': 'Supertrend趋势(长周期20)',
        'param_overrides': {'atr_period': 20, 'atr_multiplier': 3.0},
        'description': 'Supertrend 20日ATR，平滑噪音，适合中长线趋势跟踪。',
    },
    {
        'base_strategy': 'bollinger_reversion',
        'name': '布林带回归(宽通道2.5σ)',
        'param_overrides': {'bb_period': 20, 'bb_std': 2.5},
        'description': '布林带2.5倍标准差，更宽通道减少交易频率但信号更可靠。',
    },
    {
        'base_strategy': 'bollinger_reversion',
        'name': '布林带回归(短周期10)',
        'param_overrides': {'bb_period': 10, 'bb_std': 2.0},
        'description': '布林带10日周期，对价格波动响应更快，适合短线均值回归。',
    },
    {
        'base_strategy': 'keltner_breakout',
        'name': 'Keltner突破(低倍率1.0x)',
        'param_overrides': {'atr_period': 20, 'atr_multiplier': 1.0},
        'description': 'Keltner通道1.0x ATR，通道更窄更容易触发突破信号。',
    },
    {
        'base_strategy': 'keltner_breakout',
        'name': 'Keltner突破(高倍率2.5x)',
        'param_overrides': {'atr_period': 20, 'atr_multiplier': 2.5},
        'description': 'Keltner通道2.5x ATR，通道更宽信号更可靠但频率低。',
    },
    {
        'base_strategy': 'dual_momentum',
        'name': 'Dual Momentum(6M/3M)',
        'param_overrides': {'lookback_long': 6, 'lookback_short': 3},
        'description': '6月绝对动量+3月相对动量，更短回看期适应市场变化。',
    },
    {
        'base_strategy': 'donchian',
        'name': 'Donchian突破(10/5)',
        'param_overrides': {'entry_window': 10, 'exit_window': 5},
        'description': '10日新高入场5日新低出场，更快进出适合短线趋势。',
    },
    {
        'base_strategy': 'donchian',
        'name': 'Donchian突破(55/20)',
        'param_overrides': {'entry_window': 55, 'exit_window': 20},
        'description': '55日新高入场20日新低出场，经典海龟长线参数。',
    },
    {
        'base_strategy': 'rsi_pullback',
        'name': 'RSI回调买入(宽松25/75)',
        'param_overrides': {'rsi_period': 14, 'rsi_oversold': 25, 'rsi_overbought': 75},
        'description': 'RSI 25/75阈值，更宽松的超卖超买判断，更多交易机会。',
    },
    {
        'base_strategy': 'macd_supertrend',
        'name': 'MACD+Supertrend(快MACD)',
        'param_overrides': {'macd_fast': 8, 'macd_slow': 21, 'atr_multiplier': 3.0},
        'description': 'MACD 8/21快线+Supertrend，更快响应趋势转折。',
    },
    {
        'base_strategy': 'triple_ema',
        'name': 'Triple EMA(5/15/30)',
        'param_overrides': {'ema_short': 5, 'ema_mid': 15, 'ema_long': 30},
        'description': 'EMA 5/15/30短周期，更快响应趋势但噪音更多。',
    },
    {
        'base_strategy': 'vwap_trend',
        'name': 'VWAP趋势(10日短周期)',
        'param_overrides': {'vwap_period': 10},
        'description': 'VWAP 10日短周期，更快响应趋势变化。',
    },
    {
        'base_strategy': 'rsi_trend_confirm',
        'name': 'RSI趋势确认(35/65区间)',
        'param_overrides': {'rsi_period': 14, 'rsi_lower': 35, 'rsi_upper': 65},
        'description': 'RSI 35-65确认区间，更宽松的趋势确认条件。',
    },
]

# 震荡市策略参数变体模板
RANGE_PARAM_VARIANTS = [
    {
        'base_strategy': 'bollinger_mean_reversion',
        'name': '布林带回归(宽通道2.5σ)',
        'param_overrides': {'bb_period': 20, 'bb_std': 2.5},
        'description': '布林带2.5σ更宽通道，减少震荡市频繁交易。',
    },
    {
        'base_strategy': 'bollinger_mean_reversion',
        'name': '布林带回归(短周期10)',
        'param_overrides': {'bb_period': 10, 'bb_std': 2.0},
        'description': '布林带10日周期，对价格波动响应更快。',
    },
    {
        'base_strategy': 'rsi_range_trading',
        'name': 'RSI区间(25/75阈值)',
        'param_overrides': {'rsi_period': 14, 'rsi_low': 25, 'rsi_high': 75},
        'description': 'RSI 25/75更宽松阈值，更多交易机会。',
    },
    {
        'base_strategy': 'rsi_range_trading',
        'name': 'RSI区间(短周期7)',
        'param_overrides': {'rsi_period': 7, 'rsi_low': 30, 'rsi_high': 70},
        'description': 'RSI 7日短周期，更快响应价格变化。',
    },
    {
        'base_strategy': 'keltner_squeeze',
        'name': 'Keltner挤压(长周期30)',
        'param_overrides': {'ema_period': 30, 'atr_mult': 1.5},
        'description': 'Keltner 30日周期，更稳定的挤压检测。',
    },
    {
        'base_strategy': 'donchian_reversion',
        'name': 'Donchian回归(10日通道)',
        'param_overrides': {'channel_period': 10},
        'description': 'Donchian 10日短通道，更频繁的区间交易信号。',
    },
    {
        'base_strategy': 'donchian_reversion',
        'name': 'Donchian回归(30日通道)',
        'param_overrides': {'channel_period': 30},
        'description': 'Donchian 30日长通道，更宽区间更少假信号。',
    },
    {
        'base_strategy': 'macd_histogram_reversal',
        'name': 'MACD反转(快线8/21)',
        'param_overrides': {'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 9},
        'description': 'MACD 8/21快线，更快的反转信号检测。',
    },
    {
        'base_strategy': 'bias_mean_reversion',
        'name': '均线乖离(长周期30)',
        'param_overrides': {'ema_slow': 30, 'bias_threshold': 3.0},
        'description': '30日均线乖离，更长周期更稳定的均值回归。',
    },
    {
        'base_strategy': 'bias_mean_reversion',
        'name': '均线乖离(窄阈值2.0%)',
        'param_overrides': {'ema_slow': 20, 'bias_threshold': 2.0},
        'description': '乖离阈值2.0%，更敏感的高抛低吸。',
    },
]

# 熊市策略参数变体模板
BEAR_PARAM_VARIANTS = [
    {
        'base_strategy': 'rsi_oversold_bounce',
        'name': 'RSI超卖反弹(宽松25/75)',
        'param_overrides': {'rsi_period': 14, 'oversold': 25, 'overbought': 75},
        'description': 'RSI 25/75宽松阈值，更多超跌反弹交易机会。',
    },
    {
        'base_strategy': 'rsi_oversold_bounce',
        'name': 'RSI超卖反弹(短周期7)',
        'param_overrides': {'rsi_period': 7, 'oversold': 30, 'overbought': 70},
        'description': 'RSI 7日短周期，更快捕捉超跌反弹。',
    },
    {
        'base_strategy': 'supertrend_short',
        'name': 'Supertrend做空(低倍率2.0x)',
        'param_overrides': {'atr_period': 10, 'atr_mult': 2.0},
        'description': 'Supertrend 2.0x ATR做空，更敏感的做空信号。',
    },
    {
        'base_strategy': 'supertrend_short',
        'name': 'Supertrend做空(长周期20)',
        'param_overrides': {'atr_period': 20, 'atr_mult': 3.0},
        'description': 'Supertrend 20日ATR做空，过滤短期噪音。',
    },
    {
        'base_strategy': 'bollinger_bear_reversion',
        'name': '布林带熊市(宽通道2.5σ)',
        'param_overrides': {'bb_period': 20, 'bb_std': 2.5},
        'description': '布林带2.5σ宽通道，减少熊市假信号。',
    },
    {
        'base_strategy': 'macd_short',
        'name': 'MACD死叉做空(快线8/21)',
        'param_overrides': {'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 9},
        'description': 'MACD 8/21快线死叉做空，更快响应趋势反转。',
    },
    {
        'base_strategy': 'ema_short',
        'name': 'EMA空头排列(5/15/30)',
        'param_overrides': {'ema_fast': 5, 'ema_mid': 15, 'ema_slow': 30},
        'description': 'EMA 5/15/30空头排列，更短周期更快识别趋势。',
    },
    {
        'base_strategy': 'vix_timing',
        'name': 'VIX择时(低阈值1.2)',
        'param_overrides': {'vol_threshold': 1.2, 'vol_lookback': 30},
        'description': '波动率阈值1.2，更早切换避险资产。',
    },
    {
        'base_strategy': 'dividend_defense',
        'name': '高股息防御(紧止损2.0xATR)',
        'param_overrides': {'atr_mult': 2.0, 'ema_period': 50},
        'description': '2.0x ATR紧止损+50日均线过滤，更严格的风控。',
    },
    {
        'base_strategy': 'low_vol_rotation',
        'name': '低波轮动(短周期20)',
        'param_overrides': {'vol_lookback': 20, 'vol_threshold': 0.25},
        'description': '20日波动率排序轮动，更快适应波动率变化。',
    },
]


def _apply_param_overrides_to_code(code: str, param_overrides: dict) -> str:
    """
    将参数覆盖应用到策略代码中。
    替换STRATEGY_PARAMS字典和函数默认参数值。
    """
    if not param_overrides:
        return code

    modified_code = code

    # 替换 STRATEGY_PARAMS 中的参数
    for param_name, param_value in param_overrides.items():
        # 替换 STRATEGY_PARAMS 字典中的值
        # 格式: 'param_name': value 或 'param_name':value
        if isinstance(param_value, int):
            pattern = rf"('{param_name}'\s*:\s*)\d+"
            replacement = rf"\g<1>{param_value}"
            modified_code = re.sub(pattern, replacement, modified_code)
        elif isinstance(param_value, float):
            pattern = rf"('{param_name}'\s*:\s*)\d+\.?\d*"
            replacement = rf"\g<1>{param_value}"
            modified_code = re.sub(pattern, replacement, modified_code)

        # 替换函数参数默认值
        # 格式: param_name=value 或 param_name = value
        if isinstance(param_value, int):
            pattern = rf"({param_name}\s*=\s*)\d+"
            replacement = rf"\g<1>{param_value}"
            modified_code = re.sub(pattern, replacement, modified_code)
        elif isinstance(param_value, float):
            pattern = rf"({param_name}\s*=\s*)\d+\.?\d*"
            replacement = rf"\g<1>{param_value}"
            modified_code = re.sub(pattern, replacement, modified_code)

    return modified_code


def generate_param_variants(
    builtin_strategies: List[dict],
    variant_templates: List[dict],
    existing_fingerprints: set = None,
    min_new: int = 3,
    strategy_code_dirs: List[str] = None,
) -> List[dict]:
    """
    从内置策略生成参数变体（方案B主入口）。

    Args:
        builtin_strategies: 内置策略列表（含code字段）
        variant_templates: 参数变体模板列表
        existing_fingerprints: 已存在的指纹集合（用于去重）
        min_new: 最少需要的新策略数量
        strategy_code_dirs: 策略代码目录列表（优先于默认目录）

    Returns:
        新策略列表（去重后）
    """
    from strategy_dedup import compute_strategy_fingerprint

    if existing_fingerprints is None:
        existing_fingerprints = set()

    # 建立内置策略 base_name → code 映射
    # 优先从策略文件目录直接读取（base_strategy如'ema_adx'就是文件名）
    builtin_map = {}

    # 方法1: 从策略文件目录直接读取（最可靠）
    _default_dirs = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'strategies'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'range_strategies'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bear_strategies'),
    ]
    search_dirs = (strategy_code_dirs or []) + _default_dirs
    for sdir in search_dirs:
        if os.path.isdir(sdir):
            for fname in os.listdir(sdir):
                if fname.endswith('.py') and not fname.startswith('__'):
                    key = fname[:-3]  # 去掉.py后缀
                    fpath = os.path.join(sdir, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            builtin_map[key] = f.read()
                    except Exception:
                        pass

    # 方法2: 从传入的内置策略列表补充
    for s in builtin_strategies:
        name = s.get('name', '')
        code = s.get('code', '')
        source_link = s.get('source_link', '')
        if code:
            # 用source_link中的文件名匹配（如'local:run_alternative_strategies.py'中的key）
            builtin_map[name] = code
            # 也用简化名匹配
            simple_name = re.sub(r'[（）()\s]', '', name)
            builtin_map[simple_name] = code

    new_variants = []
    deduped_count = 0

    for template in variant_templates:
        base_name = template.get('base_strategy', '')
        variant_name = template.get('name', '')
        param_overrides = template.get('param_overrides', {})
        description = template.get('description', '')

        # 查找基础策略代码
        base_code = builtin_map.get(base_name)

        if not base_code:
            # 尝试模糊匹配
            for key, code in builtin_map.items():
                if base_name in key or key in base_name:
                    base_code = code
                    break

        if not base_code:
            continue

        # 应用参数覆盖
        modified_code = _apply_param_overrides_to_code(base_code, param_overrides)

        if modified_code == base_code and param_overrides:
            # 参数替换未生效，仍然保留（可能是代码结构不同但逻辑有差异）
            pass

        # 计算指纹检查去重
        fingerprint = compute_strategy_fingerprint(modified_code, param_overrides)

        # 检查与已有指纹是否重复（忽略market字段，因为此时不知道market）
        fp_exists = any(fp == fingerprint for fp, mkt in existing_fingerprints)

        if fp_exists:
            deduped_count += 1
            continue

        variant = {
            'name': variant_name,
            'description': description,
            'source': 'param_variant',
            'source_link': f'variant:{base_name}',
            'code': modified_code,
            'strategy_type': '参数变体',
            'update_time': datetime.now().strftime('%Y-%m-%d'),
            'is_classic': False,
            'param_overrides': param_overrides,
            '_fingerprint_preview': fingerprint[:12],
        }

        new_variants.append(variant)

    if deduped_count > 0:
        print(f"    🔄 参数变体去重: {deduped_count}个已存在跳过")

    return new_variants


# ================================================================
# GitHub搜索查询生成
# ================================================================

BULL_GITHUB_QUERIES = [
    'generate_signals+stocks+language:python+path:strategy',
    'vectorbt+strategy+backtest+language:python',
    'trend+following+stocks+python+def+entries',
    'momentum+strategy+backtest+python+ema+adx',
    'supertrend+stocks+python+generate_signals',
]

RANGE_GITHUB_QUERIES = [
    'mean+reversion+stocks+python+generate_signals',
    'bollinger+band+strategy+python+backtest',
    'range+trading+rsi+python+def+entries',
    'grid+trading+stocks+python+backtest',
    'pairs+trading+mean+reversion+python',
]

BEAR_GITHUB_QUERIES = [
    'short+selling+strategy+python+backtest',
    'bear+market+defensive+stocks+python',
    'vix+timing+strategy+python+generate_signals',
    'defensive+stocks+low+volatility+python',
    'safe+haven+rotation+python+backtest',
]


# ================================================================
# 混合搜索主入口
# ================================================================

def hybrid_search(
    market_type: str,
    builtin_strategies: List[dict],
    variant_templates: List[dict],
    existing_fingerprints: set,
    min_new: int = 3,
    github_queries: List[str] = None,
    strategy_code_dirs: List[str] = None,
) -> Tuple[List[dict], dict]:
    """
    混合搜索主入口：方案A(GitHub) → 方案B(参数变体)

    Args:
        market_type: 市场类型 ('bull'/'range'/'bear')
        builtin_strategies: 内置策略列表
        variant_templates: 参数变体模板列表
        existing_fingerprints: 已存在的指纹集合 (fingerprint, market) 二元组
        min_new: 去重后至少需要的新策略数量
        github_queries: GitHub搜索查询列表
        strategy_code_dirs: 策略代码目录列表（用于参数变体生成）

    Returns:
        (新策略列表, 搜索统计信息)
    """
    stats = {
        'github_searched': False,
        'github_results': 0,
        'github_rate_limited': False,
        'variant_generated': 0,
        'total_found': 0,
        'after_dedup': 0,
        'search_method': '',
    }

    all_strategies = []

    # ====== 方案A: 多源搜索（GitHub + awesome-quant + DuckDuckGo + TV间接等） ======
    print(f"  🌐 方案A: 多源策略搜索...")
    if github_queries:
        try:
            from multi_source_searcher import multi_source_search as _multi_search
            
            # 确定搜索的市场类型映射
            search_type = market_type  # bull/range/bear/cross_regime
            if search_type not in ('bull', 'range', 'bear', 'cross_regime'):
                search_type = 'cross_regime'
            
            # v8: 启用全部9个搜索来源，最大化策略多样性
            multi_results, multi_stats = _multi_search(
                market_type=search_type,
                min_new=min_new,
                enabled_sources=['joinquant', 'github', 'github_topics', 'awesome_quant', 
                                'google', 'quantconnect', 'tradingview',
                                'quantinsti', 'chinese_platforms'],
            )
            
            stats['github_searched'] = True
            stats['github_results'] = multi_stats.get('per_source', {}).get('github', 0)
            stats['multi_source_results'] = sum(multi_stats.get('per_source', {}).values())
            stats['search_method'] = 'multi_source'
            
            # 标记限流状态
            if multi_stats.get('per_source', {}).get('github', 0) == 0:
                stats['github_rate_limited'] = True
            
            if multi_results:
                print(f"    ✅ 多源搜索返回 {len(multi_results)} 个策略 "
                      f"(来源: {multi_stats.get('per_source', {})})")
                # 转换为hybrid_searcher兼容格式
                for r in multi_results:
                    strategy = {
                        'name': r.get('name', 'Unknown'),
                        'description': r.get('description', ''),
                        'source': f"multi:{r.get('source', 'unknown')}",
                        'source_link': r.get('source_link', ''),
                        'code': r.get('code', ''),
                        'stars': r.get('stars', 0),
                        'is_classic': r.get('is_classic', False),
                    }
                    all_strategies.append(strategy)
            else:
                print(f"    ⚠️ 多源搜索无结果")
                
        except ImportError:
            logger.warning("multi_source_searcher未找到，降级到单源GitHub搜索")
            # 降级到原始GitHub搜索
            github_results = github_search(github_queries, max_per_query=2)
            stats['github_searched'] = True
            stats['github_results'] = len(github_results)
            if _is_in_cooldown():
                stats['github_rate_limited'] = True
            if github_results:
                all_strategies.extend(github_results)
        except Exception as e:
            logger.warning(f"多源搜索异常: {e}，降级到单源GitHub搜索")
            github_results = github_search(github_queries, max_per_query=2)
            stats['github_searched'] = True
            stats['github_results'] = len(github_results)
            if github_results:
                all_strategies.extend(github_results)
    else:
        print(f"    ⏭️ 未提供搜索查询，跳过多源搜索")

    # ====== 去重检查方案A结果 ======
    from strategy_dedup import compute_strategy_fingerprint

    new_from_github = []
    for s in all_strategies:
        code = s.get('code', '')
        if not code or len(code.strip()) < 20:
            continue
        params = s.get('param_overrides', s.get('strategy_params', {}))
        fp = compute_strategy_fingerprint(code, params)
        s['fingerprint_preview'] = fp[:12]
        # 暂时无法按market去重，因为还没分配market，先收集
        new_from_github.append(s)

    # ====== 方案B: 参数变体 ======
    # 如果GitHub结果不足min_new，或被限流，则生成参数变体
    need_variants = len(new_from_github) < min_new or stats['github_rate_limited']

    variant_strategies = []
    if need_variants:
        print(f"  🔧 方案B: 生成参数变体（GitHub结果{len(new_from_github)}个 < {min_new}个最少需求）...")
        variant_strategies = generate_param_variants(
            builtin_strategies, variant_templates, existing_fingerprints, min_new,
            strategy_code_dirs=strategy_code_dirs,
        )
        stats['variant_generated'] = len(variant_strategies)
        print(f"    ✅ 生成 {len(variant_strategies)} 个参数变体")
    else:
        print(f"  ✅ 方案A结果充足({len(new_from_github)}个)，无需方案B")

    # 合并所有策略
    all_strategies = new_from_github + variant_strategies
    stats['total_found'] = len(all_strategies)

    # 最终去重（需要知道market，但此时还没分配，返回全部让调度器去重）
    stats['after_dedup'] = len(all_strategies)
    stats['search_method'] = 'multi_source' if not need_variants else \
                             ('variant' if not new_from_github else 'multi_source+variant')

    return all_strategies, stats


# ================================================================
# 单元测试
# ================================================================
if __name__ == '__main__':
    # 测试参数覆盖
    test_code = """
STRATEGY_PARAMS = {'ema_fast': 10, 'ema_slow': 20, 'adx_threshold': 20}

def generate_signals(close, high, low, open_prices, ema_fast=10, ema_slow=20, adx_threshold=20):
    pass
"""
    overrides = {'ema_fast': 12, 'adx_threshold': 25}
    modified = _apply_param_overrides_to_code(test_code, overrides)
    print("原始代码:")
    print(test_code)
    print("\n修改后代码:")
    print(modified)

    # 测试指纹差异
    from strategy_dedup import compute_strategy_fingerprint
    fp1 = compute_strategy_fingerprint(test_code, {'ema_fast': 10, 'ema_slow': 20})
    fp2 = compute_strategy_fingerprint(modified, overrides)
    print(f"\n原指纹: {fp1[:12]}")
    print(f"新指纹: {fp2[:12]}")
    print(f"指纹不同: {fp1 != fp2}")
