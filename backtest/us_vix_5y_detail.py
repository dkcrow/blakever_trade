#!/usr/bin/env python3
"""
七星美股版 5年回测 + VIX防守切换详细分析
区间: 2021-06-07 ~ 2026-06-05
"""
import sys, os, math, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUTPUT_DIR = PROJECT_ROOT / 'backtest' / 'results_us100'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = '2021-06-07'
END_DATE = '2026-06-05'

AGGRESSIVE_POOL = [
    'NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','AAPL','TSM','LITE',
    'META','AMZN','NFLX','GOOGL','MSFT','CRM','NOW','CRWD','ORCL',
    'PLTR','DDOG','SNPS','XOM','CVX','COP','EOG','OKE',
    'NEM','FCX','LIN','CAT','GE','RTX','PLD','AMT',
]

DEFENSIVE_POOL = ['GLD','IAU','TLT','IEF','SHY','AGG','XLU','XLP','XLV','USMV']

HN = 7
SLIPPAGE = 0.0005; COMM = 0.005; CASH = 10000

# ============================================================
# Load
# ============================================================
print("=" * 60)
print(f"  七星美股版 5年回测 + VIX>30防守切换分析")
print(f"  区间: {START_DATE} ~ {END_DATE}")
print("=" * 60)

all_data = {}
for sym in set(AGGRESSIVE_POOL + DEFENSIVE_POOL + ['VIX']):
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        mask = (df.index >= START_DATE) & (df.index <= END_DATE)
        df = df[mask]
        if len(df) >= 25: all_data[sym] = df
    except: pass

print(f"  进攻池: {sum(1 for s in AGGRESSIVE_POOL if s in all_data)}/{len(AGGRESSIVE_POOL)}")
print(f"  防守池: {sum(1 for s in DEFENSIVE_POOL if s in all_data)}/{len(DEFENSIVE_POOL)}")
print(f"  VIX: {'✅' if 'VIX' in all_data else '❌'}")

trade_dates = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]
print(f"  交易日: {len(trade_dates)} 天")

# ============================================================
# Engine
# ============================================================
class PF:
    def __init__(self):
        self.cash = CASH; self.ic = CASH
        self.pos = {}; self.log = []; self.dv = []
    @property
    def tv(self):
        return self.cash + sum(p['sh']*p.get('lp',p['cp']) for p in self.pos.values())
    def up(self, pdict):
        for c,p in pdict.items():
            if c in self.pos: self.pos[c]['lp'] = p
    def buy(self, code, sh, price, date, reason=''):
        price *= (1+SLIPPAGE); tv = sh*price; co = sh*COMM
        if tv+co > self.cash+0.01: return False
        self.cash -= tv+co
        if code in self.pos:
            o=self.pos[code]; ns=o['sh']+sh
            self.pos[code]={'sh':ns,'cp':(o['sh']*o['cp']+sh*price)/ns,'lp':price,'bd':o.get('bd',date)}
        else:
            self.pos[code]={'sh':sh,'cp':price,'lp':price,'bd':date}
        self.log.append({'date':str(date)[:10],'code':code,'action':'BUY','price':round(price,4),'shares':int(sh),'amount':round(tv,2),'commission':round(co,2),'reason':reason})
        return True
    def sell(self, code, sh, price, date, reason=''):
        if code not in self.pos: return False
        price *= (1-SLIPPAGE); pos=self.pos[code]; a=min(sh,pos['sh'])
        if a<=0: return False
        tv=a*price; co=a*COMM; self.cash+=tv-co; pos['sh']-=a
        pnl=(price-pos['cp'])/pos['cp'] if pos['cp']>0 else 0
        if pos['sh']<=0: del self.pos[code]
        self.log.append({'date':str(date)[:10],'code':code,'action':'SELL','price':round(price,4),'shares':int(a),'amount':round(tv,2),'commission':round(co,2),'pnl_pct':round(pnl,4),'reason':reason})
        return True
    def sa(self, code, price, date, reason=''):
        if code not in self.pos: return False
        return self.sell(code, self.pos[code]['sh'], price, date, reason)
    def rec(self, date):
        self.dv.append({'date':str(date)[:10],'value':round(self.tv,2)})
    def codes(self): return list(self.pos.keys())

def calc_score(close_full, lb=25):
    recent = close_full[-(lb+1):]
    y=np.log(np.maximum(recent,1e-10)); x=np.arange(len(y)); w=np.linspace(1,2,len(y))
    slope,intercept=np.polyfit(x,y,1,w=w); ann=math.exp(slope*250)-1
    ssr=np.sum(w*(y-(slope*x+intercept))**2); sst=np.sum(w*(y-np.mean(y))**2)
    return ann*(1-ssr/sst) if sst>0 else 0

def get_ranked(data, prices, date, pool):
    ranked=[]
    for code in pool:
        if code not in data or code not in prices: continue
        df=data[code]; mask=df.index<pd.Timestamp(date); hist=df[mask]
        if len(hist)<35: continue
        cp=prices[code]
        if cp<=0: continue
        ranked.append({'code':code,'score':calc_score(hist['close'].values),'price':cp})
    ranked.sort(key=lambda x:x['score'],reverse=True)
    return ranked

# ============================================================
# Run both
# ============================================================
def run(vix_threshold=None):
    """vix_threshold=None 表示纯基线; 数值表示VIX超过时切防守"""
    pf=PF(); regime='aggressive'; switches=[]; defense_days=0
    for td in trade_dates:
        tds=pd.Timestamp(td)
        prices={}
        for code,df in all_data.items():
            m=df.index<=tds
            if m.any(): prices[code]=float(df.loc[m,'close'].iloc[-1])
        pf.up(prices)

        # VIX check
        if vix_threshold is not None:
            vix_df=all_data['VIX']; vm=vix_df.index<tds
            if vm.any():
                pv=float(vix_df.loc[vm,'close'].iloc[-1])
                nr='defensive' if pv>vix_threshold else 'aggressive'
                if nr!=regime:
                    switches.append({'date':td,'from':regime,'to':nr,'vix':round(pv,2)})
                    regime=nr
            if regime=='defensive': defense_days+=1
            pool=DEFENSIVE_POOL if regime=='defensive' else AGGRESSIVE_POOL
        else:
            pool=AGGRESSIVE_POOL

        ranked=get_ranked(all_data,prices,td,pool)
        if not ranked: pf.rec(td); continue
        targets=[r['code'] for r in ranked[:HN]]

        for code in list(pf.codes()):
            if code not in targets and code in prices:
                pf.sa(code,prices[code],td,reason='调出目标')

        tv=pf.tv; each=tv/len(targets)
        for idx,code in enumerate(targets):
            if code not in prices: continue
            price=prices[code]; cv=0
            if code in pf.pos: cv=pf.pos[code]['sh']*pf.pos[code]['lp']
            diff=each-cv
            if abs(diff)<each*0.05 and cv>0: continue
            if diff>0:
                sh=int(diff/price)
                if sh>0 and sh*price>=500: pf.buy(code,sh,price,td,reason=f'排名{idx+1}')
        pf.rec(td)
    return pf, switches, defense_days

def metrics(pf):
    vals=[d['value'] for d in pf.dv]; fv=vals[-1]
    tr=(fv-CASH)/CASH; peak=mdd=vals[0]
    for v in vals:
        if v>peak: peak=v
        dd=(peak-v)/peak if peak>0 else 0
        if dd>mdd: mdd=dd
    sh=0
    if len(vals)>1:
        dr=np.diff(vals)/vals[:-1]
        sh=(np.mean(dr)/np.std(dr)*np.sqrt(252)) if np.std(dr)>0 else 0
    trades=pf.log; buys=sum(1 for t in trades if t['action']=='BUY')
    st=[t for t in trades if t['action']=='SELL' and 'pnl_pct' in t]
    wins=[t for t in st if t['pnl_pct']>0]
    wr=len(wins)/len(st)*100 if st else 0
    return {'fv':fv,'tr':tr*100,'ann':tr*252/len(trade_dates)*100,'mdd':mdd*100,'sh':sh,'trades':len(trades),'buys':buys,'sells':len(st),'wr':wr}

# Run
print(f"\n[1/2] 基线回测...")
pf_baseline,_,_ = run(vix_threshold=None)
m_bl = metrics(pf_baseline)

print(f"[2/2] VIX>30 防守回测...")
pf_vix,switches,def_days = run(vix_threshold=30)
m_vx = metrics(pf_vix)

# ============================================================
# Output
# ============================================================
print(f"\n{'='*70}")
print(f"  5年回测对比 ({START_DATE} ~ {END_DATE}, {len(trade_dates)}天)")
print(f"{'='*70}")
print(f"{'指标':<16} {'基线(无VIX)':>14} {'VIX>30防守':>14}")
print(f"{'-'*46}")
for label, key in [('累计收益','tr'),('年化','ann'),('最大回撤','mdd'),('夏普','sh'),('交易次数','trades'),('胜率','wr')]:
    print(f"{label:<16} {m_bl[key]:+13.2f}% {' ' if key in ['sh','trades','wr'] else ''}{m_vx[key]:+13.2f}% {' ' if key in ['sh','trades','wr'] else ''}"[:70])

print(f"\n{'='*70}")
print(f"  VIX>30 防守切换记录 ({len(switches)}次切换, 防守{def_days}天/{len(trade_dates)}天 = {def_days/len(trade_dates)*100:.1f}%)")
print(f"{'='*70}")
print(f"{'日期':<12} {'方向':>12} {'VIX':>8} {'前后交易日'}")
print(f"{'-'*70}")

for sw in switches:
    d = sw['date']
    direction = f"进攻→防守 🔴" if sw['to']=='defensive' else f"防守→进攻 🟢"
    # 前后交易日
    idx = trade_dates.index(d)
    prev_d = trade_dates[idx-1] if idx>0 else '?'
    next_d = trade_dates[idx+1] if idx+1<len(trade_dates) else '?'
    print(f"{d:<12} {direction:<12} {sw['vix']:>8.2f}  {prev_d} → {next_d}")

# 每次切换时持仓和买入的防守标的
print(f"\n{'='*70}")
print(f"  切换时刻持仓详情")
print(f"{'='*70}")

# 重新运行一次带详细日志
pf_detailed, sw_detailed, _ = run(vix_threshold=30)

# 从交易日志中找到切换日附近的交易
switch_dates = set(s['date'] for s in sw_detailed)
switch_trades = [t for t in pf_detailed.log if t['date'] in switch_dates or 
    any(abs((pd.Timestamp(t['date'])-pd.Timestamp(s['date'])).days)<=2 for s in sw_detailed)]

for sw in sw_detailed:
    d = sw['date']
    print(f"\n  【{d}】VIX={sw['vix']}  {sw['from']} → {sw['to']}")
    # 找到前后3天的交易
    nearby = [t for t in pf_detailed.log if abs((pd.Timestamp(t['date'])-pd.Timestamp(d)).days)<=3]
    # 按日期分组
    by_date = {}
    for t in nearby:
        dd = t['date']
        if dd not in by_date: by_date[dd] = []
        by_date[dd].append(t)
    for dd in sorted(by_date.keys()):
        for t in by_date[dd]:
            act = '买' if t['action']=='BUY' else '卖'
            pnl = f" 盈亏{t['pnl_pct']*100:+.2f}%" if 'pnl_pct' in t else ''
            print(f"    {dd} {act} {t['code']:6s} ${t['price']:.2f} x{t['shares']} [{t['reason']}]{pnl}")

# VIX期间统计
print(f"\n{'='*70}")
print(f"  VIX>30期间防守池动量排名Top3")
print(f"{'='*70}")
vix_df = all_data['VIX']
for sw in sw_detailed:
    d = sw['date']
    if sw['to'] != 'defensive': continue
    tds = pd.Timestamp(d)
    prices_d = {}
    for code,df in all_data.items():
        m=df.index==tds
        if m.any(): prices_d[code]=float(df.loc[m,'close'].iloc[0])
    if not prices_d: continue
    ranked = get_ranked(all_data, prices_d, d, DEFENSIVE_POOL)
    top3 = ", ".join([f"{r['code']}({r['score']:.4f})" for r in ranked[:3]])
    print(f"  {d}: {top3}")

print(f"\n{'='*70}")
print(f"  VIX>30 防守日收益分析")
print(f"{'='*70}")
# 计算防守期间的表现
defense_dates = {}
for sw in sw_detailed:
    if sw['to'] == 'defensive':
        start_idx = trade_dates.index(sw['date'])
        # 找下一次切换回进攻的日期
        end_idx = len(trade_dates)
        for sw2 in sw_detailed:
            if sw2['date'] > sw['date'] and sw2['to'] == 'aggressive':
                end_idx = trade_dates.index(sw2['date'])
                break
        defense_dates[sw['date']] = (start_idx, end_idx, sw['vix'])

for start_d, (si, ei, vix_val) in defense_dates.items():
    seg_vals = [pf_vix.dv[i]['value'] for i in range(si, min(ei, len(pf_vix.dv)))]
    seg_ret = (seg_vals[-1]/seg_vals[0]-1)*100 if seg_vals else 0
    seg_days = min(ei, len(pf_vix.dv)) - si
    print(f"  {start_d} → {trade_dates[min(ei-1, len(trade_dates)-1)]} ({seg_days}天): {seg_ret:+.2f}%  (VIX峰值={vix_val})")

print(f"\n{'='*70}")
print(f"  完成!")
print(f"{'='*70}")
