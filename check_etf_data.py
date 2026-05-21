#!/usr/bin/env python3
"""
检查策略中38只ETF的本地数据是否齐全（近10年 = 约2520个交易日）
若不齐全，调用 westock-data skill 补充下载
"""

import os
import json
import subprocess
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# 策略中的 ETF 池（38只）
# ============================================================
ETF_POOL = [
    # 大宗商品ETF
    "518880.XSHG",  # 黄金ETF
    "159980.XSHE",  # 有色ETF
    "159985.XSHE",  # 豆粕ETF
    "501018.XSHG",  # 南方原油
    "161226.XSHE",  # 白银LOF
    "159981.XSHE",  # 能源化工ETF
    # 国际ETF
    "513100.XSHG",  # 纳指ETF
    "159509.XSHE",  # 纳指科技ETF
    "513290.XSHG",  # 纳指生物ETF
    "513500.XSHG",  # 标普500ETF
    "159529.XSHE",  # 标普消费
    "513400.XSHG",  # 道琼斯ETF
    "513520.XSHG",  # 日经225ETF
    "513030.XSHG",  # 德国30ETF
    "513080.XSHG",  # 法国ETF
    "513310.XSHG",  # 中韩半导体ETF
    "513730.XSHG",  # 东南亚ETF
    # 香港ETF
    "159792.XSHE",  # 港股互联ETF
    "513130.XSHG",  # 恒生科技
    "513050.XSHG",  # 中概互联网ETF
    "159920.XSHE",  # 恒生ETF
    "513690.XSHG",  # 港股红利
    # 指数ETF
    "510300.XSHG",  # 沪深300ETF
    "510500.XSHG",  # 中证500ETF
    "510050.XSHG",  # 上证50ETF
    "510210.XSHG",  # 上证ETF
    "159915.XSHE",  # 创业板ETF
    "588080.XSHG",  # 科创50
    "512100.XSHG",  # 中证1000ETF
    "563360.XSHG",  # A500-ETF
    "563300.XSHG",  # 中证2000ETF
    # 风格ETF
    "512890.XSHG",  # 红利低波ETF
    "159967.XSHE",  # 创业板成长ETF
    "512040.XSHG",  # 价值ETF
    "159201.XSHE",  # 自由现金流ETF
    # 债券ETF
    "511380.XSHG",  # 可转债ETF
    "511010.XSHG",  # 国债ETF
    "511220.XSHG",  # 城投债ETF
]

# 防御ETF
DEFENSIVE_ETF = "511880.XSHG"  # 货币基金ETF

# 风险基准
BENCHMARK = "510300.XSHG"  # 沪深300ETF

# westock-data skill 路径
WESTOCK_SKILL = r"C:\Users\blakehao\.codebuddy\skills\westock-data\scripts\index.js"

# 本地数据目录
DATA_DIR = r"C:\Users\blakehao\Desktop\blakever_trade\back_trader_stocks"

# 10年 ≈ 2520 个交易日
MIN_REQUIRED_DAYS = 2400  # 留余量


def jq_to_westock_code(jq_code: str) -> str:
    """
    将聚宽代码转换为 westock-data 代码格式
    518880.XSHG -> sh518880
    159980.XSHE -> sz159980
    """
    parts = jq_code.split(".")
    code = parts[0]
    market = parts[1]
    if market == "XSHG":
        return f"sh{code}"
    elif market == "XSHE":
        return f"sz{code}"
    return jq_code


def find_local_csv(etf_code: str) -> str | None:
    """在 DATA_DIR 下递归查找 ETF 对应的 CSV 文件"""
    code_part = etf_code.split(".")[0]  # 518880
    for root, _, files in os.walk(DATA_DIR):
        for f in files:
            if f.endswith(".csv") and code_part in f:
                return os.path.join(root, f)
    return None


def check_local_data(etf_code: str) -> dict:
    """
    检查本地数据是否齐全
    返回: {"found": bool, "path": str|None, "days": int, "start": str, "end": str}
    """
    result = {"found": False, "path": None, "days": 0, "start": "", "end": ""}

    csv_path = find_local_csv(etf_code)
    if csv_path is None:
        return result

    try:
        # 只读取前面一部分来检查
        df = pd.read_csv(csv_path, nrows=MIN_REQUIRED_DAYS + 100)
        if df.empty:
            return result

        # 尝试解析日期列
        date_col = None
        for col in ["date", "Date", "交易日期", "datetime", "time"]:
            if col in df.columns:
                date_col = col
                break

        result["found"] = True
        result["path"] = csv_path
        result["days"] = len(df)

        if date_col:
            try:
                df[date_col] = pd.to_datetime(df[date_col])
                result["start"] = str(df[date_col].min().date())
                result["end"] = str(df[date_col].max().date())
            except Exception:
                pass

    except Exception as e:
        print(f"  [!] 读取 {csv_path} 失败: {e}")

    return result


def fetch_with_westock(etf_code: str, ws_code: str, output_dir: str) -> bool:
    """
    使用 westock-data skill 下载 ETF 近10年的日K数据
    保存到 output_dir/etf/<code>.csv
    """
    print(f"  正在下载 {etf_code} ({ws_code}) ...")
    try:
        cmd = [
            "node",
            WESTOCK_SKILL,
            "kline",
            ws_code,
            "day",
            str(MIN_REQUIRED_DAYS),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
            cwd=os.path.dirname(WESTOCK_SKILL),
        )

        if result.returncode != 0:
            print(f"  [!] 下载失败: {result.stderr[:300]}")
            return False

        # 解析 JSON 输出并保存为 CSV
        output = result.stdout.strip()
        if not output:
            print(f"  [!] 返回数据为空")
            return False

        data = json.loads(output)

        # westock-data 返回格式: {"data": {"nodes": [...]}}
        nodes = []
        if "data" in data and "nodes" in data["data"]:
            nodes = data["data"]["nodes"]
        elif "nodes" in data:
            nodes = data["nodes"]
        else:
            print(f"  [!] 返回数据格式异常: {list(data.keys())}")
            return False

        if not nodes:
            print(f"  [!] 无K线数据")
            return False

        # 转换为 DataFrame
        rows = []
        for n in nodes:
            rows.append({
                "date": n.get("date", ""),
                "open": n.get("open", 0),
                "close": n.get("last", n.get("close", 0)),
                "high": n.get("high", 0),
                "low": n.get("low", 0),
                "volume": n.get("volume", 0),
                "amount": n.get("amount", 0),
                "exchange": n.get("exchange", 0),
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("date")

        # 保存
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{etf_code.split('.')[0]}.csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  [OK] 已保存 {len(df)} 条到 {out_path}")
        return True

    except subprocess.TimeoutExpired:
        print(f"  [!] 下载超时")
        return False
    except json.JSONDecodeError as e:
        print(f"  [!] JSON解析失败: {e}")
        return False
    except Exception as e:
        print(f"  [!] 异常: {e}")
        return False


def main():
    print("=" * 60)
    print("ETF 本地数据检查（近10年）")
    print("=" * 60)

    all_etfs = list(set(ETF_POOL + [DEFENSIVE_ETF, BENCHMARK]))

    missing = []
    insufficient = []

    for i, etf in enumerate(all_etfs, 1):
        ws_code = jq_to_westock_code(etf)
        print(f"\n[{i}/{len(all_etfs)}] 检查 {etf} ({ws_code})")

        info = check_local_data(etf)
        if not info["found"]:
            print(f"  [X] 本地无数据")
            missing.append((etf, ws_code))
        elif info["days"] < MIN_REQUIRED_DAYS:
            print(f"  [!] 数据不足: {info['days']} 天 (需要 {MIN_REQUIRED_DAYS}+)")
            print(f"      时间范围: {info['start']} ~ {info['end']}")
            insufficient.append((etf, ws_code, info))
        else:
            print(f"  [OK] 数据充足: {info['days']} 天")
            if info["start"]:
                print(f"       时间范围: {info['start']} ~ {info['end']}")

    # 汇总
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    total_ok = len(all_etfs) - len(missing) - len(insufficient)
    print(f"总计 ETF 数量: {len(all_etfs)}")
    print(f"[OK] 数据充足: {total_ok}")
    print(f"[!] 数据不足: {len(insufficient)}")
    print(f"[X] 本地无数据: {len(missing)}")

    # 下载缺失数据
    to_fetch = [(x[0], x[1]) for x in insufficient] + missing
    if to_fetch:
        print(f"\n开始下载 {len(to_fetch)} 只 ETF 数据...")
        print("(使用 westock-data skill，单只超时120秒)\n")

        # 保存目录
        etf_output_dir = os.path.join(DATA_DIR, "etf")
        os.makedirs(etf_output_dir, exist_ok=True)

        success = 0
        for etf, ws_code in to_fetch:
            ok = fetch_with_westock(etf, ws_code, etf_output_dir)
            if ok:
                success += 1

        print(f"\n下载完成: {success}/{len(to_fetch)} 成功")
    else:
        print("\n[OK] 所有 ETF 数据已齐全，无需下载！")


if __name__ == "__main__":
    main()
