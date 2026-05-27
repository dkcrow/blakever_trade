"""
拉普拉斯策略公共模块
包含：获取实时价格、计算排名、ETF名称映射
"""
import os
import json
import urllib.request
import numpy as np
import pandas as pd

# ETF 池定义
ETF_POOL = [
    "588080", "159915", "159922", "510300", "510500", "512100", "512690",
    "515790", "159611", "159766", "159996", "512660", "515030", "159997",
    "159967", "513100", "159509", "513290", "513500", "159529", "513400",
    "513520", "513030", "513080", "513310", "513730", "159792", "513130",
    "513050", "159920", "513690", "510050", "510210", "512660", "159996",
    "515030", "159997", "159967"
]

ETF_NAMES = {
    "588080": "科创50ETF易方达",
    "159915": "创业板ETF易方达",
    "159922": "中证500ETF嘉实",
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "512100": "中证1000ETF",
    "512690": "酒ETF鹏华",
    "515790": "光伏ETF华泰柏瑞",
    "159611": "电力ETF华夏",
    "159766": "旅游ETF富国",
    "159996": "家电ETF国泰",
    "512660": "军工ETF国泰",
    "515030": "新能源车ETF华夏",
    "159997": "电子ETF天弘",
    "159967": "创成长ETF华夏",
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
    "510050": "上证50ETF",
    "510210": "上证180ETF",
    "511220": "城投债ETF",
    "511880": "天天理财ETF",
    "159981": "能源化工ETF",
    "161226": "白银LOF国投瑞银"
}

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'


def get_tencent_realtime_prices():
    """获取腾讯API实时价格，返回 {code: {'price': x, 'yesterday_close': y}}"""
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
                                price = float(parts[3])  # 当前价
                                yc = float(parts[4])    # 昨收价（正确字段！）
                                if yc > 0:
                                    prices[code] = {
                                        'price': price,
                                        'yesterday_close': yc
                                    }
                            except ValueError:
                                pass
        except Exception as e:
            print(f'  [WARN] API失败: {e}')
    
    return prices


def get_rankings(tencent_prices):
    """计算ETF排名，返回排名列表"""
    rankings = []
    
    for etf in ETF_POOL:
        if etf in ('511220', '511880'):
            continue
        
        code_int = int(etf)
        if code_int >= 500000:
            path = os.path.join(BASE_DIR, 'etf', f'{etf}.csv')
        else:
            path = os.path.join(BASE_DIR, 'etf_qixing', f'{etf}.csv')
        
        if not os.path.exists(path):
            continue
        
        try:
            df = pd.read_csv(path)
            # 兼容多种列名
            date_col = None
            close_col = None
            for col in df.columns:
                if col.lower() in ['date', 'date']:
                    date_col = col
                if col.lower() in ['close', 'close']:
                    close_col = col
            
            if date_col and close_col:
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                df = df.dropna(subset=[date_col]).set_index(date_col)
                prices = df[close_col].values.astype(float)
            else:
                continue
            
            # 短期动量（26日）
            short = 0
            if len(prices) >= 26:
                recent = prices[-26:]
                y_short = np.log(recent)
                x_short = np.arange(len(y_short))
                weights_short = np.linspace(1, 2, len(y_short))
                try:
                    slope_short = np.polyfit(x_short, y_short, 1)[0]
                    short = slope_short * 252 * 100
                except:
                    short = 0
            
            # 长期动量（252日）
            long = 0
            if len(prices) >= 252:
                recent = prices[-252:]
                y_long = np.log(recent)
                x_long = np.arange(len(y_long))
                weights_long = np.linspace(0.5, 2, len(y_long))
                try:
                    slope_long = np.polyfit(x_long, y_long, 1)[0]
                    long = slope_long * 252 * 100
                except:
                    long = 0
            
            # 综合得分
            score = short + long * 0.5
            
            # 获取实时价格
            price = None
            yesterday_close = None
            if etf in tencent_prices:
                price = tencent_prices[etf]['price']
                yesterday_close = tencent_prices[etf]['yesterday_close']
            else:
                # 降级用CSV最后收盘价
                price = float(prices[-1])
                yesterday_close = float(prices[-2]) if len(prices) >= 2 else price
            
            rankings.append({
                'code': etf,
                'name': ETF_NAMES.get(etf, etf),
                'score': score,
                'short': short,
                'long': long,
                'price': price,
                'yesterday_close': yesterday_close,
                'realtime_price': price
            })
        except Exception as e:
            print(f'  [WARN] {etf} 失败: {e}')
            continue
    
    rankings.sort(key=lambda x: x['score'], reverse=True)
    return rankings


def get_rank_change(rankings, history_file):
    """计算排名变动，返回 {code: change}"""
    # 读取历史
    yesterday_ranks = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if history and len(history) > 0:
                    yesterday_ranks = {item['code']: item['rank'] for item in history[-1].get('rankings', [])}
        except:
            pass
    
    # 计算变动
    rank_changes = {}
    for i, r in enumerate(rankings):
        code = r['code']
        current_rank = i + 1
        if code in yesterday_ranks:
            rank_changes[code] = yesterday_ranks[code] - current_rank
        else:
            rank_changes[code] = 0
    
    # 保存新排名
    new_record = {
        'date': pd.Timestamp.now().strftime('%Y-%m-%d'),
        'rankings': [{'code': r['code'], 'rank': i+1} for i, r in enumerate(rankings)]
    }
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    history = data
                elif isinstance(data, dict) and 'rankings' in data:
                    history = [data]  # 兼容旧格式
        except Exception as e:
            print(f'  [WARN] 读取历史失败: {e}')
            history = []
    history.append(new_record)
    if len(history) > 30:
        history = history[-30:]
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    return rank_changes


def calculate_pct_change(price, yesterday_close):
    """计算涨跌幅百分比"""
    if yesterday_close and yesterday_close > 0:
        return ((price - yesterday_close) / yesterday_close) * 100
    return 0.0


def get_etf_name(code):
    """根据代码返回ETF名称"""
    return ETF_NAMES.get(code, code)
