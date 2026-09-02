#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低波动ETF轮动 策略回测 (日线近似)
================================
基于聚宽"低波etf.py"(低波动ETF策略)。

核心逻辑:
- 14只ETF池
- 每周一调仓
- 选过去60日年化波动率最低的1只ETF (g.num=1)
- 全仓持有该ETF
- 5%容差避免频繁微调

用法: python backtest/lowvol_backtest.py --start 2021-08-17 --end 2026-08-17
"""
import sys, os, io, math, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'

ALL_ETFS = {
    'sz159915': '创业板ETF',
    'sh510880': '红利ETF',
    'sh518880': '黄金ETF',
    'sh513100': '纳指ETF',
    'sz159985': '豆粕ETF',
    'sh510050': '50ETF',
    'sh512100': '1000ETF',
    'sz159768': '房地产ETF银华',
    'sh515220': '煤炭ETF',
    'sz159928': '消费ETF',
    'sh512800': '银行ETF',
    'sz159995': '芯片ETF',
    'sz159870': '化工ETF',
    'sh513090': '香港证券ETF',
}
NUM = 1
LOOKBACK = 60
COMMISSION = 0.0002
MIN_COMM = 5


def load(code):
    fp = DATA_DIR / f'{code[2:]}.csv'
    if not fp.exists():
        return None
    df = pd.read_csv(fp)
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()


class Portfolio:
    def __init__(self, cash):
        self.cash = cash
        self.pos = {}
        self.daily = []

    def value(self, prices):
        v = self.cash
        for code, sh in self.pos.items():
            if code in prices:
                v += sh * prices[code]
        return v

    def trade_to_target(self, code, target_value, price):
        if price <= 0:
            return
        cur_sh = self.pos.get(code, 0)
        target_sh = int(target_value / price // 100) * 100
        diff = target_sh - cur_sh
        if abs(diff) < 100:
            return
        if diff > 0:
            cost = diff * price
            comm = max(cost * COMMISSION, MIN_COMM)
            if cost + comm > self.cash:
                return
            self.cash -= cost + comm
            self.pos[code] = cur_sh + diff
        else:
            sell_sh = min(-diff, cur_sh)
            cost = sell_sh * price
            comm = max(cost * COMMISSION, MIN_COMM)
            self.cash += cost - comm
            self.pos[code] = cur_sh - sell_sh
            if self.pos[code] <= 0:
                self.pos.pop(code, None)

    def sell_all(self, code, price):
        if code not in self.pos:
            return
        sh = self.pos[code]
        cost = sh * price
        comm = max(cost * COMMISSION, MIN_COMM)
        self.cash += cost - comm
        self.pos.pop(code, None)


def run(start, end, cash=100000):
    data = {}
    for code in ALL_ETFS:
        data[code] = load(code)

    # 交易日
    dates = set()
    for df in data.values():
        if df is not None:
            dates.update(df.index)
    dates = sorted(d for d in dates if pd.Timestamp(start) <= d <= pd.Timestamp(end))

    pf = Portfolio(cash)
    last_rebalance_week = None

    for td in dates:
        prices = {}
        for code, df in data.items():
            if df is None:
                continue
            m = df.index <= td
            if m.any():
                prices[code] = float(df.loc[m, 'close'].iloc[-1])

        # 周一调仓 (用周一近似 run_weekly)
        is_monday = td.weekday() == 0
        week_key = td.strftime('%Y-%W')
        if is_monday and week_key != last_rebalance_week:
            last_rebalance_week = week_key
            # 计算每只ETF的60日年化波动率
            vols = {}
            for code in ALL_ETFS:
                df = data[code]
                if df is None:
                    continue
                m = df.index < td  # 用td之前的数据, 防未来函数
                hist = df.loc[m, 'close']
                if len(hist) < LOOKBACK + 1:
                    continue
                log_ret = np.log(hist / hist.shift(1)).dropna().tail(LOOKBACK)
                if len(log_ret) < 2:
                    continue
                vol = float(log_ret.std() * np.sqrt(252))
                if vol > 0:
                    vols[code] = vol
            if vols:
                # 选波动率最低的NUM只
                target = [c for c, _ in sorted(vols.items(), key=lambda x: x[1])[:NUM]]
                total_val = pf.value(prices)
                # 卖出不在目标的
                for code in list(pf.pos.keys()):
                    if code not in target:
                        pf.sell_all(code, prices.get(code, 0))
                # 买入目标
                w = 1.0 / len(target)
                for code in target:
                    pf.trade_to_target(code, total_val * w, prices.get(code, 0))

        pf.daily.append({'date': str(td)[:10], 'value': pf.value(prices)})

    vals = [d['value'] for d in pf.daily]
    if not vals:
        return None
    final = vals[-1]
    total_ret = (final - cash) / cash
    n = len(vals)
    cagr = (final / cash) ** (252.0 / n) - 1 if n > 0 else 0
    peak = vals[0]
    max_dd = 0
    for v in vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    rets = np.diff(vals) / np.array(vals[:-1])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0

    return {
        'final_value': final, 'total_ret': total_ret, 'cagr': cagr,
        'max_dd': max_dd, 'sharpe': sharpe, 'trading_days': n,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, default='2021-08-17')
    parser.add_argument('--end', type=str, default='2026-08-17')
    parser.add_argument('--cash', type=float, default=100000)
    args = parser.parse_args()

    print(f"低波动ETF轮动策略回测 {args.start} ~ {args.end}")
    r = run(args.start, args.end, args.cash)
    if r is None:
        print("回测失败")
        return
    print(f"  累计收益: {r['total_ret']*100:+.2f}% | 终值: {r['final_value']:,.0f}")
    print(f"  年化CAGR: {r['cagr']*100:+.2f}%")
    print(f"  最大回撤: {r['max_dd']*100:.2f}% | 夏普: {r['sharpe']:.4f}")
    print(f"  交易日: {r['trading_days']}")


if __name__ == '__main__':
    main()
