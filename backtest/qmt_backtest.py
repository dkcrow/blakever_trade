"""七星QMT 回测脚本 — 使用172引擎 + QMT池 + QMT参数

用法: python backtest/qmt_backtest.py --start 2021-06-21 --end 2026-06-21 --cash 1000000
"""
import sys, os, argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ================================================================
# QMT 50只ETF池 (2026-06-21: -513030德国30 -513730东南亚 +588200科创芯片)
# ================================================================
QMT_RAW_CODES = [
    # 海外ETF (13)
    '513100','513290','513500','159529','513400','513520','513080',
    '513310','159792','513130','513050','159920','513690',
    # 债券ETF (3)
    '511380','511010','511220',
    # 商品ETF (7)
    '518880','159980','159985','501018','161226','159981','512400',
    # A股指数ETF (10)
    '510300','510500','510050','510210','159915','588080','588200','512100','563360','563300',
    # A股风格ETF (5)
    '512890','159967','588020','512040','159201',
    # A股行业板块ETF (12)
    '515790','563230','515880','512660','561380','159667','159559',
    '159819','159381','159732','159995','512220',
]
QMT_POOL = ['sh' + c if c.startswith('5') else 'sz' + c for c in QMT_RAW_CODES]

QMT_NAMES = {
    'sh513100': '纳指ETF', 'sh513290': '纳指生物ETF', 'sh513500': '标普500ETF',
    'sz159529': '标普消费ETF', 'sh513400': '道琼斯ETF', 'sh513520': '日经ETF',
    'sh513080': '法国ETF', 'sh513310': '中韩半导体ETF',
    'sz159792': '港股互联ETF', 'sh513130': '恒生科技ETF',
    'sh513050': '中概互联网ETF', 'sz159920': '恒生ETF', 'sh513690': '港股红利ETF',
    'sh511380': '可转债ETF', 'sh511010': '国债ETF', 'sh511220': '城投债ETF',
    'sh518880': '黄金ETF', 'sz159980': '有色ETF', 'sz159985': '豆粕ETF',
    'sh501018': '南方原油', 'sz161226': '白银LOF', 'sz159981': '能源化工ETF',
    'sh512400': '有色金属ETF',
    'sh510300': '沪深300ETF', 'sh510500': '中证500ETF', 'sh510050': '上证50ETF',
    'sh510210': '上证指数ETF', 'sz159915': '创业板ETF', 'sh588080': '科创50ETF',
    'sh588200': '科创芯片ETF', 'sh512100': '中证1000ETF', 'sh563360': 'A500ETF',
    'sh563300': '中证2000ETF',
    'sh512890': '红利低波ETF', 'sz159967': '创业板成长ETF', 'sh588020': '科创成长ETF',
    'sh512040': '价值100ETF', 'sz159201': '自由现金流ETF',
    'sh515790': '光伏ETF', 'sh563230': '卫星ETF', 'sh515880': '通信ETF',
    'sh512660': '军工ETF', 'sh561380': '电网设备ETF', 'sz159667': '工业母机ETF',
    'sz159559': '机器人ETF', 'sz159819': '人工智能ETF', 'sz159381': '创业板AI ETF',
    'sz159732': '消费电子ETF', 'sz159995': '芯片ETF', 'sh512220': 'TMTETF',
    'sh511880': '银华日利(货币基金)',
}

# ================================================================
# Monkey-patch: 替换172引擎的ETF_POOL为QMT池
# ================================================================
import strategies.etf.seven_star_base as base_module
base_module.ETF_POOL = QMT_POOL
# 合并名称
base_module.ETF_NAMES.update(QMT_NAMES)

from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

# ================================================================
# QMT参数 (区别于172原版)
# ================================================================
QMT_PARAMS = {
    'lookback_days': 25,
    'holdings_num': 1,
    'min_money': 5000,

    # 盈利保护: 启用
    'enable_profit_protection': True,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
    'profit_protection_check_times': ['11:00'],

    # 过滤器: QMT精简版 (成交量/短期动量/跌幅/得分范围 全部关闭)
    'loss': 0.01,                    # 关闭
    'min_score_threshold': -999999,  # 关闭
    'max_score_threshold': 999999,   # 关闭
    'enable_volume_check': False,    # 关闭
    'use_short_momentum_filter': False,  # 关闭
    'short_lookback_days': 10,

    # 溢价率: 启用
    'enable_premium_filter': True,
    'premium_threshold': 0.20,

    # 行情判断 & 走弱期防御 (QMT V3特有)
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
    'intraday_drawdown_threshold': 0.02,
    'weak_period_ma_lookback': 10,
    'weak_period_max_days': 20,
}


def main():
    parser = argparse.ArgumentParser(description='七星QMT回测 (使用172引擎+QMT池+QMT参数)')
    parser.add_argument('--start', type=str, default='2021-06-21', help='回测起始日期')
    parser.add_argument('--end', type=str, default='2026-06-21', help='回测结束日期')
    parser.add_argument('--cash', type=float, default=1000000, help='初始资金')
    parser.add_argument('--holdings', type=int, default=1, help='持仓数量')
    parser.add_argument('--no-protection', action='store_true', help='关闭盈利保护')
    parser.add_argument('--pp-threshold', type=float, default=0.05, help='盈利保护回撤阈值(默认0.05=5%)')
    parser.add_argument('--short-momentum', action='store_true', help='开启短期动量过滤(逃顶: 剔除短期动量<阈值的ETF)')
    parser.add_argument('--short-lb', type=int, default=10, help='短期动量回看天数(默认10)')
    parser.add_argument('--short-thr', type=float, default=0.0, help='短期动量年化阈值(默认0, <此值过滤)')
    args = parser.parse_args()

    # 覆盖持仓数 + 盈利保护开关 + 阈值 + 短期动量过滤
    QMT_PARAMS['holdings_num'] = args.holdings
    QMT_PARAMS['enable_profit_protection'] = not args.no_protection
    QMT_PARAMS['profit_protection_threshold'] = args.pp_threshold
    QMT_PARAMS['use_short_momentum_filter'] = args.short_momentum
    QMT_PARAMS['short_lookback_days'] = args.short_lb
    QMT_PARAMS['short_momentum_threshold'] = args.short_thr

    data_dir = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
    ds = LocalDataSource(data_dir)

    pp_flag = '❌关闭' if args.no_protection else f'✅启用({args.pp_threshold*100:.0f}%)'
    sm_flag = f'✅启用({args.short_lb}日,阈{args.short_thr})' if args.short_momentum else '❌关闭'
    print("=" * 70)
    print(f"  七星QMT回测 | {args.start} ~ {args.end} | ¥{args.cash:,.0f}")
    print(f"  ETF池: {len(QMT_POOL)}只 | 持仓: {args.holdings}只 | 盈利保护: {pp_flag}")
    print(f"  过滤器: 溢价率✅ 行情判断✅ 回避A股✅ 日内回撤✅")
    print(f"  短期动量: {sm_flag} | 关闭: 成交量❌ 跌幅❌ 得分范围❌")
    print("=" * 70)

    engine = BacktestEngine172(ds, engine_params=QMT_PARAMS)
    engine.commission_rate = 0.0002
    results = engine.run(args.start, args.end, args.cash)

    if results is None:
        print("回测失败!")
        return

    import json
    RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_qmt'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 文件名带阈值标签, 避免并行运行冲突
    tag = 'noPP' if args.no_protection else f'pp{int(args.pp_threshold*100)}'

    # 保存摘要
    summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
    summary_path = RESULTS_DIR / f'七星QMT_{args.start}_{args.end}_{tag}_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n摘要已保存: {summary_path}")

    # 保存交易记录
    trades_path = RESULTS_DIR / f'七星QMT_{args.start}_{args.end}_{tag}_trades.json'
    with open(trades_path, 'w', encoding='utf-8') as f:
        json.dump(results['trade_log'], f, ensure_ascii=False, indent=2, default=str)
    print(f"交易记录已保存: {trades_path}")

    # 计算正确的几何CAGR (引擎用的是算术年化, 有Bug)
    n_days = results.get('trading_days', 0)
    final_val = results.get('final_value', args.cash)
    total_ret = final_val / args.cash
    if n_days > 0:
        cagr = total_ret ** (252.0 / n_days) - 1
    else:
        cagr = 0.0
    arith = results.get('annualized_return_pct', 0)

    print(f"\n{'=' * 70}")
    print(f"  七星QMT 回测完成 | 盈利保护: {pp_flag}")
    print(f"  累计收益: {(total_ret-1)*100:+.2f}% | 终值: ¥{final_val:,.0f}")
    print(f"  年化(算术-引擎Bug): {arith:+.2f}%  →  年化(几何CAGR-正确): {cagr*100:+.2f}%")
    print(f"  最大回撤: {results.get('max_drawdown_pct', 0):.2f}% | 夏普: {results.get('sharpe_ratio', 0):.4f}")
    print(f"  交易: {results.get('total_trades', 0)} | 胜率: {results.get('win_rate_pct', 0):.1f}%")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
