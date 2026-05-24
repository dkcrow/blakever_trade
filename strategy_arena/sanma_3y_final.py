"""
Sanma 7-Star US Strategy - 3-Year Backtest (Simple Version)
Directly use CSV with 'Date' column
"""
import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

START_DATE = '2023-05-24'
END_DATE = '2026-05-24'

# US stock pool
STOCK_POOL = ['NVDA', 'TSLA', 'AAPL', 'GOOG', 'AMZN', 'META', 'MSFT', 'AMD', 'INTC', 'NVDA']

BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\us'

print("=" * 60)
print("Sanma 7-Star US Strategy - 3-Year Backtest")
print("=" * 60)

# Load data with 'Date' column
price_data = {}
for symbol in STOCK_POOL:
    csv_path = f"{BASE_DIR}\\{symbol}.csv"
    try:
        df = pd.read_csv(csv_path, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        df = df[df.index >= START_DATE]
        if len(df) > 50:
            price_data[symbol] = df
            print(f"Loaded {symbol}: {len(df)} rows")
    except Exception as e:
        print(f"Skip {symbol}: {e}")
        continue

if not price_data:
    print("ERROR: No data loaded")
    exit(1)

print(f"\nTotal loaded: {len(price_data)} stocks")
all_dates = sorted(set.union(*[set(df.index) for df in price_data.values()]))
all_dates = [d for d in all_dates if d <= pd.Timestamp(END_DATE)]
print(f"Trading Days: {len(all_dates)}")
print(f"Date Range: {all_dates[0].date()} ~ {all_dates[-1].date()}")

# Momentum calculation
def calc_momentum(prices, short=20, long=60):
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
    ann_ret = max(-2, min(2, ann_ret))
    
    if len(prices) >= long + 1:
        long_closes = prices[-(long+1):]
        x_long = np.arange(len(long_closes))
        y_long = np.log(long_closes)
        w_long = np.linspace(1, 2, len(y_long))
        try:
            slope_long, _ = np.polyfit(x_long, y_long, 1, w=w_long)
            ann_ret_long = np.exp(slope_long * 250) - 1
            ann_ret_long = max(-2, min(2, ann_ret_long))
            return ann_ret * 1.0 + ann_ret_long * 0.5
        except:
            pass
    return ann_ret

print("\nRunning backtest...")

# Backtest
positions = {}  # {symbol: {'entry_price', 'entry_date', 'max_price'}}
trades = []
portfolio_values = []
MAX_POSITIONS = 2
MIN_SCORE = 0.10

for i, current_date in enumerate(all_dates):
    # Every 3 days check
    if i % 3 != 0:
        if positions:
            total = 100000
            for symbol, pos in positions.items():
                if symbol in price_data and current_date in price_data[symbol].index:
                    price = price_data[symbol].loc[current_date]['Close']
                    total += (100000 / max(1, len(positions))) * (price / pos['entry_price'] - 1)
            portfolio_values.append({'date': current_date, 'value': total})
        continue
    
    # Calculate scores
    scores = {}
    for symbol, df in price_data.items():
        df_up = df[df.index <= current_date]
        if len(df_up) < 50:
            continue
        prices_arr = df_up['Close'].values.astype(float)
        score = calc_momentum(prices_arr)
        if score is not None and score >= MIN_SCORE:
            scores[symbol] = score
    
    if not scores:
        continue
    
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top2 = [s for s, _ in ranked[:MAX_POSITIONS]]
    
    # Check existing positions
    for symbol in list(positions.keys())[:]:
        pos = positions[symbol]
        
        if symbol not in price_data or current_date not in price_data[symbol].index:
            continue
        
        current_price = price_data[symbol].loc[current_date]['Close']
        
        # Update max price
        if current_price > pos['max_price']:
            pos['max_price'] = current_price
            positions[symbol] = pos
        
        pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
        
        stop_reason = None
        sell_price = current_price
        
        # ATR stop loss (2.0x) - simplified: use 5% fixed
        if current_price <= pos['entry_price'] * 0.95:
            stop_reason = 'ATR Stop (5%)'
            sell_price = pos['entry_price'] * 0.95
            pnl_at_sell = (sell_price - pos['entry_price']) / pos['entry_price'] * 100
        
        # Hard stop -20%
        if not stop_reason and current_price <= pos['entry_price'] * 0.80:
            stop_reason = 'Hard Stop (-20%)'
            sell_price = pos['entry_price'] * 0.80
            pnl_at_sell = -20.0
        
        # Profit protection
        if not stop_reason and pnl_pct > 10 and current_price < pos['max_price'] * 0.92:
            stop_reason = 'Profit Protection'
            sell_price = current_price
            pnl_at_sell = pnl_pct
        
        # Switch: not in top2
        if not stop_reason and symbol not in top2:
            stop_reason = 'Switch (not in top2)'
            sell_price = current_price
            pnl_at_sell = pnl_pct
        
        if stop_reason:
            trades.append({
                'id': len(trades)+1,
                'symbol': symbol,
                'action': 'Sell',
                'date': current_date.strftime('%Y-%m-%d'),
                'price': round(sell_price, 2),
                'reason': stop_reason,
                'pnl_pct': round(pnl_at_sell, 1)
            })
            print(f"{current_date.date()}: Sell {symbol} @ {sell_price:.2f} ({stop_reason}, P/L={pnl_at_sell:.1f}%)")
            del positions[symbol]
    
    # Buy new positions (if < MAX_POSITIONS)
    if len(positions) < MAX_POSITIONS:
        for symbol in top2:
            if len(positions) >= MAX_POSITIONS:
                break
            if symbol in positions:
                continue
            if symbol in price_data and current_date in price_data[symbol].index:
                entry_price = price_data[symbol].loc[current_date]['Close']
                positions[symbol] = {
                    'entry_price': entry_price,
                    'entry_date': current_date.strftime('%Y-%m-%d'),
                    'max_price': entry_price
                }
                trades.append({
                    'id': len(trades)+1,
                    'symbol': symbol,
                    'action': 'Buy',
                    'date': current_date.strftime('%Y-%m-%d'),
                    'price': round(entry_price, 2),
                    'reason': f'Top{ranked.index((symbol, scores[symbol]))+1} (score={scores[symbol]:.4f})',
                    'pnl_pct': None
                })
                print(f"{current_date.date()}: Buy {symbol} @ {entry_price:.2f} (score={scores[symbol]:.4f})")

# Results
print("\n" + "="*60)
print("Backtest Results - Sanma 7-Star US (3 Years)")
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

# Max drawdown
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

with open('sanma_trades_3y_final.json', 'w', encoding='utf-8') as f:
    json.dump({'trades': trades, 'positions': positions}, f, ensure_ascii=False, indent=2)

print("\nTrades saved: sanma_trades_3y_final.json")
print("Backtest completed!")
