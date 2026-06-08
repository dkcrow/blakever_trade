#!/usr/bin/env python3
"""七星美股版(最优) x7 实盘报告生成 (2025-01-01至今)"""
import sys, os, math, json, warnings, urllib.request, re, subprocess
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
OUTPUT_DIR = PROJECT_ROOT / 'backtest' / 'results_us100'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STRATEGY_NAME = '七星美股版(最优) x7'
NOW = datetime.now()
NOW_STR = NOW.strftime('%Y-%m-%d %H:%M')
NOW_TAG = NOW.strftime('%Y%m%d_%H%M')

START_DATE = '2025-01-01'
END_DATE = NOW.strftime('%Y-%m-%d')

POOL = 'NVDA,AVGO,AMD,MU,LRCX,AMAT,ARM,AAPL,TSM,LITE,META,AMZN,NFLX,GOOGL,MSFT,CRM,NOW,CRWD,ORCL,PLTR,DDOG,SNPS,XOM,CVX,COP,EOG,OKE,NEM,FCX,LIN,CAT,GE,RTX,PLD,AMT'.split(',')

PARAMS = {'lookback_days': 25, 'holdings_num': 7, 'min_money': 500}

# ================================================================
# 实时行情获取 — 三级兜底 (L1→L2→失败告警)
# L1: WeStock Data (腾讯自选股)  L2: 新浪财经 API  L3: 全部失败→邮件告警
# 规则: 严禁在实时行情获取失败时使用过时数据，必须告警通知
# ================================================================
WESTOCK_SCRIPT = str(Path.home() / '.workbuddy/plugins/marketplaces/cb_teams_marketplace/plugins/finance-data/skills/westock-data/scripts/index.js')

def _fetch_realtime_westock(symbols):
    """L1: 通过 westock-data quote 获取美股实时行情"""
    prices = {}
    if not symbols:
        return prices
    try:
        us_codes = ','.join([f'us{s}' for s in symbols])
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT, 'quote', us_codes],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(WESTOCK_SCRIPT)
        )
        if result.returncode != 0:
            return prices
        output = result.stdout
        in_table = False
        col_idx = {}
        for line in output.split('\n'):
            line = line.strip()
            if not line.startswith('|'):
                continue
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if not in_table:
                if 'price' in parts or 'code' in parts:
                    for i, h in enumerate(parts):
                        if h == 'price':
                            col_idx['price'] = i
                        elif h == 'change_percent':
                            col_idx['chg'] = i
                        elif h == 'code':
                            col_idx['code'] = i
                        elif h == 'prev_close':
                            col_idx['prev_close'] = i
                    in_table = True
                continue
            if all(p.replace('-','').replace(':','') == '' for p in parts):
                continue
            if 'code' in col_idx and 'price' in col_idx:
                code_raw = parts[col_idx['code']].replace('us', '')
                try:
                    p = float(parts[col_idx['price']])
                except:
                    continue
                chg = 0.0
                if 'chg' in col_idx:
                    try:
                        chg = float(parts[col_idx['chg']])
                    except:
                        pass
                prev = 0.0
                if 'prev_close' in col_idx:
                    try:
                        prev = float(parts[col_idx['prev_close']])
                    except:
                        pass
                prices[code_raw] = {
                    'price': p,
                    'change_pct': chg,
                    'prev_close': prev,
                }
    except Exception:
        pass
    return prices

def _fetch_realtime_sina(symbols):
    """L2: 新浪财经美股实时行情 (hq.sinajs.cn)"""
    prices = {}
    if not symbols:
        return prices
    try:
        codes = ','.join([f'gb_{s.lower()}' for s in symbols])
        url = f'https://hq.sinajs.cn/list={codes}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.sina.com.cn/'
        })
        resp = urllib.request.urlopen(req, timeout=15)
        text = resp.read().decode('gbk', errors='replace')
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            m = re.match(r'var hq_str_gb_(\w+)="(.+)"', line)
            if not m:
                continue
            code = m.group(1).upper()
            fields = m.group(2).split(',')
            if len(fields) < 3:
                continue
            try:
                price = float(fields[1])
                chg_pct = float(fields[2])
                if price <= 0:
                    continue
                prices[code] = {
                    'price': price,
                    'change_pct': chg_pct,
                    'prev_close': 0.0,
                }
            except (ValueError, IndexError):
                continue
    except Exception:
        pass
    return prices

def fetch_realtime_prices(symbols):
    """获取美股实时行情，三级兜底
    返回: (prices_dict, source)
      source: 'westock' | 'sina' | 'failed'
    """
    # L1: WeStock Data (腾讯自选股)
    prices = _fetch_realtime_westock(symbols)
    if prices:
        print(f'[实时行情] L1-WeStock 成功: {len(prices)}/{len(symbols)} 只')
        return prices, 'westock'

    print(f'[实时行情] L1-WeStock 失败, 尝试 L2-新浪财经...')

    # L2: 新浪财经
    prices = _fetch_realtime_sina(symbols)
    if prices:
        print(f'[实时行情] L2-新浪财经 成功: {len(prices)}/{len(symbols)} 只')
        return prices, 'sina'

    print(f'[实时行情] 所有渠道均失败! 触发告警...')
    return {}, 'failed'

def send_monitor_failure_alert(failed_sources):
    """实时行情获取失败告警邮件 — 严禁使用过时数据，必须通知用户"""
    subject = f"[七星美股版] ⚠️ 实时行情获取失败 监控已失效 - {NOW_STR}"
    body = f"""<html><body style="font-family:'Microsoft YaHei',sans-serif;max-width:600px;margin:20px auto;">
<h2 style="color:#C62828;">⚠️ 实时行情获取失败 — 监控已失效</h2>
<p>七星美股版监控任务于 <b>{NOW_STR}</b> 执行时，所有实时行情获取渠道均已失败：</p>
<table style="border-collapse:collapse;width:100%;margin:10px 0;">
<tr style="background:#FFEBEE;"><td style="padding:8px;border:1px solid #ddd;"><b>渠道</b></td><td style="padding:8px;border:1px solid #ddd;"><b>状态</b></td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;">L1: WeStock Data (腾讯自选股)</td><td style="padding:8px;border:1px solid #ddd;color:#C62828;">❌ 失败</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;">L2: 新浪财经 API</td><td style="padding:8px;border:1px solid #ddd;color:#C62828;">❌ 失败</td></tr>
</table>
<div style="background:#FFF3CD;border:1px solid #FFC107;padding:12px;border-radius:4px;margin:15px 0;">
    <b>⚠️ 当前报告中价格数据不可靠，监控已失效。</b><br>
    已尝试全部渠道获取实时价格均失败，请手动检查网络连接和数据源状态后重新执行。
</div>
<hr>
<p style="color:#888;font-size:11px;">七星美股版 · Blakever Trade · 自动告警<br>此邮件由系统自动发送，请勿回复。</p>
</body></html>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = "848786642@qq.com"
    msg["To"] = "848786642@qq.com"
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
            s.login("848786642@qq.com", "ljbtvacrctjobfed")
            s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
        print(f'[告警] 实时行情获取失败告警邮件已发送到 848786642@qq.com')
        return True
    except Exception as e:
        print(f'[告警] 告警邮件发送也失败: {e}')
        return False

# ================================================================
# 加载数据
# ================================================================
print(f'加载 {len(POOL)} 只美股数据...')
all_data = {}
for sym in POOL:
    fp = DATA_DIR / f'{sym}.csv'
    if not fp.exists(): continue
    try:
        df = pd.read_csv(fp)
        df = df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['date'] = pd.to_datetime(df['date']); df = df.set_index('date').sort_index()
        pre_start = pd.Timestamp(START_DATE) - pd.Timedelta(days=100)
        mask = (df.index >= pre_start) & (df.index <= END_DATE)
        df = df[mask]
        if len(df[df.index >= START_DATE]) >= 25: all_data[sym] = df
    except: pass

trade_dates = sorted(set().union(*[df.index.strftime('%Y-%m-%d').tolist() for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d <= END_DATE]
print(f'有效: {len(all_data)}只 | 交易日: {len(trade_dates)}天')

# ================================================================
# 回测引擎
# ================================================================
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

def get_ranked(prices, date):
    """动量排名: 仅使用 date 之前(不含当日)的收盘数据, 防未来函数"""
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index < pd.Timestamp(date); hist = df[mask]
        if len(hist) < 35: continue
        cp = prices[code]
        if cp <= 0: continue
        # 当日涨跌幅（相对于前一交易日收盘）
        chg_pct = 0.0
        if len(hist) >= 1:
            prev_close = hist['close'].iloc[-1]
            if prev_close > 0:
                chg_pct = (cp - prev_close) / prev_close * 100
        score = calc_score(hist['close'].values, 25)
        ranked.append({'code':code,'score':score,'price':cp,'chg_pct':round(chg_pct,2)})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

class USPortfolio:
    def __init__(self, cash=100000, comm=0.005, slippage=0.0005):
        self.initial_cash = cash; self.cash = cash; self.comm = comm
        self.slippage = slippage  # 滑点: 0.05%
        self.positions = {}; self.trade_log = []; self.daily_values = []
    @property
    def total_value(self):
        pv = sum(p['shares']*p.get('last_price',p['cost_price']) for p in self.positions.values())
        return self.cash + pv
    def update_prices(self, pdict):
        for c,p in pdict.items():
            if c in self.positions: self.positions[c]['last_price'] = p
    def buy(self, code, shares, price, date, reason=''):
        price = price * (1 + self.slippage)  # 买入滑点
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
        price = price * (1 - self.slippage)  # 卖出滑点
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

INITIAL_CASH = 100000
pf = USPortfolio(cash=INITIAL_CASH)
hn = PARAMS['holdings_num']

print(f'回测中: ${INITIAL_CASH:,.0f} | 持股{hn}只')
print('-' * 60)
for i, td in enumerate(trade_dates):
    tds = pd.Timestamp(td)
    prices = {}
    for code, df in all_data.items():
        m = df.index <= tds
        if m.any(): prices[code] = float(df.loc[m,'close'].iloc[-1])
    pf.update_prices(prices)
    ranked = get_ranked(prices, td)
    if not ranked: pf.record_daily_value(td); continue
    targets = [r['code'] for r in ranked if r['score'] > -999][:hn]
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
            if sh > 0 and sh * price >= PARAMS['min_money']:
                pf.buy(code, sh, price, td, reason=f'排名{idx+1}')
    pf.record_daily_value(td)
    if i % 20 == 0:
        top3 = ', '.join([f"{r['code']}({r['score']:.4f})" for r in ranked[:3]])
        print(f'  [{td}] Top3: {top3} | ${pf.total_value:,.0f}')

# ================================================================
# 结果计算
# ================================================================
dv = pf.daily_values
vals = [d['value'] for d in dv] if dv else [INITIAL_CASH]
fv = vals[-1]; tr = (fv - INITIAL_CASH) / INITIAL_CASH
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
buys = sum(1 for t in trades if t['action']=='BUY')
sells = sum(1 for t in trades if t['action']=='SELL')
st = [t for t in trades if t['action']=='SELL' and 'pnl_pct' in t]
wins = [t for t in st if t['pnl_pct']>0]; losses = [t for t in st if t['pnl_pct']<=0]
wr = len(wins)/len(st)*100 if st else 0
aw = sum(t['pnl_pct'] for t in wins)/len(wins)*100 if wins else 0
al = sum(t['pnl_pct'] for t in losses)/len(losses)*100 if losses else 0

# ================================================================
# 当前持仓 (最新7只排名)
# ================================================================
last_date = trade_dates[-1]
last_prices = {}
for code, df in all_data.items():
    mask = df.index <= pd.Timestamp(last_date)
    if mask.any(): last_prices[code] = float(df.loc[mask,'close'].iloc[-1])

# Try realtime prices (三级兜底: WeStock → 新浪 → 失败告警)
realtime, rt_source = fetch_realtime_prices(POOL)
realtime_valid = rt_source != 'failed'
final_ranked = get_ranked(last_prices, last_date)

# 实时行情失败时立即发送告警邮件
if not realtime_valid:
    send_monitor_failure_alert(['WeStock Data', '新浪财经'])
    rt_warning_banner = f"""<div style="background:#C62828;color:#fff;padding:12px 18px;border-radius:6px;margin:10px 0;text-align:center;font-weight:bold;font-size:13px;">
    ⚠️ 实时行情获取失败 (WeStock + 新浪财经 均不可用) — 当前显示价格均为最近交易日收盘价 ({last_date})，监控已失效！
</div>"""
elif rt_source == 'sina':
    rt_warning_banner = f"""<div style="background:#FFF3CD;color:#856404;padding:8px 12px;border-radius:4px;margin:8px 0;text-align:center;font-size:12px;">
    ℹ️ 实时行情来源: 新浪财经 (WeStock 不可用时自动切换)
</div>"""
else:
    rt_warning_banner = ""

# 用实时价格覆盖排名中的 price 和 chg_pct
if realtime_valid:
    for r in final_ranked:
        rt = realtime.get(r['code'], {})
        if rt.get('price', 0) > 0:
            r['price'] = rt['price']
            r['chg_pct'] = rt.get('change_pct', r.get('chg_pct', 0))

# 当前目标: 取前hn只
current_targets = [r for r in final_ranked if r['score'] > -999][:hn]

# Current portfolio holdings
current_holdings = []
for code in pf.get_position_codes():
    pos = pf.positions[code]
    rt = realtime.get(code, {})
    rt_price = rt.get('price', 0)
    rt_chg = rt.get('change_pct', 0)
    close_price = last_prices.get(code, 0)
    # 仅当实时行情有效时才使用实时价格，否则用日线收盘价
    cur_price = rt_price if (realtime_valid and rt_price > 0) else close_price
    # 当日涨跌幅：优先实时，否则从日线计算
    if realtime_valid and rt_chg != 0:
        day_chg = rt_chg
    elif code in all_data:
        h = all_data[code]
        if len(h) >= 2:
            prev = h['close'].iloc[-2]
            day_chg = (close_price - prev) / prev * 100 if prev > 0 else 0
        else:
            day_chg = 0
    else:
        day_chg = 0
    cost = pos.get('cost_price', cur_price)
    pnl = (cur_price - cost) / cost * 100 if cost > 0 else 0
    current_holdings.append({
        'code': code, 'shares': pos['shares'],
        'cost': cost, 'price': cur_price,
        'pnl_pct': pnl, 'day_chg': round(day_chg, 2),
        'buy_date': pos.get('buy_date', ''),
    })

print(f'\n{"="*60}')
print(f'  绩效: +{tr*100:.2f}% | 年化{ann_ret:.1f}% | 回撤{mdd*100:.1f}% | 夏普{sh_val:.4f}')
print(f'  交易: {len(trades)}次 | 胜率{wr:.1f}%')
print(f'  当前持仓: {len(current_holdings)}只')
print(f'{"="*60}')

# ================================================================
# 生成HTML邮件 (参考七星172模板)
# ================================================================
# 近期交易 (最近30条)
recent_trades = trades[-30:][::-1]

# 交易表格
trade_rows_html = ""
for t in recent_trades:
    d = '买入' if t['action']=='BUY' else '卖出'
    pnl = t.get('pnl_pct', None)
    ps = f'{pnl*100:+.2f}%' if pnl is not None else '-'
    bg = '#E2EFDA' if t['action']=='BUY' else '#FCE4D6'
    pc = '#28A745' if (pnl and pnl>0) else ('#DC3545' if (pnl and pnl<0) else '#888')
    trade_rows_html += f"""<tr style="background:{bg};white-space:nowrap;">
        <td style="padding:4px 8px;">{t['date']}</td>
        <td style="padding:4px 8px;font-weight:bold;">{d}</td>
        <td style="padding:4px 8px;">{t['code']}</td>
        <td style="padding:4px 8px;text-align:right;">${t['price']:.2f}</td>
        <td style="padding:4px 8px;text-align:right;">{t.get('shares',0)}</td>
        <td style="padding:4px 8px;text-align:right;">${t.get('amount',0):,.2f}</td>
        <td style="padding:4px 8px;font-size:11px;color:#555;">{t.get('reason','')}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pc};">{ps}</td></tr>"""

# 排名表格
rank_rows_html = ""
for i, r in enumerate(final_ranked[:10]):
    bg = '#FEF9E7' if i==0 else ('#FFF' if i%2==0 else '#F8F9FA')
    score_color = '#28A745' if r['score']>0 else '#DC3545'
    chg = r.get('chg_pct', 0)
    chg_color = '#28A745' if chg > 0 else ('#DC3545' if chg < 0 else '#888')
    chg_str = f'+{chg:.2f}%' if chg > 0 else (f'{chg:.2f}%' if chg < 0 else '0.00%')
    rank_rows_html += f"""<tr style="background:{bg};white-space:nowrap;">
        <td style="padding:4px 6px;text-align:center;font-weight:bold;">{i+1}</td>
        <td style="padding:4px 6px;">{r['code']}</td>
        <td style="padding:4px 6px;text-align:right;font-weight:bold;color:{score_color};">{r['score']:.4f}</td>
        <td style="padding:4px 6px;text-align:right;">${r['price']:.2f}</td>
        <td style="padding:4px 6px;text-align:right;font-weight:bold;color:{chg_color};">{chg_str}</td></tr>"""

# 当前持仓表格
holding_rows_html = ""
total_holding_val = 0
for h in current_holdings:
    val = h['shares'] * h['price']
    total_holding_val += val
    pnl_c = '#28A745' if h['pnl_pct'] > 0 else '#DC3545'
    dchg = h.get('day_chg', 0)
    dchg_c = '#28A745' if dchg > 0 else ('#DC3545' if dchg < 0 else '#888')
    dchg_str = f'+{dchg:.2f}%' if dchg > 0 else (f'{dchg:.2f}%' if dchg < 0 else '0.00%')
    holding_rows_html += f"""<tr style="white-space:nowrap;">
        <td style="padding:4px 8px;">{h['code']}</td>
        <td style="padding:4px 8px;text-align:right;">{h['shares']}</td>
        <td style="padding:4px 8px;text-align:right;">${h['cost']:.2f}</td>
        <td style="padding:4px 8px;text-align:right;">${h['price']:.2f}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{dchg_c};">{dchg_str}</td>
        <td style="padding:4px 8px;text-align:right;">${val:,.2f}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pnl_c};">{h['pnl_pct']:+.2f}%</td>
        <td style="padding:4px 8px;font-size:11px;color:#555;">{h['buy_date']}</td></tr>"""

ret_color = '#2E7D32' if tr>0 else '#C62828'
ret_bg = '#E8F5E9' if tr>0 else '#FFEBEE'

html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>七星美股版 监控报告</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:920px;margin:0 auto;padding:20px;background:#f8f9fa;}}
h1{{font-size:22px;color:#1F4E79;text-align:center;margin:0 0 5px;}}
.subtitle{{text-align:center;font-size:12px;color:#888;margin-bottom:20px;}}
.card{{background:#fff;padding:15px 20px;border-radius:8px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.config-box{{background:#fff;padding:12px 18px;border-radius:8px;border-left:4px solid #1F4E79;margin-bottom:12px;font-size:13px;}}
.metrics-row{{display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;}}
.metric-card{{flex:1;min-width:155px;background:#fff;padding:12px;border-radius:8px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06);}}
.metric-label{{font-size:11px;color:#888;margin-bottom:5px;}}
.metric-value{{font-size:18px;font-weight:bold;color:#1F4E79;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#1F4E79;color:#fff;padding:7px;text-align:left;}}
td{{padding:5px 7px;border-bottom:1px solid #eee;}}
.footer{{text-align:center;font-size:10px;color:#aaa;margin-top:25px;padding-top:15px;border-top:1px solid #eee;}}
</style></head><body>
<h1>七星美股版(最优) · 实盘监控报告</h1>
<div class="subtitle">{NOW_STR} | 数据区间: {trade_dates[0]} ~ {trade_dates[-1]}</div>
{rt_warning_banner}

<div class="config-box">
    <b>策略:</b> 七星美股版最优 | <b>股票池:</b> 35只 (8类高成长+能源+工业) | <b>持股:</b> {hn}只等权 | <b>周期:</b> 25日动量 | <b>佣金:</b> $0.005/股<br>
    <b>过滤:</b> 无 (盈利保护关·成交量关·短期动量关·硬止损关) | <b>评分:</b> exp(slope×250)×R²
</div>

<div class="card"><h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">当前持仓 ({len(current_holdings)}只) | 总市值 ${total_holding_val:,.2f}</h3>
<div style="overflow-x:auto;"><table>
<tr><th>代码</th><th>数量</th><th>成本</th><th>现价</th><th>涨跌</th><th>市值</th><th>持仓盈亏</th><th>买入日</th></tr>
{holding_rows_html}</table></div></div>

<div class="card"><h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">ETF动量排名 Top 10 ({trade_dates[-1]})</h3>
<div style="overflow-x:auto;"><table>
<tr><th>排名</th><th>代码</th><th>综合得分</th><th>价格</th><th>涨跌幅</th></tr>
{rank_rows_html}</table></div></div>

<div class="card"><h3 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">最近30条交易记录</h3>
<div style="overflow-x:auto;"><table>
<tr><th>日期</th><th>方向</th><th>代码</th><th>价格</th><th>数量</th><th>金额</th><th>理由</th><th>盈亏</th></tr>
{trade_rows_html}</table></div></div>

<div class="footer">七星美股版(最优) · Blakever Trade · {NOW_STR}<br>本报告仅供研究参考，不构成投资建议。</div>
</body></html>"""

# ================================================================
# 保存 + 发送邮件
# ================================================================
html_path = OUTPUT_DIR / f'七星美股版_实盘报告_{NOW_TAG}.html'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

# 保存交易记录
trades_path = OUTPUT_DIR / f'七星美股版_交易记录_2025-{NOW_TAG}.json'
with open(trades_path, 'w', encoding='utf-8') as f:
    json.dump({'strategy': STRATEGY_NAME, 'period': f'{trade_dates[0]}~{trade_dates[-1]}', 'trades': trades}, f, ensure_ascii=False, indent=2, default=str)

# 邮件
if realtime_valid:
    msg_subject = f"[七星美股版] 实盘监控报告 - {NOW_STR}"
else:
    msg_subject = f"[七星美股版] ⚠️ 监控失效(实时行情缺失) - {NOW_STR}"

msg = MIMEMultipart("mixed")
msg["Subject"] = msg_subject
msg["From"] = "848786642@qq.com"
msg["To"] = "848786642@qq.com"
msg.attach(MIMEText(html, "html", "utf-8"))

try:
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
        s.login("848786642@qq.com", "ljbtvacrctjobfed")
        s.sendmail("848786642@qq.com", "848786642@qq.com", msg.as_string())
    print(f'\n[OK] 邮件已发送')
except Exception as e:
    print(f'\n[WARN] 邮件发送失败: {e}')

print(f'\n报告: {html_path}')
print(f'交易: {trades_path}')
print(f'当前持仓: {len(current_holdings)}只, 市值 ${total_holding_val:,.2f}')
print('完成!')
