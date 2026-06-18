#!/usr/bin/env python3
"""七星美股版 前高回撤过滤回测对比
对比: 无过滤 vs 从前高累计下跌 10%/15%/20% 过滤
规则: 动量排名中，从前高累计跌幅超阈值的股票被过滤，直到跌幅回到阈值以内才解除
"""
import sys, os, math, json, warnings
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUTPUT_DIR = PROJECT_ROOT / 'backtest' / 'results_us100'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = datetime.now()
NOW_TAG = NOW.strftime('%Y%m%d_%H%M')
START_DATE = '2023-01-01'
END_DATE = NOW.strftime('%Y-%m-%d')

POOL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')
HN = 7
HISTORICAL_WINDOW = 500  # 向前看500天找峰值

# ============================
# 数据加载
# ============================
print(f'加载 {len(POOL)} 只美股数据...')
all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        pre_start = pd.Timestamp(START_DATE) - pd.Timedelta(days=HISTORICAL_WINDOW)
        mask = (df.index >= pre_start) & (df.index <= END_DATE)
        df = df[mask]
        if len(df[df.index >= START_DATE]) >= 25: all_data[sym] = df
    except: pass

trade_dates = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]
print(f'有效: {len(all_data)}只 | 交易日: {len(trade_dates)}天')

# ============================
# 评分函数
# ============================
def calc_score(close_full, lookback=25):
    recent = close_full[-(lookback+1):]
    y = np.log(np.maximum(recent, 1e-10))
    x = np.arange(len(y)); w = np.linspace(1, 2, len(y))
    slope, intercept = np.polyfit(x, y, 1, w=w)
    ann = math.exp(slope * 250) - 1
    ssr = np.sum(w * (y - (slope*x + intercept))**2)
    sst = np.sum(w * (y - np.mean(y))**2)
    r2 = 1 - ssr/sst if sst>0 else 0
    return ann * r2

# ============================
# 组合类
# ============================
class USPortfolio:
    def __init__(self, cash=100000, comm=0.005):
        self.initial_cash = cash; self.cash = cash; self.comm = comm
        self.positions = {}; self.trade_log = []; self.daily_values = []
    @property
    def total_value(self):
        pv = sum(p['shares']*p.get('last_price',p['cost_price']) for p in self.positions.values())
        return self.cash + pv
    def update_prices(self, pdict):
        for c,p in pdict.items():
            if c in self.positions: self.positions[c]['last_price'] = p
    def buy(self, code, shares, price, date, reason=''):
        tv = shares*price; comm = shares*self.comm; total = tv+comm
        if total > self.cash+0.01: return False
        self.cash -= total
        if code in self.positions:
            o = self.positions[code]; ts = o['shares']+shares
            self.positions[code] = {'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*price)/ts,'last_price':price,'buy_date':o.get('buy_date',date)}
        else:
            self.positions[code] = {'shares':shares,'cost_price':price,'last_price':price,'buy_date':date}
        self.trade_log.append({'date':str(date)[:10],'code':code,'action':'BUY','price':round(price,4),'shares':int(shares),'amount':round(tv,2),'commission':round(comm,2),'reason':reason})
        return True
    def sell(self, code, shares, price, date, reason=''):
        if code not in self.positions: return False
        pos = self.positions[code]; actual = min(shares, pos['shares'])
        if actual <= 0: return False
        tv = actual*price; comm = actual*self.comm; self.cash += tv-comm
        pos['shares'] -= actual
        pnl = (price-pos['cost_price'])/pos['cost_price'] if pos['cost_price']>0 else 0
        if pos['shares'] <= 0: del self.positions[code]
        self.trade_log.append({'date':str(date)[:10],'code':code,'action':'SELL','price':round(price,4),'shares':int(actual),'amount':round(tv,2),'commission':round(comm,2),'pnl_pct':round(pnl,4),'reason':reason})
        return True
    def sell_all(self, code, price, date, reason=''):
        if code not in self.positions: return False
        return self.sell(code, self.positions[code]['shares'], price, date, reason)
    def get_position_codes(self): return list(self.positions.keys())
    def record_daily_value(self, date):
        v = self.total_value
        self.daily_values.append({'date':str(date)[:10],'value':round(v,2),'returns':round((v-self.initial_cash)/self.initial_cash,6)})

# ============================
# 前高回撤过滤 辅助函数
# ============================
def precompute_rolling_peaks(all_data, trade_dates):
    """预计算每只股票在每个交易日的滚动前高"""
    peaks = {}  # peaks[code][date] = (peak_price, drawdown_from_peak_pct)
    for code, df in all_data.items():
        peaks[code] = {}
        running_peak_cl = 0
        running_peak_hi = 0
        for date_str in trade_dates:
            td = pd.Timestamp(date_str)
            mask = df.index <= td
            if not mask.any():
                peaks[code][date_str] = (0, 0)
                continue
            close = float(df.loc[mask, 'close'].iloc[-1])
            high = float(df.loc[mask, 'high'].max())
            # 滚动峰值取close和high的较大者
            if close > running_peak_cl:
                running_peak_cl = close
            if high > running_peak_hi:
                running_peak_hi = high
            peak = max(running_peak_cl, running_peak_hi)
            if peak > 0:
                dd = (close - peak) / peak * 100  # 负数=回撤
            else:
                dd = 0
            peaks[code][date_str] = (peak, round(dd, 2))
    return peaks

def get_filtered_codes(ranked, peaks, date_str, threshold):
    """根据前高回撤阈值过滤
    threshold: 负数，如 -10, -15, -20
    返回: (filtered_codes_dict, unfiltered_codes_list)
    """
    filtered = {}
    for r in ranked:
        code = r['code']
        if code in peaks and date_str in peaks[code]:
            _, dd = peaks[code][date_str]
            if dd <= threshold:  # dd是负数，如-12% <= -10% → 被过滤
                filtered[code] = f'前高回撤{dd:.1f}%(阈值{abs(threshold)}%)'
    return filtered

# ============================
# 回测(无过滤)
# ============================
def run_backtest_no_filter(peaks):
    pf = USPortfolio(cash=100000)
    for i, td in enumerate(trade_dates):
        tds = pd.Timestamp(td)
        prices = {}
        for code, df in all_data.items():
            m = df.index <= tds
            if m.any(): prices[code] = float(df.loc[m,'close'].iloc[-1])
        pf.update_prices(prices)
        ranked = _get_ranked(prices, td)
        if not ranked: pf.record_daily_value(td); continue
        targets = [r['code'] for r in ranked if r['score'] > -999][:HN]
        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code, prices[code], td, reason='调出(无目标)')
            pf.record_daily_value(td); continue
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                pf.sell_all(code, prices[code], td, reason='调出目标')
        tv = pf.total_value; each = tv / len(targets)
        for idx, code in enumerate(targets):
            if code not in prices: continue
            price = prices[code]; cv = 0
            if code in pf.positions:
                cv = pf.positions[code]['shares'] * pf.positions[code]['last_price']
            diff = each - cv
            if abs(diff) < each * 0.05 and cv > 0: continue
            if diff > 0:
                sh = int(diff / price)
                if sh > 0 and sh * price >= 500:
                    pf.buy(code, sh, price, td, reason=f'排名{idx+1}')
        pf.record_daily_value(td)
    return _compute_metrics(pf)

# ============================
# 回测(前高回撤过滤)
# ============================
def run_backtest_with_peak_filter(peaks, threshold):
    """threshold: 负数, 如 -10, -15, -20"""
    pf = USPortfolio(cash=100000)
    filter_log = []  # 记录每日过滤情况
    for i, td in enumerate(trade_dates):
        tds = pd.Timestamp(td)
        prices = {}
        for code, df in all_data.items():
            m = df.index <= tds
            if m.any(): prices[code] = float(df.loc[m,'close'].iloc[-1])
        pf.update_prices(prices)
        ranked = _get_ranked(prices, td)
        if not ranked: pf.record_daily_value(td); continue
        
        # 前高回撤过滤
        filtered = get_filtered_codes(ranked, peaks, td, threshold)
        for r in ranked:
            r['filtered'] = r['code'] in filtered
        
        targets = [r['code'] for r in ranked if r['score'] > -999 and not r.get('filtered', False)][:HN]
        
        if not targets:
            for code in list(pf.get_position_codes()):
                if code in prices: pf.sell_all(code, prices[code], td, reason='调出(无目标)')
            pf.record_daily_value(td); continue
        
        for code in list(pf.get_position_codes()):
            if code not in targets and code in prices:
                reason = '调出目标'
                if code in filtered:
                    reason = f'前高回撤过滤({filtered[code]})'
                pf.sell_all(code, prices[code], td, reason=reason)
        
        tv = pf.total_value; each = tv / len(targets)
        for idx, code in enumerate(targets):
            if code not in prices: continue
            price = prices[code]; cv = 0
            if code in pf.positions:
                cv = pf.positions[code]['shares'] * pf.positions[code]['last_price']
            diff = each - cv
            if abs(diff) < each * 0.05 and cv > 0: continue
            if diff > 0:
                sh = int(diff / price)
                if sh > 0 and sh * price >= 500:
                    pf.buy(code, sh, price, td, reason=f'排名{idx+1}')
        pf.record_daily_value(td)
        
        if filtered:
            filter_log.append({'date': td, 'count': len(filtered)})
    
    metrics = _compute_metrics(pf)
    metrics['filter_days'] = len(filter_log)
    metrics['avg_filtered_per_day'] = sum(f['count'] for f in filter_log) / len(filter_log) if filter_log else 0
    return metrics

def _get_ranked(prices, date):
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index <= pd.Timestamp(date); hist = df[mask]
        if len(hist) < 35: continue
        cp = prices[code]
        if cp <= 0: continue
        chg_pct = 0.0
        if len(hist) >= 2:
            prev_close = hist['close'].iloc[-2]
            if prev_close > 0:
                chg_pct = (cp - prev_close) / prev_close * 100
        score = calc_score(hist['close'].values, 25)
        ranked.append({'code':code,'score':score,'price':cp,'chg_pct':round(chg_pct,2)})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

def _compute_metrics(pf):
    dv = pf.daily_values
    vals = [d['value'] for d in dv] if dv else [100000]
    fv = vals[-1]; tr = (fv - 100000) / 100000
    peak, mdd = vals[0], 0
    for v in vals:
        if v > peak: peak = v
        dd = (peak-v)/peak if peak>0 else 0
        if dd>mdd: mdd=dd
    sh_val = 0
    if len(vals)>1:
        dr = np.diff(vals)/vals[:-1]
        sh_val = (np.mean(dr)/np.std(dr)*np.sqrt(252)) if np.std(dr)>0 else 0
    n_days = len(trade_dates); ann_ret = tr * 252 / n_days * 100
    cm = abs(tr*252/n_days)/mdd if mdd>0 else 0
    
    trades = pf.trade_log
    st = [t for t in trades if t['action']=='SELL' and 'pnl_pct' in t]
    wins = [t for t in st if t['pnl_pct']>0]; losses = [t for t in st if t['pnl_pct']<=0]
    wr = len(wins)/len(st)*100 if st else 0
    aw = sum(t['pnl_pct'] for t in wins)/len(wins)*100 if wins else 0
    al = sum(t['pnl_pct'] for t in losses)/len(losses)*100 if losses else 0
    
    # 统计过滤触发次数（卖出理由含"前高回撤"）
    filter_trades = [t for t in trades if '前高回撤' in t.get('reason','')]
    
    return {
        'total_return': tr*100,
        'annual_return': ann_ret,
        'max_drawdown': mdd*100,
        'sharpe': sh_val,
        'calmar': cm,
        'trades': len(trades),
        'win_rate': wr,
        'avg_win': aw,
        'avg_loss': al,
        'final_value': fv,
        'filter_trades': len(filter_trades),
    }

# ============================
# 预计算
# ============================
print('\n预计算滚动前高...')
peaks = precompute_rolling_peaks(all_data, trade_dates)
print(f'完成: {len(peaks)} 只股票的前高数据')

# 打印一些样本看分布
sample_dd = []
for code in list(peaks.keys())[:5]:
    for td in trade_dates[-5:]:
        p, dd = peaks[code].get(td, (0, 0))
        sample_dd.append(f'{code}@{td}: peak={p:.2f} dd={dd:.1f}%')
print('样本 (最近5天):', ' | '.join(sample_dd[:10]))

# ============================
# 运行对比
# ============================
print('\n' + '='*70)
print('  七星美股版 前高回撤过滤 回测对比')
print(f'  数据区间: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)}天)')
print(f'  参数: 持股{HN}只 | 25日动量 | 佣金$0.005/股')
print(f'  过滤规则: 从前高累计跌幅超阈值 → 过滤，回到阈值内 → 解除')
print('='*70)

print('\n[1/4] 无过滤 基准回测...')
no_filter = run_backtest_no_filter(peaks)
print(f'  基准: +{no_filter["total_return"]:.2f}% | 年化{no_filter["annual_return"]:.1f}% | 回撤{no_filter["max_drawdown"]:.1f}% | 夏普{no_filter["sharpe"]:.4f} | {no_filter["trades"]}次')

thresholds = [-10.0, -15.0, -20.0]
results = {}
for idx, thr in enumerate(thresholds):
    print(f'\n[{idx+2}/4] 前高回撤过滤 threshold={abs(thr):.0f}% ...')
    res = run_backtest_with_peak_filter(peaks, thr)
    results[thr] = res
    print(f'  过滤{abs(thr):.0f}%: +{res["total_return"]:.2f}% | 年化{res["annual_return"]:.1f}% | 回撤{res["max_drawdown"]:.1f}% | 夏普{res["sharpe"]:.4f} | {res["trades"]}次 | 过滤触发{res["filter_trades"]}次')

# ============================
# 生成对比HTML
# ============================
color = lambda v: '#28A745' if v > 0 else '#DC3545'
fmt_pct = lambda v: f'{v:+.2f}%'

best_ret = no_filter['total_return']
best_name = '无过滤'
for thr, r in results.items():
    if r['total_return'] > best_ret:
        best_ret = r['total_return']
        best_name = f'前高回撤{abs(thr):.0f}%'

rows_html = ''
for label, r in [('无过滤', no_filter)] + [(f'前高回撤{abs(t):.0f}%', results[t]) for t in thresholds]:
    bold = 'font-weight:bold;' if label == best_name else ''
    diff = r['total_return'] - no_filter['total_return']
    diff_str = f'{diff:+.2f}%'
    diff_c = '#28A745' if diff > 0 else ('#DC3545' if diff < 0 else '#888')
    rows_html += f"""<tr style="{bold}">
        <td style="padding:6px 10px;{bold}">{label}</td>
        <td style="padding:6px 10px;text-align:right;color:{color(r['total_return'])};{bold}">{fmt_pct(r['total_return'])}</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{r['annual_return']:.1f}%</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{r['max_drawdown']:.1f}%</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{r['sharpe']:.4f}</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{r['calmar']:.2f}</td>
        <td style="padding:6px 10px;text-align:center;{bold}">{r['trades']}</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{r['win_rate']:.1f}%</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{fmt_pct(r['avg_win'])}</td>
        <td style="padding:6px 10px;text-align:right;{bold}">{fmt_pct(r['avg_loss'])}</td>
        <td style="padding:6px 10px;text-align:center;{bold}">{r.get('filter_trades','-')}</td>
        <td style="padding:6px 10px;text-align:right;font-weight:bold;color:{diff_c};">{diff_str}</td>
    </tr>"""

html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>七星美股版 前高回撤过滤回测对比</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:1200px;margin:0 auto;padding:20px;background:#f8f9fa;}}
h1{{font-size:20px;color:#1F4E79;text-align:center;margin:0 0 5px;}}
.subtitle{{text-align:center;font-size:12px;color:#888;margin-bottom:15px;}}
.card{{background:#fff;padding:15px 20px;border-radius:8px;margin-bottom:15px;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#1F4E79;color:#fff;padding:8px;text-align:center;}}
td{{padding:6px 8px;border-bottom:1px solid #eee;}}
tr:nth-child(even) td{{background:#f8f9fa;}}
.footer{{text-align:center;font-size:10px;color:#aaa;margin-top:20px;padding-top:15px;border-top:1px solid #eee;}}
.note{{background:#FFF3CD;padding:10px 15px;border-radius:6px;margin:10px 0;font-size:12px;color:#856404;}}
.good{{background:#E8F5E9;}}
.bad{{background:#FFEBEE;}}
</style></head><body>
<h1>七星美股版 前高回撤过滤 · 回测对比</h1>
<div class="subtitle">回测区间: {trade_dates[0]} ~ {trade_dates[-1]} | {len(trade_dates)}天 | 数据截止: {NOW_TAG}</div>
<div class="note">
    <b>过滤规则:</b> 动量排名中，从历史前高累计跌幅超过阈值的股票被过滤（不可买入 + 已持仓强制卖出换仓）。<br>
    被过滤后，需跌幅回到阈值以内才能解除过滤重新参与排名。<br>
    <b>前高:</b> 取当日之前所有交易日的 close 和 high 最大值作为滚动峰值。
</div>

<div class="card"><h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">核心指标对比 — 最优: <span style="color:#28A745;">{best_name}</span></h3>
<div style="overflow-x:auto;"><table>
<tr><th>策略</th><th>累计收益</th><th>年化收益</th><th>最大回撤</th><th>夏普</th><th>Calmar</th><th>交易次数</th><th>胜率</th><th>均盈</th><th>均亏</th><th>过滤触发</th><th>vs基准</th></tr>
{rows_html}
</table></div></div>

<div class="footer">七星美股版 · Blakever Trade · {NOW.strftime('%Y-%m-%d %H:%M')}<br>本报告仅供研究参考，不构成投资建议。</div>
</body></html>"""

html_path = OUTPUT_DIR / f'七星美股版_前高回撤过滤对比_{NOW_TAG}.html'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

# 打印摘要
print(f'\n{"="*70}')
print(f'  对比摘要')
print(f'{"="*70}')
print(f'  {"策略":<10} {"累计收益":>10} {"年化":>8} {"回撤":>8} {"夏普":>8} {"交易":>6} {"过滤":>6} {"vs基准":>10}')
print(f'  {"-"*70}')
print(f'  {"无过滤":<10} {fmt_pct(no_filter["total_return"]):>10} {no_filter["annual_return"]:.1f}% {"":>4} {no_filter["max_drawdown"]:.1f}% {"":>4} {no_filter["sharpe"]:.4f} {"":>2} {no_filter["trades"]:>6} {"-":>6}')
for thr in thresholds:
    r = results[thr]
    diff = r['total_return'] - no_filter['total_return']
    print(f'  {f"回撤{abs(thr):.0f}%":<10} {fmt_pct(r["total_return"]):>10} {r["annual_return"]:.1f}% {"":>4} {r["max_drawdown"]:.1f}% {"":>4} {r["sharpe"]:.4f} {"":>2} {r["trades"]:>6} {r["filter_trades"]:>6} {diff:+.2f}% {"":>4}')

print(f'\n报告: {html_path}')
print('完成!')
