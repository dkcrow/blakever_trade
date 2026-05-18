#!/usr/bin/env python3
"""
聚宽搅屎棍策略纯选股回测 — 测量个股选股的真实alpha贡献
目的是：看看搅屎棍策略用512只个股能产生多少超额收益
"""

import sys
import os
import math
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(__file__))
from portfolio_backtest import run_portfolio_backtest_vec, load_cn_all_stocks
from cross_regime_scheduler import load_cn_etf_data, CN_RISK_FREE_RATE, CN_MAIN_START, CN_MAIN_END

LOCAL_CN_DIR = '/data/workspace/back_trader_stocks/a'


def load_cn_etf_close():
    cn_data = load_cn_etf_data()
    return pd.DataFrame({sym: df['Close'] for sym, df in cn_data.items()}).sort_index()


def test_jsg_pure(etf_close, stock_close, stock_volume):
    """测试不同选股逻辑的搅屎棍策略"""
    
    all_dates = stock_close.index.intersection(etf_close.index)
    etf_close = etf_close.loc[all_dates]
    stock_close = stock_close.loc[all_dates]
    stock_volume = stock_volume.loc[all_dates]
    
    turnover_df = stock_close * stock_volume
    
    versions = {}
    
    # ====== 版本A：原策略近似 — 从中小盘选动量最强 ======
    print("\n  📊 版本A：中小盘(20-70%分位) → 动量最强6只 → 缓冲池")
    w_a = pd.DataFrame(0.0, index=all_dates, columns=etf_close.columns.tolist() + stock_close.columns.tolist())
    holdings = []
    for i in range(20, len(all_dates)):
        if i % 5 == 0:
            loc = i
            lb = min(20, loc)
            if lb < 5:
                continue
            avg_to = turnover_df.iloc[loc-lb:loc+1].mean()
            vt = avg_to.dropna()
            if len(vt) < 30:
                continue
            p20, p70 = vt.quantile(0.20), vt.quantile(0.70)
            mid = vt[(vt >= p20) & (vt <= p70)].index.tolist()
            
            scores = {}
            for code in mid:
                p = stock_close[code].iloc[loc-lb:loc+1]
                v = stock_volume[code].iloc[loc-lb:loc+1]
                if (v == 0).sum() > 10:
                    continue
                vp = p[v > 0].dropna()
                if len(vp) < 5:
                    continue
                ret = vp.iloc[-1] / vp.iloc[0] - 1.0
                vol = vp.pct_change(fill_method=None).std()
                if vol > 0 and ret > 0:
                    scores[code] = ret / vol
            
            top12 = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:12]
            new_h = []
            for s in holdings:
                if s in top12 and len(new_h) < 6:
                    new_h.append(s)
            for s in top12:
                if s not in new_h and len(new_h) < 6:
                    new_h.append(s)
            holdings = new_h
        
        for s in holdings:
            if s in w_a.columns:
                w_a.loc[all_dates[i], s] = 1.0 / max(len(holdings), 1)
    
    r_a = run_portfolio_backtest_vec(etf_close, stock_close, stock_volume, w_a, 
                                     CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE, 'CN')
    if r_a:
        print(f"     年化: {r_a['annual_return']:+.2f}% | 回撤: {r_a['max_drawdown']:.1f}% | 夏普: {r_a['sharpe']:.2f}")
    versions['A_中小盘动量'] = r_a
    
    # ====== 版本B：纯小盘(前20%成交额) → 动量最强6只 ======
    print("\n  📊 版本B：纯小盘(前20%成交额) → 动量最强6只")
    w_b = pd.DataFrame(0.0, index=all_dates, columns=etf_close.columns.tolist() + stock_close.columns.tolist())
    holdings = []
    for i in range(20, len(all_dates)):
        if i % 5 == 0:
            loc = i
            lb = min(20, loc)
            if lb < 5:
                continue
            avg_to = turnover_df.iloc[loc-lb:loc+1].mean()
            vt = avg_to.dropna()
            if len(vt) < 30:
                continue
            p20 = vt.quantile(0.20)
            small = vt[vt <= p20].index.tolist()
            
            scores = {}
            for code in small:
                p = stock_close[code].iloc[loc-lb:loc+1]
                v = stock_volume[code].iloc[loc-lb:loc+1]
                if (v == 0).sum() > 10:
                    continue
                vp = p[v > 0].dropna()
                if len(vp) < 5:
                    continue
                ret = vp.iloc[-1] / vp.iloc[0] - 1.0
                vol = vp.pct_change(fill_method=None).std()
                if vol > 0 and ret > 0:
                    scores[code] = ret / vol
            
            top12 = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:12]
            new_h = []
            for s in holdings:
                if s in top12 and len(new_h) < 6:
                    new_h.append(s)
            for s in top12:
                if s not in new_h and len(new_h) < 6:
                    new_h.append(s)
            holdings = new_h
        
        for s in holdings:
            if s in w_b.columns:
                w_b.loc[all_dates[i], s] = 1.0 / max(len(holdings), 1)
    
    r_b = run_portfolio_backtest_vec(etf_close, stock_close, stock_volume, w_b, 
                                     CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE, 'CN')
    if r_b:
        print(f"     年化: {r_b['annual_return']:+.2f}% | 回撤: {r_b['max_drawdown']:.1f}% | 夏普: {r_b['sharpe']:.2f}")
    versions['B_纯小盘动量'] = r_b
    
    # ====== 版本C：全市场动量最强6只（不管市值） ======
    print("\n  📊 版本C：全市场动量最强6只（不管市值）")
    w_c = pd.DataFrame(0.0, index=all_dates, columns=etf_close.columns.tolist() + stock_close.columns.tolist())
    holdings = []
    for i in range(20, len(all_dates)):
        if i % 5 == 0:
            loc = i
            lb = min(20, loc)
            if lb < 5:
                continue
            
            scores = {}
            for code in stock_close.columns:
                p = stock_close[code].iloc[loc-lb:loc+1]
                v = stock_volume[code].iloc[loc-lb:loc+1]
                if (v == 0).sum() > 10:
                    continue
                vp = p[v > 0].dropna()
                if len(vp) < 5:
                    continue
                ret = vp.iloc[-1] / vp.iloc[0] - 1.0
                vol = vp.pct_change(fill_method=None).std()
                if vol > 0 and ret > 0:
                    scores[code] = ret / vol
            
            top12 = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:12]
            new_h = []
            for s in holdings:
                if s in top12 and len(new_h) < 6:
                    new_h.append(s)
            for s in top12:
                if s not in new_h and len(new_h) < 6:
                    new_h.append(s)
            holdings = new_h
        
        for s in holdings:
            if s in w_c.columns:
                w_c.loc[all_dates[i], s] = 1.0 / max(len(holdings), 1)
    
    r_c = run_portfolio_backtest_vec(etf_close, stock_close, stock_volume, w_c, 
                                     CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE, 'CN')
    if r_c:
        print(f"     年化: {r_c['annual_return']:+.2f}% | 回撤: {r_c['max_drawdown']:.1f}% | 夏普: {r_c['sharpe']:.2f}")
    versions['C_全市场动量'] = r_c
    
    # ====== 版本D：全市场等权持有512只（基准）======
    print("\n  📊 版本D：全市场等权512只（基准）")
    w_d = pd.DataFrame(0.0, index=all_dates, columns=etf_close.columns.tolist() + stock_close.columns.tolist())
    for date in all_dates[20:]:
        for code in stock_close.columns:
            w_d.loc[date, code] = 1.0 / len(stock_close.columns)
    
    r_d = run_portfolio_backtest_vec(etf_close, stock_close, stock_volume, w_d, 
                                     CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE, 'CN')
    if r_d:
        print(f"     年化: {r_d['annual_return']:+.2f}% | 回撤: {r_d['max_drawdown']:.1f}% | 夏普: {r_d['sharpe']:.2f}")
    versions['D_全市场等权基准'] = r_d
    
    # ====== 版本E：月频全市场动量最强1只（模拟ROA） ======
    print("\n  📊 版本E：月频全市场夏普最高1只（模拟ROA）")
    w_e = pd.DataFrame(0.0, index=all_dates, columns=etf_close.columns.tolist() + stock_close.columns.tolist())
    holding = None
    for i in range(20, len(all_dates)):
        if i % 20 == 0:
            loc = i
            lb = min(60, loc)
            if lb < 10:
                continue
            
            scores = {}
            for code in stock_close.columns:
                p = stock_close[code].iloc[loc-lb:loc+1]
                v = stock_volume[code].iloc[loc-lb:loc+1]
                if (v == 0).sum() > 20:
                    continue
                vp = p[v > 0].dropna()
                if len(vp) < 10:
                    continue
                dr = vp.pct_change(fill_method=None).dropna()
                if len(dr) < 5:
                    continue
                std = dr.std()
                mean = dr.mean()
                if std > 0 and mean > 0:
                    scores[code] = (mean * 252) / (std * np.sqrt(252))
            
            if scores:
                holding = max(scores, key=scores.get)
        
        if holding and holding in w_e.columns:
            w_e.loc[all_dates[i], holding] = 1.0
    
    r_e = run_portfolio_backtest_vec(etf_close, stock_close, stock_volume, w_e, 
                                     CN_MAIN_START, CN_MAIN_END, CN_RISK_FREE_RATE, 'CN')
    if r_e:
        print(f"     年化: {r_e['annual_return']:+.2f}% | 回撤: {r_e['max_drawdown']:.1f}% | 夏普: {r_e['sharpe']:.2f}")
    versions['E_月频夏普最高1只'] = r_e
    
    # ====== 汇总 ======
    print(f"\n{'='*80}")
    print(f"  📊 搅屎棍策略各选股逻辑对比")
    print(f"{'='*80}")
    print(f"  {'版本':<20} {'年化':>8} {'回撤':>8} {'夏普':>8} {'胜率':>8} {'盈亏比':>8}")
    print(f"  {'─'*20} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
    for name, r in versions.items():
        if r:
            print(f"  {name:<20} {r['annual_return']:>+7.2f}% {r['max_drawdown']:>7.1f}% {r['sharpe']:>7.2f} {r['win_rate']:>7.1f}% {r['profit_factor']:>7.2f}")
    
    # ====== 沪深300基准 ======
    print(f"  {'─'*20} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
    print(f"  {'沪深300买入持有':<20} — 参考年化约6-8%")
    
    return versions


if __name__ == '__main__':
    
    print(f"\n{'#'*80}")
    print(f"  🧪 搅屎棍策略选股逻辑对比测试")
    print(f"  📖 来源: https://www.joinquant.com/post/64178")
    print(f"{'#'*80}")
    
    print(f"\n📦 加载数据...")
    etf_close = load_cn_etf_close()
    stock_close, stock_volume = load_cn_all_stocks(min_days=500)
    
    test_jsg_pure(etf_close, stock_close, stock_volume)
