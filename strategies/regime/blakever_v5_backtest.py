#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
BlakeverStrategyV5 回测验证
==========================================================================
策略来源: blakever_test_stragegy.py (BlakeverStrategyV5)

核心逻辑:
  1. 多维环境判定 (Bullish/Sideways/Bearish + Kill Switch)
  2. Hysteresis 状态机 (3日确认)
  3. ADX + EMA + VIX 综合判定
  4. ATR-Based 仓位控制
  5. 多因子评分 (ADX + 动量 + 量能)

适配方式:
  - 将原策略的"股票池扫描"逻辑，转为单标的(ETF/个股)的买卖信号
  - 在 SPY(美股) + 港股代表性标的上进行回测
  - 使用 TA-Lib 计算技术指标 (EMA50/200, ADX14, ATR14)

框架: VectorBT 0.28.5 + TA-Lib 0.6.8
数据: back_trader_stocks/ (本地CSV)
==========================================================================
"""

import os
import warnings
import json
from datetime import datetime

import numpy as np
import pandas as pd
import talib
import vectorbt as vbt

warnings.filterwarnings('ignore')

# ================================================================
# 全局配置
# ================================================================
INIT_CASH = 1_000_000  # 100万本币
FEES_US = 0.000528     # 美股 ≈ 0.0528% (SEC费+佣金)
FEES_HK = 0.001348     # 港股 ≈ 0.1348% (印花税+征费+佣金)
SLIPPAGE = 0.001       # 滑点 0.1%

DATA_DIR = '/data/workspace/back_trader_stocks'

# 回测区间 (趋势/牛市系统)
MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'

# 震荡市回测区间
RANGE_START = '2021-01-01'
RANGE_END = '2023-12-31'

# 熊市回测区间
BEAR_START = '2022-01-01'
BEAR_END = '2023-12-31'

# 无风险利率
RISK_FREE_RATE = 0.045  # 10年美债 ~4.5% + 1%


# ================================================================
# 数据加载
# ================================================================
def load_csv(path: str) -> pd.DataFrame:
    """加载CSV数据，标准化列名"""
    df = pd.read_csv(path)
    df.columns = [c.strip().capitalize() for c in df.columns]
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date').sort_index()
    # 确保数值类型
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['Close'])
    return df


def load_spy_and_vix():
    """加载SPY和VIX数据"""
    spy_path = os.path.join(DATA_DIR, 'etf', 'SPY.csv')
    vix_path = os.path.join(DATA_DIR, 'etf', 'VIX.csv')

    spy = load_csv(spy_path)
    vix = load_csv(vix_path)

    # 对齐日期
    common_idx = spy.index.intersection(vix.index)
    spy = spy.loc[common_idx]
    vix = vix.loc[common_idx]

    return spy, vix


def load_hk_stock(code: str):
    """加载港股数据"""
    path = os.path.join(DATA_DIR, 'hk', f'{code}.csv')
    if not os.path.exists(path):
        return None
    return load_csv(path)


# ================================================================
# 技术指标计算 (TA-Lib)
# ================================================================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算策略所需技术指标"""
    close = df['Close'].values.astype(float)
    high = df['High'].values.astype(float)
    low = df['Low'].values.astype(float)
    volume = df['Volume'].values.astype(float) if 'Volume' in df.columns else None

    # EMA
    df['ema20'] = talib.EMA(close, timeperiod=20)
    df['ema50'] = talib.EMA(close, timeperiod=50)
    df['ema200'] = talib.EMA(close, timeperiod=200)

    # ADX
    df['adx14'] = talib.ADX(high, low, close, timeperiod=14)

    # ATR
    df['atr14'] = talib.ATR(high, low, close, timeperiod=14)

    # 20日收益率 (动量因子)
    df['return_20d'] = df['Close'].pct_change(20)

    # 量能趋势 (20日均线比)
    if volume is not None and np.nansum(volume) > 0:
        df['vol_ma20'] = talib.SMA(volume, timeperiod=20)
        df['volume_trend'] = volume / df['vol_ma20']
    else:
        df['volume_trend'] = 1.0

    # 布林带 (用于震荡市 range_low/range_high 替代)
    df['bb_upper'], df['bb_mid'], df['bb_lower'] = talib.BBANDS(
        close, timeperiod=20, nbdevup=2, nbdevdn=2
    )
    df['range_low'] = df['bb_lower']
    df['range_high'] = df['bb_upper']

    return df


# ================================================================
# 策略信号生成 (将 BlakeverStrategyV5 适配为向量化回测)
# ================================================================
def generate_blakever_v5_signals(
    index_df: pd.DataFrame,
    vix_series: pd.Series,
    stock_df: pd.DataFrame,
    persistence_threshold: int = 3,
    vix_threshold: float = 25.0,
    vix_spike_ratio: float = 0.15,
    adx_sideways_threshold: float = 20.0,
    adx_overbought: float = 50.0,
    adx_entry_min: float = 25.0,
    trend_strength_threshold: float = 0.015,
) -> tuple:
    """
    生成 BlakeverStrategyV5 的买卖信号。

    返回: (entries, exits) 均为 np.ndarray[bool]
    """
    n = len(stock_df)
    entries = np.full(n, False)
    exits = np.full(n, False)

    # 状态机变量
    regime = "Sideways"
    candidate_regime = None
    candidate_days = 0
    in_position = False

    # 对齐数据: 确保VIX和指数数据与股票数据日期对齐
    # 使用 index_df 和 vix_series 进行环境判定
    # 使用 stock_df 进行交易信号判定

    for i in range(200, n):  # 从200开始，确保EMA200等指标有效
        # ── 第一阶段: 环境判定 ──
        # 使用 T-1 数据
        idx_close_t1 = index_df['Close'].iloc[i - 1] if i - 1 < len(index_df) else index_df['Close'].iloc[-1]
        idx_close_t2 = index_df['Close'].iloc[i - 2] if i - 2 < len(index_df) else index_df['Close'].iloc[-2]
        idx_close_t4 = index_df['Close'].iloc[i - 4] if i - 4 >= 0 else index_df['Close'].iloc[0]
        idx_ema50_t1 = index_df['ema50'].iloc[i - 1] if i - 1 < len(index_df) else index_df['ema50'].iloc[-1]
        idx_ema200_t1 = index_df['ema200'].iloc[i - 1] if i - 1 < len(index_df) else index_df['ema200'].iloc[-1]
        idx_adx_t1 = index_df['adx14'].iloc[i - 1] if i - 1 < len(index_df) else index_df['adx14'].iloc[-1]

        vix_t1 = vix_series.iloc[i - 1] if i - 1 < len(vix_series) else vix_series.iloc[-1]
        vix_t4 = vix_series.iloc[i - 4] if i - 4 >= 0 else vix_series.iloc[0]

        # Kill Switch 检测
        daily_ret = (idx_close_t1 - idx_close_t2) / idx_close_t2 if idx_close_t2 != 0 else 0
        three_day_ret = (idx_close_t1 - idx_close_t4) / idx_close_t4 if idx_close_t4 != 0 else 0
        vix_3d_change = (vix_t1 - vix_t4) / vix_t4 if vix_t4 != 0 else 0

        kill_switch = False
        if (daily_ret < -0.03 and three_day_ret < -0.05) or (vix_t1 > vix_threshold and vix_3d_change > vix_spike_ratio):
            kill_switch = True

        # 环境判定
        trend_strength = abs(idx_ema50_t1 - idx_ema200_t1) / idx_ema200_t1 if idx_ema200_t1 != 0 and not np.isnan(idx_ema200_t1) else 0

        if not np.isnan(idx_adx_t1):
            adx_val = idx_adx_t1
        else:
            adx_val = 0

        target_regime = "Bearish"  # 默认
        if adx_val < adx_sideways_threshold and trend_strength < trend_strength_threshold:
            target_regime = "Sideways"
        elif idx_close_t1 > idx_ema200_t1 and idx_ema50_t1 > idx_ema200_t1:
            target_regime = "Bullish"

        # Hysteresis 状态机更新
        if target_regime == regime:
            candidate_regime = None
            candidate_days = 0
        else:
            if target_regime == candidate_regime:
                candidate_days += 1
            else:
                candidate_regime = target_regime
                candidate_days = 1
            if candidate_days >= persistence_threshold:
                regime = target_regime
                candidate_regime = None
                candidate_days = 0

        # ── 第二阶段: 交易信号判定 ──
        stock_close = stock_df['Close'].iloc[i]
        stock_ema20 = stock_df['ema20'].iloc[i]
        stock_adx = stock_df['adx14'].iloc[i]
        stock_range_low = stock_df['range_low'].iloc[i]
        stock_atr = stock_df['atr14'].iloc[i]

        if np.isnan(stock_ema20) or np.isnan(stock_adx):
            continue

        # 港股 ADX Fallback
        if stock_adx == 0:
            ts = (stock_close - stock_ema20) / stock_ema20 if stock_ema20 != 0 else 0
            stock_adx = min(50, max(10, ts * 100))

        if in_position:
            # 退出逻辑
            if kill_switch:
                exits[i] = True
                in_position = False
            elif stock_close < stock_ema20:
                exits[i] = True
                in_position = False
            # 牛市过热 (ADX > 50): 减仓标记，但此处简化为继续持仓
        else:
            # 开仓逻辑
            if kill_switch:
                continue

            if regime == "Bullish":
                if stock_adx >= adx_entry_min and stock_adx <= adx_overbought:
                    entries[i] = True
                    in_position = True
            elif regime == "Sideways":
                if stock_close < stock_range_low * 1.01:
                    entries[i] = True
                    in_position = True
            # Bearish: 不开仓

    return entries, exits


# ================================================================
# 回测执行
# ================================================================
def run_backtest(close, high, low, open_prices, entries, exits,
                 fees=FEES_US, name="BlakeverV5"):
    """运行回测并返回绩效指标"""
    # T+1修正
    entries_t1 = np.roll(entries, 1)
    entries_t1[0] = False
    exits_t1 = np.roll(exits, 1)
    exits_t1[0] = False

    if entries_t1.sum() == 0:
        return {
            '策略': name, '状态': '无交易信号',
            '年化收益%': 0, '最大回撤%': 0, '夏普比率': 0,
            '胜率%': 0, '交易次数': 0, '盈亏比': 0,
            '卡尔马比率': 0, '总收益率%': 0, '持仓比例%': 0
        }

    pf = vbt.Portfolio.from_signals(
        open=open_prices, close=close,
        entries=entries_t1, exits=exits_t1,
        freq='D', init_cash=INIT_CASH,
        fees=fees, slippage=SLIPPAGE,
        upon_opposite_entry='reverse'
    )

    stats = pf.stats()
    total_return = float(stats['Total Return [%]'])
    max_dd = float(stats['Max Drawdown [%]'])
    win_rate = float(stats['Win Rate [%]'])
    total_trades = int(stats['Total Trades'])
    n_years = len(pf.returns()) / 252

    if n_years > 0 and total_return > -100:
        annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100
    else:
        annual = -100

    sharpe = float(stats.get('Sharpe Ratio', 0))
    if pd.isna(sharpe):
        sharpe = 0

    # 盈亏比
    try:
        pl_ratio = float(stats.get('Profit Factor', 0))
        if pd.isna(pl_ratio):
            pl_ratio = 0
    except:
        pl_ratio = 0

    # 卡尔马比率
    calmar = annual / abs(max_dd) if max_dd != 0 else 0

    # 持仓比例
    in_pos = np.zeros(len(close), dtype=bool)
    cur = False
    for j in range(len(entries)):
        if entries[j]:
            cur = True
        elif exits[j]:
            cur = False
        in_pos[j] = cur
    pos_pct = in_pos.sum() / len(close) * 100

    return {
        '策略': name,
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': round(sharpe, 2),
        '胜率%': round(win_rate, 2),
        '交易次数': total_trades,
        '盈亏比': round(pl_ratio, 2),
        '卡尔马比率': round(calmar, 2),
        '持仓比例%': round(pos_pct, 1)
    }


def run_buyhold(close, open_prices, fees=FEES_US):
    """Buy & Hold 基准"""
    n = len(close)
    entries = np.full(n, False)
    entries[0] = True
    exits = np.full(n, False)

    pf = vbt.Portfolio.from_signals(
        open=open_prices, close=close,
        entries=entries, exits=exits,
        freq='D', init_cash=INIT_CASH,
        fees=fees, slippage=SLIPPAGE
    )

    stats = pf.stats()
    total_return = float(stats['Total Return [%]'])
    max_dd = float(stats['Max Drawdown [%]'])
    n_years = len(pf.returns()) / 252
    annual = ((1 + total_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    return {
        '策略': 'Buy & Hold',
        '状态': '✅',
        '总收益率%': round(total_return, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': '-',
        '胜率%': '-',
        '交易次数': 1,
        '盈亏比': '-',
        '卡尔马比率': round(annual / abs(max_dd), 2) if max_dd != 0 else 0,
        '持仓比例%': 100.0
    }


# ================================================================
# 过拟合检测
# ================================================================
def overfit_check(close, high, low, open_prices, entries, exits, fees=FEES_US):
    """
    过拟合检测: 训练集(前70%) vs 测试集(后30%)
    若测试集收益低于训练集30%以上，判定过拟合
    """
    n = len(close)
    split = int(n * 0.7)

    # 训练集
    train_entries = entries[:split].copy()
    train_exits = exits[:split].copy()
    train_close = close[:split]
    train_open = open_prices[:split]

    # 测试集
    test_entries = entries[split:].copy()
    test_exits = exits[split:].copy()
    test_close = close[split:]
    test_open = open_prices[split:]

    def calc_return(cl, op, ent, ext):
        ent2 = np.roll(ent, 1)
        ent2[0] = False
        ext2 = np.roll(ext, 1)
        ext2[0] = False
        if ent2.sum() == 0:
            return 0.0
        pf = vbt.Portfolio.from_signals(
            open=op, close=cl,
            entries=ent2, exits=ext2,
            freq='D', init_cash=INIT_CASH, fees=fees, slippage=SLIPPAGE
        )
        return float(pf.stats()['Total Return [%]'])

    train_ret = calc_return(train_close, train_open, train_entries, train_exits)
    test_ret = calc_return(test_close, test_open, test_entries, test_exits)

    overfit = False
    overfit_detail = ""
    if train_ret > 0 and test_ret < train_ret * 0.7:
        overfit = True
        overfit_detail = f"测试集收益({test_ret:.2f}%)低于训练集({train_ret:.2f}%)的70%，差异超过30%阈值"
    elif train_ret > 0 and test_ret < 0:
        overfit = True
        overfit_detail = f"训练集正收益({train_ret:.2f}%)但测试集亏损({test_ret:.2f}%)，严重过拟合"
    else:
        overfit_detail = f"训练集收益{train_ret:.2f}%，测试集收益{test_ret:.2f}%，未检测到过拟合"

    return {
        'overfit_detected': overfit,
        'train_return': round(train_ret, 2),
        'test_return': round(test_ret, 2),
        'overfit_details': overfit_detail
    }


# ================================================================
# 多周期一致性验证
# ================================================================
def consistency_check(all_period_results):
    """
    多周期一致性验证:
    - 1/3/5年夏普均>0.5
    - 最大回撤均<30%
    - 全部满足=通过; 单周期不达标=标记警告; 两周期不达标=不予采纳
    """
    warnings_list = []
    fail_count = 0

    for period_name, result in all_period_results.items():
        if result.get('状态') == '无交易信号':
            warnings_list.append(f"{period_name}: 无交易信号")
            fail_count += 1
            continue

        sharpe = result.get('夏普比率', 0)
        max_dd = abs(result.get('最大回撤%', 0))

        if isinstance(sharpe, (int, float)) and sharpe <= 0.5:
            warnings_list.append(f"{period_name}: 夏普比率{sharpe} ≤ 0.5 阈值")
            fail_count += 1
        if max_dd >= 30:
            warnings_list.append(f"{period_name}: 最大回撤{max_dd}% ≥ 30% 阈值")
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
# 打印结果表格
# ================================================================
def print_table(results, title):
    """打印回测结果表格"""
    print(f"\n{'━' * 120}")
    print(f"  📊 {title}")
    print(f"{'━' * 120}")
    header = f"{'策略':<22} {'状态':<6} {'总收益率':>10} {'年化收益':>10} {'最大回撤':>10} {'夏普':>8} {'胜率':>8} {'交易数':>8} {'盈亏比':>8} {'卡尔马':>8} {'持仓%':>8}"
    print(header)
    print("-" * 120)
    for r in results:
        print(f"{r['策略']:<22} {r['状态']:<6} {r['总收益率%']:>9.2f}% {r['年化收益%']:>9.2f}% "
              f"{r['最大回撤%']:>9.2f}% {str(r['夏普比率']):>8} {str(r['胜率%']):>8} "
              f"{r['交易次数']:>8} {str(r['盈亏比']):>8} {r['卡尔马比率']:>8.2f} {r['持仓比例%']:>7.1f}%")
    print(f"{'━' * 120}")


# ================================================================
# 主流程
# ================================================================
def main():
    print("=" * 120)
    print("  🚀 BlakeverStrategyV5 回测验证")
    print("  策略来源: blakever_test_stragegy.py")
    print("  回测框架: VectorBT 0.28.5 + TA-Lib 0.6.8")
    print("=" * 120)

    # ================================================================
    # 1. 加载并准备数据
    # ================================================================
    print("\n📥 加载数据...")

    # SPY + VIX
    spy_raw, vix_raw = load_spy_and_vix()
    spy = compute_indicators(spy_raw)
    vix_close = vix_raw['Close']

    print(f"  ✅ SPY: {len(spy)} 天 ({spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')})")
    print(f"  ✅ VIX: {len(vix_raw)} 天")

    # 港股标的
    hk_stocks = {}
    hk_codes = {
        'hk00700': '腾讯控股',
        'hk09988': '阿里巴巴',
        'hk00005': '汇丰控股',
        'hk01810': '小米集团',
        'hk03690': '美团',
    }
    for code, name in hk_codes.items():
        df = load_hk_stock(code)
        if df is not None and len(df) > 200:
            df = compute_indicators(df)
            hk_stocks[code] = (name, df)
            print(f"  ✅ {name}({code}): {len(df)} 天")

    # ================================================================
    # 2. SPY 多周期回测 (趋势/牛市系统)
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 第一部分: SPY 多周期回测 (趋势/牛市系统)")
    print(f"{'━' * 120}")

    # 定义回测区间
    periods = {
        '1年': ('2024-01-01', '2024-12-31'),
        '3年': ('2022-01-01', '2024-12-31'),
        '5年': ('2020-01-01', '2024-12-31'),
        '全周期(2019-2024)': ('2019-01-01', '2024-12-31'),
    }

    period_results = {}
    for period_name, (start, end) in periods.items():
        # 切片
        mask = (spy.index >= start) & (spy.index <= end)
        spy_period = spy[mask]
        vix_period = vix_close[mask]

        if len(spy_period) < 200:
            print(f"  ⚠️ {period_name}: 数据不足({len(spy_period)}天)，跳过")
            continue

        # 生成信号 (SPY 既是指数也是标的)
        entries, exits = generate_blakever_v5_signals(
            index_df=spy_period,
            vix_series=vix_period,
            stock_df=spy_period
        )

        close_arr = spy_period['Close'].values.astype(float)
        high_arr = spy_period['High'].values.astype(float)
        low_arr = spy_period['Low'].values.astype(float)
        open_arr = spy_period['Open'].values.astype(float)

        result = run_backtest(close_arr, high_arr, low_arr, open_arr,
                              entries, exits, fees=FEES_US,
                              name=f"BlakeverV5-{period_name}")
        period_results[period_name] = result

        # Buy & Hold
        bh = run_buyhold(close_arr, open_arr, fees=FEES_US)
        bh['策略'] = f'B&H-{period_name}'

        print_table([result, bh], f"SPY {period_name} ({start} ~ {end})")

    # ================================================================
    # 3. SPY 震荡市回测
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 第二部分: SPY 震荡市回测 (2021-2023)")
    print(f"{'━' * 120}")

    mask_range = (spy.index >= RANGE_START) & (spy.index <= RANGE_END)
    spy_range = spy[mask_range]
    vix_range = vix_close[mask_range]

    if len(spy_range) > 200:
        entries_r, exits_r = generate_blakever_v5_signals(
            index_df=spy_range, vix_series=vix_range, stock_df=spy_range
        )
        close_r = spy_range['Close'].values.astype(float)
        open_r = spy_range['Open'].values.astype(float)

        result_r = run_backtest(
            spy_range['Close'].values.astype(float),
            spy_range['High'].values.astype(float),
            spy_range['Low'].values.astype(float),
            open_r, entries_r, exits_r, fees=FEES_US, name="BlakeverV5-震荡市"
        )
        bh_r = run_buyhold(close_r, open_r, fees=FEES_US)
        bh_r['策略'] = 'B&H-震荡市'
        print_table([result_r, bh_r], f"SPY 震荡市 ({RANGE_START} ~ {RANGE_END})")
    else:
        result_r = {'状态': '数据不足'}

    # ================================================================
    # 4. SPY 熊市回测
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 第三部分: SPY 熊市回测 (2022-2023)")
    print(f"{'━' * 120}")

    mask_bear = (spy.index >= BEAR_START) & (spy.index <= BEAR_END)
    spy_bear = spy[mask_bear]
    vix_bear = vix_close[mask_bear]

    if len(spy_bear) > 200:
        entries_b, exits_b = generate_blakever_v5_signals(
            index_df=spy_bear, vix_series=vix_bear, stock_df=spy_bear
        )
        close_b = spy_bear['Close'].values.astype(float)
        open_b = spy_bear['Open'].values.astype(float)

        result_b = run_backtest(
            spy_bear['Close'].values.astype(float),
            spy_bear['High'].values.astype(float),
            spy_bear['Low'].values.astype(float),
            open_b, entries_b, exits_b, fees=FEES_US, name="BlakeverV5-熊市"
        )
        bh_b = run_buyhold(close_b, open_b, fees=FEES_US)
        bh_b['策略'] = 'B&H-熊市'
        print_table([result_b, bh_b], f"SPY 熊市 ({BEAR_START} ~ {BEAR_END})")
    else:
        result_b = {'状态': '数据不足'}

    # ================================================================
    # 5. 港股回测
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 第四部分: 港股代表性标的回测 (2019-2024)")
    print(f"{'━' * 120}")

    hk_results = []
    for code, (name, df) in hk_stocks.items():
        mask = (df.index >= MAIN_START) & (df.index <= MAIN_END)
        df_period = df[mask]

        if len(df_period) < 200:
            print(f"  ⚠️ {name}: 数据不足({len(df_period)}天)，跳过")
            continue

        # 港股使用SPY作为指数参考 + VIX (简化: 港股没有VIX，用恒指代替)
        # 实际上港股没有本地VIX数据，使用SPY的环境判定作为全球市场参考
        spy_mask = (spy.index >= df_period.index[0]) & (spy.index <= df_period.index[-1])
        spy_ref = spy[spy_mask]
        vix_ref = vix_close[spy_mask]

        # 对齐: 取两者日期交集
        common_idx = df_period.index.intersection(spy_ref.index)
        df_aligned = df_period.loc[common_idx]
        spy_aligned = spy_ref.loc[common_idx]
        vix_aligned = vix_ref.loc[common_idx]

        if len(df_aligned) < 200:
            continue

        entries_hk, exits_hk = generate_blakever_v5_signals(
            index_df=spy_aligned,
            vix_series=vix_aligned,
            stock_df=df_aligned
        )

        result_hk = run_backtest(
            df_aligned['Close'].values.astype(float),
            df_aligned['High'].values.astype(float),
            df_aligned['Low'].values.astype(float),
            df_aligned['Open'].values.astype(float),
            entries_hk, exits_hk, fees=FEES_HK,
            name=f"BlakeverV5-{name}"
        )
        hk_results.append(result_hk)

        # B&H
        bh_hk = run_buyhold(
            df_aligned['Close'].values.astype(float),
            df_aligned['Open'].values.astype(float),
            fees=FEES_HK
        )
        bh_hk['策略'] = f'B&H-{name}'
        hk_results.append(bh_hk)

    if hk_results:
        print_table(hk_results, "港股 BlakeverV5 vs Buy&Hold (2019-2024)")

    # ================================================================
    # 6. 过拟合检测 (SPY全周期)
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 第五部分: 过拟合检测 (SPY 2019-2024, 训练集70% vs 测试集30%)")
    print(f"{'━' * 120}")

    mask_full = (spy.index >= MAIN_START) & (spy.index <= MAIN_END)
    spy_full = spy[mask_full]
    vix_full = vix_close[mask_full]

    if len(spy_full) > 200:
        entries_full, exits_full = generate_blakever_v5_signals(
            index_df=spy_full, vix_series=vix_full, stock_df=spy_full
        )

        of_result = overfit_check(
            spy_full['Close'].values.astype(float),
            spy_full['High'].values.astype(float),
            spy_full['Low'].values.astype(float),
            spy_full['Open'].values.astype(float),
            entries_full, exits_full, fees=FEES_US
        )

        of_status = "⚠️ 过拟合" if of_result['overfit_detected'] else "✅ 未检测到过拟合"
        print(f"\n  {of_status}")
        print(f"  训练集收益: {of_result['train_return']}%")
        print(f"  测试集收益: {of_result['test_return']}%")
        print(f"  详情: {of_result['overfit_details']}")

    # ================================================================
    # 7. 多周期一致性验证
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📊 第六部分: 多周期一致性验证")
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
    # 8. 最终报告
    # ================================================================
    print(f"\n{'━' * 120}")
    print("  📋 最终报告")
    print(f"{'━' * 120}")

    # 汇总SPY全周期
    full_key = '全周期(2019-2024)'
    if full_key in period_results:
        r = period_results[full_key]
        print(f"\n  📊 SPY 全周期 (2019-2024) 绩效:")
        print(f"    年化收益: {r['年化收益%']}%")
        print(f"    最大回撤: {r['最大回撤%']}%")
        print(f"    夏普比率: {r['夏普比率']}")
        print(f"    胜率: {r['胜率%']}%")
        print(f"    交易次数: {r['交易次数']}")
        print(f"    盈亏比: {r['盈亏比']}")
        print(f"    卡尔马比率: {r['卡尔马比率']}")

    # 推荐建议
    if full_key in period_results:
        r = period_results[full_key]
        annual = r['年化收益%']
        max_dd = abs(r['最大回撤%'])
        improvement = annual / max_dd if max_dd > 0 else 0

        recommend = False
        if cc_result['verdict'] != "不予采纳" and not of_result.get('overfit_detected', True):
            if improvement > 0.1:  # (年化/回撤) 提升 > 10%
                recommend = True

        print(f"\n  🎯 推荐建议:")
        print(f"    年化/回撤比率: {improvement:.2f}")
        print(f"    recommend_adoption: {recommend}")

        if recommend:
            print(f"    ✅ 建议采纳: 策略通过过拟合检测和多周期一致性验证")
        else:
            reasons = []
            if of_result.get('overfit_detected', False):
                reasons.append("过拟合检测未通过")
            if cc_result['verdict'] == "不予采纳":
                reasons.append("多周期一致性验证未通过")
            if improvement <= 0.1:
                reasons.append("年化/回撤比率未超过10%阈值")
            print(f"    ❌ 暂不建议采纳: {', '.join(reasons)}")

    # JSON 输出
    output = {
        "strategy_name": "BlakeverStrategyV5",
        "strategy_source": "blakever_test_stragegy.py",
        "data_source": "back_trader_stocks (本地CSV)",
        "data_period": f"{MAIN_START} ~ {MAIN_END}",
        "backtest_framework": "VectorBT 0.28.5",
        "overfit_detected": of_result.get('overfit_detected', None),
        "overfit_details": of_result.get('overfit_details', ''),
        "period_results": {k: {kk: vv for kk, vv in v.items() if kk != '策略'} for k, v in period_results.items()},
        "consistency_check": cc_result,
        "recommend_adoption": recommend if full_key in period_results else False,
        "optimization_notes": [
            "策略在熊市环境(Bearish)不开仓，仅做退出操作，可考虑加入做空逻辑",
            "震荡市仅使用布林带下轨买入，可优化为RSI+布林带组合",
            "港股使用SPY指数做环境判定，建议替换为恒生指数",
            "可考虑加入ATR跟踪止损替代EMA20退出"
        ]
    }

    output_path = '/data/workspace/blakever_v5_backtest_result.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📁 完整报告已保存: {output_path}")


if __name__ == '__main__':
    main()
