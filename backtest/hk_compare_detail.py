"""
七星港股版 关闭 vs 恒生科技25日 近3年详细对比
"""
import sys, math, warnings, json
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
HN = 5; SCORE_THR = 0.5
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

def check_panic(dt):
    m = htech_c.index <= dt; h = htech_c.loc[m]
    return len(h) >= 25 and float(h.iloc[-1]) < float(h.iloc[-25:].mean())

# hk_live_report 同款回测
class PF:
    def __init__(self): self.cash = 1_000_000; self.positions = {}; self.trade_log = []
    @property
    def tv(self):
        return self.cash + sum(p['shares'] * p.get('lp', p['cp']) for p in self.positions.values())
    def codes(self): return list(self.positions.keys())

def run(enable_panic):
    pf = PF(); pd_cnt = 0
    for date in trade_dates:
        d_str = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < HN: continue

        if enable_panic and check_panic(tds):
            pd_cnt += 1
            for code in list(pf.codes()):
                p = prices.get(code)
                if not p: continue
                pos = pf.positions[code]; sp = p * (1 - SLIP); tv2 = pos['shares'] * sp
                comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                pnl = (sp - pos['cp']) / pos['cp'] * 100
                pf.cash += tv2 - comm - stamp - tfee
                pf.trade_log.append({'date': d_str, 'action': 'PANIC_SELL', 'code': code, 'price': sp, 'pnl_pct': round(pnl, 2)})
                del pf.positions[code]
            continue

        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score(hist['close'].values[-25:])
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = [r for r in ranked if r['score'] >= SCORE_THR][:HN]
        target_codes = set(r['code'] for r in targets)

        for code in list(pf.codes()):
            if code not in target_codes:
                p = prices.get(code)
                if not p: continue
                pos = pf.positions[code]; sp = p * (1 - SLIP); tv2 = pos['shares'] * sp
                comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
                pnl = (sp - pos['cp']) / pos['cp'] * 100
                pf.cash += tv2 - comm - stamp - tfee
                pf.trade_log.append({'date': d_str, 'action': 'SELL', 'code': code, 'price': sp, 'pnl_pct': round(pnl, 2)})
                del pf.positions[code]

        new = [r for r in targets if r['code'] not in pf.codes()]
        if new:
            avail = pf.cash * 0.95; per = avail / len(new)
            for r in new:
                bp = r['price'] * (1 + SLIP); sh = int(per / bp / 100) * 100
                if sh < 100: continue
                cost = sh * bp; comm = max(cost * HK_COMM, 5); stamp = 0; tfee = cost * HK_FEE
                pf.cash -= cost + comm + stamp + tfee
                pf.positions[r['code']] = {'shares': sh, 'cp': bp}
                pf.trade_log.append({'date': d_str, 'action': 'BUY', 'code': r['code'], 'price': bp, 'shares': sh})
    return pf, pd_cnt

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

print(f"加载: {len(all_data)}只 / {len(trade_dates)}交易日 ({START}~{END})")

# 跑两次
pf_off, _ = run(False)
pf_on, pd_cnt = run(True)

def stats(pf):
    vals = [1_000_000]
    cash = 1_000_000
    pns = {}
    for t in pf.trade_log:
        vals.append(pf.tv if hasattr(pf, 'tv') else cash)
        if t['action'] in ('SELL', 'PANIC_SELL') and 'pnl_pct' in t:
            if t['code'] not in pns: pns[t['code']] = {'count': 0, 'wins': 0, 'total': 0}
            pns[t['code']]['count'] += 1
            if t['pnl_pct'] > 0: pns[t['code']]['wins'] += 1
            pns[t['code']]['total'] += t['pnl_pct']
    tr = (vals[-1] / vals[0] - 1) * 100 if vals else 0
    peak = vals[0]; mdd = 0
    for v in vals:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < mdd: mdd = dd
    sells = [t for t in pf.trade_log if t['action'] in ('SELL', 'PANIC_SELL') and 'pnl_pct' in t]
    wins = [t for t in sells if t['pnl_pct'] > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    return {'total': round(tr, 1), 'mdd': round(abs(mdd), 1), 'trades': len(pf.trade_log),
            'sells': len(sells), 'wr': round(wr, 1), 'pnl_by_code': pns}

s_off = stats(pf_off); s_on = stats(pf_on)

print(f"\n{'='*70}")
print("概览对比")
print(f"{'='*70}")
print(f"{'':20} {'关闭(无过滤)':>20} {'恒生科技25日':>20} {'差异':>20}")
print(f"{'总交易笔数':20} {s_off['trades']:>20} {s_on['trades']:>20} {s_on['trades']-s_off['trades']:>+20}")
print(f"{'卖出笔数':20} {s_off['sells']:>20} {s_on['sells']:>20} {s_on['sells']-s_off['sells']:>+20}")
print(f"{'胜率':20} {s_off['wr']:>19.1f}% {s_on['wr']:>19.1f}% {s_on['wr']-s_off['wr']:>+19.1f}%")

# Top10 盈利排行
def pnl_top10(pnl_dict, label):
    ranked = sorted(pnl_dict.items(), key=lambda x: x[1]['total'], reverse=True)
    print(f"\n{'='*70}")
    print(f"Top10 成分股盈亏排行 — {label}")
    print(f"{'='*70}")
    print(f"{'排名':<5} {'代码':<7} {'名称':<10} {'交易':>5} {'胜率':>7} {'累计盈亏':>10} {'均笔':>8}")
    for i, (code, d) in enumerate(ranked[:10]):
        name = HK_NAME.get(code, code)
        avg = d['total'] / d['count'] if d['count'] > 0 else 0
        wr = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
        print(f"{i+1:<5} {code:<7} {name:<10} {d['count']:>5} {wr:>6.1f}% {d['total']:>+9.1f}% {avg:>+7.1f}%")

    # Bottom 5
    ranked = sorted(pnl_dict.items(), key=lambda x: x[1]['total'])
    print(f"\n--- 最差5只 ---")
    print(f"{'排名':<5} {'代码':<7} {'名称':<10} {'交易':>5} {'胜率':>7} {'累计盈亏':>10} {'均笔':>8}")
    for i, (code, d) in enumerate(ranked[:5]):
        name = HK_NAME.get(code, code)
        avg = d['total'] / d['count'] if d['count'] > 0 else 0
        wr = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
        print(f"{i+1:<5} {code:<7} {name:<10} {d['count']:>5} {wr:>6.1f}% {d['total']:>+9.1f}% {avg:>+7.1f}%")

pnl_top10(s_off['pnl_by_code'], '关闭(无过滤)')
pnl_top10(s_on['pnl_by_code'], '恒生科技25日')

# 交易记录对比前20笔
print(f"\n{'='*70}")
print("前20笔交易记录对比 (Y=买入, S=卖出, P=恐慌卖出)")
print(f"{'='*70}")
print(f"\n--- 关闭 前20笔 ---")
print(f"{'日期':<12} {'动作':<4} {'代码':<7} {'名称':<10} {'盈亏%':>8}")
for t in pf_off.trade_log[:20]:
    a = 'BUY' if t['action'] == 'BUY' else 'SELL'
    name = HK_NAME.get(t['code'], t['code'])
    pnl = f"{t.get('pnl_pct',0):+.1f}%" if 'pnl_pct' in t else '-'
    print(f"{t['date']:<12} {a:<4} {t['code']:<7} {name:<10} {pnl:>8}")

print(f"\n--- 恒生科技25日 前20笔 ---")
for t in pf_on.trade_log[:20]:
    a = 'BUY' if t['action'] == 'BUY' else ('PANIC' if t['action'] == 'PANIC_SELL' else 'SELL')
    name = HK_NAME.get(t['code'], t['code'])
    pnl = f"{t.get('pnl_pct',0):+.1f}%" if 'pnl_pct' in t else '-'
    print(f"{t['date']:<12} {a:<4} {t['code']:<7} {name:<10} {pnl:>8}")

# 恐慌触发详情
if pd_cnt > 0:
    panic_log = [t for t in pf_on.trade_log if t['action'] == 'PANIC_SELL']
    print(f"\n{'='*70}")
    print(f"恐慌卖出详情 ({len(panic_log)}笔 / 共{pd_cnt}天)")
    print(f"{'='*70}")
    print(f"{'日期':<12} {'代码':<7} {'名称':<10} {'价格':>10} {'盈亏%':>8}")
    for t in panic_log[:30]:
        name = HK_NAME.get(t['code'], t['code'])
        pnl = f"{t.get('pnl_pct',0):+.1f}%" if 'pnl_pct' in t else '-'
        print(f"{t['date']:<12} {t['code']:<7} {name:<10} {t['price']:>10.2f} {pnl:>8}")

print(f"\n完成!")
