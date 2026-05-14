#!/usr/bin/env python3
"""发送废弃策略回测报告邮件"""
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "848786642@qq.com"
PASSWORD = "ljbtvacrctjobfed"
RECEIVER = "848786642@qq.com"

# 加载数据
with open('/data/workspace/strategy_arena/rejected_strategies.json', 'r', encoding='utf-8') as f:
    all_rejected = json.load(f)

# 按市场分组
us_strategies = [s for s in all_rejected if s.get('market') == 'us']
hk_strategies = [s for s in all_rejected if s.get('market') == 'hk']

def dd_color(val):
    """回撤颜色：>40%红色，>25%橙色，其他绿色"""
    if val > 40:
        return '#e74c3c'
    elif val > 25:
        return '#e67e22'
    else:
        return '#27ae60'

def score_color(val):
    """得分颜色"""
    if val >= 80:
        return '#27ae60'
    elif val >= 50:
        return '#e67e22'
    else:
        return '#e74c3c'

def return_color(val):
    """收益率颜色"""
    if val > 0:
        return '#27ae60'
    else:
        return '#e74c3c'

def build_table(strategies, market_label):
    rows = ''
    for i, s in enumerate(strategies, 1):
        dd = s.get('max_drawdown', 0)
        ret = s.get('annual_return', 0)
        score = s.get('total_score', 0)
        reason = s.get('rejection_reason', '')
        rejected_time = s.get('rejected_time', '')
        
        # 评分明细
        sd = s.get('score_detail', {})
        detail_parts = []
        if sd.get('annual_return_score', 0) > 0:
            detail_parts.append(f"年化贡献{sd['annual_return_score']:.1f}")
        if sd.get('sharpe_score', 0) > 0:
            detail_parts.append(f"夏普贡献{sd['sharpe_score']:.1f}")
        if sd.get('max_drawdown_score', 0) > 0:
            detail_parts.append(f"回撤贡献{sd['max_drawdown_score']:.1f}")
        if sd.get('profit_factor_score', 0) > 0:
            detail_parts.append(f"盈亏比贡献{sd['profit_factor_score']:.1f}")
        if sd.get('win_rate_score', 0) > 0:
            detail_parts.append(f"胜率贡献{sd['win_rate_score']:.1f}")
        if sd.get('survivorship_penalty', 0) != 0:
            detail_parts.append(f"生存偏差{sd['survivorship_penalty']:.1f}")
        detail_str = '; '.join(detail_parts) if detail_parts else '无得分项'
        
        rows += f'''
        <tr>
            <td style="text-align:center;">{i}</td>
            <td><b>{s.get('strategy_name', 'Unknown')}</b><br><span style="font-size:11px;color:#888;">{s.get('strategy_type', '')} | {s.get('fingerprint_short', '')}</span></td>
            <td style="text-align:center;color:{score_color(score)};font-weight:bold;">{score:.2f}</td>
            <td style="text-align:center;color:{return_color(ret)};">{ret:.2f}%</td>
            <td style="text-align:center;">{s.get('sharpe', 0):.2f}</td>
            <td style="text-align:center;color:{dd_color(dd)};font-weight:bold;">{dd:.2f}%</td>
            <td style="text-align:center;">{s.get('profit_factor', 0):.2f}</td>
            <td style="text-align:center;">{s.get('win_rate', 0):.1f}%</td>
            <td style="text-align:center;">{s.get('avg_trades_per_year', 0):.1f}</td>
            <td style="text-align:center;">{s.get('n_stocks', 0)}</td>
            <td style="color:#e74c3c;font-size:12px;">{reason}</td>
            <td style="font-size:11px;color:#888;">{rejected_time}</td>
        </tr>'''
    
    return f'''
    <h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px;">
        🇺🇸 {market_label} 废弃策略列表 ({len(strategies)}个)
    </h2>
    <table style="border-collapse:collapse;width:100%;font-size:13px;">
        <thead>
            <tr style="background:#2c3e50;color:white;">
                <th style="padding:8px;">#</th>
                <th style="padding:8px;">策略名称</th>
                <th style="padding:8px;">得分</th>
                <th style="padding:8px;">年化收益</th>
                <th style="padding:8px;">夏普比率</th>
                <th style="padding:8px;">最大回撤</th>
                <th style="padding:8px;">盈亏比</th>
                <th style="padding:8px;">胜率</th>
                <th style="padding:8px;">年交易</th>
                <th style="padding:8px;">股票数</th>
                <th style="padding:8px;">废弃原因</th>
                <th style="padding:8px;">废弃时间</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>'''

# 统计概要
us_dd_avg = sum(s.get('max_drawdown', 0) for s in us_strategies) / len(us_strategies) if us_strategies else 0
hk_dd_avg = sum(s.get('max_drawdown', 0) for s in hk_strategies) / len(hk_strategies) if hk_strategies else 0
us_ret_avg = sum(s.get('annual_return', 0) for s in us_strategies) / len(us_strategies) if us_strategies else 0
hk_ret_avg = sum(s.get('annual_return', 0) for s in hk_strategies) / len(hk_strategies) if hk_strategies else 0

# 废弃原因统计
reason_counts = {}
for s in all_rejected:
    r = s.get('rejection_reason', '')
    for part in r.split('; '):
        part = part.strip()
        if part:
            reason_counts[part] = reason_counts.get(part, 0) + 1

reason_stats = ''.join(f'<span style="display:inline-block;background:#f39c12;color:white;padding:4px 12px;border-radius:15px;margin:4px;font-size:13px;">{k}: {v}次</span>' for k, v in sorted(reason_counts.items(), key=lambda x: -x[1]))

html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Microsoft YaHei','Segoe UI',Arial,sans-serif;background:#f5f6fa;margin:0;padding:20px;">
<div style="max-width:1200px;margin:0 auto;background:white;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">

<!-- 头部 -->
<div style="background:linear-gradient(135deg,#2c3e50,#3498db);color:white;padding:30px;">
    <h1 style="margin:0;font-size:24px;">🗑️ 策略回测 · 废弃策略报告</h1>
    <p style="margin:8px 0 0;opacity:0.85;font-size:14px;">
        扫描时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 
        废弃策略总数：{len(all_rejected)}个（美股{len(us_strategies)} + 港股{len(hk_strategies)}）
    </p>
</div>

<!-- 概览卡片 -->
<div style="display:flex;flex-wrap:wrap;padding:20px;gap:15px;">
    <div style="flex:1;min-width:150px;background:#fff3e0;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#e67e22;">{len(all_rejected)}</div>
        <div style="font-size:12px;color:#888;">废弃策略总数</div>
    </div>
    <div style="flex:1;min-width:150px;background:#ffebee;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#e74c3c;">{us_dd_avg:.1f}%</div>
        <div style="font-size:12px;color:#888;">美股平均回撤</div>
    </div>
    <div style="flex:1;min-width:150px;background:#ffebee;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#e74c3c;">{hk_dd_avg:.1f}%</div>
        <div style="font-size:12px;color:#888;">港股平均回撤</div>
    </div>
    <div style="flex:1;min-width:150px;background:#e8f5e9;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#27ae60;">{us_ret_avg:.2f}%</div>
        <div style="font-size:12px;color:#888;">美股平均年化</div>
    </div>
    <div style="flex:1;min-width:150px;background:#e8f5e9;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#27ae60;">{hk_ret_avg:.2f}%</div>
        <div style="font-size:12px;color:#888;">港股平均年化</div>
    </div>
</div>

<!-- 废弃原因统计 -->
<div style="padding:0 20px 20px;">
    <h3 style="color:#2c3e50;">📊 废弃原因分布</h3>
    <div>{reason_stats}</div>
</div>

<!-- 美股表格 -->
<div style="padding:0 20px 20px;overflow-x:auto;">
    {build_table(us_strategies, '美股')}
</div>

<!-- 港股表格 -->
<div style="padding:0 20px 20px;overflow-x:auto;">
    {build_table(hk_strategies, '港股')}
</div>

<!-- 核心洞察 -->
<div style="padding:0 20px 20px;">
    <div style="background:#e8f5e9;border-left:4px solid #27ae60;padding:15px;border-radius:0 8px 8px 0;">
        <h3 style="margin:0 0 8px;color:#2c3e50;">💡 核心洞察</h3>
        <ul style="margin:0;padding-left:20px;font-size:13px;color:#555;">
            <li>修正T+1+手续费后，所有纯趋势策略均无法同时满足年化≥15% + 最大回撤≤25%</li>
            <li>美股主要瓶颈：回撤过大（平均{us_dd_avg:.1f}%），8/10策略因回撤>25%被否决</li>
            <li>港股趋势策略表现更差：平均回撤{hk_dd_avg:.1f}%，平均年化仅{hk_ret_avg:.2f}%</li>
            <li>RSI回调买入策略回撤极低(0.34%/0.59%)但年化几乎为零，属于"躺平"策略</li>
            <li>底仓50%组合模式可能是唯一出路（参考此前Supertrend+底仓50%=年化11.64%/夏普1.07）</li>
        </ul>
    </div>
</div>

<!-- 页脚 -->
<div style="background:#f8f9fa;padding:15px 20px;text-align:center;color:#888;font-size:12px;border-top:1px solid #eee;">
    Blakever 策略回测系统 · 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>

</div>
</body>
</html>'''

# 发送邮件
msg = MIMEMultipart("mixed")
msg["Subject"] = f"🗑️ 策略回测废弃策略报告 ({len(all_rejected)}个) - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
msg["From"] = SENDER
msg["To"] = RECEIVER
msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
msg.attach(MIMEText(html, "html", "utf-8"))

# 同时附上JSON数据作为附件
att = MIMEText(json.dumps(all_rejected, ensure_ascii=False, indent=2), "plain", "utf-8")
att.add_header("Content-Disposition", "attachment", filename="rejected_strategies.json")
msg.attach(att)

with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
    server.login(SENDER, PASSWORD)
    server.sendmail(SENDER, RECEIVER, msg.as_string())

print(f"✅ 邮件已发送至 {RECEIVER}")
print(f"   包含 {len(us_strategies)} 个美股废弃策略 + {len(hk_strategies)} 个港股废弃策略")
