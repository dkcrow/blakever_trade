#!/usr/bin/env python3
"""七星美股版 35只 -8%硬止损 x5 回测"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'

STRATEGY_NAME = '七星美股版(35只 -8%止损) x5'
START_DATE = '2023-06-01'
END_DATE = '2026-04-23'

POOL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')

PARAMS = {
    'lookback_days': 25, 'holdings_num': 5, 'min_money': 500,
    'enable_profit_protection': False,
    'enable_stop_loss': True, 'stop_loss_ratio': 0.92,
}

print('=' * 60)
print(f'  {STRATEGY_NAME}')
print(f'  区间: {START_DATE} ~ {END_DATE}')
print(f'  池: {len(POOL)}只 | 持股: {PARAMS["holdings_num"]}只 | 硬止损: -8%')
print('=' * 60)

all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        mask = (df.index >= START_DATE) & (df.index <= END_DATE)
        df = df[mask]
        if len(df) >= 25: all_data[sym] = df
    except: pass

print(f'  有效: {len(all_data)} 只')
trade_dates = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]
print(f'  交易日: {len(trade_dates)} 天')

def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback+1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y)); w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope*x + intercept))**2)
    sst = np.sum(w * (y - np.mean(y))**2)
    r2 = 1 - ssr/sst if sst>0 else 0
    return ann * r2, ann

def get_ranked(all_data, prices, date, params):
    ranked = []
    lb = params['lookback_days']
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index <= pd.Timestamp(date); hist = df[mask]
        if len(hist) < lb + 10: continue
        cp = prices[code]
        if cp <= 0: continue
        score, ann = calc_score(hist['close'].values, lb)
        ranked.append({'code':code,'score':score,'price':cp,'filtered':False,'reasons':[]})
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
        self.trade_log.append({'date':str(date)[:10],'code':code,'name':code,'action':'BUY','price':round(price,4),'shares':int(shares),'amount':round(tv,2),'commission':round(comm,2),'reason':reason})
        return True
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        pos = self.positions[code]; actual = min(shares, pos['shares'])
        if actual <= 0: return False
        tv = actual*price; comm = actual*self.comm
        self.cash += tv-comm; pos['shares'] -= actual
        pnl = (price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares'] <= 0: del self.positions[code]
        self.trade_log.append({'date':str(date)[:10],'code':code,'name':code,'action':'SELL','price':round(price,4),'shares':int(actual),'amount':round(tv,2),'commission':round(comm,2),'pnl_pct':round(pnl,4),'reason':reason})
        return True
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions: return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)
    def record_daily_value(self, date):
        v = self.total_value
        self.daily_values.append({'date':str(date)[:10],'value':round(v,2),'returns':round((v-self.initial_cash)/self.initial_cash,6)})
    def get_position_codes(self): return list(self.positions.keys())

pf = USPortfolio(cash=10000)
hn = PARAMS['holdings_num']

print(f'\n回测中: {len(trade_dates)} 天')
print('-' * 60)

for i, td in enumerate(trade_dates):
    tds = pd.Timestamp(td)
    prices = {}
    for code, df in all_data.items():
        m = df.index <= tds
        if m.any(): prices[code] = float(df.loc[m,'close'].iloc[-1])
    pf.update_prices(prices)
    
    # -8% 硬止损
    if PARAMS.get('enable_stop_loss', False):
        for code in list(pf.get_position_codes()):
            if code in prices and code in pf.positions:
                pos = pf.positions[code]; cp = prices[code]
                cost = pos.get('cost_price', cp)
                if cost > 0 and cp <= cost * PARAMS['stop_loss_ratio']:
                    loss_pct = (cp / cost - 1) * 100
                    pf.sell_all(code, cp, td, reason=f'硬止损({loss_pct:.1f}%)')
    
    ranked = get_ranked(all_data, prices, td, PARAMS)
    if not ranked:
        pf.record_daily_value(td); continue
    
    targets = [r['code'] for r in ranked if not r['filtered']][:hn]
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
            if sh > 0 and sh * price >= PARAMS['min_money']:
                pf.buy(code, sh, price, td, reason=f'排名{idx+1}')
    pf.record_daily_value(td)
    if i % 30 == 0:
        top3 = ', '.join([f"{r['code']}({r['score']:.4f})" for r in ranked[:3]])
        print(f'  [{td}] Top3: {top3} | ${pf.total_value:,.0f}')

# Results
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
wins = [t for t in st if t['pnl_pct']>0]; losses = [t for t in st if t['pnl_pct']<=0]
wr = len(wins)/len(st)*100 if st else 0
aw = sum(t['pnl_pct'] for t in wins)/len(wins)*100 if wins else 0
al = sum(t['pnl_pct'] for t in losses)/len(losses)*100 if losses else 0
n_days = len(trade_dates); ann = tr * 252 / n_days * 100
sl_count = sum(1 for t in trades if '硬止损' in t.get('reason',''))

st_sorted = sorted(st, key=lambda x: x['pnl_pct'], reverse=True)
top10_w = st_sorted[:10]; top10_l = st_sorted[-10:][::-1]

by_sym = {}
for t in st:
    s = t['code']
    if s not in by_sym: by_sym[s] = {'cnt':0,'w':0,'tp':0}
    by_sym[s]['cnt'] += 1
    if t['pnl_pct'] > 0: by_sym[s]['w'] += 1
    by_sym[s]['tp'] += t['pnl_pct']*100

print(f'\n{"="*60}')
print(f'  {STRATEGY_NAME}')
print(f'{"="*60}')
print(f'  总收益: {tr*100:+.2f}%  年化: {ann:.2f}%')
print(f'  最大回撤: {mdd*100:.2f}%  夏普: {sh:.4f}  卡尔马: {cm:.4f}')
print(f'  交易: {len(trades)}次(买{buys}/卖{sells})  胜率: {wr:.1f}%')
print(f'  平均盈利: +{aw:.2f}%  平均亏损: {al:.2f}%')
print(f'  硬止损触发: {sl_count} 次')
print(f'  最终: ${fv:,.2f}')

print(f'\n  Top10 盈利:')
for t in top10_w:
    print(f'    {t["code"]:6s} {t["date"]} {t["pnl_pct"]*100:+.2f}%  {t["reason"]}')
print(f'\n  Top10 亏损:')
for t in top10_l:
    print(f'    {t["code"]:6s} {t["date"]} {t["pnl_pct"]*100:+.2f}%  {t["reason"]}')
print(f'\n  按标的统计(Top15):')
for s, d in sorted(by_sym.items(), key=lambda x: x[1]['cnt'], reverse=True)[:15]:
    avg = d['tp']/d['cnt'] if d['cnt']>0 else 0
    wr_s = d['w']/d['cnt']*100 if d['cnt']>0 else 0
    print(f'    {s:6s} {d["cnt"]:3d}笔 胜率{wr_s:5.1f}% 累计{d["tp"]:+.1f}% 均{avg:+.2f}%')
