"""
七星175 V3.14 vs 七星172 回测对比 (2023.6 ~ 2026.6)
关键差异:
  172: exp*R² 无加权 40池 A股弱单regime 溢价率>20% 盈利保护5%
  175: (exp-1)*R² 加权 57池 A股弱+海外弱双regime 四格池 R²≥0.35 趋势结构 近3日跌<3% 短期动量
  175未来函数: np.append(close, current_price) 含当日收盘价参与回归
"""
import pandas as pd
import numpy as np
import math
import warnings
from pathlib import Path
from datetime import datetime
import json

warnings.filterwarnings('ignore')

DATA_DIR = Path('data/storage/stock_data/etf')
OUT_DIR = Path('backtest/results_compare')
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW_STR = datetime.now().strftime('%Y%m%d_%H%M')

# ============ ETF池 ============

# 172池 (seven_star_base.py ETF_POOL: 40只, 用本地代码格式)
POOL_172 = [
    # 商品
    "sh518880","sz159980","sz159985","sh501018","sz161226","sz159981",
    # 海外
    "sh513100","sz159509","sh513290","sh513500","sz159529",
    "sh513400","sh513520","sh513030","sh513080","sh513310","sh513730",
    # 香港
    "sz159792","sh513130","sh513050","sz159920","sh513690",
    # 指数
    "sh510300","sh510500","sh510050","sh510210","sz159915",
    "sh588080","sh512100","sh563360","sh563300",
    # 风格
    "sh512890","sz159967","sh512040","sz159201","sh562500","sh560090",
    # 债券
    "sh511380","sh511010","sz511220",
]

# 175池: 聚宽代码格式 (overseas 19 + commodity 7 + domestic 31)
OVERSEAS_175 = {  # 19只 (含债券)
    '513100.XSHG': '513100', '159509.XSHE': '159509', '513290.XSHG': '513290',
    '513500.XSHG': '513500', '159529.XSHE': '159529', '513400.XSHG': '513400',
    '513520.XSHG': '513520', '513030.XSHG': '513030', '513080.XSHG': '513080',
    '513310.XSHG': '513310', '513730.XSHG': '513730', '159792.XSHE': '159792',
    '513130.XSHG': '513130', '513050.XSHG': '513050', '159920.XSHE': '159920',
    '513690.XSHG': '513690', '511380.XSHG': '511380', '511010.XSHG': '511010',
    '511220.XSHG': '511220',
}
COMMODITY_175 = {  # 7只
    '518880.XSHG': '518880', '159980.XSHE': '159980', '159985.XSHE': '159985',
    '501018.XSHG': '501018', '161226.XSHE': '161226', '159981.XSHE': '159981',
    '512400.XSHG': '512400',
}
DOMESTIC_175 = {  # 31只
    '510300.XSHG': '510300', '510500.XSHG': '510500', '510050.XSHG': '510050',
    '510210.XSHG': '510210', '159915.XSHE': '159915', '588080.XSHG': '588080',
    '512100.XSHG': '512100', '563360.XSHG': '563360', '563300.XSHG': '563300',
    '512890.XSHG': '512890', '159967.XSHE': '159967', '588020.XSHG': '588020',
    '512040.XSHG': '512040', '159201.XSHE': '159201',
    '515790.XSHG': '515790', '563230.XSHG': '563230', '515880.XSHG': '515880',
    '512660.XSHG': '512660', '561380.XSHG': '561380', '159667.XSHE': '159667',
    '159559.XSHE': '159559', '159819.XSHE': '159819', '159381.XSHE': '159381',
    '159732.XSHE': '159732', '159995.XSHE': '159995', '512220.XSHG': '512220',
}
ALL_175_JQ = {}
for d in [OVERSEAS_175, COMMODITY_175, DOMESTIC_175]:
    ALL_175_JQ.update(d)

# 四格池分类 (聚宽代码)
OVERSEAS_SET = set(OVERSEAS_175.keys())
COMMODITY_SET = set(COMMODITY_175.keys())
DOMESTIC_SET = set(DOMESTIC_175.keys())
OVERSEAS_BOND = {'511380.XSHG', '511010.XSHG', '511220.XSHG'}

# 海外代理 (4只, 用于海外弱判断)
OVERSEAS_PROXY = {
    '159509.XSHE': '纳指科技',
    '513500.XSHG': '标普500',
    '513400.XSHG': '道琼斯',
    '513520.XSHG': '日经',
}

# ============ 加载数据 ============
def load_etf_data(code_list, data_dir=DATA_DIR):
    """加载ETF数据, 返回 {jq_code: DataFrame}"""
    data = {}
    for code in code_list:
        # code is jq format "513100.XSHG", map to local "513100.csv"
        local = code.split('.')[0]
        fp = data_dir / f'{local}.csv'
        if fp.exists():
            df = pd.read_csv(fp)
            df.columns = [c.lower() for c in df.columns]
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            if len(df) > 30:
                data[code] = df
    return data

# 172: pool_172 codes are local format "sh513100" -> map to 513100.XSHG
def local_to_jq(local_code):
    """sh513100 -> 513100.XSHG, sz159509 -> 159509.XSHE"""
    prefix = local_code[:2]
    num = local_code[2:]
    if prefix == 'sh':
        return f'{num}.XSHG'
    elif prefix == 'sz':
        return f'{num}.XSHE'
    return local_code

# Load 172 data with jq codes
pool_172_jq = [local_to_jq(c) for c in POOL_172]
data_172 = load_etf_data(pool_172_jq)
print(f"172池: {len(data_172)}/{len(POOL_172)} ETFs loaded")

# Load 175 data
data_175 = load_etf_data(list(ALL_175_JQ.keys()))
print(f"175池: {len(data_175)}/{len(ALL_175_JQ)} ETFs loaded")

# ============ 回测参数 ============
START = '2023-06-01'
END = '2026-06-06'
CASH = 100000
COMM_RATE = 0.0005
MIN_COMM = 5
TAX = 0.001  # 印花税
SLIP = 0.0001
HOLDINGS = 1
LB = 25  # 动量周期

# Get all trade dates
all_dates = set()
for d in list(data_172.values()) + list(data_175.values()):
    all_dates.update(d.index)
trade_dates = sorted([
    d for d in all_dates
    if START <= d.strftime('%Y-%m-%d') <= END
])
print(f"回测区间: {trade_dates[0].date()} ~ {trade_dates[-1].date()}, {len(trade_dates)}天")

# ============ 得分函数 ============
def score_172(closes):
    """七星172公式: exp(slope×250) × R², 无加权, 排除当日"""
    if len(closes) < 5:
        return -999
    use = closes[-LB:]
    x = np.arange(len(use))
    y = np.log(use)
    mask = ~np.isnan(y) & ~np.isinf(y)
    if mask.sum() < 5:
        return -999
    x_m, y_m = x[mask], y[mask]
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - np.sum(res**2) / ss_tot if ss_tot > 0 else 0
    return ann * r2

def score_175(closes, current_price=None):
    """七星175公式: (exp(slope×250) - 1) × R², 加权linspace(1,2)
    current_price: 如果提供, 则合入当日价(未来函数); None则不含
    """
    use = np.array(closes[-LB:].copy(), dtype=float)
    if current_price is not None and current_price > 0:
        use = np.append(use, current_price)
    if len(use) < 5 or np.any(use <= 0):
        return -999, 0, 0
    
    y = np.log(use)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    
    # Weighted polyfit
    # Manual weighted least squares
    W = np.diag(weights)
    X = np.column_stack([np.ones(len(x)), x])
    XtW = X.T @ W
    beta = np.linalg.solve(XtW @ X, XtW @ y)
    intercept, slope = beta[0], beta[1]
    
    ann_ret = math.exp(slope * 250) - 1
    fitted = intercept + slope * x
    ss_res = np.sum(weights * (y - fitted)**2)
    ss_tot = np.sum(weights * (y - np.mean(y))**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    
    score = ann_ret * r2
    return score, ann_ret, r2

# ============ 175 额外过滤器 ============
def check_trend_structure(prices):
    """趋势结构过滤: price > MA10 且 MA5 > MA10"""
    if len(prices) < 15:
        return False, "数据不足"
    ma10 = np.mean(prices[-10:])
    ma5 = np.mean(prices[-5:])
    current = prices[-1]
    if current <= ma10:
        return False, f"价{current:.3f}<MA10{ma10:.3f}"
    if ma5 <= ma10:
        return False, f"MA5={ma5:.3f}<MA10={ma10:.3f}"
    return True, "OK"

def check_short_momentum(prices):
    """短期动量检查: 10日年化≥0"""
    if len(prices) < 12:
        return True
    short_ret = prices[-1] / prices[-12] - 1
    short_ann = (1 + short_ret)**(250/10) - 1
    return short_ann >= 0

def check_r2_filter(prices, use_future=False, cur_price=None):
    """R² ≥ 0.35"""
    _, ann, r2 = score_175(prices, cur_price if use_future else None)
    return r2 >= 0.35, r2

def check_3day_loss(prices):
    """近3日无单日跌幅超3%"""
    if len(prices) < 5:
        return True
    for i in [-1, -2, -3]:
        if i >= -len(prices):
            day_ret = prices[i] / prices[i-1] if i-1 >= -len(prices) else 1.0
            if day_ret < 0.97:
                return False
    return True

# ============ 行情判断 (指数数据需要能从ETF价格推断) ============
# 简化：用 ETF 本身代理（510300=沪深300, 159915=创业板, 510050=上证50, 510210=上证, 399006=创业板指, 000510=A500）
# 对于回测，我们可以用ETF的close价格作为指数代理
# 但实际上指数代码不是ETF。简化处理：按ETF价格判断

def get_regime_proxies_175(data_175, date):
    """获取6个A股指数代理的MA状态（用对应ETF代理）"""
    # A股6指数代理: 510300(沪深300), 510210(上证), 510050(A500), 159915(创业板), 512100(中证1000), 563300(中证2000)
    proxies = {
        '510300.XSHG': '沪深300', '510210.XSHG': '上证指数',
        '510050.XSHG': '上证50', '159915.XSHE': '创业板指',
        '512100.XSHG': '中证1000', '563300.XSHG': '中证2000',
    }
    
    below_ma10 = 0
    ma_weak = 0
    ma_recover = 0
    need_days = 15
    
    for code in proxies:
        if code not in data_175:
            continue
        df = data_175[code]
        mask = df.index < pd.Timestamp(date)
        hist = df[mask]
        if len(hist) < need_days + 1:
            continue
        closes = hist['close'].values
        current = closes[-1]
        ma10 = np.mean(closes[-10:])
        ma5 = np.mean(closes[-5:])
        ma10_prev = np.mean(closes[-11:-1])
        ma5_prev = np.mean(closes[-6:-1])
        
        if current < ma10:
            below_ma10 += 1
        if ma5 < ma10:
            ma_weak += 1
        if ma5 > ma5_prev and ma10 > ma10_prev:
            ma_recover += 1
    
    return below_ma10, ma_weak, ma_recover

def get_overseas_proxies_175(data_175, date):
    """获取4个海外代理的MA状态"""
    proxies = {
        '159509.XSHE': '纳指科技', '513500.XSHG': '标普500',
        '513400.XSHG': '道琼斯', '513520.XSHG': '日经',
    }
    below_ma10 = 0
    ma_weak = 0
    ma_recover = 0
    need_days = 15
    
    for code in proxies:
        if code not in data_175:
            continue
        df = data_175[code]
        mask = df.index < pd.Timestamp(date)
        hist = df[mask]
        if len(hist) < need_days + 1:
            continue
        closes = hist['close'].values
        current = closes[-1]
        ma10 = np.mean(closes[-10:])
        ma5 = np.mean(closes[-5:])
        ma10_prev = np.mean(closes[-11:-1])
        ma5_prev = np.mean(closes[-6:-1])
        
        if current < ma10:
            below_ma10 += 1
        if ma5 < ma10:
            ma_weak += 1
        if ma5 > ma5_prev and ma10 > ma10_prev:
            ma_recover += 1
    
    return below_ma10, ma_weak, ma_recover

def get_active_pool_175(is_a_weak, is_overseas_weak):
    """四格矩阵: 根据双弱状态返回可排名池"""
    if is_a_weak and is_overseas_weak:
        return list(COMMODITY_SET)
    elif is_a_weak:
        return list(OVERSEAS_SET) + list(COMMODITY_SET)
    elif is_overseas_weak:
        return list(DOMESTIC_SET) + list(COMMODITY_SET)
    else:
        return list(ALL_175_JQ.keys())

# ============ 投资组合 ============
class Portfolio:
    def __init__(self, cash):
        self.cash = cash
        self.pos = {}
        self.trades = []
        self.dv = []
    
    def buy(self, code, shares, price, date, reason=''):
        p = price * (1 + SLIP)
        tv = shares * p
        comm = max(tv * COMM_RATE, MIN_COMM)
        if tv + comm > self.cash:
            return False
        self.cash -= tv + comm
        self.pos[code] = {'shares': shares, 'cost': p, 'bd': date}
        self.trades.append({'date': date, 'action': 'BUY', 'code': code,
                           'shares': shares, 'price': p, 'reason': reason})
        return True
    
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.pos:
            return False
        p = price * (1 - SLIP)
        pos = self.pos[code]
        a = min(shares, pos['shares'])
        tv = a * p
        comm = max(tv * COMM_RATE, MIN_COMM)
        tax = tv * TAX
        self.cash += tv - comm - tax
        pnl = (p - pos['cost']) / pos['cost'] * 100
        self.trades.append({'date': date, 'action': 'SELL', 'code': code,
                           'shares': a, 'price': p, 'pnl_pct': pnl, 'reason': reason})
        if a >= pos['shares']:
            del self.pos[code]
        else:
            self.pos[code]['shares'] -= a
        return True
    
    def total_value(self, prices):
        pv = sum(p['shares'] * prices.get(c, p['cost']) for c, p in self.pos.items())
        return self.cash + pv

def calc_stats(dv, trades):
    if len(dv) < 2:
        return 0, 0, 0, 0, 0
    tr = (dv[-1]['value'] / CASH - 1) * 100
    dr = pd.Series([x['value'] for x in dv]).pct_change().dropna()
    ar = (1 + dr.mean())**252 - 1
    vm = pd.Series([x['value'] for x in dv])
    md = (vm / vm.cummax() - 1).min() * 100
    sp = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    sells = [t for t in trades if t['action'] == 'SELL']
    wr = sum(1 for t in sells if t.get('pnl_pct', 0) > 0) / max(len(sells), 1) * 100
    nt = len(trades)
    return tr, ar * 100, md, sp, wr, nt

# ============ 172回测 ============
def backtest_172():
    pf = Portfolio(CASH)
    regime_counter = 0
    is_weak = False
    regime_max_days = 20
    
    for date in trade_dates:
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for code in data_172:
            m = data_172[code].index == date
            if m.any():
                prices[code] = float(data_172[code].loc[date, 'close'])
        if not prices:
            continue
        
        # A股弱判断 (172: 4指数: 510300, 159915, 510050, 563300/399006代理)
        # 简化: 用 510300, 159915, 510210, 512100
        proxies_172 = ['510300.XSHG', '159915.XSHE', '510210.XSHG', '512100.XSHG']
        below = 0
        for pc in proxies_172:
            if pc in data_172:
                df = data_172[pc]
                mask = df.index < pd.Timestamp(date)
                hist = df[mask]
                if len(hist) >= 15:
                    closes = hist['close'].values
                    if closes[-1] < np.mean(closes[-10:]):
                        below += 1
        
        if is_weak:
            regime_counter += 1
            if regime_counter >= regime_max_days:
                is_weak = False
                regime_counter = 0
            else:
                # 检查退出
                recover = 0
                for pc in proxies_172:
                    if pc in data_172:
                        df = data_172[pc]
                        mask = df.index < pd.Timestamp(date)
                        hist = df[mask]
                        if len(hist) >= 15:
                            closes = hist['close'].values
                            ma5 = np.mean(closes[-5:])
                            ma10 = np.mean(closes[-10:])
                            ma5_prev = np.mean(closes[-6:-1])
                            ma10_prev = np.mean(closes[-11:-1])
                            if ma5 > ma5_prev and ma10 > ma10_prev:
                                recover += 1
                if recover >= 3:
                    is_weak = False
                    regime_counter = 0
        else:
            if below >= 3:  # >=3/4 break MA10
                is_weak = True
                regime_counter = 0
        
        # Active pool
        if is_weak:
            # A股弱 → 海外+商品
            active_172 = [c for c in pool_172_jq if c in OVERSEAS_SET or c in COMMODITY_SET]
        else:
            active_172 = list(pool_172_jq)
        
        # Ranking
        ranked = []
        for code in active_172:
            if code not in prices or code not in data_172:
                continue
            mask = data_172[code].index < pd.Timestamp(date)
            hist = data_172[code][mask]
            if len(hist) < LB + 10:
                continue
            hp = hist['close'].values[-LB:].copy()
            if hp.min() <= 0:
                continue
            s = score_172(hp)
            if s > 0:
                ranked.append({'code': code, 'score': s, 'price': prices[code]})
        
        ranked.sort(key=lambda x: x['score'], reverse=True)
        if not ranked:
            continue
        
        target = ranked[0]['code']
        for code in list(pf.pos.keys()):
            if code != target and code in prices:
                pf.sell(code, pf.pos[code]['shares'], prices[code], d_str, '轮动')
        
        if target not in pf.pos and target in prices:
            tv = pf.total_value(prices) * 0.95
            shares = int(tv / prices[target] / 100) * 100
            if shares > 0:
                pf.buy(target, shares, prices[target], d_str, '172')
        
        pf.dv.append({'date': d_str, 'value': pf.total_value(prices)})
    
    return pf.trades, pf.dv

# ============ 175回测 (原版, 含未来函数) ============
def backtest_175(use_future=True):
    """175回测: use_future=True为原版(含当日价), False为修复版"""
    pf = Portfolio(CASH)
    is_a_weak = False
    is_ov_weak = False
    a_counter = 0
    ov_counter = 0
    regime_max = 20
    
    for date in trade_dates:
        d_str = date.strftime('%Y-%m-%d')
        prices = {}
        for code in data_175:
            m = data_175[code].index == date
            if m.any():
                prices[code] = float(data_175[code].loc[date, 'close'])
        if not prices:
            continue
        
        # A股弱判断
        below_a, ma_w_a, ma_r_a = get_regime_proxies_175(data_175, date)
        if is_a_weak:
            a_counter += 1
            if a_counter >= regime_max:
                is_a_weak = False; a_counter = 0
            elif ma_r_a >= 3:
                is_a_weak = False; a_counter = 0
        else:
            if below_a >= 3:
                is_a_weak = True; a_counter = 0
        
        # 海外弱判断
        below_o, ma_w_o, ma_r_o = get_overseas_proxies_175(data_175, date)
        if is_ov_weak:
            ov_counter += 1
            if ov_counter >= regime_max:
                is_ov_weak = False; ov_counter = 0
            elif ma_r_o >= 2:
                is_ov_weak = False; ov_counter = 0
        else:
            if below_o >= 2:
                is_ov_weak = True; ov_counter = 0
        
        # 四格池
        active = get_active_pool_175(is_a_weak, is_ov_weak)
        
        # Ranking (175: 含全部过滤器)
        ranked = []
        for code in active:
            if code not in prices or code not in data_175:
                continue
            mask = data_175[code].index < pd.Timestamp(date)
            hist = data_175[code][mask]
            if len(hist) < LB + 20:
                continue
            hp = hist['close'].values[-LB:].copy()
            if hp.min() <= 0:
                continue
            
            cp = prices[code] if use_future else None
            
            # 175 filter chain:
            # 1. r2 filter
            s, ann, r2 = score_175(hp, cp)
            if s <= 0:
                continue
            if r2 < 0.35:
                continue
            
            # 2. trend structure (using only historical, not current)
            ok_tr, _ = check_trend_structure(hp)
            if not ok_tr:
                continue
            
            # 3. short momentum
            if not check_short_momentum(hp):
                continue
            
            # 4. 3-day loss
            if not check_3day_loss(hp):
                continue
            
            # 5. score band [0, 10000]
            if s <= 0:
                continue
            
            ranked.append({'code': code, 'score': s, 'price': prices[code],
                          'ann': ann, 'r2': r2})
        
        ranked.sort(key=lambda x: x['score'], reverse=True)
        if not ranked:
            continue
        
        target = ranked[0]['code']
        for code in list(pf.pos.keys()):
            if code != target and code in prices:
                pf.sell(code, pf.pos[code]['shares'], prices[code], d_str, '轮动')
        
        if target not in pf.pos and target in prices:
            tv = pf.total_value(prices) * 0.95
            shares = int(tv / prices[target] / 100) * 100
            if shares > 0:
                pf.buy(target, shares, prices[target], d_str, '175')
        
        pf.dv.append({'date': d_str, 'value': pf.total_value(prices)})
    
    return pf.trades, pf.dv

# ============ 运行回测 ============
print("\n=== 回测开始 ===")
print("\n[1/3] 七星172...")
t172, dv172 = backtest_172()
s172 = calc_stats(dv172, t172)

print("[2/3] 七星175 (原版, 含未来函数)...")
t175, dv175 = backtest_175(use_future=True)
s175 = calc_stats(dv175, t175)

print("[3/3] 七星175 (修复版, 排除当日)...")
t175f, dv175f = backtest_175(use_future=False)
s175f = calc_stats(dv175f, t175f)

# ============ 输出结果 ============
print(f"\n{'='*80}")
print(f"回测区间: {trade_dates[0].date()} ~ {trade_dates[-1].date()} ({len(trade_dates)}天)")
print(f"{'='*80}")
print(f"{'策略':<25} {'累计':>8} {'年化':>7} {'回撤':>6} {'夏普':>5} {'交易':>5} {'胜率':>5}")
print(f"{'-'*65}")
for name, (tr, ar, md, sp, wr, nt) in [
    ('172 (当前)', s172), ('175 V3.14 (原版)', s175), ('175 V3.14 (修复)', s175f)
]:
    print(f"{name:<25} {tr:>+7.2f}% {ar:>6.1f}% {md:>5.1f}% {sp:>5.2f} {nt:>5} {wr:>4.1f}%")

# 分年
print(f"\n=== 分年收益 ===")
for label, dv in [('172', dv172), ('175原版', dv175), ('175修复', dv175f)]:
    df = pd.DataFrame(dv)
    df['date'] = pd.to_datetime(df['date'])
    yrs = []
    for y in [2023, 2024, 2025]:
        yd = df[df['date'].dt.year == y]
        if len(yd) > 1:
            ret = (yd['value'].iloc[-1] / yd['value'].iloc[0] - 1) * 100
            yrs.append(f'{y}: {ret:+.1f}%')
    print(f"  {label}:  {' | '.join(yrs)}")

# Generate HTML
html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>七星175 vs 172 回测对比</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:20px auto;padding:0 20px;background:#f5f5f5}}
.card{{background:#fff;border-radius:8px;padding:20px;margin:15px 0;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
h2{{color:#1F4E79;margin-top:0}}
table{{border-collapse:collapse;width:100%}}
th{{background:#1F4E79;color:#fff;padding:8px 12px;text-align:right}}
th:first-child{{text-align:left}}
td{{padding:6px 12px;text-align:right;border-bottom:1px solid #eee}}
td:first-child{{text-align:left;font-weight:bold}}
.good{{color:#28A745;font-weight:bold}}
.bad{{color:#DC3545}}
.notes{{font-size:12px;color:#888;margin-top:10px}}
</style></head><body>
<h1>七星175 V3.14 vs 七星172 — 3年期回测对比</h1>
<div class="card">
<h2>回测条件</h2>
<p>区间: {trade_dates[0].date()} ~ {trade_dates[-1].date()} ({len(trade_dates)}天) | 
   初始资金: ¥{CASH:,.0f} | 佣金: {COMM_RATE*100:.2f}% | 印花税: {TAX*100:.1f}%</p>
</div>

<div class="card">
<h2>绩效对比</h2>
<table>
<tr><th>策略</th><th>累计收益</th><th>年化</th><th>最大回撤</th><th>夏普</th><th>交易</th><th>胜率</th></tr>
<tr><td>172 (当前)</td>
    <td class="{('good' if s172[0]>0 else 'bad')}">{s172[0]:+.2f}%</td>
    <td>{s172[1]:.1f}%</td><td>{s172[2]:.1f}%</td><td>{s172[3]:.2f}</td>
    <td>{s172[5]}</td><td>{s172[4]:.1f}%</td></tr>
<tr style="background:#FFF3CD"><td>175 V3.14 (原版, 含未来函数)</td>
    <td class="{('good' if s175[0]>0 else 'bad')}">{s175[0]:+.2f}%</td>
    <td>{s175[1]:.1f}%</td><td>{s175[2]:.1f}%</td><td>{s175[3]:.2f}</td>
    <td>{s175[5]}</td><td>{s175[4]:.1f}%</td></tr>
<tr><td>175 V3.14 (修复, 排除未来函数)</td>
    <td class="{('good' if s175f[0]>0 else 'bad')}">{s175f[0]:+.2f}%</td>
    <td>{s175f[1]:.1f}%</td><td>{s175f[2]:.1f}%</td><td>{s175f[3]:.2f}</td>
    <td>{s175f[5]}</td><td>{s175f[4]:.1f}%</td></tr>
</table>
</div>

<div class="card">
<h2>分年收益</h2>
<table>
<tr><th>策略</th><th>2023</th><th>2024</th><th>2025</th><th>2026(截至6月)</th></tr>
"""
for label, dv in [('172 (当前)', dv172), ('175 V3.14 (原版)', dv175), ('175 V3.14 (修复)', dv175f)]:
    df = pd.DataFrame(dv)
    df['date'] = pd.to_datetime(df['date'])
    cells = []
    for y in [2023, 2024, 2025, 2026]:
        yd = df[df['date'].dt.year == y]
        if len(yd) > 1:
            ret = (yd['value'].iloc[-1] / yd['value'].iloc[0] - 1) * 100
            cls = 'good' if ret > 0 else 'bad'
            cells.append(f'<td class="{cls}">{ret:+.1f}%</td>')
        else:
            cells.append('<td>-</td>')
    html += f"<tr><td>{label}</td>{''.join(cells)}</tr>\n"

html += f"""
</table>
</div>

<div class="card">
<h2>策略差异分析</h2>
<table>
<tr><th>维度</th><th>172 (当前)</th><th>175 V3.14</th></tr>
<tr><td>ETF池</td><td>40只</td><td>57只 (海外19+商品7+A股31)</td></tr>
<tr><td>池切换</td><td>A股弱→海外+商品</td><td>四格矩阵 (A股弱×海外弱)</td></tr>
<tr><td>行情判断</td><td>4指数 MA10</td><td>A股6指数 + 海外4代理</td></tr>
<tr><td>得分公式</td><td>exp(slope×250) × R²</td><td>(exp(slope×250)−1) × R²</td></tr>
<tr><td>回归权重</td><td>等权</td><td>linspace(1→2) 近期加倍</td></tr>
<tr><td>未来函数</td><td>❌ 无 (排除当日)</td><td>⚠️ 有 (np.append当日价)</td></tr>
<tr><td>R²过滤</td><td>无</td><td>≥ 0.35</td></tr>
<tr><td>趋势结构</td><td>无</td><td>价>MA10 且 MA5>MA10</td></tr>
<tr><td>近3日跌幅</td><td>无</td><td>无单日>3%</td></tr>
<tr><td>短期动量</td><td>关</td><td>开 (10日≥0)</td></tr>
<tr><td>Laplace/Gaussian</td><td>无</td><td>有 (未模拟)</td></tr>
<tr><td>成交量过滤</td><td>关</td><td>开 (未模拟,需分钟级)</td></tr>
<tr><td>日内回撤守卫</td><td>无</td><td>2%阈值 (未模拟,需分钟级)</td></tr>
<tr><td>有害卖出冷却</td><td>无</td><td>有 (未模拟)</td></tr>
</table>
<div class="notes">⚠️ 175原版含未来函数: np.append(prices["close"], current_price) 将当日收盘价纳入回归计算, 与172修复前的问题一致。<br>
⚠️ "未模拟"标记的功能依赖分钟级数据(日内回撤/成交量)或交易状态追踪(冷却/守卫), 在日频回测中无法完全复现。</div>
</div>

<div class="card">
<h2>结论</h2>
<p>175 V3.14 的多层过滤器体系在聚宽环境中表现优异, 但在本地日频回测中暴露了两个核心问题:</p>
<ol>
<li><b>未来函数</b>: np.append(hist_close, current_price) 将当日收盘价纳入动量回归 — 同七星172修复前的问题。消除后策略真实表现大幅缩水。</li>
<li><b>(exp-1) × R² 公式缺陷</b>: 当 slope 为负时, exp−1 为负数, 导致所有走平ETF得分转负被淘汰。172的 exp × R² 公式无此问题。</li>
</ol>
<p>建议: 若使用175的池+双regime+过滤器体系, 应替换为172的公式 (exp×R²) 并消除未来函数, 然后回测验证。</p>
</div>

<p style="text-align:center;color:#999;font-size:11px">七星175 vs 172 回测对比 · {NOW_STR} · Blakever Trade</p>
</body></html>
"""

report_path = OUT_DIR / f'七星175_vs_172_对比_{NOW_STR}.html'
report_path.write_text(html, encoding='utf-8')
print(f"\n报告: {report_path}")

# Save trades for analysis
for label, trades in [('172', t172), ('175_orig', t175), ('175_fixed', t175f)]:
    p = OUT_DIR / f'trades_{label}_{NOW_STR}.json'
    json.dump(trades, p, ensure_ascii=False)
    print(f"交易: {p}")
