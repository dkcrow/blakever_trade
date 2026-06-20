"""七星美股版 优化对比: 删6只 + score阈值 + 持股数"""
import numpy as np, pandas as pd
from pathlib import Path
DATA_DIR = Path('data/storage/stock_data/us')
FULL_POOL = ['NVDA','AVGO','AMD','MU','LRCX','ARM','LITE','NFLX','GOOGL','NOW','CRWD','ORCL','DDOG','SNPS','EOG','OKE','NEM','FCX','CAT','GE','RTX','AMT','PANW','ZS','NET','IONQ','RKLB','SPCX']
OPT_POOL = ['NVDA','AVGO','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS','EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB','SPCX']
COMM=0.005; SLIP=0.0005; CASH=1000000

all_data = {}
for sym in set(FULL_POOL+OPT_POOL):
    fp = DATA_DIR / f'{sym}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 35: all_data[sym] = df

trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if '2025-01-01' <= d.strftime('%Y-%m-%d') <= '2026-06-18']

def calc_score(closes):
    if len(closes) < 5: return -999
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
    def __init__(s): s.cash=CASH; s.pos={}; s.trades=[]
    @property
    def tv(s): return s.cash+sum(p['shares']*p.get('lp',p['cp']) for p in s.pos.values())
    def up(s,pd): 
        for c,p in pd.items():
            if c in s.pos: s.pos[c]['lp']=p
    def buy(s,sym,sh,price):
        p=price*(1+SLIP); tv=sh*p; c=sh*COMM
        if tv+c>s.cash+0.01: return False
        s.cash-=tv+c
        if sym in s.pos: o=s.pos[sym]; ts=o['shares']+sh; s.pos[sym]={'shares':ts,'cp':(o['shares']*o['cp']+sh*p)/ts,'lp':p}
        else: s.pos[sym]={'shares':sh,'cp':p,'lp':p}
        return True
    def sell(s,sym,sh,price):
        if sym not in s.pos: return False
        p=price*(1-SLIP); pos=s.pos[sym]; a=min(sh,pos['shares'])
        s.cash+=a*p-a*COMM
        if a>=pos['shares']: del s.pos[sym]
        else: s.pos[sym]['shares']-=a
        return True
    def codes(s): return list(s.pos.keys())

def run(pool, hn, threshold=None):
    pf=PF()
    for date in trade_dates:
        d_str=date.strftime('%Y-%m-%d')
        prices={}
        for sym in pool:
            if sym in all_data:
                m=all_data[sym].index==date
                if m.any(): prices[sym]=float(all_data[sym].loc[date,'close'])
        if len(prices)<hn: continue
        ranked=[]
        for sym in pool:
            if sym not in prices: continue
            df=all_data[sym]; mask=df.index<date; hist=df[mask]
            if len(hist)<25: continue
            cp=prices[sym]
            if cp<=0: continue
            score=calc_score(hist['close'].values[-25:])
            ranked.append({'code':sym,'score':score,'price':cp})
        ranked.sort(key=lambda x:x['score'],reverse=True)
        
        if threshold is not None:
            targets=[r for r in ranked if r['score']>=threshold][:hn]
        else:
            targets=[r for r in ranked[:hn] if r['score']>-999]
        tc=set(r['code'] for r in targets)
        cc=set(pf.codes())
        
        # Sell non-targets + below threshold
        to_sell=cc-tc
        if threshold is not None:
            for code in list(cc):
                f=next((r for r in ranked if r['code']==code),None)
                if f and f['score']<threshold: to_sell.add(code)
        for code in to_sell:
            if code in prices: pf.sell(code, pf.pos[code]['shares'], prices[code])
        
        tv=pf.tv; pf.up(prices)
        nq=max(len(targets),1)
        for r in targets:
            if r['code'] in pf.pos: continue
            if r['code'] not in prices: continue
            ps=tv*0.95/nq
            sh=int(ps/r['price'])
            if sh>=1: pf.buy(r['code'],sh,r['price'])
    
    dv=pd.DataFrame([{'value':pf.tv}])
    # Actually need daily_values... let me redo simpler
    return pf.tv

# Actually need daily_values for metrics
def run_full(pool, hn, threshold=None):
    pf=PF()
    daily=[]
    for date in trade_dates:
        d_str=date.strftime('%Y-%m-%d')
        prices={}
        for sym in pool:
            if sym in all_data:
                m=all_data[sym].index==date
                if m.any(): prices[sym]=float(all_data[sym].loc[date,'close'])
        if len(prices)<hn: continue
        
        ranked=[]
        for sym in pool:
            if sym not in prices: continue
            df=all_data[sym]; mask=df.index<date; hist=df[mask]
            if len(hist)<25: continue
            cp=prices[sym]
            if cp<=0: continue
            score=calc_score(hist['close'].values[-25:])
            ranked.append({'code':sym,'score':score,'price':cp})
        ranked.sort(key=lambda x:x['score'],reverse=True)
        
        if threshold is not None:
            targets=[r for r in ranked if r['score']>=threshold][:hn]
        else:
            targets=[r for r in ranked[:hn] if r['score']>-999]
        tc=set(r['code'] for r in targets)
        cc=set(pf.codes())
        
        to_sell=cc-tc
        if threshold is not None:
            for code in list(cc):
                f=next((r for r in ranked if r['code']==code),None)
                if f and f['score']<threshold: to_sell.add(code)
        for code in to_sell:
            if code in prices: pf.sell(code, pf.pos[code]['shares'], prices[code])
        
        tv=pf.tv; pf.up(prices)
        nq=max(len(targets),1)
        for r in targets:
            if r['code'] in pf.pos: continue
            if r['code'] not in prices: continue
            ps=tv*0.95/nq
            sh=int(ps/r['price'])
            if sh>=1: pf.buy(r['code'],sh,r['price'])
        daily.append({'date':d_str,'value':pf.tv})
    
    dv=pd.DataFrame(daily)
    tr=(dv['value'].iloc[-1]/CASH-1)*100
    dr=dv['value'].pct_change().dropna()
    ann=(dv['value'].iloc[-1]/CASH)**(252/max(len(dr),1))-1
    dd=(dv['value']/dv['value'].cummax()-1).min()*100
    sp=dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0
    sells=[t for t in pf.trades if t['action']=='SELL']
    return {'total':round(tr,1),'annual':round(ann*100,1),'dd':round(dd,1),'sharpe':round(sp,2),'final':pf.tv,'trades':len(sells),'days':len(daily)}

tests=[
    ('基准: 28只/7只/无阈值', FULL_POOL, 7, None),
    ('优化A: 22只/7只/无阈值', OPT_POOL, 7, None),
    ('优化B: 22只/7只/score>=0.5', OPT_POOL, 7, 0.5),
    ('优化C: 22只/5只/score>=0.5', OPT_POOL, 5, 0.5),
    ('优化D: 22只/5只/score>=1', OPT_POOL, 5, 1.0),
]
results=[]
for label,pool,hn,th in tests:
    r=run_full(pool,hn,th)
    r['label']=label
    results.append(r)
    print(label + f': 年化{r["annual"]:+.1f}% | 回撤{r["dd"]:.1f}% | 夏普{r["sharpe"]:.2f} | 终值${r["final"]:,.0f}')

print()
print('='*90)
header = f'{"方案":<30} | {"年化%":>8} | {"回撤%":>7} | {"夏普":>6} | {"终值":>14}'
print(header)
print('-'*90)
for r in results:
    lbl = r['label']
    print(f'{lbl:<30} | {r["annual"]:>+7.1f} | {r["dd"]:>7.1f} | {r["sharpe"]:>6.2f} | ${r["final"]:>13,.0f}')
print('='*90)
