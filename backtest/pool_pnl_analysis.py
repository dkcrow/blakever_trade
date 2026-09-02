#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析两个池子5年回测的每只ETF累计盈亏 Top20"""
import sys, os, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

import pandas as pd
from pathlib import Path
from collections import defaultdict

from strategies.etf.seven_star_base import LocalDataSource
from strategies.etf.seven_star_172 import BacktestEngine172
import strategies.etf.seven_star_172 as p172
import strategies.etf.seven_star_base as base_mod
from reporting.generate_qmt_report import QMT_POOL
from backtest.qmt_backtest import QMT_PARAMS as _QMT_PARAMS

PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
START = '2021-08-17'
END = '2026-08-17'
CASH = 100000


def extract_wufu_pool():
    src = Path(PROJECT_ROOT / 'strategies/etf/五福52V2.py').read_text(encoding='utf-8')
    codes = set()
    for line in src.split('\n'):
        code_part = line.split('#')[0]
        for m in re.finditer(r"'(\d{6})\.X(SHG|SHE)'", code_part):
            codes.add(f"{'sh' if m.group(2)=='SHG' else 'sz'}{m.group(1)}")
    index_codes = {'000001','000300','000510','399001','399006','399101'}
    return sorted(c for c in codes if c[2:] not in index_codes)


def run_and_analyze(pool, label):
    params = dict(_QMT_PARAMS)
    params['enable_hs300_state_machine'] = False
    params['enable_panic_regime'] = False

    ds = LocalDataSource(str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'))
    orig_pool = p172.ETF_POOL
    orig_base = base_mod.ETF_POOL
    p172.ETF_POOL = pool
    base_mod.ETF_POOL = pool

    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = 0.0002
    results = engine.run(START, END, CASH)

    p172.ETF_POOL = orig_pool
    base_mod.ETF_POOL = orig_base

    if results is None:
        print(f"\n{label}: 回测失败")
        return

    trades = results.get('trade_log', [])

    # 正确算法: 追踪持仓成本, 计算每只ETF已实现盈亏 + 期末浮动盈亏
    pnl_by_code = defaultdict(float)
    trade_count = defaultdict(int)
    holdings = {}  # code -> (shares, total_cost)

    for t in trades:
        code = t['code']
        trade_count[code] += 1
        if t['action'] == 'BUY':
            sh = t['shares']
            amt = t['amount'] + t.get('commission', 0)
            s0, c0 = holdings.get(code, (0, 0))
            holdings[code] = (s0 + sh, c0 + amt)
        else:  # SELL
            sh = t['shares']
            amt = t['amount'] - t.get('commission', 0)
            s0, c0 = holdings.get(code, (0, 0))
            if s0 > 0:
                avg_cost = c0 / s0
                realized = amt - avg_cost * sh
                pnl_by_code[code] += realized
                s_remain = s0 - sh
                if s_remain > 0:
                    holdings[code] = (s_remain, c0 - avg_cost * sh)
                else:
                    holdings.pop(code, None)

    # 期末未平仓持仓浮动盈亏
    for code, (s, c) in holdings.items():
        last = engine.portfolio.positions.get(code, {}).get('last_price', 0)
        if last > 0:
            pnl_by_code[code] += (last * s - c)

    # 排序
    items = [(code, pnl, trade_count[code]) for code, pnl in pnl_by_code.items()]
    items.sort(key=lambda x: -x[1])

    name_map = {}
    for t in trades:
        name_map[t['code']] = t.get('name', t['code'])

    out = []
    out.append(f"\n{'='*70}")
    out.append(f"  {label} ({len(pool)}只) 5年回测 每只ETF累计盈亏")
    out.append(f"{'='*70}")
    out.append(f"\n  【收益前20】")
    for i, (code, pnl, cnt) in enumerate(items[:20]):
        out.append(f"  {i+1:2d}. {code} {name_map.get(code,''):14s} +{pnl:>10,.0f}元 ({cnt}笔)")
    out.append(f"\n  【亏损前20】")
    for i, (code, pnl, cnt) in enumerate(items[-20:]):
        out.append(f"  {i+1:2d}. {code} {name_map.get(code,''):14s} {pnl:>10,.0f}元 ({cnt}笔)")
    total_pnl = sum(p for _, p, _ in items)
    win = sum(1 for _, p, _ in items if p > 0)
    lose = sum(1 for _, p, _ in items if p <= 0)
    out.append(f"\n  汇总: {len(items)}只ETF参与交易, 盈利{win}只/亏损{lose}只, 累计盈亏 {total_pnl:+,.0f}元")
    return '\n'.join(out)


if __name__ == '__main__':
    wufu_pool = extract_wufu_pool()
    print(f"区间 {START} ~ {END} | 初始资金 {CASH:,}")

    all_out = []
    print(f"\n\n>>> QMT池 ({len(QMT_POOL)}只)...")
    all_out.append(run_and_analyze(QMT_POOL, 'QMT原生50精选池'))

    print(f"\n\n>>> 五福池 ({len(wufu_pool)}只)...")
    all_out.append(run_and_analyze(wufu_pool, '五福113只池'))

    # 写文件
    with open(PROJECT_ROOT / 'backtest' / 'pool_pnl_analysis_result.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_out))
    print('\n结果已保存到 backtest/pool_pnl_analysis_result.txt')
