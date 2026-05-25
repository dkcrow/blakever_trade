#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照6+1 - 2026年至今回测
时间范围: 2026-01-01 ~ 2026-05-20
使用Backtrader框架
"""

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

# ETF池 (7只)
ETF_POOL = {
    '159915': '创业板ETF',
    '513100': '纳指ETF',
    '159985': '豆粕ETF',
    '518880': '黄金ETF',
    '501018': '南方原油',
    '161226': '白银LOF',
    '511220': '城投ETF',  # 安全池
}

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\a'

def load_etf_data(code, start_date='2026-01-01', end_date='2026-05-20'):
    """加载ETF数据"""
    filepath = os.path.join(DATA_DIR, f"{code}_XSHE.csv" if code.startswith('1') or code.startswith('5') else f"{code}_XSHG.csv")
    if not os.path.exists(filepath):
        return None
    try:
        df = pd.read_csv(filepath)
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)
            df.set_index('Date', inplace=True)
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        df = df[(df.index >= start) & (df.index <= end)]
        if len(df) < 20:
            return None
        # 确保列名正确
        col_map = {}
        for c in df.columns:
            c_lower = c.lower().strip()
            if c_lower in ['open', 'high', 'low', 'close', 'volume']:
                col_map[c] = c_lower
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

class Qixing61Strategy(bt.Strategy):
    params = (
        ('short_lookback', 25),
        ('long_lookback', 250),
        ('rebalance_freq', 5),  # 每周调仓
    )
    
    def __init__(self):
        self.etf_data = {}
        self.holdings = {}
        for data in self.datas:
            self.etf_data[data._name] = data
        
    def next(self):
        # 简化版：每周调仓，选得分最高的ETF
        if len(self) % self.p.rebalance_freq != 0:
            return
            
        scores = {}
        for name, data in self.etf_data.items():
            if len(data) < self.p.long_lookback + 5:
                continue
            prices = [data.close[i] for i in range(-min(self.p.long_lookback, len(data)-1), 0)]
            if len(prices) < 10:
                continue
            # 简化评分：短期动量
            short_ret = (prices[-1] / prices[-self.p.short_lookback] - 1) if len(prices) >= self.p.short_lookback else 0
            scores[name] = short_ret
        
        if not scores:
            return
            
        # 选最高分的ETF
        best_etf = max(scores.items(), key=lambda x: x[1])[0]
        
        # 清仓
        for name in list(self.holdings.keys()):
            if name != best_etf:
                self.close(data=self.etf_data[name])
                del self.holdings[name]
        
        # 买入最佳ETF
        if best_etf not in self.holdings:
            target = self.etf_data[best_etf]
            size = int(self.broker.getcash() * 0.95 / target.close[0])
            if size > 0:
                self.buy(data=target, size=size)
                self.holdings[best_etf] = {'entry': target.close[0]}

def run_backtest():
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0003)  # A股佣金
    
    loaded = 0
    for code in ETF_POOL.keys():
        df = load_etf_data(code)
        if df is not None and len(df) > 20:
            data = bt.feeds.PandasData(
                dataname=df,
                name=code,
                fromdate=datetime(2026, 1, 1),
                todate=datetime(2026, 5, 20)
            )
            cerebro.adddata(data)
            loaded += 1
            print(f"  加载: {code} ({ETF_POOL[code]}) - {len(df)}行")
    
    if loaded < 2:
        print(f"❌ 有效ETF不足 ({loaded}只)")
        return
    
    print(f"\n加载 {loaded} 只ETF")
    cerebro.addstrategy(Qixing61Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
    print("\n开始回测...")
    results = cerebro.run()
    strat = results[0]
    
    final_value = cerebro.broker.getvalue()
    initial_cash = 100000.0
    total_return = (final_value / initial_cash - 1) * 100
    
    print("\n" + "="*80)
    print("七星高照6+1 - 2026年至今回测结果")
    print("="*80)
    print(f"初始资金: ¥{initial_cash:,.2f}")
    print(f"最终资产: ¥{final_value:,.2f}")
    print(f"总收益率: {total_return:+.2f}%")
    
    # 年化收益
    days = 140  # 2026-01-01 ~ 2026-05-20 ≈ 140天
    ann_return = (1 + total_return/100) ** (365/days) - 1
    print(f"年化收益率: {ann_return*100:.2f}%")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"最大回撤: {dd['max']*100:.2f}%")
    
    # 交易统计
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total_trades = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        win_rate = won / total_trades * 100 if total_trades > 0 else 0
        avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0)
        avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0)
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        print(f"\n交易统计:")
        print(f"  总交易: {total_trades}")
        print(f"  盈利: {won}  亏损: {lost}")
        print(f"  胜率: {win_rate:.1f}%")
        print(f"  盈亏比: {pl_ratio:.2f}")

if __name__ == '__main__':
    print("\n" + "="*80)
    print("七星高照6+1 - 2026年至今回测")
    print("时间范围: 2026-01-01 ~ 2026-05-20")
    print("="*80)
    run_backtest()
