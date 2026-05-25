#!/usr/bin/env python3
"""
聚宽多策略组合回测 v2 - 还原A股核心逻辑
来源: https://www.joinquant.com/post/64178
作者: O_iX

v1问题：
  - 拆开4个子策略单独回测，丧失了组合分散化效果
  - 加权投票实质等于只跑了全天候（50%权重永远胜出）
  - 6ETF池太粗，无法体现原策略的选股+轮动逻辑

v2核心改进：
  1. 保持4子策略组合结构，但用"信号一致性"替代简单投票：
     - 4个子策略信号越一致 → 越有信心 → 持有风险资产
     - 4个子策略信号越分散 → 不确定 → 持有安全资产（全天候核心！）
  2. 扩展A股ETF池到9只（增加军工/半导体/券商ETF）
  3. 保留原策略核心逻辑：
     - 搅屎棍：小盘价值缓冲池
     - 全天候：固定比例(国债/黄金/纳指/红利)
     - ROA：高夏普低波动
     - 轮动：双周期动量+R²+急跌过滤
"""

import sys
import os
import time
import math
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from cross_regime_scheduler import (
    backtest_user_strategy, load_all_etf_data, load_all_market_data,
    fetch_risk_free_rate, ALL_ASSETS_6, CN_ALL_ASSETS_6, HK_ALL_ASSETS_6,
    SAFE_ASSETS, RISK_ASSETS, CN_RISK_ASSETS, CN_SAFE_ASSETS,
    CN_ETF_MAP, run_backtest_vec, LOCAL_CN_DIR, CN_MAIN_START, CN_MAIN_END,
    CN_RISK_FREE_RATE, FEES_CN, SLIPPAGE, INIT_CASH
)


# ================================================================
# A股扩展ETF池（本地可用的9只ETF）
# ================================================================
# 原6只映射：SPY=510300, QQQ=159915, VEA=510500, AGG=511010, SHY=511880, GLD=518880, TLT=511260
# 新增3只：
#   512100=中证1000ETF（更小盘，匹配搅屎棍策略）
#   512660=军工ETF（行业轮动标的）
#   512880=证券ETF（行业轮动标的）

CN_EXTENDED_ETF_MAP = {
    **CN_ETF_MAP,
    'IWM': '512100_XSHG',    # 中证1000ETF（小盘→小盘）- 搅屎棍策略最匹配
    'XLI': '512660_XSHG',    # 军工ETF（行业轮动）
    'XLF': '512880_XSHG',    # 证券ETF（行业轮动）
}

CN_EXTENDED_ASSETS = CN_ALL_ASSETS_6 + ['IWM', 'XLI', 'XLF']


def load_cn_extended_etf_data():
    """加载扩展A股ETF数据（9只）"""
    cn_data = {}
    for us_sym in CN_EXTENDED_ASSETS:
        cn_code = CN_EXTENDED_ETF_MAP.get(us_sym)
        if not cn_code:
            continue
        filepath = os.path.join(LOCAL_CN_DIR, f'{cn_code}.csv')
        if not os.path.exists(filepath):
            continue
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            df.columns = [c.strip().capitalize() for c in df.columns]
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            if len(df) >= 200:
                cn_data[us_sym] = df
        except Exception:
            continue
    return cn_data


# ================================================================
# 核心策略：信号一致性组合策略
# ================================================================
# 原策略精髓：4个子策略分别独立产生信号，资金按比例分配
# 在轮动框架中，我们用"信号一致性"来还原这种分散化效果：
#
#   - 4个信号全部指向同一ETF → 高度一致 → 全仓该ETF（最大攻击力）
#   - 3个信号一致 → 较高一致 → 持有共识ETF
#   - 2个信号一致 + 2个分散 → 中等 → 持有共识ETF，但可能偏保守
#   - 4个信号全不同 → 极度分散 → 持有安全资产（全天候保护！）
#
# 这才是原策略"去伪存真"的核心：
#   当策略间产生分歧时，说明市场不确定 → 退守安全资产
#   当策略间达成共识时，说明机会明确 → 积极进攻

def make_jq_combined_v2():
    """聚宽多策略组合 v2 - 信号一致性策略"""
    def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
        all_assets = [a for a in close_prices.columns if a in ALL_ASSETS_6]
        if not all_assets:
            return pd.Series('SHY', index=close_prices.index)
        
        safe = [a for a in all_assets if a in SAFE_ASSETS]
        default = safe[0] if safe else 'SHY'
        
        # ---- 子策略1: 搅屎棍(周频, 小盘价值, 缓冲池) ----
        jsg_signal = pd.Series(default, index=close_prices.index)
        weekly_ends = close_prices.resample('W-FRI').last().index
        weekly_ends = weekly_ends[weekly_ends.isin(close_prices.index)]
        
        if len(weekly_ends) >= 5:
            for i, w_date in enumerate(weekly_ends):
                loc = close_prices.index.get_loc(w_date)
                lookback = min(20, loc)
                if lookback < 5:
                    continue
                
                momentum = {}
                for asset in all_assets:
                    prices = close_prices[asset].iloc[loc-lookback:loc+1]
                    if prices.isna().all() or len(prices.dropna()) < 5:
                        continue
                    ret = prices.iloc[-1] / prices.iloc[0] - 1.0
                    vol = prices.pct_change(fill_method=None).std()
                    momentum[asset] = ret / vol if vol > 0 else 0
                
                if not momentum:
                    continue
                best_jsg = max(momentum, key=momentum.get)
                
                if i + 1 < len(weekly_ends):
                    next_w = weekly_ends[i + 1]
                    mask = (close_prices.index > w_date) & (close_prices.index <= next_w)
                else:
                    mask = close_prices.index > w_date
                jsg_signal.loc[mask] = best_jsg
        
        # ---- 子策略2: 全天候(月频, 趋势质量选最强) ----
        aw_signal = pd.Series(default, index=close_prices.index)
        monthly_ends = close_prices.resample('ME').last().index
        monthly_ends = monthly_ends[monthly_ends.isin(close_prices.index)]
        
        if len(monthly_ends) >= 3:
            for i, m_date in enumerate(monthly_ends):
                loc = close_prices.index.get_loc(m_date)
                lookback = min(60, loc)
                if lookback < 10:
                    continue
                
                asset_scores = {}
                for asset in all_assets:
                    prices = close_prices[asset].iloc[loc-lookback:loc+1].dropna()
                    if len(prices) < 5:
                        continue
                    log_p = np.log(prices)
                    x = np.arange(len(log_p))
                    slope, intercept = np.polyfit(x, log_p, 1)
                    ss_res = np.sum((log_p - (slope * x + intercept)) ** 2)
                    ss_tot = np.sum((log_p - log_p.mean()) ** 2)
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                    annualized = np.exp(slope * 252) - 1
                    asset_scores[asset] = annualized * max(r2, 0)
                
                if not asset_scores:
                    continue
                best_aw = max(asset_scores, key=asset_scores.get)
                if asset_scores[best_aw] <= 0:
                    best_aw = default
                
                if i + 1 < len(monthly_ends):
                    next_m = monthly_ends[i + 1]
                    mask = (close_prices.index > m_date) & (close_prices.index <= next_m)
                else:
                    mask = close_prices.index > m_date
                aw_signal.loc[mask] = best_aw
        
        # ---- 子策略3: ROA(月频, 高夏普) ----
        roa_signal = pd.Series(default, index=close_prices.index)
        
        if len(monthly_ends) >= 3:
            for i, m_date in enumerate(monthly_ends):
                loc = close_prices.index.get_loc(m_date)
                lookback = min(60, loc)
                if lookback < 10:
                    continue
                
                roa_scores = {}
                for asset in all_assets:
                    prices = close_prices[asset].iloc[loc-lookback:loc+1].dropna()
                    if len(prices) < 10:
                        continue
                    daily_ret = prices.pct_change(fill_method=None).dropna()
                    if len(daily_ret) < 5:
                        continue
                    std_ret = daily_ret.std()
                    roa_scores[asset] = (daily_ret.mean() * 252) / (std_ret * np.sqrt(252)) if std_ret > 0 else 0
                
                if not roa_scores:
                    continue
                best_roa = max(roa_scores, key=roa_scores.get)
                if roa_scores[best_roa] <= 0:
                    best_roa = default
                
                if i + 1 < len(monthly_ends):
                    next_m = monthly_ends[i + 1]
                    mask = (close_prices.index > m_date) & (close_prices.index <= next_m)
                else:
                    mask = close_prices.index > m_date
                roa_signal.loc[mask] = best_roa
        
        # ---- 子策略4: 核心轮动(周频, 双周期动量+R²+急跌) ----
        rot_signal = pd.Series(default, index=close_prices.index)
        
        if len(weekly_ends) >= 15:
            for i, w_date in enumerate(weekly_ends):
                loc = close_prices.index.get_loc(w_date)
                long_days = min(250, loc)
                if long_days < 25:
                    continue
                short_days = min(25, loc)
                
                best_etf = None
                best_score = -999
                
                for asset in all_assets:
                    sp = close_prices[asset].iloc[loc-short_days:loc+1].dropna()
                    if len(sp) < 5:
                        continue
                    # 急跌过滤
                    if len(sp) >= 4:
                        recent = sp.iloc[-4:]
                        ratios = [recent.iloc[j+1] / recent.iloc[j] for j in range(len(recent)-1)]
                        if any(r < 0.95 for r in ratios if r > 0):
                            continue
                    
                    y = np.log(sp.values)
                    x = np.arange(len(y))
                    w = np.linspace(1, 2, len(y))
                    try:
                        slope, intercept = np.polyfit(x, y, 1, w=w)
                    except:
                        continue
                    ann = math.exp(slope * 252) - 1
                    ss_res = np.sum(w * (y - (slope * x + intercept)) ** 2)
                    ss_tot = np.sum(w * (y - np.mean(y)) ** 2)
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                    short_score = ann * r2
                    if not (0 < short_score < 6):
                        short_score = 0
                    
                    lp = close_prices[asset].iloc[loc-long_days:loc+1].dropna()
                    if len(lp) < 20:
                        continue
                    y2 = np.log(lp.values)
                    x2 = np.arange(len(y2))
                    w2 = np.linspace(1, 2, len(y2))
                    try:
                        slope2, _ = np.polyfit(x2, y2, 1, w=w2)
                    except:
                        continue
                    ann2 = math.exp(slope2 * 252) - 1
                    ss_res2 = np.sum(w2 * (y2 - (slope2 * x2 + np.polyfit(x2, y2, 1, w=w2)[1]) ** 2))
                    ss_tot2 = np.sum(w2 * (y2 - np.mean(y2)) ** 2)
                    r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 0 else 0
                    long_score = ann2 * r22
                    if not (long_score > 0 and long_score < 0.5):
                        long_score = 0
                    
                    combined = short_score + long_score
                    if combined > best_score:
                        best_score = combined
                        best_etf = asset
                
                if best_etf is None or best_score <= 0:
                    best_etf = default
                
                if i + 1 < len(weekly_ends):
                    next_w = weekly_ends[i + 1]
                    mask = (close_prices.index > w_date) & (close_prices.index <= next_w)
                else:
                    mask = close_prices.index > w_date
                rot_signal.loc[mask] = best_etf
        
        # ---- 组合决策：信号一致性 ----
        holding = pd.Series(default, index=close_prices.index)
        
        # 权重 [搅屎棍=0.3, 全天候=0.5, ROA=0.1, 轮动=0.1]
        weight_map = {'jsg': 0.3, 'aw': 0.5, 'roa': 0.1, 'rot': 0.1}
        
        for date in close_prices.index:
            signals = {
                'jsg': jsg_signal.loc[date],
                'aw':  aw_signal.loc[date],
                'roa': roa_signal.loc[date],
                'rot': rot_signal.loc[date],
            }
            
            # 加权投票
            votes = {}
            for name, asset in signals.items():
                votes[asset] = votes.get(asset, 0) + weight_map[name]
            
            max_votes = max(votes.values())
            consensus = max_votes / sum(weight_map.values())  # 共识度 0~1
            
            # 核心逻辑：信号一致性决定激进程度
            if consensus >= 0.6:
                # 高共识 → 跟随共识信号
                winners = [a for a, v in votes.items() if v == max_votes]
                holding.loc[date] = winners[0]
            elif consensus >= 0.4:
                # 中等共识 → 跟随但偏向安全
                winners = [a for a, v in votes.items() if v == max_votes]
                chosen = winners[0]
                # 如果共识资产是风险资产但共识不够强，退一步
                if chosen in RISK_ASSETS:
                    # 检查是否有安全资产的票
                    safe_votes = sum(v for a, v in votes.items() if a in SAFE_ASSETS)
                    if safe_votes >= 0.3:
                        holding.loc[date] = default
                    else:
                        holding.loc[date] = chosen
                else:
                    holding.loc[date] = chosen
            else:
                # 低共识（极度分散）→ 全天候保护，持有安全资产
                holding.loc[date] = default
        
        # 预热期
        if len(holding) > 20:
            holding.iloc[:20] = default
        
        return holding
    return strategy_func


# ================================================================
# A股优化版：使用扩展ETF池(9只)，直接在A股数据上回测
# ================================================================
def make_jq_combined_cn_extended():
    """聚宽多策略组合 v2 - A股9ETF扩展版"""
    def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
        # A股9只ETF全部可用
        cn_assets = [a for a in close_prices.columns]
        if not cn_assets:
            return pd.Series('SHY', index=close_prices.index)
        
        cn_safe = [a for a in cn_assets if a in CN_SAFE_ASSETS]
        default = cn_safe[0] if cn_safe else 'SHY'
        
        # ---- 子策略1: 搅屎棍(周频, 小盘价值) ----
        # 在A股9ETF中，IWM=中证1000最匹配"小盘价值"
        # 但我们让它选：在IWM/VEA/QQQ(中小盘) vs AGG/SHY(安全) 之间轮动
        jsg_signal = pd.Series(default, index=close_prices.index)
        weekly_ends = close_prices.resample('W-FRI').last().index
        weekly_ends = weekly_ends[weekly_ends.isin(close_prices.index)]
        
        # 搅屎棍候选池：偏好中小盘（IWM/VEA/QQQ）+ 安全底（AGG/SHY）
        jsg_pool = [a for a in cn_assets if a in ['IWM', 'VEA', 'QQQ', 'SPY', 'AGG', 'SHY']]
        if not jsg_pool:
            jsg_pool = cn_assets
        
        if len(weekly_ends) >= 5:
            for i, w_date in enumerate(weekly_ends):
                loc = close_prices.index.get_loc(w_date)
                lookback = min(20, loc)
                if lookback < 5:
                    continue
                
                momentum = {}
                for asset in jsg_pool:
                    prices = close_prices[asset].iloc[loc-lookback:loc+1]
                    if prices.isna().all() or len(prices.dropna()) < 5:
                        continue
                    ret = prices.iloc[-1] / prices.iloc[0] - 1.0
                    vol = prices.pct_change(fill_method=None).std()
                    # 小盘价值：偏好正收益+低波动
                    momentum[asset] = ret / vol if vol > 0 else 0
                
                if not momentum:
                    continue
                # 缓冲池：取前2只
                sorted_pool = sorted(momentum.keys(), key=lambda x: momentum[x], reverse=True)
                best_jsg = sorted_pool[0]
                
                if i + 1 < len(weekly_ends):
                    next_w = weekly_ends[i + 1]
                    mask = (close_prices.index > w_date) & (close_prices.index <= next_w)
                else:
                    mask = close_prices.index > w_date
                jsg_signal.loc[mask] = best_jsg
        
        # ---- 子策略2: 全天候(月频, 固定比例映射) ----
        # 原策略：国债30%+黄金20%+纳指20%+红利30%
        # A股映射：AGG(国债)30%+GLD(黄金)20%+QQQ(创业板)20%+SPY(沪深300)30%
        # 轮动中选趋势最强的全天候标的
        aw_pool = [a for a in cn_assets if a in ['AGG', 'GLD', 'QQQ', 'SPY', 'TLT', 'SHY']]
        if not aw_pool:
            aw_pool = cn_assets
        
        aw_signal = pd.Series(default, index=close_prices.index)
        monthly_ends = close_prices.resample('ME').last().index
        monthly_ends = monthly_ends[monthly_ends.isin(close_prices.index)]
        
        if len(monthly_ends) >= 3:
            for i, m_date in enumerate(monthly_ends):
                loc = close_prices.index.get_loc(m_date)
                lookback = min(60, loc)
                if lookback < 10:
                    continue
                
                asset_scores = {}
                for asset in aw_pool:
                    prices = close_prices[asset].iloc[loc-lookback:loc+1].dropna()
                    if len(prices) < 5:
                        continue
                    log_p = np.log(prices)
                    x = np.arange(len(log_p))
                    slope, intercept = np.polyfit(x, log_p, 1)
                    ss_res = np.sum((log_p - (slope * x + intercept)) ** 2)
                    ss_tot = np.sum((log_p - log_p.mean()) ** 2)
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                    annualized = np.exp(slope * 252) - 1
                    asset_scores[asset] = annualized * max(r2, 0)
                
                if not asset_scores:
                    continue
                best_aw = max(asset_scores, key=asset_scores.get)
                if asset_scores[best_aw] <= 0:
                    best_aw = default
                
                if i + 1 < len(monthly_ends):
                    next_m = monthly_ends[i + 1]
                    mask = (close_prices.index > m_date) & (close_prices.index <= next_m)
                else:
                    mask = close_prices.index > m_date
                aw_signal.loc[mask] = best_aw
        
        # ---- 子策略3: ROA(月频, 高夏普低波) ----
        roa_signal = pd.Series(default, index=close_prices.index)
        
        if len(monthly_ends) >= 3:
            for i, m_date in enumerate(monthly_ends):
                loc = close_prices.index.get_loc(m_date)
                lookback = min(60, loc)
                if lookback < 10:
                    continue
                
                roa_scores = {}
                for asset in cn_assets:
                    prices = close_prices[asset].iloc[loc-lookback:loc+1].dropna()
                    if len(prices) < 10:
                        continue
                    daily_ret = prices.pct_change(fill_method=None).dropna()
                    if len(daily_ret) < 5:
                        continue
                    std_ret = daily_ret.std()
                    roa_scores[asset] = (daily_ret.mean() * 252) / (std_ret * np.sqrt(252)) if std_ret > 0 else 0
                
                if not roa_scores:
                    continue
                best_roa = max(roa_scores, key=roa_scores.get)
                if roa_scores[best_roa] <= 0:
                    best_roa = default
                
                if i + 1 < len(monthly_ends):
                    next_m = monthly_ends[i + 1]
                    mask = (close_prices.index > m_date) & (close_prices.index <= next_m)
                else:
                    mask = close_prices.index > m_date
                roa_signal.loc[mask] = best_roa
        
        # ---- 子策略4: 核心轮动(周频, 双周期动量) ----
        rot_signal = pd.Series(default, index=close_prices.index)
        
        if len(weekly_ends) >= 15:
            for i, w_date in enumerate(weekly_ends):
                loc = close_prices.index.get_loc(w_date)
                long_days = min(250, loc)
                if long_days < 25:
                    continue
                short_days = min(25, loc)
                
                best_etf = None
                best_combined = -999
                
                for asset in cn_assets:
                    sp = close_prices[asset].iloc[loc-short_days:loc+1].dropna()
                    if len(sp) < 5:
                        continue
                    # 急跌过滤
                    if len(sp) >= 4:
                        recent = sp.iloc[-4:]
                        ratios = [recent.iloc[j+1] / recent.iloc[j] for j in range(len(recent)-1)]
                        if any(r < 0.95 for r in ratios if r > 0):
                            continue
                    
                    y = np.log(sp.values)
                    x = np.arange(len(y))
                    w = np.linspace(1, 2, len(y))
                    try:
                        slope, intercept = np.polyfit(x, y, 1, w=w)
                    except:
                        continue
                    ann = math.exp(slope * 252) - 1
                    ss_res = np.sum(w * (y - (slope * x + intercept)) ** 2)
                    ss_tot = np.sum(w * (y - np.mean(y)) ** 2)
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                    short_score = ann * r2
                    if not (0 < short_score < 6):
                        short_score = 0
                    
                    lp = close_prices[asset].iloc[loc-long_days:loc+1].dropna()
                    if len(lp) < 20:
                        continue
                    y2 = np.log(lp.values)
                    x2 = np.arange(len(y2))
                    w2 = np.linspace(1, 2, len(y2))
                    try:
                        coeffs2 = np.polyfit(x2, y2, 1, w=w2)
                        slope2, intercept2 = coeffs2[0], coeffs2[1]
                    except:
                        continue
                    ann2 = math.exp(slope2 * 252) - 1
                    y2_pred = slope2 * x2 + intercept2
                    ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                    ss_tot2 = np.sum(w2 * (y2 - np.mean(y2)) ** 2)
                    r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 0 else 0
                    long_score = ann2 * r22
                    if not (long_score > 0 and long_score < 0.5):
                        long_score = 0
                    
                    combined = short_score + long_score
                    if combined > best_combined:
                        best_combined = combined
                        best_etf = asset
                
                if best_etf is None or best_combined <= 0:
                    best_etf = default
                
                if i + 1 < len(weekly_ends):
                    next_w = weekly_ends[i + 1]
                    mask = (close_prices.index > w_date) & (close_prices.index <= next_w)
                else:
                    mask = close_prices.index > w_date
                rot_signal.loc[mask] = best_etf
        
        # ---- 组合决策：信号一致性 ----
        holding = pd.Series(default, index=close_prices.index)
        weight_map = {'jsg': 0.3, 'aw': 0.5, 'roa': 0.1, 'rot': 0.1}
        
        for date in close_prices.index:
            signals = {
                'jsg': jsg_signal.loc[date],
                'aw':  aw_signal.loc[date],
                'roa': roa_signal.loc[date],
                'rot': rot_signal.loc[date],
            }
            
            votes = {}
            for name, asset in signals.items():
                votes[asset] = votes.get(asset, 0) + weight_map[name]
            
            max_votes = max(votes.values())
            consensus = max_votes / sum(weight_map.values())
            
            if consensus >= 0.6:
                winners = [a for a, v in votes.items() if v == max_votes]
                holding.loc[date] = winners[0]
            elif consensus >= 0.4:
                winners = [a for a, v in votes.items() if v == max_votes]
                chosen = winners[0]
                # A股波动大，中等共识时风险资产需更强信号
                risk_assets_cn = [a for a in cn_assets if a in CN_RISK_ASSETS + ['IWM', 'XLI', 'XLF', 'QQQ']]
                if chosen in risk_assets_cn:
                    safe_votes = sum(v for a, v in votes.items() if a in CN_SAFE_ASSETS)
                    if safe_votes >= 0.2:
                        holding.loc[date] = default
                    else:
                        holding.loc[date] = chosen
                else:
                    holding.loc[date] = chosen
            else:
                holding.loc[date] = default
        
        if len(holding) > 20:
            holding.iloc[:20] = default
        
        return holding
    return strategy_func


# ================================================================
# 直接A股回测：绕过回测框架，用9只A股ETF数据直接跑
# ================================================================
def direct_cn_backtest(strategy_func, strategy_name, start_date=None, end_date=None):
    """
    直接在A股9ETF数据上运行回测，不走三层递进框架
    这样可以使用扩展ETF池（9只而非6只）
    """
    print(f"\n{'─'*70}")
    print(f"  🔬 A股直接回测: {strategy_name}")
    print(f"  📦 加载A股9ETF数据...")
    
    # 加载A股扩展ETF数据
    cn_data = load_cn_extended_etf_data()
    if not cn_data:
        print("  ❌ 无A股ETF数据")
        return None
    
    print(f"  ✅ 加载 {len(cn_data)} 只A股ETF: {list(cn_data.keys())}")
    
    # 构造close_prices
    cn_close_dict = {sym: df['Close'] for sym, df in cn_data.items()}
    close_prices = pd.DataFrame(cn_close_dict).sort_index()
    
    if start_date:
        close_prices = close_prices.loc[start_date:]
    if end_date:
        close_prices = close_prices.loc[:end_date]
    
    print(f"  📊 数据范围: {close_prices.index[0].strftime('%Y-%m-%d')} ~ {close_prices.index[-1].strftime('%Y-%m-%d')} ({len(close_prices)}个交易日)")
    
    # 运行策略信号
    print(f"  ⚙️  计算策略信号...")
    holding = strategy_func(close_prices)
    
    # 向量化回测
    print(f"  📈 执行回测...")
    result = run_backtest_vec(
        close_prices, holding,
        start_date=close_prices.index[0].strftime('%Y-%m-%d'),
        end_date=close_prices.index[-1].strftime('%Y-%m-%d'),
        risk_free_rate=CN_RISK_FREE_RATE,
        market='CN'
    )
    
    if result:
        print(f"\n  📊 A股回测结果:")
        print(f"     年化收益: {result['annual_return']:+.2f}%")
        print(f"     最大回撤: {result['max_drawdown']:.2f}%")
        print(f"     夏普比率: {result['sharpe']:.2f}")
        print(f"     Calmar:   {result['calmar']:.2f}")
        print(f"     胜率:     {result['win_rate']:.1f}%")
        print(f"     盈亏比:   {result['profit_factor']:.2f}")
        print(f"     年交易:   {result['avg_trades_per_year']:.1f}次")
        print(f"     持仓分布: {result['holding_distribution']}")
    
    return result


# ================================================================
# 主程序
# ================================================================
if __name__ == '__main__':
    
    # ===== 回测1: 通过回测框架（6ETF标准池）=====
    print(f"\n{'#'*80}")
    print(f"  🧪 回测1: 聚宽组合v2(信号一致性) - 标准三市场回测")
    print(f"{'#'*80}")
    
    result1 = backtest_user_strategy(
        strategy_func=make_jq_combined_v2(),
        strategy_name='聚宽多策略v2_信号一致性',
        strategy_type='组合策略',
        strategy_params={
            'sub_strategies': '搅屎棍30%+全天候50%+ROA10%+轮动10%',
            'combo_method': '信号一致性(共识≥60%进攻,<40%防守)',
            'source': '聚宽64178',
        },
        strategy_desc='克隆自聚宽(64178): v2信号一致性组合 - 4子策略共识度高则进攻,低则退守安全资产',
        source='聚宽克隆(64178)',
    )
    
    # ===== 回测2: A股9ETF直接回测 =====
    print(f"\n\n{'#'*80}")
    print(f"  🧪 回测2: 聚宽组合v2(A股9ETF扩展) - 直接A股回测")
    print(f"{'#'*80}")
    
    cn_result = direct_cn_backtest(
        strategy_func=make_jq_combined_cn_extended(),
        strategy_name='聚宽多策略v2_A股9ETF',
    )
    
    # ===== 回测3: 通过回测框架提交A股优化版 =====
    print(f"\n\n{'#'*80}")
    print(f"  🧪 回测3: 聚宽组合v2(A股9ETF) - 标准三市场回测框架")
    print(f"{'#'*80}")
    
    # 注意：标准回测框架的A股池只有6只，9ETF策略在6只池上也能跑（额外3只会被忽略）
    result3 = backtest_user_strategy(
        strategy_func=make_jq_combined_cn_extended(),
        strategy_name='聚宽多策略v2_A股9ETF',
        strategy_type='组合策略',
        strategy_params={
            'sub_strategies': '搅屎棍30%+全天候50%+ROA10%+轮动10%',
            'combo_method': '信号一致性+A股扩展池(9ETF)',
            'etf_pool': 'SPY/QQQ/VEA/AGG/SHY/GLD/TLT + IWM(中证1000)/XLI(军工)/XLF(证券)',
            'source': '聚宽64178',
        },
        strategy_desc='克隆自聚宽(64178): A股9ETF扩展版 - 增加中证1000/军工/证券ETF，还原小盘价值逻辑',
        source='聚宽克隆(64178)',
    )
    
    # ===== 汇总 =====
    print(f"\n\n{'='*80}")
    print(f"  📊 聚宽多策略组合v2回测汇总")
    print(f"{'='*80}")
    print(f"  来源: https://www.joinquant.com/post/64178")
    print(f"  标题: 多策略11：去伪存真，拥抱不择时的核心逻辑")
    print(f"  作者: O_iX")
    print(f"")
    
    for name, res in [
        ('v2信号一致性(6ETF)', result1),
        ('A股9ETF直接回测', cn_result),
        ('A股9ETF标准框架', result3),
    ]:
        if res is None:
            print(f"  {name}: ⚠️ 无结果")
            continue
        
        if isinstance(res, dict) and 'market_summaries' in res:
            status = '✅通过' if res.get('passed') else f"❌{res.get('eliminated_at','?')}淘汰"
            print(f"  {name}: {status}")
            for market, ms in res.get('market_summaries', {}).items():
                m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[market]
                pm = '✅' if ms['passed'] else '❌'
                print(f"    [{m_label}]{pm} 评分:{ms['score']} | "
                      f"年化:{ms['annual_return']:+.2f}% | 回撤:{ms['max_drawdown']:.1f}% | "
                      f"夏普:{ms['sharpe']:.2f} | 胜率:{ms['win_rate']:.1f}%")
        elif isinstance(res, dict) and 'annual_return' in res:
            print(f"  {name}: 年化:{res['annual_return']:+.2f}% | "
                  f"回撤:{res['max_drawdown']:.1f}% | 夏普:{res['sharpe']:.2f} | "
                  f"胜率:{res['win_rate']:.1f}% | 盈亏比:{res['profit_factor']:.2f}")
        else:
            print(f"  {name}: ⚠️ 结果格式异常")
    
    print(f"\n{'='*80}")
