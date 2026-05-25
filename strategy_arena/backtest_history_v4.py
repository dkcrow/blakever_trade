#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯策略历史回测 v4 - 修正止损逻辑
- 用最低价判断止损（-8%）
- 按止损线卖出（entry × 0.92）
- 修正所有拼写错误
"""

import pandas as pd
import numpy as np
import math
import warnings
import json
import os
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'
TRADE_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\laplace_trades.json'

ETF_NAMES = {
    '518880': '黄金ETF华安', '159980': '有色ETF大成', '159985': '豆粕ETF华夏', '501018': '南方原油LOF', '161226': '白银LOF国投瑞银',
    '159981': '能源化工ETF建信', '513100': '纳指ETF国泰', '159509': '纳指科技ETF景顺', '513290': '纳指生物科技ETF汇添富', '513500': '标普500ETF博时',
    '159529': '标普消费ETF景顺', '513400': '道琼斯ETF鹏华', '513520': '日经ETF华夏', '513030': '德国ETF华安', '513080': '法国ETF华安',
    '513310': '中韩半导体ETF华泰柏瑞', '513730': '东南亚科技ETF华泰柏瑞', '159792': '港股通互联网ETF富国', '513130': '恒生科技ETF华泰柏瑞',
    '513050': '中概互联网ETF易方达', '159920': '恒生ETF华夏', '513690': '港股红利ETF博时', '510300': '沪深300ETF华泰柏瑞',
    '510500': '中证500ETF南方', '510050': '上证50ETF华夏', '510210': '上证指数ETF富国', '159915': '创业板ETF易方达',
    '588080': '科创50ETF易方达', '512100': '中证1000ETF南方', '563360': 'A500ETF华泰柏瑞', '563300': '中证2000ETF华泰柏瑞',
    '512890': '红利低波ETF华泰柏瑞', '159967': '创业板成长ETF华夏', '512040': '价值100ETF富国', '159201': '自由现金流ETF华夏',
    '511380': '可转债ETF博时', '511010': '国债ETF国泰', '511220': '城投债ETF海富通'
}

def load_etf_data(etf_code):
    """加载ETF数据"""
    for subdir in ['etf', 'etf_qixing']:
        csv_path = os.path.join(BASE_DIR, subdir, f"{etf_code}.csv")
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                return df
            except:
                continue
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

def get_top_etf_as_of(date):
    """获取指定日期的Top1 ETF"""
    rankings = []
    
    for etf in list(ETF_NAMES.keys())[:15]:  # 只看15只，加快速度
        df = load_etf_data(etf)
        if df is None:
            continue
        
        # 只用到指定日期的数据
        df_until = df[df.index <= date]
        if len(df_until) < 50:
            continue
        
        closes = df_until['close'].values
        score_short = calc_momentum(closes, min(25, len(closes)-1))
        long_period = min(250, len(closes)-1)
        score_long = calc_momentum(closes, long_period) if long_period >= 25 else None
        
        if score_short is None:
            continue
        
        combined = score_short * 1.0
        if score_long is not None:
            combined += score_long * 0.5
        
        rankings.append({
            'etf': etf,
            'name': ETF_NAMES.get(etf, etf),
            'combined': combined,
            'price': closes[-1]
        })
    
    rankings.sort(key=lambda x: x['combined'], reverse=True)
    return rankings[0] if rankings else None

# ==================== 主逻辑 ====================

print("="*60)
print("拉普拉斯策略历史回测（2025-01-01 至 2026-05-24）")
print("="*60)

# 生成所有交易日
all_dates = set()
for etf in list(ETF_NAMES.keys())[:15]:
    df = load_etf_data(etf)
    if df is not None:
        df = df[(df.index >= '2025-01-01') & (df.index <= '2026-05-24')]
        all_dates.update(df.index)

all_dates = sorted(list(all_dates))
print(f"\n交易日总数: {len(all_dates)}")

# 初始化
trades = []
positions = {}  # {etf: {'entry_price', 'entry_date', 'max_price'}}
trade_id = 0
last_top_etf = None

for i, current_date in enumerate(all_dates):
    # 每5天运行一次，跳过周末
    if i % 5 != 0:
        continue
    if current_date.weekday() >= 5:
        continue
    
    top = get_top_etf_as_of(current_date)
    if top is None:
        continue
    
    current_etf = list(positions.keys())[0] if positions else None
    
    if current_etf:
        # 获取当日数据
        df_current = load_etf_data(current_etf)
        if df_current is not None:
            daily_data = df_current[df_current.index.date == current_date.date()]
            if len(daily_data) > 0:
                current_price = daily_data['close'].iloc[0]
                low_price = daily_data['low'].iloc[0]
            else:
                current_price = top['price']
                low_price = top['price']
        else:
            current_price = top['price']
            low_price = top['price']
        
        entry_price = positions[current_etf]['entry_price']
        max_price = positions[current_etf]['max_price']
        pnl_pct = (current_price - entry_price) / entry_price * 100
        
        # 更新最高价
        if current_price > max_price:
            positions[current_etf]['max_price'] = current_price
        
        # 检查止损
        stop_loss_reason = None
        stop_price = entry_price * 0.92  # 止损线
        
        # 硬止损 -8%（用最低价判断，按止损线卖出）
        if low_price <= stop_price:
            stop_loss_reason = '硬止损（-8%）'
            sell_price = stop_price
            pnl_at_sell = (sell_price - entry_price) / entry_price * 100
        # 盈利保护：盈利>5%且回撤>5%
        elif pnl_pct > 5 and current_price < max_price * 0.95:
            stop_loss_reason = '盈利保护（回撤>5%）'
            sell_price = current_price
            pnl_at_sell = pnl_pct
        
        # 检查是否换仓
        need_switch = (current_etf != top['etf'])
        
        # 优先止损，其次换仓
        if stop_loss_reason:
            # 止损卖出（用止损线价格）
            trade_id += 1
            trades.append({
                "id": trade_id,
                "etf": current_etf,
                "name": positions[current_etf]['name'],
                "action": "卖出",
                "date": current_date.strftime('%Y-%m-%d'),
                "price": round(sell_price, 3),
                "reason": stop_loss_reason,
                "pnl_pct": round(pnl_at_sell, 1)
            })
            print(f"{current_date.strftime('%Y-%m-%d')}: 卖出 {current_etf} {positions[current_etf]['name']} @ {sell_price:.3f} (止损: {pnl_at_sell:.1f}%) - {stop_loss_reason}")
            positions.pop(current_etf)
            
            # 止损后冷却期：当天不买入
            print(f"{current_date.strftime('%Y-%m-%d')}: 止损后冷却，不买入")
            last_top_etf = None
            
        elif need_switch:
            # 换仓卖出
            trade_id += 1
            trades.append({
                "id": trade_id,
                "etf": current_etf,
                "name": positions[current_etf]['name'],
                "action": "卖出",
                "date": current_date.strftime('%Y-%m-%d'),
                "price": round(current_price, 3),
                "reason": f"动量不足换仓（新Top1: {top['etf']}）",
                "pnl_pct": round(pnl_pct, 1)
            })
            print(f"{current_date.strftime('%Y-%m-%d')}: 卖出 {current_etf} {positions[current_etf]['name']} @ {current_price:.3f} (换仓: {pnl_pct:.1f}%) - 新Top1: {top['etf']}")
            positions.pop(current_etf)
            
            # 买入新的
            positions[top['etf']] = {
                'name': top['name'],
                'entry_price': top['price'],
                'entry_date': current_date.strftime('%Y-%m-%d'),
                'max_price': top['price']
            }
            trade_id += 1
            trades.append({
                "id": trade_id,
                "etf": top['etf'],
                "name": top['name'],
                "action": "买入",
                "date": current_date.strftime('%Y-%m-%d'),
                "price": round(top['price'], 3),
                "reason": f"动量排名第1（综合得分{top['combined']:.4f}）",
                "pnl_pct": None
            })
            print(f"{current_date.strftime('%Y-%m-%d')}: 买入 {top['etf']} {top['name']} @ {top['price']:.3f} (得分: {top['combined']:.4f})")
            last_top_etf = top['etf']
    else:
        # 无持仓，买入Top1
        positions[top['etf']] = {
            'name': top['name'],
            'entry_price': top['price'],
            'entry_date': current_date.strftime('%Y-%m-%d'),
            'max_price': top['price']
        }
        trade_id += 1
        trades.append({
            "id": trade_id,
            "etf": top['etf'],
            "name": top['name'],
            "action": "买入",
            "date": current_date.strftime('%Y-%m-%d'),
            "price": round(top['price'], 3),
            "reason": f"动量排名第1（综合得分{top['combined']:.4f}）",
            "pnl_pct": None
        })
        print(f"{current_date.strftime('%Y-%m-%d')}: 买入 {top['etf']} {top['name']} @ {top['price']:.3f} (得分: {top['combined']:.4f})")

# 保存交易记录
with open(TRADE_FILE, 'w', encoding='utf-8') as f:
    json.dump({"trades": trades, "positions": {}}, f, ensure_ascii=False, indent=2)

print("\n" + "="*60)
print("回测完成")
print("="*60)
print(f"总交易笔数: {len(trades)}")
print(f"当前持仓: {len(positions)} 只")
print(f"交易记录已保存到: {TRADE_FILE}")
print("="*60)
