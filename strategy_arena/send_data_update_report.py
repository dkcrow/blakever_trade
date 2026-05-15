#!/usr/bin/env python3
"""发送A股数据更新报告邮件"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER = "848786642@qq.com"
PASSWORD = "ljbtvacrctjobfed"
RECEIVER = "848786642@qq.com"

def send_data_update_report():
    """发送A股数据更新报告"""
    # 获取当前时间
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 构建邮件内容（基于刚才的执行结果）
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A股数据更新报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; color: #333; border-bottom: 2px solid #3498db; padding-bottom: 15px; margin-bottom: 20px; }}
        .stats {{ margin: 20px 0; }}
        .stat-item {{ display: flex; justify-content: space-between; padding: 10px; margin: 5px 0; border-radius: 5px; }}
        .success {{ background-color: #d4edda; color: #155724; }}
        .skipped {{ background-color: #fff3cd; color: #856404; }}
        .failed {{ background-color: #f8d7da; color: #721c24; }}
        .total {{ background-color: #d1ecf1; color: #0c5460; font-weight: bold; }}
        .timestamp {{ text-align: right; color: #666; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 A股个股数据扩展更新报告</h1>
            <p>数据更新执行完成</p>
        </div>
        
        <div class="stats">
            <div class="stat-item total">
                <span>总共处理:</span>
                <span>512只A股</span>
            </div>
            <div class="stat-item success">
                <span>成功更新:</span>
                <span>146只股票</span>
            </div>
            <div class="stat-item skipped">
                <span>自动跳过:</span>
                <span>366只股票（已满足10年数据）</span>
            </div>
            <div class="stat-item failed">
                <span>更新失败:</span>
                <span>0只股票</span>
            </div>
        </div>
        
        <div>
            <h3>📋 更新详情:</h3>
            <p>所有需要更新的股票都已成功处理，没有遇到限流失败的情况。</p>
        </div>
        
        <div>
            <h3>ℹ️ 更新说明:</h3>
            <p>本次更新仅针对数据起始年份在2017年之后的A股个股（不足10年历史数据），已覆盖10年数据的股票自动跳过。</p>
            <p>失败的股票将在下次更新时自动重试。</p>
        </div>
        
        <div class="timestamp">
            报告生成时间: {current_time}
        </div>
    </div>
</body>
</html>"""

    # 创建邮件
    msg = MIMEMultipart()
    msg['Subject'] = f'【A股数据更新报告】{current_time}' 
    msg['From'] = SENDER
    msg['To'] = RECEIVER
    
    # 添加HTML内容
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    # 发送邮件
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SENDER, PASSWORD)
            server.sendmail(SENDER, RECEIVER, msg.as_string())
        print("📧 A股数据更新报告邮件已成功发送")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False

if __name__ == '__main__':
    send_data_update_report()