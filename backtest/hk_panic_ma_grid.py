#!/usr/bin/env python3
"""七星港股版 恐慌过滤 MA周期寻优 (80%阈值固定, 测5/10/15/20/25日 vs 关闭)
复用 hk_live_report 全套规则。1年 + 3年, 含触发统计。
"""
import warnings, io, contextlib
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

HK_POOL = [
    '00700','09988','01810','03690','09999','02513','00100','02162','02616','09969',
    '02418','01357','00981','01347','00522','01211','01093','01177','02338','02038',
    '01378','00388','02388','00005','02318','00939','02628','03988','09888','00883',
    '02899','03993','02618','01929','01113','06181','00669',
]
HOLDINGS_NUM=5; SCORE_THRESHOLD=0.5
HK_COMM_RATE=0.001; HK_STAMP_DUTY=0.0013; HK_TRADE_FEE=0.0000565; SLIPPAGE=0.001; CASH=1000000
DATA_DIR=Path('data/storage/stock_data/hk')

all_data={}
for code in HK_POOL:
    fp=DATA_DIR/f'hk{code}.csv'
    if fp.exists():
        df=pd.read_csv(fp); df.columns=[c.lower() for c in df.columns]
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        if len(df)>35: all_data[code]=df

def calc_score(closes):
    if len(closes)<5: return -999
    x=np.arange(len(closes)); y=np.log(closes)
    mask=~np.isnan(y)&~np.isinf(y); x_m=x[mask]; y_m=y[mask]
    if len(x_m)<5: return -999
    w=np.linspace(1,2,len(x_m))
    slope,intercept=np.polyfit(x_m,y_m,1,w=w)
    ann=np.exp(slope*250); fitted=slope*x_m+intercept; res=y_m-fitted
    ss_res=np.sum(w*res**2); ss_tot=np.sum(w*(y_m-np.mean(y_m))**2)
    r2=1-ss_res/ss_tot if ss_tot>0 else 0
    return (ann-1)*r2

def get_ranked(prices,date):
    ranked=[]
    for code,df in all_data.items():
        if code not in prices: continue
        mask=df.index<pd.Timestamp(date); hist=df[mask]
        if len(hist)<35: continue
        cp=prices[code]
        if cp<=0: continue
        score=calc_score(hist['close'].values[-25:])
        ranked.append({'code':code,'score':score,'price':cp})
    ranked.sort(key=lambda x:x['score'],reverse=True)
    return ranked

class HKPortfolio:
    def __init__(s,cash=CASH):
        s.cash=cash; s.positions={}; s.trade_log=[]; s.daily_values=[]
    @property
    def total_value(s):
        return s.cash+sum(p['shares']*p.get('last_price',p['cost_price']) for p in s.positions.values())
    def update_prices(s,pdict):
        for c,p in pdict.items():
            if c in s.positions: s.positions[c]['last_price']=p
    def buy(s,code,shares,price,date):
        p=price*(1+SLIPPAGE); tv=shares*p
        c=max(tv*HK_COMM_RATE,5); f=tv*HK_TRADE_FEE
        if tv+c+f>s.cash+0.01: return False
        s.cash-=tv+c+f
        if code in s.positions:
            o=s.positions[code]; ts=o['shares']+shares
            s.positions[code]={'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*p)/ts,'last_price':p,'buy_date':o.get('buy_date',date)}
        else:
            s.positions[code]={'shares':shares,'cost_price':p,'last_price':p,'buy_date':date}
        s.trade_log.append({'date':date,'action':'BUY','code':code})
        return True
    def sell_all(s,code,price,date,reason=''):
        if code not in s.positions: return False
        p=price*(1-SLIPPAGE); pos=s.positions[code]; a=pos['shares']; tv=a*p
        c=max(tv*HK_COMM_RATE,5); st=tv*HK_STAMP_DUTY; f=tv*HK_TRADE_FEE
        s.cash+=tv-c-st-f
        pnl=(p-pos['cost_price'])/pos['cost_price']*100
        s.trade_log.append({'date':date,'action':'SELL','code':code,'pnl_pct':round(pnl,2)})
        del s.positions[code]
        return True
    def get_position_codes(s): return list(s.positions.keys())

def seg_stats(idx):
    if not idx: return 0,0,0.0,0
    idx=sorted(idx); segs=[]; start=prev=idx[0]
    for x in idx[1:]:
        if x==prev+1: prev=x
        else: segs.append(prev-start+1); start=prev=x
    segs.append(prev-start+1)
    return len(segs),sum(segs),sum(segs)/len(segs),max(segs)

def run(trade_dates, enable, lb):
    pf=HKPortfolio(); hn=HOLDINGS_NUM; panic_idx=[]
    for i,date in enumerate(trade_dates):
        d_str=date.strftime('%Y-%m-%d')
        prices={}
        for code in all_data:
            m=all_data[code].index==date
            if m.any(): prices[code]=float(all_data[code].loc[date,'close'])
        if len(prices)<hn: continue
        panic=False
        if enable:
            thr=0.80; below=0; total=0; td_ts=pd.Timestamp(date)
            for code,df in all_data.items():
                hist=df.loc[df.index<=td_ts,'close']
                if len(hist)<lb: continue
                cur=prices.get(code,float(hist.iloc[-1]))
                if cur<=0: continue
                ma=float(hist.iloc[-lb:].mean())
                total+=1
                if cur<ma: below+=1
            if total>0 and below/total>thr:
                panic=True; panic_idx.append(i)
        ranked=get_ranked(prices,date)
        current_targets=[r for r in ranked if r['score']>=SCORE_THRESHOLD][:hn]
        target_codes=set(r['code'] for r in current_targets)
        if panic:
            for code in list(pf.get_position_codes()):
                sp=prices.get(code,0)
                if sp<=0: sp=pf.positions[code].get('last_price',0)
                if sp<=0: sp=pf.positions[code].get('cost_price',0)
                if sp>0: pf.sell_all(code,sp,d_str,'恐慌期空仓')
                elif code not in prices: pf.sell_all(code,pf.positions[code].get('cost_price',1),d_str,'数据缺失')
        else:
            to_sell=set(pf.get_position_codes())-target_codes
            for code in list(pf.get_position_codes()):
                found=next((r for r in ranked if r['code']==code),None)
                if found and found['score']<SCORE_THRESHOLD: to_sell.add(code)
            for code in to_sell:
                sp=prices.get(code,0)
                if sp<=0: sp=pf.positions[code].get('last_price',0)
                if sp<=0: sp=pf.positions[code].get('cost_price',0)
                if sp>0: pf.sell_all(code,sp,d_str,'得分不足/调出')
                elif code not in prices: pf.sell_all(code,pf.positions[code].get('cost_price',1),d_str,'数据缺失')
        pf.update_prices(prices)
        if not panic:
            new_targets=[r for r in current_targets if r['code'] not in pf.positions and r['code'] in prices]
            if new_targets:
                av=pf.cash*0.95; per=av/len(new_targets)
                for r in new_targets:
                    sh=int(per/r['price']/100)*100
                    if sh>=100: pf.buy(r['code'],sh,r['price'],d_str)
        pf.daily_values.append({'date':d_str,'value':pf.total_value})
    dv=pd.DataFrame(pf.daily_values)
    tr=(dv['value'].iloc[-1]/CASH-1)*100
    dr=dv['value'].pct_change().dropna()
    ann=(dv['value'].iloc[-1]/CASH)**(252/max(len(dr),1))-1
    dd=(dv['value']/dv['value'].cummax()-1).min()*100
    sh=dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0
    se=[t for t in pf.trade_log if t['action']=='SELL']
    ws=[t for t in se if t.get('pnl_pct',0)>0]
    wr=len(ws)/len(se)*100 if se else 0
    cnt,tot,avg,mx=seg_stats(panic_idx)
    return dict(tr=tr,cagr=ann*100,dd=dd,sh=sh,nt=len(pf.trade_log),wr=wr,cnt=cnt,tot=tot,avg=avg,mx=mx)

CONFIGS=[('关闭',False,None),('80%·5日',True,5),('80%·10日',True,10),('80%·15日',True,15),('80%·20日',True,20),('80%·25日',True,25)]

for label,s,e in [('3年','2023-06-18','2026-06-23'),('1年','2025-06-18','2026-06-23')]:
    td_all=[d for d in sorted(set().union(*[set(df.index) for df in all_data.values()])) if s<=d.strftime('%Y-%m-%d')<=e]
    print(f"\n{'='*120}")
    print(f"  七星港股版 恐慌过滤MA周期寻优 — {label} ({len(td_all)}交易日) [37池/5只等权/阈值80%]")
    print('='*120)
    print(f"  {'配置':<12}{'累计':>10}{'年化CAGR':>9}{'回撤':>8}{'夏普':>7}{'交易':>6}{'胜率':>6}{'触发次数':>9}{'空仓天数':>9}{'平均段长':>8}{'最长段':>7}")
    print('-'*120)
    base=None
    for name,en,lb in CONFIGS:
        r=run(td_all,en,lb)
        if base is None: base=r
        diff='' if r is base else f"累计{r['tr']-base['tr']:+.0f}pp 回撤{r['dd']-base['dd']:+.1f}pp 夏普{r['sh']-base['sh']:+.2f}"
        print(f"  {name:<12}{r['tr']:>+9.1f}%{r['cagr']:>8.1f}%{r['dd']:>7.1f}%{r['sh']:>7.2f}"
              f"{r['nt']:>6}{r['wr']:>5.0f}%{r['cnt']:>9}{r['tot']:>9}{r['avg']:>8.1f}{r['mx']:>7}   {diff}")
    print('='*120)
print("\n完成。")
