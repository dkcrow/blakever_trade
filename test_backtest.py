#!/usr/bin/env python3
"""快速回测诊断脚本"""
import sys
sys.path.insert(0, '.')
from strategies.etf.seven_star_laplacian import BacktestEngine, LocalDataSource

ds = LocalDataSource('data/storage/stock_data/etf')

# 测试A: 关闭盈利保护
print('='*60)
print('测试A: 关闭盈利保护 (2020-2025)')
print('='*60)
engine_a = BacktestEngine(ds, {'enable_profit_protection': False})
rA = engine_a.run('2020-01-01', '2025-12-31', 1000000)
print(f'  收益率: {rA["total_return_pct"]:+.2f}% | 最大回撤: {rA["max_drawdown_pct"]:.1f}% | 夏普: {rA["sharpe_ratio"]:.4f} | 交易数: {rA["total_trades"]}')

# 测试B: 开启盈利保护
print()
print('='*60)
print('测试B: 开启盈利保护 (2020-2025)')
print('='*60)
engine_b = BacktestEngine(ds, {'enable_profit_protection': True})
rB = engine_b.run('2020-01-01', '2025-12-31', 1000000)
print(f'  收益率: {rB["total_return_pct"]:+.2f}% | 最大回撤: {rB["max_drawdown_pct"]:.1f}% | 夏普: {rB["sharpe_ratio"]:.4f} | 交易数: {rB["total_trades"]}')

# 测试C: 短区间 2023-2025
print()
print('='*60)
print('测试C: 全功能 (2023-2025)')
print('='*60)
engine_c = BacktestEngine(ds, {})
rC = engine_c.run('2023-01-01', '2025-12-31', 1000000)
print(f'  收益率: {rC["total_return_pct"]:+.2f}% | 回撤: {rC["max_drawdown_pct"]:.1f}% | 夏普: {rC["sharpe_ratio"]:.4f} | 胜率: {rC["win_rate_pct"]:.1f}%')

# 测试D: 2024-2025
print()
print('='*60)
print('测试D: 全功能 (2024-2025)')
print('='*60)
engine_d = BacktestEngine(ds, {})
rD = engine_d.run('2024-01-01', '2025-12-31', 1000000)
print(f'  收益率: {rD["total_return_pct"]:+.2f}% | 回撤: {rD["max_drawdown_pct"]:.1f}% | 夏普: {rD["sharpe_ratio"]:.4f}')
