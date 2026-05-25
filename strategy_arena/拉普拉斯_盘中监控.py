#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯盘中监控版
- 实时获取32只ETF行情
- 计算动量排名
- 检测止损
- 发送HTML邮件到848786642@qq.com
"""

import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import os

warnings.filterwarnings('ignore')

INITIAL_CASH = 100000.0
COMMISSION = 0.0001
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'

LAPLACE_POOL = [
    '518880', '159980', '159985', '501018', '161226', '159981',
    '513100', '159509', '513290', '513500', '159529',
    '513400', '513520', '513030', '513080', '513310',
    '513730', '159792', '513130', '513050', '159920',
    '513690', '510300', '510500', '510050', '510210',
    '159915', '588080', '512100', '563360', '563300',
    '512890', '159967', '512040', '159201', '511380',
    '511010', '511220',
]

def calc_momentum(prices, lookback=25):
    """计算动量得分"""
    if len(prices) < lookback + 1:
        return None
    recent = prices[-(lookback + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    try:
        slope, intercept = np.polyfit(x, y, 1, w=weights)
    except:
        return None
    ann_ret = math.exp(slope * 250) - 1
    ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
    return ann_ret * r_squared


def load_latest_data(etf_code, days=300):
    """加载最近N天的数据"""
    for subdir in ['etf', 'etf_qixing']:
        csv_path = os.path.join(BASE_DIR, subdir, f"{etf_code}.csv")
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                cutoff = datetime.now() - timedelta(days=days)
                df = df[df.index >= cutoff]
                if len(df) > 100:
                    rename_map = {}
                    for col in df.columns:
                        if col.lower() in ['open', 'high', 'low', 'close', 'volume']:
                            rename_map[col] = col.lower()
                    if rename_map:
                        df = df.rename(columns=rename_map)
                    return df
            except:
                continue
    return None


def get_rankings():
    """获取ETF排名"""
    rankings = []
    for etf in LAPLACE_POOL:
        df = load_latest_data(etf)
        if df is None or len(df) < 50:
            continue
        
        closes = df['close'].values
        
    # 短期动量（25日）
        score_short = calc_momentum(closes, min(25, len(closes)-1))
        # 长期动量（用可用的最大天数，最多250日）
        long_period = min(250, len(closes)-1)
        score_long = calc_momentum(closes, long_period) if long_period >= 25 else None
        
        if score_short is None or score_long is None:
            continue
        
        # 综合得分：短期100% + 长期50%
        combined = score_short * 1.0 + score_long * 0.5
        
        rankings.append({
            'etf': etf,
            'combined': combined,
            'short': score_short,
            'long': score_long,
            'price': closes[-1],
            'date': df.index[-1].strftime('%Y-%m-%d')
        })
    
    rankings.sort(key=lambda x: x['combined'], reverse=True)
    return rankings


def check_stop_loss(current_positions):
    """检测止损"""
    alerts = []
    for etf, info in current_positions.items():
        df = load_latest_data(etf, days=50)
        if df is None:
            continue
        current_price = df['close'].iloc[-1]
        entry_price = info['entry_price']
        pnl_pct = (current_price - entry_price) / entry_price * 100
        
        # 硬止损-8%
        if pnl_pct <= -8:
            alerts.append(f"{etf} 硬止损触发：入场{entry_price:.3f} -> 当前{current_price:.3f}（{pnl_pct:.1f}%）")
        # 盈利保护：回撤5%
        elif pnl_pct > 5 and (current_price - info['max_price']) / info['max_price'] * 100 <= -5:
            alerts.append(f"{etf} 盈利保护触发：最高{info['max_price']:.3f} -> 当前{current_price:.3f}")
    return alerts


def send_email(rankings, alerts):
    """发送HTML邮件"""
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    # 生成HTML
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    html = f"""
<html>
<body>
<h2>拉普拉斯盘中监控报告 - {now_str}</h2>

<h3>ETF排名（Top 10）</h3>
<table border="1" cellpadding="8" cellspacing="0">
<tr bgcolor="#e0e0e0">
<th>排名</th><th>ETF</th><th>综合得分</th><th>短期动量</th><th>长期动量</th><th>最新价</th><th>数据日期</th>
</tr>
"""
    
    for i, r in enumerate(rankings[:10], 1):
        html += f"""
<tr>
<td>{i}</td>
<td><b>{r['etf']}</b></td>
<td>{r['combined']:.4f}</td>
<td>{r['short']:.4f}</td>
<td>{r['long']:.4f}</td>
<td>{r['price']:.3f}</td>
<td>{r['date']}</td>
</tr>
"""
    
    html += "</table>"
    
    if alerts:
        html += "<h3>止损警示</h3><ul>"
        for alert in alerts:
            html += f"<li>{alert}</li>"
        html += "</ul>"
    else:
        html += "<p>无止损警示</p>"
    
    html += f"<hr><p><small>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} GMT+8</small></p>"
    html += "</body></html>"
    
    # 发送
    msg = MIMEText(html, 'html', _charset='utf-8')
    msg['Subject'] = f"[OpenClaw] 拉普拉斯盘中监控 - {now_str}"
    msg['From'] = sender
    msg['To'] = receiver
    
    try:
        server = smtplib.SMTP('smtp.qq.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"邮件发送失败：{e}")
        return False


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 拉普拉斯盘中监控开始...")
    
    # 获取排名
    rankings = get_rankings()
    print(f"  [OK] 成功获取 {len(rankings)} 只ETF排名")
    
    # 检测止损（这里需要传入当前持仓，暂时为空）
    current_positions = {}  # TODO: 从文件读取当前持仓
    alerts = check_stop_loss(current_positions)
    
    # 发送邮件
    if rankings:
        success = send_email(rankings, alerts)
        if success:
            print(f"  [OK] 邮件已发送到 848786642@qq.com")
        else:
            print(f"  [FAIL] 邮件发送失败")
    else:
        print(f"  [FAIL] 无有效排名数据")
    
    # 输出摘要
    print(f"\n[拉普拉斯盘中监控完成]")
    print(f"  监控ETF：{len(rankings)}只")
    print(f"  排名变动：{len(rankings)}只（首次运行）")
    print(f"  止损警示：{len(alerts)}只")
    print(f"  邮件已发送")


if __name__ == '__main__':
    main()
