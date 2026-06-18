# 标题：七星超级加175v311 V3.15 双风险规避定版（聚宽）
# 作者：任侠

"""
七星超级加175v311 V3.15 双风险规避定版（聚宽独立版，基于 V3.14）

【说明】
- 由合并版 `七星超级加175v311V3.15.py` 拆分；QMT 端见 `七星超级加175v311V3.15-QMT.py`。

【变更记录】
- V3.15 [2026/05/25]（当前定版）
  - 盈利仓分钟回撤豁免：浮盈≥10% 时分钟守卫不卖，改由 13:09/盈利保护处理（修 3/4 原油 10:31 误杀）。
  - 盈利仓 13:09 回撤仅用日内高点→现价，不用昨收跳空（保留对亏损仓的昨收低开保护）。
  - 同日 13:09 轮动卖海外后，13:10 允许买入另一只 QDII（修 6/5 标普→日经被挡又买回标普）。
- V3.14 [2026/05/25]
  - 日内回撤守卫扩展：get_intraday_drawdown_ratio 买入/13:09 持仓/分钟检查三处共用；持仓触发则强制卖并剔除目标缓存。
  - 关闭防御 ETF 兜底（enable_defensive_etf=False）：无合格标的时保持空仓，减少 511010 换仓摩擦（全周期约 37 笔）。
  - 双弱无商品标的时亦空仓（不再兜底 511010）。
  - 持仓回撤补昨收基准：除日内高点→现价外，兼看昨收→现价（覆盖跳空低开）。
  - 有害卖出冷却期内禁止买回同一只标的（修复 6/4 卖出 513520 后 6/5 又买回）。
  - 回撤测算统一 float 转换（修复分钟检查 str/float 异常导致盘中守卫失效）。
- V3.13 [2026/05/25]
  - 双风险规避固定：A 股弱（回避 A 股 ETF）+ 海外弱（屏蔽 QDII）独立判断、四格池、盘中现价双轨复检。
  - 13:09/13:10 统一 refresh_regime_for_trade：A 股弱与海外弱同分钟各检一次，边界迟滞 + 有效池/守卫/缓存复检闭环。
  - 定版目标：规避国内系统性风险与海外 QDII 风险，双弱时仅商品池（V3.13 曾兜底 511010，V3.14 已关）。
- V3.12.3 [2026/05/25]
  - 海外弱双轨：09:40 日 K 定调 + 13:09/13:10 盘中现价对 MA 复检（真正「越晚越准」）。
  - 边界迟滞：同日 enter/exit 同时满足时维持原状态，盘中退出门槛 3/4（严于进入 2/4），且每分钟只复检一次。
- V3.12.2 [2026/05/25]
  - resolve_rotation_targets / select_target 统一强制当前有效池过滤；池与缓存排名不一致时兜底路径自动重算排名，杜绝回退仍选池外 QDII。
- V3.12.1 [2026/05/25]
  - 13:10 复用缓存前：刷新海外弱状态，对缓存目标复跑全部买入守卫，并剔除当前有效池外弱势标；不足则排名顺延或 resolve 兜底。
- V3.12 [2026/05/25]
  - 海外弱独立判断（与 A 股弱解耦）：4 个 QDII 代理 MA10/MA5 结构，≥2/4 进入海外弱。
  - 四格 active_pool：A正常+海外弱→A股+商品；A弱+海外弱→仅商品；海外弱即屏蔽 QDII 排名。
  - 海外弱时商品替代买入门槛 buy_min_score_overseas_weak；无合格标的仍走 511010 兜底。
  - 走弱期轮动卖出海外 QDII 后 1 日禁买同簇；有害卖 2 日 qdii_guard 保留。
  - overseas_proxy_pool 去掉 513100，与 159509 对齐。
- V3.11 [2026/05/25]
  - 在 V3.10 高收益骨架上精修：走弱期有害卖出由「2日全盘空仓」改为「2日仅挡QDII追高」，商品/原油等可继续轮动（修复3月原油被挡）。
  - 走弱期冷却内叠加：海外有害簇挡 + 低相关守卫（仅挡高相关海外，不挡商品）。
  - 排名得分上限 100→10000，避免超高动量主线被误杀。
- V3.10 [2026/05/25]
  - 有害卖出冷却收窄：正常期仅禁止同日买回该标的（drawdown_selled_today），不暂停轮动、不强制511010。
  - 走弱期保留有害卖出后2日空仓（防6/3纳指回撤后接日经）。
  - 买入得分保持V3.9：仅下限0.2、上限100，无年化上限。
- V3.9 [2026/05/25]
  - 买入仅下限0.2/上限100；V3.9回测1-5月约195%（V3.6约220%），差距主因正常期有害冷却误杀轮动。
- V3.8 [2026/05/25]
  - 买入得分[0.2,10.0]；关闭全局年化上限；有害卖出后严带≤2.5（实测仍挡主线）。
- V3.7 [2026/06/03]
  - 有害卖出冷却：分钟回撤/盈利保护卖出后暂停轮动；正常期防御511010，走弱期空仓；冷却1日/走弱2日。
  - 震荡期空仓（参考175）：震荡期无合格标的不买511010，保持空仓。
  - 买入得分双轨：排名宽区间[0,100]；买入阶段得分[0.2,2.5]+可选年化上限200%（仅买不卖）。
- V3.6 [2026/06/03]
  - 融合七星175阶段1：全时期均线结构硬过滤(价>MA10且MA5>MA10)、R²≥0.35、拉普拉斯/高斯 per-ETF 滤波。
  - 510300 震荡期切换(13:05检查)：正常期拉普拉斯、震荡期高斯；保留走弱期切池+511010防御+is_etf_tradable。
- V3.5 [2026/06/03]
  - 退出弱势期：废弃「≥3 指数站上 MA10 连续 2 日」；改为「≥3 指数 MA5、MA10 较前一日同时上升」；20 日强制退出不变。
  - 盘中停牌防护：is_etf_tradable（paused + 本交易时段无成交）；目标选择 / 13:10 缓存复检 / 下单前拦截；不可买则排名顺延。
  - 策略文件为 .py；QMT 代码见独立文件 `七星超级加175v311V3.15-QMT.py`。
- V3.4 [2026/05/31]
  - 退出弱势期条件调整（聚宽 + QMT 同步）：
    * 原「当日 ≥3 指数站上 MA10 即恢复」改为「≥3 指数站上 MA10 连续 2 个交易日」方可恢复。
    * 走弱期满 20 日强制退出逻辑不变。
- V3.3 [2026/05/31]
  - 弱势期第二路条件调整（聚宽 + QMT 同步）：
    * 移除 MA10 近 5 日斜率向下判断。
    * 改为 ≥3 个指数满足「MA5/MA10 死叉」或「MA5 < MA10」。
    * 第一路「≥3 指数现价 < MA10」保留；退出弱势逻辑不变。
- V3.2 [2026/05/31]
  - 弱势期判断升级（聚宽 + QMT 同步）：
    * 监测指数由 4 个扩充为 6 个：在原有沪深300、深证综指、创业板指、中证A500 基础上，新增上证指数(000001)、深证成指(399001)。
    * 进入弱势期条件（满足其一即可）：① ≥3 个指数当前价低于各自 10 日均线；② ≥3 个指数 10 日均线近 5 日斜率向下。
- V3 [2026/05/30]
  - 修复「同日先卖后买同一标的」的 bug：
    * 根因：卖出模块只看 ranked[:N] 前 N 名（无过滤），买入模块遍历全部排名并应用多种过滤（盈利保护/日内回撤），前 N 名被过滤后排名靠后的 ETF 会被"提拔"到目标列表，导致 13:09 卖出的 ETF 在 13:10 又被买入。
    * 修复：提取统一函数 select_target_etfs_from_rankings()，卖出与买入共用完全相同的目标选择逻辑，保证同一交易日内两者的目标集合严格一致。
    * 补充：13:09 卖出时将最终目标列表写入 g.target_etfs_cache，13:10 买入直接复用，避免日内回撤等时间敏感过滤在 1 分钟内变化导致买卖目标再次分歧。
- V2 [2026/05/29]
  - 卖出分类优化：区分"有害卖出"（回撤/盈利保护）和"中性卖出"（排名轮动/溢价率）
    * 新增 g.drawdown_selled_today 记录有害卖出标的，禁止日内买回；中性卖出（轮动/溢价率）不禁止日内买回
  - 日内回撤守卫（get_intraday_drawdown_ratio）：买入过滤 + 13:09 持仓强制卖 + 分钟检查共用；原 check_intraday_drawdown_for_buy：
    * 任何买入候选标的需通过日内回撤检查（>2%回撤暂不买入），避免"接飞刀"
  - 防御ETF检查改用 drawdown_selled_today，仅在回撤/盈利保护卖出时禁止买回
"""

import numpy as np
import math
import datetime
import pandas as pd
import time
from functools import wraps
from jqdata import *

# ==================== 物理时间监控装饰器 ====================
def time_monitor(func_name=None):
    """时间监控装饰器，记录函数执行的真实物理时间"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            start_real = datetime.datetime.now()

            log.info(f"⏱️ [{func_name or func.__name__}] 开始执行 - 真实时间: {start_real.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")

            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                end_real = datetime.datetime.now()
                elapsed = end_time - start_time

                log.info(f"✅ [{func_name or func.__name__}] 执行完成 - 耗时: {elapsed*1000:.2f}ms | 真实时间: {end_real.strftime('%H:%M:%S')}")

                if elapsed > 0.95:
                    log.warning(f"⚠️ [{func_name or func.__name__}] 执行耗时过长: {elapsed*1000:.2f}ms")

                return result
            except Exception as e:
                end_time = time.time()
                elapsed = end_time - start_time
                log.error(f"❌ [{func_name or func.__name__}] 执行异常 - 耗时: {elapsed*1000:.2f}ms | 错误: {str(e)[:100]}")
                raise
        return wrapper
    return decorator

# ==================== 辅助函数：获取真实时间 ====================
def get_real_time():
    return datetime.datetime.now().strftime('%H:%M:%S')

# ==================== 初始化模块 ====================
def initialize(context):
    """
    初始化函数：设置交易参数、ETF池、核心参数、调度任务
    """
    g.strategy_version = 'V3.15'
    g.strategy_id = 'QX3.15'
    g.strategy_log_marker = '[QX3.15]'

    # ---------- 交易设置 ----------
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0005,
            close_commission=0.0005,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    set_benchmark("000300.XSHG")

    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    log.info("🚀 ========== 策略初始化开始 ==========")

    # ---------- ETF池 ----------
    g.etf_pool_bak = [
        "518880.XSHG",   # 黄金ETF
        "159985.XSHE",   # 豆粕ETF
        "501018.XSHG",   # 南方原油
        "161226.XSHE",   # 白银LOF
        "513100.XSHG",   # 纳指ETF
        "159915.XSHE",   # 创业板ETF
        "511220.XSHG",   # 城投债ETF
    ]

    # ==========按类别分类ETF ==========
    # 海外ETF（走弱期可交易）
    g.overseas_etf_pool = [
        "513100.XSHG",  # 纳指ETF
        "159509.XSHE",  # 纳指科技ETF
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
        # 债券ETF
        "511380.XSHG",  # 可转债ETF
        "511010.XSHG",  # 国债ETF
        "511220.XSHG",  # 城投债ETF
    ]

    # 商品ETF（走弱期可交易）
    g.commodity_etf_pool = [
        "518880.XSHG",  # 黄金ETF
        "159980.XSHE",  # 有色金属ETF
        "159985.XSHE",  # 豆粕ETF
        "501018.XSHG",  # 南方原油
        '161226.XSHE',  # 白银LOF
        "159981.XSHE",  # 能源化工ETF
        "512400.XSHG",  # 工业有色ETF
    ]

    # A股ETF（走弱期回避）
    g.domestic_etf_pool = [
        # 指数ETF
        "510300.XSHG",  # 沪深300ETF
        "510500.XSHG",  # 中证500ETF
        "510050.XSHG",  # 上证50ETF
        "510210.XSHG",  # 上证ETF
        "159915.XSHE",  # 创业板ETF
        "588080.XSHG",  # 科创50
        "512100.XSHG",  # 中证1000ETF
        "563360.XSHG",  # A500-ETF
        "563300.XSHG",  # 中证2000ETF
        # 风格ETF
        "512890.XSHG",  # 红利低波ETF
        "159967.XSHE",  # 创业板成长ETF
        "588020.XSHG",  # 科创成长ETF
        "512040.XSHG",  # 价值ETF
        "159201.XSHE",  # 自由现金流ETF
        # 行业板块ETF
        "515790.XSHG",   # 光伏ETF
        "563230.XSHG",   # 卫星ETF
        "515880.XSHG",   # 通信ETF
        "512660.XSHG",   # 军工ETF
        "561380.XSHG",   # 电网设备ETF
        "159667.XSHE",   # 工业母机ETF
        "159559.XSHE",   # 机器人ETF
        "159819.XSHE",   # 人工智能ETF
        "159381.XSHE",   # 创业板人工智能ETF
        "159732.XSHE",   # 消费电子ETF
        "159995.XSHE",   # 芯片ETF
        "512220.XSHG",   # TMT(科技传媒通信150）ETF
    ]

    # 完整ETF池（初始化时合并）
    g.etf_pool = g.overseas_etf_pool + g.commodity_etf_pool + g.domestic_etf_pool

    # ---------- 核心参数 ----------
    g.lookback_days = 25               # 动量计算周期
    g.holdings_num = 1                 # 候选数量
    g.defensive_etf = '511010.XSHG'    # 避险资产：10年国债ETF（enable_defensive_etf 关时不买入）
    g.enable_defensive_etf = False     # False=无标的时空仓；True=兜底买入 511010
    g.min_money = 5000                 # 最小交易金额

    # ---------- 盈利保护参数 ----------
    g.enable_profit_protection = True                      # 盈利保护开关
    g.profit_protection_lookback = 1                       # 盈利保护回看周期（天）
    g.profit_protection_threshold = 0.05                   # 盈利保护回撤阈值（5%）

    # 盈利保护检查时间点
    g.profit_protection_check_times = ['11:00']


    g.loss = 0.97                      # 近3日单日跌幅阈值（排除）

    # ---------- 得分区间（排名宽 / 买入窄）----------
    g.rank_min_score = 0               # 排名入围下限
    g.rank_max_score = 10000.0         # 排名入围上限（实质取消，防误杀超高动量）
    g.min_score_threshold = 0          # 兼容别名 → rank_min_score
    g.max_score_threshold = 10000.0    # 兼容别名 → rank_max_score
    g.enable_buy_score_band = True     # 买入阶段得分区间开关（仅下限，不设上限）
    g.buy_min_score = 0.20             # 买入得分下限（挡极弱标的）
    g.buy_max_score = 100.0            # 买入得分上限（与排名同宽，不挡高分主线）
    g.enable_buy_annualized_cap = False  # 关闭年化上限
    g.buy_max_annualized = 5.0         # 备用（默认不启用）
    g.enable_cooldown_strict_buy_band = False  # 关闭冷却后严买入带（V3.8实测误杀高分）
    g.buy_max_score_cooldown = 2.50
    g.enable_buy_annualized_cap_cooldown = False
    g.buy_max_annualized_cooldown = 2.0
    g.harmful_sell_strict_extra_days = 0

    # ---------- 有害卖出冷却（V3.11：走弱期仅挡QDII追高，商品继续轮动）----------
    g.enable_harmful_sell_guard = True
    g.harmful_sell_last_date = None
    g.harmful_sell_last_security = None
    g.harmful_sell_cooldown_days = 0       # 正常期不暂停轮动（仅 drawdown_selled_today 禁同日买回）
    g.harmful_sell_cooldown_weak_days = 2  # 走弱期冷却交易日
    g.harmful_sell_mode_normal = 'rotation'   # 正常期：继续轮动
    g.harmful_sell_mode_weak = 'qdii_guard'   # 走弱期：仅挡海外追高，不全盘空仓

    # ---------- 走弱期有害卖后 QDII 精准防追高（V3.11）----------
    g.enable_weak_qdii_guard = True
    g.overseas_proxy_pool = [
        '159509.XSHE', '513500.XSHG', '513520.XSHG', '513400.XSHG',
        '513290.XSHG', '513030.XSHG',
        '513130.XSHG', '513050.XSHG', '159920.XSHE',
    ]
    g.correlation_lookback = 20
    g.correlation_max = 0.88

    # ---------- 海外弱判断（V3.12：独立于 A 股弱）----------
    g.enable_overseas_regime_switch = True
    g.enable_overseas_weak_shield = True
    g.is_overseas_weak = False
    g.overseas_weak_counter = 0
    g.overseas_weak_max_days = 20
    g.overseas_weak_enter_count = 2          # ≥2/4 代理走弱即进入
    g.overseas_weak_exit_count = 2           # 日频退出：≥2/4 MA5/10 回升
    g.overseas_weak_intraday_exit_count = 3  # 盘中退出：≥3/4（严于进入，防边界抖动）
    g._regime_trade_refresh_key = None       # 盘中双风险复检去重（每分钟一次）
    g.overseas_regime_proxies = {
        '纳指科技': '159509.XSHE',
        '标普500': '513500.XSHG',
        '道琼斯': '513400.XSHG',
        '日经': '513520.XSHG',
    }
    g.overseas_bond_etfs = {
        '511380.XSHG', '511010.XSHG', '511220.XSHG',
    }

    # ---------- 海外弱时商品替代门槛（非默认兜底）----------
    g.enable_overseas_weak_commodity_gate = True
    g.buy_min_score_overseas_weak = 0.50
    g.enable_overseas_weak_cash = False      # True=海外弱无商品时空仓（与 enable_defensive_etf 独立）

    # ---------- 走弱期轮动卖海外冷却（V3.12，补 6/3）----------
    g.enable_overseas_rotation_guard = True
    g.overseas_rotation_sell_last_date = None
    g.overseas_rotation_sell_last_security = None
    g.overseas_rotation_cooldown_days = 1

    # ---------- 震荡期空仓（参考175）----------
    g.enable_range_bound_cash = True

    # ---------- 成交量过滤 ----------
    g.enable_volume_check = True
    g.volume_lookback = 5
    g.volume_threshold = 2
    g.volume_return_limit = 1          # 年化收益>100%时启用放量过滤

    # ---------- 短期动量过滤 ----------
    g.use_short_momentum_filter = True
    g.short_lookback_days = 10
    g.short_momentum_threshold = 0.0

    # ---------- 溢价率过滤 ----------
    g.enable_premium_filter = True      # 是否启用溢价率过滤
    g.premium_threshold = 0.20          # 溢价率阈值（20%）


    # ---------- R² 过滤（参考七星175）----------
    g.enable_r2_filter = True
    g.r2_threshold = 0.35

    # ---------- 均线趋势结构硬过滤 ----------
    g.enable_trend_structure_filter = True
    g.trend_ma_period = 10
    g.trend_require_price_above_ma = True
    g.trend_require_ma5_above_ma10 = True

    # ---------- 震荡期 + 拉普拉斯/高斯（参考七星175/172）----------
    g.enable_range_bound_mode = True
    g.current_filter = '正常期'
    g.risk_state = '正常期'
    g.lookback_high_low_days = 20
    g.risk_benchmark = '510300.XSHG'
    g.laplace_s_param = 0.05
    g.laplace_min_slope = 0.001
    g.gaussian_sigma = 1.2
    g.gaussian_min_slope = 0.002
    g.enable_bias_trigger = True
    g.bias_threshold = 0.10
    g.ma_period = 20
    g.enable_rsi_trigger = True
    g.rsi_overbought = 75
    g.rsi_pullback = 60
    g.previous_rsi = None
    g.enable_stop_loss_trigger = False
    g.stop_loss_triggered_today = False
    g.stop_loss_triggered_date = None
    g.enable_low_point_rise_trigger = True
    g.low_point_rise_threshold = 0.03
    g.enable_stable_signal_trigger = True
    g.drawdown_recovery = 0.03
    g.max_range_bound_days = 15
    g.stable_days = 0
    g.filter_switch_cooldown = 2
    g.last_switch_date = None
    g.range_bound_start_date = None
    g.range_bound_days_count = 0
    g.previous_drawdown = None

    # ========== 分钟级当日回撤保护（V2.1：开关自动跟随行情状态） ==========
    g.intraday_drawdown_threshold = 0.02            # 当日回撤阈值（2%）
    g.enable_holding_prev_close_drawdown = True     # 持仓兼看昨收→现价回撤（补跳空低开）
    g.holding_profit_skip_minute_pct = 0.10       # 浮盈≥10%：分钟守卫不卖（防盈利商品早盘误杀）
    g.holding_profit_skip_prev_close_pct = 0.10   # 浮盈≥10%：13:09 不用昨收跳空触发卖
    # 注意：不再使用 g.enable_intraday_drawdown，改为在 handle_data 中动态判断
    # ================================================================

    # ==========  A股行情判断 ==========
    g.enable_regime_switch = True                    # 行情判断开关
    g.weak_period_ma_lookback = 10                   # 10日均线
    g.weak_period_max_days = 20                      # 走弱期最长持续20个交易日
    g.is_a_share_weak = False                        # 当前是否走弱期
    g.a_share_weak_daily_lock = False                # 09:40日频走弱后当日禁止盘中假恢复
    g.weak_period_counter = 0                        # 走弱期天数计数器
    g.a_share_weak_enter_count = 3                   # ≥3/6 指数走弱进入 A 股弱
    g.a_share_weak_exit_count = 3                    # 日频退出：≥3/6 MA5/10 回升
    g.a_share_intraday_exit_count = 4                # 盘中退出：≥4/6（严于进入，防边界抖动）
    # g.weak_exit_above_streak = 0                     # ≥3指数站上MA10的连续交易日数（满2日退出）
    # g.weak_exit_above_days = 2                       # 退出弱势：站上MA10须连续满足的天数
    # ==========  独立手动开关 ==========
    g.enable_avoid_a_share = True                    # 走弱期回避A股开关（关闭则走弱期不回避A股）
    g.enable_intraday_drawdown = True                # 分钟级回撤保护独立开关（关闭则不触发）
    # ==========================================
    g.regime_indexes = {                             # 监测指数（V3.3：6指数 + 价破线/MA5死叉双条件）
        '上证指数': '000001.XSHG',
        '沪深300': '000300.XSHG',
        '深证成指': '399001.XSHE',
        '深证综指': '399101.XSHE',
        '创业板指': '399006.XSHE',
        '中证A500': '000510.XSHG',
    }
    # ============================================

    # ---------- 运行时变量 ----------
    g.rankings_cache = {'date': None, 'data': None}   # 排名缓存
    g.target_etfs_cache = {'date': None, 'data': None}  # 13:09 目标ETF缓存，供13:10买入复用
    g.drawdown_selled_today = set()                    # 当日因回撤/盈利保护卖出的标的（禁止日内买回）

    # 盘后总结需要的变量
    g.buy_date = {}                                    # 记录买入日期
    g.trade_log = {'sell_records': []}                 # 记录当日卖出

    # ---------- 交易调度 ----------
    run_daily(check_positions, time='09:10')
    run_daily(regime_check, time='09:40')              # 行情判断
    run_daily(check_range_bound, time='13:05')         # 震荡期/滤波器切换
    run_daily(etf_sell_trade, time='13:09')
    run_daily(etf_buy_trade, time='13:10')
    run_daily(reset_range_bound_daily, time='15:10')
    run_daily(daily_summary_report, time='15:05')      # 盘后总结

    # 动态注册盈利保护检查时间点
    for check_time in g.profit_protection_check_times:
        run_daily(profit_protection_check, time=check_time)
        log.info(f"📅 已注册盈利保护检查时间：{check_time}")

    # V2.2 日志
    if g.enable_regime_switch:
        log.info(f"🌍 A股行情判断已启用，走弱期最长{g.weak_period_max_days}日")
        if g.enable_avoid_a_share:
            log.info(f"🔄 走弱期回避A股开关：ON（走弱期自动回避A股ETF）")
        else:
            log.info(f"⚠️ 走弱期回避A股开关：OFF（走弱期仍交易A股ETF）")
        if g.enable_intraday_drawdown:
            log.info(f"🛡️ 分钟级回撤保护开关：ON（走弱期自动启用）")
        else:
            log.info(f"⭕ 分钟级回撤保护开关：OFF（不触发）")
    else:
        log.info("⚠️ A股行情判断未启用")

    log.info(f"📋 策略初始化完成：ETF池{len(g.etf_pool)}只（海外{len(g.overseas_etf_pool)}只+商品{len(g.commodity_etf_pool)}只+A股{len(g.domestic_etf_pool)}只）")
    log.info(f"📈 盈利保护：{'开' if g.enable_profit_protection else '关'}，回撤{g.profit_protection_threshold*100:.0f}%")
    log.info(
        f"💰 盈利仓回撤豁免：分钟不卖≥{g.holding_profit_skip_minute_pct*100:.0f}%浮盈；"
        f"13:09不卖昨收跳空≥{g.holding_profit_skip_prev_close_pct*100:.0f}%浮盈"
    )
    if g.enable_premium_filter:
        log.info(f"💰 溢价率过滤已启用，阈值：{g.premium_threshold*100:.0f}%")
    else:
        log.info("⚠️ 溢价率过滤未启用")

    marker = getattr(g, 'strategy_log_marker', '[QX3.14]')
    log.info(f"{marker} 策略版本：{g.strategy_version} | STRATEGY_ID={g.strategy_id}")
    log.info("%s 走弱有害卖=%s 弱QDII守卫=%s 海外弱屏蔽=%s 轮动卖挡海外=%s rank_max=%.0f" % (
        marker, g.harmful_sell_mode_weak,
        'on' if g.enable_weak_qdii_guard else 'off',
        'on' if g.enable_overseas_weak_shield else 'off',
        'on' if g.enable_overseas_rotation_guard else 'off',
        g.rank_max_score))
    if g.enable_overseas_regime_switch:
        log.info(
            "🌐 海外弱判断：ON 进入≥%d/4 日退≥%d/4 盘中退≥%d/4 商品替代下限=%.2f" % (
                g.overseas_weak_enter_count, g.overseas_weak_exit_count,
                g.overseas_weak_intraday_exit_count, g.buy_min_score_overseas_weak,
            )
        )
    log.info(
        "🛡️ 双风险规避定版：A股弱≥%d/6回避A股 | 海外弱屏蔽QDII | 双弱→仅商品 | 防御511010=%s"
        % (g.a_share_weak_enter_count, "开" if g.enable_defensive_etf else "关(空仓)")
    )
    log.info("📐 趋势过滤：均线=%s R2=%s 滤波=%s(%s)" % (
        "开" if g.enable_trend_structure_filter else "关",
        "开" if g.enable_r2_filter else "关",
        "开" if g.enable_range_bound_mode else "关", g.current_filter))
    log.info("📊 买入得分：%s 下限=%.2f 上限=%.0f(同排名) 年化上限=关 冷却严带=关" % (
        "开" if g.enable_buy_score_band else "关",
        g.buy_min_score, g.buy_max_score))
    log.info("🛡️ 有害卖出冷却：%s 正常=仅禁同日买回 走弱%d日空仓 震荡期空仓=%s" % (
        "开" if g.enable_harmful_sell_guard else "关",
        g.harmful_sell_cooldown_weak_days,
        "开" if g.enable_range_bound_cash else "关"))
    init_range_bound_status(context)
    log.info("🎉 ========== 策略初始化完成 ==========")


# ==================== 开盘检查模块 ====================
def check_positions(context):
    """每日开盘检查持仓状态"""

    # 日期标记
    log.info(f"\n{'='*22}🐂🧨🧨🧨🧨🧨{context.current_dt.strftime('%Y-%m-%d')}📌策略运行开始📌一路长红🧨🧨🧨🧨🧨🐂{'='*22}")

    g.drawdown_selled_today = set()                    # 清空当日回撤卖出缓存
    g.a_share_weak_daily_lock = False                    # 新交易日重置，09:40日频后再锁定
    g.target_etfs_cache = {'date': None, 'data': None}
    g.trade_log['sell_records'] = []
    for sec in context.portfolio.positions:
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            log.info(f"📊 持仓：{sec} {get_name(sec)} 数量{pos.total_amount} 成本{pos.avg_cost:.3f} 现价{pos.price:.3f}")

# ====================  行情判断模块 ====================
def _index_live_price(context, code):
    """指数/ETF 盘中现价。"""
    try:
        price = get_current_data()[code].last_price
        if price is not None and price > 0:
            return price
    except Exception:
        pass
    return None


def compute_a_share_regime_signals(context, use_intraday=False):
    """统计 6 指数 A 股弱信号。盘中模式用现价对已完成日 K 的 MA。"""
    below_count, ma_weak_count, ma_recover_count = 0, 0, 0
    detail = []
    need_days = max(g.weak_period_ma_lookback, 5) + 1
    price_tag = '盘中' if use_intraday else '日频'

    for name, code in g.regime_indexes.items():
        try:
            df = attribute_history(code, need_days + 2, '1d', ['close'], skip_paused=False)
            if df.empty or len(df) < need_days + 1:
                continue
            closes = df['close'].values

            if use_intraday:
                live = _index_live_price(context, code)
                current_price = live if live is not None else closes[-1]
                base = closes[:-1] if len(closes) > need_days else closes
                if len(base) < g.weak_period_ma_lookback + 1:
                    continue
                ma10 = base[-g.weak_period_ma_lookback:].mean()
                ma5 = base[-5:].mean()
                ma10_prev = base[-(g.weak_period_ma_lookback + 1):-1].mean()
                ma5_prev = base[-6:-1].mean()
            else:
                current_price = closes[-1]
                ma10 = closes[-g.weak_period_ma_lookback:].mean()
                ma5 = closes[-5:].mean()
                ma10_prev = closes[-(g.weak_period_ma_lookback + 1):-1].mean()
                ma5_prev = closes[-6:-1].mean()

            if current_price < ma10:
                below_count += 1
                detail.append(f"{name}↓")
            else:
                detail.append(f"{name}↑")
            death_cross = ma5 < ma10 and ma5_prev >= ma10_prev
            if death_cross or ma5 < ma10:
                ma_weak_count += 1
                tag = '死叉' if death_cross else 'MA5<10'
                detail[-1] = detail[-1] + f'({tag})'
            if ma5 > ma5_prev and ma10 > ma10_prev:
                ma_recover_count += 1
                detail[-1] = detail[-1] + '(MA5↑10↑)'
        except Exception as e:
            log.warning(f"⚠️ 指数{name}获取失败: {e}")

    return below_count, ma_weak_count, ma_recover_count, detail, price_tag


def _log_a_share_transition(entering_weak):
    if entering_weak:
        if g.enable_avoid_a_share:
            log.info("   → 将回避A股ETF，仅交易海外+商品ETF")
        else:
            log.info("   → ⚠️ 回避A股开关已关闭，仍交易全市场ETF")
        if g.enable_intraday_drawdown:
            log.info(f"   → 🛡️ 分钟级回撤保护已启用（阈值{g.intraday_drawdown_threshold*100:.0f}%）")
        else:
            log.info("   → ⭕ 分钟级回撤保护已被独立开关关闭，不触发")
    else:
        if g.enable_avoid_a_share:
            log.info("   → 恢复交易A股ETF")
        else:
            log.info("   → 回避A股开关关闭，始终交易全市场")
        if g.enable_intraday_drawdown:
            log.info("   → 关闭分钟级回撤保护")
        else:
            log.info("   → 分钟级回撤保护独立开关已关闭，无变化")


def _apply_a_share_regime_state(context, below_count, ma_weak_count, ma_recover_count,
                                detail, mode='daily'):
    """应用 A 股弱状态迁移；边界 enter+exit 同时满足时维持原状。"""
    enter_n = g.a_share_weak_enter_count
    exit_n = (
        g.a_share_intraday_exit_count if mode == 'intraday'
        else g.a_share_weak_exit_count
    )
    would_enter = below_count >= enter_n or ma_weak_count >= enter_n
    would_exit = ma_recover_count >= exit_n
    old_state = g.is_a_share_weak
    prefix = '🕐盘中' if mode == 'intraday' else ''

    if not g.is_a_share_weak:
        if would_enter:
            g.is_a_share_weak = True
            g.weak_period_counter = 0
            reasons = []
            if below_count >= enter_n:
                reasons.append(f"价破线:{below_count}")
            if ma_weak_count >= enter_n:
                reasons.append(f"MA5弱:{ma_weak_count}")
            log.info(f"🔴 {prefix}进入走弱期 ({' + '.join(reasons)} {detail})")
            _log_a_share_transition(True)
    else:
        if mode == 'daily':
            g.weak_period_counter += 1
        if would_exit and would_enter:
            log.info(f"⚖️ {prefix}A股弱边界僵持(进/退同触)，维持走弱期 {detail}")
        elif would_exit:
            if mode == 'intraday' and g.a_share_weak_daily_lock:
                log.info(
                    f"🔒 {prefix}日频已确认走弱，忽略盘中假恢复，维持走弱期 {detail}"
                )
            else:
                g.is_a_share_weak = False
                g.weak_period_counter = 0
                log.info(f"🟢 {prefix}恢复正常期 (≥{exit_n}指数MA5/10↑:{ma_recover_count} {detail})")
                _log_a_share_transition(False)
        elif mode == 'daily' and g.weak_period_counter >= g.weak_period_max_days:
            g.is_a_share_weak = False
            g.weak_period_counter = 0
            log.info(f"⏰ 走弱期满{g.weak_period_max_days}日强制退出，恢复正常期")
            _log_a_share_transition(False)

    state_changed = old_state != g.is_a_share_weak
    if state_changed:
        g.rankings_cache = {'date': None, 'data': None}
        if mode == 'intraday':
            g.target_etfs_cache = {'date': None, 'data': None}
    return state_changed


def a_share_regime_check(context):
    """09:40 日频 A 股弱判断。"""
    if not g.enable_regime_switch:
        g.is_a_share_weak = False
        return False
    signals = compute_a_share_regime_signals(context, use_intraday=False)
    changed = _apply_a_share_regime_state(context, *signals[:4], mode='daily')
    ma_recover = signals[2]
    if g.enable_regime_switch:
        current_status = '🔴走弱期' if g.is_a_share_weak else '🟢正常期'
        avoid_status = (
            '(回避A股)' if (g.is_a_share_weak and g.enable_avoid_a_share)
            else ('(不回避A股)' if g.is_a_share_weak else '')
        )
        drawdown_status = (
            '🛡️启用' if (g.is_a_share_weak and g.enable_intraday_drawdown)
            else '⭕关闭'
        )
        recover_info = (
            f" MA5/10↑:{ma_recover}/{len(g.regime_indexes)}"
            if g.is_a_share_weak else ""
        )
        log.info(
            f"📊 当前状态：{current_status}{avoid_status} "
            f"计数:{g.weak_period_counter}/{g.weak_period_max_days}{recover_info}"
        )
        log.info(f"📊 分钟级回撤保护：{drawdown_status}（阈值{g.intraday_drawdown_threshold*100:.0f}%）")
    g.a_share_weak_daily_lock = bool(g.is_a_share_weak)
    return changed


def regime_check(context):
    """每日 9:40 双风险日频定调：A 股弱 + 海外弱。"""
    log.info("🌍 ========== 行情判断开始（双风险日频）==========")
    overseas_regime_check(context)
    a_share_regime_check(context)
    log.info("🌍 ========== 行情判断完成 ==========")


def _overseas_proxy_live_price(context, code):
    """盘中海外代理现价；无效时返回 None。"""
    try:
        price = get_current_data()[code].last_price
        if price is not None and price > 0:
            return price
    except Exception:
        pass
    return None


def compute_overseas_regime_signals(context, use_intraday=False):
    """统计 4 代理海外弱信号。盘中模式用现价对已完成日 K 的 MA。"""
    below_count, ma_weak_count, ma_recover_count = 0, 0, 0
    detail = []
    need_days = max(g.weak_period_ma_lookback, 5) + 1
    price_tag = '盘中' if use_intraday else '日频'

    for name, code in g.overseas_regime_proxies.items():
        try:
            df = attribute_history(code, need_days + 2, '1d', ['close'], skip_paused=False)
            if df.empty or len(df) < need_days + 1:
                continue
            closes = df['close'].values

            if use_intraday:
                live = _overseas_proxy_live_price(context, code)
                current_price = live if live is not None else closes[-1]
                base = closes[:-1] if len(closes) > need_days else closes
                if len(base) < g.weak_period_ma_lookback + 1:
                    continue
                ma10 = base[-g.weak_period_ma_lookback:].mean()
                ma5 = base[-5:].mean()
                ma10_prev = base[-(g.weak_period_ma_lookback + 1):-1].mean()
                ma5_prev = base[-6:-1].mean()
            else:
                current_price = closes[-1]
                ma10 = closes[-g.weak_period_ma_lookback:].mean()
                ma5 = closes[-5:].mean()
                ma10_prev = closes[-(g.weak_period_ma_lookback + 1):-1].mean()
                ma5_prev = closes[-6:-1].mean()

            if current_price < ma10:
                below_count += 1
                detail.append(f"{name}↓")
            else:
                detail.append(f"{name}↑")
            death_cross = ma5 < ma10 and ma5_prev >= ma10_prev
            if death_cross or ma5 < ma10:
                ma_weak_count += 1
                tag = '死叉' if death_cross else 'MA5<10'
                detail[-1] = detail[-1] + f'({tag})'
            if ma5 > ma5_prev and ma10 > ma10_prev:
                ma_recover_count += 1
                detail[-1] = detail[-1] + '(MA5↑10↑)'
        except Exception as e:
            log.warning(f"⚠️ 海外代理{name}获取失败: {e}")

    return below_count, ma_weak_count, ma_recover_count, detail, price_tag


def _apply_overseas_regime_state(context, below_count, ma_weak_count, ma_recover_count,
                                 detail, mode='daily'):
    """应用海外弱状态迁移；边界 enter+exit 同时满足时维持原状（迟滞）。"""
    enter_n = g.overseas_weak_enter_count
    if mode == 'intraday':
        exit_n = g.overseas_weak_intraday_exit_count
    else:
        exit_n = g.overseas_weak_exit_count

    would_enter = below_count >= enter_n or ma_weak_count >= enter_n
    would_exit = ma_recover_count >= exit_n
    old_state = g.is_overseas_weak
    prefix = '🕐盘中' if mode == 'intraday' else ''

    if not g.is_overseas_weak:
        if would_enter:
            g.is_overseas_weak = True
            g.overseas_weak_counter = 0
            reasons = []
            if below_count >= enter_n:
                reasons.append(f"价破线:{below_count}")
            if ma_weak_count >= enter_n:
                reasons.append(f"MA5弱:{ma_weak_count}")
            log.info(f"🔴 {prefix}进入海外弱 ({' + '.join(reasons)} {detail})")
    else:
        if mode == 'daily':
            g.overseas_weak_counter += 1
        if would_exit and would_enter:
            log.info(f"⚖️ {prefix}海外弱边界僵持(进/退同触)，维持海外弱 {detail}")
        elif would_exit:
            g.is_overseas_weak = False
            g.overseas_weak_counter = 0
            log.info(f"🟢 {prefix}海外弱恢复 (≥{exit_n}代理MA5/10↑:{ma_recover_count} {detail})")
        elif mode == 'daily' and g.overseas_weak_counter >= g.overseas_weak_max_days:
            g.is_overseas_weak = False
            g.overseas_weak_counter = 0
            log.info(f"⏰ 海外弱满{g.overseas_weak_max_days}日强制退出 {detail}")

    state_changed = old_state != g.is_overseas_weak
    if state_changed:
        g.rankings_cache = {'date': None, 'data': None}
        if mode == 'intraday':
            g.target_etfs_cache = {'date': None, 'data': None}
    if state_changed or g.is_overseas_weak:
        ostatus = '🔴海外弱' if g.is_overseas_weak else '🟢海外正常'
        log.info(f"🌐 海外状态：{ostatus} 计数:{g.overseas_weak_counter}/{g.overseas_weak_max_days}")
    return state_changed


def overseas_regime_check(context):
    """09:40 日频海外弱判断（独立于 A 股弱）。"""
    if not g.enable_overseas_regime_switch:
        g.is_overseas_weak = False
        return False
    signals = compute_overseas_regime_signals(context, use_intraday=False)
    return _apply_overseas_regime_state(context, *signals[:4], mode='daily')


def refresh_regime_for_trade(context):
    """13:09/13:10 双风险盘中复检（A股弱+海外弱）；同一分钟只执行一次。"""
    key = (context.current_dt.date(), context.current_dt.strftime('%H%M'))
    if getattr(g, '_regime_trade_refresh_key', None) == key:
        return False
    g._regime_trade_refresh_key = key
    changed = False
    if g.enable_overseas_regime_switch:
        signals = compute_overseas_regime_signals(context, use_intraday=True)
        below, ma_weak, ma_recover, detail, price_tag = signals
        log.info(f"🕐 盘中海外弱复检({price_tag}) 价破:{below} MA弱:{ma_weak} MA回升:{ma_recover}")
        changed |= _apply_overseas_regime_state(
            context, below, ma_weak, ma_recover, detail, mode='intraday'
        )
    if g.enable_regime_switch:
        signals = compute_a_share_regime_signals(context, use_intraday=True)
        below, ma_weak, ma_recover, detail, price_tag = signals
        log.info(f"🕐 盘中A股弱复检({price_tag}) 价破:{below} MA弱:{ma_weak} MA回升:{ma_recover}")
        changed |= _apply_a_share_regime_state(
            context, below, ma_weak, ma_recover, detail, mode='intraday'
        )
    return changed


def refresh_overseas_regime_for_trade(context):
    """兼容别名 → 双风险盘中复检。"""
    return refresh_regime_for_trade(context)


def is_overseas_qdii(etf):
    """海外池中的 QDII 权益类（不含债券）。"""
    bond_set = getattr(g, 'overseas_bond_etfs', set())
    return etf in g.overseas_etf_pool and etf not in bond_set


def is_intraday_drawdown_enabled():
    """判断分钟级回撤保护是否启用
    V2.2: 优先判断独立开关，关闭则不触发；开启则走弱期自动启用"""
    # 独立开关关闭 → 不触发
    if not g.enable_intraday_drawdown:
        return False
    # 行情判断未启用 → 不触发
    if not g.enable_regime_switch:
        return False
    # 走弱期自动启用
    return g.is_a_share_weak


def get_active_etf_pool():
    """根据 A 股弱 × 海外弱 四格矩阵返回可排名池（V3.12）。"""
    overseas_shield = (
        g.enable_overseas_weak_shield
        and g.enable_overseas_regime_switch
        and g.is_overseas_weak
    )

    if not g.enable_avoid_a_share:
        if overseas_shield and g.is_a_share_weak:
            active_pool = list(g.commodity_etf_pool)
            log.info(f"📊 【A弱+海外弱】仅商品池({len(active_pool)}只) [回避A股关]")
        elif overseas_shield:
            active_pool = list(g.domestic_etf_pool) + list(g.commodity_etf_pool)
            log.info(f"📊 【海外弱】A股+商品池({len(active_pool)}只) [回避A股关]")
        else:
            active_pool = list(g.etf_pool)
            log.info(f"📊 【强制】A股回避关，完整池({len(active_pool)}只)")
        return active_pool

    if g.is_a_share_weak:
        if overseas_shield:
            active_pool = list(g.commodity_etf_pool)
            log.info(f"📊 【A弱+海外弱】仅商品池({len(active_pool)}只)")
        else:
            active_pool = list(g.overseas_etf_pool) + list(g.commodity_etf_pool)
            log.info(f"📊 【走弱期】海外+商品池({len(active_pool)}只)")
    elif overseas_shield:
        active_pool = list(g.domestic_etf_pool) + list(g.commodity_etf_pool)
        log.info(f"📊 【海外弱】A股+商品池({len(active_pool)}只)")
    else:
        active_pool = list(g.etf_pool)
        log.info(f"📊 【正常期】完整池({len(active_pool)}只)")
    return active_pool


# ==================== 分钟级回测入口：每分钟执行一次 ====================
def handle_data(context, data):
    """当回测/实盘频率设为'分钟'时，此函数每分钟自动调用一次。
    V2.1: 只在走弱期执行回撤检查，正常期跳过
    V2.2: 受独立开关控制"""
    # V2.2: 动态判断是否启用（独立开关 + 走弱期）
    if not is_intraday_drawdown_enabled():
        return

    # 9:46 之后才执行检查
    current_time = context.current_dt.strftime('%H:%M')
    if current_time < '09:46':
        return

    intraday_drawdown_check(context)


# ==================== 分钟级当日回撤检查函数 ====================
def intraday_drawdown_check(context):
    """每分钟执行一次，检查所有持仓从当日盘中最高点的回撤。
    V2.1: 此函数仅在走弱期被调用
    V2.2: 受独立开关控制"""
    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount == 0:
            continue
        # 跳过当日买入的ETF（避免刚买入就被日内回撤保护卖出）
        if g.buy_date.get(sec) == context.current_dt.date():
            continue

        try:
            drawdown, detail, threshold = get_holding_drawdown_for_sell(
                sec, context, source='minute'
            )
            if (
                drawdown is not None
                and threshold is not None
                and drawdown >= threshold
            ):
                execute_intraday_drawdown_sell(
                    context, sec, drawdown, source='分钟级',
                    detail=detail, threshold=threshold
                )
        except Exception as e:
            log.debug(f"分钟级回撤检查异常 {sec}: {e}")


# ==================== 盈利保护独立检查函数 ====================
@time_monitor(func_name="盈利保护检查")
def profit_protection_check(context):
    """独立执行的盈利保护检查函数"""
    if not g.enable_profit_protection:
        log.debug("盈利保护模块已关闭，跳过检查")
        return

    log.info("🛡️ ========== 盈利保护检查开始 ==========")
    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            if check_profit_protection(sec, context):
                if smart_order_target_value(sec, 0, context):
                    log.info(f"🛡️ 盈利保护卖出：{sec} {get_name(sec)}")
                    g.drawdown_selled_today.add(sec)
                    mark_harmful_sell(context, sec)
                    if getattr(g, 'enable_stop_loss_trigger', False):
                        g.stop_loss_triggered_today = True
                        g.stop_loss_triggered_date = context.current_dt.date()
    log.info("🛡️ ========== 盈利保护检查完成 ==========")


# ==================== 盈利保护检查函数（核心逻辑） ====================
def check_profit_protection(security, context, lookback=None, threshold=None):
    """检查是否触发盈利保护（从最近N日最高点回撤超过阈值）"""
    if not g.enable_profit_protection:
        return False

    lookback = lookback or g.profit_protection_lookback
    threshold = threshold or g.profit_protection_threshold

    hist = attribute_history(security, lookback, '1d', ['high'])
    if hist.empty or len(hist) < lookback:
        return False

    max_high = hist['high'].max()
    current_price = get_current_data()[security].last_price

    if current_price <= max_high * (1 - threshold):
        log.info(f"🔻 盈利保护触发 {security} 回撤{(1-current_price/max_high)*100:.2f}% > {threshold*100:.0f}%")
        return True
    return False


# ==================== 溢价率获取函数 ====================
def get_premium_rate(code, date):
    """获取指定交易日的溢价率，自动向前寻找最近有净值的交易日"""
    price_data = get_price(code, start_date=date, end_date=date, frequency='daily', fields=['close'])
    if price_data.empty:
        log.debug(f"⚠️ {date} {code} 无交易价格数据")
        return None, None, None
    price = price_data['close'].iloc[0]

    net_value = None
    use_date = date
    max_search_days = 3
    found = False

    for _ in range(max_search_days):
        net_data = get_extras('unit_net_value', code, start_date=use_date, end_date=use_date, df=True)
        if not net_data.empty and not pd.isna(net_data[code].iloc[0]):
            net_value = net_data[code].iloc[0]
            found = True
            break

        try:
            q = query(finance.FUND_NET_VALUE).filter(
                finance.FUND_NET_VALUE.code == code,
                finance.FUND_NET_VALUE.day == use_date
            )
            net_df = finance.run_query(q)
            if not net_df.empty:
                net_value = net_df['net_value'].iloc[0]
                found = True
                break
        except:
            pass

        trade_days = get_trade_days(end_date=use_date, count=2)
        if len(trade_days) < 2:
            break
        use_date = trade_days[0]

    if not found or net_value is None:
        log.debug(f"⚠️ {code} 在{date}无净值数据")
        return None, None, None

    if use_date != date:
        log.debug(f"🔍 {code} 使用最近净值日期 {use_date}")

    premium_rate = (price - net_value) / net_value
    return premium_rate, price, net_value



# ==================== 震荡期机制（拉普拉斯/高斯，参考七星175）====================
def calculate_rsi(close, period=14):
    try:
        if len(close) < period + 1:
            return None
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except Exception:
        return None


def laplace_filter(price, s=0.05):
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price, sigma=1.2):
    n = len(price)
    if n < 2:
        return 0, 0
    idx_1 = np.arange(n)
    weights_1 = np.exp(-((idx_1 + 1) ** 2) / (2 * sigma ** 2))[::-1]
    weights_1 /= np.sum(weights_1)
    g1 = np.sum(price * weights_1)
    price_2 = price[:-1]
    idx_2 = np.arange(n - 1)
    weights_2 = np.exp(-((idx_2 + 1) ** 2) / (2 * sigma ** 2))[::-1]
    weights_2 /= np.sum(weights_2)
    g2 = np.sum(price_2 * weights_2)
    return g1, g2


def get_risk_benchmark_state(context):
    required_days = max(g.ma_period, g.lookback_high_low_days)
    lookback = required_days + 30
    end_date = getattr(context, 'previous_date', None)
    if end_date is None:
        return None
    df = get_price(g.risk_benchmark, end_date=end_date, count=lookback,
                   frequency='daily', fields=['close', 'high', 'low'], panel=False)
    if df is None or len(df) < required_days:
        return None
    daily_close = df['close'].values.astype(float)
    daily_high = df['high'].values.astype(float)
    daily_low = df['low'].values.astype(float)
    current_price = float(daily_close[-1])
    intraday_high = current_price
    intraday_low = current_price
    data_source = '昨日日线'
    try:
        today = context.current_dt.date()
        minute_df = get_price(
            g.risk_benchmark, start_date=today, end_date=context.current_dt,
            frequency='1m', fields=['close', 'high', 'low'], panel=False, fill_paused=False
        )
        if minute_df is not None and not minute_df.empty:
            minute_close = minute_df['close'].dropna()
            minute_high = minute_df['high'].dropna()
            minute_low = minute_df['low'].dropna()
            if not minute_close.empty:
                current_price = float(minute_close.iloc[-1])
                intraday_high = float(minute_high.max()) if not minute_high.empty else current_price
                intraday_low = float(minute_low.min()) if not minute_low.empty else current_price
                data_source = '当日盘中'
    except Exception:
        pass
    if current_price <= 0:
        try:
            live_price = get_current_data()[g.risk_benchmark].last_price
            if live_price is not None and live_price > 0:
                current_price = float(live_price)
                intraday_high = max(intraday_high, current_price)
                intraday_low = min(intraday_low, current_price)
                data_source = '实时快照'
        except Exception:
            current_price = float(daily_close[-1])
    close_series = np.append(daily_close, current_price)
    high_series = np.append(daily_high, max(intraday_high, current_price))
    low_series = np.append(daily_low, min(intraday_low, current_price))
    recent_high = np.max(high_series[-g.lookback_high_low_days:])
    recent_low = np.min(low_series[-g.lookback_high_low_days:])
    ma = np.mean(close_series[-g.ma_period:])
    current_rsi = calculate_rsi(close_series, period=14)
    previous_rsi = calculate_rsi(daily_close, period=14)
    return {
        'close_series': close_series,
        'high_series': high_series,
        'low_series': low_series,
        'current_price': current_price,
        'recent_high': recent_high,
        'recent_low': recent_low,
        'ma': ma,
        'current_rsi': current_rsi,
        'previous_rsi': previous_rsi,
        'data_source': data_source,
    }


def is_fresh_stop_loss_signal(context):
    signal_date = getattr(g, 'stop_loss_triggered_date', None)
    if signal_date is None:
        return False
    today = context.current_dt.date()
    previous_date = getattr(context, 'previous_date', None)
    if signal_date == today:
        return True
    if previous_date is not None and signal_date == previous_date:
        return True
    g.stop_loss_triggered_today = False
    g.stop_loss_triggered_date = None
    return False


def init_range_bound_status(context):
    if not g.enable_range_bound_mode:
        return
    log.info("【首次运行】初始化震荡期状态...")
    try:
        if context.previous_date is None:
            return
        end_date = context.previous_date
        lookback = max(g.ma_period, g.lookback_high_low_days) + 30
        df = get_price(g.risk_benchmark, end_date=end_date, count=lookback,
                       frequency='daily', fields=['close', 'high', 'low'], panel=False)
        if df is None or len(df) < max(g.ma_period, g.lookback_high_low_days):
            return
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        current_price = close[-1]
        recent_high = np.max(high[-g.lookback_high_low_days:]) if len(close) >= g.lookback_high_low_days else np.max(high)
        ma = np.mean(close[-g.ma_period:])
        bias = (current_price - ma) / ma if ma > 0 else 0
        current_rsi = calculate_rsi(close, period=14)
        should_enter = False
        signals = []
        if g.enable_bias_trigger and bias > g.bias_threshold:
            should_enter = True
            signals.append(f"乖离率{bias:.2%}")
        if g.enable_rsi_trigger and current_rsi is not None and len(close) >= 15:
            prev_rsi = calculate_rsi(close[:-1], period=14)
            if prev_rsi is not None and prev_rsi > g.rsi_overbought and current_rsi < g.rsi_pullback:
                should_enter = True
                signals.append(f"RSI回落{prev_rsi:.1f}->{current_rsi:.1f}")
        if should_enter:
            g.current_filter = '震荡期'
            g.risk_state = '震荡期'
            g.range_bound_start_date = end_date
            log.info(f"【首次运行】初始化进入震荡期: {'; '.join(signals)}")
        else:
            g.current_filter = '正常期'
            g.risk_state = '正常期'
            g.previous_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
            g.previous_rsi = current_rsi
            log.info(f"【首次运行】初始状态: 正常期(拉普拉斯)")
    except Exception as e:
        log.warning(f"【首次运行】震荡期初始化异常: {e}")


def check_and_exit_range_bound_mode(context):
    if not g.enable_range_bound_mode or g.current_filter != '震荡期':
        return
    try:
        benchmark_state = get_risk_benchmark_state(context)
        if benchmark_state is None:
            return
        close = benchmark_state['close_series']
        current_price = benchmark_state['current_price']
        recent_high = benchmark_state['recent_high']
        recent_low = benchmark_state['recent_low']
        current_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        recovery_signals = []
        ma = benchmark_state['ma']
        current_rsi = benchmark_state['current_rsi']
        if g.enable_low_point_rise_trigger and rise_from_low >= g.low_point_rise_threshold:
            recovery_signals.append(f"从低点涨{rise_from_low:.2%}")
        if g.enable_stable_signal_trigger:
            if current_price > ma:
                recovery_signals.append("站上均线")
            if len(close) >= 2 and close[-1] > close[-2]:
                recovery_signals.append("价格回升")
            if g.previous_drawdown is not None and current_drawdown < g.previous_drawdown:
                recovery_signals.append("回撤收窄")
            if current_rsi is not None and g.previous_rsi is not None and current_rsi > g.previous_rsi:
                recovery_signals.append("RSI回升")
            if current_drawdown < g.drawdown_recovery:
                g.stable_days += 1
            else:
                g.stable_days = 0
        g.previous_drawdown = current_drawdown
        g.previous_rsi = current_rsi
        range_bound_days = 0
        if g.range_bound_start_date is not None:
            trade_days = get_trade_days(start_date=g.range_bound_start_date, end_date=context.current_dt.date())
            range_bound_days = len(trade_days) - 1
        low_point_condition = g.enable_low_point_rise_trigger and rise_from_low >= g.low_point_rise_threshold
        stable_condition = False
        if g.enable_stable_signal_trigger:
            stable_condition = current_drawdown < g.drawdown_recovery and len(recovery_signals) >= 2 and g.stable_days >= 2
        force_condition = range_bound_days >= g.max_range_bound_days
        if low_point_condition or stable_condition or force_condition:
            can_switch = True
            if g.last_switch_date is not None:
                trade_days = get_trade_days(start_date=g.last_switch_date, end_date=context.current_dt.date())
                if len(trade_days) - 1 < g.filter_switch_cooldown:
                    can_switch = False
            if can_switch:
                g.current_filter = '正常期'
                g.risk_state = '正常期'
                g.last_switch_date = context.current_dt.date()
                g.range_bound_start_date = None
                g.stable_days = 0
                log.info(f"【退出震荡期】切回拉普拉斯: {'; '.join(recovery_signals)}")
    except Exception as e:
        log.warning(f"【震荡期退出检查】异常: {e}")


def check_and_enter_range_bound_mode(context):
    if not g.enable_range_bound_mode:
        return
    if g.current_filter == '震荡期':
        return
    if g.last_switch_date is not None:
        trade_days = get_trade_days(start_date=g.last_switch_date, end_date=context.current_dt.date())
        if len(trade_days) - 1 < g.filter_switch_cooldown:
            return
    risk_signals = []
    try:
        benchmark_state = get_risk_benchmark_state(context)
        if benchmark_state is not None:
            if g.enable_bias_trigger:
                ma = benchmark_state['ma']
                bias = (benchmark_state['current_price'] - ma) / ma if ma > 0 else 0
                if bias > g.bias_threshold:
                    risk_signals.append(f"乖离率{bias:.2%}")
            if g.enable_rsi_trigger:
                current_rsi = benchmark_state['current_rsi']
                prev_rsi = benchmark_state['previous_rsi']
                if prev_rsi is not None and current_rsi is not None:
                    if prev_rsi > g.rsi_overbought and current_rsi < g.rsi_pullback and current_rsi < prev_rsi:
                        risk_signals.append(f"RSI回落{prev_rsi:.1f}->{current_rsi:.1f}")
    except Exception as e:
        log.warning(f"【震荡期检查】异常: {e}")
    if g.enable_stop_loss_trigger and is_fresh_stop_loss_signal(context):
        risk_signals.append("盈利保护止损")
    if risk_signals:
        g.current_filter = '震荡期'
        g.risk_state = '震荡期'
        g.last_switch_date = context.current_dt.date()
        g.range_bound_start_date = context.current_dt.date()
        g.stable_days = 0
        log.info(f"【进入震荡期】切至高斯: {'; '.join(risk_signals)}")


def check_range_bound(context):
    if not g.enable_range_bound_mode:
        return
    log.info("========== 震荡期检查开始 ==========")
    prev_filter = g.current_filter
    check_and_exit_range_bound_mode(context)
    check_and_enter_range_bound_mode(context)
    log.info(f"震荡期状态: {g.current_filter}")
    if prev_filter != g.current_filter:
        g.rankings_cache = {'date': None, 'data': None}
        g.target_etfs_cache = {'date': None, 'data': None}
    log.info("========== 震荡期检查完成 ==========")


def reset_range_bound_daily(context):
    if g.current_filter == '震荡期' and g.range_bound_start_date is not None:
        trade_days = get_trade_days(start_date=g.range_bound_start_date, end_date=context.current_dt.date())
        g.range_bound_days_count = len(trade_days) - 1


def check_etf_trend_structure(price_series, current_price):
    """均线结构硬过滤：现价>MA10 且 MA5>MA10"""
    if not g.enable_trend_structure_filter:
        return True, ''
    closes = np.asarray(price_series, dtype=float)
    if len(closes) < max(g.trend_ma_period, 10) + 1:
        return False, '历史不足'
    ma10 = float(np.mean(closes[-g.trend_ma_period:]))
    ma5 = float(np.mean(closes[-5:]))
    if g.trend_require_price_above_ma and current_price <= ma10:
        return False, f'现价{current_price:.3f}<=MA{g.trend_ma_period}({ma10:.3f})'
    if g.trend_require_ma5_above_ma10 and ma5 <= ma10:
        return False, f'MA5({ma5:.3f})<=MA10({ma10:.3f})'
    return True, ''


# ==================== 有害卖出冷却 / 震荡期空仓 / 买入得分区间 ====================
def is_range_bound_filter_active(context):
    return g.enable_range_bound_mode and g.current_filter == '震荡期'


def should_fallback_defensive(context):
    """排名为空时是否允许兜底防御ETF。关闭时/震荡期保持空仓。"""
    if not g.enable_defensive_etf:
        return False
    if g.enable_range_bound_cash and is_range_bound_filter_active(context):
        return False
    return True


def mark_harmful_sell(context, security=None):
    """记录有害卖出。走弱期启动QDII守卫冷却；正常期靠 drawdown_selled_today 禁同日买回。"""
    if security:
        g.harmful_sell_last_security = security
    name = get_name(security) if security else ''
    if g.is_a_share_weak:
        g.harmful_sell_last_date = context.current_dt.date()
        log.info(
            f"🛡️ 走弱期有害卖出 {security} {name}，"
            f"{g.harmful_sell_cooldown_weak_days}日内挡QDII追高（商品可轮动）"
        )
    else:
        log.info(f"🛡️ 正常期有害卖出 {security} {name}，仅禁止同日买回该标的")


def get_harmful_sell_cooldown_days(context):
    if g.is_a_share_weak:
        return g.harmful_sell_cooldown_weak_days
    return g.harmful_sell_cooldown_days


def is_harmful_sell_cooldown_active(context):
    if not g.enable_harmful_sell_guard or g.harmful_sell_last_date is None:
        return False
    if not g.is_a_share_weak:
        return False
    cooldown = get_harmful_sell_cooldown_days(context)
    if cooldown <= 0:
        return False
    trade_days = get_trade_days(start_date=g.harmful_sell_last_date, end_date=context.current_dt.date())
    days_since = len(trade_days) - 1
    return days_since < cooldown


def trading_days_since_harmful_sell(context):
    if g.harmful_sell_last_date is None:
        return None
    trade_days = get_trade_days(start_date=g.harmful_sell_last_date, end_date=context.current_dt.date())
    return len(trade_days) - 1


def _daily_returns_series(security, context, lookback):
    hist = attribute_history(security, lookback + 1, '1d', ['close'], skip_paused=True)
    if hist is None or len(hist) < lookback + 1:
        return None
    closes = hist['close'].values.astype(float)
    if np.any(closes <= 0):
        return None
    return np.diff(closes) / closes[:-1]


def calc_return_correlation(sec_a, sec_b, context, lookback=None):
    lookback = lookback or g.correlation_lookback
    ra = _daily_returns_series(sec_a, context, lookback)
    rb = _daily_returns_series(sec_b, context, lookback)
    if ra is None or rb is None or len(ra) != len(rb) or len(ra) < 5:
        return None
    corr = float(np.corrcoef(ra, rb)[0, 1])
    if np.isnan(corr):
        return None
    return corr


def get_weak_qdii_guard_refs(context):
    """走弱期有害卖后：被卖标的 + 当日有害卖集合。"""
    refs = []
    sec = getattr(g, 'harmful_sell_last_security', None)
    if sec and (sec in g.etf_pool or sec == g.defensive_etf):
        refs.append(sec)
    for s in g.drawdown_selled_today:
        if s in g.etf_pool or s == g.defensive_etf:
            refs.append(s)
    return list(dict.fromkeys(refs))


def is_blocked_by_harmful_sell_same_etf(candidate, context):
    """有害卖出冷却期内禁止买回同一只标的（仅挡自身，不挡商品）。"""
    if not g.enable_harmful_sell_guard or not is_harmful_sell_cooldown_active(context):
        return False, None
    ref_sec = getattr(g, 'harmful_sell_last_security', None)
    if ref_sec and candidate == ref_sec:
        return True, ref_sec
    return False, None


def is_blocked_by_weak_overseas_cluster(candidate, context):
    """有害卖出海外代理后，冷却期内禁止买入其他海外ETF。"""
    if not g.enable_weak_qdii_guard or not is_harmful_sell_cooldown_active(context):
        return False, None
    proxy_set = set(getattr(g, 'overseas_proxy_pool', []))
    ref_sec = getattr(g, 'harmful_sell_last_security', None)
    if ref_sec not in proxy_set:
        return False, None
    if is_overseas_qdii(candidate) and candidate != ref_sec:
        return True, ref_sec
    return False, None


def mark_overseas_rotation_sell(context, security=None):
    """走弱期轮动卖出海外 QDII 后，启动短期禁买同簇冷却。"""
    if not g.enable_overseas_rotation_guard or not g.is_a_share_weak:
        return
    if security and not is_overseas_qdii(security):
        return
    g.overseas_rotation_sell_last_date = context.current_dt.date()
    if security:
        g.overseas_rotation_sell_last_security = security
    log.info(
        f"🛡️ 走弱期轮动卖海外 {security} {get_name(security)}，"
        f"{g.overseas_rotation_cooldown_days}日内禁买其他QDII"
    )


def is_overseas_rotation_cooldown_active(context):
    if not g.enable_overseas_rotation_guard or g.overseas_rotation_sell_last_date is None:
        return False
    if not g.is_a_share_weak:
        return False
    cooldown = g.overseas_rotation_cooldown_days
    if cooldown <= 0:
        return False
    trade_days = get_trade_days(
        start_date=g.overseas_rotation_sell_last_date,
        end_date=context.current_dt.date(),
    )
    return len(trade_days) - 1 < cooldown


def is_blocked_by_overseas_rotation_cluster(candidate, context):
    """走弱期轮动卖海外后，冷却期内禁止买入其他海外 QDII。"""
    if not is_overseas_rotation_cooldown_active(context):
        return False, None
    ref_sec = getattr(g, 'overseas_rotation_sell_last_security', None)
    if not ref_sec or not is_overseas_qdii(ref_sec):
        return False, None
    if is_overseas_qdii(candidate) and candidate != ref_sec:
        # 同日 13:09 轮动卖出后，13:10 允许切换至另一只 QDII（避免挡掉正当换仓）
        if g.overseas_rotation_sell_last_date == context.current_dt.date():
            hm = context.current_dt.strftime('%H:%M')
            if '13:05' <= hm <= '13:15':
                return False, None
        return True, ref_sec
    return False, None


def passes_weak_qdii_correlation_guard(candidate, context, refs=None):
    if not g.enable_weak_qdii_guard or not is_harmful_sell_cooldown_active(context):
        return True, None
    refs = refs or get_weak_qdii_guard_refs(context)
    worst = None
    for ref in refs:
        if ref == candidate:
            continue
        corr = calc_return_correlation(candidate, ref, context)
        if corr is None:
            continue
        if corr >= g.correlation_max and (worst is None or corr > worst[1]):
            worst = (ref, corr)
    if worst:
        return False, worst
    return True, None


def resolve_guard_target(context):
    """走弱期有害卖出冷却内的强制目标（cash 模式专用）。"""
    if g.is_a_share_weak and g.harmful_sell_mode_weak == 'cash':
        log.info("🛡️ 走弱期有害卖出冷却中，目标空仓")
        return []
    log.info("🛡️ 有害卖出冷却中，目标空仓")
    return []


def get_harmful_sell_strict_buy_days(context):
    """有害卖出后严买入带持续交易日数 = 冷却天数 + 额外观望日。"""
    return get_harmful_sell_cooldown_days(context) + g.harmful_sell_strict_extra_days


def is_harmful_sell_strict_buy_band_active(context):
    """有害卖出后是否仍处严买入带（冷却期内及恢复轮动后的额外观望日）。"""
    if not g.enable_cooldown_strict_buy_band or g.harmful_sell_last_date is None:
        return False
    trade_days = get_trade_days(start_date=g.harmful_sell_last_date, end_date=context.current_dt.date())
    days_since = len(trade_days) - 1
    return days_since < get_harmful_sell_strict_buy_days(context)


def get_buy_score_band_limits(context=None, etf=None):
    """返回当前生效的买入得分/年化上下限（正常期宽区间，有害卖出后严带）。"""
    max_score = g.buy_max_score
    enable_ann_cap = g.enable_buy_annualized_cap
    max_ann = g.buy_max_annualized
    min_score = g.buy_min_score
    if context is not None and is_harmful_sell_strict_buy_band_active(context):
        max_score = g.buy_max_score_cooldown
        enable_ann_cap = g.enable_buy_annualized_cap_cooldown
        max_ann = g.buy_max_annualized_cooldown
    if (
        context is not None
        and etf
        and g.enable_overseas_weak_commodity_gate
        and g.enable_overseas_regime_switch
        and g.is_overseas_weak
        and etf in g.commodity_etf_pool
    ):
        min_score = max(min_score, g.buy_min_score_overseas_weak)
    return min_score, max_score, enable_ann_cap, max_ann


def passes_buy_score_band(metrics, context=None):
    """买入阶段得分/年化区间（仅影响买，不影响卖）。"""
    score = metrics['score']
    if not g.enable_buy_score_band:
        return score >= g.min_score_threshold
    min_score, max_score, enable_ann_cap, max_ann = get_buy_score_band_limits(
        context, metrics.get('etf')
    )
    if score < min_score:
        log.info(f"🚫 {metrics['etf']} {metrics['etf_name']} 得分{score:.4f} < 买入下限{min_score:.2f}")
        return False
    if score > max_score:
        log.info(f"🚫 {metrics['etf']} {metrics['etf_name']} 得分{score:.4f} > 买入上限{max_score:.2f}")
        return False
    if enable_ann_cap:
        ann = metrics.get('annualized_returns', 0)
        if ann > max_ann:
            log.info(
                f"🚫 {metrics['etf']} {metrics['etf_name']} 年化{ann * 100:.1f}% > "
                f"买入上限{max_ann * 100:.0f}%"
            )
            return False
    return True


def filter_ranked_by_active_pool(ranked, active_pool):
    """仅保留当前有效池内的排名条目。"""
    pool_set = set(active_pool)
    return [m for m in ranked if m['etf'] in pool_set]


def refresh_rankings_for_current_pool(context, ranked):
    """兜底路径：排名含池外标的时，按当前有效池重算排名。"""
    active_pool = set(get_active_etf_pool())
    out_pool = [m['etf'] for m in ranked[:max(g.holdings_num * 3, 5)]
                if m['etf'] not in active_pool]
    if not out_pool:
        return ranked
    log.info(
        f"📊 排名含池外标的{out_pool}，按当前有效池({len(active_pool)}只)重算排名"
    )
    ranked = get_ranked_etfs(context)
    g.rankings_cache = {'date': context.current_dt.date(), 'data': ranked}
    return ranked


def resolve_rotation_targets(context, ranked):
    """统一解析 13:09/13:10 目标ETF（有害卖出冷却 > 轮动 > 防御/震荡期空仓）。"""
    if is_harmful_sell_cooldown_active(context):
        days_since = trading_days_since_harmful_sell(context)
        cooldown = get_harmful_sell_cooldown_days(context)
        if g.harmful_sell_mode_weak == 'cash':
            log.info(f"🛡️ 走弱期有害卖出冷却 {days_since}/{cooldown} 日，全盘空仓")
            return resolve_guard_target(context)
        log.info(
            f"🛡️ 走弱期有害卖出冷却 {days_since}/{cooldown} 日，"
            f"仅挡QDII追高，商品/轮动继续"
        )

    target_etfs = select_target_etfs_from_rankings(context, ranked)
    if not target_etfs and g.enable_overseas_weak_cash and g.is_overseas_weak:
        log.info("💤 海外弱无合格商品标的，目标空仓")
    elif not target_etfs and should_fallback_defensive(context):
        if check_defensive_etf_available(context) and g.defensive_etf not in g.drawdown_selled_today:
            target_etfs = [g.defensive_etf]
            log.info(f"🛡️ 无目标ETF，防御模式：{g.defensive_etf} {get_name(g.defensive_etf)}")
    elif not target_etfs and not g.enable_defensive_etf:
        log.info("💤 无合格标的，防御ETF已关闭，目标空仓")
    elif not target_etfs and g.enable_range_bound_cash and is_range_bound_filter_active(context):
        log.info("💤 震荡期无合格标的，目标空仓")
    return target_etfs


# ==================== 核心计算模块 ====================
def get_cached_rankings(context):
    """获取缓存的ETF排名"""
    today = context.current_dt.date()
    if g.rankings_cache['date'] != today:
        log.info("📊 重新计算ETF排名...")
        ranked = get_ranked_etfs(context)
        g.rankings_cache = {'date': today, 'data': ranked}
    else:
        log.debug("🔍 使用缓存的ETF排名")
    return g.rankings_cache['data']


def get_ranked_etfs(context):
    """计算所有ETF的动量得分（V2.0：根据行情状态动态选择ETF池，V2.2受独立开关影响）"""
    active_pool = get_active_etf_pool()

    etf_metrics = []
    for etf in active_pool:
        tradable, reason = is_etf_tradable(context, etf)
        if not tradable:
            log.debug(f"❌ {etf} {get_name(etf)} 不可交易({reason})，跳过")
            continue

        metrics = calculate_momentum_metrics(context, etf)
        if metrics is not None:
            if g.rank_min_score < metrics['score'] < g.rank_max_score:
                etf_metrics.append(metrics)
            else:
                log.debug(f"❌ {etf} {metrics['etf_name']} 得分{metrics['score']:.2f}超出排名区间，过滤")

    etf_metrics.sort(key=lambda x: x['score'], reverse=True)
    return etf_metrics


def calculate_momentum_metrics(context, etf):
    """计算单只ETF的动量指标（无未来）"""
    try:
        name = get_name(etf)
        lookback = max(g.lookback_days, g.short_lookback_days) + 20
        prices = attribute_history(etf, lookback, '1d', ['close', 'high'])
        if len(prices) < g.lookback_days:
            log.debug(f"🚫 {etf} {name} 历史数据不足{len(prices)}天，跳过")
            return None

        current_price = get_current_data()[etf].last_price
        price_series = np.append(prices["close"].values, current_price)

        # 1. 盈利保护检查
        if check_profit_protection(etf, context):
            log.info(f"🚫 {etf} {name} 触发盈利保护，从排名中排除")
            return None

        # 2. 溢价率过滤
        if g.enable_premium_filter:
            prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]
            premium, _, _ = get_premium_rate(etf, prev_date)
            if premium is not None:
                if premium > g.premium_threshold:
                    log.info(f"🚫 {etf} {name} 溢价率{premium*100:.2f}% > 阈值，排除")
                    return None
            else:
                log.debug(f"🚫 {etf} {name} 无法获取{prev_date}的净值，排除")
                return None

        # 3. 成交量过滤
        if g.enable_volume_check:
            vol_ratio = get_volume_ratio(context, etf)
            if vol_ratio is not None:
                annualized = get_annualized_returns(price_series, g.lookback_days)
                if annualized > g.volume_return_limit:
                    log.info(f"📉 {etf} {name} 成交量放量，过滤")
                    return None

        # 4. 短期动量过滤
        if len(price_series) >= g.short_lookback_days + 1:
            short_return = price_series[-1] / price_series[-(g.short_lookback_days + 1)] - 1
            short_annualized = (1 + short_return) ** (250 / g.short_lookback_days) - 1
        else:
            short_annualized = 0

        if g.use_short_momentum_filter and short_annualized < g.short_momentum_threshold:
            log.debug(f"❌ {etf} {name} 短期动量不足，过滤")
            return None

        # 4b. 均线趋势结构硬过滤
        ok_trend, trend_reason = check_etf_trend_structure(price_series, current_price)
        if not ok_trend:
            log.info(f"🚫 {etf} {name} 趋势结构未通过({trend_reason})，排除")
            return None

        # 5. 长期动量计算
        recent = price_series[-(g.lookback_days + 1):]
        y = np.log(recent)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized_returns = math.exp(slope * 250) - 1

        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0

        if g.enable_r2_filter and r_squared < g.r2_threshold:
            log.info(f"🚫 {etf} {name} R²={r_squared:.3f} < {g.r2_threshold:.2f}，排除")
            return None

        score = annualized_returns * r_squared

        # 6. 近3日跌幅过滤
        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            if min(day1, day2, day3) < g.loss:
                log.info(f"⚠️ {etf} {name} 近3日有单日跌幅超限，排除")
                return None

        # 7. 拉普拉斯/高斯动态滤波（正常期/震荡期）
        if g.enable_range_bound_mode and len(price_series) >= 10:
            try:
                laplace_values = laplace_filter(price_series, s=g.laplace_s_param)
                laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
                passed_laplace = (current_price > laplace_values[-1] and laplace_slope > g.laplace_min_slope)
                g1_val, g2_val = gaussian_filter_last_two(price_series, sigma=g.gaussian_sigma)
                gaussian_slope = g1_val - g2_val
                passed_gaussian = (current_price > g1_val and gaussian_slope > g.gaussian_min_slope)
                if g.current_filter == '正常期':
                    passed_filter = passed_laplace
                    filter_name = '拉普拉斯'
                else:
                    passed_filter = passed_gaussian
                    filter_name = '高斯'
                if not passed_filter:
                    log.info(f"🚫 {etf} {name} 未通过{filter_name}滤波({g.current_filter})，排除")
                    return None
            except Exception as e:
                log.debug(f"{etf} {name} 滤波器异常: {e}")

        return {
            'etf': etf,
            'etf_name': name,
            'annualized_returns': annualized_returns,
            'r_squared': r_squared,
            'score': score,
            'current_price': current_price,
            'short_annualized': short_annualized,
        }

    except Exception as e:
        log.warning(f"计算{etf} {get_name(etf)}时出错: {e}")
        return None


def get_annualized_returns(price_series, lookback_days):
    """计算加权年化收益率（无未来）"""
    recent = price_series[-(lookback_days + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    slope, _ = np.polyfit(x, y, 1, w=weights)
    return math.exp(slope * 250) - 1


def get_volume_ratio(context, security, lookback=None, threshold=None):
    """计算成交量比值（基于分钟线）"""
    lookback = lookback or g.volume_lookback
    threshold = threshold or g.volume_threshold
    try:
        name = get_name(security)
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
        ratio = current_vol / avg_vol if avg_vol > 0 else 0
        if ratio > threshold:
            log.debug(f"❌ {security} {name} 成交量比{ratio:.2f} > {threshold}")
            return ratio
        return None
    except Exception as e:
        log.warning(f"🚨成交量计算失败 {security}: {e}")
        return None


def is_etf_tradable(context, security):
    """
    判断 ETF 当前是否可交易（含盘中临时停牌）。
    聚宽 get_current_data().paused 对「下午临时停牌」常为 False，需结合本时段分钟成交判断。
    返回 (bool, str)：可交易时 (True, '')，不可交易时 (False, 原因)。
    """
    try:
        data = get_current_data()[security]
        if data.paused:
            return False, '全天停牌(paused)'

        price = data.last_price
        if price is None or price <= 0:
            return False, '现价无效'

        now = context.current_dt
        t = now.time()
        session_start = None
        if datetime.time(9, 30) <= t <= datetime.time(11, 30):
            session_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
        elif datetime.time(13, 0) <= t <= datetime.time(15, 0):
            session_start = now.replace(hour=13, minute=0, second=0, microsecond=0)
        else:
            return True, ''

        minutes_elapsed = (now - session_start).total_seconds() / 60.0
        if minutes_elapsed < 5:
            return True, ''

        df = get_price(
            security, start_date=session_start, end_date=now,
            frequency='1m', fields=['volume'], skip_paused=True, fq='pre'
        )
        if df is None or df.empty:
            return False, '本交易时段无分钟行情(可能盘中停牌)'

        recent = df.tail(min(15, len(df)))
        if recent['volume'].sum() == 0:
            return False, '本交易时段近段无成交(可能盘中停牌)'

        return True, ''
    except Exception as e:
        log.warning(f"⚠️ {security} {get_name(security)} 可交易性检查异常: {e}")
        return True, ''


def _to_float(value):
    """聚宽行情字段偶为 str，统一转 float 供回撤比较。"""
    try:
        if value is None:
            return None
        v = float(value)
        if np.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def get_intraday_drawdown_ratio(security, context):
    """测算当日盘中高点→现价的回撤比例；数据不足时返回 None。"""
    try:
        df = get_price(
            security, start_date=context.current_dt.date(), end_date=context.current_dt,
            frequency='1m', fields=['high', 'close'], skip_paused=True, fq='pre'
        )
        if df is None or df.empty:
            return None
        day_high = _to_float(df['high'].max())
        current = _to_float(df['close'].iloc[-1])
        if not day_high or not current or day_high <= 0:
            return None
        return (day_high - current) / day_high
    except Exception:
        return None


def get_prev_trading_close(security, context):
    """前一交易日收盘价（用于持仓跳空回撤）。"""
    try:
        prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]
        df = get_price(
            security, end_date=prev_date, frequency='1d',
            fields=['close'], count=1, fq='pre', skip_paused=True
        )
        if df is None or df.empty:
            return None
        return float(df['close'].iloc[-1])
    except Exception:
        return None


def get_holding_drawdown_detail(security, context):
    """持仓回撤明细：日内高点→现价；可选昨收→现价。买入过滤仍仅用日内。"""
    detail = {}
    idd = get_intraday_drawdown_ratio(security, context)
    if idd is not None:
        detail['日内'] = idd
    if g.enable_holding_prev_close_drawdown:
        prev_close = get_prev_trading_close(security, context)
        try:
            current = get_current_data()[security].last_price
        except Exception:
            current = None
        current = _to_float(current)
        prev_close = _to_float(prev_close)
        if prev_close and current and prev_close > 0 and current > 0:
            detail['昨收'] = (prev_close - current) / prev_close
    return detail


def get_holding_drawdown_ratio(security, context):
    detail = get_holding_drawdown_detail(security, context)
    if not detail:
        return None, detail
    return max(detail.values()), detail


def get_position_unrealized_gain(security, context):
    """持仓相对成本的浮盈比例；无法计算时返回 None。"""
    try:
        pos = context.portfolio.positions[security]
        if pos.total_amount <= 0:
            return None
        cost = _to_float(pos.avg_cost)
        price = _to_float(pos.price)
        if not price:
            try:
                price = _to_float(get_current_data()[security].last_price)
            except Exception:
                price = None
        if not price or not cost or cost <= 0:
            return None
        return (price - cost) / cost
    except Exception:
        return None


def get_holding_drawdown_for_sell(security, context, source='minute'):
    """持仓卖出回撤：盈利仓豁免分钟误杀；盈利仓 13:09 不用昨收跳空。
    返回 (drawdown, detail, threshold)；drawdown/threshold 为 None 表示不触发卖。
    """
    gain = get_position_unrealized_gain(security, context)
    skip_minute = getattr(g, 'holding_profit_skip_minute_pct', 0.10)
    skip_prev = getattr(g, 'holding_profit_skip_prev_close_pct', 0.10)

    if source == 'minute' and gain is not None and gain >= skip_minute:
        return None, {}, None

    detail = get_holding_drawdown_detail(security, context)
    if gain is not None and gain >= skip_prev and '昨收' in detail:
        detail = {k: v for k, v in detail.items() if k != '昨收'}

    if not detail:
        return None, {}, None

    drawdown = max(detail.values())
    threshold = g.intraday_drawdown_threshold
    return drawdown, detail, threshold


def is_intraday_drawdown_active(security, context):
    """与买入守卫同源：当日盘中回撤是否已达阈值。"""
    drawdown = get_intraday_drawdown_ratio(security, context)
    return drawdown is not None and drawdown >= g.intraday_drawdown_threshold


def check_intraday_drawdown_for_buy(security, context):
    """买入前检查：ETF当前是否处于日内显著回撤状态
    返回 True 表示正在回撤（不宜买入），False 表示正常
    """
    return is_intraday_drawdown_active(security, context)


def execute_intraday_drawdown_sell(
    context, security, drawdown, source='日内回撤', detail=None, threshold=None
):
    """日内回撤触发的统一卖出（分钟级 / 13:09 持仓守卫共用）。"""
    name = get_name(security)
    th = threshold if threshold is not None else g.intraday_drawdown_threshold
    detail_str = ''
    if detail:
        detail_str = ' [' + ' '.join(
            f"{k}{v * 100:.2f}%" for k, v in detail.items()
        ) + ']'
    log.info(
        f"⚠️ {source}回撤触发：{security} {name} "
        f"回撤{drawdown * 100:.2f}% > {th * 100:.0f}%"
        f"{detail_str}"
    )
    if smart_order_target_value(security, 0, context):
        log.info(f"🧨 {source}回撤卖出：{security} {name}")
        g.drawdown_selled_today.add(security)
        mark_harmful_sell(context, security)
        if security in g.buy_date:
            del g.buy_date[security]
        return True
    return False


def filter_intraday_drawdown_targets(context, target_etfs):
    """从目标列表剔除回撤标的；已持仓用持仓回撤（含昨收），候选仅用日内。"""
    held = {
        s for s in context.portfolio.positions
        if (s in g.etf_pool or s == g.defensive_etf)
        and context.portfolio.positions[s].total_amount > 0
    }
    filtered = []
    for etf in target_etfs:
        if etf in held:
            drawdown, detail, threshold = get_holding_drawdown_for_sell(
                etf, context, source='slot1309'
            )
        else:
            drawdown = get_intraday_drawdown_ratio(etf, context)
            detail = {'日内': drawdown} if drawdown is not None else {}
            threshold = g.intraday_drawdown_threshold
        if (
            drawdown is not None
            and threshold is not None
            and drawdown >= threshold
        ):
            detail_str = ' '.join(f"{k}={v * 100:.2f}%" for k, v in detail.items())
            log.info(
                f"🌊 {etf} {get_name(etf)} 回撤"
                f"(>{g.intraday_drawdown_threshold * 100:.0f}%)，目标列表剔除 [{detail_str}]"
            )
            continue
        filtered.append(etf)
    return filtered


def passes_buy_candidate_filters(m, context, guard_refs=None):
    """单只 ETF 是否通过买入阶段全部守卫与弱势过滤。"""
    etf = m['etf']
    etf_name = m['etf_name']

    if not passes_buy_score_band(m, context):
        return False

    tradable, reason = is_etf_tradable(context, etf)
    if not tradable:
        log.info(f"🚫 {etf} {etf_name} 不可交易({reason})，买入过滤剔除")
        return False

    if g.enable_profit_protection and check_profit_protection(etf, context):
        log.info(f"🚫 {etf} {etf_name} 触发盈利保护，买入过滤剔除")
        return False

    if etf in g.drawdown_selled_today:
        log.info(f"🚫 {etf} {etf_name} 今日因回撤/盈利保护卖出，买入过滤剔除")
        return False

    blocked_same, ref_same = is_blocked_by_harmful_sell_same_etf(etf, context)
    if blocked_same:
        days_since = trading_days_since_harmful_sell(context)
        cooldown = get_harmful_sell_cooldown_days(context)
        log.info(
            f"🚫 {etf} {etf_name} 有害卖出冷却 {days_since}/{cooldown} 日，"
            f"禁止买回同标的"
        )
        return False

    blocked, ref_sec = is_blocked_by_weak_overseas_cluster(etf, context)
    if blocked:
        log.info(
            f"🚫 {etf} {etf_name} 海外有害簇挡："
            f"近期有害卖出 {ref_sec} {get_name(ref_sec)}"
        )
        return False

    blocked_rot, ref_rot = is_blocked_by_overseas_rotation_cluster(etf, context)
    if blocked_rot:
        log.info(
            f"🚫 {etf} {etf_name} 轮动卖海外挡："
            f"近期轮动卖出 {ref_rot} {get_name(ref_rot)}"
        )
        return False

    ok_corr, corr_info = passes_weak_qdii_correlation_guard(etf, context, guard_refs)
    if not ok_corr:
        ref, corr = corr_info
        log.info(
            f"🚫 {etf} {etf_name} 弱期低相关守卫：与 {ref} {get_name(ref)} "
            f"{g.correlation_lookback}日相关{corr:.2f}≥{g.correlation_max:.2f}"
        )
        return False

    if check_intraday_drawdown_for_buy(etf, context):
        log.info(
            f"🌊 {etf} {etf_name} 当前处于日内回撤状态"
            f"(>{g.intraday_drawdown_threshold*100:.0f}%)，买入过滤剔除"
        )
        return False

    if g.enable_holding_prev_close_drawdown:
        _, detail = get_holding_drawdown_ratio(etf, context)
        prev_dd = detail.get('昨收')
        if prev_dd is not None and prev_dd >= g.intraday_drawdown_threshold:
            log.info(
                f"🌊 {etf} {etf_name} 相对昨收回撤{prev_dd * 100:.2f}%"
                f"(>{g.intraday_drawdown_threshold * 100:.0f}%)，买入过滤剔除"
            )
            return False

    return True


def refilter_cached_buy_targets(context, cached_etfs, ranked):
    """买入前对缓存目标复跑守卫，并过滤当前有效池外的弱势标。"""
    active_pool = set(get_active_etf_pool())
    ranked_map = {m['etf']: m for m in ranked}
    guard_refs = get_weak_qdii_guard_refs(context) if is_harmful_sell_cooldown_active(context) else []
    result = []
    for etf in cached_etfs:
        if etf not in active_pool:
            log.info(f"🚫 {etf} {get_name(etf)} 不在当前有效池(弱势屏蔽)，缓存复检剔除")
            continue
        m = ranked_map.get(etf)
        if m is None:
            log.info(f"🚫 {etf} {get_name(etf)} 不在当日排名，缓存复检剔除")
            continue
        if passes_buy_candidate_filters(m, context, guard_refs):
            result.append(etf)
            if guard_refs is not None:
                guard_refs.append(etf)
    return result, guard_refs


def extend_buy_targets_from_rankings(context, ranked, target_etfs, guard_refs=None):
    """缓存过滤后不足持仓数时，按排名顺延替补（复用相同守卫）。"""
    active_pool = set(get_active_etf_pool())
    existing = set(target_etfs)
    for m in ranked:
        if len(target_etfs) >= g.holdings_num:
            break
        etf = m['etf']
        if etf in existing:
            continue
        if etf not in active_pool:
            continue
        if passes_buy_candidate_filters(m, context, guard_refs):
            target_etfs.append(etf)
            existing.add(etf)
            log.info(f"🔄 缓存目标不可买，顺延替补：{etf} {m['etf_name']}")
            if guard_refs is not None:
                guard_refs.append(etf)
    return target_etfs


def _pick_targets_from_ranked(context, ranked, guard_refs):
    """从已按有效池过滤的排名列表中选出目标 ETF。"""
    target_etfs = []
    for m in ranked:
        if len(target_etfs) >= g.holdings_num:
            break
        if passes_buy_candidate_filters(m, context, guard_refs):
            target_etfs.append(m['etf'])
            if guard_refs is not None:
                guard_refs.append(m['etf'])
    return target_etfs


def select_target_etfs_from_rankings(context, ranked, allow_rerank=True):
    """从排名列表中按统一过滤条件选出目标ETF，最多 holdings_num 个。

    卖出和买入共用此函数，确保两者的目标集合完全一致，
    杜绝「13:09 卖出 → 13:10 买回同一标的」的现象。

    过滤逻辑（优先级从高到低）：
      0. 当前有效池（V3.12.2：池外弱势标直接跳过）
      1. 买入得分区间（passes_buy_score_band）
      2. 可交易性（全天/盘中停牌）
      3. 盈利保护检查（避免卖了又买）
      4. 当日回撤/盈利保护卖出禁止买回（drawdown_selled_today）
      5. 走弱期有害卖后 QDII 簇挡 / 低相关守卫（V3.11）
      6. 走弱期轮动卖海外后 QDII 簇挡（V3.12）
      7. 日内回撤检查（避免"接飞刀"）
    """
    active_pool = get_active_etf_pool()
    pool_ranked = filter_ranked_by_active_pool(ranked, active_pool)
    skipped = len(ranked) - len(pool_ranked)
    if skipped:
        log.info(f"📊 有效池过滤：{skipped}只不在当前池，候选缩至{len(pool_ranked)}只")

    guard_refs = get_weak_qdii_guard_refs(context) if is_harmful_sell_cooldown_active(context) else []
    target_etfs = _pick_targets_from_ranked(context, pool_ranked, guard_refs)

    if not target_etfs and allow_rerank and skipped:
        log.info("📊 池过滤后无合格标的，按当前有效池重算排名后再选")
        fresh_ranked = get_ranked_etfs(context)
        g.rankings_cache = {'date': context.current_dt.date(), 'data': fresh_ranked}
        return select_target_etfs_from_rankings(context, fresh_ranked, allow_rerank=False)

    return target_etfs


# ==================== 卖出模块 ====================
@time_monitor(func_name="卖出操作")
def etf_sell_trade(context):
    """卖出不符合条件的持仓"""
    log.info("📤 ========== 卖出操作开始 ==========")

    refresh_regime_for_trade(context)
    ranked = get_cached_rankings(context)
    target_etfs = resolve_rotation_targets(context, ranked)
    target_etfs = filter_intraday_drawdown_targets(context, target_etfs)

    # 缓存最终目标列表，供 13:10 买入复用（避免时间敏感过滤在 1 分钟内变化）
    g.target_etfs_cache = {'date': context.current_dt.date(), 'data': list(target_etfs)}

    target_set = set(target_etfs)

    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount <= 0:
            continue

        drawdown, detail, threshold = get_holding_drawdown_for_sell(
            sec, context, source='slot1309'
        )
        in_drawdown = (
            drawdown is not None
            and threshold is not None
            and drawdown >= threshold
        )
        if detail and drawdown is not None and drawdown >= 0.01:
            log.info(
                f"📉 持仓回撤检视 {sec} {get_name(sec)}: "
                + ' '.join(f"{k}={v * 100:.2f}%" for k, v in detail.items())
            )

        if in_drawdown:
            cost = pos.avg_cost
            buy_date = g.buy_date.get(sec)
            hold_days = (context.current_dt.date() - buy_date).days if buy_date else 0
            if execute_intraday_drawdown_sell(
                context, sec, drawdown, source='13:09持仓',
                detail=detail, threshold=threshold
            ):
                g.trade_log['sell_records'].append({
                    'time': get_real_time(),
                    'code': sec,
                    'name': get_name(sec),
                    'cost': cost,
                    'price': get_current_data()[sec].last_price,
                    'hold_days': hold_days
                })
            continue

        if sec not in target_set:
            cost = pos.avg_cost
            buy_date = g.buy_date.get(sec)
            hold_days = (context.current_dt.date() - buy_date).days if buy_date else 0
            if smart_order_target_value(sec, 0, context):
                log.info(f"📤 卖出持仓：{sec} {get_name(sec)}")
                if is_overseas_qdii(sec):
                    mark_overseas_rotation_sell(context, sec)
                g.trade_log['sell_records'].append({
                    'time': get_real_time(),
                    'code': sec,
                    'name': get_name(sec),
                    'cost': cost,
                    'price': get_current_data()[sec].last_price,
                    'hold_days': hold_days
                })
                if sec in g.buy_date:
                    del g.buy_date[sec]

    log.info("📤 ========== 卖出操作完成 ==========")


# ==================== 买入模块 ====================
@time_monitor(func_name="买入操作")
def etf_buy_trade(context):
    """买入符合条件的ETF"""
    log.info("📥 ========== 买入操作开始 ==========")

    refresh_regime_for_trade(context)
    ranked = get_cached_rankings(context)
    log.info("📊 === ETF排名前5 ===")
    for i, m in enumerate(ranked[:5]):
        annual_pct = m['annualized_returns'] * 100
        r_sq = m['r_squared']
        log.info(f"   排名{i+1}: {m['etf']} {m['etf_name']} 得分{m['score']:.4f} 年化{annual_pct:.2f}%")

    today = context.current_dt.date()
    if is_harmful_sell_cooldown_active(context):
        target_etfs = resolve_rotation_targets(context, ranked)
    elif g.target_etfs_cache['date'] == today and g.target_etfs_cache['data'] is not None:
        raw_targets = list(g.target_etfs_cache['data'])
        log.info(f"📋 复用13:09目标ETF缓存：{raw_targets}")
        target_etfs, guard_refs = refilter_cached_buy_targets(context, raw_targets, ranked)
        if len(target_etfs) < g.holdings_num:
            target_etfs = extend_buy_targets_from_rankings(
                context, ranked, target_etfs, guard_refs
            )
        if not target_etfs:
            log.info("📋 缓存目标经守卫复检后为空，回退 resolve_rotation_targets（同步有效池）")
            ranked = refresh_rankings_for_current_pool(context, ranked)
            target_etfs = resolve_rotation_targets(context, ranked)
    else:
        target_etfs = resolve_rotation_targets(context, ranked)

    if not target_etfs:
        log.info("💤 无目标ETF，保持空仓")
        return

    if target_etfs:
        for i, etf in enumerate(target_etfs):
            m = next((x for x in ranked if x['etf'] == etf), None)
            if m:
                log.info(f"🎯 目标ETF {i+1}: {etf} {m['etf_name']} 得分{m['score']:.4f}")
    else:
        log.info("💤 无目标ETF，保持空仓")
        return

    # 检查是否有持仓需要先卖出
    current_etf_pos = [s for s in context.portfolio.positions if s in g.etf_pool or s == g.defensive_etf]
    to_sell = [s for s in current_etf_pos if s not in target_etfs]
    if to_sell:
        log.info(f"⏳ 尚有持仓需要卖出：{[get_name(s) for s in to_sell]}，等待卖出完成")
        return

    # 等权分配
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

    log.info("📥 ========== 买入操作完成 ==========")


# ==================== 辅助函数 ====================
def get_name(security):
    try:
        return get_current_data()[security].name
    except:
        return "未知"


def check_defensive_etf_available(context):
    etf = g.defensive_etf
    tradable, _ = is_etf_tradable(context, etf)
    if not tradable:
        return False
    data = get_current_data()
    if data[etf].last_price >= data[etf].high_limit:
        return False
    if data[etf].last_price <= data[etf].low_limit:
        return False
    return True


def smart_order_target_value(security, target_value, context):
    data = get_current_data()
    name = get_name(security)

    tradable, reason = is_etf_tradable(context, security)
    if not tradable:
        log.info(f"❌ {security} {name} 不可交易({reason})，跳过下单")
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
            log.info(f"🔒 {security} {name} 涨停，跳过买入")
            return False
    elif diff < 0:
        if data[security].last_price <= data[security].low_limit:
            log.info(f"🔒 {security} {name} 跌停，跳过卖出")
            return False

    trade_val = abs(diff) * price
    if 0 < trade_val < g.min_money:
        log.info(f"💰 {security} {name} 交易金额太小，跳过")
        return False

    if diff < 0:
        closeable = cur_pos.closeable_amount if cur_pos else 0
        if closeable == 0:
            return False
        diff = -min(abs(diff), closeable)

    if diff != 0:
        order_result = order(security, diff)
        if order_result:
            log.info(f"{'📥 买入' if diff>0 else '📤 卖出'} {security} {name} 数量{abs(diff)} 价格{price:.3f}")
            if diff > 0:
                g.buy_date[security] = context.current_dt.date()
            return True
        else:
            log.warning(f"⚠️ 下单失败: {security} {name}")
            return False
    return False


# ==================== 盘后总结报告 ====================
def daily_summary_report(context):
    """盘后总结"""
    current_date = context.current_dt.strftime('%Y-%m-%d')
    total_value = context.portfolio.total_value
    cash = context.portfolio.cash
    positions_value = total_value - cash

    log.info("📋 ========== 策略运行日报 ==========")
    log.info(f"📅 日期: {current_date}")

    # 市场状态（含独立开关状态）
    if g.enable_regime_switch:
        status = "🔴走弱期" if g.is_a_share_weak else "🟢正常期"
        avoid_status = "回避A股" if (g.is_a_share_weak and g.enable_avoid_a_share) else ("不回避A股" if g.is_a_share_weak else "正常交易")
        drawdown_status = "🛡️启用" if (g.is_a_share_weak and g.enable_intraday_drawdown) else ("⭕关闭" if (g.is_a_share_weak and not g.enable_intraday_drawdown) else "⭕关闭")
        log.info(f"🌍 市场状态：{status} | {avoid_status} 计数:{g.weak_period_counter}/{g.weak_period_max_days}")
        log.info(f"🛡️ 分钟级回撤：{drawdown_status}（阈值{g.intraday_drawdown_threshold*100:.0f}%）")
        filt = "拉普拉斯·正常期" if g.current_filter == "正常期" else "高斯·震荡期"
        log.info("📐 滤波器：%s | R2过滤：%s | 均线结构：%s" % (filt, "开" if g.enable_r2_filter else "关", "开" if g.enable_trend_structure_filter else "关"))
    else:
        log.info("🌍 行情判断未启用，始终全市场交易")

    if g.enable_overseas_regime_switch:
        ostatus = "🔴海外弱" if g.is_overseas_weak else "🟢海外正常"
        log.info(f"🌐 海外状态：{ostatus} 计数:{g.overseas_weak_counter}/{g.overseas_weak_max_days}")

    if g.enable_overseas_rotation_guard and g.overseas_rotation_sell_last_date is not None:
        if is_overseas_rotation_cooldown_active(context):
            trade_days = get_trade_days(
                start_date=g.overseas_rotation_sell_last_date,
                end_date=context.current_dt.date(),
            )
            days_since = len(trade_days) - 1
            log.info(
                f"🛡️ 轮动卖海外冷却：激活 {days_since}/{g.overseas_rotation_cooldown_days}日 "
                f"上次={g.overseas_rotation_sell_last_date}"
            )

    if g.enable_harmful_sell_guard and g.harmful_sell_last_date is not None:
        if is_harmful_sell_cooldown_active(context):
            trade_days = get_trade_days(start_date=g.harmful_sell_last_date, end_date=context.current_dt.date())
            days_since = len(trade_days) - 1
            cooldown = get_harmful_sell_cooldown_days(context)
            log.info(f"🛡️ 走弱期有害卖出冷却：激活 {days_since}/{cooldown}日 上次={g.harmful_sell_last_date}")
        else:
            log.info(f"🛡️ 有害卖出冷却：已过期 上次={g.harmful_sell_last_date}")
    else:
        log.info("🛡️ 有害卖出冷却：无记录")

    # 独立开关汇总
    avoid_switch_status = "ON（走弱期回避A股）" if g.enable_avoid_a_share else "OFF（走弱期不回避A股）"
    drawdown_switch_status = "ON（走弱期自动启用）" if g.enable_intraday_drawdown else "OFF（不触发）"
    log.info(f"⚙️ 独立开关：A股回避={avoid_switch_status} | 分钟回撤={drawdown_switch_status}")

    # 今日卖出
    sell_records = g.trade_log.get('sell_records', [])
    log.info(f"📤 今日卖出：{len(sell_records)}只")
    for r in sell_records:
        cost = r.get('cost', 0)
        sell_price = r.get('price', 0)
        profit_pct = (sell_price / cost - 1) * 100 if cost > 0 else 0
        hold_days = r.get('hold_days', 0)
        log.info(f"   {r['code']} {r['name']} | 成本:{cost:.3f} | 卖出:{sell_price:.3f} | 收益:{profit_pct:+.2f}% | 持有{hold_days}天")

    # 最终持仓
    pos_list = []
    for sec, pos in context.portfolio.positions.items():
        if pos.total_amount == 0:
            continue
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos_list.append(sec)
    log.info(f"📊 最终持仓：{len(pos_list)}只")
    for sec, pos in context.portfolio.positions.items():
        if pos.total_amount == 0:
            continue
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        current_price = get_current_data()[sec].last_price
        cost = pos.avg_cost
        profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0
        buy_date = g.buy_date.get(sec)
        hold_days = (context.current_dt.date() - buy_date).days if buy_date else 0
        log.info(f"   {sec} {get_name(sec)} | 成本:{cost:.3f} | 当前:{current_price:.3f} | 收益:{profit_pct:+.2f}% | 持有{hold_days}天")

    # 账户汇总
    returns = (total_value - context.portfolio.starting_cash) / context.portfolio.starting_cash * 100
    log.info(f"💰 总资产：{total_value:.2f} | 可用：{cash:.2f} | 市值：{positions_value:.2f} | 累计收益：{returns:.2f}%")
    log.info("📋🐂🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩报告结束 🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🐂")
    log.info("")

