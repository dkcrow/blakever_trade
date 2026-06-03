#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
七星策略共享基础模块
==========================================================================
提供所有七星系列策略共用的基础设施:
- ETF池 & ETF名称映射
- 本地CSV数据源 (LocalDataSource)
- 投资组合管理 (Portfolio)
==========================================================================
"""

import os
import math
import numpy as np
import pandas as pd
from pathlib import Path

# ================================================================
# 📊 ETF池配置 (与聚宽原版完全一致)
# ================================================================
ETF_POOL = [
    # 大宗商品ETF
    "sh518880", "sz159980", "sz159985", "sh501018", "sz161226", "sz159981",
    # 国际ETF
    "sh513100", "sz159509", "sh513290", "sh513500", "sz159529",
    "sh513400", "sh513520", "sh513030", "sh513080", "sh513310", "sh513730",
    # 香港ETF
    "sz159792", "sh513130", "sh513050", "sz159920", "sh513690",
    # 指数ETF
    "sh510300", "sh510500", "sh510050", "sh510210", "sz159915",
    "sh588080", "sh512100", "sh563360", "sh563300",
    # 风格ETF
    "sh512890", "sz159967", "sh512040", "sz159201", "sh562500", "sh560090",
    # 债券ETF
    "sh511380", "sh511010", "sz511220",
]

ETF_NAMES = {
    'sh518880': '黄金ETF华安',   'sz159980': '有色ETF大成',
    'sz159985': '豆粕ETF华夏',   'sh501018': '南方原油LOF',
    'sz161226': '白银LOF国投',   'sz159981': '能源化工ETF建信',
    'sh513100': '纳指ETF国泰',   'sz159509': '纳指科技ETF景顺',
    'sh513290': '纳指生物科技ETF汇添富', 'sh513500': '标普500ETF博时',
    'sz159529': '标普消费ETF景顺','sh513400': '道琼斯ETF鹏华',
    'sh513520': '日经ETF华夏',    'sh513030': '德国ETF华安',
    'sh513080': '法国ETF华安',    'sh513310': '中韩半导体ETF华泰柏瑞',
    'sh513730': '东南亚科技ETF华泰柏瑞',
    'sz159792': '港股通互联网ETF富国', 'sh513130': '恒生科技ETF华泰柏瑞',
    'sh513050': '中概互联网ETF易方达', 'sz159920': '恒生ETF华夏',
    'sh513690': '港股红利ETF博时', 'sh510300': '沪深300ETF华泰柏瑞',
    'sh510500': '中证500ETF南方',  'sh510050': '上证50ETF华夏',
    'sh510210': '上证指数ETF富国', 'sz159915': '创业板ETF易方达',
    'sh588080': '科创50ETF易方达', 'sh512100': '中证1000ETF南方',
    'sh563360': 'A500ETF华泰柏瑞',  'sh563300': '中证2000ETF华泰柏瑞',
    'sh512890': '红利低波ETF华泰柏瑞', 'sz159967': '创业板成长ETF华夏',
    'sh512040': '价值100ETF富国',   'sz159201': '自由现金流ETF华夏',
    'sh562500': '机器人ETF华夏',    'sh560090': '证券ETF560090',
    'sh511380': '可转债ETF博时',    'sh511010': '国债ETF国泰',
    'sz511220': '城投债ETF海富通',
    'sh511880': '银华日利(货币基金)',
}

DEFENSIVE_ETF = "sh511880"  # 银华日利(货币基金)

# 默认数据目录
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / 'data' / 'storage' / 'stock_data' / 'etf'
DEFAULT_NAV_DIR = Path(__file__).parent.parent.parent / 'data' / 'storage' / 'stock_data' / 'etf_nav'


# ================================================================
# 📂 本地CSV数据源
# ================================================================

class LocalDataSource:
    """本地CSV数据源 - 用于回测"""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._cache = {}

    def load_etf_kline(self, etf_code, start_date=None, end_date=None):
        """加载单个ETF的K线数据，返回DataFrame (index=date)"""
        cache_key = etf_code
        if cache_key in self._cache and start_date is None:
            df = self._cache[cache_key]
            if start_date:
                df = df[df.index >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df.index <= pd.Timestamp(end_date)]
            return df

        possible_names = [
            f"{etf_code}.csv",
            f"{etf_code.replace('sh','').replace('sz','')}.csv",
        ]
        search_dirs = [self.data_dir]

        df = None
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            for fname in possible_names:
                fp = sdir / fname
                if fp.exists():
                    try:
                        df = pd.read_csv(fp, parse_dates=['date'], index_col='date')
                        df = df.sort_index()
                        df.columns = [c.lower().strip() for c in df.columns]
                        required_cols = {'open', 'high', 'low', 'close'}
                        if not required_cols.issubset(set(df.columns)):
                            continue
                        if 'volume' not in df.columns and 'vol' in df.columns:
                            df['volume'] = df['vol']
                        break
                    except Exception:
                        continue
            if df is not None:
                break

        if df is None:
            return None

        self._cache[cache_key] = df.copy()

        if start_date:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index <= pd.Timestamp(end_date)]

        return df

    def get_trade_dates(self, start_date=None, end_date=None):
        """获取交易日列表"""
        all_dates = set()
        for code in ETF_POOL[:5]:
            df = self.load_etf_kline(code)
            if df is not None:
                all_dates.update(df.index.date)
        dates = sorted(all_dates)
        if start_date:
            dt = pd.Timestamp(start_date).date() if isinstance(start_date, str) else start_date
            dates = [d for d in dates if d >= dt]
        if end_date:
            dt = pd.Timestamp(end_date).date() if isinstance(end_date, str) else end_date
            dates = [d for d in dates if d <= dt]
        return dates

    def get_current_price(self, etf_code, date=None):
        """获取指定日期的收盘价"""
        df = self.load_etf_kline(etf_code)
        if df is None or len(df) == 0:
            return None
        if date:
            dt = pd.Timestamp(date).date() if isinstance(date, str) else date
            mask = df.index.date == dt
            if mask.any():
                return float(df.loc[mask, 'close'].iloc[-1])
            return float(df.loc[df.index.date <= dt, 'close'].iloc[-1])
        return float(df['close'].iloc[-1])

    def load_all_etfs(self, start_date=None, end_date=None, min_rows=25, pool=None):
        """加载ETF数据，返回 {code: DataFrame} 字典
        pool: 指定ETF代码列表，默认使用 ETF_POOL（七星172池）"""
        data = {}
        codes = pool if pool is not None else ETF_POOL
        for code in codes:
            df = self.load_etf_kline(code, start_date, end_date)
            if df is not None and len(df) > min_rows:
                data[code] = df
        return data

    def load_nav(self, etf_code):
        """加载单只ETF的净值数据，返回 Series (index=date, values=unit_nav)"""
        nav_file = DEFAULT_NAV_DIR / f'{etf_code}_nav.csv'
        if not nav_file.exists():
            return None
        try:
            df = pd.read_csv(nav_file, encoding='utf-8')
            # 处理列名可能是中文的情况
            if '净值日期' in df.columns and '单位净值' in df.columns:
                df = df.rename(columns={'净值日期': 'date', '单位净值': 'unit_nav'})
            if 'date' not in df.columns or 'unit_nav' not in df.columns:
                return None
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date', 'unit_nav'])
            df = df.set_index('date').sort_index()
            return df['unit_nav']
        except Exception:
            return None

    def load_all_navs(self, pool=None):
        """加载ETF净值数据，返回 {code: Series} 字典
        pool: 指定ETF代码列表，默认使用 ETF_POOL"""
        navs = {}
        codes = pool if pool is not None else ETF_POOL
        for code in codes:
            nav = self.load_nav(code)
            if nav is not None and len(nav) > 0:
                navs[code] = nav
        return navs

    def get_nav_on_date(self, etf_code, nav_date):
        """
        获取指定日期的ETF净值，若当天无数据则向前搜索最多5个交易日
        返回 (nav_value, used_date) 或 (None, None)
        """
        nav_series = self.load_nav(etf_code)
        if nav_series is None or len(nav_series) == 0:
            return None, None
        nav_date_ts = pd.Timestamp(nav_date)
        # 尝试获取 <= nav_date 的净值（与聚宽原版逻辑一致：用前一日净值）
        mask = nav_series.index <= nav_date_ts
        available = nav_series[mask]
        if len(available) == 0:
            return None, None
        # 取最近5个交易日内最新的净值
        recent = available.tail(5)
        if len(recent) == 0:
            return None, None
        return float(recent.iloc[-1]), str(recent.index[-1].date())


# ================================================================
# 🎛️ 可插拔ETF过滤器接口
# ================================================================

class EtfFilter:
    """
    ETF过滤器抽象基类
    
    不同策略实现不同的过滤逻辑，互不干扰。
    回测引擎通过 self.filter.check() 调用，返回过滤结果。
    """
    name = "BaseFilter"

    def check(self, code, current_price, hist_df, date, params, nav_series=None):
        """
        检查ETF是否应该被过滤
        
        参数:
            code: ETF代码 (如 'sz159995')
            current_price: 当前价格
            hist_df: 历史数据 DataFrame (索引为date, 包含open/high/low/close/volume列)
            date: 检查日期
            params: 策略参数字典
            nav_series: 净值序列 (可选, 用于溢价率检查)
        
        返回:
            (is_filtered: bool, reasons: list[str])
        """
        raise NotImplementedError


class SevenStar172Filter(EtfFilter):
    """七星172策略过滤器 (6层过滤, 与原引擎内联逻辑逐层对齐)"""
    name = "SevenStar172"

    def check(self, code, current_price, hist_df, date, params, nav_series=None):
        reasons = []
        close_arr = hist_df['close'].values
        close_full = np.append(close_arr, current_price) if close_arr[-1] != current_price else close_arr
        lookback = params.get('lookback_days', 25)
        short_lb = params.get('short_lookback_days', 10)

        # 第1层: 盈利保护 (受 enable_profit_protection 控制, 与 check_profit_protection() 第332行一致)
        if params.get('enable_profit_protection', False):
            if self._check_profit_protection_172(code, current_price, hist_df, date, params):
                reasons.append('盈利保护')

        # 第2层: 溢价率 (可开关, 前一日净值, 与 get_premium_rate() 第355行一致)
        if params.get('enable_premium_filter', True) and nav_series is not None and len(nav_series) > 0:
            threshold = params.get('premium_threshold', 0.20)
            if self._check_premium(current_price, nav_series, date, threshold):
                reasons.append(f'溢价率>{int(threshold*100)}%')

        # 第3层: 成交量 (可开关, 172特有: 有量比+年化>3.0才过滤, 与 get_volume_ratio 第384行一致)
        if params.get('enable_volume_check', False):
            if self._check_volume_172(hist_df, date, close_full, lookback, params):
                reasons.append('成交量不足')

        # 第4层: 短期动量 (可开关)
        if params.get('use_short_momentum_filter', False) and len(close_full) >= short_lb + 1:
            short_momentum = self._calc_short_momentum(close_full, short_lb)
            if short_momentum < params.get('short_momentum_threshold', 0):
                reasons.append('短期动量负')

        # 第5层: 近3日单日跌幅 (始终启用, 旧内联代码无开关)
        if len(close_full) >= 4:
            day1 = close_full[-1] / close_full[-2]
            day2 = close_full[-2] / close_full[-3]
            day3 = close_full[-3] / close_full[-4]
            if min(day1, day2, day3) < params.get('loss', 0.97):
                reasons.append('近3日跌>3%')

        # 第6层: 得分范围 (始终启用)
        score = self._calc_score(close_full, lookback)
        min_s = params.get('min_score_threshold', -999)
        max_s = params.get('max_score_threshold', 999)
        if not (min_s < score < max_s):
            reasons.append('得分越界')

        return len(reasons) > 0, reasons

    def _check_profit_protection_172(self, code, current_price, hist_df, date, params):
        """盈利保护: 前N日最高点回撤>5%. 使用严格 < (原引擎第339行)"""
        lookback = params.get('profit_protection_lookback', 1)
        threshold = params.get('profit_protection_threshold', 0.05)
        try:
            mask = hist_df.index < pd.Timestamp(date)  # 严格小于, 排除当日
            hist = hist_df[mask]
            if len(hist) < lookback:
                return False
            max_high = hist['high'].tail(lookback).max()
            if max_high > 0 and current_price <= max_high * (1 - threshold):
                return True
        except Exception:
            pass
        return False

    def _check_premium(self, current_price, nav_series, date, threshold):
        """溢价率检查：用当日净值 (NAV当日早上已发布, 使用 <= 取当天)"""
        try:
            check_ts = pd.Timestamp(date)
            mask = nav_series.index <= check_ts  # <= 取当日早上已发布的净值
            available = nav_series[mask]
            if len(available) == 0:
                return False
            recent = available.tail(5)  # 向前搜索最多5日
            nav = float(recent.iloc[-1])
            if nav > 0:
                return (current_price - nav) / nav > threshold
        except Exception:
            pass
        return False

    def _check_volume_172(self, hist_df, date, close_full, lookback, params):
        """172成交量过滤: 放量 + 高年化收益 → 过滤. 与原引擎内联逻辑一致:
        仅当 (vol_ratio 可计算) AND (annualized > volume_return_limit) 时过滤"""
        try:
            vols = hist_df['volume']
            mask = vols.index <= pd.Timestamp(date)
            vols_to_date = vols[mask]
            vol_lookback = params.get('volume_lookback', 20)
            if len(vols_to_date) < vol_lookback + 1:
                return False
            avg_vol = vols_to_date.iloc[-(vol_lookback+1):-1].mean()
            current_vol = vols_to_date.iloc[-1]
            # vol_ratio 可计算即可, 不比较阈值 (与原 get_volume_ratio 一致)
            if avg_vol > 0:
                annualized = self._calc_annualized_only(close_full, lookback)
                if annualized > params.get('volume_return_limit', 3.0):
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _calc_annualized_only(close_full, lookback):
        """纯年化收益率(不含R2)，用于成交量过滤判断"""
        recent = close_full[-(lookback + 1):]
        y = np.log(np.maximum(recent, 1e-10))
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, _ = np.polyfit(x, y, 1, w=weights)
        return math.exp(slope * 250) - 1

    @staticmethod
    def _calc_short_momentum(close_full, short_lb):
        if len(close_full) < short_lb + 1:
            return 0
        short_return = close_full[-1] / close_full[-(short_lb + 1)] - 1
        return (1 + short_return) ** (250 / short_lb) - 1

    @staticmethod
    def _calc_score(close_full, lookback):
        recent = close_full[-(lookback + 1):]
        y = np.log(np.maximum(recent, 1e-10))
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized = math.exp(slope * 250) - 1
        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        return annualized * r2


class QMTFilter(EtfFilter):
    """七星QMT V3策略过滤器 (4层过滤, 与QMT聚宽版一致)"""
    name = "QMT"

    def check(self, code, current_price, hist_df, date, params, nav_series=None):
        reasons = []
        close_arr = hist_df['close'].values
        close_full = np.append(close_arr, current_price) if close_arr[-1] != current_price else close_arr

        # 第1层: 盈利保护 (回撤>5%)
        if params.get('enable_profit_protection', False):
            if self._check_profit_protection(code, current_price, hist_df, date, params):
                drawdown = self._calc_drawdown(current_price, hist_df, date, params)
                if drawdown is not None:
                    reasons.append(f'盈利保护(回撤{drawdown:.0f}%)')
                else:
                    reasons.append('盈利保护')

        # 第2层: 成交量放量 (最新日量<20日均量50% → 过滤)
        if params.get('enable_volume_check', False):
            if self._check_volume_qmt(hist_df, date):
                reasons.append('量缩')

        # 第3层: 短期动量 (<0 → 过滤)
        if params.get('use_short_momentum_filter', False):
            short_lb = params.get('short_lookback_days', 10)
            if len(close_full) >= short_lb + 1:
                sm = self._calc_short_momentum(close_full, short_lb)
                if sm < 0:
                    reasons.append(f'短期动量负({sm:.2f})')

        # 第4层: 溢价率 (>20% → 过滤)
        if params.get('enable_premium_filter', True) and nav_series is not None and len(nav_series) > 0:
            threshold = params.get('premium_threshold', 0.20)
            if self._check_premium(current_price, nav_series, date, threshold):
                reasons.append(f'溢价率>{int(threshold*100)}%')

        return len(reasons) > 0, reasons

    def _check_profit_protection(self, code, current_price, hist_df, date, params):
        lookback = params.get('profit_protection_lookback', 1)
        threshold = params.get('profit_protection_threshold', 0.05)
        try:
            mask = hist_df.index <= pd.Timestamp(date)
            hist = hist_df[mask]
            if len(hist) < lookback:
                return False
            max_high = hist['high'].tail(lookback).max()
            if max_high > 0 and current_price <= max_high * (1 - threshold):
                return True
        except Exception:
            pass
        return False

    def _calc_drawdown(self, current_price, hist_df, date, params):
        try:
            mask = hist_df.index <= pd.Timestamp(date)
            hist = hist_df[mask]
            lookback = params.get('profit_protection_lookback', 1)
            if len(hist) < lookback:
                return None
            max_high = hist['high'].tail(lookback).max()
            if max_high > 0:
                return (1 - current_price / max_high) * 100
        except Exception:
            pass
        return None

    def _check_volume_qmt(self, hist_df, date):
        """QMT成交量过滤: 最新日量 < 20日均量50%"""
        try:
            vols = hist_df['volume']
            mask = vols.index <= pd.Timestamp(date)
            vols_to_date = vols[mask]
            if len(vols_to_date) < 21:
                return False
            avg_vol = vols_to_date.iloc[-21:-1].mean()
            latest_vol = vols_to_date.iloc[-1]
            if avg_vol > 0 and latest_vol < avg_vol * 0.5:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _check_premium(current_price, nav_series, date, threshold):
        try:
            mask = nav_series.index <= pd.Timestamp(date)
            available = nav_series[mask]
            if len(available) == 0:
                return False
            nav = float(available.iloc[-1])
            if nav > 0:
                return (current_price - nav) / nav > threshold
        except Exception:
            pass
        return False

    @staticmethod
    def _calc_short_momentum(close_full, short_lb):
        if len(close_full) < short_lb + 1:
            return 0
        short_return = close_full[-1] / close_full[-(short_lb + 1)] - 1
        return (1 + short_return) ** (250 / short_lb) - 1


# ================================================================
# 💼 投资组合管理
# ================================================================

class Portfolio:
    """投资组合 - 记录持仓和资金状态"""

    def __init__(self, initial_cash=1000000, commission_rate=0.0001, min_commission=5):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.positions = {}           # {code: {shares, cost_price, last_price}}
        self.trade_log = []            # 交易记录列表
        self.daily_values = []        # 每日净值序列
        self.total_value_history = {}  # {date: total_value}

    @property
    def total_value(self):
        position_value = sum(
            p['shares'] * p.get('last_price', p['cost_price'])
            for p in self.positions.values()
        )
        return self.cash + position_value

    @property
    def total_returns(self):
        return (self.total_value - self.initial_cash) / self.initial_cash

    def update_price(self, code, price):
        """更新某标的的最新价"""
        if code in self.positions:
            self.positions[code]['last_price'] = price

    def update_prices(self, price_dict):
        """批量更新价格"""
        for code, price in price_dict.items():
            self.update_price(code, price)

    def buy(self, code, shares, price, date, reason=''):
        """买入"""
        trade_val = shares * price
        commission = max(trade_val * self.commission_rate, self.min_commission)
        total_cost = trade_val + commission

        if total_cost > self.cash + 0.01:
            print(f"  [REJECTED] 余额不足: 需要{total_cost:.2f}, 可用{self.cash:.2f}")
            return False

        self.cash -= total_cost

        if code in self.positions:
            old_pos = self.positions[code]
            total_shares = old_pos['shares'] + shares
            total_cost_val = old_pos['shares'] * old_pos['cost_price'] + shares * price
            avg_cost = total_cost_val / total_shares
            self.positions[code] = {
                'shares': total_shares,
                'cost_price': avg_cost,
                'last_price': price,
                'buy_date': old_pos.get('buy_date', date),
            }
        else:
            self.positions[code] = {
                'shares': shares,
                'cost_price': price,
                'last_price': price,
                'buy_date': date,
            }

        record = {
            'date': str(date),
            'code': code,
            'name': ETF_NAMES.get(code, code),
            'action': 'BUY',
            'price': round(price, 4),
            'shares': int(shares),
            'amount': round(trade_val, 2),
            'commission': round(commission, 2),
            'reason': reason,
        }
        self.trade_log.append(record)
        return True

    def sell(self, code, shares, price, date, reason=''):
        """卖出"""
        if code not in self.positions:
            return False

        pos = self.positions[code]
        actual_shares = min(shares, pos['shares'])
        if actual_shares <= 0:
            return False

        trade_val = actual_shares * price
        commission = max(trade_val * self.commission_rate, self.min_commission)
        net_proceeds = trade_val - commission

        self.cash += net_proceeds
        pos['shares'] -= actual_shares
        pnl_pct = (price - pos['cost_price']) / pos['cost_price'] if pos['cost_price'] > 0 else 0

        if pos['shares'] <= 0:
            del self.positions[code]

        record = {
            'date': str(date),
            'code': code,
            'name': ETF_NAMES.get(code, code),
            'action': 'SELL',
            'price': round(price, 4),
            'shares': int(actual_shares),
            'amount': round(trade_val, 2),
            'commission': round(commission, 2),
            'pnl_pct': round(pnl_pct, 4),
            'reason': reason,
        }
        self.trade_log.append(record)
        return True

    def sell_all(self, code, price, date, reason=''):
        """清仓卖出"""
        if code not in self.positions:
            return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)

    def record_daily_value(self, date):
        """记录每日净值"""
        val = self.total_value
        self.daily_values.append({
            'date': str(date),
            'value': round(val, 2),
            'returns': round((val - self.initial_cash) / self.initial_cash, 6),
        })
        self.total_value_history[str(date)] = round(val, 2)

    def get_position_codes(self):
        """返回当前持仓代码列表"""
        return list(self.positions.keys())
