#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Blakever 美股每日操作建议指南 — 2026-04-19 修正版（westock-data实时验证）"""

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

with open('/data/workspace/blakever_us_decision_20260419_v2.json', 'r') as f:
    data = json.load(f)

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blakever 美股每日操作建议指南</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #0d1117; color: #e6edf3; }}
.container {{ max-width: 800px; margin: 0 auto; }}
.header {{ background: linear-gradient(135deg, #1a2332 0%, #0d419d 100%); padding: 30px; border-radius: 12px; margin-bottom: 20px; text-align: center; }}
.header h1 {{ margin: 0; font-size: 24px; color: #fff; }}
.header .subtitle {{ color: #8b949e; margin-top: 8px; font-size: 14px; }}
.section {{ background: #161b22; border-radius: 12px; padding: 20px; margin-bottom: 16px; border: 1px solid #30363d; }}
.section-title {{ font-size: 16px; font-weight: 600; color: #58a6ff; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid #30363d; display: flex; align-items: center; gap: 8px; }}
.metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
.metric {{ background: #0d1117; border-radius: 8px; padding: 12px; text-align: center; border: 1px solid #30363d; }}
.metric .value {{ font-size: 22px; font-weight: 700; color: #fff; }}
.metric .label {{ font-size: 12px; color: #8b949e; margin-top: 4px; }}
.metric .bullish {{ color: #3fb950; }}
.metric .bearish {{ color: #f85149; }}
.metric .neutral {{ color: #d29922; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th {{ background: #0d1117; padding: 10px 8px; text-align: center; font-size: 12px; color: #8b949e; border-bottom: 1px solid #30363d; }}
td {{ padding: 10px 8px; text-align: center; font-size: 13px; border-bottom: 1px solid #21262d; }}
tr:hover {{ background: #161b2280; }}
.news-item {{ padding: 8px 0; border-bottom: 1px solid #21262d; font-size: 13px; line-height: 1.5; }}
.news-item:last-child {{ border-bottom: none; }}
.warning {{ background: #1c0a00; border: 1px solid #f8514930; border-radius: 8px; padding: 12px 16px; margin-top: 8px; font-size: 13px; color: #f85149; }}
.info {{ background: #0c2d6b20; border: 1px solid #58a6ff30; border-radius: 8px; padding: 12px 16px; margin-top: 8px; font-size: 13px; color: #58a6ff; }}
.success {{ background: #0a2e0a; border: 1px solid #3fb95030; border-radius: 8px; padding: 12px 16px; margin-top: 8px; font-size: 13px; color: #3fb950; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
.badge-bull {{ background: #3fb95020; color: #3fb950; border: 1px solid #3fb95040; }}
.badge-v2 {{ background: #a371f720; color: #a371f7; border: 1px solid #a371f740; }}
.badge-risk {{ background: #f8514920; color: #f85149; border: 1px solid #f8514940; }}
.badge-ok {{ background: #3fb95020; color: #3fb950; border: 1px solid #3fb95040; }}
.badge-exclude {{ background: #d2992220; color: #d29922; border: 1px solid #d2992240; }}
.footer {{ text-align: center; padding: 20px; color: #484f58; font-size: 12px; }}
.tag {{ font-size: 11px; padding: 1px 6px; border-radius: 4px; background: #30363d; color: #8b949e; }}
.long {{ color: #3fb950; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🇺🇸 Blakever 美股每日操作建议指南</h1>
  <div class="subtitle">{data['date']} | 策略版本: <span class="badge badge-v2">V2</span> {data['strategy_version']} | 数据来源: westock-data实时验证</div>
</div>

<!-- 数据修正说明 -->
<div class="section">
  <div class="section-title">🔧 数据修正说明</div>
  <div class="success">
    ✅ <strong>本轮已使用westock-data实时行情验证全部股价</strong>，修正了此前5只个股价格偏差问题。<br>
    ✅ SPY/QQQ ETF价格无误。个股已从westock-data获取4/17收盘价及技术指标，V2策略信号基于真实数据计算。
  </div>
</div>

<!-- 行情概览 -->
<div class="section">
  <div class="section-title">📡 行情概览（2026-04-17收盘）</div>
  <div class="metric-grid">
    <div class="metric">
      <div class="value bullish">{data['spy_close']:.2f}</div>
      <div class="label">SPY 标普500</div>
    </div>
    <div class="metric">
      <div class="value bullish">{data['qqq_close']:.2f}</div>
      <div class="label">QQQ 纳指100</div>
    </div>
    <div class="metric">
      <div class="value neutral">{data['vix']:.2f}</div>
      <div class="label">VIX 恐慌指数</div>
    </div>
    <div class="metric">
      <div class="value neutral">{data['tnx']:.2f}%</div>
      <div class="label">10Y 美债收益率</div>
    </div>
    <div class="metric">
      <div class="value bullish">{data['regime']} 🐂</div>
      <div class="label">市场环境</div>
    </div>
    <div class="metric">
      <div class="value">{data['confidence']}%</div>
      <div class="label">研判置信度</div>
    </div>
  </div>
</div>

<!-- Agent 1 -->
<div class="section">
  <div class="section-title">🔍 Agent 1: 市场行情判断 → <span class="badge badge-bull">趋势牛市</span> 置信度 {data['confidence']}%</div>
  <div class="info">
    <strong>修正说明：</strong>Python模块基于SMA判断震荡市(SMA因伊朗战争冲击滞后)，但EMA多头排列+ADX>20+纳指13连阳+标普首破7100，综合修正为趋势牛市。<br>
    <strong>SPY关键信号：</strong>EMA12(681.17) > EMA26(673.30) ✅ | ADX14=28.11 > 20 ✅ | VIX=17.48 ✅ | 纳指13连阳 ✅
  </div>
</div>

<!-- Agent 2 -->
<div class="section">
  <div class="section-title">📰 Agent 2: 宏观叙事分析 → 情绪因子 {data['sentiment_factor']}</div>
  <div style="margin-top:8px;">"""

for n in data['news_highlights']:
    html += f"""
    <div class="news-item">{n}</div>"""

html += f"""
  </div>
</div>

<!-- Agent 3 V2策略 -->
<div class="section">
  <div class="section-title">🐂 Agent 3: 牛市投资 — <span class="badge badge-v2">V2策略</span> EMA10/20 + ADX>20</div>
  <div class="info" style="margin-bottom:12px;">
    <strong>V2策略核心：</strong>3条件(EMA12>EMA26 + ADX>20 + MACD柱>0)宽松模式≥2/3通过<br>
    <strong>V2验证结果：</strong>7只候选股经westock-data技术指标实时验证
  </div>
  <table>
    <tr><th>标的</th><th>名称</th><th>收盘价</th><th>EMA12>EMA26</th><th>ADX</th><th>MACD柱</th><th>条件</th><th>V2信号</th></tr>"""

v2_stocks = [
    ('NVDA', '英伟达', 201.68, '✅', '32.47 ✅', '6.32 ✅', '3/3', '🟢'),
    ('MSFT', '微软', 422.79, '✅', '36.82 ✅', '13.56 ✅', '3/3', '🟢'),
    ('AVGO', '博通', 406.54, '✅', '47.16 ✅', '19.57 ✅', '3/3', '🟢'),
    ('GOOGL', '谷歌', 341.68, '✅', '46.54 ✅', '11.22 ✅', '3/3', '🟢'),
    ('META', 'Meta', 688.55, '✅', '34.54 ✅', '29.11 ✅', '3/3', '🟢'),
    ('AAPL', '苹果', 270.23, '✅', '9.77 ❌', '3.87 ✅', '2/3', '🟡'),
    ('TSLA', '特斯拉', 400.62, '❌', '16.01 ❌', '10.79 ✅', '1/3', '🔴'),
]

for sym, name, price, ema, adx, macd, cond, signal in v2_stocks:
    style = 'color:#f85149' if signal == '🔴' else ('color:#d29922' if signal == '🟡' else '')
    html += f"""
    <tr style="{style}">
      <td><strong>{sym}</strong></td><td>{name}</td><td>${price:.2f}</td>
      <td>{ema}</td><td>{adx}</td><td>{macd}</td><td>{cond}</td><td>{signal}</td>
    </tr>"""

html += f"""
  </table>
  <div class="warning" style="margin-top:12px;">
    ❌ <strong>AAPL</strong> ADX=9.77（无趋势），V2宽松模式边缘(2/3)，暂不入选<br>
    ❌ <strong>TSLA</strong> EMA12&lt;EMA26 + ADX=16，超跌反弹非趋势行情(1/3)，不入选
  </div>
</div>

<!-- Top5推荐 -->
<div class="section">
  <div class="section-title">🏆 Top5 推荐标的（V2策略通过，六维评分排序）</div>
  <table>
    <tr><th>排名</th><th>标的</th><th>名称</th><th>方向</th><th>入场价</th><th>止损</th><th>止盈</th><th>仓位%</th><th>ADX</th><th>RSI12</th><th>评分</th></tr>"""

for i, r in enumerate(data['recommendations'], 1):
    html += f"""
    <tr>
      <td>{i}</td><td><strong>{r['symbol']}</strong></td><td>{r['name']}</td>
      <td class="long">{r['direction']}</td>
      <td>${r['entry']:.2f}</td>
      <td style="color:#f85149">${r['stop_loss']:.2f}</td>
      <td style="color:#3fb950">${r['take_profit']:.2f}</td>
      <td>{r['position_pct']:.2f}%</td>
      <td>{r['adx']:.1f}</td>
      <td>{r['rsi12']:.0f}</td>
      <td><span class="tag">{r['score']:.0f}</span></td>
    </tr>"""

html += f"""
  </table>
</div>

<!-- 推荐理由 -->
<div class="section">
  <div class="section-title">📝 推荐理由</div>"""

for r in data['recommendations']:
    html += f"""
  <div class="news-item">
    <strong>{r['symbol']} ({r['name']})</strong> — {r['reason']}<br>
    <span style="color:#8b949e">PE={r['pe']:.1f} | ADX={r['adx']:.1f} | RSI12={r['rsi12']:.0f} | KDJ K={r['kdj_k']:.1f} | 调整后置信度={r['adjusted_confidence']}%</span>
  </div>"""

html += f"""
</div>

<!-- 反向测试辩论庭 -->
<div class="section">
  <div class="section-title">⚖️ 反向测试辩论庭</div>
  <table>
    <tr><th>标的</th><th>5日涨幅</th><th>RSI修正</th><th>KDJ修正</th><th>Bias修正</th><th>错误概率</th><th>调整后置信度</th></tr>
    <tr><td>MSFT</td><td>+10%(+10%)</td><td>+5%</td><td>-</td><td>+5%</td><td style="color:#f85149">40%</td><td>46.8%</td></tr>
    <tr><td>AVGO</td><td>+5%</td><td>+8%</td><td>+5%</td><td>-</td><td style="color:#f85149">43%</td><td>44.5%</td></tr>
    <tr><td>META</td><td>-</td><td>-</td><td>-</td><td>-</td><td style="color:#3fb950">20%</td><td>62.4%</td></tr>
    <tr><td>GOOGL</td><td>-</td><td>+5%</td><td>-</td><td>-</td><td style="color:#d29922">30%</td><td>54.6%</td></tr>
    <tr><td>NVDA</td><td>+5%</td><td>+5%</td><td>-</td><td>-</td><td style="color:#d29922">30%</td><td>54.6%</td></tr>
  </table>
</div>

<!-- CRO风控 -->
<div class="section">
  <div class="section-title">🛡️ Agent 0: CRO 风控计算</div>
  <div class="metric-grid">
    <div class="metric">
      <div class="value" style="color:#3fb950">未触发</div>
      <div class="label">强制空仓线</div>
    </div>
    <div class="metric">
      <div class="value" style="color:#3fb950">{data['cro_summary']['vix_risk_level']}</div>
      <div class="label">VIX风险等级</div>
    </div>
    <div class="metric">
      <div class="value">{data['cro_summary']['total_exposure_pct']:.2f}%</div>
      <div class="label">总敞口使用率</div>
    </div>
  </div>
  <div class="warning" style="margin-top:12px;">
    ⚠️ 隐性相关性预警：美股科技巨头 — NVDA+AVGO+GOOGL+META+MSFT + 现有AAPL/MSFT，极端行情下可能同向大幅波动
  </div>
</div>

<!-- 现有持仓 -->
<div class="section">
  <div class="section-title">📊 现有持仓</div>
  <table>
    <tr><th>标的</th><th>入场价</th><th>当前价</th><th>盈亏%</th></tr>"""

for pos in data['existing_positions']:
    pnl_color = '#3fb950' if pos['pnl_pct'] > 0 else '#f85149'
    html += f"""
    <tr>
      <td><strong>{pos['symbol']}</strong></td>
      <td>${pos['entry']:.3f}</td>
      <td>${pos['current']:.2f}</td>
      <td style="color:{pnl_color}">{pos['pnl_pct']:+.2f}%</td>
    </tr>"""

html += f"""
  </table>
</div>

<!-- 风险预警 -->
<div class="section">
  <div class="section-title">🚨 风险预警</div>"""

for w in data['risk_warnings']:
    html += f"""
  <div class="warning">⚠️ {w}</div>"""

html += f"""
</div>

<!-- 关键事件日历 -->
<div class="section">
  <div class="section-title">📅 关键事件日历</div>
  <table>
    <tr><th>日期</th><th>事件</th><th>影响</th></tr>
    <tr><td>4/20-21</td><td>美伊谈判恢复</td><td style="color:#3fb950">若达成协议→风险偏好↑</td></tr>
    <tr><td>4/21</td><td>以色列-黎巴嫩停火截止(10天)</td><td style="color:#f85149">若破裂→VIX飙升</td></tr>
    <tr><td>4/22</td><td>TSLA财报</td><td style="color:#d29922">波动加大</td></tr>
    <tr><td>4/28-29</td><td>FOMC利率决议</td><td style="color:#d29922">维持不变预期99.5%</td></tr>
    <tr><td>4/28</td><td>301调查听证会</td><td style="color:#f85149">中美关系敏感</td></tr>
    <tr><td>4/29</td><td>GOOGL财报</td><td style="color:#d29922">AI搜索验证</td></tr>
    <tr><td>4/30</td><td>MSFT/META/AMZN财报</td><td style="color:#d29922">科技巨头业绩验证</td></tr>
    <tr><td>5/1</td><td>AAPL财报</td><td style="color:#d29922">消费电子风向标</td></tr>
    <tr><td>5/20</td><td>NVDA财报</td><td style="color:#3fb950">AI算力需求验证</td></tr>
  </table>
</div>

<!-- V1→V2切换说明 -->
<div class="section">
  <div class="section-title">🔄 策略版本切换说明 V1 → V2</div>
  <div class="info">
    <strong>切换原因：</strong>基于10年美股牛市区间回测，V1六维评分策略在牛市中亏损31.75%，V2宽松版盈利28.26%<br>
    <strong>V1缺陷：</strong>MA20>MA60>MA120多头排列在牛市初期/回调中频繁不满足→空仓过多+过度交易(26.4次/区间)<br>
    <strong>V2优势：</strong>EMA10>EMA20更灵活+ADX>20确认趋势→捕获更多涨幅+交易更精准(7.0次/区间)<br>
    <strong>V2回测表现：</strong>牛市区间加权年化+3.35% vs V1 -4.65%，卡尔马比率0.75 vs V1 -0.34
  </div>
</div>

<div class="footer">
  <p>Blakever 多智能体投资决策系统 | 10个Agent协同 | V2策略 (EMA10/20+ADX>20)</p>
  <p>⚠️ 本报告仅供投资参考，不构成投资建议。投资有风险，入市需谨慎。</p>
  <p>数据来源: westock-data (腾讯自选股接口) | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>

</div>
</body>
</html>"""

html_path = '/data/workspace/blakever_us_email_20260419_v2.html'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"✅ 修正版HTML报告已保存: {html_path}")

# 发送邮件
smtp_server = 'smtp.qq.com'
smtp_port = 465
sender = '848786642@qq.com'
password = 'ljbtvacrctjobfed'
receiver = '848786642@qq.com'

msg = MIMEMultipart('alternative')
msg['Subject'] = f'🇺🇸 Blakever 美股每日操作建议指南 | {data["date"]} | 🐂牛市 V2策略（数据已修正）'
msg['From'] = sender
msg['To'] = receiver
msg.attach(MIMEText(html, 'html', 'utf-8'))

try:
    server = smtplib.SMTP_SSL(smtp_server, smtp_port)
    server.login(sender, password)
    server.sendmail(sender, receiver, msg.as_string())
    server.quit()
    print(f"✅ 修正版邮件发送成功! → {receiver}")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
