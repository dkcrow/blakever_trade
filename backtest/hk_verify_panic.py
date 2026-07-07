"""
交叉验证: hk_live_report 引擎 + 恒生科技指数恐慌过滤
"""
import sys, math, warnings, json, smtplib
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import numpy as np; import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
HK_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'hk'

# ---- hk_live_report.py 同款配置 ----
HK_POOL = ['00700','09999','09988','03690','01810','09618','09888','09961','01024','02015',
           '01211','02269','06181','01929','02331','00992','00981','01347','09626','09880',
           '02513','02382','01357','02018','02388','00005','00388','00522','00669','09901',
           '09633','01038','09868','01057','02628','01109','02057']
HN=5; SCORE_THRESHOLD=0.5; HK_COMM=0.001; HK_STAMP=0.0013; HK_TRADE_FEE=0.0000565; SLIP=0.001

def calc_score_hk(df_slice):
    x_m=np.arange(len(df_slice)); y_m=np.log(df_slice.values)
    if len(x_m)<5: return -99
    w=np.linspace(1,2,len(x_m))
    slope,_=np.polyfit(x_m,y_m,1,w=w); ann=np.exp(slope*250)
    fitted=slope*x_m+_; res=y_m-fitted
    ss_res=np.sum(w*res**2); ss_tot=np.sum(w*(y_m-np.mean(y_m))**2)
    r2=1-ss_res/ss_tot if ss_tot>0 else 0
    return (ann-1)*r2

# 恒生科技指数
import akshare as ak
htech=ak.stock_hk_index_daily_sina(symbol='HSTECH')
htech['date']=pd.to_datetime(htech['date']); htech=htech.set_index('date').sort_index()
htech_close=htech['close']
print(f'HSTECH: {len(htech_close)}条 {htech_close.index[0].date()}~{htech_close.index[-1].date()}')

def check_panic(dt, ma):
    m=htech_close.index<=dt; h=htech_close.loc[m]
    return len(h)>=ma and float(h.iloc[-1])<float(h.iloc[-ma:].mean())

# ---- hk_live_report 同款回测 ----
class State:
    def __init__(self): self.cash=1_000_000; self.positions={}; self.trade_log=[]; self.daily_vals=[]

def run(trade_dates, panic_ma=0):
    s=State(); pd_count=0
    for ti,td in enumerate(trade_dates):
        tds=pd.Timestamp(td); ds=td.strftime('%Y-%m-%d')
        prices={}
        for code,df in all_data.items():
            m=df.index<=tds
            if m.any(): prices[code]=float(df.loc[m,'close'].iloc[-1])
        
        # panic
        if panic_ma>0 and check_panic(tds,panic_ma):
            pd_count+=1
            for code in list(s.positions.keys()):
                p=prices.get(code)
                if not p: continue
                pos=s.positions[code]; sp=p*(1-SLIP); tv=pos['shares']*sp
                comm=max(tv*HK_COMM,5); stamp=tv*HK_STAMP; tfee=tv*HK_TRADE_FEE
                s.cash+=tv-comm-stamp-tfee; del s.positions[code]
                s.trade_log.append({'date':ds,'action':'PANIC_SELL','code':code})
            tv=s.cash
            for c,pos in s.positions.items():
                tv+=pos['shares']*prices.get(c,pos['cost_price'])
            s.daily_vals.append(tv); continue
        
        # 排名 index < date
        scores=[]
        for code,df in all_data.items():
            if code not in prices: continue
            m=df.index<tds; hist=df.loc[m,'close']
            if len(hist)<26: continue
            score=calc_score_hk(hist.iloc[-25:])
            scores.append((code,score,prices[code]))
        scores.sort(key=lambda x:-x[1])
        targets=[x for x in scores if x[1]>=SCORE_THRESHOLD][:HN]
        
        tc=set(t[0] for t in targets)
        for code in list(s.positions.keys()):
            if code not in tc:
                p=prices.get(code)
                if not p: continue
                pos=s.positions[code]; sp=p*(1-SLIP); tv=pos['shares']*sp
                comm=max(tv*HK_COMM,5); stamp=tv*HK_STAMP; tfee=tv*HK_TRADE_FEE
                pnl=(sp-pos['cost_price'])/pos['cost_price']*100
                s.cash+=tv-comm-stamp-tfee; del s.positions[code]
                s.trade_log.append({'date':ds,'action':'SELL','code':code,'pnl':round(pnl,2)})
        
        new=[t for t in targets if t[0] not in s.positions]
        if new and s.cash>100:
            avail=s.cash*0.95; per=avail/len(new)
            for sym,score,price in new:
                bp=price*(1+SLIP); sh=int(per/bp/100)*100
                if sh<100: continue
                cost=sh*bp; comm=max(cost*HK_COMM,5); stamp=0; tfee=cost*HK_TRADE_FEE
                s.cash-=cost+comm+stamp+tfee
                s.positions[sym]={'shares':sh,'cost_price':bp}
                s.trade_log.append({'date':ds,'action':'BUY','code':sym})
        
        tv=s.cash
        for c,pos in s.positions.items():
            tv+=pos['shares']*prices.get(c,pos['cost_price'])
        s.daily_vals.append(tv)
    
    vals=s.daily_vals
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
    sells=[t for t in s.trade_log if t['action']=='SELL']
    wins=[t for t in sells if t.get('pnl',0)>0]
    wr=len(wins)/len(sells)*100 if sells else 0
    return {'total':round(tr,1),'cagr':round(cagr,1),'mdd':round(mdd,1),
            'sh':round(sh,2),'t':len(s.trade_log),'wr':round(wr,1),'pd':pd_count,'final':round(vals[-1],0)}

print('\n加载港股成分股...')
all_data={}
for code in HK_POOL:
    fp=HK_DIR/f'hk{code}.csv'
    if fp.exists():
        df=pd.read_csv(fp); df.columns=[c.lower() for c in df.columns]
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        if len(df)>35: all_data[code]=df
print(f'有效: {len(all_data)}/{len(HK_POOL)}')

for pname,start,end in [('3年','2023-06-25','2026-06-26'),('5年','2021-06-25','2026-06-26')]:
    td_all=sorted(set().union(*[set(df.index) for df in all_data.values()]))
    td=[d for d in td_all if start<=d.strftime('%Y-%m-%d')<=end]
    print(f'\n[{pname}] {len(td)}交易日')
    
    r0=run(td)
    print(f'关闭:     +{r0["total"]}% 年化{r0["cagr"]}% 回撤-{r0["mdd"]}% 夏普{r0["sh"]} 终值HK${r0["final"]:,}')
    
    for ma in [5,10,15,20,25]:
        r=run(td,ma)
        m=' ★' if r['total']>r0['total'] and r['mdd']<r0['mdd'] else ''
        print(f'恒生科技{ma:2d}日: +{r["total"]}% 年化{r["cagr"]}% 回撤-{r["mdd"]}% 夏普{r["sh"]} 恐慌{r["pd"]}天{m}')

# 发邮件
html=f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="font-family:Microsoft YaHei;padding:20px;">
<h2>港股版 恒生科技指数恐慌过滤 · 交叉验证</h2>
<table border=1 cellpadding=6 cellspacing=0 style="border-collapse:collapse;font-size:12px;">
<tr><th>周期</th><th>配置</th><th>累计</th><th>年化</th><th>回撤</th><th>夏普</th><th>恐慌天</th></tr>
"""
for pname,start,end in [('3年','2023-06-25','2026-06-26'),('5年','2021-06-25','2026-06-26')]:
    td_all=sorted(set().union(*[set(df.index) for df in all_data.values()]))
    td=[d for d in td_all if start<=d.strftime('%Y-%m-%d')<=end]
    r0=run(td)
    html+=f'<tr><td rowspan=6>{pname}</td><td>关闭</td><td>+{r0["total"]}%</td><td>{r0["cagr"]}%</td><td>-{r0["mdd"]}%</td><td>{r0["sh"]}</td><td>0</td></tr>'
    for ma in [5,10,15,20,25]:
        r=run(td,ma)
        star=' ★' if r['total']>r0['total'] and r['mdd']<r0['mdd'] else ''
        html+=f'<tr><td>恒生科技{ma}日{star}</td><td>+{r["total"]}%</td><td>{r["cagr"]}%</td><td>-{r["mdd"]}%</td><td>{r["sh"]}</td><td>{r["pd"]}</td></tr>'
html+='</table></body></html>'

SMTP_SERVER,SMTP_PORT="smtp.qq.com",465; SENDER="848786642@qq.com"; PASSWORD="ljbtvacrctjobfed"; RECEIVER="848786642@qq.com"
msg=MIMEMultipart(); msg["Subject"]=f"[港股交叉验证] 恒生科技指数恐慌过滤"; msg["From"]=SENDER; msg["To"]=RECEIVER
msg.attach(MIMEText(html,"html","utf-8"))
with smtplib.SMTP_SSL(SMTP_SERVER,SMTP_PORT) as srv: srv.login(SENDER,PASSWORD); srv.send_message(msg)
print('\n[OK] 邮件已发送')
