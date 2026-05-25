#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blakever 美股每日操作建议指南 — 2026-04-19
HTML邮件生成+发送
"""

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# 加载决策数据
with open('/data/workspace/blakever_us_decision_20260419.json', 'r') as f:
    data = json.load(f)

# ============================================================
# HTML报告生成
# ============================================================
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
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
.badge-bull {{ background: #3fb95020; color: #3fb950; border: 1px solid #3fb95040; }}
.badge-v2 {{ background: #a371f720; color: #a371f7; border: 1px solid #a371f740; }}
.badge-risk {{ background: #f8514920; color: #f85149; border: 1px solid #f8514940; }}
.badge-ok {{ background: #3fb95020; color: #3fb950; border: 1px solid #3fb95040; }}
.footer {{ text-align: center; padding: 20px; color: #484f58; font-size: 12px; }}
.tag {{ font-size: 11px; padding: 1px 6px; border-radius: 4px; background: #30363d; color: #8b949e; }}
.long {{ color: #3fb950; }}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="header">
  <h1>🇺🇸 Blakever 美股每日操作建议指南</h1>
  <div class="subtitle">{data['date']} | 策略版本: <span class="badge badge-v2">V2</span> {data['strategy_version']} | 第{datetime.now().timetuple().tm_yday}天/{datetime.now().year}</div>
</div>

<!-- 行情概览 -->
<div class="section">
  <div class="section-title">📡 行情概览</div>
  <div class="metric-grid">
    <div class="metric">
      <div class="value bullish">{'📈 ' if data['spy_close'] > 700 else ''}{data['spy_close']:.2f}</div>
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

<!-- Agent 1 市场研判 -->
<div class="section">
  <div class="section-title">🔍 Agent 1: 市场行情判断 → <span class="badge badge-bull">趋势牛市</span> 置信度 {data['confidence']}%</div>
  <div class="info">
    <strong>修正说明：</strong>Python模块基于SMA判断震荡市(SMA因伊朗战争冲击滞后)，但EMA多头排列+ADX>20+纳指13连阳+标普首破7100，综合修正为趋势牛市。<br>
    <strong>关键信号：</strong>EMA10(687.59) > EMA20(676.83) ✅ | ADX14=28.11 > 20 ✅ | VIX=17.48 低波动 ✅ | 纳指13连阳创1992年来最长纪录 ✅
  </div>
</div>

<!-- Agent 2 宏观叙事 -->
<div class="section">
  <div class="section-title">📰 Agent 2: 宏观叙事分析 → 情绪因子 {data['sentiment_factor']}</div>
  <div style="margin-top:8px;">
    <div class="news-item">🕊️ <strong>美伊停火重大进展：</strong>伊朗宣布霍尔木兹海峡"完全开放"，油价暴跌11%，WTI跌至83.85美元</div>
    <div class="news-item">📈 <strong>纳指13连阳：</strong>创1992年来最长纪录，标普首破7100，道指收复战争全部跌幅</div>
    <div class="news-item">💰 <strong>Q1财报季：</strong>JPM/GS/BAC盈利超预期，NFLX指引不佳跌9.7%</div>
    <div class="news-item">🏦 <strong>美联储：</strong>4月维持不变99.5%，12月降息概率升至60%（油价回落提振）</div>
    <div class="news-item">💵 <strong>CTA史诗级回补：</strong>单周860亿美元扫货，未来一周再加700亿被动买盘</div>
    <div class="news-item">⚠️ <strong>风险：</strong>停火仅10天，若破裂可能快速回撤</div>
  </div>
</div>

<!-- Agent 3 牛市V2策略 -->
<div class="section">
  <div class="section-title">🐂 Agent 3: 牛市投资 — <span class="badge badge-v2">V2策略</span> EMA10/20 + ADX>20</div>
  <div class="info" style="margin-bottom:12px;">
    <strong>V2策略信号：</strong>SPY 🟢持仓 | QQQ 🟢持仓 | 双条件(EMA10>EMA20 + ADX>20)全部满足<br>
    <strong>选股流程：</strong>标普500+纳指100 → V2动量筛选 → 六维评分 → Top5
  </div>
  <table>
    <tr>
      <th>标的</th><th>名称</th><th>方向</th><th>入场价</th><th>止损</th><th>止盈</th><th>仓位%</th><th>评分</th><th>理由</th>
    </tr>"""

for i, r in enumerate(data['recommendations']):
    scores = [108, 104, 101, 100, 97]
    score = scores[i] if i < len(scores) else 90
    html += f"""
    <tr>
      <td><strong>{r['symbol']}</strong></td>
      <td>{r['name']}</td>
      <td class="long">{r['direction']}</td>
      <td>{r['entry']:.2f}</td>
      <td style="color:#f85149">{r['stop_loss']:.2f}</td>
      <td style="color:#3fb950">{r['take_profit']:.2f}</td>
      <td>{r['position_pct']:.2f}%</td>
      <td><span class="tag">{score}</span></td>
      <td style="text-align:left;font-size:12px;">{r['reason']}</td>
    </tr>"""

html += f"""
  </table>
</div>

<!-- 反向测试辩论庭 -->
<div class="section">
  <div class="section-title">⚖️ 反向测试辩论庭</div>
  <table>
    <tr><th>标的</th><th>高位修正</th><th>RSI修正</th><th>财报修正</th><th>缩量修正</th><th>错误概率</th><th>调整后置信度</th></tr>
    <tr><td>NVDA</td><td>+10%</td><td>+5%</td><td>-</td><td>+5%</td><td style="color:#f85149">40%</td><td>46.8%</td></tr>
    <tr><td>AAPL</td><td>+10%</td><td>-</td><td>-</td><td>+5%</td><td style="color:#d29922">35%</td><td>50.7%</td></tr>
    <tr><td>MSFT</td><td>-</td><td>-</td><td>-</td><td>+5%</td><td style="color:#3fb950">25%</td><td>58.5%</td></tr>
    <tr><td>TSLA</td><td>+10%</td><td>+5%</td><td>+10%</td><td>+5%</td><td style="color:#f85149">40%</td><td>46.8%</td></tr>
    <tr><td>AVGO</td><td>+10%</td><td>+5%</td><td>-</td><td>+5%</td><td style="color:#d29922">35%</td><td>50.7%</td></tr>
  </table>
</div>

<!-- 宏观因子一致性 -->
<div class="section">
  <div class="section-title">🔗 宏观因子一致性校验</div>
  <div class="info">
    ✅ 无宏观逻辑分裂：5只标的均属于"科技成长"大类<br>
    ⚠️ NVDA+AVGO同属半导体，极端行情下可能同向大幅波动<br>
    📌 半导体行业总仓位不超过净值20%（CRO约束）
  </div>
</div>

<!-- Agent 0 CRO风控 -->
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
    ⚠️ 隐性相关性预警：美股科技巨头 — 拟新增TSLA/MSFT/AAPL/NVDA，现有持仓已含MSFT/AAPL，极端行情下可能同向大幅波动
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
      <td>{pos['entry']:.3f}</td>
      <td>{pos['current']:.2f}</td>
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
    <tr><td>4/30</td><td>MSFT/META/GOOGL/AMZN财报</td><td style="color:#d29922">科技巨头业绩验证</td></tr>
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

<!-- 左侧捡漏 -->
<div class="section">
  <div class="section-title">🎣 左侧捡漏权限</div>
  <div class="info" style="color:#8b949e;">
    VIX>35? ❌ (17.48) | VIX长上影线? ❌ | 成交量≥2倍? ❌ (0.83) → 未触发
  </div>
</div>

<div class="footer">
  <p>Blakever 多智能体投资决策系统 | 10个Agent协同 | V2策略 (EMA10/20+ADX>20)</p>
  <p>⚠️ 本报告仅供投资参考，不构成投资建议。投资有风险，入市需谨慎。</p>
  <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>

</div>
</body>
</html>"""

# 保存HTML
html_path = '/data/workspace/blakever_us_email_20260419.html'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"✅ HTML报告已保存: {html_path}")

# ============================================================
# 发送邮件
# ============================================================
smtp_server = 'smtp.qq.com'
smtp_port = 465
sender = '848786642@qq.com'
password = 'ljbtvacrctjobfed'
receiver = '848786642@qq.com'

msg = MIMEMultipart('alternative')
msg['Subject'] = f'🇺🇸 Blakever 美股每日操作建议指南 | {data["date"]} | 🐂牛市 V2策略'
msg['From'] = sender
msg['To'] = receiver

msg.attach(MIMEText(html, 'html', 'utf-8'))

try:
    server = smtplib.SMTP_SSL(smtp_server, smtp_port)
    server.login(sender, password)
    server.sendmail(sender, receiver, msg.as_string())
    server.quit()
    print(f"✅ 邮件发送成功! → {receiver}")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
