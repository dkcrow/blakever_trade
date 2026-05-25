"""
拉普拉斯盘中监控 v7 - 手机端优化版
大字体、高对比度、清晰分区
"""
import pandas as pd
import numpy as np
from datetime import datetime
import json
import smtplib
from email.mime.text import MIMEText
import warnings
warnings.filterwarnings('ignore')

# =============================================================
# 配置
# =============================================================
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'
ETF_POOL = [
    '518880', '159980', '159985', '501018', '161226',
    '159981', '513100', '159509', '513290', '513500',
    '159529', '513400', '513520', '513030', '513080',
    '513310', '513730', '159792', '513130', '513050',
    '159920', '513690', '510300', '510500', '510050',
    '510210', '159915', '588080', '512100', '563360',
    '563300', '512890', '159967', '512040', '159201',
    '511380', '511010', '511220'
]

ETF_NAMES = {
    '518880': '黄金ETF华安', '159980': '有色ETF大成', '159985': '豆粕ETF华夏',
    '501018': '南方原油LOF', '161226': '白银LOF国投瑞银', '159981': '能源化工ETF建信',
    '513100': '纳指ETF国泰', '159509': '纳指科技ETF景顺', '513290': '纳指生物科技ETF汇添富',
    '513500': '标普500ETF博时', '159529': '标普消费ETF景顺', '513400': '道琼斯ETF鹏华',
    '513520': '日经ETF华夏', '513030': '德国ETF华安', '513080': '法国ETF华安',
    '513310': '中韩半导体ETF华泰柏瑞', '513730': '东南亚科技ETF华泰柏瑞',
    '159792': '港股通互联网ETF富国', '513130': '恒生科技ETF华泰柏瑞', '513050': '中概互联网ETF易方达',
    '159920': '恒生ETF华夏', '513690': '港股红利ETF博时', '510300': '沪深300ETF华泰柏瑞',
    '510500': '中证500ETF南方', '510050': '上证50ETF华夏', '510210': '上证指数ETF富国',
    '159915': '创业板ETF易方达', '588080': '科创50ETF易方达', '512100': '中证1000ETF南方',
    '563360': 'A500ETF华泰柏瑞', '563300': '中证2000ETF华泰柏瑞', '512890': '红利低波ETF华泰柏瑞',
    '159967': '创业板成长ETF华夏', '512040': '价值100ETF富国', '159201': '自由现金流ETF华夏',
    '511380': '可转债ETF博时', '511010': '国债ETF国泰', '511220': '城投债ETF海富通'
}

# =============================================================
# 获取排名
# =============================================================
def get_rankings():
    rankings = []
    for etf in ETF_POOL:
        for subdir in ['etf', 'etf_qixing']:
            csv_path = f"{BASE_DIR}\\{subdir}\\{etf}.csv"
            try:
                df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
                df = df.sort_index()
                if len(df) > 50:
                    prices = df['close'].values.astype(float)
                    
                    # 短期动量 (25日)
                    if len(prices) >= 26:
                        recent = prices[-26:]
                        y = np.log(recent)
                        x = np.arange(len(y))
                        weights = np.linspace(1, 2, len(y))
                        try:
                            slope, _ = np.polyfit(x, y, 1, w=weights)
                            short = (np.exp(slope * 250) - 1)
                        except:
                            short = 0
                    else:
                        short = 0
                    
                    # 长期动量 (250日)
                    if len(prices) >= 251:
                        long_prices = prices[-251:]
                        y = np.log(long_prices)
                        x = np.arange(len(y))
                        weights = np.linspace(1, 2, len(y))
                        try:
                            slope, _ = np.polyfit(x, y, 1, w=weights)
                            long = (np.exp(slope * 250) - 1)
                        except:
                            long = 0
                    else:
                        long = short
                    
                    combined = short * 1.0 + long * 0.5
                    combined = max(-2, min(2, combined))
                    
                    rankings.append({
                        'etf': etf,
                        'name': ETF_NAMES.get(etf, etf),
                        'combined': combined,
                        'short': short,
                        'long': long,
                        'price': df['close'].iloc[-1],
                        'date': df.index[-1].strftime('%Y-%m-%d')
                    })
                    break
            except:
                continue
    
    rankings.sort(key=lambda x: x['combined'], reverse=True)
    return rankings

# =============================================================
# 获取持仓
# =============================================================
def get_positions():
    try:
        with open('laplace_trades.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('positions', {})
    except:
        return {}

# =============================================================
# 获取实时价
# =============================================================
def get_realtime_price(etf):
    try:
        import urllib.request
        url = f"http://qt.gtimg.cn/q=s_{etf}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = response.read().decode('gbk')
            parts = data.split('~')
            if len(parts) > 5:
                return float(parts[3])
    except:
        pass
    return None

# =============================================================
# 发送邮件 - 手机优化版
# =============================================================
def send_email(rankings, positions):
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # HTML模板 - 手机端优化
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
            }}
            .header {{
                background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
                color: white;
                padding: 25px 20px;
                border-radius: 12px;
                margin-bottom: 20px;
                text-align: center;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }}
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
            .position {{
                margin: 12px 0;
                padding: 15px;
                background: #e8f0fe;
                border-left: 6px solid #1a73e8;
                border-radius: 8px;
                font-size: 17px;
            }}
            .position strong {{
                font-size: 19px;
                color: #1a73e8;
                display: block;
                margin-bottom: 8px;
            }}
            .positive {{
                color: #1e8e3e;
                font-weight: bold;
                font-size: 18px;
            }}
            .negative {{
                color: #d93025;
                font-weight: bold;
                font-size: 18px;
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
            <table style="width:100%; border-collapse: collapse; font-size: 17px;">
                <tr style="background: #1a73e8; color: white;">
                    <th style="padding: 12px 8px; text-align: left;">排名</th>
                    <th style="padding: 12px 8px; text-align: left;">ETF</th>
                    <th style="padding: 12px 8px; text-align: right;">综合分</th>
                    <th style="padding: 12px 8px; text-align: right;">价格</th>
                </tr>
        """
    
    for i, r in enumerate(rankings[:10]):
        bg = '#f8f9fa' if i % 2 == 0 else 'white'
        html += f"""
                <tr style="background: {bg};">
                    <td style="padding: 12px 8px; border-bottom: 2px solid #e8eaed;">#{i+1} {r['name']}</td>
                    <td style="padding: 12px 8px; border-bottom: 2px solid #e8eaed;">{r['etf']}</td>
                    <td style="padding: 12px 8px; border-bottom: 2px solid #e8eaed; text-align: right; font-weight: bold; color: #1a73e8;">{r['combined']:.4f}</td>
                    <td style="padding: 12px 8px; border-bottom: 2px solid #e8eaed; text-align: right; font-weight: bold;">{r['price']:.3f}</td>
                </tr>
        """
    
    html += """
            </table>
        </div>
    """
    
    # 当前持仓
    if positions:
        html += """
        <div class="section">
            <h3>当前持仓</h3>
        """
        for etf, info in positions.items():
            current_price = get_realtime_price(etf)
            if current_price:
                pnl_pct = (current_price - info['entry_price']) / info['entry_price'] * 100
                pnl_class = 'positive' if pnl_pct >= 0 else 'negative'
                html += f"""
                <div class="position">
                    <strong>{ETF_NAMES.get(etf, etf)} ({etf})</strong>
                    入场: {info['entry_price']:.3f} | 当前: {current_price:.3f}<br>
                    盈亏: <span class="{pnl_class}">{pnl_pct:.1f}%</span>
                </div>
                """
            else:
                html += f"""
                <div class="position">
                    <strong>{ETF_NAMES.get(etf, etf)} ({etf})</strong>
                    入场: {info['entry_price']:.3f} (无法获取实时价)
                </div>
                """
        html += """
        </div>
        """
    
    html += """
        <div class="footer">
            拉普拉斯策略自动监控 | 数据来源: 腾讯接口
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
        print('[OK] 邮件已发送（手机优化版）')
        return True
    except Exception as e:
        print(f'[ERROR] 邮件发送失败: {e}')
        return False

# =============================================================
# 主程序
# =============================================================
if __name__ == '__main__':
    print("="*60)
    print("拉普拉斯盘中监控 v7 (手机优化版)")
    print("="*60)
    
    # 获取排名
    print("\n[1/2] 获取ETF排名...")
    rankings = get_rankings()
    print(f"  [OK] 成功获取 {len(rankings)} 只ETF排名")
    
    # 获取持仓
    print("\n[2/2] 检查持仓...")
    positions = get_positions()
    print(f"  [OK] 当前持仓 {len(positions)} 只ETF")
    
    # 发送邮件
    print("\n[3/3] 发送HTML邮件（手机优化版）...")
    send_email(rankings, positions)
    
    print("\n" + "="*60)
    print("拉普拉斯盘中监控完成（手机优化版）")
    print("="*60)
