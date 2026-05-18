#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股排行榜策略统一回测 v3
====================
对A股穿越牛熊排行榜所有策略，使用 2019-2024主区间 + 2015-2018压力测试 统一回测
直接复用已有的 qixing_v172_strategy 和 vectorized_backtest 引擎

v3 修正：
- 策略1和3本质相同（同是V1.7.2+大池38只+无成交量过滤），合并
- 策略4（三马105原版组合）改为真正运行50%小市值+50%ETF轮动
- 加入V1.7.2短周期(15日)等变体以丰富排行榜
"""

import os, sys, json, math, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade

# 导入已有的V1.7.2策略和回测引擎
from backtest_sanma105_qixing172 import (
    qixing_v172_strategy, vectorized_backtest,
    CN_ETF_POOL_FULL, DEFENSIVE_ETF
)

# 导入三马105原版组合的回测
from backtest_sanma105_original import small_cap_strategy, compute_backtest_metrics

# ================================================================
# 回测区间（用户指定）
# ================================================================
MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'
STRESS_START = '2015-01-01'
STRESS_END = '2018-12-31'

# ================================================================
# 数据路径
# ================================================================
DATA_DIR = '/data/workspace/back_trader_stocks/a'
CN_RISK_FREE_RATE = 0.02

# ================================================================
# 6+1池
# ================================================================
QIXING_61_INVEST = [
    '159915_XSHE', '513100_XSHG', '159985_XSHE', '518880_XSHG',
    '501018_XSHG', '161226_XSHE',
]
QIXING_61_SAFE = ['511220_XSHG']
QIXING_61_POOL = list(dict.fromkeys(QIXING_61_INVEST + QIXING_61_SAFE))

# 内置策略映射（美股ETF → A股ETF）
CN_ETF_MAP = {
    'SPY': '510300_XSHG',
    'QQQ': '159915_XSHE',
    'VEA': '510500_XSHG',
    'AGG': '511010_XSHG',
    'SHY': '511880_XSHG',
    'GLD': '518880_XSHG',
    'TLT': '511260_XSHG',
}

ETF_NAMES = {
    '518880_XSHG': '黄金ETF', '159985_XSHE': '豆粕ETF', '513100_XSHG': '纳指ETF',
    '159915_XSHE': '创业板ETF', '511880_XSHG': '银华日利', '510300_XSHG': '沪深300ETF',
    '510500_XSHG': '中证500ETF', '512880_XSHG': '证券ETF', '512660_XSHG': '军工ETF',
    '513500_XSHG': '标普500ETF', '513130_XSHG': '恒生科技ETF', '512100_XSHG': '中证1000ETF',
    '512040_XSHG': '价值100ETF', '511010_XSHG': '国债ETF', '511260_XSHG': '十年国债ETF',
    '510050_XSHG': '上证50ETF', '512890_XSHG': '红利低波ETF', '513080_XSHG': '德国DAXETF',
    '513520_XSHG': '日经225ETF', '513690_XSHG': '法国CAC40ETF', '501018_XSHG': '南方原油LOF',
    '159792_XSHE': '科技创新ETF', '159967_XSHE': '创成长ETF', '159980_XSHE': '有色ETF',
    '159981_XSHE': '能源化工ETF', '511220_XSHG': '城投ETF', '511380_XSHG': '十年国开ETF',
    '159919_XSHE': '沪深300ETF联接', '159920_XSHE': '恒生ETF', '510210_XSHG': '上证指数ETF',
    '513290_XSHG': '纳斯达克生物ETF', '513310_XSHG': '东南亚科技ETF', '513050_XSHG': '中日ETF',
'159529_XSHE': '科创50ETF', '159509_XSHE': '中证500ETF联接', '161226_XSHE': '国投白银LOF',
}


# ================================================================
# 数据加载
# ================================================================
def load_etf_data(etf_pool, data_dir=DATA_DIR):
    """加载ETF数据，返回{code: DataFrame}"""
    data = {}
    for code in etf_pool:
        filepath = os.path.join(data_dir, f'{code}.csv')
        if not os.path.exists(filepath):
            continue
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            col_map = {}
            for c in df.columns:
                cl = c.strip().lower()
                if cl in ('close', '收盘'): col_map[c] = 'Close'
                elif cl in ('high', '最高'): col_map[c] = 'High'
                elif cl in ('low', '最低'): col_map[c] = 'Low'
                elif cl in ('open', '开盘'): col_map[c] = 'Open'
                elif cl in ('volume', '成交量'): col_map[c] = 'Volume'
            df = df.rename(columns=col_map)
            for needed in ['High', 'Low', 'Open']:
                if needed not in df.columns and 'Close' in df.columns:
                    df[needed] = df['Close']
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            if 'Close' in df.columns and len(df) >= 100:
                data[code] = df
        except:
            pass
    return data


def build_price_matrices(data):
    """构建收盘价/最高价/成交量矩阵"""
    close_dict, high_dict, vol_dict = {}, {}, {}
    for code, df in data.items():
        if 'Close' in df.columns: close_dict[code] = df['Close']
        if 'High' in df.columns: high_dict[code] = df['High']
        if 'Volume' in df.columns: vol_dict[code] = df['Volume']
    
    close_df = pd.DataFrame(close_dict).sort_index() if close_dict else pd.DataFrame()
    high_df = pd.DataFrame(high_dict).sort_index() if high_dict else pd.DataFrame()
    vol_df = pd.DataFrame(vol_dict).sort_index() if vol_dict else pd.DataFrame()
    
    for df in [close_df, high_df, vol_df]:
        if not df.empty:
            df.ffill(inplace=True)
            df.bfill(inplace=True)
    
    return close_df, high_df, vol_df


def load_stock_data(data_dir=DATA_DIR, max_stocks=3000):
    """加载A股个股数据用于小市值策略（2026-04-29扩展：支持全市场3268只）"""
    stock_data = {}
    etf_prefixes = ('510', '511', '512', '513', '159', '501', '161', '518', '588', '563')
    
    all_files = sorted([f for f in os.listdir(data_dir) if f.endswith('.csv')])
    count = 0
    for fname in all_files:
        code = fname.replace('.csv', '')
        # 跳过ETF和指数
        code_num = code.split('_')[0]
        if any(code_num.startswith(p) for p in etf_prefixes):
            continue
        # 沪深主板+中小板+创业板+科创板
        if not (code_num.startswith('000') or code_num.startswith('001') or 
                code_num.startswith('002') or code_num.startswith('003') or
                code_num.startswith('300') or code_num.startswith('301') or
                code_num.startswith('600') or code_num.startswith('601') or
                code_num.startswith('603') or code_num.startswith('605') or
                code_num.startswith('688')):
            continue
        
        filepath = os.path.join(data_dir, fname)
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            col_map = {}
            for c in df.columns:
                cl = c.strip().lower()
                if cl in ('close', '收盘'): col_map[c] = 'Close'
                elif cl in ('volume', '成交量'): col_map[c] = 'Volume'
            df = df.rename(columns=col_map)
            if 'Close' in df.columns and len(df) >= 500:
                stock_data[code] = df[['Close']]
                count += 1
                if count >= max_stocks:
                    break
        except:
            pass
    
    return stock_data


# ================================================================
# 七星高照6+1策略信号
# ================================================================
def qixing_61_signal(close_prices, etf_pool, safe_assets, short_lookback=25, long_lookback=250,
                      drop_days=4, drop_pct=5, defensive_etf=None):
    """七星高照6+1策略 — 周五调仓版"""
    if defensive_etf is None:
        defensive_etf = safe_assets[0] if safe_assets else etf_pool[-1]
    
    pool_in_data = [a for a in etf_pool if a in close_prices.columns]
    safe_in_data = [a for a in safe_assets if a in close_prices.columns]
    if defensive_etf not in close_prices.columns:
        defensive_etf = safe_in_data[0] if safe_in_data else pool_in_data[-1]
    
    dates = close_prices.index
    n = len(dates)
    holding = pd.Series(defensive_etf, index=dates)
    current = defensive_etf
    position_high = None
    buy_cost = None
    
    fridays = close_prices.resample('W-FRI').last().dropna().index
    fridays = fridays[fridays.isin(dates)]
    rebal_set = set(fridays)
    
    for i in range(60, n):
        date = dates[i]
        
        # 盈利保护：盘中检查
        if current in close_prices.columns and current != defensive_etf:
            price_now = close_prices[current].iloc[i]
            if position_high is not None and price_now < position_high * 0.95:
                current = defensive_etf
                position_high = None
                buy_cost = None
                holding.iloc[i] = current
                continue
        
        if date not in rebal_set:
            holding.iloc[i] = current
            continue
        
        best_etf = None
        best_score = -999
        
        for etf in pool_in_data:
            if pd.isna(close_prices[etf].iloc[i]) or close_prices[etf].iloc[i] <= 0:
                continue
            
            lookback = min(short_lookback, i)
            if lookback < 5:
                continue
            
            sp = close_prices[etf].iloc[i - lookback:i + 1].dropna()
            if len(sp) < 5:
                continue
            
            if len(sp) >= drop_days + 1:
                recent = sp.iloc[-(drop_days + 1):]
                max_drop = (recent.iloc[-1] / recent.iloc[0]) - 1
                if max_drop < -drop_pct / 100:
                    continue
            
            y = np.log(sp.values.astype(float))
            x = np.arange(len(y), dtype=float)
            w = np.linspace(1, 2, len(y))
            try:
                coeffs = np.polyfit(x, y, 1, w=w)
                slope = coeffs[0]
            except:
                continue
            ann_ret = math.exp(slope * 252) - 1
            y_pred = slope * x + coeffs[1]
            ss_res = np.sum(w * (y - y_pred) ** 2)
            y_mean = np.average(y, weights=w)
            ss_tot = np.sum(w * (y - y_mean) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0
            short_score = ann_ret * r2
            if short_score <= 0 or short_score > 6.0:
                short_score = 0
            
            long_look = min(long_lookback, i)
            lp = close_prices[etf].iloc[i - long_look:i + 1].dropna()
            if len(lp) >= 20:
                y2 = np.log(lp.values.astype(float))
                x2 = np.arange(len(y2), dtype=float)
                w2 = np.linspace(1, 2, len(y2))
                try:
                    c2 = np.polyfit(x2, y2, 1, w=w2)
                    s2 = c2[0]
                except:
                    s2 = 0
                ann2 = math.exp(s2 * 252) - 1
                long_score = ann2 * r2 if ann2 > 0 and ann2 < 0.5 else 0
                combined = short_score + long_score
            else:
                combined = short_score
            
            if combined > best_score:
                best_score = combined
                best_etf = etf
        
        if best_etf is None or best_score <= 0:
            target = defensive_etf
        else:
            target = best_etf
        
        if target != current:
            current = target
            buy_cost = close_prices[current].iloc[i] if current in close_prices.columns else None
            position_high = buy_cost
        
        if current in close_prices.columns:
            position_high = max(position_high or 0, close_prices[current].iloc[i])
        
        holding.iloc[i] = current
    
    return {'holding': holding, 'trades': []}


# ================================================================
# 内置轮动策略信号
# ================================================================
def builtin_rotation_signal(close_prices, risk_assets, safe_assets, lookback_months, buffer_days=3,
                             abs_momentum_threshold=0.0, defensive_etf=None):
    """内置月度动量轮动策略"""
    if defensive_etf is None:
        defensive_etf = safe_assets[0] if safe_assets else close_prices.columns[0]
    
    all_assets = risk_assets + safe_assets
    pool_in_data = [a for a in all_assets if a in close_prices.columns]
    risk_in_data = [a for a in risk_assets if a in close_prices.columns]
    safe_in_data = [a for a in safe_assets if a in close_prices.columns]
    
    if not pool_in_data:
        return {'holding': pd.Series(defensive_etf, index=close_prices.index), 'trades': []}
    
    dates = close_prices.index
    n = len(dates)
    holding = pd.Series(defensive_etf, index=dates)
    current = defensive_etf
    lookback_days = lookback_months * 21
    last_switch_idx = -999
    
    for i in range(lookback_days, n):
        if i - last_switch_idx < buffer_days:
            holding.iloc[i] = current
            continue
        
        best_asset = defensive_etf
        best_momentum = -999
        
        for asset in pool_in_data:
            prices = close_prices[asset].iloc[max(0, i - lookback_days):i + 1].dropna()
            if len(prices) < 20:
                continue
            momentum = (prices.iloc[-1] / prices.iloc[0]) - 1
            
            if abs_momentum_threshold > 0 and asset in risk_in_data:
                if momentum < abs_momentum_threshold:
                    continue
            
            if momentum > best_momentum:
                best_momentum = momentum
                best_asset = asset
        
        if best_momentum < 0 and safe_in_data:
            best_asset = safe_in_data[0]
        
        if best_asset != current:
            current = best_asset
            last_switch_idx = i
        
        holding.iloc[i] = current
    
    return {'holding': holding, 'trades': []}


# ================================================================
# 统一回测入口
# ================================================================
def run_strategy_backtest(strategy_name, signal_result, close_df, start_date, end_date):
    """使用V1.7.2的向量化回测引擎"""
    holding = signal_result['holding']
    
    mask = (close_df.index >= start_date) & (close_df.index <= end_date)
    cp = close_df[mask]
    h = holding[mask]
    
    if len(cp) < 30:
        return None
    
    common_idx = cp.index.intersection(h.index)
    if len(common_idx) < 30:
        return None
    
    bt_result = vectorized_backtest(
        cp, h,
        init_cash=1_000_000,
        fees_rate=0.0006,
        slippage=0.001,
        risk_free_rate=CN_RISK_FREE_RATE
    )
    
    return bt_result


def run_combined_backtest(etf_signal_result, stock_close_df, etf_close_df, safe_etf,
                           start_date, end_date):
    """50%小市值+50%ETF轮动组合回测（2026-04-29修复ETF收益计算bug）"""
    etf_holding = etf_signal_result['holding']
    
    mask = (etf_close_df.index >= start_date) & (etf_close_df.index <= end_date)
    etf_cp = etf_close_df[mask]
    etf_h = etf_holding[mask]
    
    stock_mask = (stock_close_df.index >= start_date) & (stock_close_df.index <= end_date)
    stock_cp = stock_close_df[stock_mask]
    
    if len(etf_cp) < 30 or len(stock_cp) < 30:
        return None
    
    # ETF轮动日收益率（修复版：正确计算持有/换仓收益）
    common_idx = etf_cp.index.intersection(etf_h.index)
    if len(common_idx) < 30:
        return None
    
    etf_cp_aligned = etf_cp.loc[common_idx]
    etf_h_aligned = etf_h.loc[common_idx]
    
    # 向量化计算ETF日收益率
    etf_daily_ret = etf_cp_aligned.pct_change()
    etf_returns = pd.Series(0.0, index=common_idx)
    prev_h = None
    for i, date in enumerate(common_idx):
        curr_h = etf_h_aligned.loc[date]
        if curr_h in etf_daily_ret.columns and i > 0:
            dr = etf_daily_ret[curr_h].iloc[i]
            if pd.notna(dr):
                etf_returns.iloc[i] = dr
        # 换仓扣除交易成本
        if prev_h is not None and curr_h != prev_h:
            etf_returns.iloc[i] -= 0.004  # 双边手续费+滑点
        prev_h = curr_h
    
    # 小市值策略日收益率
    sc_result = small_cap_strategy(
        stock_cp, etf_cp_aligned, safe_etf,
        top_n=5, rebalance_days=20,
        use_consistency_filter=True,
        use_defensive=True, ma_bear_period=120,
    )
    sc_returns = sc_result.get('daily_returns', pd.Series(0.0, index=stock_cp.index))
    
    # 对齐
    common_all = etf_returns.index.intersection(sc_returns.index)
    if len(common_all) < 30:
        # 如果个股数据不足，退化为纯ETF轮动
        combined_returns = etf_returns
    else:
        sc_aligned = sc_returns.reindex(common_all).fillna(0)
        etf_aligned = etf_returns.reindex(common_all).fillna(0)
        combined_returns = 0.5 * sc_aligned + 0.5 * etf_aligned
    
    metrics = compute_backtest_metrics(combined_returns)
    return metrics


# ================================================================
# 定义所有A股排行榜策略
# ================================================================
def get_all_strategies():
    strategies = []
    
    # ── 1. 七星高照ETF轮动V1.7.2-无成交量过滤 ──
    # 注意：三马105七星17-ETF轮动V1.7.2 与此策略完全相同（同逻辑+同ETF池+同参数）
    # 统一回测区间下不再单独列项
    strategies.append({
        'name': '七星高照ETF轮动V1.7.2-无成交量过滤',
        'type': '七星高照V1.7.2',
        'signal_func': 'qixing_v172',
        'signal_kwargs': {
            'lookback_days': 25,
            'enable_volume_check': False,
            'use_short_momentum_filter': True,
            'short_lookback_days': 10,
            'short_momentum_threshold': 0.0,
            'enable_profit_protection': True,
            'profit_protection_threshold': 0.05,
            'loss_limit': 0.97,
            'stop_loss': 0.95,
        },
        'fingerprint': 'v172_novol_2019_2024',
    })
    
    # ── 2. 七星高照ETF轮动V1.7.2-大池完整版（含成交量过滤） ──
    strategies.append({
        'name': '七星高照ETF轮动V1.7.2-大池完整版',
        'type': '七星高照V1.7.2',
        'signal_func': 'qixing_v172',
        'signal_kwargs': {
            'lookback_days': 25,
            'enable_volume_check': True,
            'volume_lookback': 5,
            'volume_threshold': 2.0,
            'volume_return_limit': 1.0,
            'use_short_momentum_filter': True,
            'short_lookback_days': 10,
            'short_momentum_threshold': 0.0,
            'enable_profit_protection': True,
            'profit_protection_threshold': 0.05,
            'loss_limit': 0.97,
            'stop_loss': 0.95,
        },
        'fingerprint': 'v172_full_2019_2024',
    })
    
    # ── 3. 七星高照V1.7.2-短周期(15日) ──
    strategies.append({
        'name': '七星高照V1.7.2-短周期(15日)',
        'type': '七星高照V1.7.2',
        'signal_func': 'qixing_v172',
        'signal_kwargs': {
            'lookback_days': 15,
            'enable_volume_check': False,
            'use_short_momentum_filter': True,
            'short_lookback_days': 7,
            'short_momentum_threshold': 0.0,
            'enable_profit_protection': True,
            'profit_protection_threshold': 0.05,
            'loss_limit': 0.97,
            'stop_loss': 0.95,
        },
        'fingerprint': 'v172_short15_2019_2024',
    })
    
    # ── 4. 三马105七星17-原版组合(50%小市值+50%ETF轮动) ──
    strategies.append({
        'name': '三马105七星17-原版组合(50%小市值+50%ETF轮动)',
        'type': '混合策略',
        'signal_func': 'combined',
        'etf_signal_kwargs': {
            'lookback_days': 25,
            'enable_volume_check': False,
            'use_short_momentum_filter': True,
            'short_lookback_days': 10,
            'short_momentum_threshold': 0.0,
            'enable_profit_protection': True,
            'profit_protection_threshold': 0.05,
            'loss_limit': 0.97,
            'stop_loss': 0.95,
        },
        'fingerprint': 'sanma105_combo_2019_2024',
    })
    
    # ── 5. 七星高照6+1 ──
    strategies.append({
        'name': '七星高照6+1',
        'type': '七星高照6+1',
        'signal_func': 'qixing_61',
        'etf_pool': QIXING_61_POOL,
        'safe_assets': QIXING_61_SAFE,
        'fingerprint': 'qixing61_2019_2024',
    })
    
    # ── 内置策略：使用A股ETF映射 ──
    cn_risk = [CN_ETF_MAP['SPY'], CN_ETF_MAP['VEA']]
    cn_safe = [CN_ETF_MAP['AGG'], CN_ETF_MAP['SHY']]
    
    # ── 6. SPY/GLD/SHY轮动_6M ──
    strategies.append({
        'name': 'SPY/GLD/SHY轮动_6M',
        'type': '内置轮动',
        'signal_func': 'builtin_rotation',
        'risk_assets': [CN_ETF_MAP['SPY'], CN_ETF_MAP['GLD']],
        'safe_assets': [CN_ETF_MAP['SHY']],
        'lookback_months': 6,
        'buffer_days': 3,
        'abs_momentum_threshold': 0,
        'mapped': '沪深300ETF/黄金ETF/银华日利',
        'fingerprint': 'spy_gld_shy_6m_2019_2024',
    })
    
    # ── 7. 全天候_3M+7d缓冲 ──
    strategies.append({
        'name': '全天候_3M+7d缓冲',
        'type': '内置轮动',
        'signal_func': 'builtin_rotation',
        'risk_assets': cn_risk + [CN_ETF_MAP['GLD'], CN_ETF_MAP['TLT']],
        'safe_assets': cn_safe,
        'lookback_months': 3,
        'buffer_days': 7,
        'abs_momentum_threshold': 0,
        'mapped': '沪深300/中证500/黄金/十年国债 + 国债/货币(安全)',
        'fingerprint': 'allweather_3m7d_2019_2024',
    })
    
    # ── 8. 双重动量_9M_阈值2%+3d缓冲 ──
    strategies.append({
        'name': '双重动量_9M_阈值2%+3d缓冲',
        'type': '内置轮动',
        'signal_func': 'builtin_rotation',
        'risk_assets': cn_risk + [CN_ETF_MAP['GLD']],
        'safe_assets': cn_safe,
        'lookback_months': 9,
        'buffer_days': 3,
        'abs_momentum_threshold': 0.02,
        'mapped': '沪深300/中证500/黄金 + 国债/货币(安全)',
        'fingerprint': 'dual_9m_2pct_2019_2024',
    })
    
    # ── 9. GEM4资产_9M+3d缓冲 ──
    strategies.append({
        'name': 'GEM4资产_9M+3d缓冲',
        'type': '内置轮动',
        'signal_func': 'builtin_rotation',
        'risk_assets': cn_risk,
        'safe_assets': cn_safe,
        'lookback_months': 9,
        'buffer_days': 3,
        'abs_momentum_threshold': 0,
        'mapped': '沪深300/中证500 + 国债/货币(安全)',
        'fingerprint': 'gem4_9m3d_2019_2024',
    })
    
    # ── 10. 双市场自适应_6M+3d缓冲 ──
    strategies.append({
        'name': '双市场自适应_6M+3d缓冲',
        'type': '内置轮动',
        'signal_func': 'builtin_rotation',
        'risk_assets': cn_risk + [CN_ETF_MAP['GLD'], CN_ETF_MAP['TLT']],
        'safe_assets': cn_safe,
        'lookback_months': 6,
        'buffer_days': 3,
        'abs_momentum_threshold': 0,
        'mapped': '沪深300/中证500/黄金/十年国债 + 国债/货币(安全)',
        'fingerprint': 'dual_mkt_6m3d_2019_2024',
    })
    
    return strategies


# ================================================================
# 主流程
# ================================================================
if __name__ == '__main__':
    print("=" * 90)
    print("  🇨🇳 A股排行榜策略统一回测 v3")
    print(f"  📅 主区间: {MAIN_START} ~ {MAIN_END}")
    print(f"  💪 压力测试: {STRESS_START} ~ {STRESS_END}")
    print(f"  🔧 引擎: qixing_v172_strategy + vectorized_backtest")
    print("=" * 90)
    
    strategies = get_all_strategies()
    all_results = []
    
    # ── 加载全量ETF数据 ──
    pool_38 = list(CN_ETF_POOL_FULL.keys())
    pool_61 = QIXING_61_POOL
    builtin_pool = list(set(CN_ETF_MAP.values()))
    all_codes = list(dict.fromkeys(pool_38 + pool_61 + builtin_pool + [DEFENSIVE_ETF]))
    
    print(f"\n📂 加载A股ETF数据（{len(all_codes)}只）...")
    raw_data = load_etf_data(all_codes)
    print(f"  ✅ 成功加载 {len(raw_data)} 只ETF")
    missing = [c for c in all_codes if c not in raw_data]
    if missing:
        print(f"  ⚠️ 缺失: {missing}")
    
    close_df, high_df, vol_df = build_price_matrices(raw_data)
    print(f"  📊 数据范围: {close_df.index[0].strftime('%Y-%m-%d')} ~ {close_df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  📊 总交易日: {len(close_df)}, ETF数: {len(close_df.columns)}")
    
    # 加载个股数据（用于三马105原版组合）
    has_combined = any(s['signal_func'] == 'combined' for s in strategies)
    stock_data = {}
    if has_combined:
        print(f"\n📂 加载A股个股数据（用于三马105原版组合）...")
        stock_data = load_stock_data(max_stocks=3000)
        print(f"  ✅ 成功加载 {len(stock_data)} 只个股")
    
    # 逐策略回测
    for idx, strategy in enumerate(strategies):
        print(f"\n{'='*90}")
        print(f"  📊 [{idx+1}/{len(strategies)}] {strategy['name']}")
        print(f"  类型: {strategy['type']}")
        if strategy.get('mapped'):
            print(f"  A股映射: {strategy['mapped']}")
        print(f"{'='*90}")
        
        t0 = time.time()
        
        # ── 生成信号 ──
        print("  🔄 生成策略信号...")
        
        etf_signal_result = None
        
        if strategy['signal_func'] in ('qixing_v172', 'combined'):
            # V1.7.2策略
            pool_valid = [a for a in pool_38 if a in close_df.columns]
            safe_valid = [DEFENSIVE_ETF] if DEFENSIVE_ETF in close_df.columns else []
            defensive = safe_valid[0] if safe_valid else pool_valid[-1]
            
            cp = close_df.loc['2015-01-01':]
            hp = high_df.loc['2015-01-01':] if not high_df.empty else None
            vp = vol_df.loc['2015-01-01':] if not vol_df.empty else None
            
            signal_kwargs = strategy.get('signal_kwargs', strategy.get('etf_signal_kwargs', {}))
            etf_signal_result = qixing_v172_strategy(
                close_prices=cp,
                high_prices=hp,
                volume_data=vp,
                etf_pool=pool_valid,
                defensive_etf=defensive,
                **signal_kwargs
            )
            
            if strategy['signal_func'] == 'qixing_v172':
                signal_result = etf_signal_result
            else:
                signal_result = etf_signal_result  # combined也用ETF信号作为ETF部分
        
        elif strategy['signal_func'] == 'qixing_61':
            etf_pool = [a for a in strategy['etf_pool'] if a in close_df.columns]
            safe_assets = [a for a in strategy['safe_assets'] if a in close_df.columns]
            defensive = safe_assets[0] if safe_assets else etf_pool[-1]
            
            cp = close_df.loc['2015-01-01':]
            signal_result = qixing_61_signal(
                close_prices=cp,
                etf_pool=etf_pool,
                safe_assets=safe_assets,
                defensive_etf=defensive,
            )
        
        elif strategy['signal_func'] == 'builtin_rotation':
            risk_assets = [a for a in strategy['risk_assets'] if a in close_df.columns]
            safe_assets = [a for a in strategy['safe_assets'] if a in close_df.columns]
            defensive = safe_assets[0] if safe_assets else risk_assets[0]
            
            cp = close_df.loc['2015-01-01':]
            signal_result = builtin_rotation_signal(
                close_prices=cp,
                risk_assets=risk_assets,
                safe_assets=safe_assets,
                lookback_months=strategy['lookback_months'],
                buffer_days=strategy.get('buffer_days', 3),
                abs_momentum_threshold=strategy.get('abs_momentum_threshold', 0),
                defensive_etf=defensive,
            )
        
        signal_time = time.time() - t0
        print(f"  ✅ 信号生成完成 ({signal_time:.1f}s)")
        
        # ── 主回测 ──
        main_result = None
        stress_annual = 0
        stress_dd = 0
        
        if strategy['signal_func'] == 'combined':
            # 50%小市值+50%ETF轮动组合
            print(f"  📊 主回测 — 组合策略(50%小市值+50%ETF轮动) ({MAIN_START} ~ {MAIN_END})...")
            
            stock_close_df = pd.DataFrame(
                {code: df['Close'] for code, df in stock_data.items()}
            ).sort_index().ffill().bfill() if stock_data else pd.DataFrame()
            
            try:
                main_result = run_combined_backtest(
                    etf_signal_result, stock_close_df, close_df, DEFENSIVE_ETF,
                    MAIN_START, MAIN_END
                )
            except Exception as e:
                print(f"    ❌ 组合回测异常: {e}")
                continue
            
            if main_result is None:
                print("  ❌ 组合回测失败")
                continue
            
            m = main_result
            print(f"    年化收益: {m.get('annual_return', 0):+.2f}%")
            print(f"    夏普比率: {m.get('sharpe', 0):.2f}")
            print(f"    最大回撤: {m.get('max_drawdown', 0):.2f}%")
            print(f"    胜率: {m.get('win_rate', 0):.1f}%")
            print(f"    盈亏比: {m.get('profit_factor', 0):.2f}")
            
            # 压力测试
            print(f"  💪 压力测试 ({STRESS_START} ~ {STRESS_END})...")
            try:
                stress_result = run_combined_backtest(
                    etf_signal_result, stock_close_df, close_df, DEFENSIVE_ETF,
                    STRESS_START, STRESS_END
                )
                if stress_result:
                    stress_annual = stress_result.get('annual_return', 0)
                    stress_dd = stress_result.get('max_drawdown', 0)
                    print(f"    年化收益: {stress_annual:+.2f}%")
                    print(f"    最大回撤: {stress_dd:.2f}%")
                else:
                    print("    ⚠️ 压力测试无结果")
            except Exception as e:
                print(f"    ⚠️ 压力测试异常: {e}")
            
            # 适配评分接口
            main_result = {
                'annual_return': m.get('annual_return', 0),
                'sharpe': m.get('sharpe', 0),
                'max_drawdown': m.get('max_drawdown', 0),
                'win_rate': m.get('win_rate', 0),
                'profit_factor': m.get('profit_factor', 0),
                'avg_trades_per_year': m.get('avg_trades_per_year', 0),
                'monthly_positive_rate': m.get('monthly_positive_rate', 0),
                'yearly_returns': m.get('yearly_returns', {}),
                'holding_distribution': m.get('holding_distribution', {}),
            }
        
        else:
            # 标准ETF轮动回测
            print(f"  📊 主回测 ({MAIN_START} ~ {MAIN_END})...")
            main_result = run_strategy_backtest(strategy['name'], signal_result, close_df, MAIN_START, MAIN_END)
            
            if main_result is None:
                print("  ❌ 主回测失败")
                continue
            
            print(f"    年化收益: {main_result['annual_return']:+.2f}%")
            print(f"    夏普比率: {main_result['sharpe']:.2f}")
            print(f"    最大回撤: {main_result['max_drawdown']:.2f}%")
            print(f"    胜率: {main_result['win_rate']:.1f}%")
            print(f"    盈亏比: {main_result['profit_factor']:.2f}")
            print(f"    年交易: {main_result['avg_trades_per_year']:.1f}次")
            print(f"    月度正收益: {main_result['monthly_positive_rate']:.1%}")
            if main_result.get('holding_distribution'):
                top3 = list(main_result['holding_distribution'].items())[:3]
                print(f"    持仓TOP3: {top3}")
            if main_result.get('yearly_returns'):
                yr_str = " | ".join([f"{y}年:{ret:+.1f}%" for y, ret in sorted(main_result['yearly_returns'].items())])
                print(f"    年度收益: {yr_str}")
            
            # 压力测试
            print(f"  💪 压力测试 ({STRESS_START} ~ {STRESS_END})...")
            stress_result = run_strategy_backtest(strategy['name'], signal_result, close_df, STRESS_START, STRESS_END)
            
            if stress_result:
                print(f"    年化收益: {stress_result['annual_return']:+.2f}%")
                print(f"    最大回撤: {stress_result['max_drawdown']:.2f}%")
                stress_annual = stress_result['annual_return']
                stress_dd = stress_result['max_drawdown']
            else:
                print("    ⚠️ 压力测试数据不足")
        
        # ── 统一评分 ──
        stress_passed = stress_annual > 0
        score_result = compute_total_score(
            annual_return=main_result['annual_return'],
            sharpe=main_result['sharpe'],
            max_drawdown=main_result['max_drawdown'],
            profit_factor=main_result['profit_factor'],
            win_rate=main_result['win_rate'],
            cross_period_robust=stress_passed,
            survivorship_bias=True,
            monthly_positive_rate=main_result.get('monthly_positive_rate', 0),
        )
        
        # ── 评分输出 ──
        print(f"\n  📊 v4评分: {score_result['total_score']:.2f}分 [{score_result['grade']}]")
        print(f"    年化得分: {score_result['annual_return_score']:.2f} / 夏普得分: {score_result['sharpe_score']:.2f}")
        print(f"    回撤得分: {score_result['max_drawdown_score']:.2f} / 盈亏比得分: {score_result['profit_factor_score']:.2f}")
        print(f"    胜率得分: {score_result['win_rate_score']:.2f}")
        print(f"    跨周期鲁棒: {'✅ +5分' if stress_passed else '❌ 0分'}")
        print(f"    月度稳定性: +{score_result['monthly_stability_bonus']:.0f}分 / 幸存者偏差: {score_result['survivorship_penalty']:.0f}分")
        
        result_entry = {
            'rank': idx + 1,
            'strategy_name': strategy['name'],
            'strategy_type': strategy['type'],
            'fingerprint': strategy.get('fingerprint', ''),
            'main_period': {
                'annual_return': main_result['annual_return'],
                'sharpe': main_result['sharpe'],
                'max_drawdown': main_result['max_drawdown'],
                'win_rate': main_result['win_rate'],
                'profit_factor': main_result['profit_factor'],
                'avg_trades_per_year': main_result.get('avg_trades_per_year', 0),
                'monthly_positive_rate': main_result.get('monthly_positive_rate', 0),
                'yearly_returns': main_result.get('yearly_returns', {}),
                'holding_distribution': main_result.get('holding_distribution', {}),
            },
            'stress_test': {
                'annual_return': stress_annual,
                'max_drawdown': stress_dd,
                'passed': stress_passed,
            },
            'score': score_result,
        }
        all_results.append(result_entry)
    
    # ================================================================
    # 汇总输出
    # ================================================================
    print(f"\n\n{'='*110}")
    print(f"  🇨🇳 A股排行榜策略统一回测汇总 v3")
    print(f"  主区间: {MAIN_START} ~ {MAIN_END}  |  压力测试: {STRESS_START} ~ {STRESS_END}")
    print(f"{'='*110}")
    
    all_results.sort(key=lambda x: x['score']['total_score'], reverse=True)
    
    print(f"\n{'排名':>4} {'等级':>4} {'策略名称':<42} {'评分':>6} {'年化%':>8} {'夏普':>6} {'回撤%':>7} {'胜率%':>6} {'盈亏比':>6} {'月正率':>6} {'压力年化%':>9} {'鲁棒':>4}")
    print("-" * 115)
    
    for i, r in enumerate(all_results):
        m = r['main_period']
        s = r['stress_test']
        sc = r['score']
        robust_tag = '✅' if s['passed'] else '❌'
        print(f"{i+1:>4} {sc['grade']:>4} {r['strategy_name']:<42} {sc['total_score']:>6.1f} "
              f"{m['annual_return']:>+8.1f} {m['sharpe']:>6.2f} {m['max_drawdown']:>7.1f} "
              f"{m['win_rate']:>6.1f} {m['profit_factor']:>6.2f} {m['monthly_positive_rate']:>6.1%} "
              f"{s['annual_return']:>+9.1f} {robust_tag:>4}")
    
    # 年度收益分解
    print(f"\n{'='*110}")
    print(f"  📊 年度收益分解")
    print(f"{'='*110}")
    for r in all_results:
        yr = r['main_period'].get('yearly_returns', {})
        if yr:
            yr_str = " | ".join([f"{y}年:{ret:+.1f}%" for y, ret in sorted(yr.items())])
            print(f"  {r['strategy_name']:<42} {yr_str}")
    
    # 保存结果
    output_path = '/data/workspace/strategy_arena/cn_leaderboard_backtest_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 结果已保存至: {output_path}")
    
    print(f"\n✅ 全部回测完成！")
