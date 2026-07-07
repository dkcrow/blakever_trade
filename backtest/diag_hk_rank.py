#!/usr/bin/env python3
"""诊断: 港股版网易(09999) vs 华虹(01347) 动量排名分解
复现 hk_live_report calc_score, 分解 slope/年化/R², 展示最近价格。
"""
import warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/hk')

def load(code):
    df = pd.read_csv(DATA_DIR / f'hk{code}.csv')
    df.columns = [c.lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').sort_index()

def calc_score_breakdown(closes):
    """复现港股版 calc_score, 返回 (score, slope, ann, r2)"""
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    w = np.linspace(1, 2, len(x_m))
    slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
    ann = np.exp(slope * 250)
    fitted = slope * x_m + intercept; res = y_m - fitted
    ss_res = np.sum(w * res**2); ss_tot = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    score = (ann - 1) * r2
    return score, slope, ann, r2

for code, name in [('09999','网易'),('01347','华虹半导体')]:
    df = load(code)
    last_date = df.index[-1]
    print(f"\n{'='*70}")
    print(f"  {code} {name} | 数据最新日期: {last_date.strftime('%Y-%m-%d')}")
    print('='*70)
    # 港股版排名用 hist = df[df.index < date] 的最后25根 (不含"当日")
    # 实盘中 date=今天, 所以用全部历史的最后25根(=截止最新CSV收盘)
    closes25 = df['close'].values[-25:]
    score, slope, ann, r2 = calc_score_breakdown(closes25)
    print(f"  25日动量得分(score): {score:.4f}")
    print(f"    - 年化倍数 exp(slope×250): {ann:.4f}  (=年化{(ann-1)*100:+.1f}%)")
    print(f"    - 拟合优度 R²: {r2:.4f}")
    print(f"    - 日斜率 slope: {slope:.5f}")
    print(f"  最近10日收盘价:")
    recent = df['close'].tail(10)
    for d, v in recent.items():
        print(f"    {d.strftime('%Y-%m-%d')}: {v:.2f}")
    # 25日涨跌
    c25 = df['close'].values[-25:]
    print(f"  25日区间: {c25[0]:.2f} → {c25[-1]:.2f} ({(c25[-1]/c25[0]-1)*100:+.1f}%)")
