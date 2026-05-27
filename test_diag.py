#!/usr/bin/env python3
import sys, os, io, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies.etf.seven_star_laplacian import BacktestEngine, LocalDataSource

ds = LocalDataSource('data/storage/stock_data/etf')

tests = [
    ('A:关盈利保护(20-25)', {'enable_profit_protection': False}, '2020-01-01', '2025-12-31'),
    ('B:开盈利保护(20-25)', {'enable_profit_protection': True},  '2020-01-01', '2025-12-31'),
    ('C:全功能(23-25)',    {},                                   '2023-01-01', '2025-12-31'),
    ('D:全功能(24-25)',    {},                                   '2024-01-01', '2025-12-31'),
]

for label, params, start, end in tests:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with contextlib.redirect_stderr(buf):
            engine = BacktestEngine(ds, params)
            r = engine.run(start, end, 1000000)
    print('%s | 收益=%+.2f%% | 回撤=%.1f%% | 夏普=%.4f | 交易=%d | 胜率=%.1f%%' % (
        label, r['total_return_pct'], r['max_drawdown_pct'],
        r['sharpe_ratio'], r['total_trades'], r['win_rate_pct']
    ))
