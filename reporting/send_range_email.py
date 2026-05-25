#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""震荡市策略回测报告邮件发送"""

import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

# SMTP配置
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = "848786642@qq.com"
SMTP_PASS = "ljbtvacrctjobfed"
RECIPIENT = "848786642@qq.com"

def read_json(filepath):
    """读取JSON文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def format_percent(val):
    """格式化百分比"""
    if val is None:
        return "-"
    color = "#27ae60" if val > 0 else "#e74c3c" if val < 0 else "#555"
    return f'<span style="color:{color}">{val*100:+.2f}%</span>'

def format_positive(val, suffix=""):
    """格式化正值（绿色）"""
    if val is None:
        return "-"
    return f'<span style="color:#27ae60">{val:.2f}{suffix}</span>'

def format_negative(val, suffix=""):
    """格式化负值或高风险（红色）"""
    if val is None:
        return "-"
    return f'<span style="color:#e74c3c">{val:.2f}{suffix}</span>'

def get_rank_emoji(rank):
    """获取排名勋章"""
    emojis = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
    return emojis.get(rank, f"{rank}️⃣")

def get_market_tag(market):
    """获取市场标签"""
    colors = {"us": "#3498db", "hk": "#9b59b6"}
    labels = {"us": "美股 US", "hk": "港股 HK"}
    color = colors.get(market.lower(), "#95a5a6")
    label = labels.get(market.lower(), market.upper())
    return f'<span class="market-tag" style="background:{color}">{label}</span>'

def get_robust_tag(robust):
    """鲁棒性标签"""
    if robust:
        return '<span class="tag tag-success">✅ 鲁棒</span>'
    return '<span class="tag tag-warning">❌ 单周期</span>'

def get_stop_loss_tag(has_stop):
    """止损标签"""
    if has_stop:
        return '<span class="tag tag-success">✅ 止损</span>'
    return '<span class="tag tag-danger">❌ 无止损</span>'

def generate_email_html():
    """生成邮件HTML内容"""
    
    # 读取数据
    library_path = Path("/data/workspace/strategy_arena_range/range_strategy_library.json")
    rejected_path = Path("/data/workspace/strategy_arena_range/rejected_strategies_range.json")
    
    library = read_json(library_path)
    strategies = library.get("strategies", [])
    rejected = read_json(rejected_path)
    
    # 按得分降序排序，取前5
    top5 = sorted(strategies, key=lambda x: x.get("score", 0), reverse=True)[:5]
    
    # 排序废弃策略（按时间倒序）
    rejected_sorted = sorted(rejected, key=lambda x: x.get("rejected_at", ""), reverse=True)[:10]
    
    # 统计信息
    total_strategies = 20  # 10个US + 10个HK
    us_strategies = [s for s in strategies if s.get("market") == "us"]
    hk_strategies = [s for s in strategies if s.get("market") == "hk"]
    
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    scan_date = datetime.now().strftime("%Y-%m-%d")
    
    # 生成TOP5卡片
    top5_cards = ""
    for i, s in enumerate(top5, 1):
        market = s.get("market", "us")
        score = s.get("score", 0)
        annual = s.get("annual_return", 0)
        sharpe = s.get("sharpe", 0)
        drawdown = s.get("max_drawdown", 0)
        win_rate = s.get("win_rate", 0)
        pl_ratio = s.get("profit_loss_ratio", 0)
        avg_trades = s.get("avg_trades_per_stock", 0)
        robust = s.get("cross_period_robust", False)
        has_stop = s.get("has_stop_loss", True)
        stress = s.get("stress_test", {})
        
        top5_cards += f'''
        <div class="strategy-card">
            <div class="card-header">
                <div class="rank-badge">{get_rank_emoji(i)}</div>
                <div class="strategy-title">
                    <h3>{s.get("name", "未命名策略")}</h3>
                    <p>{s.get("type", "未知类型")}</p>
                </div>
                {get_market_tag(market)}
            </div>
            <div class="score-section">
                <div class="score-value">{score:.1f}</div>
                <div class="score-label">综合得分</div>
            </div>
            <div class="metrics-grid">
                <div class="metric-item">
                    <div class="metric-value">{format_percent(annual)}</div>
                    <div class="metric-label">年化收益</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{format_positive(sharpe)}</div>
                    <div class="metric-label">夏普比率</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{format_negative(drawdown*100, "%")}</div>
                    <div class="metric-label">最大回撤</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{format_positive(pl_ratio)}</div>
                    <div class="metric-label">盈亏比</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{format_positive(win_rate*100, "%")}</div>
                    <div class="metric-label">胜率</div>
                </div>
                <div class="metric-item">
                    <div class="metric-value">{avg_trades:.1f}</div>
                    <div class="metric-label">年交易次数</div>
                </div>
            </div>
            <div class="card-footer">
                <div class="tags">
                    {get_robust_tag(robust)}
                    {get_stop_loss_tag(has_stop)}
                </div>
                <div class="stress-test">
                    压力测试: 年化{format_percent(stress.get("annual_return", 0))} / 回撤{format_negative(stress.get("max_drawdown", 0)*100, "%")}
                </div>
            </div>
        </div>
        '''
    
    # 生成废弃策略表格
    rejected_rows = ""
    for r in rejected_sorted:
        rejected_rows += f'''
        <tr>
            <td>{r.get("name", "")}</td>
            <td>{get_market_tag(r.get("market", "us"))}</td>
            <td>{r.get("score", 0):.1f}</td>
            <td>{format_percent(r.get("annual_return", 0))}</td>
            <td>{format_negative(r.get("max_drawdown", 0)*100, "%")}</td>
            <td class="reject-reason">{r.get("rejection_reason", "")}</td>
        </tr>
        '''
    
    # 生成全部策略表格行（合并US和HK）
    all_rows = ""
    for market, market_name in [("us", "美股"), ("hk", "港股")]:
        md_path = Path(f"/data/workspace/strategy_arena_range/reports/range_scan_20260422_{'11' if market == 'us' else '11'}0132.json")
        if market == "hk":
            md_path = Path("/data/workspace/strategy_arena_range/reports/range_scan_20260422_111013.json")
        
        try:
            market_data = read_json(md_path)
            for s in market_data.get("strategies", []):
                passed = s.get("score", 0) >= 75 and s.get("max_drawdown", 1) < 0.15
                pass_tag = '<span class="tag tag-success">通过</span>' if passed else '<span class="tag tag-danger">未通过</span>'
                all_rows += f'''
                <tr>
                    <td>{s.get("name", "")}</td>
                    <td>{get_market_tag(market)}</td>
                    <td>{s.get("type", "")}</td>
                    <td>{s.get("score", 0):.1f}</td>
                    <td>{format_percent(s.get("annual_return", 0))}</td>
                    <td>{format_positive(s.get("sharpe", 0))}</td>
                    <td>{format_negative(s.get("max_drawdown", 0)*100, "%")}</td>
                    <td>{pass_tag}</td>
                </tr>
                '''
        except:
            pass
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
    <title>震荡市策略回测报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }}
        .container {{ 
            max-width: 600px; 
            margin: 0 auto;
            background: #fff;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px 20px;
            text-align: center;
        }}
        .header h1 {{ font-size: 24px; margin-bottom: 8px; font-weight: 600; }}
        .header .subtitle {{ font-size: 14px; opacity: 0.9; }}
        .header .datetime {{ font-size: 12px; opacity: 0.7; margin-top: 10px; }}
        
        .content {{ padding: 20px; }}
        
        /* 统计网格 */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 25px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
            border-radius: 12px;
            padding: 15px 10px;
            text-align: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .stat-value {{ font-size: 20px; font-weight: 700; color: #667eea; }}
        .stat-label {{ font-size: 11px; color: #666; margin-top: 4px; }}
        
        /* 策略卡片 */
        .strategy-card {{
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 3px 12px rgba(0,0,0,0.08);
            margin-bottom: 16px;
            overflow: hidden;
            border: 1px solid #f0f0f0;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            padding: 15px;
            background: linear-gradient(135deg, #fafbfc 0%, #f0f2f5 100%);
            border-bottom: 1px solid #eee;
        }}
        .rank-badge {{ font-size: 28px; margin-right: 12px; }}
        .strategy-title {{ flex: 1; }}
        .strategy-title h3 {{ font-size: 15px; color: #333; margin-bottom: 2px; }}
        .strategy-title p {{ font-size: 11px; color: #888; }}
        .market-tag {{
            font-size: 10px;
            padding: 4px 10px;
            border-radius: 20px;
            color: white;
            font-weight: 500;
        }}
        
        .score-section {{
            text-align: center;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .score-value {{ font-size: 36px; font-weight: 700; }}
        .score-label {{ font-size: 12px; opacity: 0.9; }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1px;
            background: #f0f0f0;
        }}
        .metric-item {{
            background: #fff;
            padding: 12px 8px;
            text-align: center;
        }}
        .metric-value {{ font-size: 14px; font-weight: 600; color: #333; }}
        .metric-label {{ font-size: 10px; color: #888; margin-top: 3px; }}
        
        .card-footer {{
            padding: 12px 15px;
            background: #fafbfc;
            border-top: 1px solid #eee;
        }}
        .tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
        .tag {{
            font-size: 10px;
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 500;
        }}
        .tag-success {{ background: #d4edda; color: #155724; }}
        .tag-warning {{ background: #fff3cd; color: #856404; }}
        .tag-danger {{ background: #f8d7da; color: #721c24; }}
        
        .stress-test {{
            font-size: 11px;
            color: #666;
            padding-top: 8px;
            border-top: 1px dashed #ddd;
        }}
        
        /* 废弃策略表格 */
        .section-title {{
            font-size: 16px;
            font-weight: 600;
            color: #333;
            margin: 25px 0 15px;
            padding-left: 12px;
            border-left: 4px solid #667eea;
        }}
        .rejected-section {{
            background: #fafbfc;
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 20px;
        }}
        .rejected-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}
        .rejected-table th {{
            background: #34495e;
            color: #fff;
            padding: 10px 6px;
            text-align: left;
            font-weight: 500;
        }}
        .rejected-table td {{
            padding: 8px 6px;
            border-bottom: 1px solid #eee;
            color: #555;
        }}
        .rejected-table tr:nth-child(even) {{ background: #f8f9fa; }}
        .reject-reason {{ color: #e74c3c; font-size: 10px; }}
        
        /* 全部策略表格 */
        .all-strategies-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}
        .all-strategies-table th {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 10px 6px;
            text-align: left;
            font-weight: 500;
            position: sticky;
            top: 0;
        }}
        .all-strategies-table td {{
            padding: 8px 6px;
            border-bottom: 1px solid #eee;
        }}
        .all-strategies-table tr:nth-child(even) {{ background: #f8f9fa; }}
        
        /* 响应式 */
        @media (max-width: 480px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .strategy-title h3 {{ font-size: 13px; }}
            .metric-value {{ font-size: 12px; }}
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            color: #888;
            font-size: 11px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 震荡市策略回测报告</h1>
            <div class="subtitle">Range Market Strategy Arena</div>
            <div class="datetime">扫描时间: {scan_time}</div>
        </div>
        
        <div class="content">
            <!-- 统计网格 -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{total_strategies}</div>
                    <div class="stat-label">扫描策略数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{len(us_strategies)}</div>
                    <div class="stat-label">美股入库</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{len(hk_strategies)}</div>
                    <div class="stat-label">港股入库</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{len(rejected)}</div>
                    <div class="stat-label">废弃策略库</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{len([s for s in strategies if s.get("score", 0) >= 75])}</div>
                    <div class="stat-label">高分策略(≥75)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">2021-2023</div>
                    <div class="stat-label">回测区间</div>
                </div>
            </div>
            
            <h2 class="section-title">🏆 排行榜 TOP5</h2>
            {top5_cards}
            
            <div class="rejected-section">
                <h2 class="section-title">🗑️ 废弃策略库 (共{len(rejected)}个，展示最近10个)</h2>
                <table class="rejected-table">
                    <thead>
                        <tr>
                            <th>策略</th>
                            <th>市场</th>
                            <th>得分</th>
                            <th>年化</th>
                            <th>回撤</th>
                            <th>原因</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rejected_rows}
                    </tbody>
                </table>
            </div>
            
            <h2 class="section-title">📋 全部策略回测数据</h2>
            <div style="overflow-x: auto;">
                <table class="all-strategies-table">
                    <thead>
                        <tr>
                            <th>策略名称</th>
                            <th>市场</th>
                            <th>类型</th>
                            <th>得分</th>
                            <th>年化</th>
                            <th>夏普</th>
                            <th>回撤</th>
                            <th>状态</th>
                        </tr>
                    </thead>
                    <tbody>
                        {all_rows}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="footer">
            <p>震荡市策略回测系统 · strategy_arena_range</p>
            <p>报告生成时间: {scan_time}</p>
        </div>
    </div>
</body>
</html>
'''
    return html

def send_email():
    """发送邮件"""
    try:
        html_content = generate_email_html()
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"【震荡市策略回测报告】{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        msg['From'] = SMTP_USER
        msg['To'] = RECIPIENT
        
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        
        print("✅ 邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

if __name__ == "__main__":
    send_email()
