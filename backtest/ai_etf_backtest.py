#!/usr/bin/env python3
"""AI ETF策略 (激进牛熊版) 回测 — 基于BacktestEngine172权威引擎
用法: python backtest/ai_etf_backtest.py --start 2021-07-09 --end 2026-07-09 --cash 1000000
"""
import sys, os, argparse, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ====== AI ETF池 (52只, 含原品种+爆发标的) ======
AI_ETF_RAW = [
    # 商品 (6)
    '518880','159980','159985','501018','161226','159981',
    # 美股 (6)
    '513100','159509','513290','513500','159529','513400',
    # 其他海外 (5)
    '513520','513030','513080','513310','513730',
    # 港股 (5)
    '159792','513130','513050','159920','513690',
    # A股宽基 (10)
    '510300','510500','510050','510210','159915','588080','512100','563360','563300','159201',
    # A股风格 (3)
    '512890','159967','512040',
    # 债券 (3)
    '511380','511010','511220',
    # 爆发标的 (14)
    '159949','512880','512660','515050','512760','159995','515030',
    '516510','515790','512480','513300','159941','513200','159892',
]
AI_ETF_POOL = ['sh' + c if c.startswith('5') else 'sz' + c for c in AI_ETF_RAW]

# ====== Monkey-patch: 替换172引擎ETF_POOL ======
import strategies.etf.seven_star_base as base_module
base_module.ETF_POOL = AI_ETF_POOL
# 名称映射（精简）
AI_NAMES = {
    'sh518880':'黄金','sz159980':'有色期货','sz159985':'豆粕','sh501018':'原油LOF','sz161226':'白银LOF','sz159981':'能源化工',
    'sh513100':'纳指','sz159509':'纳指科技','sh513290':'纳指生物','sh513500':'标普','sz159529':'标普消费','sh513400':'道琼斯',
    'sh513520':'日经','sh513030':'德国','sh513080':'法国','sh513310':'中韩半导体','sh513730':'东南亚',
    'sz159792':'港股互联','sh513130':'恒生科技','sh513050':'中概互联','sz159920':'恒生','sh513690':'港股红利',
    'sh510300':'沪深300','sh510500':'中证500','sh510050':'上证50','sh510210':'上证综指','sz159915':'创业板',
    'sh588080':'科创50','sh512100':'中证1000','sh563360':'A500','sh563300':'A2000','sz159201':'深证主板',
    'sh512890':'红利低波','sz159967':'创成长','sh512040':'价值ETF',
    'sh511380':'可转债','sh511010':'国债','sh511220':'城投债',
    'sz159949':'创业板50','sh512880':'证券ETF','sh512660':'军工','sh515050':'5GETF','sh512760':'芯片ETF',
    'sz159995':'芯片深','sh515030':'新能车','sh516510':'云计算','sh515790':'光伏','sh512480':'半导体',
    'sh513300':'纳指ETF','sz159941':'纳指深','sh513200':'港股医药','sz159892':'恒生生物',
}
base_module.ETF_NAMES.update(AI_NAMES)

from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

# ====== AI ETF参数 ======
AI_ETF_PARAMS = {
    'lookback_days': 25,
    'holdings_num': 1,
    'min_money': 5000,

    # 盈利保护: AI ETF用3日高点回撤5% (vs QMT的1日)
    'enable_profit_protection': True,
    'profit_protection_lookback': 3,
    'profit_protection_threshold': 0.05,
    'profit_protection_check_times': ['11:00'],

    # 过滤器: AI ETF启用短期动量+成交量 (vs QMT关闭)
    'loss': 0.97,
    'min_score_threshold': 0,
    'max_score_threshold': 100.0,
    'enable_volume_check': True,
    'volume_lookback': 5,
    'volume_threshold': 2,
    'volume_return_limit': 1,
    'use_short_momentum_filter': True,
    'short_lookback_days': 10,
    'short_momentum_threshold': 0.0,

    # 溢价率: AI ETF用3% (vs QMT的20%)
    'enable_premium_filter': True,
    'premium_threshold': 0.03,

    # 行情判断: AI ETF用HS300 MA200 (不是成分股恐慌), 此处关闭BacktestEngine172的内置panic
    'enable_regime_switch': False,
    'enable_avoid_a_share': False,
    'enable_intraday_drawdown': False,
    'enable_panic_regime': False,
}


def main():
    parser = argparse.ArgumentParser(description='AI ETF回测 (172引擎+AI ETF池+参数)')
    parser.add_argument('--start', type=str, default='2021-07-09')
    parser.add_argument('--end', type=str, default='2026-07-09')
    parser.add_argument('--cash', type=float, default=1000000)
    parser.add_argument('--holdings', type=int, default=1)
    parser.add_argument('--no-protection', action='store_true')
    args = parser.parse_args()

    AI_ETF_PARAMS['holdings_num'] = args.holdings
    AI_ETF_PARAMS['enable_profit_protection'] = not args.no_protection

    data_dir = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
    ds = LocalDataSource(data_dir)

    pp_flag = '❌关闭' if args.no_protection else '✅启用(3日/5%)'
    print("=" * 70)
    print(f"  AI ETF(牛熊版) 回测 | {args.start} ~ {args.end} | ¥{args.cash:,.0f}")
    print(f"  ETF池: {len(AI_ETF_POOL)}只 | 持仓: {args.holdings}只 | 盈利保护: {pp_flag}")
    print(f"  过滤器: 溢价率✅(3%) 成交量✅ 短期动量✅(10日) 跌幅✅(0.97)")
    print(f"  行情判断: HS300 MA200 (引擎不支持, 需独立验证)")
    print("=" * 70)

    engine = BacktestEngine172(ds, engine_params=AI_ETF_PARAMS)
    engine.commission_rate = 0.0002
    results = engine.run(args.start, args.end, args.cash)

    if results is None:
        print("回测失败!")
        return

    # 计算CAGR
    n_days = results.get('trading_days', 0)
    final_val = results.get('final_value', args.cash)
    total_ret = final_val / args.cash
    cagr = total_ret ** (252.0 / n_days) - 1 if n_days > 0 else 0

    print(f"\n{'='*70}")
    print(f"  📊 回测结果")
    print(f"{'='*70}")
    print(f"  终值: ¥{final_val:,.0f}  |  累计: {(total_ret-1)*100:+.1f}%")
    print(f"  年化(CAGR): {cagr*100:+.1f}%  |  交易日: {n_days}")
    print(f"  最大回撤: {results.get('max_drawdown_pct', 0):.1f}%")
    print(f"  夏普: {results.get('sharpe', 0):.2f}  |  胜率: {results.get('win_rate', 0):.1f}%")
    print(f"  交易: {results.get('total_trades', 0)}笔")

    # 保存结果
    RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_qmt'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f'ai_etf_{args.start}_{args.end}'
    summary_path = RESULTS_DIR / f'{tag}_summary.json'
    summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n摘要已保存: {summary_path}")
    print("完成!")


if __name__ == '__main__':
    main()
