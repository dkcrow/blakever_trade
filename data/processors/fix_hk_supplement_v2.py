#!/usr/bin/env python3
"""
用westock-data补齐港股数据（替代yfinance，避免限流）
westock-data港股最多2000条日K线（约8年）
"""
import json
import time
import subprocess
import datetime
import pandas as pd
from pathlib import Path

BASE_DIR = Path('/data/workspace/back_trader_stocks')
HK_DIR = BASE_DIR / 'hk'
PROGRESS_FILE = BASE_DIR / 'jqdata_progress_v3.json'
WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'
TEN_YEAR_START = '2016-04-24'


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def fetch_westock_kline(code, limit=2000):
    """通过westock-data获取K线数据"""
    try:
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT, 'kline', code, 'day', str(limit)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None

        lines = result.stdout.strip().split('\n')
        if len(lines) < 3:
            return None

        # 解析markdown表格格式
        header_line = lines[0]
        data_lines = [l for l in lines[2:] if l.strip() and not l.startswith('| ---')]

        if not data_lines:
            return None

        # 解析表头
        headers = [h.strip() for h in header_line.split('|') if h.strip()]

        rows = []
        for line in data_lines:
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if len(cells) >= 6:
                rows.append(cells)

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=headers[:len(rows[0])])

        # 标准化列名
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if cl == 'date': col_map[col] = 'Date'
            elif cl == 'open': col_map[col] = 'Open'
            elif cl in ('last', 'close', 'price'): col_map[col] = 'Close'
            elif cl == 'high': col_map[col] = 'High'
            elif cl == 'low': col_map[col] = 'Low'
            elif cl == 'volume': col_map[col] = 'Volume'

        df = df.rename(columns=col_map)

        # 转换数据类型
        for col in ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df.columns:
                if col == 'Date':
                    df[col] = pd.to_datetime(df[col]).dt.strftime('%Y-%m-%d')
                else:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

        keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        df = df[[c for c in keep_cols if c in df.columns]]

        df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last').reset_index(drop=True)
        return df

    except Exception as e:
        print(f"    [westock错误] {e}")
        return None


def save_df_to_csv(df, csv_path):
    if df is None or df.empty:
        return False
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

    # 同时检查所有港股数据，对不足10年的也补充
    csv_files = sorted(HK_DIR.glob("*.csv"))
    need_supplement = []

    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path)
        except:
            continue
        if df.empty or 'Date' not in df.columns:
            continue
        first_date = df['Date'].min()
        first_dt = pd.to_datetime(first_date)
        if first_dt > pd.Timestamp(TEN_YEAR_START):
            hk_code = csv_path.stem
            task_key = f"hk_supp_{hk_code}"
            if progress.get(task_key) != 'success':
                need_supplement.append((hk_code, csv_path, first_date))

    print(f"需要补充至近10年的港股: {len(need_supplement)} 只")

    success = 0
    skip = 0
    fail = 0

    for i, (hk_code, csv_path, first_date) in enumerate(need_supplement):
        task_key = f"hk_supp_{hk_code}"

        print(f"  [{i+1}/{len(need_supplement)}] {hk_code} (现有从{first_date}开始)")

        # 用westock-data获取最多2000条
        ws_df = fetch_westock_kline(hk_code, limit=2000)
        if ws_df is not None and not ws_df.empty:
            merged = merge_csv_data(csv_path, ws_df)
            save_df_to_csv(merged, csv_path)
            new_rows = len(pd.read_csv(csv_path))
            new_first = pd.read_csv(csv_path)['Date'].min()
            print(f"    -> 补充成功, 总行数: {new_rows}, 数据从 {new_first} 开始")
            success += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"    -> westock-data获取失败")
            fail += 1
            progress[task_key] = 'fail'
            save_progress(progress)

        time.sleep(0.5)  # westock-data请求间隔短

    print(f"\n港股补齐结果: 成功 {success}, 跳过 {skip}, 失败 {fail}")


if __name__ == '__main__':
    main()
