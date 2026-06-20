"""
七星172 动量阈值网格回测
持仓固定4只, 测试不同得分阈值 (0 ~ 0.5)
5年回测: 2021-06-20 ~ 2026-06-20
"""
import numpy as np, pandas as pd, sys, time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'etf'
START_DATE = '2021-06-20'
END_DATE = '2026-06-20'
CASH = 1000000
COMM_RATE = 0.0002
SLIPPAGE = 0.001
LOOKBACK = 25
HN = 4

ETF_POOL_RAW = [
    "sh518880","sz159980","sz159985","sh501018","sz161226","sz159981",
    "sh513100","sz159509","sh513290","sh513500","sz159529",
    "sh513400","sh513520","sh513030","sh513080","sh513310","sh513730",
    "sz159792","sh513130","sh513050","sz159920","sh513690",
    "sh510300","sh510500","sh510050","sh510210","sz159915",
    "sh588080","sh512100","sh563360","sh563300",
    "sh512890","sz159967","sh512040","sz159201","sh562500","sh560090",
    "sh511380","sh511010","sz511220",
]
ETF_POOL = [c[2:] for c in ETF_POOL_RAW]

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(np.maximum(closes, 1e-10))
    mask = ~np.isnan(y) & ~np.isinf(y); x_m, y_m = x[mask], y[mask]
    if len(x_m) < 5: return -999
    sl = np.polyfit(x_m, y_m, 1)[0]; ann = np.exp(sl * 250)
    fitted = sl * x_m + np.polyfit(x_m, y_m, 1)[1]; res = y_m - fitted
    ss = np.sum(res**2); st = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss/st if st > 0 else 0
    return ann * r2

class Portfolio:
    def __init__(self):
        self.cash = CASH; self.positions = {}; self.wins = 0; self.losses = 0; self.daily = []
    @property
    def total_value(self):
        pv = sum(p['s'] * p.get('l', p['cp']) for p in self.positions.values())
        return self.cash + pv
    def update_prices(self, pdict):
        for c, p in pdict.items():
            if c in self.positions: self.positions[c]['l'] = p
    def buy(self, code, shares, price):
        p = price * (1 + SLIPPAGE); tv = shares * p; comm = max(tv * COMM_RATE, 5)
        if tv + comm > self.cash + 0.01: return False
        self.cash -= tv + comm
        if code in self.positions:
            o = self.positions[code]; ts = o['s'] + shares
            self.positions[code] = {'s': ts, 'cp': (o['s']*o['cp']+shares*p)/ts, 'l': p}
        else:
            self.positions[code] = {'s': shares, 'cp': p, 'l': p}
        return True
    def sell(self, code, shares, price):
        if code not in self.positions: return False
        p = price * (1 - SLIPPAGE); pos = self.positions[code]; a = min(shares, pos['s'])
        tv = a * p; comm = max(tv * COMM_RATE, 5)
        pnl = (p - pos['cp']) / pos['cp'] * 100 if pos['cp'] > 0 else 0
        if pnl > 0: self.wins += 1
        else: self.losses += 1
        self.cash += tv - comm
        if a >= pos['s']: del self.positions[code]
        else: self.positions[code]['s'] -= a
        return True
    def codes(self): return list(self.positions.keys())

# Load data once
print('加载数据...', end=' ', flush=True)
all_data = {}
for code in ETF_POOL:
    fp = DATA_DIR / f'{code}.csv'
    if fp.exists():
        df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
        if 'date' not in df.columns or 'close' not in df.columns: continue
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]; df = df[df['close'] > 0]
        if len(df) > 35: all_data[code] = df
trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]
print(f'{len(all_data)}只, {len(trade_dates)}天', flush=True)

def run_backtest(threshold):
    pf = Portfolio()
    for date in trade_dates:
        prices = {}
        for code, df in all_data.items():
            if date in df.index:
                v = df.loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[code] = float(v)
        if len(prices) < HN: continue

        ranked = []
        for code in prices:
            if code not in all_data: continue
            hist = all_data[code][all_data[code].index < date]
            if len(hist) < LOOKBACK: continue
            score = calc_score(hist['close'].values[-LOOKBACK:])
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: x['score'], reverse=True)

        if threshold > 0:
            targets = [r for r in ranked if r['score'] >= threshold][:HN]
        else:
            targets = [r for r in ranked if r['score'] > 0][:HN]

        target_codes = set(r['code'] for r in targets)
        current_codes = set(pf.codes())

        to_sell = current_codes - target_codes
        if threshold > 0:
            for code in list(current_codes):
                found = next((r for r in ranked if r['code'] == code), None)
                if found and found['score'] < threshold:
                    to_sell.add(code)
        for code in to_sell:
            if code in prices:
                pf.sell(code, pf.positions[code]['s'], prices[code])

        pf.update_prices(prices)
        new_targets = [r for r in targets if r['code'] not in pf.positions]
        if new_targets:
            per_new = pf.cash * 0.95 / len(new_targets)
            for r in new_targets:
                if r['code'] not in prices: continue
                shares = int(per_new / r['price'] / 100) * 100
                if shares >= 100:
                    pf.buy(r['code'], shares, r['price'])

        pf.daily.append(pf.total_value)

    dv = pd.Series(pf.daily)
    dr = dv.pct_change().dropna()
    ann = (dv.iloc[-1] / CASH) ** (252 / max(len(dr), 1)) - 1
    dd = (dv / dv.cummax() - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    tt = pf.wins + pf.losses
    wr = pf.wins / tt * 100 if tt > 0 else 0
    return {
        'threshold': threshold,
        'annual': round(ann * 100, 1),
        'dd': round(dd, 1),
        'sharpe': round(sp, 2),
        'win_rate': round(wr, 1),
        'trades': tt,
        'final': dv.iloc[-1],
    }

if __name__ == '__main__':
    print(f'七星172 持仓{HN}只 动量阈值网格回测')
    print(f'{START_DATE} ~ {END_DATE} | {len(ETF_POOL)}只ETF | 方案B')
    print('=' * 85)
    header = f'{"阈值":>6} | {"年化%":>8} | {"回撤%":>7} | {"夏普":>6} | {"胜率%":>5} | {"交易":>5} | {"终值":>14}'
    print(header)
    print('-' * 85)

    results = []
    for th in [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.5]:
        t0 = time.time()
        r = run_backtest(th)
        elapsed = time.time() - t0
        results.append(r)
        th_label = f'{th:.2f}' if th > 0 else ' 0(无)'
        print(f'{th_label:>6} | {r["annual"]:>+7.1f} | {r["dd"]:>7.1f} | {r["sharpe"]:>6.2f} | '
              f'{r["win_rate"]:>5.1f} | {r["trades"]:>5} | {r["final"]:>14,.0f}  ({elapsed:.0f}s)')
        sys.stdout.flush()

    print('=' * 85)
    best = max(results, key=lambda x: x['annual'])
    best_sp = max(results, key=lambda x: x['sharpe'])
    print(f'\n收益最优: 阈值{best["threshold"]} (年化{best["annual"]:+.1f}%)')
    print(f'夏普最优: 阈值{best_sp["threshold"]} (夏普{best_sp["sharpe"]:.2f})')
