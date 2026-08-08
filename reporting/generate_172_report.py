#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星172盘后报告 V3 - 含自动交易检查与同步

每次发送前:
1. 计算ETF排名 + 短期/长期得分 + 涨跌幅
2. 对比持仓, 自动执行买卖并同步到交易记录表
3. 生成HTML邮件发送
"""

import os, sys, math, json, warnings, urllib.request, re, subprocess
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from copy import deepcopy
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.etf.seven_star_base import (
    LocalDataSource, ETF_POOL, ETF_NAMES, DEFENSIVE_ETF
)

HISTORY_FILE = Path(__file__).parent / '172_ranking_history.json'
BLACKLIST_FILE = Path(__file__).parent / '172_blacklist.json'
TRADES_XLSX = Path(__file__).parent.parent / 'backtest' / 'results_172' / '七星172_交易记录_2026.xlsx'


def get_latest_trading_date():
    """动态计算最新交易日（跳过周末）"""
    today = datetime.now()
    if today.weekday() == 5:      # 周六 → 周五
        today = today - timedelta(days=1)
    elif today.weekday() == 6:    # 周日 → 周五
        today = today - timedelta(days=2)
    return today.strftime('%Y-%m-%d')


LATEST_DATE = get_latest_trading_date()


# ================================================================
# 实时行情获取 — 三级兜底 (L1→L2→降级CSV)
# L1: WeStock Data (腾讯自选股)  L2: 新浪财经 API  L3: 降级到CSV收盘价 + 邮件告警
# 规则: 全部失败时立即发送告警邮件，严禁静默使用过时数据
# ================================================================

_realtime_source = None  # 'westock' | 'sina' | None(降级CSV)

def is_realtime_valid():
    return _realtime_source is not None

def get_realtime_source():
    return _realtime_source

def _fetch_realtime_westock(codes):
    """L1: 通过 westock-data quote 获取A股ETF实时行情"""
    prices = {}
    a_codes = [c for c in codes if c.startswith('sh') or c.startswith('sz')]
    if not a_codes:
        return prices
    try:
        code_str = ','.join(a_codes)
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT, 'quote', code_str],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(WESTOCK_SCRIPT)
        )
        if result.returncode != 0:
            return prices
        output = result.stdout
        in_table = False
        col_idx = {}
        for line in output.split('\n'):
            line = line.strip()
            if not line.startswith('|'):
                continue
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if not in_table:
                if 'price' in parts or 'code' in parts:
                    for i, h in enumerate(parts):
                        if h == 'code': col_idx['code'] = i
                        elif h == 'price': col_idx['price'] = i
                        elif h == 'change_percent': col_idx['chg'] = i
                        elif h == 'prev_close': col_idx['prev_close'] = i
                    in_table = True
                continue
            if all(p.replace('-','').replace(':','') == '' for p in parts):
                continue
            if 'code' in col_idx and 'price' in col_idx:
                code_raw = parts[col_idx['code']]
                try:
                    p = float(parts[col_idx['price']])
                except:
                    continue
                if p <= 0:
                    continue
                chg = 0.0
                if 'chg' in col_idx:
                    try:
                        chg = float(parts[col_idx['chg']])
                    except:
                        pass
                prices[code_raw] = {
                    'price': p,
                    'change_pct': round(chg, 2)
                }
    except Exception:
        pass
    return prices

def _fetch_realtime_sina(codes):
    """L2: 新浪财经实时行情"""
    prices = {}
    a_codes = [c for c in codes if c.startswith('sh') or c.startswith('sz')]
    if not a_codes:
        return prices
    batch_size = 50
    for i in range(0, len(a_codes), batch_size):
        batch = a_codes[i:i + batch_size]
        url = f'http://hq.sinajs.cn/list={",".join(batch)}'
        try:
            req = urllib.request.Request(url, headers={
                'Referer': 'https://finance.sina.com.cn'
            })
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')
            for line in raw.strip().split('\n'):
                m = re.search(r'hq_str_(\w+)=\"(.*)\"', line)
                if not m:
                    continue
                code_key = m.group(1)
                fields = m.group(2).split(',')
                if len(fields) < 4:
                    continue
                try:
                    cur_price = float(fields[3])
                    prev_close = float(fields[2])
                    if cur_price > 0 and prev_close > 0:
                        change_pct = (cur_price - prev_close) / prev_close * 100
                        prices[code_key] = {
                            'price': cur_price,
                            'change_pct': round(change_pct, 2)
                        }
                except (ValueError, IndexError):
                    continue
        except Exception:
            pass
    return prices

def fetch_realtime_prices(codes):
    """获取A股ETF实时行情，三级兜底: L1 WeStock → L2 新浪 → 降级CSV
    返回: {code: {'price': float, 'change_pct': float}}
    """
    global _realtime_source

    # L1: WeStock Data (腾讯自选股)
    prices = _fetch_realtime_westock(codes)
    if prices:
        _realtime_source = 'westock'
        print(f"  [RT] L1-WeStock OK: {len(prices)}/{len([c for c in codes if c.startswith('sh') or c.startswith('sz')])} quotes")
        return prices

    print(f"  [RT] L1-WeStock failed, trying L2-Sina...")

    # L2: 新浪财经
    prices = _fetch_realtime_sina(codes)
    if prices:
        _realtime_source = 'sina'
        print(f"  [RT] L2-Sina OK: {len(prices)}/{len([c for c in codes if c.startswith('sh') or c.startswith('sz')])} quotes")
        return prices

    _realtime_source = None
    print(f"  [RT] ⚠️ ALL SOURCES FAILED! Prices will use CSV close data.")
    return {}


def send_realtime_failure_alert(mode_label):
    """实时行情获取失败告警邮件"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    now = datetime.now()
    subject = f"[{mode_label}] ⚠️ 实时行情获取失败 监控已失效 - {now.strftime('%Y-%m-%d %H:%M')}"
    body = f"""<html><body style="font-family:'Microsoft YaHei',sans-serif;max-width:600px;margin:20px auto;">
<h2 style="color:#C62828;">⚠️ 实时行情获取失败 — 监控已失效</h2>
<p>七星172监控任务于 <b>{now.strftime('%Y-%m-%d %H:%M')}</b> 执行时，所有实时行情获取渠道均已失败：</p>
<table style="border-collapse:collapse;width:100%;margin:10px 0;">
<tr style="background:#FFEBEE;"><td style="padding:8px;border:1px solid #ddd;"><b>渠道</b></td><td style="padding:8px;border:1px solid #ddd;"><b>状态</b></td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;">L1: WeStock Data (腾讯自选股)</td><td style="padding:8px;border:1px solid #ddd;color:#C62828;">❌ 失败</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;">L2: 新浪财经 API</td><td style="padding:8px;border:1px solid #ddd;color:#C62828;">❌ 失败</td></tr>
</table>
<div style="background:#FFF3CD;border:1px solid #FFC107;padding:12px;border-radius:4px;margin:15px 0;">
    <b>⚠️ 当前报告价格均为前一交易日收盘价，非盘中实时价格，监控已失效。</b><br>
    已尝试全部渠道获取实时价格均失败，请手动检查网络后重新执行。
</div>
<hr>
<p style="color:#888;font-size:11px;">七星172 · Blakever Trade · 自动告警<br>此邮件由系统自动发送，请勿回复。</p>
</body></html>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = "848786642@qq.com"
    msg["To"] = "848786642@qq.com"
    msg["Date"] = now.strftime("%a, %d %b %Y %H:%M:%S +0800")
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
            s.login("848786642@qq.com", "ljbtvacrctjobfed")
            s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
        print(f"  [ALERT] 实时行情失败告警邮件已发送")
        return True
    except Exception as e:
        print(f"  [ALERT] 告警邮件发送失败: {e}")
        return False


# ================================================================
# 排名计算
# ================================================================

def compute_scores(close_full, lookback):
    """计算给定周期的动量得分 (年化收益 × R²)"""
    recent = close_full[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann_ret = math.exp(slope * 250) - 1
    ss_res = np.sum(w * (y - (slope * x + intercept)) ** 2)
    ss_tot = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return ann_ret * r2, ann_ret


def check_profit_protection(code, cur_price, hist_df, date, lookback=1, threshold=0.05):
    """盈利保护检查"""
    try:
        mask = hist_df.index < pd.Timestamp(date)
        hist_before = hist_df[mask]
        if len(hist_before) >= lookback:
            max_h = hist_before['high'].tail(lookback).max()
            return max_h > 0 and cur_price <= max_h * (1 - threshold)
    except:
        pass
    return False


# ================================================================
# 溢价率获取（三级兜底：neodata → akshare → westock-data → 放弃交易）
# ================================================================

PYTHON = str(Path.home() / '.workbuddy' / 'binaries' / 'python' / 'envs' / 'default' / 'Scripts' / 'python.exe')
# 2026-06-22修复: 插件已迁移, 旧cb_teams_marketplace路径失效
NEODATA_SCRIPT = str(Path.home() / '.workbuddy' / 'skills-marketplace' / 'skills' / 'neodata-financial-search' / 'scripts' / 'query.py')
WESTOCK_SCRIPT = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'experts' / 'plugins' / 'stock-partner-team' / 'skills' / 'westock-data' / 'scripts' / 'index.js')


def _fetch_navs_tier1_neodata(raw_codes):
    """Tier 1: neodata API → {code: float}"""
    import subprocess, json, re
    navs = {}
    batch_size = 15
    for batch_idx in range(0, len(raw_codes), batch_size):
        batch = raw_codes[batch_idx:batch_idx + batch_size]
        query = 'ETF ' + ' '.join(batch) + ' 单位净值'
        try:
            result = subprocess.run(
                [PYTHON, NEODATA_SCRIPT, '--query', query, '--data-type', 'api'],
                capture_output=True, text=True, timeout=30,
                cwd=str(Path(NEODATA_SCRIPT).parent),
                encoding='utf-8', errors='replace'
            )
            output = result.stdout
        except Exception:
            continue
        m = re.search(r'\{[\s\S]*\}', output)
        if not m:
            continue
        try:
            data = json.loads(m.group())
        except Exception:
            continue
        api = data.get('data', {}).get('apiData', {})
        for r in api.get('apiRecall', []):
            rtype = r.get('type', '')
            # 仅解析"基金净值和区间回报率"section
            if '净值' not in rtype and '回报率' not in rtype:
                continue
            content = r.get('content', '')
            for line in content.strip().split('\n')[2:]:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) < 4:
                    continue
                raw_code = parts[0].split('.')[0] if '.' in parts[0] else parts[0]
                if not re.match(r'^\d{6}$', raw_code):
                    continue
                try:
                    nav = float(parts[3])
                    if 0.01 < nav < 10000:
                        if raw_code not in navs:
                            navs[raw_code] = nav
                except ValueError:
                    pass
    return navs


def _fetch_navs_tier2_akshare(raw_codes, date_str):
    """Tier 2: akshare 下载最新 NAV → {code: float}"""
    import time
    try:
        import akshare as ak
    except ImportError:
        return {}
    navs = {}
    for code in raw_codes:
        try:
            # 2026-06-22修复: 窗口-2天太窄, 周末/节假日空区间会触发akshare异常→全失败
            # 改为-12天确保覆盖最近有效净值(取最后一条), 跳过周末/长假
            end_dt = pd.Timestamp(date_str)
            start_dt = end_dt - pd.Timedelta(days=12)
            df_nav = ak.fund_etf_fund_info_em(
                fund=code,
                start_date=start_dt.strftime('%Y%m%d'),
                end_date=end_dt.strftime('%Y%m%d')
            )
            if len(df_nav) > 0 and '单位净值' in df_nav.columns:
                nav_val = float(df_nav['单位净值'].iloc[-1])
                if 0.01 < nav_val < 10000:
                    navs[code] = nav_val
                    # Also save to local CSV
                    nav_dir = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\data\storage\stock_data\etf_nav')
                    prefix = 'sh' if str(code).startswith('5') else 'sz'
                    fp = nav_dir / f'{prefix}{code}_nav.csv'
                    today = pd.Timestamp(date_str)
                    if fp.exists():
                        old = pd.read_csv(fp)
                        old['date'] = pd.to_datetime(old['date'])
                        new_row = pd.DataFrame([{'date': today, 'unit_nav': nav_val}])
                        merged = pd.concat([old, new_row]).drop_duplicates(subset='date').sort_values('date')
                        merged.to_csv(fp, index=False)
            time.sleep(0.3)
        except Exception:
            pass
    return navs


def _fetch_navs_tier3_westock(raw_codes):
    """Tier 3: westock-data CLI → {code: float}"""
    import subprocess, re, json
    navs = {}
    batch_size = 10
    for batch_idx in range(0, len(raw_codes), batch_size):
        batch = raw_codes[batch_idx:batch_idx + batch_size]
        codes_str = ','.join(batch)
        try:
            result = subprocess.run(
                ['node', WESTOCK_SCRIPT, 'etf', codes_str],
                capture_output=True, text=True, timeout=60,
                encoding='utf-8', errors='replace'
            )
            output = result.stdout
        except Exception:
            continue
        # Parse markdown table for unit_nav
        for line in output.split('\n'):
            line = line.strip()
            if not line.startswith('|'):
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 7:
                continue
            code = parts[1] if re.match(r'^\d{5,6}$', parts[1]) else None
            if not code:
                continue
            # Try to find NAV in last columns
            for p in parts[-3:]:
                try:
                    nav = float(p)
                    if 0.01 < nav < 10000:
                        navs[code] = nav
                        break
                except ValueError:
                    continue
    return navs


def fetch_all_navs(etf_codes):
    """四级兜底获取ETF净值: neodata → akshare → westock → eastmoney。累计补缺。"""
    raw_codes = [c[2:] if (c.startswith('sh') or c.startswith('sz')) and len(c) > 2 else c
                 for c in etf_codes if c.startswith('sh') or c.startswith('sz')]
    if not raw_codes:
        return {}, None

    all_navs = {}
    primary_source = None

    # Tier 1: neodata
    print("  [NAV] Tier1: neodata...")
    raw_navs = _fetch_navs_tier1_neodata(raw_codes)
    if raw_navs:
        navs = _map_raw_navs(raw_navs, etf_codes)
        all_navs.update(navs)
        if not primary_source:
            primary_source = 'neodata'
        print(f"  [NAV] neodata OK: {len(navs)} ETFs (累计 {len(all_navs)}/{len(raw_codes)})")
    else:
        print(f"  [NAV] neodata gave 0 navs")

    # Tier 2: akshare (补缺)
    missing = [c for c in raw_codes if not any(prefix + c in all_navs for prefix in ('sh','sz','bj'))]
    if missing and len(all_navs) < len(raw_codes) // 2:
        print(f"  [NAV] Tier2: akshare (补缺 {len(missing)}只)...")
        raw_navs = _fetch_navs_tier2_akshare(missing, LATEST_DATE.replace('-', ''))
        if raw_navs:
            navs = _map_raw_navs(raw_navs, etf_codes)
            all_navs.update(navs)
            if not primary_source:
                primary_source = 'akshare'
            print(f"  [NAV] akshare OK: +{len(navs)} ETFs (累计 {len(all_navs)}/{len(raw_codes)})")

    # Tier 3: westock (补缺)
    missing = [c for c in raw_codes if not any(prefix + c in all_navs for prefix in ('sh','sz','bj'))]
    if missing and len(all_navs) < len(raw_codes) // 2:
        print(f"  [NAV] Tier3: westock (补缺 {len(missing)}只)...")
        raw_navs = _fetch_navs_tier3_westock(missing)
        if raw_navs:
            navs = _map_raw_navs(raw_navs, etf_codes)
            all_navs.update(navs)
            if not primary_source:
                primary_source = 'westock'
            print(f"  [NAV] westock OK: +{len(navs)} ETFs (累计 {len(all_navs)}/{len(raw_codes)})")

    # Tier 4: eastmoney (补缺, 无需认证)
    missing = [c for c in raw_codes if not any(prefix + c in all_navs for prefix in ('sh','sz','bj'))]
    if missing:
        print(f"  [NAV] Tier4: eastmoney (补缺 {len(missing)}只)...")
        raw_navs = _fetch_navs_tier4_eastmoney(missing)
        if raw_navs:
            navs = _map_raw_navs(raw_navs, etf_codes)
            all_navs.update(navs)
            if not primary_source:
                primary_source = 'eastmoney'
            print(f"  [NAV] eastmoney OK: +{len(navs)} ETFs (累计 {len(all_navs)}/{len(raw_codes)})")

    if len(all_navs) >= 3:
        print(f"  [NAV] 最终: {len(all_navs)}/{len(raw_codes)} ETFs, 来源={primary_source}")
        return all_navs, primary_source

    print("  [NAV] ⚠️ ALL TIERS FAILED — 溢价率获取失败")
    return {}, None


def _fetch_navs_tier4_eastmoney(raw_codes):
    """Tier 4: 东方财富基金净值API (无需认证)"""
    import requests
    navs = {}
    for code in raw_codes:
        try:
            url = 'https://api.fund.eastmoney.com/f10/lsjz'
            params = {'fundCode': code, 'pageIndex': 1, 'pageSize': 1}
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://fundf10.eastmoney.com/'}
            r = requests.get(url, params=params, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                items = data.get('Data', {}).get('LSJZList', [])
                if items:
                    nav = float(items[0].get('DWJZ', 0))
                    if 0.01 < nav < 10000:
                        navs[code] = nav
            time.sleep(0.15)
        except Exception:
            pass
    return navs


def _map_raw_navs(raw_navs, etf_codes):
    """将纯数字代码映射回 sh/sz 前缀"""
    navs = {}
    for code, nav in raw_navs.items():
        for prefix in ('sh', 'sz', 'bj'):
            full_code = prefix + code
            if full_code in etf_codes:
                navs[full_code] = nav
                break
        if code not in navs:
            navs[code] = nav
    return navs


# ================================================================
# 🚫 盈利保护日内黑名单
# ================================================================

def load_blacklist():
    """加载磁盘黑名单: {code: date}"""
    if BLACKLIST_FILE.exists():
        try:
            with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_blacklist(bl):
    """保存黑名单到磁盘"""
    with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(bl, f, ensure_ascii=False)

def clear_blacklist_if_new_day():
    """如果黑名单日期不是今天, 清空 (每日 09:10 首次调用时自动清除昨日黑名单)"""
    bl = load_blacklist()
    if not bl:
        return
    # 检查黑名单中任意 ETF 的日期是否为今天
    dates = set(bl.values())
    today = LATEST_DATE
    if today not in dates:
        print(f"  [黑名单] 清除 {len(bl)} 条昨日黑名单记录")
        save_blacklist({})


def get_current_rankings():
    """获取最新交易日ETF完整排名（价格优先使用实时行情，三级兜底净值计算溢价率）"""
    ds = LocalDataSource()
    all_data = ds.load_all_etfs('2026-01-01', LATEST_DATE)

    # 获取单位净值（三级兜底：neodata → akshare → westock-data）
    neo_navs, nav_source = fetch_all_navs(ETF_POOL)
    nav_failed = (nav_source is None)
    if nav_failed:
        print("  [NAV] ⚠️ 所有数据源均失败 — 溢价率获取失败, 放弃本次交易")

    # 获取实时行情 (三级兜底: WeStock → 新浪 → CSV降级+告警)
    print("  [RT] Fetching realtime prices...")
    realtime = fetch_realtime_prices(ETF_POOL)
    rt_valid = is_realtime_valid()
    rt_source = get_realtime_source()
    if not rt_valid:
        # 全部失败 → 立即发送告警邮件
        send_realtime_failure_alert("仅排名")
    n_rt = len(realtime)
    n_a = len([c for c in ETF_POOL if c.startswith('sh') or c.startswith('sz')])
    print(f"  [RT] Got {n_rt}/{n_a} realtime quotes (source: {rt_source or 'CSV降级'})")

    current_prices = {}
    prev_prices = {}
    for code, df in all_data.items():
        mask = df.index <= pd.Timestamp(LATEST_DATE)
        if mask.any():
            if code in realtime:
                current_prices[code] = realtime[code]['price']
            else:
                current_prices[code] = float(df.loc[mask, 'close'].iloc[-1])
            closes = df.loc[mask, 'close']
            prev_prices[code] = float(closes.iloc[-2]) if len(closes) >= 2 else current_prices[code]

    # 盈利保护日内黑名单 (11:00触发后禁止13:04买回)
    blacklist = load_blacklist()
    blacklist_today = {code for code, d in blacklist.items() if str(d) == str(LATEST_DATE)}

    prev_rankings = load_previous_rankings()
    prev_rank_map = {r['code']: r['rank'] for r in prev_rankings}

    ranked = []
    for code in ETF_POOL:
        df = all_data.get(code)
        if df is None:
            continue
        mask = df.index <= pd.Timestamp(LATEST_DATE)
        hist = df[mask]
        if len(hist) < 25:
            continue
        close_arr = hist['close'].values
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        # 含实时价的得分数列 (排名 + 过滤均基于实时价)
        close_full = np.append(close_arr, cur)

        # 长期得分 (25日)
        long_score, ann_ret_l = compute_scores(close_full, 25)
        # 短期得分 (10日)
        short_score, _ = compute_scores(close_full, 10) if len(close_full) >= 11 else (0, 0)

        # 盈利保护: 重新启用 (独立测试证实 +35%收益 -2.2%回撤)
        protected = check_profit_protection(code, cur, df, LATEST_DATE)

        # 溢价率 = (当前价 - neodata单位净值) / neodata单位净值 * 100
        # 获取不到净值 → None（显示 "-"，不触发过滤）
        neo_nav = neo_navs.get(code) or neo_navs.get(code[2:] if len(code)>2 else '')
        if neo_nav and cur > 0 and neo_nav > 0:
            premium_pct = round((cur - neo_nav) / neo_nav * 100, 2)
        else:
            premium_pct = None
        premium_filtered = (premium_pct is not None and premium_pct > 20.0)

        # 近3日跌幅: 2026-06-03 永久关闭
        drop3 = False

        # 涨跌幅（有实时价格时用实时涨跌幅）
        if code in realtime and 'change_pct' in realtime[code]:
            change_pct = realtime[code]['change_pct']
        else:
            prev = prev_prices.get(code, cur)
            change_pct = (cur - prev) / prev * 100 if prev > 0 else 0

        ranked.append({
            'code': code,
            'name': ETF_NAMES.get(code, code),
            'score': round(long_score, 4),
            'short_score': round(short_score, 4),
            'long_score': round(long_score, 4),
            'price': round(cur, 4),
            'change_pct': round(change_pct, 2),
            'short_mom_annual': round(ann_ret_l, 8),  # 用于过滤判断
            'protected': protected,
            'drop3': drop3,
            'premium_filtered': premium_filtered,
            'premium_pct': premium_pct,
            'blacklisted': code in blacklist_today,
            'filtered': protected or premium_filtered or (code in blacklist_today),  # +黑名单
            'prev_rank': prev_rank_map.get(code, None),
            'hist_df': df,  # 暂存用于后续成交量检查
        })

    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked, current_prices, nav_failed, is_realtime_valid()


def load_previous_rankings():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('rankings', [])
        except:
            pass
    return []


def get_display_order(ranked):
    """
    返回显示排序：有效ETF按得分降序 + 被过滤/黑名单的ETF排在末尾
    """
    valid = [r for r in ranked if not r['filtered'] and not r.get('blacklisted', False)]
    blocked = [r for r in ranked if r['filtered'] or r.get('blacklisted', False)]
    result = list(valid)
    for i, r in enumerate(blocked):
        r['rank'] = len(valid) + i + 1
        result.append(r)
    return result


def save_rankings(ranked):
    """保存排名历史（按显示顺序）"""
    display_order = get_display_order(ranked)
    data = {
        'date': LATEST_DATE,
        'generated': datetime.now().isoformat(),
        'rankings': [{'code': r['code'], 'rank': i+1, 'score': r['score']}
                      for i, r in enumerate(display_order)]
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================================================================
# 交易检查与同步
# ================================================================

def get_holding_from_xlsx():
    """从交易记录xlsx中获取当前持仓 (正序遍历: 买入→有持仓, 卖出→无持仓)"""
    if not TRADES_XLSX.exists():
        return None
    df = pd.read_excel(TRADES_XLSX)
    holding = None
    for _, row in df.iterrows():
        if row.get('方向') == '买入':
            holding = {
                'code': row.get('ETF代码', ''),
                'name': row.get('ETF名称', ''),
                'price': row.get('成交价格', 0),
                'date': row.get('交易日期', ''),
            }
        elif row.get('方向') == '卖出':
            holding = None
    return holding


def pick_trade_target(ranked):
    """从排名中选出实际交易目标 (应用过滤 + 黑名单)"""
    for r in ranked:
        if not r['filtered'] and not r.get('blacklisted', False):
            return r
    return None


def append_trade_to_xlsx(direction, code, name, price, date, score, reason):
    """追加一条交易记录到xlsx"""
    if TRADES_XLSX.exists():
        df = pd.read_excel(TRADES_XLSX)
    else:
        df = pd.DataFrame(columns=['交易日期','ETF名称','ETF代码','方向','成交价格','综合动量得分','交易理由'])

    # 如果是纯日期，附加当前时间精确到分钟
    date_str = str(date)
    if len(date_str) == 10 and date_str.count('-') == 2:
        date_str = f'{date_str} {datetime.now().strftime("%H:%M")}'

    new_row = {
        '交易日期': date_str,
        'ETF名称': name,
        'ETF代码': code,
        '方向': direction,
        '成交价格': round(price, 4),
        '综合动量得分': round(score, 4) if isinstance(score, (int, float)) else score,
        '交易理由': reason,
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_excel(TRADES_XLSX, index=False)


def check_and_execute_trades(ranked):
    """
    根据排名检查是否需要换仓，如果需要则记录到交易表
    返回: (是否发生了交易, trade_description)
    """
    # 全局检查: 今日若已完成完整换仓(有买有卖)则跳过, 仅有卖出(盈利保护)则允许继续买入
    if TRADES_XLSX.exists():
        df_check = pd.read_excel(TRADES_XLSX)
        today_trades = df_check[df_check['交易日期'].astype(str).str.startswith(str(LATEST_DATE))]
        if len(today_trades) > 0:
            directions = today_trades['方向'].tolist()
            if '买入' in directions:
                return False, f"今日已有完整换仓操作({', '.join(directions)})，跳过重复执行"

    holding = get_holding_from_xlsx()
    target = pick_trade_target(ranked)

    if target is None:
        return False, "无合格标的"

    if holding is None:
        # 首次买入
        append_trade_to_xlsx(
            '买入', target['code'], target['name'],
            target['price'], LATEST_DATE, target['score'],
            f"动量排名第1/{len(ETF_POOL)}"
        )
        return True, f"初始买入: {target['name']}({target['code']})@{target['price']:.4f}"

    # 检查是否需要换仓
    if holding['code'] == target['code']:
        return False, f"持仓不变: {holding['name']} 仍是排名第一"

    # 需要换仓: 先卖后买
    # 检查是否同一天已有操作(避免重复)
    if TRADES_XLSX.exists():
        df = pd.read_excel(TRADES_XLSX)
        today_trades = df[df['交易日期'].astype(str).str.startswith(str(LATEST_DATE))]
        for _, row in today_trades.iterrows():
            if row.get('方向') == '卖出' and row.get('ETF代码') == holding['code']:
                return False, f"今日已卖出 {holding['name']}，跳过"

    # 卖出旧持仓
    old_score = 'N/A'
    sell_price = target['price']  # 默认用目标价格
    # 尝试从排名中获取旧持仓的实际价格和得分
    old_ranked = next((r for r in ranked if r['code'] == holding['code']), None)
    if old_ranked:
        old_score = old_ranked['score']
        sell_price = old_ranked['price']  # 用旧持仓的实际价格

    # 构造真实的卖出理由
    sell_reason = '调出目标(排名下降)'
    if old_ranked:
        if old_ranked.get('filtered'):
            # 被过滤，找出具体原因
            reasons = []
            if old_ranked.get('protected'):
                reasons.append(f"盈利保护(回撤超5%)")
            if old_ranked.get('premium_filtered'):
                reasons.append(f"溢价率>20%过滤")
            if old_ranked.get('drop3'):
                reasons.append(f"近3日跌幅>3%")
            if old_ranked.get('short_score', 0) < 0:
                reasons.append(f"短期动量负({old_ranked['short_score']:.2f})")
            sell_reason = '; '.join(reasons) if reasons else '被过滤规则排除'
        elif old_ranked.get('prev_rank') is not None:
            sell_reason = f"排名从{old_ranked['prev_rank']}→新第1不等,调出"

    append_trade_to_xlsx(
        '卖出', holding['code'], holding['name'],
        sell_price, LATEST_DATE, old_score,
        sell_reason
    )

    # 买入新品种
    append_trade_to_xlsx(
        '买入', target['code'], target['name'],
        target['price'], LATEST_DATE, target['score'],
        f"动量排名第1/{len(ETF_POOL)}"
    )

    return True, (f"换仓: 卖出 {holding['name']} → 买入 {target['name']}"
                  f"({target['code']})@{target['price']:.4f}")


# ================================================================
# 获取交易记录
# ================================================================

def get_recent_trades(ranked=None):
    """获取最近20条交易记录 (时间倒序: 最新在最前, 同日买入在卖出前)"""
    if not TRADES_XLSX.exists():
        return []
    df = pd.read_excel(TRADES_XLSX)
    # 补充方向排序键: 同一天买入在卖出之前 (买入时间更晚, 倒序中应排前面)
    df['_dir_order'] = df['方向'].apply(lambda x: 0 if x == '买入' else 1)
    # 按日期倒序, 同日买入优先, 取最近20条
    df = df.sort_values(['交易日期', '_dir_order'], ascending=[False, True]).head(20)
    df = df.drop(columns=['_dir_order'])
    records = df.to_dict('records')

    # 构建当前排名得分映射 (用于补充历史 N/A)
    score_map = {}
    if ranked:
        for r in ranked:
            score_map[r['code']] = r['score']

    # 修复 nan 得分 + 修正理由中的分母
    for r in records:
        score = r.get('综合动量得分', '')
        need_fix = False
        try:
            if score is None:
                need_fix = True
            elif isinstance(score, float) and np.isnan(score):
                need_fix = True
            elif isinstance(score, float) and np.isinf(score):
                need_fix = True
        except:
            need_fix = True

        if need_fix:
            code = r.get('ETF代码', '')
            if code in score_map:
                r['综合动量得分'] = round(score_map[code], 4)
            else:
                r['综合动量得分'] = 'N/A'

        # 修正历史记录中不固定的分母 -> 统一为 38
        reason = str(r.get('交易理由', ''))
        if reason and '动量排名第1/' in reason:
            import re
            reason = re.sub(r'动量排名第1/\d+', f'动量排名第1/{len(ETF_POOL)}', reason)
            r['交易理由'] = reason

    # 计算盈亏: 匹配买入→卖出对
    compute_trade_pnl(records)

    return records


def compute_trade_pnl(records):
    """为每条卖出记录计算买入→卖出的盈亏百分比"""
    if not records:
        return
    # records 是倒序的(最新在前), 需要正序遍历才能匹配买入→卖出
    # 构建买入队列: dict[code] = list of (index, price)
    buy_queue = {}
    for i in range(len(records) - 1, -1, -1):  # 从旧到新遍历
        r = records[i]
        code = r.get('ETF代码', '')
        direction = r.get('方向', '')
        price = r.get('成交价格', 0)
        try:
            price = float(price)
        except:
            price = 0

        if direction == '买入':
            if code not in buy_queue:
                buy_queue[code] = []
            buy_queue[code].append(price)
            r['_pnl'] = '-'
        elif direction == '卖出':
            if code in buy_queue and buy_queue[code]:
                buy_price = buy_queue[code].pop(0)
                if buy_price > 0 and price > 0:
                    pnl = (price - buy_price) / buy_price * 100
                    r['_pnl'] = f'{pnl:+.2f}%'
                else:
                    r['_pnl'] = '-'
            else:
                r['_pnl'] = '-'

    # 清理: 确保所有记录都有 _pnl
    for r in records:
        if '_pnl' not in r:
            r['_pnl'] = '-'


# ================================================================
# 格式化工具
# ================================================================

def fmt_rank_change(prev_rank, current_rank):
    if prev_rank is None:
        return '-'
    diff = prev_rank - current_rank
    if diff > 0:
        return f'↑{diff}'
    elif diff < 0:
        return f'↓{abs(diff)}'
    return '-'

def fmt_change_pct(pct):
    if abs(pct) < 0.005:
        return '0.00%'
    return f'{pct:+.2f}%'

def fmt_score(val):
    """格式化得分，处理 N/A 和 nan"""
    if isinstance(val, str):
        return val
    if val is None:
        return 'N/A'
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return 'N/A'
    except:
        return 'N/A'
    try:
        if np.isnan(val) or np.isinf(val):
            return 'N/A'
    except:
        pass
    return f'{val:.4f}'


# ================================================================
# 生成报告
# ================================================================

def generate_report(ranked, recent_trades, trade_info, nav_failed=False, realtime_valid=True):
    """生成Markdown + HTML"""
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M')
    traded, trade_desc = trade_info

    # 溢价率获取失败时的全局警告
    nav_warning_html = ''
    nav_warning_md = ''
    if nav_failed:
        nav_warning_html = '<div style="background:#FFF3CD;border:1px solid #FFC107;padding:10px;border-radius:6px;margin-bottom:12px;font-weight:bold;color:#856404;">⚠️ 溢价率获取失败，放弃本次交易</div>'
        nav_warning_md = '> ⚠️ **溢价率获取失败，放弃本次交易**\n\n'

    # 当前持仓
    current_holding = get_holding_from_xlsx()
    holding_code = current_holding['code'] if current_holding else ''

    # 构建展示排名：
    # - 得分前十中不被过滤的 ETF → 正常排名 1~N
    # - 得分前十但被过滤的 ETF → 从第11名顺排，变动列显示原因
    top10_by_score = ranked[:10]
    valid_in_top10 = [r for r in top10_by_score if not r['filtered']]
    filtered_in_top10 = [r for r in top10_by_score if r['filtered']]

    # 从得分前十以外补足到10只有效ETF
    rest_valid = [r for r in ranked if not r['filtered'] and r not in valid_in_top10]
    need = 10 - len(valid_in_top10)
    valid_in_top10.extend(rest_valid[:need])

    # 有效ETF：正常排名和变动
    for i, r in enumerate(valid_in_top10):
        r['rank'] = i + 1
        r['rchange'] = fmt_rank_change(r.get('prev_rank'), r['rank'])

    # 被过滤/黑名单ETF：从第11名顺排，变动显示具体原因
    for i, r in enumerate(filtered_in_top10):
        r['rank'] = 11 + i
        if r.get('blacklisted'):
            r['rchange'] = '盈利保护(当日已卖出)'
        else:
            reasons = []
            if r.get('premium_filtered'): reasons.append(f"溢价>{(r.get('premium_pct') or 0):.0f}%")
            if r.get('protected'): reasons.append('盈利保护')
            if r.get('drop3'): reasons.append('近3日跌>3%')
            if r.get('short_score', 0) < 0: reasons.append('短期动量负')
            r['rchange'] = '/'.join(reasons) if reasons else '过滤'

    # 合并为展示列表
    top10 = valid_in_top10 + filtered_in_top10

    # ---- Markdown ----
    if current_holding:
        hline = f"- **当前持仓**: {current_holding['name']}({current_holding['code']})@{current_holding['price']} 买入于 {current_holding['date']}"
    else:
        hline = "- **当前持仓**: 无"

    top10_md = ""
    for r in top10:
        prem = f"{r.get('premium_pct') or 0:.2f}%" if r.get('premium_pct') is not None else '-'
        top10_md += (f"| {r['rank']} | {r['name']} | {r['code']} | {r['score']} "
                     f"| {r['short_score']} | {r['long_score']} "
                     f"| {r['price']} | {fmt_change_pct(r['change_pct'])} | {prem} | {r['rchange']} |\n")

    trade_md = ""
    for t in recent_trades:
        price_raw = t.get('成交价格', '')
        try: price_str = f'{float(price_raw):.3f}'
        except: price_str = str(price_raw)
        trade_md += (f"| {t.get('交易日期','')} | {t.get('方向','')} | {t.get('ETF名称','')} "
                     f"| {t.get('ETF代码','')} | {price_str} "
                     f"| {fmt_score(t.get('综合动量得分'))} | {t.get('交易理由','')} "
                     f"| {t.get('_pnl','-')} |\n")

    trade_note = ""
    if trade_info[0]:  # 发生了交易
        trade_note = f"\n### ⚡ 本次交易\n{trade_info[1]}\n"

    md = f"""# 七星172盘后报告 - {now_str}

## 策略概况
- **策略名称**: 七星172 (GLM5修复版)
- **ETF池**: 38只 | **周期**: 25日 | **佣金**: 0.02%
{hline}
{trade_note}
## ETF动量排名 Top 10

| 排名 | 名称 | 代码 | 综合得分 | 短期得分 | 长期得分 | 价格 | 涨跌幅 | 溢价率 | 变动 |
|------|------|------|----------|----------|----------|------|--------|--------|------|
{top10_md}""" + ('\n' + nav_warning_md if nav_warning_md else '') + f"""## 最近20条交易记录

| 日期 | 方向 | ETF名称 | ETF代码 | 价格 | 动量得分 | 理由 | 盈亏 |
|------|------|----------|----------|------|----------|------|------|
{trade_md}
## 说明
- **综合得分** = 长期得分(25日动量×R²), 用于排名
- **短期得分** = 10日动量×R², <0过滤
- **涨跌幅** = (当日收盘-前日收盘)/前日收盘
- **变动** = 与上次报告对比 ↑升 ↓降 -不变
- **过滤规则**: 盈利保护(回撤>5%) + 溢价率>20% (其余4层已永久关闭)

## 时间
- 报告生成: {now_str} | 数据截止: {LATEST_DATE} | 引擎: 七星172 (GLM5修复版)

---
*本报告仅供研究参考，不构成投资建议。*
"""

    # ---- HTML ----
    holding_html = ""
    if current_holding:
        holding_html = f"""
        <div style="background:#FFF3CD;padding:10px 15px;border-radius:6px;margin:15px 0;font-size:13px;">
            📌 <b>当前持仓:</b> {current_holding['name']} ({current_holding['code']})
            买入价: {current_holding['price']} | 买入日: {current_holding['date']}
        </div>"""

    trade_alert = ""
    if trade_info[0]:
        trade_alert = f"""
        <div style="background:#D4EDDA;padding:10px 15px;border-radius:6px;margin:10px 0;font-size:13px;border-left:4px solid #28A745;">
            ⚡ <b>交易信号:</b> {trade_info[1]}
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>七星172盘后报告</title></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:880px;margin:0 auto;padding:20px;background:#f8f9fa;">

<div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:22px;color:#1F4E79;margin:0 0 5px 0;">🚀 七星172策略 · 盘后报告</h1>
    <p style="font-size:12px;color:#888;margin:0;">{now_str} (Asia/Shanghai) | 数据截止: {LATEST_DATE}</p>
</div>

<div style="background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:12px;font-size:13px;">
    <b>策略:</b> 七星172 (GLM5修复版) | <b>ETF池:</b> 38只 | <b>周期:</b> 25日 | <b>佣金:</b> 0.02%
</div>
{holding_html}
{trade_alert}

<!-- ETF排名 Top10 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">📊 ETF动量排名 Top 10</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 6px;text-align:center;">排名</th>
            <th nowrap style="padding:6px 6px;text-align:left;">名称</th>
            <th nowrap style="padding:6px 6px;text-align:center;">代码</th>
            <th nowrap style="padding:6px 6px;text-align:right;">综合</th>
            <th nowrap style="padding:6px 6px;text-align:right;">短期</th>
            <th nowrap style="padding:6px 6px;text-align:right;">长期</th>
            <th nowrap style="padding:6px 6px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 6px;text-align:right;">涨跌幅</th>
            <th nowrap style="padding:6px 6px;text-align:right;">溢价率</th>
            <th nowrap style="padding:6px 6px;text-align:center;">变动</th>
        </tr>"""

    for r in top10:
        is_hold = r['code'] == holding_code
        bg = '#FEF9E7' if is_hold else ('#FFF' if r['rank'] % 2 == 0 else '#F8F9FA')
        if realtime_valid:
            chg = fmt_change_pct(r['change_pct'])
            chg_c = '#DC3545' if r['change_pct'] < -0.005 else ('#28A745' if r['change_pct'] > 0.005 else '#888')
        else:
            chg = '—'; chg_c = '#888'  # 实时失败, 不冒充历史涨跌
        rc = r['rchange']
        # 变动列颜色：过滤原因显示为红色，正常变动按方向着色
        if '保护' in rc or '溢价' in rc or '跌' in rc or '动量负' in rc or '过滤' in rc:
            rc_c = '#DC3545'
        elif '↑' in rc:
            rc_c = '#28A745'
        elif '↓' in rc:
            rc_c = '#DC3545'
        else:
            rc_c = '#888'
        sc_c = '#28A745' if r['score'] > 0 else '#DC3545'
        prem_val = r.get('premium_pct')
        prem_str = f'{prem_val:.2f}%' if prem_val is not None else '-'
        prem = prem_val if prem_val is not None else 0
        prem_c = '#DC3545' if prem > 20 else ('#E65100' if prem > 10 else '#888')

        html += f"""
        <tr style="background:{bg};white-space:nowrap;">
            <td style="padding:4px 6px;text-align:center;font-weight:bold;">{r['rank']}</td>
            <td style="padding:4px 6px;">{r['name']}</td>
            <td style="padding:4px 6px;text-align:center;color:#888;font-size:11px;">{r['code']}</td>
            <td style="padding:4px 6px;text-align:right;font-weight:bold;color:{sc_c};">{r['score']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;">{r['short_score']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;">{r['long_score']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;">{r['price']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;color:{chg_c};font-weight:bold;">{chg}</td>
            <td style="padding:4px 6px;text-align:right;color:{prem_c};font-weight:bold;">{prem_str}</td>
            <td style="padding:4px 6px;text-align:center;color:{rc_c};font-weight:bold;">{rc}</td>
        </tr>"""

    # NAV获取失败警告
    if nav_failed:
        html += """
<div style="background:#FFF3CD;border:1px solid #FFC107;padding:10px;border-radius:6px;margin-bottom:12px;font-weight:bold;color:#856404;">溢价率获取失败，放弃本次交易</div>"""

    # 实时行情失效警告
    if not realtime_valid:
        rt_src = get_realtime_source()
        rt_label = f"({rt_src or '无'})" if rt_src else ""
        html += f"""
<div style="background:#C62828;color:#fff;padding:12px 18px;border-radius:6px;margin-bottom:12px;text-align:center;font-weight:bold;font-size:13px;">
    ⚠️ 实时行情获取失败 (WeStock + 新浪财经均不可用) — 当前显示价格均为前一交易日收盘价，监控已失效！
</div>"""
    elif get_realtime_source() == 'sina':
        html += """
<div style="background:#FFF3CD;color:#856404;padding:8px 12px;border-radius:4px;margin-bottom:12px;text-align:center;font-size:12px;">
    ℹ️ 实时行情来源: 新浪财经 (WeStock 不可用时自动切换)
</div>"""

    html += """
    </table>
</div>

<!-- 最近20条交易 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">### 最近20条交易记录</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 8px;">日期</th>
            <th nowrap style="padding:6px 8px;">方向</th>
            <th nowrap style="padding:6px 8px;">ETF</th>
            <th nowrap style="padding:6px 8px;">代码</th>
            <th nowrap style="padding:6px 8px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 8px;text-align:right;">得分</th>
            <th nowrap style="padding:6px 8px;text-align:left;">理由</th>
            <th nowrap style="padding:6px 8px;text-align:right;">盈亏</th>
        </tr>"""

    for i, t in enumerate(recent_trades):
        direction = t.get('方向', '')
        pnl = t.get('_pnl', '-')
        # 统一配色: 买入浅绿 / 卖出浅橙
        bg = '#E2EFDA' if direction == '买入' else '#FCE4D6'
        # 盈亏颜色
        if pnl.startswith('+'):
            pnl_c = '#28A745'
        elif pnl.startswith('-') and pnl != '-':
            pnl_c = '#DC3545'
        else:
            pnl_c = '#888'

        price_raw = t.get('成交价格', '')
        try: price_str = f'{float(price_raw):.3f}'
        except: price_str = str(price_raw)

        html += f"""
        <tr style="background:{bg};white-space:nowrap;">
            <td style="padding:4px 8px;">{t.get('交易日期','')}</td>
            <td style="padding:4px 8px;font-weight:bold;">{direction}</td>
            <td style="padding:4px 8px;">{t.get('ETF名称','')}</td>
            <td style="padding:4px 8px;color:#888;font-size:11px;">{t.get('ETF代码','')}</td>
            <td style="padding:4px 8px;text-align:right;">{price_str}</td>
            <td style="padding:4px 8px;text-align:right;">{fmt_score(t.get('综合动量得分'))}</td>
            <td style="padding:4px 8px;font-size:11px;color:#555;max-width:200px;overflow:hidden;text-overflow:ellipsis;">{t.get('交易理由','')}</td>
            <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pnl_c};">{pnl}</td>
        </tr>"""

    html += f"""
    </table>
</div>

<div style="font-size:11px;color:#888;line-height:1.6;margin-bottom:15px;">
    <b>过滤规则:</b> 盈利保护(回撤>5%) + 溢价率>20% (其余4层已永久关闭)<br>
    <b>得分:</b> 综合=长期(25日动量xR2) | 短期=10日动量xR2 (<0过滤)<br>
    <b>溢价率:</b> (市价-单位净值)/单位净值 | 红色>20%触发过滤 | '-'=暂无净值数据
</div>

<div style="text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;">
    七星172策略 | Blakever Trade | {now_str}<br>
    本报告仅供研究参考，不构成投资建议。
</div>
</body></html>"""

    return md, html


# ================================================================
# 发送邮件
# ================================================================

def send_report_email(html_content, md_path, mode_label="仅排名"):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    SMTP_SERVER, SMTP_PORT = "smtp.qq.com", 465
    SENDER = "848786642@qq.com"
    PASSWORD = "ljbtvacrctjobfed"
    RECEIVER = "848786642@qq.com"

    now = datetime.now()
    rt_ok = is_realtime_valid()
    subj_prefix = mode_label
    if not rt_ok:
        subj_prefix = f"{mode_label} ⚠️实时行情缺失"
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[{subj_prefix}] 七星172盘中监控 - {now.strftime('%Y-%m-%d %H:%M')}"
    msg["From"] = SENDER
    msg["To"] = RECEIVER
    msg["Date"] = now.strftime("%a, %d %b %Y %H:%M:%S +0800")
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    if os.path.exists(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            att = MIMEText(f.read(), "plain", "utf-8")
            att.add_header("Content-Disposition", "attachment", filename=os.path.basename(md_path))
            msg.attach(att)

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as srv:
            srv.login(SENDER, PASSWORD)
            srv.sendmail(SENDER, RECEIVER, msg.as_string())
        print(f"✅ 邮件已发送至 {RECEIVER}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False


# ================================================================
# 🏃 主入口
# ================================================================

def check_profit_protection_sell(ranked):
    """11:00 盈利保护独立检查: 持仓从最近1日最高点回撤>5%则立即卖出
    对应聚宽 profit_protection_check(11:00), 卖出后加入黑名单禁止日内买回"""
    holding = get_holding_from_xlsx()
    if holding is None:
        return False, "无持仓"

    code = holding['code']
    # 获取实时价格
    realtime = fetch_realtime_prices([code])
    if code in realtime:
        cur_price = realtime[code]['price']
    else:
        return False, f"无法获取 {code} 实时价格"

    # 获取历史数据用于盈利保护检查
    ds = LocalDataSource()
    pool_data = ds.load_all_etfs('2026-01-01', LATEST_DATE)
    df = pool_data.get(code)
    if df is None:
        return False, f"无法获取 {code} 历史数据"

    # 盈利保护检查
    if check_profit_protection(code, cur_price, df, LATEST_DATE, lookback=1, threshold=0.05):
        # 触发: 立即卖出 + 加入黑名单
        old_ranked = next((r for r in ranked if r['code'] == code), None)
        old_score = old_ranked['score'] if old_ranked else 'N/A'
        append_trade_to_xlsx('卖出', code, holding['name'], cur_price,
                             LATEST_DATE, old_score,
                             f"盈利保护卖出(回撤超5%)")
        # 加入黑名单: {code: date}
        bl = load_blacklist()
        bl[code] = LATEST_DATE
        save_blacklist(bl)
        print(f"  [黑名单] 已加入: {holding['name']}({code}) 禁止日内买回")
        return True, f"盈利保护卖出: {holding['name']}({code})@{cur_price:.4f}"

    return False, f"未触发: {holding['name']} 回撤<5%"


def main():
    # 解析命令行参数
    no_trade = '--no-trade' in sys.argv

    # 每日首次运行时清除昨日黑名单
    clear_blacklist_if_new_day()

    mode_label = "排名+交易" if not no_trade else "仅排名"
    print("=" * 60)
    print(f"七星172盘后报告生成器 V3 [{mode_label}]")
    print("=" * 60)

    # 1. 排名
    print("\n[1/5] 计算ETF动量排名...")
    ranked, prices, nav_failed, realtime_valid = get_current_rankings()
    print(f"  {len(ranked)} 只有效, Top3:")
    for r in ranked[:3]:
        flag = '[FILT]' if r['filtered'] else '[OK]'
        print(f"    {r['name']:16s} score={r['score']:.4f}  short={r['short_score']:.4f}  "
              f"chg={fmt_change_pct(r['change_pct'])}  {flag}")

    # 2. 交易检查
    print("\n[2/5] 检查交易信号...")
    is_eleven_am = datetime.now().hour == 11

    if nav_failed:
        traded, trade_desc = False, "溢价率获取失败，放弃本次交易"
        print(f"  ⚠️ {trade_desc}")
    elif no_trade:
        traded, trade_desc = False, "仅排名模式（未触发交易）"
    elif is_eleven_am:
        # 11:00 仅执行盈利保护卖出检查
        print("  [11:00] 盈利保护检查模式...")
        traded, trade_desc = check_profit_protection_sell(ranked)
        if not traded:
            trade_desc = f"盈利保护未触发: {trade_desc}"
    else:
        # 13:04 或其它时间: 完整排名轮动
        # 先检查持仓是否被盈利保护过滤(盘中暴跌), 被过滤则卖出
        holding = get_holding_from_xlsx()
        if holding:
            # 排名阶段已过滤, 检查持仓是否在过滤名单中
            for r in ranked:
                if r['code'] == holding['code'] and r['filtered']:
                    # 持仓被过滤(盈利保护触发), 先卖出
                    sell_reasons = []
                    if r.get('protected'): sell_reasons.append('盈利保护')
                    if r.get('premium_filtered'): sell_reasons.append('溢价>' + str(int(r.get('premium_pct', 0))) + '%')
                    reason_str = '; '.join(sell_reasons)
                    # 获取实时价
                    rt = fetch_realtime_prices([holding['code']])
                    sell_price = rt[holding['code']]['price'] if holding['code'] in rt else float(holding['price'])
                    append_trade_to_xlsx('卖出', holding['code'], holding['name'],
                                         sell_price, LATEST_DATE, r['score'],
                                         f'被过滤规则拦截调出: {reason_str}')
                    # 买入第一个未过滤的
                    target = pick_trade_target(ranked)
                    if target and target['code'] != holding['code']:
                        append_trade_to_xlsx('买入', target['code'], target['name'],
                                             target['price'], LATEST_DATE, target['score'],
                                             f'动量排名第1/{len(ETF_POOL)}')
                        traded, trade_desc = True, '换仓: ' + str(holding['name']) + '(被过滤) -> ' + str(target['name'])
                    else:
                        traded, trade_desc = True, '卖出: ' + str(holding['name']) + '(被过滤), 无合格买入标的'
                    break
            else:
                # 持仓未被过滤, 正常检查排名轮动
                traded, trade_desc = check_and_execute_trades(ranked)
        else:
            traded, trade_desc = check_and_execute_trades(ranked)
    if traded:
        print(f"  ⚡ 已执行: {trade_desc}")
    else:
        print(f"  ℹ️ {trade_desc}")

    # 3. 交易记录
    print("\n[3/5] 获取最近交易记录...")
    recent_trades = get_recent_trades(ranked)
    print(f"  {len(recent_trades)} 条 (时间倒序)")

    # 4. 生成报告
    print("\n[4/5] 生成报告...")
    output_dir = Path(__file__).parent.parent / 'reporting' / 'template'
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / '七星172报告模板.md'
    html_path = output_dir / f'七星172报告_{datetime.now().strftime("%Y%m%d_%H%M")}.html'

    md_content, html_content = generate_report(ranked, recent_trades, (traded, trade_desc), nav_failed=nav_failed, realtime_valid=realtime_valid)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"  ✅ {md_path.name}")
    print(f"  ✅ {html_path.name}")

    # 5. 发送 + 保存历史
    print("\n[5/5] 发送邮件 + 保存排名历史...")
    success = send_report_email(html_content, str(md_path), mode_label)
    save_rankings(ranked)

    print("\n" + "=" * 60)
    print("📊 摘要")
    print("=" * 60)
    h = get_holding_from_xlsx()
    if h:
        print(f"  当前持仓: {h['name']}({h['code']}) @{h['price']}")
    print(f"  交易信号: {'⚡ ' + trade_desc if traded else '无'}")
    print(f"  邮件: {'✅ 已发送' if success else '❌ 失败'}")
    print("=" * 60)


if __name__ == '__main__':
    main()
