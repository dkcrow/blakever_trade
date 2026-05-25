#!/usr/bin/env python3
"""
批量下载选股池股票近10年日线行情数据
保存到 /data/workspace/back_trader_stocks/{hk,us}/ 目录
用于后续回测历史股票策略

数据源：
1. 港股：westock-data skill kline接口（批量逗号分隔查询，每次最多2000条）
2. 美股：优先westock-data，yfinance备用（增加重试与限流处理）

输出格式：CSV，列包含 Date, Open, High, Low, Close, Volume
支持断点续传：已下载的股票自动跳过
"""

import os
import sys
import time
import datetime
import json
import subprocess
from pathlib import Path

# ============================================================
# 选股池配置
# ============================================================

HK_STOCKS = [
    # 恒生科技30只
    "hk00700", "hk09988", "hk03690", "hk01810", "hk01211", "hk00981", "hk00992",
    "hk01024", "hk01347", "hk02015", "hk02382", "hk03888", "hk06618", "hk06690",
    "hk09618", "hk09626", "hk09660", "hk09863", "hk09866", "hk09868", "hk09888",
    "hk09961", "hk09999", "hk00020", "hk00241", "hk00268", "hk00285", "hk00300",
    "hk00780", "hk01698",
    # 恒生指数成分股（去重后73只）
    "hk00001", "hk00002", "hk00003", "hk00005", "hk00006", "hk00011", "hk00012",
    "hk00016", "hk00027", "hk00066", "hk00101", "hk00175", "hk00267", "hk00288",
    "hk00291", "hk00316", "hk00322", "hk00386", "hk00388", "hk00669", "hk00688",
    "hk00728", "hk00762", "hk00823", "hk00836", "hk00857", "hk00868", "hk00881",
    "hk00883", "hk00939", "hk00941", "hk00960", "hk00968", "hk01038", "hk01044",
    "hk01088", "hk01093", "hk01099", "hk01109", "hk01113", "hk01177", "hk01209",
    "hk01299", "hk01378", "hk01398", "hk01801", "hk01876", "hk01928", "hk01929",
    "hk01997", "hk02020", "hk02057", "hk02269", "hk02313", "hk02318", "hk02319",
    "hk02331", "hk02359", "hk02382", "hk02388", "hk02618", "hk02628", "hk02688",
    "hk02899", "hk03692", "hk03750", "hk03968", "hk03988", "hk03993", "hk06181",
    "hk06862", "hk09633", "hk09901",
    # ====== 新增港股标的（修正后）======
    # 核心指数成分股补齐
    "hk02423",
    # 恒生生物科技指数成分股
    "hk00013", "hk01548", "hk01857", "hk02162", "hk02180", "hk02208", "hk02268", "hk02616",
    "hk06160", "hk06162", "hk06978", "hk06990", "hk09688", "hk09887", "hk02126", "hk09969",
    # 行业补强
    "hk00023", "hk00914", "hk00966", "hk00998", "hk01072", "hk06110", "hk01919", "hk01972",
    "hk02013", "hk02196", "hk02333", "hk00384",
    # 做空标的
    "hk00293", "hk00670", "hk01055", "hk02328",
    # 港股通/特色标的
    "hk00317", "hk01787", "hk01880", "hk02050", "hk09880", "hk09987",
    # 旧代码但已下载成功的标的（保留，不删除）
    "hk00017", "hk00753", "hk00987", "hk01288", "hk01797", "hk01812",
    "hk01816", "hk02018", "hk02355", "hk06060", "hk06098", "hk09606",
    "hk09608", "hk09658", "hk09955",
    # 额外补充 - 按行业分组
    # 金融
    "hk00057", "hk00135", "hk00165", "hk00183", "hk00653", "hk00694", "hk00717",
    "hk00772", "hk01336", "hk01339", "hk01448", "hk01606", "hk01728", "hk01755",
    "hk01785", "hk01988", "hk02866",
    # 工业/制造
    "hk00248", "hk00257", "hk00308", "hk00333", "hk00425", "hk00586", "hk00590", "hk00598",
    "hk00635", "hk00683", "hk00811", "hk00817", "hk00819", "hk00832",
    "hk00867", "hk00908", "hk00916", "hk00921", "hk00934", "hk00958", "hk00973",
    "hk01030", "hk01066", "hk01070", "hk01115", "hk01128", "hk01138", "hk01157",
    "hk01200", "hk01216", "hk01656",
    "hk01958", "hk01966",
    "hk02007", "hk02038", "hk02066", "hk02097", "hk02128", "hk02158",
    "hk02182", "hk02202", "hk02238",
    "hk02288", "hk02312",
    "hk02338", "hk02368",
    "hk02371", "hk02376", "hk02386", "hk02393", "hk02396", "hk02400", "hk02418",
    "hk02488", "hk02601",
    "hk02660", "hk02678",
    "hk02691", "hk02727", "hk02768",
    "hk02878",
    "hk03883", "hk06118",
    "hk06978", "hk06990",
    "hk09880", "hk09889",
    "hk09987",
]

US_STOCKS = [
    # 纳斯达克100
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "ALNY", "AMAT", "AMD", "AMGN", "AMZN",
    "APP", "ARM", "ASML", "AVGO", "AXON", "BKR", "BKNG", "CCEP", "CDNS", "CEG", "CHTR", "CMCSA",
    "COST", "CPRT", "CRWD", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC", "FAST",
    "FER", "FTNT", "FANG", "GEHC", "GILD", "HON", "IDXX", "INSM", "INTC", "INTU", "ISRG", "KDP",
    "KHC", "KLAC", "LIN", "LRCX", "MAR", "MDLZ", "MCHP", "MELI", "MNST", "MPWR", "MRVL", "MU",
    "MSTR", "NFLX", "NXPI", "ODFL", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PLTR", "PYPL",
    "QCOM", "REGN", "ROP", "ROST", "SBUX", "SHOP", "SNPS", "STX", "TEAM", "TMUS", "TTWO", "TXN",
    "VRTX", "VRSK", "WDAY", "WDC", "WBD", "XEL", "ZS",
    # 标普500去重后的额外股票
    "A", "AAP", "ABBV", "ABC", "ABT", "ACGL", "ACN", "ADM", "ADS", "AEE", "AFL", "AIG", "AJG",
    "AKAM", "ALB", "ALGN", "ALLE", "ALL", "AMCR", "AME", "AMT", "AMP", "ANET", "ANSS", "AON",
    "AOS", "APO", "APA", "APD", "APH", "APT", "ARES", "ATO", "AVB", "AVY", "AWK", "AXP", "AZO",
    "BA", "BAC", "BALL", "BAX", "BBY", "BDX", "BEN", "BF.B", "BIIB", "BK", "BLK", "BLDR", "BLL",
    "BMY", "BR", "BRK.B", "BRO", "BSX", "BX", "BXP", "C", "CARR", "CAT", "CB", "CBRE", "CBOE",
    "CCI", "CCL", "CDW", "CE", "CF", "CFG", "CHD", "CHRW", "CI", "CINF", "CIEN", "CL", "CLX",
    "CME", "CMG", "CMI", "CMS", "CNC", "CNP", "COF", "COIN", "COO", "COP", "COR", "COTY", "CPAY",
    "CPB", "CRM", "CRH", "CROX", "CTVA", "CTRA", "CVS", "CVNA", "CVX", "CXO", "D", "DAL", "DAY",
    "DD", "DECK", "DELL", "DHI", "DHR", "DIS", "DLR", "DLTR", "DOV", "DRI", "DTE", "DUK", "DVA",
    "DVN", "ECL", "ED", "EFX", "EG", "EIX", "EL", "ELV", "EME", "EMN", "EMR", "ENPH", "EOG", "EPAM",
    "EQIX", "EQR", "EQT", "ERIC", "ES", "ESS", "ETN", "ETR", "ETSY", "EVRG", "EW", "EXPD", "EXR",
    "F", "FDX", "FE", "FFIV", "FDS", "FICO", "FI", "FIS", "FISV", "FITB", "FIX", "FL", "FMX", "FMC",
    "FNV", "FOX", "FOXA", "FRT", "FSLR", "FTV", "GD", "GDDY", "GE", "GEV", "GL", "GLW", "GM", "GNRC",
    "GPC", "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HCA", "HD", "HES", "HIG", "HLT", "HOLX",
    "HON", "HPQ", "HPE", "HRL", "HSIC", "HSY", "HUBB", "HUM", "HWM", "IBM", "ICE", "IEX", "IFF",
    "INCY", "INFY", "INGR", "IP", "IPG", "IQV", "IR", "IRM", "IT", "ITW", "IVZ", "J", "JBHT",
    "JBL", "JCI", "JKHY", "JNJ", "JPM", "K", "KEY", "KEYS", "KIM", "KMB", "KMI", "KMX", "KO",
    "KR", "KVUE", "L", "LHX", "LII", "LLY", "LMT", "LNT", "LOW", "LULU", "LUV", "LVS", "LYB",
    "LYV", "MAA", "MAS", "MCD", "MCK", "MDT", "MET", "MGM", "MHK", "MKC", "MLM", "MMC", "MMM",
    "MO", "MOS", "MPC", "MRK", "MRO", "MRNA", "MS", "MSCI", "MSI", "NAVA", "NDAQ", "NDSN", "NEE",
    "NEM", "NI", "NKE", "NOC", "NOV", "NTRS", "NUE", "NVR", "O", "OKE", "OMC", "ON", "ORCL",
    "OXY", "PARA", "PAYC", "PCG", "PEG", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKI", "PLD",
    "PM", "PNC", "PNR", "PNW", "POOL", "PPG", "PPL", "PRU", "PSA", "PSX", "PTON", "PWR", "PXD",
    "QRVO", "RCL", "RE", "RF", "RHI", "RL", "RMD", "ROK", "ROL", "RSG", "RVTY", "RTX", "SBAC",
    "SCHW", "SHW", "SIRI", "SLB", "SNA", "SO", "SOLV", "SPG", "SPGI", "SRE", "STE", "STLD",
    "STZ", "SW", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG", "TDY", "TEL", "TER",
    "TFC", "TGT", "TMO", "TPL", "TPR", "TRGP", "TRI", "TRMB", "TROW", "TRV", "TSCO", "TSLA",
    "TSN", "TTD", "TWL", "TXT", "UDR", "UHS", "UNP", "UPS", "URI", "USB", "V", "VFC", "VICI",
    "VLO", "VRSN", "VRT", "VST", "VTRS", "VZ", "WAB", "WAL", "WAT", "WBA", "WEC", "WELL",
    "WFC", "WM", "WMB", "WMT", "WRB", "WSM", "WST", "WY", "WYNN", "XOM", "XYL", "YUM",
    "ZBH", "ZTS",
]

# 时间范围
START_DATE = "2016-04-19"
END_DATE = datetime.date.today().strftime("%Y-%m-%d")

# westock-data脚本路径
WESTOCK_SCRIPT = "/data/workspace/.agent/skills/westock-data/scripts/index.js"

# 输出目录
HK_OUTPUT_DIR = Path("/data/workspace/back_trader_stocks/hk")
US_OUTPUT_DIR = Path("/data/workspace/back_trader_stocks/us")

# 确保目录存在
HK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
US_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 批量查询大小（westock-data kline每次最多2000条）
BATCH_LIMIT = 2000

# yfinance限流重试配置
YFINANCE_RETRY_DELAY = 30  # 秒（缩短等待时间）
YFINANCE_MAX_RETRIES = 2  # 只重试2次

# 进度文件（断点续传）
PROGRESS_FILE = Path("/data/workspace/back_trader_stocks/download_progress.json")


def load_progress() -> dict:
    """加载下载进度"""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {"hk": {}, "us": {}}


def save_progress(progress: dict):
    """保存下载进度"""
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def run_westock_cmd(args: list, timeout: int = 120) -> tuple:
    """运行westock-data CLI命令，返回(success, stdout)"""
    cmd = ["node", WESTOCK_SCRIPT] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (result.returncode == 0, result.stdout)
    except subprocess.TimeoutExpired:
        return (False, "TIMEOUT")
    except Exception as e:
        return (False, str(e))


def parse_kline_markdown(markdown_text: str, symbol: str) -> list:
    """解析westock-data kline返回的Markdown表格为标准OHLCV格式
    
    支持两种格式：
    - 单股：| date | open | last | high | low | volume | amount | exchange |
    - 批量：| symbol | date | open | last | high | low | volume | amount | exchange |
    """
    lines = markdown_text.strip().split("\n")
    records = []
    in_data = False

    for line in lines:
        line = line.strip()
        # 跳过空行、分隔行、表头行
        if not line or line.startswith("| ---") or line.startswith("| symbol") or line.startswith("| date"):
            if line.startswith("| symbol") or line.startswith("| date"):
                in_data = True
            continue

        if not in_data:
            continue

        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]

        if len(parts) < 7:
            continue

        try:
            # 判断是否有symbol列：第一列是日期格式(YYYY-MM-DD)则无symbol列
            first_col = parts[0]
            has_symbol_col = not (len(first_col) >= 10 and "-" in first_col)

            if has_symbol_col and len(parts) >= 8:
                # 批量格式：symbol, date, open, last, high, low, volume, amount, exchange
                date_str = parts[1]
                open_val = float(parts[2])
                close_val = float(parts[3])  # "last" is close
                high_val = float(parts[4])
                low_val = float(parts[5])
                vol_raw = parts[6]
            else:
                # 单股格式：date, open, last, high, low, volume, amount, exchange
                date_str = parts[0]
                open_val = float(parts[1])
                close_val = float(parts[2])  # "last" is close
                high_val = float(parts[3])
                low_val = float(parts[4])
                vol_raw = parts[5]

            record = {
                "Date": date_str,
                "Open": open_val,
                "Close": close_val,
                "High": high_val,
                "Low": low_val,
                "Volume": int(float(vol_raw)) if vol_raw not in ("0", "") else 0,
            }
            records.append(record)
        except (ValueError, IndexError):
            continue

    return records


def save_csv(records: list, csv_path: Path) -> bool:
    """将记录保存为CSV文件"""
    if not records:
        return False

    records.sort(key=lambda r: r["Date"])

    with open(csv_path, "w") as f:
        f.write("Date,Open,High,Low,Close,Volume\n")
        for r in records:
            f.write(f"{r['Date']},{r['Open']},{r['High']},{r['Low']},{r['Close']},{r['Volume']}\n")

    return True


def fetch_hk_kline(symbol: str, progress: dict) -> bool:
    """获取单只港股近10年日线K线数据并保存为CSV"""
    csv_path = HK_OUTPUT_DIR / f"{symbol}.csv"

    # 如果已存在且有足够数据，跳过（美股有些上市不到10年，100行以上即认为完整）
    if csv_path.exists():
        with open(csv_path) as f:
            row_count = sum(1 for _ in f) - 1
        if row_count > 100:
            print(f"  [SKIP] {symbol} exists ({row_count} rows)")
            return True

    all_records = []

    # 第一次请求：最近2000条日线
    success, output = run_westock_cmd(["kline", symbol, "--period", "day", "--limit", str(BATCH_LIMIT)])
    if success:
        records = parse_kline_markdown(output, symbol)
        all_records.extend(records)
        print(f"  [OK] {symbol} batch1: {len(records)} rows")
    else:
        print(f"  [WARN] {symbol} batch1 failed: {output[:100]}")

    # 如果第一次拿到了接近2000条，尝试获取更早的数据
    if len(all_records) >= BATCH_LIMIT - 100:
        earliest_date = min(r["Date"] for r in all_records) if all_records else None
        if earliest_date:
            # 用周线数据补充更早期的数据
            success2, output2 = run_westock_cmd(["kline", symbol, "--period", "week", "--limit", "500"])
            if success2:
                weekly_records = parse_kline_markdown(output2, symbol)
                weekly_before = [r for r in weekly_records if r["Date"] < earliest_date]
                all_records.extend(weekly_before)
                if weekly_before:
                    print(f"  [OK] {symbol} weekly supplement: {len(weekly_before)} rows")

    if all_records:
        save_csv(all_records, csv_path)
        print(f"  [SAVE] {symbol} -> {csv_path} ({len(all_records)} rows total)")
        progress["hk"][symbol] = "success"
        save_progress(progress)
        return True
    else:
        print(f"  [FAIL] {symbol} no data obtained")
        progress["hk"][symbol] = "fail"
        save_progress(progress)
        return False


def fetch_us_kline(symbol: str, progress: dict) -> bool:
    """获取单只美股近10年日线K线数据并保存为CSV"""
    csv_path = US_OUTPUT_DIR / f"{symbol}.csv"

    # 如果已存在且有足够数据，跳过（美股有些上市不到10年，100行以上即认为完整）
    if csv_path.exists():
        with open(csv_path) as f:
            row_count = sum(1 for _ in f) - 1
        if row_count > 100:
            print(f"  [SKIP] {symbol} exists ({row_count} rows)")
            return True

    all_records = []

    # 方案1：westock-data（美股代码需加us前缀，小写）
    success, output = run_westock_cmd(["kline", f"us{symbol}", "--period", "day", "--limit", str(BATCH_LIMIT)])
    if success:
        records = parse_kline_markdown(output, symbol)
        all_records.extend(records)
        print(f"  [OK] {symbol} westock-data: {len(records)} rows")

    # 如果westock-data不够，尝试补充周线
    if len(all_records) >= BATCH_LIMIT - 100:
        earliest_date = min(r["Date"] for r in all_records) if all_records else None
        if earliest_date:
            success2, output2 = run_westock_cmd(["kline", f"us{symbol}", "--period", "week", "--limit", "500"])
            if success2:
                weekly_records = parse_kline_markdown(output2, symbol)
                weekly_before = [r for r in weekly_records if r["Date"] < earliest_date]
                all_records.extend(weekly_before)
                if weekly_before:
                    print(f"  [OK] {symbol} weekly supplement: {len(weekly_before)} rows")

    # 方案2：yfinance备用（仅在westock-data完全无数据时使用，且限流时快速失败）
    if len(all_records) < 100:
        print(f"  [FALLBACK] {symbol} trying yfinance...")
        yf_result = fetch_us_yfinance(symbol)
        if yf_result and len(yf_result) > len(all_records):
            all_records = yf_result
            print(f"  [OK] {symbol} yfinance: {len(all_records)} rows")
        else:
            print(f"  [WARN] {symbol} yfinance also failed, using westock data ({len(all_records)} rows)")

    if all_records:
        save_csv(all_records, csv_path)
        print(f"  [SAVE] {symbol} -> {csv_path} ({len(all_records)} rows total)")
        progress["us"][symbol] = "success"
        save_progress(progress)
        return True
    else:
        print(f"  [FAIL] {symbol} no data obtained")
        progress["us"][symbol] = "fail"
        save_progress(progress)
        return False


def fetch_us_yfinance(symbol: str) -> list:
    """通过yfinance获取美股数据（备用方案）"""
    try:
        import yfinance as yf
    except ImportError:
        print("    [INSTALL] installing yfinance...")
        subprocess.run([sys.executable, "-m", "pip", "install", "yfinance", "-q"], check=True)
        import yfinance as yf

    for attempt in range(YFINANCE_MAX_RETRIES):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=START_DATE, end=END_DATE, interval="1d")
            if df.empty:
                return []
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            df.index.name = "Date"
            records = []
            for date, row in df.iterrows():
                records.append({
                    "Date": date.strftime("%Y-%m-%d"),
                    "Open": float(row["Open"]),
                    "High": float(row["High"]),
                    "Low": float(row["Low"]),
                    "Close": float(row["Close"]),
                    "Volume": int(row["Volume"]) if row["Volume"] > 0 else 0,
                })
            return records
        except Exception as e:
            if "Rate" in str(e) or "429" in str(e):
                print(f"    [RATE-LIMIT] yfinance rate limited, retry {attempt+1}/{YFINANCE_MAX_RETRIES}")
                time.sleep(YFINANCE_RETRY_DELAY)
            else:
                print(f"    [ERROR] yfinance failed: {e}")
                return []
    return []


def main():
    print("=" * 70)
    print("批量下载选股池行情数据（近10年日线）")
    print("=" * 70)
    print(f"时间范围：{START_DATE} ~ {END_DATE}")
    print(f"港股数量：{len(HK_STOCKS)}")
    print(f"美股数量：{len(US_STOCKS)}")
    print("输出目录：/data/workspace/back_trader_stocks/hk/ 和 us/")
    print("=" * 70)

    # 加载进度
    progress = load_progress()
    if "hk" not in progress:
        progress["hk"] = {}
    if "us" not in progress:
        progress["us"] = {}

    # ========== 第一步：下载港股数据 ==========
    print(f"\n### 第一步：下载港股数据 ({len(HK_STOCKS)}只) ###\n")
    hk_success = 0
    hk_fail = 0
    hk_skip = 0
    hk_failed_list = []

    for i, code in enumerate(HK_STOCKS):
        # 断点续传：已成功的跳过
        if progress["hk"].get(code) == "success":
            hk_skip += 1
            continue
        print(f"[{i+1-hk_skip}/{len(HK_STOCKS)-hk_skip}] {code}")
        if fetch_hk_kline(code, progress):
            hk_success += 1
        else:
            hk_fail += 1
            hk_failed_list.append(code)
        time.sleep(0.3)

    print(f"\n港股结果：成功 {hk_success}，跳过 {hk_skip}，失败 {hk_fail}")
    if hk_failed_list:
        print(f"失败标的：{hk_failed_list}")

    # ========== 第二步：下载美股数据 ==========
    print(f"\n### 第二步：下载美股数据 ({len(US_STOCKS)}只) ###\n")
    us_success = 0
    us_fail = 0
    us_skip = 0
    us_failed_list = []

    for i, code in enumerate(US_STOCKS):
        # 断点续传：已成功的跳过
        if progress["us"].get(code) == "success":
            us_skip += 1
            continue
        print(f"[{i+1-us_skip}/{len(US_STOCKS)-us_skip}] {code}")
        if fetch_us_kline(code, progress):
            us_success += 1
        else:
            us_fail += 1
            us_failed_list.append(code)
        time.sleep(0.3)

    print(f"\n美股结果：成功 {us_success}，跳过 {us_skip}，失败 {us_fail}")
    if us_failed_list:
        print(f"失败标的（前30）：{us_failed_list[:30]}{'...' if len(us_failed_list) > 30 else ''}")

    # ========== 汇总 ==========
    print("\n" + "=" * 70)
    print("下载汇总")
    print("=" * 70)
    print(f"港股：成功 {hk_success}，跳过(已完成) {hk_skip}，失败 {hk_fail}")
    print(f"美股：成功 {us_success}，跳过(已完成) {us_skip}，失败 {us_fail}")
    print(f"\n数据保存位置：")
    print(f"  港股：/data/workspace/back_trader_stocks/hk/")
    print(f"  美股：/data/workspace/back_trader_stocks/us/")
    print(f"\n进度文件：{PROGRESS_FILE}")
    print("\n完成！")


if __name__ == "__main__":
    main()
