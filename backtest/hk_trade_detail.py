"""显示指定股票的买入-卖出历史"""
import json
import pandas as pd

with open('backtest/results_hk/七星港股版_44只_3年交易记录.json','r',encoding='utf-8') as f:
    data = json.load(f)
trades = data['trades']

NAMES = {'00939':'建行','09688':'再鼎医药','01211':'比亚迪','00388':'港交所','09969':'诺诚健华','00992':'联想','00669':'创科实业','02618':'京东物流','03988':'中国银行'}
for code in ['00939','09688','01211','00388','09969','00992','00669']:
    ct = [t for t in trades if t['code']==code]
    buys = [t for t in ct if t['action']=='BUY']
    sells = [t for t in ct if t['action']=='SELL']
    print(f'=== {code} {NAMES[code]} ({len(buys)}买/{len(sells)}卖) ===')
    for i in range(min(len(buys), len(sells))):
        b = buys[i]; s = sells[i]
        days = (pd.Timestamp(s['date'])-pd.Timestamp(b['date'])).days
        bp = b.get('price',0); sp = s.get('price',0)  # sell price not in sell record... use buy price
        pnl = s.get('pnl_pct',0)
        print(f'  {b["date"]} 买入 HK${bp:.2f} → {s["date"]} 卖出 pnl={pnl:+.2f}% ({days}天)')
    if len(sells) > len(buys):
        for s in sells[len(buys):]:
            print(f'  (遗留卖出) {s["date"]} pnl={s.get("pnl_pct",0):+.2f}%')
    print()
