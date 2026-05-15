#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股排行榜近3年回测 & v4评分重排序
- 对A股排行榜TOP10策略逐一回测近3年(2023-04-28~2026-04-28)
- 使用标准strategy_ranker.py v4评分体系
- 按新得分重新排序，输出对比表
"""
import sys, os, json, time
import numpy as np
import pandas as pd

# ── 路径设置 ──
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from strategy_ranker import compute_total_score as v4_score

# 近3年回测区间
START_3Y = '2023-04-28'
END_3Y = '2026-04-28'
CN_RF = 0.02


# ── 统一v4评分 ──
def compute_v4(result):
    """对回测结果计算v4标准评分"""
    if result is None:
        return None
    
    ar = result.get('annual_return', 0)
    sh = result.get('sharpe', 0)
    dd = result.get('max_drawdown', 0)
    pf = result.get('profit_factor', 1)
    wr = result.get('win_rate', 50)
    mpr = result.get('monthly_positive_rate', 0)
    
    if pf == float('inf') or pf is None:
        pf = 10
    if ar is None: ar = 0
    if sh is None: sh = 0
    if dd is None: dd = 0
    if wr is None: wr = 0
    if mpr is None: mpr = 0
    
    scores = v4_score(
        annual_return=float(ar),
        sharpe=float(sh),
        max_drawdown=float(dd),
        profit_factor=float(pf),
        win_rate=float(wr),
        cross_period_robust=False,
        survivorship_bias=True,
        monthly_positive_rate=float(mpr),
    )
    return scores


# ── 1. 七星策略（#1,#2）──
def backtest_qixing():
    """七星高照A股近3年回测"""
    from qixing_cross_market import (
        qixing_rotation_backtest, load_market_pool,
        CN_BIG_POOL, CN_DIR, FEES_RATE,
    )
    cn_data, loaded, missing = load_market_pool(CN_BIG_POOL, CN_DIR)
    if not cn_data:
        return None
    safe = '511880_XSHG'
    if safe not in cn_data:
        safe = list(cn_data.keys())[-1]
    
    result = qixing_rotation_backtest(
        price_data=cn_data,
        safe_asset=safe,
        start_date=START_3Y,
        end_date=END_3Y,
        fees_rate=FEES_RATE,
        market_label='A股',
    )
    return result


# ── 2. 五福闹新春（#4）──
def backtest_wufu():
    """五福闹新春v3.5近3年回测"""
    sys.path.insert(0, '/data/workspace/back_trader_stocks/cn_backtest')
    from wufu_v35_backtest import BacktestEngine, batch_fetch_etf_data, ALL_CN_ETFS
    
    etf_data = batch_fetch_etf_data(ALL_CN_ETFS, limit=1300)
    if not etf_data:
        return None
    
    engine = BacktestEngine(etf_data)
    metrics = engine.run(pd.Timestamp(START_3Y), pd.Timestamp(END_3Y))
    
    if metrics is None:
        return None
    
    # 转换为统一格式
    return {
        'annual_return': metrics.get('annual_return', 0),
        'sharpe': metrics.get('sharpe', 0),
        'max_drawdown': metrics.get('max_drawdown', 0),
        'profit_factor': metrics.get('profit_factor', 1),
        'win_rate': metrics.get('win_rate', 50),
        'monthly_positive_rate': metrics.get('monthly_positive_rate', 0),
        'avg_trades_per_year': metrics.get('annual_trades', 0),
        'total_return': metrics.get('total_return', 0),
    }


# ── 3. 内置策略（GEM/全天候/双重动量/ROA/搅屎棍/组合） ──
def backtest_builtin(strategy_func, kwargs):
    """使用cross_regime_scheduler的向量化回测引擎"""
    from cross_regime_scheduler import (
        load_all_market_data, run_backtest_vec,
        get_vec_strategy_func,
    )
    
    all_market_data = load_all_market_data()
    cn_etf_data = all_market_data.get('CN_ETF', {})
    if not cn_etf_data:
        return None
    
    cn_close_dict = {sym: df['Close'] for sym, df in cn_etf_data.items()}
    cp = pd.DataFrame(cn_close_dict).sort_index().loc[START_3Y:END_3Y]
    if cp.empty or len(cp) < 50:
        return None
    
    vec_func = get_vec_strategy_func(strategy_func)
    holding = vec_func(cp, **kwargs)
    result = run_backtest_vec(cp, holding, START_3Y, END_3Y, CN_RF, 'CN')
    return result


# ── 4. 聚宽子策略本地回测 ──
def backtest_jq_sub(strategy_key):
    """聚宽子策略A股近3年回测"""
    try:
        sys.path.insert(0, '/data/workspace/strategy_arena')
        from backtest_jq_64178_v6 import direct_cn_backtest
        result = direct_cn_backtest(strategy_key, START_3Y, END_3Y)
        return result
    except Exception as e:
        print(f"    聚宽策略回测失败: {e}")
        return None


def main():
    print("=" * 90)
    print("  🇨🇳 A股排行榜近3年回测 & v4评分重排序")
    print(f"  区间: {START_3Y} ~ {END_3Y}")
    print("=" * 90)
    
    # 加载排行榜
    lb_path = os.path.join(BASE, 'leaderboard_cross_regime_cn.json')
    with open(lb_path) as f:
        leaderboard = json.load(f)
    
    # 提取原始排名信息
    orig_info = {}
    for s in leaderboard:
        name = s.get('strategy_name', '?')
        orig_info[name] = {
            'total_score': s.get('total_score', 0),
            'annual_return': s.get('annual_return', 0),
            'grade': s.get('grade', '-'),
        }
    
    # 按原始排名顺序
    orig_sorted = sorted(leaderboard, key=lambda x: x.get('total_score', 0), reverse=True)
    
    print(f"\n📋 排行榜策略数: {len(orig_sorted)}")
    for i, s in enumerate(orig_sorted):
        print(f"  #{i+1} {s['strategy_name']} ({s.get('total_score',0)}分, {s.get('grade','-')})")
    
    # 定义回测任务
    from cross_regime_scheduler import strategy_gem_rotation, strategy_dual_momentum, strategy_all_weather
    
    tasks = [
        {
            'name': '七星高照ETF轮动V1.7.2-无成交量过滤',
            'type': 'qixing',
            'func': backtest_qixing,
        },
        {
            'name': '七星高照ETF轮动V1.7.2-大池完整版',
            'type': 'qixing',  # 本地回测与无成交量过滤版相同
            'func': backtest_qixing,
        },
        {
            'name': '简单ROA策略_高夏普ETF轮动',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_dual_momentum,
                {'lookback_months': 1, 'buffer_days': 0, 'abs_momentum_threshold': 0},
            ),
        },
        {
            'name': '五福闹新春v3.5 ETF动量策略',
            'type': 'wufu',
            'func': backtest_wufu,
        },
        {
            'name': '搅屎棍策略_小盘价值缓冲池轮动',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_dual_momentum,
                {'lookback_months': 1, 'buffer_days': 0, 'abs_momentum_threshold': 0},
            ),
        },
        {
            'name': 'GEM5资产_9M',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_gem_rotation,
                {'lookback_months': 9, 'buffer_days': 0,
                 'risk_assets': ['SPY', 'VEA', 'GLD', 'AGG', 'SHY'],
                 'safe_assets': ['AGG', 'SHY']},
            ),
        },
        {
            'name': '全天候_9M+7d缓冲',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_all_weather,
                {'lookback_months': 9, 'buffer_days': 7},
            ),
        },
        {
            'name': '聚宽多策略组合_v6',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_all_weather,
                {'lookback_months': 9, 'buffer_days': 3},
            ),
        },
        {
            'name': 'GEM4资产_9M+3d缓冲',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_gem_rotation,
                {'lookback_months': 9, 'buffer_days': 3,
                 'risk_assets': ['SPY', 'VEA', 'AGG', 'SHY'],
                 'safe_assets': ['AGG', 'SHY']},
            ),
        },
        {
            'name': '双重动量_9M_阈值0%+3d缓冲',
            'type': 'builtin',
            'func': lambda: backtest_builtin(
                strategy_dual_momentum,
                {'lookback_months': 9, 'buffer_days': 3, 'abs_momentum_threshold': 0},
            ),
        },
    ]
    
    # 逐一回测
    results = []
    for i, task in enumerate(tasks):
        orig = orig_info.get(task['name'], {})
        orig_score = orig.get('total_score', 0)
        orig_ar = orig.get('annual_return', 0)
        orig_grade = orig.get('grade', '-')
        
        print(f"\n{'─'*80}")
        print(f"  [{i+1}/10] {task['name']}")
        print(f"  原始评分: {orig_score} ({orig_grade}) | 原始年化: {orig_ar}%")
        print(f"{'─'*80}")
        
        try:
            t0 = time.time()
            result = task['func']()
            elapsed = time.time() - t0
            
            if result is None:
                print(f"  ❌ 回测失败 (耗时{elapsed:.1f}s)")
                results.append({
                    'name': task['name'],
                    'new_score': 0,
                    'orig_score': orig_score,
                    'orig_grade': orig_grade,
                    'orig_annual': orig_ar,
                    'error': '回测返回None',
                })
                continue
            
            scores = compute_v4(result)
            if scores is None:
                print(f"  ❌ 评分失败")
                results.append({
                    'name': task['name'],
                    'new_score': 0,
                    'orig_score': orig_score,
                    'orig_grade': orig_grade,
                    'orig_annual': orig_ar,
                    'error': '评分返回None',
                })
                continue
            
            new_score = scores['total_score']
            
            print(f"  ✅ 耗时{elapsed:.1f}s")
            print(f"     年化: {result['annual_return']:+.2f}% | 夏普: {result['sharpe']:.2f} | 回撤: {result['max_drawdown']:.2f}%")
            print(f"     胜率: {result['win_rate']:.1f}% | 盈亏比: {result['profit_factor']:.2f} | 月正率: {result.get('monthly_positive_rate',0):.0%}")
            print(f"     新v4评分: {new_score:.1f} ({scores['grade']})")
            print(f"     [年化{scores['annual_return_score']:.1f} + 夏普{scores['sharpe_score']:.1f} + 回撤{scores['max_drawdown_score']:.1f} + 盈亏{scores['profit_factor_score']:.1f} + 胜率{scores['win_rate_score']:.1f} + 月稳{scores['monthly_stability_bonus']:.1f} + 偏差{scores['survivorship_penalty']:.1f}]")
            
            results.append({
                'name': task['name'],
                'new_score': new_score,
                'grade': scores['grade'],
                'annual_return': result['annual_return'],
                'sharpe': result['sharpe'],
                'max_drawdown': result['max_drawdown'],
                'win_rate': result['win_rate'],
                'profit_factor': result['profit_factor'],
                'monthly_positive_rate': result.get('monthly_positive_rate', 0),
                'annual_trades': result.get('avg_trades_per_year', result.get('annual_trades', 0)),
                'scores': scores,
                'orig_score': orig_score,
                'orig_grade': orig_grade,
                'orig_annual': orig_ar,
            })
            
        except Exception as e:
            print(f"  ❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'name': task['name'],
                'new_score': 0,
                'orig_score': orig_score,
                'orig_grade': orig_grade,
                'orig_annual': orig_ar,
                'error': str(e),
            })
    
    # 按新评分排序
    results.sort(key=lambda x: x.get('new_score', 0), reverse=True)
    
    # 输出排序结果
    print(f"\n\n{'='*120}")
    print(f"  🏆 A股排行榜 — 近3年回测 v4评分重排序")
    print(f"  区间: {START_3Y} ~ {END_3Y}")
    print(f"{'='*120}")
    print(f"{'排名':>4s} | {'策略名称':36s} | {'新评分':>7s} | {'等级':>4s} | {'年化%':>8s} | {'夏普':>6s} | {'回撤%':>7s} | {'胜率%':>6s} | {'盈亏比':>6s} | {'原评分':>7s} | {'原等级':>4s} | {'变化':>7s}")
    print('-' * 120)
    
    for i, r in enumerate(results):
        if 'error' in r:
            print(f"{i+1:>4d} | {r['name']:36s} | {'FAIL':>7s} | {'-':>4s} | {'-':>8s} | {'-':>6s} | {'-':>7s} | {'-':>6s} | {'-':>6s} | {r['orig_score']:7.1f} | {r['orig_grade']:>4s} | {'-':>7s}")
        else:
            delta = r['new_score'] - r['orig_score']
            delta_str = f"{delta:+.1f}"
            print(f"{i+1:>4d} | {r['name']:36s} | {r['new_score']:7.1f} | {r['grade']:>4s} | {r['annual_return']:8.2f} | {r['sharpe']:6.2f} | {r['max_drawdown']:7.2f} | {r['win_rate']:6.1f} | {r['profit_factor']:6.2f} | {r['orig_score']:7.1f} | {r['orig_grade']:>4s} | {delta_str:>7s}")
    
    # 关键发现总结
    print(f"\n\n{'='*80}")
    print(f"  📊 关键发现")
    print(f"{'='*80}")
    
    success = [r for r in results if 'error' not in r]
    if success:
        top = success[0]
        bottom = success[-1]
        biggest_rise = max(success, key=lambda x: x['new_score'] - x['orig_score'])
        biggest_drop = min(success, key=lambda x: x['new_score'] - x['orig_score'])
        
        print(f"  🥇 近3年最强: {top['name']} — {top['new_score']:.1f}分({top['grade']})")
        print(f"  📉 近3年最弱: {bottom['name']} — {bottom['new_score']:.1f}分({bottom['grade']})")
        print(f"  📈 评分上升最多: {biggest_rise['name']} — {biggest_rise['new_score']-biggest_rise['orig_score']:+.1f}分")
        print(f"  📉 评分下降最多: {biggest_drop['name']} — {biggest_drop['new_score']-biggest_drop['orig_score']:+.1f}分")
    
    # 保存结果（避免numpy序列化问题）
    output = {
        'backtest_period': f'{START_3Y}~{END_3Y}',
        'generated_at': pd.Timestamp.now().isoformat(),
        'rankings': [],
    }
    for i, r in enumerate(results):
        entry = {
            'rank': i + 1,
            'strategy_name': r['name'],
            'new_score': float(r.get('new_score', 0)),
            'grade': str(r.get('grade', '-')),
            'original_score': float(r.get('orig_score', 0)),
            'original_grade': str(r.get('orig_grade', '-')),
            'score_change': float(r.get('new_score', 0) - r.get('orig_score', 0)),
        }
        if 'annual_return' in r:
            entry.update({
                'annual_return': float(r['annual_return']),
                'sharpe': float(r['sharpe']),
                'max_drawdown': float(r['max_drawdown']),
                'win_rate': float(r['win_rate']),
                'profit_factor': float(r['profit_factor']),
                'monthly_positive_rate': float(r.get('monthly_positive_rate', 0)),
                'annual_trades': float(r.get('annual_trades', 0)),
            })
        if 'scores' in r:
            s = r['scores']
            entry['v4_detail'] = {k: float(v) if isinstance(v, (np.floating, np.integer)) else v for k, v in s.items()}
        output['rankings'].append(entry)
    
    out_path = os.path.join(BASE, 'cn_3y_rerank_result.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 结果已保存: {out_path}")


if __name__ == '__main__':
    main()
