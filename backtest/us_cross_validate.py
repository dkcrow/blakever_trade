"""
交叉验证: us100_backtest 引擎 + 大盘双指数恐慌过滤
对比: 关闭 vs 大盘80%·25日 (SPX+NDX 双跌破MA25则空仓)
区间: 3年+5年
"""
import sys, os, math, json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'

# ---- us100_backtest 同款引擎 ----
class USPortfolio:
    def __init__(self, cash=10000, comm_per_share=0.005, slippage=0.0005):
        self.initial_cash = cash; self.cash = cash
        self.comm = comm_per_share; self.slippage = slippage
        self.positions = {}; self.trade_log = []; self.daily_values = []
    @property
    def total_value(self):
        return self.cash + sum(p['shares']*p.get('last_price',p['cost_price']) for p in self.positions.values())
    def update_prices(self, pdict):
        for c,p in pdict.items():
            if c in self.positions: self.positions[c]['last_price']=p
    def buy(self, code, shares, price, date, reason=''):
        price*=(1+self.slippage); tv=shares*price; comm=shares*self.comm
        if tv+comm>self.cash+0.01: return False
        self.cash-=tv+comm
        if code in self.positions:
            o=self.positions[code]; ts=o['shares']+shares
            self.positions[code]={'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*price)/ts,'last_price':price,'buy_date':o.get('buy_date',date)}
        else:
            self.positions[code]={'shares':shares,'cost_price':price,'last_price':price,'buy_date':date}
        self.trade_log.append({'date':str(date)[:10],'code':code,'name':code,'action':'BUY','price':round(price,4),'shares':int(shares),'amount':round(tv,2),'commission':round(comm,2),'reason':reason})
        return True
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        price*=(1-self.slippage); pos=self.positions[code]; actual=min(shares,pos['shares'])
        if actual<=0: return False
        tv=actual*price; comm=actual*self.comm; self.cash+=tv-comm; pos['shares']-=actual
        pnl=(price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares']<=0: del self.positions[code]
        self.trade_log.append({'date':str(date)[:10],'code':code,'name':code,'action':'SELL','price':round(price,4),'shares':int(actual),'amount':round(tv,2),'commission':round(comm,2),'pnl_pct':round(pnl,4),'reason':reason})
        return True
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions: return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)
    def record_daily_value(self, date):
        v=self.total_value
        self.daily_values.append({'date':str(date)[:10],'value':round(v,2),'returns':round((v-self.initial_cash)/self.initial_cash,6)})
    def get_position_codes(self): return list(self.positions.keys())

def calc_score(close_full, lookback=25):
    recent=close_full[-(lookback+1):]; y=np.log(np.maximum(recent,1e-10)); x=np.arange(len(y))
    w=np.linspace(1,2,len(y)); slope,intercept=np.polyfit(x,y,1,w=w)
    ann=math.exp(slope*250)-1
    ssr=np.sum(w*(y-(slope*x+intercept))**2); sst=np.sum(w*(y-np.mean(y))**2)
    r2=1-ssr/sst if sst>0 else 0
    return ann*r2, ann

def get_ranked(all_data, prices, date, lookback=25):
    ranked=[]; dt=pd.Timestamp(date)
    for code,df in all_data.items():
        if code not in prices: continue
        mask=df.index<dt; hist=df[mask]
        if len(hist)<lookback+10: continue
        cp=prices[code]
        if cp<=0: continue
        score,ann=calc_score(hist['close'].values,lookback)
        ranked.append({'code':code,'score':score,'price':cp})
    ranked.sort(key=lambda x:x['score'],reverse=True)
    return ranked

# ---- 大盘恐慌检查 (标普500+纳指100 双跌破MA) ----
import akshare as ak
def load_index_data():
    idx={}
    for name,sym in [('SPX','.INX'),('NDX','.NDX')]:
        df=ak.index_us_stock_sina(symbol=sym)
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        idx[name]=df['close']
    return idx

def check_panic(idx_data, dt, ma_period, mode='dual'):
    """mode: 'spx'|'ndx'|'dual' — 单指数或双指数跌破判定"""
    if mode == 'spx':
        s=idx_data['SPX']; mask=s.index<=dt; hist=s.loc[mask]
        return len(hist)>=ma_period and hist.iloc[-1]<hist.iloc[-ma_period:].mean()
    elif mode == 'ndx':
        s=idx_data['NDX']; mask=s.index<=dt; hist=s.loc[mask]
        return len(hist)>=ma_period and hist.iloc[-1]<hist.iloc[-ma_period:].mean()
    else:  # dual
        for idx in ['SPX','NDX']:
            s=idx_data[idx]; mask=s.index<=dt; hist=s.loc[mask]
            if len(hist)<ma_period: return False
            if hist.iloc[-1]>=hist.iloc[-ma_period:].mean(): return False
        return True

# ---- 回测 ----
POOL = ['NVDA','AVGO','AMD','MU','LRCX','ARM','LITE','NFLX','GOOGL','NOW','CRWD','ORCL',
        'DDOG','SNPS','PANW','ZS','NET','EOG','OKE','NEM','FCX','CAT','GE','RTX','AMT',
        'IONQ','RKLB','SPCX']
HN=7; MIN_MONEY=500

def run(all_data, idx_data, trade_dates, panic_ma=0, panic_mode='dual'):
    """panic_ma=0: 关闭; >0: panic_mode=spx|ndx|dual"""
    pf=USPortfolio(cash=10000)
    panic_days=0
    for i,td in enumerate(trade_dates):
        tds=pd.Timestamp(td)
        prices={}
        for code,df in all_data.items():
            m=df.index<=tds
            if m.any(): prices[code]=float(df.loc[m,'close'].iloc[-1])
        pf.update_prices(prices)
        
        # 恐慌检查
        if panic_ma>0 and check_panic(idx_data, tds, panic_ma, panic_mode):
            panic_days+=1
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code,prices[code],td,reason='PANIC')
            pf.record_daily_value(td)
            continue
        
        ranked=get_ranked(all_data,prices,td,25)
        if not ranked:
            pf.record_daily_value(td); continue
        
        targets=[r['code'] for r in ranked][:HN]
        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code,prices[code],td,reason='调出(无目标)')
            pf.record_daily_value(td); continue
        
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                pf.sell_all(code,prices[code],td,reason='调出目标')
        
        tv=pf.total_value; each=tv/len(targets)
        for idx_c,code in enumerate(targets):
            if code not in prices: continue
            price=prices[code]; cv=0
            if price<=0 or pd.isna(price): continue
            if code in pf.positions: cv=pf.positions[code]['shares']*pf.positions[code]['last_price']
            diff=each-cv
            if abs(diff)<each*0.05 and cv>0: continue
            if diff>0:
                sh=int(diff/price)
                if sh>0 and sh*price>=MIN_MONEY: pf.buy(code,sh,price,td,reason=f'排名{idx_c+1}')
        
        pf.record_daily_value(td)
    
    # 绩效计算
    vals=[d['value'] for d in pf.daily_values]
    fv=vals[-1]; tr=(fv-pf.initial_cash)/pf.initial_cash
    peak,mdd=vals[0],0
    for v in vals:
        if v>peak: peak=v
        if peak>0: dd=(peak-v)/peak
        if dd>mdd: mdd=dd
    sh=0
    if len(vals)>1:
        dr=np.diff(vals)/vals[:-1]
        sh=(np.mean(dr)/np.std(dr)*np.sqrt(252)) if np.std(dr)>0 else 0
    trades=pf.trade_log
    sells=[t for t in trades if t['action']=='SELL' and 'pnl_pct' in t]
    wins=[t for t in sells if t['pnl_pct']>0]
    wr=len(wins)/len(sells)*100 if sells else 0
    return {'total_return':round(tr*100,1),'cagr':round(tr*252/len(trade_dates)*100,1),
            'max_dd':round(mdd*100,1),'sharpe':round(sh,2),'trades':len(trades),
            'win_rate':round(wr,1),'panic_days':panic_days,'final_value':round(fv,2)}

# ---- 主流程 ----
idx_data = load_index_data()
for name,s in idx_data.items():
    print(f'{name}: {len(s)}条 {s.index[0].strftime("%Y-%m-%d")}~{s.index[-1].strftime("%Y-%m-%d")}')

periods = [
    ('3年','2023-06-25','2026-06-25'),
    ('5年','2021-06-25','2026-06-25'),
]

results = {}
for pname, start, end in periods:
    print(f'\n{"="*60}')
    print(f'[{pname}] {start} ~ {end}')
    print(f'{"="*60}')
    
    # 加载数据
    all_data={}
    for sym in POOL:
        fp=DATA_DIR/f'{sym}.csv'
        if not fp.exists(): continue
        df=pd.read_csv(fp)
        # 统一列名: 全小写, 合并 last/close
        df.columns=[c.lower().strip() for c in df.columns]
        rmap={c:'close' for c in df.columns if c in ('last','adj close') and 'close' not in df.columns}
        if rmap: df=df.rename(columns=rmap)
        # 若有 last 和 close 同时存在, 删掉 last
        if 'last' in df.columns and 'close' in df.columns:
            df=df.drop(columns=['last'])
        elif 'last' in df.columns:
            df=df.rename(columns={'last':'close'})
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        mask=(df.index>=start)&(df.index<=end)
        df=df[mask]
        if len(df)>=25: all_data[sym]=df
    
    td=sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
    td=[d for d in td if start<=d<=end]
    print(f'有效: {len(all_data)}只, 交易日: {len(td)}')
    
    r0=run(all_data,idx_data,td,0)
    results[f'{pname}_off']=r0
    print(f'关闭:        +{r0["total_return"]:.1f}% 年化{r0["cagr"]:.1f}% 回撤-{r0["max_dd"]:.1f}% 夏普{r0["sharpe"]:.2f}')
    
    for ma in [5,10,15,25]:
        for mode,mlabel in [('spx','仅标普'),('ndx','仅纳指'),('dual','双指数')]:
            r=run(all_data,idx_data,td,ma,mode)
            results[f'{pname}_{mode}{ma}']=r
            marker=''
            if r['total_return']>r0['total_return'] and r['max_dd']<r0['max_dd']:
                marker=' ★'
            print(f'{mlabel}{ma:2d}日:   +{r["total_return"]:.1f}% 年化{r["cagr"]:.1f}% 回撤-{r["max_dd"]:.1f}% 夏普{r["sharpe"]:.2f} 恐慌{r["panic_days"]}天{marker}')

print(f'\n{"="*80}')
print('单指数 vs 双指数 对比 (★=累计>关闭 且 回撤<关闭)')
print(f'{"="*80}')
for pname,s,e in periods:
    r0=results[f'{pname}_off']
    print(f'\n[{pname}] 关闭: +{r0["total_return"]:.1f}%/回撤-{r0["max_dd"]:.1f}%/夏普{r0["sharpe"]:.2f}')
    print(f'{"模式":<20} {"5日":>12} {"10日":>12} {"15日":>12} {"25日":>12}')
    for mode,mlabel in [('spx','仅标普500'),('ndx','仅纳指100'),('dual','双指数(与)')]:
        vals=[]
        for ma in [5,10,15,25]:
            r=results[f'{pname}_{mode}{ma}']
            m=' ★' if r['total_return']>r0['total_return'] and r['max_dd']<r0['max_dd'] else ''
            tr=r['total_return']; dd=r['max_dd']
            vals.append(f'+{tr:.0f}%/-{dd:.0f}%{m}')
        print(f'{mlabel:<20} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12} {vals[3]:>12}')

print('\n完成!')