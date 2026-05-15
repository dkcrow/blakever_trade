#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照6+1 穿越牛熊排行榜入榜评估 v3
====================================
独立回测6+1策略，使用v4评分体系评估能否入A股排行榜

策略核心：
  6只投资ETF(创业板/纳指/豆粕/黄金/原油/白酒) + 1只城投ETF安全池
  加权线性回归动量(短25日+长250日) + 急跌过滤 + 周频调仓 + 安全池兜底
"""

import os, sys, json, math, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade

# ================================================================
# 6+1 ETF池定义
# ================================================================
INVEST_POOL = [
    '159915_XSHE',   # 创业板ETF
    '513100_XSHG',   # 纳指ETF
    '159985_XSHE',   # 豆粕ETF
    '518880_XSHG',   # 黄金ETF
    '501018_XSHG',   # 南方原油
'161226_XSHE',   # 白银LOF
]
SAFE_POOL = [
    '511220_XSHG',   # 城投ETF
]
CN_ETF_POOL = list(dict.fromkeys(INVEST_POOL + SAFE_POOL))
CN_SAFE = list(SAFE_POOL)

CN_ETF_NAMES = {
    '159915_XSHE': '创业板ETF',
    '513100_XSHG': '纳指ETF',
    '159985_XSHE': '豆粕ETF',
    '518880_XSHG': '黄金ETF',
    '501018_XSHG': '南方原油ETF',
'161226_XSHE': '白银LOF',
    '511220_XSHG': '城投ETF',
}

DATA_DIR = '/data/workspace/back_trader_stocks/a'
CN_RISK_FREE_RATE = 0.02  # A股无风险利率2%

# 回测区间
MAIN_START = '2019-01-01'
MAIN_END = '2024-12-31'
STRESS_START = '2015-01-01'
STRESS_END = '2018-12-31'


# ================================================================
# 数据加载
# ================================================================
def load_cn_etf_data():
    """加载6+1 ETF池数据"""
    data = {}
    for code in CN_ETF_POOL:
        filepath = os.path.join(DATA_DIR, f'{code}.csv')
        if os.path.exists(filepath):
            try:
                df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
                df = df.sort_index()
                if 'Close' in df.columns and len(df) >= 200:
                    data[code] = df
                    print(f"  ✅ {code} ({CN_ETF_NAMES.get(code, '')}): {len(df)}行")
            except Exception as e:
                print(f"  ❌ {code}: {e}")
        else:
            print(f"  ❌ {code}: 文件不存在")
    return data


# ================================================================
# 6+1 策略信号生成
# ================================================================
def qixing_61_strategy(close_prices: pd.DataFrame, **kwargs) -> pd.Series:
    """七星高照6+1 ETF轮动策略信号"""
    etf_pool = kwargs.get('etf_pool', CN_ETF_POOL)
    safe_assets = kwargs.get('safe_assets', CN_SAFE)
    short_lookback = kwargs.get('short_lookback', 25)
    long_lookback = kwargs.get('long_lookback', 250)
    drop_threshold = kwargs.get('drop_threshold', 0.95)
    long_score_cap = kwargs.get('long_score_cap', 0.5)
    short_score_cap = kwargs.get('short_score_cap', 6.0)
    rebalance_freq = kwargs.get('rebalance_freq', 'W-FRI')

    safe_in_pool = [a for a in safe_assets if a in etf_pool and a in close_prices.columns]
    default_asset = safe_in_pool[0] if safe_in_pool else (etf_pool[-1] if etf_pool else close_prices.columns[0])

    holding = pd.Series(default_asset, index=close_prices.index)

    if len(close_prices) < 15:
        return holding

    rebal_dates = close_prices.resample(rebalance_freq).last().dropna().index
    rebal_dates = rebal_dates[rebal_dates.isin(close_prices.index)]

    if len(rebal_dates) < 5:
        return holding

    pool_in_data = [a for a in etf_pool if a in close_prices.columns]

    for i, r_date in enumerate(rebal_dates):
        try:
            loc = close_prices.index.get_loc(r_date)
        except KeyError:
            continue

        actual_short = min(short_lookback, loc)
        actual_long = min(long_lookback, loc)

        if actual_long < actual_short or actual_short < 5:
            continue

        best_etf = None
        best_score = -999

        for asset in pool_in_data:
            sp = close_prices[asset].iloc[max(0, loc - actual_short):loc + 1]
            sp = sp.dropna()
            if len(sp) < 5:
                continue

            if len(sp) >= 4:
                recent = sp.iloc[-4:]
                dropped = False
                for j in range(len(recent) - 1):
                    if recent.iloc[j] > 0:
                        daily_change = recent.iloc[j + 1] / recent.iloc[j]
                        if daily_change < drop_threshold:
                            dropped = True
                            break
                if dropped:
                    continue

            y = np.log(sp.values.astype(float))
            x = np.arange(len(y), dtype=float)
            w = np.linspace(1, 2, len(y))

            try:
                coeffs = np.polyfit(x, y, 1, w=w)
                slope = coeffs[0]
            except:
                continue

            ann_return = math.exp(slope * 252) - 1
            y_pred = slope * x + coeffs[1]
            ss_res = np.sum(w * (y - y_pred) ** 2)
            y_mean = np.average(y, weights=w)
            ss_tot = np.sum(w * (y - y_mean) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 1e-10 else 0

            short_score = ann_return * r2
            if not (0 < short_score < short_score_cap):
                short_score = 0

            lp = close_prices[asset].iloc[max(0, loc - actual_long):loc + 1]
            lp = lp.dropna()
            if len(lp) < 20:
                combined = short_score
            else:
                y2 = np.log(lp.values.astype(float))
                x2 = np.arange(len(y2), dtype=float)
                w2 = np.linspace(1, 2, len(y2))

                try:
                    coeffs2 = np.polyfit(x2, y2, 1, w=w2)
                    slope2 = coeffs2[0]
                except:
                    combined = short_score
                else:
                    ann2 = math.exp(slope2 * 252) - 1
                    y2_pred = slope2 * x2 + coeffs2[1]
                    ss_res2 = np.sum(w2 * (y2 - y2_pred) ** 2)
                    y2_mean = np.average(y2, weights=w2)
                    ss_tot2 = np.sum(w2 * (y2 - y2_mean) ** 2)
                    r22 = 1 - ss_res2 / ss_tot2 if ss_tot2 > 1e-10 else 0

                    long_score = ann2 * r22
                    if not (long_score > 0 and long_score < long_score_cap):
                        long_score = 0

                    combined = short_score + long_score

            if combined > best_score:
                best_score = combined
                best_etf = asset

        if best_etf is None or best_score <= 0:
            best_etf = default_asset

        if i + 1 < len(rebal_dates):
            next_r = rebal_dates[i + 1]
            mask = (close_prices.index > r_date) & (close_prices.index <= next_r)
        else:
            mask = close_prices.index > r_date

        for idx in close_prices.index[mask]:
            holding[idx] = best_etf

    if len(holding) > 20:
        for idx in close_prices.index[:20]:
            holding[idx] = default_asset

    return holding


# ================================================================
# 回测引擎（逐日循环，含手续费）
# ================================================================
def run_backtest(close_prices, holding, start_date, end_date, risk_free_rate=0.02,
                 buy_fee=0.0003, sell_fee=0.0008, min_commission=5.0):
    """
    逐日循环回测（A股手续费）
    
    返回完整回测结果字典
    """
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    cp = close_prices[mask]
    h = holding[mask]
    
    if len(cp) < 30:
        return None
    
    # 逐日计算收益
    capital = 1_000_000.0
    cash = capital
    position = None  # {'code': str, 'shares': int, 'cost': float}
    nav_history = []
    trade_count = 0
    wins = 0
    losses = 0
    total_profit = 0
    total_loss = 0
    
    prev_holding_code = None
    daily_returns = []
    
    for date_idx in range(len(cp)):
        date = cp.index[date_idx]
        current_code = h.iloc[date_idx] if date_idx < len(h) else h.iloc[-1]
        
        # 执行换仓
        if current_code != prev_holding_code and current_code in cp.columns:
            # 卖出旧持仓
            if position is not None:
                old_price = cp.iloc[date_idx][position['code']] if position['code'] in cp.columns else 0
                if old_price > 0:
                    sell_amount = position['shares'] * old_price
                    fee = max(sell_amount * sell_fee, min_commission)
                    net = sell_amount - fee
                    cash += net
                    
                    # 计算盈亏
                    pnl = net - position['cost']
                    if pnl > 0:
                        wins += 1
                        total_profit += pnl
                    else:
                        losses += 1
                        total_loss += abs(pnl)
                    
                    trade_count += 1
                position = None
            
            # 买入新持仓
            new_price = cp.iloc[date_idx][current_code] if current_code in cp.columns else 0
            if new_price > 0 and cash > 0:
                fee = max(cash * buy_fee, min_commission)
                actual_buy = cash - fee
                shares = int(actual_buy / new_price / 100) * 100
                if shares > 0:
                    cost = shares * new_price + max(shares * new_price * buy_fee, min_commission)
                    cash -= cost
                    cash = max(cash, 0)
                    position = {'code': current_code, 'shares': shares, 'cost': cost}
                    trade_count += 1
            
            prev_holding_code = current_code
        
        # 计算当日净值
        if position is not None and position['code'] in cp.columns:
            cur_price = cp.iloc[date_idx][position['code']]
            market_value = position['shares'] * cur_price
        else:
            market_value = 0
        
        nav = cash + market_value
        nav_history.append({'date': date, 'nav': nav})
        
        if len(nav_history) > 1:
            daily_ret = (nav - nav_history[-2]['nav']) / nav_history[-2]['nav'] if nav_history[-2]['nav'] > 0 else 0
            daily_returns.append(daily_ret)
    
    if not nav_history or len(daily_returns) < 10:
        return None
    
    # 计算指标
    nav_series = pd.Series([h['nav'] for h in nav_history], 
                           index=[h['date'] for h in nav_history])
    
    final_nav = nav_series.iloc[-1]
    initial_nav = nav_series.iloc[0]
    total_return = (final_nav - initial_nav) / initial_nav
    
    # 年化收益
    years = len(nav_series) / 252
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    # 最大回撤
    cummax = nav_series.cummax()
    drawdown = (nav_series - cummax) / cummax
    max_drawdown = abs(drawdown.min()) * 100
    
    # 夏普比率
    daily_ret_series = pd.Series(daily_returns)
    if daily_ret_series.std() > 0:
        sharpe = (daily_ret_series.mean() - risk_free_rate / 252) / daily_ret_series.std() * np.sqrt(252)
    else:
        sharpe = 0
    
    # Calmar
    calmar = annual_return / (max_drawdown / 100) if max_drawdown > 0 else 0
    
    # 胜率
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    # 盈亏比
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 10.0
    
    # 年交易次数
    avg_trades = trade_count / years if years > 0 else 0
    
    # 持仓分布
    holding_counts = {}
    for code in h:
        name = CN_ETF_NAMES.get(code, code)
        holding_counts[name] = holding_counts.get(name, 0) + 1
    total_days = len(h)
    holding_distribution = {k: round(v / total_days * 100, 1) for k, v in sorted(holding_counts.items(), key=lambda x: -x[1])}
    
    # 月度正收益比例
    monthly_returns = nav_series.resample('M').last().pct_change().dropna()
    monthly_positive_rate = (monthly_returns > 0).sum() / len(monthly_returns) if len(monthly_returns) > 0 else 0
    
    return {
        'annual_return': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_drawdown, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(avg_trades, 1),
        'total_return': round(total_return * 100, 2),
        'holding_distribution': holding_distribution,
        'monthly_positive_rate': round(monthly_positive_rate, 3),
        'trade_count': trade_count,
        'nav_series': nav_series,
    }


# ================================================================
# 主流程
# ================================================================
if __name__ == '__main__':
    print("=" * 70)
    print("  🌟 七星高照6+1 穿越牛熊排行榜入榜评估 v3")
    print("=" * 70)
    
    # 1. 加载数据
    print("\n📂 加载6+1 ETF数据...")
    data = load_cn_etf_data()
    if len(data) < 5:
        print("❌ 数据不足，至少需要5只ETF")
        sys.exit(1)
    
    # 2. 构建收盘价矩阵
    close_dict = {}
    for code, df in data.items():
        if 'Close' in df.columns:
            close_dict[code] = df['Close']
    close_prices = pd.DataFrame(close_dict).sort_index()
    close_prices = close_prices.dropna(how='all').ffill().bfill()
    
    print(f"\n📊 数据范围: {close_prices.index[0].strftime('%Y-%m-%d')} ~ {close_prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"📊 ETF数量: {len(close_prices.columns)}只")
    print(f"📊 总交易日: {len(close_prices)}天")
    
    # 3. 生成策略信号
    print("\n🔄 运行七星高照6+1策略...")
    etf_pool = [c for c in CN_ETF_POOL if c in close_prices.columns]
    safe_assets = [c for c in CN_SAFE if c in close_prices.columns]
    
    holding = qixing_61_strategy(
        close_prices,
        etf_pool=etf_pool,
        safe_assets=safe_assets,
    )
    print("  ✅ 策略信号生成完成")
    
    # 4. 主回测（2019-2024）
    print(f"\n📊 主回测 ({MAIN_START} ~ {MAIN_END})...")
    main_result = run_backtest(close_prices, holding, MAIN_START, MAIN_END, CN_RISK_FREE_RATE)
    
    if main_result is None:
        print("❌ 主回测失败")
        sys.exit(1)
    
    print(f"  年化收益: {main_result['annual_return']:+.2f}%")
    print(f"  夏普比率: {main_result['sharpe']:.2f}")
    print(f"  最大回撤: {main_result['max_drawdown']:.2f}%")
    print(f"  Calmar: {main_result['calmar']:.2f}")
    print(f"  胜率: {main_result['win_rate']:.1f}%")
    print(f"  盈亏比: {main_result['profit_factor']:.2f}")
    print(f"  年交易: {main_result['avg_trades_per_year']:.1f}次")
    print(f"  月度正收益比例: {main_result['monthly_positive_rate']:.1%}")
    print(f"  持仓分布: {main_result['holding_distribution']}")
    
    # 5. 压力测试（2015-2018）
    print(f"\n📊 压力测试 ({STRESS_START} ~ {STRESS_END})...")
    stress_result = run_backtest(close_prices, holding, STRESS_START, STRESS_END, CN_RISK_FREE_RATE)
    
    if stress_result:
        print(f"  年化收益: {stress_result['annual_return']:+.2f}%")
        print(f"  最大回撤: {stress_result['max_drawdown']:.2f}%")
    else:
        stress_result = {'annual_return': 0, 'max_drawdown': 0}
        print("  ⚠️ 压力测试数据不足")
    
    # 6. v4评分
    print("\n📊 v4评分体系评估...")
    
    # 压力测试是否通过（年化>0视为通过）
    stress_passed = stress_result['annual_return'] > 0 if stress_result else False
    
    score_result = compute_total_score(
        annual_return=main_result['annual_return'],
        sharpe=main_result['sharpe'],
        max_drawdown=main_result['max_drawdown'],
        profit_factor=main_result['profit_factor'],
        win_rate=main_result['win_rate'],
        cross_period_robust=stress_passed,  # 压力测试通过才算跨周期鲁棒
        survivorship_bias=True,  # ETF固定池存在幸存者偏差
        monthly_positive_rate=main_result['monthly_positive_rate'],
    )
    
    print(f"\n  📊 评分详情:")
    for key, val in score_result.items():
        if isinstance(val, float):
            print(f"    {key}: {val:.2f}")
        else:
            print(f"    {key}: {val}")
    
    # 7. 与排行榜对比
    print("\n📊 A股穿越牛熊排行榜当前TOP10:")
    lb_path = '/data/workspace/strategy_arena/leaderboard_cross_regime_cn.json'
    if os.path.exists(lb_path):
        with open(lb_path, 'r', encoding='utf-8') as f:
            leaderboard = json.load(f)
        
        for i, entry in enumerate(leaderboard[:10]):
            name = entry.get('strategy_name', '未知')
            score = entry.get('total_score', 0)
            grade = entry.get('grade', 'F')
            annual = entry.get('annual_return', 0)
            dd = entry.get('max_drawdown', 0)
            print(f"  {i+1}. [{grade}] {score:.2f}分 | 年化{annual:+.1f}% | 回撤{dd:.1f}% | {name}")
        
        # 判断6+1能否入榜
        my_score = score_result.get('total_score', 0)
        my_grade = score_result.get('grade', 'F')
        
        if len(leaderboard) < 10:
            can_enter = my_score > 0
        else:
            min_score = leaderboard[-1].get('total_score', 0)
            can_enter = my_score > min_score
        
        print(f"\n  {'='*50}")
        print(f"  🌟 七星高照6+1 评估结论:")
        print(f"  {'='*50}")
        print(f"  评分: {my_score:.2f}分")
        print(f"  等级: {my_grade}")
        print(f"  年化: {main_result['annual_return']:+.2f}%")
        print(f"  夏普: {main_result['sharpe']:.2f}")
        print(f"  回撤: {main_result['max_drawdown']:.2f}%")
        print(f"  胜率: {main_result['win_rate']:.1f}%")
        print(f"  盈亏比: {main_result['profit_factor']:.2f}")
        print(f"  月度正收益: {main_result['monthly_positive_rate']:.1%}")
        if can_enter:
            rank = next((i+1 for i, e in enumerate(leaderboard) if my_score > e.get('total_score', 0)), len(leaderboard)+1)
            print(f"\n  ✅ 可以入榜！预计排名第{rank}名")
        else:
            min_score = leaderboard[-1].get('total_score', 0) if leaderboard else 0
            gap = min_score - my_score
            print(f"\n  ❌ 不能入榜，距离第10名差{gap:.2f}分")
        
        # 8. 自动入榜（如果评分足够）
        if can_enter and my_score > 0:
            print("\n📋 自动入榜...")
            
            strategy_entry = {
                'strategy_name': '七星高照6+1',
                'strategy_params': {
                    'lookback_days': 25,
                    'long_lookback': 250,
                    'holdings_num': 1,
                    'etf_pool': '6+1精简池(6投资+1安全)',
                    'invest_pool': '创业板/纳指/豆粕/黄金/南方原油/白酒',
                    'safe_pool': '城投ETF',
                    'filters': '急跌过滤(4日/5%)+长期动量确认',
                    'rebalance_freq': '周频(W-FRI)',
                },
                'strategy_description': '七星高照6+1 ETF轮动策略：6只精选投资ETF+1只城投ETF安全池，加权线性回归动量(短25日+长250日)+急跌过滤+周频调仓+安全池兜底',
                'strategy_type': '趋势跟踪',
                'source': '🖥️本地回测',
                'annual_return': main_result['annual_return'],
                'sharpe': main_result['sharpe'],
                'max_drawdown': main_result['max_drawdown'],
                'calmar': main_result['calmar'],
                'win_rate': main_result['win_rate'],
                'profit_factor': main_result['profit_factor'],
                'avg_trades_per_year': main_result['avg_trades_per_year'],
                'holding_distribution': main_result['holding_distribution'],
                'stress_test': {
                    'annual_return': stress_result['annual_return'],
                    'max_drawdown': stress_result['max_drawdown'],
                },
                'cross_robust': bool(True),
                'survivorship_bias_flag': bool(True),
                'pine_script_rejected': bool(False),
                'portability_score': 10,
                'market': 'CN',
                'fingerprint': 'qixing61_cn_v1',
                'total_score': my_score,
                'score_detail': score_result,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'grade': my_grade,
                'base_score': score_result.get('base_score', 0),
                'cross_period_bonus': score_result.get('cross_period_bonus', 0),
                'survivorship_penalty': score_result.get('survivorship_penalty', 0),
                'monthly_stability_bonus': score_result.get('monthly_stability_bonus', 0),
                'monthly_positive_rate': main_result['monthly_positive_rate'],
                'total_return': main_result['total_return'],
                'trade_count': main_result['trade_count'],
            }
            
            # 插入排行榜
            # 检查是否已存在同名策略
            existing_idx = next((i for i, e in enumerate(leaderboard) if e.get('strategy_name') == '七星高照6+1'), None)
            if existing_idx is not None:
                if my_score > leaderboard[existing_idx].get('total_score', 0):
                    leaderboard[existing_idx] = strategy_entry
                    print(f"  📈 更新已有条目，评分从{leaderboard[existing_idx].get('total_score', 0):.2f}→{my_score:.2f}")
                else:
                    print(f"  📊 已有条目评分更高，保持不变")
            else:
                leaderboard.append(strategy_entry)
            
            # 按评分降序排列，保留TOP10
            leaderboard.sort(key=lambda x: x.get('total_score', 0), reverse=True)
            leaderboard = leaderboard[:10]
            
            with open(lb_path, 'w', encoding='utf-8') as f:
                json.dump(leaderboard, f, ensure_ascii=False, indent=2)
            
            # 显示更新后排行
            print("\n  📊 更新后A股穿越牛熊排行榜TOP10:")
            for i, entry in enumerate(leaderboard):
                name = entry.get('strategy_name', '未知')
                score = entry.get('total_score', 0)
                grade = entry.get('grade', 'F')
                annual = entry.get('annual_return', 0)
                dd = entry.get('max_drawdown', 0)
                marker = ' 🌟' if name == '七星高照6+1' else ''
                print(f"  {i+1}. [{grade}] {score:.2f}分 | 年化{annual:+.1f}% | 回撤{dd:.1f}% | {name}{marker}")
    else:
        print("  ⚠️ 排行榜文件不存在")
    
    print("\n✅ 评估完毕！")
