#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF池健康维护模块 (适配自聚宽ETF池定期维护脚本)
==============================================
功能：
  1. 对现有ETF池逐只健康检查（流动性、趋势、夏普）
  2. 按五大分类（海外/商品/A股宽基/A股行业/债券）归类
  3. 同类别内相关性去重检测
  4. 输出HTML报告 + 标记不达标ETF

数据源：本地 etf CSV（date,open,high,low,close,volume）
运行频率：每日开盘检查（09:10）自动执行
"""
import warnings
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ETF_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'etf'

# ====== 参数（与聚宽原版一致） ======
MIN_DAILY_AMOUNT = 50_000_000      # 近20日均成交额不低于5000万
LOOKBACK_DAYS = 60                 # 趋势回看天数
MIN_SHARPE = 0.3                   # 最低60日夏普
MAX_CORRELATION = 0.75             # 同类别内最大允许相关性

# ====== ETF分类关键词（与聚宽原版一致） ======
CATEGORY_RULES = [
    ('bond', ['债', '转债', '国债', '城投', '利率债', '信用债', '短融']),
    ('commodity', ['黄金', '白银', '豆粕', '原油', '有色', '能源化工', '煤炭',
                   '铜', '铝', '锌', '镍', '锡', '铁矿石', '螺纹钢', 'PTA',
                   '橡胶', '棕榈油', '棉花', '白糖', '玉米', '生猪']),
    ('overseas', ['纳指', '标普', '道琼斯', '日经', '德国', '法国', '英国',
                  '东南亚', '中韩', '港股', '恒生', '中概', '纳斯达克',
                  'DAX', 'CAC', 'FTSE', '韩国', '越南', '印度',
                  '海外', '全球', '亚太', '新兴市场', 'QDII', 'qdii']),
]
BROAD_KEYWORDS = ['沪深300', '中证500', '中证1000', '中证2000', '上证50', '上证180',
                  '上证', '创业板', '科创50', '科创100', '国证2000', '深证100',
                  'A50', 'A500', 'A100', '中证800', '中证全指', '深成指',
                  '红利低波', '红利', '价值', '成长', '自由现金流', 'MSCI', 'ESG', '基本面']
SECTOR_KEYWORDS = ['芯片', '半导体', '光伏', '新能', '电池', '军工', '国防',
                   '医疗', '医药', '生物', '消费', '食品', '饮料', '酒',
                   '科技', '通信', '5G', 'AI', '人工智能', '游戏', '传媒',
                   '银行', '券商', '证券', '保险', '地产', '房地产',
                   '汽车', '钢铁', '化工', '建材', '机械', '电力', '电网',
                   '农业', '畜牧', '旅游', '运输', '物流', '环保',
                   '软件', '计算机', '云计算', '大数据', '物联网', '区块链',
                   '碳中和', '碳达峰', '央企', '国企', '一带一路',
                   '卫星', '机床', '工业母机', '机器人', '电信', 'TMT']

CAT_LABELS = {'overseas': '海外/跨境', 'commodity': '商品', 'domestic_broad': 'A股宽基',
              'domestic_sector': 'A股行业/主题', 'bond': '债券'}


def classify_etf(name):
    """按名�自动分类"""
    if not name: return 'domestic_sector'
    for cat, keywords in CATEGORY_RULES:
        if any(kw in name for kw in keywords):
            return cat
    # A股宽基 vs 行业
    is_broad = any(kw in name for kw in BROAD_KEYWORDS)
    is_sector = any(kw in name for kw in SECTOR_KEYWORDS)
    if is_broad and not is_sector:
        return 'domestic_broad'
    return 'domestic_sector'


def load_etf_data(code, end_date=None):
    """加载单只ETF日线, 返回 DataFrame (index=date)"""
    raw = code.replace('sh', '').replace('sz', '')
    fp = ETF_DIR / f'{raw}.csv'
    if not fp.exists():
        return None
    df = pd.read_csv(fp)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    if end_date:
        df = df[df.index <= pd.Timestamp(end_date)]
    return df


def compute_metrics(df):
    """计算单只ETF的核心指标"""
    if len(df) < 40:
        return None

    # 近20日均成交额（volume × close；若volume全为0则标记为不可用）
    recent = df.tail(20)
    vol_data = recent['volume']
    has_volume = (vol_data > 0).sum() > 5  # 至少5天有成交量
    if has_volume:
        avg_amount = (vol_data * recent['close']).mean()
    else:
        avg_amount = None  # 无真实成交量数据

    # 60日收益率
    if len(df) >= LOOKBACK_DAYS:
        ret_60d = (df['close'].iloc[-1] / df['close'].iloc[-LOOKBACK_DAYS] - 1)
    else:
        ret_60d = 0

    # 日收益率序列
    daily_rets = df['close'].pct_change().dropna()
    if len(daily_rets) < 20:
        return None

    # 60日夏普（年化）
    recent_rets = daily_rets.tail(LOOKBACK_DAYS)
    ann_ret = recent_rets.mean() * 252
    ann_vol = recent_rets.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # 最新价
    last_close = float(df['close'].iloc[-1])
    last_date = str(df.index[-1].date())

    return {
        'avg_amount': avg_amount,
        'ret_60d': ret_60d,
        'sharpe_60d': sharpe,
        'last_close': last_close,
        'last_date': last_date,
        'daily_returns': daily_rets,
        'n_days': len(df),
    }


def run_health_check(qmt_pool, qmt_names):
    """对ETF池逐只健康检查，返回结构化结果"""
    today = datetime.now().strftime('%Y-%m-%d')
    results = {
        'date': today,
        'total': len(qmt_pool),
        'ok': [],       # 健康
        'warn': [],     # 需关注
        'dead': [],     # 退市/无数据
        'categories': {'overseas': [], 'commodity': [], 'domestic_broad': [],
                       'domestic_sector': [], 'bond': []},
        'high_corr_pairs': [],  # 高相关对
    }

    raw_codes = [c.replace('sh', '').replace('sz', '') for c in qmt_pool]

    # 逐只检查
    for code, raw in zip(qmt_pool, raw_codes):
        name = qmt_names.get(code, raw)
        df = load_etf_data(code, today)
        if df is None:
            results['dead'].append({'code': raw, 'name': name, 'reason': '本地无数据'})
            continue

        m = compute_metrics(df)
        if m is None:
            results['dead'].append({'code': raw, 'name': name, 'reason': '数据不足(需>=40日)'})
            continue

        issues = []
        if m['avg_amount'] is not None and m['avg_amount'] < MIN_DAILY_AMOUNT:
            issues.append(f"成交额{m['avg_amount']/1e8:.2f}亿 < 阈值{MIN_DAILY_AMOUNT/1e8:.1f}亿")
        if m['sharpe_60d'] < MIN_SHARPE:
            issues.append(f"夏普{m['sharpe_60d']:.2f} < 阈值{MIN_SHARPE}")

        cat = classify_etf(name)
        entry = {'code': raw, 'full_code': code, 'name': name, 'category': cat,
                 'ret_60d': m['ret_60d'], 'sharpe_60d': m['sharpe_60d'],
                 'avg_amount': m['avg_amount'], 'last_date': m['last_date'],
                 'issues': issues, 'daily_returns': m['daily_returns'], 'n_days': m['n_days']}

        if issues:
            results['warn'].append(entry)
        else:
            results['ok'].append(entry)

        results['categories'][cat].append(entry)

    # 同类别内相关性检测
    all_daily_rets = {}
    for entry in results['ok'] + results['warn']:
        all_daily_rets[entry['code']] = entry['daily_returns']

    for cat, entries in results['categories'].items():
        if len(entries) <= 1:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                ri = all_daily_rets.get(entries[i]['code'])
                rj = all_daily_rets.get(entries[j]['code'])
                if ri is None or rj is None:
                    continue
                common_len = min(len(ri), len(rj))
                if common_len < 20:
                    continue
                corr = np.corrcoef(ri.iloc[-common_len:], rj.iloc[-common_len:])[0, 1]
                if corr > MAX_CORRELATION:
                    results['high_corr_pairs'].append({
                        'a_code': entries[i]['code'], 'a_name': entries[i]['name'],
                        'b_code': entries[j]['code'], 'b_name': entries[j]['name'],
                        'corr': round(corr, 3), 'category': cat,
                    })

    return results


def generate_html(results, qmt_pool):
    """生成ETF池健康报告HTML"""
    if results is None:
        return '<div style="background:#FFF3CD;padding:10px;">⚠️ ETF池健康检查执行失败</div>'

    html = f"""<div class="card">
<h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">🏥 ETF池健康检查 ({results['date']})</h3>
<div style="font-size:12px;margin-bottom:10px;">
  总池: <b>{results['total']}</b>只 |
  ✅ 健康: <b style="color:#28A745;">{len(results['ok'])}</b>只 |
  ⚠️ 预警: <b style="color:#F9A825;">{len(results['warn'])}</b>只 |
  ❌ 无数据: <b style="color:#DC3545;">{len(results['dead'])}</b>只
</div>
"""

    # Critical warnings
    if len(results['warn']) > 0:
        html += '<div style="background:#FFF3CD;padding:6px 10px;border-radius:4px;margin-bottom:8px;font-size:11px;">'
        html += '<b>⚠️ 以下ETF指标不达标，建议关注：</b>'
        html += '<div style="overflow-x:auto;"><table style="font-size:11px;width:100%;border-collapse:collapse;">'
        html += '<tr><th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">代码</th><th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">名称</th><th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">分类</th><th style="background:#1F4E79;color:#fff;padding:4px;text-align:right;">60日涨幅</th><th style="background:#1F4E79;color:#fff;padding:4px;text-align:right;">夏普</th><th style="background:#1F4E79;color:#fff;padding:4px;text-align:right;">日均成交额</th><th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">问题</th></tr>'
        for e in results['warn']:
            amt = e.get('avg_amount')
            amt_str = f'{amt/1e8:.1f}亿' if amt is not None else 'N/A'
            cat_label = CAT_LABELS.get(e['category'], e['category'])
            html += f"""<tr style="white-space:nowrap;">
<td style="padding:2px 6px;">{e['code']}</td><td style="padding:2px 6px;">{e['name']}</td>
<td style="padding:2px 6px;">{cat_label}</td>
<td style="padding:2px 6px;text-align:right;color:{'#DC3545' if e['ret_60d']<0 else '#28A745'};">{e['ret_60d']*100:+.1f}%</td>
<td style="padding:2px 6px;text-align:right;">{e['sharpe_60d']:.2f}</td>
<td style="padding:2px 6px;text-align:right;">{amt_str}</td>
<td style="padding:2px 6px;font-size:10px;color:#C62828;">{'<br>'.join(e['issues'])}</td></tr>"""
        html += '</table></div></div>'

    # Category summary
    html += '<div style="font-size:11px;margin-top:6px;color:#666;">'
    cat_parts = []
    for cat in ['overseas', 'commodity', 'domestic_broad', 'domestic_sector', 'bond']:
        n = len(results['categories'][cat])
        w = sum(1 for e in results['warn'] if e['category'] == cat)
        d = sum(1 for e in results['dead'] if classify_etf(e.get('name', '')) == cat)
        if n > 0:
            warn_str = f' ({w}⚠️)' if w > 0 else ''
            dead_str = f' ({d}❌)' if d > 0 else ''
            cat_parts.append(f"{CAT_LABELS[cat]}: {n}只{warn_str}{dead_str}")
    html += ' | '.join(cat_parts)
    html += '</div></div>'

    return html


def should_alert(results):
    """判断是否需要发送告警邮件"""
    if results is None:
        return True
    # 超20%预警或10%无数据 → 告警
    warn_pct = len(results['warn']) / max(results['total'], 1) * 100
    dead_pct = len(results['dead']) / max(results['total'], 1) * 100
    return warn_pct > 20 or dead_pct > 10


def send_health_alert(results):
    """发送ETF池健康告警邮件（仅在有严重问题时调用）"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not should_alert(results):
        return False

    subject = f"⚠️ [ETF池健康告警] QMT池 {results['date']} — 预警{len(results['warn'])}只/无数据{len(results['dead'])}只"

    body = f"""<html><body style="font-family:Arial,sans-serif;">
<h2>ETF池健康告警</h2>
<p>日期: {results['date']} | 总池: {results['total']}只</p>

<h3>⚠️ 预警 ({len(results['warn'])}只)</h3>
<table border="1" cellpadding="4" cellspacing="0" style="font-size:12px;">
<tr><th>代码</th><th>名称</th><th>分类</th><th>60日涨幅</th><th>夏普</th><th>问题</th></tr>"""
    for e in results['warn']:
        body += f"<tr><td>{e['code']}</td><td>{e['name']}</td><td>{CAT_LABELS.get(e['category'],'?')}</td>"
        body += f"<td>{e['ret_60d']*100:+.1f}%</td><td>{e['sharpe_60d']:.2f}</td>"
        body += f"<td>{'; '.join(e['issues'])}</td></tr>"

    body += "</table>"
    if results['dead']:
        body += f"<h3>❌ 无数据 ({len(results['dead'])}只)</h3><ul>"
        for d in results['dead']:
            body += f"<li>{d['code']} {d.get('name','?')}: {d.get('reason','')}</li>"
        body += "</ul>"
    body += "<p><i>— ETF池自动维护系统</i></p></body></html>"

    try:
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = '848786642@qq.com'
        msg['To'] = '848786642@qq.com'
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15) as s:
            s.login('848786642@qq.com', 'lwiaaojxqjqebdjf')
            s.send_message(msg)
        print(f'[ETF健康] 告警邮件已发送: {subject}')
        return True
    except Exception as e:
        print(f'[ETF健康] 告警邮件发送失败: {e}')
        return False


# ====== 全市场ETF发掘 (每季度运行一次) ======
def _download_etf_kline(code, days=90):
    """下载单只ETF近N天K线，返回DataFrame"""
    try:
        import akshare as ak
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')
        df = ak.fund_etf_hist_em(symbol=code, period='daily', start_date=start, end_date=end, adjust='qfq')
        if df is None or len(df) < 20:
            return None
        df = df.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close',
                                '最高': 'high', '最低': 'low', '成交量': 'volume', '成交额': 'amount'})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        return df
    except Exception:
        return None


def discover_new_etfs(qmt_pool, qmt_names, top_n=15, dry_run=False):
    """全市场ETF发掘：扫描不在池中的优质ETF

    Args:
        qmt_pool: 当前QMT池 (sh/sz格式)
        qmt_names: 名称映射
        top_n: 每分类推荐前N只
        dry_run: True=仅列出候选不下数据(快速模式)

    Returns: dict with 'candidates' list + 'categories' breakdown
    """
    today = datetime.now().strftime('%Y-%m-%d')
    raw_codes_in_pool = set(c.replace('sh', '').replace('sz', '') for c in qmt_pool)

    print(f"\n{'='*60}")
    print(f"  全市场ETF发掘 — {today}")
    print(f"{'='*60}")

    # Step 1: 获取全市场ETF列表
    print("[Step 1] 获取全市场ETF/LOF列表...")
    try:
        import akshare as ak
        all_etfs = ak.fund_etf_category_sina()
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return {'error': str(e), 'candidates': []}

    print(f"  共 {len(all_etfs)} 只")

    # Step 2: 过滤 — 排除LOF/退市/已在池中
    print("[Step 2] 过滤: 排除LOF/退市/已在池中...")
    candidates = []
    for _, row in all_etfs.iterrows():
        code_raw = str(row['代码'])
        name = str(row['名称'])

        # 跳过LOF
        if 'LOF' in name.upper() or code_raw.startswith('sz169'):
            continue
        # 跳过已在池中的
        pure = code_raw.replace('sh', '').replace('sz', '')
        if pure in raw_codes_in_pool:
            continue
        # 跳过已退市
        try:
            if float(row['最新价']) <= 0:
                continue
        except (ValueError, KeyError):
            continue
        # 跳过成交额过小 (<50万)
        try:
            amount = float(row['成交额'])
            if amount < 500000:
                continue
        except (ValueError, KeyError):
            continue

        cat = classify_etf(name)
        if cat == 'unknown':
            cat = 'domestic_sector'

        candidates.append({
            'code': pure, 'name': name, 'category': cat,
            'price': float(row.get('最新价', 0)),
            'amount': float(row.get('成交额', 0)),
        })

    print(f"  候选: {len(candidates)} 只（不在当前{len(qmt_pool)}只池中）")
    if not candidates:
        return {'error': '无候选ETF', 'candidates': []}

    cat_counts = {}
    for c in candidates:
        cat_counts[c['category']] = cat_counts.get(c['category'], 0) + 1
    for cat, n in sorted(cat_counts.items()):
        print(f"    {CAT_LABELS.get(cat, cat)}: {n}只")

    if dry_run:
        candidates.sort(key=lambda x: -x['amount'])
        return {
            'date': today, 'candidates': candidates[:top_n * 5],
            'categories': cat_counts, 'dry_run': True,
        }

    # Step 3: 下载K线 + 计算指标
    print(f"[Step 3] 下载K线 + 计算指标（每只约1~2秒）...")
    scored = []
    for i, c in enumerate(candidates):
        if i % 20 == 0:
            print(f"  进度: {i}/{len(candidates)}...")
        df = _download_etf_kline(c['code'], days=90)
        if df is None or len(df) < 40:
            continue
        m = compute_metrics(df)
        if m is None:
            continue
        scored.append({
            **c,
            'ret_60d': m['ret_60d'],
            'sharpe_60d': m['sharpe_60d'],
            'avg_amount': m['avg_amount'],
            'n_days': m['n_days'],
        })

    print(f"  有效评估: {len(scored)} 只")

    if not scored:
        return {'error': '无有效K线数据', 'candidates': []}

    # Step 4: 分类排名 + 夏普过滤
    print("[Step 4] 分类排名 + 筛选...")
    recommended = []
    for cat in ['overseas', 'commodity', 'domestic_broad', 'domestic_sector', 'bond']:
        cat_candidates = [c for c in scored if c['category'] == cat and c['sharpe_60d'] >= MIN_SHARPE]
        cat_candidates.sort(key=lambda x: -x['ret_60d'])
        top = cat_candidates[:top_n]
        for rank, c in enumerate(top):
            c['rank_in_cat'] = rank + 1
        recommended.extend(top)

    recommended.sort(key=lambda x: -(x['ret_60d'] * 0.5 + x['sharpe_60d'] * 0.5))

    result = {
        'date': today, 'candidates': recommended, 'categories': cat_counts,
        'total_scanned': len(candidates), 'total_evaluated': len(scored),
    }

    print(f"\n  推荐 {len(recommended)} 只新ETF:")
    for c in recommended[:15]:
        cat_label = CAT_LABELS.get(c['category'], c['category'])
        print(f"  {c['code']:>8s} {c['name']:<16s} [{cat_label}]  "
              f"60日:{c['ret_60d']*100:+.1f}% 夏普:{c['sharpe_60d']:.2f}")

    return result


def generate_discover_html(discover_result, qmt_pool):
    """生成ETF发掘报告HTML"""
    if 'error' in discover_result:
        return f'<div style="padding:10px;color:#C62828;">❌ ETF发掘失败: {discover_result["error"]}</div>'

    candidates = discover_result.get('candidates', [])
    if not candidates:
        return '<div style="padding:10px;">未发现符合条件的新ETF</div>'

    html = f"""<div class="card">
<h3 style="font-size:14px;color:#1F4E79;margin:0 0 8px;">🔍 全市场ETF发掘 ({discover_result['date']})</h3>
<div style="font-size:12px;margin-bottom:8px;color:#666;">
  扫描: <b>{discover_result.get('total_scanned', '?')}</b>只 |
  有效评估: <b>{discover_result.get('total_evaluated', '?')}</b>只 |
  推荐: <b style="color:#28A745;">{len(candidates)}</b>只
  {'(仅快速筛选，未下载K线)' if discover_result.get('dry_run') else '(已下载K线+完整评估)'}
</div>
<div style="overflow-x:auto;"><table style="font-size:11px;width:100%;border-collapse:collapse;">
<tr><th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">代码</th>
<th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">名称</th>
<th style="background:#1F4E79;color:#fff;padding:4px;text-align:left;">分类</th>
<th style="background:#1F4E79;color:#fff;padding:4px;text-align:right;">60日涨幅</th>
<th style="background:#1F4E79;color:#fff;padding:4px;text-align:right;">夏普</th>
<th style="background:#1F4E79;color:#fff;padding:4px;text-align:right;">推荐等级</th></tr>"""

    for c in candidates[:20]:
        ret = c.get('ret_60d', 0)
        sharpe = c.get('sharpe_60d', 0)
        cat_label = CAT_LABELS.get(c['category'], c['category'])
        score = ret * 0.5 + sharpe * 0.5
        if score > 0.3:
            level = '⭐⭐⭐ 强烈推荐'
        elif score > 0.1:
            level = '⭐⭐ 推荐'
        elif score > 0:
            level = '⭐ 关注'
        else:
            level = '-'

        html += f"""<tr style="white-space:nowrap;">
<td style="padding:2px 6px;">{c['code']}</td>
<td style="padding:2px 6px;">{c['name']}</td>
<td style="padding:2px 6px;">{cat_label}</td>
<td style="padding:2px 6px;text-align:right;color:{'#DC3545' if ret<0 else '#28A745'};">{ret*100:+.1f}%</td>
<td style="padding:2px 6px;text-align:right;">{sharpe:.2f}</td>
<td style="padding:2px 6px;font-weight:bold;">{level}</td></tr>"""
    html += '</table></div></div>'
    return html


if __name__ == '__main__':
    # 独立测试
    print("ETF池健康检查 独立测试\n")
    from generate_qmt_report import QMT_POOL, QMT_NAMES
    results = run_health_check(QMT_POOL, QMT_NAMES)
    html = generate_html(results, QMT_POOL)
    print(html.replace('<br>', '\n').replace('</tr>', '</tr>\n')[:2000])
