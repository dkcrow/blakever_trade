#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯策略 - 完美版（2026-05-24）
核心逻辑：
1. 正常期：权益ETF动量轮动（原版逻辑）
2. 震荡期：切换到防御ETF轮动（511880/511010/511220）
3. 滤波器切换：正常期用拉普拉斯滤波，震荡期用高斯滤波
4. 退出震荡期：低点上涨3% + 回撤收窄 → 恢复权益轮动

关键改进：
- ✅ 滤波器真正生效（不改变动量计算，只改变排名优先级）
- ✅ 震荡期不空仓，而是轮动防御ETF
- ✅ 无最小持仓限制，交易频率保持
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

# ==========================================================
# 参数配置
# ==========================================================

INITIAL_CASH = 100000.0
COMMISSION = 0.0001

# ETF池（32只）
ALL_ETF_POOL = [
    '518880', '159980', '159985', '501018', '161226', '159981',
    '513100', '159509', '513290', '513500', '159529',
    '513400', '513520', '513030', '513080', '513310',
    '513730', '159792', '513130', '513050', '159920',
    '513690', '510300', '510500', '510050', '510210',
    '159915', '588080', '512100', '563360', '563300',
    '512890', '159967', '512040', '159201', '511380',
    '511010', '511220',
]

# 防御ETF池（震荡期使用）
DEFENSIVE_ETF_POOL = ['511880', '511010', '511220']

DEFENSIVE_ETF = '511880'  # 默认防御ETF

# 核心参数
LOOKBACK_DAYS = 25
HOLDINGS_NUM = 1

# 盈利保护
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 2
PROFIT_PROTECTION_THRESHOLD = 0.05

# 震荡期参数
ENABLE_RANGE_BOUND_MODE = True
RISK_BENCHMARK = '510300'
LAPLACE_S_PARAM = 0.05
GAUSSIAN_SIGMA = 1.2
MA_PERIOD = 20
BIAS_THRESHOLD = 0.10
RSI_OVERBOUGHT = 75
RSI_PULLBACK = 60
LOW_POINT_RISE_THRESHOLD = 0.03
DRAWDOWN_RECOVERY = 0.03
MAX_RANGE_BOUND_DAYS = 15

# 数据路径
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'


# ==========================================================
# 工具函数
# ===========================================================

def laplace_filter(price, s=0.05):
    """拉普拉斯滤波器（正常期）"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t-1]
    return L


def gaussian_filter(price, sigma=1.2):
    """高斯滤波器（震荡期）"""
    n = len(price)
    filtered = np.zeros(n)
    for i in range(n):
        idx = np.arange(i + 1)
        weights = np.exp(-(idx - i) ** 2 / (2 * sigma ** 2))
        weights /= np.sum(weights)
        filtered[i] = np.sum(price[:i+1] * weights)
    return filtered


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


# ==========================================================
# Backtrader策略类
# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """七星拉普拉斯高斯策略（完美版）"""
    
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('holdings_num', HOLDINGS_NUM),
        ('defensive_etf', DEFENSIVE_ETF),
        ('enable_profit_protection', ENABLE_PROFIT_PROTECTION),
        ('enable_range_bound_mode', ENABLE_RANGE_BOUND_MODE),
        ('risk_benchmark', RISK_BENCHMARK),
    )
    
    def __init__(self):
        self.etf_datas = {}
        for etf in ALL_ETF_POOL:
            if etf in self.getdatanames():
                self.etf_datas[etf] = self.getdatabyname(etf)
        
        self.defensive_datas = {}
        for etf in DEFENSIVE_ETF_POOL:
            if etf in self.getdatanames():
                self.defensive_datas[etf] = self.getdatabyname(etf)
        
        self.benchmark_data = self.etf_datas.get(self.p.risk_benchmark)
        
        self.current_filter = '正常期'
        self.range_bound_days = 0
        self.last_switch_bar = 0
        self.last_date = None
        self.previous_rsi = None
        self.previous_drawdown = None
        self.current_targets = []
        self.current_scores = {}
    
    def next(self):
        """每个交易日执行"""
        current_date = self.datas[0].datetime.date(0)
        current_bar = len(self.data)
        
        # 检查震荡期状态
        if self.p.enable_range_bound_mode:
            self.check_range_bound_mode()
        
        # 根据市场状态选择ETF池
        if self.current_filter == '震荡期':
            etf_pool = DEFENSIVE_ETF_POOL  # 防御ETF池
        else:
            etf_pool = ALL_ETF_POOL  # 全部ETF池
        
        # 计算排名
        ranked = self.get_ranked_etfs(etf_pool)
        
        # 确定目标
        targets = [m['etf'] for m in ranked[:self.p.holdings_num] if m['score'] > 0]
        
        if not targets:
            # 没有符合条件的，用默认防御ETF
            if self.p.defensive_etf in self.etf_datas:
                targets = [self.p.defensive_etf]
        
        # 执行再平衡
        if targets != self.current_targets:
            self._rebalance(targets)
            self.last_switch_bar = current_bar
        
        self.last_date = current_date
    
    def _rebalance(self, targets):
        """执行再平衡"""
        # 卖出不在目标的持仓
        for d in self.datas:
            etf = d._name
            if self.getposition(d).size > 0 and etf not in targets:
                self.close(d)
                print(f"[{self.last_date}] 卖出: {etf}")
        
        # 买入目标（等权）
        if targets:
            target_value = self.broker.getvalue() / len(targets)
            for etf in targets:
                d = self.getdatabyname(etf)
                if d and self.getposition(d).size == 0:
                    size = int(target_value / d.close[0] // 100 * 100)
                    if size > 0:
                        self.buy(d, size=size)
                        print(f"[{self.last_date}] 买入: {etf} {size}股 @ {d.close[0]:.3f}")
        
        self.current_targets = targets
    
    def get_ranked_etfs(self, etf_pool):
        """计算排名"""
        metrics = []
        for etf in etf_pool:
            if etf not in self.etf_datas:
                continue
            m = self.calculate_momentum(etf)
            if m:
                metrics.append(m)
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def calculate_momentum(self, etf):
        """计算动量（根据状态选择滤波）"""
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
            
            # 盈利保护
            if self.p.enable_profit_protection:
                recent_high = max(closes[-(PROFIT_PROTECTION_LOOKBACK + 1):])
                if current_price < recent_high * (1 - PROFIT_PROTECTION_THRESHOLD):
                    return None
            
            # 根据市场状态选择滤波器
            if self.current_filter == '震荡期':
                # 震荡期：用高斯滤波
                filtered = gaussian_filter(price_series, sigma=GAUSSIAN_SIGMA)
            else:
                # 正常期：用拉普拉斯滤波
                filtered = laplace_filter(price_series, s=LAPLACE_S_PARAM)
            
            recent = filtered[-(self.p.lookback_days + 1):]
            
            # 动量计算（对数加权回归）
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.exp(slope * 250) - 1
            
            # R²
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            return {
                'etf': etf,
                'score': annualized_returns * r_squared
            }
        except:
            return None
    
    def check_range_bound_mode(self):
        """检查震荡期"""
        if not self.benchmark_data:
            return
        
        lookback = max(MA_PERIOD, 20) + 5
        closes, highs, lows = [], [], []
        for i in range(-lookback, 0):
            if len(self.benchmark_data) + i >= 0:
                closes.append(self.benchmark_data.close[i])
                highs.append(self.benchmark_data.high[i])
                lows.append(self.benchmark_data.low[i])
        
        if len(closes) < MA_PERIOD:
            return
        
        close_series = np.array(closes)
        high_series = np.array(highs)
        low_series = np.array(lows)
        
        current_price = close_series[-1]
        ma = np.mean(close_series[-MA_PERIOD:])
        recent_low = np.min(low_series[-20:])
        
        bias = (current_price - ma) / ma if ma > 0 else 0
        current_rsi = calculate_rsi(close_series)
        
        # 进入震荡期
        should_enter = False
        if bias > BIAS_THRESHOLD:
            should_enter = True
        if current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        # 退出震荡期
        should_exit = False
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        if rise_from_low >= LOW_POINT_RISE_THRESHOLD:
            should_exit = True
        
        # 回撤收窄
        if self.previous_drawdown is not None:
            current_drawdown = (ma - current_price) / ma if ma > 0 else 0
            if abs(current_drawdown) < abs(self.previous_drawdown) * (1 - DRAWDOWN_RECOVERY):
                should_exit = True
        
        # 状态切换
        if should_enter and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            self.range_bound_days = 0
            print(f"[{self.last_date}] 进入震荡期 → 切换防御ETF轮动")
        elif should_exit and self.current_filter == '震荡期':
            self.current_filter = '正常期'
            print(f"[{self.last_date}] 退出震荡期 → 恢复权益ETF轮动")
        
        # 最大震荡期限制
        if self.current_filter == '震荡期':
            self.range_bound_days += 1
            if self.range_bound_days > MAX_RANGE_BOUND_DAYS:
                self.current_filter = '正常期'
                print(f"[{self.last_date}] 震荡期超时 → 强制退出")
        
        self.previous_rsi = current_rsi
        if len(close_series) > MA_PERIOD:
            ma_now = np.mean(close_series[-MA_PERIOD:])
            self.previous_drawdown = (ma_now - current_price) / ma_now if ma_now > 0 else 0


# ==========================================================
# 主函数
# ===========================================================

def load_etf_data(etf_code, fd, td):
    """加载ETF数据"""
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
        df = df[(df.index >= pd.Timestamp(fd)) & (df.index <= pd.Timestamp(td))]
        return df if len(df) > 100 else None
    except:
        return None


def run_backtest(fd, td):
    """运行回测"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    cerebro.addstrategy(QixingLaplaceGaussian)
    
    loaded = 0
    for etf in ALL_ETF_POOL:
        df = load_etf_data(etf, fd, td)
        if df is not None:
            data = bt.feeds.PandasData(
                dataname=df, name=etf,
                fromdate=fd, todate=td
            )
            cerebro.adddata(data)
            loaded += 1
    
    if loaded < 2:
        print("有效ETF数据不足")
        return
    
    print(f"成功加载 {loaded} 只ETF数据")
    
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("\n开始回测...")
    results = cerebro.run()
    strat = results[0]
    
    print("\n" + "="*60)
    print("回测结果")
    print("="*60)
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    days = (td - fd).days
    ann_return = ((final_value / INITIAL_CASH) ** (365.0 / days) - 1) * 100
    
    print(f"初始资金: ${INITIAL_CASH:,.2f}")
    print(f"最终资产: ${final_value:,.2f}")
    print(f"总收益率: {total_return:+.2f}%")
    print(f"年化收益率: {ann_return:.2f}%")
    
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd and 'drawdown' in dd['max']:
        print(f"最大回撤: {dd['max']['drawdown']*100:.2f}%")
    
    print(f"当前状态: {strat.current_filter}")
    
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
        print(f"  平均盈利: ${avg_win:.2f}")
        print(f"  平均亏损: ${avg_loss:.2f}")
        print(f"  年化交易次数: {total_trades / (days/365):.1f} 笔/年")
    
    print("="*60)


if __name__ == '__main__':
    fd = datetime(2023, 1, 1)
    td = datetime(2026, 5, 21)
    run_backtest(fd, td)
