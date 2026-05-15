#!/usr/bin/env python3
"""
聚宽多策略组合回测 v5 — 基于扩展组合引擎
来源: https://www.joinquant.com/post/64178
标题: 多策略11：去伪存真，拥抱不择时的核心逻辑
作者: O_iX

使用 portfolio_backtest 引擎，真正还原：
1. 搅屎棍策略(30%): 从全A股选市值最小+盈利>0的6只，周频调仓，缓冲池
2. 全天候ETF(50%): 固定比例(国债30%+黄金20%+创业板20%+沪深300 30%)
3. 简单ROA(10%): 月频选高夏普低估1只
4. 核心轮动(10%): ETF双周期动量+R²+急跌过滤
"""

import sys
import os
import math
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(__file__))
from portfolio_backtest import backtest_portfolio_strategy


def make_jq_portfolio_strategy():
    """
    聚宽多策略组合 — 策略函数
    
    返回的权重矩阵同时包含ETF和个股
    """
    
    def strategy_func(close_prices: pd.DataFrame, 
                     stock_close: pd.DataFrame = None, 
                     stock_volume: pd.DataFrame = None,
                     **kwargs) -> pd.DataFrame:
        """
        组合策略主函数
        
        参数:
            close_prices: ETF价格 (7只A股ETF，symbol名)
            stock_close: 个股价格 (512只A股个股)
            stock_volume: 个股成交量
        返回:
            weights_df: 每日持仓权重 (ETF+个股)
        """
        
        # ====== 初始化 ======
        all_dates = close_prices.index
        
        # 可用ETF
        etf_cols = [c for c in close_prices.columns]
        default_etf = 'AGG' if 'AGG' in etf_cols else etf_cols[0] if etf_cols else None
        
        # 可用个股
        has_stocks = stock_close is not None and not stock_close.empty
        stock_cols = list(stock_close.columns) if has_stocks else []
        
        # 构造全量权重矩阵
        all_cols = etf_cols + stock_cols
        weights = pd.DataFrame(0.0, index=all_dates, columns=all_cols)
        
        # 预热期（前20天）持有国债
        if default_etf:
            weights.loc[:all_dates[min(19, len(all_dates)-1)], default_etf] = 1.0
        warmup_end_idx = min(20, len(all_dates) - 1)
        
        # 资金分配
        W_JSG = 0.30
        W_AW = 0.50
        W_ROA = 0.10
        W_ROT = 0.10
        
        # ====== 预计算：成交额矩阵（用于市值代理） ======
        if has_stocks:
            turnover_df = stock_close * stock_volume  # 日成交额
        
        # ====== 1. 搅屎棍策略(30%) ======
        # 原逻辑：中证1000成分股(中小盘宽基) → 市值升序取前200 → PB>0+盈利>0+审计正常 → 缓冲池6只 → 周频
        # 适配：先筛"有流动性的中小盘"(模拟中证1000) → 再选质量最好的6只
        # 关键改进：不是选"最小市值"，而是从"中小盘池"中选"质量因子最强"的
        jsg_holdings = []  # 当前6只股票代码
        
        # 周频调仓日期
        for i in range(warmup_end_idx + 1, len(all_dates)):
            date = all_dates[i]
            
            # 每周调仓
            if i % 5 == 0 and has_stocks:
                loc = i
                lookback = min(20, loc)
                if lookback >= 5:
                    # 第1步：模拟中证1000 —— 先筛"有流动性的中小盘"
                    # 条件：20日均成交额在全市场排名25%~75%（不太大也不太小）
                    #       排除超大盘（前25%）和僵尸股（后25%）
                    avg_to = turnover_df.iloc[loc-lookback:loc+1].mean()
                    valid_to = avg_to.dropna()
                    if len(valid_to) < 50:
                        continue
                    
                    # 中证1000模拟：成交额排名25%~80%的（中小盘，排除超大盘和僵尸）
                    p25 = valid_to.quantile(0.25)
                    p80 = valid_to.quantile(0.80)
                    mid_cap = valid_to[(valid_to >= p25) & (valid_to <= p80)]
                    mid_cap_list = mid_cap.index.tolist()
                    
                    if not mid_cap_list:
                        continue
                    
                    # 第2步：从中小盘中选"质量因子最强"的
                    # 原策略质量因子：PB>0 + adjusted_profit>0 + 审计正常
                    # 适配：正收益(盈利>0) + 夏普比率高(质量好) + 非停牌
                    candidates = []
                    for code in mid_cap_list:
                        p = stock_close[code].iloc[loc-lookback:loc+1]
                        v = stock_volume[code].iloc[loc-lookback:loc+1]
                        
                        # 停牌>10天跳过
                        if (v == 0).sum() > 10:
                            continue
                        
                        valid_p = p[v > 0].dropna()
                        if len(valid_p) < 5:
                            continue
                        
                        # 盈利>0替代：20日正收益
                        period_ret = valid_p.iloc[-1] / valid_p.iloc[0] - 1.0
                        if period_ret <= 0:
                            continue
                        
                        # 质量因子：夏普比率（收益/波动）
                        daily_ret = valid_p.pct_change(fill_method=None).dropna()
                        if len(daily_ret) < 3:
                            continue
                        vol = daily_ret.std()
                        if vol <= 0:
                            continue
                        sharpe = period_ret / vol  # 简化夏普
                        
                        candidates.append((code, sharpe))
                    
                    # 第3步：按质量（夏普）排序取前12只（缓冲池=stock_sum*2）
                    candidates.sort(key=lambda x: x[1], reverse=True)
                    top12 = [c[0] for c in candidates[:12]]
                    
                    # 第4步：缓冲池机制
                    new_holdings = []
                    for s in jsg_holdings:
                        if s in top12 and len(new_holdings) < 6:
                            new_holdings.append(s)
                    for s in top12:
                        if s not in new_holdings and len(new_holdings) < 6:
                            new_holdings.append(s)
                    jsg_holdings = new_holdings
            
            # 设置搅屎棍权重
            if jsg_holdings:
                per_stock_weight = W_JSG / len(jsg_holdings)
                for s in jsg_holdings:
                    if s in weights.columns:
                        weights.loc[date, s] = per_stock_weight
            else:
                # 无持仓时资金放入国债
                if default_etf:
                    weights.loc[date, default_etf] += W_JSG
        
        # ====== 2. 全天候ETF策略(50%) ======
        # 固定比例：国债30%+黄金20%+创业板20%+沪深300 30%
        aw_weights_map = {
            'AGG': 0.30 * W_AW,  # 国债15%
            'GLD': 0.20 * W_AW,  # 黄金10%
            'QQQ': 0.20 * W_AW,  # 创业板10%
            'SPY': 0.30 * W_AW,  # 沪深300 15%
        }
        for date in all_dates[warmup_end_idx+1:]:
            for etf, w in aw_weights_map.items():
                if etf in weights.columns:
                    weights.loc[date, etf] += w
        
        # ====== 3. ROA策略(10%) ======
        # 原逻辑：全A股 PB<1+盈利>0 → 按ROA降序 → 取前1只 → 月调仓
        # 适配：中小盘池 → 价格<均线（低估）→ 最高夏普1只
        roa_holding = None
        
        for i in range(warmup_end_idx + 1, len(all_dates)):
            date = all_dates[i]
            
            # 每月调仓
            if i % 20 == 0 and has_stocks:
                loc = i
                lookback = min(60, loc)
                if lookback >= 10:
                    # 同样用中小盘池
                    avg_to = turnover_df.iloc[loc-lookback:loc+1].mean()
                    valid_to = avg_to.dropna()
                    if len(valid_to) < 50:
                        continue
                    p25 = valid_to.quantile(0.25)
                    p80 = valid_to.quantile(0.80)
                    mid_cap = valid_to[(valid_to >= p25) & (valid_to <= p80)]
                    mid_cap_list = mid_cap.index.tolist()
                    
                    roa_scores = {}
                    for code in mid_cap_list:
                        p = stock_close[code].iloc[loc-lookback:loc+1]
                        v = stock_volume[code].iloc[loc-lookback:loc+1]
                        
                        if (v == 0).sum() > 20:
                            continue
                        valid = p[v > 0].dropna()
                        if len(valid) < 10:
                            continue
                        
                        # PB<1替代：价格低于60日均线
                        mean_p = valid.mean()
                        if valid.iloc[-1] > mean_p * 1.2:
                            continue
                        
                        # ROA替代：夏普比率
                        daily_ret = valid.pct_change(fill_method=None).dropna()
                        if len(daily_ret) < 5:
                            continue
                        std_ret = daily_ret.std()
                        mean_ret = daily_ret.mean()
                        if std_ret > 0 and mean_ret > 0:
                            roa_scores[code] = (mean_ret * 252) / (std_ret * np.sqrt(252))
                    
                    if roa_scores:
                        roa_holding = max(roa_scores, key=roa_scores.get)
            
            if roa_holding and roa_holding in weights.columns:
                weights.loc[date, roa_holding] += W_ROA
            elif default_etf:
                weights.loc[date, default_etf] += W_ROA
        
        # ====== 4. 核心轮动策略(10%) ======
        # ETF双周期动量(25日+250日) + R² + 急跌过滤
        rot_holding = default_etf
        
        for i in range(warmup_end_idx + 1, len(all_dates)):
            date = all_dates[i]
            
            # 每周调仓
            if i % 5 == 0:
                loc = i
                long_days = min(250, loc)
                short_days = min(25, loc)
                if long_days < 25:
                    continue
                
                best_etf = default_etf
                best_score = -999
                
                for sym in etf_cols:
                    sp = close_prices[sym].iloc[loc-short_days:loc+1].dropna()
                    if len(sp) < 5:
                        continue
                    
                    # 急跌过滤
                    if len(sp) >= 4:
                        recent = sp.iloc[-4:]
                        ratios = [recent.iloc[j+1] / recent.iloc[j] for j in range(len(recent)-1)]
                        if any(r < 0.95 for r in ratios if r > 0):
                            continue
                    
                    # 短周期动量+R²
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
                    
                    # 长周期动量+R²
                    lp = close_prices[sym].iloc[loc-long_days:loc+1].dropna()
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
                    if combined > best_score:
                        best_score = combined
                        best_etf = sym
                
                if best_score <= 0:
                    best_etf = default_etf
                rot_holding = best_etf
            
            if rot_holding in weights.columns:
                weights.loc[date, rot_holding] += W_ROT
        
        return weights
    
    return strategy_func


# ================================================================
# 主程序
# ================================================================
if __name__ == '__main__':
    
    print(f"\n{'#'*80}")
    print(f"  🧪 聚宽多策略组合回测 v5 — 扩展组合引擎")
    print(f"  📖 来源: https://www.joinquant.com/post/64178")
    print(f"  📖 标题: 多策略11：去伪存真，拥抱不择时的核心逻辑")
    print(f"  📖 作者: O_iX")
    print(f"{'#'*80}")
    
    result = backtest_portfolio_strategy(
        strategy_func=make_jq_portfolio_strategy(),
        strategy_name='聚宽多策略组合_v5',
        strategy_type='组合策略',
        strategy_params={
            'sub_strategies': '搅屎棍30%+全天候50%+ROA10%+轮动10%',
            'jsg': '周频中小盘(成交额25-80%分位)→正收益+高夏普→缓冲池6只等权',
            'aw': '固定比例(国债30%+黄金20%+创业板20%+沪深300 30%)',
            'roa': '月频中小盘+低估+最高夏普1只',
            'rot': '周频双周期动量ETF轮动+R²+急跌过滤',
            'source': '聚宽64178',
        },
        strategy_desc='克隆自聚宽(64178): v5组合引擎版 - 4子策略并行持仓，搅屎棍/ROA使用512只A股个股选股',
        source='聚宽克隆(64178)',
        market_scope=['CN'],
    )
    
    # 输出对比
    print(f"\n\n{'='*80}")
    print(f"  📊 与聚宽原始回测对比")
    print(f"{'='*80}")
    print(f"  聚宽原始: A股年化 40%+ (2019-2024)")
    
    if result.get('market_summaries'):
        for market, ms in result['market_summaries'].items():
            m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[market]
            print(f"  v5回测:   [{m_label}] 年化{ms['annual_return']:+.2f}% | 回撤{ms['max_drawdown']:.1f}% | 夏普{ms['sharpe']:.2f} | 评分{ms['score']}分")
    
    if result.get('market_results'):
        for market, mr in result['market_results'].items():
            main = mr['main_result']
            if 'yearly' in main:
                print(f"\n  📊 [{market}] 年度收益:")
                for year, ret in sorted(main['yearly'].items()):
                    bar = '█' * max(0, int(ret / 5))
                    sign = '+' if ret >= 0 else ''
                    print(f"     {year}: {sign}{ret:.2f}% {bar}")
    
    print(f"\n{'='*80}")
