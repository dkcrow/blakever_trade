#!/usr/bin/env python3
import pandas as pd, os
base = r'c:\Users\blakehao\Desktop\blakever_trade\data\storage\stock_data\etf'

targets = {
    '159915': '创业板ETF',
    '513100': '纳指ETF',
    '159691': '中韩半导体',
    '159509': '标普消费ETF'
}

print('='*60)
print('关键ETF数据检查')
print('='*60)
for code, name in targets.items():
    fp = os.path.join(base, code + '.csv')
    if not os.path.exists(fp):
        # 尝试其他格式
        found = False
        for f in os.listdir(base):
            if code in f and f.endswith('.csv'):
                fp = os.path.join(base, f)
                found = True
                break
        if not found:
            print('%s(%s): 文件不存在!' % (name, code))
            continue
    
    df = pd.read_csv(fp)
    last_date = str(df.iloc[-1]['date'])
    first_date = str(df.iloc[0]['date'])
    print('  %s (%s) | 行数=%d | %s ~ %s' % (name, code, len(df), first_date, last_date))

# 检查所有文件最新日期
print()
print('数据截止日期统计:')
late_files = []
for f in sorted(os.listdir(base)):
    if not f.endswith('.csv'):
        continue
    df = pd.read_csv(os.path.join(base, f), usecols=['date'])
    last = str(df.iloc[-1]['date'])
    late_files.append((f, last))

late_sorted = sorted(late_files, key=lambda x: x[1], reverse=True)[:10]
for fname, ldate in late_sorted[:5]:
    print('  %s -> %s' % (fname, ldate))
print('  ... 共%d个CSV文件' % len(late_files))
