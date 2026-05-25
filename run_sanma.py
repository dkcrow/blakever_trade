import blakever_etf_backtest_v2 as bt
from datetime import datetime

end_date = datetime.now()
start_date = end_date.replace(year=end_date.year - 2)
print(f'回测时间: {start_date.date()} ~ {end_date.date()}')

# 三马七星
SANMA_POOL = ['NVDA', 'AAPL', 'TSLA', 'AMD', 'MU', 'AVGO', 'GOOG', 'AMZN', 'KO', 'NEM', 'XOM', 'AEP', 'JPM', 'GS', 'BRK-B']
print('\nLoading Sanma data...')
close_sanma = bt.load_etf_data(SANMA_POOL, subdirs=['us'])
close_sanma = close_sanma[start_date: end_date]
print(f'Data: {close_sanma.index[0].date()} ~ {close_sanma.index[-1].date()}, {len(close_sanma)} days')

print('\nGenerating signals...')
entries, exits, scores, ranks = bt.strategy_sanma(close_sanma, top_n=2)
print(f'Entries: {entries.sum().sum()}, Exits: {exits.sum().sum()}')

print('\nBacktesting...')
m = bt.run_backtest(close_sanma, entries, exits)
print(f'Total return: {m["total_return"]:.2f}%')
print(f'Annual: {m["annual"]:.2f}%')
print(f'Max drawdown: {m["max_dd"]:.2f}%')
print(f'Win rate: {m["win_rate"]:.2f}%')
print(f'Trades: {m["trades"]}')
print(f'Profit factor: {m["profit_factor"]:.2f}')
