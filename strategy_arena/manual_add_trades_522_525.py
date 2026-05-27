"""
补录 5.22-5.25 的交易记录
假设 5.22-5.25 期间 Top1 都是 513310（中韩半导体ETF）
"""
import json
from datetime import datetime, timedelta

# 读取现有交易记录
with open(r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json', 'r', encoding='utf-8') as f:
    trades = json.load(f)

print(f"当前交易记录数: {len(trades)}")

# 检查 5.21 之后是否已有交易
has_522_525 = any(t.get('date', '') >= '2026-05-22' and t.get('date', '') <= '2026-05-25' for t in trades)
print(f"5.22-5.25 是否已有交易: {has_522_525}")

if not has_522_525:
    # 5.21 卖出 513310
    sell_521 = None
    for t in trades:
        if t.get('date') == '2026-05-21' and t.get('action') == 'SELL':
            sell_521 = t
            break
    
    if sell_521:
        print(f"找到 5.21 卖出记录: {sell_521}")
        
        # 5.22 买入 513310（假设它仍是 Top1）
        buy_522 = {
            'id': 'manual_522',
            'date': '2026-05-22',
            'etf': '513310',
            'name': '中韩半导体ETF华泰柏瑞',
            'action': 'BUY',
            'price': sell_521['price'],  # 用卖出价近似
            'reason': 'Manual: Continue holding Top1 from 5.21',
            'pnl_pct': None
        }
        trades.append(buy_522)
        print(f"已添加 5.22 买入记录")
        
        # 5.26 的"首次买入"改成"继续持有"或删除
        for i, t in enumerate(trades):
            if t.get('date') == '2026-05-26' and t.get('action') == 'BUY' and t.get('reason') == 'Initial Top1':
                # 改成"继续持有"
                trades[i]['reason'] = 'Manual: Continue holding (5.22-5.25)'
                trades[i]['id'] = 'manual_526'
                print(f"已修改 5.26 买入记录为继续持有")
                break
    
    # 按日期排序
    trades.sort(key=lambda x: x.get('date', ''))
    
    # 保存
    with open(r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json', 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)
    
    print("\n[OK] 补录完成！新的交易记录数: {}".format(len(trades)))
else:
    print("5.22-5.25 已有交易记录，无需补录")
