#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星美股版 · 短期负动量(Top7)过滤实验 —— 可视化对比报告生成器
============================================================
读取 us100_short_neg_filter_compare_*.json 结果, 生成 HTML 对比报告:
  - 绩效对比表 (近3年 / 近1年 × base/A/B)
  - SVG 净值(累计收益%)曲线
  - 被禁买股票(短负新晋Top7)的剔除明细 + 后续10交易日表现
  - 口径说明与结论
用法: python make_short_neg_report.py [--json 指定结果文件]
不修改实盘文件, 仅供研究。
"""
import json, glob, sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUT = ROOT / 'backtest' / 'results_us100'

POOL = ('NVDA,AMD,MU,LRCX,LITE,NFLX,GOOGL,NOW,ORCL,SNPS,EOG,NEM,CAT,GE,AMT,'
        'PANW,ZS,NET,IONQ,RKLB,SPCX,COHR,HOOD,WDC,ARM,STX').split(',')
LOOK = 10  # 短动量窗口

SERIES_META = [
    ('3y_base', '近3年 · 原版(权威)', 'base'),
    ('3y_A',    '近3年 · 变体A(禁买留现金)', 'A'),
    ('3y_B',    '近3年 · 变体B(顺延补位)', 'B'),
    ('1y_base', '近1年 · 原版(权威)', 'base'),
    ('1y_A',    '近1年 · 变体A(禁买留现金)', 'A'),
    ('1y_B',    '近1年 · 变体B(顺延补位)', 'B'),
]
COLORS = {'base': '#8A94A6', 'A': '#D64545', 'B': '#2E6BE6'}

# ============ 数据 ============
def load_prices():
    all_data = {}
    for sym in POOL:
        fp = DATA_DIR / f'{sym}.csv'
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp)
            df = df.rename(columns={'Date': 'date', 'Open': 'open', 'High': 'high',
                                    'Low': 'low', 'Close': 'close', 'Last': 'close',
                                    'Volume': 'volume'})
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            df = df[df['close'] > 0]
            all_data[sym] = df
        except Exception:
            pass
    return all_data

ALL_DATA = load_prices()


def fwd_return(code, blk_date, blk_price, n=10):
    """剔除日之后第n个交易日收盘相对剔除价的收益% (数据不足返回None)"""
    df = ALL_DATA.get(code)
    if df is None or blk_price <= 0:
        return None
    after = df[df.index > pd.Timestamp(blk_date)]
    if len(after) < n:
        return None
    later = float(after['close'].iloc[n - 1])
    return (later / blk_price - 1) * 100


def block_stats(examples):
    """统计被禁股票后续10交易日表现"""
    fw = []
    for e in examples:
        r = fwd_return(e['code'], e['date'], e['price'], LOOK)
        if r is not None:
            fw.append(r)
    if not fw:
        return None
    arr = np.array(fw)
    return {'n': len(arr), 'mean': float(arr.mean()),
            'pos_ratio': float((arr > 0).mean() * 100),
            'median': float(np.median(arr))}


def fmt_pct(x, sign=True, nd=2):
    s = f'{abs(x):.{nd}f}'
    if sign and x > 0:
        s = '+' + s
    if sign and x < 0:
        s = '-' + s
    return s


# ============ SVG 曲线 ============
def equity_svg(groups, W=760, H=340):
    """groups: [(tag,color,label,daily_values)]; 同区间内归一比例"""
    L, R, T, B = 58, 14, 16, 30
    pw, ph = W - L - R, H - T - B
    all_y = [v['returns'] * 100 for _, _, _, dv in groups for v in dv]
    ymin, ymax = min(all_y), max(all_y)
    ymin = min(ymin, 0)
    pad = max((ymax - ymin) * 0.06, 2)
    ymax += pad
    ymin = max(ymin - pad * 0.4, -pad * 2.2)

    def X(i, n): return L + pw * i / max(n - 1, 1)
    def Y(y): return T + ph * (1 - (y - ymin) / (ymax - ymin))

    parts = []
    parts.append(f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Microsoft YaHei, sans-serif">')
    # 网格与Y轴
    for g in range(5):
        gy = ymin + (ymax - ymin) * g / 4
        yy = Y(gy)
        parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W - R}" y2="{yy:.1f}" stroke="#3a4356" stroke-opacity="0.16" stroke-width="1"/>')
        parts.append(f'<text x="{L - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="11" fill="#8b93a7">{gy:,.0f}%</text>')
    # X轴刻度(约8个)
    dv0 = groups[0][3]
    n = len(dv0)
    step = max(1, n // 8)
    for i in range(0, n, step):
        d = dv0[i]['date']
        parts.append(f'<text x="{X(i, n):.1f}" y="{H - 10}" text-anchor="middle" font-size="10.5" fill="#8b93a7">{d[2:]}</text>')
    # 曲线
    for tag, color, label, dv in groups:
        pts = ' '.join(f'{X(i, len(dv)):.1f},{Y(v["returns"] * 100):.1f}' for i, v in enumerate(dv))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/>')
    # 图例
    lx = L + 6
    for tag, color, label, dv in groups:
        parts.append(f'<rect x="{lx}" y="{T - 6}" width="14" height="3.5" rx="1.5" fill="{color}"/>')
        parts.append(f'<text x="{lx + 19}" y="{T - 2.5}" font-size="11" fill="#cdd3de">{label}</text>')
        lx += 30 + len(label) * 11
    parts.append('</svg>')
    return ''.join(parts)


# ============ HTML ============
def build_html(res, newest_json):
    # 数值取用
    def G(k): return res[k]

    css = '''
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #10141c; color: #e6e9ef;
           font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }
    .wrap { max-width: 980px; margin: 0 auto; padding: 28px 22px 60px; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .sub { color: #8b93a7; font-size: 13px; margin-bottom: 18px; }
    .rule { background: #171c27; border: 1px solid #2a3140; border-left: 4px solid #e0a63c;
            border-radius: 8px; padding: 12px 16px; font-size: 13.5px; line-height: 1.7; margin-bottom: 20px; }
    .rule b { color: #ffd47e; }
    .concl { background: #16202e; border: 1px solid #2e4a3a; border-left: 4px solid #3ecf8e;
             border-radius: 8px; padding: 14px 16px; margin-bottom: 24px; font-size: 13.5px; line-height: 1.8; }
    .concl b { color: #7ef0bb; }
    .concl .warn { color: #ffb4a2; }
    h2 { font-size: 16px; margin: 26px 0 10px; padding-left: 9px; border-left: 4px solid #3a87e8; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 8px; }
    th, td { border: 1px solid #2a3140; padding: 6px 8px; text-align: right; white-space: nowrap; }
    th { background: #1a202c; color: #aeb6c4; font-weight: 600; }
    td.l, th.l { text-align: left; }
    tr:nth-child(even) td { background: #141926; }
    .base td { background: #1c212c !important; }
    .best { color: #ff7b72; font-weight: 700; }
    .bestb { color: #58a6ff; font-weight: 700; }
    .hl { color: #ffd47e; font-weight: 700; }
    .chartbox { background: #161b25; border: 1px solid #2a3140; border-radius: 10px; padding: 12px; margin: 10px 0 6px; }
    .caption { font-size: 12px; color: #8b93a7; margin: 4px 2px 18px; }
    .grid2 { display: flex; gap: 16px; flex-wrap: wrap; }
    .note { background: #171c27; border: 1px solid #2a3140; border-radius: 8px; padding: 12px 16px;
            font-size: 12.5px; color: #aeb6c4; line-height: 1.75; margin-top: 22px; }
    .tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; margin-left: 6px; }
    .t-red { background: #3a2020; color: #ff8d8d; }
    .t-blue { background: #1d2c4a; color: #7cb3ff; }
    .t-gray { background: #2a2f3a; color: #b6bdc9; }
    .small { font-size: 11.5px; color: #8b93a7; }
    '''
    h = [f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
         f'<title>七星美股版 · 短负动量过滤对比</title><style>{css}</style></head><body><div class="wrap">']

    h.append('<h1>七星美股版 · Top7 短期负动量过滤 —— 对比实验报告</h1>')
    h.append(f'<div class="sub">权威引擎内核逐行复制 · 26只池 · 初始$1,000,000 · 佣金$0.005/股 · 滑点0.05% · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · 数据源文件 {newest_json.name}</div>')

    h.append('''<div class="rule">
<b>实验规则（假设性研究，未上实盘）</b> —— 排名前7中存在 <b>短期动量(10日)为负</b> 的股票时：<br>
&nbsp;&nbsp;① 若 <b>已持有</b> → 保持不变（继续持有，不因短负强制卖出）；<br>
&nbsp;&nbsp;② 若 <b>未持有</b>（刚挤入Top7的新面孔）→ <b>禁止买入</b>。<br>
<b>变体A</b>：剔除后不补位，持仓可少于7只、差额留现金；
<b>变体B</b>：从第8名起顺延补位（短负且未持有者同样禁入）。对照组=权威原版(score≥0.5阈值+NDX5恐慌过滤)。
</div>''')

    # ---------- 汇总指标表 ----------
    def row(tag, label, ttype, show_blocks=True, base_tag=None):
        v = G(tag)
        b = G(base_tag) if base_tag else None
        delta_tr = (v['total_return'] - b['total_return']) if b else None
        delta_sh = (v['sharpe'] - b['sharpe']) if b else None
        cls = 'base' if ttype == 'base' else ''
        bd = f'<span class="hl">{fmt_pct(delta_tr)}pp</span>' if delta_tr is not None else '—'
        sd = f'<span class="hl">{delta_sh:+.3f}</span>' if delta_sh is not None else '—'
        ann_d = (v['annual_return'] - b['annual_return']) if b else None
        ad = f'<span class="hl">({fmt_pct(ann_d, sign=True)}pp)</span>' if ann_d is not None else ''
        bt = f'{v["buys"]} / {v["sells"]}' if not show_blocks else f'{v["buys"]}'
        tagcls = {'base': 't-gray', 'A': 't-red', 'B': 't-blue'}[ttype]
        return (f'<tr class="{cls}"><td class="l">{label} <span class="tag {tagcls}">{ttype.upper()}</span></td>'
                f'<td>{v["days"]}</td>'
                f'<td><b>{fmt_pct(v["total_return"])}%</b> {bd}</td>'
                f'<td>{fmt_pct(v["annual_return"])}% {ad}</td>'
                f'<td>{fmt_pct(-v["max_drawdown"])}%</td>'
                f'<td>{v["sharpe"]:.3f} {sd}</td>'
                f'<td>{v["calmar"]:.1f}</td>'
                f'<td>{v["win_rate"]:.1f}%</td>'
                f'<td>{bt}</td>'
                f'<td>{v["panic_days"]}</td>'
                f'<td>{v["n_blocks"]}</td></tr>')

    h.append('<h2>一、绩效对比（近3年 2023-06-20 ~ 2026-09-02，805交易日）</h2>')
    h.append('<table><tr><th class="l">方案</th><th>天数</th><th>总收益</th><th>年化</th><th>最大回撤</th>'
             '<th>夏普</th><th>卡尔马</th><th>胜率</th><th>买入次</th><th>恐慌日</th><th>剔除短负新股次数</th></tr>')
    h.append(row('3y_base', '原版(权威)', 'base'))
    h.append(row('3y_A', '变体A · 禁买留现金', 'A', base_tag='3y_base'))
    h.append(row('3y_B', '变体B · 顺延补位', 'B', base_tag='3y_base'))
    h.append('</table>')

    h.append('<h2>二、绩效对比（近1年 2025-09-02 ~ 2026-09-02，253交易日）</h2>')
    h.append('<table><tr><th class="l">方案</th><th>天数</th><th>总收益</th><th>年化</th><th>最大回撤</th>'
             '<th>夏普</th><th>卡尔马</th><th>胜率</th><th>买入次</th><th>恐慌日</th><th>剔除短负新股次数</th></tr>')
    h.append(row('1y_base', '原版(权威)', 'base'))
    h.append(row('1y_A', '变体A · 禁买留现金', 'A', base_tag='1y_base'))
    h.append(row('1y_B', '变体B · 顺延补位', 'B', base_tag='1y_base'))
    h.append('</table>')

    # ---------- 净值曲线 ----------
    h.append('<h2>三、净值曲线（累计收益%，同区间同尺度）</h2>')
    svg3 = equity_svg([(t, COLORS[m], lbl, G(t)['daily_values'])
                       for t, lbl, m in SERIES_META if t.startswith('3y')])
    svg1 = equity_svg([(t, COLORS[m], lbl.replace('近1年 · ', ''), G(t)['daily_values'])
                       for t, lbl, m in SERIES_META if t.startswith('1y')])
    h.append(f'<div class="chartbox">{svg3}</div><div class="caption">近3年净值：变体A(红)全程领先原版(灰)，变体B(蓝)与原版基本持平、略低。</div>')
    h.append(f'<div class="chartbox">{svg1}</div><div class="caption">近1年净值：变体A与变体B均明显领先原版，B末端略超A。</div>')

    # ---------- 剔除明细 ----------
    h.append('<h2>四、剔除明细抽样（短负新晋Top7 → 禁买）</h2>')
    for tag in ('3y_A', '1y_A'):
        v = G(tag)
        ex = v['block_examples'][:12]
        st = block_stats(v['block_examples'])
        rows = ''.join(
            f'<tr><td>{e["date"]}</td><td class="l">{e["code"]}</td>'
            f'<td>{e["short"]:+.3f}</td><td>{e["score"]:.2f}</td><td>${e["price"]:,.2f}</td></tr>'
            for e in ex)
        stat = f'被禁标的后续{LOOK}交易日：均涨 <b class="hl">{fmt_pct(st["mean"])}%</b>（正收益占比 {st["pos_ratio"]:.0f}%），'
        h.append(f'<div style="display:flex;gap:24px;flex-wrap:wrap;margin:6px 0 4px;">'
                 f'<div style="flex:1;min-width:330px;"><div style="font-size:13px;font-weight:600;margin:4px 0 6px;">{tag.replace("_", " · ")}（共剔除 {v["n_blocks"]} 次，列示前 {len(ex)} 次）</div>'
                 f'<table style="font-size:12px;"><tr><th>日期</th><th class="l">代码</th><th>10日短动量</th><th>25日得分</th><th>当日价</th></tr>{rows}</table></div></div>')
        if st:
            h.append(f'<div class="small" style="margin:0 0 14px;">▲ 样本统计（n={st["n"]}）：{stat}中位 {fmt_pct(st["median"])}% —— 说明"被禁"标的多数后来确在走强，但原版用整仓新资金追它们反而拖累整体。</div>')

    # ---------- 结论 ----------
    h.append('<h2>五、结论与建议</h2>')
    h.append('''<div class="concl">
<b>★ 近3年（主口径，805交易日）</b><br>
&nbsp;&nbsp;· 变体A（顶部短负新晋股禁买、<b>不补位留现金</b>）：总收益 <b class="hl">+343.94%</b> vs 原版 <b>+319.47%</b>，<b>多赚 +24.5pp</b>；
  夏普 1.512 vs 1.407，回撤 -39.43% vs -39.87% —— <b>收益↑、夏普↑、回撤↓，全面占优</b>；<br>
&nbsp;&nbsp;· 变体B（顺延补位）：+314.61%，反略低于原版 -4.9pp → <b>"宁可空仓少持、不硬买第8名"更优</b>；<br><br>
<b>★ 近1年（253交易日）</b><br>
&nbsp;&nbsp;· 变体A <b class="hl">+106.02%</b>、变体B <b class="hl">+108.02%</b>，均大幅领先原版 +90.59%（+15~17pp）；
  两变体差异极小，夏普 2.06 / 2.12 均高于原版 1.86；<br><br>
<b>★ 机制解读</b>：短期动量为负却挤入Top7的，多为<u>动量排名靠后区间刚冲进来的票</u>；原版会按"其余现金均分"用整仓新资金买它，而短负过滤迫使系统留现金或顺延到更强的第8名以后。样本统计显示被禁标的后10日仍平均上涨，<span class="warn">过滤的真正价值不是"躲开下跌"，而是"不追已短期转弱的票、把钱留给更强的候选"</span>；<br><br>
<b>★ 建议</b>：若上实盘，推荐 <b>变体A</b>（规则简单、3年口径全指标占优、1年口径不输B）；规则改动只需在 <code>us_live_report.py</code> 选股处加一行
"short_score&lt;0 且未持有 → 跳过"，<b>但需克总拍板后</b>再改实盘文件并单独做一次权威引擎全量回归验证。
</div>''')

    # ---------- 口径说明 ----------
    h.append('''<div class="note">
<b>口径与方法说明</b><br>
1. 本实验<u>不改动任何实盘文件</u>，仅复制权威引擎（us_live_report.py：26只池 / score≥0.5阈值 / NDX5恐慌过滤 / 佣金$0.005/股 / 滑点0.05%）作为回测内核，逐行一致后叠加过滤开关；<br>
2. 结果文件 <code>us100_short_neg_filter_compare_*.json</code> 含每日净值、全部交易记录与逐次剔除明细，可复核；<br>
3. 本脚本 3y 原版基准 +319.47% 与权威引擎最近一次运行 +310.48% 的差异，全部来自 NDX100 kline 每次拉取窗口边界不同（权威历史模拟存在固有噪声，恐慌日清仓市值随之微差，12个恐慌清仓日与 9/1 清仓行为完全一致）——<b>不影响 base/A/B 同口径下的相对结论</b>；<br>
4. 短期动量 = 10日加权对数回归分 <code>(exp(slope×250)-1)×R²</code>（与实盘报告 short_score 列同款），已在 Top7 候选内单独判断，不影响长期25日排名本身。
</div>''')
    h.append('</div></body></html>')
    return ''.join(h)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=None)
    args = ap.parse_args()
    if args.json:
        jp = Path(args.json)
    else:
        cands = sorted(OUT.glob('us100_short_neg_filter_compare_*.json'))
        jp = cands[-1]
    res = json.loads(jp.read_text(encoding='utf-8'))
    missing = [k for k in ('3y_base', '3y_A', '3y_B', '1y_base', '1y_A', '1y_B') if k not in res]
    if missing:
        sys.exit(f'JSON缺少分组: {missing}')
    html = build_html(res, jp)
    out_html = OUT / f'七星美股版_短负动量过滤对比_{datetime.now().strftime("%Y%m%d_%H%M")}.html'
    out_html.write_text(html, encoding='utf-8')
    print(f'报告已生成: {out_html}  ({len(html):,} bytes)')
    print('文件内嵌svg曲线, 可直接浏览器打开/邮件附件')


if __name__ == '__main__':
    main()
