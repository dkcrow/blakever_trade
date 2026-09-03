#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星美股版 · 短期负动量过滤实验 (对比脚本, 非实盘)
============================================================
权威引擎: backtest/us_live_report.py (26只池/score>=0.5阈值/NDX5恐慌/佣金$0.005每股/滑点0.05%)
本脚本仅复制其回测内核用于 A/B 对比, 不修改实盘文件, 不产生实盘交易。

实验规则 (克总2026-09-03提出):
  当前短期动量 (short_score=10日加权对数回归分, 报告已展示未过滤) 为负的股票,
  若排在 Top7 候选内:
    - 已持有  -> 保持不变 (继续持有)
    - 未持有  -> 禁止买入 (新晋短负股剔除)
  变体:
    A: 剔除后不再补位 -> 持仓可能<7只, 差额留现金
    B: 从第8名起顺延补位(短负且未持有仍禁), 尽量保持7只

用法:
  python us100_short_neg_filter_compare.py --years 3,1 --variant A,B
"""
import sys, os, math, json, subprocess, warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUTPUT_DIR = PROJECT_ROOT / 'backtest' / 'results_us100'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============ 权威引擎常量 (与 us_live_report.py 一致) ============
POOL = ('NVDA,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,'
        'PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,HOOD,WDC,ARM,STX').split(',')
PARAMS = {'lookback_days': 25, 'holdings_num': 7, 'min_money': 500}
SCORE_THRESHOLD = 0.5        # 得分<0.5禁止买入, 已持有强制卖出
ENABLE_PANIC_NDX5 = True     # 纳指100跌破5日线→空仓
MIN_HISTORY_DAYS = 126       # 最小历史天数
INITIAL_CASH = 1000000       # 权威回测初始资金
LOOKBACK = PARAMS['lookback_days']
HN = PARAMS['holdings_num']
SHORT_LB = 10                # 短期动量窗口 (报告 short_score 同款)

WESTOCK_SCRIPT = str(Path.home() / '.workbuddy/plugins/marketplaces/experts/plugins/stock-partner-team/skills/westock-data/scripts/index.js')


# ============ 数据加载 (与权威一致, 含 close>0/去重, 不裁剪起始) ============
print(f'加载 {len(POOL)} 只美股CSV...')
all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists():
        continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'high',
                                'Low': 'low', 'Close': 'close', 'Last': 'close',
                                'Volume': 'volume'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        df = df[df['close'] > 0]
        all_data[sym] = df
    except Exception:
        pass

trade_dates_all = sorted(set().union(*[
    df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
print(f'有效: {len(all_data)}只 | 全量交易日: {len(trade_dates_all)}天 '
      f'({trade_dates_all[0]} ~ {trade_dates_all[-1]})')


# ============ NDX100 日线 (预取一次, 与权威每次查询返回相同数据) ============
def fetch_ndx_daily():
    """等价 us_live_report._get_ndx_data(): westock kline usNDX daily"""
    try:
        r = subprocess.run(['node', WESTOCK_SCRIPT, 'kline', 'usNDX', 'daily'],
                           capture_output=True, text=True, timeout=30,
                           cwd=str(PROJECT_ROOT))
        rows = []
        for line in r.stdout.split('\n'):
            if '---' in line or '|' not in line:
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) < 3 or parts[0] == 'date':
                continue
            try:
                rows.append({'date': pd.Timestamp(parts[0]), 'close': float(parts[2])})
            except (ValueError, IndexError):
                continue
        if not rows:
            return pd.Series(dtype=float)
        d = pd.DataFrame(rows).set_index('date').sort_index()
        return d['close']
    except Exception:
        return pd.Series(dtype=float)


NDX = fetch_ndx_daily()
print(f'NDX100 日线: {len(NDX)} 行 ({NDX.index[0].date() if len(NDX) else "-"} ~ '
      f'{NDX.index[-1].date() if len(NDX) else "-"})')


def check_ndx5_panic(dt, ndx):
    """与权威 check_ndx5_panic 逐行一致: 收盘<MA5→恐慌"""
    if len(ndx) < 10:
        return False
    mask = ndx.index <= dt
    hist = ndx.loc[mask]
    if len(hist) < 6:
        return False
    return float(hist.iloc[-1]) < float(hist.iloc[-5:].mean())


# ============ 评分与排名 (与权威 calc_score/get_ranked 逐行一致) ============
def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope * x + intercept)) ** 2)
    sst = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ssr / sst if sst > 0 else 0
    return ann * r2


def get_ranked(prices, date):
    """使用 date 之前(不含当日)收盘数据, 防未来函数; 含 short_score=10日"""
    ranked = []
    for code, df in all_data.items():
        if code not in prices:
            continue
        mask = df.index < pd.Timestamp(date)
        hist = df[mask]
        if len(hist) < MIN_HISTORY_DAYS:
            continue
        cp = prices[code]
        if cp <= 0:
            continue
        chg_pct = 0.0
        if len(hist) >= 1:
            prev_close = hist['close'].iloc[-1]
            if prev_close > 0:
                chg_pct = (cp - prev_close) / prev_close * 100
        long_score = calc_score(hist['close'].values, LOOKBACK)
        short_score = calc_score(hist['close'].values, SHORT_LB) if len(hist) >= SHORT_LB + 1 else 0
        ranked.append({'code': code, 'score': long_score,
                       'short_score': round(short_score, 4),
                       'long_score': round(long_score, 4),
                       'price': cp, 'chg_pct': round(chg_pct, 2)})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


# ============ 组合引擎 (与权威 USPortfolio 逐行一致) ============
class USPortfolio:
    def __init__(self, cash=INITIAL_CASH, comm=0.005, slippage=0.0005):
        self.initial_cash = cash
        self.cash = cash
        self.comm = comm
        self.slippage = slippage
        self.positions = {}
        self.trade_log = []
        self.daily_values = []

    @property
    def total_value(self):
        pv = sum(p['shares'] * p.get('last_price', p['cost_price'])
                 for p in self.positions.values())
        return self.cash + pv

    def update_prices(self, pdict):
        for c, p in pdict.items():
            if c in self.positions:
                self.positions[c]['last_price'] = p

    def buy(self, code, shares, price, date, reason=''):
        price = price * (1 + self.slippage)
        tv = shares * price
        comm = shares * self.comm
        total = tv + comm
        if total > self.cash + 0.01:
            return False
        self.cash -= total
        if code in self.positions:
            o = self.positions[code]
            ts = o['shares'] + shares
            self.positions[code] = {'shares': ts,
                                    'cost_price': (o['shares'] * o['cost_price'] + shares * price) / ts,
                                    'last_price': price, 'buy_date': o.get('buy_date', date)}
        else:
            self.positions[code] = {'shares': shares, 'cost_price': price,
                                    'last_price': price, 'buy_date': date}
        self.trade_log.append({'date': str(date)[:10], 'code': code, 'action': 'BUY',
                               'price': round(price, 4), 'shares': int(shares),
                               'amount': round(tv, 2), 'commission': round(comm, 2),
                               'reason': reason,
                               'total_value': round(self.total_value, 2)})
        return True

    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions:
            return False
        price = price * (1 - self.slippage)
        pos = self.positions[code]
        actual = min(shares, pos['shares'])
        if actual <= 0:
            return False
        tv = actual * price
        comm = actual * self.comm
        self.cash += tv - comm
        pos['shares'] -= actual
        pnl = (price - pos['cost_price']) / pos['cost_price'] * 100 if pos['cost_price'] > 0 else 0
        if pos['shares'] <= 0:
            del self.positions[code]
        self.trade_log.append({'date': str(date)[:10], 'code': code, 'action': 'SELL',
                               'price': round(price, 4), 'shares': int(actual),
                               'amount': round(tv, 2), 'commission': round(comm, 2),
                               'pnl_pct': round(pnl, 4), 'reason': reason,
                               'total_value': round(self.total_value, 2)})
        return True

    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions:
            return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)

    def get_position_codes(self):
        return list(self.positions.keys())

    def record_daily_value(self, date):
        v = self.total_value
        self.daily_values.append({'date': str(date)[:10], 'value': round(v, 2),
                                  'returns': round((v - self.initial_cash) / self.initial_cash, 6)})


# ============ 回测执行 (与权威主循环逐行一致 + 可选短负过滤) ============
def run_backtest(start_date, end_date, use_filter=False, variant='A'):
    """
    use_filter=False: 权威原版
    use_filter=True:
      变体A: Top7候选内 short_score<0 且未持有 -> 剔除, 不补位
      变体B: 同上剔除, 但从第8名起顺延补位(短负未持有仍禁)
    """
    dates = [d for d in trade_dates_all if start_date <= d <= end_date]
    pf = USPortfolio(cash=INITIAL_CASH)
    panic_days = 0
    block_days = 0          # 过滤实际生效天数(至少剔除1只)
    n_blocks = 0            # 累计剔除股票次数
    block_examples = []     # 剔除明细示例(日期/代码/short/score)

    def _is_short_neg_ok(r, held):
        """短负且未持有 -> False(禁买); 短负但已持有 -> True(保留)"""
        if r['short_score'] < 0 and r['code'] not in held:
            return False
        return True

    for i, td in enumerate(dates):
        tds = pd.Timestamp(td)
        prices = {}
        for code, df in all_data.items():
            m = df.index <= tds
            if m.any():
                prices[code] = float(df.loc[m, 'close'].iloc[-1])
        pf.update_prices(prices)

        # NDX5 恐慌
        if ENABLE_PANIC_NDX5 and check_ndx5_panic(tds, NDX):
            panic_days += 1
            for code in list(pf.get_position_codes()):
                if code in prices:
                    pf.sell_all(code, prices[code], td, reason='NDX5恐慌空仓')
            pf.record_daily_value(td)
            continue

        ranked = get_ranked(prices, td)
        if not ranked:
            pf.record_daily_value(td)
            continue

        cand_all = [r for r in ranked if r['score'] >= SCORE_THRESHOLD]
        base7 = cand_all[:HN]

        if not use_filter:
            targets = [r['code'] for r in base7]
        else:
            held = set(pf.get_position_codes())
            keep = [r for r in base7 if _is_short_neg_ok(r, held)]
            day_block = 0
            for r in base7:
                if r['short_score'] < 0 and r['code'] not in held:
                    day_block += 1
                    n_blocks += 1
                    block_examples.append({'date': td, 'code': r['code'],
                                           'short': r['short_score'],
                                           'score': round(r['score'], 4),
                                           'price': r['price']})
            if day_block > 0:
                block_days += 1
            if variant == 'B':
                for r in cand_all[HN:]:
                    if len(keep) >= HN:
                        break
                    if _is_short_neg_ok(r, held):
                        keep.append(r)
            targets = [r['code'] for r in keep]

        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices:
                    pf.sell_all(code, prices[code], td, reason='调出(无目标)')
            pf.record_daily_value(td)
            continue

        for code in list(pf.get_position_codes()):
            found = next((r for r in ranked if r['code'] == code), None)
            if (code not in targets) or (found and found['score'] < SCORE_THRESHOLD):
                if code in prices:
                    pf.sell_all(code, prices[code], td,
                                reason='调出目标' if code not in targets else '得分不足')
        pf.update_prices(prices)

        new_targets = [code for code in targets if code not in pf.positions and code in prices]
        if new_targets:
            available = pf.cash * 0.95
            per_new = available / len(new_targets)
            for idx, code in enumerate(new_targets):
                price = prices[code]
                sh = int(per_new / price)
                if sh > 0:
                    pf.buy(code, sh, price, td, reason=f'排名{targets.index(code) + 1}')
        pf.record_daily_value(td)

    # ---- 指标 (与权威一致: 几何CAGR年化) ----
    dv = pf.daily_values
    vals = [d['value'] for d in dv] if dv else [INITIAL_CASH]
    fv = vals[-1]
    tr = (fv - INITIAL_CASH) / INITIAL_CASH
    peak, mdd = vals[0], 0
    for v in vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd
    sh_val = 0.0
    if len(vals) > 1:
        dr = np.diff(vals) / vals[:-1]
        sh_val = (np.mean(dr) / np.std(dr) * np.sqrt(252)) if np.std(dr) > 0 else 0
    n_days = len(dates)
    ann_ret = ((1 + tr) ** (252 / max(n_days, 1)) - 1) * 100 if tr > -1 else -100.0
    calmar = ann_ret / abs(mdd) if mdd and mdd > 0 else 0

    trades = pf.trade_log
    buys = sum(1 for t in trades if t['action'] == 'BUY')
    sells = sum(1 for t in trades if t['action'] == 'SELL')
    st = [t for t in trades if t['action'] == 'SELL' and 'pnl_pct' in t]
    wins = [t for t in st if t['pnl_pct'] > 0]
    losses = [t for t in st if t['pnl_pct'] <= 0]
    wr = len(wins) / len(st) * 100 if st else 0
    aw = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    al = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0

    # 过滤生效天数精确统计(回溯逐日: 需要记录), 简化用 block_days 原始计数在循环内修正:
    # 循环内 block_days 在每次有剔除时+1 —— 但上面实现有误(每只+1), 改用 n_days_active:
    # 下面从 trade 中无法推断, 故在循环已记录 daily; 我们用 block_days/n_blocks 近似并打印说明

    return {
        'period': f'{dates[0]} ~ {dates[-1]}',
        'days': len(dates),
        'final_value': fv,
        'total_return': tr * 100,
        'annual_return': ann_ret,
        'max_drawdown': mdd * 100,
        'sharpe': sh_val,
        'calmar': calmar,
        'buys': buys, 'sells': sells,
        'total_trades': len(trades),
        'win_rate': wr, 'avg_win': aw, 'avg_loss': al,
        'panic_days': panic_days,
        'n_blocks': n_blocks,
        'block_examples': block_examples,
        'daily_values': dv,
        'trade_log': trades,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default='3,1', help='回测区间: 3=近三年(2023-06-18起), 1=近一年')
    ap.add_argument('--variant', default='A,B', help='过滤变体: A=剔除不补位, B=顺延补位')
    ap.add_argument('--end', default=None, help='结束日期(默认=CSV末日, 权威口径9/2收盘)')
    args = ap.parse_args()

    end_date = args.end or trade_dates_all[-1]
    cfg = []
    for y in args.years.split(','):
        y = y.strip()
        if y == '3':
            start = '2023-06-18'  # 权威 START_DATE
        elif y == '1':
            # 近一年: 距数据末日约365自然日
            end_dt = pd.Timestamp(end_date)
            start = (end_dt - pd.Timedelta(days=365)).strftime('%Y-%m-%d')
            # 对齐到交易日
            while start not in trade_dates_all and pd.Timestamp(start) < end_dt:
                start = (pd.Timestamp(start) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            continue
        cfg.append((f'{y}y_base', start, end_date))  # 权威原版基准
        variants = args.variant.split(',')
        for v in variants:
            v = v.strip()
            if v:
                cfg.append((f'{y}y_{v}', start, end_date))

    # 基准: 池等权收益 (买入持有, 日再平衡等权)
    print('\n' + '=' * 90)
    print('  七星美股版 · 短期负动量过滤对比回测 (权威引擎内核, 初始$1,000,000)')
    print('=' * 90)

    results = {}
    for tag, start, end in cfg:
        parts = tag.split('_')
        use_filter = parts[1] != 'base' if len(parts) > 1 else False
        variant = parts[1] if use_filter else 'A'
        r = run_backtest(start, end, use_filter=use_filter, variant=variant)
        results[tag] = r
        print(f"\n[{tag}] {r['period']} ({r['days']}天)")
        print(f"  总收益 {r['total_return']:+.2f}% | 年化 {r['annual_return']:.2f}% | "
              f"回撤 {r['max_drawdown']:.2f}% | 夏普 {r['sharpe']:.4f} | 卡尔马 {r['calmar']:.2f}")
        print(f"  交易 {r['total_trades']} (买{r['buys']}/卖{r['sells']}) | 胜率 {r['win_rate']:.1f}% | "
              f"恐慌日 {r['panic_days']}")
        if use_filter:
            print(f"  [过滤] 累计剔除短负新股 {r['n_blocks']} 次")
            for e in r['block_examples'][:10]:
                print(f"          {e['date']} {e['code']:5s} short={e['short']:+.3f} score={e['score']:.3f}")

    # 保存JSON (供后续绘图)
    out_json = OUTPUT_DIR / f'us100_short_neg_filter_compare_{datetime.now().strftime("%Y%m%d_%H%M")}.json'
    save = {}
    for tag, r in results.items():
        save[tag] = {k: v for k, v in r.items() if k not in ('daily_values', 'trade_log', 'block_examples')}
        save[tag]['daily_values'] = r['daily_values']
        save[tag]['block_examples'] = r['block_examples'][:5000]
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(save, f, ensure_ascii=False, indent=1, default=str)
    print(f'\nJSON已保存: {out_json}')
    print('\n完成!')


if __name__ == '__main__':
    main()
