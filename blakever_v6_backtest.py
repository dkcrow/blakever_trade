#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
BlakeverStrategyV6 回测验证
==========================================================================
策略来源: blakever_test_stragegy.py (BlakeverStrategyV6)

核心变化 (V5 → V6):
  1. ✅ ETF 轮动替代单标的择时 — 不再"空仓等信号"，而是"环境切换资产池"
  2. ✅ Risk-On 恢复机制 — Kill Switch 不再锁死，站上EMA50+日线上涨即恢复
  3. ✅ 熊市不再空仓 — 分配 TLT(50%)+GLD(30%)+SH(20%) 防守
  4. ✅ Bullish Alpha叠加 — 在ETF仓位基础上叠加20%个股Alpha

资产配置方案:
  Bullish : SPY(60%) + GLD(10%) + Alpha(30%)
  Sideways: SPY(40%) + GLD(30%) + TLT(30%)
  Bearish : TLT(50%) + GLD(30%) + SH(20%)  ← SH用IEF替代
  Risk-Off: TLT(50%) + GLD(30%) + SH(20%)

数据适配 (本地CSV):
  QQQ → SPY (无QQQ数据，用SPY近似)
  TLT → TLT (直接可用)
  GLD → GLD (直接可用)
  SH  → IEF (无SH数据，用7-10年国债ETF替代现金防守)

框架: VectorBT 0.28.5 + TA-Lib 0.6.8 (手动组合权重回测)
==========================================================================
"""

import os
import warnings
import json
from datetime import datetime

import numpy as np
import pandas as pd
import talib

warnings.filterwarnings('ignore')

# ================================================================
# 全局配置
# ================================================================
INIT_CASH = 1_000_000
FEES_US = 0.000528
FEES_HK = 0.001348
SLIPPAGE = 0.001
DATA_DIR = '/data/workspace/back_trader_stocks'

MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'

# Alpha股票池 (用于Bullish Alpha叠加)
ALPHA_POOL = ['AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'AVGO', 'CRM', 'AMD', 'ADBE']

# 无风险利率
RISK_FREE_RATE = 0.045


# ================================================================
# 数据加载
# ================================================================
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().capitalize() for c in df.columns]
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date').sort_index()
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['Close'])
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df['Close'].values.astype(float)
    high = df['High'].values.astype(float)
    low = df['Low'].values.astype(float)
    volume = df['Volume'].values.astype(float) if 'Volume' in df.columns else None

    df['ema20'] = talib.EMA(close, timeperiod=20)
    df['ema50'] = talib.EMA(close, timeperiod=50)
    df['ema200'] = talib.EMA(close, timeperiod=200)
    df['adx14'] = talib.ADX(high, low, close, timeperiod=14)
    df['atr14'] = talib.ATR(high, low, close, timeperiod=14)
    df['return_20d'] = df['Close'].pct_change(20)

    if volume is not None and np.nansum(volume) > 0:
        df['vol_ma20'] = talib.SMA(volume, timeperiod=20)
        df['volume_trend'] = volume / df['vol_ma20']
    else:
        df['volume_trend'] = 1.0

    return df


def load_etf_data(symbols: list, start: str, end: str) -> dict:
    """加载多个ETF数据，按日期对齐"""
    data = {}
    for sym in symbols:
        path = os.path.join(DATA_DIR, 'etf', f'{sym}.csv')
        if not os.path.exists(path):
            # 尝试美股目录
            path = os.path.join(DATA_DIR, 'us', f'{sym}.csv')
        if not os.path.exists(path):
            print(f"  ⚠️ {sym} 数据不存在，跳过")
            continue
        df = load_csv(path)
        mask = (df.index >= start) & (df.index <= end)
        df = df[mask]
        if len(df) < 200:
            print(f"  ⚠️ {sym} 数据不足({len(df)}天)，跳过")
            continue
        data[sym] = df
        print(f"  ✅ {sym}: {len(df)} 天 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    # 对齐所有ETF的日期索引
    if data:
        common_idx = data[symbols[0]].index
        for sym in data:
            common_idx = common_idx.intersection(data[sym].index)
        for sym in data:
            data[sym] = data[sym].loc[common_idx]

    return data


# ================================================================
# 策略V6 核心逻辑
# ================================================================
class BlakeverV6Backtest:
    """将 BlakeverStrategyV6 适配为可回测的组合权重引擎"""

    # 资产配置方案 (ETF → 本地数据映射)
    ALLOCATION = {
        "Bullish": {"SPY": 0.60, "GLD": 0.10},  # Alpha 30% 叠加
        "Sideways": {"SPY": 0.40, "GLD": 0.30, "TLT": 0.30},
        "Bearish": {"TLT": 0.50, "GLD": 0.30, "IEF": 0.20},  # IEF替代SH
        "Risk-Off": {"TLT": 0.50, "GLD": 0.30, "IEF": 0.20},  # IEF替代SH
    }

    def __init__(self, spy_data, vix_data, tlt_data, gld_data, ief_data,
                 alpha_pool_data=None):
        self.spy = spy_data
        self.vix = vix_data
        self.tlt = tlt_data
        self.gld = gld_data
        self.ief = ief_data
        self.alpha_pool = alpha_pool_data or {}

        # 状态机
        self.regime = "Sideways"
        self.candidate_regime = None
        self.candidate_days = 0
        self.kill_switch = False

        # 配置
        self.persistence_threshold = 3
        self.vix_threshold = 25.0
        self.vix_spike_ratio = 0.15
        self.adx_sideways = 20.0
        self.trend_strength_threshold = 0.015

    def _update_regime_state(self, target_regime):
        """Hysteresis 状态机"""
        if target_regime == self.regime:
            self.candidate_regime = None
            self.candidate_days = 0
        else:
            if target_regime == self.candidate_regime:
                self.candidate_days += 1
            else:
                self.candidate_regime = target_regime
                self.candidate_days = 1
            if self.candidate_days >= self.persistence_threshold:
                self.regime = target_regime
                self.candidate_regime = None
                self.candidate_days = 0

    def update_market_regime(self, i: int):
        """
        基于T-1数据更新市场环境判定 (V6 新增 Risk-On 恢复)
        i: 当前日期索引 (用 i-1 获取T-1数据)
        """
        if i < 6:
            return self.regime

        spy = self.spy
        vix = self.vix

        t1_close = spy['Close'].iloc[i - 1]
        t2_close = spy['Close'].iloc[i - 2]
        t5_close = spy['Close'].iloc[i - 5]

        t1_ema50 = spy['ema50'].iloc[i - 1]
        t1_ema200 = spy['ema200'].iloc[i - 1]
        t1_adx = spy['adx14'].iloc[i - 1]

        vix_t1 = vix['Close'].iloc[i - 1]
        vix_t5 = vix['Close'].iloc[i - 5]

        # Kill Switch 检测
        daily_ret = (t1_close - t2_close) / t2_close if t2_close != 0 else 0
        three_ret = (t1_close - t5_close) / t5_close if t5_close != 0 else 0
        vix_3d = (vix_t1 - vix_t5) / vix_t5 if vix_t5 != 0 else 0

        if (daily_ret < -0.03 and three_ret < -0.05) or (vix_t1 > self.vix_threshold and vix_3d > self.vix_spike_ratio):
            self.kill_switch = True
            return "Risk-Off"

        # ✅ V6 新增: Risk-On 恢复机制
        if self.kill_switch:
            if t1_close > t1_ema50 and (t1_close - t2_close) > 0:
                self.kill_switch = False

        # 环境判定
        if np.isnan(t1_adx):
            t1_adx = 0

        trend_strength = abs(t1_ema50 - t1_ema200) / t1_ema200 if t1_ema200 != 0 and not np.isnan(t1_ema200) else 0

        target = "Bearish"
        if t1_adx < self.adx_sideways and trend_strength < self.trend_strength_threshold:
            target = "Sideways"
        elif t1_close > t1_ema200 and t1_ema50 > t1_ema200:
            target = "Bullish"

        self._update_regime_state(target)
        return self.regime

    def get_asset_allocation(self, regime: str, alpha_stocks=None) -> dict:
        """
        生成资产配置权重 (V6核心)
        Bullish时叠加Alpha
        """
        weights = self.ALLOCATION.get(regime, self.ALLOCATION["Sideways"]).copy()

        # ✅ Bullish Alpha叠加
        if regime == "Bullish" and not self.kill_switch and alpha_stocks:
            alpha_weight = 0.30  # V6: 30% Alpha
            per_stock = alpha_weight / len(alpha_stocks) if alpha_stocks else 0

            for sym in alpha_stocks:
                weights[sym] = per_stock

            # 从 SPY 扣除
            if "SPY" in weights:
                weights["SPY"] = max(0.10, weights["SPY"] - alpha_weight)

        return weights

    def select_alpha_stocks(self, i: int) -> list:
        """
        多因子选股 (ADX + 动量 + 量能)
        返回 Top3 股票代码
        """
        if not self.alpha_pool:
            return []

        scored = []
        for sym, df in self.alpha_pool.items():
            if i < 20 or i >= len(df):
                continue
            adx = df['adx14'].iloc[i - 1] if not np.isnan(df['adx14'].iloc[i - 1]) else 0
            mom = df['return_20d'].iloc[i - 1] if not np.isnan(df['return_20d'].iloc[i - 1]) else 0
            vol = df['volume_trend'].iloc[i - 1] if not np.isnan(df['volume_trend'].iloc[i - 1]) else 1.0

            score = 0.4 * min(1, adx / 60) + 0.4 * min(1, mom / 0.15) + 0.2 * (1 if vol > 1 else 0.5)
            scored.append((sym, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:3]]


# ================================================================
# 组合权重回测引擎
# ================================================================
def run_portfolio_backtest(engine: BlakeverV6Backtest, all_data: dict,
                           start_date: str, end_date: str,
                           fees=FEES_US, rebalance_freq='W') -> dict:
    """
    组合权重回测: 每周/每天调仓，按权重分配资金

    rebalance_freq: 'D'(每日), 'W'(每周), 'M'(每月)
    """
    spy = engine.spy

    # 回测区间
    mask = (spy.index >= start_date) & (spy.index <= end_date)
    dates = spy[mask].index

    if len(dates) < 200:
        return {'状态': '数据不足'}

    # 初始化
    cash = INIT_CASH
    holdings = {}  # symbol -> shares
    portfolio_values = []
    weights_history = []
    regime_history = []

    # 上次调仓日期
    last_rebalance = None

    for idx_pos, date in enumerate(dates):
        i = spy.index.get_loc(date)

        # 1. 更新市场环境
        regime = engine.update_market_regime(i)

        # 2. 判断是否需要调仓
        need_rebalance = False
        if last_rebalance is None:
            need_rebalance = True
        elif rebalance_freq == 'D':
            need_rebalance = True
        elif rebalance_freq == 'W':
            # 每周一调仓
            if date.weekday() == 0 and date != last_rebalance:
                need_rebalance = True
        elif rebalance_freq == 'M':
            if date.month != last_rebalance.month:
                need_rebalance = True

        # 3. 调仓
        if need_rebalance:
            last_rebalance = date

            # 获取Alpha股票
            alpha_stocks = engine.select_alpha_stocks(i)

            # 获取目标权重
            target_weights = engine.get_asset_allocation(regime, alpha_stocks)

            # 清算当前持仓
            for sym, shares in holdings.items():
                if sym in all_data and date in all_data[sym].index:
                    price = all_data[sym].loc[date, 'Close']
                    cash += shares * price * (1 - fees - SLIPPAGE)
                else:
                    # 用最近可用价格
                    if sym in all_data:
                        avail = all_data[sym].loc[:date]
                        if len(avail) > 0:
                            price = avail.iloc[-1]['Close']
                            cash += shares * price * (1 - fees - SLIPPAGE)
            holdings = {}

            # 按目标权重建仓
            total_weight = sum(target_weights.values())
            if total_weight > 0:
                for sym, weight in target_weights.items():
                    if sym in all_data and date in all_data[sym].index:
                        alloc = cash * (weight / total_weight)
                        price = all_data[sym].loc[date, 'Close']
                        shares = alloc * (1 - fees - SLIPPAGE) / price if price > 0 else 0
                        if shares > 0:
                            holdings[sym] = shares
                            cash -= alloc

            weights_history.append({
                'date': date.strftime('%Y-%m-%d'),
                'regime': regime,
                'weights': {k: round(v, 3) for k, v in target_weights.items()},
                'alpha': alpha_stocks
            })

        regime_history.append(regime)

        # 4. 计算组合价值
        portfolio_value = cash
        for sym, shares in holdings.items():
            if sym in all_data and date in all_data[sym].index:
                price = all_data[sym].loc[date, 'Close']
                portfolio_value += shares * price
            elif sym in all_data:
                avail = all_data[sym].loc[:date]
                if len(avail) > 0:
                    price = avail.iloc[-1]['Close']
                    portfolio_value += shares * price

        portfolio_values.append(portfolio_value)

    # 5. 计算绩效指标
    pv = np.array(portfolio_values)
    returns = np.diff(pv) / pv[:-1]
    returns = np.concatenate([[0], returns])

    total_return = (pv[-1] / pv[0] - 1) * 100 if pv[0] > 0 else 0
    n_years = len(pv) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_return > -100 else -100

    # 最大回撤
    peak = np.maximum.accumulate(pv)
    drawdown = (pv - peak) / peak * 100
    max_dd = abs(drawdown.min())

    # 夏普比率
    daily_rf = RISK_FREE_RATE / 252
    excess_returns = returns - daily_rf
    sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if np.std(excess_returns) > 0 else 0

    # 卡尔马比率
    calmar = annual / max_dd if max_dd > 0 else 0

    # 各环境占比
    regime_arr = np.array(regime_history)
    regime_counts = pd.Series(regime_arr).value_counts()
    regime_pct = {k: round(v / len(regime_arr) * 100, 1) for k, v in regime_counts.items()}

    # 年度收益分解
    pv_series = pd.Series(pv, index=dates)
    yearly_returns = {}
    for year in sorted(pv_series.index.year.unique()):
        year_data = pv_series[pv_series.index.year == year]
        if len(year_data) > 1:
            yr = (year_data.iloc[-1] / year_data.iloc[0] - 1) * 100
            yearly_returns[str(year)] = round(yr, 2)

    return {
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': round(sharpe, 2),
        '卡尔马比率': round(calmar, 2),
        '环境占比': regime_pct,
        '年度收益': yearly_returns,
        '最终权重': weights_history[-1] if weights_history else {},
        'portfolio_values': pv,
        'regime_history': regime_history,
        'dates': dates,
    }


def run_buyhold_portfolio(spy_data, start_date, end_date, fees=FEES_US):
    """Buy & Hold SPY 基准"""
    mask = (spy_data.index >= start_date) & (spy_data.index <= end_date)
    dates = spy_data[mask].index

    pv = spy_data.loc[dates, 'Close'].values.astype(float)
    pv = pv / pv[0] * INIT_CASH

    returns = np.diff(pv) / pv[:-1]
    returns = np.concatenate([[0], returns])

    total_return = (pv[-1] / pv[0] - 1) * 100
    n_years = len(pv) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    peak = np.maximum.accumulate(pv)
    drawdown = (pv - peak) / peak * 100
    max_dd = abs(drawdown.min())

    daily_rf = RISK_FREE_RATE / 252
    excess_returns = returns - daily_rf
    sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if np.std(excess_returns) > 0 else 0

    calmar = annual / max_dd if max_dd > 0 else 0

    yearly_returns = {}
    pv_series = pd.Series(pv, index=dates)
    for year in sorted(pv_series.index.year.unique()):
        year_data = pv_series[pv_series.index.year == year]
        if len(year_data) > 1:
            yr = (year_data.iloc[-1] / year_data.iloc[0] - 1) * 100
            yearly_returns[str(year)] = round(yr, 2)

    return {
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': round(sharpe, 2),
        '卡尔马比率': round(calmar, 2),
        '年度收益': yearly_returns,
        'portfolio_values': pv,
        'dates': dates,
    }


# ================================================================
# 过拟合检测
# ================================================================
def overfit_check_portfolio(engine, all_data, start, end, fees=FEES_US):
    """过拟合检测: 训练集(前70%) vs 测试集(后30%)"""
    spy = engine.spy
    mask = (spy.index >= start) & (spy.index <= end)
    dates = spy[mask].index
    n = len(dates)
    split_date = dates[int(n * 0.7)]

    train_result = run_portfolio_backtest(engine, all_data, start, split_date.strftime('%Y-%m-%d'), fees)
    test_result = run_portfolio_backtest(engine, all_data, split_date.strftime('%Y-%m-%d'), end, fees)

    train_ret = train_result.get('总收益率%', 0)
    test_ret = test_result.get('总收益率%', 0)

    overfit = False
    detail = ""
    if train_ret > 0 and test_ret < train_ret * 0.7:
        overfit = True
        detail = f"测试集收益({test_ret:.2f}%)低于训练集({train_ret:.2f}%)的70%"
    elif train_ret > 0 and test_ret < 0:
        overfit = True
        detail = f"训练集正收益({train_ret:.2f}%)但测试集亏损({test_ret:.2f}%)"
    else:
        detail = f"训练集收益{train_ret:.2f}%，测试集收益{test_ret:.2f}%，未检测到过拟合"

    return {
        'overfit_detected': overfit,
        'train_return': round(train_ret, 2),
        'test_return': round(test_ret, 2),
        'overfit_details': detail
    }


# ================================================================
# 多周期一致性验证
# ================================================================
def consistency_check(all_period_results):
    warnings_list = []
    fail_count = 0

    for period_name, result in all_period_results.items():
        if result.get('状态') == '数据不足':
            continue

        sharpe = result.get('夏普比率', 0)
        max_dd = abs(result.get('最大回撤%', 0))
        annual = result.get('年化收益%', 0)

        if sharpe <= 0.5:
            warnings_list.append(f"{period_name}: 夏普比率{sharpe} ≤ 0.5")
            fail_count += 1
        if max_dd >= 30:
            warnings_list.append(f"{period_name}: 最大回撤{max_dd:.2f}% ≥ 30%")
            fail_count += 1
        if annual <= 0:
            warnings_list.append(f"{period_name}: 年化收益{annual:.2f}% ≤ 0")
            fail_count += 1

    if fail_count == 0:
        verdict = "通过"
    elif fail_count <= 2:
        verdict = "标记警告"
    else:
        verdict = "不予采纳"

    return {
        'passed': fail_count == 0,
        'warnings': warnings_list,
        'verdict': verdict,
        'fail_count': fail_count
    }


# ================================================================
# 打印辅助
# ================================================================
def print_portfolio_result(result, name="BlakeverV6"):
    """打印组合回测结果"""
    if result.get('状态') == '数据不足':
        print(f"  ⚠️ {name}: 数据不足")
        return

    print(f"\n  📊 {name} 绩效:")
    print(f"    总收益率: {result['总收益率%']}%")
    print(f"    年化收益: {result['年化收益%']}%")
    print(f"    最大回撤: {result['最大回撤%']}%")
    print(f"    夏普比率: {result['夏普比率']}")
    print(f"    卡尔马比率: {result['卡尔马比率']}")

    if '环境占比' in result:
        print(f"    环境占比: {result['环境占比']}")

    if '年度收益' in result:
        print(f"    年度收益:")
        for year, ret in result['年度收益'].items():
            status = "🟢" if ret > 0 else "🔴"
            print(f"      {year}: {status} {ret}%")


def print_comparison_table(results_list):
    """打印对比表格"""
    print(f"\n{'━' * 100}")
    header = f"{'策略':<28} {'总收益率':>10} {'年化收益':>10} {'最大回撤':>10} {'夏普':>8} {'卡尔马':>8}"
    print(header)
    print("-" * 100)
    for r in results_list:
        print(f"{r['策略']:<28} {r['总收益率%']:>9.2f}% {r['年化收益%']:>9.2f}% "
              f"{r['最大回撤%']:>9.2f}% {r['夏普比率']:>8.2f} {r['卡尔马比率']:>8.2f}")
    print(f"{'━' * 100}")


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 100)
    print("  🚀 BlakeverStrategyV6 回测验证")
    print("  策略来源: blakever_test_stragegy.py (BlakeverStrategyV6)")
    print("  核心升级: ETF轮动 + Risk-On恢复 + 熊市防守 + Alpha叠加")
    print("  回测框架: 手动组合权重引擎 (每周调仓)")
    print("=" * 100)

    # ================================================================
    # 1. 加载数据
    # ================================================================
    print("\n📥 加载数据...")

    # ETF数据
    etf_symbols = ['SPY', 'TLT', 'GLD', 'IEF', 'VIX']
    etf_data = load_etf_data(etf_symbols, '2018-01-01', '2024-12-31')

    if 'SPY' not in etf_data or 'VIX' not in etf_data:
        print("  ❌ SPY 或 VIX 数据缺失，无法继续")
        return

    # Alpha股票池数据
    print("\n📥 加载Alpha股票池...")
    alpha_data = {}
    for sym in ALPHA_POOL:
        path = os.path.join(DATA_DIR, 'us', f'{sym}.csv')
        if os.path.exists(path):
            df = load_csv(path)
            df = compute_indicators(df)
            # 对齐到SPY日期
            common = df.index.intersection(etf_data['SPY'].index)
            alpha_data[sym] = df.loc[common]
            print(f"  ✅ {sym}: {len(alpha_data[sym])} 天")

    # 合并所有可交易数据
    all_data = {}
    for sym in ['SPY', 'TLT', 'GLD', 'IEF']:
        if sym in etf_data:
            all_data[sym] = etf_data[sym]
    for sym, df in alpha_data.items():
        all_data[sym] = df

    # 为SPY计算指标
    spy = compute_indicators(etf_data['SPY'])

    # ================================================================
    # 2. 多周期回测
    # ================================================================
    periods = {
        '1年': ('2024-01-01', '2024-12-31'),
        '3年': ('2022-01-01', '2024-12-31'),
        '5年': ('2020-01-01', '2024-12-31'),
        '全周期(2019-2024)': ('2019-01-01', '2024-12-31'),
    }

    period_results = {}
    comparison = []

    for period_name, (start, end) in periods.items():
        print(f"\n{'━' * 100}")
        print(f"  📊 回测区间: {period_name} ({start} ~ {end})")
        print(f"{'━' * 100}")

        # 创建策略引擎
        engine = BlakeverV6Backtest(
            spy_data=spy, vix_data=etf_data['VIX'],
            tlt_data=etf_data.get('TLT'), gld_data=etf_data.get('GLD'),
            ief_data=etf_data.get('IEF'), alpha_pool_data=alpha_data
        )

        # V6 策略回测
        v6_result = run_portfolio_backtest(engine, all_data, start, end, FEES_US, 'W')
        print_portfolio_result(v6_result, f"BlakeverV6-{period_name}")

        # B&H 基准
        bh_result = run_buyhold_portfolio(spy, start, end, FEES_US)
        print_portfolio_result(bh_result, f"Buy&Hold SPY-{period_name}")

        # 对比表
        comparison.append({
            '策略': f'V6-{period_name}',
            '总收益率%': v6_result.get('总收益率%', 0),
            '年化收益%': v6_result.get('年化收益%', 0),
            '最大回撤%': v6_result.get('最大回撤%', 0),
            '夏普比率': v6_result.get('夏普比率', 0),
            '卡尔马比率': v6_result.get('卡尔马比率', 0),
        })
        comparison.append({
            '策略': f'B&H-{period_name}',
            '总收益率%': bh_result.get('总收益率%', 0),
            '年化收益%': bh_result.get('年化收益%', 0),
            '最大回撤%': bh_result.get('最大回撤%', 0),
            '夏普比率': bh_result.get('夏普比率', 0),
            '卡尔马比率': bh_result.get('卡尔马比率', 0),
        })

        period_results[period_name] = v6_result

    # ================================================================
    # 3. 对比汇总
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 V6 vs B&H 对比汇总")
    print_comparison_table(comparison)

    # ================================================================
    # 4. V5 vs V6 对比 (全周期)
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 V5 vs V6 升级效果对比 (全周期 2019-2024)")
    print(f"{'━' * 100}")

    full_key = '全周期(2019-2024)'
    if full_key in period_results:
        v6_full = period_results[full_key]
        print(f"\n  V5 (旧版 - 单标的择时):")
        print(f"    年化收益: -1.13%  最大回撤: 19.03%  夏普: -0.14  持仓比例: 28.8%")
        print(f"    问题: 大量空仓错过牛市涨幅，熊市不防守")
        print(f"\n  V6 (新版 - ETF轮动):")
        print(f"    年化收益: {v6_full.get('年化收益%', 0)}%")
        print(f"    最大回撤: {v6_full.get('最大回撤%', 0)}%")
        print(f"    夏普比率: {v6_full.get('夏普比率', 0)}")
        print(f"    卡尔马比率: {v6_full.get('卡尔马比率', 0)}")
        print(f"    环境占比: {v6_full.get('环境占比', {})}")

        if '年度收益' in v6_full:
            print(f"    年度收益:")
            for year, ret in v6_full['年度收益'].items():
                status = "🟢" if ret > 0 else "🔴"
                print(f"      {year}: {status} {ret}%")

    # ================================================================
    # 5. 震荡市专项回测
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 震荡市专项回测 (2021-2023)")
    print(f"{'━' * 100}")

    engine_range = BlakeverV6Backtest(
        spy_data=spy, vix_data=etf_data['VIX'],
        tlt_data=etf_data.get('TLT'), gld_data=etf_data.get('GLD'),
        ief_data=etf_data.get('IEF'), alpha_pool_data=alpha_data
    )
    range_result = run_portfolio_backtest(engine_range, all_data, '2021-01-01', '2023-12-31', FEES_US, 'W')
    print_portfolio_result(range_result, "BlakeverV6-震荡市")

    range_bh = run_buyhold_portfolio(spy, '2021-01-01', '2023-12-31', FEES_US)
    print_portfolio_result(range_bh, "Buy&Hold SPY-震荡市")

    # ================================================================
    # 6. 熊市专项回测
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 熊市专项回测 (2022-2023)")
    print(f"{'━' * 100}")

    engine_bear = BlakeverV6Backtest(
        spy_data=spy, vix_data=etf_data['VIX'],
        tlt_data=etf_data.get('TLT'), gld_data=etf_data.get('GLD'),
        ief_data=etf_data.get('IEF'), alpha_pool_data=alpha_data
    )
    bear_result = run_portfolio_backtest(engine_bear, all_data, '2022-01-01', '2023-12-31', FEES_US, 'W')
    print_portfolio_result(bear_result, "BlakeverV6-熊市")

    bear_bh = run_buyhold_portfolio(spy, '2022-01-01', '2023-12-31', FEES_US)
    print_portfolio_result(bear_bh, "Buy&Hold SPY-熊市")

    # ================================================================
    # 7. 过拟合检测
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 过拟合检测 (全周期 训练集70% vs 测试集30%)")
    print(f"{'━' * 100}")

    engine_of = BlakeverV6Backtest(
        spy_data=spy, vix_data=etf_data['VIX'],
        tlt_data=etf_data.get('TLT'), gld_data=etf_data.get('GLD'),
        ief_data=etf_data.get('IEF'), alpha_pool_data=alpha_data
    )
    of_result = overfit_check_portfolio(engine_of, all_data, '2019-01-01', '2024-12-31', FEES_US)

    of_status = "⚠️ 过拟合" if of_result['overfit_detected'] else "✅ 未检测到过拟合"
    print(f"\n  {of_status}")
    print(f"  训练集收益: {of_result['train_return']}%")
    print(f"  测试集收益: {of_result['test_return']}%")
    print(f"  详情: {of_result['overfit_details']}")

    # ================================================================
    # 8. 多周期一致性验证
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📊 多周期一致性验证")
    print(f"{'━' * 100}")

    cc_result = consistency_check(period_results)
    cc_status = {
        "通过": "✅ 通过",
        "标记警告": "⚠️ 标记警告",
        "不予采纳": "❌ 不予采纳"
    }
    print(f"\n  验证结果: {cc_status.get(cc_result['verdict'], cc_result['verdict'])}")
    if cc_result['warnings']:
        print(f"  警告详情:")
        for w in cc_result['warnings']:
            print(f"    - {w}")

    # ================================================================
    # 9. 最终报告
    # ================================================================
    print(f"\n{'━' * 100}")
    print("  📋 最终报告")
    print(f"{'━' * 100}")

    if full_key in period_results:
        r = period_results[full_key]
        annual = r.get('年化收益%', 0)
        max_dd = abs(r.get('最大回撤%', 0))
        sharpe = r.get('夏普比率', 0)

        recommend = False
        if cc_result['verdict'] != "不予采纳" and not of_result.get('overfit_detected', True):
            if sharpe > 0.5 and annual > 0:
                recommend = True

        print(f"\n  🎯 推荐建议:")
        print(f"    年化收益: {annual}%")
        print(f"    最大回撤: {max_dd}%")
        print(f"    夏普比率: {sharpe}")
        print(f"    recommend_adoption: {recommend}")

        if recommend:
            print(f"    ✅ 建议采纳: V6通过过拟合检测和多周期一致性验证")
        else:
            reasons = []
            if of_result.get('overfit_detected', False):
                reasons.append("过拟合检测未通过")
            if cc_result['verdict'] == "不予采纳":
                reasons.append("多周期一致性验证未通过")
            if sharpe <= 0.5:
                reasons.append(f"夏普比率{sharpe}未超过0.5阈值")
            if annual <= 0:
                reasons.append("年化收益为负")
            print(f"    ❌ 暂不建议采纳: {', '.join(reasons)}")

        # V5 → V6 升级效果
        v5_annual = -1.13
        v5_max_dd = 19.03
        v5_sharpe = -0.14
        improvement = {
            '年化收益': f"{v5_annual}% → {annual}% ({'↑' if annual > v5_annual else '↓'}{abs(annual - v5_annual):.2f}pp)",
            '最大回撤': f"{v5_max_dd}% → {max_dd}% ({'↑' if max_dd > v5_max_dd else '↓'}{abs(max_dd - v5_max_dd):.2f}pp)",
            '夏普比率': f"{v5_sharpe} → {sharpe} ({'↑' if sharpe > v5_sharpe else '↓'}{abs(sharpe - v5_sharpe):.2f})",
        }
        print(f"\n  📈 V5 → V6 升级效果:")
        for k, v in improvement.items():
            print(f"    {k}: {v}")

    # JSON 输出
    output = {
        "strategy_name": "BlakeverStrategyV6",
        "strategy_source": "blakever_test_stragegy.py",
        "data_source": "back_trader_stocks (本地CSV)",
        "data_period": f"{MAIN_START} ~ {MAIN_END}",
        "backtest_framework": "手动组合权重引擎 (每周调仓)",
        "overfit_detected": of_result.get('overfit_detected', None),
        "overfit_details": of_result.get('overfit_details', ''),
        "period_results": {},
        "consistency_check": cc_result,
        "recommend_adoption": recommend if full_key in period_results else False,
        "v5_vs_v6": {
            "v5_年化": -1.13,
            "v6_年化": period_results.get(full_key, {}).get('年化收益%', 0),
            "v5_回撤": 19.03,
            "v6_回撤": period_results.get(full_key, {}).get('最大回撤%', 0),
            "v5_夏普": -0.14,
            "v6_夏普": period_results.get(full_key, {}).get('夏普比率', 0),
        },
        "optimization_notes": [
            "SH(反向ETF)数据缺失，用IEF(7-10年国债)替代，实际SH在熊市对冲效果更强",
            "QQQ数据缺失，用SPY替代，实际QQQ在牛市弹性更大",
            "Alpha选股池为硬编码美股科技巨头，可改为动态筛选",
            "调仓频率为每周，可测试每月调仓减少交易成本",
            "可加入止损线: 单日组合回撤>3%时强制切Risk-Off"
        ]
    }

    for k, v in period_results.items():
        output["period_results"][k] = {
            '总收益率%': v.get('总收益率%', 0),
            '年化收益%': v.get('年化收益%', 0),
            '最大回撤%': v.get('最大回撤%', 0),
            '夏普比率': v.get('夏普比率', 0),
            '卡尔马比率': v.get('卡尔马比率', 0),
            '环境占比': v.get('环境占比', {}),
            '年度收益': v.get('年度收益', {}),
        }

    output_path = '/data/workspace/blakever_v6_backtest_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📁 完整报告已保存: {output_path}")


if __name__ == '__main__':
    main()
