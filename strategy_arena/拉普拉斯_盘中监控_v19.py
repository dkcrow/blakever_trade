"""
拉普拉斯盘中监控 v19（使用 laplace_common 公共模块）
正确排版：交易记录含 ETF名称、代码、操作、价格、原因、盈亏
"""
import sys
import os
import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import laplace_common as lc

RANK_HISTORY_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\laplace_rankings_history.json'
TRADES_FILE = r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json'


def generate_html(rankings, rank_changes):
    """生成HTML邮件内容"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    html = f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f8f9fa;margin:0;padding:16px}}
.header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:20px 24px;border-radius:12px 12px 0 0;margin-bottom:0}}
.header h2{{margin:0;font-size:20px;font-weight:700}}
.header p{{margin:4px 0 0;opacity:0.9;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:white;font-size:12px}}
th{{background:#f8f9fa;padding:6px 8px;text-align:left;font-weight:600;color:#374151;border-bottom:2px solid #e5e7eb}}
td{{padding:6px 8px;border-bottom:1px solid #f3f4f6}}
tr:hover{{background:#f9fafb}}
.rank{{font-weight:700;color:#111827}}
.medal{{font-size:14px}}
.name{{color:#374151;white-space:nowrap}}
.code{{color:#6b7280;font-size:11px}}
.score{{color:#059669;font-weight:600}}
.short{{color:#2563eb}}
.long{{color:#7c3aed}}
.price{{color:#111827;font-weight:500}}
.positive{{color:#059669}}
.negative{{color:#dc2626}}
.change-up{{color:#059669;font-size:11px}}
.change-down{{color:#dc2626;font-size:11px}}
.change-none{{color:#6b7280;font-size:11px}}
.footer{{background:#f8f9fa;padding:12px 24px;border-radius:0 0 12px 12px;font-size:11px;color:#6b7280}}
</style></head><body>
<div class="header">
  <h2>拉普拉斯盘中监控</h2>
  <p>更新时间：{now} | 基于动量排名 + 实时价格</p>
</div>
<table>
<tr><th>排名</th><th>ETF名称</th><th>代码</th><th>综合分</th><th>短期</th><th>长期</th><th>实时价</th><th>涨跌幅</th><th>变动</th></tr>
"""
    for i, r in enumerate(rankings):
        code = r['code']
        name = r['name']
        score = r['score']
        short = r['short']
        long = r['long']
        price = r['realtime_price']
        yesterday_close = r['yesterday_close']
        
        diff = rank_changes.get(code, 0)
        if diff > 0:
            rank_change_html = '<span class="change-up">↑+' + str(diff) + '</span>'
        elif diff < 0:
            rank_change_html = '<span class="change-down">↓' + str(diff) + '</span>'
        else:
            rank_change_html = '<span class="change-none">—</span>'
        
        pct_change = lc.calculate_pct_change(price, yesterday_close)
        pct_color = 'positive' if pct_change >= 0 else 'negative'
        pct_sign = '+' if pct_change >= 0 else ''
        
        medal = ''
        if i == 0:
            medal = '<span class="medal">🥇</span> '
        elif i == 1:
            medal = '<span class="medal">🥈</span> '
        elif i == 2:
            medal = '<span class="medal">🥉</span> '
        
        html += f"""
<tr>
  <td class="rank">{medal}{i+1}</td>
  <td class="name">{name}</td>
  <td class="code">{code}</td>
  <td class="score">{score:.2f}</td>
  <td class="short">{short:.2f}</td>
  <td class="long">{long:.2f}</td>
  <td class="price">{price:.3f}</td>
  <td class="{pct_color}">{pct_sign}{pct_change:.2f}%</td>
  <td>{rank_change_html}</td>
</tr>
"""
    
    html += "</table>"
    
    # 交易记录（宽度与排名表一致）
    html += '''
<div style="background:#f8f9fa;padding:16px 24px;border-radius:0 0 12px 12px">
  <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px">近20次交易记录</div>
  <table style="width:100%;border-collapse:collapse;background:white;font-size:11px">
  <tr><th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">日期</th>
      <th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">ETF名称</th>
      <th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">代码</th>
      <th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">操作</th>
      <th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">价格</th>
      <th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">原因</th>
      <th style="padding:4px 6px;text-align:left;background:#f8f9fa;color:#6b7280">盈亏</th></tr>
'''
    
    try:
        with open(TRADES_FILE, 'r', encoding='utf-8') as f:
            trades = json.load(f)
            if isinstance(trades, dict) and 'trades' in trades:
                trades = trades['trades']
            recent_trades = trades[-20:] if len(trades) >= 20 else trades
            recent_trades = list(reversed(recent_trades))
            
            for t in recent_trades:
                date = t.get('date', '')
                code = t.get('etf', '')
                name = t.get('name', '')
                act = t.get('action', '')
                price = t.get('price', 0)
                reason = t.get('reason', '')
                pnl = t.get('pnl_pct')
                
                ac = '#059669' if act == 'BUY' else '#dc2626'
                if pnl is not None:
                    pc = '#059669' if pnl >= 0 else '#dc2626'
                    ps = '+' if pnl >= 0 else ''
                    pnl_str = f"{ps}{pnl:.2f}%"
                else:
                    pc = '#6b7280'
                    pnl_str = '—'
                
                html += f'''
  <tr>
    <td style="padding:4px 6px;color:#374151;white-space:nowrap">{date}</td>
    <td style="padding:4px 6px;color:#111827;white-space:nowrap">{name}</td>
    <td style="padding:4px 6px;color:#6b7280">{code}</td>
    <td style="padding:4px 6px;color:{ac}">{act}</td>
    <td style="padding:4px 6px;color:#111827">{price:.3f}</td>
    <td style="padding:4px 6px;color:#6b7280;font-size:11px;white-space:nowrap">{reason}</td>
    <td style="padding:4px 6px;color:{pc}">{pnl_str}</td>
  </tr>
'''
    except Exception as e:
        print(f'  [WARN] 交易记录: {e}')
    
    html += '''
  </table>
</div>
<div class="footer">
  <p>数据来源：腾讯API + 本地CSV | 决策依据：动量排名</p>
</div>
</body></html>'''
    return html


def send_email(html):
    """发送邮件"""
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = '拉普拉斯盘中监控 ' + datetime.now().strftime('%m-%d %H:%M')
    msg['From'] = '848786642@qq.com'
    msg['To'] = '848786642@qq.com'
    
    try:
        with smtplib.SMTP('smtp.qq.com', 587) as server:
            server.starttls()
            server.login('848786642@qq.com', 'ljbtvacrctjobfed')
            server.send_message(msg)
        print('  [OK] 邮件已发送')
        return True
    except Exception as e:
        print(f'  [ERROR] 邮件失败: {e}')
        return False


if __name__ == '__main__':
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 拉普拉斯盘中监控启动（v19）...")
    
    # 1. 获取实时价格
    print('  获取腾讯API实时价格...')
    prices = lc.get_tencent_realtime_prices()
    print(f'  [OK] 获取 {len(prices)} 只ETF价格')
    
    # 2. 计算排名
    print('  计算动量排名...')
    rankings = lc.get_rankings(prices)
    print(f'  [OK] 共 {len(rankings)} 只ETF')
    
    # 3. 计算排名变动
    print('  计算排名变动...')
    rank_changes = lc.get_rank_change(rankings, RANK_HISTORY_FILE)
    print('  [OK] 变动计算完成')
    
    # 4. 生成HTML
    print('  生成HTML邮件...')
    html = generate_html(rankings, rank_changes)
    print(f'  [OK] HTML长度 {len(html)} 字节')
    
    # 5. 保存调试
    with open(r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\last_email.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    # 6. 发送邮件
    print('  发送邮件...')
    send_email(html)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 任务完成！")
