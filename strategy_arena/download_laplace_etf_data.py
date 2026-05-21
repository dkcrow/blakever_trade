#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载七星拉普拉斯高斯策略所需ETF的前复权数据（2016-2026，10年）
使用腾讯财经API（避免yfinance限流）
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime

# 聚宽原版7只ETF
ETF_LIST = [
    '518880',  # 黄金ETF
    '159980',  # 有色ETF
    '159985',  # 豆粕ETF
    '501018',  # 南方原油
    '161226',  # 白银LOF
    '159981',  # 能源化工ETF
    '513100',  # 纳指ETF
]

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

def download_tencent_kline(code, start_date='2016-01-01', end_date='2026-05-20'):
    """
    使用腾讯财经API下载K线数据
    code: 6位ETF代码，如518880
    """
    # 判断市场：5开头=上海，1开头=深圳
    if code.startswith('5') or code.startswith('6'):
        market = 'sh'
    else:
        market = 'sz'
    
    # 腾讯API
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    params = {
        'param': f'{market}{code},day,,,2500,{start_date},{end_date},qfq',
        '_var': 'kline_dayqfq'
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f'  ✗ HTTP {resp.status_code}')
            return None
        
        # 解析响应（JSONP格式）
        text = resp.text
        if 'kline_dayqfq=' in text:
            json_str = text.split('kline_dayqfq=')[1]
            import json
            data = json.loads(json_str)
            
            # 提取K线数据
            if 'data' in data and 'qfqday' in data['data']:
                klines = data['data']['qfqday']
                if not klines:
                    return None
                
                # 转换为DataFrame
                df = pd.DataFrame(klines, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df = df.astype(float)
                df = df[['open', 'high', 'low', 'close', 'volume']]
                
                return df
    except Exception as e:
        print(f'  ✗ {e}')
        return None

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    print("="*80)
    print("下载七星拉普拉斯高斯ETF数据（2016-2026，前复权）")
    print("="*80)
    
    for code in ETF_LIST:
        print(f"\n下载 {code}...")
        df = download_tencent_kline(code)
        
        if df is not None and len(df) > 100:
            # 保存
            save_path = os.path.join(DATA_DIR, f'{code}.csv')
            df.to_csv(save_path, encoding='utf-8-sig')
            print(f"  ✓ 成功: {len(df)}行 ({df.index[0].date()} ~ {df.index[-1].date()})")
            print(f"  保存到: {save_path}")
        else:
            print(f"  ✗ 失败或数据不足")
        
        time.sleep(1)  # 避免限流
    
    print("\n" + "="*80)
    print("下载完成！")
    print("="*80)

if __name__ == '__main__':
    main()
