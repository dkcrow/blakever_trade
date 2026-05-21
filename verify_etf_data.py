#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证ETF数据完整性"""

import os
import pandas as pd

etf_codes = [
    '518880', '159980', '159985', '501018', '161226', '159981', '513100',
    '159509', '513290', '513500', '159529', '513400', '513520', '513030',
    '513080', '513310', '513730', '159792', '513130', '513050', '159920',
    '513690', '510300', '510500', '510050', '510210', '159915', '588080',
    '512100', '563360', '563300', '512890', '159967', '512040', '159201',
    '511380', '511010', '511220', '511880'
]

base_dir = r'c:\Users\blakehao\Desktop\blakever_trade\back_trader_stocks\etf'

print('=' * 100)
print('ETF数据验证')
print('=' * 100)
print(f'{"代码":<12} {"状态":<10} {"起始日期":<12} {"结束日期":<12} {"行数":<8}')
print('-' * 100)

success = 0
failed = 0

for code in etf_codes:
    file_path = os.path.join(base_dir, f'{code}.csv')
    try:
        df = pd.read_csv(file_path)
        start = df['date'].iloc[0]
        end = df['date'].iloc[-1]
        rows = len(df)
        print(f'{code:<12} {"OK":<10} {start:<12} {end:<12} {rows:<8}')
        success += 1
    except Exception as e:
        print(f'{code:<12} {"FAIL":<10} {"-":<12} {"-":<12} {"-":<8} Error: {e}')
        failed += 1

print('=' * 100)
print(f'\n验证完成：')
print(f'  成功：{success} 只')
print(f'  失败：{failed} 只')
print('=' * 100)
