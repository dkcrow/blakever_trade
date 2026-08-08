#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星QMT精简版盘中监控报告 (基于 V3, 关闭成交量+短期动量过滤)

每次执行:
1. 获取实时行情, 计算51只ETF动量排名
2. 对比持仓, 必要时执行换仓 (先卖后买, 精确到分钟)
3. 生成HTML邮件发送

时间点参考:
  09:10 开盘检查 [仅排名]  - check_positions
  09:40 行情判断 [仅排名]  - regime_check
  11:00 盈利保护 [可卖出]  - profit_protection_check (回撤>5%触发卖出)
  14:50 交易窗口 [排名+交易] - sell(14:51) + buy(14:52) 合并执行
  15:05 盘后总结 [仅排名]  - daily_summary
"""

import os, sys, math, json, warnings, urllib.request, re, subprocess, time
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.etf.seven_star_base import LocalDataSource, DEFENSIVE_ETF

# 溢价率获取工具（复用172报告三级兜底）
PYTHON_EXE = str(Path.home() / '.workbuddy' / 'binaries' / 'python' / 'envs' / 'default' / 'Scripts' / 'python.exe')
# 2026-06-22修复: 插件已迁移, 旧cb_teams_marketplace路径失效
NEODATA_SCRIPT = str(Path.home() / '.workbuddy' / 'skills-marketplace' / 'skills' / 'neodata-financial-search' / 'scripts' / 'query.py')
WESTOCK_SCRIPT = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'experts' / 'plugins' / 'stock-partner-team' / 'skills' / 'westock-data' / 'scripts' / 'index.js')

# ================================================================
# QMT ETF池 (2026-06-21: 移除德国30/东南亚, 加入科创芯片)
# ================================================================
QMT_RAW_CODES = [
    # 海外ETF (13) + 债券ETF (3)
    '513100','513290','513500','159529','513400','513520','513080',
    '513310','159792','513130','513050','159920','513690',
    '511380','511010','511220',
    # 商品ETF (7)
    '518880','159980','159985','501018','161226','159981','512400',
    # A股指数ETF (10)
    '510300','510500','510050','510210','159915','588080','588200','512100','563360','563300',
    # A股风格ETF (5)
    '512890','159967','588020','512040','159201',
    # A股行业板块ETF (12)
    '515790','563230','515880','512660','561380','159667','159559',
    '159819','159381','159732','159995','512220',
]
# 本地格式: shXXXXXX / szXXXXXX
QMT_POOL = ['sh' + c if c.startswith('5') else 'sz' + c for c in QMT_RAW_CODES]

# ETF名称映射 (从回测脚本中提取)
# ETF全称（数据来源: westock-data, 查询日期 2026-06-02）
QMT_NAMES = {
    'sh513100': '纳指ETF国泰', 'sh513290': '纳指生物科技ETF汇添富', 'sh513500': '标普500ETF博时',
    'sz159529': '标普消费ETF景顺', 'sh513400': '道琼斯ETF鹏华', 'sh513520': '日经ETF华夏',
    'sh513080': '法国ETF华安', 'sh513310': '中韩半导体ETF华泰柏瑞',
    'sz159792': '港股通互联网ETF富国', 'sh513130': '恒生科技ETF华泰柏瑞',
    'sh513050': '中概互联网ETF易方达', 'sz159920': '恒生ETF华夏', 'sh513690': '港股红利ETF博时',
    'sh511380': '可转债ETF博时', 'sh511010': '国债ETF国泰', 'sh511220': '城投债ETF海富通',
    'sh518880': '黄金ETF华安', 'sz159980': '有色ETF大成', 'sz159985': '豆粕ETF华夏',
    'sh501018': '南方原油LOF', 'sz161226': '国投白银LOF', 'sz159981': '能源化工ETF建信',
    'sh512400': '有色金属ETF南方',
    'sh510300': '沪深300ETF华泰柏瑞', 'sh510500': '中证500ETF南方', 'sh510050': '上证50ETF华夏',
    'sh510210': '上证指数ETF富国', 'sz159915': '创业板ETF易方达', 'sh588080': '科创50ETF易方达',
    'sh588200': '科创芯片ETF嘉实',
    'sh512100': '中证1000ETF南方', 'sh563360': 'A500ETF华泰柏瑞', 'sh563300': '中证2000ETF华泰柏瑞',
    'sh512890': '红利低波ETF华泰柏瑞', 'sz159967': '创业板成长ETF华夏', 'sh588020': '科创成长ETF易方达',
    'sh512040': '价值100ETF富国', 'sz159201': '自由现金流ETF华夏',
    'sh515790': '光伏ETF华泰柏瑞', 'sh563230': '卫星ETF富国', 'sh515880': '通信ETF国泰',
    'sh512660': '军工ETF国泰', 'sh561380': '电网设备ETF国泰', 'sz159667': '工业母机ETF国泰',
    'sz159559': '机器人ETF景顺', 'sz159819': '人工智能ETF易方达', 'sz159381': '创业板人工智能ETF华夏',
    'sz159732': '消费电子ETF华夏', 'sz159995': '芯片ETF华夏', 'sh512220': 'TMTETF景顺',
}

HISTORY_FILE = Path(__file__).parent / 'qmt_ranking_history.json'
TRADES_XLSX = Path(__file__).parent.parent / 'backtest' / 'results_qmt' / '七星QMT_交易记录_2026.xlsx'
PENDING_FILE = Path(__file__).parent / 'qmt_pending_buy.json'

# 日内趋势过滤 (2026-07-14 五福7.3思路: 买入前检查30分钟趋势, 下跌则延时重试)
ENABLE_INTRODAY_TREND = True
TREND_LOOKBACK_MINUTES = 30       # 检查最近N分钟趋势
TREND_SLOPE_THRESHOLD = 0.001     # 归一化斜率阈值 (%/min), 高于此判定上涨
TREND_RETRY_TIMES = ['13:40', '14:10', '14:40']  # 下跌趋势时的重试时间点
TREND_FORCE_TIME = '14:55'        # 强制买入时间

def get_latest_trading_date():
    today = datetime.now()
    if today.weekday() == 5:
        today = today - timedelta(days=1)
    elif today.weekday() == 6:
        today = today - timedelta(days=2)
    return today.strftime('%Y-%m-%d')

LATEST_DATE = get_latest_trading_date()
NOW = datetime.now()
NOW_STR = NOW.strftime('%Y-%m-%d %H:%M')

# ================================================================
# 实时行情获取 — 三级兜底 (L1→L2→降级CSV)
# L1: WeStock Data (腾讯自选股)  L2: 新浪财经 API  L3: 降级到CSV收盘价 + 邮件告警
# 规则: 全部失败时立即发送告警邮件，严禁静默使用过时数据
# ================================================================

_realtime_source_qmt = None

def is_realtime_valid():
    return _realtime_source_qmt is not None

def get_realtime_source():
    return _realtime_source_qmt

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
            req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
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
                        prices[code_key] = {'price': cur_price, 'change_pct': round(change_pct, 2)}
                except (ValueError, IndexError):
                    continue
        except Exception:
            pass
    return prices

def fetch_realtime_prices(codes):
    """获取A股ETF实时行情，三级兜底: L1 WeStock → L2 新浪 → 降级CSV"""
    global _realtime_source_qmt

    # L1: WeStock
    prices = _fetch_realtime_westock(codes)
    if prices:
        _realtime_source_qmt = 'westock'
        n_a = len([c for c in codes if c.startswith('sh') or c.startswith('sz')])
        print(f"  [RT] L1-WeStock OK: {len(prices)}/{n_a} quotes")
        return prices

    print(f"  [RT] L1-WeStock failed, trying L2-Sina...")

    # L2: 新浪
    prices = _fetch_realtime_sina(codes)
    if prices:
        _realtime_source_qmt = 'sina'
        n_a = len([c for c in codes if c.startswith('sh') or c.startswith('sz')])
        print(f"  [RT] L2-Sina OK: {len(prices)}/{n_a} quotes")
        return prices

    _realtime_source_qmt = None
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
<p>七星QMT监控任务于 <b>{now.strftime('%Y-%m-%d %H:%M')}</b> 执行时，所有实时行情获取渠道均已失败：</p>
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
<p style="color:#888;font-size:11px;">七星QMT · Blakever Trade · 自动告警<br>此邮件由系统自动发送，请勿回复。</p>
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
# 溢价率获取（三级兜底：neodata → akshare → westock-data）
# ================================================================

def _fetch_navs_tier1_neodata(raw_codes):
    """Tier 1: neodata API → {code: float}"""
    navs = {}
    batch_size = 15
    for batch_idx in range(0, len(raw_codes), batch_size):
        batch = raw_codes[batch_idx:batch_idx + batch_size]
        query = 'ETF ' + ' '.join(batch) + ' 单位净值'
        try:
            result = subprocess.run(
                [PYTHON_EXE, NEODATA_SCRIPT, '--query', query, '--data-type', 'api'],
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
            # 仅解析"基金净值和区间回报率"section, 跳过"实时行情"(那是市价不是净值)
            if '净值' not in rtype and '回报率' not in rtype:
                continue
            content = r.get('content', '')
            for line in content.strip().split('\n')[2:]:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) < 4:
                    continue
                # 代码格式: "513100.OF" 或 "513100" → 提取纯数字
                raw_code = parts[0].split('.')[0] if '.' in parts[0] else parts[0]
                if not re.match(r'^\d{6}$', raw_code):
                    continue
                try:
                    nav = float(parts[3])  # 单位净值(元)
                    if 0.01 < nav < 10000:
                        if raw_code not in navs:
                            navs[raw_code] = nav
                except ValueError:
                    pass
    return navs


def _fetch_navs_tier2_akshare(raw_codes, date_str):
    """Tier 2: akshare 下载最新 NAV → {code: float}"""
    try:
        import akshare as ak
    except ImportError:
        return {}
    navs = {}
    for code in raw_codes:
        try:
            # 2026-06-22修复: 窗口-2天太窄, 周末/节假日空区间会触发akshare异常→全失败
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
            time.sleep(0.3)
        except Exception:
            pass
    return navs


def _fetch_navs_tier3_westock(raw_codes):
    """Tier 3: westock-data CLI → {code: float}"""
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
            for p in parts[-3:]:
                try:
                    nav = float(p)
                    if 0.01 < nav < 10000:
                        navs[code] = nav
                        break
                except ValueError:
                    continue
    return navs


def _map_raw_navs(raw_navs, etf_codes):
    """将纯数字代码映射回 sh/sz 前缀"""
    navs = {}
    for code, nav in raw_navs.items():
        mapped = False
        for prefix in ('sh', 'sz', 'bj'):
            full_code = prefix + code
            if full_code in etf_codes:
                navs[full_code] = nav
                mapped = True
        if not mapped and code not in navs:
            navs[code] = nav
    return navs


def _refresh_neodata_token():
    """自动刷新neodata token (有效期12h)"""
    try:
        token_file = Path.home() / '.workbuddy' / '.neodata_token'
        if token_file.exists():
            data = json.loads(token_file.read_text(encoding='utf-8'))
            saved_at = data.get('saved_at', 0)
            if time.time() - saved_at < 11 * 3600:  # < 11h, still valid
                return True
        # Token过期, 尝试通过connect_cloud_service刷新
        # (仅在WorkBuddy主进程中可用, 定时任务中该功能不可用)
        return False
    except Exception:
        return False


def _fetch_navs_tier4_eastmoney(raw_codes):
    """Tier 4: 东方财富基金净值API直连 (无需认证)"""
    import requests
    navs = {}
    for code in raw_codes:
        try:
            url = 'https://api.fund.eastmoney.com/f10/lsjz'
            params = {
                'fundCode': code,
                'pageIndex': 1,
                'pageSize': 1,
            }
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://fundf10.eastmoney.com/',
            }
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


def fetch_all_navs(etf_codes):
    """四级兜底获取ETF净值: neodata → akshare → westock → eastmoney。
    各级成功后继续补充缺失代码，实现最大覆盖率。返回 (navs_dict, source_name)"""
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

    # Tier 2: akshare (仅补缺)
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

    # Tier 3: westock (仅补缺)
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

    # Tier 4: eastmoney (仅补缺, 始终运行因为无认证)
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

    print("  [NAV] ⚠️ ALL TIERS FAILED — 溢价率获取失败, 报告中显示为'-'")
    return {}, None

# ================================================================
# 排名计算
# ================================================================
def compute_scores(close_full, lookback):
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

def get_current_rankings():
    ds = LocalDataSource()
    all_data = ds.load_all_etfs('2026-01-01', LATEST_DATE, pool=QMT_POOL)
    # 筛选QMT池
    pool_data = {c: all_data[c] for c in QMT_POOL if c in all_data}
    print(f"  [DATA] QMT池 {len(QMT_POOL)}只, 本地有数据 {len(pool_data)}只")

    # 获取净值（三级兜底）
    print("  [NAV] Fetching ETF NAVs...")
    navs_dict, nav_source = fetch_all_navs(QMT_POOL)
    nav_available = nav_source is not None

    print("  [RT] Fetching realtime prices...")
    realtime = fetch_realtime_prices(QMT_POOL)
    rt_valid = is_realtime_valid()
    rt_source = get_realtime_source()
    if not rt_valid:
        send_realtime_failure_alert("仅排名")
    n_a = len([c for c in QMT_POOL if c.startswith('sh') or c.startswith('sz')])
    print(f"  [RT] Got {len(realtime)}/{n_a} realtime quotes (source: {rt_source or 'CSV降级'})")

    current_prices = {}
    prev_prices = {}
    for code, df in pool_data.items():
        mask = df.index <= pd.Timestamp(LATEST_DATE)
        if mask.any():
            if code in realtime:
                current_prices[code] = realtime[code]['price']
            else:
                current_prices[code] = float(df.loc[mask, 'close'].iloc[-1])
            closes = df.loc[mask, 'close']
            prev_prices[code] = float(closes.iloc[-2]) if len(closes) >= 2 else current_prices[code]

    prev_rankings = load_previous_rankings()
    prev_rank_map = {r['code']: r['rank'] for r in prev_rankings}

    ranked = []
    for code in QMT_POOL:
        df = pool_data.get(code)
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
        close_full = np.append(close_arr, cur)

        long_score, ann_ret_l = compute_scores(close_full, 25)
        short_score, _ = compute_scores(close_full, 10) if len(close_full) >= 11 else (0, 0)

        # 涨跌幅
        if code in realtime and 'change_pct' in realtime[code]:
            change_pct = realtime[code]['change_pct']
        else:
            prev = prev_prices.get(code, cur)
            change_pct = (cur - prev) / prev * 100 if prev > 0 else 0

        # ===== 四层过滤规则 (QMT V3 原版) =====
        filter_reasons = []

        # 1. 盈利保护: 最近1日最高点回撤>5%
        profit_protected = False
        if ENABLE_PROFIT_PROTECTION and 'high' in df.columns:
            high_arr = hist['high'].tail(PROFIT_PROTECTION_LOOKBACK)
            if len(high_arr) >= PROFIT_PROTECTION_LOOKBACK:
                max_high = high_arr.max()
                if cur <= max_high * (1 - PROFIT_PROTECTION_THRESHOLD):
                    profit_protected = True
                    drawdown_pct = (1 - cur/max_high) * 100
                    filter_reasons.append(f'盈利保护(回撤{drawdown_pct:.0f}%)')

        # 2. 成交量放量: 最新日成交量 < 20日均量 → 过滤
        volume_filtered = False
        if ENABLE_VOLUME_CHECK and 'volume' in df.columns:
            vol_arr = hist['volume'].tail(21)
            if len(vol_arr) >= 21:
                avg_vol = vol_arr[:-1].mean()  # 前20日均量
                latest_vol = vol_arr.iloc[-1]   # 最新日成交量
                if avg_vol > 0 and latest_vol < avg_vol * 0.5:  # 不到均量50%
                    volume_filtered = True
                    filter_reasons.append(f'量缩({latest_vol/avg_vol*100:.0f}%)')

        # 3. 短期动量: < 0 → 过滤
        short_momentum_filtered = False
        if ENABLE_SHORT_MOMENTUM_FILTER and short_score < 0:
            short_momentum_filtered = True
            filter_reasons.append(f'短期动量负({short_score:.2f})')

        # 4. 溢价率: >20% → 过滤
        # 三级兜底获取净值，计算溢价率
        nav = navs_dict.get(code)
        if nav and cur > 0 and nav > 0:
            premium_pct = round((cur - nav) / nav * 100, 2)
        else:
            premium_pct = None
        premium_filtered = (premium_pct is not None and premium_pct > 20.0)

        filtered = profit_protected or volume_filtered or short_momentum_filtered or premium_filtered

        ranked.append({
            'code': code,
            'name': QMT_NAMES.get(code, code),
            'score': round(long_score, 4),
            'short_score': round(short_score, 4),
            'long_score': round(long_score, 4),
            'price': round(cur, 4),
            'change_pct': round(change_pct, 2),
            'filtered': filtered,
            'profit_protected': profit_protected,
            'volume_filtered': volume_filtered,
            'short_momentum_filtered': short_momentum_filtered,
            'premium_filtered': premium_filtered,
            'premium_pct': premium_pct,
            'filter_reasons': filter_reasons,
            'prev_rank': prev_rank_map.get(code, None),
        })

    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked, current_prices, nav_available, is_realtime_valid()

def load_previous_rankings():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('rankings', [])
        except:
            pass
    return []

def save_rankings(ranked):
    data = {
        'date': LATEST_DATE,
        'generated': NOW.isoformat(),
        'rankings': [{'code': r['code'], 'rank': i+1, 'score': r['score']}
                      for i, r in enumerate(ranked)]
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ================================================================
# 交易检查与同步
# ================================================================
def get_holding_from_xlsx():
    """获取当前真实持仓：最后买入且未被后续卖出覆盖的ETF"""
    if not TRADES_XLSX.exists():
        return None
    df = pd.read_excel(TRADES_XLSX)
    holding = None
    for _, row in df.iterrows():
        if row.get('方向') == '买入':
            code = str(row.get('ETF代码', ''))
            stored_name = str(row.get('ETF名称', ''))
            # 优先用 QMT_NAMES 映射，避免显示原始代码
            display_name = QMT_NAMES.get(code, code)
            holding = {
                'code': code,
                'name': display_name,
                'price': row.get('成交价格', 0),
                'date': row.get('交易日期', ''),
            }
        elif row.get('方向') == '卖出':
            holding = None
    return holding

def pick_trade_target(ranked):
    for r in ranked:
        if not r['filtered']:
            return r
    return None

# ================================================================
# 日内趋势过滤 (2026-07-14 五福7.3思路)
# 买入前用WeStock minute数据判断30分钟趋势, 下跌则延时到13:40/14:10/14:40重试
# ================================================================
def check_intraday_trend(code):
    """判断ETF当前日内趋势。返回 (is_uptrend, slope_pct, detail)"""
    import subprocess
    from datetime import datetime
    try:
        westock_script = r"C:\Users\blakehao\.workbuddy\plugins\marketplaces\experts\plugins\stock-partner-team\skills\westock-data\scripts\index.js"
        result = subprocess.run(
            ['node', westock_script, 'minute', code, '--days', '1'],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).parent.parent)
        )
        if result.returncode != 0 or not result.stdout.strip():
            return (True, 0, f'WeStock无数据(默认买入)')
        
        # 解析markdown表格: | code | time | price | ...
        lines = result.stdout.strip().split('\n')
        prices = []
        for line in lines:
            if '---' in line or '|' not in line:
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) < 4 or parts[0] == 'code':
                continue
            try:
                prices.append(float(parts[3]))  # price column
            except (ValueError, IndexError):
                continue
        
        if len(prices) < 5:
            return (True, 0, f'分钟线不足({len(prices)}根,默认买入)')
        
        # 取最近N根
        recent = prices[-TREND_LOOKBACK_MINUTES:]
        if len(recent) < 5:
            recent = prices[-5:]
        
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]
        mean_price = np.mean(recent)
        slope_pct = slope / mean_price * 100 if mean_price > 0 else 0
        
        is_uptrend = slope_pct > TREND_SLOPE_THRESHOLD
        detail = f'{"📈上涨" if is_uptrend else "📉下跌"}(斜率{slope_pct:+.4f}%/min, 阈值{TREND_SLOPE_THRESHOLD})'
        return (is_uptrend, slope_pct, detail)
    except Exception as e:
        return (True, 0, f'趋势异常({e})默认买入')

def save_pending_buy(target):
    """将买入目标暂存到pending文件"""
    data = {}
    if PENDING_FILE.exists():
        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data = {
        'code': target['code'],
        'name': target['name'],
        'price': target['price'],
        'score': target['score'],
        'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'retry_count': data.get('retry_count', 0),
        'retry_history': data.get('retry_history', []),
    }
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_pending_buy():
    """读取pending买入目标"""
    if not PENDING_FILE.exists():
        return None
    with open(PENDING_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def clear_pending_buy():
    """清除pending文件"""
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()

def execute_pending_buy(pending, ranked, force=False):
    """执行pending买入。force=True时跳过趋势判断, 强制买入。返回 (traded, desc)"""
    target_code = pending['code']
    # 找到该标的在最新排名中的信息
    target = next((r for r in ranked if r['code'] == target_code), None)
    if target is None:
        clear_pending_buy()
        return (False, f'待买标的{target_code}不在排名中, 已清除')
    
    if not force:
        # 趋势判断
        is_up, slope_pct, detail = check_intraday_trend(target_code)
        if not is_up:
            pending['retry_count'] = pending.get('retry_count', 0) + 1
            pending['retry_history'] = pending.get('retry_history', [])
            pending['retry_history'].append(f"{datetime.now().strftime('%H:%M')}: {detail}")
            save_pending_buy(target)
            return (False, f'趋势复检{detail}, 继续等待')
    
    # 执行买入
    holding = get_holding_from_xlsx()
    if holding and holding['code'] == target_code:
        clear_pending_buy()
        return (False, f'已持有{target_code}, 无需买入')
    
    # 检查今日是否已有买入(防重复)
    if TRADES_XLSX.exists():
        df_check = pd.read_excel(TRADES_XLSX)
        today_buys = df_check[(df_check['交易日期'].astype(str).str.startswith(str(LATEST_DATE))) & (df_check['方向'] == '买入')]
        if len(today_buys) > 0:
            clear_pending_buy()
            return (False, '今日已有买入操作, 跳过')
    
    mode = '强制买入' if force else '趋势确认买入'
    reason = f"{mode}: 动量排名第1/{len(QMT_POOL)}"
    if not force:
        reason += f' (日内趋势上涨确认)'
    append_trade_to_xlsx('买入', target['code'], target['name'],
                         target['price'], LATEST_DATE, target['score'], reason)
    clear_pending_buy()
    return (True, f"{mode}: {target['name']}({target['code']})@{target['price']:.4f}")

# ================================================================
# 交易记录持久化
# ================================================================

def append_trade_to_xlsx(direction, code, name, price, date, score, reason):
    """追加一条交易记录到xlsx"""
    if TRADES_XLSX.exists():
        df = pd.read_excel(TRADES_XLSX)
    else:
        df = pd.DataFrame(columns=['交易日期','ETF名称','ETF代码','方向','成交价格','综合动量得分','交易理由'])
    # 精确到分钟
    date_str = str(date)
    if len(date_str) == 10 and date_str.count('-') == 2:
        date_str = f'{date_str} {NOW.strftime("%H:%M")}'
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
    # ensure directory
    TRADES_XLSX.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(TRADES_XLSX, index=False)

# ---- 策略参数 (QMT精简版: 仅盈利保护+溢价率, 关闭成交量+短期动量) ----
ENABLE_PROFIT_PROTECTION = True    # 盈利保护 (11:00 回撤>5%卖出)
ENABLE_VOLUME_CHECK = False        # 成交量放量过滤 (回测证实负向, 2026-06-03永久关闭)
ENABLE_SHORT_MOMENTUM_FILTER = False  # 短期动量过滤 (回测证实负向, 2026-06-03永久关闭)
ENABLE_PANIC_FILTER = False        # 成分股恐慌过滤 (2026-07-11克总拍板: 43段碎片化拖累全周期, 永久关闭)
PROFIT_PROTECTION_LOOKBACK = 1
PROFIT_PROTECTION_THRESHOLD = 0.05
SHORT_MOMENTUM_LOOKBACK = 10

def check_profit_protection_sell(ranked):
    """11:00 盈利保护检查：持仓ETF从最近N日最高点回撤>5%则触发卖出
    对应聚宽 profit_protection_check(11:00)，卖出后加入黑名单，14:50再买入新标的"""
    if not ENABLE_PROFIT_PROTECTION:
        return False, "盈利保护已关闭"

    holding = get_holding_from_xlsx()
    if holding is None:
        return False, "无持仓"

    code = holding['code']
    buy_price = float(holding['price'])

    # 获取持仓ETF的历史数据
    ds = LocalDataSource()
    pool_data = ds.load_all_etfs('2026-01-01', LATEST_DATE)
    df = pool_data.get(code)
    if df is None:
        return False, f"无法获取 {code} 历史数据"

    mask = df.index <= pd.Timestamp(LATEST_DATE)
    hist = df[mask]
    if len(hist) < PROFIT_PROTECTION_LOOKBACK:
        return False, f"{code} 历史数据不足"

    # 从最近N日最高点计算回撤
    max_high = hist['high'].tail(PROFIT_PROTECTION_LOOKBACK).max()
    # 获取当前价格
    realtime = fetch_realtime_prices([code])
    if code in realtime:
        current_price = realtime[code]['price']
    else:
        current_price = float(hist['close'].iloc[-1])

    drawdown_pct = (1 - current_price / max_high) * 100 if max_high > 0 else 0

    if current_price <= max_high * (1 - PROFIT_PROTECTION_THRESHOLD):
        # 触发盈利保护，卖出
        old_ranked = next((r for r in ranked if r['code'] == code), None)
        old_score = old_ranked['score'] if old_ranked else 'N/A'
        reason = f"盈利保护卖出: 回撤{drawdown_pct:.2f}%>{PROFIT_PROTECTION_THRESHOLD*100:.0f}% (最高价{max_high:.4f}→现价{current_price:.4f})"
        append_trade_to_xlsx('卖出', code, holding['name'], current_price,
                             LATEST_DATE, old_score, reason)
        return True, f"盈利保护卖出: {holding['name']}({code}) 回撤{drawdown_pct:.2f}% (最高{max_high:.4f}→{current_price:.4f})"

    return False, f"未触发: {holding['name']} 回撤{drawdown_pct:.2f}% < {PROFIT_PROTECTION_THRESHOLD*100:.0f}%"


def check_and_execute_trades(ranked, allow_trade=True):
    """根据排名检查是否需要换仓, allow_trade=False 时仅检查不执行"""
    if not allow_trade:
        return False, "仅排名模式（未触发交易）"

    # 全局检查: 同一天已有换仓则跳过
    if TRADES_XLSX.exists():
        df_check = pd.read_excel(TRADES_XLSX)
        today_trades = df_check[df_check['交易日期'].astype(str).str.startswith(str(LATEST_DATE))]
        if len(today_trades) > 0:
            directions = today_trades['方向'].tolist()
            return False, f"今日已有操作({', '.join(directions)})，跳过重复执行"

    holding = get_holding_from_xlsx()
    target = pick_trade_target(ranked)

    if target is None:
        return False, "无合格标的"

    if holding is None:
        append_trade_to_xlsx(
            '买入', target['code'], target['name'],
            target['price'], LATEST_DATE, target['score'],
            f"初始买入: 动量排名第1/{len(QMT_POOL)}"
        )
        return True, f"初始买入: {target['name']}({target['code']})@{target['price']:.4f}"

    if holding['code'] == target['code']:
        return False, f"持仓不变: {holding['name']} 仍是排名第一"

    # 换仓: 先卖后买
    old_ranked = next((r for r in ranked if r['code'] == holding['code']), None)
    old_score = old_ranked['score'] if old_ranked else 'N/A'

    # 卖出价: 优先用排名中的实时价，次选直接获取实时行情，兜底用持仓记录价
    if old_ranked:
        sell_price = old_ranked['price']
    else:
        rt = fetch_realtime_prices([holding['code']])
        if holding['code'] in rt:
            sell_price = rt[holding['code']]['price']
        else:
            sell_price = float(holding['price'])

    # 卖出理由
    if old_ranked:
        if old_ranked.get('filtered'):
            reasons = old_ranked.get('filter_reasons', [])
            sell_reason = '; '.join(reasons) if reasons else '被过滤规则排除'
        else:
            sell_reason = f"排名下降({old_ranked.get('prev_rank','?') or '?'}→{ranked.index(old_ranked)+1})调出"
    else:
        sell_reason = '调出目标(排名下降)'

    append_trade_to_xlsx(
        '卖出', holding['code'], holding['name'],
        sell_price, LATEST_DATE, old_score, sell_reason
    )
    append_trade_to_xlsx(
        '买入', target['code'], target['name'],
        target['price'], LATEST_DATE, target['score'],
        f"动量排名第1/{len(QMT_POOL)}"
    )

    return True, (f"换仓: 卖出 {holding['name']} → 买入 {target['name']}"
                  f"({target['code']})@{target['price']:.4f}")

# ================================================================
# 交易记录
# ================================================================
def get_recent_trades(ranked=None):
    if not TRADES_XLSX.exists():
        return []
    df = pd.read_excel(TRADES_XLSX)
    df['_dir_order'] = df['方向'].apply(lambda x: 0 if x == '买入' else 1)
    df = df.sort_values(['交易日期', '_dir_order'], ascending=[False, True]).head(20)
    df = df.drop(columns=['_dir_order'])
    records = df.to_dict('records')

    score_map = {}
    if ranked:
        for r in ranked:
            score_map[r['code']] = r['score']

    # 修正 ETF 名称（用 QMT_NAMES 映射）
    for r in records:
        code = str(r.get('ETF代码', ''))
        if code in QMT_NAMES:
            r['ETF名称'] = QMT_NAMES[code]

        score = r.get('综合动量得分', '')
        need_fix = False
        try:
            if score is None: need_fix = True
            elif isinstance(score, float) and (np.isnan(score) or np.isinf(score)):
                need_fix = True
            elif isinstance(score, str) and score.strip().upper() in ('N/A', 'NA', '-', ''):
                need_fix = True
        except:
            need_fix = True
        if need_fix:
            code = str(r.get('ETF代码', ''))
            if code in score_map:
                r['综合动量得分'] = round(score_map[code], 4)
            else:
                # 不在当前排名中（可能是历史ETF），尝试用代码匹配
                matched = None
                for km, sc in score_map.items():
                    if km.replace('sh','').replace('sz','') == code.replace('sh','').replace('sz',''):
                        matched = sc
                        break
                r['综合动量得分'] = round(matched, 4) if matched is not None else 'N/A'

        reason = str(r.get('交易理由', ''))
        if reason and '动量排名第1/' in reason:
            reason = re.sub(r'动量排名第1/\d+', f'动量排名第1/{len(QMT_POOL)}', reason)
            r['交易理由'] = reason

    compute_trade_pnl(records)
    return records

def compute_trade_pnl(records):
    if not records:
        return
    buy_queue = {}
    for i in range(len(records) - 1, -1, -1):
        r = records[i]
        code = r.get('ETF代码', '')
        direction = r.get('方向', '')
        price = r.get('成交价格', 0)
        try: price = float(price)
        except: price = 0

        if direction == '买入':
            if code not in buy_queue: buy_queue[code] = []
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
    for r in records:
        if '_pnl' not in r:
            r['_pnl'] = '-'

# ================================================================
# 格式化工具
# ================================================================
def fmt_rank_change(prev_rank, current_rank):
    if prev_rank is None: return '-'
    diff = prev_rank - current_rank
    if diff > 0: return f'↑{diff}'
    elif diff < 0: return f'↓{abs(diff)}'
    return '-'

def fmt_change_pct(pct):
    if abs(pct) < 0.005: return '0.00%'
    return f'{pct:+.2f}%'

def fmt_score(val):
    if isinstance(val, str): return val
    if val is None: return 'N/A'
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return 'N/A'
    except: return 'N/A'
    return f'{val:.4f}'

# ================================================================
# 行情判断 — 成分股恐慌期 (2026-06-23克总拍板: 80%·15日全局最优)
# 替换旧的A股4宽基指数版(克总: A股大盘被高度控盘不具备参考性)
# ================================================================
def get_regime_status(realtime_prices=None):
    """成分股恐慌期判定: QMT_POOL成分股中最新价跌破15日线比例 > 80% → 恐慌期 → 空仓防守。
    返回 (regime_text, is_weak, status_lines, below_count, total)
    现价优先用 realtime_prices(实时行情, {code:price}), 失败则降级CSV收盘价; MA15=近15个交易日收盘均值(不含当日)。
    """
    import pandas as pd
    lb = 15; thr = 0.80
    realtime_prices = realtime_prices or {}
    ds = LocalDataSource()
    try:
        pool_data = ds.load_all_etfs('2025-01-01', LATEST_DATE)
    except Exception:
        pool_data = {}
    below_count = 0; total = 0; status_lines = []
    for code, df in sorted(pool_data.items()):
        mask = df.index <= pd.Timestamp(LATEST_DATE)
        hist = df.loc[mask, 'close']
        if len(hist) < lb: continue
        # 现价: 实时行情优先(与排名/持仓一致), CSV收盘兜底
        rt_p = realtime_prices.get(code, 0)
        cur = float(rt_p) if rt_p and rt_p > 0 else float(hist.iloc[-1])
        # MA15 = 近15根K线收盘均值(不含当日，即倒数16~倒数2共15根)
        if len(hist) >= lb + 1:
            ma = float(hist.iloc[-(lb+1):-1].mean())
        else:
            ma = float(hist.iloc[-lb:].mean())
        total += 1
        below = cur < ma
        if below: below_count += 1
        name = QMT_NAMES.get(code, code)
        status_lines.append(f"{code} {name}: {cur:.2f} {'<' if below else '>'} MA15={ma:.2f} {'⚠️' if below else '✅'}")
    if total == 0:
        return ("数据不足", False, [], 0, 0)
    ratio = below_count / total
    is_panic = ratio > thr
    regime_text = "🔴恐慌期(空仓防守)" if is_panic else "🟢正常期"
    return (regime_text, is_panic, status_lines, below_count, total)

# ================================================================
# 生成报告 (HTML)
# ================================================================
def generate_report(ranked, recent_trades, trade_info, time_label, regime_info=None, nav_available=True, realtime_valid=True, stale_banner='', etf_health_html='', trend_info=''):
    current_holding = get_holding_from_xlsx()
    holding_code = current_holding['code'] if current_holding else ''

    # ===== 172风格分层排名 =====
    # 得分前十中: 未被过滤→正常排名1~N; 被过滤→从第11名顺排, 变动列显示原因
    top10_by_score = ranked[:10]
    valid_in_top10 = [r for r in top10_by_score if not r['filtered']]
    filtered_in_top10 = [r for r in top10_by_score if r['filtered']]

    # 从得分前十以外补足10只有效ETF
    rest_valid = [r for r in ranked if not r['filtered'] and r not in valid_in_top10]
    need = 10 - len(valid_in_top10)
    valid_in_top10.extend(rest_valid[:need])

    # 有效ETF: 正常排名和变动
    for i, r in enumerate(valid_in_top10):
        r['rank'] = i + 1
        r['rchange'] = fmt_rank_change(r.get('prev_rank'), r['rank'])

    # 被过滤ETF: 从第11名顺排, 变动显示具体原因
    for i, r in enumerate(filtered_in_top10):
        r['rank'] = 11 + i
        reasons = r.get('filter_reasons', [])
        r['rchange'] = '/'.join(reasons) if reasons else '过滤'

    # 合并展示列表
    top10 = valid_in_top10 + filtered_in_top10

    # HTML
    now_str = NOW_STR

    holding_html = ""
    if current_holding:
        # 从排名列表获取实时行情
        rt_price = current_holding['price']
        rt_chg = None
        code_clean = current_holding['code'].replace('sh','').replace('sz','')
        for r in ranked:
            rcode = r['code'].replace('sh','').replace('sz','')
            if rcode == code_clean:
                rt_price = r['price']
                rt_chg = r.get('change_pct', None)
                break
        chg_str = f"{rt_chg:+.2f}%" if rt_chg is not None else "—"
        chg_color = '#28A745' if (rt_chg or 0) > 0 else ('#DC3545' if (rt_chg or 0) < 0 else '#888')
        holding_html = f"""
        <div style="background:#fff;padding:15px 20px;border-radius:8px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">💼 当前持仓 (1只)</h3>
        <div style="overflow-x:auto;"><table style="font-size:8px;width:100%;border-collapse:collapse;">
        <tr><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">代码</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">名称</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">成本</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">现价</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">涨跌</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">买入日</th></tr>
        <tr><td style="padding:3px 8px;">{current_holding['code']}</td><td style="padding:3px 8px;white-space:nowrap;">{current_holding['name']}</td><td style="padding:3px 8px;text-align:right;">¥{current_holding['price']:.4f}</td><td style="padding:3px 8px;text-align:right;">¥{rt_price:.4f}</td><td style="padding:3px 8px;text-align:right;font-weight:bold;color:{chg_color};">{chg_str}</td><td style="padding:3px 8px;white-space:nowrap;">{current_holding['date']}</td></tr>
        </table></div></div>"""

    trade_alert = ""
    if trade_info[0]:
        trade_alert = f"""
        <div style="background:#D4EDDA;padding:10px 15px;border-radius:6px;margin:10px 0;font-size:13px;border-left:4px solid #28A745;">
            <b>交易信号:</b> {trade_info[1]}
        </div>"""
    # 日内趋势信息
    if trend_info:
        trade_alert += f"""
        <div style="background:#E8EAF6;padding:6px 10px;border-radius:4px;margin:5px 0;font-size:11px;border-left:4px solid #3F51B5;">
            <b>📈 日内趋势:</b> {trend_info}
        </div>"""

    # 行情判断 (2026-07-11: 成分股恐慌过滤已永久关闭, 回测证实43段碎片化拖累全周期)
    regime_html = ""
    if regime_info and ENABLE_PANIC_FILTER:
        import re
        regime_text, is_panic, status_lines, below_count, total = regime_info
        regime_color = '#DC3545' if is_panic else '#28A745'
        pct = below_count / total * 100 if total > 0 else 0
        m5color = '#DC3545' if is_panic else '#F9A825' if pct > 30 else '#28A745'
        # 构建逐只监控表格
        parsed_rows = []
        for line in status_lines:
            try:
                header, detail = line.split(': ', 1)
            except ValueError:
                continue
            parts = header.split(' ', 1)
            code = parts[0]
            name = parts[1] if len(parts) > 1 else code
            m = re.match(r'([\d.]+)\s*([<>])\s*MA15=([\d.]+)\s*(.+)', detail)
            if m:
                cur_val, rel, ma_val = float(m.group(1)), m.group(2), float(m.group(3))
                below = rel == '<'
                parsed_rows.append((code, name, cur_val, ma_val, below))
            else:
                parsed_rows.append((code, name, 0.0, 0.0, False))
        parsed_rows.sort(key=lambda d: (-d[4], -(d[3]-d[2])/d[3] if d[3]>0 else 0))
        table_rows = ""
        for code, name, cur_val, ma_val, below in parsed_rows:
            cc = '#DC3545' if below else '#28A745'
            fstr = '⚠️跌破' if below else '✅站上'
            table_rows += f'<tr style="white-space:nowrap;"><td style="padding:3px 8px;">{code}</td><td style="padding:3px 8px;">{name}</td><td style="text-align:right;padding:3px 8px;">{cur_val:.2f}</td><td style="text-align:right;padding:3px 8px;">{ma_val:.2f}</td><td style="text-align:right;font-weight:bold;color:{cc};padding:3px 8px;">{fstr}</td></tr>'
        regime_html = f"""
        <div class="card"><h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">📊 成分股15日线监控 <br><span style="font-size:12px;color:#888;">(>80%跌破触发恐慌空仓 · 共{total}只)</span></h3>
        <div style="background:#FFF8E1;padding:6px 10px;border-radius:6px;margin-bottom:10px;font-size:11px;white-space:nowrap;border-left:4px solid {m5color};">
        <b>恐慌状态:</b> <span style="color:{regime_color};font-weight:bold;">{regime_text}</span> — 跌破15日线: <b style="color:{m5color};">{below_count}/{total} ({pct:.0f}%)</b>
        </div>
        <div style="overflow-x:auto;"><table style="font-size:8px;width:100%;border-collapse:collapse;">
        <tr><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">代码</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">名称</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">现价</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">MA15</th><th style="background:#1F4E79;color:#fff;padding:5px;text-align:left;">状态</th></tr>
        {table_rows}</table></div></div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>七星QMT原版盘中监控报告</title></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:880px;margin:0 auto;padding:20px;background:#f8f9fa;">

<div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:22px;color:#1F4E79;margin:0 0 5px 0;">七星QMT原版 · [{time_label}]</h1>
    <p style="font-size:12px;color:#888;margin:0;">{now_str} (Asia/Shanghai) | 数据截止: {LATEST_DATE}</p>
</div>

{stale_banner}
{etf_health_html}
{trade_alert}
{regime_html}

<!-- NAV失败警告 -->
""" + ("""        <div style="background:#FFF3CD;border:1px solid #FFC107;padding:10px;border-radius:6px;margin-bottom:12px;font-weight:bold;color:#856404;">⚠️ 溢价率获取失败，报告中显示为'-'</div>
""" if not nav_available else "") + f"""
<!-- 实时行情失效警告 -->
""" + ("""        <div style="background:#C62828;color:#fff;padding:12px 18px;border-radius:6px;margin-bottom:12px;text-align:center;font-weight:bold;font-size:13px;">
    ⚠️ 实时行情获取失败 (WeStock + 新浪财经均不可用) — 当前显示价格均为前一交易日收盘价，监控已失效！
</div>
""" if not realtime_valid else "") + ("""        <div style="background:#FFF3CD;color:#856404;padding:8px 12px;border-radius:4px;margin-bottom:12px;text-align:center;font-size:12px;">
    ℹ️ 实时行情来源: 新浪财经 (WeStock 不可用时自动切换)
</div>
""" if (realtime_valid and get_realtime_source() == 'sina') else "") + f"""
<!-- ETF排名 Top10 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">ETF动量排名 Top 10</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 6px;text-align:center;">排名</th>
            <th nowrap style="padding:6px 6px;text-align:left;">名称</th>
            <th nowrap style="padding:6px 6px;text-align:center;">代码</th>
            <th nowrap style="padding:6px 6px;text-align:right;">综合得分</th>
            <th nowrap style="padding:6px 6px;text-align:right;">短期得分</th>
            <th nowrap style="padding:6px 6px;text-align:right;">长期得分</th>
            <th nowrap style="padding:6px 6px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 6px;text-align:right;">涨跌幅</th>
            <th nowrap style="padding:6px 6px;text-align:right;">溢价率</th>
            <th nowrap style="padding:6px 6px;text-align:center;">变动</th>
        </tr>"""

    for r in top10:
        is_hold = r['code'] == holding_code
        is_filtered = r['filtered']
        # 被过滤的ETF排到11+后用浅红背景
        bg = '#FCE4D6' if is_filtered else ('#FEF9E7' if is_hold else ('#FFF' if r['rank'] % 2 == 0 else '#F8F9FA'))
        if realtime_valid:
            chg = fmt_change_pct(r['change_pct'])
            chg_c = '#DC3545' if r['change_pct'] < -0.005 else ('#28A745' if r['change_pct'] > 0.005 else '#888')
        else:
            chg = '—'; chg_c = '#888'  # 实时失败, 不冒充历史涨跌
        rc = r['rchange']
        # 过滤原因标红，正常变动按方向着色
        if is_filtered:
            rc_c = '#DC3545'
        elif '↑' in rc: rc_c = '#28A745'
        elif '↓' in rc: rc_c = '#DC3545'
        else: rc_c = '#888'
        sc_c = '#28A745' if r['score'] > 0 else '#DC3545'

        # 溢价率
        prem_val = r.get('premium_pct')
        if prem_val is not None:
            prem_str = f'{prem_val:.2f}%'
            prem_c = '#DC3545' if prem_val > 20 else ('#28A745' if prem_val < -5 else '#888')
        else:
            prem_str = '-'
            prem_c = '#888'

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

    html += f"""
    </table>
</div>

{holding_html}

<!-- 最近20条交易 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">最近20条交易记录</h3>
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

    for t in recent_trades:
        direction = t.get('方向', '')
        pnl = t.get('_pnl', '-')
        bg = '#E2EFDA' if direction == '买入' else '#FCE4D6'
        if pnl.startswith('+'): pnl_c = '#28A745'
        elif pnl.startswith('-') and pnl != '-': pnl_c = '#DC3545'
        else: pnl_c = '#888'

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

<div style="text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;">
    七星QMT原版 · Blakever Trade · {now_str}<br>
    本报告仅供研究参考，不构成投资建议。
</div>
</body></html>"""

    # Markdown
    if current_holding:
        hline = f"- **当前持仓**: {current_holding['name']}({current_holding['code']})@{current_holding['price']} 买入于 {current_holding['date']}"
    else:
        hline = "- **当前持仓**: 无"

    top10_md = ""
    for r in top10:
        prem_val = r.get('premium_pct')
        prem_md = f'{prem_val:.2f}%' if prem_val is not None else '-'
        top10_md += f"| {r['rank']} | {r['name']} | {r['code']} | {r['score']:.4f} | {r['short_score']:.4f} | {r['long_score']:.4f} | {r['price']:.4f} | {fmt_change_pct(r['change_pct'])} | {prem_md} | {r['rchange']} |\n"

    trade_note = ""
    if trade_info[0]:
        trade_note = f"\n### 本次交易\n{trade_info[1]}\n"

    nav_warn_md = ""  # nav warning placeholder

    md = f"""# 七星QMT原版 [{time_label}] - {now_str}

## 策略概况
- **策略名称**: 七星QMT原版
- **ETF池**: {len(QMT_POOL)}只 | **周期**: 25日 | **佣金**: 0.02%
- **过滤配置**: 盈利保护(开) | 成交量(关) | 短期动量(关)
{hline}
{trade_note}
{nav_warn_md}
## ETF动量排名 Top 10

| 排名 | 名称 | 代码 | 综合得分 | 短期得分 | 长期得分 | 价格 | 涨跌幅 | 溢价率 | 变动 |
|------|------|------|----------|----------|----------|------|--------|--------|------|
{top10_md}
## 说明
- **综合得分** = 长期得分(25日动量xR2), 用于排名
- **短期得分** = 10日动量xR2
- **溢价率** = (市价-单位净值)/单位净值, '-'=暂无净值数据
- **变动** = 与上次报告对比 ↑升 ↓降 -不变
- **全过滤**: 盈利保护(5%回撤) + 溢价率检查(>20%) | 成交量+短期动量已永久关闭

## 时间
- 报告生成: {now_str} | 数据截止: {LATEST_DATE} | 引擎: 七星QMT原版
---
*本报告仅供研究参考，不构成投资建议。*
"""
    return md, html

# ================================================================
# 发送邮件
# ================================================================
def send_report_email(html_content, md_path, time_label, data_stale=False):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    SMTP_SERVER, SMTP_PORT = "smtp.qq.com", 465
    SENDER = "848786642@qq.com"
    PASSWORD = "ljbtvacrctjobfed"
    RECEIVER = "848786642@qq.com"

    rt_ok = is_realtime_valid()
    subj_prefix = time_label
    if not rt_ok:
        subj_prefix = f"{time_label} ⚠️实时行情缺失"
    elif data_stale:
        subj_prefix = f"{time_label} ⚠️ETF数据滞后"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[{subj_prefix}] 七星QMT原版 - {NOW_STR}"
    msg["From"] = SENDER
    msg["To"] = RECEIVER
    msg["Date"] = NOW.strftime("%a, %d %b %Y %H:%M:%S +0800")
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
        print(f"[OK] Email sent to {RECEIVER}")
        return True
    except Exception as e:
        print(f"[FAIL] Email: {e}")
        return False

# ================================================================
# 主入口
# ================================================================
def main():
    # 命令行参数
    no_trade = '--no-trade' in sys.argv

    # 确定时间标签
    time_label_map = {
        '09': '开盘检查 [09:10]',
        '11': '盈利保护 [11:00]',
        '14': '交易窗口 [14:50]' if not no_trade else '收盘终检 [14:50]',
        '15': '盘后总结 [15:05]',
    }
    current_hour = str(NOW.hour).zfill(2)
    if '--label' in sys.argv:
        idx = sys.argv.index('--label')
        time_label = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else '盘中监控'
    else:
        time_label = time_label_map.get(current_hour, f'盘中监控 [{current_hour}:{str(NOW.minute).zfill(2)}]')

    print("=" * 60)
    print(f"七星QMT原版 [{time_label}]")
    print("=" * 60)

    # ETF数据新鲜度校验 (克总2026-06-24: 严禁静默用旧数据)
    import sys as _sys_q, os as _os_q
    _qmt_root = Path(__file__).resolve().parent.parent
    _sys_q.path.insert(0, str(_qmt_root))
    from backtest.data_freshness import check_freshness, build_stale_banner as _build_stale, sync_etf_data
    _etf_dir = str(_qmt_root / 'data' / 'storage' / 'stock_data' / 'etf')
    _etf_codes = [c.replace('sh','').replace('sz','') for c in QMT_POOL]
    # 同步ETF数据
    print('[数据同步] 尝试更新QMT ETF数据...')
    try:
        _eupd, _esrc = sync_etf_data(QMT_POOL, _etf_dir)  # 传入sh/sz格式, 内部自动去前缀写文件
        print(f'[数据同步] 更新 {_eupd} 只 (源: {_esrc})')
    except Exception as _e: print(f'[数据同步] 失败: {_e}')
    # 新鲜度校验
    try:
        _stale, _gap, _dtls, __ = check_freshness(_etf_codes, _etf_dir, '{code}.csv', max_gap=3)
        qmt_stale_banner = _build_stale(_stale, _gap, _dtls, 'QMT ETF')
        qmt_stale = _stale
        if _stale:
            print(f'[数据告警] ⚠️ QMT ETF数据滞后 {_gap} 个交易日, {len(_dtls)} 只超阈值')
        else:
            print(f'[数据校验] QMT ETF数据新鲜 (最大滞后 {_gap} 交易日)')
    except Exception as _e:
        qmt_stale = False; qmt_stale_banner = ''
        print(f'[数据校验] 跳过: {_e}')

    # 1. 排名
    print("\n[1/4] Computing ETF momentum rankings...")
    ranked, prices, nav_available, realtime_valid = get_current_rankings()
    print(f"  {len(ranked)} valid, Top3:")
    for r in ranked[:3]:
        flag = '[FILT]' if r['filtered'] else '[OK]'
        print(f"    {r['name']:16s} score={r['score']:.4f}  chg={fmt_change_pct(r['change_pct'])}  {flag}")

    # 2. 行情判断 (成分股80%·15日恐慌过滤 — 2026-07-11已关闭)
    if ENABLE_PANIC_FILTER:
        print("\n[2/4] Checking panic regime (成分股80%·15日)...")
        regime_info = get_regime_status(prices)
        _, is_panic, _, below_count, total = regime_info
        print(f"  Regime: {regime_info[0]} ({below_count}/{total}成分股跌破MA15)")
    else:
        is_panic = False
        regime_info = ('🟢正常期(恐慌已关闭)', False, [], 0, 0)
        print("\n[2/4] Panic filter DISABLED (成分股恐慌过滤已永久关闭)")

    # 2.5 日内趋势 (始终展示Top1标的的30分钟趋势, 无论是否交易窗口)
    trend_info = ""
    if ENABLE_INTRODAY_TREND and len(ranked) > 0:
        top_pick = pick_trade_target(ranked)
        if top_pick:
            is_up, slope_pct, trend_detail = check_intraday_trend(top_pick['code'])
            trend_icon = '📈' if is_up else '📉'
            trend_label = '上涨' if is_up else '下跌'
            action_hint = '可立即买入' if is_up else '待趋势转涨买入(13:40/14:10/14:40复检, 14:55强制)'
            trend_info = f'{trend_icon} #{1} {top_pick["name"]}({top_pick["code"]}): {trend_label}(斜率{slope_pct:+.4f}%/min) — {action_hint}'
            print(f"  [趋势] {trend_info}")

    # 3. 交易检查
    print("\n[3/4] Checking trade signals...")
    allow_trade = not no_trade
    is_eleven_am = NOW.hour == 11
    now_str = NOW.strftime('%H:%M')
    traded, trade_desc = False, ""
    # trend_info 已在步骤2.5中设置(始终展示Top1趋势), 此处不重置

    if is_panic and allow_trade:
        # 恐慌期 → 卖出一切持仓, 空仓防守, 不买入
        print("  🔴 恐慌期: 卖出一切持仓 → 空仓防守")
        holding = get_holding_from_xlsx()
        if holding:
            sell_price = float(holding['price'])
            try:
                rt = fetch_realtime_prices([holding['code']])
                if holding['code'] in rt and rt[holding['code']]['price'] > 0:
                    sell_price = rt[holding['code']]['price']
            except Exception:
                pass
            append_trade_to_xlsx('卖出', holding['code'], holding['name'],
                                sell_price, LATEST_DATE, 'N/A', '恐慌期空仓防守(>80%成分股跌破MA15)')
            traded, trade_desc = True, f"恐慌期: 卖出 {holding['name']}({holding['code']})@{sell_price:.3f} → 空仓防守"
        else:
            traded, trade_desc = True, "恐慌期: 已空仓, 保持持币待复苏"
        clear_pending_buy()
    elif is_panic and not allow_trade:
        traded, trade_desc = True, f"恐慌期(模拟): {regime_info[0]} — 若实盘则清仓空仓防守"
    elif is_eleven_am and not no_trade:
        # 11:00 仅执行盈利保护检查（卖出），不执行排名轮动
        print("  [11:00] 盈利保护检查模式...")
        traded, trade_desc = check_profit_protection_sell(ranked)
        if not traded:
            trade_desc = f"盈利保护未触发: {trade_desc}"
    elif ENABLE_INTRODAY_TREND and allow_trade and now_str >= '13:05' and now_str < '14:50':
        # ====== 日内趋势交易窗口 (13:05~14:50, 自动化提前5分钟执行) ======
        target = pick_trade_target(ranked)
        holding = get_holding_from_xlsx()

        if now_str < '13:35':
            # 13:10 核心窗口: 排名+卖出+趋势判断
            print("  [13:10] 日内趋势交易窗口...")
            # 先卖出(如果持仓不是目标)
            if holding and target and holding['code'] != target['code']:
                old_ranked = next((r for r in ranked if r['code'] == holding['code']), None)
                old_score = old_ranked['score'] if old_ranked else 'N/A'
                if old_ranked:
                    sell_price = old_ranked['price']
                else:
                    rt = fetch_realtime_prices([holding['code']])
                    sell_price = rt.get(holding['code'], {}).get('price', float(holding['price'])) if rt else float(holding['price'])
                append_trade_to_xlsx('卖出', holding['code'], holding['name'],
                                     sell_price, LATEST_DATE, old_score, '日内趋势: 换仓卖出')
                print(f"  [卖出] {holding['name']}({holding['code']})@{sell_price:.4f}")
                traded = True
                holding = None

            if target:
                if holding and holding['code'] == target['code']:
                    trade_desc = f"持仓不变: {holding['name']} 仍是排名第一"
                    clear_pending_buy()
                else:
                    is_up, slope_pct, trend_detail = check_intraday_trend(target['code'])
                    trend_info = trend_detail
                    print(f"  [趋势] {target['name']}({target['code']}): {trend_detail}")
                    if is_up:
                        append_trade_to_xlsx('买入', target['code'], target['name'],
                                             target['price'], LATEST_DATE, target['score'],
                                             f'日内趋势上涨确认: 动量排名第1/{len(QMT_POOL)}')
                        traded = True
                        trade_desc = f"趋势上涨买入: {target['name']}({target['code']})@{target['price']:.4f}"
                        clear_pending_buy()
                    else:
                        save_pending_buy(target)
                        trade_desc = f"趋势下跌, 暂缓买入 {target['name']}({target['code']}), 等待{TREND_RETRY_TIMES}复检后{TREND_FORCE_TIME}强制买入"

        elif now_str < '14:05':
            retry_label = '13:40'
            print(f"  [{retry_label}] 趋势复检窗口...")
            pending = load_pending_buy()
            if pending:
                print(f"  [待买] {pending['name']}({pending['code']}), 第{pending.get('retry_count',0)+1}次复检")
                traded, trade_desc = execute_pending_buy(pending, ranked, force=False)
            else:
                trade_desc = "无待买目标"

        elif now_str < '14:35':
            retry_label = '14:10'
            print(f"  [{retry_label}] 趋势复检窗口...")
            pending = load_pending_buy()
            if pending:
                print(f"  [待买] {pending['name']}({pending['code']}), 第{pending.get('retry_count',0)+1}次复检")
                traded, trade_desc = execute_pending_buy(pending, ranked, force=False)
            else:
                trade_desc = "无待买目标"

        else:
            retry_label = '14:40'
            print(f"  [{retry_label}] 趋势复检窗口...")
            pending = load_pending_buy()
            if pending:
                print(f"  [待买] {pending['name']}({pending['code']}), 第{pending.get('retry_count',0)+1}次复检")
                traded, trade_desc = execute_pending_buy(pending, ranked, force=False)
            else:
                trade_desc = "无待买目标"

    elif ENABLE_INTRODAY_TREND and now_str >= '14:50':
        # 14:55 强制买入 (自动化提前5分钟执行)
        print("  [14:55] 强制买入窗口...")
        pending = load_pending_buy()
        if pending:
            print(f"  [强制买入] {pending['name']}({pending['code']}) (日内趋势延时到期)")
            traded, trade_desc = execute_pending_buy(pending, ranked, force=True)
            trend_info = f"14:55强制买入(趋势延时到期, 经{pending.get('retry_count',0)}次复检)"
        else:
            # 无pending → 正常换仓(兜底: 当日未在趋势窗口执行过交易的场景)
            holding = get_holding_from_xlsx()
            if holding is None and TRADES_XLSX.exists():
                df_today = pd.read_excel(TRADES_XLSX)
                today_sells = df_today[(df_today['交易日期'].astype(str).str.startswith(str(LATEST_DATE))) & (df_today['方向'] == '卖出')]
                if len(today_sells) > 0:
                    target = pick_trade_target(ranked)
                    if target:
                        append_trade_to_xlsx('买入', target['code'], target['name'],
                                             target['price'], LATEST_DATE, target['score'],
                                             f"盈利保护后补仓: 动量排名第1/{len(QMT_POOL)}")
                        traded, trade_desc = True, f"14:55补仓: 买入 {target['name']}({target['code']})@{target['price']:.4f}"
                    else:
                        traded, trade_desc = False, "14:55无合格标的"
                else:
                    if allow_trade:
                        traded, trade_desc = check_and_execute_trades(ranked, allow_trade=True)
                    else:
                        traded, trade_desc = False, "仅排名模式"
            else:
                if allow_trade:
                    traded, trade_desc = check_and_execute_trades(ranked, allow_trade=True)
                elif holding is not None:
                    trade_desc = f"仅排名: 持仓 {holding['name']} 不变"
                else:
                    trade_desc = "仅排名: 空仓"

    else:
        # 其他时间窗口 (09:10/09:40等) 或关闭日内趋势
        if not ENABLE_INTRODAY_TREND:
            holding = get_holding_from_xlsx()
            if holding is None and TRADES_XLSX.exists():
                df_today = pd.read_excel(TRADES_XLSX)
                today_sells = df_today[(df_today['交易日期'].astype(str).str.startswith(str(LATEST_DATE))) & (df_today['方向'] == '卖出')]
                if len(today_sells) > 0:
                    target = pick_trade_target(ranked)
                    if target:
                        append_trade_to_xlsx('买入', target['code'], target['name'],
                                             target['price'], LATEST_DATE, target['score'],
                                             f"盈利保护后补仓: 动量排名第1/{len(QMT_POOL)}")
                        traded, trade_desc = True, f"盈利保护后补仓: 买入 {target['name']}({target['code']})@{target['price']:.4f}"
                    else:
                        traded, trade_desc = False, "盈利保护已卖出，但无新买入标的"
                else:
                    if allow_trade and not no_trade:
                        traded, trade_desc = check_and_execute_trades(ranked, allow_trade=True)
                    else:
                        traded, trade_desc = False, "仅排名模式"
            else:
                if allow_trade and not no_trade:
                    traded, trade_desc = check_and_execute_trades(ranked, allow_trade=True)
                else:
                    traded, trade_desc = False, "仅排名模式"
        else:
            # 非交易窗口(如09:10开盘检查), 仅排名不交易
            clear_pending_buy()
            trade_desc = f"仅排名模式 ({time_label})"

    if traded:
        print(f"  [TRADE] {trade_desc}")
    else:
        print(f"  [INFO] {trade_desc}")

    # 4. 生成报告 + 发送
    print("\n[4/4] Generating report + sending email...")
    recent_trades = get_recent_trades(ranked)

    # ETF池健康检查 (仅在09:10开盘检查时运行)
    etf_health_html = ''
    if current_hour == '09':
        print("  [ETF健康] 执行ETF池健康检查...")
        try:
            from reporting.etf_pool_health import run_health_check, generate_html as _gen_health_html
            _health = run_health_check(QMT_POOL, QMT_NAMES)
            etf_health_html = _gen_health_html(_health, QMT_POOL)
            _w, _d = len(_health['warn']), len(_health['dead'])
            print(f"  [ETF健康] 完成: OK={len(_health['ok'])} 预警={_w} 无数据={_d}")
            # 若超阈值则单独发送告警邮件
            from reporting.etf_pool_health import should_alert, send_health_alert
            if should_alert(_health):
                print(f"  [ETF健康] ⚠️ 触发告警阈值, 发送单独告警邮件...")
                send_health_alert(_health)
        except Exception as _he:
            print(f"  [ETF健康] 失败: {_he}")

    md_content, html_content = generate_report(ranked, recent_trades, (traded, trade_desc), time_label, regime_info, nav_available, realtime_valid, stale_banner=qmt_stale_banner, etf_health_html=etf_health_html, trend_info=trend_info)

    output_dir = Path(__file__).parent / 'template'
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f'七星QMT报告_{NOW.strftime("%Y%m%d_%H%M")}.md'
    html_path = output_dir / f'七星QMT报告_{NOW.strftime("%Y%m%d_%H%M")}.html'

    # Write using ASCII-safe encoding
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    success = send_report_email(html_content, str(md_path), time_label, data_stale=qmt_stale)
    save_rankings(ranked)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    h = get_holding_from_xlsx()
    if h:
        print(f"  Holding: {h['name']}({h['code']}) @{h['price']}")
    print(f"  Trade: {'[TRADE] ' + trade_desc if traded else 'None'}")
    print(f"  Email: {'[OK] Sent' if success else '[FAIL]'}")
    print("=" * 60)


if __name__ == '__main__':
    main()
