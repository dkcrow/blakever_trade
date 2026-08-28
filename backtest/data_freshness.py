#!/usr/bin/env python3
"""数据新鲜度校验 + 多源同步 (港股/美股共用)
克总2026-06-24要求: 报告前同步数据到最新; 所有源失败仍滞后则在报告/邮件明确告警, 严禁静默用旧数据。
"""
import warnings
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')


def today_trading():
    """今天(周末回退到周五)"""
    t = datetime.now()
    if t.weekday() == 5:
        t -= timedelta(days=1)
    elif t.weekday() == 6:
        t -= timedelta(days=2)
    return t


def check_freshness(codes, data_dir, fname_fmt, max_gap=3):
    """检查每只成分股CSV的滞后(工作日数). fname_fmt 如 'hk{code}.csv' / '{code}.csv'
    返回 (is_stale, max_gap_days, stale_detail[(code,last_date,gap)...], checked_count)
    """
    today = today_trading().date()
    max_gap_days = 0
    details = []
    checked = 0
    for code in codes:
        fp = Path(data_dir) / fname_fmt.format(code=code)
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp, nrows=None, usecols=None)
            dcol = next((c for c in df.columns if c.lower().strip() == 'date'), df.columns[0])
            last = pd.to_datetime(df[dcol]).max().date()
            gap = int(np.busday_count(last, today))
            checked += 1
            if gap > max_gap_days:
                max_gap_days = gap
            if gap > max_gap:
                details.append((code, last.strftime('%Y-%m-%d'), gap))
        except Exception:
            continue
    is_stale = max_gap_days > max_gap
    return is_stale, max_gap_days, details, checked


def _merge_save(fp, new_df):
    """合并新数据到CSV(去重排序)"""
    if fp.exists():
        old = pd.read_csv(fp)
        old.columns = [c.lower().strip() for c in old.columns]
        old['date'] = pd.to_datetime(old['date'])
        new_df['date'] = pd.to_datetime(new_df['date'])
        merged = pd.concat([old, new_df]).drop_duplicates('date', keep='last').sort_values('date')
    else:
        merged = new_df.sort_values('date')
    merged.to_csv(fp, index=False)


def _sync_hk_westock_sub(codes, data_dir):
    """用WeStock kline更新港股CSV (单只循环, 解析markdown table). 返回更新数量"""
    import subprocess, re
    westock_js = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'experts' /
                     'plugins' / 'stock-partner-team' / 'skills' / 'westock-data' / 'scripts' / 'index.js')
    if not Path(westock_js).exists():
        return 0
    end = today_trading().strftime('%Y-%m-%d')
    updated = 0
    for code in codes:
        fp = Path(data_dir) / f'hk{code}.csv'
        start = '2023-01-01'
        try:
            if fp.exists():
                df0 = pd.read_csv(fp)
                dcol = next((c for c in df0.columns if c.lower().strip() == 'date'), None)
                if dcol:
                    last = pd.to_datetime(df0[dcol]).max()
                    start = (last + timedelta(days=1)).strftime('%Y-%m-%d')
        except Exception:
            pass
        if start > end:
            continue
        try:
            result = subprocess.run(
                ['node', westock_js, 'kline', f'hk{code}', 'daily', start, end],
                capture_output=True, text=True, timeout=30,
                cwd=str(Path(westock_js).parent))
            if result.returncode != 0:
                continue
            rows = []
            in_table = False
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line.startswith('|'):
                    if in_table: break
                    if 'date' in line and 'open' in line: in_table = True
                    continue
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) < 3: continue
                try:
                    dt = pd.Timestamp(parts[0])
                    opn = float(parts[1]); close = float(parts[2])
                    high = float(parts[3]) if len(parts)>3 else close
                    low = float(parts[4]) if len(parts)>4 else close
                    rows.append((dt, opn, close, high, low))
                except (ValueError, KeyError):
                    continue
            if not rows:
                continue
            new2 = pd.DataFrame(rows, columns=['date','open','close','high','low'])
            new2['volume'] = 0
            _merge_save(fp, new2)
            updated += 1
        except Exception:
            continue
    return updated


def sync_hk_data(codes, data_dir):
    """更新港股CSV: WeStock优先 → akshare兜底. 返回 (updated_count, source)"""
    # L1: WeStock kline
    wc = _sync_hk_westock_sub(codes, data_dir)
    if wc > 0:
        return wc, 'westock'
    # L2: akshare
    try:
        import akshare as ak
    except ImportError:
        return 0, 'failed'
    end = today_trading().strftime('%Y%m%d')
    updated = 0
    for code in codes:
        fp = Path(data_dir) / f'hk{code}.csv'
        start = '20230101'
        try:
            if fp.exists():
                df0 = pd.read_csv(fp)
                dcol = next((c for c in df0.columns if c.lower().strip() == 'date'), None)
                if dcol:
                    last = pd.to_datetime(df0[dcol]).max()
                    start = (last + timedelta(days=1)).strftime('%Y%m%d')
            if start > end:
                continue
            new = ak.stock_hk_hist(symbol=code, period='daily', start_date=start, end_date=end, adjust='')
            if new is None or len(new) == 0:
                continue
            new2 = pd.DataFrame({
                'date': pd.to_datetime(new['日期']),
                'open': new['开盘'], 'close': new['收盘'],
                'high': new['最高'], 'low': new['最低'], 'volume': new['成交量'],
            })
            _merge_save(fp, new2)
            updated += 1
        except Exception:
            continue
    return updated, ('akshare' if updated > 0 else 'failed')


def _sync_westock_generic(codes, data_dir, code_prefix, fname_fmt):
    """通用WeStock kline同步: code_prefix 'hk'/'us'/'' ; fname_fmt 文件路径模板"""
    import subprocess
    westock_js = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'experts' /
                     'plugins' / 'stock-partner-team' / 'skills' / 'westock-data' / 'scripts' / 'index.js')
    if not Path(westock_js).exists():
        return 0
    end = today_trading().strftime('%Y-%m-%d')
    updated = 0
    for code in codes:
        fp = Path(data_dir) / fname_fmt.format(code=code)
        start = '2023-01-01'
        try:
            if fp.exists():
                df0 = pd.read_csv(fp)
                dcol = next((c for c in df0.columns if c.lower().strip() == 'date'), None)
                if dcol:
                    last = pd.to_datetime(df0[dcol]).max()
                    start = (last + timedelta(days=1)).strftime('%Y-%m-%d')
        except Exception: pass
        if start > end: continue
        try:
            result = subprocess.run(
                ['node', westock_js, 'kline', f'{code_prefix}{code}', 'daily', start, end],
                capture_output=True, text=True, timeout=30,
                cwd=str(Path(westock_js).parent))
            if result.returncode != 0: continue
            rows = []; in_table = False
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line.startswith('|'):
                    if in_table: break
                    if 'date' in line and 'open' in line: in_table = True
                    continue
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) < 3: continue
                try:
                    dt = pd.Timestamp(parts[0]); opn = float(parts[1])
                    close = float(parts[2]); high = float(parts[3]) if len(parts)>3 else close
                    low = float(parts[4]) if len(parts)>4 else close
                    rows.append((dt, opn, close, high, low))
                except (ValueError, KeyError): continue
            if not rows: continue
            new2 = pd.DataFrame(rows, columns=['date','open','close','high','low'])
            new2['volume'] = 0
            _merge_save(fp, new2)
            updated += 1
        except Exception: continue
    return updated


def sync_us_data(symbols, data_dir):
    """更新美股CSV: WeStock优先 → akshare兜底. 返回 (updated_count, source)"""
    # L1: WeStock kline (us{sym})
    wc = _sync_westock_generic(symbols, data_dir, 'us', '{code}.csv')
    if wc > 0:
        return wc, 'westock'
    # L2: akshare
    try:
        import akshare as ak
    except ImportError:
        return 0, 'failed'
    updated = 0
    for sym in symbols:
        fp = Path(data_dir) / f'{sym}.csv'
        try:
            new = ak.stock_us_hist(symbol=sym, period='daily', adjust='')
            if new is None or len(new) == 0: continue
            new2 = pd.DataFrame({
                'date': pd.to_datetime(new['日期']),
                'open': new['开盘'], 'close': new['收盘'],
                'high': new['最高'], 'low': new['最低'], 'volume': new['成交量'],
            })
            _merge_save(fp, new2)
            updated += 1
        except Exception: continue
    return updated, ('akshare' if updated > 0 else 'failed')


def sync_etf_data(codes_prefixed, data_dir):
    """更新A股ETF CSV: codes_prefixed=sh/sz格式(如sh513100), WeStock kline用原码, 文件名去前缀(513100.csv). 返回 (updated_count, source)"""
    import subprocess
    westock_js = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'experts' /
                     'plugins' / 'stock-partner-team' / 'skills' / 'westock-data' / 'scripts' / 'index.js')
    if not Path(westock_js).exists():
        return 0, 'no_westock'
    end = today_trading().strftime('%Y-%m-%d')
    updated = 0
    for pref in codes_prefixed:
        raw = pref.replace('sh','').replace('sz','')  # sh513100→513100
        fp = Path(data_dir) / f'{raw}.csv'
        start = '2023-01-01'
        try:
            if fp.exists():
                df0 = pd.read_csv(fp)
                dcol = next((c for c in df0.columns if c.lower().strip() == 'date'), None)
                if dcol:
                    last = pd.to_datetime(df0[dcol]).max()
                    start = (last + timedelta(days=1)).strftime('%Y-%m-%d')
        except Exception: pass
        if start > end: continue
        try:
            result = subprocess.run(
                ['node', westock_js, 'kline', pref, 'daily', start, end],
                capture_output=True, text=True, timeout=30,
                cwd=str(Path(westock_js).parent))
            if result.returncode != 0: continue
            rows = []; in_table = False
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line.startswith('|'):
                    if in_table: break
                    if 'date' in line and 'open' in line: in_table = True
                    continue
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) < 3: continue
                try:
                    dt = pd.Timestamp(parts[0]); opn = float(parts[1])
                    close = float(parts[2]); high = float(parts[3]) if len(parts)>3 else close
                    low = float(parts[4]) if len(parts)>4 else close
                    rows.append((dt, opn, close, high, low))
                except (ValueError, KeyError): continue
            if not rows: continue
            new2 = pd.DataFrame(rows, columns=['date','open','close','high','low'])
            new2['volume'] = 0
            _merge_save(fp, new2)
            updated += 1
        except Exception: continue
    return (updated, 'westock') if updated > 0 else (0, 'failed')


def build_stale_banner(is_stale, max_gap_days, details, market='港股'):
    """生成滞后告警横幅HTML. 不滞后返回空字符串。"""
    if not is_stale:
        return ""
    sample = '、'.join([f"{c}({d},滞后{g}日)" for c, d, g in details[:5]])
    more = f" 等{len(details)}只" if len(details) > 5 else ""
    return (f'<div style="background:#C62828;color:#fff;padding:12px 15px;border-radius:6px;'
            f'margin-bottom:12px;font-weight:bold;font-size:13px;line-height:1.6;">'
            f'⚠️ {market}历史数据滞后 {max_gap_days} 个交易日（已尝试所有同步渠道仍失败）<br>'
            f'滞后标的: {sample}{more}<br>'
            f'<b>当前动量排名基于过期数据，可能失真，请勿据此做交易决策！</b></div>')
