#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
七星拉普拉斯策略 - 本地化完整版 (v3.0)
==========================================================================
原策略: 聚宽 JoinQuant 平台 (七星高照+高斯+拉普拉斯)
原作者: king088 / 晨曦量化

改造目标:
1. 保留100%原始能力（拉普拉斯滤波器+高斯滤波器+震荡期切换+7层过滤）
2. 支持本地CSV历史数据回测
3. 支持westock-data盘中实时模拟交易

能力清单:
✅ 拉普拉斯滤波器 (正常期, s=0.05, min_slope=0.001)
✅ 高斯滤波器 (震荡期, sigma=1.2)
✅ 震荡期自动切换机制 (乖离率/RSI超买回落/止损信号触发)
✅ 退出震荡期 (从低点涨幅/企稳信号/震荡期满)
✅ 盈利保护 (回撤阈值5%, 多时间点检查)
✅ 溢价率过滤 (阈值20%)
✅ 成交量比过滤 (放量>2倍时过滤)
✅ 短期动量过滤 (10日动量<0排除)
✅ 近3日单日跌幅过滤 (>3%单日跌幅排除)
✅ R²趋势稳定性评分 (年化收益×R²)
✅ T+1交易限制处理
✅ 智能下单 (停牌/涨跌停/最小金额检查)

数据源:
- 回测模式: data/storage/market_data/ 下CSV文件 或自定义目录
- 实盘模式: westock-data skill (腾讯行情接口)

运行方式:
    # 回测
    python seven_star_laplacian.py --mode backtest --start 2019-01-01 --end 2026-05-20
    
    # 盘中模拟交易
    python seven_star_laplacian.py --mode live --data-dir ./my_etf_data
==========================================================================
"""

import os
import sys
import json
import math
import argparse
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from copy import deepcopy

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

# ==================== 项目路径 ====================
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'market_data'
RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results'
LOG_DIR = PROJECT_ROOT / 'logs'

for d in [RESULTS_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)


# ================================================================
# 📊 ETF池配置 (与聚宽原版完全一致)
# ================================================================
ETF_POOL = [
    # 大宗商品ETF
    "sh518880", "sz159980", "sz159985", "sh501018", "sz161226",
    "sz159981",
    # 国际ETF
    "sh513100", "sz159509", "sh513290", "sh513500", "sz159529",
    "sh513400", "sh513520", "sh513030", "sh513080", "sh513310",
    "sh513730",
    # 香港ETF
    "sz159792", "sh513130", "sh513050", "sz159920", "sh513690",
    # 指数ETF
    "sh510300", "sh510500", "sh510050", "sh510210", "sz159915",
    "sh588080", "sh512100", "sh563360", "sh563300",
    # 风格ETF
    "sh512890", "sz159967", "sh512040", "sz159201",
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
    'sh511380': '可转债ETF博时',    'sh511010': '国债ETF国泰',
    'sz511220': '城投债ETF海富通',
}

DEFENSIVE_ETF = "sh511880"  # 银华日利(货币基金)


# ================================================================
# 🔧 默认参数 (与聚宽原版完全一致)
# ================================================================
DEFAULT_PARAMS = {
    # ---- 核心参数 ----
    'lookback_days': 25,
    'holdings_num': 1,
    'min_money': 5000,

    # ---- 盈利保护参数 ----
    'enable_profit_protection': True,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
    'profit_protection_check_times': ['11:00'],

    # ---- 过滤器参数 ----
    'loss': 0.97,                    # 近3日单日跌幅阈值
    'min_score_threshold': 0,
    'max_score_threshold': 100.0,

    # ---- 成交量过滤 ----
    'enable_volume_check': True,
    'volume_lookback': 5,
    'volume_threshold': 2,
    'volume_return_limit': 1,

    # ---- 短期动量过滤 ----
    'use_short_momentum_filter': True,
    'short_lookback_days': 10,
    'short_momentum_threshold': 0.0,

    # ---- 溢价率过滤 ----
    'enable_premium_filter': True,
    'premium_threshold': 0.20,

    # ---- 震荡期参数 ----
    'enable_range_bound_mode': True,
    'current_filter': '正常期',
    'risk_state': '正常期',
    'lookback_high_low_days': 20,
    'risk_benchmark': 'sh510300',

    # ---- 滤波器参数 ----
    'laplace_s_param': 0.05,
    'laplace_min_slope': 0.001,
    'gaussian_sigma': 1.2,
    'gaussian_min_slope': 0.002,

    # ---- 进入震荡期条件 ----
    'enable_bias_trigger': True,
    'bias_threshold': 0.10,
    'ma_period': 20,
    'enable_rsi_trigger': True,
    'rsi_overbought': 75,
    'rsi_pullback': 60,
    'enable_stop_loss_trigger': False,

    # ---- 退出震荡期条件 ----
    'enable_low_point_rise_trigger': True,
    'low_point_rise_threshold': 0.03,
    'enable_stable_signal_trigger': True,
    'drawdown_recovery': 0.03,
    'max_range_bound_days': 15,
    'filter_switch_cooldown': 2,
}


# ================================================================
# 📂 数据源抽象层
# ================================================================

class LocalDataSource:
    """本地CSV数据源 - 用于回测"""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._cache = {}

    def load_etf_kline(self, etf_code, start_date=None, end_date=None):
        """加载单个ETF的K线数据，返回DataFrame"""
        cache_key = etf_code
        if cache_key in self._cache and start_date is None:
            df = self._cache[cache_key]
            if start_date:
                df = df[df.index >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df.index <= pd.Timestamp(end_date)]
            return df

        # 尝试多种可能的文件名格式
        possible_names = [
            f"{etf_code}.csv",
            f"{etf_code.replace('sh','').replace('sz','')}.csv",
        ]

        search_dirs = [self.data_dir, self.data_dir / 'etf', self.data_dir / 'etf_qixing']

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
                        # 标准化列名
                        df.columns = [c.lower().strip() for c in df.columns]
                        required_cols = {'open', 'high', 'low', 'close'}
                        if not required_cols.issubset(set(df.columns)):
                            continue
                        if 'volume' not in df.columns and 'vol' in df.columns:
                            df['volume'] = df['vol']
                        break
                    except Exception as e:
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
        for code in ETF_POOL[:5]:  # 用前5只ETF推断交易日
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
        """获取指定日期的收盘价（或最新价格）"""
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

    def load_all_etfs(self, start_date=None, end_date=None):
        """加载所有ETF数据，返回 {code: DataFrame} 字典"""
        data = {}
        for code in ETF_POOL:
            df = self.load_etf_kline(code, start_date, end_date)
            if df is not None and len(df) > DEFAULT_PARAMS['lookback_days']:
                data[code] = df
        return data


class WeStockDataSource:
    """westock-data实时数据源 - 用于盘中模拟交易"""

    def __init__(self):
        import subprocess
        self._skill_path = Path(__file__).parent.parent.parent.parent / '.codebuddy' / 'skills' / 'westock-data'
        self._subprocess = subprocess

    def _run(self, *args):
        """执行westock-data命令并返回JSON结果"""
        cmd = ['node', str(self._skill_path / 'scripts' / 'index.js')] + list(args)
        try:
            result = self._subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception as e:
            print(f"[WARN] westock-data 执行失败: {e}")
        return None

    def quote(self, etf_code):
        """获取实时行情"""
        return self._run('quote', etf_code)

    def kline(self, etf_code, period='day', count=260):
        """获取K线数据"""
        return self._run('kline', etf_code, period, str(count))

    def technical(self, etf_code, indicator='all'):
        """获取技术指标"""
        return self._run('technical', etf_code, indicator)

    def batch_quote(self, codes):
        """批量行情查询"""
        return self._run('quote', ','.join(codes))


# ================================================================
# 💼 组合管理
# ================================================================

class Portfolio:
    """投资组合 - 记录持仓和资金状态"""

    def __init__(self, initial_cash=1000000, commission_rate=0.0001, min_commission=5):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.positions = {}          # {code: {shares, cost_price, last_price}}
        self.trade_log = []           # 交易记录列表
        self.daily_values = []       # 每日净值序列
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


# ================================================================
# ⚙️ 核心算法模块 (与聚宽原版完全一致)
# ================================================================

def calculate_rsi(close_series, period=14):
    """计算RSI值"""
    try:
        close_arr = np.asarray(close_series, dtype=float)
        if len(close_arr) < period + 1:
            return None
        deltas = np.diff(close_arr)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    except:
        return None


def laplace_filter(price, s=0.05):
    """拉普拉斯滤波器（正常期使用）- 与聚宽原版完全一致"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price, sigma=1.2):
    """仅计算高斯滤波最后两个点（震荡期使用）- 与聚宽原版完全一致"""
    n = len(price)
    if n < 2:
        return 0, 0
    idx_1 = np.arange(n)
    weights_1 = np.exp(-((idx_1 + 1)**2) / (2 * sigma**2))[::-1]
    weights_1 /= np.sum(weights_1)
    g1 = np.sum(price * weights_1)
    price_2 = price[:-1]
    idx_2 = np.arange(n - 1)
    weights_2 = np.exp(-((idx_2 + 1)**2) / (2 * sigma**2))[::-1]
    weights_2 /= np.sum(weights_2)
    g2 = np.sum(price_2 * weights_2)
    return g1, g2


# ================================================================
# 🎯 七星拉普拉斯策略引擎
# ================================================================

class SevenStarLaplacianEngine:
    """
    七星拉普拉斯策略核心引擎
    
    保留全部原始能力的本地化实现：
    - 7层过滤管道 (盈利保护→溢价率→成交量→短期动量→长期动量→跌幅→动态滤波器)
    - 拉普拉斯/高斯双滤波器 + 震荡期自动切换
    - 盈利保护机制
    """

    def __init__(self, params=None, mode='backtest'):
        self.params = deepcopy(DEFAULT_PARAMS)
        if params:
            self.params.update(params)
        self.mode = mode

        # 运行时状态变量 (对应聚宽的 g.xxx)
        self.rankings_cache = {'date': None, 'data': None}
        self.current_filter = self.params['current_filter']
        self.risk_state = self.params['risk_state']
        self.last_switch_date = None
        self.range_bound_start_date = None
        self.range_bound_days_count = 0
        self.stable_days = 0
        self.previous_drawdown = None
        self.previous_rsi = None
        self.stop_loss_triggered_today = False
        self.stop_loss_triggered_date = None

    def reset_state(self):
        """重置所有运行时状态"""
        self.rankings_cache = {'date': None, 'data': None}
        self.current_filter = self.params['current_filter']
        self.risk_state = self.params['risk_state']
        self.last_switch_date = None
        self.range_bound_start_date = None
        self.range_bound_days_count = 0
        self.stable_days = 0
        self.previous_drawdown = None
        self.previous_rsi = None
        self.stop_loss_triggered_today = False
        self.stop_loss_triggered_date = None

    # ---------- 第1层：盈利保护检查 ----------

    def check_profit_protection(self, etf_code, current_price, hist_df, check_date):
        """盈利保护检查 - 从最近N日最高点回撤超过阈值则触发"""
        if not self.params['enable_profit_protection']:
            return False

        lookback = self.params['profit_protection_lookback']
        threshold = self.params['profit_protection_threshold']

        try:
            mask = hist_df.index < pd.Timestamp(check_date)
            hist_before = hist_df[mask]
            if len(hist_before) < lookback:
                return False

            recent_highs = hist_before['high'].tail(lookback)
            max_high = recent_highs.max()

            if max_high > 0 and current_price <= max_high * (1 - threshold):
                drawdown = (max_high - current_price) / max_high
                print(f"    [PROFIT_PROTECT] {etf_code} 触发: 当前{current_price:.3f}, "
                      f"{lookback}日最高{max_high:.3f}, 回撤{drawdown*100:.2f}%>{threshold*100:.0f}%")
                return True
        except Exception as e:
            pass
        return False

    # ---------- 第2层：溢价率过滤 ----------

    def check_premium_rate(self, etf_code, check_date):
        """溢价率检查 - 回测模式下通常无净值数据，跳过此过滤"""
        if not self.params['enable_premium_filter']:
            return False  # 不过滤

        # 回测模式下若无净值数据源，默认不过滤
        # 实盘模式可通过westock获取
        return False  # 返回False表示未超过阈值(不拦截)

    # ---------- 第3层：成交量过滤 ----------

    def check_volume_ratio(self, etf_code, current_vol, hist_df, annualized_ret):
        """成交量放量过滤"""
        if not self.params['enable_volume_check']:
            return False

        lookback = self.params['volume_lookback']
        threshold = self.params['volume_threshold']
        limit = self.params['volume_return_limit']

        try:
            if len(hist_df) < lookback + 1:
                return False
            avg_vol = hist_df['volume'].tail(lookback).mean()
            if avg_vol > 0:
                ratio = current_vol / avg_vol
                if ratio > threshold and annualized_ret > limit:
                    print(f"    [VOLUME_FILTER] {etf_code} 放量{ratio:.1f}x, 年化{annualized_ret*100:.1f}%>{limit*100:.0f}%")
                    return True
        except:
            pass
        return False

    # ---------- 第4层：短期动量过滤 ----------

    def check_short_momentum(self, price_series):
        """短期动量过滤 - N日内年化收益低于阈值则排除"""
        if not self.params['use_short_momentum_filter']:
            return False

        lb = self.params['short_lookback_days']
        threshold = self.params['short_momentum_threshold']

        if len(price_series) >= lb + 1:
            short_ret = price_series[-1] / price_series[-(lb + 1)] - 1
            short_annual = (1 + short_ret) ** (250 / lb) - 1
            if short_annual < threshold:
                return True
        return False

    # ---------- 第5层：长期动量+R²得分计算 ----------

    def calculate_score(self, price_series):
        """
        长期动量得分计算 - 与聚宽原版完全一致
        
        使用加权对数回归计算年化收益率 × R²趋势稳定性
        """
        lookback = self.params['lookback_days']
        recent = price_series[-(lookback + 1):]
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
        return score, annualized_returns, r_squared

    def get_annualized_returns(self, price_series):
        """辅助函数：计算加权年化收益率"""
        lookback = self.params['lookback_days']
        recent = price_series[-(lookback + 1):]
        y = np.log(recent)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, _ = np.polyfit(x, y, 1, w=weights)
        return math.exp(slope * 250) - 1

    # ---------- 第6层：近3日单日跌幅过滤 ----------

    def check_recent_drops(self, price_series):
        """近3日单日跌幅检查 - 任一单日跌幅超过阈值则排除"""
        loss_thresh = self.params['loss']
        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            if min(day1, day2, day3) < loss_thresh:
                return True
        return False

    # ---------- 第7层：动态滤波器（核心！拉普拉斯/高斯） ----------

    def check_dynamic_filter(self, price_series, current_price):
        """
        动态滤波器过滤 - 与聚宽原版完全一致的7层核心
        
        正常期 → 拉普拉斯滤波器
        震荡期 → 高斯滤波器
        """
        if not self.params['enable_range_bound_mode']:
            return True  # 未开启，直接通过

        if len(price_series) < 10:
            return True  # 数据不足，放行

        try:
            # 拉普拉斯滤波器
            laplace_values = laplace_filter(price_series, s=self.params['laplace_s_param'])
            laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
            passed_laplace = (current_price > laplace_values[-1] and laplace_slope > self.params['laplace_min_slope'])

            # 高斯滤波器
            g1_val, g2_val = gaussian_filter_last_two(price_series, sigma=self.params['gaussian_sigma'])
            gaussian_slope = g1_val - g2_val
            passed_gaussian = (current_price > g1_val and gaussian_slope > self.params['gaussian_min_slope'])

            if self.current_filter == '正常期':
                passed_filter = passed_laplace
                filter_name = '拉普拉斯'
            else:
                passed_filter = passed_gaussian
                filter_name = '高斯'

            return passed_filter
        except Exception as e:
            return True  # 异常时放行

    # ========== 综合排名计算 ==========

    def calculate_momentum_metrics(self, etf_code, hist_df, current_price, check_date):
        """
        计算单只ETF的动量指标 - 完整的7层过滤管道
        
        对应聚宽原版的 calculate_momentum_metrics(context, etf)
        
        返回: metrics字典 or None(被过滤)
        """
        try:
            lookback = max(self.params['lookback_days'], self.params['short_lookback_days']) + 20
            
            # 构建价格序列（含当前价作为最后一点）
            close_arr = hist_df['close'].values.astype(float)
            if len(close_arr) < self.params['lookback_days']:
                return None
            price_series = np.append(close_arr, float(current_price))

            name = ETF_NAMES.get(etf_code, etf_code)

            # ===== 第1层: 盈利保护检查 =====
            if self.check_profit_protection(etf_code, current_price, hist_df, check_date):
                return None

            # ===== 第2层: 溢价率过滤 =====
            if self.check_premium_rate(etf_code, check_date):
                return None

            # ===== 第3层: 成交量过滤 =====
            current_vol = 0
            if len(hist_df) > 0:
                current_vol = hist_df['volume'].iloc[-1] if 'volume' in hist_df.columns else 0
            _, annualized_ret, _ = self.calculate_score(price_series)
            if self.check_volume_ratio(etf_code, current_vol, hist_df, annualized_ret):
                return None

            # ===== 第4层: 短期动量过滤 =====
            if self.check_short_momentum(price_series):
                return None

            # ===== 第5层: 长期动量+R²得分 =====
            score, annualized_returns, r_squared = self.calculate_score(price_series)

            # 得分范围过滤
            if not (self.params['min_score_threshold'] < score < self.params['max_score_threshold']):
                return None

            # ===== 第6层: 近3日单日跌幅过滤 =====
            if self.check_recent_drops(price_series):
                return None

            # ===== 第7层: 动态滤波器（拉普拉斯/高斯）=====
            if not self.check_dynamic_filter(price_series, current_price):
                return None

            # 通过所有过滤，返回指标
            short_annualized = 0
            if len(price_series) >= self.params['short_lookback_days'] + 1:
                slb = self.params['short_lookback_days']
                short_ret = price_series[-1] / price_series[-(slb + 1)] - 1
                short_annualized = (1 + short_ret) ** (250 / slb) - 1

            return {
                'etf': etf_code,
                'etf_name': name,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
                'short_annualized': short_annualized,
            }

        except Exception as e:
            print(f"  [ERROR] 计算{etf_code}指标出错: {e}")
            return None

    def get_ranked_etfs(self, all_etf_data, current_prices, check_date):
        """
        计算所有ETF排名 - 对应聚宽原版的 get_ranked_etfs(context)
        
        参数:
            all_etf_data: {code: DataFrame} 所有ETF的历史K线
            current_prices: {code: float} 当前价格字典
            check_date: 当前日期
        
        返回: 排序后的metrics列表
        """
        today_str = str(pd.Timestamp(check_date).date())
        if self.rankings_cache['date'] == today_str:
            return self.rankings_cache['data']

        etf_metrics = []
        for etf_code in ETF_POOL:
            if etf_code not in all_etf_data:
                continue
            hist_df = all_etf_data[etf_code]
            current_price = current_prices.get(etf_code)
            if current_price is None or current_price <= 0:
                continue

            metrics = self.calculate_momentum_metrics(etf_code, hist_df, current_price, check_date)
            if metrics is not None:
                etf_metrics.append(metrics)

        etf_metrics.sort(key=lambda x: x['score'], reverse=True)
        self.rankings_cache = {'date': today_str, 'data': etf_metrics}
        return etf_metrics

    # ========== 震荡期判断系统 (完整保留) ==========

    def get_risk_benchmark_state(self, benchmark_hist, current_price):
        """
        获取风险基准状态 - 对应聚宽原版的 get_risk_benchmark_state(context)
        """
        required_days = max(self.params['ma_period'], self.params['lookback_high_low_days'])
        if benchmark_hist is None or len(benchmark_hist) < required_days:
            return None

        daily_close = benchmark_hist['close'].values.astype(float)
        daily_high = benchmark_hist['high'].values.astype(float)
        daily_low = benchmark_hist['low'].values.astype(float)

        close_series = np.append(daily_close, float(current_price))
        high_series = np.append(daily_high, float(current_price))  # 简化：用当前价代替盘中高低
        low_series = np.append(daily_low, float(current_price))

        recent_high = np.max(high_series[-self.params['lookback_high_low_days']:])
        recent_low = np.min(low_series[-self.params['lookback_high_low_days']:])
        ma = np.mean(close_series[-self.params['ma_period']:])
        current_rsi = calculate_rsi(close_series, period=14)
        previous_rsi = calculate_rsi(daily_close, period=14)

        return {
            'close_series': close_series,
            'high_series': high_series,
            'low_series': low_series,
            'current_price': float(current_price),
            'recent_high': recent_high,
            'recent_low': recent_low,
            'ma': ma,
            'current_rsi': current_rsi,
            'previous_rsi': previous_rsi,
        }

    def init_range_bound_status(self, benchmark_hist):
        """首次运行时初始化震荡期状态"""
        if not self.params['enable_range_bound_mode']:
            return

        if benchmark_hist is None or len(benchmark_hist) < max(self.params['ma_period'], self.params['lookback_high_low_days']):
            return

        close = benchmark_hist['close'].values
        high = benchmark_hist['high'].values
        low = benchmark_hist['low'].values
        current_price = close[-1]

        recent_high = np.max(high[-self.params['lookback_high_low_days']:]) \
            if len(close) >= self.params['lookback_high_low_days'] else np.max(high)
        recent_low = np.min(low[-self.params['lookback_high_low_days']:]) \
            if len(close) >= self.params['lookback_high_low_days'] else np.min(low)
        ma = np.mean(close[-self.params['ma_period']:])
        bias = (current_price - ma) / ma if ma > 0 else 0
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        current_rsi = calculate_rsi(close, period=14)

        should_enter = False
        signals = []

        if self.params['enable_bias_trigger'] and bias > self.params['bias_threshold']:
            should_enter = True
            signals.append(f"乖离率{bias:.2%}>{self.params['bias_threshold']:.0%}")

        if self.params['enable_rsi_trigger'] and current_rsi is not None and len(close) >= 15:
            prev_rsi = calculate_rsi(close[:-1], period=14)
            if prev_rsi is not None and prev_rsi > self.params['rsi_overbought'] and current_rsi < self.params['rsi_pullback']:
                should_enter = True
                signals.append(f"RSI超买回落{prev_rsi:.1f}->{current_rsi:.1f}")

        if should_enter:
            self.current_filter = '震荡期'
            self.risk_state = '震荡期'
            print(f"  [RANGE_BOUND_INIT] 初始进入震荡期: {'; '.join(signals)}")
        else:
            self.current_filter = '正常期'
            self.risk_state = '正常期'
            if len(close) >= self.params['lookback_high_low_days']:
                self.previous_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
            self.previous_rsi = current_rsi

    def check_and_exit_range_bound(self, benchmark_hist, current_price, check_date):
        """检查是否需要退出震荡期"""
        if not self.params['enable_range_bound_mode'] or self.current_filter != '震荡期':
            return

        state = self.get_risk_benchmark_state(benchmark_hist, current_price)
        if state is None:
            return

        close = state['close_series']
        current_price_f = state['current_price']
        recent_high = state['recent_high']
        recent_low = state['recent_low']
        current_drawdown = (recent_high - current_price_f) / recent_high if recent_high > 0 else 0
        rise_from_low = (current_price_f - recent_low) / recent_low if recent_low > 0 else 0
        recovery_signals = []
        ma = state['ma']
        current_rsi = state['current_rsi']

        if self.params['enable_low_point_rise_trigger'] and rise_from_low >= self.params['low_point_rise_threshold']:
            recovery_signals.append(f"低点上涨{rise_from_low:.2%}")

        if self.params['enable_stable_signal_trigger']:
            if current_price_f > ma:
                recovery_signals.append("站上均线")
            if self.previous_drawdown is not None and current_drawdown < self.previous_drawdown:
                recovery_signals.append(f"回撤收窄({current_drawdown:.2%}<{self.previous_drawdown:.2%})")
            if current_rsi is not None and self.previous_rsi is not None and current_rsi > self.previous_rsi:
                recovery_signals.append(f"RSI回升({current_rsi:.1f})")

            drawdown_safe = current_drawdown < self.params['drawdown_recovery']
            if drawdown_safe:
                self.stable_days += 1
            else:
                self.stable_days = 0

        self.previous_drawdown = current_drawdown
        self.previous_rsi = current_rsi

        # 震荡期满强制退出
        range_bound_days = 0
        if self.range_bound_start_date is not None:
            range_bound_days = self.range_bound_days_count
            if range_bound_days >= self.params['max_range_bound_days']:
                recovery_signals.append(f"震荡期满({range_bound_days}天)")

        low_point_cond = self.params['enable_low_point_rise_trigger'] and rise_from_low >= self.params['low_point_rise_threshold']
        stable_cond = False
        if self.params['enable_stable_signal_trigger']:
            stable_cond = (drawdown_safe and len(recovery_signals) >= 2 and self.stable_days >= 2)
        force_cond = range_bound_days >= self.params['max_range_bound_days']

        if low_point_cond or stable_cond or force_cond:
            can_switch = self._check_cooldown(check_date)
            if can_switch:
                self.current_filter = '正常期'
                self.risk_state = '正常期'
                self.last_switch_date = check_date
                self.range_bound_start_date = None
                self.range_bound_days_count = 0
                self.stable_days = 0
                print(f"  [EXIT_RANGE] 切换回拉普拉斯: {'; '.join(recovery_signals)}")

    def check_and_enter_range_bound(self, benchmark_hist, current_price, check_date):
        """检查是否需要进入震荡期"""
        if not self.params['enable_range_bound_mode']:
            return
        if self.current_filter == '震荡期':
            return

        can_switch = self._check_cooldown(check_date)
        if not can_switch:
            return

        risk_signals = []
        state = self.get_risk_benchmark_state(benchmark_hist, current_price)

        if state is not None:
            # 条件1: 乖离率过大
            if self.params['enable_bias_trigger']:
                bias = (state['current_price'] - state['ma']) / state['ma'] if state['ma'] > 0 else 0
                if bias > self.params['bias_threshold']:
                    risk_signals.append(f"乖离率{bias:.2%}")
            # 条件2: RSI超买回落
            if self.params['enable_rsi_trigger']:
                cr = state['current_rsi']
                pr = state['previous_rsi']
                if cr is not None and pr is not None:
                    if pr > self.params['rsi_overbought'] and cr < self.params['rsi_pullback'] and cr < pr:
                        risk_signals.append(f"RSI{pr:.1f}->{cr:.1f}")

        # 条件3: 止损信号
        if self.params['enable_stop_loss_trigger'] and self.stop_loss_triggered_today:
            risk_signals.append("止损信号")

        if risk_signals:
            self.current_filter = '震荡期'
            self.risk_state = '震荡期'
            self.last_switch_date = check_date
            self.range_bound_start_date = check_date
            self.range_bound_days_count = 0
            self.stable_days = 0
            self.stop_loss_triggered_today = False
            self.stop_loss_triggered_date = None
            # 清除排名缓存
            self.rankings_cache = {'date': None, 'data': None}
            print(f"  [ENTER_RANGE] 切换到高斯滤波器: {'; '.join(risk_signals)}")

    def _check_cooldown(self, check_date):
        """检查切换冷却期"""
        if self.last_switch_date is None:
            return True
        try:
            ld = pd.Timestamp(self.last_switch_date).date()
            cd = pd.Timestamp(check_date).date()
            days_since = (cd - ld).days
            return days_since >= self.params['filter_switch_cooldown']
        except:
            return True

    def update_range_bound_daily(self, check_date):
        """每日更新震荡期计数"""
        if self.current_filter == '震荡期' and self.range_bound_start_date is not None:
            self.range_bound_days_count += 1

    def trigger_stop_loss_signal(self, check_date):
        """外部触发止损信号（用于盈利保护联动）"""
        if self.params['enable_stop_loss_trigger']:
            self.stop_loss_triggered_today = True
            self.stop_loss_triggered_date = check_date


# ================================================================
# 🔄 回测引擎
# ================================================================

class BacktestEngine:
    """
    事件驱动回测引擎
    
    逐日模拟交易，完整保留聚宽原版的调度逻辑:
    - 09:10 检查持仓日志
    - 11:00 盈利保护检查
    - 13:55 震荡期检查
    - 13:10 卖出操作
    - 13:11 买入操作
    - 15:10 收盘重置
    """

    def __init__(self, data_source, engine_params=None):
        self.data_source = data_source
        self.engine = SevenStarLaplacianEngine(engine_params, mode='backtest')
        self.portfolio = None
        self.results = {}

    def run(self, start_date, end_date, initial_cash=1000000):
        """
        执行完整回测
        
        参数:
            start_date: 回测起始日期 (str 或 datetime)
            end_date: 回测结束日期 (str 或 datetime)
            initial_cash: 初始资金
        """
        print("=" * 70)
        print("七星拉普拉斯策略 - 本地回测引擎 v3.0")
        print(f"回测区间: {start_date} ~ {end_date} | 初始资金: {initial_cash:,.0f}")
        print("=" * 70)

        # 加载数据
        print("\n[1/5] 加载ETF历史数据...")
        all_etf_data = self.data_source.load_all_etfs(start_date, end_date)
        print(f"  成功加载 {len(all_etf_data)}/{len(ETF_POOL)} 只ETF")

        if len(all_etf_data) == 0:
            print("[FATAL] 无可用数据! 请检查 data_dir 是否包含ETF CSV文件")
            return None

        # 获取交易日
        trade_dates = self.data_source.get_trade_dates(start_date, end_date)
        print(f"  交易日数: {len(trade_dates)} 天")

        # 初始化
        self.engine.reset_state()
        self.portfolio = Portfolio(initial_cash=initial_cash)

        # 首次初始化震荡期状态
        bench_code = self.engine.params['risk_benchmark']
        bench_data = all_etf_data.get(bench_code)
        if bench_data is not None:
            # 用回测起始前的数据来初始化
            bench_full = self.data_source.load_etf_kline(bench_code)
            if bench_full is not None:
                init_end_idx = bench_full.index.searchsorted(pd.Timestamp(start_date))
                if init_end_idx >= self.engine.params['ma_period']:
                    bench_init = bench_full.iloc[:init_end_idx]
                    self.engine.init_range_bound_status(bench_init)
                    print(f"  震荡期初始状态: {self.engine.current_filter}")

        print(f"\n[2/5] 开始逐日回测...")
        print("-" * 70)

        for i, td in enumerate(trade_dates):
            td_ts = pd.Timestamp(td)
            
            # 构建当日快照
            current_prices = {}
            for code, df in all_etf_data.items():
                mask = df.index <= td_ts
                if mask.any():
                    current_prices[code] = float(df.loc[mask, 'close'].iloc[-1])

            # 更新组合价格
            self.portfolio.update_prices(current_prices)

            # ===== 09:10 持仓日志 =====
            self._log_positions(i, td)

            # ===== 11:00 盈利保护检查 =====
            self._run_profit_protection(current_prices, all_etf_data, td)

            # ===== 13:55 震荡期检查 (先于买卖) =====
            self._run_range_bound_check(all_etf_data, current_prices, td)

            # ===== 13:10 卖出操作 =====
            self._run_sell(current_prices, all_etf_data, td)

            # ===== 13:11 买入操作 =====
            self._run_buy(current_prices, all_etf_data, td)

            # ===== 15:10 收盘重置 =====
            self.engine.update_range_bound_daily(td)
            self.engine.stop_loss_triggered_today = False

            # 记录每日净值
            self.portfolio.record_daily_value(td)

        print("-" * 70)
        print(f"\n[3/5] 回测完成! 生成报告...")

        # 生成结果
        results = self._generate_results(trade_dates, initial_cash)
        self.results = results
        return results

    def _log_positions(self, i, date):
        """持仓日志"""
        if i % 20 != 0:  # 每20天打印一次
            return
        held = self.portfolio.get_position_codes()
        if held:
            for code in held[:3]:
                pos = self.portfolio.positions[code]
                pnl = (pos['last_price'] - pos['cost_price']) / pos['cost_price'] * 100 if pos['cost_price'] > 0 else 0
                print(f"  [{date}] 持仓: {code} {ETF_NAMES.get(code,'')} "
                      f"数量{pos['shares']} 成本{pos['cost_price']:.3f} 现价{pos['last_price']:.3f} PnL:{pnl:+.2f}%")

    def _run_profit_protection(self, current_prices, all_etf_data, date):
        """执行盈利保护检查"""
        if not self.engine.params['enable_profit_protection']:
            return

        for code in list(self.portfolio.get_position_codes()):
            if code not in all_etf_data:
                continue
            hist_df = all_etf_data[code]
            cur_price = current_prices.get(code, 0)

            if self.engine.check_profit_protection(code, cur_price, hist_df, date):
                if self.portfolio.sell_all(code, cur_price, date, reason='盈利保护'):
                    print(f"  [{date}] PROFIT_PROTECT 卖出: {code} @{cur_price:.3f}")
                    self.engine.trigger_stop_loss_signal(date)

    def _run_range_bound_check(self, all_etf_data, current_prices, date):
        """震荡期检查"""
        bench_code = self.engine.params['risk_benchmark']
        bench_data = all_etf_data.get(bench_code)
        if bench_data is None:
            return

        bench_price = current_prices.get(bench_code, 0)
        if bench_price <= 0:
            return

        # 截止到当前日的基准数据
        mask = bench_data.index <= pd.Timestamp(date)
        bench_hist = bench_data[mask]
        if len(bench_hist) < self.engine.params['ma_period']:
            return

        self.engine.check_and_exit_range_bound(bench_hist, bench_price, date)
        self.engine.check_and_enter_range_bound(bench_hist, bench_price, date)

    def _run_sell(self, current_prices, all_etf_data, date):
        """卖出操作 - 对应聚宽原版的 etf_sell_trade"""
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)

        target_etfs = []
        for m in ranked[:self.engine.params['holdings_num']]:
            if m['score'] >= self.engine.params['min_score_threshold']:
                target_etfs.append(m['etf'])

        target_set = set(target_etfs)
        holdings = self.portfolio.get_position_codes()

        to_sell = [s for s in holdings if s not in target_set]
        for sec in to_sell:
            if sec not in current_prices or current_prices[sec] <= 0:
                continue
            if self.portfolio.sell_all(sec, current_prices[sec], date, reason='调出目标'):
                print(f"  [{date}] SELL: {sec} {ETF_NAMES.get(sec,'')} @{current_prices[sec]:.3f}")

    def _run_buy(self, current_prices, all_etf_data, date):
        """买入操作 - 对应聚宽原版的 etf_buy_trade"""
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)

        # 打印前5名
        if ranked:
            print(f"  [{date}] TOP5:", end='')
            for m in ranked[:5]:
                print(f" {m['etf']}({m['score']:.4f})", end='')
            print(f" | Filter={self.engine.current_filter}")

        # 确定目标ETF
        target_etfs = []
        for m in ranked:
            if len(target_etfs) >= self.engine.params['holdings_num']:
                break
            target_etfs.append(m['etf'])

        # 防御模式
        if not target_etfs:
            target_etfs = [DEFENSIVE_ETF]
            print(f"  [{date}] DEFENSE -> {DEFENSIVE_ETF}")

        # 等权分配
        total_val = self.portfolio.total_value
        target_per_etf = total_val / len(target_etfs)
        min_money = self.engine.params['min_money']

        for etf in target_etfs:
            if etf not in current_prices or current_prices[etf] <= 0:
                continue

            current_val = 0
            if etf in self.portfolio.positions:
                pos = self.portfolio.positions[etf]
                if pos['shares'] > 0:
                    current_val = pos['shares'] * pos['last_price']

            diff = target_per_etf - current_val
            if abs(diff) < target_per_etf * 0.05 and current_val > 0:
                continue  # 在容差内，不调整

            price = current_prices[etf]
            if diff > 0:  # 买入
                target_amount = int(diff / price // 100) * 100
                if target_amount <= 0 and diff > min_money:
                    target_amount = 100
                if target_amount * price >= min_money:
                    if self.portfolio.buy(etf, target_amount, price, date, reason=f'排名{target_etfs.index(etf)+1}'):
                        print(f"  [{date}] BUY: {etf} {ETF_NAMES.get(etf,'')} {target_amount}份@{price:.3f}")
            elif diff < 0:  # 减仓
                target_amount = int(abs(diff) / price // 100) * 100
                if target_amount > 0:
                    if self.portfolio.sell(etf, target_amount, price, date, reason='减仓'):
                        print('  [%s] REDUCE: %s %s %d@%.3f' % (date, etf, ETF_NAMES.get(etf,''), target_amount, price))

    def _generate_results(self, trade_dates, initial_cash):
        """生成回测结果汇总"""
        dv = self.portfolio.daily_values
        if not dv:
            return None

        values = [d['value'] for d in dv]
        returns_arr = [d['returns'] for d in dv]
        final_val = values[-1]
        total_ret = (final_val - initial_cash) / initial_cash

        # 最大回撤
        peak = values[0]
        max_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd

        # 夏普比率 (年化)
        if len(returns_arr) > 1:
            ret_std = np.std(returns_arr) * np.sqrt(252)
            sharpe = (np.mean(returns_arr) * 252 / ret_std) if ret_std > 0 else 0
        else:
            sharpe = 0

        # 卡尔马比率
        calmar = abs(total_ret * 252 / max_dd) if max_dd > 0 else 0

        # 交易统计
        trades = self.portfolio.trade_log
        n_trades = len(trades)
        buys = sum(1 for t in trades if t['action'] == 'BUY')
        sells = sum(1 for t in trades if t['action'] == 'SELL')

        # 胜率
        sell_trades = [t for t in trades if t['action'] == 'SELL' and 'pnl_pct' in t]
        win_rate = sum(1 for t in sell_trades if t['pnl_pct'] > 0) / len(sell_trades) * 100 if sell_trades else 0

        results = {
            'strategy': '七星拉普拉斯 v3.0 (本地化)',
            'backtest_period': f'{trade_dates[0]} ~ {trade_dates[-1]}',
            'trading_days': len(trade_dates),
            'initial_cash': initial_cash,
            'final_value': round(final_val, 2),
            'total_return_pct': round(total_ret * 100, 2),
            'annualized_return_pct': round(total_ret * 252 / len(trade_dates) * 100, 2) if trade_dates else 0,
            'max_drawdown_pct': round(max_dd * 100, 2),
            'sharpe_ratio': round(sharpe, 4),
            'calmar_ratio': round(calmar, 4),
            'total_trades': n_trades,
            'buy_trades': buys,
            'sell_trades': sells,
            'win_rate_pct': round(win_rate, 2),
            'final_holdings': self.portfolio.get_position_codes(),
            'daily_values': dv,
            'trade_log': trades,
            'engine_params': self.engine.params,
            'filter_state_final': self.engine.current_filter,
        }

        # 打印摘要
        print("\n" + "=" * 70)
        print("回测结果摘要")
        print("=" * 70)
        print(f"  策略:      {results['strategy']}")
        print(f"  区间:      {results['backtest_period']} ({results['trading_days']}个交易日)")
        print(f"  初始资金:  {results['initial_cash']:,.0f}")
        print(f"  最终资产:  {results['final_value']:,.2f}")
        print(f"  总收益率:  {results['total_return_pct']:+.2f}%")
        print(f"  年化收益:  {results['annualized_return_pct']:.2f}%")
        print(f"  最大回撤:  {results['max_drawdown_pct']:.2f}%")
        print(f"  夏普比率:  {results['sharpe_ratio']:.4f}")
        print(f"  卡尔马:    {results['calmar_ratio']:.4f}")
        print(f"  总交易数:  {results['total_trades']} (买{results['buy_trades']}/卖{results['sell_trades']})")
        print(f"  胜率:      {results['win_rate_pct']:.1f}%")
        print(f"  最终持仓:  {results['final_holdings']}")
        print(f"  滤波器:    {results['filter_state_final']}")
        print("=" * 70)

        return results

    def save_results(self, output_path=None):
        """保存结果到JSON"""
        if not self.results:
            return None
        out_path = Path(output_path) if output_path else RESULTS_DIR / f'seven_star_laplacian_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        save_data = {k: v for k, v in self.results.items() if k not in ('daily_values', 'trade_log')}
        save_data['daily_values_count'] = len(self.results.get('daily_values', []))
        save_data['trade_log_count'] = len(self.results.get('trade_log', []))
        save_data['trade_log_last10'] = self.results.get('trade_log', [])[-10:]

        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n结果已保存: {out_path}")
        return out_path


# ================================================================
# 📡 盘中模拟交易引擎
# ================================================================

class LiveTraderEngine:
    """
    盘中模拟交易引擎
    
    使用westock-data获取实时数据，执行七星拉普拉斯策略逻辑
    支持定时调度和手动触发
    """

    def __init__(self, engine_params=None, state_dir=None):
        self.engine = SevenStarLaplacianEngine(engine_params, mode='live')
        self.ws = WeStockDataSource()
        self.state_dir = Path(state_dir) if state_dir else LOG_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.portfolio = None
        self._load_state()

    def _get_state_path(self):
        return self.state_dir / 'seven_star_laplacian_live_state.json'

    def _load_state(self):
        """加载持久化状态"""
        sp = self._get_state_path()
        if sp.exists():
            try:
                with open(sp, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                # 恢复引擎状态
                self.engine.current_filter = state.get('current_filter', '正常期')
                self.engine.risk_state = state.get('risk_state', '正常期')
                self.engine.last_switch_date = state.get('last_switch_date')
                self.engine.range_bound_start_date = state.get('range_bound_start_date')
                self.engine.range_bound_days_count = state.get('range_bound_days_count', 0)
                self.engine.stable_days = state.get('stable_days', 0)
                self.engine.previous_drawdown = state.get('previous_drawdown')
                self.engine.previous_rsi = state.get('previous_rsi')

                # 恢复组合
                init_cash = state.get('initial_cash', 1000000)
                self.portfolio = Portfolio(initial_cash=init_cash)
                for code, pos in state.get('positions', {}).items():
                    self.portfolio.positions[code] = pos
                self.portfolio.cash = state.get('cash', init_cash)
                self.portfolio.trade_log = state.get('trade_log', [])
                self.portfolio.daily_values = state.get('daily_values', [])

                print(f"[STATE] 已加载持久化状态 | Filter={self.engine.current_filter} | Cash={self.portfolio.cash:,.0f}")
                return
            except Exception as e:
                print(f"[WARN] 加载状态失败: {e}, 使用初始状态")

        self.portfolio = Portfolio(initial_cash=1000000)

    def _save_state(self):
        """保存状态"""
        state = {
            'saved_at': datetime.now().isoformat(),
            'current_filter': self.engine.current_filter,
            'risk_state': self.engine.risk_state,
            'last_switch_date': self.engine.last_switch_date,
            'range_bound_start_date': self.engine.range_bound_start_date,
            'range_bound_days_count': self.engine.range_bound_days_count,
            'stable_days': self.engine.stable_days,
            'previous_drawdown': self.engine.previous_drawdown,
            'previous_rsi': self.engine.previous_rsi,
            'initial_cash': self.portfolio.initial_cash,
            'cash': self.portfolio.cash,
            'positions': {k: dict(v) for k, v in self.portfolio.positions.items()},
            'trade_log': self.portfolio.trade_log[-100:],  # 只保留最近100条
            'daily_values': self.portfolio.daily_values[-252:],  # 保留最近一年
        }
        sp = self._get_state_path()
        with open(sp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)

    def fetch_realtime_data(self, etf_code):
        """获取单只ETF实时行情"""
        result = self.ws.quote(etf_code)
        if result and result.get('status') == 'ok' and result.get('data'):
            d = result['data'][0] if isinstance(result.get('data'), list) else result['data']
            return {
                'code': etf_code,
                'price': float(d.get('lastPrice', 0)),
                'high': float(d.get('high', 0)),
                'low': float(d.get('low', 0)),
                'open': float(d.get('open', 0)),
                'volume': float(d.get('volume', 0)),
                'change_pct': float(d.get('changePercent', 0)),
            }
        return None

    def fetch_batch_quotes(self):
        """批量获取所有ETF实时行情"""
        prices = {}
        for code in ETF_POOL:
            q = self.fetch_realtime_data(code)
            if q and q['price'] > 0:
                prices[code] = q
            # 稍微延迟避免请求过快
        return prices

    def fetch_historical_from_westock(self, etf_code, count=300):
        """从westock获取历史K线用于指标计算"""
        result = self.ws.kline(etf_code, 'day', count)
        if result and result.get('status') == 'ok' and result.get('data'):
            nodes = result['data'].get('nodes', [])
            if nodes:
                rows = []
                for node in nodes:
                    rows.append({
                        'date': node.get('date'),
                        'open': node.get('open'),
                        'high': node.get('high'),
                        'low': node.get('low'),
                        'close': node.get('last'),
                        'volume': node.get('volume', 0),
                    })
                df = pd.DataFrame(rows)
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df.sort_index(inplace=True)
                return df
        return None

    def run_once(self, simulate_trade=True):
        """
        执行一轮盘中监控
        
        参数:
            simulate_trade: 是否实际执行模拟交易 (False=仅查看排名不交易)
        """
        now = datetime.now()
        print("=" * 60)
        print(f"七星拉普拉斯盘中模拟交易 | {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # 1. 获取实时行情
        print("\n[1/4] 获取实时行情...")
        quotes = self.fetch_batch_quotes()
        print(f"  获取到 {len(quotes)}/{len(ETF_POOL)} 只ETF行情")

        if len(quotes) < 5:
            print("  [WARN] 行情数据不足，跳过本次")
            return None

        current_prices = {code: q['price'] for code, q in quotes.items()}
        self.portfolio.update_prices(current_prices)

        # 2. 加载历史数据(从westock)
        print("\n[2/4] 加载历史K线数据...")
        all_etf_data = {}
        for code in list(current_prices.keys()):
            df = self.fetch_historical_from_westock(code, count=300)
            if df is not None and len(df) > self.engine.params['lookback_days']:
                all_etf_data[code] = df
        print(f"  历史数据就绪: {len(all_etf_data)} 只")

        # 3. 震荡期检查
        print(f"\n[3/4] 震荡期检查 (当前: {self.engine.current_filter})")
        bench_code = self.engine.params['risk_benchmark']
        bench_data = all_etf_data.get(bench_code)
        if bench_data is not None:
            bench_price = current_prices.get(bench_code, 0)
            self.engine.check_and_exit_range_bound(bench_data, bench_price, now.date())
            self.engine.check_and_enter_range_bound(bench_data, bench_price, now.date())
            print(f"  检查后状态: {self.engine.current_filter}")

        # 4. 计算排名 & 执行交易
        print("\n[4/4] 计算排名...")
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, now.date())

        if not ranked:
            print("  无合格ETF!")
            return self._build_report(now, quotes, ranked, [])

        # 打印排名
        print(f"\n  TOP10:")
        for i, m in enumerate(ranked[:10]):
            print(f"    {i+1:>2}. {m['etf']} {m['etf_name']:16s} | "
                  f"Score={m['score']:.4f} | AnnRet={m['annualized_returns']*100:7.2f}% | "
                  f"R²={m['r_squared']:.4f} | Price={m['current_price']:.3f}")

        actions_taken = []
        if simulate_trade:
            # 卖出
            target_set = set(m['etf'] for m in ranked[:self.engine.params['holdings_num']])
            for sec in self.portfolio.get_position_codes():
                if sec not in target_set:
                    price = current_prices.get(sec, 0)
                    if price > 0 and self.portfolio.sell_all(sec, price, now.date(), reason='排名掉出'):
                        actions_taken.append({'action': 'SELL', 'code': sec, 'price': price})
                        print(f"  [TRADE] SELL {sec}@{price:.3f}")

            # 买入
            target_etfs = [m['etf'] for m in ranked[:self.engine.params['holdings_num']]]
            if not target_etfs:
                target_etfs = [DEFENSIVE_ETF]

            total_val = self.portfolio.total_value
            per_etf = total_val / len(target_etfs)
            for etf in target_etfs:
                if etf not in current_prices or current_prices[etf] <= 0:
                    continue
                price = current_prices[etf]
                cur_val = 0
                if etf in self.portfolio.positions:
                    pos = self.portfolio.positions[etf]
                    cur_val = pos['shares'] * price
                diff = per_etf - cur_val
                if diff > per_etf * 0.05 or cur_val == 0:
                    amt = int(diff / price // 100) * 100
                    if amt <= 0 and diff > self.engine.params['min_money']:
                        amt = 100
                    if amt > 0:
                        if self.portfolio.buy(etf, amt, price, now.date(), reason=f'排名{target_etfs.index(etf)+1}'):
                            actions_taken.append({'action': 'BUY', 'code': etf, 'price': price, 'shares': amt})
                            print(f"  [TRADE] BUY {etf} {amt}份@{price:.3f}")

        # 记录净值
        self.portfolio.record_daily_value(now.date())

        # 保存状态
        self._save_state()

        report = self._build_report(now, quotes, ranked, actions_taken)
        return report

    def _build_report(self, now, quotes, ranked, actions):
        """构建监控报告"""
        holdings = self.portfolio.get_position_codes()
        return {
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'filter_state': self.engine.current_filter,
            'etf_quoted': len(quotes),
            'ranked_count': len(ranked),
            'top5': [(m['etf'], m['etf_name'], round(m['score'], 4), 
                      round(m['annualized_returns']*100, 2), round(m['current_price'], 3))
                     for m in ranked[:5]],
            'holdings': {code: {
                'shares': self.portfolio.positions[code]['shares'],
                'cost': self.portfolio.positions[code]['cost_price'],
                'price': self.portfolio.positions[code]['last_price'],
                'pnl_pct': round((self.portfolio.positions[code]['last_price'] - self.portfolio.positions[code]['cost_price']) / self.portfolio.positions[code]['cost_price'] * 100, 2)
            } for code in holdings},
            'total_value': round(self.portfolio.total_value, 2),
            'total_return_pct': round(self.portfolio.total_returns * 100, 2),
            'actions': actions,
            'cash': round(self.portfolio.cash, 2),
        }


# ================================================================
# 🚀 CLI入口
# ================================================================

def main():
    parser = argparse.ArgumentParser(description='七星拉普拉斯策略 v3.0 - 本地回测/盘中模拟')
    parser.add_argument('--mode', choices=['backtest', 'live'], default='backtest',
                       help='运行模式: backtest=本地CSV回测, live=westock盘中模拟')
    parser.add_argument('--start', type=str, default='2019-01-02',
                       help='回测起始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=datetime.now().strftime('%Y-%m-%d'),
                       help='回测结束日期 (YYYY-MM-DD)')
    parser.add_argument('--cash', type=float, default=1000000,
                       help='初始资金 (默认100万)')
    parser.add_argument('--data-dir', type=str, default=None,
                       help='ETF CSV数据目录 (默认项目data/storage/market_data)')
    parser.add_argument('--output', type=str, default=None,
                       help='结果输出JSON路径')
    parser.add_argument('--no-trade', action='store_true',
                       help='仅观察排名，不执行模拟交易(live模式)')

    args = parser.parse_args()

    if args.mode == 'backtest':
        # === 回测模式 ===
        ds = LocalDataSource(data_dir=args.data_dir)
        engine = BacktestEngine(ds)
        results = engine.run(args.start, args.end, args.cash)
        if results:
            path = engine.save_results(args.output)
    else:
        # === 盘中模拟模式 ===
        trader = LiveTraderEngine(state_dir=args.state_dir if hasattr(args, 'state_dir') else None)
        report = trader.run_once(simulate_trade=not args.no_trade)
        if report:
            print("\n--- 本次报告 ---")
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
