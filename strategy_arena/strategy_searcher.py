#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略搜索模块
=============
职责: 从公开来源搜索量化策略代码，进行描述性初筛。

搜索来源（按优先级）:
  1. GitHub（vn.py策略库、awesome-quant、Quantopian遗留）
  2. QuantConnect 社区策略库
  3. TradingView Pine Script 公开策略
  4. QuantInsti 博客及课程案例
  5. 聚宽 (JoinQuant) 社区
  6. BigQuant 社区
  7. 雪球量化投资话题

注意: 本模块仅执行搜索和初筛，不执行回测。
      网络搜索依赖 web_search 工具和 browser skill，
      在自动化运行中可能受限，需要优雅降级。
"""

import json
import os
import re
from datetime import datetime
from typing import List, Optional


# ================================================================
# 搜索关键词与过滤
# ================================================================
# 策略定位关键词（初筛用）
TARGET_KEYWORDS = [
    '牛市策略', '趋势跟随', '穿越牛熊', '稳健型', '港美股', '美股', '港股',
    '高股息', '红利', 'bull strategy', 'trend following', 'momentum',
    'robust', 'US stocks', 'HK stocks', 'dividend', 'yield',
    'trend tracking', 'breakout', 'mean reversion',
]

# 排除关键词（过滤掉不相关的策略）
EXCLUDE_KEYWORDS = [
    'crypto', 'bitcoin', 'forex', '期货', '加密', '比特币', '外汇',
    'scalping', '刷单', '日内剥头皮',
    'options', '期权', '期权策略',
]

# 经典策略列表（不受12个月时效限制）
CLASSIC_STRATEGIES = [
    'turtle trading', 'dual moving average', 'donchian breakout',
    'momentum rotation', 'macd crossover', 'rsi mean reversion',
    'bollinger bands', 'supertrend', 'dual momentum',
    '海龟交易', '双均线', '动量轮动', '布林带',
]


# ================================================================
# 搜索查询模板
# ================================================================
SEARCH_QUERIES = [
    # GitHub 搜索
    'site:github.com quantitative trading strategy python stocks backtest 2024 2025',
    'site:github.com vnpy strategy stocks trend following',
    'site:github.com awesome-quant strategy backtest python',
    'site:github.com vectorbt strategy momentum stocks',
    'site:github.com talib strategy python stocks backtest',

    # QuantConnect
    'site:quantconnect.com algorithm framework stocks trend momentum',

    # TradingView
    'site:tradingview.com pine script stocks strategy "Repainting: No" momentum trend',

    # 通用搜索
    'python stocks backtest strategy trend following 2024 site:medium.com OR site:towardsdatascience.com',
    'quantitative trading strategy python stocks momentum 2024',
    '港美股趋势跟随策略 python 回测 2024',
    '美股牛市策略 python 回测代码',
]


# ================================================================
# 描述性初筛
# ================================================================
def initial_filter(strategy_info: dict) -> dict:
    """
    描述性初筛，判断策略是否值得进一步处理。
    
    初筛标准:
      1. 策略定位: 包含目标关键词
      2. 目标指标（参考值，以回测结果为准）
      3. 可落地性: 有代码或可转译的逻辑
      4. 时效性: 更新时间≤12个月或为经典策略
    
    Returns:
      {'passed': bool, 'reason': str, 'is_classic': bool}
    """
    name = strategy_info.get('name', '').lower()
    description = strategy_info.get('description', '').lower()
    code = strategy_info.get('code', '')
    update_time = strategy_info.get('update_time', '')
    source = strategy_info.get('source', '')
    claimed_return = strategy_info.get('claimed_return', None)
    claimed_drawdown = strategy_info.get('claimed_drawdown', None)

    combined_text = f"{name} {description}"

    # 检查排除关键词
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in combined_text:
            return {'passed': False, 'reason': f'排除关键词: {kw}', 'is_classic': False}

    # 检查目标关键词（至少命中一个）
    has_target = any(kw.lower() in combined_text for kw in TARGET_KEYWORDS)
    if not has_target:
        # 也接受通用策略关键词
        generic_keywords = ['strategy', 'backtest', 'trading', '策略', '回测', '交易']
        has_generic = any(kw in combined_text for kw in generic_keywords)
        if not has_generic:
            return {'passed': False, 'reason': '无目标关键词匹配', 'is_classic': False}

    # 检查经典策略
    is_classic = any(cs in combined_text for cs in CLASSIC_STRATEGIES)

    # 时效性检查（非经典策略需12个月内更新）
    if not is_classic and update_time:
        try:
            update_dt = datetime.strptime(update_time[:10], '%Y-%m-%d')
            months_old = (datetime.now() - update_dt).days / 30
            if months_old > 12:
                return {'passed': False, 'reason': f'策略已{months_old:.0f}个月未更新', 'is_classic': False}
        except (ValueError, TypeError):
            pass

    # 可落地性: 必须有代码或可转译的Pine Script
    if not code and 'pine script' not in source.lower() and 'tradingview' not in source.lower():
        return {'passed': False, 'reason': '无可执行代码', 'is_classic': False}

    # 目标指标参考检查（软性，仅作标记）
    warnings = []
    if claimed_return is not None and claimed_return < 15:
        warnings.append(f'声称年化{claimed_return}%<15%')
    if claimed_drawdown is not None and claimed_drawdown > 25:
        return {'passed': False, 'reason': f'声称最大回撤{claimed_drawdown}%>25%（硬性条件）', 'is_classic': False}

    return {
        'passed': True,
        'reason': '通过初筛' + (' (经典策略)' if is_classic else ''),
        'is_classic': is_classic,
        'warnings': warnings,
    }


# ================================================================
# 搜索结果解析
# ================================================================
def parse_search_result(raw_result: dict) -> List[dict]:
    """
    解析搜索结果，提取策略信息。
    适配多种搜索来源的返回格式。
    """
    strategies = []

    # 通用格式解析
    items = raw_result.get('results', [])
    if not items and isinstance(raw_result, list):
        items = raw_result

    for item in items:
        strategy = {
            'name': item.get('title', item.get('name', 'Unknown')),
            'description': item.get('snippet', item.get('description', '')),
            'source_link': item.get('url', item.get('link', '')),
            'source': item.get('source', 'unknown'),
            'code': item.get('code', ''),
            'update_time': item.get('date', item.get('update_time', '')),
            'claimed_return': item.get('claimed_return'),
            'claimed_drawdown': item.get('claimed_drawdown'),
        }
        strategies.append(strategy)

    return strategies


# ================================================================
# 搜索执行（由调度器调用web_search）
# ================================================================
def get_search_queries() -> List[str]:
    """获取搜索查询列表"""
    return SEARCH_QUERIES.copy()


def process_search_results(search_results: List[dict]) -> List[dict]:
    """
    处理搜索结果: 解析 → 初筛 → 返回通过的策略列表
    """
    all_strategies = []
    for result in search_results:
        parsed = parse_search_result(result)
        all_strategies.extend(parsed)

    # 初筛
    passed_strategies = []
    for strategy in all_strategies:
        filter_result = initial_filter(strategy)
        if filter_result['passed']:
            strategy['filter_result'] = filter_result
            strategy['is_classic'] = filter_result.get('is_classic', False)
            passed_strategies.append(strategy)

    return passed_strategies


# ================================================================
# 策略代码提取辅助
# ================================================================
def extract_code_from_github_readme(readme_content: str) -> Optional[str]:
    """从GitHub README中提取Python代码块"""
    # 匹配 ```python ... ``` 代码块
    pattern = r'```python\s*\n(.*?)```'
    matches = re.findall(pattern, readme_content, re.DOTALL)
    if matches:
        # 返回最长的代码块（最可能是完整策略）
        return max(matches, key=len)
    return None


def extract_pine_script(content: str) -> Optional[str]:
    """从网页内容中提取Pine Script代码"""
    pattern = r'```pine\s*\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL)
    if matches:
        return max(matches, key=len)

    # 备选: 查找 //@version 标记
    pattern2 = r'//@version[^\n]*\n(.*?)(?=\n```|\n\s*$)'
    matches2 = re.findall(pattern2, content, re.DOTALL)
    if matches2:
        return max(matches2, key=len)

    return None


# ================================================================
# 单元测试
# ================================================================
if __name__ == '__main__':
    # 测试初筛
    test_strategy_ok = {
        'name': 'EMA Crossover Trend Following Strategy',
        'description': 'A robust trend following strategy for US stocks using EMA crossover with ADX filter',
        'code': 'def generate_signals(close, high, low, open_prices): ...',
        'source': 'github',
        'update_time': '2025-03-15',
        'claimed_return': 22,
        'claimed_drawdown': 18,
    }

    test_strategy_fail = {
        'name': 'Bitcoin Scalping Strategy',
        'description': 'High frequency scalping for crypto',
        'code': '...',
        'source': 'tradingview',
        'claimed_drawdown': 40,
    }

    print(f"✅ 通过初筛: {initial_filter(test_strategy_ok)}")
    print(f"❌ 未通过初筛: {initial_filter(test_strategy_fail)}")
