#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查策略ETF池中数据完整性"""

import os
import pandas as pd
import sys

# 设置标准输出编码为UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# 策略中的ETF池
etf_pool = [
    '518880.XSHG', '159980.XSHE', '159985.XSHE', '501018.XSHG', '161226.XSHE',
    '159981.XSHE', '513100.XSHG', '159509.XSHE', '513290.XSHG', '513500.XSHG',
    '159529.XSHE', '513400.XSHG', '513520.XSHG', '513030.XSHG', '513080.XSHG',
    '513310.XSHG', '513730.XSHG', '159792.XSHE', '513130.XSHG', '513050.XSHG',
    '159920.XSHE', '513690.XSHG', '510300.XSHG', '510500.XSHG', '510050.XSHG',
    '510210.XSHG', '159915.XSHE', '588080.XSHG', '512100.XSHG', '563360.XSHG',
    '563300.XSHG', '512890.XSHG', '159967.XSHE', '512040.XSHG', '159201.XSHE',
    '511380.XSHG', '511010.XSHG', '511220.XSHG'
]

# 防御ETF
defensive_etf = '511880.XSHG'

base_dir = r'c:\Users\blakehao\Desktop\blakever_trade\back_trader_stocks'

results = []
for etf in etf_pool + [defensive_etf]:
    # 提取代码
    code = etf.split('.')[0]
    exchange = etf.split('.')[1]
    
    # 可能的文件路径
    possible_paths = [
        os.path.join(base_dir, 'etf', f'{code}.csv'),
        os.path.join(base_dir, 'a', f'{code}_XSHG.csv'),
        os.path.join(base_dir, 'a', f'{code}_XSHE.csv'),
    ]
    
    found = False
    for path in possible_paths:
        if os.path.exists(path):
            try:
                df_all = pd.read_csv(path)
                start_date = df_all['date'].iloc[0]
                end_date = df_all['date'].iloc[-1]
                total_days = len(df_all)
                
                results.append({
                    'code': etf,
                    'status': '[OK] 完整',
                    'start': start_date,
                    'end': end_date,
                    'days': total_days,
                    'file': path
                })
                found = True
                break
            except Exception as e:
                results.append({
                    'code': etf,
                    'status': f'[ERROR] 数据损坏: {str(e)}',
                    'start': '-',
                    'end': '-',
                    'days': '-',
                    'file': path
                })
                found = True
                break
    
    if not found:
        results.append({
            'code': etf,
            'status': '[MISSING] 缺失',
            'start': '-',
            'end': '-',
            'days': '-',
            'file': '未找到'
        })

# 输出结果
print('=' * 120)
print(f"{'代码':<15} {'状态':<20} {'起始日期':<12} {'结束日期':<12} {'交易日数':<10} {'文件路径'}")
print('=' * 120)

missing = []
for r in results:
    print(f"{r['code']:<15} {r['status']:<20} {r['start']:<12} {r['end']:<12} {str(r['days']):<10} {r['file']}")
    if '缺失' in r['status'] or '损坏' in r['status']:
        missing.append(r['code'])

print('=' * 120)
print(f"\n总结：")
print(f"  总计：{len(results)} 只ETF")
print(f"  [OK] 完整：{len(results) - len(missing)} 只")
print(f"  [MISSING] 缺失/损坏：{len(missing)} 只")

if missing:
    print(f"\n缺失或数据损坏的ETF：")
    for m in missing:
        print(f"  - {m}")
else:
    print(f"\n所有ETF数据完整！")
