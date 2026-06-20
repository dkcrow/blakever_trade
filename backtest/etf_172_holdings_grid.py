"""
七星172 持股数网格回测
测试不同持仓数量 (1~8只) 对策略表现的影响
5年回测: 2021-06-20 ~ 2026-06-20
"""
import numpy as np, pandas as pd, sys, time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'etf'
START_DATE = '2021-06-20'
END_DATE = '2026-06-20'
CASH = 1000000  # ¥100万
COMM_RATE = 0.0002  # 0.02% 佣金
SLIPPAGE = 0.001    # 0.1% 滑点
LOOKBACK = 25

# 172 ETF 池 (40只)
ETF_POOL_RAW = [
    "sh518880", "sz159980", "sz159985", "sh501018", "sz161226", "sz159981",
    "sh513100", "sz159509", "sh513290", "sh513500", "sz159529",
    "sh513400", "sh513520", "sh513030", "sh513080", "sh513310", "sh513730",
    "sz159792", "sh513130", "sh513050", "sz159920", "sh513690",
    "sh510300", "sh510500", "sh510050", "sh510210", "sz159915",
    "sh588080", "sh512100", "sh563360", "sh563300",
    "sh512890", "sz159967", "sh512040", "sz159201", "sh562500", "sh560090",
    "sh511380", "sh511010", "sz511220",
]
ETF_NAMES = {
    '518880': '黄金ETF', '159980': '有色ETF', '159985': '豆粕ETF',
    '501018': '原油LOF', '161226': '白银LOF', '159981': '能化ETF',
    '513100': '纳指ETF', '159509': '纳指科技', '513290': '纳指生科',
    '513500': '标普500', '159529': '标普消费', '513400': '道琼斯',
    '513520': '日经ETF', '513030': '德国ETF', '513080': '法国ETF',
    '513310': '中韩半导', '513730': '东南亚科',
    '159792': '港互联网', '513130': '恒生科技', '513050': '中概互联',
    '159920': '恒生ETF', '513690': '港红利',
    '510300': '沪深300', '510500': '中证500', '510050': '上证50',
    '510210': '上证指数', '159915': '创业板',
    '588080': '科创50', '512100': '中证1000', '563360': 'A500ETF',
    '563300': '中证2000',
    '512890': '红利低波', '159967': '创业成长', '512040': '价值100',
    '159201': '自由现金', '562500': '机器人', '560090': '证券ETF',
    '511380': '可转债', '511010': '国债ETF', '511220': '城投债',
}
# 提取纯代码
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
    def __init__(self, cash=CASH):
        self.cash = cash; self.positions = {}; self.daily_values = []
        self.wins = 0; self.losses = 0
    @property
    def total_value(self):
        pv = sum(p['shares'] * p.get('lp', p['cp']) for p in self.positions.values())
        return self.cash + pv
    def update_prices(self, prices):
        for c, p in prices.items():
            if c in self.positions: self.positions[c]['lp'] = p
    def buy(self, code, shares, price):
        p = price * (1 + SLIPPAGE); tv = shares * p
        comm = max(tv * COMM_RATE, 5)
        if tv + comm > self.cash + 0.01: return False
        self.cash -= tv + comm
        if code in self.positions:
            o = self.positions[code]; ts = o['shares'] + shares
            self.positions[code] = {'shares': ts, 'cp': (o['shares']*o['cp']+shares*p)/ts, 'lp': p}
        else:
            self.positions[code] = {'shares': shares, 'cp': p, 'lp': p}
        return True
    def sell(self, code, shares, price):
        if code not in self.positions: return False
        p = price * (1 - SLIPPAGE); pos = self.positions[code]
        a = min(shares, pos['shares']); tv = a * p
        comm = max(tv * COMM_RATE, 5)
        pnl = (p - pos['cp']) / pos['cp'] * 100 if pos['cp'] > 0 else 0
        if pnl > 0: self.wins += 1
        else: self.losses += 1
        self.cash += tv - comm
        if a >= pos['shares']: del self.positions[code]
        else: self.positions[code]['shares'] -= a
        return True
    def codes(self): return list(self.positions.keys())

def run_backtest(holdings_num, score_threshold=0):
    """Run 172 strategy with given holdings_num. Returns dict of metrics."""
    # Load data
    all_data = {}
    for code in ETF_POOL:
        fp = DATA_DIR / f'{code}.csv'
        if fp.exists():
            df = pd.read_csv(fp)
            df.columns = [c.lower() for c in df.columns]
            if 'date' not in df.columns or 'close' not in df.columns: continue
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            df = df[df['close'] > 0]
            if len(df) > 35: all_data[code] = df

    trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
    trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]

    pf = Portfolio()
    hn = holdings_num

    for date in trade_dates:
        prices = {}
        for code, df in all_data.items():
            if date in df.index:
                v = df.loc[date, 'close']
                if hasattr(v, 'iloc'): v = v.iloc[0]
                if float(v) > 0: prices[code] = float(v)
        if len(prices) < hn: continue

        # Rank by momentum
        ranked = []
        for code in prices:
            if code not in all_data: continue
            hist = all_data[code][all_data[code].index < date]
            if len(hist) < LOOKBACK: continue
            score = calc_score(hist['close'].values[-LOOKBACK:])
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: x['score'], reverse=True)

        # Apply score threshold + top N
        if score_threshold > 0:
            targets = [r for r in ranked if r['score'] >= score_threshold][:hn]
        else:
            targets = [r for r in ranked if r['score'] > 0][:hn]

        target_codes = set(r['code'] for r in targets)
        current_codes = set(pf.codes())

        # Sell: positions not in targets or below threshold
        to_sell = current_codes - target_codes
        if score_threshold > 0:
            for code in list(current_codes):
                found = next((r for r in ranked if r['code'] == code), None)
                if found and found['score'] < score_threshold:
                    to_sell.add(code)
        for code in to_sell:
            if code in prices:
                pf.sell(code, pf.positions[code]['shares'], prices[code])

        # Buy: 方案B (available cash allocation)
        pf.update_prices(prices)
        new_targets = [r for r in targets if r['code'] not in pf.positions]
        if new_targets:
            per_new = pf.cash * 0.95 / len(new_targets)
            for r in new_targets:
                if r['code'] not in prices: continue
                shares = int(per_new / r['price'] / 100) * 100  # 整手100
                if shares >= 100:
                    pf.buy(r['code'], shares, r['price'])

        pf.daily_values.append({'date': date.strftime('%Y-%m-%d'), 'value': pf.total_value})

    # Calculate metrics
    dv = pd.DataFrame(pf.daily_values)
    if len(dv) < 10:
        return None

    final = dv['value'].iloc[-1]
    dr = dv['value'].pct_change().dropna()
    n_days = len(dr)
    ann_ret = (final / CASH) ** (252 / max(n_days, 1)) - 1
    max_dd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    total_trades = pf.wins + pf.losses
    win_rate = pf.wins / total_trades * 100 if total_trades > 0 else 0

    return {
        'holdings': hn,
        'threshold': score_threshold,
        'total_return': (final / CASH - 1) * 100,
        'annual': ann_ret * 100,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'trades': total_trades,
        'final': final,
        'days': n_days,
    }

if __name__ == '__main__':
    print(f'七星172 持股数网格回测')
    print(f'{START_DATE} ~ {END_DATE} | 40只ETF池 | ¥100万 | 方案B仓位管理')
    print(f'佣金0.02% | 滑点0.1% | 25日动量 | 整手100股')
    print('='*95)

    results = []

    # Test holdings 1 through 8
    for hn in [1, 2, 3, 4, 5, 6, 7, 8]:
        t0 = time.time()
        r = run_backtest(hn, score_threshold=0)
        elapsed = time.time() - t0
        if r:
            results.append(r)
            print(f'  持仓{hn}只: 年化{r["annual"]:+.1f}% | 回撤{r["max_dd"]:.1f}% | '
                  f'夏普{r["sharpe"]:.2f} | 胜率{r["win_rate"]:.1f}% | '
                  f'交易{r["trades"]}次 | 终值¥{r["final"]:,.0f} | {elapsed:.1f}s')
            sys.stdout.flush()
        else:
            print(f'  持仓{hn}只: 数据不足')

    print('='*95)
    print()

    # Summary table
    print(f'{"持仓":>4} | {"累计%":>8} | {"年化%":>8} | {"回撤%":>7} | {"夏普":>6} | {"胜率%":>5} | {"交易":>5} | {"终值(¥)":>14}')
    print('-'*80)
    for r in results:
        print(f'{r["holdings"]:>4} | {r["total_return"]:>+7.1f} | {r["annual"]:>+7.1f} | '
              f'{r["max_dd"]:>7.1f} | {r["sharpe"]:>6.2f} | {r["win_rate"]:>5.1f} | '
              f'{r["trades"]:>5} | {r["final"]:>14,.0f}')

    # Find best
    if results:
        best_ann = max(results, key=lambda x: x['annual'])
        best_sharpe = max(results, key=lambda x: x['sharpe'])
        print(f'\n收益最优: {best_ann["holdings"]}只 (年化{best_ann["annual"]:+.1f}%)')
        print(f'夏普最优: {best_sharpe["holdings"]}只 (夏普{best_sharpe["sharpe"]:.2f})')

    # Also test score>=0.5 for the top 3 best holding counts
    print('\n' + '='*95)
    print('  加入 score>=0.5 阈值对比')
    print('='*95)
    top3 = sorted(results, key=lambda x: x['annual'], reverse=True)[:3]
    for r in top3:
        hn = r['holdings']
        t0 = time.time()
        r2 = run_backtest(hn, score_threshold=0.5)
        elapsed = time.time() - t0
        if r2:
            diff = r2['annual'] - r['annual']
            print(f'  持仓{hn}只+阈值: 年化{r2["annual"]:+.1f}% (vs无阈值{r["annual"]:+.1f}%, 差{diff:+.1f}%) | '
                  f'回撤{r2["max_dd"]:.1f}% | 夏普{r2["sharpe"]:.2f} | {elapsed:.1f}s')
            sys.stdout.flush()
