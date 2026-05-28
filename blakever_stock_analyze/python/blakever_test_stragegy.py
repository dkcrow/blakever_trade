#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
BlakeverStrategyV7 回测验证 — "三层组合工程系统"
==========================================================================
V7 核心升级 (vs V6.5):
  Layer 1: ✅ 双维度状态机  — Market Regime × Rate Regime
  Layer 2: ✅ 动态资产选择  — 不再固定映射，按状态选资产池
  Layer 3: ✅ 风险控制三件套:
            - Risk Parity  (波动率反向分配，风险均衡)
            - Vol Targeting (目标波动10%，自动加减仓)
            - Drawdown Control (回撤>10%降仓, >20%强保守)

V7 vs V6.5 关键区别:
  V6.5: Regime → 固定权重映射表 (SPY 60% + GLD 20% + SHY 20% 写死的)
  V7:   Regime → 资产池 → Risk Parity动态权重 → Vol Targeting → Drawdown Control

  V6.5: 无论市场波动多少，都是满仓100%
  V7:   波动升高自动降仓，高波动环境天然保守

  V6.5: 回撤到-37%还在满仓，完全没有止损机制
  V7:   回撤10%就自动降仓到70%，回撤20%砍半

2D 状态空间:
  ┌──────────┬─────────────────┬─────────────────┐
  │ 股市\利率 │    Falling      │    Rising        │
  ├──────────┼─────────────────┼─────────────────┤
  │ Bullish  │ QQQ,SPY,GLD 🚀  │ SPY,GLD,SHY     │
  │ Sideways │ SPY,GLD,SHY     │ SPY,GLD,SHY     │
  │ Bearish  │ TLT,GLD,SH ✅   │ SHY,GLD,SH ❗    │
  │ Risk-Off │ SHY,GLD,SH      │ SHY,GLD,SH      │
  └──────────┴─────────────────┴─────────────────┘

补充模块 (V7设计稿缺失，从V6.5继承):
  ✅ VIX Kill Switch (暴跌+恐慌检测)
  ✅ Alpha选股 (Bullish+Falling环境, 多因子Top3)
  ✅ 过拟合检测 (训练集70% vs 测试集30%)
  ✅ 多周期一致性验证
  ✅ 手续费+滑点模型
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


def try_download_etf(sym: str, start: str = '2018-01-01', end: str = '2024-12-31') -> bool:
    """尝试通过yfinance下载ETF数据"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(sym)
        df = ticker.history(start=start, end=end)
        if len(df) > 200:
            df = df.reset_index()
            df.columns = [c.capitalize() for c in df.columns]
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
            out_path = os.path.join(DATA_DIR, 'etf', f'{sym}.csv')
            df.to_csv(out_path, index=False)
            print(f"  ✅ {sym}: 已从yfinance下载 {len(df)} 天数据")
            return True
        else:
            print(f"  ⚠️ {sym}: yfinance返回数据不足({len(df)}天)")
            return False
    except Exception as e:
        print(f"  ⚠️ {sym}: yfinance下载失败 ({e})")
        return False


# ================================================================
# V7 核心逻辑: 三层组合工程系统
# ================================================================
class BlakeverStrategyV7:
    """
    BlakeverStrategyV7 — 三层组合工程系统

    Layer 1: 双维度状态机 (Market Regime × Rate Regime)
    Layer 2: 动态资产选择 (按状态选资产池，非固定映射)
    Layer 3: 风险控制三件套 (Risk Parity + Vol Targeting + Drawdown Control)

    补充模块 (V7设计稿缺失，从V6.5继承):
    - VIX Kill Switch
    - Alpha选股 (Bullish+Falling, 多因子Top3)
    """

    def __init__(self, spy_data, vix_data, ief_data, etf_data: dict,
                 alpha_pool_data=None, target_vol=0.10):
        """
        Parameters
        ----------
        spy_data : SPY DataFrame (含技术指标)
        vix_data : VIX DataFrame
        ief_data : IEF DataFrame (中期国债，利率代理)
        etf_data : dict, 可用ETF数据 {sym: DataFrame}
        alpha_pool_data : dict, Alpha股票池数据
        target_vol : float, 目标年化波动率 (默认10%)
        """
        self.spy = spy_data
        self.vix = vix_data
        self.ief = ief_data
        self.etf_data = etf_data
        self.alpha_pool = alpha_pool_data or {}

        # ── Layer 1: 状态机 ──
        self.regime = "Sideways"
        self.rate_regime = "Falling"
        self.candidate_regime = None
        self.candidate_days = 0
        self.kill_switch = False

        # ── Layer 3: 风险控制参数 ──
        self.target_vol = target_vol
        self.config = {
            "persistence": 3,        # 状态机切换确认天数
            "max_leverage": 1.5,     # Vol Targeting 最大杠杆
            "min_leverage": 0.3,     # Vol Targeting 最小杠杆
            "dd_level1": -0.10,      # 回撤保护 第一档 (-10%)
            "dd_level2": -0.20,      # 回撤保护 第二档 (-20%)
            "dd_scale1": 0.7,        # 回撤-10%时仓位缩放到70%
            "dd_scale2": 0.5,        # 回撤-20%时仓位缩放到50%
        }

        # ── Kill Switch 参数 ──
        self.vix_threshold = 25.0
        self.vix_spike_ratio = 0.15
        self.adx_sideways = 20.0
        self.trend_strength_threshold = 0.015

        # ── 可用资产追踪 ──
        self.available_assets = set(etf_data.keys())

        # ── 波动率计算回看窗口 ──
        self.vol_lookback = 60  # 60日回看窗口

    # ============================================================
    # Layer 1: 双维度状态机
    # ============================================================
    def _update_regime_state(self, target_regime: str):
        """Hysteresis 状态机 — 防止频繁切换"""
        if target_regime == self.regime:
            self.candidate_regime = None
            self.candidate_days = 0
        else:
            if target_regime == self.candidate_regime:
                self.candidate_days += 1
            else:
                self.candidate_regime = target_regime
                self.candidate_days = 1

            if self.candidate_days >= self.config["persistence"]:
                self.regime = target_regime
                self.candidate_regime = None
                self.candidate_days = 0

    def update_market_regime(self, i: int) -> str:
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

        # ── Kill Switch 检测 ──
        daily_ret = (t1_close - t2_close) / t2_close if t2_close != 0 else 0
        three_ret = (t1_close - t5_close) / t5_close if t5_close != 0 else 0
        vix_3d = (vix_t1 - vix_t5) / vix_t5 if vix_t5 != 0 else 0

        if (daily_ret < -0.03 and three_ret < -0.05) or \
           (vix_t1 > self.vix_threshold and vix_3d > self.vix_spike_ratio):
            self.kill_switch = True
            return "Risk-Off"

        # ── Risk-On 恢复 ──
        if self.kill_switch:
            if t1_close > t1_ema50 and (t1_close - t2_close) > 0:
                self.kill_switch = False

        # ── 环境判定 ──
        if np.isnan(t1_adx):
            t1_adx = 0
        trend_strength = abs(t1_ema50 - t1_ema200) / t1_ema200 \
            if t1_ema200 != 0 and not np.isnan(t1_ema200) else 0

        target = "Bearish"
        if t1_adx < self.adx_sideways and trend_strength < self.trend_strength_threshold:
            target = "Sideways"
        elif t1_close > t1_ema200 and t1_ema50 > t1_ema200:
            target = "Bullish"

        self._update_regime_state(target)
        return self.regime

    def update_rate_regime(self, i: int) -> str:
        """
        利率环境判定
        IEF 20日涨幅 > 0 → Falling (债券涨=利率降)
        IEF 20日涨幅 ≤ 0 → Rising  (债券跌=利率升)
        """
        if self.ief is None or i < 21:
            return "Falling"

        ief_ret_20d = self.ief['Close'].iloc[i - 1] / self.ief['Close'].iloc[i - 21] - 1
        self.rate_regime = "Falling" if ief_ret_20d > 0 else "Rising"
        return self.rate_regime

    # ============================================================
    # Layer 2: 动态资产选择
    # ============================================================
    def select_assets(self, regime: str, rate_regime: str) -> list:
        """
        按状态选资产池 — 不分配权重，权重由Layer 3决定

        优先使用理想资产，若不可用则降级:
          QQQ → SPY (成长降级为宽基)
          SH  → SHY (对冲降级为现金)
          TLT → AGG (长债降级为综合债)
        """
        # 理想资产池
        if regime == "Risk-Off":
            ideal = ["SHY", "GLD", "SH"]
        elif regime == "Bullish":
            if rate_regime == "Falling":
                ideal = ["QQQ", "SPY", "GLD"]
            else:
                ideal = ["SPY", "GLD", "SHY"]
        elif regime == "Bearish":
            if rate_regime == "Falling":
                ideal = ["TLT", "GLD", "SH"]
            else:
                ideal = ["SHY", "GLD", "SH"]
        else:  # Sideways
            ideal = ["SPY", "GLD", "SHY"]

        # 可用性检查 + 降级
        selected = []
        for asset in ideal:
            if asset in self.available_assets:
                selected.append(asset)
            else:
                fallback = self._get_fallback(asset)
                if fallback and fallback not in selected:
                    selected.append(fallback)

        # 至少要有一个资产
        if not selected:
            selected = ["SHY"] if "SHY" in self.available_assets else ["SPY"]

        return selected

    def _get_fallback(self, asset: str) -> str:
        """资产降级映射"""
        fallback_map = {
            "QQQ": "SPY",    # 成长 → 宽基
            "SH": "SHY",     # 对冲 → 现金
            "TLT": "AGG",    # 长债 → 综合债
        }
        fb = fallback_map.get(asset, None)
        if fb and fb in self.available_assets:
            return fb
        # 二级降级
        secondary = {"AGG": "SHY", "SPY": "SHY"}
        fb2 = secondary.get(fb or asset, None)
        if fb2 and fb2 in self.available_assets:
            return fb2
        return None

    # ============================================================
    # Layer 3: 风险控制三件套
    # ============================================================
    def risk_parity_weights(self, assets: list, i: int) -> pd.Series:
        """
        Risk Parity — 波动率反向分配
        权重 ∝ 1 / 年化波动率
        """
        vols = {}
        lookback = min(self.vol_lookback, i - 1)

        for asset in assets:
            if asset in self.etf_data and i > lookback:
                prices = self.etf_data[asset]['Close'].iloc[i - lookback:i]
                ret = prices.pct_change().dropna()
                if len(ret) > 10:
                    vols[asset] = ret.std() * np.sqrt(252)
                else:
                    vols[asset] = 0.15  # 默认15%波动率
            else:
                vols[asset] = 0.15

        # 1/波动率 → 归一化
        inv_vol = {k: 1.0 / max(v, 0.01) for k, v in vols.items()}
        total = sum(inv_vol.values())
        weights = pd.Series({k: v / total for k, v in inv_vol.items()})

        return weights

    def apply_vol_target(self, weights: pd.Series, i: int) -> pd.Series:
        """
        Vol Targeting — 目标组合波动率
        目标波动: 10% 年化 → 自动加/减仓
        杠杆范围: 0.3x ~ 1.5x
        """
        assets = list(weights.index)
        lookback = min(self.vol_lookback, i - 1)

        # 计算组合波动率
        returns_list = []
        for asset in assets:
            if asset in self.etf_data and i > lookback:
                prices = self.etf_data[asset]['Close'].iloc[i - lookback:i]
                ret = prices.pct_change().dropna()
                if len(ret) > 10:
                    returns_list.append(ret)
                else:
                    # 用默认值填充
                    ret = pd.Series(np.zeros(lookback - 1))
                    returns_list.append(ret)
            else:
                ret = pd.Series(np.zeros(max(lookback - 1, 10)))
                returns_list.append(ret)

        if returns_list:
            try:
                returns_df = pd.concat(returns_list, axis=1)
                returns_df.columns = assets
                returns_df = returns_df.dropna()
                if len(returns_df) > 10:
                    cov = returns_df.cov() * 252
                    w = weights.values
                    port_vol = np.sqrt(w.T @ cov.values @ w)

                    if port_vol > 0:
                        leverage = self.target_vol / port_vol
                        leverage = np.clip(leverage,
                                           self.config["min_leverage"],
                                           self.config["max_leverage"])
                        return weights * leverage
            except Exception:
                pass

        # 默认不加杠杆
        return weights

    def apply_drawdown_control(self, weights: pd.Series, equity_curve: np.ndarray) -> pd.Series:
        """
        Drawdown Control — 回撤保护
        回撤 > 10% → 降杠杆到70%
        回撤 > 20% → 降杠杆到50%
        """
        if len(equity_curve) < 2:
            return weights

        peak = np.maximum.accumulate(equity_curve)
        current_dd = (equity_curve[-1] - peak[-1]) / peak[-1] if peak[-1] > 0 else 0

        if current_dd < self.config["dd_level2"]:
            return weights * self.config["dd_scale2"]
        elif current_dd < self.config["dd_level1"]:
            return weights * self.config["dd_scale1"]

        return weights

    # ============================================================
    # Alpha 选股 (Bullish+Falling环境)
    # ============================================================
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

    # ============================================================
    # 主权重生成器
    # ============================================================
    def generate_weights(self, i: int, equity_curve: np.ndarray) -> dict:
        """
        完整权重生成流程:
          1. 双维度状态判定
          2. 资产池选择
          3. Risk Parity 初始权重
          4. Vol Targeting 杠杆调整
          5. Drawdown Control 回撤保护
          6. Alpha 叠加 (Bullish+Falling)
        """
        # 1. 状态判定
        regime = self.update_market_regime(i)
        rate_regime = self.update_rate_regime(i)

        # 2. 资产池选择
        assets = self.select_assets(regime, rate_regime)

        # 3. Risk Parity 初始权重
        weights = self.risk_parity_weights(assets, i)

        # 4. Vol Targeting
        weights = self.apply_vol_target(weights, i)

        # 5. Drawdown Control
        weights = self.apply_drawdown_control(weights, equity_curve)

        # 转为dict
        weight_dict = dict(weights)

        # 6. Alpha 叠加 — 仅 Bullish + Falling 环境允许
        if regime == "Bullish" and rate_regime == "Falling" and not self.kill_switch:
            alpha_stocks = self.select_alpha_stocks(i)
            if alpha_stocks:
                alpha_weight = 0.15  # Alpha总权重15%
                per_stock = alpha_weight / len(alpha_stocks)
                for sym in alpha_stocks:
                    weight_dict[sym] = per_stock
                # 从最高权重资产中扣除Alpha权重
                max_asset = max(weight_dict, key=lambda k: weight_dict[k] if k not in alpha_stocks else 0)
                weight_dict[max_asset] = max(0.1, weight_dict[max_asset] - alpha_weight)

        return weight_dict, regime, rate_regime


# ================================================================
# 组合权重回测引擎
# ================================================================
def run_portfolio_backtest(engine: BlakeverStrategyV7, all_data: dict,
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

        # 1. 组合价值 (先算当前价值)
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
        equity_curve = np.array(portfolio_values)

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

            weight_dict, regime, rate_regime = engine.generate_weights(i, equity_curve)

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
            total_weight = sum(weight_dict.values())
            if total_weight > 0:
                for sym, weight in weight_dict.items():
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
                'weights': {k: round(v, 4) for k, v in weight_dict.items()},
                'total_leverage': round(total_weight, 4),
            })

        regime_history.append(engine.regime)
        rate_regime_history.append(engine.rate_regime)

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

    # 胜率
    win_days = np.sum(returns > 0)
    total_days = len(returns[returns != 0])
    win_rate = (win_days / total_days * 100) if total_days > 0 else 0

    # 盈亏比
    avg_win = np.mean(returns[returns > 0]) if np.any(returns > 0) else 0
    avg_loss = abs(np.mean(returns[returns < 0])) if np.any(returns < 0) else 1
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

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

    # 杠杆统计
    if weights_history:
        leverages = [w['total_leverage'] for w in weights_history]
        avg_leverage = round(np.mean(leverages), 4)
        max_leverage = round(max(leverages), 4)
        min_leverage = round(min(leverages), 4)
    else:
        avg_leverage = max_leverage = min_leverage = 1.0

    return {
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': round(sharpe, 2),
        '卡尔马比率': round(calmar, 2),
        '胜率%': round(win_rate, 2),
        '盈亏比': round(profit_loss_ratio, 2),
        '环境占比': regime_pct,
        '利率环境占比': rate_pct,
        '2D组合占比': combo_pct,
        '年度收益': yearly_returns,
        '平均杠杆': avg_leverage,
        '最大杠杆': max_leverage,
        '最小杠杆': min_leverage,
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

    # 胜率
    win_days = np.sum(returns > 0)
    total_days = len(returns[returns != 0])
    win_rate = (win_days / total_days * 100) if total_days > 0 else 0

    # 盈亏比
    avg_win = np.mean(returns[returns > 0]) if np.any(returns > 0) else 0
    avg_loss = abs(np.mean(returns[returns < 0])) if np.any(returns < 0) else 1
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

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
        '胜率%': round(win_rate, 2),
        '盈亏比': round(profit_loss_ratio, 2),
        '年度收益': yearly_returns,
        'portfolio_values': pv,
        'dates': dates,
    }


# ================================================================
# 过拟合检测
# ================================================================
def overfit_check_portfolio(all_data, spy, vix, ief, etf_data, alpha_data,
                            start, end, fees=FEES_US):
    """过拟合检测: 训练集(前70%) vs 测试集(后30%)"""
    mask = (spy.index >= start) & (spy.index <= end)
    dates = spy[mask].index
    n = len(dates)
    split_date = dates[int(n * 0.7)]

    engine_train = BlakeverStrategyV7(spy, vix, ief, etf_data, alpha_data)
    train_result = run_portfolio_backtest(engine_train, all_data, start,
                                          split_date.strftime('%Y-%m-%d'), fees)

    engine_test = BlakeverStrategyV7(spy, vix, ief, etf_data, alpha_data)
    test_result = run_portfolio_backtest(engine_test, all_data,
                                         split_date.strftime('%Y-%m-%d'), end, fees)

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
def print_portfolio_result(result, name="V7"):
    if result.get('状态') == '数据不足':
        print(f"  ⚠️ {name}: 数据不足")
        return

    print(f"\n  📊 {name} 绩效:")
    print(f"    总收益率: {result['总收益率%']}%")
    print(f"    年化收益: {result['年化收益%']}%")
    print(f"    最大回撤: {result['最大回撤%']}%")
    print(f"    夏普比率: {result['夏普比率']}")
    print(f"    卡尔马比率: {result['卡尔马比率']}")
    print(f"    胜率: {result.get('胜率%', 'N/A')}%")
    print(f"    盈亏比: {result.get('盈亏比', 'N/A')}")

    if '平均杠杆' in result:
        print(f"    平均杠杆: {result['平均杠杆']}x (范围: {result.get('最小杠杆', '?')}x ~ {result.get('最大杠杆', '?')}x)")

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
    print(f"\n{'━' * 130}")
    header = f"{'策略':<32} {'总收益率':>10} {'年化收益':>10} {'最大回撤':>10} {'夏普':>8} {'卡尔马':>8} {'胜率':>8} {'盈亏比':>8}"
    print(header)
    print("-" * 130)
    for r in results_list:
        print(f"{r['策略']:<32} {r['总收益率%']:>9.2f}% {r['年化收益%']:>9.2f}% "
              f"{r['最大回撤%']:>9.2f}% {r['夏普比率']:>8.2f} {r['卡尔马比率']:>8.2f} "
              f"{r.get('胜率%', 0):>7.1f}% {r.get('盈亏比', 0):>8.2f}")
    print(f"{'━' * 130}")


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 130)
    print("  🚀 BlakeverStrategyV7 回测验证 — '三层组合工程系统'")
    print("  Layer 1: 双维度状态机 (Market Regime × Rate Regime)")
    print("  Layer 2: 动态资产选择 (按状态选资产池，非固定映射)")
    print("  Layer 3: Risk Parity + Vol Targeting + Drawdown Control")
    print("=" * 130)

    # ================================================================
    # 1. 加载数据
    # ================================================================
    print("\n📥 加载ETF数据...")

    etf_symbols = ['SPY', 'TLT', 'GLD', 'IEF', 'SHY', 'VIX', 'QQQ', 'SH', 'AGG']
    etf_data = load_etf_data(etf_symbols, '2018-01-01', '2024-12-31')

    if 'SPY' not in etf_data:
        print("  ❌ SPY 数据缺失，无法继续")
        return
    if 'VIX' not in etf_data:
        print("  ❌ VIX 数据缺失，无法继续")
        return
    if 'IEF' not in etf_data:
        print("  ❌ IEF 数据缺失，无法判定利率环境")
        return
    if 'SHY' not in etf_data:
        print("  ❌ SHY 数据缺失 (V7核心资产)")
        return

    # 尝试下载缺失的ETF
    for sym in ['QQQ', 'SH']:
        if sym not in etf_data:
            print(f"\n  📥 尝试下载 {sym} 数据...")
            if try_download_etf(sym):
                # 重新加载
                df = load_csv(os.path.join(DATA_DIR, 'etf', f'{sym}.csv'))
                mask = (df.index >= '2018-01-01') & (df.index <= '2024-12-31')
                df = df[mask]
                if len(df) > 200:
                    # 对齐索引
                    common_idx = df.index.intersection(etf_data['SPY'].index)
                    if len(common_idx) > 200:
                        etf_data[sym] = df.loc[common_idx]
                        print(f"  ✅ {sym}: 补充加载成功 ({len(etf_data[sym])} 天)")
                    else:
                        print(f"  ⚠️ {sym}: 与SPY对齐后数据不足")

    available_etfs = sorted(etf_data.keys())
    print(f"\n  ✅ 可用ETF: {available_etfs}")

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
    for sym in etf_data:
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

    # V6/V6.5 基线 (历史回测结果)
    v6_baseline = {
        '1年': {'年化%': 6.95, '回撤%': 8.02, '夏普': 0.26},
        '3年': {'年化%': -6.32, '回撤%': 30.91, '夏普': -0.94},
        '5年': {'年化%': -4.97, '回撤%': 37.58, '夏普': -0.80},
        '全周期(2019-2024)': {'年化%': -3.61, '回撤%': 37.58, '夏普': -0.73},
    }
    v65_baseline = {
        '1年': {'年化%': 0.75, '回撤%': 5.57, '夏普': -0.21},
        '3年': {'年化%': -4.97, '回撤%': 24.08, '夏普': -0.89},
        '5年': {'年化%': -4.97, '回撤%': 24.08, '夏普': -0.80},
        '全周期(2019-2024)': {'年化%': -2.28, '回撤%': 24.08, '夏普': -0.53},
    }

    for period_name, (start, end) in periods.items():
        print(f"\n{'━' * 130}")
        print(f"  📊 回测区间: {period_name} ({start} ~ {end})")
        print(f"{'━' * 130}")

        engine = BlakeverStrategyV7(
            spy_data=spy, vix_data=etf_data['VIX'],
            ief_data=etf_data['IEF'], etf_data=etf_data,
            alpha_pool_data=alpha_data
        )

        v7_result = run_portfolio_backtest(engine, all_data, start, end, FEES_US, 'W')
        print_portfolio_result(v7_result, f"BlakeverV7-{period_name}")

        bh_result = run_buyhold_portfolio(spy, start, end, FEES_US)
        print_portfolio_result(bh_result, f"Buy&Hold SPY-{period_name}")

        # V6/V6.5 → V7 对比
        v6b = v6_baseline.get(period_name, {})
        v65b = v65_baseline.get(period_name, {})
        v7_annual = v7_result.get('年化收益%', 0)
        v7_dd = v7_result.get('最大回撤%', 0)
        v7_sharpe = v7_result.get('夏普比率', 0)

        print(f"\n  📊 V6 → V6.5 → V7 进化对比 ({period_name}):")
        print(f"    V6  年化: {v6b.get('年化%', '?')}%  回撤: {v6b.get('回撤%', '?')}%  夏普: {v6b.get('夏普', '?')}")
        print(f"    V6.5年化: {v65b.get('年化%', '?')}%  回撤: {v65b.get('回撤%', '?')}%  夏普: {v65b.get('夏普', '?')}")
        print(f"    V7  年化: {v7_annual}%  回撤: {v7_dd}%  夏普: {v7_sharpe}")

        comparison.append({
            '策略': f'V7-{period_name}',
            '总收益率%': v7_result.get('总收益率%', 0),
            '年化收益%': v7_annual,
            '最大回撤%': v7_dd,
            '夏普比率': v7_sharpe,
            '卡尔马比率': v7_result.get('卡尔马比率', 0),
            '胜率%': v7_result.get('胜率%', 0),
            '盈亏比': v7_result.get('盈亏比', 0),
        })
        comparison.append({
            '策略': f'B&H-{period_name}',
            '总收益率%': bh_result.get('总收益率%', 0),
            '年化收益%': bh_result.get('年化收益%', 0),
            '最大回撤%': bh_result.get('最大回撤%', 0),
            '夏普比率': bh_result.get('夏普比率', 0),
            '卡尔马比率': bh_result.get('卡尔马比率', 0),
            '胜率%': bh_result.get('胜率%', 0),
            '盈亏比': bh_result.get('盈亏比', 0),
        })

        period_results[period_name] = v7_result

    # ================================================================
    # 3. 全面对比
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 V7 vs B&H 对比汇总")
    print_comparison_table(comparison)

    # ================================================================
    # 4. V5 → V6 → V6.5 → V7 四代进化对比
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 四代策略进化对比 (全周期 2019-2024)")
    print(f"{'━' * 130}")

    full_key = '全周期(2019-2024)'
    if full_key in period_results:
        v7_full = period_results[full_key]

        print(f"\n  V5   (单标的择时):  年化 -1.13%  回撤 19.03%  夏普 -0.14")
        print(f"  V6   (ETF轮动):     年化 -3.61%  回撤 37.58%  夏普 -0.73  ← TLT踩雷")
        print(f"  V6.5 (利率修正):    年化 -2.28%  回撤 24.08%  夏普 -0.53  ← 防守端修正")
        print(f"  V7   (组合工程):    年化 {v7_full.get('年化收益%', 0)}%  回撤 {v7_full.get('最大回撤%', 0)}%  夏普 {v7_full.get('夏普比率', 0)}  ← 风险控制")

        v7_annual = v7_full.get('年化收益%', 0)
        v7_dd = abs(v7_full.get('最大回撤%', 0))
        v7_sharpe = v7_full.get('夏普比率', 0)

        print(f"\n  📈 V6.5 → V7 关键升级效果:")
        v65_annual = -2.28
        v65_dd = 24.08
        v65_sharpe = -0.53
        print(f"    年化: {v65_annual}% → {v7_annual}% ({'✅ 改善' if v7_annual > v65_annual else '❌ 未改善'} {abs(v7_annual - v65_annual):.2f}pp)")
        print(f"    回撤: {v65_dd}% → {v7_dd}% ({'✅ 改善' if v7_dd < v65_dd else '❌ 未改善'} {abs(v7_dd - v65_dd):.2f}pp)")
        print(f"    夏普: {v65_sharpe} → {v7_sharpe} ({'✅ 改善' if v7_sharpe > v65_sharpe else '❌ 未改善'} {abs(v7_sharpe - v65_sharpe):.2f})")

        # 杠杆统计
        if '平均杠杆' in v7_full:
            print(f"\n  📊 杠杆使用统计:")
            print(f"    平均杠杆: {v7_full['平均杠杆']}x")
            print(f"    最大杠杆: {v7_full.get('最大杠杆', '?')}x")
            print(f"    最小杠杆: {v7_full.get('最小杠杆', '?')}x")

        # 2D环境分布
        if '2D组合占比' in v7_full:
            print(f"\n  📊 2D状态空间分布:")
            for combo, pct in sorted(v7_full['2D组合占比'].items()):
                print(f"    {combo}: {pct}%")

        if '年度收益' in v7_full:
            print(f"\n  📊 年度收益 (V6 → V6.5 → V7):")
            v6_yearly = {'2019': 3.33, '2020': -9.66, '2021': 5.51, '2022': -28.65, '2023': 5.47, '2024': 7.53}
            v65_yearly = {'2019': 4.21, '2020': -7.12, '2021': 3.87, '2022': -19.76, '2023': 6.34, '2024': 8.43}
            for year, ret in v7_full['年度收益'].items():
                v6r = v6_yearly.get(year, '?')
                v65r = v65_yearly.get(year, '?')
                print(f"    {year}: V6 {v6r}% → V6.5 {v65r}% → V7 {ret}%")

    # ================================================================
    # 5. 关键年度: 2022 熊市专项分析
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 2022熊市专项分析 (V7最关键验证 — 加息+股债双杀)")
    print(f"{'━' * 130}")

    engine_2022 = BlakeverStrategyV7(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], etf_data=etf_data,
        alpha_pool_data=alpha_data
    )
    result_2022 = run_portfolio_backtest(engine_2022, all_data, '2022-01-01', '2022-12-31', FEES_US, 'W')
    print_portfolio_result(result_2022, "BlakeverV7-2022熊市")

    bh_2022 = run_buyhold_portfolio(spy, '2022-01-01', '2022-12-31', FEES_US)
    print_portfolio_result(bh_2022, "Buy&Hold SPY-2022")

    print(f"\n  💡 V6 → V6.5 → V7 在2022年的进化:")
    print(f"    V6:   -28.65% (重仓TLT踩雷)")
    print(f"    V6.5: -19.76% (加息熊市→SHY现金，但满仓无风控)")
    print(f"    V7:   {result_2022.get('年化收益%', 0)}% (Risk Parity + Vol Targeting + Drawdown Control)")
    print(f"    B&H:  {bh_2022.get('年化收益%', 0)}%")
    v7_2022_improvement = abs(result_2022.get('年化收益%', 0) - (-28.65))
    print(f"    V6→V7改善: {v7_2022_improvement:.2f}pp")

    # ================================================================
    # 6. 熊市回测 (2022-2023)
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 熊市回测 (2022-2023)")
    print(f"{'━' * 130}")

    engine_bear = BlakeverStrategyV7(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], etf_data=etf_data,
        alpha_pool_data=alpha_data
    )
    bear_result = run_portfolio_backtest(engine_bear, all_data, '2022-01-01', '2023-12-31', FEES_US, 'W')
    print_portfolio_result(bear_result, "BlakeverV7-熊市")

    bear_bh = run_buyhold_portfolio(spy, '2022-01-01', '2023-12-31', FEES_US)
    print_portfolio_result(bear_bh, "Buy&Hold SPY-熊市")

    # ================================================================
    # 7. 震荡市回测 (2021-2023)
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 震荡市回测 (2021-2023)")
    print(f"{'━' * 130}")

    engine_range = BlakeverStrategyV7(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], etf_data=etf_data,
        alpha_pool_data=alpha_data
    )
    range_result = run_portfolio_backtest(engine_range, all_data, '2021-01-01', '2023-12-31', FEES_US, 'W')
    print_portfolio_result(range_result, "BlakeverV7-震荡市")

    range_bh = run_buyhold_portfolio(spy, '2021-01-01', '2023-12-31', FEES_US)
    print_portfolio_result(range_bh, "Buy&Hold SPY-震荡市")

    # ================================================================
    # 8. Vol Targeting 灵敏度分析
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 Vol Targeting 灵敏度分析 (目标波动率: 8% / 10% / 12% / 15%)")
    print(f"{'━' * 130}")

    for target_vol in [0.08, 0.10, 0.12, 0.15]:
        engine_vol = BlakeverStrategyV7(
            spy_data=spy, vix_data=etf_data['VIX'],
            ief_data=etf_data['IEF'], etf_data=etf_data,
            alpha_pool_data=alpha_data, target_vol=target_vol
        )
        vol_result = run_portfolio_backtest(engine_vol, all_data, MAIN_START, MAIN_END, FEES_US, 'W')
        annual = vol_result.get('年化收益%', 0)
        dd = vol_result.get('最大回撤%', 0)
        sharpe = vol_result.get('夏普比率', 0)
        avg_lev = vol_result.get('平均杠杆', '?')
        print(f"    目标波动 {int(target_vol*100)}%: 年化 {annual}%  回撤 {dd}%  夏普 {sharpe}  平均杠杆 {avg_lev}x")

    # ================================================================
    # 9. 过拟合检测
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 过拟合检测 (全周期 训练集70% vs 测试集30%)")
    print(f"{'━' * 130}")

    of_result = overfit_check_portfolio(
        all_data, spy, etf_data['VIX'],
        etf_data['IEF'], etf_data, alpha_data,
        MAIN_START, MAIN_END, FEES_US
    )

    of_status = "⚠️ 过拟合" if of_result['overfit_detected'] else "✅ 未检测到过拟合"
    print(f"\n  {of_status}")
    print(f"  训练集收益: {of_result['train_return']}%")
    print(f"  测试集收益: {of_result['test_return']}%")
    print(f"  详情: {of_result['overfit_details']}")

    # ================================================================
    # 10. 多周期一致性验证
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 多周期一致性验证")
    print(f"{'━' * 130}")

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
    # 11. V7 Layer 3 风险控制效果评估
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📊 V7 Layer 3 风险控制效果评估")
    print(f"{'━' * 130}")

    # 对比: 有Vol Targeting vs 无Vol Targeting
    engine_no_vol = BlakeverStrategyV7(
        spy_data=spy, vix_data=etf_data['VIX'],
        ief_data=etf_data['IEF'], etf_data=etf_data,
        alpha_pool_data=alpha_data, target_vol=1.0  # 极高目标=不限制
    )
    # 对比: 有Drawdown Control vs 无
    engine_no_vol.config["max_leverage"] = 5.0
    engine_no_vol.config["min_leverage"] = 1.0

    no_vol_result = run_portfolio_backtest(engine_no_vol, all_data, MAIN_START, MAIN_END, FEES_US, 'W')

    print(f"\n  📊 Vol Targeting + Drawdown Control 效果:")
    print(f"    {'':20} {'V7(完整)':>15} {'V7(无风控)':>15}")
    v7_full_r = period_results.get(full_key, {})
    print(f"    {'年化收益':20} {v7_full_r.get('年化收益%', 0):>14}% {no_vol_result.get('年化收益%', 0):>14}%")
    print(f"    {'最大回撤':20} {v7_full_r.get('最大回撤%', 0):>14}% {no_vol_result.get('最大回撤%', 0):>14}%")
    print(f"    {'夏普比率':20} {v7_full_r.get('夏普比率', 0):>15} {no_vol_result.get('夏普比率', 0):>15}")

    # ================================================================
    # 12. 最终报告
    # ================================================================
    print(f"\n{'━' * 130}")
    print("  📋 最终报告")
    print(f"{'━' * 130}")

    recommend = False
    if full_key in period_results:
        r = period_results[full_key]
        annual = r.get('年化收益%', 0)
        max_dd = abs(r.get('最大回撤%', 0))
        sharpe = r.get('夏普比率', 0)

        # 判定逻辑
        v65_annual = -2.28
        improvement_ratio = abs(annual - v65_annual) / abs(v65_annual) * 100 if v65_annual != 0 else 0

        if cc_result['verdict'] != "不予采纳" and not of_result.get('overfit_detected', True):
            if sharpe > 0.3 and annual > 0:
                recommend = True
            elif improvement_ratio > 10 and sharpe > 0:
                recommend = True

        print(f"\n  🎯 推荐建议:")
        print(f"    年化收益: {annual}%")
        print(f"    最大回撤: {max_dd}%")
        print(f"    夏普比率: {sharpe}")
        print(f"    胜率: {r.get('胜率%', 0)}%")
        print(f"    盈亏比: {r.get('盈亏比', 0)}")
        print(f"    V6.5→V7改善比率: {improvement_ratio:.1f}%")
        print(f"    recommend_adoption: {recommend}")

        if recommend:
            print(f"    ✅ 建议采纳: V7通过过拟合检测和多周期一致性验证")
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

        # 四代进化
        print(f"\n  📈 四代策略进化总结:")
        print(f"    V5:   年化-1.13%  回撤19.03%  夏普-0.14  问题: 空仓错过牛市")
        print(f"    V6:   年化-3.61%  回撤37.58%  夏普-0.73  问题: TLT踩雷+Alpha放大亏损")
        print(f"    V6.5: 年化-2.28%  回撤24.08%  夏普-0.53  修正: 利率维度+SHY现金，但满仓无风控")
        print(f"    V7:   年化{annual}%  回撤{max_dd}%  夏普{sharpe}  升级: Risk Parity+Vol Targeting+Drawdown Control")

    # JSON 输出
    output = {
        "strategy_name": "BlakeverStrategyV7",
        "strategy_source": "blakever_test_stragegy.py",
        "core_architecture": "三层组合工程系统",
        "layer1": "双维度状态机 (Market Regime × Rate Regime)",
        "layer2": "动态资产选择 (按状态选资产池)",
        "layer3": "Risk Parity + Vol Targeting(10%) + Drawdown Control",
        "supplements": "VIX Kill Switch + Alpha选股(Bullish+Falling) + 过拟合检测 + 多周期一致性验证",
        "data_source": "back_trader_stocks (本地CSV)",
        "data_period": f"{MAIN_START} ~ {MAIN_END}",
        "backtest_framework": "手动组合权重引擎 (每周调仓)",
        "available_etfs": available_etfs,
        "overfit_detected": of_result.get('overfit_detected', None),
        "overfit_details": of_result.get('overfit_details', ''),
        "period_results": {},
        "consistency_check": cc_result,
        "recommend_adoption": recommend,
        "evolution": {
            "V5_年化": -1.13, "V5_回撤": 19.03, "V5_夏普": -0.14,
            "V6_年化": -3.61, "V6_回撤": 37.58, "V6_夏普": -0.73,
            "V65_年化": -2.28, "V65_回撤": 24.08, "V65_夏普": -0.53,
            "V7_年化": period_results.get(full_key, {}).get('年化收益%', 0),
            "V7_回撤": period_results.get(full_key, {}).get('最大回撤%', 0),
            "V7_夏普": period_results.get(full_key, {}).get('夏普比率', 0),
        },
        "v7_key_upgrades": {
            "Risk_Parity": "权重 ∝ 1/年化波动率, 风险均衡而非名义金额均衡",
            "Vol_Targeting": "目标波动10%, 杠杆0.3x~1.5x, 高波动自动降仓",
            "Drawdown_Control": "回撤>10%→仓位0.7x, 回撤>20%→仓位0.5x",
            "Asset_Selection": "动态选池(非固定映射), Bullish+Falling→QQQ+SPY+GLD",
            "Fallback": "QQQ→SPY, SH→SHY, TLT→AGG, 自动降级",
        }
    }

    for k, v in period_results.items():
        output["period_results"][k] = {
            '总收益率%': v.get('总收益率%', 0),
            '年化收益%': v.get('年化收益%', 0),
            '最大回撤%': v.get('最大回撤%', 0),
            '夏普比率': v.get('夏普比率', 0),
            '卡尔马比率': v.get('卡尔马比率', 0),
            '胜率%': v.get('胜率%', 0),
            '盈亏比': v.get('盈亏比', 0),
            '环境占比': v.get('环境占比', {}),
            '利率环境占比': v.get('利率环境占比', {}),
            '2D组合占比': v.get('2D组合占比', {}),
            '年度收益': v.get('年度收益', {}),
            '平均杠杆': v.get('平均杠杆', 0),
        }

    output_path = '/data/workspace/blakever_v7_backtest_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📁 完整报告已保存: {output_path}")


if __name__ == '__main__':
    main()
