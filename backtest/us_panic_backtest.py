#!/usr/bin/env python3
"""七星美股版 80%·15日恐慌过滤回测对比 (成分股>80%跌破MA15→清仓空仓)
复用 us_live_report 规则: 26只池/7只等权/score>=0.5/$0.005股佣金/0.05%滑点。
1年+3年, 含触发统计。
"""
import warnings, io, contextlib
from pathlib import Path
from datetime import datetime
import numpy as np, pandas as pd, math
warnings.filterwarnings('ignore')

POOL = 'NVDA,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,HOOD,WDC,ARM,STX'.split(',')

HOLDINGS_NUM=7; SCORE_THRESHOLD=0.5; COMM=0.005; SLIPPAGE=0.0005; CASH=10000
DATA_DIR=Path('data/storage/stock_data/us')

all_data={}
for sym in POOL:
    fp=DATA_DIR/f'{sym}.csv'
    if fp.exists():
        df=pd.read_csv(fp)
        # normalize columns: Last→close, Close→close, Date→date
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
        if len(df)>35: all_data[sym]=df

def calc_score(closes):
    if len(closes)<5: return -999
    x=np.arange(len(closes)); y=np.log(np.maximum(closes,1e-10))
    mask=~np.isnan(y)&~np.isinf(y); x_m=x[mask]; y_m=y[mask]
    if len(x_m)<5: return -999
    w=np.linspace(1,2,len(x_m))
    slope,intercept=np.polyfit(x_m,y_m,1,w=w)
    ann=math.exp(slope*250)-1
    fitted=slope*x_m+intercept; res=y_m-fitted
    ss_res=np.sum(w*res**2); ss_tot=np.sum(w*(y_m-np.mean(y_m))**2)
    r2=1-ss_res/ss_tot if ss_tot>0 else 0
    return ann*r2

def get_ranked(prices,date):
    ranked=[]
    lb=25
    for code,df in all_data.items():
        if code not in prices: continue
        mask=df.index<pd.Timestamp(date); hist=df[mask]
        if len(hist)<lb+10: continue
        cp=prices[code]
        if cp<=0: continue
        score=calc_score(hist['close'].values)
        ranked.append({'code':code,'score':score,'price':cp})
    ranked.sort(key=lambda x:x['score'],reverse=True)
    return ranked

class USPortfolio:
    def __init__(s,cash=CASH):
        s.cash=cash; s.positions={}; s.trade_log=[]; s.daily_values=[];
        s.comm=COMM; s.slippage=SLIPPAGE
    @property
    def total_value(s):
        return s.cash+sum(p['shares']*p.get('last_price',p['cost_price']) for p in s.positions.values())
    def update_prices(s,pdict):
        for c,p in pdict.items():
            if c in s.positions: s.positions[c]['last_price']=p
    def buy(s,code,shares,price,date):
        p=price*(1+s.slippage); tv=p*shares; c=shares*s.comm
        if tv+c>s.cash+0.01: return False
        s.cash-=tv+c
        if code in s.positions:
            o=s.positions[code]; ts=o['shares']+shares
            s.positions[code]={'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*p)/ts,'last_price':p,'buy_date':o.get('buy_date',date)}
        else:
            s.positions[code]={'shares':shares,'cost_price':p,'last_price':p,'buy_date':date}
        s.trade_log.append({'date':date,'action':'BUY','code':code})
        return True
    def sell_all(s,code,price,date,reason=''):
        if code not in s.positions: return False
        p=price*(1-s.slippage); pos=s.positions[code]; a=pos['shares']; tv=a*p; c=a*s.comm
        s.cash+=tv-c
        pnl=(p-pos['cost_price'])/pos['cost_price']*100 if pos['cost_price']>0 else 0
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

def run(trade_dates, enable_panic):
    pf=USPortfolio(); hn=HOLDINGS_NUM; panic_idx=[]
    for i,td in enumerate(trade_dates):
        tds=pd.Timestamp(td)
        prices={}
        for code in all_data:
            m=all_data[code].index<=tds
            if m.any(): prices[code]=float(all_data[code].loc[m,'close'].iloc[-1])
        if len(prices)<hn: continue
        # 恐慌期判定
        panic=False
        if enable_panic:
            lb=15; thr=0.80; below=0; total=0
            for code,df in all_data.items():
                hist=df.loc[df.index<=tds,'close']
                if len(hist)<lb: continue
                cur=prices.get(code,float(hist.iloc[-1]))
                if cur<=0: continue
                ma=float(hist.iloc[-lb:].mean())
                total+=1
                if cur<ma: below+=1
            if total>0 and below/total>thr:
                panic=True; panic_idx.append(i)
        pf.update_prices(prices)
        if panic:
            for code in list(pf.get_position_codes()):
                if code in prices:
                    pf.sell_all(code,prices[code],td,'恐慌期空仓防守')
            pf.daily_values.append({'date':td,'value':pf.total_value})
            continue
        ranked=get_ranked(prices,td)
        if not ranked:
            pf.daily_values.append({'date':td,'value':pf.total_value})
            continue
        targets=[r['code'] for r in ranked if r['score']>=SCORE_THRESHOLD][:hn]
        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code,prices[code],td,'得分不足/调出')
            pf.daily_values.append({'date':td,'value':pf.total_value})
            continue
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                pf.sell_all(code,prices[code],td,'调出目标')
            # 额外: score跌破阈值也卖
            found=next((r for r in ranked if r['code']==code),None)
            if found and found['score']<SCORE_THRESHOLD and code in prices:
                pf.sell_all(code,prices[code],td,'得分跌破阈值')
        pf.update_prices(prices)
        tv=pf.total_value; each=tv/len(targets)
        for idx_t,code in enumerate(targets):
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

for label,s,e in [('3年','2023-06-01','2026-06-01'),('1年','2025-06-01','2026-06-01')]:
    td_all=[d for d in sorted(set().union(*[set(df.index) for df in all_data.values()])) if s<=d.strftime('%Y-%m-%d')<=e]
    print(f"\n{'='*100}")
    print(f"  七星美股版 80%·15日恐慌过滤 — {label} ({len(td_all)}交易日) [26池/7只等权/score>=0.5]")
    print('='*100)
    off=run(td_all,False)
    on=run(td_all,True)
    for tag,r in [('关闭',off),('80%·15日',on)]:
        extra='' if tag=='关闭' else f"触发{on['cnt']}次 空仓{on['tot']}天 均{on['avg']:.1f}天 最长{on['mx']}天"
        print(f"  {tag}: 累计{r['tr']:+.1f}% 年化{r['cagr']:.1f}% 回撤{r['dd']:.1f}% 夏普{r['sh']:.2f} 交易{r['nt']} 胜率{r['wr']:.0f}%  {extra}")
    print(f"  差异: 累计{on['tr']-off['tr']:+.1f}pp 回撤{on['dd']-off['dd']:+.1f}pp 夏普{on['sh']-off['sh']:+.2f}")
    print('='*100)
print("\n完成。")
