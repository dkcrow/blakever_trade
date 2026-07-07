"""
七星美股版 大盘指数行情判断
克总需求: 标普500 + 纳指100 都跌破 MA(N) 均线 → 空仓防守
回测 1年/3年/5年, MA周期: 5/10/15/20/25日
"""

import json, sys, os
from pathlib import Path
import numpy as np
import pandas as pd
import warnings; warnings.filterwarnings('ignore')

PROJECT = Path(__file__).parent.parent
DATA_DIR = PROJECT / 'data' / 'storage' / 'stock_data' / 'us'
POOL = ['NVDA','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS',
        'EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB',
        'SPCX','COHR','HOOD','WDC','ARM','STX']
HN = 7
COMM = 0.005
SLIP = 0.0005
SCORE_THRESHOLD = 0.5

def fetch_index_data():
    """用 akshare 获取标普500(.INX)和纳指100(.NDX)历史日线"""
    import akshare as ak
    idx_data = {}
    symbols = {'SPX': '.INX', 'NDX': '.NDX'}
    for name, sym in symbols.items():
        try:
            df = ak.index_us_stock_sina(symbol=sym)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            idx_data[name] = df['close']
            print(f"  {name}({sym}): {len(df)} 条, {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"  {name}({sym}): 获取失败! {e}")
    return idx_data

def load_pool_data():
    """加载26只成分股数据"""
    all_data = {}
    for sym in POOL:
        fp = DATA_DIR / f'{sym}.csv'
        if fp.exists():
            df = pd.read_csv(fp)
            # normalize columns
            rename_map = {}
            for c in df.columns:
                cl = c.lower().strip()
                if cl == 'date' and c != 'date': rename_map[c] = 'date'
                elif cl == 'close' and c != 'close': rename_map[c] = 'close'
            if rename_map:
                df = df.rename(columns=rename_map)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            if len(df) > 35:
                all_data[sym] = df
    return all_data

def get_trade_dates(all_data, start, end):
    """取共同交易日"""
    sets = [set(df.index) for df in all_data.values()]
    dates = sorted(set.union(*sets))
    return [d for d in dates if start <= d.strftime('%Y-%m-%d') <= end]

def calc_score(df_slice):
    """加权对数回归: (exp(slope×250)-1) × R²"""
    x_m = np.arange(len(df_slice))
    y_m = np.log(df_slice.values)
    if len(x_m) < 5: return -99
    w = np.linspace(1, 2, len(x_m))
    try:
        slope, _ = np.polyfit(x_m, y_m, 1, w=w)
    except Exception:
        return -99
    ann = np.exp(slope * 250)
    fitted = slope * x_m + _
    res = y_m - fitted
    ss_res = np.sum(w * res**2)
    ss_tot = np.sum(w * (y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return (ann - 1) * r2

def check_panic(idx_data, date, ma_period):
    """检查两个指数是否都跌破MA"""
    for idx in ['SPX', 'NDX']:
        if idx not in idx_data: return False
        s = idx_data[idx]
        mask = s.index <= date
        hist = s.loc[mask]
        if len(hist) < ma_period: return False
        cur = hist.iloc[-1]
        ma = hist.iloc[-ma_period:].mean()
        if cur >= ma: return False  # 任一指数没跌破 → 不恐慌
    return True  # 两个都跌破 → 恐慌

def check_panic_etf(all_data, current_prices, td, ma_period):
    """检查成分股池中 >80% 是否跌破 MA(ma_period)"""
    total = 0; below = 0
    for sym, df in all_data.items():
        if sym not in current_prices: continue
        mask = df.index <= td
        hist = df.loc[mask, 'close']
        if len(hist) < ma_period: continue
        cur = float(hist.iloc[-1])
        ma = float(hist.iloc[-ma_period:].mean())
        total += 1
        if cur < ma: below += 1
    if total == 0: return False
    return below / total > 0.80

def run_backtest(all_data, idx_data, trade_dates, ma_period, panic_mode='index'):
    """回测单组参数.  panic_mode: 'off' | 'etf' | 'index'."""
    class State:
        def __init__(self): self.cash = 1_000_000; self.positions = {}; self.trade_log = []

    s = State()
    daily_vals = {}
    panic_days = 0

    for i, td in enumerate(trade_dates):
        date_str = td.strftime('%Y-%m-%d')

        # 取有效数据(截至当天)
        current_prices = {}
        for sym, df in all_data.items():
            mask = df.index <= td
            if mask.sum() < 26: continue
            current_prices[sym] = float(df.loc[mask, 'close'].iloc[-1])

        # 恐慌检查
        panic = False
        if panic_mode == 'index':
            panic = check_panic(idx_data, td, ma_period)
        elif panic_mode == 'etf':
            panic = check_panic_etf(all_data, current_prices, td, ma_period)
        # 'off': panic stays False

        if panic:
            panic_days += 1
            # 清仓全部
            for code in list(s.positions.keys()):
                p = current_prices.get(code)
                if not p: continue
                pos = s.positions[code]
                sell_price = p * (1 - SLIP)
                tv = pos['shares'] * sell_price
                comm_cost = max(tv * 0.00005, 1)
                s.cash += tv - comm_cost
                s.trade_log.append({'date': date_str, 'action': 'PANIC_SELL', 'code': code})
                del s.positions[code]
            total = s.cash + sum(pos['shares'] * current_prices.get(c, pos['cost_price']) for c, pos in s.positions.items())
            daily_vals[date_str] = total
            continue

        # 排名与调仓
        scores = []
        for sym in POOL:
            if sym not in current_prices: continue
            df = all_data[sym]
            mask = df.index <= td
            hist = df.loc[mask, 'close']
            if len(hist) < 26: continue
            score = calc_score(hist.iloc[-25:])
            scores.append((sym, score, current_prices[sym]))

        scores.sort(key=lambda x: -x[1])
        targets = [x for x in scores if x[1] >= SCORE_THRESHOLD][:HN]

        # 卖出不在目标中的
        target_codes = {t[0] for t in targets}
        for code in list(s.positions.keys()):
            if code not in target_codes:
                p = current_prices.get(code)
                if not p: continue
                pos = s.positions[code]
                sell_price = p * (1 - SLIP)
                tv = pos['shares'] * sell_price
                comm_cost = max(pos['shares'] * COMM, 1)
                pnl = (sell_price - pos['cost_price']) / pos['cost_price'] * 100
                s.cash += tv - comm_cost
                s.trade_log.append({'date': date_str, 'action': 'SELL', 'code': code, 'pnl_pct': round(pnl, 2)})
                del s.positions[code]

        # 买入新目标(已持有不动)
        new_targets = [t for t in targets if t[0] not in s.positions]
        if new_targets and s.cash > 100:
            available = s.cash * 0.95
            per_stock = available / len(new_targets)
            for sym, score, price in new_targets:
                buy_price = price * (1 + SLIP)
                shares = int(per_stock / buy_price)
                if shares < 1: continue
                cost = shares * buy_price
                comm_cost = max(shares * COMM, 1)
                s.cash -= cost + comm_cost
                s.positions[sym] = {'shares': shares, 'cost_price': buy_price}
                s.trade_log.append({'date': date_str, 'action': 'BUY', 'code': sym})

        total = s.cash
        for code, pos in s.positions.items():
            total += pos['shares'] * current_prices.get(code, pos['cost_price'])
        daily_vals[date_str] = total

    # 计算绩效
    vals = list(daily_vals.values())
    dates = list(daily_vals.keys())
    if len(vals) < 2:
        return {'total_return': 0, 'cagr': 0, 'max_dd': 0, 'sharpe': 0, 'trades': 0, 'win_rate': 0, 'panic_days': panic_days}

    total_ret = (vals[-1] / vals[0] - 1) * 100
    days = len(vals)
    annual_factor = 252 / days if days > 0 else 1
    cagr = ((vals[-1] / vals[0]) ** annual_factor - 1) * 100

    peak = vals[0]
    max_dd = 0
    for v in vals:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd: max_dd = dd
    max_dd = abs(max_dd)

    dr = np.diff(vals) / vals[:-1]
    if len(dr) > 1 and np.std(dr) > 0:
        sharpe = np.mean(dr) / np.std(dr) * np.sqrt(252)
    else:
        sharpe = 0

    sells = [t for t in s.trade_log if t['action'] == 'SELL']
    wins = [t for t in sells if t.get('pnl_pct', 0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0

    return {
        'total_return': round(total_ret, 1),
        'cagr': round(cagr, 1),
        'max_dd': round(max_dd, 1),
        'sharpe': round(sharpe, 2),
        'trades': len(s.trade_log),
        'win_rate': round(wr, 1),
        'panic_days': panic_days
    }

# ================================================================
# 主流程
# ================================================================
print("加载美股成分股数据...")
all_data = load_pool_data()
print(f"  有效: {len(all_data)}/{len(POOL)} 只")

# 获取指数数据
print("\n获取标普500和纳指100指数数据...")
idx_data = fetch_index_data()

if len(idx_data) < 2:
    print("ERROR: 指数数据不足,退出")
    sys.exit(1)

# 回测区间
periods = {
    '1年': ('2025-06-25', '2026-06-25'),
    '3年': ('2023-06-25', '2026-06-25'),
    '5年': ('2021-06-25', '2026-06-25'),
}
results = {}
for pname, (start, end) in periods.items():
    print(f"\n{'='*60}")
    print(f"  {pname}: {start} ~ {end}")
    print(f"{'='*60}")
    dates = get_trade_dates(all_data, start, end)
    print(f"  交易日: {len(dates)}")

    # 1. 关闭
    r0 = run_backtest(all_data, idx_data, dates, 0, 'off')
    results[f"{pname}_off"] = r0
    print(f"  关闭:               累计{r0['total_return']:+.1f}% 年化{r0['cagr']:+.1f}% 回撤-{r0['max_dd']:.1f}% 夏普{r0['sharpe']:.2f}")

    # 2. 成分股ETF 80%跌破5日线
    r_etf = run_backtest(all_data, idx_data, dates, 5, 'etf')
    results[f"{pname}_etf5"] = r_etf
    print(f"  成分股80%·5日:     累计{r_etf['total_return']:+.1f}% 年化{r_etf['cagr']:+.1f}% 回撤-{r_etf['max_dd']:.1f}% 夏普{r_etf['sharpe']:.2f} 恐慌{r_etf['panic_days']}天")

    # 3. 大盘双指数 80%·25日
    r_idx = run_backtest(all_data, idx_data, dates, 25, 'index')
    results[f"{pname}_idx25"] = r_idx
    print(f"  大盘80%·25日:      累计{r_idx['total_return']:+.1f}% 年化{r_idx['cagr']:+.1f}% 回撤-{r_idx['max_dd']:.1f}% 夏普{r_idx['sharpe']:.2f} 恐慌{r_idx['panic_days']}天")

    # 额外: 所有大盘MA参数
    for ma in [5, 10, 15, 20]:
        r = run_backtest(all_data, idx_data, dates, ma, 'index')
        results[f"{pname}_idx{ma}"] = r
        print(f"  大盘80%·{ma:<2}日:      累计{r['total_return']:+.1f}% 年化{r['cagr']:+.1f}% 回撤-{r['max_dd']:.1f}% 夏普{r['sharpe']:.2f} 恐慌{r['panic_days']}天")

# 打印三方对比表
print(f"\n{'='*80}")
print("三方对比: 关闭 vs 成分股80%·5日 vs 大盘80%·25日")
print(f"{'='*80}")

for pname, (start, end) in periods.items():
    print(f"\n[{pname}]")
    print(f"{'配置':<20} {'累计':>9} {'CAGR':>8} {'回撤':>8} {'夏普':>7} {'交易':>6} {'恐慌天':>7}")
    for key, label in [('off', '关闭(无过滤)'), ('etf5', '成分股80%·5日'), ('idx25', '大盘80%·25日')]:
        r = results[f"{pname}_{key}"]
        marker = " ★" if r['total_return'] > results[f"{pname}_off"]['total_return'] and r['max_dd'] < results[f"{pname}_off"]['max_dd'] else ""
        print(f"{label:<20} {r['total_return']:>+8.1f}% {r['cagr']:>7.1f}% {-r['max_dd']:>7.1f}% {r['sharpe']:>6.2f} {r['trades']:>5} {r['panic_days']:>6}{marker}")

print("\n★ = 累计>关闭 且 回撤<关闭")
print("完成!")
