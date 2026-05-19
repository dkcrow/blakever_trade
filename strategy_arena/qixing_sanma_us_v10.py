#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三马七星策略 - 美股个股版本 V10（V7 + 表现好的新股票）
=========================================================
在V7基础上加入10年表现好的股票：
- 保留V7的15只核心股票
- 新增：SHOP, LRCX, KLAC, AMAT, LLY, MELI, PLTR, VST, DECK, ASML
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

STOCK_LIST = {
    # V7核心15只
    'NVDA': '英伟达', 'AMD': '超微半导体', 'MU': '美光科技',
    'AVGO': '博通', 'TSLA': '特斯拉', 'AAPL': '苹果',
    'GOOG': '谷歌', 'AMZN': '亚马逊', 'KO': '可口可乐',
    'NEM': '纽曼矿业', 'XOM': '埃克森美孚', 'AEP': '美国电力',
    'JPM': '摩根大通', 'GS': '高盛', 'BRK-B': '伯克希尔-B',
    # 新增表现好的股票
    'SHOP': 'Shopify', 'LRCX': 'Lam Research', 'KLAC': 'KLA Corp',
    'AMAT': '应用材料', 'LLY': '礼来', 'MELI': 'MercadoLibre',
    'PLTR': 'Palantir', 'VST': 'Vistra', 'DECK': 'Deckers',
    'ASML': 'ASML',
}

INITIAL_CASH = 100000.0
COMMISSION = 0.0015

SHORT_LOOKBACK = 20
LONG_LOOKBACK = 60
ATR_MULTIPLIER = 2.0
ATR_PERIOD = 14
MIN_SCORE = 0.15
MAX_POSITIONS = 2

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us'

def weighted_reg(prices_list):
    n = len(prices_list)
    if n < 5:
        return 0, 0, 0
    y = [np.log(max(p, 0.001)) for p in prices_list]
    x = np.arange(n)
    w = np.linspace(1, 2, n)
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

def score_etf(prices_list, short_n=20, long_n=60):
    if len(prices_list) < 5:
        return None, None, None
    sp = prices_list[-short_n:]
    lp = prices_list[-long_n:] if len(prices_list) >= long_n else prices_list
    ann_s, r2_s, score_s = weighted_reg(sp)
    ann_l, r2_l, score_l = weighted_reg(lp)
    if score_s < score_l * 0.5:
        score_s = 0
    return score_s, score_l, score_s + score_l

def load_stock_data(symbol, start_date, end_date):
    filepath = os.path.join(DATA_DIR, f'{symbol}.csv')
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath)
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)
            df.set_index('Date', inplace=True)
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], utc=True).dt.tz_localize(None)
            df.set_index('date', inplace=True)
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        df = df[(df.index >= start_ts) & (df.index <= end_ts)]
        if len(df) < 70:
            return None
        col_map = {}
        for c in df.columns:
            c_lower = c.lower().strip()
            if c_lower in ['open', 'high', 'low', 'close', 'volume']:
                col_map[c] = c_lower
            elif c_lower in ['adj close', 'adj_close']:
                col_map[c] = 'close'
        df = df.rename(columns=col_map)
        required = ['open', 'high', 'low', 'close']
        for col in required:
            if col not in df.columns:
                return None
        if 'volume' not in df.columns:
            df['volume'] = 0
        df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
        return df
    except Exception as e:
        return None

class QixingSanmaV10(bt.Strategy):
    params = (
        ('short_lookback', SHORT_LOOKBACK),
        ('long_lookback', LONG_LOOKBACK),
        ('atr_multiplier', ATR_MULTIPLIER),
        ('atr_period', ATR_PERIOD),
        ('min_score', MIN_SCORE),
        ('max_positions', MAX_POSITIONS),
    )

    def __init__(self):
        self.stock_data = {}
        self.holdings = {}
        self.trade_log = []
        for i, d in enumerate(self.datas):
            self.stock_data[d._name] = d

    def calculate_atr(self, d, period=14):
        if len(d) < period + 1:
            return None
        tr_list = []
        for i in range(-period + 1, 1):
            high = d.high[i]
            low = d.low[i]
            prev_close = d.close[i-1] if i > -len(d) + 1 else d.close[i]
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
            tr_list.append(tr)
        return np.mean(tr_list) if tr_list else None

    def next(self):
        current_scores = {}
        for name, d in self.stock_data.items():
            if len(d) < self.p.long_lookback + 5:
                continue
            prices = [d.close[i] for i in range(-self.p.long_lookback, 0)]
            prices.append(d.close[0])
            score_s, score_l, total = score_etf(prices, self.p.short_lookback, self.p.long_lookback)
            if total is not None and total > self.p.min_score:
                current_scores[name] = {'total': total, 'price': d.close[0]}

        if not current_scores:
            for name in list(self.holdings.keys()):
                d = self.stock_data[name]
                entry = self.holdings[name]['entry_price']
                pnl = (d.close[0] / entry - 1) * 100
                self.close(data=d)
                self.trade_log.append({'date': self.datas[0].datetime.date(0), 'action': 'SELL', 'stock': name, 'price': d.close[0], 'pnl_pct': pnl})
                print(f'  [SELL] {name}: {d.close[0]:.2f} (pnl:{pnl:+.1f}%) - no signal')
                del self.holdings[name]
            return

        ranked = sorted(current_scores.items(), key=lambda x: x[1]['total'], reverse=True)
        top_stocks = [x[0] for x in ranked[:self.p.max_positions]]

        # ATR止损检测
        to_remove = []
        for name, pos in list(self.holdings.items()):
            d = self.stock_data[name]
            price = d.close[0]
            entry_price = pos['entry_price']
            atr = self.calculate_atr(d, self.p.atr_period)
            if atr is None:
                continue
            stop_price = entry_price - atr * self.p.atr_multiplier
            if price <= stop_price:
                self.close(data=d)
                pnl = (price / entry_price - 1) * 100
                self.trade_log.append({'date': self.datas[0].datetime.date(0), 'action': 'ATR_STOP', 'stock': name, 'price': price, 'pnl_pct': pnl})
                print(f'  [ATR_STOP] {name}: {price:.2f} (pnl:{pnl:.1f}%)')
                to_remove.append(name)
                continue
        
        for name in to_remove:
            del self.holdings[name]

        # 调仓逻辑
        current_holding = set(self.holdings.keys())
        target_holding = set(top_stocks)
        
        to_sell = current_holding - target_holding
        to_buy = target_holding - current_holding

        for name in to_sell:
            d = self.stock_data[name]
            entry = self.holdings[name]['entry_price']
            pnl = (d.close[0] / entry - 1) * 100
            self.close(data=d)
            self.trade_log.append({'date': self.datas[0].datetime.date(0), 'action': 'SELL', 'stock': name, 'price': d.close[0], 'pnl_pct': pnl})
            print(f'  [SELL] {name}: {d.close[0]:.2f} (pnl:{pnl:+.1f}%)')
            del self.holdings[name]

        cash_per_stock = self.broker.getcash() * 0.95 / len(to_buy) if to_buy else 0
        for name in to_buy:
            d = self.stock_data[name]
            size = int(cash_per_stock / d.close[0])
            if size > 0:
                self.buy(data=d, size=size)
                self.holdings[name] = {'entry_price': d.close[0]}
                self.trade_log.append({'date': self.datas[0].datetime.date(0), 'action': 'BUY', 'stock': name, 'price': d.close[0], 'size': size})
                print(f'  [BUY] {name}: {d.close[0]:.2f} x{size}')

def run_backtest(start_date='2016-05-19', end_date='2026-05-18'):
    print(f'\n{"="*70}')
    print(f'三马七星策略 - 美股个股版本 V10（V7 + 表现好的新股票）')
    print(f'{"="*70}')
    print(f'参数: 短期{SHORT_LOOKBACK}日/长期{LONG_LOOKBACK}日/ATR{ATR_MULTIPLIER}倍/得分>{MIN_SCORE}/持仓{MAX_POSITIONS}只')

    cerebro = bt.Cerebro()
    valid_stocks = {}

    for symbol, name in STOCK_LIST.items():
        df = load_stock_data(symbol, start_date, end_date)
        if df is not None and len(df) >= 70:
            data = bt.feeds.PandasData(dataname=df, name=symbol, datetime=None, open='open', high='high', low='low', close='close', volume='volume')
            cerebro.adddata(data)
            valid_stocks[symbol] = name

    if len(valid_stocks) < 3:
        print(f'有效股票不足 ({len(valid_stocks)}只)')
        return None

    print(f'\n有效股票: {len(valid_stocks)}只')
    cerebro.addstrategy(QixingSanmaV10)
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    print(f'\n开始回测...')
    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    years = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days / 365.25
    ann_return = ((final_value / INITIAL_CASH) ** (1/years) - 1) * 100 if years > 0 else 0

    print(f'\n{"="*70}')
    print(f'回测结果')
    print(f'{"="*70}')
    print(f'最终资产: ${final_value:,.2f}')
    print(f'总收益率: {total_return:+.2f}%')
    print(f'年化收益率: {ann_return:+.2f}%')

    trades = strat.analyzers.trades.get_analysis()
    total_trades = won_trades = lost_trades = win_rate = trades_per_year = 0
    avg_win = avg_loss = pl_ratio = 0
    
    if trades.get('total'):
        total_trades = trades['total']['total']
        won_trades = trades['won']['total'] if trades.get('won') else 0
        lost_trades = trades['lost']['total'] if trades.get('lost') else 0
        win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0
        trades_per_year = total_trades / years if years > 0 else 0
        
        print(f'\n交易统计:')
        print(f'  总交易: {total_trades} ({trades_per_year:.0f}笔/年)')
        print(f'  盈利: {won_trades} / 亏损: {lost_trades}')
        print(f'  胜率: {win_rate:.1f}%')

        if trades.get('won') and trades.get('lost'):
            avg_win = trades['won']['pnl']['average'] if trades['won'].get('pnl') else 0
            avg_loss = abs(trades['lost']['pnl']['average']) if trades['lost'].get('pnl') else 0
            pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            print(f'  盈亏比: {pl_ratio:.2f}')

    sharpe = strat.analyzers.sharpe.get_analysis()
    sharpe_val = sharpe.get('sharperatio', 0) if sharpe else 0
    dd = strat.analyzers.drawdown.get_analysis()
    max_dd = dd.get('max', {}).get('drawdown', 0) if dd else 0
    
    print(f'\n风险指标:')
    print(f'  夏普: {sharpe_val:.2f}')
    print(f'  最大回撤: {max_dd:.2f}%')

    print(f'\n目标检查:')
    print(f'  年化>=30%: {"Y" if ann_return >= 30 else "N"} {ann_return:.2f}%')
    print(f'  盈亏比>=3: {"Y" if pl_ratio >= 3 else "N"} {pl_ratio:.2f}')
    print(f'  胜率>=40%: {"Y" if win_rate >= 40 else "N"} {win_rate:.1f}%')
    print(f'  年交易50-150: {"Y" if 50 <= trades_per_year <= 150 else "N"} {trades_per_year:.0f}笔/年')
    print(f'{"="*70}')

    return {'final_value': final_value, 'ann_return': ann_return, 'trades': total_trades, 'win_rate': win_rate, 'pl_ratio': pl_ratio}

if __name__ == '__main__':
    run_backtest('2016-05-19', '2026-05-18')
