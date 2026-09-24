"""七星简化版 vs 七星QMT — 权威引擎对比回测

简化版来源: 克总提供的聚宽策略 (17只ETF池 / 持仓2只 / 20日动量 / 无行情判断 / 防御511880)
权威引擎: BacktestEngine172 (strategies/etf/seven_star_172.py) — 严禁手写简化回测

用法:
    python backtest/simplified_vs_qmt.py --mode simplified --start 2021-06-21 --end 2026-09-17
    python backtest/simplified_vs_qmt.py --mode qmt        --start 2021-06-21 --end 2026-09-17
"""
import sys
import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ================================================================
# 简化版 ETF 池 (与聚宽原版 g.etf_pool_3 逐只对齐)
# ================================================================
SIMPLIFIED_RAW = [
    # ===== 期货 (3) =====
    'sh518880',  # 黄金
    'sz159985',  # 豆粕
    'sz159981',  # 能源化工
    # ===== 跨境 (7) =====
    'sh513100',  # 纳指
    'sh513500',  # 标普
    'sh513520',  # 日经
    'sh513030',  # 德国
    'sz159329',  # 沙特 (本地无数据, 自动跳过)
    'sh513730',  # 东南亚
    'sh513600',  # 恒指 (本地无数据, 自动跳过)
    # ===== 宽基 (4) =====
    'sh588080',  # 科创50
    'sz159949',  # 创业50
    'sh512100',  # 中证1000
    'sh510880',  # 红利
    # ===== 债券 (3) =====
    'sh511010',  # 国债
    'sh511380',  # 可转债
    'sz511220',  # 城投债
]
# 追加防御ETF(银华日利)以便回测中可交易, 与聚宽 g.defensive_etf=511880 对应
SIMPLIFIED_POOL = SIMPLIFIED_RAW + ['sh511880']

SIMPLIFIED_NAMES = {
    'sh518880': '黄金ETF华安', 'sz159985': '豆粕ETF华夏', 'sz159981': '能源化工ETF建信',
    'sh513100': '纳指ETF国泰', 'sh513500': '标普500ETF博时', 'sh513520': '日经ETF华夏',
    'sh513030': '德国ETF华安', 'sz159329': '沙特ETF', 'sh513730': '东南亚科技ETF',
    'sh513600': '恒指ETF',
    'sh588080': '科创50ETF易方达', 'sz159949': '创业50ETF', 'sh512100': '中证1000ETF南方',
    'sh510880': '红利ETF', 'sh511010': '国债ETF国泰', 'sh511380': '可转债ETF博时',
    'sz511220': '城投债ETF海富通', 'sh511880': '银华日利(货币)',
}

# ================================================================
# 简化版参数 (与聚宽原版逐项对齐)
# ================================================================
SIMPLIFIED_PARAMS = {
    'lookback_days': 20,                 # g.lookback_days = 20
    'holdings_num': 2,                   # g.holdings_num = 2
    'min_money': 5000,

    # 盈利保护 (聚宽: 11:00 + 14:00 双时点; 日频引擎仅能体现 11:00)
    'enable_profit_protection': True,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
    'profit_protection_check_times': ['11:00', '14:00'],

    # 6层过滤器: 跌幅(loss)+得分范围 启用, 成交量/短期动量 关闭
    'loss': 0.97,                        # g.loss = 0.97 启用
    'min_score_threshold': 0,            # g.min_score_threshold = 0
    'max_score_threshold': 100.0,        # g.max_score_threshold = 100
    'enable_volume_check': False,        # 简化版无成交量过滤
    'use_short_momentum_filter': False,  # 简化版无短期动量过滤
    'short_lookback_days': 10,

    # 溢价率
    'enable_premium_filter': True,
    'premium_threshold': 0.20,

    # 简化版: 无行情判断/无走弱回避/无日内回撤/无状态机/无恐慌
    'enable_regime_switch': False,
    'enable_avoid_a_share': False,
    'enable_intraday_drawdown': False,
    'enable_hs300_state_machine': False,
    'enable_panic_regime': False,
    'enable_no_down_day_buy': False,
}


def build_qmt_config():
    """复用权威脚本 backtest/qmt_backtest.py 的池与参数定义"""
    from backtest.qmt_backtest import QMT_POOL, QMT_PARAMS
    params = dict(QMT_PARAMS)
    # 克总2026-07-11拍板: 成分股MA恐慌期空仓永久关闭 (权威基线口径)
    params['enable_panic_regime'] = False
    return QMT_POOL, params


def main():
    parser = argparse.ArgumentParser(description='七星简化版 vs QMT 权威引擎对比')
    parser.add_argument('--mode', choices=['simplified', 'qmt'], required=True)
    parser.add_argument('--start', default='2021-06-21')
    parser.add_argument('--end', default='2026-09-17')
    parser.add_argument('--cash', type=float, default=1000000)
    args = parser.parse_args()

    # ---- 关键: 先 monkey-patch base 模块的 ETF_POOL, 再 import 引擎 ----
    import strategies.etf.seven_star_base as base_module

    if args.mode == 'simplified':
        base_module.ETF_POOL = SIMPLIFIED_POOL
        base_module.ETF_NAMES.update(SIMPLIFIED_NAMES)
        params = SIMPLIFIED_PARAMS
        pool_size = len(SIMPLIFIED_POOL)
        tag = '简化版'
        label = f'七星简化版 | 池{pool_size}只 | 持仓2只 | 20日动量 | 无行情判断 | 防御511880'
    else:
        pool, params = build_qmt_config()
        base_module.ETF_POOL = pool
        pool_size = len(pool)
        tag = 'QMT'
        label = f'七星QMT | 池{pool_size}只 | 持仓1只 | 25日动量 | 行情判断✅ | 恐慌❌'

    from strategies.etf.seven_star_172 import BacktestEngine172
    from strategies.etf.seven_star_base import LocalDataSource

    data_dir = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
    ds = LocalDataSource(data_dir)

    print('=' * 72)
    print(f'  {label}')
    print(f'  区间: {args.start} ~ {args.end} | 初始资金: ¥{args.cash:,.0f}')
    print('=' * 72)

    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = 0.0002
    results = engine.run(args.start, args.end, args.cash)
    if results is None:
        print('[FATAL] 回测失败')
        return

    # ---- 汇总 ----
    n_days = results.get('trading_days', 0)
    final_val = results.get('final_value', args.cash)
    total_ret = final_val / args.cash
    cagr = (total_ret ** (252.0 / n_days) - 1) if n_days > 0 else 0.0

    # ---- 分年度收益 (用于与聚宽逐年结果交叉验证) ----
    import collections
    yearly = collections.OrderedDict()
    dv = results.get('daily_values', [])
    prev_end = args.cash
    by_year = collections.OrderedDict()
    for d in dv:
        y = str(d['date'])[:4]
        by_year.setdefault(y, []).append(d['value'])
    for y, vals in by_year.items():
        yearly[y] = round((vals[-1] / prev_end - 1) * 100, 2)
        prev_end = vals[-1]

    summary = {
        'mode': args.mode,
        'tag': tag,
        'period': f'{args.start} ~ {args.end}',
        'pool_size': pool_size,
        'holdings_num': params['holdings_num'],
        'lookback_days': params['lookback_days'],
        'trading_days': n_days,
        'final_value': round(final_val, 2),
        'total_return_pct': round((total_ret - 1) * 100, 2),
        'cagr_pct': round(cagr * 100, 2),
        'max_drawdown_pct': results.get('max_drawdown_pct', 0),
        'sharpe_ratio': results.get('sharpe_ratio', 0),
        'calmar_ratio': results.get('calmar_ratio', 0),
        'total_trades': results.get('total_trades', 0),
        'win_rate_pct': results.get('win_rate_pct', 0),
        'final_holdings': results.get('final_holdings', []),
        'yearly_returns_pct': dict(yearly),
    }

    out_dir = PROJECT_ROOT / 'backtest' / 'results_compare'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'{args.mode}_{args.start}_{args.end}_summary.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print('\n' + '=' * 72)
    print(f'  【{tag}】回测完成')
    print(f'  累计收益: {(total_ret-1)*100:+.2f}% | 终值: ¥{final_val:,.0f}')
    print(f'  年化CAGR(几何): {cagr*100:+.2f}%')
    print(f'  最大回撤: {summary["max_drawdown_pct"]:.2f}% | 夏普: {summary["sharpe_ratio"]:.4f}')
    print(f'  交易: {summary["total_trades"]} | 胜率: {summary["win_rate_pct"]:.1f}%')
    print(f'  期末持仓: {summary["final_holdings"]}')
    print(f'  分年度: {summary["yearly_returns_pct"]}')
    print(f'  摘要已保存: {out_path}')
    print('=' * 72)


if __name__ == '__main__':
    main()
