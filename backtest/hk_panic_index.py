"""
七星港股版 大盘指数行情判断
恒生指数(HSI) / 恒生科技指数(HSTECH) 跌破MA → 空仓防守
3年/5年回测
"""
import sys, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
HK_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'hk'

# 港股池
HK_POOL = ['00700','09999','09988','03690','01810','09618','09888','09961','01024','02015',
           '01211','02269','06181','01929','02331','00992','00981','01347','09626','09880',
           '02513','02382','01357','02018','02388','00005','00388','00522','00669','09901',
           '09633','01038','09868','01057','02628','01109','02057']
HK_NAME = {'00700':'腾讯','09999':'网易','09988':'阿里','03690':'美团','01810':'小米',
           '09618':'京东','09888':'百度','09961':'携程','01024':'快手','02015':'理想',
           '01211':'比亚迪','02269':'药明生物','06181':'老铺黄金','01929':'周大福',
           '02331':'李宁','00992':'联想','00981':'中芯国际','01347':'华虹半导体',
           '09626':'B站','09880':'优必选','02513':'智谱','02382':'舜宇','01357':'美图',
           '02018':'瑞声','02388':'中银香港','00005':'汇丰','00388':'港交所',
           '00522':'ASMPT','00669':'创科','09901':'新东方在线','09633':'农夫山泉',
           '01038':'长建','09868':'小鹏','01057':'浙江沪杭甬','02628':'中国人寿',
           '01109':'华润置地','02057':'中通快递'}

HN = 5; SCORE_THRESHOLD = 0.5
HK_COMM = 0.001; HK_STAMP = 0.0013; HK_TRADE_FEE = 0.0000565; SLIP = 0.001

def calc_score(df_slice):
    x_m=np.arange(len(df_slice)); y_m=np.log(df_slice.values)
    if len(x_m)<5: return -99
    w=np.linspace(1,2,len(x_m))
    slope,_=np.polyfit(x_m,y_m,1,w=w); ann=np.exp(slope*250)
    fitted=slope*x_m+_; res=y_m-fitted
    ss_res=np.sum(w*res**2); ss_tot=np.sum(w*(y_m-np.mean(y_m))**2)
    r2=1-ss_res/ss_tot if ss_tot>0 else 0
    return (ann-1)*r2

# 获取指数
import akshare as ak
idx_data={}
for name,sym in [('HSI','HSI'),('HSTECH','HSTECH')]:
    try:
        df=ak.stock_hk_index_daily_sina(symbol=sym)
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        idx_data[name]=df['close']
        print(f'{name}: {len(df)}条 {df.index[0].date()}~{df.index[-1].date()}')
    except Exception as e:
        print(f'{name}: fail {e}')

def check_panic(idx_name, dt, ma):
    s=idx_data[idx_name]; mask=s.index<=dt; hist=s.loc[mask]
    return len(hist)>=ma and hist.iloc[-1]<hist.iloc[-ma:].mean()

# 回测
class State:
    def __init__(self): self.cash=1_000_000; self.positions={}; self.trade_log=[]; self.daily_vals=[]

def run(all_data, trade_dates, panic_idx=None, panic_ma=0):
    s=State(); panic_days=0
    for td in trade_dates:
        tds=pd.Timestamp(td); date_str=td.strftime('%Y-%m-%d')
        prices={}
        for code,df in all_data.items():
            m=df.index<=tds
            if m.any(): prices[code]=float(df.loc[m,'close'].iloc[-1])
        
        # 恐慌
        panic=False
        if panic_idx and panic_ma>0:
            panic=check_panic(panic_idx,tds,panic_ma)
        if panic:
            panic_days+=1
            for code in list(s.positions.keys()):
                p=prices.get(code)
                if not p: continue
                pos=s.positions[code]; sp=p*(1-SLIP); tv=pos['shares']*sp
                comm=max(tv*HK_COMM,5); stamp=tv*HK_STAMP; tfee=tv*HK_TRADE_FEE
                s.cash+=tv-comm-stamp-tfee; s.trade_log.append({'date':date_str,'action':'PANIC','code':code})
                del s.positions[code]
            total=s.cash
            for c,pos in s.positions.items():
                total+=pos['shares']*prices.get(c,pos['cost_price'])
            s.daily_vals.append(total)
            continue
        
        # 排名 (index < date)
        scores=[]
        for code,df in all_data.items():
            if code not in prices: continue
            m=df.index<tds; hist=df.loc[m,'close']
            if len(hist)<26: continue
            score=calc_score(hist.iloc[-25:])
            scores.append((code,score,prices[code]))
        scores.sort(key=lambda x:-x[1])
        targets=[x for x in scores if x[1]>=SCORE_THRESHOLD][:HN]
        
        target_codes=set(t[0] for t in targets)
        for code in list(s.positions.keys()):
            if code not in target_codes:
                p=prices.get(code)
                if not p: continue
                pos=s.positions[code]; sp=p*(1-SLIP); tv=pos['shares']*sp
                comm=max(tv*HK_COMM,5); stamp=tv*HK_STAMP; tfee=tv*HK_TRADE_FEE
                pnl=(sp-pos['cost_price'])/pos['cost_price']*100
                s.cash+=tv-comm-stamp-tfee; s.trade_log.append({'date':date_str,'action':'SELL','code':code,'pnl':round(pnl,2)})
                del s.positions[code]
        
        new_targets=[t for t in targets if t[0] not in s.positions]
        if new_targets and s.cash>100:
            available=s.cash*0.95; per=available/len(new_targets)
            for sym,score,price in new_targets:
                bp=price*(1+SLIP); sh=int(per/bp/100)*100
                if sh<100: continue
                cost=sh*bp; comm=max(cost*HK_COMM,5); stamp=0; tfee=cost*HK_TRADE_FEE
                s.cash-=cost+comm+stamp+tfee
                s.positions[sym]={'shares':sh,'cost_price':bp}
                s.trade_log.append({'date':date_str,'action':'BUY','code':sym})
        
        total=s.cash
        for c,pos in s.positions.items():
            total+=pos['shares']*prices.get(c,pos['cost_price'])
        s.daily_vals.append(total)
    
    vals=s.daily_vals
    if len(vals)<2: return {}
    tr=(vals[-1]/vals[0]-1)*100; days=len(vals)
    cagr=((vals[-1]/vals[0])**(252/days)-1)*100 if days>0 else 0
    peak=vals[0]; mdd=0
    for v in vals:
        if v>peak: peak=v
        dd=(v-peak)/peak*100
        if dd<mdd: mdd=dd
    mdd=abs(mdd)
    dr=np.diff(vals)/vals[:-1]
    sh=np.mean(dr)/np.std(dr)*np.sqrt(252) if len(dr)>1 and np.std(dr)>0 else 0
    sells=[t for t in s.trade_log if t['action']=='SELL']
    wins=[t for t in sells if t.get('pnl',0)>0]
    wr=len(wins)/len(sells)*100 if sells else 0
    return {'total':round(tr,1),'cagr':round(cagr,1),'mdd':round(mdd,1),
            'sh':round(sh,2),'trades':len(s.trade_log),'wr':round(wr,1),
            'panic_days':panic_days}

# 加载数据
print('\n加载港股成分股...')
all_data={}
for code in HK_POOL:
    fp=HK_DIR/f'hk{code}.csv'
    if fp.exists():
        df=pd.read_csv(fp); df.columns=[c.lower() for c in df.columns]
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        if len(df)>35: all_data[code]=df
print(f'有效: {len(all_data)}/{len(HK_POOL)}')

periods=[('3年','2023-06-25','2026-06-26'),('5年','2021-06-25','2026-06-26')]
mas=[5,10,15,20,25]
modes=[('HSI','恒生指数'),('HSTECH','恒生科技')]

for pname,start,end in periods:
    print(f'\n{"="*60}')
    print(f'[{pname}] {start}~{end}')
    
    td_set=sorted(set().union(*[set(df.index) for df in all_data.values()]))
    td=[d for d in td_set if start<=d.strftime('%Y-%m-%d')<=end]
    print(f'交易日: {len(td)}')
    
    r0=run(all_data,td)
    rt=r0['total']; rc=r0['cagr']; rm=r0['mdd']; rs=r0['sh']
    print(f'关闭:     +{rt}% 年化{rc}% 回撤-{rm}% 夏普{rs}')
    
    for mode,mlabel in modes:
        for ma in mas:
            r=run(all_data,td,mode,ma)
            if r:
                rt2=r['total']; rc2=r['cagr']; rm2=r['mdd']; rs2=r['sh']; pd2=r['panic_days']
                m='' if not (r['total']>r0['total'] and r['mdd']<r0['mdd']) else ' ★'
                print(f'{mlabel}{ma:2d}日: +{rt2}% 年化{rc2}% 回撤-{rm2}% 夏普{rs2} 恐慌{pd2}天{m}')

print('\n完成!')
