#!/usr/bin/env python3
"""七星QMT vs 七星172 回测对比"""
import sys, warnings, json
warnings.filterwarnings('ignore')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

from strategies.etf import seven_star_base
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

# QMT pool
qmt_codes_raw = [
    '513100','513290','513500','159529','513400','513520','513030','513080',
    '513310','513730','159792','513130','513050','159920','513690',
    '518880','159980','159985','501018','161226','159981','512400',
    '510300','510500','510050','510210','159915','588080','512100','563360','563300',
    '512890','159967','588020','512040','159201',
    '511380','511010','511220',
    '515790','563230','515880','512660','561380','159667','159559','159819',
    '159381','159732','159995','512220',
]
qmt_formatted = ['sh' + c if c.startswith('5') else 'sz' + c for c in qmt_codes_raw]

original_pool = seven_star_base.ETF_POOL[:]

params = {
    'lookback_days': 25, 'holdings_num': 1,
    'enable_profit_protection': True, 'enable_volume_check': True,
    'use_short_momentum_filter': True, 'enable_premium_filter': True,
}

# Run 172 baseline
print('=== Running 七星172 baseline (40 ETFs) ===')
ds = LocalDataSource()
e = BacktestEngine172(ds, engine_params=params)
e.commission_rate = 0.0002
r172 = e.run('2025-01-02', '2026-05-30', 10000)

# Run with QMT pool
print('\n=== Running 七星172 with QMT pool (51 ETFs) ===')
seven_star_base.ETF_POOL = qmt_formatted
import strategies.etf.seven_star_172 as s172_mod
s172_mod.ETF_POOL = qmt_formatted
ds2 = LocalDataSource()
e2 = BacktestEngine172(ds2, engine_params=params)
e2.commission_rate = 0.0002
r_qmt = e2.run('2025-01-02', '2026-05-30', 10000)

# Also update the import in seven_star_172 module
import strategies.etf.seven_star_172 as s172
s172.ETF_POOL = original_pool
seven_star_base.ETF_POOL = original_pool

# === Report ===
metrics = [
    ('ETF数量', lambda r: len(original_pool) if r is r172 else len(qmt_formatted), 'd', False),
    ('年化收益率', lambda r: r['annualized_return_pct'], '.2f%', True),
    ('总收益率', lambda r: r['total_return_pct'], '.2f%', True),
    ('最大回撤', lambda r: r['max_drawdown_pct'], '.2f%', False),
    ('夏普比率', lambda r: r['sharpe_ratio'], '.4f', True),
    ('卡尔马比率', lambda r: r['calmar_ratio'], '.4f', True),
    ('总交易次数', lambda r: r['total_trades'], 'd', False),
    ('买入次数', lambda r: r['buy_trades'], 'd', False),
    ('卖出次数', lambda r: r['sell_trades'], 'd', False),
    ('胜率', lambda r: r['win_rate_pct'], '.2f%', True),
    ('平均盈利', lambda r: r['avg_win_pct'], '.2f%', True),
    ('平均亏损', lambda r: r['avg_loss_pct'], '.2f%', False),
    ('最终资产', lambda r: r['final_value'], '.2f', True),
]

print('\n' + '=' * 90)
print(f'  {"指标":20s} | {"七星172 (40只)":>16s} | {"QMT池 (51只)":>16s} | {"差异":>12s} |')
print('=' * 90)

for name, getter, fmt, higher_better in metrics:
    v172 = getter(r172)
    v_qmt = getter(r_qmt)
    if fmt == 'd':
        s172 = str(int(v172))
        s_qmt = str(int(v_qmt))
        diff = v_qmt - v172
        s_diff = f'{diff:+d}'
    elif fmt.endswith('%'):
        s172 = f'{v172:.2f}%'
        s_qmt = f'{v_qmt:.2f}%'
        diff = v_qmt - v172
        s_diff = f'{diff:+.2f}%'
    elif fmt == '.2f':
        s172 = f'{v172:.2f}'
        s_qmt = f'{v_qmt:.2f}'
        diff = v_qmt - v172
        s_diff = f'{diff:+.2f}'
    else:
        s172 = f'{v172:{fmt}}'
        s_qmt = f'{v_qmt:{fmt}}'
        diff = v_qmt - v172
        s_diff = f'{diff:{fmt}}'

    # Color diff
    if (higher_better and diff > 0) or (not higher_better and diff < 0):
        marker = '+'
    elif diff == 0:
        marker = ' '
    else:
        marker = '-'
    print(f'  {name:20s} | {s172:>16s} | {s_qmt:>16s} | {marker} {s_diff:>10s} |')

print('=' * 90)

# Count how many better
better = 0
worse = 0
for name, getter, fmt, higher_better in metrics:
    if name == 'ETF数量': continue
    v172 = getter(r172)
    v_qmt = getter(r_qmt)
    diff = v_qmt - v172
    if higher_better:
        if diff > 0: better += 1
        elif diff < 0: worse += 1
    else:
        if diff < 0: better += 1
        elif diff > 0: worse += 1

print(f'\n结论: QMT池 {better}项改善 / {worse}项变差 / {12-better-worse}项持平')
