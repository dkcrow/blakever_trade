#!/usr/bin/env python3
"""
RSI(2) Strict Mean Reversion vs Buy & Hold - QQQ 对比回测
==========================================================
对比RSI(2)严格均值回归策略与一直持有QQQ的表现
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

# 回测周期
PERIODS = {
    'bull1': ('牛市(2019-21)', '2019-01-01', '2021-12-31', 3.0),
    'bear':  ('熊市(2022)',    '2022-01-01', '2022-12-31', 1.0),
    'range': ('震荡(2023)',    '2023-01-01', '2023-12-31', 1.0),
    'bull2': ('牛市(2024)',    '2024-01-01', '2024-12-31', 1.0),
    'full':  ('全周期(2020-24)', '2020-01-01', '2024-12-31', 5.0),
}


def calc_rsi2(closes):
    if len(closes) < 3:
        return np.nan
    deltas = np.diff(closes[-3:])
    gains = deltas[deltas > 0].sum() if any(deltas > 0) else 0
    losses = -deltas[deltas < 0].sum() if any(deltas < 0) else 1e-10
    rs = gains / losses
    return 100 - (100 / (1 + rs))


class RSI2Strict(bt.Strategy):
    """RSI(2)严格均值回归策略"""
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


class BuyAndHold(bt.Strategy):
    """买入持有策略 - 首日全仓买入后持有不动"""
    params = (
        ('pos_size', 0.95),
        ('start_dt', None),
    )

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
        invest = cash * self.p.pos_size
        size = int(invest / price)
        if size > 0:
            self.buy(data=d, size=size)
            self._bought = True


def load_data(symbol, fromdate, todate, preload_days=60):
    """加载QQQ数据"""
    # 尝试多个路径
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
            print(f"  ⚠️ {symbol} 数据不足50行: {len(df)}")
            return None
        df = df.set_index('date')
        return bt.feeds.PandasData(dataname=df)
    except Exception as e:
        print(f"  ⚠️ 加载 {symbol} 失败: {e}")
        return None


def run_comparison(symbol, period_name, start_str, end_str, years):
    """运行RSI2策略 vs 买入持有对比"""
    fromdate = pd.Timestamp(start_str)
    todate = pd.Timestamp(end_str)

    d = load_data(symbol, fromdate, todate)
    if d is None:
        return None

    results = {}

    for strategy_name, strategy_class in [('RSI(2)均值回归', RSI2Strict), ('买入持有', BuyAndHold)]:
        cerebro = bt.Cerebro(stdstats=False, runonce=False)
        cerebro.broker.setcash(INITIAL_CAPITAL)
        cerebro.broker.setcommission(commission=COMMISSION)
        cerebro.adddata(d, name=symbol)

        if strategy_name == 'RSI(2)均值回归':
            cerebro.addstrategy(strategy_class, rsi_buy=10, rsi_sell=80, pos_size=0.95, start_dt=fromdate)
        else:
            cerebro.addstrategy(strategy_class, pos_size=0.95, start_dt=fromdate)

        cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe',
                            riskfreerate=0.05, annualize=True,
                            timeframe=bt.TimeFrame.Days)
        cerebro.addanalyzer(btanalyzers.DrawDown, _name='dd')
        cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')
        cerebro.addanalyzer(btanalyzers.Returns, _name='returns')

        run_results = cerebro.run()
        strat = run_results[0]

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

        results[strategy_name] = {
            'final_value': round(final_value, 2),
            'total_return_pct': round(total_ret * 100, 2),
            'annual_return_pct': round(ann_ret * 100, 2),
            'max_drawdown_pct': round(-max_dd, 2),
            'sharpe_ratio': round(sharpe, 3),
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
        }

    return results


def main():
    symbol = 'QQQ'
    print(f"\n{'#'*70}")
    print(f"  RSI(2)严格均值回归 vs 买入持有 — {symbol} 对比回测")
    print(f"  RSI2<10买入 | RSI2>80卖出 | 95%仓位")
    print(f"{'#'*70}")

    all_results = []

    for key, (name, start, end, years) in PERIODS.items():
        print(f"\n{'─'*70}")
        print(f"  📅 {name}  ({start} ~ {end})")
        print(f"{'─'*70}")

        r = run_comparison(symbol, name, start, end, years)
        if r is None:
            continue

        rsi = r['RSI(2)均值回归']
        bnh = r['买入持有']

        # 计算超额收益
        excess_ann = rsi['annual_return_pct'] - bnh['annual_return_pct']
        excess_dd = rsi['max_drawdown_pct'] - bnh['max_drawdown_pct']  # 负=更好

        print(f"\n  {'指标':<16} {'RSI(2)均值回归':>16} {'买入持有':>16} {'差异':>14}")
        print(f"  {'─'*66}")
        print(f"  {'最终净值($)':<16} {rsi['final_value']:>16,.2f} {bnh['final_value']:>16,.2f} {rsi['final_value']-bnh['final_value']:>+14,.2f}")
        print(f"  {'总收益(%)':<16} {rsi['total_return_pct']:>16.2f} {bnh['total_return_pct']:>16.2f} {rsi['total_return_pct']-bnh['total_return_pct']:>+14.2f}")
        print(f"  {'年化收益(%)':<16} {rsi['annual_return_pct']:>16.2f} {bnh['annual_return_pct']:>16.2f} {excess_ann:>+14.2f}")
        print(f"  {'最大回撤(%)':<16} {rsi['max_drawdown_pct']:>16.2f} {bnh['max_drawdown_pct']:>16.2f} {excess_dd:>+14.2f}")
        print(f"  {'夏普比率':<16} {rsi['sharpe_ratio']:>16.3f} {bnh['sharpe_ratio']:>16.3f} {rsi['sharpe_ratio']-bnh['sharpe_ratio']:>+14.3f}")
        print(f"  {'交易次数':<16} {rsi['total_trades']:>16} {bnh['total_trades']:>16}")
        print(f"  {'胜率(%)':<16} {rsi['win_rate']:>16.2f} {bnh['win_rate']:>16.2f}")

        if excess_ann > 0:
            verdict = f"✅ RSI(2)策略年化超额 +{excess_ann:.2f}%"
        else:
            verdict = f"⚠️ RSI(2)策略年化落后 {excess_ann:.2f}%"
        print(f"\n  结论: {verdict}")

        all_results.append({
            'period': name,
            'rsi': rsi,
            'bnh': bnh,
            'excess_ann': round(excess_ann, 2),
            'excess_dd': round(excess_dd, 2),
        })

    # 总览表
    if all_results:
        print(f"\n\n{'='*90}")
        print(f"  📊 {symbol} 全周期对比汇总")
        print(f"{'='*90}")
        print(f"  {'周期':<16} {'RSI年化%':>10} {'持有年化%':>10} {'超额%':>8} {'RSI回撤%':>10} {'持有回撤%':>10} {'回撤差':>8} {'RSI夏普':>10} {'持有夏普':>10}")
        print(f"  {'─'*90}")
        for r in all_results:
            print(f"  {r['period']:<16} {r['rsi']['annual_return_pct']:>10.2f} {r['bnh']['annual_return_pct']:>10.2f} "
                  f"{r['excess_ann']:>+8.2f} {r['rsi']['max_drawdown_pct']:>10.2f} {r['bnh']['max_drawdown_pct']:>10.2f} "
                  f"{r['excess_dd']:>+8.2f} {r['rsi']['sharpe_ratio']:>10.3f} {r['bnh']['sharpe_ratio']:>10.3f}")

        print(f"\n  💡 核心发现:")
        # 统计胜出次数
        rsi_wins = sum(1 for r in all_results if r['excess_ann'] > 0)
        bnh_wins = sum(1 for r in all_results if r['excess_ann'] <= 0)
        dd_wins = sum(1 for r in all_results if r['excess_dd'] < 0)

        full = next((r for r in all_results if '全周期' in r['period']), None)
        if full:
            print(f"     全周期: RSI(2)年化 {full['rsi']['annual_return_pct']}% vs 持有 {full['bnh']['annual_return_pct']}%")
            print(f"            RSI(2)回撤 {full['rsi']['max_drawdown_pct']}% vs 持有 {full['bnh']['max_drawdown_pct']}%")
            print(f"            RSI(2)夏普 {full['rsi']['sharpe_ratio']} vs 持有 {full['bnh']['sharpe_ratio']}")
        print(f"     年化收益胜出: RSI(2) {rsi_wins}次 vs 买入持有 {bnh_wins}次")
        print(f"     回撤控制胜出: RSI(2) {dd_wins}次 vs 买入持有 {len(all_results)-dd_wins}次")

    print(f"\n{'='*70}")
    print(f"  ✅ 对比回测完成")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
