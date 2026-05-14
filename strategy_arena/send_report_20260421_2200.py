#!/usr/bin/env python3
"""发送策略回测扫描完整报告邮件 - 2026-04-21 22:00"""
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

us_strategies = [s for s in all_rejected if s.get('market') == 'us']
hk_strategies = [s for s in all_rejected if s.get('market') == 'hk']

# 加载排行榜
try:
    with open('/data/workspace/strategy_arena/leaderboard.json', 'r', encoding='utf-8') as f:
        leaderboard = json.load(f)
except:
    leaderboard = []

def dd_color(val):
    if val > 40: return '#e74c3c'
    elif val > 25: return '#e67e22'
    else: return '#27ae60'

def score_color(val):
    if val >= 80: return '#27ae60'
    elif val >= 50: return '#e67e22'
    else: return '#e74c3c'

def return_color(val):
    if val > 0: return '#27ae60'
    else: return '#e74c3c'

# ==================== 美股回测数据 ====================
us_backtest_data = [
    {"name": "Supertrend ATR自适应趋势跟踪", "type": "趋势跟踪", "fp": "4c1073f1", "score": 0, "ret": 7.08, "sharpe": 0.42, "dd": 39.92, "pf": 10.0, "wr": 0, "trades": 0.3, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "Donchian通道突破(海龟交易法)", "type": "趋势跟踪", "fp": "53092435", "score": 0, "ret": 1.13, "sharpe": 0.11, "dd": 28.55, "pf": 1.48, "wr": 41.4, "trades": 4.0, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "MACD+Supertrend双重过滤", "type": "趋势跟踪", "fp": "b770f27a", "score": 0, "ret": 1.23, "sharpe": 0.18, "dd": 33.06, "pf": 1.16, "wr": 39.4, "trades": 9.4, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "EMA交叉+ADX趋势强度过滤", "type": "趋势跟踪", "fp": "1a31ebc7", "score": 0, "ret": 4.8, "sharpe": 0.33, "dd": 36.94, "pf": 1.66, "wr": 43.8, "trades": 6.0, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "高股息轮动策略", "type": "趋势跟踪", "fp": "6be4ae8d", "score": 0, "ret": -2.57, "sharpe": -0.2, "dd": 32.29, "pf": 0.91, "wr": 44.3, "trades": 10.5, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "Keltner通道突破策略", "type": "趋势跟踪", "fp": "7632ef57", "score": 0, "ret": 2.16, "sharpe": 0.13, "dd": 32.36, "pf": 4.07, "wr": 40.0, "trades": 1.8, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "MACD金叉+趋势确认策略", "type": "趋势跟踪", "fp": "6755e0af", "score": 15.66, "ret": -0.75, "sharpe": -0.14, "dd": 21.65, "pf": 1.02, "wr": 36.7, "trades": 5.3, "pass": False, "reason": "年化<15%; 夏普<0.5"},
    {"name": "Triple EMA三层均线策略", "type": "趋势跟踪", "fp": "b5f7b315", "score": 0, "ret": 0.11, "sharpe": 0.0, "dd": 32.24, "pf": 1.38, "wr": 34.2, "trades": 3.7, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "VWAP趋势跟踪策略", "type": "趋势跟踪", "fp": "5046ba27", "score": 0, "ret": -2.98, "sharpe": -0.1, "dd": 36.88, "pf": 0.94, "wr": 35.3, "trades": 14.2, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "RSI趋势确认策略", "type": "趋势跟踪", "fp": "239cb63e", "score": 0, "ret": -2.07, "sharpe": -0.09, "dd": 36.46, "pf": 0.98, "wr": 33.0, "trades": 10.9, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
]

# ==================== 港股回测数据 ====================
hk_backtest_data = [
    {"name": "Supertrend ATR自适应趋势跟踪", "type": "趋势跟踪", "fp": "4c1073f1", "score": 0, "ret": 9.13, "sharpe": 0.19, "dd": 61.03, "pf": 10.0, "wr": 0, "trades": 0.3, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "Donchian通道突破(海龟交易法)", "type": "趋势跟踪", "fp": "53092435", "score": 0, "ret": 0.62, "sharpe": 0.0, "dd": 43.15, "pf": 1.04, "wr": 34.5, "trades": 3.6, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "Dual Momentum双动量策略", "type": "趋势跟踪", "fp": "57856069", "score": 0, "ret": -4.16, "sharpe": -0.32, "dd": 30.93, "pf": 1.04, "wr": 31.1, "trades": 4.7, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "MACD+Supertrend双重过滤", "type": "趋势跟踪", "fp": "b770f27a", "score": 0, "ret": -0.97, "sharpe": 0.07, "dd": 50.81, "pf": 1.01, "wr": 35.2, "trades": 9.5, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "EMA交叉+ADX趋势强度过滤", "type": "趋势跟踪", "fp": "1a31ebc7", "score": 0, "ret": 12.58, "sharpe": 0.22, "dd": 54.56, "pf": 1.24, "wr": 39.0, "trades": 6.7, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "布林带均值回归策略", "type": "趋势跟踪", "fp": "743c7e87", "score": 0, "ret": 1.37, "sharpe": 0.24, "dd": 37.92, "pf": 2.81, "wr": 60.0, "trades": 4.6, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "高股息轮动策略", "type": "趋势跟踪", "fp": "6be4ae8d", "score": 0, "ret": -7.56, "sharpe": -0.43, "dd": 43.46, "pf": 0.77, "wr": 37.4, "trades": 9.0, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "Keltner通道突破策略", "type": "趋势跟踪", "fp": "7632ef57", "score": 0, "ret": -1.0, "sharpe": -0.06, "dd": 48.6, "pf": 2.23, "wr": 28.8, "trades": 1.6, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "Triple EMA三层均线策略", "type": "趋势跟踪", "fp": "b5f7b315", "score": 0, "ret": 6.99, "sharpe": -0.22, "dd": 44.84, "pf": 0.81, "wr": 26.8, "trades": 3.3, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "VWAP趋势跟踪策略", "type": "趋势跟踪", "fp": "5046ba27", "score": 0, "ret": -3.85, "sharpe": -0.14, "dd": 52.82, "pf": 0.84, "wr": 31.8, "trades": 14.5, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
    {"name": "RSI趋势确认策略", "type": "趋势跟踪", "fp": "239cb63e", "score": 0, "ret": -1.95, "sharpe": -0.18, "dd": 50.29, "pf": 0.93, "wr": 28.7, "trades": 11.1, "pass": False, "reason": "回撤>25%; 年化<15%; 夏普<0.5; 得分0"},
]

# ==================== 排行榜数据 ====================
top5 = leaderboard

# ==================== 构建回测表格 ====================
def build_backtest_table(data, market_label):
    rows = ''
    for i, s in enumerate(data, 1):
        pass_icon = '✅' if s['pass'] else '❌'
        pass_bg = '#e8f5e9' if s['pass'] else '#fff5f5'
        rows += f'''
        <tr style="background:{pass_bg};">
            <td style="text-align:center;padding:6px;">{i}</td>
            <td style="padding:6px;"><b>{s['name']}</b><br><span style="font-size:11px;color:#888;">{s['type']} | {s['fp']}</span></td>
            <td style="text-align:center;padding:6px;color:{score_color(s['score'])};font-weight:bold;">{s['score']:.2f}</td>
            <td style="text-align:center;padding:6px;color:{return_color(s['ret'])};">{s['ret']:.2f}%</td>
            <td style="text-align:center;padding:6px;">{s['sharpe']:.2f}</td>
            <td style="text-align:center;padding:6px;color:{dd_color(s['dd'])};font-weight:bold;">{s['dd']:.2f}%</td>
            <td style="text-align:center;padding:6px;">{s['pf']:.2f}</td>
            <td style="text-align:center;padding:6px;">{s['wr']:.1f}%</td>
            <td style="text-align:center;padding:6px;">{s['trades']:.1f}</td>
            <td style="text-align:center;padding:6px;">{pass_icon}</td>
            <td style="padding:6px;color:#e74c3c;font-size:12px;">{s['reason']}</td>
        </tr>'''
    
    return f'''
    <h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px;">
        {market_label} 全部策略回测数据 ({len(data)}个)
    </h2>
    <div style="overflow-x:auto;">
    <table style="border-collapse:collapse;width:100%;font-size:13px;">
        <thead>
            <tr style="background:#2c3e50;color:white;">
                <th style="padding:8px;">#</th>
                <th style="padding:8px;">策略名称</th>
                <th style="padding:8px;">得分</th>
                <th style="padding:8px;">年化收益</th>
                <th style="padding:8px;">夏普</th>
                <th style="padding:8px;">最大回撤</th>
                <th style="padding:8px;">盈亏比</th>
                <th style="padding:8px;">胜率</th>
                <th style="padding:8px;">年交易</th>
                <th style="padding:8px;">通过</th>
                <th style="padding:8px;">未通过原因</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    </div>'''

# ==================== 构建排行榜详情 ====================
def build_top5_detail():
    cards = ''
    rank_icons = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    rank_colors = ['#ffd700', '#c0c0c0', '#cd7f32', '#607d8b', '#607d8b']
    
    for i, s in enumerate(top5):
        market_flag = '🇭🇰' if s.get('market') == 'HK' else '🇺🇸'
        params = s.get('strategy_params', {})
        params_str = ', '.join([f"{k}={v}" for k, v in params.items()]) if params else 'N/A'
        stress_info = f"压力期年化{s.get('stress_annual', 0)}%/回撤{s.get('stress_dd', 0)}%"
        
        cards += f'''
        <div style="border:2px solid {rank_colors[i]};border-radius:10px;margin-bottom:15px;overflow:hidden;">
            <div style="background:{rank_colors[i]}20;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:18px;">{rank_icons[i]} 第{s.get('total_score', 0):.0f}名: {s.get('strategy_name', '')} {market_flag} ({s.get('market', '')})</span>
                <span style="font-size:22px;font-weight:bold;color:{rank_colors[i]};">{s.get('total_score', 0):.2f}分</span>
            </div>
            <div style="padding:15px 20px;">
                <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;">
                    <div style="flex:1;min-width:120px;background:#f8f9fa;border-radius:6px;padding:8px 12px;">
                        <div style="font-size:11px;color:#888;">年化收益</div>
                        <div style="font-size:18px;font-weight:bold;color:{return_color(s.get('annual_return', 0))};">{s.get('annual_return', 0):.2f}%</div>
                    </div>
                    <div style="flex:1;min-width:120px;background:#f8f9fa;border-radius:6px;padding:8px 12px;">
                        <div style="font-size:11px;color:#888;">夏普比率</div>
                        <div style="font-size:18px;font-weight:bold;">{s.get('sharpe', 0):.2f}</div>
                    </div>
                    <div style="flex:1;min-width:120px;background:#f8f9fa;border-radius:6px;padding:8px 12px;">
                        <div style="font-size:11px;color:#888;">最大回撤</div>
                        <div style="font-size:18px;font-weight:bold;color:{dd_color(s.get('max_drawdown', 0))};">{s.get('max_drawdown', 0):.2f}%</div>
                    </div>
                    <div style="flex:1;min-width:120px;background:#f8f9fa;border-radius:6px;padding:8px 12px;">
                        <div style="font-size:11px;color:#888;">盈亏比</div>
                        <div style="font-size:18px;font-weight:bold;">{s.get('profit_factor', 0):.2f}</div>
                    </div>
                    <div style="flex:1;min-width:120px;background:#f8f9fa;border-radius:6px;padding:8px 12px;">
                        <div style="font-size:11px;color:#888;">胜率</div>
                        <div style="font-size:18px;font-weight:bold;">{s.get('win_rate', 0):.1f}%</div>
                    </div>
                    <div style="flex:1;min-width:120px;background:#f8f9fa;border-radius:6px;padding:8px 12px;">
                        <div style="font-size:11px;color:#888;">年交易次数</div>
                        <div style="font-size:18px;font-weight:bold;">{s.get('avg_trades_per_year', 0):.1f}</div>
                    </div>
                </div>
                <div style="display:flex;gap:15px;font-size:13px;color:#555;">
                    <div><b>策略类型:</b> {s.get('strategy_type', '')}</div>
                    <div><b>策略参数:</b> {params_str}</div>
                </div>
                <div style="display:flex;gap:15px;font-size:13px;color:#555;margin-top:6px;">
                    <div><b>压力测试:</b> {stress_info}</div>
                </div>
                <div style="font-size:13px;color:#777;margin-top:6px;"><b>描述:</b> {s.get('strategy_description', '')}</div>
            </div>
        </div>'''
    
    return f'''
    <h2 style="color:#2c3e50;border-bottom:2px solid #f39c12;padding-bottom:8px;">
        🏆 历史前五高评分策略排行榜
    </h2>
    {cards}'''

# ==================== 构建废弃策略表格 ====================
def build_rejected_table(strategies, market_label):
    rows = ''
    for i, s in enumerate(strategies, 1):
        dd = s.get('max_drawdown', 0)
        ret = s.get('annual_return', 0)
        score = s.get('total_score', 0)
        rows += f'''
        <tr>
            <td style="text-align:center;padding:5px;">{i}</td>
            <td style="padding:5px;"><b>{s.get('strategy_name', '')}</b></td>
            <td style="text-align:center;padding:5px;color:{score_color(score)};font-weight:bold;">{score:.2f}</td>
            <td style="text-align:center;padding:5px;color:{return_color(ret)};">{ret:.2f}%</td>
            <td style="text-align:center;padding:5px;">{s.get('sharpe', 0):.2f}</td>
            <td style="text-align:center;padding:5px;color:{dd_color(dd)};font-weight:bold;">{dd:.2f}%</td>
            <td style="padding:5px;color:#e74c3c;font-size:12px;">{s.get('rejection_reason', '')}</td>
            <td style="padding:5px;font-size:11px;color:#888;">{s.get('rejected_time', '')}</td>
        </tr>'''
    
    return f'''
    <h3 style="color:#2c3e50;">🗑️ {market_label} 废弃策略 ({len(strategies)}个)</h3>
    <div style="overflow-x:auto;">
    <table style="border-collapse:collapse;width:100%;font-size:12px;">
        <thead>
            <tr style="background:#7f8c8d;color:white;">
                <th style="padding:6px;">#</th>
                <th style="padding:6px;">策略名称</th>
                <th style="padding:6px;">得分</th>
                <th style="padding:6px;">年化</th>
                <th style="padding:6px;">夏普</th>
                <th style="padding:6px;">回撤</th>
                <th style="padding:6px;">废弃原因</th>
                <th style="padding:6px;">废弃时间</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    </div>'''

# ==================== 组装HTML ====================
now = datetime.now()
html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Microsoft YaHei','Segoe UI',Arial,sans-serif;background:#f5f6fa;margin:0;padding:20px;">
<div style="max-width:1200px;margin:0 auto;background:white;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">

<!-- 头部 -->
<div style="background:linear-gradient(135deg,#2c3e50,#3498db);color:white;padding:30px;">
    <h1 style="margin:0;font-size:24px;">🤖 策略回测定时扫描报告</h1>
    <p style="margin:8px 0 0;opacity:0.85;font-size:14px;">
        扫描时间：{now.strftime('%Y-%m-%d %H:%M:%S')} | 
        美股耗时：331秒 | 港股耗时：164秒
    </p>
</div>

<!-- 概览卡片 -->
<div style="display:flex;flex-wrap:wrap;padding:20px;gap:12px;">
    <div style="flex:1;min-width:140px;background:#e3f2fd;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#1976d2;">13+13</div>
        <div style="font-size:12px;color:#888;">发现策略(US+HK)</div>
    </div>
    <div style="flex:1;min-width:140px;background:#fff3e0;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#e67e22;">9+11</div>
        <div style="font-size:12px;color:#888;">去重后新策略</div>
    </div>
    <div style="flex:1;min-width:140px;background:#e8f5e9;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#27ae60;">9+11</div>
        <div style="font-size:12px;color:#888;">回测验证数量</div>
    </div>
    <div style="flex:1;min-width:140px;background:#ffebee;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#e74c3c;">0+0</div>
        <div style="font-size:12px;color:#888;">上榜策略</div>
    </div>
    <div style="flex:1;min-width:140px;background:#fce4ec;border-radius:8px;padding:15px;text-align:center;">
        <div style="font-size:28px;font-weight:bold;color:#c62828;">{len(all_rejected)}</div>
        <div style="font-size:12px;color:#888;">废弃策略库累计</div>
    </div>
</div>

<!-- 美股扫描概要 -->
<div style="padding:0 20px 10px;">
    <div style="background:#e3f2fd;border-left:4px solid #1976d2;padding:12px 15px;border-radius:0 8px 8px 0;">
        <b>🇺🇸 美股扫描:</b> 发现13 → 去重后9 → 回测9 → 有评分2(得分>0) / 零分9(回撤>25%)
        <br><b>美股最优:</b> Supertrend ATR自适应 年化7.08%/夏普0.42/回撤39.92%
    </div>
</div>
<div style="padding:0 20px 15px;">
    <div style="background:#fff3e0;border-left:4px solid #e67e22;padding:12px 15px;border-radius:0 8px 8px 0;">
        <b>🇭🇰 港股扫描:</b> 发现13 → 去重后11 → 回测11 → 有评分0 / 零分11(全部回撤>25%)
        <br><b>港股最优:</b> EMA+ADX趋势过滤 年化12.58%/夏普0.22/回撤54.56%
    </div>
</div>

<!-- 全部策略回测数据 - 美股 -->
<div style="padding:0 20px 20px;overflow-x:auto;">
    {build_backtest_table(us_backtest_data, '🇺🇸 美股')}
</div>

<!-- 全部策略回测数据 - 港股 -->
<div style="padding:0 20px 20px;overflow-x:auto;">
    {build_backtest_table(hk_backtest_data, '🇭🇰 港股')}
</div>

<!-- 历史前五排行榜 -->
<div style="padding:0 20px 20px;">
    {build_top5_detail()}
</div>

<!-- 废弃策略库 -->
<div style="padding:0 20px 20px;">
    <h2 style="color:#2c3e50;border-bottom:2px solid #7f8c8d;padding-bottom:8px;">
        🗑️ 废弃策略库 (累计{len(all_rejected)}个: 美股{len(us_strategies)} + 港股{len(hk_strategies)})
    </h2>
    {build_rejected_table(us_strategies, '🇺🇸 美股')}
    <div style="height:15px;"></div>
    {build_rejected_table(hk_strategies, '🇭🇰 港股')}
</div>

<!-- 核心洞察 -->
<div style="padding:0 20px 20px;">
    <div style="background:#e8f5e9;border-left:4px solid #27ae60;padding:15px;border-radius:0 8px 8px 0;">
        <h3 style="margin:0 0 8px;color:#2c3e50;">💡 核心洞察</h3>
        <ul style="margin:0;padding-left:20px;font-size:13px;color:#555;">
            <li>修正T+1+手续费后，所有纯趋势策略均无法同时满足年化≥15% + 最大回撤≤25%</li>
            <li>美股9/9策略回撤>25%，港股11/11全部回撤>25%</li>
            <li>港股趋势策略回撤平均~50%，最高61%（Supertrend ATR）</li>
            <li>排行榜得分普遍偏低（最高31.62分），与理想80分差距甚远</li>
            <li>10个内置策略已穷尽验证，连续多轮扫描结果完全一致</li>
            <li>底仓50%组合模式可能是唯一出路（参考此前Supertrend+底仓50%=年化11.64%/夏普1.07）</li>
        </ul>
    </div>
</div>

<!-- 页脚 -->
<div style="background:#f8f9fa;padding:15px 20px;text-align:center;color:#888;font-size:12px;border-top:1px solid #eee;">
    Blakever 策略回测系统 · 自动扫描报告 · {now.strftime('%Y-%m-%d %H:%M')}
</div>

</div>
</body>
</html>'''

# 发送邮件
msg = MIMEMultipart("mixed")
msg["Subject"] = f"【策略回测报告】{now.strftime('%Y-%m-%d')} {now.strftime('%H:%M')}"
msg["From"] = SENDER
msg["To"] = RECEIVER
msg["Date"] = now.strftime("%a, %d %b %Y %H:%M:%S +0800")
msg.attach(MIMEText(html, "html", "utf-8"))

# 附上JSON数据
att = MIMEText(json.dumps(all_rejected, ensure_ascii=False, indent=2), "plain", "utf-8")
att.add_header("Content-Disposition", "attachment", filename="rejected_strategies.json")
msg.attach(att)

with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
    server.login(SENDER, PASSWORD)
    server.sendmail(SENDER, RECEIVER, msg.as_string())

print(f"✅ 邮件已发送至 {RECEIVER}")
print(f"   标题: 【策略回测报告】{now.strftime('%Y-%m-%d')} {now.strftime('%H:%M')}")
