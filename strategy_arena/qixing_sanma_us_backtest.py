#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马七星ETF策略 - 美股版本回测
==============================
使用yfinance获取数据，Backtrader框架回测

成分股：
- 美股大盘：QQQ, SPY, DIA, IWM
- 大宗商品：GLD, SLV, USO
- 债券：AGG
- 行业：SMH
- 货币基金：JPST
"""

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import sys
import os
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

# ================================================================
# 配置
# ================================================================
ETF_LIST = {
    'QQQ': '纳斯达克100',
    'SPY': '标普500',
    'DIA': '道琼斯',
    'IWM': '罗素2000',
    'GLD': '黄金',
    'SLV': '白银',
    'USO': '原油',
    'AGG': '综合债券',
    'SMH': '半导体',
    'JPST': '超短债',
}

INITIAL_CASH = 100000.0  # 初始资金
COMMISSION = 0.0015      # 佣金 0.15%

# 策略参数
SHORT_LOOKBACK = 25
LONG_LOOKBACK = 250
STOP_LOSS_PCT = 0.08
PROFIT_PROTECT_PCT = 0.05
HIGH20_LOOKBACK = 20

# ================================================================
# 数据获取
# ================================================================
LOCAL_DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'

def fetch_data(ticker, start, end):
    """获取美股ETF数据（优先本地，失败则yfinance）"""
    # 先尝试本地数据
    local_path = os.path.join(LOCAL_DATA_DIR, f'{ticker}.csv')
    if os.path.exists(local_path):
        try:
            df = pd.read_csv(local_path)
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
            # 过滤日期范围
            df = df[(df.index >= start) & (df.index <= end)]
            if len(df) >= 50:
                # 标准化列名
                col_map = {}
                for c in df.columns:
                    c_lower = c.lower()
                    if c_lower in ['open', 'high', 'low', 'close', 'volume']:
                        col_map[c] = c_lower
                df = df.rename(columns=col_map)
                df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
                print(f'  [OK-local] {ticker}: {len(df)} rows {df.index[0].date()} ~ {df.index[-1].date()}')
                return df
        except Exception as e:
            print(f'  [local-fail] {ticker}: {e}')
    
    # 本地没有，尝试yfinance
    try:
        df = yf.download(ticker, start=start, end=end, progress=False)
        if len(df) < 50:
            print(f'  ⚠️ {ticker} 数据不足: {len(df)} 行')
            return None
        # 处理多级列名
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
        print(f'  [OK-yf] {ticker}: {len(df)} rows {df.index[0].date()} ~ {df.index[-1].date()}')
        return df
    except Exception as e:
        print(f'  [FAIL] {ticker}: {e}')
        return None

# ================================================================
# 动量计算
# ================================================================
def weighted_reg(prices_list):
    """加权线性回归：返回(年化收益率, R², 动量得分)"""
    n = len(prices_list)
    if n < 5:
        return 0, 0, 0
    y = [np.log(max(p, 0.001)) for p in prices_list]
    x = np.arange(n)
    w = np.linspace(1, 2, n)  # 线性加权
    w_sum = w.sum()
    xm = (w * x).sum() / w_sum
    ym = (w * y).sum() / w_sum
    num = (w * (x - xm) * (y - ym)).sum()
    den = (w * (x - xm) ** 2).sum()
    slope = num / den if abs(den) > 1e-10 else 0
    ss_tot = (w * (y - ym) ** 2).sum()
    y_pred = slope * (x - xm) + ym
    ss_res = (w * (y - y_pred) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0
    ann_return = np.exp(slope * 252) - 1
    return ann_return, r2, ann_return * r2

def score_etf(prices_list, short_n=25, long_n=250):
    """计算ETF动量得分（短期×1 + 长期×0.5）"""
    if len(prices_list) < 5:
        return None, None, None
    sp = prices_list[-short_n:]
    lp = prices_list[-long_n:] if len(prices_list) >= long_n else prices_list
    ann_s, r2_s, score_s = weighted_reg(sp)
    ann_l, r2_l, score_l = weighted_reg(lp)
    # 近4日急跌过滤
    if len(sp) >= 4:
        for i in range(len(sp) - 1):
            if sp[i] > 0 and sp[i + 1] / sp[i] < 0.95:
                score_s = 0
                break
    return score_s, score_l * 0.5, score_s + score_l * 0.5

# ================================================================
# Backtrader 策略
# ================================================================
class QixingSanmaUS(bt.Strategy):
    params = (
        ('short_lookback', SHORT_LOOKBACK),
        ('long_lookback', LONG_LOOKBACK),
        ('stop_loss_pct', STOP_LOSS_PCT),
        ('profit_protect_pct', PROFIT_PROTECT_PCT),
        ('high20_lookback', HIGH20_LOOKBACK),
    )

    def __init__(self):
        self.etf_data = {}  # {name: data}
        self.scores = {}    # {name: total_score}
        self.holdings = {}  # {name: {'entry_price': x, 'high20': y}}
        self.order = None

        # 收集所有ETF数据
        for i, d in enumerate(self.datas):
            name = d._name
            self.etf_data[name] = d

    def next(self):
        # 计算每个ETF的动量得分
        current_scores = {}
        for name, d in self.etf_data.items():
            if len(d) < self.p.long_lookback + 5:
                continue
            prices = [d.close[i] for i in range(-self.p.long_lookback, 0)]
            prices.append(d.close[0])
            score_s, score_l, total = score_etf(prices, self.p.short_lookback, self.p.long_lookback)
            if total is not None:
                current_scores[name] = {
                    'total': total,
                    'short': score_s,
                    'long': score_l,
                    'price': d.close[0],
                    'prev_close': d.close[-1] if len(d) > 1 else d.close[0],
                }

        if not current_scores:
            return

        # 排名
        ranked = sorted(current_scores.items(), key=lambda x: x[1]['total'], reverse=True)
        top_etf = ranked[0][0]
        top_score = ranked[0][1]['total']

        # 止损检测
        to_remove = []
        for name, pos in self.holdings.items():
            d = self.etf_data[name]
            price = d.close[0]
            entry_price = pos['entry_price']
            high20 = pos['high20']

            # 硬止损
            if price / entry_price - 1 <= -self.p.stop_loss_pct:
                self.close(data=d)
                print(f'  [STOP] Hard stop {name}: {price:.2f} (entry:{entry_price:.2f})')
                to_remove.append(name)
                continue

            # 盈利保护
            if high20 > 0 and price / high20 - 1 <= -self.p.profit_protect_pct:
                self.close(data=d)
                print(f'  [PROTECT] Profit protect {name}: {price:.2f} (high:{high20:.2f})')
                to_remove.append(name)
                continue

            # 更新20日高点
            recent_prices = [d.close[i] for i in range(-self.p.high20_lookback + 1, 1)]
            pos['high20'] = max(recent_prices)
        
        for name in to_remove:
            del self.holdings[name]

        # 调仓逻辑：持有最高分ETF
        current_holding = list(self.holdings.keys())

        # 如果当前持有且仍是第一，保持
        if current_holding and current_holding[0] == top_etf:
            return

        # 卖出当前持仓
        for name in current_holding:
            d = self.etf_data[name]
            self.close(data=d)
            print(f'  [SELL] {name}: {d.close[0]:.2f}')
            del self.holdings[name]

        # 买入新的Top1
        if top_score > 0:  # 只买入正得分
            d = self.etf_data[top_etf]
            size = int(self.broker.getcash() * 0.95 / d.close[0])  # 95%资金
            if size > 0:
                self.buy(data=d, size=size)
                recent_prices = [d.close[i] for i in range(-self.p.high20_lookback + 1, 1)]
                self.holdings[top_etf] = {
                    'entry_price': d.close[0],
                    'high20': max(recent_prices)
                }
                print(f'  [BUY] {top_etf}: {d.close[0]:.2f} x{size} (score:{top_score:.4f})')

# ================================================================
# 回测执行
# ================================================================
def run_backtest(start_date='2021-01-01', end_date='2026-05-18'):
    print(f'\n{"="*60}')
    print(f'三马七星美股ETF策略回测')
    print(f'{"="*60}')
    print(f'回测周期: {start_date} ~ {end_date}')
    print(f'初始资金: ${INITIAL_CASH:,.2f}')
    print(f'交易成本: {COMMISSION*100:.2f}%')
    print(f'\n获取数据...')

    # 获取数据
    cerebro = bt.Cerebro()
    valid_etfs = {}

    for ticker, name in ETF_LIST.items():
        df = fetch_data(ticker, start_date, end_date)
        if df is not None and len(df) >= 260:
            data = bt.feeds.PandasData(
                dataname=df,
                name=ticker,
                datetime=None,
                open='open',
                high='high',
                low='low',
                close='close',
                volume='volume',
            )
            cerebro.adddata(data)
            valid_etfs[ticker] = name

    if len(valid_etfs) < 3:
        print(f'❌ 有效ETF不足 ({len(valid_etfs)}只)，无法回测')
        return None

    print(f'\n有效ETF: {len(valid_etfs)}只')
    for t, n in valid_etfs.items():
        print(f'  {t}: {n}')

    # 配置回测
    cerebro.addstrategy(QixingSanmaUS)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    print(f'\n开始回测...')
    results = cerebro.run()
    strat = results[0]

    # 结果分析
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100

    print(f'\n{"="*60}')
    print(f'回测结果')
    print(f'{"="*60}')
    print(f'最终资产: ${final_value:,.2f}')
    print(f'总收益率: {total_return:.2f}%')

    # 交易统计
    trades = strat.analyzers.trades.get_analysis()
    if trades.get('total'):
        total_trades = trades['total']['total']
        won_trades = trades['won']['total'] if trades.get('won') else 0
        lost_trades = trades['lost']['total'] if trades.get('lost') else 0
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
        print(f'总交易次数: {total_trades}')
        print(f'盈利次数: {won_trades}')
        print(f'亏损次数: {lost_trades}')
        print(f'胜率: {win_rate:.1f}%')

        if trades.get('won') and trades.get('lost'):
            avg_win = trades['won']['pnl']['average'] if trades['won'].get('pnl') else 0
            avg_loss = abs(trades['lost']['pnl']['average']) if trades['lost'].get('pnl') else 0
            pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            print(f'平均盈利: ${avg_win:.2f}')
            print(f'平均亏损: ${avg_loss:.2f}')
            print(f'盈亏比: {pl_ratio:.2f}')

    # 夏普比率
    sharpe = strat.analyzers.sharpe.get_analysis()
    if sharpe and sharpe.get('sharperatio'):
        print(f'夏普比率: {sharpe["sharperatio"]:.2f}')

    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if dd:
        print(f'最大回撤: {dd.get("max", {}).get("drawdown", 0):.2f}%')

    # 年化收益
    returns = strat.analyzers.returns.get_analysis()
    if returns and returns.get('rnorm100'):
        print(f'年化收益率: {returns["rnorm100"]:.2f}%')

    return {
        'final_value': final_value,
        'total_return': total_return,
        'trades': trades,
        'sharpe': sharpe,
        'drawdown': dd,
        'returns': returns,
    }

if __name__ == '__main__':
    # 5年回测
    result = run_backtest('2021-01-01', '2026-05-18')
