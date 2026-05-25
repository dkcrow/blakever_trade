import os

# 策略1：七星拉普拉斯
strategy1 = '''
# =============================================================
# 策略1：七星拉普拉斯（Laplace）
# =============================================================
def strategy_laplace(close_df, top_n=1, short_window=25, long_window=250, 
                      stop_loss_pct=0.08, profit_protect_pct=0.05, cooldown_days=40):
    """七星拉普拉斯策略（动量排名+轮动）"""
    etfs = close_df.columns.tolist()
    n = len(close_df)
    dates = close_df.index
    
    scores = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    
    for etf in etfs:
        prices = close_df[etf].values
        short_scores = np.zeros(n)
        for i in range(short_window, n):
            recent = prices[max(0, i-short_window):i+1]
            if len(recent) >= 2:
                y = np.log(recent)
                x = np.arange(len(y))
                weights = np.linspace(1, 2, len(y))
                try:
                    slope, _ = np.polyfit(x, y, 1, w=weights)
                    short_scores[i] = slope * 250
                except:
                    short_scores[i] = 0
        
        long_scores = np.zeros(n)
        for i in range(long_window, n):
            long_prices = prices[max(0, i-long_window):i+1]
            if len(long_prices) >= 2:
                y = np.log(long_prices)
                x = np.arange(len(y))
                weights = np.linspace(1, 2, len(y))
                try:
                    slope, _ = np.polyfit(x, y, 1, w=weights)
                    long_scores[i] = slope * 250
                except:
                    long_scores[i] = 0
        
        scores[etf] = short_scores * 1.0 + long_scores * 0.5
        scores[etf] = scores[etf].fillna(0)
    
    ranks = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    for i in range(long_window + 1, n):
        day_scores = scores.iloc[i]
        if day_scores.isna().all():
            continue
        ranks.iloc[i] = day_scores.rank(method='first', ascending=False)
    
    entries = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    exits = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    
    holding = {etf: {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': 0} for etf in etfs}
    
    for i in range(long_window + 1, n):
        day_prices = close_df.iloc[i]
        day_low = day_prices * 0.999
        
        for etf in etfs:
            if holding[etf]['in_pos']:
                entry = holding[etf]['entry_price']
                current = day_prices[etf]
                high = holding[etf]['high_price']
                
                if current > high:
                    holding[etf]['high_price'] = current
                
                stop_price = entry * (1 - stop_loss_pct)
                if day_low[etf] <= stop_price:
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': cooldown_days}
                    continue
                
                drawdown = (high - current) / high
                if drawdown >= profit_protect_pct:
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': cooldown_days}
                    continue
                
                if holding[etf]['cooldown'] > 0:
                    holding[etf]['cooldown'] -= 1
            
            elif holding[etf]['cooldown'] > 0:
                holding[etf]['cooldown'] -= 1
        
        if i % 5 != 0:
            continue
        
        day_ranks = ranks.iloc[i]
        if day_ranks.isna().all():
            continue
        
        top_etfs = day_ranks[day_ranks <= top_n].index.tolist()
        
        for etf in etfs:
            if holding[etf]['in_pos'] and etf not in top_etfs:
                exits.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': cooldown_days}
        
        for etf in top_etfs:
            if not holding[etf]['in_pos'] and holding[etf]['cooldown'] == 0:
                entries.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': True, 'entry_price': day_prices[etf], 'high_price': day_prices[etf], 'cooldown': 0}
    
    return entries, exits, scores, ranks
'''

# 策略2：七星6+1
strategy2 = '''
# =============================================================
# 策略2：七星（6+1）策略（简化版）
# =============================================================
def strategy_qixing(close_df, top_n=1, short_window=10, long_window=60):
    """七星6+1策略（EMA动量排名）"""
    etfs = close_df.columns.tolist()
    n = len(close_df)
    
    scores = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    
    for etf in etfs:
        prices = close_df[etf].values
        ema_short = pd.Series(prices).ewm(span=short_window, adjust=False).mean().values
        ema_long = pd.Series(prices).ewm(span=long_window, adjust=False).mean().values
        
        momentum = np.zeros(n)
        for i in range(long_window, n):
            if ema_long[i] > 0:
                momentum[i] = (ema_short[i] / ema_long[i] - 1) * 100
        scores[etf] = momentum
    
    ranks = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    for i in range(long_window, n):
        day_scores = scores.iloc[i]
        if day_scores.isna().all():
            continue
        ranks.iloc[i] = day_scores.rank(method='first', ascending=False)
    
    entries = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    exits = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    holding = {etf: False for etf in etfs}
    
    for i in range(long_window + 1, n):
        day_ranks = ranks.iloc[i]
        if day_ranks.isna().all():
            continue
        
        top_etfs = day_ranks[day_ranks <= top_n].index.tolist()
        
        for etf in etfs:
            if holding[etf] and etf not in top_etfs:
                exits.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = False
        
        for etf in top_etfs:
            if not holding[etf]:
                entries.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = True
    
    return entries, exits, scores, ranks
'''

# 策略3：三马七星
strategy3 = '''
# =============================================================
# 策略3：三马七星美股版（Sanma）
# =============================================================
def strategy_sanma(close_df, top_n=2, short=20, long=60, atr_multiplier=2.0, 
                    hard_stop_pct=0.20, min_score=0.15):
    """三马七星美股版策略（动量排名+ATR止损）"""
    etfs = close_df.columns.tolist()
    n = len(close_df)
    
    scores = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    
    for etf in etfs:
        prices = close_df[etf].values
        momentum = np.zeros(n)
        for i in range(long + 1, n):
            if i >= short and i >= long:
                short_ret = (prices[i] / prices[i-short] - 1) * 100
                long_ret = (prices[i] / prices[i-long] - 1) * 100
                momentum[i] = short_ret * 1.0 + long_ret * 0.5
        scores[etf] = momentum
    
    ranks = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    for i in range(long + 1, n):
        day_scores = scores.iloc[i]
        if day_scores.isna().all():
            continue
        ranks.iloc[i] = day_scores.rank(method='first', ascending=False)
    
    entries = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    exits = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    holding = {etf: {'in_pos': False, 'entry_price': 0} for etf in etfs}
    
    for i in range(long + 2, n):
        current_prices = close_df.iloc[i]
        
        for etf in etfs:
            if holding[etf]['in_pos']:
                entry = holding[etf]['entry_price']
                current = current_prices[etf]
                if current <= entry * (1 - hard_stop_pct):
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0}
                    continue
                atr_stop = entry * (1 - atr_multiplier * 0.02)
                if current <= atr_stop:
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0}
        
        if i % 5 != 0:
            continue
        
        day_ranks = ranks.iloc[i]
        if day_ranks.isna().all():
            continue
        
        day_scores = scores.iloc[i]
        valid_etfs = day_ranks.index[day_scores >= min_score].tolist()
        top_etfs = [etf for etf in day_ranks.index if day_ranks[etf] <= top_n and etf in valid_etfs]
        
        for etf in etfs:
            if holding[etf]['in_pos'] and (etf not in top_etfs):
                exits.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': False, 'entry_price': 0}
        
        for etf in top_etfs:
            if not holding[etf]['in_pos']:
                entries.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': True, 'entry_price': current_prices[etf]}
    
    return entries, exits, scores, ranks
'''

# 回测引擎
backtest_engine = '''
# =============================================================
# 轻量级回测引擎（纯 pandas/numpy）
# =============================================================
def run_backtest(close_df, entries, exits, init_cash=100000, fees=0.0015):
    """简化的回测引擎，使用 pandas 逐行计算"""
    etfs = close_df.columns.tolist()
    n = len(close_df)
    dates = close_df.index
    
    cash = init_cash
    positions = {etf: 0.0 for etf in etfs}
    entry_prices = {etf: 0.0 for etf in etfs}
    portfolio_values = []
    all_trades = []
    
    for i in range(n):
        date = dates[i]
        day_prices = close_df.iloc[i]
        
        # 处理出场
        for etf in etfs:
            if exits.iloc[i, close_df.columns.get_loc(etf)] and positions[etf] > 0:
                sell_price = day_prices[etf]
                sell_value = positions[etf] * sell_price * (1 - fees)
                pnl = sell_value - positions[etf] * entry_prices[etf]
                pnl_pct = (sell_price / entry_prices[etf] - 1) * 100
                all_trades.append({
                    'etf': etf, 'action': 'SELL', 'date': str(date)[:10],
                    'price': sell_price, 'pnl': pnl, 'pnl_pct': pnl_pct
                })
                cash += sell_value
                positions[etf] = 0
                entry_prices[etf] = 0
        
        # 处理入场
        for etf in etfs:
            if entries.iloc[i, close_df.columns.get_loc(etf)] and cash > 0:
                n_entries = entries.iloc[i].sum()
                if n_entries == 0:
                    continue
                buy_cash = cash / max(n_entries, 1)
                buy_price = day_prices[etf]
                shares = buy_cash / buy_price / (1 + fees)
                all_trades.append({
                    'etf': etf, 'action': 'BUY', 'date': str(date)[:10],
                    'price': buy_price, 'pnl': 0, 'pnl_pct': 0
                })
                positions[etf] = shares
                entry_prices[etf] = buy_price
                cash -= buy_cash
        
        # 计算当前组合价值
        portfolio_value = cash
        for etf in etfs:
            portfolio_value += positions[etf] * day_prices[etf]
        portfolio_values.append(portfolio_value)
    
    # 计算指标
    portfolio_series = pd.Series(portfolio_values, index=dates)
    returns = portfolio_series.pct_change().dropna()
    total_return = (portfolio_values[-1] / init_cash - 1) * 100
    n_days = len(portfolio_values)
    n_years = n_days / 252
    if n_years > 0 and total_return > -100:
        annual = ((portfolio_values[-1] / init_cash) ** (1/n_years) - 1) * 100
    else:
        annual = -100
    peak = portfolio_series.expanding().max()
    drawdown = (portfolio_series - peak) / peak * 100
    max_dd = drawdown.min()
    closed_trades = [t for t in all_trades if t['action'] == 'SELL']
    if len(closed_trades) > 0:
        wins = [t for t in closed_trades if t['pnl'] > 0]
        losses = [t for t in closed_trades if t['pnl'] < 0]
        win_rate = len(wins) / len(closed_trades) * 100
        avg_win = np.mean([t['pnl'] for t in wins]) if len(wins) > 0 else 0
        avg_loss = abs(np.mean([t['pnl'] for t in losses])) if len(losses) > 0 else 1
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
    else:
        win_rate = 0
        profit_factor = 0
    
    return {
        'total_return': total_return, 'annual': annual, 'max_dd': max_dd,
        'win_rate': win_rate, 'trades': len(closed_trades),
        'profit_factor': profit_factor, 'n_years': n_years,
        'n_days': n_days, 'portfolio_values': portfolio_values, 'all_trades': all_trades
    }
'''

# 主程序
main_program = '''
# =============================================================
# 主程序：回测3个策略（近2年）
# =============================================================
if __name__ == '__main__':
    print("=" * 110)
    print("Blakever ETF 轮动回测框架 v2.0 (纯 pandas/numpy)")
    print("=" * 110)
    
    end_date = datetime.now()
    start_date = end_date.replace(year=end_date.year - 2)
    print(f"\\n回测时间范围: {start_date.date()} ~ {end_date.date()} (约2年)")
    
    # 策略1：七星拉普拉斯
    print("\\n" + "=" * 110)
    print("策略1：七星拉普拉斯（Laplace）- 38只ETF，Top1持仓")
    print("=" * 110)
    LAPLACE_ETF_POOL = [
        '518880', '159980', '159985', '501018', '161226',
        '159981', '513100', '159509', '513290', '513500',
        '159529', '513400', '513520', '513030', '513080',
        '513310', '513730', '159792', '513130', '513050',
        '159920', '513690', '510300', '510500', '510050',
        '510210', '159915', '588080', '512100', '563360',
        '563300', '512890', '159967', '512040', '159201',
        '511380', '511010', '511220'
    ]
    print("\\n[1/3] 加载数据...")
    close_laplace = load_etf_data(LAPLACE_ETF_POOL)
    close_laplace = close_laplace[start_date: end_date]
    print(f"  数据范围: {close_laplace.index[0].date()} ~ {close_laplace.index[-1].date()}, {len(close_laplace)} 天")
    print("\\n[2/3] 生成信号（拉普拉斯策略）...")
    entries_laplace, exits_laplace, scores_laplace, ranks_laplace = strategy_laplace(
        close_laplace, top_n=1, short_window=25, long_window=250)
    print(f"  入场信号总数: {entries_laplace.sum().sum()}")
    print(f"  出场信号总数: {exits_laplace.sum().sum()}")
    print("\\n[3/3] 回测中...")
    m_laplace = run_backtest(close_laplace, entries_laplace, exits_laplace)
    print(f"\\n  总收益率: {m_laplace['total_return']:.2f}%")
    print(f"  年化收益: {m_laplace['annual']:.2f}%")
    print(f"  最大回撤: {m_laplace['max_dd']:.2f}%")
    print(f"  胜率: {m_laplace['win_rate']:.2f}%")
    print(f"  交易次数: {m_laplace['trades']}")
    print(f"  盈亏比: {m_laplace['profit_factor']:.2f}")
    print(f"  回测天数: {m_laplace['n_days']} 天 ({m_laplace['n_years']:.2f}年)")
    
    # 策略2：七星6+1
    print("\\n" + "=" * 110)
    print("策略2：七星（6+1）- 7只ETF，Top1持仓")
    print("=" * 110)
    QIXING_ETF_POOL = ['159915', '513100', '159985', '518880', '501018', '161226', '511220']
    print("\\n[1/3] 加载数据...")
    close_qixing = load_etf_data(QIXING_ETF_POOL)
    close_qixing = close_qixing[start_date: end_date]
    print(f"  数据范围: {close_qixing.index[0].date()} ~ {close_qixing.index[-1].date()}, {len(close_qixing)} 天")
    print("\\n[2/3] 生成信号（七星策略）...")
    entries_qixing, exits_qixing, scores_qixing, ranks_qixing = strategy_qixing(
        close_qixing, top_n=1, short_window=10, long_window=60)
    print(f"  入场信号总数: {entries_qixing.sum().sum()}")
    print(f"  出场信号总数: {exits_qixing.sum().sum()}")
    print("\\n[3/3] 回测中...")
    m_qixing = run_backtest(close_qixing, entries_qixing, exits_qixing)
    print(f"\\n  总收益率: {m_qixing['total_return']:.2f}%")
    print(f"  年化收益: {m_qixing['annual']:.2f}%")
    print(f"  最大回撤: {m_qixing['max_dd']:.2f}%")
    print(f"  胜率: {m_qixing['win_rate']:.2f}%")
    print(f"  交易次数: {m_qixing['trades']}")
    print(f"  盈亏比: {m_qixing['profit_factor']:.2f}")
    print(f"  回测天数: {m_qixing['n_days']} 天 ({m_qixing['n_years']:.2f}年)")
    
    # 策略3：三马七星美股版
    print("\\n" + "=" * 110)
    print("策略3：三马七星美股版（Sanma）- 15只美股，Top2持仓")
    print("=" * 110)
    SANMA_ETF_POOL = ['NVDA', 'AAPL', 'TSLA', 'AMD', 'MU', 'AVGO',
        'GOOG', 'AMZN', 'KO', 'NEM', 'XOM', 'AEP', 'JPM', 'GS', 'BRK-B']
    print("\\n[1/3] 加载数据...")
    try:
        close_sanma = load_etf_data(SANMA_ETF_POOL, subdirs=['us'])
        close_sanma = close_sanma[start_date: end_date]
        print(f"  数据范围: {close_sanma.index[0].date()} ~ {close_sanma.index[-1].date()}, {len(close_sanma)} 天")
        print("\\n[2/3] 生成信号（三马七星策略）...")
        entries_sanma, exits_sanma, scores_sanma, ranks_sanma = strategy_sanma(
            close_sanma, top_n=2, short=20, long=60)
        print(f"  入场信号总数: {entries_sanma.sum().sum()}")
        print(f"  出场信号总数: {exits_sanma.sum().sum()}")
        print("\\n[3/3] 回测中...")
        m_sanma = run_backtest(close_sanma, entries_sanma, exits_sanma)
        print(f"\\n  总收益率: {m_sanma['total_return']:.2f}%")
        print(f"  年化收益: {m_sanma['annual']:.2f}%")
        print(f"  最大回撤: {m_sanma['max_dd']:.2f}%")
        print(f"  胜率: {m_sanma['win_rate']:.2f}%")
        print(f"  交易次数: {m_sanma['trades']}")
        print(f"  盈亏比: {m_sanma['profit_factor']:.2f}")
        print(f"  回测天数: {m_sanma['n_days']} 天 ({m_sanma['n_years']:.2f}年)")
    except Exception as e:
        print(f"  [ERROR] 三马七星加载失败: {e}")
        m_sanma = None
    
    # 汇总对比
    print("\\n" + "=" * 110)
    print("策略对比汇总（近2年）")
    print("=" * 110)
    header = "│{:<30}│{:>12}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
        '策略', '总收益率%', '年化收益%', '最大回撤%', '胜率%', '交易数', '盈亏比')
    sep = "├" + "─"*30 + "┼" + "─"*12 + "┼" + "─"*12 + "┼" + "─"*12 + "┼" + "─"*10 + "┼" + "─"*8 + "┼" + "─"*8 + "┤"
    footer = "└" + "─"*30 + "┴" + "─"*12 + "┴" + "─"*12 + "┴" + "─"*12 + "┴" + "─"*10 + "┴" + "─"*8 + "┴" + "─"*8 + "┘"
    print("\\n" + sep)
    print(header)
    print(sep)
    def print_row(name, m):
        if m is None:
            return "│{:<30}│{:>12}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(name, 'N/A', '-', '-', '-', '-', '-')
        return "│{:<30}│{:>11.2f}%│{:>11.2f}%│{:>11.2f}%│{:>9.2f}%│{:>8}│{:>8.2f}│".format(
            name, m['total_return'], m['annual'], m['max_dd'], m['win_rate'], m['trades'], m['profit_factor'])
    print(print_row("1. 七星拉普拉斯（Top1）", m_laplace))
    print(print_row("2. 七星6+1（Top1）", m_qixing))
    print(print_row("3. 三马七星（Top2）", m_sanma))
    print(footer)
    print("\\n" + "=" * 110)
    print("Blakever ETF 轮动回测完成（v2.0）")
    print("=" * 110)
'''

# 写入文件
with open('blakever_etf_backtest_v2.py', 'a', encoding='utf-8') as f:
    f.write(strategy1)
    f.write(strategy2)
    f.write(strategy3)
    f.write(backtest_engine)
    f.write(main_program)

print('All parts written! Size:', os.path.getsize('blakever_etf_backtest_v2.py'))
