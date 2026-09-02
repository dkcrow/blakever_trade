#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全天候逆波动率 + 阿尔法抄底 策略回测 (日线近似)
================================================
基于聚宽"拆解低回撤策略"(作者fafa_18) 本地回测。

策略结构:
- 策略B(全天候底仓): 5只资产(黄金/豆粕/纳指/创业板/科创) 月度逆波动率加权
  + 创业板ROC择时(20日ROC>8%配创业板, <0%配可转债)
- 策略A(阿尔法抄底): 上证指数 昨跌<=-1.5% 且 今跌<=-1.4% → 全仓买中证1000, 持20天清仓

用法: python backtest/allweather_alpha_backtest.py --start 2021-08-17 --end 2026-08-17
"""
import sys, os, io, math, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'
INDEX_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'index'

# 策略参数
ALL_SYMBOLS = {  # 5只底仓资产
    'sh518880': '黄金ETF',
    'sz159985': '豆粕ETF',
    'sh513100': '纳指100',
    'sz159915': '创业板ETF',
    'sh588200': '科创100ETF',
}
BOND = 'sh512890'      # 可转债ETF(防御)
ALPHA_ETF = 'sh512100' # 中证1000(阿尔法抄底标的)
VOL_LOOKBACK = 60
ROC_PERIOD = 20
ROC_BUY = 0.08
ROC_SELL = 0.0
ALPHA_Y = -0.015
ALPHA_T = -0.014
ALPHA_HOLD = 20
COMMISSION = 0.00013
MIN_COMM = 5


def load(code, is_index=False):
    d = INDEX_DIR if is_index else DATA_DIR
    fp = d / f'{code[2:]}.csv'
    if not fp.exists():
        return None
    df = pd.read_csv(fp)
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()


class Portfolio:
    def __init__(self, cash):
        self.cash = cash
        self.pos = {}  # code -> shares
        self.cost = {}  # code -> avg_cost
        self.daily = []

    def value(self, prices):
        v = self.cash
        for code, sh in self.pos.items():
            if code in prices:
                v += sh * prices[code]
        return v

    def trade_to_target(self, code, target_value, price):
        """调整到目标市值"""
        if price <= 0 or target_value <= 0:
            return
        cur_sh = self.pos.get(code, 0)
        target_sh = int(target_value / price // 100) * 100
        diff = target_sh - cur_sh
        if abs(diff) < 100:
            return
        if diff > 0:  # 买入
            cost = diff * price
            comm = max(cost * COMMISSION, MIN_COMM)
            if cost + comm > self.cash:
                return
            self.cash -= cost + comm
            if code in self.pos:
                old_sh = self.pos[code]
                old_cost = self.cost[code] * old_sh
                self.pos[code] += diff
                self.cost[code] = (old_cost + cost) / (old_sh + diff)
            else:
                self.pos[code] = diff
                self.cost[code] = price
        else:  # 卖出
            sell_sh = -diff
            actual = min(sell_sh, cur_sh)
            cost = actual * price
            comm = max(cost * COMMISSION, MIN_COMM)
            self.cash += cost - comm
            self.pos[code] = cur_sh - actual
            if self.pos[code] <= 0:
                self.pos.pop(code, None)
                self.cost.pop(code, None)

    def sell_all(self, code, price):
        if code not in self.pos:
            return
        sh = self.pos[code]
        cost = sh * price
        comm = max(cost * COMMISSION, MIN_COMM)
        self.cash += cost - comm
        self.pos.pop(code, None)
        self.cost.pop(code, None)


def run(start, end, cash=100000):
    # 加载数据
    data = {}
    for code in ALL_SYMBOLS:
        data[code] = load(code)
    data[BOND] = load(BOND)
    data[ALPHA_ETF] = load(ALPHA_ETF)
    sh_idx = load('sh000001', is_index=True)

    # 交易日
    dates = set()
    for df in data.values():
        if df is not None:
            dates.update(df.index)
    dates = sorted(d for d in dates if pd.Timestamp(start) <= d <= pd.Timestamp(end))

    pf = Portfolio(cash)
    alpha_active = False
    alpha_day = 0
    roc_signal = 0
    monthly_weights = {}
    last_rebalance_month = None

    for i, td in enumerate(dates):
        # 当日价格快照
        prices = {}
        for code, df in data.items():
            if df is None:
                continue
            m = df.index <= td
            if m.any():
                prices[code] = float(df.loc[m, 'close'].iloc[-1])

        # ===== 阿尔法状态检查 =====
        if alpha_active:
            alpha_day += 1
            if alpha_day >= ALPHA_HOLD:
                pf.sell_all(ALPHA_ETF, prices.get(ALPHA_ETF, 0))
                alpha_active = False
                alpha_day = 0
        else:
            # 检查阿尔法抄底信号 (上证指数)
            if sh_idx is not None:
                m = sh_idx.index <= td
                hist = sh_idx[m]
                if len(hist) >= 2:
                    y1 = float(hist['close'].iloc[-2])
                    y2 = float(hist['close'].iloc[-1])
                    # y_cha = 昨日跌幅, t_cha = 今日跌幅(用收盘近似)
                    y_cha = (y2 - y1) / y1
                    t_cha = 0  # 日线近似: 今日收盘 vs 昨日收盘 = y_cha 本身
                    # 注意: 原策略用分钟tick, 这里日线近似为"昨日跌幅和今日开盘跳空"
                    # 简化: 只用昨日跌幅判断(因为本地无分钟数据)
                    # 用连续两日跌幅近似: 前日跌幅 + 昨日跌幅
                    if len(hist) >= 3:
                        y0 = float(hist['close'].iloc[-3])
                        prev_cha = (y1 - y0) / y0  # 前日跌幅
                        if prev_cha <= ALPHA_Y and y_cha <= ALPHA_T:
                            # 触发阿尔法: 清仓全部, 全仓买中证1000
                            for c in list(pf.pos.keys()):
                                pf.sell_all(c, prices.get(c, 0))
                            if ALPHA_ETF in prices:
                                pf.trade_to_target(ALPHA_ETF, pf.cash, prices[ALPHA_ETF])
                            alpha_active = True
                            alpha_day = 0

        # ===== 策略B: 月度逆波动率调仓 =====
        if not alpha_active:
            cur_month = td.strftime('%Y-%m')
            if cur_month != last_rebalance_month:
                last_rebalance_month = cur_month
                # 计算逆波动率权重
                vols = {}
                for code in ALL_SYMBOLS:
                    df = data[code]
                    if df is None:
                        continue
                    m = df.index <= td
                    hist = df[m]['close']
                    if len(hist) < VOL_LOOKBACK + 1:
                        continue
                    rets = hist.pct_change().dropna().tail(VOL_LOOKBACK)
                    if len(rets) < 2:
                        continue
                    vol = float(rets.std())
                    if vol > 0:
                        vols[code] = vol
                if vols:
                    inv = {c: 1.0 / v for c, v in vols.items()}
                    tot = sum(inv.values())
                    monthly_weights = {c: inv[c] / tot for c in inv}

                # 执行调仓: 4只固定资产按权重, 创业板槽位由ROC决定
                if monthly_weights:
                    total_val = pf.value(prices)
                    # 创业板槽位
                    chuangye_w = monthly_weights.get('sz159915', 0)
                    # 4只固定资产
                    for code in ALL_SYMBOLS:
                        if code == 'sz159915':
                            continue
                        w = monthly_weights.get(code, 0)
                        pf.trade_to_target(code, w * total_val, prices.get(code, 0))
                    # 创业板槽位
                    if roc_signal == 1:
                        pf.trade_to_target('sz159915', chuangye_w * total_val, prices.get('sz159915', 0))
                        if BOND in pf.pos:
                            pf.sell_all(BOND, prices.get(BOND, 0))
                    else:
                        pf.trade_to_target(BOND, chuangye_w * total_val, prices.get(BOND, 0))
                        if 'sz159915' in pf.pos:
                            pf.sell_all('sz159915', prices.get('sz159915', 0))

            # ===== 每日: 创业板ROC择时 =====
            df_cy = data.get('sz159915')
            if df_cy is not None:
                m = df_cy.index <= td
                hist = df_cy[m]['close']
                if len(hist) >= ROC_PERIOD + 1:
                    roc = float(hist.iloc[-1] / hist.iloc[-(ROC_PERIOD+1)] - 1)
                    old_sig = roc_signal
                    if roc > ROC_BUY:
                        roc_signal = 1
                    elif roc < ROC_SELL:
                        roc_signal = 0
                    if roc_signal != old_sig:
                        # 切换创业板/可转债
                        chuangye_w = monthly_weights.get('sz159915', 0)
                        total_val = pf.value(prices)
                        if roc_signal == 1:
                            pf.trade_to_target('sz159915', chuangye_w * total_val, prices.get('sz159915', 0))
                            if BOND in pf.pos:
                                pf.sell_all(BOND, prices.get(BOND, 0))
                        else:
                            pf.trade_to_target(BOND, chuangye_w * total_val, prices.get(BOND, 0))
                            if 'sz159915' in pf.pos:
                                pf.sell_all('sz159915', prices.get('sz159915', 0))

        # 记录净值
        pf.daily.append({'date': str(td)[:10], 'value': pf.value(prices)})

    # 计算指标
    vals = [d['value'] for d in pf.daily]
    if not vals:
        return None
    final = vals[-1]
    total_ret = (final - cash) / cash
    n = len(vals)
    cagr = (final / cash) ** (252.0 / n) - 1 if n > 0 else 0

    # 最大回撤
    peak = vals[0]
    max_dd = 0
    for v in vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    # 夏普
    rets = np.diff(vals) / np.array(vals[:-1])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0

    return {
        'final_value': final,
        'total_ret': total_ret,
        'cagr': cagr,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'trading_days': n,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, default='2021-08-17')
    parser.add_argument('--end', type=str, default='2026-08-17')
    parser.add_argument('--cash', type=float, default=100000)
    args = parser.parse_args()

    print(f"全天候+阿尔法策略回测 {args.start} ~ {args.end}")
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
