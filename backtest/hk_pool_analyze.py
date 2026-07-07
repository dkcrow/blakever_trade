"""
恒生+恒生科技成分股 5年单只回测
找出优质/劣质标的, 优化股池
"""
import sys, math, warnings, subprocess, json, os
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
HK_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'hk'
HK_DIR.mkdir(parents=True, exist_ok=True)

# 恒生指数 + 恒生科技 核心成分股 (5位代码)
CANDIDATES = [
    '00005','00011','00016','00027','00175','00241','00267','00288','00291','00316',
    '00388','00669','00700','00762','00823','00883','00909','00939','00941','00981',
    '00992','01038','01044','01088','01093','01109','01113','01177','01209','01211',
    '01299','01398','01810','01876','01929','01997','02007','02015','02018','02020',
    '02057','02269','02313','02318','02319','02331','02382','02388','02628','02688',
    '02899','03690','03888','06098','06181','06618','06862','09618','09626','09633',
    '09660','09688','09698','09866','09868','09880','09888','09901','09961','09988',
    '09992','09999','01024','01347','01357','01833','02513','02013','09987','02601',
]
# Dedupe
CANDIDATES = list(dict.fromkeys(CANDIDATES))

WESTOCK = str(Path.home() / '.workbuddy/plugins/marketplaces/experts/plugins/stock-partner-team/skills/westock-data/scripts/index.js')

def download_hk_kline(code):
    """下载港股日线数据到本地"""
    fp = HK_DIR / f'hk{code}.csv'
    if fp.exists(): return True
    try:
        result = subprocess.run(
            ['node', WESTOCK, 'kline', f'hk{code}', 'daily', '2018-01-01', '2026-06-27'],
            capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT
        )
        if result.returncode != 0 or not result.stdout.strip(): return False
        lines = [l.strip() for l in result.stdout.split('\n') if l.strip() and '---' not in l]
        header = None
        for l in lines:
            if '|' in l and 'date' in l.lower():
                header = l; break
        if not header: return False
        cols = [c.strip() for c in header.split('|') if c.strip()]
        rows = []
        for l in lines[lines.index(header)+1:]:
            if '|' not in l: continue
            vals = [v.strip() for v in l.split('|') if v.strip()]
            if len(vals) != len(cols): continue
            rows.append(dict(zip(cols, vals)))
        if len(rows) < 50: return False
        df = pd.DataFrame(rows)
        for c in df.columns:
            if c.lower() == 'last': df = df.rename(columns={'last': 'close'})
        df = df[['date','close']]
        df['date'] = pd.to_datetime(df['date']); df = df.sort_values('date')
        df.to_csv(fp, index=False)
        return True
    except Exception:
        return False

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

HK_COMM = 0.001; HK_STAMP = 0.0013; HK_FEE = 0.0000565; SLIP = 0.001

def run_single(df, lookback=25, thr=0.5):
    """单只买入持有模拟: 有得分>thr时买入,得分<0.5时卖出,现金等待"""
    cash = 1_000_000; pos = None; vals = [cash]
    for i in range(len(df)):
        if i < lookback + 10: continue
        close = float(df.iloc[i]['close'])
        date = df.index[i]
        # 用前lookback日计算得分
        score = calc_score(df.iloc[i-lookback:i]['close'].values)

        if pos is None and score >= thr:
            bp = close * (1 + SLIP); sh = int(cash * 0.95 / bp / 100) * 100
            if sh >= 100:
                cost = sh * bp; comm = max(cost * HK_COMM, 5)
                cash -= cost + comm
                pos = {'shares': sh, 'cp': bp}
        elif pos is not None:
            tv_now = pos['shares'] * close * (1 - SLIP)
            comm = max(tv_now * HK_COMM, 5); stamp = tv_now * HK_STAMP; tfee = tv_now * HK_FEE
            net = tv_now - comm - stamp - tfee
            if score < thr:
                cash = net; pos = None

        tv = cash + (pos['shares'] * close if pos else 0)
        vals.append(tv)

    return (vals[-1] / vals[0] - 1) * 100 if len(vals) > 1 else 0

# 主流程
print("1. 同步港股成分股数据...")
exist = 0; dl = 0; fail = 0
for code in CANDIDATES:
    fp = HK_DIR / f'hk{code}.csv'
    if fp.exists():
        exist += 1; continue
    if download_hk_kline(code):
        dl += 1; print(f'  + {code}')
    else:
        fail += 1
print(f"  已有{exist}只, 下载{dl}只, 失败{fail}只")

print("\n2. 5年回测 (2021-06~2026-06)...")
results = []
START, END = '2021-06-26', '2026-06-27'
for code in CANDIDATES:
    fp = HK_DIR / f'hk{code}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        if 'last' in df.columns: df = df.rename(columns={'last': 'close'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= START) & (df.index <= END)
        df = df[m]
        if len(df) < 250: continue
        # 单持有
        r = run_single(df, 25, 0.5)
        # 也计算简单buy&hold
        bh = (float(df['close'].iloc[-1]) / float(df['close'].iloc[0]) - 1) * 100
        results.append({'code': code, 'ret': round(r, 1), 'bh': round(bh, 1)})
    except Exception as e:
        pass

results.sort(key=lambda x: -x['ret'])
print(f"  有效: {len(results)}只")

# 当前股池
current_set = set(HK_POOL) if 'HK_POOL' in dir() else {'00700','09999','09988','03690','01810','09618','09888','09961','01024','02015','01211','02269','06181','01929','02331','00992','00981','01347','09626','09880','02513','02382','01357','02018','02388','00005','00388','00522','00669','09901','09633','01038','09868','01057','02628','01109','02057'}

print(f"\n{'='*70}")
print("Top 30 正向收益 (策略回测)")
print(f"{'='*70}")
print(f"{'排名':<5} {'代码':<7} {'策略%':>8} {'持有%':>8} {'状态':>6}")
for i, r in enumerate(results[:30]):
    in_pool = '池内' if r['code'] in current_set else ''
    print(f"{i+1:<5} {r['code']:<7} {r['ret']:>+7.1f} {r['bh']:>+7.1f} {in_pool:>6}")

print(f"\n{'='*70}")
print("Bottom 20 (最差)")
print(f"{'='*70}")
for i, r in enumerate(results[-20:]):
    in_pool = '池内' if r['code'] in current_set else ''
    print(f"{len(results)-19+i:<5} {r['code']:<7} {r['ret']:>+7.1f} {r['bh']:>+7.1f} {in_pool:>6}")

# 池内vs池外对比
pool_ret = [r['ret'] for r in results if r['code'] in current_set]
out_ret = [r['ret'] for r in results if r['code'] not in current_set]
print(f"\n{'='*70}")
print(f"股池分析")
print(f"{'='*70}")
print(f"当前池内({len(pool_ret)}只): 均值{np.mean(pool_ret):+.1f}% 中位{np.median(pool_ret):+.1f}% 正收益{sum(1 for r in pool_ret if r>0)}/{len(pool_ret)}")
print(f"池外候选({len(out_ret)}只): 均值{np.mean(out_ret):+.1f}% 中位{np.median(out_ret):+.1f}% 正收益{sum(1 for r in out_ret if r>0)}/{len(out_ret)}")

# 池内负收益股
neg_codes = [(r['code'], r['ret']) for r in results if r['code'] in current_set and r['ret'] < 0]
print(f"\n池内负收益股({len(neg_codes)}只):")
for c, v in neg_codes:
    print(f"  {c}: {v:+.0f}%")

# Top池外正收益
pos_out = [r for r in results if r['code'] not in current_set and r['ret'] > 0]
print(f"\n池外正收益Top15:")
for i, r in enumerate(pos_out[:15]):
    print(f"  {r['code']} {r['ret']:+.1f}% (持有{r['bh']:+.1f}%)")

print("\n完成!")
