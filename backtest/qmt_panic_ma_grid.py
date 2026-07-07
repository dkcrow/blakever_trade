#!/usr/bin/env python3
"""七星QMT 恐慌期空仓 — 固定80%阈值, MA周期寻优 (15/20基准/25/200/250)
统计每个配置: 触发次数(连续段数) / 总空仓天数 / 平均段长 / 最长段。
唯一变量 = panic_ma_lookback, 其余QMT参数/池/费率一致。
"""
import sys, copy, io, contextlib
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.qmt_backtest import QMT_POOL, QMT_PARAMS   # 触发 monkey-patch (50只池)
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

DATA_DIR = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
CASH = 1000000

def seg_stats(idx):
    """连续索引分段: 返回 (触发次数, 总天数, 平均段长, 最长段)"""
    if not idx:
        return 0, 0, 0.0, 0
    idx = sorted(idx)
    segs = []
    start = prev = idx[0]
    for x in idx[1:]:
        if x == prev + 1:
            prev = x
        else:
            segs.append(prev - start + 1)
            start = prev = x
    segs.append(prev - start + 1)
    return len(segs), sum(segs), sum(segs)/len(segs), max(segs)

def run_one(start, end, enable, lb):
    params = copy.deepcopy(QMT_PARAMS)
    params['enable_panic_regime'] = enable
    if enable:
        params['panic_threshold'] = 0.80
        params['panic_ma_lookback'] = lb
    ds = LocalDataSource(DATA_DIR)
    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = 0.0002
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = engine.run(start, end, CASH)
    n = r.get('trading_days', 0); fv = r.get('final_value', CASH)
    cagr = (fv / CASH) ** (252.0 / n) - 1 if n > 0 else 0
    cnt, tot, avg, mx = seg_stats(r.get('panic_idx', []))
    return dict(tr=(fv/CASH-1)*100, cagr=cagr*100, dd=r.get('max_drawdown_pct', 0),
                sh=r.get('sharpe_ratio', 0), nt=r.get('total_trades', 0),
                wr=r.get('win_rate_pct', 0), days=n,
                cnt=cnt, tot=tot, avg=avg, mx=mx)

CONFIGS = [
    ('关闭(基线)', False, None),
    ('80%·15日',  True, 15),
    ('80%·20日(基准)', True, 20),
    ('80%·25日',  True, 25),
    ('80%·200日', True, 200),
    ('80%·250日', True, 250),
]
PERIODS = [('1年', '2025-06-21', '2026-06-21'),
           ('3年', '2023-06-21', '2026-06-21')]

for label, s, e in PERIODS:
    print(f"\n{'='*118}")
    print(f"  七星QMT 恐慌期MA周期寻优 — {label} ({s} ~ {e})  [阈值固定80%, 持仓1只]")
    print('='*118)
    print(f"  {'配置':<16}{'累计':>10}{'年化':>9}{'回撤':>8}{'夏普':>7}{'交易':>6}{'胜率':>6}"
          f"{'触发次数':>9}{'空仓天数':>9}{'平均段长':>9}{'最长段':>8}")
    print('-'*118)
    base = None
    for name, en, lb in CONFIGS:
        r = run_one(s, e, en, lb)
        if base is None: base = r
        print(f"  {name:<16}{r['tr']:>+9.1f}%{r['cagr']:>8.1f}%{r['dd']:>7.1f}%{r['sh']:>7.2f}"
              f"{r['nt']:>6}{r['wr']:>5.0f}%{r['cnt']:>9}{r['tot']:>9}{r['avg']:>9.1f}{r['mx']:>8}")
    print('-'*118)
    print(f"  注: 触发次数=连续恐慌段数; 空仓天数=总恐慌交易日; 平均/最长段=每次空仓持续交易日")
    print('='*118)
print("\n完成。")
