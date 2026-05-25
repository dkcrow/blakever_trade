#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, urllib.request, smtplib
from email.mime.text import MIMEText
from datetime import datetime

POSITION_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\current_positions.json'

ETF_NAMES = {
    '588080': '科创50ETF易方达', '513100': '纳指ETF国泰', '159915': '创业板ETF易方达', '518880': '黄金ETF华安'
}

def get_realtime_price(etf_code):
    prefix = 'sh' if etf_code.startswith('5') else 'sz'
    url = f'http://qt.gtimg.cn/q={prefix}{etf_code}'
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            data = r.read().decode('gbk')
            if '~' in data:
                parts = data.split('~')
                if len(parts) > 3:
                    return float(parts[3])
    except:
        pass
    return None

def check_stop_loss():
    alerts = []
    if not os.path.exists(POSITION_FILE):
        print('持仓文件不存在')
        return alerts
    
    with open(POSITION_FILE, 'r', encoding='utf-8') as f:
        positions = json.load(f)
    
    print(f'持仓文件包含 {len(positions)} 只ETF')
    
    for etf, info in positions.items():
        current = get_realtime_price(etf)
        if current is None:
            continue
        
        entry = info.get('entry_price', 0)
        if entry == 0:
            continue
        
        pnl = (current - entry) / entry * 100
        print(f'{etf}: 入场={entry:.3f}, 当前={current:.3f}, 盈亏={pnl:.1f}%')
        
        if pnl <= -8:
            print(f'  => 触发硬止损！')
            alerts.append({
                'etf': etf,
                'name': ETF_NAMES.get(etf, etf),
                'type': '硬止损',
                'entry': entry,
                'current': current,
                'pnl': pnl
            })
        elif pnl > 5:
            max_price = info.get('max_price', entry)
            drawdown = (current - max_price) / max_price * 100
            if drawdown <= -5:
                print(f'  => 触发盈利保护！')
                alerts.append({
                    'etf': etf,
                    'name': ETF_NAMES.get(etf, etf),
                    'type': '盈利保护',
                    'entry': entry,
                    'current': current,
                    'high': max_price,
                    'pnl': pnl
                })
    
    print(f'共触发 {len(alerts)} 只止损')
    return alerts

def send_email(alerts):
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body{{font-family:Arial,sans-serif;padding:20px;background:#f5f5f5}}
.container{{max-width:800px;margin:0 auto;background:white;border-radius:8px;overflow:hidden}}
.header{{background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:30px;text-align:center}}
.content{{padding:30px}}
.alert-box{{background:#fef2f2;border-left:4px solid #ef4444;padding:15px;margin-bottom:20px}}
</style></head><body>
<div class="container">
<div class="header"><h1>拉普拉斯盘中监控报告</h1><p>生成时间：{now_str}</p></div>
<div class="content">
"""
    if alerts:
        html += f'<div class="alert-box"><h3>止损警示（{len(alerts)}只触发）</h3>'
        for a in alerts:
            html += f'<p><strong>{a["etf"]} {a["name"]}</strong> ({a["type"]})<br>入场价：{a["entry"]:.3f} → 当前价：{a["current"]:.3f}（盈亏：{a["pnl"]:.1f}%）</p>'
        html += '</div>'
    else:
        html += '<p>无止损触发。</p>'
    
    html += '</div></div></body></html>'
    
    msg = MIMEText(html, 'html', _charset='utf-8')
    msg['Subject'] = f"[OpenClaw] 拉普拉斯盘中监控 - {now_str}"
    msg['From'] = sender
    msg['To'] = receiver
    
    try:
        server = smtplib.SMTP('smtp.qq.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"邮件发送失败：{e}")
        return False

alerts = check_stop_loss()
if alerts:
    send_email(alerts)
    print('邮件已发送')
else:
    print('无止损触发，不发送邮件')
