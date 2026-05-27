#!/usr/bin/env python3
"""深度诊断脚本 - 检查排名、交易、资金曲线"""
import sys, os, io, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
from strategies.etf.seven_star_laplacian import (
    BacktestEngine, LocalDataSource, SevenStarLaplacianEngine,
    ETF_POOL, ETF_NAMES, DEFAULT_PARAMS
)

ds = LocalDataSource('data/storage/stock_data/etf')
all_data = ds.load_all_etfs('2024-06-01', '2025-12-31')

engine = SevenStarLaplacianEngine()

print('='*60)
print('诊断1: 单日排名详情 (2025-01-15)')
print('='*60)
test_date = '2025-01-15'
prices = {}
for code, df in all_data.items():
    mask = df.index <= pd.Timestamp(test_date)
    if mask.any():
        prices[code] = float(df.loc[mask, 'close'].iloc[-1])

ranked = engine.get_ranked_etfs(all_data, prices, test_date)
if ranked:
    for i, m in enumerate(ranked[:10]):
        print(f'  {i+1:>2}. {m["etf"]:12s} {m["etf_name"]:16s} | Score={m["score"]:8.4f} | AnnRet={m["annualized_returns"]*100:7.2f}% | R2={m["r_squared"]:.4f} | Price={m["current_price"]:.3f}')
else:
    print('  无合格ETF!')
    # 检查为什么被过滤
    print('\n  过滤原因分析:')
    for code in list(ETF_POOL)[:5]:
        if code not in all_data:
            continue
        df = all_data[code]
        price = prices.get(code, 0)
        if price <= 0:
            continue
        close_arr = df['close'].values.astype(float)
        price_series = np.append(close_arr, float(price))
        
        reasons = []
        # 盈利保护
        if engine.check_profit_protection(code, price, df, test_date):
            reasons.append('PROFIT_PROTECT')
        # RSI
        rsi = engine.calculate_rsi(price_series)
        if rsi > engine.params['rsi_overbought']:
            reasons.append(f'RSI超买({rsi:.1f})')
        # 短期动量
        if len(price_series) >= 11:
            sm = price_series[-1] / price_series[-11] - 1
            if sm < engine.params['short_momentum_threshold']:
                reasons.append(f'短期动量({sm*100:.1f}%)')
        # 得分
        score, ann, r2 = engine.calculate_score(price_series)
        if not (engine.params['min_score_threshold'] < score < engine.params['max_score_threshold']):
            reasons.append(f'Score={score:.2f}超出范围')
        
        name = ETF_NAMES.get(code, '')
        print(f'    {code} {name:16s} | Price={price:.3f} | 原因: {reasons if reasons else "未知"}')

print()
print('='*60)
print('诊断2: 资金曲线采样')
print('='*60)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    with contextlib.redirect_stderr(buf):
        be = BacktestEngine(ds, {})
        r = be.run('2024-06-01', '2025-12-31', 1000000)

dv = be.portfolio.daily_values
if dv:
    n = len(dv)
    step = max(1, n // 10)
    print(f'  总记录数: {n}')
    for i in range(0, n, step):
        d = dv[i]
        val = d['value']
        pct = (val / 1000000 - 1) * 100
        print('  %s | 资产=%.0f | 收益率=%+.2f%%' % (d['date'], val, pct))
    # 最后一条
    d = dv[-1]
    val = d['value']
    pct = (val / 1000000 - 1) * 100
    print('  %s | 资产=%.0f | 收益率=%+.2f%%' % (d['date'], val, pct))

print()
print('='*60)
print('诊断3: 交易明细分析 (最后20笔)')
print('='*60)
trade_log = be.portfolio.trade_log
if trade_log:
    total_cost = 0
    for t in trade_log[-20:]:
        action = t['action']
        cost = t['shares'] * t['price'] * (t.get('commission', 0.003) if action == 'BUY' else 0)
        total_cost += cost
        pnl_str = ''
        if action == 'SELL':
            pnl_str = f' | PnL={(t["price"]-t.get("cost_price",t["price"]))/t.get("cost_price",t["price"])*100:+.1f}%'
        print(f'  {t["date"]} {action:4s} {t["code"]:12s} {t["shares"]:>8d}@{t["price"]:.3f}{pnl_str}')
    print(f'\n  总交易笔数: {len(trade_log)} | 最后20笔估计手续费: {total_cost:,.0f}')

# 检查是否有大额异常交易
print()
print('='*60)
print('诊断4: 异常交易检测 (单笔>10万)')
print('='*60)
big_trades = [t for t in trade_log if t['shares'] * t['price'] > 100000]
if big_trades:
    for t in big_trades[:10]:
        amt = t['shares'] * t['price']
        print(f'  {t["date"]} {t["action"]:4s} {t["code"]:12s} {amt:>12,.0f} ({t["shares"]}@{t["price"]:.3f})')
    print(f'  共{len(big_trades)}笔大额交易')
