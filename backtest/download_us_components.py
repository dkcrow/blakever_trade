#!/usr/bin/env python3
"""
下载 S&P 500 + Nasdaq 100 成分股历史数据
- 仅下载本地缺失或数据过旧的成分股
- 数据源: yfinance (Yahoo Finance)
- 输出: CSV 文件 (Date,Open,High,Low,Close,Volume)
"""

import sys, os, time
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import yfinance as yf

# ================================================================
# 配置
# ================================================================
PROJECT_ROOT = Path('c:/Users/blakehao/WorkBuddy/Claw/blakever_trade')
DATA_DIR = PROJECT_ROOT / 'data' / 'storage' / 'stock_data' / 'us'
os.makedirs(DATA_DIR, exist_ok=True)

START_DATE = '2016-01-01'   # 下载起始日
END_DATE = None              # 使用当前日期

# S&P 500 tickers (from finquota.com, 2026-06)
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

# Combine unique targets
ALL_TARGETS = sorted(set(SP500_TICKERS + NQ100_TICKERS))


def scan_local():
    """扫描本地数据，返回 (存在且OK的文件, 需要更新数据, 完全缺失)"""
    existing_ok = []
    need_update = []
    missing = []

    for t in ALL_TARGETS:
        fp = DATA_DIR / f'{t}.csv'
        if not fp.exists():
            missing.append(t)
            continue

        try:
            df = pd.read_csv(fp)
            date_col = None
            for c in df.columns:
                if c.lower() == 'date':
                    date_col = c
                    break
            if date_col is None:
                need_update.append(t)
                continue

            df[date_col] = pd.to_datetime(df[date_col])
            last_date = df[date_col].max()
            target_start = pd.Timestamp('2023-06-01')
            rows_3yr = (df[date_col] >= target_start).sum()

            # 数据在近3年内需要 >= 400行，且最新日期 >= 2026-04-01
            if rows_3yr < 400 or last_date < pd.Timestamp('2026-04-01'):
                need_update.append(t)
            else:
                existing_ok.append(t)
        except:
            need_update.append(t)

    return existing_ok, need_update, missing


def download_batch(tickers, label):
    """批量下载历史数据"""
    if not tickers:
        print(f'  [{label}] 无需下载')
        return

    print(f'  [{label}] 下载 {len(tickers)} 只...')
    success = 0
    fail = []

    # 分批下载，每批10只
    batch_size = 10
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            data = yf.download(
                ' '.join(batch),
                start=START_DATE,
                end=END_DATE,
                progress=False,
                auto_adjust=True,
                group_by='ticker'
            )

            for sym in batch:
                try:
                    if len(batch) == 1:
                        df = data.copy()
                    else:
                        if sym in data.columns.levels[0]:
                            df = data[sym].copy()
                        else:
                            fail.append(sym)
                            continue

                    if df.empty or len(df) < 20:
                        fail.append(sym)
                        continue

                    # 标准化列名
                    df = df.rename(columns={
                        'Open': 'Open', 'High': 'High',
                        'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'
                    })
                    df.index.name = 'Date'
                    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                    df = df.round(2)

                    # 如果文件已存在，合并
                    fp = DATA_DIR / f'{sym}.csv'
                    if fp.exists():
                        existing = pd.read_csv(fp)
                        existing['Date'] = pd.to_datetime(existing['Date'])
                        existing = existing.set_index('Date').sort_index()
                        # 合并：已有数据 + 新下载数据
                        combined = existing.combine_first(df)
                        # 对新日期，用新数据覆盖
                        new_dates = df.index.difference(existing.index)
                        if len(new_dates) > 0:
                            combined = pd.concat([existing, df.loc[new_dates]]).sort_index()
                        else:
                            # 没有新数据，但可能有补充数据
                            combined = existing.combine_first(df)
                    else:
                        combined = df

                    combined.to_csv(fp, float_format='%.2f')
                    success += 1

                except Exception as e:
                    fail.append(sym)

            if len(tickers) > batch_size:
                print(f'    进度: {min(i+batch_size, len(tickers))}/{len(tickers)}')

            # 防止请求过快
            time.sleep(0.5)

        except Exception as e:
            print(f'    批次失败: {e}')
            fail.extend(batch)
            time.sleep(2)

    print(f'    成功: {success}, 失败: {len(fail)}')
    if fail:
        print(f'    失败列表: {fail}')
    return fail


def main():
    print('=' * 70)
    print('  S&P 500 + Nasdaq 100 成分股数据下载')
    print(f'  目标: {len(ALL_TARGETS)} 只 | 周期: {START_DATE} ~ 最新')
    print('=' * 70)

    # 1. 扫描
    print('\n[1/3] 扫描本地数据...')
    existing_ok, need_update, missing = scan_local()
    print(f'  已有且OK: {len(existing_ok)} | 需更新: {len(need_update)} | 完全缺失: {len(missing)}')

    # 2. 下载完全缺失的
    print(f'\n[2/3] 下载完全缺失的 {len(missing)} 只...')
    failed_missing = download_batch(missing, '缺失下载')

    # 3. 更新需要刷新的
    print(f'\n[3/3] 更新数据过旧的 {len(need_update)} 只...')
    failed_update = download_batch(need_update, '增量更新')

    # 总结
    print('\n' + '=' * 70)
    print('  完成!')
    print(f'  已有OK: {len(existing_ok)}')
    print(f'  新下载成功: {len(missing) - len(failed_missing)}')
    print(f'  更新成功: {len(need_update) - len(failed_update)}')
    print(f'  失败: {len(failed_missing) + len(failed_update)}')

    total_ok = len(existing_ok) + len(missing) - len(failed_missing) + len(need_update) - len(failed_update)
    print(f'  总计可用: {total_ok}/{len(ALL_TARGETS)}')

    if failed_missing or failed_update:
        print(f'\n  失败符号需手动处理:')
        for s in failed_missing + failed_update:
            print(f'    {s}')

    print('=' * 70)


if __name__ == '__main__':
    main()
