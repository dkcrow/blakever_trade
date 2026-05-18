#!/usr/bin/env python3
"""
RSI(2) vs KDJ-J 均值回归策略对比回测
======================================
公平对比：
- RSI(2): RSI2 < 10 买入，RSI2 > 80 卖出
- KDJ-J:  J < 0   买入，J > 100 卖出
同一标的QQQ，同一回测周期，同一仓位管理
"""
import os, warnings
import pandas as pd
import numpy as np
import backtrader as bt
import backtrader.analyzers as btanalyzers

warnings.filterwarnings('ignore')

DATA_DIR = '/data/workspace/back_trader_stocks'
INITIAL_CAPITAL = 100_000.0
COMMISSION = 0.001

PERIODS = {
    'bull1': ('牛市(2019-21)', '2019-01-01', '2021-12-31', 3.0),
    'bear':  ('熊市(2022)',    '2022-01-01', '2022-12-31', 1.0),
    'range': ('震荡(2023)',    '2023-01-01', '2023-12-31', 1.0),
    'bull2': ('牛市(2024)',    '2024-01-01', '2024-12-31', 1.0),
    'full':  ('全周期(2020-24)', '2020-01-01', '2024-12-31', 5.0),
}


# ============================================================
#  RSI(2) 均值回归策略
# ============================================================
def calc_rsi2(closes):
    if len(closes) < 3:
        return np.nan
    deltas = np.diff(closes[-3:])
    gains = deltas[deltas > 0].sum() if any(deltas > 0) else 0
    losses = -deltas[deltas < 0].sum() if any(deltas < 0) else 1e-10
    rs = gains / losses
    return 100 - (100 / (1 + rs))


class RSI2MeanReversion(bt.Strategy):
    """RSI(2) 均值回归: RSI2<10买, RSI2>80卖"""
    params = (
        ('rsi_buy',  10),
        ('rsi_sell', 80),
        ('pos_size', 0.95),
        ('start_dt', None),
    )

    def __init__(self):
        self._trade_count = 0
        self._order_ref = None

    def next(self):
        if self.p.start_dt is not None:
            if pd.Timestamp(self.datetime.datetime()) < self.p.start_dt:
                return

        d = self.data0
        n = len(d)
        if n < 5:
            return

        closes = np.array([d.close[-i] for i in range(min(n, 10), -1, -1)])
        rsi2 = calc_rsi2(closes)
        if np.isnan(rsi2):
            return

        pos = self.getposition(d)
        price = d.close[0]

        if rsi2 < self.p.rsi_buy and pos.size == 0:
            if self._order_ref is None:
                cash = self.broker.getcash()
                invest = cash * self.p.pos_size
                if invest < price:
                    return
                size = int(invest / price)
                if size > 0:
                    o = self.buy(data=d, size=size)
                    self._order_ref = o.ref

        elif rsi2 > self.p.rsi_sell and pos.size > 0:
            if self._order_ref is None:
                o = self.sell(data=d, size=pos.size)
                self._order_ref = o.ref

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self._order_ref = None
            if order.status == order.Completed:
                self._trade_count += 1


# ============================================================
#  KDJ-J 均值回归策略
# ============================================================
def calc_kdj(highs, lows, closes, k_period=9, k_smooth=3, d_smooth=3):
    """
    手动计算KDJ指标
    RSV = (C - L9) / (H9 - L9) * 100
    K = SMA(RSV, 3)
    D = SMA(K, 3)
    J = 3*K - 2*D
    """
    n = len(closes)
    if n < k_period:
        return np.nan, np.nan, np.nan

    # 计算RSV序列
    rsvs = []
    k_vals = []
    d_vals = []
    j_vals = []

    k_prev = 50.0  # K初始值
    d_prev = 50.0  # D初始值

    for i in range(n):
        if i < k_period - 1:
            rsvs.append(50.0)
            k_vals.append(k_prev)
            d_vals.append(d_prev)
            j_vals.append(3 * k_prev - 2 * d_prev)
            continue

        highest = max(highs[max(0, i - k_period + 1):i + 1])
        lowest = min(lows[max(0, i - k_period + 1):i + 1])
        close = closes[i]

        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (close - lowest) / (highest - lowest) * 100

        # SMA平滑
        k_curr = (2 / (k_smooth + 1)) * rsv + (1 - 2 / (k_smooth + 1)) * k_prev
        d_curr = (2 / (d_smooth + 1)) * k_curr + (1 - 2 / (d_smooth + 1)) * d_prev
        j_curr = 3 * k_curr - 2 * d_curr

        k_prev = k_curr
        d_prev = d_curr

        rsvs.append(rsv)
        k_vals.append(k_curr)
        d_vals.append(d_curr)
        j_vals.append(j_curr)

    return k_vals[-1], d_vals[-1], j_vals[-1]


class KDJJMeanReversion(bt.Strategy):
    """KDJ-J均值回归: J<0买, J>100卖"""
    params = (
        ('j_buy',    0),
        ('j_sell',  100),
        ('k_period', 9),
        ('pos_size', 0.95),
        ('start_dt', None),
    )

    def __init__(self):
        self._trade_count = 0
        self._order_ref = None

    def next(self):
        if self.p.start_dt is not None:
            if pd.Timestamp(self.datetime.datetime()) < self.p.start_dt:
                return

        d = self.data0
        n = len(d)
        if n < self.p.k_period + 2:
            return

        # 取足够长度的数据计算KDJ
        lookback = min(n, 30)
        highs = [d.high[-i] for i in range(lookback - 1, -1, -1)]
        lows = [d.low[-i] for i in range(lookback - 1, -1, -1)]
        closes = [d.close[-i] for i in range(lookback - 1, -1, -1)]

        _, _, j_val = calc_kdj(highs, lows, closes, self.p.k_period)

        pos = self.getposition(d)
        price = d.close[0]

        if j_val < self.p.j_buy and pos.size == 0:
            if self._order_ref is None:
                cash = self.broker.getcash()
                invest = cash * self.p.pos_size
                if invest < price:
                    return
                size = int(invest / price)
                if size > 0:
                    o = self.buy(data=d, size=size)
                    self._order_ref = o.ref

        elif j_val > self.p.j_sell and pos.size > 0:
            if self._order_ref is None:
                o = self.sell(data=d, size=pos.size)
                self._order_ref = o.ref

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self._order_ref = None
            if order.status == order.Completed:
                self._trade_count += 1


# ============================================================
#  买入持有基准
# ============================================================
class BuyAndHold(bt.Strategy):
    params = (('pos_size', 0.95), ('start_dt', None))

    def __init__(self):
        self._bought = False

    def next(self):
        if self._bought:
            return
        if self.p.start_dt is not None:
            if pd.Timestamp(self.datetime.datetime()) < self.p.start_dt:
                return
        d = self.data0
        cash = self.broker.getcash()
        price = d.close[0]
        size = int(cash * self.p.pos_size / price)
        if size > 0:
            self.buy(data=d, size=size)
            self._bought = True


# ============================================================
#  数据加载 & 回测引擎
# ============================================================
def load_data(symbol, fromdate, todate, preload_days=60):
    paths = [
        os.path.join(DATA_DIR, 'etf', f'{symbol}.csv'),
        os.path.join(DATA_DIR, 'us', f'{symbol}.csv'),
    ]
    for path in paths:
        if os.path.exists(path):
            break
    else:
        print(f"  ⚠️ 数据文件不存在: {symbol}")
        return None

    try:
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        df = df[(df['close'] > 0.01) & (df['open'] > 0.01) &
                (df['high'] > 0.01) & (df['low'] > 0.01) &
                (df['high'] >= df['low'])].copy()
        pre_from = fromdate - pd.Timedelta(days=preload_days)
        df = df[(df['date'] >= pre_from) & (df['date'] <= todate)].copy()
        if len(df) < 50:
            return None
        df = df.set_index('date')
        return bt.feeds.PandasData(dataname=df)
    except Exception as e:
        print(f"  ⚠️ 加载 {symbol} 失败: {e}")
        return None


def run_strategy(strategy_class, strategy_name, symbol, fromdate, todate, years, **kwargs):
    """运行单个策略回测"""
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=COMMISSION)

    d = load_data(symbol, fromdate, todate)
    if d is None:
        return None
    cerebro.adddata(d, name=symbol)

    if strategy_name == '买入持有':
        cerebro.addstrategy(strategy_class, pos_size=0.95, start_dt=fromdate)
    else:
        cerebro.addstrategy(strategy_class, start_dt=fromdate, **kwargs)

    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe',
                        riskfreerate=0.05, annualize=True,
                        timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_ret = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL
    ann_ret = (1 + total_ret) ** (1 / max(years, 0.01)) - 1

    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
    max_dd = strat.analyzers.dd.get_analysis().get('max', {}).get('drawdown', 0) or 0
    trade_a = strat.analyzers.trades.get_analysis()

    total_trades = getattr(strat, '_trade_count', 1)
    won = trade_a.get('won', {}).get('total', 0) or 0
    lost = trade_a.get('lost', {}).get('total', 0) or 0
    win_rate = won / max(won + lost, 1) * 100
    won_pnl = trade_a.get('won', {}).get('pnl', {}).get('total', 0) or 0
    lost_pnl = abs(trade_a.get('lost', {}).get('pnl', {}).get('total', 1e-10) or 1e-10)
    pf = won_pnl / max(lost_pnl, 1e-10)

    return {
        'strategy': strategy_name,
        'final_value': round(final_value, 2),
        'total_return_pct': round(total_ret * 100, 2),
        'annual_return_pct': round(ann_ret * 100, 2),
        'max_drawdown_pct': round(-max_dd, 2),
        'sharpe_ratio': round(sharpe, 3),
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(pf, 2),
    }


def main():
    symbol = 'QQQ'

    print(f"\n{'#'*76}")
    print(f"  RSI(2) vs KDJ-J 均值回归策略对比 — {symbol}")
    print(f"  RSI(2): RSI2<10买入, RSI2>80卖出")
    print(f"  KDJ-J:  J<0买入, J>100卖出")
    print(f"  基准:   买入持有{symbol}")
    print(f"{'#'*76}")

    # 策略配置
    strategies = [
        ('RSI(2)均值回归', RSI2MeanReversion, {'rsi_buy': 10, 'rsi_sell': 80, 'pos_size': 0.95}),
        ('KDJ-J均值回归', KDJJMeanReversion, {'j_buy': 0, 'j_sell': 100, 'k_period': 9, 'pos_size': 0.95}),
        ('买入持有', BuyAndHold, {}),
    ]

    all_period_results = []

    for key, (period_name, start, end, years) in PERIODS.items():
        fromdate = pd.Timestamp(start)
        todate = pd.Timestamp(end)

        print(f"\n{'━'*76}")
        print(f"  📅 {period_name}  ({start} ~ {end})")
        print(f"{'━'*76}")

        period_results = {}
        for strat_name, strat_class, strat_kwargs in strategies:
            r = run_strategy(strat_class, strat_name, symbol, fromdate, todate, years, **strat_kwargs)
            if r:
                period_results[strat_name] = r
                print(f"  {strat_name:<14} 年化: {r['annual_return_pct']:>7.2f}%  "
                      f"回撤: {r['max_drawdown_pct']:>7.2f}%  "
                      f"夏普: {r['sharpe_ratio']:>6.3f}  "
                      f"胜率: {r['win_rate']:>6.2f}%  "
                      f"盈亏比: {r['profit_factor']:>5.2f}  "
                      f"交易: {r['total_trades']:>4}")

        if len(period_results) == 3:
            rsi = period_results['RSI(2)均值回归']
            kdj = period_results['KDJ-J均值回归']
            bnh = period_results['买入持有']

            # 判定该周期胜者
            if rsi['annual_return_pct'] >= kdj['annual_return_pct']:
                winner = 'RSI(2)'
                diff = rsi['annual_return_pct'] - kdj['annual_return_pct']
            else:
                winner = 'KDJ-J'
                diff = kdj['annual_return_pct'] - rsi['annual_return_pct']

            print(f"\n  🏆 本周期胜者: {winner} (+{diff:.2f}%年化)")

            all_period_results.append({
                'period': period_name,
                'rsi': rsi,
                'kdj': kdj,
                'bnh': bnh,
                'winner': winner,
                'diff': round(diff, 2),
            })

    # ===================== 全周期汇总 =====================
    if all_period_results:
        print(f"\n\n{'='*100}")
        print(f"  📊 RSI(2) vs KDJ-J 全周期对比汇总 — {symbol}")
        print(f"{'='*100}")

        # 详细对比表
        print(f"\n  {'周期':<16} │ {'RSI年化%':>9} {'RSI回撤%':>9} {'RSI夏普':>8} │ "
              f"{'KDJ年化%':>9} {'KDJ回撤%':>9} {'KDJ夏普':>8} │ {'胜者':>6} {'差额':>7}")
        print(f"  {'─'*100}")

        rsi_wins = 0
        kdj_wins = 0
        rsi_dd_wins = 0
        kdj_dd_wins = 0

        for r in all_period_results:
            winner_mark = 'RSI(2)' if r['winner'] == 'RSI(2)' else 'KDJ-J'
            if r['winner'] == 'RSI(2)':
                rsi_wins += 1
            else:
                kdj_wins += 1
            if r['rsi']['max_drawdown_pct'] >= r['kdj']['max_drawdown_pct']:  # 回撤是负数, 越大(越接近0)越好
                rsi_dd_wins += 1
            else:
                kdj_dd_wins += 1

            print(f"  {r['period']:<16} │ {r['rsi']['annual_return_pct']:>9.2f} {r['rsi']['max_drawdown_pct']:>9.2f} "
                  f"{r['rsi']['sharpe_ratio']:>8.3f} │ {r['kdj']['annual_return_pct']:>9.2f} "
                  f"{r['kdj']['max_drawdown_pct']:>9.2f} {r['kdj']['sharpe_ratio']:>8.3f} │ "
                  f"{winner_mark:>6} {r['diff']:>+7.2f}")

        # 综合评价
        print(f"\n  {'━'*100}")
        print(f"  📋 综合评价")
        print(f"  {'━'*100}")

        full = next((r for r in all_period_results if '全周期' in r['period']), None)
        if full:
            print(f"\n  【全周期(2020-24)核心指标】")
            print(f"  ┌─────────────┬────────────┬────────────┬────────────┐")
            print(f"  │   指标      │  RSI(2)    │   KDJ-J    │   买入持有  │")
            print(f"  ├─────────────┼────────────┼────────────┼────────────┤")
            print(f"  │ 年化收益    │ {full['rsi']['annual_return_pct']:>8.2f}%  │ {full['kdj']['annual_return_pct']:>8.2f}%  │ {full['bnh']['annual_return_pct']:>8.2f}%  │")
            print(f"  │ 最大回撤    │ {full['rsi']['max_drawdown_pct']:>8.2f}%  │ {full['kdj']['max_drawdown_pct']:>8.2f}%  │ {full['bnh']['max_drawdown_pct']:>8.2f}%  │")
            print(f"  │ 夏普比率    │ {full['rsi']['sharpe_ratio']:>9.3f} │ {full['kdj']['sharpe_ratio']:>9.3f} │ {full['bnh']['sharpe_ratio']:>9.3f} │")
            print(f"  │ 胜率        │ {full['rsi']['win_rate']:>8.2f}%  │ {full['kdj']['win_rate']:>8.2f}%  │ {full['bnh']['win_rate']:>8.2f}%  │")
            print(f"  │ 盈亏比      │ {full['rsi']['profit_factor']:>9.2f} │ {full['kdj']['profit_factor']:>9.2f} │ {full['bnh']['profit_factor']:>9.2f} │")
            print(f"  │ 交易次数    │ {full['rsi']['total_trades']:>9} │ {full['kdj']['total_trades']:>9} │ {full['bnh']['total_trades']:>9} │")
            print(f"  │ 最终净值$   │ {full['rsi']['final_value']:>9,.2f} │ {full['kdj']['final_value']:>9,.2f} │ {full['bnh']['final_value']:>9,.2f} │")
            print(f"  └─────────────┴────────────┴────────────┴────────────┘")

        print(f"\n  【分周期胜出统计】")
        print(f"  年化收益胜出: RSI(2) {rsi_wins}次 vs KDJ-J {kdj_wins}次")
        print(f"  回撤控制胜出: RSI(2) {rsi_dd_wins}次 vs KDJ-J {kdj_dd_wins}次")

        # 各周期详细对比
        print(f"\n  【各周期详细分析】")
        for r in all_period_results:
            rsi_r = r['rsi']
            kdj_r = r['kdj']
            ann_diff = rsi_r['annual_return_pct'] - kdj_r['annual_return_pct']
            dd_diff = rsi_r['max_drawdown_pct'] - kdj_r['max_drawdown_pct']
            sharpe_diff = rsi_r['sharpe_ratio'] - kdj_r['sharpe_ratio']

            if ann_diff > 2:
                ann_verdict = f"RSI(2)明显领先 +{ann_diff:.2f}%"
            elif ann_diff > 0:
                ann_verdict = f"RSI(2)微弱领先 +{ann_diff:.2f}%"
            elif ann_diff > -2:
                ann_verdict = f"KDJ-J微弱领先 +{-ann_diff:.2f}%"
            else:
                ann_verdict = f"KDJ-J明显领先 +{-ann_diff:.2f}%"

            print(f"  {r['period']}: {ann_verdict} | 回撤差: {dd_diff:+.2f}% | 夏普差: {sharpe_diff:+.3f}")

    print(f"\n{'='*76}")
    print(f"  ✅ RSI(2) vs KDJ-J 对比回测完成")
    print(f"{'='*76}\n")


if __name__ == '__main__':
    main()
