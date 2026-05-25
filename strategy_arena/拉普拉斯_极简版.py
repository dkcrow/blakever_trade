#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯高斯策略 - 极简版（对齐聚宽原版核心逻辑）
只保留：动量得分 + 拉普拉斯/高斯双滤波 + 震荡期切换
去掉所有复杂过滤，确保能买到高波动ETF
"""

import backtrader as bt
import numpy as np
import math
import pandas as pd
from datetime import datetime
import os

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

# 聚宽原版7只ETF
ETF_POOL = [
    '518880',  # 黄金ETF
    '159985',  # 豆粕ETF
    '501018',  # 南方原油（核心高波动）
    '161226',  # 白银LOF
    '513100',  # 纳指ETF（核心高波动）
    '159915',  # 创业板ETF（核心高波动）
    '511220',  # 城投债ETF（防御）
]

LOOKBACK_DAYS = 25
DEFENSIVE_ETF = '511220'

# 震荡期参数
MA_PERIOD = 20
LOOKBACK_HIGH_LOW_DAYS = 20
BIAS_THRESHOLD = 0.10
RSI_OVERBOUGHT = 70
RSI_PULLBACK = 65
LAPLACE_S_PARAM = 0.05
GAUSSIAN_SIGMA = 1.2


def laplace_filter(price, s=0.05):
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price, sigma=1.2):
    n = len(price)
    if n < 2:
        return 0, 0
    idx_1 = np.arange(n)
    weights_1 = np.exp(-(idx_1 + 1) ** 2 / (2 * sigma ** 2))[::-1]
    weights_1 /= np.sum(weights_1)
    g1 = np.sum(price * weights_1)
    price_2 = price[:-1]
    idx_2 = np.arange(n - 1)
    weights_2 = np.exp(-(idx_2 + 1) ** 2 / (2 * sigma ** 2))[::-1]
    weights_2 /= np.sum(weights_2)
    g2 = np.sum(price_2 * weights_2)
    return g1, g2


def calculate_rsi(prices, period=14):
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
    rsi = 100 - (100 / (1 + rs))
    return rsi


class LaplaceGaussianSimple(bt.Strategy):
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('defensive_etf', DEFENSIVE_ETF),
    )
    
    def __init__(self):
        self.etf_datas = {}
        self.current_filter = '正常期'
        self.previous_rsi = None
        self.benchmark_data = None
        
        for etf in ETF_POOL:
            if etf in [d._name for d in self.datas]:
                self.etf_datas[etf] = self.getdatabyname(etf)
        
        # 基准用159915创业板
        self.benchmark_data = self.etf_datas.get('159915')
        
        print(f"策略初始化完成，加载 {len(self.etf_datas)} 只ETF")
        print(f"防御ETF: {self.p.defensive_etf}")
    
    def next(self):
        # 检查震荡期
        self._check_range_bound()
        
        # 计算得分
        rankings = self._calculate_all()
        
        # 执行交易
        self._execute_trades(rankings)
    
    def _check_range_bound(self):
        if not self.benchmark_data:
            return
        
        lookback = max(MA_PERIOD, LOOKBACK_HIGH_LOW_DAYS) + 5
        closes = []
        for i in range(-lookback, 0):
            if len(self.benchmark_data) + i >= 0:
                closes.append(self.benchmark_data.close[i])
        
        if len(closes) < MA_PERIOD:
            return
        
        close_series = np.array(closes)
        current_price = close_series[-1]
        ma = np.mean(close_series[-MA_PERIOD:])
        bias = (current_price - ma) / ma if ma > 0 else 0
        
        current_rsi = calculate_rsi(close_series)
        
        should_enter = False
        if bias > BIAS_THRESHOLD:
            should_enter = True
        if not should_enter and current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        should_exit = False
        if self.current_filter == '震荡期':
            if current_price > ma and bias < BIAS_THRESHOLD * 0.5:
                should_exit = True
        
        if should_enter and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            print(f"[{self.data.datetime.date(0)}] 进入震荡期 → 高斯滤波")
        elif should_exit and self.current_filter == '震荡期':
            self.current_filter = '正常期'
            print(f"[{self.data.datetime.date(0)}] 退出震荡期 → 拉普拉斯滤波")
        
        self.previous_rsi = current_rsi
    
    def _calculate_all(self):
        metrics = []
        for etf in ETF_POOL:
            if etf not in self.etf_datas:
                continue
            m = self._calculate_momentum(etf)
            if m:
                metrics.append(m)
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def _calculate_momentum(self, etf):
        data = self.etf_datas.get(etf)
        if not data:
            return None
        
        try:
            lookback = self.p.lookback_days + 20
            closes = []
            for i in range(-lookback, 0):
                if len(data) + i >= 0:
                    closes.append(data.close[i])
            
            if len(closes) < self.p.lookback_days:
                return None
            
            current_price = closes[-1]
            price_series = np.array(closes)
            
            # 动量计算
            recent = price_series[-(self.p.lookback_days + 1):]
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.exp(slope * 250) - 1
            
            # R²
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            score = annualized_returns * r_squared
            
            # 滤波器检查
            if etf != self.p.defensive_etf:
                laplace_values = laplace_filter(price_series, s=LAPLACE_S_PARAM)
                laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
                passed_laplace = (current_price > laplace_values[-1] and laplace_slope > 0.001)
                
                g1_val, g2_val = gaussian_filter_last_two(price_series, sigma=GAUSSIAN_SIGMA)
                gaussian_slope = g1_val - g2_val
                passed_gaussian = (current_price > g1_val and gaussian_slope > 0.002)
                
                if self.current_filter == '正常期':
                    if not passed_laplace:
                        return None
                else:
                    if not passed_gaussian:
                        return None
            
            return {
                'etf': etf,
                'score': score,
                'current_price': current_price,
            }
        except Exception as e:
            return None
    
    def _execute_trades(self, rankings):
        # 当前持仓
        current_pos = None
        for etf in self.etf_datas:
            pos = self.getposition(self.etf_datas[etf])
            if pos.size > 0:
                current_pos = etf
                break
        
        if not rankings:
            # 无合格ETF，持有防御
            if current_pos != self.p.defensive_etf:
                if current_pos:
                    self.close(self.etf_datas[current_pos])
                self._buy_defensive()
            return
        
        target = rankings[0]['etf']
        
        if current_pos == target:
            return
        
        if current_pos:
            self.close(self.etf_datas[current_pos])
            print(f"[{self.data.datetime.date(0)}] 卖出: {current_pos}")
        
        if target in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[target].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[target], size=size)
                print(f"[{self.data.datetime.date(0)}] 买入: {target} {size}股 @ {price:.3f}")
    
    def _buy_defensive(self):
        if self.p.defensive_etf in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[self.p.defensive_etf].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[self.p.defensive_etf], size=size)
                print(f"[{self.data.datetime.date(0)}] 买入防御: {self.p.defensive_etf} {size}股 @ {price:.3f}")


def run_backtest():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(LaplaceGaussianSimple)
    
    loaded = 0
    for etf in ETF_POOL:
        df = load_etf_data(etf)
        if df is not None and len(df) > 100:
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
                fromdate=datetime(2026, 2, 1),
                todate=datetime(2026, 4, 16)
            )
            cerebro.adddata(data)
            loaded += 1
    
    if loaded < 2:
        print("数据不足")
        return
    
    print(f"加载 {loaded} 只ETF数据")
    
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0001)
    
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("="*80)
    print("拉普拉斯高斯策略 - 极简版（对齐聚宽核心逻辑）")
    print("="*80)
    print("回测: 2026-02-01 ~ 2026-04-16 (75天)")
    print("ETF池: 7只（原版g.etf_pool_bak）")
    print("="*80)
    
    strat = cerebro.run()[0]
    
    print("\n" + "="*80)
    print("回测结果")
    print("="*80)
    
    final_value = cerebro.broker.getvalue()
    print(f"初始资金: $100,000.00")
    print(f"最终资产: ${final_value:.2f}")
    
    total_return = (final_value / 100000 - 1) * 100
    print(f"总收益率: {total_return:.2f}%")
    
    days = 75
    ann_return = ((final_value / 100000) ** (365 / days) - 1) * 100
    print(f"年化收益率: {ann_return:.2f}%")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if sharpe and 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    # 最大回撤（修复bug）
    dd = strat.analyzers.drawdown.get_analysis()
    if dd and 'max' in dd:
        max_dd = dd['max']
        if isinstance(max_dd, dict):
            print(f"最大回撤: {max_dd.get('drawdown', 0)*100:.2f}%")
        else:
            print(f"最大回撤: {max_dd*100:.2f}%")
    
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
    
    print("="*80)
    print(f"参考目标: 总收益115% 胜率68% 盈亏比9.3 盈利13次 亏损6次")
    print(f"当前结果: 总收益{total_return:.2f}% 年化{ann_return:.2f}%")
    print("="*80)


def load_etf_data(etf_code):
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return None


if __name__ == '__main__':
    run_backtest()
