#!/usr/bin/env python3
"""
使用 akshare 补充缺失的 ETF 近10年日K数据
保存到 back_trader_stocks/etf/<code>.csv
"""

import os
import time
import pandas as pd
import akshare as ak

# ============================================================
# ETF 池（与策略一致）
# ============================================================
ETF_POOL = [
    "518880", "159980", "159985", "501018", "161226", "159981",
    "513100", "159509", "513290", "513500", "159529", "513400",
    "513520", "513030", "513080", "513310", "513730",
    "159792", "513130", "513050", "159920", "513690",
    "510300", "510500", "510050", "510210", "159915",
    "588080", "512100", "563360", "563300",
    "512890", "159967", "512040", "159201",
    "511380", "511010", "511220",
    "511880",  # 防御ETF
]

# 保存目录
OUTPUT_DIR = r"C:\Users\blakehao\Desktop\blakever_trade\back_trader_stocks\etf"

# 近10年
YEARS_BACK = 10


def fetch_etf_akshare(code: str) -> pd.DataFrame | None:
    """
    使用 akshare 获取 ETF 日K数据
    尝试多个接口，返回 DataFrame 或 None
    """
    # 方法1: stock_zh_a_hist (通用A股/ETF日线)
    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(pd.Timestamp.now() - pd.Timedelta(days=YEARS_BACK*400)).strftime("%Y%m%d"),
            end_date=pd.Timestamp.now().strftime("%Y%m%d"),
            adjust="",
        )
        if df is not None and not df.empty:
            return df
    except Exception as e:
        pass

    # 方法2: fund_etf_hist_em (ETF专用)
    try:
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=(pd.Timestamp.now() - pd.Timedelta(days=YEARS_BACK*400)).strftime("%Y%m%d"),
            end_date=pd.Timestamp.now().strftime("%Y%m%d"),
            adjust="",
        )
        if df is not None and not df.empty:
            return df
    except Exception as e:
        pass

    return None


def standardize_df(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """统一字段名"""
    # akshare 返回列名可能不同
    col_map = {
        "日期": "date",
        "date": "date",
        "Date": "date",
        "开盘": "open",
        "open": "open",
        "收盘": "close",
        "close": "close",
        "最高": "high",
        "high": "high",
        "最低": "low",
        "low": "low",
        "成交量": "volume",
        "volume": "volume",
        "成交额": "amount",
        "amount": "amount",
    }
    df = df.rename(columns=col_map)

    # 确保必要列存在
    required = ["date", "open", "close", "high", "low"]
    for col in required:
        if col not in df.columns:
            print(f"  [!] 缺少列: {col}, 可用列: {list(df.columns)}")
            return None

    # 选取需要的列
    keep = ["date", "open", "close", "high", "low"]
    for c in ["volume", "amount", "exchange"]:
        if c in df.columns:
            keep.append(c)

    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print(f"使用 akshare ({ak.__version__}) 补充 ETF 数据")
    print("=" * 60)

    # 先检查哪些已有足够数据
    existing = set()
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".csv"):
            code = f.replace(".csv", "")
            existing.add(code)
    print(f"本地已有 {len(existing)} 只 ETF 数据\n")

    to_fetch = [c for c in ETF_POOL if c not in existing]
    print(f"需要下载: {len(to_fetch)} 只")
    print(f"跳过(已有): {len(existing)} 只\n")

    success = 0
    failed = []

    for i, code in enumerate(to_fetch, 1):
        print(f"[{i}/{len(to_fetch)}] 下载 {code} ...")
        try:
            df = fetch_etf_akshare(code)
            if df is None or df.empty:
                print(f"  [X] 无数据")
                failed.append((code, "无数据"))
                time.sleep(0.5)
                continue

            df = standardize_df(df, code)
            if df is None:
                failed.append((code, "字段异常"))
                time.sleep(0.5)
                continue

            out_path = os.path.join(OUTPUT_DIR, f"{code}.csv")
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            print(f"  [OK] {len(df)} 条, {df['date'].min().date()} ~ {df['date'].max().date()}")
            success += 1

        except Exception as e:
            print(f"  [X] 异常: {e}")
            failed.append((code, str(e)))

        time.sleep(0.8)  # 避免请求过快

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)
    print(f"成功: {success}/{len(to_fetch)}")
    if failed:
        print(f"失败: {len(failed)}")
        for code, reason in failed:
            print(f"  {code}: {reason}")


if __name__ == "__main__":
    main()
