#!/usr/bin/env python3
"""Blakever 通用邮件发送脚本"""
import smtplib, sys, os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "848786642@qq.com"
PASSWORD = "ljbtvacrctjobfed"
RECEIVER = "848786642@qq.com"

def send_email(subject, html_file=None, md_file=None, body_text=None):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = RECEIVER
    msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")

    # HTML正文
    if html_file and os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()
        msg.attach(MIMEText(html_content, "html", "utf-8"))
    elif body_text:
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # MD附件
    if md_file and os.path.exists(md_file):
        with open(md_file, "r", encoding="utf-8") as f:
            md_content = f.read()
        att = MIMEText(md_content, "plain", "utf-8")
        att.add_header("Content-Disposition", "attachment", filename=os.path.basename(md_file))
        msg.attach(att)

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, RECEIVER, msg.as_string())
    print(f"✅ 邮件已发送至 {RECEIVER}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True)
    parser.add_argument("--html", help="HTML文件路径")
    parser.add_argument("--md", help="Markdown附件路径")
    parser.add_argument("--body", help="纯文本正文")
    args = parser.parse_args()
    send_email(args.subject, args.html, args.md, args.body)
