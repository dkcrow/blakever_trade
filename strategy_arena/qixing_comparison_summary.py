#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星策略对比总结
基于已完成的回测结果
"""

print("="*80)
print("七星策略大对比 — 4个策略")
print("="*80)

# 七星三马V7 (美股个股，10年回测)
sanma_v7 = {
    'name': '七星三马V7 (美股个股)',
    'annual_return': 30.13,
    'total_return': 1291.24,
    'sharpe': 0.89,
    'win_rate': 43.5,
    'pl_ratio': 2.21,
    'max_drawdown': 29.72,
    'trades_per_year': 71,
    'backtest_years': 10,
    'assets': '15只美股个股',
}

# 七星拉普拉斯高斯 (A股ETF，1.2年回测)
laplace = {
    'name': '七星拉普拉斯高斯 (A股ETF)',
    'annual_return': 32.56,
    'total_return': 181.43,
    'sharpe': 0.31,
    'win_rate': None,
    'pl_ratio': None,
    'max_drawdown': None,
    'trades_per_year': None,
    'backtest_years': 1.2,
    'assets': '36只A股ETF',
}

# 七星高照6+1 (只找到每日模拟，无完整回测)
qixing_6plus1 = {
    'name': '七星高照6+1 (A股ETF)',
    'annual_return': None,  # 文档说5年20.02%
    'total_return': None,
    'sharpe': None,  # 文档说5年夏普1.07
    'win_rate': None,
    'pl_ratio': None,
    'max_drawdown': None,  # 文档说5年最大回撤-17.34%
    'trades_per_year': None,
    'backtest_years': None,
    'assets': '7只A股ETF (6+1)',
    'note': '文档数据: 5年年化20.02%, 夏普1.07, 最大回撤-17.34%'
}

print("\n策略对比表:")
print("-"*80)
print(f"{'策略':<35} {'年化%':>8} {'夏普':>6} {'胜率%':>7} {'盈亏比':>7} {'回撤%':>8} {'年限':>6}")
print("-"*80)

for s in [sanma_v7, laplace, qixing_6plus1]:
    name = s['name'][:33]
    ann = f"{s['annual_return']:.2f}" if s['annual_return'] else 'N/A'
    sharpe = f"{s['sharpe']:.2f}" if s['sharpe'] else 'N/A'
    wr = f"{s['win_rate']:.1f}" if s['win_rate'] else 'N/A'
    pl = f"{s['pl_ratio']:.2f}" if s['pl_ratio'] else 'N/A'
    dd = f"{s['max_drawdown']:.2f}" if s['max_drawdown'] else 'N/A'
    yrs = f"{s['backtest_years']:.1f}" if s['backtest_years'] else 'N/A'
    print(f"{name:<35} {ann:>8} {sharpe:>6} {wr:>7} {pl:>7} {dd:>8} {yrs:>6}")

print("\n" + "="*80)
print("结论:")
print("="*80)
print("✅ 年化≥30%: 三马V7(30.13%)✅ 拉普拉斯(32.56%)✅")
print("✅ 夏普>1: 三马V7(0.89)❌ 拉普拉斯(0.31)❌")
print("✅ 胜率≥40%: 三马V7(43.5%)✅ 拉普拉斯(未知)")
print("❌ 盈亏比≥3: 三马V7(2.21)❌ 拉普拉斯(未知)")
print("❌ 最大回撤<20%: 三马V7(29.72%)❌ 拉普拉斯(未知)")
print("\n最佳策略: 七星三马V7 (10年完整回测，夏普最高0.89)")
print("注意: 拉普拉斯仅1.2年回测，数据不足；6+1无完整回测")
