"""
七星港股版 恐慌防御策略测试
方案: 恐慌期切换至防御模式 vs 空仓 vs 关闭
1/3/5年对比
"""
import math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

HK_DIR = Path('data/storage/stock_data/hk')
CURRENT_POOL = ['00700','09988','01810','03690','09999','02513','00100','02162','02616','09969',
    '02418','01357','00981','01347','00522','01093','01177','02338','02038','01378',
    '00388','02388','02318','00939','02628','03988','09888','02899','03993','02618',
    '01929','01113','06181','00669','09660']
HN = 5; SCORE_THR = 0.5
HK_COMM = 0.001; HK_STAMP = 0.0013; HK_FEE = 0.0000565; SLIP = 0.001

# 防御池 (恐慌期表现靠前的)
DEFENSE = ['00939','03988','02388','02318','01113','02628','02338','01378','02418']

def calc_score(closes):
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~(np.isnan(y)|np.isinf(y)); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    w = np.linspace(1, 2, len(x_m))
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = np.exp(slope * 250); fitted = slope * x_m + intercept; res = y_m - fitted
    ss_res = np.sum(w * res ** 2); ss_tot = np.sum(w * (y_m - np.mean(y_m)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return (ann - 1) * r2

import akshare as ak
htech = ak.stock_hk_index_daily_sina(symbol='HSTECH')
htech['date'] = pd.to_datetime(htech['date']); htech = htech.set_index('date').sort_index()
htech_c = htech['close']

def check_panic(dt):
    m = htech_c.index <= dt; h = htech_c.loc[m]
    return len(h) >= 25 and float(h.iloc[-1]) < float(h.iloc[-25:].mean())

def run(all_data, td, mode='empty'):
    """
    mode: 'empty'=恐慌清仓空仓, 'normal'=恐慌不干预, 'defense'=恐慌仅买防御
    """
    pf_cash = 1_000_000; pos = {}; panic_cnt = 0
    for date in td:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < 5: continue

        is_panic = check_panic(tds)

        if mode == 'empty' and is_panic:
            panic_cnt += 1
            for code in list(pos.keys()):
                p = prices.get(code)
                if not p: continue
                po = pos[code]; sp = p * (1 - SLIP); tv2 = po['shares'] * sp
                comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                pf_cash += tv2 - comm - stamp - tfee; del pos[code]
            continue

        # 排名
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score(hist['close'].values[-25:])
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])

        if mode == 'defense' and is_panic:
            # 恐慌期: 卖出不在目标+不在防御池的; 新买入仅限防御池
            panic_cnt += 1
            # 允许的目标: 防御池得分>=SCORE_THR + 已有持仓(保留)
            defense_ranked = [r for r in ranked if r['code'] in DEFENSE and r['score'] >= SCORE_THR]
            # 已有持仓也保留如果得分>=0
            hold_codes = set(pos.keys())
            targets = defense_ranked[:HN]
            target_codes = set(r['code'] for r in targets)
            
            for code in list(pos.keys()):
                if code not in target_codes and code not in hold_codes:
                    p = prices.get(code)
                    if not p: continue
                    po = pos[code]; sp = p * (1 - SLIP); tv2 = po['shares'] * sp
                    comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                    pf_cash += tv2 - comm - stamp - tfee; del pos[code]
        else:
            # 正常排名
            targets = [r for r in ranked if r['score'] >= SCORE_THR][:HN]
            target_codes = set(r['code'] for r in targets)

            for code in list(pos.keys()):
                if code not in target_codes:
                    p = prices.get(code)
                    if not p: continue
                    po = pos[code]; sp = p * (1 - SLIP); tv2 = po['shares'] * sp
                    comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                    pf_cash += tv2 - comm - stamp - tfee; del pos[code]

            # 买入
            new = [r for r in targets if r['code'] not in pos]
            if new:
                avail = pf_cash * 0.95; per = avail / len(new)
                for r in new:
                    bp = r['price'] * (1 + SLIP); sh = int(per / bp / 100) * 100
                    if sh < 100: continue
                    cost = sh * bp; comm = max(cost * HK_COMM, 5); tfee = cost * HK_FEE
                    pf_cash -= cost + comm + tfee
                    pos[r['code']] = {'shares': sh, 'cp': bp}

    # 终值
    tv = pf_cash
    for c, po in pos.items():
        tv += po['shares'] * prices.get(c, po['cp'])
    tr = (tv / 1_000_000 - 1) * 100
    days = len(td); af = 252 / max(days, 1)
    cagr = ((tv / 1_000_000) ** af - 1) * 100
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'pd': panic_cnt}

# 1/3/5年
periods = [('1年','2025-06-26','2026-06-27'),('3年','2023-06-26','2026-06-27'),('5年','2021-06-26','2026-06-27')]
modes = [('empty','当前(空仓)'),('normal','恐慌不干预'),('defense','恐慌防御池')]

for pn, start, end in periods:
    print(f'\n[{pn}] {start}~{end}')
    pdata = {}
    for code in CURRENT_POOL:
        fp = HK_DIR / f'hk{code}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp); df.columns = [c.lower().strip() for c in df.columns]
        dc = [c for c in df.columns if c.lower() == 'date'][0]
        df = df.rename(columns={dc: 'date'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= start) & (df.index <= end); df = df[m]
        if len(df) >= 25: pdata[code] = df
    td = sorted(set().union(*[set(df.index) for df in pdata.values()]))
    td = [d for d in td if start <= d.strftime('%Y-%m-%d') <= end]

    print(f'  {len(pdata)}只/{len(td)}交易日')

    best_tr = -999; best_mode = ''
    for mode, label in modes:
        r = run(pdata, td, mode)
        t = r['tr']; c = r['cagr']; p = r['pd']
        print(f'  {label:<20} +{t:>7.1f}% CAGR{c:>6.1f}% 恐慌{p:>4}天')
        if r['tr'] > best_tr:
            best_tr = r['tr']; best_mode = label
    if best_mode:
        print(f'  → 最优: {best_mode}')

print('\n完成!')
