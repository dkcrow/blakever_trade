#!/usr/bin/env python3
"""发送熊市策略回测报告邮件"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import json
import os

# 加载数据
os.chdir('/data/workspace/strategy_arena')
with open('bear_strategy_library.json', 'r') as f:
    lib = json.load(f)
with open('bear_rejected_strategies.json', 'r') as f:
    rejected = json.load(f)

strategies = sorted(lib['strategies'], key=lambda x: x['total_score'], reverse=True)
top5 = strategies[:5]
all_strategies = strategies

# 废弃策略按时间倒序
rejected_sorted = sorted(rejected, key=lambda x: x.get('deprecated_time', x.get('backtest_time', '')), reverse=True)
recent_rejected = rejected_sorted[:10]

def val_color(val, threshold=0, invert=False):
    """正值绿色，负值红色"""
    try:
        v = float(val)
    except:
        return 'color:#ccc'
    if invert:
        return 'color:#e74c3c' if v > threshold else 'color:#2ecc71'
    return 'color:#2ecc71' if v > threshold else 'color:#e74c3c' if v < threshold else 'color:#ccc'

def fmt_pct(val, suffix='%'):
    try:
        v = float(val)
        sign = '+' if v > 0 else ''
        return f'{sign}{v:.2f}{suffix}'
    except:
        return f'{val}{suffix}'

def risk_tag_html(tag_str):
    """将风险标签转为HTML标签"""
    tags = tag_str.split() if tag_str else []
    html = ''
    for t in tags:
        t = t.strip()
        if not t:
            continue
        if '回撤>20%' in t:
            html += f'<span style="background:#e74c3c;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;margin:1px;">{t}</span>'
        elif '仅限熊市' in t:
            html += f'<span style="background:#e67e22;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;margin:1px;">{t}</span>'
        elif '幸存者偏差' in t:
            html += f'<span style="background:#9b59b6;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;margin:1px;">{t}</span>'
        else:
            html += f'<span style="background:#555;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;margin:1px;">{t}</span>'
    return html

def compat_tag_html(tag):
    if '✅' in tag:
        return f'<span style="background:#27ae60;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;">{tag}</span>'
    else:
        return f'<span style="background:#e67e22;color:#fff;padding:2px 6px;border-radius:3px;font-size:10px;">{tag}</span>'

def market_badge(market):
    if market == 'us':
        return '<span style="background:#3498db;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">🇺🇸 US</span>'
    else:
        return '<span style="background:#e74c3c;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">🇭🇰 HK</span>'

medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
card_colors = ['#FFD700', '#C0C0C0', '#CD7F32', '#5DADE2', '#AF7AC5']

now = datetime.now()
date_str = now.strftime('%Y-%m-%d')
time_str = now.strftime('%H:%M')

# 统计信息
us_count = sum(1 for s in all_strategies if s['market'] == 'us')
hk_count = sum(1 for s in all_strategies if s['market'] == 'hk')
positive_count = sum(1 for s in all_strategies if s['annual_return'] > 0)
compatible_count = sum(1 for s in all_strategies if s['bull_compatible'])
avg_score = sum(s['total_score'] for s in all_strategies) / len(all_strategies) if all_strategies else 0

# ===== TOP 5 卡片 =====
top5_cards = ''
for i, s in enumerate(top5):
    medal = medals[i]
    border_color = card_colors[i]
    desc = s.get('strategy_description', '')
    params = s.get('strategy_params', {})
    params_str = ', '.join(f'{k}={v}' for k, v in params.items()) if params else '默认参数'
    
    # 压力测试
    stress_annual = s.get('stress_annual', 0)
    stress_dd = s.get('stress_dd', 0)
    bull_annual = s.get('bull_annual', 0)
    bull_dd = s.get('bull_dd', 0)
    
    top5_cards += f'''
    <div style="background:#1e2130;border-radius:12px;border-left:4px solid {border_color};margin-bottom:16px;box-shadow:0 4px 15px rgba(0,0,0,0.3);overflow:hidden;">
      <div style="background:linear-gradient(135deg,#1a1d2e,#252840);padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.05);">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;">
          <div>
            <span style="font-size:24px;">{medal}</span>
            <span style="font-size:18px;font-weight:bold;color:#fff;margin-left:8px;">{s["strategy_name"]}</span>
            {market_badge(s["market"])}
          </div>
          <div style="text-align:right;">
            <div style="font-size:28px;font-weight:bold;color:{border_color};">{s["total_score"]:.1f}</div>
            <div style="font-size:11px;color:#888;">综合得分</div>
          </div>
        </div>
        <div style="margin-top:6px;font-size:12px;color:#aaa;">{s["strategy_type"]} · {s["volatility_feature"]}</div>
      </div>
      <div style="padding:16px 20px;">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;">
          <div style="background:#141625;padding:10px;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">年化收益</div>
            <div style="font-size:16px;font-weight:bold;{val_color(s['annual_return'])}">{fmt_pct(s['annual_return'])}</div>
          </div>
          <div style="background:#141625;padding:10px;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">夏普比率</div>
            <div style="font-size:16px;font-weight:bold;{val_color(s['sharpe'])}">{s['sharpe']:.2f}</div>
          </div>
          <div style="background:#141625;padding:10px;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">最大回撤</div>
            <div style="font-size:16px;font-weight:bold;{val_color(s['max_drawdown'], invert=True)}">{s['max_drawdown']:.2f}%</div>
          </div>
          <div style="background:#141625;padding:10px;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">盈亏比</div>
            <div style="font-size:16px;font-weight:bold;{val_color(s['profit_factor'])}">{s['profit_factor']:.2f}</div>
          </div>
          <div style="background:#141625;padding:10px;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">胜率</div>
            <div style="font-size:16px;font-weight:bold;{val_color(s['win_rate'], 50)}">{s['win_rate']:.1f}%</div>
          </div>
          <div style="background:#141625;padding:10px;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#888;margin-bottom:4px;">年交易次数</div>
            <div style="font-size:16px;font-weight:bold;color:#ccc;">{s['avg_trades_per_year']:.1f}</div>
          </div>
        </div>
        <!-- 压力测试 & 牛市测试 -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
          <div style="background:#141625;padding:10px;border-radius:8px;">
            <div style="font-size:11px;color:#e67e22;margin-bottom:6px;">🔥 压力测试(2023)</div>
            <div style="font-size:12px;color:#aaa;">年化: <span style="{val_color(stress_annual)}">{fmt_pct(stress_annual)}</span> · 回撤: <span style="{val_color(stress_dd, invert=True)}">{stress_dd:.2f}%</span></div>
          </div>
          <div style="background:#141625;padding:10px;border-radius:8px;">
            <div style="font-size:11px;color:#2ecc71;margin-bottom:6px;">🐂 牛市辅助(2023-2024)</div>
            <div style="font-size:12px;color:#aaa;">年化: <span style="{val_color(bull_annual)}">{fmt_pct(bull_annual)}</span> · 回撤: <span style="{val_color(bull_dd, invert=True)}">{bull_dd:.2f}%</span></div>
          </div>
        </div>
        <!-- 参数 & 标签 -->
        <div style="font-size:11px;color:#888;margin-bottom:6px;">📌 {params_str}</div>
        <div style="font-size:11px;color:#aaa;margin-bottom:6px;">📝 {desc}</div>
        <div style="display:flex;flex-wrap:wrap;gap:4px;">
          {compat_tag_html(s['bull_compatible_tag'])}
          {risk_tag_html(s.get('risk_tags', ''))}
        </div>
      </div>
    </div>'''

# ===== 全部策略表格 =====
table_rows = ''
for i, s in enumerate(all_strategies):
    row_bg = '#1a1d2e' if i % 2 == 0 else '#1e2130'
    table_rows += f'''
    <tr style="background:{row_bg};">
      <td style="padding:6px 8px;text-align:center;color:#888;font-size:11px;">{i+1}</td>
      <td style="padding:6px 8px;font-size:11px;color:#eee;">{s["strategy_name"]}</td>
      <td style="padding:6px 8px;text-align:center;">{market_badge(s["market"])}</td>
      <td style="padding:6px 8px;text-align:center;color:#ddd;font-size:11px;">{s["strategy_type"]}</td>
      <td style="padding:6px 8px;text-align:center;font-weight:bold;{val_color(s['total_score'], 30)}">{s['total_score']:.1f}</td>
      <td style="padding:6px 8px;text-align:center;{val_color(s['annual_return'])}">{fmt_pct(s['annual_return'])}</td>
      <td style="padding:6px 8px;text-align:center;{val_color(s['sharpe'])}">{s['sharpe']:.2f}</td>
      <td style="padding:6px 8px;text-align:center;{val_color(s['max_drawdown'], invert=True)}">{s['max_drawdown']:.2f}%</td>
      <td style="padding:6px 8px;text-align:center;{val_color(s['profit_factor'])}">{s['profit_factor']:.2f}</td>
      <td style="padding:6px 8px;text-align:center;{val_color(s['win_rate'], 50)}">{s['win_rate']:.1f}%</td>
      <td style="padding:6px 8px;text-align:center;color:#ccc;font-size:11px;">{s['avg_trades_per_year']:.1f}</td>
      <td style="padding:6px 8px;text-align:center;font-size:10px;">{compat_tag_html(s['bull_compatible_tag'])}</td>
    </tr>'''

# ===== 废弃策略表格 =====
dep_rows = ''
for i, d in enumerate(recent_rejected):
    row_bg = '#1a1d2e' if i % 2 == 0 else '#1e2130'
    dep_time = d.get('deprecated_time', d.get('backtest_time', 'N/A'))
    if dep_time and len(dep_time) > 16:
        dep_time = dep_time[:16]
    dep_rows += f'''
    <tr style="background:{row_bg};">
      <td style="padding:5px 8px;text-align:center;color:#888;font-size:11px;">{i+1}</td>
      <td style="padding:5px 8px;font-size:11px;color:#aaa;">{d["strategy_name"]}</td>
      <td style="padding:5px 8px;text-align:center;font-size:10px;">{market_badge(d["market"])}</td>
      <td style="padding:5px 8px;text-align:center;color:#888;font-size:11px;">{d.get("strategy_type","N/A")}</td>
      <td style="padding:5px 8px;text-align:center;color:#e74c3c;font-size:11px;">{d["max_drawdown"]:.1f}%</td>
      <td style="padding:5px 8px;text-align:center;{val_color(d['annual_return'])};font-size:11px;">{fmt_pct(d['annual_return'])}</td>
      <td style="padding:5px 8px;text-align:center;color:#666;font-size:10px;">{dep_time}</td>
    </tr>'''

# ===== 构建完整HTML =====
html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>熊市策略回测报告</title>
</head>
<body style="margin:0;padding:0;background:#0d0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#eee;">

<div style="max-width:600px;margin:0 auto;padding:12px;">

<!-- 标题栏 -->
<div style="background:linear-gradient(135deg,#1a0533,#2d1b69,#4a1942);border-radius:12px;padding:24px 20px;text-align:center;margin-bottom:16px;box-shadow:0 4px 20px rgba(75,0,130,0.4);">
  <div style="font-size:32px;margin-bottom:8px;">🐻</div>
  <h1 style="margin:0;font-size:22px;color:#fff;letter-spacing:1px;">熊市策略回测报告</h1>
  <div style="font-size:13px;color:#b8a9d4;margin-top:8px;">{date_str} {time_str} · 自动扫描</div>
  <div style="font-size:11px;color:#8878a8;margin-top:4px;">回测区间: 2022年美股熊市 · 压力测试: 2023高利率 · 牛市辅助: 2023-2024</div>
</div>

<!-- 统计网格 -->
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px;">
  <div style="background:#1e2130;border-radius:10px;padding:14px 10px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
    <div style="font-size:24px;font-weight:bold;color:#3498db;">{len(all_strategies)}</div>
    <div style="font-size:10px;color:#888;margin-top:2px;">策略总数</div>
  </div>
  <div style="background:#1e2130;border-radius:10px;padding:14px 10px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
    <div style="font-size:24px;font-weight:bold;color:#2ecc71;">{positive_count}</div>
    <div style="font-size:10px;color:#888;margin-top:2px;">正收益策略</div>
  </div>
  <div style="background:#1e2130;border-radius:10px;padding:14px 10px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
    <div style="font-size:24px;font-weight:bold;color:#e67e22;">{compatible_count}</div>
    <div style="font-size:10px;color:#888;margin-top:2px;">牛熊兼容</div>
  </div>
  <div style="background:#1e2130;border-radius:10px;padding:14px 10px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
    <div style="font-size:24px;font-weight:bold;color:#9b59b6;">🇺🇸 {us_count}</div>
    <div style="font-size:10px;color:#888;margin-top:2px;">美股策略</div>
  </div>
  <div style="background:#1e2130;border-radius:10px;padding:14px 10px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
    <div style="font-size:24px;font-weight:bold;color:#e74c3c;">🇭🇰 {hk_count}</div>
    <div style="font-size:10px;color:#888;margin-top:2px;">港股策略</div>
  </div>
  <div style="background:#1e2130;border-radius:10px;padding:14px 10px;text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
    <div style="font-size:24px;font-weight:bold;color:#f39c12;">{avg_score:.1f}</div>
    <div style="font-size:10px;color:#888;margin-top:2px;">平均得分</div>
  </div>
</div>

<!-- TOP 5 排行榜 -->
<div style="background:linear-gradient(135deg,#1a0533,#2d1b69);border-radius:12px;padding:12px;margin-bottom:16px;">
  <h2 style="margin:0 0 4px 12px;font-size:16px;color:#fff;">🏆 熊市策略排行榜 TOP 5</h2>
  <div style="font-size:11px;color:#b8a9d4;margin:0 0 12px 12px;">基于综合评分排名（含年化/回撤/夏普/盈亏比/胜率多维评估）</div>
  {top5_cards}
</div>

<!-- 全部策略表格 -->
<div style="background:#1e2130;border-radius:12px;padding:12px;margin-bottom:16px;overflow-x:auto;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
  <h2 style="margin:0 0 10px 8px;font-size:15px;color:#fff;">📊 全部策略数据（{len(all_strategies)}个）</h2>
  <table style="width:100%;border-collapse:collapse;font-size:11px;min-width:560px;">
    <thead>
      <tr style="background:#141625;border-bottom:2px solid #2d1b69;">
        <th style="padding:8px;color:#aaa;font-size:10px;">#</th>
        <th style="padding:8px;color:#aaa;font-size:10px;text-align:left;">策略名称</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">市场</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">类型</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">得分</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">年化</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">夏普</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">回撤</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">盈亏比</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">胜率</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">年交易</th>
        <th style="padding:8px;color:#aaa;font-size:10px;">兼容</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</div>

<!-- 废弃策略库 -->
<div style="background:#1e2130;border-radius:12px;padding:12px;margin-bottom:16px;overflow-x:auto;box-shadow:0 2px 10px rgba(0,0,0,0.2);">
  <h2 style="margin:0 0 10px 8px;font-size:15px;color:#e74c3c;">🗑️ 废弃策略库（共{len(rejected)}个，展示最近10个）</h2>
  <table style="width:100%;border-collapse:collapse;font-size:11px;min-width:480px;">
    <thead>
      <tr style="background:#141625;border-bottom:2px solid #e74c3c;">
        <th style="padding:6px;color:#aaa;font-size:10px;">#</th>
        <th style="padding:6px;color:#aaa;font-size:10px;text-align:left;">策略名称</th>
        <th style="padding:6px;color:#aaa;font-size:10px;">市场</th>
        <th style="padding:6px;color:#aaa;font-size:10px;">类型</th>
        <th style="padding:6px;color:#aaa;font-size:10px;">最大回撤</th>
        <th style="padding:6px;color:#aaa;font-size:10px;">年化</th>
        <th style="padding:6px;color:#aaa;font-size:10px;">废弃时间</th>
      </tr>
    </thead>
    <tbody>
      {dep_rows}
    </tbody>
  </table>
</div>

<!-- 页脚 -->
<div style="text-align:center;padding:16px;color:#555;font-size:10px;">
  <div>Blakever 熊市策略回测系统 · 自动扫描报告</div>
  <div style="margin-top:4px;">⚠️ 本报告仅供研究参考，不构成投资建议</div>
  <div style="margin-top:4px;">⚠️ 所有策略均标注幸存者偏差风险，实际表现可能低于回测</div>
</div>

</div>
</body>
</html>'''

# 保存HTML
with open('bear_report_email.html', 'w', encoding='utf-8') as f:
    f.write(html)

# ===== 同时生成Markdown附件 =====
md = f'''# 🐻 熊市策略回测报告 {date_str} {time_str}

## 统计概览
- 策略总数: {len(all_strategies)} (US:{us_count} / HK:{hk_count})
- 正收益策略: {positive_count}
- 牛熊兼容: {compatible_count}
- 平均得分: {avg_score:.1f}
- 废弃策略库: {len(rejected)}个
- 回测区间: 2022年美股熊市
- 压力测试: 2023年高利率震荡市
- 牛市辅助: 2023-2024

## 🏆 TOP 5 排行榜

| 排名 | 策略名称 | 市场 | 类型 | 得分 | 年化 | 夏普 | 回撤 | 盈亏比 | 胜率 | 年交易 | 兼容 | 风险标记 |
|------|---------|------|------|------|------|------|------|--------|------|--------|------|---------|
'''
for i, s in enumerate(top5):
    md += f'| {i+1} | {s["strategy_name"]} | {s["market"].upper()} | {s["strategy_type"]} | {s["total_score"]:.1f} | {fmt_pct(s["annual_return"])} | {s["sharpe"]:.2f} | {s["max_drawdown"]:.2f}% | {s["profit_factor"]:.2f} | {s["win_rate"]:.1f}% | {s["avg_trades_per_year"]:.1f} | {s["bull_compatible_tag"]} | {s.get("risk_tags","")} |\n'

md += f'\n## 📊 全部策略数据（{len(all_strategies)}个）\n\n'
md += '| # | 策略名称 | 市场 | 类型 | 得分 | 年化 | 夏普 | 回撤 | 盈亏比 | 胜率 | 年交易 | 兼容 |\n'
md += '|---|---------|------|------|------|------|------|------|--------|------|--------|------|\n'
for i, s in enumerate(all_strategies):
    md += f'| {i+1} | {s["strategy_name"]} | {s["market"].upper()} | {s["strategy_type"]} | {s["total_score"]:.1f} | {fmt_pct(s["annual_return"])} | {s["sharpe"]:.2f} | {s["max_drawdown"]:.2f}% | {s["profit_factor"]:.2f} | {s["win_rate"]:.1f}% | {s["avg_trades_per_year"]:.1f} | {s["bull_compatible_tag"]} |\n'

md += f'\n## 🗑️ 废弃策略库（共{len(rejected)}个，展示最近10个）\n\n'
md += '| # | 策略名称 | 市场 | 类型 | 回撤 | 年化 | 废弃时间 |\n'
md += '|---|---------|------|------|------|------|--------|\n'
for i, d in enumerate(recent_rejected):
    dep_time = d.get('deprecated_time', d.get('backtest_time', 'N/A'))
    if dep_time and len(dep_time) > 16:
        dep_time = dep_time[:16]
    md += f'| {i+1} | {d["strategy_name"]} | {d["market"].upper()} | {d.get("strategy_type","N/A")} | {d["max_drawdown"]:.1f}% | {fmt_pct(d["annual_return"])} | {dep_time} |\n'

md += '\n---\n⚠️ 本报告仅供研究参考，不构成投资建议\n⚠️ 所有策略均标注幸存者偏差风险，实际表现可能低于回测\n'

with open('bear_report_email.md', 'w', encoding='utf-8') as f:
    f.write(md)

# ===== 发送邮件 =====
msg = MIMEMultipart('mixed')
msg['From'] = '848786642@qq.com'
msg['To'] = '848786642@qq.com'
msg['Subject'] = f'【熊市策略回测报告】{date_str} {time_str}'

# HTML正文
html_part = MIMEText(html, 'html', 'utf-8')
msg.attach(html_part)

# Markdown附件
with open('bear_report_email.md', 'rb') as f:
    md_attachment = MIMEBase('application', 'octet-stream')
    md_attachment.set_payload(f.read())
    encoders.encode_base64(md_attachment)
    md_attachment.add_header('Content-Disposition', 'attachment', filename=f'bear_report_{date_str}.md')
    msg.attach(md_attachment)

# 发送
try:
    server = smtplib.SMTP_SSL('smtp.qq.com', 465)
    server.login('848786642@qq.com', 'ljbtvacrctjobfed')
    server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())
    server.quit()
    print('✅ 邮件发送成功！')
except Exception as e:
    print(f'❌ 邮件发送失败: {e}')
