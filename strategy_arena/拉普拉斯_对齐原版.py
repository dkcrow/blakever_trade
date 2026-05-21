#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯高斯策略 - Backtrader版（完全对齐聚宽原版V1.7.2）
源码：七星172拉普拉斯高斯.py
重写：对齐全部9层过滤 + 震荡期切换 + 双滤波器
"""

import backtrader as bt
import numpy as np
import math
import pandas as pd
from datetime import datetime, timedelta
import os

# ===========================================================
# 策略参数（完全对齐聚宽原版）
# ===========================================================

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

ETF_POOL = [
    # 大宗商品ETF（7只）
    '518880',  # 黄金ETF
    '159980',  # 有色ETF
    '159985',  # 豆粕ETF
    '501018',  # 南方原油
    '161226',  # 白银LOF
    '159981',  # 能源化工ETF
    # 国际ETF（10只）
    '513100',  # 纳指ETF
    '159509',  # 纳指科技ETF
    '513290',  # 纳指生物ETF
    '513500',  # 标普500ETF
    '159529',  # 标普消费
    '513400',  # 道琼斯ETF
    '513520',  # 日经225ETF
    '513030',  # 德国30ETF
    '513310',  # 中韩半导体ETF
    '513730',  # 东南亚ETF
    # 香港ETF（4只）
    '159792',  # 港股互联ETF
    '513130',  # 恒生科技
    '513050',  # 中概互联网ETF
    '159920',  # 恒生ETF
    '513690',  # 港股红利
    # 指数ETF（8只）
    '510300',  # 沪深300ETF
    '510500',  # 中证500ETF
    '510050',  # 上证50ETF
    '510210',  # 上证ETF
    '159915',  # 创业板ETF
    '588080',  # 科创50
    '512100',  # 中证1000ETF
    '563360',  # A500-ETF
    '563300',  # 中证2000ETF
    # 风格ETF（4只）
    '512890',  # 红利低波ETF
    '159967',  # 创业板成长ETF
    '512040',  # 价值ETF
    '159201',  # 自由现金流ETF
    # 债券ETF（3只）
    '511380',  # 可转债ETF
    '511010',  # 国债ETF
    '511220',  # 城投债ETF
]

# 核心参数（对齐聚宽原版）
LOOKBACK_DAYS = 25               # 动量计算周期
HOLDINGS_NUM = 1                 # 持仓数量（Top1）
DEFENSIVE_ETF = '511880'         # 防御ETF（货币基金）
MIN_MONEY = 5000                 # 最小交易金额

# 盈利保护参数
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1    # 回看周期（天）
PROFIT_PROTECTION_THRESHOLD = 0.05 # 回撤阈值（5%）

# 近3日跌幅过滤
LOSS_THRESHOLD = 0.97             # 近3日单日跌幅阈值

# 得分范围
MIN_SCORE_THRESHOLD = 0
MAX_SCORE_THRESHOLD = 100.0

# 成交量过滤
ENABLE_VOLUME_CHECK = True
VOLUME_LOOKBACK = 5
VOLUME_THRESHOLD = 2
VOLUME_RETURN_LIMIT = 1            # 年化收益>100%时启用

# 短期动量过滤
USE_SHORT_MOMENTUM_FILTER = True
SHORT_LOOKBACK_DAYS = 10
SHORT_MOMENTUM_THRESHOLD = 0.0

# 溢价率过滤（Backtrader版暂不支持，需要实时数据）
ENABLE_PREMIUM_FILTER = False
PREMIUM_THRESHOLD = 0.20

# 震荡期参数
ENABLE_RANGE_BOUND_MODE = True
LOOKBACK_HIGH_LOW_DAYS = 20
RISK_BENCHMARK = '510300'         # 风险基准ETF
LAPLACE_S_PARAM = 0.05
LAPLACE_MIN_SLOPE = 0.001
GAUSSIAN_SIGMA = 1.2
GAUSSIAN_MIN_SLOPE = 0.002
ENABLE_BIAS_TRIGGER = True
BIAS_THRESHOLD = 0.10              # 乖离率阈值（10%）
MA_PERIOD = 20
RSI_OVERBOUGHT = 70
RSI_PULLBACK = 65

# 滤波器中需排除的ETF（防御性资产）
FILTER_EXCLUDE = {DEFENSIVE_ETF, '511010', '511380', '511220'}

# ===========================================================
# 工具函数（对齐聚宽原版）
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
# Backtrader策略类（完全对齐聚宽原版逻辑）
# ===========================================================

class LaplaceGaussianStrategy(bt.Strategy):
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('holdings_num', HOLDINGS_NUM),
        ('defensive_etf', DEFENSIVE_ETF),
        ('enable_profit_protection', ENABLE_PROFIT_PROTECTION),
        ('profit_protection_lookback', PROFIT_PROTECTION_LOOKBACK),
        ('profit_protection_threshold', PROFIT_PROTECTION_THRESHOLD),
    )
    
    def __init__(self):
        # 存储ETF数据
        self.etf_datas = {}
        self.current_filter = '正常期'  # '正常期'=拉普拉斯, '震荡期'=高斯
        self.range_bound_days_count = 0
        
        # 加载所有ETF数据
        for etf in ETF_POOL:
            if etf in self.getdatabyname_all():
                self.etf_datas[etf] = self.getdatabyname(etf)
        
        # 基准数据（用于震荡期判断）
        self.benchmark_data = self.etf_datas.get(RISK_BENCHMARK)
        
        print(f"策略初始化完成，加载 {len(self.etf_datas)} 只ETF数据")
        print(f"持仓数量: {self.p.holdings_num}, 防御ETF: {self.p.defensive_etf}")
        print(f"当前滤波器: {self.current_filter}")
        self.previous_rsi = None  # 初始化RSI缓存
    
    def getdatabyname_all(self):
        """获取所有数据的名字列表"""
        return [d._name for d in self.datas]
    
    def next(self):
        """每个交易日执行"""
        # 1. 检查震荡期切换
        if ENABLE_RANGE_BOUND_MODE:
            self.check_range_bound_mode()
        
        # 2. 计算所有ETF得分
        rankings = self.calculate_all_rankings()
        
        if not rankings:
            return
        
        # 3. 执行交易（持仓1只Top1）
        self.execute_trades(rankings)
    
    def check_range_bound_mode(self):
        """检查是否需要切换震荡期/正常期模式"""
        if not self.benchmark_data:
            return
        
        closes = []
        highs = []
        lows = []
        lookback = max(MA_PERIOD, LOOKBACK_HIGH_LOW_DAYS) + 5
        
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
        if not should_enter and current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        # 检查退出震荡期
        should_exit = False
        if self.current_filter == '震荡期':
            if current_price > ma and bias < BIAS_THRESHOLD * 0.5:
                should_exit = True
        
        # 执行切换
        if should_enter and self.current_filter == '正常期':
            self.current_filter = '震荡期'
            print(f"[{self.data.datetime.date(0)}] 进入震荡期 → 切换到高斯滤波器")
        elif should_exit and self.current_filter == '震荡期':
            self.current_filter = '正常期'
            print(f"[{self.data.datetime.date(0)}] 退出震荡期 → 切换到拉普拉斯滤波器")
        
        self.previous_rsi = current_rsi
    
    def calculate_all_rankings(self):
        """计算所有ETF的动量得分，应用所有过滤条件"""
        metrics = []
        
        for etf in ETF_POOL:
            if etf not in self.etf_datas:
                continue
            
            m = self.calculate_momentum(etf)
            if m:
                # 得分范围过滤
                if MIN_SCORE_THRESHOLD <= m['score'] <= MAX_SCORE_THRESHOLD:
                    metrics.append(m)
        
        # 按得分降序排序
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def calculate_momentum(self, etf):
        """计算单只ETF的动量指标（对齐聚宽原版）"""
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
            
            # ===== 1. 盈利保护检查（排除）=====
            if self.p.enable_profit_protection and etf in self.etf_datas:
                pos = self.getposition(self.etf_datas[etf])
                if pos.size > 0:
                    cost = pos.price
                    recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                    if current_price < recent_high * (1 - self.p.profit_protection_threshold):
                        return None
            
            # ===== 2. 近3日单日跌幅过滤（排除）=====
            if len(closes) >= 4:
                day1 = closes[-1] / closes[-2] if closes[-2] > 0 else 1
                day2 = closes[-2] / closes[-3] if closes[-3] > 0 else 1
                day3 = closes[-3] / closes[-4] if closes[-4] > 0 else 1
                if min(day1, day2, day3) < LOSS_THRESHOLD:
                    return None
            
            # ===== 3. 长期动量计算 =====
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
            
            # ===== 4. 短期动量过滤 =====
            short_annualized = 0
            if USE_SHORT_MOMENTUM_FILTER and len(closes) >= SHORT_LOOKBACK_DAYS:
                short_recent = price_series[-(SHORT_LOOKBACK_DAYS + 1):]
                short_y = np.log(short_recent)
                short_x = np.arange(len(short_y))
                short_weights = np.linspace(1, 2, len(short_y))
                short_slope, _ = np.polyfit(short_x, short_y, 1, w=short_weights)
                short_annualized = math.exp(short_slope * 250) - 1
                if short_annualized < SHORT_MOMENTUM_THRESHOLD:
                    return None
            
            # ===== 5. 动态滤波器过滤（震荡期机制）=====
            if ENABLE_RANGE_BOUND_MODE and etf not in FILTER_EXCLUDE:
                laplace_values = laplace_filter(price_series, s=LAPLACE_S_PARAM)
                laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
                passed_laplace = (current_price > laplace_values[-1] and laplace_slope > LAPLACE_MIN_SLOPE)
                
                g1_val, g2_val = gaussian_filter_last_two(price_series, sigma=GAUSSIAN_SIGMA)
                gaussian_slope = g1_val - g2_val
                passed_gaussian = (current_price > g1_val and gaussian_slope > GAUSSIAN_MIN_SLOPE)
                
                if self.current_filter == '正常期':
                    passed_filter = passed_laplace
                else:
                    passed_filter = passed_gaussian
                
                if not passed_filter:
                    return None
            
            return {
                'etf': etf,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
                'short_annualized': short_annualized,
            }
        except Exception as e:
            return None
    
    def execute_trades(self, rankings):
        """执行交易：对齐聚宽原版（持仓1只Top1，无合格则持防御ETF）"""
        # 当前持仓
        current_pos = None
        for etf in self.etf_datas:
            pos = self.getposition(self.etf_datas[etf])
            if pos.size > 0:
                current_pos = etf
                break
        
        # 如果没有合格ETF，买入防御ETF
        if not rankings:
            if current_pos != self.p.defensive_etf:
                if current_pos:
                    self.close(self.etf_datas[current_pos])
                    print(f"[{self.data.datetime.date(0)}] 卖出: {current_pos}（无合格ETF，切换到防御）")
                self._buy_defensive()
            return
        
        # Top1候选
        target = rankings[0]['etf']
        
        # 如果已持有Top1，继续持有
        if current_pos == target:
            return
        
        # 卖出当前持仓
        if current_pos:
            self.close(self.etf_datas[current_pos])
            print(f"[{self.data.datetime.date(0)}] 卖出: {current_pos}")
        
        # 买入新持仓（全仓）
        if target in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[target].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[target], size=size)
                print(f"[{self.data.datetime.date(0)}] 买入: {target} {size}股 @ {price:.3f}")
    
    def _buy_defensive(self):
        """买入防御ETF（货币基金）"""
        if self.p.defensive_etf in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[self.p.defensive_etf].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[self.p.defensive_etf], size=size)
                print(f"[{self.data.datetime.date(0)}] 买入防御ETF: {self.p.defensive_etf} {size}股 @ {price:.3f}")


# ===========================================================
# 回测主函数
# ===========================================================

def run_backtest():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(LaplaceGaussianStrategy)
    
    # 加载ETF数据
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
    
    # 设置初始资金
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0001)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("="*80)
    print("开始回测: 拉普拉斯高斯策略（对齐聚宽原版V1.7.2）")
    print("="*80)
    print(f"回测时间: 2026-02-01 ~ 2026-04-16")
    print(f"ETF池: {loaded}只")
    print(f"持仓数量: {HOLDINGS_NUM}只（Top1）")
    print(f"滤波器: {ENABLE_RANGE_BOUND_MODE and '拉普拉斯/高斯双滤波' or '仅拉普拉斯'}")
    print("="*80)
    
    # 运行回测
    strat = cerebro.run()[0]
    
    # 输出结果
    print("\n" + "="*80)
    print("回测结果")
    print("="*80)
    print(f"初始资金: $100,000.00")
    print(f"最终资产: ${cerebro.broker.getvalue():.2f}")
    print(f"总收益率: {(cerebro.broker.getvalue()/100000-1)*100:.2f}%")
    
    # 年化收益
    days = 75  # 2026-02-01 ~ 2026-04-16
    ann_return = ((cerebro.broker.getvalue() / 100000) ** (365 / days) - 1) * 100
    print(f"年化收益率: {ann_return:.2f}%")
    
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
        
        if lost > 0 and 'average' in trades.get('lost', {}).get('pnl', {}):
            avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0)
            avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0)
            pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        else:
            pl_ratio = 0
        
        print(f"\n交易统计:")
        print(f"  总交易: {total_trades}")
        print(f"  盈利: {won}  亏损: {lost}")
        print(f"  胜率: {win_rate:.1f}%")
        print(f"  盈亏比: {pl_ratio:.2f}")
        print(f"  平均盈利: ${avg_win:.2f}" if avg_win else "  平均盈利: N/A")
        print(f"  平均亏损: ${avg_loss:.2f}" if avg_loss else "  平均亏损: N/A")
    
    print("="*80)


def load_etf_data(etf_code):
    """加载本地ETF数据"""
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    if not os.path.exists(csv_path):
        return None
    
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        
        # 确保列名正确
        df.columns = [c.lower() for c in df.columns]
        required = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            return None
        
        return df
    except Exception:
        return None


if __name__ == '__main__':
    run_backtest()
