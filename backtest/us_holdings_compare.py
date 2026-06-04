#!/usr/bin/env python3
"""七星美股版 持股数对比: 3 vs 5 vs 7 vs 8"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
START_DATE = '2023-06-01'; END_DATE = '2026-04-23'

POOL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')

all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        mask = (df.index >= START_DATE) & (df.index <= END_DATE); df = df[mask]
        if len(df) >= 25: all_data[sym] = df
    except: pass

trade_dates = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]

def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback+1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y)); w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope*x + intercept))**2)
    sst = np.sum(w * (y - np.mean(y))**2)
    r2 = 1 - ssr/sst if sst>0 else 0
    return ann * r2

def get_ranked(prices, date):
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index <= pd.Timestamp(date); hist = df[mask]
        if len(hist) < 35: continue
        cp = prices[code]
        if cp <= 0: continue
        score = calc_score(hist['close'].values, 25)
        ranked.append({'code':code,'score':score,'price':cp})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

class USPortfolio:
    def __init__(self, cash=10000, comm=0.005):
        self.initial_cash = cash; self.cash = cash; self.comm = comm
        self.positions = {}; self.trade_log = []; self.daily_values = []
    @property
    def total_value(self):
        pv = sum(p['shares']*p.get('last_price',p['cost_price']) for p in self.positions.values())
        return self.cash + pv
    def update_prices(self, pdict):
        for c,p in pdict.items():
            if c in self.positions: self.positions[c]['last_price'] = p
    def buy(self, code, shares, price, date, reason=''):
        tv = shares*price; comm = shares*self.comm; total = tv+comm
        if total > self.cash+0.01: return False
        self.cash -= total
        if code in self.positions:
            o = self.positions[code]; ts = o['shares']+shares
            self.positions[code] = {'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*price)/ts,'last_price':price,'buy_date':o.get('buy_date',date)}
        else:
            self.positions[code] = {'shares':shares,'cost_price':price,'last_price':price,'buy_date':date}
        self.trade_log.append({'date':str(date)[:10],'code':code,'action':'BUY','price':round(price,4),'shares':int(shares),'amount':round(tv,2),'commission':round(comm,2),'reason':reason})
        return True
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        pos = self.positions[code]; actual = min(shares, pos['shares'])
        if actual <= 0: return False
        tv = actual*price; comm = actual*self.comm; self.cash += tv-comm
        pos['shares'] -= actual
        pnl = (price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares'] <= 0: del self.positions[code]
        self.trade_log.append({'date':str(date)[:10],'code':code,'action':'SELL','price':round(price,4),'shares':int(actual),'amount':round(tv,2),'commission':round(comm,2),'pnl_pct':round(pnl,4),'reason':reason})
        return True
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions: return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)
    def record_daily_value(self, date):
        v = self.total_value
        self.daily_values.append({'date':str(date)[:10],'value':round(v,2),'returns':round((v-self.initial_cash)/self.initial_cash,6)})
    def get_position_codes(self): return list(self.positions.keys())

def run_backtest(hn):
    pf = USPortfolio(cash=10000)
    for i, td in enumerate(trade_dates):
        tds = pd.Timestamp(td)
        prices = {}
        for code, df in all_data.items():
            m = df.index <= tds
            if m.any(): prices[code] = float(df.loc[m,'close'].iloc[-1])
        pf.update_prices(prices)
        ranked = get_ranked(prices, td)
        if not ranked: pf.record_daily_value(td); continue
        targets = [r['code'] for r in ranked if r['score'] > -999][:hn]
        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code, prices[code], td, reason='调出(无目标)')
            pf.record_daily_value(td); continue
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                pf.sell_all(code, prices[code], td, reason='调出目标')
        tv = pf.total_value; each = tv / len(targets)
        for idx, code in enumerate(targets):
            if code not in prices: continue
            price = prices[code]; cv = 0
            if code in pf.positions:
                cv = pf.positions[code]['shares'] * pf.positions[code]['last_price']
            diff = each - cv
            if abs(diff) < each * 0.05 and cv > 0: continue
            if diff > 0:
                sh = int(diff / price)
                if sh > 0 and sh * price >= 500:
                    pf.buy(code, sh, price, td, reason=f'排名{idx+1}')
        pf.record_daily_value(td)

    dv = pf.daily_values
    vals = [d['value'] for d in dv]; fv = vals[-1]
    tr = (fv - pf.initial_cash) / pf.initial_cash
    peak, mdd = vals[0], 0
    for v in vals:
        if v > peak: peak = v
        dd = (peak-v)/peak if peak>0 else 0
        if dd>mdd: mdd=dd
    sh = 0
    if len(vals)>1:
        dr = np.diff(vals)/vals[:-1]
        sh = (np.mean(dr)/np.std(dr)*np.sqrt(252)) if np.std(dr)>0 else 0
    cm = abs(tr*252/len(trade_dates))/mdd if mdd>0 else 0
    trades = pf.trade_log
    buys = sum(1 for t in trades if t['action']=='BUY')
    sells = sum(1 for t in trades if t['action']=='SELL')
    st = [t for t in trades if t['action']=='SELL' and 'pnl_pct' in t]
    wins = [t for t in st if t['pnl_pct']>0]
    losses = [t for t in st if t['pnl_pct']<=0]
    wr = len(wins)/len(st)*100 if st else 0
    aw = sum(t['pnl_pct'] for t in wins)/len(wins)*100 if wins else 0
    al = sum(t['pnl_pct'] for t in losses)/len(losses)*100 if losses else 0
    ann = tr * 252 / len(trade_dates) * 100
    return {'hn':hn,'final':fv,'total_pct':tr*100,'ann_pct':ann,'mdd_pct':mdd*100,'sharpe':sh,'calmar':cm,'trades':len(trades),'buys':buys,'sells':sells,'win_pct':wr,'avg_win':aw,'avg_loss':al}

print(f'池: {len(all_data)}只 | 交易日: {len(trade_dates)}天')
print('=' * 70)
print(f'{"持股数":>6s} {"总收益":>10s} {"年化":>8s} {"回撤":>8s} {"夏普":>7s} {"胜率":>7s} {"平均盈":>7s} {"平均亏":>7s} {"交易":>6s}')
print('-' * 70)

results = []
for hn in [3, 5, 7, 8]:
    r = run_backtest(hn)
    results.append(r)
    print(f'{r["hn"]:6d}只 {r["total_pct"]:+9.2f}% {r["ann_pct"]:7.2f}% {r["mdd_pct"]:7.2f}% {r["sharpe"]:6.4f} {r["win_pct"]:6.1f}% {r["avg_win"]:+6.2f}% {r["avg_loss"]:7.2f}% {r["trades"]:5d}次')

print('=' * 70)
