"""
七星美股版 精简27只 3年回测 — 生成交易记录
纯动量, 无未来函数, 日频调仓, 7只等权
零后视镜偏见 — 仅从40只删除13只低贡献/占位
"""
import pandas as pd, numpy as np, math, json, warnings
from pathlib import Path
from datetime import datetime
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/us')
OUT_DIR = Path('backtest/results_us100')
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRIM27 = ['NVDA','AVGO','AMD','MU','LRCX','ARM','LITE',
    'NFLX','GOOGL','NOW','CRWD','ORCL',
    'DDOG','SNPS','EOG','OKE','NEM','FCX',
    'CAT','GE','RTX','AMT','PANW','ZS','NET','IONQ','RKLB']

LB, HN, CASH = 25, 7, 100000
SLIP, COMM = 0.0005, 0.005

def load_data():
    data = {}
    for s in TRIM27:
        fp = DATA_DIR / f'{s}.csv'
        if fp.exists():
            df = pd.read_csv(fp)
            df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            if len(df) > 60: data[s] = df
    return data

def score_qx(closes):
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_res = np.sum(res**2); ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return ann * r2

class PF:
    def __init__(s): s.cash = CASH; s.pos = {}; s.trades = []; s.dv = []
    def buy(s, code, shares, price, date, reason=''):
        p = price * (1 + SLIP); tv = shares * p; cf = shares * COMM
        if tv + cf > s.cash: return False
        s.cash -= tv + cf
        s.pos[code] = {'shares': shares, 'cost': p, 'bd': date}
        s.trades.append({'date': date, 'action': 'BUY', 'code': code,
                         'shares': shares, 'price': round(p, 4), 'reason': reason})
        return True
    def sell(s, code, shares, price, date, reason=''):
        if code not in s.pos: return False
        p = price * (1 - SLIP); pos = s.pos[code]; a = min(shares, pos['shares'])
        tv = a * p; cf = a * COMM
        s.cash += tv - cf; pnl = (p - pos['cost']) / pos['cost'] * 100
        s.trades.append({'date': date, 'action': 'SELL', 'code': code,
                         'shares': a, 'price': round(p, 4), 'pnl_pct': round(pnl, 2), 'reason': reason})
        if a >= pos['shares']: del s.pos[code]
        else: s.pos[code]['shares'] -= a
        return True
    def tv(s, prices):
        return s.cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in s.pos.items())

# 加载
print("Loading data...")
all_data = load_data()
print(f"  {len(all_data)}/28 symbols loaded")

# 确定区间: 3年(2023.6~今)
START = '2023-06-01'; END = datetime.now().strftime('%Y-%m-%d')
trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START <= d.strftime('%Y-%m-%d') <= END]
print(f"  {len(trade_dates)} trading days: {trade_dates[0].date()} ~ {trade_dates[-1].date()}")

# 回测
pf = PF()
for date in trade_dates:
    d_str = date.strftime('%Y-%m-%d')
    prices = {}
    for code in all_data:
        m = all_data[code].index == date
        if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
    if len(prices) < 10: continue

    # 排名 (< date, 无未来函数)
    ranked = []
    for code in all_data:
        if code not in prices: continue
        mask = all_data[code].index < pd.Timestamp(date)
        hist = all_data[code][mask]
        if len(hist) < LB + 10: continue
        hp = hist['close'].values[-LB:].copy()
        if np.any(hp <= 0): continue
        s = score_qx(hp)
        if s > 0: ranked.append({'code': code, 'score': s, 'price': prices[code]})
    ranked.sort(key=lambda x: x['score'], reverse=True)

    targets = [r for r in ranked[:HN] if r['score'] > 0]
    target_set = set(r['code'] for r in targets)

    # 卖出不在目标中的
    for code in list(pf.pos.keys()):
        if code not in target_set and code in prices:
            pf.sell(code, pf.pos[code]['shares'], prices[code], d_str, '调出Top7')

    # 买入新目标
    total_val = pf.tv(prices)
    for r in targets:
        if r['code'] in pf.pos or r['code'] not in prices: continue
        per = total_val * 0.95 / len(targets)
        shares = int(per / r['price'])
        if shares > 0:
            pf.buy(r['code'], shares, r['price'], d_str, '动量轮换')

    pf.dv.append({'date': d_str, 'value': pf.tv(prices)})

# 统计
dv = pd.DataFrame(pf.dv)
tr = (dv['value'].iloc[-1] / CASH - 1) * 100
dr = dv['value'].pct_change().dropna()
ar = (1 + dr.mean())**252 - 1
md = (dv['value'] / dv['value'].cummax() - 1).min() * 100
sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
sells = [t for t in pf.trades if t['action'] == 'SELL']
wr = sum(1 for t in sells if t.get('pnl_pct', 0) > 0) / max(len(sells), 1) * 100

print(f'\n===== 精简27只 3年回测 =====')
print(f'累计: {tr:+.2f}% | 年化: {ar*100:.1f}% | 回撤: {md:.1f}% | 夏普: {sp:.2f}')
print(f'交易: {len(pf.trades)}笔 (买{sum(1 for t in pf.trades if t["action"]=="BUY")}/卖{len(sells)}) | 胜率: {wr:.1f}%')

# 分年
for year in [2023, 2024, 2025, 2026]:
    yd = dv[dv['date'].str.startswith(str(year))]
    if len(yd) < 2: continue
    yr = (yd['value'].iloc[-1] / yd['value'].iloc[0] - 1) * 100
    print(f'  {year}: {yr:+.2f}% ({len(yd)}天)')

# 保存交易记录
output = {
    'stats': {
        'total_return': round(tr, 2), 'annual_return': round(ar*100, 1),
        'max_drawdown': round(md, 1), 'sharpe': round(sp, 2),
        'total_trades': len(pf.trades), 'win_rate': round(wr, 1),
        'start': trade_dates[0].strftime('%Y-%m-%d'),
        'end': trade_dates[-1].strftime('%Y-%m-%d'),
        'trading_days': len(trade_dates), 'pool_size': len(TRIM27),
    },
    'trades': pf.trades
}

trades_path = OUT_DIR / '七星美股版_精简27只_交易记录.json'
with open(trades_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f'\n交易记录已保存: {trades_path} ({len(pf.trades)}笔)')

# 最近20笔
print('\n===== 最近20笔交易 =====')
for t in pf.trades[-20:][::-1]:
    pnl = t.get('pnl_pct', 0)
    pnl_str = f'{pnl:+.2f}%' if t['action'] == 'SELL' else '-'
    print(f'  {t["date"]} {t["action"]:4s} {t["code"]:6s} {t["shares"]:>6}股 @{t["price"]:.2f} {pnl_str} {t.get("reason","")}')
