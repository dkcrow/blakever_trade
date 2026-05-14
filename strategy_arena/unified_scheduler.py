#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一策略回测定时调度器
======================
合并牛市/震荡市/熊市三套策略扫描系统为统一入口。

主入口: python unified_scheduler.py [run|status]

执行频率: 每2小时一次（由外部cron调度或AI Agent定时触发）

执行方式:
  使用子进程调用三个独立调度器，避免模块路径冲突：
  1. 牛市/全局策略扫描: strategy_arena/strategy_scheduler.py
  2. 震荡市策略扫描: strategy_arena_range/range_scheduler.py
  3. 熊市策略扫描: strategy_arena/bear_strategy_scheduler.py
  4. 读取各系统排行榜/废弃库JSON，汇总生成一封合并HTML邮件

邮件: 合并三个系统的扫描结果为一份精美手机适配HTML报告
"""

import json
import os
import subprocess
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# 项目路径
WORKSPACE_DIR = '/data/workspace' if sys.platform != 'win32' else r'C:\Users\blakehao\.qclaw\workspace\workspace_full_20260430' if sys.platform != 'win32' else r'C:\Users\blakehao\.qclaw\workspace\workspace_full_20260430'
BULL_DIR = os.path.join(WORKSPACE_DIR, 'strategy_arena')
RANGE_DIR = os.path.join(WORKSPACE_DIR, 'strategy_arena_range')

# 邮件配置
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USER = '848786642@qq.com'
SMTP_PASSWORD = 'ljbtvacrctjobfed'
EMAIL_TO = '848786642@qq.com'

# Python解释器
PYTHON = sys.executable or 'python3'


# ================================================================
# 子进程调用各调度器
# ================================================================
def _run_subprocess(cmd: str, cwd: str, label: str, market: str) -> dict:
    """子进程执行调度器命令，解析输出获取结果"""
    print(f"\n  ▶️ 执行: {label} — {market.upper()}")
    print(f"    命令: cd {cwd} && {cmd}")
    
    result = {
        'success': False,
        'stdout': '',
        'stderr': '',
        'total_found': 0,
        'new_after_dedup': 0,
        'backtest_passed': 0,
        'total_rejected_in_db': 0,
    }
    
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=1800,  # 30分钟超时
            encoding='utf-8', errors='replace'
        )
        result['stdout'] = proc.stdout
        result['stderr'] = proc.stderr
        result['success'] = proc.returncode == 0
        
        # 从输出中提取关键数据
        for line in proc.stdout.split('\n'):
            line = line.strip()
            if '本次发现策略数量' in line:
                try:
                    result['total_found'] = int(line.split(':')[-1].strip())
                except ValueError:
                    pass
            elif '通过去重后新策略数量' in line:
                try:
                    result['new_after_dedup'] = int(line.split(':')[-1].strip())
                except ValueError:
                    pass
            elif '通过回测验证数量' in line:
                try:
                    result['backtest_passed'] = int(line.split(':')[-1].strip())
                except ValueError:
                    pass
            elif '废弃策略库累计' in line:
                try:
                    val = line.split('累计')[-1].strip().replace('个', '')
                    result['total_rejected_in_db'] = int(val)
                except ValueError:
                    pass
        
        # 打印关键输出
        if proc.returncode != 0:
            print(f"    ⚠️ 退出码: {proc.returncode}")
            if proc.stderr:
                print(f"    错误: {proc.stderr[:200]}")
        else:
            print(f"    ✅ 完成: 发现{result['total_found']} → 新{result['new_after_dedup']} → 回测{result['backtest_passed']}")
    
    except subprocess.TimeoutExpired:
        result['stderr'] = '超时(30分钟)'
        print(f"    ❌ 超时")
    except Exception as e:
        result['stderr'] = str(e)
        print(f"    ❌ 异常: {e}")
    
    return result


def run_bull_scan(market: str = 'us') -> dict:
    """执行牛市/全局策略扫描"""
    cmd = f'{PYTHON} strategy_scheduler.py run --market {market}'
    return _run_subprocess(cmd, BULL_DIR, '🐂 牛市/全局扫描', market)


def run_range_scan(market: str = 'us') -> dict:
    """执行震荡市策略扫描"""
    cmd = f'{PYTHON} range_scheduler.py run --market {market}'
    return _run_subprocess(cmd, RANGE_DIR, '📊 震荡市扫描', market)


def run_bear_scan(market: str = 'us') -> dict:
    """执行熊市策略扫描"""
    cmd = f'{PYTHON} bear_strategy_scheduler.py run --market {market}'
    return _run_subprocess(cmd, BULL_DIR, '🐻 熊市扫描', market)


# ================================================================
# 主调度逻辑
# ================================================================
def run_all_scans():
    """执行全部三套系统的扫描（美股+港股），并发送合并邮件"""
    scan_start = datetime.now()
    
    results = {
        'bull': {'us': None, 'hk': None},
        'range': {'us': None, 'hk': None},
        'bear': {'us': None, 'hk': None},
    }
    
    print("=" * 70)
    print(f"  🔄 统一策略回测调度器 — 全系统扫描开始")
    print(f"  ⏰ 时间: {scan_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📋 扫描: 牛市 + 震荡市 + 熊市 × 美股 + 港股 = 6次扫描")
    print("=" * 70)
    
    for market in ['us', 'hk']:
        print(f"\n{'#'*60}")
        print(f"  🌍 市场: {market.upper()}")
        print(f"{'#'*60}")
        
        # 1. 牛市扫描
        results['bull'][market] = run_bull_scan(market)
        
        # 2. 震荡市扫描
        results['range'][market] = run_range_scan(market)
        
        # 3. 熊市扫描
        results['bear'][market] = run_bear_scan(market)
    
    scan_end = datetime.now()
    duration = (scan_end - scan_start).total_seconds()
    
    # 汇总
    summary = {
        'scan_time': scan_start.strftime('%Y-%m-%d %H:%M:%S'),
        'duration_seconds': duration,
        'results': results,
    }
    
    # 保存JSON结果
    reports_dir = os.path.join(BULL_DIR, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    json_path = os.path.join(reports_dir, 
                              f'unified_scan_{scan_start.strftime("%Y%m%d_%H%M%S")}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        # 清理不可序列化字段
        clean = {}
        for regime, markets in results.items():
            clean[regime] = {}
            for mkt, data in markets.items():
                if data:
                    clean[regime][mkt] = {k: v for k, v in data.items() 
                                          if k not in ('stdout', 'stderr')}
                else:
                    clean[regime][mkt] = data
        
        json.dump({
            'scan_time': summary['scan_time'],
            'duration_seconds': duration,
            'results': clean,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n📁 统一扫描结果已保存: {json_path}")
    
    # 生成并发送合并邮件
    try:
        html_content = generate_unified_email(results, scan_start, duration)
        send_unified_email(html_content, scan_start)
        print("  ✅ 合并邮件发送成功")
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")
        raise
    
    # 打印汇总
    print(f"\n{'='*70}")
    print(f"  ✅ 统一扫描完成")
    print(f"  ⏱️ 耗时: {duration:.0f}秒")
    print(f"  📧 邮件已发送至: {EMAIL_TO}")
    print(f"{'='*70}")
    
    return summary


# ================================================================
# HTML邮件生成
# ================================================================
def _format_score_cell(score):
    """格式化得分单元格"""
    if score is None or score == 'N/A':
        return '<span style="color:#999">—</span>'
    try:
        s = float(score)
        if s >= 50:
            return f'<span style="color:#2ecc71;font-weight:bold">{s:.1f}</span>'
        elif s >= 30:
            return f'<span style="color:#f39c12;font-weight:bold">{s:.1f}</span>'
        else:
            return f'<span style="color:#e74c3c;font-weight:bold">{s:.1f}</span>'
    except (ValueError, TypeError):
        return f'<span style="color:#999">{score}</span>'


def _format_pct(val, invert=False):
    """格式化百分比，正值绿色/负值红色"""
    if val is None or val == 'N/A':
        return '<span style="color:#999">—</span>'
    try:
        v = float(str(val).replace('%', ''))
        if invert:
            if v <= 10:
                return f'<span style="color:#2ecc71">{v:.1f}%</span>'
            elif v <= 20:
                return f'<span style="color:#f39c12">{v:.1f}%</span>'
            else:
                return f'<span style="color:#e74c3c">{v:.1f}%</span>'
        else:
            if v > 0:
                return f'<span style="color:#2ecc71">{v:.1f}%</span>'
            elif v < 0:
                return f'<span style="color:#e74c3c">{v:.1f}%</span>'
            else:
                return f'<span style="color:#999">{v:.1f}%</span>'
    except (ValueError, TypeError):
        return f'<span style="color:#999">{val}</span>'


def _format_leaderboard_cards(leaderboard, regime_label, regime_icon):
    """生成排行榜前十卡片HTML"""
    if not leaderboard or not isinstance(leaderboard, list) or len(leaderboard) == 0:
        return f'<p style="text-align:center;color:#999;padding:20px">暂无{regime_label}策略上榜</p>'
    
    medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    cards = ''
    
    for i, entry in enumerate(leaderboard[:5]):
        score = entry.get('score', 0)
        name = entry.get('name', '未知策略')
        market = entry.get('market', 'N/A')
        annual_return = entry.get('annual_return', entry.get('annualized_return', 'N/A'))
        sharpe = entry.get('sharpe_ratio', entry.get('sharpe', 'N/A'))
        max_dd = entry.get('max_drawdown', 'N/A')
        win_rate = entry.get('win_rate', 'N/A')
        profit_loss = entry.get('profit_loss_ratio', entry.get('avg_profit_loss_ratio', 'N/A'))
        trades = entry.get('annual_trades', entry.get('avg_trades_per_year', 'N/A'))
        params = entry.get('strategy_params', entry.get('params', {}))
        stress = entry.get('stress_test', {})
        
        market_color = '#3498db' if market in ('US', 'us') else '#e67e22'
        market_label = '美股' if market in ('US', 'us') else '港股'
        
        params_html = ''
        if params and isinstance(params, dict):
            param_items = [f'{k}={v}' for k, v in list(params.items())[:6]]
            params_html = ', '.join(param_items)
            if len(params) > 6:
                params_html += '...'
        
        stress_html = ''
        if stress and isinstance(stress, dict):
            stress_return = stress.get('annual_return', stress.get('annualized_return', 'N/A'))
            stress_dd = stress.get('max_drawdown', 'N/A')
            stress_html = f'''
            <div style="margin-top:8px;padding:6px 8px;background:#fff3e0;border-radius:4px;font-size:11px">
              <strong>压力测试:</strong> 年化{_format_pct(stress_return)} / 回撤{_format_pct(stress_dd, invert=True)}
            </div>'''
        
        cards += f'''
        <div style="background:#fff;border-radius:10px;padding:14px;margin-bottom:10px;
                     box-shadow:0 2px 8px rgba(0,0,0,0.08);border-left:4px solid 
                     {'#2ecc71' if score >= 50 else '#f39c12' if score >= 30 else '#e74c3c'}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div>
              <span style="font-size:18px">{medals[i]}</span>
              <strong style="font-size:14px;margin-left:4px">{name}</strong>
              <span style="display:inline-block;background:{market_color};color:#fff;
                           padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px">
                {market_label}
              </span>
            </div>
            <div style="font-size:20px;font-weight:bold">
              {_format_score_cell(score)}<span style="font-size:11px;color:#999">分</span>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:12px">
            <div>📈 年化: {_format_pct(annual_return)}</div>
            <div>📊 夏普: <span style="font-weight:bold">{sharpe if sharpe == 'N/A' else f'{float(sharpe):.2f}'}</span></div>
            <div>📉 回撤: {_format_pct(max_dd, invert=True)}</div>
            <div>💰 盈亏比: <span>{profit_loss if profit_loss == 'N/A' else f'{float(profit_loss):.2f}'}</span></div>
            <div>🎯 胜率: {_format_pct(win_rate)}</div>
            <div>🔄 年交易: <span>{trades if trades == 'N/A' else f'{float(trades):.0f}'}</span></div>
          </div>
          <div style="margin-top:6px;font-size:11px;color:#666">
            <strong>参数:</strong> {params_html or '默认'}
          </div>
          {stress_html}
        </div>'''
    
    return cards


def _load_json(path):
    """安全加载JSON文件"""
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def generate_unified_email(results, scan_start, duration):
    """生成统一合并HTML邮件内容"""
    scan_time_str = scan_start.strftime('%Y-%m-%d %H:%M:%S')
    
    regimes = [
        ('bull', '牛市/全局', '🐂', BULL_DIR),
        ('range', '震荡市', '📊', RANGE_DIR),
        ('bear', '熊市', '🐻', BULL_DIR),
    ]
    
    # ========== 统计卡片 ==========
    stats_cards = ''
    for regime_key, regime_label, icon, base_dir in regimes:
        for market_key, market_label in [('us', '美股'), ('hk', '港股')]:
            data = results.get(regime_key, {}).get(market_key, {})
            if data and data.get('success'):
                found = data.get('total_found', 0)
                new = data.get('new_after_dedup', 0)
                passed = data.get('backtest_passed', 0)
                rejected_db = data.get('total_rejected_in_db', 0)
            else:
                found = new = passed = rejected_db = '—'
            
            bg = '#e8f5e9' if market_key == 'us' else '#fff3e0'
            stats_cards += f'''
            <div style="background:{bg};border-radius:8px;padding:10px;text-align:center">
              <div style="font-size:12px;color:#666">{icon} {regime_label}·{market_label}</div>
              <div style="margin-top:4px">
                <span style="font-size:16px;font-weight:bold">{found}</span><span style="font-size:10px;color:#999">发现</span>
                <span style="margin:0 4px">→</span>
                <span style="font-size:16px;font-weight:bold">{new}</span><span style="font-size:10px;color:#999">新策略</span>
                <span style="margin:0 4px">→</span>
                <span style="font-size:16px;font-weight:bold;color:#2ecc71">{passed}</span><span style="font-size:10px;color:#999">回测</span>
              </div>
              <div style="font-size:11px;color:#999;margin-top:2px">废弃库: {rejected_db}个</div>
            </div>'''
    
    # ========== 排行榜区域 ==========
    leaderboard_sections = ''
    for regime_key, regime_label, icon, base_dir in regimes:
        # 直接读取排行榜JSON（各调度器执行完后已更新）
        if regime_key == 'bull':
            lb_path = os.path.join(BULL_DIR, 'leaderboard.json')
        elif regime_key == 'range':
            lb_path = os.path.join(RANGE_DIR, 'leaderboard_range.json')
        else:
            lb_path = os.path.join(BULL_DIR, 'bear_leaderboard.json')
        
        lb_data = _load_json(lb_path)
        lb_data.sort(key=lambda x: float(x.get('score', 0)), reverse=True)
        
        period_map = {
            'bull': '2019-2024 (5年牛市)',
            'range': '2021-2023 (3年震荡市)',
            'bear': '2022-2023 (熊市+压力测试)',
        }
        
        leaderboard_sections += f'''
        <div style="margin-top:16px">
          <div style="background:linear-gradient(135deg,#2c3e50,#3498db);color:#fff;
                       padding:10px 14px;border-radius:8px 8px 0 0;font-size:14px;font-weight:bold">
            {icon} {regime_label}策略排行榜
            <span style="font-size:11px;font-weight:normal;opacity:0.8;margin-left:8px">
              回测: {period_map[regime_key]}
            </span>
          </div>
          <div style="background:#f8f9fa;padding:10px;border-radius:0 0 8px 8px">
            {_format_leaderboard_cards(lb_data, regime_label, icon)}
          </div>
        </div>'''
    
    # ========== 废弃策略库 ==========
    rejected_sections = ''
    for regime_key, regime_label, icon, base_dir in regimes:
        if regime_key == 'bull':
            rej_path = os.path.join(BULL_DIR, 'rejected_strategies.json')
        elif regime_key == 'range':
            rej_path = os.path.join(RANGE_DIR, 'rejected_strategies_range.json')
        else:
            rej_path = os.path.join(BULL_DIR, 'bear_rejected_strategies.json')
        
        rej_data = _load_json(rej_path)
        total_rej = len(rej_data)
        display_rej = rej_data[-10:]
        
        if display_rej:
            rows = ''
            for r in display_rej:
                name = r.get('name', '未知')
                mkt = r.get('market', 'N/A')
                reason = r.get('reject_reason', r.get('reason', ''))
                ts = r.get('timestamp', r.get('rejected_at', ''))
                rows += f'''
                <tr>
                  <td style="padding:3px 6px;font-size:11px">{name[:18]}</td>
                  <td style="padding:3px 6px;font-size:11px">{mkt}</td>
                  <td style="padding:3px 6px;font-size:10px;color:#999">{reason[:24]}</td>
                  <td style="padding:3px 6px;font-size:10px;color:#bbb">{ts[:10] if ts else ''}</td>
                </tr>'''
            
            rejected_sections += f'''
            <div style="margin-top:12px">
              <div style="font-size:12px;font-weight:bold;color:#555;margin-bottom:4px">
                🗑️ {regime_label}废弃策略库 (共{total_rej}个，展示最近10个)
              </div>
              <table style="width:100%;border-collapse:collapse;font-size:11px">
                <tr style="background:#ffe0e0">
                  <th style="padding:3px 6px;text-align:left">策略</th>
                  <th style="padding:3px 6px">市场</th>
                  <th style="padding:3px 6px">废弃原因</th>
                  <th style="padding:3px 6px">日期</th>
                </tr>
                {rows}
              </table>
            </div>'''
    
    # ========== 组装完整HTML ==========
    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <style>
    body {{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
          margin:0;padding:10px;background:#f0f2f5;color:#333}}
    .container {{max-width:600px;margin:0 auto}}
  </style>
</head>
<body>
  <div class="container">
    <!-- 标题 -->
    <div style="background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;
                 padding:18px 16px;border-radius:12px;margin-bottom:14px">
      <h1 style="margin:0;font-size:18px">🔄 统一策略回测扫描报告</h1>
      <p style="margin:4px 0 0;font-size:12px;opacity:0.9">
        {scan_time_str} · 耗时{duration:.0f}秒 · 牛市+震荡+熊市三系统合并
      </p>
    </div>
    
    <!-- 统计网格 -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px">
      {stats_cards}
    </div>
    
    <!-- 排行榜 -->
    {leaderboard_sections}
    
    <!-- 废弃策略库 -->
    <div style="margin-top:16px">
      <div style="background:linear-gradient(135deg,#c0392b,#e74c3c);color:#fff;
                   padding:10px 14px;border-radius:8px;font-size:14px;font-weight:bold">
        🗑️ 废弃策略库
      </div>
      <div style="background:#fff;padding:10px;border-radius:0 0 8px 8px">
        {rejected_sections if rejected_sections else '<p style="text-align:center;color:#999;padding:10px">暂无废弃策略</p>'}
      </div>
    </div>
    
    <!-- 底部 -->
    <div style="text-align:center;color:#aaa;font-size:10px;margin-top:12px;padding:8px">
      Blakever 统一策略回测系统 · 每2小时自动扫描<br>
      牛市(2019-2024) + 震荡市(2021-2023) + 熊市(2022-2023)
    </div>
  </div>
</body>
</html>'''
    
    return html


def send_unified_email(html_content, scan_start):
    """发送统一合并邮件"""
    date_str = scan_start.strftime('%Y-%m-%d')
    time_str = scan_start.strftime('%H:%M')
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'【统一策略回测报告】{date_str} {time_str}'
    msg['From'] = SMTP_USER
    msg['To'] = EMAIL_TO
    
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
    
    print(f"  📧 邮件已发送至 {EMAIL_TO}")


# ================================================================
# 状态查看
# ================================================================
def show_status():
    """显示全部系统状态"""
    print("\n" + "=" * 60)
    print("  🔄 统一策略回测系统 — 状态总览")
    print("=" * 60)
    
    # 牛市
    bull_lb = _load_json(os.path.join(BULL_DIR, 'leaderboard.json'))
    bull_rej = _load_json(os.path.join(BULL_DIR, 'rejected_strategies.json'))
    print(f"\n  🐂 牛市排行榜: {len(bull_lb)}个策略 | 废弃库: {len(bull_rej)}个")
    for i, e in enumerate(bull_lb[:3]):
        print(f"    {i+1}. {e.get('name','?')} ({e.get('market','?')}) - {e.get('score',0):.1f}分")
    
    # 震荡市
    range_lb = _load_json(os.path.join(RANGE_DIR, 'leaderboard_range.json'))
    range_rej = _load_json(os.path.join(RANGE_DIR, 'rejected_strategies_range.json'))
    print(f"\n  📊 震荡市排行榜: {len(range_lb)}个策略 | 废弃库: {len(range_rej)}个")
    for i, e in enumerate(range_lb[:3]):
        print(f"    {i+1}. {e.get('name','?')} ({e.get('market','?')}) - {e.get('score',0):.1f}分")
    
    # 熊市
    bear_lb = _load_json(os.path.join(BULL_DIR, 'bear_leaderboard.json'))
    bear_rej = _load_json(os.path.join(BULL_DIR, 'bear_rejected_strategies.json'))
    print(f"\n  🐻 熊市排行榜: {len(bear_lb)}个策略 | 废弃库: {len(bear_rej)}个")
    for i, e in enumerate(bear_lb[:3]):
        print(f"    {i+1}. {e.get('name','?')} ({e.get('market','?')}) - {e.get('score',0):.1f}分")


# ================================================================
# 命令行入口
# ================================================================
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='统一策略回测定时调度器')
    parser.add_argument('action', choices=['run', 'status'],
                        default='status', nargs='?',
                        help='run=执行全系统扫描, status=查看状态')
    
    args = parser.parse_args()
    
    if args.action == 'run':
        result = run_all_scans()
        print(f"\n✅ 统一扫描完成，耗时{result['duration_seconds']:.0f}秒")
    else:
        show_status()
