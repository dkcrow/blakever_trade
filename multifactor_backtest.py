# -*- coding: utf-8 -*-
"""
机构级多因子量化策略 - 本地回测版本
【策略名称】Alpha因子增强策略
【策略类型】多因子选股 + 行业中性 + 组合优化
【研究框架】因子挖掘 → 因子测试 → 因子合成 → 组合构建 → 风险控制
【目标收益】年化超额收益8-15%，信息比率>1.5
【回测周期】2018-01-01 至 2026-04-23
【调仓频率】月度调仓

基于聚宽平台v1.5策略，转换为本地baostock数据源回测
"""

import baostock as bs
import pandas as pd
import numpy as np
from scipy import stats
from functools import reduce
import warnings
import time
import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

warnings.filterwarnings('ignore')

# ============================================================================
# 全局配置
# ============================================================================
class Config:
    """策略配置"""
    START_DATE = '2018-01-01'
    END_DATE = '2026-04-23'
    INITIAL_CAPITAL = 1000000

    INDEX_POOL = 'sh.000905'  # 中证500
    MIN_MARKET_CAP = 20       # 亿（使用换手率等作为代理筛选）
    MAX_MARKET_CAP = 5000
    MIN_PRICE = 1
    MAX_STOCK_NUM = 50

    FACTOR_WEIGHTS = {
        'value': 0.20,
        'quality': 0.25,
        'growth': 0.15,
        'momentum': 0.15,
        'volatility': 0.15,
        'liquidity': 0.10
    }

    MAX_SINGLE_WEIGHT = 0.05
    STOP_LOSS_RATIO = 0.08
    MAX_TURNOVER = 0.50

    COMMISSION = 0.0003
    SLIPPAGE = 0.002
    STAMP_TAX = 0.001

g = Config()


# ============================================================================
# 数据获取模块 - 基于baostock
# ============================================================================
class DataService:
    """数据服务 - 封装baostock接口"""

    def __init__(self):
        bs.login()

    def __del__(self):
        try:
            bs.logout()
        except:
            pass

    def get_index_stocks(self, index_code='sh.000905'):
        """获取指数成分股"""
        # baostock指数代码: sh.000905(中证500), sh.000300(沪深300), sz.399006(创业板指)
        func_map = {
            'sh.000905': bs.query_zz500_stocks,
            'sh.000300': bs.query_hs300_stocks,
            'sz.399006': bs.query_sz50_stocks,  # 用上证50备选
        }

        func = func_map.get(index_code, bs.query_zz500_stocks)
        rs = func()
        stocks = []
        while (rs.error_code == '0') and rs.next():
            row = rs.get_row_data()
            stocks.append(row[1])  # code列

        return stocks

    def get_stock_daily(self, code, start_date, end_date, adjustflag='2'):
        """获取个股日K线（前复权）"""
        rs = bs.query_history_k_data_plus(
            code,
            'date,open,high,low,close,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM',
            start_date=start_date,
            end_date=end_date,
            frequency='d',
            adjustflag=adjustflag
        )
        data = []
        while (rs.error_code == '0') and rs.next():
            data.append(rs.get_row_data())

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=rs.fields)
        # 转换数值类型
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn',
                     'peTTM', 'pbMRQ', 'psTTM', 'pcfNcfTTM']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['date'] = pd.to_datetime(df['date'])
        return df

    def get_stock_monthly(self, code, start_date, end_date, adjustflag='2'):
        """获取个股月K线"""
        rs = bs.query_history_k_data_plus(
            code,
            'date,open,high,low,close,volume,amount',
            start_date=start_date,
            end_date=end_date,
            frequency='m',
            adjustflag=adjustflag
        )
        data = []
        while (rs.error_code == '0') and rs.next():
            data.append(rs.get_row_data())

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=rs.fields)
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df['date'] = pd.to_datetime(df['date'])
        return df

    def get_profit_data(self, code, year, quarter):
        """获取盈利能力数据"""
        rs = bs.query_profit_data(code=code, year=year, quarter=quarter)
        data = []
        while (rs.error_code == '0') and rs.next():
            data.append(rs.get_row_data())
        if not data:
            return None
        df = pd.DataFrame(data, columns=rs.fields)
        for col in df.columns:
            if col not in ['code', 'pubDate', 'statDate']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    def get_growth_data(self, code, year, quarter):
        """获取成长性数据"""
        rs = bs.query_growth_data(code=code, year=year, quarter=quarter)
        data = []
        while (rs.error_code == '0') and rs.next():
            data.append(rs.get_row_data())
        if not data:
            return None
        df = pd.DataFrame(data, columns=rs.fields)
        for col in df.columns:
            if col not in ['code', 'pubDate', 'statDate']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    def get_trade_days(self, start_date, end_date):
        """获取交易日列表"""
        rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)
        days = []
        while (rs.error_code == '0') and rs.next():
            row = rs.get_row_data()
            if row[1] == '1':  # is_trading_day
                days.append(row[0])
        return sorted(days)

    def get_all_stocks(self, date):
        """获取某日全部A股列表"""
        rs = bs.query_all_stock(day=date)
        data = []
        while (rs.error_code == '0') and rs.next():
            data.append(rs.get_row_data())
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=rs.fields)
        # 只保留沪深A股
        df = df[df['code'].str.match(r'(sh\.6|sz\.0|sz\.3)')]
        return df

    def get_stock_basic(self, code):
        """获取股票基本信息"""
        rs = bs.query_stock_basic(code=code)
        data = []
        while (rs.error_code == '0') and rs.next():
            data.append(rs.get_row_data())
        if not data:
            return None
        return data[0]


# ============================================================================
# 因子计算模块
# ============================================================================
class FactorCalculator:
    """因子计算器"""

    def __init__(self, data_service):
        self.ds = data_service
        # 缓存：避免重复请求
        self._price_cache = {}
        self._profit_cache = {}
        self._growth_cache = {}

    def _get_prices_batch(self, stock_list, end_date, count=250):
        """批量获取价格数据（带缓存）"""
        cache_key = (tuple(stock_list[:50]), end_date)
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        all_data = {}
        start = (pd.Timestamp(end_date) - timedelta(days=count * 2)).strftime('%Y-%m-%d')

        for code in stock_list:
            try:
                df = self.ds.get_stock_daily(code, start, end_date)
                if len(df) >= 40:
                    all_data[code] = df
                time.sleep(0.05)  # 限速
            except:
                continue

        self._price_cache[cache_key] = all_data
        return all_data

    def calc_value_factors(self, stock_list, date):
        """价值因子 - PE/PB/PS/PCF倒数"""
        if len(stock_list) == 0:
            return pd.DataFrame()

        results = []
        start = (pd.Timestamp(date) - timedelta(days=10)).strftime('%Y-%m-%d')

        for code in stock_list[:300]:
            try:
                df = self.ds.get_stock_daily(code, start, date)
                if df is None or len(df) == 0:
                    continue

                last_row = df.iloc[-1]
                pe = last_row.get('peTTM', np.nan)
                pb = last_row.get('pbMRQ', np.nan)
                ps = last_row.get('psTTM', np.nan)
                pcf = last_row.get('pcfNcfTTM', np.nan)

                # EP, BP, SP, CPFP
                ep = 1 / pe if pd.notna(pe) and pe > 0.1 else 0
                bp = 1 / pb if pd.notna(pb) and pb > 0.1 else 0
                sp = 1 / ps if pd.notna(ps) and ps > 0.1 else 0
                cp = 1 / pcf if pd.notna(pcf) and pcf > 0.1 else 0

                results.append({
                    'code': code,
                    'value_ep': ep,
                    'value_bp': bp,
                    'value_sp': sp,
                    'value_cp': cp
                })
            except:
                continue

        if len(results) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(results)

        df['value_score'] = (
            df['value_ep'].rank(pct=True).fillna(0.5) * 0.25 +
            df['value_bp'].rank(pct=True).fillna(0.5) * 0.25 +
            df['value_sp'].rank(pct=True).fillna(0.5) * 0.25 +
            df['value_cp'].rank(pct=True).fillna(0.5) * 0.25
        )

        return df[['code', 'value_score']]

    def calc_quality_factors(self, stock_list, date):
        """质量因子 - ROE/ROA"""
        if len(stock_list) == 0:
            return pd.DataFrame()

        date_ts = pd.Timestamp(date)
        # 确定财务数据年份和季度
        year = date_ts.year
        quarter = min((date_ts.month - 1) // 3 + 1, 4)
        # 使用上一期已公布的财报（滞后一个季度）
        if quarter == 1:
            fy = year - 1
            fq = 4
        else:
            fy = year
            fq = quarter - 1

        results = []
        for code in stock_list[:300]:
            try:
                cache_key = (code, fy, fq)
                if cache_key in self._profit_cache:
                    pdata = self._profit_cache[cache_key]
                else:
                    pdata = self.ds.get_profit_data(code, fy, fq)
                    self._profit_cache[cache_key] = pdata
                    time.sleep(0.05)

                if pdata is None or len(pdata) == 0:
                    continue

                row = pdata.iloc[0]
                roe = row.get('roeAvg', np.nan)
                np_margin = row.get('npMargin', np.nan)

                results.append({
                    'code': code,
                    'quality_roe': roe if pd.notna(roe) else 0,
                    'quality_np_margin': np_margin if pd.notna(np_margin) else 0
                })
            except:
                continue

        if len(results) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['quality_roe'] = df['quality_roe'].clip(-1, 1)
        df['quality_np_margin'] = df['quality_np_margin'].clip(-1, 1)

        df['quality_score'] = (
            df['quality_roe'].rank(pct=True).fillna(0.5) * 0.6 +
            df['quality_np_margin'].rank(pct=True).fillna(0.5) * 0.4
        )

        return df[['code', 'quality_score']]

    def calc_growth_factors(self, stock_list, date):
        """成长因子 - 营收/利润同比增长"""
        if len(stock_list) == 0:
            return pd.DataFrame()

        date_ts = pd.Timestamp(date)
        year = date_ts.year
        quarter = min((date_ts.month - 1) // 3 + 1, 4)
        if quarter == 1:
            fy = year - 1
            fq = 4
        else:
            fy = year
            fq = quarter - 1

        results = []
        for code in stock_list[:300]:
            try:
                cache_key = (code, fy, fq)
                if cache_key in self._growth_cache:
                    gdata = self._growth_cache[cache_key]
                else:
                    gdata = self.ds.get_growth_data(code, fy, fq)
                    self._growth_cache[cache_key] = gdata
                    time.sleep(0.05)

                if gdata is None or len(gdata) == 0:
                    continue

                row = gdata.iloc[0]
                yoy_asset = row.get('YOYAsset', np.nan)   # 总资产同比增长
                yoy_ni = row.get('YOYNI', np.nan)          # 净利润同比增长
                yoy_eps = row.get('YOYEPSBasic', np.nan)   # EPS同比增长

                results.append({
                    'code': code,
                    'growth_asset': yoy_asset if pd.notna(yoy_asset) else 0,
                    'growth_ni': yoy_ni if pd.notna(yoy_ni) else 0,
                    'growth_eps': yoy_eps if pd.notna(yoy_eps) else 0
                })
            except:
                continue

        if len(results) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['growth_asset'] = df['growth_asset'].clip(-2, 5)
        df['growth_ni'] = df['growth_ni'].clip(-5, 10)
        df['growth_eps'] = df['growth_eps'].clip(-5, 10)

        df['growth_score'] = (
            df['growth_asset'].rank(pct=True).fillna(0.5) * 0.3 +
            df['growth_ni'].rank(pct=True).fillna(0.5) * 0.4 +
            df['growth_eps'].rank(pct=True).fillna(0.5) * 0.3
        )

        return df[['code', 'growth_score']]

    def calc_momentum_factors(self, stock_list, date):
        """动量因子 - 12M/6M/3M动量 + 1M反转"""
        if len(stock_list) == 0:
            return pd.DataFrame()

        results = []
        start = (pd.Timestamp(date) - timedelta(days=400)).strftime('%Y-%m-%d')

        for code in stock_list[:300]:
            try:
                df = self.ds.get_stock_daily(code, start, date)
                if df is None or len(df) < 60:
                    continue

                close = df['close'].values
                n = len(close)

                mom_12m = close[-1] / close[-min(240, n)] - 1 if n >= 240 else np.nan
                mom_6m = close[-1] / close[-min(120, n)] - 1 if n >= 120 else np.nan
                mom_3m = close[-1] / close[-min(60, n)] - 1 if n >= 60 else np.nan
                rev_1m = close[-1] / close[-min(20, n)] - 1 if n >= 20 else np.nan

                results.append({
                    'code': code,
                    'momentum_12m': mom_12m,
                    'momentum_6m': mom_6m,
                    'momentum_3m': mom_3m,
                    'reversal_1m': rev_1m
                })
                time.sleep(0.03)
            except:
                continue

        if len(results) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(results)

        df['momentum_score'] = (
            df['momentum_12m'].rank(pct=True).fillna(0.5) * 0.3 +
            df['momentum_6m'].rank(pct=True).fillna(0.5) * 0.3 +
            df['momentum_3m'].rank(pct=True).fillna(0.5) * 0.2 +
            (1 - df['reversal_1m'].rank(pct=True).fillna(0.5)) * 0.2
        )

        return df[['code', 'momentum_score']]

    def calc_volatility_factors(self, stock_list, date):
        """波动因子 - 波动率/下行风险/Beta"""
        if len(stock_list) == 0:
            return pd.DataFrame()

        # 获取基准数据
        bench_df = self.ds.get_stock_daily('sh.000300',
                                           (pd.Timestamp(date) - timedelta(days=120)).strftime('%Y-%m-%d'),
                                           date)
        if bench_df is None or len(bench_df) < 40:
            return pd.DataFrame()

        bench_ret = bench_df['close'].pct_change().dropna().values[-60:]

        results = []
        start = (pd.Timestamp(date) - timedelta(days=120)).strftime('%Y-%m-%d')

        for code in stock_list[:200]:
            try:
                df = self.ds.get_stock_daily(code, start, date)
                if df is None or len(df) < 40:
                    continue

                ret = df['close'].pct_change().dropna().values[-60:]

                if len(ret) < 30:
                    continue

                vol = np.std(ret) * np.sqrt(252)

                neg_ret = ret[ret < 0]
                downside_vol = np.std(neg_ret) * np.sqrt(252) if len(neg_ret) > 5 else vol

                min_len = min(len(ret), len(bench_ret))
                if min_len > 10:
                    cov = np.cov(ret[:min_len], bench_ret[:min_len])[0, 1]
                    var = np.var(bench_ret[:min_len])
                    beta = cov / var if var > 0 else 1
                else:
                    beta = 1

                results.append({
                    'code': code,
                    'volatility': vol,
                    'downside_risk': downside_vol,
                    'beta': beta
                })
                time.sleep(0.03)
            except:
                continue

        if len(results) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(results)

        df['volatility_score'] = (
            (1 - df['volatility'].rank(pct=True).fillna(0.5)) * 0.4 +
            (1 - df['downside_risk'].rank(pct=True).fillna(0.5)) * 0.4 +
            (1 - df['beta'].rank(pct=True).fillna(0.5)) * 0.2
        )

        return df[['code', 'volatility_score']]

    def calc_liquidity_factors(self, stock_list, date):
        """流动性因子 - 换手率"""
        if len(stock_list) == 0:
            return pd.DataFrame()

        results = []
        start = (pd.Timestamp(date) - timedelta(days=30)).strftime('%Y-%m-%d')

        for code in stock_list[:300]:
            try:
                df = self.ds.get_stock_daily(code, start, date)
                if df is None or len(df) < 5:
                    continue

                avg_turn = df['turn'].mean()
                if pd.isna(avg_turn):
                    avg_turn = 0

                results.append({
                    'code': code,
                    'liquidity_turnover': avg_turn
                })
            except:
                continue

        if len(results) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(results)

        # 流动性适中最佳（太高说明投机，太低说明流动性差）
        turnover_rank = df['liquidity_turnover'].rank(pct=True)
        df['liquidity_score'] = 1 - abs(turnover_rank - 0.5) * 2
        df['liquidity_score'] = df['liquidity_score'].clip(0, 1)

        return df[['code', 'liquidity_score']]


# ============================================================================
# 因子处理模块
# ============================================================================
class FactorProcessor:
    """因子处理器"""

    @staticmethod
    def winsorize_mad(series, n_mad=3):
        """MAD法去极值"""
        median = series.median()
        mad = np.median(np.abs(series - median))
        if mad == 0:
            return series
        upper = median + n_mad * mad * 1.4826
        lower = median - n_mad * mad * 1.4826
        return series.clip(lower, upper)

    @staticmethod
    def standardize(series):
        """Z-Score标准化"""
        std = series.std()
        if std == 0 or pd.isna(std):
            return series - series.mean()
        return (series - series.mean()) / std

    @staticmethod
    def fill_na_with_median(df, factor_cols):
        """用中位数填充缺失值"""
        for col in factor_cols:
            if col in df.columns:
                median_val = df[col].median()
                if pd.isna(median_val):
                    median_val = 0.5
                df[col] = df[col].fillna(median_val)
        return df


# ============================================================================
# 因子合成模块
# ============================================================================
class FactorCombiner:
    """因子合成器"""

    @staticmethod
    def equal_weight(df, factor_cols, factor_weights):
        """加权合成"""
        cols = [col for col in factor_cols if col in df.columns]
        if len(cols) == 0:
            df['combined_factor'] = 0
            return df

        df['combined_factor'] = 0
        total_weight = 0
        for col in cols:
            category = col.replace('_score', '')
            weight = factor_weights.get(category, 1 / len(cols))
            df['combined_factor'] += df[col].fillna(0) * weight
            total_weight += weight

        if total_weight > 0:
            df['combined_factor'] = df['combined_factor'] / total_weight

        return df


# ============================================================================
# 组合优化模块
# ============================================================================
class PortfolioOptimizer:
    """组合优化器"""

    @staticmethod
    def optimize(df, max_stocks=50, max_single_weight=0.05):
        """组合优化 - 因子得分加权"""
        df = df.drop_duplicates(subset=['code'])
        df = df.sort_values('combined_factor', ascending=False)
        selected = df.head(max_stocks).copy()

        if len(selected) == 0:
            return pd.DataFrame(columns=['code', 'weight'])

        n = len(selected)
        score_min = selected['combined_factor'].min()
        score_max = selected['combined_factor'].max()

        if score_max > score_min:
            selected['weight'] = (selected['combined_factor'] - score_min) / (score_max - score_min) + 0.5
        else:
            selected['weight'] = 1.0

        selected['weight'] = selected['weight'].clip(upper=max_single_weight)

        weight_sum = selected['weight'].sum()
        if weight_sum > 0:
            selected['weight'] = selected['weight'] / weight_sum
        else:
            selected['weight'] = 1 / n

        return selected[['code', 'weight']]


# ============================================================================
# 风险控制模块
# ============================================================================
class RiskController:
    """风险控制器"""

    def __init__(self):
        self.position_cost = {}
        self.position_high = {}
        self.max_drawdown = 0
        self.peak_value = g.INITIAL_CAPITAL

    def check_stop_loss(self, stock, current_price):
        """个股止损检查"""
        cost = self.position_cost.get(stock, current_price)

        if stock not in self.position_high:
            self.position_high[stock] = current_price
        else:
            self.position_high[stock] = max(self.position_high[stock], current_price)

        if cost == 0:
            return False, None

        loss = (current_price - cost) / cost

        # 固定止损8%
        if loss <= -0.08:
            return True, 'fixed_stop'

        # 追踪止盈止损：盈利>5%后回撤5%
        if loss > 0.05:
            high = self.position_high[stock]
            if high > 0:
                drawdown = (high - current_price) / high
                if drawdown >= 0.05:
                    return True, 'trailing_stop'

        return False, None

    def check_portfolio_risk(self, total_value):
        """组合风险检查"""
        if total_value > self.peak_value:
            self.peak_value = total_value

        if self.peak_value > 0:
            drawdown = (self.peak_value - total_value) / self.peak_value
            self.max_drawdown = max(self.max_drawdown, drawdown)

            if drawdown > 0.15:
                return True, drawdown

        return False, 0


# ============================================================================
# 回测引擎
# ============================================================================
class BacktestEngine:
    """本地回测引擎"""

    def __init__(self):
        self.ds = DataService()
        self.factor_calc = FactorCalculator(self.ds)
        self.factor_proc = FactorProcessor()
        self.factor_comb = FactorCombiner()
        self.portfolio_opt = PortfolioOptimizer()
        self.risk_ctrl = RiskController()

        # 持仓与资金
        self.cash = g.INITIAL_CAPITAL
        self.positions = {}  # {code: {'shares': int, 'cost': float, 'value': float}}
        self.target_weights = {}

        # 记录
        self.daily_values = []
        self.trade_log = []
        self.rebalance_log = []

    def get_stock_pool(self, date):
        """获取股票池 - 从指数成分股中筛选"""
        stocks = []

        # 尝试多个指数
        index_codes = ['sh.000905', 'sh.000300']
        for idx_code in index_codes:
            try:
                stocks = self.ds.get_index_stocks(idx_code)
                if len(stocks) > 50:
                    break
            except:
                continue

        if len(stocks) < 10:
            print(f"  [WARN] 股票池过小: {len(stocks)}")
            return stocks

        # 基本筛选：获取当日价格数据，过滤ST、低价股、停牌
        valid_stocks = []
        check_date = date
        start = (pd.Timestamp(date) - timedelta(days=10)).strftime('%Y-%m-%d')

        for code in stocks:
            try:
                df = self.ds.get_stock_daily(code, start, check_date)
                if df is None or len(df) == 0:
                    continue

                last = df.iloc[-1]

                # 价格过滤
                price = last['close']
                if pd.isna(price) or price < g.MIN_PRICE:
                    continue

                # 成交量过滤（停牌）
                vol = last.get('volume', 0)
                if pd.isna(vol) or vol <= 0:
                    continue

                valid_stocks.append(code)
            except:
                continue

        print(f"  股票池筛选: {len(stocks)} -> {len(valid_stocks)}")
        return valid_stocks[:300]  # 限制数量避免数据请求过多

    def calc_all_factors(self, stock_list, date):
        """计算所有因子"""
        if len(stock_list) > 300:
            stock_list = stock_list[:300]

        print(f"  计算因子中... (共{len(stock_list)}只)")

        t0 = time.time()
        value_df = self.factor_calc.calc_value_factors(stock_list, date)
        print(f"    价值因子: {len(value_df)}只, {time.time()-t0:.1f}s")

        t0 = time.time()
        quality_df = self.factor_calc.calc_quality_factors(stock_list, date)
        print(f"    质量因子: {len(quality_df)}只, {time.time()-t0:.1f}s")

        t0 = time.time()
        growth_df = self.factor_calc.calc_growth_factors(stock_list, date)
        print(f"    成长因子: {len(growth_df)}只, {time.time()-t0:.1f}s")

        t0 = time.time()
        momentum_df = self.factor_calc.calc_momentum_factors(stock_list, date)
        print(f"    动量因子: {len(momentum_df)}只, {time.time()-t0:.1f}s")

        t0 = time.time()
        volatility_df = self.factor_calc.calc_volatility_factors(stock_list, date)
        print(f"    波动因子: {len(volatility_df)}只, {time.time()-t0:.1f}s")

        t0 = time.time()
        liquidity_df = self.factor_calc.calc_liquidity_factors(stock_list, date)
        print(f"    流动性因子: {len(liquidity_df)}只, {time.time()-t0:.1f}s")

        dfs = [value_df, quality_df, growth_df, momentum_df, volatility_df, liquidity_df]
        dfs = [df for df in dfs if len(df) > 0]

        if len(dfs) == 0:
            return pd.DataFrame()

        merged_df = reduce(lambda x, y: pd.merge(x, y, on='code', how='outer'), dfs)
        print(f"    因子合并: {len(merged_df)}只")

        return merged_df

    def process_factors(self, df):
        """因子处理"""
        factor_cols = [col for col in df.columns if col.endswith('_score')]
        if len(factor_cols) == 0:
            return df

        df = self.factor_proc.fill_na_with_median(df, factor_cols)
        for col in factor_cols:
            df[col] = self.factor_proc.winsorize_mad(df[col])
            df[col] = self.factor_proc.standardize(df[col])

        return df

    def combine_factors(self, df):
        """因子合成"""
        factor_cols = [col for col in df.columns if col.endswith('_score')]
        if len(factor_cols) == 0:
            df['combined_factor'] = 0
            return df
        df = self.factor_comb.equal_weight(df, factor_cols, g.FACTOR_WEIGHTS)
        return df

    def get_month_end_dates(self, start_date, end_date):
        """获取每月最后一个交易日"""
        # 简化：取每月最后一个自然日后最近的交易日
        all_days = self.ds.get_trade_days(start_date, end_date)
        if not all_days:
            return []

        month_ends = {}
        for d in all_days:
            ym = d[:7]  # YYYY-MM
            month_ends[ym] = d  # 不断更新，最后保留的就是月末最后一个交易日

        return sorted(month_ends.values())

    def get_price_on_date(self, code, date):
        """获取某日收盘价"""
        start = (pd.Timestamp(date) - timedelta(days=10)).strftime('%Y-%m-%d')
        df = self.ds.get_stock_daily(code, start, date)
        if df is not None and len(df) > 0:
            return float(df.iloc[-1]['close'])
        return None

    def execute_order(self, code, target_value, date, price):
        """执行交易订单"""
        if price is None or price <= 0:
            return

        current_pos = self.positions.get(code, {'shares': 0, 'cost': 0, 'value': 0})
        current_value = current_pos['shares'] * price

        diff_value = target_value - current_value

        if abs(diff_value) < 1000:  # 忽略小额调整
            return

        # 计算交易股数（100股整数倍）
        shares_diff = int(diff_value / price / 100) * 100

        if shares_diff == 0:
            return

        trade_value = shares_diff * price

        # 扣除手续费
        commission = max(abs(trade_value) * g.COMMISSION, 5)
        if shares_diff < 0:  # 卖出
            stamp_tax = abs(trade_value) * g.STAMP_TAX
        else:
            stamp_tax = 0
        slippage_cost = abs(trade_value) * g.SLIPPAGE

        total_cost = commission + stamp_tax + slippage_cost

        if shares_diff > 0:  # 买入
            if trade_value + total_cost > self.cash:
                # 资金不足，减少买入量
                shares_diff = int(self.cash / (price * (1 + g.COMMISSION + g.SLIPPAGE)) / 100) * 100
                if shares_diff <= 0:
                    return
                trade_value = shares_diff * price
                commission = max(trade_value * g.COMMISSION, 5)
                slippage_cost = trade_value * g.SLIPPAGE
                total_cost = commission + slippage_cost

            self.cash -= (trade_value + total_cost)
            new_shares = current_pos['shares'] + shares_diff
            new_cost = (current_pos['cost'] * current_pos['shares'] + price * shares_diff) / new_shares if new_shares > 0 else 0

            self.positions[code] = {
                'shares': new_shares,
                'cost': new_cost,
                'value': new_shares * price
            }

            # 更新风控成本
            if current_pos['shares'] == 0:
                self.risk_ctrl.position_cost[code] = price
                self.risk_ctrl.position_high[code] = price

        else:  # 卖出
            self.cash += (abs(trade_value) - total_cost)
            new_shares = current_pos['shares'] + shares_diff  # shares_diff为负

            if new_shares <= 0:
                if code in self.positions:
                    del self.positions[code]
                if code in self.risk_ctrl.position_cost:
                    del self.risk_ctrl.position_cost[code]
                if code in self.risk_ctrl.position_high:
                    del self.risk_ctrl.position_high[code]
            else:
                self.positions[code] = {
                    'shares': new_shares,
                    'cost': current_pos['cost'],
                    'value': new_shares * price
                }

        self.trade_log.append({
            'date': date,
            'code': code,
            'action': 'buy' if shares_diff > 0 else 'sell',
            'shares': abs(shares_diff),
            'price': price,
            'value': abs(trade_value),
            'cost': total_cost
        })

    def monthly_rebalance(self, date):
        """月度调仓"""
        print(f"\n{'='*70}")
        print(f"【月度调仓】{date}")

        # 1. 获取股票池
        stock_pool = self.get_stock_pool(date)
        if len(stock_pool) < 20:
            print("  股票池过小，跳过调仓")
            return

        # 2. 计算因子
        factor_df = self.calc_all_factors(stock_pool, date)
        if len(factor_df) < 10:
            print("  因子数据不足，跳过调仓")
            return

        # 3. 处理因子
        factor_df = self.process_factors(factor_df)
        factor_df = self.combine_factors(factor_df)

        # 4. 组合优化
        target_portfolio = self.portfolio_opt.optimize(
            factor_df,
            max_stocks=g.MAX_STOCK_NUM,
            max_single_weight=g.MAX_SINGLE_WEIGHT
        )

        if len(target_portfolio) == 0:
            print("  优化后无持仓，跳过调仓")
            return

        # 5. 计算当前总资产
        total_value = self._calc_total_value(date)

        # 6. 生成目标权重
        self.target_weights = dict(zip(target_portfolio['code'], target_portfolio['weight']))
        print(f"  目标持仓: {len(self.target_weights)}只, 总资产: {total_value:,.0f}")

        # 7. 执行交易 - 先卖后买
        # 获取当前所有股票的价格
        prices = {}
        for code in list(self.positions.keys()) + list(self.target_weights.keys()):
            p = self.get_price_on_date(code, date)
            if p is not None:
                prices[code] = p

        # 先清仓不在目标中的股票
        for code in list(self.positions.keys()):
            if code not in self.target_weights:
                self.execute_order(code, 0, date, prices.get(code))

        # 调整持仓到目标权重
        for code, target_weight in self.target_weights.items():
            if code in prices:
                target_val = target_weight * total_value
                self.execute_order(code, target_val, date, prices[code])

        self.rebalance_log.append({
            'date': date,
            'num_stocks': len(self.target_weights),
            'total_value': total_value
        })

    def daily_risk_control(self, date):
        """日度风控"""
        prices = {}

        for code in list(self.positions.keys()):
            try:
                p = self.get_price_on_date(code, date)
                if p is not None:
                    prices[code] = p
            except:
                continue

        # 更新持仓市值
        for code in list(self.positions.keys()):
            if code in prices:
                self.positions[code]['value'] = self.positions[code]['shares'] * prices[code]

        total_value = self._calc_total_value_from_positions(prices)

        # 组合风险
        risk, drawdown = self.risk_ctrl.check_portfolio_risk(total_value)
        if risk:
            print(f"  [风控] 组合回撤{drawdown*100:.1f}%，减仓50%")
            for code in list(self.positions.keys()):
                pos = self.positions.get(code)
                if pos and pos['shares'] > 0:
                    sell_shares = pos['shares'] // 2
                    if sell_shares > 0 and code in prices:
                        self.execute_order(code, pos['value'] - sell_shares * prices[code],
                                         date, prices[code])

        # 个股止损
        for code in list(self.positions.keys()):
            pos = self.positions.get(code)
            if not pos or pos['shares'] == 0:
                continue

            if code not in prices:
                continue

            price = prices[code]
            should_stop, reason = self.risk_ctrl.check_stop_loss(code, price)
            if should_stop:
                print(f"  [止损] {code}: {reason}, 价格{price:.2f}")
                self.execute_order(code, 0, date, price)

    def _calc_total_value(self, date):
        """计算总资产"""
        position_value = 0
        for code, pos in self.positions.items():
            p = self.get_price_on_date(code, date)
            if p is not None:
                pos['value'] = pos['shares'] * p
                position_value += pos['value']
            else:
                position_value += pos.get('value', 0)

        return self.cash + position_value

    def _calc_total_value_from_positions(self, prices):
        """从已知价格计算总资产"""
        position_value = 0
        for code, pos in self.positions.items():
            if code in prices:
                position_value += pos['shares'] * prices[code]
            else:
                position_value += pos.get('value', 0)
        return self.cash + position_value

    def record_daily_value(self, date):
        """记录每日净值"""
        prices = {}
        for code in self.positions.keys():
            p = self.get_price_on_date(code, date)
            if p is not None:
                prices[code] = p

        total_value = self._calc_total_value_from_positions(prices)
        position_value = sum(pos['shares'] * prices.get(code, pos.get('value', 0) / max(pos['shares'], 1))
                           for code, pos in self.positions.items())

        self.daily_values.append({
            'date': date,
            'total_value': total_value,
            'cash': self.cash,
            'position_value': total_value - self.cash,
            'num_positions': len(self.positions)
        })

    def run(self):
        """运行回测"""
        print("=" * 70)
        print("【机构级多因子策略】本地回测 v1.5")
        print(f"回测区间: {g.START_DATE} ~ {g.END_DATE}")
        print(f"初始资金: {g.INITIAL_CAPITAL:,.0f}")
        print(f"最大持仓: {g.MAX_STOCK_NUM}只")
        print(f"因子权重: {g.FACTOR_WEIGHTS}")
        print("=" * 70)

        # 获取调仓日（每月最后一个交易日）
        rebalance_dates = self.get_month_end_dates(g.START_DATE, g.END_DATE)
        print(f"\n调仓日数量: {len(rebalance_dates)}")
        print(f"首次调仓: {rebalance_dates[0] if rebalance_dates else 'N/A'}")
        print(f"末次调仓: {rebalance_dates[-1] if rebalance_dates else 'N/A'}")

        # 获取基准数据
        print("\n获取基准数据...")
        bench_df = self.ds.get_stock_daily('sh.000905', g.START_DATE, g.END_DATE)
        if bench_df is not None and len(bench_df) > 0:
            print(f"  基准数据: {len(bench_df)}天")

        # 月度调仓循环
        for i, rebal_date in enumerate(rebalance_dates):
            print(f"\n>>> 调仓进度: {i+1}/{len(rebalance_dates)}")

            try:
                # 月度调仓
                self.monthly_rebalance(rebal_date)

                # 记录净值
                total_value = self._calc_total_value(rebal_date)
                self.daily_values.append({
                    'date': rebal_date,
                    'total_value': total_value,
                    'cash': self.cash,
                    'position_value': total_value - self.cash,
                    'num_positions': len(self.positions)
                })

            except Exception as e:
                print(f"  [ERROR] 调仓失败: {e}")
                import traceback
                traceback.print_exc()
                continue

        # 生成报告
        self.generate_report(bench_df)

    def generate_report(self, bench_df):
        """生成回测报告"""
        print("\n\n" + "=" * 70)
        print("【回测报告】")
        print("=" * 70)

        if not self.daily_values:
            print("无回测数据")
            return

        values_df = pd.DataFrame(self.daily_values)
        values_df['date'] = pd.to_datetime(values_df['date'])
        values_df = values_df.sort_values('date').drop_duplicates(subset=['date'], keep='last')

        # 计算收益指标
        initial = g.INITIAL_CAPITAL
        final_value = values_df['total_value'].iloc[-1]
        total_return = (final_value - initial) / initial

        # 年化收益
        days = (values_df['date'].iloc[-1] - values_df['date'].iloc[0]).days
        years = days / 365.25
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # 最大回撤
        values_df['cummax'] = values_df['total_value'].cummax()
        values_df['drawdown'] = (values_df['cummax'] - values_df['total_value']) / values_df['cummax']
        max_drawdown = values_df['drawdown'].max()

        # 夏普比率（使用月度收益）
        values_df['monthly_return'] = values_df['total_value'].pct_change()
        monthly_returns = values_df['monthly_return'].dropna()
        if len(monthly_returns) > 1 and monthly_returns.std() > 0:
            sharpe = monthly_returns.mean() / monthly_returns.std() * np.sqrt(12)
        else:
            sharpe = 0

        # 基准收益
        bench_return = 0
        if bench_df is not None and len(bench_df) > 0:
            bench_start = bench_df['close'].iloc[0]
            bench_end = bench_df['close'].iloc[-1]
            if bench_start > 0:
                bench_return = (bench_end - bench_start) / bench_start
                bench_annual = (1 + bench_return) ** (1 / years) - 1 if years > 0 else 0
            else:
                bench_annual = 0
        else:
            bench_annual = 0

        excess_return = annual_return - bench_annual
        info_ratio = excess_return / max(max_drawdown, 0.01)

        # 交易统计
        trades_df = pd.DataFrame(self.trade_log) if self.trade_log else pd.DataFrame()
        num_trades = len(trades_df)
        total_commission = trades_df['cost'].sum() if num_trades > 0 else 0

        print(f"\n📊 收益指标:")
        print(f"  初始资金:     {initial:>12,.0f}")
        print(f"  最终资产:     {final_value:>12,.0f}")
        print(f"  总收益率:     {total_return*100:>11.2f}%")
        print(f"  年化收益率:   {annual_return*100:>11.2f}%")
        print(f"  基准年化收益: {bench_annual*100:>11.2f}%")
        print(f"  超额年化收益: {excess_return*100:>11.2f}%")

        print(f"\n📉 风险指标:")
        print(f"  最大回撤:     {max_drawdown*100:>11.2f}%")
        print(f"  夏普比率:     {sharpe:>11.2f}")
        print(f"  信息比率:     {info_ratio:>11.2f}")

        print(f"\n💰 交易统计:")
        print(f"  交易笔数:     {num_trades:>12d}")
        print(f"  总手续费:     {total_commission:>12,.0f}")
        print(f"  调仓次数:     {len(self.rebalance_log):>12d}")

        # 年度收益分解
        print(f"\n📅 年度收益分解:")
        values_df['year'] = values_df['date'].dt.year
        for year in sorted(values_df['year'].unique()):
            year_data = values_df[values_df['year'] == year]
            if len(year_data) >= 2:
                year_start = year_data['total_value'].iloc[0]
                year_end = year_data['total_value'].iloc[-1]
                year_return = (year_end - year_start) / year_start if year_start > 0 else 0
                year_dd = year_data['drawdown'].max()
                print(f"  {year}: 收益 {year_return*100:>7.2f}%  最大回撤 {year_dd*100:>6.2f}%")

        # 保存结果
        result = {
            'strategy': 'Alpha因子增强策略 v1.5',
            'period': f"{g.START_DATE} ~ {g.END_DATE}",
            'initial_capital': initial,
            'final_value': round(final_value, 2),
            'total_return': round(total_return * 100, 2),
            'annual_return': round(annual_return * 100, 2),
            'bench_annual_return': round(bench_annual * 100, 2),
            'excess_return': round(excess_return * 100, 2),
            'max_drawdown': round(max_drawdown * 100, 2),
            'sharpe_ratio': round(sharpe, 2),
            'info_ratio': round(info_ratio, 2),
            'num_trades': num_trades,
            'total_commission': round(total_commission, 2),
            'rebalance_count': len(self.rebalance_log),
            'factor_weights': g.FACTOR_WEIGHTS,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        result_file = '/data/workspace/multifactor_backtest_result.json'
        with open(result_file, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n结果已保存: {result_file}")

        # 保存净值曲线
        values_df.to_csv('/data/workspace/multifactor_nav_curve.csv', index=False)
        print(f"净值曲线已保存: /data/workspace/multifactor_nav_curve.csv")

        # 保存交易记录
        if num_trades > 0:
            trades_df.to_csv('/data/workspace/multifactor_trades.csv', index=False)
            print(f"交易记录已保存: /data/workspace/multifactor_trades.csv")

        # 生成HTML报告
        self._generate_html_report(result, values_df, bench_df, trades_df)

        return result

    def _generate_html_report(self, result, values_df, bench_df, trades_df):
        """生成HTML回测报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Alpha因子增强策略回测报告</title>
<style>
body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{ color: #1a5276; text-align: center; border-bottom: 3px solid #2980b9; padding-bottom: 10px; }}
h2 {{ color: #2c3e50; border-left: 4px solid #3498db; padding-left: 10px; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; background: white; }}
th, td {{ border: 1px solid #ddd; padding: 10px; text-align: center; }}
th {{ background: #2980b9; color: white; }}
tr:nth-child(even) {{ background: #f2f2f2; }}
.positive {{ color: #e74c3c; font-weight: bold; }}
.negative {{ color: #27ae60; font-weight: bold; }}
.metric-card {{ display: inline-block; width: 22%; margin: 1%; padding: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
.metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
.metric-label {{ font-size: 12px; color: #7f8c8d; margin-top: 5px; }}
.chart-container {{ background: white; padding: 20px; border-radius: 8px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.section {{ background: white; padding: 20px; border-radius: 8px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
</style>
</head>
<body>
<div class="container">
<h1>🏛️ Alpha因子增强策略 - 回测报告</h1>
<p style="text-align:center; color:#7f8c8d;">机构级多因子量化策略 v1.5 | 回测周期: {result['period']}</p>

<div style="text-align:center;">
<div class="metric-card">
<div class="metric-value">{'{:.2f}%'.format(result['annual_return'])}</div>
<div class="metric-label">年化收益率</div>
</div>
<div class="metric-card">
<div class="metric-value">{'{:.2f}%'.format(result['max_drawdown'])}</div>
<div class="metric-label">最大回撤</div>
</div>
<div class="metric-card">
<div class="metric-value">{'{:.2f}'.format(result['sharpe_ratio'])}</div>
<div class="metric-label">夏普比率</div>
</div>
<div class="metric-card">
<div class="metric-value">{'{:.2f}%'.format(result['excess_return'])}</div>
<div class="metric-label">超额年化收益</div>
</div>
</div>

<div class="section">
<h2>📈 收益指标</h2>
<table>
<tr><th>指标</th><th>策略</th><th>基准(中证500)</th><th>超额</th></tr>
<tr><td>总收益率</td><td class="{'positive' if result['total_return']>0 else 'negative'}">{'{:.2f}%'.format(result['total_return'])}</td>
    <td>-</td><td>-</td></tr>
<tr><td>年化收益率</td><td class="{'positive' if result['annual_return']>0 else 'negative'}">{'{:.2f}%'.format(result['annual_return'])}</td>
    <td>{'{:.2f}%'.format(result['bench_annual_return'])}</td>
    <td class="{'positive' if result['excess_return']>0 else 'negative'}">{'{:.2f}%'.format(result['excess_return'])}</td></tr>
<tr><td>最大回撤</td><td>{'{:.2f}%'.format(result['max_drawdown'])}</td><td>-</td><td>-</td></tr>
<tr><td>夏普比率</td><td>{'{:.2f}'.format(result['sharpe_ratio'])}</td><td>-</td><td>-</td></tr>
<tr><td>信息比率</td><td>{'{:.2f}'.format(result['info_ratio'])}</td><td>-</td><td>-</td></tr>
</table>
</div>

<div class="section">
<h2>⚖️ 因子权重配置</h2>
<table>
<tr><th>因子类别</th><th>权重</th><th>因子含义</th></tr>
<tr><td>价值因子</td><td>{'{:.0f}%'.format(g.FACTOR_WEIGHTS['value']*100)}</td><td>EP/BP/SP/CPFP</td></tr>
<tr><td>质量因子</td><td>{'{:.0f}%'.format(g.FACTOR_WEIGHTS['quality']*100)}</td><td>ROE/净利率</td></tr>
<tr><td>成长因子</td><td>{'{:.0f}%'.format(g.FACTOR_WEIGHTS['growth']*100)}</td><td>营收/利润/EPS增速</td></tr>
<tr><td>动量因子</td><td>{'{:.0f}%'.format(g.FACTOR_WEIGHTS['momentum']*100)}</td><td>12M/6M/3M动量+1M反转</td></tr>
<tr><td>波动因子</td><td>{'{:.0f}%'.format(g.FACTOR_WEIGHTS['volatility']*100)}</td><td>低波动率/低下行风险/低Beta</td></tr>
<tr><td>流动性因子</td><td>{'{:.0f}%'.format(g.FACTOR_WEIGHTS['liquidity']*100)}</td><td>适中换手率</td></tr>
</table>
</div>

<div class="section">
<h2>🔧 交易统计</h2>
<table>
<tr><th>指标</th><th>数值</th></tr>
<tr><td>初始资金</td><td>{'{:,.0f}'.format(result['initial_capital'])}</td></tr>
<tr><td>最终资产</td><td>{'{:,.0f}'.format(result['final_value'])}</td></tr>
<tr><td>交易笔数</td><td>{result['num_trades']}</td></tr>
<tr><td>调仓次数</td><td>{result['rebalance_count']}</td></tr>
<tr><td>总手续费</td><td>{'{:,.0f}'.format(result['total_commission'])}</td></tr>
<tr><td>单股最大权重</td><td>{'{:.1f}%'.format(g.MAX_SINGLE_WEIGHT*100)}</td></tr>
<tr><td>止损线</td><td>{'{:.1f}%'.format(g.STOP_LOSS_RATIO*100)}</td></tr>
</table>
</div>

<div class="section">
<h2>📅 年度收益分解</h2>
<table>
<tr><th>年份</th><th>期初资产</th><th>期末资产</th><th>年度收益率</th><th>年度最大回撤</th></tr>
"""
        # 年度分解
        values_df_copy = values_df.copy()
        values_df_copy['year'] = pd.to_datetime(values_df_copy['date']).dt.year
        for year in sorted(values_df_copy['year'].unique()):
            year_data = values_df_copy[values_df_copy['year'] == year]
            if len(year_data) >= 2:
                y_start = year_data['total_value'].iloc[0]
                y_end = year_data['total_value'].iloc[-1]
                y_ret = (y_end - y_start) / y_start * 100 if y_start > 0 else 0
                y_dd = year_data['drawdown'].max() * 100
                css = 'positive' if y_ret > 0 else 'negative'
                html += f"""<tr><td>{year}</td><td>{y_start:,.0f}</td><td>{y_end:,.0f}</td>
                    <td class="{css}">{y_ret:.2f}%</td><td>{y_dd:.2f}%</td></tr>\n"""

        html += """</table>
</div>

<div class="section">
<h2>🛡️ 风控规则</h2>
<table>
<tr><th>风控类型</th><th>触发条件</th><th>操作</th></tr>
<tr><td>固定止损</td><td>亏损 ≥ 8%</td><td>清仓</td></tr>
<tr><td>追踪止盈</td><td>盈利>5%后回撤 ≥ 5%</td><td>清仓</td></tr>
<tr><td>组合风控</td><td>组合回撤 > 15%</td><td>全部持仓减仓50%</td></tr>
</table>
</div>

<div class="section">
<p style="text-align:center; color:#7f8c8d; font-size:12px;">
报告生成时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """ | 
策略版本: v1.5 | 数据源: BaoStock
</p>
</div>
</div>
</body>
</html>"""

        report_file = '/data/workspace/multifactor_backtest_report.html'
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML报告已保存: {report_file}")


# ============================================================================
# 主函数
# ============================================================================
if __name__ == '__main__':
    engine = BacktestEngine()
    result = engine.run()
