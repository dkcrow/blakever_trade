"""
验证补录结果
"""
import json

with open(r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json', 'r', encoding='utf-8') as f:
    trades = json.load(f)

print("=== 5.22-5.26 的交易记录 ===")
for t in trades:
    date = t.get('date', '')
    if '2026-05-22' <= date <= '2026-05-26':
        print(f"{date} | {t.get('etf')} | {t.get('action')} | {t.get('reason')}")

print()
print("=== 当前持仓（从最后一条BUY记录） ===")
for t in reversed(trades):
    if t.get('action') == 'BUY':
        print(f"持仓: {t.get('etf')} @ {t.get('price')} ({t.get('date')})")
        break
