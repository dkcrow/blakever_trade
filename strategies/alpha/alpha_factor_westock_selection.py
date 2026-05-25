#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alpha因子增强策略 v1.5 A股版 - westock-data实时因子版
数据源: westock-data (实时行情+估值) + AKShare (指数日线)
特点: 使用当前截面因子数据选股, 用指数+个股K线模拟持仓收益

策略逻辑:
1. 从westock-data获取中证500成分股的实时因子截面(PE/PB/PS/PCF/市值/换手率/涨跌幅)
2. 计算6大因子得分, 合成综合评分, 选出TOP50
3. 用K线数据回测近1个月持仓收益
4. 对比中证500买入持有基准
"""

import os, sys, json, time, warnings, datetime, subprocess
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

WESTOCK_SCRIPT = '/data/workspace/.agent/skills/westock-data/scripts/index.js'


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


def westock_cmd(*args):
    """运行westock-data命令"""
    try:
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT] + list(args),
            capture_output=True, text=True, timeout=60
        )
        return result.stdout
    except Exception as e:
        return f"Error: {e}"


def parse_markdown_table(text):
    """解析Markdown表格为DataFrame"""
    lines = text.strip().split('\n')
    # 找到表格行
    table_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith('|') and not line.startswith('| ---') and not line.startswith('|---'):
            table_lines.append(line)

    if len(table_lines) < 2:
        return pd.DataFrame()

    # 解析表头
    headers = [h.strip() for h in table_lines[0].split('|') if h.strip()]
    rows = []
    for line in table_lines[2:]:  # 跳过分隔线
        cells = [c.strip() for c in line.split('|') if c.strip() != '']
        if len(cells) >= len(headers):
            rows.append(cells[:len(headers)])

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=headers)
    return df


def get_zz500_stocks_akshare():
    """使用AKShare获取中证500成分股"""
    import akshare as ak
    try:
        df = ak.index_stock_cons_weight_csindex(symbol='000905')
        # 列名可能变化，动态匹配
        code_col = [c for c in df.columns if '代码' in c and '成分' in c]
        name_col = [c for c in df.columns if '名称' in c and '成分' in c and '英文' not in c]
        weight_col = [c for c in df.columns if '权重' in c]
        
        if not code_col or not name_col:
            print(f"  ⚠️ 列名不匹配: {df.columns.tolist()}")
            return pd.DataFrame()
        
        code_col = code_col[0]
        name_col = name_col[0]
        
        stocks = df[[code_col, name_col]].copy()
        stocks.columns = ['code', 'name']
        # 转换代码格式
        stocks['westock_code'] = stocks['code'].astype(str).apply(
            lambda x: f"sh{x}" if x.startswith('6') else f"sz{x}" if x.startswith('0') or x.startswith('3') else f"bj{x}"
        )
        return stocks
    except Exception as e:
        print(f"  ⚠️ AKShare获取成分股失败: {e}")
        return pd.DataFrame()


def get_zz500_stocks_westock():
    """使用westock-data的rank功能获取股票列表"""
    # 通过估值排行获取大量A股
    output = westock_cmd('rank', 'fin_valuation', '--desc', 'true')
    # 解析并过滤
    return output


def batch_quote(stocks, batch_size=20):
    """批量获取实时行情"""
    all_data = []
    codes = stocks['westock_code'].tolist()

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        batch_str = ','.join(batch)
        output = westock_cmd('quote', batch_str)
        df = parse_markdown_table(output)
        if len(df) > 0:
            all_data.append(df)
        time.sleep(0.3)  # 避免请求过快

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()


def batch_kline(stocks, period='day', limit=120, batch_size=5):
    """批量获取K线数据"""
    all_data = {}
    codes = stocks['westock_code'].tolist()

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        batch_str = ','.join(batch)
        output = westock_cmd('kline', batch_str, '--period', period, '--limit', str(limit), '--fq', 'qfq')
        # K线批量返回需要按股票分割
        # 简化处理：逐只获取
        for code in batch:
            output = westock_cmd('kline', code, '--period', period, '--limit', str(limit), '--fq', 'qfq')
            df = parse_markdown_table(output)
            if len(df) > 0:
                all_data[code] = df
            time.sleep(0.1)

    return all_data


def calc_factors_from_quote(quote_df):
    """从实时行情计算因子得分"""
    results = []

    for _, row in quote_df.iterrows():
        try:
            code = row.get('code', '')
            if not code:
                continue

            # 价值因子
            pe = _safe_float(row.get('pe_ratio') or row.get('pe_lyr'))
            pb = _safe_float(row.get('pb_ratio'))
            ps = _safe_float(row.get('ps_ttm'))
            pcf = _safe_float(row.get('pcf_ttm'))
            dividend = _safe_float(row.get('dividend_ratio_ttm'))

            pe_inv = 1.0 / pe if pe and pe > 0 else (0.01 if pe and pe < 0 else None)
            pb_inv = 1.0 / pb if pb and pb > 0 else (0.01 if pb and pb < 0 else None)
            ps_inv = 1.0 / ps if ps and ps > 0 else (0.01 if ps and ps < 0 else None)
            pcf_inv = 1.0 / pcf if pcf and pcf > 0 else (0.01 if pcf and pcf < 0 else None)

            # 质量因子（用股息率作为质量的代理）
            quality_dividend = dividend if dividend and dividend > 0 else None

            # 成长因子（用涨跌幅作为成长的代理）
            chg_60d = _safe_float(row.get('chg_60d'))
            chg_ytd = _safe_float(row.get('chg_ytd'))

            # 动量因子
            chg_5d = _safe_float(row.get('chg_5d'))
            chg_10d = _safe_float(row.get('chg_10d'))
            chg_20d = _safe_float(row.get('chg_20d'))

            # 流动性因子
            turnover = _safe_float(row.get('turnover_rate'))
            market_cap = _safe_float(row.get('total_market_cap'))
            volume_ratio = _safe_float(row.get('volume_ratio'))

            results.append({
                'code': code,
                'name': row.get('name', ''),
                'price': _safe_float(row.get('price')),
                # 原始因子
                'pe_inv': pe_inv,
                'pb_inv': pb_inv,
                'ps_inv': ps_inv,
                'pcf_inv': pcf_inv,
                'dividend': quality_dividend,
                'chg_5d': chg_5d,
                'chg_10d': chg_10d,
                'chg_20d': chg_20d,
                'chg_60d': chg_60d,
                'chg_ytd': chg_ytd,
                'turnover': turnover,
                'market_cap': market_cap,
                'volume_ratio': volume_ratio,
            })
        except Exception as e:
            continue

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    # ─── 计算因子得分 ───
    # 1. 价值因子
    pe_rank = df['pe_inv'].rank(pct=True) if df['pe_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    pb_rank = df['pb_inv'].rank(pct=True) if df['pb_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    ps_rank = df['ps_inv'].rank(pct=True) if df['ps_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    pcf_rank = df['pcf_inv'].rank(pct=True) if df['pcf_inv'].notna().sum() > 5 else pd.Series(0.5, index=df.index)
    df['value_score'] = (
        pe_rank.fillna(0.5) * 0.30 +
        pb_rank.fillna(0.5) * 0.30 +
        ps_rank.fillna(0.5) * 0.20 +
        pcf_rank.fillna(0.5) * 0.20
    )

    # 2. 质量因子（股息率）
    if df['dividend'].notna().sum() > 5:
        df['quality_score'] = df['dividend'].rank(pct=True).fillna(0.5)
    else:
        df['quality_score'] = 0.5

    # 3. 成长因子（用价格涨幅代理，A股反向 - 低成长更优）
    if df['chg_ytd'].notna().sum() > 5 and df['chg_ytd'].std() > 0.001:
        df['growth_score'] = 1 - df['chg_ytd'].rank(pct=True).fillna(0.5)
    elif df['chg_60d'].notna().sum() > 5 and df['chg_60d'].std() > 0.001:
        df['growth_score'] = 1 - df['chg_60d'].rank(pct=True).fillna(0.5)
    else:
        df['growth_score'] = 0.5

    # 4. 动量因子（中期动量 + 短期反转）
    if df['chg_60d'].notna().sum() > 5 and df['chg_20d'].notna().sum() > 5:
        mom_60 = df['chg_60d'].rank(pct=True).fillna(0.5)
        rev_5 = 1 - df['chg_5d'].rank(pct=True).fillna(0.5)  # 短期反转
        rev_10 = 1 - df['chg_10d'].rank(pct=True).fillna(0.5)
        df['momentum_score'] = mom_60 * 0.5 + rev_5 * 0.25 + rev_10 * 0.25
    elif df['chg_20d'].notna().sum() > 5:
        df['momentum_score'] = 1 - df['chg_20d'].rank(pct=True).fillna(0.5)  # 反转
    else:
        df['momentum_score'] = 0.5

    # 5. 波动因子（用range_pct作为波动率代理）
    range_pct = _safe_float(row.get('range_pct')) if 'range_pct' in row else None
    # 没有直接波动率，用涨跌幅波动代理
    if df['chg_5d'].notna().sum() > 5 and df['chg_20d'].notna().sum() > 5:
        # 高涨跌幅意味着高波动 -> 低波动得分高
        chg_abs = df[['chg_5d', 'chg_10d', 'chg_20d', 'chg_60d']].abs().mean(axis=1)
        df['volatility_score'] = 1 - chg_abs.rank(pct=True).fillna(0.5)
    else:
        df['volatility_score'] = 0.5

    # 6. 流动性因子
    turnover_rank = df['turnover'].rank(pct=True) if df['turnover'].notna().sum() > 5 else None
    cap_rank = df['market_cap'].rank(pct=True) if df['market_cap'].notna().sum() > 5 else None

    score = pd.Series(0.5, index=df.index)
    if turnover_rank is not None:
        t_score = 1 - (turnover_rank - 0.6).abs() * 1.5
        t_score = t_score.clip(0.2, 1.0).fillna(0.5)
        score = score * 0.4 + t_score * 0.4
    if cap_rank is not None:
        score = score + cap_rank.fillna(0.5) * 0.3
    if turnover_rank is not None and cap_rank is not None:
        score = score - 0.15
    df['liquidity_score'] = score

    return df


def combine_factors(df, factor_weights):
    """合成因子"""
    factor_cols = ['value_score', 'quality_score', 'growth_score',
                   'momentum_score', 'volatility_score', 'liquidity_score']

    # 标准化
    for col in factor_cols:
        if col in df.columns:
            std = df[col].std()
            if std > 0 and not pd.isna(std):
                df[col] = (df[col] - df[col].mean()) / std
            else:
                df[col] = 0

    # 加权合成
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

    n = len(selected)
    scores = selected['combined_factor'].values
    score_min = scores.min()
    score_max = scores.max()

    if score_max > score_min:
        normalized = (scores - score_min) / (score_max - score_min)
        raw_weights = np.exp(normalized * 2)
    else:
        raw_weights = np.ones(n)

    raw_weights = np.minimum(raw_weights, max_single_weight * raw_weights.sum())
    raw_weights = raw_weights / raw_weights.sum()
    selected['weight'] = raw_weights

    return selected


def simulate_monthly_return(portfolio, kline_data):
    """使用K线数据模拟1个月持仓收益"""
    # 获取每只股票最近30天K线
    stock_returns = {}
    for _, row in portfolio.iterrows():
        code = row['code']
        weight = row['weight']

        if code in kline_data and len(kline_data[code]) > 0:
            df = kline_data[code]
            prices = df['last'].values if 'last' in df.columns else df['close'].values if 'close' in df.columns else None
            if prices is not None and len(prices) >= 2:
                try:
                    prices = [float(p) for p in prices if p is not None]
                    if len(prices) >= 2:
                        ret = (prices[0] - prices[-1]) / prices[-1]  # 最新价 vs 30天前
                        stock_returns[code] = ret * weight
                except:
                    pass

    if stock_returns:
        total_return = sum(stock_returns.values())
        return total_return, stock_returns
    return 0, {}


def main():
    print("=" * 70)
    print("  Alpha因子增强策略 v1.5 A股版 (westock-data实时因子版)")
    print("  数据源: westock-data (实时行情+估值) + AKShare (指数日线)")
    print("=" * 70)

    # Step 1: 获取中证500成分股
    print(f"\n📥 Step 1: 获取中证500成分股...")
    stocks = get_zz500_stocks_akshare()
    if len(stocks) == 0:
        print("  ❌ 获取成分股失败!")
        return
    print(f"  ✅ 获取{len(stocks)}只成分股")

    # Step 2: 批量获取实时行情（含因子数据）
    print(f"\n📥 Step 2: 批量获取实时行情因子数据...")
    quote_df = batch_quote(stocks, batch_size=20)
    if len(quote_df) == 0:
        print("  ❌ 获取行情数据失败!")
        return
    print(f"  ✅ 获取{len(quote_df)}只股票行情数据")

    # Step 3: 计算因子得分
    print(f"\n📊 Step 3: 计算6大因子得分...")
    factor_df = calc_factors_from_quote(quote_df)
    if len(factor_df) == 0:
        print("  ❌ 因子计算失败!")
        return

    # 因子诊断
    for col in ['value_score', 'quality_score', 'growth_score', 'momentum_score', 'volatility_score', 'liquidity_score']:
        if col in factor_df.columns:
            s = factor_df[col]
            print(f"  {col}: mean={s.mean():.3f}, std={s.std():.3f}, valid={s.notna().sum()}/{len(s)}")

    # Step 4: 两套权重选股
    results = {}
    for label, weights in [('原始权重', g.FACTOR_WEIGHTS_ORIGINAL), ('A股IC优化权重', g.FACTOR_WEIGHTS)]:
        print(f"\n{'='*50}")
        print(f"📊 {label}选股: {weights}")

        df = factor_df.copy()
        df = combine_factors(df, weights)

        portfolio = select_portfolio(df, max_stocks=g.MAX_STOCK_NUM, max_single_weight=g.MAX_SINGLE_WEIGHT)
        if len(portfolio) == 0:
            print(f"  ❌ 选股失败!")
            continue

        print(f"\n  🏆 TOP 20 选股结果:")
        print(f"  {'排名':<4} {'代码':<12} {'名称':<10} {'综合因子':>8} {'权重':>6} {'PE':>8} {'PB':>6} {'换手率':>6} {'60日涨跌':>8}")
        print(f"  {'-'*80}")
        for i, (_, row) in enumerate(portfolio.head(20).iterrows()):
            name = str(row.get('name', ''))[:8]
            print(f"  {i+1:<4} {row['code']:<12} {name:<10} {row['combined_factor']:>8.3f} {row['weight']*100:>5.1f}% "
                  f"{row.get('pe_inv', 0):>8.3f} {row.get('pb_inv', 0):>6.3f} "
                  f"{row.get('turnover', 0):>6.2f} {row.get('chg_60d', 0):>+7.1f}%")

        results[label] = portfolio

    # Step 5: 获取K线数据验证
    print(f"\n📥 Step 5: 获取K线数据验证收益...")
    # 对A股IC优化权重的组合获取K线
    if 'A股IC优化权重' in results:
        portfolio = results['A股IC优化权重']
        kline_data = {}
        codes = portfolio['code'].tolist()
        for i, code in enumerate(codes[:30]):  # 只获取前30只
            output = westock_cmd('kline', code, '--period', 'day', '--limit', '30', '--fq', 'qfq')
            df = parse_markdown_table(output)
            if len(df) > 0:
                kline_data[code] = df
            time.sleep(0.1)
            if (i + 1) % 10 == 0:
                print(f"    K线进度: {i+1}/30")

        monthly_ret, stock_rets = simulate_monthly_return(portfolio, kline_data)
        print(f"\n  📈 A股IC优化组合近30天模拟收益: {monthly_ret*100:+.2f}%")

    # Step 6: 获取中证500基准
    print(f"\n📥 Step 6: 获取中证500基准...")
    zz500_kline = westock_cmd('kline', 'sh000905', '--period', 'day', '--limit', '30')
    zz500_df = parse_markdown_table(zz500_kline)
    if len(zz500_df) > 0:
        prices = zz500_df['last'].values if 'last' in zz500_df.columns else zz500_df['close'].values
        try:
            prices = [float(p) for p in prices if p is not None]
            if len(prices) >= 2:
                zz500_ret = (prices[0] - prices[-1]) / prices[-1]
                print(f"  📈 中证500近30天收益: {zz500_ret*100:+.2f}%")

                if 'A股IC优化权重' in results:
                    excess = monthly_ret - zz500_ret
                    print(f"  📈 超额收益: {excess*100:+.2f}%")
        except:
            pass

    # Step 7: 生成报告
    print(f"\n{'='*70}")
    print(f"  📋 Alpha因子增强策略 A股版 - 实时因子选股报告")
    print(f"{'='*70}")
    print(f"  日期: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  数据源: westock-data实时行情")

    # 保存选股结果
    for label, portfolio in results.items():
        output_path = f'/data/workspace/alpha_factor_stock_selection_{label}.csv'
        portfolio.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"  📁 {label}选股结果: {output_path}")

    # 生成HTML报告
    html_path = '/data/workspace/alpha_factor_a_stock_report.html'
    _gen_report(results, html_path)

    # 发送邮件
    _send_email_report(html_path)


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        f = float(str(v).replace(',', ''))
        if np.isinf(f) or np.isnan(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _gen_report(results, path):
    """生成HTML报告"""
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # 构建选股表格
    tables_html = ''
    for label, portfolio in results.items():
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
        <h2>🏆 {label} TOP 50 选股结果</h2>
        <table>
        <tr><th>#</th><th>代码</th><th>名称</th><th>综合因子</th><th>权重</th>
            <th>价值</th><th>质量</th><th>成长</th><th>动量</th><th>波动</th><th>流动性</th><th>60日涨跌</th></tr>
        {rows}
        </table>
        '''

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Alpha因子增强策略 A股版 - 实时选股报告</title>
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
</style>
</head>
<body>
<div class="container">
<h1>📋 Alpha因子增强策略 A股版 - 实时因子选股报告</h1>
<div class="info">
<strong>报告时间:</strong> {now}<br>
<strong>数据源:</strong> westock-data 实时行情<br>
<strong>股票池:</strong> 中证500成分股<br>
<strong>选股数量:</strong> TOP 50
</div>
{tables_html}
</div>
</body>
</html>"""

    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"  📁 HTML报告: {path}")


def _send_email_report(html_path):
    """发送邮件报告"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'【策略选股报告】{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} Alpha因子增强策略A股版'
        msg['From'] = '848786642@qq.com'
        msg['To'] = '848786642@qq.com'
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        with smtplib.SMTP_SSL('smtp.qq.com', 465) as server:
            server.login('848786642@qq.com', 'ljbtvacrctjobfed')
            server.sendmail('848786642@qq.com', '848786642@qq.com', msg.as_string())

        print(f"\n📧 邮件报告已发送至 848786642@qq.com")
    except Exception as e:
        print(f"\n⚠️ 邮件发送失败: {e}")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n❌ 运行失败: {e}")
        traceback.print_exc()
        sys.exit(1)
