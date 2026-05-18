#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震荡市策略搜索模块
==================
职责: 从公开来源搜索适配震荡行情的量化策略代码，进行描述性初筛。

与趋势市搜索模块的核心差异:
  - 搜索关键词: 震荡市/均值回归/区间交易/网格/波动率套利
  - 初筛指标: 年化≥10%(理想≥15%), 回撤≤15%(硬性), 胜率≥55%, 盈亏比≥1.8
  - 止损检查: 无止损逻辑标记风险
  - Pine Script一票否决制: 与趋势版相同

搜索来源（按优先级）:
  1. QuantConnect 社区策略库
  2. TradingView Pine Script 公开策略（标注"Repainting: No"）
  3. GitHub vn.py / awesome-quant / Quantopian 遗留
  4. QuantInsti 博客及课程案例
  5. 聚宽 (JoinQuant) 社区
  6. BigQuant 社区
  7. 雪球量化投资话题
"""

import json
import os
import re
from datetime import datetime
from typing import List, Optional


# ================================================================
# 震荡市搜索关键词
# ================================================================
TARGET_KEYWORDS = [
    # 震荡市定位
    '震荡市', '区间交易', '均值回归', '高抛低吸', '波动率套利',
    '网格交易', '对冲型', '市场中性', '低波动',
    '港美股', '美股', '港股',
    # 英文
    'mean reversion', 'range trading', 'range-bound', 'sideways market',
    'grid trading', 'volatility arbitrage', 'market neutral',
    'pair trading', 'statistical arbitrage', 'contrarian',
    'oscillation', 'consolidation', 'channel trading',
    'Bollinger bands reversion', 'RSI range', 'Keltner squeeze',
    # 通用
    'backtest', 'strategy', 'quantitative', 'trading',
]

# 排除关键词
EXCLUDE_KEYWORDS = [
    'crypto', 'bitcoin', 'forex', '期货', '加密', '比特币', '外汇',
    'scalping', '刷单', '日内剥头皮',
    'options', '期权', '期权策略',
    '趋势跟踪', 'trend following', 'breakout', '趋势突破',
    # 排除纯趋势策略（震荡市不需要）
]

# 经典震荡市策略（不受12个月时效限制）
CLASSIC_STRATEGIES = [
    'bollinger bands mean reversion', 'rsi mean reversion', 'grid trading',
    'pairs trading', 'statistical arbitrage', 'keltner squeeze',
    'donchian channel range', 'macd histogram divergence',
    '布林带回归', 'RSI均值回归', '网格交易', '配对交易',
    '统计套利', 'Keltner挤压', '区间交易',
]


# ================================================================
# 搜索查询模板（震荡市专用）
# ================================================================
SEARCH_QUERIES = [
    # GitHub 搜索
    'site:github.com mean reversion strategy python stocks backtest 2024 2025',
    'site:github.com bollinger bands range trading python backtest',
    'site:github.com pairs trading statistical arbitrage python stocks',
    'site:github.com grid trading strategy python stocks backtest',
    'site:github.com market neutral strategy python quantitative',

    # QuantConnect
    'site:quantconnect.com mean reversion algorithm stocks range bound',

    # TradingView
    'site:tradingview.com pine script stocks strategy "Repainting: No" mean reversion range',

    # 通用搜索
    'python stocks backtest mean reversion strategy 2024 site:medium.com OR site:towardsdatascience.com',
    'quantitative range trading strategy python mean reversion 2024',
    '港美股震荡市策略 python 回测 2024 均值回归',
    '美股区间交易策略 python 回测代码 网格',
    'bollinger bands squeeze strategy python backtest stocks 2024',
    'RSI overbought oversold mean reversion python backtest stocks',
]


# ================================================================
# 止损逻辑检测
# ================================================================
STOP_LOSS_PATTERNS = [
    # 固定比例止损
    r'stop[_\s]?loss',
    r'止损',
    # ATR止损
    r'atr[_\s]?stop',
    r'atr[_\s]?multiplier',
    r'吊灯止损',
    r'trailing[_\s]?stop',
    # 时间止损
    r'time[_\s]?stop',
    r'bars[_\s]?since[_\s]?entry',
    # 最大亏损止损
    r'max[_\s]?loss',
    r'risk[_\s]?per[_\s]?trade',
    r'position[_\s]?size',
    # VectorBT止损
    r'stop_loss',
    r'trailing_stop',
    r'sl_price',
    r'tp_price',
]


def detect_stop_loss(code: str) -> dict:
    """
    检测策略代码中是否包含止损逻辑。
    
    Returns:
        {'has_stop_loss': bool, 'detected_patterns': list, 'warning': str}
    """
    if not code:
        return {'has_stop_loss': False, 'detected_patterns': [], 'warning': '⚠️ 无止损保护'}

    code_lower = code.lower()
    detected = []

    for pattern in STOP_LOSS_PATTERNS:
        if re.search(pattern, code_lower):
            detected.append(pattern)

    has_stop = len(detected) > 0
    warning = '' if has_stop else '⚠️ 无止损保护'

    return {
        'has_stop_loss': has_stop,
        'detected_patterns': detected,
        'warning': warning,
    }


# ================================================================
# 震荡市初筛
# ================================================================
def initial_filter_range(strategy_info: dict) -> dict:
    """
    震荡市策略描述性初筛。

    初筛标准:
      1. 策略定位: 包含震荡市目标关键词
      2. 目标指标（初筛参考，以回测结果为准）:
         - 年化收益率 ≥ 10%（理想≥15%）
         - 盈亏比 ≥ 1.8:1
         - 胜率 ≥ 55%
         - 单标年平均交易次数 ≥ 100次
         - 最大回撤 ≤ 15%（硬性条件）
      3. 止损检查: 必须有止损逻辑，否则扣10分
      4. 可落地性: 有代码或可转译的逻辑
      5. 时效性: 更新时间≤12个月或为经典策略

    Returns:
      {'passed': bool, 'reason': str, 'is_classic': bool, 'warnings': list,
       'stop_loss_info': dict, 'portability_score': int}
    """
    name = strategy_info.get('name', '').lower()
    description = strategy_info.get('description', '').lower()
    code = strategy_info.get('code', '')
    update_time = strategy_info.get('update_time', '')
    source = strategy_info.get('source', '')
    claimed_return = strategy_info.get('claimed_return', None)
    claimed_drawdown = strategy_info.get('claimed_drawdown', None)
    claimed_win_rate = strategy_info.get('claimed_win_rate', None)
    claimed_profit_ratio = strategy_info.get('claimed_profit_ratio', None)

    combined_text = f"{name} {description}"
    warnings = []

    # 检查排除关键词
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in combined_text:
            return {
                'passed': False, 'reason': f'排除关键词: {kw}',
                'is_classic': False, 'warnings': [],
                'stop_loss_info': {'has_stop_loss': False, 'warning': ''},
                'portability_score': 0,
            }

    # 检查目标关键词（至少命中一个）
    has_target = any(kw.lower() in combined_text for kw in TARGET_KEYWORDS)
    if not has_target:
        # 例外：若策略明确声明在低波动或横盘期表现优异
        exception_keywords = ['low volatility', 'sideways', '横盘', '低波动', 'consolidation']
        has_exception = any(kw.lower() in combined_text for kw in exception_keywords)
        if not has_exception:
            # 也接受通用策略关键词（但需标记为弱匹配）
            generic_keywords = ['strategy', 'backtest', 'trading', '策略', '回测', '交易']
            has_generic = any(kw in combined_text for kw in generic_keywords)
            if not has_generic:
                return {
                    'passed': False, 'reason': '无目标关键词匹配',
                    'is_classic': False, 'warnings': [],
                    'stop_loss_info': {'has_stop_loss': False, 'warning': ''},
                    'portability_score': 0,
                }
            warnings.append('弱关键词匹配，需回测验证')

    # 检查经典策略
    is_classic = any(cs in combined_text for cs in CLASSIC_STRATEGIES)

    # 时效性检查（非经典策略需12个月内更新）
    if not is_classic and update_time:
        try:
            update_dt = datetime.strptime(update_time[:10], '%Y-%m-%d')
            months_old = (datetime.now() - update_dt).days / 30
            if months_old > 12:
                return {
                    'passed': False, 'reason': f'策略已{months_old:.0f}个月未更新',
                    'is_classic': False, 'warnings': [],
                    'stop_loss_info': {'has_stop_loss': False, 'warning': ''},
                    'portability_score': 0,
                }
        except (ValueError, TypeError):
            pass

    # 可落地性: 必须有代码或可转译的Pine Script
    if not code and 'pine script' not in source.lower() and 'tradingview' not in source.lower():
        return {
            'passed': False, 'reason': '无可执行代码',
            'is_classic': False, 'warnings': [],
            'stop_loss_info': {'has_stop_loss': False, 'warning': ''},
            'portability_score': 0,
        }

    # 目标指标参考检查（软性，仅作标记）
    if claimed_return is not None and claimed_return < 10:
        warnings.append(f'声称年化{claimed_return}%<10%')
    if claimed_drawdown is not None and claimed_drawdown > 15:
        return {
            'passed': False, 'reason': f'声称最大回撤{claimed_drawdown}%>15%（硬性条件）',
            'is_classic': False, 'warnings': warnings,
            'stop_loss_info': {'has_stop_loss': False, 'warning': ''},
            'portability_score': 0,
        }
    if claimed_win_rate is not None and claimed_win_rate < 55:
        warnings.append(f'声称胜率{claimed_win_rate}%<55%')
    if claimed_profit_ratio is not None and claimed_profit_ratio < 1.8:
        warnings.append(f'声称盈亏比{claimed_profit_ratio}<1.8')

    # 止损逻辑检测
    stop_loss_info = detect_stop_loss(code)
    if not stop_loss_info['has_stop_loss']:
        warnings.append('⚠️ 无止损保护')

    # 可移植性评分
    portability_score = _score_portability(code, source)

    return {
        'passed': True,
        'reason': '通过初筛' + (' (经典策略)' if is_classic else ''),
        'is_classic': is_classic,
        'warnings': warnings,
        'stop_loss_info': stop_loss_info,
        'portability_score': portability_score,
    }


def _score_portability(code: str, source: str = 'unknown') -> int:
    """
    可移植性评分（满分10分）:
      - 10分：纯Python，无平台专有API依赖
      - 7分：依赖通用API且代码中数据获取逻辑清晰可替换
      - 4分：依赖封闭平台专有函数，需大幅改写
      - 0分：无代码或仅为截图 / Pine Script触发一票否决
    """
    if not code or len(code.strip()) < 20:
        return 0

    # 复用Pine Script验证
    if source.lower() in ('tradingview', 'pine_script', 'pine'):
        sys_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                'strategy_arena', 'pine_validator.py')
        try:
            from pine_validator import check_pine_veto
            veto = check_pine_veto(code)
            if veto['vetoed']:
                return 0
        except ImportError:
            pass

    python_indicators = ['import ', 'def ', 'class ', 'pd.', 'np.', 'talib.', 'vbt.']
    is_python = any(ind in code for ind in python_indicators)

    if is_python:
        platform_apis = [
            'joinquant', 'jqdatasdk', 'rqdatac', 'rqalpha',
            'vnpy', 'vn.', 'zipline', 'quantconnect', 'backtrader',
        ]
        platform_count = sum(1 for api in platform_apis if api in code.lower())
        if platform_count == 0:
            return 10
        elif platform_count == 1:
            return 7
        else:
            return 4
    else:
        return 4


# ================================================================
# 搜索结果解析
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
            'claimed_win_rate': item.get('claimed_win_rate'),
            'claimed_profit_ratio': item.get('claimed_profit_ratio'),
        }
        strategies.append(strategy)

    return strategies


# ================================================================
# 搜索执行接口
# ================================================================
def get_search_queries() -> List[str]:
    """获取震荡市搜索查询列表"""
    return SEARCH_QUERIES.copy()


def process_search_results(search_results: List[dict]) -> List[dict]:
    """处理搜索结果: 解析 → 震荡市初筛 → 返回通过的策略列表"""
    all_strategies = []
    for result in search_results:
        parsed = parse_search_result(result)
        all_strategies.extend(parsed)

    passed_strategies = []
    for strategy in all_strategies:
        filter_result = initial_filter_range(strategy)
        if filter_result['passed']:
            strategy['filter_result'] = filter_result
            strategy['is_classic'] = filter_result.get('is_classic', False)
            strategy['stop_loss_info'] = filter_result.get('stop_loss_info', {})
            strategy['portability_score'] = filter_result.get('portability_score', 0)
            passed_strategies.append(strategy)

    return passed_strategies


# ================================================================
# 策略代码提取辅助
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
    # 测试震荡市初筛 - 通过
    test_ok = {
        'name': 'Bollinger Bands Mean Reversion Strategy',
        'description': 'A mean reversion strategy for range-bound US stocks using Bollinger Bands with ATR stop loss',
        'code': 'def generate_signals(close, high, low, open_prices):\n    stop_loss = entry - 2*atr\n    ...',
        'source': 'github',
        'update_time': '2025-03-15',
        'claimed_return': 14,
        'claimed_drawdown': 12,
        'claimed_win_rate': 58,
        'claimed_profit_ratio': 2.0,
    }

    # 测试震荡市初筛 - 未通过（回撤过大）
    test_fail = {
        'name': 'Trend Following Breakout Strategy',
        'description': 'A breakout trend following strategy for US stocks',
        'code': '...',
        'source': 'tradingview',
        'claimed_drawdown': 40,
    }

    # 测试止损检测
    test_no_stop = {
        'name': 'RSI Range Trading Strategy',
        'description': 'RSI mean reversion range trading for HK stocks',
        'code': 'def generate_signals(close, high, low, open_prices):\n    rsi = talib.RSI(close)\n    entries = rsi < 30\n    exits = rsi > 70\n    return entries, exits',
        'source': 'github',
        'update_time': '2025-01-10',
    }

    print(f"✅ 震荡市通过初筛: {initial_filter_range(test_ok)}")
    print(f"❌ 趋势策略未通过: {initial_filter_range(test_fail)}")
    print(f"⚠️ 无止损策略: {initial_filter_range(test_no_stop)}")
