"""批量测试HSI + 复合测试"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
warnings.filterwarnings('ignore')
DATA_DIR = Path('data/storage/stock_data/hk')
CUR33 = ['00700','09988','01810','03690','09999','02513','00100','02162','02616','09688','09969','02418','00992','01357','00981','01347','00522','01211','00175','03692','02338','02038','00388','02388','00005','02318','00939','09888','00883','02899','09633','01929','00669']
LB,HN,CASH=25,7,1000000; SLIP,COMM,STAMP,FEE=0.001,0.001,0.0013,0.0000565; START,END='2023-04-01','2026-04-24'

def ld(pool):
    d={}
    for c in pool:
        fp=DATA_DIR/f'hk{c}.csv'
        if fp.exists():
            df=pd.read_csv(fp); df.columns=[c.lower() for c in df.columns]; df['date']=pd.to_datetime(df['date']).dt.tz_localize(None); df=df.set_index('date').sort_index()
            if len(df)>60: d[c]=df
    return d
def cs(cl):
    x=np.arange(len(cl)); y=np.log(cl); m=~np.isnan(y)&~np.isinf(y); xm=x[m]; ym=y[m]
    if len(xm)<5: return -999
    s=np.polyfit(xm,ym,1)[0]; a=np.exp(s*250); f=s*xm+np.polyfit(xm,ym,1)[1]; r=ym-f
    ssr=np.sum(r**2); sst=np.sum((ym-np.mean(ym))**2)
    return a*(1-ssr/sst) if sst>0 else 0
def run(pool):
    data=ld(pool); tdates=sorted(set().union(*[set(df.index) for df in data.values()]))
    tdates=[d for d in tdates if START<=d.strftime('%Y-%m-%d')<=END]
    cash=CASH; pos={}; dv=[]
    for date in tdates:
        ds=date.strftime('%Y-%m-%d'); prices={c:float(data[c].loc[date,'close']) for c in data if date in data[c].index}
        if len(prices)<5: continue
        ranked=[]
        for c in data:
            if c not in prices: continue
            h=data[c][data[c].index<pd.Timestamp(date)]
            if len(h)<LB+10: continue
            hp=h['close'].values[-LB:].copy()
            if np.any(hp)<=0: continue
            s=cs(hp)
            if s>0: ranked.append({'c':c,'s':s,'p':prices[c]})
        ranked.sort(key=lambda x:x['s'],reverse=True); tg=set(r['c'] for r in ranked[:HN])
        for c in list(pos.keys()):
            if c not in tg and c in prices:
                p=prices[c]*(1-SLIP); val=p*pos[c]['sh']
                cash+=val-max(val*COMM,5)-val*STAMP-val*FEE; del pos[c]
        tv=cash+sum(p['sh']*prices.get(c,p['cost']) for c,p in pos.items())
        for r in ranked[:HN]:
            c2=r['c']
            if c2 not in pos and c2 in prices:
                bp=prices[c2]*(1+SLIP); per=tv*0.95/HN; sh=int(per/bp/100)*100
                if sh>=100: cash-=sh*bp+max(sh*bp*COMM,5)+sh*bp*FEE; pos[c2]={'sh':sh,'cost':bp}
        dv.append({'d':ds,'v':cash+sum(p['sh']*prices.get(c,p['cost']) for c,p in pos.items())})
    dv2=pd.DataFrame(dv); dr=dv2['v'].pct_change().dropna()
    tr=round((dv2['v'].iloc[-1]/CASH-1)*100,1)
    cagr=round(((dv2['v'].iloc[-1]/CASH)**(252/max(len(dr),1))-1)*100,1)
    md=round((dv2['v']/dv2['v'].cummax()-1).min()*100,1)
    sp=round(dr.mean()/dr.std()*np.sqrt(252),2)
    return tr,cagr,md,sp

TOP4 = ['06181','01378','02628','02618']
ALL11 = ['06181','01378','02628','02618','06690','01113','01177','02057','01093','03988','03993']

tr,cg,md,sp = run(CUR33)
print(f'基线33只: +{tr}% CAGR{cg}% DD{md}% 夏普{sp}')
tr,cg,md,sp = run(CUR33+TOP4)
print(f'+Top4(老铺+宏桥+人寿+京东物流): +{tr}% CAGR{cg}% DD{md}% 夏普{sp}')
tr,cg,md,sp = run(CUR33+ALL11)
print(f'+全部11只: +{tr}% CAGR{cg}% DD{md}% 夏普{sp}')
tr,cg,md,sp = run(CUR33+['06181'])
print(f'+仅老铺黄金: +{tr}% CAGR{cg}% DD{md}% 夏普{sp}')
