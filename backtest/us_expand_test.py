"""测试扩池: 22只base + 候选 → 回测对比"""
import numpy as np, pandas as pd
from pathlib import Path

DATA_DIR = Path('data/storage/stock_data/us')
BASE_POOL = ['NVDA','AVGO','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS','EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB','SPCX']

# Candidates from scan with score>=2 + diverse sectors
CANDIDATES = {
    'SMCI': '超微电脑',
    'COHR': 'Coherent光学',
    'CSCO': '思科',
    'MDB': 'MongoDB',
    'NTAP': 'NetApp',
    'QBTS': 'D-Wave量子',
    'AAPL': '苹果',
    'MSFT': '微软',
    'SNOW': 'Snowflake',
    'HOOD': 'Robinhood',
}

COMM=0.005; SLIP=0.0005; CASH=1000000; HN=7; TH=0.5

all_data = {}
for sym in set(BASE_POOL + list(CANDIDATES.keys())):
    fp = DATA_DIR / f'{sym}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 35: all_data[sym] = df

trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if '2025-01-01' <= d.strftime('%Y-%m-%d') <= '2026-06-18']

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_res = np.sum(res**2); ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return ann * r2

class PF:
    def __init__(s): s.cash=CASH; s.pos={}
    @property
    def tv(s): return s.cash+sum(p['shares']*p.get('lp',p['cp']) for p in s.pos.values())
    def up(s,pd):
        for c,p in pd.items():
            if c in s.pos: s.pos[c]['lp']=p
    def buy(s,sym,sh,price):
        p=price*(1+SLIP); tv=sh*p; c=sh*COMM
        if tv+c>s.cash+0.01: return False
        s.cash-=tv+c
        if sym in s.pos: o=s.pos[sym]; ts=o['shares']+sh; s.pos[sym]={'shares':ts,'cp':(o['shares']*o['cp']+sh*p)/ts,'lp':p}
        else: s.pos[sym]={'shares':sh,'cp':p,'lp':p}
        return True
    def sell(s,sym,sh,price):
        if sym not in s.pos: return False
        p=price*(1-SLIP); pos=s.pos[sym]; a=min(sh,pos['shares'])
        s.cash+=a*p-a*COMM
        if a>=pos['shares']: del s.pos[sym]
        else: s.pos[sym]['shares']-=a
        return True
    def codes(s): return list(s.pos.keys())

def run(pool):
    pf=PF(); daily=[]
    for date in trade_dates:
        prices={}
        for sym in pool:
            if sym in all_data:
                m=all_data[sym].index==date
                if m.any(): prices[sym]=float(all_data[sym].loc[date,'close'])
        if len(prices)<HN: continue
        ranked=[]
        for sym in pool:
            if sym not in prices: continue
            df=all_data[sym]; mask=df.index<date; hist=df[mask]
            if len(hist)<25: continue
            cp=prices[sym]; 
            if cp<=0: continue
            score=calc_score(hist['close'].values[-25:])
            ranked.append({'code':sym,'score':score,'price':cp})
        ranked.sort(key=lambda x:x['score'],reverse=True)
        targets=[r for r in ranked if r['score']>=TH][:HN]
        tc=set(r['code'] for r in targets)
        cc=set(pf.codes())
        ts=cc-tc
        for code in list(cc):
            f=next((r for r in ranked if r['code']==code),None)
            if f and f['score']<TH: ts.add(code)
        for code in ts:
            if code in prices: pf.sell(code,pf.pos[code]['shares'],prices[code])
        tv=pf.tv; pf.up(prices)
        nq=max(len(targets),1)
        for r in targets:
            if r['code'] in pf.pos: continue
            if r['code'] not in prices: continue
            ps=tv*0.95/nq; sh=int(ps/r['price'])
            if sh>=1: pf.buy(r['code'],sh,r['price'])
        daily.append({'date':date.strftime('%Y-%m-%d'),'value':pf.tv})
    dv=pd.DataFrame(daily)
    tr=(dv['value'].iloc[-1]/CASH-1)*100
    dr=dv['value'].pct_change().dropna()
    ann=(dv['value'].iloc[-1]/CASH)**(252/max(len(dr),1))-1
    dd=(dv['value']/dv['value'].cummax()-1).min()*100
    sp=dr.mean()/dr.std()*np.sqrt(252) if dr.std()>0 else 0
    return {'total':round(tr,1),'annual':round(ann*100,1),'dd':round(dd,1),'sharpe':round(sp,2),'final':pf.tv,'n':len(pool)}

# Test progressive additions
print('增量扩池测试 (逐步加入候选):')
print('-'*85)
base = run(BASE_POOL)
print('基准22只: 年化' + f'{base["annual"]:+.1f}% | 回撤{base["dd"]:.1f}% | 夏普{base["sharpe"]:.2f} | ${base["final"]:,.0f}')

# Try adding candidates one by one in order of score
add_order = ['SMCI','COHR','CSCO','MDB','AAPL','MSFT','NTAP','QBTS','SNOW','HOOD']
best_pool = list(BASE_POOL)
best_result = base
for cand in add_order:
    test_pool = best_pool + [cand]
    r = run(test_pool)
    diff = r['annual'] - best_result['annual']
    mark = 'YES' if diff > 0 else 'NO '
    print('  +' + cand + f': 年化{r["annual"]:+.1f}% | 回撤{r["dd"]:.1f}% | 夏普{r["sharpe"]:.2f} | 差{diff:+.1f}% {mark}')
    if diff > 0:
        best_pool.append(cand)
        best_result = r

print('')
print('最终推荐池(' + str(len(best_pool)) + '只):')
print(','.join(best_pool))
r = run(best_pool)
print('年化' + f'{r["annual"]:+.1f}% | 回撤{r["dd"]:.1f}% | 夏普{r["sharpe"]:.2f} | 终值${r["final"]:,.0f}')
print('vs基准: +' + f'{(r["annual"]-base["annual"]):.1f}%年化增量')
