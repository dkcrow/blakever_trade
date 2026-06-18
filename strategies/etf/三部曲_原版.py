# 克隆自聚宽文章：https://www.joinquant.com/post/57189
# 标题：讨论下大家正在实盘的策略
# 作者：专注小市值

# 克隆自聚宽文章：https://www.joinquant.com/post/66388
# 标题：【三部曲吃透ETF动量3】地囚人，欲成仙，殊不知，天亦囚仙
# 作者：烟花三月ETF
# 修复版：解决重复定义、双重删除、score过滤、放量卖出等bug

from jqdata import *
import datetime
import math
import numpy as np
from scipy.optimize import minimize
import pandas as pd

# --- 全局配置与常量 ---
etf_pool = [
    "513100.XSHG", "159509.XSHE", "513520.XSHG", "513030.XSHG", "518880.XSHG",
    "159985.XSHE", "159981.XSHE", "501018.XSHG", "511260.XSHG", "513130.XSHG",
    "513690.XSHG", "510180.XSHG", "159915.XSHE", "510410.XSHG", "515650.XSHG",
    "588120.XSHG", "159851.XSHE", "159637.XSHE", "516160.XSHG", "159550.XSHE",
    "515250.XSHG", "159378.XSHE", "516510.XSHG", "515050.XSHG", "515000.XSHG",
    "159529.XSHE"
]

g_strategys = {}
g_portfolio_value_proportion = [1]
g_positions = {i: {} for i in range(len(g_portfolio_value_proportion))}
g_weights = {}
g_channel = 'etfld'

# 策略配置
g_etf_rotation = {
    "index": 0,
    "name": "核心资产轮动策略",
    "stock_sum": 1,
    "hold_list": [],
    "min_money": 500,
    "etf_pool": etf_pool,
    "m_days": 25,
    "enable_volume_check": False,   # 【修复4】默认关闭放量卖出，与动量逻辑一致
    "volume_lookback_days": 5,
    "volume_threshold": 1.0,
    "ma_filter_days": 20,
    "enable_ma_filter": False,
    "score_upper": 5,              # 【修复3】score上限从5放宽至20，保留防极端值
}


# --- 辅助函数 ---
def order_(context, security, vol):
    try:
        o = order(security, vol)
        return o
    except Exception as e:
        log.error(f"下单失败 {security}: {str(e)}")
        return None


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    log.info("策略初始化完成（修复版）")
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')

    set_slippage(FixedSlippage(0.0001), type="fund")
    set_slippage(FixedSlippage(0.003), type="stock")

    set_order_cost(
        OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003,
                  close_commission=0.0003, close_today_commission=0, min_commission=5),
        type="stock",
    )
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0,
                             close_commission=0, close_today_commission=0, min_commission=0),
                   type="mmf")

    if g_portfolio_value_proportion[0] > 0:
        run_daily(etf_rotation_sell, "10:40")
        run_daily(etf_rotation_buy, "10:40")
    run_daily(end_trade, "14:59")


def process_initialize(context):
    global g_strategys
    g_strategys = {"核心资产轮动策略": {"index": 0, "name": "核心资产轮动策略"}}


def end_trade(context):
    """
    收盘前同步持仓记录，清理无关持仓
    """
    marked = {s for d in g_positions.values() for s in d}
    current_data = get_current_data()

    for stock in context.portfolio.positions:
        if stock not in marked:
            pos = context.portfolio.positions[stock].total_amount
            price = current_data[stock].last_price

            if stock in etf_pool:
                index = g_etf_rotation["index"]
                old_recorded_pos = g_positions[index].get(stock, 0)
                g_positions[index][stock] = pos
                g_etf_rotation["hold_list"] = list(g_positions[index].keys())
                log.info(f"更新持仓记录: {stock}({current_data[stock].name}) "
                         f"数量从 {old_recorded_pos} 更新为 {pos}")
            else:
                if my_order(context, stock, -pos, price, 0):
                    log.info(f"清理无关持仓: 卖出{stock}({current_data[stock].name}), "
                             f"价格{price}, 数量{pos}")


# ================================================================
# 【修复1】只保留一个可靠版本的 etf_rotation_order_target_value
# 使用账户实际持仓更新 g_positions，避免部分成交导致记录不准
# ================================================================
def etf_rotation_order_target_value(context, security, value):
    strategy = g_etf_rotation
    current_data = get_current_data()

    cd = current_data[security]
    if cd.paused:
        log.info(f"{security}: 今日停牌")
        return False
    if cd.last_price == cd.high_limit:
        log.info(f"{security}: 涨停")
        return False
    if cd.last_price == cd.low_limit:
        log.info(f"{security}: 跌停")
        return False

    price = cd.last_price
    current_position = g_positions[strategy["index"]].get(security, 0)

    target_position = (int(value / price) // 100) * 100 if price != 0 else 0
    adjustment = target_position - current_position

    # T+1限制检查
    closeable_amount = context.portfolio.positions[security].closeable_amount \
        if security in context.portfolio.positions else 0
    if adjustment < 0 and closeable_amount == 0:
        log.info(f"{security}: T+1限制，无法卖出")
        return False

    if adjustment != 0:
        o = my_order(context, security, adjustment, price, target_position)
        if o:
            # 核心修改：用账户实际持仓更新，最可靠
            actual_total = context.portfolio.positions[security].total_amount \
                if security in context.portfolio.positions else 0
            if actual_total > 0:
                g_positions[strategy["index"]][security] = actual_total
            else:
                g_positions[strategy["index"]].pop(security, None)

            g_etf_rotation["hold_list"] = list(g_positions[strategy["index"]].keys())
            log.debug(f"订单执行完成: {security}. 本地持仓记录已更新为: {actual_total}")
            return True
    else:
        # 无需调整时也同步一次实际持仓
        actual_total = context.portfolio.positions[security].total_amount \
            if security in context.portfolio.positions else 0
        if actual_total > 0:
            g_positions[strategy["index"]][security] = actual_total
        else:
            g_positions[strategy["index"]].pop(security, None)
        g_etf_rotation["hold_list"] = list(g_positions[strategy["index"]].keys())

    return False


def my_order(context, security, vol, price, target_position):
    try:
        return order_(context, security, vol)
    except Exception as e:
        log.error(f"my_order 执行失败 {security}: {str(e)}")
        return None


def get_etf_rotation_total_value(context):
    index = g_etf_rotation["index"]
    if not g_positions[index]:
        return 0
    total_value = 0
    for key, value in g_positions[index].items():
        if key in context.portfolio.positions:
            price = context.portfolio.positions[key].price
            total_value += price * value
    return total_value


def get_volume_ratio(context, security, lookback_days, threshold):
    """计算当前成交量与历史均量的比值"""
    try:
        hist_data = attribute_history(security, lookback_days, '1d', ['volume'])
        if hist_data is None or len(hist_data) < lookback_days:
            return None
        avg_volume = hist_data['volume'].mean()

        today = context.current_dt.date()
        df_vol = get_price(security, start_date=today, end_date=context.current_dt,
                           frequency='1m', fields=['volume'], skip_paused=False, fq='pre')
        if df_vol is None or df_vol.empty:
            return None

        current_volume = df_vol['volume'].sum()
        ratio = current_volume / avg_volume if avg_volume > 0 else 0
        return ratio if ratio > threshold else None
    except:
        return None


def filter_below_ma_with_detail(stocks, days=20):
    """返回 (保留列表, 被剔除明细列表)"""
    if not stocks:
        return [], []
    current_data = get_current_data()
    kept = []
    removed = []

    for stock in stocks:
        try:
            hist = attribute_history(stock, days, "1d", ["close"])
            if hist is None or len(hist) < days:
                continue
            ma_n = hist["close"].mean()
            current_price = current_data[stock].last_price
            name = current_data[stock].name if stock in current_data else 'Unknown'

            if current_price >= ma_n:
                kept.append(stock)
            else:
                removed.append((stock, name, current_price, ma_n))
        except Exception as e:
            continue
    return kept, removed


def etf_rotation_filter(context, operation_time=""):
    """ETF筛选逻辑，计算动量得分并排序"""
    strategy = g_etf_rotation
    log.info(f"--- ETF筛选开始 (原始池: {len(strategy['etf_pool'])}) ---")

    # Step 1: 均线过滤
    filtered_pool = strategy["etf_pool"]
    removed_list = []
    if strategy["enable_ma_filter"]:
        filtered_pool, removed_list = filter_below_ma_with_detail(
            filtered_pool, strategy["ma_filter_days"])
        log.info(f"均线过滤后: {len(filtered_pool)} 只")

        if removed_list:
            log.info("=== 被均线过滤剔除的ETF（当前价 < MA20）===")
            for code, name, price, ma in removed_list:
                log.info(f"{code}({name}) - 当前价:{price:.4f}, MA20:{ma:.4f}")
        else:
            log.info("=== 无ETF被均线过滤剔除 ===")

    # Step 2: 计算评分
    data = pd.DataFrame(columns=["annualized_returns", "r2", "score"])
    current_data = get_current_data()

    for etf in filtered_pool:
        try:
            df = attribute_history(etf, strategy["m_days"], "1d", ["close"])
            if df is None or len(df) < strategy["m_days"]:
                continue
            prices = df["close"].values
            current_price = current_data[etf].last_price
            prices = np.append(prices, current_price)

            if np.any(prices <= 0):
                continue

            y = np.log(prices)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))

            if np.allclose(y, y[0]):
                slope = 0.0
            else:
                slope, intercept = np.polyfit(x, y, 1, w=weights)

            annualized_returns = math.exp(slope * 250) - 1
            fitted_y = slope * x + intercept
            ss_res = np.sum(weights * (y - fitted_y) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            score = annualized_returns * r2

            data.loc[etf] = [annualized_returns, r2, score]

        except Exception as e:
            continue

    # Step 3: 应用评分条件（【修复3】上限放宽至 score_upper）
    score_upper = strategy.get("score_upper", 20)
    if not data.empty:
        valid_data = data.query(f"0 < score < {score_upper}").sort_values(
            by="score", ascending=False)
    else:
        valid_data = pd.DataFrame()

    # 列出评分详情
    log.info(f"=== 所有通过均线过滤的ETF评分详情（共{len(data)}只）===")
    current_data = get_current_data()
    for idx in data.index:
        row = data.loc[idx]
        name = current_data[idx].name if idx in current_data else 'Unknown'
        if idx in valid_data.index:
            status = "✅ 有效"
        else:
            if row['score'] <= 0:
                reason = "score ≤ 0"
            elif row['score'] >= score_upper:
                reason = f"score ≥ {score_upper}"
            else:
                reason = "其他"
            status = f"❌ 无效（{reason}）"
        log.info(f"{idx}({name}) - 评分:{row['score']:.6f} | "
                 f"动量:{row['annualized_returns']*100:.2f}% | "
                 f"R²:{row['r2']:.3f} | {status}")

    selected_etfs = valid_data.index.tolist()
    log.info(f"--- 筛选结束，最终入选: {selected_etfs} ---")
    return selected_etfs


def get_cached_etf_targets(context):
    """带缓存的ETF目标获取函数"""
    today = context.current_dt.date()
    if hasattr(context, 'etf_rotation_cache') \
       and context.etf_rotation_cache.get('date') == today:
        return context.etf_rotation_cache['targets']

    raw_targets = etf_rotation_filter(context)
    targets = raw_targets[:g_etf_rotation["stock_sum"]]

    context.etf_rotation_cache = {
        'date': today,
        'targets': targets
    }
    return targets


def check_etf_rotation_holdings(context):
    strategy = g_etf_rotation
    hold = list(g_positions[strategy["index"]].keys())
    if not hold:
        return []
    current_data = get_current_data()
    return [s for s in hold if current_data[s].last_price < current_data[s].high_limit]


# ================================================================
# 【修复2】卖出函数：移除双重删除，由 etf_rotation_order_target_value 统一管理
# ================================================================
def etf_rotation_sell(context):
    targets = get_cached_etf_targets(context)

    current_data = get_current_data()
    hold_list = list(g_positions[g_etf_rotation["index"]].keys())
    original_holds = set(hold_list)

    log.info(f"=== 卖出逻辑 === 目标: {targets}, 当前持仓: {hold_list}")

    # 放量卖出（可选，默认关闭）
    if g_etf_rotation["enable_volume_check"]:
        for stock in hold_list[:]:
            vol_ratio = get_volume_ratio(
                context, stock,
                g_etf_rotation["volume_lookback_days"],
                g_etf_rotation["volume_threshold"])
            if vol_ratio is not None:
                current_pos = g_positions[g_etf_rotation["index"]].get(stock, 0)
                log.info(f"【放量卖出】{stock}({current_data[stock].name}) "
                         f"放量比值:{vol_ratio:.2f}, 卖出{current_pos}股")
                etf_rotation_order_target_value(context, stock, 0)
                # ✅ 不再手动 del，由 etf_rotation_order_target_value 内部处理

    # 不在目标列表中则卖出
    for stock in hold_list[:]:
        if stock not in targets:
            if stock not in g_positions[g_etf_rotation["index"]]:
                continue
            current_pos = g_positions[g_etf_rotation["index"]][stock]
            log.info(f"【目标外卖出】{stock}({current_data[stock].name}), "
                     f"卖出{current_pos}股")
            etf_rotation_order_target_value(context, stock, 0)
            # ✅ 不再手动 del

    # 超仓卖出
    current_hold_in_targets = [s for s in g_positions[g_etf_rotation["index"]]
                               if s in targets]
    if len(current_hold_in_targets) > g_etf_rotation["stock_sum"]:
        for stock in current_hold_in_targets[g_etf_rotation["stock_sum"]:]:
            log.info(f"【超仓卖出】{stock}")
            etf_rotation_order_target_value(context, stock, 0)

    final_holds = set(g_positions[g_etf_rotation["index"]].keys())
    sold = original_holds - final_holds
    if sold:
        log.info(f"=== 卖出完成，共卖出 {len(sold)} 只: {list(sold)} ===")
    else:
        log.info("=== 无卖出操作 ===")


# ================================================================
# 【修复4】买入函数：current_hold_count 随循环动态更新
# ================================================================
def etf_rotation_buy(context):
    targets = get_cached_etf_targets(context)

    if not targets:
        log.info("无目标ETF，跳过买入")
        return

    log.info(f"=== 买入逻辑 === 目标: {targets}")

    current_data = get_current_data()
    portfolio = context.portfolio
    total_value = portfolio.total_value
    available_cash = portfolio.available_cash
    target_value = total_value * g_portfolio_value_proportion[g_etf_rotation["index"]]

    # ✅ 动态跟踪当前已持有目标ETF的数量
    current_hold_count = 0

    for stock in targets:
        current_position = g_positions[g_etf_rotation["index"]].get(stock, 0)
        last_price = current_data[stock].last_price
        current_value = current_position * last_price
        weight = 1 / len(targets)
        target = target_value * weight

        if current_position > 0:
            # 已持有该标的，计入持仓数量
            current_hold_count += 1
            # 补仓逻辑：当前仓位低于目标90%时补仓
            if current_value < target * 0.9:
                rebalance_amount = target - current_value
                if rebalance_amount > max(g_etf_rotation["min_money"], last_price * 100):
                    log.info(f"补仓 {stock}({current_data[stock].name}) - "
                             f"补仓金额 {rebalance_amount:.2f}元")
                    etf_rotation_order_target_value(context, stock, target)
        else:
            # 未持有，全新买入
            if current_hold_count == 0:
                need_buy_value = target - current_value
                actual_buy_value = min(need_buy_value, available_cash)
                if actual_buy_value <= max(g_etf_rotation["min_money"], last_price * 100):
                    log.info(f"跳过 {stock} - 金额太小 ({actual_buy_value:.2f}元)")
                    continue
                log.info(f"买入 {stock}({current_data[stock].name}) - "
                         f"目标金额 {target:.2f}元")
                etf_rotation_order_target_value(context, stock, target)
                # ✅ 买入成功后更新计数
                if g_positions[g_etf_rotation["index"]].get(stock, 0) > 0:
                    current_hold_count += 1
            else:
                # 已有其他持仓，判断是否需要买入新标的
                need_buy_value = target - current_value
                actual_buy_value = min(need_buy_value, available_cash)
                if actual_buy_value > max(g_etf_rotation["min_money"], last_price * 100):
                    log.info(f"买入 {stock}({current_data[stock].name}) - "
                             f"目标金额 {target:.2f}元")
                    etf_rotation_order_target_value(context, stock, target)
                    if g_positions[g_etf_rotation["index"]].get(stock, 0) > 0:
                        current_hold_count += 1

    log.info(f"=== 买入完成，当前持仓: "
             f"{list(g_positions[g_etf_rotation['index']].keys())} ===")


def filter_limitup_stock(stocks, n):
    current_data = get_current_data()
    return [stock for stock in stocks
            if current_data[stock].last_price != current_data[stock].high_limit]
