"""
从历史数据模拟交易记录（2025-01-01 至 2026-05-23）
使用本地 ETF 数据，生成真实交易记录
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os

# 配置
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'
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

def load_etf_data(etf_code, start_date='2025-01-01', end_date='2026-05-23'):
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
        
        # 标准化列名
        if 'date' in col_map:
            df = df.rename(columns={col_map['date']: 'date'})
        if 'close' in col_map:
            df = df.rename(columns={col_map['close']: 'close'})
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        # 过滤日期范围
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        df = df[(df['date'] >= start) & (df['date'] <= end)]
        
        if len(df) < 20:
            return None
        
        return df
    except Exception as e:
        return None

def calc_scores(df, etf_code):
    """计算ETF得分（简化版）"""
    try:
        if len(df) < 20:
            return None
        
        # 短期动量（10日）
        short_momentum = (df.iloc[-1]['close'] / df.iloc[-10]['close'] - 1) if len(df) >= 10 else 0
        
        # 长期动量（20日）
        long_momentum = (df.iloc[-1]['close'] / df.iloc[-20]['close'] - 1) if len(df) >= 20 else 0
        
        # 综合得分
        composite = short_momentum * 0.6 + long_momentum * 0.4
        
        return {
            'etf': etf_code,
            'name': ETF_NAMES.get(etf_code, etf_code),
            'short': short_momentum,
            'long': long_momentum,
            'composite': composite
        }
    except:
        return None

def simulate_trades():
    """模拟交易"""
    trades = []
    position = None  # 当前持仓 {'etf': ..., 'price': ..., 'date': ...}
    
    # 获取所有交易日
    all_dates = set()
    etf_data = {}
    
    for etf in ETF_POOL:
        df = load_etf_data(etf)
        if df is not None:
            etf_data[etf] = df
            for date in df['date'].dt.strftime('%Y-%m-%d'):
                all_dates.add(date)
    
    if not all_dates:
        print("❌ 没有数据")
        return []
    
    # 按日期排序
    dates = sorted(list(all_dates))
    print(f"✅ 共 {len(dates)} 个交易日")
    
    trade_id = 0
    
    for date in dates:
        # 计算所有ETF得分
        scores = []
        for etf in ETF_POOL:
            if etf in etf_data and date in etf_data[etf]['date'].dt.strftime('%Y-%m-%d').values:
                df = etf_data[etf]
                df_date = df[df['date'].dt.strftime('%Y-%m-%d') <= date]
                if len(df_date) >= 20:
                    score = calc_scores(df_date, etf)
                    if score:
                        scores.append(score)
        
        if not scores:
            continue
        
        # 按综合分排序
        scores.sort(key=lambda x: x['composite'], reverse=True)
        
        # 当前Top1
        top1 = scores[0]
        
        # 检查是否需要换仓
        if position is None:
            # 买入
            trade_id += 1
            position = {
                'etf': top1['etf'],
                'name': top1['name'],
                'price': get_price(etf_data[top1['etf']], date),
                'date': date
            }
            trades.append({
                'id': f"hist_{trade_id:03d}",
                'date': date,
                'etf': top1['etf'],
                'name': top1['name'],
                'action': 'BUY',
                'price': position['price'],
                'reason': 'Top1 ranking',
                'pnl_pct': None
            })
            print(f"  {date} BUY  {top1['name']} @ {position['price']:.3f}")
        
        elif position['etf'] != top1['etf']:
            # 卖出旧持仓
            sell_price = get_price(etf_data[position['etf']], date)
            if sell_price:
                pnl = (sell_price - position['price']) / position['price'] * 100
                trade_id += 1
                trades.append({
                    'id': f"hist_{trade_id:03d}",
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
                    'id': f"hist_{trade_id:03d}",
                    'date': date,
                    'etf': top1['etf'],
                    'name': top1['name'],
                    'action': 'BUY',
                    'price': buy_price,
                    'reason': 'Top1 ranking',
                    'pnl_pct': None
                })
                print(f"  {date} BUY  {top1['name']} @ {buy_price:.3f}")
    
    # 清仓（最后一天）
    if position:
        last_date = dates[-1]
        sell_price = get_price(etf_data[position['etf']], last_date)
        if sell_price:
            pnl = (sell_price - position['price']) / position['price'] * 100
            trade_id += 1
            trades.append({
                'id': f"hist_{trade_id:03d}",
                'date': last_date,
                'etf': position['etf'],
                'name': position['name'],
                'action': 'SELL',
                'price': sell_price,
                'reason': 'Simulation end',
                'pnl_pct': round(pnl, 1)
            })
            print(f"  {last_date} SELL {position['name']} @ {sell_price:.3f} | PnL={pnl:.1f}%")
    
    return trades

def get_price(df, date_str):
    """获取指定日期的价格"""
    try:
        target = pd.to_datetime(date_str)
        df = df[df['date'] == target]
        if len(df) > 0:
            return round(float(df.iloc[0]['close']), 3)
    except:
        pass
    return None

# 主程序
if __name__ == '__main__':
    print("=" * 60)
    print("历史交易模拟（2025-01-01 至 2026-05-23）")
    print("=" * 60)
    
    trades = simulate_trades()
    
    print("\n" + "=" * 60)
    print(f"模拟完成！共 {len(trades)} 笔交易")
    print("=" * 60)
    
    # 保存为数组格式（兼容脚本）
    with open('laplace_trades.json', 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 交易记录已保存到 laplace_trades.json")
    print(f"✅ 共 {len(trades)} 笔交易")
    
    # 显示最近20条
    print("\n最近20条交易记录:")
    for i, t in enumerate(trades[-20:], 1):
        pnl_str = f"{t['pnl_pct']}%" if t['pnl_pct'] else '-'
        print(f"  {i}. {t['date']} | {t['name']} | {t['action']} @ {t['price']:.3f} | PnL={pnl_str} | {t['reason']}")
