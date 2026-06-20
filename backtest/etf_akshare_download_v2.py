"""
用akshare重新下载172 ETF池数据 - 带长延迟和重试
"""
import time, sys
from pathlib import Path
import pandas as pd

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
    '511880',
]

def try_akshare(code, retries=3, delay=8):
    """Download single ETF with retries"""
    import akshare as ak
    for attempt in range(retries):
        try:
            if attempt > 0:
                wait = delay * (attempt + 1)
                print(f'  重试{attempt+1}/{retries} (等{wait}s)...', end=' ', flush=True)
                time.sleep(wait)
            
            df = ak.fund_etf_hist_em(
                symbol=code, period='daily',
                start_date='20210101', end_date='20260620',
                adjust='qfq'
            )
            if df is not None and len(df) > 0:
                return df
        except Exception as e:
            if attempt == retries - 1:
                return None
    return None

if __name__ == '__main__':
    success = 0; fail_list = []
    total = len(ETF_POOL)
    
    print(f'akshare下载 ({total}只, 8s间隔, 3次重试)')
    print('=' * 60)
    
    for i, code in enumerate(ETF_POOL):
        print(f'[{i+1}/{total}] {code}...', end=' ', flush=True)
        
        df = try_akshare(code)
        
        if df is None or len(df) == 0:
            print('全部失败')
            fail_list.append(code)
            continue
        
        # 标准化列名
        col_map = {}
        for c in df.columns:
            cl = str(c)
            if '日期' in cl: col_map[c] = 'date'
            elif '开盘' in cl: col_map[c] = 'open'
            elif '收盘' in cl: col_map[c] = 'close'
            elif '最高' in cl: col_map[c] = 'high'
            elif '最低' in cl: col_map[c] = 'low'
            elif '成交量' in cl: col_map[c] = 'volume'
        df = df.rename(columns=col_map)
        
        if 'date' not in df.columns or 'close' not in df.columns:
            print(f'列缺失')
            fail_list.append(code)
            continue
        
        keep = [c for c in ['date','open','close','high','low','volume'] if c in df.columns]
        df = df[keep]
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # 检查精度
        sample = str(df['close'].iloc[-1])
        prec = len(sample.split('.')[-1]) if '.' in sample else 0
        
        fp = DATA_DIR / f'{code}.csv'
        df.to_csv(fp, index=False)
        success += 1
        print(f'OK ({len(df)}行, {prec}位精度, {df["date"].iloc[0]}~{df["date"].iloc[-1]})')
        sys.stdout.flush()
        
        time.sleep(8)
    
    print(f'\n完成: 成功{success}/{total}')
    if fail_list:
        print(f'失败: {",".join(fail_list)}')
