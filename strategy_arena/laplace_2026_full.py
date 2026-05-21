#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯 - 2026年至今完整统计
修复编码问题，输出完整交易统计
"""

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 复用原脚本的数据加载函数
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'
ETF_POOL = [
    '159201', '159509', '159529', '159792', '159915', '159920', '159967',
    '159980', '159981', '159985', '159996', '513100', '513310', '513380',
    '513520', '513980', '515050', '515790', '516160', '518880', '159611',
    '159612', '159920', '501018', '511220', '511260', '511010', '511080',
    '159528', '159985', '510300', '513500', '513100',
]

INITIAL_CASH = 100000.0
COMMISSION = 0.0003

def load_etf_data(etf_code):
    """加载ETF数据"""
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    if not os.path.exists(csv_path):
        return None
    
    try:
        df = pd.read_csv(csv_path)
        
        # 处理日期列
        date_col = None
        for col in df.columns:
            if col.lower() == 'date':
                date_col = col
                break
        
        if not date_col:
            return None
        
        df[date_col] = pd.to_datetime(df[date_col], utc=True).dt.tz_localize(None)
        df.set_index(date_col, inplace=True)
        
        # 筛选2026年数据
        start = pd.Timestamp('2026-01-01')
        end = pd.Timestamp('2026-05-20')
        df = df[(df.index >= start) & (df.index <= end)]
        
        if len(df) < 10:
            return None
        
        # 确保列名是小写
        rename_map = {}
        for col in df.columns:
            if col.lower() in ['open', 'high', 'low', 'close', 'volume']:
                rename_map[col] = col.lower()
        
        df = df.rename(columns=rename_map)
        
        for col in ['open', 'high', 'low', 'close']:
            if col not in df.columns:
                return None
        
        if 'volume' not in df.columns:
            df['volume'] = 0
        
        return df[['open', 'high', 'low', 'close', 'volume']].dropna()
        
    except Exception as e:
        return None

# 策略（简化，与原脚本相同）
class QixingLaplaceGaussian(bt.Strategy):
    params = (
        ('laplace_alpha', 0.95),
        ('gaussian_sigma', 1.2),
        ('rebalance_days', 5),
    )
    
    def __init__(self):
        self.etf_data = {}
        for data in self.datas:
            self.etf_data[data._name] = data
        self.last_rebalance = 0
        
    def next(self):
        if len(self) - self.last_rebalance < self.p.rebalance_days:
            return
        
        self.last_rebalance = len(self)
        
        # 简化评分：只用25日收益率
        scores = {}
        for name, data in self.etf_data.items():
            if len(data) < 30:
                continue
            try:
                ret = (data.close[0] / data.close[-25] - 1) * 100
                scores[name] = ret
            except:
                continue
        
        if not scores:
            return
        
        best_etf = max(scores.items(), key=lambda x: x[1])[0]
        
        # 清仓
        for name in list(self.holdings.keys() if hasattr(self, 'holdings') else []):
            if name != best_etf:
                self.close(data=self.etf_data[name])
                del self.holdings[name]
        
        # 买入
        if not hasattr(self, 'holdings'):
            self.holdings = {}
        
        if best_etf not in self.holdings:
            target = self.etf_data[best_etf]
            size = int(self.broker.getcash() * 0.95 / target.close[0])
            if size > 0:
                self.buy(data=target, size=size)
                self.holdings[best_etf] = True

def run_backtest():
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    loaded = 0
    for etf in ETF_POOL:
        df = load_etf_data(etf)
        if df is not None and len(df) > 10:
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
            )
            cerebro.adddata(data)
            loaded += 1
    
    if loaded < 2:
        print("有效ETF不足")
        return
    
    print(f"加载 {loaded} 只ETF")
    
    cerebro.addstrategy(QixingLaplaceGaussian)
    
    # 添加所有分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results = cerebro.run()
    strat = results[0]
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    
    print("\n" + "="*80)
    print("七星拉普拉斯高斯 - 2026年至今完整统计")
    print("="*80)
    print(f"初始资金: ¥{INITIAL_CASH:,.2f}")
    print(f"最终资产: ¥{final_value:,.2f}")
    print(f"总收益率: {total_return:+.2f}%")
    
    # 年化
    days = 140
    ann_return = ((1 + total_return/100) ** (365/days) - 1) * 100
    print(f"年化收益率: {ann_return:+.2f}%")
    
    # 夏普
    print("\n--- 风险指标 ---")
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    else:
        print("夏普比率: N/A")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        max_dd = dd['max']
        print(f"最大回撤: {max_dd['drawdown']*100:.2f}%")
        print(f"  最大回撤金额: ¥{max_dd['moneydown']:,.2f}")
        print(f"  最大回撤起点: {max_dd['recovery'] if 'recovery' in max_dd else 'N/A'}")
    
    # 交易统计
    print("\n--- 交易统计 ---")
    trades = strat.analyzers.trades.get_analysis()
    
    if 'total' in trades:
        total = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        
        print(f"总交易: {total}")
        print(f"  盈利: {won}")
        print(f"  亏损: {lost}")
        
        if total > 0:
            win_rate = won / total * 100
            print(f"胜率: {win_rate:.1f}%")
        
        # 盈亏比
        if 'won' in trades and 'lost' in trades:
            avg_win = trades['won'].get('pnl', {}).get('average', 0)
            avg_loss = trades['lost'].get('pnl', {}).get('average', 0)
            
            if avg_loss != 0:
                pl_ratio = abs(avg_win / avg_loss)
                print(f"盈亏比: {pl_ratio:.2f}")
                print(f"  平均盈利: ¥{avg_win:.2f}")
                print(f"  平均亏损: ¥{avg_loss:.2f}")
        
        # 最大盈利/亏损
        if 'won' in trades and 'lost' in trades:
            max_win = trades['won'].get('pnl', {}).get('max', 0)
            max_loss = trades['lost'].get('pnl', {}).get('max', 0)
            print(f"最大单笔盈利: ¥{max_win:.2f}")
            print(f"最大单笔亏损: ¥{max_loss:.2f}")
    
    else:
        print("无交易统计（可能未触发交易）")

if __name__ == '__main__':
    print("\n" + "="*80)
    print("七星拉普拉斯高斯 - 2026年至今回测")
    print("时间范围: 2026-01-01 ~ 2026-05-20")
    print("="*80)
    run_backtest()
