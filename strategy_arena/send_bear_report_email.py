#!/usr/bin/env python3
"""发送熊市策略回测报告邮件"""
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

# === 配置 ===
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "848786642@qq.com"
PASSWORD = "ljbtvacrctjobfed"
RECIPIENT = "848786642@qq.com"

now = datetime.now()
DATE_STR = now.strftime("%Y-%m-%d")
TIME_STR = now.strftime("%H:%M")
SUBJECT = f"【熊市策略回测报告】{DATE_STR} {TIME_STR}"

# === 加载数据 ===
with open("/data/workspace/strategy_arena/bear_strategy_library.json", "r") as f:
    library = json.load(f)
with open("/data/workspace/strategy_arena/bear_leaderboard.json", "r") as f:
    leaderboard = json.load(f)
with open("/data/workspace/strategy_arena/bear_rejected_strategies.json", "r") as f:
    rejected = json.load(f)

strategies = library["strategies"]
last_updated = library.get("last_updated", "")

# 按得分排序
strategies_sorted = sorted(strategies, key=lambda x: x.get("total_score", 0), reverse=True)
top5 = strategies_sorted[:5]

# === 辅助函数 ===
def color_value(val, suffix="", is_pct=False):
    """正值绿色，负值红色"""
    if isinstance(val, (int, float)):
        if val > 0:
            return f'<span style="color:#2ecc71;font-weight:600;">+{val:.2f}{suffix}</span>'
        elif val < 0:
            return f'<span style="color:#e74c3c;font-weight:600;">{val:.2f}{suffix}</span>'
        else:
            return f'<span style="color:#95a5a6;">0{suffix}</span>'
    return f'<span>{val}</span>'

def color_pct(val, suffix="%"):
    """百分比着色"""
    if isinstance(val, (int, float)):
        if val > 0:
            return f'<span style="color:#2ecc71;font-weight:600;">+{val:.2f}{suffix}</span>'
        elif val < 0:
            return f'<span style="color:#e74c3c;font-weight:600;">{val:.2f}{suffix}</span>'
        else:
            return f'<span style="color:#95a5a6;">0{suffix}</span>'
    return f'<span>{val}</span>'

def market_badge(market):
    if market == "us":
        return '<span style="background:#3498db;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">🇺🇸 美股</span>'
    else:
        return '<span style="background:#e67e22;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">🇭🇰 港股</span>'

def rank_medal(rank):
    medals = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
    return medals.get(rank, f"{rank}")

def compatible_tag(tag):
    if "牛熊兼容" in tag:
        return f'<span style="background:#27ae60;color:#fff;padding:2px 8px;border-radius:10px;font-size:10px;">✅ 牛熊兼容</span>'
    else:
        return f'<span style="background:#c0392b;color:#fff;padding:2px 8px;border-radius:10px;font-size:10px;">⚠️ 仅限熊市</span>'

def risk_tags_html(tags):
    if not tags:
        return ""
    parts = tags.split("⚠️")
    parts = [p.strip() for p in parts if p.strip()]
    html = ""
    for p in parts:
        html += f'<span style="background:#e74c3c;color:#fff;padding:1px 6px;border-radius:8px;font-size:9px;margin-left:3px;">⚠️{p}</span>'
    return html

# === 统计 ===
us_strategies = [s for s in strategies if s.get("market") == "us"]
hk_strategies = [s for s in strategies if s.get("market") == "hk"]
avg_score_us = sum(s["total_score"] for s in us_strategies) / len(us_strategies) if us_strategies else 0
avg_score_hk = sum(s["total_score"] for s in hk_strategies) / len(hk_strategies) if hk_strategies else 0
bull_compat = sum(1 for s in strategies if s.get("bull_compatible"))
bear_only = len(strategies) - bull_compat

# === 构建HTML ===
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #1a1a2e; color: #e0e0e0; line-height: 1.6; }}
  .container {{ max-width: 600px; margin: 0 auto; padding: 10px; }}
  .header {{ background: linear-gradient(135deg, #2c3e50 0%, #e74c3c 50%, #c0392b 100%); border-radius: 16px 16px 0 0; padding: 24px 20px; text-align: center; }}
  .header h1 {{ color: #fff; font-size: 22px; margin-bottom: 6px; text-shadow: 0 2px 4px rgba(0,0,0,0.3); }}
  .header p {{ color: rgba(255,255,255,0.85); font-size: 13px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 12px; background: #16213e; }}
  .stat-item {{ background: #1a1a3e; border-radius: 10px; padding: 10px 8px; text-align: center; }}
  .stat-value {{ font-size: 20px; font-weight: 700; color: #e74c3c; }}
  .stat-label {{ font-size: 10px; color: #95a5a6; margin-top: 2px; }}
  .card {{ background: #16213e; border-radius: 12px; margin: 10px; padding: 16px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); border: 1px solid rgba(231,76,60,0.15); }}
  .card-header {{ display: flex; align-items: center; margin-bottom: 10px; }}
  .rank-badge {{ font-size: 28px; margin-right: 10px; }}
  .card-title {{ font-size: 16px; font-weight: 700; color: #ecf0f1; flex: 1; }}
  .card-score {{ font-size: 22px; font-weight: 800; color: #e74c3c; }}
  .card-market {{ margin-left: 8px; }}
  .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin: 10px 0; }}
  .metric-item {{ background: #0f3460; border-radius: 8px; padding: 8px 6px; text-align: center; }}
  .metric-label {{ font-size: 9px; color: #95a5a6; text-transform: uppercase; }}
  .metric-value {{ font-size: 14px; font-weight: 700; margin-top: 2px; }}
  .tags-row {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }}
  .stress-row {{ background: #0f3460; border-radius: 8px; padding: 8px 10px; margin-top: 8px; font-size: 11px; }}
  .stress-row span {{ margin-right: 12px; }}
  .section-title {{ background: linear-gradient(90deg, #e74c3c, #c0392b); color: #fff; padding: 10px 16px; font-size: 14px; font-weight: 700; border-radius: 8px; margin: 16px 10px 8px; }}
  .full-table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin: 8px 10px; }}
  .full-table th {{ background: #0f3460; color: #95a5a6; padding: 6px 4px; text-align: center; font-size: 9px; border-bottom: 1px solid #2c3e50; }}
  .full-table td {{ padding: 5px 4px; text-align: center; border-bottom: 1px solid rgba(44,62,80,0.5); }}
  .full-table tr:hover {{ background: rgba(231,76,60,0.08); }}
  .discard-table {{ width: 100%; border-collapse: collapse; font-size: 10px; margin: 8px 0; }}
  .discard-table th {{ background: #4a1a1a; color: #e74c3c; padding: 5px 3px; text-align: center; font-size: 9px; }}
  .discard-table td {{ padding: 4px 3px; text-align: center; border-bottom: 1px solid rgba(231,76,60,0.15); color: #95a5a6; }}
  .footer {{ text-align: center; padding: 16px; color: #555; font-size: 10px; }}
  .params-box {{ background: #0f3460; border-radius: 6px; padding: 6px 10px; font-size: 10px; color: #7f8c8d; margin-top: 6px; }}
</style>
</head>
<body>
<div class="container">

<!-- 标题栏 -->
<div class="header">
  <h1>🐻 熊市策略回测报告</h1>
  <p>📅 {DATE_STR} {TIME_STR} ｜ 回测区间: 2022-01-01 ~ 2022-12-31</p>
  <p>💪 压力测试: 2023 ｜ 🐂 牛市辅助: 2023.10~2024.12</p>
</div>

<!-- 统计网格 -->
<div class="stats-grid">
  <div class="stat-item">
    <div class="stat-value">{len(strategies)}</div>
    <div class="stat-label">策略总数</div>
  </div>
  <div class="stat-item">
    <div class="stat-value">{len(leaderboard)}</div>
    <div class="stat-label">排行榜策略</div>
  </div>
  <div class="stat-item">
    <div class="stat-value" style="color:#c0392b;">{len(rejected)}</div>
    <div class="stat-label">废弃策略</div>
  </div>
  <div class="stat-item">
    <div class="stat-value" style="color:#3498db;">{len(us_strategies)}</div>
    <div class="stat-label">美股策略</div>
  </div>
  <div class="stat-item">
    <div class="stat-value" style="color:#e67e22;">{len(hk_strategies)}</div>
    <div class="stat-label">港股策略</div>
  </div>
  <div class="stat-item">
    <div class="stat-value" style="color:#27ae60;">{bull_compat}</div>
    <div class="stat-label">牛熊兼容</div>
  </div>
  <div class="stat-item">
    <div class="stat-value">{avg_score_us:.1f}</div>
    <div class="stat-label">美股均分</div>
  </div>
  <div class="stat-item">
    <div class="stat-value">{avg_score_hk:.1f}</div>
    <div class="stat-label">港股均分</div>
  </div>
  <div class="stat-item">
    <div class="stat-value" style="color:#c0392b;">{bear_only}</div>
    <div class="stat-label">仅限熊市</div>
  </div>
</div>

<!-- 排行榜前五 - 卡片式设计 -->
<div class="section-title">🏆 排行榜 TOP 5</div>
"""

for i, s in enumerate(top5):
    rank = i + 1
    medal = rank_medal(rank)
    stress_ann = s.get("stress_annual", 0)
    stress_dd = s.get("stress_dd", 0)
    bull_ann = s.get("bull_annual", 0)
    bull_dd = s.get("bull_dd", 0)
    
    html += f"""
<div class="card">
  <div class="card-header">
    <span class="rank-badge">{medal}</span>
    <span class="card-title">{s['strategy_name']}</span>
    {market_badge(s.get('market', 'us'))}
    <span class="card-score">{s['total_score']:.2f}分</span>
  </div>
  <div style="font-size:11px;color:#95a5a6;margin-bottom:8px;">类型: {s.get('strategy_type', '-')} ｜ 波动率: {s.get('volatility_feature', '-')} ｜ 标的数: {s.get('n_stocks', '-')}</div>
  
  <div class="metric-grid">
    <div class="metric-item">
      <div class="metric-label">年化收益</div>
      <div class="metric-value">{color_pct(s['annual_return'])}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">夏普比率</div>
      <div class="metric-value">{color_value(s['sharpe'])}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">最大回撤</div>
      <div class="metric-value" style="color:#e74c3c;font-weight:700;">{s['max_drawdown']:.2f}%</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">盈亏比</div>
      <div class="metric-value">{color_value(s['profit_factor'])}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">胜率</div>
      <div class="metric-value">{color_pct(s['win_rate'])}</div>
    </div>
    <div class="metric-item">
      <div class="metric-label">年交易次数</div>
      <div class="metric-value" style="color:#ecf0f1;">{s.get('avg_trades_per_year', 0):.1f}</div>
    </div>
  </div>
  
  <div class="stress-row">
    <span>💪 压力: 年化{color_pct(stress_ann)} / 回撤<span style="color:#e74c3c;">{stress_dd:.2f}%</span></span>
    <span>🐂 牛市: 年化{color_pct(bull_ann)} / 回撤<span style="color:#e74c3c;">{bull_dd:.2f}%</span></span>
  </div>
  
  <div class="params-box">📋 {s.get('strategy_description', '-')[:80]}...</div>
  
  <div class="tags-row">
    {compatible_tag(s.get('bull_compatible_tag', ''))}
    {risk_tags_html(s.get('risk_tags', ''))}
  </div>
</div>
"""

# === 全部策略紧凑表格 ===
html += """
<div class="section-title">📊 全部策略数据</div>
<div style="overflow-x:auto;padding:0 10px;">
<table class="full-table">
<thead>
<tr>
  <th>#</th><th>策略</th><th>市场</th><th>得分</th><th>年化</th><th>夏普</th><th>回撤</th><th>盈亏比</th><th>胜率</th><th>年交易</th><th>兼容</th>
</tr>
</thead>
<tbody>
"""

for i, s in enumerate(strategies_sorted):
    ann = s.get("annual_return", 0)
    sharpe = s.get("sharpe", 0)
    dd = s.get("max_drawdown", 0)
    pf = s.get("profit_factor", 0)
    wr = s.get("win_rate", 0)
    trades = s.get("avg_trades_per_year", 0)
    score = s.get("total_score", 0)
    mkt = s.get("market", "-").upper()
    compat = "✅" if s.get("bull_compatible") else "⚠️"
    
    ann_color = "#2ecc71" if ann > 0 else "#e74c3c" if ann < 0 else "#95a5a6"
    sharpe_color = "#2ecc71" if sharpe > 0 else "#e74c3c" if sharpe < 0 else "#95a5a6"
    dd_color = "#e74c3c" if dd > 20 else "#e67e22" if dd > 10 else "#2ecc71"
    
    html += f"""<tr>
  <td>{i+1}</td>
  <td style="text-align:left;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{s['strategy_name']}</td>
  <td>{mkt}</td>
  <td style="font-weight:700;color:#e74c3c;">{score:.1f}</td>
  <td style="color:{ann_color};">{ann:+.1f}%</td>
  <td style="color:{sharpe_color};">{sharpe:.2f}</td>
  <td style="color:{dd_color};">{dd:.1f}%</td>
  <td>{pf:.2f}</td>
  <td>{wr:.1f}%</td>
  <td>{trades:.1f}</td>
  <td>{compat}</td>
</tr>"""

html += """</tbody></table></div>"""

# === 废弃策略库 ===
rejected_sorted = sorted(rejected, key=lambda x: x.get("rejected_time", ""), reverse=True)
recent_rejected = rejected_sorted[:10]
html += f"""
<div class="section-title">🗑️ 废弃策略库（共{len(rejected)}个，展示最近10个）</div>
<div style="overflow-x:auto;padding:0 10px;">
<table class="discard-table">
<thead>
<tr><th>#</th><th>策略</th><th>市场</th><th>类型</th><th>年化</th><th>回撤</th><th>废弃原因</th><th>废弃时间</th></tr>
</thead>
<tbody>
"""
for i, s in enumerate(recent_rejected):
    mkt = s.get("market", "-").upper()
    ann = s.get("annual_return", 0)
    dd = s.get("max_drawdown", 0)
    ann_color = "#e74c3c" if ann < 0 else "#95a5a6"
    dd_color = "#e74c3c" if dd > 20 else "#e67e22"
    
    html += f"""<tr>
  <td>{i+1}</td>
  <td style="text-align:left;">{s['strategy_name']}</td>
  <td>{mkt}</td>
  <td>{s.get('strategy_type', '-')}</td>
  <td style="color:{ann_color};">{ann:+.1f}%</td>
  <td style="color:{dd_color};">{dd:.1f}%</td>
  <td style="color:#e74c3c;">{s.get('rejection_reason', '-')}</td>
  <td>{s.get('rejected_time', '-')[:16]}</td>
</tr>"""

html += """</tbody></table></div>"""

# === 底部 ===
html += f"""
<div class="footer">
  <p>🐻 Blakever 熊市策略回测系统 ｜ 更新时间: {last_updated}</p>
  <p>⚠️ 本报告仅供研究参考，不构成投资建议</p>
  <p>⚠️ 所有策略均存在幸存者偏差风险标记</p>
</div>

</div>
</body>
</html>
"""

# === 构建Markdown附件 ===
md = f"""# 🐻 熊市策略回测报告 {DATE_STR} {TIME_STR}

## 概览
- 策略总数: {len(strategies)}
- 排行榜策略: {len(leaderboard)}
- 废弃策略: {len(rejected)}
- 美股策略: {len(us_strategies)} (均分: {avg_score_us:.1f})
- 港股策略: {len(hk_strategies)} (均分: {avg_score_hk:.1f})
- 牛熊兼容: {bull_compat} / 仅限熊市: {bear_only}

## 排行榜 TOP 5

"""
for i, s in enumerate(top5):
    rank = i + 1
    md += f"""### {rank_medal(rank)} 第{rank}名: {s['strategy_name']} ({s.get('market','-').upper()})
- 综合得分: {s['total_score']:.2f}
- 年化收益: {s['annual_return']:.2f}% | 夏普: {s['sharpe']:.2f} | 回撤: {s['max_drawdown']:.2f}%
- 盈亏比: {s['profit_factor']:.2f} | 胜率: {s['win_rate']:.1f}% | 年交易: {s.get('avg_trades_per_year',0):.1f}
- 压力测试: 年化{s.get('stress_annual',0):.2f}% / 回撤{s.get('stress_dd',0):.2f}%
- 牛市辅助: 年化{s.get('bull_annual',0):.2f}% / 回撤{s.get('bull_dd',0):.2f}%
- 兼容: {s.get('bull_compatible_tag','-')} | 风险: {s.get('risk_tags','-')}
- 描述: {s.get('strategy_description','-')}

"""

md += """## 全部策略数据

| # | 策略名称 | 市场 | 得分 | 年化 | 夏普 | 回撤 | 盈亏比 | 胜率 | 年交易 | 兼容 | 风险标记 |
|---|---------|------|------|------|------|------|--------|------|--------|------|---------|
"""
for i, s in enumerate(strategies_sorted):
    compat = "✅牛熊兼容" if s.get("bull_compatible") else "⚠️仅限熊市"
    md += f"| {i+1} | {s['strategy_name']} | {s.get('market','-').upper()} | {s['total_score']:.1f} | {s['annual_return']:+.2f}% | {s['sharpe']:.2f} | {s['max_drawdown']:.2f}% | {s['profit_factor']:.2f} | {s['win_rate']:.1f}% | {s.get('avg_trades_per_year',0):.1f} | {compat} | {s.get('risk_tags','-')} |\n"

md += f"""
## 废弃策略库（共{len(rejected)}个，展示最近10个）

| # | 策略名称 | 市场 | 类型 | 年化 | 回撤 | 废弃原因 | 废弃时间 |
|---|---------|------|------|------|------|---------|---------|
"""
for i, s in enumerate(recent_rejected):
    md += f"| {i+1} | {s['strategy_name']} | {s.get('market','-').upper()} | {s.get('strategy_type','-')} | {s.get('annual_return',0):+.1f}% | {s.get('max_drawdown',0):.1f}% | {s.get('rejection_reason','-')} | {s.get('rejected_time','-')[:16]} |\n"

md += f"""
---
🐻 Blakever 熊市策略回测系统 | 更新时间: {last_updated}
⚠️ 本报告仅供研究参考，不构成投资建议
"""

# === 发送邮件 ===
msg = MIMEMultipart("alternative")
msg["Subject"] = SUBJECT
msg["From"] = SENDER
msg["To"] = RECIPIENT

html_part = MIMEText(html, "html", "utf-8")
msg.attach(html_part)

md_part = MIMEApplication(md.encode("utf-8"), Name=f"bear_report_{DATE_STR}.md")
md_part["Content-Disposition"] = f'attachment; filename="bear_report_{DATE_STR}.md"'
msg.attach(md_part)

try:
    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
    server.login(SENDER, PASSWORD)
    server.sendmail(SENDER, RECIPIENT, msg.as_string())
    server.quit()
    print("✅ 邮件发送成功！")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
    raise
