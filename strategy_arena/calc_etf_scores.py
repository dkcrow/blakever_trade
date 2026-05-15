#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算7只ETF的策略评分排名（截至最新交易日）"""
import sys, math, os
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

LOCAL_BASE = r"C:\Users\blakehao\.qclaw\workspace\workspace_full_20260430"
DATA_DIR = os.path.join(LOCAL_BASE, "back_trader_stocks", "a")

INVEST_POOL = ['159915_XSHE', '513100_XSHG', '159985_XSHE', '518880_XSHG', '501018_XSHG', '161226_XSHE']
SAFE_POOL   = ['511220_XSHG']
CN_ETF_POOL = INVEST_POOL + SAFE_POOL
CN_ETF_NAMES = {
    '159915_XSHE': '创业板ETF',
    '513100_XSHG': '纳指ETF',
    '159985_XSHE': '科创板ETF',
    '518880_XSHG': '黄金ETF',
    '501018_XSHG': '原油ETF',
    '161226_XSHE': 'H股LOF',
    '511220_XSHG': '货币ETF',
}

SHORT_LOOKBACK = 25
LONG_LOOKBACK  = 250
DROP_THRESHOLD = 0.95
SHORT_SCORE_CAP = 6.0
LONG_SCORE_CAP  = 0.5

# ── 加载数据 ──────────────────────────────────────────────
def load_all():
    dfs = {}
    for code in CN_ETF_POOL:
        fpath = os.path.join(DATA_DIR, f"{code}.csv")
        if not os.path.exists(fpath):
            print(f"[WARN] 找不到: {fpath}")
            continue
        df = pd.read_csv(fpath)
        date_col = [c for c in df.columns if 'date' in c.lower()][0]
        close_col = [c for c in df.columns if 'close' in c.lower() or 'price' in c.lower()][0]
        df = df[[date_col, close_col]].rename(columns={date_col:'date', close_col: code})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        dfs[code] = df[code]
    return pd.DataFrame(dfs)

df_all = load_all()
print(f"数据范围: {df_all.index[0].date()} ~ {df_all.index[-1].date()}")

# ── 最新交易日 ────────────────────────────────────────────
latest = df_all.index[-1]
loc = len(df_all) - 1

actual_short = min(SHORT_LOOKBACK, loc)
actual_long  = min(LONG_LOOKBACK,  loc)
print(f"实际窗口: 短期={actual_short}天, 长期={actual_long}天\n")

results = []

for asset in CN_ETF_POOL:
    if asset not in df_all.columns:
        continue

    sp = df_all[asset].iloc[max(0, loc - actual_short): loc + 1].dropna()
    if len(sp) < 5:
        print(f"[SKIP] {asset} 数据不足")
        continue

    # ── 近期4日跌幅过滤 ──────────────────────────────────
    dropped = False
    if len(sp) >= 4:
        recent4 = sp.iloc[-4:]
        for j in range(len(recent4) - 1):
            if recent4.iloc[j] > 0:
                ratio = recent4.iloc[j + 1] / recent4.iloc[j]
                if ratio < DROP_THRESHOLD:
                    dropped = True
                    break

    # ── 短期动量评分 ────────────────────────────────────
    short_score = 0.0
    y = np.log(sp.values.astype(float))
    x = np.arange(len(y), dtype=float)
    w = np.linspace(1, 2, len(y))
    try:
        coeffs = np.polyfit(x, y, 1, w=w)
        slope  = coeffs[0]
        y_pred = slope * x + coeffs[1]
        ss_res = np.sum(w * (y - y_pred) ** 2)
        y_mean = np.average(y, weights=w)
        ss_tot = np.sum(w * (y - y_mean) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0
        ann_return = math.exp(slope * 252) - 1
        short_score = ann_return * r2
        if not (0 < short_score < SHORT_SCORE_CAP):
            short_score = 0.0
    except:
        pass

    # ── 长期动量评分 ────────────────────────────────────
    lp = df_all[asset].iloc[max(0, loc - actual_long): loc + 1].dropna()
    long_score = 0.0
    if len(lp) >= 20:
        y2 = np.log(lp.values.astype(float))
        x2 = np.arange(len(y2), dtype=float)
        w2 = np.linspace(1, 2, len(y2))
        try:
            coeffs2 = np.polyfit(x2, y2, 1, w=w2)
            slope2  = coeffs2[0]
            y2_pred = slope2 * x2 + coeffs2[1]
            ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
            y2_mean = np.average(y2, weights=w2)
            ss_tot2 = np.sum(w2 * (y2 - y2_mean) ** 2)
            r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 1e-10 else 0
            ann2 = math.exp(slope2 * 252) - 1
            long_score = ann2 * r22
            if not (long_score > 0 and long_score < LONG_SCORE_CAP):
                long_score = 0.0
        except:
            pass

    combined = short_score + long_score
    results.append({
        'code':  asset,
        'name':  CN_ETF_NAMES.get(asset, asset),
        'short_score': round(short_score, 4),
        'long_score':  round(long_score, 4),
        'combined':    round(combined, 4),
        'dropped':     dropped,
        'selected':    '✅' if (combined > 0 and not dropped and combined == max(r['combined'] for r in results + [{'combined': combined}])) else '',
    })

# 重新判断选中者（等所有结果收集完）
max_combined = max(r['combined'] for r in results)
for r in results:
    r['selected'] = '✅' if (r['combined'] == max_combined and not r['dropped']) else ('❌ 近期跌幅超5%' if r['dropped'] else '⬜ 得分非最高')

# 排序
results.sort(key=lambda x: x['combined'], reverse=True)

print("=" * 62)
print(f"📊 七星高照6+1 ETF评分排名（截至 {latest.date()}）")
print("=" * 62)
print(f"{'排名':<4} {'ETF名称':<10} {'短期分':>8} {'长期分':>8} {'综合分':>8} {'状态'}")
print("-" * 62)
for i, r in enumerate(results, 1):
    print(f"{i:<4} {r['name']:<10} {r['short_score']:>8.4f} {r['long_score']:>8.4f} {r['combined']:>8.4f}  {r['selected']}")
print("=" * 62)
winner = [r for r in results if r['selected'] == '✅']
if winner:
    print(f"\n🎯 当日建议: 买入 {winner[0]['name']}（综合分 {winner[0]['combined']:.4f}）")
elif any(r['dropped'] for r in results):
    print(f"\n🎯 当日建议: 持有货币ETF（所有正动量ETF均已跌幅超5%）")