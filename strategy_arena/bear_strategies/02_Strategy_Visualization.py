
# 策略: 02 Strategy Visualization
# 来源: multi:google_github
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:15:38

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "02 Strategy Visualization"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

import sys
from pathlib import Path
import importlib

# Add parent directory to path so we can import from strategies/
sys.path.insert(0, str(Path.cwd().parent))

import strategies.ema_crossover_rsi_filter as strategy
importlib.reload(strategy)

Strategy = strategy.EMACrossoverRSIFFilterStrategy

from pathlib import Path
from datetime import datetime, timezone
from investing_algorithm_framework import BacktestDateRange

production_params_path = Path.cwd().parent / "production_params.json"
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

from investing_algorithm_framework import generate_rolling_backtest_windows

rolling_backtest_windows = generate_rolling_backtest_windows(
    start_date=backtest_window_date_range.start_date,
    end_date=backtest_window_date_range.end_date,
    train_days=365,
    test_days=180,
    gap_days=30,
    step_days=90,
)

first_train_window_key, first_test_window_key = rolling_backtest_windows[0]
first_train_window = rolling_backtest_windows[0][first_train_window_key]

params = {
    "trading_symbol": "EUR",
    "ema_timeframe": "2h",
    "ema_short_period": 50,
    "ema_long_period": 200,
    "ema_cross_lookback_window": 3,
    "rsi_timeframe": "2h",
    "rsi_period": 14,
    "rsi_overbought_threshold": 75,
    "rsi_oversold_threshold": 30,
}

from investing_algorithm_framework import TimeUnit

algorithm_id = "visualization_strategy"
strategy = Strategy(
    **params,
    algorithm_id=algorithm_id,
    time_unit=TimeUnit.HOUR,
    interval=2,
    market=MARKET,
    symbols=in_sample_assets,
)

from investing_algorithm_framework import create_app, RESOURCE_DIRECTORY, PortfolioConfiguration
from investing_algorithm_framework.domain import DATA_DIRECTORY

print(first_train_window)
app = create_app(config={RESOURCE_DIRECTORY: "./resources", DATA_DIRECTORY: data_storage_path})
app.add_portfolio_configuration(
    PortfolioConfiguration(initial_balance=1000, market="BITVAVO", trading_symbol="EUR")
)
app.add_strategy(strategy)
backtest = app.run_vector_backtest(
    backtest_date_range=first_train_window, show_progress=True
)

backtest_run = backtest.get_backtest_run(first_train_window)
trades = backtest_run.get_trades()
print(len(trades))

buy_orders = backtest_run.get_orders(order_side="buy")
sell_orders = backtest_run.get_orders(order_side="sell")

import plotly.graph_objects as go
import pandas as pd
from plotly.subplots import make_subplots
from investing_algorithm_framework import download
from pyindicators import ema, rsi, crossover, crossunder

buy_orders = backtest_run.get_orders(order_side="buy")
sell_orders = backtest_run.get_orders(order_side="sell")

start_date = first_train_window.start_date
end_date = first_train_window.end_date


def build_symbol_traces(symbol, strategy, buy_orders, sell_orders, start_date, end_date):
    """Build all plotly traces + hlines for one symbol. Returns (traces_row1, traces_row2, traces_row3, hlines)."""
    timeframe = strategy.ema_timeframe

    ohlcv = download(
        market="BITVAVO",
        symbol=f"{symbol}/EUR",
        time_frame=timeframe,
        start_date=start_date,
        end_date=end_date,
        storage_path=str(data_storage_path),
        pandas=True,
    )

    # Compute indicators
    ema_data = ema(ohlcv.copy(), period=strategy.ema_short_period,
                   source_column="Close", result_column="ema_short")
    ema_data = ema(ema_data, period=strategy.ema_long_period,
                   source_column="Close", result_column="ema_long")
    ema_data = crossover(ema_data, first_column="ema_short",
                         second_column="ema_long", result_column="ema_crossover")
    ema_data = crossunder(ema_data, first_column="ema_short",
                          second_column="ema_long", result_column="ema_crossunder")
    rsi_data = rsi(ohlcv.copy(), period=strategy.rsi_period,
                   source_column="Close", result_column="rsi")

    # Reproduce strategy signals
    rsi_oversold = rsi_data["rsi"] < strategy.rsi_oversold_threshold
    rsi_overbought = rsi_data["rsi"] >= strategy.rsi_overbought_threshold
    cross_up = ema_data["ema_crossover"].rolling(
        window=strategy.ema_cross_lookback_window).sum() > 0
    cross_down = ema_data["ema_crossunder"].rolling(
        window=strategy.ema_cross_lookback_window).sum() > 0
    buy_signal = (rsi_oversold & cross_up).fillna(False)
    sell_signal = (rsi_overbought & cross_down).fillna(False)

    sym_buys = [o for o in buy_orders if o.target_symbol == symbol]
    sym_sells = [o for o in sell_orders if o.target_symbol == symbol]

    traces_r1 = []
    traces_r2 = []
    traces_r3 = []

    # Row 1: Candlestick
    traces_r1.append(go.Candlestick(
        x=ohlcv.index, open=ohlcv["Open"], high=ohlcv["High"],
        low=ohlcv["Low"], close=ohlcv["Close"], name="OHLCV",
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        showlegend=False,
    ))

    # Row 1: EMA short & long
    traces_r1.append(go.Scatter(
        x=ema_data.index, y=ema_data["ema_short"],
        mode="lines", name=f"EMA {strategy.ema_short_period}",
        line=dict(color="#2196f3", width=1.5),
    ))
    traces_r1.append(go.Scatter(
        x=ema_data.index, y=ema_data["ema_long"],
        mode="lines", name=f"EMA {strategy.ema_long_period}",
        line=dict(color="#ff9800", width=1.5),
    ))

    # Row 1: Buy/sell signal markers (strategy-computed)
    buy_signal_dates = ema_data.index[buy_signal]
    if len(buy_signal_dates):
        traces_r1.append(go.Scatter(
            x=buy_signal_dates,
            y=ohlcv.loc[buy_signal_dates, "Low"] * 0.995,
            mode="markers", name="Buy Signal",
            marker=dict(symbol="triangle-up-open", size=8,
                        color="#00c853", line=dict(width=1)),
            opacity=0.5,
        ))

    sell_signal_dates = ema_data.index[sell_signal]
    if len(sell_signal_dates):
        traces_r1.append(go.Scatter(
            x=sell_signal_dates,
            y=ohlcv.loc[sell_signal_dates, "High"] * 1.005,
            mode="markers", name="Sell Signal",
            marker=dict(symbol="triangle-down-open", size=8,
                        color="#ff1744", line=dict(width=1)),
            opacity=0.5,
        ))

    # Row 1: Actual order markers
    if sym_buys:
        traces_r1.append(go.Scatter(
            x=[o.created_at for o in sym_buys],
            y=[o.price for o in sym_buys],
            mode="markers", name="Buy Order",
            marker=dict(symbol="triangle-up", size=14, color="#00c853",
                        line=dict(width=2, color="white")),
            hovertemplate="<b>BUY</b><br>Date: %{x}<br>Price: €%{y:.2f}<extra></extra>",
        ))
    if sym_sells:
        traces_r1.append(go.Scatter(
            x=[o.created_at for o in sym_sells],
            y=[o.price for o in sym_sells],
            mode="markers", name="Sell Order",
            marker=dict(symbol="triangle-down", size=14, color="#ff1744",
                        line=dict(width=2, color="white")),
            hovertemplate="<b>SELL</b><br>Date: %{x}<br>Price: €%{y:.2f}<extra></extra>",
        ))

    # Row 2: RSI
    traces_r2.append(go.Scatter(
        x=rsi_data.index, y=rsi_data["rsi"],
        mode="lines", name="RSI",
        line=dict(color="#ab47bc", width=1.5),
    ))

    # Row 3: Volume (use Scatter fill instead of Bar for reliable rendering)
    vol_col = "Volume" if "Volume" in ohlcv.columns else "volume"
    vol = ohlcv[vol_col] if vol_col in ohlcv.columns else pd.Series(0, index=ohlcv.index)
    traces_r3.append(go.Scatter(
        x=ohlcv.index, y=vol, name="Volume",
        fill="tozeroy", fillcolor="rgba(100,149,237,0.3)",
        line=dict(color="rgba(100,149,237,0.6)", width=0.5),
        showlegend=False,
    ))

    return traces_r1, traces_r2, traces_r3, len(sym_buys), len(sym_sells)


# ── Precompute traces for every symbol ───────────────────────────
symbol_traces = {}
for sym in in_sample_assets:
    symbol_traces[sym] = build_symbol_traces(
        sym, strategy, buy_orders, sell_orders, start_date, end_date,
    )

# ── Build figure with first symbol visible, rest hidden ──────────
first_sym = in_sample_assets[0]
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.04,
    row_heights=[0.6, 0.25, 0.15],
    subplot_titles=(
        f"Price & EMA Crossover",
        f"RSI ({strategy.rsi_period})",
        "Volume",
    ),
)

# Track how many traces each symbol has, and their start index
trace_index_map = {}  # sym -> (start_idx, count)
total_traces = 0

for sym in in_sample_assets:
    r1, r2, r3, n_buys, n_sells = symbol_traces[sym]
    start_idx = total_traces
    is_first = (sym == first_sym)

    for t in r1:
        t.visible = is_first
        fig.add_trace(t, row=1, col=1)
    for t in r2:
        t.visible = is_first
        fig.add_trace(t, row=2, col=1)
    for t in r3:
        t.visible = is_first
        fig.add_trace(t, row=3, col=1)

    count = len(r1) + len(r2) + len(r3)
    trace_index_map[sym] = (start_idx, count)
    total_traces += count

# ── Build dropdown buttons ───────────────────────────────────────
buttons = []
for sym in in_sample_assets:
    _, _, _, n_buys, n_sells = symbol_traces[sym]
    visibility = [False] * total_traces
    start_idx, count = trace_index_map[sym]
    for i in range(start_idx, start_idx + count):
        visibility[i] = True

    buttons.append(dict(
        label=f"{sym} ({n_buys}B / {n_sells}S)",
        method="update",
        args=[
            {"visible": visibility},
            {"title": f"{sym}/EUR — EMA Crossover + RSI Filter ({n_buys} buys, {n_sells} sells)"},
        ],
    ))

# ── RSI threshold lines & shading ───────────────────────────────
fig.add_hline(
    y=strategy.rsi_overbought_threshold, row=2, col=1,
    line=dict(color="#ff1744", width=1, dash="dash"),
    annotation_text="Overbought", annotation_position="top right",
)
fig.add_hline(
    y=strategy.rsi_oversold_threshold, row=2, col=1,
    line=dict(color="#00c853", width=1, dash="dash"),
    annotation_text="Oversold", annotation_position="bottom right",
)
fig.add_hrect(
    y0=strategy.rsi_overbought_threshold, y1=100, row=2, col=1,
    fillcolor="rgba(255,23,68,0.08)", line_width=0,
)
fig.add_hrect(
    y0=0, y1=strategy.rsi_oversold_threshold, row=2, col=1,
    fillcolor="rgba(0,200,83,0.08)", line_width=0,
)

# ── Layout with dropdown ────────────────────────────────────────
_, _, _, first_buys, first_sells = symbol_traces[first_sym]
fig.update_layout(
    title=f"{first_sym}/EUR — EMA Crossover + RSI Filter ({first_buys} buys, {first_sells} sells)",
    updatemenus=[dict(
        type="dropdown",
        direction="down",
        x=0.0,
        xanchor="left",
        y=1.15,
        yanchor="top",
        buttons=buttons,
        bgcolor="#f0f0f0",
        font=dict(color="black"),
    )],
    xaxis_rangeslider_visible=False,
    template="plotly_white",
    height=850,
    showlegend=True,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig.update_yaxes(title_text="Price (EUR)", row=1, col=1)
fig.update_yaxes(title_text="RSI", row=2, col=1, range=[0, 100])
fig.update_yaxes(title_text="Volume", row=3, col=1)

fig.show()
