#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯策略 vs 三马七星策略 - 对比回测
===================================================
用相同的美股数据（15只）对比两个策略的表现
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# ===========================================================
# 参数配置
# ===========================================================

INITIAL_CASH = 100000.0
COMMISSION = 0.001  # 0.1%
US_STOCKS_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us_stocks'

# 15只美股（与三马七星相同）
US_STOCKS = [
    'AAPL', 'NVDA', 'AMD', 'MU', 'AVGO', 'TSLA',
    'GOOG', 'AMZN', 'KO', 'NEM', 'XOM', 'AEP',
    'JPM', 'GS', 'BRK-B'
]

# 三马七星参数（V7最优版）
QIXING_US_PARAMS = {
    'short_period': 20,
    'long_period': 60,
    'atr_period': 14,
    'atr_multiplier': 2.0,
    'min_score': 0.15,
    'max_positions': 3,
}

# 七星拉普拉斯参数
QIXING_LAPLACE_PARAMS = {
    'lookback_days': 25,
    'holdings_num': 3,  # 改为3只，与三马七星可比
    'enable_profit_protection': True,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
    'enable_range_bound': True,
    'laplace_s_param': 0.05,
    'gaussian_sigma': 1.2,
    'ma_period': 20,
    'bias_threshold': 0.10,
}


# ===========================================================
# 工具函数
# ===========================================================

def laplace_filter(price, s=0.05):
    """拉普拉斯滤波器"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def calculate_rsi(prices, period=14):
    """计算RSI"""
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def load_stock_data(symbol):
    """加载美股数据"""
    csv_path = os.path.join(US_STOCKS_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
        # 确保列名正确
        df.columns = [c.lower() for c in df.columns]
        return df
    except:
        return None


# ===========================================================
# 策略1: 三马七星（简化版，仅用价格动量）
# ===========================================================

class SanmaQixing(bt.Strategy):
    """三马七星美股版（简化回测版）"""
    
    params = (
        ('short_period', 20),
        ('long_period', 60),
        ('min_score', 0.15),
        ('max_positions', 3),
    )
    
    def __init__(self):
        self.stock_datas = {}
        for d in self.datas:
            self.stock_datas[d._name] = d
        
    def next(self):
        dt = self.datas[0].datetime.date(0)
        
        # 计算所有股票得分
        scores = []
        for name, d in self.stock_datas.items():
            if len(d) < self.p.long_period + 5:
                continue
            
            # 计算动量得分（简化版）
            closes = [d.close[i] for i in range(-(self.p.short_period + 1), 0)]
            if len(closes) < self.p.short_period:
                continue
            
            y = np.log(closes)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, _ = np.polyfit(x, y, 1, w=weights)
            ann_return = math.exp(slope * 250) - 1
            
            # R²
            ss_res = np.sum(weights * (y - slope * x - np.mean(y)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            score = ann_return * r_squared
            
            if score > self.p.min_score:
                scores.append((name, score, ann_return))
        
        # 按得分排名
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # 确定目标持仓
        targets = [s[0] for s in scores[:self.p.max_positions]]
        
        # 卖出不在目标的持仓
        for name, d in self.stock_datas.items():
            pos = self.getposition(d).size
            if pos > 0 and name not in targets:
                self.close(d)
        
        # 买入目标
        if targets:
            target_val = self.broker.getvalue() / len(targets)
            for name in targets:
                d = self.stock_datas[name]
                pos = self.getposition(d).size
                cur_val = pos * d.close[0]
                if abs(cur_val - target_val) > target_val * 0.05 or pos == 0:
                    size = int(target_val / d.close[0] / 100) * 100
                    if size > 0 and size != pos:
                        self.order_target_size(d, size)


# ===========================================================
# 策略2: 七星拉普拉斯高斯
# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """七星拉普拉斯高斯策略"""
    
    params = (
        ('lookback_days', 25),
        ('holdings_num', 3),
        ('enable_profit_protection', True),
        ('profit_protection_lookback', 1),
        ('profit_protection_threshold', 0.05),
        ('enable_range_bound', True),
        ('ma_period', 20),
        ('bias_threshold', 0.10),
    )
    
    def __init__(self):
        self.stock_datas = {}
        self.current_filter = '正常期'
        self.previous_rsi = None
        self.range_bound_start = None
        
        for d in self.datas:
            self.stock_datas[d._name] = d
        
    def next(self):
        dt = self.datas[0].datetime.date(0)
        
        # 检查震荡期（简化版，仅检查第一个数据作为基准）
        if self.p.enable_range_bound and len(self.datas[0]) > self.p.ma_period:
            self._check_range_bound()
        
        # 计算排名
        scores = self._calculate_scores()
        
        if not scores:
            return
        
        # 确定目标
        targets = [s[0] for s in scores[:self.p.holdings_num]]
        
        # 卖出不在目标的持仓
        for name, d in self.stock_datas.items():
            pos = self.getposition(d).size
            if pos > 0 and name not in targets:
                self.close(d)
                print(f"[{dt}] 卖出 {name}")
        
        # 买入目标
        if targets:
            target_val = self.broker.getvalue() / len(targets)
            for name in targets:
                d = self.stock_datas[name]
                pos = self.getposition(d).size
                cur_val = pos * d.close[0]
                if abs(cur_val - target_val) > target_val * 0.05 or pos == 0:
                    size = int(target_val / d.close[0] / 100) * 100
                    if size > 0 and size != pos:
                        self.order_target_size(d, size)
                        print(f"[{dt}] 买入 {name} {size}股 @ {d.close[0]:.2f}")
    
    def _calculate_scores(self):
        """计算所有股票得分"""
        scores = []
        
        for name, d in self.stock_datas.items():
            if len(d) < self.p.lookback_days + 5:
                continue
            
            # 获取历史数据
            closes = [d.close[i] for i in range(-(self.p.lookback_days + 20), 0)]
            
            if len(closes) < self.p.lookback_days:
                continue
            
            # 盈利保护
            if self.p.enable_profit_protection:
                recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                if closes[-1] < recent_high * (1 - self.p.profit_protection_threshold):
                    continue
            
            # 动量计算
            recent = closes[-(self.p.lookback_days + 1):]
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            ann_return = math.exp(slope * 250) - 1
            
            # R²
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            score = ann_return * r_squared
            
            if score > 0:
                scores.append((name, score, ann_return))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores
    
    def _check_range_bound(self):
        """检查震荡期（简化版）"""
        d = self.datas[0]  # 用第一个股票作为基准
        
        closes = [d.close[i] for i in range(-(self.p.ma_period + 5), 0)]
        
        if len(closes) < self.p.ma_period:
            return
        
        close_arr = np.array(closes)
        current_price = close_arr[-1]
        ma = np.mean(close_arr[-self.p.ma_period:])
        
        bias = (current_price - ma) / ma if ma > 0 else 0
        current_rsi = calculate_rsi(close_arr, 14)
        
        dt = self.datas[0].datetime.date(0)
        
        # 进入震荡期条件
        if bias > self.p.bias_threshold and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            self.range_bound_start = dt
            print(f"\n[{dt}] *** 进入震荡期（高斯滤波器）***")
        
        # 退出震荡期条件
        if self.current_filter == '震荡期' and bias < self.p.bias_threshold * 0.5:
            self.current_filter = '正常期'
            print(f"\n[{dt}] *** 退出震荡期（拉普拉斯滤波器）***")
        
        self.previous_rsi = current_rsi


# ===========================================================
# 主函数：对比回测
# ===========================================================

def run_comparison_backtest():
    """运行对比回测"""
    
    # 加载数据
    print("\n正在加载美股数据...")
    data_dict = {}
    for symbol in US_STOCKS:
        df = load_stock_data(symbol)
        if df is not None and len(df) > 100:
            data = bt.feeds.PandasData(
                dataname=df,
                name=symbol,
                fromdate=datetime(2019, 1, 1),
                todate=datetime(2024, 12, 31)
            )
            data_dict[symbol] = data
            print(f"  ✓ {symbol} ({len(df)}条)")
    
    if len(data_dict) < 5:
        print(f"\n✗ 数据不足（仅{len(data_dict)}只）")
        return
    
    print(f"\n✓ 成功加载 {len(data_dict)} 只美股数据\n")
    
    # ===== 策略1: 三马七星 =====
    print("="*60)
    print("策略1: 三马七星美股版")
    print("="*60)
    
    cerebro1 = bt.Cerebro()
    cerebro1.broker.setcash(INITIAL_CASH)
    cerebro1.broker.setcommission(commission=COMMISSION)
    cerebro1.addstrategy(SanmaQixing, **QIXING_US_PARAMS)
    
    for symbol, data in data_dict.items():
        cerebro1.adddata(data)
    
    cerebro1.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro1.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro1.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro1.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results1 = cerebro1.run()
    strat1 = results1[0]
    
    print(f"\n初始资金:    ${INITIAL_CASH:,.2f}")
    print(f"最终资产:    ${cerebro1.broker.getvalue():,.2f}")
    total_return1 = (cerebro1.broker.getvalue() / INITIAL_CASH - 1) * 100
    print(f"总收益率:    {total_return1:+.2f}%")
    
    returns1 = strat1.analyzers.returns.get_analysis()
    if 'rtot' in returns1:
        ann1 = (1 + returns1['rtot']) ** (250 / len(strat1.data)) - 1
        print(f"年化收益率:  {ann1*100:.2f}%")
    
    sharpe1 = strat1.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe1:
        print(f"夏普比率:    {sharpe1['sharperatio']:.2f}")
    
    dd1 = strat1.analyzers.drawdown.get_analysis()
    if 'max' in dd1:
        print(f"最大回撤:    {dd1['max']*100:.2f}%")
    
    trades1 = strat1.analyzers.trades.get_analysis()
    if 'total' in trades1 and trades1['total']['total'] > 0:
        total = trades1['total']['total']
        won = trades1.get('won', {}).get('total', 0)
        lost = trades1.get('lost', {}).get('total', 0)
        wr1 = won / total * 100 if total > 0 else 0
        print(f"交易次数:    {total}")
        print(f"胜率:        {wr1:.1f}%")
    
    # ===== 策略2: 七星拉普拉斯 =====
    print("\n" + "="*60)
    print("策略2: 七星拉普拉斯高斯")
    print("="*60)
    
    cerebro2 = bt.Cerebro()
    cerebro2.broker.setcash(INITIAL_CASH)
    cerebro2.broker.setcommission(commission=COMMISSION)
    cerebro2.addstrategy(QixingLaplaceGaussian, **QIXING_LAPLACE_PARAMS)
    
    for symbol, data in data_dict.items():
        cerebro2.adddata(data)
    
    cerebro2.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro2.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro2.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro2.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results2 = cerebro2.run()
    strat2 = results2[0]
    
    print(f"\n初始资金:    ${INITIAL_CASH:,.2f}")
    print(f"最终资产:    ${cerebro2.broker.getvalue():,.2f}")
    total_return2 = (cerebro2.broker.getvalue() / INITIAL_CASH - 1) * 100
    print(f"总收益率:    {total_return2:+.2f}%")
    
    returns2 = strat2.analyzers.returns.get_analysis()
    if 'rtot' in returns2:
        ann2 = (1 + returns2['rtot']) ** (250 / len(strat2.data)) - 1
        print(f"年化收益率:  {ann2*100:.2f}%")
    
    sharpe2 = strat2.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe2:
        print(f"夏普比率:    {sharpe2['sharperatio']:.2f}")
    
    dd2 = strat2.analyzers.drawdown.get_analysis()
    if 'max' in dd2:
        print(f"最大回撤:    {dd2['max']*100:.2f}%")
    
    trades2 = strat2.analyzers.trades.get_analysis()
    if 'total' in trades2 and trades2['total']['total'] > 0:
        total = trades2['total']['total']
        won = trades2.get('won', {}).get('total', 0)
        lost = trades2.get('lost', {}).get('total', 0)
        wr2 = won / total * 100 if total > 0 else 0
        print(f"交易次数:    {total}")
        print(f"胜率:        {wr2:.1f}%")
    
    # ===== 对比总结 =====
    print("\n" + "="*60)
    print("对比总结")
    print("="*60)
    print(f"{'指标':<15} {'三马七星':>15} {'七星拉普拉斯':>15}")
    print("-"*45)
    print(f"{'总收益率':<15} {total_return1:>+14.2f}% {total_return2:>+14.2f}%")
    if 'rtot' in returns1 and 'rtot' in returns2:
        print(f"{'年化收益率':<15} {ann1*100:>14.2f}% {ann2*100:>14.2f}%")
    if 'sharperatio' in sharpe1 and 'sharperatio' in sharpe2:
        print(f"{'夏普比率':<15} {sharpe1['sharperatio']:>15.2f} {sharpe2['sharperatio']:>15.2f}")
    if 'max' in dd1 and 'max' in dd2:
        print(f"{'最大回撤':<15} {dd1['max']*100:>14.2f}% {dd2['max']*100:>14.2f}%")
    print("="*60)


if __name__ == '__main__':
    run_comparison_backtest()
