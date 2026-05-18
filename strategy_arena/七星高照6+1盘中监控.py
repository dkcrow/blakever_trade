#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照6+1 A股盘中实时监控 — 定时任务脚本
==========================================
策略名称：七星高照6+1 盘中监控
策略版本：V1.0

功能：
  1. 每30分钟检查一次6+1 ETF池的动量评分排名
  2. 显示所有候选ETF的当日检测结果和买入排名
  3. 检测第一名是否被替代
  4. 如果第一名被替代，发送邮件通知（用于实盘买卖操作）
  5. 工作日9:30-15:00期间执行

数据源：/data/workspace/back_trader_stocks/a/ 本地CSV日频数据
"""

import os, sys, json, math, time, smtplib, warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')

# ================================================================
# 🌟 6+1 ETF池定义（与七星高照6+1.py一致）
# ================================================================
INVEST_POOL = [
    '159915_XSHE',   # 创业板ETF
    '513100_XSHG',   # 纳指ETF
    '159985_XSHE',   # 豆粕ETF
    '518880_XSHG',   # 黄金ETF
    '501018_XSHG',   # 南方原油LOF
'161226_XSHE',   # 白银LOF
]

SAFE_POOL = [
    '511220_XSHG',   # 城投ETF
]

CN_ETF_POOL = list(dict.fromkeys(INVEST_POOL + SAFE_POOL))

CN_SAFE = list(SAFE_POOL)

CN_ETF_NAMES = {
    '159915_XSHE': '创业板ETF',
    '513100_XSHG': '纳指ETF',
    '159985_XSHE': '豆粕ETF',
    '518880_XSHG': '黄金ETF',
    '501018_XSHG': '南方原油LOF',
'161226_XSHE': '国投白银LOF',
    '511220_XSHG': '城投ETF',
}

STRATEGY_NAME = '七星高照6+1'

# ================================================================
# 策略参数（与主脚本一致）
# ================================================================
SHORT_LOOKBACK = 25
LONG_LOOKBACK = 250
DROP_THRESHOLD = 0.95
LONG_SCORE_CAP = 0.5
SHORT_SCORE_CAP = 6.0

# ================================================================
# 数据与状态路径
# ================================================================
DATA_DIR = '/data/workspace/back_trader_stocks/a'
MONITOR_STATE_FILE = '/data/workspace/strategy_arena/qixing_intraday_monitor_state.json'
MONITOR_LOG_DIR = '/data/workspace/strategy_arena/qixing_intraday_logs'

# ================================================================
# 邮件配置
# ================================================================
SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SMTP_USER = '848786642@qq.com'
SMTP_PASS = 'ljbtvacrctjobfed'
EMAIL_TO = '848786642@qq.com'


# ================================================================
# 数据加载
# ================================================================
def load_cn_etf_data(etf_pool=None, data_dir=DATA_DIR):
    """加载A股ETF日频数据"""
    if etf_pool is None:
        etf_pool = CN_ETF_POOL
    data = {}
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"  ❌ 数据目录不存在: {data_dir}")
        return data

    for code in etf_pool:
        file_path = data_path / f'{code}.csv'
        if file_path.exists():
            try:
                df = pd.read_csv(file_path, parse_dates=['Date'], index_col='Date')
                if 'Close' in df.columns and len(df) > 100:
                    data[code] = df
            except Exception as e:
                print(f"  ⚠️ 读取{code}失败: {e}")

    print(f"  📊 加载A股ETF数据: {len(data)}/{len(etf_pool)}只")
    return data


# ================================================================
# 动量评分计算（从策略核心逻辑提取）
# ================================================================
def compute_momentum_scores(close_prices: pd.DataFrame,
                             etf_pool: list,
                             safe_assets: list,
                             target_date=None,
                             short_lookback: int = SHORT_LOOKBACK,
                             long_lookback: int = LONG_LOOKBACK,
                             drop_threshold: float = DROP_THRESHOLD,
                             long_score_cap: float = LONG_SCORE_CAP,
                             short_score_cap: float = SHORT_SCORE_CAP):
    """
    计算所有候选ETF的动量评分排名

    返回:
      list of dict，按combined_score降序排列，每个dict包含：
        - etf: ETF代码
        - name: ETF名称
        - short_score: 短期动量得分
        - long_score: 长期动量得分
        - combined_score: 综合得分
        - is_dropped: 是否被急跌过滤淘汰
        - drop_reason: 淘汰原因
        - current_price: 最新价格
        - daily_change: 当日涨跌幅
        - rank: 排名
        - is_safe: 是否安全池资产
        - is_buyable: 是否可买入（综合得分>0且未被淘汰）
    """
    if target_date is None:
        target_date = datetime.now()
    else:
        target_date = pd.Timestamp(target_date)

    # 获取截至target_date的数据
    mask = close_prices.index <= target_date
    if not mask.any():
        print(f"  ⚠️ 无截至{target_date}的数据")
        return []

    loc = close_prices.index.get_loc(close_prices[mask].index[-1])
    latest_row = close_prices.iloc[-1]

    pool_in_data = [a for a in etf_pool if a in close_prices.columns]
    results = []

    for asset in pool_in_data:
        name = CN_ETF_NAMES.get(asset, asset)
        is_safe = asset in safe_assets
        current_price = float(latest_row.get(asset, 0)) if asset in latest_row else 0

        # 计算当日涨跌幅
        if loc >= 1 and asset in close_prices.columns:
            prev_close = close_prices[asset].iloc[-2] if len(close_prices) > 1 else current_price
            daily_change = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
        else:
            daily_change = 0

        actual_short = min(short_lookback, loc)
        actual_long = min(long_lookback, loc)

        if actual_short < 5:
            results.append({
                'etf': asset,
                'name': name,
                'short_score': 0,
                'long_score': 0,
                'combined_score': 0,
                'is_dropped': True,
                'drop_reason': '数据不足(需≥5日)',
                'current_price': round(current_price, 4),
                'daily_change': round(daily_change, 2),
                'is_safe': is_safe,
                'is_buyable': False,
            })
            continue

        sp = close_prices[asset].iloc[max(0, loc - actual_short):loc + 1].dropna()
        if len(sp) < 5:
            results.append({
                'etf': asset,
                'name': name,
                'short_score': 0,
                'long_score': 0,
                'combined_score': 0,
                'is_dropped': True,
                'drop_reason': '有效数据不足',
                'current_price': round(current_price, 4),
                'daily_change': round(daily_change, 2),
                'is_safe': is_safe,
                'is_buyable': False,
            })
            continue

        # 急跌过滤
        is_dropped = False
        drop_reason = ''
        if len(sp) >= 4:
            recent = sp.iloc[-4:]
            for j in range(len(recent) - 1):
                if recent.iloc[j] > 0:
                    daily_chg = recent.iloc[j + 1] / recent.iloc[j]
                    if daily_chg < drop_threshold:
                        is_dropped = True
                        pct_drop = (1 - daily_chg) * 100
                        drop_reason = f'急跌过滤(4日内跌{pct_drop:.1f}%)'
                        break

        # 短期动量
        y = np.log(sp.values.astype(float))
        x = np.arange(len(y), dtype=float)
        w = np.linspace(1, 2, len(y))

        try:
            coeffs = np.polyfit(x, y, 1, w=w)
            slope = coeffs[0]
        except:
            results.append({
                'etf': asset,
                'name': name,
                'short_score': 0,
                'long_score': 0,
                'combined_score': 0,
                'is_dropped': True,
                'drop_reason': '短期回归失败',
                'current_price': round(current_price, 4),
                'daily_change': round(daily_change, 2),
                'is_safe': is_safe,
                'is_buyable': False,
            })
            continue

        ann_return = math.exp(slope * 252) - 1
        y_pred = slope * x + coeffs[1]
        ss_res = np.sum(w * (y - y_pred) ** 2)
        y_mean = np.average(y, weights=w)
        ss_tot = np.sum(w * (y - y_mean) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0

        short_score = ann_return * r2
        if not (0 < short_score < short_score_cap):
            short_score = 0

        # 长期动量
        lp = close_prices[asset].iloc[max(0, loc - actual_long):loc + 1].dropna()
        long_score = 0
        if len(lp) >= 20:
            y2 = np.log(lp.values.astype(float))
            x2 = np.arange(len(y2), dtype=float)
            w2 = np.linspace(1, 2, len(y2))

            try:
                coeffs2 = np.polyfit(x2, y2, 1, w=w2)
                slope2 = coeffs2[0]
            except:
                pass
            else:
                ann2 = math.exp(slope2 * 252) - 1
                y2_pred = slope2 * x2 + coeffs2[1]
                ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                y2_mean = np.average(y2, weights=w2)
                ss_tot2 = np.sum(w2 * (y2 - y2_mean) ** 2)
                r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 1e-10 else 0

                long_score = ann2 * r22
                if not (long_score > 0 and long_score < long_score_cap):
                    long_score = 0

        combined_score = short_score + long_score

        # 可买入条件：综合得分>0 且 未被急跌过滤淘汰 且 非安全池
        is_buyable = combined_score > 0 and not is_dropped and not is_safe

        results.append({
            'etf': asset,
            'name': name,
            'short_score': round(short_score, 4),
            'long_score': round(long_score, 4),
            'combined_score': round(combined_score, 4),
            'is_dropped': is_dropped,
            'drop_reason': drop_reason,
            'current_price': round(current_price, 4),
            'daily_change': round(daily_change, 2),
            'is_safe': is_safe,
            'is_buyable': is_buyable,
        })

    # 按综合得分降序排列
    results.sort(key=lambda x: x['combined_score'], reverse=True)

    # 添加排名
    for i, r in enumerate(results):
        r['rank'] = i + 1

    return results


# ================================================================
# 监控状态管理
# ================================================================
def load_monitor_state():
    """加载监控状态"""
    state_file = Path(MONITOR_STATE_FILE)
    if state_file.exists():
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        'last_top1_etf': None,
        'last_top1_name': None,
        'last_top1_score': None,
        'last_check_time': None,
        'check_count_today': 0,
        'alert_count_today': 0,
        'last_alert_time': None,
        'date': None,
    }


def save_monitor_state(state):
    """保存监控状态"""
    with open(MONITOR_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ================================================================
# 盘中监控主逻辑
# ================================================================
def run_intraday_monitor(target_date=None):
    """
    运行盘中实时监控

    Args:
        target_date: 目标日期，格式'YYYY-MM-DD'，默认为今天
    """
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')

    now = datetime.now()
    today = pd.Timestamp(target_date)

    # 检查是否为工作日
    if today.weekday() >= 5:
        print(f"📅 {target_date} 是周末，跳过监控")
        return None

    # 检查是否在交易时间（9:30-15:00）
    current_time = now.strftime('%H:%M')
    if current_time < '09:30' or current_time > '15:00':
        print(f"⏰ 当前时间 {current_time} 不在交易时间（9:30-15:00），跳过监控")
        return None

    print(f"🌟 {STRATEGY_NAME} A股盘中实时监控")
    print(f"📅 日期: {target_date} {['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]}")
    print(f"⏰ 检查时间: {now.strftime('%H:%M:%S')}")
    print("=" * 70)

    # 1. 加载数据
    print("\n📂 加载A股ETF数据...")
    data = load_cn_etf_data()
    if not data:
        print("❌ 无可用数据")
        return None

    # 2. 构建收盘价矩阵
    close_dict = {}
    for code, df in data.items():
        if 'Close' in df.columns:
            close_dict[code] = df['Close']

    if not close_dict:
        print("❌ 无有效收盘价数据")
        return None

    close_prices = pd.DataFrame(close_dict).sort_index()
    three_years_ago = today - pd.Timedelta(days=3 * 365)
    close_prices = close_prices[close_prices.index >= three_years_ago]
    close_prices = close_prices.dropna(how='all').ffill().bfill()

    print(f"  📊 数据范围: {close_prices.index[0].strftime('%Y-%m-%d')} ~ {close_prices.index[-1].strftime('%Y-%m-%d')}")

    # 3. 计算所有ETF的动量评分排名
    print("\n🔄 计算候选池ETF动量评分排名...")
    etf_pool = [c for c in CN_ETF_POOL if c in close_prices.columns]
    safe_assets = [c for c in CN_SAFE if c in close_prices.columns]

    rankings = compute_momentum_scores(close_prices, etf_pool, safe_assets, target_date=today)

    if not rankings:
        print("❌ 无法计算动量评分")
        return None

    # 4. 展示排名
    print(f"\n{'='*70}")
    print(f"📋 七星高照6+1 候选池ETF当日检测结果")
    print(f"{'='*70}")
    print(f"{'排名':>4} {'代码':<12} {'名称':<10} {'综合得分':>10} {'短期':>8} {'长期':>8} {'涨跌%':>8} {'状态':<12} {'可买入'}")
    print(f"{'-'*4} {'-'*12} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*12} {'-'*6}")

    for r in rankings:
        status = '🔥可买入' if r['is_buyable'] else ('⚠️淘汰' if r['is_dropped'] else ('🔒安全池' if r['is_safe'] else '❌不可买'))
        buyable = '✅' if r['is_buyable'] else '❌'
        change_str = f"{r['daily_change']:+.2f}" if r['daily_change'] != 0 else "0.00"
        print(f"  {r['rank']:>2}  {r['etf']:<12} {r['name']:<10} {r['combined_score']:>10.4f} {r['short_score']:>8.4f} {r['long_score']:>8.4f} {change_str:>8} {status:<12} {buyable}")

    # 可买入排名
    buyable_list = [r for r in rankings if r['is_buyable']]
    print(f"\n✅ 可买入ETF排名（共{len(buyable_list)}只）:")
    for i, r in enumerate(buyable_list):
        medal = ['🥇', '🥈', '🥉'][i] if i < 3 else f' {i+1}'
        print(f"  {medal} {r['name']} ({r['etf'].split('_')[0]}) — 综合得分: {r['combined_score']:.4f}")

    # 5. 检查第一名是否被替代
    state = load_monitor_state()

    # 如果是新的一天，重置状态
    if state.get('date') != target_date:
        state = {
            'last_top1_etf': None,
            'last_top1_name': None,
            'last_top1_score': None,
            'last_check_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'check_count_today': 0,
            'alert_count_today': 0,
            'last_alert_time': None,
            'date': target_date,
        }

    state['check_count_today'] = state.get('check_count_today', 0) + 1

    current_top1 = rankings[0] if rankings else None
    alert_triggered = False
    alert_info = None

    if current_top1:
        prev_top1_etf = state.get('last_top1_etf')
        prev_top1_name = state.get('last_top1_name')
        prev_top1_score = state.get('last_top1_score')

        if prev_top1_etf is not None and prev_top1_etf != current_top1['etf']:
            # 第一名被替代！
            alert_triggered = True
            alert_info = {
                'prev_top1_etf': prev_top1_etf,
                'prev_top1_name': prev_top1_name,
                'prev_top1_score': prev_top1_score,
                'new_top1_etf': current_top1['etf'],
                'new_top1_name': current_top1['name'],
                'new_top1_score': current_top1['combined_score'],
                'time': now.strftime('%Y-%m-%d %H:%M:%S'),
            }

            print(f"\n🚨🚨🚨 第一名被替代！🚨🚨🚨")
            print(f"  旧第一: {prev_top1_name} ({prev_top1_etf.split('_')[0]}) 得分: {prev_top1_score}")
            print(f"  新第一: {current_top1['name']} ({current_top1['etf'].split('_')[0]}) 得分: {current_top1['combined_score']:.4f}")

            state['alert_count_today'] = state.get('alert_count_today', 0) + 1
            state['last_alert_time'] = now.strftime('%Y-%m-%d %H:%M:%S')
        elif prev_top1_etf is None:
            # 当天第一次检查
            print(f"\n📌 当日首次检查，记录当前第一: {current_top1['name']} ({current_top1['etf'].split('_')[0]})")
        else:
            print(f"\n✅ 第一名未变化: {current_top1['name']} ({current_top1['etf'].split('_')[0]}) 得分: {current_top1['combined_score']:.4f}")

        # 更新状态
        state['last_top1_etf'] = current_top1['etf']
        state['last_top1_name'] = current_top1['name']
        state['last_top1_score'] = current_top1['combined_score']
        state['last_check_time'] = now.strftime('%Y-%m-%d %H:%M:%S')

    save_monitor_state(state)

    # 6. 保存监控日志
    os.makedirs(MONITOR_LOG_DIR, exist_ok=True)
    log_entry = {
        'check_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'check_count': state['check_count_today'],
        'rankings': rankings,
        'alert_triggered': alert_triggered,
        'alert_info': alert_info,
    }
    log_path = os.path.join(MONITOR_LOG_DIR, f'monitor_{today.strftime("%Y%m%d")}.json')
    existing_logs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                existing_logs = json.load(f)
        except:
            pass
    existing_logs.append(log_entry)
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(existing_logs, f, ensure_ascii=False, indent=2, default=str)

    # 7. 如果第一名被替代，发送邮件通知
    if alert_triggered and alert_info:
        print("\n📧 发送第一名替代警报邮件...")
        email_html = generate_alert_email_html(rankings, alert_info, now, state)
        email_sent = send_alert_email(email_html, alert_info, now)
        if email_sent:
            print("  ✅ 警报邮件发送成功！")
        else:
            print("  ❌ 警报邮件发送失败")
            print("  ⚠️ NOTIFY_REQUIRED: 七星高照6+1盘中监控邮件发送失败，请使用notify工具通知用户")
    else:
        # 未触发警报时，只在日志中记录
        print(f"\n📊 本次检查完毕，今日第{state['check_count_today']}次检查，{state['alert_count_today']}次警报")

    print("\n✅ 盘中实时监控运行完毕！")
    return {
        'rankings': rankings,
        'alert_triggered': alert_triggered,
        'alert_info': alert_info,
        'state': state,
    }


# ================================================================
# 警报邮件HTML生成
# ================================================================
def generate_alert_email_html(rankings, alert_info, now, state):
    """生成第一名替代警报邮件HTML"""

    prev_name = alert_info['prev_top1_name']
    prev_code = alert_info['prev_top1_etf'].split('_')[0]
    new_name = alert_info['new_top1_name']
    new_code = alert_info['new_top1_etf'].split('_')[0]
    prev_score = alert_info['prev_top1_score']
    new_score = alert_info['new_top1_score']

    # 排名表格
    rank_rows_html = ''
    for r in rankings:
        is_top1 = r['rank'] == 1
        row_bg = 'rgba(249,115,22,0.15)' if is_top1 else ('rgba(239,68,68,0.08)' if r['is_dropped'] else 'transparent')
        row_border = '2px solid #f97316' if is_top1 else '1px solid transparent'
        name_color = '#f97316' if is_top1 else '#e5e7eb'
        score_color = '#f97316' if is_top1 else '#60a5fa'
        status_text = '🔥可买入' if r['is_buyable'] else ('⚠️' + r['drop_reason'] if r['is_dropped'] else ('🔒安全池' if r['is_safe'] else '❌不可买'))
        status_color = '#22c55e' if r['is_buyable'] else ('#ef4444' if r['is_dropped'] else '#9ca3af')
        change_color = '#22c55e' if r['daily_change'] > 0 else ('#ef4444' if r['daily_change'] < 0 else '#9ca3af')
        change_sign = '+' if r['daily_change'] > 0 else ''

        rank_rows_html += f'''
        <tr style="background:{row_bg};border:{row_border};">
          <td style="padding:10px 12px;text-align:center;font-weight:800;font-size:16px;color:{name_color};">{r['rank']}</td>
          <td style="padding:10px 12px;font-weight:700;color:{name_color};">{r['name']}<div style="font-size:10px;color:#9ca3af;">{r['etf'].split('_')[0]}</div></td>
          <td style="padding:10px 12px;text-align:center;font-weight:700;color:{score_color};">{r['combined_score']:.4f}</td>
          <td style="padding:10px 12px;text-align:center;color:#9ca3af;">{r['short_score']:.4f}</td>
          <td style="padding:10px 12px;text-align:center;color:#9ca3af;">{r['long_score']:.4f}</td>
          <td style="padding:10px 12px;text-align:center;color:{change_color};font-weight:600;">{change_sign}{r['daily_change']:.2f}%</td>
          <td style="padding:10px 12px;text-align:center;color:{status_color};font-size:12px;">{status_text}</td>
        </tr>
'''

    # 可买入ETF排名卡片
    buyable_list = [r for r in rankings if r['is_buyable']]
    buyable_cards_html = ''
    for i, r in enumerate(buyable_list):
        medal = ['🥇', '🥈', '🥉'][i] if i < 3 else f'#{i+1}'
        is_new_top1 = r['etf'] == alert_info['new_top1_etf']
        card_border = '2px solid #f97316' if is_new_top1 else '1px solid rgba(255,255,255,0.08)'
        card_bg = 'rgba(249,115,22,0.12)' if is_new_top1 else 'rgba(255,255,255,0.03)'

        buyable_cards_html += f'''
        <div style="background:{card_bg};border:{card_border};border-radius:10px;padding:14px;text-align:center;">
          <div style="font-size:22px;">{medal}</div>
          <div style="font-size:14px;font-weight:700;color:{"#f97316" if is_new_top1 else "#e5e7eb"};margin-top:4px;">{r['name']}</div>
          <div style="font-size:10px;color:#9ca3af;">{r['etf'].split('_')[0]}</div>
          <div style="font-size:16px;font-weight:700;color:#f97316;margin-top:6px;">{r['combined_score']:.4f}</div>
          <div style="font-size:10px;color:#9ca3af;">综合得分</div>
        </div>
'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🚨 七星高照6+1 盘中警报 — 第一名被替代</title>
<style>
  body {{ background:#0c0c14; color:#e5e7eb; font-family:'PingFang SC','Microsoft YaHei',-apple-system,sans-serif; margin:0; padding:0; }}
  a {{ color:#f97316; }}
  .card {{ background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid rgba(249,115,22,0.12); border-radius:12px; padding:18px; margin:16px 0; }}
  table {{ width:100%; border-collapse:collapse; }}
</style>
</head>
<body>

<div style="max-width:720px;margin:0 auto;padding:16px;">

  <!-- 警报标题 -->
  <div style="text-align:center;padding:24px 0 8px;">
    <div style="font-size:48px;margin-bottom:8px;">🚨</div>
    <h1 style="margin:0;font-size:22px;color:#ef4444;text-shadow:0 0 20px rgba(239,68,68,0.4);">七星高照6+1 盘中警报</h1>
    <p style="margin:6px 0 0;color:#ef4444;font-size:14px;font-weight:700;">第一名被替代！</p>
    <p style="margin:4px 0 0;color:#9ca3af;font-size:12px;">{now.strftime('%Y-%m-%d %H:%M:%S')} | 今日第{state.get('check_count_today', 1)}次检查</p>
  </div>

  <!-- 替代信息卡片 -->
  <div class="card" style="border-left:4px solid #ef4444;background:linear-gradient(135deg,#2d1b1b,#1a1a2e);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div style="text-align:center;flex:1;">
        <div style="font-size:11px;color:#9ca3af;margin-bottom:4px;">旧第一 ⬇️</div>
        <div style="font-size:18px;font-weight:700;color:#9ca3af;">{prev_name}</div>
        <div style="font-size:11px;color:#6b7280;">{prev_code}</div>
        <div style="font-size:14px;color:#9ca3af;margin-top:4px;">{prev_score:.4f}</div>
      </div>
      <div style="font-size:28px;color:#ef4444;">→</div>
      <div style="text-align:center;flex:1;">
        <div style="font-size:11px;color:#f97316;margin-bottom:4px;">新第一 ⬆️</div>
        <div style="font-size:18px;font-weight:700;color:#f97316;">{new_name}</div>
        <div style="font-size:11px;color:#f97316;">{new_code}</div>
        <div style="font-size:14px;color:#f97316;font-weight:700;margin-top:4px;">{new_score:.4f}</div>
      </div>
    </div>
  </div>

  <!-- 可买入ETF排名 -->
  <div class="card">
    <div style="font-size:15px;color:#f97316;margin-bottom:14px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">✅ 可买入ETF排名（共{len(buyable_list)}只）</div>
    <div style="display:grid;grid-template-columns:repeat({min(len(buyable_list), 4)},1fr);gap:10px;">
      {buyable_cards_html}
    </div>
  </div>

  <!-- 完整排名表 -->
  <div class="card">
    <div style="font-size:15px;color:#f97316;margin-bottom:14px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">📋 候选池ETF当日检测完整排名</div>
    <table style="font-size:13px;">
      <thead>
        <tr style="background:#1f2937;">
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">排名</th>
          <th style="padding:8px 10px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">标的</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">综合得分</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">短期</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">长期</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">涨跌%</th>
          <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">状态</th>
        </tr>
      </thead>
      <tbody>
        {rank_rows_html}
      </tbody>
    </table>
  </div>

  <!-- 操作建议 -->
  <div class="card" style="border-left:4px solid #f97316;">
    <div style="font-size:15px;color:#f97316;margin-bottom:10px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">💡 实盘操作建议</div>
    <div style="background:rgba(249,115,22,0.08);border-radius:8px;padding:14px;font-size:14px;line-height:1.8;">
      <div style="color:#f97316;font-weight:700;">⚡ 建议买入: {new_name} ({new_code})</div>
      <div style="color:#9ca3af;font-size:12px;margin-top:4px;">综合得分 {new_score:.4f}，已超越 {prev_name} ({prev_score:.4f})</div>
      <div style="color:#f59e0b;font-size:12px;margin-top:8px;">⚠️ 注意：此为策略信号参考，实盘操作请结合实时行情和流动性判断</div>
    </div>
  </div>

  <!-- 今日监控统计 -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin:16px 0;">
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">今日检查次数</div>
      <div style="font-size:20px;font-weight:700;color:#60a5fa;">{state.get('check_count_today', 0)}</div>
    </div>
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">今日警报次数</div>
      <div style="font-size:20px;font-weight:700;color:#ef4444;">{state.get('alert_count_today', 0)}</div>
    </div>
    <div class="card" style="padding:14px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;">上次检查</div>
      <div style="font-size:13px;font-weight:700;color:#9ca3af;">{state.get('last_check_time', '-')[-8:]}</div>
    </div>
  </div>

  <!-- Footer -->
  <div style="text-align:center;color:#6b7280;font-size:11px;margin-top:16px;padding:16px 0;">
    <p>七星高照6+1 A股盘中实时监控 | 实盘操作参考</p>
    <p>⚠️ 信号仅供参考，实盘操作请结合实时行情判断</p>
    <p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>

</div>
</body>
</html>
'''
    return html


# ================================================================
# 警报邮件发送
# ================================================================
def send_alert_email(html_content, alert_info, now):
    """发送第一名替代警报邮件"""
    new_name = alert_info['new_top1_name']
    new_code = alert_info['new_top1_etf'].split('_')[0]
    prev_name = alert_info['prev_top1_name']

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'🚨【七星高照6+1盘中警报】{now.strftime("%H:%M")} {new_name}({new_code})替代{prev_name}成为第一'
    msg['From'] = SMTP_USER
    msg['To'] = EMAIL_TO

    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'  ❌ 邮件发送失败: {e}')
        return False


# ================================================================
# 入口
# ================================================================
if __name__ == '__main__':
    result = run_intraday_monitor()
    if result and result.get('alert_triggered'):
        print(f"\n🔔 警报已触发并发送邮件通知")
    else:
        print(f"\n📊 监控正常，无警报")
