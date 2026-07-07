"""
七星QMT 行情判断验证: 沪深300(510300)跌破MA → 转投国债ETF(511010)
1/3/5年回测, MA: 5/10/15/20/25/200/250日
"""
import sys, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
A_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'

# QMT ETF池 (50只)
QMT_RAW = ['510050','510300','510500','510880','512010','512070','512100','512170','512400','512660',
           '512690','512720','512760','512800','512880','513100','513180','513500','515050','515790',
           '515880','516020','516480','516970','517090','518880','561300','562800','563300','588000',
           '588090','588160','588200','159509','159561','159605','159611','159612','159766','159828',
           '159847','159863','159865','159869','159883','159915','159919','159941','159967','159985']
QMT_POOL = ['sh' + c if c.startswith('5') else 'sz' + c for c in QMT_RAW]
HN = 1; COMM = 0.0002; SLIP = 0.0001

def calc_score(df_slice):
    x_m = np.arange(len(df_slice))
    if hasattr(df_slice, 'values'): df_slice = df_slice.values
    y_m = np.log(np.maximum(df_slice, 1e-10))
    mask = ~(np.isnan(y_m) | np.isinf(y_m)); x_m = x_m[mask]; y_m = y_m[mask]
    w = np.linspace(1, 2, len(x_m))
    slope, _ = np.polyfit(x_m, y_m, 1, w=w); ann = np.exp(slope * 250)
    fitted = slope * x_m + _; res = y_m - fitted
    ss_res = np.sum(w * res ** 2); ss_tot = np.sum(w * (y_m - np.mean(y_m)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return (ann - 1) * r2

# 加载 ETF 数据
print("加载ETF数据...")
all_data = {}
for code in QMT_POOL:
    raw = code.replace('sh','').replace('sz','')
    fp = A_DIR / f'{raw}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        rmap = {}
        for c in df.columns:
            cl = c.lower().strip()
            if cl == 'date' and c != 'date': rmap[c] = 'date'
            elif cl == 'close' and c != 'close': rmap[c] = 'close'
        if rmap: df = df.rename(columns=rmap)
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        if len(df) > 35: all_data[code] = df
    except Exception:
        pass
print(f"  有效: {len(all_data)}/{len(QMT_POOL)}")

# 510300 + 511010
df_300 = pd.read_csv(A_DIR / '510300.csv')
df_300 = df_300.rename(columns={'Date': 'date', 'Close': 'close'})
df_300['date'] = pd.to_datetime(df_300['date']); df_300 = df_300.set_index('date').sort_index()
hs300 = df_300['close']

df_bond = pd.read_csv(A_DIR / '511010.csv')
df_bond = df_bond.rename(columns={'Date': 'date', 'Close': 'close'})
df_bond['date'] = pd.to_datetime(df_bond['date']); df_bond = df_bond.set_index('date').sort_index()
bond = df_bond['close']
print(f"510300: {len(hs300)}条 {hs300.index[0].date()}~{hs300.index[-1].date()}")
print(f"511010: {len(bond)}条 {bond.index[0].date()}~{bond.index[-1].date()}")

def check_hs300_below(dt, ma):
    m = hs300.index <= dt; h = hs300.loc[m]
    return len(h) >= ma and float(h.iloc[-1]) < float(h.iloc[-ma:].mean())

def get_bond_price(dt):
    """获取511010最近价格(含当日)"""
    m = bond.index <= dt; h = bond.loc[m]
    return float(h.iloc[-1]) if len(h) > 0 else None

# 回测
class State:
    def __init__(self): self.cash = 1_000_000; self.pos = {}; self.log = []; self.in_bond = False
    @property
    def tv(self):
        pv = sum(p['shares'] * p['lp'] for p in self.pos.values())
        return self.cash + pv

def run(all_data, trade_dates, ma=0):
    s = State(); warn_days = 0
    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])
        if len(prices) < 5: continue

        # 行情判断
        if ma > 0:
            is_bear = check_hs300_below(tds, ma)
            if is_bear and not s.in_bond:
                # 卖出所有 ETF → 买入国债
                warn_days += 1
                for code in list(s.pos.keys()):
                    p = prices.get(code)
                    if not p: continue
                    tv2 = s.pos[code]['shares'] * p
                    comm = max(tv2 * COMM, 5); s.cash += tv2 - comm
                    del s.pos[code]
                bp = get_bond_price(tds)
                if bp:
                    sh = int(s.cash / bp / 100) * 100
                    if sh >= 100:
                        cost = sh * bp; comm = max(cost * COMM, 5)
                        s.cash -= cost + comm
                        s.pos['511010'] = {'shares': sh, 'lp': bp, 'cp': bp}
                        s.in_bond = True
                continue

            if not is_bear and s.in_bond:
                # 国债转回 → 恢复正常
                p = get_bond_price(tds)
                if p and '511010' in s.pos:
                    tv2 = s.pos['511010']['shares'] * p
                    comm = max(tv2 * COMM, 5); s.cash += tv2 - comm
                    del s.pos['511010']
                    s.in_bond = False
                # fall through to normal trading

            if s.in_bond:
                continue  # 持有国债日, 不调仓

        # 正常QMT排名调仓 (仅1只)
        scores = []
        for code, df in all_data.items():
            if code not in prices: continue
            m_rank = df.index < tds; hist = df[m_rank]
            if len(hist) < 26: continue
            score = calc_score(hist['close'].values[-25:])
            scores.append((code, score, prices[code]))
        scores.sort(key=lambda x: -x[1])
        targets = scores[:1]  # QMT持仓1只

        tc = set(t[0] for t in targets)
        for code in list(s.pos.keys()):
            if code == '511010': continue
            if code not in tc:
                p = prices.get(code)
                if not p: continue
                tv2 = s.pos[code]['shares'] * p
                comm = max(tv2 * COMM, 5)
                pnl = (p - s.pos[code]['cp']) / s.pos[code]['cp'] * 100
                s.cash += tv2 - comm; del s.pos[code]
                s.log.append({'date': ds, 'code': code, 'pnl': round(pnl, 2)})

        for sym, score, price in targets:
            if sym in s.pos: continue
            available = s.cash * 0.98
            sh = int(available / price / 100) * 100
            if sh < 100: continue
            bp = price * (1 + SLIP); cost = sh * bp; comm = max(cost * COMM, 5)
            s.cash -= cost + comm
            s.pos[sym] = {'shares': sh, 'lp': price, 'cp': bp}

    # 终值
    total = s.cash
    for code, pos in s.pos.items():
        total += pos['shares'] * pos['lp']
    return total, s.log, warn_days

# 回测
periods = [('1年','2025-06-26','2026-06-26'),('3年','2023-06-26','2026-06-26'),('5年','2021-06-26','2026-06-26')]
mas = [5, 10, 15, 20, 25, 200, 250]

for pn, start, end in periods:
    print(f'\n{"="*60}')
    print(f'[{pn}] {start}~{end}')
    # 过滤数据
    period_data = {}
    for code, df in list(all_data.items()):
        m = (df.index >= start) & (df.index <= end)
        df2 = df[m]
        if len(df2) >= 25: period_data[code] = df2
    
    td_all = sorted(set().union(*[set(df.index) for df in period_data.values()]))
    td = [d for d in td_all if start <= d.strftime('%Y-%m-%d') <= end]
    print(f'  {len(period_data)}只 / {len(td)}交易日')
    
    # 关闭基线
    tv0, _, _ = run(period_data, td, 0)
    r0 = (tv0 / 1_000_000 - 1) * 100
    print(f'  关闭:     +{r0:.1f}%')

    for ma in mas:
        tv, logs, wd = run(period_data, td, ma)
        r = (tv / 1_000_000 - 1) * 100
        m = ' ★' if r > r0 else ''
        print(f'  HS300{ma:3d}日: +{r:.1f}% 避险{wd}天{m}')

print('\n完成!')
