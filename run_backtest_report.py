#!/usr/bin/env python3
"""七星拉普拉斯策略回测 - 完整交易记录报告"""
import sys, os, io, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategies.etf.seven_star_laplacian import (
    BacktestEngine, LocalDataSource, ETF_NAMES
)
from datetime import datetime

START_DATE = '2025-01-01'
END_DATE   = '2026-05-20'
INITIAL_CASH = 10_000

# 静默运行回测
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    with contextlib.redirect_stderr(buf):
        ds = LocalDataSource('data/storage/stock_data/etf')
        engine = BacktestEngine(ds, {})
        results = engine.run(START_DATE, END_DATE, INITIAL_CASH)

trade_log = engine.portfolio.trade_log
daily_vals = engine.portfolio.daily_values

# 买卖配对
positions_map = {}
trades_pair = []

for t in trade_log:
    code = t['code']
    name = ETF_NAMES.get(code, code)
    if t['action'] == 'BUY':
        positions_map.setdefault(code, []).append({
            'buy_date': t['date'],
            'buy_price': t['price'],
            'shares': t['shares'],
            'amount': t['shares'] * t['price'],
            'reason': t.get('reason', ''),
        })
    elif t['action'] == 'SELL':
        if code in positions_map and positions_map[code]:
            buy = positions_map[code].pop(0)
            cp = buy['buy_price']
            sp = t['price']
            pnl_pct = (sp - cp) / cp * 100 if cp > 0 else 0
            hold_days = ''
            try:
                d1 = datetime.strptime(buy['buy_date'], '%Y-%m-%d')
                d2 = datetime.strptime(t['date'], '%Y-%m-%d')
                hold_days = str((d2 - d1).days)
            except: pass
            trades_pair.append({
                'etf_code': code, 'etf_name': name,
                'buy_date': buy['buy_date'], 'sell_date': t['date'],
                'buy_price': cp, 'sell_price': sp,
                'shares': buy['shares'],
                'buy_amount': round(buy['amount'], 2),
                'sell_amount': round(t['shares'] * sp, 2),
                'buy_reason': buy.get('reason', ''),
                'sell_reason': t.get('reason', ''),
                'pnl_pct': round(pnl_pct, 2),
                'pnl_amount': round(t['shares'] * sp - buy['amount'], 2),
                'hold_days': hold_days,
            })

open_positions = []
for code, buys in positions_map.items():
    for buy in buys:
        open_positions.append({
            'etf_code': code,
            'etf_name': ETF_NAMES.get(code, code),
            'buy_date': buy['buy_date'],
            'buy_price': buy['buy_price'],
            'shares': buy['shares'],
            'amount': round(buy['shares'] * buy['buy_price'], 2),
            'reason': buy.get('reason', ''),
        })

# ============================================================
# 输出完整报告（写入文件）
# ============================================================
lines = []
L = lines.append

L('='*140)
L('  七星拉普拉斯策略 v3.0 - 历史交易记录详细报告')
L(f'  回测区间: {START_DATE} ~ {END_DATE} | 初始资金: {INITIAL_CASH:,}元')
L('='*140)
L('')
L('-'*140)
L('%-4s %-12s %-16s %-8s %-8s %9s %9s %7s %13s %13s %-14s %-18s %+8s %+10s' % (
    '#', 'ETF代码', 'ETF名称', '买入日', '卖出日',
    '买入价', '卖出价', '数量',
    '买入金额', '卖出金额',
    '买入理由', '卖出理由',
    '盈亏率', '盈亏额'
))
L('-'*140)

total_pnl = 0
commission_rate = 0.0003
total_comm = 0

for i, tr in enumerate(trades_pair, 1):
    comm = (tr['buy_amount'] + tr['sell_amount']) * commission_rate
    total_comm += comm
    net = tr['pnl_amount'] - comm
    total_pnl += net
    L('%-4d %-12s %-16s %-8s %-8s %9.3f %9.3f %7d %13.2f %13.2f %-14s %-18s %+7.2f%% %+10.2f' % (
        i, tr['etf_code'], tr['etf_name'],
        tr['buy_date'], tr['sell_date'],
        tr['buy_price'], tr['sell_price'],
        tr['shares'],
        tr['buy_amount'], tr['sell_amount'],
        tr['buy_reason'][:12], tr['sell_reason'][:15],
        tr['pnl_pct'], tr['pnl_amount']
    ))

if not trades_pair:
    L('  (无已完成交易)')

# 未平仓
if open_positions:
    L('')
    L('-'*140)
    L('  未平仓持仓:')
    L('-'*140)
    for op in open_positions:
        L('    %s %s | 买入:%s 价格:%.3f 数量:%d 金额:%.2f 理由:%s' % (
            op['etf_code'], op['etf_name'], op['buy_date'],
            op['buy_price'], op['shares'], op['amount'], op['reason']
        ))

# 总结
final_value = daily_vals[-1]['value'] if daily_vals else 0
final_ret = (final_value / INITIAL_CASH - 1) * 100
buy_n = sum(1 for t in trade_log if t['action'] == 'BUY')
sell_n = sum(1 for t in trade_log if t['action'] == 'SELL')

wins = [t for t in trades_pair if t['pnl_pct'] > 0]
losses = [t for t in trades_pair if t['pnl_pct'] <= 0]
avg_w = sum(t['pnl_pct'] for t in wins)/len(wins) if wins else 0
avg_l = sum(t['pnl_pct'] for t in losses)/len(losses) if losses else 0
mx_w = max((t['pnl_pct'] for t in wins), default=0)
mx_l = min((t['pnl_pct'] for t in losses), default=0)

# 按ETF统计交易频率
etf_stats = {}
for tr in trades_pair:
    c = tr['etf_code']
    if c not in etf_stats:
        etf_stats[c] = {'name': tr['etf_name'], 'count': 0, 'win': 0, 'total_pnl': 0}
    etf_stats[c]['count'] += 1
    if tr['pnl_pct'] > 0: etf_stats[c]['win'] += 1
    etf_stats[c]['total_pnl'] += tr['pnl_amount']

L('')
L('='*100)
L('  回测总结')
L('='*100)
L(f'  策略版本:     七星拉普拉斯 v3.0 (本地化)')
L(f'  回测区间:     {START_DATE} ~ {END_DATE}')
L(f'  初始资金:     {INITIAL_CASH:>12,.2f} 元')
L(f'  最终资产:     {final_value:>12,.2f} 元')
sign_r = '+' if final_ret >= 0 else ''
sign_p = '+' if (final_value - INITIAL_CASH) >= 0 else ''
L('  总收益率:     %s%.2f%%' % (sign_r, final_ret))
L('  盈利/亏损:    %s%.2f 元' % (sign_p, final_value - INITIAL_CASH))
L('')
L(f'  总交易次数:   {len(trade_log)} 次 (买入{buy_n}次 / 卖出{sell_n}次)')
L(f'  已完成轮次:   {len(trades_pair)} 轮 (买+卖配对)')
L(f'  未平仓持仓:   {len(open_positions)} 只')
L('')
L(f'  胜率:         {len(wins)/len(trades_pair)*100:.1f}% ({len(wins)}赢/{len(losses)}负)' if trades_pair else '  胜率:         N/A')
L(f'  平均盈利:     {avg_w:+.2f}%')
L(f'  平均亏损:     {avg_l:+.2f}%')
L(f'  最大单笔盈利: {mx_w:+.2f}%')
L(f'  最大单笔亏损: {mx_l:+.2f}%')
L(f'  盈亏比:       {abs(avg_w/avg_l):.2f}' if avg_l != 0 else '  盈亏比:       N/A')
L(f'  预估总手续费: {total_comm:.2f} 元 (按万三双边)')
L(f'  净盈亏(扣费): {total_pnl:+,.2f} 元')
L('')
L('  各ETF交易统计:')
L('  %-12s %-16s %5s %5s %10s %10s' % ('代码', '名称', '次数', '胜', '总盈亏额', '平均盈亏%'))
L('  ' + '-'*60)
sorted_etfs = sorted(etf_stats.items(), key=lambda x: x[1]['count'], reverse=True)
for c, s in sorted_etfs:
    avg_pnl_pct = s['total_pnl'] / (s['count'] * INITIAL_CASH) * 100 if s['count'] > 0 else 0
    L('  %-12s %-16s %5d %5d %+10.2f %+9.2f%%' % (c, s['name'], s['count'], s['win'], s['total_pnl'], avg_pnl_pct))

L('')
L('  资金曲线:')
n_dv = len(daily_vals)
step = max(1, n_dv // 15)
for i in range(0, n_dv, step):
    d = daily_vals[i]
    rv = (d['value']/INITIAL_CASH-1)*100
    L('    %s -> %12.2f元 (%+.2f%%)' % (d['date'], d['value'], rv))
if n_dv > 0 and (n_dv-1) != i:
    d = daily_vals[-1]
    rv = (d['value']/INITIAL_CASH-1)*100
    L('    %s -> %12.2f元 (%+.2f%%)' % (d['date'], d['value'], rv))

L('')
L('='*100)

report_text = '\n'.join(lines)
print(report_text)

# 同时保存到文件
out_path = os.path.join(os.path.dirname(__file__),
    f'report_seven_star_{START_DATE}_{END_DATE}.txt')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(report_text)
print(f'\n报告已保存至: {out_path}')
