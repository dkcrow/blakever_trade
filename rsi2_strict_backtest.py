#!/usr/bin/env python3
"""
RSI(2) Strict Mean Reversion Strategy - Backtest v2
====================================================
基于搜索发现的策略：
- 来源: quantifiedstrategies.com "3 RSI Trading Strategies (Backtested)"
- 来源: tradingwithrayner.com "Mean Reversion Strategy That Works"
- 规则:
    1. RSI(2) < 10 → 收盘买入（极度超卖）
    2. RSI(2) > 80 → 收盘卖出（极度超买）
    3. 只用SPY测试（简单，有学术背书）
- 参考 backtrader_v13.py 框架结构
"""
import os, argparse, warnings
import pandas as pd
import numpy as np
import backtrader as bt
import backtrader.analyzers as btanalyzers

warnings.filterwarnings('ignore')

# 适配实际数据路径
DATA_DIR = '/data/workspace/back_trader_stocks'
INITIAL_CAPITAL = 100_000.0
COMMISSION = 0.001

PERIODS = {
    'bull1': ('牛市1(2019-21)', '2019-01-01', '2021-12-31', 3.0),
    'bear':  ('熊市(2022)',      '2022-01-01', '2022-12-31', 1.0),
    'range': ('震荡(2023)',      '2023-01-01', '2023-12-31', 1.0),
    'bull2': ('牛市2(2024)',     '2024-01-01', '2024-12-31', 1.0),
    'full':  ('全周期(2020-24)', '2020-01-01', '2024-12-31', 5.0),
}

# 标的符号映射: 策略名 → (数据子目录, 文件名)
TARGET_SYMBOLS = {
    'SPY': ('etf', 'SPY'),
    'QQQ': ('etf', 'QQQ'),
    'IWM': ('us',  'IWM'),
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
    params = (
        ('rsi_buy',   10),
        ('rsi_sell',  80),
        ('pos_size', 0.95),
        ('start_dt', None),
        ('verbose',  False),
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
                    if self.p.verbose:
                        print(f"  BUY {d._name} RSI2={rsi2:.1f} @ {price:.2f}")

        elif rsi2 > self.p.rsi_sell and pos.size > 0:
            if self._order_ref is None:
                o = self.sell(data=d, size=pos.size)
                self._order_ref = o.ref
                if self.p.verbose:
                    print(f"  SELL {d._name} RSI2={rsi2:.1f} @ {price:.2f}")

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self._order_ref = None
            if order.status == order.Completed:
                self._trade_count += 1

    def stop(self):
        print(f"  RSI2策略交易次数: {self._trade_count}, 最终净值: {self.broker.getvalue():.2f}")


def load_data(symbol_key, fromdate, todate, preload_days=60):
    """加载数据，symbol_key 为 TARGET_SYMBOLS 的键名"""
    subdir, fname = TARGET_SYMBOLS[symbol_key]
    path = os.path.join(DATA_DIR, subdir, f'{fname}.csv')
    if not os.path.exists(path):
        print(f"  ⚠️ 数据文件不存在: {path}")
        return None
    try:
        df = pd.read_csv(path)
        # 统一列名为小写
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        df = df[(df['close'] > 0.01) & (df['open'] > 0.01) &
                (df['high'] > 0.01) & (df['low'] > 0.01) &
                (df['high'] >= df['low'])].copy()
        pre_from = fromdate - pd.Timedelta(days=preload_days)
        df = df[(df['date'] >= pre_from) & (df['date'] <= todate)].copy()
        if len(df) < 50:
            print(f"  ⚠️ {symbol_key} 数据不足50行: {len(df)}")
            return None
        df = df.set_index('date')
        return bt.feeds.PandasData(dataname=df)
    except Exception as e:
        print(f"  ⚠️ 加载 {symbol_key} 失败: {e}")
        return None


def run_single(symbol, period_name, start_str, end_str, years, verbose=False):
    fromdate = pd.Timestamp(start_str)
    todate = pd.Timestamp(end_str)

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=COMMISSION)

    d = load_data(symbol, fromdate, todate)
    if d is None:
        return None
    cerebro.adddata(d, name=symbol)

    cerebro.addstrategy(
        RSI2Strict, rsi_buy=10, rsi_sell=80, pos_size=0.95,
        start_dt=fromdate, verbose=verbose,
    )

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

    total_trades = strat._trade_count
    won = trade_a.get('won', {}).get('total', 0) or 0
    lost = trade_a.get('lost', {}).get('total', 0) or 0
    win_rate = won / max(won + lost, 1) * 100
    won_pnl = trade_a.get('won', {}).get('pnl', {}).get('total', 0) or 0
    lost_pnl = abs(trade_a.get('lost', {}).get('pnl', {}).get('total', 1e-10) or 1e-10)
    pf = won_pnl / max(lost_pnl, 1e-10)
    trades_per_year = total_trades / max(years, 0.01)

    print(f"  [{symbol}] 年化收益: {ann_ret*100:>8.2f}% | 最大回撤: {-max_dd:>7.2f}% | "
          f"夏普: {sharpe:>6.3f} | 胜率: {win_rate:>6.2f}% | 盈亏比: {pf:>5.2f} | 笔/年: {trades_per_year:>6.1f}")

    return {
        'symbol': symbol,
        'period': period_name,
        'annual_return_pct': round(ann_ret * 100, 2),
        'max_drawdown_pct': round(-max_dd, 2),
        'sharpe_ratio': round(sharpe, 3),
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(pf, 2),
        'trades_per_year': round(trades_per_year, 1),
        'final_value': round(final_value, 2),
    }


def run_backtest(period_name, start_str, end_str, years, verbose=False):
    print(f"\n{'='*60}")
    print(f"  周期: {period_name}  ({start_str} ~ {end_str})")
    print(f"  加载数据中...")

    results = []
    for sym in TARGET_SYMBOLS:
        r = run_single(sym, period_name, start_str, end_str, years, verbose=verbose)
        if r:
            results.append(r)

    if not results:
        print("  无可用数据")
        return None

    best = max(results, key=lambda x: x['annual_return_pct'])

    print(f"\n{'─'*60}")
    print(f"  【RSI(2) Strict - {period_name} 汇总】")
    print(f"{'─'*60}")
    print(f"  最佳标的:   {best['symbol']}")
    print(f"  年化收益:   {best['annual_return_pct']:>11.2f}%")
    print(f"  最大回撤:   {best['max_drawdown_pct']:>11.2f}%")
    print(f"  夏普比率:   {best['sharpe_ratio']:>12.3f}")
    print(f"  总交易次数: {best['total_trades']:>12}")
    print(f"  胜率:       {best['win_rate']:>11.2f}%")
    print(f"  盈亏比:     {best['profit_factor']:>12.2f}")
    print(f"  笔/年:      {best['trades_per_year']:>12.1f}")

    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='full', choices=list(PERIODS.keys()))
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--output', default=None, help='输出JSON文件路径')
    args = parser.parse_args()

    print(f"\n{'#'*60}")
    print(f"  RSI(2) Strict Mean Reversion - Backtrader Backtest")
    print(f"  backtrader {bt.__version__}")
    print(f"  策略: RSI2<10买入 | RSI2>80卖出 | T+1执行")
    print(f"{'#'*60}")

    periods_to_run = list(PERIODS.items()) if args.all else [(args.period, PERIODS[args.period])]
    bt_results = []
    for key, (name, start, end, years) in periods_to_run:
        r = run_backtest(name, start, end, years, verbose=args.verbose)
        if r:
            bt_results.append(r)

    if len(bt_results) > 1:
        print(f"\n\n{'='*80}")
        print(f"  📊 RSI(2) Strict策略 - 多周期汇总")
        print(f"{'='*80}")
        print(f"{'周期':<20} {'年化%':>8} {'回撤%':>8} {'夏普':>8} {'胜率%':>8} {'盈亏比':>8} {'笔/年':>8}")
        print(f"{'─'*80}")
        for r in bt_results:
            print(f"{r['period']:<20} {r['annual_return_pct']:>8.2f} {r['max_drawdown_pct']:>8.2f} "
                  f"{r['sharpe_ratio']:>8.3f} {r['win_rate']:>8.2f} {r['profit_factor']:>8.2f} {r['trades_per_year']:>8.1f}")

    # 输出JSON（供调度器统一评分）
    if args.output and bt_results:
        import json as _json
        # 输出所有标的+周期的结果列表，方便调度器逐个评分
        output_data = bt_results
        with open(args.output, 'w', encoding='utf-8') as f:
            _json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  📁 结果已保存至: {args.output} ({len(bt_results)}个结果)")

    print(f"\n{'='*60}")
    print(f"  ✅ RSI2 Strict回测完成")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
