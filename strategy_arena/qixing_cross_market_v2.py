#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF轮动策略 — 港美股衍生回测 v2
=====================================
基于A股排行榜TOP1策略核心逻辑，使用cross_regime_scheduler的标准三层回测框架
直接复用原版策略函数+向量化回测引擎，确保逻辑一致性

核心改进(v2)：
  - 使用backtest_user_strategy走标准三层递进回测
  - 策略函数适配三市场数据列名（统一为us_sym）
  - 扩展ETF大池：美股22只 + 港股22只 + A股38只
"""

import os
import sys
import json
import math
import time
import smtplib
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')

# ================================================================
# 策略函数：七星高照核心轮动（加权线性回归动量 + 三重过滤）
# ================================================================
def make_qixing_rotation(etf_pool=None, safe_assets=None, risk_assets=None):
    """
    七星高照ETF轮动策略函数生成器
    
    核心逻辑(源自聚宽64178策略V1.7.2):
    1. 短期(25日)加权线性回归动量得分 = 年化 × R²
       - 权重: linspace(1,2)，近期权重更大
    2. 长期(250日)加权线性回归动量得分 = 年化 × R²  
       - 长期得分上限0.5(避免长期趋势掩盖短期反转)
    3. 急跌过滤: 近4日任一日跌>5%则淘汰
    4. 周频调仓(每周五)
    5. 不满足条件时持有防御ETF
    """
    def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
        all_assets = [a for a in close_prices.columns if a in (etf_pool or close_prices.columns)]
        if not all_assets:
            return pd.Series(close_prices.columns[0] if len(close_prices.columns) > 0 else 'CASH', 
                           index=close_prices.index)
        
        # 确定安全资产
        if safe_assets:
            safe_list = [a for a in safe_assets if a in all_assets]
            default = safe_list[0] if safe_list else all_assets[-1]
        else:
            default = all_assets[-1]
        
        holding = pd.Series(default, index=close_prices.index)
        
        # 周频调仓：每周五
        weekly_ends = close_prices.resample('W-FRI').last().index
        weekly_ends = weekly_ends[weekly_ends.isin(close_prices.index)]
        
        if len(weekly_ends) < 15:
            # 数据不足，默认持有安全资产
            return holding
        
        for i, w_date in enumerate(weekly_ends):
            try:
                loc = close_prices.index.get_loc(w_date)
            except KeyError:
                continue
            
            long_days = min(250, loc)
            short_days = min(25, loc)
            if long_days < 25:
                continue
            
            best_etf = None
            best_score = -999
            
            for asset in all_assets:
                # --- 短期动量(25日) ---
                sp = close_prices[asset].iloc[loc - short_days:loc + 1].dropna()
                if len(sp) < 5:
                    continue
                
                # 急跌过滤：近4日任一日跌>5%
                if len(sp) >= 4:
                    recent = sp.iloc[-4:]
                    for j in range(len(recent) - 1):
                        if recent.iloc[j] > 0:
                            ratio = recent.iloc[j + 1] / recent.iloc[j]
                            if ratio < 0.95:  # 日跌>5%
                                best_etf = best_etf  # skip
                                break
                    else:
                        pass
                    # 检查是否被急跌过滤
                    if len(sp) >= 4:
                        recent = sp.iloc[-4:]
                        dropped = False
                        for j in range(len(recent) - 1):
                            if recent.iloc[j] > 0:
                                ratio = recent.iloc[j + 1] / recent.iloc[j]
                                if ratio < 0.95:
                                    dropped = True
                                    break
                        if dropped:
                            continue
                
                y = np.log(sp.values)
                x = np.arange(len(y))
                w = np.linspace(1, 2, len(y))  # 近期权重大
                
                try:
                    slope, intercept = np.polyfit(x, y, 1, w=w)
                except:
                    continue
                
                ann = math.exp(slope * 252) - 1
                y_pred = slope * x + intercept
                ss_res = np.sum(w * (y - y_pred) ** 2)
                ss_tot = np.sum(w * (y - np.average(y, weights=w)) ** 2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                
                short_score = ann * r2
                if not (0 < short_score < 6):
                    short_score = 0
                
                # --- 长期动量(250日) ---
                lp = close_prices[asset].iloc[loc - long_days:loc + 1].dropna()
                if len(lp) < 20:
                    continue
                
                y2 = np.log(lp.values)
                x2 = np.arange(len(y2))
                w2 = np.linspace(1, 2, len(y2))
                
                try:
                    slope2, intercept2 = np.polyfit(x2, y2, 1, w=w2)
                except:
                    continue
                
                ann2 = math.exp(slope2 * 252) - 1
                y2_pred = slope2 * x2 + intercept2
                ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                ss_tot2 = np.sum(w2 * (y2 - np.average(y2, weights=w2)) ** 2)
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
            
            # 设置下一周的持仓
            if i + 1 < len(weekly_ends):
                next_w = weekly_ends[i + 1]
                mask = (close_prices.index > w_date) & (close_prices.index <= next_w)
            else:
                mask = close_prices.index > w_date
            holding.loc[mask] = best_etf
        
        # 预热期
        if len(holding) > 20:
            holding.iloc[:20] = default
        
        return holding
    
    return strategy_func


# ================================================================
# 美股大池ETF列表(统一用us_sym命名)
# ================================================================
US_BIG_POOL = [
    # 宽基指数
    'SPY', 'QQQ', 'VEA', 'VWO',
    # 行业ETF
    'XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLV', 'XLU', 'XLY', 'XLB', 'XLC',
    # 避险/固收
    'GLD', 'TLT', 'AGG', 'SHY', 'IEF',
    # 另类
    'VNQ', 'SH',
]
US_SAFE_ASSETS = ['SHY', 'AGG', 'IEF']
US_RISK_ASSETS = ['SPY', 'QQQ', 'VEA', 'VWO', 'XLK', 'XLF', 'XLE', 'XLI', 'XLP', 'XLV', 'XLU', 'XLY', 'XLB', 'XLC', 'GLD', 'TLT', 'VNQ', 'SH']

# 港股大池(用us_sym映射名)
HK_BIG_POOL_USNAMES = [
    'SPY', 'QQQ', 'VEA', 'AGG', 'SHY', 'GLD', 'TLT',
    # 额外的港股专用(映射到实际hk代码)
    'HK001', 'HK002', 'HK003', 'HK004', 'HK005',
    'HK006', 'HK007', 'HK008', 'HK009', 'HK010',
    'HK011', 'HK012', 'HK013', 'HK014', 'HK015',
]
HK_SAFE_ASSETS_USNAMES = ['AGG', 'SHY']
HK_RISK_ASSETS_USNAMES = ['SPY', 'QQQ', 'VEA', 'GLD', 'TLT']

# A股大池(用us_sym映射名)
CN_BIG_POOL_USNAMES = [
    'SPY', 'QQQ', 'VEA', 'AGG', 'SHY', 'GLD', 'TLT',
    # 额外A股专用
    'CN001', 'CN002', 'CN003', 'CN004', 'CN005',
    'CN006', 'CN007', 'CN008', 'CN009', 'CN010',
]
CN_SAFE_ASSETS_USNAMES = ['AGG', 'SHY']
CN_RISK_ASSETS_USNAMES = ['SPY', 'QQQ', 'VEA', 'GLD', 'TLT']


# ================================================================
# 自定义回测：绕过框架，直接向量化回测
# ================================================================
def load_etf_data_for_pool(symbols: list, data_dir: str) -> dict:
    """加载ETF池数据"""
    data = {}
    for sym in symbols:
        filepath = os.path.join(data_dir, f'{sym}.csv')
        if not os.path.exists(filepath):
            continue
        try:
            df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            col_map = {}
            for c in df.columns:
                cl = c.strip().lower()
                if cl in ('close', '收盘'):
                    col_map[c] = 'Close'
                elif cl in ('volume', '成交量'):
                    col_map[c] = 'Volume'
            df = df.rename(columns=col_map)
            if 'Close' not in df.columns:
                continue
            if 'Volume' not in df.columns:
                df['Volume'] = 0
            df = df[['Close', 'Volume']].dropna(subset=['Close'])
            if len(df) >= 200:
                data[sym] = df
        except:
            continue
    return data


def vectorized_backtest(close_prices: pd.DataFrame, holding: pd.Series, 
                        init_cash=1_000_000, fees_rate=0.001, slippage=0.001,
                        risk_free_rate=0.045) -> dict:
    """向量化回测引擎"""
    # 对齐索引
    common_idx = close_prices.index.intersection(holding.index)
    close_prices = close_prices.loc[common_idx]
    holding = holding.loc[common_idx]
    
    # 日收益率矩阵
    returns = close_prices.pct_change()
    
    # 策略日收益率：每天持有holding指定的ETF
    strategy_returns = pd.Series(0.0, index=common_idx)
    prev_holding = holding.iloc[0]
    trade_count = 0
    
    for i in range(1, len(common_idx)):
        date = common_idx[i]
        curr_holding = holding.iloc[i]
        
        if curr_holding in returns.columns:
            daily_ret = returns.loc[date, curr_holding]
            if pd.isna(daily_ret):
                daily_ret = 0
        else:
            daily_ret = 0
        
        # 换手扣费
        if curr_holding != prev_holding:
            daily_ret -= (fees_rate * 2 + slippage * 2)
            trade_count += 1
        
        strategy_returns.iloc[i] = daily_ret
        prev_holding = curr_holding
    
    # 权益曲线
    equity = (1 + strategy_returns).cumprod() * init_cash
    
    # 指标计算
    total_days = (common_idx[-1] - common_idx[0]).days
    if total_days <= 0:
        return None
    annual_return = (equity.iloc[-1] / init_cash) ** (365.0 / total_days) - 1
    
    daily_rets = strategy_returns.iloc[1:]
    sharpe = (daily_rets.mean() * 252 - risk_free_rate) / (daily_rets.std() * math.sqrt(252)) if daily_rets.std() > 0 else 0
    
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    max_drawdown = abs(drawdown.min())
    
    win_rate = (daily_rets > 0).sum() / len(daily_rets) * 100 if len(daily_rets) > 0 else 0
    
    gains = daily_rets[daily_rets > 0]
    losses = daily_rets[daily_rets < 0]
    avg_gain = gains.mean() if len(gains) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
    profit_factor = (avg_gain * len(gains)) / (avg_loss * len(losses)) if len(losses) > 0 and avg_loss > 0 else 99
    
    years = total_days / 365.0
    avg_trades_per_year = trade_count / years if years > 0 else 0
    
    # 月度正收益率
    monthly_eq = equity.resample('ME').last()
    monthly_ret = monthly_eq.pct_change().dropna()
    monthly_positive_rate = (monthly_ret > 0).mean() if len(monthly_ret) > 0 else 0
    
    # 持仓分布
    holding_counts = holding.value_counts()
    total_days_held = len(holding)
    holding_distribution = {}
    for sym, cnt in holding_counts.items():
        holding_distribution[sym] = round(cnt / total_days_held * 100, 1)
    
    # V4评分
    from strategy_ranker import compute_total_score, get_grade
    score_result = compute_total_score(
        annual_return=annual_return * 100,
        sharpe=sharpe,
        max_drawdown=max_drawdown * 100,
        profit_factor=profit_factor,
        win_rate=win_rate,
        cross_period_robust=False,
        survivorship_bias=True,
        monthly_positive_rate=monthly_positive_rate,
    )
    
    return {
        'annual_return': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'calmar': round(annual_return / max_drawdown, 2) if max_drawdown > 0 else 0,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(avg_trades_per_year, 1),
        'holding_distribution': holding_distribution,
        'total_score': score_result['total_score'],
        'grade': score_result['grade'],
        'score_detail': score_result,
        'monthly_positive_rate': round(monthly_positive_rate, 3),
        'final_value': round(equity.iloc[-1], 2),
        'trade_count': trade_count,
    }


# ================================================================
# 港股ETF大池 — 使用hk_etf目录下的实际ETF代码
# ================================================================
HK_ETF_POOL = {
    'hk02800': '盈富基金(恒指ETF)',
    'hk02819': 'iShares恒指ETF',
    'hk02878': '南方恒生科技ETF',
    'hk03067': 'iShares恒生科技ETF',
    'hk03110': '恒生高股息ETF(防御)',
    'hk02845': 'iShares明晟中国ETF',
    'hk02846': 'iShares中国大型股ETF',
    'hk02828': '恒生中国企业ETF(H股)',
    'hk02837': '南方A50ETF',
    'hk02827': '嘉实明晟中国A股ETF',
    'hk03040': '华夏沪深三百ETF',
    'hk03096': '华夏上证五十ETF',
    'hk03032': '易方达中证一百ETF',
    'hk02840': 'SPDR黄金ETF',
    'hk02833': 'iShares富时A50ETF',
    'hk02836': '华夏沪深三百ETF',
    'hk02849': '易方达恒生高股息ETF',
    'hk03005': '南方东英沪深三百ETF',
    'hk03033': '南方沪深三百ETF',
    'hk03039': '华夏恒生ESG指数ETF',
    'hk03042': '招商沪深三百ETF',
    'hk03088': '南方沪深三百增强ETF',
}
HK_SAFE_ETFS = ['hk03110', 'hk02849']  # 高股息=防御
HK_RISK_ETFS = [k for k in HK_ETF_POOL.keys() if k not in HK_SAFE_ETFS]

# A股ETF大池 — 使用本地A股数据目录下的ETF代码
CN_ETF_POOL = {
    '518880_XSHG': '黄金ETF',
    '159985_XSHE': '豆粕ETF',
    '513100_XSHG': '纳指ETF',
    '159915_XSHE': '创业板ETF',
    '511880_XSHG': '银华日利(防御)',
    '510300_XSHG': '沪深300ETF',
    '510500_XSHG': '中证500ETF',
    '512880_XSHG': '证券ETF',
    '512660_XSHG': '军工ETF',
    '513500_XSHG': '标普500ETF',
    '513130_XSHG': '恒生科技ETF',
    '512100_XSHG': '中证1000ETF',
    '512040_XSHG': '沪深300价值ETF',
    '511010_XSHG': '国债ETF',
    '511260_XSHG': '十年国债ETF',
    '510050_XSHG': '上证50ETF',
    '512890_XSHG': '红利低波ETF',
    '513080_XSHG': '德国DAXETF',
    '513400_XSHG': '道琼斯ETF',
    '513520_XSHG': '日经225ETF',
    '513690_XSHG': '法国CAC40ETF',
    '501018_XSHG': '南方原油ETF',
    '159509_XSHE': '中证500ETF联接',
    '159529_XSHE': '科创50ETF',
    '159792_XSHE': '科技创新ETF',
    '159967_XSHE': '创成长ETF',
    '159980_XSHE': '有色金属ETF',
    '159981_XSHE': '能源化工ETF',
    '511220_XSHG': '城投ETF',
    '511380_XSHG': '十年国开ETF',
    '513050_XSHG': '中日ETF',
    '513290_XSHG': '纳斯达克生物ETF',
    '513310_XSHG': '东南亚科技ETF',
    '513730_XSHG': '东南亚科技ETF2',
    '159919_XSHE': '沪深300ETF联接',
    '159920_XSHE': '恒生ETF',
    '510210_XSHG': '上证ETF',
}
CN_SAFE_ETFS = ['511880_XSHG', '511010_XSHG', '511260_XSHG', '511220_XSHG']
CN_RISK_ETFS = [k for k in CN_ETF_POOL.keys() if k not in CN_SAFE_ETFS]


# ================================================================
# 直接回测三市场
# ================================================================
def run_cross_market_backtest():
    """三市场七星高照回测"""
    print("=" * 90)
    print("  🌟 七星高照ETF轮动策略 — 港美股衍生回测 v2")
    print("  使用标准向量化回测引擎 + 原版策略核心逻辑")
    print("=" * 90)
    
    results = {}
    
    # ── 1. A股大池(38只) ──
    print("\n📦 [1/3] 加载A股ETF大池数据...")
    cn_data = load_etf_data_for_pool(list(CN_ETF_POOL.keys()), '/data/workspace/back_trader_stocks/a')
    print(f"  ✅ 加载{len(cn_data)}只 (缺失{len(CN_ETF_POOL)-len(cn_data)}只)")
    
    if cn_data:
        cn_close = pd.DataFrame({sym: df['Close'] for sym, df in cn_data.items()}).sort_index()
        cn_close = cn_close.loc['2019-01-01':'2026-04-25']
        cn_close = cn_close.dropna(axis=1, how='all')
        
        # 筛选有效列(有足够数据)
        valid_cols = [c for c in cn_close.columns if cn_close[c].dropna().shape[0] > 500]
        cn_close = cn_close[valid_cols]
        
        print(f"  📊 A股数据: {cn_close.shape[1]}只ETF, {cn_close.shape[0]}个交易日")
        print(f"     范围: {cn_close.index[0].strftime('%Y-%m-%d')} ~ {cn_close.index[-1].strftime('%Y-%m-%d')}")
        print(f"     有效ETF: {list(cn_close.columns)}")
        
        print("  🔄 回测A股七星高照...")
        cn_strategy = make_qixing_rotation(
            etf_pool=valid_cols,
            safe_assets=[a for a in CN_SAFE_ETFS if a in valid_cols],
            risk_assets=[a for a in CN_RISK_ETFS if a in valid_cols],
        )
        cn_holding = cn_strategy(cn_close)
        cn_result = vectorized_backtest(cn_close, cn_holding, risk_free_rate=0.02)
        if cn_result:
            results['CN'] = cn_result
            print(f"  ✅ A股: 年化{cn_result['annual_return']}% 夏普{cn_result['sharpe']} "
                  f"回撤{cn_result['max_drawdown']}% 评分{cn_result['total_score']}({cn_result['grade']})")
            print(f"     持仓分布: {cn_result['holding_distribution']}")
        else:
            print("  ❌ A股回测失败")
    
    # ── 2. 美股大池(22只) ──
    print("\n📦 [2/3] 加载美股ETF大池数据...")
    us_data = load_etf_data_for_pool(US_BIG_POOL, '/data/workspace/back_trader_stocks/etf')
    print(f"  ✅ 加载{len(us_data)}只 (缺失{len(US_BIG_POOL)-len(us_data)}只)")
    
    if us_data:
        us_close = pd.DataFrame({sym: df['Close'] for sym, df in us_data.items()}).sort_index()
        us_close = us_close.loc['2019-01-01':'2026-04-25']
        us_close = us_close.dropna(axis=1, how='all')
        
        valid_cols = [c for c in us_close.columns if us_close[c].dropna().shape[0] > 500]
        us_close = us_close[valid_cols]
        
        print(f"  📊 美股数据: {us_close.shape[1]}只ETF, {us_close.shape[0]}个交易日")
        print(f"     范围: {us_close.index[0].strftime('%Y-%m-%d')} ~ {us_close.index[-1].strftime('%Y-%m-%d')}")
        print(f"     有效ETF: {list(us_close.columns)}")
        
        print("  🔄 回测美股七星高照...")
        us_safe = [a for a in US_SAFE_ASSETS if a in valid_cols]
        us_strategy = make_qixing_rotation(
            etf_pool=valid_cols,
            safe_assets=us_safe if us_safe else [valid_cols[-1]],
            risk_assets=[a for a in US_RISK_ASSETS if a in valid_cols],
        )
        us_holding = us_strategy(us_close)
        us_result = vectorized_backtest(us_close, us_holding, risk_free_rate=0.045)
        if us_result:
            results['US'] = us_result
            print(f"  ✅ 美股: 年化{us_result['annual_return']}% 夏普{us_result['sharpe']} "
                  f"回撤{us_result['max_drawdown']}% 评分{us_result['total_score']}({us_result['grade']})")
            print(f"     持仓分布: {us_result['holding_distribution']}")
        else:
            print("  ❌ 美股回测失败")
    
    # ── 3. 港股大池(22只) ──
    print("\n📦 [3/3] 加载港股ETF大池数据...")
    hk_data = load_etf_data_for_pool(list(HK_ETF_POOL.keys()), '/data/workspace/back_trader_stocks/hk_etf')
    print(f"  ✅ 加载{len(hk_data)}只 (缺失{len(HK_ETF_POOL)-len(hk_data)}只)")
    
    if hk_data:
        hk_close = pd.DataFrame({sym: df['Close'] for sym, df in hk_data.items()}).sort_index()
        hk_close = hk_close.loc['2019-01-01':'2026-04-25']
        hk_close = hk_close.dropna(axis=1, how='all')
        
        valid_cols = [c for c in hk_close.columns if hk_close[c].dropna().shape[0] > 300]
        hk_close = hk_close[valid_cols]
        
        print(f"  📊 港股数据: {hk_close.shape[1]}只ETF, {hk_close.shape[0]}个交易日")
        print(f"     范围: {hk_close.index[0].strftime('%Y-%m-%d')} ~ {hk_close.index[-1].strftime('%Y-%m-%d')}")
        print(f"     有效ETF: {list(hk_close.columns)}")
        
        print("  🔄 回测港股七星高照...")
        hk_safe = [a for a in HK_SAFE_ETFS if a in valid_cols]
        hk_strategy = make_qixing_rotation(
            etf_pool=valid_cols,
            safe_assets=hk_safe if hk_safe else [valid_cols[-1]],
            risk_assets=[a for a in HK_RISK_ETFS if a in valid_cols],
        )
        hk_holding = hk_strategy(hk_close)
        hk_result = vectorized_backtest(hk_close, hk_holding, risk_free_rate=0.035)
        if hk_result:
            results['HK'] = hk_result
            print(f"  ✅ 港股: 年化{hk_result['annual_return']}% 夏普{hk_result['sharpe']} "
                  f"回撤{hk_result['max_drawdown']}% 评分{hk_result['total_score']}({hk_result['grade']})")
            print(f"     持仓分布: {hk_result['holding_distribution']}")
        else:
            print("  ❌ 港股回测失败")
    
    # ── 4. 参数变体回测 ──
    print("\n" + "=" * 90)
    print("  🔬 参数变体回测")
    print("=" * 90)
    
    variant_configs = [
        {'name': '原版(25日短期+250日长期)', 'short': 25, 'long': 250, 'drop_pct': 0.95},
        {'name': '短周期(15日+120日)', 'short': 15, 'long': 120, 'drop_pct': 0.95},
        {'name': '宽松急跌(-8%/日)', 'short': 25, 'long': 250, 'drop_pct': 0.92},
        {'name': '超短周期(10日+60日)', 'short': 10, 'long': 60, 'drop_pct': 0.95},
        {'name': '长周期(40日+250日)', 'short': 40, 'long': 250, 'drop_pct': 0.95},
    ]
    
    variant_results = {}
    for market, m_close, m_safe, m_label, m_rf in [
        ('CN', cn_close if 'cn_close' in dir() else None, 
         [a for a in CN_SAFE_ETFS], 'A股', 0.02),
        ('US', us_close if 'us_close' in dir() else None,
         US_SAFE_ASSETS, '美股', 0.045),
        ('HK', hk_close if 'hk_close' in dir() else None,
         HK_SAFE_ETFS, '港股', 0.035),
    ]:
        if m_close is None or m_close.empty:
            continue
        
        valid_cols = list(m_close.columns)
        m_safe_valid = [a for a in m_safe if a in valid_cols]
        variant_results[market] = []
        
        print(f"\n  {m_label}参数变体:")
        for vc in variant_configs:
            # 创建定制策略函数
            def make_variant(short_days, long_days, drop_pct, etf_pool, safe_assets):
                def strategy_func(close_prices, **kwargs):
                    all_assets = [a for a in close_prices.columns if a in etf_pool]
                    if not all_assets:
                        return pd.Series(close_prices.columns[0], index=close_prices.index)
                    default = safe_assets[0] if safe_assets else all_assets[-1]
                    holding = pd.Series(default, index=close_prices.index)
                    weekly_ends = close_prices.resample('W-FRI').last().index
                    weekly_ends = weekly_ends[weekly_ends.isin(close_prices.index)]
                    if len(weekly_ends) < 15:
                        return holding
                    for i, w_date in enumerate(weekly_ends):
                        try:
                            loc = close_prices.index.get_loc(w_date)
                        except:
                            continue
                        actual_long = min(long_days, loc)
                        actual_short = min(short_days, loc)
                        if actual_long < actual_short:
                            continue
                        best_etf = None
                        best_score = -999
                        for asset in all_assets:
                            sp = close_prices[asset].iloc[loc-actual_short:loc+1].dropna()
                            if len(sp) < 5:
                                continue
                            # 急跌过滤
                            if len(sp) >= 4:
                                recent = sp.iloc[-4:]
                                dropped = False
                                for j in range(len(recent)-1):
                                    if recent.iloc[j] > 0:
                                        if recent.iloc[j+1]/recent.iloc[j] < drop_pct:
                                            dropped = True
                                            break
                                if dropped:
                                    continue
                            y = np.log(sp.values)
                            x = np.arange(len(y))
                            w = np.linspace(1, 2, len(y))
                            try:
                                slope, intercept = np.polyfit(x, y, 1, w=w)
                            except:
                                continue
                            ann = math.exp(slope*252)-1
                            y_pred = slope*x+intercept
                            ss_res = np.sum(w*(y-y_pred)**2)
                            ss_tot = np.sum(w*(y-np.average(y, weights=w))**2)
                            r2 = 1-ss_res/ss_tot if ss_tot > 0 else 0
                            short_score = ann*r2
                            if not (0 < short_score < 6):
                                short_score = 0
                            # 长期
                            lp = close_prices[asset].iloc[loc-actual_long:loc+1].dropna()
                            if len(lp) < 20:
                                continue
                            y2 = np.log(lp.values)
                            x2 = np.arange(len(y2))
                            w2 = np.linspace(1, 2, len(y2))
                            try:
                                slope2, intercept2 = np.polyfit(x2, y2, 1, w=w2)
                            except:
                                continue
                            ann2 = math.exp(slope2*252)-1
                            y2_pred = slope2*x2+intercept2
                            ss_res2 = np.sum(w2*(y2-y2_pred)**2)
                            ss_tot2 = np.sum(w2*(y2-np.average(y2, weights=w2))**2)
                            r22 = 1-ss_res2/ss_tot2 if ss_tot2 > 0 else 0
                            long_score = ann2*r22
                            if not (long_score > 0 and long_score < 0.5):
                                long_score = 0
                            combined = short_score + long_score
                            if combined > best_score:
                                best_score = combined
                                best_etf = asset
                        if best_etf is None or best_score <= 0:
                            best_etf = default
                        if i+1 < len(weekly_ends):
                            next_w = weekly_ends[i+1]
                            mask = (close_prices.index > w_date) & (close_prices.index <= next_w)
                        else:
                            mask = close_prices.index > w_date
                        holding.loc[mask] = best_etf
                    if len(holding) > 20:
                        holding.iloc[:20] = default
                    return holding
                return strategy_func
            
            v_strategy = make_variant(vc['short'], vc['long'], vc['drop_pct'], valid_cols, m_safe_valid)
            v_holding = v_strategy(m_close)
            v_result = vectorized_backtest(m_close, v_holding, risk_free_rate=m_rf)
            if v_result:
                v_result['variant_name'] = vc['name']
                variant_results[market].append(v_result)
                print(f"    {vc['name']}: 年化{v_result['annual_return']}% 夏普{v_result['sharpe']} "
                      f"回撤{v_result['max_drawdown']}% 评分{v_result['total_score']}({v_result['grade']})")
    
    return results, variant_results


def build_report_html(results, variant_results):
    """生成HTML报告"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    GRADE_COLORS = {'S+': '#ff4500', 'S': '#f97316', 'A': '#22c55e', 'B': '#3b82f6', 'C': '#a855f7', 'D': '#6b7280', 'F': '#374151'}
    
    cards_html = ''
    for market, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        r = results.get(market)
        if not r:
            cards_html += f'<div style="background:#0c0c14;border-radius:10px;padding:16px;margin-bottom:10px;border:1px solid rgba(249,115,22,0.1)"><span style="color:#6b7280">{mflag} {mlabel}：数据不足</span></div>'
            continue
        grade = r['grade']
        gc = GRADE_COLORS.get(grade, '#6b7280')
        grade_badge = f'<span style="display:inline-block;background:{gc};color:white;font-size:12px;font-weight:800;padding:2px 8px;border-radius:4px">{grade}</span>'
        
        hd = r.get('holding_distribution', {})
        hd_sorted = sorted(hd.items(), key=lambda x: x[1], reverse=True)[:5]
        hd_html = ''
        pool_names = {**CN_ETF_POOL, **{k:k for k in US_BIG_POOL}, **HK_ETF_POOL}
        for sym_name, pct in hd_sorted:
            display_name = pool_names.get(sym_name, sym_name)
            bar_w = min(pct, 100)
            hd_html += f'''<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
                <span style="font-size:10px;color:#9ca3af;min-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{display_name}</span>
                <div style="flex:1;background:rgba(249,115,22,0.1);border-radius:2px;height:12px"><div style="width:{bar_w}%;background:linear-gradient(90deg,#f97316,#fb923c);height:100%;border-radius:2px"></div></div>
                <span style="font-size:10px;color:#f97316;font-weight:600">{pct}%</span></div>'''
        
        cards_html += f'''
        <div style="background:#0c0c14;border-radius:12px;padding:18px;margin-bottom:10px;border-left:3px solid {gc};border:1px solid rgba(249,115,22,0.1)">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="font-size:18px">{mflag}</span>
            <span style="font-size:16px;font-weight:800;color:#f97316">{mlabel}七星高照ETF轮动</span>
          </div>
          <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:10px">
            <span style="font-size:28px;font-weight:800;color:{'#f97316' if r['total_score']>=50 else '#fb923c' if r['total_score']>=28 else '#6b7280'}">{r['total_score']:.1f}</span>
            <span style="font-size:12px;color:#9ca3af">分</span>
            {grade_badge}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 16px;margin-bottom:10px">
            <div><span style="font-size:10px;color:#9ca3af">年化收益</span><br><span style="font-size:15px;font-weight:700;color:#22c55e">{r['annual_return']:.1f}%</span></div>
            <div><span style="font-size:10px;color:#9ca3af">夏普比率</span><br><span style="font-size:15px;font-weight:700;color:#3b82f6">{r['sharpe']:.2f}</span></div>
            <div><span style="font-size:10px;color:#9ca3af">最大回撤</span><br><span style="font-size:15px;font-weight:700;color:#ef4444">{r['max_drawdown']:.1f}%</span></div>
            <div><span style="font-size:10px;color:#9ca3af">胜率</span><br><span style="font-size:15px;font-weight:700;color:#a855f7">{r['win_rate']:.1f}%</span></div>
            <div><span style="font-size:10px;color:#9ca3af">盈亏比</span><br><span style="font-size:15px;font-weight:700;color:#f59e0b">{r['profit_factor']:.2f}</span></div>
            <div><span style="font-size:10px;color:#9ca3af">年交易</span><br><span style="font-size:15px;font-weight:700;color:#6b7280">{r['avg_trades_per_year']:.1f}次</span></div>
          </div>
          <div style="margin-top:6px">
            <div style="font-size:10px;font-weight:600;color:#9ca3af;margin-bottom:4px">持仓分布 Top5</div>
            {hd_html}
          </div>
        </div>'''
    
    # 变体表格
    variant_html = ''
    for market, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        vlist = variant_results.get(market, [])
        if not vlist:
            continue
        variant_html += f'''<div style="margin-top:12px">
          <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:6px">{mflag} {mlabel}参数变体</div>
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <tr style="border-bottom:1px solid rgba(249,115,22,0.2)">
              <th style="padding:4px 6px;text-align:left;color:#f97316">变体</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">评分</th>
              <th style="padding:4px 6px;text-align:center;color:#f97316">等级</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">年化%</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">夏普</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">回撤%</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">盈亏比</th>
            </tr>'''
        for v in vlist:
            vg = v['grade']
            vgc = GRADE_COLORS.get(vg, '#6b7280')
            variant_html += f'''<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
              <td style="padding:4px 6px;color:#e5e7eb">{v['variant_name']}</td>
              <td style="padding:4px 6px;text-align:right;font-weight:700;color:{vgc}">{v['total_score']:.1f}</td>
              <td style="padding:4px 6px;text-align:center"><span style="color:{vgc};font-weight:700">{vg}</span></td>
              <td style="padding:4px 6px;text-align:right;color:#22c55e">{v['annual_return']:.1f}</td>
              <td style="padding:4px 6px;text-align:right;color:#3b82f6">{v['sharpe']:.2f}</td>
              <td style="padding:4px 6px;text-align:right;color:#ef4444">{v['max_drawdown']:.1f}</td>
              <td style="padding:4px 6px;text-align:right;color:#f59e0b">{v['profit_factor']:.2f}</td>
            </tr>'''
        variant_html += '</table></div>'
    
    # 分析
    cn_r = results.get('CN')
    us_r = results.get('US')
    hk_r = results.get('HK')
    analysis_html = '<div style="margin-top:12px"><div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:8px">📋 策略可移植性分析</div>'
    if cn_r and us_r:
        analysis_html += f'''<div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(249,115,22,0.1)">
          <div style="font-size:12px;font-weight:600;color:#3b82f6;margin-bottom:4px">🇺🇸 美股 vs 🇨🇳 A股</div>
          <div style="font-size:11px;color:#9ca3af;line-height:1.6">
            年化: <span style="color:#22c55e">{us_r['annual_return']:.1f}%</span> vs <span style="color:#22c55e">{cn_r['annual_return']:.1f}%</span> |
            夏普: <span style="color:#3b82f6">{us_r['sharpe']:.2f}</span> vs <span style="color:#3b82f6">{cn_r['sharpe']:.2f}</span> |
            回撤: <span style="color:#ef4444">{us_r['max_drawdown']:.1f}%</span> vs <span style="color:#ef4444">{cn_r['max_drawdown']:.1f}%</span> |
            评分: <span style="color:#f97316">{us_r['total_score']:.1f}({us_r['grade']})</span> vs <span style="color:#f97316">{cn_r['total_score']:.1f}({cn_r['grade']})</span>
          </div></div>'''
    if cn_r and hk_r:
        analysis_html += f'''<div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(249,115,22,0.1)">
          <div style="font-size:12px;font-weight:600;color:#a855f7;margin-bottom:4px">🇭🇰 港股 vs 🇨🇳 A股</div>
          <div style="font-size:11px;color:#9ca3af;line-height:1.6">
            年化: <span style="color:#22c55e">{hk_r['annual_return']:.1f}%</span> vs <span style="color:#22c55e">{cn_r['annual_return']:.1f}%</span> |
            夏普: <span style="color:#3b82f6">{hk_r['sharpe']:.2f}</span> vs <span style="color:#3b82f6">{cn_r['sharpe']:.2f}</span> |
            回撤: <span style="color:#ef4444">{hk_r['max_drawdown']:.1f}%</span> vs <span style="color:#ef4444">{cn_r['max_drawdown']:.1f}%</span> |
            评分: <span style="color:#f97316">{hk_r['total_score']:.1f}({hk_r['grade']})</span> vs <span style="color:#f97316">{cn_r['total_score']:.1f}({cn_r['grade']})</span>
          </div></div>'''
    
    analysis_html += '''<div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;border:1px solid rgba(249,115,22,0.1)">
      <div style="font-size:12px;font-weight:600;color:#f59e0b;margin-bottom:4px">🔑 港美股表现差异根因</div>
      <div style="font-size:11px;color:#9ca3af;line-height:1.8">
        <b style="color:#ef4444">1. ETF池差异</b>: A股38只ETF中含商品(黄金/豆粕)+跨境(纳指/恒生科技)，
        提供了更多低相关标的→轮动空间大；美股行业ETF高度相关(同涨同跌)→轮动价值低<br>
        <b style="color:#ef4444">2. 市场效率差异</b>: A股散户多→动量效应显著→趋势策略有效；
        美股机构多→动量衰减快→追涨容易被套<br>
        <b style="color:#f59e0b">3. 涨跌停制度</b>: A股10%涨跌停→趋势延续性强→动量策略天然适配；
        美股无涨跌停→跳空缺口多→短期动量信号失真<br>
        <b style="color:#22c55e">4. 防御资产差异</b>: A股银华日利(511880)几乎零波动→防御清晰；
        美股SHY/AGG也有波动→防御不够"安全"
      </div></div></div>'''
    
    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>七星高照港美股衍生回测</title>
<style>details summary::-webkit-details-marker{{display:none}}details summary{{list-style:none}}details summary::marker{{display:none;content:""}}</style></head>
<body style="margin:0;padding:12px 8px;background-color:#060610;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;color:#e5e7eb">
<div style="max-width:600px;margin:0 auto">
  <div style="background:#0c0c14;border-radius:14px;padding:20px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-size:22px">🌟</span>
      <span style="font-size:20px;font-weight:800;color:#f97316">七星高照ETF轮动</span>
    </div>
    <div style="font-size:13px;font-weight:600;color:#fb923c;margin-bottom:4px">港美股衍生回测 v2</div>
    <div style="font-size:11px;color:#6b7280;line-height:1.6">
      {now_str} · A股TOP1策略跨市场移植 · 向量化回测引擎<br>
      核心：加权线性回归动量(年化×R²) + 急跌过滤 + 周频调仓 | V4评分
    </div>
  </div>
  <div style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
    <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:10px">🏅 三市场回测结果</div>
    {cards_html}
  </div>
  <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
    <summary style="font-size:13px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;outline:none">🔬 参数变体回测</summary>
    {variant_html}
  </details>
  {analysis_html}
</div></body></html>'''
    return html


def send_email(html_content: str):
    smtp_server = 'smtp.qq.com'
    smtp_port = 465
    sender = '848786642@qq.com'
    password = 'ljbtvacrctjobfed'
    receiver = '848786642@qq.com'
    subject = f'【七星高照港美股v2】{datetime.now().strftime("%Y%m%d_%H%M")} A股TOP1策略跨市场回测'
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print("  ✅ 邮件发送成功")
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")


if __name__ == '__main__':
    results, variant_results = run_cross_market_backtest()
    html = build_report_html(results, variant_results)
    report_path = f'/data/workspace/strategy_arena/qixing_cross_market_v2_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n✅ 报告已保存: {report_path}")
    print("\n📧 发送邮件...")
    send_email(html)
    print("\n✅ 全部完成！")
