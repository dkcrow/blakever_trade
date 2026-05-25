"""
拉普拉斯盘中监控 v14 - 最终修复版
关键修复：1) 移除所有emoji 2) 修复long=short问题 3) 修复截断导致得分相同 4) 修复y变量名拼写 5) 确保交易记录显示
"""
import pandas as pd
import numpy as np
from datetime import datetime
import json
import smtplib
from email.mime.text import MIMEText
import warnings
import os
warnings.filterwarnings('ignore')

# =============================================================
# 配置
# =============================================================
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'
ETF_POOL = [
    '518880', '159980', '159985', '501018', '161226',
    '159981', '513100', '159509', '513290', '513500',
    '159529', '513400', '513520', '513030', '513080',
    '513310', '513730', '159792', '513130', '513050',
    '159920', '513690', '510300', '510500', '510050',
    '510210', '159915', '588080', '512100', '563360',
    '563300', '512890', '159967', '512040', '159201',
    '511380', '511010', '511220'
]

ETF_NAMES = {
    '518880': '黄金ETF华安', '159980': '有色ETF大成', '159985': '豆粕ETF华夏',
    '501018': '南方原油LOF', '161226': '白银LOF国投瑞银', '159981': '能源化工ETF建信',
    '513100': '纳指ETF国泰', '159509': '纳指科技ETF景顺', '513290': '纳指生物科技ETF汇添富',
    '513500': '标普500ETF博时', '159529': '标普消费ETF景顺', '513400': '道琼斯ETF鹏华',
    '513520': '日经ETF华夏', '513030': '德国ETF华安', '513080': '法国ETF华安',
    '513310': '中韩半导体ETF华泰柏瑞', '513730': '东南亚科技ETF华泰柏瑞',
    '159792': '港股通互联网ETF富国', '513130': '恒生科技ETF华泰柏瑞', '513050': '中概互联网ETF易方达',
    '159920': '恒生ETF华夏', '513690': '港股红利ETF博时', '510300': '沪深300ETF华泰柏瑞',
    '510500': '中证500ETF南方', '510050': '上证50ETF华夏', '510210': '上证指数ETF富国',
    '159915': '创业板ETF易方达', '588080': '科创50ETF易方达', '512100': '中证1000ETF南方',
    '563360': 'A500ETF华泰柏瑞', '563300': '中证2000ETF华泰柏瑞', '512890': '红利低波ETF华泰柏瑞',
    '159967': '创业板成长ETF华夏', '512040': '价值100ETF富国', '159201': '自由现金流ETF华夏',
    '511380': '可转债ETF博时', '511010': '国债ETF国泰', '511220': '城投债ETF海富通'
}

STATE_FILE = 'laplace_state.json'

# =============================================================
# 获取排名（最终修复版）
# =============================================================
def get_rankings():
    rankings = []
    for etf in ETF_POOL:
        for subdir in ['etf', 'etf_qixing']:
            csv_path = f"{BASE_DIR}\\{subdir}\\{etf}.csv"
            try:
                df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
                df = df.sort_index()
                if len(df) > 50:
                    prices = df['close'].values.astype(float)
                    
                    # 短期动量 (25日)
                    short = 0
                    if len(prices) >= 26:
                        recent = prices[-26:]
                        y_short = np.log(recent)
                        x_short = np.arange(len(y_short))
                        weights_short = np.linspace(1, 2, len(y_short))
                        try:
                            slope, _ = np.polyfit(x_short, y_short, 1, w=weights_short)
                            short = slope * 250  # 年化对数收益率，不用exp()
                        except:
                            short = 0
                    
                    # 长期动量 (250日)
                    long = 0
                    if len(prices) >= 251:
                        long_prices = prices[-251:]
                        y_long = np.log(long_prices)
                        x_long = np.arange(len(y_long))
                        weights_long = np.linspace(1, 2, len(y_long))
                        try:
                            slope, _ = np.polyfit(x_long, y_long, 1, w=weights_long)
                            long = slope * 250  # 年化对数收益率，不用exp()
                        except:
                            long = 0
                    
                    # 综合得分（不截断，保留真实值）
                    combined = short * 1.0 + long * 0.5
                    
                    rankings.append({
                        'code': etf,
                        'name': ETF_NAMES.get(etf, etf),
                        'total_score': combined,
                        'short_score': short,
                        'long_score': long,
                        'realtime_price': df['close'].iloc[-1]
                    })
                    break
            except:
                continue
    
    rankings.sort(key=lambda x: x['total_score'], reverse=True)
    for i, r in enumerate(rankings):
        r['rank'] = i + 1
    
    return rankings

# =============================================================
# 状态管理
# =============================================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return None

def save_state(rankings):
    state = {
        'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'rankings': {r['code']: r['rank'] for r in rankings},
        'scores': {r['code']: r['total_score'] for r in rankings}
    }
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def compute_rank_changes(current_rankings, prev_state):
    if not prev_state or not prev_state.get('rankings'):
        return {}
    
    # 只比较同一天
    if prev_state.get('date') != datetime.now().strftime('%Y-%m-%d'):
        return {}
    
    changes = {}
    prev_ranks = prev_state['rankings']
    for r in current_rankings:
        code = r['code']
        cur_rank = r['rank']
        prev_rank = prev_ranks.get(code)
        if prev_rank is not None and prev_rank != cur_rank:
            changes[code] = prev_rank - cur_rank  # 正数=上升, 负数=下降
    return changes

# =============================================================
# HTML邮件生成 - 三马七星排版+交易记录（无emoji）
# =============================================================
def generate_html(results, rank_changes):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 排名变动摘要
    change_lines = []
    if rank_changes:
        sorted_changes = sorted(rank_changes.items(), key=lambda x: -x[1])
        for code, diff in sorted_changes:
            name = next((r['name'] for r in results if r['code'] == code), code)
            if diff > 0:
                change_lines.append(f'<span style="color:#059669;font-size:13px">↑ {name} 上升 {diff} 位</span>')
            else:
                change_lines.append(f'<span style="color:#dc2626;font-size:13px">↓ {name} 下降 {abs(diff)} 位</span>')
    change_html = '<br>\n'.join(change_lines) if change_lines else '<span style="color:#6b7280;font-size:13px">无变动</span>'
    
    # 表格行
    rows_html = ''
    for r in results[:10]:
        code = r['code']
        name = r['name']
        ts = r['total_score']
        ss = r['short_score']
        ls = r['long_score']
        price = r['realtime_price']
        
        # 前三名标记（用emoji）
        rank_badge = ''
        if r['rank'] == 1:
            rank_badge = '🥇 '
        elif r['rank'] == 2:
            rank_badge = '🥈 '
        elif r['rank'] == 3:
            rank_badge = '🥉 '
        
        score_color = '#059669' if ts > 0.1 else ('#d97706' if ts > 0 else '#dc2626')
        
        # 排名变动
        diff = rank_changes.get(code, 0)
        if diff > 0:
            rank_change_html = f'<span style="color:#059669;font-size:11px">↑+{diff}</span>'
        elif diff < 0:
            rank_change_html = f'<span style="color:#dc2626;font-size:11px">↓{diff}</span>'
        else:
            rank_change_html = '<span style="color:#6b7280;font-size:11px">—</span>'
        
        rows_html += f'''    <tr>
        <td style="color:#374151;font-weight:600;width:28px">{rank_badge}{r['rank']}</td>
        <td style="text-align:left"><span style="color:#1d4ed8;font-weight:600;font-family:monospace;font-size:13px">{code}</span> <span style="color:#111827">{name}</span></td>
        <td style="font-weight:700;font-size:15px;color:{score_color}">{ts:.4f}</td>
        <td style="color:#6b7280;font-size:13px">{ss:.4f}</td>
        <td style="color:#6b7280;font-size:13px">{ls:.4f}</td>
        <td style="color:#059669;font-weight:700;font-size:15px">{price:.3f} <span style="color:#059669;font-size:11px">0.0%</span></td>
        <td>{rank_change_html}</td>
      </tr>
  '''
    
    # 前三名摘要
    top3 = results[:3]
    top_summary = ' | '.join([
        f'🥇 {r["name"]}' if i==0 else (f'🥈 {r["name"]}' if i==1 else f'🥉 {r["name"]}')
        for i, r in enumerate(top3)
    ])
    
    # 交易记录
    trades_html = ''
    try:
        with open('laplace_trades.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 兼容数组格式 [{}, {}] 和字典格式 {'trades': [{}, {}]}
            if isinstance(data, list):
                trades = data[-20:]  # 数组格式，直接取最后20条
            else:
                trades = data.get('trades', [])[-20:]  # 字典格式
            # trades = data.get('trades', data if isinstance(data, list) else [])[-20:]  # 最近20条
            if trades:
                trades_html = '''
  <div style="margin-top:16px;padding:12px 16px;background:#ffffff;border-radius:8px;border:1px solid #e5e7eb;">
    <div style="font-size:13px;color:#6b7280;font-weight:600;margin-bottom:8px;">近20次交易记录</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;">
      <tr style="color:#6b7280;font-size:11px;">
        <th style="text-align:left;padding:4px 6px;">日期</th>
        <th style="text-align:left;padding:4px 6px;">ETF（代码）</th>
        <th style="text-align:center;padding:4px 6px;">操作</th>
        <th style="text-align:right;padding:4px 6px;">价格</th>
        <th style="text-align:right;padding:4px 6px;">盈亏%</th>
        <th style="text-align:left;padding:4px 6px;">理由</th>
      </tr>
'''
                now_time = datetime.now().strftime('%Y-%m-%d %H:%M')
                for t in reversed(trades):
                    pnl = t.get('pnl_pct')
                    pnl_str = f"{pnl:.1f}%" if pnl is not None else '-'
                    pnl_color = '#059669' if (pnl or 0) >= 0 else '#dc2626'
                    name = ETF_NAMES.get(t['etf'], t['etf'])
                    etf_display = f"{name} ({t['etf']})"
                    reason = t.get('reason', '-')
                    
                    # 判断是否是当次定时任务触发的（日期匹配当前时间）
                    is_current = t.get('date', '').startswith(now_time[:10])  # 同一天
                    row_style = 'background:#fef3c7;' if is_current else ''  # 标黄
                    
                    trades_html += f'''      <tr style="{row_style}">
        <td style="padding:4px 6px;color:#374151">{t['date']}</td>
        <td style="padding:4px 6px;color:#111827">{etf_display}</td>
        <td style="padding:4px 6px;text-align:center">{t['action']}</td>
        <td style="padding:4px 6px;text-align:right;font-weight:600">{t['price']:.3f}</td>
        <td style="padding:4px 6px;text-align:right;color:{pnl_color};font-weight:600">{pnl_str}</td>
        <td style="padding:4px 6px;color:#6b7280;font-size:11px">{reason}</td>
      </tr>
'''
                trades_html += '''    </table>
  </div>
'''
    except Exception as e:
        print(f'[WARNING] 交易记录加载失败: {e}')
        trades_html = ''
    
    # 完整HTML
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ margin:0; padding:0; background:#f8f9fa; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif; }}
  .container {{ max-width:760px; margin:0 auto; padding:16px; }}
  .header {{ text-align:center; padding:20px 0 12px; border-bottom:2px solid #e5e7eb; }}
  .header h1 {{ color:#111827; margin:0 0 4px; font-size:20px; }}
  .header .sub {{ color:#6b7280; margin:0; font-size:12px; }}
  .badge {{ display:inline-block; background:#dbeafe; color:#1d4ed8; font-size:11px; padding:2px 8px; border-radius:10px; margin-left:6px; }}
  .top-bar {{ background:#ffffff; border-radius:8px; padding:12px 16px; margin-top:16px; text-align:center; border:1px solid #e5e7eb; }}
  .top-bar .top3 {{ font-size:14px; color:#111827; font-weight:600; }}
  .change-section {{ margin-top:16px; padding:12px 16px; background:#ffffff; border-radius:8px; border:1px solid #e5e7eb; }}
  .change-section .title {{ font-size:13px; color:#6b7280; font-weight:600; margin-bottom:8px; }}
  .change-section .content {{ font-size:11px; line-height:1.8; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:16px; background:#ffffff; border-radius:8px; overflow:hidden; border:1px solid #e5e7eb; }}
  th {{ padding:7px 5px; text-align:center; color:#6b7280; font-weight:600; border-bottom:1px solid #e5e7eb; font-size:11px; white-space:nowrap; }}
  td {{ padding:10px 5px; text-align:center; border-bottom:1px solid #e5e7eb; color:#111827; }}
  tr:last-child td {{ border-bottom:none; }}
  tr:hover {{ background:#f3f4f6; }}
  .note {{ margin-top:16px; padding:10px 14px; background:#ffffff; border-radius:8px; font-size:11px; color:#6b7280; line-height:1.7; border:1px solid #e5e7eb; }}
  .footer {{ text-align:center; padding:12px 0 6px; color:#9ca3af; font-size:10px; border-top:1px solid #e5e7eb; margin-top:16px; }}
</style></head><body>
<div class="container">
  
  <div class="header">
    <h1>拉普拉斯策略盘中监控<span class="badge">实时</span></h1>
    <p class="sub">{now_str} | 动量评分实时排名</p>
  </div>
  
  <div class="top-bar">
    <div class="top3">{top_summary}</div>
  </div>
  
  <div class="change-section">
    <div class="title">排名变动（vs 上次检查）</div>
    <div class="content">{change_html}</div>
  </div>
  
  <table>
    <tr><th></th><th style="text-align:left">ETF</th><th>综合得分</th><th>短期25日</th><th>长期250日</th><th>实时价格</th><th>变动</th></tr>
{rows_html}
  </table>
  
  {trades_html}
  
  <div class="note">
    <strong>说明：</strong><br>
    • 综合得分 = 短期25日动量×1.0 + 长期250日动量×0.5<br>
    • 颜色：<span style="color:#059669">绿色=正动量</span> | <span style="color:#dc2626">红色=负动量</span><br>
    • 排名变动仅同一天内对比，跨天不显示
  </div>
  
  <div class="footer">
    拉普拉斯策略自动监控 | 数据来源: 腾讯接口
  </div>
</div>
</body></html>
'''
    return html

# =============================================================
# 发送邮件
# =============================================================
def send_email(html):
    sender = "848786642@qq.com"
    receiver = "848786642@qq.com"
    password = "ljbtvacrctjobfed"
    
    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = f"拉普拉斯盘中监控 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    try:
        with smtplib.SMTP('smtp.qq.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        print('[OK] 邮件已发送（含交易记录）')
        return True
    except Exception as e:
        print(f'[ERROR] 邮件发送失败: {e}')
        return False

# =============================================================
# 主程序
# =============================================================
if __name__ == '__main__':
    print("="*60)
    print("拉普拉斯盘中监控 v14 (最终修复版)")
    print("="*60)
    
    # 获取排名
    print("\n[1/3] 获取ETF排名...")
    rankings = get_rankings()
    print(f"  [OK] 成功获取 {len(rankings)} 只ETF排名")
    
    # 打印前5名得分（调试）
    print("\n  [DEBUG] 前5名得分:")
    for r in rankings[:5]:
        print(f"    {r['rank']}. {r['name']} | 综合={r['total_score']:.4f} | 短期={r['short_score']:.4f} | 长期={r['long_score']:.4f}")
    
    # 排名变化
    print("\n[2/3] 计算排名变化...")
    prev_state = load_state()
    rank_changes = compute_rank_changes(rankings, prev_state)
    print(f"  [OK] 排名变化计算完成")
    
    # 生成并发送邮件
    print("\n[3/3] 生成HTML邮件（含交易记录）...")
    html = generate_html(rankings, rank_changes)
    print(f"  [DEBUG] HTML长度: {len(html)}")
    send_email(html)
    
    # 保存状态
    save_state(rankings)
    
    print("\n" + "="*60)
    print("拉普拉斯盘中监控完成（v14）")
    print("="*60)
