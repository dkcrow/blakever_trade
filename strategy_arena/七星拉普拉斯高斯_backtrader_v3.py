#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯策略 - Backtrader版本 v3
===================================================
数据源：akshare（A股）+ yfinance（美股ETF）
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
COMMISSION = 0.0001

# ETF池（聚宽代码）
ETF_POOL = [
    '518880',  # 黄金ETF
    '159985',  # 豆粕ETF
    '513100',  # 纳指ETF
    '159915',  # 创业板ETF
    '510300',  # 沪深300ETF
    '510500',  # 中证500ETF
    '510050',  # 上证50ETF
    '159920',  # 恒生ETF
    '513500',  # 标普500ETF
    '511010',  # 国债ETF
    '511220',  # 城投债ETF
]

DEFENSIVE_ETF = '511880'

# 核心参数
LOOKBACK_DAYS = 25
HOLDINGS_NUM = 1
MIN_MONEY = 5000

# 盈利保护
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1
PROFIT_PROTECTION_THRESHOLD = 0.05

# 震荡期
ENABLE_RANGE_BOUND_MODE = True
LOOKBACK_HIGH_LOW_DAYS = 20
RISK_BENCHMARK = '510300'
LAPLACE_S_PARAM = 0.05
LAPLACE_MIN_SLOPE = 0.001
GAUSSIAN_SIGMA = 1.2
GAUSSIAN_MIN_SLOPE = 0.002
MA_PERIOD = 20
BIAS_THRESHOLD = 0.10
RSI_OVERBOUGHT = 75
RSI_PULLBACK = 60
LOW_POINT_RISE_THRESHOLD = 0.03
DRAWDOWN_RECOVERY = 0.03
MAX_RANGE_BOUND_DAYS = 15

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_data'
os.makedirs(DATA_DIR, exist_ok=True)


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


def gaussian_filter_last_two(price, sigma=1.2):
    """高斯滤波器"""
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
    return 100 - (100 / (1 + rs))


def fetch_with_akshare(etf_code):
    """用akshare获取A股ETF数据"""
    print(f"  正在用akshare下载 {etf_code}...")
    try:
        import akshare as ak
        
        # 聚宽代码转akshare格式
        if etf_code.startswith('51') or etf_code.startswith('50'):
            # 上海ETF: 518880.XSHG -> sh518880
            symbol = f"sh{etf_code}"
        elif etf_code.startswith('15') or etf_code.startswith('16'):
            # 深圳ETF
            symbol = f"sz{etf_code}"
        else:
            print(f"  无法识别: {etf_code}")
            return None
        
        # 获取ETF历史数据（最近5年）
        df = ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date="20190101",
            end_date="20241231",
            adjust="qfq"  # 前复权
        )
        
        if df.empty:
            print(f"  akshare无数据: {symbol}")
            return None
        
        # 标准化列名
        df = df.rename(columns={
            '日期': 'date', '开盘': 'open', '收盘': 'close',
            '最高': 'high', '最低': 'low', '成交量': 'volume'
        })
        
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df = df.sort_index()
        
        print(f"  ✓ {len(df)}条数据")
        return df
        
    except Exception as e:
        print(f"  失败: {e}")
        return None


def load_etf_data(etf_code):
    """加载或下载ETF数据"""
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
            if len(df) > 100:
                print(f"  ✓ {etf_code} ({len(df)}条)")
                return df
        except:
            pass
    
    # 下载
    df = fetch_with_akshare(etf_code)
    if df is not None and len(df) > 100:
        df.to_csv(csv_path)
        return df
    return None


# ===========================================================
# Backtrader策略
# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """七星拉普拉斯高斯策略"""
    
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('holdings_num', HOLDINGS_NUM),
        ('defensive_etf', DEFENSIVE_ETF),
        ('enable_profit_protection', ENABLE_PROFIT_PROTECTION),
        ('enable_range_bound', ENABLE_RANGE_BOUND_MODE),
        ('risk_benchmark', RISK_BENCHMARK),
    )
    
    def __init__(self):
        self.etf_datas = {}
        self.benchmark_data = None
        
        for d in self.datas:
            name = d._name
            self.etf_datas[name] = d
            if name == self.p.risk_benchmark:
                self.benchmark_data = d
        
        self.current_filter = '正常期'
        self.range_bound_start = None
        self.last_switch_date = None
        self.previous_rsi = None
        self.previous_drawdown = None
        
    def next(self):
        dt = self.datas[0].datetime.date(0)
        
        # 检查震荡期
        if self.p.enable_range_bound:
            self._check_range_bound()
        
        # 计算排名
        ranked = self._get_ranked_etfs()
        
        if not ranked:
            return
        
        # 确定目标
        targets = [m['etf'] for m in ranked[:self.p.holdings_num] if m['score'] > 0]
        
        if not targets and self.p.defensive_etf in self.etf_datas:
            targets = [self.p.defensive_etf]
        
        # 卖出不在目标的持仓
        for name, d in self.etf_datas.items():
            pos = self.getposition(d).size
            if pos > 0 and name not in targets:
                self.close(d)
                print(f"[{dt}] 卖出 {name}")
        
        # 买入目标
        if targets:
            target_val = self.broker.getvalue() / len(targets)
            for etf in targets:
                d = self.etf_datas.get(etf)
                if not d:
                    continue
                pos = self.getposition(d).size
                cur_val = pos * d.close[0]
                if abs(cur_val - target_val) > target_val * 0.05 or pos == 0:
                    size = int(target_val / d.close[0] / 100) * 100
                    if size > 0 and size != pos:
                        self.order_target_size(d, size)
                        print(f"[{dt}] 买入 {etf} {size}股 @ {d.close[0]:.3f}")
    
    def _get_ranked_etfs(self):
        """计算ETF排名"""
        metrics = []
        for etf, d in self.etf_datas.items():
            if len(d) < self.p.lookback_days + 5:
                continue
            m = self._calc_momentum(d, etf)
            if m:
                metrics.append(m)
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def _calc_momentum(self, d, etf):
        """计算动量指标"""
        try:
            lookback = self.p.lookback_days + 20
            lookback = min(lookback, len(d))
            closes = [d.close[i] for i in range(-lookback, 0)]
            
            if len(closes) < self.p.lookback_days:
                return None
            
            current_price = closes[-1]
            price_series = np.array(closes)
            
            # 盈利保护
            if self.p.enable_profit_protection:
                recent_high = max(closes[-(PROFIT_PROTECTION_LOOKBACK + 1):])
                if current_price < recent_high * (1 - PROFIT_PROTECTION_THRESHOLD):
                    return None
            
            # 动量计算
            recent = price_series[-(self.p.lookback_days + 1):]
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
            
            return {
                'etf': etf,
                'annualized_returns': ann_return,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
            }
        except Exception as e:
            return None
    
    def _check_range_bound(self):
        """检查震荡期状态"""
        if not self.benchmark_data:
            return
        
        d = self.benchmark_data
        if len(d) < MA_PERIOD:
            return
        
        lookback = max(MA_PERIOD, LOOKBACK_HIGH_LOW_DAYS) + 5
        lookback = min(lookback, len(d))
        
        closes = [d.close[i] for i in range(-lookback, 0)]
        highs = [d.high[i] for i in range(-lookback, 0)]
        lows = [d.low[i] for i in range(-lookback, 0)]
        
        close_arr = np.array(closes)
        high_arr = np.array(highs)
        low_arr = np.array(lows)
        
        current_price = close_arr[-1]
        ma = np.mean(close_arr[-MA_PERIOD:])
        recent_high = np.max(high_arr[-LOOKBACK_HIGH_LOW_DAYS:])
        recent_low = np.min(low_arr[-LOOKBACK_HIGH_LOW_DAYS:])
        
        bias = (current_price - ma) / ma if ma > 0 else 0
        current_rsi = calculate_rsi(close_arr, 14)
        
        # 检查进入震荡期
        should_enter = False
        if bias > BIAS_THRESHOLD:
            should_enter = True
        if current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        # 检查退出
        should_exit = False
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        if rise_from_low >= LOW_POINT_RISE_THRESHOLD:
            should_exit = True
        
        dt = self.datas[0].datetime.date(0)
        
        if should_enter and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            self.range_bound_start = dt
            print(f"\n[{dt}] *** 进入震荡期（高斯滤波器）***")
        elif should_exit and self.current_filter == '震荡期':
            self.current_filter = '正常期'
            print(f"\n[{dt}] *** 退出震荡期（拉普拉斯滤波器）***")
        
        self.previous_rsi = current_rsi


# ===========================================================
# 主函数
# ===========================================================

def run_backtest():
    """运行回测"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addstrategy(QixingLaplaceGaussian)
    
    print("\n正在加载ETF数据...")
    loaded = 0
    for etf in ETF_POOL:
        print(f"  {etf}: ", end='', flush=True)
        df = load_etf_data(etf)
        if df is not None and len(df) > 100:
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
                fromdate=datetime(2019, 1, 1),
                todate=datetime(2024, 12, 31)
            )
            cerebro.adddata(data)
            loaded += 1
    
    if loaded < 2:
        print(f"\n✗ 有效数据不足（仅{loaded}只），回测终止")
        return
    
    print(f"\n✓ 成功加载 {loaded} 只ETF数据")
    
    # 分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("\n开始回测...\n")
    results = cerebro.run()
    strat = results[0]
    
    # 结果
    print("\n" + "="*60)
    print("回测结果")
    print("="*60)
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    
    print(f"初始资金:    ¥{INITIAL_CASH:,.2f}")
    print(f"最终资产:    ¥{final_value:,.2f}")
    print(f"总收益率:    {total_return:+.2f}%")
    
    # 年化
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns and len(strat.data) > 0:
        ann_return = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
        print(f"年化收益率:  {ann_return*100:.2f}%")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe:
        print(f"夏普比率:    {sharpe['sharperatio']:.2f}")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"最大回撤:    {dd['max']*100:.2f}%")
    
    # 交易统计
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        win_rate = won / total * 100 if total > 0 else 0
        print(f"\n交易统计:")
        print(f"  总交易: {total}")
        print(f"  盈利: {won}  亏损: {lost}")
        print(f"  胜率: {win_rate:.1f}%")
    
    print("="*60)


if __name__ == '__main__':
    run_backtest()
