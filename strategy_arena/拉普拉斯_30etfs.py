#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯策略 - Backtrader版本
===================================================
克隆自聚宽文章：https://www.joinquant.com/post/70329
原作者：king088

核心逻辑：
1. ETF动量轮动 + 拉普拉斯/高斯双滤波器
2. 震荡期自动检测与切换（拉普拉斯=正常期，高斯=震荡期）
3. 盈利保护、溢价率过滤、成交量过滤
4. 等权持仓（Top1）

改写为Backtrader本地回测版本
"""

import sys
import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings
from datetime import datetime, timedelta
import os
from io import StringIO

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# ===========================================================
# 参数配置
# ===========================================================

INITIAL_CASH = 100000.0
COMMISSION = 0.0001  # 0.01%

# ETF池（30只，移除513080/513730因数据缺失）
ETF_POOL = [
    '518880',  # 黄金ETF
    '159980',  # 有色ETF
    '159985',  # 豆粕ETF
    '501018',  # 南方原油
    '161226',  # 白银LOF
    '159981',  # 能源化工ETF
    '513100',  # 纳指ETF
    '159509',  # 纳指科技ETF
    '513290',  # 纳指生物ETF
    '513500',  # 标普500ETF
    '159529',  # 标普消费
    '513400',  # 道琼斯ETF
    '513520',  # 日经225ETF
    '513030',  # 德国30ETF
    '513310',  # 中韩半导体ETF
    '159792',  # 港股互联ETF
    '513130',  # 恒生科技
    '513050',  # 中概互联网ETF
    '159920',  # 恒生ETF
    '513690',  # 港股红利
    '510300',  # 沪深300ETF
    '510500',  # 中证500ETF
    '510050',  # 上证50ETF
    '510210',  # 上证ETF
    '159915',  # 创业板ETF
    '588080',  # 科创50
    '512100',  # 中证1000ETF
    '563360',  # A500-ETF
    '563300',  # 中证2000ETF
    '512890',  # 红利低波ETF
    '159967',  # 创业板成长ETF
    '512040',  # 价值ETF
    '159201',  # 自由现金流ETF
    '511380',  # 可转债ETF
    '511010',  # 国债ETF
    '511220',  # 城投债ETF
]

DEFENSIVE_ETF = '511880'  # 货币基金（防御性ETF）

# 核心参数
LOOKBACK_DAYS = 25              # 动量计算周期
HOLDINGS_NUM = 1                # 持仓数量（Top N）
MIN_MONEY = 5000                 # 最小交易金额

# 盈利保护参数
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1    # 回看周期（天）
PROFIT_PROTECTION_THRESHOLD = 0.05  # 回撤阈值（5%）

# 成交量过滤
ENABLE_VOLUME_CHECK = False  # 本地回测暂不支持实时成交量
VOLUME_LOOKBACK = 5
VOLUME_THRESHOLD = 2

# 短期动量过滤
USE_SHORT_MOMENTUM_FILTER = False
SHORT_LOOKBACK_DAYS = 10
SHORT_MOMENTUM_THRESHOLD = 0.0

# 溢价率过滤（ETF特有，本地回测暂不支持）
ENABLE_PREMIUM_FILTER = False
PREMIUM_THRESHOLD = 0.20

# 震荡期参数
ENABLE_RANGE_BOUND_MODE = True
LOOKBACK_HIGH_LOW_DAYS = 20  # 高低点回看
RISK_BENCHMARK = '510300'     # 风险基准（沪深300ETF）
LAPLACE_S_PARAM = 0.05
LAPLACE_MIN_SLOPE = 0.001
GAUSSIAN_SIGMA = 1.2
GAUSSIAN_MIN_SLOPE = 0.002

# 进入震荡期条件
ENABLE_BIAS_TRIGGER = True
BIAS_THRESHOLD = 0.10            # 乖离率阈值（10%）
MA_PERIOD = 20
ENABLE_RSI_TRIGGER = True
RSI_OVERBOUGHT = 75
RSI_PULLBACK = 60

# 退出震荡期条件
ENABLE_LOW_POINT_RISE_TRIGGER = True
LOW_POINT_RISE_THRESHOLD = 0.03  # 从低点上涨3%
ENABLE_STABLE_SIGNAL_TRIGGER = True
DRAWDOWN_RECOVERY = 0.03       # 回撤收窄阈值
MAX_RANGE_BOUND_DAYS = 15        # 最大震荡期天数

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
# Backtrader策略类
# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """七星拉普拉斯高斯策略"""
    
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
        self.etf_pool = ETF_POOL
        self.current_filter = '正常期'  # 或 '震荡期'
        self.range_bound_start = None
        self.range_bound_days = 0
        self.last_switch_date = None
        self.previous_drawdown = None
        self.previous_rsi = None
        self.stable_days = 0
        
        # 为每只ETF创建数据引用
        self.etf_datas = {}
        for i, etf in enumerate(self.etf_pool):
            if etf in self.getdatanames():
                self.etf_datas[etf] = self.getdatabyname(etf)
        
        # 防御ETF
        if self.p.defensive_etf in self.getdatanames():
            self.defensive_data = self.getdatabyname(self.p.defensive_etf)
        else:
            self.defensive_data = None
        
        # 风险基准
        if self.p.risk_benchmark in self.getdatanames():
            self.benchmark_data = self.getdatabyname(self.p.risk_benchmark)
        else:
            self.benchmark_data = None
        
        self.last_date = None
        self.current_targets = []
    
    def next(self):
        """每个交易日执行"""
        current_date = self.datas[0].datetime.date(0)
        
        # 检查震荡期状态
        if self.p.enable_range_bound_mode:
            self.check_range_bound_mode()
        
        # 计算排名
        ranked = self.get_ranked_etfs()
        
        # 确定目标ETF
        targets = []
        for m in ranked[:self.p.holdings_num]:
            if m['score'] > 0:
                targets.append(m['etf'])
        
        if not targets and self.defensive_data:
            targets = [self.p.defensive_etf]
        
        self.current_targets = targets
        
        # 卖出不在目标的持仓
        for d in self.datas:
            etf = d._name
            pos = self.getposition(d).size
            if pos > 0 and etf not in targets:
                self.close(d)
                print(f"[{current_date}] 卖出: {etf}")
        
        # 买入目标ETF（等权）
        if targets:
            target_value = self.broker.getvalue() / len(targets)
            for etf in targets:
                d = self.getdatabyname(etf)
                if d:
                    current_pos = self.getposition(d).size
                    current_val = current_pos * d.close[0]
                    if abs(current_val - target_value) > target_value * 0.05 or current_pos == 0:
                        size = int((target_value / d.close[0]) // 100 * 100)
                        if size > 0:
                            self.order_target_size(d, size)
                            print(f"[{current_date}] 买入: {etf} {size}股 @ {d.close[0]:.3f}")
        
        self.last_date = current_date
    
    def get_ranked_etfs(self):
        """计算所有ETF的动量得分并排名"""
        metrics = []
        for etf in self.etf_pool:
            if etf not in self.etf_datas:
                continue
            m = self.calculate_momentum(etf)
            if m:
                metrics.append(m)
        
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def calculate_momentum(self, etf):
        """计算单只ETF的动量指标"""
        data = self.etf_datas.get(etf)
        if not data:
            return None
        
        try:
            # 获取历史数据
            lookback = max(self.p.lookback_days, SHORT_LOOKBACK_DAYS) + 20
            closes = []
            for i in range(-lookback, 0):
                if len(data) + i >= 0:
                    closes.append(data.close[i])
            
            if len(closes) < self.p.lookback_days:
                return None
            
            current_price = closes[-1]
            price_series = np.array(closes)
            
            # 盈利保护检查
            if self.p.enable_profit_protection:
                recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                if current_price < recent_high * (1 - self.p.profit_protection_threshold):
                    return None
            
            # 长期动量计算
            recent = price_series[-(self.p.lookback_days + 1):]
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.exp(slope * 250) - 1
            
            # R²（趋势稳定性）
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            score = annualized_returns * r_squared
            
            return {
                'etf': etf,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
            }
        except Exception as e:
            return None
    
    def check_range_bound_mode(self):
        """检查是否需要切换震荡期/正常期模式"""
        if not self.benchmark_data:
            return
        
        closes = []
        highs = []
        lows = []
        for i in range(-(max(MA_PERIOD, LOOKBACK_HIGH_LOW_DAYS) + 5), 0):
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
        recent_high = np.max(high_series[-LOOKBACK_HIGH_LOW_DAYS:])
        recent_low = np.min(low_series[-LOOKBACK_HIGH_LOW_DAYS:])
        
        # 乖离率
        bias = (current_price - ma) / ma if ma > 0 else 0
        
        # RSI
        current_rsi = calculate_rsi(close_series, period=14)
        
        # 检查进入震荡期
        should_enter = False
        if ENABLE_BIAS_TRIGGER and bias > BIAS_THRESHOLD:
            should_enter = True
        if ENABLE_RSI_TRIGGER and current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        # 检查退出震荡期
        should_exit = False
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        if ENABLE_LOW_POINT_RISE_TRIGGER and rise_from_low >= LOW_POINT_RISE_THRESHOLD:
            should_exit = True
        
        # 更新状态
        if should_enter and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            self.range_bound_start = self.last_date
            print(f"[{self.last_date}] 进入震荡期（高斯滤波器）")
        elif should_exit and self.current_filter == '震荡期':
            self.current_filter = '正常期'
            print(f"[{self.last_date}] 退出震荡期（拉普拉斯滤波器）")
        
        self.previous_rsi = current_rsi


# ===========================================================
# 主函数
# ===========================================================

def fetch_etf_data_with_westock(etf_code):
    """用westock-data获取ETF数据"""
    import subprocess
    import json
    
    print(f"正在用westock获取 {etf_code} 数据...")
    try:
        # 转换聚宽代码到westock格式
        if etf_code.startswith('51') or etf_code.startswith('50'):
            # 上海ETF
            ws_code = f"sh{etf_code}"
        elif etf_code.startswith('15') or etf_code.startswith('16'):
            # 深圳ETF
            ws_code = f"sz{etf_code}"
        else:
            print(f"  无法识别的ETF代码: {etf_code}")
            return None
        
        # 调用westock-data kline
        result = subprocess.run(
            ['npx', 'westock-data', 'kline', ws_code, '--limit', '1000'],
            capture_output=True, text=True, cwd=r'C:\Users\blakehao\.qclaw\workspace\skills\westock-data'
        )
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            if len(lines) < 2:
                return None
            
            # 解析CSV数据
            from io import StringIO
            df = pd.read_csv(StringIO(result.stdout))
            
            # 标准化列名
            df.columns = [c.strip() for c in df.columns]
            df = df.rename(columns={
                '日期': 'date', '开盘': 'open', '收盘': 'close', 
                '最高': 'high', '最低': 'low', '成交量': 'volume'
            })
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df = df.set_index('date')
            
            # 确保列存在
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    df[col] = df.get('close', 0)
            
            return df
        else:
            print(f"  westock获取失败: {result.stderr}")
            return None
    except Exception as e:
        print(f"  获取失败: {e}")
        return None


def load_etf_data(etf_code):
    """加载ETF数据，本地没有则用westock拉取"""
    # 本地路径
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    
    if os.path.exists(csv_path):
        print(f"加载本地数据: {etf_code}")
        df = pd.read_csv(csv_path, parse_dates=['Date'], index_col='Date')
        return df
    else:
        # 用westock拉取
        df = fetch_etf_data_with_westock(etf_code)
        if df is not None:
            # 保存到本地
            os.makedirs(DATA_DIR, exist_ok=True)
            df.to_csv(csv_path)
            print(f"  已保存到: {csv_path}")
            return df
        else:
            print(f"  ✗ {etf_code} 数据获取失败")
            return None


def run_backtest():
    """运行回测"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    # 添加策略
    cerebro.addstrategy(QixingLaplaceGaussian)
    
    # 加载数据
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
        print("有效ETF数据不足，回测终止")
        return
    
    print(f"成功加载 {loaded} 只ETF数据")
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("\n开始回测...")
    results = cerebro.run()
    strat = results[0]
    
    # 输出结果
    print("\n" + "="*60)
    print("回测结果")
    print("="*60)
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    
    print(f"初始资金: ${INITIAL_CASH:,.2f}")
    print(f"最终资产: ${final_value:,.2f}")
    print(f"总收益率: {total_return:+.2f}%")
    
    # 年化收益
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns:
        ann_return = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
        print(f"年化收益率: {ann_return*100:.2f}%")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if sharpe and 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"最大回撤: {dd['max']*100:.2f}%")
    
    # 交易统计
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total_trades = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        win_rate = won / total_trades * 100 if total_trades > 0 else 0
        
        # 盈亏比
        if lost > 0 and 'average' in trades.get('lost', {}).get('pnl', {}):
            avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0)
            avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0)
            pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        else:
            pl_ratio = 0
            avg_win = avg_loss = 0
        
        print(f"\n交易统计:")
        print(f"  总交易: {total_trades}")
        print(f"  盈利: {won}  亏损: {lost}")
        print(f"  胜率: {win_rate:.1f}%")
        print(f"  盈亏比: {pl_ratio:.2f}")
        print(f"  平均盈利: ${avg_win:.2f}")
        print(f"  平均亏损: ${avg_loss:.2f}")
    
    print("="*60)


if __name__ == '__main__':
    import sys
    run_backtest()
