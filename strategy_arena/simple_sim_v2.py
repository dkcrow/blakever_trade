"""
简化版历史交易模拟
"""
import json
import pandas as pd
import os
from datetime import datetime

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

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'

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

def load_data(etf_code):
    """加载ETF数据"""
    try:
        file_path = os.path.join(BASE_DIR, f"{etf_code}.csv")
        if not os.path.exists(file_path):
            return None
        
        df = pd.read_csv(file_path)
        
        # 兼容大小写列名
        col_map = {}
        for col in df.columns:
            col_map[col.lower()] = col
        
        if 'date' in col_map:
            df = df.rename(columns={col_map['date']: 'date'})
        if 'close' in col_map:
            df = df.rename(columns={col_map['close']: 'close'})
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        df = df[df['date'] >= '2025-01-01']
        
        if len(df) < 10:
            return None
        
        return df
    except Exception as e:
        return None

def get_price(df, date_str):
    """获取指定日期价格"""
    try:
        target = pd.to_datetime(date_str)
        row = df[df['date'] == target]
        if len(row) > 0:
            return float(row.iloc[0]['close'])
    except:
        pass
    return None

# 主程序
print("=" * 60)
print("简化版历史交易模拟 (2025-01-01 to 2026-05-23)")
print("=" * 60)

# 加载所有ETF数据
etf_data = {}
all_dates = set()

for etf in ETF_POOL:
    df = load_data(etf)
    if df is not None:
        etf_data[etf] = df
        for date in df['date'].dt.strftime('%Y-%m-%d'):
            all_dates.add(date)

if not all_dates:
    print("No data found!")
    exit(1)

dates = sorted(list(all_dates))
print(f"Total trading days: {len(dates)}")

# 模拟交易
trades = []
position = None
trade_id = 0

for date in dates:
    # 计算所有ETF短期动量（10日）
    scores = []
    for etf in ETF_POOL:
        if etf not in etf_data:
            continue
        
        df = etf_data[etf]
        df_d = df[df['date'].dt.strftime('%Y-%m-%d') <= date]
        
        if len(df_d) < 10:
            continue
        
        try:
            price_now = float(df_d.iloc[-1]['close'])
            price_10d = float(df_d.iloc[-10]['close'])
            momentum = (price_now / price_10d - 1)
            scores.append({
                'etf': etf,
                'name': ETF_NAMES.get(etf, etf),
                'score': momentum
            })
        except:
            pass
    
    if not scores:
        continue
    
    # 按动量排序
    scores.sort(key=lambda x: x['score'], reverse=True)
    top1 = scores[0]
    
    # 检查是否需要交易
    if position is None:
        # 买入
        price = get_price(etf_data[top1['etf']], date)
        if price:
            trade_id += 1
            position = {
                'etf': top1['etf'],
                'name': top1['name'],
                'price': price,
                'date': date
            }
            trades.append({
                'id': f"sim_{trade_id:03d}",
                'date': date,
                'etf': top1['etf'],
                'name': top1['name'],
                'action': 'BUY',
                'price': price,
                'reason': 'Top1 momentum',
                'pnl_pct': None
            })
            print(f"  {date} BUY {top1['name']} @ {price:.3f}")
    
    elif position['etf'] != top1['etf']:
        # 卖出旧持仓
        sell_price = get_price(etf_data[position['etf']], date)
        if sell_price:
            pnl = (sell_price - position['price']) / position['price'] * 100
            trade_id += 1
            trades.append({
                'id': f"sim_{trade_id:03d}",
                'date': date,
                'etf': position['etf'],
                'name': position['name'],
                'action': 'SELL',
                'price': sell_price,
                'reason': 'Top1 replaced',
                'pnl_pct': round(pnl, 1)
            })
            print(f"  {date} SELL {position['name']} @ {sell_price:.3f} | PnL={pnl:.1f}%")
        
        # 买入新持仓
        buy_price = get_price(etf_data[top1['etf']], date)
        if buy_price:
            trade_id += 1
            position = {
                'etf': top1['etf'],
                'name': top1['name'],
                'price': buy_price,
                'date': date
            }
            trades.append({
                'id': f"sim_{trade_id:03d}",
                'date': date,
                'etf': top1['etf'],
                'name': top1['name'],
                'action': 'BUY',
                'price': buy_price,
                'reason': 'Top1 momentum',
                'pnl_pct': None
            })
            print(f"  {date} BUY {top1['name']} @ {buy_price:.3f}")

print("\n" + "=" * 60)
print(f"Simulation completed! Total {len(trades)} trades")
print("=" * 60)

# 保存为数组格式
with open('laplace_trades.json', 'w', encoding='utf-8') as f:
    json.dump(trades, f, ensure_ascii=False, indent=2)

print(f"Trades saved to laplace_trades.json")
print(f"Total trades: {len(trades)}")

# 显示最近20条
print("\nLast 20 trades:")
for i, t in enumerate(trades[-20:], 1):
    pnl_str = f"{t['pnl_pct']}%" if t['pnl_pct'] is not None else '-'
    print(f"  {i}. {t['date']} | {t['name']} | {t['action']} @ {t['price']:.3f} | PnL={pnl_str} | {t['reason']}")
