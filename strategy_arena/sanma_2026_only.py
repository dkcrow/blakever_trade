#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星三马V7 - 2026年至今回测
时间范围: 2026-01-01 ~ 2026-05-20
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

# 修改回测时间
import qixing_sanma_us_v7 as strategy

# 运行2026年回测
print("\n" + "="*80)
print("七星三马V7 - 2026年至今回测")
print("时间范围: 2026-01-01 ~ 2026-05-20")
print("="*80)

# 调用原函数，但修改时间范围
strategy.run_backtest(start_date='2026-01-01', end_date='2026-05-20')
