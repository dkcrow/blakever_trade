#!/usr/bin/env python3
"""七星美股版 恐慌过滤MA周期寻优 (80%阈值固定, 5/10/15/20/25/250日 vs 关闭)
基于us100_backtest规则(35池/7只等权/无score阈值)。1年+3年+5年, 含触发统计。
"""
import warnings, io, contextlib
from pathlib import Path
import numpy as np, pandas as pd, math
warnings.filterwarnings('ignore')

POOL_SYMBOLS = [
    'NVDA','AVGO','AMD','MU','LRCX','ARM','LITE',
    'NFLX','GOOGL','NOW','CRWD','ORCL','DDOG','SNPS',
    'PANW','ZS','NET','EOG','OKE','NEM','FCX',
    'CAT','GE','RTX','AMT','IONQ','RKLB','SPCX',
]
DATA_DIR=Path('data/storage/stock_data/us')
CASH=10000; COMM=0.005; SLIP=0.0005; HOLDINGS=7
START='2021-06-01'; END='2026-04-23'

all_data={}
for sym in POOL_SYMBOLS:
    fp=DATA_DIR/f'{sym}.csv'
    if not fp.exists(): continue
    df=pd.read_csv(fp)
    remap={}
    for c in df.columns:
        cl=c.lower().strip()
        if cl=='date' and c!='date': remap[c]='date'
        elif cl in ('close','last') and c!='close': remap[c]='close'
        elif cl=='open' and c!='open': remap[c]='open'
        elif cl=='high' and c!='high': remap[c]='high'
        elif cl=='low' and c!='low': remap[c]='low'
        elif cl=='volume' and c!='volume': remap[c]='volume'
    if remap: df=df.rename(columns=remap)
    df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
    df=df[(df.index>=START)&(df.index<=END)]
    if len(df)>=25: all_data[sym]=df

trade_dates=sorted(set().union(*[d.index.strftime('%Y-%m-%d') for d in all_data.values()]))
trade_dates=[d for d in trade_dates if START<=d<=END]

def calc_score(closes):
    recent=closes[-(25+1):]; y=np.log(np.maximum(recent,1e-10))
    x=np.arange(len(y)); w=np.linspace(1,2,len(y))
    s,i=np.polyfit(x,y,1,w=w)
    ann=math.exp(s*250)-1
    ssr=np.sum(w*(y-(s*x+i))**2); sst=np.sum(w*(y-np.mean(y))**2)
    r2=1-ssr/sst if sst>0 else 0
    return ann*r2

def get_ranked(prices,date):
    ranked=[]
    for code,df in all_data.items():
        if code not in prices: continue
        mask=df.index<pd.Timestamp(date); hist=df[mask]
        if len(hist)<35: continue
        cp=prices[code]
        if cp<=0: continue
        score=calc_score(hist['close'].values)
        ranked.append({'code':code,'score':score,'price':cp})
    ranked.sort(key=lambda x:x['score'],reverse=True)
    return ranked

class USPortfolio:
    def __init__(s): s.cash=CASH; s.positions={}; s.trade_log=[]; s.daily_values=[]
    @property
    def total_value(s): return s.cash+sum(p['shares']*p.get('last_price',p['cost_price']) for p in s.positions.values())
    def update_prices(s,pd): 
        for c,p in pd.items():
            if c in s.positions: s.positions[c]['last_price']=p
    def buy(s,code,sh,price,date):
        p=price*(1+SLIP); tv=p*sh; c=sh*COMM
        if tv+c>s.cash+0.01: return False
        s.cash-=tv+c
        if code in s.positions:
            o=s.positions[code]; ts=o['shares']+sh
            s.positions[code]={'shares':ts,'cost_price':(o['shares']*o['cost_price']+sh*p)/ts,'last_price':p,'buy_date':o.get('buy_date',date)}
        else: s.positions[code]={'shares':sh,'cost_price':p,'last_price':p,'buy_date':date}
        s.trade_log.append({'date':date,'action':'BUY','code':code}); return True
    def sell_all(s,code,price,date,reason=''):
        if code not in s.positions: return False
        p=price*(1-SLIP); pos=s.positions[code]; a=pos['shares']; tv=a*p; c=a*COMM
        s.cash+=tv-c
        pnl=(p-pos['cost_price'])/pos['cost_price']*100 if pos['cost_price']>0 else 0
        s.trade_log.append({'date':date,'action':'SELL','code':code,'pnl_pct':round(pnl,2)})
        del s.positions[code]; return True
    def get_position_codes(s): return list(s.positions.keys())

def seg_stats(idx):
    if not idx: return 0,0,0.0,0
    idx=sorted(idx); segs=[]; start=prev=idx[0]
    for x in idx[1:]:
        if x==prev+1: prev=x
        else: segs.append(prev-start+1); start=prev=x
    segs.append(prev-start+1)
    return len(segs),sum(segs),sum(segs)/len(segs),max(segs)

def run(td_list, lb):
    pf=USPortfolio(); hn=HOLDINGS; panic_idx=[]; enable=(lb is not None)
    for i,td in enumerate(td_list):
        tds=pd.Timestamp(td)
        prices={}
        for code in all_data:
            m=all_data[code].index<=tds
            if m.any(): prices[code]=float(all_data[code].loc[m,'close'].iloc[-1])
        if len(prices)<hn: continue
        panic=False
        if enable:
            thr=0.80; below=0; total=0
            for code,df in all_data.items():
                hist=df.loc[df.index<=tds,'close']
                if len(hist)<lb: continue
                cur=prices.get(code,float(hist.iloc[-1]))
                if cur<=0: continue
                ma=float(hist.iloc[-lb:].mean()); total+=1
                if cur<ma: below+=1
            if total>0 and below/total>thr: panic=True; panic_idx.append(i)
        pf.update_prices(prices)
        if panic:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code,prices[code],td,'恐慌期空仓防守')
            pf.daily_values.append({'date':td,'value':pf.total_value})
            continue
        ranked=get_ranked(prices,td)
        if not ranked: pf.daily_values.append({'date':td,'value':pf.total_value}); continue
        targets=[r['code'] for r in ranked[:hn]]
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                pf.sell_all(code,prices[code],td,'调出目标')
        pf.update_prices(prices)
        tv=pf.total_value; each=tv/hn
        for code in targets:
            if code not in prices: continue
            cv=0
            if code in pf.positions: cv=pf.positions[code]['shares']*pf.positions[code]['last_price']
            diff=each-cv
            if abs(diff)<each*0.05 and cv>0: continue
            if diff>0:
                sh=int(diff/prices[code])
                if sh>0 and sh*prices[code]>=500: pf.buy(code,sh,prices[code],td)
        pf.daily_values.append({'date':td,'value':pf.total_value})
    vals=[d['value'] for d in pf.daily_values]
    if not vals: return dict(tr=0,cagr=0,dd=0,sh=0,nt=0,wr=0,cnt=0,tot=0,avg=0,mx=0)
    fv=vals[-1]; tr=(fv/CASH-1)*100
    dr=np.diff(vals)/vals[:-1] if len(vals)>1 else []
    ann=(fv/CASH)**(252/max(len(dr),1))-1
    pk=vals[0]; mdd=0
    for v in vals:
        if v>pk: pk=v
        dd=(pk-v)/pk if pk>0 else 0
        if dd>mdd: mdd=dd
    sh=0
    if len(dr)>0 and np.std(dr)>0: sh=np.mean(dr)/np.std(dr)*np.sqrt(252)
    se=[t for t in pf.trade_log if t['action']=='SELL']
    ws=[t for t in se if t.get('pnl_pct',0)>0]
    wr=len(ws)/len(se)*100 if se else 0
    cnt,tot,avg,mx=seg_stats(panic_idx)
    return dict(tr=tr,cagr=ann*100,dd=mdd*100,sh=sh,nt=len(pf.trade_log),wr=wr,cnt=cnt,tot=tot,avg=avg,mx=mx)

CONFIGS=[('关闭',None),('80%·5日',5),('80%·10日',10),('80%·15日',15),('80%·20日',20),('80%·25日',25),('80%·250日',250)]
PERIODS=[('5年','2021-06-01','2026-04-23'),('3年','2023-06-01','2026-04-23'),('1年','2025-04-01','2026-04-23')]

for label,sd,ed in PERIODS:
    td_all=[d for d in trade_dates if sd<=d<=ed]
    print(f"\n{'='*120}")
    print(f"  七星美股版 恐慌过滤MA周期寻优 — {label} ({len(td_all)}交易日) [35池/7只/阈值80%]")
    print('='*120)
    print(f"  {'配置':<12}{'累计':>10}{'年化CAGR':>9}{'回撤':>8}{'夏普':>7}{'交易':>6}{'胜率':>6}{'触发次数':>9}{'空仓天数':>9}{'平均段长':>9}{'最长段':>7}")
    print('-'*120)
    base=None
    for name,lb in CONFIGS:
        r=run(td_all,lb)
        if base is None: base=r
        diff='' if r is base else f"累计{r['tr']-base['tr']:+.0f}pp 回撤{r['dd']-base['dd']:+.1f}pp 夏普{r['sh']-base['sh']:+.2f}"
        print(f"  {name:<12}{r['tr']:>+9.1f}%{r['cagr']:>8.1f}%{r['dd']:>7.1f}%{r['sh']:>7.2f}"
              f"{r['nt']:>6}{r['wr']:>5.0f}%{r['cnt']:>9}{r['tot']:>9}{r['avg']:>9.1f}{r['mx']:>7}   {diff}")
    print('='*120)
print("\n完成。")
