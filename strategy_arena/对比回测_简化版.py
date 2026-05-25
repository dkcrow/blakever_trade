#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯vs三马七星 - 简化对比回测
直接用本地美股数据
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings

warnings.filterwarnings('ignore')

# 配置
INITIAL_CASH = 100000.0
COMMISSION = 0.001
ETF_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'

# 10只美股ETF
ETF_LIST = ['AGG', 'GLD', 'IEF', 'QQQ', 'SH', 'SHY', 'SPY', 'TLT', 'VEA', 'SPY_RV']

# 美股股票（15只，与三马七星相同）
US_STOCKS_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks'
US_STOCKS = ['AAPL', 'NVDA', 'AMD', 'MU', 'AVGO', 'TSLA', 'GOOG', 'AMZN', 'KO', 'NEM', 'XOM', 'AEP', 'JPM', 'GS', 'BRK-B']


def load_data(filepath, name, fromdate, todate):
    """加载数据到Backtrader"""
    try:
        df = pd.read_csv(filepath)
        
        # 处理日期列
        date_col = None
        for col in ['Date', 'datetime', df.columns[0]]:
            if col in df.columns:
                date_col = col
                break
        
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col)
        
        df = df.sort_index()
        
        # 移除时区信息（统一为naive）
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        
        # 标准化列名
        col_map = {}
        for col in df.columns:
            lower = col.lower()
            if 'open' in lower: col_map[col] = 'open'
            elif 'high' in lower: col_map[col] = 'high'
            elif 'low' in lower: col_map[col] = 'low'
            elif 'close' in lower: col_map[col] = 'close'
            elif 'volume' in lower: col_map[col] = 'volume'
        
        if col_map:
            df = df.rename(columns=col_map)
        
        # 筛选日期
        if fromdate:
            from_ts = pd.Timestamp(fromdate)
            df = df[df.index >= from_ts]
        if todate:
            to_ts = pd.Timestamp(todate)
            df = df[df.index <= to_ts]
        
        if len(df) < 50:
            return None
        
        # 创建Data Feed
        data = bt.feeds.PandasData(
            dataname=df,
            name=name,
        )
        return data
    except Exception as e:
        print(f"  加载 {name} 失败: {e}")
        return None


def run_sanma_backtest():
    """运行三马七星策略回测（简化版）"""
    print("\n" + "="*70)
    print("策略1: 三马七星（简化版）")
    print("="*70)
    
    # 加载数据
    print("\n加载美股数据...")
    datas = []
    names = []
    for code in US_STOCKS:
        filepath = os.path.join(US_STOCKS_DIR, f"{code}.csv")
        if not os.path.exists(filepath):
            continue
        data = load_data(filepath, code, '2019-01-01', '2024-12-31')
        if data:
            datas.append(data)
            names.append(code)
            print(f"  ✓ {code}")
    
    if len(datas) < 5:
        print("数据不足！")
        return
    
    # 创建Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    # 添加数据
    for data in datas:
        cerebro.adddata(data)
    
    # 简化策略：只做Top3动量
    class SimpleMomentum(bt.Strategy):
        params = (('lookback', 20), ('top_n', 3))
        
        def __init__(self):
            self.datas_dict = {d._name: d for d in self.datas}
        
        def next(self):
            scores = []
            for name, d in self.datas_dict.items():
                if len(d) < self.p.lookback + 5:
                    continue
                closes = [d.close[i] for i in range(-(self.p.lookback + 1), 0)]
                ret = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
                if ret > 0:
                    scores.append((name, ret))
            
            scores.sort(key=lambda x: x[1], reverse=True)
            targets = [s[0] for s in scores[:self.p.top_n]]
            
            # 调仓
            if targets:
                target_val = self.broker.getvalue() / len(targets)
                for name in targets:
                    d = self.datas_dict[name]
                    pos = self.getposition(d).size
                    cur_val = pos * d.close[0]
                    if abs(cur_val - target_val) > target_val * 0.1 or pos == 0:
                        size = int(target_val / d.close[0] / 100) * 100
                        if size > 0 and size != pos:
                            self.order_target_size(d, size)
                
                # 卖出不在目标的
                for name, d in self.datas_dict.items():
                    if name not in targets and self.getposition(d).size > 0:
                        self.close(d)
    
    cerebro.addstrategy(SimpleMomentum, lookback=20, top_n=3)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results = cerebro.run()
    strat = results[0]
    
    print(f"\n初始资金:    ${INITIAL_CASH:,.2f}")
    print(f"最终资产:    ${cerebro.broker.getvalue():,.2f}")
    total_ret = (cerebro.broker.getvalue() / INITIAL_CASH - 1) * 100
    print(f"总收益率:    {total_ret:+.2f}%")
    
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns:
        ann = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
        print(f"年化收益率:  {ann*100:.2f}%")
    
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"最大回撤:    {dd['max']*100:.2f}%")
    
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        wr = won / total * 100 if total > 0 else 0
        print(f"交易次数:    {total}")
        print(f"胜率:        {wr:.1f}%")


def run_laplace_backtest():
    """运行拉普拉斯策略回测"""
    print("\n" + "="*70)
    print("策略2: 七星拉普拉斯（简化版）")
    print("="*70)
    
    # 加载数据
    print("\n加载ETF数据...")
    datas = []
    names = []
    for code in ETF_LIST:
        filepath = os.path.join(ETF_DIR, f"{code}.csv")
        if not os.path.exists(filepath):
            continue
        data = load_data(filepath, code, '2019-01-01', '2024-12-31')
        if data:
            datas.append(data)
            names.append(code)
            print(f"  ✓ {code}")
    
    if len(datas) < 3:
        print("数据不足！")
        return
    
    # 创建Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    # 添加数据
    for data in datas:
        cerebro.adddata(data)
    
    # 简化策略：拉普拉斯滤波 + Top1持仓
    class LaplaceSimple(bt.Strategy):
        params = (('lookback', 25), ('top_n', 1))
        
        def __init__(self):
            self.datas_dict = {d._name: d for d in self.datas}
        
        def next(self):
            scores = []
            for name, d in self.datas_dict.items():
                if len(d) < self.p.lookback + 5:
                    continue
                
                closes = [d.close[i] for i in range(-(self.p.lookback + 1), 0)]
                
                # 拉普拉斯滤波
                s = 0.05
                alpha = 1 - math.exp(-s)
                filtered = [closes[0]]
                for i in range(1, len(closes)):
                    filtered.append(alpha * closes[i] + (1 - alpha) * filtered[-1])
                
                # 动量得分
                y = np.log(filtered)
                x = np.arange(len(y))
                weights = np.linspace(1, 2, len(y))
                slope, _ = np.polyfit(x, y, 1, w=weights)
                ann_ret = math.exp(slope * 250) - 1
                
                if ann_ret > 0:
                    scores.append((name, ann_ret))
            
            scores.sort(key=lambda x: x[1], reverse=True)
            
            if scores:
                target = scores[0][0]  # Top1
                d = self.datas_dict[target]
                pos = self.getposition(d).size
                target_val = self.broker.getvalue()
                cur_val = pos * d.close[0]
                
                if abs(cur_val - target_val) > target_val * 0.1 or pos == 0:
                    size = int(target_val / d.close[0] / 100) * 100
                    if size > 0 and size != pos:
                        self.order_target_size(d, size)
                
                # 卖出其他
                for name, d2 in self.datas_dict.items():
                    if name != target and self.getposition(d2).size > 0:
                        self.close(d2)
    
    cerebro.addstrategy(LaplaceSimple, lookback=25, top_n=1)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results = cerebro.run()
    strat = results[0]
    
    print(f"\n初始资金:    ${INITIAL_CASH:,.2f}")
    print(f"最终资产:    ${cerebro.broker.getvalue():,.2f}")
    total_ret = (cerebro.broker.getvalue() / INITIAL_CASH - 1) * 100
    print(f"总收益率:    {total_ret:+.2f}%")
    
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns:
        ann = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
        print(f"年化收益率:  {ann*100:.2f}%")
    
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"最大回撤:    {dd['max']*100:.2f}%")
    
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        wr = won / total * 100 if total > 0 else 0
        print(f"交易次数:    {total}")
        print(f"胜率:        {wr:.1f}%")


if __name__ == '__main__':
    run_sanma_backtest()
    run_laplace_backtest()
    
    print("\n" + "="*70)
    print("对比总结")
    print("="*70)
    print("\n三马七星：多股持仓，动量轮动")
    print("七星拉普拉斯：单股持仓，滤波平滑")
    print("\n两者融合可能是更好的方向：拉普拉斯滤波 + ATR止损 + 多股持仓")
    print("="*70 + "\n")
