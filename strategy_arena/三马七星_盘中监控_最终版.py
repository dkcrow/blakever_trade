#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马七星美股版 - 盘中监控 v1.0
核心参数（基于V7优化）：
- ATR 2倍动态止损
- Top3持仓（max_positions=3）
- 20/60日回看周期
- 最小得分0.15
- 美股15只：NVDA, AMD, MU, AVGO, TSLA, AAPL, GOOG, AMZN, KO, NEM, XOM, AEP, JPM, GS, BRK-B
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import smtplib
from email.mime.text import MIMEText
import warnings
import os
import urllib.request
import sys

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

# =============================================================
# 配置
# =============================================================
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks'

STOCK_POOL = {
    'NVDA': '英伟达', 'AMD': '超微半导体', 'MU': '美光科技',
    'AVGO': '博通', 'TSLA': '特斯拉', 'AAPL': '苹果',
    'GOOG': '谷歌', 'AMZN': '亚马逊', 'KO': '可口可乐',
    'NEM': '纽曼矿业', 'XOM': '埃克森美孚', 'AEP': '美国电力',
    'JPM': '摩根大通', 'GS': '高盛', 'BRK-B': '伯克希尔-B',
}

SHORT_LOOKBACK = 20
LONG_LOOKBACK = 60
ATR_MULTIPLIER = 2.0
ATR_PERIOD = 14
MIN_SCORE = 0.15
MAX_POSITIONS = 3

TRADE_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\sanma_trades.json'
RANK_HISTORY_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\sanma_rankings_history.json'

# =============================================================
# 获取排名
# =============================================================
def calculate_momentum_score(stock_code):
    """计算动量综合得分（加权回归）"""
    try:
        path = os.path.join(BASE_DIR, f'{stock_code}.csv')
        if not os.path.exists(path):
            return None
        
        df = pd.read_csv(path)
        # 兼容列名
        column_map = {col.lower(): col for col in df.columns}
        if 'date' in column_map and column_map['date'] != 'date':
            df = df.rename(columns={column_map['date']: 'date'})
        if 'close' in column_map and column_map['close'] != 'close':
            df = df.rename(columns={column_map['close']: 'close'})
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        if len(df) < 30:
            return None
        
        prices = df['close'].tolist()
        current_price = prices[-1]
        
        # 短期动量（20日加权回归）
        if len(prices) >= SHORT_LOOKBACK:
            sp = prices[-SHORT_LOOKBACK:]
            ann_s, r2_s, score_s = weighted_reg(sp)
        else:
            score_s = 0
        
        # 长期动量（60日加权回归）
        if len(prices) >= LONG_LOOKBACK:
            lp = prices[-LONG_LOOKBACK:]
            ann_l, r2_l, score_l = weighted_reg(lp)
        else:
            score_l = 0
        
        # 综合得分
        combined = score_s * 1.0 + score_l * 0.5
        
        return {
            'stock': stock_code,
            'name': STOCK_POOL.get(stock_code, stock_code),
            'short': score_s,
            'long': score_l,
            'combined': combined,
            'price': current_price,
            'date': df.iloc[-1]['date'].strftime('%Y-%m-%d')
        }
    except Exception as e:
        return None

def weighted_reg(prices_list):
    """加权线性回归"""
    n = len(prices_list)
    if n < 5:
        return 0, 0, 0
    
    y = [np.log(max(p, 0.001)) for p in prices_list]
    x = np.arange(n)
    w = np.linspace(1, 2, n)
    w_sum = w.sum()
    
    xm = (w * x).sum() / w_sum
    ym = (w * y).sum() / w_sum
    
    num = (w * (x - xm) * (y - ym)).sum()
    den = (w * (x - xm) ** 2).sum()
    slope = num / den if abs(den) > 1e-10 else 0
    
    ss_tot = (w * (y - ym) ** 2).sum()
    y_pred = slope * (x - xm) + ym
    ss_res = (w * (y - y_pred) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0
    
    ann_return = np.exp(slope * 252) - 1
    return ann_return, r2, ann_return * r2

def get_rankings():
    """获取所有股票排名"""
    rankings = []
    for stock_code in STOCK_POOL.keys():
        score = calculate_momentum_score(stock_code)
        if score and score['combined'] >= MIN_SCORE:
            rankings.append(score)
    
    # 按综合得分排序
    rankings.sort(key=lambda x: x['combined'], reverse=True)
    return rankings

# =============================================================
# 交易记录
# =============================================================
def load_trades():
    """加载交易记录"""
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('trades', [])
        except:
            pass
    return []

def load_rank_history():
    """加载排名历史"""
    if os.path.exists(RANK_HISTORY_FILE):
        try:
            with open(RANK_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_rank_history(rankings):
    """保存当前排名"""
    history = {r['stock']: i+1 for i, r in enumerate(rankings)}
    with open(RANK_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False)

def get_rank_change(stock_code, current_rank, rank_history):
    """获取排名变动"""
    if stock_code not in rank_history:
        return '→0'
    
    old_rank = rank_history[stock_code]
    diff = old_rank - current_rank
    
    if diff > 0:
        return f'↑{diff}'
    elif diff < 0:
        return f'↓{abs(diff)}'
    else:
        return '→0'

# =============================================================
# 发送邮件（模仿拉普拉斯v14格式）
# =============================================================
def send_email(rankings):
    """发送HTML邮件"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 加载排名历史
    rank_history = load_rank_history()
    
    # Top3
    top3 = rankings[:3]
    top_summary = ' | '.join([
        f"🥇 {r['name']}" if i==0 else (f"🥈 {r['name']}" if i==1 else f"🥉 {r['name']}")
        for i, r in enumerate(top3)
    ])
    
    # 排名变动
    rank_change_summary = ' | '.join([
        f"{r['name']} {get_rank_change(r['stock'], i+1, rank_history)}"
        for i, r in enumerate(top3)
    ])
    
    # HTML头部
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ margin:0; padding:0; background:#f8f9fa; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; }}
  .container {{ max-width:760px; margin:0 auto; padding:16px; }}
  .header {{ text-align:center; padding:20px 0 12px; border-bottom:2px solid #e5e7eb; }}
  .header h1 {{ color:#111827; margin:0 0 4px; font-size:20px; }}
  .header .sub {{ color:#6b7280; margin:0; font-size:12px; }}
  .badge {{ display:inline-block; background:#dbeafe; color:#1d4ed8; font-size:11px; padding:2px 8px; border-radius:10px; margin-left:6px; }}
  .top-bar {{ background:#ffffff; border-radius:8px; padding:12px 16px; margin-top:16px; text-align:center; border:1px solid #e5e7eb; }}
  .top-bar .top3 {{ font-size:14px; color:#111827; font-weight:600; }}
  .change-section {{ margin-top:16px; padding:12px 16px; background:#ffffff; border-radius:8px; border:1px solid #e5e7eb; }}
  .change-section .title {{ font-size:13px; color:#6b7280; font-weight:600; margin-bottom:8px; }}
  .change-section .content {{ font-size:11px; line-height:1.8; }}
  .table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:12px; }}
  .table th {{ background:#1d4ed8; color:white; padding:8px 6px; text-align:left; font-size:12px; font-weight:600; }}
  .table td {{ padding:8px 6px; border-bottom:1px solid #e5e7eb; font-size:12px; }}
  .rank-1 {{ background:#fef3c7 !important; }}
  .highlight {{ background:#fef3c7 !important; font-weight:bold; }}
  .positive {{ color:#059669; font-weight:bold; }}
  .negative {{ color:#dc2626; font-weight:bold; }}
  .footer {{ text-align:center; color:#6b7280; font-size:10px; margin-top:16px; padding:12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>三马七星策略盘中监控</h1>
    <p class="sub">{now_str}</p>
  </div>
  
  <div class="top-bar">
    <div class="top3">{top_summary}</div>
    <div style="font-size:11px;color:#6b7280;margin-top:4px;">{rank_change_summary}</div>
  </div>
  
  <div class="change-section">
    <div class="title">美股排名 Top 10（共{len(rankings)}只）</div>
    <table class="table">
      <tr>
        <th style="text-align:center;width:40px;">排名</th>
        <th style="width:120px;">股票名称</th>
        <th style="text-align:center;width:60px;">代码</th>
        <th style="text-align:right;width:70px;">综合分</th>
        <th style="text-align:right;width:70px;">短期</th>
        <th style="text-align:right;width:70px;">长期</th>
        <th style="text-align:right;width:60px;">价格</th>
        <th style="width:80px;">日期</th>
        <th style="width:50px;">变动</th>
      </tr>
'''
    
    # 排名表格
    for i, r in enumerate(rankings[:10]):
        rank = i + 1
        rank_change = get_rank_change(r['stock'], rank, rank_history)
        row_class = 'rank-1' if rank == 1 else ''
        
        html += f'''      <tr class="{row_class}">
        <td style="text-align:center;">{rank}</td>
        <td>{r['name']}</td>
        <td style="text-align:center;">{r['stock']}</td>
        <td style="text-align:right;">{r['combined']:.4f}</td>
        <td style="text-align:right;">{r['short']:.4f}</td>
        <td style="text-align:right;">{r['long']:.4f}</td>
        <td style="text-align:right;">{r['price']:.2f}</td>
        <td>{r['date']}</td>
        <td>{rank_change}</td>
      </tr>
'''
    
    html += '''    </table>
  </div>
'''
    
    # 交易记录
    trades_html = ''
    try:
        trades = load_trades()[-20:]  # 最近20条
        if trades:
            trades_html = '''
  <div style="margin-top:16px;padding:12px 16px;background:#ffffff;border-radius:8px;border:1px solid #e5e7eb;">
    <div style="font-size:13px;color:#6b7280;font-weight:600;margin-bottom:8px;">近20次交易记录</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <tr style="color:#6b7280;font-size:11px;">
        <th style="text-align:left;padding:4px 6px;">日期</th>
        <th style="text-align:left;padding:4px 6px;">股票（代码）</th>
        <th style="text-align:center;padding:4px 6px;">操作</th>
        <th style="text-align:right;padding:4px 6px;">价格</th>
        <th style="text-align:right;padding:4px 6px;">盈亏%</th>
        <th style="text-align:left;padding:4px 6px;">理由</th>
      </tr>
'''
            now_time = datetime.now().strftime('%Y-%m-%d')
            for t in reversed(trades):
                pnl = t.get('pnl_pct')
                pnl_str = f"{pnl:.1f}%" if pnl is not None else '-'
                pnl_color = '#059669' if (pnl or 0) >= 0 else '#dc2626'
                name = STOCK_POOL.get(t['stock'], t['stock'])
                stock_display = f"{name} ({t['stock']})"
                reason = t.get('reason', '-')
                
                is_current = t.get('date', '').startswith(now_time)
                row_style = 'background:#fef3c7;' if is_current else ''
                
                trades_html += f'''      <tr style="{row_style}">
        <td style="padding:4px 6px;color:#374151">{t['date']}</td>
        <td style="padding:4px 6px;color:#111827">{stock_display}</td>
        <td style="padding:4px 6px;text-align:center">{t['action']}</td>
        <td style="padding:4px 6px;text-align:right;font-weight:600">{t['price']:.2f}</td>
        <td style="padding:4px 6px;text-align:right;color:{pnl_color};font-weight:600">{pnl_str}</td>
        <td style="padding:4px 6px;color:#6b7280;font-size:11px;">{reason}</td>
      </tr>
'''
            trades_html += '''    </table>
  </div>
'''
    except Exception as e:
        print(f'[WARNING] 交易记录加载失败: {e}')
    
    html += trades_html
    
    html += f'''
  <div class="footer">
    三马七星策略盘中监控 | 自动发送 | {now_str}
  </div>
</div>
</body>
</html>'''
    
    # 发送邮件
    try:
        msg = MIMEText(html, 'html', 'utf-8')
        msg['Subject'] = f'三马七星盘中监控 {now_str}'
        msg['From'] = '848786642@qq.com'
        msg['To'] = '848786642@qq.com'
        
        server = smtplib.SMTP('smtp.qq.com', 587, timeout=10)
        server.starttls()
        server.login('848786642@qq.com', 'ljbtvacrctjobfed')
        server.sendmail('848786642@qq.com', ['848786642@qq.com'], msg.as_string())
        server.quit()
        
        print('[OK] 三马七星邮件已发送（含交易记录）')
        return True
    except Exception as e:
        print(f'[ERROR] 邮件发送失败: {e}')
        return False

# =============================================================
# 主函数
# =============================================================
def main():
    print('=' * 60)
    print('三马七星美股版盘中监控 v1.0 开始...')
    print('=' * 60)
    
    # 1. 获取排名
    print('\n[1/2] 获取美股排名...')
    rankings = get_rankings()
    print(f'  [OK] 成功获取 {len(rankings)} 只美股排名')
    
    # 2. 发送邮件
    print('\n[2/2] 发送HTML邮件...')
    send_email(rankings)
    
    # 保存排名历史
    save_rank_history(rankings)
    
    print('\n' + '=' * 60)
    print('三马七星盘中监控完成')
    print(f'  美股: {len(rankings)}只')
    print('=' * 60)

if __name__ == '__main__':
    main()
