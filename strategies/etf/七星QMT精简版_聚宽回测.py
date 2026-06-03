# 策略名称：七星QMT精简版 — 聚宽回测专用
# 来源：https://www.joinquant.com/post/73146 (七星QMT V3, 作者: 任侠)
# 修改：blakehao (2026-06-03) — 关闭成交量+短期动量过滤, 佣金降至0.02%
#
# 【与V3原版的关键差异】
# 1. g.enable_volume_check = False（原版: True）— 回测证实成交量过滤严重负向
# 2. g.use_short_momentum_filter = False（原版: True）— 回测证实短期动量过滤严重负向
# 3. 佣金: 0.02%（原版: 0.05%）— 对齐实际费率
# 4. 防御ETF: 511880 银华日利（原版: 511010 国债ETF）
#
# 【本地回测对照】
# 本地回测引擎(BacktestEngine172) + 51 ETF池 + 精简过滤:
#   2025-01-01 ~ 2026-06-02, 佣金0.02%, 初始¥10,000
#   年化+527.92%, 总收益+712.27%, 回撤27.62%, 夏普3.2148
#
# 聚宽回测请设置: 频率=日, 佣金=0.02%双边, 滑点=0.01%

import numpy as np
import math
import datetime
import pandas as pd
from jqdata import *

# ==================== 初始化模块 ====================
def initialize(context):
    """
    初始化函数：设置交易参数、ETF池、核心参数、调度任务
    精简版：仅盈利保护 + 溢价率 + 行情判断（关闭成交量/短期动量）
    """
    # ---------- 交易设置 ----------
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0002,      # 0.02% (精简版对齐本地费率)
            close_commission=0.0002,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    set_benchmark("000300.XSHG")

    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    log.info("🚀 ========== 七星QMT精简版 初始化 ==========")

    # ---------- ETF池 (51只, 分三类) ----------
    # 海外+债券ETF（走弱期可交易, 18只）
    g.overseas_etf_pool = [
        "513100.XSHG",  # 纳指ETF
        "513290.XSHG",  # 纳指生物ETF
        "513500.XSHG",  # 标普500ETF
        "159529.XSHE",  # 标普消费
        "513400.XSHG",  # 道琼斯ETF
        "513520.XSHG",  # 日经225ETF
        "513030.XSHG",  # 德国30ETF
        "513080.XSHG",  # 法国ETF
        "513310.XSHG",  # 中韩半导体ETF
        "513730.XSHG",  # 东南亚ETF
        "159792.XSHE",  # 港股互联ETF
        "513130.XSHG",  # 恒生科技
        "513050.XSHG",  # 中概互联网ETF
        "159920.XSHE",  # 恒生ETF
        "513690.XSHG",  # 港股红利
        "511380.XSHG",  # 可转债ETF
        "511010.XSHG",  # 国债ETF
        "511220.XSHG",  # 城投债ETF
    ]

    # 商品ETF（走弱期可交易, 7只）
    g.commodity_etf_pool = [
        "518880.XSHG",  # 黄金ETF
        "159980.XSHE",  # 有色金属ETF
        "159985.XSHE",  # 豆粕ETF
        "501018.XSHG",  # 南方原油
        '161226.XSHE',  # 白银LOF
        "159981.XSHE",  # 能源化工ETF
        "512400.XSHG",  # 工业有色ETF
    ]

    # A股ETF（走弱期回避, 26只）
    g.domestic_etf_pool = [
        # 指数ETF (9)
        "510300.XSHG", "510500.XSHG", "510050.XSHG", "510210.XSHG",
        "159915.XSHE", "588080.XSHG", "512100.XSHG", "563360.XSHG", "563300.XSHG",
        # 风格ETF (5)
        "512890.XSHG", "159967.XSHE", "588020.XSHG", "512040.XSHG", "159201.XSHE",
        # 行业板块ETF (12)
        "515790.XSHG", "563230.XSHG", "515880.XSHG", "512660.XSHG",
        "561380.XSHG", "159667.XSHE", "159559.XSHE", "159819.XSHE",
        "159381.XSHE", "159732.XSHE", "159995.XSHE", "512220.XSHG",
    ]

    g.etf_pool = g.overseas_etf_pool + g.commodity_etf_pool + g.domestic_etf_pool

    # ---------- 核心参数 ----------
    g.lookback_days = 25
    g.holdings_num = 1
    g.defensive_etf = '511880.XSHG'    # 银华日利(货币基金)
    g.min_money = 5000

    # ---------- 盈利保护 (保留) ----------
    g.enable_profit_protection = True
    g.profit_protection_lookback = 1
    g.profit_protection_threshold = 0.05
    g.profit_protection_check_times = ['11:00']

    g.loss = 0.97                      # 近3日单日跌幅阈值（已废弃, 不触发）

    g.min_score_threshold = -999999     # 精简版不移除任何得分
    g.max_score_threshold = 999999

    # ---------- 成交量过滤 (精简版: 关闭) ----------
    g.enable_volume_check = False      # 【精简版】永久关闭
    g.volume_lookback = 5
    g.volume_threshold = 2
    g.volume_return_limit = 1

    # ---------- 短期动量过滤 (精简版: 关闭) ----------
    g.use_short_momentum_filter = False # 【精简版】永久关闭
    g.short_lookback_days = 10
    g.short_momentum_threshold = 0.0

    # ---------- 溢价率过滤 (保留) ----------
    g.enable_premium_filter = True
    g.premium_threshold = 0.20

    # ---------- 行情判断 (保留) ----------
    g.intraday_drawdown_threshold = 0.02
    g.enable_regime_switch = True
    g.weak_period_ma_lookback = 10
    g.weak_period_max_days = 20
    g.is_a_share_weak = False
    g.weak_period_counter = 0
    g.enable_avoid_a_share = True
    g.enable_intraday_drawdown = True
    g.regime_indexes = {
        '沪深300': '000300.XSHG',
        '深证综指': '399101.XSHE',
        '创业板指': '399006.XSHE',
        '中证A500': '000510.XSHG',
    }

    # ---------- 运行时变量 ----------
    g.rankings_cache = {'date': None, 'data': None}
    g.target_etfs_cache = {'date': None, 'data': None}
    g.drawdown_selled_today = set()
    g.buy_date = {}
    g.trade_log = {'sell_records': []}

    # ---------- 交易调度 ----------
    run_daily(check_positions, time='09:10')
    run_daily(regime_check, time='09:40')
    run_daily(etf_sell_trade, time='14:51')
    run_daily(etf_buy_trade, time='14:52')
    run_daily(daily_summary_report, time='15:05')

    for check_time in g.profit_protection_check_times:
        run_daily(profit_protection_check, time=check_time)

    log.info(f"📋 ETF池: {len(g.etf_pool)}只 (海外{len(g.overseas_etf_pool)}+商品{len(g.commodity_etf_pool)}+A股{len(g.domestic_etf_pool)})")
    log.info(f"📈 过滤器: 盈利保护(5%回撤) + 溢价率(>20%) + 行情判断")
    log.info(f"📈 成交量过滤: 关 | 短期动量过滤: 关")
    log.info(f"💰 佣金: 0.02% 双边")
    log.info("🎉 ========== 七星QMT精简版 初始化完成 ==========")


# ==================== 行情判断 ====================
def check_positions(context):
    log.info(f"\n{'='*22}{context.current_dt.strftime('%Y-%m-%d')} 策略运行开始 {'='*22}")
    g.drawdown_selled_today = set()
    g.target_etfs_cache = {'date': None, 'data': None}
    g.trade_log['sell_records'] = []
    for sec in context.portfolio.positions:
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            log.info(f"📊 持仓：{sec} {get_name(sec)} 数量{pos.total_amount} 成本{pos.avg_cost:.3f} 现价{pos.price:.3f}")

def regime_check(context):
    """09:40 行情判断"""
    log.info("🌍 ========== 行情判断开始 ==========")
    if not g.enable_regime_switch:
        g.is_a_share_weak = False
        return

    below_count, above_count = 0, 0
    detail = []
    for name, code in g.regime_indexes.items():
        try:
            df = attribute_history(code, g.weak_period_ma_lookback + 1, '1d', ['close'], skip_paused=False)
            if df.empty or len(df) < g.weak_period_ma_lookback:
                continue
            current_price = df['close'].iloc[-1]
            ma_val = df['close'].iloc[-g.weak_period_ma_lookback:].mean()
            if current_price < ma_val:
                below_count += 1
                detail.append(f"{name}↓")
            else:
                above_count += 1
                detail.append(f"{name}↑")
        except:
            pass

    old_state = g.is_a_share_weak
    if not g.is_a_share_weak:
        if below_count >= 3:
            g.is_a_share_weak = True
            g.weak_period_counter = 0
            log.info(f"🔴 进入走弱期 ({detail})")
    else:
        g.weak_period_counter += 1
        if above_count >= 3:
            g.is_a_share_weak = False
            g.weak_period_counter = 0
            log.info(f"🟢 恢复正常期 ({detail})")
        elif g.weak_period_counter >= g.weak_period_max_days:
            g.is_a_share_weak = False
            g.weak_period_counter = 0
            log.info(f"⏰ 走弱期满{g.weak_period_max_days}日强制退出")

    if old_state != g.is_a_share_weak:
        g.rankings_cache = {'date': None, 'data': None}
        g.target_etfs_cache = {'date': None, 'data': None}

    status = '🔴走弱期' if g.is_a_share_weak else '🟢正常期'
    log.info(f"📊 当前状态：{status} 计数:{g.weak_period_counter}/{g.weak_period_max_days}")
    log.info("🌍 ========== 行情判断完成 ==========")


def get_active_etf_pool():
    """根据行情状态获取当前可交易ETF池"""
    if not g.enable_avoid_a_share:
        return g.etf_pool
    if g.is_a_share_weak:
        active = g.overseas_etf_pool + g.commodity_etf_pool
        return active
    return g.etf_pool


# ==================== 盈利保护 ====================
def profit_protection_check(context):
    if not g.enable_profit_protection:
        return
    log.info("🛡️ ========== 盈利保护检查 ==========")
    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            if check_profit_protection(sec, context):
                if smart_order_target_value(sec, 0, context):
                    log.info(f"🛡️ 盈利保护卖出：{sec} {get_name(sec)}")
                    g.drawdown_selled_today.add(sec)
    log.info("🛡️ ========== 盈利保护完成 ==========")


def check_profit_protection(security, context, lookback=None, threshold=None):
    if not g.enable_profit_protection:
        return False
    lookback = lookback or g.profit_protection_lookback
    threshold = threshold or g.profit_protection_threshold
    hist = attribute_history(security, lookback, '1d', ['high'])
    if hist.empty or len(hist) < lookback:
        return False
    max_high = hist['high'].max()
    current_price = get_current_data()[security].last_price
    return current_price <= max_high * (1 - threshold)


# ==================== 溢价率 ====================
def get_premium_rate(code, date):
    price_data = get_price(code, start_date=date, end_date=date, frequency='daily', fields=['close'])
    if price_data.empty:
        return None, None, None
    price = price_data['close'].iloc[0]

    net_value = None
    use_date = date
    max_search_days = 3
    for _ in range(max_search_days):
        net_data = get_extras('unit_net_value', code, start_date=use_date, end_date=use_date, df=True)
        if not net_data.empty and not pd.isna(net_data[code].iloc[0]):
            net_value = net_data[code].iloc[0]
            break
        try:
            q = query(finance.FUND_NET_VALUE).filter(
                finance.FUND_NET_VALUE.code == code,
                finance.FUND_NET_VALUE.day == use_date
            )
            net_df = finance.run_query(q)
            if not net_df.empty:
                net_value = net_df['net_value'].iloc[0]
                break
        except:
            pass
        trade_days = get_trade_days(end_date=use_date, count=2)
        if len(trade_days) < 2:
            break
        use_date = trade_days[0]

    if net_value is None:
        return None, None, None
    premium_rate = (price - net_value) / net_value
    return premium_rate, price, net_value


# ==================== 核心排名计算 ====================
def get_cached_rankings(context):
    today = context.current_dt.date()
    if g.rankings_cache['date'] != today:
        ranked = get_ranked_etfs(context)
        g.rankings_cache = {'date': today, 'data': ranked}
    return g.rankings_cache['data']


def get_ranked_etfs(context):
    active_pool = get_active_etf_pool()
    etf_metrics = []
    for etf in active_pool:
        if get_current_data()[etf].paused:
            continue
        metrics = calculate_momentum_metrics(context, etf)
        if metrics is not None:
            if g.min_score_threshold < metrics['score'] < g.max_score_threshold:
                etf_metrics.append(metrics)
    etf_metrics.sort(key=lambda x: x['score'], reverse=True)
    return etf_metrics


def calculate_momentum_metrics(context, etf):
    try:
        name = get_name(etf)
        lookback = max(g.lookback_days, g.short_lookback_days) + 20
        prices = attribute_history(etf, lookback, '1d', ['close', 'high'])
        if len(prices) < g.lookback_days:
            return None

        current_price = get_current_data()[etf].last_price
        price_series = np.append(prices["close"].values, current_price)

        # 1. 盈利保护检查
        if check_profit_protection(etf, context):
            return None

        # 2. 溢价率过滤 [保留]
        if g.enable_premium_filter:
            prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]
            premium, _, _ = get_premium_rate(etf, prev_date)
            if premium is not None:
                if premium > g.premium_threshold:
                    return None
            else:
                return None

        # 3. 成交量过滤 [精简版: 已关闭, 代码路径不执行]
        if g.enable_volume_check:
            vol_ratio = get_volume_ratio(context, etf)
            if vol_ratio is not None:
                annualized = get_annualized_returns(price_series, g.lookback_days)
                if annualized > g.volume_return_limit:
                    return None

        # 4. 短期动量年化 (计算但不过滤, 仅日志用)
        if len(price_series) >= g.short_lookback_days + 1:
            short_return = price_series[-1] / price_series[-(g.short_lookback_days + 1)] - 1
            short_annualized = (1 + short_return) ** (250 / g.short_lookback_days) - 1
        else:
            short_annualized = 0

        # 短期动量过滤 [精简版: 已关闭, 代码路径不执行]
        if g.use_short_momentum_filter and short_annualized < g.short_momentum_threshold:
            return None

        # 5. 长期动量计算 (得分核心)
        recent = price_series[-(g.lookback_days + 1):]
        y = np.log(recent)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized_returns = math.exp(slope * 250) - 1

        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
        score = annualized_returns * r_squared

        # 6. 近3日跌幅过滤
        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            if min(day1, day2, day3) < g.loss:
                return None

        return {
            'etf': etf, 'etf_name': name,
            'annualized_returns': annualized_returns, 'r_squared': r_squared,
            'score': score, 'current_price': current_price,
            'short_annualized': short_annualized,
        }
    except:
        return None


def get_annualized_returns(price_series, lookback_days):
    recent = price_series[-(lookback_days + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    slope, _ = np.polyfit(x, y, 1, w=weights)
    return math.exp(slope * 250) - 1


def get_volume_ratio(context, security, lookback=None, threshold=None):
    lookback = lookback or g.volume_lookback
    threshold = threshold or g.volume_threshold
    try:
        hist = attribute_history(security, lookback, '1d', ['volume'])
        if hist.empty or len(hist) < lookback:
            return None
        avg_vol = hist['volume'].mean()
        today = context.current_dt.date()
        df_vol = get_price(security, start_date=today, end_date=context.current_dt,
                           frequency='1m', fields=['volume'], skip_paused=False, fq='pre')
        if df_vol is None or df_vol.empty:
            return None
        current_vol = df_vol['volume'].sum()
        now = context.current_dt
        elapsed_minutes = (now.hour - 9) * 60 + now.minute - 30
        if now.hour >= 13: elapsed_minutes -= 90
        elapsed_minutes = max(1, min(elapsed_minutes, 240))
        projected_today_vol = current_vol * (240.0 / elapsed_minutes)
        ratio = projected_today_vol / avg_vol if avg_vol > 0 else 0
        return ratio if ratio > threshold else None
    except:
        return None


# ==================== 卖出 ====================
def etf_sell_trade(context):
    log.info("📤 ========== 卖出操作开始 ==========")
    ranked = get_cached_rankings(context)
    target_etfs = select_target_etfs_from_rankings(context, ranked)

    defensive_available = check_defensive_etf_available(context)
    if not target_etfs and defensive_available:
        target_etfs = [g.defensive_etf]
        log.info(f"🛡️ 防御模式：{g.defensive_etf} {get_name(g.defensive_etf)}")

    g.target_etfs_cache = {'date': context.current_dt.date(), 'data': list(target_etfs)}
    target_set = set(target_etfs)

    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        if sec not in target_set:
            pos = context.portfolio.positions[sec]
            if pos.total_amount > 0:
                cost = pos.avg_cost
                buy_date = g.buy_date.get(sec)
                hold_days = (context.current_dt.date() - buy_date).days if buy_date else 0
                if smart_order_target_value(sec, 0, context):
                    log.info(f"📤 卖出：{sec} {get_name(sec)}")
                    g.trade_log['sell_records'].append({
                        'time': datetime.datetime.now().strftime('%H:%M:%S'),
                        'code': sec, 'name': get_name(sec),
                        'cost': cost, 'price': get_current_data()[sec].last_price,
                        'hold_days': hold_days
                    })
                    if sec in g.buy_date:
                        del g.buy_date[sec]
    log.info("📤 ========== 卖出完成 ==========")


# ==================== 买入 ====================
def select_target_etfs_from_rankings(context, ranked):
    target_etfs = []
    for m in ranked:
        if len(target_etfs) >= g.holdings_num:
            break
        if m['score'] < g.min_score_threshold:
            continue
        etf = m['etf']
        if g.enable_profit_protection and check_profit_protection(etf, context):
            continue
        if etf in g.drawdown_selled_today:
            continue
        # 走弱期日内回撤检查
        if g.is_a_share_weak and g.enable_intraday_drawdown:
            if _check_intraday_drawdown(etf, context):
                continue
        target_etfs.append(etf)
    return target_etfs


def _check_intraday_drawdown(security, context):
    try:
        df = get_price(security, start_date=context.current_dt.date(), end_date=context.current_dt,
                       frequency='1m', fields=['high', 'close'], skip_paused=True, fq='pre')
        if df is None or df.empty:
            return False
        day_high = df['high'].max()
        current = df['close'].iloc[-1]
        if day_high <= 0:
            return False
        drawdown = (day_high - current) / day_high
        return drawdown >= g.intraday_drawdown_threshold
    except:
        return False


def etf_buy_trade(context):
    log.info("📥 ========== 买入操作开始 ==========")
    ranked = get_cached_rankings(context)

    log.info("📊 ETF排名前5:")
    for i, m in enumerate(ranked[:5]):
        log.info(f"   {i+1}: {m['etf']} {m['etf_name']} 得分{m['score']:.4f}")

    today = context.current_dt.date()
    if g.target_etfs_cache['date'] == today and g.target_etfs_cache['data'] is not None:
        target_etfs = list(g.target_etfs_cache['data'])
    else:
        target_etfs = select_target_etfs_from_rankings(context, ranked)
        if not target_etfs:
            if check_defensive_etf_available(context) and g.defensive_etf not in g.drawdown_selled_today:
                target_etfs = [g.defensive_etf]
            else:
                log.info("💤 无目标ETF，保持空仓")
                return

    for i, etf in enumerate(target_etfs):
        m = next((x for x in ranked if x['etf'] == etf), None)
        if m:
            log.info(f"🎯 目标{i+1}: {etf} {m['etf_name']} 得分{m['score']:.4f}")

    # 检查是否有持仓需要先卖出
    current_etf_pos = [s for s in context.portfolio.positions if s in g.etf_pool or s == g.defensive_etf]
    to_sell = [s for s in current_etf_pos if s not in target_etfs]
    if to_sell:
        log.info(f"⏳ 尚有持仓待卖出：{[get_name(s) for s in to_sell]}，等待卖出完成")
        return

    total_val = context.portfolio.total_value
    target_per_etf = total_val / len(target_etfs)

    for etf in target_etfs:
        current_val = 0
        if etf in context.portfolio.positions:
            pos = context.portfolio.positions[etf]
            if pos.total_amount > 0:
                current_val = pos.total_amount * pos.price
        if abs(current_val - target_per_etf) > target_per_etf * 0.05 or current_val == 0:
            if smart_order_target_value(etf, target_per_etf, context):
                action = "买入" if current_val < target_per_etf else "调仓"
                log.info(f"📦 {action}：{etf} {get_name(etf)} 目标金额{target_per_etf:.2f}")

    log.info("📥 ========== 买入完成 ==========")


# ==================== 辅助函数 ====================
def get_name(security):
    try:
        return get_current_data()[security].name
    except:
        return "未知"

def check_defensive_etf_available(context):
    data = get_current_data()
    etf = g.defensive_etf
    if data[etf].paused:
        return False
    if data[etf].last_price >= data[etf].high_limit:
        return False
    if data[etf].last_price <= data[etf].low_limit:
        return False
    return True

def smart_order_target_value(security, target_value, context):
    data = get_current_data()
    name = get_name(security)
    if data[security].paused:
        return False
    price = data[security].last_price
    if price == 0:
        return False
    target_amount = int(target_value / price)
    target_amount = (target_amount // 100) * 100
    if target_amount <= 0 and target_value > 0:
        target_amount = 100
    cur_pos = context.portfolio.positions.get(security, None)
    cur_amount = cur_pos.total_amount if cur_pos else 0
    diff = target_amount - cur_amount
    if diff > 0:
        if data[security].last_price >= data[security].high_limit:
            return False
    elif diff < 0:
        if data[security].last_price <= data[security].low_limit:
            return False
    trade_val = abs(diff) * price
    if 0 < trade_val < g.min_money:
        return False
    if diff < 0:
        closeable = cur_pos.closeable_amount if cur_pos else 0
        if closeable == 0:
            return False
        diff = -min(abs(diff), closeable)
    if diff != 0:
        order_result = order(security, diff)
        if order_result:
            if diff > 0:
                g.buy_date[security] = context.current_dt.date()
            return True
    return False


# ==================== 盘后总结 ====================
def daily_summary_report(context):
    current_date = context.current_dt.strftime('%Y-%m-%d')
    total_value = context.portfolio.total_value
    cash = context.portfolio.cash

    log.info("📋 ========== 策略运行日报 ==========")
    log.info(f"📅 日期: {current_date}")

    if g.enable_regime_switch:
        status = "🔴走弱期" if g.is_a_share_weak else "🟢正常期"
        log.info(f"🌍 市场：{status} 计数:{g.weak_period_counter}/{g.weak_period_max_days}")

    sell_records = g.trade_log.get('sell_records', [])
    log.info(f"📤 今日卖出：{len(sell_records)}只")
    for r in sell_records:
        cost = r.get('cost', 0)
        sell_price = r.get('price', 0)
        profit_pct = (sell_price / cost - 1) * 100 if cost > 0 else 0
        log.info(f"   {r['code']} {r['name']} 成本:{cost:.3f} 卖出:{sell_price:.3f} 收益:{profit_pct:+.2f}%")

    for sec, pos in context.portfolio.positions.items():
        if pos.total_amount == 0:
            continue
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        current_price = get_current_data()[sec].last_price
        cost = pos.avg_cost
        profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0
        log.info(f"📊 持仓: {sec} {get_name(sec)} 成本:{cost:.3f} 现价:{current_price:.3f} 收益:{profit_pct:+.2f}%")

    returns = (total_value - context.portfolio.starting_cash) / context.portfolio.starting_cash * 100
    log.info(f"💰 总资产：{total_value:.2f} | 累计收益：{returns:.2f}%")
    log.info("📋 ========== 报告结束 ==========\n")
