#!/usr/bin/env python3
"""
七星QMT vs 七星172 全面回测对比
日期: 2025-01-01 ~ 2026-06-02
"""
import sys, os, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

from strategies.etf.seven_star_base import ETF_POOL, ETF_NAMES, LocalDataSource
from strategies.etf.seven_star_172 import BacktestEngine172, DEFAULT_PARAMS

# ============================================================
# QMT池 (51只, 比172多11只行业/风格ETF)
# ============================================================
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

# ============================================================
# 基础参数模板 (包含所有必需字段)
# ============================================================
_base_params = {
    'lookback_days': 25, 'holdings_num': 1, 'min_money': 5000,
    'profit_protection_lookback': 1, 'profit_protection_threshold': 0.05,
    'profit_protection_check_times': ['11:00'],
    'loss': 0.01, 'min_score_threshold': -999999, 'max_score_threshold': 999999,
    'volume_lookback': 5, 'volume_threshold': 2, 'volume_return_limit': 1,
    'short_lookback_days': 10, 'short_momentum_threshold': 0.0,
    'premium_threshold': 0.20,
    'weak_period_ma_lookback': 10, 'weak_period_max_days': 20,
}

# ============================================================
# 七星172 默认参数 (当前最优配置)
# ============================================================
params_172 = {**_base_params,
    'enable_profit_protection': True,
    'enable_volume_check': False,          # 永久关闭
    'use_short_momentum_filter': False,    # 永久关闭
    'enable_premium_filter': True,
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
    'intraday_drawdown_threshold': 0.02,
}

# ============================================================
# 七星QMT 原始参数 (V3原版, 全过滤开启)
# ============================================================
params_qmt = {**_base_params,
    'enable_profit_protection': True,
    'enable_volume_check': True,           # QMT原版开启
    'use_short_momentum_filter': True,     # QMT原版开启
    'enable_premium_filter': True,
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
    'intraday_drawdown_threshold': 0.02,
}

START, END = '2025-01-01', '2026-06-02'

# ============================================================
# 回测函数
# ============================================================
def run_172(data_source_cls, etf_pool, params, commission, label):
    """运行七星172引擎回测"""
    import strategies.etf.seven_star_base as base_mod
    import strategies.etf.seven_star_172 as s172_mod

    # 临时切换ETF池
    original_pool = base_mod.ETF_POOL[:]
    base_mod.ETF_POOL = etf_pool
    s172_mod.ETF_POOL = etf_pool

    try:
        ds = data_source_cls()
        e = BacktestEngine172(ds, engine_params=params)
        e.commission_rate = commission
        print(f'\n{"="*70}')
        print(f'  {label}')
        print(f'  ETF池: {len(etf_pool)}只 | 佣金: {commission*100:.3f}%')
        filter_status = []
        if params.get('enable_profit_protection'): filter_status.append('盈利保护')
        if params.get('enable_volume_check'): filter_status.append('成交量')
        if params.get('use_short_momentum_filter'): filter_status.append('短期动量')
        if params.get('enable_premium_filter'): filter_status.append('溢价率')
        print(f'  过滤器: {", ".join(filter_status) if filter_status else "无"}')
        print('='*70)
        r = e.run(START, END, 10000)
    finally:
        base_mod.ETF_POOL = original_pool
        s172_mod.ETF_POOL = original_pool

    return r


# ============================================================
# 执行
# ============================================================
results = {}

# 七星172
results['172'] = run_172(
    LocalDataSource, ETF_POOL[:], params_172, 0.0002,
    '七星172策略 (40 ETF Pool · 精简过滤 · 0.02%佣金)'
)

# 七星QMT (佣金统一0.02%)
results['qmt'] = run_172(
    LocalDataSource, qmt_formatted, params_qmt, 0.0002,
    '七星QMT策略 (51 ETF Pool · 全过滤 · 0.02%佣金)'
)

# ============================================================
# 对比报告
# ============================================================
if not results['172'] or not results['qmt']:
    print('\n[FATAL] 回测失败!')
    sys.exit(1)

r172 = results['172']
rqmt = results['qmt']

metrics_def = [
    ('ETF池数量',  (lambda: 40, lambda: 51), 'd', False),
    ('年化收益率(%)',   (lambda: r172['annualized_return_pct'], lambda: rqmt['annualized_return_pct']), '.2f', True),
    ('总收益率(%)',     (lambda: r172['total_return_pct'], lambda: rqmt['total_return_pct']), '.2f', True),
    ('最大回撤(%)',     (lambda: r172['max_drawdown_pct'], lambda: rqmt['max_drawdown_pct']), '.2f', False),
    ('夏普比率',        (lambda: r172['sharpe_ratio'], lambda: rqmt['sharpe_ratio']), '.4f', True),
    ('卡尔马比率',      (lambda: r172['calmar_ratio'], lambda: rqmt['calmar_ratio']), '.4f', True),
    ('总交易次数',      (lambda: r172['total_trades'], lambda: rqmt['total_trades']), 'd', False),
    ('买入次数',        (lambda: r172['buy_trades'], lambda: rqmt['buy_trades']), 'd', False),
    ('卖出次数',        (lambda: r172['sell_trades'], lambda: rqmt['sell_trades']), 'd', False),
    ('胜率(%)',         (lambda: r172['win_rate_pct'], lambda: rqmt['win_rate_pct']), '.2f', True),
    ('平均盈利(%)',     (lambda: r172['avg_win_pct'], lambda: rqmt['avg_win_pct']), '.2f', True),
    ('平均亏损(%)',     (lambda: r172['avg_loss_pct'], lambda: rqmt['avg_loss_pct']), '.2f', False),
    ('最终资产(元)',    (lambda: r172['final_value'], lambda: rqmt['final_value']), '.2f', True),
]

print('\n')
print('=' * 100)
print(f'  {"指标":22s} | {"七星172 (40池)":>16s} | {"七星QMT (51池)":>16s} | {"差异":>14s} | 优劣')
print('=' * 100)

better = 0; worse = 0

for name, (get172, get_qmt), fmt, higher_better in metrics_def:
    v172 = get172()
    v_qmt = get_qmt()

    if fmt == 'd':
        s172 = str(int(v172)); s_qmt = str(int(v_qmt))
        diff = v_qmt - v172; s_diff = f'{diff:+d}'
    elif fmt.startswith('.'):
        s172 = f'{v172:{fmt}}'; s_qmt = f'{v_qmt:{fmt}}'
        diff = v_qmt - v172; s_diff = f'{diff:{fmt}}'
    else:
        s172 = f'{v172:{fmt}}'; s_qmt = f'{v_qmt:{fmt}}'
        diff = v_qmt - v172; s_diff = f'{diff:{fmt}}'

    if name == 'ETF池数量':
        marker = ' '
    elif diff == 0:
        marker = ' '
    elif (higher_better and diff > 0) or (not higher_better and diff < 0):
        marker = 'QMT✓' if diff > 0 else '172✓'
        if higher_better and diff > 0: better += 1
        elif not higher_better and diff < 0: better += 1
        else: worse += 1
    else:
        marker = '172✓' if diff < 0 else 'QMT✓'
        if higher_better and diff < 0: worse += 1
        elif not higher_better and diff > 0: worse += 1
        else: better += 1

    print(f'  {name:22s} | {s172:>16s} | {s_qmt:>16s} | {s_diff:>14s} | {marker}')

print('=' * 100)
print(f'\n结论: 七星QMT {better}项领先 / 七星172 {worse}项领先')

# ============================================================
# 日净值序列对比摘要 (用于可视化)
# ============================================================
dv172 = r172.get('daily_values', [])
dv_qmt = rqmt.get('daily_values', [])

# 保存对比结果JSON
result_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(result_dir, exist_ok=True)

comparison = {
    'period': f'{START} ~ {END}',
    '172': {
        'pool_size': 40,
        'commission': 0.0002,
        'filters': [k for k, v in params_172.items() if v is True and k.startswith('enable') or k.startswith('use')],
        'metrics': {k: v for k, v in r172.items() if not isinstance(v, (list, dict))},
        'daily_values': dv172,
        'trade_log': r172.get('trade_log', []),
    },
    'qmt': {
        'pool_size': 51,
        'commission': 0.0002,
        'filters': [k for k, v in params_qmt.items() if v is True and k.startswith('enable') or k.startswith('use')],
        'metrics': {k: v for k, v in rqmt.items() if not isinstance(v, (list, dict))},
        'daily_values': dv_qmt,
        'trade_log': rqmt.get('trade_log', []),
    },
}

out_path = os.path.join(result_dir, 'qmt_vs_172_comparison.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(comparison, f, ensure_ascii=False, indent=2, default=str)
print(f'\n对比结果已保存: {out_path}')
