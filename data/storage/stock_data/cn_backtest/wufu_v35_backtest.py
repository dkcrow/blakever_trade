#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五福闹新春v3.5 ETF动量策略 - A股回测
======================================
克隆自聚宽文章：https://www.joinquant.com/post/69702
适配：本地westock-data数据源 + v4评分体系
"""

import os, sys, json, math, time, logging, subprocess
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 导入标准v4评分模块
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score as v4_compute_total_score

WORKSPACE = '/data/workspace'
DATA_DIR = os.path.join(WORKSPACE, 'back_trader_stocks', 'cn_backtest')
RESULT_DIR = os.path.join(DATA_DIR, 'results')
WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

logger = logging.getLogger('wufu_backtest')
logger.setLevel(logging.INFO)
logger.handlers.clear()
fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(fmt)
logger.addHandler(sh)
fh = logging.FileHandler(os.path.join(DATA_DIR, 'wufu_backtest.log'), encoding='utf-8')
fh.setFormatter(fmt)
logger.addHandler(fh)

# ── A股可交易ETF池 ──
COMMODITY_ETFS = {'sh518880':'黄金ETF','sz161226':'国投白银LOF','sz159980':'有色ETF大成','sh501018':'南方原油LOF','sz159985':'豆粕ETF'}
OVERSEAS_ETFS = {'sh513100':'纳指ETF','sz159509':'纳指科技ETF','sh513290':'纳指生物','sh513500':'标普500','sz159518':'标普油气ETF','sz159502':'标普生物科技ETF','sz159529':'标普消费ETF','sh513400':'道琼斯','sh520830':'沙特ETF','sh513520':'日经ETF','sh513030':'德国ETF'}
HK_ETFS = {'sh513090':'香港证券','sh513180':'恒指科技','sh513120':'HK创新药','sh513330':'恒生互联','sh513750':'港股非银','sz159892':'恒生医药ETF','sz159605':'中概互联ETF','sh513190':'H股金融','sh510900':'恒生中国','sh513630':'香港红利','sh513920':'港股通央企红利','sh513970':'恒生消费'}
INDEX_ETFS = {'sh510500':'中证500ETF','sh512100':'中证1000ETF','sh563300':'中证2000','sh510300':'沪深300ETF','sh512050':'A500ETF','sh510760':'上证ETF','sz159915':'创业板ETF','sz159949':'创业板50ETF','sz159967':'创业板成长ETF','sh588080':'科创板50','sh588220':'科创100','sh511380':'可转债ETF'}
INDUSTRY_ETFS = {'sh513310':'中韩芯片','sh588200':'科创芯片','sz159852':'软件ETF','sh512880':'证券ETF','sh512400':'有色金属ETF','sh512980':'传媒ETF','sz159516':'半导体设备ETF','sh512480':'半导体','sh515880':'通信ETF','sz159869':'游戏ETF','sh512170':'医疗ETF','sh512800':'银行ETF','sh512710':'军工龙头','sh512660':'军工ETF','sh512690':'酒ETF','sh512890':'红利低波','sz159992':'创新药ETF','sh512010':'医药ETF','sh510880':'红利ETF','sh515220':'煤炭ETF','sh515050':'5GETF','sh516160':'新能源','sh512200':'地产ETF','sz159928':'消费ETF','sh515790':'光伏ETF','sz159865':'养殖ETF','sz159825':'农业ETF','sh515210':'钢铁ETF'}

ALL_CN_ETFS = {}
for d in [COMMODITY_ETFS, OVERSEAS_ETFS, HK_ETFS, INDEX_ETFS, INDUSTRY_ETFS]:
    ALL_CN_ETFS.update(d)
DEFENSIVE_ETF = 'sh511880'

# ── 数据获取 ──
def fetch_kline_single(symbol, limit=1300):
    try:
    cmd = f'node {WESTOCK_SCRIPT} kline {symbol} --period day --limit {limit} --fq bfq'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        lines = result.stdout.strip().split('\n')
        headers = None
        rows = []
        for line in lines:
            line = line.strip()
            if not line.startswith('|'):
                continue
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if headers is None:
                if 'date' in cells:
                    headers = cells
                continue
            if all(c == '---' for c in cells):
                continue
            if headers and len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
        if not rows:
            return None
        df = pd.DataFrame(rows)
        rename_map = {'date':'Date','open':'Open','last':'Close','high':'High','low':'Low','volume':'Volume','amount':'Amount'}
        df = df.rename(columns={k:v for k,v in rename_map.items() if k in df.columns})
        for col in ['Open','High','Low','Close','Volume','Amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'Close' in df.columns:
            df = df[df['Close'] > 0]
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date').drop_duplicates(subset='Date', keep='last').reset_index(drop=True)
        return df if len(df) >= 100 else None
    except Exception as e:
        logger.warning(f"获取失败 {symbol}: {e}")
        return None

def batch_fetch_etf_data(etf_dict, limit=1300):
    symbols = list(etf_dict.keys())
    all_data = {}
    failed_symbols = []
    for i, sym in enumerate(symbols):
        logger.info(f"获取 {i+1}/{len(symbols)}: {sym} {etf_dict[sym]}")
        df = fetch_kline_single(sym, limit)
        if df is not None:
            all_data[sym] = df
            logger.info(f"  成功: {len(df)}天")
        else:
            failed_symbols.append(sym)
            logger.info(f"  失败")
        time.sleep(0.5)  # 增加延时避免API限流
    
    # 重试失败的ETF
    if failed_symbols:
        logger.info(f"\n🔄 重试 {len(failed_symbols)} 只失败的ETF...")
        time.sleep(3)  # 重试前等待3秒
        for sym in failed_symbols:
            logger.info(f"重试: {sym} {etf_dict[sym]}")
            df = fetch_kline_single(sym, limit)
            if df is not None:
                all_data[sym] = df
                logger.info(f"  重试成功: {len(df)}天")
            else:
                logger.info(f"  重试失败")
            time.sleep(1.0)
    
    logger.info(f"成功获取 {len(all_data)}/{len(symbols)} 只ETF数据")
    return all_data

# ── 策略核心函数 ──
def calculate_momentum_score(price_series, lookback_days=25):
    if len(price_series) < lookback_days + 1:
        return None, None, None
    recent = price_series[-(lookback_days + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    W = weights ** 2
    W_sum = np.sum(W)
    x_bar = np.sum(W * x) / W_sum
    y_bar = np.sum(W * y) / W_sum
    dx = x - x_bar; dy = y - y_bar
    var_x = np.sum(W * dx ** 2)
    if var_x == 0:
        return 0, 0, 0
    slope = np.sum(W * dx * dy) / var_x
    intercept = y_bar - slope * x_bar
    annual = math.exp(slope * 250) - 1
    y_pred = slope * x + intercept
    ss_res = np.sum(weights * (y - y_pred) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0
    score = annual * r2
    return score, annual, r2

def laplace_filter(price, s=0.05):
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L

def gaussian_filter_last_two(price, sigma=1.2):
    n = len(price)
    if n < 2: return 0, 0
    idx1 = np.arange(n)
    w1 = np.exp(-((idx1+1)**2)/(2*sigma**2))[::-1]
    w1 /= np.sum(w1)
    g1 = np.sum(price * w1)
    p2 = price[:-1]
    idx2 = np.arange(n-1)
    w2 = np.exp(-((idx2+1)**2)/(2*sigma**2))[::-1]
    w2 /= np.sum(w2)
    g2 = np.sum(p2 * w2)
    return g1, g2

def calculate_rsi(close, period=14):
    if len(close) < period + 1: return None
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ── 评分体系：使用 strategy_ranker.py 标准v4 ──
# 已在文件头部 import strategy_ranker.compute_total_score as v4_compute_total_score


# ══════════════════════════════════════════════════════════
#  回测引擎 - 五福闹新春v3.5 ETF动量策略
# ══════════════════════════════════════════════════════════

class WufuStrategy:
    """五福闹新春v3.5 策略状态机"""
    
    def __init__(self):
        # 动量参数
        self.lookback_days = 25
        self.min_score_threshold = 0
        self.max_score_threshold = 5
        self.score_threshold_ratio = 0.9
        self.holdings_num = 1
        
        # 过滤参数
        self.enable_r2_filter = True
        self.r2_threshold = 0.4
        self.enable_volume_check = True
        self.volume_lookback = 5
        self.volume_threshold = 1.8
        self.enable_loss_filter = True
        self.loss = 0.97  # 单日最大允许跌幅3%
        
        # 滤波器参数
        self.laplace_s_param = 0.05
        self.laplace_min_slope = 0.002
        self.gaussian_sigma = 1.2
        self.gaussian_min_slope = 0.002
        
        # 震荡期参数
        self.enable_range_bound_mode = True
        self.current_filter = '正常期'
        self.risk_state = '正常期'
        self.lookback_high_low_days = 20
        self.risk_benchmark = 'sh510300'
        
        # 进入震荡期条件
        self.enable_bias_trigger = True
        self.bias_threshold = 0.08
        self.ma_period = 20
        self.enable_rsi_trigger = True
        self.rsi_overbought = 70
        self.rsi_pullback = 65
        self.previous_rsi = None
        self.enable_stop_loss_trigger = True
        self.stop_loss_triggered_today = False
        
        # 退出震荡期条件
        self.enable_low_point_rise_trigger = True
        self.low_point_rise_threshold = 0.04
        self.enable_stable_signal_trigger = True
        self.drawdown_recovery = 0.02
        self.max_range_bound_days = 20
        self.stable_days = 0
        
        # 震荡期控制
        self.filter_switch_cooldown = 3
        self.last_switch_date = None
        self.range_bound_start_date = None
        self.range_bound_days_count = 0
        self.previous_drawdown = None
        
        # 止损参数
        self.use_fixed_stop_loss = True
        self.fixedStopLossThreshold = 0.95
        self.use_pct_stop_loss = False
        self.pct_stop_loss_threshold = 0.95
        
        # 风险监控
        self.max_portfolio_value = 0
        self.drawdown_threshold = 0.03
    
    def reset_daily(self):
        self.stop_loss_triggered_today = False


class BacktestEngine:
    """本地回测引擎"""
    
    def __init__(self, etf_data, strategy_params=None):
        """
        etf_data: dict {symbol: DataFrame(Date,Open,High,Low,Close,Volume)}
        """
        self.etf_data = etf_data
        self.strat = WufuStrategy() if strategy_params is None else strategy_params
        
        # 构建统一交易日历
        all_dates = set()
        for sym, df in etf_data.items():
            all_dates.update(df['Date'].tolist())
        self.trade_dates = sorted(list(all_dates))
        
        # 构建价格查询表
        self.price_tables = {}
        self.volume_tables = {}
        for sym, df in etf_data.items():
            df = df.set_index('Date')
            self.price_tables[sym] = df['Close'] if 'Close' in df.columns else None
            self.volume_tables[sym] = df['Volume'] if 'Volume' in df.columns else None
        
        # 回测状态
        self.cash = 1000000.0  # 100万初始资金
        self.positions = {}  # {symbol: {'shares': int, 'cost': float}}
        self.net_values = []  # [(date, net_value)]
        self.trades = []  # 交易记录
        self.daily_returns = []
    
    def get_price(self, symbol, date, field='Close'):
        """获取指定日期的价格"""
        pt = self.price_tables.get(symbol)
        if pt is None:
            return None
        try:
            val = pt.loc[date]
            if pd.isna(val):
                return None
            return float(val)
        except (KeyError, TypeError):
            return None
    
    def get_price_series(self, symbol, end_date, count):
        """获取截至end_date的前count个交易日数据"""
        pt = self.price_tables.get(symbol)
        if pt is None:
            return None
        mask = pt.index <= end_date
        series = pt[mask].tail(count)
        if len(series) < count * 0.6:
            return None
        return series.values
    
    def get_volume_series(self, symbol, end_date, count):
        """获取成交量序列"""
        vt = self.volume_tables.get(symbol)
        if vt is None:
            return None
        mask = vt.index <= end_date
        series = vt[mask].tail(count)
        return series.values
    
    def get_high_low_series(self, symbol, end_date, count):
        """获取最高最低价序列"""
        df = self.etf_data.get(symbol)
        if df is None:
            return None, None
        df = df.set_index('Date')
        mask = df.index <= end_date
        sub = df[mask].tail(count)
        if 'High' in sub.columns and 'Low' in sub.columns:
            return sub['High'].values, sub['Low'].values
        return None, None
    
    def get_benchmark_series(self, end_date, count):
        """获取风险基准ETF数据"""
        return self.get_price_series(self.strat.risk_benchmark, end_date, count)
    
    def check_range_bound_enter(self, date):
        """检查是否进入震荡期"""
        s = self.strat
        if not s.enable_range_bound_mode:
            return
        if s.current_filter == '震荡期':
            return
        
        # 冷却期检查
        if s.last_switch_date is not None:
            days_since = (date - s.last_switch_date).days
            if days_since < s.filter_switch_cooldown:
                return
        
        risk_signals = []
        
        # 条件1: 乖离率过大
        if s.enable_bias_trigger:
            close = self.get_benchmark_series(date, s.ma_period + 30)
            if close is not None and len(close) >= s.ma_period:
                current_price = close[-1]
                ma = np.mean(close[-s.ma_period:])
                bias = (current_price - ma) / ma if ma > 0 else 0
                if bias > s.bias_threshold:
                    risk_signals.append(f"乖离率{bias:.2%}")
        
        # 条件2: RSI超买回落
        if s.enable_rsi_trigger:
            close = self.get_benchmark_series(date, 50)
            if close is not None and len(close) >= 15:
                current_rsi = calculate_rsi(close, period=14)
                if current_rsi is not None:
                    prev_rsi = calculate_rsi(close[:-1], period=14)
                    if prev_rsi is not None and prev_rsi > s.rsi_overbought and current_rsi < s.rsi_pullback and current_rsi < prev_rsi:
                        risk_signals.append(f"RSI回落{prev_rsi:.1f}→{current_rsi:.1f}")
                    s.previous_rsi = current_rsi
        
        # 条件3: 止损触发
        if s.enable_stop_loss_trigger and s.stop_loss_triggered_today:
            risk_signals.append("止损触发")
            s.stop_loss_triggered_today = False
        
        if risk_signals:
            s.current_filter = '震荡期'
            s.risk_state = '震荡期'
            s.last_switch_date = date
            s.range_bound_start_date = date
            s.range_bound_days_count = 0
            s.stable_days = 0
            logger.info(f"  🔔 {date.strftime('%Y-%m-%d')} 进入震荡期: {'; '.join(risk_signals)}")
    
    def check_range_bound_exit(self, date):
        """检查是否退出震荡期"""
        s = self.strat
        if not s.enable_range_bound_mode or s.current_filter != '震荡期':
            return
        
        close = self.get_benchmark_series(date, max(s.ma_period, s.lookback_high_low_days) + 30)
        high, low = self.get_high_low_series(s.risk_benchmark, date, max(s.ma_period, s.lookback_high_low_days) + 30)
        
        if close is None or len(close) < max(s.ma_period, s.lookback_high_low_days):
            return
        
        current_price = close[-1]
        
        if high is not None and low is not None and len(high) >= s.lookback_high_low_days:
            recent_high = np.max(high[-s.lookback_high_low_days:])
            recent_low = np.min(low[-s.lookback_high_low_days:])
        else:
            recent_high = np.max(close)
            recent_low = np.min(close)
        
        current_dd = (recent_high - current_price) / recent_high if recent_high > 0 else 0
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        
        recovery_signals = []
        
        # 条件1: 从低点上涨
        if s.enable_low_point_rise_trigger and rise_from_low >= s.low_point_rise_threshold:
            recovery_signals.append(f"低点上涨{rise_from_low:.2%}")
        
        # 条件2: 企稳信号
        if s.enable_stable_signal_trigger:
            ma = np.mean(close[-s.ma_period:])
            if current_price > ma:
                recovery_signals.append("站上均线")
            if s.previous_drawdown is not None and current_dd < s.previous_drawdown:
                recovery_signals.append("回撤收窄")
            if current_dd < s.drawdown_recovery:
                s.stable_days += 1
            else:
                s.stable_days = 0
        
        s.previous_drawdown = current_dd
        
        # 条件3: 震荡期满
        if s.range_bound_start_date is not None:
            range_days = (date - s.range_bound_start_date).days
            if range_days >= s.max_range_bound_days:
                recovery_signals.append(f"震荡期满{range_days}天")
        
        # 判断退出
        low_rise = s.enable_low_point_rise_trigger and rise_from_low >= s.low_point_rise_threshold
        stable = s.enable_stable_signal_trigger and current_dd < s.drawdown_recovery and len(recovery_signals) >= 2 and s.stable_days >= 2
        force = s.range_bound_start_date is not None and (date - s.range_bound_start_date).days >= s.max_range_bound_days
        
        if low_rise or stable or force:
            # 冷却期
            if s.last_switch_date is not None and (date - s.last_switch_date).days < s.filter_switch_cooldown:
                return
            s.current_filter = '正常期'
            s.risk_state = '正常期'
            s.last_switch_date = date
            s.range_bound_start_date = None
            s.range_bound_days_count = 0
            s.stable_days = 0
            logger.info(f"  🔔 {date.strftime('%Y-%m-%d')} 退出震荡期: {'; '.join(recovery_signals)}")
    
    def calculate_etf_momentum(self, symbol, date):
        """计算单个ETF的动量得分和过滤指标"""
        s = self.strat
        lookback = max(s.lookback_days, s.volume_lookback) + 20
        
        close = self.get_price_series(symbol, date, lookback + 5)
        if close is None or len(close) < s.lookback_days:
            return None
        
        current_price = close[-1]
        if current_price <= 0:
            return None
        
        # 动量得分
        ms, annual, r2 = calculate_momentum_score(close, s.lookback_days)
        if ms is None:
            return None
        
        # R²过滤
        passed_r2 = r2 > s.r2_threshold if s.enable_r2_filter else True
        
        # 成交量过滤（简化：用成交额比代替）
        vol_ratio = None
        passed_volume = True
        if s.enable_volume_check:
            vol = self.get_volume_series(symbol, date, s.volume_lookback + 5)
            if vol is not None and len(vol) >= s.volume_lookback:
                recent_vol = vol[-s.volume_lookback:]
                if np.all(recent_vol > 0):
                    avg_vol = np.mean(recent_vol[:-1])
                    today_vol = recent_vol[-1]
                    if avg_vol > 0:
                        vol_ratio = today_vol / avg_vol
                        passed_volume = vol_ratio < s.volume_threshold
        
        # 短期风控过滤
        passed_loss = True
        day_ratios = []
        if s.enable_loss_filter and len(close) >= 4:
            day_ratios = [close[-1]/close[-2], close[-2]/close[-3], close[-3]/close[-4]]
            if min(day_ratios) < s.loss:
                passed_loss = False
        
        # 滤波器
        passed_filter = False
        filter_slope = 0
        if len(close) >= 10:
            try:
                laplace_vals = laplace_filter(close, s=s.laplace_s_param)
                if len(laplace_vals) >= 2:
                    laplace_slope = laplace_vals[-1] - laplace_vals[-2]
                    passed_laplace = current_price > laplace_vals[-1] and laplace_slope > s.laplace_min_slope
                else:
                    laplace_slope = 0
                    passed_laplace = False
                
                g1, g2 = gaussian_filter_last_two(close, sigma=s.gaussian_sigma)
                gaussian_slope = g1 - g2
                passed_gaussian = current_price > g1 and gaussian_slope > s.gaussian_min_slope
                
                if s.current_filter == '正常期':
                    passed_filter = passed_laplace
                    filter_slope = laplace_slope
                else:
                    passed_filter = passed_gaussian
                    filter_slope = gaussian_slope
            except:
                passed_filter = False
        
        # 动量得分过滤
        passed_momentum = s.min_score_threshold <= ms <= s.max_score_threshold
        
        return {
            'symbol': symbol, 'name': ALL_CN_ETFS.get(symbol, symbol),
            'momentum_score': ms, 'annualized': annual, 'r2': r2,
            'current_price': current_price, 'vol_ratio': vol_ratio,
            'passed_momentum': passed_momentum, 'passed_r2': passed_r2,
            'passed_volume': passed_volume, 'passed_loss': passed_loss,
            'passed_filter': passed_filter, 'filter_slope': filter_slope,
            'day_ratios': day_ratios,
        }
    
    def select_target_etfs(self, date):
        """选出目标持仓ETF"""
        s = self.strat
        all_metrics = []
        
        for sym in ALL_CN_ETFS:
            metrics = self.calculate_etf_momentum(sym, date)
            if metrics is not None:
                all_metrics.append(metrics)
        
        if not all_metrics:
            return []
        
        # 按动量得分排序
        all_metrics.sort(key=lambda x: x['momentum_score'], reverse=True)
        
        # 应用过滤条件
        filtered = all_metrics[:]
        if s.enable_r2_filter:
            filtered = [m for m in filtered if m['passed_r2']]
        if s.enable_volume_check:
            filtered = [m for m in filtered if m['passed_volume']]
        if s.enable_loss_filter:
            filtered = [m for m in filtered if m['passed_loss']]
        if s.enable_range_bound_mode:
            filtered = [m for m in filtered if m['passed_filter']]
        
        # 动量得分范围过滤
        filtered = [m for m in filtered if m['passed_momentum']]
        
        if not filtered:
            return []
        
        # 取前holdings_num只
        return filtered[:s.holdings_num]
    
    def check_stop_loss(self, date):
        """检查止损"""
        s = self.strat
        if not s.use_fixed_stop_loss:
            return
        
        to_sell = []
        for sym, pos in list(self.positions.items()):
            current_price = self.get_price(sym, date)
            if current_price is None or current_price <= 0:
                continue
            cost = pos['cost']
            if cost <= 0:
                continue
            if current_price <= cost * s.fixedStopLossThreshold:
                loss_pct = (current_price / cost - 1) * 100
                logger.info(f"  🚨 止损 {sym} {ALL_CN_ETFS.get(sym,sym)} 亏损{loss_pct:.2f}%")
                to_sell.append(sym)
                if s.enable_stop_loss_trigger:
                    s.stop_loss_triggered_today = True
        
        for sym in to_sell:
            self._sell(sym, date)
    
    def _sell(self, symbol, date):
        """卖出"""
        if symbol not in self.positions:
            return 0
        pos = self.positions[symbol]
        price = self.get_price(symbol, date)
        if price is None or price <= 0:
            return 0
        
        # 扣除交易成本 (0.02% + 印花税0.05%)
        sell_amount = pos['shares'] * price
        commission = max(5, sell_amount * 0.0002)
        stamp_tax = sell_amount * 0.0005  # 卖出印花税
        net_amount = sell_amount - commission - stamp_tax
        
        cost_basis = pos['shares'] * pos['cost']
        pnl = net_amount - cost_basis
        
        self.cash += net_amount
        del self.positions[symbol]
        
        self.trades.append({
            'date': date, 'symbol': symbol, 'action': 'sell',
            'price': price, 'shares': pos['shares'], 'amount': net_amount,
            'pnl': pnl, 'cost': cost_basis
        })
        return net_amount
    
    def _buy(self, symbol, date, amount):
        """买入"""
        price = self.get_price(symbol, date)
        if price is None or price <= 0:
            return False
        
        shares = int(amount / price / 100) * 100  # A股100股整数倍
        if shares <= 0:
            return False
        
        buy_amount = shares * price
        commission = max(5, buy_amount * 0.0002)
        total_cost = buy_amount + commission
        
        if total_cost > self.cash:
            shares = int((self.cash - 5) / price / 100) * 100
            if shares <= 0:
                return False
            buy_amount = shares * price
            commission = max(5, buy_amount * 0.0002)
            total_cost = buy_amount + commission
        
        self.cash -= total_cost
        self.positions[symbol] = {'shares': shares, 'cost': price}
        
        self.trades.append({
            'date': date, 'symbol': symbol, 'action': 'buy',
            'price': price, 'shares': shares, 'amount': total_cost,
            'pnl': 0, 'cost': total_cost
        })
        return True
    
    def get_portfolio_value(self, date):
        """计算组合总市值"""
        total = self.cash
        for sym, pos in self.positions.items():
            price = self.get_price(sym, date)
            if price is not None and price > 0:
                total += pos['shares'] * price
            else:
                total += pos['shares'] * pos['cost']
        return total
    
    def run(self, start_date, end_date):
        """运行回测"""
        logger.info(f"\n{'='*60}")
        logger.info(f"五福闹新春v3.5 A股回测")
        logger.info(f"回测区间: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        logger.info(f"初始资金: {self.cash:,.0f}")
        logger.info(f"ETF池: {len(ALL_CN_ETFS)}只")
        logger.info(f"{'='*60}")
        
        # 过滤交易日
        trade_dates = [d for d in self.trade_dates if start_date <= d <= end_date]
        if not trade_dates:
            logger.error("无可用交易日")
            return None
        
        logger.info(f"交易日数: {len(trade_dates)}")
        
        prev_value = self.cash
        
        for i, date in enumerate(trade_dates):
            # 1. 止损检查
            self.check_stop_loss(date)
            
            # 2. 每日调仓（午后13:10逻辑）
            # 退出震荡期检查
            self.check_range_bound_exit(date)
            # 进入震荡期检查
            self.check_range_bound_enter(date)
            
            # 3. 选出目标ETF
            targets = self.select_target_etfs(date)
            target_syms = [t['symbol'] for t in targets]
            
            # 4. 卖出不在目标中的持仓
            for sym in list(self.positions.keys()):
                if sym not in target_syms:
                    self._sell(sym, date)
            
            # 5. 买入目标ETF
            if targets:
                for t in targets:
                    if t['symbol'] not in self.positions:
                        buy_amount = self.cash  # holdings_num=1时全仓买入
                        self._buy(t['symbol'], date, buy_amount)
            
            # 6. 如果无目标且无持仓，持有防御ETF
            if not targets and not self.positions:
                if DEFENSIVE_ETF in self.price_tables:
                    self._buy(DEFENSIVE_ETF, date, self.cash)
            
            # 7. 记录净值
            current_value = self.get_portfolio_value(date)
            self.net_values.append((date, current_value))
            
            # 8. 更新最高净值
            if current_value > self.strat.max_portfolio_value:
                self.strat.max_portfolio_value = current_value
            
            # 9. 日收益率
            if prev_value > 0:
                daily_ret = (current_value / prev_value) - 1
                self.daily_returns.append(daily_ret)
            prev_value = current_value
            
            # 重置每日标志
            self.strat.reset_daily()
            
            # 每50个交易日输出一次进度
            if (i + 1) % 50 == 0:
                ret_pct = (current_value / 1000000 - 1) * 100
                hold_str = ', '.join([f"{sym}({ALL_CN_ETFS.get(sym,sym)})" for sym in self.positions])
                logger.info(f"  第{i+1}天 {date.strftime('%Y-%m-%d')} 净值:{current_value:,.0f} 收益:{ret_pct:.2f}% 持仓:{hold_str} 滤波器:{self.strat.current_filter}")
        
        # 计算回测指标
        return self._calculate_metrics()
    
    def _calculate_metrics(self):
        """计算回测指标"""
        if not self.net_values:
            return None
        
        dates = [nv[0] for nv in self.net_values]
        values = [nv[1] for nv in self.net_values]
        nv_series = pd.Series(values, index=dates)
        
        # 总收益率
        total_return = (values[-1] / values[0] - 1)
        
        # 年化收益率
        days = (dates[-1] - dates[0]).days
        annual_return = (1 + total_return) ** (365.25 / days) - 1 if days > 0 else 0
        
        # 日收益率序列
        if not self.daily_returns:
            return None
        ret_series = pd.Series(self.daily_returns)
        
        # 夏普比率（无风险利率2%）
        rf_daily = 0.02 / 252
        excess_returns = ret_series - rf_daily
        sharpe = np.sqrt(252) * excess_returns.mean() / excess_returns.std() if excess_returns.std() > 0 else 0
        
        # 最大回撤
        cummax = nv_series.cummax()
        drawdown = (nv_series - cummax) / cummax
        max_drawdown = drawdown.min()
        
        # 交易统计
        buy_trades = [t for t in self.trades if t['action'] == 'buy']
        sell_trades = [t for t in self.trades if t['action'] == 'sell']
        total_trades = len(buy_trades)
        
        # 盈利交易
        winning_trades = [t for t in sell_trades if t['pnl'] > 0]
        losing_trades = [t for t in sell_trades if t['pnl'] < 0]
        win_rate = len(winning_trades) / len(sell_trades) * 100 if sell_trades else 0
        
        # 盈亏比
        total_profit = sum(t['pnl'] for t in winning_trades) if winning_trades else 0
        total_loss = abs(sum(t['pnl'] for t in losing_trades)) if losing_trades else 1
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        # 年交易次数
        years = days / 365.25 if days > 0 else 1
        annual_trades = total_trades / years
        
        # 月度正收益比例
        monthly_returns = nv_series.resample('ME').last().pct_change().dropna()
        monthly_positive_rate = (monthly_returns > 0).mean() if len(monthly_returns) > 0 else 0
        
        # 计算v4评分（标准strategy_ranker.py，参数均为百分比格式）
        annual_pct = annual_return * 100  # 小数 → 百分比
        max_dd_pct = abs(max_drawdown) * 100  # 小数 → 百分比
        wr_pct = win_rate  # 胜率已经是百分比
        pf_val = profit_factor if profit_factor != float('inf') else 10
        
        scores_v4 = v4_compute_total_score(
            annual_return=annual_pct,
            sharpe=sharpe,
            max_drawdown=max_dd_pct,
            profit_factor=pf_val,
            win_rate=wr_pct,
            cross_period_robust=False,
            survivorship_bias=True,
            monthly_positive_rate=monthly_positive_rate,
        )
        # 转换为原有scores字段格式（兼容下游代码）
        scores = {
            'total': scores_v4['total_score'],
            'annual_score': scores_v4['annual_return_score'],
            'sharpe_score': scores_v4['sharpe_score'],
            'pf_score': scores_v4['profit_factor_score'],
            'wr_score': scores_v4['win_rate_score'],
            'dd_bonus': scores_v4['max_drawdown_score'],
            'monthly_score': scores_v4['monthly_stability_bonus'],
            'grade': scores_v4['grade'],
            'base_score': scores_v4['base_score'],
            'survivorship_penalty': scores_v4['survivorship_penalty'],
            'cross_period_bonus': scores_v4['cross_period_bonus'],
        }
        
        metrics = {
            'strategy': '五福闹新春v3.5',
            'source': '聚宽',
            'source_url': 'https://www.joinquant.com/post/69702',
            'market': 'CN',
            'total_return': round(total_return * 100, 2),
            'annual_return': round(annual_return * 100, 2),
            'sharpe': round(sharpe, 2),
            'max_drawdown': round(abs(max_drawdown) * 100, 2),
            'profit_factor': round(min(profit_factor, 10), 2),
            'win_rate': round(win_rate, 2),
            'annual_trades': round(annual_trades, 1),
            'monthly_positive_rate': round(monthly_positive_rate * 100, 2),
            'total_trades': total_trades,
            'start_date': dates[0].strftime('%Y-%m-%d'),
            'end_date': dates[-1].strftime('%Y-%m-%d'),
            'final_value': round(values[-1], 2),
            'initial_value': 1000000,
            'scores': scores,
        }
        
        return metrics


# ══════════════════════════════════════════════════════════
#  排行榜管理
# ══════════════════════════════════════════════════════════

LEADERBOARD_FILE = os.path.join(DATA_DIR, 'cn_leaderboard.json')
STRATEGY_DIR = os.path.join(DATA_DIR, 'strategies')
os.makedirs(STRATEGY_DIR, exist_ok=True)

def load_leaderboard():
    """加载A股排行榜"""
    if os.path.exists(LEADERBOARD_FILE):
        with open(LEADERBOARD_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'market': 'CN', 'updated': datetime.now().isoformat(), 'top10': []}

def save_leaderboard(lb):
    """保存排行榜"""
    lb['updated'] = datetime.now().isoformat()
    with open(LEADERBOARD_FILE, 'w', encoding='utf-8') as f:
        json.dump(lb, f, ensure_ascii=False, indent=2)

def check_and_enter_leaderboard(metrics):
    """检查策略是否可进入A股排行榜，如果可以则入榜"""
    lb = load_leaderboard()
    top10 = lb.get('top10', [])
    
    score = metrics['scores']['total']
    strategy_name = metrics['strategy']
    
    # 检查是否已在榜中（同名策略）
    existing_idx = None
    for i, item in enumerate(top10):
        if item.get('strategy') == strategy_name:
            existing_idx = i
            break
    
    can_enter = False
    replace_idx = None
    
    if existing_idx is not None:
        # 已在榜中，分数更高则替换
        if score > top10[existing_idx].get('scores', {}).get('total', 0):
            replace_idx = existing_idx
            can_enter = True
    elif len(top10) < 10:
        # 未满10，直接入榜
        can_enter = True
    else:
        # 满了，检查是否能替换末尾
        min_score = min(item.get('scores', {}).get('total', 0) for item in top10)
        if score > min_score:
            # 找到最低分的索引
            for i, item in enumerate(top10):
                if item.get('scores', {}).get('total', 0) == min_score:
                    replace_idx = i
                    can_enter = True
                    break
    
    if can_enter:
        entry = {
            'rank': 0,  # 重新排名
            'strategy': strategy_name,
            'source': metrics.get('source', ''),
            'source_url': metrics.get('source_url', ''),
            'market': 'CN',
            'total_return': metrics['total_return'],
            'annual_return': metrics['annual_return'],
            'sharpe': metrics['sharpe'],
            'max_drawdown': metrics['max_drawdown'],
            'profit_factor': metrics['profit_factor'],
            'win_rate': metrics['win_rate'],
            'annual_trades': metrics['annual_trades'],
            'monthly_positive_rate': metrics['monthly_positive_rate'],
            'scores': metrics['scores'],
            'backtest_period': f"{metrics['start_date']}~{metrics['end_date']}",
            'entered_at': datetime.now().isoformat(),
        }
        
        if replace_idx is not None:
            entry['replaced'] = top10[replace_idx].get('strategy', '')
            top10[replace_idx] = entry
            logger.info(f"🔄 替换排行榜第{replace_idx+1}位: {entry.get('replaced', '')} → {strategy_name}")
        else:
            top10.append(entry)
            logger.info(f"🆕 新入榜: {strategy_name}")
        
        # 重新按分数排序
        top10.sort(key=lambda x: x.get('scores', {}).get('total', 0), reverse=True)
        for i, item in enumerate(top10):
            item['rank'] = i + 1
        
        lb['top10'] = top10
        save_leaderboard(lb)
        
        # 保存策略文件
        strategy_file = os.path.join(STRATEGY_DIR, f"{strategy_name.replace(' ', '_')}.json")
        with open(strategy_file, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 策略已保存: {strategy_file}")
        
        return True, lb
    else:
        logger.info(f"❌ 未能入榜: 得分{score}未超过排行榜最低分")
        return False, lb


def print_leaderboard(lb):
    """打印排行榜"""
    top10 = lb.get('top10', [])
    if not top10:
        print("\n🇨🇳 A股排行榜 - 暂无策略")
        return
    
    print(f"\n{'='*80}")
    print(f"🇨🇳 A股ETF策略排行榜 TOP10 (更新: {lb.get('updated', '-')})")
    print(f"{'='*80}")
    print(f"{'排名':<4} {'策略名称':<20} {'得分':<8} {'年化%':<8} {'夏普':<6} {'回撤%':<8} {'盈亏比':<6} {'胜率%':<6} {'年交易':<6}")
    print(f"{'-'*80}")
    for item in top10:
        scores = item.get('scores', {})
        print(f"{'🥇' if item['rank']==1 else '🥈' if item['rank']==2 else '🥉' if item['rank']==3 else str(item['rank']):<4} "
              f"{item.get('strategy','-'):<20} "
              f"{scores.get('total',0):<8.2f} "
              f"{item.get('annual_return',0):<8.2f} "
              f"{item.get('sharpe',0):<6.2f} "
              f"{item.get('max_drawdown',0):<8.2f} "
              f"{item.get('profit_factor',0):<6.2f} "
              f"{item.get('win_rate',0):<6.2f} "
              f"{item.get('annual_trades',0):<6.1f}")
    print(f"{'='*80}")


# ══════════════════════════════════════════════════════════
#  主函数
# ══════════════════════════════════════════════════════════

def main():
    logger.info("\n" + "★" * 60)
    logger.info("五福闹新春v3.5 ETF动量策略 - A股回测")
    logger.info("克隆自: https://www.joinquant.com/post/69702")
    logger.info("★" * 60)
    
    # 回测参数
    end_date = pd.Timestamp('2026-04-25')
    start_date = pd.Timestamp('2021-04-25')  # 近5年
    
    # 1. 获取ETF数据
    logger.info("\n📊 第一步: 获取A股ETF K线数据...")
    etf_data = batch_fetch_etf_data(ALL_CN_ETFS, limit=1300)
    
    if not etf_data:
        logger.error("无法获取任何ETF数据，退出")
        return
    
    # 2. 运行回测
    logger.info("\n📈 第二步: 运行回测...")
    engine = BacktestEngine(etf_data)
    metrics = engine.run(start_date, end_date)
    
    if metrics is None:
        logger.error("回测失败")
        return
    
    # 3. 输出回测结果
    logger.info("\n" + "=" * 60)
    logger.info("📊 回测结果")
    logger.info("=" * 60)
    logger.info(f"策略: {metrics['strategy']}")
    logger.info(f"回测区间: {metrics['start_date']} ~ {metrics['end_date']}")
    logger.info(f"初始资金: {metrics['initial_value']:,.0f}")
    logger.info(f"最终净值: {metrics['final_value']:,.2f}")
    logger.info(f"总收益率: {metrics['total_return']:.2f}%")
    logger.info(f"年化收益率: {metrics['annual_return']:.2f}%")
    logger.info(f"夏普比率: {metrics['sharpe']:.2f}")
    logger.info(f"最大回撤: {metrics['max_drawdown']:.2f}%")
    logger.info(f"盈亏比: {metrics['profit_factor']:.2f}")
    logger.info(f"胜率: {metrics['win_rate']:.2f}%")
    logger.info(f"年交易次数: {metrics['annual_trades']:.1f}")
    logger.info(f"月度正收益比例: {metrics['monthly_positive_rate']:.2f}%")
    logger.info(f"总交易次数: {metrics['total_trades']}")
    logger.info("-" * 60)
    scores = metrics['scores']
    logger.info(f"🏆 v4评分: {scores['total']}分")
    logger.info(f"  年化得分: {scores['annual_score']}")
    logger.info(f"  夏普得分: {scores['sharpe_score']}")
    logger.info(f"  盈亏比得分: {scores['pf_score']}")
    logger.info(f"  胜率得分: {scores['wr_score']}")
    logger.info(f"  回撤奖励: {scores['dd_bonus']}")
    logger.info(f"  月度得分: {scores['monthly_score']}")
    logger.info("=" * 60)
    
    # 4. 检查排行榜
    logger.info("\n🏅 第三步: 检查A股排行榜...")
    entered, lb = check_and_enter_leaderboard(metrics)
    
    if entered:
        logger.info(f"✅ 成功进入A股排行榜！")
    else:
        logger.info(f"❌ 未能进入A股排行榜")
    
    # 5. 打印排行榜
    print_leaderboard(lb)
    
    # 6. 保存回测结果
    result_file = os.path.join(RESULT_DIR, f"wufu_v35_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    logger.info(f"\n💾 回测结果已保存: {result_file}")
    
    return metrics


if __name__ == '__main__':
    main()
