#!/usr/bin/env python3
"""
下载 S&P 500 + Nasdaq 100 成分股历史数据
- 使用 Yahoo Finance CSV API (无需yfinance依赖绕过缓存问题)
- 输出: CSV 文件 (Date,Open,High,Low,Close,Volume)
"""

import sys, os, time, json
from pathlib import Path
from datetime import datetime, timedelta
import requests

# ================================================================
# 配置
# ================================================================
PROJECT_ROOT = Path('c:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
os.makedirs(DATA_DIR, exist_ok=True)

STALE_DAYS = 45  # 数据超过此天数视为过期

# S&P 500 + Nasdaq 100 合并目标
ALL_TARGETS = set()
SP500_TICKERS = [
    'NVDA','GOOGL','GOOG','AAPL','MSFT','AMZN','AVGO','TSLA','META','WMT',
    'MU','LLY','JPM','AMD','INTC','XOM','V','ORCL','JNJ','COST',
    'MA','CAT','CVX','NFLX','BAC','ABBV','AMAT','LRCX','PG','UNH',
    'KO','PLTR','GE','CSCO','GS','MS','HD','TXN','MRK','PM',
    'LIN','RTX','WFC','C','AXP','TMUS','ADI','IBM','VZ','MCD',
    'PEP','DELL','NEE','CRM','KLAC','AMGN','APH','STX','BA','DIS',
    'ANET','T','TJX','PANW','GILD','ISRG','CRWD','WDC','TMO','BLK',
    'ETN','QCOM','UNP','SCHW','ABT','UBER','APP','WELL','COP','PFE',
    'HON','BX','DE','VRT','LOW','BKNG','GLW','PLD','MDT','ACN',
    'CB','SPGI','DHR','LMT','SBUX','COF','PGR','VRTX','BMY','NEM',
    'PH','SYK','MO','NOW','EQIX','PWR','HCA','CME','CVS','CEG',
    'INTU','SO','ADBE','MCK','SNPS','DUK','MAR','TT','GD','BSX',
    'CDNS','FDX','WM','FCX','CMCSA','WMB','ICE','ELV','USB','JCI',
    'KKR','FTNT','MRSH','CSX','UPS','EMR','ADP','SHW','PNC','MCO',
    'CMI','HWM','AMT','MNST','MDLZ','CI','NOC','HOOD','ABNB','NKE',
    'SLB','MMM','ROST','APO','RCL','ITW','HLT','GM','REGN','MPC',
    'ORLY','KMI','DDOG','EOG','AEP','ECL','CTAS','CIEN','DASH','AON',
    'CL','COR','TDG','DLR','WBD','VLO','CRH','MPWR','SPG','BKR',
    'PCAR','NSC','RSG','PSX','MSI','APD','TRV','F','FIX','TFC',
    'COHR','NXPI','SRE','KEYS','TEL','TGT','O','AFL','TER','LHX',
    'OXY','OKE','AJG','COIN','ALL','AZO','D','FANG','CTVA','CARR',
    'GWW','MET','TRGP','ETR','AME','CVNA','PSA','FAST','BDX','NDAQ',
    'ADSK','EA','EXC','EW','VST','GRMN','XEL','ROK','URI','EBAY',
    'CAH','FITB','YUM','ON','ODFL','IDXX','STT','MSCI','AMP','MCHP',
    'CMG','TTWO','KR','AIG','CBRE','SATS','WAB','PYPL','A','ED',
    'JBL','DHI','VTR','HSY','CCL','EME','PEG','DAL','LYV','CCI',
    'STLD','ADM','LVS','VMC','IBKR','PRU','NUE','KDP','TPL','PCG',
    'WEC','EQT','SYY','HAL','HIG','PAYX','MLM','FISV','FIS','WDAY',
    'ACGL','WAT','FSLR','ROP','HBAN','AXON','IR','KVUE','HPE','Q',
    'UAL','KMB','TDY','CPRT','ATO','DTE','ZTS','NTRS','IRM','AEE',
    'VICI','EXR','DVN','MTB','FICO','VRSK','DOV','FE','RMD','NRG',
    'GEHC','KHC','OTIS','IQV','DXCM','EL','RJF','VRSN','CASY','DOW',
    'ARES','CNP','FOXA','EIX','PPL','BIIB','CBOE','ROL','CTSH','TPR',
    'EXPE','CINF','XYL','LYB','CFG','WRB','AVB','STZ','SYF','HUBB',
    'ES','CMS','CHTR','AWK','EQR','BRO','LITE','WSM','ULTA','FOX',
    'RF','WTW','TSN','DG','BG','KEY','PPG','SBAC','L','CPAY','NI',
    'HUM','CHD','VLTO','DRI','PHM','OMC','LH','FFIV','MRNA','CNC',
    'JBHT','CSGP','EXPD','DGX','DLTR','STE','MTD','ALB','PFG','LEN',
    'SW','CHRW','NTAP','DD','RL','SMCI','HPQ','TROW','LUV','TSCO',
    'SNA','PKG','CF','GPN','GIS','WST','LNT','EVRG','IFF','FTV',
    'AMCR','VTRS','AKAM','LII','LDOS','INCY','ESS','BR','BBY','WY',
    'NVR','PSKY','NWS','PTC','INVH','IP','NDSN','ZBH','TXT','LULU',
    'APTV','BALL','HII','GEN','KIM','IEX','HST','TKO','MAA','CDW',
    'DECK','BEN','REG','NWSA','AVY','MAS','GPC','TYL','J','HAS',
    'TRMB','PNR','TTD','APA','MKC','ALGN','DPZ','CLX','MGM','COO',
    'UDR','GL','SWK','HRL','GNRC','ERIE','GDDY','SJM','WYNN','AIZ',
    'ALLE','PNW','ZBRA','CPT','PODD','IVZ','BAX','AES','DVA','IT',
    'JKHY','RVTY','FRT','BXP','UHS','ARE','SWKS','MOS','HSIC','TECH',
    'CRL','TAP','NCLH','FDS','BLDR','AOS','CAG','EPAM','POOL','CPB',
]
NQ100_TICKERS = [
    'NVDA','GOOGL','GOOG','AAPL','MSFT','AMZN','AVGO','TSLA','META','WMT',
    'MU','AMD','INTC','ASML','COST','NFLX','AMAT','LRCX','PLTR','CSCO',
    'TXN','LIN','ARM','TMUS','ADI','PEP','KLAC','AMGN','STX','PANW',
    'GILD','ISRG','CRWD','WDC','SHOP','MRVL','QCOM','APP','HON','BKNG',
    'PDD','SBUX','VRTX','CEG','INTU','ADBE','SNPS','MAR','MELI','CDNS',
    'CMCSA','FTNT','CSX','ADP','MNST','MDLZ','ABNB','ROST','REGN','ORLY',
    'DDOG','AEP','CTAS','DASH','WBD','MPWR','BKR','PCAR','NXPI','FANG',
    'FAST','ADSK','EA','EXC','XEL','MSTR','TRI','ODFL','IDXX','CCEP',
    'MCHP','TTWO','PYPL','ALNY','KDP','PAYX','WDAY','ROP','AXON','CPRT',
    'VRSK','GEHC','KHC','DXCM','CTSH','CHTR','INSM','ZS','TEAM','CSGP',
]

ALL_TARGETS = sorted(set(SP500_TICKERS + NQ100_TICKERS))

# Yahoo Finance 下载 URL 模板
YF_URL = 'https://query1.finance.yahoo.com/v7/finance/download/{}?period1={}&period2={}&interval=1d&events=history&includeAdjustedClose=true'

# User-Agent
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Session with cookie jar
session = requests.Session()
session.headers.update(HEADERS)


def get_yahoo_cookies():
    """获取Yahoo Finance的cookie (需要先访问主页)"""
    try:
        resp = session.get('https://fc.yahoo.com/', timeout=10)
        # Try to get crumb
        resp2 = session.get('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=10)
        if resp2.status_code == 200:
            return resp2.text.strip()
    except:
        pass
    return None


def download_one(sym, start_date='2016-01-01', end_date=None, crumb=None):
    """下载单只股票数据"""
    from datetime import datetime
    import time as time_mod

    # 计算时间戳
    start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp())
    if end_date:
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp())
    else:
        end_ts = int(datetime.now().timestamp())

    url = YF_URL.format(sym, start_ts, end_ts)
    if crumb:
        url += f'&crumb={crumb}'

    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 200 and resp.text and not resp.text.startswith('{'):
            # 解析CSV
            lines = resp.text.strip().split('\n')
            if len(lines) < 2:
                return None  # 只有header

            fp = DATA_DIR / f'{sym}.csv'

            # 读取已有数据
            existing_data = set()
            if fp.exists():
                with open(fp, 'r') as f:
                    existing_lines = f.read().strip().split('\n')
                    for line in existing_lines[1:]:  # 跳过header
                        existing_data.add(line.split(',')[0] if line else '')

            # 写回
            mode = 'w' if not fp.exists() else 'a'
            with open(fp, mode, encoding='utf-8') as f:
                if mode == 'w':
                    f.write('Date,Open,High,Low,Close,Volume\n')

                new_count = 0
                for line in lines[1:]:  # 跳过header
                    date = line.split(',')[0]
                    if date not in existing_data:
                        f.write(line + '\n')
                        new_count += 1

            return new_count, len(lines) - 1

        elif resp.status_code == 429:
            return 'rate_limit', 0
        elif 'Will be right back' in resp.text:
            return 'down', 0
        else:
            return 'fail', 0

    except requests.exceptions.Timeout:
        return 'timeout', 0
    except Exception as e:
        return str(e)[:100], 0


def scan_local():
    """扫描本地文件，找出缺失或过期的"""
    import pandas as pd
    from datetime import timedelta

    stale_threshold = datetime.now() - timedelta(days=STALE_DAYS)
    target_start = pd.Timestamp('2023-06-01')

    existing_ok = []
    need_download = []

    for t in ALL_TARGETS:
        fp = DATA_DIR / f'{t}.csv'
        if not fp.exists():
            need_download.append(t)
            continue

        try:
            df = pd.read_csv(fp)
            date_col = None
            for c in df.columns:
                if c.lower() == 'date':
                    date_col = c
                    break
            if date_col is None:
                need_download.append(t)
                continue

            df[date_col] = pd.to_datetime(df[date_col])
            last_date = df[date_col].max()
            rows_3yr = (df[date_col] >= target_start).sum()

            # 过期条件: 数据太旧或近期行数不够
            if last_date < stale_threshold or rows_3yr < 400:
                need_download.append(t)
            else:
                existing_ok.append(t)
        except:
            need_download.append(t)

    return existing_ok, need_download


def main():
    print('=' * 70)
    print(f'  S&P 500 + Nasdaq 100 成分股数据下载')
    print(f'  目标: {len(ALL_TARGETS)} 只 | 数据过期阈值: {STALE_DAYS}天')
    print('=' * 70)

    # 1. 扫描
    print('\n[1/3] 扫描本地数据...')
    existing_ok, need_download = scan_local()
    print(f'  已有且OK: {len(existing_ok)} | 需下载/更新: {len(need_download)}')

    if not need_download:
        print('\n  无需下载, 全部数据就绪!')
        return

    print(f'\n  缺失/过期列表 ({len(need_download)}只):')
    for i in range(0, len(need_download), 20):
        print(f'    {", ".join(need_download[i:i+20])}')

    # 2. 获取Yahoo Finance cookie/crumb
    print(f'\n[2/3] 连接Yahoo Finance...')
    crumb = get_yahoo_cookies()
    if crumb:
        print(f'  获取crumb成功')
    else:
        print(f'  未获取crumb, 直接下载 (可能受限)')

    # 3. 下载
    print(f'\n[3/3] 开始下载 {len(need_download)} 只...')
    success = 0
    fail = []
    total_new_rows = 0

    for i, sym in enumerate(need_download):
        result, total = download_one(sym, crumb=crumb)

        if isinstance(result, int) and result >= 0:
            success += 1
            total_new_rows += result
            if (i + 1) % 20 == 0:
                print(f'  进度: {i+1}/{len(need_download)} (成功: {success}, 失败: {len(fail)})')
        elif result == 'rate_limit':
            fail.append(sym)
            print(f'  [限流] {sym}, 等待30秒...')
            time.sleep(30)
        else:
            fail.append(sym)

        # 节流
        if (i + 1) % 5 == 0:
            time.sleep(0.3)

    # 总结
    print('\n' + '=' * 70)
    print(f'  下载完成!')
    print(f'  成功: {success} 只 (新增 {total_new_rows} 行)')
    print(f'  失败: {len(fail)} 只')
    total_ok = len(existing_ok) + success
    print(f'  总计可用: {total_ok}/{len(ALL_TARGETS)} ({total_ok/len(ALL_TARGETS)*100:.1f}%)')

    if fail:
        print(f'\n  失败列表:')
        for i in range(0, len(fail), 10):
            print(f'    {", ".join(fail[i:i+10])}')
        print(f'\n  可稍后重试: python backtest/download_us_components_v2.py')

    print('=' * 70)

    return success, fail


if __name__ == '__main__':
    main()
