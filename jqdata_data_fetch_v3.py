#!/usr/bin/env python3
"""
简化数据获取脚本 - 逐步执行避免限流
"""
import os
import sys
import time
import datetime
import json
import pandas as pd
from pathlib import Path
from jqdatasdk import auth, get_price, get_index_stocks, get_all_securities

JQ_USERNAME = '17665394957'
JQ_PASSWORD = 'Wshqwpsa54565852'
JQ_DATA_START = '2025-01-14'
JQ_DATA_END = '2026-01-21'
TEN_YEAR_START = '2016-04-24'
TODAY = datetime.date.today().strftime('%Y-%m-%d')

BASE_DIR = Path('/data/workspace/back_trader_stocks')
A_STOCK_DIR = BASE_DIR / 'a'
COMMODITY_DIR = BASE_DIR / 'commodity'
HK_DIR = BASE_DIR / 'hk'
US_DIR = BASE_DIR / 'us'
ETF_DIR = BASE_DIR / 'etf'
PROGRESS_FILE = BASE_DIR / 'jqdata_progress_v3.json'

ZZ500_INDEX = '000905.XSHG'


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


def save_df_to_csv(df, csv_path, source='jqdata'):
    """将DataFrame保存为标准CSV格式: Date,Open,High,Low,Close,Volume"""
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
        if cl == date_col.lower():
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
        elif cl in ('money', 'amount'):
            col_map[col] = 'Money'

    df = df.rename(columns=col_map)

    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    df = df[[c for c in keep_cols if c in df.columns]]

    df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last')
    df.to_csv(csv_path, index=False)
    return True


def merge_csv_data(existing_csv, new_df, source_label='yfinance'):
    """将新数据合并到已有CSV"""
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
    if 'Date' in new_copy.columns:
        new_copy['Date'] = pd.to_datetime(new_copy['Date']).dt.strftime('%Y-%m-%d')

    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    existing_df = existing_df[[c for c in keep_cols if c in existing_df.columns]]
    new_copy = new_copy[[c for c in keep_cols if c in new_copy.columns]]

    merged = pd.concat([existing_df, new_copy]).drop_duplicates(subset='Date', keep='last')
    merged = merged.sort_values('Date').reset_index(drop=True)
    return merged


def fetch_yfinance_kline(symbol, start_date, end_date):
    """通过yfinance获取K线数据"""
    import yfinance as yf
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date, interval='1d')
            if df.empty:
                return None
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
            df.index.name = 'Date'
            return df
        except Exception as e:
            if 'Rate' in str(e) or '429' in str(e):
                print(f"    [限流] yfinance retry {attempt+1}/3")
                time.sleep(60)
            else:
                print(f"    [yfinance错误] {e}")
                return None
    return None


def task1_zz500(progress):
    """获取中证500成分股数据，保存到 back_trader_stocks/a/ 目录"""
    print("\n" + "=" * 70)
    print("任务1: 中证500成分股数据获取 (JQData)")
    print("=" * 70)

    stocks = get_index_stocks(ZZ500_INDEX, date='2025-06-01')
    print(f"中证500成分股数量: {len(stocks)}")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, code in enumerate(stocks):
        task_key = f"zz500_{code}"

        if progress.get(task_key) == 'success':
            skip_count += 1
            continue

        csv_path = A_STOCK_DIR / f"{code.replace('.', '_')}.csv"

        # 检查已有数据是否完整
        if csv_path.exists():
            existing_df = pd.read_csv(csv_path)
            if not existing_df.empty and len(existing_df) > 100:
                skip_count += 1
                progress[task_key] = 'success'
                save_progress(progress)
                continue

        df = get_price(code, start_date=JQ_DATA_START, end_date=JQ_DATA_END, frequency='daily')

        if df is not None and not df.empty:
            save_df_to_csv(df, csv_path, 'jqdata')
            rows = len(pd.read_csv(csv_path))
            print(f"  [{i+1}/{len(stocks)}] {code}: OK ({rows} rows)")
            success_count += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            fail_count += 1
            print(f"  [{i+1}/{len(stocks)}] {code}: FAIL")
            progress[task_key] = 'fail'
            save_progress(progress)

        if (i + 1) % 50 == 0:
            print(f"  --- 已处理 {i+1}/{len(stocks)}, 休息2秒 ---")
            time.sleep(2)

    print(f"\n中证500结果: 成功 {success_count}, 跳过 {skip_count}, 失败 {fail_count}")


def task2_us_supplement(progress):
    """补充美股数据至近10年"""
    print("\n" + "=" * 70)
    print("任务2: 美股数据补充至近10年 (yfinance)")
    print("=" * 70)

    csv_files = sorted(US_DIR.glob("*.csv"))
    print(f"美股CSV文件数: {len(csv_files)}")

    success = 0
    skip = 0
    fail = 0

    for i, csv_path in enumerate(csv_files):
        task_key = f"us_supp_{csv_path.stem}"

        try:
            df = pd.read_csv(csv_path)
        except:
            continue

        if df.empty or 'Date' not in df.columns:
            continue

        first_date = df['Date'].min()
        first_dt = pd.to_datetime(first_date)

        if first_dt <= pd.Timestamp(TEN_YEAR_START):
            skip += 1
            continue

        if progress.get(task_key) == 'success':
            skip += 1
            continue

        symbol = csv_path.stem  # e.g., AAPL
        print(f"  [{i+1}/{len(csv_files)}] {symbol} (现有从{first_date}开始)")

        yf_df = fetch_yfinance_kline(symbol, TEN_YEAR_START, first_date)
        if yf_df is not None and not yf_df.empty:
            merged = merge_csv_data(csv_path, yf_df, 'yfinance')
            save_df_to_csv(merged, csv_path, 'yfinance')
            new_rows = len(pd.read_csv(csv_path))
            print(f"    -> 补充成功, 总行数: {new_rows}")
            success += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"    -> yfinance获取失败")
            fail += 1
            progress[task_key] = 'fail'
            save_progress(progress)

        time.sleep(3)  # 增加间隔避免限流

    print(f"\n美股补充结果: 成功 {success}, 跳过 {skip}, 失败 {fail}")


def task2_hk_supplement(progress):
    """补充港股数据至近10年 - 使用yfinance"""
    print("\n" + "=" * 70)
    print("任务2b: 港股数据补充至近10年 (yfinance)")
    print("=" * 70)

    csv_files = sorted(HK_DIR.glob("*.csv"))
    print(f"港股CSV文件数: {len(csv_files)}")

    success = 0
    skip = 0
    fail = 0

    for i, csv_path in enumerate(csv_files):
        task_key = f"hk_supp_{csv_path.stem}"

        try:
            df = pd.read_csv(csv_path)
        except:
            continue

        if df.empty or 'Date' not in df.columns:
            continue

        first_date = df['Date'].min()
        first_dt = pd.to_datetime(first_date)

        if first_dt <= pd.Timestamp(TEN_YEAR_START):
            skip += 1
            continue

        if progress.get(task_key) == 'success':
            skip += 1
            continue

        hk_code = csv_path.stem  # e.g., hk00700
        # 港股代码转换: hk00700 -> 0700.HK (去掉hk前缀，保留4位数字+.HK)
        num_part = hk_code.lower().replace('hk', '')
        yf_symbol = num_part.lstrip('0') + '.HK'  # 0700.HK
        # 如果lstrip后为空，保留原始数字
        if not num_part.lstrip('0'):
            yf_symbol = num_part + '.HK'
        print(f"  [{i+1}/{len(csv_files)}] {hk_code} (现有从{first_date}开始) -> yfinance: {yf_symbol}")

        yf_df = fetch_yfinance_kline(yf_symbol, TEN_YEAR_START, first_date)
        if yf_df is not None and not yf_df.empty:
            merged = merge_csv_data(csv_path, yf_df, 'yfinance')
            save_df_to_csv(merged, csv_path, 'yfinance')
            new_rows = len(pd.read_csv(csv_path))
            print(f"    -> 补充成功, 总行数: {new_rows}")
            success += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"    -> yfinance获取失败")
            fail += 1
            progress[task_key] = 'fail'
            save_progress(progress)

        time.sleep(3)

    print(f"\n港股补充结果: 成功 {success}, 跳过 {skip}, 失败 {fail}")


def task3_commodities(progress):
    """获取黄金/原油/美元/比特币近10年数据"""
    print("\n" + "=" * 70)
    print("任务3: 商品/大类资产数据获取 (yfinance)")
    print("=" * 70)

    COMMODITY_CONFIGS = [
        ('commodity_gold_futures', 'GC=F', 'gold_futures.csv', '黄金期货(GC=F)'),
        ('commodity_gold_etf_gld', 'GLD', 'gold_etf_gld.csv', '黄金ETF(GLD)'),
        ('commodity_oil_wti', 'CL=F', 'oil_wti_futures.csv', 'WTI原油期货(CL=F)'),
        ('commodity_oil_brent', 'BZ=F', 'oil_brent_futures.csv', 'Brent原油期货(BZ=F)'),
        ('commodity_usd_index', 'DX-Y.NYB', 'usd_index.csv', '美元指数(DX-Y.NYB)'),
        ('commodity_usd_etf_uup', 'UUP', 'usd_etf_uup.csv', '美元ETF(UUP)'),
        ('commodity_usdcny', 'CNY=X', 'usdcny.csv', 'USD/CNY汇率(CNY=X)'),
        ('commodity_btc', 'BTC-USD', 'btc_usd.csv', '比特币(BTC-USD)'),
        ('commodity_eth', 'ETH-USD', 'eth_usd.csv', '以太坊(ETH-USD)'),
    ]

    for task_key, yf_symbol, filename, desc in COMMODITY_CONFIGS:
        csv_path = COMMODITY_DIR / filename

        if progress.get(task_key) == 'success':
            if csv_path.exists():
                print(f"  {desc}: 已完成，跳过")
                continue
            else:
                progress.pop(task_key, None)

        print(f"  获取 {desc} ({yf_symbol})...")

        yf_df = fetch_yfinance_kline(yf_symbol, TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            rows = len(pd.read_csv(csv_path))
            print(f"    -> {desc}: OK ({rows} rows)")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"    -> {desc}: yfinance获取失败")
            # 尝试备用
            if yf_symbol == 'DX-Y.NYB':
                print(f"    -> 尝试备用: UUP ETF")
                yf_df2 = fetch_yfinance_kline('UUP', TEN_YEAR_START, TODAY)
                if yf_df2 is not None and not yf_df2.empty:
                    save_df_to_csv(yf_df2, COMMODITY_DIR / 'usd_etf_uup.csv', 'yfinance')
                    rows2 = len(pd.read_csv(COMMODITY_DIR / 'usd_etf_uup.csv'))
                    print(f"    -> 美元ETF(UUP): OK ({rows2} rows)")
                    progress[task_key] = 'success_uup'
                    save_progress(progress)

        time.sleep(3)

    # JQData额外: AU9999现货黄金
    print("\n--- JQData额外数据 ---")
    task_key = 'commodity_au9999'
    if progress.get(task_key) != 'success':
        jq_df = get_price('AU9999.XSGE', start_date=JQ_DATA_START, end_date=JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'gold_au9999.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  AU9999现货黄金: {len(jq_df)} rows")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  AU9999现货黄金: JQData获取失败（试用账号限制）")

    # JQData: 黄金ETF 518880
    task_key = 'commodity_gold_etf_cn'
    if progress.get(task_key) != 'success':
        jq_df = get_price('518880.XSHG', start_date=JQ_DATA_START, end_date=JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'gold_etf_518880.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  黄金ETF(518880): {len(jq_df)} rows")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  黄金ETF(518880): JQData获取失败")

    # JQData: 南方原油LOF
    task_key = 'commodity_oil_lof'
    if progress.get(task_key) != 'success':
        jq_df = get_price('501018.XSHG', start_date=JQ_DATA_START, end_date=JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'oil_lof_501018.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  南方原油LOF(501018): {len(jq_df)} rows")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  南方原油LOF(501018): JQData获取失败")


def task4_fix_etf_volume(progress):
    """修复ETF中Volume=0的问题"""
    print("\n" + "=" * 70)
    print("任务4: 修复ETF Volume=0问题 (yfinance)")
    print("=" * 70)

    csv_files = sorted(ETF_DIR.glob("*.csv"))

    fixed_count = 0
    total_zero = 0
    skip_count = 0

    for csv_path in csv_files:
        df = pd.read_csv(csv_path)
        if df.empty or 'Volume' not in df.columns:
            skip_count += 1
            continue

        zero_count = (df['Volume'] == 0).sum()
        if zero_count == 0:
            continue

        total_zero += zero_count
        symbol = csv_path.stem

        task_key = f"etf_fix_{symbol}"
        if progress.get(task_key) == 'success':
            skip_count += 1
            continue

        yf_df = fetch_yfinance_kline(symbol, df['Date'].min(), df['Date'].max())
        if yf_df is not None and not yf_df.empty:
            merged = merge_csv_data(csv_path, yf_df, 'yfinance')
            save_df_to_csv(merged, csv_path, 'yfinance')
            new_zero = (merged['Volume'] == 0).sum()
            print(f"  {symbol}: 修复 {zero_count - new_zero}/{zero_count} Volume=0行")
            fixed_count += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  {symbol}: yfinance获取失败, {zero_count}个Volume=0未修复")
            progress[task_key] = 'fail'
            save_progress(progress)

        time.sleep(3)

    print(f"\nETF修复结果: 修复 {fixed_count} 个文件, 总Volume=0行数: {total_zero}")


def main():
    print("=" * 70)
    print("简化数据获取脚本 v3")
    print("数据源: JQData(试用) + westock-data + yfinance")
    print("JQData试用账号限制: 仅2025-01-14~2026-01-21")
    print("yfinance可获取近10年数据（可能限流）")
    print("=" * 70)

    # 登录JQData
    try:
        auth(JQ_USERNAME, JQ_PASSWORD)
        print("JQData登录成功")
    except Exception as e:
        print(f"JQData登录失败: {e}")

    progress = load_progress()

    # 执行各任务
    task1_zz500(progress)
    task2_us_supplement(progress)
    task2_hk_supplement(progress)
    task3_commodities(progress)
    task4_fix_etf_volume(progress)

    # 汇总
    print("\n" + "=" * 70)
    print("全部任务完成汇总")
    print("=" * 70)

    for dir_path, label in [(A_STOCK_DIR, 'A股'), (COMMODITY_DIR, '商品'),
                            (HK_DIR, '港股'), (US_DIR, '美股'), (ETF_DIR, 'ETF')]:
        csv_files = list(dir_path.glob("*.csv"))
        total_rows = 0
        for f in csv_files:
            try:
                total_rows += len(pd.read_csv(f))
            except:
                pass
        print(f"  {label}: {len(csv_files)} 个文件, 共 {total_rows} 行数据")

    print(f"\n商品数据目录: {COMMODITY_DIR}")
    commodity_files = list(COMMODITY_DIR.glob("*.csv"))
    for f in sorted(commodity_files):
        try:
            df = pd.read_csv(f)
            first = df['Date'].min()
            last = df['Date'].max()
            print(f"  {f.name}: {len(df)} rows, {first} ~ {last}")
        except:
            print(f"  {f.name}: 读取失败")


if __name__ == '__main__':
    main()
