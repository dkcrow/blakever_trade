"""
交叉验证2: us_live_report.py 引擎 + 仅纳指100·5日 panic
对比 us_cross_validate.py 结果, 验证可信度
"""
import sys, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'

# ---- 从 us_live_report.py 复制的核心 ----
POOL = ['NVDA','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS',
        'EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB',
        'SPCX','COHR','HOOD','WDC','ARM','STX']
HN = 7
SCORE_THRESHOLD = 0.5

def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y)); w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope * x + intercept)) ** 2)
    sst = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann * r2

# ---- 纳指100 panic ----
import akshare as ak
ndx = ak.index_us_stock_sina(symbol='.NDX')
ndx['date'] = pd.to_datetime(ndx['date']); ndx = ndx.set_index('date').sort_index()
ndx_close = ndx['close']
print(f'NDX: {len(ndx_close)}条 {ndx_close.index[0].date()}~{ndx_close.index[-1].date()}')

def check_ndx_panic(dt, ma=5):
    mask = ndx_close.index <= dt; hist = ndx_close.loc[mask]
    if len(hist) < ma: return False
    return hist.iloc[-1] < hist.iloc[-ma:].mean()

# ---- 回测 ----
class USPortfolio:
    def __init__(self, cash=10000):
        self.cash = cash; self.initial_cash = cash
        self.positions = {}; self.trade_log = []; self.daily_values = []
        self.comm = 0.005; self.slippage = 0.0005
    @property
    def total_value(self):
        return self.cash + sum(p['shares']*p.get('last_price',p['cost_price']) for p in self.positions.values())
    def update_prices(self, pdict):
        for c,p in pdict.items():
            if c in self.positions: self.positions[c]['last_price']=p
    def buy(self, code, shares, price, date, reason=''):
        price *= (1+self.slippage); tv = shares*price; comm = shares*self.comm
        if tv+comm > self.cash+0.01: return False
        self.cash -= tv+comm
        if code in self.positions:
            o=self.positions[code]; ts=o['shares']+shares
            self.positions[code]={'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*price)/ts,'last_price':price,'buy_date':o.get('buy_date',date)}
        else:
            self.positions[code]={'shares':shares,'cost_price':price,'last_price':price,'buy_date':date}
        self.trade_log.append({'date':str(date)[:10],'code':code,'action':'BUY','price':round(price,4),'shares':int(shares),'reason':reason})
        return True
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        price *= (1-self.slippage); pos=self.positions[code]; actual=min(shares,pos['shares'])
        if actual<=0: return False
        tv=actual*price; comm=actual*self.comm; self.cash+=tv-comm; pos['shares']-=actual
        if pos['shares']<=0: del self.positions[code]
        pnl=(price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        self.trade_log.append({'date':str(date)[:10],'code':code,'action':'SELL','price':round(price,4),'shares':int(actual),'pnl_pct':round(pnl,4),'reason':reason})
        return True
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions: return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)
    def record_daily_value(self, date):
        v=self.total_value
        self.daily_values.append({'date':str(date)[:10],'value':round(v,2)})
    def get_position_codes(self): return list(self.positions.keys())

def run(enable_panic, start, end):
    # 加载数据
    all_data={}
    for sym in POOL:
        fp=DATA_DIR/f'{sym}.csv'
        if not fp.exists(): continue
        df=pd.read_csv(fp)
        df.columns=[c.lower().strip() for c in df.columns]
        if 'last' in df.columns and 'close' in df.columns: df=df.drop(columns=['last'])
        elif 'last' in df.columns: df=df.rename(columns={'last':'close'})
        df['date']=pd.to_datetime(df['date']); df=df.set_index('date').sort_index()
        mask=(df.index>=start)&(df.index<=end)
        df=df[mask]
        if len(df)>=25: all_data[sym]=df
    
    td=sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
    td=[d for d in td if start<=d<=end]
    
    pf=USPortfolio(cash=10000); panic_days=0
    
    for i,td_str in enumerate(td):
        tds=pd.Timestamp(td_str)
        prices={}
        for code,df in all_data.items():
            m=df.index<=tds
            if m.any(): prices[code]=float(df.loc[m,'close'].iloc[-1])
        pf.update_prices(prices)
        
        # panic
        if enable_panic and check_ndx_panic(tds, 5):
            panic_days+=1
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code,prices[code],td_str,reason='NDX5_PANIC')
            pf.record_daily_value(td_str)
            continue
        
        # 排名 (us_live_report风格: index < date)
        ranked=[]
        for code,df in all_data.items():
            if code not in prices: continue
            mask=df.index<tds; hist=df[mask]
            if len(hist)<26: continue
            score=calc_score(hist['close'].values, 25)
            ranked.append({'code':code,'score':score,'price':prices[code]})
        ranked.sort(key=lambda x:x['score'],reverse=True)
        
        targets=[r['code'] for r in ranked if r['score']>=SCORE_THRESHOLD][:HN]
        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code,prices[code],td_str,reason='无目标')
            pf.record_daily_value(td_str); continue
        
        # 卖出
        target_set=set(targets)
        for code in list(pf.get_position_codes()):
            found=None
            for r in ranked:
                if r['code']==code: found=r; break
            if code not in target_set or (found and found['score']<SCORE_THRESHOLD):
                if code in prices: pf.sell_all(code,prices[code],td_str,reason='调出')
        
        # 买入（us_live_report风格: 已持有重新等权）
        tv=pf.total_value; each=tv/len(targets)
        for idx_c,code in enumerate(targets):
            if code not in prices: continue
            price=prices[code]; cv=0
            if code in pf.positions: cv=pf.positions[code]['shares']*pf.positions[code]['last_price']
            diff=each-cv
            if abs(diff)<each*0.05 and cv>0: continue
            if diff>0:
                sh=int(diff/price)
                if sh>0 and sh*price>=500: pf.buy(code,sh,price,td_str,reason=f'排名{idx_c+1}')
        
        pf.record_daily_value(td_str)
    
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
    return {'total_return':round(tr*100,1),'cagr':round(tr*252/len(td)*100,1),
            'max_dd':round(mdd*100,1),'sharpe':round(sh,2),'panic_days':panic_days,
            'final_value':round(fv,2),'trades':len(pf.trade_log),'days':len(td)}

print(f'\n{"="*70}')
print('us_live_report 引擎交叉验证: 关闭 vs 仅纳指5日')
print(f'{"="*70}')

for pname,start,end in [('3年','2023-06-25','2026-06-25'),('5年','2021-06-25','2026-06-25')]:
    r_off=run(False,start,end)
    r_on=run(True,start,end)
    print(f'\n[{pname}] {start}~{end} | 交易日:{r_off["days"]}')
    print(f'  关闭:     +{r_off["total_return"]}% 年化{r_off["cagr"]}% 回撤-{r_off["max_dd"]}% 夏普{r_off["sharpe"]} 终值${r_off["final_value"]}')
    print(f'  仅纳指5日: +{r_on["total_return"]}% 年化{r_on["cagr"]}% 回撤-{r_on["max_dd"]}% 夏普{r_on["sharpe"]} 终值${r_on["final_value"]} 恐慌{r_on["panic_days"]}天')
    ratio=r_on['total_return']/r_off['total_return'] if r_off['total_return']>0 else 0
    print(f'  收益比: {ratio:.2f}x | {"优于关闭" if r_off["total_return"]>0 and r_on["total_return"]>r_off["total_return"] and r_on["max_dd"]<r_off["max_dd"] else "未全面碾压"}')

print(f'\n{"="*70}')
print('对比 us_cross_validate.py (us100_backtest引擎) 结果')
print(f'{"="*70}')
print('[5年] us100引擎: 关闭+576%/回撤-48%  vs  仅纳指5日+765%/回撤-15% ★')
print('[3年] us100引擎: 关闭+526%/回撤-24%  vs  仅纳指5日+416%/回撤-12%')
