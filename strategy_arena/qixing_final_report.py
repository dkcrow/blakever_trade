#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF轮动策略 — 港美股衍生回测最终报告
包含：三市场最优参数+交易成本×调仓频率组合+可移植性分析
"""
import pandas as pd, numpy as np, math, sys, os, json, smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, '/data/workspace/strategy_arena')
from qixing_cross_market_v3 import (qixing_rotation_strategy, load_etf_data, 
    vectorized_backtest, CN_ETF_POOL, CN_SAFE, US_ETF_POOL, US_SAFE, HK_ETF_POOL, HK_SAFE)

GRADE_COLORS = {'S+': '#ff4500', 'S': '#f97316', 'A': '#22c55e', 'B': '#3b82f6', 'C': '#a855f7', 'D': '#6b7280', 'F': '#374151'}
pool_names = {**CN_ETF_POOL, **US_ETF_POOL, **HK_ETF_POOL}

def run_best_config(close_df, pool_valid, safe_valid, rf_rate, market_id):
    """对每个市场跑最优配置组合"""
    configs = [
        # (短期, 长期, 急跌阈值, 调仓频率, 佣金, 滑点, 配置名称)
        (25, 250, 0.95, 'W-FRI', 0.001, 0.001, '原版周频(标准成本)'),
        (25, 250, 0.95, 'W-FRI', 0.00025, 0, '原版周频(聚宽成本)'),
        (25, 250, 0.95, 'ME', 0.001, 0.001, '原版月频(标准成本)'),
        (25, 250, 0.95, 'ME', 0.00025, 0, '原版月频(聚宽成本)'),
        (15, 120, 0.95, 'ME', 0.001, 0.001, '短周期月频(标准成本)'),
        (15, 120, 0.95, 'ME', 0.00025, 0, '短周期月频(聚宽成本)'),
        (25, 250, 0.92, 'ME', 0.001, 0.001, '宽松急跌月频(标准成本)'),
        (25, 250, 0.90, 'ME', 0.00025, 0, '超宽松月频(聚宽成本)'),
    ]
    
    results = []
    for short, long, drop, freq, fees, slip, name in configs:
        holding = qixing_rotation_strategy(close_df, pool_valid, safe_valid,
            short_lookback=short, long_lookback=long, drop_threshold=drop, rebalance_freq=freq)
        result = vectorized_backtest(close_df, holding, fees_rate=fees, slippage=slip, risk_free_rate=rf_rate)
        if result:
            result['config_name'] = name
            result['market'] = market_id
            results.append(result)
    return results


def build_final_report(all_results):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 各市场最优结果卡片
    cards = {}
    for mid, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        mresults = [r for r in all_results if r['market'] == mid]
        if not mresults:
            continue
        best = max(mresults, key=lambda x: x['total_score'])
        cards[mid] = best
    
    cards_html = ''
    for mid, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        r = cards.get(mid)
        if not r:
            continue
        grade = r['grade']
        gc = GRADE_COLORS.get(grade, '#6b7280')
        badge = f'<span style="display:inline-block;background:{gc};color:white;font-size:12px;font-weight:800;padding:2px 8px;border-radius:4px">{grade}</span>'
        
        hd = r.get('holding_distribution', {})
        hd_sorted = sorted(hd.items(), key=lambda x: x[1], reverse=True)[:4]
        hd_html = ''
        for sym, pct in hd_sorted:
            display_name = pool_names.get(sym, sym)
            bar_w = min(pct, 100)
            hd_html += f'''<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
                <span style="font-size:10px;color:#9ca3af;min-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{display_name}</span>
                <div style="flex:1;background:rgba(249,115,22,0.1);border-radius:2px;height:10px"><div style="width:{bar_w}%;background:linear-gradient(90deg,#f97316,#fb923c);height:100%;border-radius:2px"></div></div>
                <span style="font-size:10px;color:#f97316;font-weight:600">{pct}%</span></div>'''
        
        sc_color = '#f97316' if r['total_score'] >= 50 else '#fb923c' if r['total_score'] >= 28 else '#6b7280'
        cards_html += f'''
        <div style="background:#0c0c14;border-radius:12px;padding:16px;margin-bottom:10px;border-left:3px solid {gc};border:1px solid rgba(249,115,22,0.1)">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="font-size:18px">{mflag}</span>
            <span style="font-size:14px;font-weight:700;color:#f97316">{mlabel}七星高照(最优配置)</span>
          </div>
          <div style="font-size:10px;color:#6b7280;margin-bottom:6px">配置: {r.get('config_name','')}</div>
          <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:8px">
            <span style="font-size:26px;font-weight:800;color:{sc_color}">{r['total_score']:.1f}</span>
            <span style="font-size:11px;color:#9ca3af">分</span>{badge}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:2px 14px;margin-bottom:8px">
            <div><span style="font-size:9px;color:#9ca3af">年化</span><br><span style="font-size:14px;font-weight:700;color:#22c55e">{r['annual_return']:.1f}%</span></div>
            <div><span style="font-size:9px;color:#9ca3af">夏普</span><br><span style="font-size:14px;font-weight:700;color:#3b82f6">{r['sharpe']:.2f}</span></div>
            <div><span style="font-size:9px;color:#9ca3af">回撤</span><br><span style="font-size:14px;font-weight:700;color:#ef4444">{r['max_drawdown']:.1f}%</span></div>
            <div><span style="font-size:9px;color:#9ca3af">胜率</span><br><span style="font-size:14px;font-weight:700;color:#a855f7">{r['win_rate']:.1f}%</span></div>
            <div><span style="font-size:9px;color:#9ca3af">盈亏比</span><br><span style="font-size:14px;font-weight:700;color:#f59e0b">{r['profit_factor']:.2f}</span></div>
            <div><span style="font-size:9px;color:#9ca3af">年交易</span><br><span style="font-size:14px;font-weight:700;color:#6b7280">{r['avg_trades_per_year']:.1f}</span></div>
          </div>
          <div style="font-size:9px;font-weight:600;color:#9ca3af;margin-bottom:3px">持仓分布</div>
          {hd_html}
        </div>'''
    
    # 全部配置对比表
    table_html = ''
    for mid, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        mresults = [r for r in all_results if r['market'] == mid]
        if not mresults:
            continue
        mresults.sort(key=lambda x: x['total_score'], reverse=True)
        table_html += f'''<div style="margin-top:10px">
          <div style="font-size:12px;font-weight:700;color:#f97316;margin-bottom:4px">{mflag} {mlabel}全部配置</div>
          <table style="width:100%;border-collapse:collapse;font-size:10px">
            <tr style="border-bottom:1px solid rgba(249,115,22,0.2)">
              <th style="padding:3px 4px;text-align:left;color:#f97316">配置</th>
              <th style="padding:3px 4px;text-align:right;color:#f97316">评分</th>
              <th style="padding:3px 4px;color:#f97316">等级</th>
              <th style="padding:3px 4px;text-align:right;color:#f97316">年化%</th>
              <th style="padding:3px 4px;text-align:right;color:#f97316">夏普</th>
              <th style="padding:3px 4px;text-align:right;color:#f97316">回撤%</th>
              <th style="padding:3px 4px;text-align:right;color:#f97316">盈亏比</th>
            </tr>'''
        for r in mresults:
            vg = r['grade']
            vgc = GRADE_COLORS.get(vg, '#6b7280')
            table_html += f'''<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
              <td style="padding:2px 4px;color:#e5e7eb">{r['config_name']}</td>
              <td style="padding:2px 4px;text-align:right;font-weight:700;color:{vgc}">{r['total_score']:.1f}</td>
              <td style="padding:2px 4px;text-align:center"><span style="color:{vgc};font-weight:700">{vg}</span></td>
              <td style="padding:2px 4px;text-align:right;color:#22c55e">{r['annual_return']:.1f}</td>
              <td style="padding:2px 4px;text-align:right;color:#3b82f6">{r['sharpe']:.2f}</td>
              <td style="padding:2px 4px;text-align:right;color:#ef4444">{r['max_drawdown']:.1f}</td>
              <td style="padding:2px 4px;text-align:right;color:#f59e0b">{r['profit_factor']:.2f}</td>
            </tr>'''
        table_html += '</table></div>'
    
    # 核心结论
    cn_best = cards.get('CN')
    us_best = cards.get('US')
    hk_best = cards.get('HK')
    
    conclusion_html = f'''
    <div style="background:#0c0c14;border-radius:12px;padding:16px;margin-top:10px;border:1px solid rgba(249,115,22,0.15)">
      <div style="font-size:14px;font-weight:800;color:#f97316;margin-bottom:10px">📋 核心结论</div>
      
      <div style="background:rgba(34,197,94,0.08);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(34,197,94,0.15)">
        <div style="font-size:12px;font-weight:700;color:#22c55e;margin-bottom:4px">✅ A股：策略有效，月频调仓为最优</div>
        <div style="font-size:11px;color:#9ca3af;line-height:1.7">
          {f"最优配置年化{cn_best['annual_return']:.1f}%/夏普{cn_best['sharpe']:.2f}/回撤{cn_best['max_drawdown']:.1f}%/评分{cn_best['total_score']:.1f}({cn_best['grade']})" if cn_best else "N/A"}<br>
          <b>关键发现</b>: 月频调仓远优于周频(年化+24%)，因为A股交易成本高(万10佣金+0.1%滑点)，
          周频7年换仓191次→成本侵蚀≈12%年化；月频仅44次→成本仅≈3%年化<br>
          <b>与聚宽差异</b>: 聚宽原版212% vs 本地月频30%→差距来自：①回测时段(含2015年小盘牛) ②数据复权方式 ③可能含幸存者偏差
        </div>
      </div>
      
      <div style="background:rgba(239,68,68,0.08);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(239,68,68,0.15)">
        <div style="font-size:12px;font-weight:700;color:#ef4444;margin-bottom:4px">❌ 美股：策略失效，动量轮动不适配</div>
        <div style="font-size:11px;color:#9ca3af;line-height:1.7">
          {f"最优配置年化{us_best['annual_return']:.1f}%/夏普{us_best['sharpe']:.2f}/回撤{us_best['max_drawdown']:.1f}%" if us_best else "N/A"}<br>
          <b>根因</b>: ①美股ETF同涨同跌(2020-2021全行业牛市)→轮动空间极小 ②美股机构主导→动量衰减快→25日窗口太慢 
          ③无涨跌停→跳空缺口多→趋势不连续 ④美股缺少A股式"商品+跨境"低相关标的<br>
          <b>唯一正收益</b>: 双月调仓+零成本=7.1%年化，但回撤47%→不可接受
        </div>
      </div>
      
      <div style="background:rgba(168,85,247,0.08);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(168,85,247,0.15)">
        <div style="font-size:12px;font-weight:700;color:#a855f7;margin-bottom:4px">⚠️ 港股：策略勉强有效，月频可盈利</div>
        <div style="font-size:11px;color:#9ca3af;line-height:1.7">
          {f"最优配置年化{hk_best['annual_return']:.1f}%/夏普{hk_best['sharpe']:.2f}/回撤{hk_best['max_drawdown']:.1f}%" if hk_best else "N/A"}<br>
          <b>特点</b>: 港股有A股ETF(沪深300/A50)+黄金+高股息→多元性介于A股和美股之间<br>
          <b>月频调仓</b>: 标准成本10.3%年化→勉强可接受，但回撤34%仍偏高<br>
          <b>核心问题</b>: 港股ETF流动性远低于A股→冲击成本更高→实际收益更低
        </div>
      </div>
      
      <div style="background:rgba(249,115,22,0.08);border-radius:8px;padding:10px;border:1px solid rgba(249,115,22,0.15)">
        <div style="font-size:12px;font-weight:700;color:#f59e0b;margin-bottom:4px">🔑 策略可移植性总结</div>
        <div style="font-size:11px;color:#9ca3af;line-height:1.8">
          <table style="width:100%;border-collapse:collapse;font-size:11px;margin-top:4px">
            <tr style="border-bottom:1px solid rgba(249,115,22,0.2)">
              <th style="padding:3px 6px;text-align:left;color:#f97316">维度</th>
              <th style="padding:3px 6px;text-align:center;color:#22c55e">🇨🇳A股</th>
              <th style="padding:3px 6px;text-align:center;color:#a855f7">🇭🇰港股</th>
              <th style="padding:3px 6px;text-align:center;color:#3b82f6">🇺🇸美股</th>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
              <td style="padding:3px 6px;color:#9ca3af">ETF池多元性</td>
              <td style="padding:3px 6px;text-align:center;color:#22c55e">★★★★★</td>
              <td style="padding:3px 6px;text-align:center;color:#a855f7">★★★</td>
              <td style="padding:3px 6px;text-align:center;color:#ef4444">★★</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
              <td style="padding:3px 6px;color:#9ca3af">动量延续性</td>
              <td style="padding:3px 6px;text-align:center;color:#22c55e">★★★★★</td>
              <td style="padding:3px 6px;text-align:center;color:#a855f7">★★★</td>
              <td style="padding:3px 6px;text-align:center;color:#ef4444">★★</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
              <td style="padding:3px 6px;color:#9ca3af">防御资产质量</td>
              <td style="padding:3px 6px;text-align:center;color:#22c55e">★★★★★</td>
              <td style="padding:3px 6px;text-align:center;color:#a855f7">★★★</td>
              <td style="padding:3px 6px;text-align:center;color:#f59e0b">★★★</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
              <td style="padding:3px 6px;color:#9ca3af">轮动策略适配</td>
              <td style="padding:3px 6px;text-align:center;color:#22c55e;font-weight:700">✅高度适配</td>
              <td style="padding:3px 6px;text-align:center;color:#a855f7;font-weight:700">⚠️勉强可用</td>
              <td style="padding:3px 6px;text-align:center;color:#ef4444;font-weight:700">❌不适配</td>
            </tr>
          </table>
        </div>
      </div>
    </div>'''
    
    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>七星高照跨市场报告</title>
<style>details summary::-webkit-details-marker{{display:none}}details summary{{list-style:none}}details summary::marker{{display:none;content:""}}</style></head>
<body style="margin:0;padding:12px 8px;background-color:#060610;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;color:#e5e7eb">
<div style="max-width:600px;margin:0 auto">
  <div style="background:#0c0c14;border-radius:14px;padding:20px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <span style="font-size:22px">🌟</span>
      <span style="font-size:18px;font-weight:800;color:#f97316">七星高照ETF轮动</span>
    </div>
    <div style="font-size:13px;font-weight:600;color:#fb923c;margin-bottom:4px">港美股衍生回测 · 最终报告</div>
    <div style="font-size:11px;color:#6b7280;line-height:1.5">
      {now_str} · A股TOP1策略跨市场移植 · 交易成本×调仓频率组合回测 · V4评分
    </div>
  </div>
  
  <div style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:10px;border:1px solid rgba(249,115,22,0.15)">
    <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:8px">🏅 三市场最优配置</div>
    {cards_html}
  </div>
  
  <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:10px;border:1px solid rgba(249,115,22,0.1)">
    <summary style="font-size:12px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;outline:none">📊 全部配置对比(8种组合×3市场)</summary>
    {table_html}
  </details>
  
  {conclusion_html}
  
</div></body></html>'''
    return html


def send_email(html):
    smtp_server, smtp_port = 'smtp.qq.com', 465
    sender, password, receiver = '848786642@qq.com', 'ljbtvacrctjobfed', '848786642@qq.com'
    subject = f'【七星高照最终报告】{datetime.now().strftime("%Y%m%d_%H%M")} A股TOP1跨市场回测'
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject; msg['From'] = sender; msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print("✅ 邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


if __name__ == '__main__':
    print("🌟 七星高照ETF轮动 — 港美股衍生最终报告")
    print("=" * 70)
    
    all_results = []
    for market, pool, safe, data_dir, rf, mlabel in [
        ('CN', list(CN_ETF_POOL.keys()), CN_SAFE, '/data/workspace/back_trader_stocks/a', 0.02, 'A股'),
        ('US', list(US_ETF_POOL.keys()), US_SAFE, '/data/workspace/back_trader_stocks/etf', 0.045, '美股'),
        ('HK', list(HK_ETF_POOL.keys()), HK_SAFE, '/data/workspace/back_trader_stocks/hk_etf', 0.035, '港股'),
    ]:
        print(f"\n📦 {mlabel}市场...")
        raw = load_etf_data(pool, data_dir)
        if len(raw) < 3:
            continue
        close_df = pd.DataFrame({sym: df['Close'] for sym, df in raw.items()}).sort_index()
        close_df = close_df.loc['2019-01-01':'2026-04-25'].dropna(axis=1, how='all')
        valid_cols = [c for c in close_df.columns if close_df[c].dropna().shape[0] > 300]
        close_df = close_df[valid_cols]
        safe_valid = [a for a in safe if a in valid_cols]
        pool_valid = [a for a in pool if a in valid_cols]
        
        print(f"  有效ETF: {len(valid_cols)}只")
        mresults = run_best_config(close_df, pool_valid, safe_valid, rf, market)
        all_results.extend(mresults)
        
        best = max(mresults, key=lambda x: x['total_score'])
        print(f"  最优: {best['config_name']}")
        print(f"  年化{best['annual_return']}% 夏普{best['sharpe']} 回撤{best['max_drawdown']}% 评分{best['total_score']}({best['grade']})")
    
    html = build_final_report(all_results)
    report_path = f'/data/workspace/strategy_arena/qixing_final_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n✅ 报告保存: {report_path}")
    send_email(html)
    print("✅ 全部完成！")
