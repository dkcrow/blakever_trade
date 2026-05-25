#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股安全资产ETF数据获取器（定时版）- 腾讯财经接口
=====================================================
主数据源：腾讯财经港股K线API（稳定、无限流）
备选数据源：westock-data、yfinance

用法：
  python hk_etf_fetcher.py run       # 主执行
  python hk_etf_fetcher.py status    # 查看状态
  python hk_etf_fetcher.py fetch 03110  # 手动获取单只
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# ── 配置 ──
WORKSPACE = '/data/workspace'
DATA_DIR = os.path.join(WORKSPACE, 'back_trader_stocks', 'hk_etf')
PROGRESS_FILE = os.path.join(DATA_DIR, 'hk_etf_progress.json')
LOG_FILE = os.path.join(DATA_DIR, 'hk_etf_fetch.log')

WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'

# 腾讯财经港股K线API
TENCENT_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'

# 港股ETF目标列表: (5位代码, 中文名, 优先级1-5)
HK_ETFS = [
    ('02800', '盈富基金(恒指ETF)', 5),
    ('03110', '恒生高股息率ETF', 5),
    ('02840', 'SPDR黄金ETF', 4),
    ('02819', 'iShares安硕恒生指数ETF', 4),
    ('02878', '南方恒生科技指数ETF', 4),
    ('03067', 'iShares安硕恒生科技ETF', 4),
    ('02845', 'iShares安硕明晟中国ETF', 3),
    ('02846', 'iShares安硕中国大型股ETF', 3),
    ('03040', '华夏沪深三百指数ETF', 3),
    ('03096', '华夏上证五十ETF', 3),
    ('03032', '易方达中证一百ETF', 3),
    ('02827', '嘉实明晟中国A股ETF', 3),
    ('02837', '南方A50ETF', 3),
    ('03039', '华夏恒生ESG指数ETF', 3),
    ('02828', '恒生中国企业ETF(H股ETF)', 3),  # 原错误代码03060，实际是02828
    ('02833', 'iShares安硕富时A50中国指数ETF', 2),  # ⚠️可能已退市，仅历史数据
    ('02836', '华夏沪深三百ETF', 3),
    ('02849', 'XDB中国ETF', 2),  # ⚠️可能已退市，仅历史数据
    ('03042', '华夏创业板ETF', 2),
    ('03049', 'FXI(中国大盘ETF)', 2),  # ⚠️可能已退市，仅历史数据
    ('03088', '华夏恒生科技ETF', 2),  # 原错误代码03014，实际是03088
    ('03033', '南方恒生科技ETF', 2),  # 原错误代码03025，实际是03033
    ('03005', 'X南方中五百ETF', 2),   # 原错误代码03045，实际是03005
    # 03138 标普上证五十ETF 在港股市场不存在，已移除
]

# 每轮最多处理几只ETF
MAX_PER_RUN = 5
# 请求间隔（秒）
REQUEST_DELAY = 0.5

# ── 日志 ──
os.makedirs(DATA_DIR, exist_ok=True)

logger = logging.getLogger('hk_etf_fetcher')
logger.setLevel(logging.INFO)
# 清除旧handler
logger.handlers.clear()
fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(fmt)
logger.addHandler(sh)

fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setFormatter(fmt)
logger.addHandler(fh)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'created': datetime.now().isoformat(), 'etfs': {}, 'runs': []}


def save_progress(progress):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def fetch_tencent_kline(code, start_date='2021-01-01', end_date=None):
    """通过腾讯财经API获取港股ETF日K线数据（前复权）
    
    接口格式: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
    参数: param=hkXXXXX,day,起始日,结束日,数据量,qfq
    
    返回数据格式: [[日期, 开盘, 收盘, 最高, 最低, 成交量], ...]
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    try:
        param = f'hk{code},day,{start_date},{end_date},1500,qfq'
        url = f'{TENCENT_KLINE_URL}?param={param}'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://gu.qq.com/',
        }
        
        resp = requests.get(url, timeout=15, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('code') != 0:
            logger.warning(f"腾讯接口返回非0 code: {data.get('msg', 'unknown')}")
            return None
        
        # 提取K线数据
        stock_key = f'hk{code}'
        stock_data = data.get('data', {}).get(stock_key, {})
        day_data = stock_data.get('day', [])
        
        if not day_data:
            logger.warning(f"腾讯接口 {code}: 无K线数据（可能该ETF不在腾讯数据库中）")
            return None
        
        # 转为DataFrame
        # 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量] (部分ETF可能有第7列换手率)
        df = pd.DataFrame(day_data)
        # 只保留前6列，忽略多余的列
        df = df.iloc[:, :6]
        df.columns = ['Date', 'Open', 'Close', 'High', 'Low', 'Volume']
        
        # 类型转换
        df['Date'] = pd.to_datetime(df['Date'])
        for col in ['Open', 'Close', 'High', 'Low', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 过滤无效行
        df = df[df['Close'] > 0]
        df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last').reset_index(drop=True)
        
        logger.info(f"腾讯接口 {code}: 获取 {len(df)} 天数据 ({df['Date'].min().strftime('%Y-%m-%d')} ~ {df['Date'].max().strftime('%Y-%m-%d')})")
        return df
        
    except Exception as e:
        logger.warning(f"腾讯接口 {code}: {str(e)[:100]}")
        return None


def fetch_westock(code, period='day', limit=5000):
    """通过 westock-data 获取K线数据（备选）"""
    import subprocess
    ws_symbol = f'hk{code}'
    try:
        cmd = f'node {WESTOCK_SCRIPT} kline {ws_symbol} --period {period} --limit {limit}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 3 and '|' in lines[0]:
                headers = [h.strip() for h in lines[0].split('|') if h.strip()]
                rows = []
                for line in lines[2:]:
                    cells = [c.strip() for c in line.split('|') if c.strip()]
                    if len(cells) == len(headers):
                        rows.append(dict(zip(headers, cells)))
                
                if rows:
                    df = pd.DataFrame(rows)
                    rename_map = {'date': 'Date', 'open': 'Open', 'last': 'Close',
                                  'high': 'High', 'low': 'Low', 'volume': 'Volume'}
                    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
                    
                    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    if 'Close' in df.columns:
                        df = df[df['Close'] > 0]
                    
                    if 'Date' in df.columns:
                        df['Date'] = pd.to_datetime(df['Date'])
                    
                    if not df.empty:
                        return df
    except Exception as e:
        logger.warning(f"westock {code}: {str(e)[:80]}")
    return None


def fetch_yfinance(code, period='max', max_retries=1):
    """通过 yfinance 获取数据（最后备选）"""
    import yfinance as yf
    yf_symbol = f'{code}.HK'
    
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(yf_symbol)
            hist = t.history(period=period)
            if not hist.empty:
                hist = hist.reset_index()
                return hist
        except Exception as e:
            logger.warning(f"yfinance {yf_symbol}: {str(e)[:80]}")
        if attempt < max_retries - 1:
            time.sleep(3)
    return None


def save_csv(df, filepath):
    """保存为标准格式CSV"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # 确保列名标准化
    rename_map = {'date': 'Date', 'open': 'Open', 'high': 'High', 'low': 'Low',
                  'close': 'Close', 'last': 'Close', 'adj close': 'Close',
                  'volume': 'Volume'}
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    
    keep_cols = [c for c in ['Date', 'Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
    df = df[keep_cols]
    
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
    
    df = df.drop_duplicates(subset='Date', keep='last').sort_values('Date')
    df.to_csv(filepath, index=False)
    return len(df)


def get_pending_etfs(progress):
    """返回优先排序的待处理ETF列表"""
    pending = []
    for code, name, priority in HK_ETFS:
        key = f'hk{code}'
        info = progress.get('etfs', {}).get(key, {})
        rows = info.get('rows', 0)
        last_date = info.get('last_date', '1970-01-01')
        status = info.get('status', '未获取')
        source = info.get('source', '-')
        
        # 检查实际CSV文件
        csv_path = os.path.join(DATA_DIR, f'{key}.csv')
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                actual_rows = len(df)
                if actual_rows != rows:
                    rows = actual_rows
            except:
                pass
        
        # 判断是否需要更新
        need_update = False
        if status != 'ok' or rows < 50:
            need_update = True
        else:
            try:
                days_since = (datetime.now() - datetime.strptime(last_date, '%Y-%m-%d')).days
                # 非交易日期间数据旧是正常的：周五到周一差3天，长假差更久
                # 只有数据超过7天旧才标记为需更新（排除周末/假期）
                if days_since >= 7:
                    need_update = True
            except:
                need_update = True
        
        if need_update:
            pending.append((priority, code, name, rows, last_date, status, source))
    
    pending.sort(key=lambda x: -x[0])  # 优先级高的排前面
    return pending


def run_fetch():
    logger.info("=" * 60)
    logger.info("港股ETF数据获取器（腾讯财经版）启动")
    logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    progress = load_progress()
    pending = get_pending_etfs(progress)
    
    if not pending:
        logger.info("所有港股ETF数据已是最新，无需处理")
        return None
    
    logger.info(f"待处理: {len(pending)} 只ETF（本次最多处理 {MAX_PER_RUN} 只）")
    
    to_process = pending[:MAX_PER_RUN]
    
    run_record = {
        'start': datetime.now().isoformat(),
        'success': 0,
        'failed': 0,
        'details': []
    }
    
    for priority, code, name, existing_rows, last_date, status, source in to_process:
        key = f'hk{code}'
        logger.info(f"\n▶ {name} ({code}) [优先级{priority}, 现有{existing_rows}行, {status}]")
        
        csv_path = os.path.join(DATA_DIR, f'{key}.csv')
        
        # 已有数据则增量更新
        start_date = '2021-01-01'
        existing_df = None
        if os.path.exists(csv_path):
            try:
                existing_df = pd.read_csv(csv_path)
                # 统一列名为大写
                col_rename = {'date': 'Date', 'open': 'Open', 'high': 'High', 
                              'low': 'Low', 'close': 'Close', 'volume': 'Volume'}
                existing_df = existing_df.rename(columns={k: v for k, v in col_rename.items() if k in existing_df.columns})
                if 'Date' in existing_df.columns and not existing_df.empty:
                    existing_df['Date'] = pd.to_datetime(existing_df['Date'])
                    last_csv_date = existing_df['Date'].max()
                    start_date = (last_csv_date - timedelta(days=5)).strftime('%Y-%m-%d')
            except:
                pass
        
        # ── 数据源1: 腾讯财经（主） ──
        data = fetch_tencent_kline(code, start_date=start_date)
        
        # ── 数据源2: westock-data（备） ──
        if data is None:
            data = fetch_westock(code)
            if data is not None:
                logger.info(f"  🔄 westock备选成功")
        
        # ── 数据源3: yfinance（最后） ──
        if data is None:
            data = fetch_yfinance(code, period='max', max_retries=1)
            if data is not None:
                logger.info(f"  🔄 yfinance备选成功")
        
        if data is not None:
            # 合并已有数据
            if existing_df is not None and not existing_df.empty:
                existing_df['Date'] = pd.to_datetime(existing_df['Date'])
                data['Date'] = pd.to_datetime(data['Date'])
                merged = pd.concat([existing_df, data], ignore_index=True)
                merged = merged.drop_duplicates(subset='Date', keep='last')
                merged = merged.sort_values('Date').reset_index(drop=True)
            else:
                merged = data
            
            final_rows = save_csv(merged, csv_path)
            latest = pd.to_datetime(merged['Date']).max().strftime('%Y-%m-%d')
            
            # 判断来源
            actual_source = 'tencent'
            if data is not None and existing_df is None:
                actual_source = 'tencent'
            
            progress['etfs'][key] = {
                'last_date': latest,
                'rows': final_rows,
                'status': 'ok',
                'source': actual_source,
                'updated': datetime.now().isoformat()
            }
            run_record['success'] += 1
            run_record['details'].append({
                'symbol': code, 'name': name,
                'status': 'ok', 'rows': final_rows,
                'latest': latest, 'source': actual_source
            })
            logger.info(f"  ✅ 成功: 总计 {final_rows} 行, 最新 {latest}")
        else:
            progress['etfs'][key] = {
                'last_date': last_date,
                'rows': existing_rows,
                'status': 'failed',
                'source': source,
                'updated': datetime.now().isoformat()
            }
            run_record['failed'] += 1
            run_record['details'].append({
                'symbol': code, 'name': name,
                'status': 'failed', 'rows': existing_rows,
                'reason': '腾讯+westock+yfinance均失败'
            })
            logger.info(f"  ❌ 三源均失败，留待下次尝试")
        
        save_progress(progress)
        time.sleep(REQUEST_DELAY)
    
    run_record['end'] = datetime.now().isoformat()
    progress['runs'].append(run_record)
    if len(progress['runs']) > 20:
        progress['runs'] = progress['runs'][-20:]
    save_progress(progress)
    
    logger.info("\n" + "=" * 60)
    logger.info(f"本轮: 成功{run_record['success']}, 失败{run_record['failed']}")
    
    pending_left = len(get_pending_etfs(progress))
    logger.info(f"剩余待处理: {pending_left} 只")
    logger.info("=" * 60)
    
    return run_record


def show_status():
    progress = load_progress()
    
    print(f"\n港股ETF数据状态（腾讯财经版）")
    print("=" * 95)
    print(f"{'代码':<8} {'名称':<28} {'行数':>6} {'最新日期':<12} {'状态':<8} {'来源':<10} {'优先级'}")
    print("-" * 95)
    
    for code, name, priority in HK_ETFS:
        key = f'hk{code}'
        info = progress.get('etfs', {}).get(key, {})
        rows = info.get('rows', 0)
        last_date = info.get('last_date', '-')
        status = info.get('status', '未获取')
        source = info.get('source', '-')
        
        csv_path = os.path.join(DATA_DIR, f'{key}.csv')
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                actual_rows = len(df)
                if actual_rows != rows:
                    rows = actual_rows
            except:
                pass
        
        print(f"{code:<8} {name:<28} {rows:>6} {last_date:<12} {status:<8} {source:<10} {priority}")
    
    total_ok = sum(1 for _, _, _ in HK_ETFS 
                   if progress.get('etfs', {}).get(f'hk{_}', {}).get('status') == 'ok')
    total_rows = sum(v.get('rows', 0) for v in progress.get('etfs', {}).values())
    pending = len(get_pending_etfs(progress))
    
    print("-" * 95)
    print(f"已获取: {total_ok}/{len(HK_ETFS)} 只, 总行数: {total_rows}, 待处理: {pending}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'status':
            show_status()
        elif cmd == 'run':
            run_fetch()
        elif cmd == 'fetch':
            if len(sys.argv) > 2:
                code = sys.argv[2].replace('.HK', '').replace('hk', '')
                for etf_code, name, _ in HK_ETFS:
                    if code == etf_code:
                        logger.info(f"手动获取: {name} ({code})")
                        data = fetch_tencent_kline(code)
                        if data is None:
                            data = fetch_westock(code)
                        if data is None:
                            data = fetch_yfinance(code)
                        
                        if data is not None:
                            key = f'hk{code}'
                            csv_path = os.path.join(DATA_DIR, f'{key}.csv')
                            final_rows = save_csv(data, csv_path)
                            latest = pd.to_datetime(data['Date']).max().strftime('%Y-%m-%d')
                            
                            progress = load_progress()
                            progress['etfs'][key] = {
                                'last_date': latest,
                                'rows': final_rows,
                                'status': 'ok',
                                'source': 'tencent',
                                'updated': datetime.now().isoformat()
                            }
                            save_progress(progress)
                            logger.info(f"✅ 保存 {final_rows} 行, 最新 {latest}")
                        else:
                            logger.info(f"❌ 获取失败")
                        break
            else:
                print("用法: python hk_etf_fetcher.py fetch <code>")
        else:
            print(f"用法: python {sys.argv[0]} [run|status|fetch <code>]")
    else:
        run_fetch()
