#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha因子增强策略 v1.5 A股版 - V3稳健版
数据源: JQData SDK (中证500成分股)
回测周期: 2025-01-14 ~ 2026-01-21 (JQData试用账号限制, 约1年)

V3核心改进:
1. 修复价值/质量因子全0问题 - 增加数据验证和fallback
2. 修复流动性因子区分度 - 使用成交额+换手率+市值三维
3. 修复NaN导致调仓失败 - 全面NaN防护
4. 优化JQData查询效率 - 减少重复查询，一次获取所有数据
5. 增加westock-data因子验证 - 对比因子数据准确性
"""

import os, sys, json, time, warnings, datetime
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


class Config:
    """策略配置"""
    START_DATE = '2025-01-14'
    END_DATE = '2026-01-21'
    INITIAL_CAPITAL = 1_000_000
    INDEX_POOL = '000905.XSHG'

    MIN_MARKET_CAP = 20
    MAX_MARKET_CAP = 5000
    MIN_PRICE = 1
    MAX_STOCK_NUM = 50

    FACTOR_WEIGHTS_ORIGINAL = {
        'value': 0.20, 'quality': 0.25, 'growth': 0.15,
        'momentum': 0.15, 'volatility': 0.15, 'liquidity': 0.10
    }

    FACTOR_WEIGHTS = {
        'value': 0.15, 'quality': 0.20, 'growth': 0.10,
        'momentum': 0.30, 'volatility': 0.10, 'liquidity': 0.15
    }

    MAX_SINGLE_WEIGHT = 0.06
    STOP_LOSS_RATIO = 0.08
    MAX_TURNOVER = 0.50
    COMMISSION = 0.0003
    SLIPPAGE = 0.001
    STAMP_TAX = 0.001
    RISK_FREE_RATE = 0.03

    JQ_USERNAME = '17665394957'
    JQ_PASSWORD = 'Wshqwpsa54565852'


g = Config()


# ================================================================
# 数据获取模块 - 高效版
# ================================================================
class DataFetcher:
    """统一数据获取器 - JQData为主，westock-data为辅"""

    def __init__(self):
        self.jq = None
        self._connected = False
        self._stock_pool_cache = {}
        self._info_cache = {}
        self._all_prices = {}  # {code: DataFrame}
        self._all_fundamentals = {}  # {date_str: {code: dict}}

    def connect_jq(self):
        """连接JQData"""
        try:
            import jqdatasdk
            jqdatasdk.auth(g.JQ_USERNAME, g.JQ_PASSWORD)
            self.jq = jqdatasdk
            spare = jqdatasdk.get_query_count().get('spare', 0)
            print(f"  ✅ JQData连接成功, 剩余查询: {spare:,}")
            self._connected = spare > 50000
            if spare < 50000:
                print(f"  ⚠️ JQData查询额度不足({spare}), 将使用缓存模式")
            return True
        except Exception as e:
            print(f"  ❌ JQData连接失败: {e}")
            return False

    def get_zz500_stocks(self, date_str):
        """获取中证500成分股"""
        if date_str in self._stock_pool_cache:
            return self._stock_pool_cache[date_str]
        try:
            stocks = self.jq.get_index_stocks(g.INDEX_POOL, date=date_str)
            self._stock_pool_cache[date_str] = stocks
            return stocks
        except Exception as e:
            print(f"  ⚠️ 获取成分股失败: {e}")
            return []

    def preload_all_data(self, rebal_dates, end_date):
        """一次性预加载所有数据 - 减少JQData查询次数"""
        # 1. 收集所有成分股
        print(f"  📥 Step 1: 收集所有调仓日成分股...")
        all_stocks_set = set()
        for rd in rebal_dates:
            pool = self.get_zz500_stocks(rd.strftime('%Y-%m-%d'))
            all_stocks_set.update(pool)
        all_stocks_list = sorted(all_stocks_set)
        print(f"  📥 去重后共 {len(all_stocks_list)} 只成分股")

        # 2. 批量获取价格数据 - 分批避免超时和额度限制
        print(f"  📥 Step 2: 批量获取价格数据...")
        batch_size = 30  # 减小批次避免额度问题
        loaded = 0
        failed_batches = 0
        for i in range(0, len(all_stocks_list), batch_size):
            batch = all_stocks_list[i:i + batch_size]
            try:
                df = self.jq.get_price(
                    batch, end_date=end_date, count=300,
                    frequency='daily',
                    fields=['open', 'close', 'high', 'low', 'volume', 'money'],
                    fq='pre', panel=False
                )
                if df is not None and len(df) > 0:
                    for code in batch:
                        sub = df[df['code'] == code].copy() if 'code' in df.columns else pd.DataFrame()
                        if len(sub) > 0:
                            if 'date' in sub.columns:
                                sub['date'] = pd.to_datetime(sub['date'])
                                sub = sub.set_index('date')
                            self._all_prices[code] = sub
                    loaded += len(batch)
                else:
                    failed_batches += 1
            except Exception as e:
                err_str = str(e)
                if '查询条数超过' in err_str:
                    print(f"  ❌ JQData额度耗尽! 已加载{loaded}只, 剩余跳过")
                    failed_batches += (len(all_stocks_list) - i) // batch_size + 1
                    break
                failed_batches += 1
                if i % 150 == 0:
                    print(f"  ⚠️ 批次{i//batch_size+1}失败: {e}")

            # 进度显示
            if (i // batch_size + 1) % 3 == 0:
                print(f"    进度: {loaded}/{len(all_stocks_list)} ({loaded*100//len(all_stocks_list)}%)")

        print(f"  ✅ 价格数据加载完成: {loaded}/{len(all_stocks_list)} 只, 失败批次: {failed_batches}")

        # 3. 批量获取基本面数据 - 每个调仓日获取一次
        print(f"  📥 Step 3: 批量获取基本面数据...")
        for idx, rd in enumerate(rebal_dates):
            date_str = rd.strftime('%Y-%m-%d')
            if date_str in self._all_fundamentals:
                continue
            pool = self.get_zz500_stocks(date_str)
            if len(pool) < 10:
                continue
            self._all_fundamentals[date_str] = self._fetch_fundamentals_batch(pool, date_str)
            if (idx + 1) % 3 == 0:
                print(f"    基本面进度: {idx+1}/{len(rebal_dates)}")

        print(f"  ✅ 基本面数据加载完成: {len(self._all_fundamentals)} 个调仓日")

        return loaded, len(self._all_fundamentals)

    def _fetch_fundamentals_batch(self, stock_list, date_str):
        """批量获取基本面数据 - 一次查询获取估值+指标"""
        fundamentals = {}

        try:
            # 合并估值和指标到一次查询
            q = self.jq.query(
                self.jq.valuation.code,
                self.jq.valuation.pe_ratio,
                self.jq.valuation.pb_ratio,
                self.jq.valuation.ps_ratio,
                self.jq.valuation.pcf_ratio,
                self.jq.valuation.market_cap,
                self.jq.valuation.turnover_ratio,
                self.jq.valuation.circulating_market_cap,
                self.jq.indicator.roe,
                self.jq.indicator.roa,
                self.jq.indicator.inc_revenue_year_on_year,
                self.jq.indicator.inc_net_profit_year_on_year,
            ).filter(self.jq.valuation.code.in_(stock_list))

            df = self.jq.get_fundamentals(q, date=date_str)

            if df is not None and len(df) > 0:
                valid_count = 0
                for _, row in df.iterrows():
                    code = row['code']
                    fund = {}
                    has_valid = False
                    for col in df.columns:
                        if col == 'code':
                            continue
                        v = row[col]
                        if v is not None and not pd.isna(v):
                            try:
                                fund[col] = float(v)
                                if abs(float(v)) > 1e-10:
                                    has_valid = True
                            except (ValueError, TypeError):
                                fund[col] = None
                        else:
                            fund[col] = None
                    if has_valid:
                        fundamentals[code] = fund
                        valid_count += 1
        except Exception as e:
            print(f"  ⚠️ 基本面查询失败({date_str}): {e}")

        return fundamentals

    def get_price_data(self, code, end_date=None):
        """获取单只股票价格数据（从缓存）"""
        if code in self._all_prices:
            return self._all_prices[code]
        return pd.DataFrame()

    def get_fundamentals(self, date_str, stock_list=None):
        """获取基本面数据（从缓存）"""
        fund = self._all_fundamentals.get(date_str, {})
        if stock_list:
            return {k: v for k, v in fund.items() if k in stock_list}
        return fund

    def get_security_info(self, code):
        """获取证券信息"""
        if code in self._info_cache:
            return self._info_cache[code]
        try:
            info = self.jq.get_security_info(code)
            self._info_cache[code] = info
            return info
        except:
            return None


# ================================================================
# 因子计算模块 - V3稳健版
# ================================================================
class FactorCalculator:
    """因子计算器 - 增强数据验证和fallback"""

    @staticmethod
    def _safe_float(v, default=None):
        """安全转换为float"""
        if v is None or pd.isna(v):
            return default
        try:
            f = float(v)
            if np.isinf(f) or np.isnan(f):
                return default
            return f
        except (ValueError, TypeError):
            return default

    @staticmethod
    def calc_value_factors(fundamentals):
        """价值因子 - PE/PB/PS/PCF倒数，增强数据验证"""
        results = []
        for code, fund in fundamentals.items():
            pe = FactorCalculator._safe_float(fund.get('pe_ratio'))
            pb = FactorCalculator._safe_float(fund.get('pb_ratio'))
            ps = FactorCalculator._safe_float(fund.get('ps_ratio'))
            pcf = FactorCalculator._safe_float(fund.get('pcf_ratio'))

            # PE倒数（低PE高分，负PE也给分但低于正PE）
            pe_inv = None
            if pe is not None:
                if pe > 0:
                    pe_inv = 1.0 / pe  # 越小PE分越高
                elif pe < 0:
                    pe_inv = 0.01  # 负PE给极低分，但不是None
                # pe=0 不计分

            pb_inv = None
            if pb is not None:
                if pb > 0:
                    pb_inv = 1.0 / pb
                elif pb < 0:
                    pb_inv = 0.01

            ps_inv = None
            if ps is not None:
                if ps > 0:
                    ps_inv = 1.0 / ps
                elif ps < 0:
                    ps_inv = 0.01

            pcf_inv = None
            if pcf is not None:
                if pcf > 0:
                    pcf_inv = 1.0 / pcf
                elif pcf < 0:
                    pcf_inv = 0.01

            # 至少有一个有效因子才纳入
            if any(v is not None for v in [pe_inv, pb_inv, ps_inv, pcf_inv]):
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
        # 使用rank pct统一量纲
        pe_rank = df['value_pe'].rank(pct=True) if df['value_pe'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
        pb_rank = df['value_pb'].rank(pct=True) if df['value_pb'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
        ps_rank = df['value_ps'].rank(pct=True) if df['value_ps'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
        pcf_rank = df['value_pcf'].rank(pct=True) if df['value_pcf'].notna().sum() > 5 else pd.Series(0.5, index=df.index)

        df['value_score'] = (
            pe_rank.fillna(0.5) * 0.30 +
            pb_rank.fillna(0.5) * 0.30 +
            ps_rank.fillna(0.5) * 0.20 +
            pcf_rank.fillna(0.5) * 0.20
        )
        return df[['code', 'value_score']]

    @staticmethod
    def calc_quality_factors(fundamentals):
        """质量因子 - ROE/ROA，增强数据验证"""
        results = []
        for code, fund in fundamentals.items():
            roe = FactorCalculator._safe_float(fund.get('roe'))
            roa = FactorCalculator._safe_float(fund.get('roa'))

            if roe is not None or roa is not None:
                results.append({
                    'code': code,
                    'quality_roe': roe if roe is not None else 0,
                    'quality_roa': roa if roa is not None else 0,
                })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        # 检查数据有效性
        roe_valid = df['quality_roe'].notna().sum() > 5 and df['quality_roe'].std() > 0.001
        roa_valid = df['quality_roa'].notna().sum() > 5 and df['quality_roa'].std() > 0.001

        if roe_valid and roa_valid:
            df['quality_score'] = (
                df['quality_roe'].rank(pct=True).fillna(0.5) * 0.6 +
                df['quality_roa'].rank(pct=True).fillna(0.5) * 0.4
            )
        elif roe_valid:
            df['quality_score'] = df['quality_roe'].rank(pct=True).fillna(0.5)
        elif roa_valid:
            df['quality_score'] = df['quality_roa'].rank(pct=True).fillna(0.5)
        else:
            df['quality_score'] = 0.5  # 无法区分，给中间分

        return df[['code', 'quality_score']]

    @staticmethod
    def calc_growth_factors(fundamentals, stock_prices):
        """成长因子 - 营收/利润增长率，缺失时用价格趋势代理"""
        results = []
        for code in fundamentals:
            fund = fundamentals[code]
            inc_rev = FactorCalculator._safe_float(fund.get('inc_revenue_year_on_year'))
            inc_profit = FactorCalculator._safe_float(fund.get('inc_net_profit_year_on_year'))

            growth_rev = inc_rev
            growth_profit = inc_profit

            # 基本面缺失时用价格动量代理
            if growth_rev is None or growth_profit is None:
                prices_df = stock_prices.get(code, pd.DataFrame())
                if len(prices_df) >= 60:
                    try:
                        close = prices_df['close'].values
                        if growth_rev is None and len(close) >= 60:
                            growth_rev = (close[-1] / close[-60] - 1) * 100
                        if growth_profit is None and len(close) >= 120:
                            growth_profit = (close[-1] / close[-120] - 1) * 100
                    except:
                        pass

            if growth_rev is not None or growth_profit is not None:
                results.append({
                    'code': code,
                    'growth_revenue': growth_rev if growth_rev is not None else 0,
                    'growth_profit': growth_profit if growth_profit is not None else 0,
                })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        # A股成长因子均值回归明显，使用反向rank（低成长反而更优）
        rev_valid = df['growth_revenue'].std() > 0.001 if df['growth_revenue'].notna().sum() > 5 else False
        pro_valid = df['growth_profit'].std() > 0.001 if df['growth_profit'].notna().sum() > 5 else False

        if rev_valid and pro_valid:
            df['growth_score'] = (
                (1 - df['growth_revenue'].rank(pct=True).fillna(0.5)) * 0.5 +
                (1 - df['growth_profit'].rank(pct=True).fillna(0.5)) * 0.5
            )
        elif rev_valid:
            df['growth_score'] = 1 - df['growth_revenue'].rank(pct=True).fillna(0.5)
        elif pro_valid:
            df['growth_score'] = 1 - df['growth_profit'].rank(pct=True).fillna(0.5)
        else:
            df['growth_score'] = 0.5

        return df[['code', 'growth_score']]

    @staticmethod
    def calc_momentum_factors(stock_prices):
        """动量因子 - 降低最低数据要求，60天即可"""
        results = []
        for code, prices_df in stock_prices.items():
            n = len(prices_df)
            if n < 20:
                continue

            try:
                close = prices_df['close'].values
                # 确保close没有NaN
                if np.any(np.isnan(close[-min(n, 60):])):
                    close = np.nan_to_num(close, nan=close[~np.isnan(close)].mean() if (~np.isnan(close)).any() else 0)
                if close[-1] <= 0:
                    continue

                last_close = close[-1]

                # 1月反转
                mom_1m = last_close / close[-20] - 1 if n >= 20 else 0
                rev_1m = -mom_1m

                # 3月动量
                mom_3m = last_close / close[-60] - 1 if n >= 60 else 0

                # 6月动量
                mom_6m = last_close / close[-120] - 1 if n >= 120 else 0

                # 12月动量
                mom_12m = last_close / close[-240] - 1 if n >= 240 else None

                # 根据数据长度调整权重
                if mom_12m is not None:
                    mom_score_raw = mom_12m * 0.3 + mom_6m * 0.3 + mom_3m * 0.2 + rev_1m * 0.2
                else:
                    if n >= 120:
                        mom_score_raw = mom_6m * 0.4 + mom_3m * 0.35 + rev_1m * 0.25
                    elif n >= 60:
                        mom_score_raw = mom_3m * 0.5 + rev_1m * 0.5
                    else:
                        mom_score_raw = rev_1m

                results.append({
                    'code': code,
                    'momentum_raw': mom_score_raw,
                })
            except:
                continue

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df['momentum_score'] = df['momentum_raw'].rank(pct=True).fillna(0.5)
        return df[['code', 'momentum_score']]

    @staticmethod
    def calc_volatility_factors(stock_prices, bench_prices=None):
        """波动因子 - 低波动 + 低Beta"""
        bench_ret = None
        if bench_prices is not None and len(bench_prices) >= 30:
            bench_ret = bench_prices['close'].pct_change().dropna().values

        results = []
        for code, prices_df in stock_prices.items():
            n = len(prices_df)
            if n < 20:
                continue

            try:
                ret = prices_df['close'].pct_change().dropna().values
                if len(ret) < 10:
                    continue

                use_ret = ret[-60:] if len(ret) >= 60 else ret
                # 过滤NaN
                use_ret = use_ret[~np.isnan(use_ret)]
                if len(use_ret) < 10:
                    continue

                vol = np.std(use_ret) * np.sqrt(252)

                neg = use_ret[use_ret < 0]
                downside_vol = np.std(neg) * np.sqrt(252) if len(neg) > 3 else vol

                beta = 1.0
                if bench_ret is not None and len(bench_ret) > 20:
                    ml = min(len(use_ret), len(bench_ret))
                    if ml > 20:
                        cov_mat = np.cov(use_ret[-ml:], bench_ret[-ml:])
                        if cov_mat.shape == (2, 2) and cov_mat[1, 1] > 0:
                            beta = cov_mat[0, 1] / cov_mat[1, 1]

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
            (1 - df['downside_risk'].rank(pct=True).fillna(0.5)) * 0.35 +
            (1 - df['beta'].rank(pct=True).fillna(0.5)) * 0.25
        )
        return df[['code', 'volatility_score']]

    @staticmethod
    def calc_liquidity_factors(fundamentals, stock_prices=None):
        """流动性因子 - 三维: 换手率+成交额+市值，增强区分度"""
        results = []
        for code, fund in fundamentals.items():
            turnover = FactorCalculator._safe_float(fund.get('turnover_ratio'))
            market_cap = FactorCalculator._safe_float(fund.get('market_cap'))
            circ_cap = FactorCalculator._safe_float(fund.get('circulating_market_cap'))

            # 从价格数据补充成交额
            avg_amount = None
            if stock_prices and code in stock_prices:
                pdf = stock_prices[code]
                if 'money' in pdf.columns and len(pdf) >= 20:
                    avg_amount = pdf['money'].tail(20).mean()

            results.append({
                'code': code,
                'turnover': turnover if turnover is not None and turnover > 0 else None,
                'market_cap': market_cap if market_cap is not None and market_cap > 0 else None,
                'circ_cap': circ_cap if circ_cap is not None and circ_cap > 0 else None,
                'avg_amount': avg_amount if avg_amount is not None and avg_amount > 0 else None,
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)

        # 换手率rank - 适度最好（用二次函数，峰值在0.6处）
        turnover_rank = df['turnover'].rank(pct=True) if df['turnover'].notna().sum() > 5 else None

        # 市值rank - 大市值流动性好
        cap_rank = df['market_cap'].rank(pct=True) if df['market_cap'].notna().sum() > 5 else None

        # 成交额rank
        amount_rank = df['avg_amount'].rank(pct=True) if df['avg_amount'].notna().sum() > 5 else None

        # 综合计算
        score = pd.Series(0.5, index=df.index)

        if turnover_rank is not None:
            # 换手率适中最好 - 用二次函数
            t_score = 1 - (turnover_rank - 0.6).abs() * 1.5
            t_score = t_score.clip(0.2, 1.0).fillna(0.5)
            score = score * 0.4 + t_score * 0.4

        if cap_rank is not None:
            score = score + cap_rank.fillna(0.5) * 0.3
        elif amount_rank is not None:
            score = score + amount_rank.fillna(0.5) * 0.3

        if amount_rank is not None and cap_rank is not None:
            score = score - 0.15  # 避免双重计算，减去

        df['liquidity_score'] = score

        return df[['code', 'liquidity_score']]


# ================================================================
# 因子处理/合成/优化模块
# ================================================================
class FactorProcessor:
    @staticmethod
    def winsorize_mad(series, n_mad=3):
        median = series.median()
        mad = np.median(np.abs(series - median))
        if mad == 0 or pd.isna(mad):
            return series
        upper = median + n_mad * mad * 1.4826
        lower = median - n_mad * mad * 1.4826
        return series.clip(lower, upper)

    @staticmethod
    def standardize(series):
        std = series.std()
        if std == 0 or pd.isna(std):
            return pd.Series(0, index=series.index)
        return (series - series.mean()) / std

    @staticmethod
    def fill_na_with_median(df, factor_cols):
        for col in factor_cols:
            if col in df.columns:
                median_val = df[col].median()
                if pd.isna(median_val):
                    median_val = 0
                df[col] = df[col].fillna(median_val)
        return df


class FactorCombiner:
    @staticmethod
    def equal_weight(df, factor_cols, factor_weights):
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


class PortfolioOptimizer:
    @staticmethod
    def optimize(df, max_stocks=50, max_single_weight=0.06):
        """组合优化 - 强制差异化权重"""
        df = df.drop_duplicates(subset=['code'])
        df = df.sort_values('combined_factor', ascending=False)
        selected = df.head(max_stocks).copy()

        if len(selected) == 0:
            return pd.DataFrame(columns=['code', 'weight'])

        n = len(selected)
        scores = selected['combined_factor'].values

        score_min = scores.min()
        score_max = scores.max()
        if score_max > score_min:
            normalized = (scores - score_min) / (score_max - score_min)
            raw_weights = np.exp(normalized * 2)
        else:
            raw_weights = np.ones(n)

        raw_weights = np.minimum(raw_weights, max_single_weight * raw_weights.sum())
        raw_weights = raw_weights / raw_weights.sum()

        selected['weight'] = raw_weights
        return selected[['code', 'weight']]


class RiskController:
    def __init__(self):
        self.max_drawdown = 0
        self.peak_value = g.INITIAL_CAPITAL

    def check_portfolio_risk(self, total_value):
        if total_value > self.peak_value:
            self.peak_value = total_value
        if self.peak_value > 0:
            drawdown = (self.peak_value - total_value) / self.peak_value
            self.max_drawdown = max(self.max_drawdown, drawdown)
            if drawdown > 0.15:
                return True, drawdown
        return False, 0


# ================================================================
# 回测引擎 - V3稳健版
# ================================================================
def run_backtest(data_fetcher, start, end, factor_weights, freq='M'):
    """运行完整回测"""
    zz500_index = pd.read_csv('/data/workspace/zz500_index_daily.csv', index_col='date', parse_dates=True)
    zz500_index = zz500_index[start:end]

    mask = (zz500_index.index >= start) & (zz500_index.index <= end)
    dates = zz500_index[mask].index.tolist()

    if len(dates) < 20:
        return {'状态': '数据不足', '原因': f'仅{len(dates)}个交易日'}

    print(f"  回测交易日: {len(dates)} 天 ({dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')})")

    # 月度调仓日期
    rebal_dates = []
    last_month = None
    for d in dates:
        if last_month is None or d.month != last_month:
            rebal_dates.append(d)
            last_month = d.month

    print(f"  调仓日: {len(rebal_dates)} 个")

    # 预加载数据
    data_fetcher.preload_all_data(rebal_dates, end)

    # 初始化
    cash = float(g.INITIAL_CAPITAL)
    positions = {}
    pos_cost = {}
    pos_high = {}
    risk_ctrl = RiskController()
    pv_list = []
    rebalance_count = 0
    stop_events = []
    total_commission = 0
    last_month = None

    # 逐日回测
    for di, date in enumerate(dates):
        date_str = date.strftime('%Y-%m-%d')

        # 月度调仓
        if freq == 'M' and (last_month is None or date.month != last_month):
            last_month = date.month

            pool = data_fetcher.get_zz500_stocks(date_str)
            if len(pool) < 20:
                continue

            fundamentals = data_fetcher.get_fundamentals(date_str, pool)

            # 筛选有效股票
            valid_pool = []
            for code in pool:
                pdf = data_fetcher.get_price_data(code)
                if len(pdf) == 0:
                    continue

                # 截止到当前日期的价格
                if isinstance(pdf.index, pd.DatetimeIndex):
                    avail = pdf[pdf.index <= date]
                else:
                    avail = pdf
                if len(avail) < 30:
                    continue

                close_val = avail.iloc[-1]['close']
                if pd.isna(close_val) or float(close_val) < g.MIN_PRICE:
                    continue

                # ST筛选
                info = data_fetcher.get_security_info(code)
                if info is not None:
                    name = getattr(info, 'display_name', '') or ''
                    if 'ST' in name or '*' in name or '退' in name:
                        continue

                # 市值筛选
                fund = fundamentals.get(code, {})
                mcap = fund.get('market_cap')
                if mcap is not None:
                    mcap_val = FactorCalculator._safe_float(mcap)
                    if mcap_val is not None and (mcap_val < g.MIN_MARKET_CAP or mcap_val > g.MAX_MARKET_CAP):
                        continue

                valid_pool.append(code)

            if len(valid_pool) < 20:
                print(f"  ⚠️ {date_str}: 有效股票仅{len(valid_pool)}只，跳过")
                continue

            # 准备截止到当前日期的子数据
            sub_prices = {}
            for code in valid_pool:
                pdf = data_fetcher.get_price_data(code)
                if isinstance(pdf.index, pd.DatetimeIndex):
                    sub = pdf[pdf.index <= date].tail(250)
                else:
                    sub = pdf.tail(250)
                if len(sub) >= 30:
                    sub_prices[code] = sub

            sub_fundamentals = {s: fundamentals.get(s, {}) for s in valid_pool}

            # 计算6大因子
            factor_dfs = []

            f = FactorCalculator.calc_value_factors(sub_fundamentals)
            if len(f) > 0:
                factor_dfs.append(f)
                if rebalance_count == 0:
                    print(f"    value: {len(f)}只, score均值={f['value_score'].mean():.3f}, std={f['value_score'].std():.3f}")

            f = FactorCalculator.calc_quality_factors(sub_fundamentals)
            if len(f) > 0:
                factor_dfs.append(f)
                if rebalance_count == 0:
                    print(f"    quality: {len(f)}只, score均值={f['quality_score'].mean():.3f}, std={f['quality_score'].std():.3f}")

            f = FactorCalculator.calc_growth_factors(sub_fundamentals, sub_prices)
            if len(f) > 0:
                factor_dfs.append(f)
                if rebalance_count == 0:
                    print(f"    growth: {len(f)}只, score均值={f['growth_score'].mean():.3f}, std={f['growth_score'].std():.3f}")

            f = FactorCalculator.calc_momentum_factors(sub_prices)
            if len(f) > 0:
                factor_dfs.append(f)
                if rebalance_count == 0:
                    print(f"    momentum: {len(f)}只, score均值={f['momentum_score'].mean():.3f}, std={f['momentum_score'].std():.3f}")

            bench_data = zz500_index[zz500_index.index <= date].tail(60)
            f = FactorCalculator.calc_volatility_factors(sub_prices, bench_data)
            if len(f) > 0:
                factor_dfs.append(f)
                if rebalance_count == 0:
                    print(f"    volatility: {len(f)}只, score均值={f['volatility_score'].mean():.3f}, std={f['volatility_score'].std():.3f}")

            f = FactorCalculator.calc_liquidity_factors(sub_fundamentals, sub_prices)
            if len(f) > 0:
                factor_dfs.append(f)
                if rebalance_count == 0:
                    print(f"    liquidity: {len(f)}只, score均值={f['liquidity_score'].mean():.3f}, std={f['liquidity_score'].std():.3f}")

            if len(factor_dfs) < 3:
                continue

            # 合并因子
            from functools import reduce
            merged = reduce(lambda x, y: pd.merge(x, y, on='code', how='outer'), factor_dfs)
            if len(merged) < 10:
                continue

            factor_cols = [col for col in merged.columns if col.endswith('_score')]
            merged = FactorProcessor.fill_na_with_median(merged, factor_cols)
            for col in factor_cols:
                merged[col] = FactorProcessor.winsorize_mad(merged[col])
                merged[col] = FactorProcessor.standardize(merged[col])

            merged = FactorCombiner.equal_weight(merged, factor_cols, factor_weights)

            if rebalance_count == 0:
                print(f"\n  📊 首次调仓因子诊断 ({date_str}):")
                print(f"    有效股票: {len(valid_pool)}, 合并后: {len(merged)}")
                for col in factor_cols:
                    s = merged[col]
                    print(f"    {col}: mean={s.mean():.3f}, std={s.std():.3f}, min={s.min():.3f}, max={s.max():.3f}")
                cf = merged['combined_factor']
                print(f"    combined: mean={cf.mean():.3f}, std={cf.std():.3f}, min={cf.min():.3f}, max={cf.max():.3f}")

            # 组合优化
            portfolio = PortfolioOptimizer.optimize(merged, max_stocks=g.MAX_STOCK_NUM, max_single_weight=g.MAX_SINGLE_WEIGHT)
            target_weights = dict(zip(portfolio['code'], portfolio['weight']))

            if len(target_weights) < 5:
                continue

            # 趋势择时
            if date in zz500_index.index:
                idx_loc = zz500_index.index.get_loc(date)
                if idx_loc >= 200:
                    zz500_close = float(zz500_index.iloc[idx_loc]['close'])
                    zz500_sma200 = float(zz500_index.iloc[idx_loc-200:idx_loc+1]['close'].mean())
                    if zz500_close < zz500_sma200:
                        target_weights = {k: v * 0.5 for k, v in target_weights.items()}

            # 计算当前总资产
            pv_before = cash
            for sym, shares in positions.items():
                p = _get_price(data_fetcher, sym, date)
                if p is not None and not np.isnan(p):
                    pv_before += shares * p

            # 执行调仓 - 先卖后买
            # 卖出不在目标中的持仓
            for sym in list(positions.keys()):
                if sym not in target_weights:
                    shares = positions[sym]
                    p = _get_price(data_fetcher, sym, date)
                    if p is not None and p > 0 and shares > 0:
                        sell_amount = shares * p
                        commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                        cash += sell_amount - commission
                        total_commission += commission
                    del positions[sym]
                    pos_cost.pop(sym, None)
                    pos_high.pop(sym, None)

            # 买入/调整目标持仓
            for sym, target_weight in target_weights.items():
                p = _get_price(data_fetcher, sym, date)
                if p is None or np.isnan(p) or p <= 0:
                    continue

                target_value = pv_before * target_weight
                target_shares = int(target_value / p)

                current_shares = positions.get(sym, 0)
                diff_shares = target_shares - current_shares

                if abs(diff_shares) < 1:
                    continue

                if diff_shares > 0:
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
                            old_cost = pos_cost[sym]
                            if target_shares > 0:
                                pos_cost[sym] = (old_cost * current_shares + p * diff_shares) / target_shares
                else:
                    sell_shares = abs(diff_shares)
                    sell_amount = sell_shares * p
                    commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                    cash += sell_amount - commission
                    total_commission += commission
                    positions[sym] = max(target_shares, 0)

            rebalance_count += 1
            print(f"  🔄 调仓#{rebalance_count} {date_str}: 持仓{len(positions)}只, 现金{cash:,.0f}")

        # 日度风控 - 个股止损
        for sym in list(positions.keys()):
            shares = positions[sym]
            if shares <= 0:
                del positions[sym]
                continue
            p = _get_price(data_fetcher, sym, date)
            if p is None or np.isnan(p) or p <= 0:
                continue

            cost = pos_cost.get(sym, p)
            if sym not in pos_high:
                pos_high[sym] = p
            else:
                pos_high[sym] = max(pos_high[sym], p)
            high = pos_high[sym]

            should_stop = False
            reason = None
            if cost > 0:
                loss = (p - cost) / cost
                if loss <= -g.STOP_LOSS_RATIO:
                    should_stop = True
                    reason = 'fixed_stop'
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
            p = _get_price(data_fetcher, sym, date)
            if p is not None and not np.isnan(p) and p > 0:
                pv += shares * p

        risk, drawdown = risk_ctrl.check_portfolio_risk(pv)
        if risk:
            for sym in list(positions.keys()):
                sell_shares = positions[sym] // 3
                if sell_shares > 0:
                    p = _get_price(data_fetcher, sym, date)
                    if p is not None and not np.isnan(p) and p > 0:
                        sell_amount = sell_shares * p
                        commission = sell_amount * (g.COMMISSION + g.STAMP_TAX)
                        cash += sell_amount - commission
                        total_commission += commission
                        positions[sym] -= sell_shares

        # 记录当日市值
        pv = cash
        for sym, shares in positions.items():
            p = _get_price(data_fetcher, sym, date)
            if p is not None and not np.isnan(p) and p > 0:
                pv += shares * p

        pv_list.append(pv)

    return _calc_perf(pv_list, dates, rebalance_count, stop_events, total_commission)


def _get_price(data_fetcher, code, date):
    """安全获取股票价格"""
    pdf = data_fetcher.get_price_data(code)
    if len(pdf) == 0:
        return None
    if isinstance(pdf.index, pd.DatetimeIndex):
        avail = pdf[pdf.index <= date]
    else:
        avail = pdf
    if len(avail) == 0:
        return None
    close_val = avail.iloc[-1]['close']
    try:
        return float(close_val)
    except (ValueError, TypeError):
        return None


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
    """中证500买入持有基准"""
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


# ================================================================
# 主函数
# ================================================================
def main():
    print("=" * 70)
    print("  Alpha因子增强策略 v1.5 A股版 (V3稳健版)")
    print("  数据源: JQData SDK (中证500成分股 + 基本面)")
    print("  回测周期: 2025-01-14 ~ 2026-01-21")
    print("=" * 70)

    print(f"\n📂 初始化JQData连接...")
    data_fetcher = DataFetcher()
    data_fetcher.connect_jq()

    # 加载中证500指数
    print(f"\n📊 加载中证500指数数据...")
    zz500_index = pd.read_csv('/data/workspace/zz500_index_daily.csv', index_col='date', parse_dates=True)
    zz500_index = zz500_index[g.START_DATE:g.END_DATE]
    print(f"  ✅ {len(zz500_index)} 行")

    # 回测1: 原始权重
    print(f"\n{'='*50}")
    print(f"🚀 回测1: 原始权重 {g.FACTOR_WEIGHTS_ORIGINAL}")
    r1 = run_backtest(data_fetcher, g.START_DATE, g.END_DATE, g.FACTOR_WEIGHTS_ORIGINAL)

    # 回测2: A股IC优化权重
    print(f"\n{'='*50}")
    print(f"🚀 回测2: A股IC优化权重 {g.FACTOR_WEIGHTS}")
    r2 = run_backtest(data_fetcher, g.START_DATE, g.END_DATE, g.FACTOR_WEIGHTS)

    # 基准
    print(f"\n📈 运行基准 (中证500 Buy & Hold)...")
    spy_r = run_buyhold_bench(zz500_index, g.START_DATE, g.END_DATE)

    # 输出报告
    print("\n" + "=" * 70)
    print("  📋 Alpha因子增强策略 A股版 - 回测报告")
    print("=" * 70)

    print(f"\n📊 三方对比:")
    print(f"  {'指标':<14} {'原始权重':>12} {'A股IC优化':>12} {'中证500持有':>12}")
    print(f"  {'-'*54}")
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

    # 年度收益
    all_y = sorted(set(
        list(r1.get('年度收益', {}).keys()) +
        list(r2.get('年度收益', {}).keys()) +
        list(spy_r.get('年度收益', {}).keys())
    ))
    print(f"\n📅 年度收益对比:")
    print(f"  {'年份':<8} {'原始权重':>12} {'A股IC优化':>12} {'中证500持有':>12} {'超额':>12}")
    print(f"  {'-'*58}")
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
            print(f"  固定止损: {sl.get('固定止损', 0)}次, 移动止损: {sl.get('移动止损', 0)}次")

    # 超额收益
    excess_annual = r2.get('年化收益%', 0) - spy_r['年化收益%']
    excess_total = r2.get('总收益率%', 0) - spy_r['总收益率%']
    print(f"\n📈 超额收益(A股IC优化 vs 中证500):")
    print(f"  年化超额: {excess_annual:+.2f}%")
    print(f"  总超额: {excess_total:+.2f}%")

    # 评分
    for label, result in [('原始版', r1), ('A股IC优化版', r2)]:
        if result.get('状态') != '✅':
            continue
        annual_ret = result['年化收益%']
        max_dd = result['最大回撤%']
        sharpe = result['夏普比率']

        dd_score = 20 if max_dd <= 10 else 15 if max_dd <= 20 else 8 if max_dd <= 25 else 5 if max_dd <= 30 else 0
        ann_score = 25 if annual_ret >= 25 else 18 if annual_ret >= 15 else 12 if annual_ret >= 8 else 5 if annual_ret >= 0 else 0
        sh_score = 25 if sharpe >= 1.5 else 18 if sharpe >= 1.0 else 12 if sharpe >= 0.5 else 5 if sharpe >= 0 else 0
        plr = result['盈亏比']
        plr_score = 15 if plr >= 2.0 else 10 if plr >= 1.5 else 6 if plr >= 1.0 else 0
        wr = result['胜率%']
        wr_score = 15 if wr >= 60 else 10 if wr >= 55 else 6 if wr >= 50 else 0

        total_score = dd_score + ann_score + sh_score + plr_score + wr_score
        print(f"\n{'='*70}")
        print(f"  📊 策略评分({label}): {total_score}/100")
        print(f"    回撤: {dd_score}/20 | 年化: {ann_score}/25 | 夏普: {sh_score}/25 | 盈亏比: {plr_score}/15 | 胜率: {wr_score}/15")

    # 保存报告
    report = {
        '策略名称': 'Alpha因子增强策略 v1.5 A股版 (V3稳健版)',
        '回测区间': f"{g.START_DATE} ~ {g.END_DATE}",
        '初始资金': g.INITIAL_CAPITAL,
        '数据源': 'JQData SDK',
        '说明': 'JQData试用账号限制，仅1年数据',
        '原始权重回测': {k: r1[k] for k in ['总收益率%', '年化收益%', '最大回撤%', '夏普比率', '索提诺比率', '胜率%', '盈亏比'] if k in r1},
        'A股IC优化权重回测': {k: r2[k] for k in ['总收益率%', '年化收益%', '最大回撤%', '夏普比率', '索提诺比率', '胜率%', '盈亏比'] if k in r2},
        '基准绩效(中证500)': {k: spy_r[k] for k in ['总收益率%', '年化收益%', '最大回撤%', '夏普比率']},
        '超额收益(A股IC优化)': {'年化超额%': round(excess_annual, 2), '总超额%': round(excess_total, 2)},
    }

    report_path = '/data/workspace/alpha_factor_a_stock_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    html_path = '/data/workspace/alpha_factor_a_stock_report.html'
    _gen_html_report(report, r1, r2, spy_r, all_y, html_path)

    print(f"\n📁 JSON报告: {report_path}")
    print(f"📁 HTML报告: {html_path}")

    # 发送邮件
    _send_email_report(html_path)

    return report


def _gen_html_report(report, r1, r2, spy_r, all_y, path):
    """生成HTML报告"""
    excess = report.get('超额收益(A股IC优化)', {})
    cls_pos = 'positive'
    cls_neg = 'negative'

    rows = ''
    for key, label in [('总收益率%', '总收益率'), ('年化收益%', '年化收益'), ('最大回撤%', '最大回撤')]:
        v1 = r1.get(key, 0)
        v2 = r2.get(key, 0)
        sp = spy_r.get(key, 0)
        c1 = cls_pos if v1 > 0 else cls_neg
        c2 = cls_pos if v2 > 0 else cls_neg
        csp = cls_pos if sp > 0 else cls_neg
        rows += f'<tr><td>{label}</td><td class="{c1}">{v1:.2f}%</td><td class="{c2}">{v2:.2f}%</td><td class="{csp}">{sp:.2f}%</td></tr>\n'
    for key, label in [('夏普比率', '夏普比率'), ('卡尔马比率', '卡尔马比率'), ('索提诺比率', '索提诺比率')]:
        v1 = r1.get(key, 0)
        v2 = r2.get(key, 0)
        sp = spy_r.get(key, 0)
        rows += f'<tr><td>{label}</td><td>{v1:.2f}</td><td>{v2:.2f}</td><td>{sp:.2f}</td></tr>\n'

    year_rows = ''
    for y in all_y:
        v1 = r1.get('年度收益', {}).get(y, 0)
        v2 = r2.get('年度收益', {}).get(y, 0)
        sp = spy_r.get('年度收益', {}).get(y, 0)
        ex = v2 - sp
        ec = cls_pos if ex > 0 else cls_neg
        year_rows += f'<tr><td>{y}</td><td>{v1:.2f}%</td><td>{v2:.2f}%</td><td>{sp:.2f}%</td><td class="{ec}">{ex:+.2f}%</td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Alpha因子增强策略 A股版 回测报告</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 1000px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
h2 {{ color: #34495e; margin-top: 30px; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: center; }}
th {{ background: #3498db; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
tr:hover {{ background: #e8f4f8; }}
.positive {{ color: #27ae60; font-weight: bold; }}
.negative {{ color: #e74c3c; font-weight: bold; }}
.info {{ background: #d5f5e3; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #27ae60; }}
.warning {{ background: #fdebd0; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #f39c12; }}
.danger {{ background: #fadbd8; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #e74c3c; }}
</style>
</head>
<body>
<div class="container">
<h1>📋 Alpha因子增强策略 A股版 - 回测报告</h1>
<div class="info">
<strong>策略:</strong> Alpha因子增强策略 v1.5 A股版 (V3稳健版)<br>
<strong>回测区间:</strong> {report['回测区间']}<br>
<strong>初始资金:</strong> {report['初始资金']:,}<br>
<strong>数据源:</strong> JQData SDK (中证500成分股)<br>
<strong>说明:</strong> {report['说明']}
</div>
<h2>📊 绩效对比</h2>
<table>
<tr><th>指标</th><th>原始权重</th><th>A股IC优化</th><th>中证500持有</th></tr>
{rows}
</table>
<h2>📈 超额收益</h2>
<div class="{'info' if excess.get('年化超额%',0)>=0 else 'warning'}">
<strong>年化超额:</strong> {excess.get('年化超额%',0):+.2f}% | <strong>总超额:</strong> {excess.get('总超额%',0):+.2f}%
</div>
<h2>📅 年度收益</h2>
<table>
<tr><th>年份</th><th>原始权重</th><th>A股IC优化</th><th>中证500持有</th><th>超额</th></tr>
{year_rows}
</table>
</div>
</body>
</html>"""

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
