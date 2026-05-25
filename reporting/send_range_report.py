#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

def create_html_report():
    """创建HTML格式的震荡市策略回测报告"""
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
    <title>震荡市策略回测报告</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        
        .container {{
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            overflow: hidden;
            margin-bottom: 20px;
        }}
        
        .header {{
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 15px 15px 0 0;
        }}
        
        .header h1 {{
            font-size: 24px;
            margin-bottom: 5px;
            font-weight: bold;
        }}
        
        .header .time {{
            font-size: 14px;
            opacity: 0.9;
        }}
        
        .card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin: 15px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border: 1px solid #e0e0e0;
        }}
        
        .card-header {{
            display: flex;
            align-items: center;
            margin-bottom: 15px;
        }}
        
        .medal {{
            font-size: 24px;
            margin-right: 10px;
        }}
        
        .rank-1 {{ color: #FFD700; }}
        .rank-2 {{ color: #C0C0C0; }}
        .rank-3 {{ color: #CD7F32; }}
        
        .strategy-name {{
            font-size: 18px;
            font-weight: bold;
            color: #2c3e50;
        }}
        
        .market-tag {{
            background: #3498db;
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin-left: 10px;
        }}
        
        .score {{
            font-size: 20px;
            font-weight: bold;
            color: #e74c3c;
            margin-left: auto;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin: 15px 0;
        }}
        
        .metric {{
            text-align: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        
        .metric-label {{
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }}
        
        .metric-value {{
            font-size: 14px;
            font-weight: bold;
        }}
        
        .positive {{ color: #27ae60; }}
        .negative {{ color: #e74c3c; }}
        
        .tags {{
            display: flex;
            gap: 5px;
            margin-top: 10px;
        }}
        
        .tag {{
            background: #ecf0f1;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
        }}
        
        .tag.robust {{ background: #d4edda; color: #155724; }}
        .tag.stop-loss {{ background: #fff3cd; color: #856404; }}
        .tag.warning {{ background: #f8d7da; color: #721c24; }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin: 15px 0;
        }}
        
        .stat {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 18px;
            font-weight: bold;
            color: #2c3e50;
        }}
        
        .stat-label {{
            font-size: 12px;
            color: #666;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 12px;
        }}
        
        th, td {{
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        
        th {{
            background: #f8f9fa;
            font-weight: bold;
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 震荡市策略回测报告</h1>
            <div class="time">{current_time}</div>
        </div>
        
        <!-- 统计信息 -->
        <div class="card">
            <h3>📈 统计概览</h3>
            <div class="stats-grid">
                <div class="stat">
                    <div class="stat-value">6</div>
                    <div class="stat-label">策略总数</div>
                </div>
                <div class="stat">
                    <div class="stat-value">17</div>
                    <div class="stat-label">废弃策略</div>
                </div>
                <div class="stat">
                    <div class="stat-value">5</div>
                    <div class="stat-label">排行榜策略</div>
                </div>
                <div class="stat">
                    <div class="stat-value">2</div>
                    <div class="stat-label">市场覆盖</div>
                </div>
            </div>
        </div>
        
        <!-- 排行榜前五 -->
        <div class="card">
            <h3>🏆 策略排行榜 TOP 5</h3>
            
            <!-- 第1名 -->
            <div class="card">
                <div class="card-header">
                    <span class="medal rank-1">🥇</span>
                    <span class="strategy-name">布林带均值回归策略</span>
                    <span class="market-tag">US</span>
                    <span class="score">47.9</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">年化收益</div>
                        <div class="metric-value positive">1.24%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">夏普比率</div>
                        <div class="metric-value">0.14</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">最大回撤</div>
                        <div class="metric-value negative">11.06%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">盈亏比</div>
                        <div class="metric-value positive">5.33</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">胜率</div>
                        <div class="metric-value positive">54.2%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">年交易次数</div>
                        <div class="metric-value">2</div>
                    </div>
                </div>
                <div class="tags">
                    <span class="tag robust">✅ 跨周期鲁棒</span>
                    <span class="tag warning">⚠️ 幸存者偏差</span>
                    <span class="tag stop-loss">✅ 止损保护</span>
                </div>
            </div>
            
            <!-- 第2名 -->
            <div class="card">
                <div class="card-header">
                    <span class="medal rank-2">🥈</span>
                    <span class="strategy-name">布林带均值回归策略</span>
                    <span class="market-tag">HK</span>
                    <span class="score">40.7</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">年化收益</div>
                        <div class="metric-value positive">1.80%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">夏普比率</div>
                        <div class="metric-value">0.13</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">最大回撤</div>
                        <div class="metric-value negative">14.93%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">盈亏比</div>
                        <div class="metric-value positive">7.68</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">胜率</div>
                        <div class="metric-value positive">55.7%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">年交易次数</div>
                        <div class="metric-value">1</div>
                    </div>
                </div>
                <div class="tags">
                    <span class="tag robust">✅ 跨周期鲁棒</span>
                    <span class="tag warning">⚠️ 幸存者偏差</span>
                    <span class="tag stop-loss">✅ 止损保护</span>
                </div>
            </div>
            
            <!-- 第3名 -->
            <div class="card">
                <div class="card-header">
                    <span class="medal rank-3">🥉</span>
                    <span class="strategy-name">Keltner通道挤压突破策略</span>
                    <span class="market-tag">HK</span>
                    <span class="score">39.6</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">年化收益</div>
                        <div class="metric-value positive">0.45%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">夏普比率</div>
                        <div class="metric-value negative">-0.17</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">最大回撤</div>
                        <div class="metric-value">4.87%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">盈亏比</div>
                        <div class="metric-value positive">40.66</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">胜率</div>
                        <div class="metric-value">13.5%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">年交易次数</div>
                        <div class="metric-value">0</div>
                    </div>
                </div>
                <div class="tags">
                    <span class="tag robust">✅ 跨周期鲁棒</span>
                    <span class="tag warning">⚠️ 幸存者偏差</span>
                    <span class="tag stop-loss">✅ 止损保护</span>
                </div>
            </div>
            
            <!-- 第4名 -->
            <div class="card">
                <div class="card-header">
                    <span class="medal">4</span>
                    <span class="strategy-name">双均线乖离回归策略</span>
                    <span class="market-tag">HK</span>
                    <span class="score">39.0</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">年化收益</div>
                        <div class="metric-value negative">-0.94%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">夏普比率</div>
                        <div class="metric-value negative">-0.13</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">最大回撤</div>
                        <div class="metric-value">5.74%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">盈亏比</div>
                        <div class="metric-value positive">4.66</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">胜率</div>
                        <div class="metric-value">29.4%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">年交易次数</div>
                        <div class="metric-value">1</div>
                    </div>
                </div>
                <div class="tags">
                    <span class="tag warning">❌ 跨周期鲁棒</span>
                    <span class="tag warning">⚠️ 幸存者偏差</span>
                    <span class="tag stop-loss">✅ 止损保护</span>
                </div>
            </div>
            
            <!-- 第5名 -->
            <div class="card">
                <div class="card-header">
                    <span class="medal">5</span>
                    <span class="strategy-name">Keltner通道挤压突破策略</span>
                    <span class="market-tag">US</span>
                    <span class="score">34.3</span>
                </div>
                <div class="metrics-grid">
                    <div class="metric">
                        <div class="metric-label">年化收益</div>
                        <div class="metric-value positive">0.07%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">夏普比率</div>
                        <div class="metric-value negative">-0.08</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">最大回撤</div>
                        <div class="metric-value">2.94%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">盈亏比</div>
                        <div class="metric-value positive">7.76</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">胜率</div>
                        <div class="metric-value">13.8%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">年交易次数</div>
                        <div class="metric-value">0</div>
                    </div>
                </div>
                <div class="tags">
                    <span class="tag warning">❌ 跨周期鲁棒</span>
                    <span class="tag warning">⚠️ 幸存者偏差</span>
                    <span class="tag stop-loss">✅ 止损保护</span>
                </div>
            </div>
        </div>
        
        <!-- 废弃策略库 -->
        <div class="card">
            <h3>🗑️ 废弃策略库 (共17个，展示最近10个)</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>策略名称</th>
                        <th>市场</th>
                        <th>得分</th>
                        <th>年化</th>
                        <th>回撤</th>
                        <th>废弃原因</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>1</td>
                        <td>布林带均值回归策略</td>
                        <td>US</td>
                        <td>51.31</td>
                        <td class="positive">1.7%</td>
                        <td>10.0%</td>
                        <td>年化1.65%<10%; 得分51.31<75</td>
                    </tr>
                    <tr>
                        <td>2</td>
                        <td>RSI区间交易策略</td>
                        <td>US</td>
                        <td>48.65</td>
                        <td class="positive">8.7%</td>
                        <td class="negative">20.3%</td>
                        <td>最大回撤20.3%≥15%</td>
                    </tr>
                    <tr>
                        <td>3</td>
                        <td>Keltner通道挤压突破策略</td>
                        <td>US</td>
                        <td>15.0</td>
                        <td class="negative">-1.5%</td>
                        <td>7.8%</td>
                        <td>年化-1.48%<10%; 得分15.0<75</td>
                    </tr>
                    <tr>
                        <td>4</td>
                        <td>网格交易策略(简化版)</td>
                        <td>US</td>
                        <td>13.88</td>
                        <td class="negative">-5.1%</td>
                        <td class="negative">33.3%</td>
                        <td>最大回撤33.3%≥15%</td>
                    </tr>
                    <tr>
                        <td>5</td>
                        <td>配对交易均值回归策略</td>
                        <td>US</td>
                        <td>28.16</td>
                        <td class="positive">2.1%</td>
                        <td class="negative">25.1%</td>
                        <td>最大回撤25.1%≥15%</td>
                    </tr>
                    <tr>
                        <td>6</td>
                        <td>支撑阻力区间交易策略</td>
                        <td>US</td>
                        <td>20.96</td>
                        <td class="positive">0.3%</td>
                        <td class="negative">20.4%</td>
                        <td>最大回撤20.4%≥15%</td>
                    </tr>
                    <tr>
                        <td>7</td>
                        <td>MACD柱状图反转策略</td>
                        <td>US</td>
                        <td>33.32</td>
                        <td class="positive">7.4%</td>
                        <td class="negative">34.7%</td>
                        <td>最大回撤34.7%≥15%</td>
                    </tr>
                    <tr>
                        <td>8</td>
                        <td>Donchian通道回归策略</td>
                        <td>US</td>
                        <td>35.94</td>
                        <td class="positive">6.7%</td>
                        <td class="negative">20.4%</td>
                        <td>最大回撤20.4%≥15%</td>
                    </tr>
                    <tr>
                        <td>9</td>
                        <td>波动率收缩-扩张轮动策略</td>
                        <td>US</td>
                        <td>30.36</td>
                        <td class="positive">3.7%</td>
                        <td class="negative">26.9%</td>
                        <td>最大回撤26.9%≥15%</td>
                    </tr>
                    <tr>
                        <td>10</td>
                        <td>双均线乖离回归策略</td>
                        <td>US</td>
                        <td>18.64</td>
                        <td class="negative">-1.2%</td>
                        <td>3.5%</td>
                        <td>年化-1.22%<10%; 得分18.64<75</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <!-- 全部策略数据 -->
        <div class="card">
            <h3>📊 全部策略数据</h3>
            <table>
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>策略名称</th>
                        <th>类型</th>
                        <th>市场</th>
                        <th>得分</th>
                        <th>年化</th>
                        <th>夏普</th>
                        <th>回撤</th>
                        <th>盈亏比</th>
                        <th>胜率</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>1</td>
                        <td>布林带均值回归策略</td>
                        <td>均值回归</td>
                        <td>US</td>
                        <td>47.9</td>
                        <td class="positive">1.24%</td>
                        <td>0.14</td>
                        <td class="negative">11.06%</td>
                        <td class="positive">5.33</td>
                        <td class="positive">54.2%</td>
                    </tr>
                    <tr>
                        <td>2</td>
                        <td>布林带均值回归策略</td>
                        <td>均值回归</td>
                        <td>HK</td>
                        <td>40.7</td>
                        <td class="positive">1.80%</td>
                        <td>0.13</td>
                        <td class="negative">14.93%</td>
                        <td class="positive">7.68</td>
                        <td class="positive">55.7%</td>
                    </tr>
                    <tr>
                        <td>3</td>
                        <td>Keltner通道挤压突破策略</td>
                        <td>趋势跟踪</td>
                        <td>HK</td>
                        <td>39.6</td>
                        <td class="positive">0.45%</td>
                        <td class="negative">-0.17</td>
                        <td>4.87%</td>
                        <td class="positive">40.66</td>
                        <td>13.5%</td>
                    </tr>
                    <tr>
                        <td>4</td>
                        <td>双均线乖离回归策略</td>
                        <td>趋势跟踪</td>
                        <td>HK</td>
                        <td>39.0</td>
                        <td class="negative">-0.94%</td>
                        <td class="negative">-0.13</td>
                        <td>5.74%</td>
                        <td class="positive">4.66</td>
                        <td>29.4%</td>
                    </tr>
                    <tr>
                        <td>5</td>
                        <td>Keltner通道挤压突破策略</td>
                        <td>趋势跟踪</td>
                        <td>US</td>
                        <td>34.3</td>
                        <td class="positive">0.07%</td>
                        <td class="negative">-0.08</td>
                        <td>2.94%</td>
                        <td class="positive">7.76</td>
                        <td>13.8%</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>📧 本报告由震荡市策略回测系统自动生成 | {current_time}</p>
        </div>
    </div>
</body>
</html>
"""
    return html_content

def send_email():
    """发送邮件"""
    # 邮件配置
    smtp_server = "smtp.qq.com"
    smtp_port = 465
    sender_email = "848786642@qq.com"
    receiver_email = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    # 创建邮件
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = f"【震荡市策略回测报告】{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    # HTML内容
    html_content = create_html_report()
    msg.attach(MIMEText(html_content, 'html'))
    
    try:
        # 连接SMTP服务器并发送
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("✅ 邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

if __name__ == "__main__":
    send_email()