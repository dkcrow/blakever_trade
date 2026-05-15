#!/usr/bin/env python3
"""用现有排行榜和策略库数据重新生成穿越牛熊报告并发送（用于验证上榜标注功能）"""
import json
import os
import sys
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, '/data/workspace/strategy_arena')

from cross_regime_scheduler import generate_email, SMTP_USER, EMAIL_TO, SMTP_SERVER, SMTP_PORT, SMTP_PASSWORD

STRATEGY_DIR = '/data/workspace/strategy_arena'

# 加载排行榜数据（三市场）
all_lbs = {}
for market in ['US', 'HK', 'CN']:
    lb_path = os.path.join(STRATEGY_DIR, f'leaderboard_cross_regime_{market.lower()}.json')
    if os.path.exists(lb_path):
        with open(lb_path, 'r', encoding='utf-8') as f:
            all_lbs[market] = json.load(f)
        print(f"  ✅ 加载{market}排行榜: {len(all_lbs[market])}个策略")
    else:
        all_lbs[market] = []

# 加载废弃策略数据（三市场）
all_rjs = {}
for market in ['US', 'HK', 'CN']:
    rj_path = os.path.join(STRATEGY_DIR, f'rejected_strategies_cross_regime_{market.lower()}.json')
    if os.path.exists(rj_path):
        with open(rj_path, 'r', encoding='utf-8') as f:
            all_rjs[market] = json.load(f)
        print(f"  ✅ 加载{market}废弃库: {len(all_rjs[market])}个策略")
    else:
        all_rjs[market] = []

# 加载策略库
lib_path = os.path.join(STRATEGY_DIR, 'strategy_library_cross_regime.json')
with open(lib_path, 'r', encoding='utf-8') as f:
    strategy_lib = json.load(f)

# 构建三市场得分映射（从排行榜和策略库中提取）
multi_market_map = {}  # strategy_name -> {US: score, HK: score, CN: score}
for market, lb in all_lbs.items():
    for entry in lb:
        sn = entry.get('strategy_name', '')
        ts = entry.get('total_score', 0)
        if sn:
            multi_market_map.setdefault(sn, {})[market] = ts

# 为策略库中的策略也补充得分
for s in strategy_lib.get('strategies', []):
    sn = s.get('strategy_name', '')
    mkt = s.get('market', '')
    ts = s.get('total_score', 0)
    if sn and mkt:
        multi_market_map.setdefault(sn, {})[mkt] = max(
            multi_market_map.get(sn, {}).get(mkt, 0), ts
        )

# 从策略库的strategies列表中提取结果（构造兼容 generate_email 的字典）
results = []
for s in strategy_lib.get('strategies', []):
    strategy_name = s.get('strategy_name', '')
    sd = s.get('score_detail', {})
    stress = s.get('stress_test')
    mms = multi_market_map.get(strategy_name, {})
    
    results.append({
        'strategy': strategy_name,
        'type': s.get('strategy_type', ''),
        'source': s.get('source', ''),
        'market': s.get('market', ''),
        'score': s.get('total_score', 0),
        'passed': True,
        'backtest_time': s.get('timestamp', ''),
        'annual': s.get('annual_return', 0),
        'sharpe': s.get('sharpe', 0),
        'drawdown': s.get('max_drawdown', 0),
        'calmar': s.get('calmar', 0),
        'win_rate': s.get('win_rate', 0),
        'profit_factor': s.get('profit_factor', 0),
        'reason': '',
        'cross_robust': s.get('cross_robust', False),
        'survivorship_bias': s.get('survivorship_bias_flag', True),
        'timing_discovery': 0.001,
        'timing_coding': 0.001,
        'timing_backtest': 5.0,
        'timing_total': 5.002,
        'multi_market_scores': mms,
        'url': '',
        'pine_code': '',
        'strategy_params': s.get('strategy_params', {}),
        'stress_test': stress,
        'pine_script_rejected': s.get('pine_script_rejected', False),
        'portability_score': s.get('portability_score', 0),
        'fingerprint': s.get('fingerprint', ''),
        'batch_symbol_count': s.get('batch_symbol_count', 0),
        'batch_profitable_ratio': s.get('batch_profitable_ratio', 0),
        'validation_status': s.get('validation_status', ''),
    })

results.sort(key=lambda x: x.get('score', 0), reverse=True)
print(f"\n  📊 共加载 {len(results)} 条有效策略结果")

# 检查哪些策略会上榜
from collections import defaultdict
leaderboard_names = defaultdict(list)
for mkt, lb in all_lbs.items():
    for rank, entry in enumerate(lb, 1):
        sn = entry.get('strategy_name', '')
        if sn:
            leaderboard_names[sn].append((mkt, rank))
print(f"\n  🏆 排行榜上榜策略: {len(leaderboard_names)}个")
for sn, info in leaderboard_names.items():
    print(f"    {sn}: {info}")

# 生成邮件
scan_start = datetime.now()
duration = 0.0
new_best = {mkt: lb[0].get('strategy_name', '') for mkt, lb in all_lbs.items() if lb}
search_stats = {'total_searched': len(results), 'new_strategies': len(results), 'backtested': len(results)}
risk_free_rate = 0.045

print("\n  🔄 正在生成报告HTML...")
html_content = generate_email(
    results=results,
    leaderboard=all_lbs,
    rejected=all_rjs,
    scan_start=scan_start,
    duration=duration,
    new_best=new_best,
    search_stats=search_stats,
    risk_free_rate=risk_free_rate,
    survivorship_bias=True,
    all_market_data=None
)

# 保存报告
report_path = os.path.join(STRATEGY_DIR, f'preview_report_{scan_start.strftime("%Y%m%d_%H%M%S")}.html')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(html_content)
print(f"  📄 报告已保存: {report_path}")

# 发送邮件
date_str = scan_start.strftime('%Y-%m-%d')
time_str = scan_start.strftime('%H:%M')

msg = MIMEMultipart('alternative')
msg['Subject'] = f'【穿越牛熊策略回测报告·预览】{date_str} {time_str}'
msg['From'] = SMTP_USER
msg['To'] = EMAIL_TO
msg.attach(MIMEText(html_content, 'html', 'utf-8'))

try:
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
    print(f"  📧 邮件已发送至 {EMAIL_TO}")
except Exception as e:
    print(f"  ❌ 邮件发送失败: {e}")
