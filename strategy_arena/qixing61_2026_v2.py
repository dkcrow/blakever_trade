#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照6+1 - 2026年至今回测（简化版）
使用Backtrader框架
"""

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 7只ETF
ETF_POOL = {
    '159915': '创业板ETF',
    '513100': '纳指ETF',
    '159985': '豆粕ETF',
    '518880': '黄金ETF',
    '501018': '南方原油',
    '161226': '白银LOF',
    '511220': '城投ETF',  # 安全池
}

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

def load_etf_data(code):
    """加载ETF数据"""
    filepath = os.path.join(DATA_DIR, f"{code}.csv")
    
    if not os.path.exists(filepath):
        print(f"  ❌ 文件不存在: {code}.csv")
        return None
    
    try:
        df = pd.read_csv(filepath)
        
        # 检查列名
        print(f"  📂 {code}.csv: {len(df)}行, 列={list(df.columns)[:6]}")
        
        # 处理日期列
        date_col = None
        for col in df.columns:
            if col.lower() == 'date':
                date_col = col
                break
        
        if not date_col:
            print(f"  ❌ 找不到日期列")
            return None
        
        df[date_col] = pd.to_datetime(df[date_col], utc=True).dt.tz_localize(None)
        df.set_index(date_col, inplace=True)
        
        # 筛选2026年数据
        start = pd.Timestamp('2026-01-01')
        end = pd.Timestamp('2026-05-20')
        df = df[(df.index >= start) & (df.index <= end)]
        
        if len(df) < 10:
            print(f"  ⚠️ 2026年数据不足: {len(df)}行")
            return None
        
        # 确保列名是小写
        rename_map = {}
        for col in df.columns:
            if col.lower() in ['open', 'high', 'low', 'close', 'volume']:
                rename_map[col] = col.lower()
        
        df = df.rename(columns=rename_map)
        
        # 检查必要列
        for col in ['open', 'high', 'low', 'close']:
            if col not in df.columns:
                print(f"  ❌ 缺少列: {col}")
                return None
        
        if 'volume' not in df.columns:
            df['volume'] = 0
        
        return df[['open', 'high', 'low', 'close', 'volume']].dropna()
        
    except Exception as e:
        print(f"  ❌ 加载失败: {e}")
        import traceback
        traceback.print_exc()
        return None

class Qixing61Strategy(bt.Strategy):
    params = (
        ('short_lookback', 25),
        ('rebalance_freq', 5),  # 每周调仓
    )
    
    def __init__(self):
        self.etf_data = {}
        self.holdings = {}
        
        for data in self.datas:
            self.etf_data[data._name] = data
        
        print(f"\n策略初始化完成，管理 {len(self.etf_data)} 只ETF")
    
    def next(self):
        # 每周调仓
        if len(self) % self.p.rebalance_freq != 0:
            return
        
        # 计算每只ETF的短期动量得分
        scores = {}
        for name, data in self.etf_data.items():
            if len(data) < self.p.short_lookback + 5:
                continue
            
            # 简化评分：25日收益率
            try:
                price_now = data.close[0]
                price_past = data.close[-self.p.short_lookback]
                ret = (price_now / price_past - 1) * 100
                scores[name] = ret
            except:
                continue
        
        if not scores:
            return
        
        # 找到得分最高的ETF
        best_name = max(scores.items(), key=lambda x: x[1])[0]
        best_score = scores[best_name]
        
        # 清仓所有非最佳ETF
        for name in list(self.holdings.keys()):
            if name != best_name:
                self.close(data=self.etf_data[name])
                del self.holdings[name]
                print(f"  [{self.datas[0].datetime.date(0)}] 卖出: {name}")
        
        # 买入最佳ETF
        if best_name not in self.holdings:
            target = self.etf_data[best_name]
            cash = self.broker.getcash()
            size = int(cash * 0.95 / target.close[0])
            
            if size > 0:
                self.buy(data=target, size=size)
                self.holdings[best_name] = {'entry': target.close[0]}
                print(f"  [{self.datas[0].datetime.date(0)}] 买入: {best_name} @ {target.close[0]:.3f} x{size} (得分:{best_score:.2f})")

def run_backtest():
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0003)  # A股佣金
    
    loaded = 0
    for code, name in ETF_POOL.items():
        # 判断市场
        if code.startswith('5') or code.startswith('1'):
            market = 'XSHG'  # 上海: 5开头(ETF)、1开头(LOF)
        else:
            market = 'XSHE'  # 深圳: 0/3开头
        
        df = load_etf_data(code, market)
        if df is not None and len(df) > 10:
            data = bt.feeds.PandasData(
                dataname=df,
                name=code,
            )
            cerebro.adddata(data)
            loaded += 1
    
    if loaded < 2:
        print(f"\n❌ 有效ETF不足 ({loaded}只)")
        return
    
    print(f"\n✅ 加载 {loaded} 只ETF，开始回测...")
    
    cerebro.addstrategy(Qixing61Strategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
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
    days = 140  # 2026-01-01 ~ 2026-05-20
    ann_return = ((1 + total_return/100) ** (365/days) - 1) * 100
    print(f"年化收益率: {ann_return:+.2f}%")
    
    # 夏普
    try:
        sharpe = strat.analyzers.sharpe.get_analysis()
        if 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
            print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    except:
        pass
    
    # 最大回撤
    try:
        dd = strat.analyzers.drawdown.get_analysis()
        if 'max' in dd:
            print(f"最大回撤: {dd['max']['drawdown']*100:.2f}%")
    except:
        pass
    
    # 交易统计
    try:
        trades = strat.analyzers.trades.get_analysis()
        if 'total' in trades and trades['total']['total'] > 0:
            total_trades = trades['total']['total']
            won = trades.get('won', {}).get('total', 0)
            lost = trades.get('lost', {}).get('total', 0)
            win_rate = won / total_trades * 100 if total_trades > 0 else 0
            
            print(f"\n交易统计:")
            print(f"  总交易: {total_trades}")
            print(f"  盈利: {won}  亏损: {lost}")
            print(f"  胜率: {win_rate:.1f}%")
    except:
        pass

if __name__ == '__main__':
    print("\n" + "="*80)
    print("七星高照6+1 - 2026年至今回测")
    print("时间范围: 2026-01-01 ~ 2026-05-20")
    print("="*80)
    run_backtest()
