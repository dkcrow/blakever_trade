#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发送排行榜第一名策略源码到邮箱"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

SMTP_SERVER = 'smtp.qq.com'
SMTP_PORT = 465
SENDER = '848786642@qq.com'
PASSWORD = 'ljbtvacrctjobfed'
RECEIVER = '848786642@qq.com'

# 读取策略源码
with open('/data/workspace/strategy_arena/gem_enhanced_backtest.py', 'r', encoding='utf-8') as f:
    gem_source = f.read()

with open('/data/workspace/strategy_arena/gem_unified_rerank.py', 'r', encoding='utf-8') as f:
    rerank_source = f.read()

now = datetime.now().strftime('%Y-%m-%d %H:%M')

# HTML转义
def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

html = f"""<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px;">
<div style="max-width: 750px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.1);">

  <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 24px 30px; color: white;">
    <h1 style="margin:0; font-size: 22px;">🏆 排行榜第一名策略 - 完整源码</h1>
    <p style="margin: 8px 0 0; opacity: 0.9; font-size: 14px;">GEM日度9M+3d缓冲策略（修正穿越后） | {now}</p>
  </div>

  <div style="padding: 20px 30px;">

    <!-- 策略概况 -->
    <div style="background: #f8f9ff; border-radius: 10px; padding: 18px; margin-bottom: 20px; border-left: 4px solid #667eea;">
      <h2 style="margin: 0 0 12px; color: #333; font-size: 17px;">📊 策略概况</h2>
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr><td style="padding: 4px 0; color: #666; width: 120px;">策略名称</td><td style="padding: 4px 0; font-weight: 600;">GEM日度9M+3d缓冲(修正后)</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">综合得分</td><td style="padding: 4px 0; font-weight: 700; color: #667eea; font-size: 18px;">47.88 分</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">年化收益率</td><td style="padding: 4px 0; font-weight: 600; color: #27ae60;">9.7%</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">最大回撤</td><td style="padding: 4px 0; font-weight: 600; color: #e74c3c;">-24.52%</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">夏普比率</td><td style="padding: 4px 0; font-weight: 600;">0.73</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">盈亏比</td><td style="padding: 4px 0; font-weight: 600;">1.28</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">胜率</td><td style="padding: 4px 0; font-weight: 600;">54.9%</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">年均交易次数</td><td style="padding: 4px 0; font-weight: 600;">6.7 次</td></tr>
        <tr><td style="padding: 4px 0; color: #666;">持仓分布</td><td style="padding: 4px 0;">SPY 67% / SHY 15.1% / VEA 14.8% / AGG 3.2%</td></tr>
      </table>
    </div>

    <!-- 核心机制 -->
    <div style="background: #fff8e1; border-radius: 10px; padding: 18px; margin-bottom: 20px; border-left: 4px solid #f39c12;">
      <h2 style="margin: 0 0 10px; color: #333; font-size: 17px;">⚙️ 核心机制</h2>
      <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #555; line-height: 1.8;">
        <li><strong>双动量轮动</strong>：绝对动量(&gt;0)确认方向 + 相对动量选最强资产</li>
        <li><strong>9M回看期</strong>：9个月×21天=189天，平衡灵敏度和稳定性</li>
        <li><strong>3天缓冲</strong>：距上次换仓＜3天则不换，减少Whipsaw（年换仓8.7→6.7次）</li>
        <li><strong>shift(1)修正</strong>：T日信号T+1日执行，消除未来函数偏差</li>
        <li><strong>交易成本</strong>：开平仓各扣0.2%（费用0.1%+滑点0.1%）</li>
      </ul>
    </div>

    <!-- 文件1: gem_enhanced_backtest.py -->
    <div style="background: #1e1e2e; border-radius: 10px; padding: 18px; margin-bottom: 20px;">
      <h2 style="margin: 0 0 8px; color: #cdd6f4; font-size: 17px;">📄 文件1: gem_enhanced_backtest.py</h2>
      <p style="margin: 0 0 10px; color: #a6adc8; font-size: 12px;">核心引擎：数据加载 + GEM轮动策略 + 回测引擎（含shift(1)修正）</p>
      <pre style="margin: 0; padding: 12px; background: #11111b; border-radius: 8px; overflow-x: auto; font-size: 11px; line-height: 1.4; color: #cdd6f4; max-height: 600px; overflow-y: auto;"><code>{esc(gem_source)}</code></pre>
    </div>

    <!-- 文件2: gem_unified_rerank.py -->
    <div style="background: #1e1e2e; border-radius: 10px; padding: 18px; margin-bottom: 20px;">
      <h2 style="margin: 0 0 8px; color: #cdd6f4; font-size: 17px;">📄 文件2: gem_unified_rerank.py</h2>
      <p style="margin: 0 0 10px; color: #a6adc8; font-size: 12px;">统一回测调度：3天缓冲逻辑 + 评分 + 排行榜生成</p>
      <pre style="margin: 0; padding: 12px; background: #11111b; border-radius: 8px; overflow-x: auto; font-size: 11px; line-height: 1.4; color: #cdd6f4; max-height: 600px; overflow-y: auto;"><code>{esc(rerank_source)}</code></pre>
    </div>

    <!-- 关键函数速查 -->
    <div style="background: #e8f5e9; border-radius: 10px; padding: 18px; margin-bottom: 20px; border-left: 4px solid #27ae60;">
      <h2 style="margin: 0 0 10px; color: #333; font-size: 17px;">🔍 关键函数速查</h2>
      <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr style="background: #c8e6c9;"><th style="padding: 6px; text-align: left;">函数</th><th style="padding: 6px; text-align: left;">所在文件</th><th style="padding: 6px; text-align: left;">作用</th></tr>
        <tr><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;"><code>gem_rotation_baseline()</code></td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">gem_enhanced_backtest.py</td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">日度9M双动量轮动核心信号</td></tr>
        <tr><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;"><code>_apply_holding_buffer()</code></td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">gem_unified_rerank.py</td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">3天换仓缓冲期逻辑</td></tr>
        <tr><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;"><code>run_backtest_enhanced()</code></td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">gem_enhanced_backtest.py</td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">回测引擎（含shift(1)修正）</td></tr>
        <tr><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;"><code>load_etf_data()</code></td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">gem_enhanced_backtest.py</td><td style="padding: 6px; border-bottom: 1px solid #e0e0e0;">加载ETF CSV数据</td></tr>
        <tr><td style="padding: 6px;"><code>backtest_gem_strategy()</code></td><td style="padding: 6px;">gem_unified_rerank.py</td><td style="padding: 6px;">完整回测+评分+生成排行榜条目</td></tr>
      </table>
    </div>

    <div style="text-align: center; padding: 12px 0; color: #999; font-size: 12px; border-top: 1px solid #eee;">
      策略回测系统 · 排行榜第一名 · {now}
    </div>
  </div>
</div>
</body></html>"""

msg = MIMEMultipart('alternative')
msg['Subject'] = f'🏆 排行榜第一名策略源码 - GEM日度9M+3d缓冲(47.88分) - {now}'
msg['From'] = SENDER
msg['To'] = RECEIVER
msg.attach(MIMEText(html, 'html', 'utf-8'))

try:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
        server.login(SENDER, PASSWORD)
        server.sendmail(SENDER, RECEIVER, msg.as_string())
    print('✅ 邮件发送成功！')
except Exception as e:
    print(f'❌ 发送失败: {e}')
