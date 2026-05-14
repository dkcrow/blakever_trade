#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股全量数据扩展脚本 v2
======================
目标：将本地A股数据从512只扩展到5000+只（全覆盖）
包括：ROE、净利润等基本面数据

策略：
1. 先通过sector/index批量获取全A股代码（快速）
2. 再分批下载K线数据和基本面数据（每批100只）
3. 限流时等待30分钟后重试
4. 支持断点续传（cn_stock_progress.json）
5. 完成条件：成功获取数量超过98%

数据源：westock-data（东方财富）
输出目录：
  K线: /data/workspace/back_trader_stocks/a/
  基本面: /data/workspace/back_trader_stocks/a_fundamentals/
"""

import subprocess, json, os, time, sys, re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'
WORKSPACE_DIR = '/data/workspace'
DATA_DIR = '/data/workspace/back_trader_stocks/a'
FUND_DIR = '/data/workspace/back_trader_stocks/a_fundamentals'
PROGRESS_FILE = '/data/workspace/strategy_arena/cn_stock_progress.json'

# Create directories
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FUND_DIR, exist_ok=True)

# Retry configuration
MAX_RETRIES = 5
RATE_LIMIT_WAIT = 1800  # 30 minutes in seconds
REQUEST_TIMEOUT = 120
BATCH_SIZE = 100  # Process stocks in batches


def run_westock(cmd_args, timeout=REQUEST_TIMEOUT):
    """Execute westock-data CLI command"""
    cmd = ['node', WESTOCK_SCRIPT] + cmd_args
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=WORKSPACE_DIR
            )
            # Check for rate limiting
            if result.stderr and ('限流' in result.stderr or '429' in result.stderr or 'limit' in result.stderr.lower()):
                print(f"  ⚠️ 限流检测 (attempt {attempt+1}/{MAX_RETRIES}), 等待{RATE_LIMIT_WAIT//60}分钟...")
                time.sleep(RATE_LIMIT_WAIT)
                continue
            return result
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ 超时 (attempt {attempt+1}/{MAX_RETRIES})，重试...")
            time.sleep(10)
        except Exception as e:
            print(f"  ❌ 执行错误: {e}")
            time.sleep(10)
    return None


def load_progress():
    """Load progress from file"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {
        'total_codes': [],
        'downloaded_kline': {},
        'downloaded_fundamentals': {},
        'started_at': datetime.now().isoformat(),
        'last_updated': datetime.now().isoformat(),
    }


def save_progress(progress):
    """Save progress to file"""
    progress['last_updated'] = datetime.now().isoformat()
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def parse_stock_codes(text):
    """Parse stock codes from westock-data table output"""
    codes = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line.startswith('|') and not line.startswith('| ---') and not line.startswith('| code') and not line.startswith('| 序号'):
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if len(cols) >= 1:
                code = cols[0].strip()
                if re.match(r'^(sh|sz)\d{6}$', code):
                    codes.append(code)
    return codes


def get_all_a_stock_codes():
    """Get all A-share stock codes via westock-data"""
    progress = load_progress()
    all_codes = set(progress.get('total_codes', []))
    
    if len(all_codes) > 5000:
        print(f"  ✅ 已有{len(all_codes)}只A股代码，跳过获取")
        return list(all_codes)
    
    print(f"📦 获取全A股代码列表...")
    print(f"  当前已有: {len(all_codes)}只, 目标: 5000+只")
    
    # Method 1: Sector-based enumeration (SW L1 industries)
    sector_total = 0
    for sector_code in SW1_SECTORS:
        result = run_westock(['sector', sector_code, '--limit', '500'])
        if result and result.stdout:
            codes = parse_stock_codes(result.stdout)
            new_codes = [c for c in codes if c not in all_codes]
            all_codes.update(codes)
            sector_total += len(codes)
        time.sleep(0.5)
    
    # Method 2: Index constituents
    index_codes = [
        'sh000001',  # 上证指数
        'sh000300',  # 沪深300
        'sh000905',  # 中证500
        'sh000852',  # 中证1000
        'sh000986',  # 中证2000
        'sz399001',  # 深证成指
        'sz399006',  # 创业板指
        'sz399106',  # 深证综指
    ]
    
    for idx in index_codes:
        result = run_westock(['index', idx])
        if result and result.stdout:
            codes = parse_stock_codes(result.stdout)
            new_codes = [c for c in codes if c not in all_codes]
            all_codes.update(codes)
        time.sleep(0.5)
    
    # Method 3: Prefix-based search
    for prefix in ['sh600', 'sh601', 'sh603', 'sh605', 'sz000', 'sz001', 'sz002', 'sz003', 'sz300', 'sz301', 'sh688', 'sz688']:
        result = run_westock(['search', prefix, '--limit', '500'])
        if result and result.stdout:
            codes = parse_stock_codes(result.stdout)
            all_codes.update(codes)
        time.sleep(0.3)
    
    print(f"  ✅ 总计获取A股代码: {len(all_codes)}只")
    
    progress['total_codes'] = list(all_codes)
    save_progress(progress)
    
    return list(all_codes)


def download_kline_data(stock_codes, lookback_years=11):
    """Download K-line (OHLCV) data for all stocks"""
    progress = load_progress()
    downloaded = progress.get('downloaded_kline', {})
    
    total = len(stock_codes)
    already = len(downloaded)
    to_download = [c for c in stock_codes if c not in downloaded]
    
    print(f"\n📊 下载K线数据: {len(to_download)}只待下载 (已完成{already}/{total})")
    
    success_count = already
    fail_count = 0
    start_date = (datetime.now() - timedelta(days=lookback_years*365+30)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    
    for i, code in enumerate(to_download):
        norm_code = normalize_stock_code(code)
        filepath = os.path.join(DATA_DIR, f'{norm_code}.csv')
        
        # Skip if already downloaded recently (within 1 day)
        if os.path.exists(filepath) and (datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))).days < 1:
            downloaded[code] = datetime.now().isoformat()
            success_count += 1
            continue
        
        result = run_westock(['kline', code, '--start', start_date, '--end', end_date, '--period', 'day'])
        if result and result.stdout and len(result.stdout) > 100:
            try:
                df = parse_kline_table(result.stdout, code)
                if df is not None and len(df) > 100:
                    df.to_csv(filepath, index=True)
                    downloaded[code] = datetime.now().isoformat()
                    success_count += 1
                    if (i+1) % 50 == 0 or (i+1) == len(to_download):
                        print(f"  [{i+1}/{len(to_download)}] ✅ {code} -> {filepath} ({len(df)} rows)")
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
        else:
            fail_count += 1
        
        # Save progress every BATCH_SIZE stocks
        if (i+1) % BATCH_SIZE == 0:
            progress['downloaded_kline'] = downloaded
            save_progress(progress)
            print(f"  📝 进度已保存 ({i+1}/{len(to_download)} 已处理)")
        
        time.sleep(0.3)
    
    progress['downloaded_kline'] = downloaded
    save_progress(progress)
    
    print(f"  ✅ K线下载完成: 成功{success_count}, 失败{fail_count}")
    return downloaded


def download_fundamentals(stock_codes):
    """Download fundamental data (ROE, net profit, etc.) for all stocks"""
    progress = load_progress()
    downloaded = progress.get('downloaded_fundamentals', {})
    
    total = len(stock_codes)
    already = len(downloaded)
    to_download = [c for c in stock_codes if c not in downloaded]
    
    print(f"\n📊 下载基本面数据: {len(to_download)}只待下载 (已完成{already}/{total})")
    
    success_count = already
    fail_count = 0
    
    for i, code in enumerate(to_download):
        norm_code = normalize_stock_code(code)
        filepath = os.path.join(FUND_DIR, f'{norm_code}.json')
        
        # Skip if already downloaded recently
        if os.path.exists(filepath) and (datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))).days < 7:
            downloaded[code] = datetime.now().isoformat()
            success_count += 1
            continue
        
        finance_data = {'code': code, 'norm_code': norm_code, 'updated_at': datetime.now().isoformat()}
        
        # 1. Profile (基本信息)
        result = run_westock(['profile', code])
        if result and result.stdout and len(result.stdout) > 50:
            finance_data['profile'] = parse_key_value(result.stdout)
        time.sleep(0.3)
        
        # 2. Finance (财务数据)
        result = run_westock(['finance', code])
        if result and result.stdout and len(result.stdout) > 50:
            finance_data['finance'] = parse_table_data(result.stdout)
        time.sleep(0.3)
        
        # 3. Valuation
        result = run_westock(['valuation', code])
        if result and result.stdout and len(result.stdout) > 50:
            finance_data['valuation'] = parse_table_data(result.stdout)
        time.sleep(0.3)
        
        # 4. Cashflow
        result = run_westock(['cashflow', code])
        if result and result.stdout and len(result.stdout) > 50:
            finance_data['cashflow'] = parse_table_data(result.stdout)
        time.sleep(0.3)
        
        # Save fundamental data
        if any(k in finance_data for k in ['profile', 'finance', 'valuation', 'cashflow']):
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(finance_data, f, ensure_ascii=False, indent=2)
            downloaded[code] = datetime.now().isoformat()
            success_count += 1
            if (i+1) % 50 == 0 or (i+1) == len(to_download):
                print(f"  [{i+1}/{len(to_download)}] ✅ {code} -> {filepath}")
        else:
            fail_count += 1
        
        # Save progress every BATCH_SIZE
        if (i+1) % BATCH_SIZE == 0:
            progress['downloaded_fundamentals'] = downloaded
            save_progress(progress)
            print(f"  📝 进度已保存 ({i+1}/{len(to_download)} 已处理)")
        
        time.sleep(0.5)
    
    progress['downloaded_fundamentals'] = downloaded
    save_progress(progress)
    
    print(f"  ✅ 基本面下载完成: 成功{success_count}, 失败{fail_count}")
    return downloaded


def normalize_stock_code(code):
    """Convert code like sh600519 to 600519_XSHG"""
    if code.startswith('sh'):
        return f'{code[2:]}_XSHG'
    elif code.startswith('sz'):
        return f'{code[2:]}_XSHE'
    return code


def parse_kline_table(text, stock_code):
    """Parse K-line data from westock-data table output into DataFrame"""
    rows = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line.startswith('|') and not line.startswith('| ---') and not line.startswith('| date') and not line.startswith('| 日期'):
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if len(cols) >= 6:
                try:
                    date_str = cols[0]
                    open_p = float(cols[1])
                    high_p = float(cols[2])
                    low_p = float(cols[3])
                    close_p = float(cols[4])
                    volume = float(cols[5]) if len(cols) > 5 else 0
                    rows.append({
                        'Date': pd.to_datetime(date_str),
                        'Open': open_p,
                        'High': high_p,
                        'Low': low_p,
                        'Close': close_p,
                        'Volume': volume,
                    })
                except (ValueError, TypeError):
                    continue
    
    if not rows:
        return None
    
    df = pd.DataFrame(rows).set_index('Date').sort_index()
    return df


def parse_key_value(text):
    """Parse key-value pair output from westock-data"""
    data = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if ':' in line or '：' in line:
            parts = re.split(r'[:：]', line, maxsplit=1)
            if len(parts) == 2:
                key = parts[0].strip()
                value = parts[1].strip()
                data[key] = value
    return data


def parse_table_data(text):
    """Parse table data from westock-data output"""
    data = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if line.startswith('|') and not line.startswith('| ---'):
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if len(cols) >= 2:
                metric = cols[0]
                values = cols[1:]
                data[metric] = values
    return data


def main():
    print("=" * 70)
    print("  🔥 A股全量数据扩展 v2")
    print("  目标: 5000+只股票 + 基本面数据(ROE/净利润等)")
    print("  数据源: westock-data (东方财富)")
    print("  限流策略: 每30分钟重试")
    print("  进度文件: " + PROGRESS_FILE)
    print("=" * 70)
    
    # Step 1: Get all A-stock codes
    stock_codes = get_all_a_stock_codes()
    print(f"\n📦 第1步完成: 获取A股代码 {len(stock_codes)}只")
    
    if len(stock_codes) < 4000:
        print(f"  ⚠️ 获取数量不足(仅{len(stock_codes)}只)，将继续尝试补充...")
    
    # Step 2: Download K-line data
    kline_downloaded = download_kline_data(stock_codes, lookback_years=11)
    print(f"\n📦 第2步完成: K线数据已下载 {len(kline_downloaded)}只")
    
    # Step 3: Download fundamental data
    fund_downloaded = download_fundamentals(stock_codes)
    print(f"\n📦 第3步完成: 基本面数据已下载 {len(fund_downloaded)}只")
    
    # Summary
    total = len(stock_codes)
    kline_success = len(kline_downloaded)
    fund_success = len(fund_downloaded)
    completion_rate = kline_success / total * 100 if total > 0 else 0
    fund_completion = fund_success / total * 100 if total > 0 else 0
    
    print(f"\n{'=' * 70}")
    print(f"  📊 扩展结果汇总")
    print(f"  A股代码: {total}只")
    print(f"  K线数据: {kline_success}只 ({completion_rate:.1f}%)")
    print(f"  基本面数据: {fund_success}只 ({fund_completion:.1f}%)")
    print(f"  K线目录: {DATA_DIR}")
    print(f"  基本面目录: {FUND_DIR}")
    
    if completion_rate >= 98:
        print(f"\n  ✅ K线完成率{completion_rate:.1f}% ≥ 98%，可以删除定时任务")
    else:
        print(f"\n  ⚠️ K线完成率{completion_rate:.1f}% < 98%，需要继续运行定时任务")
    
    if fund_completion >= 98:
        print(f"  ✅ 基本面完成率{fund_completion:.1f}% ≥ 98%，可以删除定时任务")
    else:
        print(f"  ⚠️ 基本面完成率{fund_completion:.1f}% < 98%，需要继续运行定时任务")
    
    print(f"{'=' * 70}")
    
    return {
        'total': total,
        'kline_success': kline_success,
        'fund_success': fund_success,
        'completion_rate': completion_rate,
        'fund_completion': fund_completion,
    }


if __name__ == '__main__':
    result = main()
