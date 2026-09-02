#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QMT池 vs 五福池 对比回测
====================
用相同的 QMT 引擎 + QMT 参数(单只持仓+盈利保护5%), 只替换ETF池,
对比池子本身对策略表现的影响。

用法: python backtest/pool_compare.py --start 2023-08-17 --end 2026-08-17 --cash 100000
"""
import sys, os, json, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

import pandas as pd
from pathlib import Path

from strategies.etf.seven_star_base import LocalDataSource
from strategies.etf.seven_star_172 import BacktestEngine172
import strategies.etf.seven_star_172 as p172
import strategies.etf.seven_star_base as base_mod
from reporting.generate_qmt_report import QMT_POOL
from backtest.qmt_backtest import QMT_PARAMS as _QMT_PARAMS

PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')


def extract_wufu_pool():
    src = Path(PROJECT_ROOT / 'strategies/etf/五福52V2.py').read_text(encoding='utf-8')
    codes = set()
    for line in src.split('\n'):
        code_part = line.split('#')[0]
        for m in re.finditer(r"'(\d{6})\.X(SHG|SHE)'", code_part):
            codes.add(f"{'sh' if m.group(2)=='SHG' else 'sz'}{m.group(1)}")
    index_codes = {'000001','000300','000510','399001','399006','399101'}
    return sorted(c for c in codes if c[2:] not in index_codes)


def run_pool(pool, label, start, end, cash):
    params = dict(_QMT_PARAMS)
    # 关闭五福不相关的东西, 保持纯QMT逻辑
    params['enable_hs300_state_machine'] = False
    params['enable_panic_regime'] = False

    ds = LocalDataSource(str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'))

    # monkey-patch 池
    orig_pool = p172.ETF_POOL
    orig_base = base_mod.ETF_POOL
    p172.ETF_POOL = pool
    base_mod.ETF_POOL = pool

    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = 0.0002
    results = engine.run(start, end, cash)

    p172.ETF_POOL = orig_pool
    base_mod.ETF_POOL = orig_base

    return results


def summarize(results, cash, label, pool_size):
    if results is None:
        print(f"\n{label}: 回测失败!")
        return
    n_days = results.get('trading_days', 0)
    final_val = results.get('final_value', cash)
    total_ret = final_val / cash
    cagr = total_ret ** (252.0 / n_days) - 1 if n_days > 0 else 0
    print(f"\n{'='*60}")
    print(f"  {label} ({pool_size}只)")
    print(f"  累计收益: {(total_ret-1)*100:+.2f}% | 年化CAGR: {cagr*100:+.2f}%")
    print(f"  最大回撤: {results.get('max_drawdown_pct',0):.2f}% | 夏普: {results.get('sharpe_ratio',0):.4f}")
    print(f"  交易: {results.get('total_trades',0)} | 胜率: {results.get('win_rate_pct',0):.1f}%")
    print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, default='2023-08-17')
    parser.add_argument('--end', type=str, default='2026-08-17')
    parser.add_argument('--cash', type=float, default=100000)
    args = parser.parse_args()

    wufu_pool = extract_wufu_pool()
    print(f"池子对比: QMT {len(QMT_POOL)}只 vs 五福 {len(wufu_pool)}只")
    print(f"区间: {args.start} ~ {args.end} | 初始资金 {args.cash:,.0f}")
    print(f"引擎: 纯QMT逻辑(单只持仓+盈利保护5%) 只换池子")

    # QMT池
    print(f"\n\n>>> 回测 QMT 池 ({len(QMT_POOL)}只)...")
    r_qmt = run_pool(QMT_POOL, 'QMT池', args.start, args.end, args.cash)
    summarize(r_qmt, args.cash, 'QMT池', len(QMT_POOL))

    # 五福池
    print(f"\n\n>>> 回测 五福池 ({len(wufu_pool)}只)...")
    r_wufu = run_pool(wufu_pool, '五福池', args.start, args.end, args.cash)
    summarize(r_wufu, args.cash, '五福池', len(wufu_pool))


if __name__ == '__main__':
    main()
