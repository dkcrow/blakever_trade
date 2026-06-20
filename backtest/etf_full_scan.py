"""
全量A股ETF扫描 + 七星172贡献度分析
1. 获取所有A股ETF列表
2. 下载/更新5年(2021至今)日线数据
3. 对每只ETF运行172动量评分, 统计贡献度
4. 输出优化建议
"""
import akshare as ak
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import time, json, sys, os

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'etf'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 当前172池
CURRENT_POOL = [
    "sh518880","sz159980","sz159985","sh501018","sz161226","sz159981",
    "sh513100","sz159509","sh513290","sh513500","sz159529",
    "sh513400","sh513520","sh513030","sh513080","sh513310","sh513730",
    "sz159792","sh513130","sh513050","sz159920","sh513690",
    "sh510300","sh510500","sh510050","sh510210","sz159915",
    "sh588080","sh512100","sh563360","sh563300",
    "sh512890","sz159967","sh512040","sz159201","sh562500","sh560090",
    "sh511380","sh511010","sz511220",
]
CURRENT_CODES = set(c[2:] for c in CURRENT_POOL)  # strip sh/sz prefix

START_DATE = "20210101"
END_DATE = datetime.now().strftime("%Y%m%d")
BACKTEST_START = "2024-01-01"
BACKTEST_END = "2026-06-19"

# ================================================================
# Step 1: 获取全部A股ETF列表
# ================================================================
print("=" * 70)
print("Step 1: 获取A股ETF列表...")
try:
    etf_list = ak.fund_etf_spot_em()
    print(f"  获取到 {len(etf_list)} 只ETF")
    # 只保留代码为6位数字的
    etf_list = etf_list[etf_list['代码'].str.match(r'^\d{6}$')]
    print(f"  过滤后 {len(etf_list)} 只")
except Exception as e:
    print(f"  获取ETF列表失败: {e}")
    sys.exit(1)

# ================================================================
# Step 2: 下载/更新5年数据
# ================================================================
print(f"\nStep 2: 下载/更新ETF数据 ({START_DATE} ~ {END_DATE})...")
all_codes = etf_list['代码'].tolist()
downloaded = 0; skipped = 0; failed = 0; updated = 0

for i, code in enumerate(all_codes):
    fp = DATA_DIR / f'{code}.csv'
    
    # 检查是否已有最新数据
    if fp.exists():
        try:
            df_existing = pd.read_csv(fp)
            if len(df_existing) > 0:
                last_col = 'date' if 'date' in df_existing.columns else '日期'
                if last_col in df_existing.columns:
                    last_date = str(df_existing[last_col].iloc[-1]).replace('-','')
                    if last_date >= "20260618":
                        skipped += 1
                        if (i+1) % 100 == 0:
                            print(f"  [{i+1}/{len(all_codes)}] 已跳过 {skipped}, 下载 {downloaded}, 更新 {updated}, 失败 {failed}")
                        continue
        except:
            pass
    
    # 下载数据
    try:
        df = ak.fund_etf_hist_em(symbol=code, period="daily", 
                                  start_date=START_DATE, end_date=END_DATE,
                                  adjust="qfq")
        if df is not None and len(df) > 50:
            df = df.rename(columns={'日期':'date','开盘':'open','收盘':'close','最高':'high','最低':'low','成交量':'volume'})
            df = df[['date','open','close','high','low','volume']]
            df.to_csv(fp, index=False)
            if fp.exists():
                updated += 1
            else:
                downloaded += 1
        else:
            failed += 1
        time.sleep(0.3)  # 限速
    except Exception as e:
        failed += 1
        if "该" in str(e) or "不存在" in str(e):
            pass  # ETF可能已退市
        time.sleep(0.2)
    
    if (i+1) % 50 == 0:
        print(f"  [{i+1}/{len(all_codes)}] 下载/更新 {downloaded+updated}, 跳过 {skipped}, 失败 {failed}")

print(f"\n  完成: 下载 {downloaded}, 更新 {updated}, 跳过 {skipped}, 失败 {failed}")

# ================================================================
# Step 3: 对所有ETF运行172动量评分
# ================================================================
print(f"\nStep 3: 172策略贡献度分析 ({BACKTEST_START} ~ {BACKTEST_END})...")

def calc_score(closes, lookback=25):
    """172动量评分: exp(slope×250) × R²"""
    if len(closes) < max(5, lookback):
        return -999
    recent = closes[-lookback:]
    x = np.arange(len(recent))
    y = np.log(np.maximum(recent, 1e-10))
    mask = ~np.isnan(y) & ~np.isinf(y)
    x_m, y_m = x[mask], y[mask]
    if len(x_m) < 5:
        return -999
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_res = np.sum(res**2)
    ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return ann * r2

# 加载所有ETF数据
all_etf_data = {}
etf_files = sorted(DATA_DIR.glob('*.csv'))
for fp in etf_files:
    code = fp.stem
    try:
        df = pd.read_csv(fp)
        if 'date' not in df.columns and '日期' in df.columns:
            df = df.rename(columns={'日期':'date','收盘':'close','开盘':'open','最高':'high','最低':'low','成交量':'volume'})
        if 'date' not in df.columns:
            continue
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        # 需要在回测期间有足够数据
        bt_data = df[(df.index >= BACKTEST_START) & (df.index <= BACKTEST_END)]
        if len(bt_data) > 100 and 'close' in df.columns:
            all_etf_data[code] = df
    except:
        pass

print(f"  有效ETF: {len(all_etf_data)} 只")

# 计算交易日序列
trade_dates = sorted(set().union(*[set(df.index) for df in all_etf_data.values()]))
trade_dates = [d for d in trade_dates if BACKTEST_START <= d.strftime('%Y-%m-%d') <= BACKTEST_END]
print(f"  交易日: {len(trade_dates)} 天")

# 模拟172策略: 每天选排名第1的ETF, 跟踪每只ETF被选中次数和带来的收益
etf_stats = {}  # code -> {'selected': count, 'pnl': cumulative, 'trades': [...]}
prev_held = None
prev_price = 0

for date in trade_dates:
    # 获取当日价格
    prices = {}
    for code, df in all_etf_data.items():
        if date in df.index:
            val = df.loc[date, 'close']
            if hasattr(val, 'iloc'):
                val = val.iloc[0]
            if float(val) > 0:
                prices[code] = float(val)
    
    if len(prices) < 5:
        continue
    
    # 计算动量得分
    scored = []
    for code in prices:
        df = all_etf_data[code]
        hist = df[df.index < date]
        if len(hist) < 25:
            continue
        score = calc_score(hist['close'].values, 25)
        if score > 0:  # 只考虑正分
            scored.append((code, score, prices[code]))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    
    if not scored:
        # 如果没有正分ETF, 持有防守
        if prev_held and prev_held != 'CASH':
            # 卖出
            if prev_held in prices:
                sell_pnl = (prices[prev_held] - prev_price) / prev_price * 100
                if prev_held not in etf_stats:
                    etf_stats[prev_held] = {'selected': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
                etf_stats[prev_held]['pnl'] += sell_pnl
                if sell_pnl > 0:
                    etf_stats[prev_held]['wins'] += 1
                else:
                    etf_stats[prev_held]['losses'] += 1
            prev_held = 'CASH'
            prev_price = 0
        continue
    
    top_code = scored[0][0]
    top_price = scored[0][2]
    
    # 如果和昨天持有的一样, 不换
    if top_code == prev_held:
        continue
    
    # 卖出旧持仓
    if prev_held and prev_held != 'CASH' and prev_held in prices:
        sell_pnl = (prices[prev_held] - prev_price) / prev_price * 100
        if prev_held not in etf_stats:
            etf_stats[prev_held] = {'selected': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
        etf_stats[prev_held]['pnl'] += sell_pnl
        if sell_pnl > 0:
            etf_stats[prev_held]['wins'] += 1
        else:
            etf_stats[prev_held]['losses'] += 1
    
    # 买入新标的
    if top_code not in etf_stats:
        etf_stats[top_code] = {'selected': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
    etf_stats[top_code]['selected'] += 1
    prev_held = top_code
    prev_price = top_price

# 最后一天平仓
if prev_held and prev_held != 'CASH' and prev_held in prices:
    sell_pnl = (prices[prev_held] - prev_price) / prev_price * 100
    if prev_held not in etf_stats:
        etf_stats[prev_held] = {'selected': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
    etf_stats[prev_held]['pnl'] += sell_pnl

# ================================================================
# Step 4: 输出结果
# ================================================================
print(f"\n{'='*90}")
print(f"{'全量ETF 172策略贡献度排名':^80}")
print(f"{'='*90}")

# 读取ETF名称
name_map = {}
try:
    for _, row in etf_list.iterrows():
        name_map[row['代码']] = row['名称']
except:
    pass

ranked = sorted(etf_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)

print(f"\n{'排名':>4} | {'代码':>6} | {'名称':<20} | {'入选':>4} | {'胜':>3}/{' 负':>3} | {'累计盈亏%':>10} | {'池内?':>5}")
print('-' * 90)

in_pool_count = 0; not_in_pool_positive = []
for i, (code, stats) in enumerate(ranked):
    name = name_map.get(code, '未知')[:18]
    in_pool = '✅' if code in CURRENT_CODES else ''
    if code in CURRENT_CODES:
        in_pool_count += 1
    if stats['pnl'] > 0 and code not in CURRENT_CODES:
        not_in_pool_positive.append((code, name, stats))
    if i < 50 or code in CURRENT_CODES:  # Top50 或池内ETF
        print(f"{i+1:>4} | {code:>6} | {name:<20} | {stats['selected']:>4} | {stats['wins']:>3}/{stats['losses']:>3} | {stats['pnl']:>+10.1f} | {in_pool:>5}")

total_positive = sum(1 for _, s in etf_stats.items() if s['pnl'] > 0)
total_negative = sum(1 for _, s in etf_stats.items() if s['pnl'] <= 0)
print(f"\n{'='*90}")
print(f"  总计: {len(etf_stats)} 只ETF被策略选中过")
print(f"  正贡献: {total_positive} 只 | 负贡献: {total_negative} 只")
print(f"  当前池内: {in_pool_count}/{len(CURRENT_CODES)} 只被选中")
print(f"  池外正贡献: {len(not_in_pool_positive)} 只 (建议加入候选)")

# 建议删除的池内ETF (从未被选中或负贡献)
never_selected = [c for c in CURRENT_CODES if c not in etf_stats]
negative_pool = [(c, etf_stats[c]) for c in CURRENT_CODES if c in etf_stats and etf_stats[c]['pnl'] <= 0]
print(f"\n  池内从未被选中: {len(never_selected)} 只: {never_selected}")
print(f"  池内负贡献: {len(negative_pool)} 只:")
for c, s in sorted(negative_pool, key=lambda x: x[1]['pnl']):
    name = name_map.get(c, '未知')
    print(f"    {c} {name}: {s['pnl']:+.1f}% (入选{s['selected']}次)")

# 建议加入的池外ETF
print(f"\n  池外正贡献 Top20 (建议加入):")
for code, name, stats in sorted(not_in_pool_positive, key=lambda x: x[2]['pnl'], reverse=True)[:20]:
    print(f"    {code} {name}: {stats['pnl']:+.1f}% (入选{stats['selected']}次, 胜{stats['wins']}/负{stats['losses']})")

# 保存结果
results = {
    'scan_date': datetime.now().strftime('%Y-%m-%d'),
    'total_etfs': len(all_etf_data),
    'selected_etfs': len(etf_stats),
    'backtest_period': f'{BACKTEST_START} ~ {BACKTEST_END}',
    'rankings': [{
        'code': code,
        'name': name_map.get(code, ''),
        'selected': stats['selected'],
        'pnl': round(stats['pnl'], 2),
        'wins': stats['wins'],
        'losses': stats['losses'],
        'in_pool': code in CURRENT_CODES,
    } for code, stats in ranked],
}
out_path = DATA_DIR.parent / 'etf_172_full_scan.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n结果已保存: {out_path}")
