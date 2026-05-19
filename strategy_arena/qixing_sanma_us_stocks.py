#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马七星策略 - 美股个股版本回测
==============================
成分股：NVDA, SNDK, AMD, MU, AVGO, TSLA, AAPL, GOOG, AMZN, KO, NEM, XOM, AEP, JPM, GS, BRK-B
使用Backtrader框架，10年回测
"""

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import sys
import os
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

# ================================================================
# 配置
# ================================================================
STOCK_LIST = {
    'NVDA': '英伟达',
    'SNDK': 'Sandisk',
    'AMD': '超微半导体',
    'MU': '美光科技',
    'AVGO': '博通',
    'TSLA': '特斯拉',
    'AAPL': '苹果',
    'GOOG': '谷歌',
    'AMZN': '亚马逊',
    'KO': '可口可乐',
    'NEM': '纽曼矿业',
    'XOM': '埃克森美孚',
    'AEP': '美国电力',
    'JPM': '摩根大通',
    'GS': '高盛',
    'BRK-B': '伯克希尔-B',
}

INITIAL_CASH = 100000.0  # 初始资金$10万
COMMISSION = 0.0015      # 佣金 0.15%

# 策略参数（与原版一致）
SHORT_LOOKBACK = 25      # 短期回看25日
LONG_LOOKBACK = 250      # 长期回看250日
STOP_LOSS_PCT = 0.08     # 硬止损8%
PROFIT_PROTECT_PCT = 0.05  # 盈利保护5%回撤
HIGH20_LOOKBACK = 20     # 20日高点

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks'

# ================================================================
# 动量计算（与原版完全一致）
# ================================================================
def weighted_reg(prices_list):
    """加权线性回归：返回(年化收益率, R², 动量得分)"""
    n = len(prices_list)
    if n < 5:
        return 0, 0, 0
    y = [np.log(max(p, 0.001)) for p in prices_list]
    x = np.arange(n)
    w = np.linspace(1, 2, n)  # 线性加权，近期权重更高
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
    """计算动量得分（短期×1 + 长期×0.5）"""
    if len(prices_list) < 5:
        return None, None, None
    sp = prices_list[-short_n:]
    lp = prices_list[-long_n:] if len(prices_list) >= long_n else prices_list
    ann_s, r2_s, score_s = weighted_reg(sp)
    ann_l, r2_l, score_l = weighted_reg(lp)
    # 近4日急跌过滤（与原版一致）
    if len(sp) >= 4:
        for i in range(len(sp) - 1):
            if sp[i] > 0 and sp[i + 1] / sp[i] < 0.95:
                score_s = 0
                break
    return score_s, score_l * 0.5, score_s + score_l * 0.5

# ================================================================
# 数据加载
# ================================================================
def load_stock_data(symbol, start_date, end_date):
    """从本地CSV加载股票数据"""
    filepath = os.path.join(DATA_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        print(f'  [MISSING] {symbol}: 文件不存在')
        return None
    
    try:
        df = pd.read_csv(filepath)
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)
            df.set_index('Date', inplace=True)
        
        # 转换日期参数为Timestamp
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        
        # 过滤日期范围
        df = df[(df.index >= start_ts) & (df.index <= end_ts)]
        
        if len(df) < 260:
            print(f'  [WARN] {symbol}: 数据不足 {len(df)} 行')
            return None
        
        # 标准化列名
        col_map = {}
        for c in df.columns:
            c_lower = c.lower().strip()
            if c_lower in ['open', 'high', 'low', 'close', 'volume']:
                col_map[c] = c_lower
            elif c_lower == 'adj close' or c_lower == 'adj_close':
                col_map[c] = 'close'
        
        df = df.rename(columns=col_map)
        
        # 确保必要列存在
        required = ['open', 'high', 'low', 'close']
        for col in required:
            if col not in df.columns:
                print(f'  [ERR] {symbol}: 缺少{col}列')
                return None
        
        if 'volume' not in df.columns:
            df['volume'] = 0
        
        df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
        
        print(f'  [OK] {symbol}: {len(df)} rows {df.index[0].date()} ~ {df.index[-1].date()}')
        return df
        
    except Exception as e:
        print(f'  [ERR] {symbol}: {str(e)[:60]}')
        return None

# ================================================================
# Backtrader 策略（与原版逻辑一致）
# ================================================================
class QixingSanmaStocks(bt.Strategy):
    params = (
        ('short_lookback', SHORT_LOOKBACK),
        ('long_lookback', LONG_LOOKBACK),
        ('stop_loss_pct', STOP_LOSS_PCT),
        ('profit_protect_pct', PROFIT_PROTECT_PCT),
        ('high20_lookback', HIGH20_LOOKBACK),
    )

    def __init__(self):
        self.stock_data = {}   # {name: data}
        self.scores = {}       # {name: total_score}
        self.holdings = {}     # {name: {'entry_price': x, 'high20': y}}
        self.order = None
        self.trade_log = []    # 交易记录

        # 收集所有股票数据
        for i, d in enumerate(self.datas):
            name = d._name
            self.stock_data[name] = d

    def next(self):
        # 计算每个股票的动量得分
        current_scores = {}
        for name, d in self.stock_data.items():
            if len(d) < self.p.long_lookback + 5:
                continue
            
            # 获取价格序列
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

        # 按得分排名
        ranked = sorted(current_scores.items(), key=lambda x: x[1]['total'], reverse=True)
        top_stock = ranked[0][0]
        top_score = ranked[0][1]['total']

        # 止损检测（与原版一致）
        to_remove = []
        for name, pos in list(self.holdings.items()):
            d = self.stock_data[name]
            price = d.close[0]
            entry_price = pos['entry_price']
            high20 = pos['high20']

            # 硬止损 8%
            if price / entry_price - 1 <= -self.p.stop_loss_pct:
                self.close(data=d)
                pnl = (price / entry_price - 1) * 100
                self.trade_log.append({
                    'date': self.datas[0].datetime.date(0),
                    'action': 'STOP',
                    'stock': name,
                    'price': price,
                    'pnl_pct': pnl
                })
                print(f'  [STOP] Hard stop {name}: {price:.2f} (entry:{entry_price:.2f}, pnl:{pnl:.1f}%)')
                to_remove.append(name)
                continue

            # 盈利保护 5%回撤
            if high20 > 0 and price / high20 - 1 <= -self.p.profit_protect_pct:
                self.close(data=d)
                pnl = (price / entry_price - 1) * 100
                self.trade_log.append({
                    'date': self.datas[0].datetime.date(0),
                    'action': 'PROTECT',
                    'stock': name,
                    'price': price,
                    'pnl_pct': pnl
                })
                print(f'  [PROTECT] Profit protect {name}: {price:.2f} (high:{high20:.2f}, pnl:{pnl:.1f}%)')
                to_remove.append(name)
                continue

            # 更新20日高点（追踪全局最高点）
            pos['high20'] = max(pos['high20'], d.close[0])
        
        for name in to_remove:
            del self.holdings[name]

        # 调仓逻辑：始终持有得分最高的1只股票
        current_holding = list(self.holdings.keys())

        # 如果当前持有且仍是第一，保持（但检查得分是否仍为正）
        if current_holding and current_holding[0] == top_stock:
            # 更新high20
            d = self.stock_data[top_stock]
            self.holdings[top_stock]['high20'] = max(self.holdings[top_stock]['high20'], d.close[0])
            return

        # 卖出当前持仓
        for name in current_holding:
            d = self.stock_data[name]
            entry = self.holdings[name]['entry_price']
            pnl = (d.close[0] / entry - 1) * 100
            self.close(data=d)
            self.trade_log.append({
                'date': self.datas[0].datetime.date(0),
                'action': 'SELL',
                'stock': name,
                'price': d.close[0],
                'pnl_pct': pnl
            })
            print(f'  [SELL] {name}: {d.close[0]:.2f} (pnl:{pnl:+.1f}%)')
            del self.holdings[name]

        # 买入新的Top1（只买正得分）
        if top_score > 0:
            d = self.stock_data[top_stock]
            size = int(self.broker.getcash() * 0.95 / d.close[0])  # 95%资金
            if size > 0:
                self.buy(data=d, size=size)
                # 初始化high20为当前价格
                self.holdings[top_stock] = {
                    'entry_price': d.close[0],
                    'high20': d.close[0]
                }
                self.trade_log.append({
                    'date': self.datas[0].datetime.date(0),
                    'action': 'BUY',
                    'stock': top_stock,
                    'price': d.close[0],
                    'size': size
                })
                print(f'  [BUY] {top_stock}: {d.close[0]:.2f} x{size} (score:{top_score:.4f})')

    def notify_trade(self, trade):
        if trade.isclosed:
            pass

# ================================================================
# 回测执行
# ================================================================
def run_backtest(start_date='2016-05-19', end_date='2026-05-18'):
    print(f'\n{"="*70}')
    print(f'三马七星策略 - 美股个股版本')
    print(f'{"="*70}')
    print(f'回测周期: {start_date} ~ {end_date}')
    print(f'初始资金: ${INITIAL_CASH:,.2f}')
    print(f'交易成本: {COMMISSION*100:.2f}%')
    print(f'成分股数: {len(STOCK_LIST)}只')
    print(f'\n策略参数:')
    print(f'  短期回看: {SHORT_LOOKBACK}日')
    print(f'  长期回看: {LONG_LOOKBACK}日')
    print(f'  硬止损: {STOP_LOSS_PCT*100:.0f}%')
    print(f'  盈利保护: {PROFIT_PROTECT_PCT*100:.0f}%回撤')
    print(f'\n加载数据...')

    # 加载数据
    cerebro = bt.Cerebro()
    valid_stocks = {}

    for symbol, name in STOCK_LIST.items():
        df = load_stock_data(symbol, start_date, end_date)
        if df is not None and len(df) >= 260:
            data = bt.feeds.PandasData(
                dataname=df,
                name=symbol,
                datetime=None,
                open='open',
                high='high',
                low='low',
                close='close',
                volume='volume',
            )
            cerebro.adddata(data)
            valid_stocks[symbol] = name

    if len(valid_stocks) < 3:
        print(f'\n❌ 有效股票不足 ({len(valid_stocks)}只)，无法回测')
        return None

    print(f'\n有效股票: {len(valid_stocks)}/{len(STOCK_LIST)}只')
    for t, n in valid_stocks.items():
        print(f'  {t}: {n}')

    # 配置回测
    cerebro.addstrategy(QixingSanmaStocks)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn', timeframe=bt.TimeFrame.Days)

    print(f'\n开始回测...')
    print(f'{"="*70}')
    results = cerebro.run()
    strat = results[0]

    # 结果汇总
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    years = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days / 365.25
    ann_return = ((final_value / INITIAL_CASH) ** (1/years) - 1) * 100 if years > 0 else 0

    print(f'\n{"="*70}')
    print(f'回测结果汇总')
    print(f'{"="*70}')
    print(f'最终资产:     ${final_value:,.2f}')
    print(f'总收益率:     {total_return:+.2f}%')
    print(f'年化收益率:   {ann_return:+.2f}%')

    # 交易统计
    trades = strat.analyzers.trades.get_analysis()
    if trades.get('total'):
        total_trades = trades['total']['total']
        won_trades = trades['won']['total'] if trades.get('won') else 0
        lost_trades = trades['lost']['total'] if trades.get('lost') else 0
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
        trades_per_year = total_trades / years if years > 0 else 0
        
        print(f'\n交易统计:')
        print(f'  总交易次数: {total_trades} ({trades_per_year:.0f}笔/年)')
        print(f'  盈利次数:   {won_trades}')
        print(f'  亏损次数:   {lost_trades}')
        print(f'  胜率:       {win_rate:.1f}%')

        if trades.get('won') and trades.get('lost'):
            avg_win = trades['won']['pnl']['average'] if trades['won'].get('pnl') else 0
            avg_loss = abs(trades['lost']['pnl']['average']) if trades['lost'].get('pnl') else 0
            pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            print(f'  平均盈利:   ${avg_win:.2f}')
            print(f'  平均亏损:   ${avg_loss:.2f}')
            print(f'  盈亏比:     {pl_ratio:.2f}')

    # 夏普比率
    sharpe = strat.analyzers.sharpe.get_analysis()
    if sharpe and sharpe.get('sharperatio'):
        print(f'\n风险指标:')
        print(f'  夏普比率:   {sharpe["sharperatio"]:.2f}')

    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if dd:
        max_dd = dd.get('max', {}).get('drawdown', 0)
        print(f'  最大回撤:   {max_dd:.2f}%')

    # 目标达成检查
    print(f'\n{"="*70}')
    print(f'目标检查')
    print(f'{"="*70}')
    print(f'  年化≥30%:    {"✅" if ann_return >= 30 else "❌"} {ann_return:.2f}%')
    print(f'  盈亏比≥3:    {"✅" if pl_ratio >= 3 else "❌"} {pl_ratio:.2f}')
    print(f'  胜率≥40%:    {"✅" if win_rate >= 40 else "❌"} {win_rate:.1f}%')
    print(f'  年交易50-150:{"✅" if 50 <= trades_per_year <= 150 else "❌"} {trades_per_year:.0f}笔/年')
    print(f'{"="*70}')

    return {
        'final_value': final_value,
        'total_return': total_return,
        'ann_return': ann_return,
        'trades': trades,
        'sharpe': sharpe,
        'drawdown': dd,
        'trade_log': strat.trade_log,
    }

if __name__ == '__main__':
    result = run_backtest('2016-05-19', '2026-05-18')
