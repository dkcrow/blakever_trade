#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用腾讯API下载7只ETF的2026年数据
保存到 back_trader_stocks/a/ 目录
"""

import urllib.request
import json
import os
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

# 7只ETF
ETF_POOL = {
    '159915': '创业板ETF',
    '513100': '纳指ETF', 
    '159985': '豆粕ETF',
    '518880': '黄金ETF',
    '501018': '南方原油',
    '161226': '白银LOF',
    '511220': '城投ETF',
}

SAVE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\a'

def download_etf_tencent(code, start_date='2026-01-01', end_date='2026-05-20'):
    """用腾讯API下载ETF数据"""
    try:
        # 腾讯API: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=code,day,start,end,250,qfq
        # ETF代码格式: sz159915, sh518880
        if code.startswith('5') or code.startswith('1'):
            prefix = 'sz'  # 深圳
        else:
            prefix = 'sh'  # 上海
        
        full_code = f"{prefix}{code}"
        
        # 计算天数
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        days = (end - start).days + 10  # 多取几天确保覆盖
        
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,,,{days},qfq"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('gbk'))
        
        if not data.get('code') == 0:
            return None
        
        # 提取K线
        klines = data.get('data', {}).get(full_code, {}).get('qfqday', [])
        if not klines:
            return None
        
        # 过滤日期范围
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        rows = []
        for k in klines:
            # k: [日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额]
            date_str = k[0]
            try:
                k_date = datetime.strptime(date_str, '%Y-%m-%d')
            except:
                continue
            
            if start_dt <= k_date <= end_dt:
                rows.append({
                    'Date': date_str,
                    'Open': float(k[1]),
                    'Close': float(k[2]),
                    'High': float(k[3]),
                    'Low': float(k[4]),
                    'Volume': float(k[5]) if len(k) > 5 else 0,
                })
        
        return rows
        
    except Exception as e:
        print(f"    ❌ 异常: {e}")
        return None

def save_csv(code, rows):
    """保存为CSV"""
    try:
        import pandas as pd
        
        if not rows:
            return False
        
        df = pd.DataFrame(rows)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        df = df.sort_index()
        
        # 文件名: 159915_XSHE.csv
        if code.startswith('5') or code.startswith('1'):
            suffix = 'XSHE'
        else:
            suffix = 'XSHG'
        
        filename = f"{code}_{suffix}.csv"
        filepath = os.path.join(SAVE_DIR, filename)
        
        df.to_csv(filepath, encoding='utf-8-sig')
        print(f"    ✅ 保存 {len(df)}行: {df.index[0].date()} ~ {df.index[-1].date()}")
        return True
        
    except Exception as e:
        print(f"    ❌ 保存失败: {e}")
        return False

print("="*80)
print("用腾讯API下载7只ETF的2026年数据")
print("="*80)

success = 0
for code, name in ETF_POOL.items():
    print(f"\n📊 {code} ({name})...")
    rows = download_etf_tencent(code)
    if rows:
        if save_csv(code, rows):
            success += 1
    else:
        print(f"    ❌ 下载失败")

print("\n" + "="*80)
print(f"完成！成功 {success}/7 只ETF")
print("="*80)

if success == 7:
    print("\n✅ 所有数据已就绪！现在可以运行6+1回测了！")
