#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================
ETF双池平滑动量轮动 策略回测
==========================================================================
基于聚宽原版策略代码 (JoinQuant → 本地回测)

策略特点:
- 静态ETF池: 121只核心ETF (宽基/行业/跨境/商品等)
- 双均线过滤: close > MA20 AND MA20 > MA60
- 成交量放量过滤: 当日量/5日均量 > 2.5 → 过滤
- 动量评分: 加权对数回归 exp(slope*250)-1 × R² (与七星172一致)
- 得分范围: (0, 5)
- 止损: 成本价92%
- 防御ETF: 银华日利(511880)
- 佣金: 万分之一 (双边)
==========================================================================
"""

import sys, os, json, math, io
# 修复Windows控制台编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

from strategies.etf.seven_star_base import (
    LocalDataSource, Portfolio, EtfFilter
)
import strategies.etf.seven_star_base as base_mod
from strategies.etf.seven_star_172 import BacktestEngine172
import strategies.etf.seven_star_172 as p172  # 需要直接访问模块来替换ETF_POOL

# ================================================================
# 策略元数据
# ================================================================
STRATEGY_NAME = "ETF双池平滑动量轮动"
PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_dual_pool'
os.makedirs(RESULTS_DIR, exist_ok=True)

# ================================================================
# ETF池转换: JoinQuant → blakever_trade 格式
# ================================================================
STATIC_ETF_POOL_JQ = [
    "159206.XSHE", "159218.XSHE", "159227.XSHE", "159256.XSHE", "159323.XSHE",
    "159326.XSHE", "159363.XSHE", "159378.XSHE", "159502.XSHE", "159509.XSHE",
    "159516.XSHE", "159518.XSHE", "159529.XSHE", "159550.XSHE", "159566.XSHE",
    "159583.XSHE", "159605.XSHE", "159611.XSHE", "159637.XSHE", "159638.XSHE",
    "159667.XSHE", "159732.XSHE", "159755.XSHE", "159766.XSHE", "159819.XSHE",
    "159825.XSHE", "159840.XSHE", "159851.XSHE", "159852.XSHE", "159865.XSHE",
    "159869.XSHE", "159870.XSHE", "159883.XSHE", "159892.XSHE", "159915.XSHE",
    "159919.XSHE", "159922.XSHE", "159928.XSHE", "159949.XSHE", "159967.XSHE",
    "159980.XSHE", "159981.XSHE", "159985.XSHE", "159992.XSHE", "159995.XSHE",
    "159998.XSHE", "161226.XSHE", "501018.XSHG", "510050.XSHG", "510180.XSHG",
    "510300.XSHG", "510410.XSHG", "510500.XSHG", "510760.XSHG", "510880.XSHG",
    "510900.XSHG", "511260.XSHG", "511380.XSHG", "512000.XSHG", "512010.XSHG",
    "512050.XSHG", "512070.XSHG", "512100.XSHG", "512170.XSHG", "512200.XSHG",
    "512400.XSHG", "512480.XSHG", "512660.XSHG", "512670.XSHG", "512690.XSHG",
    "512710.XSHG", "512800.XSHG", "512880.XSHG", "512890.XSHG", "512980.XSHG",
    "513030.XSHG", "513050.XSHG", "513090.XSHG", "513100.XSHG", "513120.XSHG",
    "513130.XSHG", "513180.XSHG", "513190.XSHG", "513290.XSHG", "513300.XSHG",
    "513310.XSHG", "513330.XSHG", "513350.XSHG", "513360.XSHG", "513400.XSHG",
    "513500.XSHG", "513520.XSHG", "513630.XSHG", "513690.XSHG", "513750.XSHG",
    "513920.XSHG", "513970.XSHG", "515000.XSHG", "515030.XSHG", "515050.XSHG",
    "515120.XSHG", "515170.XSHG", "515210.XSHG", "515220.XSHG", "515250.XSHG",
    "515400.XSHG", "515650.XSHG", "515790.XSHG", "515880.XSHG", "515980.XSHG",
    "516010.XSHG", "516150.XSHG", "516160.XSHG", "516190.XSHG", "516510.XSHG",
    "516520.XSHG", "517520.XSHG", "518880.XSHG", "520830.XSHG", "560860.XSHG",
    "561330.XSHG", "561360.XSHG", "561980.XSHG", "562500.XSHG", "562590.XSHG",
    "562800.XSHG", "563300.XSHG", "588080.XSHG", "588120.XSHG", "588170.XSHG",
    "588200.XSHG", "588220.XSHG", "588790.XSHG"
]


def jq_to_blake(code):
    """转换聚宽代码格式: 159206.XSHE → sz159206, 510050.XSHG → sh510050"""
    parts = code.split('.')
    if len(parts) != 2:
        return code
    num, exchange = parts
    prefix = 'sh' if exchange == 'XSHG' else 'sz'
    return f'{prefix}{num}'


DUAL_POOL_ETF = [jq_to_blake(c) for c in STATIC_ETF_POOL_JQ]
DEFENSIVE_ETF = 'sh511880'

# 确保防御ETF在数据池中 (策略池 + 防御ETF)
ALL_LOAD_CODES = list(set(DUAL_POOL_ETF + [DEFENSIVE_ETF]))

# 名称映射 (简单使用代码作为名称, 实际回测中从已有映射获取)
DUAL_POOL_NAMES = {}
for c in STATIC_ETF_POOL_JQ:
    blake_code = jq_to_blake(c)
    DUAL_POOL_NAMES[blake_code] = blake_code  # 占位, 后续用get_security_name获取

# ================================================================
# 策略参数
# ================================================================
DUAL_POOL_PARAMS = {
    # ---- 核心参数 ----
    'lookback_days': 25,              # 动量回看天数
    'holdings_num': 1,                # 持仓数量
    'min_money': 500,                 # 最小交易金额

    # ---- 双均线过滤 ----
    'enable_ma_filter': True,
    'ma_short': 20,
    'ma_long': 60,

    # ---- 成交量放量过滤 ----
    'enable_volume_check': True,
    'volume_lookback': 5,
    'volume_threshold': 2.5,

    # ---- 止损 ----
    'stop_loss_ratio': 0.92,

    # ---- 得分范围 ----
    'min_score_threshold': -999999,   # 不设下限 (去除(0,5)限制)
    'max_score_threshold': 999999,    # 不设上限 (去除(0,5)限制)

    # ---- 关闭七星172特有过滤器 ----
    'enable_profit_protection': False,
    'use_short_momentum_filter': False,
    'short_lookback_days': 10,          # 短期动量回看天数 (get_ranked_etfs需要, 即使过滤关闭)
    'enable_premium_filter': False,
    'enable_regime_switch': False,
    'enable_avoid_a_share': False,
    'enable_intraday_drawdown': False,
    'loss': 0.01,                     # 保留但关闭(七星参数)
}


# ================================================================
# 自定义过滤器: 双池策略专属
# ================================================================

class DualPoolFilter(EtfFilter):
    """
    ETF双池平滑动量轮动 过滤器

    过滤层级:
    1. 双均线过滤: close > MA20 AND MA20 > MA60
    2. 成交量放量过滤: 当日量/5日均量 > 2.5 → 过滤
    3. 得分范围: 0 < score < 5 (在评分阶段完成，此处不做)
    """
    name = "DualPool"

    def check(self, code, current_price, hist_df, date, params, nav_series=None):
        reasons = []
        close_arr = hist_df['close'].values

        # ---- 第1层: 双均线过滤 ----
        if params.get('enable_ma_filter', True):
            ma_short = params.get('ma_short', 20)
            ma_long = params.get('ma_long', 60)
            if len(close_arr) >= ma_long:
                ma_s = np.mean(close_arr[-ma_short:])
                ma_l = np.mean(close_arr[-ma_long:])
                if not (close_arr[-1] > ma_s and ma_s > ma_l):
                    reasons.append('双均线过滤')
            else:
                reasons.append(f'数据不足(需{ma_long}日)')

        # ---- 第2层: 成交量放量过滤 (当日量远超5日均量 → 过滤) ----
        if params.get('enable_volume_check', False):
            if 'volume' in hist_df.columns:
                vols = hist_df['volume'].values
                v_lookback = params.get('volume_lookback', 5)
                v_threshold = params.get('volume_threshold', 2.5)
                if len(vols) > v_lookback:
                    today_vol = vols[-1]
                    avg_vol = np.mean(vols[-(v_lookback + 1):-1])
                    if avg_vol > 0 and today_vol / avg_vol > v_threshold:
                        reasons.append(f'成交量放量({today_vol / avg_vol:.1f}x)')

        return len(reasons) > 0, reasons


# ================================================================
# 自定义回测引擎: 继承BacktestEngine172, 覆盖交易逻辑
# ================================================================

class DualPoolBacktest(BacktestEngine172):
    """双池策略回测引擎 - 覆盖买卖逻辑以适配止损和防御模式"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commission_rate = 0.0001  # 万分之一 (策略指定)

    def run(self, start_date, end_date, initial_cash=100000):
        """
        执行完整回测 (覆盖父类以使用双池ETF池)
        """
        print("=" * 70)
        print(f"{STRATEGY_NAME} - 本地回测引擎")
        print(f"回测区间: {start_date} ~ {end_date} | 初始资金: {initial_cash:,.0f}")
        print(f"佣金费率: {self.commission_rate*100:.3f}% (双边) | ETF池: {len(DUAL_POOL_ETF)}只")
        print("=" * 70)

        # 替换ETF_POOL (get_ranked_etfs在seven_star_172模块中使用ETF_POOL)
        p172_original_pool = p172.ETF_POOL
        p172_original_names = p172.ETF_NAMES
        p172.ETF_POOL = ALL_LOAD_CODES
        # 也替换base模块 (避免其他引用)
        base_original_pool = base_mod.ETF_POOL
        base_mod.ETF_POOL = ALL_LOAD_CODES

        # [1] 加载数据 (传入双池ETF列表 + 防御ETF)
        print("\n[1/4] 加载ETF历史数据...")
        all_etf_data = self.data_source.load_all_etfs(start_date, end_date, pool=ALL_LOAD_CODES)
        print(f"  成功加载 {len(all_etf_data)}/{len(ALL_LOAD_CODES)} 只ETF")

        # 净值数据
        nav_data = self.data_source.load_all_navs(pool=ALL_LOAD_CODES)
        self.engine.nav_data = nav_data
        nav_count = len(nav_data)
        print(f"  净值数据: {nav_count}/{len(ALL_LOAD_CODES)} 只ETF (溢价率过滤关闭)")

        # 监测指数数据 (行情判断关闭, 仅加载)
        self.engine.regime_indexes_data = {}

        if len(all_etf_data) == 0:
            print("[FATAL] 无可用数据!")
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

            # ===== 13:09 卖出操作 (止损/放量/调仓) =====
            self._run_sell(current_prices, all_etf_data, td)

            # ===== 13:10 买入操作 =====
            self._run_buy(current_prices, all_etf_data, td)

            # 记录每日净值
            self.portfolio.record_daily_value(td)

        print("-" * 70)

        # [4] 生成报告
        print(f"\n[3/4] 回测完成! 生成报告...")
        results = self._generate_results(trade_dates, initial_cash)
        self.results = results

        # 恢复原始ETF池
        p172.ETF_POOL = p172_original_pool
        p172.ETF_NAMES = p172_original_names
        base_mod.ETF_POOL = base_original_pool

        return results

    def _run_sell(self, current_prices, all_etf_data, date):
        """
        卖出操作 (13:09):
        1. 固定比例止损: 现价 <= 成本 * 0.92
        2. 成交量放量卖出: 持仓标的大幅放量 → 卖出
        3. 调仓卖出: 不在新目标列表 → 卖出 (防御ETF除外)
        """
        params = self.engine.params
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)

        # 确定今日目标: 必须与 _run_buy 使用相同逻辑, 遍历全部排名
        target_etfs = []
        for m in ranked:
            if len(target_etfs) >= params['holdings_num']:
                break
            if params.get('min_score_threshold', 0) < m['score'] < params.get('max_score_threshold', 5):
                target_etfs.append(m['etf'])

        if not target_etfs:
            target_etfs = [DEFENSIVE_ETF]

        target_set = set(target_etfs)

        held = list(self.portfolio.get_position_codes())
        if not held:
            return

        for sec in held:
            if sec not in current_prices or current_prices[sec] <= 0:
                continue

            pos = self.portfolio.positions.get(sec)
            if pos is None or pos['shares'] <= 0:
                continue

            cur_price = current_prices[sec]
            cost_price = pos.get('cost_price', cur_price)

            # ---- 1. 止损检查 ----
            if cur_price <= cost_price * params.get('stop_loss_ratio', 0.92):
                loss_pct = (cur_price / cost_price - 1) * 100
                if self.portfolio.sell_all(sec, cur_price, date, reason=f'止损({loss_pct:.1f}%)'):
                    print(f"  [{date}] 🚨 STOP: {sec} @{cur_price:.3f} 成本{cost_price:.3f} 亏损{loss_pct:.2f}%")
                continue

            # ---- 2. 放量卖出 ----
            if params.get('enable_volume_check', False):
                hist_df = all_etf_data.get(sec)
                if hist_df is not None and 'volume' in hist_df.columns:
                    vols = hist_df['volume'].values
                    v_lb = params.get('volume_lookback', 5)
                    v_th = params.get('volume_threshold', 2.5)
                    if len(vols) > v_lb:
                        avg_vol = np.mean(vols[-(v_lb + 1):-1])
                        if avg_vol > 0 and vols[-1] / avg_vol > v_th:
                            if self.portfolio.sell_all(sec, cur_price, date, reason='放量卖出'):
                                print(f"  [{date}] 📊 VOL_SELL: {sec} @{cur_price:.3f} 量比{vols[-1]/avg_vol:.2f}")
                            continue

            # ---- 3. 不在目标列表 ----
            if sec not in target_set:
                # 防御ETF仅在无动量目标时保留; 有目标时卖出以释放资金
                has_real_targets = any(t != DEFENSIVE_ETF for t in target_etfs)
                if sec == DEFENSIVE_ETF and not has_real_targets:
                    continue
                if self.portfolio.sell_all(sec, cur_price, date, reason='调出目标'):
                    print(f"  [{date}] 📤 SELL: {sec} @{cur_price:.3f}")

    def _run_buy(self, current_prices, all_etf_data, date):
        """
        买入操作 (13:10):
        - 有动量目标 → 等权买入
        - 无动量目标 → 买入防御ETF (银华日利)
        """
        params = self.engine.params
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)

        # 确定目标 (得分范围 0<score<5)
        target_etfs = []
        for m in ranked:
            if len(target_etfs) >= params['holdings_num']:
                break
            if params.get('min_score_threshold', 0) < m['score'] < params.get('max_score_threshold', 5):
                target_etfs.append(m['etf'])

        # 打印前5名
        if ranked:
            tops = ", ".join([f"{m['etf']}({m['score']:.4f})" for m in ranked[:5]])
            print(f"  [{date}] TOP5: {tops}")

        # 防御模式: 无目标时买入防御ETF
        if not target_etfs:
            if DEFENSIVE_ETF in current_prices and current_prices[DEFENSIVE_ETF] > 0:
                target_etfs = [DEFENSIVE_ETF]
                print(f"  [{date}] 🛡️ DEFENSE -> {DEFENSIVE_ETF}")
            else:
                print(f"  [{date}] ⚠️ 无目标且防御ETF不可交易")
                return

        total_val = self.portfolio.total_value
        target_per_etf = total_val / len(target_etfs)
        min_money = params['min_money']

        for etf in target_etfs:
            if etf not in current_prices or current_prices[etf] <= 0:
                continue

            price = current_prices[etf]

            if etf in self.portfolio.positions:
                pos = self.portfolio.positions[etf]
                if pos['shares'] > 0:
                    current_val = pos['shares'] * price
                    diff = target_per_etf - current_val
                    # 5%容差, 不调仓
                    if abs(diff) < target_per_etf * 0.05:
                        continue
                    if diff > 0:
                        target_amount = int(diff / price // 100) * 100
                        if target_amount * price >= min_money:
                            if self.portfolio.buy(etf, target_amount, price, date, reason='再平衡'):
                                print(f"  [{date}] ⚖️ REBAL: {etf} {target_amount}份@{price:.3f}")
            else:
                target_amount = int(target_per_etf / price // 100) * 100
                if target_amount == 0 and target_per_etf >= price * 100:
                    target_amount = 100
                if target_amount * price >= min_money:
                    if self.portfolio.buy(etf, target_amount, price, date, reason=f'排名{target_etfs.index(etf)+1}'):
                        print(f"  [{date}] 📥 BUY: {etf} {target_amount}份@{price:.3f}")

    def _generate_results(self, trade_dates, initial_cash):
        """生成回测结果 (覆盖策略名称)"""
        results = super()._generate_results(trade_dates, initial_cash)
        if results:
            results['strategy'] = STRATEGY_NAME
        return results


# ================================================================
# 🏃 主入口
# ================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description=f'{STRATEGY_NAME} 回测')
    parser.add_argument('--start', type=str, default='2025-01-01', help='回测起始日期')
    parser.add_argument('--end', type=str, default='2026-06-03', help='回测结束日期')
    parser.add_argument('--cash', type=float, default=100000, help='初始资金')
    parser.add_argument('--holdings', type=int, default=1, help='持仓数量')

    args = parser.parse_args()

    # 修改参数
    params = DUAL_POOL_PARAMS.copy()
    params['holdings_num'] = args.holdings

    # 数据源
    data_dir = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
    ds = LocalDataSource(data_dir)

    # 过滤器
    etf_filter = DualPoolFilter()

    # 回测引擎
    engine = DualPoolBacktest(ds, engine_params=params, etf_filter=etf_filter)

    # 执行回测
    results = engine.run(args.start, args.end, args.cash)

    if results is None:
        print("\n回测失败!")
        return None

    # 保存结果
    suffix = f"{args.start}_{args.end}"

    # 摘要
    summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
    summary_path = RESULTS_DIR / f'dual_pool_{suffix}_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n摘要: {summary_path}")

    # 每日净值
    dv_path = RESULTS_DIR / f'dual_pool_{suffix}_daily.json'
    with open(dv_path, 'w', encoding='utf-8') as f:
        json.dump(results.get('daily_values', []), f, ensure_ascii=False, indent=2, default=str)
    print(f"净值: {dv_path}")

    # 交易记录
    trades_path = RESULTS_DIR / f'dual_pool_{suffix}_trades.json'
    with open(trades_path, 'w', encoding='utf-8') as f:
        json.dump(results.get('trade_log', []), f, ensure_ascii=False, indent=2, default=str)
    print(f"交易: {trades_path}")

    # 参数
    params_path = RESULTS_DIR / f'dual_pool_{suffix}_params.json'
    with open(params_path, 'w', encoding='utf-8') as f:
        json.dump(params, f, ensure_ascii=False, indent=2, default=str)
    print(f"参数: {params_path}")

    return results


if __name__ == '__main__':
    main()
