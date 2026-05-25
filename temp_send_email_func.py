def send_email(rankings, alerts, highlight_ids):
    """发送精美HTML邮件（含交易记录）"""
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # HTML模板 - 手机端优化版(大字体+高对比度)
    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ 
                font-family: 'Microsoft YaHei', Arial, sans-serif; 
                margin: 0; 
                padding: 10px;
                background: #f0f2f5;
                font-size: 18px;
                line-height: 1.6;
            }
            .header {{ 
                background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%); 
                color: white; 
                padding: 25px 20px; 
                border-radius: 12px; 
                margin-bottom: 20px;
                text-align: center;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            .header h2 {{ 
                margin: 0 0 10px 0; 
                font-size: 28px;
                font-weight: bold;
            }}
            .header p {{ 
                margin: 0; 
                font-size: 16px;
                opacity: 0.9;
            }}
            .section {{ 
                background: white; 
                padding: 20px; 
                margin-bottom: 20px; 
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            .section h3 {{ 
                margin: 0 0 15px 0;
                font-size: 22px;
                color: #1a73e8;
                border-bottom: 3px solid #1a73e8;
                padding-bottom: 10px;
            }}
            .ranking {{ 
                margin: 12px 0; 
                padding: 15px;
                background: #f8f9fa;
                border-left: 6px solid #1a73e8;
                border-radius: 8px;
                font-size: 17px;
            }}
            .ranking strong {{ 
                font-size: 19px;
                color: #202124;
                display: block;
                margin-bottom: 8px;
            }}
            .ranking .score {{ 
                color: #5f6368;
                font-size: 16px;
            }}
            .alert {{ 
                background: #fee;
                border-left: 6px solid #d93025;
                padding: 18px;
                margin: 12px 0;
                border-radius: 8px;
                font-size: 18px;
            }}
            .alert strong {{ 
                color: #d93025;
                font-size: 20px;
                display: block;
                margin-bottom: 10px;
            }}
            .trades-table {{ 
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
                font-size: 16px;
            }}
            .trades-table th {{ 
                background: #1a73e8;
                color: white;
                padding: 14px 10px;
                text-align: left;
                font-size: 17px;
                font-weight: bold;
            }}
            .trades-table td {{ 
                padding: 14px 10px;
                border-bottom: 2px solid #e8eaed;
                font-size: 16px;
            }}
            .highlight {{ 
                background: #fff3e0 !important;
                font-weight: bold;
                color: #e65100;
            }}
            .positive {{ 
                color: #1e8e3e;
                font-weight: bold;
                font-size: 17px;
            }}
            .negative {{ 
                color: #d93025;
                font-weight: bold;
                font-size: 17px;
            }}
            .badge {{ 
                display: inline-block;
                padding: 6px 12px;
                border-radius: 20px;
                font-size: 14px;
                font-weight: bold;
                margin-left: 8px;
            }}
            .badge-realtime {{ 
                background: #e6f4ea;
                color: #1e8e3e;
            }}
            .badge-csv {{ 
                background: #f1f3f4;
                color: #5f6368;
            }}
            .footer {{ 
                text-align: center;
                color: #5f6368;
                font-size: 14px;
                margin-top: 20px;
                padding: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>拉普拉斯策略盘中监控</h2>
            <p>{now_str}</p>
        </div>
        
        <div class="section">
            <h3>ETF排名 Top 10</h3>
    """
    
    # 排名 - 手机优化版
    for i, r in enumerate(rankings[:10]):
        realtime_badge = '<span class="badge badge-realtime">实时</span>' if r['is_realtime'] else '<span class="badge badge-csv">CSV</span>'
        html += f"""
            <div class="ranking">
                <strong>#{i+1} {r['name']} ({r['etf']}) {realtime_badge}</strong>
                <div class="score">
                    综合: {r['combined']:.4f} | 短期: {r['short']:.4f} | 长期: {r['long']:.4f}<br>
                    价格: {r['price']:.3f} ({r['date']})
                </div>
            </div>
        """
    
    # 止损警示 - 手机优化版
    if alerts:
        html += f"""
        <div class="section">
            <h3>止损警示（{len(alerts)}只）</h3>
        """
        for alert in alerts:
            html += f"""
            <div class="alert">
                <strong>{alert['name']} ({alert['etf']}) - {alert['type']}</strong><br><br>
                入场: {alert['entry']:.3f} → 当前: {alert['current']:.3f}<br>
                盈亏: <span class="{'positive' if alert.get('pnl', 0) >= 0 else 'negative'}">{alert.get('pnl', 0):.1f}%</span><br>
            """
            if 'high' in alert:
                html += f"最高: {alert['high']:.3f}<br>"
            html += "</div>"
        html += "</div>"
    
    # 最近交易 - 手机优化版
    recent_trades = get_recent_trades(20)
    if recent_trades:
        html += f"""
        <div class="section">
            <h3>近20次交易记录</h3>
            <table class="trades-table">
                <tr>
                    <th>日期</th><th>ETF</th><th>操作</th><th>价格</th><th>盈亏%</th>
                </tr>
        """
        for trade in recent_trades:
            highlight = 'class="highlight"' if trade['id'] in highlight_ids else ''
            pnl_class = 'positive' if (trade.get('pnl_pct') or 0) >= 0 else 'negative'
            pnl_display = f"{trade['pnl_pct']:.1f}%" if trade.get('pnl_pct') is not None else '-'
            html += f"""
                <tr {highlight}>
                    <td>{trade['date']}</td>
                    <td>{trade['name']}</td>
                    <td>{trade['action']}</td>
                    <td>{trade['price']:.3f}</td>
                    <td class="{pnl_class}">{pnl_display}</td>
                </tr>
            """
        html += """
            </table>
        </div>
        """
    
    html += """
        <div class="footer">
            拉普拉斯策略自动监控 | 数据来源: westock-data / 腾讯接口
        </div>
    </body>
    </html>
    """
    
    # 发送
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = f"拉普拉斯盘中监控 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    try:
        with smtplib.SMTP('smtp.qq.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        print('[OK] 邮件已发送')
        return True
    except Exception as e:
        print(f'[ERROR] 邮件发送失败: {e}')
        return False

# ==================== 主程序 ====================

if __name__ == '__main__':
    print('='*60)
    print('拉普拉斯盘中监控 v5 开始...')
    print('='*60)
    
    # 1. 获取ETF排名
    print('\n[1/3] 获取ETF排名...')
    rankings = get_rankings()
    print(f'  [OK] 成功获取 {len(rankings)} 只ETF排名')
    
    # 2. 检查止损
    print('\n[2/3] 检查止损...')
    alerts, highlight_ids = check_stop_loss()
    print(f'  [OK] 检测到 {len(alerts)} 只止损警示')
    for alert in alerts:
        print(f'    {alert["etf"]} {alert["name"]}: {alert["type"]}')
    
    # 3. 发送邮件
    print('\n[3/3] 发送HTML邮件...')
    send_email(rankings, alerts, highlight_ids)
    
    print('\n' + '='*60)
    print('拉普拉斯盘中监控完成')
    print(f'  总ETF: {len(rankings)}只')
    print(f'  止损警示: {len(alerts)}只')
    print(f'  近20次交易记录已附上')
    print('='*60)