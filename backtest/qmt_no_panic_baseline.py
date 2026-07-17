#!/usr/bin/env python3
"""QMT纯动量(关闭恐慌过滤) 1/3/5年回测 — 严谨基线"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
ETF_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'
from reporting.generate_qmt_report import QMT_RAW_CODES

def load_etf(code, start, end):
    fp = ETF_DIR / f'{code}.csv'
    if not fp.exists(): return None
    df = pd.read_csv(fp); df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    m = (df.index >= start) & (df.index <= end); df = df[m]
    return df if len(df) >= 40 else None

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(np.maximum(closes, 1e-10))
    mask = ~np.isnan(y) & ~np.isinf(y); x_m, y_m = x[mask], y[mask]
    if len(x_m) < 5: return -999
    w = np.linspace(1, 2, len(x_m))
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = math.exp(slope * 250)
    fitted = slope * x_m + intercept; res = y_m - fitted
    ssr = np.sum(w * res**2); sst = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return (ann - 1) * r2

def run_qmt_no_panic(all_data, trade_dates):
    """QMT: 纯动量, score>=0.5, 持1只, 佣金万二, 滑点0.2%, 无恐慌过滤"""
    CASH0 = 1_000_000; cash = CASH0; pos = {}; daily_vals = []
    trades = []; HN = 1; SCORE_THR = 0.5

    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])

        # 排名 (无恐慌过滤)
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score(hist['close'].values[-25:])
            if score < SCORE_THR: continue
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]; tc = set(r['code'] for r in targets)

        # 卖出
        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code, pos[code]['cp'])
                sp = p * 0.998; tv_pos = pos[code]['shares'] * sp
                comm = max(tv_pos * 0.0002, 5)
                cash += tv_pos - comm
                pnl = (sp / pos[code]['cp'] - 1) * 100
                trades.append({'date': ds, 'code': code, 'action': 'SELL', 'pnl_pct': round(pnl, 2)})
                del pos[code]

        # 买入
        new = [r for r in targets if r['code'] not in pos]
        if new:
            per = cash * 0.95 / len(new)
            for r in new:
                bp = r['price'] * 1.002; shares = int(per / bp / 100) * 100
                if shares < 100: continue
                cost = shares * bp; comm = max(cost * 0.0002, 5)
                if cost + comm > cash: continue
                cash -= cost + comm
                pos[r['code']] = {'shares': shares, 'cp': bp}
                trades.append({'date': ds, 'code': r['code'], 'action': 'BUY', 'pnl_pct': 0})

        tv = cash + sum(po['shares'] * prices.get(c, po['cp']) for c, po in pos.items())
        daily_vals.append((ds, tv))

    # 统计
    fv = daily_vals[-1][1] if daily_vals else CASH0
    tr = (fv / CASH0 - 1) * 100; days = len(daily_vals)
    af = 252 / max(days, 1); cagr = ((fv / CASH0) ** af - 1) * 100
    vals = np.array([v for _, v in daily_vals])
    peak = np.maximum.accumulate(vals)
    mdd = float(np.min((vals - peak) / peak * 100)) if len(vals) > 0 else 0
    rets = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0])
    sh = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    win_sells = [t for t in trades if t['action'] == 'SELL']
    wr = sum(1 for t in win_sells if t['pnl_pct'] > 0) / max(len(win_sells), 1) * 100

    # 月度统计
    monthly = {}
    for ds, tv in daily_vals:
        m_key = ds[:7]
        if m_key not in monthly: monthly[m_key] = []
        monthly[m_key].append(tv)
    month_vals = {k: v[-1] for k, v in sorted(monthly.items())}

    return {
        'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
        'sh': round(sh, 2), 'fv': round(fv, 2), 'trades': len(trades),
        'wr': round(wr, 1), 'monthly': month_vals, 'daily': daily_vals,
    }


if __name__ == '__main__':
    periods = [
        ('1年', '2025-07-09', '2026-07-09'),
        ('3年', '2023-07-09', '2026-07-09'),
        ('5年', '2021-07-09', '2026-07-09'),
    ]

    for pname, start, end in periods:
        print(f"\n{'='*65}")
        print(f"  {pname}: {start} ~ {end}")
        print(f"{'='*65}")

        qmt_data = {}
        for c in QMT_RAW_CODES:
            df = load_etf(c, start, end)
            if df is not None: qmt_data[c] = df
        td = sorted(set.union(*[set(df.index) for df in qmt_data.values()]))
        td = [d for d in td if start <= d.strftime('%Y-%m-%d') <= end]
        print(f"  池: {len(qmt_data)}/{len(QMT_RAW_CODES)}只, {len(td)}交易日")

        r = run_qmt_no_panic(qmt_data, td)

        print(f"\n  📊 绩效:")
        print(f"    累计: {r['tr']:+.1f}%     年化: {r['cagr']:+.1f}%     终值: ¥{r['fv']:,.0f}")
        print(f"    回撤: {r['mdd']:.1f}%     夏普: {r['sh']:.2f}     交易: {r['trades']}笔     胜率: {r['wr']:.0f}%")

        # 年度收益
        print(f"\n  📅 年度收益:")
        yearly = {}
        for ds, tv in r['daily']:
            yr = ds[:4]
            if yr not in yearly: yearly[yr] = {}
            yearly[yr][ds] = tv
        prev_end = 1_000_000
        for yr in sorted(yearly.keys()):
            yr_end = list(yearly[yr].values())[-1]
            yr_ret = (yr_end / prev_end - 1) * 100
            print(f"    {yr}: {yr_ret:+.1f}%  (¥{yr_end:,.0f})")
            prev_end = yr_end

        # 月度最大回撤和最���单月收益
        vals = list(r['monthly'].values())
        if len(vals) > 1:
            mo_rets = [(vals[i] - vals[i-1]) / vals[i-1] * 100 for i in range(1, len(vals))]
            keys = list(r['monthly'].keys())
            print(f"\n  📈 月度极值:")
            best_idx = np.argmax(mo_rets); worst_idx = np.argmin(mo_rets)
            print(f"    最佳: {keys[best_idx+1]} {mo_rets[best_idx]:+.1f}%")
            print(f"    最差: {keys[worst_idx+1]} {mo_rets[worst_idx]:+.1f}%")

print("\n完成!")
