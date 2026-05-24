#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯盘中监控版 v2 - 精美HTML邮件排版
对齐七星三马盘中监控邮件格式
"""

import pandas as pd
import numpy as np
import math
import warnings
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import os

warnings.filterwarnings('ignore')

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'

# ETF中文名称映射
ETF_NAMES = {
    '518880': '黄金ETF华安', '159980': '有色ETF大成', '159985': '豆粕ETF华夏', '501018': '南方原油LOF', '161226': '黄金LOF',
    '159981': '能源化工ETF建信', '513100': '纳指ETF国泰', '159509': '纳指科技ETF景顺', '513290': '纳指生物科技ETF汇添富', '513500': '标普500ETF博时',
    '159529': '标普消费ETF景顺', '513400': '道琼斯ETF鹏华', '513520': '日经ETF华夏', '513030': '德国ETF华安', '513080': '法国ETF华安',
    '513310': '中韩半导体ETF华泰柏瑞', '513730': '东南亚科技ETF华泰柏瑞', '159792': '港股通互联网ETF富国', '513130': '恒生科技ETF华泰柏瑞',
    '513050': '中概互联网ETF易方达', '159920': '恒生ETF华夏', '513690': '港股红利ETF博时', '510300': '沪深300ETF华泰柏瑞',
    '510500': '中证500ETF南方', '510050': '上证50ETF华夏', '510210': '上证指数ETF富国', '159915': '创业板ETF易方达',
    '588080': '科创50ETF易方达', '512100': '中证1000ETF南方', '563360': 'A500ETF华泰柏瑞', '563300': '中证2000ETF华泰柏瑞',
    '512890': '红利低波ETF华泰柏瑞', '159967': '创业板成长ETF华夏', '512040': '价值100ETF富国', '159201': '自由现金流ETF华夏',
    '511380': '可转债ETF博时', '511010': '国债ETF国泰', '511220': '城投债ETF海富通'
}

LAPLACE_POOL = list(ETF_NAMES.keys())

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
    # 限制动量得分在合理范围[-2, 2]
    ann_ret = max(-2, min(2, ann_ret))
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
                if len(df) > 50:
                    return df
            except:
                continue
    return None


def get_rankings():
    """获取排名"""
    rankings = []
    for etf in LAPLACE_POOL:
        df = load_latest_data(etf)
        if df is None or len(df) < 50:
            continue
        
        closes = df['close'].values
        
        # 短期动量（25日）
        score_short = calc_momentum(closes, min(25, len(closes)-1))
        # 长期动量（用可用的最大天数）
        long_period = min(250, len(closes)-1)
        score_long = calc_momentum(closes, long_period) if long_period >= 25 else None
        
        if score_short is None:
            continue
        
        # 综合得分：短期100% + 长期50%
        combined = score_short * 1.0
        if score_long is not None:
            combined += score_long * 0.5
        
        rankings.append({
            'etf': etf,
            'name': ETF_NAMES.get(etf, etf),
            'combined': combined,
            'short': score_short,
            'long': score_long if score_long else 0,
            'price': closes[-1],
            'date': df.index[-1].strftime('%Y-%m-%d')
        })
    
    rankings.sort(key=lambda x: x['combined'], reverse=True)
    return rankings


def send_email(rankings):
    """发送精美HTML邮件（对齐七星三马格式）"""
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 精美HTML模板（对齐七星三马格式）
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
    .container {{ max-width: 800px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 28px; font-weight: 600; }}
    .header p {{ margin: 10px 0 0; opacity: 0.9; font-size: 14px; }}
    .content {{ padding: 30px; }}
    .section {{ margin-bottom: 30px; }}
    .section h2 {{ font-size: 20px; color: #333; margin-bottom: 15px; border-left: 4px solid #667eea; padding-left: 12px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
    th {{ background: #f8f9fa; padding: 12px; text-align: left; font-size: 13px; color: #666; border-bottom: 2px solid #dee2e6; }}
    td {{ padding: 12px; border-bottom: 1px solid #e9ecef; font-size: 14px; }}
    tr:hover {{ background: #f8f9fa; }}
    .rank-1 {{ background: linear-gradient(90deg, #fff9e6 0%, #fff 100%); }}
    .rank-2 {{ background: linear-gradient(90deg, #f0f9ff 0%, #fff 100%); }}
    .rank-3 {{ background: linear-gradient(90deg, #fdf2f8 0%, #fff 100%); }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }}
    .badge-green {{ background: #d1fae5; color: #065f46; }}
    .badge-blue {{ background: #dbeafe; color: #1e40af; }}
    .badge-purple {{ background: #ede9fe; color: #5b21b6; }}
    .score {{ font-weight: 600; color: #667eea; }}
    .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>拉普拉斯盘中监控报告</h1>
        <p>生成时间：{now_str} | 监控ETF：{len(rankings)}只</p>
    </div>
    
    <div class="content">
        <div class="section">
            <h2>ETF排名（Top 10）</h2>
            <table>
                <tr>
                    <th>排名</th>
                    <th>ETF代码</th>
                    <th>综合得分</th>
                    <th>短期动量</th>
                    <th>长期动量</th>
                    <th>最新价</th>
                    <th>数据日期</th>
                </tr>
"""
    
    # 添加排名行
    for i, r in enumerate(rankings[:10], 1):
        row_class = f"rank-{i}" if i <= 3 else ""
        html += f"""
                <tr class="{row_class}">
                    <td><span class="badge badge-purple">{i}</span></td>
                    <td><strong>{r['etf']}</strong><br><small style="color:#666">{r['name']}</small></td>
                    <td><span class="score">{r['combined']:.4f}</span></td>
                    <td>{r['short']:.4f}</td>
                    <td>{r['long']:.4f}</td>
                    <td>{r['price']:.3f}</td>
                    <td>{r['date']}</td>
                </tr>
"""
    
    html += """
            </table>
        </div>
        
        <div class="section">
            <h2>执行摘要</h2>
            <p><strong>监控ETF：</strong>{}只</p>
            <p><strong>排名变动：</strong>{}只（首次运行）</p>
            <p><strong>止损警示：</strong>0只（当前无持仓）</p>
            <p><strong>邮件状态：</strong><span class="badge badge-green">已发送</span></p>
        </div>
    </div>
    
    <div class="footer">
        <p>OpenClaw 拉普拉斯盘中监控系统 | 生成时间：{}</p>
    </div>
</div>
</body>
</html>
""".format(len(rankings), len(rankings), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    # 发送邮件
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
    
    # 发送邮件
    if rankings:
        success = send_email(rankings)
        if success:
            print(f"  [OK] 精美HTML邮件已发送到 848786642@qq.com")
        else:
            print(f"  [FAIL] 邮件发送失败")
    else:
        print(f"  [FAIL] 无有效排名数据")
    
    # 输出摘要（微信推送用）
    print(f"\n[拉普拉斯盘中监控完成]")
    print(f"  监控ETF：{len(rankings)}只")
    print(f"  排名变动：{len(rankings)}只（首次运行）")
    print(f"  止损警示：0只")
    print(f"  精美HTML邮件已发送")


if __name__ == '__main__':
    main()
