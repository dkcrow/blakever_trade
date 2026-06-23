#!/usr/bin/env python3
"""补齐4个监测指数日线到最新(akshare), 写回CSV, 并用新数据重算QMT行情判断真实状态。
CSV格式对齐原文件: Date,Open,Close,High,Low,Volume (date升序)
"""
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import akshare as ak

index_dir = Path('data/storage/stock_data/index')
index_map = {
    '沪深300': 'sh000300.csv',
    '创业板指': 'sz399006.csv',
    '上证指数': 'sh000001.csv',
    '中证500': 'sh000905.csv',
}
symbol_map = {
    '沪深300': 'sh000300', '创业板指': 'sz399006',
    '上证指数': 'sh000001', '中证500': 'sh000905',
}

print("=== 补齐指数数据 (akshare) ===")
for name, fn in index_map.items():
    sym = symbol_map[name]
    try:
        df = ak.stock_zh_index_daily(symbol=sym)  # date,open,high,low,close,volume
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        out = pd.DataFrame({
            'Date': df['date'].dt.strftime('%Y-%m-%d'),
            'Open': df['open'].round(2),
            'Close': df['close'].round(2),
            'High': df['high'].round(2),
            'Low': df['low'].round(2),
            'Volume': df['volume'].astype('int64'),
        })
        fp = index_dir / fn
        out.to_csv(fp, index=False)
        print(f"  {name:<8} {fn}: {len(out)}行, 最新={out['Date'].iloc[-1]} 收盘={out['Close'].iloc[-1]}")
    except Exception as e:
        print(f"  {name:<8} 失败: {repr(e)[:150]}")

# === 用新数据重算 (复现 generate_qmt_report.get_regime_status) ===
def get_latest_trading_date():
    t = datetime.now()
    if t.weekday() == 5: t -= timedelta(days=1)
    elif t.weekday() == 6: t -= timedelta(days=2)
    return t.strftime('%Y-%m-%d')

LATEST_DATE = get_latest_trading_date()
TODAY = datetime.now().strftime('%Y-%m-%d')
print(f"\n=== 重算行情判断 (今天={TODAY}, LATEST_DATE={LATEST_DATE}) ===")
print(f"{'指数':<8}{'文件最新':<13}{'gap':<5}{'判断日':<13}{'收盘':>9}{'MA10':>9}{'状态':>8}")
print("-"*72)
below_count = 0; total = 0
for name, fn in index_map.items():
    fp = index_dir / fn
    df = pd.read_csv(fp)
    for c in df.columns:
        if c.lower().strip() == 'date' and c != 'date': df = df.rename(columns={c: 'date'})
        elif c.lower().strip() == 'close' and c != 'close': df = df.rename(columns={c: 'close'})
    df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
    file_last = df.index[-1].strftime('%Y-%m-%d')
    gap = (pd.Timestamp(TODAY) - df.index[-1]).days
    hist = df[df.index <= pd.Timestamp(LATEST_DATE)]
    if len(hist) < 11: continue
    total += 1
    used = hist.index[-1].strftime('%Y-%m-%d')
    cur = hist['close'].iloc[-1]; ma10 = hist['close'].iloc[-(10+1):-1].mean()
    below = cur < ma10
    if below: below_count += 1
    print(f"{name:<8}{file_last:<13}{gap:<5}{used:<13}{cur:>9.1f}{ma10:>9.1f}{'⚠️跌破' if below else '✅站上':>8}")
print("-"*72)
threshold = max(2, int(total * 0.75))
is_weak = below_count >= threshold
print(f"跌破: {below_count}/{total} | 走弱阈值≥{threshold} | 判定: {'🔴走弱期' if is_weak else '🟢正常期'}")
