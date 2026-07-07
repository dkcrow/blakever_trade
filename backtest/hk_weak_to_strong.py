#!/usr/bin/env python3
"""七星弱转强港股版 — 动量拐点策略
规则: 只买入从不符合评分(score<0.5)变成符合(score>=0.5)的股票
      持有直到再次score<0.5卖出
      资金100000, 5份等权, 最多5只, FIFO替换
      不修改任何已有逻辑, 独立运行
"""
import sys, os, math, warnings
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
HK_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'hk'

# ====== 股池 (与七星港股版完全一致) ======
HK_POOL = [
    '00700','09988','01810','03690','09999',
    '02513','00100',
    '02162','02616','09969',
    '02418','01357',
    '00981','01347','00522',
    '01093','01177',
    '02338','02038','01378',
    '00388','02388','02318','00939','02628','03988',
    '09888',
    '02899','03993',
    '02618',
    '01929',
    '01113','06181',
    '00669',
    '09660',
]
HK_NAME = {
    '00700':'腾讯','09988':'阿里','01810':'小米','03690':'美团','09999':'网易',
    '02513':'智谱','00100':'MiniMax',
    '02162':'康诺亚','02616':'基石药业','09969':'诺诚健华',
    '02418':'德银天下','01357':'美图',
    '00981':'中芯','01347':'华虹','00522':'ASMPT',
    '01093':'石药','01177':'生物制药',
    '02338':'潍柴','02038':'富智康','01378':'宏桥',
    '00388':'港交所','02388':'中银香港','02318':'平安','00939':'建行','02628':'人寿','03988':'中国银行',
    '09888':'百度',
    '02899':'紫金','03993':'洛阳钼业',
    '02618':'京东物流',
    '01929':'周大福',
    '01113':'长实','06181':'老铺黄金',
    '00669':'创科',
    '09660':'地平线',
}

HK_COMM = 0.001
HK_STAMP = 0.0013
HK_FEE = 0.0000565
SLIP = 0.001


def calc_score(closes):
    """(exp(slope×250)-1)×R², 线性加权linspace(1,2)"""
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(np.maximum(closes, 1e-10))
    mask = ~np.isnan(y) & ~np.isinf(y)
    x_m, y_m = x[mask], y[mask]
    if len(x_m) < 5: return -999
    w = np.linspace(1, 2, len(x_m))
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = math.exp(slope * 250)
    fitted = slope * x_m + intercept
    res = y_m - fitted
    ss_res = np.sum(w * res**2); ss_tot = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return (ann - 1) * r2


def load_all_data(start, end):
    """加载全池日线数据"""
    all_data = {}
    for code in HK_POOL:
        fp = HK_DIR / f'hk{code}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        df.columns = [c.lower().strip() for c in df.columns]
        dc = next((c for c in df.columns if c.lower() == 'date'), df.columns[0])
        df = df.rename(columns={dc: 'date'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        mask = (df.index >= start) & (df.index <= end)
        df = df[mask]
        if len(df) >= 35: all_data[code] = df
    return all_data


def run_weak_to_strong(all_data, trade_dates):
    """弱转强策略回测"""
    CASH0 = 100000
    MAX_HOLD = 5
    SCORE_THR = 0.5

    cash = CASH0
    positions = {}  # {code: {'shares': int, 'cp': float, 'entry_date': str}}
    trades = []
    daily_vals = []
    prev_scores = {}  # 上一交易日每只的得分

    for i, date in enumerate(trade_dates):
        ds = date.strftime('%Y-%m-%d')
        tds = pd.Timestamp(date)

        # 获取当日价格
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < 5: continue

        # 计算当日得分(用<date的数据, 防未来函数)
        curr_scores = {}
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score(hist['close'].values[-25:])
            curr_scores[code] = score

        # 弱转强信号: prev < 0.5 and curr >= 0.5
        rising_stars = []
        for code, score in curr_scores.items():
            if score < SCORE_THR: continue
            prev = prev_scores.get(code, -999)
            if prev < SCORE_THR:  # 之前不符合
                rising_stars.append((code, score, prices[code]))

        # 排序(得分高的优先)
        rising_stars.sort(key=lambda x: -x[1])

        # 卖出: 已持有的如果score<0.5或不在curr_scores中
        for code in list(positions.keys()):
            sc = curr_scores.get(code, -999)
            if sc < SCORE_THR:
                p = prices.get(code)
                if not p: continue
                pos = positions[code]
                sp = p * (1 - SLIP)
                tv = pos['shares'] * sp
                comm = max(tv * HK_COMM, 5)
                stamp = tv * HK_STAMP
                tfee = tv * HK_FEE
                cash += tv - comm - stamp - tfee
                pnl = (sp - pos['cp']) / pos['cp'] * 100
                trades.append({
                    'date': ds, 'code': code, 'action': 'SELL', 'price': round(sp, 4),
                    'shares': pos['shares'], 'pnl_pct': round(pnl, 2),
                    'entry_date': pos['entry_date'],
                    'reason': f'得分{sc:.4f}<{SCORE_THR}'
                })
                del positions[code]

        # 买入: 弱转强信号, FIFO替换
        if rising_stars:
            # 当前持仓中的弱转强不重复买(可能已有)
            new_stars = [(c, s, pr) for c, s, pr in rising_stars if c not in positions]

            if new_stars:
                # FIFO: 如果信号超过仓位上限, 逐步替换最早持仓
                while len(positions) + len(new_stars) > MAX_HOLD:
                    if len(positions) > 0:
                        # 卖出最早买入的持仓腾出空间
                        oldest_code = min(positions.keys(), key=lambda c: positions[c]['entry_date'])
                        p = prices.get(oldest_code)
                        if p:
                            pos = positions[oldest_code]
                            sp = p * (1 - SLIP)
                            tv = pos['shares'] * sp
                            comm = max(tv * HK_COMM, 5)
                            stamp = tv * HK_STAMP
                            tfee = tv * HK_FEE
                            cash += tv - comm - stamp - tfee
                            pnl = (sp - pos['cp']) / pos['cp'] * 100
                            trades.append({
                                'date': ds, 'code': oldest_code, 'action': 'SELL',
                                'price': round(sp, 4), 'shares': pos['shares'],
                                'pnl_pct': round(pnl, 2),
                                'entry_date': pos['entry_date'],
                                'reason': 'FIFO替换为更新信号'
                            })
                        del positions[oldest_code]
                    else:
                        # 无持仓可踢, 截断信号列表
                        new_stars = new_stars[:MAX_HOLD - len(positions)]
                        break

                # 等权买入
                n_buy = min(len(new_stars), MAX_HOLD - len(positions))
                new_stars = new_stars[:n_buy]
                if n_buy > 0:
                    total_positions = len(positions) + n_buy
                    per_stock = cash * 0.95 / n_buy  # 可用现金均分给新买入
                    for code, score, price in new_stars:
                        bp = price * (1 + SLIP)
                        shares = int(per_stock / bp / 100) * 100
                        if shares < 100: continue
                        cost = shares * bp
                        comm = max(cost * HK_COMM, 5)
                        tfee = cost * HK_FEE
                        cash -= cost + comm + tfee
                        positions[code] = {'shares': shares, 'cp': bp, 'entry_date': ds}
                        trades.append({
                            'date': ds, 'code': code, 'action': 'BUY',
                            'price': round(bp, 4), 'shares': shares,
                            'pnl_pct': 0, 'entry_date': ds,
                            'reason': f'弱转强 得分{score:.4f}>={SCORE_THR}'
                        })

        # 记录当日净值
        tv = cash
        for code, pos in positions.items():
            p = prices.get(code, pos['cp'])
            tv += pos['shares'] * p
        daily_vals.append((ds, tv))

        # 保存当日得分供下日比较
        prev_scores = curr_scores.copy()

    # 统计
    final_tv = daily_vals[-1][1] if daily_vals else CASH0
    total_return = (final_tv / CASH0 - 1) * 100
    days = len(daily_vals)

    # 年化
    if days > 0:
        af = 252 / max(days, 1)
        cagr = ((final_tv / CASH0) ** af - 1) * 100
    else:
        cagr = 0

    # 回撤
    vals = np.array([v for _, v in daily_vals])
    peak = np.maximum.accumulate(vals)
    dd = (vals - peak) / peak * 100
    max_dd = float(np.min(dd)) if len(dd) > 0 else 0

    # 夏普
    if len(vals) > 1:
        rets = np.diff(vals) / vals[:-1]
        sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    else:
        sharpe = 0

    win_trades = [t for t in trades if t['action'] == 'SELL']
    win_rate = sum(1 for t in win_trades if t['pnl_pct'] > 0) / max(len(win_trades), 1) * 100

    return {
        'total_return': round(total_return, 1),
        'cagr': round(cagr, 1),
        'max_dd': round(max_dd, 1),
        'sharpe': round(sharpe, 2),
        'trades': len(trades),
        'win_rate': round(win_rate, 1),
        'final_tv': round(final_tv, 2),
        'daily_vals': daily_vals,
        'trade_log': trades,
        'positions': positions,
    }


def run_original_baseline(all_data, trade_dates):
    """七星港股版原版策略(长期持有, 5只等权, score>=0.5)"""
    CASH0 = 100000
    MAX_HOLD = 5
    SCORE_THR = 0.5

    cash = CASH0
    positions = {}
    trades = []
    daily_vals = []

    for i, date in enumerate(trade_dates):
        ds = date.strftime('%Y-%m-%d')
        tds = pd.Timestamp(date)

        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < 5: continue

        # 排名
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score(hist['close'].values[-25:])
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = [r for r in ranked if r['score'] >= SCORE_THR][:MAX_HOLD]
        target_codes = set(r['code'] for r in targets)

        # 卖出不在目标中的
        for code in list(positions.keys()):
            if code not in target_codes:
                p = prices.get(code)
                if not p: continue
                pos = positions[code]
                sp = p * (1 - SLIP)
                tv = pos['shares'] * sp
                comm = max(tv * HK_COMM, 5)
                stamp = tv * HK_STAMP
                tfee = tv * HK_FEE
                cash += tv - comm - stamp - tfee
                pnl = (sp - pos['cp']) / pos['cp'] * 100
                trades.append({
                    'date': ds, 'code': code, 'action': 'SELL',
                    'price': round(sp, 4), 'shares': pos['shares'],
                    'pnl_pct': round(pnl, 2), 'entry_date': pos['entry_date']
                })
                del positions[code]

        # 买入新目标
        new_targets = [r for r in targets if r['code'] not in positions]
        if new_targets:
            n = len(new_targets) + len(positions)
            total_target = cash * 0.95 / max(n, 1)
            per_stock = cash * 0.95 / len(new_targets) if len(new_targets) <= MAX_HOLD - len(positions) else total_target
            for r in new_targets[:MAX_HOLD - len(positions)]:
                bp = r['price'] * (1 + SLIP)
                per = cash * 0.95 / (len(new_targets) + len(positions))
                shares = int(per / bp / 100) * 100
                if shares < 100: continue
                cost = shares * bp
                comm = max(cost * HK_COMM, 5)
                tfee = cost * HK_FEE
                cash -= cost + comm + tfee
                positions[r['code']] = {'shares': shares, 'cp': bp, 'entry_date': ds}
                trades.append({
                    'date': ds, 'code': r['code'], 'action': 'BUY',
                    'price': round(bp, 4), 'shares': shares,
                    'pnl_pct': 0, 'entry_date': ds
                })

        tv = cash + sum(pos['shares'] * prices.get(c, pos['cp']) for c, pos in positions.items())
        daily_vals.append((ds, tv))

    final_tv = daily_vals[-1][1] if daily_vals else CASH0
    total_return = (final_tv / CASH0 - 1) * 100
    days = len(daily_vals)
    af = 252 / max(days, 1)
    cagr = ((final_tv / CASH0) ** af - 1) * 100
    vals = np.array([v for _, v in daily_vals])
    peak = np.maximum.accumulate(vals)
    max_dd = float(np.min((vals - peak) / peak * 100)) if len(vals) > 0 else 0
    rets = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    win_trades = [t for t in trades if t['action'] == 'SELL']
    win_rate = sum(1 for t in win_trades if t['pnl_pct'] > 0) / max(len(win_trades), 1) * 100

    return {
        'total_return': round(total_return, 1), 'cagr': round(cagr, 1),
        'max_dd': round(max_dd, 1), 'sharpe': round(sharpe, 2),
        'trades': len(trades), 'win_rate': round(win_rate, 1),
        'final_tv': round(final_tv, 2), 'daily_vals': daily_vals, 'trade_log': trades,
    }


# ====== 执行 ======
if __name__ == '__main__':
    START, END = '2023-07-03', '2026-07-03'

    print("加载数据...")
    all_data = load_all_data(START, END)
    trade_dates = sorted(set.union(*[set(df.index) for df in all_data.values()]))
    trade_dates = [d for d in trade_dates if START <= d.strftime('%Y-%m-%d') <= END]
    print(f"有效: {len(all_data)}/{len(HK_POOL)}只, {len(trade_dates)}交易日")
    print(f"日期范围: {trade_dates[0].strftime('%Y-%m-%d')} ~ {trade_dates[-1].strftime('%Y-%m-%d')}")

    print(f"\n{'='*60}")
    print("  策略A: 七星港股版(原版)")
    print(f"{'='*60}")
    r_orig = run_original_baseline(all_data, trade_dates)
    print(f"  终值: ¥{r_orig['final_tv']:,.0f}  |  累计: {r_orig['total_return']:+.1f}%  |  年化: {r_orig['cagr']:+.1f}%")
    print(f"  回撤: {r_orig['max_dd']:.1f}%  |  夏普: {r_orig['sharpe']:.2f}  |  交易: {r_orig['trades']}笔  |  胜率: {r_orig['win_rate']:.0f}%")

    print(f"\n{'='*60}")
    print("  策略B: 七星弱转强版(仅买拐点)")
    print(f"{'='*60}")
    r_new = run_weak_to_strong(all_data, trade_dates)
    print(f"  终值: ¥{r_new['final_tv']:,.0f}  |  累计: {r_new['total_return']:+.1f}%  |  年化: {r_new['cagr']:+.1f}%")
    print(f"  回撤: {r_new['max_dd']:.1f}%  |  夏普: {r_new['sharpe']:.2f}  |  交易: {r_new['trades']}笔  |  胜率: {r_new['win_rate']:.0f}%")

    # 交易明细
    print(f"\n{'='*60}")
    print("  弱转强信号触发统计(按股)")
    print(f"{'='*60}")
    sig_counts = {}
    for t in r_new['trade_log']:
        if t['action'] == 'BUY':
            code = t['code']
            if code not in sig_counts: sig_counts[code] = {'signals': 0, 'total_pnl': 0, 'sell_count': 0, 'win_count': 0}
            sig_counts[code]['signals'] += 1
        elif t['action'] == 'SELL':
            code = t['code']
            if code not in sig_counts: sig_counts[code] = {'signals': 0, 'total_pnl': 0, 'sell_count': 0, 'win_count': 0}
            sig_counts[code]['total_pnl'] += t['pnl_pct']
            sig_counts[code]['sell_count'] += 1
            if t['pnl_pct'] > 0: sig_counts[code]['win_count'] += 1

    for code in sorted(sig_counts.keys(), key=lambda c: -sig_counts[c]['signals']):
        s = sig_counts[code]
        avg_pnl = s['total_pnl'] / max(s['sell_count'], 1)
        name = HK_NAME.get(code, code)
        print(f"  {code} {name:<8}: {s['signals']:>3}次信号  {s['sell_count']:>3}次卖出  胜{s['win_count']}/{s['sell_count']}  均利{avg_pnl:+.1f}%")

    # 月度对比
    print(f"\n{'='*60}")
    print("  月度净值对比")
    print(f"{'='*60}")
    print(f"  {'月份':<10} {'原版':>10} {'弱转强':>10} {'差异':>10}")
    orig_dict = {d: v for d, v in r_orig['daily_vals']}
    new_dict = {d: v for d, v in r_new['daily_vals']}

    # 按季度采样
    for year in [2023, 2024, 2025, 2026]:
        for month in [1, 4, 7, 10]:
            ds = f"{year}-{month:02d}-01"
            if ds in orig_dict:
                ov = orig_dict[ds]
                nv = new_dict.get(ds, new_dict.get(min(new_dict.keys(), key=lambda x: abs((pd.Timestamp(x) - pd.Timestamp(ds)).days)), CASH0))
                diff = ((nv - nv) - (ov - CASH0))
                print(f"  {ds:<10} ¥{ov:>9,.0f} ¥{nv:>9,.0f} {(nv-ov):>+9,.0f}")

    print(f"\n完成!")
