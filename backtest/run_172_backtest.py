#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立脚本: 运行七星172回测并保存结果"""
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

from pathlib import Path
from strategies.etf.seven_star_base import LocalDataSource
from strategies.etf.seven_star_172 import BacktestEngine172, SevenStar172Engine
from strategies.etf.seven_star_base import SevenStar172Filter

PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_172'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

START = '2025-01-01'
END = '2026-06-03'
CASH = 100000

# 数据源
data_dir = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
ds = LocalDataSource(data_dir)

# 参数 (与七星172默认一致)
params = {
    'lookback_days': 25,
    'holdings_num': 1,
    'enable_profit_protection': True,
    'enable_volume_check': False,
    'use_short_momentum_filter': False,
    'enable_premium_filter': True,
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
}

# 回测
etf_filter = SevenStar172Filter()
engine = BacktestEngine172(ds, engine_params=params, etf_filter=etf_filter)
engine.commission_rate = 0.0002
results = engine.run(START, END, CASH)

if results is None:
    print('回测失败!')
    sys.exit(1)

# 保存
summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
with open(RESULTS_DIR / '七星172_2025-01-01_2026-06-03_summary.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

with open(RESULTS_DIR / '七星172_2025-01-01_2026-06-03_trades.json', 'w', encoding='utf-8') as f:
    json.dump(results['trade_log'], f, ensure_ascii=False, indent=2, default=str)

with open(RESULTS_DIR / '七星172_2025-01-01_2026-06-03_daily.json', 'w', encoding='utf-8') as f:
    json.dump(results['daily_values'], f, ensure_ascii=False, indent=2, default=str)

print(f'\n摘要: {RESULTS_DIR / "七星172_2025-01-01_2026-06-03_summary.json"}')
print(f'交易: {RESULTS_DIR / "七星172_2025-01-01_2026-06-03_trades.json"}')
print(f'净值: {RESULTS_DIR / "七星172_2025-01-01_2026-06-03_daily.json"}')
