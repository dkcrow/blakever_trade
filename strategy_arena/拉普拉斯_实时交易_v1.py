"""
拉普拉斯实时交易脚本 - v1
自动执行买卖操作，更新交易记录
"""
import urllib.request
import json
import smtplib
from email.mime.text import MIMEText
import time
import os
import pandas as pd
import numpy as np

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'
WORKSPACE = r'C:\Users\blakehao\.qclaw\workspace'

ETF_POOL = [
    '518880', '159980', '159985', '501018', '161226', '159981',
    '513100', '159509', '513290', '513500', '159529', '513400',
    '513520', '513030', '513080', '513310', '513730', '159792',
    '513130', '513050', '159920', '513690', '510300', '510500',
    '510050', '510210', '512100', '159915', '159922', '588080',
    '512690', '515790', '159611', '159766', '159996', '512660',
    '515030', '515790', '159997', '159967'
]

ETF_NAMES = {
    "518880": "黄金ETF华安",
    "159980": "有色金属ETF",
    "159985": "豆粕ETF",
    "501018": "南方原油LOF",
    "161226": "白银LOF国投瑞银",
    "159981": "能源化工ETF",
    "513100": "纳指100ETF易方达",
    "159509": "纳指科技ETF景顺",
    "513290": "纳指100ETF华夏",
    "513500": "纳指100ETF博时",
    "159529": "纳指科技ETF易方达",
    "513400": "纳指ETF道富",
    "513520": "日经225ETF",
    "513030": "德国30ETF",
    "513080": "法国CAC40ETF",
    "513310": "中韩半导体ETF华泰柏瑞",
    "513730": "东南亚科技ETF",
    "159792": "港股科技ETF",
    "513130": "恒生科技ETF华泰柏瑞",
    "513050": "中概互联ETF易方达",
    "159920": "恒生ETF华夏",
    "513690": "恒生股息ETF",
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "510050": "上证50ETF",
    "510210": "上证180ETF",
    "512100": "中证1000ETF",
    "159915": "创业板ETF易方达",
    "159922": "中证500ETF嘉实",
    "588080": "科创50ETF易方达",
    "512690": "酒ETF鹏华",
    "515790": "光伏ETF华泰柏瑞",
    "159611": "电力ETF华夏",
    "159766": "旅游ETF富国",
    "159996": "家电ETF国泰",
    "512660": "军工ETF国泰",
    "515030": "新能源车ETF华夏",
    "159997": "电子ETF天弘",
    "159967": "创成长ETF华夏"
}

def get_tencent_realtime_prices():
    """获取腾讯API实时价格"""
    prices = {}
    batch_size = 10
    
    for i in range(0, len(ETF_POOL), batch_size):
        batch = ETF_POOL[i:i+batch_size]
        query_parts = []
        for code in batch:
            if code.startswith('5') or code.startswith('6') or code.startswith('9'):
                query_parts.append(f'sh{code}')
            else:
                query_parts.append(f'sz{code}')
        query = ','.join(query_parts)
        url = f'http://qt.gtimg.cn/q={query}'
        
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                data = r.read().decode('gbk')
                for line in data.strip().split(';'):
                    if '~' in line:
                        parts = line.split('~')
                        if len(parts) > 5:
                            full_code = parts[2]
                            code = ''.join(c for c in full_code if c.isdigit())
                            try:
                                price = float(parts[3])
                                yc = float(parts[4])
                                if yc > 0:
                                    prices[code] = {
                                        'price': price,
                                        'yesterday_close': yc
                                    }
                            except ValueError:
                                pass
        except Exception as e:
            print(f'  [WARN] 批量查询失败: {e}')
        
        time.sleep(0.1)
    
    return prices

def get_rankings():
    """计算所有ETF的动量排名"""
    rankings = []
    tencent_prices = get_tencent_realtime_prices()
    
    for etf in ETF_POOL:
        try:
            if etf.startswith('5') or etf.startswith('1'):
                path = os.path.join(BASE_DIR, 'etf', f'{etf}.csv')
            else:
                path = os.path.join(BASE_DIR, 'etf_qixing', f'{etf}.csv')
            
            if not os.path.exists(path):
                continue
            
            df = pd.read_csv(path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
                df = df.dropna(subset=['date']).set_index('date')
            elif 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df = df.dropna(subset=['Date']).set_index('Date')
            
            df = df.sort_index()
            
            if len(df) < 50:
                continue
            
            prices = df['close'].values.astype(float)
            
            short = 0
            if len(prices) >= 26:
                recent = prices[-26:]
                y_short = np.log(recent)
                x_short = np.arange(len(y_short))
                weights_short = np.linspace(1, 2, len(y_short))
                try:
                    slope, _ = np.polyfit(x_short, y_short, 1, w=weights_short)
                    short = slope * 250
                except:
                    short = 0
            
            long = 0
            if len(prices) >= 61:
                recent = prices[-61:]
                y_long = np.log(recent)
                x_long = np.arange(len(y_long))
                weights_long = np.linspace(1, 2, len(y_long))
                try:
                    slope, _ = np.polyfit(x_long, y_long, 1, w=weights_long)
                    long = slope * 250
                except:
                    long = 0
            
            score = short * 2 + long * 1
            
            api_data = tencent_prices.get(etf, None)
            if api_data and api_data['yesterday_close'] > 0:
                realtime_price = api_data['price']
            else:
                realtime_price = float(prices[-1])
            
            rankings.append({
                'code': etf,
                'name': ETF_NAMES.get(etf, etf),
                'score': score,
                'price': realtime_price
            })
        
        except Exception as e:
            continue
    
    rankings.sort(key=lambda x: x['score'], reverse=True)
    return rankings

def load_current_positions():
    """加载当前持仓"""
    pos_file = os.path.join(WORKSPACE, 'current_positions.json')
    if os.path.exists(pos_file):
        with open(pos_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_current_positions(positions):
    """保存当前持仓"""
    pos_file = os.path.join(WORKSPACE, 'current_positions.json')
    with open(pos_file, 'w', encoding='utf-8') as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)

def load_trades():
    """加载交易记录"""
    trades_file = os.path.join(WORKSPACE, 'laplace_trades.json')
    if os.path.exists(trades_file):
        with open(trades_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get('trades', [])
    return []

def save_trades(trades):
    """保存交易记录"""
    trades_file = os.path.join(WORKSPACE, 'laplace_trades.json')
    with open(trades_file, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)

def execute_trade(trades, positions, rankings):
    """执行交易逻辑"""
    today = time.strftime('%Y-%m-%d')
    top1 = rankings[0] if rankings else None
    
    if not top1:
        print('  [WARN] 无排名数据，跳过交易')
        return trades, positions, None
    
    current_code = positions.get('code', None)
    current_name = positions.get('name', '')
    
    # 检查是否需要换仓
    if current_code and current_code != top1['code']:
        # 卖出当前持仓
        current_price = positions.get('buy_price', 0)
        sell_price = top1['price']  # 用新ETF价格近似（实际应该用当前持仓的实时价）
        
        # 尝试获取当前持仓的实时价
        tencent_prices = get_tencent_realtime_prices()
        if current_code in tencent_prices:
            sell_price = tencent_prices[current_code]['price']
        
        pnl_pct = ((sell_price - current_price) / current_price * 100) if current_price > 0 else 0
        
        sell_record = {
            'id': f'auto_{int(time.time())}',
            'date': today,
            'etf': current_code,
            'name': current_name,
            'action': 'SELL',
            'price': sell_price,
            'reason': 'Top1 replaced',
            'pnl_pct': round(pnl_pct, 2)
        }
        trades.append(sell_record)
        print(f'  [Trade] 卖出 {current_code} {current_name} @ {sell_price:.3f}, 盈亏 {pnl_pct:.2f}%')
        
        # 买入新ETF
        buy_record = {
            'id': f'auto_{int(time.time())+1}',
            'date': today,
            'etf': top1['code'],
            'name': top1['name'],
            'action': 'BUY',
            'price': top1['price'],
            'reason': 'Top1 momentum',
            'pnl_pct': None
        }
        trades.append(buy_record)
        
        positions = {
            'code': top1['code'],
            'name': top1['name'],
            'buy_price': top1['price'],
            'buy_date': today
        }
        print(f'  [Trade] 买入 {top1["code"]} {top1["name"]} @ {top1["price"]:.3f}')
        
        return trades, positions, f'换仓: {current_code} → {top1["code"]}'
    
    elif not current_code:
        # 第一次买入
        buy_record = {
            'id': f'auto_{int(time.time())}',
            'date': today,
            'etf': top1['code'],
            'name': top1['name'],
            'action': 'BUY',
            'price': top1['price'],
            'reason': 'Initial Top1',
            'pnl_pct': None
        }
        trades.append(buy_record)
        
        positions = {
            'code': top1['code'],
            'name': top1['name'],
            'buy_price': top1['price'],
            'buy_date': today
        }
        print(f'  [Trade] 首次买入 {top1["code"]} {top1["name"]} @ {top1["price"]:.3f}')
        
        return trades, positions, f'首次买入: {top1["code"]}'
    
    else:
        print(f'  [Info] 持仓 {current_code} 仍是 Top1，无需操作')
        return trades, positions, None

def send_email(action_msg, rankings):
    """发送交易通知邮件"""
    top1 = rankings[0] if rankings else {}
    
    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;padding:20px;background:#f8f9fa">
<h1>📊 拉普拉斯交易通知</h1>
<p style="color:#6b7280">{time.strftime('%Y-%m-%d %H:%M:%S')}</p>

{'<div style="background:white;padding:15px;border-radius:8px;margin:15px 0">' +
'<h2 style="color:#059669">✅ ' + action_msg + '</h2>' +
'<p>Top1: ' + top1.get('code', '') + ' ' + top1.get('name', '') + ' @ ' + format(top1.get('price', 0), '.3f') + '</p>' +
'</div>' if action_msg else '<p style="color:#6b7280">今日无交易操作</p>'}

<h2>当前排名 Top5</h2>
<table style="width:100%;border-collapse:collapse;background:white">
<tr style="background:#f8f9fa"><th style="padding:8px;text-align:left">排名</th><th style="padding:8px;text-align:left">ETF</th><th style="padding:8px;text-align:left">名称</th><th style="padding:8px;text-align:left">得分</th></tr>
'''
    
    for i, r in enumerate(rankings[:5]):
        html += f'<tr><td style="padding:8px">{i+1}</td><td style="padding:8px">{r["code"]}</td><td style="padding:8px">{r["name"]}</td><td style="padding:8px">{r["score"]:.2f}</td></tr>'
    
    html += '</table></body></html>'
    
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = f'[OpenClaw] 拉普拉斯交易通知 - {time.strftime("%m-%d %H:%M")}'
    msg['From'] = '848786642@qq.com'
    msg['To'] = '848786642@qq.com'
    
    try:
        with smtplib.SMTP('smtp.qq.com', 587) as server:
            server.starttls()
            server.login('848786642@qq.com', 'ljbtvacrctjobfed')
            server.send_message(msg)
        print('  [OK] 交易通知邮件已发送')
    except Exception as e:
        print(f'  [ERROR] 邮件发送失败: {e}')

if __name__ == '__main__':
    print(f'[{time.strftime("%H:%M:%S")}] 拉普拉斯实时交易启动...')
    
    # 1. 获取排名
    rankings = get_rankings()
    print(f'  [OK] 排名计算完成，共 {len(rankings)} 只ETF')
    
    # 2. 加载当前状态
    positions = load_current_positions()
    trades = load_trades()
    print(f'  [OK] 当前持仓: {positions.get("code", "无")}')
    print(f'  [OK] 历史交易: {len(trades)} 条')
    
    # 3. 执行交易
    trades, positions, action_msg = execute_trade(trades, positions, rankings)
    
    # 4. 保存状态
    save_current_positions(positions)
    save_trades(trades)
    print(f'  [OK] 状态已保存')
    
    # 5. 发送通知
    send_email(action_msg, rankings)
    
    print(f'[{time.strftime("%H:%M:%S")}] 交易执行完成！')
