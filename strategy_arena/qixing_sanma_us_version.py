#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马七星ETF策略 - 美股版本
============================
基于动量轮动的ETF策略，美股市场版本

成分股：
- 美股大盘指数：QQQ(纳斯达克100), SPY(标普500), DIA(道琼斯), IWM(罗素2000)
- 大宗商品：GLD(黄金), SLV(白银), USO(原油)
- 债券：AGG(综合债券)
- 行业：SMH(半导体)
- 货币基金：JPST(超短债)
"""

import os, sys, math, json, subprocess, time, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

# ================================================================
# 配置
# ================================================================
TENCENT_API = 'C:\\Users\\blakehao\\.qclaw\\workspace\\westock-data\\scripts\\tencent_api.mjs'
STATE_FILE = 'C:\\Users\\blakehao\\.qclaw\\workspace\\strategy_arena\\qixing_sanma_us_state.json'
LOG_DIR = 'C:\\Users\\blakehao\\.qclaw\\workspace\\strategy_arena\\qixing_sanma_us_logs'

EMAIL_TO = '848786642@qq.com'
EMAIL_AUTH = 'ljbtvacrctjobfed'
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465

SHORT_LOOKBACK = 25
LONG_LOOKBACK = 250
STOP_LOSS_PCT = 0.08        # 硬止损：从参考价跌8%触发
PROFIT_PROTECT_PCT = 0.05   # 盈利保护：从近20日高点回撤5%触发
HIGH20_LOOKBACK = 20        # 近20日高点窗口

# 美股ETF池（10只）
ETF_MAP = {
    'usQQQ':  ('usQQQ',  '纳斯达克100'),
    'usSPY':  ('usSPY',  '标普500'),
    'usDIA':  ('usDIA',  '道琼斯'),
    'usIWM':  ('usIWM',  '罗素2000'),
    'usGLD':  ('usGLD',  '黄金'),
    'usSLV':  ('usSLV',  '白银'),
    'usUSO':  ('usUSO',  '原油'),
    'usAGG':  ('usAGG',  '综合债券'),
    'usSMH':  ('usSMH',  '半导体'),
    'usJPST': ('usJPST', '超短债'),
}

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
# 评分计算（与A股版本完全一致）
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
        if code in prev_ranks:
            delta = prev_ranks[code] - cur_rank  # 正值=上升
            if delta != 0:
                changes[code] = delta
    return changes

# ================================================================
# 邮件报告
# ================================================================
def send_email(subject, html_body):
    """发送HTML邮件"""
    try:
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = EMAIL_TO
        msg['To'] = EMAIL_TO
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_TO, EMAIL_AUTH)
            server.sendmail(EMAIL_TO, EMAIL_TO, msg.as_string())
        return True
    except Exception as e:
        print(f'邮件发送失败: {e}')
        return False

def build_email_report(check_time, rankings, changes, stop_alerts):
    """构建HTML邮件报告"""
    rows = []
    for r in rankings:
        code = r['code']
        change_mark = ''
        if code in changes:
            delta = changes[code]
            if delta > 0:
                change_mark = f'<span style="color:green">↑{delta}</span>'
            else:
                change_mark = f'<span style="color:red">↓{abs(delta)}</span>'
        rows.append(
            f'<tr><td>{r["rank"]}</td><td>{r["name"]}</td>'
            f'<td>{r["total_score"]:.4f}</td><td>{r["short_score"]:.4f}</td>'
            f'<td>{r["long_score"]:.4f}</td><td>{r["price"]}</td>'
            f'<td>{change_mark}</td></tr>'
        )

    stop_rows = []
    for alert in stop_alerts:
        stop_rows.append(
            f'<tr><td>{alert["name"]}</td><td>{alert["type"]}</td>'
            f'<td>{alert["drawdown"]:.2f}%</td><td>{alert["ref_price"]:.3f}</td>'
            f'<td>{alert["price"]:.3f}</td></tr>'
        )

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
table {{ border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
th {{ background-color: #4CAF50; color: white; }}
tr:nth-child(even) {{ background-color: #f2f2f2; }}
.stop {{ background-color: #ffebee; }}
</style></head><body>
<h2>三马七星美股ETF监控 | {check_time}</h2>
<h3>排名 Top 10</h3>
<table>
<tr><th>排名</th><th>名称</th><th>综合得分</th><th>短期得分</th><th>长期得分</th><th>价格</th><th>变动</th></tr>
{''.join(rows[:10])}
</table>
<h3>止损警示 ({len(stop_alerts)}只)</h3>
<table class="stop">
<tr><th>名称</th><th>类型</th><th>回撤</th><th>参考价</th><th>现价</th></tr>
{''.join(stop_rows)}
</table>
</body></html>'''
    return html

# ================================================================
# 主流程
# ================================================================
def main():
    check_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'============================================================')
    print(f'三马七星美股ETF监控 | {check_time} | 立即执行')
    print(f'============================================================')

    # 加载上一次状态
    prev_state = load_state()

    # 拉取数据
    print(f'\n拉取 {len(ETF_MAP)} 只美股ETF数据...')
    all_data = []
    high20_data = {}

    for code, (tcode, name) in ETF_MAP.items():
        nodes = get_kline(tcode, limit=260)
        quote_data = get_quote(tcode)

        if not nodes or len(nodes) < 5:
            print(f'  ❌ {name}({code}) K线获取失败')
            continue

        prices = [n['close'] for n in nodes]
        current_price = quote_data.get('price', prices[-1])
        prev_close = quote_data.get('lastClose', prices[-2] if len(prices) > 1 else prices[-1])

        # 计算20日高点
        high20 = max(prices[-HIGH20_LOOKBACK:]) if len(prices) >= HIGH20_LOOKBACK else max(prices)
        high20_data[code] = high20

        # 计算得分
        score_s, score_l, total = score_etf(prices)
        if total is None:
            print(f'  ❌ {name}({code}) 得分计算失败')
            continue

        all_data.append({
            'code': code, 'name': name, 'tcode': tcode,
            'total_score': total, 'short_score': score_s, 'long_score': score_l,
            'price': current_price, 'prev_close': prev_close,
            'high20': high20
        })
        print(f'  ✅ {name}({code}) 价格:{current_price} 综合:{total:.4f}')

    if not all_data:
        print('❌ 无可用数据')
        return

    # 排名
    all_data.sort(key=lambda x: x['total_score'], reverse=True)
    for i, r in enumerate(all_data, 1):
        r['rank'] = i

    # 排名变动
    changes = compute_rank_changes(all_data, prev_state)

    # 止损检测
    stop_alerts = []
    for r in all_data:
        stop_type, dd, ref = check_stop_loss(r['price'], r['prev_close'], r['high20'])
        if stop_type:
            stop_alerts.append({
                'name': r['name'], 'type': '硬止损' if stop_type == 'HARD_STOP' else '盈利保护',
                'drawdown': dd, 'ref_price': ref, 'price': r['price']
            })

    # 显示结果
    print(f'\n--- 当前排名 ---')
    for r in all_data[:10]:
        change_mark = ''
        if r['code'] in changes:
            delta = changes[r['code']]
            change_mark = f' ↑{delta}' if delta > 0 else f' ↓{abs(delta)}'
        print(f'   {r["rank"]}. {r["name"]:8s} 综合:{r["total_score"]:8.4f}  短期:{r["short_score"]:8.4f}  长期:{r["long_score"]:8.4f}  价格:{r["price"]} {change_mark}')

    if changes:
        print(f'\n--- 排名变动 ---')
        for code, delta in changes.items():
            name = ETF_MAP[code][1]
            print(f'   {name}: {"↑"+str(delta) if delta > 0 else "↓"+str(abs(delta))}')

    if stop_alerts:
        print(f'\n--- 止损警示 ({len(stop_alerts)}只) ---')
        for a in stop_alerts:
            print(f'   🟠{a["type"]} {a["name"]}: {a["drawdown"]:.2f}%（参考价:{a["ref_price"]:.3f} → 现价:{a["price"]:.3f}）')

    # 保存状态
    save_state(all_data, check_time, high20_data)
    print(f'✅ 状态已保存（含20日高点）')

    # 发送邮件
    subject = f'【三马七星美股】{check_time[-8:-3]} 排名更新 | ⚠️{len(stop_alerts)}只止损'
    html = build_email_report(check_time, all_data, changes, stop_alerts)
    if send_email(subject, html):
        print(f'✅ 邮件发送成功！')
    else:
        print(f'❌ 邮件发送失败')

    print(f'\n✅ 美股监控完成！')

if __name__ == '__main__':
    main()
