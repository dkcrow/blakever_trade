#!/usr/bin/env python3
"""
七星QMT ETF贡献度分析 (基于修复后的引擎评分公式)
扫描本地所有ETF, 3年回测, 分析每只ETF的收益贡献
使用与172引擎完全一致的加权回归评分公式
"""
import numpy as np
import pandas as pd
import math
import json
import sys
import time
from pathlib import Path
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'
NAV_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf_nav'

START_DATE = '2023-06-20'
END_DATE = '2026-06-20'
LOOKBACK = 25
CASH = 1000000
COMM_RATE = 0.0002
SLIPPAGE = 0.001

# 当前40只池
CURRENT_POOL_RAW = [
    'sh518880','sz159980','sz159985','sh501018','sz161226','sz159981',
    'sh513100','sz159509','sh513290','sh513500','sz159529',
    'sh513400','sh513520','sh513030','sh513080','sh513310','sh513730',
    'sz159792','sh513130','sh513050','sz159920','sh513690',
    'sh510300','sh510500','sh510050','sh510210','sz159915',
    'sh588080','sh512100','sh563360','sh563300',
    'sh512890','sz159967','sh512040','sz159201','sh562500','sh560090',
    'sh511380','sh511010','sz511220',
]
CURRENT_POOL = set(c[2:] for c in CURRENT_POOL_RAW)

# ============ 172引擎完全一致的评分公式 ============
def calc_engine_score(close_series, lookback=25):
    """与172引擎get_ranked_etfs()完全一致的加权回归评分"""
    if len(close_series) < lookback + 1:
        return -999
    recent = close_series[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    try:
        slope, intercept = np.polyfit(x, y, 1, w=weights)
    except:
        return -999
    annualized_ret = math.exp(slope * 250) - 1
    ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return annualized_ret * r_squared

# ============ 加载数据 ============
print('加载ETF数据...', flush=True)
t0 = time.time()
all_data = {}
etf_names = {}

for fp in sorted(DATA_DIR.glob('*.csv')):
    code = fp.stem
    if len(code) > 6 or code.startswith('^') or code.startswith('.'):
        continue
    try:
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        if 'date' not in df.columns or 'close' not in df.columns:
            continue
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        df = df[df['close'] > 0]
        # 需要回测区间内有足够数据
        bt = df[(df.index >= START_DATE) & (df.index <= END_DATE)]
        if len(bt) > 100:
            all_data[code] = df
    except:
        pass

# 加载NAV数据(用于溢价率过滤)
nav_data = {}
if NAV_DIR.exists():
    for fp in NAV_DIR.glob('*_nav.csv'):
        code = fp.stem.replace('_nav', '')
        # 去掉sh/sz前缀
        if code.startswith('sh') or code.startswith('sz'):
            code = code[2:]
        try:
            ndf = pd.read_csv(fp)
            if 'date' in ndf.columns and 'unit_nav' in ndf.columns:
                ndf['date'] = pd.to_datetime(ndf['date'])
                ndf = ndf.set_index('date').sort_index()
                nav_data[code] = ndf['unit_nav']
        except:
            pass

print(f'{len(all_data)}只ETF | {len(nav_data)}只有NAV | {time.time()-t0:.1f}s', flush=True)

# ============ 交易日 ============
trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]
print(f'交易日: {len(trade_dates)}天 ({trade_dates[0].strftime("%Y-%m-%d")} ~ {trade_dates[-1].strftime("%Y-%m-%d")})', flush=True)

# ============ 回测模拟 ============
print(f'\n开始回测...', flush=True)

# 统计
stats = defaultdict(lambda: {'buys': 0, 'pnl_total': 0.0, 'wins': 0, 'losses': 0,
                               'first_date': '', 'last_date': '', 'hold_days': 0})
prev_held = None
prev_price = 0
prev_date = None
cash = CASH
total_trades = 0

for i, date in enumerate(trade_dates):
    d_str = date.strftime('%Y-%m-%d')

    # 获取当天所有ETF价格
    prices = {}
    for code, df in all_data.items():
        if date in df.index:
            v = df.loc[date, 'close']
            if hasattr(v, 'iloc'): v = v.iloc[0]
            if float(v) > 0:
                prices[code] = float(v)

    if len(prices) < 5:
        continue

    # 计算所有ETF得分 (使用修复后的日期过滤逻辑)
    scored = []
    for code in prices:
        if code not in all_data:
            continue
        df = all_data[code]
        # 关键: 仅使用当天之前的数据 (与修复后的引擎一致)
        hist = df[df.index <= date]
        if len(hist) < LOOKBACK + 1:
            continue

        # 溢价率过滤 (>20%排除)
        if code in nav_data:
            ns = nav_data[code]
            prev_nav_mask = ns.index < date
            if prev_nav_mask.any():
                nav_val = ns[prev_nav_mask].iloc[-1]
                if nav_val > 0:
                    premium = (prices[code] - nav_val) / nav_val
                    if premium > 0.20:
                        continue

        score = calc_engine_score(hist['close'].values, LOOKBACK)
        if score > 0:  # 仅保留正分
            scored.append((code, score, prices[code]))

    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        # 无目标, 平仓(如有)
        if prev_held and prev_held in prices:
            sell_price = prices[prev_held] * (1 - SLIPPAGE)
            pnl = (sell_price - prev_price) / prev_price * 100
            s = stats[prev_held]
            s['pnl_total'] += pnl
            if pnl > 0: s['wins'] += 1
            else: s['losses'] += 1
            s['last_date'] = d_str
            hold = (date - pd.Timestamp(prev_date)).days if prev_date else 0
            s['hold_days'] += hold
            total_trades += 1
        prev_held = None
        prev_price = 0
        prev_date = None
        continue

    top_code, top_score, top_price = scored[0]

    # 轮换检查
    if top_code == prev_held:
        continue  # 持仓不变

    # 卖出旧持仓
    if prev_held and prev_held in prices:
        sell_price = prices[prev_held] * (1 - SLIPPAGE)
        pnl = (sell_price - prev_price) / prev_price * 100
        s = stats[prev_held]
        s['pnl_total'] += pnl
        if pnl > 0: s['wins'] += 1
        else: s['losses'] += 1
        s['last_date'] = d_str
        hold = (date - pd.Timestamp(prev_date)).days if prev_date else 0
        s['hold_days'] += hold
        total_trades += 1

    # 买入新持仓
    buy_price = top_price * (1 + SLIPPAGE)
    stats[top_code]['buys'] += 1
    if not stats[top_code]['first_date']:
        stats[top_code]['first_date'] = d_str

    prev_held = top_code
    prev_price = buy_price
    prev_date = d_str
    total_trades += 1

    if (i + 1) % 100 == 0:
        print(f'  进度: {i+1}/{len(trade_dates)} ({d_str})', flush=True)

# 最后平仓
if prev_held and prev_held in prices:
    sell_price = prices[prev_held] * (1 - SLIPPAGE)
    pnl = (sell_price - prev_price) / prev_price * 100
    s = stats[prev_held]
    s['pnl_total'] += pnl
    if pnl > 0: s['wins'] += 1
    else: s['losses'] += 1
    s['last_date'] = trade_dates[-1].strftime('%Y-%m-%d')

# ============ 输出结果 ============
ranked = sorted(stats.items(), key=lambda x: x[1]['pnl_total'], reverse=True)

print(f'\n{"="*95}')
print(f'{"七星QMT ETF贡献度分析 (修复后引擎, 3年回测)":^85}')
print(f'{START_DATE} ~ {END_DATE} | {len(all_data)}只ETF | N=1 | 加权回归评分')
print(f'{"="*95}')
print(f'{"排名":>4} | {"代码":>6} | {"池内":>4} | {"入选":>4} | {"胜/负":>7} | {"累计盈亏%":>10} | {"均盈亏%":>8} | {"首次":>10} | {"末次":>10}')
print(f'{"-"*95}')

pos_in_pool = 0; neg_in_pool = 0
pos_out_pool = 0; neg_out_pool = 0
pos_candidates = []
neg_in_list = []

for i, (code, s) in enumerate(ranked):
    in_pool = '✅' if code in CURRENT_POOL else ''
    total = s['wins'] + s['losses']
    avg = s['pnl_total'] / total if total > 0 else 0
    print(f'{i+1:>4} | {code:>6} | {in_pool:>4} | {s["buys"]:>4} | {s["wins"]:>3}/{s["losses"]:>3} | {s["pnl_total"]:>+10.1f} | {avg:>+7.1f} | {s["first_date"]:>10} | {s["last_date"]:>10}')

    if s['pnl_total'] > 0:
        if code in CURRENT_POOL:
            pos_in_pool += 1
        else:
            pos_out_pool += 1
            pos_candidates.append((code, s))
    else:
        if code in CURRENT_POOL:
            neg_in_pool += 1
            neg_in_list.append((code, s))
        else:
            neg_out_pool += 1

never = [c for c in CURRENT_POOL if c not in stats]

print(f'\n{"="*95}')
print(f'被选中ETF: {len(stats)}只 | 正贡献: {pos_in_pool + pos_out_pool} | 负贡献: {neg_in_pool + neg_out_pool}')
print(f'池内: 正{pos_in_pool} 负{neg_in_pool} 未选{len(never)} | 池外正贡献: {pos_out_pool}只')
print(f'总交易: {total_trades}笔')

if pos_candidates:
    print(f'\n🟢 池外正贡献 Top10 (建议加入):')
    for code, s in sorted(pos_candidates, key=lambda x: x[1]['pnl_total'], reverse=True)[:10]:
        total = s['wins'] + s['losses']
        print(f'  {code}: {s["pnl_total"]:+.1f}% | {s["buys"]}次入选 | 胜{s["wins"]}/负{s["losses"]} | {s["first_date"]}~{s["last_date"]}')

if neg_in_list:
    print(f'\n🔴 池内负贡献 (建议移除):')
    for code, s in sorted(neg_in_list, key=lambda x: x[1]['pnl_total']):
        total = s['wins'] + s['losses']
        print(f'  {code}: {s["pnl_total"]:+.1f}% | {s["buys"]}次入选 | 胜{s["wins"]}/负{s["losses"]}')

if never:
    print(f'\n⚪ 池内从未入选 ({len(never)}只):')
    print(f'  {", ".join(sorted(never))}')

# 保存结果
result = {
    'period': f'{START_DATE} ~ {END_DATE}',
    'total_etfs': len(all_data),
    'selected_etfs': len(stats),
    'total_trades': total_trades,
    'pool_positive': pos_in_pool,
    'pool_negative': neg_in_pool,
    'pool_never': len(never),
    'outside_positive': pos_out_pool,
    'rankings': [{'code': code, **s} for code, s in ranked],
    'candidates': [{'code': code, 'pnl': s['pnl_total'], 'buys': s['buys']}
                   for code, s in sorted(pos_candidates, key=lambda x: x[1]['pnl_total'], reverse=True)[:20]],
}
out_path = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf_qmt_contribution.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2, default=str)
print(f'\n结果已保存: {out_path}')
