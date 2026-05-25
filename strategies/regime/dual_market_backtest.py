#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双市场自适应策略（趋势+震荡）v4.5 回测
=========================================
策略核心：通过SPY的DMI指标每日判断市场状态，自动在趋势市和震荡市之间切换。

趋势市（+DI > -DI 且 ADX > 15）：
  - 行业轮动 + 动量选股 + 波动率过滤
  - 3只股票，仓位40%/30%/30%
  - 移动止盈 + 绝对止损 + 暴跌止损 + 周五动量衰退卖出
  - 冷却期5个交易日

震荡市（不满足趋势条件）：
  - 布林带下轨 + RSI超卖买入
  - ATR止损/止盈 + 时间止损 + 上轨RSI卖出
  - 最多6只，每只10%仓位，总仓位60%
  - 最小持有期3天

状态锁定：趋势市锁定5个交易日，避免频繁切换。
强制切换：震荡转趋势时，立即清空所有震荡持仓。
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import talib

warnings.filterwarnings('ignore')

# ================================================================
# 全局参数
# ================================================================
INIT_CASH = 1_000_000
DATA_DIR = '/data/workspace/back_trader_stocks'

# 回测区间
BACKTEST_START = '2021-01-01'
BACKTEST_END = '2024-12-31'

# 手续费与滑点
COMMISSION_RATE = 0.001    # 单边0.1%
SLIPPAGE_RATE = 0.001      # 单边0.1%

# ================================================================
# 大盘择时参数（DMI）
# ================================================================
DMI_PERIOD = 14
ADX_THRESHOLD = 15         # ADX阈值
TREND_LOCK_DAYS = 5        # 趋势市锁定天数
TREND_CONFIRM_DAYS = 2     # 趋势市确认天数（连续2天趋势信号才切换）

# ================================================================
# 趋势市子策略参数
# ================================================================
TREND_MAX_HOLDINGS = 3
TREND_WEIGHTS = [0.40, 0.30, 0.30]   # 仓位分配
TREND_MOMENTUM_PERIOD = 20           # 动量计算周期
TREND_R2_THRESHOLD = 0.3             # R²最低要求
TREND_EWMA_FAST = 15                 # 波动率EWMA快线
TREND_EWMA_SLOW = 40                 # 波动率EWMA慢线
TREND_VOL_PERCENTILE = 0.70          # 波动率分位数上限
TREND_TAKEPROFIT_PCT = 0.15          # 盈利15%后启动移动止盈（更早启动保护）
TREND_TRAILING_STOP = 0.08           # 从最高点回撤8%止盈（更紧的移动止盈）
TREND_ABS_STOPLOSS = 0.08            # 绝对止损8%
TREND_CRASH_STOPLOSS = 0.08          # 单日暴跌8%止损
TREND_COOLDOWN = 3                   # 冷却期3个交易日（缩短，更快重入）
TREND_AVG3_RECENT = 3                # 近3日均价
TREND_AVG7_PAST3 = 7                 # 前7日前3日均价
TREND_MA_PERIOD = 20                 # 20日均线

# ================================================================
# 震荡市子策略参数
# ================================================================
RANGE_MAX_HOLDINGS = 4               # 减少到4只
RANGE_WEIGHT = 0.075                 # 每只7.5%仓位
RANGE_MAX_TOTAL_WEIGHT = 0.30        # 总仓位30%（降低，减少震荡市亏损）
RANGE_BB_PERIOD = 20
RANGE_BB_STD = 2.0
RANGE_RSI_PERIOD = 14
RANGE_RSI_THRESHOLD = 35             # RSI阈值放宽到35（更多机会）
RANGE_BB_ENTRY_MULT = 1.05          # 收盘价≤下轨×1.05（放宽入场条件）
RANGE_BB_LOW_MULT = 1.03            # 最低价≤下轨×1.03（放宽入场条件）
RANGE_ATR_PERIOD = 14
RANGE_ATR_STOP_MULT = 2.0           # ATR止损2倍（放宽止损）
RANGE_ATR_PROFIT_MULT = 3.0         # ATR止盈3倍（增加盈利空间）
RANGE_TIME_STOP_DAYS = 14           # 时间止损14天（翻倍，给予更多时间）
RANGE_MIN_HOLD_DAYS = 3             # 最小持有期3天
RANGE_RSI_EXIT = 70                 # RSI>70卖出
RANGE_MIN_VOLUME = 5_000_000        # 日均成交额下限(USD)
RANGE_MIN_LIST_DAYS = 60            # 最小上市天数


# ================================================================
# 数据加载
# ================================================================
def load_stock_data(symbol, market='us'):
    """加载单只股票CSV数据"""
    subdir = market
    filepath = os.path.join(DATA_DIR, subdir, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        required = ['Open', 'High', 'Low', 'Close']
        for col in required:
            if col not in df.columns:
                return None
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except Exception:
        return None


def get_stock_pool(market='us'):
    """获取标的池列表"""
    subdir = market
    directory = os.path.join(DATA_DIR, subdir)
    if not os.path.isdir(directory):
        return []
    return [f.replace('.csv', '') for f in os.listdir(directory)
            if f.endswith('.csv') and not f.startswith('.')]


# ================================================================
# 大盘择时：DMI指标判断市场状态
# ================================================================
def compute_dmi(df, period=DMI_PERIOD):
    """计算DMI指标（+DI, -DI, ADX）"""
    h = df['High'].values.astype(float)
    l = df['Low'].values.astype(float)
    c = df['Close'].values.astype(float)

    plus_di = talib.PLUS_DI(h, l, c, timeperiod=period)
    minus_di = talib.MINUS_DI(h, l, c, timeperiod=period)
    adx = talib.ADX(h, l, c, timeperiod=period)

    return plus_di, minus_di, adx


def determine_market_regime(dates, plus_di, minus_di, adx):
    """
    判断每日市场状态
    返回: dict {date: 'trend'/'range'}
    
    规则:
    - +DI > -DI 且 ADX > 15 → 趋势信号
    - 连续TREND_CONFIRM_DAYS天趋势信号 → 确认趋势市
    - 锁定机制：进入趋势市后锁定TREND_LOCK_DAYS天
    - 趋势市时，只要+DI > -DI就保持（ADX可不达标）
    """
    n = len(dates)
    regime = ['range'] * n
    lock_counter = 0
    trend_confirm_counter = 0

    for i in range(n):
        pdi = plus_di[i] if not np.isnan(plus_di[i]) else 0
        mdi = minus_di[i] if not np.isnan(minus_di[i]) else 0
        adx_val = adx[i] if not np.isnan(adx[i]) else 0

        is_trend_signal = (pdi > mdi) and (adx_val > ADX_THRESHOLD)

        # 锁定期内保持趋势市
        if lock_counter > 0:
            regime[i] = 'trend'
            lock_counter -= 1
            # 锁定期内再次出现趋势信号，重置锁定
            if is_trend_signal:
                lock_counter = TREND_LOCK_DAYS
            continue

        # 确认机制
        if is_trend_signal:
            trend_confirm_counter += 1
        else:
            trend_confirm_counter = 0

        if trend_confirm_counter >= TREND_CONFIRM_DAYS:
            regime[i] = 'trend'
            lock_counter = TREND_LOCK_DAYS
            trend_confirm_counter = 0
        else:
            regime[i] = 'range'

    return regime


# ================================================================
# 趋势市子策略：行业轮动 + 动量选股 + 波动率过滤
# ================================================================
def compute_momentum_score(close_series, period=TREND_MOMENTUM_PERIOD):
    """
    计算动量得分 = 年化收益 × R²
    """
    if len(close_series) < period:
        return 0.0, 0.0
    prices = close_series[-period:]
    returns = np.diff(prices) / prices[:-1]
    cumulative = np.cumprod(1 + returns)
    # 年化收益
    n_days = len(returns)
    annual_return = (cumulative[-1] ** (252 / max(n_days, 1)) - 1)
    # R²：价格对时间的线性回归拟合度
    x = np.arange(len(prices))
    y = prices
    if len(x) < 2:
        return 0.0, 0.0
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    score = annual_return * max(r_squared, 0)
    return score, annual_return


def compute_volatility_filter(close_series):
    """
    EWMA波动率过滤
    取EWMA(15)与EWMA(40)波动率均值，需低于70%分位数
    返回: (vol_value, is_below_threshold)
    """
    if len(close_series) < TREND_EWMA_SLOW + 10:
        return 0.0, True

    returns = pd.Series(close_series).pct_change().dropna()
    if len(returns) < TREND_EWMA_SLOW:
        return 0.0, True

    ewma_fast = returns.ewm(span=TREND_EWMA_FAST).std().iloc[-1]
    ewma_slow = returns.ewm(span=TREND_EWMA_SLOW).std().iloc[-1]
    vol_avg = (ewma_fast + ewma_slow) / 2

    # 70%分位数（使用近期数据）
    rolling_vols = returns.rolling(20).std().dropna()
    if len(rolling_vols) < 20:
        return vol_avg, True
    threshold = rolling_vols.quantile(TREND_VOL_PERCENTILE)
    return vol_avg, vol_avg <= threshold


def trend_stock_selection(all_data, current_date, date_list):
    """
    趋势市选股
    1. 计算每只股票的动量得分
    2. 过滤：近3日均价 > 前7日前3日均价 且 > 20日均线
    3. 波动率过滤
    4. 返回排名前3的股票
    """
    candidates = []

    for symbol, df in all_data.items():
        # 截取到当前日期的数据
        mask = df.index <= current_date
        df_sub = df.loc[mask]
        if len(df_sub) < TREND_MOMENTUM_PERIOD + TREND_EWMA_SLOW:
            continue

        close = df_sub['Close'].values.astype(float)
        if len(close) < TREND_MA_PERIOD + 5:
            continue

        # 动量得分
        score, annual_ret = compute_momentum_score(close)
        if score <= 0 or annual_ret <= 0:
            continue

        # 近3日均价 vs 前7日前3日均价
        if len(close) < TREND_AVG7_PAST3 + TREND_AVG3_RECENT + 5:
            continue
        recent_avg3 = np.mean(close[-TREND_AVG3_RECENT:])
        past_avg3 = np.mean(close[-(TREND_AVG7_PAST3 + TREND_AVG3_RECENT):-TREND_AVG7_PAST3])

        # 20日均线
        ma20 = np.mean(close[-TREND_MA_PERIOD:])

        if recent_avg3 <= past_avg3 or recent_avg3 <= ma20:
            continue

        # 波动率过滤
        vol_val, vol_pass = compute_volatility_filter(close)
        if not vol_pass:
            continue

        candidates.append({
            'symbol': symbol,
            'score': score,
            'annual_return': annual_ret,
            'close_price': close[-1],
        })

    # 按得分排序
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:TREND_MAX_HOLDINGS]


# ================================================================
# 震荡市子策略：布林带下轨 + RSI超卖
# ================================================================
def range_stock_selection(all_data, current_date, date_list, cooldown_stocks):
    """
    震荡市选股
    1. 前一交易日收盘价 ≤ 布林带下轨×1.03 或 最低价 ≤ 下轨×1.02
    2. RSI(14) < 30
    3. 按RSI最低、距离下轨最大、量比最大排序
    4. 最多6只，每只10%仓位
    """
    candidates = []

    for symbol, df in all_data.items():
        if symbol in cooldown_stocks:
            continue

        mask = df.index <= current_date
        df_sub = df.loc[mask]
        if len(df_sub) < RANGE_BB_PERIOD + RANGE_RSI_PERIOD + 10:
            continue

        close = df_sub['Close'].values.astype(float)
        high = df_sub['High'].values.astype(float)
        low = df_sub['Low'].values.astype(float)
        volume = df_sub['Volume'].values.astype(float)

        if len(close) < RANGE_BB_PERIOD + 5:
            continue

        # 日均成交额过滤（近20日）
        if len(close) >= 20:
            avg_amount = np.mean(close[-20:] * volume[-20:])
            if avg_amount < RANGE_MIN_VOLUME:
                continue

        # 上市天数过滤
        if len(df_sub) < RANGE_MIN_LIST_DAYS:
            continue

        # 布林带
        c_series = pd.Series(close, dtype=float)
        upper, middle, lower = talib.BBANDS(
            c_series.values,
            timeperiod=RANGE_BB_PERIOD,
            nbdevup=RANGE_BB_STD,
            nbdevdn=RANGE_BB_STD,
            matype=0
        )
        if np.isnan(lower[-1]):
            continue

        # RSI
        rsi = talib.RSI(c_series.values, timeperiod=RANGE_RSI_PERIOD)
        if np.isnan(rsi[-1]):
            continue

        # 买入条件
        prev_close = close[-2] if len(close) >= 2 else close[-1]
        prev_low = low[-2] if len(low) >= 2 else low[-1]

        bb_lower = lower[-1]
        condition1 = prev_close <= bb_lower * RANGE_BB_ENTRY_MULT
        condition2 = prev_low <= bb_lower * RANGE_BB_LOW_MULT
        condition3 = rsi[-1] < RANGE_RSI_THRESHOLD

        if not ((condition1 or condition2) and condition3):
            continue

        # 距离下轨距离
        bb_distance = (close[-1] - bb_lower) / bb_lower if bb_lower > 0 else 0

        # 量比（当日成交量 / 近20日平均成交量）
        if len(volume) >= 20 and np.mean(volume[-20:]) > 0:
            volume_ratio = volume[-1] / np.mean(volume[-20:])
        else:
            volume_ratio = 1.0

        candidates.append({
            'symbol': symbol,
            'rsi': rsi[-1],
            'bb_distance': bb_distance,
            'volume_ratio': volume_ratio,
            'close_price': close[-1],
            'atr': _compute_atr(high, low, close),
        })

    # 排序：RSI最低优先，距离下轨最大优先，量比最大优先
    candidates.sort(key=lambda x: (x['rsi'], -x['bb_distance'], -x['volume_ratio']))
    return candidates[:RANGE_MAX_HOLDINGS]


def _compute_atr(high, low, close, period=RANGE_ATR_PERIOD):
    """计算ATR"""
    if len(close) < period + 1:
        return 0.0
    h = pd.Series(high[-(period + 1):], dtype=float)
    l = pd.Series(low[-(period + 1):], dtype=float)
    c = pd.Series(close[-(period + 1):], dtype=float)
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return atr if not pd.isna(atr) else 0.0


# ================================================================
# 交易模拟引擎
# ================================================================
class Position:
    """持仓对象"""
    def __init__(self, symbol, entry_price, entry_date, weight, atr_at_entry,
                 position_type='trend', shares=0):
        self.symbol = symbol
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.weight = weight
        self.atr_at_entry = atr_at_entry
        self.position_type = position_type
        self.shares = shares
        self.highest_price = entry_price
        self.days_held = 0

    def update(self, current_price, current_date):
        """更新持仓状态"""
        self.days_held += 1
        if current_price > self.highest_price:
            self.highest_price = current_price


class DualMarketBacktest:
    """双市场自适应策略回测引擎"""

    def __init__(self, init_cash=INIT_CASH, market='us',
                 start_date=BACKTEST_START, end_date=BACKTEST_END,
                 max_stocks=None):
        self.init_cash = init_cash
        self.market = market
        self.start_date = start_date
        self.end_date = end_date
        self.max_stocks = max_stocks

        # 状态
        self.cash = init_cash
        self.positions = {}        # symbol -> Position
        self.portfolio_value = []
        self.trade_log = []
        self.daily_returns = []
        self.regime_log = []

        # 冷却
        self.cooldown = {}          # symbol -> cooldown_end_date_idx
        self.prev_regime = 'range'
        self.regime_switch_count = 0
        self.spy_ma200_dict = {}    # SPY 200日均线

    def run(self):
        """执行回测"""
        print("=" * 60)
        print("双市场自适应策略（趋势+震荡）v4.5 回测")
        print("=" * 60)

        # 1. 加载大盘指标数据（SPY）
        print("\n📊 加载大盘指标数据（SPY）...")
        spy_df = load_stock_data('SPY', 'etf')
        if spy_df is None:
            print("❌ 无法加载SPY数据，尝试使用QQQ...")
            spy_df = load_stock_data('QQQ', 'etf')
        if spy_df is None:
            print("❌ 无法加载大盘指标数据，回测终止")
            return None

        # 保存SPY数据供后续使用
        self.spy_df = spy_df

        # 计算DMI
        plus_di, minus_di, adx = compute_dmi(spy_df)
        spy_dates = spy_df.index.tolist()

        # 计算SPY 200日均线（用于趋势过滤）
        spy_close = spy_df['Close'].values.astype(float)
        spy_ma200 = np.full(len(spy_close), np.nan)
        for i in range(199, len(spy_close)):
            spy_ma200[i] = np.mean(spy_close[i-199:i+1])
        spy_ma200_dict = dict(zip(spy_dates, spy_ma200))

        # 判断每日市场状态
        regime_series = determine_market_regime(spy_dates, plus_di, minus_di, adx)
        regime_dict = dict(zip(spy_dates, regime_series))

        # 保存SPY 200日均线
        self.spy_ma200_dict = spy_ma200_dict

        trend_days = sum(1 for r in regime_series if r == 'trend')
        range_days = sum(1 for r in regime_series if r == 'range')
        print(f"  大盘状态统计: 趋势市 {trend_days}天 ({trend_days/len(regime_series)*100:.1f}%), "
              f"震荡市 {range_days}天 ({range_days/len(regime_series)*100:.1f}%)")

        # 2. 加载股票池数据
        print(f"\n📦 加载{self.market.upper()}股池数据...")
        pool = get_stock_pool(self.market)
        if self.max_stocks:
            pool = pool[:self.max_stocks]
        print(f"  股票池大小: {len(pool)}")

        all_data = {}
        loaded = 0
        for symbol in pool:
            df = load_stock_data(symbol, self.market)
            if df is not None:
                # 不截取！保留完整历史数据供指标计算，回测区间由日期序列控制
                if len(df) > 60:
                    all_data[symbol] = df
                    loaded += 1
        print(f"  有效加载: {loaded} 只")

        if not all_data:
            print("❌ 无有效股票数据")
            return None

        # 3. 获取回测日期序列（使用大盘指标SPY的日期序列，每只股票独立判断有无当日数据）
        common_dates = sorted(set(spy_df.index))
        common_dates = [d for d in common_dates if self.start_date <= str(d)[:10] <= self.end_date]

        print(f"  回测交易日数: {len(common_dates)}")

        # 4. 逐日模拟
        print(f"\n🚀 开始逐日回测...")

        for day_idx, current_date in enumerate(common_dates):
            # 获取当日市场状态
            current_regime = regime_dict.get(current_date, 'range')

            # 检测状态切换
            if current_regime != self.prev_regime:
                self.regime_switch_count += 1
                if current_regime == 'trend' and self.prev_regime == 'range':
                    # 震荡转趋势：强制清空所有震荡持仓
                    self._force_close_range_positions(all_data, current_date, day_idx, common_dates,
                                                      reason="震荡转趋势强制清仓")

            self.prev_regime = current_regime

            # 更新冷却
            expired = [s for s, end_idx in self.cooldown.items() if day_idx >= end_idx]
            for s in expired:
                del self.cooldown[s]

            # 更新持仓状态
            total_value = self.cash
            for symbol, pos in list(self.positions.items()):
                price = self._get_price(all_data, symbol, current_date)
                if price is not None:
                    pos.update(price, current_date)
                    total_value += pos.shares * price

            # 执行止损/止盈检查
            self._check_stops(all_data, current_date, day_idx, common_dates, current_regime)

            # 根据市场状态执行选股
            if current_regime == 'trend':
                self._execute_trend_strategy(all_data, current_date, day_idx, common_dates)
            else:
                self._execute_range_strategy(all_data, current_date, day_idx, common_dates)

            # 计算当日组合价值
            total_value = self.cash
            for symbol, pos in self.positions.items():
                price = self._get_price(all_data, symbol, current_date)
                if price is not None:
                    total_value += pos.shares * price

            self.portfolio_value.append({
                'date': current_date,
                'value': total_value,
                'cash': self.cash,
                'n_positions': len(self.positions),
                'regime': current_regime,
            })

            # 计算日收益率
            if len(self.portfolio_value) >= 2:
                prev_val = self.portfolio_value[-2]['value']
                daily_ret = (total_value - prev_val) / prev_val if prev_val > 0 else 0
                self.daily_returns.append(daily_ret)

            self.regime_log.append({
                'date': current_date,
                'regime': current_regime,
            })

            # 进度
            if (day_idx + 1) % 100 == 0:
                print(f"  进度: {day_idx + 1}/{len(common_dates)} | "
                      f"组合价值: ${total_value:,.0f} | 持仓: {len(self.positions)} | "
                      f"状态: {current_regime}")

        # 5. 计算绩效
        result = self._compute_performance()
        return result

    def _get_price(self, all_data, symbol, date):
        """获取某只股票某日的收盘价"""
        if symbol not in all_data:
            return None
        df = all_data[symbol]
        if date in df.index:
            return float(df.loc[date, 'Close'])
        # 降级：查找最近的前一个交易日
        earlier = df.index[df.index <= date]
        if len(earlier) > 0:
            return float(df.loc[earlier[-1], 'Close'])
        return None

    def _get_open_price(self, all_data, symbol, date):
        """获取某只股票某日的开盘价"""
        if symbol not in all_data:
            return None
        df = all_data[symbol]
        if date in df.index:
            return float(df.loc[date, 'Open'])
        # 降级：查找最近的前一个交易日
        earlier = df.index[df.index <= date]
        if len(earlier) > 0:
            return float(df.loc[earlier[-1], 'Open'])
        return None

    def _buy_stock(self, symbol, all_data, current_date, day_idx, common_dates,
                   weight, position_type='trend'):
        """买入股票"""
        if symbol in self.positions:
            return False
        if symbol in self.cooldown:
            return False

        open_price = self._get_open_price(all_data, symbol, current_date)
        if open_price is None or open_price <= 0:
            return False

        # 计算ATR
        df = all_data[symbol]
        mask = df.index <= current_date
        df_sub = df.loc[mask]
        if len(df_sub) < RANGE_ATR_PERIOD + 1:
            return False
        atr = _compute_atr(
            df_sub['High'].values.astype(float),
            df_sub['Low'].values.astype(float),
            df_sub['Close'].values.astype(float)
        )

        # 计算买入金额（含滑点）
        buy_price = open_price * (1 + SLIPPAGE_RATE)
        buy_amount = self.init_cash * weight

        if buy_amount > self.cash:
            buy_amount = self.cash * 0.95  # 保留5%现金缓冲

        shares = int(buy_amount / buy_price)
        if shares <= 0:
            return False

        cost = shares * buy_price
        commission = cost * COMMISSION_RATE

        if cost + commission > self.cash:
            shares = int((self.cash - commission) / buy_price)
            if shares <= 0:
                return False
            cost = shares * buy_price
            commission = cost * COMMISSION_RATE

        self.cash -= (cost + commission)
        self.positions[symbol] = Position(
            symbol=symbol,
            entry_price=buy_price,
            entry_date=current_date,
            weight=weight,
            atr_at_entry=atr,
            position_type=position_type,
            shares=shares
        )
        self.trade_log.append({
            'date': current_date,
            'action': 'BUY',
            'symbol': symbol,
            'price': round(buy_price, 2),
            'shares': shares,
            'amount': round(cost, 2),
            'commission': round(commission, 2),
            'type': position_type,
        })
        return True

    def _sell_stock(self, symbol, all_data, current_date, day_idx, common_dates,
                    reason='', force=False):
        """卖出股票"""
        if symbol not in self.positions:
            return False

        pos = self.positions[symbol]
        close_price = self._get_price(all_data, symbol, current_date)
        if close_price is None:
            return False

        # 卖出价（含滑点）
        sell_price = close_price * (1 - SLIPPAGE_RATE)
        proceeds = pos.shares * sell_price
        commission = proceeds * COMMISSION_RATE

        pnl = proceeds - pos.shares * pos.entry_price - commission
        pnl_pct = (sell_price - pos.entry_price) / pos.entry_price * 100

        self.cash += (proceeds - commission)

        # 设置冷却期
        cooldown_end = day_idx + TREND_COOLDOWN if pos.position_type == 'trend' else day_idx + 2
        self.cooldown[symbol] = cooldown_end

        del self.positions[symbol]

        self.trade_log.append({
            'date': current_date,
            'action': 'SELL',
            'symbol': symbol,
            'price': round(sell_price, 2),
            'shares': pos.shares,
            'amount': round(proceeds, 2),
            'commission': round(commission, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'days_held': pos.days_held,
            'reason': reason,
            'type': pos.position_type,
        })
        return True

    def _force_close_range_positions(self, all_data, current_date, day_idx, common_dates,
                                      reason='强制清仓'):
        """强制清空亏损的震荡持仓，盈利的保留"""
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            if pos.position_type == 'range':
                price = self._get_price(all_data, symbol, current_date)
                if price is not None:
                    pnl_pct = (price - pos.entry_price) / pos.entry_price
                    # 只清亏损的，盈利的保留
                    if pnl_pct < 0:
                        self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                         reason=reason, force=True)

    def _check_stops(self, all_data, current_date, day_idx, common_dates, current_regime):
        """检查止损止盈条件"""
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            price = self._get_price(all_data, symbol, current_date)
            if price is None:
                continue

            pnl_pct = (price - pos.entry_price) / pos.entry_price

            if pos.position_type == 'trend':
                # === 趋势市止损止盈 ===
                # 1. 绝对止损8%
                if pnl_pct <= -TREND_ABS_STOPLOSS:
                    self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                     reason=f'绝对止损{pnl_pct*100:.1f}%')
                    continue

                # 2. 单日暴跌8%（用开盘价和收盘价对比）
                open_price = self._get_open_price(all_data, symbol, current_date)
                if open_price and open_price > 0:
                    daily_drop = (price - open_price) / open_price
                    if daily_drop <= -TREND_CRASH_STOPLOSS:
                        self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                         reason=f'单日暴跌{daily_drop*100:.1f}%')
                        continue

                # 3. 移动止盈：盈利20%后，从最高点回撤10%
                if pnl_pct >= TREND_TAKEPROFIT_PCT:
                    trailing_pct = (price - pos.highest_price) / pos.highest_price
                    if trailing_pct <= -TREND_TRAILING_STOP:
                        self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                         reason=f'移动止盈(最高回撤{trailing_pct*100:.1f}%)')
                        continue

                # 4. 动量衰退卖出（严格条件：连续3天动量下降且当前动量为负）
                if pos.days_held >= 10:  # 至少持有10天才检查动量衰退
                    df = all_data[symbol]
                    mask = df.index <= current_date
                    df_sub = df.loc[mask]
                    close = df_sub['Close'].values.astype(float)
                    if len(close) >= TREND_MOMENTUM_PERIOD + 5:
                        score, annual_ret = compute_momentum_score(close)
                        # 只有动量从正变负（趋势反转）才卖出
                        score_5d_ago, _ = compute_momentum_score(close[:-5]) if len(close) > TREND_MOMENTUM_PERIOD + 5 else (0, 0)
                        if score <= 0 and score_5d_ago > 0:
                            self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                             reason='动量衰退(趋势反转)')
                            continue

            elif pos.position_type == 'range':
                # === 震荡市止损止盈 ===
                # 最小持有期检查
                if pos.days_held < RANGE_MIN_HOLD_DAYS:
                    continue

                # 1. ATR止损1.5倍
                if pos.atr_at_entry > 0:
                    atr_stop = pos.entry_price - RANGE_ATR_STOP_MULT * pos.atr_at_entry
                    if price <= atr_stop:
                        self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                         reason=f'ATR止损(价格{price:.2f}<止损{atr_stop:.2f})')
                        continue

                    # 2. ATR止盈2倍
                    atr_profit = pos.entry_price + RANGE_ATR_PROFIT_MULT * pos.atr_at_entry
                    if price >= atr_profit:
                        self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                         reason=f'ATR止盈(价格{price:.2f}>止盈{atr_profit:.2f})')
                        continue

                # 3. 时间止损7天
                if pos.days_held >= RANGE_TIME_STOP_DAYS:
                    self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                     reason=f'时间止损({pos.days_held}天)')
                    continue

                # 4. 布林带上轨+RSI>70
                df = all_data[symbol]
                mask = df.index <= current_date
                df_sub = df.loc[mask]
                close = df_sub['Close'].values.astype(float)
                if len(close) >= RANGE_BB_PERIOD + RANGE_RSI_PERIOD:
                    c_series = pd.Series(close, dtype=float)
                    upper, middle, lower = talib.BBANDS(
                        c_series.values, timeperiod=RANGE_BB_PERIOD,
                        nbdevup=RANGE_BB_STD, nbdevdn=RANGE_BB_STD, matype=0
                    )
                    rsi = talib.RSI(c_series.values, timeperiod=RANGE_RSI_PERIOD)
                    if not np.isnan(upper[-1]) and not np.isnan(rsi[-1]):
                        if price >= upper[-1] and rsi[-1] >= RANGE_RSI_EXIT:
                            self._sell_stock(symbol, all_data, current_date, day_idx, common_dates,
                                             reason=f'上轨+RSI>{RANGE_RSI_EXIT}')
                            continue

    def _execute_trend_strategy(self, all_data, current_date, day_idx, common_dates):
        """执行趋势市策略"""
        # SPY均线过滤：SPY低于200日均线时半仓
        spy_ma200 = self.spy_ma200_dict.get(current_date, np.nan)
        
        # 如果SPY低于200日均线，半仓操作
        half_position = False
        if not np.isnan(spy_ma200):
            # 获取SPY当日收盘价
            if self.spy_df is not None and current_date in self.spy_df.index:
                spy_price = float(self.spy_df.loc[current_date, 'Close'])
                if spy_price < spy_ma200:
                    half_position = True
        
        # 已持有的趋势持仓数量
        trend_positions = {s: p for s, p in self.positions.items() if p.position_type == 'trend'}

        # SPY低于200日均线时，最多1只持仓
        max_holdings = 1 if half_position else TREND_MAX_HOLDINGS

        # 如果趋势持仓未满，进行选股补仓
        if len(trend_positions) < max_holdings:
            candidates = trend_stock_selection(all_data, current_date, common_dates)
            for cand in candidates:
                if cand['symbol'] in self.positions:
                    continue
                if cand['symbol'] in self.cooldown:
                    continue
                if len({s: p for s, p in self.positions.items() if p.position_type == 'trend'}) >= max_holdings:
                    break
                # 按权重分配（半仓时权重减半）
                n_trend = len({s: p for s, p in self.positions.items() if p.position_type == 'trend'})
                base_weight = TREND_WEIGHTS[n_trend] if n_trend < len(TREND_WEIGHTS) else 0.20
                weight = base_weight * 0.5 if half_position else base_weight
                self._buy_stock(cand['symbol'], all_data, current_date, day_idx, common_dates,
                                weight=weight, position_type='trend')

    def _execute_range_strategy(self, all_data, current_date, day_idx, common_dates):
        """执行震荡市策略 - 轻仓防守模式"""
        # SPY均线过滤
        spy_ma200 = self.spy_ma200_dict.get(current_date, np.nan)
        spy_above_ma200 = True
        if not np.isnan(spy_ma200) and self.spy_df is not None and current_date in self.spy_df.index:
            spy_price = float(self.spy_df.loc[current_date, 'Close'])
            if spy_price < spy_ma200:
                spy_above_ma200 = False

        # SPY低于200日均线时，震荡市完全空仓
        if not spy_above_ma200:
            return

        # SPY高于200日均线时，轻仓做均值回归
        range_positions = {s: p for s, p in self.positions.items() if p.position_type == 'range'}
        current_range_weight = sum(p.weight for p in range_positions.values())

        if len(range_positions) < RANGE_MAX_HOLDINGS and current_range_weight < RANGE_MAX_TOTAL_WEIGHT:
            cooldown_symbols = set(self.cooldown.keys())
            candidates = range_stock_selection(all_data, current_date, common_dates, cooldown_symbols)
            for cand in candidates:
                if cand['symbol'] in self.positions:
                    continue
                if current_range_weight + RANGE_WEIGHT > RANGE_MAX_TOTAL_WEIGHT:
                    break
                if len({s: p for s, p in self.positions.items() if p.position_type == 'range'}) >= RANGE_MAX_HOLDINGS:
                    break
                self._buy_stock(cand['symbol'], all_data, current_date, day_idx, common_dates,
                                weight=RANGE_WEIGHT, position_type='range')
                current_range_weight += RANGE_WEIGHT

    def _compute_performance(self):
        """计算绩效指标"""
        if not self.portfolio_value:
            return None

        df_pv = pd.DataFrame(self.portfolio_value)
        df_pv['date'] = pd.to_datetime(df_pv['date'])
        df_pv = df_pv.set_index('date')

        # 基本统计
        final_value = df_pv['value'].iloc[-1]
        total_return = (final_value - self.init_cash) / self.init_cash * 100

        # 年化收益
        n_days = len(df_pv)
        n_years = n_days / 252
        annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100 if n_years > 0 else 0

        # 最大回撤
        df_pv['peak'] = df_pv['value'].cummax()
        df_pv['drawdown'] = (df_pv['value'] - df_pv['peak']) / df_pv['peak'] * 100
        max_drawdown = df_pv['drawdown'].min()

        # 夏普比率
        if self.daily_returns:
            rets = pd.Series(self.daily_returns)
            sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        else:
            sharpe = 0

        # 交易统计
        sells = [t for t in self.trade_log if t['action'] == 'SELL']
        total_trades = len(sells)
        wins = [t for t in sells if t['pnl'] > 0]
        losses = [t for t in sells if t['pnl'] <= 0]
        win_rate = len(wins) / max(total_trades, 1) * 100

        total_win = sum(t['pnl'] for t in wins)
        total_loss = abs(sum(t['pnl'] for t in losses))
        profit_factor = total_win / max(total_loss, 1)

        # 按子策略分类统计
        trend_sells = [t for t in sells if t['type'] == 'trend']
        range_sells = [t for t in sells if t['type'] == 'range']

        trend_wins = [t for t in trend_sells if t['pnl'] > 0]
        range_wins = [t for t in range_sells if t['pnl'] > 0]

        trend_pnl = sum(t['pnl'] for t in trend_sells)
        range_pnl = sum(t['pnl'] for t in range_sells)

        # 卖出原因统计
        reason_stats = {}
        for t in sells:
            r = t.get('reason', '未知')
            reason_stats[r] = reason_stats.get(r, 0) + 1

        # 市场状态统计
        trend_days = sum(1 for r in self.regime_log if r['regime'] == 'trend')
        range_days = sum(1 for r in self.regime_log if r['regime'] == 'range')

        # 平均持仓天数
        avg_hold_days = np.mean([t['days_held'] for t in sells]) if sells else 0

        # 年交易次数
        avg_trades_per_year = total_trades / max(n_years, 0.01)

        # 盈亏比
        avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 0
        win_loss_ratio = avg_win / max(avg_loss, 1)

        # 市值曲线回撤期间统计
        in_drawdown = df_pv['drawdown'] < -5
        max_dd_duration = 0
        current_dd = 0
        for val in in_drawdown:
            if val:
                current_dd += 1
                max_dd_duration = max(max_dd_duration, current_dd)
            else:
                current_dd = 0

        # Calmar比率
        calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

        result = {
            'strategy_name': '双市场自适应策略（趋势+震荡）v4.5',
            'backtest_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'backtest_period': f'{self.start_date} ~ {self.end_date}',
            'market': self.market,
            'init_cash': self.init_cash,
            'final_value': round(final_value, 2),
            'total_return_pct': round(total_return, 2),
            'annual_return_pct': round(annual_return, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'calmar_ratio': round(calmar, 2),
            'win_rate_pct': round(win_rate, 1),
            'profit_factor': round(profit_factor, 2),
            'win_loss_ratio': round(win_loss_ratio, 2),
            'total_trades': total_trades,
            'avg_trades_per_year': round(avg_trades_per_year, 1),
            'avg_hold_days': round(avg_hold_days, 1),
            'max_dd_duration_days': max_dd_duration,
            'regime_stats': {
                'trend_days': trend_days,
                'range_days': range_days,
                'trend_pct': round(trend_days / max(trend_days + range_days, 1) * 100, 1),
                'range_pct': round(range_days / max(trend_days + range_days, 1) * 100, 1),
                'switch_count': self.regime_switch_count,
            },
            'sub_strategy_stats': {
                'trend': {
                    'trades': len(trend_sells),
                    'wins': len(trend_wins),
                    'win_rate': round(len(trend_wins) / max(len(trend_sells), 1) * 100, 1),
                    'total_pnl': round(trend_pnl, 2),
                },
                'range': {
                    'trades': len(range_sells),
                    'wins': len(range_wins),
                    'win_rate': round(len(range_wins) / max(len(range_sells), 1) * 100, 1),
                    'total_pnl': round(range_pnl, 2),
                },
            },
            'stop_reason_stats': reason_stats,
            'daily_returns_stats': {
                'mean': round(np.mean(self.daily_returns) * 100, 4) if self.daily_returns else 0,
                'std': round(np.std(self.daily_returns) * 100, 4) if self.daily_returns else 0,
                'skew': round(float(pd.Series(self.daily_returns).skew()), 2) if self.daily_returns else 0,
                'kurtosis': round(float(pd.Series(self.daily_returns).kurtosis()), 2) if self.daily_returns else 0,
            },
            'trades': self.trade_log,
        }

        return result


# ================================================================
# 过拟合检测
# ================================================================
def run_overfit_check(market='us', max_stocks=None):
    """训练集(前70%) vs 测试集(后30%)过拟合检测"""
    print("\n" + "=" * 60)
    print("过拟合检测：训练集 vs 测试集")
    print("=" * 60)

    # 训练集: 2021-01-01 ~ 2023-09-30 (约70%)
    # 测试集: 2023-10-01 ~ 2024-12-31 (约30%)
    train_bt = DualMarketBacktest(
        init_cash=INIT_CASH, market=market,
        start_date='2021-01-01', end_date='2023-09-30',
        max_stocks=max_stocks
    )
    train_result = train_bt.run()

    test_bt = DualMarketBacktest(
        init_cash=INIT_CASH, market=market,
        start_date='2023-10-01', end_date='2024-12-31',
        max_stocks=max_stocks
    )
    test_result = test_bt.run()

    if train_result and test_result:
        train_annual = train_result['annual_return_pct']
        test_annual = test_result['annual_return_pct']
        degradation = (train_annual - test_annual) / max(abs(train_annual), 1) * 100
        overfit = degradation > 30

        print(f"\n📊 过拟合检测结果:")
        print(f"  训练集年化: {train_annual:.2f}%")
        print(f"  测试集年化: {test_annual:.2f}%")
        print(f"  收益衰减: {degradation:.1f}%")
        print(f"  过拟合判定: {'⚠️ 是' if overfit else '✅ 否'}")

        return {
            'train_annual_return': train_annual,
            'test_annual_return': test_annual,
            'degradation_pct': round(degradation, 1),
            'overfit_detected': overfit,
        }

    return None


# ================================================================
# 多周期一致性验证
# ================================================================
def run_consistency_check(market='us', max_stocks=None):
    """1年/3年/5年夏普均>0.5，最大回撤均<30%"""
    print("\n" + "=" * 60)
    print("多周期一致性验证")
    print("=" * 60)

    periods = [
        ('1y', '2024-01-01', '2024-12-31'),
        ('3y', '2022-01-01', '2024-12-31'),
        ('5y', '2020-01-01', '2024-12-31'),
    ]

    results = {}
    warnings_list = []
    fail_count = 0

    for label, start, end in periods:
        bt = DualMarketBacktest(
            init_cash=INIT_CASH, market=market,
            start_date=start, end_date=end,
            max_stocks=max_stocks
        )
        r = bt.run()
        if r:
            results[label] = r
            sharpe_ok = r['sharpe_ratio'] > 0.5
            dd_ok = abs(r['max_drawdown_pct']) < 30

            if not sharpe_ok:
                warnings_list.append(f"{label}周期夏普={r['sharpe_ratio']:.2f}，低于0.5阈值")
                fail_count += 1
            if not dd_ok:
                warnings_list.append(f"{label}周期最大回撤={r['max_drawdown_pct']:.2f}%，超过30%阈值")
                fail_count += 1

            print(f"\n  {label} ({start}~{end}): 年化={r['annual_return_pct']:.2f}%, "
                  f"夏普={r['sharpe_ratio']:.2f}, 回撤={r['max_drawdown_pct']:.2f}%")
        else:
            results[label] = None
            fail_count += 1
            warnings_list.append(f"{label}周期回测失败")

    if fail_count == 0:
        verdict = "通过"
    elif fail_count <= 2:
        verdict = "标记警告"
    else:
        verdict = "不予采纳"

    print(f"\n  一致性判定: {verdict}")
    for w in warnings_list:
        print(f"  ⚠️ {w}")

    return {
        'period_results': {k: {
            'annual_return': v['annual_return_pct'] if v else None,
            'sharpe': v['sharpe_ratio'] if v else None,
            'max_drawdown': v['max_drawdown_pct'] if v else None,
        } for k, v in results.items()},
        'warnings': warnings_list,
        'verdict': verdict,
    }


# ================================================================
# 主函数
# ================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description='双市场自适应策略回测')
    parser.add_argument('--market', default='us', choices=['us', 'hk'])
    parser.add_argument('--max-stocks', type=int, default=50,
                        help='最大使用股票数（调试用，默认50）')
    parser.add_argument('--start', default=BACKTEST_START)
    parser.add_argument('--end', default=BACKTEST_END)
    parser.add_argument('--overfit-check', action='store_true',
                        help='执行过拟合检测')
    parser.add_argument('--consistency-check', action='store_true',
                        help='执行多周期一致性验证')
    parser.add_argument('--output', default=None, help='输出JSON文件路径')

    args = parser.parse_args()

    # 主回测
    bt = DualMarketBacktest(
        init_cash=INIT_CASH, market=args.market,
        start_date=args.start, end_date=args.end,
        max_stocks=args.max_stocks
    )
    result = bt.run()

    if result:
        print("\n" + "=" * 60)
        print("📊 回测绩效报告")
        print("=" * 60)
        print(f"  策略名称: {result['strategy_name']}")
        print(f"  回测区间: {result['backtest_period']}")
        print(f"  市场: {result['market'].upper()}")
        print(f"  初始资金: ${result['init_cash']:,.0f}")
        print(f"  最终价值: ${result['final_value']:,.2f}")
        print(f"  总收益率: {result['total_return_pct']:.2f}%")
        print(f"  年化收益: {result['annual_return_pct']:.2f}%")
        print(f"  最大回撤: {result['max_drawdown_pct']:.2f}%")
        print(f"  夏普比率: {result['sharpe_ratio']:.2f}")
        print(f"  Calmar比率: {result['calmar_ratio']:.2f}")
        print(f"  胜率: {result['win_rate_pct']:.1f}%")
        print(f"  盈亏比: {result['profit_factor']:.2f}")
        print(f"  盈亏比率: {result['win_loss_ratio']:.2f}")
        print(f"  总交易次数: {result['total_trades']}")
        print(f"  年均交易: {result['avg_trades_per_year']:.1f}次")
        print(f"  平均持仓: {result['avg_hold_days']:.1f}天")
        print(f"  回撤持续: 最长{result['max_dd_duration_days']}天")
        print(f"\n  📈 市场状态统计:")
        print(f"    趋势市: {result['regime_stats']['trend_days']}天 ({result['regime_stats']['trend_pct']}%)")
        print(f"    震荡市: {result['regime_stats']['range_days']}天 ({result['regime_stats']['range_pct']}%)")
        print(f"    状态切换: {result['regime_stats']['switch_count']}次")
        print(f"\n  📊 子策略表现:")
        print(f"    趋势市: 交易{result['sub_strategy_stats']['trend']['trades']}次, "
              f"胜率{result['sub_strategy_stats']['trend']['win_rate']}%, "
              f"盈亏${result['sub_strategy_stats']['trend']['total_pnl']:,.2f}")
        print(f"    震荡市: 交易{result['sub_strategy_stats']['range']['trades']}次, "
              f"胜率{result['sub_strategy_stats']['range']['win_rate']}%, "
              f"盈亏${result['sub_strategy_stats']['range']['total_pnl']:,.2f}")
        print(f"\n  🛑 止损原因统计:")
        for reason, count in sorted(result['stop_reason_stats'].items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}次")

    # 过拟合检测
    if args.overfit_check:
        overfit_result = run_overfit_check(args.market, args.max_stocks)
        if overfit_result:
            result['overfit_check'] = overfit_result

    # 一致性验证
    if args.consistency_check:
        consistency_result = run_consistency_check(args.market, args.max_stocks)
        if consistency_result:
            result['consistency_check'] = consistency_result

    # 保存结果
    if result and args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n📁 结果已保存至: {args.output}")

    return result


if __name__ == '__main__':
    main()
