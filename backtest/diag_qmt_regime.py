#!/usr/bin/env python3
"""诊断: 七星QMT报告"行情判断"数据核对
复现 generate_qmt_report.py get_regime_status 算法, 额外打印各指数数据最新日期/cur/ma10/是否跌破。
"""
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

def get_latest_trading_date():
    today = datetime.now()
    if today.weekday() == 5: today = today - timedelta(days=1)
    elif today.weekday() == 6: today = today - timedelta(days=2)
    return today.strftime('%Y-%m-%d')

LATEST_DATE = get_latest_trading_date()
TODAY = datetime.now().strftime('%Y-%m-%d')
index_dir = Path('data/storage/stock_data/index')

index_map = {
    '沪深300': 'sh000300.csv',
    '创业板指': 'sz399006.csv',
    '上证指数': 'sh000001.csv',
    '中证500': 'sh000905.csv',
}

print(f"今天={TODAY} | LATEST_DATE(脚本mask上限)={LATEST_DATE}")
print(f"指数目录: {index_dir.resolve()}")
print("="*92)
print(f"{'指数':<8}{'文件最新日期':<14}{'gap天':<7}{'用于判断日期':<14}{'收盘':>9}{'MA10':>9}{'状态':>8}")
print("-"*92)

below_count = 0; total = 0
for name, fn in index_map.items():
    fp = index_dir / fn
    if not fp.exists():
        print(f"{name:<8}文件不存在: {fn}")
        continue
    df = pd.read_csv(fp)
    for c in df.columns:
        if c.lower().strip() == 'date' and c != 'date': df = df.rename(columns={c: 'date'})
        elif c.lower().strip() == 'close' and c != 'close': df = df.rename(columns={c: 'close'})
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    file_last = df.index[-1].strftime('%Y-%m-%d')
    gap = (pd.Timestamp(TODAY) - df.index[-1]).days
    mask = df.index <= pd.Timestamp(LATEST_DATE)
    hist = df[mask]
    if len(hist) < 11:
        print(f"{name:<8}{file_last:<14}{gap:<7}数据不足11根")
        continue
    total += 1
    used_date = hist.index[-1].strftime('%Y-%m-%d')
    cur = hist['close'].iloc[-1]
    ma10 = hist['close'].iloc[-(10+1):-1].mean()
    below = cur < ma10
    if below: below_count += 1
    flag = '⚠️跌破' if below else '✅站上'
    print(f"{name:<8}{file_last:<14}{gap:<7}{used_date:<14}{cur:>9.1f}{ma10:>9.1f}{flag:>8}")

print("-"*92)
threshold = max(2, int(total * 0.75))
is_weak = below_count >= threshold if total > 0 else False
print(f"跌破: {below_count}/{total} | 走弱阈值≥{threshold} | 判定: {'🔴走弱期' if is_weak else '🟢正常期'}")
print("="*92)

# 额外: 用各指数"文件真实最新数据"重算(不受LATEST_DATE mask影响), 看真实当前状态
print("\n[对照] 用各指数文件真实最新一根K线重算(忽略LATEST_DATE截断):")
bc2 = 0; t2 = 0
for name, fn in index_map.items():
    fp = index_dir / fn
    if not fp.exists(): continue
    df = pd.read_csv(fp)
    for c in df.columns:
        if c.lower().strip() == 'date' and c != 'date': df = df.rename(columns={c: 'date'})
        elif c.lower().strip() == 'close' and c != 'close': df = df.rename(columns={c: 'close'})
    df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
    if len(df) < 11: continue
    t2 += 1
    cur = df['close'].iloc[-1]; ma10 = df['close'].iloc[-(10+1):-1].mean()
    if cur < ma10: bc2 += 1
print(f"  真实最新数据跌破: {bc2}/{t2}")
