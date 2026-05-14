#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF池精简对比回测
============================
对比旧池(35只) vs 新池(6只+1只安全) 在1年/3年/5年区间的表现

8: 新ETF池：159915(创业板) 513100(纳指) 511220(城投) 159985(豆粕) 518880(黄金) 501018(南方原油) 161226(白银)
安全池不变：511880(银华日利) 511010(国债) 511260(十年国债) 511220(城投)
"""

import os, sys, math, warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

# ================================================================
# 旧ETF池（35只）
# ================================================================
OLD_POOL = [
    '518880_XSHG', '159985_XSHE', '513100_XSHG',
    '159915_XSHE', '511880_XSHG', '510300_XSHG',
    '510500_XSHG', '512880_XSHG', '512660_XSHG',
    '513500_XSHG', '513130_XSHG', '512100_XSHG',
    '512040_XSHG', '511010_XSHG', '511260_XSHG',
    '510050_XSHG', '512890_XSHG', '513080_XSHG',
    '513520_XSHG', '513690_XSHG', '501018_XSHG',
    '159792_XSHE', '159967_XSHE', '159980_XSHE',
    '159981_XSHE', '511220_XSHG', '511380_XSHG',
    '159919_XSHE', '159920_XSHE', '510210_XSHG',
    '513290_XSHG', '513310_XSHG', '513050_XSHG',
    '159529_XSHE', '159509_XSHE',
]

OLD_NAMES = {
    '518880_XSHG': '黄金ETF', '159985_XSHE': '豆粕ETF', '513100_XSHG': '纳指ETF',
    '159915_XSHE': '创业板ETF', '511880_XSHG': '银华日利', '510300_XSHG': '沪深300ETF',
    '510500_XSHG': '中证500ETF', '512880_XSHG': '证券ETF', '512660_XSHG': '军工ETF',
    '513500_XSHG': '标普500ETF', '513130_XSHG': '恒生科技ETF', '512100_XSHG': '中证1000ETF',
    '512040_XSHG': '沪深300价值', '511010_XSHG': '国债ETF', '511260_XSHG': '十年国债ETF',
    '510050_XSHG': '上证50ETF', '512890_XSHG': '红利低波ETF', '513080_XSHG': '德国DAX',
    '513520_XSHG': '日经225ETF', '513690_XSHG': '法国CAC40', '501018_XSHG': '南方原油',
    '159792_XSHE': '科技创新ETF', '159967_XSHE': '创成长ETF', '159980_XSHE': '有色金属ETF',
    '159981_XSHE': '能源化工ETF', '511220_XSHG': '城投ETF', '511380_XSHG': '十年国开ETF',
    '159919_XSHE': '沪深300联接', '159920_XSHE': '恒生ETF', '510210_XSHG': '上证ETF',
    '513290_XSHG': '纳指生物ETF', '513310_XSHG': '东南亚科技', '513050_XSHG': '中日ETF',
    '159529_XSHE': '科创50ETF', '159509_XSHE': '中证500联接',
}

# ================================================================
# 新ETF池（7只 + 安全池不变）
# ================================================================
NEW_POOL = [
    '159915_XSHE',   # 创业板ETF
    '513100_XSHG',   # 纳指ETF
    '159985_XSHE',   # 豆粕ETF
    '518880_XSHG',   # 黄金ETF
    '501018_XSHG',   # 南方原油
    '161226_XSHE',   # 白银LOF
]

NEW_NAMES = {
    '159915_XSHE': '创业板ETF', '513100_XSHG': '纳指ETF',
    '159985_XSHE': '豆粕ETF', '518880_XSHG': '黄金ETF',
    '501018_XSHG': '南方原油', '161226_XSHE': '白银LOF',
}

# 安全池（仅城投ETF一只）
SAFE_POOL = ['511220_XSHG']
SAFE_NAMES = {'511220_XSHG': '城投ETF'}

# 完整新池 = 投资池 + 安全池
NEW_FULL_POOL = list(dict.fromkeys(NEW_POOL + SAFE_POOL))  # 去重保序

ALL_NAMES = {**OLD_NAMES, **NEW_NAMES, '161226_XSHE': '白银LOF'}

# ================================================================
# 费率参数
# ================================================================
BUY_FEE_RATE = 0.0003
SELL_FEE_RATE = 0.0008
MIN_COMMISSION = 5.0
INIT_CAPITAL = 1_000_000

# ================================================================
# 数据加载
# ================================================================
DATA_DIR = '/data/workspace/back_trader_stocks/a'

def load_data(etf_list, start_date=None, end_date=None):
    """加载ETF日频数据，返回close_prices宽表"""
    all_data = {}
    for code in etf_list:
        fpath = os.path.join(DATA_DIR, f'{code}.csv')
        if not os.path.exists(fpath):
            continue
        df = pd.read_csv(fpath, parse_dates=['Date'], index_col='Date')
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        if len(df) > 0:
            all_data[code] = df['Close']
    
    if not all_data:
        return pd.DataFrame()
    
    close = pd.DataFrame(all_data)
    close = close.sort_index()
    close = close.dropna(how='all')
    return close


# ================================================================
# 策略函数（与cn_daily_sim_task.py一致）
# ================================================================
def qixing_rotation(close_prices, etf_pool, safe_assets,
                    short_lookback=25, long_lookback=250,
                    drop_threshold=0.95, long_score_cap=0.5,
                    short_score_cap=6.0, rebalance_freq='W-FRI'):
    """七星高照ETF轮动策略 — 纯函数版"""
    safe_in_pool = [a for a in safe_assets if a in etf_pool and a in close_prices.columns]
    default_asset = safe_in_pool[0] if safe_in_pool else (etf_pool[-1] if etf_pool else close_prices.columns[0])

    holding = pd.Series(default_asset, index=close_prices.index)

    if len(close_prices) < 15:
        return holding

    rebal_dates = close_prices.resample(rebalance_freq).last().dropna().index
    rebal_dates = rebal_dates[rebal_dates.isin(close_prices.index)]

    if len(rebal_dates) < 5:
        return holding

    pool_in_data = [a for a in etf_pool if a in close_prices.columns]

    for i, r_date in enumerate(rebal_dates):
        try:
            loc = close_prices.index.get_loc(r_date)
        except KeyError:
            continue

        actual_short = min(short_lookback, loc)
        actual_long = min(long_lookback, loc)

        if actual_long < actual_short or actual_short < 5:
            continue

        best_etf = None
        best_score = -999

        for asset in pool_in_data:
            sp = close_prices[asset].iloc[max(0, loc - actual_short):loc + 1]
            sp = sp.dropna()
            if len(sp) < 5:
                continue

            if len(sp) >= 4:
                recent = sp.iloc[-4:]
                dropped = False
                for j in range(len(recent) - 1):
                    if recent.iloc[j] > 0:
                        daily_change = recent.iloc[j + 1] / recent.iloc[j]
                        if daily_change < drop_threshold:
                            dropped = True
                            break
                if dropped:
                    continue

            y = np.log(sp.values.astype(float))
            x = np.arange(len(y), dtype=float)
            w = np.linspace(1, 2, len(y))

            try:
                coeffs = np.polyfit(x, y, 1, w=w)
                slope = coeffs[0]
            except:
                continue

            ann_return = math.exp(slope * 252) - 1
            y_pred = slope * x + coeffs[1]
            ss_res = np.sum(w * (y - y_pred) ** 2)
            y_mean = np.average(y, weights=w)
            ss_tot = np.sum(w * (y - y_mean) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0

            short_score = ann_return * r2
            if not (0 < short_score < short_score_cap):
                short_score = 0

            lp = close_prices[asset].iloc[max(0, loc - actual_long):loc + 1]
            lp = lp.dropna()
            if len(lp) < 20:
                combined = short_score
            else:
                y2 = np.log(lp.values.astype(float))
                x2 = np.arange(len(y2), dtype=float)
                w2 = np.linspace(1, 2, len(y2))

                try:
                    coeffs2 = np.polyfit(x2, y2, 1, w=w2)
                    slope2 = coeffs2[0]
                except:
                    combined = short_score
                else:
                    ann2 = math.exp(slope2 * 252) - 1
                    y2_pred = slope2 * x2 + coeffs2[1]
                    ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                    y2_mean = np.average(y2, weights=w2)
                    ss_tot2 = np.sum(w2 * (y2 - y2_mean) ** 2)
                    r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 1e-10 else 0

                    long_score = ann2 * r22
                    if not (long_score > 0 and long_score < long_score_cap):
                        long_score = 0

                    combined = short_score + long_score

            if combined > best_score:
                best_score = combined
                best_etf = asset

        if best_etf is None or best_score <= 0:
            best_etf = default_asset

        if i + 1 < len(rebal_dates):
            next_r = rebal_dates[i + 1]
            mask = (close_prices.index > r_date) & (close_prices.index <= next_r)
        else:
            mask = close_prices.index > r_date

        for idx in close_prices.index[mask]:
            holding[idx] = best_etf

    if len(holding) > 20:
        for idx in close_prices.index[:20]:
            holding[idx] = default_asset

    return holding


# ================================================================
# 回测引擎（含手续费）
# ================================================================
def backtest_with_fees(close_prices, holding, init_capital=INIT_CAPITAL):
    """基于持仓信号进行含手续费的逐日回测"""
    nav = [float(init_capital)]
    current_pos = None    # (etf_code, shares, avg_price)
    cash = float(init_capital)
    trade_count = 0

    dates = close_prices.index.tolist()
    
    for i in range(1, len(dates)):
        date = dates[i]
        prev_date = dates[i - 1]
        
        target_etf = holding.get(date, holding.get(prev_date, None))
        if target_etf is None or target_etf not in close_prices.columns:
            nav.append(nav[-1])
            continue

        price_today = close_prices[target_etf].get(date, np.nan)
        if pd.isna(price_today) or price_today <= 0:
            nav.append(nav[-1])
            continue

        # 检查是否需要换仓
        if current_pos is None:
            # 首次买入
            fee = max(cash * BUY_FEE_RATE, MIN_COMMISSION)
            buy_amount = cash - fee
            shares = int(buy_amount / price_today / 100) * 100
            if shares <= 0:
                nav.append(cash)
                continue
            cost = shares * price_today
            actual_fee = max(cost * BUY_FEE_RATE, MIN_COMMISSION)
            cash -= (cost + actual_fee)
            current_pos = (target_etf, shares, price_today)
            trade_count += 1
        elif current_pos[0] != target_etf:
            # 换仓：卖出旧持仓
            old_code, old_shares, old_avg = current_pos
            old_price = close_prices[old_code].get(date, np.nan)
            if pd.isna(old_price) or old_price <= 0:
                old_price = old_avg  # fallback
            
            sell_amount = old_shares * old_price
            sell_fee = max(sell_amount * SELL_FEE_RATE, MIN_COMMISSION)
            cash = sell_amount - sell_fee
            
            # 买入新持仓
            fee = max(cash * BUY_FEE_RATE, MIN_COMMISSION)
            buy_amount = cash - fee
            shares = int(buy_amount / price_today / 100) * 100
            if shares <= 0:
                nav.append(cash)
                current_pos = None
                continue
            cost = shares * price_today
            actual_fee = max(cost * BUY_FEE_RATE, MIN_COMMISSION)
            cash -= (cost + actual_fee)
            cash = max(cash, 0)
            current_pos = (target_etf, shares, price_today)
            trade_count += 1

        # 计算当日净值
        if current_pos:
            code, shares, avg_price = current_pos
            cur_price = close_prices[code].get(date, avg_price)
            if pd.isna(cur_price) or cur_price <= 0:
                cur_price = avg_price
            market_value = shares * cur_price
            total = market_value + cash
        else:
            total = cash
        
        nav.append(total)

    nav_series = pd.Series(nav, index=dates)
    return nav_series, trade_count


# ================================================================
# 绩效指标计算
# ================================================================
def calc_metrics(nav, trade_count, years):
    """计算回测绩效指标"""
    if len(nav) < 10 or years <= 0:
        return {}
    
    total_return = (nav.iloc[-1] / nav.iloc[0]) - 1
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    # 日收益率
    daily_ret = nav.pct_change().dropna()
    if len(daily_ret) == 0:
        return {}
    
    # 夏普比率（无风险利率2%）
    rf_daily = 0.02 / 252
    sharpe = (daily_ret.mean() - rf_daily) / daily_ret.std() * math.sqrt(252) if daily_ret.std() > 0 else 0
    
    # 最大回撤
    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    max_dd = drawdown.min()
    
    # 胜率
    win_rate = (daily_ret > 0).sum() / len(daily_ret) if len(daily_ret) > 0 else 0
    
    # 盈亏比
    gains = daily_ret[daily_ret > 0]
    losses = daily_ret[daily_ret < 0]
    profit_factor = gains.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf')
    
    # 年交易次数
    annual_trades = trade_count / years if years > 0 else 0
    
    # Calmar比率
    calmar = annual_return / abs(max_dd) if max_dd != 0 else float('inf')
    
    return {
        '总收益': f'{total_return*100:.2f}%',
        '年化收益': f'{annual_return*100:.2f}%',
        '年化_值': annual_return,
        '夏普比率': f'{sharpe:.2f}',
        '夏普_值': sharpe,
        '最大回撤': f'{max_dd*100:.2f}%',
        '回撤_值': max_dd,
        '胜率': f'{win_rate*100:.1f}%',
        '盈亏比': f'{profit_factor:.2f}',
        '年交易次数': f'{annual_trades:.1f}',
        '交易总次数': trade_count,
        'Calmar比率': f'{calmar:.2f}',
        '期末净值': f'{nav.iloc[-1]/nav.iloc[0]:.4f}',
    }


# ================================================================
# 持仓分布统计
# ================================================================
def holding_stats(holding, etf_names):
    """统计各ETF的持仓占比"""
    counts = holding.value_counts()
    total = len(holding)
    stats = []
    for code, cnt in counts.items():
        pct = cnt / total * 100
        name = etf_names.get(code, code)
        stats.append((name, code, pct, cnt))
    return sorted(stats, key=lambda x: -x[2])


# ================================================================
# 主回测流程
# ================================================================
def run_comparison():
    print("=" * 80)
    print("七星高照ETF池精简对比回测")
    print("=" * 80)
    
    # 新池描述
    print("\n📦 新ETF池（6只投资+1只安全）:")
    for code in NEW_FULL_POOL:
        name = ALL_NAMES.get(code, code)
        tag = "🔒安全池" if code in SAFE_POOL else "📈投资池"
        print(f"  {tag} {code}: {name}")
    
    print(f"\n📦 旧ETF池: {len(OLD_POOL)}只")
    
    # 回测区间
    end_date = '2026-04-27'
    periods = {
        '近1年': {'start': '2025-04-27', 'years': 1.0},
        '近3年': {'start': '2023-04-27', 'years': 3.0},
        '近5年': {'start': '2021-04-27', 'years': 5.0},
    }
    
    all_results = {}
    
    for period_name, cfg in periods.items():
        print(f"\n{'='*80}")
        print(f"📊 回测区间: {period_name} ({cfg['start']} ~ {end_date})")
        print(f"{'='*80}")
        
        # 加载数据
        all_etfs = list(dict.fromkeys(OLD_POOL + NEW_FULL_POOL + SAFE_POOL))
        close = load_data(all_etfs, start_date=cfg['start'], end_date=end_date)
        
        if len(close) < 30:
            print(f"  ❌ 数据不足，跳过")
            continue
        
        print(f"  📊 数据加载完成: {len(close)}交易日, {len(close.columns)}只ETF")
        
        # 实际年份
        actual_years = (close.index[-1] - close.index[0]).days / 365.25
        
        # ---- 旧池回测 ----
        old_pool_with_safe = list(dict.fromkeys(OLD_POOL + SAFE_POOL))
        old_holding = qixing_rotation(close, old_pool_with_safe, SAFE_POOL)
        old_nav, old_trades = backtest_with_fees(close, old_holding)
        old_metrics = calc_metrics(old_nav, old_trades, actual_years)
        old_hstat = holding_stats(old_holding, ALL_NAMES)
        
        # ---- 新池回测 ----
        new_holding = qixing_rotation(close, NEW_FULL_POOL, SAFE_POOL)
        new_nav, new_trades = backtest_with_fees(close, new_holding)
        new_metrics = calc_metrics(new_nav, new_trades, actual_years)
        new_hstat = holding_stats(new_holding, ALL_NAMES)
        
        all_results[period_name] = {
            'old': old_metrics, 'new': new_metrics,
            'old_hstat': old_hstat, 'new_hstat': new_hstat,
            'actual_years': actual_years,
        }
        
        # 打印对比
        print(f"\n  ┌─────────────────────────────────────────────────────────────┐")
        print(f"  │ {'指标':<12} │ {'旧池(35只)':<16} │ {'新池(6+1只)':<16} │ {'差异':<12} │")
        print(f"  ├─────────────────────────────────────────────────────────────┤")
        
        compare_keys = ['总收益', '年化收益', '夏普比率', '最大回撤', '胜率', '盈亏比', '年交易次数', 'Calmar比率', '期末净值']
        value_keys = ['总收益', '年化收益', '夏普比率', '最大回撤', '胜率', '盈亏比', '年交易次数', 'Calmar比率', '期末净值']
        
        for key in compare_keys:
            old_v = old_metrics.get(key, '-')
            new_v = new_metrics.get(key, '-')
            
            # 计算数值差异
            num_key = key.replace('总收益', '年化_值').replace('年化收益', '年化_值').replace('夏普比率', '夏普_值').replace('最大回撤', '回撤_值')
            if num_key in old_metrics and num_key in new_metrics:
                try:
                    diff = new_metrics[num_key] - old_metrics[num_key]
                    diff_str = f'{diff*100:+.2f}%' if isinstance(diff, float) and abs(diff) < 10 else f'{diff:+.2f}'
                except:
                    diff_str = '-'
            else:
                diff_str = '-'
            
            print(f"  │ {key:<12} │ {str(old_v):<16} │ {str(new_v):<16} │ {diff_str:<12} │")
        
        print(f"  └─────────────────────────────────────────────────────────────┘")
        
        # 持仓分布对比
        print(f"\n  📊 旧池持仓分布 TOP10:")
        for name, code, pct, cnt in old_hstat[:10]:
            bar = '█' * int(pct / 2)
            print(f"    {name:<12} {pct:>5.1f}% {bar}")
        
        print(f"\n  📊 新池持仓分布:")
        for name, code, pct, cnt in new_hstat:
            bar = '█' * int(pct / 2)
            print(f"    {name:<12} {pct:>5.1f}% {bar}")
    
    # ================================================================
    # 汇总对比表
    # ================================================================
    print(f"\n\n{'='*100}")
    print(f"📋 三区间汇总对比")
    print(f"{'='*100}")
    
    print(f"\n  ┌────────────┬───────────────────────────────────┬───────────────────────────────────┐")
    print(f"  │ {'区间':<10} │ {'旧池(35只)':^33} │ {'新池(6+1只)':^33} │")
    print(f"  │ {'':<10} │ {'年化':<11} {'夏普':<8} {'回撤':<8} {'胜率':<6} │ {'年化':<11} {'夏普':<8} {'回撤':<8} {'胜率':<6} │")
    print(f"  ├────────────┼───────────────────────────────────┼───────────────────────────────────┤")
    
    for period_name in ['近1年', '近3年', '近5年']:
        if period_name not in all_results:
            continue
        r = all_results[period_name]
        o = r['old']
        n = r['new']
        
        o_ann = o.get('年化收益', '-')
        o_sh = o.get('夏普比率', '-')
        o_dd = o.get('最大回撤', '-')
        o_wr = o.get('胜率', '-')
        
        n_ann = n.get('年化收益', '-')
        n_sh = n.get('夏普比率', '-')
        n_dd = n.get('最大回撤', '-')
        n_wr = n.get('胜率', '-')
        
        print(f"  │ {period_name:<10} │ {o_ann:<11} {o_sh:<8} {o_dd:<8} {o_wr:<6} │ {n_ann:<11} {n_sh:<8} {n_dd:<8} {n_wr:<6} │")
    
    print(f"  └────────────┴───────────────────────────────────┴───────────────────────────────────┘")
    
    # ================================================================
    # 关键发现
    # ================================================================
    print(f"\n\n{'='*100}")
    print(f"🔍 关键发现与结论")
    print(f"{'='*100}")
    
    # 判断新池是否更优
    better_count = 0
    worse_count = 0
    for period_name in ['近1年', '近3年', '近5年']:
        if period_name not in all_results:
            continue
        r = all_results[period_name]
        o_ann = r['old'].get('年化_值', 0)
        n_ann = r['new'].get('年化_值', 0)
        o_sh = r['old'].get('夏普_值', 0)
        n_sh = r['new'].get('夏普_值', 0)
        o_dd = r['old'].get('回撤_值', 0)
        n_dd = r['new'].get('回撤_值', 0)
        
        # 综合评分：年化+夏普-回撤
        o_score = o_ann + o_sh * 0.1 - abs(o_dd) * 0.5
        n_score = n_ann + n_sh * 0.1 - abs(n_dd) * 0.5
        
        if n_score > o_score:
            better_count += 1
            print(f"\n  ✅ {period_name}: 新池更优")
            print(f"     年化: {r['new']['年化收益']} vs {r['old']['年化收益']}")
            print(f"     夏普: {r['new']['夏普比率']} vs {r['old']['夏普比率']}")
            print(f"     回撤: {r['new']['最大回撤']} vs {r['old']['最大回撤']}")
        else:
            worse_count += 1
            print(f"\n  ❌ {period_name}: 旧池更优")
            print(f"     年化: {r['new']['年化收益']} vs {r['old']['年化收益']}")
            print(f"     夏普: {r['new']['夏普比率']} vs {r['old']['夏普比率']}")
            print(f"     回撤: {r['new']['最大回撤']} vs {r['old']['最大回撤']}")
    
    print(f"\n  📊 总体: 新池在{better_count}个区间更优，旧池在{worse_count}个区间更优")
    
    if better_count > worse_count:
        print(f"\n  🏆 结论: 精简ETF池表现更好！减少噪音标的，策略聚焦核心资产，建议切换到新池")
    elif better_count < worse_count:
        print(f"\n  ⚠️ 结论: 旧池整体更优，精简后损失了部分轮动机会")
    else:
        print(f"\n  ⚖️ 结论: 新旧池各有千秋，可根据偏好选择")
    
    # ================================================================
    # 新池各标的贡献分析
    # ================================================================
    print(f"\n\n{'='*100}")
    print(f"📈 新池各ETF标的特征分析")
    print(f"{'='*100}")
    
    for code in NEW_POOL:
        name = ALL_NAMES.get(code, code)
        fpath = os.path.join(DATA_DIR, f'{code}.csv')
        if os.path.exists(fpath):
            df = pd.read_csv(fpath, parse_dates=['Date'], index_col='Date')
            df_5y = df[df.index >= '2021-04-27']
            if len(df_5y) > 20:
                total_ret = (df_5y['Close'].iloc[-1] / df_5y['Close'].iloc[0] - 1) * 100
                ann_ret = ((df_5y['Close'].iloc[-1] / df_5y['Close'].iloc[0]) ** (252/len(df_5y)) - 1) * 100
                daily_ret = df_5y['Close'].pct_change().dropna()
                vol = daily_ret.std() * math.sqrt(252) * 100
                max_dd_val = ((df_5y['Close'] / df_5y['Close'].cummax()) - 1).min() * 100
                print(f"  📌 {name}({code}): 5年总收益{total_ret:+.1f}%, 年化{ann_ret:+.1f}%, 波动率{vol:.1f}%, 最大回撤{max_dd_val:.1f}%")
    
    return all_results


if __name__ == '__main__':
    results = run_comparison()
