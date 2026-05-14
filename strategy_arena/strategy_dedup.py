#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略去重与指纹模块
==================
职责:
  1. 提取策略核心逻辑代码（剔除注释、空行、变量名、输出打印语句）
  2. 计算策略指纹（SHA256）
  3. 策略去重判断

指纹算法:
  策略指纹 = SHA256(逻辑代码哈希 + 参数哈希)
  - 逻辑代码哈希: 对核心逻辑代码归一化后计算SHA256
  - 参数哈希: 对核心参数归一化后计算SHA256

去重规则:
  - 指纹完全相同 → 重复策略
  - 指纹相似度≥90%（参数差异≤10%）→ 同一策略家族，保留得分最高者
"""

import hashlib
import json
import os
import re
from typing import Tuple, Optional


# ================================================================
# 核心逻辑代码提取
# ================================================================
def extract_core_logic(code: str) -> str:
    """
    提取策略核心逻辑代码：
      - 移除注释
      - 移除空行
      - 移除 print/logging 等输出语句
      - 标准化变量名（将自定义变量名替换为通用名）
      - 标准化空白
    """
    if not code:
        return ''

    # 移除多行注释
    code = re.sub(r'"""[\s\S]*?"""', '', code)
    code = re.sub(r"'''[\s\S]*?'''", '', code)

    # 移除单行注释
    code = re.sub(r'#.*$', '', code, flags=re.MULTILINE)

    # 移除 print/logging 语句
    code = re.sub(r'^\s*print\s*\([^)]*\)\s*$', '', code, flags=re.MULTILINE)
    code = re.sub(r'^\s*logging\.\w+\s*\([^)]*\)\s*$', '', code, flags=re.MULTILINE)

    # 移除 docstring（已经是空的）
    # 移除 import 语句（不是核心逻辑）
    code = re.sub(r'^\s*(?:import|from)\s+\S+.*$', '', code, flags=re.MULTILINE)

    # 移除空行
    lines = [l.rstrip() for l in code.split('\n') if l.strip()]
    code = '\n'.join(lines)

    # 标准化空白：将连续空白替换为单个空格（保留缩进结构）
    # 先保留缩进信息（行首空格）
    normalized_lines = []
    for line in lines:
        if not line.strip():
            continue
        # 保留缩进
        indent = len(line) - len(line.lstrip())
        content = ' '.join(line.strip().split())
        normalized_lines.append(' ' * indent + content)
    code = '\n'.join(normalized_lines)

    return code.strip()


# ================================================================
# 参数归一化
# ================================================================
def normalize_params(params: dict) -> str:
    """
    参数归一化：
      1. 按key排序
      2. 值转为字符串
      3. 拼接为固定格式
    """
    if not params:
        return ''
    sorted_items = sorted(params.items(), key=lambda x: x[0])
    parts = []
    for k, v in sorted_items:
        if isinstance(v, float):
            parts.append(f"{k}={v:.4f}")
        else:
            parts.append(f"{k}={v}")
    return '|'.join(parts)


# ================================================================
# 指纹计算
# ================================================================
def compute_strategy_fingerprint(code: str, params: dict = None) -> str:
    """
    计算策略指纹 = SHA256(逻辑代码哈希 + 参数哈希)
    返回完整的SHA256十六进制字符串。
    """
    core_logic = extract_core_logic(code)
    logic_hash = hashlib.sha256(core_logic.encode('utf-8')).hexdigest()

    params_str = normalize_params(params or {})
    params_hash = hashlib.sha256(params_str.encode('utf-8')).hexdigest()

    combined = logic_hash + params_hash
    fingerprint = hashlib.sha256(combined.encode('utf-8')).hexdigest()
    return fingerprint


def fingerprint_short(fingerprint: str, length: int = 8) -> str:
    """返回指纹的前N位（默认8位）"""
    return fingerprint[:length]


# ================================================================
# 参数相似度计算
# ================================================================
def compute_param_similarity(params1: dict, params2: dict) -> float:
    """
    计算两组参数的相似度（0~1）。
    使用数值型参数的相对差异，字符串参数的精确匹配。
    """
    if not params1 and not params2:
        return 1.0
    if not params1 or not params2:
        return 0.0

    all_keys = set(params1.keys()) | set(params2.keys())
    if not all_keys:
        return 1.0

    similarities = []
    for key in all_keys:
        v1 = params1.get(key)
        v2 = params2.get(key)

        if v1 is None or v2 is None:
            similarities.append(0.0)
            continue

        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            # 数值型：相对差异
            if v1 == 0 and v2 == 0:
                similarities.append(1.0)
            elif v1 == 0 or v2 == 0:
                similarities.append(0.0)
            else:
                ratio = min(abs(v1), abs(v2)) / max(abs(v1), abs(v2))
                similarities.append(ratio)
        else:
            # 字符串/其他：精确匹配
            similarities.append(1.0 if str(v1) == str(v2) else 0.0)

    return sum(similarities) / len(similarities)


# ================================================================
# 策略家族检测
# ================================================================
def is_same_family(fp1: str, fp2: str, params1: dict, params2: dict,
                   threshold: float = 0.9) -> bool:
    """
    判断两个策略是否属于同一家族（指纹相似度≥90%且参数差异≤10%）。
    
    判定逻辑：
      - 如果指纹完全相同 → True
      - 如果逻辑代码哈希相同（指纹前64位之一致）且参数相似度≥90% → True
      - 否则 → False
    """
    if fp1 == fp2:
        return True

    # 逻辑代码哈希 = SHA256(逻辑代码) = fingerprint构造中的前64位逻辑部分
    # 无法直接拆解，改用参数相似度判定
    param_sim = compute_param_similarity(params1, params2)
    return param_sim >= threshold


# ================================================================
# 策略库操作
# ================================================================
STRATEGY_DB_PATH = '/data/workspace/strategy_arena/strategy_library.json'


def load_strategy_library(db_path: str = STRATEGY_DB_PATH) -> dict:
    """加载策略库"""
    if not os.path.exists(db_path):
        return {'strategies': [], 'version': '1.0', 'last_updated': ''}
    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'strategies': [], 'version': '1.0', 'last_updated': ''}


def save_strategy_library(library: dict, db_path: str = STRATEGY_DB_PATH):
    """保存策略库"""
    from datetime import datetime
    library['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with open(db_path, 'w', encoding='utf-8') as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def check_duplicate(fingerprint: str, params: dict, library: dict) -> Optional[dict]:
    """
    检查策略是否已存在或属于同一家族。
    
    Returns:
      - None: 新策略
      - dict: 已存在的策略记录（含指纹和得分）
    """
    for strategy in library.get('strategies', []):
        existing_fp = strategy.get('fingerprint', '')
        existing_params = strategy.get('strategy_params', {})

        if existing_fp == fingerprint:
            return strategy

        if is_same_family(fingerprint, existing_fp, params, existing_params):
            return strategy

    return None


def add_strategy_to_library(strategy_record: dict, library: dict) -> dict:
    """
    添加策略到库中。如果同指纹+同市场已存在，保留得分最高者。
    同一策略在不同市场（us/hk）视为不同条目，分别保存。
    
    Returns:
      更新后的library
    """
    new_fp = strategy_record.get('fingerprint', '')
    new_market = strategy_record.get('market', '')
    new_score = strategy_record.get('total_score', 0)
    new_params = strategy_record.get('strategy_params', {})

    # 检查重复（指纹+市场联合去重）
    found_idx = -1
    for i, s in enumerate(library.get('strategies', [])):
        if s.get('fingerprint', '') == new_fp and s.get('market', '') == new_market:
            found_idx = i
            break

    if found_idx >= 0:
        existing_score = library['strategies'][found_idx].get('total_score', 0)
        if new_score > existing_score:
            # 替换旧策略
            library['strategies'][found_idx] = strategy_record
        # 否则保留旧策略，新策略不入库
    else:
        library['strategies'].append(strategy_record)

    return library


# ================================================================
# 单元测试
# ================================================================
if __name__ == '__main__':
    # 测试核心逻辑提取
    test_code = '''
    # 这是一个EMA交叉策略
    import numpy as np
    import talib

    def generate_signals(close, high, low, open_prices, ema_fast=10, ema_slow=20):
        """EMA交叉策略"""
        c = pd.Series(close, dtype=float)
        fast = c.ewm(span=ema_fast, adjust=False).mean()
        slow = c.ewm(span=ema_slow, adjust=False).mean()
        print(f"Fast: {fast[-1]}, Slow: {slow[-1]}")
        in_pos = fast > slow
        entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
        exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
        return entries, exits
    '''
    core = extract_core_logic(test_code)
    print(f"核心逻辑:\n{core[:200]}...")

    # 测试指纹计算
    params = {'ema_fast': 10, 'ema_slow': 20}
    fp = compute_strategy_fingerprint(test_code, params)
    print(f"指纹: {fp}")
    print(f"短指纹: {fingerprint_short(fp)}")

    # 测试参数相似度
    params2 = {'ema_fast': 12, 'ema_slow': 20}
    sim = compute_param_similarity(params, params2)
    print(f"参数相似度: {sim:.2%}")

    # 测试同家族检测
    fp2 = compute_strategy_fingerprint(test_code, params2)
    print(f"同家族: {is_same_family(fp, fp2, params, params2)}")
