#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照V1.7.2 排行榜前二策略 — 2026年月线收益表格邮件
纯HTML表格，不依赖ECharts，邮件中直接可见
"""
import sys
import os
import json
import math
import smtplib
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/data/workspace')
import seven_stars_etf_backtest as ss

# 关键：修改模块的全局日期范围，使数据加载包含2026年
ss.START_DATE = '2021-01-01'
ss.END_DATE = '2026-04-24'

CHART_START = '2026-01-01'


def run_backtest_extract_returns(data, etf_pool, strategy_name,
                                 lookback_days=ss.LOOKBACK_DAYS,
                                 holdings_num=ss.HOLDINGS_NUM,
                                 fees_rate=ss.ETF_FEES,
                                 use_volume_filter=True,
                                 use_short_momentum=True,
                                 use_profit_protection=True,
                                 use_recent_drop_filter=True,
                                 defensive_etf_code=ss.DEFENSIVE_ETF):
    """运行回测并提取每日收益率序列和持仓记录"""
    all_dates = None
    for code, df in data.items():
        if all_dates is None:
            all_dates = set(df.index)
        else:
            all_dates = all_dates | set(df.index)
    if defensive_etf_code in data:
        all_dates = all_dates | set(data[defensive_etf_code].index)
    all_dates = sorted(all_dates)
    if len(all_dates) < 100:
        return None, None, None

    all_codes = list(data.keys())
    close_dict = {}
    volume_dict = {}
    high_dict = {}
    for code in all_codes:
        s = data[code]['Close']
        s_high = data[code].get('High', data[code]['Close'])
        s_vol = data[code].get('Volume', pd.Series(0, index=data[code].index))
        close_dict[code] = s
        volume_dict[code] = s_vol.reindex(all_dates).fillna(0)
        high_dict[code] = s_high.reindex(all_dates).fillna(method='ffill')

    close_prices = pd.DataFrame(close_dict).reindex(all_dates)
    close_prices = close_prices.fillna(method='ffill').fillna(method='bfill')
    volumes = pd.DataFrame(volume_dict, index=all_dates).fillna(0)
    highs = pd.DataFrame(high_dict, index=all_dates)

    portfolio_returns = pd.Series(0.0, index=all_dates)
    prev_holdings = None
    trade_count = 0
    daily_holdings = []
    daily_holdings_list = []
    profit_protection_sold = set()
    warmup = lookback_days + 20

    for i, date in enumerate(all_dates):
        profit_protection_sold = set()

        if i < warmup:
            target_holdings = [defensive_etf_code] if defensive_etf_code in close_prices.columns else [None]
            current_holding = target_holdings[0]
            daily_holdings.append(current_holding)
            daily_holdings_list.append(target_holdings)
            if current_holding and current_holding in close_prices.columns:
                r = close_prices.iloc[i][current_holding]
                prev_r = close_prices.iloc[i - 1][current_holding] if i > 0 else r
                daily_ret = (r / prev_r - 1) if prev_r > 0 else 0
                portfolio_returns.iloc[i] = daily_ret
            if prev_holdings is not None and prev_holdings != target_holdings:
                trade_count += 1
                portfolio_returns.iloc[i] -= fees_rate
            prev_holdings = target_holdings
            continue

        # 盈利保护
        if use_profit_protection and prev_holdings is not None:
            for h in prev_holdings:
                if h and h in etf_pool and h in close_prices.columns:
                    current_price = close_prices.iloc[i][h]
                    high_hist = highs[h].iloc[:i]
                    if ss.check_profit_protection(high_hist, current_price):
                        profit_protection_sold.add(h)

        # 排名
        etf_metrics = []
        for code in etf_pool:
            if code not in close_prices.columns:
                continue
            if code not in data:
                continue
            etf_dates = set(data[code].index)
            if date not in etf_dates:
                continue

            close_hist_raw = data[code]['Close']
            close_hist = close_hist_raw[close_hist_raw.index <= date]
            if len(close_hist) < lookback_days + 1:
                continue

            current_price = close_hist.iloc[-1]
            if current_price <= 0 or np.isnan(current_price):
                continue

            if use_profit_protection and code in profit_protection_sold:
                continue

            if use_volume_filter and code in volumes.columns:
                vol_hist = volumes[code].iloc[:i]
                current_vol = volumes[code].iloc[i] if i < len(volumes) else 0
                if ss.check_volume_spike(vol_hist, current_vol):
                    metrics_temp = ss.calculate_momentum_score(close_hist, lookback_days)
                    if metrics_temp and metrics_temp['annualized'] > ss.VOLUME_RETURN_LIMIT:
                        continue

            if use_short_momentum:
                if not ss.check_short_momentum(close_hist):
                    continue

            metrics = ss.calculate_momentum_score(close_hist, lookback_days)
            if metrics is None:
                continue

            if not (ss.MIN_SCORE_THRESHOLD < metrics['score'] < ss.MAX_SCORE_THRESHOLD):
                continue

            if use_recent_drop_filter and ss.check_recent_drop(close_hist):
                continue

            etf_metrics.append({
                'code': code,
                'name': ss.ETF_NAMES.get(code, code),
                'score': metrics['score'],
                'annualized': metrics['annualized'],
                'r_squared': metrics['r_squared'],
                'current_price': current_price,
            })

        etf_metrics.sort(key=lambda x: x['score'], reverse=True)

        target_holdings = []
        for m in etf_metrics:
            if len(target_holdings) >= holdings_num:
                break
            if use_profit_protection and m['code'] in profit_protection_sold:
                continue
            target_holdings.append(m['code'])

        if not target_holdings:
            if defensive_etf_code in close_prices.columns:
                target_holdings = [defensive_etf_code]
            else:
                target_holdings = [None]

        daily_holdings_list.append(target_holdings)
        daily_holdings.append(target_holdings[0])

        daily_ret = 0
        n_valid = 0
        for h in target_holdings:
            if h and h in close_prices.columns:
                cur_price = close_prices.iloc[i][h]
                if i > 0:
                    prev_price = close_prices.iloc[i - 1][h]
                    if prev_price > 0:
                        daily_ret += cur_price / prev_price - 1
                        n_valid += 1
        if n_valid > 0:
            portfolio_returns.iloc[i] = daily_ret / n_valid
        else:
            portfolio_returns.iloc[i] = 0

        if prev_holdings is not None:
            prev_set = set([h for h in prev_holdings if h])
            cur_set = set([h for h in target_holdings if h])
            new_positions = cur_set - prev_set
            if new_positions:
                trade_count += 1
                turnover_ratio = len(new_positions) / max(len(cur_set), 1)
                portfolio_returns.iloc[i] -= fees_rate * turnover_ratio

        prev_holdings = target_holdings

    cum = (1 + portfolio_returns).cumprod()
    return portfolio_returns, cum, daily_holdings


def build_monthly_table(port_ret, cum, holdings, strategy_name):
    """按月汇总收益率，返回月度数据"""
    mask = port_ret.index >= pd.Timestamp(CHART_START)
    ret_2026 = port_ret[mask].copy()
    hold_2026 = holdings[-len(ret_2026):] if len(holdings) >= len(ret_2026) else holdings

    # 添加月份列
    ret_2026_df = pd.DataFrame({
        'ret': ret_2026.values,
        'holding': hold_2026[-len(ret_2026):] if len(hold_2026) >= len(ret_2026) else hold_2026,
    }, index=ret_2026.index)
    ret_2026_df['month'] = ret_2026_df.index.to_period('M')

    monthly_data = []
    for period, group in ret_2026_df.groupby('month'):
        # 月度收益 = 该月最后一天的累计净值 / 上月最后一天累计净值 - 1
        month_start = period.start_time
        month_end = period.end_time

        # 找上月末净值
        prev_mask = cum.index < month_start
        if prev_mask.any():
            prev_cum = cum[prev_mask].iloc[-1]
        else:
            prev_cum = 1.0

        # 找本月末净值
        curr_mask = cum.index <= month_end
        if curr_mask.any():
            curr_cum = cum[curr_mask].iloc[-1]
        else:
            curr_cum = prev_cum

        month_ret = (curr_cum / prev_cum - 1) * 100

        days = len(group)
        win_days = (group['ret'] > 0).sum()
        win_rate = win_days / days * 100 if days > 0 else 0
        max_daily = group['ret'].max() * 100
        min_daily = group['ret'].min() * 100

        # 该月持仓分布
        h_counts = Counter([h for h in group['holding'] if h])
        top_holding = h_counts.most_common(1)
        top_h_name = ss.ETF_NAMES.get(top_holding[0][0], top_holding[0][0]) if top_holding else '货币基金'

        # 最大回撤（月内）
        cum_in_month = cum[(cum.index >= month_start) & (cum.index <= month_end)]
        if len(cum_in_month) > 1:
            peak = cum_in_month.iloc[0]
            max_dd = 0
            for v in cum_in_month:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            month_dd = abs(max_dd) * 100
        else:
            month_dd = 0

        monthly_data.append({
            'month': str(period),
            'ret': round(month_ret, 2),
            'days': days,
            'win_rate': round(win_rate, 1),
            'max_gain': round(max_daily, 2),
            'max_loss': round(min_daily, 2),
            'max_dd': round(month_dd, 2),
            'top_holding': top_h_name,
        })

    return monthly_data


def generate_email_html(all_results):
    """生成纯HTML邮件，包含月线收益表格"""

    # 计算各策略月度数据
    monthly_all = {}
    stats_all = {}
    for name, (port_ret, cum, holdings) in all_results.items():
        monthly_all[name] = build_monthly_table(port_ret, cum, holdings, name)

        # 总体统计
        mask = port_ret.index >= pd.Timestamp(CHART_START)
        ret_2026 = port_ret[mask]
        cum_2026 = cum[mask]
        if len(cum_2026) > 0:
            cum_norm = cum_2026 / cum_2026.iloc[0]
            total_ret = (cum_norm.iloc[-1] / cum_norm.iloc[0] - 1) * 100
            n_days = len(ret_2026)
            ann_ret = ((cum_norm.iloc[-1] / cum_norm.iloc[0]) ** (252 / max(n_days, 1)) - 1) * 100
            sharpe = (np.mean(ret_2026) * 252 - 0.02) / (np.std(ret_2026) * np.sqrt(252)) if np.std(ret_2026) > 0 else 0
            peak = cum_norm.iloc[0]
            max_dd = 0
            for v in cum_norm:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            win_rate = (ret_2026 > 0).mean() * 100
            max_daily_gain = ret_2026.max() * 100
            max_daily_loss = ret_2026.min() * 100
        else:
            total_ret = ann_ret = sharpe = max_dd = win_rate = max_daily_gain = max_daily_loss = 0
            n_days = 0

        stats_all[name] = {
            'total_ret': round(total_ret, 2),
            'ann_ret': round(ann_ret, 2),
            'sharpe': round(sharpe, 2),
            'max_dd': round(abs(max_dd) * 100, 2),
            'win_rate': round(win_rate, 1),
            'max_gain': round(max_daily_gain, 2),
            'max_loss': round(max_daily_loss, 2),
            'n_days': n_days,
        }

    # 颜色定义
    strategy_colors = {
        '七星高照-无成交量过滤': '#f97316',
        '七星高照-大池完整版': '#3b82f6',
    }

    # ========== 构建HTML ==========
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>七星高照V1.7.2 — 2026年月线收益</title>
</head>
<body style="margin:0;padding:0;background:#0c0c14;color:#e5e7eb;font-family:'PingFang SC','Microsoft YaHei',-apple-system,sans-serif;">

<div style="max-width:800px;margin:0 auto;padding:20px;">

<!-- 标题 -->
<div style="text-align:center;padding:30px 0 10px;">
  <h1 style="margin:0;font-size:26px;color:#f97316;text-shadow:0 0 20px rgba(249,115,22,0.3);">🌟 七星高照ETF轮动 V1.7.2</h1>
  <p style="margin:8px 0 0;color:#9ca3af;font-size:14px;">2026年月线收益报告 | 2026-01-01 ~ 2026-04-24</p>
</div>

<!-- 总览卡片 -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:24px 0;">
'''

    for name, s in stats_all.items():
        clr = strategy_colors.get(name, '#f97316')
        tr_cls = '#22c55e' if s['total_ret'] >= 0 else '#ef4444'
        ar_cls = '#22c55e' if s['ann_ret'] >= 0 else '#ef4444'
        html += f'''
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2d2d44;border-radius:12px;padding:18px;">
  <div style="font-size:15px;color:{clr};margin-bottom:10px;font-weight:700;border-bottom:1px solid #2d2d44;padding-bottom:8px;">{name}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
    <div style="text-align:center;padding:6px 0;">
      <div style="font-size:11px;color:#9ca3af;">区间收益</div>
      <div style="font-size:22px;font-weight:700;color:{tr_cls};">{s["total_ret"]:+.2f}%</div>
    </div>
    <div style="text-align:center;padding:6px 0;">
      <div style="font-size:11px;color:#9ca3af;">年化收益</div>
      <div style="font-size:22px;font-weight:700;color:{ar_cls};">{s["ann_ret"]:+.0f}%</div>
    </div>
    <div style="text-align:center;padding:6px 0;">
      <div style="font-size:11px;color:#9ca3af;">夏普比率</div>
      <div style="font-size:22px;font-weight:700;color:#60a5fa;">{s["sharpe"]:.2f}</div>
    </div>
    <div style="text-align:center;padding:6px 0;">
      <div style="font-size:11px;color:#9ca3af;">最大回撤</div>
      <div style="font-size:22px;font-weight:700;color:#ef4444;">{s["max_dd"]:.2f}%</div>
    </div>
    <div style="text-align:center;padding:6px 0;">
      <div style="font-size:11px;color:#9ca3af;">胜率</div>
      <div style="font-size:22px;font-weight:700;color:#60a5fa;">{s["win_rate"]:.1f}%</div>
    </div>
    <div style="text-align:center;padding:6px 0;">
      <div style="font-size:11px;color:#9ca3af;">交易日</div>
      <div style="font-size:22px;font-weight:700;color:#60a5fa;">{s["n_days"]}</div>
    </div>
  </div>
</div>
'''

    html += '</div>\n'

    # ========== 月线收益表格（每个策略一个） ==========
    for name, monthly in monthly_all.items():
        clr = strategy_colors.get(name, '#f97316')
        html += f'''
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2d2d44;border-radius:12px;padding:18px;margin-bottom:16px;">
  <div style="font-size:16px;color:{clr};margin-bottom:14px;font-weight:700;border-left:4px solid {clr};padding-left:10px;">📊 {name} — 月线收益</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <thead>
      <tr style="background:#1f2937;">
        <th style="padding:8px 10px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">月份</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">月收益率</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">交易天数</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">胜率</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">最大单日盈利</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">最大单日亏损</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">月内回撤</th>
        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">主要持仓</th>
      </tr>
    </thead>
    <tbody>
'''
        for row in monthly:
            ret_cls = '#22c55e' if row['ret'] >= 0 else '#ef4444'
            gain_cls = '#22c55e' if row['max_gain'] >= 0 else '#ef4444'
            loss_cls = '#ef4444'
            # 收益率背景条
            bar_width = min(abs(row['ret']) * 1.5, 100)
            bar_color = '#22c55e' if row['ret'] >= 0 else '#ef4444'
            bar_html = f'''
            <div style="position:relative;height:20px;">
              <div style="position:absolute;top:0;left:50%;width:{bar_width if row["ret"]>=0 else bar_width}%;height:100%;background:{bar_color};opacity:0.25;border-radius:2px;{"right:50%" if row["ret"]>=0 else "left:50%"};"></div>
              <span style="position:relative;z-index:1;font-weight:700;color:{ret_cls};">{row["ret"]:+.2f}%</span>
            </div>'''

            html += f'''
      <tr style="border-bottom:1px solid #1f2937;">
        <td style="padding:8px 10px;color:#e5e7eb;font-weight:600;">{row["month"]}</td>
        <td style="padding:8px 10px;text-align:center;">{bar_html}</td>
        <td style="padding:8px 10px;text-align:center;color:#9ca3af;">{row["days"]}</td>
        <td style="padding:8px 10px;text-align:center;color:#60a5fa;">{row["win_rate"]:.0f}%</td>
        <td style="padding:8px 10px;text-align:center;color:#22c55e;">{row["max_gain"]:+.2f}%</td>
        <td style="padding:8px 10px;text-align:center;color:#ef4444;">{row["max_loss"]:+.2f}%</td>
        <td style="padding:8px 10px;text-align:center;color:#ef4444;">{row["max_dd"]:.2f}%</td>
        <td style="padding:8px 10px;text-align:center;color:#60a5fa;font-size:12px;">{row["top_holding"]}</td>
      </tr>
'''

        html += '''
    </tbody>
  </table>
</div>
'''

    # ========== 对比表格 ==========
    html += '''
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2d2d44;border-radius:12px;padding:18px;margin-bottom:16px;">
  <div style="font-size:16px;color:#f97316;margin-bottom:14px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">⚖️ 策略月度对比</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <thead>
      <tr style="background:#1f2937;">
        <th style="padding:8px 10px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">月份</th>
'''
    for name in monthly_all:
        clr = strategy_colors.get(name, '#f97316')
        html += f'        <th style="padding:8px 10px;text-align:center;color:{clr};border-bottom:2px solid #2d2d44;">{name}</th>\n'
    html += '''        <th style="padding:8px 10px;text-align:center;color:#9ca3af;border-bottom:2px solid #2d2d44;">差值</th>
      </tr>
    </thead>
    <tbody>
'''
    # 按月份对齐
    months = [m['month'] for m in list(monthly_all.values())[0]]
    for i, month in enumerate(months):
        rets = []
        for name, monthly in monthly_all.items():
            r = [m['ret'] for m in monthly if m['month'] == month]
            rets.append(r[0] if r else 0)

        diff = rets[0] - rets[1] if len(rets) >= 2 else 0
        diff_cls = '#22c55e' if diff >= 0 else '#ef4444'

        html += f'      <tr style="border-bottom:1px solid #1f2937;">\n'
        html += f'        <td style="padding:8px 10px;color:#e5e7eb;font-weight:600;">{month}</td>\n'
        for j, r in enumerate(rets):
            r_cls = '#22c55e' if r >= 0 else '#ef4444'
            html += f'        <td style="padding:8px 10px;text-align:center;color:{r_cls};font-weight:700;">{r:+.2f}%</td>\n'
        html += f'        <td style="padding:8px 10px;text-align:center;color:{diff_cls};font-weight:600;">{diff:+.2f}%</td>\n'
        html += f'      </tr>\n'

    # 合计行
    html += '      <tr style="border-top:2px solid #2d2d44;background:#1f2937;">\n'
    html += '        <td style="padding:8px 10px;color:#f97316;font-weight:700;">合计</td>\n'
    totals = []
    for name, s in stats_all.items():
        r_cls = '#22c55e' if s['total_ret'] >= 0 else '#ef4444'
        html += f'        <td style="padding:8px 10px;text-align:center;color:{r_cls};font-weight:700;font-size:15px;">{s["total_ret"]:+.2f}%</td>\n'
        totals.append(s['total_ret'])
    diff_total = totals[0] - totals[1] if len(totals) >= 2 else 0
    diff_cls = '#22c55e' if diff_total >= 0 else '#ef4444'
    html += f'        <td style="padding:8px 10px;text-align:center;color:{diff_cls};font-weight:700;">{diff_total:+.2f}%</td>\n'
    html += '      </tr>\n'

    html += '''
    </tbody>
  </table>
</div>
'''

    # ========== 持仓分布 ==========
    html += '''
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2d2d44;border-radius:12px;padding:18px;margin-bottom:16px;">
  <div style="font-size:16px;color:#f97316;margin-bottom:14px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">🏦 2026年持仓分布</div>
'''
    bar_colors = ['#f97316', '#3b82f6', '#22c55e', '#a855f7', '#ec4899', '#eab308', '#14b8a6', '#6366f1']
    for name, (port_ret, cum, holdings) in all_results.items():
        mask = port_ret.index >= pd.Timestamp(CHART_START)
        hold_2026 = holdings[-mask.sum():] if len(holdings) >= mask.sum() else holdings
        h_counts = Counter([h for h in hold_2026 if h])
        total_h = sum(h_counts.values())
        if total_h > 0:
            clr = strategy_colors.get(name, '#f97316')
            html += f'  <div style="margin-bottom:14px;">'
            html += f'    <div style="font-size:13px;color:{clr};font-weight:600;margin-bottom:8px;">{name}</div>'
            for idx, (code, cnt) in enumerate(h_counts.most_common(8)):
                etf_name = ss.ETF_NAMES.get(code, code)
                pct = cnt / total_h * 100
                bar_w = min(pct, 100)
                bc = bar_colors[idx % len(bar_colors)]
                html += f'''
    <div style="display:flex;align-items:center;margin-bottom:4px;font-size:12px;">
      <div style="width:100px;color:#9ca3af;text-align:right;padding-right:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{etf_name}</div>
      <div style="flex:1;height:16px;background:#1f2937;border-radius:4px;overflow:hidden;">
        <div style="width:{bar_w}%;height:100%;background:{bc};border-radius:4px;"></div>
      </div>
      <div style="width:50px;text-align:right;color:#e5e7eb;">{pct:.1f}%</div>
    </div>
'''
            html += '  </div>'

    html += '</div>\n'

    # ========== 全区间年线收益 ==========
    html += '''
<div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2d2d44;border-radius:12px;padding:18px;margin-bottom:16px;">
  <div style="font-size:16px;color:#f97316;margin-bottom:14px;font-weight:700;border-left:4px solid #f97316;padding-left:10px;">📈 全区间年线收益（2021-2026）</div>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <thead>
      <tr style="background:#1f2937;">
        <th style="padding:8px 10px;text-align:left;color:#9ca3af;border-bottom:2px solid #2d2d44;">年份</th>
'''
    for name in all_results:
        clr = strategy_colors.get(name, '#f97316')
        html += f'        <th style="padding:8px 10px;text-align:center;color:{clr};border-bottom:2px solid #2d2d44;">{name}</th>\n'
    html += '''      </tr>
    </thead>
    <tbody>
'''
    for year in range(2021, 2027):
        html += f'      <tr style="border-bottom:1px solid #1f2937;">\n'
        html += f'        <td style="padding:8px 10px;color:#e5e7eb;font-weight:600;">{year}</td>\n'
        for name, (port_ret, cum, holdings) in all_results.items():
            year_start = pd.Timestamp(f'{year}-01-01')
            year_end = pd.Timestamp(f'{year}-12-31')
            year_data = port_ret[(port_ret.index >= year_start) & (port_ret.index <= year_end)]
            if len(year_data) > 0:
                cum_start = cum[cum.index < year_start]
                if len(cum_start) > 0:
                    start_val = cum_start.iloc[-1]
                else:
                    start_val = 1.0
                cum_end = cum[(cum.index >= year_start) & (cum.index <= year_end)].iloc[-1]
                year_ret = (cum_end / start_val - 1) * 100
                r_cls = '#22c55e' if year_ret >= 0 else '#ef4444'
                html += f'        <td style="padding:8px 10px;text-align:center;color:{r_cls};font-weight:700;">{year_ret:+.2f}%</td>\n'
            else:
                html += f'        <td style="padding:8px 10px;text-align:center;color:#6b7280;">—</td>\n'
        html += f'      </tr>\n'

    html += '''
    </tbody>
  </table>
</div>
'''

    # ========== Footer ==========
    html += '''
<div style="text-align:center;color:#6b7280;font-size:12px;margin-top:20px;padding:20px 0;">
  <p>七星高照ETF轮动 V1.7.2 | 数据来源：本地CSV日频数据 | 回测引擎：逐日循环</p>
  <p>⚠️ 回测结果不代表未来表现，仅供研究参考</p>
  <p>生成时间：''' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '''</p>
</div>

</div>
</body>
</html>
'''
    return html


def send_email(html_content):
    """发送HTML邮件"""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart('alternative')
    msg['Subject'] = '【策略回测报告】2026-04-27 七星高照V1.7.2 2026年月线收益'
    msg['From'] = '848786642@qq.com'
    msg['To'] = '848786642@qq.com'

    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)

    try:
        server = smtplib.SMTP_SSL('smtp.qq.com', 465)
        server.login('848786642@qq.com', 'ljbtvacrctjobfed')
        server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())
        server.quit()
        print('✅ 邮件发送成功！')
    except Exception as e:
        print(f'❌ 邮件发送失败: {e}')


if __name__ == '__main__':
    print('🌟 七星高照V1.7.2 — 2026年月线收益表格邮件')
    print('=' * 60)

    # 加载数据
    print('📂 加载A股ETF数据...')
    defensive_data = {}
    df_def = ss.load_or_download_etf(ss.DEFENSIVE_ETF)
    if not df_def.empty:
        defensive_data[ss.DEFENSIVE_ETF] = df_def

    large_pool_unique = list(dict.fromkeys(ss.ETF_POOL_LARGE))
    large_data = ss.load_all_etfs(large_pool_unique)
    all_data_large = {**defensive_data, **large_data}
    actual_defensive = list(defensive_data.keys())[0] if defensive_data else None

    print(f'  加载ETF: {len(all_data_large)}只')

    results = {}

    # 策略1: 无成交量过滤
    print('\n🔄 运行策略1: 七星高照-无成交量过滤...')
    r1_ret, r1_cum, r1_hold = run_backtest_extract_returns(
        all_data_large, large_pool_unique,
        '七星高照-无成交量过滤',
        use_volume_filter=False,
        defensive_etf_code=actual_defensive,
    )
    if r1_ret is not None:
        results['七星高照-无成交量过滤'] = (r1_ret, r1_cum, r1_hold)
        print(f'  ✅ 完成，2026年数据点: {(r1_ret.index >= pd.Timestamp(CHART_START)).sum()}')

    # 策略2: 大池完整版
    print('\n🔄 运行策略2: 七星高照-大池完整版...')
    r2_ret, r2_cum, r2_hold = run_backtest_extract_returns(
        all_data_large, large_pool_unique,
        '七星高照-大池完整版',
        use_volume_filter=True,
        defensive_etf_code=actual_defensive,
    )
    if r2_ret is not None:
        results['七星高照-大池完整版'] = (r2_ret, r2_cum, r2_hold)
        print(f'  ✅ 完成，2026年数据点: {(r2_ret.index >= pd.Timestamp(CHART_START)).sum()}')

    # 生成HTML
    print('\n📊 生成月线收益表格邮件...')
    html = generate_email_html(results)

    # 保存本地副本
    output_path = '/data/workspace/strategy_arena/qixing_2026_monthly_table.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  ✅ 本地副本: {output_path}')

    # 发送邮件
    print('\n📧 发送邮件...')
    send_email(html)

