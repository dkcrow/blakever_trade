#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha因子增强策略 v1.5 A股版 - 完整回测
数据源: westock-data (实时行情+K线) + AKShare (指数日线)

回测逻辑:
1. 使用当前实时因子截面选股(中证500成分股)
2. 获取每只股票近120天K线数据
3. 模拟1个月/3个月/6个月持仓收益
4. 对比中证500买入持有基准
5. 评估因子IC(信息系数)

特点: 不依赖JQData, 纯westock-data实现
"""

import os, sys, json, time, warnings, datetime, subprocess
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

WESTOCK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'westock-data', 'scripts', 'tencent_api.mjs')


class Config:
    INITIAL_CAPITAL = 1_000_000
    MAX_STOCK_NUM = 50
    MAX_SINGLE_WEIGHT = 0.06

    FACTOR_WEIGHTS_ORIGINAL = {
        'value': 0.20, 'quality': 0.25, 'growth': 0.15,
        'momentum': 0.15, 'volatility': 0.15, 'liquidity': 0.10
    }

    FACTOR_WEIGHTS = {
        'value': 0.15, 'quality': 0.20, 'growth': 0.10,
        'momentum': 0.30, 'volatility': 0.10, 'liquidity': 0.15
    }

    RISK_FREE_RATE = 0.03


g = Config()


def westock_cmd(*args, delay=1.0):
    """运行腾讯行情API命令，带延迟"""
    time.sleep(delay)
    try:
        # 将 --limit N 转换为位置参数 N
        new_args = []
        skip_next = False
        for i, a in enumerate(args):
            if skip_next:
                # 上一个是 --limit，这个是数字，直接加入
                new_args.append(a)
                skip_next = False
            elif a == '--limit':
                skip_next = True
            elif a == '--days':
                skip_next = True
            else:
                new_args.append(a)
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT] + new_args,
            capture_output=True, text=True, timeout=60
        )
        return result.stdout
    except Exception as e:
        return f"Error: {e}"


def parse_markdown_table(text):
    """解析Markdown表格为DataFrame"""
    lines = text.strip().split('\n')
    table_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith('|') and not line.startswith('| ---') and not line.startswith('|---'):
            table_lines.append(line)

    if len(table_lines) < 2:
        return pd.DataFrame()

    headers = [h.strip() for h in table_lines[0].split('|') if h.strip()]
    rows = []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.split('|') if c.strip() != '']
        if len(cells) >= len(headers):
            rows.append(cells[:len(headers)])

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=headers)
    return df


def _sf(v, default=None):
    """安全转float"""
    if v is None:
        return default
    try:
        f = float(str(v).replace(',', '').replace('%', ''))
        if np.isinf(f) or np.isnan(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


# ================================================================
# 数据获取
# ================================================================
def get_zz500_stocks():
    """获取中证500成分股"""
    import akshare as ak
    df = ak.index_stock_cons_weight_csindex(symbol='000905')

    code_col = [c for c in df.columns if '代码' in c and '成分' in c][0]
    name_col = [c for c in df.columns if '名称' in c and '成分' in c and '英文' not in c][0]

    stocks = df[[code_col, name_col]].copy()
    stocks.columns = ['code', 'name']
    stocks['westock_code'] = stocks['code'].astype(str).apply(
        lambda x: f"sh{x}" if x.startswith('6') else f"sz{x}" if x.startswith('0') or x.startswith('3') else f"bj{x}"
    )
    return stocks


def batch_quote(stocks, batch_size=20):
    """批量获取实时行情"""
    all_data = []
    codes = stocks['westock_code'].tolist()

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        batch_str = ','.join(batch)
        output = westock_cmd('quote', batch_str, delay=0.8)
        df = parse_markdown_table(output)
        if len(df) > 0:
            all_data.append(df)

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()


def batch_kline(codes, limit=120, delay=0.5):
    """逐只获取K线数据"""
    all_data = {}
    for i, code in enumerate(codes):
        output = westock_cmd('kline', code, '--limit', str(limit), delay=delay)
        df = parse_markdown_table(output)
        if len(df) > 0 and 'last' in df.columns:
            # 解析K线
            try:
                kline = pd.DataFrame({
                    'date': df['date'].values,
                    'close': df['last'].astype(float).values,
                    'open': df['open'].astype(float).values if 'open' in df.columns else df['last'].astype(float).values,
                    'high': df['high'].astype(float).values if 'high' in df.columns else df['last'].astype(float).values,
                    'low': df['low'].astype(float).values if 'low' in df.columns else df['last'].astype(float).values,
                    'volume': df['volume'].astype(float).values if 'volume' in df.columns else np.ones(len(df)),
                    'amount': df['amount'].astype(float).values if 'amount' in df.columns else np.ones(len(df)),
                })
                # 按日期升序排列（westock返回是倒序的）
                kline = kline.iloc[::-1].reset_index(drop=True)
                all_data[code] = kline
            except:
                pass

        if (i + 1) % 20 == 0:
            print(f"    K线进度: {i+1}/{len(codes)}")

    return all_data


# ================================================================
# 因子计算
# ================================================================
def calc_factors_from_quote(quote_df):
    """从实时行情计算6大因子"""
    results = []

    for _, row in quote_df.iterrows():
        try:
            code = row.get('code', '')
            if not code:
                continue

            # 价值因子
            pe = _sf(row.get('pe_ratio'))
            pb = _sf(row.get('pb_ratio'))
            ps = _sf(row.get('ps_ttm'))
            pcf = _sf(row.get('pcf_ttm'))
            dividend = _sf(row.get('dividend_ratio_ttm'))

            pe_inv = 1.0 / pe if pe and pe > 0 else (0.01 if pe and pe < 0 else None)
            pb_inv = 1.0 / pb if pb and pb > 0 else (0.01 if pb and pb < 0 else None)
            ps_inv = 1.0 / ps if ps and ps > 0 else (0.01 if ps and ps < 0 else None)
            pcf_inv = 1.0 / pcf if pcf and pcf > 0 else (0.01 if pcf and pcf < 0 else None)

            # 成长/动量因子
            chg_5d = _sf(row.get('chg_5d'))
            chg_10d = _sf(row.get('chg_10d'))
            chg_20d = _sf(row.get('chg_20d'))
            chg_60d = _sf(row.get('chg_60d'))
            chg_ytd = _sf(row.get('chg_ytd'))

            # 流动性因子
            turnover = _sf(row.get('turnover_rate'))
            market_cap = _sf(row.get('total_market_cap'))
            volume_ratio = _sf(row.get('volume_ratio'))

            results.append({
                'code': code,
                'name': row.get('name', ''),
                'price': _sf(row.get('price')),
                'pe_inv': pe_inv, 'pb_inv': pb_inv,
                'ps_inv': ps_inv, 'pcf_inv': pcf_inv,
                'dividend': dividend,
                'chg_5d': chg_5d, 'chg_10d': chg_10d,
                'chg_20d': chg_20d, 'chg_60d': chg_60d, 'chg_ytd': chg_ytd,
                'turnover': turnover, 'market_cap': market_cap,
                'volume_ratio': volume_ratio,
            })
        except:
            continue

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    # 1. 价值因子
    pe_r = df['pe_inv'].rank(pct=True) if df['pe_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    pb_r = df['pb_inv'].rank(pct=True) if df['pb_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    ps_r = df['ps_inv'].rank(pct=True) if df['ps_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    pcf_r = df['pcf_inv'].rank(pct=True) if df['pcf_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    df['value_score'] = (pe_r.fillna(0.5)*0.30 + pb_r.fillna(0.5)*0.30 + ps_r.fillna(0.5)*0.20 + pcf_r.fillna(0.5)*0.20)

    # 2. 质量因子（股息率）
    df['quality_score'] = df['dividend'].rank(pct=True).fillna(0.5) if df['dividend'].notna().sum() > 5 else 0.5

    # 3. 成长因子（A股反向 - 低成长更优，均值回归）
    if df['chg_ytd'].notna().sum() > 5 and df['chg_ytd'].std() > 0.001:
        df['growth_score'] = 1 - df['chg_ytd'].rank(pct=True).fillna(0.5)
    elif df['chg_60d'].notna().sum() > 5 and df['chg_60d'].std() > 0.001:
        df['growth_score'] = 1 - df['chg_60d'].rank(pct=True).fillna(0.5)
    else:
        df['growth_score'] = 0.5

    # 4. 动量因子（中期动量 + 短期反转）
    if df['chg_60d'].notna().sum() > 5 and df['chg_20d'].notna().sum() > 5:
        mom_60 = df['chg_60d'].rank(pct=True).fillna(0.5)
        rev_5 = 1 - df['chg_5d'].rank(pct=True).fillna(0.5)
        rev_10 = 1 - df['chg_10d'].rank(pct=True).fillna(0.5)
        df['momentum_score'] = mom_60 * 0.5 + rev_5 * 0.25 + rev_10 * 0.25
    elif df['chg_20d'].notna().sum() > 5:
        df['momentum_score'] = 1 - df['chg_20d'].rank(pct=True).fillna(0.5)
    else:
        df['momentum_score'] = 0.5

    # 5. 波动因子（高涨跌幅 = 高波动）
    chg_abs = df[['chg_5d', 'chg_10d', 'chg_20d', 'chg_60d']].apply(lambda x: x.abs()).mean(axis=1)
    if chg_abs.notna().sum() > 5:
        df['volatility_score'] = 1 - chg_abs.rank(pct=True).fillna(0.5)
    else:
        df['volatility_score'] = 0.5

    # 6. 流动性因子
    t_r = df['turnover'].rank(pct=True) if df['turnover'].notna().sum() > 5 else None
    c_r = df['market_cap'].rank(pct=True) if df['market_cap'].notna().sum() > 5 else None
    score = pd.Series(0.5, index=df.index)
    if t_r is not None:
        t_score = (1 - (t_r - 0.6).abs() * 1.5).clip(0.2, 1.0).fillna(0.5)
        score = score * 0.4 + t_score * 0.4
    if c_r is not None:
        score = score + c_r.fillna(0.5) * 0.3
    if t_r is not None and c_r is not None:
        score = score - 0.15
    df['liquidity_score'] = score

    return df


def combine_factors(df, factor_weights):
    """合成因子"""
    factor_cols = ['value_score', 'quality_score', 'growth_score',
                   'momentum_score', 'volatility_score', 'liquidity_score']

    for col in factor_cols:
        if col in df.columns:
            std = df[col].std()
            if std > 0 and not pd.isna(std):
                df[col] = (df[col] - df[col].mean()) / std
            else:
                df[col] = 0

    df['combined_factor'] = 0
    total_w = 0
    for col in factor_cols:
        if col in df.columns:
            category = col.replace('_score', '')
            w = factor_weights.get(category, 1/len(factor_cols))
            df['combined_factor'] += df[col].fillna(0) * w
            total_w += w

    if total_w > 0:
        df['combined_factor'] /= total_w
    return df


def select_portfolio(df, max_stocks=50, max_single_weight=0.06):
    """选股 + 权重分配"""
    df = df.sort_values('combined_factor', ascending=False)
    selected = df.head(max_stocks).copy()
    if len(selected) == 0:
        return pd.DataFrame()

    scores = selected['combined_factor'].values
    s_min, s_max = scores.min(), scores.max()
    if s_max > s_min:
        normalized = (scores - s_min) / (s_max - s_min)
        raw_weights = np.exp(normalized * 2)
    else:
        raw_weights = np.ones(len(selected))

    raw_weights = np.minimum(raw_weights, max_single_weight * raw_weights.sum())
    raw_weights = raw_weights / raw_weights.sum()
    selected['weight'] = raw_weights
    return selected


# ================================================================
# 回测模拟
# ================================================================
def simulate_holding(portfolio, kline_data, holding_days_list=[20, 60, 120]):
    """模拟不同持有期的收益"""
    results = {}
    
    for hd in holding_days_list:
        stock_returns = {}
        for _, row in portfolio.iterrows():
            code = row['code']
            weight = row['weight']

            if code in kline_data and len(kline_data[code]) >= hd + 1:
                kline = kline_data[code]
                n = len(kline)
                # 从hd天前买入，持有到最新
                buy_price = kline.iloc[n - hd - 1]['close']
                sell_price = kline.iloc[-1]['close']
                if buy_price > 0:
                    ret = (sell_price - buy_price) / buy_price
                    stock_returns[code] = {
                        'ret': ret,
                        'weight': weight,
                        'weighted_ret': ret * weight,
                    }

        if stock_returns:
            total_return = sum(v['weighted_ret'] for v in stock_returns.values())
            n_stocks = len(stock_returns)
            avg_ret = np.mean([v['ret'] for v in stock_returns.values()])
            win_rate = sum(1 for v in stock_returns.values() if v['ret'] > 0) / len(stock_returns) * 100
            max_ret = max(v['ret'] for v in stock_returns.values())
            min_ret = min(v['ret'] for v in stock_returns.values())
        else:
            total_return = 0
            n_stocks = 0
            avg_ret = 0
            win_rate = 0
            max_ret = 0
            min_ret = 0

        results[f'{hd}d'] = {
            'total_return': total_return,
            'n_stocks': n_stocks,
            'avg_ret': avg_ret,
            'win_rate': win_rate,
            'max_ret': max_ret,
            'min_ret': min_ret,
        }

    return results


def calc_ic(factor_df, kline_data, forward_days=20):
    """计算因子IC（信息系数）"""
    ic_results = {}
    factor_cols = ['value_score', 'quality_score', 'growth_score',
                   'momentum_score', 'volatility_score', 'liquidity_score', 'combined_factor']

    for col in factor_cols:
        if col not in factor_df.columns:
            continue

        ranks = []
        forward_rets = []

        for _, row in factor_df.iterrows():
            code = row['code']
            if code in kline_data and len(kline_data[code]) >= forward_days + 1:
                kline = kline_data[code]
                n = len(kline)
                buy_price = kline.iloc[n - forward_days - 1]['close']
                sell_price = kline.iloc[-1]['close']
                if buy_price > 0:
                    fwd_ret = (sell_price - buy_price) / buy_price
                    factor_val = row[col]
                    if not pd.isna(factor_val):
                        ranks.append(factor_val)
                        forward_rets.append(fwd_ret)

        if len(ranks) > 20:
            ic = np.corrcoef(ranks, forward_rets)[0, 1]
            ic_results[col] = round(ic, 4)

    return ic_results


# ================================================================
# 报告生成
# ================================================================
def generate_report(portfolios, holding_results, ic_results, benchmark_ret, path):
    """生成HTML报告"""
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    tables_html = ''
    for label, portfolio in portfolios.items():
        rows = ''
        for i, (_, row) in enumerate(portfolio.iterrows()):
            chg_60d = row.get('chg_60d', 0) or 0
            cls = 'positive' if chg_60d > 0 else 'negative'
            rows += f'''<tr>
                <td>{i+1}</td>
                <td>{row['code']}</td>
                <td>{row.get('name','')}</td>
                <td>{row['combined_factor']:.3f}</td>
                <td>{row['weight']*100:.1f}%</td>
                <td>{row.get('value_score',0):.2f}</td>
                <td>{row.get('quality_score',0):.2f}</td>
                <td>{row.get('growth_score',0):.2f}</td>
                <td>{row.get('momentum_score',0):.2f}</td>
                <td>{row.get('volatility_score',0):.2f}</td>
                <td>{row.get('liquidity_score',0):.2f}</td>
                <td class="{cls}">{chg_60d:+.1f}%</td>
            </tr>\n'''

        tables_html += f'''
        <h2>🏆 {label} TOP 50</h2>
        <table>
        <tr><th>#</th><th>代码</th><th>名称</th><th>综合因子</th><th>权重</th>
            <th>价值</th><th>质量</th><th>成长</th><th>动量</th><th>波动</th><th>流动性</th><th>60日涨跌</th></tr>
        {rows}
        </table>
        '''

    # 持有期收益对比
    holding_html = '<h2>📈 持有期收益模拟</h2><table>'
    holding_html += '<tr><th>持有期</th>'
    for label in portfolios.keys():
        holding_html += f'<th>{label}组合收益</th><th>胜率</th>'
    if benchmark_ret:
        holding_html += '<th>中证500基准</th><th>超额收益</th>'
    holding_html += '</tr>\n'

    for hd_key in ['20d', '60d', '120d']:
        hd_label = {'20d': '1个月', '60d': '3个月', '120d': '6个月'}.get(hd_key, hd_key)
        holding_html += f'<tr><td>{hd_label} ({hd_key})</td>'
        best_excess = None
        for label in portfolios.keys():
            r = holding_results.get(label, {}).get(hd_key, {})
            tr = r.get('total_return', 0) * 100
            wr = r.get('win_rate', 0)
            cls = 'positive' if tr > 0 else 'negative'
            holding_html += f'<td class="{cls}">{tr:+.2f}%</td><td>{wr:.0f}%</td>'
            if best_excess is None or tr > (best_excess or -999):
                best_excess = tr
        if benchmark_ret and hd_key in benchmark_ret:
            br = benchmark_ret[hd_key] * 100
            cls_b = 'positive' if br > 0 else 'negative'
            ex = (best_excess or 0) - br
            cls_ex = 'positive' if ex > 0 else 'negative'
            holding_html += f'<td class="{cls_b}">{br:+.2f}%</td><td class="{cls_ex}">{ex:+.2f}%</td>'
        holding_html += '</tr>\n'
    holding_html += '</table>'

    # IC分析
    ic_html = ''
    if ic_results:
        ic_html = '<h2>📊 因子IC分析（信息系数）</h2><table>'
        ic_html += '<tr><th>因子</th><th>IC值</th><th>评价</th></tr>\n'
        for factor, ic in ic_results.items():
            if ic > 0.05:
                eval_str = '✅ 有效'
                cls = 'positive'
            elif ic > 0.02:
                eval_str = '⚠️ 弱有效'
                cls = ''
            elif ic > -0.02:
                eval_str = '➖ 无效'
                cls = ''
            elif ic > -0.05:
                eval_str = '⚠️ 弱反向'
                cls = ''
            else:
                eval_str = '❌ 反向'
                cls = 'negative'
            ic_html += f'<tr><td>{factor}</td><td class="{cls}">{ic:.4f}</td><td>{eval_str}</td></tr>\n'
        ic_html += '</table>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Alpha因子增强策略 A股版 - 回测报告</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 1200px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
h2 {{ color: #34495e; margin-top: 30px; }}
table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: center; }}
th {{ background: #3498db; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
tr:hover {{ background: #e8f4f8; }}
.positive {{ color: #27ae60; font-weight: bold; }}
.negative {{ color: #e74c3c; font-weight: bold; }}
.info {{ background: #d5f5e3; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #27ae60; }}
.warning {{ background: #fdebd0; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #f39c12; }}
</style>
</head>
<body>
<div class="container">
<h1>📋 Alpha因子增强策略 A股版 - 回测报告</h1>
<div class="info">
<strong>报告时间:</strong> {now}<br>
<strong>数据源:</strong> westock-data 实时行情 + K线<br>
<strong>股票池:</strong> 中证500成分股<br>
<strong>选股数量:</strong> TOP 50<br>
<strong>回测方式:</strong> 当前截面因子选股 + 历史K线模拟持仓
</div>
{tables_html}
{holding_html}
{ic_html}
</div>
</body>
</html>"""

    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


def send_email(html_path):
    """发送邮件"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'【策略回测报告】{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} Alpha因子增强策略A股版'
        msg['From'] = '848786642@qq.com'
        msg['To'] = '848786642@qq.com'
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        with smtplib.SMTP_SSL('smtp.qq.com', 465) as server:
            server.login('848786642@qq.com', 'ljbtvacrctjobfed')
            server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())

        print(f"\n📧 邮件报告已发送至 848786642@qq.com")
    except Exception as e:
        print(f"\n⚠️ 邮件发送失败: {e}")


# ================================================================
# 主函数
# ================================================================
def main():
    print("=" * 70)
    print("  Alpha因子增强策略 v1.5 A股版 (westock-data完整回测)")
    print("=" * 70)

    # Step 1: 获取中证500成分股
    print(f"\n📥 Step 1: 获取中证500成分股...")
    stocks = get_zz500_stocks()
    print(f"  ✅ {len(stocks)} 只成分股")

    # Step 2: 批量获取实时行情
    print(f"\n📥 Step 2: 批量获取实时行情因子数据...")
    quote_df = batch_quote(stocks, batch_size=20)
    print(f"  ✅ {len(quote_df)} 只股票行情数据")

    # Step 3: 计算因子
    print(f"\n📊 Step 3: 计算6大因子得分...")
    factor_df = calc_factors_from_quote(quote_df)
    for col in ['value_score', 'quality_score', 'growth_score', 'momentum_score', 'volatility_score', 'liquidity_score']:
        if col in factor_df.columns:
            s = factor_df[col]
            print(f"  {col}: mean={s.mean():.3f}, std={s.std():.3f}, valid={s.notna().sum()}/{len(s)}")

    # Step 4: 两套权重选股
    portfolios = {}
    for label, weights in [('原始权重', g.FACTOR_WEIGHTS_ORIGINAL), ('A股IC优化权重', g.FACTOR_WEIGHTS)]:
        print(f"\n{'='*50}")
        print(f"📊 {label}选股")
        df = factor_df.copy()
        df = combine_factors(df, weights)
        portfolio = select_portfolio(df, max_stocks=g.MAX_STOCK_NUM, max_single_weight=g.MAX_SINGLE_WEIGHT)
        portfolios[label] = portfolio

        # 打印TOP10
        print(f"\n  TOP 10:")
        for i, (_, row) in enumerate(portfolio.head(10).iterrows()):
            name = str(row.get('name', ''))[:8]
            chg = row.get('chg_60d', 0) or 0
            print(f"  {i+1}. {row['code']} {name:<8} CF={row['combined_factor']:.3f} W={row['weight']*100:.1f}% 60D={chg:+.1f}%")

    # Step 5: 获取K线数据
    print(f"\n📥 Step 5: 获取TOP50股票K线数据...")
    # 合并两套权重的选股代码
    all_selected_codes = set()
    for label, portfolio in portfolios.items():
        all_selected_codes.update(portfolio['code'].tolist())

    # 也需要获取一些非选股的K线用于IC计算（随机抽样100只）
    other_codes = factor_df[~factor_df['code'].isin(all_selected_codes)]['code'].tolist()[:100]
    all_kline_codes = list(all_selected_codes) + other_codes

    kline_data = batch_kline(all_kline_codes, limit=150, delay=0.5)
    print(f"  ✅ 获取{len(kline_data)}只股票K线数据")

    # Step 6: 模拟持有期收益
    print(f"\n📈 Step 6: 模拟持有期收益...")
    holding_results = {}
    for label, portfolio in portfolios.items():
        h = simulate_holding(portfolio, kline_data, holding_days_list=[20, 60, 120])
        holding_results[label] = h
        print(f"\n  {label}:")
        for hd, r in h.items():
            print(f"    {hd}: 总收益={r['total_return']*100:+.2f}%, 胜率={r['win_rate']:.0f}%, 均值={r['avg_ret']*100:+.2f}%, 覆盖={r['n_stocks']}只")

    # Step 7: 中证500基准
    print(f"\n📈 Step 7: 获取中证500基准K线...")
    time.sleep(2)  # 避免频率限制
    zz500_output = westock_cmd('kline', 'sh000905', '--limit', '150', delay=1.5)
    zz500_df = parse_markdown_table(zz500_output)
    benchmark_ret = {}
    if len(zz500_df) > 0 and 'last' in zz500_df.columns:
        try:
            prices = zz500_df['last'].astype(float).values
            prices = prices[::-1]  # 升序
            for hd in [20, 60, 120]:
                if len(prices) > hd:
                    ret = (prices[-1] - prices[-hd-1]) / prices[-hd-1]
                    benchmark_ret[f'{hd}d'] = ret
                    print(f"  中证500 {hd}天收益: {ret*100:+.2f}%")
        except Exception as e:
            print(f"  ⚠️ 基准计算失败: {e}")

    # Step 8: IC分析
    print(f"\n📊 Step 8: 因子IC分析...")
    ic_results = {}
    for label, weights in [('A股IC优化权重', g.FACTOR_WEIGHTS)]:
        df = factor_df.copy()
        df = combine_factors(df, weights)
        ic = calc_ic(df, kline_data, forward_days=20)
        ic_results[label] = ic
        print(f"  {label} IC (20天前瞻):")
        for factor, val in ic.items():
            status = '✅' if val > 0.05 else '⚠️' if val > 0.02 else '➖' if val > -0.02 else '❌'
            print(f"    {factor}: {val:.4f} {status}")

    # Step 9: 输出总结
    print(f"\n{'='*70}")
    print(f"  📋 Alpha因子增强策略 A股版 - 回测报告总结")
    print(f"{'='*70}")
    print(f"  日期: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  有效因子股票: {len(factor_df)} 只")

    for label, portfolio in portfolios.items():
        h = holding_results.get(label, {})
        print(f"\n  📊 {label}:")
        for hd in ['20d', '60d', '120d']:
            r = h.get(hd, {})
            tr = r.get('total_return', 0) * 100
            wr = r.get('win_rate', 0)
            ex = 0
            if hd in benchmark_ret:
                ex = tr - benchmark_ret[hd] * 100
            print(f"    {hd}: 收益={tr:+.2f}% 胜率={wr:.0f}% 超额={ex:+.2f}%")

    # Step 10: 生成报告
    html_path = '/data/workspace/alpha_factor_a_stock_report.html'
    # 使用A股IC优化权重的IC结果
    main_ic = ic_results.get('A股IC优化权重', {})
    generate_report(portfolios, holding_results, main_ic, benchmark_ret, html_path)
    print(f"\n📁 HTML报告: {html_path}")

    # 保存选股CSV
    for label, portfolio in portfolios.items():
        csv_path = f'/data/workspace/alpha_factor_stock_selection_{label}.csv'
        portfolio.to_csv(csv_path, index=False, encoding='utf-8-sig')

    # 保存JSON报告
    report_data = {
        '日期': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        '有效因子股票数': len(factor_df),
        'K线数据股票数': len(kline_data),
        '持有期收益': {},
        '因子IC': main_ic,
        '基准收益': {k: round(v*100, 2) for k, v in benchmark_ret.items()},
    }
    for label, h in holding_results.items():
        report_data['持有期收益'][label] = {
            hd: {k: round(v*100, 2) if isinstance(v, float) and abs(v) < 10 else round(v, 2)
                 for k, v in r.items()}
            for hd, r in h.items()
        }

    with open('/data/workspace/alpha_factor_a_stock_report.json', 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)

    # 发送邮件
    send_email(html_path)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n❌ 运行失败: {e}")
        traceback.print_exc()
        sys.exit(1)
