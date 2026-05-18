#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股全市场数据补全脚本
======================
从东方财富(westock-data)批量下载A股个股历史K线数据
支持断点续传、限流重试、定时任务分批执行

目标：3268只A股（沪深300 + 沪股通1542 + 深股通1727，去重后）
已有：544只，缺口约2770只

批量模式：100只/批，2600条历史(≈10年)，约14秒/批
总预计：~28批 ≈ 6-7分钟全量完成
定时任务模式：每小时拉取一批100只，约28小时全部完成
"""

import os, sys, json, time, subprocess, logging, argparse, re
from datetime import datetime

# ── 配置 ──
WORKSPACE = '/data/workspace'
DATA_DIR = os.path.join(WORKSPACE, 'back_trader_stocks', 'a')
PROGRESS_FILE = os.path.join(WORKSPACE, 'back_trader_stocks', 'a_stock_full_progress.json')
LOG_FILE = os.path.join(WORKSPACE, 'back_trader_stocks', 'a_stock_full_fetch.log')
CODE_LIST_FILE = '/tmp/all_cn_stock_codes.txt'
WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'

BATCH_SIZE = 100
KLINE_LIMIT = 2600
RATE_LIMIT_WAIT = 2

os.makedirs(DATA_DIR, exist_ok=True)

# ── 日志 ──
logger = logging.getLogger('a_stock_fetch')
logger.setLevel(logging.INFO)
logger.handlers.clear()
fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(fmt)
logger.addHandler(sh)
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setFormatter(fmt)
logger.addHandler(fh)


def get_existing_codes():
    """获取本地已有的A股代码集合"""
    existing = set()
    for f in os.listdir(DATA_DIR):
        if not f.endswith('.csv'):
            continue
        parts = f.replace('.csv', '').split('_')
        code = parts[0]
        suffix = parts[1] if len(parts) > 1 else ''
        if suffix == 'XSHG':
            existing.add(f'sh{code}')
        elif suffix == 'XSHE':
            existing.add(f'sz{code}')
        else:
            if code.startswith('6') or code.startswith('5'):
                existing.add(f'sh{code}')
            else:
                existing.add(f'sz{code}')
    return existing


def get_target_codes():
    """获取目标A股代码列表"""
    if os.path.exists(CODE_LIST_FILE):
        with open(CODE_LIST_FILE) as f:
            codes = [line.strip() for line in f if line.strip()]
        codes = [c for c in codes if not (c.startswith('sh000') or c.startswith('sz399'))]
        return sorted(set(codes))
    return []


def code_to_filename(code):
    """将代码转换为文件名格式"""
    if code.startswith('sh'):
        num = code[2:]
        return f'{num}_XSHG.csv'
    elif code.startswith('sz'):
        num = code[2:]
        return f'{num}_XSHE.csv'
    return None


def fetch_kline_batch(codes, limit=KLINE_LIMIT):
    """批量获取K线数据"""
    if not codes:
        return {}, []
    
    codes_str = ','.join(codes)
    cmd = f'node {WESTOCK_SCRIPT} kline {codes_str} --period day --limit {limit} --fq bfq'
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not result.stdout.strip():
            return {}, list(codes)
        
        lines = result.stdout.strip().split('\n')
        headers = None
        all_data = {}
        failed = list(codes)
        
        for line in lines:
            line = line.strip()
            if not line.startswith('|'):
                continue
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if all(c == '---' for c in cells):
                continue
            if 'date' in [c.lower() for c in cells]:
                headers = cells
                continue
            if headers and len(cells) >= len(headers):
                row = dict(zip(headers, cells))
                symbol = row.get('symbol', '')
                if symbol:
                    if symbol not in all_data:
                        all_data[symbol] = []
                        if symbol in failed:
                            failed.remove(symbol)
                    all_data[symbol].append(row)
        
        import pandas as pd
        result_data = {}
        for symbol, rows in all_data.items():
            try:
                df = pd.DataFrame(rows)
                rename_map = {
                    'date': 'Date', 'open': 'Open', 'last': 'Close',
                    'high': 'High', 'low': 'Low', 'volume': 'Volume', 'amount': 'Amount'
                }
                df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
                for col in ['Open', 'High', 'Low', 'Close', 'Volume', 'Amount']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                if 'Date' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'])
                    df = df.sort_values('Date').reset_index(drop=True)
                keep_cols = [c for c in ['Date', 'Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
                df = df[keep_cols]
                if 'Close' in df.columns and len(df) >= 100:
                    result_data[symbol] = df
            except Exception as e:
                logger.warning(f'解析{symbol}数据失败: {e}')
                failed.append(symbol)
        
        return result_data, failed
        
    except subprocess.TimeoutExpired:
        logger.error(f'批量请求超时 ({len(codes)}只)')
        return {}, list(codes)
    except Exception as e:
        logger.error(f'批量请求异常: {e}')
        return {}, list(codes)


def save_csv(code, df):
    """保存CSV到本地"""
    fname = code_to_filename(code)
    if fname is None:
        return False
    fpath = os.path.join(DATA_DIR, fname)
    try:
        df.to_csv(fpath, index=False)
        return True
    except Exception as e:
        logger.error(f'保存{code}失败: {e}')
        return False


def load_progress():
    """加载下载进度"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_progress(progress):
    """保存下载进度"""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def run_full_fetch():
    """全量下载模式：一次性下载所有缺失数据"""
    existing = get_existing_codes()
    target = get_target_codes()
    missing = sorted(set(target) - existing)
    
    logger.info(f'=== A股全市场数据补全 ===')
    logger.info(f'目标: {len(target)}只, 已有: {len(existing)}只, 缺口: {len(missing)}只')
    
    if not missing:
        logger.info('所有数据已完整，无需下载')
        return
    
    progress = load_progress()
    already_done = set(k for k, v in progress.items() if v.get('status') == 'success')
    to_download = [c for c in missing if c not in already_done]
    
    logger.info(f'本次需下载: {len(to_download)}只 (已跳过{len(already_done)}只)')
    
    total_batches = (len(to_download) + BATCH_SIZE - 1) // BATCH_SIZE
    total_success = 0
    total_fail = 0
    
    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(to_download))
        batch_codes = to_download[start:end]
        
        logger.info(f'批次 {batch_idx+1}/{total_batches}: 下载 {len(batch_codes)}只 ({batch_codes[0]}~{batch_codes[-1]})')
        
        data, failed = fetch_kline_batch(batch_codes)
        
        batch_success = 0
        for code, df in data.items():
            if save_csv(code, df):
                batch_success += 1
                progress[code] = {
                    'status': 'success',
                    'rows': len(df),
                    'date_range': f'{df.Date.min()}~{df.Date.max()}' if 'Date' in df.columns else 'unknown',
                    'downloaded_at': datetime.now().isoformat()
                }
            else:
                progress[code] = {'status': 'save_failed', 'downloaded_at': datetime.now().isoformat()}
        
        for code in failed:
            if code not in progress:
                progress[code] = {'status': 'fetch_failed', 'downloaded_at': datetime.now().isoformat()}
        
        total_success += batch_success
        total_fail += len(failed)
        
        save_progress(progress)
        logger.info(f'批次完成: 成功{batch_success}, 失败{len(failed)}, 累计成功{total_success}/{len(to_download)}')
        
        if batch_idx < total_batches - 1:
            time.sleep(RATE_LIMIT_WAIT)
    
    logger.info(f'=== 下载完成 === 总成功: {total_success}, 总失败: {total_fail}')


def run_scheduled_batch():
    """定时任务模式：每小时下载一批100只"""
    existing = get_existing_codes()
    target = get_target_codes()
    missing = sorted(set(target) - existing)
    
    progress = load_progress()
    already_done = set(k for k, v in progress.items() if v.get('status') == 'success')
    to_download = [c for c in missing if c not in already_done]
    
    if not to_download:
        logger.info('所有A股数据已完整，无需下载')
        return
    
    batch_codes = to_download[:BATCH_SIZE]
    logger.info(f'=== 定时批次下载 === 剩余: {len(to_download)}只, 本次: {len(batch_codes)}只')
    
    data, failed = fetch_kline_batch(batch_codes)
    
    batch_success = 0
    for code, df in data.items():
        if save_csv(code, df):
            batch_success += 1
            progress[code] = {
                'status': 'success',
                'rows': len(df),
                'date_range': f'{df.Date.min()}~{df.Date.max()}' if 'Date' in df.columns else 'unknown',
                'downloaded_at': datetime.now().isoformat()
            }
        else:
            progress[code] = {'status': 'save_failed', 'downloaded_at': datetime.now().isoformat()}
    
    for code in failed:
        if code not in progress:
            progress[code] = {'status': 'fetch_failed', 'downloaded_at': datetime.now().isoformat()}
    
    save_progress(progress)
    
    remaining = len(to_download) - batch_success
    logger.info(f'批次完成: 成功{batch_success}, 失败{len(failed)}, 剩余{remaining}只')
    
    if remaining <= 0:
        logger.info('A股全市场数据补全完成！')
    else:
        logger.info(f'预计还需 {remaining // BATCH_SIZE + 1} 个批次')


def refresh_code_list():
    """重新从东方财富获取最新A股代码列表"""
    logger.info('正在更新A股代码列表...')
    all_codes = set()
    
    logger.info('获取沪深300成分股...')
    cmd = f'node {WESTOCK_SCRIPT} index sh000300 --limit 300'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    codes = re.findall(r'(sh|sz)\d{6}', result.stdout)
    all_codes.update(codes)
    logger.info(f'沪深300: {len(codes)}只')
    
    logger.info('获取沪股通成分股...')
    for offset in range(0, 1600, 100):
        cmd = f'node {WESTOCK_SCRIPT} lgt sh --limit 100 --offset {offset}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        codes = re.findall(r'(sh|sz)\d{6}', result.stdout)
        if not codes:
            break
        all_codes.update(codes)
        logger.info(f'  沪股通 offset={offset}: +{len(codes)}只')
    
    logger.info('获取深股通成分股...')
    for offset in range(0, 1800, 100):
        cmd = f'node {WESTOCK_SCRIPT} lgt sz --limit 100 --offset {offset}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        codes = re.findall(r'(sh|sz)\d{6}', result.stdout)
        if not codes:
            break
        all_codes.update(codes)
        logger.info(f'  深股通 offset={offset}: +{len(codes)}只')
    
    all_codes = set(c for c in all_codes if not (c.startswith('sh000') or c.startswith('sz399')))
    
    with open(CODE_LIST_FILE, 'w') as f:
        for code in sorted(all_codes):
            f.write(code + '\n')
    
    logger.info(f'代码列表已更新: {len(all_codes)}只 -> {CODE_LIST_FILE}')
    return sorted(all_codes)


def show_status():
    """查看当前进度"""
    existing = get_existing_codes()
    target = get_target_codes()
    progress = load_progress()
    
    success_count = sum(1 for v in progress.values() if v.get('status') == 'success')
    fail_count = sum(1 for v in progress.values() if v.get('status') != 'success')
    missing = set(target) - existing
    missing_still = len(missing)
    
    print(f'=== A股数据补全进度 ===')
    print(f'目标: {len(target)}只')
    print(f'本地已有: {len(existing)}只')
    print(f'进度记录(成功): {success_count}只')
    print(f'进度记录(失败): {fail_count}只')
    print(f'仍需下载: {missing_still}只')
    print(f'完成率: {(len(target) - missing_still) / max(1, len(target)) * 100:.1f}%')
    
    if missing_still > 0:
        print(f'预计还需: {missing_still // BATCH_SIZE + 1} 批次')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='A股全市场数据补全')
    parser.add_argument('--mode', choices=['full', 'batch', 'refresh', 'status'], default='batch',
                        help='full=全量一次性下载, batch=定时任务单批次, refresh=刷新代码列表, status=查看进度')
    args = parser.parse_args()
    
    if args.mode == 'full':
        run_full_fetch()
    elif args.mode == 'batch':
        run_scheduled_batch()
    elif args.mode == 'refresh':
        refresh_code_list()
    elif args.mode == 'status':
        show_status()
