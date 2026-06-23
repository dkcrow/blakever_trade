#!/usr/bin/env python3
"""七星港股版 评分公式对比: exp×R² (当前) vs (exp-1)×R² (拟统一)
唯一变量 = calc_score 最后一行, 其余规则与 hk_live_report.py 完全一致。
3年回测 (2023-06-18 ~ 今), 5只等权, score>=0.5, 港股费率, 线性加权linspace(1,2)。
"""
import warnings
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

# ===== 配置 (复制自 hk_live_report.py) =====
HK_POOL = [
    '00700','09988','01810','03690','09999',        # 互联网/平台
    '02513','00100',                                # AI大模型
    '02162','02616','09969',                        # AI/生物科技
    '02418','01357',                                # AI应用/硬件
    '00981','01347','00522',                        # 半导体
    '01211',                                        # 新能源车
    '01093','01177',                                # 制药
    '02338','02038','01378',                        # 工业/制造
    '00388','02388','00005','02318','00939','02628','03988',  # 金融
    '09888',                                        # 科技/AI平台
    '00883','02899','03993',                        # 能源/材料
    '02618',                                        # 物流
    '01929',                                        # 消费
    '01113','06181',                                # 房地产/珠宝
    '00669',                                        # 工业
]
PARAMS = {'lookback_days': 25, 'holdings_num': 5, 'min_money': 500}
SCORE_THRESHOLD = 0.5
HK_COMM_RATE = 0.001
HK_STAMP_DUTY = 0.0013
HK_TRADE_FEE = 0.0000565
SLIPPAGE = 0.001
CASH = 1000000
DATA_DIR = Path('data/storage/stock_data/hk')
START_DATE = '2023-06-18'
END_DATE = datetime.now().strftime('%Y-%m-%d')

# ===== 数据加载 =====
all_data = {}
for code in HK_POOL:
    fp = DATA_DIR / f'hk{code}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 35:
            all_data[code] = df
trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]

# ===== 参数化评分 (minus1=True → (exp-1)×R²; False → exp×R²) =====
def calc_score(closes, minus1):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    w = np.linspace(1, 2, len(x_m))                 # 线性加权, 与实盘一致
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = np.exp(slope * 250)
    fitted = slope * x_m + intercept
    res = y_m - fitted
    ss_res = np.sum(w * res**2); ss_tot = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return (ann - 1) * r2 if minus1 else ann * r2

def get_ranked(prices, date, minus1):
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index < pd.Timestamp(date); hist = df[mask]
        if len(hist) < 35: continue
        cp = prices[code]
        if cp <= 0: continue
        score = calc_score(hist['close'].values[-25:], minus1)
        ranked.append({'code': code, 'score': score, 'price': cp})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

# ===== 投资组合 (复制自 hk_live_report.py) =====
class HKPortfolio:
    def __init__(s, cash=CASH):
        s.initial_cash = cash; s.cash = cash
        s.positions = {}; s.trade_log = []; s.daily_values = []
    @property
    def total_value(s):
        pv = sum(p['shares']*p.get('last_price', p['cost_price']) for p in s.positions.values())
        return s.cash + pv
    def update_prices(s, pdict):
        for c, p in pdict.items():
            if c in s.positions: s.positions[c]['last_price'] = p
    def buy(s, code, shares, price, date, reason=''):
        p = price * (1 + SLIPPAGE); tv = shares * p
        comm = max(tv * HK_COMM_RATE, 5)
        trade_fee = tv * HK_TRADE_FEE
        total = tv + comm + trade_fee
        if total > s.cash + 0.01: return False
        s.cash -= total
        if code in s.positions:
            o = s.positions[code]; ts = o['shares'] + shares
            s.positions[code] = {'shares': ts, 'cost_price': (o['shares']*o['cost_price']+shares*p)/ts,
                                 'last_price': p, 'buy_date': o.get('buy_date', date)}
        else:
            s.positions[code] = {'shares': shares, 'cost_price': p, 'last_price': p, 'buy_date': date}
        s.trade_log.append({'date': date, 'action': 'BUY', 'code': code, 'shares': int(shares), 'price': round(p, 4)})
        return True
    def sell(s, code, shares, price, date, reason=''):
        if code not in s.positions: return False
        p = price * (1 - SLIPPAGE); pos = s.positions[code]
        a = min(shares, pos['shares']); tv = a * p
        comm = max(tv * HK_COMM_RATE, 5)
        stamp = tv * HK_STAMP_DUTY
        trade_fee = tv * HK_TRADE_FEE
        s.cash += tv - comm - stamp - trade_fee
        pnl = (p - pos['cost_price']) / pos['cost_price'] * 100
        s.trade_log.append({'date': date, 'action': 'SELL', 'code': code, 'shares': int(a),
                            'price': round(p, 4), 'pnl_pct': round(pnl, 2)})
        if a >= pos['shares']: del s.positions[code]
        else: s.positions[code]['shares'] -= a
        return True
    def get_position_codes(s):
        return list(s.positions.keys())

# ===== 回测 =====
def run(minus1):
    pf = HKPortfolio(); hn = PARAMS['holdings_num']
    for i, date in enumerate(trade_dates):
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for code in all_data:
            m = all_data[code].index == date
            if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
        if len(prices) < hn: continue
        ranked = get_ranked(prices, date, minus1)
        current_targets = [r for r in ranked if r['score'] >= SCORE_THRESHOLD][:hn]
        target_codes = set(r['code'] for r in current_targets)
        current_codes = set(pf.get_position_codes())
        to_sell = current_codes - target_codes
        for code in list(current_codes):
            found = next((r for r in ranked if r['code'] == code), None)
            if found and found['score'] < SCORE_THRESHOLD: to_sell.add(code)
        for code in to_sell:
            sp = prices.get(code, 0)
            if sp <= 0: sp = pf.positions[code].get('last_price', 0)
            if sp <= 0: sp = pf.positions[code].get('cost_price', 0)
            if sp > 0: pf.sell(code, pf.positions[code]['shares'], sp, d_str)
            elif code not in prices: pf.sell(code, pf.positions[code]['shares'], pf.positions[code].get('cost_price', 1), d_str)
        pf.update_prices(prices)
        new_targets = [r for r in current_targets if r['code'] not in pf.positions and r['code'] in prices]
        if new_targets:
            available = pf.cash * 0.95; per = available / len(new_targets)
            for r in new_targets:
                shares = int(per / r['price'] / 100) * 100
                if shares >= 100: pf.buy(r['code'], shares, r['price'], d_str)
        pf.daily_values.append({'date': d_str, 'value': pf.total_value})
    dv = pd.DataFrame(pf.daily_values)
    tr = (dv['value'].iloc[-1] / CASH - 1) * 100
    dr = dv['value'].pct_change().dropna()
    ann = (dv['value'].iloc[-1] / CASH) ** (252 / max(len(dr), 1)) - 1
    dd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
    sh = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    sells = [t for t in pf.trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl_pct', 0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    return dict(tr=tr, ann=ann*100, dd=dd, sh=sh, n=len(pf.trade_log), wr=wr, final=dv['value'].iloc[-1])

print(f"数据: {len(all_data)}只 | 交易日: {len(trade_dates)}天 | "
      f"{trade_dates[0].strftime('%Y-%m-%d')} ~ {trade_dates[-1].strftime('%Y-%m-%d')}")
print("回测中 A: exp×R² (当前) ...")
A = run(False)
print("回测中 B: (exp-1)×R² (拟统一) ...")
B = run(True)

def fmt(d):
    return (f"累计{d['tr']:+.1f}% | 年化{d['ann']:.1f}% | 回撤{d['dd']:.1f}% | "
            f"夏普{d['sh']:.2f} | 交易{d['n']}次 | 胜率{d['wr']:.0f}% | 终值HK${d['final']:,.0f}")

print("\n" + "="*78)
print(f"  港股版评分公式对比 (3年, 37只池, 5只等权, score>=0.5, 线性加权)")
print("="*78)
print(f"  A  exp×R²     (当前): {fmt(A)}")
print(f"  B (exp-1)×R² (拟统一): {fmt(B)}")
print("-"*78)
print(f"  差异(B-A): 累计{B['tr']-A['tr']:+.1f}pp | 年化{B['ann']-A['ann']:+.1f}pp | "
      f"回撤{B['dd']-A['dd']:+.1f}pp | 夏普{B['sh']-A['sh']:+.2f} | 交易{B['n']-A['n']:+d}次 | 胜率{B['wr']-A['wr']:+.0f}pp")
print("="*78)
