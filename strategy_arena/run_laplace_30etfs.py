#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run Laplace-Gaussian backtest (30 ETFs, 2016-2026)
Based on 拉普拉斯_30etfs.py
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import subprocess
import os

script = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_30etfs.py'

print("="*80)
print("Running Laplace-Gaussian Backtest (30 ETFs, 2016-2026)")
print("="*80)
print(f"Script: {script}")
print(f"Data: back_trader_stocks/etf_qixing/ (30 ETFs CSV)")
print("="*80)

if not os.path.exists(script):
    print(f"ERROR: Script not found: {script}")
    sys.exit(1)

# Run backtest
result = subprocess.run(
    ['python', script],
    cwd=r'C:\Users\blakehao\.qclaw\workspace\strategy_arena',
    capture_output=True,
    text=True,
    encoding='utf-8'
)

print("\n" + "="*80)
print("BACKTEST OUTPUT:")
print("="*80)
print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)

if result.stderr:
    print("\n" + "="*80)
    print("STDERR:")
    print("="*80)
    print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)

print("\n" + "="*80)
print(f"Return code: {result.returncode}")
print("="*80)
