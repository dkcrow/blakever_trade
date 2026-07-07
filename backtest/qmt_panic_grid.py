#!/usr/bin/env python3
"""七星QMT 恐慌期空仓 参数网格对比 (跌破比例 × MA周期)
组合: 关闭 / 60%·5日 / 80%·5日 / 60%·10日 / 80%·10日(基线) / 80%·20日 / 60%·20日
唯一变量 = enable_panic_regime + panic_threshold + panic_ma_lookback, 其余QMT参数/池/费率一致。
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

def run_one(start, end, enable, thr, lb):
    params = copy.deepcopy(QMT_PARAMS)
    params['enable_panic_regime'] = enable
    if enable:
        params['panic_threshold'] = thr
        params['panic_ma_lookback'] = lb
    ds = LocalDataSource(DATA_DIR)
    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = 0.0002
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = engine.run(start, end, CASH)
    n = r.get('trading_days', 0); fv = r.get('final_value', CASH)
    cagr = (fv / CASH) ** (252.0 / n) - 1 if n > 0 else 0
    return dict(tr=(fv/CASH-1)*100, cagr=cagr*100, dd=r.get('max_drawdown_pct', 0),
                sh=r.get('sharpe_ratio', 0), nt=r.get('total_trades', 0),
                wr=r.get('win_rate_pct', 0), panic=r.get('panic_days', 0), days=n)

CONFIGS = [
    ('关闭(基线)',  False, None, None),
    ('60%·5日',    True, 0.60, 5),
    ('80%·5日',    True, 0.80, 5),
    ('60%·10日',   True, 0.60, 10),
    ('80%·10日',   True, 0.80, 10),
    ('80%·20日',   True, 0.80, 20),
    ('60%·20日',   True, 0.60, 20),
]
PERIODS = [('1年', '2025-06-21', '2026-06-21'),
           ('3年', '2023-06-21', '2026-06-21')]

for label, s, e in PERIODS:
    print(f"\n{'='*104}")
    print(f"  七星QMT 恐慌期空仓参数网格 — {label} ({s} ~ {e})  [持仓1只, 唯一变量=恐慌参数]")
    print('='*104)
    print(f"  {'配置':<12}{'累计':>10}{'年化':>9}{'回撤':>9}{'夏普':>7}{'交易':>6}{'胜率':>6}{'空仓天':>7}   {'vs关闭':<22}")
    print('-'*104)
    base = None
    for name, en, thr, lb in CONFIGS:
        r = run_one(s, e, en, thr, lb)
        if base is None: base = r
        diff = '' if r is base else f"累计{r['tr']-base['tr']:+.0f}pp 回撤{r['dd']-base['dd']:+.1f}pp 夏普{r['sh']-base['sh']:+.2f}"
        print(f"  {name:<12}{r['tr']:>+9.1f}%{r['cagr']:>8.1f}%{r['dd']:>8.1f}%{r['sh']:>7.2f}"
              f"{r['nt']:>6}{r['wr']:>5.0f}%{r['panic']:>7}   {diff:<22}")
    print('='*104)
print("\n完成。")
