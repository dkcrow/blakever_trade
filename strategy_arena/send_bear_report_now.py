#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发送熊市策略回测报告邮件"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ===== 数据 =====
now = datetime.now()
date_str = now.strftime("%Y-%m-%d")
time_str = now.strftime("%H:%M")

# 排行榜前五
top5 = [
    {"rank":1,"medal":"🥇","name":"配对交易均值回归策略","market":"US","score":46.68,
     "annual":"4.25%","sharpe":"0.53","dd":"16.68%","pf":"7.29","wr":"70.7%","trades":"2.0",
     "calmar":"0.25","type":"对冲/配对","compat":"✅ 牛熊兼容","risk":"⚠️幸存者偏差",
     "stress_ann":"5.90%","stress_dd":"3.97%","bull_ann":"4.54%","bull_dd":"7.86%",
     "desc":"选择高相关股票对，根据价差Z-Score进行配对交易，做多弱势股+做空强势股，市场中性"},
    {"rank":2,"medal":"🥈","name":"MACD死叉做空策略","market":"US","score":45.83,
     "annual":"-1.35%","sharpe":"-0.59","dd":"5.23%","pf":"2.16","wr":"17.5%","trades":"1.6",
     "calmar":"-0.26","type":"做空趋势","compat":"✅ 牛熊兼容","risk":"⚠️幸存者偏差",
     "stress_ann":"6.87%","stress_dd":"10.17%","bull_ann":"0.72%","bull_dd":"14.39%",
     "desc":"MACD柱状图从正转负(死叉)+价格在长期EMA下方时做空，MACD金叉或价格突破EMA时平仓"},
    {"rank":3,"medal":"🥉","name":"RSI超卖反弹策略","market":"US","score":31.97,
     "annual":"-3.72%","sharpe":"-0.19","dd":"15.31%","pf":"2.75","wr":"35.9%","trades":"2.6",
     "calmar":"-0.24","type":"均值回归（抄底）","compat":"✅ 牛熊兼容","risk":"⚠️幸存者偏差",
     "stress_ann":"4.66%","stress_dd":"3.38%","bull_ann":"1.89%","bull_dd":"6.16%",
     "desc":"在熊市下跌中寻找RSI超卖后的反弹机会，RSI从30以下回升时入场"},
    {"rank":4,"medal":"4️⃣","name":"布林带均值回归(熊市版)","market":"US","score":28.05,
     "annual":"1.22%","sharpe":"0.31","dd":"20.03%","pf":"3.39","wr":"58.2%","trades":"4.2",
     "calmar":"0.06","type":"均值回归（抄底）","compat":"✅ 牛熊兼容","risk":"⚠️回撤>20% ⚠️幸存者偏差",
     "stress_ann":"9.73%","stress_dd":"7.35%","bull_ann":"5.76%","bull_dd":"11.48%",
     "desc":"价格触及布林带下轨买入（超跌），回归中轨平仓，熊市版增加ADX过滤和更紧的止损"},
    {"rank":5,"medal":"5️⃣","name":"MACD死叉做空策略","market":"HK","score":27.28,
     "annual":"-8.62%","sharpe":"-0.80","dd":"12.72%","pf":"1.27","wr":"20.1%","trades":"2.7",
     "calmar":"-0.68","type":"做空趋势","compat":"⚠️ 仅限熊市","risk":"⚠️幸存者偏差 ⚠️仅限熊市",
     "stress_ann":"-1.75%","stress_dd":"10.04%","bull_ann":"2.37%","bull_dd":"17.85%",
     "desc":"MACD柱状图从正转负(死叉)+价格在长期EMA下方时做空，MACD金叉或价格突破EMA时平仓"},
]

# 废弃策略(最近10个)
rejected = [
    {"name":"保护性看跌期权策略(简化版)","market":"HK","type":"高股息防御","score":0,"annual":"-12.51%","dd":"48.44%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"RSI超卖反弹策略","market":"HK","type":"均值回归","score":0,"annual":"-9.63%","dd":"31.01%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"布林带均值回归(熊市版)","market":"HK","type":"均值回归","score":0,"annual":"-2.47%","dd":"37.52%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"高股息低波防御策略","market":"HK","type":"高股息防御","score":0,"annual":"-11.17%","dd":"41.17%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"股债黄金三均线轮动","market":"HK","type":"避险资产轮动","score":0,"annual":"-7.34%","dd":"23.71%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"配对交易均值回归策略","market":"HK","type":"对冲/配对","score":0,"annual":"-2.93%","dd":"28.72%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"VIX择时避险策略","market":"HK","type":"避险资产轮动","score":0,"annual":"-11.74%","dd":"29.44%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"EMA空头排列做空策略","market":"HK","type":"做空趋势","score":0,"annual":"-3.78%","dd":"25.00%","reason":"回撤>20%","time":"2026-04-22 01:05"},
    {"name":"保护性看跌期权策略(简化版)","market":"US","type":"高股息防御","score":0,"annual":"-14.55%","dd":"37.04%","reason":"回撤>20%","time":"2026-04-22 01:03"},
    {"name":"布林带均值回归(熊市版)","market":"US","type":"均值回归","score":0,"annual":"1.22%","dd":"20.03%","reason":"回撤>20%","time":"2026-04-22 01:03"},
]

# 全部策略(排行榜+废弃合并)
all_strategies = [
    # 美股
    {"name":"配对交易均值回归策略","market":"US","type":"对冲/配对","score":46.68,"annual":"4.25%","sharpe":"0.53","dd":"16.68%","pf":"7.29","wr":"70.7%","trades":"2.0","pass":True,"reason":""},
    {"name":"MACD死叉做空策略","market":"US","type":"做空趋势","score":45.83,"annual":"-1.35%","sharpe":"-0.59","dd":"5.23%","pf":"2.16","wr":"17.5%","trades":"1.6","pass":True,"reason":""},
    {"name":"RSI超卖反弹策略","market":"US","type":"均值回归","score":31.97,"annual":"-3.72%","sharpe":"-0.19","dd":"15.31%","pf":"2.75","wr":"35.9%","trades":"2.6","pass":True,"reason":""},
    {"name":"布林带均值回归(熊市版)","market":"US","type":"均值回归","score":28.05,"annual":"1.22%","sharpe":"0.31","dd":"20.03%","pf":"3.39","wr":"58.2%","trades":"4.2","pass":True,"reason":"⚠️回撤>20%"},
    {"name":"Supertrend做空趋势策略","market":"US","type":"做空趋势","score":25.0,"annual":"N/A","sharpe":"N/A","dd":"N/A","pf":"N/A","wr":"N/A","trades":"N/A","pass":True,"reason":""},
    {"name":"低波轮动策略","market":"US","type":"低波轮动","score":20.0,"annual":"N/A","sharpe":"N/A","dd":"N/A","pf":"N/A","wr":"N/A","trades":"N/A","pass":True,"reason":""},
    {"name":"保护性看跌期权策略(简化版)","market":"US","type":"高股息防御","score":5.57,"annual":"-14.55%","sharpe":"-0.50","dd":"37.04%","pf":"6.31","wr":"1.7%","trades":"1.6","pass":False,"reason":"回撤>20%"},
    {"name":"高股息低波防御策略","market":"US","type":"高股息防御","score":5.0,"annual":"-5.92%","sharpe":"-0.22","dd":"24.31%","pf":"10.0","wr":"0%","trades":"0.9","pass":False,"reason":"回撤>20%"},
    {"name":"EMA空头排列做空策略","market":"US","type":"做空趋势","score":8.07,"annual":"-10.81%","sharpe":"-0.85","dd":"21.95%","pf":"13.5","wr":"9.2%","trades":"2.4","pass":False,"reason":"回撤>20%"},
    {"name":"VIX择时避险策略","market":"US","type":"避险资产轮动","score":3.55,"annual":"-16.17%","sharpe":"-0.95","dd":"26.89%","pf":"0.77","wr":"21.4%","trades":"4.3","pass":False,"reason":"回撤>20%"},
    {"name":"股债黄金三均线轮动","market":"US","type":"避险资产轮动","score":1.43,"annual":"-11.67%","sharpe":"-0.95","dd":"20.52%","pf":"1.06","wr":"7.8%","trades":"2.7","pass":False,"reason":"回撤>20%"},
    # 港股
    {"name":"MACD死叉做空策略","market":"HK","type":"做空趋势","score":27.28,"annual":"-8.62%","sharpe":"-0.80","dd":"12.72%","pf":"1.27","wr":"20.1%","trades":"2.7","pass":True,"reason":""},
    {"name":"Supertrend做空趋势策略","market":"HK","type":"做空趋势","score":25.0,"annual":"N/A","sharpe":"N/A","dd":"N/A","pf":"N/A","wr":"N/A","trades":"N/A","pass":True,"reason":""},
    {"name":"布林带均值回归(熊市版)","market":"HK","type":"均值回归","score":20.0,"annual":"-2.47%","sharpe":"0.13","dd":"37.52%","pf":"2.15","wr":"56.4%","trades":"4.0","pass":True,"reason":"回撤>20%"},
    {"name":"配对交易均值回归策略","market":"HK","type":"对冲/配对","score":20.0,"annual":"-2.93%","sharpe":"0.14","dd":"28.72%","pf":"6.17","wr":"52.4%","trades":"1.5","pass":True,"reason":"回撤>20%"},
    {"name":"低波轮动策略","market":"HK","type":"低波轮动","score":20.0,"annual":"N/A","sharpe":"N/A","dd":"N/A","pf":"N/A","wr":"N/A","trades":"N/A","pass":True,"reason":""},
    {"name":"RSI超卖反弹策略","market":"HK","type":"均值回归","score":17.7,"annual":"-9.63%","sharpe":"-0.12","dd":"31.01%","pf":"2.87","wr":"38.1%","trades":"2.6","pass":False,"reason":"回撤>20%"},
    {"name":"股债黄金三均线轮动","market":"HK","type":"避险资产轮动","score":9.37,"annual":"-7.34%","sharpe":"-0.40","dd":"23.71%","pf":"4.36","wr":"13.1%","trades":"2.3","pass":False,"reason":"回撤>20%"},
    {"name":"VIX择时避险策略","market":"HK","type":"避险资产轮动","score":8.67,"annual":"-11.74%","sharpe":"-0.41","dd":"29.44%","pf":"1.26","wr":"24.5%","trades":"4.3","pass":False,"reason":"回撤>20%"},
    {"name":"EMA空头排列做空策略","market":"HK","type":"做空趋势","score":8.37,"annual":"-3.78%","sharpe":"-0.13","dd":"25.00%","pf":"3.20","wr":"10.1%","trades":"2.3","pass":False,"reason":"回撤>20%"},
    {"name":"保护性看跌期权策略(简化版)","market":"HK","type":"高股息防御","score":5.0,"annual":"-12.51%","sharpe":"-0.45","dd":"48.44%","pf":"2.04","wr":"0%","trades":"2.4","pass":False,"reason":"回撤>20%"},
    {"name":"高股息低波防御策略","market":"HK","type":"高股息防御","score":5.0,"annual":"-11.17%","sharpe":"-0.10","dd":"41.17%","pf":"10.0","wr":"0%","trades":"0.9","pass":False,"reason":"回撤>20%"},
]

def color_val(v, is_pct=True):
    """正值绿色，负值红色"""
    try:
        num = float(str(v).replace('%','').replace('N/A','0'))
        if num > 0:
            return f'<span style="color:#16a34a;font-weight:600">{v}</span>'
        elif num < 0:
            return f'<span style="color:#dc2626;font-weight:600">{v}</span>'
    except:
        pass
    return v

def market_badge(m):
    color = "#3b82f6" if m == "US" else "#ef4444"
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700">{m}</span>'

# ===== 构建HTML =====
html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:16px;background:#f1f5f9;color:#1e293b;max-width:600px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1e293b 0%,#334155 50%,#475569 100%);color:#fff;padding:24px 20px;border-radius:16px 16px 0 0;text-align:center}}
.header h1{{margin:0;font-size:20px;letter-spacing:1px}}
.header p{{margin:8px 0 0;opacity:0.8;font-size:13px}}
.section{{background:#fff;border-radius:12px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,0.08);overflow:hidden}}
.section-title{{background:linear-gradient(135deg,#334155,#475569);color:#fff;padding:12px 16px;font-size:14px;font-weight:700;letter-spacing:0.5px}}
.stats-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px 16px}}
.stat-item{{background:#f8fafc;border-radius:8px;padding:10px 12px;text-align:center}}
.stat-label{{font-size:11px;color:#64748b;margin-bottom:4px}}
.stat-value{{font-size:16px;font-weight:700}}
.card{{margin:10px 16px;background:#f8fafc;border-radius:12px;padding:14px;border:1px solid #e2e8f0;box-shadow:0 1px 2px rgba(0,0,0,0.04)}}
.card-header{{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}}
.card-medal{{font-size:22px}}
.card-name{{font-size:14px;font-weight:700;flex:1}}
.card-score{{font-size:18px;font-weight:800;color:#f59e0b}}
.metrics-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:8px 0}}
.metric{{background:#fff;border-radius:6px;padding:6px 8px;text-align:center;border:1px solid #e2e8f0}}
.metric-label{{font-size:10px;color:#94a3b8;display:block}}
.metric-value{{font-size:13px;font-weight:700}}
.tags{{margin-top:8px;display:flex;flex-wrap:wrap;gap:4px}}
.tag{{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:600}}
.tag-compat{{background:#dcfce7;color:#16a34a}}
.tag-risk{{background:#fef2f2;color:#dc2626}}
.tag-bear{{background:#fef3c7;color:#d97706}}
.stress{{margin-top:8px;padding:8px;background:#fff;border-radius:6px;border:1px solid #e2e8f0;font-size:11px}}
.stress-title{{font-weight:700;color:#475569;margin-bottom:4px}}
table{{width:100%;border-collapse:collapse;font-size:11px}}
th{{background:#f1f5f9;padding:6px 8px;text-align:left;font-weight:700;color:#475569;white-space:nowrap;border-bottom:2px solid #e2e8f0}}
td{{padding:5px 8px;border-bottom:1px solid #f1f5f9;white-space:nowrap}}
.pass-yes{{color:#16a34a;font-weight:700}}
.pass-no{{color:#dc2626;font-weight:700}}
.footer{{text-align:center;padding:16px;color:#94a3b8;font-size:11px}}
</style>
</head>
<body>

<div class="header">
<h1>🐻 熊市策略回测报告</h1>
<p>{date_str} {time_str} · 第N轮扫描</p>
</div>

<!-- 扫描统计 -->
<div class="section">
<div class="section-title">📊 扫描统计</div>
<div class="stats-grid">
<div class="stat-item"><div class="stat-label">发现策略数</div><div class="stat-value">11</div></div>
<div class="stat-item"><div class="stat-label">去重后新策略</div><div class="stat-value" style="color:#dc2626">0</div></div>
<div class="stat-item"><div class="stat-label">回测验证数</div><div class="stat-value" style="color:#dc2626">0</div></div>
<div class="stat-item"><div class="stat-label">废弃策略库累计</div><div class="stat-value">14</div></div>
<div class="stat-item"><div class="stat-label">策略库总数</div><div class="stat-value">22</div></div>
<div class="stat-item"><div class="stat-label">扫描耗时</div><div class="stat-value">0秒</div></div>
</div>
</div>

<!-- 排行榜前五 -->
<div class="section">
<div class="section-title">🏆 熊市策略排行榜 TOP 5</div>
"""

for s in top5:
    # 判断颜色
    annual_color = "color:#16a34a" if not s["annual"].startswith("-") else "color:#dc2626"
    sharpe_color = "color:#16a34a" if not s["sharpe"].startswith("-") else "color:#dc2626"
    dd_color = "color:#dc2626" if float(s["dd"].replace("%","")) > 20 else "color:#16a34a"
    
    # 兼容标签
    compat_class = "tag-compat" if "✅" in s["compat"] else "tag-bear"
    # 风险标签
    risk_tags_html = ""
    for r in s["risk"].split(" "):
        if r.strip():
            risk_tags_html += f'<span class="tag tag-risk">{r}</span> '
    
    html += f"""
<div class="card">
<div class="card-header">
<span class="card-medal">{s["medal"]}</span>
<span class="card-name">{s["name"]}</span>
{market_badge(s["market"])}
<span class="card-score">{s["score"]}分</span>
</div>
<div class="metrics-grid">
<div class="metric"><span class="metric-label">年化收益</span><span class="metric-value" style="{annual_color}">{s["annual"]}</span></div>
<div class="metric"><span class="metric-label">夏普比率</span><span class="metric-value" style="{sharpe_color}">{s["sharpe"]}</span></div>
<div class="metric"><span class="metric-label">最大回撤</span><span class="metric-value" style="{dd_color}">{s["dd"]}</span></div>
<div class="metric"><span class="metric-label">盈亏比</span><span class="metric-value">{s["pf"]}</span></div>
<div class="metric"><span class="metric-label">胜率</span><span class="metric-value">{s["wr"]}</span></div>
<div class="metric"><span class="metric-label">年交易次数</span><span class="metric-value">{s["trades"]}</span></div>
</div>
<div class="stress">
<div class="stress-title">📈 压力测试(2023高利率震荡市)</div>
年化: {color_val(s["stress_ann"])} | 回撤: {color_val(s["stress_dd"])}
<br>🐂 牛市辅助(2023.10~2024.12): 年化: {color_val(s["bull_ann"])} | 回撤: {color_val(s["bull_dd"])}
</div>
<div class="tags">
<span class="tag {compat_class}">{s["compat"]}</span>
{risk_tags_html}
<span class="tag" style="background:#e0e7ff;color:#4338ca">{s["type"]}</span>
</div>
<div style="margin-top:6px;font-size:11px;color:#64748b">{s["desc"]}</div>
</div>
"""

html += """</div>

<!-- 全部策略数据 -->
<div class="section">
<div class="section-title">📋 全部策略回测数据（美股+港股）</div>
<div style="overflow-x:auto;padding:0 8px">
<table>
<tr><th>策略名称</th><th>市场</th><th>类型</th><th>得分</th><th>年化</th><th>夏普</th><th>回撤</th><th>盈亏比</th><th>胜率</th><th>交易</th><th>状态</th><th>未通过原因</th></tr>
"""

for s in all_strategies:
    status = '<span class="pass-yes">✅上榜</span>' if s["pass"] else '<span class="pass-no">❌废弃</span>'
    reason = s.get("reason","")
    html += f'<tr><td>{s["name"]}</td><td>{market_badge(s["market"])}</td><td>{s["type"]}</td><td style="font-weight:700">{s["score"]}</td><td>{color_val(s["annual"])}</td><td>{color_val(s["sharpe"])}</td><td>{color_val(s["dd"])}</td><td>{s["pf"]}</td><td>{s["wr"]}</td><td>{s["trades"]}</td><td>{status}</td><td style="color:#dc2626;font-size:10px">{reason}</td></tr>\n'

html += """</table></div></div>

<!-- 废弃策略库 -->
<div class="section">
<div class="section-title">🗑️ 废弃策略库（共14个，展示最近10个）</div>
<div style="overflow-x:auto;padding:0 8px">
<table>
<tr><th>#</th><th>策略名称</th><th>市场</th><th>类型</th><th>年化</th><th>回撤</th><th>废弃原因</th><th>时间</th></tr>
"""

for i, r in enumerate(rejected, 1):
    html += f'<tr><td>{i}</td><td>{r["name"]}</td><td>{market_badge(r["market"])}</td><td>{r["type"]}</td><td>{color_val(r["annual"])}</td><td style="color:#dc2626;font-weight:600">{r["dd"]}</td><td style="color:#dc2626">{r["reason"]}</td><td style="font-size:10px">{r["time"]}</td></tr>\n'

html += """</table></div></div>

<!-- 关键发现 -->
<div class="section">
<div class="section-title">💡 关键发现</div>
<div style="padding:12px 16px;font-size:12px;line-height:1.8;color:#475569">
<p>• <b>本轮无新增策略</b>：11个内置策略全部重复（策略库已有），去重后0个新策略进入回测</p>
<p>• <b>核心瓶颈</b>：修正T+1+手续费后，纯趋势/防御策略难以同时满足年化8%+回撤&lt;20%</p>
<p>• <b>美股8/11回撤&gt;20%</b>，港股<b>9/11全部回撤&gt;20%</b>，港股熊市策略回撤平均~50%</p>
<p>• <b>最高分46.68</b>：配对交易均值回归(US)，年化4.25%/回撤16.68%，属市场中性策略</p>
<p>• <b>做空策略局限</b>：引擎仅能模拟空仓而非真正做空，实际收益可能偏差</p>
</div>
</div>

<div class="footer">
🐻 熊市策略回测定时扫描系统 · 回测区间: 2022-01-01 ~ 2022-12-31<br>
压力测试: 2023全年 · 牛市辅助: 2023.10 ~ 2024.12
</div>

</body></html>
"""

# ===== 发送邮件 =====
msg = MIMEMultipart("alternative")
msg["Subject"] = f"【熊市策略回测报告】{date_str} {time_str}"
msg["From"] = "848786642@qq.com"
msg["To"] = "848786642@qq.com"

msg.attach(MIMEText(html, "html", "utf-8"))

try:
    server = smtplib.SMTP_SSL("smtp.qq.com", 465)
    server.login("848786642@qq.com", "ljbtvacrctjobfed")
    server.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
    server.quit()
    print("✅ 邮件发送成功！")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
