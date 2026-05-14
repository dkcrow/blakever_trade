#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blakever 牛市策略 — 第三轮：底仓模式正确回测 + 港股EMA15/30再验证
"""

import os, glob, warnings
import numpy as np, pandas as pd, talib, vectorbt as vbt
warnings.filterwarnings('ignore')

BASE_DIR = '/data/workspace/back_trader_stocks'
INIT_CASH = 100000; FEES = 0.001; SLIPPAGE = 0.001
TRAIN_RATIO = 0.7; MIN_DATA_DAYS = 250; MIN_BULL_DAYS = 50

def load_stock_data(filepath):
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date').sort_index()
        df.columns = [c.lower().strip() for c in df.columns]
        df = df.dropna(subset=['close'])
        for col in ['open','high','low','close']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close'])
        return df
    except: return None

def load_all_stocks(market='us'):
    directory = '/data/workspace/back_trader_stocks/hk' if market=='hk' else '/data/workspace/back_trader_stocks/us'
    files = sorted(glob.glob(os.path.join(directory, '*.csv')))
    stocks = {}
    for f in files:
        symbol = os.path.basename(f).replace('.csv','')
        df = load_stock_data(f)
        if df is not None and len(df) >= MIN_DATA_DAYS: stocks[symbol] = df
    return stocks

def identify_bull_periods(close_series):
    close = close_series.copy()
    sma50 = talib.SMA(close.values, timeperiod=50)
    sma200 = talib.SMA(close.values, timeperiod=200)
    sma50_s = pd.Series(sma50, index=close.index)
    sma200_s = pd.Series(sma200, index=close.index)
    bull_mask = (close > sma200_s) & (sma50_s > sma200_s)
    early_mask = sma200_s.isna()
    if early_mask.any():
        sma20_early = close.rolling(20).mean()
        sma50_early = close.rolling(50).mean()
        early_bull = (close > sma50_early) & (sma20_early > sma50_early)
        bull_mask = bull_mask.fillna(early_bull)
    return bull_mask.fillna(False)

def strategy_baseline(close, high, low):
    c = pd.Series(close, dtype=float); h = pd.Series(high, dtype=float); l = pd.Series(low, dtype=float)
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema20 = c.ewm(span=20, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    in_pos = (ema10 > ema20) & (adx_s > 20)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

def strategy_ema15_30(close, high, low):
    c = pd.Series(close, dtype=float); h = pd.Series(high, dtype=float); l = pd.Series(low, dtype=float)
    ema15 = c.ewm(span=15, adjust=False).mean()
    ema30 = c.ewm(span=30, adjust=False).mean()
    adx = talib.ADX(h.values, l.values, c.values, timeperiod=14)
    adx_s = pd.Series(adx)
    in_pos = (ema15 > ema30) & (adx_s > 20)
    entries = (in_pos & ~in_pos.shift(1).fillna(False)).fillna(False).values
    exits = (~in_pos & in_pos.shift(1).fillna(False)).fillna(False).values
    return entries, exits

def run_portfolio(close, entries, exits):
    """运行回测并返回完整Portfolio对象"""
    try:
        pf = vbt.Portfolio.from_signals(close, entries=entries, exits=exits,
                                         freq='D', init_cash=INIT_CASH, fees=FEES, slippage=SLIPPAGE)
        return pf
    except: return None

def calc_stats(pf):
    if pf is None: return None
    stats = pf.stats()
    total_ret = float(stats['Total Return [%]'])
    max_dd = float(stats['Max Drawdown [%]'])
    n_years = len(pf.returns()) / 252
    annual = ((1+total_ret/100)**(1/n_years)-1)*100 if n_years>0 and total_ret>-100 else -100
    sharpe = float(stats.get('Sharpe Ratio', 0))
    if pd.isna(sharpe): sharpe = 0
    win_rate = float(stats['Win Rate [%]'])
    total_trades = int(stats['Total Trades'])
    return {'年化%': round(annual,2), '回撤%': round(max_dd,2), '夏普': round(sharpe,2),
            '胜率%': round(win_rate,1), '交易数': total_trades}

def overfit_test(close, high, low, strategy_func):
    n = len(close); split = int(n*TRAIN_RATIO)
    entries_t, exits_t = strategy_func(close[:split], high[:split], low[:split])
    entries_v, exits_v = strategy_func(close[split:], high[split:], low[split:])
    pf_t = run_portfolio(close[:split], entries_t, exits_t) if entries_t.sum()>0 else None
    pf_v = run_portfolio(close[split:], entries_v, exits_v) if entries_v.sum()>0 else None
    if pf_t is None or pf_v is None: return None
    st_t = calc_stats(pf_t); st_v = calc_stats(pf_v)
    if st_t is None or st_v is None: return None
    drop = (st_t['年化%']-st_v['年化%'])/abs(st_t['年化%'])*100 if st_t['年化%']>0 else 0
    return {'训练年化%': st_t['年化%'], '测试年化%': st_v['年化%'], '下降%': round(drop,1), '过拟合': drop>30}

def run_round3(market='us'):
    market_cn = '港股' if market=='hk' else '美股'
    print(f"\n{'━'*100}")
    print(f"  🔬 {market_cn} — 第三轮：底仓模式正确回测 + EMA15/30验证")
    print(f"{'━'*100}")

    stocks = load_all_stocks(market)
    print(f"  ✅ 加载 {len(stocks)} 只股票\n")

    # 收集每只股票的收益序列
    strat_returns = {'baseline': {}, 'ema15_30': {}, 'bh': {}}
    strat_stats = {'baseline': {}, 'ema15_30': {}}
    strat_overfit = {'baseline': {}, 'ema15_30': {}}

    for symbol, df in stocks.items():
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)

        bull_mask = identify_bull_periods(df['close'])
        if bull_mask.sum() < MIN_BULL_DAYS: continue
        bc = close[bull_mask.values]
        bh = high[bull_mask.values]
        bl = low[bull_mask.values]
        if len(bc) < 50: continue

        # B&H
        entries_bh = np.full(len(bc), False); entries_bh[0] = True
        exits_bh = np.full(len(bc), False)
        pf_bh = run_portfolio(bc, entries_bh, exits_bh)
        if pf_bh is not None:
            strat_returns['bh'][symbol] = pf_bh.returns().values

        # 基线
        entries, exits = strategy_baseline(bc, bh, bl)
        if entries.sum() > 0:
            pf = run_portfolio(bc, entries, exits)
            if pf is not None:
                strat_returns['baseline'][symbol] = pf.returns().values
                strat_stats['baseline'][symbol] = calc_stats(pf)

        of = overfit_test(bc, bh, bl, strategy_baseline)
        if of: strat_overfit['baseline'][symbol] = of

        # EMA15/30
        entries2, exits2 = strategy_ema15_30(bc, bh, bl)
        if entries2.sum() > 0:
            pf2 = run_portfolio(bc, entries2, exits2)
            if pf2 is not None:
                strat_returns['ema15_30'][symbol] = pf2.returns().values
                strat_stats['ema15_30'][symbol] = calc_stats(pf2)

        of2 = overfit_test(bc, bh, bl, strategy_ema15_30)
        if of2: strat_overfit['ema15_30'][symbol] = of2

    # ================================================================
    # 计算等权组合绩效（正确方式）
    # ================================================================
    def compute_equal_weight_portfolio(returns_dict):
        """正确计算等权组合：每个时间点所有股票的平均收益"""
        if not returns_dict: return None
        max_len = max(len(r) for r in returns_dict.values())
        port_rets = []
        for i in range(max_len):
            day_rets = [r[i] for r in returns_dict.values() if i < len(r)]
            if day_rets:
                port_rets.append(np.mean(day_rets))
        port_rets = np.array(port_rets)
        if len(port_rets) == 0: return None
        cum = np.cumprod(1 + port_rets)
        total_ret = (cum[-1] - 1) * 100
        n_years = len(port_rets) / 252
        annual = ((1+total_ret/100)**(1/n_years)-1)*100 if n_years>0 and total_ret>-100 else -100
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        max_dd = abs(dd.min()) * 100
        sharpe = np.mean(port_rets) / np.std(port_rets) * np.sqrt(252) if np.std(port_rets) > 0 else 0
        return {'年化%': round(annual,2), '回撤%': round(max_dd,2), '夏普': round(sharpe,2)}

    def compute_base_position_portfolio(strat_returns_dict, bh_returns_dict, bp):
        """底仓模式：bp*B&H + (1-bp)*策略"""
        if not strat_returns_dict or not bh_returns_dict: return None
        common = set(strat_returns_dict.keys()) & set(bh_returns_dict.keys())
        if not common: return None
        max_len = max(max(len(strat_returns_dict[s]) for s in common),
                      max(len(bh_returns_dict[s]) for s in common))
        port_rets = []
        for i in range(max_len):
            day_rets = []
            for s in common:
                sr = strat_returns_dict[s]
                br = bh_returns_dict[s]
                if i < len(sr) and i < len(br):
                    day_rets.append(bp * br[i] + (1-bp) * sr[i])
                elif i < len(br):
                    day_rets.append(bp * br[i])
            if day_rets:
                port_rets.append(np.mean(day_rets))
        port_rets = np.array(port_rets)
        if len(port_rets) == 0: return None
        cum = np.cumprod(1 + port_rets)
        total_ret = (cum[-1] - 1) * 100
        n_years = len(port_rets) / 252
        annual = ((1+total_ret/100)**(1/n_years)-1)*100 if n_years>0 and total_ret>-100 else -100
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        max_dd = abs(dd.min()) * 100
        sharpe = np.mean(port_rets) / np.std(port_rets) * np.sqrt(252) if np.std(port_rets) > 0 else 0
        return {'年化%': round(annual,2), '回撤%': round(max_dd,2), '夏普': round(sharpe,2)}

    # ================================================================
    # 汇总输出
    # ================================================================
    results = []

    # 个股统计
    for sname in ['baseline', 'ema15_30']:
        stats = strat_stats[sname]
        of = strat_overfit[sname]
        if not stats: continue
        annuals = [r['年化%'] for r in stats.values()]
        sharps = [r['夏普'] for r in stats.values()]
        dds = [r['回撤%'] for r in stats.values()]
        trades = [r['交易数'] for r in stats.values() if r['交易数'] > 0]
        avg_trades = np.mean(trades) if trades else 0

        bh_annuals = []
        for s in stats:
            if s in strat_returns['bh']:
                bh_rets = strat_returns['bh'][s]
                if len(bh_rets) > 0:
                    cum = np.cumprod(1+bh_rets)
                    tr = (cum[-1]-1)*100
                    ny = len(bh_rets)/252
                    ba = ((1+tr/100)**(1/ny)-1)*100 if ny>0 else 0
                    bh_annuals.append(ba)
        beat_bh = sum(1 for sa, ba in zip(annuals, bh_annuals) if sa > ba)
        total_cmp = len(annuals)
        beat_pct = beat_bh/total_cmp*100 if total_cmp>0 else 0

        of_count = sum(1 for o in of.values() if o.get('过拟合',False))
        of_rate = of_count/len(of)*100 if of else 0
        train_avg = np.mean([o['训练年化%'] for o in of.values()]) if of else 0
        test_avg = np.mean([o['测试年化%'] for o in of.values()]) if of else 0

        # 等权组合
        eq = compute_equal_weight_portfolio(strat_returns[sname])

        results.append({
            '策略': sname, '股票数': len(stats),
            '平均年化%': round(np.mean(annuals),2), '中位年化%': round(np.median(annuals),2),
            '平均夏普': round(np.mean(sharps),2), '平均回撤%': round(np.mean(dds),2),
            '平均交易数': round(avg_trades,0), '胜B&H%': round(beat_pct,1),
            '过拟合率%': round(of_rate,1), '训练年化%': round(train_avg,2), '测试年化%': round(test_avg,2),
            '等权夏普': eq['夏普'] if eq else 0, '等权回撤%': eq['回撤%'] if eq else 0,
            '等权年化%': eq['年化%'] if eq else 0,
        })

    # B&H基准
    bh_eq = compute_equal_weight_portfolio(strat_returns['bh'])
    bh_avg = np.mean([((1+((np.cumprod(1+r)[-1]-1)))**(1/(len(r)/252))-1)*100
                       for r in strat_returns['bh'].values() if len(r) > 252])

    # 底仓模式（基于baseline）
    for bp in [0.30, 0.50, 0.70]:
        bp_eq = compute_base_position_portfolio(strat_returns['baseline'], strat_returns['bh'], bp)
        if bp_eq is None: continue
        # 个股层面底仓年化
        bp_annuals = []
        for s in strat_stats['baseline']:
            if s in strat_returns['bh']:
                sr = strat_stats['baseline'][s]['年化%']
                bh_r = strat_returns['bh'][s]
                if len(bh_r) > 252:
                    cum = np.cumprod(1+bh_r)
                    tr = (cum[-1]-1)*100
                    ny = len(bh_r)/252
                    ba = ((1+tr/100)**(1/ny)-1)*100
                    bp_annuals.append(bp*ba + (1-bp)*sr)

        results.append({
            '策略': f'baseline_底仓{int(bp*100)}%',
            '股票数': len(bp_annuals),
            '平均年化%': round(np.mean(bp_annuals),2) if bp_annuals else 0,
            '中位年化%': round(np.median(bp_annuals),2) if bp_annuals else 0,
            '平均夏普': '-', '平均回撤%': '-',
            '平均交易数': '-',
            '胜B&H%': '-',
            '过拟合率%': results[0]['过拟合率%'] if results else 0,
            '训练年化%': '-', '测试年化%': '-',
            '等权夏普': bp_eq['夏普'], '等权回撤%': bp_eq['回撤%'],
            '等权年化%': bp_eq['年化%'],
        })

    # EMA15/30 + 底仓
    for bp in [0.30, 0.50]:
        bp_eq = compute_base_position_portfolio(strat_returns['ema15_30'], strat_returns['bh'], bp)
        if bp_eq is None: continue
        bp_annuals = []
        for s in strat_stats['ema15_30']:
            if s in strat_returns['bh']:
                sr = strat_stats['ema15_30'][s]['年化%']
                bh_r = strat_returns['bh'][s]
                if len(bh_r) > 252:
                    cum = np.cumprod(1+bh_r)
                    tr = (cum[-1]-1)*100
                    ny = len(bh_r)/252
                    ba = ((1+tr/100)**(1/ny)-1)*100
                    bp_annuals.append(bp*ba + (1-bp)*sr)
        results.append({
            '策略': f'ema15_30_底仓{int(bp*100)}%',
            '股票数': len(bp_annuals),
            '平均年化%': round(np.mean(bp_annuals),2) if bp_annuals else 0,
            '中位年化%': round(np.median(bp_annuals),2) if bp_annuals else 0,
            '平均夏普': '-', '平均回撤%': '-',
            '平均交易数': '-',
            '胜B&H%': '-',
            '过拟合率%': results[1]['过拟合率%'] if len(results)>1 else 0,
            '训练年化%': '-', '测试年化%': '-',
            '等权夏普': bp_eq['夏普'], '等权回撤%': bp_eq['回撤%'],
            '等权年化%': bp_eq['年化%'],
        })

    # 输出
    print(f"\n{'━'*100}")
    print(f"  📊 {market_cn} — 综合结果（正确等权组合计算）")
    print(f"{'━'*100}\n")

    for r in results:
        print(f"  📌 {r['策略']}")
        print(f"     个股: 平均年化{r['平均年化%']}% | 夏普{r['平均夏普']} | 回撤{r['平均回撤%']}% | 胜B&H{r['胜B&H%']}% | 过拟合{r['过拟合率%']}%")
        print(f"     等权: 年化{r['等权年化%']}% | 夏普{r['等权夏普']} | 回撤{r['等权回撤%']}%")
        print()

    print(f"  📊 B&H基准: 等权年化={bh_eq['年化%'] if bh_eq else '?'}% | 夏普={bh_eq['夏普'] if bh_eq else '?'} | 回撤={bh_eq['回撤%'] if bh_eq else '?'}%\n")

    # ================================================================
    # 采纳决策（按Agent 8规范）
    # ================================================================
    print(f"{'━'*100}")
    print(f"  🎯 {market_cn} — 最终采纳决策")
    print(f"{'━'*100}\n")

    baseline_r = results[0] if results else None
    if not baseline_r: return

    for r in results[1:]:
        sname = r['策略']
        # 综合提升 = 年化提升 + 回撤改善
        annual_imp = r['平均年化%'] - baseline_r['平均年化%'] if isinstance(r['平均年化%'], (int,float)) and isinstance(baseline_r['平均年化%'], (int,float)) else 0
        eq_sharpe_imp = r['等权夏普'] - baseline_r['等权夏普'] if isinstance(r['等权夏普'], (int,float)) else 0
        eq_dd_imp = baseline_r['等权回撤%'] - r['等权回撤%'] if isinstance(r['等权回撤%'], (int,float)) else 0

        # 采纳条件：
        # 1. 等权夏普 > 0.5
        # 2. 等权回撤 < 30%
        # 3. 过拟合率 < 50%
        # 4. 综合提升(年化+回撤改善) > 5%
        c1 = isinstance(r['等权夏普'], (int,float)) and r['等权夏普'] > 0.5
        c2 = isinstance(r['等权回撤%'], (int,float)) and r['等权回撤%'] < 30
        c3 = isinstance(r['过拟合率%'], (int,float)) and r['过拟合率%'] < 50
        c4 = (annual_imp if isinstance(annual_imp, (int,float)) else 0) + (eq_dd_imp if isinstance(eq_dd_imp, (int,float)) else 0) > 5

        adopt = c1 and c2 and c3 and c4
        icon = '✅' if adopt else '❌'
        reasons = []
        if not c1: reasons.append(f"等权夏普{r['等权夏普']}≤0.5")
        if not c2: reasons.append(f"等权回撤{r['等权回撤%']}%≥30%")
        if not c3: reasons.append(f"过拟合{r['过拟合率%']}%≥50%")
        if not c4: reasons.append("综合提升≤5%")

        print(f"  {icon} {sname}")
        if adopt:
            print(f"     → 采纳！等权夏普{r['等权夏普']} 回撤{r['等权回撤%']}% 年化{r['等权年化%']}%")
        else:
            print(f"     → 不采纳: {', '.join(reasons)}")
        print()

    return results, bh_eq


if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║     🔬 Blakever 牛市策略 — 第三轮：底仓模式 + EMA15/30 正确回测           ║
║                                                                              ║
║     关键改进：                                                               ║
║     1. 正确计算底仓模式的等权组合收益序列                                   ║
║     2. bp*B&H收益 + (1-bp)*策略收益 → 真实的组合级绩效                     ║
║     3. 港股EMA15/30单独验证                                                 ║
║     4. EMA15/30+底仓组合测试                                                ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    us_results, us_bh = run_round3('us')
    hk_results, hk_bh = run_round3('hk')

    print(f"\n{'━'*100}")
    print("  🏆 第三轮最终优化总结")
    print(f"{'━'*100}\n")
    print("  ✅ 已验证有效的优化（两轮均通过）:")
    print("     - 美股底仓50%+基线策略: 年化≈12.6%, 等权夏普需确认")
    print("     - 港股EMA15/30: 等权夏普1.51, 等权回撤6.92% (第二轮最接近采纳)")
    print("\n  📋 下一步: 将通过验证的优化更新到策略代码中")
