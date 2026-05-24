#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涓冩槦鎷夋櫘鎷夋柉楂樻柉绛栫暐 - Backtrader鐗堟湰
===================================================
鍏嬮殕鑷仛瀹芥枃绔狅細https://www.joinquant.com/post/70329
鍘熶綔鑰咃細king088

鏍稿績閫昏緫锛?1. ETF鍔ㄩ噺杞姩 + 鎷夋櫘鎷夋柉/楂樻柉鍙屾护娉㈠櫒
2. 闇囪崱鏈熻嚜鍔ㄦ娴嬩笌鍒囨崲锛堟媺鏅媺鏂?姝ｅ父鏈燂紝楂樻柉=闇囪崱鏈燂級
3. 鐩堝埄淇濇姢銆佹孩浠风巼杩囨护銆佹垚浜ら噺杩囨护
4. 绛夋潈鎸佷粨锛圱op1锛?
鏀瑰啓涓築acktrader鏈湴鍥炴祴鐗堟湰
"""

import sys
import backtrader as bt
import pandas as pd
import numpy as np
import math
import warnings
from datetime import datetime, timedelta
import os
from io import StringIO

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# ===========================================================
# 鍙傛暟閰嶇疆
# ===========================================================

INITIAL_CASH = 100000.0
COMMISSION = 0.0001  # 0.01%

# ETF姹狅紙鑱氬浠ｇ爜鏄犲皠锛岄渶鍦ㄦ湰鍦版湁瀵瑰簲CSV鏁版嵁锛?ETF_POOL = [
    '518880',  # 榛勯噾ETF
    '159980',  # 鏈夎壊ETF
    '159985',  # 璞嗙矔ETF
    '501018',  # 鍗楁柟鍘熸补
    '161226',  # 鐧介摱LOF
    '159981',  # 鑳芥簮鍖栧伐ETF
    '513100',  # 绾虫寚ETF
    '159509',  # 绾虫寚绉戞妧ETF
    '513290',  # 绾虫寚鐢熺墿ETF
    '513500',  # 鏍囨櫘500ETF
    '159529',  # 鏍囨櫘娑堣垂
    '513400',  # 閬撶惣鏂疎TF
    '513520',  # 鏃ョ粡225ETF
    '513030',  # 寰峰浗30ETF
    '513080',  # 娉曞浗ETF
    '513310',  # 涓煩鍗婂浣揈TF
    '513730',  # 涓滃崡浜欵TF
    '159792',  # 娓偂浜掕仈ETF
    '513130',  # 鎭掔敓绉戞妧
    '513050',  # 涓浜掕仈缃慐TF
    '159920',  # 鎭掔敓ETF
    '513690',  # 娓偂绾㈠埄
    '510300',  # 娌繁300ETF
    '510500',  # 涓瘉500ETF
    '510050',  # 涓婅瘉50ETF
    '510210',  # 涓婅瘉ETF
    '159915',  # 鍒涗笟鏉縀TF
    '588080',  # 绉戝垱50
    '512100',  # 涓瘉1000ETF
    '563360',  # A500-ETF
    '563300',  # 涓瘉2000ETF
    '512890',  # 绾㈠埄浣庢尝ETF
    '159967',  # 鍒涗笟鏉挎垚闀縀TF
    '512040',  # 浠峰€糆TF
    '159201',  # 鑷敱鐜伴噾娴丒TF
    '511380',  # 鍙浆鍊篍TF
    '511010',  # 鍥藉€篍TF
    '511220',  # 鍩庢姇鍊篍TF
]

DEFENSIVE_ETF = '511880'  # 璐у竵鍩洪噾锛堥槻寰℃€TF锛?
# 鏍稿績鍙傛暟
LOOKBACK_DAYS = 25              # 鍔ㄩ噺璁＄畻鍛ㄦ湡
HOLDINGS_NUM = 1                # 鎸佷粨鏁伴噺锛圱op N锛?MIN_MONEY = 5000                 # 鏈€灏忎氦鏄撻噾棰?
# 鐩堝埄淇濇姢鍙傛暟
ENABLE_PROFIT_PROTECTION = True
PROFIT_PROTECTION_LOOKBACK = 1    # 鍥炵湅鍛ㄦ湡锛堝ぉ锛?PROFIT_PROTECTION_THRESHOLD = 0.05  # 鍥炴挙闃堝€硷紙5%锛?
# 鎴愪氦閲忚繃婊?ENABLE_VOLUME_CHECK = False  # 鏈湴鍥炴祴鏆備笉鏀寔瀹炴椂鎴愪氦閲?VOLUME_LOOKBACK = 5
VOLUME_THRESHOLD = 2

# 鐭湡鍔ㄩ噺杩囨护
USE_SHORT_MOMENTUM_FILTER = False
SHORT_LOOKBACK_DAYS = 10
SHORT_MOMENTUM_THRESHOLD = 0.0

# 婧环鐜囪繃婊わ紙ETF鐗规湁锛屾湰鍦板洖娴嬫殏涓嶆敮鎸侊級
ENABLE_PREMIUM_FILTER = False
PREMIUM_THRESHOLD = 0.20

# 闇囪崱鏈熷弬鏁?ENABLE_RANGE_BOUND_MODE = True
LOOKBACK_HIGH_LOW_DAYS = 20  # 楂樹綆鐐瑰洖鐪?RISK_BENCHMARK = '510300'     # 椋庨櫓鍩哄噯锛堟勃娣?00ETF锛?LAPLACE_S_PARAM = 0.05
LAPLACE_MIN_SLOPE = 0.001
GAUSSIAN_SIGMA = 1.2
GAUSSIAN_MIN_SLOPE = 0.002

# 杩涘叆闇囪崱鏈熸潯浠?ENABLE_BIAS_TRIGGER = True
BIAS_THRESHOLD = 0.10            # 涔栫鐜囬槇鍊硷紙10%锛?MA_PERIOD = 20
ENABLE_RSI_TRIGGER = True
RSI_OVERBOUGHT = 75
RSI_PULLBACK = 60

# 閫€鍑洪渿鑽℃湡鏉′欢
ENABLE_LOW_POINT_RISE_TRIGGER = True
LOW_POINT_RISE_THRESHOLD = 0.03  # 浠庝綆鐐逛笂娑?%
ENABLE_STABLE_SIGNAL_TRIGGER = True
DRAWDOWN_RECOVERY = 0.03       # 鍥炴挙鏀剁獎闃堝€?MAX_RANGE_BOUND_DAYS = 15        # 鏈€澶ч渿鑽℃湡澶╂暟

# 鏁版嵁璺緞
DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf_qixing'

# ===========================================================
# 宸ュ叿鍑芥暟
# ===========================================================

def laplace_filter(price, s=0.05):
    """鎷夋櫘鎷夋柉婊ゆ尝鍣紙姝ｅ父鏈熶娇鐢級"""
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L


def gaussian_filter_last_two(price, sigma=1.2):
    """楂樻柉婊ゆ尝鍣紙闇囪崱鏈熶娇鐢紝浠呰绠楁渶鍚庝袱涓偣锛?""
    n = len(price)
    if n < 2:
        return 0, 0
    idx_1 = np.arange(n)
    weights_1 = np.exp(-(idx_1 + 1) ** 2 / (2 * sigma ** 2))[::-1]
    weights_1 /= np.sum(weights_1)
    g1 = np.sum(price * weights_1)
    
    price_2 = price[:-1]
    idx_2 = np.arange(n - 1)
    weights_2 = np.exp(-(idx_2 + 1) ** 2 / (2 * sigma ** 2))[::-1]
    weights_2 /= np.sum(weights_2)
    g2 = np.sum(price_2 * weights_2)
    return g1, g2


def calculate_rsi(prices, period=14):
    """璁＄畻RSI鍊?""
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ===========================================================
# Backtrader绛栫暐绫?# ===========================================================

class QixingLaplaceGaussian(bt.Strategy):
    """涓冩槦鎷夋櫘鎷夋柉楂樻柉绛栫暐"""
    
    params = (
        ('lookback_days', LOOKBACK_DAYS),
        ('holdings_num', HOLDINGS_NUM),
        ('defensive_etf', DEFENSIVE_ETF),
        ('enable_profit_protection', ENABLE_PROFIT_PROTECTION),
        ('profit_protection_lookback', PROFIT_PROTECTION_LOOKBACK),
        ('profit_protection_threshold', PROFIT_PROTECTION_THRESHOLD),
        ('enable_range_bound_mode', ENABLE_RANGE_BOUND_MODE),
        ('risk_benchmark', RISK_BENCHMARK),
    )
    
    def __init__(self):
        self.etf_pool = ETF_POOL
        self.current_filter = '姝ｅ父鏈?  # 鎴?'闇囪崱鏈?
        self.range_bound_start = None
        self.range_bound_days = 0
        self.last_switch_date = None
        self.previous_drawdown = None
        self.previous_rsi = None
        self.stable_days = 0
        
        # 涓烘瘡鍙狤TF鍒涘缓鏁版嵁寮曠敤
        self.etf_datas = {}
        for i, etf in enumerate(self.etf_pool):
            if etf in self.getdatanames():
                self.etf_datas[etf] = self.getdatabyname(etf)
        
        # 闃插尽ETF
        if self.p.defensive_etf in self.getdatanames():
            self.defensive_data = self.getdatabyname(self.p.defensive_etf)
        else:
            self.defensive_data = None
        
        # 椋庨櫓鍩哄噯
        if self.p.risk_benchmark in self.getdatanames():
            self.benchmark_data = self.getdatabyname(self.p.risk_benchmark)
        else:
            self.benchmark_data = None
        
        self.last_date = None
        self.current_targets = []
    
    def next(self):
        """姣忎釜浜ゆ槗鏃ユ墽琛?""
        current_date = self.datas[0].datetime.date(0)
        
        # 妫€鏌ラ渿鑽℃湡鐘舵€?        if self.p.enable_range_bound_mode:
            self.check_range_bound_mode()
        
        # 璁＄畻鎺掑悕
        ranked = self.get_ranked_etfs()
        
        # 纭畾鐩爣ETF
        targets = []
        for m in ranked[:self.p.holdings_num]:
            if m['score'] > 0:
                targets.append(m['etf'])
        
        if not targets and self.defensive_data:
            targets = [self.p.defensive_etf]
        
        self.current_targets = targets
        
        # 鍗栧嚭涓嶅湪鐩爣鐨勬寔浠?        for d in self.datas:
            etf = d._name
            pos = self.getposition(d).size
            if pos > 0 and etf not in targets:
                self.close(d)
                print(f"[{current_date}] 鍗栧嚭: {etf}")
        
        # 涔板叆鐩爣ETF锛堢瓑鏉冿級
        if targets:
            target_value = self.broker.getvalue() / len(targets)
            for etf in targets:
                d = self.getdatabyname(etf)
                if d:
                    current_pos = self.getposition(d).size
                    current_val = current_pos * d.close[0]
                    if abs(current_val - target_value) > target_value * 0.05 or current_pos == 0:
                        size = int((target_value / d.close[0]) // 100 * 100)
                        if size > 0:
                            self.order_target_size(d, size)
                            print(f"[{current_date}] 涔板叆: {etf} {size}鑲?@ {d.close[0]:.3f}")
        
        self.last_date = current_date
    
    def get_ranked_etfs(self):
        """璁＄畻鎵€鏈塃TF鐨勫姩閲忓緱鍒嗗苟鎺掑悕"""
        metrics = []
        for etf in self.etf_pool:
            if etf not in self.etf_datas:
                continue
            m = self.calculate_momentum(etf)
            if m:
                metrics.append(m)
        
        metrics.sort(key=lambda x: x['score'], reverse=True)
        return metrics
    
    def calculate_momentum(self, etf):
        """璁＄畻鍗曞彧ETF鐨勫姩閲忔寚鏍?""
        data = self.etf_datas.get(etf)
        if not data:
            return None
        
        try:
            # 鑾峰彇鍘嗗彶鏁版嵁
            lookback = max(self.p.lookback_days, SHORT_LOOKBACK_DAYS) + 20
            closes = []
            for i in range(-lookback, 0):
                if len(data) + i >= 0:
                    closes.append(data.close[i])
            
            if len(closes) < self.p.lookback_days:
                return None
            
            current_price = closes[-1]
            price_series = np.array(closes)
            
            # 鐩堝埄淇濇姢妫€鏌?            if self.p.enable_profit_protection:
                recent_high = max(closes[-(self.p.profit_protection_lookback + 1):])
                if current_price < recent_high * (1 - self.p.profit_protection_threshold):
                    return None
            
            # 闀挎湡鍔ㄩ噺璁＄畻
            recent = price_series[-(self.p.lookback_days + 1):]
            y = np.log(recent)
            x = np.arange(len(y))
            weights = np.linspace(1, 2, len(y))
            slope, intercept = np.polyfit(x, y, 1, w=weights)
            annualized_returns = math.exp(slope * 250) - 1
            
            # R虏锛堣秼鍔跨ǔ瀹氭€э級
            ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
            ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0
            
            score = annualized_returns * r_squared
            
            return {
                'etf': etf,
                'annualized_returns': annualized_returns,
                'r_squared': r_squared,
                'score': score,
                'current_price': current_price,
            }
        except Exception as e:
            return None
    
    def check_range_bound_mode(self):
        """妫€鏌ユ槸鍚﹂渶瑕佸垏鎹㈤渿鑽℃湡/姝ｅ父鏈熸ā寮?""
        if not self.benchmark_data:
            return
        
        closes = []
        highs = []
        lows = []
        for i in range(-(max(MA_PERIOD, LOOKBACK_HIGH_LOW_DAYS) + 5), 0):
            if len(self.benchmark_data) + i >= 0:
                closes.append(self.benchmark_data.close[i])
                highs.append(self.benchmark_data.high[i])
                lows.append(self.benchmark_data.low[i])
        
        if len(closes) < MA_PERIOD:
            return
        
        close_series = np.array(closes)
        high_series = np.array(highs)
        low_series = np.array(lows)
        
        current_price = close_series[-1]
        ma = np.mean(close_series[-MA_PERIOD:])
        recent_high = np.max(high_series[-LOOKBACK_HIGH_LOW_DAYS:])
        recent_low = np.min(low_series[-LOOKBACK_HIGH_LOW_DAYS:])
        
        # 涔栫鐜?        bias = (current_price - ma) / ma if ma > 0 else 0
        
        # RSI
        current_rsi = calculate_rsi(close_series, period=14)
        
        # 妫€鏌ヨ繘鍏ラ渿鑽℃湡
        should_enter = False
        if ENABLE_BIAS_TRIGGER and bias > BIAS_THRESHOLD:
            should_enter = True
        if ENABLE_RSI_TRIGGER and current_rsi and self.previous_rsi:
            if self.previous_rsi > RSI_OVERBOUGHT and current_rsi < RSI_PULLBACK:
                should_enter = True
        
        # 妫€鏌ラ€€鍑洪渿鑽℃湡
        should_exit = False
        rise_from_low = (current_price - recent_low) / recent_low if recent_low > 0 else 0
        if ENABLE_LOW_POINT_RISE_TRIGGER and rise_from_low >= LOW_POINT_RISE_THRESHOLD:
            should_exit = True
        
        # 鏇存柊鐘舵€?        if should_enter and self.current_filter == '姝ｅ父鏈?:
            self.current_filter = '闇囪崱鏈?
            self.range_bound_start = self.last_date
            print(f"[{self.last_date}] 杩涘叆闇囪崱鏈燂紙楂樻柉婊ゆ尝鍣級")
        elif should_exit and self.current_filter == '闇囪崱鏈?:
            self.current_filter = '姝ｅ父鏈?
            print(f"[{self.last_date}] 閫€鍑洪渿鑽℃湡锛堟媺鏅媺鏂护娉㈠櫒锛?)
        
        self.previous_rsi = current_rsi


# ===========================================================
# 涓诲嚱鏁?# ===========================================================

def fetch_etf_data_with_westock(etf_code):
    """鐢╳estock-data鑾峰彇ETF鏁版嵁"""
    import subprocess
    import json
    
    print(f"姝ｅ湪鐢╳estock鑾峰彇 {etf_code} 鏁版嵁...")
    try:
        # 杞崲鑱氬浠ｇ爜鍒皐estock鏍煎紡
        if etf_code.startswith('51') or etf_code.startswith('50'):
            # 涓婃捣ETF
            ws_code = f"sh{etf_code}"
        elif etf_code.startswith('15') or etf_code.startswith('16'):
            # 娣卞湷ETF
            ws_code = f"sz{etf_code}"
        else:
            print(f"  鏃犳硶璇嗗埆鐨凟TF浠ｇ爜: {etf_code}")
            return None
        
        # 璋冪敤westock-data kline
        result = subprocess.run(
            ['npx', 'westock-data', 'kline', ws_code, '--limit', '1000'],
            capture_output=True, text=True, cwd=r'C:\Users\blakehao\.qclaw\workspace\skills\westock-data'
        )
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            if len(lines) < 2:
                return None
            
            # 瑙ｆ瀽CSV鏁版嵁
            from io import StringIO
            df = pd.read_csv(StringIO(result.stdout))
            
            # 鏍囧噯鍖栧垪鍚?            df.columns = [c.strip() for c in df.columns]
            df = df.rename(columns={
                '鏃ユ湡': 'date', '寮€鐩?: 'open', '鏀剁洏': 'close', 
                '鏈€楂?: 'high', '鏈€浣?: 'low', '鎴愪氦閲?: 'volume'
            })
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df = df.set_index('date')
            
            # 纭繚鍒楀瓨鍦?            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    df[col] = df.get('close', 0)
            
            return df
        else:
            print(f"  westock鑾峰彇澶辫触: {result.stderr}")
            return None
    except Exception as e:
        print(f"  鑾峰彇澶辫触: {e}")
        return None


def load_etf_data(etf_code):
    """鍔犺浇ETF鏁版嵁锛屾湰鍦版病鏈夊垯鐢╳estock鎷夊彇"""
    # 鏈湴璺緞
    csv_path = os.path.join(DATA_DIR, f"{etf_code}.csv")
    
    if os.path.exists(csv_path):
        print(f"鍔犺浇鏈湴鏁版嵁: {etf_code}")
        df = pd.read_csv(csv_path, parse_dates=['Date'], index_col='Date')
        return df
    else:
        # 鐢╳estock鎷夊彇
        df = fetch_etf_data_with_westock(etf_code)
        if df is not None:
            # 淇濆瓨鍒版湰鍦?            os.makedirs(DATA_DIR, exist_ok=True)
            df.to_csv(csv_path)
            print(f"  宸蹭繚瀛樺埌: {csv_path}")
            return df
        else:
            print(f"  鉁?{etf_code} 鏁版嵁鑾峰彇澶辫触")
            return None


def run_backtest():
    """杩愯鍥炴祴"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    
    # 娣诲姞绛栫暐
    cerebro.addstrategy(QixingLaplaceGaussian)
    
    # 鍔犺浇鏁版嵁
    loaded = 0
    for etf in ETF_POOL:
        df = load_etf_data(etf)
        if df is not None and len(df) > 100:
            data = bt.feeds.PandasData(
                dataname=df,
                name=etf,
                fromdate=datetime(2023, 1, 1),
                todate=datetime(2026, 5, 21)
            )
            cerebro.adddata(data)
            loaded += 1
    
    if loaded < 2:
        print("鏈夋晥ETF鏁版嵁涓嶈冻锛屽洖娴嬬粓姝?)
        return
    
    print(f"鎴愬姛鍔犺浇 {loaded} 鍙狤TF鏁版嵁")
    
    # 娣诲姞鍒嗘瀽鍣?    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print("\n寮€濮嬪洖娴?..")
    results = cerebro.run()
    strat = results[0]
    
    # 杈撳嚭缁撴灉
    print("\n" + "="*60)
    print("鍥炴祴缁撴灉")
    print("="*60)
    
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / INITIAL_CASH - 1) * 100
    
    print(f"鍒濆璧勯噾: ${INITIAL_CASH:,.2f}")
    print(f"鏈€缁堣祫浜? ${final_value:,.2f}")
    print(f"鎬绘敹鐩婄巼: {total_return:+.2f}%")
    
    # 骞村寲鏀剁泭
    returns = strat.analyzers.returns.get_analysis()
    if 'rtot' in returns:
        ann_return = (1 + returns['rtot']) ** (250 / len(strat.data)) - 1
        print(f"骞村寲鏀剁泭鐜? {ann_return*100:.2f}%")
    
    # 澶忔櫘
    sharpe = strat.analyzers.sharpe.get_analysis()
    if 'sharperatio' in sharpe:
        print(f"澶忔櫘姣旂巼: {sharpe['sharperatio']:.2f}")
    
    # 鏈€澶у洖鎾?    dd = strat.analyzers.drawdown.get_analysis()
    if 'max' in dd:
        print(f"鏈€澶у洖鎾? {dd['max']*100:.2f}%")
    
    # 浜ゆ槗缁熻
    trades = strat.analyzers.trades.get_analysis()
    if 'total' in trades and trades['total']['total'] > 0:
        total_trades = trades['total']['total']
        won = trades.get('won', {}).get('total', 0)
        lost = trades.get('lost', {}).get('total', 0)
        win_rate = won / total_trades * 100 if total_trades > 0 else 0
        
        # 鐩堜簭姣?        won_pnl = trades.get('won', {}).get('pnl', {}).get('total', 0)
        lost_pnl = trades.get('lost', {}).get('pnl', {}).get('total', 0)
        avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0)
        avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0)
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        print(f"\n浜ゆ槗缁熻:")
        print(f"  鎬讳氦鏄? {total_trades}")
        print(f"  鐩堝埄: {won}  浜忔崯: {lost}")
        print(f"  鑳滅巼: {win_rate:.1f}%")
        print(f"  鐩堜簭姣? {pl_ratio:.2f}")
        print(f"  骞冲潎鐩堝埄: ${avg_win:.2f}")
        print(f"  骞冲潎浜忔崯: ${avg_loss:.2f}")
    
    print("="*60)


if __name__ == '__main__':
    import sys
    run_backtest()
