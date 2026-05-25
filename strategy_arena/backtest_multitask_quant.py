#!/usr/bin/env python3
"""
修复优化版多任务量化选股模型 - 本地ETF回测适配版

原始策略是JoinQuant平台上的多因子+深度学习选股模型，
本脚本将其核心思想适配到本地ETF轮动回测框架：

核心逻辑映射：
- 多因子选股 → 多因子选ETF（动量/波动率/趋势/流动性等因子）
- ML模型预测排名 → 因子加权评分排名
- Focal Loss类别不平衡 → 动态阈值调整
- 不确定性加权 → 多因子自适应权重
- IC筛选因子 → 滚动IC筛选有效因子
- 时序严格划分 → 滚动窗口避免未来函数

策略类型：机器学习
"""

import sys
import os
import time
import numpy as np
import pandas as pd
from scipy import stats
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 添加路径，确保能导入回测框架
# ============================================================
sys.path.insert(0, '/data/workspace/strategy_arena')

# ============================================================
# 策略核心：多因子ETF评分轮动
# ============================================================

def calculate_etf_factors(close_prices, lookback=60):
    """
    从ETF价格数据计算多因子特征
    模拟原始策略的44个jqfactor因子（用可从价格计算的因子替代）
    """
    factors = {}
    
    for col in close_prices.columns:
        series = close_prices[col].dropna()
        if len(series) < lookback + 10:
            continue
        
        prices = series.values
        factor_dict = {}
        
        # 1. 动量因子（对应: momentum, ROC120, Rank1M）
        for lb in [20, 60, 120]:
            if len(prices) > lb:
                factor_dict[f'momentum_{lb}'] = prices[-1] / prices[-lb] - 1
        
        # 2. 波动率因子（对应: Variance20, turnover_volatility, daily_standard_deviation）
        for lb in [20, 60]:
            rets = np.diff(prices[-lb-1:]) / prices[-lb-1:-1]
            factor_dict[f'volatility_{lb}'] = np.std(rets) * np.sqrt(252) if len(rets) > 5 else np.nan
        
        # 3. 偏度/峰度因子（对应: Skewness20, Kurtosis20）
        if len(prices) > 60:
            rets_60 = np.diff(prices[-61:]) / prices[-61:-1]
            factor_dict['skewness'] = stats.skew(rets_60) if len(rets_60) > 10 else np.nan
            factor_dict['kurtosis'] = stats.kurtosis(rets_60) if len(rets_60) > 10 else np.nan
        
        # 4. ATR因子（对应: ATR14, ATR6）
        for lb in [14, 28]:
            if len(prices) > lb:
                high_low = np.abs(np.diff(prices[-lb:]))
                factor_dict[f'atr_{lb}'] = np.mean(high_low) / prices[-1] if prices[-1] > 0 else np.nan
        
        # 5. 成交量相关（对应: VOSC, VMACD, money_flow_20）- 简化为价格代理
        for lb in [10, 20]:
            if len(prices) > lb * 2:
                # 短期均值/长期均值
                short_ma = np.mean(prices[-lb:])
                long_ma = np.mean(prices[-lb*2:])
                factor_dict[f'price_osc_{lb}'] = short_ma / long_ma - 1 if long_ma > 0 else np.nan
        
        # 6. 均线偏离（对应: BIAS60）
        for lb in [20, 60]:
            if len(prices) > lb:
                ma = np.mean(prices[-lb:])
                factor_dict[f'bias_{lb}'] = (prices[-1] - ma) / ma if ma > 0 else np.nan
        
        # 7. RSI因子
        for lb in [14, 28]:
            if len(prices) > lb + 1:
                rets = np.diff(prices[-lb-1:])
                gains = np.mean(rets[rets > 0]) if np.any(rets > 0) else 0
                losses = -np.mean(rets[rets < 0]) if np.any(rets < 0) else 1e-8
                factor_dict[f'rsi_{lb}'] = gains / (gains + losses) if (gains + losses) > 0 else 0.5
        
        # 8. 最大回撤因子（对应: CR20）
        for lb in [20, 60]:
            if len(prices) > lb:
                window = prices[-lb:]
                peak = np.maximum.accumulate(window)
                dd = (window - peak) / peak
                factor_dict[f'max_dd_{lb}'] = np.min(dd)
        
        # 9. 夏普比率因子
        for lb in [20, 60]:
            if len(prices) > lb + 1:
                rets = np.diff(prices[-lb-1:]) / prices[-lb-1:-1]
                factor_dict[f'sharpe_{lb}'] = np.mean(rets) / (np.std(rets) + 1e-8) * np.sqrt(252)
        
        # 10. 量价趋势因子（对应: WVAD, VPT）
        if len(prices) > 20:
            rets = np.diff(prices[-21:]) / prices[-21:-1]
            factor_dict['trend_strength'] = np.sum(rets > 0) / len(rets) if len(rets) > 0 else 0.5
        
        factors[col] = factor_dict
    
    return factors


def calculate_rolling_ic(factor_history, return_history, min_periods=6):
    """
    滚动IC计算 - 对应原始策略的IC筛选逻辑
    """
    ic_values = defaultdict(list)
    
    for factor_name in factor_history.keys():
        for date_idx in range(len(factor_history[factor_name])):
            if date_idx not in return_history:
                continue
            factor_vals = factor_history[factor_name][date_idx]
            ret_vals = return_history[date_idx]
            
            # 对齐
            common_keys = set(factor_vals.keys()) & set(ret_vals.keys())
            if len(common_keys) < 3:
                continue
            
            f_vals = [factor_vals[k] for k in common_keys if not np.isnan(factor_vals.get(k, np.nan))]
            r_vals = [ret_vals[k] for k in common_keys if not np.isnan(factor_vals.get(k, np.nan))]
            
            if len(f_vals) < 3:
                continue
            
            try:
                ic, _ = stats.spearmanr(f_vals, r_vals)
                if not np.isnan(ic):
                    ic_values[factor_name].append(ic)
            except:
                continue
    
    return ic_values


def multi_factor_score(factor_dict, weights=None, ic_threshold=0.02):
    """
    多因子综合评分 - 对应原始策略的MultiTaskNetV2模型输出
    使用IC加权替代不确定性加权
    """
    if not factor_dict:
        return 0.0
    
    score = 0.0
    count = 0
    
    # 定义因子方向（正=越大越好，负=越小越好）
    factor_direction = {
        'momentum_20': 1, 'momentum_60': 1, 'momentum_120': 1,
        'volatility_20': -1, 'volatility_60': -1,
        'skewness': -1, 'kurtosis': -1,
        'atr_14': -1, 'atr_28': -1,
        'price_osc_10': 1, 'price_osc_20': 1,
        'bias_20': 1, 'bias_60': 1,
        'rsi_14': 1, 'rsi_28': 1,
        'max_dd_20': -1, 'max_dd_60': -1,
        'sharpe_20': 1, 'sharpe_60': 1,
        'trend_strength': 1,
    }
    
    for fname, fval in factor_dict.items():
        if np.isnan(fval):
            continue
        
        direction = factor_direction.get(fname, 1)
        w = weights.get(fname, 1.0) if weights else 1.0
        score += direction * fval * w
        count += 1
    
    return score / count if count > 0 else 0.0


# ============================================================
# 策略信号函数 - 符合回测框架接口
# ============================================================

def make_multitask_etf_strategy(ic_threshold=0.02, rebalance_months=2, lookback=60, 
                                  top_k=1, use_vol_filter=True, vol_threshold=0.25):
    """
    构造多因子ETF轮动策略信号函数
    模拟原始策略的核心逻辑：
    1. IC筛选有效因子 → 滚动IC测试
    2. 多任务学习评分 → 多因子加权评分
    3. 时序严格划分 → 滚动窗口
    4. 类别不平衡处理 → 动态阈值
    """
    
    def strategy_func(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
        # 获取市场资产池
        all_assets = [a for a in close_prices.columns]
        if not all_assets:
            return pd.Series('SHY', index=close_prices.index)
        
        # 识别风险/安全资产
        risk_like = [a for a in all_assets if a not in ['AGG', 'SHY', '511010_XSHG', '511880_XSHG']]
        safe_like = [a for a in all_assets if a in ['AGG', 'SHY', '511010_XSHG', '511880_XSHG']]
        
        if not risk_like:
            return pd.Series(safe_like[0] if safe_like else all_assets[0], index=close_prices.index)
        
        # 月末采样点（模拟原始策略的2M调仓周期）
        rebalance_days = rebalance_months * 21
        holding = pd.Series(safe_like[0] if safe_like else all_assets[0], index=close_prices.index)
        
        # 滚动IC历史记录
        ic_history = defaultdict(list)
        factor_history = defaultdict(list)
        return_history = {}
        
        # 记录上一次调仓的评分，用于时序一致性检查
        last_scores = None
        
        for i in range(lookback + 1, len(close_prices)):
            current_date = close_prices.index[i]
            
            # 判断是否到达调仓日（每rebalance_months月末）
            if i > 0:
                prev_date = close_prices.index[i-1]
                # 月末判断：当前月 != 上一个月，且日期间隔足够
                if hasattr(current_date, 'month') and hasattr(prev_date, 'month'):
                    is_month_end = current_date.month != prev_date.month
                else:
                    is_month_end = (i % 21 == 0)
                
                # 检查是否到达双月调仓点
                months_passed = 0
                if is_month_end:
                    months_passed = 1
                    # 简化：每2个月调仓一次
                    if i % (rebalance_days) > 21:  # 不在调仓窗口
                        continue
                else:
                    continue
            else:
                continue
            
            # 计算各ETF因子
            window_data = close_prices.iloc[max(0, i-lookback-10):i+1]
            factors = calculate_etf_factors(window_data, lookback=lookback)
            
            if not factors:
                continue
            
            # 计算过去一期的收益（用于IC计算）
            past_return_window = min(rebalance_days, i)
            current_returns = {}
            for col in all_assets:
                if col in close_prices.columns:
                    s = close_prices[col].iloc[max(0, i-past_return_window):i+1]
                    if len(s) >= 2 and pd.notna(s.iloc[-1]) and pd.notna(s.iloc[0]) and s.iloc[0] > 0:
                        current_returns[col] = s.iloc[-1] / s.iloc[0] - 1
            
            return_history[i] = current_returns
            
            # 记录因子值用于IC计算
            for asset, fdict in factors.items():
                for fname, fval in fdict.items():
                    if not np.isnan(fval):
                        factor_history[fname].append({asset: fval})
            
            # 计算滚动IC（需要至少6期数据）
            if len(return_history) >= 6:
                for fname in factor_history.keys():
                    # 简化IC计算
                    if len(factor_history[fname]) < 6:
                        continue
                    try:
                        f_vals = []
                        r_vals = []
                        for date_idx, rets in return_history.items():
                            for asset, ret in rets.items():
                                # 获取该资产该日期的因子值
                                for fh in factor_history[fname][-20:]:
                                    if asset in fh:
                                        f_vals.append(fh[asset])
                                        r_vals.append(ret)
                                        break
                        
                        if len(f_vals) >= 10:
                            ic, _ = stats.spearmanr(f_vals, r_vals)
                            if not np.isnan(ic):
                                ic_history[fname].append(ic)
                    except:
                        continue
            
            # 基于IC计算因子权重（模拟不确定性加权）
            factor_weights = {}
            for fname in factor_history.keys():
                if fname in ic_history and len(ic_history[fname]) >= 3:
                    mean_ic = np.mean([abs(x) for x in ic_history[fname]])
                    if mean_ic > ic_threshold:
                        factor_weights[fname] = mean_ic  # IC越大权重越高
            
            # 对每个资产计算综合评分
            asset_scores = {}
            for asset, fdict in factors.items():
                # 波动率过滤（模拟Focal Loss的类别不平衡处理）
                if use_vol_filter:
                    vol_key = 'volatility_20'
                    if vol_key in fdict and not np.isnan(fdict[vol_key]):
                        if fdict[vol_key] > vol_threshold:
                            # 高波动率资产降权（类似Focal Loss对困难样本降权）
                            asset_scores[asset] = multi_factor_score(fdict, factor_weights) * 0.5
                            continue
                
                asset_scores[asset] = multi_factor_score(fdict, factor_weights)
            
            if not asset_scores:
                continue
            
            # 时序一致性检查（模拟早停机制 - 避免信号剧烈翻转）
            if last_scores is not None:
                # 检查评分变化是否过大
                score_change = 0
                common_assets = set(asset_scores.keys()) & set(last_scores.keys())
                if len(common_assets) > 0:
                    changes = [abs(asset_scores.get(a, 0) - last_scores.get(a, 0)) for a in common_assets]
                    avg_change = np.mean(changes) if changes else 0
                    # 如果变化太大，只取前1/3权重更新（平滑处理）
                    if avg_change > 0.5:
                        for a in common_assets:
                            asset_scores[a] = 0.7 * last_scores[a] + 0.3 * asset_scores[a]
            
            last_scores = asset_scores.copy()
            
            # 选择评分最高的风险资产
            risk_scores = {a: s for a, s in asset_scores.items() 
                          if a in risk_like and s > 0}
            
            if risk_scores:
                # 绝对动量过滤（评分>0才持有风险资产）
                best_asset = max(risk_scores, key=risk_scores.get)
                
                # 额外安全检查：如果最佳资产近期回撤过大，持有安全资产
                best_series = close_prices[best_asset].iloc[max(0, i-20):i+1]
                if len(best_series) >= 2:
                    recent_dd = (best_series.iloc[-1] - best_series.max()) / best_series.max()
                    if recent_dd < -0.15:  # 近期回撤超15%，暂时避险
                        best_asset = safe_like[0] if safe_like else all_assets[0]
            else:
                # 无正评分风险资产，持有安全资产
                best_asset = safe_like[0] if safe_like else all_assets[0]
            
            # 设置持仓（从当前日到下次调仓日）
            # 找到下次调仓日
            next_rebalance = min(i + rebalance_days, len(close_prices) - 1)
            mask = (close_prices.index > current_date) & (close_prices.index <= close_prices.index[next_rebalance])
            holding.loc[mask] = best_asset
            # 当日也设置
            holding.loc[current_date] = best_asset
        
        return holding
    
    return strategy_func


# ============================================================
# 主函数：执行三层递进回测
# ============================================================

if __name__ == '__main__':
    from cross_regime_scheduler import backtest_user_strategy
    
    # 构造策略函数
    strategy_func = make_multitask_etf_strategy(
        ic_threshold=0.02,
        rebalance_months=2,
        lookback=60,
        top_k=1,
        use_vol_filter=True,
        vol_threshold=0.25
    )
    
    # 策略参数
    strategy_params = {
        'ic_threshold': 0.02,
        'rebalance_months': 2,
        'lookback_days': 60,
        'top_k': 1,
        'use_vol_filter': True,
        'vol_threshold': 0.25,
        'factor_count': 18,  # 计算了18个因子
        'model_type': 'IC加权多因子评分（模拟MultiTaskNetV2）',
        'improvements': [
            'IC滚动筛选有效因子',
            'IC加权替代不确定性加权',
            '波动率过滤替代Focal Loss',
            '时序一致性平滑替代早停',
            '绝对动量过滤',
        ]
    }
    
    # 执行回测
    result = backtest_user_strategy(
        strategy_func=strategy_func,
        strategy_name='修复优化版多任务量化选股模型',
        strategy_kwargs={'market_scope': ['US', 'HK', 'CN']},
        strategy_type='机器学习',
        strategy_params=strategy_params,
        strategy_desc='基于JoinQuant多因子+深度学习选股模型的ETF适配版。核心思想：'
                      '1) IC筛选有效因子 → 滚动IC测试保留预测力强的因子；'
                      '2) 多任务网络评分 → IC加权多因子综合评分；'
                      '3) Focal Loss不平衡处理 → 波动率过滤+降权；'
                      '4) 不确定性加权 → IC值自适应权重；'
                      '5) 时序严格划分 → 滚动窗口避免未来函数；'
                      '6) 早停机制 → 时序一致性平滑防止信号翻转；'
                      '7) 因子持久化 → IC历史记录支持增量更新',
        source='🖥️本地'
    )
    
    # 输出结果摘要
    print(f"\n{'='*70}")
    print(f"  📊 回测结果摘要")
    print(f"{'='*70}")
    
    if result.get('passed'):
        print(f"  ✅ 策略通过三层递进回测！")
        print(f"  🏆 最终评分: {result.get('final_score', 'N/A')}")
        print(f"  📈 等级: {result.get('grade', 'N/A')}")
        
        # 各市场结果
        for market in ['US', 'HK', 'CN']:
            market_result = result.get(f'{market.lower()}_result', {})
            if market_result:
                print(f"\n  🌍 {market}市场:")
                print(f"     年化收益: {market_result.get('annual_return', 'N/A')}")
                print(f"     夏普比率: {market_result.get('sharpe', 'N/A')}")
                print(f"     最大回撤: {market_result.get('max_drawdown', 'N/A')}")
                print(f"     盈亏比: {market_result.get('profit_factor', 'N/A')}")
                print(f"     胜率: {market_result.get('win_rate', 'N/A')}")
                print(f"     评分: {market_result.get('score', 'N/A')}")
    else:
        print(f"  ❌ 策略未通过回测")
        print(f"  淘汰层级: {result.get('eliminated_at', 'N/A')}")
        print(f"  淘汰原因: {result.get('reason', 'N/A')}")
        
        # L1快速结果
        market_quick = result.get('market_quick', {})
        if market_quick:
            print(f"\n  L1快速广筛结果:")
            for market, mdata in market_quick.items():
                print(f"    {market}: {mdata}")
    
    total_time = result.get('total_time', 0)
    print(f"\n  ⏱️ 总耗时: {total_time:.1f}s")
    print(f"{'='*70}")
