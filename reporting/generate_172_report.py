#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星172盘后报告 V3 - 含自动交易检查与同步

每次发送前:
1. 计算ETF排名 + 短期/长期得分 + 涨跌幅
2. 对比持仓, 自动执行买卖并同步到交易记录表
3. 生成HTML邮件发送
"""

import os, sys, math, json, warnings, urllib.request
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from copy import deepcopy
warnings.filterwarnings('ignore')

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.etf.seven_star_base import (
    LocalDataSource, ETF_POOL, ETF_NAMES, DEFENSIVE_ETF, DEFAULT_NAV_DIR
)

HISTORY_FILE = Path(__file__).parent / '172_ranking_history.json'
TRADES_XLSX = Path(__file__).parent.parent / 'backtest' / 'results_172' / '七星172_交易记录_2026.xlsx'


def get_latest_trading_date():
    """动态计算最新交易日（跳过周末）"""
    today = datetime.now()
    if today.weekday() == 5:      # 周六 → 周五
        today = today - timedelta(days=1)
    elif today.weekday() == 6:    # 周日 → 周五
        today = today - timedelta(days=2)
    return today.strftime('%Y-%m-%d')


LATEST_DATE = get_latest_trading_date()


# ================================================================
# 实时行情获取（盘中价格替换CSV收盘价）
# ================================================================

def fetch_realtime_prices(codes):
    """
    通过新浪实时行情接口获取ETF最新价和涨跌幅。
    仅支持A股ETF（sh/sz开头），返回 {code: {'price': float, 'change_pct': float}}
    """
    import urllib.request
    import re

    realtime = {}
    # 过滤A股ETF
    a_codes = [c for c in codes if c.startswith('sh') or c.startswith('sz')]
    if not a_codes:
        return realtime

    # 新浪接口每次最多请求约 50 只
    batch_size = 50
    for i in range(0, len(a_codes), batch_size):
        batch = a_codes[i:i + batch_size]
        url = f'http://hq.sinajs.cn/list={",".join(batch)}'

        try:
            req = urllib.request.Request(url, headers={
                'Referer': 'https://finance.sina.com.cn'
            })
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')

            # 解析每行: var hq_str_sh513100="名称,今开,昨收,当前价,最高,最低,..."
            for line in raw.strip().split('\n'):
                m = re.search(r'hq_str_(\w+)=\"(.*)\"', line)
                if not m:
                    continue
                code_key = m.group(1)  # sh513100 或 sz159915
                fields = m.group(2).split(',')
                if len(fields) < 4:
                    continue

                # 新浪ETF字段: 0=名称, 1=今开, 2=昨收, 3=当前(最新)价
                try:
                    cur_price = float(fields[3])
                    prev_close = float(fields[2])
                    if cur_price > 0 and prev_close > 0:
                        change_pct = (cur_price - prev_close) / prev_close * 100
                        realtime[code_key] = {
                            'price': cur_price,
                            'change_pct': round(change_pct, 2)
                        }
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            pass  # 静默失败，降级到CSV价格

    return realtime


# ================================================================
# 排名计算
# ================================================================

def compute_scores(close_full, lookback):
    """计算给定周期的动量得分 (年化收益 × R²)"""
    recent = close_full[-(lookback + 1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y))
    w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann_ret = math.exp(slope * 250) - 1
    ss_res = np.sum(w * (y - (slope * x + intercept)) ** 2)
    ss_tot = np.sum(w * (y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return ann_ret * r2, ann_ret


def check_profit_protection(code, cur_price, hist_df, date, lookback=1, threshold=0.05):
    """盈利保护检查"""
    try:
        mask = hist_df.index < pd.Timestamp(date)
        hist_before = hist_df[mask]
        if len(hist_before) >= lookback:
            max_h = hist_before['high'].tail(lookback).max()
            return max_h > 0 and cur_price <= max_h * (1 - threshold)
    except:
        pass
    return False


# ================================================================
# 溢价率过滤 + 净值加载
# ================================================================

def load_nav_data():
    """加载所有ETF净值数据"""
    navs = {}
    nav_dir = DEFAULT_NAV_DIR
    if not nav_dir.exists():
        return navs
    for f in nav_dir.glob('*_nav.csv'):
        code = f.stem.replace('_nav', '')
        try:
            df = pd.read_csv(f, encoding='utf-8')
            if '净值日期' in df.columns and '单位净值' in df.columns:
                df = df.rename(columns={'净值日期': 'date', '单位净值': 'unit_nav'})
            if 'date' not in df.columns or 'unit_nav' not in df.columns:
                continue
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date', 'unit_nav'])
            df = df.set_index('date').sort_index()
            navs[code] = df['unit_nav']
        except Exception:
            pass
    return navs


def check_premium(code, cur_price, nav_data, check_date, threshold=0.20):
    """溢价率检查：当前价格 vs 前一日净值，超过20%则过滤"""
    if code not in nav_data:
        return False
    nav_series = nav_data[code]
    check_ts = pd.Timestamp(check_date)
    mask = nav_series.index < check_ts
    available = nav_series[mask]
    if len(available) == 0:
        return False
    recent = available.tail(5)
    net_value = float(recent.iloc[-1])
    if net_value <= 0:
        return False
    premium = (cur_price - net_value) / net_value
    return premium > threshold


def get_current_rankings():
    """获取最新交易日ETF完整排名（价格优先使用实时行情，含溢价率过滤）"""
    ds = LocalDataSource()
    all_data = ds.load_all_etfs('2026-01-01', LATEST_DATE)

    # 加载净值数据（用于溢价率过滤）
    nav_data = load_nav_data()
    print(f"  [NAV] Loaded {len(nav_data)} ETF net values")

    # 获取实时行情
    print("  [RT] Fetching realtime prices...")
    realtime = fetch_realtime_prices(ETF_POOL)
    realtime_count = len(realtime)
    print(f"  [RT] Got {realtime_count}/{len(ETF_POOL)} realtime quotes")

    current_prices = {}
    prev_prices = {}
    for code, df in all_data.items():
        mask = df.index <= pd.Timestamp(LATEST_DATE)
        if mask.any():
            # 优先使用实时价格
            if code in realtime:
                current_prices[code] = realtime[code]['price']
            else:
                current_prices[code] = float(df.loc[mask, 'close'].iloc[-1])
            closes = df.loc[mask, 'close']
            prev_prices[code] = float(closes.iloc[-2]) if len(closes) >= 2 else current_prices[code]

    prev_rankings = load_previous_rankings()
    prev_rank_map = {r['code']: r['rank'] for r in prev_rankings}

    ranked = []
    for code in ETF_POOL:
        df = all_data.get(code)
        if df is None:
            continue
        mask = df.index <= pd.Timestamp(LATEST_DATE)
        hist = df[mask]
        if len(hist) < 25:
            continue
        close_arr = hist['close'].values
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        close_full = np.append(close_arr, cur)

        # 长期得分 (25日)
        long_score, ann_ret_l = compute_scores(close_full, 25)
        # 短期得分 (10日)
        short_score, _ = compute_scores(close_full, 10) if len(close_full) >= 11 else (0, 0)

        # 盈利保护
        protected = check_profit_protection(code, cur, df, LATEST_DATE)

        # 溢价率过滤（当前价 vs 前一日净值，超过20%过滤）
        premium_filtered = check_premium(code, cur, nav_data, LATEST_DATE)

        # 计算实际溢价率（用于展示）
        premium_pct = 0.0
        if code in nav_data:
            nav_series = nav_data[code]
            check_ts = pd.Timestamp(LATEST_DATE)
            mask = nav_series.index < check_ts
            available = nav_series[mask]
            if len(available) > 0:
                net_value = float(available.iloc[-1])
                if net_value > 0:
                    premium_pct = round((cur - net_value) / net_value * 100, 2)

        # 近3日跌幅
        drop3 = False
        if len(close_full) >= 4:
            d = [close_full[-1]/close_full[-2], close_full[-2]/close_full[-3], close_full[-3]/close_full[-4]]
            drop3 = min(d) < 0.97

        # 涨跌幅（有实时价格时用实时涨跌幅）
        if code in realtime and 'change_pct' in realtime[code]:
            change_pct = realtime[code]['change_pct']
        else:
            prev = prev_prices.get(code, cur)
            change_pct = (cur - prev) / prev * 100 if prev > 0 else 0

        ranked.append({
            'code': code,
            'name': ETF_NAMES.get(code, code),
            'score': round(long_score, 4),
            'short_score': round(short_score, 4),
            'long_score': round(long_score, 4),
            'price': round(cur, 4),
            'change_pct': round(change_pct, 2),
            'short_mom_annual': round(ann_ret_l, 8),  # 用于过滤判断
            'protected': protected,
            'drop3': drop3,
            'premium_filtered': premium_filtered,
            'premium_pct': premium_pct,
            'filtered': protected or premium_filtered or drop3 or short_score < 0,
            'prev_rank': prev_rank_map.get(code, None),
            'hist_df': df,  # 暂存用于后续成交量检查
        })

    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked, current_prices


def load_previous_rankings():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('rankings', [])
        except:
            pass
    return []


def get_display_order(ranked):
    """
    返回显示排序：有效ETF按得分降序 + 被过滤的ETF排在末尾
    """
    valid = [r for r in ranked if not r['filtered']]
    blocked = [r for r in ranked if r['filtered']]
    result = list(valid)
    for i, r in enumerate(blocked):
        r['rank'] = len(valid) + i + 1
        result.append(r)
    return result


def save_rankings(ranked):
    """保存排名历史（按显示顺序）"""
    display_order = get_display_order(ranked)
    data = {
        'date': LATEST_DATE,
        'generated': datetime.now().isoformat(),
        'rankings': [{'code': r['code'], 'rank': i+1, 'score': r['score']}
                      for i, r in enumerate(display_order)]
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================================================================
# 交易检查与同步
# ================================================================

def get_holding_from_xlsx():
    """从交易记录xlsx中获取当前持仓"""
    if not TRADES_XLSX.exists():
        return None
    df = pd.read_excel(TRADES_XLSX)
    # 从后往前找最后一条买入
    for _, row in df.iloc[::-1].iterrows():
        if row.get('方向') == '买入':
            return {
                'code': row.get('ETF代码', ''),
                'name': row.get('ETF名称', ''),
                'price': row.get('成交价格', 0),
                'date': row.get('交易日期', ''),
            }
    return None


def pick_trade_target(ranked):
    """从排名中选出实际交易目标 (应用过滤)"""
    for r in ranked:
        if not r['filtered']:
            return r
    return None


def append_trade_to_xlsx(direction, code, name, price, date, score, reason):
    """追加一条交易记录到xlsx"""
    if TRADES_XLSX.exists():
        df = pd.read_excel(TRADES_XLSX)
    else:
        df = pd.DataFrame(columns=['交易日期','ETF名称','ETF代码','方向','成交价格','综合动量得分','交易理由'])

    new_row = {
        '交易日期': str(date),
        'ETF名称': name,
        'ETF代码': code,
        '方向': direction,
        '成交价格': round(price, 4),
        '综合动量得分': round(score, 4) if isinstance(score, (int, float)) else score,
        '交易理由': reason,
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_excel(TRADES_XLSX, index=False)


def check_and_execute_trades(ranked):
    """
    根据排名检查是否需要换仓，如果需要则记录到交易表
    返回: (是否发生了交易, trade_description)
    """
    # 全局检查: 同一天内如果已在之前时间点换仓，不再重复换仓
    if TRADES_XLSX.exists():
        df_check = pd.read_excel(TRADES_XLSX)
        today_trades = df_check[df_check['交易日期'] == str(LATEST_DATE)]
        if len(today_trades) > 0:
            directions = today_trades['方向'].tolist()
            return False, f"今日已有换仓操作({', '.join(directions)})，跳过重复执行"

    holding = get_holding_from_xlsx()
    target = pick_trade_target(ranked)

    if target is None:
        return False, "无合格标的"

    if holding is None:
        # 首次买入
        append_trade_to_xlsx(
            '买入', target['code'], target['name'],
            target['price'], LATEST_DATE, target['score'],
            f"动量排名第1/{len(ETF_POOL)}"
        )
        return True, f"初始买入: {target['name']}({target['code']})@{target['price']:.4f}"

    # 检查是否需要换仓
    if holding['code'] == target['code']:
        return False, f"持仓不变: {holding['name']} 仍是排名第一"

    # 需要换仓: 先卖后买
    # 检查是否同一天已有操作(避免重复)
    if TRADES_XLSX.exists():
        df = pd.read_excel(TRADES_XLSX)
        today_trades = df[df['交易日期'] == str(LATEST_DATE)]
        for _, row in today_trades.iterrows():
            if row.get('方向') == '卖出' and row.get('ETF代码') == holding['code']:
                return False, f"今日已卖出 {holding['name']}，跳过"

    # 卖出旧持仓
    old_score = 'N/A'
    sell_price = target['price']  # 默认用目标价格
    # 尝试从排名中获取旧持仓的实际价格和得分
    old_ranked = next((r for r in ranked if r['code'] == holding['code']), None)
    if old_ranked:
        old_score = old_ranked['score']
        sell_price = old_ranked['price']  # 用旧持仓的实际价格

    # 构造真实的卖出理由
    sell_reason = '调出目标(排名下降)'
    if old_ranked:
        if old_ranked.get('filtered'):
            # 被过滤，找出具体原因
            reasons = []
            if old_ranked.get('protected'):
                reasons.append(f"盈利保护(回撤超5%)")
            if old_ranked.get('premium_filtered'):
                reasons.append(f"溢价率>20%过滤")
            if old_ranked.get('drop3'):
                reasons.append(f"近3日跌幅>3%")
            if old_ranked.get('short_score', 0) < 0:
                reasons.append(f"短期动量负({old_ranked['short_score']:.2f})")
            sell_reason = '; '.join(reasons) if reasons else '被过滤规则排除'
        elif old_ranked.get('prev_rank') is not None:
            sell_reason = f"排名从{old_ranked['prev_rank']}→新第1不等,调出"

    append_trade_to_xlsx(
        '卖出', holding['code'], holding['name'],
        sell_price, LATEST_DATE, old_score,
        sell_reason
    )

    # 买入新品种
    append_trade_to_xlsx(
        '买入', target['code'], target['name'],
        target['price'], LATEST_DATE, target['score'],
        f"动量排名第1/{len(ETF_POOL)}"
    )

    return True, (f"换仓: 卖出 {holding['name']} → 买入 {target['name']}"
                  f"({target['code']})@{target['price']:.4f}")


# ================================================================
# 获取交易记录
# ================================================================

def get_recent_trades(ranked=None):
    """获取最近20条交易记录 (时间倒序: 最新在最前, 同日买入在卖出前)"""
    if not TRADES_XLSX.exists():
        return []
    df = pd.read_excel(TRADES_XLSX)
    # 补充方向排序键: 同一天买入在卖出之前 (买入时间更晚, 倒序中应排前面)
    df['_dir_order'] = df['方向'].apply(lambda x: 0 if x == '买入' else 1)
    # 按日期倒序, 同日买入优先, 取最近20条
    df = df.sort_values(['交易日期', '_dir_order'], ascending=[False, True]).head(20)
    df = df.drop(columns=['_dir_order'])
    records = df.to_dict('records')

    # 构建当前排名得分映射 (用于补充历史 N/A)
    score_map = {}
    if ranked:
        for r in ranked:
            score_map[r['code']] = r['score']

    # 修复 nan 得分 + 修正理由中的分母
    for r in records:
        score = r.get('综合动量得分', '')
        need_fix = False
        try:
            if score is None:
                need_fix = True
            elif isinstance(score, float) and np.isnan(score):
                need_fix = True
            elif isinstance(score, float) and np.isinf(score):
                need_fix = True
        except:
            need_fix = True

        if need_fix:
            code = r.get('ETF代码', '')
            if code in score_map:
                r['综合动量得分'] = round(score_map[code], 4)
            else:
                r['综合动量得分'] = 'N/A'

        # 修正历史记录中不固定的分母 -> 统一为 38
        reason = str(r.get('交易理由', ''))
        if reason and '动量排名第1/' in reason:
            import re
            reason = re.sub(r'动量排名第1/\d+', f'动量排名第1/{len(ETF_POOL)}', reason)
            r['交易理由'] = reason

    # 计算盈亏: 匹配买入→卖出对
    compute_trade_pnl(records)

    return records


def compute_trade_pnl(records):
    """为每条卖出记录计算买入→卖出的盈亏百分比"""
    if not records:
        return
    # records 是倒序的(最新在前), 需要正序遍历才能匹配买入→卖出
    # 构建买入队列: dict[code] = list of (index, price)
    buy_queue = {}
    for i in range(len(records) - 1, -1, -1):  # 从旧到新遍历
        r = records[i]
        code = r.get('ETF代码', '')
        direction = r.get('方向', '')
        price = r.get('成交价格', 0)
        try:
            price = float(price)
        except:
            price = 0

        if direction == '买入':
            if code not in buy_queue:
                buy_queue[code] = []
            buy_queue[code].append(price)
            r['_pnl'] = '-'
        elif direction == '卖出':
            if code in buy_queue and buy_queue[code]:
                buy_price = buy_queue[code].pop(0)
                if buy_price > 0 and price > 0:
                    pnl = (price - buy_price) / buy_price * 100
                    r['_pnl'] = f'{pnl:+.2f}%'
                else:
                    r['_pnl'] = '-'
            else:
                r['_pnl'] = '-'

    # 清理: 确保所有记录都有 _pnl
    for r in records:
        if '_pnl' not in r:
            r['_pnl'] = '-'


# ================================================================
# 格式化工具
# ================================================================

def fmt_rank_change(prev_rank, current_rank):
    if prev_rank is None:
        return '-'
    diff = prev_rank - current_rank
    if diff > 0:
        return f'↑{diff}'
    elif diff < 0:
        return f'↓{abs(diff)}'
    return '-'

def fmt_change_pct(pct):
    if abs(pct) < 0.005:
        return '0.00%'
    return f'{pct:+.2f}%'

def fmt_score(val):
    """格式化得分，处理 N/A 和 nan"""
    if isinstance(val, str):
        return val
    if val is None:
        return 'N/A'
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return 'N/A'
    except:
        return 'N/A'
    try:
        if np.isnan(val) or np.isinf(val):
            return 'N/A'
    except:
        pass
    return f'{val:.4f}'


# ================================================================
# 生成报告
# ================================================================

def generate_report(ranked, recent_trades, trade_info):
    """生成Markdown + HTML"""
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M')

    # 当前持仓
    current_holding = get_holding_from_xlsx()
    holding_code = current_holding['code'] if current_holding else ''

    # 构建展示排名：
    # - 得分前十中不被过滤的 ETF → 正常排名 1~N
    # - 得分前十但被过滤的 ETF → 从第11名顺排，变动列显示原因
    top10_by_score = ranked[:10]
    valid_in_top10 = [r for r in top10_by_score if not r['filtered']]
    filtered_in_top10 = [r for r in top10_by_score if r['filtered']]

    # 从得分前十以外补足到10只有效ETF
    rest_valid = [r for r in ranked if not r['filtered'] and r not in valid_in_top10]
    need = 10 - len(valid_in_top10)
    valid_in_top10.extend(rest_valid[:need])

    # 有效ETF：正常排名和变动
    for i, r in enumerate(valid_in_top10):
        r['rank'] = i + 1
        r['rchange'] = fmt_rank_change(r.get('prev_rank'), r['rank'])

    # 被过滤ETF：从第11名顺排，变动显示具体原因
    for i, r in enumerate(filtered_in_top10):
        r['rank'] = 11 + i
        reasons = []
        if r.get('premium_filtered'): reasons.append(f'溢价>{r.get("premium_pct",0):.0f}%')
        if r.get('protected'): reasons.append('盈利保护')
        if r.get('drop3'): reasons.append('近3日跌>3%')
        if r.get('short_score', 0) < 0: reasons.append('短期动量负')
        r['rchange'] = '/'.join(reasons) if reasons else '过滤'

    # 合并为展示列表
    top10 = valid_in_top10 + filtered_in_top10

    # ---- Markdown ----
    if current_holding:
        hline = f"- **当前持仓**: {current_holding['name']}({current_holding['code']})@{current_holding['price']} 买入于 {current_holding['date']}"
    else:
        hline = "- **当前持仓**: 无"

    top10_md = ""
    for r in top10:
        prem = f"{r.get('premium_pct', 0):.1f}%" if r.get('premium_pct') else '-'
        top10_md += (f"| {r['rank']} | {r['name']} | {r['code']} | {r['score']} "
                     f"| {r['short_score']} | {r['long_score']} "
                     f"| {r['price']} | {fmt_change_pct(r['change_pct'])} | {prem} | {r['rchange']} |\n")

    trade_md = ""
    for t in recent_trades:
        price_raw = t.get('成交价格', '')
        try: price_str = f'{float(price_raw):.3f}'
        except: price_str = str(price_raw)
        trade_md += (f"| {t.get('交易日期','')} | {t.get('方向','')} | {t.get('ETF名称','')} "
                     f"| {t.get('ETF代码','')} | {price_str} "
                     f"| {fmt_score(t.get('综合动量得分'))} | {t.get('交易理由','')} "
                     f"| {t.get('_pnl','-')} |\n")

    trade_note = ""
    if trade_info[0]:  # 发生了交易
        trade_note = f"\n### ⚡ 本次交易\n{trade_info[1]}\n"

    md = f"""# 七星172盘后报告 - {now_str}

## 策略概况
- **策略名称**: 七星172 (GLM5修复版)
- **ETF池**: 38只 | **周期**: 25日 | **佣金**: 0.02%
{hline}
{trade_note}
## ETF动量排名 Top 10

| 排名 | 名称 | 代码 | 综合得分 | 短期得分 | 长期得分 | 价格 | 涨跌幅 | 溢价率 | 变动 |
|------|------|------|----------|----------|----------|------|--------|--------|------|
{top10_md}
## 最近20条交易记录

| 日期 | 方向 | ETF名称 | ETF代码 | 价格 | 动量得分 | 理由 | 盈亏 |
|------|------|----------|----------|------|----------|------|------|
{trade_md}
## 说明
- **综合得分** = 长期得分(25日动量×R²), 用于排名
- **短期得分** = 10日动量×R², <0过滤
- **涨跌幅** = (当日收盘-前日收盘)/前日收盘
- **变动** = 与上次报告对比 ↑升 ↓降 -不变
- **过滤规则**: 盈利保护(回撤>5%) → 成交量放量 → 短期动量(<0) → 近3日跌幅(>3%)

## 时间
- 报告生成: {now_str} | 数据截止: {LATEST_DATE} | 引擎: 七星172 (GLM5修复版)

---
*本报告仅供研究参考，不构成投资建议。*
"""

    # ---- HTML ----
    holding_html = ""
    if current_holding:
        holding_html = f"""
        <div style="background:#FFF3CD;padding:10px 15px;border-radius:6px;margin:15px 0;font-size:13px;">
            📌 <b>当前持仓:</b> {current_holding['name']} ({current_holding['code']})
            买入价: {current_holding['price']} | 买入日: {current_holding['date']}
        </div>"""

    trade_alert = ""
    if trade_info[0]:
        trade_alert = f"""
        <div style="background:#D4EDDA;padding:10px 15px;border-radius:6px;margin:10px 0;font-size:13px;border-left:4px solid #28A745;">
            ⚡ <b>交易信号:</b> {trade_info[1]}
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>七星172盘后报告</title></head>
<body style="font-family:'Microsoft YaHei',sans-serif;max-width:880px;margin:0 auto;padding:20px;background:#f8f9fa;">

<div style="text-align:center;margin-bottom:20px;">
    <h1 style="font-size:22px;color:#1F4E79;margin:0 0 5px 0;">🚀 七星172策略 · 盘后报告</h1>
    <p style="font-size:12px;color:#888;margin:0;">{now_str} (Asia/Shanghai) | 数据截止: {LATEST_DATE}</p>
</div>

<div style="background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:12px;font-size:13px;">
    <b>策略:</b> 七星172 (GLM5修复版) | <b>ETF池:</b> 38只 | <b>周期:</b> 25日 | <b>佣金:</b> 0.02%
</div>
{holding_html}
{trade_alert}

<!-- ETF排名 Top10 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">📊 ETF动量排名 Top 10</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 6px;text-align:center;">排名</th>
            <th nowrap style="padding:6px 6px;text-align:left;">名称</th>
            <th nowrap style="padding:6px 6px;text-align:center;">代码</th>
            <th nowrap style="padding:6px 6px;text-align:right;">综合</th>
            <th nowrap style="padding:6px 6px;text-align:right;">短期</th>
            <th nowrap style="padding:6px 6px;text-align:right;">长期</th>
            <th nowrap style="padding:6px 6px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 6px;text-align:right;">涨跌幅</th>
            <th nowrap style="padding:6px 6px;text-align:right;">溢价率</th>
            <th nowrap style="padding:6px 6px;text-align:center;">变动</th>
        </tr>"""

    for r in top10:
        is_hold = r['code'] == holding_code
        bg = '#FEF9E7' if is_hold else ('#FFF' if r['rank'] % 2 == 0 else '#F8F9FA')
        chg = fmt_change_pct(r['change_pct'])
        chg_c = '#DC3545' if r['change_pct'] < -0.005 else ('#28A745' if r['change_pct'] > 0.005 else '#888')
        rc = r['rchange']
        # 变动列颜色：过滤原因显示为红色，正常变动按方向着色
        if '保护' in rc or '溢价' in rc or '跌' in rc or '动量负' in rc or '过滤' in rc:
            rc_c = '#DC3545'
        elif '↑' in rc:
            rc_c = '#28A745'
        elif '↓' in rc:
            rc_c = '#DC3545'
        else:
            rc_c = '#888'
        sc_c = '#28A745' if r['score'] > 0 else '#DC3545'
        prem = r.get('premium_pct', 0)
        prem_str = f'{prem:.1f}%' if prem else '-'
        prem_c = '#DC3545' if prem > 20 else ('#E65100' if prem > 10 else '#888')

        html += f"""
        <tr style="background:{bg};white-space:nowrap;">
            <td style="padding:4px 6px;text-align:center;font-weight:bold;">{r['rank']}</td>
            <td style="padding:4px 6px;">{r['name']}</td>
            <td style="padding:4px 6px;text-align:center;color:#888;font-size:11px;">{r['code']}</td>
            <td style="padding:4px 6px;text-align:right;font-weight:bold;color:{sc_c};">{r['score']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;">{r['short_score']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;">{r['long_score']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;">{r['price']:.4f}</td>
            <td style="padding:4px 6px;text-align:right;color:{chg_c};font-weight:bold;">{chg}</td>
            <td style="padding:4px 6px;text-align:right;color:{prem_c};font-weight:bold;">{prem_str}</td>
            <td style="padding:4px 6px;text-align:center;color:{rc_c};font-weight:bold;">{rc}</td>
        </tr>"""

    html += """
    </table>
</div>

<!-- 最近20条交易 -->
<div style="background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;">
    <h3 style="font-size:15px;color:#1F4E79;margin:0 0 10px 0;">📈 最近20条交易记录</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <tr style="background:#1F4E79;color:#fff;">
            <th nowrap style="padding:6px 8px;">日期</th>
            <th nowrap style="padding:6px 8px;">方向</th>
            <th nowrap style="padding:6px 8px;">ETF</th>
            <th nowrap style="padding:6px 8px;">代码</th>
            <th nowrap style="padding:6px 8px;text-align:right;">价格</th>
            <th nowrap style="padding:6px 8px;text-align:right;">得分</th>
            <th nowrap style="padding:6px 8px;text-align:left;">理由</th>
            <th nowrap style="padding:6px 8px;text-align:right;">盈亏</th>
        </tr>"""

    for i, t in enumerate(recent_trades):
        direction = t.get('方向', '')
        pnl = t.get('_pnl', '-')
        # 统一配色: 买入浅绿 / 卖出浅橙
        bg = '#E2EFDA' if direction == '买入' else '#FCE4D6'
        # 盈亏颜色
        if pnl.startswith('+'):
            pnl_c = '#28A745'
        elif pnl.startswith('-') and pnl != '-':
            pnl_c = '#DC3545'
        else:
            pnl_c = '#888'

        price_raw = t.get('成交价格', '')
        try: price_str = f'{float(price_raw):.3f}'
        except: price_str = str(price_raw)

        html += f"""
        <tr style="background:{bg};white-space:nowrap;">
            <td style="padding:4px 8px;">{t.get('交易日期','')}</td>
            <td style="padding:4px 8px;font-weight:bold;">{direction}</td>
            <td style="padding:4px 8px;">{t.get('ETF名称','')}</td>
            <td style="padding:4px 8px;color:#888;font-size:11px;">{t.get('ETF代码','')}</td>
            <td style="padding:4px 8px;text-align:right;">{price_str}</td>
            <td style="padding:4px 8px;text-align:right;">{fmt_score(t.get('综合动量得分'))}</td>
            <td style="padding:4px 8px;font-size:11px;color:#555;max-width:200px;overflow:hidden;text-overflow:ellipsis;">{t.get('交易理由','')}</td>
            <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pnl_c};">{pnl}</td>
        </tr>"""

    html += f"""
    </table>
</div>

<div style="font-size:11px;color:#888;line-height:1.6;margin-bottom:15px;">
    <b>过滤规则:</b> 溢价率>20% → 盈利保护(回撤>5%) → 短期动量(<0) → 近3日跌幅(>3%)<br>
    <b>得分:</b> 综合=长期(25日动量×R²) | 短期=10日动量×R² (<0过滤)<br>
    <b>溢价率:</b> (当前价-前日净值)/前日净值 | 红色>20%触发过滤 | ✗=被过滤未交易
</div>

<div style="text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;">
    七星172策略 · Blakever Trade · {now_str}<br>
    本报告仅供研究参考，不构成投资建议。
</div>
</body></html>"""

    return md, html


# ================================================================
# 发送邮件
# ================================================================

def send_report_email(html_content, md_path):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    SMTP_SERVER, SMTP_PORT = "smtp.qq.com", 465
    SENDER = "848786642@qq.com"
    PASSWORD = "ljbtvacrctjobfed"
    RECEIVER = "848786642@qq.com"

    now = datetime.now()
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"⚡ 核心交易 七星172盘中监控 - {now.strftime('%Y-%m-%d %H:%M')}"
    msg["From"] = SENDER
    msg["To"] = RECEIVER
    msg["Date"] = now.strftime("%a, %d %b %Y %H:%M:%S +0800")
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    if os.path.exists(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            att = MIMEText(f.read(), "plain", "utf-8")
            att.add_header("Content-Disposition", "attachment", filename=os.path.basename(md_path))
            msg.attach(att)

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as srv:
            srv.login(SENDER, PASSWORD)
            srv.sendmail(SENDER, RECEIVER, msg.as_string())
        print(f"✅ 邮件已发送至 {RECEIVER}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False


# ================================================================
# 🏃 主入口
# ================================================================

def main():
    print("=" * 60)
    print("七星172盘后报告生成器 V3")
    print("=" * 60)

    # 1. 排名
    print("\n[1/5] 计算ETF动量排名...")
    ranked, prices = get_current_rankings()
    print(f"  {len(ranked)} 只有效, Top3:")
    for r in ranked[:3]:
        flag = '[FILT]' if r['filtered'] else '[OK]'
        print(f"    {r['name']:16s} score={r['score']:.4f}  short={r['short_score']:.4f}  "
              f"chg={fmt_change_pct(r['change_pct'])}  {flag}")

    # 2. 交易检查
    print("\n[2/5] 检查交易信号...")
    traded, trade_desc = check_and_execute_trades(ranked)
    if traded:
        print(f"  ⚡ 已执行: {trade_desc}")
    else:
        print(f"  ℹ️ {trade_desc}")

    # 3. 交易记录
    print("\n[3/5] 获取最近交易记录...")
    recent_trades = get_recent_trades(ranked)
    print(f"  {len(recent_trades)} 条 (时间倒序)")

    # 4. 生成报告
    print("\n[4/5] 生成报告...")
    output_dir = Path(__file__).parent.parent / 'reporting' / 'template'
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / '七星172报告模板.md'
    html_path = output_dir / f'七星172报告_{datetime.now().strftime("%Y%m%d_%H%M")}.html'

    md_content, html_content = generate_report(ranked, recent_trades, (traded, trade_desc))
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"  ✅ {md_path.name}")
    print(f"  ✅ {html_path.name}")

    # 5. 发送 + 保存历史
    print("\n[5/5] 发送邮件 + 保存排名历史...")
    success = send_report_email(html_content, str(md_path))
    save_rankings(ranked)

    print("\n" + "=" * 60)
    print("📊 摘要")
    print("=" * 60)
    h = get_holding_from_xlsx()
    if h:
        print(f"  当前持仓: {h['name']}({h['code']}) @{h['price']}")
    print(f"  交易信号: {'⚡ ' + trade_desc if traded else '无'}")
    print(f"  邮件: {'✅ 已发送' if success else '❌ 失败'}")
    print("=" * 60)


if __name__ == '__main__':
    main()
