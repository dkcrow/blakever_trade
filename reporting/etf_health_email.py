#!/usr/bin/env python3
"""ETF池健康检查 - 独立邮件发送 (每日08:00执行)"""
import sys, os
from pathlib import Path

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

from reporting.etf_pool_health import run_health_check, generate_html, should_alert
from reporting.generate_qmt_report import QMT_POOL, QMT_NAMES
from datetime import datetime

print("=" * 60)
print(f"ETF池健康检查 [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
print("=" * 60)

results = run_health_check(QMT_POOL, QMT_NAMES)
html_fragment = generate_html(results, QMT_POOL)

warn_count = len(results['warn'])
dead_count = len(results['dead'])
total = results['total']
alert = should_alert(results)

status_line = '🟢 健康' if not alert else f'🔴 {warn_count}只预警'
if dead_count > 0:
    status_line += f' / {dead_count}只无数据'

html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>ETF池健康检查</title></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:700px;margin:0 auto;padding:20px;background:#f8f9fa;">
<div style="text-align:center;margin-bottom:15px;">
    <h2 style="color:#1F4E79;margin:0;">🏥 ETF池健康检查</h2>
    <p style="color:#888;font-size:12px;">{datetime.now().strftime('%Y-%m-%d %H:%M')} | 池{total}只 | {status_line}</p>
</div>
{html_fragment}
<div style="margin-top:20px;padding:10px;background:#E8EAF6;border-radius:6px;font-size:11px;color:#555;">
    <b>评分标准:</b> 60日趋势为负 / 夏普<0.3 → 预警 | 无数据/成交量持续为0 → 死标<br>
    <b>下期建议:</b> 预警ETF若连续3天未改善, 建议从池中移除
</div>
</body>
</html>"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 从 generate_qmt_report 复用 SMTP 配置
SENDER = '848786642@qq.com'
RECEIVER = '848786642@qq.com'
PASSWORD = 'ljbtvacrctjobfed'
SMTP_SERVER, SMTP_PORT = 'smtp.qq.com', 465

for attempt in range(3):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"{'⚠️' if alert else '✅'} ETF池健康检查 [{datetime.now().strftime('%m/%d')}] - {status_line}"
        msg['From'] = SENDER
        msg['To'] = RECEIVER
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as srv:
            srv.login(SENDER, PASSWORD)
            srv.sendmail(SENDER, RECEIVER, msg.as_string())
        print(f"邮件已发送 (attempt {attempt+1})")
        break
    except Exception as e:
        print(f"SMTP attempt {attempt+1} failed: {e}")
        if attempt == 2:
            # Fallback: save HTML locally
            local_path = Path(__file__).parent / 'template' / f'ETF健康检查_{datetime.now().strftime("%Y%m%d_%H%M")}.html'
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"邮件发送失败, 已保存到: {local_path}")
        import time; time.sleep(3)

print(f"OK: {len(results['ok'])}只 预警:{warn_count}只 死标:{dead_count}只 → 邮件已发送")
