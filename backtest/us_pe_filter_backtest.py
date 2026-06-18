#!/usr/bin/env python3
"""七星美股版 PE过滤回测 (静态近似: 用当前PE过滤整个回测区间)"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/us')
POOL_ALL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')

# 当前PE (2026-06-10 WeStock quote)
CURRENT_PE_TTM = {
    'NVDA':31.6,'AVGO':62.5,'AMD':154.9,'MU':43.8,'LRCX':65.4,'AMAT':49.9,
    'ARM':384.0,'AAPL':35.1,'TSM':36.6,'LITE':155.3,'META':21.3,'AMZN':28.9,
    'NFLX':26.3,'GOOGL':27.9,'MSFT':24.0,'CRM':20.2,'NOW':64.7,'CRWD':-5508.4,
    'ORCL':37.5,'PLTR':148.4,'DDOG':596.2,'SNPS':107.3,'XOM':25.4,'CVX':33.0,
    'COP':20.3,'EOG':13.8,'OKE':15.9,'NEM':12.5,'FCX':33.9,'LIN':34.5,
    'CAT':44.6,'GE':40.5,'RTX':33.9,'PLD':36.9,'AMT':30.5,
}

# 加载数据
all_data = {}
for s in POOL_ALL:
    fp = DATA_DIR / f'{s}.csv'
    if not fp.exists(): continue
    df = pd.read_csv(fp)
    df.columns = [c.lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    if len(df) > 30: all_data[s] = df

START='2025-01-02'; END='2026-06-09'
tdates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
tdates = [d for d in tdates if START <= d.strftime('%Y-%m-%d') <= END]

LB=25; HN=7; CASH=100000; COMM=0.005; SLIP=0.0005

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

def run_backtest(pool, label):
    cash = CASH; pos = {}; trades = []; dv = []
    valid_pool = [s for s in pool if s in all_data]
    
    for date in tdates:
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for c in valid_pool:
            m = all_data[c].index == date
            if m.any(): prices[c] = float(all_data[c].loc[date, 'close'])
        if not prices: continue
        
        ranked = []
        for c in valid_pool:
            if c not in prices: continue
            mask = all_data[c].index < pd.Timestamp(date)
            hist = all_data[c][mask]
            if len(hist) < LB + 10: continue
            hp = hist['close'].values[-LB:].copy()
            if np.any(hp <= 0): continue
            s = score_qx(hp)
            if s > 0: ranked.append({'code': c, 'score': s, 'price': prices[c]})
        
        ranked.sort(key=lambda x: x['score'], reverse=True)
        if len(ranked) < HN: continue
        
        targets = [r for r in ranked[:HN] if r['score'] > 0]
        target_codes = set(r['code'] for r in targets)
        
        for c in list(pos.keys()):
            if c not in target_codes and c in prices:
                p = prices[c] * (1 - SLIP)
                tv = pos[c]['shares'] * p; cf = pos[c]['shares'] * COMM
                cash += tv - cf
                pnl = (p - pos[c]['cost']) / pos[c]['cost'] * 100
                trades.append({'date': d_str, 'code': c, 'pnl': pnl})
                del pos[c]
        
        total_val = cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in pos.items())
        for r in targets:
            c = r['code']
            if c not in pos and c in prices:
                per = total_val * 0.95 / len(targets)
                shares = int(per / prices[c])
                if shares > 0:
                    p_buy = prices[c] * (1 + SLIP)
                    tv = shares * p_buy; cf = shares * COMM
                    cash -= tv + cf
                    pos[c] = {'shares': shares, 'cost': p_buy}
        
        dv.append({'date': d_str, 'value': cash + sum(p['shares'] * prices.get(c, p['cost']) for c, p in pos.items())})
    
    dv_df = pd.DataFrame(dv)
    tr = (dv_df['value'].iloc[-1] / CASH - 1) * 100
    dr = dv_df['value'].pct_change().dropna()
    ar = (1 + dr.mean())**252 - 1
    md = (dv_df['value'] / dv_df['value'].cummax() - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) * 100 if trades else 0
    return tr, ar*100, md, sp, len(trades), wr

# 测试阈值
tests = [
    ('无过滤(基准)', POOL_ALL, None),
    ('PE>50排除', [s for s in POOL_ALL if CURRENT_PE_TTM.get(s,0) <= 50], 50),
    ('PE>70排除', [s for s in POOL_ALL if CURRENT_PE_TTM.get(s,0) <= 70], 70),
    ('PE>100排除', [s for s in POOL_ALL if CURRENT_PE_TTM.get(s,0) <= 100], 100),
]

print(f'回测区间: {tdates[0].date()} ~ {tdates[-1].date()}, {len(tdates)}天')
print()
print(f'{"约束":<20} {"累计":>8} {"年化":>7} {"回撤":>6} {"夏普":>5} {"交易":>5} {"胜率":>5} {"排除":>6}')
print('-' * 75)
for label, pool, thresh in tests:
    tr, ar, md, sp, nt, wr = run_backtest(pool, label)
    excluded = len(POOL_ALL) - len(pool)
    print(f'{label:<20} {tr:>+7.2f}% {ar:>6.1f}% {md:>5.1f}% {sp:>5.2f} {nt:>5} {wr:>5.1f}% {excluded:>4}只')

# 列出被排除的股票
print()
for thresh, label in [(50,'PE>50'), (70,'PE>70'), (100,'PE>100')]:
    excluded = sorted([s for s in POOL_ALL if CURRENT_PE_TTM.get(s,0) > thresh])
    print(f'{label} 排除: {excluded}')
