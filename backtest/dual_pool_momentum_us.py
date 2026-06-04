#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
ETF双池平滑美股版 (Nasdaq 100) 策略回测
==========================================================================
核心策略: etf双池平滑动量轮动 (dual_pool_momentum.py)
成分股: 纳斯达克100 (Nasdaq 100) 成分股

策略特点:
- 静态成分股池: ~90只Nasdaq100成分股
- 双均线过滤: close > MA20 AND MA20 > MA60
- 成交量放量过滤: 当日量/5日均量 > 2.5 -> 过滤
- 动量评分: 加权对数回归 exp(slope*250)-1 x R2 (与七星172/双池A股一致)
- 得分范围: 无限制 (同双池A股 -999999~999999)
- 止损: 成本价92%
- 防御模式: 无目标时持有现金
- 佣金: $0.005/股 (双边)
==========================================================================
"""

import sys, os, json, math, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

# ================================================================
# 策略元数据
# ================================================================
STRATEGY_NAME = "ETF双池平滑美股版(Nasdaq100)"
STRATEGY_TAG = "dual_pool_us100"
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUTPUT_DIR = PROJECT_ROOT / 'backtest' / 'results_dual_pool_us'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = '2025-01-01'
END_DATE = '2026-04-23'  # 本地数据最新日期

# ================================================================
# 纳斯达克100成分股 (与七星美股版一致)
# ================================================================
NASDAQ100_SYMBOLS = [
    'AAPL','MSFT','NVDA','AMZN','META','GOOGL','GOOG','AVGO','TSLA',
    'COST','NFLX','AMD','PEP','ADBE','CSCO','QCOM','INTU','TXN',
    'AMGN','HON','AMAT','CMCSA','INTC','BKNG','ISRG','VRTX',
    'REGN','ADI','LRCX','MU','GILD','MDLZ','SBUX','ADP','KLAC',
    'PANW','SNPS','CDNS','MELI','ASML','CTAS','MAR','ABNB','ORLY',
    'CRWD','WDAY','FTNT','ADSK','ROP','PCAR','MNST','KDP','PAYX',
    'ODFL','CEG','DASH','TEAM','CPRT','NXPI','CHTR','KHC',
    'IDXX','TTD','PYPL','MCHP','EA','FAST','BKR','EXC',
    'XEL','CTSH','VRSK','CCEP','DDOG','ON','CDW','FANG',
    'GEHC','ZS','BIIB','DXCM','TTWO','WBD',
    'ARM','MSTR','COIN','LIN','PLTR','APP','AXON','MRVL',
]

# ================================================================
# 策略参数 (与双池A股版一致)
# ================================================================
PARAMS = {
    # ---- 核心参数 ----
    'lookback_days': 25,              # 动量回看天数
    'holdings_num': 1,                # 持仓数量
    'min_money': 5000,                # 最小交易金额

    # ---- 双均线过滤 ----
    'enable_ma_filter': True,
    'ma_short': 20,
    'ma_long': 60,

    # ---- 成交量放量过滤 ----
    'enable_volume_check': True,
    'volume_lookback': 5,
    'volume_threshold': 2.5,

    # ---- 止损 ----
    'stop_loss_ratio': 0.92,

    # ---- 得分范围 (与双池A股一致: 无限制) ----
    'min_score_threshold': -999999,
    'max_score_threshold': 999999,
}

print("=" * 70)
print(f"  {STRATEGY_NAME}")
print(f"  回测区间: {START_DATE} ~ {END_DATE}")
print(f"  策略架构: 双池平滑动量 (A股版完整移植)")
print("=" * 70)

# ================================================================
# Step 1: 加载本地数据
# ================================================================
print(f"\n[1/5] 加载本地美股数据...")
all_data = {}
missing = []

for sym in NASDAQ100_SYMBOLS:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists():
        missing.append(sym)
        continue
    try:
        df = pd.read_csv(fp)
        # 统一列名
        cols_lower = [c.lower() for c in df.columns]
        rename_map = {}
        for c in df.columns:
            lc = c.lower()
            if lc == 'date':
                rename_map[c] = 'date'
            elif lc == 'open':
                rename_map[c] = 'open'
            elif lc == 'high':
                rename_map[c] = 'high'
            elif lc == 'low':
                rename_map[c] = 'low'
            elif lc == 'close':
                rename_map[c] = 'close'
            elif lc == 'volume':
                rename_map[c] = 'volume'
        df = df.rename(columns=rename_map)

        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()

        # 确保所需列存在
        required = ['open','high','low','close','volume']
        for col in required:
            if col not in df.columns:
                df[col] = np.nan

        # 筛选回测区间 (含前置数据用于MA计算)
        pre_start = pd.Timestamp(START_DATE) - pd.Timedelta(days=150)
        mask = (df.index >= pre_start) & (df.index <= END_DATE)
        df = df[mask]

        if len(df[df.index >= START_DATE]) >= 25:
            all_data[sym] = df
        else:
            missing.append(sym)
    except Exception as e:
        missing.append(sym)

print(f"  有效: {len(all_data)} 只, 缺失: {len(missing)} 只")
if missing:
    print(f"  缺失列表: {missing}")

if len(all_data) < 20:
    print(f"[FATAL] 数据不足: {len(all_data)}只")
    sys.exit(1)

# ================================================================
# Step 2: 提取交易日
# ================================================================
trade_dates = sorted(set().union(*[
    df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()
]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]
print(f"  交易日: {len(trade_dates)} 天")

# ================================================================
# Step 3: 回测引擎
# ================================================================

class USPortfolio:
    """美股组合管理 (与七星美股版完全一致)"""
    def __init__(self, cash=100000, comm_per_share=0.005):
        self.initial_cash = cash
        self.cash = cash
        self.comm = comm_per_share
        self.positions = {}
        self.trade_log = []
        self.daily_values = []

    @property
    def total_value(self):
        pv = sum(p['shares'] * p.get('last_price', p['cost_price'])
                 for p in self.positions.values())
        return self.cash + pv

    def update_prices(self, pdict):
        for c, p in pdict.items():
            if c in self.positions:
                self.positions[c]['last_price'] = p

    def buy(self, code, shares, price, date, reason=''):
        tv = shares * price
        comm = shares * self.comm
        total = tv + comm
        if total > self.cash + 0.01:
            return False
        self.cash -= total
        if code in self.positions:
            o = self.positions[code]
            ts = o['shares'] + shares
            self.positions[code] = {
                'shares': ts,
                'cost_price': (o['shares']*o['cost_price'] + shares*price)/ts,
                'last_price': price, 'buy_date': o.get('buy_date', date)
            }
        else:
            self.positions[code] = {
                'shares': shares, 'cost_price': price,
                'last_price': price, 'buy_date': date
            }
        self.trade_log.append({
            'date': str(date)[:10], 'code': code, 'name': code,
            'action': 'BUY', 'price': round(price, 4),
            'shares': int(shares), 'amount': round(tv, 2),
            'commission': round(comm, 2), 'reason': reason,
        })
        return True

    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions:
            return False
        pos = self.positions[code]
        actual = min(shares, pos['shares'])
        if actual <= 0:
            return False
        tv = actual * price
        comm = actual * self.comm
        self.cash += tv - comm
        pos['shares'] -= actual
        pnl = (price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares'] <= 0:
            del self.positions[code]
        self.trade_log.append({
            'date': str(date)[:10], 'code': code, 'name': code,
            'action': 'SELL', 'price': round(price, 4),
            'shares': int(actual), 'amount': round(tv, 2),
            'commission': round(comm, 2), 'pnl_pct': round(pnl, 4),
            'reason': reason,
        })
        return True

    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions:
            return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)

    def record_daily_value(self, date):
        v = self.total_value
        self.daily_values.append({
            'date': str(date)[:10], 'value': round(v, 2),
            'returns': round((v-self.initial_cash)/self.initial_cash, 6),
        })

    def get_position_codes(self):
        return list(self.positions.keys())


# ================================================================
# 动量评分函数 (与双池A股/七星172完全一致)
# ================================================================
def calc_momentum_score(close_full, lookback=25):
    """加权对数回归: exp(slope*250)-1 x R2"""
    recent = close_full[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope * x + intercept)) ** 2)
    sst = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann * r2, ann


# ================================================================
# 双池过滤器 (移植自DualPoolFilter)
# ================================================================
def dual_pool_filter(code, close_arr, vol_arr, params):
    """
    双池过滤逻辑:
    1. 双均线: close > MA20 AND MA20 > MA60
    2. 成交量放量: vol / 5d_avg > 2.5 -> 过滤
    Returns: (is_filtered, [reasons])
    """
    reasons = []

    # ---- 第1层: 双均线过滤 ----
    if params.get('enable_ma_filter', True):
        ma_short = params.get('ma_short', 20)
        ma_long = params.get('ma_long', 60)
        if len(close_arr) >= ma_long:
            ma_s = np.mean(close_arr[-ma_short:])
            ma_l = np.mean(close_arr[-ma_long:])
            if not (close_arr[-1] > ma_s and ma_s > ma_l):
                reasons.append('双均线过滤')

    # ---- 第2层: 成交量放量过滤 ----
    if params.get('enable_volume_check', False) and len(vol_arr) > 0:
        v_lookback = params.get('volume_lookback', 5)
        v_threshold = params.get('volume_threshold', 2.5)
        if len(vol_arr) > v_lookback:
            today_vol = vol_arr[-1]
            avg_vol = np.mean(vol_arr[-(v_lookback + 1):-1])
            if avg_vol > 0 and today_vol / avg_vol > v_threshold:
                reasons.append(f'成交量放量({today_vol / avg_vol:.1f}x)')

    return len(reasons) > 0, reasons


def rank_stocks(all_data, prices, date, params):
    """
    排名+过滤: 对Nasdaq100成分股进行动量排名，同时应用双池过滤器
    """
    ranked = []
    lb = params['lookback_days']
    td_ts = pd.Timestamp(date)

    for code, df in all_data.items():
        if code not in prices or prices[code] <= 0:
            continue

        mask = df.index <= td_ts
        hist = df[mask]
        if len(hist) < params.get('ma_long', 60) + 10:
            continue

        cp = prices[code]
        close_arr = hist['close'].values
        vol_arr = hist['volume'].values if 'volume' in hist.columns else np.array([])

        # 动量评分
        score, ann = calc_momentum_score(close_arr, lb)

        # 双池过滤
        filtered, reasons = dual_pool_filter(code, close_arr, vol_arr, params)

        ranked.append({
            'code': code, 'score': score, 'annualized': ann,
            'price': cp, 'filtered': filtered,
            'reasons': reasons
        })

    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


# ================================================================
# Step 4: 执行回测
# ================================================================
INITIAL_CASH = 100000
pf = USPortfolio(cash=INITIAL_CASH)
hn = PARAMS['holdings_num']

print(f"\n[2/5] 开始逐日回测...")
print(f"  初始资金: ${INITIAL_CASH:,.0f} | 持仓数: {hn} | 佣金: $0.005/股")
print("-" * 70)

for i, td in enumerate(trade_dates):
    tds = pd.Timestamp(td)

    # 构建当日价格快照
    prices = {}
    for code, df in all_data.items():
        m = df.index <= tds
        if m.any():
            prices[code] = float(df.loc[m, 'close'].iloc[-1])

    # 更新持仓价格
    pf.update_prices(prices)

    # ===== 卖出操作 =====

    held = list(pf.get_position_codes())
    for code in held:
        if code not in prices:
            continue

        cp = prices[code]
        pos = pf.positions.get(code)
        if pos is None or pos['shares'] <= 0:
            continue

        cost_price = pos.get('cost_price', cp)

        # 1. 止损检查 (成本价92%)
        if cp <= cost_price * PARAMS.get('stop_loss_ratio', 0.92):
            loss_pct = (cp / cost_price - 1) * 100
            pf.sell_all(code, cp, td, reason=f'止损({loss_pct:.1f}%)')
            continue

        # 2. 放量卖出
        if PARAMS.get('enable_volume_check', False) and code in all_data:
            hist_df = all_data[code]
            mask = hist_df.index <= tds
            hist = hist_df[mask]
            if 'volume' in hist.columns and len(hist) > PARAMS.get('volume_lookback', 5):
                vols = hist['volume'].values
                v_lb = PARAMS.get('volume_lookback', 5)
                v_th = PARAMS.get('volume_threshold', 2.5)
                avg_vol = np.mean(vols[-(v_lb + 1):-1])
                if avg_vol > 0 and vols[-1] / avg_vol > v_th:
                    pf.sell_all(code, cp, td, reason=f'放量卖出({vols[-1] / avg_vol:.1f}x)')
                    continue

    # ===== 排名+过滤 =====
    ranked = rank_stocks(all_data, prices, td, PARAMS)
    if not ranked:
        pf.record_daily_value(td)
        continue

    # 获取通过过滤的目标 (得分无范围限制, 与双池A股一致)
    targets = []
    for r in ranked:
        if len(targets) >= hn:
            break
        if not r['filtered']:
            if PARAMS.get('min_score_threshold', -999999) < r['score'] < PARAMS.get('max_score_threshold', 999999):
                targets.append(r['code'])

    # 无目标: 卖出所有, 持有现金
    if not targets:
        for code in list(pf.get_position_codes()):
            if code in prices:
                pf.sell_all(code, prices[code], td, reason='转入防御(无目标)')
        pf.record_daily_value(td)
        if i % 30 == 0:
            print(f'  [{td}] DEFENSE: 无目标, 持有现金 | ${pf.total_value:,.0f}')
        continue

    # ===== 调仓卖出 =====
    target_set = set(targets)
    for code in list(pf.get_position_codes()):
        if code not in target_set and code in prices:
            pf.sell_all(code, prices[code], td, reason='调出目标')

    # ===== 买入操作 =====
    tv = pf.total_value
    each = tv / len(targets)

    for idx, code in enumerate(targets):
        if code not in prices or prices[code] <= 0:
            continue

        price = prices[code]
        cv = 0
        if code in pf.positions:
            cv = pf.positions[code]['shares'] * pf.positions[code]['last_price']

        diff = each - cv
        if abs(diff) < each * 0.05 and cv > 0:
            continue

        if diff > 0:
            sh = int(diff / price)
            if sh > 0 and sh * price >= PARAMS['min_money']:
                pf.buy(code, sh, price, td, reason=f'排名{idx+1}')

    pf.record_daily_value(td)

    if i % 30 == 0:
        top3 = ", ".join([f"{r['code']}({r['score']:.4f})" for r in ranked[:3]])
        filt_info = f"通过: {len(targets)}/{len(ranked)}" if ranked else "无排名"
        top_scores = f" | {filt_info}"
        print(f'  [{td}] Top3: {top3}{top_scores} | ${pf.total_value:,.0f}')


# ================================================================
# Step 5: 生成结果
# ================================================================
print("-" * 70)
print(f"\n[3/5] 回测完成! 计算绩效指标...")

dv = pf.daily_values
vals = [d['value'] for d in dv]
fv = vals[-1] if vals else INITIAL_CASH
tr = (fv - pf.initial_cash) / pf.initial_cash
peak, mdd = vals[0] if vals else INITIAL_CASH, 0

for v in vals:
    if v > peak:
        peak = v
    dd = (peak - v) / peak if peak > 0 else 0
    if dd > mdd:
        mdd = dd

sh = 0
if len(vals) > 1:
    dr = np.diff(vals) / vals[:-1]
    std_val = np.std(dr)
    if len(dr) > 0 and std_val > 0:
        sh = float(np.mean(dr) / std_val * np.sqrt(252))

n_days = len(trade_dates)
ann = float(tr * 252 / n_days if n_days > 0 else 0)
cm = float(abs(ann) / mdd if mdd > 0 else 0)

trades = pf.trade_log
buys = sum(1 for t in trades if t['action'] == 'BUY')
sells = sum(1 for t in trades if t['action'] == 'SELL')
st = [t for t in trades if t['action'] == 'SELL' and 'pnl_pct' in t]
wins = [t for t in st if t['pnl_pct'] > 0]
losses = [t for t in st if t['pnl_pct'] <= 0]
wr = len(wins) / len(st) * 100 if st else 0
aw = sum(t['pnl_pct'] for t in wins) / len(wins) * 100 if wins else 0
al = sum(t['pnl_pct'] for t in losses) / len(losses) * 100 if losses else 0

# 市场基准: QQQ buy & hold
def calc_benchmark():
    qqq_path = DATA_DIR / 'QQQ.csv'
    if not qqq_path.exists():
        return None

    try:
        qdf = pd.read_csv(qqq_path)
        qdf = qdf.rename(columns={
            c: c.lower() for c in qdf.columns if c.lower() in ['date','close']
        })
        if 'date' in qdf.columns and 'close' in qdf.columns:
            qdf['date'] = pd.to_datetime(qdf['date'])
            qdf = qdf.set_index('date').sort_index()
            mask = (qdf.index >= START_DATE) & (qdf.index <= END_DATE)
            qdf = qdf[mask]
            if len(qdf) >= 2:
                qqq_start_price = float(qdf['close'].iloc[0])
                qqq_end_price = float(qdf['close'].iloc[-1])
                qqq_return = (qqq_end_price / qqq_start_price - 1) * 100
                return {
                    'name': 'QQQ (买入持有)',
                    'start_price': qqq_start_price,
                    'end_price': qqq_end_price,
                    'total_return_pct': qqq_return,
                }
    except:
        pass
    return None

benchmark = calc_benchmark()

results = {
    'strategy': STRATEGY_NAME,
    'backtest_period': f'{trade_dates[0]} ~ {trade_dates[-1]}',
    'trading_days': len(trade_dates),
    'initial_cash': pf.initial_cash,
    'final_value': round(fv, 2),
    'total_return_pct': round(tr * 100, 2),
    'annualized_return_pct': round(ann * 100, 2),
    'max_drawdown_pct': round(mdd * 100, 2),
    'sharpe_ratio': round(sh, 4),
    'calmar_ratio': round(cm, 4),
    'total_trades': len(trades),
    'buy_trades': buys,
    'sell_trades': sells,
    'win_rate_pct': round(wr, 2),
    'avg_win_pct': round(aw, 2),
    'avg_loss_pct': round(al, 2),
    'daily_values': dv,
    'trade_log': trades,
    'engine_params': PARAMS,
}

print(f"\n{'='*60}")
print(f"  回测结果: {STRATEGY_NAME}")
print(f"{'='*60}")
print(f"  区间: {results['backtest_period']} ({results['trading_days']}天)")
print(f"  初始: ${results['initial_cash']:,.0f} -> 最终: ${results['final_value']:,.2f}")
print(f"  总收益: {results['total_return_pct']:+.2f}%  年化: {results['annualized_return_pct']:.2f}%")
print(f"  最大回撤: {results['max_drawdown_pct']:.2f}%  夏普: {results['sharpe_ratio']:.4f}  卡尔马: {results['calmar_ratio']:.4f}")
print(f"  交易: {results['total_trades']}次 (买{buys}/卖{sells})  胜率: {wr:.1f}%")
if wins:
    print(f"  平均盈利: +{aw:.2f}%")
if losses:
    print(f"  平均亏损: {al:.2f}%")

if benchmark:
    print(f"\n  基准对比 [{benchmark['name']}]:")
    print(f"    {benchmark['name']}: {benchmark['total_return_pct']:+.2f}%")
    print(f"    策略超额: {tr*100 - benchmark['total_return_pct']:+.2f}%")

print(f"{'='*60}")

# ================================================================
# Step 6: 保存结果
# ================================================================
now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
now_tag = datetime.now().strftime('%Y%m%d_%H%M')

suffix = f"{START_DATE}_{END_DATE}"

# 摘要JSON
summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
summary_path = OUTPUT_DIR / f'{STRATEGY_TAG}_{suffix}_summary.json'
with open(summary_path, 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
print(f"摘要: {summary_path}")

# 每日净值
dv_path = OUTPUT_DIR / f'{STRATEGY_TAG}_{suffix}_daily.json'
with open(dv_path, 'w', encoding='utf-8') as f:
    json.dump(results.get('daily_values', []), f, ensure_ascii=False, indent=2, default=str)
print(f"净值: {dv_path}")

# 交易记录
trades_path = OUTPUT_DIR / f'{STRATEGY_TAG}_{suffix}_trades.json'
with open(trades_path, 'w', encoding='utf-8') as f:
    json.dump(results.get('trade_log', []), f, ensure_ascii=False, indent=2, default=str)
print(f"交易: {trades_path}")

# 参数
params_path = OUTPUT_DIR / f'{STRATEGY_TAG}_{suffix}_params.json'
with open(params_path, 'w', encoding='utf-8') as f:
    json.dump(PARAMS, f, ensure_ascii=False, indent=2, default=str)
print(f"参数: {params_path}")


# ================================================================
# Step 7: 生成HTML+MD报告
# ================================================================
print(f"\n[4/5] 生成报告...")

# 交易表格行
trades_rows = ""
for t in trades[-50:]:
    d = '买入' if t['action'] == 'BUY' else '卖出'
    pnl = t.get('pnl_pct', None)
    ps = f'{pnl * 100:+.2f}%' if pnl is not None else '-'
    bg = '#E2EFDA' if t['action'] == 'BUY' else '#FCE4D6'
    pc = '#28A745' if (pnl and pnl > 0) else ('#DC3545' if (pnl and pnl < 0) else '#888')
    trades_rows += f"""<tr style="background:{bg};">
        <td>{t['date']}</td><td style="font-weight:bold;">{d}</td><td>{t['name']}</td>
        <td style="text-align:right;">${t['price']:.2f}</td><td style="text-align:right;">{t.get('shares', 0)}</td>
        <td style="text-align:right;">${t.get('amount', 0):,.2f}</td>
        <td style="font-size:11px;color:#555;">{t.get('reason', '')}</td>
        <td style="text-align:right;font-weight:bold;color:{pc};">{ps}</td></tr>"""

# 绩效颜色
ret_color = '#2E7D32' if tr > 0 else '#C62828'
ret_bg = '#E8F5E9' if tr > 0 else '#FFEBEE'

# 基准对比行
bench_rows = ""
if benchmark:
    bm_color = '#2E7D32' if benchmark['total_return_pct'] > 0 else '#C62828'
    excess = tr * 100 - benchmark['total_return_pct']
    ex_color = '#2E7D32' if excess > 0 else '#C62828'
    bench_rows = f"""
    <tr><td>QQQ买入持有 (基准)</td><td style="color:{bm_color};font-weight:bold;text-align:right;">{benchmark['total_return_pct']:+.2f}%</td></tr>
    <tr><td>策略超额收益</td><td style="color:{ex_color};font-weight:bold;text-align:right;">{excess:+.2f}%</td></tr>
    """

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{STRATEGY_NAME}</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:960px;margin:0 auto;padding:20px;background:#f8f9fa;}}
h1{{font-size:24px;color:#1F4E79;text-align:center;margin:0 0 5px;}}
.subtitle{{text-align:center;font-size:13px;color:#888;margin-bottom:25px;}}
.card{{background:#fff;padding:15px 20px;border-radius:8px;margin-bottom:15px;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.config-box{{background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:15px;font-size:13px;}}
.metrics-row{{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;}}
.metric-card{{flex:1;min-width:180px;background:#fff;padding:15px;border-radius:8px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.metric-label{{font-size:12px;color:#888;margin-bottom:6px;}}
.metric-value{{font-size:20px;font-weight:bold;color:#1F4E79;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#1F4E79;color:#fff;padding:8px;text-align:left;}}
td{{padding:6px 8px;border-bottom:1px solid #eee;}}
.comparison-table td{{padding:8px 12px;font-size:13px;}}
.footer{{text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;}}
</style></head><body>
<h1>{STRATEGY_NAME} · 回测报告</h1>
<div class="subtitle">{now_str} | {results['backtest_period']} ({results['trading_days']}天)</div>

<div class="config-box">
    <b>策略架构:</b> ETF双池平滑动量轮动 (完整移植) |
    <b>成分股:</b> Nasdaq100 ({len(all_data)}只有效) |
    <b>周期:</b> 25日加权对数回归<br>
    <b>过滤:</b> 双均线(MA20>MA60+站上) | 成交量放量(>2.5x→过滤) | 止损(成本92%)<br>
    <b>佣金:</b> $0.005/股 | <b>持仓:</b> 1只 | <b>防御:</b> 现金 |
    <b>评分:</b> exp(slope x 250) x R² (与七星172/双池A股完全一致)
</div>

<div class="card"><h3 style="font-size:15px;color:#1F4E79;margin:0 0 12px;">回测绩效 (USD)</h3>
<div class="metrics-row">
    <div class="metric-card" style="background:{ret_bg}">
        <div class="metric-label">总收益率</div><div class="metric-value" style="color:{ret_color}">{tr:+.2f}%</div></div>
    <div class="metric-card"><div class="metric-label">年化收益</div><div class="metric-value">{results['annualized_return_pct']:.2f}%</div></div>
    <div class="metric-card"><div class="metric-label">最大回撤</div><div class="metric-value">{results['max_drawdown_pct']:.2f}%</div></div>
    <div class="metric-card"><div class="metric-label">夏普比率</div><div class="metric-value">{results['sharpe_ratio']:.4f}</div></div>
</div>
<div class="metrics-row">
    <div class="metric-card"><div class="metric-label">初始资金</div><div class="metric-value">${results['initial_cash']:,.0f}</div></div>
    <div class="metric-card"><div class="metric-label">最终资产</div><div class="metric-value">${results['final_value']:,.2f}</div></div>
    <div class="metric-card"><div class="metric-label">胜率</div><div class="metric-value">{results['win_rate_pct']:.1f}%</div></div>
    <div class="metric-card"><div class="metric-label">总交易</div><div class="metric-value">{results['total_trades']}次(买{buys}/卖{sells})</div></div>
</div></div>

<div class="card"><h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px;">A股双池 vs 美股双池 对比</h3>
<div style="overflow-x:auto;"><table class="comparison-table">
<tr><th>指标</th><th>ETF双池A股版</th><th>ETF双池美股版</th></tr>
<tr><td>成分股</td><td>121只A股ETF</td><td>{len(all_data)}只Nasdaq100个股</td></tr>
<tr><td>总收益</td><td style="color:#2E7D32;font-weight:bold;">+162.24%</td><td style="color:{ret_color};font-weight:bold;">{tr:+.2f}%</td></tr>
<tr><td>年化收益</td><td>+119.89%</td><td>{results['annualized_return_pct']:.2f}%</td></tr>
<tr><td>最大回撤</td><td>28.04%</td><td>{results['max_drawdown_pct']:.2f}%</td></tr>
<tr><td>夏普比率</td><td>1.82</td><td>{results['sharpe_ratio']:.4f}</td></tr>
<tr><td>胜率</td><td>52.38%</td><td>{results['win_rate_pct']:.1f}%</td></tr>
<tr><td>交易次数</td><td>85次</td><td>{results['total_trades']}次</td></tr>
{bench_rows}</table></div></div>

<div class="card"><h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px;">交易记录 (最近50条)</h3>
<div style="overflow-x:auto;"><table>
<tr><th>日期</th><th>方向</th><th>标的</th><th>价格</th><th>数量</th><th>金额</th><th>理由</th><th>盈亏</th></tr>
{trades_rows}</table></div></div>

<div class="footer">{STRATEGY_NAME} · Blakever Trade · {now_str}<br>本报告仅供研究参考，不构成投资建议。</div>
</body></html>"""

# Markdown报告
tmd = ""
for t in trades[-50:]:
    d = '买入' if t['action'] == 'BUY' else '卖出'
    pnl = t.get('pnl_pct', None)
    ps = f'{pnl * 100:+.2f}%' if pnl is not None else '-'
    tmd += f"| {t['date']} | {d} | {t['name']} | ${t['price']:.2f} | {t.get('shares', 0)} | ${t.get('amount', 0):,.2f} | {t.get('reason', '')} | {ps} |\n"

bench_md = ""
if benchmark:
    excess = tr * 100 - benchmark['total_return_pct']
    bench_md = f"| QQQ买入持有 (基准) | {benchmark['total_return_pct']:+.2f}% |\n| 策略超额收益 | {excess:+.2f}% |\n"

md = f"""# {STRATEGY_NAME} 回测报告 - {now_str}

## 策略配置
- **成分股**: Nasdaq100 ({len(all_data)}只有效, {len(missing)}只缺失)
- **回测区间**: {results['backtest_period']} ({results['trading_days']}天)
- **策略架构**: ETF双池平滑动量轮动 (完整移植)
- **过滤**: 双均线(MA20>MA60+站上) | 成交量放量(>2.5x) | 止损(成本92%)
- **佣金**: $0.005/股 | **持仓数**: {hn}
- **评分**: exp(slope x 250) x R² (与七星172/双池A股完全一致)
- **防御**: 无目标时持有现金

## 回测绩效 (USD)

| 指标 | 数值 |
|------|------|
| 初始资金 | ${results['initial_cash']:,.0f} |
| 最终资产 | ${results['final_value']:,.2f} |
| 总收益率 | {tr:+.2f}% |
| 年化收益 | {results['annualized_return_pct']:.2f}% |
| 最大回撤 | {results['max_drawdown_pct']:.2f}% |
| 夏普比率 | {results['sharpe_ratio']:.4f} |
| 卡尔马比率 | {results['calmar_ratio']:.4f} |
| 总交易 | {results['total_trades']} (买{buys}/卖{sells}) |
| 胜率 | {results['win_rate_pct']:.1f}% |
| 平均盈利 | +{results['avg_win_pct']:.2f}% |
| 平均亏损 | {results['avg_loss_pct']:.2f}% |

## A股双池 vs 美股双池

| 指标 | ETF双池A股版 | ETF双池美股版 |
|------|-------------|--------------|
| 成分股 | 121只A股ETF | {len(all_data)}只Nasdaq100个股 |
| 总收益 | +162.24% | {tr:+.2f}% |
| 年化收益 | +119.89% | {results['annualized_return_pct']:.2f}% |
| 最大回撤 | 28.04% | {results['max_drawdown_pct']:.2f}% |
| 夏普比率 | 1.82 | {results['sharpe_ratio']:.4f} |
| 胜率 | 52.38% | {results['win_rate_pct']:.1f}% |
| 交易次数 | 85次 | {results['total_trades']}次 |
{bench_md}

## 交易记录 (最近50条)

| 日期 | 方向 | 标的 | 价格 | 数量 | 金额 | 理由 | 盈亏 |
|------|------|------|------|------|------|------|------|
{tmd}
---
*{STRATEGY_NAME} · Blakever Trade · {now_str}*
"""

html_path = OUTPUT_DIR / f'{STRATEGY_NAME}_回测报告_{now_tag}.html'
md_path = OUTPUT_DIR / f'{STRATEGY_NAME}_回测报告_{now_tag}.md'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
with open(md_path, 'w', encoding='utf-8') as f:
    f.write(md)
print(f'报告已生成:')
print(f'  HTML: {html_path}')
print(f'  MD:   {md_path}')

# ================================================================
# Step 8: 发送邮件
# ================================================================
print(f"\n[5/5] 发送邮件...")
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

msg = MIMEMultipart("mixed")
msg["Subject"] = f"[回测报告] {STRATEGY_NAME} - {now_tag}"
msg["From"] = "848786642@qq.com"
msg["To"] = "848786642@qq.com"
msg.attach(MIMEText(html, "html", "utf-8"))
with open(md_path, 'r', encoding='utf-8') as f:
    att = MIMEText(f.read(), "plain", "utf-8")
    att.add_header("Content-Disposition", "attachment", filename=os.path.basename(md_path))
    msg.attach(att)

try:
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
        s.login("848786642@qq.com", "ljbtvacrctjobfed")
        s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
    print(f'[OK] 邮件已发送到 848786642@qq.com')
except Exception as e:
    print(f'[FAIL] 邮件发送失败: {e}')

print(f"\n{'='*70}")
print(f"  全部完成!")
print(f"{'='*70}")
