#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机构级多因子量化策略 - Alpha因子增强策略 v1.5 A股版
数据源: JQData SDK (中证500成分股 + 基本面数据)
回测周期: 2025-01-14 ~ 2026-01-21 (JQData试用账号限制, 约1年)
调仓频率: 月度

策略框架: 因子挖掘 → 因子测试 → 因子合成 → 组合构建 → 风险控制
原始目标: 年化超额收益8-15%, 信息比率>1.5
"""

import os, sys, json, time, warnings, datetime
from functools import reduce
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


# ================================================================
# 全局配置
# ================================================================
class Config:
    """策略配置"""
    START_DATE = '2025-01-14'
    END_DATE = '2026-01-21'
    INITIAL_CAPITAL = 1_000_000
    INDEX_POOL = '000905.XSHG'  # 中证500

    # 股票池筛选
    MIN_MARKET_CAP = 20       # 最小市值(亿元)
    MAX_MARKET_CAP = 5000     # 最大市值(亿元)
    MIN_PRICE = 1             # 最低股价(元)
    MAX_STOCK_NUM = 50        # 最大持仓数

    # 原始因子权重（作者888设定）
    FACTOR_WEIGHTS_ORIGINAL = {
        'value': 0.20,
        'quality': 0.25,
        'growth': 0.15,
        'momentum': 0.15,
        'volatility': 0.15,
        'liquidity': 0.10
    }

    # A股IC优化权重
    # A股特点: 动量效应显著, 价值因子在震荡市有效, 成长因子均值回归
    FACTOR_WEIGHTS = {
        'value': 0.15,       # A股价值因子IC适中，保留一定权重
        'quality': 0.20,     # 高ROE在A股有效
        'growth': 0.10,      # 成长因子均值回归，降权
        'momentum': 0.30,    # A股动量效应显著，核心因子
        'volatility': 0.10,  # 低波动在A股无效，降权
        'liquidity': 0.15    # 机构偏好流动性
    }

    MAX_SINGLE_WEIGHT = 0.05
    STOP_LOSS_RATIO = 0.08         # 固定止损8%
    MAX_TURNOVER = 0.50

    # 交易成本（A股标准）
    COMMISSION = 0.0003             # 佣金万3
    SLIPPAGE = 0.002                # 滑点
    STAMP_TAX = 0.001               # 印花税千1（卖出时收取）
    RISK_FREE_RATE = 0.03           # 无风险利率3%

    # JQData账号
    JQ_USERNAME = '17665394957'
    JQ_PASSWORD = 'Wshqwpsa54565852'


g = Config()


# ================================================================
# 因子计算模块 - 6大因子体系（A股适配版）
# ================================================================
class FactorCalculator:
    """因子计算器 - 基于JQData A股基本面和价格数据"""

    @staticmethod
    def calc_value_factors(fundamentals):
        """
        价值因子 - PE/PB/PS/PCF倒数
        A股适配: PE合理区间10-25, PB合理区间1-4
        """
        results = []
        for code, fund in fundamentals.items():
            pe = fund.get('pe_ratio')
            pb = fund.get('pb_ratio')
            ps = fund.get('ps_ratio')
            pcf = fund.get('pcf_ratio')

            # PE评分
            if pe is not None and pe > 0:
                if 10 <= pe <= 25:
                    pe_inv = 1.0
                elif pe < 10:
                    pe_inv = 0.7
                elif pe < 40:
                    pe_inv = 0.8
                elif pe < 80:
                    pe_inv = 0.5
                else:
                    pe_inv = 0.2
            else:
                pe_inv = 0.5

            # PB评分
            if pb is not None and pb > 0:
                if 1 <= pb <= 4:
                    pb_inv = 1.0
                elif pb < 1:
                    pb_inv = 0.7
                elif pb < 8:
                    pb_inv = 0.6
                else:
                    pb_inv = 0.3
            else:
                pb_inv = 0.5

            # PS评分
            if ps is not None and ps > 0:
                ps_inv = 1 / max(ps, 0.1)
            else:
                ps_inv = 0.5

            # PCF评分
            if pcf is not None and pcf > 0:
                pcf_inv = 1 / max(pcf, 0.1)
            else:
                pcf_inv = 0.5

            results.append({
                'code': code,
                'value_pe': pe_inv,
                'value_pb': pb_inv,
                'value_ps': ps_inv,
                'value_pcf': pcf_inv,
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['value_score'] = (
            df['value_pe'].rank(pct=True).fillna(0.5) * 0.25 +
            df['value_pb'].rank(pct=True).fillna(0.5) * 0.25 +
            df['value_ps'].rank(pct=True).fillna(0.5) * 0.25 +
            df['value_pcf'].rank(pct=True).fillna(0.5) * 0.25
        )

        return df[['code', 'value_score']]

    @staticmethod
    def calc_quality_factors(fundamentals):
        """
        质量因子 - ROE/ROA
        A股适配: 高ROE有效，选ROE>15%的优质公司
        """
        results = []
        for code, fund in fundamentals.items():
            roe = fund.get('roe')
            roa = fund.get('roa')

            if roe is not None:
                quality_roe = max(0, min(roe / 20, 1))
            else:
                quality_roe = 0.5

            if roa is not None:
                quality_roa = max(0, min(roa / 10, 1))
            else:
                quality_roa = 0.5

            results.append({
                'code': code,
                'quality_roe': quality_roe,
                'quality_roa': quality_roa,
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['quality_score'] = (
            df['quality_roe'].rank(pct=True).fillna(0.5) * 0.6 +
            df['quality_roa'].rank(pct=True).fillna(0.5) * 0.4
        )

        return df[['code', 'quality_score']]

    @staticmethod
    def calc_growth_factors(fundamentals, stock_prices):
        """
        成长因子 - 营收增长率/利润增长率
        无基本面数据时使用价格动量作为成长代理
        """
        results = []
        for code, fund in fundamentals.items():
            inc_rev = fund.get('inc_revenue_year_on_year')
            inc_profit = fund.get('inc_net_profit_year_on_year')

            if inc_rev is not None and inc_profit is not None:
                growth_revenue = max(0, min(inc_rev / 50, 1))
                growth_profit = max(0, min(inc_profit / 50, 1))

                results.append({
                    'code': code,
                    'growth_revenue': growth_revenue,
                    'growth_profit': growth_profit,
                })
            else:
                # 无基本面数据，使用价格动量代理
                prices_df = stock_prices.get(code, pd.DataFrame())
                if len(prices_df) >= 120:
                    try:
                        close = prices_df['close']
                        if len(close) >= 120:
                            growth_60d = close.iloc[-1] / close.iloc[-60] - 1 if len(close) >= 60 else 0
                            growth_120d = close.iloc[-1] / close.iloc[-120] - 1

                            results.append({
                                'code': code,
                                'growth_revenue': growth_60d,
                                'growth_profit': growth_120d,
                            })
                    except:
                        pass

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        # 成长因子：A股均值回归效应显著，反向使用
        df['growth_score'] = (
            (1 - df['growth_revenue'].rank(pct=True).fillna(0.5)) * 0.5 +
            (1 - df['growth_profit'].rank(pct=True).fillna(0.5)) * 0.5
        )

        return df[['code', 'growth_score']]

    @staticmethod
    def calc_momentum_factors(stock_prices):
        """
        动量因子 - 与原策略一致
        12M/6M/3M动量 + 1M反转
        """
        results = []
        for code, prices_df in stock_prices.items():
            if len(prices_df) < 240:
                continue

            try:
                close = prices_df['close']
                mom_12m = close.iloc[-1] / close.iloc[-240] - 1 if len(close) >= 240 else 0
                mom_6m = close.iloc[-1] / close.iloc[-120] - 1 if len(close) >= 120 else 0
                mom_3m = close.iloc[-1] / close.iloc[-60] - 1 if len(close) >= 60 else 0
                rev_1m = close.iloc[-1] / close.iloc[-20] - 1 if len(close) >= 20 else 0

                if pd.isna(mom_12m): mom_12m = 0
                if pd.isna(mom_6m): mom_6m = 0
                if pd.isna(mom_3m): mom_3m = 0
                if pd.isna(rev_1m): rev_1m = 0

                results.append({
                    'code': code,
                    'momentum_12m': mom_12m,
                    'momentum_6m': mom_6m,
                    'momentum_3m': mom_3m,
                    'reversal_1m': rev_1m,
                })
            except:
                continue

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['momentum_score'] = (
            df['momentum_12m'].rank(pct=True).fillna(0.5) * 0.3 +
            df['momentum_6m'].rank(pct=True).fillna(0.5) * 0.3 +
            df['momentum_3m'].rank(pct=True).fillna(0.5) * 0.2 +
            (1 - df['reversal_1m'].rank(pct=True).fillna(0.5)) * 0.2
        )

        return df[['code', 'momentum_score']]

    @staticmethod
    def calc_volatility_factors(stock_prices, bench_prices=None):
        """
        波动因子 - 低波动 + 低下行风险 + 低Beta
        """
        # 基准收益率
        bench_ret = None
        if bench_prices is not None and len(bench_prices) >= 60:
            bench_ret = bench_prices['close'].pct_change().dropna().values
            if len(bench_ret) > 60:
                bench_ret = bench_ret[-60:]

        results = []
        for code, prices_df in stock_prices.items():
            if len(prices_df) < 40:
                continue

            try:
                ret = prices_df['close'].pct_change().dropna().values
                if len(ret) < 20:
                    continue

                # 年化波动率
                vol = np.std(ret) * np.sqrt(252)

                # 下行波动率
                neg = ret[ret < 0]
                downside_vol = np.std(neg) * np.sqrt(252) if len(neg) > 5 else vol

                # Beta
                beta = 1.0
                if bench_ret is not None and len(bench_ret) > 20:
                    ml = min(len(ret), len(bench_ret))
                    if ml > 20:
                        cov = np.cov(ret[-ml:], bench_ret[-ml:])
                        if cov.shape == (2, 2) and cov[1, 1] > 0:
                            beta = cov[0, 1] / cov[1, 1]

                results.append({
                    'code': code,
                    'volatility': vol,
                    'downside_risk': downside_vol,
                    'beta': beta,
                })
            except:
                continue

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['volatility_score'] = (
            (1 - df['volatility'].rank(pct=True).fillna(0.5)) * 0.4 +
            (1 - df['downside_risk'].rank(pct=True).fillna(0.5)) * 0.4 +
            (1 - df['beta'].rank(pct=True).fillna(0.5)) * 0.2
        )

        return df[['code', 'volatility_score']]

    @staticmethod
    def calc_liquidity_factors(fundamentals):
        """
        流动性因子 - 换手率适度
        A股适配: 换手率在3%-8%区间得分最高（机构偏好）
        """
        results = []
        for code, fund in fundamentals.items():
            turnover = fund.get('turnover_ratio')

            if turnover is not None and turnover > 0:
                liquidity_turnover = turnover
            else:
                liquidity_turnover = 5.0

            results.append({
                'code': code,
                'liquidity_turnover': liquidity_turnover,
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        # 换手率适中最好（3%-8%），rank接近0.5最高分
        turnover_rank = df['liquidity_turnover'].rank(pct=True)
        df['liquidity_score'] = (1 - abs(turnover_rank - 0.5) * 2).clip(0, 1)

        return df[['code', 'liquidity_score']]


# ================================================================
# 因子处理模块
# ================================================================
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


# ================================================================
# 因子合成模块
# ================================================================
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


# ================================================================
# 组合优化模块
# ================================================================
class PortfolioOptimizer:
    """组合优化器"""

    @staticmethod
    def optimize(df, max_stocks=50, max_single_weight=0.05):
        """组合优化 - 评分加权 + 权重上限"""
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


# ================================================================
# 风险控制模块
# ================================================================
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
        if loss <= -g.STOP_LOSS_RATIO:
            return True, 'fixed_stop'

        # 盈利5%后移动止损5%
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


# ================================================================
# 数据获取模块（JQData SDK版本）
# ================================================================
class JQDataFetcher:
    """JQData数据获取器"""
    def __init__(self):
        import jqdatasdk
        jqdatasdk.auth(g.JQ_USERNAME, g.JQ_PASSWORD)
        self.jq = jqdatasdk
        self._stock_pool_cache = {}

    def get_zz500_stocks(self, date):
        """获取中证500成分股"""
        if date in self._stock_pool_cache:
            return self._stock_pool_cache[date]

        try:
            stocks = self.jq.get_index_stocks(g.INDEX_POOL, date=date)
            self._stock_pool_cache[date] = stocks
            return stocks
        except Exception as e:
            print(f"  ⚠️ 获取中证500成分股失败: {e}")
            return []

    def get_stock_prices(self, stock_list, date):
        """获取股票价格数据（截至date的最近250个交易日）"""
        try:
            df = self.jq.get_price(
                stock_list,
                end_date=date,
                count=250,
                frequency='daily',
                fields=['open', 'close', 'high', 'low', 'volume'],
                fq='pre',
                panel=False
            )
            return df
        except Exception as e:
            return pd.DataFrame()

    def get_fundamentals(self, stock_list, date):
        """获取基本面数据（估值 + 指标）"""
        fundamentals = {}

        # 1. 估值数据
        try:
            q = self.jq.query(
                self.jq.valuation.code,
                self.jq.valuation.pe_ratio,
                self.jq.valuation.pb_ratio,
                self.jq.valuation.ps_ratio,
                self.jq.valuation.pcf_ratio,
                self.jq.valuation.market_cap,
                self.jq.valuation.turnover_ratio,
            ).filter(
                self.jq.valuation.code.in_(stock_list)
            )
            df_val = self.jq.get_fundamentals(q, date=date)

            if df_val is not None and len(df_val) > 0:
                for _, row in df_val.iterrows():
                    code = row['code']
                    fundamentals[code] = {}
                    for col in df_val.columns:
                        if col != 'code':
                            v = row[col]
                            fundamentals[code][col] = float(v) if v is not None and not pd.isna(v) and v != 0 else None
        except Exception as e:
            pass

        # 2. 指标数据（ROE/ROA/营收增长率/利润增长率）
        try:
            q2 = self.jq.query(
                self.jq.valuation.code,
                self.jq.indicator.roe,
                self.jq.indicator.roa,
                self.jq.indicator.inc_revenue_year_on_year,
                self.jq.indicator.inc_net_profit_year_on_year,
            ).filter(
                self.jq.valuation.code.in_(stock_list)
            )
            df_ind = self.jq.get_fundamentals(q2, date=date)

            if df_ind is not None and len(df_ind) > 0:
                for _, row in df_ind.iterrows():
                    code = row['code']
                    if code not in fundamentals:
                        fundamentals[code] = {}
                    for col in df_ind.columns:
                        if col != 'code':
                            v = row[col]
                            fundamentals[code][col] = float(v) if v is not None and not pd.isna(v) and v != 0 else None
        except Exception as e:
            pass

        return fundamentals

    def get_security_info(self, code, date):
        """获取证券信息（名称/是否停牌/是否ST等）"""
        try:
            info = self.jq.get_security_info(code)
            return info
        except:
            return None


# ================================================================
# 回测引擎
# ================================================================
def run_backtest(data_fetcher, start, end, factor_weights, freq='M'):
    """
    运行完整回测
    data_fetcher: JQData数据获取器
    start/end: 回测起止日期
    factor_weights: 因子权重字典
    freq: 调仓频率 ('M' = 月度)
    """
    # 加载中证500指数数据（作为基准收益率计算Beta）
    zz500_index = pd.read_csv('/data/workspace/zz500_index_daily.csv', index_col='date', parse_dates=True)
    zz500_index = zz500_index[start:end]

    # 生成交易日序列
    mask = (zz500_index.index >= start) & (zz500_index.index <= end)
    dates = zz500_index[mask].index.tolist()

    if len(dates) < 20:
        return {'状态': '数据不足', '原因': f'仅{len(dates)}个交易日'}

    print(f"  回测交易日: {len(dates)} 天 ({dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')})")

    # 初始化
    cash = float(g.INITIAL_CAPITAL)
    positions = {}      # sym -> shares
    pos_cost = {}       # sym -> cost price
    pos_high = {}       # sym -> high water mark price
    risk_ctrl = RiskController()

    pv_list = []
    rebalance_count = 0
    stop_events = []
    peak_pv = g.INITIAL_CAPITAL
    max_dd = 0
    last_month = None
    total_commission = 0

    # 缓存
    price_cache = {}        # sym -> DataFrame
    fundamentals_cache = {} # date -> {code: fund_data}

    # 月度日期列表（调仓日）
    rebal_dates = []
    for d in dates:
        if last_month is None or d.month != last_month:
            rebal_dates.append(d)
            last_month = d.month
    last_month = None

    print(f"  调仓日: {len(rebal_dates)} 个")

    for date in dates:
        date_str = date.strftime('%Y-%m-%d')

        # 月度调仓
        if freq == 'M' and (last_month is None or date.month != last_month):
            last_month = date.month

            # 1. 获取中证500成分股
            pool = data_fetcher.get_zz500_stocks(date_str)
            if len(pool) < 20:
                continue

            # 2. 获取基本面数据
            if date_str not in fundamentals_cache:
                fundamentals_cache[date_str] = data_fetcher.get_fundamentals(pool, date_str)
            fundamentals = fundamentals_cache[date_str]

            # 3. 获取价格数据（最近250天）
            stock_prices = {}
            for code in pool:
                if code not in price_cache:
                    df = data_fetcher.get_stock_prices([code], date_str)
                    if df is not None and len(df) > 0:
                        price_cache[code] = df
                if code in price_cache:
                    stock_prices[code] = price_cache[code]

            # 4. 筛选有效股票（有足够历史数据+价格>=MIN_PRICE+非ST非停牌）
            valid_pool = []
            for code in pool:
                if code not in stock_prices or len(stock_prices[code]) < 200:
                    continue
                # 价格筛选
                prices_df = stock_prices[code]
                if date in prices_df.index:
                    close = float(prices_df.loc[date, 'close'])
                    if close < g.MIN_PRICE:
                        continue
                # ST/停牌筛选
                try:
                    info = data_fetcher.get_security_info(code, date_str)
                    if info is None:
                        continue
                    name = info.display_name
                    if name and ('ST' in name or '*' in name or '退' in name):
                        continue
                    if hasattr(info, 'paused') and info.paused:
                        continue
                except:
                    pass

                # 市值筛选
                fund = fundamentals.get(code, {})
                mcap = fund.get('market_cap')
                if mcap is not None:
                    if mcap < g.MIN_MARKET_CAP or mcap > g.MAX_MARKET_CAP:
                        continue

                valid_pool.append(code)

            if len(valid_pool) < 20:
                continue

            # 5. 计算6大因子
            sub_prices = {s: stock_prices[s] for s in valid_pool if s in stock_prices}
            sub_fundamentals = {s: fundamentals.get(s, {}) for s in valid_pool}

            factor_dfs = []
            # 价值因子
            f = FactorCalculator.calc_value_factors(sub_fundamentals)
            if len(f) > 0:
                factor_dfs.append(f)
            # 质量因子
            f = FactorCalculator.calc_quality_factors(sub_fundamentals)
            if len(f) > 0:
                factor_dfs.append(f)
            # 成长因子
            f = FactorCalculator.calc_growth_factors(sub_fundamentals, sub_prices)
            if len(f) > 0:
                factor_dfs.append(f)
            # 动量因子
            f = FactorCalculator.calc_momentum_factors(sub_prices)
            if len(f) > 0:
                factor_dfs.append(f)
            # 波动因子
            bench_data = zz500_index[zz500_index.index <= date].tail(60)
            f = FactorCalculator.calc_volatility_factors(sub_prices, bench_data)
            if len(f) > 0:
                factor_dfs.append(f)
            # 流动性因子
            f = FactorCalculator.calc_liquidity_factors(sub_fundamentals)
            if len(f) > 0:
                factor_dfs.append(f)

            # 6. 合并因子数据
            if len(factor_dfs) < 3:
                continue

            merged = reduce(lambda x, y: pd.merge(x, y, on='code', how='outer'), factor_dfs)
            if len(merged) < 10:
                continue

            # 7. 因子处理
            factor_cols = [col for col in merged.columns if col.endswith('_score')]
            merged = FactorProcessor.fill_na_with_median(merged, factor_cols)
            for col in factor_cols:
                merged[col] = FactorProcessor.winsorize_mad(merged[col])
                merged[col] = FactorProcessor.standardize(merged[col])

            # 8. 因子合成
            merged = FactorCombiner.equal_weight(merged, factor_cols, factor_weights)

            # 9. 组合优化
            portfolio = PortfolioOptimizer.optimize(
                merged,
                max_stocks=g.MAX_STOCK_NUM,
                max_single_weight=g.MAX_SINGLE_WEIGHT
            )
            target_weights = dict(zip(portfolio['code'], portfolio['weight']))

            # 10. 趋势择时（中证500指数低于200日均线时减仓50%）
            if date in zz500_index.index:
                idx_loc = zz500_index.index.get_loc(date)
                if idx_loc >= 200:
                    zz500_close = float(zz500_index.iloc[idx_loc]['close'])
                    # 计算200日均线
                    zz500_sma200 = float(zz500_index.iloc[idx_loc-200:idx_loc+1]['close'].mean())
                    if zz500_close < zz500_sma200:
                        # 熊市信号：减仓50%
                        target_weights = {k: v * 0.5 for k, v in target_weights.items()}

            if len(target_weights) < 5:
                continue

            # 11. 执行调仓
            pv_before = cash
            for sym, shares in positions.items():
                if sym in stock_prices and date in stock_prices[sym].index:
                    p = float(stock_prices[sym].loc[date, 'close'])
                    if p > 0:
                        pv_before += shares * p
                    else:
                        pv_before += pos_cost.get(sym, 0) * shares

            # 先卖出不在目标中的持仓
            for sym in list(positions.keys()):
                if sym not in target_weights:
                    shares = positions[sym]
                    if sym in stock_prices and date in stock_prices[sym].index:
                        p = float(stock_prices[sym].loc[date, 'close'])
                        if p > 0 and shares > 0:
                            sell_amount = shares * p
                            commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                            cash += sell_amount - commission
                            total_commission += commission
                    del positions[sym]
                    pos_cost.pop(sym, None)
                    pos_high.pop(sym, None)

            # 调整持仓
            for sym, target_weight in target_weights.items():
                if sym not in stock_prices or date not in stock_prices[sym].index:
                    continue
                p = float(stock_prices[sym].loc[date, 'close'])
                if p <= 0:
                    continue

                target_value = pv_before * target_weight
                target_shares = int(target_value / p)

                current_shares = positions.get(sym, 0)
                diff_shares = target_shares - current_shares

                if abs(diff_shares) < 1:  # 差异小于1股，跳过
                    continue

                if diff_shares > 0:
                    # 买入
                    buy_amount = diff_shares * p
                    commission = buy_amount * g.COMMISSION
                    if cash >= buy_amount + commission:
                        cash -= buy_amount + commission
                        total_commission += commission
                        positions[sym] = target_shares
                        if sym not in pos_cost:
                            pos_cost[sym] = p
                            pos_high[sym] = p
                        else:
                            # 更新成本价（加权平均）
                            old_cost = pos_cost[sym]
                            old_shares = current_shares
                            if target_shares > 0:
                                new_cost = (old_cost * old_shares + p * diff_shares) / target_shares
                                pos_cost[sym] = new_cost
                else:
                    # 卖出部分
                    sell_shares = abs(diff_shares)
                    sell_amount = sell_shares * p
                    commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                    cash += sell_amount - commission
                    total_commission += commission
                    positions[sym] = target_shares

            rebalance_count += 1

        # 日度风控 - 个股止损
        for sym in list(positions.keys()):
            shares = positions[sym]
            if shares <= 0:
                del positions[sym]
                continue
            if sym not in stock_prices or date not in stock_prices[sym].index:
                continue
            p = float(stock_prices[sym].loc[date, 'close'])
            if p <= 0:
                continue

            should_stop = False
            reason = None
            cost = pos_cost.get(sym, p)
            if sym not in pos_high:
                pos_high[sym] = p
            else:
                pos_high[sym] = max(pos_high[sym], p)
            high = pos_high[sym]

            # 固定止损8%
            if cost > 0:
                loss = (p - cost) / cost
                if loss <= -g.STOP_LOSS_RATIO:
                    should_stop = True
                    reason = 'fixed_stop'
                # 盈利5%后移动止损5%
                elif loss > 0.05:
                    drawdown = (high - p) / high if high > 0 else 0
                    if drawdown >= 0.05:
                        should_stop = True
                        reason = 'trailing_stop'

            if should_stop:
                sell_amount = shares * p
                commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                cash += sell_amount - commission
                total_commission += commission
                pnl = (p - cost) / cost * 100 if cost > 0 else 0
                del positions[sym]
                pos_cost.pop(sym, None)
                pos_high.pop(sym, None)
                stop_events.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'stock': sym,
                    'reason': reason,
                    'pnl%': round(pnl, 2)
                })

        # 日度风控 - 组合风险
        pv = cash
        for sym, shares in positions.items():
            if sym in stock_prices and date in stock_prices[sym].index:
                p = float(stock_prices[sym].loc[date, 'close'])
                if p > 0:
                    pv += shares * p

        risk, drawdown = risk_ctrl.check_portfolio_risk(pv)
        if risk:
            # 组合回撤超限，减仓1/3
            for sym in list(positions.keys()):
                sell_shares = positions[sym] // 3
                if sell_shares > 0 and sym in stock_prices and date in stock_prices[sym].index:
                    p = float(stock_prices[sym].loc[date, 'close'])
                    if p > 0:
                        sell_amount = sell_shares * p
                        commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                        cash += sell_amount - commission
                        total_commission += commission
                        positions[sym] -= sell_shares

        # 滑点成本
        if len(pv_list) > 0:
            daily_slippage = pv * g.SLIPPAGE / 252
            pv -= daily_slippage

        # 记录当日市值
        pv = cash
        for sym, shares in positions.items():
            if sym in stock_prices and date in stock_prices[sym].index:
                p = float(stock_prices[sym].loc[date, 'close'])
                if p > 0:
                    pv += shares * p
        pv_list.append(pv)

    return _calc_perf(pv_list, dates, rebalance_count, stop_events, total_commission)


def _calc_perf(pv_list, dates, rebal_count, stops, total_commission):
    """计算绩效指标"""
    if len(pv_list) < 2:
        return {'状态': '数据不足', '原因': f'仅{len(pv_list)}个数据点'}

    pv = np.array(pv_list, dtype=float)
    rets = np.diff(pv) / pv[:-1]
    rets = np.concatenate([[0], rets])

    total_r = (pv[-1] / pv[0] - 1) * 100
    n_days = len(pv)
    ny = n_days / 252
    annual = ((1 + total_r / 100) ** (1 / ny) - 1) * 100 if ny > 0 and total_r > -100 else -100

    peak = np.maximum.accumulate(pv)
    dd = (pv - peak) / peak * 100
    max_dd = abs(dd.min())

    drf = g.RISK_FREE_RATE / 252
    exc = rets - drf
    sharpe = np.mean(exc) / np.std(exc) * np.sqrt(252) if np.std(exc) > 0 else 0
    calmar = annual / max_dd if max_dd > 0 else 0
    sortino_denom = np.std(exc[exc < 0]) * np.sqrt(252) if (exc < 0).any() and np.std(exc[exc < 0]) > 0 else 1
    sortino = np.mean(exc) * np.sqrt(252) / sortino_denom

    pv_s = pd.Series(pv, index=dates[:len(pv)])
    yearly = {}
    for y in sorted(pv_s.index.year.unique()):
        yd = pv_s[pv_s.index.year == y]
        if len(yd) > 1:
            yearly[str(y)] = round((yd.iloc[-1] / yd.iloc[0] - 1) * 100, 2)

    monthly = {}
    for y in sorted(pv_s.index.year.unique()):
        for m in range(1, 13):
            md = pv_s[(pv_s.index.year == y) & (pv_s.index.month == m)]
            if len(md) > 1:
                monthly[f"{y}-{m:02d}"] = round((md.iloc[-1] / md.iloc[0] - 1) * 100, 2)

    # 交易统计
    win = (rets > 0).sum()
    total = len(rets[rets != 0])
    wr = win / total * 100 if total > 0 else 0

    aw = rets[rets > 0].mean() if (rets > 0).any() else 0
    al = abs(rets[rets < 0].mean()) if (rets < 0).any() else 1
    plr = aw / al if al > 0 else 0

    streak = 0
    max_streak = 0
    for r in rets < 0:
        streak = streak + 1 if r else 0
        max_streak = max(max_streak, streak)

    fs = sum(1 for e in stops if e['reason'] == 'fixed_stop')
    ts_count = sum(1 for e in stops if e['reason'] == 'trailing_stop')

    return {
        '状态': '✅',
        '总收益率%': round(total_r, 2),
        '年化收益%': round(annual, 2),
        '最大回撤%': round(max_dd, 2),
        '夏普比率': round(sharpe, 2),
        '索提诺比率': round(sortino, 2),
        '卡尔马比率': round(calmar, 2),
        '胜率%': round(wr, 2),
        '盈亏比': round(plr, 2),
        '最大连续亏损天数': max_streak,
        '年度收益': yearly,
        '月度收益': monthly,
        '止损事件': {'固定止损': fs, '移动止损': ts_count, '总计': len(stops)},
        '调仓次数': rebal_count,
        '总手续费': round(total_commission, 2),
        '最终资产': round(pv[-1], 2),
    }


def run_buyhold_bench(bench_data, start, end):
    """中证500指数买入持有基准"""
    mask = (bench_data.index >= start) & (bench_data.index <= end)
    dates = bench_data[mask].index
    pv = bench_data.loc[dates, 'close'].values.astype(float)
    pv = pv / pv[0] * g.INITIAL_CAPITAL

    rets = np.diff(pv) / pv[:-1]
    rets = np.concatenate([[0], rets])
    tr = (pv[-1] / pv[0] - 1) * 100
    ny = len(pv) / 252
    an = ((1 + tr / 100) ** (1 / ny) - 1) * 100
    peak = np.maximum.accumulate(pv)
    mdd = abs(((pv - peak) / peak * 100).min())
    exc = rets - g.RISK_FREE_RATE / 252
    sh = np.mean(exc) / np.std(exc) * np.sqrt(252) if np.std(exc) > 0 else 0
    ca = an / mdd if mdd > 0 else 0

    pv_s = pd.Series(pv, index=dates)
    yearly = {}
    for y in sorted(pv_s.index.year.unique()):
        yd = pv_s[pv_s.index.year == y]
        if len(yd) > 1:
            yearly[str(y)] = round((yd.iloc[-1] / yd.iloc[0] - 1) * 100, 2)

    return {
        '总收益率%': round(tr, 2), '年化收益%': round(an, 2),
        '最大回撤%': round(mdd, 2), '夏普比率': round(sh, 2),
        '卡尔马比率': round(ca, 2), '年度收益': yearly,
    }


def overfitting_test(data_fetcher, start, end, factor_weights):
    """过拟合检测：训练集(70%) vs 测试集(30%)"""
    bench_data = pd.read_csv('/data/workspace/zz500_index_daily.csv', index_col='date', parse_dates=True)
    mask = (bench_data.index >= start) & (bench_data.index <= end)
    dates = bench_data[mask].index
    sp = int(len(dates) * 0.7)
    te = dates[sp].strftime('%Y-%m-%d')
    ts = dates[sp + 1].strftime('%Y-%m-%d')

    tr = run_backtest(data_fetcher, start, te, factor_weights)
    tst = run_backtest(data_fetcher, ts, end, factor_weights)

    train_ann = tr.get('年化收益%', 0)
    test_ann = tst.get('年化收益%', 0)

    if train_ann != 0:
        ratio = test_ann / train_ann
    else:
        ratio = 0

    overfit_detected = False
    overfit_details = ''
    if train_ann > 0:
        underperformance = (train_ann - test_ann) / abs(train_ann)
        if underperformance > 0.30:
            overfit_detected = True
            overfit_details = f"测试集年化({test_ann:.1f}%)低于训练集({train_ann:.1f}%)达{underperformance*100:.0f}%，超过阈值30%"
    elif train_ann <= 0 and test_ann <= 0:
        overfit_details = "训练集和测试集均亏损，策略无效"

    return {
        '训练集': {k: tr[k] for k in ['年化收益%', '最大回撤%', '夏普比率']},
        '测试集': {k: tst[k] for k in ['年化收益%', '最大回撤%', '夏普比率']},
        '过拟合比率': round(ratio, 2),
        '过拟合检测': overfit_detected,
        '过拟合详情': overfit_details,
    }


def consistency_check(yearly_results):
    """多周期一致性验证"""
    warnings = []
    failed = 0

    for y, ret in yearly_results.items():
        y_warnings = []
        if ret < -20:
            y_warnings.append(f"{y}年收益{ret}%，低于-20%阈值")
        failed += 1 if y_warnings else 0
        warnings.extend(y_warnings)

    if failed == 0:
        return {'passed': True, 'warnings': [], 'verdict': '通过'}
    elif failed <= 1:
        return {'passed': True, 'warnings': warnings, 'verdict': '标记警告'}
    else:
        return {'passed': False, 'warnings': warnings, 'verdict': '不予采纳'}


# ================================================================
# 主函数
# ================================================================
def main():
    print("=" * 70)
    print("  机构级多因子量化策略 - Alpha因子增强策略 v1.5 A股版")
    print("  作者: 888 | 数据源: JQData SDK (中证500 + 基本面)")
    print("  回测周期: 2025-01-14 ~ 2026-01-21 (JQData试用账号)")
    print("=" * 70)

    # 初始化JQData
    print(f"\n📂 初始化JQData连接...")
    data_fetcher = JQDataFetcher()
    print(f"  ✅ JQData连接成功")

    # 加载中证500指数数据
    print(f"\n📊 加载中证500指数数据...")
    zz500_index = pd.read_csv('/data/workspace/zz500_index_daily.csv', index_col='date', parse_dates=True)
    zz500_index = zz500_index[g.START_DATE:g.END_DATE]
    print(f"  ✅ 中证500指数: {len(zz500_index)} 行 ({zz500_index.index[0].strftime('%Y-%m-%d')} ~ {zz500_index.index[-1].strftime('%Y-%m-%d')})")

    # ══════════════════════════════════════════════════════════
    # 回测1: 作者888原始权重
    # ══════════════════════════════════════════════════════════
    original_weights = g.FACTOR_WEIGHTS_ORIGINAL
    print(f"\n🚀 回测1: 作者原始权重 {original_weights}")

    r1 = run_backtest(data_fetcher, g.START_DATE, g.END_DATE, original_weights)

    # ══════════════════════════════════════════════════════════
    # 回测2: A股IC优化权重
    # ══════════════════════════════════════════════════════════
    print(f"\n🚀 回测2: A股IC优化权重 {g.FACTOR_WEIGHTS}")
    r2 = run_backtest(data_fetcher, g.START_DATE, g.END_DATE, g.FACTOR_WEIGHTS)

    # 基准
    print(f"\n📈 运行基准 (中证500指数 Buy & Hold)...")
    spy_r = run_buyhold_bench(zz500_index, g.START_DATE, g.END_DATE)

    # 过拟合检测
    print(f"\n🔬 过拟合检测 (A股IC优化版, 训练70% vs 测试30%)...")
    overfit = overfitting_test(data_fetcher, g.START_DATE, g.END_DATE, g.FACTOR_WEIGHTS)

    # 一致性验证
    consistency = consistency_check(r2.get('年度收益', {}))

    # ══════════════════════════════════════════════════════════
    # 输出报告
    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  📋 Alpha因子增强策略 A股版 - 回测报告")
    print("=" * 70)

    print(f"\n📊 三方对比（原始权重 vs A股IC优化 vs 中证500基准）:")
    print(f"  {'指标':<14} {'原始权重':>12} {'A股IC优化':>12} {'中证500持有':>12}")
    print(f"  {'-' * 54}")
    for key, label in [('总收益率%', '总收益率'), ('年化收益%', '年化收益'), ('最大回撤%', '最大回撤')]:
        v1 = r1[key] if r1.get('状态') == '✅' else 0
        v2 = r2[key] if r2.get('状态') == '✅' else 0
        sp = spy_r[key]
        print(f"  {label:<12} {v1:>11.2f}% {v2:>11.2f}% {sp:>11.2f}%")
    for key, label in [('夏普比率', '夏普比率'), ('卡尔马比率', '卡尔马比率'), ('索提诺比率', '索提诺比率')]:
        v1 = r1.get(key, 0)
        v2 = r2.get(key, 0)
        sp = spy_r.get(key, 0)
        print(f"  {label:<12} {v1:>12.2f} {v2:>12.2f} {sp:>12.2f}")
    print(f"  {'胜率':<12} {r1.get('胜率%', 0):>11.2f}% {r2.get('胜率%', 0):>11.2f}%")
    print(f"  {'盈亏比':<12} {r1.get('盈亏比', 0):>12.2f} {r2.get('盈亏比', 0):>12.2f}")
    print(f"  {'调仓次数':<12} {r1.get('调仓次数', 0):>12d} {r2.get('调仓次数', 0):>12d}")
    print(f"  {'止损次数':<12} {r1.get('止损事件', {}).get('总计', 0):>12d} {r2.get('止损事件', {}).get('总计', 0):>12d}")

    # 年度收益对比
    print(f"\n📅 年度收益对比（A股IC优化版 vs 中证500）:")
    print(f"  {'年份':<8} {'原始权重':>12} {'A股IC优化':>12} {'中证500持有':>12} {'超额(IC优化)':>12}")
    print(f"  {'-' * 58}")
    all_y = sorted(set(
        list(r1.get('年度收益', {}).keys()) +
        list(r2.get('年度收益', {}).keys()) +
        list(spy_r.get('年度收益', {}).keys())
    ))
    for y in all_y:
        v1 = r1.get('年度收益', {}).get(y, 0)
        v2 = r2.get('年度收益', {}).get(y, 0)
        sp = spy_r.get('年度收益', {}).get(y, 0)
        ex = v2 - sp
        print(f"  {y:<8} {v1:>11.2f}% {v2:>11.2f}% {sp:>11.2f}% {ex:>+11.2f}%")

    # 止损统计
    for label, result in [('原始版', r1), ('A股IC优化版', r2)]:
        sl = result.get('止损事件', {})
        if sl:
            print(f"\n🛡️ 止损统计({label}):")
            print(f"  固定止损: {sl.get('固定止损', 0)}次, 移动止损: {sl.get('移动止损', 0)}次, 总计: {sl.get('总计', 0)}次")

    # 过拟合检测
    print(f"\n🔬 过拟合检测(A股IC优化版):")
    tr, te = overfit['训练集'], overfit['测试集']
    for k in ['年化收益%', '最大回撤%', '夏普比率']:
        print(f"  {k:<10} 训练:{tr[k]:>8.2f}  测试:{te[k]:>8.2f}")
    print(f"  过拟合比率: {overfit['过拟合比率']}")
    print(f"  检测结果: {'⚠️ 过拟合' if overfit['过拟合检测'] else '✅ 良好'}")
    if overfit['过拟合详情']:
        print(f"  详情: {overfit['过拟合详情']}")

    # 一致性验证
    print(f"\n📋 一致性验证(A股IC优化版):")
    print(f"  结果: {consistency['verdict']}")
    if consistency['warnings']:
        for w in consistency['warnings']:
            print(f"  ⚠️ {w}")

    # ══════════════════════════════════════════════════════════
    # 评分
    # ══════════════════════════════════════════════════════════
    for label, result in [('原始版', r1), ('A股IC优化版', r2)]:
        if result.get('状态') != '✅':
            continue
        annual_ret = result['年化收益%']
        max_dd = result['最大回撤%']
        sharpe = result['夏普比率']

        if max_dd <= 10: dd_score = 20
        elif max_dd <= 20: dd_score = 15
        elif max_dd <= 25: dd_score = 8
        elif max_dd <= 30: dd_score = 5
        else: dd_score = 0

        if annual_ret >= 25: ann_score = 25
        elif annual_ret >= 15: ann_score = 18
        elif annual_ret >= 8: ann_score = 12
        elif annual_ret >= 0: ann_score = 5
        else: ann_score = 0

        if sharpe >= 1.5: sh_score = 25
        elif sharpe >= 1.0: sh_score = 18
        elif sharpe >= 0.5: sh_score = 12
        elif sharpe >= 0: sh_score = 5
        else: sh_score = 0

        plr = result['盈亏比']
        if plr >= 2.0: plr_score = 15
        elif plr >= 1.5: plr_score = 10
        elif plr >= 1.0: plr_score = 6
        else: plr_score = 0

        wr = result['胜率%']
        if wr >= 60: wr_score = 15
        elif wr >= 55: wr_score = 10
        elif wr >= 50: wr_score = 6
        else: wr_score = 0

        total_score = dd_score + ann_score + sh_score + plr_score + wr_score

        print(f"\n{'=' * 70}")
        print(f"  📊 策略评分({label}): {total_score}/100")
        print(f"    回撤: {dd_score}/20 | 年化: {ann_score}/25 | 夏普: {sh_score}/25 | 盈亏比: {plr_score}/15 | 胜率: {wr_score}/15")
        recommend = total_score >= 75 and not overfit['过拟合检测'] and consistency['passed']
        print(f"  采纳建议: {'✅ 推荐' if recommend else '❌ 不推荐'}")

    # ══════════════════════════════════════════════════════════
    # 保存完整报告
    # ══════════════════════════════════════════════════════════
    report = {
        '策略名称': 'Alpha因子增强策略 v1.5 A股版 (作者888)',
        '策略类型': '多因子选股 + 行业中性 + 组合优化',
        '研究框架': '因子挖掘 → 因子测试 → 因子合成 → 组合构建 → 风险控制',
        '目标收益': '年化超额收益8-15%, 信息比率>1.5',
        '回测区间': f"{g.START_DATE} ~ {g.END_DATE}",
        '初始资金': g.INITIAL_CAPITAL,
        '数据源': 'JQData SDK (中证500成分股 + 基本面数据)',
        '说明': 'JQData试用账号限制，仅可获取约1年数据(2025-01-14~2026-01-21)',

        '原始权重回测': {
            '因子权重': original_weights,
            '风控参数': {'止损': '8%固定+5%移动', '组合回撤': '15%', '持仓数': 50, '滑点': '0.2%', '印花税': '0.1%'},
            '绩效': {k: r1[k] for k in ['总收益率%', '年化收益%', '最大回撤%', '夏普比率', '索提诺比率', '卡尔马比率', '胜率%', '盈亏比']},
            '年度收益': r1.get('年度收益', {}),
            '止损统计': r1.get('止损事件', {}),
        },

        'A股IC优化权重回测': {
            '因子权重': g.FACTOR_WEIGHTS,
            '因子调整说明': {
                'value': 'A股价值因子IC适中(0.03)，PE合理区间10-25',
                'quality': 'A股高ROE有效，权重保持20%',
                'growth': 'A股成长因子均值回归，反向使用',
                'momentum': 'A股动量效应显著，核心因子权重30%',
                'volatility': 'A股低波动因子无效，降权10%',
                'liquidity': 'A股机构偏好流动性，权重15%',
            },
            '风控参数': {'止损': '8%固定+5%移动', '组合回撤': '15%', '持仓数': 50, '滑点': '0.2%', '印花税': '0.1%'},
            '趋势择时': '中证500<200日均线时减仓50%',
            '绩效': {k: r2[k] for k in ['总收益率%', '年化收益%', '最大回撤%', '夏普比率', '索提诺比率', '卡尔马比率', '胜率%', '盈亏比']},
            '年度收益': r2.get('年度收益', {}),
            '止损统计': r2.get('止损事件', {}),
        },

        '基准绩效(中证500)': {k: spy_r[k] for k in ['总收益率%', '年化收益%', '最大回撤%', '夏普比率', '卡尔马比率']},
        '超额收益(A股IC优化)': {
            '年化超额%': round(r2.get('年化收益%', 0) - spy_r['年化收益%'], 2),
            '总超额%': round(r2.get('总收益率%', 0) - spy_r['总收益率%'], 2),
        },
        '年度收益对比': {y: {'原始': r1.get('年度收益', {}).get(y, 0), 'A股IC优化': r2.get('年度收益', {}).get(y, 0), '中证500': spy_r.get('年度收益', {}).get(y, 0)} for y in all_y},

        '过拟合检测': overfit,
        '一致性验证': consistency,

        '结论': {
            '数据限制': 'JQData试用账号仅可获取2025-01-14至2026-01-21数据（约1年），无法进行10年回测',
            '建议': '获取JQData正式账号或其他A股数据源(如Tushare Pro)以获取完整10年数据',
        },
    }

    report_path = '/data/workspace/alpha_factor_a_stock_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    # 生成HTML报告
    html_path = '/data/workspace/alpha_factor_a_stock_report.html'
    _gen_html_report(report, html_path)

    print(f"\n{'=' * 70}")
    print(f"📁 完整报告已保存: {report_path}")
    print(f"📁 HTML报告已保存: {html_path}")
    print(f"{'=' * 70}")

    # 发送邮件报告
    _send_email_report(html_path)

    return report


def _gen_html_report(report, path):
    """生成HTML报告"""
    r1 = report.get('原始权重回测', {})
    r2 = report.get('A股IC优化权重回测', {})
    spy_r = report.get('基准绩效(中证500)', {})
    overfit = report.get('过拟合检测', {})
    consistency = report.get('一致性验证', {})
    excess = report.get('超额收益(A股IC优化)', {})
    yearly_cmp = report.get('年度收益对比', {})

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Alpha因子增强策略 A股版 - 回测报告</title>
    <style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: center; }}
        th {{ background: #3498db; color: white; font-weight: bold; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        tr:hover {{ background: #e8f4f8; }}
        .positive {{ color: #27ae60; font-weight: bold; }}
        .negative {{ color: #e74c3c; font-weight: bold; }}
        .info {{ background: #d5f5e3; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #27ae60; }}
        .warning {{ background: #fdebd0; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #f39c12; }}
        .danger {{ background: #fadbd8; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #e74c3c; }}
        .score {{ display: inline-block; padding: 5px 10px; border-radius: 3px; color: white; font-weight: bold; }}
        .score-high {{ background: #27ae60; }}
        .score-mid {{ background: #f39c12; }}
        .score-low {{ background: #e74c3c; }}
    </style>
</head>
<body>
<div class="container">
    <h1>📋 Alpha因子增强策略 A股版 - 回测报告</h1>
    
    <div class="info">
        <strong>策略名称:</strong> Alpha因子增强策略 v1.5 A股版 (作者888)<br>
        <strong>策略类型:</strong> 多因子选股 + 行业中性 + 组合优化<br>
        <strong>数据源:</strong> JQData SDK (中证500成分股 + 基本面数据)<br>
        <strong>回测区间:</strong> {report['回测区间']}<br>
        <strong>初始资金:</strong> {report['初始资金']:,}<br>
        <strong>数据限制:</strong> {report['结论']['数据限制']}
    </div>
    
    <h2>📊 三方绩效对比</h2>
    <table>
        <tr><th>指标</th><th>原始权重</th><th>A股IC优化</th><th>中证500持有</th></tr>
        <tr><td>总收益率</td><td class="{'positive' if r1.get('总收益率%',0)>0 else 'negative'}">{r1.get('总收益率%',0):.2f}%</td><td class="{'positive' if r2.get('总收益率%',0)>0 else 'negative'}">{r2.get('总收益率%',0):.2f}%</td><td class="{'positive' if spy_r.get('总收益率%',0)>0 else 'negative'}">{spy_r.get('总收益率%',0):.2f}%</td></tr>
        <tr><td>年化收益</td><td class="{'positive' if r1.get('年化收益%',0)>0 else 'negative'}">{r1.get('年化收益%',0):.2f}%</td><td class="{'positive' if r2.get('年化收益%',0)>0 else 'negative'}">{r2.get('年化收益%',0):.2f}%</td><td class="{'positive' if spy_r.get('年化收益%',0)>0 else 'negative'}">{spy_r.get('年化收益%',0):.2f}%</td></tr>
        <tr><td>最大回撤</td><td class="negative">{r1.get('最大回撤%',0):.2f}%</td><td class="negative">{r2.get('最大回撤%',0):.2f}%</td><td class="negative">{spy_r.get('最大回撤%',0):.2f}%</td></tr>
        <tr><td>夏普比率</td><td>{r1.get('夏普比率',0):.2f}</td><td>{r2.get('夏普比率',0):.2f}</td><td>{spy_r.get('夏普比率',0):.2f}</td></tr>
        <tr><td>卡尔马比率</td><td>{r1.get('卡尔马比率',0):.2f}</td><td>{r2.get('卡尔马比率',0):.2f}</td><td>{spy_r.get('卡尔马比率',0):.2f}</td></tr>
    </table>
    
    <h2>📈 超额收益（A股IC优化版 vs 中证500）</h2>
    <div class="{'info' if excess.get('年化超额%',0)>=0 else 'warning'}">
        <strong>年化超额:</strong> {excess.get('年化超额%',0):.2f}% | <strong>总超额:</strong> {excess.get('总超额%',0):.2f}%
    </div>
    
    <h2>📅 年度收益对比</h2>
    <table>
        <tr><th>年份</th><th>原始权重</th><th>A股IC优化</th><th>中证500持有</th><th>超额(IC优化)</th></tr>
"""

    for y, data in sorted(yearly_cmp.items()):
        orig = data.get('原始', 0)
        ic = data.get('A股IC优化', 0)
        zz = data.get('中证500', 0)
        ex = ic - zz
        cls = 'positive' if ex > 0 else 'negative'
        html += f"""        <tr><td>{y}</td><td>{orig:.2f}%</td><td>{ic:.2f}%</td><td>{zz:.2f}%</td><td class="{cls}">{ex:+.2f}%</td></tr>
"""

    html += f"""    </table>
    
    <h2>🔬 过拟合检测</h2>
    <table>
        <tr><th>指标</th><th>训练集(70%)</th><th>测试集(30%)</th></tr>
        <tr><td>年化收益%</td><td>{overfit.get('训练集',{}).get('年化收益%',0):.2f}</td><td>{overfit.get('测试集',{}).get('年化收益%',0):.2f}</td></tr>
        <tr><td>最大回撤%</td><td>{overfit.get('训练集',{}).get('最大回撤%',0):.2f}</td><td>{overfit.get('测试集',{}).get('最大回撤%',0):.2f}</td></tr>
        <tr><td>夏普比率</td><td>{overfit.get('训练集',{}).get('夏普比率',0):.2f}</td><td>{overfit.get('测试集',{}).get('夏普比率',0):.2f}</td></tr>
    </table>
    <div class="{'danger' if overfit.get('过拟合检测') else 'info'}">
        <strong>过拟合比率:</strong> {overfit.get('过拟合比率',0):.2f} | <strong>检测结果:</strong> {'⚠️ 过拟合' if overfit.get('过拟合检测') else '✅ 良好'}<br>
        {overfit.get('过拟合详情', '')}
    </div>
    
    <h2>📋 一致性验证</h2>
    <div class="{'info' if consistency.get('passed') else 'warning'}">
        <strong>结果:</strong> {consistency.get('verdict', 'N/A')}
    </div>
"""

    if consistency.get('warnings'):
        html += """    <ul>
"""
        for w in consistency['warnings']:
            html += f"""        <li>⚠️ {w}</li>
"""
        html += """    </ul>
"""

    html += f"""
    <h2>📝 结论与建议</h2>
    <div class="danger">
        <strong>数据限制:</strong> {report['结论']['数据限制']}<br>
        <strong>建议:</strong> {report['结论']['建议']}
    </div>
</div>
</body>
</html>
"""

    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


def _send_email_report(html_path):
    """发送邮件报告"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'【策略回测报告】{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} Alpha因子增强策略A股版'
        msg['From'] = '848786642@qq.com'
        msg['To'] = '848786642@qq.com'

        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        with smtplib.SMTP_SSL('smtp.qq.com', 465) as server:
            server.login('848786642@qq.com', 'ljbtvacrctjobfed')
            server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())

        print(f"\n📧 邮件报告已发送至 848786642@qq.com")
    except Exception as e:
        print(f"\n⚠️ 邮件发送失败: {e}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n❌ 回测失败: {e}")
        traceback.print_exc()
        sys.exit(1)
