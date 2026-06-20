"""
用akshare重新下载172 ETF池的高精度(4位小数)日线数据
替代WeStock的2位小数数据
"""
import time, sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'etf'

ETF_POOL = [
    '518880','159980','159985','501018','161226','159981',
    '513100','159509','513290','513500','159529',
    '513400','513520','513030','513080','513310','513730',
    '159792','513130','513050','159920','513690',
    '510300','510500','510050','510210','159915',
    '588080','512100','563360','563300',
    '512890','159967','512040','159201','562500','560090',
    '511380','511010','511220',
    '511880',  # 货币基金(防御)
]

def download_with_akshare():
    import akshare as ak
    import pandas as pd
    
    success = 0; fail = 0; total = len(ETF_POOL)
    
    for i, code in enumerate(ETF_POOL):
        print(f'[{i+1}/{total}] {code}...', end=' ', flush=True)
        try:
            df = ak.fund_etf_hist_em(
                symbol=code, 
                period='daily', 
                start_date='20210101', 
                end_date='20260620', 
                adjust='qfq'  # 前复权
            )
            if df is None or len(df) == 0:
                print('无数据')
                fail += 1
                continue
            
            # 标准化列名
            col_map = {}
            for c in df.columns:
                cl = c.lower()
                if '日期' in c or 'date' in cl: col_map[c] = 'date'
                elif '开盘' in c or 'open' in cl: col_map[c] = 'open'
                elif '收盘' in c or 'close' in cl: col_map[c] = 'close'
                elif '最高' in c or 'high' in cl: col_map[c] = 'high'
                elif '最低' in c or 'low' in cl: col_map[c] = 'low'
                elif '成交量' in c or 'vol' in cl: col_map[c] = 'volume'
            df = df.rename(columns=col_map)
            
            # 确保有必要列
            if 'date' not in df.columns or 'close' not in df.columns:
                print(f'列缺失: {list(df.columns)}')
                fail += 1
                continue
            
            # 只保留标准列
            keep = [c for c in ['date','open','close','high','low','volume'] if c in df.columns]
            df = df[keep]
            
            # 排序
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            # 检查精度
            sample_close = df['close'].iloc[-1]
            precision = len(str(sample_close).split('.')[-1]) if '.' in str(sample_close) else 0
            
            # 保存
            fp = DATA_DIR / f'{code}.csv'
            df.to_csv(fp, index=False)
            success += 1
            print(f'OK ({len(df)}行, 精度{precision}位, {df["date"].iloc[0]}~{df["date"].iloc[-1]})')
            sys.stdout.flush()
            
            time.sleep(0.5)  # 控制频率
            
        except Exception as e:
            err = str(e)[:80]
            print(f'失败: {err}')
            fail += 1
            time.sleep(2)  # 失败后多等
    
    print(f'\n完成: 成功{success}/{total}, 失败{fail}')
    return success, fail

if __name__ == '__main__':
    print(f'akshare ETF数据下载 ({len(ETF_POOL)}只)')
    print(f'目标: {DATA_DIR}')
    print('=' * 60)
    s, f = download_with_akshare()
    
    if f > 0:
        print(f'\n{f}只失败, 检查精度...')
        import pandas as pd
        for code in ETF_POOL:
            fp = DATA_DIR / f'{code}.csv'
            if fp.exists():
                df = pd.read_csv(fp)
                if 'close' in df.columns:
                    sample = df['close'].iloc[-1]
                    prec = len(str(sample).split('.')[-1]) if '.' in str(sample) else 0
                    if prec < 3:
                        print(f'  {code}: 精度仅{prec}位!')
