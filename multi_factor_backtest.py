#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机构级多因子量化策略 - Alpha因子增强策略 v3 (优化版)
本地美股CSV数据回测

核心改进：
1. 因子体系适配美股（无基本面数据时的替代方案）
2. 动量因子为核心，质量和波动为约束
3. 严格的现金管理和仓位管理
4. 合理的风控参数
"""

import os, warnings, json
from functools import reduce
import numpy as np
import pandas as pd
import talib
warnings.filterwarnings('ignore')

# ================================================================
# 配置
# ================================================================
INIT_CASH = 1_000_000
DATA_DIR = '/data/workspace/back_trader_stocks/us'
ETF_DIR = '/data/workspace/back_trader_stocks/etf'

BACKTEST_START = '2022-01-01'
BACKTEST_END = '2026-04-17'
WARMUP_START = '2021-01-01'  # 因子预热起始

FEES_RATE = 0.001
RISK_FREE_RATE = 0.045

MAX_STOCK_NUM = 30      # 适中持仓数
MAX_SINGLE_WEIGHT = 0.06
STOP_LOSS_RATIO = 0.10  # 10%固定止损
TRAILING_STOP_ACTIVATION = 0.12  # 盈利12%后启用
TRAILING_STOP_RATIO = 0.07       # 移动止损7%
PORTFOLIO_DRAWDOWN_LIMIT = 0.15  # 组合最大回撤15%
MIN_PRICE = 5.0
MIN_HISTORY_DAYS = 200

FACTOR_WEIGHTS = {
    'momentum': 0.35,   # 核心：多周期动量
    'trend':    0.25,   # 趋势强度（均线排列/ADX/RSI）
    'quality':  0.20,   # 质量（低波/正偏/小回撤）
    'volatility': 0.15, # 低波动优先
    'liquidity': 0.05,  # 流动性约束
}


# ================================================================
# 数据
# ================================================================
def load_stock_csv(path):
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


def load_all_stocks(min_days=600):
    data = {}
    for f in os.listdir(DATA_DIR):
        if not f.endswith('.csv'): continue
        try:
            df = load_stock_csv(os.path.join(DATA_DIR, f))
            mask = (df.index >= WARMUP_START) & (df.index <= BACKTEST_END)
            df = df[mask]
            if len(df) >= min_days:
                data[f.replace('.csv', '')] = df
        except: pass
    return data


def load_etf(sym):
    path = os.path.join(ETF_DIR, f'{sym}.csv')
    return load_stock_csv(path) if os.path.exists(path) else pd.DataFrame()


def compute_indicators(df):
    c = df['Close'].values.astype(float)
    h = df['High'].values.astype(float) if 'High' in df.columns else c
    l = df['Low'].values.astype(float) if 'Low' in df.columns else c
    v = df['Volume'].values.astype(float) if 'Volume' in df.columns else None

    df['sma20'] = talib.SMA(c, 20)
    df['sma50'] = talib.SMA(c, 50)
    df['sma200'] = talib.SMA(c, 200)
    df['atr14'] = talib.ATR(h, l, c, 14)
    df['adx14'] = talib.ADX(h, l, c, 14)
    df['rsi14'] = talib.RSI(c, 14)

    if v is not None and np.nansum(v) > 0:
        df['vol_ma20'] = talib.SMA(v, 20)

    for p in [1, 5, 20, 60, 120, 240]:
        df[f'ret_{p}d'] = df['Close'].pct_change(p)

    return df


# ================================================================
# 因子计算
# ================================================================
def calc_momentum_factors(stock_data, date):
    """动量因子 - 核心alpha"""
    results = []
    for sym, df in stock_data.items():
        if date not in df.index: continue
        loc = df.index.get_loc(date)
        if loc < 240: continue
        close = df['Close'].iloc[loc]
        if close < MIN_PRICE: continue

        r240 = df['ret_240d'].iloc[loc]
        r120 = df['ret_120d'].iloc[loc]
        r60 = df['ret_60d'].iloc[loc]
        r20 = df['ret_20d'].iloc[loc]

        if np.isnan(r240): r240 = 0
        if np.isnan(r120): r120 = 0
        if np.isnan(r60): r60 = 0
        if np.isnan(r20): r20 = 0

        results.append({'code': sym, 'm240': r240, 'm120': r120, 'm60': r60, 'm20': r20})

    if not results: return pd.DataFrame()
    df = pd.DataFrame(results)
    df['momentum_score'] = (
        df['m240'].rank(pct=True) * 0.30 +
        df['m120'].rank(pct=True) * 0.30 +
        df['m60'].rank(pct=True) * 0.25 +
        df['m20'].rank(pct=True) * 0.15
    ).fillna(0.5)
    return df[['code', 'momentum_score']]


def calc_trend_factors(stock_data, date):
    """趋势因子 - 均线排列/ADX/RSI"""
    results = []
    for sym, df in stock_data.items():
        if date not in df.index: continue
        loc = df.index.get_loc(date)
        if loc < 200: continue
        close = df['Close'].iloc[loc]

        # 均线排列
        sma20 = df['sma20'].iloc[loc]
        sma50 = df['sma50'].iloc[loc]
        sma200 = df['sma200'].iloc[loc]
        ma_score = 0
        if not np.isnan(sma20) and not np.isnan(sma50):
            if close > sma20: ma_score += 0.33
            if sma20 > sma50: ma_score += 0.33
            if not np.isnan(sma200) and sma50 > sma200: ma_score += 0.34

        # ADX
        adx = df['adx14'].iloc[loc]
        adx_s = min(1, adx / 40) if not np.isnan(adx) else 0

        # RSI (50-70最佳)
        rsi = df['rsi14'].iloc[loc]
        rsi_s = max(0, 1 - abs(rsi - 60) / 40) if not np.isnan(rsi) else 0.5

        results.append({'code': sym, 'ma': ma_score, 'adx': adx_s, 'rsi': rsi_s})

    if not results: return pd.DataFrame()
    df = pd.DataFrame(results)
    df['trend_score'] = (
        df['ma'].rank(pct=True).fillna(0.5) * 0.40 +
        df['adx'].rank(pct=True).fillna(0.5) * 0.30 +
        df['rsi'].rank(pct=True).fillna(0.5) * 0.30
    )
    return df[['code', 'trend_score']]


def calc_quality_factors(stock_data, date):
    """质量因子 - 低波/正偏度/小回撤"""
    results = []
    for sym, df in stock_data.items():
        if date not in df.index: continue
        loc = df.index.get_loc(date)
        if loc < 60: continue
        ret = df['ret_1d'].iloc[loc-59:loc+1].dropna()
        if len(ret) < 30: continue

        vol = ret.std()
        pos_ratio = (ret > 0).sum() / len(ret)
        prices = df['Close'].iloc[loc-59:loc+1]
        max_dd = abs(((prices - prices.cummax()) / prices.cummax()).min())
        skew = ret.skew() if len(ret) > 10 else 0

        results.append({
            'code': sym,
            'low_vol': 1/vol if vol > 0 else 0,
            'pos_ratio': pos_ratio,
            'low_dd': 1/(max_dd+0.01),
            'skew': skew
        })

    if not results: return pd.DataFrame()
    df = pd.DataFrame(results)
    df['quality_score'] = (
        df['low_vol'].rank(pct=True).fillna(0.5) * 0.30 +
        df['pos_ratio'].rank(pct=True).fillna(0.5) * 0.25 +
        df['low_dd'].rank(pct=True).fillna(0.5) * 0.25 +
        df['skew'].rank(pct=True).fillna(0.5) * 0.20
    )
    return df[['code', 'quality_score']]


def calc_volatility_factors(stock_data, date, spy_data=None):
    """波动因子 - 低波动优先"""
    results = []
    bench_ret = None
    if spy_data is not None and date in spy_data.index:
        bl = spy_data.index.get_loc(date)
        if bl >= 60:
            bench_ret = spy_data['ret_1d'].iloc[bl-59:bl+1].dropna().values

    for sym, df in stock_data.items():
        if date not in df.index: continue
        loc = df.index.get_loc(date)
        if loc < 40: continue
        ret = df['ret_1d'].iloc[loc-39:loc+1].dropna().values
        if len(ret) < 20: continue
        vol = np.std(ret) * np.sqrt(252)
        neg = ret[ret < 0]
        dvol = np.std(neg) * np.sqrt(252) if len(neg) > 5 else vol
        beta = 1.0
        if bench_ret is not None and len(bench_ret) > 20:
            ml = min(len(ret), len(bench_ret))
            cov = np.cov(ret[:ml], bench_ret[:ml])
            if cov.shape == (2,2) and cov[1,1] > 0:
                beta = cov[0,1] / cov[1,1]
        results.append({'code': sym, 'vol': vol, 'dvol': dvol, 'beta': beta})

    if not results: return pd.DataFrame()
    df = pd.DataFrame(results)
    df['volatility_score'] = (
        (1 - df['vol'].rank(pct=True).fillna(0.5)) * 0.4 +
        (1 - df['dvol'].rank(pct=True).fillna(0.5)) * 0.4 +
        (1 - df['beta'].rank(pct=True).fillna(0.5)) * 0.2
    )
    return df[['code', 'volatility_score']]


def calc_liquidity_factors(stock_data, date):
    """流动性因子"""
    results = []
    for sym, df in stock_data.items():
        if date not in df.index: continue
        loc = df.index.get_loc(date)
        if loc < 20 or 'Volume' not in df.columns: continue
        vol = df['Volume'].iloc[loc]
        if np.isnan(vol) or vol <= 0: continue
        amt = df['Close'].iloc[loc] * vol
        results.append({'code': sym, 'amount': amt})

    if not results: return pd.DataFrame()
    df = pd.DataFrame(results)
    rank = df['amount'].rank(pct=True).fillna(0.5)
    df['liquidity_score'] = (1 - abs(rank - 0.6) * 2).clip(0, 1)
    return df[['code', 'liquidity_score']]


# ================================================================
# 因子处理 & 合成
# ================================================================
def process_and_combine(dfs, factor_weights):
    dfs = [d for d in dfs if len(d) > 0]
    if not dfs: return pd.DataFrame()
    merged = reduce(lambda x, y: pd.merge(x, y, on='code', how='outer'), dfs)
    if len(merged) < 10: return pd.DataFrame()

    fcols = [c for c in merged.columns if c.endswith('_score')]

    # 填充NaN
    for c in fcols:
        m = merged[c].median()
        merged[c] = merged[c].fillna(m if not pd.isna(m) else 0.5)

    # MAD去极值 + Z-Score标准化
    for c in fcols:
        s = merged[c]
        med = s.median()
        mad = np.median(np.abs(s - med))
        if mad > 0:
            s = s.clip(med - 3*mad*1.4826, med + 3*mad*1.4826)
        std = s.std()
        if std > 0 and not pd.isna(std):
            merged[c] = (s - s.mean()) / std
        else:
            merged[c] = 0

    # 合成
    merged['combined_factor'] = 0
    tw = 0
    for c in fcols:
        cat = c.replace('_score', '')
        w = factor_weights.get(cat, 1/len(fcols))
        merged['combined_factor'] += merged[c] * w
        tw += w
    if tw > 0:
        merged['combined_factor'] /= tw

    return merged.dropna(subset=['combined_factor'])


def optimize_portfolio(df, max_stocks, max_weight):
    df = df.drop_duplicates('code').sort_values('combined_factor', ascending=False)
    sel = df.head(max_stocks).copy()
    if len(sel) == 0: return pd.DataFrame(columns=['code', 'weight'])

    n = len(sel)
    smin, smax = sel['combined_factor'].min(), sel['combined_factor'].max()
    if smax > smin:
        sel['weight'] = (sel['combined_factor'] - smin) / (smax - smin) + 0.5
    else:
        sel['weight'] = 1.0

    sel['weight'] = sel['weight'].clip(upper=max_weight)
    wsum = sel['weight'].sum()
    sel['weight'] = sel['weight'] / wsum if wsum > 0 else 1.0 / n

    return sel[['code', 'weight']]


# ================================================================
# 回测引擎
# ================================================================
def get_price(stock_data, sym, date):
    if sym not in stock_data or date not in stock_data[sym].index:
        return None
    return float(stock_data[sym].loc[date, 'Close'])


def run_backtest(stock_data, spy_data, start, end, freq='M'):
    mask = (spy_data.index >= start) & (spy_data.index <= end)
    dates = spy_data[mask].index.tolist()
    if len(dates) < 100: return {'状态': '数据不足'}

    cash = float(INIT_CASH)
    positions = {}  # sym -> shares
    pos_cost = {}
    pos_high = {}

    pv_list = []
    rebalance_count = 0
    stop_events = []
    peak_pv = INIT_CASH
    max_dd = 0
    last_month = None

    for date in dates:
        # 月度调仓
        if freq == 'M' and (last_month is None or date.month != last_month):
            last_month = date.month

            # 获取股票池
            pool = []
            for sym, df in stock_data.items():
                if date not in df.index: continue
                loc = df.index.get_loc(date)
                if loc < MIN_HISTORY_DAYS: continue
                if df['Close'].iloc[loc] < MIN_PRICE: continue
                pool.append(sym)

            if len(pool) >= 20:
                sub = {s: stock_data[s] for s in pool}

                # 计算因子
                factor_dfs = [
                    calc_momentum_factors(sub, date),
                    calc_trend_factors(sub, date),
                    calc_quality_factors(sub, date),
                    calc_volatility_factors(sub, date, spy_data),
                    calc_liquidity_factors(sub, date),
                ]
                merged = process_and_combine(factor_dfs, FACTOR_WEIGHTS)

                if len(merged) >= 10:
                    portfolio = optimize_portfolio(merged, MAX_STOCK_NUM, MAX_SINGLE_WEIGHT)
                    target_weights = dict(zip(portfolio['code'], portfolio['weight']))

                    if len(target_weights) >= 5:
                        # 全部清仓
                        for sym, shares in positions.items():
                            p = get_price(stock_data, sym, date)
                            if p and p > 0 and shares > 0:
                                cash += shares * p * (1 - FEES_RATE)
                        positions = {}
                        pos_cost = {}
                        pos_high = {}

                        # pv = 卖出后总现金
                        pv = cash

                        # 按权重建仓（参考已验证正确的现金分配方式）
                        for sym, weight in target_weights.items():
                            p = get_price(stock_data, sym, date)
                            if not p or p <= 0: continue
                            alloc = pv * weight  # 分配金额
                            shares = alloc * (1 - FEES_RATE) / p  # 扣除手续费后的股数
                            if shares > 0:
                                positions[sym] = shares
                                cash -= alloc  # 减少现金
                                pos_cost[sym] = p
                                pos_high[sym] = p

                        rebalance_count += 1

        # 日度风控 - 个股止损
        for sym in list(positions.keys()):
            shares = positions[sym]
            if shares <= 0:
                del positions[sym]
                continue
            p = get_price(stock_data, sym, date)
            if not p or p <= 0: continue

            cost = pos_cost.get(sym, p)
            high = pos_high.get(sym, p)
            if p > high:
                pos_high[sym] = p
                high = p

            should_stop = False
            reason = None
            pnl = (p - cost) / cost if cost > 0 else 0

            if pnl <= -STOP_LOSS_RATIO:
                should_stop = True
                reason = 'fixed_stop'
            elif pnl > TRAILING_STOP_ACTIVATION and high > 0:
                if (high - p) / high >= TRAILING_STOP_RATIO:
                    should_stop = True
                    reason = 'trailing_stop'

            if should_stop:
                cash += shares * p * (1 - FEES_RATE)
                del positions[sym]
                pos_cost.pop(sym, None)
                pos_high.pop(sym, None)
                stop_events.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'stock': sym, 'reason': reason,
                    'pnl%': round(pnl * 100, 2)
                })

        # 组合风控
        pv = cash
        for sym, shares in positions.items():
            p = get_price(stock_data, sym, date)
            if p and p > 0: pv += shares * p

        if pv > peak_pv: peak_pv = pv
        if peak_pv > 0:
            dd = (peak_pv - pv) / peak_pv
            max_dd = max(max_dd, dd)
            if dd > PORTFOLIO_DRAWDOWN_LIMIT:
                for sym in list(positions.keys()):
                    sell = positions[sym] / 2
                    p = get_price(stock_data, sym, date)
                    if p and p > 0 and sell > 0:
                        cash += sell * p * (1 - FEES_RATE)
                        positions[sym] -= sell

        # 记录当日市值
        pv = cash
        for sym, shares in positions.items():
            p = get_price(stock_data, sym, date)
            if p and p > 0: pv += shares * p
        pv_list.append(pv)

    return _calc_perf(pv_list, dates, rebalance_count, stop_events)


def _calc_perf(pv_list, dates, rebal_count, stops):
    pv = np.array(pv_list, dtype=float)
    rets = np.diff(pv) / pv[:-1]
    rets = np.concatenate([[0], rets])

    total_r = (pv[-1] / pv[0] - 1) * 100
    ny = len(pv) / 252
    annual = ((1 + total_r/100) ** (1/ny) - 1) * 100 if ny > 0 and total_r > -100 else -100

    peak = np.maximum.accumulate(pv)
    dd = (pv - peak) / peak * 100
    max_dd = abs(dd.min())

    drf = RISK_FREE_RATE / 252
    exc = rets - drf
    sharpe = np.mean(exc) / np.std(exc) * np.sqrt(252) if np.std(exc) > 0 else 0
    calmar = annual / max_dd if max_dd > 0 else 0

    pv_s = pd.Series(pv, index=dates)
    yearly = {}
    for y in sorted(pv_s.index.year.unique()):
        yd = pv_s[pv_s.index.year == y]
        if len(yd) > 1:
            yearly[str(y)] = round((yd.iloc[-1] / yd.iloc[0] - 1) * 100, 2)

    monthly = {}
    for y in sorted(pv_s.index.year.unique()):
        for m in range(1, 13):
            md = pv_s[(pv_s.index.year == y) & (pv_s.index.month == m)]
            if len(md) > 1:
                monthly[f"{y}-{m:02d}"] = round((md.iloc[-1] / md.iloc[0] - 1) * 100, 2)

    win = (rets > 0).sum()
    total = len(rets[rets != 0])
    wr = win / total * 100 if total > 0 else 0

    aw = rets[rets > 0].mean() if (rets > 0).any() else 0
    al = abs(rets[rets < 0].mean()) if (rets < 0).any() else 1
    plr = aw / al if al > 0 else 0

    streak = max_streak = 0
    for r in rets < 0:
        streak = streak + 1 if r else 0
        max_streak = max(max_streak, streak)

    fs = sum(1 for e in stops if e['reason'] == 'fixed_stop')
    ts = sum(1 for e in stops if e['reason'] == 'trailing_stop')

    return {
        '状态': '✅',
        '总收益率%': round(total_r, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': round(sharpe, 2),
        '卡尔马比率': round(calmar, 2),
        '胜率%': round(wr, 2),
        '盈亏比': round(plr, 2),
        '最大连续亏损天数': max_streak,
        '年度收益': yearly,
        '月度收益': monthly,
        '止损事件': {'固定止损': fs, '移动止损': ts, '总计': len(stops)},
        '调仓次数': rebal_count,
    }


def run_buyhold_spy(spy_data, start, end):
    mask = (spy_data.index >= start) & (spy_data.index <= end)
    dates = spy_data[mask].index
    pv = spy_data.loc[dates, 'Close'].values.astype(float)
    pv = pv / pv[0] * INIT_CASH

    rets = np.diff(pv) / pv[:-1]
    rets = np.concatenate([[0], rets])
    tr = (pv[-1] / pv[0] - 1) * 100
    ny = len(pv) / 252
    an = ((1 + tr/100) ** (1/ny) - 1) * 100
    peak = np.maximum.accumulate(pv)
    mdd = abs(((pv - peak) / peak * 100).min())
    exc = rets - RISK_FREE_RATE / 252
    sh = np.mean(exc) / np.std(exc) * np.sqrt(252) if np.std(exc) > 0 else 0
    ca = an / mdd if mdd > 0 else 0

    pv_s = pd.Series(pv, index=dates)
    yearly = {}
    for y in sorted(pv_s.index.year.unique()):
        yd = pv_s[pv_s.index.year == y]
        if len(yd) > 1:
            yearly[str(y)] = round((yd.iloc[-1] / yd.iloc[0] - 1) * 100, 2)

    return {
        '总收益率%': round(tr, 2), '年化收益%': round(an, 2),
        '最大回撤%': round(mdd, 2), '夏普比率': round(sh, 2),
        '卡尔马比率': round(ca, 2), '年度收益': yearly,
    }


def overfitting_test(sd, spy, start, end):
    mask = (spy.index >= start) & (spy.index <= end)
    dates = spy[mask].index
    sp = int(len(dates) * 0.7)
    te = dates[sp].strftime('%Y-%m-%d')
    ts = dates[sp+1].strftime('%Y-%m-%d')

    tr = run_backtest(sd, spy, start, te)
    tst = run_backtest(sd, spy, ts, end)
    ratio = tst.get('年化收益%', 0) / tr.get('年化收益%', 1) if tr.get('年化收益%', 0) != 0 else 0

    return {
        '训练集': {k: tr[k] for k in ['年化收益%', '最大回撤%', '夏普比率']},
        '测试集': {k: tst[k] for k in ['年化收益%', '最大回撤%', '夏普比率']},
        '过拟合比率': round(ratio, 2),
    }


# ================================================================
# 主函数
# ================================================================
def main():
    print("=" * 70)
    print("  机构级多因子量化策略 - Alpha因子增强策略 v3")
    print("=" * 70)

    print("\n📂 加载数据...")
    sd = load_all_stocks(600)
    spy = load_etf('SPY')
    print(f"  ✅ {len(sd)} 只股票 + SPY")

    print("📊 计算技术指标...")
    for sym in list(sd.keys()):
        sd[sym] = compute_indicators(sd[sym])
    spy = compute_indicators(spy)
    print("  ✅ 完成")

    print(f"\n🚀 运行回测: {BACKTEST_START} ~ {BACKTEST_END}")
    result = run_backtest(sd, spy, BACKTEST_START, BACKTEST_END)

    print("📈 运行基准 (SPY Buy & Hold)...")
    spy_r = run_buyhold_spy(spy, BACKTEST_START, BACKTEST_END)

    print("🔬 过拟合检测...")
    overfit = overfitting_test(sd, spy, BACKTEST_START, BACKTEST_END)

    # 输出
    print("\n" + "=" * 70)
    print("  📋 回测报告")
    print("=" * 70)

    print(f"\n📊 策略绩效 vs 基准(SPY):")
    print(f"  {'指标':<14} {'多因子策略':>12} {'SPY持有':>12} {'超额':>10}")
    print(f"  {'-'*50}")
    for key, label in [('总收益率%', '总收益率'), ('年化收益%', '年化收益'), ('最大回撤%', '最大回撤')]:
        mf, sp = result[key], spy_r[key]
        print(f"  {label:<12} {mf:>11.2f}% {sp:>11.2f}% {mf-sp:>+9.2f}%")
    for key, label in [('夏普比率', '夏普比率'), ('卡尔马比率', '卡尔马比率')]:
        mf, sp = result[key], spy_r[key]
        print(f"  {label:<12} {mf:>12.2f} {sp:>12.2f}")
    print(f"  {'胜率':<12} {result['胜率%']:>11.2f}%")
    print(f"  {'盈亏比':<12} {result['盈亏比']:>12.2f}")
    print(f"  {'最大连亏天数':<12} {result['最大连续亏损天数']:>12d}")
    print(f"  {'调仓次数':<12} {result['调仓次数']:>12d}")

    print(f"\n📅 年度收益对比:")
    print(f"  {'年份':<8} {'多因子策略':>12} {'SPY持有':>12} {'超额':>10}")
    print(f"  {'-'*44}")
    all_y = sorted(set(list(result['年度收益'].keys()) + list(spy_r.get('年度收益', {}).keys())))
    for y in all_y:
        mf = result['年度收益'].get(y, 0)
        sp = spy_r.get('年度收益', {}).get(y, 0)
        print(f"  {y:<8} {mf:>11.2f}% {sp:>11.2f}% {mf-sp:>+9.2f}%")

    sl = result['止损事件']
    print(f"\n🛡️ 止损: 固定{sl['固定止损']}次 + 移动{sl['移动止损']}次 = {sl['总计']}次")

    print(f"\n🔬 过拟合检测:")
    tr, te = overfit['训练集'], overfit['测试集']
    for k in ['年化收益%', '最大回撤%', '夏普比率']:
        print(f"  {k:<10} 训练:{tr[k]:>8.2f}  测试:{te[k]:>8.2f}")
    print(f"  过拟合比率: {overfit['过拟合比率']} ({'✅良好' if 0.5<=overfit['过拟合比率']<=2.0 else '⚠️过拟合'})")

    # 保存
    report = {
        '策略名称': 'Alpha因子增强策略(多因子选股) v3',
        '策略类型': '多因子选股+组合优化+风险控制',
        '因子体系': FACTOR_WEIGHTS,
        '调仓频率': '月度',
        '回测区间': f"{BACKTEST_START} ~ {BACKTEST_END}",
        '初始资金': INIT_CASH,
        '股票池': f"美股{len(sd)}只",
        '策略绩效': {k: result[k] for k in ['总收益率%','年化收益%','最大回撤%','夏普比率','卡尔马比率','胜率%','盈亏比','最大连续亏损天数']},
        '基准绩效': {k: spy_r[k] for k in ['总收益率%','年化收益%','最大回撤%','夏普比率','卡尔马比率']},
        '超额收益': {
            '年化超额%': round(result['年化收益%'] - spy_r['年化收益%'], 2),
            '总超额%': round(result['总收益率%'] - spy_r['总收益率%'], 2),
        },
        '年度收益对比': {y: {'策略': result['年度收益'].get(y,0), 'SPY': spy_r.get('年度收益',{}).get(y,0)} for y in all_y},
        '月度收益': result['月度收益'],
        '止损统计': sl,
        '调仓次数': result['调仓次数'],
        '过拟合检测': overfit,
        '风控参数': {
            '个股止损': f'{STOP_LOSS_RATIO*100}%',
            '追踪止损': f'盈利{TRAILING_STOP_ACTIVATION*100}%后回撤{TRAILING_STOP_RATIO*100}%',
            '组合最大回撤': f'{PORTFOLIO_DRAWDOWN_LIMIT*100}%',
            '最大持仓数': MAX_STOCK_NUM,
            '单只最大权重': f'{MAX_SINGLE_WEIGHT*100}%',
        },
    }

    with open('/data/workspace/multi_factor_backtest_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n📁 报告已保存: multi_factor_backtest_report.json")
    print("=" * 70)
    return report


if __name__ == '__main__':
    main()
