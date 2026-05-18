#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
熊市策略搜索模块
=================
职责: 搜索熊市/做空/避险/防御型量化策略代码，进行描述性初筛。

搜索来源（按优先级）:
  1. QuantConnect 社区策略库（Bear Market, Short, Hedge, Low Volatility）
  2. TradingView Pine Script 公开策略（Repainting: No）
  3. GitHub（vn.py策略库、awesome-quant、Quantopian遗留）
  4. QuantInsti 博客及课程案例
  5. 聚宽 (JoinQuant) 社区
  6. BigQuant 社区及AI量化策略
  7. 雪球 (Xueqiu) 量化投资话题

搜索时效性:
  - 优先抓取更新时间 ≤ 12个月的策略
  - 经典熊市防御策略（保护性看跌期权、高股息低波、趋势反转做空）不受此限

策略筛选标准（熊市特别版）:
  - 策略定位关键词: 熊市策略、做空、Short、逆势、避险、防御型、
    低波动、高股息、红利、对冲、配对交易、均值回归(超跌反弹)、
    趋势反转、黄金、国债、VIX、避险资产
  - 目标指标: 年化≥8%(理想≥12%), 盈亏比≥1.8, 胜率≥45%,
    单标年交易≥40次, 最大回撤≤20%
  - 可落地性: Python代码或可转译的逻辑（Pine Script一票否决制）
"""

import json
import os
import re
from datetime import datetime
from typing import List, Optional


# ================================================================
# 熊市策略定位关键词
# ================================================================
BEAR_TARGET_KEYWORDS = [
    # 中文
    '熊市策略', '做空', '逆势', '避险', '防御型', '低波动',
    '高股息', '红利', '对冲', '配对交易', '均值回归', '超跌反弹',
    '趋势反转', '黄金', '国债', 'VIX', '避险资产', '恐慌指数',
    '空仓', '反手', '逆势交易', '安全边际',
    # 英文
    'bear market', 'short', 'hedge', 'low volatility', 'defensive',
    'dividend', 'yield', 'mean reversion', 'oversold bounce',
    'trend reversal', 'gold', 'treasury', 'bond', 'vix', 'safe haven',
    'pair trading', 'pairs trading', 'inverse', 'contra',
    'protective put', 'covered call', 'defensive rotation',
    'flight to quality', 'risk-off', 'risk parity',
    'short selling', 'market neutral', 'long-short',
]

# 排除关键词
EXCLUDE_KEYWORDS = [
    'crypto', 'bitcoin', 'forex', '期货', '加密', '比特币', '外汇',
    'scalping', '刷单', '日内剥头皮', 'options', '期权策略',
    '牛市专用', 'bull only', '趋势跟随',  # 排除纯牛市策略
]

# 经典熊市防御策略（不受12个月时效限制）
CLASSIC_BEAR_STRATEGIES = [
    'protective put', 'covered call', 'turtle trading',
    'dual moving average', 'donchian breakout',
    'mean reversion', 'bollinger bands', 'supertrend',
    'pairs trading', 'market neutral', 'risk parity',
    'high dividend', 'low volatility', 'defensive rotation',
    'flight to quality', 'inverse etf',
    '保护性看跌', '高股息低波', '趋势反转做空', '避险轮动',
    '配对交易', '均值回归',
]


# ================================================================
# 搜索查询模板（熊市专用）
# ================================================================
BEAR_SEARCH_QUERIES = [
    # QuantConnect
    'site:quantconnect.com algorithm framework stocks bear market short hedge low volatility',
    'site:quantconnect.com algorithm pairs trading mean reversion defensive stocks',

    # TradingView
    'site:tradingview.com pine script stocks bear strategy "Repainting: No" short hedge',
    'site:tradingview.com pine script defensive dividend low volatility stocks strategy',

    # GitHub
    'site:github.com quantitative trading strategy python stocks bear market short backtest 2024 2025',
    'site:github.com vnpy strategy stocks mean reversion pairs trading hedge',
    'site:github.com vectorbt strategy defensive stocks low volatility dividend',
    'site:github.com python backtest bear market strategy short selling hedge',

    # 通用搜索
    'python stocks backtest bear market defensive strategy low volatility 2024',
    'quantitative trading bear market strategy python short hedge pairs 2024',
    '港美股熊市防御策略 python 回测 做空 对冲 2024',
    '美股避险策略 python 回测 黄金 国债 VIX',
    'mean reversion oversold bounce python stocks backtest strategy',
    'protective put covered call python backtest strategy stocks',
    'flight to quality rotation strategy python stocks gold treasury',
]


# ================================================================
# 熊市策略描述性初筛
# ================================================================
def bear_initial_filter(strategy_info: dict) -> dict:
    """
    熊市策略描述性初筛。

    初筛标准:
      1. 策略定位: 包含熊市/做空/避险/防御型等关键词
      2. 目标指标（参考值，以回测结果为准）
      3. 可落地性: 有代码或可转译的逻辑
      4. 时效性: 更新时间≤12个月或为经典策略
      5. Pine Script一票否决制标记

    Returns:
      {'passed': bool, 'reason': str, 'is_classic': bool, 'strategy_category': str}
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
            return {'passed': False, 'reason': f'排除关键词: {kw}',
                    'is_classic': False, 'strategy_category': ''}

    # 检查熊市目标关键词（至少命中一个）
    has_bear_target = any(kw.lower() in combined_text for kw in BEAR_TARGET_KEYWORDS)
    if not has_bear_target:
        # 也接受通用策略关键词（可能是中性策略）
        generic_keywords = ['strategy', 'backtest', 'trading', '策略', '回测', '交易',
                           'rotation', 'switch', '轮动', '切换']
        has_generic = any(kw in combined_text for kw in generic_keywords)
        if not has_generic:
            return {'passed': False, 'reason': '无熊市相关关键词匹配',
                    'is_classic': False, 'strategy_category': ''}

    # 检查经典策略
    is_classic = any(cs in combined_text for cs in CLASSIC_BEAR_STRATEGIES)

    # 时效性检查
    if not is_classic and update_time:
        try:
            update_dt = datetime.strptime(update_time[:10], '%Y-%m-%d')
            months_old = (datetime.now() - update_dt).days / 30
            if months_old > 12:
                return {'passed': False,
                        'reason': f'策略已{months_old:.0f}个月未更新',
                        'is_classic': False, 'strategy_category': ''}
        except (ValueError, TypeError):
            pass

    # 可落地性
    if not code and 'pine script' not in source.lower() and 'tradingview' not in source.lower():
        return {'passed': False, 'reason': '无可执行代码',
                'is_classic': False, 'strategy_category': ''}

    # 目标指标参考检查（软性）
    warnings = []
    if claimed_return is not None and claimed_return < 8:
        warnings.append(f'声称年化{claimed_return}%<8%')
    if claimed_drawdown is not None and claimed_drawdown > 20:
        return {'passed': False,
                'reason': f'声称最大回撤{claimed_drawdown}%>20%（熊市硬性条件）',
                'is_classic': False, 'strategy_category': ''}

    # 自动分类
    strategy_category = _classify_bear_strategy(name, description, code)

    return {
        'passed': True,
        'reason': '通过初筛' + (' (经典策略)' if is_classic else ''),
        'is_classic': is_classic,
        'warnings': warnings,
        'strategy_category': strategy_category,
    }


def _classify_bear_strategy(name: str, description: str, code: str = '') -> str:
    """
    策略类型自动分类（熊市版）。
    分类标签: 做空趋势 / 均值回归（抄底） / 对冲/配对 / 高股息防御 /
              避险资产轮动 / 低波轮动 / 其他
    """
    text = f"{name} {description} {code}".lower()

    category_keywords = {
        '做空趋势': ['short', '做空', 'inverse', '空仓', 'trend reversal',
                     '趋势反转', '反手', 'bear trend'],
        '均值回归（抄底）': ['mean reversion', 'oversold', '超跌反弹', '均值回归',
                          'rsi oversold', 'bounce', '底部', '抄底'],
        '对冲/配对': ['hedge', 'pairs', 'pair trading', 'market neutral',
                    'long-short', 'long short', '对冲', '配对', '套利',
                    'spread', 'statistical arbitrage'],
        '高股息防御': ['dividend', 'yield', 'high yield', 'income',
                    '股息', '红利', '高股息', 'aristocrats', 'defensive'],
        '避险资产轮动': ['gold', 'treasury', 'bond', 'flight to quality',
                      'safe haven', 'risk-off', '黄金', '国债', '债券',
                      'gld', 'tlt', 'vix', 'vxx', '恐慌', '避险'],
        '低波轮动': ['low volatility', 'min variance', 'low vol',
                   '低波动', '最小方差', 'risk parity', '风险平价'],
    }

    scores = {}
    for cat, keywords in category_keywords.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[cat] = score

    if not scores:
        return '其他'

    return max(scores, key=scores.get)


# ================================================================
# 避险资产关键词→ETF映射
# ================================================================
SAFE_HAVEN_KEYWORD_MAP = {
    '黄金': ['GLD', 'IAU'],
    'gold': ['GLD', 'IAU'],
    'Gold': ['GLD', 'IAU'],
    '国债': ['TLT', 'IEF'],
    '债券': ['TLT', 'IEF'],
    'treasury': ['TLT', 'IEF'],
    'Treasury': ['TLT', 'IEF'],
    'bond': ['TLT', 'IEF'],
    'Bond': ['TLT', 'IEF'],
    'VIX': ['VXX', 'UVXY'],
    'vix': ['VXX', 'UVXY'],
    '恐慌指数': ['VXX', 'UVXY'],
    '红利': [],  # 需要从恒生高股息/标普红利贵族指数中获取
    '高股息': [],
    'dividend': [],
    'yield': [],
}


def detect_safe_haven_assets(strategy_info: dict) -> list:
    """
    解析策略描述，自动检测避险资产关键词，
    返回需要纳入回测标的池的ETF代码列表。
    """
    name = strategy_info.get('name', '').lower()
    description = strategy_info.get('description', '').lower()
    code = strategy_info.get('code', '').lower()
    combined = f"{name} {description} {code}"

    etf_pool = set()
    needs_dividend_index = False

    for keyword, etfs in SAFE_HAVEN_KEYWORD_MAP.items():
        if keyword.lower() in combined:
            for etf in etfs:
                etf_pool.add(etf)
            # 红利/高股息关键词需要添加对应指数成分股
            if keyword in ('红利', '高股息', 'dividend', 'yield'):
                needs_dividend_index = True

    return {
        'etf_list': sorted(etf_pool),
        'needs_dividend_index': needs_dividend_index,
    }


# ================================================================
# 搜索结果解析（复用通用逻辑）
# ================================================================
def parse_search_result(raw_result: dict) -> List[dict]:
    """解析搜索结果，提取策略信息。"""
    strategies = []
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
# 搜索执行
# ================================================================
def get_bear_search_queries() -> List[str]:
    """获取熊市策略搜索查询列表"""
    return BEAR_SEARCH_QUERIES.copy()


def process_bear_search_results(search_results: List[dict]) -> List[dict]:
    """处理搜索结果: 解析 → 初筛 → 返回通过的策略列表"""
    all_strategies = []
    for result in search_results:
        parsed = parse_search_result(result)
        all_strategies.extend(parsed)

    passed_strategies = []
    for strategy in all_strategies:
        filter_result = bear_initial_filter(strategy)
        if filter_result['passed']:
            strategy['filter_result'] = filter_result
            strategy['is_classic'] = filter_result.get('is_classic', False)
            strategy['strategy_category'] = filter_result.get('strategy_category', '其他')
            # 检测避险资产需求
            haven_info = detect_safe_haven_assets(strategy)
            strategy['safe_haven_etfs'] = haven_info['etf_list']
            strategy['needs_dividend_index'] = haven_info['needs_dividend_index']
            passed_strategies.append(strategy)

    return passed_strategies


# ================================================================
# 代码提取辅助（复用通用逻辑）
# ================================================================
def extract_code_from_github_readme(readme_content: str) -> Optional[str]:
    """从GitHub README中提取Python代码块"""
    pattern = r'```python\s*\n(.*?)```'
    matches = re.findall(pattern, readme_content, re.DOTALL)
    if matches:
        return max(matches, key=len)
    return None


def extract_pine_script(content: str) -> Optional[str]:
    """从网页内容中提取Pine Script代码"""
    pattern = r'```pine\s*\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL)
    if matches:
        return max(matches, key=len)
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
    test_bear_ok = {
        'name': 'Protective Put + Dividend Rotation Strategy',
        'description': 'A defensive bear market strategy using protective puts on high dividend stocks with gold/treasury rotation',
        'code': 'def generate_signals(close, high, low, open_prices): ...',
        'source': 'github',
        'update_time': '2025-03-15',
        'claimed_return': 12,
        'claimed_drawdown': 15,
    }

    test_bear_fail = {
        'name': 'Bull Market Momentum Strategy',
        'description': 'High growth bull market trend following strategy',
        'code': '...',
        'source': 'tradingview',
        'claimed_drawdown': 30,
    }

    print(f"✅ 熊市策略通过: {bear_initial_filter(test_bear_ok)}")
    print(f"❌ 牛市策略拒绝: {bear_initial_filter(test_bear_fail)}")

    # 测试避险资产检测
    test_gold = {
        'name': 'Gold Treasury Rotation',
        'description': 'Flight to quality strategy using gold and treasury bonds',
        'code': '',
    }
    print(f"🏦 避险资产检测: {detect_safe_haven_assets(test_gold)}")

    # 测试分类
    print(f"分类-做空: {_classify_bear_strategy('Short Trend Reversal', 'short selling bear trend')}")
    print(f"分类-避险: {_classify_bear_strategy('Gold Treasury Rotation', 'gold treasury bond flight to quality')}")
