#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
BlakeverStrategyV6.5 回测验证 — "利率维度修正版"
==========================================================================
V6 致命问题: 把 TLT 当"永远安全"的防守资产 → 2022加息周期 TLT 跌-29%
V6.5 核心修正:
  1. ✅ 引入第二维度状态机: Rate Regime (Rising / Falling)
  2. ✅ Bearish + Rising → SHY(现金) 替代 TLT(长期债券)
  3. ✅ Bullish + Falling → SPY高配，捕捉降息红利
  4. ✅ Alpha 仅在 Bullish + Falling 环境下允许
  5. ✅ Kill Switch → SHY(现金) 而非 TLT
  6. ✅ 现金 = 主动决策资产，不是 fallback

2D 状态空间:
  ┌──────────┬───────────┬──────────────┐
  │ 股市\利率 │  Falling  │   Rising     │
  ├──────────┼───────────┼──────────────┤
  │ Bullish  │ SPY+Alpha │ SPY+Value    │
  │ Sideways │ 分散+GLD  │ SPY+SHY      │
  │ Bearish  │ TLT+GLD   │ SHY(现金)❗   │
  │ Risk-Off │ SHY+GLD   │ SHY+GLD      │
  └──────────┴───────────┴──────────────┘

利率判断: IEF 20日涨幅 > 0 → Falling (债券涨=利率降)
          IEF 20日涨幅 ≤ 0 → Rising  (债券跌=利率升)

数据适配: SHY → SHY (短期国债ETF，直接可用)
框架: 手动组合权重引擎 (每周调仓)
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

ALPHA_POOL = ['AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'AVGO', 'CRM', 'AMD', 'ADBE']

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
    data = {}
    for sym in symbols:
        path = os.path.join(DATA_DIR, 'etf', f'{sym}.csv')
        if not os.path.exists(path):
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

    if data:
        common_idx = data[symbols[0]].index
        for sym in data:
            common_idx = common_idx.intersection(data[sym].index)
        for sym in data:
            data[sym] = data[sym].loc[common_idx]

    return data


# ================================================================
# V6.5 核心逻辑: 双维度状态机 + 利率适配资产配置
# ================================================================
class BlakeverV65Backtest:
    """
    BlakeverStrategyV6.5 — 利率维度修正版

    核心改动 vs V6:
    - 新增 Rate Regime (Rising/Falling) 判断
    - Bearish + Rising → SHY(现金) 替代 TLT
    - Bullish + Falling → Alpha 允许
    - Alpha 仅在非加息环境允许
    - Kill Switch → SHY 而非 TLT
    """

    # ✅ V6.5 2D资产配置矩阵
    ALLOCATION = {
        # Bullish 环境
        ("Bullish", "Falling"): {"SPY": 0.55, "GLD": 0.10},      # Alpha 15% 叠加
        ("Bullish", "Rising"):  {"SPY": 0.60, "GLD": 0.20, "SHY": 0.20},  # 无Alpha, 加现金

        # Sideways 环境
        ("Sideways", "Falling"): {"SPY": 0.30, "GLD": 0.30, "TLT": 0.20, "SHY": 0.20},
        ("Sideways", "Rising"):  {"SPY": 0.30, "GLD": 0.20, "SHY": 0.50},  # 加息时重仓现金

        # Bearish 环境 — 关键改动
        ("Bearish", "Falling"): {"TLT": 0.50, "GLD": 0.30, "SHY": 0.20},  # 降息熊市: TLT有效
        ("Bearish", "Rising"):  {"SHY": 0.70, "GLD": 0.30},               # ❗加息熊市: 全现金

        # Risk-Off
        ("Risk-Off", "Falling"): {"SHY": 0.60, "GLD": 0.20, "TLT": 0.20},
        ("Risk-Off", "Rising"):  {"SHY": 0.70, "GLD": 0.30},
    }

    def __init__(self, spy_data, vix_data, ief_data, tlt_data, gld_data, shy_data,
                 alpha_pool_data=None):
        self.spy = spy_data
        self.vix = vix_data
        self.ief = ief_data
        self.tlt = tlt_data
        self.gld = gld_data
        self.shy = shy_data
        self.alpha_pool = alpha_pool_data or {}

        # 状态机
        self.regime = "Sideways"
        self.rate_regime = "Falling"
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
        """基于T-1数据更新市场环境判定"""
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

        # Risk-On 恢复
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

    def update_rate_regime(self, i: int) -> str:
        """
        ✅ V6.5 新增: 利率环境判定
        IEF(7-10年国债) 20日涨幅 > 0 → Falling (债券涨=利率降)
        IEF 20日涨幅 ≤ 0 → Rising (债券跌=利率升)
        """
        if self.ief is None or i < 21:
            return "Falling"  # 默认降息(偏保守)

        ief_ret_20d = self.ief['Close'].iloc[i - 1] / self.ief['Close'].iloc[i - 21] - 1
        self.rate_regime = "Falling" if ief_ret_20d > 0 else "Rising"
        return self.rate_regime

    def get_asset_allocation(self, regime: str, rate_regime: str, alpha_stocks=None) -> dict:
        """
        ✅ V6.5 核心: 2D资产配置矩阵
        """
        # Risk-Off 优先
        if self.kill_switch:
            if rate_regime == "Rising":
                weights = {"SHY": 0.70, "GLD": 0.30}
            else:
                weights = {"SHY": 0.60, "GLD": 0.20, "TLT": 0.20}
            return weights

        # 查2D配置表
        key = (regime, rate_regime)
        weights = self.ALLOCATION.get(key, {"SHY": 0.50, "GLD": 0.30, "SPY": 0.20}).copy()

        # ✅ Alpha 叠加 — 仅 Bullish + Falling 环境允许
        if regime == "Bullish" and rate_regime == "Falling" and alpha_stocks:
            alpha_weight = 0.15  # V6.5: 从30%降到15%
            per_stock = alpha_weight / len(alpha_stocks) if alpha_stocks else 0
            for sym in alpha_stocks:
                weights[sym] = per_stock
            if "SPY" in weights:
                weights["SPY"] = max(0.30, weights["SPY"] - alpha_weight)

        return weights

    def select_alpha_stocks(self, i: int) -> list:
        """多因子选股 (ADX + 动量 + 量能) → Top3"""
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
def run_portfolio_backtest(engine: BlakeverV65Backtest, all_data: dict,
                           start_date: str, end_date: str,
                           fees=FEES_US, rebalance_freq='W') -> dict:
    spy = engine.spy
    mask = (spy.index >= start_date) & (spy.index <= end_date)
    dates = spy[mask].index

    if len(dates) < 200:
        return {'状态': '数据不足'}

    cash = INIT_CASH
    holdings = {}
    portfolio_values = []
    weights_history = []
    regime_history = []
    rate_regime_history = []

    last_rebalance = None

    for idx_pos, date in enumerate(dates):
        i = spy.index.get_loc(date)

        # 1. 更新双维度状态
        regime = engine.update_market_regime(i)
        rate_regime = engine.update_rate_regime(i)

        # 2. 判断调仓
        need_rebalance = False
        if last_rebalance is None:
            need_rebalance = True
        elif rebalance_freq == 'D':
            need_rebalance = True
        elif rebalance_freq == 'W':
            if date.weekday() == 0 and date != last_rebalance:
                need_rebalance = True
        elif rebalance_freq == 'M':
            if date.month != last_rebalance.month:
                need_rebalance = True

        # 3. 调仓
        if need_rebalance:
            last_rebalance = date

            alpha_stocks = engine.select_alpha_stocks(i)
            target_weights = engine.get_asset_allocation(regime, rate_regime, alpha_stocks)

            # 清算
            for sym, shares in holdings.items():
                if sym in all_data and date in all_data[sym].index:
                    price = all_data[sym].loc[date, 'Close']
                    cash += shares * price * (1 - fees - SLIPPAGE)
                elif sym in all_data:
                    avail = all_data[sym].loc[:date]
                    if len(avail) > 0:
                        price = avail.iloc[-1]['Close']
                        cash += shares * price * (1 - fees - SLIPPAGE)
            holdings = {}

            # 建仓
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
                'rate_regime': rate_regime,
                'weights': {k: round(v, 3) for k, v in target_weights.items()},
                'alpha': alpha_stocks
            })

        regime_history.append(regime)
        rate_regime_history.append(rate_regime)

        # 4. 组合价值
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

    # 5. 绩效指标
    pv = np.array(portfolio_values)
    returns = np.diff(pv) / pv[:-1]
    returns = np.concatenate([[0], returns])

    total_return = (pv[-1] / pv[0] - 1) * 100 if pv[0] > 0 else 0
    n_years = len(pv) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_return > -100 else -100

    peak = np.maximum.accumulate(pv)
    drawdown = (pv - peak) / peak * 100
    max_dd = abs(drawdown.min())

    daily_rf = RISK_FREE_RATE / 252
    excess_returns = returns - daily_rf
    sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if np.std(excess_returns) > 0 else 0

    calmar = annual / max_dd if max_dd > 0 else 0

    # 各环境占比
    regime_arr = np.array(regime_history)
    regime_counts = pd.Series(regime_arr).value_counts()
    regime_pct = {k: round(v / len(regime_arr) * 100, 1) for k, v in regime_counts.items()}

    # 利率环境占比
    rate_arr = np.array(rate_regime_history)
    rate_counts = pd.Series(rate_arr).value_counts()
    rate_pct = {k: round(v / len(rate_arr) * 100, 1) for k, v in rate_counts.items()}

    # 2D组合环境占比
    combo_arr = np.array([f"{r}/{rr}" for r, rr in zip(regime_history, rate_regime_history)])
    combo_counts = pd.Series(combo_arr).value_counts()
    combo_pct = {k: round(v / len(combo_arr) * 100, 1) for k, v in combo_counts.items()}

    # 年度收益
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
        '利率环境占比': rate_pct,
        '2D组合占比': combo_pct,
        '年度收益': yearly_returns,
        '最终权重': weights_history[-1] if weights_history else {},
        'portfolio_values': pv,
        'regime_history': regime_history,
        'rate_regime_history': rate_regime_history,
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
def overfit_check_portfolio(engine_class, all_data, spy, vix, ief, tlt, gld, shy, alpha_data,
                            start, end, fees=FEES_US):
    """过拟合检测: 训练集(前70%) vs 测试集(后30%)"""
    mask = (spy.index >= start) & (spy.index <= end)
    dates = spy[mask].index
    n = len(dates)
    split_date = dates[int(n * 0.7)]

    engine_train = engine_class(spy, vix, ief, tlt, gld, shy, alpha_data)
    train_result = run_portfolio_backtest(engine_train, all_data, start, split_date.strftime('%Y-%m-%d'), fees)

    engine_test = engine_class(spy, vix, ief, tlt, gld, shy, alpha_data)
    test_result = run_portfolio_backtest(engine_test, all_data, split_date.strftime('%Y-%m-%d'), end, fees)

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
def print_portfolio_result(result, name="V6.5"):
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
        print(f"    股市环境占比: {result['环境占比']}")
    if '利率环境占比' in result:
        print(f"    利率环境占比: {result['利率环境占比']}")
    if '2D组合占比' in result:
        print(f"    2D组合占比: {result['2D组合占比']}")

    if '年度收益' in result:
        print(f"    年度收益:")
        for year, ret in result['年度收益'].items():
            status = "🟢" if ret > 0 else "🔴"
            print(f"      {year}: {status} {ret}%")


def print_comparison_table(results_list):
    print(f"\n{'━' * 120}")
    header = f"{'策略':<32} {'总收益率':>10} {'年化收益':>10} {'最大回撤':>10} {'夏普':>8} {'卡尔马':>8}"
    print(header)
    print("-" * 120)
    for r in results_list:
        print(f"{r['策略']:<32} {r['总收益率%']:>9.2f}% {r['年化收益%']:>9.2f}% "
              f"{r['最大回撤%']:>9.2f}% {r['夏普比率']:>8.2f} {r['卡尔马比率']:>8.2f}")
    print(f"{'━' * 120}")


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 120)
    print("  🚀 BlakeverStrategyV6.5 回测验证 — '利率维度修正版'")
    print("  核心修正: TLT不是永远安全 → 加入利率Regime → Bearish+Rising=SHY(现金)")
    print("  2D状态: Market Regime × Rate Regime → 动态资产配置")
    print("=" * 120)

    # ================================================================
    # 1. 加载数据
    # ================================================================
    print("\n📥 加载数据...")

    etf_symbols = ['SPY', 'TLT', 'GLD', 'IEF', 'SHY', 'VIX']
    etf_data = load_etf_data(etf_symbols, '2018-01-01', '2024-12-31')

    if 'SPY' not in etf_data or 'VIX' not in etf_data:
        print("  ❌ SPY 或 VIX 数据缺失，无法继续")
        return

    if 'SHY' not in etf_data:
        print("  ❌ SHY 数据缺失，无法继续 (V6.5核心资产)")
        return

    if 'IEF' not in etf_data:
        print("  ❌ IEF 数据缺失，无法判定利率环境")
        return

    print(f"\n  ✅ V6.5 核心数据就绪: SPY + VIX + IEF(利率) + SHY(现金) + TLT + GLD")

    # Alpha股票池
    print("\n📥 加载Alpha股票池...")
    alpha_data = {}
    for sym in ALPHA_POOL:
        path = os.path.join(DATA_DIR, 'us', f'{sym}.csv')
        if os.path.exists(path):
            df = load_csv(path)
            df = compute_indicators(df)
            common = df.index.intersection(etf_data['SPY'].index)
            alpha_data[sym] = df.loc[common]
            print(f"  ✅ {sym}: {len(alpha_data[sym])} 天")

    # 合并可交易数据
    all_data = {}
    for sym in ['SPY', 'TLT', 'GLD', 'IEF', 'SHY']:
        if sym in etf_data:
            all_data[sym] = etf_data[sym]
    for sym, df in alpha_data.items():
        all_data[sym] = df

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

    # V6 基准数据 (上次回测结果)
    v6_baseline = {
        '1年': {'年化%': 6.95, '回撤%': 8.02, '夏普': 0.26},
        '3年': {'年化%': -6.32, '回撤%': 30.91, '夏普': -0.94},
        '5年': {'年化%': -4.97, '回撤%': 37.58, '夏普': -0.80},
        '全周期(2019-2024)': {'年化%': -3.61, '回撤%': 37.58, '夏普': -0.73},
    }

    for period_name, (start, end) in periods.items():
        print(f"\n{'━' * 120}")
        print(f"  📊 回测区间: {period_name} ({start} ~ {end})")
        print(f"{'━' * 120}")

        engine = BlakeverV65Backtest(
            spy_data=spy, vix_data=etf_data['VIX'],
            ief_data=etf_data['IEF'], tlt_data=etf_data.get('TLT'),
            gld_data=etf_data.get('GLD'), shy_data=etf_data['SHY'],
            alpha_pool_data=alpha_data
        )

        v65_result = run_portfolio_backtest(engine, all_data, start, end, FEES_US, 'W')
        print_portfolio_result(v65_result, f"BlakeverV6.5-{period_name}")

        bh_result = run_buyhold_portfolio(spy, start, end, FEES_US)
        print_portfolio_result(bh_result, f"Buy&Hold SPY-{period_name}")

        # V6 vs V6.5 对比
        v6b = v6_baseline.get(period_name, {})
        print(f"\n  📊 V6 → V6.5 升级效果 ({period_name}):")
        v65_annual = v65_result.get('年化收益%', 0)
        v65_dd = v65_result.get('最大回撤%', 0)
        v65_sharpe = v65_result.get('夏普比率', 0)
        print(f"    年化: {v6b.get('年化%', '?')}% → {v65_annual}%")
        print(f"    回撤: {v6b.get('回撤%', '?')}% → {v65_dd}%")
        print(f"    夏普: {v6b.get('夏普', '?')} → {v65_sharpe}")

        comparison.append({
            '策略': f'V6.5-{period_name}',
            '总收益率%': v65_result.get('总收益率%', 0),
            '年化收益%': v65_annual,
            '最大回撤%': v65_dd,
            '夏普比率': v65_sharpe,
            '卡尔马比率': v65_result.get('卡尔马比率', 0),
        })
        comparison.append({
            '策略': f'B&H-{period_name}',
            '总收益率%': bh_result.get('总收益率%', 0),
            '年化收益%': bh_result.get('年化收益%', 0),
            '最大回撤%': bh_result.get('最大回撤%', 0),
            '夏普比率': bh_result.get('夏普比率', 0),
            '卡尔马比率': bh_result.get('卡尔马比率', 0),
        })

        period_results[period_name] = v65_result

    # ================================================================
    # 3. 全面对比
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 V6.5 vs B&H 对比汇总")
    print_comparison_table(comparison)

    # ================================================================
    # 4. V5 → V6 → V6.5 三代进化对比
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 三代策略进化对比 (全周期 2019-2024)")
    print(f"{'━' * 120}")

    full_key = '全周期(2019-2024)'
    if full_key in period_results:
        v65_full = period_results[full_key]

        print(f"\n  V5 (单标的择时):  年化 -1.13%  回撤 19.03%  夏普 -0.14")
        print(f"  V6 (ETF轮动):     年化 -3.61%  回撤 37.58%  夏普 -0.73  ← TLT踩雷")
        print(f"  V6.5(利率修正):   年化 {v65_full.get('年化收益%', 0)}%  回撤 {v65_full.get('最大回撤%', 0)}%  夏普 {v65_full.get('夏普比率', 0)}")

        v65_annual = v65_full.get('年化收益%', 0)
        v65_dd = abs(v65_full.get('最大回撤%', 0))
        v65_sharpe = v65_full.get('夏普比率', 0)

        print(f"\n  📈 V6 → V6.5 关键改动效果:")
        print(f"    年化: -3.61% → {v65_annual}% ({'✅ 改善' if v65_annual > -3.61 else '❌ 未改善'} {abs(v65_annual - (-3.61)):.2f}pp)")
        print(f"    回撤: 37.58% → {v65_dd}% ({'✅ 改善' if v65_dd < 37.58 else '❌ 未改善'} {abs(v65_dd - 37.58):.2f}pp)")
        print(f"    夏普: -0.73 → {v65_sharpe} ({'✅ 改善' if v65_sharpe > -0.73 else '❌ 未改善'} {abs(v65_sharpe - (-0.73)):.2f})")

        # 2D环境分布
        if '2D组合占比' in v65_full:
            print(f"\n  📊 2D状态空间分布:")
            for combo, pct in sorted(v65_full['2D组合占比'].items()):
                print(f"    {combo}: {pct}%")

        if '年度收益' in v65_full:
            print(f"\n  📊 年度收益 (V6 vs V6.5):")
            v6_yearly = {'2019': 3.33, '2020': -9.66, '2021': 5.51, '2022': -28.65, '2023': 5.47, '2024': 7.53}
            for year, ret in v65_full['年度收益'].items():
                v6r = v6_yearly.get(year, '?')
                arrow = '✅' if ret > v6r else '❌' if isinstance(v6r, (int, float)) else ''
                print(f"    {year}: V6 {v6r}% → V6.5 {ret}% {arrow}")

    # ================================================================
    # 5. 关键年度: 2022 熊市专项分析
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 2022熊市专项分析 (V6.5最关键验证)")
    print(f"{'━' * 120}")

    engine_2022 = BlakeverV65Backtest(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], tlt_data=etf_data.get('TLT'),
        gld_data=etf_data.get('GLD'), shy_data=etf_data['SHY'],
        alpha_pool_data=alpha_data
    )
    result_2022 = run_portfolio_backtest(engine_2022, all_data, '2022-01-01', '2022-12-31', FEES_US, 'W')
    print_portfolio_result(result_2022, "BlakeverV6.5-2022熊市")

    bh_2022 = run_buyhold_portfolio(spy, '2022-01-01', '2022-12-31', FEES_US)
    print_portfolio_result(bh_2022, "Buy&Hold SPY-2022")

    print(f"\n  💡 V6.5 vs V6 在2022年的差异:")
    print(f"    V6:   -28.65% (重仓TLT踩雷)")
    print(f"    V6.5: {result_2022.get('年化收益%', 0)}% (加息熊市→SHY现金)")
    print(f"    B&H:  {bh_2022.get('年化收益%', 0)}%")
    print(f"    改善: {abs(result_2022.get('年化收益%', 0) - (-28.65)):.2f}pp")

    # ================================================================
    # 6. 熊市回测 (2022-2023)
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 熊市回测 (2022-2023)")
    print(f"{'━' * 120}")

    engine_bear = BlakeverV65Backtest(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], tlt_data=etf_data.get('TLT'),
        gld_data=etf_data.get('GLD'), shy_data=etf_data['SHY'],
        alpha_pool_data=alpha_data
    )
    bear_result = run_portfolio_backtest(engine_bear, all_data, '2022-01-01', '2023-12-31', FEES_US, 'W')
    print_portfolio_result(bear_result, "BlakeverV6.5-熊市")

    bear_bh = run_buyhold_portfolio(spy, '2022-01-01', '2023-12-31', FEES_US)
    print_portfolio_result(bear_bh, "Buy&Hold SPY-熊市")

    # ================================================================
    # 7. 震荡市回测 (2021-2023)
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 震荡市回测 (2021-2023)")
    print(f"{'━' * 120}")

    engine_range = BlakeverV65Backtest(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], tlt_data=etf_data.get('TLT'),
        gld_data=etf_data.get('GLD'), shy_data=etf_data['SHY'],
        alpha_pool_data=alpha_data
    )
    range_result = run_portfolio_backtest(engine_range, all_data, '2021-01-01', '2023-12-31', FEES_US, 'W')
    print_portfolio_result(range_result, "BlakeverV6.5-震荡市")

    range_bh = run_buyhold_portfolio(spy, '2021-01-01', '2023-12-31', FEES_US)
    print_portfolio_result(range_bh, "Buy&Hold SPY-震荡市")

    # ================================================================
    # 8. 过拟合检测
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 过拟合检测 (全周期 训练集70% vs 测试集30%)")
    print(f"{'━' * 120}")

    of_result = overfit_check_portfolio(
        BlakeverV65Backtest, all_data, spy, etf_data['VIX'],
        etf_data['IEF'], etf_data.get('TLT'), etf_data.get('GLD'),
        etf_data['SHY'], alpha_data,
        '2019-01-01', '2024-12-31', FEES_US
    )

    of_status = "⚠️ 过拟合" if of_result['overfit_detected'] else "✅ 未检测到过拟合"
    print(f"\n  {of_status}")
    print(f"  训练集收益: {of_result['train_return']}%")
    print(f"  测试集收益: {of_result['test_return']}%")
    print(f"  详情: {of_result['overfit_details']}")

    # ================================================================
    # 9. 多周期一致性验证
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 多周期一致性验证")
    print(f"{'━' * 120}")

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
    # 10. 最终报告
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📋 最终报告")
    print(f"{'━' * 120}")

    recommend = False
    if full_key in period_results:
        r = period_results[full_key]
        annual = r.get('年化收益%', 0)
        max_dd = abs(r.get('最大回撤%', 0))
        sharpe = r.get('夏普比率', 0)

        # 判定逻辑: 改善比率 > 10% 且过拟合+一致性通过
        v6_annual = -3.61
        improvement_ratio = abs(annual - v6_annual) / abs(v6_annual) * 100 if v6_annual != 0 else 0

        if cc_result['verdict'] != "不予采纳" and not of_result.get('overfit_detected', True):
            if sharpe > 0.3 and annual > 0:
                recommend = True
            elif improvement_ratio > 10 and sharpe > 0:
                recommend = True

        print(f"\n  🎯 推荐建议:")
        print(f"    年化收益: {annual}%")
        print(f"    最大回撤: {max_dd}%")
        print(f"    夏普比率: {sharpe}")
        print(f"    V6→V6.5改善比率: {improvement_ratio:.1f}%")
        print(f"    recommend_adoption: {recommend}")

        if recommend:
            print(f"    ✅ 建议采纳: V6.5通过过拟合检测和多周期一致性验证")
        else:
            reasons = []
            if of_result.get('overfit_detected', False):
                reasons.append("过拟合检测未通过")
            if cc_result['verdict'] == "不予采纳":
                reasons.append("多周期一致性验证未通过")
            if sharpe <= 0.3:
                reasons.append(f"夏普比率{sharpe}未超过0.3阈值")
            if annual <= 0:
                reasons.append("年化收益为负")
            print(f"    ❌ 暂不建议采纳: {', '.join(reasons)}")

        # V5 → V6 → V6.5 三代进化
        print(f"\n  📈 三代策略进化总结:")
        print(f"    V5:   年化-1.13%  回撤19.03%  夏普-0.14  问题: 空仓错过牛市")
        print(f"    V6:   年化-3.61%  回撤37.58%  夏普-0.73  问题: TLT踩雷+Alpha放大亏损")
        print(f"    V6.5: 年化{annual}%  回撤{max_dd}%  夏普{sharpe}  修正: 利率维度+SHY现金")

    # JSON 输出
    output = {
        "strategy_name": "BlakeverStrategyV6.5",
        "strategy_source": "blakever_test_stragegy.py",
        "core_change": "加入利率Regime, Bearish+Rising→SHY(现金), Alpha仅Bullish+Falling",
        "data_source": "back_trader_stocks (本地CSV)",
        "data_period": f"{MAIN_START} ~ {MAIN_END}",
        "backtest_framework": "手动组合权重引擎 (每周调仓)",
        "overfit_detected": of_result.get('overfit_detected', None),
        "overfit_details": of_result.get('overfit_details', ''),
        "period_results": {},
        "consistency_check": cc_result,
        "recommend_adoption": recommend,
        "evolution": {
            "V5_年化": -1.13, "V5_回撤": 19.03, "V5_夏普": -0.14,
            "V6_年化": -3.61, "V6_回撤": 37.58, "V6_夏普": -0.73,
            "V65_年化": period_results.get(full_key, {}).get('年化收益%', 0),
            "V65_回撤": period_results.get(full_key, {}).get('最大回撤%', 0),
            "V65_夏普": period_results.get(full_key, {}).get('夏普比率', 0),
        },
        "v65_vs_v6_key_change": {
            "Bearish+Rising": "TLT 50% → SHY 70% (现金替代长期债券)",
            "Alpha_filter": "仅 Bullish+Falling 允许 (非加息环境)",
            "Alpha_weight": "30% → 15%",
            "Kill_Switch": "→ SHY 而非 TLT",
            "Rate_proxy": "IEF 20日涨幅 (债券涨=利率降)",
        }
    }

    for k, v in period_results.items():
        output["period_results"][k] = {
            '总收益率%': v.get('总收益率%', 0),
            '年化收益%': v.get('年化收益%', 0),
            '最大回撤%': v.get('最大回撤%', 0),
            '夏普比率': v.get('夏普比率', 0),
            '卡尔马比率': v.get('卡尔马比率', 0),
            '环境占比': v.get('环境占比', {}),
            '利率环境占比': v.get('利率环境占比', {}),
            '2D组合占比': v.get('2D组合占比', {}),
            '年度收益': v.get('年度收益', {}),
        }

    output_path = '/data/workspace/blakever_v65_backtest_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📁 完整报告已保存: {output_path}")


if __name__ == '__main__':
    main()
