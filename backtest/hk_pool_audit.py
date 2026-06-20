"""七星港股版 44只优化分析: 选中次数 + 盈亏贡献"""
import json, os
from collections import defaultdict

with open('backtest/results_hk/七星港股版_交易记录_2025-20260618_1536.json') as f:
    data = json.load(f)

trades = data['trades']
HK_NAME = {
    '00700':'腾讯','09988':'阿里','01810':'小米','03690':'美团','09999':'网易',
    '02513':'智谱','00100':'MiniMax',
    '02162':'康诺亚','02616':'基石药业','09688':'再鼎医药','09969':'诺诚健华',
    '02418':'德银天下','00992':'联想','01357':'美图',
    '00981':'中芯国际','01347':'华虹半导体','00522':'ASMPT',
    '01211':'比亚迪','00175':'吉利',
    '03692':'翰森制药','01093':'石药','01177':'中生制药',
    '02338':'潍柴','02038':'富智康','01378':'中国宏桥',
    '00388':'港交所','02388':'中银香港','00005':'汇丰','02318':'平安','00939':'建行','02628':'国寿','03988':'中行',
    '09888':'百度',
    '00883':'中海油','02899':'紫金','03993':'洛阳钼业',
    '02618':'京东物流','02057':'中通快递',
    '09633':'农夫山泉','01929':'周大福','06690':'海尔',
    '01113':'长实','06181':'老铺黄金',
    '00669':'创科实业',
}

# Per-stock stats
stats = defaultdict(lambda: {'buys': 0, 'sells': 0, 'total_pnl': 0.0, 'total_comm': 0.0, 'first_seen': '9999', 'last_seen': '0000'})
for t in trades:
    code = t['code']
    if t['action'] == 'BUY':
        stats[code]['buys'] += 1
        stats[code]['total_comm'] += t.get('comm', 0) + t.get('fee', 0)
    else:
        stats[code]['sells'] += 1
        stats[code]['total_pnl'] += t.get('pnl_pct', 0)
        stats[code]['total_comm'] += t.get('comm', 0) + t.get('stamp', 0) + t.get('fee', 0)
    if t['date'] < stats[code]['first_seen']:
        stats[code]['first_seen'] = t['date']
    if t['date'] > stats[code]['last_seen']:
        stats[code]['last_seen'] = t['date']

# Sort by total PnL contribution
ranked_stocks = sorted(stats.items(), key=lambda x: x[1]['total_pnl'], reverse=True)

print(f'{"代码":>6} | {"名称":<10} | {"买入":>4} | {"卖出":>4} | {"累计盈亏%":>10} | {"首次交易":>10} | {"最后交易":>10} | {"建议":>6}')
print('-' * 95)
never_traded = 0
sum_positive = 0
sum_negative = 0
for code, s in ranked_stocks:
    name = HK_NAME.get(code, code)
    pnl_str = f'{s["total_pnl"]:+.1f}' if s['total_pnl'] != 0 else '   -'
    if s['buys'] == 0:
        advice = '删除'  # never selected
        never_traded += 1
    elif s['total_pnl'] < -50:
        advice = '删除'  # heavy loser
        sum_negative += 1
    elif s['total_pnl'] < 0 and s['buys'] <= 2:
        advice = '删除'  # light loser, barely used
        sum_negative += 1
    else:
        advice = '保留'
        sum_positive += 1
    print(f'{code:>6} | {name:<10} | {s["buys"]:>4} | {s["sells"]:>4} | {pnl_str:>10} | {s["first_seen"]:>10} | {s["last_seen"]:>10} | {advice:>6}')

print()
print('=' * 95)
print(f'总结: 保留{sum_positive}只 + 建议删除{sum_negative + never_traded}只(从未交易{never_traded}只 + 负贡献/极少使用{sum_negative}只)')
never_list = [(c, HK_NAME.get(c,c)) for c,s in ranked_stocks if s['buys']==0]
print(f'从未被选中: {never_list}')
