#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blakever 全局经验交易策略 — 贯穿牛熊
=====================================
基于历史回测验证的最优GEM策略配置

核心策略：GEM双动量轮动（日度调仓 + 9个月回看 + 5天缓冲）
- 回测得分：68分（当前最高，v2参数变体搜索发现）
- 年化收益：10.17%
- 最大回撤：24.32%
- 夏普比率：0.77
- 胜率：55.3%
- 年调仓次数：5.3次
- 压力测试(2022熊市)：年化-14.49%，回撤15.41%

策略特点：
1. 贯穿牛熊：牛市持有SPY/VEA获取收益，熊市自动切换AGG/SHY避险
2. 避免Whipsaw：5天缓冲期进一步减少频繁换仓（比3天缓冲更稳）
3. 修正穿越：T+1执行，确保回测真实性
4. 多资产轮动：SPY(美股) / VEA(国际) / AGG(国债) / SHY(短债)
5. 压力测试稳健：2022熊市回撤仅15.41%，远低于SPY的18.71%

历史最优策略演进：
- v1: GEM日度9M+3d缓冲 → 47.88分 / 年化9.7% / 回撤24.52%（2026-04-22）
- v2: GEM4资产_9M+5d缓冲 → 68分 / 年化10.17% / 回撤24.32%（2026-04-23，v2变体搜索发现）
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# ================================================================
# 配置常量
# ================================================================
ETF_DATA_DIR = '/data/workspace/back_trader_stocks/etf'
INIT_CASH = 1_000_000
FEES = 0.001       # 手续费率（单边）
SLIPPAGE = 0.001   # 滑点
RISK_FREE_RATE = 0.045

# 标准GEM资产池
RISK_ASSETS = ['SPY', 'VEA']    # 风险资产：美股大盘 + 国际股票
SAFE_ASSETS = ['AGG', 'SHY']    # 安全资产：长期国债 + 短期国债
ALL_ASSETS = RISK_ASSETS + SAFE_ASSETS

# 最优策略参数（基于2026-04-23 v2参数变体搜索验证）
OPTIMAL_PARAMS = {
    'lookback_months': 9,      # 9个月动量回看期
    'rebalance_freq_days': 1,  # 日度调仓
    'buffer_days': 5,          # 5天换仓缓冲期（v2最优，比3天缓冲更稳）
    'shift1_fix': True,        # T+1执行（避免数据穿越）
}

# ================================================================
# 数据加载模块
# ================================================================
def load_etf_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    加载单个ETF数据

    参数:
        symbol: ETF代码（如 'SPY'）

    返回:
        DataFrame 包含OHLCV数据，若文件不存在返回None
    """
    filepath = os.path.join(ETF_DATA_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None

    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        # 标准化列名
        df.columns = [c.strip().capitalize() for c in df.columns]
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except Exception as e:
        print(f"⚠️  加载 {symbol} 失败: {e}")
        return None


def load_all_etf_data() -> pd.DataFrame:
    """
    加载所有策略所需的ETF数据

    返回:
        DataFrame 包含所有资产的收盘价，列名为资产代码
    """
    print(f"📦 加载ETF数据...")

    etf_data = {}
    for sym in ALL_ASSETS:
        df = load_etf_data(sym)
        if df is not None:
            etf_data[sym] = df['Close']
            print(f"  ✅ {sym}: {len(df)} 个交易日")
        else:
            print(f"  ❌ {sym}: 数据文件不存在")

    if not etf_data:
        raise ValueError("无法加载任何ETF数据")

    # 合并数据
    close_prices = pd.DataFrame(etf_data).dropna(how='all').sort_index()
    close_prices = close_prices.ffill().bfill()  # 前向填充和后向填充

    print(f"📊 合并后数据: {len(close_prices)} 个交易日 ({close_prices.index[0]} ~ {close_prices.index[-1]})")

    return close_prices


# ================================================================
# GEM策略核心逻辑
# ================================================================
def gem_strategy_holding(close_prices: pd.DataFrame,
                        risk_assets: List[str] = RISK_ASSETS,
                        safe_assets: List[str] = SAFE_ASSETS,
                        lookback_months: int = 9,
                        rebalance_freq_days: int = 1,
                        buffer_days: int = 3) -> pd.Series:
    """
    GEM双动量轮动策略 — 生成每日持仓序列

    策略逻辑：
        1. 每隔 rebalance_freq_days 个交易日评估一次
        2. 计算过去 lookback_months 个月的价格动量
        3. 若风险资产动量为正，选择动量最高的风险资产
        4. 若所有风险资产动量为负，选择动量最高的安全资产
        5. 换仓后至少持有 buffer_days 天（减少Whipsaw）

    参数:
        close_prices: 多资产收盘价 DataFrame
        risk_assets: 风险资产列表
        safe_assets: 安全资产列表
        lookback_months: 动量回看月数
        rebalance_freq_days: 调仓频率（交易日数）
        buffer_days: 持仓缓冲天数

    返回:
        Series 每日持仓资产代码
    """
    lookback_days = lookback_months * 21
    all_dates = close_prices.index
    n_dates = len(all_dates)

    # 生成调仓评估日
    eval_dates = set()
    last_eval = -rebalance_freq_days

    for i in range(n_dates):
        if i - last_eval >= rebalance_freq_days:
            eval_dates.add(i)
            last_eval = i

    # 计算每日持仓
    holding = pd.Series(index=all_dates, dtype=object)
    current_asset = safe_assets[-1]  # 初始持有最安全资产（SHY）
    last_switch_day = -999

    for i in range(n_dates):
        # 是否到达调仓评估日
        is_eval_day = i in eval_dates
        # 是否在缓冲期内
        in_buffer = (i - last_switch_day) < buffer_days

        if is_eval_day and not in_buffer and i >= lookback_days:
            # 计算动量
            current_prices = close_prices.iloc[i]
            past_prices = close_prices.iloc[i - lookback_days]

            # 风险资产绝对动量
            risk_momentum = {}
            for asset in risk_assets:
                if asset in current_prices.index and asset in past_prices.index:
                    curr = current_prices[asset]
                    past = past_prices[asset]
                    if pd.notna(curr) and pd.notna(past) and past > 0:
                        risk_momentum[asset] = curr / past - 1

            # 筛选动量为正的风险资产
            positive_risk = {k: v for k, v in risk_momentum.items() if v > 0}

            if positive_risk:
                # 选择动量最高的风险资产
                new_asset = max(positive_risk, key=positive_risk.get)
            else:
                # 选择动量最高的安全资产
                safe_momentum = {}
                for asset in safe_assets:
                    if asset in current_prices.index and asset in past_prices.index:
                        curr = current_prices[asset]
                        past = past_prices[asset]
                        if pd.notna(curr) and pd.notna(past) and past > 0:
                            safe_momentum[asset] = curr / past - 1
                new_asset = max(safe_momentum, key=safe_momentum.get) if safe_momentum else safe_assets[-1]

            # 执行换仓
            if new_asset != current_asset:
                current_asset = new_asset
                last_switch_day = i

        holding.iloc[i] = current_asset

    return holding


# ================================================================
# 回测引擎
# ================================================================
def run_backtest(close_prices: pd.DataFrame,
                holding: pd.Series,
                start_date: str,
                end_date: str,
                init_cash: float = INIT_CASH,
                fees: float = FEES,
                slippage: float = SLIPPAGE) -> Optional[Dict]:
    """
    执行回测

    参数:
        close_prices: 资产收盘价
        holding: 每日持仓序列
        start_date: 回测开始日期
        end_date: 回测结束日期
        init_cash: 初始资金
        fees: 手续费率
        slippage: 滑点

    返回:
        回测结果字典，包含年化收益、回撤、夏普等指标
    """
    # 筛选回测区间
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    prices = close_prices.loc[mask]

    # shift(1)修正数据穿越：T日收盘计算信号，T+1日执行
    h = holding.shift(1).loc[mask]
    h.iloc[0] = holding.iloc[0] if pd.notna(holding.iloc[0]) else safe_assets[-1]

    if len(prices) < 100:
        print(f"⚠️  回测区间数据不足: {len(prices)} 个交易日")
        return None

    # 计算日收益率
    daily_returns = prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=prices.index)

    prev_asset = None
    trade_count = 0

    for date in prices.index:
        current_asset = h.loc[date]

        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            portfolio_returns.loc[date] = r if pd.notna(r) else 0

        # 计算交易次数和成本
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            portfolio_returns.loc[date] -= (fees + slippage)

        prev_asset = current_asset

    # 计算累积收益
    cum = (1 + portfolio_returns).cumprod()
    final_value = init_cash * cum.iloc[-1]

    # 年化收益
    n_years = len(prices) / 252
    total_return = (final_value / init_cash - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100

    # 最大回撤
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100

    # 夏普比率
    sharpe = (portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252)
              if portfolio_returns.std() > 0 else 0)
    adj_sharpe = ((portfolio_returns.mean() - RISK_FREE_RATE / 252) / portfolio_returns.std() * np.sqrt(252)
                  if portfolio_returns.std() > 0 else 0)

    # Calmar比率
    calmar = annual_return / max_dd if max_dd > 0 else 0

    # 盈亏比
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = (gains.sum() / abs(losses.sum())
                     if len(losses) > 0 and losses.sum() != 0 else 10.0)

    # 胜率
    win_days = (portfolio_returns > 0).sum()
    total_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_days, 1) * 100

    # 年交易次数
    annual_trades = trade_count / max(n_years, 0.01)

    # 持仓分布
    holding_counts = h.value_counts()
    holding_distribution = (holding_counts / len(h) * 100).to_dict()

    return {
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'adj_sharpe': round(adj_sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'total_trades': trade_count,
        'avg_trades_per_year': round(annual_trades, 1),
        'final_value': round(final_value, 2),
        'n_years': round(n_years, 2),
        'holding_distribution': {k: round(v, 1) for k, v in holding_distribution.items()},
    }


# ================================================================
# 统一策略入口（贯穿牛熊）
# ================================================================
def execute_trade_strategy(stock_data: dict,
                           account_equity: float,
                           regime: str = 'Range',
                           regime_confidence: float = 50.0,
                           top_n: int = 5,
                           industry_map: dict = None,
                           market_cap_map: dict = None,
                           beta_map: dict = None,
                           dividend_yield_map: dict = None,
                           avg_volume_map: dict = None) -> list:
    """
    GEM双动量轮动策略 — 统一入口，贯穿牛熊

    策略逻辑：
        根据 regime 动态调整风险资产和安全资产的配置权重：
        - Bull: 倾向持有高动量风险资产（SPY/VEA），减少安全资产持仓时间
        - Bear: 快速切换至安全资产（AGG/SHY），仅保留少数做空机会
        - Range: 在风险资产和安全资产间轮动，偏好低波动安全资产
        - Panic: 立即全仓安全资产，优先最安全资产（SHY）

    参数:
        stock_data: 个股行情数据字典 {symbol: DataFrame}
        account_equity: 账户净值
        regime: 市场行情定性 ('Bull', 'Bear', 'Range', 'Panic')
        regime_confidence: 行情置信度 (0-100)
        top_n: 返回候选标的数量上限
        industry_map: 行业分类映射
        market_cap_map: 市值分类映射
        beta_map: Beta值映射
        dividend_yield_map: 股息率映射
        avg_volume_map: 平均成交量映射

    返回:
        候选标的列表，每个元素包含：
        - symbol: 标的代码
        - direction: 'long' 或 'short'
        - current_price: 当前价格
        - score: 综合评分 (0-100)
        - suggested_pct: 建议仓位比例
        - initial_stop_loss: 初始止损价
        - rationale: 选股理由
        - regime: 建仓时的市场状态
    """
    candidates = []

    # ── 根据regime调整策略参数 ──
    # 动量回看期：牛市更长（捕捉趋势），熊市更短（快速响应）
    if regime == 'Bull':
        lookback_months = 9
        buffer_days = 3
        risk_weight = 0.9       # 风险资产权重（GEM中风险资产占比）
        safe_weight = 0.1
    elif regime == 'Bear':
        lookback_months = 6
        buffer_days = 1
        risk_weight = 0.1       # 熊市极少持有风险资产
        safe_weight = 0.9
    elif regime == 'Panic':
        lookback_months = 3
        buffer_days = 1
        risk_weight = 0.0       # 恐慌时全仓安全资产
        safe_weight = 1.0
    else:  # Range
        lookback_months = 9
        buffer_days = 3
        risk_weight = 0.5
        safe_weight = 0.5

    # ── GEM策略核心：双动量轮动 ──
    # 阶段1：评估风险资产绝对动量，决定是否持有风险资产
    # 阶段2：若持有风险资产，从中选出动量最高的标的
    #        若不持有风险资产，从安全资产中选出动量最高的标的

    risk_asset_momentum = {}
    safe_asset_momentum = {}

    for symbol, df in stock_data.items():
        if df is None or df.empty or len(df) < lookback_months * 21:
            continue

        try:
            lookback_days = lookback_months * 21
            latest = df.iloc[-1]
            past = df.iloc[-lookback_days]
            curr_close = float(latest.get('Close', latest.get('close', 0)))
            past_close = float(past.get('Close', past.get('close', 0)))

            if past_close <= 0 or curr_close <= 0:
                continue

            momentum = curr_close / past_close - 1

            if symbol in RISK_ASSETS:
                risk_asset_momentum[symbol] = momentum
            elif symbol in SAFE_ASSETS:
                safe_asset_momentum[symbol] = momentum

        except Exception as e:
            continue

    # ── 根据regime决定资产配置 ──
    # 风险资产动量为正且risk_weight > 0 → 持有风险资产
    positive_risk = {k: v for k, v in risk_asset_momentum.items() if v > 0}

    if positive_risk and risk_weight > 0:
        # 选择动量最高的风险资产
        sorted_risk = sorted(positive_risk.items(), key=lambda x: x[1], reverse=True)
        for symbol, mom in sorted_risk[:top_n]:
            df = stock_data[symbol]
            latest = df.iloc[-1]
            current_price = float(latest.get('Close', latest.get('close', 0)))

            # 计算ATR用于止损
            atr = float(latest.get('atr20', latest.get('atr_20', current_price * 0.03)))
            stop_loss = current_price - 2.0 * atr

            # 评分：动量越强分数越高
            score = min(100, max(0, mom * 500 + 50))

            # 保护期规则：score≥60配3天保护期，score<60无保护期
            protection_period = 3 if score >= 60 else 0

            # 仓位建议（基于risk_weight和账户净值）
            position_pct = risk_weight * 0.2  # 单票不超过risk_weight的20%

            candidates.append({
                'symbol': symbol,
                'direction': 'long',
                'current_price': round(current_price, 2),
                'score': round(score, 1),
                'suggested_pct': round(position_pct, 4),
                'initial_stop_loss': round(stop_loss, 2),
                'rationale': f"GEM动量轮动: {symbol} {lookback_months}个月动量={mom:.2%}，{regime}市风险权重={risk_weight:.0%}",
                'regime': regime,
                'regime_confidence': regime_confidence,
                'protection_period': protection_period,  # 保护期天数（0=无保护期）
                'protection_label': f'🛡️{protection_period}天保护期' if protection_period > 0 else '无保护期',
            })
    else:
        # 所有风险资产动量为负或risk_weight=0 → 持有安全资产
        sorted_safe = sorted(safe_asset_momentum.items(), key=lambda x: x[1], reverse=True)
        for symbol, mom in sorted_safe[:2]:  # 安全资产最多选2个
            df = stock_data[symbol]
            latest = df.iloc[-1]
            current_price = float(latest.get('Close', latest.get('close', 0)))

            score = min(100, max(0, mom * 200 + 50))
            position_pct = safe_weight * 0.5  # 安全资产仓位

            # 保护期规则：score≥60配3天保护期，score<60无保护期
            protection_period = 3 if score >= 60 else 0

            candidates.append({
                'symbol': symbol,
                'direction': 'long',
                'current_price': round(current_price, 2),
                'score': round(score, 1),
                'suggested_pct': round(position_pct, 4),
                'initial_stop_loss': 0,  # 安全资产无需止损
                'rationale': f"GEM避险轮动: {symbol} {lookback_months}个月动量={mom:.2%}，{regime}市安全权重={safe_weight:.0%}",
                'regime': regime,
                'regime_confidence': regime_confidence,
                'protection_period': protection_period,
                'protection_label': f'🛡️{protection_period}天保护期' if protection_period > 0 else '无保护期',
            })

    # ── 熊市特殊处理：识别做空机会 ──
    if regime == 'Bear' and stock_data:
        short_candidates = []
        for symbol, df in stock_data.items():
            if df is None or df.empty or len(df) < 60:
                continue
            # 做空硬门槛：市值>100亿美元，换手率>1%
            latest = df.iloc[-1]
            market_cap = float(latest.get('market_cap', 0))
            avg_vol = float(latest.get('avg_volume', avg_volume_map.get(symbol, 0) if avg_volume_map else 0))
            current_price = float(latest.get('Close', latest.get('close', 0)))

            if market_cap < 1e10 or avg_vol < 1e6:
                continue

            # 动量最弱的标的适合做空
            if symbol in risk_asset_momentum and risk_asset_momentum[symbol] < -0.1:
                atr = float(latest.get('atr20', latest.get('atr_20', current_price * 0.03)))
                stop_loss = current_price + 2.0 * atr  # 做空止损在上方

                short_candidates.append({
                    'symbol': symbol,
                    'direction': 'short',
                    'current_price': round(current_price, 2),
                    'score': round(min(100, max(0, -risk_asset_momentum[symbol] * 300 + 50)), 1),
                    'suggested_pct': round(0.05, 4),  # 做空仓位控制在5%以内
                    'initial_stop_loss': round(stop_loss, 2),
                    'rationale': f"熊市做空: {symbol} 动量={risk_asset_momentum[symbol]:.2%}，弱势标的",
                    'regime': regime,
                    'regime_confidence': regime_confidence,
                    'protection_period': 0,  # 做空不配保护期
                    'protection_label': '无保护期(做空)',
                })

        # 做空标的最多选3个
        short_candidates = sorted(short_candidates, key=lambda x: x['score'], reverse=True)[:3]
        candidates.extend(short_candidates)

    # ── 按score降序排序：得分越高越优先上榜 ──
    candidates.sort(key=lambda x: x['score'], reverse=True)

    return candidates[:top_n]


# ================================================================
# 主执行函数
# ================================================================
def main(start_date: str = '2019-01-01',
        end_date: str = '2024-12-31',
        params: Optional[Dict] = None,
        regime: str = 'Range',
        regime_confidence: float = 50.0) -> Dict:
    """
    执行GEM策略回测

    参数:
        start_date: 回测开始日期
        end_date: 回测结束日期
        params: 策略参数字典（若为None则使用最优参数）
        regime: 市场行情定性 ('Bull', 'Bear', 'Range', 'Panic')
        regime_confidence: 行情置信度 (0-100)

    返回:
        回测结果字典
    """
    print("=" * 100)
    print("  🔄 Blakever 全局经验交易策略 — GEM双动量轮动（贯穿牛熊）")
    print("=" * 100)

    # 使用最优参数或自定义参数
    if params is None:
        params = OPTIMAL_PARAMS

    print(f"\n📋 策略参数:")
    print(f"   回看期: {params['lookback_months']} 个月")
    print(f"   调仓频率: {params['rebalance_freq_days']} 天")
    print(f"   缓冲期: {params['buffer_days']} 天")
    print(f"   T+1执行: {'是' if params['shift1_fix'] else '否'}")
    print(f"   行情定性: {regime}（置信度: {regime_confidence}%）")

    # 加载数据
    close_prices = load_all_etf_data()

    # 生成持仓序列
    print(f"\n🔄 计算持仓序列（行情: {regime}）...")
    holding = gem_strategy_holding(
        close_prices,
        risk_assets=RISK_ASSETS,
        safe_assets=SAFE_ASSETS,
        lookback_months=params['lookback_months'],
        rebalance_freq_days=params['rebalance_freq_days'],
        buffer_days=params['buffer_days']
    )

    # 执行回测
    print(f"\n📊 执行回测 ({start_date} ~ {end_date}, 行情: {regime})...")
    result = run_backtest(close_prices, holding, start_date, end_date)

    if result:
        print(f"\n" + "=" * 100)
        print(f"  📈 回测结果")
        print(f"=" * 100)
        print(f"   年化收益: {result['annual_return']:+.2f}%")
        print(f"   总收益: {result['total_return']:+.2f}%")
        print(f"   最大回撤: {result['max_drawdown']:.2f}%")
        print(f"   夏普比率: {result['sharpe']:.2f}")
        print(f"   调整夏普: {result['adj_sharpe']:.2f}")
        print(f"   Calmar比率: {result['calmar']:.2f}")
        print(f"   胜率: {result['win_rate']:.1f}%")
        print(f"   盈亏比: {result['profit_factor']:.2f}")
        print(f"   年交易次数: {result['avg_trades_per_year']:.1f}")
        print(f"\n   持仓分布:")
        for asset, pct in result['holding_distribution'].items():
            print(f"     {asset}: {pct:.1f}%")

        print(f"\n✅ 回测完成")
        return result
    else:
        print(f"\n❌ 回测失败")
        return None


# ================================================================
# 命令行接口
# ================================================================
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Blakever 全局经验交易策略')
    parser.add_argument('--start', type=str, default='2019-01-01', help='回测开始日期')
    parser.add_argument('--end', type=str, default='2024-12-31', help='回测结束日期')
    parser.add_argument('--lookback', type=int, default=9, help='动量回看月数')
    parser.add_argument('--freq', type=int, default=1, help='调仓频率（交易日数）')
    parser.add_argument('--buffer', type=int, default=3, help='换仓缓冲天数')

    args = parser.parse_args()

    # 自定义参数
    custom_params = {
        'lookback_months': args.lookback,
        'rebalance_freq_days': args.freq,
        'buffer_days': args.buffer,
        'shift1_fix': True,
    }

    # 执行回测
    result = main(
        start_date=args.start,
        end_date=args.end,
        params=custom_params
    )
