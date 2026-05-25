#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股数据更新报告邮件发送"""

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

def read_status_file():
    """读取数据更新状态文件"""
    status_file = Path("/data/workspace/back_trader_stocks/.data_update_status.json")
    if status_file.exists():
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def get_update_summary():
    """获取更新统计信息"""
    status = read_status_file()
    
    # 统计各类更新数量
    cn_updates = len([k for k in status.keys() if k.startswith('cn_')])
    us_updates = len([k for k in status.keys() if k.startswith('us_')])
    hk_updates = len([k for k in status.keys() if k.startswith('hk_')])
    
    total_updates = cn_updates + us_updates + hk_updates
    
    # 获取最近更新时间
    latest_update = ""
    if status:
        latest_timestamp = max([v.get('updated', '') for v in status.values() if 'updated' in v])
        if latest_timestamp:
            try:
                dt = datetime.fromisoformat(latest_timestamp)
                latest_update = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                latest_update = latest_timestamp
    
    return {
        'total_updates': total_updates,
        'cn_updates': cn_updates,
        'us_updates': us_updates,
        'hk_updates': hk_updates,
        'latest_update': latest_update,
        'status_count': len(status)
    }

def generate_update_email_html():
    """生成数据更新邮件HTML内容"""
    
    summary = get_update_summary()
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 从终端输出中提取A股更新结果
    # 根据之前的执行结果：A股: 更新146只, 跳过366只, 失败0只
    a_stock_updated = 146
    a_stock_skipped = 366
    a_stock_failed = 0
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
    <title>A股数据更新报告</title>
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
        
        /* 结果卡片 */
        .result-card {{
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 3px 12px rgba(0,0,0,0.08);
            margin-bottom: 16px;
            padding: 20px;
            border-left: 4px solid #27ae60;
        }}
        .result-card.failed {{
            border-left-color: #e74c3c;
        }}
        .result-card.skipped {{
            border-left-color: #f39c12;
        }}
        
        .result-title {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .result-metrics {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 15px;
        }}
        .metric {{
            text-align: center;
            padding: 10px;
            border-radius: 8px;
            background: #f8f9fa;
        }}
        .metric.success {{ background: #d4edda; color: #155724; }}
        .metric.warning {{ background: #fff3cd; color: #856404; }}
        .metric.danger {{ background: #f8d7da; color: #721c24; }}
        .metric-value {{ font-size: 18px; font-weight: 700; }}
        .metric-label {{ font-size: 12px; margin-top: 4px; }}
        
        /* 详情表格 */
        .details-section {{
            background: #fafbfc;
            border-radius: 12px;
            padding: 15px;
            margin-top: 20px;
        }}
        .details-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        .details-table th {{
            background: #34495e;
            color: #fff;
            padding: 10px 8px;
            text-align: left;
            font-weight: 500;
        }}
        .details-table td {{
            padding: 8px 8px;
            border-bottom: 1px solid #eee;
            color: #555;
        }}
        .details-table tr:nth-child(even) {{ background: #f8f9fa; }}
        
        .section-title {{
            font-size: 16px;
            font-weight: 600;
            color: #333;
            margin: 25px 0 15px;
            padding-left: 12px;
            border-left: 4px solid #667eea;
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            color: #888;
            font-size: 11px;
        }}
        
        @media (max-width: 480px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .result-metrics {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 A股数据更新报告</h1>
            <div class="subtitle">10年数据扩展更新任务</div>
            <div class="datetime">报告时间: {update_time}</div>
        </div>
        
        <div class="content">
            <!-- 总体统计 -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{a_stock_updated}</div>
                    <div class="stat-label">更新股票数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{a_stock_skipped}</div>
                    <div class="stat-label">跳过股票数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{a_stock_failed}</div>
                    <div class="stat-label">失败股票数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{a_stock_updated + a_stock_skipped}</div>
                    <div class="stat-label">总处理股票</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{summary['status_count']}</div>
                    <div class="stat-label">状态记录数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">2017年后</div>
                    <div class="stat-label">更新范围</div>
                </div>
            </div>
            
            <!-- A股更新结果 -->
            <h2 class="section-title">📊 A股个股数据更新结果</h2>
            <div class="result-card">
                <div class="result-title">
                    <span>🎯 数据扩展更新</span>
                </div>
                <p>成功将数据起始年份在2017年之后的A股个股数据扩展到10年完整数据。</p>
                
                <div class="result-metrics">
                    <div class="metric success">
                        <div class="metric-value">{a_stock_updated}</div>
                        <div class="metric-label">成功更新</div>
                    </div>
                    <div class="metric warning">
                        <div class="metric-value">{a_stock_skipped}</div>
                        <div class="metric-label">已覆盖跳过</div>
                    </div>
                    <div class="metric danger">
                        <div class="metric-value">{a_stock_failed}</div>
                        <div class="metric-label">更新失败</div>
                    </div>
                </div>
            </div>
            
            <!-- 更新详情 -->
            <div class="details-section">
                <h3 class="section-title">📋 更新详情</h3>
                <table class="details-table">
                    <thead>
                        <tr>
                            <th>市场</th>
                            <th>更新数量</th>
                            <th>跳过数量</th>
                            <th>失败数量</th>
                            <th>成功率</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><strong>A股个股</strong></td>
                            <td>{a_stock_updated}</td>
                            <td>{a_stock_skipped}</td>
                            <td>{a_stock_failed}</td>
                            <td style="color: #27ae60;">100.0%</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <!-- 技术说明 -->
            <div class="details-section">
                <h3 class="section-title">⚙️ 技术说明</h3>
                <ul style="font-size: 12px; line-height: 1.6; color: #555;">
                    <li><strong>更新策略</strong>: 只更新数据起始年份在2017年之后的A股个股（不足10年）</li>
                    <li><strong>跳过逻辑</strong>: 已覆盖10年完整数据的股票自动跳过</li>
                    <li><strong>限流处理</strong>: 遇到限流自动等待重试，最大重试次数3次</li>
                    <li><strong>数据源</strong>: 通过westock-data拉取日线数据</li>
                    <li><strong>数据格式</strong>: CSV格式，包含OHLCV完整数据</li>
                    <li><strong>数据范围</strong>: 约10年日线数据（2600个交易日）</li>
                </ul>
            </div>
        </div>
        
        <div class="footer">
            <p>A股数据更新系统 · strategy_arena/update_market_data.py</p>
            <p>报告生成时间: {update_time}</p>
            <p>💡 提示: 此报告仅包含A股个股数据更新情况，其他市场数据更新请查看完整报告</p>
        </div>
    </div>
</body>
</html>
'''
    
    return html

def send_email():
    """发送邮件"""
    try:
        html_content = generate_update_email_html()
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"【A股数据更新报告】{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        msg['From'] = SMTP_USER
        msg['To'] = RECIPIENT
        
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        
        print("✅ A股数据更新邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ A股数据更新邮件发送失败: {e}")
        return False

if __name__ == "__main__":
    success = send_email()
    exit(0 if success else 1)