#!/usr/bin/env python3
"""Blakever 每日美股操作建议指南邮件发送脚本"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

# 邮件配置
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "848786642@qq.com"
PASSWORD = "ljbtvacrctjobfed"
RECEIVER = "848786642@qq.com"

# 读取HTML模板
with open("/data/workspace/blakever-us-email-20260418.html", "r", encoding="utf-8") as f:
    html_content = f.read()

# 读取Markdown报告
with open("/data/workspace/blakever-us-daily-guide-20260418.md", "r", encoding="utf-8") as f:
    md_content = f.read()

# 构建邮件
msg = MIMEMultipart("mixed")
msg["Subject"] = f"📊 Blakever 每日美股操作建议指南 | 2026-04-18 | 趋势牛市·置信度75%"
msg["From"] = SENDER
msg["To"] = RECEIVER
msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")

# HTML正文
html_part = MIMEText(html_content, "html", "utf-8")
msg.attach(html_part)

# 附件：Markdown报告
md_attachment = MIMEBase("text", "markdown")
md_attachment.set_payload(md_content.encode("utf-8"))
encoders.encode_base64(md_attachment)
md_attachment.add_header("Content-Disposition", "attachment", filename="blakever-us-daily-guide-20260418.md")
msg.attach(md_attachment)

# 发送邮件
try:
    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
    server.login(SENDER, PASSWORD)
    server.sendmail(SENDER, RECEIVER, msg.as_string())
    server.quit()
    print("✅ 邮件发送成功！")
    print(f"   收件人: {RECEIVER}")
    print(f"   主题: {msg['Subject']}")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
    raise
