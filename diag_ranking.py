#!/usr/bin/env python3
"""深度诊断：2026年1-5月策略排名逻辑"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

from strategies.etf.seven_star_laplacian import (
    SevenStarLaplacianEngine, LocalDataSource, ETF_POOL, ETF_NAMES,
    DEFAULT_PARAMS
)

ds = LocalDataSource('data/storage/stock_data/etf')
engine = SevenStarLaplacianEngine()

# 加载全部数据
all_data = ds.load_all_etfs('2025-06-01', '2026-05-20')
print('加载ETF数: %d' % len(all_data))

# 关键日期测试
test_dates = [
    '2026-03-15',   # 用户说3-5月纳指/创业板应该很高
    '2026-04-15',
    '2026-05-10',
    '2026-04-01',
]

target_codes = ['sh513100', 'sz159915', 'sh513310']  # 纳指/创业板/中韩半导体

for test_date in test_dates:
    print()
    print('='*80)
    print('  测试日期: %s' % test_date)
    print('='*80)
    
    # 获取当日价格
    prices = {}
    for code, df in all_data.items():
        mask = df.index <= pd.Timestamp(test_date)
        if mask.any():
            prices[code] = float(df.loc[mask, 'close'].iloc[-1])
    
    # 对每个目标ETF做详细分析
    print('\n--- 目标ETF详细分析 ---')
    for code in target_codes:
        if code not in all_data:
            # 查找类似代码
            found = [c for c in all_data.keys() if code[2:] in c]
            if not found:
                print('  [%s] 数据不存在!' % code)
                continue
            code = found[0]
        
        name = ETF_NAMES.get(code, code)
        df = all_data[code]
        price = prices.get(code, 0)
        
        if price <= 0:
            print('  [%s] %s | 价格=0 (无数据)' % (code, name))
            continue
        
        close_arr = df['close'].values.astype(float)
        price_series = np.append(close_arr, float(price))
        
        print('\n  >>> %s (%s) | Price=%.3f' % (name, code, price))
        
        # 逐层过滤分析
        
        # Layer 1: 盈利保护
        pp = engine.check_profit_protection(code, price, df, test_date)
        print('      Layer1 盈利保护: %s' % ('BLOCKED!' if pp else 'PASS'))
        if pp:
            mask_h = df.index < pd.Timestamp(test_date)
            hist_before = df[mask_h]
            lookback = engine.params['profit_protection_lookback']
            recent_highs = hist_before['high'].tail(lookback)
            max_h = recent_highs.max()
            dd = (max_h - price) / max_h * 100 if max_h > 0 else 0
            print('             -> %d日最高=%.3f 当前=%.3f 回撤=%.2f%% 阈值%.0f%%' % (
                lookback, max_h, price, dd, engine.params['profit_protection_threshold']*100))
        
        # Layer 2: 溢价率（跳过）
        print('      Layer2 溢价率: SKIP (无净值数据)')
        
        # Layer 3: 成交量
        current_vol = df['volume'].iloc[-1] if len(df) > 0 else 0
        _, ann_ret, _ = engine.calculate_score(price_series)
        vr = engine.check_volume_ratio(code, current_vol, df, ann_ret)
        print('      Layer3 成交量: %s | vol=%d ann_ret=%.2f%%' % ('BLOCKED' if vr else 'PASS', current_vol, ann_ret*100))
        
        # Layer 4: 短期动量
        sm_pass = not engine.check_short_momentum(price_series)
        sm_val = 0
        if len(price_series) >= 11:
            sm_val = (price_series[-1] / price_series[-11] - 1) * 100
        print('      Layer4 短期动量: %s | 10日动量=%.2f%%' % ('PASS' if sm_pass else 'BLOCKED', sm_val))
        
        # Layer 5: 得分+R2
        score, annualized_returns, r_squared = engine.calculate_score(price_series)
        score_ok = engine.params['min_score_threshold'] < score < engine.params['max_score_threshold']
        print('      Layer5 得分: Score=%.4f AnnRet=%.2f%% R2=%.4f -> %s' % (
            score, annualized_returns*100, r_squared, 
            'PASS' if score_ok else 'BLOCKED (范围%.1f~%.1f)' % (
                engine.params['min_score_threshold'], engine.params['max_score_threshold'])))
        
        # Layer 6: 近3日跌幅
        rd = not engine.check_recent_drops(price_series)
        drops = []
        if len(price_series) >= 4:
            for i in range(-3, 0):
                d = (price_series[i] - price_series[i-1]) / price_series[i-1]
                drops.append(d*100)
        print('      Layer6 近3日跌幅: %s | 日跌幅=%s' % ('PASS' if rd else 'BLOCKED', ['%.2f%%'%d for d in drops]))
        
        # Layer 7: 动态滤波器
        df_pass = engine.check_dynamic_filter(price_series, price)
        lf_slope = None
        try:
            from strategies.etf.seven_star_laplacian import laplace_filter
            lf = laplace_filter(price_series, s=engine.params['laplace_s_param'])
            lf_slope = lf[-1] - lf[-2]
        except:
            pass
        print('      Layer7 滤波器: %s | Filter=%s Laplace斜率=%s' % (
            'PASS' if df_pass else 'BLOCKED', engine.current_filter, 
            '%.6f' % lf_slope if lf_slope is not None else 'N/A'))
    
    # 完整排名
    print('\n--- 完整排名 TOP10 ---')
    ranked = engine.get_ranked_etfs(all_data, prices, test_date)
    if ranked:
        for i, m in enumerate(ranked[:10]):
            tag = ''
            if m['etf'] in target_codes or any(t in m['etf'] for t in target_codes):
                tag = ' <<< TARGET'
            print('  %2d. %-14s %-16s Score=%8.4f | AnnRet=%7.2f%% R2=%5.4f | Price=%.3f%s' % (
                i+1, m['etf'], m['etf_name'], m['score'],
                m['annualized_returns']*100, m['r_squared'],
                m['current_price'], tag))
        
        # 统计通过率
        total_in_pool = len(ETF_POOL)
        passed = len(ranked)
        print('\n  通过率: %d/%d (%.1f%%)' % (passed, total_in_pool, passed/total_in_pool*100))
        
        # 检查目标是否在池中但被过滤
        print('  --- 未通过的ETF (目标ETF标注) ---')
        for tc in target_codes:
            if tc in all_data and tc not in [m['etf'] for m in ranked]:
                print('    *** %s %s 在池中但未通过任何层!' % (tc, ETF_NAMES.get(tc,'')))
    else:
        print('  无ETF通过所有过滤!')
