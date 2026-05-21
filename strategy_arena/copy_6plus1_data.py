#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复制7只ETF数据到 back_trader_stocks/a/ 并转换为正确格式
"""

import pandas as pd
import shutil
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 7只ETF
ETF_POOL = {
    '159915': ('创业板ETF', 'XSHE'),
    '513100': ('纳指ETF', 'XSHG'),  # 注意：纳指在沪市
    '159985': ('豆粕ETF', 'XSHE'),
    '518880': ('黄金ETF', 'XSHG'),
    '501018': ('南方原油', 'XSHG'),
    '161226': ('白银LOF', 'XSHE'),
    '511220': ('城投ETF', 'XSHG'),
}

SOURCE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'
TARGET_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\a'

print("="*80)
print("复制并转换7只ETF数据")
print("="*80)

success = 0
for code, (name, market) in ETF_POOL.items():
    print(f"\n📊 {code} ({name})...")
    
    # 源文件
    source_file = os.path.join(SOURCE_DIR, f"{code}.csv")
    if not os.path.exists(source_file):
        print(f"  ❌ 源文件不存在: {source_file}")
        continue
    
    try:
        # 读取源文件
        df = pd.read_csv(source_file)
        
        # 检查列名
        print(f"  列名: {list(df.columns)}")
        
        # 确保有正确的列
        col_map = {}
        for c in df.columns:
            c_lower = c.lower().strip()
            if c_lower in ['date', 'open', 'high', 'low', 'close', 'volume']:
                col_map[c] = c_lower
        
        if 'Date' in df.columns and 'date' not in col_map:
            col_map['Date'] = 'date'
        elif 'date' not in col_map and 'Date' not in col_map:
            print(f"  ❌ 无法识别日期列")
            continue
        
        df = df.rename(columns=col_map)
        
        # 设置日期索引
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], utc=True).dt.tz_localize(None)
            df.set_index('date', inplace=True)
        elif 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)
            df.set_index('Date', inplace=True)
        
        # 筛选2026年数据
        start_2026 = pd.Timestamp('2026-01-01')
        end_2026 = pd.Timestamp('2026-05-20')
        df_2026 = df[(df.index >= start_2026) & (df.index <= end_2026)]
        
        if len(df_2026) < 10:
            print(f"  ⚠️ 2026年数据不足: {len(df_2026)}行")
        
        # 保存为目标文件 (159915_XSHE.csv 格式)
        target_filename = f"{code}_{market}.csv"
        target_path = os.path.join(TARGET_DIR, target_filename)
        
        # 确保列名正确
        needed_cols = ['open', 'high', 'low', 'close']
        for col in needed_cols:
            if col not in df.columns:
                print(f"  ❌ 缺少列: {col}")
                break
        else:
            if 'volume' not in df.columns:
                df['volume'] = 0
            
            df_to_save = df[['open', 'high', 'low', 'close', 'volume']].copy()
            df_to_save.to_csv(target_path, encoding='utf-8-sig')
            
            print(f"  ✅ 保存成功: {len(df)}行 ({df.index[0].date()} ~ {df.index[-1].date()})")
            print(f"      2026年: {len(df_2026)}行")
            success += 1
        
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "="*80)
print(f"完成！成功 {success}/7 只ETF")
print("="*80)

if success == 7:
    print("\n✅ 所有数据已就绪！可以运行6+1回测了！")
else:
    print(f"\n⚠️ 还有 {7-success} 只ETF未处理")
