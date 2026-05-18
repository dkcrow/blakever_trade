#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V4评分体系全量重评 + 等级标签报告生成
对港美A股排行榜上所有策略应用V4对数+安全区奖励评分体系
"""

import json
import math
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# 添加项目路径
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import (
    compute_total_score, get_grade, score_annual_return, score_sharpe,
    score_max_drawdown, score_profit_factor, score_win_rate
)

# 排行榜文件路径
LB_FILES = {
    'US': '/data/workspace/strategy_arena/leaderboard_cross_regime_us.json',
    'HK': '/data/workspace/strategy_arena/leaderboard_cross_regime_hk.json',
    'CN': '/data/workspace/strategy_arena/leaderboard_cross_regime_cn.json',
}

MARKET_LABELS = {'US': '美股', 'HK': '港股', 'CN': 'A股'}
MARKET_FLAGS = {'US': '🇺🇸', 'HK': '🇭🇰', 'CN': '🇨🇳'}
MEDALS = ['🥇', '🥈', '🥉', '4', '5', '6', '7', '8', '9', '10']

# 等级对应颜色
GRADE_COLORS = {
    'S+': '#ff4500',
    'S': '#f97316',
    'A': '#22c55e',
    'B': '#3b82f6',
    'C': '#a855f7',
    'D': '#6b7280',
    'F': '#374151',
}


def rescore_strategy(entry: dict) -> dict:
    """用V4评分体系对单个策略重新评分"""
    annual = entry.get('annual_return', 0)
    sharpe = entry.get('sharpe', 0)
    dd = abs(entry.get('max_drawdown', 0))
    pf = entry.get('profit_factor', 0)
    wr = entry.get('win_rate', 0)
    robust = entry.get('cross_robust', False)
    bias = entry.get('survivorship_bias_flag', True)
    monthly_rate = entry.get('monthly_stability_bonus', 0)
    # 反推monthly_positive_rate：5分→0.75, 3分→0.6, 0分→0.0
    if monthly_rate >= 5:
        monthly_positive_rate = 0.75
    elif monthly_rate >= 3:
        monthly_positive_rate = 0.6
    else:
        monthly_positive_rate = 0.0

    score_result = compute_total_score(
        annual_return=annual,
        sharpe=sharpe,
        max_drawdown=dd,
        profit_factor=pf,
        win_rate=wr,
        cross_period_robust=robust,
        survivorship_bias=bias,
        monthly_positive_rate=monthly_positive_rate,
    )

    # 更新策略条目
    entry['total_score'] = score_result['total_score']
    entry['grade'] = score_result['grade']
    entry['base_score'] = score_result['base_score']
    entry['score_detail'] = score_result
    entry['cross_period_bonus'] = score_result['cross_period_bonus']
    entry['survivorship_penalty'] = score_result['survivorship_penalty']
    entry['monthly_stability_bonus'] = score_result['monthly_stability_bonus']
    entry['rescored_at'] = f"2026-04-27 v4"

    return entry


def rescore_all():
    """对三市场所有策略重新V4评分"""
    all_strategies = {}
    for market, filepath in LB_FILES.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                strategies = json.load(f)
        except Exception as e:
            print(f"[WARN] 读取{market}排行榜失败: {e}")
            strategies = []

        # V4重评分
        rescored = []
        for entry in strategies:
            rescored.append(rescore_strategy(entry))

        # 按新分数排序
        rescored.sort(key=lambda x: x.get('total_score', 0), reverse=True)
        all_strategies[market] = rescored

        # 保存回文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(rescored, f, ensure_ascii=False, indent=2)

        print(f"[OK] {market}市场: {len(rescored)}个策略V4重评分完成")
        for i, s in enumerate(rescored[:3]):
            print(f"  TOP{i+1}: {s['strategy_name'][:20]}... → {s['total_score']:.2f}分 ({s['grade']})")

    return all_strategies


def build_html_report(all_strategies: dict) -> str:
    """生成带等级标签的HTML报告"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 背景图URL（Base64 1x1透明图）
    BG_BODY = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPg4REBAABUAC3Q9Pc3AAAAAElFTkSuQmCC"
    BG_CARD = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPg4REBAABUAC3Q9Pc3AAAAAElFTkSuQmCC"

    total_count = sum(len(v) for v in all_strategies.values())

    # 统计各等级数量
    grade_counts = {}
    for market, strategies in all_strategies.items():
        for s in strategies:
            g = s.get('grade', 'F')
            grade_counts[g] = grade_counts.get(g, 0) + 1

    # 各市场排行榜HTML
    leaderboard_sections = ''
    for market in ['US', 'HK', 'CN']:
        strategies = all_strategies.get(market, [])
        m_label = MARKET_LABELS[market]
        m_flag = MARKET_FLAGS[market]

        section = f'''
        <details style="margin-top:12px;margin-bottom:8px;border-radius:8px;border:1px solid rgba(249,115,22,0.12);overflow:hidden">
          <summary style="padding:8px 12px;background:linear-gradient(90deg,rgba(249,115,22,0.15),transparent);border-left:3px solid #f97316;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">
            <span style="font-size:14px;font-weight:700;color:#f97316">{m_flag} {m_label}策略排行榜 TOP{len(strategies)}</span>
            <span style="font-size:11px;color:#6b7280">{len(strategies)}个策略</span>
          </summary>'''

        if not strategies:
            section += f'<div style="padding:20px;text-align:center;color:#6b7280;font-size:12px">暂无{m_label}策略上榜</div>'
            section += '\n        </details>'
            leaderboard_sections += section
            continue

        for i, entry in enumerate(strategies):
            score = entry.get('total_score', 0)
            grade = entry.get('grade', 'F')
            name = entry.get('strategy_name', '未知')
            annual = entry.get('annual_return', 0)
            sharpe = entry.get('sharpe', 0)
            max_dd = abs(entry.get('max_drawdown', 0))
            win_rate = entry.get('win_rate', 0)
            pf = entry.get('profit_factor', 0)
            trades = entry.get('avg_trades_per_year', 0)
            strategy_type = entry.get('strategy_type', '其他')
            params = entry.get('strategy_params', {})
            stress = entry.get('stress_test', {})
            cross_robust = entry.get('cross_robust', False)
            bias_flag = entry.get('survivorship_bias_flag', True)
            source = entry.get('source', '')
            validation_status = entry.get('validation_status', '')

            # 自适应字号
            name_font = max(9, 15 - max(0, len(name) - 8) // 2)

            # 评分颜色
            grade_color = GRADE_COLORS.get(grade, '#6b7280')
            score_color = '#f97316' if score >= 50 else '#fb923c' if score >= 28 else '#6b7280'

            # 策略参数简览
            param_str = ''
            if isinstance(params, dict):
                param_parts = [f"{k}={v}" for k, v in list(params.items())[:4]]
                param_str = ' | '.join(param_parts)
                if len(params) > 4:
                    param_str += '...'

            # 压力测试
            stress_str = ''
            if stress:
                if 'annual_return' in stress:
                    stress_str = f"年化{stress['annual_return']:.1f}%/回撤{abs(stress.get('max_drawdown', 0)):.1f}%"
                elif 'stress_annual' in stress:
                    stress_str = f"年化{stress['stress_annual']:.1f}%/回撤{abs(stress.get('stress_drawdown', 0)):.1f}%"

            # 来源标签
            source_tag = ''
            if 'local_backtest' in source or '本地' in str(source):
                source_tag = '🖥️本地'
            elif 'builtin' in source:
                source_tag = '📦内置'
            elif 'joinquant' in source.lower() or '聚宽' in source:
                source_tag = '🌐聚宽'
            elif source:
                source_tag = f'🌐{source[:8]}'

            # 验证状态
            validation_tag = ''
            if '✅' in validation_status:
                validation_tag = '<span style="color:#22c55e;font-size:10px">✅有效</span>'
            elif '⚠️' in validation_status:
                validation_tag = '<span style="color:#f97316;font-size:10px">⚠️疑似失效</span>'
            elif '🔄' in validation_status:
                validation_tag = '<span style="color:#3b82f6;font-size:10px">🔄观察中</span>'

            # V4 vs 旧评分对比
            old_score = entry.get('_old_score', None)

            # 奖牌
            medal = MEDALS[i] if i < len(MEDALS) else str(i + 1)

            # 等级徽章样式
            grade_bg = grade_color if grade in ('S+', 'S') else grade_color
            grade_badge = f'<span style="display:inline-block;background:{grade_bg};color:white;font-size:11px;font-weight:800;padding:1px 6px;border-radius:3px;letter-spacing:0.5px">{grade}</span>'

            section += f'''
            <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:8px;padding:14px 16px;margin-bottom:6px;border-left:3px solid {grade_color};border-top:1px solid rgba(249,115,22,0.08);border-bottom:1px solid rgba(249,115,22,0.08);border-right:1px solid rgba(249,115,22,0.08)">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
                <span style="font-size:14px;font-weight:bold;color:#f97316;min-width:24px">{medal}</span>
                <span style="display:inline-block;background:rgba(249,115,22,0.15);color:#fb923c;font-size:10px;padding:1px 6px;border-radius:3px">{strategy_type}</span>
                <div style="flex:1;min-width:0;overflow:hidden">
                  <span style="font-size:{name_font}px;font-weight:600;color:#e5e7eb;white-space:nowrap;overflow:hidden;display:block">{name}</span>
                </div>
              </div>
              <div style="display:flex;align-items:baseline;gap:4px;margin-bottom:8px;margin-left:30px">
                {source_tag and f'<span style="font-size:10px;color:#9ca3af">{source_tag}</span>'}
                <span style="font-size:24px;font-weight:800;color:{score_color}">{score:.1f}</span>
                <span style="font-size:12px;color:#9ca3af">分</span>
                {grade_badge}
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 12px;margin-left:30px">
                <div><span style="font-size:10px;color:#9ca3af">年化</span><br><span style="font-size:13px;font-weight:600;color:#22c55e">{annual:.1f}%</span></div>
                <div><span style="font-size:10px;color:#9ca3af">夏普</span><br><span style="font-size:13px;font-weight:600;color:#3b82f6">{sharpe:.2f}</span></div>
                <div><span style="font-size:10px;color:#9ca3af">回撤</span><br><span style="font-size:13px;font-weight:600;color:#ef4444">{max_dd:.1f}%</span></div>
                <div><span style="font-size:10px;color:#9ca3af">胜率</span><br><span style="font-size:13px;font-weight:600;color:#a855f7">{win_rate:.1f}%</span></div>
                <div><span style="font-size:10px;color:#9ca3af">盈亏比</span><br><span style="font-size:13px;font-weight:600;color:#f59e0b">{pf:.2f}</span></div>
                <div><span style="font-size:10px;color:#9ca3af">年交易</span><br><span style="font-size:13px;font-weight:600;color:#6b7280">{trades:.1f}次</span></div>
              </div>
              <div style="margin-top:6px;margin-left:30px;font-size:10px;color:#4b5563;line-height:1.5">
                📋 {param_str}
                {stress_str and f'<br>🔥 压力测试: {stress_str}'}
                {cross_robust and ' <span style="color:#22c55e">✅鲁棒</span>'}
                {bias_flag and ' <span style="color:#f59e0b">⚠️幸存者偏差</span>'}
                {validation_tag and f' {validation_tag}'}
              </div>
            </div>'''

        section += '\n        </details>'
        leaderboard_sections += section

    # 等级分布统计
    grade_order = ['S+', 'S', 'A', 'B', 'C', 'D', 'F']
    grade_stat_html = ''
    for g in grade_order:
        cnt = grade_counts.get(g, 0)
        if cnt > 0:
            gc = GRADE_COLORS.get(g, '#6b7280')
            grade_stat_html += f'<span style="display:inline-block;background:{gc};color:white;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin:2px">{g}×{cnt}</span> '

    # 完整HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>V4评分体系全量重评报告</title>
  <style>
    :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
    details summary::-webkit-details-marker {{ display: none; }}
    details summary {{ list-style: none; }}
    details summary::marker {{ display: none; content: ""; }}
  </style>
</head>
<body style="margin:0;padding:12px 8px;background-image:url({BG_BODY});background-color:#060610;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,sans-serif;color:#e5e7eb">
  <div style="max-width:580px;margin:0 auto">

    <!-- 标题卡片 -->
    <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:14px;padding:20px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="font-size:22px">🏆</span>
        <span style="font-size:20px;font-weight:800;color:#f97316;letter-spacing:1px">V4评分体系全量重评报告</span>
      </div>
      <div style="font-size:11px;color:#6b7280;line-height:1.7">
        {now_str} · 三市场共{total_count}只策略 · 对数+安全区奖励(永不截断)<br>
        <span style="color:#9ca3af">评分体系: 年化6.0×ln(1+r/12) | 夏普8.0×ln(1+s/0.5) | 盈亏比5.5×ln(pf)+1.5×(pf-1)^0.5 | 回撤安全区奖励3×(1-dd/15)</span>
      </div>
    </div>

    <!-- 等级分布 -->
    <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:10px;padding:12px 16px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
      <div style="font-size:12px;font-weight:600;color:#f97316;margin-bottom:6px">📊 等级分布</div>
      <div>{grade_stat_html}</div>
      <div style="margin-top:6px;font-size:10px;color:#6b7280">
        S+(≥75) 传奇 | S(≥62) 传奇 | A(≥50) 优秀 | B(≥40) 良好 | C(≥28) 一般 | D(≥16) 较差 | F(<16) 废策略
      </div>
    </div>

    <!-- 排行榜 -->
    <details style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)" open>
      <summary style="font-size:13px;font-weight:700;color:#f97316;letter-spacing:0.5px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">🏅 三市场策略排行榜（V4评分）</summary>
      <div style="margin-top:10px">
      {leaderboard_sections}
      </div>
    </details>

    <!-- 评分体系说明 -->
    <div style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:10px;padding:14px 16px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.08)">
      <div style="font-size:12px;font-weight:600;color:#f97316;margin-bottom:8px">📐 V4评分体系 vs V3</div>
      <div style="font-size:10px;color:#9ca3af;line-height:1.8">
        <b style="color:#ef4444">V3问题</b>: 年化≥80%/夏普≥3.7/盈亏比≥4.0撞天花板截断<br>
        → 收益更高的第二名和第一名得分一样，无法区分！<br><br>
        <b style="color:#22c55e">V4改革</b>: 对数函数替代天花板截断，永不撞顶<br>
        → 年化164%→16.1分 vs 212%→17.6分 ✓ 正确拉开差距<br>
        → 夏普3.67→15.9分 vs 4.09→17.3分 ✓ 高夏普不再一视同仁<br>
        → 盈亏比3.61→9.1分 vs 3.96→10.1分 ✓ 盈亏优势得到体现<br><br>
        <b style="color:#3b82f6">回撤安全区</b>: ≤15%回撤额外加分3×(1-dd/15)<br>
        → 5%回撤: 22.0分 | 12%回撤: 15.9分 | 15%回撤: 13.7分
      </div>
    </div>

    <!-- 数据表格 -->
    <details style="background-image:url({BG_CARD});background-color:#0c0c14;border-radius:10px;padding:12px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.08)">
      <summary style="font-size:12px;font-weight:600;color:#f97316;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">📋 完整数据表格</summary>
      <div style="margin-top:8px;overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:10px;color:#9ca3af">
          <tr style="border-bottom:1px solid rgba(249,115,22,0.15)">
            <th style="padding:4px 6px;text-align:left;color:#f97316">排名</th>
            <th style="padding:4px 6px;text-align:left;color:#f97316">等级</th>
            <th style="padding:4px 6px;text-align:left;color:#f97316">市场</th>
            <th style="padding:4px 6px;text-align:left;color:#f97316">策略</th>
            <th style="padding:4px 6px;text-align:right;color:#f97316">得分</th>
            <th style="padding:4px 6px;text-align:right;color:#f97316">年化%</th>
            <th style="padding:4px 6px;text-align:right;color:#f97316">夏普</th>
            <th style="padding:4px 6px;text-align:right;color:#f97316">回撤%</th>
            <th style="padding:4px 6px;text-align:right;color:#f97316">盈亏比</th>
            <th style="padding:4px 6px;text-align:right;color:#f97316">胜率%</th>
          </tr>'''

    rank = 1
    for market in ['CN', 'US', 'HK']:
        strategies = all_strategies.get(market, [])
        for i, s in enumerate(strategies):
            grade = s.get('grade', 'F')
            gc = GRADE_COLORS.get(grade, '#6b7280')
            html += f'''
          <tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
            <td style="padding:3px 6px">{rank}</td>
            <td style="padding:3px 6px"><span style="color:{gc};font-weight:700">{grade}</span></td>
            <td style="padding:3px 6px">{MARKET_FLAGS[market]}</td>
            <td style="padding:3px 6px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{s.get('strategy_name', '?')[:20]}</td>
            <td style="padding:3px 6px;text-align:right;font-weight:700;color:{gc}">{s.get('total_score', 0):.1f}</td>
            <td style="padding:3px 6px;text-align:right">{s.get('annual_return', 0):.1f}</td>
            <td style="padding:3px 6px;text-align:right">{s.get('sharpe', 0):.2f}</td>
            <td style="padding:3px 6px;text-align:right">{abs(s.get('max_drawdown', 0)):.1f}</td>
            <td style="padding:3px 6px;text-align:right">{s.get('profit_factor', 0):.2f}</td>
            <td style="padding:3px 6px;text-align:right">{s.get('win_rate', 0):.1f}</td>
          </tr>'''
            rank += 1

    html += '''
        </table>
      </div>
    </details>

  </div>
</body>
</html>'''

    return html


def send_email(html_content: str):
    """发送HTML邮件"""
    smtp_server = 'smtp.qq.com'
    smtp_port = 465
    sender = '848786642@qq.com'
    password = 'ljbtvacrctjobfed'
    receiver = '848786642@qq.com'

    now_str = datetime.now().strftime('%Y%m%d_%H%M')
    subject = f'【V4评分报告】{now_str} 三市场全量重评'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver

    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print(f"[OK] 邮件发送成功: {subject}")
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}")


def main():
    print("=" * 60)
    print("V4评分体系全量重评 - 港美A股排行榜")
    print("=" * 60)

    # 1. 备份原始分数
    print("\n[1] 备份原始分数...")
    for market, filepath in LB_FILES.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                strategies = json.load(f)
            for s in strategies:
                s['_old_score'] = s.get('total_score', 0)
                s['_old_grade'] = s.get('grade', 'F')
        except:
            pass

    # 2. V4重评分
    print("\n[2] 执行V4重评分...")
    all_strategies = rescore_all()

    # 3. 打印评分对比
    print("\n[3] 评分对比 (旧V3 → 新V4):")
    print("-" * 80)
    for market in ['CN', 'US', 'HK']:
        strategies = all_strategies.get(market, [])
        m_flag = MARKET_FLAGS[market]
        print(f"\n{m_flag} {MARKET_LABELS[market]}:")
        for i, s in enumerate(strategies):
            old = s.get('_old_score', 0)
            new = s.get('total_score', 0)
            old_g = s.get('_old_grade', '?')
            new_g = s.get('grade', '?')
            diff = new - old
            sign = '+' if diff > 0 else ''
            print(f"  {i+1}. {s['strategy_name'][:25]:25s}  {old:6.1f}({old_g}) → {new:6.1f}({new_g})  [{sign}{diff:.1f}]")

    # 4. 生成HTML报告
    print("\n[4] 生成HTML报告...")
    html = build_html_report(all_strategies)

    # 保存本地
    report_path = f'/data/workspace/strategy_arena/v4_rescore_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[OK] 报告已保存: {report_path}")

    # 5. 发送邮件
    print("\n[5] 发送邮件...")
    send_email(html)

    # 6. 清理临时字段
    print("\n[6] 清理临时字段并保存...")
    for market, filepath in LB_FILES.items():
        strategies = all_strategies[market]
        for s in strategies:
            s.pop('_old_score', None)
            s.pop('_old_grade', None)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(strategies, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("V4评分体系全量重评完成！")
    print("=" * 60)


if __name__ == '__main__':
    main()
