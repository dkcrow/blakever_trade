"""七星港股版 近1年交易明细 (50,000本金)"""
import math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

START, END = '2025-06-29', '2026-06-29'
CASH = 50000
HK_DIR = Path('data/storage/stock_data/hk')
SCORE_THRESHOLD = 0.5
HK_COMM = 0.001; HK_STAMP = 0.0013; HK_FEE = 0.0000565; SLIP = 0.001

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

# 加载当前35只股池
CURRENT_POOL = ['00700','09988','01810','03690','09999','02513','00100','02162','02616','09969',
    '02418','01357','00981','01347','00522','01093','01177','02338','02038','01378',
    '00388','02388','02318','00939','02628','03988','09888','02899','03993','02618',
    '01929','01113','06181','00669','09660']

all_data = {}
for code in CURRENT_POOL:
    fp = HK_DIR / f'hk{code}.csv'
    if not fp.exists(): continue
    df = pd.read_csv(fp); df.columns = [c.lower().strip() for c in df.columns]
    dc = [c for c in df.columns if c.lower() == 'date'][0]
    df = df.rename(columns={dc: 'date'})
    df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
    m = (df.index >= START) & (df.index <= END); df = df[m]
    if len(df) >= 25: all_data[code] = df

td = sorted(set().union(*[set(df.index) for df in all_data.values()]))
td = [d for d in td if START <= d.strftime('%Y-%m-%d') <= END]
print(f"股池: {len(all_data)}只 / {len(td)}交易日 / 本金HK$ {CASH:,}")

# 回测(关闭恐慌看纯策略, 但克总要的是当前默认配置)
pf_cash = CASH; pos = {}
trades = []
daily_vals = [{'date': td[0].strftime('%Y-%m-%d'), 'value': CASH, 'cash': CASH}]

for date in td:
    ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
    prices = {}
    for code in all_data:
        m = all_data[code].index == date
        if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
    if len(prices) < 5: continue

    # 恐慌检查(当前默认开启)
    if check_panic(tds):
        for code in list(pos.keys()):
            p = prices.get(code)
            if not p: continue
            po = pos[code]; sp = p * (1 - SLIP); tv2 = po['shares'] * sp
            comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
            pnl = (sp - po['cp']) / po['cp'] * 100
            pf_cash += tv2 - comm - stamp - tfee
            trades.append({'date': ds, 'act': '恐慌卖出', 'code': code, 'price': round(p, 2), 'sh': po['shares'],
                          'amt': round(tv2, 0), 'pnl_pct': round(pnl, 1), 'cash': round(pf_cash, 0)})
            del pos[code]
        tv = pf_cash
        for c, po2 in pos.items():
            tv += po2['shares'] * prices.get(c, po2['cp'])
        daily_vals.append({'date': ds, 'value': round(tv, 0), 'cash': round(pf_cash, 0)})
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
    targets = [r for r in ranked if r['score'] >= SCORE_THRESHOLD][:5]
    tc = set(r['code'] for r in targets)
    current_codes = set(pos.keys())

    # 卖出
    for code in list(current_codes):
        if code not in tc:
            p = prices.get(code)
            if not p: continue
            po = pos[code]; sp = p * (1 - SLIP); tv2 = po['shares'] * sp
            comm = max(tv2 * HK_COMM, 5); stamp = tv2 * HK_STAMP; tfee = tv2 * HK_FEE
            pnl = (sp - po['cp']) / po['cp'] * 100
            pf_cash += tv2 - comm - stamp - tfee
            trades.append({'date': ds, 'act': '卖出', 'code': code, 'price': round(p, 2), 'sh': po['shares'],
                          'amt': round(tv2, 0), 'pnl_pct': round(pnl, 1), 'cash': round(pf_cash, 0)})
            del pos[code]
            current_codes.discard(code)

    # 买入
    new = [r for r in targets if r['code'] not in current_codes]
    if new:
        avail = pf_cash * 0.95; per = avail / len(new)
        for r in new:
            bp = r['price'] * (1 + SLIP); sh = int(per / bp / 100) * 100
            if sh < 100: continue
            cost = sh * bp; comm = max(cost * HK_COMM, 5); tfee = cost * HK_FEE
            pf_cash -= cost + comm + tfee
            pos[r['code']] = {'shares': sh, 'cp': bp}
            trades.append({'date': ds, 'act': '买入', 'code': r['code'], 'price': round(r['price'], 2), 'sh': sh,
                          'amt': round(cost, 0), 'pnl_pct': 0, 'cash': round(pf_cash, 0)})

    tv = pf_cash
    for c, po2 in pos.items():
        tv += po2['shares'] * prices.get(c, po2['cp'])
    daily_vals.append({'date': ds, 'value': round(tv, 0), 'cash': round(pf_cash, 0)})

# 输出
print(f"\n{'='*100}")
print("每笔交易明细")
print(f"{'='*100}")
print(f"{'日期':<12} {'动作':<6} {'代码':<7} {'名称':<12} {'价格':>8} {'数量':>6} {'金额':>10} {'盈亏%':>8} {'现金余额':>10}")
print("-" * 100)

hn = {'00700':'腾讯','09988':'阿里','01810':'小米','03690':'美团','09999':'网易',
      '02513':'智谱','00100':'MiniMax','02162':'康诺亚','02616':'基石药业','09969':'诺诚健华',
      '02418':'德银天下','01357':'美图','00981':'中芯','01347':'华虹','00522':'ASMPT',
      '01093':'石药','01177':'中生制药','02338':'潍柴','02038':'富智康','01378':'中国宏桥',
      '00388':'港交所','02388':'中银香港','02318':'中国平安','00939':'建行','02628':'人寿',
      '03988':'中国银行','09888':'百度','02899':'紫金','03993':'洛阳钼业','02618':'京东物流',
      '01929':'周大福','01113':'长实','06181':'老铺','00669':'创科','09660':'地平线'}

for t in trades:
    name = hn.get(t['code'], t['code'])
    print(f"{t['date']:<12} {t['act']:<6} {t['code']:<7} {name:<12} {t['price']:>8.2f} {t['sh']:>6} HK{t['amt']:>9,.0f} {t['pnl_pct']:>+7.1f}% HK{t['cash']:>9,.0f}")

# 最终状态
print(f"\n{'='*70}")
print("最终持仓")
print(f"{'='*70}")
tv_end = pf_cash
print(f"{'代码':<7} {'名称':<12} {'数量':>6} {'成本':>8} {'现价':>8} {'市值':>10} {'盈亏%':>8}")
for code, po in pos.items():
    name = hn.get(code, code)
    # 取最后价格
    last_p = prices.get(code, po['cp']) if 'prices' in dir() else po['cp']
    mv = po['shares'] * last_p
    tv_end += mv
    pnl = (last_p - po['cp']) / po['cp'] * 100
    print(f"{code:<7} {name:<12} {po['shares']:>6} HK{po['cp']:>7.1f} HK{last_p:>7.1f} HK{mv:>9,.0f} {pnl:>+7.1f}%")

print(f"\n现金: HK${pf_cash:,.0f} | 总资产: HK${tv_end:,.0f}")
tp = (tv_end / CASH - 1) * 100
print(f"总盈利: HK${tv_end - CASH:,.0f} ({tp:+.1f}%) | 共{tp/50000*100:.1f}倍")
print(f"交易次数: {len(trades)} (买{sum(1 for t in trades if t['act']=='买入')} 卖{sum(1 for t in trades if t['act']=='卖出')} 恐慌{sum(1 for t in trades if '恐慌' in t['act'])})")

# 月度变化
print(f"\n{'='*70}")
print("月度净值变化")
print(f"{'='*70}")
for i in range(0, len(daily_vals), max(1, len(daily_vals)//12)):
    dv = daily_vals[i]
    mo_chg = (dv['value'] / CASH - 1) * 100
    print(f"  {dv['date']}: HK${dv['value']:,} ({mo_chg:+.1f}%)")

print(f"\n完成!")
