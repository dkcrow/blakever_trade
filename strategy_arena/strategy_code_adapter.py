#!/usr/bin/env python3
"""
策略代码适配器：将搜索到的策略代码转换为可回测的策略变体

核心思路：
1. 搜索到的代码作为「代码参考」保存
2. 从代码中提取策略参数和逻辑模式
3. 将其映射到已有的内置策略函数（安全、可控）
4. 生成新的参数变体组合

不需要动态执行外部代码（安全风险），而是从外部代码中「提取灵感」
"""

import re
import hashlib
import json
import os
from typing import List, Dict, Tuple, Optional, Any


# ================================================================
# 策略模式识别：从代码中识别策略类型和参数
# ================================================================

# 策略模式定义：每种模式对应一种内置策略函数
STRATEGY_PATTERNS = {
    'gem_rotation': {
        'keywords': ['gem', 'global equity momentum', 'rotation', 'momentum_rotation',
                    'dual_momentum', 'relative_momentum', 'absolute_momentum',
                    'lookback', 'buffer', 'rebalance'],
        'strategy_func': 'strategy_gem_rotation',
        'param_extractors': {
            'lookback_months': [r'lookback[_\s]*(?:months?|period|window)\s*[=:]\s*(\d+)',
                              r'(\d+)\s*month', r'momentum.*?(\d+)\s*m',
                              r'lookback\s*=\s*(\d+)'],
            'buffer_days': [r'buffer[_\s]*(?:days?)\s*[=:]\s*(\d+)',
                          r'delay\s*[=:]\s*(\d+)'],
            'abs_momentum_threshold': [r'threshold\s*[=:]\s*([\d.]+)',
                                      r'abs.*?momentum.*?([\d.]+)'],
        },
    },
    'dual_momentum': {
        'keywords': ['dual_momentum', 'dual momentum', 'relative.*absolute.*momentum',
                    'two.*momentum', '双动量'],
        'strategy_func': 'strategy_dual_momentum',
        'param_extractors': {
            'lookback_months': [r'lookback[_\s]*(?:months?|period)\s*[=:]\s*(\d+)',
                              r'(\d+)\s*month.*momentum'],
            'buffer_days': [r'buffer[_\s]*(?:days?)\s*[=:]\s*(\d+)'],
            'abs_momentum_threshold': [r'abs.*?threshold\s*[=:]\s*([\d.]+)',
                                      r'absolute.*?momentum.*?([\d.]+)'],
        },
    },
    'multi_asset_rotation': {
        'keywords': ['multi.*asset.*rotation', 'sector.*rotation', 'free.*rotation',
                    'n.*asset.*rotation', 'top.*n', 'rank.*rotation',
                    'rotation.*etf', 'etf.*rotation', '轮动'],
        'strategy_func': 'strategy_multi_asset_rotation',
        'param_extractors': {
            'lookback_months': [r'lookback[_\s]*(?:months?|period)\s*[=:]\s*(\d+)',
                              r'(\d+)\s*month'],
            'buffer_days': [r'buffer[_\s]*(?:days?)\s*[=:]\s*(\d+)'],
            'top_n': [r'top[_\s]*n\s*[=:]\s*(\d+)', r'select.*?top\s*(\d+)'],
        },
    },
    'bollinger_reversion': {
        'keywords': ['bollinger', 'mean.?reversion', 'boll.*band', 'reversion',
                    'zscore', 'z_score', 'oversold', '布林', '均值回归'],
        'strategy_func': 'strategy_bollinger_reversion',
        'param_extractors': {
            'bb_period': [r'bb?[_\s]*(?:period|window)\s*[=:]\s*(\d+)',
                        r'bollinger.*?period\s*[=:]\s*(\d+)',
                        r'window\s*[=:]\s*(\d+).*boll'],
            'bb_std': [r'bb?[_\s]*(?:std|dev|sigma)\s*[=:]\s*([\d.]+)',
                      r'bollinger.*?std\s*[=:]\s*([\d.]+)'],
        },
    },
    'macd_rotation': {
        'keywords': ['macd', 'moving.*average.*convergence', 'histogram.*cross',
                    'signal.*line.*cross'],
        'strategy_func': 'strategy_macd_rotation',
        'param_extractors': {
            'fast_period': [r'fast[_\s]*(?:period|window|ema)\s*[=:]\s*(\d+)',
                          r'macd.*?fast\s*[=:]\s*(\d+)'],
            'slow_period': [r'slow[_\s]*(?:period|window|ema)\s*[=:]\s*(\d+)',
                          r'macd.*?slow\s*[=:]\s*(\d+)'],
            'signal_period': [r'signal[_\s]*(?:period|window|ema)\s*[=:]\s*(\d+)',
                            r'macd.*?signal\s*[=:]\s*(\d+)'],
        },
    },
    'rsi_rotation': {
        'keywords': ['rsi', 'relative.*strength.*index', 'overbought', 'oversold',
                    'rsi.*cross', 'rsi.*rotation'],
        'strategy_func': 'strategy_rsi_rotation',
        'param_extractors': {
            'rsi_period': [r'rsi[_\s]*(?:period|window|length)\s*[=:]\s*(\d+)',
                         r'rsi.*?period\s*[=:]\s*(\d+)'],
            'oversold': [r'oversold\s*[=:]\s*(\d+)', r'rsi.*?low\s*[=:]\s*(\d+)'],
            'overbought': [r'overbought\s*[=:]\s*(\d+)', r'rsi.*?high\s*[=:]\s*(\d+)'],
        },
    },
    'all_weather': {
        'keywords': ['all.?weather', 'risk.?parity', 'permanent.*portfolio',
                    'golden.*butterfly', '全天候', '风险平价'],
        'strategy_func': 'strategy_all_weather',
        'param_extractors': {
            'rebalance_days': [r'rebalance[_\s]*(?:days?|freq|period)\s*[=:]\s*(\d+)',
                             r'(\d+)\s*day.*rebalance'],
            'vol_lookback': [r'vol(?:atility)?[_\s]*(?:lookback|window|period)\s*[=:]\s*(\d+)',
                           r'rolling.*?std.*?(\d+)'],
        },
    },
    'dividend_rotation': {
        'keywords': ['dividend', 'yield.*rotation', 'high.*yield', '红利', '股息'],
        'strategy_func': 'strategy_dividend_rotation',
        'param_extractors': {
            'lookback_months': [r'lookback[_\s]*(?:months?|period)\s*[=:]\s*(\d+)'],
            'min_yield_pct': [r'min.*?yield\s*[=:]\s*([\d.]+)',
                            r'yield.*?threshold\s*[=:]\s*([\d.]+)'],
        },
    },
    'macro_rotation': {
        'keywords': ['macro.*rotation', 'economic.*cycle', 'regime.*switch',
                    'business.*cycle', '宏观轮动'],
        'strategy_func': 'strategy_macro_rotation',
        'param_extractors': {
            'lookback_months': [r'lookback[_\s]*(?:months?|period)\s*[=:]\s*(\d+)'],
            'sma_period': [r'sma[_\s]*(?:period|window)\s*[=:]\s*(\d+)'],
        },
    },
}


# ================================================================
# ETF/资产池发现：从代码中识别使用的ETF和资产
# ================================================================

# 已知ETF代码及其类别
KNOWN_ETFS = {
    # 美股宽基
    'SPY': 'us_equity', 'VOO': 'us_equity', 'IVV': 'us_equity', 'QQQ': 'us_tech',
    'DIA': 'us_equity', 'IWM': 'us_small_cap', 'VTI': 'us_total',
    # 国际
    'VEA': 'intl_developed', 'VWO': 'emerging', 'EFA': 'intl_developed',
    'IEFA': 'intl_developed', 'IXUS': 'intl_ex_us',
    # 债券
    'AGG': 'us_bond', 'BND': 'us_bond', 'SHY': 'us_short_bond', 'SHV': 'us_short_bond',
    'TLT': 'us_long_bond', 'IEF': 'us_mid_bond', 'LQD': 'us_corp_bond',
    'BNDX': 'intl_bond',
    # 商品
    'GLD': 'gold', 'IAU': 'gold', 'SLV': 'silver', 'DBC': 'commodities',
    'USO': 'oil', 'GSG': 'commodities',
    # 房产
    'VNQ': 'us_reits', 'IYR': 'us_reits',
    # TIPS
    'TIP': 'tips', 'SCHP': 'tips',
    # 港股
    '2800': 'hk_equity', '2801': 'hk_equity', '2828': 'hk_hshare',
    '0700': 'hk_tech', '9988': 'hk_tech',
}

# 默认资产池组合
ASSET_PRESETS = {
    'classic_4': {'risk': ['SPY', 'VEA'], 'safe': ['AGG', 'SHY']},
    'with_gold': {'risk': ['SPY', 'VEA', 'GLD'], 'safe': ['AGG', 'SHY']},
    'with_gold_tlt': {'risk': ['SPY', 'VEA', 'GLD'], 'safe': ['AGG', 'SHY', 'TLT']},
    'spy_gld_shy': {'risk': ['SPY'], 'safe': ['GLD', 'SHY']},
    'qqq_spy_gld': {'risk': ['QQQ', 'SPY', 'GLD'], 'safe': ['AGG', 'SHY']},
    'sp500_only': {'risk': ['SPY'], 'safe': ['SHY']},
    'all_weather': {'risk': ['SPY', 'VEA', 'GLD'], 'safe': ['AGG', 'SHY', 'TLT']},
}


def discover_assets_from_code(code: str) -> Dict[str, List[str]]:
    """
    从策略代码中发现使用的ETF/资产池
    返回: {'risk': [...], 'safe': [...]}
    """
    found = {}
    code_upper = code.upper()
    
    for etf, category in KNOWN_ETFS.items():
        if etf in code_upper:
            found[etf] = category
    
    # 分类为risk和safe
    risk = [etf for etf, cat in found.items() 
            if cat in ('us_equity', 'us_tech', 'us_small_cap', 'us_total',
                      'intl_developed', 'emerging', 'gold', 'commodities',
                      'hk_equity', 'hk_tech')]
    safe = [etf for etf, cat in found.items() 
            if cat in ('us_bond', 'us_short_bond', 'us_long_bond', 'us_mid_bond',
                      'us_corp_bond', 'tips', 'intl_bond')]
    
    # 确保至少有一个risk和一个safe
    if not risk:
        risk = ['SPY', 'VEA']
    if not safe:
        safe = ['AGG', 'SHY']
    
    return {'risk': risk, 'safe': safe}


def match_asset_preset(assets: Dict[str, List[str]]) -> str:
    """将发现的资产池匹配到最近的预设"""
    all_found = set(assets['risk'] + assets['safe'])
    best_match = 'classic_4'
    best_overlap = 0
    
    for preset_name, preset in ASSET_PRESETS.items():
        all_preset = set(preset['risk'] + preset['safe'])
        overlap = len(all_found & all_preset)
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = preset_name
    
    return best_match


# ================================================================
# 参数提取：从代码中提取策略参数值
# ================================================================

def extract_params_from_code(code: str, pattern_name: str) -> Dict[str, Any]:
    """
    从策略代码中提取特定策略类型的参数值
    """
    pattern = STRATEGY_PATTERNS.get(pattern_name, {})
    extractors = pattern.get('param_extractors', {})
    
    extracted = {}
    for param_name, regex_list in extractors.items():
        for regex in regex_list:
            match = re.search(regex, code, re.IGNORECASE)
            if match:
                try:
                    value = int(match.group(1)) if '.' not in match.group(1) else float(match.group(1))
                    # 参数范围验证
                    if param_name in ('lookback_months', 'buffer_days', 'bb_period',
                                     'fast_period', 'slow_period', 'signal_period',
                                     'rsi_period', 'rebalance_days', 'vol_lookback',
                                     'sma_period', 'top_n'):
                        value = max(1, min(60, value))  # 1-60范围
                    elif param_name in ('bb_std', 'abs_momentum_threshold', 'min_yield_pct'):
                        value = max(0, min(5.0, value))  # 0-5范围
                    elif param_name in ('oversold', 'overbought'):
                        value = max(1, min(99, value))  # RSI范围1-99
                    
                    extracted[param_name] = value
                    break  # 找到第一个匹配就够了
                except (ValueError, IndexError):
                    continue
    
    return extracted


# ================================================================
# 策略模式分类：识别代码属于哪种策略类型
# ================================================================

def classify_strategy_code(code: str) -> List[Tuple[str, float]]:
    """
    分类策略代码，返回匹配的策略类型和置信度
    格式: [(pattern_name, confidence), ...]
    """
    code_lower = code.lower()
    matches = []
    
    for pattern_name, pattern_def in STRATEGY_PATTERNS.items():
        keyword_matches = 0
        for kw in pattern_def['keywords']:
            if re.search(kw, code_lower):
                keyword_matches += 1
        
        if keyword_matches > 0:
            confidence = keyword_matches / len(pattern_def['keywords'])
            matches.append((pattern_name, confidence))
    
    # 按置信度排序
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


# ================================================================
# 策略变体生成：将搜索结果转换为可回测的策略
# ================================================================

def adapt_searched_strategies(
    search_results: List[Dict],
    strategy_funcs: Dict[str, callable],
    existing_fingerprints: set = None,
) -> List[Dict]:
    """
    将搜索到的策略代码适配为可回测的策略变体
    
    Args:
        search_results: multi_source_searcher的搜索结果
        strategy_funcs: 内置策略函数映射 {'strategy_gem_rotation': func, ...}
        existing_fingerprints: 已有策略指纹集合
    
    Returns:
        策略变体列表，格式与generate_strategy_variants一致
    """
    if existing_fingerprints is None:
        existing_fingerprints = set()
    
    variants = []
    seen_variants = set()  # 去重
    
    for result in search_results:
        code = result.get('code', '')
        name = result.get('name', '未知')
        source = result.get('source', '')
        source_link = result.get('source_link', '')
        description = result.get('description', '')
        
        if not code or len(code) < 100:
            continue
        
        # 1. 分类策略代码
        pattern_matches = classify_strategy_code(code)
        
        if not pattern_matches:
            # 无法识别策略类型，尝试用通用方法提取
            generic_variants = _extract_generic_variants(
                code, name, source, source_link, description,
                strategy_funcs, existing_fingerprints, seen_variants
            )
            variants.extend(generic_variants)
            continue
        
        # 2. 对每种匹配的策略模式，提取参数
        assets = discover_assets_from_code(code)
        asset_preset = match_asset_preset(assets)
        
        for pattern_name, confidence in pattern_matches[:2]:  # 最多取前2种模式
            pattern_def = STRATEGY_PATTERNS[pattern_name]
            func_name = pattern_def['strategy_func']
            
            if func_name not in strategy_funcs:
                continue
            
            strategy_func = strategy_funcs[func_name]
            
            # 提取参数
            extracted_params = extract_params_from_code(code, pattern_name)
            
            # 3. 生成策略变体
            variant = _build_strategy_variant(
                strategy_func=strategy_func,
                func_name=func_name,
                extracted_params=extracted_params,
                assets=assets,
                asset_preset=asset_preset,
                name=name,
                source=source,
                source_link=source_link,
                description=description,
                confidence=confidence,
            )
            
            if variant:
                fp = variant.get('_fingerprint', '')
                if fp not in existing_fingerprints and fp not in seen_variants:
                    seen_variants.add(fp)
                    variants.append(variant)
    
    return variants


def _build_strategy_variant(
    strategy_func: callable,
    func_name: str,
    extracted_params: Dict[str, Any],
    assets: Dict[str, List[str]],
    asset_preset: str,
    name: str,
    source: str,
    source_link: str,
    description: str,
    confidence: float,
) -> Optional[Dict]:
    """构建单个策略变体"""
    
    # 根据策略函数类型组装参数
    if func_name == 'strategy_gem_rotation':
        kwargs = {
            'lookback_months': extracted_params.get('lookback_months', 12),
            'buffer_days': extracted_params.get('buffer_days', 0),
            'risk_assets': assets['risk'],
            'safe_assets': assets['safe'],
        }
        params = {
            'lookback_months': kwargs['lookback_months'],
            'buffer_days': kwargs['buffer_days'],
            'assets': '/'.join(assets['risk'] + assets['safe']),
        }
        variant_name = f'GEM搜索_{kwargs["lookback_months"]}M'
        if kwargs['buffer_days'] > 0:
            variant_name += f'+{kwargs["buffer_days"]}d缓冲'
        variant_name += f'_{asset_preset}'
        desc = f'来自{source}的GEM轮动策略灵感'
        strategy_type = '趋势跟踪'
        
    elif func_name == 'strategy_dual_momentum':
        kwargs = {
            'lookback_months': extracted_params.get('lookback_months', 12),
            'buffer_days': extracted_params.get('buffer_days', 0),
            'abs_momentum_threshold': extracted_params.get('abs_momentum_threshold', 0),
        }
        params = {
            'lookback_months': kwargs['lookback_months'],
            'buffer_days': kwargs['buffer_days'],
            'abs_momentum_threshold': kwargs['abs_momentum_threshold'],
        }
        variant_name = f'双动量搜索_{kwargs["lookback_months"]}M_阈值{kwargs["abs_momentum_threshold"]:.0%}'
        desc = f'来自{source}的双重动量策略灵感'
        strategy_type = '趋势跟踪'
        
    elif func_name == 'strategy_multi_asset_rotation':
        kwargs = {
            'lookback_months': extracted_params.get('lookback_months', 12),
            'buffer_days': extracted_params.get('buffer_days', 0),
            'top_n': extracted_params.get('top_n', 1),
        }
        params = {
            'lookback_months': kwargs['lookback_months'],
            'buffer_days': kwargs['buffer_days'],
            'top_n': kwargs['top_n'],
            'assets': '/'.join(assets['risk'] + assets['safe']),
        }
        variant_name = f'自由轮动搜索_{kwargs["lookback_months"]}M_{asset_preset}'
        desc = f'来自{source}的轮动策略灵感'
        strategy_type = '趋势跟踪'
        
    elif func_name == 'strategy_bollinger_reversion':
        kwargs = {
            'bb_period': extracted_params.get('bb_period', 20),
            'bb_std': extracted_params.get('bb_std', 2.0),
        }
        params = {
            'bb_period': kwargs['bb_period'],
            'bb_std': kwargs['bb_std'],
        }
        variant_name = f'布林回归搜索_{kwargs["bb_period"]}p_{kwargs["bb_std"]}std'
        desc = f'来自{source}的布林带回归策略灵感'
        strategy_type = '均值回归'
        
    elif func_name == 'strategy_macd_rotation':
        kwargs = {
            'fast_period': extracted_params.get('fast_period', 12),
            'slow_period': extracted_params.get('slow_period', 26),
            'signal_period': extracted_params.get('signal_period', 9),
        }
        params = kwargs.copy()
        variant_name = f'MACD轮动搜索_{kwargs["fast_period"]}/{kwargs["slow_period"]}/{kwargs["signal_period"]}'
        desc = f'来自{source}的MACD轮动策略灵感'
        strategy_type = '趋势跟踪'
        
    elif func_name == 'strategy_rsi_rotation':
        kwargs = {
            'rsi_period': extracted_params.get('rsi_period', 14),
            'oversold': extracted_params.get('oversold', 30),
            'overbought': extracted_params.get('overbought', 70),
        }
        params = kwargs.copy()
        variant_name = f'RSI轮动搜索_{kwargs["rsi_period"]}p_{kwargs["oversold"]}/{kwargs["overbought"]}'
        desc = f'来自{source}的RSI轮动策略灵感'
        strategy_type = '均值回归'
        
    elif func_name == 'strategy_all_weather':
        kwargs = {
            'rebalance_days': extracted_params.get('rebalance_days', 90),
            'vol_lookback': extracted_params.get('vol_lookback', 60),
        }
        params = kwargs.copy()
        variant_name = f'全天候搜索_{kwargs["rebalance_days"]}d再平衡'
        desc = f'来自{source}的全天候策略灵感'
        strategy_type = '资产配置'
        
    elif func_name == 'strategy_dividend_rotation':
        kwargs = {
            'lookback_months': extracted_params.get('lookback_months', 12),
            'min_yield_pct': extracted_params.get('min_yield_pct', 2.0),
        }
        params = kwargs.copy()
        variant_name = f'红利轮动搜索_{kwargs["lookback_months"]}M'
        desc = f'来自{source}的红利轮动策略灵感'
        strategy_type = '趋势跟踪'
        
    elif func_name == 'strategy_macro_rotation':
        kwargs = {
            'lookback_months': extracted_params.get('lookback_months', 6),
            'sma_period': extracted_params.get('sma_period', 200),
        }
        params = kwargs.copy()
        variant_name = f'宏观轮动搜索_{kwargs["lookback_months"]}M_{kwargs["sma_period"]}SMA'
        desc = f'来自{source}的宏观轮动策略灵感'
        strategy_type = '趋势跟踪'
    else:
        return None
    
    # 生成指纹
    params_str = json.dumps(params, sort_keys=True)
    fingerprint = hashlib.sha256(f"{variant_name}_{params_str}".encode()).hexdigest()
    
    return {
        'name': variant_name,
        'func': strategy_func,
        'kwargs': kwargs,
        'params': params,
        'desc': desc,
        'type': strategy_type,
        '_fingerprint': fingerprint,
        'source': source,
        'source_link': source_link,
        'source_description': description[:200],
        'confidence': round(confidence, 2),
        'is_search_derived': True,  # 标记为搜索来源的策略
    }


def _extract_generic_variants(
    code: str, name: str, source: str, source_link: str,
    description: str, strategy_funcs: Dict[str, callable],
    existing_fingerprints: set, seen_variants: set
) -> List[Dict]:
    """
    从无法精确分类的代码中提取通用参数变体
    """
    variants = []
    
    # 尝试提取通用参数
    lookback = None
    for pattern in [r'lookback\s*[=:]\s*(\d+)', r'window\s*[=:]\s*(\d+)',
                   r'period\s*[=:]\s*(\d+)', r'(\d+)\s*month']:
        match = re.search(pattern, code, re.IGNORECASE)
        if match:
            lookback = int(match.group(1))
            break
    
    assets = discover_assets_from_code(code)
    
    # 如果提取到了lookback，生成GEM和轮动变体
    if lookback and 1 <= lookback <= 24:
        for func_name, variant_suffix in [
            ('strategy_gem_rotation', 'GEM'),
            ('strategy_multi_asset_rotation', '轮动'),
        ]:
            if func_name not in strategy_funcs:
                continue
            
            strategy_func = strategy_funcs[func_name]
            kwargs = {
                'lookback_months': lookback,
                'buffer_days': 0,
            }
            if func_name == 'strategy_gem_rotation':
                kwargs.update({'risk_assets': assets['risk'], 'safe_assets': assets['safe']})
            elif func_name == 'strategy_multi_asset_rotation':
                kwargs.update({'top_n': 1})
            
            params = {k: v for k, v in kwargs.items() if k != 'risk_assets' and k != 'safe_assets'}
            params['assets'] = '/'.join(assets['risk'] + assets['safe'])
            
            variant_name = f'{variant_suffix}搜索_{lookback}M通用'
            params_str = json.dumps(params, sort_keys=True)
            fingerprint = hashlib.sha256(f"{variant_name}_{params_str}".encode()).hexdigest()
            
            if fingerprint not in existing_fingerprints and fingerprint not in seen_variants:
                seen_variants.add(fingerprint)
                variants.append({
                    'name': variant_name,
                    'func': strategy_func,
                    'kwargs': kwargs,
                    'params': params,
                    'desc': f'来自{source}的{variant_suffix}策略灵感（通用参数提取）',
                    'type': '趋势跟踪',
                    '_fingerprint': fingerprint,
                    'source': source,
                    'source_link': source_link,
                    'source_description': description[:200],
                    'confidence': 0.3,
                    'is_search_derived': True,
                })
    
    return variants


# ================================================================
# 测试
# ================================================================

if __name__ == '__main__':
    # 测试代码适配器
    test_code = """
    import pandas as pd
    import numpy as np
    
    def dual_momentum_strategy(prices, lookback_months=9, abs_threshold=0.02):
        # Dual Momentum: relative + absolute
        risk_assets = ['SPY', 'VEA']
        safe_assets = ['AGG', 'SHY']
        
        # Calculate momentum scores
        lookback_days = lookback_months * 21
        momentum = prices.pct_change(lookback_days)
        
        # Relative momentum: pick best risk asset
        best_risk = momentum[risk_assets].idxmax(axis=1)
        
        # Absolute momentum: check if positive
        abs_check = momentum[risk_assets] > abs_threshold
        
        # Combine signals
        signal = np.where(abs_check, 1, 0)
        return signal
    
    def backtest():
        lookback = 9  # months
        buffer_days = 3
    """
    
    # 分类
    matches = classify_strategy_code(test_code)
    print("策略模式匹配:")
    for name, conf in matches:
        print(f"  {name}: {conf:.2f}")
    
    # 参数提取
    for name, conf in matches[:1]:
        params = extract_params_from_code(test_code, name)
        print(f"\n{name} 提取的参数: {params}")
    
    # 资产发现
    assets = discover_assets_from_code(test_code)
    print(f"\n发现的资产池: {assets}")
    print(f"匹配的预设: {match_asset_preset(assets)}")
