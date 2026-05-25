#!/usr/bin/env python3
"""Blakever 盘中风控警报邮件发送脚本 - 2026-04-19"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# 邮件配置
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "848786642@qq.com"
PASSWORD = "ljbtvacrctjobfed"
RECEIVER = "848786642@qq.com"

# 构建邮件
msg = MIMEMultipart("alternative")
msg["Subject"] = "【Blakever风控警报】阶梯止盈兜底保护 - AAPL/MSFT/TSLA"
msg["From"] = SENDER
msg["To"] = RECEIVER
msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")

# 风控触发详情
trigger_details = """
<h2 style="color: red;">⚠️ Blakever 盘中风控警报</h2>
<h3>触发时间：2026-04-19 15:00 (Asia/Shanghai)</h3>

<h3 style="color: red;">触发类型：阶梯止盈兜底保护</h3>

<table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
  <tr style="background-color: #f2f2f2;">
    <th>标的代码</th>
    <th>标的名称</th>
    <th>当前价格</th>
    <th>近60日最高价</th>
    <th>最高浮盈(估算)</th>
    <th>当前浮盈(估算)</th>
    <th>利润回吐比例</th>
    <th>触发状态</th>
  </tr>
  <tr style="background-color: #ffe0e0;">
    <td>usAAPL</td>
    <td>苹果</td>
    <td>$270.23</td>
    <td>$289.75</td>
    <td>~$31.75</td>
    <td>~$12.23</td>
    <td><b style="color: red;">61.6%</b></td>
    <td>🔴 已触发</td>
  </tr>
  <tr style="background-color: #ffe0e0;">
    <td>usMSFT</td>
    <td>微软</td>
    <td>$422.79</td>
    <td>$552.23</td>
    <td>~$163.23</td>
    <td>~$33.79</td>
    <td><b style="color: red;">79.3%</b></td>
    <td>🔴 已触发</td>
  </tr>
  <tr style="background-color: #ffe0e0;">
    <td>usTSLA</td>
    <td>特斯拉</td>
    <td>$400.62</td>
    <td>$498.83</td>
    <td>~$123.83</td>
    <td>~$25.62</td>
    <td><b style="color: red;">79.3%</b></td>
    <td>🔴 已触发</td>
  </tr>
  <tr>
    <td>usNVDA</td>
    <td>英伟达</td>
    <td>$201.68</td>
    <td>$212.15</td>
    <td>~$29.15</td>
    <td>~$18.68</td>
    <td>36.3%</td>
    <td>🟢 未触发</td>
  </tr>
  <tr>
    <td>usAVGO</td>
    <td>博通</td>
    <td>$406.54</td>
    <td>$412.95</td>
    <td>~$74.95</td>
    <td>~$68.54</td>
    <td>8.6%</td>
    <td>🟢 未触发</td>
  </tr>
</table>

<h3>VIX 预警检查</h3>
<ul>
  <li>VIX 最新值：<b>17.48</b>（2026-04-17收盘）</li>
  <li>VIX 阈值：35</li>
  <li>状态：<span style="color: green;">🟢 未触发（VIX < 35）</span></li>
</ul>

<h3 style="color: red;">已执行操作</h3>
<ol>
  <li><b>AAPL</b>：立即平仓该标的全部持仓</li>
  <li><b>MSFT</b>：立即平仓该标的全部持仓</li>
  <li><b>TSLA</b>：立即平仓该标的全部持仓</li>
</ol>

<h3>触发前持仓状态</h3>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
  <tr style="background-color: #f2f2f2;">
    <th>标的</th>
    <th>原仓位</th>
    <th>CRO批准仓位</th>
    <th>当前浮盈/亏损</th>
  </tr>
  <tr>
    <td>AAPL</td>
    <td>8.25%总敞口</td>
    <td>CRO压缩后≈2.47%</td>
    <td>~+$12.23/股</td>
  </tr>
  <tr>
    <td>MSFT</td>
    <td>8.25%总敞口</td>
    <td>CRO压缩后≈2.47%</td>
    <td>~+$33.79/股</td>
  </tr>
  <tr>
    <td>TSLA</td>
    <td>8.25%总敞口</td>
    <td>CRO压缩后≈2.47%</td>
    <td>~+$25.62/股</td>
  </tr>
</table>

<h3>风控红线提醒</h3>
<ul>
  <li>🔴 <b>阶梯止盈兜底保护</b>：利润回吐超50%→自动平仓</li>
  <li>本次触发3只标的，均为利润回吐超过50%阈值</li>
</ul>

<hr>
<p style="font-size: 12px; color: #888;">
  本邮件由 Blakever 多智能体投资决策系统自动生成<br>
  报告时间：2026-04-19 15:00:14 +08:00<br>
  数据截止：2026-04-17（最新交易日收盘）<br>
  ⚠️ 投资有风险，决策需谨慎
</p>
"""

html_part = MIMEText(trigger_details, "html", "utf-8")
msg.attach(html_part)

# 发送邮件
try:
    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
    server.login(SENDER, PASSWORD)
    server.sendmail(SENDER, RECEIVER, msg.as_string())
    server.quit()
    print("✅ 风控警报邮件发送成功！")
    print(f"   收件人: {RECEIVER}")
    print(f"   主题: {msg['Subject']}")
except Exception as e:
    print(f"❌ 风控警报邮件发送失败: {e}")
    raise
