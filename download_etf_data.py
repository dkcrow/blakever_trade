#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量下载/修复策略ETF池的历史数据"""

import os
import pandas as pd
import akshare as ak
from datetime import datetime
import time

# 策略中的ETF池（需要下载的代码映射）
etf_list = [
    # 代码, 新浪代码前缀(sh/sz)
    ('518880', 'sh'),  # 黄金ETF（已有，用于测试）
    ('159980', 'sz'),  # 有色ETF
    ('159985', 'sz'),  # 豆粕ETF
    ('501018', 'sh'),  # 南方原油
    ('161226', 'sz'),  # 白银LOF
    ('159981', 'sz'),  # 能源化工ETF
    ('513100', 'sh'),  # 纳指ETF
    ('159509', 'sz'),  # 纳指科技ETF
    ('513290', 'sh'),  # 纳指生物ETF
    ('513500', 'sh'),  # 标普500ETF
    ('159529', 'sz'),  # 标普消费
    ('513400', 'sh'),  # 道琼斯ETF
    ('513520', 'sh'),  # 日经225ETF
    ('513030', 'sh'),  # 德国30ETF
    ('513080', 'sh'),  # 法国ETF
    ('513310', 'sh'),  # 中韩半导体ETF
    ('513730', 'sh'),  # 东南亚ETF
    ('159792', 'sz'),  # 港股互联ETF
    ('513130', 'sh'),  # 恒生科技
    ('513050', 'sh'),  # 中概互联网ETF
    ('159920', 'sz'),  # 恒生ETF
    ('513690', 'sh'),  # 港股红利
    ('510300', 'sh'),  # 沪深300ETF
    ('510500', 'sh'),  # 中证500ETF
    ('510050', 'sh'),  # 上证50ETF
    ('510210', 'sh'),  # 上证ETF
    ('159915', 'sz'),  # 创业板ETF
    ('588080', 'sh'),  # 科创50
    ('512100', 'sh'),  # 中证1000ETF
    ('563360', 'sh'),  # A500-ETF
    ('563300', 'sh'),  # 中证2000ETF
    ('512890', 'sh'),  # 红利低波ETF
    ('159967', 'sz'),  # 创业板成长ETF
    ('512040', 'sh'),  # 价值ETF
    ('159201', 'sz'),  # 自由现金流ETF
    ('511380', 'sh'),  # 可转债ETF
    ('511010', 'sh'),  # 国债ETF
    ('511220', 'sh'),  # 城投债ETF
    ('511880', 'sh'),  # 货币基金（防御ETF）
]

# 输出目录
output_dir = r'c:\Users\blakehao\Desktop\blakever_trade\back_trader_stocks\etf'
os.makedirs(output_dir, exist_ok=True)

print('=' * 80)
print('开始批量下载ETF历史数据')
print('=' * 80)

success_count = 0
failed_list = []

for code, prefix in etf_list:
    try:
        sina_code = f'{prefix}{code}'
        market = 'XSHE' if prefix == 'sz' else 'XSHG'
        print(f'\n正在下载 {sina_code} ({code}.{market})...')
        
        # 使用AkShare下载ETF历史数据
        df = ak.fund_etf_hist_sina(symbol=sina_code)
        
        if df is not None and len(df) > 0:
            # 标准化列名（确保是小写）
            df.columns = df.columns.str.lower()
            
            # 如果amount列不存在，添加一个空列
            if 'amount' not in df.columns:
                df['amount'] = 0
            
            # 保存到ETF目录
            output_path = os.path.join(output_dir, f'{code}.csv')
            df.to_csv(output_path, index=False)
            
            start_date = df['date'].iloc[0]
            end_date = df['date'].iloc[-1]
            print(f'  [OK] 成功：{len(df)} 条数据，时间范围 {start_date} 至 {end_date}')
            print(f'  已保存到：{output_path}')
            success_count += 1
        else:
            print(f'  ✗ 失败：返回数据为空')
            failed_list.append(code)
        
        # 暂停避免请求过快
        time.sleep(0.5)
        
    except Exception as e:
        print(f'  ✗ 失败：{str(e)}')
        failed_list.append(code)
        time.sleep(1)

print('\n' + '=' * 80)
print(f'下载完成！')
print(f'  成功：{success_count} 只')
print(f'  失败：{len(failed_list)} 只')
if failed_list:
    print(f'\n失败列表：{failed_list}')
print('=' * 80)
