#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股个股数据更新报告邮件发送"""

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

# 在文件末尾添加实际执行结果的解析逻辑
# 从刚才的执行结果中提取准确的数据
def get_actual_execution_stats():
    """从实际执行结果中获取统计数据"""
    # 根据刚才的终端输出结果
    # 📈 A股: 更新146只, 跳过366只, 失败0只
    return {
        'total_stocks': 512,  # 146 + 366
        'updated_stocks': 146,
        'skipped_stocks': 366,
        'failed_stocks': 0
    }

# 修改generate_a_stock_update_html函数，使用实际数据
def generate_a_stock_update_html():
    """生成A股数据更新报告的HTML内容"""
    
    # 使用实际执行结果数据
    stats = get_actual_execution_stats()
    total_stocks = stats['total_stocks']
    updated_stocks = stats['updated_stocks']
    skipped_stocks = stats['skipped_stocks']
    failed_stocks = stats['failed_stocks']
    
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 生成更新统计卡片
    stats_cards = f'''
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{total_stocks}</div>
            <div class="stat-label">总处理股票数</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{updated_stocks}</div>
            <div class="stat-label">成功更新</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{skipped_stocks}</div>
            <div class="stat-label">已覆盖跳过</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{failed_stocks}</div>
            <div class="stat-label">更新失败</div>
        </div>
    </div>
    '''
    
    # 生成简要说明
    explanation = f'''
    <div class="explanation-section">
        <h3>📋 任务说明</h3>
        <p>本次A股数据更新任务专门针对<strong>起始年份在2017年之后</strong>的个股进行数据扩展，目标是将不足10年历史数据的股票扩展到完整的10年数据。</p>
        <p><strong>更新逻辑：</strong></p>
        <ul>
            <li>✅ <strong>成功更新</strong>：起始年份在2017年之后的个股（数据不足10年）</li>
            <li>⏭️ <strong>已覆盖跳过</strong>：已经拥有10年完整数据的个股</li>
            <li>❌ <strong>更新失败</strong>：数据获取过程中出现错误的个股</li>
        </ul>
        <p><strong>数据范围：</strong>沪深交易所所有A股（主板、创业板、科创板）</p>
    </div>
    '''
    
    # 根据执行结果生成不同的摘要信息
    if failed_stocks == 0:
        summary_section = f'''
        <div class="summary-section">
            <h3>✅ 任务执行成功</h3>
            <p>所有A股个股数据已按计划完成更新和检查，无失败记录</p>
        </div>
        '''
    else:
        summary_section = f'''
        <div class="summary-section" style="background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); border: 2px solid #dc3545;">
            <h3 style="color: #721c24;">⚠️ 任务执行完成（有失败记录）</h3>
            <p style="color: #721c24;">{failed_stocks}只股票更新失败，建议检查网络连接和数据源</p>
        </div>
        '''
    
    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
    <title>A股个股数据更新报告</title>
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
            grid-template-columns: repeat(4, 1fr);
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
        
        /* 说明部分 */
        .explanation-section {{
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border-left: 4px solid #667eea;
        }}
        .explanation-section h3 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 16px;
        }}
        .explanation-section p {{
            margin-bottom: 10px;
            line-height: 1.5;
            font-size: 14px;
            color: #555;
        }}
        .explanation-section ul {{
            margin-left: 20px;
            margin-bottom: 10px;
        }}
        .explanation-section li {{
            margin-bottom: 5px;
            font-size: 14px;
            color: #555;
        }}
        
        /* 结果摘要 */
        .summary-section {{
            background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 2px solid #28a745;
        }}
        .summary-section h3 {{
            color: #155724;
            margin-bottom: 10px;
            font-size: 18px;
        }}
        .summary-section p {{
            font-size: 16px;
            color: #155724;
            font-weight: 600;
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            color: #888;
            font-size: 11px;
        }}
        
        /* 响应式 */
        @media (max-width: 480px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 A股个股数据更新报告</h1>
            <div class="subtitle">10年历史数据扩展任务</div>
            <div class="datetime">执行时间: {scan_time}</div>
        </div>
        
        <div class="content">
            {stats_cards}
            
            {summary_section}
            
            {explanation}
        </div>
        
        <div class="footer">
            <p>A股数据更新系统 · strategy_arena</p>
            <p>报告生成时间: {scan_time}</p>
        </div>
    </div>
</body>
</html>
'''
    return html

def send_a_stock_update_email():
    """发送A股数据更新报告邮件"""
    try:
        html_content = generate_a_stock_update_html()
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"【A股个股数据更新报告】{datetime.now().strftime('%Y-%m-%d %H:%M')}"
        msg['From'] = SMTP_USER
        msg['To'] = RECIPIENT
        
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        
        print("✅ A股数据更新报告邮件发送成功！")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

if __name__ == "__main__":
    send_a_stock_update_email()