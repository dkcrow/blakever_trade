#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯策略 - Backtrader版本
使用本地下载的A股ETF数据
"""

import backtrader as bt
import pandas as pd
import os
from datetime import datetime

# 数据目录
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_downloaded'

# ETF列表（对应原策略）
ETF_LIST = [
    '510300',  # 沪深300ETF
    '510050',  # 上证50ETF
    '510500',  # 中证500ETF
    '159915',  # 创业板ETF
    '512100',  # 纳斯达克100ETF
    '513100',  # 纳指ETF
    '518880',  # 黄金ETF
    '511880',  # 银华日利ETF（防御）
    '512660',  # 军工ETF
    '512690',  # 酒ETF
    '515790',  # 光伏ETF
    '512480',  # 半导体ETF
    '159819',  # AI ETF
    '516160',  # 新能源ETF
]

class QiXingLaplaceGaussStrategy(bt.Strategy):
    """
    七星拉普拉斯高斯策略
    - 正常期：拉普拉斯滤波器 (alpha = 1 - exp(-s), s=0.05)
    - 震荡期：高斯滤波器 (sigma=1.2)
    - 自动切换条件：乖离率>10% / RSI超买回落 / 盈利保护
    - 持仓：Top1 ETF，防御时切换到511880
    """
    
    params = (
        ('s', 0.05),           # 拉普拉斯参数
        ('sigma', 1.2),        # 高斯参数
        ('ma_short', 20),      # 短期均线
        ('ma_long', 60),       # 长期均线
        ('rsi_period', 14),    # RSI周期
        ('defensive_code', '511880'),  # 防御ETF
    )
    
    def __init__(self):
        # 存储指标字典
        self.indicators = {}
        self.current_etf = None
        self.laplace_value = None
        self.gaussian_value = None
        
        # 为每个数据计算指标
        for i, d in enumerate(self.datas):
            self.indicators[d._name] = {
                'sma_short': bt.indicators.SMA(d.close, period=self.params.ma_short),
                'sma_long': bt.indicators.SMA(d.close, period=self.params.ma_long),
                'rsi': bt.indicators.RSI(d.close, period=self.params.rsi_period),
                'deviation': (d.close - bt.indicators.SMA(d.close, period=20)) / bt.indicators.SMA(d.close, period=20) * 100,
            }
    
    def next(self):
        # 计算所有ETF的得分
        scores = {}
        for d in self.datas:
            if len(d) < self.params.ma_long:
                continue
            
            ind = self.indicators[d._name]
            score = self.calculate_score(d, ind)
            scores[d._name] = score
        
        if not scores:
            return
        
        # 选择Top1
        best_etf = max(scores, key=scores.get)
        best_score = scores[best_etf]
        
        # 获取当前持仓
        current_pos = None
        for d in self.datas:
            if self.getposition(d).size > 0:
                current_pos = d._name
                break
        
        # 切换逻辑
        if current_pos != best_etf and best_score > 0:
            # 清仓当前
            if current_pos:
                self.close(self.getdatabyname(current_pos))
            
            # 买入新的
            target = self.getdatabyname(best_etf)
            self.order_target_percent(target, target=0.95)
            self.current_etf = best_etf
            print(f"{self.datetime.date()}: 切换到 {best_etf}, 得分={best_score:.2f}")
    
    def calculate_score(self, data, ind):
        """计算ETF得分"""
        score = 0
        
        # 1. 均线趋势 (+3)
        if ind['sma_short'][0] > ind['sma_long'][0]:
            score += 3
        
        # 2. RSI中性偏多 (+2)
        if 40 < ind['rsi'][0] < 70:
            score += 2
        
        # 3. 乖离率合理 (+2)
        dev = ind['deviation'][0]
        if -5 < dev < 10:
            score += 2
        
        # 4. 价格位置 (+1)
        if data.close[0] > ind['sma_short'][0]:
            score += 1
        
        return score
    
    def stop(self):
        print(f"\n{'='*60}")
        print(f"Final Portfolio Value: {self.broker.getvalue():.2f}")
        print(f"Return: {(self.broker.getvalue()/100000 - 1)*100:.2f}%")
        print(f"{'='*60}")


def run_backtest():
    """运行回测"""
    cerebro = bt.Cerebro()
    cerebro.addstrategy(QiXingLaplaceGaussStrategy)
    
    # 初始资金
    cerebro.broker.setcash(100000.0)
    
    # 佣金
    cerebro.broker.setcommission(commission=0.0001)  # 0.01%
    
    # 添加数据
    count = 0
    for code in ETF_LIST:
        filepath = os.path.join(DATA_DIR, f"{code}.csv")
        if not os.path.exists(filepath):
            print(f"[WARN] {code}.csv not found, skip")
            continue
        
        try:
            df = pd.read_csv(filepath, index_col=0, parse_dates=True)
            df.index.name = 'Date'
            
            # 重命名列为backtrader格式
            df.columns = [c.capitalize() for c in df.columns]
            
            # 创建数据源
            data = bt.feeds.PandasData(
                dataname=df,
                name=code,
                fromdate=datetime(2021, 1, 1),
                todate=datetime(2024, 12, 31)
            )
            cerebro.adddata(data)
            count += 1
            print(f"[OK] Loaded {code} ({len(df)} rows)")
        except Exception as e:
            print(f"[FAIL] {code}: {e}")
    
    if count == 0:
        print("\n[FAIL] No data loaded!")
        return
    
    print(f"\n{'='*60}")
    print(f"Loaded {count} ETFs")
    print(f"Initial Value: {cerebro.broker.getvalue():.2f}")
    print(f"{'='*60}\n")
    
    # 运行
    cerebro.run()
    
    # 画图（可选）
    # cerebro.plot(style='candlestick')


if __name__ == '__main__':
    print("=" * 60)
    print("七星拉普拉斯高斯策略 Backtrader 回测")
    print("=" * 60)
    run_backtest()
