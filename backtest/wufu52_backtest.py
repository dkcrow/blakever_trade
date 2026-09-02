#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五福52V2 策略回测 (日线近似)
================================================
基于聚宽"五福52V2-多ETF"策略, 用本地日线数据近似回测。

核心逻辑(日线可近似部分):
- 双池: 全球/海外池 + 中国池 (约110只)
- 动量评分: 25日加权对数回归 × R² (与QMT相同公式)
- 走弱期: 4指数至少3/4低于MA10 → 减仓(3只→2只) + 回避A股
- 多持仓: 正常期3只, 走弱期2只
- 相关性过滤: 60日收益相关 ≥ 0.85 跳过
- 防御: 无目标 → 货币基金511880

不可近似部分(分钟级, 本地无分钟数据):
- 分钟级固定止损 / 当日跌幅止损 / ATR移动止损
- 日内趋势复检 (13:10/13:40/14:10/14:40)
  以上用日线盈利保护5%近似替代止损

用法: python backtest/wufu52_backtest.py --start 2023-08-17 --end 2026-08-17 --cash 100000
"""
import sys, os, json, math, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, 'C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')

import numpy as np
import pandas as pd
from pathlib import Path

from strategies.etf.seven_star_base import LocalDataSource, Portfolio, DEFENSIVE_ETF as _DEF
from strategies.etf.seven_star_172 import BacktestEngine172
import strategies.etf.seven_star_172 as p172
import strategies.etf.seven_star_base as base_mod

STRATEGY_NAME = "五福52V2(日线近似)"
PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_wufu52'
os.makedirs(RESULTS_DIR, exist_ok=True)

# 防御ETF: 货币基金
DEFENSIVE_ETF = 'sh511880'


def jq_to_blake(code):
    parts = code.split('.')
    if len(parts) != 2:
        return None
    num, exchange = parts
    prefix = 'sh' if exchange == 'XSHG' else 'sz'
    return f'{prefix}{num}'


def extract_wufu_pool():
    """从五福52V2.py 提取有效ETF池(去注释、去指数)"""
    src = Path(PROJECT_ROOT / 'strategies/etf/五福52V2.py').read_text(encoding='utf-8')
    # 逐行处理, 去掉注释行(以 # 开头或行内 # 后内容)
    codes = set()
    for line in src.split('\n'):
        # 去掉行内注释
        code_part = line.split('#')[0]
        # 提取 XSHG/XSHE 代码
        for m in re.finditer(r"'(\d{6})\.X(SHG|SHE)'", code_part):
            codes.add(f"{m.group(1)}.{m.group(2)}")
    # 排除指数代码(走弱期判断用, 非ETF)
    index_codes = {'000001', '000300', '000510', '399001', '399006', '399101'}
    etf_codes = {c for c in codes if c.split('.')[0] not in index_codes}
    # 转换为 blake 格式
    pool = []
    for c in sorted(etf_codes):
        b = jq_to_blake(c)
        if b:
            pool.append(b)
    return pool


WUFU_POOL = extract_wufu_pool()
ALL_LOAD_CODES = list(set(WUFU_POOL + [DEFENSIVE_ETF]))
print(f"五福池提取: {len(WUFU_POOL)} 只ETF (含防御{len(ALL_LOAD_CODES)-len(WUFU_POOL)}只)")

# ================================================================
# 策略参数
# ================================================================
WUFU_PARAMS = {
    'lookback_days': 25,              # 动量回看天数
    'holdings_num': 3,                # 正常期持仓数
    'weak_holdings_num': 2,           # 走弱期持仓数
    'min_money': 500,
    'min_score_threshold': -999999,
    'max_score_threshold': 999999,

    # 走弱期判断 (复用QMT: 4指数至少3/4低于MA10)
    'enable_regime_switch': True,
    'enable_avoid_a_share': True,
    'weak_period_ma_lookback': 10,
    'weak_period_max_days': 20,
    'enable_intraday_drawdown': False,

    # 相关性过滤
    'enable_corr_filter': True,
    'corr_lookback_days': 60,
    'corr_threshold': 0.85,

    # 止损(日线近似: 盈利保护5%)
    'enable_profit_protection': True,
    'profit_protection_threshold': 0.05,

    # 关闭其他
    'enable_premium_filter': False,
    'use_short_momentum_filter': False,
    'enable_volume_check': False,
    'loss': 0.01,
    'enable_hs300_state_machine': False,
    'enable_panic_regime': False,
}


class Wufu52Backtest(BacktestEngine172):
    """五福52V2 日线近似回测引擎"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commission_rate = 0.0001  # 万分之一

    def _get_holdings_num(self):
        """动态持仓数: 走弱期2只, 正常期3只"""
        if self.engine.is_a_share_weak:
            return self.engine.params.get('weak_holdings_num', 2)
        return self.engine.params.get('holdings_num', 3)

    def run(self, start_date, end_date, initial_cash=100000):
        print("=" * 70)
        print(f"{STRATEGY_NAME} - 本地回测引擎")
        print(f"回测区间: {start_date} ~ {end_date} | 初始资金: {initial_cash:,.0f}")
        print(f"ETF池: {len(WUFU_POOL)}只 | 正常持仓3只/走弱2只 | 相关性过滤≥0.85")
        print("=" * 70)

        # monkey-patch ETF_POOL
        orig_pool = p172.ETF_POOL
        orig_base_pool = base_mod.ETF_POOL
        p172.ETF_POOL = ALL_LOAD_CODES
        base_mod.ETF_POOL = ALL_LOAD_CODES

        print("\n[1/4] 加载ETF历史数据...")
        all_etf_data = self.data_source.load_all_etfs(start_date, end_date, pool=ALL_LOAD_CODES)
        print(f"  成功加载 {len(all_etf_data)}/{len(ALL_LOAD_CODES)} 只ETF")

        nav_data = self.data_source.load_all_navs(pool=ALL_LOAD_CODES)
        self.engine.nav_data = nav_data

        # 加载监测指数(走弱期判断)
        self.engine.load_regime_indexes(self.data_source, start_date, end_date)

        if len(all_etf_data) == 0:
            print("[FATAL] 无可用数据!")
            return None

        trade_dates = self.data_source.get_trade_dates(start_date, end_date)
        print(f"  交易日数: {len(trade_dates)} 天")

        self.engine.reset_state()
        self.portfolio = Portfolio(
            initial_cash=initial_cash,
            commission_rate=self.commission_rate,
            min_commission=self.min_commission
        )

        print(f"\n[2/4] 开始逐日回测...")
        print("-" * 70)

        for i, td in enumerate(trade_dates):
            td_ts = pd.Timestamp(td)
            current_prices = {}
            for code, df in all_etf_data.items():
                mask = df.index <= td_ts
                if mask.any():
                    current_prices[code] = float(df.loc[mask, 'close'].iloc[-1])

            self.portfolio.update_prices(current_prices)
            self._log_positions(i, td)
            self.engine.reset_daily_blacklist()

            # 09:40 行情判断(走弱期)
            self.engine.check_regime(td)

            # 11:00 盈利保护检查
            self._run_profit_protection(current_prices, all_etf_data, td)

            # 13:10 卖出
            self._run_sell(current_prices, all_etf_data, td)

            # 13:11 买入
            self._run_buy(current_prices, all_etf_data, td)

            self.portfolio.record_daily_value(td)

        print("-" * 70)
        print(f"\n[3/4] 回测完成! 生成报告...")
        results = self._generate_results(trade_dates, initial_cash)
        self.results = results

        # 恢复
        p172.ETF_POOL = orig_pool
        base_mod.ETF_POOL = orig_base_pool
        return results

    def _compute_corr(self, code_a, code_b, all_etf_data, date):
        """计算两只ETF的60日收益相关"""
        lb = self.engine.params.get('corr_lookback_days', 60)
        df_a = all_etf_data.get(code_a)
        df_b = all_etf_data.get(code_b)
        if df_a is None or df_b is None:
            return None
        ts = pd.Timestamp(date)
        ha = df_a[df_a.index <= ts]['close'].tail(lb + 1)
        hb = df_b[df_b.index <= ts]['close'].tail(lb + 1)
        if len(ha) < lb * 0.7 or len(hb) < lb * 0.7:
            return None
        # 对齐索引
        common = ha.index.intersection(hb.index)
        if len(common) < 30:
            return None
        ra = ha.loc[common].pct_change().dropna()
        rb = hb.loc[common].pct_change().dropna()
        common2 = ra.index.intersection(rb.index)
        if len(common2) < 30:
            return None
        corr = ra.loc[common2].corr(rb.loc[common2])
        return corr

    def _run_sell(self, current_prices, all_etf_data, date):
        params = self.engine.params
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)
        holdings_num = self._get_holdings_num()

        # 目标: 动量前N + 相关性过滤
        target_etfs = self._select_targets(ranked, all_etf_data, current_prices, date, holdings_num)

        if not target_etfs:
            target_etfs = [DEFENSIVE_ETF]

        target_set = set(target_etfs)

        for sec in list(self.portfolio.get_position_codes()):
            if sec not in current_prices or current_prices[sec] <= 0:
                continue
            if sec == DEFENSIVE_ETF:
                # 防御ETF只在无真实目标时保留
                has_real = any(t != DEFENSIVE_ETF for t in target_etfs)
                if not has_real:
                    continue
            if sec not in target_set:
                if self.portfolio.sell_all(sec, current_prices[sec], date, reason='调出目标'):
                    print(f"  [{date}] 📤 SELL: {sec} @{current_prices[sec]:.3f}")

    def _select_targets(self, ranked, all_etf_data, current_prices, date, holdings_num):
        """动量前N + 相关性过滤"""
        params = self.engine.params
        active_pool = self.engine.get_active_pool(list(all_etf_data.keys()))

        selected = []
        for m in ranked:
            if len(selected) >= holdings_num:
                break
            etf = m['etf']
            if etf not in active_pool and etf != DEFENSIVE_ETF:
                continue
            # 相关性过滤
            if params.get('enable_corr_filter', False):
                skip = False
                for sel in selected:
                    corr = self._compute_corr(etf, sel, all_etf_data, date)
                    if corr is not None and abs(corr) >= params.get('corr_threshold', 0.85):
                        skip = True
                        break
                if skip:
                    continue
            selected.append(etf)
        return selected

    def _run_buy(self, current_prices, all_etf_data, date):
        params = self.engine.params
        ranked = self.engine.get_ranked_etfs(all_etf_data, current_prices, date)
        holdings_num = self._get_holdings_num()

        if ranked:
            tops = ", ".join([f"{m['etf']}({m['score']:.3f})" for m in ranked[:5]])
            print(f"  [{date}] 持仓数{holdings_num} TOP5: {tops}")

        target_etfs = self._select_targets(ranked, all_etf_data, current_prices, date, holdings_num)

        if not target_etfs:
            if DEFENSIVE_ETF in current_prices and current_prices[DEFENSIVE_ETF] > 0:
                target_etfs = [DEFENSIVE_ETF]
            else:
                return

        total_val = self.portfolio.total_value * 0.998
        target_per_etf = total_val / len(target_etfs)
        min_money = params['min_money']

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
                continue
            price = current_prices[etf]
            if diff > 0:
                target_amount = int(diff / price // 100) * 100
                if target_amount <= 0 and diff > min_money:
                    target_amount = 100
                if target_amount * price >= min_money:
                    if self.portfolio.buy(etf, target_amount, price, date, reason='买入'):
                        print(f"  [{date}] 📥 BUY: {etf} {target_amount}份@{price:.3f}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='五福52V2 日线近似回测')
    parser.add_argument('--start', type=str, default='2023-08-17')
    parser.add_argument('--end', type=str, default='2026-08-17')
    parser.add_argument('--cash', type=float, default=100000)
    args = parser.parse_args()

    data_dir = str(PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf')
    ds = LocalDataSource(data_dir)

    engine = Wufu52Backtest(ds, engine_params=WUFU_PARAMS)
    results = engine.run(args.start, args.end, args.cash)

    if results is None:
        print("回测失败!")
        return

    suffix = f"{args.start}_{args.end}"
    summary = {k: v for k, v in results.items() if k not in ('daily_values', 'trade_log', 'engine_params')}
    with open(RESULTS_DIR / f'wufu52_{suffix}_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    with open(RESULTS_DIR / f'wufu52_{suffix}_trades.json', 'w', encoding='utf-8') as f:
        json.dump(results.get('trade_log', []), f, ensure_ascii=False, indent=2, default=str)

    n_days = results.get('trading_days', 0)
    final_val = results.get('final_value', args.cash)
    total_ret = final_val / args.cash
    cagr = total_ret ** (252.0 / n_days) - 1 if n_days > 0 else 0

    print(f"\n{'=' * 70}")
    print(f"  五福52V2(日线近似) 回测完成")
    print(f"  累计收益: {(total_ret-1)*100:+.2f}% | 终值: ¥{final_val:,.0f}")
    print(f"  年化CAGR: {cagr*100:+.2f}%")
    print(f"  最大回撤: {results.get('max_drawdown_pct', 0):.2f}% | 夏普: {results.get('sharpe_ratio', 0):.4f}")
    print(f"  交易: {results.get('total_trades', 0)} | 胜率: {results.get('win_rate_pct', 0):.1f}%")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
