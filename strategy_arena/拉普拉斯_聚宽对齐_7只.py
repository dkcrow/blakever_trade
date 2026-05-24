#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉普拉斯高斯策略 - 聚宽原版对齐（7只ETF，2016-2026）
严格按照聚宽原版七星1.7.2的参数和ETF池
数据目录：back_trader_stocks\etf\
"""

import backtrader as bt
import numpy as np
import pandas as pd
from datetime import datetime
import os

# ===========================================================
# 聚宽原版7只ETF（严格对齐）
# ===========================================================
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'

# 聚宽原版7只ETF
ETF_POOL_7 = [
    '159915',  # 创业板ETF（核心！2023-2026大牛市）
    '513100',  # 纳指ETF（核心！美股科技牛市）
    '159985',  # 豆粕ETF
    '518880',  # 黄金ETF
    '501018',  # 南方原油
    '161226',  # 白银LOF
    '511220',  # 城投债ETF（防御）
]

# 聚宽原版参数
LOOKBACK_DAYS = 25
HOLDINGS_NUM = 1
DEFENSIVE_ETF = '511220'

# 盈利保护
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1
PROFIT_PROTECTION_THRESHOLD = 0.05

# 近3日跌幅过滤
LOSS_THRESHOLD = 0.97

# 震荡期参数
ENABLE_RANGE_BOUND_MODE = True
RISK_BENCHMARK = '510300'
LAPLACE_S_PARAM = 0.05
GAUSSIAN_SIGMA = 1.2

# 滤波器排除
FILTER_EXCLUDE = {DEFENSIVE_ETF}


# ===========================================================
# 策略类
# ===========================================================
class LaplaceGaussianStrategy_7ETF(bt.Strategy):
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('holdings_num', HOLDINGS_NUM),
        ('defensive_etf', DEFENSIVE_ETF),
        ('enable_profit_protection', ENABLE_PROFIT_PROTECTION),
        ('profit_protection_lookback', PROFIT_PROTECTION_LOOKBACK),
        ('profit_protection_threshold', PROFIT_PROTECTION_THRESHOLD),
    )
    
    def __init__(self):
        self.etf_datas = {}
        self.benchmark_data = None
        self.current_filter = '正常期'
        
        for d in self.datas:
            if d._name in ETF_POOL_7:
                self.etf_datas[d._name] = d
            if d._name == RISK_BENCHMARK:
                self.benchmark_data = d
        
        print(f"加载ETF: {list(self.etf_datas.keys())}")
    
    def next(self):
        # 检查震荡期
        if ENABLE_RANGE_BOUND_MODE:
            self.check_range_bound_mode()
        
        # 计算得分
        rankings = self.calculate_all_rankings()
        if not rankings:
            self._buy_defensive()
            return
        
        # 执行交易
        self.execute_trades(rankings)
    
    def check_range_bound_mode(self):
        """检查震荡期切换（简化版）"""
        if not self.benchmark_data or len(self.benchmark_data) < 20:
            return
        
        closes = [self.benchmark_data.close[i] for i in range(-20, 0) if len(self.benchmark_data) + i >= 0]
        if len(closes) < 20:
            return
        
        current_price = closes[-1]
        ma20 = sum(closes) / len(closes)
        bias = (current_price - ma20) / ma20 if ma20 > 0 else 0
        
        if bias > 0.10 and self.current_filter == '正常期':
            self.current_filter = '震荡期'
        elif bias < 0.05 and self.current_filter == '震荡期':
            self.current_filter = '正常期'
    
    def calculate_all_rankings(self):
        """计算所有ETF得分"""
        metrics = []
        for etf in ETF_POOL_7:
            if etf not in self.etf_datas:
                continue
            
            m = self.calculate_momentum(etf)
            if m:
                metrics.append(m)
        
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def calculate_momentum(self, etf):
        """计算动量得分"""
        data = self.etf_datas.get(etf)
        if not data:
            return None
        
        try:
            lookback = self.p.lookback_days + 20
            closes = [data.close[i] for i in range(-lookback, 0) if len(data) + i >= 0]
            
            if len(closes) < self.p.lookback_days:
                return None
            
            # 盈利保护检查
            if self.p.enable_profit_protection and etf in self.etf_datas:
                pos = self.getposition(self.etf_datas[etf])
                if pos.size > 0:
                    cost = pos.price
                    recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                    if data.close[0] < recent_high * (1 - self.p.profit_protection_threshold):
                        return None
            
            # 近3日跌幅过滤
            if len(closes) >= 4:
                day1 = closes[-1] / closes[-2] if closes[-2] > 0 else 1
                day2 = closes[-2] / closes[-3] if closes[-3] > 0 else 1
                day3 = closes[-3] / closes[-4] if closes[-4] > 0 else 1
                if min(day1, day2, day3) < LOSS_THRESHOLD:
                    return None
            
            # 长期动量（对数回归）
            recent = closes[-(self.p.lookback_days + 1):]
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, _ = np.polyfit(x, y, 1, w=weights)
            annualized_returns = np.exp(slope * 250) - 1
            
            # R²
            ss_res = np.sum(weights * (y - (slope * x + np.mean(y))) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            score = annualized_returns * r_squared
            
            return {
                'etf': etf,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'score': score,
                'current_price': closes[-1],
            }
        except Exception as e:
            return None
    
    def execute_trades(self, rankings):
        """执行交易（持仓Top1）"""
        current_pos = None
        for etf in self.etf_datas:
            pos = self.getposition(self.etf_datas[etf])
            if pos.size > 0:
                current_pos = etf
                break
        
        if not rankings:
            if current_pos and current_pos != self.p.defensive_etf:
                self.close(self.etf_datas[current_pos])
            self._buy_defensive()
            return
        
        target = rankings[0]['etf']
        
        if current_pos == target:
            return  # 已持有Top1
        
        if current_pos:
            self.close(self.etf_datas[current_pos])
        
        if target in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[target].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[target], size=size)
    
    def _buy_defensive(self):
        """买入防御ETF"""
        if self.p.defensive_etf in self.etf_datas:
            cash = self.broker.getcash()
            price = self.etf_datas[self.p.defensive_etf].close[0]
            size = int(cash / price)
            if size > 0:
                self.buy(self.etf_datas[self.p.defensive_etf], size=size)


# ===========================================================
# 回测主函数（10年完整数据）
# ===========================================================
def run_backtest_10y():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(LaplaceGaussianStrategy_7ETF)
    
    # 加载7只ETF数据（2016-2026）
    loaded = 0
    for etf in ETF_POOL_7:
        csv_path = os.path.join(DATA_DIR, f"{etf}.csv")
        if not os.path.exists(csv_path):
            print(f"缺失: {etf}.csv")
            continue
        
        try:
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            if df.empty or len(df) < 100:
                continue
            
            # 确保列名小写
            df.columns = [c.lower() for c in df.columns]
            required = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required):
                continue
            
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
                fromdate=datetime(2016, 1, 1),
                todate=datetime(2026, 4, 30)
            )
            cerebro.adddata(data)
            loaded += 1
            print(f"OK: {etf} ({len(df)}天, {df.index[0].date()} ~ {df.index[-1].date()})")
        except Exception as e:
            print(f"失败: {etf} - {e}")
    
    if loaded < 2:
        print("有效ETF不足，终止")
        return
    
    print(f"\n成功加载 {loaded} 只ETF")
    
    # 设置资金
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0001)
    
    # 分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("="*80)
    print("回测: 拉普拉斯高斯策略（聚宽原版7只ETF，2016-2026）")
    print("="*80)
    print(f"时间范围: 2016-01-01 ~ 2026-04-30 (10年+)")
    print(f"ETF池: {ETF_POOL_7}")
    print(f"持仓: Top1（1只）")
    print("="*80)
    
    strat = cerebro.run()[0]
    
    # 输出结果
    print("\n" + "="*80)
    print("回测结果（聚宽原版对齐）")
    print("="*80)
    print(f"初始资金: ¥100,000.00")
    print(f"最终资产: ¥{cerebro.broker.getvalue():.2f}")
    print(f"总收益率: {(cerebro.broker.getvalue()/100000-1)*100:.2f}%")
    
    # 年化收益（正确计算）
    days = (datetime(2026, 4, 30) - datetime(2016, 1, 1)).days
    ann_return = ((cerebro.broker.getvalue() / 100000) ** (365 / days) - 1) * 100
    print(f"年化收益率: {ann_return:.2f}%")
    print(f"聚宽原版参考: 20%+ （差距: {ann_return-20:.2f}%）")
    
    # 夏普
    sharpe = strat.analyzers.sharpe.get_analysis()
    if sharpe and 'sharperatio' in sharpe:
        print(f"夏普比率: {sharpe['sharperatio']:.2f}")
    
    # 最大回撤
    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"最大回撤: {dd['max']*100:.2f}%")
    
    # 交易统计
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        win_rate = won / total * 100 if total > 0 else 0
        
        avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0)
        avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0)
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        print(f"\n交易统计:")
        print(f"  总交易: {total}")
        print(f"  胜率: {win_rate:.1f}% (聚宽: 68%)")
        print(f"  盈亏比: {pl_ratio:.2f} (聚宽: 9.3)")
        print(f"  平均盈利: ¥{avg_win:.2f}")
        print(f"  平均亏损: ¥{avg_loss:.2f}")
    
    print("="*80)


if __name__ == '__main__':
    run_backtest_10y()
