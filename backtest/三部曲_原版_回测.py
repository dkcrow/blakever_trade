#!/usr/bin/env python3
"""三部曲_原版 回测 (聚宽策略移植, 修复版)
修复: ①排除当日收盘价(防未来函数) ②取消score<5截断
核心: 26只ETF, 持仓1只, 加权线性回归动量
"""
import pandas as pd, numpy as np, math, warnings
from pathlib import Path
from datetime import datetime
warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/etf')

# 聚宽代码 → 本地文件名(去掉.XSHG/.XSHE)
JQ_CODES = [
    "513100.XSHG", "159509.XSHE", "513520.XSHG", "513030.XSHG", "518880.XSHG",
    "159985.XSHE", "159981.XSHE", "501018.XSHG", "511260.XSHG", "513130.XSHG",
    "513690.XSHG", "510180.XSHG", "159915.XSHE", "510410.XSHG", "515650.XSHG",
    "588120.XSHG", "159851.XSHE", "159637.XSHE", "516160.XSHG", "159550.XSHE",
    "515250.XSHG", "159378.XSHE", "516510.XSHG", "515050.XSHG", "515000.XSHG",
    "159529.XSHE"
]

STOCK_SUM = 1
M_DAYS = 25
SCORE_UPPER = 999  # 已取消截断(原版=5, 修复后=999)
CASH = 100000
COMM = 0.0003  # 佣金
TAX = 0.001    # 印花税(卖出)
SLIPPAGE = 0.0001  # ETF滑点

# 加载数据: 聚宽代码 "513100.XSHG" → 本地 "513100.csv"
etf_data = {}
for jq_code in JQ_CODES:
    local_code = jq_code.split('.')[0]
    fp = DATA_DIR / f'{local_code}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 30:
            etf_data[jq_code] = df

print(f'Loaded {len(etf_data)} ETFs')

# 确定区间
START = '2023-06-08'; END = '2026-06-05'
trade_dates = sorted(set().union(*[set(df.index) for df in etf_data.values()]))
trade_dates = [d for d in trade_dates if START <= d.strftime('%Y-%m-%d') <= END]
print(f'区间: {trade_dates[0].date()} ~ {trade_dates[-1].date()}, {len(trade_dates)}天')

def calc_score(prices):
    """三部曲加权回归评分: 权重linspace(1,2), score=年化×R², 上限截断"""
    y = np.log(prices)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    
    slope, intercept = np.polyfit(x, y, 1, w=weights)
    ann_ret = math.exp(slope * 250) - 1
    fitted = slope * x + intercept
    ss_res = np.sum(weights * (y - fitted)**2)
    ss_tot = np.sum(weights * (y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0
    score = ann_ret * r2
    return score, ann_ret, r2

class Portfolio:
    def __init__(self, cash=CASH):
        self.cash = cash; self.positions = {}; self.trades = []
        self.daily_values = []
    
    def buy(self, code, shares, price, date, reason=''):
        price_adj = price * (1 + SLIPPAGE)
        tv = shares * price_adj; comm_fee = max(tv * COMM, 5)
        total = tv + comm_fee
        if total > self.cash: return False
        self.cash -= total
        self.positions[code] = {'shares': shares, 'cost': price_adj, 'buy_date': date}
        self.trades.append({'date': date, 'action': 'BUY', 'code': code, 'shares': shares,
                          'price': price_adj, 'reason': reason})
        return True
    
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        price_adj = price * (1 - SLIPPAGE)
        pos = self.positions[code]; actual = min(shares, pos['shares'])
        tv = actual * price_adj
        comm_fee = max(tv * COMM, 5); tax = tv * TAX
        self.cash += tv - comm_fee - tax
        pnl = (price_adj - pos['cost']) / pos['cost'] * 100
        self.trades.append({'date': date, 'action': 'SELL', 'code': code, 'shares': actual,
                          'price': price_adj, 'pnl_pct': pnl, 'reason': reason})
        if actual >= pos['shares']: del self.positions[code]
        else: self.positions[code]['shares'] -= actual
        return True
    
    def total_value(self, prices):
        pv = sum(p['shares'] * prices.get(c, p['cost']) for c, p in self.positions.items())
        return self.cash + pv

pf = Portfolio()

for i, date in enumerate(trade_dates):
    d_str = date.strftime('%Y-%m-%d')
    
    # 当日价格
    prices = {}
    for code in etf_data:
        m = etf_data[code].index == date
        if m.any():
            prices[code] = float(etf_data[code].loc[date, 'close'])
    if not prices: continue
    
    # 计算排名: 仅用前一日及之前的数据(修复: 排除当日收盘价, 防未来函数)
    data = []
    for code in etf_data:
        if code not in prices: continue
        mask = etf_data[code].index < pd.Timestamp(date)
        hist = etf_data[code][mask]
        if len(hist) < M_DAYS: continue
        
        # 修复: 仅用历史收盘价, 不附加当日
        hist_prices = hist['close'].values[-M_DAYS:].copy()
        
        if np.any(hist_prices <= 0): continue
        if np.allclose(np.log(hist_prices), np.log(hist_prices[0])): continue
        
        score, ann_ret, r2 = calc_score(hist_prices)
        # 修复: 取消score<5截断, 仅过滤score<=0
        if score > 0:
            data.append({'code': code, 'score': score, 'ann': ann_ret, 'r2': r2, 'price': prices[code]})
    
    data.sort(key=lambda x: x['score'], reverse=True)
    
    if not data: continue
    
    target = data[0]['code']
    current_holds = list(pf.positions.keys())
    
    # 卖出不在目标中的
    for code in current_holds[:]:
        if code != target:
            sp = prices.get(code)
            if not sp or sp <= 0: continue
            pf.sell(code, pf.positions[code]['shares'], sp, d_str, f'切换到{target}')
    
    # 买入目标（如果未持有）
    if target not in pf.positions:
        per_stock = pf.total_value(prices) / STOCK_SUM
        shares = int(per_stock / prices[target])
        shares = (shares // 100) * 100  # 聚宽A股100股整数倍
        if shares > 0:
            pf.buy(target, shares, prices[target], d_str, '动量轮换')
    
    pf.daily_values.append({'date': d_str, 'value': pf.total_value(prices)})

# 汇总
dv = pd.DataFrame(pf.daily_values)
total_ret = (dv['value'].iloc[-1] / CASH - 1) * 100
daily_ret = dv['value'].pct_change().dropna()
ann_ret = (1 + daily_ret.mean())**252 - 1
mdd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0
wins = sum(1 for t in pf.trades if t['action'] == 'SELL' and t.get('pnl_pct', 0) > 0)
losses = sum(1 for t in pf.trades if t['action'] == 'SELL' and t.get('pnl_pct', 0) <= 0)
wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

print(f'\n{"="*60}')
print(f'  三部曲_原版 近3年回测 ({trade_dates[0].date()} ~ {trade_dates[-1].date()})')
print(f'{"="*60}')
print(f'  累计收益: {total_ret:+.2f}%')
print(f'  年化收益: {ann_ret*100:.1f}%')
print(f'  最大回撤: {mdd:.1f}%')
print(f'  夏普比率: {sharpe:.2f}')
print(f'  交易次数: {len(pf.trades)} (买{sum(1 for t in pf.trades if t["action"]=="BUY")}/卖{sum(1 for t in pf.trades if t["action"]=="SELL")})')
print(f'  胜率: {wr:.1f}%')

# 交易明细
print(f'\n=== 最近10笔交易 ===')
for t in pf.trades[-10:]:
    pnl = t.get('pnl_pct', 0)
    pnl_s = f'{pnl:+.2f}%' if t['action'] == 'SELL' else '-'
    print(f'  {t["date"]} {t["action"]:4s} {t["code"]:15s} {t["shares"]:>6}股  @{t["price"]:.4f}  {pnl_s:>8s}  {t["reason"]}')

# 按年统计
print(f'\n=== 年度收益 ===')
for year in range(2023, 2027):
    yd = dv[dv['date'].str.startswith(str(year))]
    if len(yd) < 2: continue
    y_ret = (yd['value'].iloc[-1] / yd['value'].iloc[0] - 1) * 100
    print(f'  {year}: {y_ret:+.2f}% ({len(yd)}天)')

# 分析score分布(修复后无截断)
all_scores = []
for date in trade_dates[:5]:  # 仅采样5天分析
    d_str = date.strftime('%Y-%m-%d')
    for code in etf_data:
        mask = etf_data[code].index < pd.Timestamp(date)
        hist = etf_data[code][mask]
        if len(hist) < M_DAYS: continue
        hp = hist['close'].values[-M_DAYS:].copy()
        if np.any(hp <= 0): continue
        s, a, r = calc_score(hp)
        all_scores.append(s)

if all_scores:
    all_scores = np.array(all_scores)
    above5 = np.sum(all_scores >= 5)
    below0 = np.sum(all_scores <= 0)
    valid = np.sum(all_scores > 0)
    print(f'\n=== Score分布 (修复后无截断) ===')
    print(f'  score>=5(原版被过滤): {above5}/{len(all_scores)} ({above5/len(all_scores)*100:.1f}%)')
    print(f'  score<=0(被过滤): {below0}/{len(all_scores)} ({below0/len(all_scores)*100:.1f}%)')
    print(f'  score>0(有效): {valid}/{len(all_scores)} ({valid/len(all_scores)*100:.1f}%)')
    print(f'  均值: {np.mean(all_scores):.4f}, 中位数: {np.median(all_scores):.4f}, 最大: {np.max(all_scores):.4f}')

print(f'\nDone.')
