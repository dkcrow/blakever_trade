#!/usr/bin/env python3
"""七星QMT 成分股MA10恐慌期空仓 开关对比回测 (1年 + 3年)
唯一变量 = enable_panic_regime (其余QMT参数/池/费率完全一致)。
恐慌期: 调仓日统计成分股池跌破MA10比例 > 80% → 清仓空仓防守。
"""
import sys, copy
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# import 触发 qmt_backtest 顶层 monkey-patch (ETF_POOL→QMT 50只池)
from backtest.qmt_backtest import QMT_POOL, QMT_PARAMS
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

DATA_DIR = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
CASH = 1000000

def run_one(start, end, panic):
    params = copy.deepcopy(QMT_PARAMS)
    params['enable_panic_regime'] = panic
    params['panic_ma_lookback'] = 10
    params['panic_threshold'] = 0.80
    ds = LocalDataSource(DATA_DIR)
    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = 0.0002
    r = engine.run(start, end, CASH)
    n = r.get('trading_days', 0); fv = r.get('final_value', CASH)
    cagr = (fv / CASH) ** (252.0 / n) - 1 if n > 0 else 0
    return dict(tr=(fv/CASH-1)*100, cagr=cagr*100, dd=r.get('max_drawdown_pct', 0),
                sh=r.get('sharpe_ratio', 0), nt=r.get('total_trades', 0),
                wr=r.get('win_rate_pct', 0), panic=r.get('panic_days', 0),
                days=n, fv=fv)

PERIODS = [('1年', '2025-06-21', '2026-06-21'),
           ('3年', '2023-06-21', '2026-06-21')]

rows = []
for label, s, e in PERIODS:
    print(f"\n########## {label} 回测: 关闭恐慌期 ##########")
    off = run_one(s, e, False)
    print(f"\n########## {label} 回测: 开启恐慌期(>80%跌破MA10空仓) ##########")
    on = run_one(s, e, True)
    rows.append((label, off, on))

def fmt(d):
    return (f"累计{d['tr']:+.1f}% 年化{d['cagr']:.1f}% 回撤{d['dd']:.1f}% "
            f"夏普{d['sh']:.2f} 交易{d['nt']} 胜率{d['wr']:.0f}%")

print("\n" + "="*96)
print("  七星QMT 恐慌期空仓 开关对比 (持仓1只, 唯一变量=enable_panic_regime)")
print("="*96)
for label, off, on in rows:
    print(f"\n【{label}】({off['days']}交易日)")
    print(f"  关闭: {fmt(off)}")
    print(f"  开启: {fmt(on)}   [恐慌空仓 {on['panic']} 天]")
    print(f"  差异: 累计{on['tr']-off['tr']:+.1f}pp | 年化{on['cagr']-off['cagr']:+.1f}pp | "
          f"回撤{on['dd']-off['dd']:+.1f}pp | 夏普{on['sh']-off['sh']:+.2f}")
print("="*96)
