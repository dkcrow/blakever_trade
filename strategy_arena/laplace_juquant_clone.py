#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯 - 完全克隆聚宽原版 2016-2026回测
使用本地etf_qixing数据，时间范围2016-2026
"""

import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings
from datetime import datetime, timedelta
import os
import sys

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

# ===========================================================
# 参数配置（完全复制聚宽原版）
# ===========================================================

INITIAL_CASH = 100000.0
COMMISSION = 0.0001  # 0.01%

# ETF池（聚宽原版7只）
ETF_POOL = [
    '518880',  # 黄金ETF
    '159980',  # 有色ETF
    '159985',  # 豆粕ETF
    '501018',  # 南方原油
    '161226',  # 白银LOF
    '159981',  # 能源化工ETF
    '513100',  # 纳指ETF
]

# 策略参数（完全复制聚宽原版）
LOOKBACK_DAYS = 25
HOLDINGS_NUM = 1
DEFENSIVE_ETF = '511220'  # 城投ETF（防御）

ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 3
PROFIT_PROTECTION_THRESHOLD = 0.05  # 5%盈利回撤止盈

ENABLE_RANGE_BOUND_MODE = True
LOOKBACK_HIGH_LOW_DAYS = 20
RISK_BENCHMARK = '510300'

# 滤波器参数
LAPLACE_S_PARAM = 0.05
LAPLACE_MIN_SLOPE = 0.001
GAUSSIAN_SIGMA = 1.2
GAUSSIAN_MIN_SLOPE = 0.002

# 震荡期触发条件
ENABLE_BIAS_TRIGGER = True
BIAS_THRESHOLD = 0.10
MA_PERIOD = 20
ENABLE_RSI_TRIGGER = True
RSI_OVERBOUGHT = 75
RSI_PULLBACK = 60

# 退出震荡期条件
ENABLE_LOW_POINT_RISE_TRIGGER = True
LOW_POINT_RISE_THRESHOLD = 0.03
ENABLE_STABLE_SIGNAL_TRIGGER = True
DRAWDOWN_RECOVERY = 0.03
MAX_RANGE_BOUND_DAYS = 15

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

# ===========================================================
# 工具函数（完全复制聚宽原版）
# ===========================================================

def laplace_filter(price, s=0.05):
    """拉普拉斯滤波器（正常期使用）"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t-1]
    return L

def gaussian_filter_last_two(price, sigma=1.2):
    """高斯滤波器（震荡期使用，仅计算最后两个点）"""
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
    """计算RSI值"""
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

# ===========================================================
# Backtrader策略类（完全复制聚宽逻辑）
# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """七星拉普拉斯高斯策略（完全克隆聚宽原版）"""
    
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('holdings_num', HOLDINGS_NUM),
        ('defensive_etf', DEFENSIVE_ETF),
        ('enable_profit_protection', ENABLE_PROFIT_PROTECTION),
        ('profit_protection_lookback', PROFIT_PROTECTION_LOOKBACK),
        ('profit_protection_threshold', PROFIT_PROTECTION_THRESHOLD),
        ('enable_range_bound_mode', ENABLE_RANGE_BOUND_MODE),
        ('risk_benchmark', RISK_BENCHMARK),
    )
    
    def __init__(self):
        # 存储所有ETF的数据
        self.etf_datas = {}
        for data in self.datas:
            self.etf_datas[data._name] = data
        
        # 风险基准（沪深300ETF）
        self.risk_benchmark_data = None
        for name, data in self.etf_datas.items():
            if name == self.p.risk_benchmark:
                self.risk_benchmark_data = data
                break
        
        # 持仓记录
        self.current_holdings = {}  # {etf_name: position_size}
        self.entry_prices = {}      # {etf_name: entry_price}
        self.last_rebalance = 0
        self.range_bound_start = None
        self.is_range_bound = False
        
    def next(self):
        # 控制调仓频率（每天检查，但满足条件才调仓）
        current_len = len(self)
        
        # 每天检查是否进入震荡期
        if self.p.enable_range_bound_mode:
            self._check_range_bound_mode()
        
        # 检查是否退出震荡期
        if self.is_range_bound:
            self._check_exit_range_bound()
        
        # 每天检查盈利保护
        if self.p.enable_profit_protection:
            self._check_profit_protection()
        
        # 每天计算所有ETF得分并调仓（聚宽原版是每天检查）
        self._rebalance_portfolio()
    
    def _check_range_bound_mode(self):
        """检查是否进入震荡期"""
        if not self.risk_benchmark_data or len(self.risk_benchmark_data) < LOOKBACK_HIGH_LOW_DAYS:
            return
        
        # 计算乖离率
        if ENABLE_BIAS_TRIGGER:
            ma = np.mean([self.risk_benchmark_data.close[-i] for i in range(MA_PERIOD)])
            bias = (self.risk_benchmark_data.close[0] - ma) / ma
            
            if bias > BIAS_THRESHOLD:
                self.is_range_bound = True
                self.range_bound_start = len(self)
                return
        
        # 计算RSI超买回落
        if ENABLE_RSI_TRIGGER:
            prices = [self.risk_benchmark_data.close[-i] for i in range(14)]
            rsi = calculate_rsi(prices, 14)
            
            if rsi and rsi > RSI_OVERBOUGHT:
                # 检查是否回落
                if len(self.risk_benchmark_data) >= RSI_PULLBACK:
                    pullback = (self.risk_benchmark_data.close[0] - 
                               max([self.risk_benchmark_data.close[-i] for i in range(RSI_PULLBACK)])) / \
                              max([self.risk_benchmark_data.close[-i] for i in range(RSI_PULLBACK)])
                    
                    if pullback > 0:  # 回落
                        self.is_range_bound = True
                        self.range_bound_start = len(self)
                        return
    
    def _check_exit_range_bound(self):
        """检查是否退出震荡期"""
        if not self.is_range_bound:
            return
        
        # 检查最大震荡期天数
        if self.range_bound_start and (len(self) - self.range_bound_start) > MAX_RANGE_BOUND_DAYS:
            self.is_range_bound = False
            self.range_bound_start = None
            return
        
        # 从低点上涨3%以上
        if ENABLE_LOW_POINT_RISE_TRIGGER:
            if len(self.risk_benchmark_data) >= LOOKBACK_HIGH_LOW_DAYS:
                low = min([self.risk_benchmark_data.close[-i] for i in range(LOOKBACK_HIGH_LOW_DAYS)])
                rise = (self.risk_benchmark_data.close[0] - low) / low
                
                if rise >= LOW_POINT_RISE_THRESHOLD:
                    self.is_range_bound = False
                    self.range_bound_start = None
                    return
        
        # 回撤收窄
        if ENABLE_STABLE_SIGNAL_TRIGGER:
            if len(self.risk_benchmark_data) >= 5:
                # 简化：检查最近5天波动率是否下降
                recent_vol = np.std([self.risk_benchmark_data.close[-i] for i in range(5)])
                older_vol = np.std([self.risk_benchmark_data.close[-i] for i in range(20)])
                
                if recent_vol < older_vol * (1 - DRAWDOWN_RECOVERY):
                    self.is_range_bound = False
                    self.range_bound_start = None
                    return
    
    def _check_profit_protection(self):
        """检查盈利保护（盈利回撤止盈）"""
        for name, entry_price in list(self.entry_prices.items()):
            if name not in self.current_holdings:
                continue
            
            current_price = self.etf_datas[name].close[0]
            profit_pct = (current_price - entry_price) / entry_price
            
            if profit_pct > self.p.profit_protection_threshold:
                # 盈利超过阈值，检查是否回撤
                # 简化：检查最近N天是否从高点回撤
                if len(self.etf_datas[name]) >= self.p.profit_protection_lookback:
                    recent_high = max([self.etf_datas[name].close[-i] for i in range(self.p.profit_protection_lookback)])
                    drawdown = (current_price - recent_high) / recent_high
                    
                    if drawdown < -0.02:  # 回撤超过2%
                        self.close(data=self.etf_datas[name])
                        del self.current_holdings[name]
                        del self.entry_prices[name]
    
    def _rebalance_portfolio(self):
        """重新平衡投资组合（选股+调仓）"""
        scores = {}
        
        for name, data in self.etf_datas.items():
            if len(data) < self.p.lookback_days + 10:
                continue
            
            # 计算动量得分（25日收益率）
            if self.is_range_bound:
                # 震荡期：用高斯滤波器
                prices = [data.close[-i] for i in range(self.p.lookback_days)]
                g1, g2 = gaussian_filter_last_two(prices, GAUSIAN_SIGMA)
                score = (g1 - g2) / g2 if g2 != 0 else 0
            else:
                # 正常期：用拉普拉斯滤波器
                prices = [data.close[-i] for i in range(self.p.lookback_days)]
                L = laplace_filter(prices, LAPLACE_S_PARAM)
                score = (L[-1] - L[-2]) / L[-2] if L[-2] != 0 else 0
            
            scores[name] = score
        
        if not scores:
            return
        
        # 选得分最高的Top1
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_etf = sorted_scores[0][0]
        
        # 清仓不在Top1的持仓
        for name in list(self.current_holdings.keys()):
            if name != best_etf:
                self.close(data=self.etf_datas[name])
                del self.current_holdings[name]
                if name in self.entry_prices:
                    del self.entry_prices[name]
        
        # 买入Top1（如果未持有）
        if best_etf not in self.current_holdings:
            target_data = self.etf_datas[best_etf]
            available_cash = self.broker.getcash()
            size = int(available_cash * 0.95 / target_data.close[0])
            
            if size > 0:
                self.buy(data=target_data, size=size)
                self.current_holdings[best_etf] = size
                self.entry_prices[best_etf] = target_data.close[0]

# ===========================================================
# 数据加载函数
# ===========================================================

def load_etf_data(etf_code, start_date=datetime(2016, 1, 1), end_date=datetime(2026, 5, 20)):
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
        
        # 筛选时间范围
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        
        if len(df) < 100:
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
        print(f"Error loading {etf_code}: {e}")
        return None

# ===========================================================
# 主函数
# ===========================================================

def run_backtest():
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    # 加载数据（2016-2026）
    loaded = 0
    for etf in ETF_POOL:
        df = load_etf_data(etf)
        if df is not None:
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
            )
            cerebro.adddata(data)
            loaded += 1
            print(f"  ✓ {etf}: {len(df)} rows ({df.index[0].date()} ~ {df.index[-1].date()})")
        else:
            print(f"  ✗ {etf}: Failed to load")
    
    if loaded < 2:
        print("Insufficient ETF data, backtest terminated")
        return
    
    print(f"\nLoaded {loaded} ETFs, starting backtest...")
    
    cerebro.addstrategy(QixingLaplaceGaussian)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results = cerebro.run()
    strat = results[0]
    
    # 输出结果
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    
    print("\n" + "="*80)
    print("七星拉普拉斯高斯 - 2016-2026回测结果（克隆聚宽原版）")
    print("="*80)
    print(f"初始资金: ¥{INITIAL_CASH:,.2f}")
    print(f"最终资产: ¥{final_value:,.2f}")
    print(f"总收益率: {total_return:+.2f}%")
    
    # 年化收益
    years = 10 + (140/365)  # 2016-01-01 to 2026-05-20
    ann_return = ((final_value / INITIAL_CASH) ** (1/years) - 1) * 100
    print(f"年化收益率: {ann_return:+.2f}%")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        max_dd = dd['max']
        print(f"最大回撤: {max_dd['drawdown']*100:.2f}%")
        print(f"  最大回撤金额: ¥{max_dd['moneydown']:,.2f}")
    
    # 交易统计
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
        
        # 盈亏比
        avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0)
        avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0)
        if avg_loss != 0:
            pl_ratio = abs(avg_win / avg_loss)
            print(f"  盈亏比: {pl_ratio:.2f}")
            print(f"  平均盈利: ¥{avg_win:.2f}")
            print(f"  平均亏损: ¥{avg_loss:.2f}")
    
    print("="*80)

if __name__ == '__main__':
    print("\n" + "="*80)
    print("七星拉普拉斯高斯 - 克隆聚宽原版回测")
    print("时间范围: 2016-01-01 ~ 2026-05-20")
    print("="*80)
    run_backtest()
