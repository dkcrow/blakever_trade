# 追加测试: 组合优化
import sys, warnings
sys.path.insert(0, '.')
from backtest.hk_optimize import *

add_configs = [
    ("Thr=0.7+恐慌", 5, 0.7, True, 25),
    ("HN=3/Thr=0.7", 3, 0.7, False, 25),
    ("HN=3/Thr=0.7+恐慌", 3, 0.7, True, 25),
    ("HN=3+恐慌", 3, 0.5, True, 25),
    ("Thr=0.8", 5, 0.8, False, 25),
    ("Thr=1.0", 5, 1.0, False, 25),
]

print(f"{'追加配置':<25} {'累计%':>8} {'CAGR%':>7} {'回撤%':>7} {'夏普':>6} {'胜率%':>6} {'交易':>5} {'恐慌':>5} {'终值HKD':>12}")
print("-" * 90)
for label, hn, thr, panic, lb in add_configs:
    r = run(all_data, trade_dates, hn, thr, panic, lb)
    print(f"{label:<25} {r['tr']:>+7.1f} {r['cagr']:>7.1f} {-r['mdd']:>7.1f} {r['sh']:>6.2f} {r['wr']:>6.1f} {r['nt']:>5} {r['pd']:>5} HK$ {r['tv']:>10,.0f}")

# 最优对比
print(f"\n{'='*70}")
print("最优组合对比")
print(f"{'='*70}")
final_tests = [
    ("当前默认", 5, 0.5, True, 25),
    ("HN=3/无恐慌", 3, 0.5, False, 25),
    ("Thr=0.7/无恐慌", 5, 0.7, False, 25),
    ("Thr=0.7+恐慌", 5, 0.7, True, 25),
    ("HN=3/Thr=0.7+恐慌", 3, 0.7, True, 25),
    ("Thr=0.8/无恐慌", 5, 0.8, False, 25),
]
print(f"{'配置':<25} {'累计%':>8} {'回撤%':>7} {'夏普':>5} {'恐慌':>5}")
for label, hn, thr, panic, lb in final_tests:
    r = run(all_data, trade_dates, hn, thr, panic, lb)
    print(f"{label:<25} {r['tr']:>+7.1f} {-r['mdd']:>7.1f} {r['sh']:>5.2f} {r['pd']:>5}")

print("\n完成!")
