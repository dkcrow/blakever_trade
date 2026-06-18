"""七星175回撤诊断"""
import pandas as pd, numpy as np, math, json, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/etf')

ALL_175_JQ = {}
for d in [
    {'513100.XSHG':'513100','159509.XSHE':'159509','513290.XSHG':'513290','513500.XSHG':'513500',
     '159529.XSHE':'159529','513400.XSHG':'513400','513520.XSHG':'513520','513030.XSHG':'513030',
     '513080.XSHG':'513080','513310.XSHG':'513310','513730.XSHG':'513730','159792.XSHE':'159792',
     '513130.XSHG':'513130','513050.XSHG':'513050','159920.XSHE':'159920','513690.XSHG':'513690',
     '511380.XSHG':'511380','511010.XSHG':'511010','511220.XSHG':'511220'},
    {'518880.XSHG':'518880','159980.XSHE':'159980','159985.XSHE':'159985','501018.XSHG':'501018',
     '161226.XSHE':'161226','159981.XSHE':'159981','512400.XSHG':'512400'},
    {'510300.XSHG':'510300','510500.XSHG':'510500','510050.XSHG':'510050','510210.XSHG':'510210',
     '159915.XSHE':'159915','588080.XSHG':'588080','512100.XSHG':'512100','563360.XSHG':'563360',
     '563300.XSHG':'563300','512890.XSHG':'512890','159967.XSHE':'159967','588020.XSHG':'588020',
     '512040.XSHG':'512040','159201.XSHE':'159201','515790.XSHG':'515790','563230.XSHG':'563230',
     '515880.XSHG':'515880','512660.XSHG':'512660','561380.XSHG':'561380','159667.XSHE':'159667',
     '159559.XSHE':'159559','159819.XSHE':'159819','159381.XSHE':'159381','159732.XSHE':'159732',
     '159995.XSHE':'159995','512220.XSHG':'512220'},
]: ALL_175_JQ.update(d)

OVERSEAS_SET = set(k for k in ALL_175_JQ if ALL_175_JQ[k] in
    ['513100','159509','513290','513500','159529','513400','513520','513030','513080',
     '513310','513730','159792','513130','513050','159920','513690','511380','511010','511220'])
COMMODITY_SET = set(k for k in ALL_175_JQ if ALL_175_JQ[k] in
    ['518880','159980','159985','501018','161226','159981','512400'])

data_175 = {}
for jq_code, local in ALL_175_JQ.items():
    fp = DATA_DIR / f'{local}.csv'
    if fp.exists():
        df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        if len(df) > 30: data_175[jq_code] = df

print(f"加载: {len(data_175)} ETFs")

trade_dates = sorted(set().union(*[set(df.index) for df in data_175.values()]))
trade_dates = [d for d in trade_dates if '2023-01-01' <= d.strftime('%Y-%m-%d') <= '2026-06-03']
print(f"日期: {trade_dates[0].date()} ~ {trade_dates[-1].date()}, {len(trade_dates)}天")

LB, CASH, COMM, MIN_COMM, TAX, SLIP = 25, 100000, 0.0005, 5, 0.001, 0.0001

def score_175(closes):
    use = np.array(closes[-LB:].copy(), dtype=float)
    if len(use) < 5 or np.any(use <= 0): return -999, 0, 0
    y = np.log(use); x = np.arange(len(y)); w = np.linspace(1, 2, len(y))
    W = np.diag(w); X = np.column_stack([np.ones(len(x)), x])
    XtW = X.T @ W; beta = np.linalg.solve(XtW @ X, XtW @ y)
    slope = beta[1]; ann = math.exp(slope*250)-1
    fitted = beta[0] + slope*x
    ss_res = np.sum(w*(y-fitted)**2); ss_tot = np.sum(w*(y-np.mean(y))**2)
    r2 = 1-ss_res/ss_tot if ss_tot>0 else 0
    return ann*r2, ann, r2

def check_filters(code, date, cur_price):
    df = data_175.get(code)
    if df is None: return False, "无数据"
    mask = df.index < pd.Timestamp(date); hist = df[mask]
    if len(hist) < 15: return False, "数据不足"
    closes = hist['close'].values[-LB:].copy()
    _, _, r2 = score_175(closes)
    if r2 < 0.35: return False, f"R²={r2:.2f}"
    ma10, ma5 = np.mean(closes[-10:]), np.mean(closes[-5:])
    if cur_price <= ma10: return False, "价<MA10"
    if ma5 <= ma10: return False, "MA5<MA10"
    if len(closes)>=12 and cur_price/closes[-12] < 1: return False, "短动负"
    for i in [-1,-2,-3]:
        if -i <= len(closes) and closes[i]/closes[i-1] < 0.97: return False, "3日跌>3%"
    return True, "OK"

A_PROXIES = ['510300.XSHG','510210.XSHG','510050.XSHG','159915.XSHE','512100.XSHG','563300.XSHG']
O_PROXIES = ['159509.XSHE','513500.XSHG','513400.XSHG','513520.XSHG']

def get_regime(date):
    a_break = 0
    for c in A_PROXIES:
        if c in data_175:
            df = data_175[c]; m = df.index < date; h = df[m]
            if len(h) >= 15 and h['close'].iloc[-1] < np.mean(h['close'].values[-10:]):
                a_break += 1
    o_break = 0
    for c in O_PROXIES:
        if c in data_175:
            df = data_175[c]; m = df.index < date; h = df[m]
            if len(h) >= 15 and h['close'].iloc[-1] < np.mean(h['close'].values[-10:]):
                o_break += 1
    return a_break >= 3, o_break >= 2

def active_pool(a, o):
    if a and o: return list(COMMODITY_SET)
    elif a: return list(OVERSEAS_SET) + list(COMMODITY_SET)
    elif o: return list(set(ALL_175_JQ.keys()) - OVERSEAS_SET)
    return list(ALL_175_JQ.keys())

class PF:
    def __init__(self): self.cash = CASH; self.pos = {}; self.trades = []; self.dv = []
    def buy(self, code, sh, p, d, rs=''):
        p_buy = p * (1 + SLIP); tv = sh * p_buy; cf = max(tv * COMM, MIN_COMM)
        if tv + cf > self.cash: return False
        self.cash -= tv + cf
        self.pos[code] = {'shares': sh, 'cost': p_buy, 'buy_date': d}
        self.trades.append({'date': d, 'action': 'BUY', 'code': code, 'shares': sh,
                           'price': round(p_buy, 4), 'reason': rs})
        return True
    def sell(self, code, sh, p, d, rs=''):
        if code not in self.pos: return False
        p_sell = p * (1 - SLIP); pos = self.pos[code]; a = min(sh, pos['shares'])
        tv = a * p_sell; cf = max(tv * COMM, MIN_COMM); tax = tv * TAX
        self.cash += tv - cf - tax
        pnl = (p_sell - pos['cost']) / pos['cost'] * 100
        self.trades.append({'date': d, 'action': 'SELL', 'code': code, 'shares': a,
                           'price': round(p_sell, 4), 'pnl_pct': round(pnl, 2), 'reason': rs})
        if a >= pos['shares']: del self.pos[code]
        else: self.pos[code]['shares'] -= a
        return True
    def total_value(self, prices):
        pv = sum(p['shares'] * prices.get(c, p['cost']) for c, p in self.pos.items())
        return self.cash + pv

pf = PF(); regime_a = False; regime_o = False; regime_days = 0

for date in trade_dates:
    d_str = date.strftime('%Y-%m-%d')
    prices = {c: float(data_175[c].loc[date, 'close']) for c in data_175 if date in data_175[c].index}
    if len(prices) < 10: continue

    a_new, o_new = get_regime(date)
    if regime_a or regime_o:
        regime_days += 1
        if regime_days >= 20:
            regime_a = regime_o = False; regime_days = 0
        else:
            a_rec = o_rec = 0
            for c in A_PROXIES:
                if c in data_175:
                    df = data_175[c]; h = df[df.index < date]
                    if len(h) >= 15:
                        cv = h['close'].values
                        if np.mean(cv[-5:]) > np.mean(cv[-6:-1]) and np.mean(cv[-10:]) > np.mean(cv[-11:-1]):
                            a_rec += 1
            for c in O_PROXIES:
                if c in data_175:
                    df = data_175[c]; h = df[df.index < date]
                    if len(h) >= 15:
                        cv = h['close'].values
                        if np.mean(cv[-5:]) > np.mean(cv[-6:-1]) and np.mean(cv[-10:]) > np.mean(cv[-11:-1]):
                            o_rec += 1
            if a_rec >= 4: regime_a = False
            if o_rec >= 3: regime_o = False
            if not regime_a and not regime_o: regime_days = 0
    else:
        regime_a, regime_o = a_new, o_new

    active = active_pool(regime_a, regime_o)
    ranked = []
    for code in active:
        if code not in prices or code not in data_175: continue
        m = data_175[code].index < pd.Timestamp(date); h = data_175[code][m]
        if len(h) < LB + 10: continue
        hp = h['close'].values[-LB:].copy()
        if hp.min() <= 0: continue
        s, ann, r2 = score_175(hp)
        ok, reason = check_filters(code, date, prices[code])
        if ok and s > 0:
            ranked.append({'code': code, 'score': s, 'ann': ann, 'r2': r2, 'price': prices[code]})

    ranked.sort(key=lambda x: x['score'], reverse=True)
    targets = [r['code'] for r in ranked[:1]] if ranked else []
    target_set = set(targets)

    for c in list(pf.pos.keys()):
        if c not in target_set and c in prices:
            pf.sell(c, pf.pos[c]['shares'], prices[c], d_str, '轮动')
    for c in targets:
        if c not in pf.pos and c in prices:
            tv = pf.total_value(prices) * 0.95
            shares = int(tv / prices[c] / 100) * 100
            if shares > 0:
                pf.buy(c, shares, prices[c], d_str, '175')

    pf.dv.append({'date': d_str, 'value': pf.total_value(prices)})

# Stats
dv = pd.DataFrame(pf.dv)
vm = dv['value']; cm = vm.cummax(); dd = (vm - cm) / cm * 100
max_dd = dd.min(); dd_idx = dd.idxmin()
peak_idx = vm.iloc[:dd_idx].idxmax()

print(f"\n最大回撤: {max_dd:.1f}%")
print(f"高点: {dv.iloc[peak_idx]['date']} ¥{vm.iloc[peak_idx]:,.0f}")
print(f"低点: {dv.iloc[dd_idx]['date']} ¥{vm.iloc[dd_idx]:,.0f}")

# 找出所有>15%的回撤段
print("\n=== 大幅回撤段 (>15%) ===")
for i in range(1, len(dv)):
    if dd.iloc[i] <= -15 and dd.iloc[i-1] > -15:
        # 找到这段的最高点
        seg_peak_idx = vm.iloc[:i].idxmax()
        print(f"  {dv.iloc[seg_peak_idx]['date']} → {dv.iloc[i]['date']}: 从¥{vm.iloc[seg_peak_idx]:,.0f}跌至¥{vm.iloc[i]:,.0f} ({dd.iloc[i]:.1f}%)")

# 最大亏损卖出
sells = [t for t in pf.trades if t['action'] == 'SELL']
sells_sorted = sorted(sells, key=lambda x: x.get('pnl_pct', 0))
print(f"\n=== 最大亏损卖出 Top15 ===")
for t in sells_sorted[:15]:
    print(f"  {t['date']} {ALL_175_JQ.get(t['code'],t['code']):8s} pnl={t.get('pnl_pct',0):+.1f}%  {t.get('reason','')}")

# 按年统计
print(f"\n=== 分年统计 ===")
dr = dv['value'].pct_change().dropna()
for year in [2023, 2024, 2025, 2026]:
    yd = dv[dv['date'].str.startswith(str(year))]
    if len(yd) < 2: continue
    yr = (yd['value'].iloc[-1] / yd['value'].iloc[0] - 1) * 100
    print(f"  {year}: {yr:+.2f}% ({len(yd)}天)")
