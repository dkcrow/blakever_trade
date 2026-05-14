
# 策略: 01 Data Exploration
# 来源: multi:google_github
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:15:37

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "01 Data Exploration"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

from pathlib import Path
from datetime import datetime, timezone
from investing_algorithm_framework import BacktestDateRange, \
    generate_rolling_backtest_windows

data_storage_path = Path.cwd().parent / "data"
backtest_results_dir = Path.cwd().parent / "backtest_results"
reports_dir = Path.cwd().parent / "reports"
figures_dir = reports_dir / "figures"

backtest_window_date_range = BacktestDateRange(
    start_date=datetime(2022, 1, 1, tzinfo=timezone.utc),
    end_date=datetime(2025, 12, 30, tzinfo=timezone.utc)
)
MARKET = "BITVAVO"
in_sample_assets = ["BTC", "ETH", "ADA", "SOL", "DOT"]
out_sample_assets = ["XRP", "LTC", "BCH"]
time_frames = ["2h", "4h", "1d"]

import os

# create all required directories
if not os.path.exists(data_storage_path):
    os.makedirs(data_storage_path)

if not os.path.exists(backtest_results_dir):
    os.makedirs(backtest_results_dir)

if not os.path.exists(reports_dir):
    os.makedirs(reports_dir)

if not os.path.exists(figures_dir):
    os.makedirs(figures_dir)

rolling_backtest_windows = generate_rolling_backtest_windows(
    start_date=backtest_window_date_range.start_date,
    end_date=backtest_window_date_range.end_date,
    train_days=365,
    test_days=180,
    gap_days=30,
    step_days=90,
)

from investing_algorithm_framework import download_v2, TimeFrame, tqdm
in_sample_data = {}
out_sample_data = {}

for symbol in in_sample_assets:
    symbol_pair = f"{symbol}/EUR"

    for time_frame in tqdm(time_frames, desc=f"Downloading data for {symbol_pair} {time_frames}"):
        if symbol not in in_sample_data:
            in_sample_data[symbol] = {}

        result = download_v2(
            symbol=symbol_pair,
            market=MARKET,
            time_frame=time_frame,
            data_type="ohlcv",
            start_date=backtest_window_date_range.start_date,
            end_date=backtest_window_date_range.end_date,
            save=True,
            storage_path=str(data_storage_path),
            # Optional: provide a custom filename instead of the auto-generated one
            # filename=f"{symbol}_{time_frame}_in_sample",
        )
        in_sample_data[symbol][time_frame] = {
            "data": result.data,
            "path": result.path
        }
        first_date = result.data.index[0]

        if first_date > backtest_window_date_range.start_date:
            print(f"Warning: Data for {symbol_pair} starts on {first_date} which is after the requested start date of {backtest_window_date_range.start_date}.")


for symbol in out_sample_assets:
    symbol_pair = f"{symbol}/EUR"

    for time_frame in tqdm(time_frames, desc=f"Downloading data for {symbol_pair} {time_frames}"):
        if symbol not in out_sample_data:
            out_sample_data[symbol] = {}

        result = download_v2(
            symbol=symbol_pair,
            market=MARKET,
            time_frame=time_frame,
            data_type="ohlcv",
            start_date=backtest_window_date_range.start_date,
            end_date=backtest_window_date_range.end_date,
            save=True,
            storage_path=str(data_storage_path),
            # Optional: provide a custom filename instead of the auto-generated one
            # filename=f"{symbol}_{time_frame}_out_sample",
        )
        out_sample_data[symbol][time_frame] = {
            "data": result.data,
            "path": result.path
        }
        first_date = result.data.index[0]

        if first_date > backtest_window_date_range.start_date:
            print(f"Warning: Data for {symbol_pair} starts on {first_date} which is after the requested start date of {backtest_window_date_range.start_date}.")

from investing_algorithm_framework import fill_missing_timeseries_data, tqdm, get_missing_timeseries_data_entries

for symbol, time_frames_dict in tqdm(in_sample_data.items(), desc="Checking in-sample data"):
    for time_frame, entry in time_frames_dict.items():
        data = entry["data"]
        file_path = entry["path"]
        missing_dates = get_missing_timeseries_data_entries(data)

        if len(missing_dates) > 0:
            print(f"Filling {len(missing_dates)} missing dates for {symbol} {time_frame}")
            fill_missing_timeseries_data(
                data,
                missing_dates=missing_dates,
                save_to_file=True,
                file_path=str(file_path)
            )

for symbol, time_frames_dict in tqdm(out_sample_data.items(), desc="Checking out-sample data"):
    for time_frame, entry in time_frames_dict.items():
        data = entry["data"]
        file_path = entry["path"]
        missing_dates = get_missing_timeseries_data_entries(data)

        if len(missing_dates) > 0:
            print(f"Filling {len(missing_dates)} missing dates for {symbol} {time_frame}")
            fill_missing_timeseries_data(
                data,
                missing_dates=missing_dates,
                save_to_file=True,
                file_path=str(file_path)
            )


import numpy as np
from typing import Dict, Tuple
import pandas as pd
from investing_algorithm_framework import create_markdown_table, BacktestDateRange
from IPython.display import Markdown, display


def show_backtest_windows_analysis(
    data: Dict[str, Tuple[BacktestDateRange, pd.DataFrame]],
):
    """
    Show analysis of backtest windows. Each entry in `data` should map
    a label to a tuple of (date_range, ohlcv_dataframe).

    Args:
        data (Dict[str, Tuple[BacktestDateRange, pd.DataFrame]]): Mapping
            of labels (backtest window identifiers) to
            (date_range, ohlcv_dataframe)

    Returns:
        List[Dict]: List of detailed analysis dictionaries for each window
    """
    summary_data = []
    detailed_analysis = []

    for key, (date_range, df) in data.items():
        sliced_data = df[date_range.start_date:date_range.end_date].copy()

        if sliced_data.empty:
            continue

        # Calculate comprehensive metrics
        sliced_data['returns'] = sliced_data['Close'].pct_change().dropna()

        start_price = sliced_data['Close'].iloc[0]
        end_price = sliced_data['Close'].iloc[-1]
        total_return = (end_price / start_price - 1) * 100

        daily_returns = sliced_data['returns'] * 100
        volatility = daily_returns.std() * np.sqrt(365)
        mean_daily_return = daily_returns.mean()
        sharpe_ratio = (mean_daily_return * 365) / volatility if volatility > 0 else 0

        # Drawdown analysis
        rolling_max = sliced_data['Close'].cummax()
        drawdown = (sliced_data['Close'] / rolling_max - 1) * 100
        max_drawdown = drawdown.min()

        # Volatility regimes
        high_vol_days = (daily_returns.abs() > daily_returns.abs().quantile(0.8)).sum()
        low_vol_days = (daily_returns.abs() < daily_returns.abs().quantile(0.2)).sum()

        # Trend analysis (count of data points, not calendar days)
        up_periods = (daily_returns > 0).sum()
        down_periods = (daily_returns < 0).sum()
        total_periods = len(sliced_data)

        # Duration in calendar days
        duration_days = (date_range.end_date - date_range.start_date).days
        start_date_str = date_range.start_date.strftime('%Y-%m-%d')
        end_date_str = date_range.end_date.strftime('%Y-%m-%d')

        summary_data.append({
            "window": key,
            "date_range": f"{start_date_str} to {end_date_str}",
            "days": str(duration_days),
            "avg_daily_return": f"{mean_daily_return:.3f}%",
            "cumulative_return": f"{total_return:.2f}%",
            "volatility_ann": f"{volatility:.2f}%",
            "sharpe_ratio": f"{sharpe_ratio:.2f}",
            "max_drawdown": f"{max_drawdown:.2f}%",
            "up_periods": f"{up_periods} ({up_periods/total_periods*100:.1f}%)",
            "down_periods": f"{down_periods} ({down_periods/total_periods*100:.1f}%)",
            "high_vol_periods": f"{high_vol_days} ({high_vol_days/total_periods*100:.1f}%)",
            "low_vol_periods": f"{low_vol_days} ({low_vol_days/total_periods*100:.1f}%)"
        })

        # Detailed analysis for each period
        detailed_analysis.append({
            'name': key,
            'total_return': total_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'up_periods': up_periods,
            'down_periods': down_periods,
            'high_vol_periods': high_vol_days,
            'low_vol_periods': low_vol_days,
            'duration_days': duration_days,
            'total_periods': total_periods,
            'mean_daily_return': mean_daily_return,
            'start_price': start_price,
            'end_price': end_price
        })

    # Create and display the markdown table
    table = create_markdown_table(summary_data)
    display(Markdown(table))

    return detailed_analysis


# Prepare data for analysis - use BTC as reference asset
btc_data = in_sample_data["BTC"]["2h"]["data"]

# Create analysis data dictionary from rolling backtest windows
analysis_data = {}
for i, window in enumerate(rolling_backtest_windows):
    train_range = window["train_range"]
    analysis_data[f"Window {i+1} (Train)"] = (train_range, btc_data)

    if "test_range" in window:
        test_range = window["test_range"]
        analysis_data[f"Window {i+1} (Test)"] = (test_range, btc_data)

# Show the analysis
detailed_results = show_backtest_windows_analysis(
    data=analysis_data,
)

