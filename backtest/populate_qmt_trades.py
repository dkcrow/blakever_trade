#!/usr/bin/env python3
"""QMT原版回测 + 提取交易记录到xlsx (交易时间统一14:52)"""
import sys, warnings, io
warnings.filterwarnings('ignore')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
from pathlib import Path
from strategies.etf import seven_star_base
from strategies.etf.seven_star_172 import BacktestEngine172
from strategies.etf.seven_star_base import LocalDataSource, QMTFilter

# QMT 51 ETF pool (local format)
QMT_RAW = ['513100','513290','513500','159529','513400','513520','513030','513080',
    '513310','513730','159792','513130','513050','159920','513690',
    '511380','511010','511220',
    '518880','159980','159985','501018','161226','159981','512400',
    '510300','510500','510050','510210','159915','588080','512100','563360','563300',
    '512890','159967','588020','512040','159201',
    '515790','563230','515880','512660','561380','159667','159559',
    '159819','159381','159732','159995','512220']
QMT_FORMATTED = [f'sh{c}' if c.startswith('5') else f'sz{c}' for c in QMT_RAW]

# Monkey-patch pool
seven_star_base.ETF_POOL = QMT_FORMATTED[:]
import strategies.etf.seven_star_172 as s172
s172.ETF_POOL = QMT_FORMATTED[:]

# QMT V3 原版参数: 全过滤器开启
PARAMS = {
    'lookback_days': 25,
    'holdings_num': 1,
    'enable_profit_protection': True,
    'enable_volume_check': True,
    'use_short_momentum_filter': True,
    'enable_premium_filter': True,
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'enable_intraday_drawdown': True,
}

START = '2025-01-01'
END = '2026-06-01'

# ETF全称映射（与 generate_qmt_report.py 保持一致）
QMT_NAMES = {
    'sh513100': '纳指ETF国泰', 'sh513290': '纳指生物科技ETF汇添富', 'sh513500': '标普500ETF博时',
    'sz159529': '标普消费ETF景顺', 'sh513400': '道琼斯ETF鹏华', 'sh513520': '日经ETF华夏',
    'sh513030': '德国ETF华安', 'sh513080': '法国ETF华安', 'sh513310': '中韩半导体ETF华泰柏瑞',
    'sh513730': '东南亚科技ETF华泰柏瑞', 'sz159792': '港股通互联网ETF富国', 'sh513130': '恒生科技ETF华泰柏瑞',
    'sh513050': '中概互联网ETF易方达', 'sz159920': '恒生ETF华夏', 'sh513690': '港股红利ETF博时',
    'sh511380': '可转债ETF博时', 'sh511010': '国债ETF国泰', 'sh511220': '城投债ETF海富通',
    'sh518880': '黄金ETF华安', 'sz159980': '有色ETF大成', 'sz159985': '豆粕ETF华夏',
    'sh501018': '南方原油LOF', 'sz161226': '国投白银LOF', 'sz159981': '能源化工ETF建信',
    'sh512400': '有色金属ETF南方',
    'sh510300': '沪深300ETF华泰柏瑞', 'sh510500': '中证500ETF南方', 'sh510050': '上证50ETF华夏',
    'sh510210': '上证指数ETF富国', 'sz159915': '创业板ETF易方达', 'sh588080': '科创50ETF易方达',
    'sh512100': '中证1000ETF南方', 'sh563360': 'A500ETF华泰柏瑞', 'sh563300': '中证2000ETF华泰柏瑞',
    'sh512890': '红利低波ETF华泰柏瑞', 'sz159967': '创业板成长ETF华夏', 'sh588020': '科创成长ETF易方达',
    'sh512040': '价值100ETF富国', 'sz159201': '自由现金流ETF华夏',
    'sh515790': '光伏ETF华泰柏瑞', 'sh563230': '卫星ETF富国', 'sh515880': '通信ETF国泰',
    'sh512660': '军工ETF国泰', 'sh561380': '电网设备ETF国泰', 'sz159667': '工业母机ETF国泰',
    'sz159559': '机器人ETF景顺', 'sz159819': '人工智能ETF易方达', 'sz159381': '创业板人工智能ETF华夏',
    'sz159732': '消费电子ETF华夏', 'sz159995': '芯片ETF华夏', 'sh512220': 'TMTETF景顺',
}

print(f"QMT原版回测: {START} ~ {END}")
print(f"参数: {PARAMS}")
ds = LocalDataSource()
engine = BacktestEngine172(ds, engine_params=PARAMS, etf_filter=QMTFilter())
engine.commission_rate = 0.0002

result = engine.run(START, END, 10000)

# Extract trades
trades = engine.portfolio.trade_log  # list of dicts: action, code, price, date, ...

# Also check results dict
if not trades:
    # fallback to results
    trades = result.get('trade_log', []) if isinstance(result, dict) else []

print(f"\nTotal trades: {len(trades)}")

# Build xlsx rows with 14:52 time
rows = []
for t in trades:
    d = str(t.get('date', ''))
    action = t.get('action', '')
    direction = '买入' if action == 'BUY' else '卖出'
    code = t.get('code', '')
    name = QMT_NAMES.get(code, t.get('name', code))
    price = float(t.get('price', 0))
    score = t.get('score', 'N/A')  # trade_log doesn't store score, use N/A

    # 交易时间统一 14:52
    if len(d) == 10 and d.count('-') == 2:
        trade_date = f'{d} 14:52'
    else:
        trade_date = d

    if direction == '卖出':
        reason = t.get('reason', '排名下降调出')
    else:
        reason = t.get('reason', f'动量排名第1/51')

    rows.append({
        '交易日期': trade_date,
        'ETF名称': name,
        'ETF代码': code,
        '方向': direction,
        '成交价格': round(price, 4),
        '综合动量得分': round(score, 4) if isinstance(score, (int, float)) else str(score),
        '交易理由': reason,
    })

df = pd.DataFrame(rows)
output_dir = Path('backtest/results_qmt')
output_dir.mkdir(parents=True, exist_ok=True)
xlsx_path = output_dir / '七星QMT_交易记录_2026.xlsx'
df.to_excel(str(xlsx_path), index=False)

print(f"\nSaved {len(rows)} records to {xlsx_path}")
print(f"Sample (first 5):")
for r in rows[:5]:
    print(f"  {r['交易日期']} {r['方向']:4s} {r['ETF名称']:16s} {r['成交价格']:.4f} {r['交易理由']}")
print(f"\n... last 5:")
for r in rows[-5:]:
    print(f"  {r['交易日期']} {r['方向']:4s} {r['ETF名称']:16s} {r['成交价格']:.4f} {r['交易理由']}")

# Quick stats
sells = [r for r in rows if r['方向'] == '卖出']
buys = [r for r in rows if r['方向'] == '买入']
print(f"\nStats: {len(buys)} buys, {len(sells)} sells")
