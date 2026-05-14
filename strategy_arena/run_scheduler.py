import sys
import io
import os

# Force UTF-8 encoding for stdout/stderr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

WORKSPACE_DIR = r'C:\Users\blakehao\.qclaw\workspace\workspace_full_20260430'
STRATEGY_DIR = os.path.join(WORKSPACE_DIR, 'strategy_arena')
LOCAL_DATA_DIR = os.path.join(WORKSPACE_DIR, 'back_trader_stocks')
LOCAL_ETF_DIR = os.path.join(LOCAL_DATA_DIR, 'etf')

sys.path.insert(0, STRATEGY_DIR)

import pandas as pd
import time
import numpy as np
from typing import List, Tuple

from cross_regime_scheduler import (
    ALL_ASSETS_6, scan_strategies
)

def load_etf_data_local(symbol: str):
    """降级：从本地CSV加载ETF数据"""
    filepath = os.path.join(LOCAL_ETF_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df.columns = [c.strip().capitalize() for c in df.columns]
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df
    except Exception:
        return None

def patched_load_etf_data(assets: List[str] = None) -> Tuple[pd.DataFrame, bool]:
    """Patched: local ETF CSV only (no westock-data, Windows-safe)."""
    if assets is None:
        assets = ALL_ASSETS_6

    print(f"📦 加载ETF数据（本地CSV，Windows-safe）...")
    etf_data = {}
    has_survivorship_bias = True

    for sym in assets:
        df = load_etf_data_local(sym)
        if df is not None and len(df) > 100:
            etf_data[sym] = df['Close']
            print(f"  ✅ {sym}: {len(df)} 个交易日 (本地CSV)")
        else:
            print(f"  ❌ {sym}: 数据不可用")

    if not etf_data:
        raise ValueError("无法加载任何ETF数据")

    close_prices = pd.DataFrame(etf_data).dropna(how='all').sort_index()
    close_prices = close_prices.ffill().bfill()

    print(f"📊 合并后数据: {len(close_prices)} 个交易日 ({close_prices.index[0]} ~ {close_prices.index[-1]})")
    print(f"⚠️ 幸存者偏差标记: {has_survivorship_bias} (ETF固定池，非动态历史成分股)")

    return close_prices, has_survivorship_bias

# Monkey-patch
import cross_regime_scheduler
cross_regime_scheduler.load_all_etf_data = patched_load_etf_data

if __name__ == '__main__':
    result = scan_strategies()
    print(f"\n✅ 扫描完成，耗时{result['duration_seconds']:.0f}秒")
    if result.get('new_best'):
        print(f"🆕 新上榜策略: {result['new_best']}")
    print(f"📊 搜索方式: {result.get('search_method', 'variant')}")
    print(f"📊 Pine否决: {result.get('pine_vetoed', 0)}个")
    print(f"📊 无风险利率: {result.get('risk_free_rate', 0):.4f}")
