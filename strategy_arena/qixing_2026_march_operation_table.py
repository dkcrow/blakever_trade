#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照V1.7.2 — 2026年3月无动量过滤策略操作明细表
本金10,000元，逐日展示操作、持仓、收益变化
"""

import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/data/workspace')
import seven_stars_etf_backtest as ss

# ========== 全局配置 ==========
INIT_CASH = 10_000  # 本金1万元
CHART_START = '2026-03-01'  # 3月开始
CHART_END = '2026-03-31'    # 3月末
MAR_START = '2026-03-01'
MAR_END = '2026-03-31'

# 修改模块全局日期范围以包含2026年数据
ss.START_DATE = '2021-01-01'
ss.END_DATE = '2026-04-24'

# 策略参数（无成交量过滤版）
LOOKBACK_DAYS = ss.LOOKBACK_DAYS       # 25天
HOLDINGS_NUM = ss.HOLDINGS_NUM         # 1只
FEES_RATE = ss.ETF_FEES                # ~0.06%
DEFENSIVE_ETF = ss.DEFENSIVE_ETF       # 511880

ETF_NAMES = ss.ETF_NAMES

# ========== 数据加载 ==========
def load_data():
    """加载所有ETF数据"""
    print('📂 加载A股ETF数据...')
    defensive_data = {}
    df_def = ss.load_or_download_etf(ss.DEFENSIVE_ETF)
    if not df_def.empty:
        defensive_data[ss.DEFENSIVE_ETF] = df_def
        actual_defensive = ss.DEFENSIVE_ETF
    else:
        actual_defensive = None

    large_pool_unique = list(dict.fromkeys(ss.ETF_POOL_LARGE))
    large_data = ss.load_all_etfs(large_pool_unique)
    all_data = {**defensive_data, **large_data}
    
    print(f'  加载ETF: {len(all_data)}只')
    return all_data, large_pool_unique, actual_defensive


def run_backtest_march(data, etf_pool, defensive_etf_code):
    """
    运行无成交量过滤策略回测，提取3月每日明细
    返回: portfolio_returns, cum, daily_holdings_list (3月区间)
    """
    # 构建日期索引
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

    # 构建价格矩阵
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

    # 逐日回测
    portfolio_returns = pd.Series(0.0, index=all_dates)
    prev_holdings = None
    trade_count = 0
    daily_holdings = []
    daily_holdings_list = []
    daily_actions = []  # 记录每日操作明细
    profit_protection_sold = set()
    warmup = LOOKBACK_DAYS + 20

    # 使用无成交量过滤参数
    use_volume_filter = False
    use_short_momentum = True
    use_profit_protection = True
    use_recent_drop_filter = True

    for i, date in enumerate(all_dates):
        profit_protection_sold = set()
        action_detail = {'date': date, 'action': '持有', 'sell': [], 'buy': [], 'reason': ''}

        # 热身期
        if i < warmup:
            target_holdings = [defensive_etf_code] if defensive_etf_code in close_prices.columns else [None]
            current_holding = target_holdings[0] if target_holdings else None
            daily_holdings.append(current_holding)
            daily_holdings_list.append(target_holdings)
            if current_holding and current_holding in close_prices.columns:
                r = close_prices.iloc[i][current_holding]
                prev_r = close_prices.iloc[i - 1][current_holding] if i > 0 else r
                daily_ret = (r / prev_r - 1) if prev_r > 0 else 0
                portfolio_returns.iloc[i] = daily_ret
            if prev_holdings is not None and prev_holdings != target_holdings:
                trade_count += 1
                portfolio_returns.iloc[i] -= FEES_RATE
                action_detail['action'] = '换仓'
                action_detail['reason'] = '热身期换入防御ETF'
            prev_holdings = target_holdings
            daily_actions.append(action_detail)
            continue

        # 盈利保护检查
        if use_profit_protection and prev_holdings is not None:
            for h in prev_holdings:
                if h and h in etf_pool and h in close_prices.columns:
                    current_price = close_prices.iloc[i][h]
                    high_hist = highs[h].iloc[:i]
                    if ss.check_profit_protection(high_hist, current_price):
                        profit_protection_sold.add(h)

        # 排名计算
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
            if len(close_hist) < LOOKBACK_DAYS + 1:
                continue

            current_price = close_hist.iloc[-1]
            if current_price <= 0 or np.isnan(current_price):
                continue

            # 盈利保护过滤
            if use_profit_protection and code in profit_protection_sold:
                continue

            # 成交量过滤（关闭）
            # if use_volume_filter: ...

            # 短期动量过滤
            if use_short_momentum:
                if not ss.check_short_momentum(close_hist):
                    continue

            # 动量得分
            metrics = ss.calculate_momentum_score(close_hist, LOOKBACK_DAYS)
            if metrics is None:
                continue

            if not (ss.MIN_SCORE_THRESHOLD < metrics['score'] < ss.MAX_SCORE_THRESHOLD):
                continue

            # 近3日跌幅过滤
            if use_recent_drop_filter and ss.check_recent_drop(close_hist):
                continue

            etf_metrics.append({
                'code': code,
                'name': ETF_NAMES.get(code, code),
                'score': metrics['score'],
                'annualized': metrics['annualized'],
                'r_squared': metrics['r_squared'],
                'current_price': current_price,
            })

        # 排序
        etf_metrics.sort(key=lambda x: x['score'], reverse=True)

        # 选择持仓
        target_holdings = []
        for m in etf_metrics:
            if len(target_holdings) >= HOLDINGS_NUM:
                break
            if use_profit_protection and m['code'] in profit_protection_sold:
                continue
            target_holdings.append(m['code'])

        # 防御模式
        if not target_holdings:
            if defensive_etf_code in close_prices.columns:
                target_holdings = [defensive_etf_code]
            else:
                target_holdings = [None]

        # 记录持仓
        daily_holdings_list.append(target_holdings)
        daily_holdings.append(target_holdings[0] if target_holdings else None)

        # 计算收益
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

        # 换仓成本 & 操作记录
        if prev_holdings is not None:
            prev_set = set([h for h in prev_holdings if h])
            cur_set = set([h for h in target_holdings if h])
            new_positions = cur_set - prev_set
            sold_positions = prev_set - cur_set
            if new_positions or sold_positions:
                trade_count += 1
                turnover_ratio = len(new_positions) / max(len(cur_set), 1)
                portfolio_returns.iloc[i] -= FEES_RATE * turnover_ratio
                action_detail['action'] = '换仓'
                action_detail['sell'] = list(sold_positions)
                action_detail['buy'] = list(new_positions)
                action_detail['reason'] = '动量排名更新'
            else:
                action_detail['action'] = '持有'
        else:
            # 首次建仓
            if target_holdings and target_holdings != [defensive_etf_code]:
                action_detail['action'] = '建仓'
                action_detail['buy'] = [h for h in target_holdings if h]
                action_detail['reason'] = '热身期结束，首次建仓'

        prev_holdings = target_holdings
        daily_actions.append(action_detail)

    cum = (1 + portfolio_returns).cumprod()
    return portfolio_returns, cum, daily_holdings_list, daily_actions


def build_march_table(port_ret, cum, holdings_list, actions, strategy_name):
    """构建3月操作+收益明细表"""
    # 筛选3月数据
    mar_mask = (port_ret.index >= pd.Timestamp(MAR_START)) & (port_ret.index <= pd.Timestamp(MAR_END))
    mar_dates = port_ret.index[mar_mask]
    
    if len(mar_dates) == 0:
        print("❌ 2026年3月无交易数据")
        return None

    # 找3月之前的累计净值（作为起始基准）
    pre_mar_mask = cum.index < pd.Timestamp(MAR_START)
    if pre_mar_mask.any():
        cum_start = cum[pre_mar_mask].iloc[-1]
    else:
        cum_start = 1.0

    rows = []
    for i, date in enumerate(mar_dates):
        idx_all = list(port_ret.index).index(date)
        
        # 当日收益率
        daily_ret = port_ret.iloc[idx_all]
        
        # 累计净值（相对于全局起点）
        cum_val = cum.iloc[idx_all]
        
        # 3月起始后的累计净值（相对于3月1日）
        cum_mar = cum_val / cum_start
        
        # 账户净值 = 本金 × 3月累计净值
        account_value = INIT_CASH * cum_mar
        
        # 当日盈亏 = 本金 × 当日收益率
        daily_pnl = INIT_CASH * daily_ret
        
        # 累计盈亏 = 本金 × (3月累计净值 - 1)
        cum_pnl = INIT_CASH * (cum_mar - 1)
        
        # 持仓信息
        if idx_all < len(holdings_list):
            holdings = holdings_list[idx_all]
        else:
            holdings = []
        
        holding_names = [ETF_NAMES.get(h, h) if h else '货币基金' for h in holdings]
        holding_str = ' + '.join(holding_names) if holding_names else '—'
        
        # 持仓比例（等权）
        if holdings and holdings[0]:
            n_hold = len([h for h in holdings if h])
            pct_per = 100 / n_hold if n_hold > 0 else 0
            holding_pct = ', '.join([f"{ETF_NAMES.get(h, h) if h else '货币基金'}: {pct_per:.1f}%" for h in holdings if h])
        else:
            holding_pct = '货币基金: 100%'
        
        # 操作信息
        if idx_all < len(actions):
            act = actions[idx_all]
        else:
            act = {'action': '—', 'sell': [], 'buy': [], 'reason': ''}
        
        action_str = act.get('action', '—')
        if action_str == '换仓':
            sell_names = [ETF_NAMES.get(s, s) for s in act.get('sell', [])]
            buy_names = [ETF_NAMES.get(b, b) for b in act.get('buy', [])]
            action_detail = f"卖出{', '.join(sell_names)} → 买入{', '.join(buy_names)}"
        elif action_str == '建仓':
            buy_names = [ETF_NAMES.get(b, b) for b in act.get('buy', [])]
            action_detail = f"买入{', '.join(buy_names)}"
        else:
            action_detail = '持有'
        
        reason = act.get('reason', '')
        
        rows.append({
            '日期': date.strftime('%Y-%m-%d'),
            '星期': ['一', '二', '三', '四', '五'][date.weekday()],
            '操作': action_str,
            '操作明细': action_detail,
            '持仓ETF': holding_str,
            '持仓比例': holding_pct,
            '当日收益率': f"{daily_ret*100:+.4f}%",
            '当日盈亏': f"{daily_pnl:+.2f}元",
            '累计净值': f"{cum_mar:.6f}",
            '账户净值': f"{account_value:.2f}元",
            '累计盈亏': f"{cum_pnl:+.2f}元",
        })
    
    return pd.DataFrame(rows)


def generate_march_html(march_df, strategy_name, stats):
    """生成3月操作+收益表的HTML邮件"""
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>七星高照V1.7.2 — 2026年3月操作明细</title>
<style>
  body { margin:0; padding:0; background:#0c0c14; color:#e5e7eb; font-family:'PingFang SC','Microsoft YaHei',-apple-system,sans-serif; }
  .container { max-width:1100px; margin:0 auto; padding:20px; }
  h1 { margin:0; font-size:24px; color:#f97316; text-shadow:0 0 20px rgba(249,115,22,0.3); }
  .subtitle { margin:6px 0 0; color:#9ca3af; font-size:13px; }
  .stats-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:20px 0; }
  .stat-card { background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid #2d2d44; border-radius:10px; padding:14px; text-align:center; }
  .stat-label { font-size:11px; color:#9ca3af; margin-bottom:4px; }
  .stat-value { font-size:20px; font-weight:700; }
  .stat-green { color:#22c55e; }
  .stat-red { color:#ef4444; }
  .stat-blue { color:#60a5fa; }
  .table-wrap { background:linear-gradient(135deg,#1a1a2e,#16213e); border:1px solid #2d2d44; border-radius:12px; padding:16px; margin-bottom:16px; overflow-x:auto; }
  .section-title { font-size:16px; color:#f97316; font-weight:700; border-left:4px solid #f97316; padding-left:10px; margin-bottom:12px; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  thead tr { background:#1f2937; }
  th { padding:6px 8px; text-align:left; color:#9ca3af; border-bottom:2px solid #2d2d44; white-space:nowrap; }
  td { padding:6px 8px; border-bottom:1px solid #1f2937; white-space:nowrap; }
  .action-trade { color:#f97316; font-weight:600; }
  .action-hold { color:#6b7280; }
  .action-buy { color:#22c55e; font-weight:600; }
  .ret-pos { color:#22c55e; }
  .ret-neg { color:#ef4444; }
  .ret-zero { color:#6b7280; }
  .footer { text-align:center; color:#6b7280; font-size:11px; margin-top:20px; padding:16px 0; }
  @media (max-width:768px) { .stats-grid { grid-template-columns:repeat(2,1fr); } table { font-size:11px; } }
</style>
</head>
<body>
<div class="container">

<div style="text-align:center;padding:24px 0 8px;">
  <h1>🌟 七星高照ETF轮动 V1.7.2</h1>
  <p class="subtitle">2026年3月操作明细 | 本金10,000元 | ''' + strategy_name + '''</p>
</div>

<!-- 3月总览 -->
<div class="stats-grid">
'''
    # 统计卡片
    items = [
        ('3月收益', stats['mar_ret'], 'stat-green' if float(stats['mar_ret'].rstrip('%')) >= 0 else 'stat-red'),
        ('3月胜率', stats['win_rate'], 'stat-blue'),
        ('最大单日盈利', stats['max_gain'], 'stat-green'),
        ('最大单日亏损', stats['max_loss'], 'stat-red'),
        ('换仓次数', stats['trade_count'], 'stat-blue'),
        ('3月回撤', stats['mar_dd'], 'stat-red'),
        ('期末净值', stats['end_value'], 'stat-green' if float(stats['end_value'].rstrip('元')) >= INIT_CASH else 'stat-red'),
        ('累计盈亏', stats['cum_pnl'], 'stat-green' if float(stats['cum_pnl'].rstrip('元').replace('+','')) >= 0 else 'stat-red'),
    ]
    
    for i, (label, value, cls) in enumerate(items):
        if i % 4 == 0:
            html += '</div>\n<div class="stats-grid">\n'
        html += f'''  <div class="stat-card">
    <div class="stat-label">{label}</div>
    <div class="stat-value {cls}">{value}</div>
  </div>
'''
    html += '</div>\n'

    # 操作明细表
    html += '''
<div class="table-wrap">
  <div class="section-title">📋 每日操作明细</div>
  <table>
    <thead>
      <tr>
        <th>日期</th>
        <th>星期</th>
        <th>操作</th>
        <th>操作明细</th>
        <th>持仓ETF</th>
        <th>持仓比例</th>
        <th>当日收益率</th>
        <th>当日盈亏</th>
        <th>累计净值</th>
        <th>账户净值</th>
        <th>累计盈亏</th>
      </tr>
    </thead>
    <tbody>
'''
    
    for _, row in march_df.iterrows():
        # 收益率着色
        ret_str = row['当日收益率']
        if ret_str.startswith('+'):
            ret_cls = 'ret-pos'
        elif ret_str.startswith('-'):
            ret_cls = 'ret-neg'
        else:
            ret_cls = 'ret-zero'
        
        # 盈亏着色
        pnl_str = row['当日盈亏']
        if '+元' in pnl_str:
            pnl_cls = 'ret-pos'
        elif '-元' in pnl_str:
            pnl_cls = 'ret-neg'
        else:
            pnl_cls = 'ret-zero'
        
        cum_pnl_str = row['累计盈亏']
        if '+元' in cum_pnl_str:
            cp_cls = 'ret-pos'
        elif '-元' in cum_pnl_str:
            cp_cls = 'ret-neg'
        else:
            cp_cls = 'ret-zero'
        
        # 操作着色
        action = row['操作']
        if action == '换仓':
            act_cls = 'action-trade'
        elif action == '建仓':
            act_cls = 'action-buy'
        else:
            act_cls = 'action-hold'
        
        html += f'''      <tr>
        <td>{row['日期']}</td>
        <td>周{row['星期']}</td>
        <td class="{act_cls}">{row['操作']}</td>
        <td>{row['操作明细']}</td>
        <td>{row['持仓ETF']}</td>
        <td>{row['持仓比例']}</td>
        <td class="{ret_cls}">{row['当日收益率']}</td>
        <td class="{pnl_cls}">{row['当日盈亏']}</td>
        <td>{row['累计净值']}</td>
        <td>{row['账户净值']}</td>
        <td class="{cp_cls}">{row['累计盈亏']}</td>
      </tr>
'''
    
    html += '''    </tbody>
  </table>
</div>
'''

    # 持仓变化图（纯CSS柱状图）
    html += '''
<div class="table-wrap">
  <div class="section-title">📊 每日持仓变化</div>
  <table>
    <thead>
      <tr>
        <th>日期</th>
        <th>持仓ETF</th>
        <th>当日收益率</th>
        <th>累计净值</th>
      </tr>
    </thead>
    <tbody>
'''
    for _, row in march_df.iterrows():
        ret_str = row['当日收益率']
        if ret_str.startswith('+'):
            ret_cls = 'ret-pos'
        elif ret_str.startswith('-'):
            ret_cls = 'ret-neg'
        else:
            ret_cls = 'ret-zero'
        
        # 持仓着色
        holding = row['持仓ETF']
        if '黄金' in holding:
            h_cls = 'color:#f97316;'
        elif '货币' in holding or '银华' in holding:
            h_cls = 'color:#22c55e;'
        elif '纳指' in holding or '标普' in holding or '道琼斯' in holding:
            h_cls = 'color:#3b82f6;'
        elif '创业板' in holding or '科创' in holding:
            h_cls = 'color:#a855f7;'
        elif '恒生' in holding or '港股' in holding or '中概' in holding:
            h_cls = 'color:#ec4899;'
        elif '有色' in holding or '白银' in holding or '原油' in holding or '豆粕' in holding or '能源' in holding:
            h_cls = 'color:#eab308;'
        elif '沪深' in holding or '上证' in holding or '中证' in holding or '红利' in holding or '价值' in holding:
            h_cls = 'color:#14b8a6;'
        else:
            h_cls = 'color:#60a5fa;'
        
        html += f'''      <tr>
        <td>{row['日期']}</td>
        <td style="{h_cls}font-weight:600;">{row['持仓ETF']}</td>
        <td class="{ret_cls}">{row['当日收益率']}</td>
        <td>{row['累计净值']}</td>
      </tr>
'''
    
    html += '''    </tbody>
  </table>
</div>
'''

    # 收益曲线（纯CSS实现）
    html += '''
<div class="table-wrap">
  <div class="section-title">📈 3月累计净值曲线</div>
'''
    
    # 获取净值数据
    cum_vals = []
    for _, row in march_df.iterrows():
        cum_vals.append(float(row['累计净值']))
    
    if cum_vals:
        min_cum = min(cum_vals)
        max_cum = max(cum_vals)
        range_cum = max_cum - min_cum if max_cum != min_cum else 1
        
        html += '  <div style="display:flex;align-items:flex-end;height:120px;gap:2px;margin:12px 0;">\n'
        for i, cv in enumerate(cum_vals):
            height = ((cv - min_cum) / range_cum) * 100 + 5
            if cv >= 1:
                bar_color = '#22c55e'
            else:
                bar_color = '#ef4444'
            date_label = march_df.iloc[i]['日期'][-5:]  # MM-DD
            html += f'    <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;">\n'
            html += f'      <div style="width:100%;height:{height}%;background:{bar_color};opacity:0.7;border-radius:2px 2px 0 0;min-height:2px;"></div>\n'
            html += f'      <div style="font-size:8px;color:#9ca3af;margin-top:2px;white-space:nowrap;">{date_label}</div>\n'
            html += f'    </div>\n'
        html += '  </div>\n'
    
    html += '</div>\n'

    # 页脚
    from datetime import datetime
    html += f'''
<div class="footer">
  <p>七星高照ETF轮动 V1.7.2 | 本金: ¥10,000 | 策略: {strategy_name} | 数据来源: 本地CSV日频数据</p>
  <p>⚠️ 回测结果不代表未来表现，仅供研究参考</p>
  <p>生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</div>

</div>
</body>
</html>
'''
    return html


def send_email(html_content):
    """发送HTML邮件"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart('alternative')
    msg['Subject'] = '【3月操作明细】七星高照V1.7.2 2026年3月无动量过滤策略'
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
    print('🌟 七星高照V1.7.2 — 2026年3月操作明细表')
    print('=' * 60)

    # 加载数据
    all_data, etf_pool, actual_defensive = load_data()
    
    # 运行回测（无成交量过滤版）
    print('\n🔄 运行回测: 七星高照-无成交量过滤（3月区间）...')
    strategy_name = '七星高照-无成交量过滤'
    port_ret, cum, holdings_list, actions = run_backtest_march(
        all_data, etf_pool, actual_defensive
    )
    
    if port_ret is None:
        print('❌ 回测失败')
        sys.exit(1)
    
    print(f'  ✅ 回测完成')

    # 构建3月操作表
    print('\n📊 生成3月操作明细表...')
    march_df = build_march_table(port_ret, cum, holdings_list, actions, strategy_name)
    
    if march_df is None:
        print('❌ 3月数据为空')
        sys.exit(1)
    
    # 计算3月统计
    mar_mask = (port_ret.index >= pd.Timestamp(MAR_START)) & (port_ret.index <= pd.Timestamp(MAR_END))
    mar_ret = port_ret[mar_mask]
    
    # 3月之前的累计净值
    pre_mar_cum = cum[cum.index < pd.Timestamp(MAR_START)]
    cum_start_mar = pre_mar_cum.iloc[-1] if len(pre_mar_cum) > 0 else 1.0
    
    # 3月累计净值
    mar_cum = cum[mar_mask]
    cum_end_mar = mar_cum.iloc[-1] if len(mar_cum) > 0 else cum_start_mar
    
    mar_total_ret = (cum_end_mar / cum_start_mar - 1) * 100
    mar_ret_val = INIT_CASH * (cum_end_mar / cum_start_mar - 1)
    mar_win_rate = (mar_ret > 0).mean() * 100
    mar_max_gain = mar_ret.max() * INIT_CASH
    mar_max_loss = mar_ret.min() * INIT_CASH
    
    # 3月内回撤
    mar_cum_norm = mar_cum / cum_start_mar
    running_max = mar_cum_norm.cummax()
    mar_dd = abs(((mar_cum_norm - running_max) / running_max).min()) * 100
    
    # 换仓次数
    mar_actions = [actions[list(port_ret.index).index(d)] for d in mar_ret.index if d in list(port_ret.index)]
    trade_count = sum(1 for a in mar_actions if a.get('action') in ['换仓', '建仓'])
    
    stats = {
        'mar_ret': f'{mar_total_ret:+.2f}%',
        'win_rate': f'{mar_win_rate:.0f}%',
        'max_gain': f'{mar_max_gain:+.2f}元',
        'max_loss': f'{mar_max_loss:+.2f}元',
        'trade_count': str(trade_count),
        'mar_dd': f'{mar_dd:.2f}%',
        'end_value': f'{INIT_CASH * cum_end_mar / cum_start_mar:.2f}元',
        'cum_pnl': f'{mar_ret_val:+.2f}元',
    }
    
    # 打印3月统计
    print(f'\n📊 3月统计:')
    print(f'  3月收益: {mar_total_ret:+.2f}%')
    print(f'  3月胜率: {mar_win_rate:.0f}%')
    print(f'  最大单日盈利: {mar_max_gain:+.2f}元')
    print(f'  最大单日亏损: {mar_max_loss:+.2f}元')
    print(f'  换仓次数: {trade_count}')
    print(f'  3月内回撤: {mar_dd:.2f}%')
    print(f'  期末账户: {INIT_CASH * cum_end_mar / cum_start_mar:.2f}元')
    print(f'  累计盈亏: {mar_ret_val:+.2f}元')
    
    # 生成HTML
    print('\n📊 生成HTML邮件...')
    html = generate_march_html(march_df, strategy_name, stats)
    
    # 保存本地副本
    output_path = '/data/workspace/strategy_arena/qixing_2026_march_operation_table.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  ✅ 本地副本: {output_path}')
    
    # 发送邮件
    print('\n📧 发送邮件...')
    send_email(html)
    
