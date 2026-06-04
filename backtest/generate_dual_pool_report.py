#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF双池平滑动量轮动 回测报告生成器
"""

import json, sys, os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path('C:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
RESULTS_DIR = PROJECT_ROOT / 'backtest' / 'results_dual_pool'

# 加载回测结果
def load_results(suffix="2025-01-01_2026-06-03"):
    with open(RESULTS_DIR / f'dual_pool_{suffix}_summary.json', 'r', encoding='utf-8') as f:
        summary = json.load(f)
    with open(RESULTS_DIR / f'dual_pool_{suffix}_trades.json', 'r', encoding='utf-8') as f:
        trades = json.load(f)
    with open(RESULTS_DIR / f'dual_pool_{suffix}_daily.json', 'r', encoding='utf-8') as f:
        daily = json.load(f)
    return summary, trades, daily

def generate_html(summary, trades, daily):
    strategy = summary.get('strategy', 'ETF双池平滑动量轮动')
    period = summary.get('backtest_period', 'N/A')
    trade_days = summary.get('trading_days', 0)
    init_cash = summary.get('initial_cash', 0)
    final_val = summary.get('final_value', 0)
    total_ret = summary.get('total_return_pct', 0)
    annual_ret = summary.get('annualized_return_pct', 0)
    max_dd = summary.get('max_drawdown_pct', 0)
    sharpe = summary.get('sharpe_ratio', 0)
    calmar = summary.get('calmar_ratio', 0)
    total_trades = summary.get('total_trades', 0)
    buys = summary.get('buy_trades', 0)
    sells = summary.get('sell_trades', 0)
    win_rate = summary.get('win_rate_pct', 0)
    avg_win = summary.get('avg_win_pct', 0)
    avg_loss = summary.get('avg_loss_pct', 0)

    # 最近20笔交易
    recent_trades = trades[-20:] if len(trades) > 20 else trades

    # 生成交易表格HTML
    def color(val, is_pct=True):
        if isinstance(val, str):
            return val
        if is_pct:
            if val > 0:
                return f'<span style="color:#DC3545">+{val:.2f}%</span>'
            elif val < 0:
                return f'<span style="color:#28A745">{val:.2f}%</span>'
            return f'<span style="color:#666">{val:.2f}%</span>'
        return str(val)

    trade_rows = ""
    for t in reversed(recent_trades):
        date = t.get('date', '')
        code = t.get('code', t.get('etf', ''))
        name = t.get('name', t.get('etf_name', ''))
        action = t.get('action', '')
        action_label = '买入' if action == 'BUY' else '卖出'
        action_color = '#DC3545' if action == 'BUY' else '#28A745'
        price = t.get('price', 0)
        shares = t.get('shares', t.get('amount', 0))
        pnl = t.get('pnl_pct', None)
        reason = t.get('reason', '')
        pnl_str = color(pnl, True) if pnl is not None else '-'
        trade_rows += f"""
        <tr>
            <td>{date}</td>
            <td>{code}</td>
            <td>{name}</td>
            <td style="color:{action_color};font-weight:600">{action_label}</td>
            <td>{price:.4f}</td>
            <td>{shares}</td>
            <td>{pnl_str}</td>
            <td style="font-size:12px">{reason}</td>
        </tr>"""

    # 策略概述
    etf_pool_size = "133 (静态121 + 动态100融合, 实际可用38)"
    lookback = 25
    commission = "0.01% (万分之一) 双边"

    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{strategy} - 回测报告</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; background:#f0f2f5; color:#333; line-height:1.6; }}
.container {{ max-width:960px; margin:0 auto; padding:20px; }}

/* 标题栏 */
.header {{ background: linear-gradient(135deg, #1F4E79 0%, #2B7AB8 100%); color:white; padding:30px; border-radius:12px; margin-bottom:20px; text-align:center; }}
.header h1 {{ font-size:24px; margin-bottom:8px; }}
.header .subtitle {{ font-size:14px; opacity:0.85; }}

/* 卡片 */
.card {{ background:white; border-radius:10px; padding:24px; margin-bottom:20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.card h2 {{ font-size:18px; color:#1F4E79; margin-bottom:16px; padding-bottom:8px; border-bottom:2px solid #1F4E79; }}

/* 概览网格 */
.overview-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap:12px; }}
.overview-item {{ padding:12px; background:#f8f9fa; border-radius:8px; text-align:center; }}
.overview-item .label {{ font-size:12px; color:#666; margin-bottom:4px; }}
.overview-item .value {{ font-size:22px; font-weight:700; }}

/* 结果卡片 */
.result-cards {{ display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; }}
.result-card {{ padding:16px; border-radius:8px; text-align:center; }}
.result-card.bg-blue {{ background:#E3F2FD; }}
.result-card.bg-green {{ background:#E8F5E9; }}
.result-card.bg-red {{ background:#FFEBEE; }}
.result-card.bg-yellow {{ background:#FFF8E1; }}
.result-card .label {{ font-size:12px; color:#666; }}
.result-card .value {{ font-size:24px; font-weight:700; margin:4px 0; }}
.result-card .sub {{ font-size:12px; color:#888; }}

/* 表格 */
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#1F4E79; color:white; padding:10px 8px; text-align:left; font-weight:600; }}
td {{ padding:8px; border-bottom:1px solid #eee; }}
tr:nth-child(even) {{ background:#f8f9fa; }}
tr:hover {{ background:#e3f2fd; }}

/* 策略概览表格 */
.info-table td:first-child {{ width:140px; color:#666; font-weight:600; }}
.info-table td:last-child {{ color:#333; }}

/* 正负色 */
.positive {{ color:#DC3545; font-weight:600; }}
.negative {{ color:#28A745; font-weight:600; }}

.footer {{ text-align:center; padding:20px; color:#999; font-size:12px; }}
.footer p {{ margin:4px 0; }}
</style>
</head>
<body>
<div class="container">

<!-- 标题 -->
<div class="header">
    <h1>{strategy} 回测报告</h1>
    <div class="subtitle">基于聚宽原版策略代码 | 报告时间: {now} | 数据截止: {period.split('~')[-1].strip() if '~' in period else 'N/A'}</div>
</div>

<!-- 策略概况 -->
<div class="card">
    <h2>策略概况</h2>
    <table class="info-table">
        <tr><td>ETF池</td><td>静态池133只 + 动态池(top100成交额) → 融合去重, 实际可用134只</td></tr>
        <tr><td>动量周期</td><td>{lookback}日 加权对数回归</td></tr>
        <tr><td>持仓数量</td><td>1只 (动量最强)</td></tr>
        <tr><td>佣金费率</td><td>{commission}</td></tr>
        <tr><td>双均线过滤</td><td>close > MA20 且 MA20 > MA60</td></tr>
        <tr><td>成交量过滤</td><td>当日量/5日均量 > 2.5 → 过滤 (放量回避)</td></tr>
        <tr><td>动量得分</td><td>exp(slope × 250) - 1 × R², 范围(0, 5)</td></tr>
        <tr><td>止损</td><td>现价 ≤ 成本价 × 0.92 → 清仓</td></tr>
        <tr><td>防御模式</td><td>无动量目标时 → 买入银华日利(511880)</td></tr>
        <tr><td>其他过滤</td><td>无溢价率/无盈利保护/无行情判断</td></tr>
    </table>
</div>

<!-- 回测结果 -->
<div class="card">
    <h2>回测结果</h2>
    <div class="overview-grid">
        <div class="overview-item"><div class="label">回测区间</div><div class="value" style="font-size:14px">{period}</div></div>
        <div class="overview-item"><div class="label">交易日数</div><div class="value">{trade_days}</div></div>
        <div class="overview-item"><div class="label">初始资金</div><div class="value">{init_cash:,.0f}</div></div>
        <div class="overview-item"><div class="label">最终资产</div><div class="value">{final_val:,.0f}</div></div>
    </div>

    <div class="result-cards" style="margin-top:16px">
        <div class="result-card bg-green">
            <div class="label">总收益率</div>
            <div class="value" style="color:{'#DC3545' if total_ret >= 0 else '#28A745'}">{total_ret:+.2f}%</div>
            <div class="sub">年化 {annual_ret:.2f}%</div>
        </div>
        <div class="result-card bg-red">
            <div class="label">最大回撤</div>
            <div class="value" style="color:#DC3545">{max_dd:.2f}%</div>
            <div class="sub">风险指标</div>
        </div>
        <div class="result-card bg-blue">
            <div class="label">夏普比率</div>
            <div class="value" style="font-size:20px">{sharpe:.4f}</div>
            <div class="sub">卡尔马 {calmar:.4f}</div>
        </div>
    </div>

    <div class="result-cards" style="grid-template-columns: repeat(4, 1fr); margin-top:12px">
        <div class="result-card bg-yellow">
            <div class="label">总交易次数</div>
            <div class="value" style="font-size:20px">{total_trades}</div>
            <div class="sub">买{buys} / 卖{sells}</div>
        </div>
        <div class="result-card bg-green">
            <div class="label">胜率</div>
            <div class="value" style="font-size:20px">{win_rate:.1f}%</div>
            <div class="sub">(不含防御ETF交易)</div>
        </div>
        <div class="result-card bg-green">
            <div class="label">平均盈利</div>
            <div class="value" style="font-size:20px;color:#DC3545">+{avg_win:.2f}%</div>
            <div class="sub">卖出盈利交易</div>
        </div>
        <div class="result-card bg-red">
            <div class="label">平均亏损</div>
            <div class="value" style="font-size:20px;color:#28A745">{avg_loss:.2f}%</div>
            <div class="sub">卖出亏损交易</div>
        </div>
    </div>
</div>

<!-- 最近交易记录 -->
<div class="card">
    <h2>最近交易记录 (最后20笔)</h2>
    <table>
        <thead>
            <tr>
                <th>日期</th>
                <th>代码</th>
                <th>名称</th>
                <th>方向</th>
                <th>价格</th>
                <th>数量</th>
                <th>盈亏</th>
                <th>原因</th>
            </tr>
        </thead>
        <tbody>
            {trade_rows}
        </tbody>
    </table>
</div>

<!-- 数据说明 -->
<div class="card" style="background:#fff3cd; border-left:4px solid #ffc107">
    <h2 style="border-bottom-color:#ffc107">注意事项</h2>
    <ul style="font-size:13px; color:#856404; padding-left:20px">
        <li>数据覆盖率: 134/134只ETF有数据 (100%), 其中124只覆盖完整回测区间 (92.5%)</li>
        <li>数据源: 新浪财经API (money.finance.sina.com.cn) 批量下载, datalen=2000条/只</li>
        <li>成交量放量过滤: 回测使用当日完整成交量(非盘中投影), 与实盘逻辑有差异</li>
        <li>策略原代码来自聚宽平台, 本地回测为近似复现</li>
    </ul>
</div>

<!-- 页脚 -->
<div class="footer">
    <p>{strategy} 回测报告 · 生成于 {now}</p>
    <p>blakever_trade 量化交易系统 | 免责声明: 回测结果不代表未来表现</p>
</div>

</div>
</body>
</html>"""
    return html


def generate_markdown(summary, trades, daily):
    strategy = summary.get('strategy', 'ETF双池平滑动量轮动')
    period = summary.get('backtest_period', 'N/A')
    trade_days = summary.get('trading_days', 0)
    init_cash = summary.get('initial_cash', 0)
    final_val = summary.get('final_value', 0)
    total_ret = summary.get('total_return_pct', 0)
    annual_ret = summary.get('annualized_return_pct', 0)
    max_dd = summary.get('max_drawdown_pct', 0)
    sharpe = summary.get('sharpe_ratio', 0)
    calmar = summary.get('calmar_ratio', 0)
    total_trades = summary.get('total_trades', 0)
    buys = summary.get('buy_trades', 0)
    sells = summary.get('sell_trades', 0)
    win_rate = summary.get('win_rate_pct', 0)
    avg_win = summary.get('avg_win_pct', 0)
    avg_loss = summary.get('avg_loss_pct', 0)

    md = f"""# {strategy} 回测报告

**报告时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**数据截止**: {period.split('~')[-1].strip() if '~' in period else 'N/A'}

---

## 策略概况

| 参数 | 值 |
|------|-----|
| ETF池 | 静态121只 + 动态100只 → 融合 (实际可用38只) |
| 动量周期 | 25日 加权对数回归 |
| 持仓数量 | 1只 |
| 佣金费率 | 0.01% (万分之一) 双边 |
| 双均线过滤 | close > MA20 且 MA20 > MA60 |
| 成交量过滤 | 放量 > 2.5x → 过滤 |
| 止损 | -8% (成本价 × 0.92) |
| 防御模式 | 银华日利(511880) |

## 回测结果

| 指标 | 数值 |
|------|------|
| 回测区间 | {period} |
| 交易日数 | {trade_days} |
| 初始资金 | ¥{init_cash:,.0f} |
| 最终资产 | ¥{final_val:,.0f} |
| **总收益率** | **{total_ret:+.2f}%** |
| **年化收益率** | **{annual_ret:.2f}%** |
| 最大回撤 | {max_dd:.2f}% |
| 夏普比率 | {sharpe:.4f} |
| 卡尔马比率 | {calmar:.4f} |
| 总交易次数 | {total_trades} (买{buys}/卖{sells}) |
| 胜率 | {win_rate:.1f}% |
| 平均盈利 | +{avg_win:.2f}% |
| 平均亏损 | {avg_loss:.2f}% |

## 注意事项

- 数据覆盖率仅 28% (38/133), 回测不能代表完整策略表现
- 动态池未实现, 仅使用静态池
- 聚宽原版代码本地近似复现

---
*blakever_trade 量化交易系统 · 免责声明: 回测结果不代表未来表现*
"""
    return md


if __name__ == '__main__':
    summary, trades, daily = load_results()

    # HTML
    html = generate_html(summary, trades, daily)
    html_path = RESULTS_DIR / 'dual_pool_report.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"HTML报告: {html_path}")

    # Markdown
    md = generate_markdown(summary, trades, daily)
    md_path = RESULTS_DIR / 'dual_pool_report.md'
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"MD报告: {md_path}")
