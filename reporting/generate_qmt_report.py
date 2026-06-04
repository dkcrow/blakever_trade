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
NEODATA_SCRIPT = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'cb_teams_marketplace' / 'plugins' / 'finance-data' / 'skills' / 'neodata-financial-search' / 'scripts' / 'query.py')
WESTOCK_SCRIPT = str(Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'cb_teams_marketplace' / 'plugins' / 'finance-data' / 'skills' / 'westock-data' / 'scripts' / 'index.js')

# ================================================================
# QMT 51只ETF池 (聚宽格式 → 本地格式映射)
# ================================================================
QMT_RAW_CODES = [
    # 海外ETF (15) + 债券ETF (3)
    '513100','513290','513500','159529','513400','513520','513030','513080',
    '513310','513730','159792','513130','513050','159920','513690',
    '511380','511010','511220',
    # 商品ETF (7)
    '518880','159980','159985','501018','161226','159981','512400',
    # A股指数ETF (9)
    '510300','510500','510050','510210','159915','588080','512100','563360','563300',
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
    'sh513030': '德国ETF华安', 'sh513080': '法国ETF华安', 'sh513310': '中韩半导体ETF华泰柏瑞',
    'sh513730': '东南亚科技ETF华泰柏瑞', 'sz159792': '港股通互联网ETF富国', 'sh513130': '恒生科技ETF华泰柏瑞',
    'sh513050': '中概互联网ETF易方达', 'sz159920': '恒生ETF华夏', 'sh513690': '港股红利ETF博时',
    'sh511380': '可转债ETF博时', 'sh511010': '国债ETF国泰', 'sh511220': '城投债ETF海富通',
    'sh518880': '黄金ETF华安', 'sz159980': '有色ETF大成', 'sz159985': '豆粕ETF华夏',
    'sh501018': '南方原油LOF', 'sz161226': '国投白银LOF', 'sz159981': '能源化工ETF建信',
    'sh512400': '有色金属ETF南方',
    'sh510300': '沪深300ETF华泰柏瑞', 'sh510500': '中证500ETF南方', 'sh510050': '上证50ETF华夏',
    'sh510210': '上证指数ETF富国', 'sz159915': '创业板ETF易方达', 'sh588080': '科创50ETF易方达',
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
# 实时行情获取
# ================================================================
def fetch_realtime_prices(codes):
    realtime = {}
    a_codes = [c for c in codes if c.startswith('sh') or c.startswith('sz')]
    if not a_codes:
        return realtime
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
                        realtime[code_key] = {'price': cur_price, 'change_pct': round(change_pct, 2)}
                except (ValueError, IndexError):
                    continue
        except Exception:
            pass
    return realtime

# ================================================================
# 溢价率获取（三级兜底：neodata → akshare → westock-data）
# ================================================================

def _fetch_navs_tier1_neodata(raw_codes):
    """Tier 1: neodata API → {code: float}"""
    navs = {}
    batch_size = 15
    for batch_idx in range(0, len(raw_codes), batch_size):
        batch = raw_codes[batch_idx:batch_idx + batch_size]
        query = 'ETF ' + ' '.join(batch) + ' 最新行情 单位净值'
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
            content = r.get('content', '')
            rtype = r.get('type', '')
            if '实时行情' in rtype:
                for line in content.strip().split('\n')[2:]:
                    parts = [p.strip() for p in line.split('|') if p.strip()]
                    if len(parts) < 4:
                        continue
                    code = None
                    for p in parts:
                        if re.match(r'^\d{5,6}$', p):
                            code = p
                            break
                    if not code:
                        continue
                    try:
                        nav = float(parts[-1])
                        if 0.01 < nav < 10000:
                            navs[code] = nav
                    except ValueError:
                        pass
            elif '净值' in rtype or '净值' in r.get('desc', ''):
                for line in content.strip().split('\n')[2:]:
                    parts = [p.strip() for p in line.split('|') if p.strip()]
                    if len(parts) >= 4:
                        code = parts[0] if re.match(r'^\d{6}$', parts[0]) else None
                        if code:
                            try:
                                nav = float(parts[3])
                                if 0.01 < nav < 10000:
                                    if code not in navs:
                                        navs[code] = nav
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
            end_dt = pd.Timestamp(date_str)
            start_dt = end_dt - pd.Timedelta(days=2)
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


def fetch_all_navs(etf_codes):
    """三级兜底获取ETF净值。返回 (navs_dict, source_name)"""
    raw_codes = [c[2:] if (c.startswith('sh') or c.startswith('sz')) and len(c) > 2 else c
                 for c in etf_codes if c.startswith('sh') or c.startswith('sz')]
    if not raw_codes:
        return {}, None

    # Tier 1: neodata
    print("  [NAV] Tier1: neodata...")
    raw_navs = _fetch_navs_tier1_neodata(raw_codes)
    if raw_navs and len(raw_navs) >= max(3, len(raw_codes) // 3):
        navs = _map_raw_navs(raw_navs, etf_codes)
        print(f"  [NAV] neodata OK: {len(navs)} ETFs")
        return navs, 'neodata'
    print(f"  [NAV] neodata gave {len(raw_navs)} navs, trying next tier...")

    # Tier 2: akshare
    print("  [NAV] Tier2: akshare...")
    date_fmt = LATEST_DATE.replace('-', '')
    raw_navs = _fetch_navs_tier2_akshare(raw_codes, date_fmt)
    if raw_navs and len(raw_navs) >= max(3, len(raw_codes) // 3):
        navs = _map_raw_navs(raw_navs, etf_codes)
        print(f"  [NAV] akshare OK: {len(navs)} ETFs")
        return navs, 'akshare'
    print(f"  [NAV] akshare gave {len(raw_navs)} navs, trying next tier...")

    # Tier 3: westock-data
    print("  [NAV] Tier3: westock-data...")
    raw_navs = _fetch_navs_tier3_westock(raw_codes)
    if raw_navs and len(raw_navs) >= max(3, len(raw_codes) // 3):
        navs = _map_raw_navs(raw_navs, etf_codes)
        print(f"  [NAV] westock-data OK: {len(navs)} ETFs")
        return navs, 'westock'
    print(f"  [NAV] westock-data gave {len(raw_navs)} navs")

    # All failed
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
    print(f"  [RT] Got {len(realtime)}/{len(QMT_POOL)} realtime quotes")

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
    return ranked, current_prices, nav_available

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

def append_trade_to_xlsx(direction, code, name, price, date, score, reason):
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
# 行情判断 (简化版, 用于报告中展示)
# ================================================================
def get_regime_status():
    """简化版行情判断: 检查沪深300/创业板/上证/中证500与MA10关系"""
    import pandas as pd
    index_dir = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'index'
    index_map = {
        '沪深300': 'sh000300.csv',
        '创业板指': 'sz399006.csv',
        '上证指数': 'sh000001.csv',
        '中证500': 'sh000905.csv',
    }
    below_count = 0
    total = 0
    status_lines = []
    for name, fn in index_map.items():
        fp = index_dir / fn
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp)
            # normalize columns
            for c in df.columns:
                if c.lower().strip() == 'date' and c != 'date':
                    df = df.rename(columns={c: 'date'})
                elif c.lower().strip() == 'close' and c != 'close':
                    df = df.rename(columns={c: 'close'})
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            mask = df.index <= pd.Timestamp(LATEST_DATE)
            hist = df[mask]
            if len(hist) < 11:
                continue
            total += 1
            cur = hist['close'].iloc[-1]
            ma10 = hist['close'].iloc[-(10+1):-1].mean()
            below = cur < ma10
            if below: below_count += 1
            status_lines.append(f"{name}: {cur:.0f} {'<' if below else '>'} MA10={ma10:.0f} {'⚠️' if below else '✅'}")
        except Exception:
            pass

    threshold = max(2, int(total * 0.75))
    is_weak = below_count >= threshold if total > 0 else False
    regime_text = "走弱期" if is_weak else "正常期"
    return regime_text, is_weak, status_lines, below_count, total

# ================================================================
# 生成报告 (HTML)
# ================================================================
def generate_report(ranked, recent_trades, trade_info, time_label, regime_info=None, nav_available=True):
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
        holding_html = f"""
        <div style="background:#FFF3CD;padding:10px 15px;border-radius:6px;margin:15px 0;font-size:13px;">
            <b>当前持仓:</b> {current_holding['name']} ({current_holding['code']})
            买入价: {current_holding['price']} | 买入日: {current_holding['date']}
        </div>"""

    trade_alert = ""
    if trade_info[0]:
        trade_alert = f"""
        <div style="background:#D4EDDA;padding:10px 15px;border-radius:6px;margin:10px 0;font-size:13px;border-left:4px solid #28A745;">
            <b>交易信号:</b> {trade_info[1]}
        </div>"""

    # 行情判断
    regime_html = ""
    if regime_info:
        regime_text, is_weak, status_lines, below_count, total = regime_info
        regime_color = '#DC3545' if is_weak else '#28A745'
        lines_html = '<br>'.join(status_lines)
        regime_html = f"""
        <div style="background:#fff;padding:10px 15px;border-radius:8px;margin:10px 0;font-size:12px;border-left:4px solid {regime_color};">
            <b>行情判断:</b> <span style="color:{regime_color};font-weight:bold;">{regime_text}</span>
            ({below_count}/{total}指数跌破MA10)
            <div style="color:#666;margin-top:4px;">{lines_html}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>七星QMT原版盘中监控报告</title></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:880px;margin:0 auto;padding:20px;background:#f8f9fa;">

<div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:22px;color:#1F4E79;margin:0 0 5px 0;">七星QMT原版 · [{time_label}]</h1>
    <p style="font-size:12px;color:#888;margin:0;">{now_str} (Asia/Shanghai) | 数据截止: {LATEST_DATE}</p>
</div>

<div style="background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:12px;font-size:13px;">
    <b>策略:</b> 七星QMT原版 | <b>ETF池:</b> {len(QMT_POOL)}只 | <b>周期:</b> 25日 | <b>佣金:</b> 0.02%
    | <b>过滤:</b> 盈利保护(开) 成交量(关) 短期动量(关)
</div>
{holding_html}
{trade_alert}
{regime_html}

<!-- NAV失败警告 -->
""" + ("""        <div style="background:#FFF3CD;border:1px solid #FFC107;padding:10px;border-radius:6px;margin-bottom:12px;font-weight:bold;color:#856404;">⚠️ 溢价率获取失败，报告中显示为'-'</div>
""" if not nav_available else "") + f"""
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
        chg = fmt_change_pct(r['change_pct'])
        chg_c = '#DC3545' if r['change_pct'] < -0.005 else ('#28A745' if r['change_pct'] > 0.005 else '#888')
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

    html += """
    </table>
</div>

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

<div style="font-size:11px;color:#888;line-height:1.6;margin-bottom:15px;">
    <b>过滤规则 (QMT精简版):</b> 盈利保护(回撤>5%) → 溢价率(>20%)<br>
    <b>溢价率:</b> (市价-单位净值)/单位净值 | 红色>20%触发过滤 | '-'=暂无净值数据<br>
    <b>得分:</b> 综合=长期(25日动量xR2) | 短期=10日动量xR2<br>
    <b>变动:</b> 与上次报告对比 ↑升 ↓降 -不变<br>
    <b>回报:</b> 回测年化435.62% (2025.1-2026.5) | 聚宽验证总收益640% (2024.1-2026.5)
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
def send_report_email(html_content, md_path, time_label):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    SMTP_SERVER, SMTP_PORT = "smtp.qq.com", 465
    SENDER = "848786642@qq.com"
    PASSWORD = "ljbtvacrctjobfed"
    RECEIVER = "848786642@qq.com"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[{time_label}] 七星QMT原版 - {NOW_STR}"
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

    # 1. 排名
    print("\n[1/4] Computing ETF momentum rankings...")
    ranked, prices, nav_available = get_current_rankings()
    print(f"  {len(ranked)} valid, Top3:")
    for r in ranked[:3]:
        flag = '[FILT]' if r['filtered'] else '[OK]'
        print(f"    {r['name']:16s} score={r['score']:.4f}  chg={fmt_change_pct(r['change_pct'])}  {flag}")

    # 2. 行情判断
    print("\n[2/4] Checking regime status...")
    regime_info = get_regime_status()
    print(f"  Regime: {regime_info[0]} ({regime_info[3]}/{regime_info[4]} indices below MA10)")

    # 3. 交易检查
    print("\n[3/4] Checking trade signals...")
    allow_trade = not no_trade
    is_eleven_am = NOW.hour == 11
    traded, trade_desc = False, ""

    if not allow_trade:
        traded, trade_desc = False, "仅排名模式（未触发交易）"
    elif is_eleven_am:
        # 11:00 仅执行盈利保护检查（卖出），不执行排名轮动
        print("  [11:00] 盈利保护检查模式...")
        traded, trade_desc = check_profit_protection_sell(ranked)
        if not traded:
            trade_desc = f"盈利保护未触发: {trade_desc}"
    else:
        # 14:50 交易窗口: 若盈利保护已在11:00卖出 → 仅买入新#1；否则完整换仓
        holding = get_holding_from_xlsx()
        if holding is None and TRADES_XLSX.exists():
            # 今日可能已被盈利保护卖出(持仓为空)，需要买入
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
                traded, trade_desc = check_and_execute_trades(ranked, allow_trade=True)
        else:
            traded, trade_desc = check_and_execute_trades(ranked, allow_trade=True)
    if traded:
        print(f"  [TRADE] {trade_desc}")
    else:
        print(f"  [INFO] {trade_desc}")

    # 4. 生成报告 + 发送
    print("\n[4/4] Generating report + sending email...")
    recent_trades = get_recent_trades(ranked)
    md_content, html_content = generate_report(ranked, recent_trades, (traded, trade_desc), time_label, regime_info, nav_available)

    output_dir = Path(__file__).parent / 'template'
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f'七星QMT报告_{NOW.strftime("%Y%m%d_%H%M")}.md'
    html_path = output_dir / f'七星QMT报告_{NOW.strftime("%Y%m%d_%H%M")}.html'

    # Write using ASCII-safe encoding
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    success = send_report_email(html_content, str(md_path), time_label)
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
