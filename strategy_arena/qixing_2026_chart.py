#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股排行榜前二策略 2026年日线收益图
使用原始 seven_stars_etf_backtest.py 策略代码
"""
import sys, os, json, math
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/data/workspace')

# ====== 直接内嵌核心回测逻辑，提取每日收益率序列 ======
import seven_stars_etf_backtest as ss

# 关键：修改模块的全局日期范围，使数据加载包含2026年
ss.START_DATE = '2021-01-01'
ss.END_DATE = '2026-04-24'

# 回测区间：包含2026年
BT_START = '2021-01-01'
BT_END = '2026-04-24'

# 只看2026年
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

    # 计算累计净值
    cum = (1 + portfolio_returns).cumprod()
    
    return portfolio_returns, cum, daily_holdings


def generate_chart_html(returns_data, output_path):
    """生成包含两个策略2026年日线收益的HTML图表"""
    
    # 提取2026年数据
    charts = {}
    for name, (port_ret, cum, holdings) in returns_data.items():
        mask = port_ret.index >= pd.Timestamp(CHART_START)
        ret_2026 = port_ret[mask]
        cum_2026 = cum[mask]
        hold_2026 = holdings[-len(ret_2026):] if len(holdings) >= len(ret_2026) else holdings
        
        # 重新计算从2026年初开始的净值（归一化到1）
        if len(cum_2026) > 0:
            cum_norm = cum_2026 / cum_2026.iloc[0]
        else:
            cum_norm = cum_2026
        
        charts[name] = {
            'dates': [d.strftime('%Y-%m-%d') for d in ret_2026.index],
            'daily_ret': [round(v * 100, 3) for v in ret_2026.values],
            'cum_norm': [round(v, 4) for v in cum_norm.values],
            'holdings': hold_2026[-len(ret_2026):] if len(hold_2026) >= len(ret_2026) else hold_2026,
        }
    
    # 计算统计
    stats = {}
    for name, c in charts.items():
        rets = np.array(c['daily_ret'])
        cum_v = np.array(c['cum_norm'])
        if len(rets) > 0:
            total_ret = (cum_v[-1] / cum_v[0] - 1) * 100 if cum_v[0] > 0 else 0
            n_days = len(rets)
            ann_ret = ((cum_v[-1] / cum_v[0]) ** (252 / max(n_days, 1)) - 1) * 100 if cum_v[0] > 0 else 0
            sharpe = (np.mean(rets) * 252 - 0.02) / (np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else 0
            max_dd = 0
            peak = cum_v[0]
            for v in cum_v:
                if v > peak:
                    peak = v
                dd = (v - peak) / peak
                if dd < max_dd:
                    max_dd = dd
            win_rate = (rets > 0).mean() * 100
            max_daily_gain = rets.max()
            max_daily_loss = rets.min()
        else:
            total_ret = ann_ret = sharpe = max_dd = win_rate = max_daily_gain = max_daily_loss = 0
        
        stats[name] = {
            'total_ret': round(total_ret, 2),
            'ann_ret': round(ann_ret, 2),
            'sharpe': round(sharpe, 2),
            'max_dd': round(abs(max_dd) * 100, 2),
            'win_rate': round(win_rate, 1),
            'max_gain': round(max_daily_gain, 3),
            'max_loss': round(max_daily_loss, 3),
            'n_days': len(rets),
        }
    
    # 持仓分布统计
    holding_stats = {}
    for name, c in charts.items():
        from collections import Counter
        h_counts = Counter([h for h in c['holdings'] if h])
        total_h = sum(h_counts.values())
        if total_h > 0:
            holding_stats[name] = {
                ss.ETF_NAMES.get(k, k): round(v / total_h * 100, 1)
                for k, v in h_counts.most_common(10)
            }
        else:
            holding_stats[name] = {}
    
    # 生成HTML
    colors = {
        '七星高照-无成交量过滤': {'line': '#f97316', 'bar': 'rgba(249,115,22,0.6)'},
        '七星高照-大池完整版': {'line': '#3b82f6', 'bar': 'rgba(59,130,246,0.6)'},
    }
    
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>七星高照V1.7.2 — 2026年日线收益图</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0c0c14; color:#e5e7eb; font-family:'PingFang SC','Microsoft YaHei',sans-serif; }
.container { max-width:1400px; margin:0 auto; padding:20px; }
h1 { text-align:center; font-size:28px; color:#f97316; margin:20px 0 10px; text-shadow:0 0 20px rgba(249,115,22,0.3); }
h2 { font-size:18px; color:#f97316; margin:30px 0 15px; border-left:4px solid #f97316; padding-left:12px; }
.subtitle { text-align:center; color:#9ca3af; font-size:14px; margin-bottom:30px; }
.stats-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:16px; margin-bottom:30px; }
.stat-card { background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid #2d2d44; border-radius:12px; padding:20px; }
.stat-card h3 { font-size:16px; color:#f97316; margin-bottom:12px; display:flex; align-items:center; gap:8px; }
.stat-card h3 .badge { font-size:11px; background:#f97316; color:#000; padding:2px 8px; border-radius:4px; font-weight:700; }
.stat-row { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:8px; }
.stat-item { text-align:center; }
.stat-item .label { font-size:11px; color:#9ca3af; margin-bottom:4px; }
.stat-item .value { font-size:18px; font-weight:700; }
.stat-item .value.pos { color:#22c55e; }
.stat-item .value.neg { color:#ef4444; }
.stat-item .value.neu { color:#60a5fa; }
.chart-box { background:#111827; border:1px solid #2d2d44; border-radius:12px; padding:16px; margin-bottom:20px; }
.chart-container { width:100%; height:450px; }
.holding-section { margin-top:20px; }
.holding-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:16px; }
.holding-card { background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid #2d2d44; border-radius:12px; padding:16px; }
.holding-card h4 { color:#f97316; font-size:14px; margin-bottom:10px; }
.holding-bar { display:flex; align-items:center; margin-bottom:6px; font-size:12px; }
.holding-bar .name { width:120px; color:#9ca3af; text-align:right; padding-right:10px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.holding-bar .bar-bg { flex:1; height:16px; background:#1f2937; border-radius:4px; overflow:hidden; position:relative; }
.holding-bar .bar-fill { height:100%; border-radius:4px; transition:width 0.3s; }
.holding-bar .pct { width:50px; text-align:right; color:#e5e7eb; }
.footer { text-align:center; color:#6b7280; font-size:12px; margin-top:30px; padding:20px; }
</style>
</head>
<body>
<div class="container">
<h1>🌟 七星高照ETF轮动 V1.7.2</h1>
<p class="subtitle">2026年日线收益表现 | 回测区间：2026-01-01 ~ 2026-04-24</p>

<div class="stats-grid">
'''
    
    # 统计卡片
    for name, s in stats.items():
        c = colors.get(name, {'line':'#f97316','bar':'rgba(249,115,22,0.6)'})
        tr_cls = 'pos' if s['total_ret'] >= 0 else 'neg'
        ar_cls = 'pos' if s['ann_ret'] >= 0 else 'neg'
        html += f'''
<div class="stat-card">
<h3>{name} <span class="badge">{s["n_days"]}个交易日</span></h3>
<div class="stat-row">
  <div class="stat-item"><div class="label">区间收益</div><div class="value {tr_cls}">{s["total_ret"]:+.2f}%</div></div>
  <div class="stat-item"><div class="label">年化收益</div><div class="value {ar_cls}">{s["ann_ret"]:+.2f}%</div></div>
  <div class="stat-item"><div class="label">夏普比率</div><div class="value neu">{s["sharpe"]:.2f}</div></div>
  <div class="stat-item"><div class="label">最大回撤</div><div class="value neg">{s["max_dd"]:.2f}%</div></div>
</div>
<div class="stat-row">
  <div class="stat-item"><div class="label">胜率</div><div class="value neu">{s["win_rate"]:.1f}%</div></div>
  <div class="stat-item"><div class="label">最大单日盈利</div><div class="value pos">{s["max_gain"]:+.3f}%</div></div>
  <div class="stat-item"><div class="label">最大单日亏损</div><div class="value neg">{s["max_loss"]:+.3f}%</div></div>
  <div class="stat-item"><div class="label">交易日数</div><div class="value neu">{s["n_days"]}</div></div>
</div>
</div>
'''
    
    html += '</div>\n'
    
    # 图表1: 累计净值曲线
    html += '''
<div class="chart-box">
<h2>📈 累计净值曲线（归一化至1.0）</h2>
<div id="chart_cum" class="chart-container"></div>
</div>
'''
    
    # 图表2: 日收益率柱状图
    html += '''
<div class="chart-box">
<h2>📊 日收益率分布</h2>
<div id="chart_daily" class="chart-container"></div>
</div>
'''
    
    # 图表3: 滚动夏普
    html += '''
<div class="chart-box">
<h2>📉 20日滚动夏普比率</h2>
<div id="chart_rolling_sharpe" class="chart-container"></div>
</div>
'''
    
    # 图表4: 回撤
    html += '''
<div class="chart-box">
<h2>🔻 回撤曲线</h2>
<div id="chart_drawdown" class="chart-container"></div>
</div>
'''
    
    # 持仓分布
    html += '''
<div class="holding-section">
<h2>🏦 2026年持仓分布</h2>
<div class="holding-grid">
'''
    
    holding_colors = ['#f97316','#3b82f6','#22c55e','#a855f7','#ec4899','#eab308','#14b8a6','#6366f1','#ef4444','#06b6d4']
    for name, h_dist in holding_stats.items():
        html += f'<div class="holding-card"><h4>{name}</h4>'
        for idx, (etf_name, pct) in enumerate(h_dist.items()):
            c = holding_colors[idx % len(holding_colors)]
            bar_w = min(pct, 100)
            html += f'''<div class="holding-bar">
<div class="name" title="{etf_name}">{etf_name}</div>
<div class="bar-bg"><div class="bar-fill" style="width:{bar_w}%;background:{c}"></div></div>
<div class="pct">{pct}%</div>
</div>'''
        html += '</div>'
    
    html += '</div></div>'
    
    # 交易日明细表
    html += '''
<div class="chart-box" style="margin-top:20px;">
<h2>📋 2026年交易日明细（最近20个交易日）</h2>
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-size:12px;">
<thead>
<tr style="background:#1f2937;">
<th style="padding:8px;text-align:left;color:#9ca3af;">日期</th>
'''
    for name in charts:
        html += f'<th style="padding:8px;text-align:right;color:#9ca3af;">{name[:8]}收益%</th>'
    for name in charts:
        html += f'<th style="padding:8px;text-align:left;color:#9ca3af;">{name[:8]}持仓</th>'
    html += '</tr></thead><tbody>'
    
    n_names = list(charts.keys())
    n_days = len(charts[n_names[0]]['dates']) if n_names else 0
    start_row = max(0, n_days - 20)
    for i in range(start_row, n_days):
        bg = '#111827' if i % 2 == 0 else '#0f172a'
        html += f'<tr style="background:{bg};">'
        html += f'<td style="padding:6px 8px;color:#9ca3af;">{charts[n_names[0]]["dates"][i]}</td>'
        for name in n_names:
            v = charts[name]['daily_ret'][i]
            cls = 'color:#22c55e' if v >= 0 else 'color:#ef4444'
            html += f'<td style="padding:6px 8px;text-align:right;{cls}">{v:+.3f}</td>'
        for name in n_names:
            h = charts[name]['holdings'][i] if i < len(charts[name]['holdings']) else '-'
            h_name = ss.ETF_NAMES.get(h, h) if h and h != '-' else '货币基金'
            html += f'<td style="padding:6px 8px;color:#60a5fa;">{h_name}</td>'
        html += '</tr>'
    html += '</tbody></table></div></div>'
    
    # Footer
    html += '''
<div class="footer">
<p>七星高照ETF轮动 V1.7.2 | 数据来源：本地CSV日频数据 | 回测引擎：逐日循环</p>
<p>⚠️ 回测结果不代表未来表现，仅供研究参考</p>
</div>
</div>
'''
    
    # JavaScript
    dates_js = json.dumps(charts[n_names[0]]['dates'])
    
    series_cum = []
    series_daily = []
    series_rolling_sharpe = []
    series_dd = []
    for name, c in charts.items():
        clr = colors.get(name, {'line':'#f97316','bar':'rgba(249,115,22,0.6)'})
        series_cum.append({
            'name': name,
            'type': 'line',
            'data': c['cum_norm'],
            'smooth': True,
            'lineStyle': {'width': 2.5, 'color': clr['line']},
            'itemStyle': {'color': clr['line']},
            'symbol': 'none',
        })
        series_daily.append({
            'name': name,
            'type': 'bar',
            'data': c['daily_ret'],
            'itemStyle': {'color': clr['bar']},
        })
        # 滚动夏普
        rets = np.array(c['daily_ret'])
        rolling_sharpe = []
        for j in range(len(rets)):
            if j < 20:
                rolling_sharpe.append(None)
            else:
                window = rets[j-20:j]
                if np.std(window) > 0:
                    rs = (np.mean(window) * 252 - 2) / (np.std(window) * np.sqrt(252))
                    rolling_sharpe.append(round(rs, 2))
                else:
                    rolling_sharpe.append(0)
        series_rolling_sharpe.append({
            'name': name,
            'type': 'line',
            'data': rolling_sharpe,
            'smooth': True,
            'lineStyle': {'width': 2, 'color': clr['line']},
            'itemStyle': {'color': clr['line']},
            'symbol': 'none',
        })
        # 回撤
        cum_arr = np.array(c['cum_norm'])
        dd_arr = []
        peak = cum_arr[0] if len(cum_arr) > 0 else 1
        for v in cum_arr:
            if v > peak:
                peak = v
            dd_arr.append(round((v - peak) / peak * 100, 3))
        series_dd.append({
            'name': name,
            'type': 'line',
            'data': dd_arr,
            'smooth': True,
            'lineStyle': {'width': 2, 'color': clr['line']},
            'itemStyle': {'color': clr['line']},
            'areaStyle': {'color': clr['line'], 'opacity': 0.15},
            'symbol': 'none',
        })
    
    html += f'''
<script>
var dates = {dates_js};
var seriesCum = {json.dumps(series_cum)};
var seriesDaily = {json.dumps(series_daily)};
var seriesRollingSharpe = {json.dumps(series_rolling_sharpe)};
var seriesDD = {json.dumps(series_dd)};

function makeGrid() {{
    return {{
        left: '5%', right: '3%', top: '12%', bottom: '8%',
        containLabel: true
    }};
}}
function makeTooltip() {{
    return {{
        trigger: 'axis',
        backgroundColor: 'rgba(17,24,39,0.95)',
        borderColor: '#2d2d44',
        textStyle: {{ color: '#e5e7eb', fontSize: 12 }},
        axisPointer: {{ type: 'cross', crossStyle: {{ color: '#999' }} }}
    }};
}}
function makeXAxis() {{
    return {{
        type: 'category',
        data: dates,
        axisLine: {{ lineStyle: {{ color: '#2d2d44' }} }},
        axisLabel: {{ color: '#9ca3af', fontSize: 10, rotate: 30 }},
        splitLine: {{ show: false }}
    }};
}}

// 累计净值
var c1 = echarts.init(document.getElementById('chart_cum'));
c1.setOption({{
    tooltip: makeTooltip(),
    legend: {{ data: {json.dumps(list(charts.keys()))}, textStyle: {{ color: '#9ca3af' }}, top: 5 }},
    grid: makeGrid(),
    xAxis: makeXAxis(),
    yAxis: {{
        type: 'value',
        scale: true,
        axisLine: {{ lineStyle: {{ color: '#2d2d44' }} }},
        axisLabel: {{ color: '#9ca3af', fontSize: 11, formatter: '{{value}}' }},
        splitLine: {{ lineStyle: {{ color: '#1f2937' }} }}
    }},
    series: seriesCum,
    dataZoom: [{{ type: 'inside' }}]
}});

// 日收益率
var c2 = echarts.init(document.getElementById('chart_daily'));
c2.setOption({{
    tooltip: makeTooltip(),
    legend: {{ data: {json.dumps(list(charts.keys()))}, textStyle: {{ color: '#9ca3af' }}, top: 5 }},
    grid: makeGrid(),
    xAxis: makeXAxis(),
    yAxis: {{
        type: 'value',
        axisLine: {{ lineStyle: {{ color: '#2d2d44' }} }},
        axisLabel: {{ color: '#9ca3af', fontSize: 11, formatter: '{{value}}%' }},
        splitLine: {{ lineStyle: {{ color: '#1f2937' }} }}
    }},
    series: seriesDaily,
    dataZoom: [{{ type: 'inside' }}]
}});

// 滚动夏普
var c3 = echarts.init(document.getElementById('chart_rolling_sharpe'));
c3.setOption({{
    tooltip: makeTooltip(),
    legend: {{ data: {json.dumps(list(charts.keys()))}, textStyle: {{ color: '#9ca3af' }}, top: 5 }},
    grid: makeGrid(),
    xAxis: makeXAxis(),
    yAxis: {{
        type: 'value',
        axisLine: {{ lineStyle: {{ color: '#2d2d44' }} }},
        axisLabel: {{ color: '#9ca3af', fontSize: 11 }},
        splitLine: {{ lineStyle: {{ color: '#1f2937' }} }}
    }},
    visualMap: {{
        show: false,
        pieces: [
            {{ gt: 0, color: '#22c55e' }},
            {{ lte: 0, color: '#ef4444' }}
        ]
    }},
    series: seriesRollingSharpe,
    dataZoom: [{{ type: 'inside' }}]
}});

// 回撤
var c4 = echarts.init(document.getElementById('chart_drawdown'));
c4.setOption({{
    tooltip: makeTooltip(),
    legend: {{ data: {json.dumps(list(charts.keys()))}, textStyle: {{ color: '#9ca3af' }}, top: 5 }},
    grid: makeGrid(),
    xAxis: makeXAxis(),
    yAxis: {{
        type: 'value',
        axisLine: {{ lineStyle: {{ color: '#2d2d44' }} }},
        axisLabel: {{ color: '#9ca3af', fontSize: 11, formatter: '{{value}}%' }},
        splitLine: {{ lineStyle: {{ color: '#1f2937' }} }}
    }},
    series: seriesDD,
    dataZoom: [{{ type: 'inside' }}]
}});

window.addEventListener('resize', function() {{
    c1.resize(); c2.resize(); c3.resize(); c4.resize();
}});
</script>
</body>
</html>
'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  ✅ 图表已生成: {output_path}')


if __name__ == '__main__':
    print('🌟 七星高照V1.7.2 — 2026年日线收益图生成')
    print('='*60)
    
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
    
    # 修改回测区间
    ss.START_DATE = BT_START
    ss.END_DATE = BT_END
    
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
        # 全区间统计
        total_ret = (r1_cum.iloc[-1] / r1_cum.iloc[0] - 1) * 100
        print(f'  全区间年化: {ss.backtest_seven_stars(all_data_large, large_pool_unique, "x", use_volume_filter=False, defensive_etf_code=actual_defensive)["annual_return"]}%')
    
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
    
    # 生成图表
    print('\n📊 生成2026年日线收益图...')
    output_path = '/data/workspace/strategy_arena/qixing_2026_daily_chart.html'
    generate_chart_html(results, output_path)
    
    # 恢复原始区间
    ss.START_DATE = '2021-01-01'
    ss.END_DATE = '2025-04-24'
    
