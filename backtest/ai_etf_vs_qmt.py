#!/usr/bin/env python3
"""AI ETF策略 (激进牛熊版 v3.0.2) vs 七星QMT 回测
核心: (exp×250-1)×R² + 牛熊判断(沪深300 vs MA200) → 熊市减半仓 + 换511010国债
ETF池: 52只 | 持1只 | 多级过滤 | 盈利保护
"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
ETF_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'

# ====== AI ETF池 (52只) ======
AI_ETF_POOL = [
    '518880','159980','159985','501018','161226',       # 商品
    '159981','513100','159509','513290','513500',        # 商品+美股
    '159529','513400','513520','513030','513080',        # 美股+海外
    '513310','513730','159792','513130','513050',        # 海外+港股
    '159920','513690','510300','510500','510050',        # 港股+A宽基
    '510210','159915','588080','512100','563360',        # A宽基
    '563300','512890','159967','512040','159201',        # A宽基+风格
    '511380','511010','511220','159949','512880',        # 债券+爆发
    '512660','515050','512760','159995','515030',        # 爆发标的
    '516510','515790','512480','513300','159941',        # 爆发标的
    '513200','159892',                                    # 爆发标的
]

def calc_score(closes):
    """(exp(slope×250)-1)×R², 线性加权"""
    if len(closes) < 5: return None
    x = np.arange(len(closes)); y = np.log(np.maximum(closes, 1e-10))
    mask = ~np.isnan(y) & ~np.isinf(y); x_m, y_m = x[mask], y[mask]
    if len(x_m) < 5: return None
    w = np.linspace(1, 2, len(x_m))
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = math.exp(slope * 250) - 1
    fitted = slope * x_m + intercept; res = y_m - fitted
    ssr = np.sum(w * res**2); sst = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann * r2

def load_etf(code, start, end):
    fp = ETF_DIR / f'{code}.csv'
    if not fp.exists(): return None
    df = pd.read_csv(fp); df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    m = (df.index >= start) & (df.index <= end)
    df = df[m]
    return df if len(df) >= 40 else None

def run_ai_etf(all_data, trade_dates, hs300_series):
    """AI ETF激进版: 牛熊判断+动态仓位+多级过滤"""
    CASH0 = 1_000_000; cash = CASH0; pos = {}; daily_vals = []
    HN = 1; MA_BEAR = 200; BEAR_RATIO = 0.5; DEF_ETF = '511010'

    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])

        # 牛熊判断: 沪深300 vs MA200
        is_bear = False
        if hs300_series is not None:
            m_hs = hs300_series.index <= tds
            if m_hs.sum() >= MA_BEAR:
                cur_hs = float(hs300_series.loc[m_hs].iloc[-1])
                ma_hs = float(hs300_series.loc[m_hs].iloc[-MA_BEAR:].mean())
                is_bear = cur_hs < ma_hs

        # 仓位比率
        pos_ratio = BEAR_RATIO if is_bear else 1.0

        # 排名
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 30: continue
            close_arr = hist['close'].values

            # 三日跌幅过滤
            if len(close_arr) >= 4:
                d1 = close_arr[-1] / close_arr[-2]
                d2 = close_arr[-2] / close_arr[-3]
                d3 = close_arr[-3] / close_arr[-4]
                if min(d1,d2,d3) < 0.97: continue

            # 短期动量过滤: 10日年化<0 → 跳过
            if len(close_arr) >= 11:
                short_ret = close_arr[-1] / close_arr[-11] - 1
                short_ann = (1 + short_ret) ** 25 - 1
                if short_ann < 0: continue

            score = calc_score(close_arr[-25:])
            if score is None or score < 0 or score > 100: continue
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]
        tc = set(r['code'] for r in targets)

        # 防御模式: 无候选→换防御ETF
        if not targets:
            if is_bear:
                def_code = '511010'  # 国债
            else:
                def_code = '511880'  # 银华日利(本地无, 用511010替代)
                def_code = '511010'
            if def_code in prices:
                targets = [{'code': def_code, 'score': 999, 'price': prices[def_code]}]
                tc = {def_code}
            else:
                # 纯空仓
                tv = cash + sum(po['shares'] * prices.get(c, po['cp']) for c, po in pos.items())
                daily_vals.append((ds, tv)); continue

        # 卖出不在目标中的
        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code, pos[code]['cp'])
                sp = p * 0.998; tv_pos = pos[code]['shares'] * sp
                cash += tv_pos - max(tv_pos * 0.0002, 5)
                del pos[code]

        # 买入
        new = [r for r in targets if r['code'] not in pos]
        if new:
            allocated_cash = cash * 0.95 * pos_ratio  # 牛熊动态仓位
            per = allocated_cash / len(new)
            for r in new:
                bp = r['price'] * 1.002; shares = int(per / bp / 100) * 100
                if shares < 100: continue
                cost = shares * bp + max(shares * bp * 0.0002, 5)
                if cost > cash: continue
                cash -= cost
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
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
            'sh': round(sh, 2), 'fv': round(fv, 2)}


def run_qmt(all_data, trade_dates):
    """QMT原版: (exp×250-1)×R², 持1只, score>=0.5"""
    CASH0 = 1_000_000; cash = CASH0; pos = {}; daily_vals = []; HN = 1
    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score(hist['close'].values[-25:])
            if score < 0.5: continue
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]; tc = set(r['code'] for r in targets)
        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code)
                if not p: continue
                sp = p * 0.998; tv_pos = pos[code]['shares'] * sp
                cash += tv_pos - max(tv_pos * 0.0002, 5)
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
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
            'sh': round(sh, 2), 'fv': round(fv, 2)}


if __name__ == '__main__':
    from reporting.generate_qmt_report import QMT_RAW_CODES
    periods = [('1年','2025-07-09','2026-07-09'),('3年','2023-07-09','2026-07-09'),('5年','2021-07-09','2026-07-09')]
    for pname, start, end in periods:
        print(f"\n{'='*60}")
        print(f"  {pname}: {start} ~ {end}")
        print(f"{'='*60}")

        # AI ETF池
        ai_data = {}
        for c in AI_ETF_POOL:
            df = load_etf(c, start, end)
            if df is not None: ai_data[c] = df
        td_ai = sorted(set.union(*[set(df.index) for df in ai_data.values()]))
        td_ai = [d for d in td_ai if start <= d.strftime('%Y-%m-%d') <= end]

        # 沪深300 (510300)用于牛熊判断
        hs300 = load_etf('510300', start, end)

        # QMT池
        qmt_data = {}
        for c in QMT_RAW_CODES:
            df = load_etf(c, start, end)
            if df is not None: qmt_data[c] = df
        td_qmt = sorted(set.union(*[set(df.index) for df in qmt_data.values()]))
        td_qmt = [d for d in td_qmt if start <= d.strftime('%Y-%m-%d') <= end]

        print(f"  AI ETF池: {len(ai_data)}/{len(AI_ETF_POOL)}只有效, {len(td_ai)}交易日")
        print(f"  沪深300: {'可用' if hs300 is not None else '缺失'}")
        print(f"  QMT池:   {len(qmt_data)}只有效, {len(td_qmt)}交易日")

        r_ai = run_ai_etf(ai_data, td_ai, hs300['close'] if hs300 is not None else None)
        r_qmt = run_qmt(qmt_data, td_qmt)

        print(f"\n  {'策略':<22} {'累计':>10} {'CAGR':>8} {'回撤':>8} {'夏普':>7}")
        print(f"  {'-'*57}")
        print(f"  {'AI ETF(牛熊版)':<22} {r_ai['tr']:>+9.1f}% {r_ai['cagr']:>7.1f}% {r_ai['mdd']:>7.1f}% {r_ai['sh']:>6.2f}")
        print(f"  {'QMT原版(50只)':<22} {r_qmt['tr']:>+9.1f}% {r_qmt['cagr']:>7.1f}% {r_qmt['mdd']:>7.1f}% {r_qmt['sh']:>6.2f}")
        diff = r_ai['tr'] - r_qmt['tr']
        print(f"  {'差异':<22} {diff:>+9.1f}pp → {'AI ETF胜' if diff>0 else 'QMT胜' if diff<0 else '平'}")

print("\n完成!")
