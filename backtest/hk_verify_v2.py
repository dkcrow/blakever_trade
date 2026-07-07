"""
交叉验证v2: 完全复制 hk_live_report.py 引擎 + 恒生科技恐慌过滤
"""
import sys, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT=Path(__file__).parent.parent; HK_DIR=PROJECT_ROOT/'data'/'storage'/'stock_data'/'hk'

HK_POOL=['00700','09999','09988','03690','01810','09618','09888','09961','01024','02015',
         '01211','02269','06181','01929','02331','00992','00981','01347','09626','09880',
         '02513','02382','01357','02018','02388','00005','00388','00522','00669','09901',
         '09633','01038','09868','01057','02628','01109','02057']
PARAMS={'holdings_num':5}; HK_COMM=0.001; HK_STAMP=0.0013; HK_FEE=0.0000565; SLIP=0.001; SCORE_THR=0.5

# ---- hk_live_report 同款 calc_score ----
def calc_score(closes):
    x=np.arange(len(closes)); y=np.log(closes)
    mask=~(np.isnan(y)|np.isinf(y)); x_m=x[mask]; y_m=y[mask]
    if len(x_m)<5: return -999
    w=np.linspace(1,2,len(x_m))
    slope,intercept=np.polyfit(x_m,y_m,1,w=w)
    ann=np.exp(slope*250)
    fitted=slope*x_m+intercept; res=y_m-fitted
    ss_res=np.sum(w*res**2); ss_tot=np.sum(w*(y_m-np.mean(y_m))**2)
    r2=1-ss_res/ss_tot if ss_tot>0 else 0
    return (ann-1)*r2

# ---- hk_live_report 同款 get_ranked ----
def get_ranked(all_data,prices,date):
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

# ---- hk_live_report 同款 Portfolio ----
class HKPortfolio:
    def __init__(self): self.cash=1_000_000; self.positions={}; self.trade_log=[]
    @property
    def total_value(self):
        return self.cash+sum(p['shares']*p.get('last_price',p['cost_price']) for p in self.positions.values())
    def get_position_codes(self): return list(self.positions.keys())

# ---- 恒生科技 ----
import akshare as ak
htech=ak.stock_hk_index_daily_sina(symbol='HSTECH')
htech['date']=pd.to_datetime(htech['date']); htech=htech.set_index('date').sort_index()
htech_c=htech['close']

def check_panic(dt,ma):
    m=htech_c.index<=dt; h=htech_c.loc[m]
    return len(h)>=ma and float(h.iloc[-1])<float(h.iloc[-ma:].mean())

# ---- 回测(完全复制 hk_live_report 循环) ----
def run(all_data,td_list,panic_ma=0):
    pf=HKPortfolio(); hn=PARAMS['holdings_num']; pd_cnt=0; daily_vals=[]
    for date in td_list:
        d_str=date.strftime('%Y-%m-%d'); tds=pd.Timestamp(date)
        # 获取当日价格(精确匹配, hk_live同款)
        prices={}
        for code in all_data:
            m=all_data[code].index==date
            if m.any(): prices[code]=float(all_data[code].loc[date,'close'])
        if len(prices)<hn: continue  # hk_live同款: 不足hn只则跳过
        
        # 恐慌检查
        if panic_ma>0 and check_panic(tds,panic_ma):
            pd_cnt+=1
            for code in list(pf.get_position_codes()):
                p=prices.get(code)
                if not p: continue
                pos=pf.positions[code]; sp=p*(1-SLIP); tv=pos['shares']*sp
                comm=max(tv*HK_COMM,5); stamp=tv*HK_STAMP; tfee=tv*HK_FEE
                pf.cash+=tv-comm-stamp-tfee; pf.trade_log.append({'date':d_str,'action':'PANIC','code':code})
                del pf.positions[code]
            daily_vals.append(pf.total_value); continue
        
        ranked=get_ranked(all_data,prices,date)
        targets=[r for r in ranked if r['score']>=SCORE_THR][:hn]
        target_codes=set(r['code'] for r in targets)
        current_codes=set(pf.get_position_codes())
        
        # 卖出非目标
        for code in list(current_codes):
            if code not in target_codes:
                p=prices.get(code)
                if not p: continue
                pos=pf.positions[code]; sp=p*(1-SLIP); tv=pos['shares']*sp
                comm=max(tv*HK_COMM,5); stamp=tv*HK_STAMP; tfee=tv*HK_FEE
                pf.cash+=tv-comm-stamp-tfee; pf.trade_log.append({'date':d_str,'action':'SELL','code':code})
                del pf.positions[code]
                current_codes.discard(code)
        
        # 买入(hk_live同款: 新目标等权)
        new_targets=[r for r in targets if r['code'] not in current_codes]
        if new_targets:
            available=pf.cash*0.95; per=available/len(new_targets)
            for r in new_targets:
                bp=r['price']*(1+SLIP); sh=int(per/bp/100)*100
                if sh<100: continue
                cost=sh*bp; comm=max(cost*HK_COMM,5); stamp=0; tfee=cost*HK_FEE
                pf.cash-=cost+comm+stamp+tfee
                pf.positions[r['code']]={'shares':sh,'cost_price':bp,'last_price':r['price']}
                pf.trade_log.append({'date':d_str,'action':'BUY','code':r['code']})
        
        daily_vals.append(pf.total_value)
    
    vals=daily_vals
    if len(vals)<2: return {}
    tr=(vals[-1]/vals[0]-1)*100; days=len(vals)
    cagr=((vals[-1]/vals[0])**(252/days)-1)*100
    peak=vals[0]; mdd=0
    for v in vals:
        if v>peak: peak=v
        dd=(v-peak)/peak*100
        if dd<mdd: mdd=dd
    mdd=abs(mdd)
    dr=np.diff(vals)/vals[:-1]
    sh=np.mean(dr)/np.std(dr)*np.sqrt(252) if len(dr)>1 and np.std(dr)>0 else 0
    sells=[t for t in pf.trade_log if t['action']=='SELL' or t['action']=='PANIC']
    wins=[t for t in pf.trade_log if t['action']=='SELL']  # only count real sells for win rate
    wr=len(wins)/len(sells)*100 if sells else 0
    return {'total':round(tr,1),'cagr':round(cagr,1),'mdd':round(mdd,1),
            'sh':round(sh,2),'t':len(pf.trade_log),'wr':round(wr,1),'pd':pd_cnt,
            'final':round(vals[-1],0),'val_days':len(vals)}

# 加载(完全复制 hk_live_report)
all_data={}
for code in HK_POOL:
    fp=HK_DIR/f'hk{code}.csv'
    if not fp.exists(): continue
    df=pd.read_csv(fp); df.columns=[c.lower().strip() for c in df.columns]
    if 'date' not in df.columns: print(f'{code}: no date col! cols={list(df.columns)}'); continue
    df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
    # 过滤日期范围(hk_live_report同款: 用START_DATE~END_DATE)
    for start,end in [('2021-06-25','2026-06-26'),('2023-06-25','2026-06-26')]:
        pass  # 在后面per-period处理
    if len(df)>35: all_data[code]=df
print(f'加载: {len(all_data)}/{len(HK_POOL)}只')

periods={'3年':('2023-06-25','2026-06-26'),'5年':('2021-06-25','2026-06-26')}

for pname,(start,end) in periods.items():
    # 过滤日期范围
    period_data={}
    for code,df in all_data.items():
        m=(df.index>=start)&(df.index<=end)
        df_p=df[m]
        if len(df_p)>=25: period_data[code]=df_p
    
    td=sorted(set().union(*[set(df.index) for df in period_data.values()]))
    td=[d for d in td if start<=d.strftime('%Y-%m-%d')<=end]
    print(f'\n[{pname}] {len(period_data)}只/{len(td)}交易日')
    
    r0=run(period_data,td)
    t0=r0['total']; c0=r0['cagr']; d0=r0['mdd']; s0=r0['sh']; v0=r0['val_days']
    print(f'关闭:     +{t0}% 年化{c0}% 回撤-{d0}% 夏普{s0} 有效天{v0}')
    
    for ma in [5,25]:
        r=run(period_data,td,ma)
        t=r['total']; c=r['cagr']; d=r['mdd']; s=r['sh']; p=r['pd']
        m=' ★' if r['total']>r0['total'] and r['mdd']<r0['mdd'] else ''
        print(f'恒生科技{ma:2d}日: +{t}% 年化{c}% 回撤-{d}% 夏普{s} 恐慌{p}天{m}')

print('\n完成!')
