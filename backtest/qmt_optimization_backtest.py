#!/usr/bin/env python3
"""
七星QMT策略优化回测：应用审计建议1和3
- 建议1: 精简参数 (关闭冗余过滤器)
- 建议3: 移除成交量过滤

基础设施: QMT ETF池 (51只), 七星172引擎
回测区间: 2025-01-02 ~ 2026-05-30
初始资金: ¥10,000
"""
import sys, warnings, json, io
warnings.filterwarnings('ignore')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
# Fix Windows GBK encoding issue
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from strategies.etf import seven_star_base
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

# QMT 51-ETF pool
qmt_codes_raw = [
    # 海外
    '513100','513290','513500','159529','513400','513520','513030','513080',
    '513310','513730','159792','513130','513050','159920','513690',
    # 商品
    '518880','159980','159985','501018','161226','159981','512400',
    # A股指数
    '510300','510500','510050','510210','159915','588080','512100','563360','563300',
    # 风格
    '512890','159967','588020','512040','159201',
    # 债券
    '511380','511010','511220',
    # 行业板块 (QMT新增)
    '515790','563230','515880','512660','561380','159667','159559','159819',
    '159381','159732','159995','512220',
]
qmt_formatted = ['sh' + c if c.startswith('5') else 'sz' + c for c in qmt_codes_raw]

def monkeypatch_pool(pool):
    """同时更新 base 和 172 模块的 ETF_POOL"""
    seven_star_base.ETF_POOL = pool[:]
    import strategies.etf.seven_star_172 as s172
    s172.ETF_POOL = pool[:]

# ================================================================
# 场景1: 基准 (QMT参数，所有过滤器开启)
# ================================================================
print('=' * 80)
print('  场景0: 基准 (QMT池 + 全部过滤器开启)')
print('=' * 80)
monkeypatch_pool(qmt_formatted)
params_baseline = {
    'lookback_days': 25, 'holdings_num': 1,
    'enable_profit_protection': True,
    'enable_volume_check': True,
    'use_short_momentum_filter': True,
    'enable_premium_filter': True,
}
ds0 = LocalDataSource()
e0 = BacktestEngine172(ds0, engine_params=params_baseline)
e0.commission_rate = 0.0002
r_baseline = e0.run('2025-01-02', '2026-05-30', 10000)

# ================================================================
# 场景1: 建议1 - 精简参数 (关闭盈利保护/成交量/短期动量，仅保留溢价率)
# ================================================================
print('\n' + '=' * 80)
print('  场景1: 精简参数 (关闭盈利保护/成交量/短期动量，仅溢价率)')
print('=' * 80)
monkeypatch_pool(qmt_formatted)
params_simple = {
    'lookback_days': 25, 'holdings_num': 1,
    'enable_profit_protection': False,    # 关闭
    'enable_volume_check': False,         # 关闭
    'use_short_momentum_filter': False,   # 关闭
    'enable_premium_filter': True,        # 保留
}
ds1 = LocalDataSource()
e1 = BacktestEngine172(ds1, engine_params=params_simple)
e1.commission_rate = 0.0002
r_simple = e1.run('2025-01-02', '2026-05-30', 10000)

# ================================================================
# 场景2: 建议3 - 仅移除成交量过滤
# ================================================================
print('\n' + '=' * 80)
print('  场景2: 仅移除成交量过滤 (其余过滤器全开)')
print('=' * 80)
monkeypatch_pool(qmt_formatted)
params_no_volume = {
    'lookback_days': 25, 'holdings_num': 1,
    'enable_profit_protection': True,      # 保留
    'enable_volume_check': False,          # 关闭
    'use_short_momentum_filter': True,     # 保留
    'enable_premium_filter': True,         # 保留
}
ds2 = LocalDataSource()
e2 = BacktestEngine172(ds2, engine_params=params_no_volume)
e2.commission_rate = 0.0002
r_novol = e2.run('2025-01-02', '2026-05-30', 10000)

# ================================================================
# 对比报告
# ================================================================
results = {
    '基准(QMT全开)': r_baseline,
    '①精简参数': r_simple,
    '③移除成交量': r_novol,
}

metrics = [
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

print('\n')
print('=' * 110)
header = f'  {"指标":20s}'
for name in results:
    header += f' | {name:>18s}'
print(header)
print('=' * 110)

for m_name, getter, fmt, higher_better in metrics:
    row = f'  {m_name:20s}'
    values = []
    for r_name, r in results.items():
        v = getter(r)
        values.append(v)
        if fmt == 'd':
            row += f' | {int(v):>18d}'
        elif fmt.endswith('%'):
            row += f' | {v:>17.2f}%'
        else:
            row += f' | {v:>18.4f}'
    print(row)

print('=' * 110)

# 与基准的差异
print()
print('=' * 110)
print(f'  {"指标":20s} | {"①精简 vs 基准":>20s} | {"③移除成交量 vs 基准":>22s}')
print('=' * 110)

for m_name, getter, fmt, higher_better in metrics:
    v_base = getter(r_baseline)
    v_simple = getter(r_simple)
    v_novol = getter(r_novol)

    d1 = v_simple - v_base
    d2 = v_novol - v_base

    if fmt == 'd':
        s1 = f'{int(d1):+d}'
        s2 = f'{int(d2):+d}'
    elif fmt.endswith('%'):
        s1 = f'{d1:+.2f}%'
        s2 = f'{d2:+.2f}%'
    else:
        s1 = f'{d1:+.4f}'
        s2 = f'{d2:+.4f}'

    # Determine marker
    if higher_better:
        m1 = '✅' if d1 > 0 else ('➖' if d1 == 0 else '❌')
        m2 = '✅' if d2 > 0 else ('➖' if d2 == 0 else '❌')
    else:
        m1 = '✅' if d1 < 0 else ('➖' if d1 == 0 else '❌')
        m2 = '✅' if d2 < 0 else ('➖' if d2 == 0 else '❌')

    print(f'  {m_name:20s} | {m1} {s1:>17s} | {m2} {s2:>19s}')

print('=' * 110)

# 汇总
print('\n📊 汇总:')
for label, r_data in [('①精简参数', r_simple), ('③移除成交量', r_novol)]:
    better = 0
    worse = 0
    for m_name, getter, fmt, higher_better in metrics:
        v_base = getter(r_baseline)
        v_opt = getter(r_data)
        diff = v_opt - v_base
        if diff == 0:
            continue
        if higher_better:
            if diff > 0: better += 1
            else: worse += 1
        else:
            if diff < 0: better += 1
            else: worse += 1
    print(f'  {label}: {better}项改善 / {worse}项变差 / {12-better-worse}项持平')

print()
