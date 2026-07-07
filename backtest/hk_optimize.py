"""
七星港股版 参数优化
测试: 持仓数 / 得分阈值 / 恐慌过滤 / 排名周期
"""
import sys, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
HK_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'hk'

HK_POOL = ['00700','09999','09988','03690','01810','09618','09888','09961','01024','02015',
           '01211','02269','06181','01929','02331','00992','00981','01347','09626','09880',
           '02513','02382','01357','02018','02388','00005','00388','00522','00669','09901',
           '09633','01038','09868','01057','02628','01109','02057']
HK_NAME = {'00700':'腾讯','09999':'网易','09988':'阿里','03690':'美团','01810':'小米',
           '09618':'京东','09888':'百度','09961':'携程','01024':'快手','02015':'理想',
           '01211':'比亚迪','02269':'药明生物','06181':'老铺黄金','01929':'周大福',
           '02331':'李宁','00992':'联想','00981':'中芯国际','01347':'华虹半导体',
           '09626':'B站','09880':'优必选','02513':'智谱','02382':'舜宇','01357':'美图',
           '02018':'瑞声','02388':'中银香港','00005':'汇丰','00388':'港交所',
           '00522':'ASMPT','00669':'创科','09901':'新东方在线','09633':'农夫山泉',
           '01038':'长建','09868':'小鹏','01057':'浙江沪杭甬','02628':'中国人寿',
           '01109':'华润置地','02057':'中通快递'}
HK_COMM = 0.001; HK_STAMP = 0.0013; HK_FEE = 0.0000565; SLIP = 0.001

# hk_live_report 同款 calc_score
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

# 恒生科技
import akshare as ak
htech = ak.stock_hk_index_daily_sina(symbol='HSTECH')
htech['date'] = pd.to_datetime(htech['date']); htech = htech.set_index('date').sort_index()
htech_c = htech['close']

def check_panic(dt, ma=25):
    m = htech_c.index <= dt; h = htech_c.loc[m]
    return len(h) >= ma and float(h.iloc[-1]) < float(h.iloc[-ma:].mean())

class PF:
    def __init__(self): self.cash = 1_000_000; self.pos = {}; self.log = []; self.daily = []
    @property
    def tv(self):
        return self.cash + sum(p['shares'] * p.get('lp', p['cp']) for p in self.pos.values())
    def codes(self): return [c for c in self.pos if c != '511010']

def run(all_data, td_list, hn=5, thr=0.5, panic=False, lookback=25):
    pf = PF(); pd_cnt = 0
    for date in td_list:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < hn: continue

        if panic and check_panic(tds):
            pd_cnt += 1
            for code in list(pf.codes()):
                p = prices.get(code)
                if not p: continue
                pos = pf.pos[code]; sp = p * (1 - SLIP); tv2 = pos['shares'] * sp
                comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                pf.cash += tv2 - comm - stamp - tfee; del pf.pos[code]
            pf.daily.append(pf.tv); continue

        # 排名
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < lookback + 10: continue
            score = calc_score(hist['close'].values[-lookback:])
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = [r for r in ranked if r['score'] >= thr][:hn]
        target_codes = set(r['code'] for r in targets)

        # 卖出
        for code in list(pf.codes()):
            if code not in target_codes:
                p = prices.get(code)
                if not p: continue
                pos = pf.pos[code]; sp = p * (1 - SLIP); tv2 = pos['shares'] * sp
                comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                pnl = (sp - pos['cp']) / pos['cp'] * 100
                pf.cash += tv2 - comm - stamp - tfee
                pf.log.append({'pnl': round(pnl, 2)}); del pf.pos[code]

        # 买入
        new = [r for r in targets if r['code'] not in pf.codes()]
        if new:
            avail = pf.cash * 0.95; per = avail / len(new)
            for r in new:
                bp = r['price'] * (1 + SLIP); sh = int(per / bp / 100) * 100
                if sh < 100: continue
                cost = sh * bp; comm = max(cost * HK_COMM, 5); stamp = 0; tfee = cost * HK_FEE
                pf.cash -= cost + comm + stamp + tfee
                pf.pos[r['code']] = {'shares': sh, 'cp': bp, 'lp': r['price']}

        pf.daily.append(pf.tv)

    vals = pf.daily
    if len(vals) < 2: return {'tr': 0, 'cagr': 0, 'mdd': 0, 'sh': 0, 'wr': 0, 'nt': 0, 'pd': pd_cnt}
    tr = (vals[-1] / vals[0] - 1) * 100
    days = len(vals); af = 252 / days
    cagr = ((vals[-1] / vals[0]) ** af - 1) * 100
    peak = vals[0]; mdd = 0
    for v in vals:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < mdd: mdd = dd
    mdd = abs(mdd)
    dr = np.diff(vals) / vals[:-1]
    sh = np.mean(dr) / np.std(dr) * np.sqrt(252) if len(dr) > 1 and np.std(dr) > 0 else 0
    sells = [t for t in pf.log]
    wins = [t for t in sells if t['pnl'] > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
            'sh': round(sh, 2), 'wr': round(wr, 1), 'nt': len(pf.log), 'pd': pd_cnt, 'tv': round(vals[-1], 0)}

# 加载
START, END = '2023-06-25', '2026-06-26'
all_data = {}
for code in HK_POOL:
    fp = HK_DIR / f'hk{code}.csv'
    if not fp.exists(): continue
    df = pd.read_csv(fp); df.columns = [c.lower().strip() for c in df.columns]
    df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
    m = (df.index >= START) & (df.index <= END)
    df = df[m]
    if len(df) >= 25: all_data[code] = df

td_all = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in td_all if START <= d.strftime('%Y-%m-%d') <= END]
print(f"池: {len(all_data)}只 / {len(trade_dates)}交易日\n")

# ---- 参数网格 ----
configs = [
    # (label, hn, thr, panic, lookback)
    ("当前默认", 5, 0.5, True, 25),
    ("关闭恐慌", 5, 0.5, False, 25),
    ("HN=3", 3, 0.5, False, 25),
    ("HN=7", 7, 0.5, False, 25),
    ("Thr=0.3", 5, 0.3, False, 25),
    ("Thr=0.7", 5, 0.7, False, 25),
    ("HN=3/Thr=0.3", 3, 0.3, False, 25),
    ("HN=7/Thr=0.3", 7, 0.3, False, 25),
    ("LB=15日", 5, 0.5, False, 15),
    ("LB=50日", 5, 0.5, False, 50),
    ("HN=3/LB=15/Thr=0.3", 3, 0.3, False, 15),
    ("HN=7/LB=15/Thr=0.3", 7, 0.3, False, 15),
]

print(f"{'配置':<25} {'累计%':>8} {'CAGR%':>7} {'回撤%':>7} {'夏普':>6} {'胜率%':>6} {'交易':>5} {'恐慌':>5} {'终值HKD':>12}")
print("-" * 90)

best = None
for label, hn, thr, panic, lb in configs:
    r = run(all_data, trade_dates, hn, thr, panic, lb)
    star = ''
    if best is None: best = r
    elif r['tr'] > best['tr']: best = r
    if r['tr'] == max(r['tr'] for _,_,_,_,_ in configs): star = ' ★'
    print(f"{label:<25} {r['tr']:>+7.1f} {r['cagr']:>7.1f} {-r['mdd']:>7.1f} {r['sh']:>6.2f} {r['wr']:>6.1f} {r['nt']:>5} {r['pd']:>5} HK$ {r['tv']:>10,.0f}{star}")

# 按类别分析
print(f"\n{'='*70}")
print("分析总结")
print(f"{'='*70}")

baseline = [c for c in configs if c[0] == "关闭恐慌"][0]
r_bl = run(all_data, trade_dates, baseline[1], baseline[2], baseline[3], baseline[4])
print(f"\n基准(关闭恐慌,HN=5,Thr=0.5): +{r_bl['tr']}% / 回撤-{r_bl['mdd']}% / 夏普{r_bl['sh']}")

# HN效应
for hn in [3, 5, 7]:
    r = run(all_data, trade_dates, hn, 0.5, False, 25)
    diff = r['tr'] - r_bl['tr']
    print(f"  HN={hn}: +{r['tr']}% / 回撤-{r['mdd']}% / 夏普{r['sh']} (vs基准 {diff:+.1f}%)")

# 阈值效应
for thr in [0.3, 0.5, 0.7]:
    r = run(all_data, trade_dates, 5, thr, False, 25)
    diff = r['tr'] - r_bl['tr']
    print(f"  Thr={thr}: +{r['tr']}% / 回撤-{r['mdd']}% / 夏普{r['sh']} (vs基准 {diff:+.1f}%)")

# LB效应  
for lb in [15, 25, 50]:
    r = run(all_data, trade_dates, 5, 0.5, False, lb)
    diff = r['tr'] - r_bl['tr']
    print(f"  LB={lb}: +{r['tr']}% / 回撤-{r['mdd']}% / 夏普{r['sh']} (vs基准 {diff:+.1f}%)")

print("\n完成!")
