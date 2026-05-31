#!/usr/bin/env python3
"""七星172 多仓位回测对比 (top1~5) — 隔离子进程版"""
import sys, subprocess, json, smtplib
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

PROJECT = Path(__file__).parent.parent
PY = str(Path.home() / '.workbuddy' / 'binaries' / 'python' / 'envs' / 'default' / 'Scripts' / 'python.exe')
SEND_EMAIL = '--send-email' in sys.argv

BACKTEST_CODE = r'''
import sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, r'__PROJECT__')
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource

params = {
    'lookback_days': 25, 'holdings_num': __HOLDINGS__,
    'enable_profit_protection': True, 'enable_volume_check': True,
    'use_short_momentum_filter': True, 'enable_premium_filter': True,
}
ds = LocalDataSource()
e = BacktestEngine172(ds, engine_params=params)
e.commission_rate = 0.0002
r = e.run('2025-01-02', '2026-05-30', 10000)

buys_per_day = {}
for t in r['trade_log']:
    if t['action'] == '买入' and t['etf'] != 'sh511880':
        buys_per_day.setdefault(t['date'], []).append(t['etf'])

from collections import Counter
hold_dist = Counter(len(v) for v in buys_per_day.values())

print(json.dumps({
    'holdings': __HOLDINGS__,
    'trades': len(r['trade_log']),
    'buy': r['buy_trades'], 'sell': r['sell_trades'],
    'annual': round(r['annualized_return_pct'], 2),
    'total_ret': round(r['total_return_pct'], 2),
    'drawdown': round(r['max_drawdown_pct'], 2),
    'sharpe': round(r['sharpe_ratio'], 4),
    'calmar': round(r['calmar_ratio'], 4),
    'win_rate': round(r['win_rate_pct'], 2),
    'avg_win': round(r['avg_win_pct'], 2),
    'avg_loss': round(r['avg_loss_pct'], 2),
    'final_value': round(r['final_value'], 2),
    'hold_dist': dict(hold_dist),
}))
'''.replace('__PROJECT__', str(PROJECT))

def run_backtest(holdings):
    code = BACKTEST_CODE.replace('__HOLDINGS__', str(holdings))
    r = subprocess.run([PY, '-c', code], capture_output=True, text=True, timeout=600,
                       cwd=str(PROJECT), encoding='utf-8', errors='replace')
    for line in r.stdout.strip().split('\n'):
        try:
            return json.loads(line)
        except: pass
    return None

# Run all 5
print('Running top1~5 backtests in isolated subprocesses...')
results = {}
for h in [1, 2, 3, 4, 5]:
    print(f'  holdings={h} ... ', end='', flush=True)
    r = run_backtest(h)
    if r:
        results[h] = r
        print(f'OK ({r["trades"]} trades, {r["annual"]:.1f}% annual)')
    else:
        print('FAILED')

if not results:
    sys.exit(1)

# Build HTML report
def fmt(v, fmt_spec):
    if v is None: return 'N/A'
    if fmt_spec == '%': return f'{v:.2f}%'
    if fmt_spec == '¥': return f'{v:.2f}¥'
    return f'{v:.4f}' if fmt_spec == 'f' else f'{v}'

metrics = [
    ('年化收益率', 'annualized_return_pct', '%', True),
    ('总收益率', 'total_return_pct', '%', True),
    ('最大回撤', 'max_drawdown_pct', '%', False),
    ('夏普比率', 'sharpe_ratio', 'f', True),
    ('卡尔马比率', 'calmar_ratio', 'f', True),
    ('总交易次数', 'total_trades', 'd', False),
    ('买入次数', 'buy_trades', 'd', False),
    ('卖出次数', 'sell_trades', 'd', False),
    ('胜率', 'win_rate_pct', '%', True),
    ('平均盈利', 'avg_win_pct', '%', True),
    ('平均亏损', 'avg_loss_pct', '%', False),
    ('最终资产', 'final_value', '¥', True),
]

# Find best per metric
best = {}
for mname, mkey, _, higher_better in metrics:
    vals = [(h, results[h].get(mkey, 0)) for h in results]
    valid = [(h, v) for h, v in vals if v is not None]
    if not valid: continue
    if higher_better:
        best[mkey] = max(valid, key=lambda x: x[1])[0]
    else:
        best[mkey] = min(valid, key=lambda x: x[1])[0]

def bold_best(metric_key, val_str, h):
    return f'<b>{val_str}</b>' if best.get(metric_key) == h else val_str

comp_rows = ''
for mname, mkey, fmt_spec, _ in metrics:
    comp_rows += f'<tr><td style="padding:4px 10px;text-align:right;color:#666;white-space:nowrap;">{mname}</td>'
    for h in [1, 2, 3, 4, 5]:
        v = results[h].get(mkey)
        if v is None:
            s = '—'
        elif fmt_spec == '%':
            s = f'{v:.2f}%'
        elif fmt_spec == '¥':
            s = f'{v:.2f}¥'
        elif fmt_spec == 'f':
            s = f'{v:.4f}'
        else:
            s = str(v)
        comp_rows += f'<td style="padding:4px 10px;text-align:right;white-space:nowrap;">{bold_best(mkey, s, h)}</td>'
    comp_rows += '</tr>\n'

# Auto-reduction summary
auto_reduce_rows = ''
for h in [2, 3, 4, 5]:
    dist = results[h].get('hold_dist', {})
    auto_reduce_rows += f'<tr><td style="padding:4px 8px;font-weight:bold;">top{h}</td>'
    for n in [1, 2, 3, 4, 5]:
        cnt = dist.get(str(n), 0)
        v = f'{cnt}天' if cnt else '—'
        highlight = 'background:#E8F5E9;' if n < h else ''
        auto_reduce_rows += f'<td style="padding:4px 8px;text-align:center;{highlight}">{v}</td>'
    auto_reduce_rows += '</tr>\n'

now = datetime.now().strftime('%Y-%m-%d %H:%M')
html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:'Microsoft YaHei',sans-serif;font-size:14px;color:#333;max-width:750px;margin:0 auto;padding:10px;}}
h2{{color:#667eea;margin:6px 0;}}
table{{border-collapse:collapse;}}
td,th{{white-space:nowrap;word-break:keep-all;}}
tr:nth-child(even){{background:#f8f9fa;}}
</style></head><body>
<h2>七星172 多仓位回测对比 (top1~5)</h2>
<p style="color:#888;">回测区间: 2025-01-02 ~ 2026-05-30 | 39只ETF | {now}</p>

<h3>📊 关键指标对比</h3>
<table style="font-size:13px;">
<tr style="background:#667eea;color:#fff;"><th style="padding:6px 10px;text-align:right;">指标</th>
<th style="padding:6px 10px;">top1</th><th style="padding:6px 10px;">top2</th><th style="padding:6px 10px;">top3</th><th style="padding:6px 10px;">top4</th><th style="padding:6px 10px;">top5</th></tr>
{comp_rows}
</table>

<h3>🔄 每日实际持仓ETF数分布 (自动减仓)</h3>
<p style="color:#888;font-size:12px;">绿色: 因合格ETF不足，自动减至实际可持仓数</p>
<table style="font-size:13px;">
<tr style="background:#667eea;color:#fff;"><th>策略</th><th>持1只</th><th>持2只</th><th>持3只</th><th>持4只</th><th>持5只</th></tr>
{auto_reduce_rows}
</table>

<p style="color:#888;font-size:11px;margin-top:16px;">
<b>规则:</b> 每日最大持仓 = min(holdings_num, 通过过滤的ETF数)。仅当0只合格时才进入货基防御。<br>
<b>粗体</b> = 该项指标最优。
</p>
</body></html>'''

# Save and optionally send
report_path = PROJECT / 'reporting' / 'template' / '七星172多仓位回测.html'
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(html, encoding='utf-8')
print(f'\nReport: {report_path}')

if SEND_EMAIL:
    SMTP_SERVER, SMTP_PORT = "smtp.qq.com", 465
    SENDER = "848786642@qq.com"
    PASSWORD = "ljbtvacrctjobfed"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[多仓位对比] 七星172 top1~5 回测报告 - {now}"
    msg["From"] = SENDER
    msg["To"] = SENDER
    msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as srv:
            srv.login(SENDER, PASSWORD)
            srv.sendmail(SENDER, SENDER, msg.as_string())
        print('Mail sent to 848786642@qq.com')
    except Exception as e:
        print(f'Mail failed: {e}')
