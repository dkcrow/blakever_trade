"""US threshold fine-grained test: 0.5 to 4.5"""
import numpy as np, pandas as pd
from pathlib import Path

DATA_DIR = Path('data/storage/stock_data/us')
POOL = 'NVDA,AVGO,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,CSCO,HOOD'.split(',')
HN=7; CASH=1000000; COMM=0.005; SLIP=0.0005

all_data={}
for sym in POOL:
    fp=DATA_DIR/f'{sym}.csv'
    if fp.exists():
        df=pd.read_csv(fp)
        df.columns=[c.lower() for c in df.columns]
        df['date']=pd.to_datetime(df['date'])
        df=df.set_index('date').sort_index()
        if len(df)>35: all_data[sym]=df

tds=sorted(set().union(*[set(df.index) for df in all_data.values()]))
tds=[d for d in tds if '2025-01-01'<=d.strftime('%Y-%m-%d')<='2026-06-18']

def sc(closes):
    if len(closes)<5: return -999
    x=np.arange(len(closes)); y=np.log(closes)
    mask=~np.isnan(y)&~np.isinf(y); x_m=x[mask]; y_m=y[mask]
    if len(x_m)<5: return -999
    sl=np.polyfit(x_m,y_m,1)[0]; ann=np.exp(sl*250)
    fitted=sl*x_m+np.polyfit(x_m,y_m,1)[1]; res=y_m-fitted
    ss=sum(res**2); st=sum((y_m-np.mean(y_m))**2)
    r2=1-ss/st if st>0 else 0
    return ann*r2

class PF:
    def __init__(s): s.c=CASH; s.p={}
    @property
    def tv(s): return s.c+sum(p['s']*p.get('l',p['cp']) for p in s.p.values())
    def up(s,d):
        for c,p in d.items():
            if c in s.p: s.p[c]['l']=p
    def buy(s,x,sh,pr):
        p=pr*(1+SLIP); t=sh*p; c=sh*COMM
        if t+c>s.c+0.01: return False
        s.c-=t+c
        if x in s.p: o=s.p[x]; ts=o['s']+sh; s.p[x]={'s':ts,'cp':(o['s']*o['cp']+sh*p)/ts,'l':p}
        else: s.p[x]={'s':sh,'cp':p,'l':p}
        return True
    def sell(s,x,sh,pr):
        if x not in s.p: return False
        p=pr*(1-SLIP); pos=s.p[x]; a=min(sh,pos['s'])
        s.c+=a*p-a*COMM
        if a>=pos['s']: del s.p[x]
        else: s.p[x]['s']-=a
        return True
    def cs(s): return list(s.p.keys())

def run(th):
    pf=PF(); daily=[]
    for date in tds:
        prices={}
        for sym in POOL:
            if sym in all_data:
                m=all_data[sym].index==date
                if m.any(): prices[sym]=float(all_data[sym].loc[date,'close'])
        if len(prices)<HN: continue
        ranked=[]
        for sym in POOL:
            if sym not in prices: continue
            df=all_data[sym]; mask=df.index<date; hist=df[mask]
            if len(hist)<25: continue
            cp=prices[sym]
            if cp<=0: continue
            score=sc(hist['close'].values[-25:])
            ranked.append({'code':sym,'score':score,'price':cp})
        ranked.sort(key=lambda x:x['score'],reverse=True)
        targets=[r for r in ranked if r['score']>=th][:HN]
        tc=set(r['code'] for r in targets)
        cc=set(pf.cs())
        ts=cc-tc
        for code in list(cc):
            f=next((r for r in ranked if r['code']==code),None)
            if f and f['score']<th: ts.add(code)
        for code in ts:
            if code in prices: pf.sell(code,pf.p[code]['s'],prices[code])
        tv=pf.tv; pf.up(prices)
        nq=max(len(targets),1)
        for r in targets:
            if r['code'] in pf.p: continue
            if r['code'] not in prices: continue
            ps=tv*0.95/nq; sh=int(ps/r['price'])
            if sh>=1: pf.buy(r['code'],sh,r['price'])
        daily.append({'date':date.strftime('%Y-%m-%d'),'value':pf.tv})
    dv=pd.DataFrame(daily)
    dr=dv['value'].pct_change().dropna()
    ann=(dv['value'].iloc[-1]/CASH)**(252/max(len(dr),1))-1
    dd=(dv['value']/dv['value'].cummax()-1).min()*100
    sp=dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0
    return {'annual':round(ann*100,1),'dd':round(dd,1),'sharpe':round(sp,2),'final':dv['value'].iloc[-1]}

results=[]
for th in [0.5,1,1.5,2,2.5,3,3.5,4,4.5]:
    r=run(th)
    r['th']=th
    results.append(r)

print(f'{"阈值":>5} | {"年化%":>8} | {"回撤%":>7} | {"夏普":>6} | {"终值":>14}')
print('-'*55)
for r in results:
    print(f'{r["th"]:>5} | {r["annual"]:>+7.1f} | {r["dd"]:>7.1f} | {r["sharpe"]:>6.2f} | ${r["final"]:>13,.0f}')

best=max(results,key=lambda x:x['annual'])
print(f'\n最优: score>={best["th"]} (年化{best["annual"]:+.1f}%)')
