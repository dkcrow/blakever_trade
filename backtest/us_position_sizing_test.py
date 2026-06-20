#!/usr/bin/env python3
"""
七星美股版 仓位管理方案对比回测
方案A: 等权调仓 (target = total_value / N, 每日再平衡)
方案B: 可用现金 (仅新标的获得现金, 已持有不调)
方案C: 固定金额 (target = initial_capital / N, 赢家削减+亏损补足)
"""
import numpy as np, pandas as pd, time
from pathlib import Path

DATA_DIR = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\data\storage\stock_data\us')
POOL = 'NVDA,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,HOOD,WDC,ARM,STX'.split(',')
HN = 7; CASH = 1000000; COMM = 0.005; SLIP = 0.0005; TH = 0.5
START = '2023-06-18'; END = '2026-06-18'

def load_data():
    all_data = {}
    for sym in POOL:
        fp = DATA_DIR / f'{sym}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        if 'Date' in df.columns:
            df = df.rename(columns={'Date':'date','Last':'close','Open':'open','High':'high','Low':'low','Volume':'volume'})
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        df = df[df['close'] > 0]
        if len(df) > 35: all_data[sym] = df
    return all_data

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(np.maximum(closes, 0.01))
    mask = ~np.isnan(y) & ~np.isinf(y); xm = x[mask]; ym = y[mask]
    if len(xm) < 5: return -999
    sl = np.polyfit(xm, ym, 1)[0]; ann = np.exp(sl * 250)
    fitted = sl * xm + np.polyfit(xm, ym, 1)[1]; res = ym - fitted
    ss = sum(res**2); st = sum((ym - np.mean(ym))**2)
    r2 = 1 - ss/st if st > 0 else 0
    return ann * r2

def get_ranked(all_data, prices, date):
    ranked = []
    for sym in POOL:
        if sym not in prices or sym not in all_data: continue
        df = all_data[sym]; hist = df[df.index < date]
        if len(hist) < 25: continue
        if prices[sym] <= 0: continue
        score = calc_score(hist['close'].values[-25:])
        ranked.append({'code': sym, 'score': score, 'price': prices[sym]})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


# ===== 方案A: 等权调仓 (172原版思路, target = total_value / N) =====
def run_equal_weight(all_data, tds):
    cash = CASH; pos = {}; daily = []
    
    for date in tds:
        prices = {}
        for sym in POOL:
            if sym in all_data and date in all_data[sym].index:
                v = all_data[sym].loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[sym] = float(v)
        
        # Update position prices
        for c in list(pos.keys()):
            if c in prices: pos[c]['lp'] = prices[c]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        if len(prices) < HN:
            daily.append(tv); continue
        
        ranked = get_ranked(all_data, prices, date)
        targets = [r for r in ranked if r['score'] >= TH][:HN]
        tc = set(r['code'] for r in targets)
        
        # Force sell if score < threshold
        for code in list(pos.keys()):
            f = next((r for r in ranked if r['code'] == code), None)
            if f and f['score'] < TH: tc.discard(code)
        
        # Sell non-targets
        for code in list(pos.keys()):
            if code not in tc and code in prices:
                p = prices[code] * (1 - SLIP); s = pos[code]['s']
                cash += s * p - s * COMM
                del pos[code]
        
        # Rebalance ALL positions to equal weight
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        if len(targets) == 0:
            daily.append(tv); continue
        target_val = tv / len(targets)
        
        for r in targets:
            code = r['code']
            if code not in prices: continue
            price = prices[code]
            
            cur_val = pos[code]['s'] * price if code in pos else 0
            diff = target_val - cur_val
            
            # 5% tolerance
            if abs(diff) < target_val * 0.05 and cur_val > 0:
                continue
            
            if diff > 0:  # Buy
                bp = price * (1 + SLIP)
                sh = int(diff / bp)
                cost = sh * bp + sh * COMM
                if sh > 0 and cost <= cash:
                    cash -= cost
                    if code in pos:
                        o = pos[code]; ts = o['s'] + sh
                        pos[code] = {'s': ts, 'cp': (o['s']*o['cp'] + sh*bp)/ts, 'lp': price}
                    else:
                        pos[code] = {'s': sh, 'cp': bp, 'lp': price}
            elif diff < 0:  # Sell excess
                sp = price * (1 - SLIP)
                sh = int(abs(diff) / sp)
                if sh > 0 and code in pos and sh <= pos[code]['s']:
                    cash += sh * sp - sh * COMM
                    pos[code]['s'] -= sh
                    if pos[code]['s'] <= 0: del pos[code]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        daily.append(tv)
    
    return daily


# ===== 方案B: 可用现金分配 (仅新标的获得现金) =====
def run_available_cash(all_data, tds):
    cash = CASH; pos = {}; daily = []
    
    for date in tds:
        prices = {}
        for sym in POOL:
            if sym in all_data and date in all_data[sym].index:
                v = all_data[sym].loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[sym] = float(v)
        
        for c in list(pos.keys()):
            if c in prices: pos[c]['lp'] = prices[c]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        if len(prices) < HN:
            daily.append(tv); continue
        
        ranked = get_ranked(all_data, prices, date)
        targets = [r for r in ranked if r['score'] >= TH][:HN]
        tc = set(r['code'] for r in targets)
        
        for code in list(pos.keys()):
            f = next((r for r in ranked if r['code'] == code), None)
            if f and f['score'] < TH: tc.discard(code)
        
        # Sell non-targets
        for code in list(pos.keys()):
            if code not in tc and code in prices:
                p = prices[code] * (1 - SLIP); s = pos[code]['s']
                cash += s * p - s * COMM
                del pos[code]
        
        # Only buy NEW targets with available cash
        new_targets = [r for r in targets if r['code'] not in pos]
        if new_targets:
            per_new = cash * 0.95 / len(new_targets)
            for r in new_targets:
                code = r['code']
                if code not in prices: continue
                bp = prices[code] * (1 + SLIP)
                sh = int(per_new / bp)
                cost = sh * bp + sh * COMM
                if sh > 0 and cost <= cash:
                    cash -= cost
                    pos[code] = {'s': sh, 'cp': bp, 'lp': prices[code]}
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        daily.append(tv)
    
    return daily


# ===== 方案C: 固定金额 (target = initial_capital / N) =====
def run_fixed_amount(all_data, tds):
    cash = CASH; pos = {}; daily = []
    FIXED_PER = CASH / HN  # 固定每只 = 初始本金 / 持仓数
    
    for date in tds:
        prices = {}
        for sym in POOL:
            if sym in all_data and date in all_data[sym].index:
                v = all_data[sym].loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[sym] = float(v)
        
        for c in list(pos.keys()):
            if c in prices: pos[c]['lp'] = prices[c]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        if len(prices) < HN:
            daily.append(tv); continue
        
        ranked = get_ranked(all_data, prices, date)
        targets = [r for r in ranked if r['score'] >= TH][:HN]
        tc = set(r['code'] for r in targets)
        
        for code in list(pos.keys()):
            f = next((r for r in ranked if r['code'] == code), None)
            if f and f['score'] < TH: tc.discard(code)
        
        # Sell non-targets
        for code in list(pos.keys()):
            if code not in tc and code in prices:
                p = prices[code] * (1 - SLIP); s = pos[code]['s']
                cash += s * p - s * COMM
                del pos[code]
        
        # 对所有目标: 维持固定金额 FIXED_PER
        for r in targets:
            code = r['code']
            if code not in prices: continue
            price = prices[code]
            
            cur_val = pos[code]['s'] * price if code in pos else 0
            diff = FIXED_PER - cur_val
            
            # 5% tolerance
            if abs(diff) < FIXED_PER * 0.05 and cur_val > 0:
                continue
            
            if diff > 0:  # 需要买入/补仓
                bp = price * (1 + SLIP)
                sh = int(diff / bp)
                cost = sh * bp + sh * COMM
                if sh > 0 and cost <= cash:
                    cash -= cost
                    if code in pos:
                        o = pos[code]; ts = o['s'] + sh
                        pos[code] = {'s': ts, 'cp': (o['s']*o['cp'] + sh*bp)/ts, 'lp': price}
                    else:
                        pos[code] = {'s': sh, 'cp': bp, 'lp': price}
            elif diff < -FIXED_PER * 0.05:  # 需要削减 (赢家收割)
                sp = price * (1 - SLIP)
                sh = int(abs(diff) / sp)
                if sh > 0 and code in pos and sh <= pos[code]['s']:
                    cash += sh * sp - sh * COMM
                    pos[code]['s'] -= sh
                    if pos[code]['s'] <= 0: del pos[code]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        daily.append(tv)
    
    return daily


# ===== 方案D: 混合方案 (可用现金 + 漂移上限 2/N) =====
def run_hybrid(all_data, tds):
    cash = CASH; pos = {}; daily = []
    
    for date in tds:
        prices = {}
        for sym in POOL:
            if sym in all_data and date in all_data[sym].index:
                v = all_data[sym].loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[sym] = float(v)
        
        for c in list(pos.keys()):
            if c in prices: pos[c]['lp'] = prices[c]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        if len(prices) < HN:
            daily.append(tv); continue
        
        ranked = get_ranked(all_data, prices, date)
        targets = [r for r in ranked if r['score'] >= TH][:HN]
        tc = set(r['code'] for r in targets)
        
        for code in list(pos.keys()):
            f = next((r for r in ranked if r['code'] == code), None)
            if f and f['score'] < TH: tc.discard(code)
        
        # Sell non-targets
        for code in list(pos.keys()):
            if code not in tc and code in prices:
                p = prices[code] * (1 - SLIP); s = pos[code]['s']
                cash += s * p - s * COMM
                del pos[code]
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        
        # 漂移上限: 单只不超过 2/N 的总市值
        n_actual = max(len(targets), 1)
        drift_cap = tv * 2.0 / n_actual
        for code in list(pos.keys()):
            if code in prices:
                cur_val = pos[code]['s'] * prices[code]
                if cur_val > drift_cap:
                    excess = cur_val - drift_cap
                    sp = prices[code] * (1 - SLIP)
                    sh = int(excess / sp)
                    if sh > 0 and sh <= pos[code]['s']:
                        cash += sh * sp - sh * COMM
                        pos[code]['s'] -= sh
                        if pos[code]['s'] <= 0: del pos[code]
        
        # Buy NEW targets with available cash
        new_targets = [r for r in targets if r['code'] not in pos]
        if new_targets:
            per_new = cash * 0.95 / len(new_targets)
            for r in new_targets:
                code = r['code']
                if code not in prices: continue
                bp = prices[code] * (1 + SLIP)
                sh = int(per_new / bp)
                cost = sh * bp + sh * COMM
                if sh > 0 and cost <= cash:
                    cash -= cost
                    pos[code] = {'s': sh, 'cp': bp, 'lp': prices[code]}
        
        tv = cash + sum(p['s'] * p.get('lp', p['cp']) for p in pos.values())
        daily.append(tv)
    
    return daily


def calc_metrics(daily_vals, label):
    dv = np.array(daily_vals)
    tr = (dv[-1] / CASH - 1) * 100
    dr = np.diff(dv) / dv[:-1]
    ann = (dv[-1] / CASH) ** (252 / max(len(dr), 1)) - 1
    dd = (dv / np.maximum.accumulate(dv) - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    return {
        'label': label,
        'total': round(tr, 1),
        'annual': round(ann * 100, 1),
        'dd': round(dd, 1),
        'sharpe': round(sp, 2),
        'final': dv[-1]
    }


if __name__ == '__main__':
    print('加载数据...')
    t0 = time.time()
    all_data = load_data()
    tds = sorted(set().union(*[set(d.index) for d in all_data.values()]))
    tds = [d for d in tds if START <= d.strftime('%Y-%m-%d') <= END]
    print(f'{len(all_data)}只, {len(tds)}天 ({time.time()-t0:.1f}s)')
    
    results = []
    
    for label, func in [
        ('A.等权调仓(172原版)', run_equal_weight),
        ('B.可用现金(当前美股版)', run_available_cash),
        ('C.固定金额(克总方案)', run_fixed_amount),
        ('D.混合(可用现金+漂移上限)', run_hybrid),
    ]:
        t1 = time.time()
        dv = func(all_data, tds)
        r = calc_metrics(dv, label)
        elapsed = time.time() - t1
        results.append(r)
        print(f'{label}: 年化{r["annual"]:+.1f}% | 回撤{r["dd"]:.1f}% | 夏普{r["sharpe"]:.2f} | ${r["final"]:,.0f} | {elapsed:.1f}s')
    
    print()
    print('=' * 90)
    print(f'{"方案":<25} | {"累计%":>8} | {"年化%":>8} | {"回撤%":>7} | {"夏普":>6} | {"终值":>14}')
    print('-' * 90)
    for r in results:
        print(f'{r["label"]:<25} | {r["total"]:>+7.1f} | {r["annual"]:>+7.1f} | {r["dd"]:>7.1f} | {r["sharpe"]:>6.2f} | ${r["final"]:>13,.0f}')
    print('=' * 90)
    
    best = max(results, key=lambda x: x['annual'])
    print(f'\n最优: {best["label"]} (年化{best["annual"]:+.1f}%)')
