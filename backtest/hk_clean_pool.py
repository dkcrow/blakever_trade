"""
港股版股池清洗 + 扩招
1. 诊断当前38只池内每只的策略贡献
2. 扫描恒生科技+恒生指数池外候选
"""
import sys, math, warnings, subprocess
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0,'.')
from backtest.hk_optimize import *

HK_DIR = Path('data/storage/stock_data/hk')
WESTOCK = str(Path.home() / '.workbuddy/plugins/marketplaces/experts/plugins/stock-partner-team/skills/westock-data/scripts/index.js')

START, END = '2023-06-25', '2026-06-29'

def load_pool(codes):
    data = {}
    for code in codes:
        fp = HK_DIR / f'hk{code}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp); df.columns = [c.lower().strip() for c in df.columns]
        dc = [c for c in df.columns if c.lower() == 'date'][0]
        df = df.rename(columns={dc: 'date'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= START) & (df.index <= END); df = df[m]
        if len(df) >= 25: data[code] = df
    td = sorted(set().union(*[set(df.index) for df in data.values()]))
    td = [d for d in td if START <= d.strftime('%Y-%m-%d') <= END]
    return data, td

# ====== 1. 加载全池 + 逐只诊断 ======
print("=== 1. 池内逐只诊断 ===\n")
all_data, td = load_pool(HK_POOL)

# 跑一次完整回测追踪每只的买入/卖出
class DiagPF:
    def __init__(self): self.cash = 1_000_000; self.pos = {}
    def codes(self): return list(self.pos.keys())

pf = DiagPF()
stats = {}  # code -> {buys, sells, total_pnl}
for date in td:
    ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
    prices = {}
    for code in all_data:
        m = all_data[code].index == date
        if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
    if len(prices) < 5: continue

    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        m = df.index < tds; hist = df[m]
        if len(hist) < 35: continue
        score = calc_score(hist['close'].values[-25:])
        ranked.append({'code': code, 'score': score, 'price': prices[code]})
    ranked.sort(key=lambda x: -x['score'])
    targets = [r for r in ranked if r['score'] >= 0.5][:5]
    tc = set(r['code'] for r in targets)

    # Sell
    for code in list(pf.codes()):
        if code not in tc:
            p = prices.get(code)
            if not p: continue
            pos = pf.pos[code]; sp = p * (1 - SLIP); tv2 = pos['shares'] * sp
            comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
            pnl = (sp - pos['cp']) / pos['cp'] * 100
            pf.cash += tv2 - comm - stamp - tfee
            if code not in stats: stats[code] = {'buys': 0, 'sells': 0, 'pnl': 0}
            stats[code]['sells'] += 1; stats[code]['pnl'] += pnl
            del pf.pos[code]

    # Buy - properly track
    new_targets = [r for r in targets if r['code'] not in pf.pos]
    if new_targets:
        avail = pf.cash * 0.95; per = avail / len(new_targets)
        for r in new_targets:
            bp = r['price'] * (1 + SLIP); sh = int(per / bp / 100) * 100
            if sh < 100: continue
            cost = sh * bp; comm = max(cost * HK_COMM, 5); tfee = cost * HK_FEE
            pf.cash -= cost + comm + tfee
            pf.pos[r['code']] = {'shares': sh, 'cp': bp}
            if r['code'] not in stats: stats[r['code']] = {'buys': 0, 'sells': 0, 'pnl': 0}
            stats[r['code']]['buys'] += 1

# 计算得分统计
for code in list(all_data.keys()):
    scores = []
    for date in td[:600:15]:
        tds = pd.Timestamp(date); df = all_data[code]
        m = df.index < tds; hist = df[m]
        if len(hist) < 35: continue
        scores.append(calc_score(hist['close'].values[-25:]))
    if scores:
        avg_s = np.mean(scores); pos_pct = sum(1 for s in scores if s >= 0.5) / len(scores) * 100
        max_s = max(scores)
    else:
        avg_s = -999; pos_pct = 0; max_s = -999
    if code not in stats: stats[code] = {'buys': 0, 'sells': 0, 'pnl': 0}
    stats[code]['avg_score'] = round(avg_s, 3)
    stats[code]['score_pos_pct'] = round(pos_pct, 1)
    stats[code]['max_score'] = round(max_s, 2)

# 输出
print(f"{'代码':<7} {'名称':<12} {'买入':>4} {'卖出':>4} {'盈亏%':>8} {'均分':>7} {'>=0.5%':>7} {'判定':>10}")
print("-" * 70)
remove_candidates = []
for code in sorted(stats.keys()):
    s = stats[code]
    name = HK_NAME.get(code, code)
    buys = s.get('buys', 0); sells = s.get('sells', 0)
    pnl = s.get('pnl', 0)
    avg = s.get('avg_score', -999); pos = s.get('score_pos_pct', 0)
    mx = s.get('max_score', -999)
    
    # 判定
    verdict = '✅保留'
    if buys == 0 and sells == 0:
        verdict = '❌从未交易'  # 死重
    elif sells > 0 and pnl < -20:
        verdict = '❌策略大亏'
    elif buys < 5 and sells < 5:
        verdict = '⚠️极少交易'
    elif sells > 0 and pnl < 0:
        verdict = '⚠️轻微亏损'
    
    if verdict.startswith('❌'):
        remove_candidates.append(code)
    
    print(f"{code:<7} {name:<12} {buys:>4} {sells:>4} {pnl:>+7.1f} {avg:>7.3f} {pos:>6.1f}% {verdict:>10}")

print(f"\n待剔除候选({len(remove_candidates)}只): {remove_candidates}")

# ====== 2. 扫描池外恒生/恒生科技成分股 ======
print(f"\n{'='*70}")
print("2. 扫描池外候选 (恒生指数+恒生科技成分股)")
print(f"{'='*70}")

# 预设池外候选(之前分析时硬编码的CANDIDATES中不在当前池的)
CANDIDATES = [
    '00011','00016','00027','00175','00241','00267','00288','00291','00316',
    '00762','00823','00883','00909','00939','00941','01044','01088','01093',
    '01113','01177','01209','01299','01398','01876','01997','02007','02020',
    '02313','02318','02319','02688','02899','03888','06098','06618','06862',
    '09660','09688','09698','09866','09987','09992','02013','02601','01833',
]

pool_set = set(HK_POOL)
outside = [c for c in CANDIDATES if c not in pool_set]

# 下载缺失数据
new_dl = 0
for code in outside:
    fp = HK_DIR / f'hk{code}.csv'
    if fp.exists(): continue
    try:
        r = subprocess.run(['node', WESTOCK, 'kline', f'hk{code}', 'daily', '2018-01-01', '2026-06-29'],
                          capture_output=True, text=True, timeout=60, cwd=Path(__file__).parent.parent)
        if r.returncode != 0 or not r.stdout.strip(): continue
        lines = [l.strip() for l in r.stdout.split('\n') if l.strip() and '---' not in l]
        header = None
        for l in lines:
            if '|' in l and 'date' in l.lower(): header = l; break
        if not header: continue
        cols = [c.strip() for c in header.split('|') if c.strip()]
        rows = []
        for l in lines[lines.index(header)+1:]:
            if '|' not in l: continue
            v = [x.strip() for x in l.split('|') if x.strip()]
            if len(v) != len(cols): continue
            rows.append(dict(zip(cols, v)))
        if len(rows) < 50: continue
        df2 = pd.DataFrame(rows)
        if 'last' in df2.columns: df2 = df2.rename(columns={'last': 'close'})
        df2 = df2[['date', 'close']]
        df2.to_csv(fp, index=False)
        new_dl += 1
    except Exception:
        pass

# 分析池外候选
print(f"池外总候选: {len(outside)}只, 新下载: {new_dl}只\n")

outside_good = []
for code in outside:
    fp = HK_DIR / f'hk{code}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        if 'last' in df.columns: df = df.rename(columns={'last': 'close'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= START) & (df.index <= END)
        df = df[m]
        if len(df) < 100: continue
        
        # 计算得分统计
        scores = []
        for i in range(25, len(df), 15):
            scores.append(calc_score(df.iloc[i-25:i]['close'].values))
        if not scores: continue
        avg_s = np.mean(scores); pos_pct = sum(1 for s in scores if s >= 0.5) / len(scores) * 100
        mx_s = max(scores)
        bh = (float(df['close'].iloc[-1]) / float(df['close'].iloc[0]) - 1) * 100
        
        # 判定: 得分>=0.5占比>20% 且 max>0.5 → 候选
        if pos_pct > 15 and mx_s > 0.8:
            outside_good.append((code, round(avg_s,3), round(pos_pct,1), round(mx_s,2), round(bh,1)))
    except Exception:
        pass

outside_good.sort(key=lambda x: -x[2])  # 按>=0.5占比排序
print(f"{'代码':<7} {'BH%':>7} {'均分':>7} {'>=0.5%':>7} {'最高分':>8} {'建议':>10}")
for code, avg, pos, mx, bh in outside_good[:20]:
    rec = '✅强烈推荐' if pos > 30 else '✅推荐' if pos > 20 else '⚠️观察'
    print(f"{code:<7} {bh:>+6.1f} {avg:>7.3f} {pos:>6.1f}% {mx:>8.2f} {rec:>10}")

print(f"\n池外符合条件: {len(outside_good)}只")

# ====== 总结 ======
print(f"\n{'='*70}")
print("建议")
print(f"{'='*70}")
print(f"剔除 ({len(remove_candidates)}只): {remove_candidates}")
top_picks = [c for c,_,_,_,_ in outside_good[:5]]
print(f"加入 ({len(top_picks)}只): {top_picks}")
print(f"净变化: {len(HK_POOL) - len(remove_candidates) + len(top_picks)}只")
