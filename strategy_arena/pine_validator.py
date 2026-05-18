#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pine Script 验证与转译模块
===========================
职责:
  1. Pine Script 一票否决制检测
  2. Pine Script 核心逻辑提取（用于指纹计算）
  3. Pine Script → Python 转译辅助（标记需人工审核的部分）

一票否决规则:
  - 调用 request.security() / security() 进行跨周期数据获取
  - 使用 barmerge.lookahead_on 参数
  - 使用 ta.valuewhen 等已知引用未来数据的函数
"""

import re
from typing import Tuple, List, Optional


# ================================================================
# 一票否决制检测
# ================================================================
VETO_PATTERNS = [
    # 跨周期数据获取
    (r'request\.security\s*\(', 'request.security() 跨周期数据获取，引入未来信息'),
    (r'\bsecurity\s*\(', 'security() 跨周期数据获取，引入未来信息'),
    # 前瞻合并
    (r'barmerge\.lookahead_on', 'barmerge.lookahead_on 参数，启用前瞻合并'),
    # 未来数据函数
    (r'ta\.valuewhen\s*\(', 'ta.valuewhen() 可能引用未来数据'),
    # 额外可疑模式
    (r'\[-\d+\]', '负索引数组访问，可能引用未来K线', 'warning'),
    (r'request\.financial\s*\(', 'request.financial() 财务数据可能存在未来信息偏差', 'warning'),
]

# 必须一票否决的关键词（不包含warning级别）
VETO_REQUIRED_PATTERNS = [(p, d) for p, d, *rest in VETO_PATTERNS if not rest or rest[0] != 'warning']
VETO_WARNING_PATTERNS = [(p, d) for p, d, *rest in VETO_PATTERNS if rest and rest[0] == 'warning']


def check_pine_veto(pine_code: str) -> dict:
    """
    检查Pine Script代码是否触发一票否决制。
    
    Returns:
        {
            'vetoed': bool,           # 是否被否决
            'veto_reasons': list,     # 否决原因
            'warnings': list,         # 警告（不否决但需注意）
            'pine_script_rejected': bool  # 同vetoed，与存储字段对齐
        }
    """
    veto_reasons = []
    warnings = []

    # 移除注释（单行 // 和多行 /* */）
    code_no_comments = re.sub(r'//.*$', '', pine_code, flags=re.MULTILINE)
    code_no_comments = re.sub(r'/\*.*?\*/', '', code_no_comments, flags=re.DOTALL)

    # 检查一票否决模式
    for pattern, description in VETO_REQUIRED_PATTERNS:
        if re.search(pattern, code_no_comments):
            veto_reasons.append(description)

    # 检查警告模式
    for pattern, description in VETO_WARNING_PATTERNS:
        if re.search(pattern, code_no_comments):
            warnings.append(description)

    vetoed = len(veto_reasons) > 0

    return {
        'vetoed': vetoed,
        'veto_reasons': veto_reasons,
        'warnings': warnings,
        'pine_script_rejected': vetoed,
    }


# ================================================================
# Pine Script 核心逻辑提取（用于指纹计算）
# ================================================================
def extract_pine_core_logic(pine_code: str) -> str:
    """
    提取Pine Script核心逻辑代码：
      - 移除注释
      - 移除空行
      - 移除变量声明关键字（var, varip）
      - 保留核心策略逻辑
    """
    # 移除注释
    code = re.sub(r'//.*$', '', pine_code, flags=re.MULTILINE)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)

    # 移除空行
    lines = [l.strip() for l in code.split('\n') if l.strip()]
    code = '\n'.join(lines)

    # 移除版本声明
    code = re.sub(r'//@version=\d+', '', code)
    code = re.sub(r'indicator\s*\([^)]*\)', '', code)
    code = re.sub(r'strategy\s*\([^)]*\)', '', code)

    # 标准化空格
    code = re.sub(r'\s+', ' ', code)

    return code.strip()


# ================================================================
# Pine Script 参数提取
# ================================================================
def extract_pine_params(pine_code: str) -> dict:
    """
    提取Pine Script中的策略参数（input系列函数调用）
    """
    params = {}
    # 匹配 input.int, input.float, input.source, input.bool, input.string
    input_pattern = re.compile(
        r'(\w+)\s*=\s*input\.(?:int|float|source|bool|string)\s*\('
        r'(?:[^,]*,\s*(?:defval\s*=\s*)?([^,)]+)|([^,)]+))',
        re.MULTILINE
    )
    for match in input_pattern.finditer(pine_code):
        var_name = match.group(1)
        # 尝试提取默认值
        defval = match.group(2) or match.group(3)
        if defval:
            defval = defval.strip().rstrip(')')
            try:
                params[var_name] = float(defval) if '.' in defval else int(defval)
            except ValueError:
                params[var_name] = defval.strip('"').strip("'")

    # 简单模式: x = input(10, ...)
    simple_pattern = re.compile(
        r'(\w+)\s*=\s*input\s*\(\s*(\d+\.?\d*)',
        re.MULTILINE
    )
    for match in simple_pattern.finditer(pine_code):
        var_name = match.group(1)
        defval = match.group(2)
        try:
            params[var_name] = float(defval) if '.' in defval else int(defval)
        except ValueError:
            pass

    return params


# ================================================================
# Pine Script → Python 转译标记
# ================================================================
# 需要人工审核的函数映射
PINE_TO_PYTHON_MANUAL = {
    'request.security': '⚠️ 需手动处理: 跨周期数据需用resample/rebase实现',
    'security': '⚠️ 需手动处理: 跨周期数据需用resample/rebase实现',
    'ta.valuewhen': '⚠️ 需手动处理: 需用循环+状态机实现',
    'str.tostring': 'Python: str()',
    'math.abs': 'Python: abs()',
    'math.round': 'Python: round()',
    'math.max': 'Python: max()',
    'math.min': 'Python: min()',
    'ta.sma': 'Python: talib.SMA()',
    'ta.ema': 'Python: talib.EMA()',
    'ta.rsi': 'Python: talib.RSI()',
    'ta.macd': 'Python: talib.MACD()',
    'ta.atr': 'Python: talib.ATR()',
    'ta.adx': 'Python: talib.ADX()',
    'ta.stoch': 'Python: talib.STOCH()',
    'ta.bb': 'Python: talib.BBANDS()',
    'ta.rma': 'Python: talib.EMA() (近似)',
    'ta.wma': 'Python: talib.WMA()',
    'ta.crossover': 'Python: (a > b) & (a.shift(1) <= b.shift(1))',
    'ta.crossunder': 'Python: (a < b) & (a.shift(1) >= b.shift(1))',
    'ta.barssince': '⚠️ 需手动实现: 距离上次条件成立的K线数',
    'ta.highest': 'Python: high.rolling(n).max()',
    'ta.lowest': 'Python: low.rolling(n).min()',
    'ta.change': 'Python: series.diff()',
    'strategy.entry': 'Python: entries[i] = True',
    'strategy.close': 'Python: exits[i] = True',
    'strategy.exit': 'Python: 止损/止盈逻辑需手动实现',
    'barstate.isfirst': 'Python: i == 0',
    'barstate.islast': 'Python: i == len(data) - 1',
    'barstate.ishistory': 'Python: True (回测中全部为历史)',
    'nz()': 'Python: fillna(0)',
}


def analyze_pine_for_translation(pine_code: str) -> dict:
    """
    分析Pine Script代码，标记需要人工转译的部分。
    返回每个函数的转译建议。
    """
    code_no_comments = re.sub(r'//.*$', '', pine_code, flags=re.MULTILINE)
    code_no_comments = re.sub(r'/\*.*?\*/', code_no_comments, flags=re.DOTALL)

    translation_notes = {}
    for pine_func, note in PINE_TO_PYTHON_MANUAL.items():
        # 简单搜索函数名出现
        func_name = pine_func.split('(')[0].split('.')[-1] if '.' in pine_func else pine_func.split('(')[0]
        if func_name in code_no_comments:
            translation_notes[pine_func] = note

    # 检测plot/bgcolor等纯显示函数（可忽略）
    display_funcs = re.findall(r'(?:plot|bgcolor|fill|hline|label\.\w+)\s*\(', code_no_comments)
    if display_funcs:
        translation_notes['_display_only'] = f'发现{len(display_funcs)}个纯显示函数，转译时可忽略'

    return translation_notes


# ================================================================
# 可移植性评分
# ================================================================
def score_portability(code: str, source: str = 'unknown') -> int:
    """
    计算策略可移植性评分（满分10分）:
      - 10分：纯Python，无平台专有API依赖
      - 7分：依赖通用API且代码中数据获取逻辑清晰可替换
      - 4分：依赖封闭平台专有函数，需大幅改写
      - 0分：无代码或仅为截图
    """
    if not code or len(code.strip()) < 20:
        return 0

    # Pine Script一票否决检查
    if source.lower() in ('tradingview', 'pine_script', 'pine'):
        veto = check_pine_veto(code)
        if veto['vetoed']:
            return 0  # 一票否决 → 0分

    # 检测Python代码
    python_indicators = ['import ', 'def ', 'class ', 'pd.', 'np.', 'talib.', 'vbt.']
    is_python = any(ind in code for ind in python_indicators)

    if is_python:
        # 检测平台专有API
        platform_apis = [
            'joinquant', 'jqdatasdk',  # 聚宽
            'rqdatac', 'rqalpha',       # 米筐
            'vnpy', 'vn.',              # vn.py
            'zipline',                   # Quantopian遗留
            'quantconnect',              # QuantConnect
            'backtrader',                # Backtrader (可替换)
        ]
        platform_count = sum(1 for api in platform_apis if api in code.lower())

        if platform_count == 0:
            return 10  # 纯Python
        elif platform_count == 1:
            return 7   # 单一平台依赖
        else:
            return 4   # 多平台依赖
    else:
        # Pine Script或其他
        if source.lower() in ('tradingview', 'pine_script', 'pine'):
            veto = check_pine_veto(code)
            if not veto['vetoed'] and not veto['warnings']:
                return 7   # 干净的Pine Script，可转译
            elif not veto['vetoed']:
                return 4   # 有警告但未否决
        return 4  # 其他语言，需改写


# ================================================================
# 单元测试
# ================================================================
if __name__ == '__main__':
    # 测试一票否决
    test_veto_code = """
    //@version=5
    indicator("Test")
    daily_close = request.security(syminfo.tickerid, "D", close, barmerge.lookahead_on)
    valuewhen_cond = ta.valuewhen(close > open, high, 0)
    plot(daily_close)
    """
    result = check_pine_veto(test_veto_code)
    print(f"一票否决测试: vetoed={result['vetoed']}, reasons={result['veto_reasons']}")

    # 测试参数提取
    test_params_code = """
    fast_len = input.int(10, "Fast Length")
    slow_len = input.int(20, "Slow Length")
    mult = input.float(2.0, "Multiplier")
    """
    params = extract_pine_params(test_params_code)
    print(f"参数提取: {params}")

    # 测试可移植性评分
    print(f"Pine否决代码评分: {score_portability(test_veto_code, 'tradingview')}")
    clean_pine = """
    //@version=5
    strategy("EMA Cross")
    fast = ta.ema(close, 10)
    slow = ta.ema(close, 20)
    if ta.crossover(fast, slow)
        strategy.entry("Long", strategy.long)
    if ta.crossunder(fast, slow)
        strategy.close("Long")
    """
    print(f"干净Pine评分: {score_portability(clean_pine, 'tradingview')}")
    print(f"转译标记: {analyze_pine_for_translation(clean_pine)}")
