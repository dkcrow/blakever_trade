#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯盘中监控 v5 - 修复版
- 修复盈利保护逻辑：先更新最高价，再计算回撤
- 实时价格 + 止损检测
- 交易记录系统（买入/卖出/盈亏）
- 持久化到 laplace_trades.json
- 邮件显示近20次交易
"""

import pandas as pd
import numpy as np
import math
import warnings
import smtplib
import json
import urllib.request
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import os
import sys

warnings.filterwarnings('ignore')

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'
TRADE_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\laplace_trades.json'

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

# ==================== 交易记录管理 ====================

def load_trades():
    """加载交易记录"""
    if not os.path.exists(TRADE_FILE):
        return {"trades": [], "positions": {}}
    try:
        with open(TRADE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"trades": [], "positions": {}}

def save_trades(data):
    """保存交易记录"""
    with open(TRADE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_trade(etf, action, price, reason, pnl_pct=None):
    """添加交易记录，返回trade_id"""
    data = load_trades()
    trade_id = len(data['trades']) + 1
    trade = {
        "id": trade_id,
        "etf": etf,
        "name": ETF_NAMES.get(etf, etf),
        "action": action,
        "date": datetime.now().strftime('%Y-%m-%d'),
        "price": round(price, 3),
        "reason": reason,
        "pnl_pct": round(pnl_pct, 1) if pnl_pct is not None else None
    }
    data['trades'].append(trade)
    save_trades(data)
    return trade_id

def update_position(etf, entry_price=None, entry_date=None, max_price=None):
    """更新持仓（None表示删除）"""
    data = load_trades()
    if entry_price is None:
        if etf in data['positions']:
            del data['positions'][etf]
    else:
        data['positions'][etf] = {
            "entry_price": entry_price,
            "entry_date": entry_date,
            "max_price": max_price or entry_price
        }
    save_trades(data)

def get_recent_trades(n=20):
    """获取最近N次交易（最新的在前）"""
    data = load_trades()
    trades = data['trades'][-n:]
    trades.reverse()
    return trades

def get_positions():
    """获取当前持仓"""
    data = load_trades()
    return data['positions']

# ==================== 核心逻辑 ====================

def get_realtime_price(etf_code):
    """从腾讯接口获取实时价"""
    if etf_code.startswith('5'):
        prefix = 'sh'
    elif etf_code.startswith('1'):
        prefix = 'sz'
    else:
        return None
    
    url = f'http://qt.gtimg.cn/q={prefix}{etf_code}'
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            data = response.read().decode('gbk')
            if '~' in data:
                parts = data.split('~')
                if len(parts) > 3:
                    return float(parts[3])
    except:
        pass
    return None

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
    """获取ETF排名"""
    rankings = []
    
    for etf in ETF_NAMES.keys():
        df = load_latest_data(etf)
        if df is None or len(df) < 50:
            continue
        
        closes = df['close'].values
        score_short = calc_momentum(closes, min(25, len(closes)-1))
        long_period = min(250, len(closes)-1)
        score_long = calc_momentum(closes, long_period) if long_period >= 25 else None
        
        if score_short is None:
            continue
        
        combined = score_short * 1.0
        if score_long is not None:
            combined += score_long * 0.5
        
        realtime_price = get_realtime_price(etf)
        display_price = realtime_price if realtime_price else closes[-1]
        display_date = datetime.now().strftime('%Y-%m-%d') if realtime_price else df.index[-1].strftime('%Y-%m-%d')
        
        rankings.append({
            'etf': etf,
            'name': ETF_NAMES.get(etf, etf),
            'combined': combined,
            'short': score_short,
            'long': score_long if score_long else 0,
            'price': display_price,
            'date': display_date,
            'is_realtime': realtime_price is not None
        })
    
    rankings.sort(key=lambda x: x['combined'], reverse=True)
    return rankings

def check_stop_loss():
    """检测止损，更新交易记录"""
    alerts = []
    positions = get_positions()
    
    if not positions:
        print('当前无持仓')
        return alerts, []
    
    print(f'当前持仓 {len(positions)} 只ETF')
    highlight_ids = []
    
    for etf, info in positions.items():
        current_price = get_realtime_price(etf)
        if current_price is None:
            print(f'{etf}: 无法获取实时价')
            continue
        
        entry_price = info['entry_price']
        pnl_pct = (current_price - entry_price) / entry_price * 100
        print(f'{etf}: 入场={entry_price:.3f}, 当前={current_price:.3f}, 盈亏={pnl_pct:.1f}%')
        
        # 硬止损-8%
        if pnl_pct <= -8:
            reason = f"硬止损触发（{pnl_pct:.1f}%）"
            print(f'  => 触发硬止损！')
            alerts.append({
                'etf': etf,
                'name': ETF_NAMES.get(etf, etf),
                'type': '硬止损',
                'entry': entry_price,
                'current': current_price,
                'pnl': pnl_pct
            })
            # 记录卖出
            trade_id = add_trade(etf, '卖出', current_price, reason, pnl_pct)
            highlight_ids.append(trade_id)
            # 删除持仓
            update_position(etf, None)
        
        # 盈利保护：回撤5%
        elif pnl_pct > 5:
            max_price = info.get('max_price', entry_price)
            # 先更新最高价
            if current_price > max_price:
                update_position(etf, entry_price, info['entry_date'], current_price)
                max_price = current_price  # 更新为最新最高价
            
            # 再计算回撤
            drawdown = (current_price - max_price) / max_price * 100
            print(f'  盈利>{5}%, 最高={max_price}, 回撤={drawdown:.1f}%')
            
            if drawdown <= -5:
                reason = f"盈利保护触发（最高{max_price:.3f}→当前{current_price:.3f}，回撤{drawdown:.1f}%）"
                print(f'  => 触发盈利保护！')
                alerts.append({
                    'etf': etf,
                    'name': ETF_NAMES.get(etf, etf),
                    'type': '盈利保护',
                    'entry': entry_price,
                    'current': current_price,
                    'high': max_price,
                    'pnl': pnl_pct
                })
                trade_id = add_trade(etf, '卖出', current_price, reason, pnl_pct)
                highlight_ids.append(trade_id)
                update_position(etf, None)
            else:
                print(f'  未触发盈利保护（回撤 {drawdown:.1f}% > -5%）')
        else:
            print(f'  未触发（盈亏 {pnl_pct:.1f}% 未达条件）')
    
    return alerts, highlight_ids

# ==================== 邮件发送 ====================

def send_email(rankings, alerts, highlight_ids):
    """发送精美HTML邮件（含交易记录）"""
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # HTML模板
    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
            .section {{ background: white; padding: 15px; margin-bottom: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .ranking {{ margin: 10px 0; padding: 10px; background: #f8f9fa; border-left: 4px solid #667eea; }}
            .alert {{ background: #ffe6e6; border-left: 4px solid #ff4444; padding: 10px; margin: 5px 0; border-radius: 4px; }}
            .trades-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            .trades-table th {{ background: #667eea; color: white; padding: 8px; text-align: left; }}
            .trades-table td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
            .highlight {{ background: #ffe6e6 !important; font-weight: bold; }}
            .positive {{ color: #28a745; }}
            .negative {{ color: #dc3545; }}
            .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; }}
            .badge-red {{ background: #ffe6e6; color: #dc3545; }}
            .badge-green {{ background: #d4edda; color: #28a745; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>📊 拉普拉斯策略盘中监控</h2>
            <p>{now_str}</p>
        </div>
        
        <div class="section">
            <h3>🏆 ETF排名（Top10）</h3>
    """
    
    # 排名
    for i, r in enumerate(rankings[:10]):
        realtime_badge = '<span class="badge badge-green">实时</span>' if r['is_realtime'] else '<span class="badge">CSV</span>'
        html += f"""
            <div class="ranking">
                <strong>#{i+1} {r['name']} ({r['etf']})</strong> {realtime_badge}<br>
                综合: {r['combined']:.4f} | 短期: {r['short']:.4f} | 长期: {r['long']:.4f}<br>
                价格: {r['price']:.3f} ({r['date']})
            </div>
        """
    
    # 止损警示
    if alerts:
        html += f"""
        <div class="section">
            <h3>⚠️ 止损警示（{len(alerts)}只）</h3>
        """
        for alert in alerts:
            html += f"""
            <div class="alert">
                <strong>{alert['name']} ({alert['etf']})</strong> - {alert['type']}<br>
                入场: {alert['entry']:.3f} → 当前: {alert['current']:.3f} 
                (盈亏: <span class="{'positive' if alert.get('pnl', 0) >= 0 else 'negative'}">{alert.get('pnl', 0):.1f}%</span>)<br>
            """
            if 'high' in alert:
                html += f"最高: {alert['high']:.3f}<br>"
            html += "</div>"
        html += "</div>"
    
    # 最近交易
    recent_trades = get_recent_trades(20)
    if recent_trades:
        html += f"""
        <div class="section">
            <h3>📋 近20次交易记录</h3>
            <table class="trades-table">
                <tr>
                    <th>ID</th><th>日期</th><th>ETF</th><th>操作</th><th>价格</th><th>盈亏%</th><th>原因</th>
                </tr>
        """
        for trade in recent_trades:
            highlight = 'class="highlight"' if trade['id'] in highlight_ids else ''
            pnl_class = 'positive' if (trade.get('pnl_pct') or 0) >= 0 else 'negative'
            pnl_display = f"{trade['pnl_pct']:.1f}%" if trade.get('pnl_pct') is not None else '-'
            html += f"""
                <tr {highlight}>
                    <td>{trade['id']}</td>
                    <td>{trade['date']}</td>
                    <td>{trade['name']} ({trade['etf']})</td>
                    <td>{trade['action']}</td>
                    <td>{trade['price']:.3f}</td>
                    <td class="{pnl_class}">{pnl_display}</td>
                    <td>{trade['reason']}</td>
                </tr>
            """
        html += """
            </table>
        </div>
        """
    
    html += """
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
