# 鍏嬮殕鑷鑱氬芥枃绔狅細https://www.joinquant.com/post/70329
# 鏍囬橈細60鍊嶄竷鏄熼珮鐓+楂樻柉+鎷夋櫘鎷夋柉
# 浣滆咃細king088

# 鍏嬮殕鑷鑱氬芥枃绔狅細https://www.joinquant.com/post/69163
# 鏍囬橈細銆愮瓥鐣ヤ紭鍖栥慐TF杞鍔ㄧ瓥鐣ヤ紭鍖-V1.7.2
# 浣滆咃細鏅ㄦ洣閲忓寲

import numpy as np
import math
import datetime
import pandas as pd
from jqdata import *

# ==================== 鍒濆嬪寲妯″潡 ====================
def initialize(context):
    """
    鍒濆嬪寲鍑芥暟锛氳剧疆浜ゆ槗鍙傛暟銆丒TF姹犮佹牳蹇冨弬鏁般佽皟搴︿换鍔
    """
    # ---------- 浜ゆ槗璁剧疆 ----------
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0001,
            close_commission=0.0001,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    set_benchmark("161226.XSHE")

    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    log.info("========== 绛栫暐鍒濆嬪寲寮濮 ==========")

    # ---------- ETF姹 ----------
    g.etf_pool_bak = [
        "518880.XSHG",   # 榛勯噾ETF
        "159985.XSHE",   # 璞嗙矔ETF
        "501018.XSHG",   # 鍗楁柟鍘熸补
        "161226.XSHE",   # 鐧介摱LOF
        "513100.XSHG",   # 绾虫寚ETF
        "159915.XSHE",   # 鍒涗笟鏉縀TF
        "511220.XSHG",   # 鍩庢姇鍊篍TF
    ]
        # 澶ETF姹
    g.etf_pool  = [
        # 澶у畻鍟嗗搧ETF
        "518880.XSHG",  # 榛勯噾ETF
        "159980.XSHE",  # 鏈夎壊ETF锛堣窡韪鏈夎壊閲戝睘鏉垮潡锛
        "159985.XSHE",  # 璞嗙矔ETF锛堣窡韪璞嗙矔鏈熻揣浠锋牸锛
        "501018.XSHG",  # 鍗楁柟鍘熸补锛堟姇璧勫師娌圭浉鍏宠祫浜э級
        '161226.XSHE',  # 鐧介摱LOF
        "159981.XSHE",  # 鑳芥簮鍖栧伐ETF
        # 鍥介檯ETF
        "513100.XSHG",  # 绾虫寚ETF
        "159509.XSHE",  # 绾虫寚绉戞妧ETF
        "513290.XSHG",  # 绾虫寚鐢熺墿ETF
        "513500.XSHG",  # 鏍囨櫘500ETF
        "159529.XSHE",  # 鏍囨櫘娑堣垂
        "513400.XSHG",  # 閬撶惣鏂疎TF
        "513520.XSHG",  # 鏃ョ粡225ETF
        "513030.XSHG",  # 寰峰浗30ETF
        "513080.XSHG",  # 娉曞浗ETF
        "513310.XSHG",  # 涓闊╁崐瀵间綋ETF
        "513730.XSHG",  # 涓滃崡浜欵TF
        # 棣欐腐ETF
        "159792.XSHE",  # 娓鑲′簰鑱擡TF
        "513130.XSHG",  # 鎭掔敓绉戞妧
        "513050.XSHG",  # 涓姒備簰鑱旂綉ETF
        "159920.XSHE",  # 鎭掔敓ETF
        "513690.XSHG",  # 娓鑲＄孩鍒
        # 鎸囨暟ETF
        "510300.XSHG",  # 娌娣300ETF
        "510500.XSHG",  # 涓璇500ETF
        "510050.XSHG",  # 涓婅瘉50ETF
        "510210.XSHG",  # 涓婅瘉ETF
        "159915.XSHE",  # 鍒涗笟鏉縀TF
        "588080.XSHG",  # 绉戝垱50
        "512100.XSHG",  # 涓璇1000ETF
        "563360.XSHG",  # A500-ETF
        "563300.XSHG",  # 涓璇2000ETF
        # 椋庢牸ETF
        "512890.XSHG",  # 绾㈠埄浣庢尝ETF
        "159967.XSHE",  # 鍒涗笟鏉挎垚闀縀TF
        "512040.XSHG",  # 浠峰糆TF
        "159201.XSHE",  # 鑷鐢辩幇閲戞祦ETF
        # 鍊哄埜ETF
        "511380.XSHG",  # 鍙杞鍊篍TF
        "511010.XSHG",  # 鍥藉篍TF
        "511220.XSHG",  # 鍩庢姇鍊篍TF
    ]
    

    # ---------- 鏍稿績鍙傛暟 ----------
    g.lookback_days = 25               # 鍔ㄩ噺璁＄畻鍛ㄦ湡
    g.holdings_num = 1                 # 鍊欓夋暟閲
    g.defensive_etf = "511880.XSHG"    # 闃插尽ETF锛堣揣甯佸熀閲戯級
    g.min_money = 5000                 # 鏈灏忎氦鏄撻噾棰

    # ---------- 鐩堝埄淇濇姢鍙傛暟 ----------
    g.enable_profit_protection = True                      # 鐩堝埄淇濇姢寮鍏
    g.profit_protection_lookback = 1                       # 鐩堝埄淇濇姢鍥炵湅鍛ㄦ湡锛堝ぉ锛
    g.profit_protection_threshold = 0.05                   # 鐩堝埄淇濇姢鍥炴挙闃堝硷紙5%锛
    g.profit_protection_check_times = ['11:00']            # 鐩堝埄淇濇姢妫鏌ユ椂闂寸偣锛堝彲娣诲姞澶氫釜锛屽俒'09:45','11:00','13:30']锛

    g.loss = 0.97                      # 杩3鏃ュ崟鏃ヨ穼骞呴槇鍊硷紙鎺掗櫎锛

    g.min_score_threshold = 0          # 鏈浣庡緱鍒
    g.max_score_threshold = 100.0      # 鏈楂樺緱鍒

    # ---------- 鎴愪氦閲忚繃婊 ----------
    g.enable_volume_check = True
    g.volume_lookback = 5
    g.volume_threshold = 2
    g.volume_return_limit = 1          # 骞村寲鏀剁泭>100%鏃跺惎鐢ㄦ斁閲忚繃婊

    # ---------- 鐭鏈熷姩閲忚繃婊 ----------
    g.use_short_momentum_filter = True
    g.short_lookback_days = 10
    g.short_momentum_threshold = 0.0

    # ---------- 婧浠风巼杩囨护 ----------
    g.enable_premium_filter = True      # 鏄鍚﹀惎鐢ㄦ孩浠风巼杩囨护
    g.premium_threshold = 0.20          # 婧浠风巼闃堝硷紙20%锛

    # ---------- 杩愯屾椂鍙橀噺 ----------
    g.rankings_cache = {'date': None, 'data': None}   # 鎺掑悕缂撳瓨

    # ---------- 闇囪崱鏈熷弬鏁 ----------
    g.enable_range_bound_mode = True      # 闇囪崱鏈熸ā寮忓紑鍏
    g.current_filter = '姝ｅ父鏈'           # 褰撳墠婊ゆ尝鍣锛'姝ｅ父鏈'=鎷夋櫘鎷夋柉, '闇囪崱鏈'=楂樻柉
    g.risk_state = '姝ｅ父鏈'               # 椋庨櫓鐘舵
    g.lookback_high_low_days = 20         # 杩慛涓浜ゆ槗鏃ラ珮浣庣偣鍥炵湅
    g.risk_benchmark = '510300.XSHG'      # 椋庨櫓鍩哄噯ETF
    # 婊ゆ尝鍣ㄥ弬鏁帮紙姝ｅ父鏈熸媺鏅鎷夋柉锛岄渿鑽℃湡楂樻柉锛
    g.laplace_s_param = 0.05
    g.laplace_min_slope = 0.001
    g.gaussian_sigma = 1.2
    g.gaussian_min_slope = 0.002
    # 杩涘叆闇囪崱鏈熸潯浠
    g.enable_bias_trigger = True          # 涔栫荤巼杩囧ぇ瑙﹀彂
    g.bias_threshold = 0.10               # 涔栫荤巼闃堝硷紙8%锛
    g.ma_period = 20                      # 鍧囩嚎鍛ㄦ湡
    g.enable_rsi_trigger = True           # RSI瓒呬拱鍥炶惤瑙﹀彂
    g.rsi_overbought = 75
    g.rsi_pullback = 60
    g.previous_rsi = None
    g.enable_stop_loss_trigger = False    # 鐩堝埄淇濇姢瑙﹀彂姝㈡崯淇″彿寮鍏
    g.stop_loss_triggered_today = False
    g.stop_loss_triggered_date = None
    # 閫鍑洪渿鑽℃湡鏉′欢
    g.enable_low_point_rise_trigger = True
    g.low_point_rise_threshold = 0.03     # 浠庝綆鐐逛笂娑4%閫鍑
    g.enable_stable_signal_trigger = True
    g.drawdown_recovery = 0.03            # 鍥炴挙鏀剁獎闃堝
    g.max_range_bound_days = 15           # 鏈澶ч渿鑽℃湡澶╂暟
    g.stable_days = 0
    # 闇囪崱鏈熸帶鍒
    g.filter_switch_cooldown = 2          # 鍒囨崲鍐峰嵈鏈燂紙浜ゆ槗鏃ワ級
    g.last_switch_date = None
    g.range_bound_start_date = None
    g.range_bound_days_count = 0
    g.previous_drawdown = None

    # ---------- 浜ゆ槗璋冨害 ----------
    run_daily(check_positions, time='09:10')
    run_daily(etf_sell_trade, time='13:10')
    run_daily(etf_buy_trade, time='13:11')

    # 鍔ㄦ佹敞鍐岀泩鍒╀繚鎶ゆ鏌ユ椂闂寸偣
    for check_time in g.profit_protection_check_times:
        run_daily(profit_protection_check, time=check_time)
        log.info(f"宸叉敞鍐岀泩鍒╀繚鎶ゆ鏌ユ椂闂达細{check_time}")

    # 闇囪崱鏈熸鏌ワ紙鍦ㄥ崠鍑哄墠鎵ц岋級涓庢敹鐩橀噸缃
    run_daily(check_range_bound, time='13:55')
    run_daily(reset_range_bound_daily, time='15:10')

    log.info(f"绛栫暐鍒濆嬪寲瀹屾垚锛欵TF姹爗len(g.etf_pool)}鍙锛屽姩閲忓懆鏈焮g.lookback_days}澶╋紝鎸佷粨{g.holdings_num}鍙")
    log.info(f"鐩堝埄淇濇姢寮鍏筹細{'寮鍚' if g.enable_profit_protection else '鍏抽棴'}锛屽洖鐪嬪懆鏈焮g.profit_protection_lookback}澶╋紝鍥炴挙闃堝納g.profit_protection_threshold*100:.0f}%")
    if g.enable_premium_filter:
        log.info(f"婧浠风巼杩囨护宸插惎鐢锛岄槇鍊硷細{g.premium_threshold*100:.0f}%")
    else:
        log.info("婧浠风巼杩囨护鏈鍚鐢")
    log.info(f"闇囪崱鏈熸ā寮忥細{'寮鍚' if g.enable_range_bound_mode else '鍏抽棴'}锛屾ｅ父鏈=鎷夋櫘鎷夋柉婊ゆ尝鍣锛岄渿鑽℃湡=楂樻柉婊ゆ尝鍣")

    # 棣栨¤繍琛屾椂锛屾牴鎹鍘嗗彶鏁版嵁鍒ゆ柇褰撳墠鏄鍚﹀勪簬闇囪崱鏈
    init_range_bound_status(context)
    log.info("========== 绛栫暐鍒濆嬪寲瀹屾垚 ==========")


# ==================== 鐩堝埄淇濇姢鐙绔嬫鏌ュ嚱鏁 ====================
def profit_protection_check(context):
    """
    鐙绔嬫墽琛岀殑鐩堝埄淇濇姢妫鏌ュ嚱鏁
    閬嶅巻鎵鏈夋寔浠擄紝鑻ヨЕ鍙戠泩鍒╀繚鎶ゅ垯鍗栧嚭
    """
    if not g.enable_profit_protection:
        log.debug("鐩堝埄淇濇姢妯″潡宸插叧闂锛岃烦杩囨鏌")
        return

    log.info("========== 鐩堝埄淇濇姢鐙绔嬫鏌ュ紑濮 ==========")
    for sec in list(context.portfolio.positions.keys()):
        # 鍙澶勭悊ETF姹犱腑鐨勬爣鐨勫拰闃插尽ETF
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            if check_profit_protection(sec, context):
                if smart_order_target_value(sec, 0, context):
                    log.info(f"馃洝锔 鐩堝埄淇濇姢鍗栧嚭锛堢嫭绔嬫鏌ワ級锛歿sec} {get_name(sec)}")
                    # 瑙﹀彂姝㈡崯淇″彿锛岀敤浜庨渿鑽℃湡杩涘叆鍒ゆ柇
                    if getattr(g, 'enable_stop_loss_trigger', False):
                        g.stop_loss_triggered_today = True
                        g.stop_loss_triggered_date = context.current_dt.date()
                        log.info("銆愮泩鍒╀繚鎶よЕ鍙戙戣板綍姝㈡崯淇″彿锛屽皢鍦ㄩ渿鑽℃湡妫鏌ユ椂浣跨敤")
    log.info("========== 鐩堝埄淇濇姢鐙绔嬫鏌ュ畬鎴 ==========")


# ==================== 鐩堝埄淇濇姢妫鏌ュ嚱鏁帮紙鏍稿績閫昏緫锛 ====================
def check_profit_protection(security, context, lookback=None, threshold=None):
    """
    妫鏌ユ槸鍚﹁Е鍙戠泩鍒╀繚鎶わ紙浠庢渶杩慛鏃ユ渶楂樼偣鍥炴挙瓒呰繃闃堝硷級
    鍙傛暟:
        security: ETF浠ｇ爜
        context: 涓婁笅鏂
        lookback: 鍥炵湅澶╂暟锛岄粯璁g.profit_protection_lookback
        threshold: 鍥炴挙闃堝硷紝榛樿g.profit_protection_threshold
    杩斿洖:
        bool: True琛ㄧず搴旇Е鍙戠泩鍒╀繚鎶わ紙鍗栧嚭/鎺掗櫎锛夛紝False琛ㄧず瀹夊叏
    """
    # 鑻ュ紑鍏冲叧闂锛岀洿鎺ヨ繑鍥炲畨鍏锛堢嫭绔嬫鏌ュ嚱鏁板凡鍦ㄥ栧眰鍒ゆ柇锛屼絾淇濈暀姝ゅ垽鏂浠ラ槻鐩存帴璋冪敤锛
    if not g.enable_profit_protection:
        return False

    lookback = lookback or g.profit_protection_lookback
    threshold = threshold or g.profit_protection_threshold

    # 鑾峰彇鏈杩慛鏃ョ殑鏈楂樹环锛堜笉鍖呮嫭褰撳ぉ锛
    hist = attribute_history(security, lookback, '1d', ['high'])
    if hist.empty or len(hist) < lookback:
        log.debug(f"{security} {get_name(security)} 鍘嗗彶鏁版嵁涓嶈冻{lookback}澶╋紝鏃犳硶妫鏌ョ泩鍒╀繚鎶")
        return False

    max_high = hist['high'].max()
    current_price = get_current_data()[security].last_price

    if current_price <= max_high * (1 - threshold):
        log.info(f"馃敾 {security} {get_name(security)} 瑙﹀彂鐩堝埄淇濇姢锛氬綋鍓嶄环{current_price:.3f}锛屾渶杩憑lookback}鏃ユ渶楂榹max_high:.3f}锛屽洖鎾{(1 - current_price/max_high)*100:.2f}% > {threshold*100:.0f}%")
        return True
    else:
        return False


# ==================== 婧浠风巼鑾峰彇鍑芥暟 ====================
def get_premium_rate(code, date, max_back_days=5):
    """
    鑾峰彇鎸囧畾鏃ユ湡鐨勬孩浠风巼锛岃嫢褰撳ぉ鏃犲噣鍊煎垯鍚戝墠鎼滅储鏈澶歮ax_back_days涓浜ゆ槗鏃
    鍙傛暟:
        code: 鍩洪噾浠ｇ爜
        date: 鏃ユ湡锛宒atetime.date 瀵硅薄
        max_back_days: 鏈澶у洖閫澶╂暟
    杩斿洖:
        premium_rate: 婧浠风巼锛堝皬鏁板舰寮忥級锛孨one 琛ㄧず鑾峰彇澶辫触
        price: 鍦哄唴浜ゆ槗浠锋牸
        net_value: 鍩洪噾鍑鍊
    """
    # 鑾峰彇鍦哄唴浜ゆ槗浠锋牸锛堢粰瀹氭棩鏈燂級
    price_data = get_price(
        code,
        start_date=date,
        end_date=date,
        frequency='daily',
        fields=['close']
    )
    if price_data.empty:
        log.debug(f"{date} {code} 鏃犱氦鏄撲环鏍兼暟鎹")
        return None, None, None
    price = price_data['close'].iloc[0]

    # 鑾峰彇鍑鍊硷紝鍏堝皾璇曟寚瀹氭棩鏈燂紝鑻ュけ璐ュ垯鍚戝墠鎼滅储浜ゆ槗鏃
    net_value = None
    used_date = date
    # 鑾峰彇浠巇ate寰鍓峬ax_back_days涓浜ゆ槗鏃ョ殑鍒楄〃锛堟墿澶ц寖鍥寸‘淇濆寘鍚瓒冲熶氦鏄撴棩锛
    start_date = date - datetime.timedelta(days=max_back_days*2)
    trade_days = get_trade_days(start_date=start_date, end_date=date)
    # 杞鎹涓 Python date 瀵硅薄
    trade_days = [pd.to_datetime(d).date() for d in trade_days]
    # 鍊掑簭鎼滅储锛屼粠date寮濮嬪悜鍓
    for dt in reversed(trade_days):
        if dt > date:  # 蹇界暐澶т簬date鐨勬棩鏈
            continue
        # 灏濊瘯鑾峰彇鍑鍊肩殑涓ょ嶆柟寮
        net_data = get_extras('unit_net_value', code, start_date=dt, end_date=dt, df=True)
        if not net_data.empty and not pd.isna(net_data[code].iloc[0]):
            net_value = net_data[code].iloc[0]
            used_date = dt
            break
        # 澶囩敤鏂规硶
        try:
            q = query(finance.FUND_NET_VALUE).filter(
                finance.FUND_NET_VALUE.code == code,
                finance.FUND_NET_VALUE.day == dt
            )
            net_df = finance.run_query(q)
            if not net_df.empty:
                net_value = net_df['net_value'].iloc[0]
                used_date = dt
                break
        except:
            continue

    if net_value is None:
        log.debug(f"{code} 鍦▄date}鍙婂墠{max_back_days}涓浜ゆ槗鏃ュ潎鏃犲噣鍊兼暟鎹")
        return None, None, None

    premium_rate = (price - net_value) / net_value
    if used_date != date:
        log.debug(f"{code} 浣跨敤{used_date}鐨勫噣鍊納net_value:.4f}浠ｆ浛{date}鐨勫噣鍊艰＄畻婧浠风巼")
    return premium_rate, price, net_value


# ==================== 闇囪崱鏈熸満鍒 ====================
def calculate_rsi(close, period=14):
    """璁＄畻RSI鍊"""
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
        rsi = 100 - (100 / (1 + rs))
        return rsi
    except:
        return None


def laplace_filter(price, s=0.05):
    """鎷夋櫘鎷夋柉婊ゆ尝鍣锛堟ｅ父鏈熶娇鐢锛"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price, sigma=1.2):
    """浠呰＄畻楂樻柉婊ゆ尝鏈鍚庝袱涓鐐癸紙闇囪崱鏈熶娇鐢锛屾晥鐜囦紭鍖栵級"""
    n = len(price)
    if n < 2:
        return 0, 0
    idx_1 = np.arange(n)
    weights_1 = np.exp(-((idx_1+1)**2) / (2 * sigma**2))[::-1]
    weights_1 /= np.sum(weights_1)
    g1 = np.sum(price * weights_1)
    price_2 = price[:-1]
    idx_2 = np.arange(n-1)
    weights_2 = np.exp(-((idx_2+1)**2) / (2 * sigma**2))[::-1]
    weights_2 /= np.sum(weights_2)
    g2 = np.sum(price_2 * weights_2)
    return g1, g2


def get_risk_benchmark_state(context):
    """鑾峰彇椋庨櫓鍩哄噯鐨勬棩绾+鐩樹腑铻嶅悎鐘舵侊紝鐢ㄤ簬闇囪崱鏈熷垽鏂"""
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
    data_source = '鏄ㄦ棩鏃ョ嚎'
    try:
        today = context.current_dt.date()
        minute_df = get_price(
            g.risk_benchmark, start_date=today, end_date=context.current_dt,
            frequency='1m', fields=['close', 'high', 'low'],
            panel=False, fill_paused=False
        )
        if minute_df is not None and not minute_df.empty:
            minute_close = minute_df['close'].dropna()
            minute_high = minute_df['high'].dropna()
            minute_low = minute_df['low'].dropna()
            if not minute_close.empty:
                current_price = float(minute_close.iloc[-1])
                intraday_high = float(minute_high.max()) if not minute_high.empty else current_price
                intraday_low = float(minute_low.min()) if not minute_low.empty else current_price
                data_source = '褰撴棩鐩樹腑'
    except Exception:
        pass
    if current_price <= 0:
        try:
            current_data = get_current_data()
            live_price = current_data[g.risk_benchmark].last_price
            if live_price is not None and live_price > 0:
                current_price = float(live_price)
                intraday_high = max(intraday_high, current_price)
                intraday_low = min(intraday_low, current_price)
                data_source = '瀹炴椂蹇鐓'
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
    """鍒ゆ柇姝㈡崯淇″彿鏄鍚︿粛鍦ㄦ湁鏁堟湡鍐"""
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
    """棣栨¤繍琛屾椂锛屾牴鎹鍘嗗彶鏁版嵁鍒ゆ柇褰撳墠鏄鍚﹀勪簬闇囪崱鏈"""
    if not g.enable_range_bound_mode:
        return
    log.info("銆愰栨¤繍琛屻戝垵濮嬪寲闇囪崱鏈熺姸鎬...")
    try:
        if context.previous_date is None:
            log.warning("銆愰栨¤繍琛屻戞棤娉曡幏鍙栧墠涓涓浜ゆ槗鏃ワ紝淇濇寔姝ｅ父鏈")
            return
        end_date = context.previous_date
        lookback = max(g.ma_period, g.lookback_high_low_days) + 30
        df = get_price(g.risk_benchmark, end_date=end_date, count=lookback,
                       frequency='daily', fields=['close', 'high', 'low'], panel=False)
        if df is None or len(df) < max(g.ma_period, g.lookback_high_low_days):
            log.warning("銆愰栨¤繍琛屻戞暟鎹涓嶈冻锛屼繚鎸佹ｅ父鏈")
            return
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        current_price = close[-1]
        if len(close) >= g.lookback_high_low_days:
            recent_high = np.max(high[-g.lookback_high_low_days:])
            recent_low = np.min(low[-g.lookback_high_low_days:])
        else:
            recent_high = np.max(high)
            recent_low = np.min(low)
        ma = np.mean(close[-g.ma_period:])
        bias = (current_price - ma) / ma if ma > 0 else 0
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        current_rsi = calculate_rsi(close, period=14)
        should_enter = False
        signals = []
        if g.enable_bias_trigger and bias > g.bias_threshold:
            should_enter = True
            signals.append(f"涔栫荤巼{bias:.2%}>{g.bias_threshold:.0%}")
        if g.enable_rsi_trigger and current_rsi is not None and len(close) >= 15:
            prev_rsi = calculate_rsi(close[:-1], period=14)
            if prev_rsi is not None and prev_rsi > g.rsi_overbought and current_rsi < g.rsi_pullback:
                should_enter = True
                signals.append(f"RSI瓒呬拱鍥炶惤{prev_rsi:.1f}->{current_rsi:.1f}")
        if should_enter:
            g.current_filter = '闇囪崱鏈'
            g.risk_state = '闇囪崱鏈'
            g.range_bound_start_date = end_date
            g.range_bound_days_count = 0
            log.info(f"銆愰栨¤繍琛屻戝垵濮嬪寲杩涘叆闇囪崱鏈: {'; '.join(signals)}")
        else:
            g.current_filter = '姝ｅ父鏈'
            g.risk_state = '姝ｅ父鏈'
            if len(close) >= g.lookback_high_low_days:
                g.previous_drawdown = (recent_high - current_price) / recent_high if recent_high > 0 else 0
            else:
                g.previous_drawdown = 0
            g.previous_rsi = current_rsi
            rsi_str = f"{current_rsi:.1f}" if current_rsi is not None else "N/A"
            log.info(f"銆愰栨¤繍琛屻戝垵濮嬬姸鎬: 姝ｅ父鏈, 涔栫荤巼: {bias:.2%}, RSI: {rsi_str}, 浠庝綆鐐规定骞: {rise_from_low:.2%}")
    except Exception as e:
        log.warning(f"銆愰栨¤繍琛屻戝垵濮嬪寲闇囪崱鏈熺姸鎬佸紓甯: {e}锛屼繚鎸佹ｅ父鏈")


def check_and_exit_range_bound_mode(context):
    """妫鏌ユ槸鍚﹂渶瑕侀鍑洪渿鑽℃湡"""
    if not g.enable_range_bound_mode:
        return
    if g.current_filter != '闇囪崱鏈':
        return
    log.info("銆愰渿鑽℃湡閫鍑烘鏌ャ戝紑濮嬫娴嬮鍑烘潯浠...")
    try:
        benchmark_state = get_risk_benchmark_state(context)
        if benchmark_state is None:
            log.warning("銆愰渿鑽℃湡閫鍑烘鏌ャ戞暟鎹涓嶈冻锛岃烦杩")
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
        log.info(f"銆愰渿鑽℃湡鏁版嵁銆戝綋鍓嶄环: {current_price:.3f}, 杩憑g.lookback_high_low_days}鏃ラ珮鐐: {recent_high:.3f}, 浣庣偣: {recent_low:.3f}")
        log.info(f"銆愰渿鑽℃湡鏁版嵁銆戝洖鎾: {current_drawdown:.2%}, 浠庝綆鐐规定骞: {rise_from_low:.2%}")
        if g.enable_low_point_rise_trigger:
            if rise_from_low >= g.low_point_rise_threshold:
                recovery_signals.append(f"浠庝綆鐐逛笂娑▄rise_from_low:.2%}>={g.low_point_rise_threshold:.0%}")
                log.info(f"銆愰鍑烘潯浠惰Е鍙戙戜粠浣庣偣涓婃定: {rise_from_low:.2%}")
        if g.enable_stable_signal_trigger:
            if current_price > ma:
                recovery_signals.append("浠锋牸绔欎笂鍧囩嚎")
            if len(close) >= 2 and close[-1] > close[-2]:
                recovery_signals.append("浠锋牸鍥炲崌")
            if g.previous_drawdown is not None and current_drawdown < g.previous_drawdown:
                recovery_signals.append(f"鍥炴挙鏀剁獎({current_drawdown:.2%}<{g.previous_drawdown:.2%})")
            if current_rsi is not None and g.previous_rsi is not None and current_rsi > g.previous_rsi:
                recovery_signals.append(f"RSI鍥炲崌({current_rsi:.1f})")
            drawdown_safe = current_drawdown < g.drawdown_recovery
            if drawdown_safe:
                g.stable_days += 1
                log.info(f"銆愪紒绋宠℃暟銆戣繛缁浼佺ǔ澶╂暟: {g.stable_days}")
            else:
                g.stable_days = 0
        g.previous_drawdown = current_drawdown
        g.previous_rsi = current_rsi
        range_bound_days = 0
        if g.range_bound_start_date is not None:
            trade_days = get_trade_days(start_date=g.range_bound_start_date, end_date=context.current_dt.date())
            range_bound_days = len(trade_days) - 1
            if range_bound_days >= g.max_range_bound_days:
                recovery_signals.append(f"闇囪崱鏈熸弧({range_bound_days}澶)")
                log.info(f"銆愰鍑烘潯浠惰Е鍙戙戦渿鑽℃湡宸叉弧{range_bound_days}澶")
        low_point_condition = g.enable_low_point_rise_trigger and rise_from_low >= g.low_point_rise_threshold
        stable_condition = False
        if g.enable_stable_signal_trigger:
            drawdown_safe = current_drawdown < g.drawdown_recovery
            stable_condition = drawdown_safe and len(recovery_signals) >= 2 and g.stable_days >= 2
        force_condition = range_bound_days >= g.max_range_bound_days
        should_recover = low_point_condition or stable_condition or force_condition
        if should_recover:
            can_switch = True
            if g.last_switch_date is not None:
                trade_days = get_trade_days(start_date=g.last_switch_date, end_date=context.current_dt.date())
                days_since = len(trade_days) - 1
                if days_since < g.filter_switch_cooldown:
                    can_switch = False
                    log.info(f"銆愰渿鑽℃湡閫鍑恒戝喎鍗存湡涓锛岃窛涓婃″垏鎹{days_since}澶")
            if can_switch:
                g.current_filter = '姝ｅ父鏈'
                g.risk_state = '姝ｅ父鏈'
                g.last_switch_date = context.current_dt.date()
                g.range_bound_start_date = None
                g.range_bound_days_count = 0
                g.stable_days = 0
                log.info(f"銆愰鍑洪渿鑽℃湡銆戝垏鎹㈠洖鎷夋櫘鎷夋柉婊ゆ尝鍣: {'; '.join(recovery_signals)}")
        else:
            log.info("銆愰渿鑽℃湡閫鍑烘鏌ャ戞湭婊¤冻閫鍑烘潯浠讹紝淇濇寔闇囪崱鏈(楂樻柉婊ゆ尝鍣)")
    except Exception as e:
        log.warning(f"銆愰渿鑽℃湡閫鍑烘鏌ャ戝垽鏂鍑洪敊: {e}")


def check_and_enter_range_bound_mode(context):
    """妫鏌ユ槸鍚﹂渶瑕佽繘鍏ラ渿鑽℃湡"""
    if not g.enable_range_bound_mode:
        return
    log.info("銆愰渿鑽℃湡杩涘叆妫鏌ャ戝紑濮嬫娴...")
    stop_loss_signal_active = is_fresh_stop_loss_signal(context)
    can_switch = True
    if g.last_switch_date is not None:
        trade_days = get_trade_days(start_date=g.last_switch_date, end_date=context.current_dt.date())
        days_since = len(trade_days) - 1
        if days_since < g.filter_switch_cooldown:
            can_switch = False
            log.info(f"銆愰渿鑽℃湡妫鏌ャ戝喎鍗存湡涓锛岃窛涓婃″垏鎹{days_since}澶")
    if g.current_filter == '闇囪崱鏈':
        log.info("銆愰渿鑽℃湡妫鏌ャ戝綋鍓嶅凡鍦ㄩ渿鑽℃湡")
        return
    if not can_switch:
        return
    risk_signals = []
    try:
        benchmark_state = get_risk_benchmark_state(context)
        if benchmark_state is not None:
            close = benchmark_state['close_series']
            current_price = benchmark_state['current_price']
            # 鏉′欢1: 涔栫荤巼杩囧ぇ
            if g.enable_bias_trigger:
                ma = benchmark_state['ma']
                bias = (current_price - ma) / ma if ma > 0 else 0
                if bias > g.bias_threshold:
                    risk_signals.append(f"涔栫荤巼杩囧ぇ({bias:.2%}>{g.bias_threshold:.0%})")
                    log.info(f"銆愭潯浠惰Е鍙戙戜箹绂荤巼: {bias:.2%} (鏁版嵁婧:{benchmark_state['data_source']})")
            # 鏉′欢2: RSI瓒呬拱鍥炶惤
            if g.enable_rsi_trigger:
                current_rsi = benchmark_state['current_rsi']
                if len(close) >= 15 and current_rsi is not None:
                    prev_rsi = benchmark_state['previous_rsi']
                    if prev_rsi is not None:
                        if prev_rsi > g.rsi_overbought and current_rsi < g.rsi_pullback and current_rsi < prev_rsi:
                            risk_signals.append(f"RSI瓒呬拱鍥炶惤({prev_rsi:.1f}->{current_rsi:.1f})")
                            log.info(f"銆愭潯浠惰Е鍙戙慠SI瓒呬拱鍥炶惤: {prev_rsi:.1f}->{current_rsi:.1f}")
    except Exception as e:
        log.warning(f"銆愰渿鑽℃湡妫鏌ャ戣幏鍙栧熀鍑嗘暟鎹寮傚父: {e}")
    # 鏉′欢3: 鐩堝埄淇濇姢瑙﹀彂姝㈡崯
    if g.enable_stop_loss_trigger and stop_loss_signal_active:
        risk_signals.append("鐩堝埄淇濇姢瑙﹀彂姝㈡崯")
        log.info("銆愭潯浠惰Е鍙戙戠泩鍒╀繚鎶よЕ鍙戞㈡崯淇″彿")
    if len(risk_signals) > 0:
        g.current_filter = '闇囪崱鏈'
        g.risk_state = '闇囪崱鏈'
        g.last_switch_date = context.current_dt.date()
        g.range_bound_start_date = context.current_dt.date()
        g.range_bound_days_count = 0
        g.stable_days = 0
        g.stop_loss_triggered_today = False
        g.stop_loss_triggered_date = None
        log.info(f"銆愯繘鍏ラ渿鑽℃湡銆戝垏鎹㈠埌楂樻柉婊ゆ尝鍣: {'; '.join(risk_signals)}")
    else:
        log.info("銆愰渿鑽℃湡妫鏌ャ戞湭婊¤冻杩涘叆鏉′欢锛屼繚鎸佹ｅ父鏈(鎷夋櫘鎷夋柉婊ゆ尝鍣)")


def check_range_bound(context):
    """闇囪崱鏈熸鏌ュ叆鍙ｏ紙13:55瀹氭椂璋冨害锛屽湪鍗栧嚭鍓嶆墽琛岋級"""
    if not g.enable_range_bound_mode:
        return
    log.info("========== 闇囪崱鏈熸鏌ュ紑濮 ==========")
    log.info(f"褰撳墠鐘舵: {g.current_filter}")
    check_and_exit_range_bound_mode(context)
    check_and_enter_range_bound_mode(context)
    log.info(f"妫鏌ュ悗鐘舵: {g.current_filter}")
    # 鐘舵佸彉鏇村悗娓呴櫎鎺掑悕缂撳瓨锛岀‘淇14:00鍗栧嚭鏃堕噸鏂拌＄畻
    g.rankings_cache = {'date': None, 'data': None}
    log.info("========== 闇囪崱鏈熸鏌ュ畬鎴 ==========")


def reset_range_bound_daily(context):
    """鏀剁洏鍚庨噸缃闇囪崱鏈熺浉鍏崇殑姣忔棩鏍囧織"""
    if g.current_filter == '闇囪崱鏈' and g.range_bound_start_date is not None:
        trade_days = get_trade_days(start_date=g.range_bound_start_date, end_date=context.current_dt.date())
        g.range_bound_days_count = len(trade_days) - 1
        log.info(f"闇囪崱鏈熷凡鎸佺画 {g.range_bound_days_count} 涓浜ゆ槗鏃")
    log.debug("鏀剁洏闇囪崱鏈熸爣蹇楅噸缃瀹屾垚")


# ==================== 鏍稿績璁＄畻妯″潡 ====================
def get_cached_rankings(context):
    """鑾峰彇缂撳瓨鐨凟TF鎺掑悕锛屼繚璇佸悓涓浜ゆ槗鏃ュ唴澶氭¤皟鐢ㄧ粨鏋滀竴鑷"""
    today = context.current_dt.date()
    if g.rankings_cache['date'] != today:
        log.info("閲嶆柊璁＄畻ETF鎺掑悕...")
        ranked = get_ranked_etfs(context)
        g.rankings_cache = {'date': today, 'data': ranked}
    else:
        log.debug("浣跨敤缂撳瓨鐨凟TF鎺掑悕")
    return g.rankings_cache['data']


def get_ranked_etfs(context):
    """
    璁＄畻鎵鏈塃TF鐨勫姩閲忓緱鍒嗭紝搴旂敤鎵鏈夎繃婊ゆ潯浠讹紝杩斿洖鎸夊緱鍒嗛檷搴忕殑鍒楄〃
    """
    etf_metrics = []
    for etf in g.etf_pool:
        # 鍋滅墝杩囨护
        if get_current_data()[etf].paused:
            log.debug(f"{etf} {get_name(etf)} 鍋滅墝锛岃烦杩")
            continue

        metrics = calculate_momentum_metrics(context, etf)
        if metrics is not None:
            # 寰楀垎鑼冨洿杩囨护
            if g.min_score_threshold < metrics['score'] < g.max_score_threshold:
                etf_metrics.append(metrics)
            else:
                log.debug(f"{etf} {metrics['etf_name']} 寰楀垎{metrics['score']:.2f}瓒呭嚭闃堝硷紝杩囨护")

    etf_metrics.sort(key=lambda x: x['score'], reverse=True)
    return etf_metrics


def calculate_momentum_metrics(context, etf):
    """
    璁＄畻鍗曞彧ETF鐨勫姩閲忔寚鏍囷紝搴旂敤鎵鏈夎繃婊ゆ潯浠
    杩斿洖瀛楀吀锛歟tf, etf_name, annualized_returns, r_squared, score, current_price, short_annualized
    """
    try:
        name = get_name(etf)
        # 鑾峰彇瓒冲熷巻鍙叉暟鎹
        lookback = max(g.lookback_days, g.short_lookback_days) + 20
        prices = attribute_history(etf, lookback, '1d', ['close', 'high'])
        if len(prices) < g.lookback_days:
            log.debug(f"{etf} {name} 鍘嗗彶鏁版嵁涓嶈冻{len(prices)}澶╋紝璺宠繃")
            return None

        # 浠锋牸搴忓垪锛堝惈褰撳ぉ锛
        current_price = get_current_data()[etf].last_price
        price_series = np.append(prices["close"].values, current_price)

        # ===== 1. 鐩堝埄淇濇姢妫鏌ワ紙鎺掗櫎锛 =====
        if check_profit_protection(etf, context):
            log.info(f"馃毇 {etf} {name} 瑙﹀彂鐩堝埄淇濇姢锛屼粠鎺掑悕涓鎺掗櫎")
            return None

        # ===== 2. 婧浠风巼杩囨护锛堟彁鍓嶈嚦鎺掑悕闃舵碉紝鑾峰彇澶辫触鍒欒烦杩囪繃婊わ級=====
        if g.enable_premium_filter:
            # 鑾峰彇鍓嶄竴涓浜ゆ槗鏃ワ紙鐢ㄤ簬鍑鍊兼暟鎹锛
            prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]
            premium, _, _ = get_premium_rate(etf, prev_date)
            if premium is not None:
                if premium > g.premium_threshold:
                    log.info(f"馃毇 {etf} {name} 婧浠风巼{premium*100:.2f}% > {g.premium_threshold*100:.0f}%锛屼粠鎺掑悕涓鎺掗櫎")
                    return None
            else:
                # 鏃犳硶鑾峰彇婧浠风巼锛岃烦杩囪ヨ繃婊ゆ潯浠讹紙涓嶈繃婊わ級
                log.debug(f"{etf} {name} 鏃犳硶鑾峰彇婧浠风巼锛岃烦杩囨孩浠风巼杩囨护")

        # ===== 3. 鎴愪氦閲忚繃婊わ紙鎺掗櫎锛 =====
        if g.enable_volume_check:
            vol_ratio = get_volume_ratio(context, etf)
            if vol_ratio is not None:
                annualized = get_annualized_returns(price_series, g.lookback_days)
                if annualized > g.volume_return_limit:
                    log.info(f"馃搲 {etf} {name} 鎴愪氦閲忔斁閲弡vol_ratio:.1f}鍊嶏紝涓斿勾鍖杮annualized*100:.1f}% > 闃堝納g.volume_return_limit*100:.1f}%锛岃繃婊")
                    return None

        # ===== 4. 鐭鏈熷姩閲忚繃婊わ紙鎺掗櫎锛 =====
        if len(price_series) >= g.short_lookback_days + 1:
            short_return = price_series[-1] / price_series[-(g.short_lookback_days + 1)] - 1
            short_annualized = (1 + short_return) ** (250 / g.short_lookback_days) - 1
        else:
            short_annualized = 0

        if g.use_short_momentum_filter and short_annualized < g.short_momentum_threshold:
            log.debug(f"{etf} {name} 鐭鏈熷姩閲弡short_annualized*100:.1f}% < 闃堝納g.short_momentum_threshold*100:.1f}%锛岃繃婊")
            return None

        # ===== 5. 闀挎湡鍔ㄩ噺璁＄畻锛堝緱鍒嗭級 =====
        recent = price_series[-(g.lookback_days + 1):]
        y = np.log(recent)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized_returns = math.exp(slope * 250) - 1

        # R虏锛堣秼鍔跨ǔ瀹氭э級
        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0

        score = annualized_returns * r_squared

        # ===== 6. 杩3鏃ュ崟鏃ヨ穼骞呰繃婊わ紙鎺掗櫎锛 =====
        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            if min(day1, day2, day3) < g.loss:
                log.info(f"鈿狅笍 {etf} {name} 杩3鏃ユ湁鍗曟棩璺屽箙瓒厈(1-g.loss)*100:.1f}%锛岀洿鎺ユ帓闄")
                return None

        # ===== 7. 鍔ㄦ佹护娉㈠櫒杩囨护锛堥渿鑽℃湡鏈哄埗锛 =====
        if g.enable_range_bound_mode and len(price_series) >= 10:
            try:
                laplace_values = laplace_filter(price_series, s=g.laplace_s_param)
                laplace_slope = laplace_values[-1] - laplace_values[-2] if len(laplace_values) >= 2 else 0
                passed_laplace = (current_price > laplace_values[-1] and laplace_slope > g.laplace_min_slope)
                g1_val, g2_val = gaussian_filter_last_two(price_series, sigma=g.gaussian_sigma)
                gaussian_slope = g1_val - g2_val
                passed_gaussian = (current_price > g1_val and gaussian_slope > g.gaussian_min_slope)
                if g.current_filter == '姝ｅ父鏈':
                    passed_filter = passed_laplace
                    filter_name = '鎷夋櫘鎷夋柉'
                else:
                    passed_filter = passed_gaussian
                    filter_name = '楂樻柉'
                if not passed_filter:
                    log.debug(f"{etf} {name} 鏈閫氳繃{filter_name}婊ゆ尝鍣({g.current_filter})锛岃繃婊")
                    return None
            except Exception as e:
                log.debug(f"{etf} {name} 婊ゆ尝鍣ㄨ＄畻寮傚父: {e}")

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
        log.warning(f"璁＄畻{etf} {get_name(etf)}鏃跺嚭閿: {e}")
        return None


def get_annualized_returns(price_series, lookback_days):
    """璁＄畻鍔犳潈骞村寲鏀剁泭鐜"""
    recent = price_series[-(lookback_days + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    slope, _ = np.polyfit(x, y, 1, w=weights)
    return math.exp(slope * 250) - 1


def get_volume_ratio(context, security, lookback=None, threshold=None):
    """璁＄畻褰撴棩鎴愪氦閲忎笌杩囧幓N鏃ュ潎閲忕殑姣斿硷紝鑻ヨ秴杩囬槇鍊煎垯杩斿洖姣斿硷紝鍚﹀垯None"""
    lookback = lookback or g.volume_lookback
    threshold = threshold or g.volume_threshold
    try:
        name = get_name(security)
        hist = attribute_history(security, lookback, '1d', ['volume'])
        if hist.empty or len(hist) < lookback:
            return None
        avg_vol = hist['volume'].mean()

        # 鑾峰彇褰撴棩鍒嗛挓鎴愪氦閲忕疮璁
        today = context.current_dt.date()
        df_vol = get_price(security, start_date=today, end_date=context.current_dt,
                           frequency='1m', fields=['volume'], skip_paused=False, fq='pre')
        if df_vol is None or df_vol.empty:
            return None
        current_vol = df_vol['volume'].sum()
        ratio = current_vol / avg_vol if avg_vol > 0 else 0
        if ratio > threshold:
            log.debug(f"{security} {name} 鎴愪氦閲忔瘮{ratio:.2f} > {threshold}")
            return ratio
        return None
    except Exception as e:
        log.warning(f"鎴愪氦閲忚＄畻澶辫触 {security}: {e}")
        return None


# ==================== 鍗栧嚭妯″潡 ====================
def check_positions(context):
    """姣忔棩寮鐩樻鏌ユ寔浠撶姸鎬侊紝浠呯敤浜庢棩蹇"""
    for sec in context.portfolio.positions:
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            log.info(f"馃搳 鎸佷粨锛歿sec} {get_name(sec)} 鏁伴噺{pos.total_amount} 鎴愭湰{pos.avg_cost:.3f} 鐜颁环{pos.price:.3f}")


def etf_sell_trade(context):
    """鍗栧嚭涓嶇﹀悎鏉′欢鐨勬寔浠擄紙鎺掑悕鍙樺寲銆佹孩浠风巼杩囬珮锛"""
    log.info("========== 鍗栧嚭鎿嶄綔寮濮 ==========")

    ranked = get_cached_rankings(context)
    # 纭瀹氱洰鏍嘐TF鍒楄〃锛堝緱鍒嗗墠N鍚嶄笖婊¤冻寰楀垎闃堝硷級
    target_etfs = []
    for m in ranked[:g.holdings_num]:
        if m['score'] >= g.min_score_threshold:
            target_etfs.append(m['etf'])
    # 鑻ユ病鏈夌洰鏍嘐TF涓旈槻寰″彲鐢锛屽垯鎶婇槻寰ETF浣滀负鐩鏍囷紙渚涘崠鍑哄垽鏂鐢锛
    defensive_available = check_defensive_etf_available(context)
    if not target_etfs and defensive_available:
        target_etfs = [g.defensive_etf]

    target_set = set(target_etfs)

    # 鍗栧嚭涓嶅湪鐩鏍囧垪琛ㄧ殑鎸佷粨
    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        if sec not in target_set:
            pos = context.portfolio.positions[sec]
            if pos.total_amount > 0:
                if smart_order_target_value(sec, 0, context):
                    log.info(f"馃摛 鍗栧嚭涓嶅湪鐩鏍囩殑鎸佷粨锛歿sec} {get_name(sec)}")

    log.info("========== 鍗栧嚭鎿嶄綔瀹屾垚 ==========")


# ==================== 涔板叆妯″潡 ====================
def etf_buy_trade(context):
    """涔板叆绗﹀悎鏉′欢鐨凟TF锛岀瓑鏉冨垎閰嶏紝鎸夋帓鍚嶉『搴忛愪釜灏濊瘯鐩村埌鍑戝熸寔浠撴暟閲"""
    log.info("========== 涔板叆鎿嶄綔寮濮 ==========")

    ranked = get_cached_rankings(context)
    # 鎵撳嵃鎺掑悕鍓5鐨勬寚鏍囷紙璋冭瘯鐢锛
    log.info("=== ETF鎺掑悕鍓5 ===")
    for i, m in enumerate(ranked[:5]):
        log.info(f"鎺掑悕{i+1}: {m['etf']} {m['etf_name']} 寰楀垎{m['score']:.4f} 骞村寲{m['annualized_returns']*100:.2f}% R虏={m['r_squared']:.4f}")

    # ---------- 纭瀹氱洰鏍嘐TF鍒楄〃锛氫緷娆″皾璇曟帓鍚嶉潬鍓嶇殑ETF ----------
    target_etfs = []
    prev_date = None
    if g.enable_premium_filter:
        # 鑾峰彇鍓嶄竴涓浜ゆ槗鏃ョ敤浜庢孩浠风巼璁＄畻
        prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]

    for m in ranked:   # 鎸夊緱鍒嗕粠楂樺埌浣庨亶鍘嗘墍鏈塃TF
        if len(target_etfs) >= g.holdings_num:
            break   # 宸插噾澶熺洰鏍囨寔浠撴暟閲
        etf = m['etf']

        # 閫氳繃鎵鏈夋鏌ワ紝鍔犲叆鐩鏍囧垪琛
        target_etfs.append(etf)
        log.info(f"馃幆 鐩鏍嘐TF {len(target_etfs)}: {etf} {m['etf_name']} 寰楀垎{m['score']:.4f}")

    # ---------- 闃插尽妯″紡鍒ゆ柇 ----------
    if not target_etfs:
        if check_defensive_etf_available(context):
            target_etfs = [g.defensive_etf]
            log.info(f"馃洝锔 杩涘叆闃插尽妯″紡锛岄夋嫨闃插尽ETF锛歿g.defensive_etf} {get_name(g.defensive_etf)}")
        else:
            log.info("馃挙 鏃犵洰鏍嘐TF涓旈槻寰′笉鍙鐢锛屼繚鎸佺┖浠")
            return

    # 妫鏌ユ槸鍚︽湁鎸佷粨闇瑕佸厛鍗栧嚭锛堜笉鍦ㄧ洰鏍囧垪琛ㄧ殑鎸佷粨锛
    current_etf_pos = [s for s in context.portfolio.positions if s in g.etf_pool or s == g.defensive_etf]
    to_sell = [s for s in current_etf_pos if s not in target_etfs]
    if to_sell:
        to_sell_names = [get_name(s) for s in to_sell]
        log.info(f"灏氭湁鎸佷粨闇瑕佸崠鍑猴細{list(zip(to_sell, to_sell_names))}锛岀瓑寰呭崠鍑哄畬鎴愬啀涔板叆")
        return

    # 绛夋潈鍒嗛厤
    total_val = context.portfolio.total_value
    target_per_etf = total_val / len(target_etfs)

    for etf in target_etfs:
        current_val = 0
        if etf in context.portfolio.positions:
            pos = context.portfolio.positions[etf]
            if pos.total_amount > 0:
                current_val = pos.total_amount * pos.price
        # 5%瀹瑰樊璋冧粨
        if abs(current_val - target_per_etf) > target_per_etf * 0.05 or current_val == 0:
            if smart_order_target_value(etf, target_per_etf, context):
                action = "涔板叆" if current_val < target_per_etf else "璋冧粨"
                log.info(f"馃摝 {action}锛歿etf} {get_name(etf)} 鐩鏍囬噾棰漿target_per_etf:.2f}")

    log.info("========== 涔板叆鎿嶄綔瀹屾垚 ==========")


# ==================== 杈呭姪鍑芥暟 ====================
def get_name(security):
    """鑾峰彇璇佸埜鍚嶇О锛屽甫寮傚父澶勭悊"""
    try:
        return get_current_data()[security].name
    except:
        return "鏈鐭"


def check_defensive_etf_available(context):
    """妫鏌ラ槻寰ETF鏄鍚﹀彲浜ゆ槗锛堟湭鍋滅墝銆佹湭娑ㄨ穼鍋滐級"""
    data = get_current_data()
    etf = g.defensive_etf
    if data[etf].paused:
        log.debug(f"闃插尽ETF {etf} {get_name(etf)} 鍋滅墝")
        return False
    if data[etf].last_price >= data[etf].high_limit:
        log.debug(f"闃插尽ETF {etf} {get_name(etf)} 娑ㄥ仠")
        return False
    if data[etf].last_price <= data[etf].low_limit:
        log.debug(f"闃插尽ETF {etf} {get_name(etf)} 璺屽仠")
        return False
    return True


def smart_order_target_value(security, target_value, context):
    """
    鏅鸿兘涓嬪崟锛氭牴鎹鐩鏍囧競鍊艰皟鏁存寔浠擄紝澶勭悊鍋滅墝銆佹定璺屽仠銆佹渶灏忎氦鏄撻噾棰濄乀+1
    """
    data = get_current_data()
    name = get_name(security)

    if data[security].paused:
        log.info(f"{security} {name} 鍋滅墝锛岃烦杩")
        return False

    price = data[security].last_price
    if price == 0:
        log.info(f"{security} {name} 褰撳墠浠锋牸0锛岃烦杩")
        return False

    target_amount = int(target_value / price)
    # 鎸100鑲℃暣鏁板嶈皟鏁
    target_amount = (target_amount // 100) * 100
    if target_amount <= 0 and target_value > 0:
        target_amount = 100

    cur_pos = context.portfolio.positions.get(security, None)
    cur_amount = cur_pos.total_amount if cur_pos else 0
    diff = target_amount - cur_amount

    # 鏍规嵁浜ゆ槗鏂瑰悜妫鏌ユ定璺屽仠
    if diff > 0:  # 涔板叆
        if data[security].last_price >= data[security].high_limit:
            log.info(f"{security} {name} 娑ㄥ仠锛岃烦杩囦拱鍏")
            return False
    elif diff < 0:  # 鍗栧嚭
        if data[security].last_price <= data[security].low_limit:
            log.info(f"{security} {name} 璺屽仠锛岃烦杩囧崠鍑")
            return False

    # 鏈灏忎氦鏄撻噾棰濇鏌
    trade_val = abs(diff) * price
    if 0 < trade_val < g.min_money:
        log.info(f"{security} {name} 浜ゆ槗閲戦漿trade_val:.2f} < {g.min_money}锛岃烦杩")
        return False

    # T+1澶勭悊
    if diff < 0:
        closeable = cur_pos.closeable_amount if cur_pos else 0
        if closeable == 0:
            log.info(f"{security} {name} 褰撳ぉ涔板叆涓嶅彲鍗栧嚭")
            return False
        diff = -min(abs(diff), closeable)

    if diff != 0:
        order_result = order(security, diff)
        if order_result:
            log.info(f"{'馃摜 涔板叆' if diff>0 else '馃摛 鍗栧嚭'} {security} {name} 鏁伴噺{abs(diff)} 浠锋牸{price:.3f}")
            return True
        else:
            log.warning(f"涓嬪崟澶辫触: {security} {name} 鏁伴噺{diff}")
            return False
    return False
