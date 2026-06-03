"""重建七星172历史交易记录
回测: 2025-01-02 ~ 2026-06-02
过滤器: 盈利保护(回撤>5%) + 溢价率>20%
输出: backtest/results_172/七星172_交易记录_2026.xlsx
"""
import sys, warnings, io
warnings.filterwarnings('ignore')
sys.path.insert(0, r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
from pathlib import Path
from strategies.etf import seven_star_base
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource, ETF_NAMES

START = '2025-01-02'
END = '2026-06-02'

# 参数: 盈利保护 + 溢价率 (消融实验证实其余4层均为负贡献)
PARAMS = {
    'lookback_days': 25,
    'holdings_num': 1,
    'enable_profit_protection': True,      # 重新启用: +35%收益 -2.2%回撤
    'enable_volume_check': False,          # 永久关闭
    'use_short_momentum_filter': False,    # 永久关闭
    'enable_premium_filter': True,         # 保留
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
    'loss': 0.01,                          # 永久关闭
    'min_score_threshold': -999999,        # 永久关闭
    'max_score_threshold': 999999,         # 永久关闭
    'short_lookback_days': 10,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
}

print(f'七星172回测 (成交量已关闭)')
print(f'区间: {START} ~ {END}')
print(f'ETF池: {len(seven_star_base.ETF_POOL)}只')
print()

ds = LocalDataSource()
engine = BacktestEngine172(ds, engine_params=PARAMS)
engine.commission_rate = 0.0002
result = engine.run(START, END, 10000)

tr = result.get('total_return', 0)
sr = result.get('sharpe_ratio', result.get('sharpe', 0))
mdd = result.get('max_drawdown', 0)
nt = result.get('total_trades', result.get('num_trades', 0))
fv = result.get('final_value', 0)
wr = result.get('win_rate', 0)

print(f'\n=== 回测结果 ===')
print(f'总收益率: {tr*100:.2f}%')
print(f'年化收益率: {((1+tr)**(1/((2026+5/12-2025-1/12)))-1)*100:.2f}%' if tr > -1 else '年化: N/A')
print(f'夏普比率: {sr:.2f}' if sr else '夏普: N/A')
print(f'最大回撤: {mdd*100:.2f}%' if mdd else '最大回撤: N/A')
print(f'交易次数: {nt}')
print(f'胜率: {wr*100:.1f}%' if wr else '胜率: N/A')
print(f'最终资产: ¥{fv:,.0f}' if fv else '最终资产: N/A')

# 提取交易记录
trades = engine.portfolio.trade_log
print(f'\n交易记录: {len(trades)}条')

# 构建xlsx行
rows = []
for t in trades:
    d = str(t.get('date', ''))
    action = t.get('action', '')
    direction = '买入' if action == 'BUY' else '卖出'
    code = t.get('code', '')
    name = ETF_NAMES.get(code, code)
    price = float(t.get('price', 0))
    
    if len(d) == 10 and d.count('-') == 2:
        trade_date = f'{d} 13:04'
    else:
        trade_date = d

    if direction == '卖出':
        reason = t.get('reason', '排名下降调出')
    else:
        reason = t.get('reason', f'动量排名第1/{len(seven_star_base.ETF_POOL)}')

    rows.append({
        '交易日期': trade_date,
        '方向': direction,
        'ETF名称': name,
        'ETF代码': code,
        '成交价格': round(price, 4),
        '综合动量得分': 'N/A',
        '交易理由': reason,
    })

# 计算盈亏
for i in range(0, len(rows)-1, 2):
    if i+1 >= len(rows):
        break
    sell = rows[i]
    buy = rows[i+1]
    if sell['方向'] == '买入' and rows[i+1]['方向'] == '卖出':
        sell, buy = rows[i+1], rows[i]
    if sell['ETF代码'] == buy['ETF代码'] and sell['方向'] == '卖出' and buy['方向'] == '买入':
        pnl = (sell['成交价格'] - buy['成交价格']) / buy['成交价格'] * 100
        rows[i]['收益率'] = f'{pnl:.2f}%'

xlsx_path = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\backtest\results_172\七星172_交易记录_2026.xlsx')
xlsx_path.parent.mkdir(parents=True, exist_ok=True)
df = pd.DataFrame(rows)
df.to_excel(xlsx_path, index=False)

print(f'\n已写入: {xlsx_path}')
print(f'共 {len(df)} 条记录')
print(f'日期范围: {df.iloc[0]["交易日期"][:10]} ~ {df.iloc[-1]["交易日期"][:10]}')

# 显示最后5条
print(f'\n最后5条:')
for _, r in df.tail(5).iterrows():
    print(f"  {r['交易日期']}  {r['方向']}  {r['ETF名称']}  @{r['成交价格']}")
