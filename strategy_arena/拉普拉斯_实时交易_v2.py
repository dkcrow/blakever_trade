"""
拉普拉斯实时交易 v2（使用 laplace_common 公共模块）
"""
import sys
import os
import json
import time
import laplace_common as lc

TRADES_FILE = r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json'
POSITIONS_FILE = r'C:\Users\blakehao\.qclaw\workspace\current_positions.json'


def load_positions():
    """读取当前持仓"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return None


def save_positions(positions):
    """保存持仓"""
    with open(POSITIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def load_trades():
    """读取交易记录"""
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'trades' in data:
                    return data['trades']
        except:
            pass
    return []


def save_trades(trades):
    """保存交易记录"""
    with open(TRADES_FILE, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


def execute_trade(etf_code, action, price, reason):
    """执行交易，更新持仓和记录"""
    now = time.strftime('%Y-%m-%d')
    name = lc.get_etf_name(etf_code)
    pnl_pct = None
    
    if action == 'SELL':
        # 卖出：计算盈亏
        positions = load_positions()
        if positions and positions.get('code') == etf_code:
            buy_price = positions.get('buy_price', price)
            pnl_pct = ((price - buy_price) / buy_price) * 100
            # 清空持仓
            save_positions({})
    
    # 记录交易
    trade = {
        'id': f"auto_{int(time.time())}",
        'date': now,
        'etf': etf_code,
        'name': name,
        'action': action,
        'price': price,
        'reason': reason,
        'pnl_pct': round(pnl_pct, 2) if pnl_pct is not None else None
    }
    
    trades = load_trades()
    trades.append(trade)
    save_trades(trades)
    
    # 如果是买入，更新持仓
    if action == 'BUY':
        new_positions = {
            'code': etf_code,
            'name': name,
            'buy_price': price,
            'buy_date': now
        }
        save_positions(new_positions)
    
    print(f"  [TRADE] {action} {etf_code} @ {price:.3f} ({reason})")
    return True


def check_and_trade():
    """检查持仓并执行交易"""
    print("[" + time.strftime('%H:%M:%S') + "] 拉普拉斯实时交易启动（v2）...")
    
    # 1. 获取实时价格
    print("  获取实时价格...")
    prices = lc.get_tencent_realtime_prices()
    print(f"  [OK] 获取 {len(prices)} 只ETF价格")
    
    # 2. 计算排名
    print("  计算排名...")
    rankings = lc.get_rankings(prices)
    if len(rankings) == 0:
        print("  [ERROR] 无排名数据")
        return
    print(f"  [OK] Top1: {rankings[0]['name']} (得分: {rankings[0]['score']:.2f})")
    
    # 3. 检查持仓
    positions = load_positions()
    top1_code = rankings[0]['code']
    top1_price = rankings[0]['realtime_price']
    
    if positions is None:
        # 无持仓，买入Top1
        print(f"  无持仓，买入Top1: {top1_code}")
        execute_trade(top1_code, 'BUY', top1_price, 'Top1 momentum (auto)')
    else:
        current_code = positions.get('code')
        if current_code != top1_code:
            # 换仓：卖出当前，买入Top1
            current_price = prices.get(current_code, {}).get('price', positions.get('buy_price', 0))
            print(f"  换仓: {current_code} → {top1_code}")
            execute_trade(current_code, 'SELL', current_price, 'Top1 replaced (auto)')
            execute_trade(top1_code, 'BUY', top1_price, 'Top1 momentum (auto)')
        else:
            print(f"  持仓不变: {current_code} @ {positions.get('buy_price')}")
    
    print(f"[" + time.strftime('%H:%M:%S') + "] 任务完成！")


if __name__ == '__main__':
    check_and_trade()
