"""
Blakever Agent 8 - EMA Crossover Backtest (VectorBT + westock-data)
Strategy: Buy when Fast EMA crosses above Slow EMA, sell on cross below.
Data: westock-data (美股 SPY)
Indicators: TA-Lib EMA exclusively.
Fees: US equity model (0.1% per side).
Benchmark: S&P 500 Buy & Hold.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import talib as tl
import vectorbt as vbt

# --- 内联 exrem ---
def exrem(signal1, signal2):
    """Remove excessive signals: keep first signal1 until signal2 fires."""
    result = signal1.copy()
    active = False
    for i in range(len(signal1)):
        if active:
            result.iloc[i] = False
        if signal1.iloc[i] and not active:
            active = True
        if signal2.iloc[i]:
            active = False
    return result

# --- westock-data 数据获取 ---
def fetch_kline_westock(symbol: str, period: str = "day", limit: int = 800) -> pd.DataFrame:
    """通过 westock-data CLI 获取K线数据，返回 DataFrame"""
    script_path = "/data/workspace/.agent/skills/westock-data/scripts/index.js"
    cmd = ["node", script_path, "kline", symbol, "--period", period, "--limit", str(limit)]
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd="/data/workspace")
    if result.returncode != 0:
        print(f"westock-data 错误: {result.stderr}")
        sys.exit(1)
    
    # 解析 Markdown 表格
    lines = result.stdout.strip().split("\n")
    # 找到表头和数据行
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("|") and "date" in line.lower():
            header_idx = i
            break
    
    if header_idx is None:
        print("无法解析 westock-data 输出")
        sys.exit(1)
    
    # 解析表头
    headers = [h.strip() for h in lines[header_idx].split("|") if h.strip()]
    # 跳过分隔行
    data_lines = [l for l in lines[header_idx + 2:] if l.strip().startswith("|")]
    
    rows = []
    for line in data_lines:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) >= len(headers):
            rows.append(cells[:len(headers)])
    
    df = pd.DataFrame(rows, columns=headers)
    
    # 类型转换
    df["date"] = pd.to_datetime(df["date"])
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["last"] = pd.to_numeric(df["last"], errors="coerce")  # westock 用 last 而非 close
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    
    # 重命名 last -> close
    df = df.rename(columns={"last": "close"})
    
    # 设置索引
    df = df.set_index("date").sort_index()
    
    # 去除NaN
    df = df.dropna(subset=["close", "high", "low", "open"])
    
    return df[["open", "high", "low", "close", "volume"]]


# --- 配置 ---
script_dir = Path(__file__).resolve().parent

SYMBOL = "usSPY"              # 标普500 ETF
FAST_EMA = 10
SLOW_EMA = 20
INIT_CASH = 100_000           # 10万美元初始资金
FEES = 0.001                  # 0.1% per side (US equity commission estimate)
ALLOCATION = 0.90             # 90%仓位
BENCHMARK_SYMBOL = "us.INX"   # S&P 500 指数
DATA_LIMIT = 800              # 获取近800个交易日数据

# --- 获取数据 ---
print(f"[Blakever Agent 8] 获取 {SYMBOL} 日线数据 (近{DATA_LIMIT}个交易日)...")

df = fetch_kline_westock(SYMBOL, period="day", limit=DATA_LIMIT)
print(f"数据加载完成: {len(df)} 根K线, {df.index[0].date()} ~ {df.index[-1].date()}")

close = df["close"]

# --- 策略: EMA Crossover (TA-Lib) ---
ema_fast = pd.Series(tl.EMA(close.values, timeperiod=FAST_EMA), index=close.index)
ema_slow = pd.Series(tl.EMA(close.values, timeperiod=SLOW_EMA), index=close.index)

# 生成原始信号
buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

# 清洗重复信号
entries = exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = exrem(sell_raw.fillna(False), buy_raw.fillna(False))

print(f"信号统计 - 买入: {entries.sum()}, 卖出: {exits.sum()}")

# --- 执行回测 ---
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=INIT_CASH,
    size=ALLOCATION,
    size_type="percent",
    fees=FEES,
    direction="longonly",
    min_size=1,
    size_granularity=1,
    freq="1D",
)

# --- 基准: S&P 500 Buy & Hold ---
print(f"\n[Blakever Agent 8] 获取基准数据: {BENCHMARK_SYMBOL}")
df_bench = fetch_kline_westock(BENCHMARK_SYMBOL, period="day", limit=DATA_LIMIT)

bench_close = df_bench["close"].reindex(close.index).ffill().bfill()
pf_bench = vbt.Portfolio.from_holding(bench_close, init_cash=INIT_CASH, fees=FEES, freq="1D")

# --- 输出回测结果 ---
print("\n" + "=" * 70)
print(f"  Blakever Agent 8 | EMA {FAST_EMA}/{SLOW_EMA} Crossover 回测报告")
print(f"  标的: SPY | 周期: 日线 | 区间: {df.index[0].date()} ~ {df.index[-1].date()}")
print("=" * 70)
print(pf.stats())

# --- 策略 vs 基准对比 ---
print("\n" + "-" * 70)
print("  策略 vs 基准 (S&P 500 Buy & Hold) 对比")
print("-" * 70)
comparison = pd.DataFrame({
    "EMA策略": [
        f"{pf.total_return() * 100:.2f}%",
        f"{pf.sharpe_ratio():.2f}",
        f"{pf.sortino_ratio():.2f}",
        f"{pf.max_drawdown() * 100:.2f}%",
        f"{pf.trades.win_rate() * 100:.1f}%",
        f"{pf.trades.count()}",
        f"{pf.trades.profit_factor():.2f}",
    ],
    "基准 (S&P 500)": [
        f"{pf_bench.total_return() * 100:.2f}%",
        f"{pf_bench.sharpe_ratio():.2f}",
        f"{pf_bench.sortino_ratio():.2f}",
        f"{pf_bench.max_drawdown() * 100:.2f}%",
        "-",
        "-",
        "-",
    ],
}, index=["总收益率", "夏普比率", "索提诺比率", "最大回撤",
          "胜率", "交易次数", "盈亏比"])
print(comparison.to_string())

# --- 通俗解读 ---
print("\n" + "-" * 70)
print("  回测报告解读 (通俗版)")
print("-" * 70)
alpha = pf.total_return() - pf_bench.total_return()
print(f"* 总收益率: 策略 {pf.total_return() * 100:.2f}% vs 基准 {pf_bench.total_return() * 100:.2f}%")
print(f"  -> 超额收益(Alpha): {alpha * 100:.2f}% ({'跑赢基准' if alpha > 0 else '跑输基准'})")
print(f"* 夏普比率: {pf.sharpe_ratio():.2f} "
      f"({'优秀 >2' if pf.sharpe_ratio() > 2 else '良好 >1' if pf.sharpe_ratio() > 1 else '偏低 <1'})")
print(f"  -> 每承受1单位风险，获得多少超额回报。>1可接受，>2优秀。")
print(f"* 最大回撤: {pf.max_drawdown() * 100:.2f}%")
print(f"  -> 最惨的时候从高点亏损了这么多。10万美元最惨亏损约 ${abs(pf.max_drawdown()) * INIT_CASH:,.0f}")
print(f"* 胜率: {pf.trades.win_rate() * 100:.1f}%")
print(f"  -> EMA交叉策略通常胜率35-45%，靠盈亏比取胜。")
print(f"* 盈亏比: {pf.trades.profit_factor():.2f} "
      f"({'优秀 >2' if pf.trades.profit_factor() > 2 else '良好 >1.5' if pf.trades.profit_factor() > 1.5 else '边际 >1' if pf.trades.profit_factor() > 1 else '亏损 <1'})")
print(f"  -> 赚的钱是亏的钱的几倍。>1.5良好，>2优秀。")
print(f"* 交易次数: {pf.trades.count()}")
print(f"  -> {'统计意义充足 (>=30次)' if pf.trades.count() >= 30 else '交易次数偏少，结果可能不可靠'}")

# --- CRO 风控评估 ---
print("\n" + "-" * 70)
print("  CRO 风控评估")
print("-" * 70)
max_dd_pct = abs(pf.max_drawdown()) * 100
cro_verdict = "PASS" if max_dd_pct < 25 else "WARNING" if max_dd_pct < 40 else "REJECT"
print(f"* 最大回撤: {max_dd_pct:.2f}% -> CRO评估: {cro_verdict}")
print(f"  -> Blakever红线: 回撤<25% PASS, 25-40% WARNING, >40% REJECT")
if cro_verdict == "REJECT":
    print(f"  -> [风控红线] 该策略最大回撤超过40%，CRO建议降低仓位或放弃!")
elif cro_verdict == "WARNING":
    print(f"  -> [风控警告] 回撤偏高，建议仓位打折至50%!")
else:
    print(f"  -> [风控通过] 回撤在可控范围内。")

# --- 导出交易记录 ---
trades_file = script_dir / "SPY_ema_crossover_trades.csv"
pf.positions.records_readable.to_csv(trades_file, index=False)
print(f"\n交易记录已导出: {trades_file}")
print(f"\n[Blakever Agent 8] 回测完成! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
