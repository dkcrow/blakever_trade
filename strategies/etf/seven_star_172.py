#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
七星172策略 - 本地化完整版 (基于GLM5修复版)
==========================================================================
原策略: 聚宽 JoinQuant 平台 (七星高照ETF轮动策略-V1.7.2)
原作者: 晨曦量化 / tina25 / GLM5

能力清单:
✅ 6层过滤管道 (盈利保护→溢价率→成交量→短期动量→长期动量→跌幅)
✅ 日内卖出黑名单机制 (防止尾盘买回盈利保护卖出的标的)
✅ 买入二次检查 (补上作者文档声称但漏掉的代码)
✅ 盈利保护 (回撤阈值5%, 11:00检查)
✅ T+1交易限制处理
✅ 智能下单 (停牌/涨跌停/最小金额检查)
✅ 防御模式 (货币基金)

与七星拉普拉斯的主要区别:
❌ 无震荡期机制 (无拉普拉斯/高斯滤波器切换)
❌ 无动态滤波器

数据源:
- 回测模式: data/storage/stock_data/etf/ 下CSV文件

运行方式:
    # 回测
    python seven_star_172.py --start 2024-01-01 --end 2026-05-27
    
    # 指定资金
    python seven_star_172.py --start 2024-01-01 --end 2026-05-27 --cash 100000
==========================================================================
"""

import os
import sys
import math
import argparse
import warnings
from datetime import datetime
from pathlib import Path
from copy import deepcopy

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

# ==================== 项目路径 ====================
_THIS_FILE = Path(__file__)
PROJECT_ROOT = _THIS_FILE.parent.parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'
RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_172'

os.makedirs(RESULTS_DIR, exist_ok=True)

# 导入共享基础设施
sys.path.insert(0, str(PROJECT_ROOT))
from strategies.etf.seven_star_base import (
    LocalDataSource, Portfolio, ETF_POOL, ETF_NAMES, DEFENSIVE_ETF
)

# ================================================================
# 🔧 默认参数 (与聚宽七星172原版完全一致 — 禁止修改!)
# ================================================================
# ⚠️ RULE: 以下参数必须与七星172原版.py完全一致, 任何修改都需要克总明确授权
# ⚠️ RULE: 如需实验, 请在七星QMT(generate_qmt_report.py)中进行

DEFAULT_PARAMS = {
    # ---- 核心参数 ----
    'lookback_days': 25,
    'holdings_num': 1,                 # 原版: 仅持1只
    'min_money': 5000,

    # ---- 盈利保护参数 ----
    'enable_profit_protection': True,
    'profit_protection_lookback': 1,
    'profit_protection_threshold': 0.05,
    'profit_protection_check_times': ['11:00'],

    # ---- 过滤器参数 (原版值) ----
    'loss': 0.97,                    # 原版: 近3日单日跌幅>3%过滤
    'min_score_threshold': 0,        # 原版: 得分<0过滤
    'max_score_threshold': 100.0,    # 原版: 得分>100过滤

    # ---- 成交量过滤 (原版: 启用) ----
    'enable_volume_check': True,

    # ---- 短期动量过滤 (原版: 启用) ----
    'use_short_momentum_filter': True,
    'short_lookback_days': 10,

    # ---- 溢价率过滤 ----
    'enable_premium_filter': True,
    'premium_threshold': 0.20,

    # ---- 行情判断 & 走弱期防御 (QMT V3, 原版无此功能) ----
    'enable_regime_switch': False,     # 原版无, 默认关闭
    'enable_avoid_a_share': False,     # 原版无, 默认关闭
    'enable_intraday_drawdown': False, # 原版无, 默认关闭

    # ---- V4 行业轮动状态机 (2026-07-30移植) ----
    'enable_hs300_state_machine': False,   # 沪深300 MA60状态机 ON/OFF
    'hs300_ma_period': 60,                 # MA周期
    'hs300_buffer_pct': 0.005,            # ±0.5%缓冲带
    'hs300_confirm_days': 2,              # 连续确认天数
    'hs300_slope_lookback': 5,            # MA60斜率确认(恢复ON时MA60>5日前)
    'hs300_cooling_days': 2,              # 状态切换冷静期
    'hs300_combo_dd_threshold': 0.08,     # 组合回撤阈值(-8%清仓)
    'hs300_combo_dd_cooling': 5,          # 组合止损后冷静期
    'hs300_defensive_etf': 'sh511010',    # OFF/冷静期切换到国债ETF
    'intraday_drawdown_threshold': 0.02,
    'weak_period_ma_lookback': 10,
    'weak_period_max_days': 20,
}

# ================================================================
# 📋 ETF类别分类 (对应QMT V3的分类体系，用于走弱期回避A股)
# 注意：此分类包含所有可能出现在池中的ETF，运行时自动过滤到当前池
# ================================================================
ETF_CATEGORY_OVERSEAS = {
    # 海外ETF（走弱期可交易）
    'sh513100','sz159509','sh513290','sh513500','sz159529',
    'sh513400','sh513520','sh513030','sh513080','sh513310','sh513730',
    'sz159792','sh513130','sh513050','sz159920','sh513690',
    # 债券ETF（走弱期可交易）
    'sh511380','sh511010','sz511220',
}
ETF_CATEGORY_COMMODITY = {
    # 商品ETF（走弱期可交易）
    'sh518880','sz159980','sz159985','sh501018','sz161226','sz159981',
    'sh512400',
}
# A股ETF = 指数 + 风格 + 行业板块（走弱期回避）


# ======================================================================
# 🎯 七星172策略引擎 (简化版，无震荡期/无动态滤波器)
# ======================================================================

class SevenStar172Engine:
    """
    七星172策略核心引擎
    
    与七星拉普拉斯的主要区别:
    - 无震荡期机制 (无拉普拉斯/高斯滤波器)
    - 有日内卖出黑名单机制
    - 有买入二次检查
    - 佣金费率 0.02% (vs 0.01%)
    - 基准: 沪深300 (vs 国投白银LOF)
    
    V2 [2026/06/02]: 新增QMT V3特性
    - 行情判断 (regime_switch): 走弱期自动回避A股ETF
    - 日内回撤检查 (intraday_drawdown): 买入前跳过日内大幅回撤标的
    """

    def __init__(self, params=None, mode='backtest', etf_filter=None):
        self.params = deepcopy(DEFAULT_PARAMS)
        if params:
            self.params.update(params)
        self.mode = mode

        # 过滤器: 默认用 SevenStar172Filter
        if etf_filter is not None:
            self.filter = etf_filter
        else:
            from strategies.etf.seven_star_base import SevenStar172Filter
            self.filter = SevenStar172Filter()

        # 运行时状态变量
        self.rankings_cache = {'date': None, 'data': None}
        self.profit_protection_sold_today = []  # 日内卖出黑名单
        self.nav_data = {}  # 净值数据缓存 {code: Series}

        # ---- 行情判断状态 (QMT V3) ----
        self.is_a_share_weak = False
        self.weak_period_counter = 0
        self.regime_indexes_data = None  # 监测指数数据缓存

        # ---- V4 沪深300 MA60 状态机 (2026-07-30) ----
        self.hs300_data = None          # 沪深300日线close Series
        self.hs300_state = None         # None=未初始化, 'ON', 'OFF'
        self.hs300_consecutive_on = 0   # 连续在MA60以上的天数
        self.hs300_consecutive_off = 0  # 连续在MA60以下的天数
        self.hs300_cooling_remaining = 0 # 冷静期剩余天数
        self.hs300_nav_high = 0         # 组合净值高水位
        self.hs300_combo_cooling = 0    # 组合止损冷静期

    def reset_state(self):
        """重置所有运行时状态"""
        self.rankings_cache = {'date': None, 'data': None}
        self.profit_protection_sold_today = []
        self.is_a_share_weak = False
        self.weak_period_counter = 0
        self.regime_indexes_data = None
        # V4状态机重置
        self.hs300_data = None
        self.hs300_state = None
        self.hs300_consecutive_on = 0
        self.hs300_consecutive_off = 0
        self.hs300_cooling_remaining = 0
        self.hs300_nav_high = 0
        self.hs300_combo_cooling = 0

    # ---------- 行情判断 (QMT V3) ----------

    def load_regime_indexes(self, data_source, start_date, end_date):
        """加载监测指数数据：沪深300、深证综指、创业板指、中证A500
        优先使用本地index数据，缺失则用已有ETF近似"""
        import os
        index_codes = {
            '沪深300': 'sh000300',
            '创业板指': 'sz399006',
            '上证指数': 'sh000001',   # 近似替代深证综指
            '中证500': 'sh000905',    # 近似替代中证A500
        }
        # QMT原始使用: 000300(沪深300), 399101(深证综指), 399006(创业板指), 000510(中证A500)
        # 本地替代: 000300, 399006, 000001(上证), 000905(中证500)

        data_dir = data_source.data_dir.parent / 'index'
        self.regime_indexes_data = {}

        for name, code in index_codes.items():
            fp = data_dir / f'{code}.csv'
            if not fp.exists():
                # 尝试在etf目录找
                fp_alt = data_source.data_dir / f'{code.replace("sh","").replace("sz","")}.csv'
                if fp_alt.exists():
                    fp = fp_alt

            if fp.exists():
                try:
                    df = pd.read_csv(fp)
                    # 统一列名（兼容大写 Date/Open/Close 等格式）
                    rename_map = {}
                    for c in df.columns:
                        lc = c.lower().strip()
                        if lc == 'date' and c != 'date':
                            rename_map[c] = 'date'
                        elif lc in ('open','high','low','close','volume') and lc != c:
                            rename_map[c] = lc
                    if rename_map:
                        df = df.rename(columns=rename_map)
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.set_index('date').sort_index()
                    if 'close' in df.columns:
                        self.regime_indexes_data[name] = df['close']
                except Exception as e:
                    pass

        if self.regime_indexes_data:
            names = list(self.regime_indexes_data.keys())
            print(f"  行情监测指数: {', '.join(names)} ({len(names)}个)")
        else:
            print(f"  ⚠️ 未找到监测指数数据，行情判断将跳过")

    def check_regime(self, date):
        """..."""
        if not self.params['enable_regime_switch']:
            self.is_a_share_weak = False
            return

        if self.regime_indexes_data is None or len(self.regime_indexes_data) == 0:
            return

        ma_lookback = self.params['weak_period_ma_lookback']
        threshold = max(2, int(len(self.regime_indexes_data) * 0.75))

        below_count, above_count = 0, 0
        total = 0

        for name, close_series in self.regime_indexes_data.items():
            mask = close_series.index <= pd.Timestamp(date)
            hist = close_series[mask]
            if len(hist) < ma_lookback + 1:
                continue
            total += 1
            current_price = hist.iloc[-1]
            ma_val = hist.iloc[-(ma_lookback+1):-1].mean()
            if current_price < ma_val:
                below_count += 1
            else:
                above_count += 1

        if total == 0:
            return

        old_state = self.is_a_share_weak

        if not self.is_a_share_weak:
            if below_count >= threshold:
                self.is_a_share_weak = True
                self.weak_period_counter = 0
                if self.params['enable_avoid_a_share']:
                    # Use ASCII-only to avoid encoding issues on Windows
                    s = 'WEAK: %d/%d indices below MA%d -> avoid A-share' % (below_count, total, ma_lookback)
                    print('  [%s] %s' % (date, s))
        else:
            self.weak_period_counter += 1
            if above_count >= threshold:
                self.is_a_share_weak = False
                self.weak_period_counter = 0
                s = 'NORMAL: %d/%d indices above MA%d' % (above_count, total, ma_lookback)
                print('  [%s] %s' % (date, s))
            elif self.weak_period_counter >= self.params['weak_period_max_days']:
                self.is_a_share_weak = False
                self.weak_period_counter = 0
                s = 'TIMEOUT: weak period forced exit after %d days' % self.params['weak_period_max_days']
                print('  [%s] %s' % (date, s))

        if old_state != self.is_a_share_weak:
            self.rankings_cache = {'date': None, 'data': None}

    def get_active_pool(self, full_pool):
        """根据行情状态获取当前可交易的ETF池"""
        if not self.params['enable_avoid_a_share']:
            return full_pool
        if not self.is_a_share_weak:
            return full_pool

        # 走弱期：仅海外 + 商品 + 债券
        active = [c for c in full_pool
                  if c in ETF_CATEGORY_OVERSEAS or c in ETF_CATEGORY_COMMODITY]
        return active

    def check_intraday_drawdown(self, etf_code, current_price, hist_df, date):
        """买入前日内回撤检查（近似：用当日 open vs close 计算回撤，而非分钟级 high）
        返回 True 表示处于回撤状态 → 不宜买入"""
        if not self.params.get('enable_intraday_drawdown', True):
            return False
        if not self.is_a_share_weak:
            return False  # 仅走弱期启用

        threshold = self.params.get('intraday_drawdown_threshold', 0.02)
        try:
            mask = hist_df.index == pd.Timestamp(date)
            today_rows = hist_df[mask]
            if len(today_rows) == 0:
                return False
            today_open = today_rows['open'].iloc[0]
            if today_open <= 0:
                return False
            # 用开盘价近似日内高点（实际QMT用分钟级最高价）
            drawdown = (today_open - current_price) / today_open
            if drawdown >= threshold:
                return True
        except Exception:
            pass
        return False

    def reset_daily_blacklist(self):
        """每日开盘清空黑名单 (对应聚宽 check_positions 中的重置)"""
        self.profit_protection_sold_today = []

    # ---------- 盈利保护检查 ----------

    def check_profit_protection(self, etf_code, current_price, hist_df, check_date):
        """从最近N日最高点回撤超过阈值则触发盈利保护"""
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
                return True
        except Exception:
            pass
        return False

    # ---------- 溢价率计算 ----------

    def get_premium_rate(self, etf_code, check_date):
        """
        获取溢价率（与聚宽原版一致：用前一日净值计算）
        返回 (premium_rate, price, net_value) 或 (None, None, None)
        """
        if not self.params.get('enable_premium_filter', True):
            return None, None, None
        if etf_code not in self.nav_data:
            return None, None, None

        nav_series = self.nav_data.get(etf_code)
        if nav_series is None or len(nav_series) == 0:
            return None, None, None

        check_ts = pd.Timestamp(check_date)
        # 获取前一日净值（聚宽原版逻辑：prev_date = 前一个交易日）
        mask = nav_series.index < check_ts  # 严格小于，取前一日
        available = nav_series[mask]
        if len(available) == 0:
            return None, None, None

        # 向前搜索最多5个交易日（与聚宽原版max_back_days=5一致）
        recent = available.tail(5)
        net_value = float(recent.iloc[-1])
        used_date = str(recent.index[-1].date())
        return None, net_value, used_date  # price 由调用方提供

    # ---------- 成交量比 ----------

    def get_volume_ratio(self, hist_df, check_date):
        """计算当日成交量与过去N日均量的比值"""
        lookback = self.params['volume_lookback']
        threshold = self.params['volume_threshold']

        try:
            mask = hist_df.index <= pd.Timestamp(check_date)
            hist_to_date = hist_df[mask]
            if len(hist_to_date) < lookback + 1:
                return None

            vols = hist_to_date['volume'].tail(lookback + 1)
            avg_vol = vols.iloc[:-1].mean()
            current_vol = vols.iloc[-1]

            if avg_vol > 0:
                ratio = current_vol / avg_vol
                if ratio > threshold:
                    return ratio
        except Exception:
            pass
        return None

    # ---------- 核心排名计算 ----------

    # ---------- V4 行业轮动: 沪深300 MA60 状态机 (2026-07-30移植) ----------

    def init_hs300_state_machine(self, data_source, start_date):
        """加载沪深300数据并初始化状态机。回测启动时通过回放历史数据建立状态记忆。"""
        from pathlib import Path
        data_dir = data_source.data_dir
        hs300_paths = [
            data_dir.parent / 'index' / 'sh000300.csv',
            data_dir / '000300.csv',
            data_dir / 'sh000300.csv',
        ]
        for fp in hs300_paths:
            if fp.exists():
                df = pd.read_csv(fp)
                rename_map = {}
                for c in df.columns:
                    lc = c.lower().strip()
                    if lc == 'date' and c != 'date': rename_map[c] = 'date'
                    elif lc in ('open','high','low','close','volume') and lc != c: rename_map[c] = lc
                if rename_map: df = df.rename(columns=rename_map)
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                if 'close' in df.columns:
                    self.hs300_data = df['close']
                    break

        if self.hs300_data is None or len(self.hs300_data) < self.params['hs300_ma_period']:
            print("  [V4状态机] ⚠️ 未找到沪深300数据，跳过")
            return

        # 回放历史数据: 从数据起始日到 start_date 前一天
        start_ts = pd.Timestamp(start_date)
        mask = self.hs300_data.index < start_ts
        hist_dates = self.hs300_data[mask].index
        print(f"  [V4状态机] 沪深300 历史回放: {len(hist_dates)} 天 → {start_date} 启动")

        for dt in hist_dates:
            self._step_hs300_state(dt, portfolio_value=None)

    def _step_hs300_state(self, date, portfolio_value=None):
        """单步推进状态机。portfolio_value 用于组合回撤检查（仅回测启动后传入）"""
        p = self.params
        ma_period = p['hs300_ma_period']
        buf = p['hs300_buffer_pct']
        confirm = p['hs300_confirm_days']
        slope_lb = p['hs300_slope_lookback']

        # 获取沪深300当前收盘价和MA60
        mask = self.hs300_data.index <= pd.Timestamp(date)
        hist = self.hs300_data[mask]
        if len(hist) < ma_period + slope_lb:
            return
        close = float(hist.iloc[-1])
        ma60 = float(hist.iloc[-ma_period:].mean())
        ma60_slope_ok = float(hist.iloc[-slope_lb:].mean()) > float(hist.iloc[-(ma_period):-(ma_period-slope_lb)].mean())

        # 组合回撤检查 (仅当有实际净值时)
        if portfolio_value is not None and self.hs300_nav_high > 0 and self.hs300_combo_cooling == 0:
            dd = 1 - portfolio_value / self.hs300_nav_high
            if dd >= p['hs300_combo_dd_threshold']:
                self.hs300_state = 'OFF'
                self.hs300_consecutive_on = 0
                self.hs300_consecutive_off = confirm
                self.hs300_combo_cooling = p['hs300_combo_dd_cooling']
                self.hs300_nav_high = portfolio_value  # 就地重置高水位
                print('  [%s] COMBO_STOP: DD %.1f%% >= %.0f%% → OFF + %d日冷静' % (
                    date, dd*100, p['hs300_combo_dd_threshold']*100, p['hs300_combo_dd_cooling']))
                return

        # 更新高水位
        if portfolio_value is not None:
            if portfolio_value > self.hs300_nav_high:
                self.hs300_nav_high = portfolio_value

        # 状态机主逻辑
        if self.hs300_state is None:
            # 初始状态: 根据当前MA60位置设定
            self.hs300_state = 'ON' if close > ma60 * (1 + buf) else 'OFF'
            self.hs300_consecutive_on = 1 if self.hs300_state == 'ON' else 0
            self.hs300_consecutive_off = 1 if self.hs300_state == 'OFF' else 0
            if close > 0:
                self.hs300_nav_high = portfolio_value or 1000000
            return

        # 冷却期倒计时
        if self.hs300_cooling_remaining > 0:
            self.hs300_cooling_remaining -= 1
            return
        if self.hs300_combo_cooling > 0:
            self.hs300_combo_cooling -= 1
            if self.hs300_combo_cooling == 0:
                # 冷静期结束 → 重新初始化状态
                self.hs300_state = 'ON' if close > ma60 * (1 + buf) else 'OFF'
                self.hs300_consecutive_on = 1 if self.hs300_state == 'ON' else 0
                self.hs300_consecutive_off = 1 if self.hs300_state == 'OFF' else 0
                self.hs300_nav_high = portfolio_value or self.hs300_nav_high
                print('  [%s] COOLING END → %s' % (date, self.hs300_state))
            return

        # ON/OFF 判定
        if self.hs300_state == 'OFF':
            if close > ma60 * (1 + buf):
                self.hs300_consecutive_on += 1
                self.hs300_consecutive_off = 0
            else:
                self.hs300_consecutive_on = 0
                self.hs300_consecutive_off += 1

            if self.hs300_consecutive_on >= confirm and ma60_slope_ok:
                self.hs300_state = 'ON'
                self.hs300_cooling_remaining = p['hs300_cooling_days']
                print('  [%s] STATE: OFF→ON (close=%.0f MA60=%.0f %+.1f%%)' % (
                    date, close, ma60, (close/ma60-1)*100))
        else:
            if close < ma60 * (1 - buf):
                self.hs300_consecutive_off += 1
                self.hs300_consecutive_on = 0
            else:
                self.hs300_consecutive_off = 0
                self.hs300_consecutive_on += 1

            if self.hs300_consecutive_off >= confirm:
                self.hs300_state = 'OFF'
                self.hs300_cooling_remaining = p['hs300_cooling_days']
                print('  [%s] STATE: ON→OFF (close=%.0f MA60=%.0f %+.1f%%)' % (
                    date, close, ma60, (close/ma60-1)*100))

    def get_hs300_can_trade(self):
        """查询当前状态机是否允许交易"""
        if not self.params.get('enable_hs300_state_machine', False):
            return True
        if self.hs300_state is None:
            return True  # 未初始化 → 默认允许
        return self.hs300_state == 'ON' and self.hs300_cooling_remaining == 0 and self.hs300_combo_cooling == 0

    def get_hs300_state_display(self):
        """当前状态机显示文本"""
        if not self.params.get('enable_hs300_state_machine', False):
            return 'OFF(未启用)'
        state = self.hs300_state or 'INIT'
        extras = []
        if self.hs300_cooling_remaining > 0: extras.append('cool%d' % self.hs300_cooling_remaining)
        if self.hs300_combo_cooling > 0: extras.append('combo%d' % self.hs300_combo_cooling)
        return state + ('(' + ','.join(extras) + ')' if extras else '')

    # ---------- 排名计算 ----------

    def get_ranked_etfs(self, all_etf_data, current_prices, check_date):
        """
        计算所有ETF的动量得分，应用全部过滤条件，返回按得分降序的列表
        对应聚宽原版的 get_cached_rankings + get_ranked_etfs + calculate_momentum_metrics
        """
        # 检查缓存
        if self.rankings_cache['date'] == check_date and self.rankings_cache['data'] is not None:
            return self.rankings_cache['data']

        etf_metrics = []
        lookback_days = self.params['lookback_days']
        short_lookback = self.params['short_lookback_days']

        for etf_code in ETF_POOL:
            df = all_etf_data.get(etf_code)
            if df is None or len(df) < lookback_days + 10:
                continue

            # 截取到当前日期的数据
            mask = df.index <= pd.Timestamp(check_date)
            hist = df[mask]
            if len(hist) < lookback_days:
                continue

            close_series = hist['close'].values
            # 【修复】close_series 已包含当天收盘价，不应重复追加
            # 聚宽原版中 attribute_history 不含当天，才需要 append current_price
            # 本地回测中 hist 已截取到当天，直接用即可
            close_full = close_series
            current_price = close_series[-1]
            if current_price <= 0:
                continue

            # ===== 可插拔过滤器 (策略独立) =====
            nav_s = self.nav_data.get(etf_code)
            # 【修复】传入hist(截止到当天)而非df(全量数据), 防止过滤器使用未来数据
            is_filtered, reasons = self.filter.check(etf_code, current_price, hist, check_date, self.params, nav_s)
            if is_filtered:
                continue

            # ===== 长期动量计算 (得分核心) =====
            recent = close_full[-(lookback_days + 1):]
            y = np.log(np.maximum(recent, 1e-10))
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_ret = math.exp(slope * 250) - 1

            # R² (趋势稳定性)
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

            score = annualized_ret * r_squared

            # 短期年化 (仅用于日志/调试, 不影响排名)
            short_lookback = self.params.get('short_lookback_days', 10)
            if len(close_full) >= short_lookback + 1:
                short_return = close_full[-1] / close_full[-(short_lookback + 1)] - 1
                short_annualized = (1 + short_return) ** (250 / short_lookback) - 1
            else:
                short_annualized = 0

            etf_metrics.append({
                'etf': etf_code,
                'etf_name': ETF_NAMES.get(etf_code, etf_code),
                'annualized_returns': annualized_ret,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
                'short_annualized': short_annualized,
            })

        # 按得分降序
        etf_metrics.sort(key=lambda x: x['score'], reverse=True)

        # 缓存
        self.rankings_cache = {'date': check_date, 'data': etf_metrics}
        return etf_metrics

    def _calc_annualized_returns(self, price_series, lookback_days):
        """计算加权年化收益率"""
        recent = price_series[-(lookback_days + 1):]
        y = np.log(np.maximum(recent, 1e-10))
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, _ = np.polyfit(x, y, 1, w=weights)
        return math.exp(slope * 250) - 1


# ======================================================================
# ⚙️ 七星172回测引擎
# ======================================================================

class BacktestEngine172:
    """
    七星172事件驱动回测引擎
    
    逐日模拟交易，保留聚宽原版的调度逻辑：
    - 09:10 检查持仓日志 + 清空黑名单
    - 11:00 盈利保护检查 (卖出并加入黑名单)
    - 13:10 卖出操作
    - 13:11 买入操作 (含黑名单过滤 + 二次检查)
    - 15:10 收盘重置
    """

    def __init__(self, data_source, engine_params=None, etf_filter=None):
        self.data_source = data_source
        self.engine = SevenStar172Engine(engine_params, mode='backtest', etf_filter=etf_filter)
        self.portfolio = None
        self.results = {}
        self.commission_rate = 0.0002  # 七星172的佣金费率 (vs 拉普拉斯0.0001)
        self.min_commission = 5
        self.panic_days = 0  # 成分股MA恐慌期触发天数 (QMT扩展统计)
        self.panic_idx = []  # 恐慌日在trade_dates中的索引序列 (用于算触发次数/每段持续天数)

    def run(self, start_date, end_date, initial_cash=1000000):
        """
        执行完整回测
        
        参数:
            start_date: 回测起始日期 (str)
            end_date: 回测结束日期 (str)
            initial_cash: 初始资金
        """
        print("=" * 70)
        print("七星172策略 (GLM5修复版) - 本地回测引擎")
        print(f"回测区间: {start_date} ~ {end_date} | 初始资金: {initial_cash:,.0f}")
        print(f"佣金费率: {self.commission_rate*100:.3f}% (双边)")
        print("=" * 70)

        # [1] 加载数据
        print("\n[1/4] 加载ETF历史数据...")
        all_etf_data = self.data_source.load_all_etfs(start_date, end_date)
        print(f"  成功加载 {len(all_etf_data)}/{len(ETF_POOL)} 只ETF")

        # 加载净值数据（用于溢价率过滤）
        nav_data = self.data_source.load_all_navs()
        self.engine.nav_data = nav_data
        nav_count = len(nav_data)
        print(f"  净值数据: {nav_count}/{len(ETF_POOL)} 只ETF (溢价率过滤{'启用' if self.engine.params.get('enable_premium_filter') else '关闭'})")

        # 加载监测指数数据（行情判断用）
        if self.engine.params.get('enable_regime_switch', False):
            self.engine.load_regime_indexes(self.data_source, start_date, end_date)

        if len(all_etf_data) == 0:
            print("[FATAL] 无可用数据! 请检查 data_dir 是否包含ETF CSV文件")
            return None

        # [2] 获取交易日
        trade_dates = self.data_source.get_trade_dates(start_date, end_date)
        print(f"  交易日数: {len(trade_dates)} 天")

        # 初始化
        self.engine.reset_state()
        self.portfolio = Portfolio(
            initial_cash=initial_cash,
            commission_rate=self.commission_rate,
            min_commission=self.min_commission
        )

        # V4状态机: 加载沪深300 + 回放历史 (必须在 reset_state 之后)
        if self.engine.params.get('enable_hs300_state_machine', False):
            self.engine.init_hs300_state_machine(self.data_source, start_date)

        # [3] 逐日回测
        print(f"\n[2/4] 开始逐日回测...")
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

            # ===== 09:10 持仓日志 + 清空黑名单 =====
            self._log_positions(i, td)
            self.engine.reset_daily_blacklist()

            # ===== 09:40 行情判断 (QMT V3) =====
            self.engine.check_regime(td)

            # ===== V4状态机: 沪深300 MA60 (2026-07-30移植) =====
            if self.engine.params.get('enable_hs300_state_machine', False):
                pv = self.portfolio.cash + self.portfolio.total_value
                self.engine._step_hs300_state(td, portfolio_value=pv)
            hs300_ok = self.engine.get_hs300_can_trade()

            # ===== 成分股MA10恐慌期判定 (QMT扩展, 默认关闭, 不影响172) =====
            panic = False
            if self.engine.params.get('enable_panic_regime', False):
                panic = self._check_panic_regime(all_etf_data, current_prices, td)
                if panic:
                    self.panic_days += 1
                    self.panic_idx.append(i)

            # ===== 11:00 盈利保护检查 =====
            self._run_profit_protection(current_prices, all_etf_data, td)

            if panic or not hs300_ok:
                # 恐慌期或状态机OFF: 清仓空仓防守, 不执行买入
                self._panic_liquidate(current_prices, td)
            else:
                # ===== 13:10 卖出操作 =====
                self._run_sell(current_prices, all_etf_data, td)

                # ===== 13:11 买入操作 =====
                self._run_buy(current_prices, all_etf_data, td)

            # 记录每日净值
            self.portfolio.record_daily_value(td)

        print("-" * 70)

        # [4] 生成报告
        print(f"\n[3/4] 回测完成! 生成报告...")
        results = self._generate_results(trade_dates, initial_cash)
        self.results = results
        return results

    def _log_positions(self, i, date):
        """持仓日志 (每20天打印一次)"""
        if i % 20 != 0:
            return
        held = self.portfolio.get_position_codes()
        if held:
            for code in held[:3]:
                pos = self.portfolio.positions[code]
                pnl = (pos['last_price'] - pos['cost_price']) / pos['cost_price'] * 100 if pos['cost_price'] > 0 else 0
                print(f"  [{date}] 持仓: {code} {ETF_NAMES.get(code,'')} "
                      f"数量{pos['shares']} 成本{pos['cost_price']:.3f} 现价{pos['last_price']:.3f} PnL:{pnl:+.2f}%")

    def _check_panic_regime(self, all_etf_data, current_prices, date):
        """成分股MA10恐慌期判定 (QMT扩展, 默认关闭)
        统计成分股池中"最新价跌破MA10"的比例, 超过阈值(默认80%)→恐慌期→空仓防守。
        分母用实际加载的成分股池(all_etf_data), 不依赖全局ETF_POOL(避免monkey-patch绑定问题)。
        MA10口径: 最近lb个交易日收盘价均值(含当日), 即标准10日线。
        """
        lb = self.engine.params.get('panic_ma_lookback', 10)
        thr = self.engine.params.get('panic_threshold', 0.80)
        td_ts = pd.Timestamp(date)
        below = 0
        total = 0
        for code, df in all_etf_data.items():
            hist = df.loc[df.index <= td_ts, 'close']
            if len(hist) < lb:
                continue
            cur = current_prices.get(code, 0)
            if cur <= 0:
                cur = float(hist.iloc[-1])
            if cur <= 0:
                continue
            ma = float(hist.iloc[-lb:].mean())
            total += 1
            if cur < ma:
                below += 1
        if total == 0:
            return False
        ratio = below / total
        is_panic = ratio > thr
        if is_panic:
            print(f"  [{date}] 🔴 PANIC: {below}/{total}={ratio:.0%} 成分股跌破MA{lb} (>{thr:.0%}) → 空仓防守")
        return is_panic

    def _panic_liquidate(self, current_prices, date):
        """恐慌期空仓防守: 清仓全部持仓, 持币 (QMT扩展)"""
        for sec in list(self.portfolio.get_position_codes()):
            if sec in current_prices and current_prices[sec] > 0:
                if self.portfolio.sell_all(sec, current_prices[sec], date, reason='恐慌期空仓防守'):
                    print(f"  [{date}] 🛡️ PANIC_LIQUIDATE: {sec} {ETF_NAMES.get(sec,'')} @{current_prices[sec]:.3f}")

    def _run_profit_protection(self, current_prices, all_etf_data, date):
        """执行盈利保护检查 (11:00)"""
        if not self.engine.params['enable_profit_protection']:
            return

        for code in list(self.portfolio.get_position_codes()):
            if code not in all_etf_data:
                continue
            hist_df = all_etf_data[code]
            cur_price = current_prices.get(code, 0)
            if cur_price <= 0:
                continue

            if self.engine.check_profit_protection(code, cur_price, hist_df, date):
                if self.portfolio.sell_all(code, cur_price, date, reason='盈利保护'):
                    print(f"  [{date}] 🛡️ PROFIT_PROTECT: {code} {ETF_NAMES.get(code,'')} @{cur_price:.3f}")
                    # 【关键】加入黑名单，防止尾盘买回
                    if code not in self.engine.profit_protection_sold_today:
                        self.engine.profit_protection_sold_today.append(code)

    def _run_sell(self, current_prices, all_etf_data, date):
        """卖出操作 (13:10) - 对应聚宽原版 etf_sell_trade"""
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)

        target_etfs = []
        for m in ranked[:self.engine.params['holdings_num']]:
            if m['score'] >= self.engine.params['min_score_threshold']:
                target_etfs.append(m['etf'])

        # 【修复】补齐防御ETF保护：无合格目标时，防御ETF不卖出（与聚宽原版一致）
        if not target_etfs:
            target_etfs = [DEFENSIVE_ETF]

        target_set = set(target_etfs)

        for sec in list(self.portfolio.get_position_codes()):
            if sec not in target_set:
                if sec not in current_prices or current_prices[sec] <= 0:
                    continue
                if self.portfolio.sell_all(sec, current_prices[sec], date, reason='调出目标'):
                    print(f"  [{date}] 📤 SELL: {sec} {ETF_NAMES.get(sec,'')} @{current_prices[sec]:.3f}")

    def _run_buy(self, current_prices, all_etf_data, date):
        """买入操作 (13:11) - 对应聚宽原版 etf_buy_trade (含GLM5修复 + QMT V3走弱期防御)"""
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)

        # ===== QMT V3: 走弱期过滤 —— 获取当前可交易池 =====
        active_pool = self.engine.get_active_pool(list(all_etf_data.keys()))

        # 打印前5名
        if ranked:
            tops = ", ".join([f"{m['etf']}({m['score']:.4f})" for m in ranked[:5]])
            print(f"  [{date}] TOP5: {tops}")

        # 确定目标ETF (逐个尝试)
        target_etfs = []
        for m in ranked:
            if len(target_etfs) >= self.engine.params['holdings_num']:
                break

            etf = m['etf']
            cur_price = m['current_price']

            # ===== QMT V3: 走弱期回避A股 =====
            if etf not in active_pool and etf != DEFENSIVE_ETF:
                continue

            # ===== QMT V3: 日内回撤检查（买入前） =====
            hist_df = all_etf_data.get(etf)
            if self.engine.check_intraday_drawdown(etf, cur_price, hist_df, date):
                continue

            # 【GLM5修复1】买入二次检查：补上作者文档声称但漏掉的盈利保护检查
            if self.engine.params['enable_profit_protection']:
                if hist_df is not None:
                    if self.engine.check_profit_protection(etf, cur_price, hist_df, date):
                        continue

            # 【GLM5修复2】黑名单检查：禁止买回今日盈利保护卖出的标的
            if etf in self.engine.profit_protection_sold_today:
                print(f"  [{date}] 🚫 BLACKLIST: {etf} {ETF_NAMES.get(etf,'')} 今日已盈利保护卖出，禁止买回")
                continue

            # 【新思路验证 2026-08-17】当天收盘下跌则不买入
            if self.engine.params.get('enable_no_down_day_buy', False):
                if hist_df is not None:
                    hist_cut = hist_df[hist_df.index <= pd.Timestamp(date)]
                    if len(hist_cut) >= 2:
                        today_close = hist_cut['close'].iloc[-1]
                        prev_close = hist_cut['close'].iloc[-2]
                        if today_close < prev_close:
                            print(f"  [{date}] 📉 SKIP_DOWN: {etf} {ETF_NAMES.get(etf,'')} 当日收盘{today_close:.3f}<前收{prev_close:.3f}，不买入")
                            continue

            target_etfs.append(etf)

        # 防御模式
        if not target_etfs:
            target_etfs = [DEFENSIVE_ETF]
            print(f"  [{date}] 🛡️ DEFENSE -> {DEFENSIVE_ETF} {ETF_NAMES.get(DEFENSIVE_ETF,'')}")

        # 等权分配 (原版逻辑, 预留佣金空间防止余额不足)
        total_val = self.portfolio.total_value * 0.998  # 预留0.2%给佣金+取整误差
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
            # 5%容差不调仓
            if abs(diff) < target_per_etf * 0.05 and current_val > 0:
                continue

            price = current_prices[etf]
            if diff > 0:  # 买入
                target_amount = int(diff / price // 100) * 100
                if target_amount <= 0 and diff > min_money:
                    target_amount = 100
                if target_amount * price >= min_money:
                    if self.portfolio.buy(etf, target_amount, price, date,
                                          reason=f'排名{target_etfs.index(etf)+1}'):
                        print(f"  [{date}] 📥 BUY: {etf} {ETF_NAMES.get(etf,'')} "
                              f"{target_amount}份@{price:.3f}")

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
        max_dd_start, max_dd_end = '', ''
        for i, v in enumerate(values):
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_end = str(dv[i]['date'])

        # 夏普比率 (年化)
        if len(returns_arr) > 1:
            daily_ret = np.diff(values) / values[:-1]
            ret_mean = np.mean(daily_ret)
            ret_std = np.std(daily_ret)
            sharpe = (ret_mean / ret_std * np.sqrt(252)) if ret_std > 0 else 0
        else:
            sharpe = 0

        # 卡尔马比率
        calmar = abs(total_ret * 252 / len(trade_dates)) / max_dd if max_dd > 0 else 0

        # 交易统计
        trades = self.portfolio.trade_log
        n_trades = len(trades)
        buys = sum(1 for t in trades if t['action'] == 'BUY')
        sells = sum(1 for t in trades if t['action'] == 'SELL')

        # 胜率
        sell_trades = [t for t in trades if t['action'] == 'SELL' and 'pnl_pct' in t]
        wins = [t for t in sell_trades if t['pnl_pct'] > 0]
        losses = [t for t in sell_trades if t['pnl_pct'] <= 0]
        win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0

        results = {
            'strategy': '七星172 (GLM5修复版)',
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
            'avg_win_pct': round(sum(t['pnl_pct'] for t in wins) / len(wins) * 100, 2) if wins else 0,
            'avg_loss_pct': round(sum(t['pnl_pct'] for t in losses) / len(losses) * 100, 2) if losses else 0,
            'final_holdings': self.portfolio.get_position_codes(),
            'panic_days': self.panic_days,
            'panic_idx': list(self.panic_idx),
            'daily_values': dv,
            'trade_log': trades,
            'engine_params': self.engine.params,
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
        print(f"  总交易:    {results['total_trades']} (买{results['buy_trades']}/卖{results['sell_trades']})")
        print(f"  胜率:      {results['win_rate_pct']:.1f}% ({len(wins)}赢/{len(losses)}负)")
        if wins:
            print(f"  平均盈利:  +{results['avg_win_pct']:.2f}%")
        if losses:
            print(f"  平均亏损:  {results['avg_loss_pct']:.2f}%")

        return results


# ======================================================================
# 🏃 主入口
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description='七星172策略 v1.0 - 本地回测')
    parser.add_argument('--start', type=str, default='2024-01-01', help='回测起始日期')
    parser.add_argument('--end', type=str, default='2026-05-27', help='回测结束日期')
    parser.add_argument('--cash', type=float, default=10000, help='初始资金')
    parser.add_argument('--data-dir', type=str, default=None, help='数据目录')
    parser.add_argument('--holdings', type=int, default=1, help='持仓数量')
    parser.add_argument('--lookback', type=int, default=25, help='动量回看天数')
    parser.add_argument('--no-protection', action='store_true', help='关闭盈利保护')
    parser.add_argument('--no-volume', action='store_true', help='关闭成交量过滤')
    parser.add_argument('--no-short-momentum', action='store_true', help='关闭短期动量过滤')
    parser.add_argument('--no-premium', action='store_true', help='关闭溢价率过滤')
    parser.add_argument('--no-regime', action='store_true', help='关闭行情判断(regime_switch)')
    parser.add_argument('--no-avoid-a', action='store_true', help='关闭避A股走弱(avoid_a_share)')
    parser.add_argument('--no-intraday-dd', action='store_true', help='关闭日内回撤检查(intraday_drawdown)')
    parser.add_argument('--premium-only', action='store_true', help='仅保留溢价率过滤,关闭其他所有过滤器')
    parser.add_argument('--original', action='store_true', help='使用聚宽原版172参数(启用原版4过滤器+关闭QMT V3)')
    parser.add_argument('--commission', type=float, default=0.0002, help='佣金费率')

    args = parser.parse_args()

    # 数据源
    data_dir = args.data_dir or str(DATA_DIR)
    if not os.path.isdir(data_dir):
        # 尝试在项目根目录下找
        alt = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'
        if alt.is_dir():
            data_dir = str(alt)

    ds = LocalDataSource(data_dir)

    # 参数
    # --premium-only: 只保留溢价率过滤,关闭所有其他过滤器
    if args.premium_only:
        args.no_protection = True
        args.no_regime = True
        args.no_avoid_a = True
        args.no_intraday_dd = True

    # --original: 恢复聚宽原版172参数 (启用原版4过滤器 + 关闭QMT V3)
    if args.original:
        args.no_regime = True       # 原版没有行情判断
        args.no_avoid_a = True      # 原版没有回避A股
        args.no_intraday_dd = True  # 原版没有日内回撤

    params = {
        'lookback_days': args.lookback,
        'holdings_num': args.holdings,
        'enable_profit_protection': not args.no_protection,
        'enable_volume_check': True if args.original else (not args.no_volume),
        'use_short_momentum_filter': True if args.original else (not args.no_short_momentum),
        'enable_premium_filter': not args.no_premium,
        'enable_regime_switch': not getattr(args, 'no_regime', False),
        'enable_avoid_a_share': not getattr(args, 'no_avoid_a', False),
        'enable_intraday_drawdown': not getattr(args, 'no_intraday_dd', False),
    }

    # --original: 额外恢复原版参数值
    if args.original:
        params['loss'] = 0.97                    # 原版: 近3日单日跌幅>3%过滤
        params['min_score_threshold'] = 0        # 原版: 得分<0过滤
        params['max_score_threshold'] = 100.0    # 原版: 得分>100过滤
        params['volume_return_limit'] = 1        # 原版: 年化>100%时启用放量过滤
        params['short_momentum_threshold'] = 0.0 # 原版: 短期动量<0过滤

    # 回测
    engine = BacktestEngine172(ds, engine_params=params)
    engine.commission_rate = args.commission
    results = engine.run(args.start, args.end, args.cash)

    if results is None:
        print("回测失败!")
        return

    # 保存摘要JSON
    summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
    summary_path = RESULTS_DIR / f'七星172_{args.start}_{args.end}_summary.json'
    import json
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📄 摘要已保存: {summary_path}")

    # 保存完整交易记录
    trades_path = RESULTS_DIR / f'七星172_{args.start}_{args.end}_trades.json'
    with open(trades_path, 'w', encoding='utf-8') as f:
        json.dump(results['trade_log'], f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📄 交易记录已保存: {trades_path}")

    # 生成HTML报告并发送邮件
    _generate_html_and_email(results, args.start, args.end, args.cash)

    return results


def _generate_html_and_email(results, start, end, initial_cash):
    """生成172回测HTML报告并邮件发送"""
    import json, smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from datetime import datetime

    trades = results.get('trade_log', [])
    r = results
    now_str = datetime.now().strftime('%Y%m%d_%H%M')

    # 最近20条交易
    recent = trades[-20:][::-1] if trades else []
    trade_rows = ""
    for t in recent:
        d = '买入' if t['action']=='BUY' else '卖出'
        bg = '#E2EFDA' if t['action']=='BUY' else '#FCE4D6'
        pnl = t.get('pnl_pct')
        if pnl is not None and pnl != 0:
            ps = f'+{pnl*100:.2f}%' if pnl > 0 else f'{pnl*100:.2f}%'
            pc = '#28A745' if pnl > 0 else '#DC3545'
        else:
            ps = '-'; pc = '#888'
        tv = t.get('total_value', 0)
        trade_rows += f"""<tr style="background:{bg};white-space:nowrap;">
            <td style="padding:4px 6px;">{t['date']}</td>
            <td style="padding:4px 6px;font-weight:bold;">{d}</td>
            <td style="padding:4px 6px;">{t.get('name','')}</td>
            <td style="padding:4px 6px;color:#888;font-size:11px;">{t['code']}</td>
            <td style="padding:4px 6px;text-align:right;">{t['price']:.3f}</td>
            <td style="padding:4px 6px;text-align:right;">{t.get('shares',0)}</td>
            <td style="padding:4px 6px;text-align:right;">¥{t.get('amount',0):,.0f}</td>
            <td style="padding:4px 6px;font-size:11px;color:#555;">{t.get('reason','')}</td>
            <td style="padding:4px 6px;text-align:right;font-weight:bold;color:{pc};">{ps}</td>
            <td style="padding:4px 6px;text-align:right;font-weight:bold;color:#1F4E79;">¥{tv:,.0f}</td></tr>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:15px;background:#F0F2F5;}}
.card{{background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#1F4E79;color:#fff;padding:6px 8px;text-align:left;}}
td{{padding:4px 6px;border-bottom:1px solid #eee;}}
</style></head><body>
<div class="card">
<h1 style="font-size:18px;color:#1F4E79;margin:0;">七星172策略 3年回测报告</h1>
<p style="font-size:12px;color:#888;margin:5px 0;">{start} ~ {end} | 初始资金: ¥{initial_cash:,.0f} | 佣金: 0.02%</p>
</div>
<div class="card">
<div style="display:flex;flex-wrap:wrap;gap:10px;">
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;">
<div style="font-size:11px;color:#888;">累计收益</div>
<div style="font-size:20px;font-weight:bold;color:{'#28A745' if r['total_return_pct']>0 else '#DC3545'};">{r['total_return_pct']:+.2f}%</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;">
<div style="font-size:11px;color:#888;">年化收益</div>
<div style="font-size:20px;font-weight:bold;">{r['annualized_return_pct']:.1f}%</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;">
<div style="font-size:11px;color:#888;">最大回撤</div>
<div style="font-size:20px;font-weight:bold;color:#DC3545;">-{r['max_drawdown_pct']:.1f}%</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;">
<div style="font-size:11px;color:#888;">夏普比率</div>
<div style="font-size:20px;font-weight:bold;">{r['sharpe_ratio']:.2f}</div></div>
<div style="flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;">
<div style="font-size:11px;color:#888;">终值</div>
<div style="font-size:20px;font-weight:bold;">¥{r['final_value']:,.0f}</div></div>
</div></div>
<div class="card">
<h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">最近20条交易记录 (共{r['total_trades']}笔)</h3>
<div style="overflow-x:auto;"><table>
<tr><th>日期</th><th>方向</th><th>ETF</th><th>代码</th><th>价格</th><th>数量</th><th>金额</th><th>理由</th><th>盈亏</th><th>总资产</th></tr>
{trade_rows}
</table></div></div>
<div style="font-size:11px;color:#888;text-align:center;margin-top:15px;">
七星172策略 (GLM5修复版) | Blakever Trade | {now_str}</div>
</body></html>"""

    # 保存HTML
    html_path = RESULTS_DIR / f'七星172_回测报告_{now_str}.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"📄 HTML报告: {html_path}")

    # 发送邮件
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'七星172 回测报告 {start}~{end} | 收益{r["total_return_pct"]:+.1f}%'
        msg['From'] = '848786642@qq.com'
        msg['To'] = '848786642@qq.com'
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP_SSL('smtp.qq.com', 465) as s:
            s.login('848786642@qq.com', 'ljbtvacrctjobfed')
            s.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())
        print('[OK] 邮件已发送')
    except Exception as e:
        print(f'[WARN] 邮件发送失败: {e}')


if __name__ == '__main__':
    main()
