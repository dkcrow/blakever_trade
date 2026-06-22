#!/usr/bin/env python3
"""七星港股版 实盘报告 (37只, 2025-01-01至今)
Pool: 37只港股, 动量排名, 5只等权, score>=0.5, 日频调仓
佣金0.1%+印花税0.13%+交易费0.00565%, 滑点0.1%
"""
import sys, os, math, json, warnings, urllib.request, re, subprocess
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
warnings.filterwarnings('ignore')

NOW = datetime.now()
NOW_STR = NOW.strftime('%Y-%m-%d %H:%M')
NOW_TAG = NOW.strftime('%Y%m%d_%H%M')
STRATEGY_NAME = "七星港股版"

# ================================================================
# 港股池: 44只 (2026-06-18: 持股5只, 年化+125.5%, 回撤-17.8%, 夏普2.14)
# ================================================================
# 37只 (2026-06-18精简: 删7只低贡献+负向股)
HK_POOL = [
    # 互联网/平台 (5)
    '00700',  # 腾讯控股
    '09988',  # 阿里巴巴
    '01810',  # 小米
    '03690',  # 美团
    '09999',  # 网易
    # AI大模型 (2)
    '02513',  # 智谱
    '00100',  # MiniMax-W
    # AI/生物科技 (3)
    '02162',  # 康诺亚-B
    '02616',  # 基石药业-B
    '09969',  # 诺诚健华
    # AI应用/硬件 (2)
    '02418',  # 德银天下
    '01357',  # 美图公司
    # 半导体 (3)
    '00981',  # 中芯国际
    '01347',  # 华虹半导体
    '00522',  # ASMPT
    # 新能源车 (1)
    '01211',  # 比亚迪
    # 制药 (2)
    '01093',  # 石药集团
    '01177',  # 中国生物制药
    # 工业/制造 (3)
    '02338',  # 潍柴动力
    '02038',  # 富智康集团
    '01378',  # 中国宏桥
    # 金融 (7)
    '00388',  # 港交所
    '02388',  # 中银香港
    '00005',  # 汇丰控股
    '02318',  # 中国平安
    '00939',  # 建设银行
    '02628',  # 中国人寿
    '03988',  # 中国银行
    # 科技/AI平台 (1)
    '09888',  # 百度
    # 能源/材料 (3)
    '00883',  # 中海油
    '02899',  # 紫金矿业
    '03993',  # 洛阳钼业
    # 物流 (1)
    '02618',  # 京东物流
    # 消费 (1)
    '01929',  # 周大福
    # 房地产/珠宝 (2)
    '01113',  # 长实集团
    '06181',  # 老铺黄金
    # 工业 (1)
    '00669',  # 创科实业
]

HK_NAME = {
    '00700': '腾讯控股', '09988': '阿里巴巴', '01810': '小米集团',
    '03690': '美团', '09999': '网易',
    '02513': '智谱', '00100': 'MiniMax',
    '02162': '康诺亚-B', '02616': '基石药业-B', '09688': '再鼎医药', '09969': '诺诚健华',
    '02418': '德银天下', '00992': '联想集团', '01357': '美图公司',
    '00981': '中芯国际', '01347': '华虹半导体', '00522': 'ASMPT',
    '01211': '比亚迪', '00175': '吉利汽车',
    '03692': '翰森制药', '01093': '石药集团', '01177': '中国生物制药',
    '02338': '潍柴动力', '02038': '富智康集团', '01378': '中国宏桥',
    '00388': '港交所', '02388': '中银香港', '00005': '汇丰控股', '02318': '中国平安', '00939': '建设银行', '02628': '中国人寿', '03988': '中国银行',
    '09888': '百度',
    '00883': '中海油', '02899': '紫金矿业', '03993': '洛阳钼业',
    '02618': '京东物流', '02057': '中通快递',
    '09633': '农夫山泉', '01929': '周大福', '06690': '海尔智家',
    '01113': '长实集团', '06181': '老铺黄金',
    '00669': '创科实业',
}

PARAMS = {'lookback_days': 25, 'holdings_num': 5, 'min_money': 500}
SCORE_THRESHOLD = 0.5  # 动量得分<0.5禁止买入, 已持有强制卖出
HK_COMM_RATE = 0.001       # 佣金0.1%
HK_STAMP_DUTY = 0.0013     # 印花税0.13%
HK_TRADE_FEE = 0.0000565   # 交易费0.00565%
SLIPPAGE = 0.001            # 滑点0.1%
CASH = 1000000               # 港币100万本金
DATA_DIR = Path('data/storage/stock_data/hk')
OUTPUT_DIR = Path('backtest/results_hk')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = '2023-06-18'
END_DATE = NOW.strftime('%Y-%m-%d')

# ================================================================
# 实时行情 (WeStock Data)
# ================================================================
# 2026-06-22修复: 插件迁移, 旧cb_teams_marketplace路径失效→实时行情失败→涨跌回退历史值(不是最新)
WESTOCK_SCRIPT = str(Path.home() / '.workbuddy/plugins/marketplaces/experts/plugins/stock-partner-team/skills/westock-data/scripts/index.js')

def _fetch_realtime_hk_westock(codes_list):
    """L1: WeStock Data (腾讯自选股) 港股实时行情 → {code: {price, change_pct}}"""
    prices = {}
    if not codes_list: return prices
    codes = ','.join([f'hk{c}' for c in codes_list])
    try:
        result = subprocess.run(
            ['node', WESTOCK_SCRIPT, 'quote', codes],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(WESTOCK_SCRIPT))
        if result.returncode != 0: return prices
        in_table = False; col_idx = {}
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line.startswith('|'): continue
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if not in_table:
                if 'code' in parts or 'price' in parts:
                    for i, h in enumerate(parts):
                        if h == 'code': col_idx['code'] = i
                        elif h == 'price': col_idx['price'] = i
                        elif h == 'change_percent': col_idx['chg'] = i
                    in_table = True
                continue
            if all(p.replace('-','').replace(':','') == '' for p in parts): continue
            if 'code' in col_idx and 'price' in col_idx:
                try:
                    code = parts[col_idx['code']].replace('hk','')
                    p = float(parts[col_idx['price']])
                    chg = float(parts[col_idx.get('chg', 0)]) if col_idx.get('chg') else 0
                    if p > 0: prices[code] = {'price': p, 'change_pct': chg}
                except: pass
    except: pass
    return prices

def _fetch_realtime_hk_sina(codes_list):
    """L2: 新浪财经 (hq.sinajs.cn) 港股实时行情 → {code: {price, change_pct}}
    港股格式: rt_hk<5位代码>; 字段: [3]昨收 [6]现价 [8]涨跌幅%"""
    prices = {}
    if not codes_list: return prices
    try:
        codes = ','.join([f'rt_hk{c}' for c in codes_list])
        url = f'https://hq.sinajs.cn/list={codes}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.sina.com.cn/'})
        text = urllib.request.urlopen(req, timeout=15).read().decode('gbk', errors='replace')
        for line in text.strip().split('\n'):
            m = re.match(r'var hq_str_rt_hk(\d+)="(.+)"', line)
            if not m: continue
            code = m.group(1); f = m.group(2).split(',')
            if len(f) < 9: continue
            try:
                price = float(f[6]); chg = float(f[8])
                if price > 0: prices[code] = {'price': price, 'change_pct': chg}
            except (ValueError, IndexError): continue
    except: pass
    return prices

def fetch_realtime_prices():
    """获取港股实时行情, 两级兜底逐个尝试: L1 WeStock → L2 新浪财经 → failed
    返回 (prices_dict, source). source: 'westock'|'sina'|'failed'
    铁律: 全部失败时返回 'failed', 严禁用历史数据冒充实时"""
    # L1: WeStock Data
    prices = _fetch_realtime_hk_westock(HK_POOL)
    if prices:
        print(f'[实时行情] L1-WeStock 成功: {len(prices)}/{len(HK_POOL)} 只')
        return prices, 'westock'
    print('[实时行情] L1-WeStock 失败, 尝试 L2-新浪财经...')
    # L2: 新浪财经
    prices = _fetch_realtime_hk_sina(HK_POOL)
    if prices:
        print(f'[实时行情] L2-新浪财经 成功: {len(prices)}/{len(HK_POOL)} 只')
        return prices, 'sina'
    print('[实时行情] ⚠️ 所有渠道均失败! 严禁使用历史数据冒充实时')
    return {}, 'failed'

# ================================================================
# 数据加载
# ================================================================
all_data = {}
for code in HK_POOL:
    fp = DATA_DIR / f'hk{code}.csv'
    if fp.exists():
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        if len(df) > 35: all_data[code] = df

trade_dates = sorted(set().union(*[set(df.index) for df in all_data.values()]))
trade_dates = [d for d in trade_dates if START_DATE <= d.strftime('%Y-%m-%d') <= END_DATE]

# ================================================================
# 动量评分 (与七星美股版完全一致: exp(slope×250) × R², 仅用<date数据)
# ================================================================
def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_res = np.sum(res**2); ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return ann * r2

def get_ranked(prices, date):
    ranked = []
    for code, df in all_data.items():
        if code not in prices: continue
        mask = df.index < pd.Timestamp(date); hist = df[mask]
        if len(hist) < 35: continue
        cp = prices[code]
        if cp <= 0: continue
        chg_pct = 0.0
        if len(hist) >= 1:
            prev_close = hist['close'].iloc[-1]
            if prev_close > 0: chg_pct = (cp - prev_close) / prev_close * 100
        score = calc_score(hist['close'].values[-25:])
        ranked.append({'code': code, 'score': score, 'price': cp, 'chg_pct': round(chg_pct, 2)})
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked

# ================================================================
# 投资组合 (港股费率)
# ================================================================
class HKPortfolio:
    def __init__(s, cash=CASH):
        s.initial_cash = cash; s.cash = cash
        s.positions = {}; s.trade_log = []; s.daily_values = []
    @property
    def total_value(s):
        pv = sum(p['shares']*p.get('last_price',p['cost_price']) for p in s.positions.values())
        return s.cash + pv
    def update_prices(s, pdict):
        for c,p in pdict.items():
            if c in s.positions: s.positions[c]['last_price'] = p
    def buy(s, code, shares, price, date, reason=''):
        p = price * (1 + SLIPPAGE); tv = shares * p
        comm = max(tv * HK_COMM_RATE, 5)
        stamp = 0  # 港股买入免印花税
        trade_fee = tv * HK_TRADE_FEE
        total = tv + comm + trade_fee
        if total > s.cash + 0.01: return False
        s.cash -= total
        if code in s.positions:
            o = s.positions[code]; ts = o['shares'] + shares
            s.positions[code] = {'shares':ts,'cost_price':(o['shares']*o['cost_price']+shares*p)/ts,'last_price':p,'buy_date':o.get('buy_date',date)}
        else:
            s.positions[code] = {'shares':shares,'cost_price':p,'last_price':p,'buy_date':date}
        s.trade_log.append({'date':date,'action':'BUY','code':code,'shares':int(shares),'price':round(p,4),'reason':reason,
                            'comm':round(comm,2),'stamp':round(stamp,2),'fee':round(trade_fee,2),'total_value':round(s.total_value,2)})
        return True
    def sell(s, code, shares, price, date, reason=''):
        if code not in s.positions: return False
        p = price * (1 - SLIPPAGE); pos = s.positions[code]
        a = min(shares, pos['shares'])
        tv = a * p
        comm = max(tv * HK_COMM_RATE, 5)
        stamp = tv * HK_STAMP_DUTY  # 港股卖出印花税
        trade_fee = tv * HK_TRADE_FEE
        s.cash += tv - comm - stamp - trade_fee
        pnl = (p - pos['cost_price']) / pos['cost_price'] * 100
        s.trade_log.append({'date':date,'action':'SELL','code':code,'shares':int(a),'price':round(p,4),'pnl_pct':round(pnl,2),'reason':reason,
                            'comm':round(comm,2),'stamp':round(stamp,2),'fee':round(trade_fee,2),'total_value':round(s.total_value,2)})
        if a >= pos['shares']: del s.positions[code]
        else: s.positions[code]['shares'] -= a
        return True
    def get_position_codes(s):
        return list(s.positions.keys())

# ================================================================
# 回测执行
# ================================================================
print(f"加载 {len(all_data)} 只港股数据...")
print(f"有效: {len(all_data)}只 | 交易日: {len(trade_dates)}天")
print(f"回测中: HK$ {CASH:,.0f} | 持股{PARAMS['holdings_num']}只 | {START_DATE}~{END_DATE}")

pf = HKPortfolio()
hn = PARAMS['holdings_num']
last_backtest_ranked = []  # 记录最后一天回测实际使用的排名

for i, date in enumerate(trade_dates):
    d_str = date.strftime('%Y-%m-%d')
    prices = {}
    for code in all_data:
        m = all_data[code].index == date
        if m.any(): prices[code] = float(all_data[code].loc[date, 'close'])
    if len(prices) < hn: continue

    ranked = get_ranked(prices, date)
    last_backtest_ranked = ranked  # 始终保存最新一天的排名
    # 得分阈值过滤: score>=0.5才允许买入, 最多hn只
    current_targets = [r for r in ranked if r['score'] >= SCORE_THRESHOLD][:hn]
    target_codes = set(r['code'] for r in current_targets)
    current_codes = set(pf.get_position_codes())

    # 卖出非目标 + 得分跌破阈值的持仓
    to_sell = current_codes - target_codes
    for code in list(current_codes):
        found = next((r for r in ranked if r['code'] == code), None)
        if found and found['score'] < SCORE_THRESHOLD:
            to_sell.add(code)
    for code in to_sell:
        sell_price = prices.get(code, 0)
        if sell_price <= 0:
            sell_price = pf.positions[code].get('last_price', 0)
        if sell_price <= 0:
            sell_price = pf.positions[code].get('cost_price', 0)
        if sell_price > 0:
            pf.sell(code, pf.positions[code]['shares'], sell_price, d_str, '得分不足/调出')
        elif code not in prices:
            pf.sell(code, pf.positions[code]['shares'], pf.positions[code].get('cost_price', 1), d_str, '数据缺失_按成本清仓')

    pf.update_prices(prices)
    # 方案B: 纯可用现金分配 — 仅新标的获得现金，已持有不动
    new_targets = [r for r in current_targets if r['code'] not in pf.positions and r['code'] in prices]
    if new_targets:
        available = pf.cash * 0.95
        per_stock = available / len(new_targets)
        for r in new_targets:
            shares = int(per_stock / r['price'] / 100) * 100  # 港股整手100股
            if shares >= 100:
                pf.buy(r['code'], shares, r['price'], d_str, '动量轮换')

    pf.daily_values.append({'date': d_str, 'value': pf.total_value})

    if i % 50 == 0 or i == len(trade_dates)-1:
        top3 = ranked[:3]
        info = ', '.join([f'{r["code"]}({r["score"]:.4f})' for r in top3])
        print(f'  [{d_str}] Top3: {info} | HK$ {pf.total_value:,.0f}')

dv = pd.DataFrame(pf.daily_values)
tr_total = (dv['value'].iloc[-1] / CASH - 1) * 100
daily_ret = dv['value'].pct_change().dropna()
# 年化: 几何CAGR = (终值/本金)^(252/交易日) - 1
ann_ret = (dv['value'].iloc[-1] / CASH) ** (252 / max(len(daily_ret), 1)) - 1
max_dd = (dv['value'] / dv['value'].cummax() - 1).min() * 100
sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0

trades = pf.trade_log
sells_all = [t for t in trades if t['action'] == 'SELL']
wins = [t for t in sells_all if t.get('pnl_pct',0) > 0]
wr = len(wins) / len(sells_all) * 100 if sells_all else 0

# ================================================================
# 实时行情
# ================================================================
realtime, rt_source = fetch_realtime_prices()
realtime_valid = rt_source != 'failed'
final_ranked = last_backtest_ranked  # 使用回测最后一天的实际排名, 确保与持仓一致
if realtime_valid:
    for r in final_ranked:
        rt = realtime.get(r['code'], {})
        if rt.get('price', 0) > 0: r['price'] = rt['price']; r['chg_pct'] = rt.get('change_pct', r['chg_pct'])

current_holdings = []
for code in pf.get_position_codes():
    pos = pf.positions[code]
    rt = realtime.get(code, {})
    rt_price = rt.get('price', 0)
    cur_price = rt_price if (realtime_valid and rt_price > 0) else prices.get(code, pos['cost_price'])
    cost = pos['cost_price']
    pnl = (cur_price - cost) / cost * 100 if cost > 0 else 0
    # 2026-06-22: 实时失败时day_chg=None(显示"—"), 严禁用历史涨跌冒充实时
    if realtime_valid and rt.get('change_pct') is not None and rt.get('price', 0) > 0:
        chg = rt.get('change_pct', 0)
    else:
        chg = None
    current_holdings.append({'code': code, 'shares': pos['shares'], 'cost': cost, 'price': cur_price,
                              'pnl_pct': pnl, 'day_chg': chg, 'buy_date': pos.get('buy_date','')})

# ================================================================
# HTML报告
# ================================================================
hn = PARAMS['holdings_num']
# 实时行情来源标签 + 失败告警横幅
rt_label = {'westock': 'L1-WeStock(腾讯自选股)', 'sina': 'L2-新浪财经', 'failed': '⚠️ 全部渠道失败'}.get(rt_source, rt_source)
if realtime_valid:
    warning_banner = ''
else:
    warning_banner = ('<div style="background:#C62828;color:#fff;padding:12px 15px;border-radius:6px;'
                      'margin-bottom:12px;font-weight:bold;font-size:13px;line-height:1.6;">'
                      '⚠️ 实时行情获取失败（WeStock + 新浪财经均不可用）<br>'
                      '下方"现价"为最近交易日收盘价，"涨跌"列显示 — 表示无实时数据。'
                      '<b>请勿据此做盘中交易决策！</b></div>')
# 排名表
rank_rows = ""
for i, r in enumerate(final_ranked[:10]):
    bg = '#FEF9E7' if i==0 else ('#FFF' if i%2==0 else '#F8F9FA')
    sc = '#28A745' if r['score']>0 else '#DC3545'
    if realtime_valid:
        cc = '#28A745' if r.get('chg_pct',0)>0 else ('#DC3545' if r.get('chg_pct',0)<0 else '#888')
        cs = f'+{r["chg_pct"]:.2f}%' if r.get('chg_pct',0)>0 else (f'{r["chg_pct"]:.2f}%' if r.get('chg_pct',0)<0 else '0.00%')
    else:
        cc = '#888'; cs = '—'  # 实时失败, 不冒充历史涨跌
    name = HK_NAME.get(r['code'], r['code'])
    rank_rows += f"""<tr style="background:{bg};white-space:nowrap;">
        <td style="padding:4px 8px;text-align:center;font-weight:bold;">{i+1}</td>
        <td style="padding:4px 8px;">{r['code']}</td>
        <td style="padding:4px 8px;">{name}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{sc};">{r['score']:.4f}</td>
        <td style="padding:4px 8px;text-align:right;">HK$ {r['price']:.2f}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{cc};">{cs}</td></tr>"""

# 持仓表
hold_rows = ""
total_val = 0
for h in current_holdings:
    val = h['shares'] * h['price']; total_val += val
    pc = '#28A745' if h['pnl_pct']>0 else '#DC3545'
    dchg = h.get('day_chg')
    if dchg is None:
        dc = '#888'; ds = '—'  # 实时失败, 不冒充历史涨跌
    else:
        dc = '#28A745' if dchg > 0 else ('#DC3545' if dchg < 0 else '#888')
        ds = f'+{dchg:.2f}%' if dchg > 0 else (f'{dchg:.2f}%' if dchg < 0 else '0.00%')
    name = HK_NAME.get(h['code'], h['code'])
    hold_rows += f"""<tr style="white-space:nowrap;">
        <td style="padding:4px 8px;">{h['code']}</td>
        <td style="padding:4px 8px;">{name}</td>
        <td style="padding:4px 8px;text-align:right;">{h['shares']:,}</td>
        <td style="padding:4px 8px;text-align:right;">HK$ {h['cost']:.2f}</td>
        <td style="padding:4px 8px;text-align:right;">HK$ {h['price']:.2f}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{dc};">{ds}</td>
        <td style="padding:4px 8px;text-align:right;">HK$ {val:,.0f}</td>
        <td style="padding:4px 8px;text-align:right;font-weight:bold;color:{pc};">{h['pnl_pct']:+.2f}%</td>
        <td style="padding:4px 8px;font-size:10px;color:#555;">{h['buy_date']}</td></tr>"""

# 最近20条交易
recent = trades[-20:][::-1]
trade_html = ""
for t in recent:
    d = '买入' if t['action']=='BUY' else '卖出'
    pnl = t.get('pnl_pct')
    ps = f'+{pnl:.2f}%' if (pnl is not None and pnl>0) else (f'{pnl:.2f}%' if (pnl is not None and pnl<0) else '-')
    amt = t.get('shares',0) * t.get('price',0)
    bg = '#E2EFDA' if t['action']=='BUY' else '#FCE4D6'
    name = HK_NAME.get(t['code'], '')
    trade_html += f"""<tr style="background:{bg};white-space:nowrap;">
        <td style="padding:3px 6px;">{t['date']}</td>
        <td style="padding:3px 6px;font-weight:bold;">{d}</td>
        <td style="padding:3px 6px;">{t['code']} {name}</td>
        <td style="padding:3px 6px;text-align:right;">HK$ {t['price']:.2f}</td>
        <td style="padding:3px 6px;text-align:right;">{t.get('shares',0)}</td>
        <td style="padding:3px 6px;text-align:right;">HK$ {amt:,.0f}</td>
        <td style="padding:3px 6px;font-size:10px;color:#555;">{t.get('reason','')}</td>
        <td style="padding:3px 6px;text-align:right;font-weight:bold;color:{'#28A745' if (pnl and pnl>0) else ('#DC3545' if (pnl and pnl<0) else '#888')};">{ps}</td>
        <td style="padding:3px 6px;text-align:right;font-weight:bold;color:#1F4E79;">HK$ {t.get('total_value',0):,.0f}</td></tr>"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:15px;background:#F0F2F5;}}
.card{{background:#fff;padding:15px;border-radius:8px;margin-bottom:12px;}}
.config-box{{background:#1F4E79;color:#fff;padding:10px 15px;border-radius:6px;margin-bottom:10px;font-size:12px;line-height:1.6;}}
.metrics-row{{display:flex;flex-wrap:wrap;gap:10px;}}
.metric-card{{flex:1;min-width:100px;background:#F8F9FA;padding:10px;border-radius:6px;text-align:center;}}
.metric-label{{font-size:11px;color:#888;}}
.metric-value{{font-size:18px;font-weight:bold;}}
h1{{font-size:18px;color:#1F4E79;margin:0;}}
.subtitle{{font-size:11px;color:#888;margin-top:3px;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
th{{background:#1F4E79;color:#fff;padding:6px 8px;text-align:left;}}
.footer{{text-align:center;font-size:10px;color:#999;margin-top:15px;}}
</style></head><body>
<h1>🇭🇰 七星港股版</h1>
<div class="subtitle">{NOW_STR} | 数据区间: {trade_dates[0].strftime('%Y-%m-%d')} ~ {trade_dates[-1].strftime('%Y-%m-%d')}</div>

{warning_banner}
<div class="config-box">
    <b>策略:</b> 七星港股版 | <b>股票池:</b> 37只 | <b>持股:</b> {hn}只等权 | <b>周期:</b> 25日动量 | <b>得分阈值:</b> >=0.5<br>
    <b>佣金:</b> 0.1% | <b>印花税:</b> 0.13%(卖) | <b>滑点:</b> 0.1% | <b>评分:</b> exp(slope×250)×R² | <b>约束:</b> 得分<0.5禁止买入,已持强制卖出<br>
    <b>实时行情:</b> {rt_label}
</div>

<div class="card"><h2 style="font-size:14px;color:#1F4E79;margin:0 0 8px 0;">📈 回测绩效</h2>
<div class="metrics-row">
<div class="metric-card"><div class="metric-label">累计收益</div><div class="metric-value" style="color:#2E7D32;">{tr_total:+.1f}%</div></div>
<div class="metric-card"><div class="metric-label">年化收益</div><div class="metric-value" style="color:#2E7D32;">{ann_ret*100:.1f}%</div></div>
<div class="metric-card"><div class="metric-label">最大回撤</div><div class="metric-value" style="color:#C62828;">{max_dd:.1f}%</div></div>
<div class="metric-card"><div class="metric-label">夏普比率</div><div class="metric-value" style="color:#1F4E79;">{sharpe:.2f}</div></div>
<div class="metric-card"><div class="metric-label">交易次数</div><div class="metric-value" style="color:#1F4E79;">{len(trades)}</div></div>
<div class="metric-card"><div class="metric-label">胜率</div><div class="metric-value" style="color:#2E7D32;">{wr:.0f}%</div></div>
</div></div>

<div class="card"><h2 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">🏆 动量排名 Top10</h2>
<div style="overflow-x:auto;"><table>
<tr><th>排名</th><th>代码</th><th>名称</th><th>综合得分</th><th>现价</th><th>涨跌</th></tr>
{rank_rows}</table></div></div>

<div class="card"><h2 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">💼 当前持仓 ({len(current_holdings)}只) | 总市值 HK$ {total_val:,.0f}</h2>
<div style="overflow-x:auto;"><table>
<tr><th>代码</th><th>名称</th><th>数量</th><th>成本</th><th>现价</th><th>涨跌</th><th>市值</th><th>盈亏</th><th>买入日</th></tr>
{hold_rows}</table></div></div>

<div class="card"><h2 style="font-size:14px;color:#1F4E79;margin:0 0 10px;">📋 最近20条交易记录</h2>
<div style="overflow-x:auto;"><table>
<tr><th>日期</th><th>方向</th><th>代码/名称</th><th>价格</th><th>数量</th><th>金额</th><th>理由</th><th>盈亏</th><th>总资产</th></tr>
{trade_html}</table></div></div>

<div class="footer">七星港股版 · Blakever Trade · {NOW_STR}<br>本报告仅供研究参考，不构成投资建议。</div>
</body></html>"""

# 保存
html_path = OUTPUT_DIR / f'七星港股版_实盘报告_{NOW_TAG}.html'
with open(html_path, 'w', encoding='utf-8') as f: f.write(html)
trades_path = OUTPUT_DIR / f'七星港股版_交易记录_2025-{NOW_TAG}.json'
with open(trades_path, 'w', encoding='utf-8') as f:
    json.dump({'strategy': STRATEGY_NAME, 'pool': HK_POOL, 'trades': trades}, f, ensure_ascii=False, indent=2, default=str)

# 邮件
msg = MIMEMultipart("mixed")
msg["Subject"] = (f"⚠️[七星港股版] 实时行情获取失败 - {NOW_STR}" if not realtime_valid
                  else f"[七星港股版] 实盘监控报告 - {NOW_STR}")
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

print(f'\n============================================================')
print(f'  绩效: {tr_total:+.2f}% | 年化{ann_ret*100:.1f}% | 回撤{max_dd:.1f}% | 夏普{sharpe:.4f}')
print(f'  交易: {len(trades)}次 | 胜率{wr:.1f}%')
print(f'  当前持仓: {len(current_holdings)}只, 市值 HK$ {total_val:,.2f}')
print(f'============================================================')
print(f'\n报告: {html_path}')
print(f'交易: {trades_path}')
print(f'完成!')
