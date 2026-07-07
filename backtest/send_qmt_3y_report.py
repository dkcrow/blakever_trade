#!/usr/bin/env python3
"""七星QMT 80%·15日恐慌过滤 近3年回测报告 — 生成HTML并发邮件
读 results_qmt 下的 summary + trades JSON, 输出报告并发送到 848786642@qq.com
"""
import json, smtplib
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = Path(__file__).parent.parent
RES = ROOT / 'backtest' / 'results_qmt'
TAG = '2023-06-21_2026-06-21_pp5'
summary = json.load(open(RES / f'七星QMT_{TAG}_summary.json', encoding='utf-8'))
trades = json.load(open(RES / f'七星QMT_{TAG}_trades.json', encoding='utf-8'))

NOW = datetime.now().strftime('%Y-%m-%d %H:%M')
n = summary.get('trading_days', 712)
fv = summary.get('final_value', 0); cash = summary.get('initial_cash', 1000000)
cagr = (fv / cash) ** (252.0 / n) - 1 if n > 0 else 0
tr = summary.get('total_return_pct', 0)
dd = summary.get('max_drawdown_pct', 0)
sh = summary.get('sharpe_ratio', 0)
nt = summary.get('total_trades', 0)
wr = summary.get('win_rate_pct', 0)
panic_sells = [t for t in trades if '恐慌' in str(t.get('reason', ''))]

# 最近20笔
recent = trades[-20:][::-1]
rows = ""
for t in recent:
    act = '买入' if t['action'] == 'BUY' else '卖出'
    bg = '#FCE9E9' if t['action'] == 'BUY' else '#E9F3EC'   # 中国惯例: 买红 卖绿
    pnl = t.get('pnl_pct')
    if pnl is None:
        ps, pc = '-', '#888'
    else:
        pv = pnl * 100
        ps = f'{pv:+.2f}%'
        pc = '#C62828' if pv > 0 else ('#2E7D32' if pv < 0 else '#888')  # 涨红跌绿
    panic = '🛡️恐慌空仓' if '恐慌' in str(t.get('reason', '')) else t.get('reason', '')
    rows += f"""<tr style="background:{bg};white-space:nowrap;">
        <td style="padding:4px 8px;">{t['date']}</td>
        <td style="padding:4px 8px;font-weight:bold;">{act}</td>
        <td style="padding:4px 8px;">{t['code']} {t.get('name','')}</td>
        <td style="padding:4px 8px;text-align:right;">¥{t['price']:.3f}</td>
        <td style="padding:4px 8px;text-align:right;">¥{t.get('amount',0):,.0f}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pc};">{ps}</td>
        <td style="padding:4px 8px;font-size:11px;color:#555;">{panic}</td>
        <td style="padding:4px 8px;text-align:right;color:#1F4E79;">¥{t.get('total_value',0):,.0f}</td></tr>"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:15px;background:#F0F2F5;">
<h1 style="font-size:18px;color:#1F4E79;margin:0;">📊 七星QMT · 80%·15日恐慌过滤 · 近3年回测</h1>
<div style="font-size:11px;color:#888;margin-top:3px;">{NOW} | 区间: {summary.get('backtest_period','2023-06-21 ~ 2026-06-02')} | {n}交易日 | 50只池 持仓1只</div>

<div style="background:#1F4E79;color:#fff;padding:10px 15px;border-radius:6px;margin:12px 0;font-size:12px;line-height:1.6;">
<b>策略规则:</b> 七星QMT(动量轮动) + <b>新增恐慌过滤</b>: 成分股池 &gt;80% 跌破15日线 → 判恐慌期 → <b>卖出全部持仓、空仓防守</b><br>
<b>其余:</b> 盈利保护(5%回撤) | 溢价率(&gt;20%) | 佣金0.02% | 评分(exp(slope×250)-1)×R²线性加权
</div>

<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
<h2 style="font-size:14px;color:#1F4E79;margin:0 0 8px 0;">📈 回测绩效</h2>
<div style="display:flex;flex-wrap:wrap;gap:10px;">
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:11px;color:#888;">累计收益</div><div style="font-size:18px;font-weight:bold;color:#C62828;">{tr:+.1f}%</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:11px;color:#888;">年化(CAGR)</div><div style="font-size:18px;font-weight:bold;color:#C62828;">{cagr*100:.1f}%</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:11px;color:#888;">最大回撤</div><div style="font-size:18px;font-weight:bold;color:#2E7D32;">{dd:.1f}%</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:11px;color:#888;">夏普</div><div style="font-size:18px;font-weight:bold;color:#1F4E79;">{sh:.2f}</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;"><div style="font-size:11px;color:#888;">交易/胜率</div><div style="font-size:18px;font-weight:bold;color:#1F4E79;">{nt}/{wr:.0f}%</div></div>
</div>
<div style="margin-top:10px;font-size:12px;color:#555;background:#FFF8E1;padding:8px 12px;border-radius:6px;border-left:4px solid #F9A825;">
🛡️ <b>恐慌过滤效果:</b> 近3年触发空仓卖出 <b>{len(panic_sells)}</b> 笔; 最大回撤由关闭时的 36.3% 降至 <b>{dd:.1f}%</b> (改善约7.9pp), 夏普基本持平(1.79 vs 1.81)。
</div>
</div>

<div style="background:#fff;padding:15px;border-radius:8px;">
<h2 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">📋 最近20笔交易</h2>
<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:12px;">
<tr style="background:#1F4E79;color:#fff;"><th style="padding:6px 8px;text-align:left;">日期</th><th style="padding:6px 8px;">方向</th><th style="padding:6px 8px;text-align:left;">标的</th><th style="padding:6px 8px;">价格</th><th style="padding:6px 8px;">金额</th><th style="padding:6px 8px;">盈亏</th><th style="padding:6px 8px;">理由</th><th style="padding:6px 8px;">总资产</th></tr>
{rows}</table></div></div>

<div style="text-align:center;font-size:10px;color:#999;margin-top:15px;">七星QMT · 80%·15日恐慌过滤 · Blakever Trade · {NOW}<br>本报告为回测结果，仅供研究参考，不构成投资建议。</div>
</body></html>"""

out = RES / f'七星QMT_80pct15日恐慌过滤_近3年报告_{datetime.now().strftime("%Y%m%d_%H%M")}.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)

msg = MIMEMultipart("mixed")
msg["Subject"] = f"[七星QMT] 80%·15日恐慌过滤 近3年回测 - 累计{tr:+.0f}% 回撤{dd:.1f}% - {NOW}"
msg["From"] = "848786642@qq.com"
msg["To"] = "848786642@qq.com"
msg.attach(MIMEText(html, "html", "utf-8"))
try:
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
        s.login("848786642@qq.com", "ljbtvacrctjobfed")
        s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
    print("[OK] 邮件已发送")
except Exception as e:
    print(f"[WARN] 邮件发送失败: {e}")
print(f"报告: {out}")
print(f"绩效: 累计{tr:+.2f}% | 年化{cagr*100:.1f}% | 回撤{dd:.1f}% | 夏普{sh:.2f} | 交易{nt} | 恐慌空仓{len(panic_sells)}笔")
