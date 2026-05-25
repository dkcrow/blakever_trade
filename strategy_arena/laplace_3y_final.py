"""
Laplace Strategy 3-Year Backtest - Simplified Version
No Chinese characters, no emojis, pure ASCII
"""
import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'
START_DATE = '2023-05-24'
END_DATE = '2026-05-24'

ETF_POOL = [
    '518880', '159980', '159985', '501018', '161226',
    '159981', '513100', '159509', '513290', '513500',
    '159529', '513400', '513520', '513030', '513080',
    '513310', '513730', '159792', '513130', '513050',
    '159920', '513690', '510300', '510500', '510050',
    '510210', '159915', '588080', '512100', '563360',
    '563300', '512890', '159967', '512040', '159201',
    '511380', '511010', '511220'
]

ETF_NAMES = {
    '518880': 'Gold', '159980': 'Metal', '159985': 'Soybean', '501018': 'Oil', '161226': 'Silver',
    '159981': 'Energy', '513100': 'Nasdaq', '159509': 'NasdaqTech', '513290': 'NasdaqBio', '513500': 'SP500',
    '159529': 'SPConsume', '513400': 'DowJones', '513520': 'Nikkei', '513030': 'DAX', '513080': 'CAC40',
    '513310': 'KOSDAQ', '513730': 'ASEAN', '159792': 'HKInternet', '513130': 'HSTECH', '513050': 'ChinaNet',
    '159920': 'HSI', '513690': 'HKDiv', '510300': 'CSI300', '510500': 'CSI500', '510050': 'SSE50',
    '510210': 'SSEIdx', '159915': 'ChiNext', '588080': 'STAR50', '512100': 'CSI1000', '563360': 'A500',
    '563300': 'CSI2000', '512890': 'DivLowVol', '159967': 'GEM', '512040': 'Value100', '159201': 'FreeCash',
    '511380': 'Convertible', '511010': 'TBond', '511220': 'Municipal'
}

print("=" * 60)
print("Laplace Strategy 3-Year Backtest")
print("=" * 60)

# Load data
etf_data = {}
for etf in ETF_POOL:
    for subdir in ['etf', 'etf_qixing']:
        csv_path = f"{BASE_DIR}\\{subdir}\\{etf}.csv"
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
            df = df.sort_index()
            df = df[df.index >= START_DATE]
            if len(df) > 50:
                etf_data[etf] = df
                break
        except:
            continue

print(f"Loaded {len(etf_data)} ETFs")

all_dates = sorted(set.union(*[set(df.index) for df in etf_data.values()]))
all_dates = [d for d in all_dates if d <= pd.Timestamp(END_DATE)]
print(f"Trading Days: {len(all_dates)}")
print(f"Date Range: {all_dates[0].date()} ~ {all_dates[-1].date()}")

# Momentum calculation
def calc_momentum(prices, short=25):
    if len(prices) < short + 1:
        return None
    recent = prices[-(short+1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    try:
        slope, _ = np.polyfit(x, y, 1, w=weights)
    except:
        return None
    ann_ret = np.exp(slope * 250) - 1
    return max(-2, min(2, ann_ret))

print("\nCalculating momentum...")

# Backtest
print("\nRunning backtest...")
positions = {}
trades = []
portfolio_values = []

for i, current_date in enumerate(all_dates):
    # Every 5 days check
    if i % 5 != 0:
        if positions:
            total = 100000
            for etf, pos in positions.items():
                if etf in etf_data and current_date in etf_data[etf].index:
                    price = etf_data[etf].loc[current_date]['close']
                    total += (100000 / len(positions)) * (price / pos['entry_price'] - 1)
            portfolio_values.append({'date': current_date, 'value': total})
        continue
    
    # Calculate scores
    scores = {}
    for etf, df in etf_data.items():
        df_up = df[df.index <= current_date]
        if len(df_up) < 50:
            continue
        prices_arr = df_up['close'].values.astype(float)
        score = calc_momentum(prices_arr)
        if score is not None:
            scores[etf] = score
    
    if not scores:
        continue
    
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_etf, top_score = ranked[0]
    
    if positions:
        current_etf = list(positions.keys())[0]
        pos = positions[current_etf]
        
        if current_date not in etf_data[current_etf].index:
            continue
        
        daily = etf_data[current_etf].loc[current_date]
        current_price = daily['close']
        low_price = daily['low']
        
        if current_price > pos['max_price']:
            pos['max_price'] = current_price
        
        entry_price = pos['entry_price']
        pnl_pct = (current_price - entry_price) / entry_price * 100
        
        stop_reason = None
        sell_price = None
        
        # Hard stop -8% (use low price)
        if low_price <= entry_price * 0.92:
            stop_reason = 'Hard Stop (-8%)'
            sell_price = entry_price * 0.92
            pnl_at_sell = (sell_price - entry_price) / entry_price * 100
        # Profit protection
        elif pnl_pct > 5 and current_price < pos['max_price'] * 0.95:
            stop_reason = 'Profit Protection'
            sell_price = current_price
            pnl_at_sell = pnl_pct
        # Switch
        elif current_etf != top_etf:
            stop_reason = 'Switch to ' + top_etf
            sell_price = current_price
            pnl_at_sell = pnl_pct
        
        if stop_reason:
            trades.append({
                'id': len(trades)+1,
                'etf': current_etf,
                'name': ETF_NAMES.get(current_etf, current_etf),
                'action': 'Sell',
                'date': current_date.strftime('%Y-%m-%d'),
                'price': round(sell_price, 3),
                'reason': stop_reason,
                'pnl_pct': round(pnl_at_sell, 1)
            })
            print(f"{current_date.date()}: Sell {current_etf} @ {sell_price:.3f} ({stop_reason}, P/L={pnl_at_sell:.1f}%)")
            positions.pop(current_etf)
            
            if top_etf in etf_data and current_date in etf_data[top_etf].index:
                entry_new = etf_data[top_etf].loc[current_date]['close']
                positions[top_etf] = {
                    'entry_price': entry_new,
                    'entry_date': current_date.strftime('%Y-%m-%d'),
                    'max_price': entry_new
                }
                trades.append({
                    'id': len(trades)+1,
                    'etf': top_etf,
                    'name': ETF_NAMES.get(top_etf, top_etf),
                    'action': 'Buy',
                    'date': current_date.strftime('%Y-%m-%d'),
                    'price': round(entry_new, 3),
                    'reason': 'Top1 (score=' + str(round(top_score, 4)) + ')',
                    'pnl_pct': None
                })
                print(f"{current_date.date()}: Buy {top_etf} @ {entry_new:.3f} (score={top_score:.4f})")
    else:
        if top_etf in etf_data and current_date in etf_data[top_etf].index:
            entry_price = etf_data[top_etf].loc[current_date]['close']
            positions[top_etf] = {
                'entry_price': entry_price,
                'entry_date': current_date.strftime('%Y-%m-%d'),
                'max_price': entry_price
            }
            trades.append({
                'id': len(trades)+1,
                'etf': top_etf,
                'name': ETF_NAMES.get(top_etf, top_etf),
                'action': 'Buy',
                'date': current_date.strftime('%Y-%m-%d'),
                'price': round(entry_price, 3),
                'reason': 'Top1 (score=' + str(round(top_score, 4)) + ')',
                'pnl_pct': None
            })
            print(f"{current_date.date()}: Buy {top_etf} @ {entry_price:.3f} (score={top_score:.4f})")
    
    # Record portfolio value
    total = 100000
    for etf, pos in positions.items():
        if etf in etf_data and current_date in etf_data[etf].index:
            price = etf_data[etf].loc[current_date]['close']
            total += (100000 / max(1, len(positions))) * (price / pos['entry_price'] - 1)
    portfolio_values.append({'date': current_date, 'value': total})

# Results
print("\n" + "="*60)
print("Backtest Results - Laplace Strategy (3 Years)")
print("="*60)

if portfolio_values:
    final_value = portfolio_values[-1]['value']
    total_return = (final_value / 100000 - 1) * 100
    years = (all_dates[-1] - all_dates[0]).days / 365.25
    annual_return = ((final_value / 100000) ** (1/years) - 1) * 100
else:
    final_value = 100000
    total_return = 0
    years = 3
    annual_return = 0

n_trades = len([t for t in trades if t['action'] == 'Sell'])
win_trades = [t for t in trades if t['action'] == 'Sell' and t['pnl_pct'] and t['pnl_pct'] > 0]
loss_trades = [t for t in trades if t['action'] == 'Sell' and t['pnl_pct'] and t['pnl_pct'] <= 0]

win_rate = len(win_trades) / n_trades * 100 if n_trades > 0 else 0
avg_win = sum(t['pnl_pct'] for t in win_trades) / len(win_trades) if win_trades else 0
avg_loss = abs(sum(t['pnl_pct'] for t in loss_trades) / len(loss_trades)) if loss_trades else 1
pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0

if portfolio_values:
    df_val = pd.DataFrame(portfolio_values)
    df_val['date'] = pd.to_datetime(df_val['date'])
    df_val.set_index('date', inplace=True)
    peak = df_val['value'].cummax()
    dd = ((df_val['value'] - peak) / peak * 100)
    max_dd = dd.min()
else:
    max_dd = 0

trades_per_year = n_trades / years

print(f"Initial Capital: $100,000")
print(f"Final Value: ${final_value:,.2f}")
print(f"Total Return: {total_return:.2f}%")
print(f"Annualized Return: {annual_return:.2f}%")
print(f"Max Drawdown: {max_dd:.2f}%")
print(f"Total Trades: {n_trades}")
print(f"Trades/Year: {trades_per_year:.1f}")
print(f"Win Rate: {win_rate:.1f}%")
print(f"P/L Ratio: {pl_ratio:.2f}")
print("="*60)

with open('laplace_trades_3y_final.json', 'w', encoding='utf-8') as f:
    json.dump({'trades': trades, 'positions': positions}, f, ensure_ascii=False, indent=2)

print("\nTrades saved: laplace_trades_3y_final.json")
print("Backtest completed!")
