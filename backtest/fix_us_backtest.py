#!/usr/bin/env python3
"""Fix us100_backtest.py to optimal config"""
import re

path = 'backtest/us100_backtest.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Replace pool import section with inline 35-symbol list
old_pool = r'''# 七星多元化股池 (移除消费/公用事业/医疗/金融/通信 → 保留高成长+能源+工业+REITs)
from strategies.us.seven_star_us_pool import SEVEN_STAR_US_POOL
REMOVED_CATS = {"消费防御", "消费服务", "公用事业", "医疗健康", "金融_价值", "通信"}
FILTERED_SYMBOLS = []
for cat, syms in SEVEN_STAR_US_POOL.items():
    if cat not in REMOVED_CATS:
        FILTERED_SYMBOLS.extend(syms)
POOL_SYMBOLS = FILTERED_SYMBOLS'''

new_pool = '''# 七星美股版最优池 (35只, 8类 — 无防御板块)
POOL_SYMBOLS = [
    # 大科技/半导体 (10)
    'NVDA','AVGO','AMD','MU','LRCX','AMAT','ARM','AAPL','TSM','LITE',
    # 互联网/平台 (4)
    'META','AMZN','NFLX','GOOGL',
    # 软件/SaaS (5)
    'MSFT','CRM','NOW','CRWD','ORCL',
    # AI/数据 (3)
    'PLTR','DDOG','SNPS',
    # 能源 (5)
    'XOM','CVX','COP','EOG','OKE',
    # 材料/矿业 (3)
    'NEM','FCX','LIN',
    # 工业/基建 (3)
    'CAT','GE','RTX',
    # REITs (2)
    'PLD','AMT',
]'''

content = content.replace(old_pool, new_pool)

# 2. Remove stop_loss from PARAMS
content = content.replace(
    "    'enable_stop_loss': True,\n    'stop_loss_ratio': 0.92,\n",
    ""
)

# 3. Fix strategy name
for old_name in [
    "STRATEGY_NAME = '七星美股版(高成长35无PP) x5'",
    "STRATEGY_NAME = '七星美股版(多元化池58) x5'",
    "STRATEGY_NAME = '七星美股版(Nasdaq100) x5'",
    "STRATEGY_NAME = '七星美股版(高成长+能源35) x5'",
]:
    if old_name in content:
        content = content.replace(old_name, "STRATEGY_NAME = '七星美股版(最优) x5'")
        break

# 4. Remove stop loss code from main loop (if exists)
content = content.replace(
    r'''
    # -8% 硬止损
    if PARAMS.get('enable_stop_loss', False):
        for code in list(pf.get_position_codes()):
            if code in prices and code in pf.positions:
                pos = pf.positions[code]
                cp = prices[code]
                cost = pos.get('cost_price', cp)
                if cost > 0 and cp <= cost * 0.92:
                    loss_pct = (cp / cost - 1) * 100
                    pf.sell_all(code, cp, td, reason=f'硬止损({loss_pct:.1f}%)')''',
    ""
)

# 5. Update docstring
content = content.replace(
    '基于七星QMT框架，成分股 = 七星多元化美股池 (58只, 14类)',
    '基于七星QMT框架，成分股 = 高成长35只优化池 (无防御板块，PP关)'
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done - us100_backtest.py restored to optimal config")
