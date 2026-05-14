#!/usr/bin/env python3
"""
补丁: 补齐48只港股yfinance补充失败的数据
问题: v3脚本用 lstrip('0') 导致 00001->1.HK, 正确应该是 0001.HK (4位数字)
"""
import json
import time
import datetime
import pandas as pd
from pathlib import Path

BASE_DIR = Path('/data/workspace/back_trader_stocks')
HK_DIR = BASE_DIR / 'hk'
PROGRESS_FILE = BASE_DIR / 'jqdata_progress_v3.json'
TEN_YEAR_START = '2016-04-24'


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def save_df_to_csv(df, csv_path):
    if df is None or df.empty:
        return False
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    date_col = None
    for col in df.columns:
        if col.lower() in ('date', 'index'):
            date_col = col
            break
    if date_col is None:
        return False
    col_map = {}
    for col in df.columns:
        cl = col.lower()
        if cl == date_col.lower(): col_map[col] = 'Date'
        elif cl == 'open': col_map[col] = 'Open'
        elif cl == 'high': col_map[col] = 'High'
        elif cl == 'low': col_map[col] = 'Low'
        elif cl in ('close', 'last', 'price'): col_map[col] = 'Close'
        elif cl == 'volume': col_map[col] = 'Volume'
    df = df.rename(columns=col_map)
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    df = df[[c for c in keep_cols if c in df.columns]]
    df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last')
    df.to_csv(csv_path, index=False)
    return True


def merge_csv_data(existing_csv, new_df):
    if not existing_csv.exists():
        return new_df
    existing_df = pd.read_csv(existing_csv)
    if existing_df.empty:
        return new_df
    existing_df['Date'] = pd.to_datetime(existing_df['Date']).dt.strftime('%Y-%m-%d')
    new_copy = new_df.copy()
    if isinstance(new_copy.index, pd.DatetimeIndex):
        new_copy = new_copy.reset_index()
    if 'Date' in new_copy.columns:
        new_copy['Date'] = pd.to_datetime(new_copy['Date']).dt.strftime('%Y-%m-%d')
    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    existing_df = existing_df[[c for c in keep_cols if c in existing_df.columns]]
    new_copy = new_copy[[c for c in keep_cols if c in new_copy.columns]]
    merged = pd.concat([existing_df, new_copy]).drop_duplicates(subset='Date', keep='last')
    merged = merged.sort_values('Date').reset_index(drop=True)
    return merged


def main():
    progress = load_progress()
    fails = {k: v for k, v in progress.items() if k.startswith('hk_supp_') and v == 'fail'}
    print(f"需要补齐的港股: {len(fails)} 只")

    import yfinance as yf

    success = 0
    still_fail = 0

    for i, (task_key, _) in enumerate(fails.items()):
        hk_code = task_key.replace('hk_supp_', '')  # e.g., hk00001
        num_part = hk_code.lower().replace('hk', '')  # e.g., 00001
        # 正确格式: 4位数字.HK (yfinance港股代码标准)
        # 00001 -> 取后4位 -> 0001.HK
        four_digit = num_part[-4:]  # 取后4位
        yf_symbol = four_digit + '.HK'  # e.g., 0001.HK

        csv_path = HK_DIR / f"{hk_code}.csv"
        if not csv_path.exists():
            print(f"  [{i+1}/{len(fails)}] {hk_code}: CSV文件不存在，跳过")
            continue

        df = pd.read_csv(csv_path)
        if df.empty or 'Date' not in df.columns:
            continue

        first_date = df['Date'].min()
        first_dt = pd.to_datetime(first_date)

        if first_dt <= pd.Timestamp(TEN_YEAR_START):
            progress[task_key] = 'success'
            save_progress(progress)
            continue

        print(f"  [{i+1}/{len(fails)}] {hk_code} -> yfinance: {yf_symbol} (现有从{first_date}开始)")

        for attempt in range(3):
            try:
                ticker = yf.Ticker(yf_symbol)
                yf_df = ticker.history(start=TEN_YEAR_START, end=first_date, interval='1d')
                if yf_df is not None and not yf_df.empty:
                    yf_df = yf_df[['Open', 'High', 'Low', 'Close', 'Volume']]
                    yf_df.index.name = 'Date'
                    merged = merge_csv_data(csv_path, yf_df)
                    save_df_to_csv(merged, csv_path)
                    new_rows = len(pd.read_csv(csv_path))
                    print(f"    -> 补充成功, 总行数: {new_rows}")
                    success += 1
                    progress[task_key] = 'success'
                    save_progress(progress)
                    break
                else:
                    print(f"    -> yfinance返回空数据")
                    if attempt < 2:
                        time.sleep(30)
            except Exception as e:
                if 'Rate' in str(e) or '429' in str(e):
                    print(f"    [限流] retry {attempt+1}/3, 等待120s")
                    time.sleep(120)
                else:
                    print(f"    [错误] {e}")
                    break
        else:
            still_fail += 1
            print(f"    -> 3次重试仍失败")

        time.sleep(15)

    print(f"\n补齐结果: 成功 {success}, 仍失败 {still_fail}")


if __name__ == '__main__':
    main()
