"""同步缺失的ETF日线数据 — 回测前自动检查并补齐
用法: python sync_etf_data.py [--check-only] [--pool 172|qmt|all]
"""
import sys, os, warnings, time, argparse
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(r'C:\Users\blakehao\WorkBuddy\Claw\blakever_trade\data\storage\stock_data\etf')

def get_all_pools(pool_name='all'):
    """获取需要检查的ETF池"""
    from strategies.etf.seven_star_base import ETF_POOL as P172
    from reporting.generate_qmt_report import QMT_POOL as PQMT
    pools = {}
    if pool_name in ('172', 'all'):
        pools['172'] = P172
    if pool_name in ('qmt', 'all'):
        pools['qmt'] = PQMT
    return pools

def check_gaps(target_date='2026-06-02'):
    """检查所有ETF数据缺口，返回 {code: (last_date, gap_days)}"""
    target = pd.Timestamp(target_date)
    gaps = {}
    all_codes = set()
    for name, pool in get_all_pools('all').items():
        all_codes.update(pool)

    for code in sorted(all_codes):
        raw = code[2:] if (code.startswith('sh') or code.startswith('sz')) else code
        fp = DATA_DIR / f'{raw}.csv'
        if not fp.exists():
            gaps[code] = ('MISSING', -1)
            continue
        try:
            df = pd.read_csv(fp)
            last = pd.to_datetime(df['date']).max()
            gap = (target - last).days
            if gap > 1:
                gaps[code] = (last.strftime('%Y-%m-%d'), gap)
        except:
            gaps[code] = ('ERROR', -1)
    return gaps

def download_missing(codes, end_date='20260602'):
    """通过新浪财经API批量下载缺失数据"""
    import requests, json, re
    
    updated = 0
    failed = 0
    total = len(codes)
    
    for idx, code in enumerate(sorted(codes)):
        raw = code[2:] if (code.startswith('sh') or code.startswith('sz')) else code
        market = 'sh' if code.startswith('sh') else 'sz'
        fp = DATA_DIR / f'{raw}.csv'
        
        # 新浪API (日线, 最多返回最近的数据)
        symbol = f'{market}{raw}'
        url = f'https://quotes.sina.cn/cn/api/jsonp_v2.php/data/CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=50'
        
        try:
            r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            text = r.text
            m = re.search(r'\((.*)\)', text, re.DOTALL)
            if not m:
                failed += 1
                time.sleep(0.3)
                continue
            data = json.loads(m.group(1))
            if not data or len(data) == 0:
                failed += 1
                time.sleep(0.3)
                continue
            
            # 转换为DataFrame
            rows = []
            for bar in data:
                rows.append({
                    'date': bar['day'],
                    'open': float(bar['open']),
                    'high': float(bar['high']),
                    'low': float(bar['low']),
                    'close': float(bar['close']),
                    'volume': int(float(bar['volume']))
                })
            df_new = pd.DataFrame(rows)
            df_new['date'] = pd.to_datetime(df_new['date'])
            
            # 合并已有数据
            if fp.exists():
                df_old = pd.read_csv(fp)
                df_old['date'] = pd.to_datetime(df_old['date'])
                merged = pd.concat([df_old, df_new]).drop_duplicates(subset='date').sort_values('date')
                merged = merged[['date','open','high','low','close','volume']].dropna(subset=['close'])
            else:
                merged = df_new[['date','open','high','low','close','volume']].dropna(subset=['close'])
            
            merged.to_csv(fp, index=False)
            updated += 1
            
        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f'  FAIL {code}: {e}')
        
        if (idx + 1) % 10 == 0:
            print(f'  进度: {idx+1}/{total}')
        time.sleep(0.3)
    
    return updated, failed

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--pool', default='all', choices=['172','qmt','all'])
    parser.add_argument('--target-date', default='2026-06-02')
    args = parser.parse_args()
    
    print(f'=== ETF数据同步检查 (目标日期: {args.target_date}) ===')
    gaps = check_gaps(args.target_date)
    
    if not gaps:
        print('所有ETF数据完整，无需同步')
        sys.exit(0)
    
    # 按池分组
    pools = get_all_pools(args.pool)
    for name, pool in pools.items():
        pool_gaps = {c: g for c, g in gaps.items() if c in pool}
        if pool_gaps:
            missing = [c for c, (d, g) in pool_gaps.items() if g < 0]
            stale = {c: (d, g) for c, (d, g) in pool_gaps.items() if g > 1}
            print(f'\n{name}池: {len(pool)}只, 缺失{len(missing)}只, 数据滞后{len(stale)}只')
            for c, (d, g) in stale.items():
                print(f'  {c}: last={d}, gap={g}天')
    
    if args.check_only:
        total_stale = sum(1 for c, (d, g) in gaps.items() if g > 1 or g < 0)
        print(f'\n需同步: {total_stale}只ETF')
        sys.exit(0)
    
    # 下载
    need_sync = [c for c, (d, g) in gaps.items() if g > 1 or g < 0]
    if not need_sync:
        print('\n无需同步')
        sys.exit(0)
    
    print(f'\n开始下载 {len(need_sync)} 只ETF缺失数据...')
    updated, failed = download_missing(need_sync, args.target_date.replace('-', ''))
    print(f'\n同步完成: 更新{updated}只, 失败{failed}只')
    
    # 二次验证
    gaps_after = check_gaps(args.target_date)
    remaining = {c: (d, g) for c, (d, g) in gaps_after.items() if g > 1 or g < 0}
    if remaining:
        print(f'\n仍有{len(remaining)}只未解决:')
        for c, (d, g) in remaining.items():
            print(f'  {c}: {d} (gap={g if g>0 else "MISSING"})')
    else:
        print('\n全部ETF数据已补齐')
