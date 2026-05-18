#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星三马ETF轮动策略 - 盘中实时监控（每30分钟）
================================================
交易时间 9:30-11:30 / 13:00-15:00 每30分钟执行一次：
  1. 获取25只ETF实时行情 + K线数据
  2. 计算动量综合得分（短期25日×100% + 长期250日×50%）
  3. 生成排名列表（综合得分、短期、长期、实时价格）
  4. 止损检测（硬止损8% + 盈利保护5%）
  5. 与上次排名对比，标注名次变动
  6. 发送HTML邮件报告

数据源：腾讯行情API（tencent_api.mjs）
状态文件：qixing_sanma_intraday_state.json
"""

import os, sys, math, json, subprocess, time, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

# ================================================================
# 配置
# ================================================================
TENCENT_API = '/home/node/.openclaw/workspace/blakever_trade/westock-data/scripts/tencent_api.mjs'
STATE_FILE = '/home/node/.openclaw/workspace/blakever_trade/strategy_arena/qixing_sanma_intraday_state.json'
LOG_DIR = '/home/node/.openclaw/workspace/blakever_trade/strategy_arena/qixing_sanma_intraday_logs'

EMAIL_TO = '848786642@qq.com'
EMAIL_AUTH = 'ljbtvacrctjobfed'
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465

SHORT_LOOKBACK = 25
LONG_LOOKBACK = 250
STOP_LOSS_PCT = 0.08        # 硬止损：从参考价跌8%触发
PROFIT_PROTECT_PCT = 0.05   # 盈利保护：从近20日高点回撤5%触发
HIGH20_LOOKBACK = 20        # 近20日高点窗口

# 三马七星ETF池（25只）
ETF_MAP = {
    'sh518880': ('518880_XSHG', '黄金ETF'),
    'sz159980': ('159980_XSHE', '有色ETF'),
    'sz159985': ('159985_XSHE', '豆粕ETF'),
    'sh501018': ('501018_XSHG', '南方原油LOF'),
    'sz161226': ('161226_XSHE', '国投白银LOF'),
    'sz159981': ('159981_XSHE', '能源化工ETF'),
    'sh513100': ('513100_XSHG', '纳指ETF'),
    'sh513500': ('513500_XSHG', '标普500ETF'),
    'sh513400': ('513400_XSHG', '道琼斯ETF'),
    'sh510300': ('510300_XSHG', '沪深300ETF'),
    'sh510500': ('510500_XSHG', '中证500ETF'),
    'sh510050': ('510050_XSHG', '上证50ETF'),
    'sh510210': ('510210_XSHG', '上证指数ETF'),
    'sz159915': ('159915_XSHE', '创业板ETF'),
    'sh588080': ('588080_XSHG', '科创50ETF'),
    'sh512100': ('512100_XSHG', '中证1000ETF'),
    'sh563360': ('563360_XSHG', 'A500ETF'),
    'sh512890': ('512890_XSHG', '红利低波ETF'),
    'sz159967': ('159967_XSHE', '创成长ETF'),
    'sh512040': ('512040_XSHG', '价值100ETF'),
    'sz159201': ('159201_XSHE', '自由现金流ETF'),
    'sh511380': ('511380_XSHG', '可转债ETF'),
    'sh511010': ('511010_XSHG', '国债ETF'),
    'sh511220': ('511220_XSHG', '城投债ETF'),
    'sh516080': ('516080_XSHG', '创新药ETF'),
    'sh511880': ('511880_XSHG', '银华日利ETF'),
}

# ================================================================
# 交易时间判断
# ================================================================
def is_trading_time():
    """判断当前是否在A股交易时间（9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False, '周末休市'
    t = now.strftime('%H:%M')
    if '09:30' <= t <= '11:30':
        return True, '上午盘'
    if '13:00' <= t <= '15:00':
        return True, '下午盘'
    if t < '09:30':
        return False, '盘前'
    if '11:30' < t < '13:00':
        return False, '午休'
    return False, '盘后'

# ================================================================
# 数据获取
# ================================================================
def get_kline(tcode, limit=260):
    """通过腾讯API获取K线数据"""
    result = subprocess.run(
        ['node', TENCENT_API, 'kline', tcode, 'day', str(limit), 'qfq'],
        capture_output=True, text=True, timeout=20
    )
    try:
        j = json.loads(result.stdout)
        if j['success']:
            return j['data']['nodes']
        return []
    except:
        return []

def get_quote(tcode):
    """获取实时行情"""
    result = subprocess.run(
        ['node', TENCENT_API, 'quote', tcode],
        capture_output=True, text=True, timeout=15
    )
    try:
        j = json.loads(result.stdout)
        if j['success']:
            return j['data'].get(tcode, {})
        return {}
    except:
        return {}

# ================================================================
# 评分计算（与 qixing_daily_email.py 完全一致）
# ================================================================
def weighted_reg(prices_list):
    """纯Python加权线性回归：返回(年化收益率, R², 动量得分)"""
    n = len(prices_list)
    if n < 5:
        return 0, 0, 0
    y = [math.log(max(p, 0.001)) for p in prices_list]
    x = list(range(n))
    w = [1 + i * (1 / (n - 1)) for i in range(n)] if n > 1 else [1] * n
    w_sum = sum(w)
    wx = sum(w[i] * x[i] for i in range(n))
    wy = sum(w[i] * y[i] for i in range(n))
    xm, ym = wx / w_sum, wy / w_sum
    num = sum(w[i] * (x[i] - xm) * (y[i] - ym) for i in range(n))
    den = sum(w[i] * (x[i] - xm) ** 2 for i in range(n))
    slope = num / den if abs(den) > 1e-10 else 0
    ss_tot = sum(w[i] * (y[i] - ym) ** 2 for i in range(n))
    ss_res = sum(w[i] * (y[i] - (slope * (x[i] - xm) + ym)) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0
    ann_return = math.exp(slope * 252) - 1
    return ann_return, r2, ann_return * r2

def score_etf(prices_list, short_n=25, long_n=250):
    """计算ETF动量得分（三马权重：短期×1 + 长期×0.5）"""
    if len(prices_list) < 5:
        return None, None, None
    sp = prices_list[-short_n:]
    lp = prices_list[-long_n:]
    ann_s, r2_s, score_s = weighted_reg(sp)
    ann_l, r2_l, score_l = weighted_reg(lp)
    # 近4日急跌过滤
    if len(sp) >= 4:
        for i in range(len(sp) - 1):
            if sp[i] > 0 and sp[i + 1] / sp[i] < 0.95:
                score_s = 0
                break
    return score_s, score_l * 0.5, score_s + score_l * 0.5

# ================================================================
# 止损检测
# ================================================================
def check_stop_loss(price, prev_close, high20):
    """
    检测止损状态
    硬止损：当前价相对参考价（前收）跌幅 >= 8%
    盈利保护：当前价相对近20日高点回撤 >= 5%
    返回: (stop_level: None|'HARD_STOP'|'PROFIT_PROTECT', drawdown_pct, ref_price)
    """
    # 硬止损：以昨日收盘为代理买入价
    if prev_close > 0:
        dd_hard = (price / prev_close - 1) * 100
        if dd_hard <= -STOP_LOSS_PCT * 100:
            return 'HARD_STOP', dd_hard, prev_close

    # 盈利保护：以近20日高点为参考
    if high20 and high20 > 0:
        dd_pp = (price / high20 - 1) * 100
        if dd_pp <= -PROFIT_PROTECT_PCT * 100:
            return 'PROFIT_PROTECT', dd_pp, high20

    return None, 0, 0

# ================================================================
# 状态管理（排名变动追踪 + 20日高点）
# ================================================================
def load_state():
    """加载上一次状态（含20日高点）"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return None

def save_state(rankings, check_time, high20_data):
    """保存当前排名状态（含20日高点）"""
    state = {
        'check_time': check_time,
        'date': check_time[:10],
        'rankings': {r['code']: r['rank'] for r in rankings},
        'scores': {r['code']: r['total_score'] for r in rankings},
        'high20': high20_data,  # {code: high20_price}
    }
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return state

def compute_rank_changes(current_rankings, prev_state):
    """计算排名变动"""
    if not prev_state or not prev_state.get('rankings'):
        return {}
    changes = {}
    prev_ranks = prev_state['rankings']
    prev_date = prev_state.get('date', '')
    cur_date = datetime.now().strftime('%Y-%m-%d')
    if prev_date != cur_date:
        return {}  # 跨天不对比
    for r in current_rankings:
        code = r['code']
        cur_rank = r['rank']
        prev_rank = prev_ranks.get(code)
        if prev_rank is not None and prev_rank != cur_rank:
            diff = prev_rank - cur_rank
            changes[code] = diff
    return changes

# ================================================================
# HTML邮件生成
# ================================================================
def generate_html(results, rank_changes, stop_warnings, check_time_str, session_label):
    """生成盘中监控HTML邮件"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 排名变动摘要
    change_lines = []
    if rank_changes:
        sorted_changes = sorted(rank_changes.items(), key=lambda x: -x[1])
        for code, diff in sorted_changes:
            name = next((r['name'] for r in results if r['code'] == code), code)
            if diff > 0:
                change_lines.append(f'<span style="color:#10b981">🔺 {name} 上升 {diff} 位</span>')
            else:
                change_lines.append(f'<span style="color:#ef4444">🔻 {name} 下降 {abs(diff)} 位</span>')
    change_html = '<br>\n'.join(change_lines) if change_lines else '<span style="color:#6b7280">无变动</span>'

    # 止损警示区块
    stop_html = ''
    if stop_warnings:
        warn_rows = ''
        for r in stop_warnings:
            level = r['stop_level']
            color = '#ef4444' if level == 'HARD_STOP' else '#f97316'
            label = '🔴 硬止损' if level == 'HARD_STOP' else '🟠 盈利保护'
            dd = r['drawdown_pct']
            ref = r.get('stop_ref_price', 0)
            ref_str = f'{ref:.3f}' if ref else '-'
            warn_rows += f'''      <tr>
        <td style="text-align:left"><span style="font-weight:700;color:{color}">{label}</span></td>
        <td style="text-align:left"><span style="color:#93c5fd;font-weight:600;font-family:monospace">{r['tcode']}</span> <span style="color:#f1f5f9">{r['name']}</span></td>
        <td style="color:{color};font-weight:700;text-align:center">{dd:+.2f}%</td>
        <td style="color:#94a3b8;text-align:center">{ref_str}</td>
        <td style="color:#e5e7eb;text-align:center">{r['realtime_price']:.3f}</td>
      </tr>
'''
        stop_html = f'''<div style="margin-top:16px;padding:12px 16px;background:#1e293b;border-radius:8px;border-left:4px solid #ef4444;">
  <div style="font-size:13px;color:#f87171;font-weight:700;margin-bottom:10px;">⚠️ 止损警示（{len(stop_warnings)}只ETF触发条件）</div>
  <table style="width:100%;border-collapse:collapse;font-size:12px;">
    <tr style="color:#94a3b8;font-size:11px;">
      <th style="text-align:left;padding:4px 6px;">类型</th>
      <th style="text-align:left;padding:4px 6px;">ETF</th>
      <th style="text-align:center;padding:4px 6px;">当前回撤</th>
      <th style="text-align:center;padding:4px 6px;">参考价</th>
      <th style="text-align:center;padding:4px 6px;">现价</th>
    </tr>
    {warn_rows}
  </table>
</div>
'''

    # 表格行
    rows_html = ''
    for r in results:
        code = r['code']
        name = r['name']
        ts = r['total_score']
        ss = r['short_score']
        ls = r['long_score']
        price = r['realtime_price']
        chg = r.get('changePct', 0)
        dd = r.get('drawdown_pct', 0)
        stop_level = r.get('stop_level')

        score_color = '#10b981' if ts > 0.1 else ('#f59e0b' if ts > 0 else '#ef4444')
        chg_color = '#10b981' if chg >= 0 else '#ef4444'
        chg_str = f'{chg:+.2f}%'

        # 排名变动
        diff = rank_changes.get(code, 0)
        if diff > 0:
            rank_change_html = f'<span style="color:#10b981;font-size:11px">🔺+{diff}</span>'
        elif diff < 0:
            rank_change_html = f'<span style="color:#ef4444;font-size:11px">🔻{diff}</span>'
        else:
            rank_change_html = '<span style="color:#475569;font-size:11px">—</span>'

        # 回撤/止损列
        if stop_level == 'HARD_STOP':
            dd_html = f'<span style="color:#ef4444;font-weight:700;font-size:11px">🔴{dd:+.1f}%</span>'
        elif stop_level == 'PROFIT_PROTECT':
            dd_html = f'<span style="color:#f97316;font-weight:700;font-size:11px">🟠{dd:+.1f}%</span>'
        elif dd < -3:
            dd_html = f'<span style="color:#fb923c;font-size:11px">⚠️{dd:+.1f}%</span>'
        else:
            dd_html = f'<span style="color:#475569;font-size:11px">{dd:+.1f}%</span>'

        rows_html += f'''    <tr>
      <td style="color:#94a3b8;font-weight:600;width:28px">{r['rank']}</td>
      <td style="text-align:left"><span style="color:#93c5fd;font-weight:600;font-family:monospace;font-size:11px">{r['tcode']}</span> <span style="color:#f1f5f9">{name}</span></td>
      <td style="font-weight:700;font-size:13px;color:{score_color}">{ts:.4f}</td>
      <td style="color:#94a3b8">{ss:.4f}</td>
      <td style="color:#94a3b8">{ls:.4f}</td>
      <td style="color:#e5e7eb">{price:.3f} <span style="color:{chg_color};font-size:11px">{chg_str}</span></td>
      <td>{dd_html}</td>
      <td>{rank_change_html}</td>
    </tr>
'''

    top3 = results[:3]
    top_summary = ' | '.join([
        f'🥇{r["name"]}' if i==0 else (f'🥈{r["name"]}' if i==1 else f'🥉{r["name"]}')
        for i, r in enumerate(top3)
    ])

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{ margin:0; padding:0; background:#0f172a; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; }}
.container {{ max-width:760px; margin:0 auto; padding:16px; }}
.header {{ text-align:center; padding:20px 0 12px; border-bottom:2px solid #1e293b; }}
.header h1 {{ color:#f8fafc; margin:0 0 4px; font-size:20px; }}
.header .sub {{ color:#94a3b8; margin:0; font-size:12px; }}
.badge {{ display:inline-block; background:#1e40af; color:#93c5fd; font-size:11px; padding:2px 8px; border-radius:10px; margin-left:6px; }}
.top-bar {{ background:#1e293b; border-radius:8px; padding:12px 16px; margin-top:16px; text-align:center; }}
.top-bar .top3 {{ font-size:14px; color:#e2e8f0; font-weight:600; }}
.change-section {{ margin-top:16px; padding:12px 16px; background:#1e293b; border-radius:8px; }}
.change-section .title {{ font-size:13px; color:#94a3b8; font-weight:600; margin-bottom:8px; }}
.change-section .content {{ font-size:13px; line-height:1.8; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:16px; }}
th {{ padding:7px 5px; text-align:center; color:#94a3b8; font-weight:600; border-bottom:1px solid #1e293b; font-size:11px; white-space:nowrap; }}
td {{ padding:6px 5px; text-align:center; border-bottom:1px solid #1e293b; }}
.note {{ margin-top:16px; padding:10px 14px; background:#1e293b; border-radius:8px; font-size:11px; color:#94a3b8; line-height:1.7; }}
.note strong {{ color:#e2e8f0; }}
.footer {{ text-align:center; padding:12px 0 6px; color:#475569; font-size:10px; border-top:1px solid #1e293b; margin-top:16px; }}
</style></head><body>
<div class="container">

<div class="header">
  <h1>📊 七星三马 ETF 盘中监控<span class="badge">{session_label}</span></h1>
  <p class="sub">{now_str} | 每30分钟更新 | 动量评分实时排名</p>
</div>

<div class="top-bar">
  <div class="top3">{top_summary}</div>
</div>

<div class="change-section">
  <div class="title">📋 排名变动（vs 上次检查）</div>
  <div class="content">{change_html}</div>
</div>

{stop_html}

<table>
  <tr><th></th><th style="text-align:left">ETF</th><th>综合得分</th><th>短期25日</th><th>长期250日</th><th>实时价格</th><th>回撤</th><th>变动</th></tr>
{rows_html}
</table>

<div class="note">
  <strong>止损：</strong>🔴硬止损=从参考价跌≥8% | 🟠盈利保护=从20日高点回撤≥5% | ⚠️=回撤≥3%警告<br>
  <strong>参考价：</strong>硬止损基准=前一交易日收盘（策略代理买入价）；盈利保护基准=近20日最高收盘价<br>
  <strong>评分：</strong>动量得分 = 年化收益率 × R²（短期×100% + 长期×50%）<br>
  <strong>过滤：</strong>近4日单日跌幅>5%的ETF短期得分清零<br>
  <strong>数据：</strong>腾讯行情API（前复权K线 + 实时报价）
</div>

<div class="footer">
  QClaw · 七星三马ETF盘中监控 · 自动生成
</div>

</div></body></html>'''
    return html

# ================================================================
# 邮件发送
# ================================================================
def send_email(html_content, subject):
    """发送HTML邮件"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_TO
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(EMAIL_TO, EMAIL_AUTH)
        server.sendmail(EMAIL_TO, EMAIL_TO, msg.as_string())
        server.quit()
        print('✅ 邮件发送成功！')
        return True
    except Exception as e:
        print(f'❌ 邮件发送失败: {e}')
        return False

# ================================================================
# 主流程
# ================================================================
def main():
    now = datetime.now()
    check_time_str = now.strftime('%Y-%m-%d %H:%M:%S')

    # 1. 检查交易时间
    trading, session_label = is_trading_time()
    if not trading:
        print(f'⏰ 非交易时间（{session_label}），跳过')
        return

    print('=' * 60)
    print(f'七星三马ETF盘中监控 | {check_time_str} | {session_label}')
    print('=' * 60)

    # 2. 加载上次状态
    prev_state = load_state()
    prev_high20 = prev_state.get('high20', {}) if prev_state else {}

    # 3. 拉取数据、计算得分、止损检测
    results = []
    high20_data = {}
    stop_warnings = []
    success_count = 0
    print(f'\n拉取 {len(ETF_MAP)} 只ETF数据...')

    for tcode, (code, name) in ETF_MAP.items():
        # K线数据
        klines = get_kline(tcode, 260)
        if not klines:
            print(f'  ❌ {name}({tcode}) K线获取失败')
            continue

        closes = [k['close'] for k in klines]
        ss, ls, total = score_etf(closes)
        if total is None:
            continue

        # 实时行情
        quote = get_quote(tcode)
        realtime_price = quote.get('price', closes[-1])
        chg_pct = quote.get('changePct', 0)

        # 前一交易日收盘（用作硬止损代理参考价）
        prev_close = closes[-2] if len(closes) >= 2 else closes[-1]

        # 近20日高点（结合上次状态，取max）
        n20 = HIGH20_LOOKBACK
        high20_prices = closes[-n20:]
        high20 = max(high20_prices) if high20_prices else realtime_price
        # 若当前价更高，则更新高点
        if realtime_price > high20:
            high20 = realtime_price
        high20_data[code] = high20

        # 止损检测
        stop_level, dd, ref_price = check_stop_loss(realtime_price, prev_close, high20)

        r = {
            'code': code, 'name': name, 'tcode': tcode,
            'short_score': ss, 'long_score': ls, 'total_score': total,
            'realtime_price': realtime_price, 'changePct': chg_pct,
            'drawdown_pct': dd,
            'stop_level': stop_level,
            'stop_ref_price': ref_price,
        }
        results.append(r)
        if stop_level:
            stop_warnings.append(r)
        success_count += 1
        time.sleep(0.2)

    if not results:
        print('❌ 无可用数据')
        return

    # 4. 排序
    results.sort(key=lambda x: x['total_score'], reverse=True)
    for i, r in enumerate(results):
        r['rank'] = i + 1

    print(f'\n数据获取: {success_count}/{len(ETF_MAP)} 只')
    print('\n--- 当前排名 ---')
    for r in results[:10]:
        print(f'  {r["rank"]:>2}. {r["name"]:<8} 综合:{r["total_score"]:>7.4f}  短期:{r["short_score"]:>7.4f}  长期:{r["long_score"]:>7.4f}  价格:{r["realtime_price"]:.3f}')

    # 5. 排名变动
    rank_changes = compute_rank_changes(results, prev_state)
    if rank_changes:
        print(f'\n--- 排名变动 ({len(rank_changes)}只) ---')
        for code, diff in sorted(rank_changes.items(), key=lambda x: -x[1]):
            name = next((r['name'] for r in results if r['code'] == code), code)
            arrow = '🔺' if diff > 0 else '🔻'
            print(f'  {arrow} {name}: {"上升" if diff > 0 else "下降"} {abs(diff)} 位')
    else:
        print('\n--- 排名变动：无（首次或跨天） ---')

    # 6. 止损汇总
    if stop_warnings:
        print(f'\n--- 止损警示 ({len(stop_warnings)}只) ---')
        for r in stop_warnings:
            label = '🔴硬止损' if r['stop_level'] == 'HARD_STOP' else '🟠盈利保护'
            print(f'  {label} {r["name"]}: {r["drawdown_pct"]:+.2f}%（参考价:{r["stop_ref_price"]:.3f} → 现价:{r["realtime_price"]:.3f}）')
    else:
        print('\n--- 止损状态：正常 ---')

    # 7. 保存状态
    save_state(results, check_time_str, high20_data)
    print('✅ 状态已保存（含20日高点）')

    # 8. 保存日志
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'monitor_{now.strftime("%Y%m%d")}.jsonl')
    log_entry = {
        'check_time': check_time_str,
        'session': session_label,
        'etf_count': len(results),
        'top1': results[0]['name'] if results else None,
        'rank_changes': {next((r['name'] for r in results if r['code'] == k), k): v for k, v in rank_changes.items()},
        'stop_warnings': [{'name': r['name'], 'level': r['stop_level'], 'dd': r['drawdown_pct']} for r in stop_warnings],
    }
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    # 9. 生成并发送邮件
    html = generate_html(results, rank_changes, stop_warnings, check_time_str, session_label)
    top1_name = results[0]['name'] if results else '?'
    stop_count = len(stop_warnings)
    change_count = len(rank_changes)
    if stop_count > 0:
        subject = f'【七星三马盘中】{now.strftime("%H:%M")} {top1_name}领跑 | ⚠️{stop_count}只止损 | {change_count}只变动'
    else:
        subject = f'【七星三马盘中】{now.strftime("%H:%M")} {top1_name}领跑 | {change_count}只变动'

    success = send_email(html, subject)
    if success:
        print(f'\n📧 邮件已发送 | 主题: {subject}')
    else:
        print(f'\n⚠️ 邮件发送失败')

    print(f'\n✅ 盘中监控完成！')

if __name__ == '__main__':
    main()
