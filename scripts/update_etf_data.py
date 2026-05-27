#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量更新ETF历史数据，补齐缺失的交易日"""

import os
import sys
import time
import pandas as pd
import akshare as ak

# ETF池及新浪代码前缀
ETF_LIST = [
    ('518880', 'sh'), ('159980', 'sz'), ('159985', 'sz'),
    ('501018', 'sh'), ('161226', 'sz'), ('159981', 'sz'),
    ('513100', 'sh'), ('159509', 'sz'), ('513290', 'sh'),
    ('513500', 'sh'), ('159529', 'sz'), ('513400', 'sh'),
    ('513520', 'sh'), ('513030', 'sh'), ('513080', 'sh'),
    ('513310', 'sh'), ('513730', 'sh'),
    ('159792', 'sz'), ('513130', 'sh'), ('513050', 'sh'),
    ('159920', 'sz'), ('513690', 'sh'),
    ('510300', 'sh'), ('510500', 'sh'), ('510050', 'sh'),
    ('510210', 'sh'), ('159915', 'sz'), ('588080', 'sh'),
    ('512100', 'sh'), ('563360', 'sh'), ('563300', 'sh'),
    ('512890', 'sh'), ('159967', 'sz'), ('512040', 'sh'),
    ('159201', 'sz'),
    ('511380', 'sh'), ('511010', 'sh'), ('511220', 'sh'),
    ('511880', 'sh'),  # 防御ETF
]

OUTPUT_DIR = '/workspace/blakever_trade/data/storage/stock_data/etf'
os.makedirs(OUTPUT_DIR, exist_ok=True)

print('=' * 80)
print('ETF数据批量更新 - 补齐到最新交易日')
print('=' * 80)

success_count = 0
failed_list = []
update_count = 0

for code, prefix in ETF_LIST:
    try:
        sina_code = f'{prefix}{code}'
        filepath = os.path.join(OUTPUT_DIR, f'{code}.csv')
        
        # 读取本地已有数据
        if os.path.exists(filepath):
            df_existing = pd.read_csv(filepath)
            df_existing['date'] = df_existing['date'].astype(str).str.strip()
            existing_last = df_existing['date'].iloc[-1]
            existing_first = df_existing['date'].iloc[0]
        else:
            df_existing = None
            existing_last = 'N/A'
            existing_first = 'N/A'

        # 从akshare下载全量数据
        df_new = ak.fund_etf_hist_sina(symbol=sina_code)
        
        if df_new is None or len(df_new) == 0:
            print(f'  ✗ {code}: 下载返回空数据')
            failed_list.append(code)
            continue

        # 标准化列名
        df_new.columns = [c.lower().strip() for c in df_new.columns]
        df_new['date'] = df_new['date'].astype(str).str.strip()

        # 合并：用新数据覆盖旧文件（保留全量）
        if df_existing is not None:
            # 保留旧数据中的日期，新数据只追加不覆盖的日期
            existing_dates = set(df_existing['date'])
            new_only = df_new[~df_new['date'].isin(existing_dates)]
            
            if len(new_only) == 0:
                print(f'  ✓ {code}: 已是最新 (本地: {existing_first} ~ {existing_last}, 线上: {existing_last})')
                success_count += 1
            else:
                df_merged = pd.concat([df_existing, new_only], ignore_index=True)
                df_merged = df_merged.drop_duplicates(subset=['date'], keep='first')
                df_merged = df_merged.sort_values('date').reset_index(drop=True)
                df_merged.to_csv(filepath, index=False)
                
                added = len(new_only)
                print(f'  ✓ {code}: 新增{added}条 (本地: {existing_first} ~ {df_merged["date"].iloc[-1]}, '
                      f'补了 {new_only["date"].iloc[0]} ~ {new_only["date"].iloc[-1]})')
                success_count += 1
                update_count += 1
        else:
            # 新文件，直接保存
            df_new = df_new.sort_values('date').reset_index(drop=True)
            df_new.to_csv(filepath, index=False)
            print(f'  ✓ {code}: 新建文件, {len(df_new)}条 ({df_new["date"].iloc[0]} ~ {df_new["date"].iloc[-1]})')
            success_count += 1
            update_count += 1

        # 暂停避免请求过快
        time.sleep(0.3)

    except Exception as e:
        print(f'  ✗ {code}: 异常 - {str(e)[:80]}')
        failed_list.append(code)
        time.sleep(1)

print('\n' + '=' * 80)
print(f'更新完成!')
print(f'  成功: {success_count}/{len(ETF_LIST)} 只')
print(f'  实际更新: {update_count} 只')
print(f'  失败: {len(failed_list)} 只')
if failed_list:
    print(f'  失败列表: {", ".join(failed_list)}')
print('=' * 80)
