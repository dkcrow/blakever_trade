#!/usr/bin/env python3
"""QMT学习AI ETF: 测试牛熊判断 + 防御标的优化"""
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

def run_backtest(all_data, trade_dates, hs300_series, panic_mode, defense_mode):
    """panic_mode: 'qmt'=成分股80%破15日线 | 'hs300'=沪深300<MA200 | 'off'=关闭
       defense_mode: 'empty'=空仓 | 'bond'=511010国债"""
    CASH0 = 1_000_000; cash = CASH0; pos = {}; daily_vals = []; HN = 1; SCORE_THR = 0.5

    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])

        # 恐慌判断
        is_panic = False
        if panic_mode == 'qmt':
            # QMT原版: 成分股80%跌破15日线
            below = 0; total = 0
            for code, df in all_data.items():
                m = df.index <= tds; hist = df[m]
                if len(hist) < 15: continue
                cur = float(hist['close'].iloc[-1])
                ma15 = float(hist['close'].iloc[-15:].mean())
                total += 1
                if cur < ma15: below += 1
            is_panic = (below / max(total, 1)) > 0.8
        elif panic_mode == 'hs300':
            # AI ETF方式: 沪深300 < MA200
            if hs300_series is not None:
                m_hs = hs300_series.index <= tds
                if m_hs.sum() >= 200:
                    cur_hs = float(hs300_series.loc[m_hs].iloc[-1])
                    ma200 = float(hs300_series.loc[m_hs].iloc[-200:].mean())
                    is_panic = cur_hs < ma200

        if is_panic:
            if defense_mode == 'empty':
                # QMT原版: 空仓
                for code in list(pos.keys()):
                    p = prices.get(code, pos[code]['cp'])
                    sp = p * 0.998; tv = pos[code]['shares'] * sp
                    cash += tv - max(tv * 0.0002, 5)
                    del pos[code]
            elif defense_mode == 'bond':
                # AI ETF方式: 换511010国债
                bond_code = '511010'
                # 卖出非国债持仓
                for code in list(pos.keys()):
                    if code == bond_code: continue
                    p = prices.get(code, pos[code]['cp'])
                    sp = p * 0.998; tv = pos[code]['shares'] * sp
                    cash += tv - max(tv * 0.0002, 5)
                    del pos[code]
                # 买入国债(全仓)
                if bond_code in prices and bond_code not in pos:
                    bp = prices[bond_code] * 1.002
                    shares = int(cash * 0.95 / bp / 100) * 100
                    if shares >= 100:
                        cost = shares * bp + max(shares * bp * 0.0002, 5)
                        cash -= cost
                        pos[bond_code] = {'shares': shares, 'cp': bp}
            tv = cash + sum(po['shares'] * prices.get(c, po['cp']) for c, po in pos.items())
            daily_vals.append((ds, tv)); continue

        # 正常期: 持有国债→卖出回现金
        if defense_mode == 'bond' and '511010' in pos:
            p = prices.get('511010', pos['511010']['cp'])
            sp = p * 0.998; tv = pos['511010']['shares'] * sp
            cash += tv - max(tv * 0.0002, 5); del pos['511010']

        # 排名
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

        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code, pos[code]['cp'])
                sp = p * 0.998; tv = pos[code]['shares'] * sp
                cash += tv - max(tv * 0.0002, 5)
                del pos[code]
        new = [r for r in targets if r['code'] not in pos]
        if new:
            per = cash * 0.95 / len(new)
            for r in new:
                bp = r['price'] * 1.002; shares = int(per / bp / 100) * 100
                if shares < 100: continue
                cash -= shares * bp + max(shares * bp * 0.0002, 5)
                pos[r['code']] = {'shares': shares, 'cp': bp}
        tv = cash + sum(po['shares'] * prices.get(c, po['cp']) for c, po in pos.items())
        daily_vals.append((ds, tv))

    fv = daily_vals[-1][1] if daily_vals else CASH0
    tr = (fv / CASH0 - 1) * 100; days = len(daily_vals)
    af = 252 / max(days, 1); cagr = ((fv / CASH0) ** af - 1) * 100
    vals = np.array([v for _, v in daily_vals])
    peak = np.maximum.accumulate(vals)
    mdd = float(np.min((vals - peak) / peak * 100)) if len(vals) > 0 else 0
    rets = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0])
    sh = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1), 'sh': round(sh, 2)}


if __name__ == '__main__':
    periods = [('1年','2025-07-09','2026-07-09'),('3年','2023-07-09','2026-07-09'),('5年','2021-07-09','2026-07-09')]

    configs = [
        ('qmt',  'empty', 'A. QMT原版(成分股80%破15日→空仓)'),
        ('qmt',  'bond',  'B. QMT恐慌+511010国债(换防御标的)'),
        ('hs300','empty', 'C. 沪深300<MA200→空仓(换牛熊判断)'),
        ('hs300','bond',  'D. 沪深300<MA200→511010国债(二者都换)'),
        ('off',  'empty', 'E. 关闭恐慌过滤(纯动量基线)'),
    ]

    for pname, start, end in periods:
        print(f"\n{'='*70}")
        print(f"  {pname}: {start} ~ {end}")
        print(f"{'='*70}")

        qmt_data = {}
        for c in QMT_RAW_CODES:
            df = load_etf(c, start, end)
            if df is not None: qmt_data[c] = df
        td = sorted(set.union(*[set(df.index) for df in qmt_data.values()]))
        td = [d for d in td if start <= d.strftime('%Y-%m-%d') <= end]
        hs300 = load_etf('510300', start, end)
        print(f"  QMT池: {len(qmt_data)}只, {len(td)}交易日 | 沪深300: {'有' if hs300 is not None else '无'}")

        results = {}
        best_tr = -999; best_label = ''
        for panic_m, defense_m, label in configs:
            r = run_backtest(qmt_data, td, hs300['close'] if hs300 is not None else None, panic_m, defense_m)
            results[label] = r
            if r['tr'] > best_tr: best_tr = r['tr']; best_label = label

        # 打印对比表
        print(f"\n  {'配置':<42} {'累计':>10} {'CAGR':>8} {'回撤':>8} {'夏普':>7}")
        print(f"  {'-'*77}")
        for _, _, label in configs:
            r = results[label]
            star = ' ★' if r is results[best_label] else ''
            print(f"  {label:<42} {r['tr']:>+9.1f}% {r['cagr']:>7.1f}% {r['mdd']:>7.1f}% {r['sh']:>6.2f}{star}")
        print(f"  {'最优: '+best_label}")

print("\n完成!")
