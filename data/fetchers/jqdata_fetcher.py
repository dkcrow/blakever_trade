#!/usr/bin/env python3
"""
综合数据补充脚本：JQData + westock-data + yfinance 多源数据融合

任务1: 中证500成分股数据（JQData 试用账号范围：2025-01-14 ~ 2026-01-21）
任务2: 港美股现有股票池补充至近10年（westock-data + yfinance）
任务3: 黄金/原油/美元/比特币数据（JQData + yfinance 多源）
任务4: 用JQData修复港股成交量（Volume=0）问题

数据源能力：
- JQData试用账号: 仅限2025-01-14~2026-01-21, 支持A股/期货/ETF, 不支持港股/美股
- westock-data: 港股/美股, 最多2000条日线
- yfinance: 全球市场, 无严格限制, 但可能被限流

输出格式：Date,Open,High,Low,Close,Volume
"""

import os
import sys
import time
import datetime
import json
import subprocess
import pandas as pd
from pathlib import Path
from jqdatasdk import auth, get_price, get_index_stocks, get_all_securities

# ============================================================
# 配置
# ============================================================

# JQData账号
JQ_USERNAME = '17665394957'
JQ_PASSWORD = 'Wshqwpsa54565852'
JQ_DATA_START = '2025-01-14'
JQ_DATA_END = '2026-01-21'

# 近10年起始日期
TEN_YEAR_START = '2016-04-24'
TODAY = datetime.date.today().strftime('%Y-%m-%d')

# 输出目录
BASE_DIR = Path('/data/workspace/back_trader_stocks')
A_STOCK_DIR = BASE_DIR / 'a'          # A股数据
COMMODITY_DIR = BASE_DIR / 'commodity' # 商品数据(黄金/原油等)
HK_DIR = BASE_DIR / 'hk'
US_DIR = BASE_DIR / 'us'

# 创建目录
for d in [A_STOCK_DIR, COMMODITY_DIR, HK_DIR, US_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# westock-data脚本路径
WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'

# 进度文件
PROGRESS_FILE = BASE_DIR / 'jqdata_progress.json'

# yfinance限流配置
YFINANCE_RETRY_DELAY = 30
YFINANCE_MAX_RETRIES = 2

# 中证500指数代码
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


def jq_login():
    """登录JQData"""
    auth(JQ_USERNAME, JQ_PASSWORD)
    print("JQData登录成功")


def save_df_to_csv(df, csv_path, source='jqdata'):
    """将DataFrame保存为标准CSV格式: Date,Open,High,Low,Close,Volume[,VolumeSource]"""
    if df is None or df.empty:
        return False

    # 重置索引使Date变成列
    if df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()

    # 查找Date列
    date_col = None
    for col in ['Date', 'date', 'index']:
        if col in df.columns:
            date_col = col
            break

    if date_col is None:
        print(f"  [WARN] 找不到日期列: {list(df.columns)}")
        return False

    # 标准化列名
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

    # 格式化Date
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    # 只保留标准列
    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    if 'VolumeSource' in df.columns:
        keep_cols.append('VolumeSource')
    df = df[[c for c in keep_cols if c in df.columns]]

    # 按日期排序
    df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last')

    # 写入CSV
    df.to_csv(csv_path, index=False)
    return True


def fetch_jq_kline(code, start_date, end_date):
    """通过JQData获取K线数据"""
    try:
        df = get_price(code, start_date=start_date, end_date=end_date, frequency='daily')
        if df is not None and not df.empty:
            df.index.name = 'Date'
            return df
    except Exception as e:
        err = str(e)
        if '权限' in err or '时间' in err:
            print(f"  [JQ权限] {code}: {err[:80]}")
        else:
            print(f"  [JQ错误] {code}: {err[:80]}")
    return None


def fetch_yfinance_kline(symbol, start_date, end_date):
    """通过yfinance获取K线数据"""
    try:
        import yfinance as yf
    except ImportError:
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'yfinance', '-q'], check=True)
        import yfinance as yf

    for attempt in range(YFINANCE_MAX_RETRIES):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date, interval='1d')
            if df.empty:
                return None
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
            df.index.name = 'Date'
            # 过滤掉Volume=0的行（美股可能有些异常数据）
            return df
        except Exception as e:
            if 'Rate' in str(e) or '429' in str(e):
                print(f"    [限流] yfinance retry {attempt+1}/{YFINANCE_MAX_RETRIES}")
                time.sleep(YFINANCE_RETRY_DELAY)
            else:
                print(f"    [yfinance错误] {e}")
                return None
    return None


def merge_csv_data(existing_csv, new_df, source_label='jqdata'):
    """将新数据合并到已有CSV，填充缺失区间，避免重复
    
    策略：
    1. 读取已有CSV
    2. 将新数据转为相同格式
    3. 按Date合并，新数据优先（覆盖旧数据的Volume=0等问题）
    4. 去重、排序
    """
    if not existing_csv.exists():
        return new_df

    existing_df = pd.read_csv(existing_csv)
    if existing_df.empty:
        return new_df

    # 标准化现有数据
    for col in ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']:
        if col not in existing_df.columns:
            return new_df

    existing_df['Date'] = pd.to_datetime(existing_df['Date']).dt.strftime('%Y-%m-%d')

    # 标准化新数据
    new_copy = new_df.copy()
    if isinstance(new_copy.index, pd.DatetimeIndex):
        new_copy = new_copy.reset_index()
    if 'Date' in new_copy.columns:
        new_copy['Date'] = pd.to_datetime(new_copy['Date']).dt.strftime('%Y-%m-%d')
    elif 'index' in new_copy.columns:
        new_copy = new_copy.rename(columns={'index': 'Date'})
        new_copy['Date'] = pd.to_datetime(new_copy['Date']).dt.strftime('%Y-%m-%d')

    # 合并
    keep_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    existing_df = existing_df[[c for c in keep_cols if c in existing_df.columns]]
    new_copy = new_copy[[c for c in keep_cols if c in new_copy.columns]]

    # 使用新数据覆盖旧数据中同日期的行（修复Volume等问题）
    merged = pd.concat([existing_df, new_copy]).drop_duplicates(subset='Date', keep='last')
    merged = merged.sort_values('Date').reset_index(drop=True)

    return merged


# ============================================================
# 任务1: 中证500成分股数据
# ============================================================

def task1_zz500(progress):
    """获取中证500成分股数据，保存到 back_trader_stocks/a/ 目录"""
    print("\n" + "=" * 70)
    print("任务1: 中证500成分股数据获取")
    print("=" * 70)

    # 获取成分股列表
    try:
        stocks = get_index_stocks(ZZ500_INDEX, date='2025-06-01')
        print(f"中证500成分股数量: {len(stocks)}")
    except Exception as e:
        print(f"获取中证500成分股失败: {e}")
        return

    success_count = 0
    skip_count = 0
    fail_count = 0
    failed_list = []

    for i, code in enumerate(stocks):
        task_key = f"zz500_{code}"

        # 断点续传
        if progress.get(task_key) == 'success':
            skip_count += 1
            continue

        csv_path = A_STOCK_DIR / f"{code.replace('.', '_')}.csv"

        # 获取JQData数据（试用账号限制范围）
        df = fetch_jq_kline(code, JQ_DATA_START, JQ_DATA_END)

        if df is not None and not df.empty:
            # 如果已有数据，合并
            if csv_path.exists():
                merged = merge_csv_data(csv_path, df, 'jqdata')
                save_df_to_csv(merged, csv_path, 'jqdata')
            else:
                save_df_to_csv(df, csv_path, 'jqdata')

            rows = len(pd.read_csv(csv_path))
            print(f"  [{i+1}/{len(stocks)}] {code}: OK ({rows} rows)")
            success_count += 1
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            fail_count += 1
            failed_list.append(code)
            print(f"  [{i+1}/{len(stocks)}] {code}: FAIL")
            progress[task_key] = 'fail'
            save_progress(progress)

        # JQData限流：每50个暂停一下
        if (i + 1) % 50 == 0:
            print(f"  --- 已处理 {i+1}/{len(stocks)}, 休息2秒 ---")
            time.sleep(2)

    print(f"\n中证500结果: 成功 {success_count}, 跳过 {skip_count}, 失败 {fail_count}")
    if failed_list:
        print(f"失败标的(前20): {failed_list[:20]}")


# ============================================================
# 任务2: 港美股补充至近10年
# ============================================================

def run_westock_cmd(args, timeout=120):
    """运行westock-data CLI命令"""
    cmd = ["node", WESTOCK_SCRIPT] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (result.returncode == 0, result.stdout)
    except subprocess.TimeoutExpired:
        return (False, "TIMEOUT")
    except Exception as e:
        return (False, str(e))


def parse_westock_kline(markdown_text, symbol):
    """解析westock-data kline返回的Markdown表格"""
    lines = markdown_text.strip().split("\n")
    records = []
    in_data = False

    for line in lines:
        line = line.strip()
        if not line or line.startswith("| ---") or line.startswith("| symbol") or line.startswith("| date"):
            if line.startswith("| symbol") or line.startswith("| date"):
                in_data = True
            continue
        if not in_data:
            continue

        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 7:
            continue

        try:
            first_col = parts[0]
            has_symbol_col = not (len(first_col) >= 10 and "-" in first_col)

            if has_symbol_col and len(parts) >= 8:
                date_str = parts[1]
                open_val = float(parts[2])
                close_val = float(parts[3])
                high_val = float(parts[4])
                low_val = float(parts[5])
                vol_raw = parts[6]
            else:
                date_str = parts[0]
                open_val = float(parts[1])
                close_val = float(parts[2])
                high_val = float(parts[3])
                low_val = float(parts[4])
                vol_raw = parts[5]

            records.append({
                "Date": date_str,
                "Open": open_val,
                "High": high_val,
                "Low": low_val,
                "Close": close_val,
                "Volume": int(float(vol_raw)) if vol_raw not in ("0", "") else 0,
            })
        except (ValueError, IndexError):
            continue

    return records


def task2_hk_supplement(progress):
    """补充港股数据至近10年 - 用yfinance获取更早期数据"""
    print("\n" + "=" * 70)
    print("任务2a: 港股数据补充至近10年")
    print("=" * 70)

    csv_files = sorted(HK_DIR.glob("*.csv"))
    print(f"港股CSV文件数: {len(csv_files)}")

    success = 0
    skip = 0
    fail = 0

    for i, csv_path in enumerate(csv_files):
        task_key = f"hk_supp_{csv_path.stem}"

        # 读取现有数据
        try:
            df = pd.read_csv(csv_path)
        except:
            continue

        if df.empty or 'Date' not in df.columns:
            continue

        # 检查数据起始日期
        first_date = df['Date'].min()
        first_dt = pd.to_datetime(first_date)

        # 如果数据已经够10年，跳过
        if first_dt <= pd.Timestamp(TEN_YEAR_START):
            skip += 1
            continue

        # 断点续传
        if progress.get(task_key) == 'success':
            skip += 1
            continue

        # 用yfinance补充更早期数据
        # 港股代码转换: hk00700 -> 0700.HK
        symbol = csv_path.stem
        if symbol.startswith('hk'):
            yf_symbol = symbol[2:] + '.HK'
            # 补零: 700 -> 0700
            num_part = symbol[2:]
            yf_symbol = num_part.zfill(4) + '.HK'
        else:
            yf_symbol = symbol + '.HK'

        print(f"  [{i+1}/{len(csv_files)}] {symbol} (现有从{first_date}开始) -> 用yfinance补充...")

        yf_df = fetch_yfinance_kline(yf_symbol, TEN_YEAR_START, first_date)
        if yf_df is not None and not yf_df.empty:
            # 合并数据
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

        time.sleep(1)  # yfinance限流

    print(f"\n港股补充结果: 成功 {success}, 跳过 {skip}, 失败 {fail}")


def task2_us_supplement(progress):
    """补充美股数据至近10年 - 用yfinance获取更早期数据"""
    print("\n" + "=" * 70)
    print("任务2b: 美股数据补充至近10年")
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

        symbol = csv_path.stem
        yf_symbol = symbol  # 美股直接用代码

        print(f"  [{i+1}/{len(csv_files)}] {symbol} (现有从{first_date}开始) -> 用yfinance补充...")

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

        time.sleep(1)

    print(f"\n美股补充结果: 成功 {success}, 跳过 {skip}, 失败 {fail}")


# ============================================================
# 任务3: 黄金/原油/美元/比特币数据
# ============================================================

def task3_commodities(progress):
    """获取黄金、原油、美元、比特币近10年数据"""
    print("\n" + "=" * 70)
    print("任务3: 商品/大类资产数据获取（黄金/原油/美元/比特币）")
    print("=" * 70)

    # ========== 黄金 ==========
    # 方案1: yfinance获取国际金价 (GC=F 黄金期货, GLD ETF)
    # 方案2: JQData获取AU9999现货黄金 (仅2025-01-14~2026-01-21)
    print("\n--- 黄金 ---")

    # 3a: yfinance - 黄金期货连续合约
    task_key = "commodity_gold_futures"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('GC=F', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'gold_futures.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  黄金期货(GC=F): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  黄金期货(GC=F): yfinance获取失败")
    else:
        print(f"  黄金期货: 已完成，跳过")

    # 3b: yfinance - 黄金ETF (GLD)
    task_key = "commodity_gold_etf"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('GLD', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'gold_etf_gld.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  黄金ETF(GLD): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  黄金ETF(GLD): yfinance获取失败")
    else:
        print(f"  黄金ETF: 已完成，跳过")

    # 3c: JQData - AU9999现货黄金
    task_key = "commodity_au9999"
    if progress.get(task_key) != 'success':
        jq_df = fetch_jq_kline('AU9999.XSGE', JQ_DATA_START, JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'gold_au9999.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  AU9999现货黄金: {len(jq_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  AU9999现货黄金: JQData获取失败")
    else:
        print(f"  AU9999: 已完成，跳过")

    # 3d: JQData - 黄金ETF 518880
    task_key = "commodity_gold_etf_cn"
    if progress.get(task_key) != 'success':
        jq_df = fetch_jq_kline('518880.XSHG', JQ_DATA_START, JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'gold_etf_518880.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  黄金ETF(518880): {len(jq_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  黄金ETF(518880): JQData获取失败")
    else:
        print(f"  黄金ETF(518880): 已完成，跳过")

    # ========== 原油 ==========
    print("\n--- 原油 ---")

    # 3e: yfinance - WTI原油期货 (CL=F)
    task_key = "commodity_oil_wti"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('CL=F', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'oil_wti_futures.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  WTI原油期货(CL=F): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  WTI原油期货(CL=F): yfinance获取失败")
    else:
        print(f"  WTI原油期货: 已完成，跳过")

    # 3f: yfinance - Brent原油期货 (BZ=F)
    task_key = "commodity_oil_brent"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('BZ=F', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'oil_brent_futures.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  Brent原油期货(BZ=F): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  Brent原油期货(BZ=F): yfinance获取失败")
    else:
        print(f"  Brent原油期货: 已完成，跳过")

    # 3g: JQData - 原油主力合约 (SC9999.XINE)
    task_key = "commodity_oil_sc"
    if progress.get(task_key) != 'success':
        jq_df = fetch_jq_kline('SC9999.XINE', JQ_DATA_START, JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'oil_sc_main.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  原油主力合约(SC9999): {len(jq_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  原油主力合约(SC9999): JQData获取失败")
    else:
        print(f"  原油主力合约: 已完成，跳过")

    # 3h: JQData - 南方原油LOF (501018)
    task_key = "commodity_oil_lof"
    if progress.get(task_key) != 'success':
        jq_df = fetch_jq_kline('501018.XSHG', JQ_DATA_START, JQ_DATA_END)
        if jq_df is not None and not jq_df.empty:
            csv_path = COMMODITY_DIR / 'oil_lof_501018.csv'
            save_df_to_csv(jq_df, csv_path, 'jqdata')
            print(f"  南方原油LOF(501018): {len(jq_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  南方原油LOF(501018): JQData获取失败")
    else:
        print(f"  南方原油LOF: 已完成，跳过")

    # ========== 美元 ==========
    print("\n--- 美元 ---")

    # 3i: yfinance - 美元指数 (DX-Y.NYB)
    task_key = "commodity_usd_index"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('DX-Y.NYB', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'usd_index.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  美元指数(DX-Y.NYB): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  美元指数(DX-Y.NYB): yfinance获取失败，尝试UUP ETF...")
            # 备用: UUP美元看多ETF
            yf_df2 = fetch_yfinance_kline('UUP', TEN_YEAR_START, TODAY)
            if yf_df2 is not None and not yf_df2.empty:
                csv_path = COMMODITY_DIR / 'usd_etf_uup.csv'
                save_df_to_csv(yf_df2, csv_path, 'yfinance')
                print(f"  美元ETF(UUP): {len(yf_df2)} rows -> {csv_path}")
                progress[task_key] = 'success_uup'
                save_progress(progress)
    else:
        print(f"  美元指数: 已完成，跳过")

    # 3j: yfinance - USD/CNY汇率
    task_key = "commodity_usdcny"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('CNY=X', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'usdcny.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  USD/CNY汇率(CNY=X): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  USD/CNY汇率: yfinance获取失败")
    else:
        print(f"  USD/CNY: 已完成，跳过")

    # ========== 比特币 ==========
    print("\n--- 比特币 ---")

    # 3k: yfinance - BTC-USD
    task_key = "commodity_btc"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('BTC-USD', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'btc_usd.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  比特币(BTC-USD): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  比特币(BTC-USD): yfinance获取失败")
    else:
        print(f"  比特币: 已完成，跳过")

    # 3l: yfinance - ETH-USD
    task_key = "commodity_eth"
    if progress.get(task_key) != 'success':
        yf_df = fetch_yfinance_kline('ETH-USD', TEN_YEAR_START, TODAY)
        if yf_df is not None and not yf_df.empty:
            csv_path = COMMODITY_DIR / 'eth_usd.csv'
            save_df_to_csv(yf_df, csv_path, 'yfinance')
            print(f"  以太坊(ETH-USD): {len(yf_df)} rows -> {csv_path}")
            progress[task_key] = 'success'
            save_progress(progress)
        else:
            print(f"  以太坊(ETH-USD): yfinance获取失败")
    else:
        print(f"  以太坊: 已完成，跳过")


# ============================================================
# 任务4: 用JQData修复港股Volume=0问题
# ============================================================

def task4_fix_hk_volume(progress):
    """用JQData数据修复港股CSV中Volume=0的行"""
    print("\n" + "=" * 70)
    print("任务4: JQData修复港股Volume=0问题")
    print("注意: JQData不支持港股，此任务将跳过")
    print("=" * 70)

    # JQData试用账号不支持港股数据
    # 已确认: 00700.XHKG 等港股代码返回"无效的证券代码"
    # 因此无法用JQData修复港股Volume问题

    print("JQData不支持港股市场，无法修复港股Volume数据。")
    print("港股Volume=0问题仍需依赖yfinance或插值法修复。")
    print("已有修复脚本: fix_hk_volume.py 和 fix_hk_volume_v2.py")


def task4_fix_etf_volume(progress):
    """修复ETF中Volume=0的问题"""
    print("\n" + "=" * 70)
    print("任务4b: 修复ETF Volume=0问题")
    print("=" * 70)

    etf_dir = BASE_DIR / 'etf'
    csv_files = sorted(etf_dir.glob("*.csv"))

    fixed_count = 0
    total_zero = 0

    for csv_path in csv_files:
        df = pd.read_csv(csv_path)
        if df.empty or 'Volume' not in df.columns:
            continue

        zero_count = (df['Volume'] == 0).sum()
        if zero_count == 0:
            continue

        total_zero += zero_count
        symbol = csv_path.stem

        # 用yfinance获取ETF真实数据
        yf_df = fetch_yfinance_kline(symbol, df['Date'].min(), df['Date'].max())
        if yf_df is not None and not yf_df.empty:
            merged = merge_csv_data(csv_path, yf_df, 'yfinance')
            save_df_to_csv(merged, csv_path, 'yfinance')
            new_zero = (merged['Volume'] == 0).sum()
            print(f"  {symbol}: 修复 {zero_count - new_zero}/{zero_count} 个Volume=0行")
            fixed_count += 1
        else:
            print(f"  {symbol}: yfinance获取失败, {zero_count}个Volume=0未修复")

        time.sleep(1)

    print(f"\nETF修复结果: 修复 {fixed_count} 个文件, 总Volume=0行数: {total_zero}")


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 70)
    print("综合数据补充脚本")
    print("数据源: JQData(试用) + westock-data + yfinance")
    print("=" * 70)

    # 加载进度
    progress = load_progress()

    # 登录JQData
    try:
        jq_login()
    except Exception as e:
        print(f"JQData登录失败: {e}")
        print("将跳过需要JQData的任务")

    # 执行任务
    task1_zz500(progress)
    task2_hk_supplement(progress)
    task2_us_supplement(progress)
    task3_commodities(progress)
    task4_fix_hk_volume(progress)
    task4_fix_etf_volume(progress)

    # 汇总
    print("\n" + "=" * 70)
    print("全部任务完成汇总")
    print("=" * 70)
    print(f"A股数据目录: {A_STOCK_DIR}")
    print(f"商品数据目录: {COMMODITY_DIR}")
    print(f"港股数据目录: {HK_DIR}")
    print(f"美股数据目录: {US_DIR}")

    # 统计各目录文件数和总行数
    for dir_path, label in [(A_STOCK_DIR, 'A股'), (COMMODITY_DIR, '商品'),
                            (HK_DIR, '港股'), (US_DIR, '美股')]:
        csv_files = list(dir_path.glob("*.csv"))
        total_rows = 0
        for f in csv_files:
            try:
                with open(f) as fp:
                    total_rows += sum(1 for _ in fp) - 1
            except:
                pass
        print(f"  {label}: {len(csv_files)} 个文件, 共 {total_rows} 行数据")


if __name__ == '__main__':
    main()
