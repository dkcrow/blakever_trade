#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 westock-data kline 获取7只ETF的2026年数据
保存到 back_trader_stocks/a/ 目录
"""

import subprocess
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# 7只ETF代码
ETF_POOL = {
    '159915': '创业板ETF',
    '513100': '纳指ETF',
    '159985': '豆粕ETF',
    '518880': '黄金ETF',
    '501018': '南方原油',
    '161226': '白银LOF',
    '511220': '城投ETF',
}

# westock-data 路径
WESTOCK_JS = r'C:\Users\blakehao\.qclaw\workspace\skills\westock-data\scripts\index.js'
SAVE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\a'

def fetch_kline(code):
    """用 westock-data kline 获取数据"""
    try:
        # kline 命令: node index.js kline <code> day <count>
        # 获取250条确保覆盖2026全年 + 历史数据
        cmd = ['node', WESTOCK_JS, 'kline', code, 'day', '250']
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.dirname(WESTOCK_JS)
        )
        
        if result.returncode != 0:
            print(f"  ❌ {code} 失败: {result.stderr[:100]}")
            return None
        
        # 解析输出
        output = result.stdout.strip()
        if not output:
            print(f"  ❌ {code} 无输出")
            return None
        
        # 查找JSON部分
        lines = output.split('\n')
        json_started = False
        json_lines = []
        
        for line in lines:
            if line.strip().startswith('{') or line.strip().startswith('['):
                json_started = True
            if json_started:
                json_lines.append(line)
        
        if not json_lines:
            print(f"  ❌ {code} 无JSON数据")
            return None
        
        json_str = '\n'.join(json_lines)
        data = json.loads(json_str)
        
        # 检查是否是 BatchResult 结构
        if isinstance(data, dict) and 'data' in data:
            items = data['data']
            if items and len(items) > 0:
                return items[0]  # 返回第一个股票的K线
        elif isinstance(data, list):
            return {'klines': data}
        
        return data
        
    except Exception as e:
        print(f"  ❌ {code} 异常: {e}")
        return None

def save_to_csv(code, kline_data):
    """保存K线数据为CSV"""
    try:
        if not kline_data or 'klines' not in kline_data:
            return False
        
        klines = kline_data['klines']
        if not klines or len(klines) == 0:
            return False
        
        # 转换为CSV格式
        rows = []
        for k in klines:
            # k 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率]
            date_str = k[0]
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            except:
                continue
            
            row = {
                'Date': date_obj.strftime('%Y-%m-%d'),
                'Open': float(k[1]),
                'Close': float(k[2]),
                'High': float(k[3]),
                'Low': float(k[4]),
                'Volume': float(k[5]) if len(k) > 5 else 0,
            }
            rows.append(row)
        
        if not rows:
            return False
        
        # 转为DataFrame并保存
        import pandas as pd
        df = pd.DataFrame(rows)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        df = df.sort_index()
        
        # 文件名: 159915_XSHE.csv
        if code.startswith('5') or code.startswith('1'):
            suffix = 'XSHE'  # 深圳
        else:
            suffix = 'XSHG'  # 上海
        
        filename = f"{code}_{suffix}.csv"
        filepath = os.path.join(SAVE_DIR, filename)
        
        df.to_csv(filepath, encoding='utf-8-sig')
        print(f"  ✅ {code} 保存成功: {len(df)}行 ({df.index[0].date()} ~ {df.index[-1].date()})")
        return True
        
    except Exception as e:
        print(f"  ❌ {code} 保存失败: {e}")
        return False

print("="*80)
print("用 westock-data 获取7只ETF的2026年数据")
print("="*80)

success_count = 0
for code, name in ETF_POOL.items():
    print(f"\n📊 获取 {code} ({name})...")
    kline_data = fetch_kline(code)
    if kline_data:
        if save_to_csv(code, kline_data):
            success_count += 1
    else:
        print(f"  ❌ 获取失败")

print("\n" + "="*80)
print(f"完成！成功 {success_count}/7 只ETF")
print("="*80)

if success_count == 7:
    print("\n✅ 所有数据已准备好，可以运行6+1回测了！")
else:
    print(f"\n⚠️ 还有 {7-success_count} 只ETF数据未获取")
