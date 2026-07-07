"""
七星港股版 1/3/5年回测确认最优参数
"""
import sys, math, warnings
sys.path.insert(0, '.')
from backtest.hk_optimize import *

periods = [('1年','2025-06-26','2026-06-27'), ('3年','2023-06-26','2026-06-27'), ('5年','2021-06-26','2026-06-27')]
best_configs = [
    ("当前默认 Thr=0.5 恐慌", 5, 0.5, True, 25),
    ("Thr=0.7 无恐慌", 5, 0.7, False, 25),
    ("Thr=0.7 恐慌", 5, 0.7, True, 25),
    ("Thr=1.0 无恐慌", 5, 1.0, False, 25),
    ("Thr=1.0 恐慌", 5, 1.0, True, 25),
    ("HN=3 Thr=0.7 无恐慌", 3, 0.7, False, 25),
]

results = {}
for pn, start, end in periods:
    # 加载该区间数据
    pdata = {}
    for code in HK_POOL:
        fp = HK_DIR / f'hk{code}.csv'
        if not fp.exists(): continue
        df = pd.read_csv(fp); df.columns = [c.lower().strip() for c in df.columns]
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        m = (df.index >= start) & (df.index <= end)
        df = df[m]
        if len(df) >= 25: pdata[code] = df
    
    td_all = sorted(set().union(*[set(df.index) for df in pdata.values()]))
    td = [d for d in td_all if start <= d.strftime('%Y-%m-%d') <= end]
    
    print(f"\n{'='*70}")
    print(f"[{pn}] {len(pdata)}只/{len(td)}交易日")
    print(f"{'='*70}")
    print(f"{'配置':<30} {'累计%':>8} {'CAGR%':>7} {'回撤%':>7} {'夏普':>6} {'交易':>5} {'恐慌':>5}")
    print("-" * 75)

    for label, hn, thr, panic, lb in best_configs:
        r = run(pdata, td, hn, thr, panic, lb)
        results[(pn, label)] = r
        print(f"{label:<30} {r['tr']:>+7.1f} {r['cagr']:>7.1f} {-r['mdd']:>7.1f} {r['sh']:>6.2f} {r['nt']:>5} {r['pd']:>5}")

# 汇总
print(f"\n{'='*70}")
print("跨周期汇总 (累计/回撤)")
print(f"{'='*70}")
print(f"{'配置':<30} {'1年':>18} {'3年':>18} {'5年':>18}")
for label, hn, thr, panic, lb in best_configs:
    vals = []
    for pn in ['1年','3年','5年']:
        r = results.get((pn, label), {})
        if r:
            vals.append(f"{r['tr']:+.0f}%/-{r['mdd']:.0f}%")
        else:
            vals.append('N/A')
    print(f"{label:<30} {vals[0]:>18} {vals[1]:>18} {vals[2]:>18}")

print("\n完成!")
