#!/usr/bin/env python3
"""五福5.2 vs 七星QMT 回测对比
五福核心: (exp(slope×250)-1)×R² 评分 + 走弱期判断(4指数≥3低于MA10→切海外池)
"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
ETF_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'

# ====== 五福5.2 ETF池 (从原版提取) ======
WUFU_GLOBAL_RAW = [
    '518880','501018','161226','159985','159980',         # 商品
    '513310','159518','159509','513100','513520','513500', # 海外
    '159502','513400','513030','513290','520830','159529',
]
WUFU_CHINA_RAW = [
    '513090','513120','513180','513330','513750','159892', # 港股
    '513190','159605','513630','159323','510900','513920','513970',
    '511380','512050','510500','159915','510300','512100', # 指数
    '159949','588080','159967','588220','563300','510760',
    '588200','515880','159981','512880','513350','159326', # 行业
    '159516','159206','512480','159363','159870','512400',
    '159755','588170','159992','159995','512890','515220',
    '159566','159819','512800','512690','515050','562500',
    '512170','517520','159869','512070','159611','562800',
    '515120','512010','510880','515790','515980','512660',
    '159928','512710','560860','515030','159766','159218',
    '159852','516160','516150','159227','159583','588790',
    '159865','512980','159851','561360','561980','562590',
    '512200','159732','159667','516510','159840','159998',
    '159825','512670','159883','515210','515400','159256',
    '561330','515170','159638','516520','513360','516190',
]
WUFU_RAW = WUFU_GLOBAL_RAW + WUFU_CHINA_RAW

# ====== 走弱期判断: 沪深300/创业板/A500/小盘, ≥3低于MA10 → 走弱 ======
# 指数代码(用本地ETF代理: 510300=沪深300, 159915=创业板, 563360=A500, 512100=中证1000≈小盘)
WEAK_ETF_PROXY = {
    '510300': '沪深300',   # 000300
    '159915': '创业板',     # 399006
    '563360': '中证A500',   # 000510
    '512100': '小盘(中证1000)', # 399101代理
}
WEAK_MA = 10; WEAK_THRESHOLD = 3; MAX_WEAK_DAYS = 20

def calc_score_wufu(closes):
    """五福5.2 手动OLS加权: W=weights², (exp×250-1)×R²"""
    if len(closes) < 5: return None
    y = np.log(np.maximum(closes, 1e-10)); x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y)); W = weights ** 2; W_sum = np.sum(W)
    x_bar = np.sum(W * x) / W_sum; y_bar = np.sum(W * y) / W_sum
    dx = x - x_bar; dy = y - y_bar
    var_x = np.sum(W * dx ** 2)
    if var_x == 0: return None
    slope = np.sum(W * dx * dy) / var_x
    intercept = y_bar - slope * x_bar
    ann = math.exp(slope * 250) - 1
    y_pred = slope * x + intercept
    ss_res = np.sum(weights * (y - y_pred) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0
    return ann * r2

def calc_score_qmt(closes):
    """QMT: polyfit线性加权, (exp×250-1)×R²"""
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

def load_etf(code, start, end):
    fp = ETF_DIR / f'{code}.csv'
    if not fp.exists(): return None
    df = pd.read_csv(fp); df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    m = (df.index >= start) & (df.index <= end); df = df[m]
    return df if len(df) >= 40 else None

import akshare as ak
_idx_cache = {}
def get_index_data(code, start, end):
    if code in _idx_cache: return _idx_cache[code]
    try:
        df = ak.stock_zh_index_daily_em(symbol=code)
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= start) & (df.index <= end); df = df[m]
        _idx_cache[code] = df
        return df
    except: return None

def check_weak(tds, idx_data):
    """走弱期判断: ≥3指数低于MA10 → 返回True"""
    cnt = 0
    for proxy_code in WEAK_ETF_PROXY:
        if proxy_code in idx_data:
            cur = float(idx_data[proxy_code]['cur'])
            ma = float(idx_data[proxy_code]['ma'])
            if cur < ma: cnt += 1
    return cnt >= WEAK_THRESHOLD

def run_wufu(all_data, global_codes, trade_dates):
    """五福5.2回测: 走弱→海外池, 正常→全池"""
    CASH0 = 1_000_000; cash = CASH0; pos = {}; daily_vals = []
    is_weak = False; weak_start = None; weak_cnt = 0
    HN = 1

    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])

        # 走弱期判断 (用ETF代理指数)
        idx_state = {}
        for proxy_code, df_p in idx_proxy.items():
            m = df_p.index < tds
            if m.sum() < 11: continue
            cur = float(df_p.loc[m, 'close'].iloc[-1])
            ma = float(df_p.loc[m, 'close'].iloc[-WEAK_MA:].mean())
            idx_state[proxy_code] = {'cur': cur, 'ma': ma}
        new_weak = check_weak(tds, idx_state)

        # 走弱期状态机
        if is_weak:
            weak_cnt += 1
            if weak_cnt >= MAX_WEAK_DAYS or not new_weak:
                is_weak = False; weak_cnt = 0
            elif new_weak:
                weak_cnt = 0  # 重新触发, 重置计数
        else:
            if new_weak:
                is_weak = True; weak_cnt = 0

        # 选池
        if is_weak:
            pool_codes = [c for c in global_codes if c in all_data]
        else:
            pool_codes = list(all_data.keys())

        # 排名
        ranked = []
        for code in pool_codes:
            if code not in prices: continue
            df = all_data[code]; m = df.index < tds; hist = df[m]
            if len(hist) < 30: continue
            score = calc_score_wufu(hist['close'].values[-25:])
            if score is None or score < 0: continue
            # 三日跌幅过滤
            if len(hist) >= 4:
                d1 = hist['close'].iloc[-1] / hist['close'].iloc[-2]
                d2 = hist['close'].iloc[-2] / hist['close'].iloc[-3]
                d3 = hist['close'].iloc[-3] / hist['close'].iloc[-4]
                if min(d1,d2,d3) < 0.97: continue
            if score > 5: continue  # max_score_threshold
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]
        tc = set(r['code'] for r in targets)

        # 卖出
        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code)
                if not p: continue
                sp = p * 0.998; tv = pos[code]['shares'] * sp
                cash += tv - max(tv * 0.0001, 5)
                del pos[code]

        # 买入
        new = [r for r in targets if r['code'] not in pos]
        if new:
            per = cash * 0.95 / len(new)
            for r in new:
                bp = r['price'] * 1.002; shares = int(per / bp / 100) * 100
                if shares < 100: continue
                cash -= shares * bp + max(shares * bp * 0.0001, 5)
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
            'sh': round(sh, 2), 'fv': round(fv, 2), 'daily': daily_vals}


def run_qmt(all_data, trade_dates):
    """七星QMT精简回测: (exp×250-1)×R², 持1只, score>=0.5"""
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
            score = calc_score_qmt(hist['close'].values[-25:])
            if score < 0.5: continue
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]; tc = set(r['code'] for r in targets)
        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code)
                if not p: continue
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
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
            'sh': round(sh, 2), 'fv': round(fv, 2), 'daily': daily_vals}


if __name__ == '__main__':
    from reporting.generate_qmt_report import QMT_RAW_CODES
    periods = [('1年','2025-07-08','2026-07-08'),('3年','2023-07-08','2026-07-08'),('5年','2021-07-08','2026-07-08')]
    for pname, start, end in periods:
        print(f"\n{'='*60}")
        print(f"  {pname}: {start} ~ {end}")
        print(f"{'='*60}")

        # 五福池(仅本地有数据的)
        wf_global = [c for c in WUFU_GLOBAL_RAW if load_etf(c, start, end) is not None]
        wf_all = {}
        for c in WUFU_RAW:
            df = load_etf(c, start, end)
            if df is not None: wf_all[c] = df
        td_wf = sorted(set.union(*[set(df.index) for df in wf_all.values()]))
        td_wf = [d for d in td_wf if start <= d.strftime('%Y-%m-%d') <= end]

        # QMT池
        qmt_all = {}
        for c in QMT_RAW_CODES:
            df = load_etf(c, start, end)
            if df is not None: qmt_all[c] = df
        td_qmt = sorted(set.union(*[set(df.index) for df in qmt_all.values()]))
        td_qmt = [d for d in td_qmt if start <= d.strftime('%Y-%m-%d') <= end]

        print(f"  五福池: 全球{len(wf_global)}只+全{len(wf_all)}只有效, {len(td_wf)}交易日")
        print(f"  QMT池:  {len(qmt_all)}只有效, {len(td_qmt)}交易日")

        # 预加载走弱期代理ETF数据
        idx_proxy = {}
        for proxy_code in WEAK_ETF_PROXY:
            df_p = load_etf(proxy_code, start, end)
            if df_p is not None: idx_proxy[proxy_code] = df_p
        print(f"  走弱指数代理ETF: {len(idx_proxy)}/4可用")

        r_wf = run_wufu(wf_all, wf_global, td_wf)
        r_qmt = run_qmt(qmt_all, td_qmt)

        print(f"\n  {'策略':<20} {'累计':>10} {'CAGR':>8} {'回撤':>8} {'夏普':>7}")
        print(f"  {'-'*55}")
        print(f"  {'五福5.2(走弱切换)':<20} {r_wf['tr']:>+9.1f}% {r_wf['cagr']:>7.1f}% {r_wf['mdd']:>7.1f}% {r_wf['sh']:>6.2f}")
        print(f"  {'QMT原版(50只)':<20} {r_qmt['tr']:>+9.1f}% {r_qmt['cagr']:>7.1f}% {r_qmt['mdd']:>7.1f}% {r_qmt['sh']:>6.2f}")
        diff = r_wf['tr'] - r_qmt['tr']
        print(f"  {'差异':<20} {diff:>+9.1f}pp → {'五福胜' if diff>0 else 'QMT胜' if diff<0 else '平'}")

print("\n完成!")
