#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯策略 - 5年回测版本（2019-2026）
核心ETF：159985（豆粕）、501018（原油）、161226（白银）
数据起始：2019-12-05（豆粕最早）→ 2026-05-22
"""

import sys
import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings
from datetime import datetime
import os

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# ===========================================================
# 参数配置（对齐聚宽原版）
# ===========================================================

INITIAL_CASH = 100000.0
COMMISSION = 0.0001  # 0.01%

# 核心ETF池（3只，有5年+数据）
ETF_POOL_5Y = [
    '159985',  # 豆粕ETF（2019-12-05起，5.5年）
    '501018',  # 南方原油（2018-02-09起，8.3年）
    '161226',  # 白银LOF（2018-02-09起，8.3年）
]

# 参数
LOOKBACK_DAYS = 25
HOLDINGS_NUM = 1
DEFENSIVE_ETF = '511220'  # 城投债（防御用，数据不足5年但短期可用）

# 盈利保护
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1
PROFIT_PROTECTION_THRESHOLD = 0.05

# 震荡期参数
ENABLE_RANGE_BOUND_MODE = True
LOOKBACK_HIGH_LOW_DAYS = 20
RISK_BENCHMARK = '159985'  # 用豆粕作为风险基准
LAPLACE_S_PARAM = 0.05
LAPLACE_MIN_SLOPE = 0.001
GAUSSIAN_SIGMA = 1.2
GAUSSIAN_MIN_SLOPE = 0.002

ENABLE_BIAS_TRIGGER = True
BIAS_THRESHOLD = 0.10
MA_PERIOD = 20
ENABLE_RSI_TRIGGER = True
RSI_OVERBOUGHT = 75
RSI_PULLBACK = 60

# 数据路径
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

# ===========================================================
# 工具函数
# ===========================================================

def laplace_filter(price, s=0.05):
    """拉普拉斯滤波器（正常期使用）"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price, sigma=1.2):
    """高斯滤波器（震荡期使用）"""
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
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ===========================================================
# Backtrader策略类
# ===========================================================

class QixingLaplaceGaussian5Y(bt.Strategy):
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
        self.etf_datas = {}
        self.current_filter = '正常期'
        self.range_bound_days = 0
        self.previous_rsi = None
        
        for etf in ETF_POOL_5Y:
            if etf in self.getdatanames():
                self.etf_datas[etf] = self.getdatabyname(etf)
                print(f"  加载ETF: {etf}")
        
        # 防御ETF（可选）
        self.defensive_data = None
        if DEFENSIVE_ETF in self.getdatanames():
            self.defensive_data = self.getdatabyname(DEFENSIVE_ETF)
        
        # 风险基准
        self.benchmark_data = None
        if RISK_BENCHMARK in self.getdatanames():
            self.benchmark_data = self.getdatabyname(RISK_BENCHMARK)
        
        print(f"\n策略初始化完成")
        print(f"  核心ETF: {len(self.etf_datas)}只（5年+数据）")
        print(f"  持仓数量: {self.p.holdings_num}")
        defensive_status = '已加载' if self.defensive_data is not None else '未加载'
        print(f"  防御ETF: {DEFENSIVE_ETF} ({defensive_status})")
        print(f"  风险基准: {RISK_BENCHMARK}")
        print(f"  当前滤波器: {self.current_filter}")
    
    def next(self):
        current_date = self.datas[0].datetime.date(0)
        
        # 检查震荡期
        if self.p.enable_range_bound_mode and self.benchmark_data:
            self.check_range_bound_mode(current_date)
        
        # 计算排名
        rankings = self.calculate_all_rankings()
        
        if not rankings:
            self._buy_defensive()
            return
        
        # 执行交易
        self.execute_trades(rankings)
    
    def check_range_bound_mode(self, current_date):
        """检查震荡期切换"""
        lookback = max(MA_PERIOD, LOOKBACK_HIGH_LOW_DAYS) + 5
        closes = []
        highs = []
        lows = []
        
        for i in range(-lookback, 0):
            if len(self.benchmark_data) + i >= 0:
                closes.append(self.benchmark_data.close[i])
                highs.append(self.benchmark_data.high[i])
                lows.append(self.benchmark_data.low[i])
        
        if len(closes) < MA_PERIOD:
            return
        
        close_series = np.array(closes)
        current_price = close_series[-1]
        ma = np.mean(close_series[-MA_PERIOD:])
        bias = (current_price - ma) / ma if ma > 0 else 0
        
        current_rsi = calculate_rsi(close_series)
        
        should_enter = False
        if ENABLE_BIAS_TRIGGER and abs(bias) > BIAS_THRESHOLD:
            should_enter = True
        if not should_enter and current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        should_exit = False
        if self.current_filter == '震荡期':
            if current_price > ma and abs(bias) < BIAS_THRESHOLD * 0.5:
                should_exit = True
        
        if should_enter and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            print(f"[{current_date}] 进入震荡期 → 切换高斯滤波")
        elif should_exit and self.current_filter == '震荡期':
            self.current_filter = '正常期'
            print(f"[{current_date}] 退出震荡期 → 切换拉普拉斯滤波")
        
        self.previous_rsi = current_rsi
    
    def calculate_all_rankings(self):
        """计算所有ETF得分"""
        metrics = []
        for etf in ETF_POOL_5Y:
            if etf not in self.etf_datas:
                continue
            m = self.calculate_momentum(etf)
            if m and m['score'] > 0:
                metrics.append(m)
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def calculate_momentum(self, etf):
        """计算动量指标"""
        data = self.etf_datas.get(etf)
        if not data:
            return None
        
        try:
            lookback_total = self.p.lookback_days + 20
            closes = []
            for i in range(-lookback_total, 0):
                if len(data) + i >= 0:
                    closes.append(data.close[i])
            
            if len(closes) < self.p.lookback_days:
                return None
            
            current_price = closes[-1]
            price_series = np.array(closes)
            
            # 盈利保护
            if self.p.enable_profit_protection:
                pos = self.getposition(data)
                if pos.size > 0:
                    recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                    if current_price < recent_high * (1 - self.p.profit_protection_threshold):
                        return None
            
            # 长期动量
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
            
            # 动态滤波器
            if etf != self.p.defensive_etf:
                laplace_values = laplace_filter(price_series, s=LAPLACE_S_PARAM)
                laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
                passed_laplace = (current_price > laplace_values[-1] and laplace_slope > LAPLACE_MIN_SLOPE)
                
                g1_val, g2_val = gaussian_filter_last_two(price_series, sigma=GAUSSIAN_SIGMA)
                gaussian_slope = g1_val - g2_val
                passed_gaussian = (current_price > g1_val and gaussian_slope > GAUSSIAN_MIN_SLOPE)
                
                if self.current_filter == '正常期':
                    if not passed_laplace:
                        return None
                else:
                    if not passed_gaussian:
                        return None
            
            return {
                'etf': etf,
                'score': score,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'current_price': current_price,
            }
        except Exception as e:
            return None
    
    def execute_trades(self, rankings):
        """执行交易"""
        # 当前持仓
        current_pos = None
        for etf in self.etf_datas:
            pos = self.getposition(self.etf_datas[etf])
            if pos.size > 0:
                current_pos = etf
                break
        
        if not rankings:
            if current_pos:
                self.close(self.etf_datas[current_pos])
                print(f"[{self.datas[0].datetime.date(0)}] 卖出: {current_pos}（无合格ETF）")
            self._buy_defensive()
            return
        
        target = rankings[0]['etf']
        
        if current_pos == target:
            return  # 已持有目标
        
        # 卖出旧持仓
        if current_pos:
            self.close(self.etf_datas[current_pos])
            print(f"[{self.datas[0].datetime.date(0)}] 卖出: {current_pos}")
        
        # 买入新目标
        if target in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[target].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[target], size=size)
                print(f"[{self.datas[0].datetime.date(0)}] 买入: {target} {size}股 @ {price:.3f}")
    
    def _buy_defensive(self):
        """买入防御ETF"""
        if not self.defensive_data:
            return
        
        cash = self.broker.getcash()
        price = self.defensive_data.close[0]
        size = int(cash / price)
        if size > 0:
            self.buy(self.defensive_data, size=size)
            print(f"[{self.datas[0].datetime.date(0)}] 买入防御: {DEFENSIVE_ETF} {size}股 @ {price:.3f}")


# ===========================================================
# 数据加载与回测
# ===========================================================

def load_etf_data(etf_code):
    """加载本地ETF数据"""
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    if not os.path.exists(csv_path):
        return None
    
    try:
        df = pd.read_csv(csv_path, parse_dates=['Date'], index_col='Date')
        if df.empty:
            return None
        return df
    except Exception as e:
        print(f"  加载失败 {etf_code}: {e}")
        return None


def run_backtest():
    """运行5年回测（2019-2026）"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    cerebro.addstrategy(QixingLaplaceGaussian5Y)
    
    # 加载数据（2019-2026）
    loaded = 0
    for etf in ETF_POOL_5Y:
        df = load_etf_data(etf)
        if df is not None and len(df) > 100:
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
                fromdate=datetime(2019, 12, 1),  # 豆粕最早2019-12-05
                todate=datetime(2026, 5, 22)
            )
            cerebro.adddata(data)
            loaded += 1
            print(f"✓ {etf}: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}天)")
    
    # 防御ETF（如果有数据）
    if DEFENSIVE_ETF not in ETF_POOL_5Y:
        df_def = load_etf_data(DEFENSIVE_ETF)
        if df_def is not None:
            data = bt.feeds.PandasData(
                dataname=df_def,
                name=DEFENSIVE_ETF,
                fromdate=datetime(2019, 12, 1),
                todate=datetime(2026, 5, 22)
            )
            cerebro.adddata(data)
            print(f"✓ {DEFENSIVE_ETF} (防御): {df_def.index[0].date()} ~ {df_def.index[-1].date()}")
    
    if loaded < 2:
        print("有效ETF数据不足，回测终止")
        return
    
    print(f"\n成功加载 {loaded} 只核心ETF数据")
    print(f"回测时间: 2019-12-01 ~ 2026-05-22（约6.5年）")
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')
    
    print("\n" + "="*80)
    print("开始5年回测: 七星拉普拉斯高斯策略（核心3只ETF）")
    print("="*80)
    print(f"ETF池: {loaded}只（159985豆粕/501018原油/161226白银）")
    print(f"持仓: Top{HOLDINGS_NUM}（等权）")
    print(f"防御ETF: {DEFENSIVE_ETF}（城投债，可选）")
    print("="*80)
    
    strat = cerebro.run()[0]
    
    print("\n" + "="*80)
    print("回测结果")
    print("="*80)
    
    final_value = cerebro.broker.getvalue()
    print(f"初始资金: ¥{INITIAL_CASH:,.2f}")
    print(f"最终资产: ¥{final_value:,.2f}")
    
    total_return = (final_value / INITIAL_CASH - 1) * 100
    print(f"总收益率: {total_return:+.2f}%")
    
    # 年化收益
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns:
        n_days = len(strat.data)
        ann_return = (1 + returns['rtot']) ** (250 / n_days) - 1
        print(f"年化收益率: {ann_return*100:+.2f}%")
        print(f"实际交易天数: {n_days}天（约{n_days/250:.1f}年）")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if sharpe and 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        max_dd = dd['max']
        if isinstance(max_dd, dict):
            print(f"最大回撤: {max_dd.get('drawdown', 0)*100:.2f}%")
            print(f"回撤长度: {max_dd.get('len', 0)}天")
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
        
        print(f"\n📊 交易统计:")
        print(f"  总交易: {total_trades}笔")
        print(f"  盈利: {won}笔  亏损: {lost}笔")
        print(f"  胜率: {win_rate:.1f}%")
        print(f"  盈亏比: {pl_ratio:.2f}")
        print(f"  平均盈利: ¥{avg_win:.2f}" if avg_win else "  平均盈利: N/A")
        print(f"  平均亏损: ¥{avg_loss:.2f}" if avg_loss else "  平均亏损: N/A")
    
    print("="*80)
    print(f"\n聚宽原版参考（10年）: 年化20%+  胜率68%  盈亏比9.3")
    print(f"当前5年回测: 数据{loaded}只ETF，约6.5年（2019.12-2026.05）")
    print("="*80)


if __name__ == '__main__':
    run_backtest()
