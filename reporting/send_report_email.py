#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发送回测报告邮件"""
import smtplib, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

with open('/data/workspace/alpha_factor_enhanced_report.json') as f:
    report = json.load(f)

html = '<html><head><style>'
html += 'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:800px;margin:0 auto;padding:20px;background:#f5f5f5}'
html += 'h1{background:linear-gradient(135deg,#1a237e,#0d47a1);color:white;padding:20px;border-radius:12px;margin-bottom:20px;font-size:22px}'
html += 'h2{color:#1a237e;border-bottom:2px solid #1a237e;padding-bottom:8px;margin-top:30px}'
html += 'h3{color:#0d47a1;margin-top:20px}'
html += 'table{border-collapse:collapse;width:100%;margin:15px 0;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)}'
html += 'th{background:linear-gradient(135deg,#1a237e,#0d47a1);color:white;padding:12px 16px;text-align:left;font-weight:600}'
html += 'td{padding:10px 16px;border-bottom:1px solid #eee}'
html += 'tr:last-child td{border-bottom:none}'
html += 'tr:hover{background:#e3f2fd}'
html += '.positive{color:#2e7d32;font-weight:bold}'
html += '.negative{color:#c62828;font-weight:bold}'
html += '.card{background:white;border-radius:12px;padding:20px;margin:15px 0;box-shadow:0 2px 12px rgba(0,0,0,0.08)}'
html += '.warning{background:#fff3e0;border-left:4px solid #ff9800;padding:12px 16px;margin:15px 0;border-radius:4px;color:#e65100}'
html += '.success{background:#e8f5e9;border-left:4px solid #4caf50;padding:12px 16px;margin:15px 0;border-radius:4px;color:#2e7d32}'
html += '.footer{text-align:center;color:#999;font-size:12px;margin-top:30px;padding:20px}'
html += '@media(max-width:600px){.metric{width:90%!important}}'
html += '</style></head><body>'
html += '<h1>📋 Alpha因子增强策略 - 回测报告</h1>'

# 配置卡片
html += '<div class="card"><h3>📐 策略配置</h3>'
html += '<table><tr><th>参数</th><th>原始版</th><th>IC优化版</th></tr>'
for param, label in [('value','价值因子'),('quality','质量因子'),('growth','成长因子'),('momentum','动量因子'),('volatility','波动因子'),('liquidity','流动性因子')]:
    orig = report['原始权重回测']['因子权重'][param]
    opt = report['IC优化权重回测']['因子权重'][param]
    html += f'<tr><td>{label}</td><td>{orig*100:.0f}%</td><td>{opt*100:.0f}%</td></tr>'

orig_risk = report['原始权重回测']['风控参数']
opt_risk = report['IC优化权重回测']['风控参数']
for key, label in [('止损','止损'),('组合回撤','组合回撤'),('持仓数','持仓数'),('滑点','滑点'),('印花税','印花税')]:
    html += f'<tr><td>{label}</td><td>{orig_risk.get(key,"-")}</td><td>{opt_risk.get(key,"-")}</td></tr>'
if '趋势择时' in opt_risk:
    html += f'<tr><td>趋势择时</td><td>无</td><td>{opt_risk["趋势择时"]}</td></tr>'
html += '</table></div>'

# 三方对比绩效
html += '<h2>📊 三方对比绩效</h2>'
html += '<table><tr><th>指标</th><th>原始权重</th><th>IC优化</th><th>SPY持有</th></tr>'
for key, label in [('总收益率%','总收益率'),('年化收益%','年化收益'),('最大回撤%','最大回撤')]:
    v1 = report['原始权重回测']['绩效'][key]
    v2 = report['IC优化权重回测']['绩效'][key]
    sp = report['基准绩效(SPY)'][key]
    cls = 'positive' if v2 > 0 else 'negative'
    html += f'<tr><td>{label}</td><td class="{"positive" if v1>0 else "negative"}">{v1:.2f}%</td><td class="{cls}">{v2:.2f}%</td><td class="positive">{sp:.2f}%</td></tr>'
for key, label in [('夏普比率','夏普比率'),('卡尔马比率','卡尔马比率'),('索提诺比率','索提诺比率')]:
    v1 = report['原始权重回测']['绩效'].get(key, 0)
    v2 = report['IC优化权重回测']['绩效'].get(key, 0)
    sp = report['基准绩效(SPY)'].get(key, 0)
    html += f'<tr><td>{label}</td><td>{v1:.2f}</td><td>{v2:.2f}</td><td>{sp:.2f}</td></tr>'
for key, label in [('胜率%','胜率'),('盈亏比','盈亏比')]:
    v1 = report['原始权重回测']['绩效'].get(key, 0)
    v2 = report['IC优化权重回测']['绩效'].get(key, 0)
    html += f'<tr><td>{label}</td><td>{v1:.2f}</td><td>{v2:.2f}</td><td>-</td></tr>'
html += '</table>'

# 年度收益对比
html += '<h2>📅 年度收益对比</h2>'
html += '<table><tr><th>年份</th><th>原始权重</th><th>IC优化</th><th>SPY持有</th><th>超额(IC优化)</th></tr>'
yearly = report['年度收益对比']
for y in sorted(yearly.keys()):
    d = yearly[y]
    orig = d['原始']
    opt = d['IC优化']
    spy = d['SPY']
    exc = opt - spy
    cls = 'positive' if exc > 0 else 'negative'
    html += f'<tr><td>{y}</td><td class="{"positive" if orig>0 else "negative"}">{orig:.2f}%</td><td class="{"positive" if opt>0 else "negative"}">{opt:.2f}%</td><td class="positive">{spy:.2f}%</td><td class="{cls}">{exc:+.2f}%</td></tr>'
html += '</table>'

# 止损统计
html += '<h2>🛡️ 止损统计</h2>'
html += '<table><tr><th>版本</th><th>固定止损</th><th>移动止损</th><th>总计</th></tr>'
for label, key in [('原始版','原始权重回测'),('IC优化版','IC优化权重回测')]:
    sl = report[key]['止损统计']
    html += f'<tr><td>{label}</td><td>{sl["固定止损"]}次</td><td>{sl["移动止损"]}次</td><td>{sl["总计"]}次</td></tr>'
html += '</table>'

# 过拟合检测
html += '<h2>🔬 过拟合检测</h2>'
html += '<table><tr><th>指标</th><th>训练集</th><th>测试集</th></tr>'
of = report['过拟合检测']
for k in ['年化收益%','最大回撤%','夏普比率']:
    html += f'<tr><td>{k}</td><td>{of["训练集"][k]:.2f}</td><td>{of["测试集"][k]:.2f}</td></tr>'
html += f'</table><p>过拟合比率: {of["过拟合比率"]:.2f} | 检测结果: {"⚠️ 过拟合" if of["过拟合检测"] else "✅ 良好"}</p>'

# 一致性验证
cv = report['一致性验证']
div_cls = 'success' if cv['passed'] else 'warning'
html += f'<h2>📋 一致性验证</h2><div class="{div_cls}">结果: {cv["verdict"]}'
if cv.get('warnings'):
    for w in cv['warnings']:
        html += f'<br>⚠️ {w}'
html += '</div>'

# 因子IC分析
html += '<h2>📊 因子IC分析（2019-2025美股）</h2>'
html += '<table><tr><th>因子</th><th>IC均值</th><th>ICIR</th><th>方向</th></tr>'
for fac, data in report['因子IC分析(2019-2025美股)'].items():
    html += f'<tr><td>{fac}</td><td>{data["IC均值"]:.4f}</td><td>{data["ICIR"]:.4f}</td><td>{data["方向"]}</td></tr>'
html += '</table>'

# 评分
for label, key in [('原始版','原始权重回测'),('IC优化版','IC优化权重回测')]:
    sc = report[key].get('评分', {})
    if not sc: continue
    html += f'<h2>📊 策略评分({label})</h2><div class="card">'
    html += f'<p style="font-size:28px;color:#1a237e;font-weight:bold;text-align:center;">{sc["总分"]}/100</p>'
    html += f'<p>回撤: {sc["回撤分"]}/20 | 年化: {sc["年化分"]}/25 | 夏普: {sc["夏普分"]}/25 | 盈亏比: {sc["盈亏比分"]}/15 | 胜率: {sc["胜率分"]}/15</p>'
    html += '</div>'

# 结论
conclusion = report['结论']
html += '<h2>📌 结论</h2>'
html += f'<div class="warning"><strong>目标vs实际</strong>: {conclusion["目标vs实际"]}</div>'
html += '<div class="card"><h3>核心问题</h3><ul>'
for issue in conclusion['核心问题']:
    html += f'<li>{issue}</li>'
html += '</ul><h3>IC优化改善</h3><ul>'
for imp in conclusion['IC优化改善']:
    html += f'<li>{imp}</li>'
html += f'</ul></div>'
html += f'<div class="warning"><strong>采纳建议</strong>: {conclusion["采纳建议"]}</div>'

html += f'<div class="footer">报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>回测引擎: 本地美股CSV + westock-data基本面</div>'
html += '</body></html>'

msg = MIMEMultipart('alternative')
msg['Subject'] = f'【策略回测报告】{datetime.now().strftime("%Y-%m-%d")} {datetime.now().strftime("%H:%M")}'
msg['From'] = '848786642@qq.com'
msg['To'] = '848786642@qq.com'
msg.attach(MIMEText(html, 'html', 'utf-8'))

try:
    with smtplib.SMTP_SSL('smtp.qq.com', 465) as s:
        s.login('848786642@qq.com', 'ljbtvacrctjobfed')
        s.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())
    print('✅ 邮件发送成功')
except Exception as e:
    print(f'❌ 邮件发送失败: {e}')
