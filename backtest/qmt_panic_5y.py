#!/usr/bin/env python3
"""七星QMT 恐慌期空仓 — 5年回测对比 (80%阈值, MA 15/20/25日 vs 关闭)
标注触发次数(连续段数)/空仓天数/平均段长/最长段。唯一变量=恐慌参数。
"""
import sys, copy, io, contextlib
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.qmt_backtest import QMT_POOL, QMT_PARAMS   # monkey-patch 50只池
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

DATA_DIR = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
CASH = 1000000
START, END = '2021-06-21', '2026-06-21'

def seg_stats(idx):
    if not idx:
        return 0, 0, 0.0, 0
    idx = sorted(idx)
    segs = []; start = prev = idx[0]
    for x in idx[1:]:
        if x == prev + 1:
            prev = x
        else:
            segs.append(prev - start + 1); start = prev = x
    segs.append(prev - start + 1)
    return len(segs), sum(segs), sum(segs)/len(segs), max(segs)

def run_one(enable, lb):
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
        r = engine.run(START, END, CASH)
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
    ('80%·20日',  True, 20),
    ('80%·25日',  True, 25),
]

print(f"七星QMT 5年回测 ({START} ~ {END}) | 阈值固定80% | 持仓1只")
rows = []
for name, en, lb in CONFIGS:
    rows.append((name, run_one(en, lb)))

print(f"\n{'='*120}")
print(f"  七星QMT 恐慌期空仓 5年对比 ({rows[0][1]['days']}交易日)  [唯一变量=恐慌参数]")
print('='*120)
print(f"  {'配置':<14}{'累计':>11}{'年化CAGR':>10}{'回撤':>8}{'夏普':>7}{'交易':>6}{'胜率':>6}"
      f"{'触发次数':>9}{'空仓天数':>9}{'平均段长':>9}{'最长段':>8}   {'vs关闭':<20}")
print('-'*120)
base = rows[0][1]
for name, r in rows:
    diff = '' if r is base else f"累计{r['tr']-base['tr']:+.0f}pp 回撤{r['dd']-base['dd']:+.1f}pp 夏普{r['sh']-base['sh']:+.2f}"
    print(f"  {name:<14}{r['tr']:>+10.1f}%{r['cagr']:>9.1f}%{r['dd']:>7.1f}%{r['sh']:>7.2f}"
          f"{r['nt']:>6}{r['wr']:>5.0f}%{r['cnt']:>9}{r['tot']:>9}{r['avg']:>9.1f}{r['mx']:>8}   {diff:<20}")
print('-'*120)
print("  注: 触发次数=连续恐慌段数; 空仓天数=总恐慌交易日; 平均/最长段=每次空仓持续交易日")
print('='*120)
