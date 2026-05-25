#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星拉普拉斯高斯策略 - Backtrader版本
使用本地ETF历史数据回测（2019-2024，6年）
直接运行，自动拉取缺失数据（如果可能）
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
COMMISSION = 0.001  # 0.1%佣金
ETF_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'

# 37只A股ETF（与原始策略相同）
ETF_LIST = [
    '510300', '510050', '510500', '159915', '512100', '159922', '515000', '512880',
    '512690', '515790', '512480', '159949', '512660', '512760', '159928', '515030',
    '512800', '512200', '512010', '159766', '159825', '159766', '512700', '515250',
    '159870', '159766', '512980', '159996', '515790', '159766', '511880', '511990',
    '511010', '511060', '511260', '511030', '511160'
]

# 防御ETF（货币/债券）
DEFENSIVE_ETFs = ['511880', '511990', '511010', '511060', '511260', '511030', '511160']

# 拉普拉斯策略参数
LAPLACE_PARAMS = {
    'lookback_days': 25,
    'holdings_num': 1,  # 只持有一只ETF（Top1）
    'enable_profit_protection': True,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
    'enable_range_bound': True,
    'ma_period': 20,
    'bias_threshold': 0.10,
    'enable_defensive_switch': True,  # 防御切换
}


# ===========================================================
# 工具函数
# ===========================================================

def load_etf_data(code, data_dir=ETF_DIR):
    """加载ETF数据"""
    # 尝试不同格式
    possible_names = [
        f'{code}.csv',
        f'sh{code}.csv',
        f'sz{code}.csv',
    ]
    
    for name in possible_names:
        csv_path = os.path.join(data_dir, name)
        if os.path.exists(csv_path):
            break
    else:
        return None
    
    try:
        df = pd.read_csv(csv_path)
        
        # 处理列名
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
        elif 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
        
        df = df.sort_index()
        
        # 标准化列名
        df = df.rename(columns={
            'Open': 'open', 'Close': 'close', 'High': 'high',
            'Low': 'low', 'Volume': 'volume'
        })
        
        # 只保留需要的列
        needed_cols = ['open', 'high', 'low', 'close', 'volume']
        df = df[[c for c in needed_cols if c in df.columns]]
        
        return df
    except Exception as e:
        print(f"  加载 {code} 失败: {e}")
        return None


# ===========================================================
# 策略：七星拉普拉斯高斯
# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """七星拉普拉斯高斯策略"""
    
    params = (
        ('lookback_days', 25),
        ('holdings_num', 1),
        ('enable_profit_protection', True),
        ('profit_protection_lookback', 1),
        ('profit_protection_threshold', 0.05),
        ('enable_range_bound', True),
        ('ma_period', 20),
        ('bias_threshold', 0.10),
        ('enable_defensive_switch', True),
    )
    
    def __init__(self):
        self.stock_datas = {}
        self.current_filter = '正常期'
        self.range_bound_start = None
        
        for d in self.datas:
            self.stock_datas[d._name] = d
        
        # 计算防御ETF列表（排除自己）
        self.defensive_list = [
            f'sh{code}' if not code.startswith('sh') else code
            for code in DEFENSIVE_ETFs
            if f'sh{code}' in self.stock_datas or code in self.stock_datas
        ]
        
        if not self.defensive_list:
            print("警告：未找到防御ETF，将不使用防御切换")
        
    def next(self):
        dt = self.datas[0].datetime.date(0)
        
        # 检查震荡期（用第一个股票作为基准）
        if self.p.enable_range_bound and len(self.datas[0]) > self.p.ma_period:
            self._check_range_bound()
        
        # 计算所有ETF得分
        scores = self._calculate_scores()
        
        if not scores:
            return
        
        # 确定目标持仓
        if self.current_filter == '震荡期' and self.p.enable_defensive_switch and self.defensive_list:
            # 震荡期：切换到防御ETF
            targets = self.defensive_list[:self.p.holdings_num]
            if self.defensive_list:
                targets = [self.defensive_list[0]]  # 只持有一只防御ETF
        else:
            # 正常期：持有Top N
            targets = [s[0] for s in scores[:self.p.holdings_num]]
        
        if not targets:
            return
        
        # 卖出不在目标的持仓
        for name, d in self.stock_datas.items():
            pos = self.getposition(d).size
            if pos > 0 and name not in targets:
                self.close(d)
                print(f"[{dt}] 卖出 {name} @ {d.close[0]:.3f}")
        
        # 买入目标
        target_val = self.broker.getvalue() / len(targets)
        for name in targets:
            d = self.stock_datas.get(name)
            if d is None:
                continue
            
            pos = self.getposition(d).size
            cur_val = pos * d.close[0]
            
            if abs(cur_val - target_val) > target_val * 0.05 or pos == 0:
                size = int(target_val / d.close[0] / 100) * 100
                if size > 0 and size != pos:
                    self.order_target_size(d, size)
                    print(f"[{dt}] 买入 {name} @ {d.close[0]:.3f}, size={size}")
    
    def _calculate_scores(self):
        """计算所有ETF得分（拉普拉斯/高斯滤波）"""
        scores = []
        
        for name, d in self.stock_datas.items():
            if len(d) < self.p.lookback_days + 5:
                continue
            
            # 获取历史数据
            lookback = min(self.p.lookback_days + 20, len(d))
            closes = [d.close[i] for i in range(-lookback, 0)]
            
            if len(closes) < self.p.lookback_days:
                continue
            
            # 盈利保护
            if self.p.enable_profit_protection:
                recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                if closes[-1] < recent_high * (1 - self.p.profit_protection_threshold):
                    continue
            
            # 根据滤波器选择计算方式
            if self.current_filter == '正常期':
                # 拉普拉斯滤波器（趋势期）
                score = self._laplace_filter(closes[-(self.p.lookback_days + 1):])
            else:
                # 高斯滤波器（震荡期）
                score = self._gaussian_filter(closes[-(self.p.lookback_days + 1):])
            
            if score > 0:
                scores.append((name, score, closes[-1]))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores
    
    def _laplace_filter(self, prices):
        """拉普拉斯滤波器（趋势期）"""
        s = 0.05  # 平滑参数
        alpha = 1 - math.exp(-s)
        
        filtered = [prices[0]]
        for i in range(1, len(prices)):
            filtered.append(alpha * prices[i] + (1 - alpha) * filtered[-1])
        
        # 计算动量得分
        y = np.log(filtered)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        ann_return = math.exp(slope * 250) - 1
        
        # R²
        y_mean = np.mean(y)
        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - y_mean) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
        
        return ann_return * r_squared
    
    def _gaussian_filter(self, prices):
        """高斯滤波器（震荡期）"""
        sigma = 1.2
        n = len(prices)
        
        # 高斯权重
        x = np.arange(n)
        center = (n - 1) / 2
        weights = np.exp(-0.5 * ((x - center) / sigma) ** 2)
        weights = weights / np.sum(weights)
        
        filtered = np.sum(np.array(prices) * weights)
        
        # 用滤波后的值计算短期动量
        short_prices = prices[-5:]
        y = np.log(short_prices)
        x = np.arange(len(y))
        slope, _ = np.polyfit(x, y, 1)
        ann_return = math.exp(slope * 250) - 1
        
        return max(0, ann_return)  # 震荡期只做多
    
    def _check_range_bound(self):
        """检查震荡期（乖离率）"""
        d = self.datas[0]  # 用第一个股票作为基准
        
        lookback = min(self.p.ma_period + 5, len(d))
        closes = [d.close[i] for i in range(-lookback, 0)]
        
        if len(closes) < self.p.ma_period:
            return
        
        close_arr = np.array(closes)
        current_price = close_arr[-1]
        ma = np.mean(close_arr[-self.p.ma_period:])
        
        bias = (current_price - ma) / ma if ma > 0 else 0
        
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


# ===========================================================
# 主函数
# ===========================================================

def run_laplace_backtest():
    """运行拉普拉斯策略回测"""
    
    print("\n" + "="*70)
    print("七星拉普拉斯高斯策略 - Backtrader回测")
    print("="*70)
    
    # 加载数据
    print("\n正在加载ETF数据...")
    data_dict = {}
    failed = []
    
    for code in ETF_LIST:
        df = load_etf_data(code)
        if df is not None and len(df) > 100:
            # 添加到Backtrader
            data_name = f'sh{code}'
            data = bt.feeds.PandasData(
                dataname=df,
                name=data_name,
                fromdate=datetime(2019, 1, 1),
                todate=datetime(2024, 12, 31)
            )
            data_dict[data_name] = data
            print(f"  ✓ {code} ({len(df)}条)")
        else:
            failed.append(code)
    
    if failed:
        print(f"\n  未加载: {', '.join(failed[:5])}...")
    
    if len(data_dict) < 5:
        print(f"\n✗ 数据不足（仅{len(data_dict)}只）")
        return
    
    print(f"\n✓ 成功加载 {len(data_dict)} 只ETF数据\n")
    
    # 创建Cerebro
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addstrategy(QixingLaplaceGaussian, **LAPLACE_PARAMS)
    
    for name, data in data_dict.items():
        cerebro.adddata(data)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn')
    
    results = cerebro.run()
    strat = results[0]
    
    # 输出结果
    print("\n" + "="*70)
    print("回测结果")
    print("="*70)
    
    final_value = cerebro.broker.getvalue()
    print(f"\n初始资金:    ${INITIAL_CASH:,.2f}")
    print(f"最终资产:    ${final_value:,.2f}")
    total_return = (final_value / INITIAL_CASH - 1) * 100
    print(f"总收益率:    {total_return:+.2f}%")
    
    # 年化收益
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns:
        ann_return = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
        print(f"年化收益率:  {ann_return*100:.2f}%")
    
    # 夏普比率
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
        wr = won / total * 100 if total > 0 else 0
        print(f"\n交易次数:    {total}")
        print(f"盈利次数:    {won}")
        print(f"亏损次数:    {lost}")
        print(f"胜率:        {wr:.1f}%")
        
        if 'won' in trades and 'lost' in trades:
            avg_win = trades['won'].get('pnl', {}).get('average', 0)
            avg_loss = trades['lost'].get('pnl', {}).get('average', 0)
            if avg_loss != 0:
                pl_ratio = abs(avg_win / avg_loss)
                print(f"平均盈利:    ${avg_win:,.2f}")
                print(f"平均亏损:    ${avg_loss:,.2f}")
                print(f"盈亏比:      {pl_ratio:.2f}")
    
    print("\n" + "="*70)
    print("策略参数:")
    print(f"  持仓数量: {LAPLACE_PARAMS['holdings_num']}")
    print(f"  回看天数: {LAPLACE_PARAMS['lookback_days']}")
    print(f"  盈利保护: {'开启' if LAPLACE_PARAMS['enable_profit_protection'] else '关闭'}")
    print(f"  震荡期检测: {'开启' if LAPLACE_PARAMS['enable_range_bound'] else '关闭'}")
    print(f"  防御切换: {'开启' if LAPLACE_PARAMS['enable_defensive_switch'] else '关闭'}")
    print("="*70 + "\n")


if __name__ == '__main__':
    run_laplace_backtest()
