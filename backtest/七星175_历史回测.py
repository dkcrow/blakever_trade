"""
七星175 V3.15 历史回测 2023-2026
双risk四格池 + 加权动量 + 多层过滤器 + 盈利保护(止损+黑名单)
"""
import pandas as pd, numpy as np, math, json, warnings
from pathlib import Path
from datetime import datetime
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/etf')
OUT_DIR = Path('reporting/template')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ============ 175池 ============
OVERSEAS_175 = {
    '513100.XSHG':'513100','159509.XSHE':'159509','513290.XSHG':'513290',
    '513500.XSHG':'513500','159529.XSHE':'159529','513400.XSHG':'513400',
    '513520.XSHG':'513520','513030.XSHG':'513030','513080.XSHG':'513080',
    '513310.XSHG':'513310','513730.XSHG':'513730','159792.XSHE':'159792',
    '513130.XSHG':'513130','513050.XSHG':'513050','159920.XSHE':'159920',
    '513690.XSHG':'513690','511380.XSHG':'511380','511010.XSHG':'511010',
    '511220.XSHG':'511220',
}
COMMODITY_175 = {
    '518880.XSHG':'518880','159980.XSHE':'159980','159985.XSHE':'159985',
    '501018.XSHG':'501018','161226.XSHE':'161226','159981.XSHE':'159981',
    '512400.XSHG':'512400',
}
DOMESTIC_175 = {
    '510300.XSHG':'510300','510500.XSHG':'510500','510050.XSHG':'510050',
    '510210.XSHG':'510210','159915.XSHE':'159915','588080.XSHG':'588080',
    '512100.XSHG':'512100','563360.XSHG':'563360','563300.XSHG':'563300',
    '512890.XSHG':'512890','159967.XSHE':'159967','588020.XSHG':'588020',
    '512040.XSHG':'512040','159201.XSHE':'159201',
    '515790.XSHG':'515790','563230.XSHG':'563230','515880.XSHG':'515880',
    '512660.XSHG':'512660','561380.XSHG':'561380','159667.XSHE':'159667',
    '159559.XSHE':'159559','159819.XSHE':'159819','159381.XSHE':'159381',
    '159732.XSHE':'159732','159995.XSHE':'159995','512220.XSHG':'512220',
}
ALL_175_JQ = {}
for d in [OVERSEAS_175, COMMODITY_175, DOMESTIC_175]:
    ALL_175_JQ.update(d)
OVERSEAS_SET = set(OVERSEAS_175.keys())
COMMODITY_SET = set(COMMODITY_175.keys())
DOMESTIC_SET = set(DOMESTIC_175.keys())

A_PROXIES = {'510300.XSHG':'沪深300','510210.XSHG':'上证指数','510050.XSHG':'上证50',
             '159915.XSHE':'创业板指','512100.XSHG':'中证1000','563300.XSHG':'中证2000'}
O_PROXIES = {'159509.XSHE':'纳指科技','513500.XSHG':'标普500','513400.XSHG':'道琼斯','513520.XSHG':'日经'}

# ============ 参数 ============
START, END = '2023-01-01', datetime.now().strftime('%Y-%m-%d')
CASH, COMM, MIN_COMM, TAX, SLIP = 100000, 0.0005, 5, 0.001, 0.0001
LB, HOLDINGS = 25, 1
REGIME_MAX_DAYS = 20
PROFIT_PROTECTION_PCT = 0.05  # 5%回撤止损
INTRADAY_DRAWDOWN_PCT = 0.02  # 2%日内回撤 (仅走弱期)

# ============ 加载数据 ============
data_175 = {}
for jq_code in ALL_175_JQ:
    local = ALL_175_JQ[jq_code]
    fp = DATA_DIR / f'{local}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 30:
            data_175[jq_code] = df
print(f"加载: {len(data_175)}/{len(ALL_175_JQ)} ETFs")

trade_dates = sorted(set().union(*[set(df.index) for df in data_175.values()]))
trade_dates = [d for d in trade_dates if START <= d.strftime('%Y-%m-%d') <= END]
print(f"回测区间: {trade_dates[0].date()} ~ {trade_dates[-1].date()}, {len(trade_dates)}天")

# ============ 得分函数 ============
def score_175(closes):
    """七星175: (exp(slope×250)-1) × R², weighted linspace(1,2), 无未来函数"""
    use = np.array(closes[-LB:].copy(), dtype=float)
    if len(use) < 5 or np.any(use <= 0):
        return -999, 0, 0
    y = np.log(use); x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    W = np.diag(weights)
    X = np.column_stack([np.ones(len(x)), x])
    XtW = X.T @ W
    beta = np.linalg.solve(XtW @ X, XtW @ y)
    intercept, slope = beta[0], beta[1]
    ann_ret = math.exp(slope * 250) - 1
    fitted = intercept + slope * x
    ss_res = np.sum(weights * (y - fitted)**2)
    ss_tot = np.sum(weights * (y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return ann_ret * r2, ann_ret, r2

def check_filters(data_175_jq, code, date, cur_price):
    """175多层过滤器: R²≥0.35, 趋势结构, 短期动量≥0, 近3日无>3%跌"""
    df = data_175_jq.get(code)
    if df is None: return False, "无数据"
    mask = df.index < pd.Timestamp(date)
    hist = df[mask]
    if len(hist) < 15: return False, "数据不足"
    closes = hist['close'].values[-LB:].copy()

    _, _, r2 = score_175(closes)
    if r2 < 0.35: return False, f"R²={r2:.2f}<0.35"

    ma10, ma5 = np.mean(closes[-10:]), np.mean(closes[-5:])
    if cur_price <= ma10: return False, f"价<MA10"
    if ma5 <= ma10: return False, f"MA5<MA10"

    if len(closes) >= 12 and cur_price / closes[-12] < 1: return False, "短期动量负"

    for i in [-1, -2, -3]:
        if -i <= len(closes) and closes[i] / closes[i-1] < 0.97:
            return False, f"近3日跌>3%"

    return True, "OK"

def get_dual_regime(date):
    """双风险判断: 返回 (is_a_weak, is_overseas_weak)"""
    a_break, a_dead = 0, 0
    for code in A_PROXIES:
        if code not in data_175: continue
        df = data_175[code]; m = df.index < pd.Timestamp(date); h = df[m]
        if len(h) < 15: continue
        c = h['close'].values
        if c[-1] < np.mean(c[-10:]): a_break += 1
        if np.mean(c[-5:]) < np.mean(c[-10:]): a_dead += 1
    is_a_weak = a_break >= 3

    o_break, o_dead = 0, 0
    for code in O_PROXIES:
        if code not in data_175: continue
        df = data_175[code]; m = df.index < pd.Timestamp(date); h = df[m]
        if len(h) < 15: continue
        c = h['close'].values
        if c[-1] < np.mean(c[-10:]): o_break += 1
        if np.mean(c[-5:]) < np.mean(c[-10:]): o_dead += 1
    is_o_weak = o_break >= 2

    return is_a_weak, is_o_weak

def get_active_pool(is_a_weak, is_o_weak):
    if is_a_weak and is_o_weak: return list(COMMODITY_SET)
    elif is_a_weak: return list(OVERSEAS_SET) + list(COMMODITY_SET)
    elif is_o_weak: return list(DOMESTIC_SET) + list(COMMODITY_SET)
    else: return list(ALL_175_JQ.keys())

# ============ 回测 ============
class PF:
    def __init__(s): s.cash = CASH; s.pos = {}; s.trades = []; s.dv = []; s.blacklist = set()
    def buy(s, code, shares, price, date, reason=''):
        p = price * (1 + SLIP); tv = shares * p; cf = max(tv * COMM, MIN_COMM)
        if tv + cf > s.cash: return False
        s.cash -= tv + cf
        s.pos[code] = {'shares': shares, 'cost': p, 'bd': date, 'peak_close': price}
        s.trades.append({'date': date, 'action': 'BUY', 'code': code,
                         'shares': shares, 'price': round(p, 4), 'reason': reason})
        return True
    def sell(s, code, shares, price, date, reason=''):
        if code not in s.pos: return False
        p = price * (1 - SLIP); pos = s.pos[code]; a = min(shares, pos['shares'])
        tv = a * p; cf = max(tv * COMM, MIN_COMM); tax = tv * TAX
        s.cash += tv - cf - tax
        pnl = (p - pos['cost']) / pos['cost'] * 100
        s.trades.append({'date': date, 'action': 'SELL', 'code': code,
                         'shares': a, 'price': round(p, 4), 'pnl_pct': round(pnl, 2), 'reason': reason})
        if a >= pos['shares']: del s.pos[code]
        else: s.pos[code]['shares'] -= a
        return True
    def tv(s, prices):
        return s.cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in s.pos.items())
    def check_profit_protection(s, prices, date_str, is_weak):
        """盈利保护: 持仓从近期高点回撤>5%触发止损, 加入当日黑名单防买回"""
        triggered = []
        for code, pos in list(s.pos.items()):
            cur_p = prices.get(code, 0)
            if cur_p <= 0: continue
            if cur_p > pos['peak_close']:
                pos['peak_close'] = cur_p
            dd_pct = (cur_p - pos['peak_close']) / pos['peak_close']
            if dd_pct <= -PROFIT_PROTECTION_PCT:
                s.sell(code, pos['shares'], cur_p, date_str,
                       f'盈利保护({dd_pct*100:.1f}%)')
                s.blacklist.add(code)  # 当日不可买回
                triggered.append(code)
            elif is_weak and dd_pct <= -INTRADAY_DRAWDOWN_PCT:
                s.sell(code, pos['shares'], cur_p, date_str,
                       f'日内回撤({dd_pct*100:.1f}%)')
                s.blacklist.add(code)
                triggered.append(code)
        return triggered

pf = PF()
regime_a, regime_o = False, False; regime_days = 0

for date in trade_dates:
    d_str = date.strftime('%Y-%m-%d')
    pf.blacklist.clear()  # 新交易日清除黑名单
    prices = {}
    for code in data_175:
        m = data_175[code].index == date
        if m.any(): prices[code] = float(data_175[code].loc[date, 'close'])
    if len(prices) < 10: continue

    # 双risk
    a_new, o_new = get_dual_regime(date)
    if regime_a or regime_o:
        regime_days += 1
        if regime_days >= REGIME_MAX_DAYS:
            regime_a = False; regime_o = False; regime_days = 0
        else:
            a_rec, o_rec = 0, 0
            for code in A_PROXIES:
                if code in data_175:
                    df = data_175[code]; m = df.index < pd.Timestamp(date); h = df[m]
                    if len(h) >= 15:
                        c = h['close'].values
                        if np.mean(c[-5:]) > np.mean(c[-6:-1]) and np.mean(c[-10:]) > np.mean(c[-11:-1]):
                            a_rec += 1
            for code in O_PROXIES:
                if code in data_175:
                    df = data_175[code]; m = df.index < pd.Timestamp(date); h = df[m]
                    if len(h) >= 15:
                        c = h['close'].values
                        if np.mean(c[-5:]) > np.mean(c[-6:-1]) and np.mean(c[-10:]) > np.mean(c[-11:-1]):
                            o_rec += 1
            if a_rec >= 4: regime_a = False
            if o_rec >= 3: regime_o = False
            if not regime_a and not regime_o: regime_days = 0
    else:
        regime_a, regime_o = a_new, o_new

    active = get_active_pool(regime_a, regime_o)

    # 先执行盈利保护 (在排名之前, 被止损的ETF加入黑名单, 当天不参与排名)
    is_weak_now = regime_a or regime_o
    pf.check_profit_protection(prices, d_str, is_weak_now)

    ranked = []
    for code in active:
        if code not in prices or code not in data_175: continue
        if code in pf.blacklist: continue  # 当日黑名单跳过
        mask = data_175[code].index < pd.Timestamp(date)
        hist = data_175[code][mask]
        if len(hist) < LB + 10: continue
        hp = hist['close'].values[-LB:].copy()
        if hp.min() <= 0: continue
        s, ann, r2 = score_175(hp)
        ok, reason = check_filters(data_175, code, date, prices[code])
        if ok and s > 0:
            ranked.append({'code': code, 'score': s, 'ann_ret': ann, 'r2': r2, 'price': prices[code],
                          'local': ALL_175_JQ.get(code, code), 'reason': reason})

    ranked.sort(key=lambda x: x['score'], reverse=True)
    targets = [r['code'] for r in ranked[:HOLDINGS]] if ranked else []
    target_set = set(targets)

    for code in list(pf.pos.keys()):
        if code not in target_set and code in prices:
            pf.sell(code, pf.pos[code]['shares'], prices[code], d_str, '轮动')
    for code in targets:
        if code not in pf.pos and code in prices:
            tv = pf.tv(prices) * 0.95 / max(len(targets), 1)
            s = int(tv / prices[code] / 100) * 100
            if s > 0: pf.buy(code, s, prices[code], d_str, '175动量')

    pf.dv.append({'date': d_str, 'value': pf.tv(prices)})

# ============ 统计 ============
dv = pd.DataFrame(pf.dv)
tr = (dv['value'].iloc[-1] / CASH - 1) * 100
dr = dv['value'].pct_change().dropna()
ar = (1 + dr.mean())**252 - 1
vm = dv['value']
md = (vm / vm.cummax() - 1).min() * 100
sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
sells = [t for t in pf.trades if t['action'] == 'SELL']
wr = sum(1 for t in sells if t.get('pnl_pct', 0) > 0) / max(len(sells), 1) * 100

print(f"\n===== 七星175 V3.15 回测 =====")
print(f"累计: {tr:+.2f}% | 年化: {ar*100:.1f}% | 回撤: {md:.1f}% | 夏普: {sp:.2f}")
print(f"交易: {len(pf.trades)}笔 (买{sum(1 for t in pf.trades if t['action']=='BUY')}/卖{sum(1 for t in pf.trades if t['action']=='SELL')}) | 胜率: {wr:.1f}%")

for year in [2023, 2024, 2025, 2026]:
    yd = dv[dv['date'].str.startswith(str(year))]
    if len(yd) < 2: continue
    yr = (yd['value'].iloc[-1] / yd['value'].iloc[0] - 1) * 100
    print(f"  {year}: {yr:+.2f}% ({len(yd)}天)")

# ============ 保存交易记录 ============
# 格式化为可读形式
trades_for_report = []
for t in pf.trades:
    local_code = ALL_175_JQ.get(t['code'], t['code'])
    trades_for_report.append({
        'date': t['date'],
        'action': t['action'],
        'code': local_code,
        'shares': t['shares'],
        'price': t['price'],
        'pnl_pct': t.get('pnl_pct', 0),
        'reason': t.get('reason', ''),
    })

# 保存完整记录
out_file = OUT_DIR / '七星175_交易记录.json'
with open(out_file, 'w', encoding='utf-8') as f:
    json.dump({
        'strategy': '七星175 V3.15',
        'period': f'{trade_dates[0].date()} ~ {trade_dates[-1].date()}',
        'stats': {
            'total_return': round(tr, 2),
            'annual_return': round(ar * 100, 1),
            'max_drawdown': round(md, 1),
            'sharpe': round(sp, 2),
            'total_trades': len(pf.trades),
            'win_rate': round(wr, 1),
        },
        'trades': trades_for_report,
    }, f, ensure_ascii=False, indent=2)

print(f"\n交易记录保存: {out_file} ({len(trades_for_report)}笔)")
