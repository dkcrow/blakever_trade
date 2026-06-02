#!/usr/bin/env python3
"""七星QMT原版 vs 无过滤版 回测对比 (2024-01-02 ~ 2026-05-29)"""
import sys, warnings, io
warnings.filterwarnings('ignore')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from strategies.etf import seven_star_base
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

# QMT 51-ETF pool
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

def monkeypatch_pool(pool):
    seven_star_base.ETF_POOL = pool[:]
    import strategies.etf.seven_star_172 as s172
    s172.ETF_POOL = pool[:]

START, END, CASH = '2024-01-02', '2026-05-29', 10000

# ================================================================
# 场景1: 原版 (全部过滤器开启)
# ================================================================
print('=' * 70)
print('  场景1: 七星QMT原版 (全部过滤器开启)')
print(f'  区间: {START} ~ {END}')
print('=' * 70)
monkeypatch_pool(qmt_formatted)
params_orig = {
    'lookback_days': 25, 'holdings_num': 1,
    'enable_profit_protection': True,
    'enable_volume_check': True,
    'use_short_momentum_filter': True,
    'enable_premium_filter': True,
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
}
ds1 = LocalDataSource()
e1 = BacktestEngine172(ds1, engine_params=params_orig)
e1.commission_rate = 0.0002
r_orig = e1.run(START, END, CASH)

# ================================================================
# 场景2: 无过滤版
# ================================================================
print('\n' + '=' * 70)
print('  场景2: 七星QMT无过滤版 + 行情判断 + 日内回撤')
print(f'  区间: {START} ~ {END}')
print('=' * 70)
monkeypatch_pool(qmt_formatted)
params_nofilter = {
    'lookback_days': 25, 'holdings_num': 1,
    'enable_profit_protection': False,
    'enable_volume_check': False,
    'use_short_momentum_filter': False,
    'enable_premium_filter': True,
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
}
ds2 = LocalDataSource()
e2 = BacktestEngine172(ds2, engine_params=params_nofilter)
e2.commission_rate = 0.0002
r_nofilter = e2.run(START, END, CASH)

# ================================================================
# 对比报告
# ================================================================
results = {'原版(全过滤)': r_orig, '无过滤版': r_nofilter}

metrics = [
    ('年化收益率',    lambda r: r['annualized_return_pct'], '.2f%', True),
    ('总收益率',      lambda r: r['total_return_pct'],      '.2f%', True),
    ('最大回撤',      lambda r: r['max_drawdown_pct'],      '.2f%', False),
    ('夏普比率',      lambda r: r['sharpe_ratio'],           '.4f', True),
    ('卡尔马比率',    lambda r: r['calmar_ratio'],           '.4f', True),
    ('总交易次数',    lambda r: r['total_trades'],            'd',   False),
    ('买入次数',      lambda r: r['buy_trades'],              'd',   False),
    ('卖出次数',      lambda r: r['sell_trades'],             'd',   False),
    ('胜率',          lambda r: r['win_rate_pct'],           '.2f%', True),
    ('平均盈利',      lambda r: r['avg_win_pct'],            '.2f%', True),
    ('平均亏损',      lambda r: r['avg_loss_pct'],           '.2f%', False),
    ('最终资产',      lambda r: r['final_value'],             '.2f', True),
]

print('\n')
print('=' * 90)
print(f'  {"指标":18s} | {"原版(全过滤)":>16s} | {"无过滤版":>16s} | {"差异":>12s}')
print('=' * 90)

wins = {'无过滤版': 0, '原版(全过滤)': 0}
for m_name, getter, fmt, higher_better in metrics:
    v1 = getter(r_orig)
    v2 = getter(r_nofilter)
    diff = v2 - v1

    if fmt == 'd':
        s1, s2 = str(int(v1)), str(int(v2))
        s_diff = f'{int(diff):+d}'
    elif fmt.endswith('%'):
        s1, s2 = f'{v1:.2f}%', f'{v2:.2f}%'
        s_diff = f'{diff:+.2f}%'
    else:
        s1, s2 = f'{v1:.4f}', f'{v2:.4f}'
        s_diff = f'{diff:+.4f}'

    # 获胜方标记
    if diff == 0:
        marker = '  '
    elif higher_better:
        marker = '✅' if diff > 0 else '❌'
        if diff > 0: wins['无过滤版'] += 1
        else: wins['原版(全过滤)'] += 1
    else:
        marker = '✅' if diff < 0 else '❌'
        if diff < 0: wins['无过滤版'] += 1
        else: wins['原版(全过滤)'] += 1

    print(f'  {m_name:18s} | {s1:>16s} | {s2:>16s} | {marker} {s_diff:>9s}')

print('=' * 90)
print(f'\n📊 无过滤版 {wins["无过滤版"]}项胜出 / 原版 {wins["原版(全过滤)"]}项胜出 (共{len(metrics)}项)')
print()
