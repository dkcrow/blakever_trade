"""逐个测试: 19只候选分别加入当前27只池, 3年回测"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/hk')
CUR = ['00700','09988','01810','03690','09999','02513','00100',
    '02162','02616','09688','09969','02418','00992',
    '00981','01347','01211','00175','03692','02338','02038',
    '00388','02388','00883','02899','09633','01929','00669']
NEW = ['09618','01024','09888','00020','01357','00268','03888','00522','01385',
    '01088','00857','02688','00916','00968','00005','01299','02318','03968','00939']
LB,HN,CASH = 25,7,1000000; SLIP,COMM,STAMP,FEE = 0.001,0.001,0.0013,0.0000565
START,END = '2023-04-01','2026-04-24'

def load(pool):
    d={}
    for c in pool:
        fp=DATA_DIR/f'hk{c}.csv'
        if fp.exists():
            df=pd.read_csv(fp); df.columns=[c.lower() for c in df.columns]; df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
            if len(df)>60: d[c]=df
    return d

def cs(cl):
    x=np.arange(len(cl)); y=np.log(cl); m=~np.isnan(y)&~np.isinf(y); xm=x[m]; ym=y[m]
    if len(xm)<5: return -999
    s=np.polyfit(xm,ym,1)[0]; a=np.exp(s*250); f=s*xm+np.polyfit(xm,ym,1)[1]; r=ym-f
    ssr=np.sum(r**2); sst=np.sum((ym-np.mean(ym))**2)
    return a*(1-ssr/sst) if sst>0 else 0

def run(pool):
    data=load(pool); tdates=sorted(set().union(*[set(df.index) for df in data.values()]))
    tdates=[d for d in tdates if START<=d.strftime('%Y-%m-%d')<=END]
    cash=CASH; pos={}; trades=[]; dv=[]
    for date in tdates:
        ds=date.strftime('%Y-%m-%d')
        prices={c:float(data[c].loc[date,'close']) for c in data if date in data[c].index}
        if len(prices)<5: continue
        ranked=[]
        for c in data:
            if c not in prices: continue
            h=data[c][data[c].index<pd.Timestamp(date)]
            if len(h)<LB+10: continue
            hp=h['close'].values[-LB:].copy()
            if np.any(hp<=0): continue
            s=cs(hp)
            if s>0: ranked.append({'c':c,'s':s,'p':prices[c]})
        ranked.sort(key=lambda x:x['s'],reverse=True)
        tg=set(r['c'] for r in ranked[:HN])
        for c in list(pos.keys()):
            if c not in tg and c in prices:
                p=prices[c]*(1-SLIP); val=p*pos[c]['sh']
                cash+=val-max(val*COMM,5)-val*STAMP-val*FEE
                pnl=(p-pos[c]['cost'])/pos[c]['cost']*100
                trades.append({'pnl':pnl}); del pos[c]
        tv=cash+sum(p['sh']*prices.get(c,p['cost']) for c,p in pos.items())
        for r in ranked[:HN]:
            c2=r['c']
            if c2 not in pos and c2 in prices:
                bp=prices[c2]*(1+SLIP); per=tv*0.95/HN
                sh=int(per/bp/100)*100
                if sh>=100:
                    cash-=sh*bp+max(sh*bp*COMM,5)+sh*bp*FEE; pos[c2]={'sh':sh,'cost':bp}
        dv.append({'d':ds,'v':cash+sum(p['sh']*prices.get(c,p['cost']) for c,p in pos.items())})
    dv2=pd.DataFrame(dv); dr=dv2['v'].pct_change().dropna()
    tr=round((dv2['v'].iloc[-1]/CASH-1)*100,1)
    cagr=round(((dv2['v'].iloc[-1]/CASH)**(252/max(len(dr),1))-1)*100,1)
    md=round((dv2['v']/dv2['v'].cummax()-1).min()*100,1)
    sp=round(dr.mean()/dr.std()*np.sqrt(252),2)
    sells=[t for t in trades if abs(t['pnl'])>0.001]
    wr=round(sum(1 for t in sells if t['pnl']>0)/max(len(sells),1)*100,1)
    return tr,cagr,md,sp,wr

b_tr,b_cg,b_md,b_sp,b_wr = run(CUR)
print(f'基线(27只): +{b_tr}% CAGR{b_cg}% DD{b_md}% 夏普{b_sp} 胜率{b_wr}%')
print()
print(f'{"代码":6s} {"累计":>8} {"CAGR":>7} {"回撤":>6} {"夏普":>5} {"胜率":>5} {"vs基线":>8}')
print('-'*55)
positive = []
for code in NEW:
    pool = CUR + [code]
    tr,cg,md,sp,wr = run(pool)
    diff = tr - b_tr
    mark = '✅' if diff > 0 else ('≈' if diff > -2 else '✗')
    print(f'{code:6s} {tr:>+7.1f}% {cg:>6.1f}% {md:>5.1f}% {sp:>5.2f} {wr:>5.1f}% {diff:>+7.1f}% {mark}')
    if diff > 0: positive.append((code, diff, cg, md, sp))

if positive:
    print(f'\n正向({len(positive)}只):')
    for c,diff,cg,md,sp in sorted(positive, key=lambda x: x[1], reverse=True):
        print(f'  {c} +{diff:.1f}% CAGR{cg:.1f}% DD{md:.1f}% 夏普{sp:.2f}')
else:
    print(f'\n零正向 — 19只全部不优于基线')

# 复合测试: Top3 vs 全部6只
print(f'\n=== 复合加入测试 ===')
TOP3 = ['01357','00005','00522']
POS6 = ['01357','00005','00522','02318','09888','00939']
for label, add in [('Top3(美图+汇丰+ASMPT)', TOP3), ('全部6只', POS6)]:
    tr,cg,md,sp,wr = run(CUR + add)
    diff = tr - b_tr
    print(f'当前+{label}: +{tr}% CAGR{cg}% DD{md}% 夏普{sp} 胜率{wr}% vs基线 {diff:+.1f}%')
