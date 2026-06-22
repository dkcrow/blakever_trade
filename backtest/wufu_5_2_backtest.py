# -*- coding: utf-8 -*-
"""五福5.2原版 — 本地固定池简化复现回测
原策略为聚宽代码, 依赖全市场动态扫描+分钟数据, 无法本地直接运行。
本脚本复现其核心: 五福动量公式 + 大A走弱期择时 + 多层过滤 + 单持仓 + 日级止损 + 防御货基。
局限: 仅用固定池114只, 不含动态全市场扫描300只(会低估真实表现)。
"""
import numpy as np, math, pandas as pd, sys
from pathlib import Path

DATA = Path('data/storage/stock_data/etf')
START, END = '2023-06-18', '2026-06-22'
CASH = 1000000
COMM = 0.0001; SLIP = 0.0001  # 五福: 佣金万一+滑点万一
LOOKBACK = 25
MIN_SCORE, MAX_SCORE = 0, 5
R2_THR = 0.4; MA_LB = 10; MA_THR = 1.0
VOL_LB = 5; VOL_THR = 1.8
LOSS = 0.97
STOP = 0.95          # 分钟级止损→日级近似: 现价<成本×0.95卖出
DEFENSIVE = '511880'  # 货币ETF
WEAK_MA = 10; MAX_WEAK = 20
IDX = {'大盘':'510300','小盘':'510500','创业板':'159915','A500':'512050'}

GLOBAL_POOL = ['518880','501018','161226','159985','159980','513310','159518','159509','513100','513520','513500','159502','513400','513030','513290','520830','159529']
CHINA_POOL = ['513090','513120','513180','513330','513750','159892','513190','159605','513630','159323','510900','513920','513970','511380','512050','510500','159915','510300','512100','159949','588080','159967','588220','563300','510760','588200','515880','159981','512880','513350','159326','159516','159206','512480','159363','159870','512400','159755','588170','159992','159995','512890','515220','159566','159819','512800','512690','515050','562500','512170','517520','159869','512070','159611','562800','515120','512010','510880','515790','515980','512660','159928','512710','560860','515030','159766','159218','159852','516160','516150','159227','159583','588790','159865','512980','159851','561360','561980','562590','512200','159732','159667','516510','159840','159998','159825','512670','159883','515210','515400','159256','561330','515170','159638','516520','513360','516190']
FIXED_POOL = GLOBAL_POOL + CHINA_POOL


def load(code):
    fp = DATA / f'{code}.csv'
    if not fp.exists(): return None
    df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
    if 'date' not in df.columns or 'close' not in df.columns: return None
    df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
    df = df[~df.index.duplicated(keep='last')]; df = df[df['close'] > 0]
    return df if len(df) > 35 else None


def wufu_score(prices):
    """五福动量: 25日加权对数回归, W=linspace(1,2)^2, (exp(slope*250)-1)*R²"""
    if len(prices) < LOOKBACK + 1: return None, None
    p = prices[-(LOOKBACK+1):]
    y = np.log(p); x = np.arange(len(y))
    w = np.linspace(1, 2, len(y)); W = w**2; Ws = np.sum(W)
    xb = np.sum(W*x)/Ws; yb = np.sum(W*y)/Ws
    dx = x-xb; dy = y-yb
    vx = np.sum(W*dx**2)
    if vx == 0: return 0, 0
    slope = np.sum(W*dx*dy)/vx; intc = yb - slope*xb
    ann = math.exp(slope*250) - 1
    yp = slope*x + intc
    ssr = np.sum(w*(y-yp)**2); sst = np.sum(w*(y-np.mean(y))**2)
    r2 = 1 - ssr/sst if sst else 0
    return ann*r2, r2


print('加载数据...', end=' ', flush=True)
all_data = {}
for c in set(FIXED_POOL + [DEFENSIVE] + list(IDX.values())):
    d = load(c)
    if d is not None: all_data[c] = d
print(f'{len(all_data)}只')

# 交易日
tds = sorted(set().union(*[set(d.index) for d in all_data.values()]))
tds = [d for d in tds if START <= d.strftime('%Y-%m-%d') <= END]
print(f'交易日: {len(tds)}天 {tds[0].date()}~{tds[-1].date()}')


def idx_ma_state(date):
    """大A走弱期: 4指数代理收盘 vs MA10, >=3低于=走弱信号, >=3站上=退出信号"""
    below = above = 0
    for code in IDX.values():
        if code not in all_data: continue
        h = all_data[code][all_data[code].index <= date]
        if len(h) < WEAK_MA: continue
        cur = h['close'].iloc[-1]; ma = h['close'].iloc[-WEAK_MA:].mean()
        if cur < ma: below += 1
        elif cur > ma: above += 1
    return below, above


cash = CASH; pos = {}; daily = []; trades = []
is_weak = False; weak_days = 0
wins = sells = 0

for di, date in enumerate(tds):
    ds = date.strftime('%Y-%m-%d')
    prices = {}
    for c, d in all_data.items():
        if date in d.index:
            v = d.loc[date, 'close']
            if hasattr(v, 'iloc'): v = v.iloc[0]
            if float(v) > 0: prices[c] = float(v)
    for c in pos:
        if c in prices: pos[c]['lp'] = prices[c]

    # 大A走弱期判断
    below, above = idx_ma_state(date)
    if is_weak:
        weak_days += 1
        if weak_days >= MAX_WEAK or above >= 3: is_weak = False; weak_days = 0
    else:
        if below >= 3: is_weak = True; weak_days = 0
    active_pool = GLOBAL_POOL if is_weak else FIXED_POOL

    # 日级止损: 现价<成本×0.95 强制卖出
    for c in list(pos.keys()):
        if c in prices and prices[c] <= pos[c]['cp'] * STOP:
            p = prices[c]*(1-SLIP); tv = pos[c]['s']*p
            cash += tv - max(tv*COMM, 5)
            pnl = (p-pos[c]['cp'])/pos[c]['cp']; sells += 1; wins += 1 if pnl > 0 else 0
            del pos[c]

    # 动量评分+过滤
    ranked = []
    for c in active_pool:
        if c not in prices or c not in all_data: continue
        h = all_data[c][all_data[c].index < date]
        if len(h) < LOOKBACK: continue
        closes = np.append(h['close'].values, prices[c])
        sc, r2 = wufu_score(closes)
        if sc is None: continue
        # 过滤
        if not (MIN_SCORE <= sc <= MAX_SCORE): continue
        # 成交量(日级量比<1.8): 当日量/近VOL_LB日均量
        if 'volume' in h.columns and len(h) >= VOL_LB:
            vols = h['volume'].values[-VOL_LB:]
            if len(vols) and np.all(vols > 0):
                tv_now = all_data[c].loc[date, 'volume'] if date in all_data[c].index and 'volume' in all_data[c].columns else 0
                if hasattr(tv_now, 'iloc'): tv_now = tv_now.iloc[0]
                ratio = tv_now/np.mean(vols) if np.mean(vols) > 0 else 0
                if ratio >= VOL_THR: continue
        # 短期风控: 近3日单日跌幅<3%
        if len(closes) >= 4:
            if min(closes[-1]/closes[-2], closes[-2]/closes[-3], closes[-3]/closes[-4]) < LOSS: continue
        # R²(正常期) / MA(走弱期)
        if not is_weak:
            if r2 <= R2_THR: continue
        else:
            if len(closes) >= MA_LB:
                if prices[c] <= np.mean(closes[-MA_LB:]) * MA_THR: continue
            else: continue
        ranked.append({'c': c, 'sc': sc, 'p': prices[c]})
    ranked.sort(key=lambda x: x['sc'], reverse=True)

    # 单持仓目标
    target = ranked[0]['c'] if ranked else (DEFENSIVE if DEFENSIVE in prices else None)
    # 卖出非目标
    for c in list(pos.keys()):
        if c != target and c in prices:
            p = prices[c]*(1-SLIP); tv = pos[c]['s']*p
            cash += tv - max(tv*COMM, 5)
            pnl = (p-pos[c]['cp'])/pos[c]['cp']; sells += 1; wins += 1 if pnl > 0 else 0
            del pos[c]
    # 买入目标
    if target and target not in pos and target in prices:
        avail = cash * 0.98
        p = prices[target]*(1+SLIP)
        sh = int(avail/p/100)*100
        if sh >= 100:
            t = sh*p + max(sh*p*COMM, 5)
            if t <= cash: cash -= t; pos[target] = {'s': sh, 'cp': p, 'lp': p}

    tv_total = cash + sum(pp['s']*pp.get('lp', pp['cp']) for pp in pos.values())
    daily.append(tv_total)

dv = pd.Series(daily)
tr = (dv.iloc[-1]/CASH - 1)*100
dr = dv.pct_change().dropna()
cagr = ((dv.iloc[-1]/CASH)**(252.0/max(len(dr), 1)) - 1)*100
dd = (dv/dv.cummax()-1).min()*100
sharpe = dr.mean()/dr.std()*np.sqrt(252) if dr.std() > 0 else 0
wr = wins/sells*100 if sells else 0

print('\n' + '='*70)
print(f'  五福5.2原版 本地固定池简化复现 | {START}~{END}')
print(f'  固定池{len([c for c in FIXED_POOL if c in all_data])}只(无动态扩展) | 单持仓 | {CASH:,.0f}')
print('='*70)
print(f'  累计收益: {tr:+.1f}%   终值: ¥{dv.iloc[-1]:,.0f}')
print(f'  年化CAGR: {cagr:+.1f}%')
print(f'  最大回撤: {dd:.1f}%')
print(f'  夏普比率: {sharpe:.2f}')
print(f'  交易次数: {sells}卖 | 胜率: {wr:.1f}%')
print('='*70)
