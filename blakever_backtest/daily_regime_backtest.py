#!/usr/bin/env python3
"""
Blakever 港股/美股 日K线级别策略回测分析
============================================
使用日K线数据，按日划分市场周期，回测三种策略：
1. Blakever 对应市场策略（牛市动量/震荡市箱体/熊市做空+避险）
2. 长期持有策略（Buy & Hold）
3. EMA Crossover 策略
"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import talib
import warnings
import os
import subprocess

from vectorbt.portfolio.enums import ConflictMode

warnings.filterwarnings('ignore')


def fetch_daily_kline(symbol, limit=2000):
    """获取日K线数据"""
    cmd = f"node /data/workspace/.agent/skills/westock-data/scripts/index.js kline {symbol} --period day --limit {limit} --fq hfq"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd='/data/workspace')
    
    lines = result.stdout.strip().split('\n')
    data_lines = [l for l in lines if l.startswith('|') and not l.startswith('| date') and not l.startswith('| ---')]
    
    records = []
    for line in data_lines:
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) >= 5:
            try:
                records.append({
                    'date': pd.to_datetime(parts[0]),
                    'open': float(parts[1]),
                    'close': float(parts[2]),
                    'high': float(parts[3]),
                    'low': float(parts[4]),
                    'volume': float(parts[5]) if parts[5] != '0' else 0,
                })
            except:
                continue
    
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records).set_index('date').sort_index()
    return df


def classify_regime_daily(df, lookback=120):
    """
    使用日K线数据按日划分市场周期
    - lookback=120 约等于6个月交易日
    - sma_250 约等于1年交易日
    """
    df = df.copy()
    close = df['close'].values.astype(float)
    n = len(close)
    
    # 6个月动量
    momentum = np.zeros(n)
    for i in range(lookback, n):
        momentum[i] = (close[i] - close[i - lookback]) / close[i - lookback]
    df['momentum_6m'] = momentum
    
    # 12个月均线
    sma_250 = np.full(n, np.nan)
    for i in range(250, n):
        sma_250[i] = np.mean(close[i-250:i])
    df['sma_250'] = sma_250
    
    # 6个月波动率年化
    returns = np.zeros(n)
    for i in range(1, n):
        returns[i] = (close[i] - close[i-1]) / close[i-1]
    
    vol = np.full(n, np.nan)
    for i in range(lookback, n):
        vol[i] = np.std(returns[i-lookback:i]) * np.sqrt(252)
    df['vol_6m'] = vol
    
    # 市场定性
    regime = ['range'] * n
    for i in range(250, n):
        if not np.isnan(sma_250[i]) and not np.isnan(vol[i]):
            if momentum[i] > 0.02 and close[i] > sma_250[i] and vol[i] < 0.25:
                regime[i] = 'bull'
            elif momentum[i] < -0.02 and close[i] < sma_250[i]:
                regime[i] = 'bear'
            else:
                regime[i] = 'range'
    
    df['regime'] = regime
    return df


def backtest_regime(df, regime_type, strategy_name):
    """在指定市场周期内回测策略"""
    mask = df['regime'] == regime_type
    df_r = df[mask].copy()
    
    if len(df_r) < 30:
        return None
    
    close = pd.Series(df_r['close'].values.astype(float), index=df_r.index, dtype=float)
    high = pd.Series(df_r['high'].values.astype(float), index=df_r.index, dtype=float)
    low = pd.Series(df_r['low'].values.astype(float), index=df_r.index, dtype=float)
    
    try:
        if strategy_name == 'Blakever牛市':
            return _bull_strategy(close, high, low)
        elif strategy_name == 'Blakever震荡市':
            return _range_strategy(close, high, low)
        elif strategy_name == 'Blakever熊市':
            return _bear_strategy(close, high, low)
        elif strategy_name == '长期持有':
            return _buyhold(close)
        elif strategy_name == 'EMA Crossover':
            return _ema_cross(close)
    except Exception as e:
        print(f"  ⚠️ {strategy_name}@{regime_type} 失败: {e}")
        return None


def _bull_strategy(close, high, low):
    """牛市：EMA20/50交叉 + 3M动量确认 + ATR止损"""
    ema20 = talib.EMA(close.values, timeperiod=20)
    ema50 = talib.EMA(close.values, timeperiod=50)
    atr = talib.ATR(high.values, low.values, close.values, timeperiod=14)
    mom60 = np.zeros(len(close))
    for i in range(60, len(close)):
        mom60[i] = (close.values[i] - close.values[i-60]) / close.values[i-60]
    
    entries = np.zeros(len(close), dtype=bool)
    exits = np.zeros(len(close), dtype=bool)
    
    for i in range(1, len(close)):
        if ema20[i-1] <= ema50[i-1] and ema20[i] > ema50[i] and mom60[i] > 0:
            entries[i] = True
        elif (ema20[i-1] >= ema50[i-1] and ema20[i] < ema50[i]) or mom60[i] < -0.05:
            exits[i] = True
    
    pf = vbt.Portfolio.from_signals(
        close,
        entries=pd.Series(entries, index=close.index),
        exits=pd.Series(exits, index=close.index),
        freq='1D',
        sl_stop=0.15,
        accumulate=True,
        upon_long_conflict=ConflictMode.Exit,
        upon_short_conflict=ConflictMode.Exit
    )
    return pf


def _range_strategy(close, high, low):
    """震荡市：Bollinger Bands + RSI"""
    upper, mid, lower = talib.BBANDS(close.values, timeperiod=20, nbdevup=2, nbdevdn=2)
    rsi = talib.RSI(close.values, timeperiod=14)
    
    entries = np.zeros(len(close), dtype=bool)
    exits = np.zeros(len(close), dtype=bool)
    
    for i in range(20, len(close)):
        if close.values[i] <= lower[i] and rsi[i] < 35:
            entries[i] = True
        elif close.values[i] >= upper[i] or rsi[i] > 65:
            exits[i] = True
    
    pf = vbt.Portfolio.from_signals(
        close,
        entries=pd.Series(entries, index=close.index),
        exits=pd.Series(exits, index=close.index),
        freq='1D',
        sl_stop=0.08,
        tp_stop=0.12,
        accumulate=True,
        upon_long_conflict=ConflictMode.Exit,
        upon_short_conflict=ConflictMode.Exit
    )
    return pf


def _bear_strategy(close, high, low):
    """熊市：做空 + 避险"""
    rsi = talib.RSI(close.values, timeperiod=14)
    sma200 = talib.SMA(close.values, timeperiod=200)
    
    short_entries = np.zeros(len(close), dtype=bool)
    short_exits = np.zeros(len(close), dtype=bool)
    
    for i in range(200, len(close)):
        if rsi[i] > 60 and close.values[i] < sma200[i]:
            short_entries[i] = True
        elif rsi[i] < 35 or close.values[i] > sma200[i]:
            short_exits[i] = True
    
    pf = vbt.Portfolio.from_signals(
        close,
        short_entries=pd.Series(short_entries, index=close.index),
        short_exits=pd.Series(short_exits, index=close.index),
        freq='1D',
        sl_stop=0.10,
        tp_stop=0.15,
        accumulate=True,
        upon_long_conflict=ConflictMode.Exit,
        upon_short_conflict=ConflictMode.Exit
    )
    return pf


def _buyhold(close):
    """长期持有"""
    entries = pd.Series(False, index=close.index)
    entries.iloc[0] = True
    exits = pd.Series(False, index=close.index)
    
    pf = vbt.Portfolio.from_signals(close, entries=entries, exits=exits, freq='1D', accumulate=True)
    return pf


def _ema_cross(close):
    """EMA交叉"""
    ema20 = talib.EMA(close.values, timeperiod=20)
    ema50 = talib.EMA(close.values, timeperiod=50)
    
    entries = np.zeros(len(close), dtype=bool)
    exits = np.zeros(len(close), dtype=bool)
    
    for i in range(1, len(close)):
        if ema20[i-1] <= ema50[i-1] and ema20[i] > ema50[i]:
            entries[i] = True
        elif ema20[i-1] >= ema50[i-1] and ema20[i] < ema50[i]:
            exits[i] = True
    
    pf = vbt.Portfolio.from_signals(
        close,
        entries=pd.Series(entries, index=close.index),
        exits=pd.Series(exits, index=close.index),
        freq='1D',
        sl_stop=0.15,
        accumulate=True,
        upon_long_conflict=ConflictMode.Exit,
        upon_short_conflict=ConflictMode.Exit
    )
    return pf


def safe_float(val, default=0.0):
    if isinstance(val, (int, float, np.integer, np.floating)):
        return float(val)
    if isinstance(val, str):
        val = val.replace('%', '').replace(',', '')
        try: return float(val)
        except: return default
    return default


def extract_metrics(pf, strategy_name, regime, market):
    if pf is None:
        return None
    try:
        stats = pf.stats()
        total_return = safe_float(stats.get('Total Return [%]', 0))
        max_dd = safe_float(stats.get('Max Drawdown [%]', 0))
        sharpe = safe_float(stats.get('Sharpe Ratio', 0))
        if sharpe in (float('-inf'), float('inf')): sharpe = 0
        win_rate = safe_float(stats.get('Win Rate [%]', 0))
        pf_val = safe_float(stats.get('Profit Factor', 0))
        if pf_val == float('inf'): pf_val = 999
        trades = safe_float(stats.get('Total Trades', 0))
        avg_win = safe_float(stats.get('Avg Winning Trade [%]', 0))
        avg_loss = safe_float(stats.get('Avg Losing Trade [%]', 0))
        calmar = safe_float(stats.get('Calmar Ratio', 0))
        sortino = safe_float(stats.get('Sortino Ratio', 0))
        
        # 手动计算年化收益
        start_val = safe_float(stats.get('Start Value', 100))
        end_val = safe_float(stats.get('End Value', 100))
        period_str = str(stats.get('Period', '0 days'))
        
        # 从Period字符串提取天数
        import re
        days_match = re.search(r'(\d+)\s*days?', period_str)
        n_days = int(days_match.group(1)) if days_match else 0
        years = max(n_days / 252, 0.01)
        
        if end_val > 0 and start_val > 0 and years > 0:
            annual_return = ((end_val / start_val) ** (1 / years) - 1) * 100
        else:
            annual_return = total_return / years if years > 0 else 0
        
        return {
            'strategy': strategy_name,
            'regime': regime,
            'market': market,
            'total_return': total_return,
            'annual_return': annual_return,
            'max_drawdown': max_dd,
            'sharpe_ratio': sharpe,
            'win_rate': win_rate,
            'profit_factor': pf_val,
            'total_trades': int(trades),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'calmar_ratio': calmar,
            'sortino_ratio': sortino,
            'n_days': n_days,
        }
    except Exception as e:
        print(f"  ⚠️ 指标提取失败: {e}")
        return None


def main():
    print("=" * 80)
    print("Blakever 港股/美股 日K线级别策略回测分析")
    print("=" * 80)
    
    results = []
    
    regime_map = {
        'bull': ('牛市', 'Blakever牛市'),
        'range': ('震荡市', 'Blakever震荡市'),
        'bear': ('熊市', 'Blakever熊市'),
    }
    
    for market_name, symbol in [('港股', 'hkHSI'), ('美股', 'us.INX')]:
        print(f"\n📥 获取{market_name}日K线数据...")
        data = fetch_daily_kline(symbol, limit=2000)
        
        if data.empty or len(data) < 300:
            print(f"  ⚠️ {market_name}数据不足，跳过")
            continue
        
        print(f"  ✅ {market_name}数据：{len(data)} 天 ({data.index[0].strftime('%Y-%m-%d')} ~ {data.index[-1].strftime('%Y-%m-%d')})")
        
        # 划分市场周期
        classified = classify_regime_daily(data)
        regime_counts = classified['regime'].value_counts()
        print(f"  📊 {market_name}市场周期分布：牛市 {regime_counts.get('bull', 0)}天 / 熊市 {regime_counts.get('bear', 0)}天 / 震荡市 {regime_counts.get('range', 0)}天")
        
        # 分周期回测
        for regime_code, (regime_cn, blakever_strat) in regime_map.items():
            for strat in [blakever_strat, '长期持有', 'EMA Crossover']:
                pf = backtest_regime(classified, regime_code, strat)
                m = extract_metrics(pf, strat, regime_cn, market_name)
                if m:
                    results.append(m)
        
        # 全周期回测
        close = pd.Series(classified['close'].values.astype(float), index=classified.index, dtype=float)
        for func, name in [
            (lambda c=close: _buyhold(c), '长期持有'),
            (lambda c=close: _ema_cross(c), 'EMA Crossover'),
        ]:
            try:
                pf = func()
                m = extract_metrics(pf, name, '全周期', market_name)
                if m: results.append(m)
            except Exception as e:
                print(f"  ⚠️ {name}全周期回测失败: {e}")
    
    # ====================== 结果汇总 ======================
    print("\n" + "=" * 80)
    print("📊 日K线级别回测结果汇总")
    print("=" * 80)
    
    results_df = pd.DataFrame(results)
    if results_df.empty:
        print("⚠️ 无有效回测结果")
        return
    
    for market in ['港股', '美股']:
        print(f"\n{'─' * 90}")
        print(f"📍 {market}")
        print(f"{'─' * 90}")
        
        market_results = results_df[results_df['market'] == market]
        
        for regime in ['牛市', '震荡市', '熊市', '全周期']:
            regime_results = market_results[market_results['regime'] == regime]
            if regime_results.empty:
                continue
            
            print(f"\n  🔹 {regime}")
            print(f"  {'策略':<20} {'总收益':>8} {'年化收益':>8} {'最大回撤':>8} {'夏普':>6} {'胜率':>6} {'盈亏比':>6} {'交易数':>6} {'均赢':>7} {'均亏':>7}")
            print(f"  {'─'*88}")
            
            for _, row in regime_results.iterrows():
                print(f"  {row['strategy']:<20} {row['total_return']:>7.1f}% {row['annual_return']:>7.1f}% {row['max_drawdown']:>7.1f}% {row['sharpe_ratio']:>6.2f} {row['win_rate']:>5.1f}% {row['profit_factor']:>5.2f} {int(row['total_trades']):>6} {row['avg_win']:>6.1f}% {row['avg_loss']:>6.1f}%")
    
    # ====================== 对比分析 ======================
    print("\n" + "=" * 80)
    print("🔍 策略对比与优化建议")
    print("=" * 80)
    
    for market in ['港股', '美股']:
        print(f"\n📍 {market}：")
        market_results = results_df[results_df['market'] == market]
        
        for regime in ['牛市', '震荡市', '熊市']:
            regime_results = market_results[market_results['regime'] == regime]
            if regime_results.empty:
                continue
            
            blakever = regime_results[regime_results['strategy'].str.contains('Blakever')]
            hold = regime_results[regime_results['strategy'] == '长期持有']
            ema = regime_results[regime_results['strategy'] == 'EMA Crossover']
            
            print(f"\n  🔹 {regime}：")
            
            # Blakever vs Buy&Hold
            if not blakever.empty and not hold.empty:
                b_ret = blakever.iloc[0]['annual_return']
                h_ret = hold.iloc[0]['annual_return']
                b_dd = abs(blakever.iloc[0]['max_drawdown'])
                h_dd = abs(hold.iloc[0]['max_drawdown'])
                
                ret_diff = b_ret - h_ret
                dd_diff = h_dd - b_dd
                
                if ret_diff > 0:
                    print(f"     ✅ Blakever跑赢长期持有 {ret_diff:.1f}%/年")
                else:
                    print(f"     ⚠️ Blakever跑输长期持有 {abs(ret_diff):.1f}%/年")
                
                if dd_diff > 5:
                    print(f"     ✅ Blakever回撤更小 {dd_diff:.1f}%")
                elif dd_diff < -5:
                    print(f"     ⚠️ Blakever回撤更大 {abs(dd_diff):.1f}%")
            
            # Blakever vs EMA
            if not blakever.empty and not ema.empty:
                b_ret = blakever.iloc[0]['annual_return']
                e_ret = ema.iloc[0]['annual_return']
                diff = b_ret - e_ret
                if diff > 0:
                    print(f"     ✅ Blakever跑赢EMA Crossover {diff:.1f}%/年")
                else:
                    print(f"     ⚠️ Blakever跑输EMA Crossover {abs(diff):.1f}%/年")
            
            # 最优
            best_idx = regime_results['annual_return'].idxmax()
            best = regime_results.loc[best_idx]
            print(f"     🏆 最优策略：{best['strategy']}（年化 {best['annual_return']:.1f}%，回撤 {best['max_drawdown']:.1f}%，夏普 {best['sharpe_ratio']:.2f}）")
            
            if regime == '牛市':
                print(f"     💡 建议：牛市中80%仓位长期持有 + 20%动量增强，放宽止损至ATR×2")
            elif regime == '震荡市':
                print(f"     💡 建议：保持箱体策略核心逻辑，加入波动率自适应和成交量确认")
            elif regime == '熊市':
                print(f"     💡 建议：降低做空RSI阈值至55，增加GLD/TLT避险配置30-50%")
    
    # 保存
    output_dir = '/data/workspace/blakever_backtest'
    os.makedirs(output_dir, exist_ok=True)
    results_df.to_csv(f'{output_dir}/daily_backtest_results.csv', index=False)
    print(f"\n💾 日K线回测结果已保存至 {output_dir}/daily_backtest_results.csv")
    
    print("\n✅ 日K线级别回测分析完成！")


if __name__ == '__main__':
    main()
