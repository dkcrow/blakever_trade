#!/usr/bin/env python3
"""
美股市场行情研判脚本
- SPX数据: westock-data (通过CLI获取，本脚本解析stdin或文件)
- VIX数据: yfinance降级获取
- 调用 analyze_market_with_confirmation() 进行研判
"""

import sys
import os
import json
import pandas as pd

# 确保能引用同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_info import standardize_ohlcv
from market_analyze import analyze_market_with_confirmation


def parse_westock_kline(raw_text: str) -> pd.DataFrame:
    """解析westock-data kline命令输出的Markdown表格"""
    lines = raw_text.strip().split('\n')
    # 找到表头行
    header_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('|') and 'date' in line.lower():
            header_idx = i
            break
    
    if header_idx < 0:
        raise ValueError("无法找到K线数据表头")
    
    # 解析表头
    headers = [h.strip() for h in lines[header_idx].split('|') if h.strip()]
    
    # 解析数据行（跳过分隔行）
    rows = []
    for line in lines[header_idx + 2:]:  # 跳过表头和分隔行
        if not line.strip() or not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if len(cells) == len(headers):
            rows.append(cells)
    
    df = pd.DataFrame(rows, columns=headers)
    
    # 重命名列: last -> close
    if 'last' in df.columns and 'close' not in df.columns:
        df = df.rename(columns={'last': 'close'})
    
    # 转换数据类型
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
    
    return df


def fetch_vix_cboe() -> pd.DataFrame:
    """
    从CBOE官网获取VIX指数历史数据。
    数据源: https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
    """
    import urllib.request
    import io
    
    url = 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode('utf-8')
    except Exception as e:
        raise ValueError(f"CBOE VIX数据获取失败: {e}")
    
    # 解析CSV
    df = pd.read_csv(io.StringIO(content))
    df = df.rename(columns={
        'DATE': 'date',
        'OPEN': 'open',
        'HIGH': 'high',
        'LOW': 'low',
        'CLOSE': 'close',
    })
    
    # CBOE日期格式: MM/DD/YYYY
    df['date'] = pd.to_datetime(df['date'], format='%m/%d/%Y')
    df['volume'] = 0  # VIX指数无成交量
    
    # 只保留需要的列
    keep_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    df = df[keep_cols]
    df = df.sort_values('date').reset_index(drop=True)
    
    # 只保留最近130个交易日（足够覆盖SPX的时间范围）
    if len(df) > 130:
        df = df.iloc[-130:].reset_index(drop=True)
    
    return df


def main():
    # 1. 读取SPX K线数据（从文件或stdin）
    spx_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'spx_kline_raw.txt')
    if os.path.exists(spx_file):
        with open(spx_file, 'r', encoding='utf-8') as f:
            raw_spx = f.read()
    else:
        print("错误: 未找到SPX K线数据文件，请先运行获取脚本")
        sys.exit(1)
    
    print(f"[INFO] 解析SPX K线数据...")
    spx_df = parse_westock_kline(raw_spx)
    print(f"[INFO] SPX数据行数: {len(spx_df)}, 日期范围: {spx_df['date'].iloc[0]} ~ {spx_df['date'].iloc[-1]}")
    
    # 2. 标准化SPX数据（含技术指标计算）
    print(f"[INFO] 标准化SPX数据并计算技术指标...")
    spx_std = standardize_ohlcv(spx_df, symbol='SPX', add_indicators=True)
    print(f"[INFO] 标准化后列: {list(spx_std.columns)}")
    
    # 打印最新指标值用于验证
    latest = spx_std.iloc[-1]
    print(f"[INFO] 最新数据日期: {latest.get('date', 'N/A')}")
    print(f"[INFO] Close={latest['close']:.2f}, MA20={latest.get('ma20', 0):.2f}, MA60={latest.get('ma60', 0):.2f}, MA120={latest.get('ma120', 0):.2f}")
    print(f"[INFO] ADX14={latest.get('adx14', 0):.2f}, RSI14={latest.get('rsi14', 0):.2f}, Volatility20={latest.get('volatility20', 0):.4f}")
    
    # 3. 获取VIX数据
    print(f"[INFO] 通过CBOE官网获取VIX数据...")
    vix_df = fetch_vix_cboe()
    vix_source = 'CBOE'
    print(f"[INFO] VIX数据行数: {len(vix_df)}, 日期范围: {vix_df['date'].iloc[0]} ~ {vix_df['date'].iloc[-1]}")
    print(f"[INFO] 最新VIX: {vix_df.iloc[-1]['close']:.2f}")
    
    # 4. 调用带确认期防抖的市场研判
    print(f"\n[INFO] 调用 analyze_market_with_confirmation()...")
    result = analyze_market_with_confirmation(spx_std, vix_df)
    
    # 5. 输出结果
    print(f"\n{'='*60}")
    print(f"市场行情研判结果")
    print(f"{'='*60}")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    
    return result


if __name__ == '__main__':
    main()
