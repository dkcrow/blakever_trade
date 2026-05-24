import backtrader as bt
import pandas as pd
import math
import os
from datetime import datetime

DATA_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\etf'

SANMA_ETFs = [
    '518880','159980','159985','501018','161226','159981',
    '513100','513500','513400','510300','510500','510050',
    '510210','159915','588080','512100','563360','512890',
    '159967','512040','159201','511380','511010','511220','511880',
]

LAPLACE_ETFs = [
    '518880','159980','159985','501018','161226','159981',
    '513100','159509','513290','513500','159529',
    '513400','513520','513030','513080','513310',
    '513730','159792','513130','513050','159920',
    '513690','510300','510500','510050','510210',
    '159915','588080','512100','563360','563300',
    '512890','159967','512040','159201','511380',
    '511010','511220',
]

def load_etf(code, fd, td):
    path = os.path.join(DATA_DIR, code + '.csv')
    if not os.path.exists(path): return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty: return None
        df.columns = [c.lower() for c in df.columns]
        need = ['open','high','low','close','volume']
        if not all(n in df.columns for n in need): return None
        df = df[(df.index >= pd.Timestamp(fd)) & (df.index <= pd.Timestamp(td))]
        return df if len(df) >= 30 else None
    except: return None

def w_reg(prices):
    n = len(prices)
    if n < 5: return 0.0
    y = [math.log(max(p, 0.001)) for p in prices]
    x = list(range(n))
    w = [1.0 + i/(n-1) for i in range(n)] if n > 1 else [1.0]*n
    ws = sum(w)
    wx = sum(w[i]*x[i] for i in range(n))
    wy = sum(w[i]*y[i] for i in range(n))
    xm = wx/ws
    ym = wy/ws
    num = sum(w[i]*(x[i]-xm)*(y[i]-ym) for i in range(n))
    den = sum(w[i]*(x[i]-xm)**2 for i in range(n))
    slope = num/den if abs(den) > 1e-10 else 0.0
    ss_tot = sum(w[i]*(y[i]-ym)**2 for i in range(n))
    ss_res = sum(w[i]*(y[i]-(slope*(x[i]-xm)+ym))**2 for i in range(n))
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 1e-10 else 0.0
    ann = math.exp(slope*252) - 1
    return max(0.0, ann * r2)

def add_an(cerebro):
    cerebro.addanalyzer(bt.analyzers.Returns, _name='ret')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')

def show(strat, label, cash=100000.0):
    print('\n' + '=' * 60)
    print('  ' + label)
    print('=' * 60)
    final = strat.broker.getvalue()
    tr = (final / cash - 1) * 100
    days = (datetime(2026,5,21) - datetime(2023,1,1)).days
    ann = ((final / cash) ** (365.0 / days) - 1) * 100
    print('Initial cash:   %.2f' % cash)
    print('Final value:    %.2f' % final)
    print('Total return:   %.2f%%' % tr)
    print('Annual return:  %.2f%%' % ann)
    try:
        dd_val = strat.analyzers.dd.get_analysis().get('max', {}).get('drawdown', 0.0)
        print('Max drawdown:   %.2f%%' % (dd_val * 100))
    except Exception as e:
        print('Max drawdown:  error', e)
    ta = strat.analyzers.ta.get_analysis()
    if 'total' in ta and ta['total']['total'] > 0:
        tot = ta['total']['total']
        won = ta.get('won', {}).get('total', 0)
        lost = ta.get('lost', {}).get('total', 0)
        wr = won / tot * 100 if tot > 0 else 0
        aw = ta.get('won', {}).get('pnl', {}).get('average', 0)
        al = ta.get('lost', {}).get('pnl', {}).get('average', 0)
        pl = abs(aw / al) if al != 0 else 0
        print('\nTrade stats:')
        print('  Trades: %d  |  /yr: %.1f' % (tot, tot / 3.0))
        print('  Win rate: %.1f%%  P/L: %.2f' % (wr, pl))
        print('  Avg win: %.2f  Avg loss: %.2f' % (aw, al))
    print('=' * 60)


class Sanma(bt.Strategy):
    params = (('short_lb', 10), ('long_lb', 60), ('top_n', 3), ('min_score', 0.0))
    def __init__(s):
        s.etfs = {}
        for d in s.datas: s.etfs[d._name] = d
        s.min_bars = s.p.long_lb + 1
        s.started = False
        s.current_etfs = set()
        s.pending_orders = {}
    def next(s):
        if len(s.data) < s.min_bars: return
        if not s.started:
            s.started = True
            print('  Sanma starts trading at bar', len(s.data))
        s._check_orders()
        scores = []
        for etf in SANMA_ETFs:
            if etf not in s.etfs: continue
            data = s.etfs[etf]
            n = len(data)
            if n < s.p.long_lb + 1: continue
            closes = [data.close[-i] for i in range(s.p.long_lb, -1, -1)]
            if len(closes) < s.p.short_lb: continue
            # Removed 4-day drop filter for more trades
            sp = closes[-s.p.short_lb:]
            lp = closes[-s.p.long_lb:] if len(closes) >= s.p.long_lb else sp
            sc = w_reg(sp) + w_reg(lp) * 0.5
            if sc > s.p.min_score:
                scores.append({'etf': etf, 'score': sc})
        if not scores:
            target_etfs = {'511880'}
        else:
            scores.sort(key=lambda x: x['score'], reverse=True)
            target_etfs = set(e['etf'] for e in scores[:s.p.top_n])
        if target_etfs != s.current_etfs:
            print('  bar=%d, top%d=%s' % (len(s.data), s.p.top_n, list(target_etfs)))
            s._rebalance(target_etfs)
    def _check_orders(s):
        done = [ref for ref, o in s.pending_orders.items() if o.status not in [bt.Order.Submitted, bt.Order.Accepted]]
        for ref in done: del s.pending_orders[ref]
    def _rebalance(s, target_etfs):
        for etf in list(s.current_etfs):
            if etf not in target_etfs:
                d = s.etfs.get(etf)
                if d and s.getposition(d).size > 0:
                    order = s.close(d)
                    if order: s.pending_orders[order.ref] = order
                s.current_etfs.discard(etf)
        for etf in target_etfs:
            if etf not in s.current_etfs:
                s._buy(etf)
                s.current_etfs.add(etf)
    def _buy(s, etf):
        d = s.etfs.get(etf)
        if not d: return
        p = d.close[0]
        if p <= 0: return
        cash = s.broker.getcash()
        sz = int((cash * 0.998 / len(s.current_etfs)) / p) if s.current_etfs else int((cash * 0.998) / p)
        print('  [Sanma] Buy %s: price=%.3f, cash=%.2f, size=%d' % (etf, p, cash, sz))
        if sz > 0:
            order = s.buy(d, size=sz)
            if order: s.pending_orders[order.ref] = order
    def notify_order(s, order):
        if order.status in [bt.Order.Completed]:
            if order.isbuy():
                print('  BUY EXECUTED: %s, price=%.3f, size=%d, value=%.2f' % (order.data._name, order.executed.price, order.executed.size, order.executed.value))
            elif order.issell():
                print('  SELL EXECUTED: %s, price=%.3f, size=%d, value=%.2f' % (order.data._name, order.executed.price, order.executed.size, order.executed.value))
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            print('  ORDER FAILED: %s, status=%d' % (order.data._name, order.status))


class Laplace(bt.Strategy):
    params = (('lookback', 25), ('top_n', 1))
    def __init__(s):
        s.etfs = {}
        s.bench = None
        for d in s.datas:
            if d._name in LAPLACE_ETFs: s.etfs[d._name] = d
            if d._name == '510300': s.bench = d
        s.mode = 'normal'
        s.min_bars = 50
        s.current_etfs = set()
        s.pending_orders = {}
    def next(s):
        if len(s.data) < s.min_bars: return
        s._check_mode()
        scores = []
        for etf in LAPLACE_ETFs:
            if etf not in s.etfs: continue
            data = s.etfs[etf]
            n = len(data)
            needed = s.p.lookback + 2
            if n < needed: continue
            closes = [data.close[-i] for i in range(needed-1, -1, -1)]
            if len(closes) < s.p.lookback: continue
            if etf != '511220':
                pos = s.getposition(data)
                if pos.size > 0:
                    hi = max(closes[-2:])
                    if data.close[0] < hi * (1 - 0.05): continue
            if len(closes) >= 4:
                d1 = closes[-1]/closes[-2] if closes[-2] > 0 else 1
                d2 = closes[-2]/closes[-3] if closes[-3] > 0 else 1
                d3 = closes[-3]/closes[-4] if closes[-4] > 0 else 1
                if min(d1, d2, d3) < 0.97: continue
            recent = closes[-(s.p.lookback+1):]
            sc = w_reg(recent)
            if sc > 0: scores.append({'etf': etf, 'score': sc})
        if not scores: target_etfs = {'511220'}
        else:
            scores.sort(key=lambda x: x['score'], reverse=True)
            target_etfs = set(e['etf'] for e in scores[:s.p.top_n])
        if target_etfs != s.current_etfs: s._rebalance(target_etfs)
    def _check_mode(s):
        if not s.bench: return
        if len(s.bench) < 21: return
        closes = [s.bench.close[-i] for i in range(20, -1, -1)]
        cur = closes[-1]
        ma20 = sum(closes) / 20.0
        bias = (cur - ma20) / ma20 if ma20 > 0 else 0
        if bias > 0.10 and s.mode == 'normal': s.mode = 'range'
        elif bias < 0.05 and s.mode == 'range': s.mode = 'normal'
    def _check_orders(s):
        done = [ref for ref, o in s.pending_orders.items() if o.status not in [bt.Order.Submitted, bt.Order.Accepted]]
        for ref in done: del s.pending_orders[ref]
    def _rebalance(s, target_etfs):
        for etf in list(s.current_etfs):
            if etf not in target_etfs:
                d = s.etfs.get(etf)
                if d and s.getposition(d).size > 0:
                    order = s.close(d)
                    if order: s.pending_orders[order.ref] = order
                s.current_etfs.discard(etf)
        for etf in target_etfs:
            if etf not in s.current_etfs:
                s._buy(etf)
                s.current_etfs.add(etf)
    def _buy(s, etf):
        d = s.etfs.get(etf)
        if not d: return
        p = d.close[0]
        if p <= 0: return
        cash = s.broker.getcash()
        sz = int((cash * 0.998 / len(s.current_etfs)) / p) if s.current_etfs else int((cash * 0.998) / p)
        print('  [Laplace] Buy %s: price=%.3f, cash=%.2f, size=%d' % (etf, p, cash, sz))
        if sz > 0:
            order = s.buy(d, size=sz)
            if order: s.pending_orders[order.ref] = order
    def notify_order(s, order):
        if order.status in [bt.Order.Completed]:
            if order.isbuy():
                print('  BUY EXECUTED: %s, price=%.3f, size=%d, value=%.2f' % (order.data._name, order.executed.price, order.executed.size, order.executed.value))
            elif order.issell():
                print('  SELL EXECUTED: %s, price=%.3f, size=%d, value=%.2f' % (order.data._name, order.executed.price, order.executed.size, order.executed.value))
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            print('  ORDER FAILED: %s, status=%d' % (order.data._name, order.status))


def run(strategy_cls, label, pool, fd, td, cash=100000.0, **kwargs):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(strategy_cls, **kwargs)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0001)
    loaded = 0
    for etf in pool:
        df = load_etf(etf, fd, td)
        if df is None: continue
        data = bt.feeds.PandasData(
            dataname=df, name=etf,
            fromdate=pd.Timestamp(fd), todate=pd.Timestamp(td))
        cerebro.adddata(data)
        loaded += 1
    print('\n[%s] Loaded %d ETFs' % (label, loaded))
    if loaded < 2:
        print('[%s] Not enough data, skipped' % label)
        return None
    add_an(cerebro)
    strat = cerebro.run()[0]
    show(strat, label, cash)
    return strat


if __name__ == '__main__':
    fd = datetime(2023, 1, 1)
    td = datetime(2026, 5, 21)
    print('=' * 60)
    print('  Sanma vs Laplace - 3-Year Backtest Comparison')
    print('  Period: 2023-01-01 ~ 2026-05-21 (3.38 years)')
    print('=' * 60)
    run(Sanma, 'Strategy A: Sanma (25 ETFs, Top3, short momentum)', SANMA_ETFs, fd, td)
    run(Laplace, 'Strategy B: Laplace (32 ETFs, Juquan original)', LAPLACE_ETFs, fd, td)
    print('\n' + '=' * 60)
    print('  Summary')
    print('=' * 60)
    print('  Sanma:   25 ETFs, short momentum(10+60), Top3, no drop filter')
    print('  Laplace:  32 ETFs (Juquan), dual filter+range mode, defense=511220')
    print('=' * 60)
