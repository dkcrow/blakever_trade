"""
七星172 完整回测 + 交易记录重建 v2
修复: 综合动量得分存真实分数而非排名号
"""
import sys, os, json
from pathlib import Path
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.etf.seven_star_base import (
    LocalDataSource, Portfolio, ETF_POOL, ETF_NAMES, DEFENSIVE_ETF
)
from strategies.etf.seven_star_172 import SevenStar172Engine, BacktestEngine172

PROJECT_ROOT = Path(__file__).parent.parent
TRADES_XLSX = PROJECT_ROOT / 'backtest' / 'results_172' / '七星172_交易记录_2026.xlsx'
TRADES_XLSX.parent.mkdir(parents=True, exist_ok=True)

START_DATE = '2025-01-01'
END_DATE = '2026-05-28'
INITIAL_CASH = 10000

# 1. 备份
if TRADES_XLSX.exists():
    backup = TRADES_XLSX.with_suffix('.xlsx.bak')
    if backup.exists():
        backup.unlink()
    TRADES_XLSX.rename(backup)
    print(f"[备份] -> {backup.name}")

# 2. 加载数据
print(f"加载数据: {START_DATE} ~ {END_DATE}")
ds = LocalDataSource()
all_data = ds.load_all_etfs(START_DATE, END_DATE)
nav_data = ds.load_all_navs()
print(f"  ETF: {len(all_data)}/38, NAV: {len(nav_data)}/38")

# 3. 引擎
engine = SevenStar172Engine(mode='backtest')
engine.nav_data = nav_data
engine.reset_state()

bt = BacktestEngine172(ds, engine_params=engine.params)
bt.engine = engine
bt.portfolio = Portfolio(initial_cash=INITIAL_CASH, commission_rate=0.0002, min_commission=5)

trade_dates = ds.get_trade_dates(START_DATE, END_DATE)
print(f"  交易日: {len(trade_dates)} 天")

# 4. 逐日回测 + 记录买入得分
score_map = {}  # (date, code) -> score

for i, td in enumerate(trade_dates):
    td_ts = pd.Timestamp(td)
    td_str = str(td)

    current_prices = {}
    for code, df in all_data.items():
        mask = df.index <= td_ts
        if mask.any():
            current_prices[code] = float(df.loc[mask, 'close'].iloc[-1])

    bt.portfolio.update_prices(current_prices)
    bt.engine.reset_daily_blacklist()

    # 获取当日排名（记录买入时的得分）
    ranked = bt.engine.get_ranked_etfs(all_data, current_prices, td)
    for m in ranked:
        score_map[(td_str, m['etf'])] = round(m['score'], 4)

    # 11:00 盈利保护
    bt._run_profit_protection(current_prices, all_data, td)
    # 13:10 卖出
    bt._run_sell(current_prices, all_data, td)
    # 13:11 买入
    bt._run_buy(current_prices, all_data, td)

    bt.portfolio.record_daily_value(td)

    if (i + 1) % 50 == 0:
        print(f"  [{td}] 资产={bt.portfolio.total_value:,.2f}")

# 5. 写入xlsx
print(f"\n写入交易记录...")
trades = bt.portfolio.trade_log
records = []

for t in trades:
    td_str = str(t['date'])[:10]
    direction = '买入' if t['action'] == 'BUY' else '卖出'

    # 查找真实得分
    score = score_map.get((td_str, t['code']), None)

    # 交易理由格式化
    reason = t.get('reason', '')
    if '排名' in str(reason):
        rank_num = str(reason).replace('排名', '')
        reason = f'动量排名第{rank_num}/{len(ETF_POOL)}'
    elif reason == '调出目标':
        reason = '调出目标(排名下降)'

    records.append({
        '交易日期': td_str,
        'ETF名称': t['name'],
        'ETF代码': t['code'],
        '方向': direction,
        '成交价格': round(t['price'], 4),
        '综合动量得分': round(score, 4) if score is not None else '',
        '交易理由': reason,
    })

df = pd.DataFrame(records)
df.to_excel(TRADES_XLSX, index=False)

# 6. 计算盈亏
buy_queue = {}
for i in range(len(records) - 1, -1, -1):
    r = records[i]
    code = r['ETF代码']
    direction = r['方向']
    price = r['成交价格']
    try:
        price = float(price)
    except:
        price = 0

    if direction == '买入':
        if code not in buy_queue:
            buy_queue[code] = []
        buy_queue[code].append(price)
        r['_pnl'] = '-'
    else:
        if code in buy_queue and buy_queue[code]:
            buy_price = buy_queue[code].pop(0)
            if buy_price > 0 and price > 0:
                pnl = (price - buy_price) / buy_price * 100
                r['_pnl'] = f'{pnl:+.2f}%'
            else:
                r['_pnl'] = '-'
        else:
            r['_pnl'] = '-'

for r in records:
    if '_pnl' not in r:
        r['_pnl'] = '-'

print(f"  records: {len(records)}")

# 7. 显示结果
print(f"\n{'='*80}")
print(f"最近20条交易记录")
print(f"{'='*80}")
print(f"{'日期':<12}{'方向':<6}{'名称':<22}{'代码':<14}{'价格':>8}{'得分':>10}{'盈亏':>8}{'理由':<24}")
print("-" * 80)

for r in records[-20:]:
    score_s = f"{r['综合动量得分']:.4f}" if r['综合动量得分'] != '' else 'N/A'
    pnl = r.get('_pnl', '-')
    print(f"{r['交易日期']:<12}{r['方向']:<6}{r['ETF名称']:<22}{r['ETF代码']:<14}"
          f"{r['成交价格']:>8.4f}{score_s:>10}{pnl:>8}{r['交易理由']:<24}")

# 8. 当前持仓
last_buy = None
for r in reversed(records):
    if r['方向'] == '买入':
        last_buy = r
        break

print(f"\n当前持仓: {last_buy['ETF名称']}({last_buy['ETF代码']}) @{last_buy['成交价格']} 买入于 {last_buy['交易日期']}")

# 9. 统计
buys = sum(1 for r in records if r['方向'] == '买入')
sells = sum(1 for r in records if r['方向'] == '卖出')
sell_records = [r for r in records if r['方向'] == '卖出']
wins = sum(1 for r in sell_records if r.get('_pnl', '-').startswith('+'))
losses = sum(1 for r in sell_records if r.get('_pnl', '-').startswith('-') and r['_pnl'] != '-')
print(f"\n总交易: {len(records)} (买{buys}/卖{sells}) | 盈利{sells-losses}笔/亏损{losses}笔")

print(f"\n完成! -> {TRADES_XLSX.name}")
