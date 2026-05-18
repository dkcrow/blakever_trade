#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星三马ETF轮动策略 - 每日评分邮件
===================================
每个交易日8:00执行，基于前一交易日数据计算动量评分，
发送推荐买入/关注/回避列表到邮箱。

数据源：腾讯行情API（前复权日线，260日窗口）
ETF池：三马七星策略38只大池（本地有数据的25只）
评分逻辑：加权线性回归动量 = 年化收益率 × R²
"""

import os, sys, math, json, subprocess, time, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
sys.stdout.reconfigure(encoding='utf-8')

# ================================================================
# 配置
# ================================================================
TENCENT_API = '/home/node/.openclaw/workspace/blakever_trade/westock-data/scripts/tencent_api.mjs'
DATA_DIR = '/home/node/.openclaw/workspace/blakever_trade/back_trader_stocks/a'
EMAIL_TO = '848786642@qq.com'
EMAIL_AUTH = 'ljbtvacrctjobfed'
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SHORT_LOOKBACK = 25
LONG_LOOKBACK = 250

# 三马七星ETF池（25只本地有数据）
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
# 评分计算
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
    """计算ETF动量得分"""
    if len(prices_list) < 5:
        return None, None, None
    sp = prices_list[-short_n:]
    lp = prices_list[-long_n:]
    ann_s, r2_s, score_s = weighted_reg(sp)
    ann_l, r2_l, score_l = weighted_reg(lp)
    # 近期4日急跌过滤（跌幅>5%则短期得分清零）
    if len(sp) >= 4:
        for i in range(len(sp) - 1):
            if sp[i] > 0 and sp[i + 1] / sp[i] < 0.95:
                score_s = 0
                break
    return score_s, score_l * 0.5, score_s + score_l * 0.5

# ================================================================
# 邮件生成
# ================================================================
def generate_html(results, trade_date):
    """生成HTML邮件"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 分类
    strong_buy = [r for r in results if r['total_score'] > 0.1 and r['code'] != '511880_XSHG']
    watch = [r for r in results if 0.01 <= r['total_score'] <= 0.1 and r['code'] != '511880_XSHG']
    avoid = [r for r in results if r['total_score'] < 0]
    neutral = [r for r in results if 0 <= r['total_score'] < 0.01 and r['code'] != '511880_XSHG']

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ margin:0; padding:0; background:#0f172a; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
.container {{ max-width:720px; margin:0 auto; padding:20px; }}
.header {{ text-align:center; padding:24px 0 16px; border-bottom:2px solid #1e293b; }}
.header h1 {{ color:#f8fafc; margin:0 0 4px; font-size:22px; }}
.header p {{ color:#94a3b8; margin:0; font-size:13px; }}
.section {{ margin-top:24px; }}
.section-title {{ font-size:16px; font-weight:700; margin-bottom:12px; padding-bottom:8px;
    border-bottom:2px solid; }}
.section-buy .section-title {{ color:#10b981; border-color:#10b981; }}
.section-watch .section-title {{ color:#f59e0b; border-color:#f59e0b; }}
.section-avoid .section-title {{ color:#ef4444; border-color:#ef4444; }}
.section-neutral .section-title {{ color:#6b7280; border-color:#6b7280; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ padding:8px 6px; text-align:center; color:#94a3b8; font-weight:600;
    border-bottom:1px solid #1e293b; font-size:12px; }}
td {{ padding:7px 6px; text-align:center; border-bottom:1px solid #1e293b; }}
tr:hover {{ background:#1e293b40; }}
.code {{ color:#93c5fd; font-weight:600; font-family:monospace; }}
.name {{ color:#f1f5f9; }}
.score-up {{ color:#10b981; font-weight:700; }}
.score-down {{ color:#ef4444; font-weight:700; }}
.price {{ color:#e5e7eb; }}
.date {{ color:#64748b; font-size:12px; }}
.rank {{ color:#94a3b8; font-weight:600; width:30px; }}
.note {{ margin-top:20px; padding:12px 16px; background:#1e293b; border-radius:8px;
    font-size:12px; color:#94a3b8; line-height:1.8; }}
.note strong {{ color:#e2e8f0; }}
.footer {{ text-align:center; padding:16px 0 8px; color:#475569; font-size:11px; border-top:1px solid #1e293b; margin-top:24px; }}
</style></head><body>
<div class="container">

<div class="header">
  <h1>🚀 七星三马 ETF 轮动日报</h1>
  <p>基于 {trade_date} 收盘数据 &nbsp;|&nbsp; 加权线性回归动量评分</p>
</div>
'''

    def render_table(items, title, score_class, section_class):
        if not items:
            return ''
        h = f'''<div class="section {section_class}">
  <div class="section-title">{title}（{len(items)}只）</div>
  <table>
    <tr><th></th><th style="text-align:left">ETF</th><th>短期25日</th><th>长期250日</th><th>综合得分</th><th>收盘价</th></tr>
'''
        for i, r in enumerate(items, 1):
            sc = score_class
            ss = f'{r["short_score"]:.3f}'
            ls = f'{r["long_score"]:.3f}'
            ts = f'{r["total_score"]:.3f}'
            chg = r.get('changePct', 0)
            chg_str = f'{chg:+.2f}%'
            chg_color = '#10b981' if chg >= 0 else '#ef4444'
            h += f'''    <tr>
      <td class="rank">{i}</td>
      <td style="text-align:left"><span class="code">{r["code"]}</span> <span class="name">{r["name"]}</span></td>
      <td class="{sc}">{ss}</td>
      <td class="{sc}">{ls}</td>
      <td class="{sc}" style="font-size:15px">{ts}</td>
      <td class="price">{r["last_price"]:.3f} <span style="color:{chg_color};font-size:11px">{chg_str}</span></td>
    </tr>
'''
        h += '  </table>\n</div>\n'
        return h

    html += render_table(strong_buy, '🔥 强烈推荐买入', 'score-up', 'section-buy')
    html += render_table(watch, '👀 适当关注', 'score-up', 'section-watch')
    html += render_table(neutral, '😐 中性观望', 'price', 'section-neutral')
    html += render_table(avoid, '⚠️ 建议回避', 'score-down', 'section-avoid')

    html += f'''
<div class="note">
  <strong>评分说明：</strong>动量得分 = 年化收益率 × R²（短期25日权重100% + 长期250日权重50%）<br>
  <strong>过滤规则：</strong>近4日单日跌幅>5%的ETF短期得分清零 | 货币ETF(511880)仅作参考不计入推荐<br>
  <strong>数据来源：</strong>腾讯行情API（前复权日线，260日窗口）| 脚本: tencent_api.mjs<br>
  <strong>执行时间：</strong>{now}
</div>

<div class="footer">
  QClaw · 七星三马ETF轮动策略 · 自动生成
</div>

</div></body></html>'''
    return html

# ================================================================
# 发送邮件
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
    print('='*50)
    print(f'七星三马ETF轮动日报 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('='*50)

    results = []
    print(f'拉取 {len(ETF_MAP)} 只ETF K线数据...')

    for tcode, (code, name) in ETF_MAP.items():
        klines = get_kline(tcode, 260)
        if not klines:
            print(f'  ❌ {name}({tcode}) K线获取失败')
            continue

        closes = [k['close'] for k in klines]
        ss, ls, total = score_etf(closes)
        if total is None:
            continue

        last_kline = klines[-1]
        # 获取实时涨跌幅
        quote = get_quote(tcode)
        chg_pct = quote.get('changePct', 0)

        results.append({
            'code': code, 'name': name, 'tcode': tcode,
            'short_score': ss, 'long_score': ls, 'total_score': total,
            'last_price': last_kline['close'], 'last_date': last_kline['date'],
            'changePct': chg_pct
        })
        print(f'  ✅ {name}: {total:.4f}')
        time.sleep(0.3)

    results.sort(key=lambda x: x['total_score'], reverse=True)
    
    # 确定交易日日期（最新K线日期）
    trade_date = results[0]['last_date'] if results else datetime.now().strftime('%Y-%m-%d')
    
    print(f'\n数据截止: {trade_date}')
    print(f'有数据ETF: {len(results)}/25')

    # TOP5
    print('\n--- TOP5 推荐 ---')
    for i, r in enumerate(results[:5], 1):
        if r['code'] != '511880_XSHG':
            print(f'  {i}. {r["name"]}({r["code"]}) 得分:{r["total_score"]:.4f}')

    # 生成并发送邮件
    html = generate_html(results, trade_date)
    subject = f'【七星三马ETF日报】{trade_date} 推荐买入TOP{min(5,len([r for r in results if r["total_score"]>0.1 and r["code"]!="511880_XSHG"]))}'

    # 保存HTML到本地
    output_dir = '/home/node/.openclaw/workspace/blakever_trade/strategy_arena'
    html_path = os.path.join(output_dir, f'qixing_daily_{trade_date}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n📄 HTML已保存: {html_path}')

    # 发送邮件
    success = send_email(html, subject)
    return success

if __name__ == '__main__':
    main()
