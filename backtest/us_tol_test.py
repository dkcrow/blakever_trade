#!/usr/bin/env python3
"""七星美股版 容差参数对比: 5% vs 2% tolerance"""
import math, warnings; from pathlib import Path
import numpy as np, pandas as pd; warnings.filterwarnings('ignore')

DATA = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'us'
START, END = '2023-06-01', '2026-06-04'
POOL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')
HM = 7

adata = {}
for s in POOL:
    fp = DATA / f'{s}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        df = df[(df.index >= START) & (df.index <= END)]
        if len(df) >= 25: adata[s] = df
    except: pass
tdates = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in adata.values()]))
tdates = [d for d in tdates if START <= d <= END]

def score(c, l=25):
    r = c[-(l+1):]; y = np.log(np.maximum(r,1e-10)); x = np.arange(len(y)); w = np.linspace(1,2,len(y))
    s,i = np.polyfit(x,y,1,w=w); a = math.exp(s*250)-1
    ssr=np.sum(w*(y-(s*x+i))**2); sst=np.sum(w*(y-np.mean(y))**2)
    return a*(1-ssr/sst if sst>0 else 0)

def rank(prices, date):
    rk = []
    for cd, df in adata.items():
        if cd not in prices: continue
        m = df.index <= pd.Timestamp(date); h = df[m]
        if len(h) < 35: continue
        cp = prices[cd]
        if cp <= 0: continue
        rk.append({'code':cd,'score':score(h['close'].values),'price':cp})
    rk.sort(key=lambda x: x['score'], reverse=True); return rk

class PF:
    def __init__(self, c=10000, cm=0.005):
        self.ic=c; self.c=c; self.ci=cm; self.p={}; self.t=[]; self.dv=[]
    @property
    def tv(self):
        pv=sum(p['shares']*p.get('lp',p['cp']) for p in self.p.values())
        return self.c+pv
    def up(self, pdict):
        for k,v in pdict.items():
            if k in self.p: self.p[k]['lp']=v
    def buy(self, cd, sh, pr, date, rn=''):
        tv=sh*pr; cm=sh*self.ci; tt=tv+cm
        if tt>self.c+.01: return False
        self.c-=tt
        if cd in self.p:
            o=self.p[cd]; ts=o['shares']+sh
            self.p[cd]={'shares':ts,'cp':(o['shares']*o['cp']+sh*pr)/ts,'lp':pr,'bd':o.get('bd',date)}
        else:
            self.p[cd]={'shares':sh,'cp':pr,'lp':pr,'bd':date}
        self.t.append({'date':str(date)[:10],'code':cd,'action':'BUY','price':round(pr,4),'shares':int(sh),'amount':round(tv,2),'commission':round(cm,2),'reason':rn})
        return True
    def sell(self, cd, sh, pr, date, rn=''):
        if cd not in self.p: return False
        po=self.p[cd]; act=min(sh,po['shares'])
        if act<=0: return False
        tv=act*pr; cm=act*self.ci; self.c+=tv-cm; po['shares']-=act
        pl=(pr-po['cp'])/po['cp'] if po['cp']>0 else 0
        if po['shares']<=0: del self.p[cd]
        self.t.append({'date':str(date)[:10],'code':cd,'action':'SELL','price':round(pr,4),'shares':int(act),'amount':round(tv,2),'commission':round(cm,2),'pnl_pct':round(pl,4),'reason':rn})
        return True
    def sa(self, cd, pr, date, rn=''):
        if cd not in self.p: return False
        return self.sell(cd,self.p[cd]['shares'],pr,date,rn)
    def rdv(self, date):
        v=self.tv; self.dv.append({'date':str(date)[:10],'value':round(v,2),'returns':round((v-self.ic)/self.ic,6)})
    def gpc(self): return list(self.p.keys())

def run(tol, mm):
    pf = PF()
    for td in tdates:
        tds = pd.Timestamp(td)
        prices = {}
        for cd, df in adata.items():
            m = df.index <= tds
            if m.any(): prices[cd] = float(df.loc[m,'close'].iloc[-1])
        pf.up(prices)
        rk = rank(prices, td)
        if not rk: pf.rdv(td); continue
        tgs = [r['code'] for r in rk if r['score'] > -999][:HM]
        if not tgs:
            for cd in list(pf.gpc()):
                if cd in prices: pf.sa(cd, prices[cd], td, '无目标')
            pf.rdv(td); continue
        for cd in list(pf.gpc()):
            if cd not in tgs and cd in prices: pf.sa(cd, prices[cd], td, '调出')
        tv=pf.tv; each=tv/len(tgs)
        for idx, cd in enumerate(tgs):
            if cd not in prices: continue
            pr=prices[cd]; cv=0
            if cd in pf.p: cv=pf.p[cd]['shares']*pf.p[cd]['lp']
            diff=each-cv
            if abs(diff)<each*tol and cv>0: continue
            if diff>0:
                sh=int(diff/pr)
                if sh>0 and sh*pr>=mm: pf.buy(cd,sh,pr,td,f'排名{idx+1}')
        pf.rdv(td)
    dv=pf.dv; vals=[d['value'] for d in dv]; fv=vals[-1]
    tr=(fv-pf.ic)/pf.ic; pk,mdd=vals[0],0
    for v in vals:
        if v>pk: pk=v
        dd=(pk-v)/pk if pk>0 else 0
        if dd>mdd: mdd=dd
    shv=0
    if len(vals)>1:
        dr=np.diff(vals)/vals[:-1]; s=np.std(dr)
        shv=(np.mean(dr)/s*np.sqrt(252)) if s>0 else 0
    t=pf.t; st=[x for x in t if x['action']=='SELL' and 'pnl_pct' in x]
    w=[x for x in st if x['pnl_pct']>0]; nd=len(tdates)
    wr=len(w)/len(st)*100 if st else 0; ann=tr*252/nd*100
    return tr*100, ann, mdd*100, shv, len(t), wr, len(pf.gpc())

print(f'池: {len(adata)}只 | 交易日: {len(tdates)}天')
print(f'{"配置":<30s} {"总收益":>8s} {"年化":>7s} {"回撤":>6s} {"夏普":>6s} {"胜率":>5s} {"交易":>5s} {"持仓":>4s}')
print('-' * 75)
for label, tol, mm in [('原始(5%容差 $500)', 0.05, 500), ('优化(2%容差 $100)', 0.02, 100)]:
    tr, ann, mdd, sh, cnt, wr, hc = run(tol, mm)
    print(f'{label:<30s} {tr:+7.2f}% {ann:6.1f}% {mdd:5.1f}% {sh:5.4f} {wr:5.1f}% {cnt:5d} {hc:4d}只')
print('=' * 75)
