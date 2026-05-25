#!/usr/bin/env python3
"""
A股数据扩展脚本 - 将500只中证500成分股数据扩展至2021年起

数据源优先级:
1. 新浪财经API - 稳定可靠，可获取约5年日K线，每只0.3秒
2. yfinance - 备用（可能限流）
3. akshare  - 最后备用

A股代码转换:
  JQData: 000009.XSHE -> 新浪: sz000009
  JQData: 600000.XSHG -> 新浪: sh600000
"""
import os
import sys
import time
import json
import re
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime

BASE_DIR = Path('/data/workspace/back_trader_stocks')
A_STOCK_DIR = BASE_DIR / 'a'
PROGRESS_FILE = BASE_DIR / 'a_stock_extend_progress.json'
LOG_FILE = BASE_DIR / 'a_stock_extend_log.txt'

TARGET_START = '2021-01-01'
SINA_DATALEN = 1350  # 约5年+缓冲


def log(msg):
    """同时输出到控制台和日志文件"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def jqcode_to_sina(code):
    """JQData代码转新浪代码
    000009.XSHE -> sz000009
    600000.XSHG -> sh600000
    """
    parts = code.split('.')
    if len(parts) != 2:
        return None
    num, market = parts
    if market == 'XSHE':
        return f"sz{num}"
    elif market == 'XSHG':
        return f"sh{num}"
    return None


def jqcode_to_yf(code):
    """JQData代码转yfinance代码"""
    parts = code.split('.')
    if len(parts) != 2:
        return None
    num, market = parts
    if market == 'XSHE':
        return f"{num}.SZ"
    elif market == 'XSHG':
        return f"{num}.SS"
    return None


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def save_df_to_csv(df, csv_path):
    """将DataFrame保存为标准CSV格式: Date,Open,High,Low,Close,Volume"""
    if df is None or df.empty:
        return False

    df = df.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()

    # 找日期列
    date_col = None
    for col in df.columns:
        if col.lower() in ('date', 'day', 'index'):
            date_col = col
            break

    if date_col is None:
        return False

    # 标准化列名
    col_map = {}
    for col in df.columns:
        cl = col.lower()
        if cl in (date_col.lower(), 'day'):
            col_map[col] = 'Date'
        elif cl == 'open':
            col_map[col] = 'Open'
        elif cl == 'high':
            col_map[col] = 'High'
        elif cl == 'low':
            col_map[col] = 'Low'
        elif cl in ('close', 'last', 'price'):
            col_map[col] = 'Close'
        elif cl == 'volume':
            col_map[col] = 'Volume'

    df = df.rename(columns=col_map)

    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    df = df[[c for c in keep_cols if c in df.columns]]

    df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last')
    df.to_csv(csv_path, index=False)
    return True


def merge_with_existing(existing_csv, new_df):
    """将新获取的数据与已有CSV合并"""
    if not existing_csv.exists():
        return new_df

    existing_df = pd.read_csv(existing_csv)
    if existing_df.empty:
        return new_df

    for col in ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']:
        if col not in existing_df.columns:
            return new_df

    existing_df['Date'] = pd.to_datetime(existing_df['Date']).dt.strftime('%Y-%m-%d')

    new_copy = new_df.copy()
    if isinstance(new_copy.index, pd.DatetimeIndex):
        new_copy = new_copy.reset_index()

    # 标准化new_copy列名
    col_map = {}
    for col in new_copy.columns:
        cl = col.lower()
        if cl in ('date', 'day', 'index'):
            col_map[col] = 'Date'
        elif cl == 'open':
            col_map[col] = 'Open'
        elif cl == 'high':
            col_map[col] = 'High'
        elif cl == 'low':
            col_map[col] = 'Low'
        elif cl in ('close', 'last', 'price'):
            col_map[col] = 'Close'
        elif cl == 'volume':
            col_map[col] = 'Volume'
    new_copy = new_copy.rename(columns=col_map)

    if 'Date' in new_copy.columns:
        new_copy['Date'] = pd.to_datetime(new_copy['Date']).dt.strftime('%Y-%m-%d')

    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    existing_df = existing_df[[c for c in keep_cols if c in existing_df.columns]]
    new_copy = new_copy[[c for c in keep_cols if c in new_copy.columns]]

    # 合并：同日数据以新数据为准
    merged = pd.concat([existing_df, new_copy]).drop_duplicates(subset='Date', keep='last')
    merged = merged.sort_values('Date').reset_index(drop=True)
    return merged


def fetch_sina(sina_code, max_retries=2):
    """通过新浪财经API获取A股日K线数据（约5年）"""
    url = 'https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData'
    params = {
        'symbol': sina_code,
        'scale': '240',      # 日K
        'ma': 'no',
        'datalen': str(SINA_DATALEN),
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn',
    }

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            match = re.search(r'\((\[.*\])\)', resp.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                if data:
                    df = pd.DataFrame(data)
                    # 新浪返回: day, open, high, low, close, volume
                    return df
            # 解析失败或空数据
            return None
        except requests.exceptions.ConnectionError:
            log(f"    [新浪连接错误] {sina_code} 重试{attempt+1}/{max_retries}")
            time.sleep(5)
        except Exception as e:
            log(f"    [新浪错误] {sina_code}: {e}")
            return None
    
    return "RATE_LIMITED"


def fetch_yfinance(yf_symbol, max_retries=1):
    """通过yfinance获取K线数据（备用）"""
    import yfinance as yf
    
    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(start=TARGET_START, end='2026-04-25', interval='1d')
            if df is not None and not df.empty:
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                df.index.name = 'Date'
                return df
            return None
        except Exception as e:
            err_str = str(e)
            if 'Rate' in err_str or '429' in err_str or 'Too Many' in err_str:
                log(f"    [yfinance限流] {yf_symbol}")
                return "RATE_LIMITED"
            else:
                log(f"    [yfinance错误] {yf_symbol}: {e}")
                return None
    return None


def main():
    log("=" * 60)
    log("A股数据扩展脚本 - 扩展至2021年起")
    log(f"主数据源: 新浪财经API (约5年日K线)")
    log(f"备用数据源: yfinance, akshare")
    log(f"目标: 数据起始日期 <= {TARGET_START}")
    log("=" * 60)

    # 收集所有需要扩展的A股文件
    csv_files = sorted(A_STOCK_DIR.glob('*.csv'))
    need_extend = []
    already_done = []

    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path)
            if 'Date' in df.columns and not df.empty:
                first_date = pd.to_datetime(df['Date'].min())
                if first_date <= pd.Timestamp('2021-02-01'):
                    already_done.append(csv_path.name)
                else:
                    stem = csv_path.stem
                    jq_code = stem.replace('_', '.', 1)
                    need_extend.append({
                        'csv_path': csv_path,
                        'jq_code': jq_code,
                        'sina_code': jqcode_to_sina(jq_code),
                        'yf_code': jqcode_to_yf(jq_code),
                        'current_start': first_date.strftime('%Y-%m-%d')
                    })
        except Exception as e:
            log(f"  读取 {csv_path.name} 失败: {e}")

    log(f"总文件数: {len(csv_files)}")
    log(f"已满足(从2021年起): {len(already_done)}")
    log(f"需要扩展: {len(need_extend)}")

    if not need_extend:
        log("🎉 所有A股数据已从2021年起，无需扩展！")
        return True  # 返回True表示全部完成

    progress = load_progress()
    success_count = 0
    skip_count = 0
    fail_count = 0
    rate_limited = False

    for i, item in enumerate(need_extend):
        task_key = f"extend_{item['jq_code']}"
        csv_path = item['csv_path']
        jq_code = item['jq_code']
        sina_code = item['sina_code']

        # 跳过已完成的
        if progress.get(task_key) == 'success':
            skip_count += 1
            continue

        if sina_code is None:
            continue

        log(f"[{i+1}/{len(need_extend)}] {jq_code} -> {sina_code} (当前从{item['current_start']}开始)")

        # 主数据源: 新浪财经
        sina_result = fetch_sina(sina_code)

        if isinstance(sina_result, str) and sina_result == "RATE_LIMITED":
            log(f"  *** 新浪API限流，停止本轮 ***")
            rate_limited = True
            break

        if sina_result is not None and isinstance(sina_result, pd.DataFrame) and not sina_result.empty:
            merged = merge_with_existing(csv_path, sina_result)
            save_df_to_csv(merged, csv_path)

            # 验证
            verify_df = pd.read_csv(csv_path)
            new_start = verify_df['Date'].min()
            new_rows = len(verify_df)
            log(f"  ✓ 扩展成功: {new_start} ~ {verify_df['Date'].max()} ({new_rows} rows)")

            success_count += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            # 新浪无数据，尝试yfinance备用
            log(f"  新浪无数据，尝试yfinance...")
            yf_result = fetch_yfinance(item['yf_code'])

            if isinstance(yf_result, str) and yf_result == "RATE_LIMITED":
                log(f"  *** yfinance限流，停止本轮 ***")
                rate_limited = True
                break

            if yf_result is not None and isinstance(yf_result, pd.DataFrame) and not yf_result.empty:
                merged = merge_with_existing(csv_path, yf_result)
                save_df_to_csv(merged, csv_path)
                verify_df = pd.read_csv(csv_path)
                new_start = verify_df['Date'].min()
                log(f"  ✓ yfinance扩展成功: {new_start} ~ {verify_df['Date'].max()} ({len(verify_df)} rows)")
                success_count += 1
                progress[task_key] = 'success'
                save_progress(progress)
            else:
                log(f"  ✗ 所有数据源均失败")
                fail_count += 1
                progress[task_key] = 'fail'
                save_progress(progress)

        # 新浪API请求间隔1秒即可（比yfinance快得多）
        time.sleep(1)

    # 汇总
    log("=" * 60)
    log(f"本轮汇总: 成功={success_count}, 跳过={skip_count}, 失败={fail_count}")

    # 统计整体进度
    from_2021 = 0
    not_from_2021 = 0
    for csv_path in A_STOCK_DIR.glob('*.csv'):
        try:
            df = pd.read_csv(csv_path)
            if 'Date' in df.columns and not df.empty:
                if pd.to_datetime(df['Date'].min()) <= pd.Timestamp('2021-02-01'):
                    from_2021 += 1
                else:
                    not_from_2021 += 1
        except:
            pass

    log(f"整体进度: 已从2021年起={from_2021}/{from_2021+not_from_2021}, 仍需扩展={not_from_2021}")
    
    if not_from_2021 == 0:
        log("🎉 所有A股数据已扩展至2021年起！")
        return True  # 全部完成
    elif rate_limited:
        log("⚠️  遇到限流，等待1小时后自动重试")
    return False


if __name__ == '__main__':
    completed = main()
    if completed:
        print("ALL_DONE")
