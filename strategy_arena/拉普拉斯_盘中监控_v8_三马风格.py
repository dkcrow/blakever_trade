"""
拉普拉斯盘中监控 v8 - 三马七星风格
前三名高亮 + 排名变化标注
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
                    short = 0
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
                    
                    # 长期动量 (250日)
                    long = short
                    if len(prices) >= 251:
                        long_prices = prices[-251:]
                        y = np.log(long_prices)
                        x = np.arange(len(y))
                        weights = np.linspace(1, 2, len(y))
                        try:
                            slope, _ = np.polyfit(x, y, 1, w=weights)
                            long = (np.exp(slope * 250) - 1)
                        except:
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
# 排名变化
# =============================================================
def get_rank_changes(current_rankings):
    try:
        with open('laplace_rank_history.json', 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
            prev_ranks = prev_data.get('ranks', {})
    except:
        prev_ranks = {}
    
    changes = {}
    for i, r in enumerate(current_rankings):
        current_rank = i + 1
        prev_rank = prev_ranks.get(r['etf'])
        if prev_rank is None:
            changes[r['etf']] = 'new'
        else:
            diff = prev_rank - current_rank
            if diff > 0:
                changes[r['etf']] = f'up'  # ↑
            elif diff < 0:
                changes[r['etf']] = f'down'  # ↓
            else:
                changes[r['etf']] = 'same'  # →
    
    # 保存当前排名
    new_ranks = {r['etf']: i+1 for i, r in enumerate(current_rankings)}
    with open('laplace_rank_history.json', 'w', encoding='utf-8') as f:
        json.dump({'ranks': new_ranks, 'time': datetime.now().strftime('%Y-%m-%d %H:%M')}, f)
    
    return changes

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
# 发送邮件 - 三马七星风格
# =============================================================
def send_email(rankings, rank_changes, positions):
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # HTML模板 - 三马七星风格
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
                background: #0f172a;
                font-size: 18px;
                line-height: 1.6;
            }}
            .header {{
                background: linear-gradient(135deg, #1e3a8a 0%, #3730a3 100%);
                color: white;
                padding: 25px 20px;
                border-radius: 12px;
                margin-bottom: 20px;
                text-align: center;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
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
                background: #1e293b;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            }}
            .section h3 {{
                margin: 0 0 15px 0;
                font-size: 22px;
                color: #60a5fa;
                border-bottom: 3px solid #3b82f6;
                padding-bottom: 10px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 17px;
            }}
            th {{
                background: #1e3a8a;
                color: white;
                padding: 14px 10px;
                text-align: left;
                font-size: 17px;
                font-weight: bold;
            }}
            /* 前三名高亮 */
            .rank1 {{
                background: linear-gradient(90deg, #fbbf24 0%, #f59e0b 100%) !important;
                color: #000;
                font-weight: bold;
                border-bottom: 3px solid #d97706;
            }}
            .rank2 {{
                background: linear-gradient(90deg, #e5e7eb 0%, #d1d5db 100%) !important;
                color: #000;
                font-weight: bold;
                border-bottom: 3px solid #9ca3af;
            }}
            .rank3 {{
                background: linear-gradient(90deg, #fcd34d 0%, #f59e0b 100%) !important;
                color: #000;
                font-weight: bold;
                border-bottom: 3px solid #d97706;
            }}
            .rank-other {{
                background: #1e293b;
                border-bottom: 2px solid #334155;
            }}
            td {{
                padding: 14px 10px;
                border-bottom: 2px solid #334155;
                font-size: 17px;
            }}
            .rank-num {{
                font-weight: bold;
                font-size: 18px;
                color: #f1f5f9;
            }}
            .etf-name {{
                color: #f1f5f9;
                font-weight: 600;
            }}
            .etf-code {{
                color: #94a3b8;
                font-size: 15px;
            }}
            .score {{
                color: #60a5fa;
                font-weight: bold;
                font-size: 17px;
            }}
            .price {{
                color: #34d399;
                font-weight: bold;
                font-size: 17px;
                text-align: right;
            }}
            .change-up {{
                color: #10b981;
                text-align: right;
                font-size: 16px;
            }}
            .change-down {{
                color: #ef4444;
                text-align: right;
                font-size: 16px;
            }}
            .change-same {{
                color: #6b7280;
                text-align: right;
                font-size: 16px;
            }}
            .change-new {{
                color: #f59e0b;
                text-align: right;
                font-size: 16px;
            }}
            .position {{
                margin: 12px 0;
                padding: 15px;
                background: #1e293b;
                border-left: 6px solid #3b82f6;
                border-radius: 8px;
                font-size: 17px;
            }}
            .position strong {{
                font-size: 19px;
                color: #60a5fa;
                display: block;
                margin-bottom: 8px;
            }}
            .positive {{
                color: #10b981;
                font-weight: bold;
                font-size: 18px;
            }}
            .negative {{
                color: #ef4444;
                font-weight: bold;
                font-size: 18px;
            }}
            .footer {{
                text-align: center;
                color: #64748b;
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
            <table>
                <tr>
                    <th>排名</th>
                    <th>ETF</th>
                    <th style="text-align: right;">综合分</th>
                    <th style="text-align: right;">变化</th>
                </tr>
    """
    
    # 排名表格
    for i, r in enumerate(rankings[:10]):
        rank = i + 1
        if rank == 1:
            row_class = 'rank1'
        elif rank == 2:
            row_class = 'rank2'
        elif rank == 3:
            row_class = 'rank3'
        else:
            row_class = 'rank-other'
        
        change = rank_changes.get(r['etf'], 'new')
        if change == 'up':
            change_html = '<span class="change-up">↑ 上升</span>'
        elif change == 'down':
            change_html = '<span class="change-down">↓ 下降</span>'
        elif change == 'same':
            change_html = '<span class="change-same">→ 不变</span>'
        else:
            change_html = '<span class="change-new">NEW 新进</span>'
        
        html += f"""
                <tr class="{row_class}">
                    <td class="rank-num">#{rank}</td>
                    <td>
                        <span class="etf-name">{r['name']}</span><br>
                        <span class="etf-code">{r['etf']}</span>
                    </td>
                    <td class="score">{r['combined']:.4f}</td>
                    <td>{change_html}</td>
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
        print('[OK] 邮件已发送（三马七星风格）')
        return True
    except Exception as e:
        print(f'[ERROR] 邮件发送失败: {e}')
        return False

# =============================================================
# 主程序
# =============================================================
if __name__ == '__main__':
    print("="*60)
    print("拉普拉斯盘中监控 v8 (三马七星风格)")
    print("="*60)
    
    # 获取排名
    print("\n[1/3] 获取ETF排名...")
    rankings = get_rankings()
    print(f"  [OK] 成功获取 {len(rankings)} 只ETF排名")
    
    # 排名变化
    print("\n[2/3] 计算排名变化...")
    rank_changes = get_rank_changes(rankings)
    print(f"  [OK] 排名变化计算完成")
    
    # 获取持仓
    print("\n[3/3] 检查持仓...")
    positions = get_positions()
    print(f"  [OK] 当前持仓 {len(positions)} 只ETF")
    
    # 发送邮件
    print("\n[4/4] 发送HTML邮件（三马七星风格）...")
    send_email(rankings, rank_changes, positions)
    
    print("\n" + "="*60)
    print("拉普拉斯盘中监控完成（三马七星风格）")
    print("="*60)
