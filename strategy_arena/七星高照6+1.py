#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照6+1 A股每日模拟盘 — 定时任务脚本
==========================================
策略名称：七星高照6+1
策略版本：V2.0

ETF池配置（精简版）：
  📈投资池（6只）：
    159915 创业板ETF   — A股成长核心
    513100 纳指ETF     — 海外科技龙头
    159985 豆粕ETF     — 农产品周期
    518880 黄金ETF     — 避险+趋势
    501018 南方原油    — 商品周期
161226 白银LOF     — A股贵金属期货
  🔒安全池（1只）：
    511220 城投ETF     — 避风港（无趋势时持有）

策略核心逻辑（继承V1.7.2）：
  1. 加权线性回归动量（短期25天+长期250天）
  2. 急跌过滤（4日内日跌>5%淘汰）
  3. 周频调仓（W-FRI）
  4. 安全池兜底（所有标的无正动量时持有城投ETF）

手续费规则（A股）：
  - 佣金：0.025%（单边），最低5元
  - 印花税：0.05%（仅卖出）
  - 过户费：0.001%（双边）
  - 简化单边费率：买入0.03%，卖出0.08%

T+1规则：
  - 信号T日产生，T+1日开盘价执行
  - 当日买入的ETF次日才可卖出

回测表现（截至2026-04-27）：
  近1年：年化81.80%，夏普1.82，最大回撤-17.99%
  近3年：年化33.23%，夏普1.36，最大回撤-17.36%
  近5年：年化20.02%，夏普1.07，最大回撤-17.34%

数据源：/data/workspace/back_trader_stocks/a/ 本地CSV日频数据
"""

import os, sys, json, math, time, smtplib, warnings, copy, subprocess
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from collections import OrderedDict

warnings.filterwarnings('ignore')
sys.path.insert(0, r'C:\Users\blakehao\.qclaw\workspace\strategy_arena')
from strategy_ranker import compute_total_score, get_grade

# ================================================================
# 🌟 6+1 ETF池定义（七星高照精简版）
# ================================================================
# 投资池：6只精选ETF
INVEST_POOL = [
    '159915_XSHE',   # 创业板ETF — A股成长核心
    '513100_XSHG',   # 纳指ETF — 海外科技龙头
    '159985_XSHE',   # 豆粕ETF — 农产品周期
    '518880_XSHG',   # 黄金ETF — 避险+趋势
    '501018_XSHG',   # 南方原油 — 商品周期
'161226_XSHE',   # 白银LOF — A股贵金属期货
]

# 安全池：1只城投ETF
SAFE_POOL = [
    '511220_XSHG',   # 城投ETF — 避风港
]

# 完整ETF池 = 投资池 + 安全池
CN_ETF_POOL = list(dict.fromkeys(INVEST_POOL + SAFE_POOL))

# 安全资产列表
CN_SAFE = list(SAFE_POOL)

# ETF名称映射
CN_ETF_NAMES = {
    '159915_XSHE': '创业板ETF',
    '513100_XSHG': '纳指ETF',
    '159985_XSHE': '豆粕ETF',
    '518880_XSHG': '黄金ETF',
    '501018_XSHG': '南方原油ETF',
'161226_XSHE': '白银LOF',
    '511220_XSHG': '城投ETF',
}

# 策略名称
STRATEGY_NAME = '七星高照6+1'

# ================================================================
# 费率参数（A股）
# ================================================================
BUY_FEE_RATE = 0.0003    # 买入总费率 ≈ 佣金+过户费
SELL_FEE_RATE = 0.0008   # 卖出总费率 ≈ 佣金+印花税+过户费
MIN_COMMISSION = 5.0     # 最低佣金5元

# ================================================================
# 初始资金
# ================================================================
INIT_CAPITAL = 1_000_000  # 100万

# ================================================================
# 数据与状态路径
# ================================================================
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\a'
ACCOUNT_STATE_FILE = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\cn_daily_sim_account_61.json'
DAILY_OPS_DIR = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\cn_daily_ops_61'


# ================================================================
# 数据加载
# ================================================================
def load_cn_etf_data(etf_pool=None, data_dir=DATA_DIR):
    """加载A股ETF日频数据"""
    if etf_pool is None:
        etf_pool = CN_ETF_POOL
    data = {}
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"  ❌ 数据目录不存在: {data_dir}")
        return data

    for code in etf_pool:
        file_path = data_path / f'{code}.csv'
        if file_path.exists():
            try:
                df = pd.read_csv(file_path, parse_dates=['Date'], index_col='Date')
                if 'Close' in df.columns and len(df) > 100:
                    data[code] = df
            except Exception as e:
                print(f"  ⚠️ 读取{code}失败: {e}")

    print(f"  📊 加载A股ETF数据: {len(data)}/{len(etf_pool)}只")
    return data


# ================================================================
# 实时行情获取（盘中修正涨跌幅和最新价）
# ================================================================
# westock代码 → (内部ETF代码, 名称) 映射
_WESTOCK_CODE_MAP = {
    'sz159915': ('159915_XSHE', '创业板ETF'),
    'sh513100': ('513100_XSHG', '纳指ETF'),
    'sz159985': ('159985_XSHE', '豆粕ETF'),
    'sh518880': ('518880_XSHG', '黄金ETF'),
    'sh501018': ('501018_XSHG', '南方原油ETF'),
    'sz161226': ('161226_XSHE', '白银LOF'),
    'sh511220': ('511220_XSHG', '城投ETF'),
}

def get_realtime_quotes():
    """通过westock-data获取ETF实时行情（最新价+涨跌幅）"""
    results = {}
    for westock_code, (etf_code, name) in _WESTOCK_CODE_MAP.items():
        try:
            proc = subprocess.run(
                ['node', '/data/workspace/.agent/skills/westock-data/scripts/index.js', 'quote', westock_code],
                capture_output=True, text=True, cwd='/data/workspace', timeout=15
            )
            lines = proc.stdout.strip().split('\n')
            if len(lines) >= 3:
                header = [c.strip() for c in lines[0].split('|') if c.strip()]
                data_line = lines[2] if len(lines) > 2 else lines[-1]
                cols = [c.strip() for c in data_line.split('|') if c.strip()]
                price_idx = header.index('price')
                pct_idx = header.index('change_percent')
                results[etf_code] = {
                    'price': float(cols[price_idx]),
                    'change_pct': float(cols[pct_idx]),
                }
        except Exception as e:
            print(f"  ⚠️ 获取{name}实时行情失败: {e}")
    if results:
        print(f"  📡 获取实时行情: {len(results)}/{len(_WESTOCK_CODE_MAP)}只")
    return results


def apply_realtime_to_rankings(rankings, realtime_quotes):
    """用实时行情修正排名表中的涨跌幅和最新价"""
    for r in rankings:
        etf_code = r['etf']
        if etf_code in realtime_quotes:
            q = realtime_quotes[etf_code]
            r['current_price'] = round(q['price'], 4)
            r['daily_change'] = round(q['change_pct'], 2)
    return rankings


# ================================================================
# 七星高照6+1策略信号生成
# ================================================================
def qixing_rotation_strategy(close_prices: pd.DataFrame,
                              etf_pool: list,
                              safe_assets: list,
                              short_lookback: int = 25,
                              long_lookback: int = 250,
                              drop_threshold: float = 0.95,
                              long_score_cap: float = 0.5,
                              short_score_cap: float = 6.0,
                              rebalance_freq: str = 'W-FRI') -> pd.Series:
    """
    七星高照6+1 ETF轮动策略

    核心逻辑（继承V1.7.2）：
    1. 加权线性回归动量（短期+长期）
    2. 急跌过滤（4日窗口日跌>5%淘汰）
    3. 周频调仓
    4. 安全池兜底

    参数:
      close_prices: 宽表，columns=ETF代码，index=Date
      etf_pool: 参与轮动的ETF列表
      safe_assets: 防御ETF列表(无合适标的时持有)
      short_lookback: 短期动量回溯天数(默认25)
      long_lookback: 长期动量回溯天数(默认250)
      drop_threshold: 急跌过滤阈值(日跌超过1-threshold则淘汰)
      long_score_cap: 长期动量得分上限
      short_score_cap: 短期动量得分上限
      rebalance_freq: 调仓频率

    返回:
      pd.Series，index=Date，values=持有的ETF代码
    """
    safe_in_pool = [a for a in safe_assets if a in etf_pool and a in close_prices.columns]
    default_asset = safe_in_pool[0] if safe_in_pool else (etf_pool[-1] if etf_pool else close_prices.columns[0])

    holding = pd.Series(default_asset, index=close_prices.index)

    if len(close_prices) < 15:
        return holding

    # 获取调仓日
    rebal_dates = close_prices.resample(rebalance_freq).last().dropna().index
    rebal_dates = rebal_dates[rebal_dates.isin(close_prices.index)]

    if len(rebal_dates) < 5:
        return holding

    pool_in_data = [a for a in etf_pool if a in close_prices.columns]

    for i, r_date in enumerate(rebal_dates):
        try:
            loc = close_prices.index.get_loc(r_date)
        except KeyError:
            continue

        actual_short = min(short_lookback, loc)
        actual_long = min(long_lookback, loc)

        if actual_long < actual_short or actual_short < 5:
            continue

        best_etf = None
        best_score = -999

        for asset in pool_in_data:
            sp = close_prices[asset].iloc[max(0, loc - actual_short):loc + 1]
            sp = sp.dropna()
            if len(sp) < 5:
                continue

            # 急跌过滤
            if len(sp) >= 4:
                recent = sp.iloc[-4:]
                dropped = False
                for j in range(len(recent) - 1):
                    if recent.iloc[j] > 0:
                        daily_change = recent.iloc[j + 1] / recent.iloc[j]
                        if daily_change < drop_threshold:
                            dropped = True
                            break
                if dropped:
                    continue

            # 加权线性回归动量（短期）
            y = np.log(sp.values.astype(float))
            x = np.arange(len(y), dtype=float)
            w = np.linspace(1, 2, len(y))

            try:
                coeffs = np.polyfit(x, y, 1, w=w)
                slope = coeffs[0]
            except:
                continue

            ann_return = math.exp(slope * 252) - 1
            y_pred = slope * x + coeffs[1]
            ss_res = np.sum(w * (y - y_pred) ** 2)
            y_mean = np.average(y, weights=w)
            ss_tot = np.sum(w * (y - y_mean) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0

            short_score = ann_return * r2
            if not (0 < short_score < short_score_cap):
                short_score = 0

            # 长期动量
            lp = close_prices[asset].iloc[max(0, loc - actual_long):loc + 1]
            lp = lp.dropna()
            if len(lp) < 20:
                combined = short_score
            else:
                y2 = np.log(lp.values.astype(float))
                x2 = np.arange(len(y2), dtype=float)
                w2 = np.linspace(1, 2, len(y2))

                try:
                    coeffs2 = np.polyfit(x2, y2, 1, w=w2)
                    slope2 = coeffs2[0]
                except:
                    combined = short_score
                else:
                    ann2 = math.exp(slope2 * 252) - 1
                    y2_pred = slope2 * x2 + coeffs2[1]
                    ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                    y2_mean = np.average(y2, weights=w2)
                    ss_tot2 = np.sum(w2 * (y2 - y2_mean) ** 2)
                    r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 1e-10 else 0

                    long_score = ann2 * r22
                    if not (long_score > 0 and long_score < long_score_cap):
                        long_score = 0

                    combined = short_score + long_score

            if combined > best_score:
                best_score = combined
                best_etf = asset

        if best_etf is None or best_score <= 0:
            best_etf = default_asset

        # 设置下一调仓周期内的持仓
        if i + 1 < len(rebal_dates):
            next_r = rebal_dates[i + 1]
            mask = (close_prices.index > r_date) & (close_prices.index <= next_r)
        else:
            mask = close_prices.index > r_date

        for idx in close_prices.index[mask]:
            holding[idx] = best_etf

    # 预热期保持默认
    if len(holding) > 20:
        for idx in close_prices.index[:20]:
            holding[idx] = default_asset

    return holding


def _compute_all_etf_rankings(close_prices, etf_pool, safe_assets, target_date,
                               short_lookback=25, long_lookback=250,
                               drop_threshold=0.95, long_score_cap=0.5, short_score_cap=6.0):
    """
    计算所有候选ETF的动量评分排名（用于每日报告和盘中监控）

    返回:
      list of dict，按combined_score降序排列
    """
    target_date = pd.Timestamp(target_date)

    # 获取截至target_date的最后一行数据
    mask = close_prices.index <= target_date
    if not mask.any():
        return []

    loc = close_prices.index.get_loc(close_prices[mask].index[-1])
    latest_row = close_prices.iloc[-1]

    pool_in_data = [a for a in etf_pool if a in close_prices.columns]
    results = []

    for asset in pool_in_data:
        name = CN_ETF_NAMES.get(asset, asset)
        is_safe = asset in safe_assets
        current_price = float(latest_row.get(asset, 0)) if asset in latest_row else 0

        # 当日涨跌幅
        if loc >= 1 and asset in close_prices.columns:
            prev_close = close_prices[asset].iloc[-2] if len(close_prices) > 1 else current_price
            daily_change = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
        else:
            daily_change = 0

        actual_short = min(short_lookback, loc)
        actual_long = min(long_lookback, loc)

        if actual_short < 5:
            results.append({
                'etf': asset, 'name': name,
                'short_score': 0, 'long_score': 0, 'combined_score': 0,
                'is_dropped': True, 'drop_reason': '数据不足(需≥5日)',
                'current_price': round(current_price, 4),
                'daily_change': round(daily_change, 2),
                'is_safe': is_safe, 'is_buyable': False,
            })
            continue

        sp = close_prices[asset].iloc[max(0, loc - actual_short):loc + 1].dropna()
        if len(sp) < 5:
            results.append({
                'etf': asset, 'name': name,
                'short_score': 0, 'long_score': 0, 'combined_score': 0,
                'is_dropped': True, 'drop_reason': '有效数据不足',
                'current_price': round(current_price, 4),
                'daily_change': round(daily_change, 2),
                'is_safe': is_safe, 'is_buyable': False,
            })
            continue

        # 急跌过滤
        is_dropped = False
        drop_reason = ''
        if len(sp) >= 4:
            recent = sp.iloc[-4:]
            for j in range(len(recent) - 1):
                if recent.iloc[j] > 0:
                    daily_chg = recent.iloc[j + 1] / recent.iloc[j]
                    if daily_chg < drop_threshold:
                        is_dropped = True
                        pct_drop = (1 - daily_chg) * 100
                        drop_reason = f'急跌过滤(4日内跌{pct_drop:.1f}%)'
                        break

        # 短期动量
        y = np.log(sp.values.astype(float))
        x = np.arange(len(y), dtype=float)
        w = np.linspace(1, 2, len(y))

        try:
            coeffs = np.polyfit(x, y, 1, w=w)
            slope = coeffs[0]
        except:
            results.append({
                'etf': asset, 'name': name,
                'short_score': 0, 'long_score': 0, 'combined_score': 0,
                'is_dropped': True, 'drop_reason': '短期回归失败',
                'current_price': round(current_price, 4),
                'daily_change': round(daily_change, 2),
                'is_safe': is_safe, 'is_buyable': False,
            })
            continue

        ann_return = math.exp(slope * 252) - 1
        y_pred = slope * x + coeffs[1]
        ss_res = np.sum(w * (y - y_pred) ** 2)
        y_mean = np.average(y, weights=w)
        ss_tot = np.sum(w * (y - y_mean) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0

        short_score = ann_return * r2
        if not (0 < short_score < short_score_cap):
            short_score = 0

        # 长期动量
        lp = close_prices[asset].iloc[max(0, loc - actual_long):loc + 1].dropna()
        long_score = 0
        if len(lp) >= 20:
            y2 = np.log(lp.values.astype(float))
            x2 = np.arange(len(y2), dtype=float)
            w2 = np.linspace(1, 2, len(y2))

            try:
                coeffs2 = np.polyfit(x2, y2, 1, w=w2)
                slope2 = coeffs2[0]
            except:
                pass
            else:
                ann2 = math.exp(slope2 * 252) - 1
                y2_pred = slope2 * x2 + coeffs2[1]
                ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                y2_mean = np.average(y2, weights=w2)
                ss_tot2 = np.sum(w2 * (y2 - y2_mean) ** 2)
                r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 1e-10 else 0

                long_score = ann2 * r22
                if not (long_score > 0 and long_score < long_score_cap):
                    long_score = 0

        combined_score = short_score + long_score

        # 可买入条件：综合得分>0 且 未被急跌过滤淘汰 且 非安全池
        is_buyable = combined_score > 0 and not is_dropped and not is_safe

        results.append({
            'etf': asset, 'name': name,
            'short_score': round(short_score, 4),
            'long_score': round(long_score, 4),
            'combined_score': round(combined_score, 4),
            'is_dropped': is_dropped,
            'drop_reason': drop_reason,
            'current_price': round(current_price, 4),
            'daily_change': round(daily_change, 2),
            'is_safe': is_safe, 'is_buyable': is_buyable,
        })

    # 按综合得分降序排列
    results.sort(key=lambda x: x['combined_score'], reverse=True)

    # 添加排名
    for i, r in enumerate(results):
        r['rank'] = i + 1

    return results


# ================================================================
# 模拟盘账户管理
# ================================================================
class SimAccount:
    """A股ETF模拟盘账户（100万本金）"""

    def __init__(self, initial_capital=INIT_CAPITAL):
        self.initial_capital = initial_capital
        self.cash = float(initial_capital)
        self.positions = {}  # {etf_code: {'shares': float, 'avg_price': float, 'market_value': float}}
        self.trade_log = []  # 交易记录
        self.cumulative_pnl = 0.0
        self.net_value = float(initial_capital)
        self.daily_records = []  # 每日明细

    def buy(self, etf_code, price, date_str):
        """买入ETF（考虑手续费）— 全仓买入"""
        # 卖出旧持仓
        if self.positions:
            for old_code, pos in list(self.positions.items()):
                self._sell_position(old_code, pos['avg_price'], date_str)

        # 计算可买数量（ETF按份计，1份=1元净值，最小100份=1手）
        buy_amount = self.cash
        fee = max(buy_amount * BUY_FEE_RATE, MIN_COMMISSION)
        actual_buy = buy_amount - fee
        if actual_buy <= 0 or price <= 0:
            return False

        shares = int(actual_buy / price / 100) * 100  # 按手取整
        if shares <= 0:
            return False

        cost = shares * price
        actual_fee = max(cost * BUY_FEE_RATE, MIN_COMMISSION)

        # 退回多余现金
        self.cash -= (cost + actual_fee)
        self.cash = max(self.cash, 0)

        self.positions = {
            etf_code: {
                'shares': shares,
                'avg_price': price,
                'market_value': cost,
            }
        }

        self.trade_log.append({
            'date': date_str,
            'action': '买入',
            'etf': etf_code,
            'name': CN_ETF_NAMES.get(etf_code, etf_code),
            'price': round(price, 4),
            'shares': shares,
            'amount': round(cost, 2),
            'fee': round(actual_fee, 2),
        })

        self._update_net_value()
        return True

    def _sell_position(self, etf_code, sell_price, date_str):
        """卖出持仓（内部方法）"""
        if etf_code not in self.positions:
            return 0

        pos = self.positions[etf_code]
        shares = pos['shares']
        sell_amount = shares * sell_price
        fee = max(sell_amount * SELL_FEE_RATE, MIN_COMMISSION)
        net_proceeds = sell_amount - fee

        # 计算盈亏
        cost_basis = pos['market_value']
        pnl = net_proceeds - cost_basis

        self.cash += net_proceeds

        self.trade_log.append({
            'date': date_str,
            'action': '卖出',
            'etf': etf_code,
            'name': CN_ETF_NAMES.get(etf_code, etf_code),
            'price': round(sell_price, 4),
            'shares': shares,
            'amount': round(sell_amount, 2),
            'fee': round(fee, 2),
            'pnl': round(pnl, 2),
        })

        del self.positions[etf_code]
        self.cumulative_pnl += pnl
        return pnl

    def sell_current(self, current_price, date_str):
        """按当前市价卖出当前持仓"""
        if not self.positions:
            return 0

        total_pnl = 0
        for etf_code in list(self.positions.keys()):
            total_pnl += self._sell_position(etf_code, current_price, date_str)

        self.cumulative_pnl += total_pnl
        self._update_net_value()
        return total_pnl

    def hold_position(self, date_str, current_prices):
        """持仓不变，更新市值"""
        for etf_code, pos in self.positions.items():
            if etf_code in current_prices:
                new_mv = pos['shares'] * current_prices[etf_code]
                pos['market_value'] = new_mv

        self._update_net_value(current_prices)

    def _update_net_value(self, current_prices=None):
        """更新净值"""
        total_mv = sum(pos['market_value'] for pos in self.positions.values())
        self.net_value = self.cash + total_mv

    def get_position_details(self, current_prices):
        """获取当前持仓明细"""
        details = []
        for etf_code, pos in self.positions.items():
            cur_price = current_prices.get(etf_code, pos['avg_price'])
            cur_mv = pos['shares'] * cur_price
            pnl = cur_mv - pos['market_value']
            pnl_pct = (cur_price - pos['avg_price']) / pos['avg_price'] * 100 if pos['avg_price'] > 0 else 0

            details.append({
                'etf': etf_code,
                'name': CN_ETF_NAMES.get(etf_code, etf_code),
                'shares': int(pos['shares']),
                'buy_price': round(pos['avg_price'], 4),
                'current_price': round(cur_price, 4),
                'market_value': round(cur_mv, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
            })
        return details


# ================================================================
# 每日模拟盘运行
# ================================================================
def run_daily_simulation(target_date=None):
    """
    运行每日A股模拟盘

    Args:
        target_date: 目标日期，格式'YYYY-MM-DD'，默认为今天
    """
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')

    today = pd.Timestamp(target_date)
    yesterday = today - pd.Timedelta(days=1)

    print(f"🌟 {STRATEGY_NAME} A股每日模拟盘")
    print(f"📅 日期: {target_date}")
    print(f"💰 本金: ¥{INIT_CAPITAL:,.0f}")
    print(f"📦 池子: {len(INVEST_POOL)}只投资 + {len(SAFE_POOL)}只安全")
    print("=" * 70)

    # 1. 加载数据
    print("\n📂 加载A股ETF数据...")
    data = load_cn_etf_data()
    if not data:
        print("❌ 无可用数据")
        return None

    # 2. 构建收盘价矩阵
    close_dict = {}
    for code, df in data.items():
        if 'Close' in df.columns:
            close_dict[code] = df['Close']

    if not close_dict:
        print("❌ 无有效收盘价数据")
        return None

    close_prices = pd.DataFrame(close_dict).sort_index()
    # 只保留最近3年数据（策略所需长期回溯250日≈1年 + 缓冲）
    three_years_ago = today - pd.Timedelta(days=3 * 365)
    close_prices = close_prices[close_prices.index >= three_years_ago]
    close_prices = close_prices.dropna(how='all').ffill().bfill()

    print(f"  📊 数据范围: {close_prices.index[0].strftime('%Y-%m-%d')} ~ {close_prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"  📊 ETF数量: {len(close_prices.columns)}")

    # 3. 运行策略生成信号
    print("\n🔄 运行七星高照6+1策略...")
    etf_pool = [c for c in CN_ETF_POOL if c in close_prices.columns]
    safe_assets = [c for c in CN_SAFE if c in close_prices.columns]

    holding = qixing_rotation_strategy(
        close_prices,
        etf_pool=etf_pool,
        safe_assets=safe_assets,
    )

    # 4. 加载或创建模拟账户
    account = load_account()

    # 5. 获取策略建议
    mask = holding.index <= today
    if mask.any():
        current_holding = holding[mask].iloc[-1]
    else:
        current_holding = holding.iloc[-1]

    # 获取上一个持仓（判断是否需要换仓）
    prev_mask = (holding.index <= today) & (holding.index >= today - pd.Timedelta(days=7))
    if prev_mask.any() and prev_mask.sum() > 1:
        prev_holding = holding[prev_mask].iloc[-2]
    else:
        prev_holding = None

    # 初始化手续费估算
    total_fee_estimate = 0.0

    # 判断操作类型
    need_rebalance = (current_holding != prev_holding) if prev_holding is not None else True
    operation = '换仓' if need_rebalance else '持有'

    # 获取最新价格
    latest_row = close_prices.iloc[-1]
    current_price = float(latest_row.get(current_holding, 0))

    current_holding_name = CN_ETF_NAMES.get(current_holding, current_holding)
    prev_holding_name = CN_ETF_NAMES.get(prev_holding, prev_holding) if prev_holding else ''

    # 6. 计算所有候选ETF的动量评分排名
    print("\n🔄 计算候选池ETF动量评分排名...")
    rankings = _compute_all_etf_rankings(close_prices, etf_pool, safe_assets, today)

    # 7. 用实时行情修正涨跌幅和最新价（盘中数据更准确）
    try:
        realtime = get_realtime_quotes()
        if realtime:
            rankings = apply_realtime_to_rankings(rankings, realtime)
    except Exception as e:
        print(f"  ⚠️ 实时行情获取失败，使用CSV数据: {e}")

    if rankings:
        print(f"\n{'='*70}")
        print(f"📋 七星高照6+1 候选池ETF当日检测结果")
        print(f"{'='*70}")
        print(f"{'排名':>4} {'代码':<12} {'名称':<10} {'综合得分':>10} {'短期':>8} {'长期':>8} {'最新价':>8} {'涨跌%':>8} {'状态':<12} {'可买入'}")
        print(f"{'-'*4} {'-'*12} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12} {'-'*6}")

        for r in rankings:
            status = '🔥可买入' if r['is_buyable'] else ('⚠️淘汰' if r['is_dropped'] else ('🔒安全池' if r['is_safe'] else '❌不可买'))
            buyable = '✅' if r['is_buyable'] else '❌'
            change_str = f"{r['daily_change']:+.2f}" if r['daily_change'] != 0 else "0.00"
            price_str = f"{r['current_price']:.3f}" if r['current_price'] > 0 else "-"
            print(f"  {r['rank']:>2}  {r['etf']:<12} {r['name']:<10} {r['combined_score']:>10.4f} {r['short_score']:>8.4f} {r['long_score']:>8.4f} {price_str:>8} {change_str:>8} {status:<12} {buyable}")

        buyable_list = [r for r in rankings if r['is_buyable']]
        print(f"\n✅ 可买入ETF排名（共{len(buyable_list)}只）:")
        for i, r in enumerate(buyable_list):
            medal = ['🥇', '🥈', '🥉'][i] if i < 3 else f' {i+1}'
            print(f"  {medal} {r['name']} ({r['etf'].split('_')[0]}) — 综合得分: {r['combined_score']:.4f}")

    # 7. 执行操作
    print(f"\n📋 当日操作建议:")
    print(f"  操作: {operation}")
    print(f"  当前持仓: {current_holding_name} ({current_holding})")

    if need_rebalance:
        if account.positions:
            old_etf = list(account.positions.keys())[0]
        elif prev_holding:
            old_etf = prev_holding
        else:
            old_etf = None

        if old_etf and prev_holding_name:
            operation_detail = f'卖出{prev_holding_name} → 买入{current_holding_name}'
        else:
            operation_detail = f'买入{current_holding_name}'
        print(f"  操作明细: {operation_detail}")

        # 估算手续费
        if old_etf and old_etf in latest_row:
            old_price = float(latest_row[old_etf])
        else:
            old_price = 0

        sell_fee = max(account.net_value * SELL_FEE_RATE, MIN_COMMISSION) if (account.positions and old_etf) else 0
        buy_fee = max(account.net_value * BUY_FEE_RATE, MIN_COMMISSION)
        total_fee_estimate = sell_fee + buy_fee
        print(f"  预估手续费: ¥{total_fee_estimate:,.2f}")

        # 执行换仓
        if account.positions and old_etf and old_price > 0:
            account.sell_current(old_price, today.strftime('%Y-%m-%d'))
        if current_price > 0:
            account.buy(current_holding, current_price, today.strftime('%Y-%m-%d'))
    else:
        operation_detail = f'继续持有{current_holding_name}'
        print(f"  操作明细: {operation_detail}")

        # 更新市值
        latest_prices = latest_row.to_dict()
        account.hold_position(today.strftime('%Y-%m-%d'), latest_prices)

    # 7. 构建每日操作明细
    latest_prices = latest_row.to_dict()
    position_details = account.get_position_details(latest_prices)
    positions_dict = {p['etf']: p for p in position_details}

    daily_ops = {
        'date': today.strftime('%Y-%m-%d'),
        'weekday': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][today.weekday()],
        'current_holding': current_holding,
        'current_holding_name': current_holding_name,
        'previous_holding': prev_holding,
        'previous_holding_name': prev_holding_name,
        'need_rebalance': need_rebalance,
        'operation': operation,
        'operation_detail': operation_detail,
        'current_price': round(current_price, 4) if current_price else 0,
        'positions': positions_dict,
        'cash': round(account.cash, 2),
        'net_value': round(account.net_value, 2),
        'total_pnl': round(account.net_value - INIT_CAPITAL, 2),
        'total_pnl_pct': round((account.net_value - INIT_CAPITAL) / INIT_CAPITAL * 100, 2),
        'cumulative_pnl': round(account.cumulative_pnl, 2),
        'fees_estimate': round(total_fee_estimate, 2) if need_rebalance else 0,
        'trade_log': account.trade_log[-5:],
        'rankings': rankings if rankings else [],
    }

    # 保存每日记录
    account.daily_records.append({
        'date': today.strftime('%Y-%m-%d'),
        'net_value': round(account.net_value, 2),
        'operation': operation,
        'holding': current_holding_name,
        'total_pnl': daily_ops['total_pnl'],
        'total_pnl_pct': daily_ops['total_pnl_pct'],
    })

    # 8. 保存账户状态
    save_account(account)

    # 9. 保存每日操作明细到JSON
    os.makedirs(DAILY_OPS_DIR, exist_ok=True)
    json_path = os.path.join(DAILY_OPS_DIR, f'cn_daily_ops_{today.strftime("%Y%m%d")}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(daily_ops, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  ✅ 操作明细保存: {json_path}")

    # 10. 生成HTML报告
    report_html = generate_daily_report_html(daily_ops, account, today)

    # 保存本地副本
    report_path = os.path.join(DAILY_OPS_DIR, f'cn_daily_sim_report_{today.strftime("%Y%m%d")}.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_html)
    print(f"  ✅ 报告保存: {report_path}")

    # 11. 发送邮件
    print("\n📧 发送邮件...")
    email_sent = send_daily_report_email(report_html, today)
    if email_sent:
        print("  ✅ 邮件发送成功！")
    else:
        print("  ❌ 邮件发送失败")
        notify_user_email_failed(today)

    print("\n✅ 每日模拟盘运行完毕！")
    return daily_ops


# ================================================================
# 账户状态持久化
# ================================================================
def load_account():
    """加载账户状态"""
    state_file = Path(ACCOUNT_STATE_FILE)
    if state_file.exists():
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            account = SimAccount(state.get('initial_capital', INIT_CAPITAL))
            account.cash = state.get('cash', INIT_CAPITAL)
            account.positions = state.get('positions', {})
            account.cumulative_pnl = state.get('cumulative_pnl', 0)
            account.net_value = state.get('net_value', INIT_CAPITAL)
            account.daily_records = state.get('daily_records', [])
            account.trade_log = state.get('trade_log', [])
            print(f"  📂 加载已有账户: 净值¥{account.net_value:,.2f}")
            return account
        except:
            pass

    account = SimAccount()
    print(f"  🆕 创建新账户: 本金¥{INIT_CAPITAL:,.0f}")
    return account


def save_account(account):
    """保存账户状态"""
    state = {
        'initial_capital': account.initial_capital,
        'cash': account.cash,
        'positions': account.positions,
        'cumulative_pnl': account.cumulative_pnl,
        'net_value': account.net_value,
        'daily_records': account.daily_records,
        'trade_log': account.trade_log[-100:],
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'strategy': STRATEGY_NAME,
    }
    with open(ACCOUNT_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"  💾 账户状态已保存: 净值¥{account.net_value:,.2f}")


# ================================================================
# 每日操作报告生成（HTML邮件）
# ================================================================
def generate_rankings_table_html(rankings):
    """生成候选池ETF检测排名表HTML片段"""
    if not rankings:
        return '<!-- 无排名数据 -->'

    rows_html = ''
    for r in rankings:
        is_top1 = r['rank'] == 1
        row_bg = 'rgba(249,115,22,0.15)' if is_top1 else 'transparent'
        name_color = '#f97316' if is_top1 else '#e5e7eb'
        score_color = '#f97316' if is_top1 else '#60a5fa'
        code_short = r['etf'].split('_')[0]
        change_sign = '+' if r['daily_change'] > 0 else ''
        change_color = '#22c55e' if r['daily_change'] > 0 else '#ef4444'

        if r['is_buyable']:
            status_text = '🔥可买入'
            status_color = '#22c55e'
        elif r['is_dropped']:
            status_text = '⚠️' + r.get('drop_reason', '淘汰')
            status_color = '#ef4444'
        elif r['is_safe']:
            status_text = '🔒安全池'
            status_color = '#9ca3af'
        else:
            status_text = '❌不可买'
            status_color = '#9ca3af'

        rows_html += f'''
        <tr style="background:{row_bg};border-bottom:1px solid #1f2937;">
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{name_color};">{r['rank']}</td>
          <td style="padding:8px 10px;color:{name_color};font-weight:600;">{r['name']}<div style="font-size:10px;color:#9ca3af;">{code_short}</div></td>
          <td style="padding:8px 10px;text-align:center;color:{score_color};font-weight:700;">{r['combined_score']:.4f}</td>
          <td style="padding:8px 10px;text-align:center;color:#9ca3af;">{r['short_score']:.4f}</td>
          <td style="padding:8px 10px;text-align:center;color:#9ca3af;">{r['long_score']:.4f}</td>
          <td style="padding:8px 10px;text-align:center;color:#60a5fa;font-weight:600;">{r['current_price']:.3f}</td>
          <td style="padding:8px 10px;text-align:center;color:{change_color};font-weight:600;">{change_sign}{r['daily_change']:.2f}%</td>
          <td style="padding:8px 10px;text-align:center;color:{status_color};font-size:11px;">{status_text}</td>
        </tr>'''

    return f'''
  <div class="card">
    <div style="font-size:15px;color:#f97316;margin-bottom:14px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">📊 候选池ETF当日检测排名</div>
    <table style="font-size:12px;">
      <thead>
        <tr style="background:#1f2937;">
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">排名</th>
          <th style="padding:8px 10px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">标的</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">综合得分</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">短期</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">长期</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">最新价</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">涨跌%</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">状态</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
'''


def generate_daily_report_html(operations, account, today):
    """生成每日操作报告HTML"""

    holding_name = operations.get('current_holding_name', '未知')
    operation = operations.get('operation', '持有')
    operation_detail = operations.get('operation_detail', '')
    total_pnl = operations.get('total_pnl', 0)
    total_pnl_pct = operations.get('total_pnl_pct', 0)
    net_value = operations.get('net_value', INIT_CAPITAL)
    cash = operations.get('cash', 0)
    weekday = operations.get('weekday', '')
    current_price = operations.get('current_price', 0)
    fees_estimate = operations.get('fees_estimate', 0)

    pnl_color = '#22c55e' if total_pnl >= 0 else '#ef4444'
    pnl_sign = '+' if total_pnl >= 0 else ''

    # 操作卡片颜色
    op_border_color = '#f97316' if operation == '换仓' else '#3b82f6'
    op_bg_gradient = 'linear-gradient(135deg, #1a1a2e 0%, #2d1b0e 100%)' if operation == '换仓' else 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)'

    # 持仓明细表格
    positions_html = ''
    for etf_code, pos in operations.get('positions', {}).items():
        pos_pnl_color = '#22c55e' if pos['pnl'] >= 0 else '#ef4444'
        pos_pnl_sign = '+' if pos['pnl'] >= 0 else ''
        positions_html += f'''
        <tr style="border-bottom:1px solid #1f2937;">
          <td style="padding:8px 10px;color:#e5e7eb;font-weight:600;">{pos['name']}</td>
          <td style="padding:8px 10px;text-align:center;color:#9ca3af;">{pos['shares']}</td>
          <td style="padding:8px 10px;text-align:center;color:#9ca3af;">¥{pos['buy_price']:.4f}</td>
          <td style="padding:8px 10px;text-align:center;color:#60a5fa;">¥{pos['current_price']:.4f}</td>
          <td style="padding:8px 10px;text-align:center;color:#9ca3af;">¥{pos['market_value']:,.2f}</td>
          <td style="padding:8px 10px;text-align:center;color:{pos_pnl_color};font-weight:700;">{pos_pnl_sign}¥{abs(pos['pnl']):,.2f}</td>
          <td style="padding:8px 10px;text-align:center;color:{pos_pnl_color};font-weight:700;">{pos_pnl_sign}{pos['pnl_pct']:.2f}%</td>
        </tr>
'''

    # 最近交易记录
    trades_html = ''
    for trade in operations.get('trade_log', []):
        trade_color = '#22c55e' if trade.get('action') == '买入' else '#ef4444'
        trades_html += f'''
        <tr style="border-bottom:1px solid #1f2937;">
          <td style="padding:6px 8px;color:#9ca3af;font-size:12px;">{trade.get('date', '')}</td>
          <td style="padding:6px 8px;color:{trade_color};font-weight:600;font-size:12px;">{trade.get('action', '')}</td>
          <td style="padding:6px 8px;color:#e5e7eb;font-size:12px;">{trade.get('name', trade.get('etf', ''))}</td>
          <td style="padding:6px 8px;text-align:right;color:#9ca3af;font-size:12px;">¥{trade.get('price', 0):.4f}</td>
          <td style="padding:6px 8px;text-align:right;color:#9ca3af;font-size:12px;">{trade.get('shares', 0)}</td>
          <td style="padding:6px 8px;text-align:right;color:#9ca3af;font-size:12px;">¥{trade.get('fee', 0):.2f}</td>
        </tr>
'''

    # 每日历史记录表格
    history_html = ''
    for record in account.daily_records[-30:]:  # 最近30天
        rec_pnl_color = '#22c55e' if record.get('total_pnl', 0) >= 0 else '#ef4444'
        rec_pnl_sign = '+' if record.get('total_pnl', 0) >= 0 else ''
        rec_op_bg = 'rgba(249,115,22,0.1)' if record.get('operation') == '换仓' else 'transparent'
        history_html += f'''
        <tr style="border-bottom:1px solid #1f2937; background:{rec_op_bg};">
          <td style="padding:6px 8px;color:#e5e7eb;font-size:12px;font-weight:600;">{record.get('date', '')}</td>
          <td style="padding:6px 8px;text-align:center;color:{"#f97316" if record.get("operation") == "换仓" else "#3b82f6"};font-weight:600;font-size:12px;">{record.get('operation', '')}</td>
          <td style="padding:6px 8px;text-align:center;color:#f97316;font-size:12px;">{record.get('holding', '')}</td>
          <td style="padding:6px 8px;text-align:center;color:#60a5fa;font-size:12px;">¥{record.get('net_value', 0):,.2f}</td>
          <td style="padding:6px 8px;text-align:center;color:{rec_pnl_color};font-weight:600;font-size:12px;">{rec_pnl_sign}¥{abs(record.get('total_pnl', 0)):,.2f}</td>
          <td style="padding:6px 8px;text-align:center;color:{rec_pnl_color};font-size:12px;">{rec_pnl_sign}{record.get('total_pnl_pct', 0):.2f}%</td>
        </tr>
'''

    # 6+1池子展示
    pool_items_html = ''
    for code in INVEST_POOL:
        name = CN_ETF_NAMES.get(code, code)
        is_current = (code == operations.get('current_holding', ''))
        bg = 'rgba(249,115,22,0.15)' if is_current else 'rgba(255,255,255,0.03)'
        border = '2px solid #f97316' if is_current else '1px solid rgba(255,255,255,0.08)'
        label = '🔥 当前持仓' if is_current else ''
        pool_items_html += f'''
        <div style="background:{bg};border:{border};border-radius:8px;padding:10px 12px;text-align:center;">
          <div style="font-size:13px;font-weight:700;color:{"#f97316" if is_current else "#e5e7eb"};">{name}</div>
          <div style="font-size:10px;color:#9ca3af;margin-top:2px;">{code.split("_")[0]}</div>
          {f'<div style="font-size:10px;color:#f97316;margin-top:4px;font-weight:600;">{label}</div>' if is_current else ''}
        </div>
'''

    # 安全池展示
    for code in SAFE_POOL:
        name = CN_ETF_NAMES.get(code, code)
        is_current = (code == operations.get('current_holding', ''))
        bg = 'rgba(249,115,22,0.15)' if is_current else 'rgba(34,197,94,0.05)'
        border = '2px solid #f97316' if is_current else '1px solid rgba(34,197,94,0.2)'
        label = '🔥 当前持仓' if is_current else '🔒 安全池'
        pool_items_html += f'''
        <div style="background:{bg};border:{border};border-radius:8px;padding:10px 12px;text-align:center;">
          <div style="font-size:13px;font-weight:700;color:{"#f97316" if is_current else "#22c55e"};">{name}</div>
          <div style="font-size:10px;color:#9ca3af;margin-top:2px;">{code.split("_")[0]}</div>
          <div style="font-size:10px;color:{"#f97316" if is_current else "#22c55e"};margin-top:4px;font-weight:600;">{label}</div>
        </div>
'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{STRATEGY_NAME} A股模拟盘 — 每日操作报告</title>
<style>
  body {{ background:#0c0c14; color:#e5e7eb; font-family:'PingFang SC','Microsoft YaHei',-apple-system,sans-serif; margin:0; padding:0; }}
  a {{ color:#f97316; }}
  .card {{ background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid rgba(249,115,22,0.12); border-radius:12px; padding:18px; margin:16px 0; }}
  .highlight {{ background:rgba(249,115,22,0.08); }}
  table {{ width:100%; border-collapse:collapse; }}
</style>
</head>
<body>

<div style="max-width:720px;margin:0 auto;padding:16px;">

  <!-- 标题 -->
  <div style="text-align:center;padding:24px 0 8px;">
    <h1 style="margin:0;font-size:22px;color:#f97316;text-shadow:0 0 20px rgba(249,115,22,0.3);">🌟 {STRATEGY_NAME} A股模拟盘</h1>
    <p style="margin:6px 0 0;color:#9ca3af;font-size:13px;">每日操作报告 | 本金¥{INIT_CAPITAL:,.0f} | {today.strftime("%Y-%m-%d")} {weekday}</p>
    <p style="margin:2px 0 0;color:#6b7280;font-size:11px;">6只投资ETF轮动 + 1只城投ETF安全池</p>
  </div>

  <!-- ETF池展示 -->
  <div class="card">
    <div style="font-size:13px;color:#f97316;margin-bottom:10px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">📦 6+1 ETF池</div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
      {pool_items_html}
    </div>
  </div>

  <!-- 候选池ETF当日检测排名 -->
  {generate_rankings_table_html(operations.get('rankings', []))}

  <!-- 今日操作卡片 -->
  <div class="card" style="border-left:3px solid {op_border_color};">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div>
        <div style="font-size:11px;color:#9ca3af;">今日操作</div>
        <div style="font-size:20px;font-weight:800;color:{op_border_color};">{operation}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:11px;color:#9ca3af;">当前持仓</div>
        <div style="font-size:17px;font-weight:700;color:#f97316;">{holding_name}</div>
      </div>
    </div>
    <div style="border-top:1px solid #2d2d44;padding-top:10px;margin-top:6px;">
      <div style="color:#e5e7eb;font-size:13px;margin-bottom:6px;">📌 {operation_detail}</div>
      <div style="display:flex;gap:12px;font-size:12px;color:#9ca3af;">
        <span>现价: <span style="color:#60a5fa;font-weight:600;">¥{current_price:.4f}</span></span>
        <span>预估手续费: <span style="color:#f59e0b;font-weight:600;">¥{fees_estimate:,.2f}</span></span>
      </div>
    </div>
  </div>

  <!-- 账户总览 -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;margin:16px 0;">
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">账户净值</div>
      <div style="font-size:17px;font-weight:700;color:#60a5fa;">¥{net_value:,.2f}</div>
    </div>
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">累计盈亏</div>
      <div style="font-size:17px;font-weight:700;color:{pnl_color};">{pnl_sign}¥{abs(total_pnl):,.2f}</div>
    </div>
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">收益率</div>
      <div style="font-size:17px;font-weight:700;color:{pnl_color};">{pnl_sign}{total_pnl_pct:.2f}%</div>
    </div>
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">现金余额</div>
      <div style="font-size:17px;font-weight:700;color:#9ca3af;">¥{cash:,.2f}</div>
    </div>
  </div>

  <!-- 每日持仓明细表 -->
  <div class="card">
    <div style="font-size:15px;color:#f97316;margin-bottom:12px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">📋 每日持仓明细</div>
    <table style="font-size:13px;">
      <thead>
        <tr style="background:#1f2937;">
          <th style="padding:8px 10px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">标的</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">份额</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">买入价</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">现价</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">市值</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">盈亏</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">盈亏%</th>
        </tr>
      </thead>
      <tbody>
        {positions_html}
      </tbody>
    </table>
  </div>

  <!-- 每日操作明细表 -->
  <div class="card">
    <div style="font-size:15px;color:#f97316;margin-bottom:12px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">📝 每日操作明细</div>
    <table style="font-size:12px;">
      <thead>
        <tr style="background:#1f2937;">
          <th style="padding:6px 8px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">日期</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">操作</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">持仓ETF</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">净值</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">盈亏</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">收益率</th>
        </tr>
      </thead>
      <tbody>
        {history_html}
      </tbody>
    </table>
  </div>

  <!-- 最近交易记录 -->
  <div class="card">
    <div style="font-size:15px;color:#f97316;margin-bottom:12px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">💸 最近交易记录</div>
    <table style="font-size:12px;">
      <thead>
        <tr style="background:#1f2937;">
          <th style="padding:6px 8px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">日期</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">操作</th>
          <th style="padding:6px 8px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">标的</th>
          <th style="padding:6px 8px;text-align:right;color:#9ca3af;border-bottom:2px solid #2d2d44;">价格</th>
          <th style="padding:6px 8px;text-align:right;color:#9ca3af;border-bottom:2px solid #2d2d44;">数量</th>
          <th style="padding:6px 8px;text-align:right;color:#9ca3af;border-bottom:2px solid #2d2d44;">手续费</th>
        </tr>
      </thead>
      <tbody>
        {trades_html}
      </tbody>
    </table>
  </div>

  <!-- 手续费说明 -->
  <div class="card" style="font-size:12px;">
    <div style="font-size:13px;color:#f97316;margin-bottom:8px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">💰 手续费规则（A股）</div>
    <table>
      <tr style="border-bottom:1px solid #1f2937;">
        <td style="padding:6px 8px;color:#e5e7eb;font-weight:600;">佣金（单边）</td>
        <td style="padding:6px 8px;text-align:right;color:#9ca3af;">0.025%（最低5元）</td>
      </tr>
      <tr style="border-bottom:1px solid #1f2937;">
        <td style="padding:6px 8px;color:#e5e7eb;font-weight:600;">印花税（仅卖出）</td>
        <td style="padding:6px 8px;text-align:right;color:#9ca3af;">0.05%</td>
      </tr>
      <tr style="border-bottom:1px solid #1f2937;">
        <td style="padding:6px 8px;color:#e5e7eb;font-weight:600;">过户费（双边）</td>
        <td style="padding:6px 8px;text-align:right;color:#9ca3af;">0.001%</td>
      </tr>
      <tr style="border-bottom:1px solid #1f2937;">
        <td style="padding:6px 8px;color:#e5e7eb;font-weight:600;">≈ 买入总费率</td>
        <td style="padding:6px 8px;text-align:right;color:#60a5fa;font-weight:600;">{BUY_FEE_RATE*100:.3f}%</td>
      </tr>
      <tr>
        <td style="padding:6px 8px;color:#e5e7eb;font-weight:600;">≈ 卖出总费率</td>
        <td style="padding:6px 8px;text-align:right;color:#ef4444;font-weight:600;">{SELL_FEE_RATE*100:.3f}%</td>
      </tr>
    </table>
  </div>

  <!-- Footer -->
  <div style="text-align:center;color:#6b7280;font-size:11px;margin-top:16px;padding:16px 0;">
    <p>{STRATEGY_NAME} A股模拟盘 | 本金¥{INIT_CAPITAL:,.0f} | 数据来源：本地CSV日频数据</p>
    <p>⚠️ 模拟盘结果不代表未来表现，仅供研究参考</p>
    <p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>

</div>
</body>
</html>
'''
    return html


# ================================================================
# 邮件发送
# ================================================================
def send_daily_report_email(html_content, today):
    """发送每日操作报告邮件"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'【{STRATEGY_NAME}模拟盘】{today.strftime("%Y-%m-%d")} 每日操作建议'
    msg['From'] = '848786642@qq.com'
    msg['To'] = '848786642@qq.com'

    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)

    try:
        server = smtplib.SMTP_SSL('smtp.qq.com', 465)
        server.login('848786642@qq.com', 'ljbtvacrctjobfed')
        server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'  ❌ 邮件发送失败: {e}')
        return False


def notify_user_email_failed(today):
    """邮件发送失败时通知用户"""
    notify(
        title=f'⚠️ {STRATEGY_NAME}模拟盘邮件发送失败',
        message=f'{today.strftime("%Y-%m-%d")}的每日操作报告邮件发送失败，请检查网络或SMTP配置。\n\n报告已保存至本地：`cn_daily_ops_61/` 目录。'
    )


# ================================================================
# 入口
# ================================================================
if __name__ == '__main__':
    run_daily_simulation()
