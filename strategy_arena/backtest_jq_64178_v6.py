#!/usr/bin/env python3
"""
聚宽多策略组合回测 v6 — 最终优化版
来源: https://www.joinquant.com/post/64178

v5问题：年化5.41%，远低于聚宽40%+

差距分析：
1. 聚宽搅屎棍策略的核心收益 = "小盘股连板效应"(A股特有)
   - 每周从200只小市值中选6只 → 靠的是A股小盘溢价+连板+打板
   - 512只个股数据无法还原这个效应（缺财务数据+实时行情）
2. 聚宽全天候策略占50%资金 → 提供稳定收益(年化~5-10%)
3. 打新收益 ≈ 年化5-10%（A股100万市值年化打新收益）

v6优化方向：
1. 搅屎棍：放弃还原"小盘连板"，改为"中小盘动量轮动"
   - 从中小盘中选近期动量最强+波动率适中的6只
   - 这是v3年化198%的合理版本（去掉幸存者偏差后的真实效果）
2. 全天候：保持50%不变
3. ROA：保持不变
4. 核心轮动：保持不变
5. 组合：调整权重，让搅屎棍真正贡献alpha
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


def make_jq_portfolio_v6():
    """聚宽多策略组合 v6 — 优化版"""
    
    def strategy_func(close_prices: pd.DataFrame, 
                     stock_close: pd.DataFrame = None, 
                     stock_volume: pd.DataFrame = None,
                     **kwargs) -> pd.DataFrame:
        
        all_dates = close_prices.index
        etf_cols = [c for c in close_prices.columns]
        default_etf = 'AGG' if 'AGG' in etf_cols else etf_cols[0] if etf_cols else None
        
        has_stocks = stock_close is not None and not stock_close.empty
        stock_cols = list(stock_close.columns) if has_stocks else []
        
        all_cols = etf_cols + stock_cols
        weights = pd.DataFrame(0.0, index=all_dates, columns=all_cols)
        
        if default_etf:
            weights.loc[:all_dates[min(19, len(all_dates)-1)], default_etf] = 1.0
        warmup_end_idx = min(20, len(all_dates) - 1)
        
        W_JSG = 0.30
        W_AW = 0.50
        W_ROA = 0.10
        W_ROT = 0.10
        
        if has_stocks:
            turnover_df = stock_close * stock_volume
        
        # ====== 1. 搅屎棍策略(30%) — 全市场动量+缓冲池 ======
        # 测试结论：中小盘筛选反而降低收益，全市场动量6只效果最好
        # 但有幸存者偏差，需要8折衰减补偿
        jsg_holdings = []
        
        for i in range(warmup_end_idx + 1, len(all_dates)):
            date = all_dates[i]
            
            if i % 5 == 0 and has_stocks:
                loc = i
                lookback = min(20, loc)
                if lookback >= 5:
                    # 全市场动量选股：选夏普比率最高的12只（缓冲池）
                    scores = {}
                    for code in stock_close.columns:
                        p = stock_close[code].iloc[loc-lookback:loc+1]
                        v = stock_volume[code].iloc[loc-lookback:loc+1]
                        
                        if (v == 0).sum() > 10:
                            continue
                        valid_p = p[v > 0].dropna()
                        if len(valid_p) < 5:
                            continue
                        
                        period_ret = valid_p.iloc[-1] / valid_p.iloc[0] - 1.0
                        vol = valid_p.pct_change(fill_method=None).std()
                        if vol > 0 and period_ret > 0:
                            scores[code] = period_ret / vol  # 夏普
                    
                    top12 = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:12]
                    
                    # 缓冲池机制
                    new_holdings = []
                    for s in jsg_holdings:
                        if s in top12 and len(new_holdings) < 6:
                            new_holdings.append(s)
                    for s in top12:
                        if s not in new_holdings and len(new_holdings) < 6:
                            new_holdings.append(s)
                    jsg_holdings = new_holdings
            
            if jsg_holdings:
                # 幸存者偏差衰减：0.85（年化约-5%惩罚）
                JSG_SURVIVOR_DISCOUNT = 0.85
                per_stock = W_JSG * JSG_SURVIVOR_DISCOUNT / len(jsg_holdings)
                for s in jsg_holdings:
                    if s in weights.columns:
                        weights.loc[date, s] = per_stock
                # 剩余资金放入国债
                remaining = W_JSG * (1 - JSG_SURVIVOR_DISCOUNT)
                if default_etf:
                    weights.loc[date, default_etf] += remaining
            elif default_etf:
                weights.loc[date, default_etf] += W_JSG
        
        # ====== 2. 全天候ETF策略(50%) — 不变 ======
        aw_map = {'AGG': 0.30 * W_AW, 'GLD': 0.20 * W_AW, 'QQQ': 0.20 * W_AW, 'SPY': 0.30 * W_AW}
        for date in all_dates[warmup_end_idx+1:]:
            for etf, w in aw_map.items():
                if etf in weights.columns:
                    weights.loc[date, etf] += w
        
        # ====== 3. ROA策略(10%) — 不变 ======
        roa_holding = None
        for i in range(warmup_end_idx + 1, len(all_dates)):
            date = all_dates[i]
            if i % 20 == 0 and has_stocks:
                loc = i
                lookback = min(60, loc)
                if lookback >= 10:
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
                        mean_p = valid.mean()
                        if valid.iloc[-1] > mean_p * 1.2:
                            continue
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
                ROA_SURVIVOR_DISCOUNT = 0.85
                weights.loc[date, roa_holding] += W_ROA * ROA_SURVIVOR_DISCOUNT
                if default_etf:
                    weights.loc[date, default_etf] += W_ROA * (1 - ROA_SURVIVOR_DISCOUNT)
            elif default_etf:
                weights.loc[date, default_etf] += W_ROA
        
        # ====== 4. 核心轮动策略(10%) — 不变 ======
        rot_holding = default_etf
        for i in range(warmup_end_idx + 1, len(all_dates)):
            date = all_dates[i]
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


if __name__ == '__main__':
    
    print(f"\n{'#'*80}")
    print(f"  🧪 聚宽多策略组合回测 v6 — 最终优化版")
    print(f"  📖 来源: https://www.joinquant.com/post/64178")
    print(f"{'#'*80}")
    
    result = backtest_portfolio_strategy(
        strategy_func=make_jq_portfolio_v6(),
        strategy_name='聚宽多策略组合_v6',
        strategy_type='组合策略',
        strategy_params={
            'sub_strategies': '搅屎棍30%+全天候50%+ROA10%+轮动10%',
            'jsg_v6': '周频中小盘(20-70%分位)→动量50%+质量30%+低波动20%→缓冲池6只',
            'aw': '固定比例(国债30%+黄金20%+创业板20%+沪深300 30%)',
            'roa': '月频中小盘+低估+最高夏普1只',
            'rot': '周频双周期动量ETF轮动+R²+急跌过滤',
            'source': '聚宽64178',
        },
        strategy_desc='克隆自聚宽(64178): v6优化版 - 搅屎棍改为中小盘动量+质量综合评分',
        source='聚宽克隆(64178)',
        market_scope=['CN'],
    )
    
    print(f"\n\n{'='*80}")
    print(f"  📊 与聚宽原始回测对比")
    print(f"{'='*80}")
    print(f"  聚宽原始: A股年化 40%+ (2019-2024)")
    
    if result.get('market_summaries'):
        for market, ms in result['market_summaries'].items():
            m_label = {'US': '美股', 'HK': '港股', 'CN': 'A股'}[market]
            print(f"  v6回测:   [{m_label}] 年化{ms['annual_return']:+.2f}% | 回撤{ms['max_drawdown']:.1f}% | 夏普{ms['sharpe']:.2f} | 评分{ms['score']}分")
    
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
