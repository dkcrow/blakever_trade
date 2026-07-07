#!/usr/bin/env python3
"""七星双动量策略 vs 七星QMT原版 回测对比
池: 57只ETF (双动量原始池) 
规则: 25日总收益 × (1+10日总收益) → 排名 → 持1只 → 三级过滤
"""
import sys, os, math, warnings
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ETF_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'

# ====== 双动量 ETF池 (57只, 与原始脚本完全一致) ======
DM_POOL_RAW = [
    # 商品 (6)
    '518880','159980','159985','501018','161226','159981',
    # 美股 (6)
    '513100','159509','513290','513500','159529','513400',
    # 其他海外 (5)
    '513520','513030','513080','513310','513730',
    # 港股 (5)
    '159792','513130','513050','159920','513690',
    # A股宽基 (10)
    '510300','510500','510050','510210','159915','588080','512100','563360','563300','159201',
    # A股风格 (3)
    '512890','159967','512040',
    # 债券 (3)
    '511380','511010','511220',
    # 未来方向 (7)
    '515880','588200','515030','159530','159255','159206','159316',
]
DM_NAMES = {
    '518880':'黄金ETF','159980':'有色期货','159985':'豆粕','501018':'原油LOF',
    '161226':'白银LOF','159981':'能源化工',
    '513100':'纳指100','159509':'纳指科技','513290':'纳指生物','513500':'标普500',
    '159529':'标普消费','513400':'道琼斯',
    '513520':'日经','513030':'德国DAX','513080':'法国CAC','513310':'中韩半导体','513730':'东南亚',
    '159792':'港股互联网','513130':'恒生科技','513050':'中概互联','159920':'恒生指数','513690':'港股红利',
    '510300':'沪深300','510500':'中证500','510050':'上证50','510210':'上证综指',
    '159915':'创业板','588080':'科创50','512100':'中证1000','563360':'A500','563300':'A2000','159201':'深证主板',
    '512890':'红利低波','159967':'创成长','512040':'价值ETF',
    '511380':'可转债','511010':'国债ETF','511220':'城投债',
    '515880':'通信ETF','588200':'科创芯片','515030':'新能源车',
    '159530':'机器人ETF','159255':'无人机ETF','159206':'卫星ETF','159316':'创新药ETF',
}

# ====== 过滤参数 (与原始脚本一致) ======
STOP_LOSS = 0.95         # 三日连续跌幅阈值
LOSS = 0.97
VOLUME_LOOKBACK = 5
VOLUME_THRESHOLD = 2
VOLUME_RETURN_LIMIT = 1  # 年化收益超过100%时跳过放量ETF

def load_etf(code, start, end):
    fp = ETF_DIR / f'{code}.csv'
    if not fp.exists(): return None
    df = pd.read_csv(fp)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    m = (df.index >= start) & (df.index <= end)
    df = df[m]
    return df if len(df) >= 40 else None

def calc_returns(close_series, lookback):
    """计算总收益率: (price[-1]/price[-(lookback+1)]-1)"""
    if len(close_series) < lookback + 1:
        return None
    return close_series[-1] / close_series[-(lookback + 1)] - 1

def calc_double_momentum(close_series):
    """双重动量: 25日总收益 × (1 + 10日总收益)"""
    long_ret = calc_returns(close_series, 25)
    short_ret = calc_returns(close_series, 10)
    if long_ret is None or short_ret is None:
        return None, None, None
    score = long_ret * (1 + short_ret)
    return score, long_ret, short_ret

def check_3day_loss(close_series):
    """连续三日跌幅检查: any(day_ret) < 0.97"""
    if len(close_series) < 4:
        return False
    d1 = close_series[-1] / close_series[-2]
    d2 = close_series[-2] / close_series[-3]
    d3 = close_series[-3] / close_series[-4]
    return min(d1, d2, d3) < LOSS

def run_dm_backtest(all_data, trade_dates):
    """双动量策略回测"""
    CASH0 = 1_000_000
    cash = CASH0; pos = {}; trades = []; daily_vals = []
    HN = 1  # 持1只

    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d')
        tds = pd.Timestamp(date)

        # 当日价格
        prices = {}
        for code, df in all_data.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])

        # 计算所有ETF的双重动量得分
        ranked = []
        for code, df in all_data.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 30: continue

            close_arr = hist['close'].values
            score, long_ret, short_ret = calc_double_momentum(close_arr)
            if score is None: continue

            # 绝对动量过滤: 长期收益必须>0
            if long_ret <= 0: continue

            # 连续三日跌幅过滤
            if check_3day_loss(close_arr): continue

            # 得分上限过滤
            if score >= 100.0: continue

            ranked.append({'code': code, 'score': score, 'long_ret': long_ret,
                          'short_ret': short_ret, 'price': prices[code]})

        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]
        target_codes = set(r['code'] for r in targets)

        # 卖出
        for code in list(pos.keys()):
            if code not in target_codes:
                p = prices.get(code)
                if not p:
                    continue
                po = pos[code]
                sp = p * 0.998  # 滑点
                tv = po['shares'] * sp
                comm = max(tv * 0.0002, 5)
                cash += tv - comm
                pnl = (sp - po['cp']) / po['cp'] * 100
                trades.append({'date': ds, 'code': code, 'action': 'SELL',
                              'pnl_pct': round(pnl, 2), 'shares': po['shares']})
                del pos[code]

        # 防御模式: 无候选时现金持有
        if not targets:
            tv = cash
            for c, po in pos.items():
                tv += po['shares'] * prices.get(c, po['cp'])
            daily_vals.append((ds, tv))
            continue

        # 买入
        new = [r for r in targets if r['code'] not in pos]
        if new:
            per_stock = cash * 0.95 / len(new)
            for r in new:
                bp = r['price'] * 1.002  # 滑点
                shares = int(per_stock / bp / 100) * 100
                if shares < 100: continue
                cost = shares * bp
                comm = max(cost * 0.0002, 5)
                cash -= cost + comm
                pos[r['code']] = {'shares': shares, 'cp': bp}
                trades.append({'date': ds, 'code': r['code'], 'action': 'BUY',
                              'pnl_pct': 0, 'shares': shares})

        tv = cash
        for c, po in pos.items():
            tv += po['shares'] * prices.get(c, po['cp'])
        daily_vals.append((ds, tv))

    final_tv = daily_vals[-1][1] if daily_vals else CASH0
    tr = (final_tv / CASH0 - 1) * 100
    days = len(daily_vals)
    af = 252 / max(days, 1)
    cagr = ((final_tv / CASH0) ** af - 1) * 100
    vals = np.array([v for _, v in daily_vals])
    peak = np.maximum.accumulate(vals)
    mdd = float(np.min((vals - peak) / peak * 100)) if len(vals) > 0 else 0
    rets = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    win_trades = [t for t in trades if t['action'] == 'SELL']
    wr = sum(1 for t in win_trades if t['pnl_pct'] > 0) / max(len(win_trades), 1) * 100

    return {
        'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
        'sharpe': round(sharpe, 2), 'trades': len(trades), 'wr': round(wr, 1),
        'fv': round(final_tv, 2), 'daily': daily_vals,
    }


def run_qmt_baseline(all_data_qmt, qmt_pool, trade_dates):
    """QMT原版策略: (exp(slope×250)-1)×R² 排名, 持1只"""
    CASH0 = 1_000_000; cash = CASH0; pos = {}; daily_vals = []
    HN = 1; SCORE_THR = 0.5

    def calc_score_qmt(closes):
        if len(closes) < 5: return -999
        x = np.arange(len(closes)); y = np.log(np.maximum(closes, 1e-10))
        mask = ~np.isnan(y) & ~np.isinf(y); x_m, y_m = x[mask], y[mask]
        if len(x_m) < 5: return -999
        w = np.linspace(1, 2, len(x_m))
        slope, intercept = np.polyfit(x_m, y_m, 1, w=w)
        ann = math.exp(slope * 250)
        fitted = slope * x_m + intercept; res = y_m - fitted
        ssr = np.sum(w * res**2); sst = np.sum(w * (y_m - np.mean(y_m))**2)
        r2 = 1 - ssr / sst if sst > 0 else 0
        return (ann - 1) * r2

    for date in trade_dates:
        ds = date.strftime('%Y-%m-%d'); tds = pd.Timestamp(date)
        prices = {}
        for code, df in all_data_qmt.items():
            m = df.index == date
            if m.any(): prices[code] = float(df.loc[date, 'close'])

        ranked = []
        for code, df in all_data_qmt.items():
            if code not in prices: continue
            m = df.index < tds; hist = df[m]
            if len(hist) < 35: continue
            score = calc_score_qmt(hist['close'].values[-25:])
            if score < SCORE_THR: continue
            ranked.append({'code': code, 'score': score, 'price': prices[code]})
        ranked.sort(key=lambda x: -x['score'])
        targets = ranked[:HN]
        tc = set(r['code'] for r in targets)

        for code in list(pos.keys()):
            if code not in tc:
                p = prices.get(code)
                if not p: continue
                sp = p * 0.998; tv_pos = pos[code]['shares'] * sp
                cash += tv_pos - max(tv_pos * 0.0002, 5)
                del pos[code]

        new = [r for r in targets if r['code'] not in pos]
        if new:
            per = cash * 0.95 / len(new)
            for r in new:
                bp = r['price'] * 1.002
                shares = int(per / bp / 100) * 100
                if shares < 100: continue
                cash -= shares * bp + max(shares * bp * 0.0002, 5)
                pos[r['code']] = {'shares': shares, 'cp': bp}

        tv = cash + sum(po['shares'] * prices.get(c, po['cp']) for c, po in pos.items())
        daily_vals.append((ds, tv))

    fv = daily_vals[-1][1] if daily_vals else CASH0
    tr = (fv / CASH0 - 1) * 100
    days = len(daily_vals); af = 252 / max(days, 1); cagr = ((fv / CASH0) ** af - 1) * 100
    vals = np.array([v for _, v in daily_vals])
    peak = np.maximum.accumulate(vals)
    mdd = float(np.min((vals - peak) / peak * 100)) if len(vals) > 0 else 0
    rets = np.diff(vals) / vals[:-1] if len(vals) > 1 else np.array([0])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
    return {'tr': round(tr, 1), 'cagr': round(cagr, 1), 'mdd': round(mdd, 1),
            'sharpe': round(sharpe, 2), 'fv': round(fv, 2)}


if __name__ == '__main__':
    # QMT池用于对比
    from reporting.generate_qmt_report import QMT_RAW_CODES

    periods = [
        ('1年', '2025-07-06', '2026-07-06'),
        ('3年', '2023-07-06', '2026-07-06'),
        ('5年', '2021-07-06', '2026-07-06'),
    ]

    for pname, start, end in periods:
        print(f"\n{'='*60}")
        print(f"  {pname}: {start} ~ {end}")
        print(f"{'='*60}")

        # 加载双动量池
        dm_data = {}
        for code in DM_POOL_RAW:
            df = load_etf(code, start, end)
            if df is not None: dm_data[code] = df
        td = sorted(set.union(*[set(df.index) for df in dm_data.values()]))
        td = [d for d in td if start <= d.strftime('%Y-%m-%d') <= end]
        print(f"  双动量池: {len(dm_data)}/{len(DM_POOL_RAW)}只有效, {len(td)}交易日")

        # 加载QMT池
        qmt_data = {}
        for code in QMT_RAW_CODES:
            df = load_etf(code, start, end)
            if df is not None: qmt_data[code] = df
        td_qmt = sorted(set.union(*[set(df.index) for df in qmt_data.values()]))
        td_qmt = [d for d in td_qmt if start <= d.strftime('%Y-%m-%d') <= end]
        print(f"  QMT池:  {len(qmt_data)}/{len(QMT_RAW_CODES)}只有效, {len(td_qmt)}交易日")

        r_dm = run_dm_backtest(dm_data, td)
        r_qmt = run_qmt_baseline(qmt_data, QMT_RAW_CODES, td_qmt)

        print(f"\n  {'策略':<20} {'累计':>10} {'CAGR':>8} {'回撤':>8} {'夏普':>7} {'交易':>6} {'胜率':>6}")
        print(f"  {'-'*65}")
        print(f"  {'双动量(57只)':<20} {r_dm['tr']:>+9.1f}% {r_dm['cagr']:>7.1f}% {r_dm['mdd']:>7.1f}% {r_dm['sharpe']:>6.2f} {r_dm['trades']:>5} {r_dm['wr']:>5.0f}%")
        print(f"  {'QMT原版(50只)':<20} {r_qmt['tr']:>+9.1f}% {r_qmt['cagr']:>7.1f}% {r_qmt['mdd']:>7.1f}% {r_qmt['sharpe']:>6.2f} {'N/A':>5} {'N/A':>5}")
        diff = r_dm['tr'] - r_qmt['tr']
        better = '双动量胜' if diff > 0 else 'QMT胜' if diff < 0 else '平'
        print(f"  {'差异':<20} {diff:>+9.1f}pp → {better}")

print("\n完成!")
