#!/usr/bin/env python3
"""七星175 V3.15 实盘报告 — 双risk四格池 + 加权动量排名 (版式对齐172)"""
import os, sys, math, json, warnings, re, subprocess
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
warnings.filterwarnings('ignore')

NOW = datetime.now()
NOW_STR = NOW.strftime('%Y-%m-%d %H:%M')
NOW_FILE = NOW.strftime('%Y%m%d_%H%M')

def get_latest_trading_date():
    today = datetime.now()
    if today.weekday() == 5: today -= timedelta(days=1)
    elif today.weekday() == 6: today -= timedelta(days=2)
    return today.strftime('%Y-%m-%d')

LATEST_DATE = get_latest_trading_date()

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / 'data' / 'storage' / 'stock_data' / 'etf'
OUT_DIR = SCRIPT_DIR / 'reporting' / 'template'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ============ 175 ETF池 ============
OVERSEAS = {
    '513100': '纳指ETF', '159509': '纳指科技ETF', '513290': '纳指生物科技ETF',
    '513500': '标普500ETF', '159529': '标普消费ETF', '513400': '道琼斯ETF',
    '513520': '日经ETF', '513030': '德国ETF', '513080': '法国ETF',
    '513310': '中韩半导体ETF', '513730': '东南亚科技ETF', '159792': '港股通互联网ETF',
    '513130': '恒生科技ETF', '513050': '中概互联ETF', '159920': '恒生ETF',
    '513690': '港股红利ETF', '511380': '可转债ETF', '511010': '国债ETF', '511220': '城投债ETF',
}
COMMODITY = {
    '518880': '黄金ETF', '159980': '有色金属ETF', '159985': '豆粕ETF',
    '501018': '南方原油LOF', '161226': '白银基金LOF', '159981': '能源化工ETF',
    '512400': '工业有色ETF',
}
DOMESTIC = {
    '510300': '沪深300ETF', '510500': '中证500ETF', '510050': '上证50ETF',
    '510210': '上证综指ETF', '159915': '创业板ETF',
    '588080': '科创50ETF', '512100': '中证1000ETF',
    '563360': '中证A500ETF', '563300': '中证2000ETF',
    '512890': '红利低波ETF', '159967': '创业板成长ETF',
    '588020': '科创成长ETF', '512040': '价值ETF', '159201': '自由现金流ETF',
    '515790': '光伏ETF', '563230': '卫星ETF', '515880': '通信ETF',
    '512660': '军工ETF', '561380': '电力ETF', '159667': '工业母机ETF',
    '159559': '机器人ETF', '159819': 'AI智能ETF', '159381': '人工智能ETF',
    '159732': '消费电子ETF', '159995': '芯片ETF', '512220': 'TMTETF',
}

ALL_POOL = {}; [ALL_POOL.update(d) for d in [OVERSEAS, COMMODITY, DOMESTIC]]
OVERSEAS_SET = set(OVERSEAS.keys()); COMMODITY_SET = set(COMMODITY.keys()); DOMESTIC_SET = set(DOMESTIC.keys())

A_PROXIES = {'510300': '沪深300', '510210': '上证指数', '510050': '上证50',
             '159915': '创业板指', '512100': '中证1000', '563300': '中证2000'}
O_PROXIES = {'159509': '纳指科技', '513500': '标普500', '513400': '道琼斯', '513520': '日经'}

# ============ 参数 ============
LB, SLB, CASH, COMM, MIN_COMM, TAX, SLIP, HOLDINGS = 25, 10, 100000, 0.0005, 5, 0.001, 0.0001, 1
HOLDING_PROFIT_SKIP_MINUTE_PCT = 0.10
HOLDING_PROFIT_SKIP_PREV_CLOSE_PCT = 0.10
OVERSEAS_ROTATION_COOLDOWN_DAYS = 1

# ============ 实时行情 ============
# 2026-06-22修复: 插件迁移, 旧cb_teams_marketplace路径失效
WESTOCK_SCRIPT = str(Path.home() / '.workbuddy/plugins/marketplaces/experts/plugins/stock-partner-team/skills/westock-data/scripts/index.js')

def _fetch_westock(codes):
    prices = {}
    sh_codes = [f'sh{c}' for c in codes if c.startswith('5')]
    sz_codes = [f'sz{c}' for c in codes if c.startswith(('1','0'))]
    all_wc = sh_codes + sz_codes
    if not all_wc: return prices
    try:
        result = subprocess.run(['node', WESTOCK_SCRIPT, 'quote', ','.join(all_wc)],
            capture_output=True, text=True, timeout=30, cwd=os.path.dirname(WESTOCK_SCRIPT))
        if result.returncode != 0: return prices
        in_table, col_idx = False, {}
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line.startswith('|'): continue
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if not in_table:
                for i, h in enumerate(parts):
                    if h == 'code': col_idx['code'] = i
                    elif h == 'price': col_idx['price'] = i
                    elif h == 'change_percent': col_idx['chg'] = i
                in_table = True; continue
            if all(p.replace('-','').replace(':','') == '' for p in parts): continue
            if 'code' in col_idx and 'price' in col_idx:
                code_raw = parts[col_idx['code']].replace('sh','').replace('sz','')
                try: p = float(parts[col_idx['price']])
                except: continue
                if p <= 0: continue
                chg = 0.0
                if 'chg' in col_idx:
                    try: chg = float(parts[col_idx['chg']])
                    except: pass
                prices[code_raw] = {'price': p, 'chg_pct': round(chg, 2)}
    except: pass
    return prices

def _fetch_sina(codes):
    prices = {}
    all_codes = [f'sh{c}' if c.startswith('5') else f'sz{c}' for c in codes]
    for i in range(0, len(all_codes), 50):
        batch = all_codes[i:i+50]
        try:
            url = f'http://hq.sinajs.cn/list={",".join(batch)}'
            req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
            resp = urllib.request.urlopen(req, timeout=10)
            text = resp.read().decode('gbk', errors='replace')
            for line in text.strip().split('\n'):
                m = re.match(r'var hq_str_(\w+)="(.+)"', line)
                if not m: continue
                code_raw = m.group(1)[2:]
                fields = m.group(2).split(',')
                if len(fields) < 4: continue
                try:
                    p = float(fields[3]); prev = float(fields[2])
                    if p > 0 and prev > 0:
                        prices[code_raw] = {'price': p, 'chg_pct': round((p-prev)/prev*100, 2)}
                except: continue
        except: pass
    return prices

# ============ 动量计算 ============
def score_175(closes):
    use = np.array(closes[-LB:], dtype=float)
    if len(use) < 5 or np.any(use <= 0): return -999, 0, 0
    y = np.log(use); x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    W = np.diag(weights); X = np.column_stack([np.ones(len(x)), x])
    XtW = X.T @ W
    try: beta = np.linalg.solve(XtW @ X, XtW @ y)
    except np.linalg.LinAlgError: return -999, 0, 0
    slope = beta[1]
    ann_ret = math.exp(slope * 250) - 1
    fitted = beta[0] + slope * x
    ss_res = np.sum(weights * (y - fitted) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return ann_ret * r2, ann_ret, r2

def score_short(closes):
    """10日短期动量: (exp(slope*250)-1) × R²"""
    use = np.array(closes[-(SLB+1):], dtype=float)
    if len(use) < 5: return 0
    y = np.log(use); x = np.arange(len(y))
    slope = np.polyfit(x, y, 1)[0]
    ann = math.exp(slope * 250) - 1
    fitted = slope * x + np.polyfit(x, y, 1)[1]
    res = y - fitted
    r2 = 1 - np.sum(res**2) / max(np.sum((y - np.mean(y))**2), 1e-12)
    return ann * r2

def check_trend(prices):
    if len(prices) < 15: return False
    ma10, ma5 = np.mean(prices[-10:]), np.mean(prices[-5:])
    return prices[-1] > ma10 and ma5 > ma10

def check_short_momentum(prices):
    if len(prices) < SLB + 2: return True
    ret = prices[-1] / prices[-(SLB+1)] - 1
    return (1+ret)**(250/SLB) - 1 >= 0

def check_3day_loss(prices):
    if len(prices) < 5: return True
    for i in [-1, -2, -3]:
        if abs(i) <= len(prices):
            if prices[i] / prices[i-1] < 0.97: return False
    return True

def get_sector(code):
    if code in OVERSEAS_SET: return '海外'
    if code in COMMODITY_SET: return '商品'
    return 'A股'

# ============ 行情判断 ============
def check_regime(data, rt_prices):
    a_below, a_weak, a_recover = 0, 0, 0
    o_below, o_weak, o_recover = 0, 0, 0
    need = 15
    for code in A_PROXIES:
        if code not in data: continue
        df = data[code]; closes = df['close'].values
        if len(closes) < need: continue
        cur = rt_prices.get(code, {}).get('price', 0) if isinstance(rt_prices.get(code), dict) else rt_prices.get(code, closes[-1])
        if cur <= 0: cur = closes[-1]
        ma10, ma5 = np.mean(closes[-10:]), np.mean(closes[-5:])
        ma10_prev, ma5_prev = np.mean(closes[-11:-1]), np.mean(closes[-6:-1])
        if cur < ma10: a_below += 1
        if ma5 < ma10: a_weak += 1
        if ma5 > ma5_prev and ma10 > ma10_prev: a_recover += 1
    for code in O_PROXIES:
        if code not in data: continue
        df = data[code]; closes = df['close'].values
        if len(closes) < need: continue
        cur = rt_prices.get(code, {}).get('price', 0) if isinstance(rt_prices.get(code), dict) else rt_prices.get(code, closes[-1])
        if cur <= 0: cur = closes[-1]
        ma10, ma5 = np.mean(closes[-10:]), np.mean(closes[-5:])
        ma10_prev, ma5_prev = np.mean(closes[-11:-1]), np.mean(closes[-6:-1])
        if cur < ma10: o_below += 1
        if ma5 < ma10: o_weak += 1
        if ma5 > ma5_prev and ma10 > ma10_prev: o_recover += 1
    return a_below >= 3 or a_weak >= 3, o_below >= 2 or o_weak >= 2, {
        'a_below': a_below, 'a_weak': a_weak, 'a_recover': a_recover,
        'o_below': o_below, 'o_weak': o_weak, 'o_recover': o_recover}

def get_active_pool(is_a_weak, is_o_weak):
    if is_a_weak and is_o_weak: return list(COMMODITY_SET), '双弱→仅商品(7只)'
    elif is_a_weak: return list(OVERSEAS_SET | COMMODITY_SET), 'A股弱→海外+商品(26只)'
    elif is_o_weak: return list(DOMESTIC_SET | COMMODITY_SET), '海外弱→A股+商品(38只)'
    else: return list(ALL_POOL.keys()), '双正常→全池(57只)'

# ============ 回测绩效 ============
def get_backtest_stats():
    """从最近一次回测结果获取绩效"""
    bf = SCRIPT_DIR / 'backtest' / 'results_compare'
    jsons = sorted(bf.glob('trades_175_orig_*.json'), reverse=True) if bf.exists() else []
    if not jsons: return None
    with open(jsons[0]) as f: trades = json.load(f)
    sells = [t for t in trades if t.get('action') == 'SELL']
    if not sells: return None
    wr = sum(1 for t in sells if t.get('pnl_pct', 0) > 0) / len(sells) * 100
    return {'trades': len(trades), 'sells': len(sells), 'win_rate': wr}

# ============ 历史排名追踪 ============
HISTORY_FILE = OUT_DIR / '175_ranking_history.json'

def load_history():
    if HISTORY_FILE.exists():
        try: return json.loads(HISTORY_FILE.read_text())
        except: pass
    return {}

def save_history(ranked):
    data = {'date': LATEST_DATE, 'rankings': []}
    for i, r in enumerate(ranked[:15]):
        data['rankings'].append({'rank': i+1, 'code': r['code'], 'score': r['score']})
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False))

def get_prev_rank(code):
    hist = load_history()
    for r in hist.get('rankings', []):
        if r['code'] == code: return r['rank']
    return None

def fmt_rank_change(prev, curr):
    if prev is None: return '-'
    if curr < prev: return f'↑{prev-curr}'
    elif curr > prev: return f'↓{curr-prev}'
    return '-'

def fmt_change_pct(v):
    if v is None or v == 0: return '0.00%'
    return f'+{v:.2f}%' if v > 0 else f'{v:.2f}%'

# ============ 主流程 ============
print(f'🌍 七星175 V3.15 — {NOW_STR}')
print('='*50)

# 加载数据
all_data = {}
for code in ALL_POOL:
    fp = DATA_DIR / f'{code}.csv'
    if not fp.exists(): continue
    df = pd.read_csv(fp); df.columns = [c.lower() for c in df.columns]
    df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
    if len(df) > 30: all_data[code] = df
print(f'[数据] {len(all_data)}/{len(ALL_POOL)} ETFs')

# 实时行情
print('[RT] 获取实时行情...')
rt = _fetch_westock(list(ALL_POOL.keys())); rt_src = 'WeStock'
if not rt: rt = _fetch_sina(list(ALL_POOL.keys())); rt_src = '新浪'
rt_valid = len(rt) > 0
print(f'[RT] {rt_src}: {len(rt)} quotes {"✅" if rt_valid else "❌"}')

# 收盘价
last_prices = {c: float(all_data[c]['close'].iloc[-1]) for c in all_data}

# 行情判断
is_a_weak, is_o_weak, regime_detail = check_regime(all_data, rt)
active_pool, pool_label = get_active_pool(is_a_weak, is_o_weak)
a_status = '🔴走弱' if is_a_weak else '🟢正常'
o_status = '🔴走弱' if is_o_weak else '🟢正常'
print(f'[Regime] A股{a_status} ({regime_detail["a_below"]}/6破MA10) | 海外{o_status} ({regime_detail["o_below"]}/4破MA10) → {pool_label}')

# 排名
print(f'[Rank] 计算动量...')
ranked = []
for code in active_pool:
    if code not in all_data: continue
    closes = all_data[code]['close'].values
    if len(closes) < LB + 20 or closes[-LB:].min() <= 0: continue
    s, ann, r2 = score_175(closes[-LB:])
    if s <= 0 or r2 < 0.35: continue
    if not check_trend(closes[-LB:]): continue
    if not check_short_momentum(closes): continue
    if not check_3day_loss(closes): continue

    cp = rt.get(code, {}).get('price', 0) if isinstance(rt.get(code), dict) else (rt.get(code, 0) or 0)
    if cp <= 0: cp = last_prices.get(code, 0)
    chg = rt.get(code, {}).get('chg_pct', 0) if isinstance(rt.get(code), dict) else 0
    if chg == 0 and cp > 0 and len(closes) >= 2:
        chg = (cp - closes[-2]) / closes[-2] * 100

    short_s = score_short(closes)
    name = ALL_POOL.get(code, code)
    sector = get_sector(code)

    ranked.append({'code': code, 'name': name, 'sector': sector,
                   'score': s, 'ann': ann*100, 'r2': r2,
                   'short_score': short_s, 'long_score': s,
                   'price': cp, 'chg_pct': round(chg, 2),
                   'premium_pct': None, 'filtered': False})

ranked.sort(key=lambda x: x['score'], reverse=True)
print(f'[Rank] 有效: {len(ranked)}只 (通过全部过滤器)')

# 历史排名
prev_ranks = {r['code']: r['rank'] for r in load_history().get('rankings', [])}
save_history(ranked)

# 构建展示排名 (对齐172: 前10有效, 超出的过滤标记)
top10_all = ranked[:10]
valid_top10 = [r for r in top10_all if not r['filtered']]
filtered_top10 = [r for r in top10_all if r['filtered']]
rest_valid = [r for r in ranked[10:] if not r['filtered']]
need = 10 - len(valid_top10)
valid_top10.extend(rest_valid[:need])

for i, r in enumerate(valid_top10):
    r['display_rank'] = i + 1
    prev = prev_ranks.get(r['code'])
    r['rchange'] = fmt_rank_change(prev, i + 1)
for i, r in enumerate(filtered_top10):
    r['display_rank'] = 11 + i
    r['rchange'] = '过滤'

display = valid_top10 + filtered_top10

# 回测绩效
perf = get_backtest_stats()

# ============ HTML (对齐172版式) ============

# 策略配置栏
config_html = f"""
<div style="background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:12px;font-size:13px;">
    <b>策略:</b> 七星175 V3.15 (双风险四格池) | <b>ETF池:</b> 57只(海外19+商品7+A股31) | <b>周期:</b> 25日 | <b>佣金:</b> 0.05%
    <br><b>得分:</b> (exp(slope×250)−1)×R² 加权 | <b>过滤:</b> R²≥0.35+趋势结构+短期动量+近3日跌幅+溢价率>20%
</div>"""

# 行情状态
regime_html = f"""
<div style="background:#fff;padding:10px 15px;border-radius:8px;margin-bottom:12px;font-size:12px;">
    📊 <b>A股:</b> {a_status}({regime_detail['a_below']}/6破MA10, {regime_detail['a_weak']}/6MA5弱)
    | 🌐 <b>海外:</b> {o_status}({regime_detail['o_below']}/4破MA10, {regime_detail['o_weak']}/4MA5弱)
    | <b>池:</b> {pool_label} | <b>行情:</b> {rt_src} L1 ({len(rt)}只)
</div>"""

# 排名表
rank_rows = ""
for r in display[:12]:
    is_hold = r.get('is_holding', False)
    bg = '#FEF9E7' if is_hold else ('#FFF' if r['display_rank'] % 2 == 0 else '#F8F9FA')
    sc_c = '#28A745' if r['score'] > 0 else '#DC3545'
    chg = fmt_change_pct(r['chg_pct'])
    chg_c = '#DC3545' if r['chg_pct'] < -0.005 else ('#28A745' if r['chg_pct'] > 0.005 else '#888')
    rc = r.get('rchange', '-')
    rc_c = '#DC3545' if ('保护' in rc or '过滤' in rc) else ('#28A745' if '↑' in rc else ('#DC3545' if '↓' in rc else '#888'))
    prem_val = r.get('premium_pct')
    prem_str = f'{prem_val:.2f}%' if prem_val is not None else '-'
    prem_c = '#888'
    sec_tag = {'海外': '🌐', '商品': '🥇', 'A股': '📈'}.get(r['sector'], '')
    rank_rows += f"""<tr style="background:{bg};white-space:nowrap;">
        <td style="padding:4px 6px;text-align:center;font-weight:bold;">{r['display_rank']}</td>
        <td style="padding:4px 6px;">{sec_tag} {r['name']}</td>
        <td style="padding:4px 6px;text-align:center;color:#888;font-size:11px;">{r['code']}</td>
        <td style="padding:4px 6px;text-align:right;font-weight:bold;color:{sc_c};">{r['score']:.4f}</td>
        <td style="padding:4px 6px;text-align:right;">{r['ann']:+.1f}%</td>
        <td style="padding:4px 6px;text-align:right;">{r['r2']:.3f}</td>
        <td style="padding:4px 6px;text-align:right;">{r['price']:.4f}</td>
        <td style="padding:4px 6px;text-align:right;color:{chg_c};font-weight:bold;">{chg}</td>
        <td style="padding:4px 6px;text-align:right;color:{prem_c};font-weight:bold;">{prem_str}</td>
        <td style="padding:4px 6px;text-align:center;color:{rc_c};font-weight:bold;font-size:11px;">{rc}</td></tr>"""

# 指数MA明细
ma_rows = ""
for code in A_PROXIES:
    if code not in all_data: continue
    closes = all_data[code]['close'].values
    cp = rt.get(code, {}).get('price', closes[-1]) if isinstance(rt.get(code), dict) else (rt.get(code, closes[-1]) or closes[-1])
    ma10, ma5 = np.mean(closes[-10:]), np.mean(closes[-5:])
    status = '⬇破MA10' if cp < ma10 else '⬆线上'
    bg = '#FFF3CD' if cp < ma10 else '#fff'
    ma_rows += f"""<tr style="background:{bg}"><td>{A_PROXIES[code]}</td><td style="text-align:right;">{cp:.4f}</td><td style="text-align:right;">{ma5:.4f}</td><td style="text-align:right;">{ma10:.4f}</td><td style="text-align:right;">{'MA5<MA10 ⚠' if ma5 < ma10 else 'MA5↑'}</td><td>{status}</td></tr>"""

html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>七星175 V3.15 盘后报告</title></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:920px;margin:0 auto;padding:20px;background:#f8f9fa;">

<div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:22px;color:#1F4E79;margin:0 0 5px 0;">🌍 七星175 V3.15 · 盘后报告</h1>
    <p style="font-size:12px;color:#888;margin:0;">{NOW_STR} (Asia/Shanghai) | 数据截止: {LATEST_DATE}</p>
</div>

{config_html}
{regime_html}

<!-- 指数MA状态 -->
<div style="background:#fff;padding:12px 15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:14px;color:#1F4E79;margin:0 0 8px 0;">📊 A股指数MA状态</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 8px;text-align:left;">指数</th>
            <th nowrap style="padding:6px 8px;text-align:right;">现价</th>
            <th nowrap style="padding:6px 8px;text-align:right;">MA5</th>
            <th nowrap style="padding:6px 8px;text-align:right;">MA10</th>
            <th nowrap style="padding:6px 8px;text-align:right;">MA5趋势</th>
            <th nowrap style="padding:6px 8px;text-align:center;">状态</th></tr>
        {ma_rows}
    </table>
</div>

<!-- 排名Top10 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">📊 ETF动量排名 Top10 ({pool_label.split('→')[1]})</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 6px;text-align:center;">排名</th>
            <th nowrap style="padding:6px 6px;text-align:left;">名称</th>
            <th nowrap style="padding:6px 6px;text-align:center;">代码</th>
            <th nowrap style="padding:6px 6px;text-align:right;">综合</th>
            <th nowrap style="padding:6px 6px;text-align:right;">年化</th>
            <th nowrap style="padding:6px 6px;text-align:right;">R²</th>
            <th nowrap style="padding:6px 6px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 6px;text-align:right;">涨跌幅</th>
            <th nowrap style="padding:6px 6px;text-align:right;">溢价率</th>
            <th nowrap style="padding:6px 6px;text-align:center;">变动</th></tr>
        {rank_rows}
    </table>
</div>

<!-- 策略说明 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:14px;color:#1F4E79;margin:0 0 8px 0;">📋 过滤规则</h3>
    <table style="font-size:12px;width:100%;">
    <tr><td style="width:180px"><b>R² ≥ 0.35</b></td><td>排除拟合度不足的ETF</td></tr>
    <tr><td><b>趋势结构</b></td><td>现价 > MA10 且 MA5 > MA10</td></tr>
    <tr><td><b>短期动量</b></td><td>10日年化 ≥ 0</td></tr>
    <tr><td><b>近3日跌幅</b></td><td>无单日 > 3%</td></tr>
    <tr><td><b>溢价率 > 20%</b></td><td>排除高溢价ETF（需NAV数据）</td></tr>
    <tr style="color:#28A745"><td><b>🆕 盈利仓分钟豁免</b></td><td>浮盈≥10%时分钟级回撤不强制卖</td></tr>
    <tr style="color:#28A745"><td><b>🆕 盈利仓昨收豁免</b></td><td>浮盈≥10%时仅看日内回撤，不用昨收跳空</td></tr>
    <tr style="color:#28A745"><td><b>🆕 QDII轮动修复</b></td><td>同日轮动卖海外后可买入另一只QDII</td></tr>
    </table>
</div>
"""

# 回测绩效 (从交易记录JSON加载)
TRADES_JSON_PATH = OUT_DIR / '七星175_交易记录.json'
backtest_stats = None
recent_trades_data = []
if TRADES_JSON_PATH.exists():
    try:
        with open(TRADES_JSON_PATH, 'r', encoding='utf-8') as f:
            bt_data = json.load(f)
        backtest_stats = bt_data.get('stats', {})
        all_bt_trades = bt_data.get('trades', [])
        # 取最近20笔 (倒序: 最新在前)
        recent_trades_data = all_bt_trades[-20:][::-1]
    except Exception as e:
        print(f'  [交易记录] 加载失败: {e}')

# 回测绩效卡片
if backtest_stats:
    html += f"""
<div style="background:#fff;padding:12px 15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:14px;color:#1F4E79;margin:0 0 8px 0;">📈 回测绩效 (2023.1 ~ 今)</h3>
    <table style="font-size:12px;width:100%;">
    <tr>
        <td style="width:25%"><b>累计收益</b><br><span style="color:#28A745;font-size:16px;font-weight:bold;">{backtest_stats.get('total_return',0):+.1f}%</span></td>
        <td style="width:25%"><b>年化收益</b><br><span style="color:#28A745;font-size:14px;">{backtest_stats.get('annual_return',0):.1f}%</span></td>
        <td style="width:25%"><b>最大回撤</b><br><span style="color:#DC3545;font-size:14px;">{backtest_stats.get('max_drawdown',0):.1f}%</span></td>
        <td style="width:25%"><b>夏普比率</b><br><span style="color:#1F4E79;font-size:14px;">{backtest_stats.get('sharpe',0):.2f}</span></td>
    </tr>
    <tr>
        <td style="width:25%;padding-top:8px;"><b>总交易</b><br><span style="color:#333;font-size:14px;">{backtest_stats.get('total_trades',0)}笔</span></td>
        <td style="width:25%;padding-top:8px;"><b>胜率</b><br><span style="color:#28A745;font-size:14px;">{backtest_stats.get('win_rate',0):.1f}%</span></td>
        <td></td><td></td>
    </tr>
    </table>
</div>"""

# 最近20条交易记录 (版式对齐172)
if recent_trades_data:
    trade_rows_html = ""
    for t in recent_trades_data:
        direction = t.get('action', '')
        dir_label = '买入' if direction == 'BUY' else '卖出'
        bg = '#E2EFDA' if dir_label == '买入' else '#FCE4D6'
        pnl = t.get('pnl_pct', 0)
        pnl_str = f'+{pnl:.2f}%' if pnl > 0 else (f'{pnl:.2f}%' if pnl < 0 else '-')
        pnl_c = '#28A745' if pnl > 0 else ('#DC3545' if pnl < 0 else '#888')

        # ETF名称映射
        etf_name = ALL_POOL.get(t.get('code', ''), t.get('code', ''))

        trade_rows_html += f"""
        <tr style="background:{bg};white-space:nowrap;">
            <td style="padding:4px 8px;">{t.get('date','')}</td>
            <td style="padding:4px 8px;font-weight:bold;">{dir_label}</td>
            <td style="padding:4px 8px;">{etf_name}</td>
            <td style="padding:4px 8px;color:#888;font-size:11px;">{t.get('code','')}</td>
            <td style="padding:4px 8px;text-align:right;">{t.get('price',0):.3f}</td>
            <td style="padding:4px 8px;text-align:right;">{t.get('shares','')}</td>
            <td style="padding:4px 8px;font-size:11px;color:#555;">{t.get('reason','')}</td>
            <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pnl_c};">{pnl_str}</td>
        </tr>"""

    html += f"""
<!-- 最近20条交易记录 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">📋 最近20条交易记录</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 8px;">日期</th>
            <th nowrap style="padding:6px 8px;">方向</th>
            <th nowrap style="padding:6px 8px;">ETF</th>
            <th nowrap style="padding:6px 8px;">代码</th>
            <th nowrap style="padding:6px 8px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 8px;text-align:right;">数量</th>
            <th nowrap style="padding:6px 8px;text-align:left;">理由</th>
            <th nowrap style="padding:6px 8px;text-align:right;">盈亏</th>
        </tr>
        {trade_rows_html}
    </table>
</div>"""

html += f"""
<p style="text-align:center;color:#999;font-size:11px;margin-top:20px;">七星175 V3.15 · Blakever Trade · {NOW_STR} · 本报告仅供研究参考</p>
</body></html>
"""

fname = f'七星175报告_{NOW_FILE}.html'
fpath = OUT_DIR / fname
fpath.write_text(html, encoding='utf-8')
print(f'\n[报告] {fpath}')

# ============ 邮件 ============
msg = MIMEMultipart("mixed")
msg["Subject"] = f"[七星175 V3.15] 盘后报告 - {NOW_STR}"
msg["From"] = "848786642@qq.com"
msg["To"] = "848786642@qq.com"
msg.attach(MIMEText(html, "html", "utf-8"))

try:
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
        s.login("848786642@qq.com", "ljbtvacrctjobfed")
        s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
    print(f'[邮件] ✅ 已发送到 848786642@qq.com')
except Exception as e:
    print(f'[邮件] ❌ 发送失败: {e}')

print(f'\nTop5:')
for i, r in enumerate(ranked[:5]):
    print(f'  {i+1}. {r["code"]} {r["name"]:15s} 得分{r["score"]:.4f}  年化{r["ann"]:+.1f}%  R²={r["r2"]:.3f}  ¥{r["price"]:.4f}')

print(f'\n[完成] {len(ranked)}只通过全部过滤器')
