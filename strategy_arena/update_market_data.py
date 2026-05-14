#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场10年数据更新工具
======================
通过westock-data拉取美股ETF、港股蓝筹、A股ETF近10年日线数据，
保存为CSV到本地数据目录，供回测引擎使用。

支持限流重试：遇到限流自动等待重试，每批次间加入间隔。
"""

import os
import sys
import time
import json
import subprocess
import pandas as pd
from datetime import datetime

# ================================================================
# 配置
# ================================================================
WORKSPACE_DIR = '/data/workspace'
WESTOCK_SCRIPT = os.path.join(WORKSPACE_DIR, '.agent/skills/westock-data/scripts/index.js')

DATA_DIR = os.path.join(WORKSPACE_DIR, 'back_trader_stocks')
LOCAL_ETF_DIR = os.path.join(DATA_DIR, 'etf')
LOCAL_HK_DIR = os.path.join(DATA_DIR, 'hk')
LOCAL_CN_DIR = os.path.join(DATA_DIR, 'a')
LOCAL_US_DIR = os.path.join(DATA_DIR, 'us')

# 10年约2600个交易日
DATA_LIMIT = 2600

# 限流重试配置
RETRY_WAIT = 30          # 遇到限流等待秒数
MAX_RETRIES = 3          # 最大重试次数
BATCH_INTERVAL = 2       # 每个请求间隔秒数（避免触发限流）

# 状态文件（记录下载进度，支持断点续传）
STATUS_FILE = os.path.join(DATA_DIR, '.data_update_status.json')

# ================================================================
# 美股ETF代码映射
# ================================================================
US_ETF_SYMBOLS = {
    'SPY': 'usSPY',
    'VEA': 'usVEA',
    'AGG': 'usAGG',
    'SHY': 'usSHY',
    'GLD': 'usGLD',
    'TLT': 'usTLT',
    'QQQ': 'usQQQ',
    'IEF': 'usIEF',
    'VWO': 'usVWO',
    'SH': 'usSH',
}

# ================================================================
# 港股蓝筹代码映射（来自cross_regime_scheduler.py的HK_ETF_MAP + HK_BLUE_CHIPS）
# ================================================================
HK_SYMBOLS = {
    # ETF映射标的（核心7只）
    'hk00700': '腾讯控股',
    'hk09988': '阿里巴巴',
    'hk00005': '汇丰控股',
    'hk00011': '恒生银行',
    'hk00002': '中电控股',
    'hk01810': '小米集团',
    'hk00388': '中港石化',
}

# 额外补充港股蓝筹
HK_EXTRA = [
    'hk00001', 'hk00003', 'hk00006', 'hk00012', 'hk00016',
    'hk00017', 'hk00027', 'hk00066', 'hk00175', 'hk00241',
    'hk00267', 'hk00669', 'hk00688', 'hk00762', 'hk00823',
    'hk00883', 'hk00939', 'hk00941', 'hk00981', 'hk01024',
    'hk01288', 'hk01299', 'hk01816', 'hk02318', 'hk02382',
    'hk02628', 'hk03690', 'hk03988', 'hk06098', 'hk09618',
    'hk09633', 'hk09961', 'hk02015', 'hk02018',
]

# ================================================================
# A股ETF代码映射（来自cross_regime_scheduler.py的CN_ETF_MAP）
# ================================================================
CN_ETF_SYMBOLS = {
    'sh510300': '沪深300ETF',
    'sz159915': '创业板ETF',
    'sh510500': '中证500ETF',
    'sh511010': '国债ETF',
    'sh511880': '银华日利',
    'sh518880': '黄金ETF',
    'sh511260': '十年国债ETF',
}

# ================================================================
# 数据拉取函数
# ================================================================

def fetch_kline(westock_code: str, period: str = 'day', limit: int = DATA_LIMIT, fq: str = 'qfq') -> pd.DataFrame:
    """通过westock-data获取K线数据，支持限流重试"""
    for attempt in range(MAX_RETRIES):
        try:
            cmd = ['node', WESTOCK_SCRIPT, 'kline', westock_code, '--period', period, '--limit', str(limit), '--fq', fq]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=WORKSPACE_DIR)

            if result.returncode != 0:
                error_msg = result.stderr[:200] if result.stderr else 'unknown error'
                if '限流' in error_msg or 'rate' in error_msg.lower() or '429' in error_msg:
                    print(f"    ⏳ {westock_code} 限流，等待{RETRY_WAIT}秒后重试({attempt+1}/{MAX_RETRIES})...")
                    time.sleep(RETRY_WAIT)
                    continue
                print(f"    ❌ {westock_code} 获取失败: {error_msg}")
                return pd.DataFrame()

            lines = result.stdout.strip().split('\n')
            # 检查"数据为空"
            if len(lines) < 3 or '数据为空' in result.stdout:
                print(f"    ⚠️ {westock_code} 数据为空")
                return pd.DataFrame()

            data_lines = [l for l in lines if l.startswith('|') and not l.startswith('| ---') and not l.startswith('| date')]
            if len(data_lines) < 10:
                print(f"    ⚠️ {westock_code} 数据量不足: {len(data_lines)}行")
                return pd.DataFrame()

            records = []
            for line in data_lines:
                cols = [c.strip() for c in line.split('|')[1:-1]]
                if len(cols) >= 5:
                    try:
                        records.append({
                            'Date': cols[0],
                            'Open': float(cols[1]),
                            'High': float(cols[2]) if len(cols) > 3 else float(cols[1]),
                            'Low': float(cols[3]) if len(cols) > 3 else float(cols[1]),
                            'Close': float(cols[2]) if len(cols) > 3 else float(cols[1]),
                            'Volume': float(cols[5]) if len(cols) > 5 else 0,
                        })
                    except (ValueError, IndexError):
                        continue

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date').sort_index()
            return df

        except subprocess.TimeoutExpired:
            print(f"    ⏳ {westock_code} 超时，等待{RETRY_WAIT}秒后重试({attempt+1}/{MAX_RETRIES})...")
            time.sleep(RETRY_WAIT)
        except Exception as e:
            print(f"    ❌ {westock_code} 异常: {e}")
            break

    return pd.DataFrame()


def save_csv(df: pd.DataFrame, filepath: str) -> bool:
    """保存DataFrame为CSV"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        df.to_csv(filepath)
        return True
    except Exception as e:
        print(f"    ❌ 保存失败 {filepath}: {e}")
        return False


def load_status() -> dict:
    """加载下载状态"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_status(status: dict):
    """保存下载状态"""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2, ensure_ascii=False)


# ================================================================
# 主流程
# ================================================================

def update_us_etf(force: bool = False):
    """更新美股ETF数据"""
    print(f"\n{'='*60}")
    print(f"📊 [1/4] 更新美股ETF数据 ({len(US_ETF_SYMBOLS)}只)")
    print(f"{'='*60}")

    status = load_status()
    updated = 0
    skipped = 0
    failed = 0

    for name, ws_code in US_ETF_SYMBOLS.items():
        filepath = os.path.join(LOCAL_ETF_DIR, f'{name}.csv')

        # 检查是否需要更新
        if not force and os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                last_date = df.index[-1]
                days_old = (pd.Timestamp.now() - last_date).days
                if days_old <= 3:
                    print(f"  ⏭️ {name}: 数据最新({last_date.strftime('%Y-%m-%d')})，跳过")
                    skipped += 1
                    continue
            except Exception:
                pass

        print(f"  📥 {name} ({ws_code})...", end=' ', flush=True)
        df = fetch_kline(ws_code)
        if not df.empty:
            start = df.index[0].strftime('%Y-%m-%d')
            end = df.index[-1].strftime('%Y-%m-%d')
            if save_csv(df, filepath):
                print(f"✅ {len(df)}行 ({start} ~ {end})")
                updated += 1
                status[f'us_etf_{name}'] = {'updated': datetime.now().isoformat(), 'rows': len(df)}
            else:
                print(f"❌ 保存失败")
                failed += 1
        else:
            print(f"❌ 获取失败")
            failed += 1

        time.sleep(BATCH_INTERVAL)

    save_status(status)
    print(f"\n📈 美股ETF: 更新{updated}只, 跳过{skipped}只, 失败{failed}只")
    return updated, skipped, failed


def update_hk_stocks(force: bool = False):
    """更新港股蓝筹数据"""
    all_hk = dict(HK_SYMBOLS)
    for code in HK_EXTRA:
        if code not in all_hk:
            all_hk[code] = ''

    print(f"\n{'='*60}")
    print(f"📊 [2/4] 更新港股蓝筹数据 ({len(all_hk)}只)")
    print(f"{'='*60}")

    status = load_status()
    updated = 0
    skipped = 0
    failed = 0

    for hk_code, desc in all_hk.items():
        filepath = os.path.join(LOCAL_HK_DIR, f'{hk_code}.csv')
        label = f"{hk_code}" + (f"({desc})" if desc else "")

        # 检查是否需要更新
        if not force and os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                last_date = df.index[-1]
                days_old = (pd.Timestamp.now() - last_date).days
                if days_old <= 3:
                    print(f"  ⏭️ {label}: 数据最新({last_date.strftime('%Y-%m-%d')})，跳过")
                    skipped += 1
                    continue
            except Exception:
                pass

        print(f"  📥 {label}...", end=' ', flush=True)
        df = fetch_kline(hk_code)
        if not df.empty:
            start = df.index[0].strftime('%Y-%m-%d')
            end = df.index[-1].strftime('%Y-%m-%d')
            if save_csv(df, filepath):
                print(f"✅ {len(df)}行 ({start} ~ {end})")
                updated += 1
                status[f'hk_{hk_code}'] = {'updated': datetime.now().isoformat(), 'rows': len(df)}
            else:
                print(f"❌ 保存失败")
                failed += 1
        else:
            print(f"❌ 获取失败")
            failed += 1

        time.sleep(BATCH_INTERVAL)

    save_status(status)
    print(f"\n📈 港股: 更新{updated}只, 跳过{skipped}只, 失败{failed}只")
    return updated, skipped, failed


def update_cn_etf(force: bool = False):
    """更新A股ETF数据"""
    print(f"\n{'='*60}")
    print(f"📊 [3/4] 更新A股ETF数据 ({len(CN_ETF_SYMBOLS)}只)")
    print(f"{'='*60}")

    status = load_status()
    updated = 0
    skipped = 0
    failed = 0

    # A股ETF本地文件名映射（westock代码 → 本地文件名）
    cn_file_map = {
        'sh510300': '510300_XSHG',
        'sz159915': '159915_XSHE',
        'sh510500': '510500_XSHG',
        'sh511010': '511010_XSHG',
        'sh511880': '511880_XSHG',
        'sh518880': '518880_XSHG',
        'sh511260': '511260_XSHG',
    }

    for ws_code, desc in CN_ETF_SYMBOLS.items():
        local_name = cn_file_map.get(ws_code, ws_code)
        filepath = os.path.join(LOCAL_CN_DIR, f'{local_name}.csv')

        # 检查是否需要更新
        if not force and os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                last_date = df.index[-1]
                days_old = (pd.Timestamp.now() - last_date).days
                if days_old <= 3:
                    print(f"  ⏭️ {local_name}({desc}): 数据最新({last_date.strftime('%Y-%m-%d')})，跳过")
                    skipped += 1
                    continue
            except Exception:
                pass

        print(f"  📥 {local_name}({desc}) [{ws_code}]...", end=' ', flush=True)
        df = fetch_kline(ws_code)
        if not df.empty:
            start = df.index[0].strftime('%Y-%m-%d')
            end = df.index[-1].strftime('%Y-%m-%d')
            if save_csv(df, filepath):
                print(f"✅ {len(df)}行 ({start} ~ {end})")
                updated += 1
                status[f'cn_etf_{local_name}'] = {'updated': datetime.now().isoformat(), 'rows': len(df)}
            else:
                print(f"❌ 保存失败")
                failed += 1
        else:
            print(f"❌ 获取失败")
            failed += 1

        time.sleep(BATCH_INTERVAL)

    save_status(status)
    print(f"\n📈 A股ETF: 更新{updated}只, 跳过{skipped}只, 失败{failed}只")
    return updated, skipped, failed


def update_us_stocks(force: bool = False):
    """更新美股个股数据"""
    # 获取现有美股CSV列表
    if not os.path.exists(LOCAL_US_DIR):
        print(f"\n⚠️ 美股数据目录不存在: {LOCAL_US_DIR}")
        return 0, 0, 0

    csv_files = [f for f in os.listdir(LOCAL_US_DIR) if f.endswith('.csv') and not f.startswith('.')]
    if not csv_files:
        print(f"\n⚠️ 美股数据目录为空")
        return 0, 0, 0

    print(f"\n{'='*60}")
    print(f"📊 [4/4] 更新美股个股数据 ({len(csv_files)}只)")
    print(f"{'='*60}")

    status = load_status()
    updated = 0
    skipped = 0
    failed = 0

    for csv_file in sorted(csv_files):
        name = csv_file.replace('.csv', '')
        filepath = os.path.join(LOCAL_US_DIR, csv_file)
        ws_code = f'us{name}'

        # 检查是否需要更新
        if not force and os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                last_date = df.index[-1]
                days_old = (pd.Timestamp.now() - last_date).days
                if days_old <= 3:
                    skipped += 1
                    continue
            except Exception:
                pass

        print(f"  📥 {name}...", end=' ', flush=True)
        df = fetch_kline(ws_code)
        if not df.empty:
            start = df.index[0].strftime('%Y-%m-%d')
            end = df.index[-1].strftime('%Y-%m-%d')
            if save_csv(df, filepath):
                print(f"✅ {len(df)}行 ({start} ~ {end})")
                updated += 1
                status[f'us_{name}'] = {'updated': datetime.now().isoformat(), 'rows': len(df)}
            else:
                print(f"❌ 保存失败")
                failed += 1
        else:
            print(f"❌ 获取失败")
            failed += 1

        time.sleep(BATCH_INTERVAL)

    save_status(status)
    print(f"\n📈 美股: 更新{updated}只, 跳过{skipped}只, 失败{failed}只")
    return updated, skipped, failed


def update_cn_stocks(force: bool = False):
    """更新A股个股数据（将5年数据扩展为10年）"""
    if not os.path.exists(LOCAL_CN_DIR):
        print(f"\n⚠️ A股数据目录不存在: {LOCAL_CN_DIR}")
        return 0, 0, 0

    csv_files = [f for f in os.listdir(LOCAL_CN_DIR) if f.endswith('.csv') and not f.startswith('.')]
    if not csv_files:
        print(f"\n⚠️ A股数据目录为空")
        return 0, 0, 0

    print(f"\n{'='*60}")
    print(f"📊 [5/5] 更新A股个股数据 ({len(csv_files)}只)")
    print(f"{'='*60}")

    status = load_status()
    updated = 0
    skipped = 0
    failed = 0

    for csv_file in sorted(csv_files):
        name = csv_file.replace('.csv', '')
        filepath = os.path.join(LOCAL_CN_DIR, csv_file)

        # 解析A股代码，构建westock代码
        # 本地格式: 510300_XSHG, 159915_XSHE, 000001_XSHE, 600000_XSHG
        parts = name.split('_')
        if len(parts) == 2:
            code, exchange = parts
            if exchange == 'XSHG':
                ws_code = f'sh{code}'
            elif exchange == 'XSHE':
                ws_code = f'sz{code}'
            else:
                skipped += 1
                continue
        else:
            skipped += 1
            continue

        # 检查是否需要更新（只更新5年以内起始的数据，或3天以上未更新的）
        if not force and os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                if len(df) > 0:
                    first_date = df.index[0]
                    last_date = df.index[-1]
                    days_old = (pd.Timestamp.now() - last_date).days
                    # 数据起始在2017年之后说明不足10年，需要更新
                    if first_date.year < 2017 and days_old <= 3:
                        skipped += 1
                        continue
            except Exception:
                pass

        print(f"  📥 {name}({ws_code})...", end=' ', flush=True)
        df = fetch_kline(ws_code)
        if not df.empty:
            start = df.index[0].strftime('%Y-%m-%d')
            end = df.index[-1].strftime('%Y-%m-%d')
            if save_csv(df, filepath):
                print(f"✅ {len(df)}行 ({start} ~ {end})")
                updated += 1
                status[f'cn_{name}'] = {'updated': datetime.now().isoformat(), 'rows': len(df)}
            else:
                print(f"❌ 保存失败")
                failed += 1
        else:
            print(f"❌ 获取失败")
            failed += 1

        time.sleep(BATCH_INTERVAL)

    save_status(status)
    print(f"\n📈 A股: 更新{updated}只, 跳过{skipped}只, 失败{failed}只")
    return updated, skipped, failed


def main(force: bool = False, skip_us_stocks: bool = False, skip_cn_stocks: bool = False):
    """
    主入口：更新全市场数据

    Args:
        force: 强制更新所有数据（忽略3天内已更新的检查）
        skip_us_stocks: 跳过美股个股更新（数量多，耗时长）
        skip_cn_stocks: 跳过A股个股更新（数量多，耗时长）
    """
    start_time = time.time()
    print(f"🚀 全市场10年数据更新开始 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"   数据限制: {DATA_LIMIT}条 (≈10年日线)")

    total_updated = 0
    total_skipped = 0
    total_failed = 0

    # 1. 美股ETF（核心7只）
    u, s, f = update_us_etf(force)
    total_updated += u; total_skipped += s; total_failed += f

    # 2. 港股蓝筹
    u, s, f = update_hk_stocks(force)
    total_updated += u; total_skipped += s; total_failed += f

    # 3. A股ETF
    u, s, f = update_cn_etf(force)
    total_updated += u; total_skipped += s; total_failed += f

    # 4. 美股个股（数量多，可选择跳过）
    if not skip_us_stocks:
        u, s, f = update_us_stocks(force)
        total_updated += u; total_skipped += s; total_failed += f

    # 5. A股个股（数量多，可选择跳过）
    if not skip_cn_stocks:
        u, s, f = update_cn_stocks(force)
        total_updated += u; total_skipped += s; total_failed += f

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"🏁 更新完成! 耗时{elapsed:.1f}s")
    print(f"   ✅ 更新{total_updated}只 | ⏭️ 跳过{total_skipped}只 | ❌ 失败{total_failed}只")
    print(f"{'='*60}")

    # 如果有失败的，返回非零退出码
    return 1 if total_failed > 0 else 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='全市场10年数据更新工具')
    parser.add_argument('--force', action='store_true', help='强制更新所有数据')
    parser.add_argument('--skip-us-stocks', action='store_true', help='跳过美股个股更新')
    parser.add_argument('--skip-cn-stocks', action='store_true', help='跳过A股个股更新')
    parser.add_argument('--us-etf-only', action='store_true', help='只更新美股ETF')
    parser.add_argument('--hk-only', action='store_true', help='只更新港股')
    parser.add_argument('--cn-only', action='store_true', help='只更新A股ETF')
    parser.add_argument('--cn-stocks-only', action='store_true', help='只更新A股个股')
    args = parser.parse_args()

    if args.us_etf_only:
        sys.exit(update_us_etf(force=args.force)[2] > 0)
    elif args.hk_only:
        sys.exit(update_hk_stocks(force=args.force)[2] > 0)
    elif args.cn_only:
        sys.exit(update_cn_etf(force=args.force)[2] > 0)
    elif args.cn_stocks_only:
        sys.exit(update_cn_stocks(force=args.force)[2] > 0)
    else:
        sys.exit(main(force=args.force, skip_us_stocks=args.skip_us_stocks, skip_cn_stocks=args.skip_cn_stocks))
