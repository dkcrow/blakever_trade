#!/usr/bin/env python3
"""牛市/全局回测定时报告邮件发送脚本"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

now = datetime.now()
date_str = now.strftime("%Y-%m-%d")
time_str = now.strftime("%H:%M")

# ========== 数据定义 ==========
# 排行榜前五
top_strategies = [
    {
        "rank": 1, "medal": "🥇", "name": "GEM日度9M+3d缓冲(修正后)", "market": "US", "market_tag": "美股",
        "score": 47.88, "type": "其他",
        "annual": 9.7, "sharpe": 0.73, "drawdown": 24.52, "pl_ratio": 1.15, "win_rate": 55.5, "trades": 6.7,
        "stress_annual": 16.61, "stress_drawdown": 10.65, "robust": True, "data_bias": True,
        "desc": "日度9M + 3天换仓缓冲期，减少Whipsaw。",
        "params": "lookback_months=9, rebalance_freq_days=1, buffer_days=3, shift1_fix=True"
    },
    {
        "rank": 2, "medal": "🥈", "name": "RSI回调买入策略(牛市专用)", "market": "HK", "market_tag": "港股",
        "score": 31.62, "type": "均值回归",
        "annual": 0.03, "sharpe": 0.09, "drawdown": 0.04, "pl_ratio": 10.0, "win_rate": 20.0, "trades": 0.1,
        "stress_annual": 0, "stress_drawdown": 0, "robust": False, "data_bias": True,
        "desc": "在确认的牛市趋势中买回调，RSI从超卖区回升时入场，RSI超买或趋势破位出场。",
        "params": "period=50, rsi_period=14"
    },
    {
        "rank": 3, "medal": "🥉", "name": "MACD金叉+趋势确认策略", "market": "HK", "market_tag": "港股",
        "score": 25.8, "type": "趋势跟踪",
        "annual": 1.97, "sharpe": 0.2, "drawdown": 22.31, "pl_ratio": 1.55, "win_rate": 41.1, "trades": 3.8,
        "stress_annual": 0, "stress_drawdown": 0, "robust": False, "data_bias": True,
        "desc": "MACD柱状图从负转正(金叉确认)+价格在长期EMA上方，减少震荡市假信号。",
        "params": "macd_fast=12, macd_slow=26, macd_signal=9"
    },
    {
        "rank": 4, "medal": "4️⃣", "name": "Dual Momentum双动量策略", "market": "US", "market_tag": "美股",
        "score": 19.93, "type": "趋势跟踪",
        "annual": 1.18, "sharpe": 0.01, "drawdown": 21.82, "pl_ratio": 1.35, "win_rate": 37.4, "trades": 6.0,
        "stress_annual": 0, "stress_drawdown": 0, "robust": False, "data_bias": True,
        "desc": "绝对动量+相对动量月度轮动策略，12M绝对动量确认大方向，1M相对动量确认短期趋势。",
        "params": "lookback_abs=12M, lookback_rel=1M"
    },
]

# 美股本轮扫描数据
us_new_strategies = [
    {"name": "Supertrend ATR自适应趋势跟踪", "type": "趋势跟踪", "fp": "4c1073f1", "score": 0, "annual": 7.08, "sharpe": 0.42, "drawdown": 39.92, "pl_ratio": 10.0, "win_rate": 0, "trades": 0.3, "pass": False, "reason": "回撤>25%"},
    {"name": "Donchian通道突破(海龟交易法)", "type": "趋势跟踪", "fp": "53092435", "score": 0, "annual": 1.13, "sharpe": 0.11, "drawdown": 28.55, "pl_ratio": 1.48, "win_rate": 41.4, "trades": 4.0, "pass": False, "reason": "回撤>25%"},
    {"name": "MACD+Supertrend双重过滤", "type": "趋势跟踪", "fp": "b770f27a", "score": 0, "annual": 1.23, "sharpe": 0.18, "drawdown": 33.06, "pl_ratio": 1.16, "win_rate": 39.4, "trades": 9.4, "pass": False, "reason": "回撤>25%"},
    {"name": "EMA交叉+ADX趋势强度过滤", "type": "趋势跟踪", "fp": "1a31ebc7", "score": 0, "annual": 4.8, "sharpe": 0.33, "drawdown": 36.94, "pl_ratio": 1.66, "win_rate": 43.8, "trades": 6.0, "pass": False, "reason": "回撤>25%"},
    {"name": "高股息轮动策略", "type": "趋势跟踪", "fp": "6be4ae8d", "score": 0, "annual": -2.57, "sharpe": -0.2, "drawdown": 32.29, "pl_ratio": 0.91, "win_rate": 44.3, "trades": 10.5, "pass": False, "reason": "回撤>25%"},
    {"name": "Keltner通道突破策略", "type": "趋势跟踪", "fp": "7632ef57", "score": 0, "annual": 2.16, "sharpe": 0.13, "drawdown": 32.36, "pl_ratio": 4.07, "win_rate": 40.0, "trades": 1.8, "pass": False, "reason": "回撤>25%"},
    {"name": "Triple EMA三层均线策略", "type": "趋势跟踪", "fp": "b5f7b315", "score": 0, "annual": 0.11, "sharpe": 0, "drawdown": 32.24, "pl_ratio": 1.38, "win_rate": 34.2, "trades": 3.7, "pass": False, "reason": "回撤>25%"},
    {"name": "VWAP趋势跟踪策略", "type": "趋势跟踪", "fp": "5046ba27", "score": 0, "annual": -2.98, "sharpe": -0.1, "drawdown": 36.88, "pl_ratio": 0.94, "win_rate": 35.3, "trades": 14.2, "pass": False, "reason": "回撤>25%"},
    {"name": "RSI趋势确认策略", "type": "趋势跟踪", "fp": "239cb63e", "score": 0, "annual": -2.07, "sharpe": -0.09, "drawdown": 36.46, "pl_ratio": 0.98, "win_rate": 33.0, "trades": 10.9, "pass": False, "reason": "回撤>25%"},
]

# 港股本轮扫描数据
hk_new_strategies = [
    {"name": "Supertrend ATR自适应趋势跟踪", "type": "趋势跟踪", "fp": "4c1073f1", "score": 0, "annual": 9.13, "sharpe": 0.19, "drawdown": 61.03, "pl_ratio": 10.0, "win_rate": 0, "trades": 0.3, "pass": False, "reason": "回撤>25%"},
    {"name": "Donchian通道突破(海龟交易法)", "type": "趋势跟踪", "fp": "53092435", "score": 0, "annual": 0.62, "sharpe": 0, "drawdown": 43.15, "pl_ratio": 1.04, "win_rate": 34.5, "trades": 3.6, "pass": False, "reason": "回撤>25%"},
    {"name": "Dual Momentum双动量策略", "type": "趋势跟踪", "fp": "57856069", "score": 0, "annual": -4.16, "sharpe": -0.32, "drawdown": 30.93, "pl_ratio": 1.04, "win_rate": 31.1, "trades": 4.7, "pass": False, "reason": "回撤>25%"},
    {"name": "MACD+Supertrend双重过滤", "type": "趋势跟踪", "fp": "b770f27a", "score": 0, "annual": -0.97, "sharpe": 0.07, "drawdown": 50.81, "pl_ratio": 1.01, "win_rate": 35.2, "trades": 9.5, "pass": False, "reason": "回撤>25%"},
    {"name": "EMA交叉+ADX趋势强度过滤", "type": "趋势跟踪", "fp": "1a31ebc7", "score": 0, "annual": 12.58, "sharpe": 0.22, "drawdown": 54.56, "pl_ratio": 1.24, "win_rate": 39.0, "trades": 6.7, "pass": False, "reason": "回撤>25%"},
    {"name": "布林带均值回归策略", "type": "趋势跟踪", "fp": "743c7e87", "score": 0, "annual": 1.37, "sharpe": 0.24, "drawdown": 37.92, "pl_ratio": 2.81, "win_rate": 60.0, "trades": 4.6, "pass": False, "reason": "回撤>25%"},
    {"name": "高股息轮动策略", "type": "趋势跟踪", "fp": "6be4ae8d", "score": 0, "annual": -7.56, "sharpe": -0.43, "drawdown": 43.46, "pl_ratio": 0.77, "win_rate": 37.4, "trades": 9.0, "pass": False, "reason": "回撤>25%"},
    {"name": "Keltner通道突破策略", "type": "趋势跟踪", "fp": "7632ef57", "score": 0, "annual": -1.0, "sharpe": -0.06, "drawdown": 48.6, "pl_ratio": 2.23, "win_rate": 28.8, "trades": 1.6, "pass": False, "reason": "回撤>25%"},
    {"name": "Triple EMA三层均线策略", "type": "趋势跟踪", "fp": "b5f7b315", "score": 0, "annual": 6.99, "sharpe": -0.22, "drawdown": 44.84, "pl_ratio": 0.81, "win_rate": 26.8, "trades": 3.3, "pass": False, "reason": "回撤>25%"},
    {"name": "VWAP趋势跟踪策略", "type": "趋势跟踪", "fp": "5046ba27", "score": 0, "annual": -3.85, "sharpe": -0.14, "drawdown": 52.82, "pl_ratio": 0.84, "win_rate": 31.8, "trades": 14.5, "pass": False, "reason": "回撤>25%"},
    {"name": "RSI趋势确认策略", "type": "趋势跟踪", "fp": "239cb63e", "score": 0, "annual": -1.95, "sharpe": -0.18, "drawdown": 50.29, "pl_ratio": 0.93, "win_rate": 28.7, "trades": 11.1, "pass": False, "reason": "回撤>25%"},
]

# 废弃策略库（最近10个）
retired_strategies = [
    {"name": "Triple EMA三层均线策略", "market": "US", "type": "趋势跟踪", "fp": "b5f7b315", "score": 0, "annual": 0.11, "sharpe": 0, "drawdown": 32.24, "reason": "回撤>25%", "time": "2026-04-21 21:08"},
    {"name": "Dual Momentum双动量策略", "market": "HK", "type": "趋势跟踪", "fp": "57856069", "score": 0, "annual": 2.7, "sharpe": 0.01, "drawdown": 29.35, "reason": "回撤>25%", "time": "2026-04-21 20:33"},
    {"name": "布林带均值回归策略", "market": "HK", "type": "趋势跟踪", "fp": "743c7e87", "score": 0, "annual": -0.6, "sharpe": 0.1, "drawdown": 41.57, "reason": "回撤>25%", "time": "2026-04-21 20:33"},
    {"name": "Triple EMA三层均线策略", "market": "HK", "type": "趋势跟踪", "fp": "b5f7b315", "score": 0, "annual": 3.33, "sharpe": 0.29, "drawdown": 36.21, "reason": "回撤>25%", "time": "2026-04-21 20:33"},
    {"name": "Supertrend ATR自适应趋势跟踪", "market": "HK", "type": "趋势跟踪", "fp": "4c1073f1", "score": 0, "annual": 9.13, "sharpe": 0.19, "drawdown": 61.03, "reason": "回撤>25%", "time": "2026-04-21 08:49"},
    {"name": "Donchian通道突破(海龟交易法)", "market": "HK", "type": "趋势跟踪", "fp": "53092435", "score": 0, "annual": 0.62, "sharpe": 0, "drawdown": 43.15, "reason": "回撤>25%", "time": "2026-04-21 08:49"},
    {"name": "RSI回调买入策略(牛市专用)", "market": "HK", "type": "均值回归", "fp": "7fbf43ac", "score": 26.35, "annual": 0.08, "sharpe": 0, "drawdown": 0.59, "reason": "年化<15%;夏普<0.5", "time": "2026-04-21 08:49"},
    {"name": "MACD+Supertrend双重过滤", "market": "HK", "type": "趋势跟踪", "fp": "b770f27a", "score": 0, "annual": -0.97, "sharpe": 0.07, "drawdown": 50.81, "reason": "回撤>25%", "time": "2026-04-21 08:49"},
    {"name": "EMA交叉+ADX趋势强度过滤", "market": "HK", "type": "趋势跟踪", "fp": "1a31ebc7", "score": 0, "annual": 12.58, "sharpe": 0.22, "drawdown": 54.56, "reason": "回撤>25%", "time": "2026-04-21 08:49"},
    {"name": "高股息轮动策略", "market": "HK", "type": "趋势跟踪", "fp": "6be4ae8d", "score": 0, "annual": -7.56, "sharpe": -0.43, "drawdown": 43.46, "reason": "回撤>25%", "time": "2026-04-21 08:49"},
]

def val_color(v, inverse=False):
    """返回正值绿色、负值红色"""
    try:
        num = float(v)
    except:
        return '#333'
    if inverse:
        return '#e53935' if num > 0 else ('#2e7d32' if num < 0 else '#333')
    return '#2e7d32' if num > 0 else ('#e53935' if num < 0 else '#333')

def market_tag_color(market):
    return '#1565c0' if market == 'US' else '#c62828'

def market_tag_bg(market):
    return '#e3f2fd' if market == 'US' else '#fce4ec'

def market_label(market):
    return '美股' if market == 'US' else '港股'

def build_strategy_card(s):
    score_color = '#2e7d32' if s['score'] > 0 else '#e53935'
    robust_icon = '✅' if s.get('robust') else '❌'
    bias_icon = '⚠️' if s.get('data_bias') else '✅'
    
    # 压力测试行
    stress_annual_color = val_color(s.get('stress_annual', 0))
    stress_dd_color = val_color(s.get('stress_drawdown', 0), inverse=True)
    
    card = f'''
    <div style="background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,0.08);margin-bottom:16px;overflow:hidden;border:1px solid #e0e0e0;">
      <!-- 卡片头部 -->
      <div style="background:linear-gradient(135deg,#1a237e,#283593);padding:14px 16px;display:flex;align-items:center;justify-content:space-between;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:24px;">{s['medal']}</span>
          <div>
            <div style="color:#fff;font-size:15px;font-weight:bold;">{s['name']}</div>
            <div style="display:flex;gap:6px;margin-top:4px;">
              <span style="background:{market_tag_bg(s['market'])};color:{market_tag_color(s['market'])};font-size:11px;padding:2px 8px;border-radius:10px;font-weight:bold;">{s['market_tag']}</span>
              <span style="background:#f3e5f5;color:#7b1fa2;font-size:11px;padding:2px 8px;border-radius:10px;">{s['type']}</span>
            </div>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="color:#ffd54f;font-size:22px;font-weight:bold;">{s['score']}</div>
          <div style="color:rgba(255,255,255,0.7);font-size:11px;">综合得分</div>
        </div>
      </div>
      <!-- 核心指标网格 -->
      <div style="padding:12px 16px;">
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
          <div style="background:#f5f5f5;border-radius:8px;padding:8px 10px;text-align:center;">
            <div style="font-size:11px;color:#757575;">年化收益</div>
            <div style="font-size:15px;font-weight:bold;color:{val_color(s['annual'])};">{s['annual']}%</div>
          </div>
          <div style="background:#f5f5f5;border-radius:8px;padding:8px 10px;text-align:center;">
            <div style="font-size:11px;color:#757575;">夏普比率</div>
            <div style="font-size:15px;font-weight:bold;color:{val_color(s['sharpe'])};">{s['sharpe']}</div>
          </div>
          <div style="background:#f5f5f5;border-radius:8px;padding:8px 10px;text-align:center;">
            <div style="font-size:11px;color:#757575;">最大回撤</div>
            <div style="font-size:15px;font-weight:bold;color:{val_color(s['drawdown'], inverse=True)};">{s['drawdown']}%</div>
          </div>
          <div style="background:#f5f5f5;border-radius:8px;padding:8px 10px;text-align:center;">
            <div style="font-size:11px;color:#757575;">盈亏比</div>
            <div style="font-size:15px;font-weight:bold;color:{val_color(s['pl_ratio'])};">{s['pl_ratio']}</div>
          </div>
          <div style="background:#f5f5f5;border-radius:8px;padding:8px 10px;text-align:center;">
            <div style="font-size:11px;color:#757575;">胜率</div>
            <div style="font-size:15px;font-weight:bold;color:#333;">{s['win_rate']}%</div>
          </div>
          <div style="background:#f5f5f5;border-radius:8px;padding:8px 10px;text-align:center;">
            <div style="font-size:11px;color:#757575;">年交易次数</div>
            <div style="font-size:15px;font-weight:bold;color:#333;">{s['trades']}</div>
          </div>
        </div>
        <!-- 压力测试 & 鲁棒性 -->
        <div style="margin-top:10px;padding:8px 10px;background:#fafafa;border-radius:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;">
          <div style="font-size:12px;color:#666;">
            压力测试: <span style="color:{stress_annual_color};font-weight:bold;">年化{s.get('stress_annual',0)}%</span> / <span style="color:{stress_dd_color};font-weight:bold;">回撤{s.get('stress_drawdown',0)}%</span>
          </div>
          <div style="font-size:12px;">
            鲁棒:{robust_icon} 偏差:{bias_icon}
          </div>
        </div>
        <!-- 描述 & 参数 -->
        <div style="margin-top:8px;font-size:12px;color:#666;line-height:1.5;">💡 {s['desc']}</div>
        <div style="margin-top:6px;font-size:11px;color:#999;background:#f5f5f5;padding:6px 10px;border-radius:6px;word-break:break-all;">⚙️ {s['params']}</div>
      </div>
    </div>'''
    return card

def build_stats_block():
    return f'''
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
      <div style="background:linear-gradient(135deg,#e3f2fd,#bbdefb);border-radius:10px;padding:14px;text-align:center;">
        <div style="font-size:13px;color:#1565c0;">🇺🇸 美股扫描</div>
        <div style="font-size:22px;font-weight:bold;color:#0d47a1;margin-top:4px;">9 新策略</div>
        <div style="font-size:12px;color:#1565c0;margin-top:2px;">耗时 333秒 | 全部零分</div>
      </div>
      <div style="background:linear-gradient(135deg,#fce4ec,#f8bbd0);border-radius:10px;padding:14px;text-align:center;">
        <div style="font-size:13px;color:#c62828;">🇭🇰 港股扫描</div>
        <div style="font-size:22px;font-weight:bold;color:#b71c1c;margin-top:4px;">11 新策略</div>
        <div style="font-size:12px;color:#c62828;margin-top:2px;">耗时 165秒 | 全部零分</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:20px;">
      <div style="background:#fff3e0;border-radius:10px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#e65100;">🏆 有效策略</div>
        <div style="font-size:20px;font-weight:bold;color:#bf360c;">4</div>
      </div>
      <div style="background:#fce4ec;border-radius:10px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#c62828;">❌ 本轮零分</div>
        <div style="font-size:20px;font-weight:bold;color:#b71c1c;">20</div>
      </div>
      <div style="background:#efebe9;border-radius:10px;padding:12px;text-align:center;">
        <div style="font-size:11px;color:#4e342e;">🗑️ 废弃库累计</div>
        <div style="font-size:20px;font-weight:bold;color:#3e2723;">24</div>
      </div>
    </div>'''

def build_strategy_table(strategies, market_label):
    rows = ""
    for i, s in enumerate(strategies, 1):
        pass_icon = "✅" if s['pass'] else "❌"
        rows += f'''<tr style="background:{'#fff' if i%2 else '#fafafa'};">
          <td style="padding:6px 8px;font-size:12px;text-align:center;">{i}</td>
          <td style="padding:6px 8px;font-size:12px;">{s['name']}</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;color:{val_color(s['annual'])};font-weight:bold;">{s['annual']}%</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;color:{val_color(s['sharpe'])};">{s['sharpe']}</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;color:{val_color(s['drawdown'],inverse=True)};font-weight:bold;">{s['drawdown']}%</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;color:{val_color(s['pl_ratio'])};">{s['pl_ratio']}</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;">{s['win_rate']}%</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;">{s['trades']}</td>
          <td style="padding:6px 8px;font-size:12px;text-align:center;">{pass_icon}</td>
          <td style="padding:6px 8px;font-size:11px;color:#e53935;">{s['reason']}</td>
        </tr>'''
    
    return f'''
    <div style="margin-bottom:20px;">
      <div style="background:linear-gradient(135deg,#1a237e,#283593);padding:10px 16px;border-radius:10px 10px 0 0;">
        <span style="color:#fff;font-size:14px;font-weight:bold;">📊 {market_label}本轮回测数据（{len(strategies)}个策略）</span>
      </div>
      <div style="overflow-x:auto;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 10px 10px;">
        <table style="width:100%;border-collapse:collapse;min-width:560px;">
          <thead>
            <tr style="background:#e8eaf6;">
              <th style="padding:8px;font-size:12px;">#</th>
              <th style="padding:8px;font-size:12px;text-align:left;">策略名称</th>
              <th style="padding:8px;font-size:12px;">年化</th>
              <th style="padding:8px;font-size:12px;">夏普</th>
              <th style="padding:8px;font-size:12px;">回撤</th>
              <th style="padding:8px;font-size:12px;">盈亏比</th>
              <th style="padding:8px;font-size:12px;">胜率</th>
              <th style="padding:8px;font-size:12px;">年交易</th>
              <th style="padding:8px;font-size:12px;">通过</th>
              <th style="padding:8px;font-size:12px;">原因</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>'''

def build_retired_table(strategies, total):
    rows = ""
    for i, s in enumerate(strategies, 1):
        market_tag = '🇺🇸' if s['market'] == 'US' else '🇭🇰'
        rows += f'''<tr style="background:{'#fff' if i%2 else '#fafafa'};">
          <td style="padding:5px 6px;font-size:11px;text-align:center;">{i}</td>
          <td style="padding:5px 6px;font-size:11px;">{market_tag} {s['name']}</td>
          <td style="padding:5px 6px;font-size:11px;text-align:center;color:{val_color(s['annual'])};">{s['annual']}%</td>
          <td style="padding:5px 6px;font-size:11px;text-align:center;color:{val_color(s['drawdown'],inverse=True)};font-weight:bold;">{s['drawdown']}%</td>
          <td style="padding:5px 6px;font-size:10px;color:#e53935;">{s['reason']}</td>
          <td style="padding:5px 6px;font-size:10px;color:#999;">{s['time']}</td>
        </tr>'''
    
    return f'''
    <div style="margin-bottom:20px;">
      <div style="background:linear-gradient(135deg,#4e342e,#6d4c41);padding:10px 16px;border-radius:10px 10px 0 0;">
        <span style="color:#fff;font-size:14px;font-weight:bold;">🗑️ 废弃策略库（共{total}个，展示最近10个）</span>
      </div>
      <div style="overflow-x:auto;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 10px 10px;">
        <table style="width:100%;border-collapse:collapse;min-width:500px;">
          <thead>
            <tr style="background:#efebe9;">
              <th style="padding:6px;font-size:11px;">#</th>
              <th style="padding:6px;font-size:11px;text-align:left;">策略名称</th>
              <th style="padding:6px;font-size:11px;">年化</th>
              <th style="padding:6px;font-size:11px;">回撤</th>
              <th style="padding:6px;font-size:11px;">废弃原因</th>
              <th style="padding:6px;font-size:11px;">时间</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>'''

# ========== 构建HTML ==========
cards_html = "".join(build_strategy_card(s) for s in top_strategies)
stats_html = build_stats_block()
us_table = build_strategy_table(us_new_strategies, "美股US")
hk_table = build_strategy_table(hk_new_strategies, "港股HK")
retired_table = build_retired_table(retired_strategies, 24)

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="format" content="flow">
<title>牛市/全局回测定时报告</title>
<style>
  body {{ margin:0; padding:0; background:#f0f2f5; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif; }}
  .container {{ max-width:600px; margin:0 auto; padding:12px; }}
  a {{ color:#1565c0; text-decoration:none; }}
</style>
</head>
<body>
<div class="container">

<!-- 标题栏 -->
<div style="background:linear-gradient(135deg,#0d47a1,#1a237e,#311b92);border-radius:14px;padding:20px 16px;margin-bottom:16px;text-align:center;box-shadow:0 4px 16px rgba(13,71,161,0.3);">
  <div style="color:#ffd54f;font-size:12px;letter-spacing:2px;margin-bottom:6px;">📈 BLAKEVER STRATEGY ARENA</div>
  <div style="color:#fff;font-size:20px;font-weight:bold;margin-bottom:4px;">牛市/全局回测定时报告</div>
  <div style="color:rgba(255,255,255,0.7);font-size:13px;">{date_str} {time_str} · 双市场扫描</div>
</div>

<!-- 统计概览 -->
{stats_html}

<!-- 排行榜前五 -->
<div style="background:linear-gradient(135deg,#1b5e20,#2e7d32);padding:10px 16px;border-radius:10px;margin-bottom:12px;">
  <span style="color:#fff;font-size:14px;font-weight:bold;">🏆 策略排行榜 TOP {len(top_strategies)}</span>
</div>
{cards_html}

<!-- 美股回测数据 -->
{us_table}

<!-- 港股回测数据 -->
{hk_table}

<!-- 废弃策略库 -->
{retired_table}

<!-- 底部说明 -->
<div style="background:#fff;border-radius:10px;padding:14px 16px;margin-top:16px;border:1px solid #e0e0e0;">
  <div style="font-size:13px;color:#333;font-weight:bold;margin-bottom:8px;">📋 扫描说明</div>
  <div style="font-size:12px;color:#666;line-height:1.8;">
    • 美股扫描：发现13个策略，9个新策略，全部因回撤>25%得零分<br>
    • 港股扫描：发现13个策略，11个新策略，全部因回撤>25%得零分<br>
    • 当前有效策略4个（得分>0），废弃库累计24个<br>
    • 评分标准：年化≥15%、夏普≥0.5、回撤≤25%为基础门槛<br>
    • 🥇 GEM日度9M+3d缓冲策略以47.88分稳居榜首，是唯一通过鲁棒性检验的策略
  </div>
</div>

<div style="text-align:center;padding:16px 0;color:#999;font-size:11px;">
  Blakever Strategy Arena · 自动生成<br>
  {date_str} {time_str}
</div>

</div>
</body>
</html>'''

# ========== 发送邮件 ==========
subject = f"【牛市/全局回测定时报告】{date_str} {time_str}"

msg = MIMEMultipart('alternative')
msg['Subject'] = subject
msg['From'] = '848786642@qq.com'
msg['To'] = '848786642@qq.com'

html_part = MIMEText(html, 'html', 'utf-8')
msg.attach(html_part)

try:
    server = smtplib.SMTP_SSL('smtp.qq.com', 465)
    server.login('848786642@qq.com', 'ljbtvacrctjobfed')
    server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())
    server.quit()
    print("✅ 邮件发送成功！")
except Exception as e:
    print(f"❌ 邮件发送失败: {e}")
    raise
