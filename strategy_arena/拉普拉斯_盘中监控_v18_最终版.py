"""
拉普拉斯盘中监控 - v18 最终版
包含：
1. 腾讯API实时价格（正确前缀）
2. 涨跌幅计算 (price - yc) / yc * 100
3. 显示所有38只ETF
4. 交易记录（读取 laplace_trades.json，修复null）
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

ETF_POOL = [
    '518880', '159980', '159985', '501018', '161226', '159981',
    '513100', '159509', '513290', '513500', '159529', '513400',
    '513520', '513030', '513080', '513310', '513730', '159792',
    '513130', '513050', '159920', '513690', '510300', '510500',
    '510050', '510210', '512100', '159915', '159922', '588080',
    '512690', '515790', '159611', '159766', '159996', '512660',
    '515030', '515790', '159997'
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

RANK_HISTORY_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\laplace_rankings_history.json'

def get_tencent_realtime_prices():
    """获取腾讯API实时价格"""
    prices = {}
    batch_size = 10
    
    for i in range(0, len(ETF_POOL), batch_size):
        batch = ETF_POOL[i:i+batch_size]
        query_parts = []
        for code in batch:
            # 深圳: 0,1,2,3 开头；上海: 5,6,9 开头
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
                                yc = float(parts[4])  # 今开价作为昨收价
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
    
    print(f'  [OK] 腾讯API获取 {len(prices)} 只ETF实时价格')
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
                yesterday_close = api_data['yesterday_close']
            else:
                realtime_price = float(prices[-1])
                yesterday_close = float(prices[-2]) if len(prices) >= 2 else realtime_price
            
            rankings.append({
                'code': etf,
                'name': ETF_NAMES.get(etf, etf),
                'score': score,
                'short': short,
                'long': long,
                'realtime_price': realtime_price,
                'yesterday_close': yesterday_close
            })
        
        except Exception as e:
            print(f'  [ERROR] {etf}: {e}')
            continue
    
    rankings.sort(key=lambda x: x['score'], reverse=True)
    return rankings

def load_rank_history():
    """加载历史排名"""
    if os.path.exists(RANK_HISTORY_FILE):
        try:
            with open(RANK_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_rank_history(history):
    """保存历史排名"""
    with open(RANK_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False)

def get_rank_change(rankings):
    """计算排名变动"""
    history = load_rank_history()
    today = time.strftime('%Y-%m-%d')
    
    today_ranks = {r['code']: i for i, r in enumerate(rankings)}
    
    changes = {}
    for code, new_pos in today_ranks.items():
        if code in history.get('yesterday', {}):
            old_pos = history['yesterday'][code]
            changes[code] = old_pos - new_pos
    
    # 更新历史
    history[today] = today_ranks
    history['yesterday'] = today_ranks
    
    # 只保留最近30天
    keys_to_del = [k for k in history.keys() if k not in [today, 'yesterday'] and k < '2026-04-01']
    for k in keys_to_del[:10]:
        del history[k]
    
    save_rank_history(history)
    
    return changes

def generate_html(rankings, rank_changes):
    """生成HTML邮件"""
    rows_html = ""
    trades_html = ""
    
    # 读取交易记录
    trades_file = r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json'
    try:
        with open(trades_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 兼容格式
        if isinstance(data, list):
            trades = data
        elif isinstance(data, dict):
            trades = data.get('trades', [])
        else:
            trades = []
        
        # 取最近20条，反转顺序（最新的在前面）
        recent = trades[-20:] if len(trades) >= 20 else trades
        recent = list(reversed(recent))
        
        for t in recent:
            act = t.get('action', '')
            etf = t.get('etf', t.get('code', ''))
            price = t.get('price', 0)
            reason = t.get('reason', '')
            pnl = t.get('pnl_pct', t.get('pnl', 0))
            if pnl is None:
                pnl = 0
            
            ac = '#dc2626' if act == 'SELL' else '#059669'
            pc = '#059669' if pnl > 0 else '#dc2626' if pnl < 0 else '#6b7280'
            ps = '+' if pnl > 0 else ''
            
            trades_html += '<tr>'
            trades_html += '<td style="padding:4px 6px;color:#6b7280;font-size:11px">' + str(t.get('date', '')) + '</td>'
            trades_html += '<td style="padding:4px 6px;font-weight:600;color:#111827">' + etf + ' ' + ETF_NAMES.get(etf, '') + '</td>'
            trades_html += '<td style="padding:4px 6px;color:' + ac + '">' + act + '</td>'
            trades_html += '<td style="padding:4px 6px;color:#111827">' + format(price, '.3f') + '</td>'
            trades_html += '<td style="padding:4px 6px;color:#6b7280;font-size:11px">' + reason + '</td>'
            trades_html += '<td style="padding:4px 6px;color:' + pc + '">' + ps + format(pnl, '.2f') + '%</td>'
            trades_html += '</tr>'
    except Exception as e:
        print(f'  [WARN] 交易记录: {e}')
    
    for i, r in enumerate(rankings):
        code = r['code']
        name = r['name']
        score = r['score']
        short = r['short']
        long = r['long']
        price = r['realtime_price']
        yesterday_close = r['yesterday_close']
        
        diff = rank_changes.get(code, 0)
        if diff > 0:
            rank_change_html = '<span style="color:#059669;font-size:11px">↑+' + str(diff) + '</span>'
        elif diff < 0:
            rank_change_html = '<span style="color:#dc2626;font-size:11px">↓' + str(diff) + '</span>'
        else:
            rank_change_html = '<span style="color:#6b7280;font-size:11px">—</span>'
        
        if yesterday_close > 0:
            pct_change = ((price - yesterday_close) / yesterday_close) * 100
            pct_color = '#059669' if pct_change >= 0 else '#dc2626'
            pct_sign = '+' if pct_change >= 0 else ''
            pct_html = '<span style="color:' + pct_color + ';font-size:11px">' + pct_sign + format(pct_change, '.2f') + '%</span>'
        else:
            pct_html = '<span style="color:#6b7280;font-size:11px">0.00%</span>'
        
        medal = ''
        if i == 0:
            medal = '🥇 '
        elif i == 1:
            medal = '🥈 '
        elif i == 2:
            medal = '🥉 '
        
        rows_html += '<tr>'
        rows_html += '<td>' + medal + str(i+1) + '</td>'
        rows_html += '<td>' + name + '</td>'
        rows_html += '<td>' + code + '</td>'
        rows_html += '<td>' + format(score, '.2f') + '</td>'
        rows_html += '<td>' + format(short, '.2f') + '</td>'
        rows_html += '<td>' + format(long, '.2f') + '</td>'
        rows_html += '<td style="color:#111827;font-weight:600">' + format(price, '.3f') + '</td>'
        rows_html += '<td>' + pct_html + '</td>'
        rows_html += '<td>' + rank_change_html + '</td>'
        rows_html += '</tr>'
    
    html = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin:0; padding:20px; background:#f8f9fa; }
h1 { font-size:16px; color:#111827; margin-bottom:5px; }
h2 { font-size:14px; color:#111827; margin:20px 0 10px 0; }
table { width:100%; border-collapse:collapse; background:white; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.1); }
th { background:#f8f9fa; padding:8px 6px; font-size:11px; color:#6b7280; text-align:left; }
td { padding:8px 6px; font-size:11px; border-bottom:1px solid #e5e7eb; }
tr:hover { background:#f9fafb; }
.footer { margin-top:15px; font-size:11px; color:#6b7280; }
</style>
</head>
<body>
<h1>📊 拉普拉斯盘中监控（v18）</h1>
<p style="font-size:11px;color:#6b7280;margin:0 0 10px 0">数据来源：腾讯API | 更新时间：''' + time.strftime('%Y-%m-%d %H:%M:%S') + '''</p>
<table>
<tr><th>排名</th><th>名称</th><th>代码</th><th>综合分</th><th>短期</th><th>长期</th><th>实时价</th><th>涨跌幅</th><th>变动</th></tr>
''' + rows_html + '''
</table>

<h2>📋 最近20次交易记录</h2>
<table>
<tr><th>时间</th><th>ETF</th><th>操作</th><th>价格</th><th>原因</th><th>盈亏</th></tr>
''' + trades_html + '''
</table>

<p class="footer">⚠️ 本邮件为自动化监控，不构成投资建议。</p>
</body>
</html>'''
    
    return html

def send_email(html):
    """发送邮件"""
    with open('last_email.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print('  [OK] HTML 已保存到 last_email.html')
    
    msg = MIMEText(html, 'html', 'utf-8')
    msg['Subject'] = f'[OpenClaw] 拉普拉斯监控v18 - {time.strftime("%m-%d %H:%M")}'
    msg['From'] = '848786642@qq.com'
    msg['To'] = '848786642@qq.com'
    
    try:
        with smtplib.SMTP('smtp.qq.com', 587) as server:
            server.starttls()
            server.login('848786642@qq.com', 'ljbtvacrctjobfed')
            server.send_message(msg)
        print('  [OK] 邮件已发送')
        return True
    except Exception as e:
        print(f'  [ERROR] 邮件发送失败: {e}')
        return False

if __name__ == '__main__':
    print(f'[{time.strftime("%H:%M:%S")}] 拉普拉斯盘中监控启动（v18）...')
    
    rankings = get_rankings()
    print(f'  [OK] 计算完成，共 {len(rankings)} 只ETF')
    
    rank_changes = get_rank_change(rankings)
    print(f'  [OK] 排名变动计算完成')
    
    html = generate_html(rankings, rank_changes)
    print(f'  [OK] HTML生成完成，长度 {len(html)} 字节')
    
    send_email(html)
    
    print(f'[{time.strftime("%H:%M:%S")}] 任务完成！')
