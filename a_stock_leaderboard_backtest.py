#!/usr/bin/env python3
"""
A股排行榜策略回测 — 验证美股排行榜策略在A股的有效性
================================================
将穿越牛熊排行榜TOP10策略适配到A股ETF进行回测：
  SPY → 510300(沪深300ETF)    - 大盘宽基
  QQQ → 159915(创业板ETF)    - 成长/科技
  VEA → 510500(中证500ETF)   - 中盘
  AGG → 511010(国债ETF)      - 安全体
  SHY → 511880(银华日利)     - 现金管理
  GLD → 518880(黄金ETF)      - 避险

回测期间: 2021-01-01 ~ 2025-04-24
基准: 沪深300ETF买入持有
费率: A股印花税0.05%(卖出) + 佣金0.025%(双向) ≈ 单边0.075%
T+1约束: 买入次日才能卖出
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ============ 全局配置 ============
DATA_DIR = Path('/data/workspace/back_trader_stocks/a')
START_DATE = '2021-01-01'
END_DATE = '2025-04-24'
INIT_CASH = 1_000_000

# A股费率: 印花税0.05%(卖出) + 佣金0.025%(双向) + 滑点0.05%
A_STOCK_FEES = 0.0005 + 0.00025 * 2 + 0.0005  # ≈ 0.15% 单边
# ETF费率更低: 无印花税 + 佣金0.015%(双向) + 滑点0.03%
ETF_FEES = 0.00015 * 2 + 0.0003  # ≈ 0.06% 单边

# A股标的映射
A_STOCK_MAP = {
    'SPY': '510300_XSHG',    # 沪深300ETF
    'QQQ': '159915_XSHE',    # 创业板ETF
    'VEA': '510500_XSHG',    # 中证500ETF
    'AGG': '511010_XSHG',    # 国债ETF
    'SHY': '511880_XSHG',    # 银华日利
    'GLD': '518880_XSHG',    # 黄金ETF
}


def load_etf_data(jq_code: str) -> pd.DataFrame:
    """加载ETF CSV数据，返回Date索引的DataFrame"""
    csv_path = DATA_DIR / f'{jq_code}.csv'
    if not csv_path.exists():
        print(f"  ⚠️ {jq_code} 数据不存在")
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    # 过滤日期范围
    df = df.loc[START_DATE:END_DATE]
    return df


def load_all_etfs() -> dict:
    """加载所有A股ETF数据"""
    data = {}
    for us_sym, a_sym in A_STOCK_MAP.items():
        df = load_etf_data(a_sym)
        if not df.empty:
            data[us_sym] = df
            print(f"  ✓ {us_sym}({a_sym}): {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
    return data


def calc_rsi(series, period=2):
    """计算RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_sma(series, period):
    return series.rolling(window=period).mean()


def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ============ 回测引擎 ============

def backtest_etf_rotation(data: dict, generate_signals, strategy_name: str,
                          fees_rate=ETF_FEES, t_plus_1=True):
    """
    通用ETF轮动回测引擎
    
    Args:
        data: {us_sym: DataFrame} ETF价格数据
        generate_signals: function(data, date) -> str (返回持仓的us_sym)
        strategy_name: 策略名称
        fees_rate: 单边费率
        t_plus_1: 是否T+1
    
    Returns:
        dict with backtest results
    """
    # 构建统一日期索引（取所有ETF的交集）
    all_dates = None
    for sym, df in data.items():
        if all_dates is None:
            all_dates = set(df.index)
        else:
            all_dates = all_dates & set(df.index)
    all_dates = sorted(all_dates)
    
    if len(all_dates) < 100:
        return None
    
    # 构建close price DataFrame
    close_dict = {}
    for sym, df in data.items():
        close_dict[sym] = df['Close']
    close_prices = pd.DataFrame(close_dict, index=all_dates)
    
    # 生成持仓信号序列
    holding_list = []
    for date in all_dates:
        h = generate_signals(data, date, close_prices)
        holding_list.append(h)
    
    holding = pd.Series(holding_list, index=all_dates)
    
    # 计算日收益
    daily_returns = close_prices.pct_change().fillna(0)
    portfolio_returns = pd.Series(0.0, index=all_dates)
    
    prev_asset = None
    trade_count = 0
    
    for i, date in enumerate(all_dates):
        current_asset = holding.loc[date]
        
        if current_asset is not None and current_asset in daily_returns.columns:
            r = daily_returns.loc[date, current_asset]
            portfolio_returns.loc[date] = r if pd.notna(r) else 0
        
        # 换仓成本
        if prev_asset is not None and prev_asset != current_asset:
            trade_count += 1
            portfolio_returns.loc[date] -= fees_rate
        
        prev_asset = current_asset
    
    # 计算核心指标
    cum = (1 + portfolio_returns).cumprod()
    final_value = INIT_CASH * cum.iloc[-1]
    n_years = len(all_dates) / 252
    total_return = (final_value / INIT_CASH - 1) * 100
    annual_return = ((1 + total_return / 100) ** (1 / max(n_years, 0.01)) - 1) * 100
    
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = abs(dd.min()) * 100
    
    # 夏普比率（无风险利率2%）
    rf = 0.02
    sharpe = (portfolio_returns.mean() * 252 - rf) / (portfolio_returns.std() * np.sqrt(252)) if portfolio_returns.std() > 0 else 0
    calmar = annual_return / max_dd if max_dd > 0 else 0
    
    # 盈亏比
    gains = portfolio_returns[portfolio_returns > 0]
    losses = portfolio_returns[portfolio_returns < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 10.0
    
    # 胜率
    win_days = (portfolio_returns > 0).sum()
    total_active_days = (portfolio_returns != 0).sum()
    win_rate = win_days / max(total_active_days, 1) * 100
    
    annual_trades = trade_count / max(n_years, 0.01)
    
    # 持仓分布
    holding_counts = holding.value_counts()
    holding_dist = (holding_counts / len(holding) * 100).to_dict()
    holding_dist = {k: round(v, 1) for k, v in holding_dist.items()}
    
    return {
        'strategy_name': strategy_name,
        'annual_return': round(annual_return, 2),
        'total_return': round(total_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(annual_trades, 1),
        'holding_distribution': holding_dist,
        'final_value': round(final_value, 0),
        'n_years': round(n_years, 2),
        'trade_count': trade_count,
    }


# ============ 策略信号生成函数 ============

def gem_signal(data, date, close_prices, lookback_months=9, buffer_days=5,
               risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']):
    """GEM双重动量信号: 相对动量(最强) + 绝对动量(>均线)"""
    all_assets = risk_assets + safe_assets
    
    lookback_days = lookback_months * 21
    buffer_offset = buffer_days
    
    # 获取当前日期在close_prices中的位置
    if date not in close_prices.index:
        return safe_assets[0]
    
    idx = close_prices.index.get_loc(date)
    if idx < lookback_days + buffer_offset:
        return safe_assets[0]
    
    ref_date = close_prices.index[idx - buffer_offset]
    past_date = close_prices.index[max(0, idx - lookback_days - buffer_offset)]
    
    # 相对动量：风险资产中涨幅最大的
    best_risk = None
    best_risk_return = -999
    
    for sym in risk_assets:
        if sym in close_prices.columns:
            try:
                current = close_prices.loc[ref_date, sym]
                past = close_prices.loc[past_date, sym]
                if pd.notna(current) and pd.notna(past) and past > 0:
                    ret = current / past - 1
                    if ret > best_risk_return:
                        best_risk_return = ret
                        best_risk = sym
            except:
                continue
    
    # 绝对动量：最佳风险资产是否在均线上方
    if best_risk is not None and best_risk_return > 0:
        return best_risk
    
    # 避险：选择安全资产中表现最好的
    best_safe = safe_assets[0]
    best_safe_return = -999
    for sym in safe_assets:
        if sym in close_prices.columns:
            try:
                current = close_prices.loc[ref_date, sym]
                past = close_prices.loc[past_date, sym]
                if pd.notna(current) and pd.notna(past) and past > 0:
                    ret = current / past - 1
                    if ret > best_safe_return:
                        best_safe_return = ret
                        best_safe = sym
            except:
                continue
    
    return best_safe


def dual_momentum_signal(data, date, close_prices, lookback_months=9, buffer_days=3,
                         abs_threshold=0, risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']):
    """双重动量: 相对+绝对>阈值"""
    lookback_days = lookback_months * 21
    
    if date not in close_prices.index:
        return safe_assets[0]
    
    idx = close_prices.index.get_loc(date)
    if idx < lookback_days + buffer_days:
        return safe_assets[0]
    
    ref_date = close_prices.index[idx - buffer_days]
    past_date = close_prices.index[max(0, idx - lookback_days - buffer_days)]
    
    # 相对动量
    best_risk = None
    best_risk_return = -999
    
    for sym in risk_assets:
        if sym in close_prices.columns:
            try:
                current = close_prices.loc[ref_date, sym]
                past = close_prices.loc[past_date, sym]
                if pd.notna(current) and pd.notna(past) and past > 0:
                    ret = current / past - 1
                    if ret > best_risk_return:
                        best_risk_return = ret
                        best_risk = sym
            except:
                continue
    
    # 绝对动量阈值
    if best_risk is not None and best_risk_return > abs_threshold / 100:
        return best_risk
    
    # 避险
    best_safe = safe_assets[0]
    best_safe_return = -999
    for sym in safe_assets:
        if sym in close_prices.columns:
            try:
                current = close_prices.loc[ref_date, sym]
                past = close_prices.loc[past_date, sym]
                if pd.notna(current) and pd.notna(past) and past > 0:
                    ret = current / past - 1
                    if ret > best_safe_return:
                        best_safe_return = ret
                        best_safe = sym
            except:
                continue
    
    return best_safe


def rsi2_mean_reversion_signal(data, date, close_prices, rsi_buy=10, rsi_sell=80, target='QQQ'):
    """RSI(2)严格均值回归: RSI<10买入, RSI>80卖出, 不持有则持有安全资产"""
    if date not in close_prices.index:
        return 'SHY'
    
    idx = close_prices.index.get_loc(date)
    if idx < 5:
        return 'SHY'
    
    if target not in close_prices.columns:
        return 'SHY'
    
    # 计算RSI(2)
    closes = close_prices[target].iloc[:idx+1]
    if len(closes) < 3:
        return 'SHY'
    
    rsi2 = calc_rsi(closes, 2)
    current_rsi = rsi2.iloc[-1]
    
    if pd.isna(current_rsi):
        return 'SHY'
    
    if current_rsi < rsi_buy:
        return target
    elif current_rsi > rsi_sell:
        return 'SHY'
    else:
        return None  # 维持当前仓位


def macd_trend_signal(data, date, close_prices, fast=8, slow=21, signal_period=9,
                      risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']):
    """MACD金叉死叉趋势策略"""
    if date not in close_prices.index:
        return safe_assets[0]
    
    idx = close_prices.index.get_loc(date)
    if idx < slow + signal_period + 10:
        return safe_assets[0]
    
    # 对每个风险资产计算MACD
    best_risk = None
    best_risk_macd = -999
    
    for sym in risk_assets:
        if sym in close_prices.columns:
            closes = close_prices[sym].iloc[:idx+1]
            if len(closes) < slow + signal_period + 5:
                continue
            macd_line, signal_line, histogram = calc_macd(closes, fast, slow, signal_period)
            if len(histogram) > 1 and pd.notna(histogram.iloc[-1]):
                # MACD金叉（柱>0）且柱状图在增大
                if histogram.iloc[-1] > 0 and histogram.iloc[-1] > best_risk_macd:
                    best_risk_macd = histogram.iloc[-1]
                    best_risk = sym
    
    if best_risk is not None:
        return best_risk
    
    return safe_assets[0]


def dual_market_adaptive_signal(data, date, close_prices, lookback_months=9, buffer_days=5,
                                 risk_assets=['QQQ', 'SPY', 'VEA'], safe_assets=['AGG', 'SHY']):
    """双市场自适应: 趋势期用动量，震荡期用均值回归"""
    lookback_days = lookback_months * 21
    
    if date not in close_prices.index:
        return safe_assets[0]
    
    idx = close_prices.index.get_loc(date)
    if idx < lookback_days + buffer_days + 50:
        return safe_assets[0]
    
    ref_date = close_prices.index[idx - buffer_days]
    past_date = close_prices.index[max(0, idx - lookback_days - buffer_days)]
    
    # 判断市场状态：ADX简化版（用波动率+趋势强度）
    # 用20日波动率和60日趋势
    spy_closes = close_prices.get('SPY', close_prices.get('QQQ'))
    if spy_closes is None:
        return safe_assets[0]
    
    recent = spy_closes.iloc[max(0, idx-60):idx+1]
    if len(recent) < 30:
        return safe_assets[0]
    
    # 趋势强度：20日均线斜率
    ma20 = recent.rolling(20).mean().dropna()
    if len(ma20) < 5:
        return safe_assets[0]
    
    slope = (ma20.iloc[-1] - ma20.iloc[0]) / ma20.iloc[0] * 100
    
    # 波动率：20日收益标准差
    vol = recent.pct_change().tail(20).std() * np.sqrt(252) * 100
    
    # 高波动+低趋势 = 震荡市
    is_range = vol > 25 and abs(slope) < 10
    
    if is_range:
        # 震荡市：均值回归，用RSI(2)
        for sym in risk_assets:
            if sym in close_prices.columns:
                closes = close_prices[sym].iloc[:idx+1]
                rsi2 = calc_rsi(closes, 2)
                if len(rsi2) > 0 and pd.notna(rsi2.iloc[-1]):
                    if rsi2.iloc[-1] < 10:
                        return sym
        return safe_assets[0]
    else:
        # 趋势市：动量策略
        best_risk = None
        best_return = -999
        
        for sym in risk_assets:
            if sym in close_prices.columns:
                try:
                    current = close_prices.loc[ref_date, sym]
                    past = close_prices.loc[past_date, sym]
                    if pd.notna(current) and pd.notna(past) and past > 0:
                        ret = current / past - 1
                        if ret > best_return:
                            best_return = ret
                            best_risk = sym
                except:
                    continue
        
        if best_risk is not None and best_return > 0:
            return best_risk
        
        return safe_assets[0]


def blakever_v65_signal(data, date, close_prices, lookback_months=6,
                        risk_assets=['SPY', 'QQQ'], safe_assets=['AGG', 'SHY']):
    """Blakever V6.5: 利率维度修正 — EMA趋势 + 利率状态"""
    if date not in close_prices.index:
        return safe_assets[0]
    
    idx = close_prices.index.get_loc(date)
    if idx < 200:
        return safe_assets[0]
    
    # EMA趋势判断
    spy_closes = close_prices.get('SPY')
    if spy_closes is None:
        return safe_assets[0]
    
    current_price = spy_closes.iloc[idx]
    ema200 = calc_ema(spy_closes.iloc[:idx+1], 200)
    
    if len(ema200) == 0 or pd.isna(ema200.iloc[-1]):
        return safe_assets[0]
    
    is_bullish = current_price > ema200.iloc[-1]
    
    # 利率状态简化：用国债ETF 20日收益
    agg_closes = close_prices.get('AGG')
    if agg_closes is not None and idx >= 20:
        agg_ret_20d = agg_closes.iloc[idx] / agg_closes.iloc[idx-20] - 1
        rate_falling = agg_ret_20d > 0  # 国债涨→利率下行
    else:
        rate_falling = True
    
    if is_bullish:
        if rate_falling:
            # 牛市+利率下行 → 激进
            # 选最强风险资产
            best = None
            best_ret = -999
            lookback = lookback_months * 21
            if idx > lookback:
                for sym in risk_assets:
                    if sym in close_prices.columns:
                        ret = close_prices[sym].iloc[idx] / close_prices[sym].iloc[idx-lookback] - 1
                        if ret > best_ret:
                            best_ret = ret
                            best = sym
            return best if best is not None else risk_assets[0]
        else:
            # 牛市+利率上行 → 偏保守
            return risk_assets[0]
    else:
        # 熊市 → 避险
        if rate_falling:
            return safe_assets[0]  # 国债
        else:
            return safe_assets[-1] if len(safe_assets) > 1 else safe_assets[0]


# ============ 主程序 ============

def main():
    print("=" * 70)
    print("A股排行榜策略回测 — 验证美股排行榜策略在A股的有效性")
    print(f"回测期间: {START_DATE} ~ {END_DATE}")
    print(f"标的映射: SPY→沪深300, QQQ→创业板, VEA→中证500, AGG→国债, SHY→银华日利")
    print("=" * 70)
    
    # 加载数据
    print("\n📂 加载A股ETF数据...")
    data = load_all_etfs()
    
    if len(data) < 3:
        print("❌ 数据不足，无法回测")
        return
    
    results = []
    
    # ---------- 策略1: RSI(2)严格均值回归(创业板ETF) ----------
    print("\n🔄 策略1: RSI(2)严格均值回归(创业板ETF)")
    rsi2_result = backtest_etf_rotation(
        data, 
        lambda d, dt, cp: rsi2_mean_reversion_signal(d, dt, cp, rsi_buy=10, rsi_sell=80, target='QQQ'),
        "RSI(2)严格均值回归(创业板ETF)",
    )
    if rsi2_result:
        results.append(rsi2_result)
    
    # ---------- 策略2: RSI(2)严格均值回归(沪深300ETF) ----------
    print("🔄 策略2: RSI(2)严格均值回归(沪深300ETF)")
    rsi2_spy_result = backtest_etf_rotation(
        data,
        lambda d, dt, cp: rsi2_mean_reversion_signal(d, dt, cp, rsi_buy=10, rsi_sell=80, target='SPY'),
        "RSI(2)严格均值回归(沪深300ETF)",
    )
    if rsi2_spy_result:
        results.append(rsi2_spy_result)
    
    # ---------- 策略3: 双市场自适应v4.5 ----------
    print("🔄 策略3: 双市场自适应v4.5(A股)")
    dual_result = backtest_etf_rotation(
        data,
        lambda d, dt, cp: dual_market_adaptive_signal(d, dt, cp, lookback_months=9, buffer_days=5),
        "双市场自适应v4.5(A股)",
    )
    if dual_result:
        results.append(dual_result)
    
    # ---------- 策略4: GEM4资产_9M+5d缓冲 ----------
    print("🔄 策略4: GEM4资产_9M+5d缓冲(A股)")
    gem_9m5d = backtest_etf_rotation(
        data,
        lambda d, dt, cp: gem_signal(d, dt, cp, lookback_months=9, buffer_days=5,
                                      risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']),
        "GEM4资产_9M+5d缓冲(A股)",
    )
    if gem_9m5d:
        results.append(gem_9m5d)
    
    # ---------- 策略5: GEM4资产_9M+3d缓冲 ----------
    print("🔄 策略5: GEM4资产_9M+3d缓冲(A股)")
    gem_9m3d = backtest_etf_rotation(
        data,
        lambda d, dt, cp: gem_signal(d, dt, cp, lookback_months=9, buffer_days=3,
                                      risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']),
        "GEM4资产_9M+3d缓冲(A股)",
    )
    if gem_9m3d:
        results.append(gem_9m3d)
    
    # ---------- 策略6: GEM4资产_12M+7d缓冲 ----------
    print("🔄 策略6: GEM4资产_12M+7d缓冲(A股)")
    gem_12m7d = backtest_etf_rotation(
        data,
        lambda d, dt, cp: gem_signal(d, dt, cp, lookback_months=12, buffer_days=7,
                                      risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']),
        "GEM4资产_12M+7d缓冲(A股)",
    )
    if gem_12m7d:
        results.append(gem_12m7d)
    
    # ---------- 策略7: 双重动量_9M_阈值0%+3d缓冲 ----------
    print("🔄 策略7: 双重动量_9M_阈值0%+3d缓冲(A股)")
    dm_9m0 = backtest_etf_rotation(
        data,
        lambda d, dt, cp: dual_momentum_signal(d, dt, cp, lookback_months=9, buffer_days=3,
                                                abs_threshold=0, risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']),
        "双重动量_9M_阈值0%+3d缓冲(A股)",
    )
    if dm_9m0:
        results.append(dm_9m0)
    
    # ---------- 策略8: 双市场自适应_9M+5d缓冲 ----------
    print("🔄 策略8: 双市场自适应_9M+5d缓冲(A股)")
    dual_9m5d = backtest_etf_rotation(
        data,
        lambda d, dt, cp: dual_market_adaptive_signal(d, dt, cp, lookback_months=9, buffer_days=5,
                                                       risk_assets=['QQQ', 'SPY', 'VEA'], safe_assets=['AGG', 'SHY']),
        "双市场自适应_9M+5d缓冲(A股)",
    )
    if dual_9m5d:
        results.append(dual_9m5d)
    
    # ---------- 策略9: Blakever V6.5 ----------
    print("🔄 策略9: Blakever V6.5(A股)")
    blakever_result = backtest_etf_rotation(
        data,
        lambda d, dt, cp: blakever_v65_signal(d, dt, cp, lookback_months=6,
                                               risk_assets=['SPY', 'QQQ'], safe_assets=['AGG', 'SHY']),
        "Blakever V6.5(A股)",
    )
    if blakever_result:
        results.append(blakever_result)
    
    # ---------- 策略10: MACD8/21趋势 ----------
    print("🔄 策略10: MACD8/21趋势(A股)")
    macd_result = backtest_etf_rotation(
        data,
        lambda d, dt, cp: macd_trend_signal(d, dt, cp, fast=8, slow=21, signal_period=9,
                                             risk_assets=['SPY', 'VEA'], safe_assets=['AGG', 'SHY']),
        "MACD8/21趋势(A股)",
    )
    if macd_result:
        results.append(macd_result)
    
    # ---------- 基准: 沪深300ETF买入持有 ----------
    print("🔄 基准: 沪深300ETF买入持有")
    benchmark_result = backtest_etf_rotation(
        data,
        lambda d, dt, cp: 'SPY',
        "沪深300ETF买入持有(基准)",
    )
    if benchmark_result:
        results.append(benchmark_result)
    
    # ---------- 基准: 创业板ETF买入持有 ----------
    print("🔄 基准: 创业板ETF买入持有")
    qqq_benchmark = backtest_etf_rotation(
        data,
        lambda d, dt, cp: 'QQQ',
        "创业板ETF买入持有(基准)",
    )
    if qqq_benchmark:
        results.append(qqq_benchmark)
    
    # ============ 输出结果 ============
    print("\n" + "=" * 100)
    print("📊 A股排行榜策略回测结果")
    print("=" * 100)
    
    # 按年化收益排序
    results.sort(key=lambda x: x['annual_return'], reverse=True)
    
    # 表头
    header = f"{'排名':>3} {'策略名称':<30} {'年化%':>7} {'总收益%':>8} {'回撤%':>7} {'夏普':>6} {'卡玛':>6} {'胜率%':>6} {'盈亏比':>6} {'年交易':>5} {'持仓分布':<30}"
    print(header)
    print("-" * len(header))
    
    for i, r in enumerate(results):
        hd = r.get('holding_distribution', {})
        hd_str = '/'.join([f"{k}:{v}%" for k, v in sorted(hd.items(), key=lambda x: -x[1])[:4]])
        print(f"{i+1:>3} {r['strategy_name']:<30} {r['annual_return']:>7.2f} {r['total_return']:>8.2f} "
              f"{r['max_drawdown']:>7.2f} {r['sharpe']:>6.2f} {r['calmar']:>6.2f} "
              f"{r['win_rate']:>6.1f} {r['profit_factor']:>6.2f} {r['avg_trades_per_year']:>5.1f} {hd_str:<30}")
    
    # 对比美股排行榜结果
    print("\n" + "=" * 100)
    print("📈 A股 vs 美股策略表现对比")
    print("=" * 100)
    
    us_results = {
        "双市场自适应v4.5": {"annual": 22.09, "dd": 19.38, "sharpe": 0.99},
        "RSI(2)均值回归(QQQ)": {"annual": 14.11, "dd": 15.15, "sharpe": 0.57},
        "GEM4资产_9M+5d缓冲": {"annual": 10.60, "dd": 24.28, "sharpe": 0.47},
        "GEM4资产_9M+3d缓冲": {"annual": 10.60, "dd": 24.28, "sharpe": 0.47},
        "GEM4资产_12M+7d缓冲": {"annual": 10.60, "dd": 24.28, "sharpe": 0.47},
        "双重动量_9M_阈值0%+3d缓冲": {"annual": 10.60, "dd": 24.28, "sharpe": 0.47},
        "Blakever V6.5": {"annual": 10.60, "dd": 24.28, "sharpe": 0.47},
    }
    
    comparison = []
    for r in results:
        if '基准' in r['strategy_name']:
            continue
        # 找美股对应
        a_name = r['strategy_name'].replace('(A股)', '')
        matched_us = None
        for us_key, us_val in us_results.items():
            if us_key in a_name or a_name in us_key:
                matched_us = us_val
                break
        
        if matched_us:
            comparison.append({
                'name': r['strategy_name'],
                'a_annual': r['annual_return'],
                'us_annual': matched_us['annual'],
                'a_dd': r['max_drawdown'],
                'us_dd': matched_us['dd'],
                'a_sharpe': r['sharpe'],
                'us_sharpe': matched_us['sharpe'],
            })
    
    if comparison:
        print(f"{'策略':<30} {'A股年化%':>9} {'美股年化%':>9} {'差值':>7} {'A股回撤%':>9} {'美股回撤%':>9} {'A股夏普':>8} {'美股夏普':>8}")
        print("-" * 110)
        for c in comparison:
            diff = c['a_annual'] - c['us_annual']
            diff_str = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"
            print(f"{c['name']:<30} {c['a_annual']:>9.2f} {c['us_annual']:>9.2f} {diff_str:>7} "
                  f"{c['a_dd']:>9.2f} {c['us_dd']:>9.2f} {c['a_sharpe']:>8.2f} {c['us_sharpe']:>8.2f}")
    
    print("\n" + "=" * 100)
    print("💡 关键发现")
    print("=" * 100)
    
    # 找出跑赢基准的策略
    benchmark_annual = None
    for r in results:
        if '沪深300买入持有' in r['strategy_name']:
            benchmark_annual = r['annual_return']
            break
    
    if benchmark_annual is not None:
        beat_benchmark = [r for r in results if '基准' not in r['strategy_name'] and r['annual_return'] > benchmark_annual]
        lose_benchmark = [r for r in results if '基准' not in r['strategy_name'] and r['annual_return'] <= benchmark_annual]
        
        print(f"\n沪深300买入持有年化: {benchmark_annual:.2f}%")
        print(f"跑赢基准的策略: {len(beat_benchmark)} 个")
        for r in beat_benchmark:
            print(f"  ✓ {r['strategy_name']}: 年化{r['annual_return']:.2f}%, 回撤{r['max_drawdown']:.2f}%")
        
        print(f"跑输基准的策略: {len(lose_benchmark)} 个")
        for r in lose_benchmark:
            print(f"  ✗ {r['strategy_name']}: 年化{r['annual_return']:.2f}%, 回撤{r['max_drawdown']:.2f}%")
    
    return results


if __name__ == '__main__':
    main()
