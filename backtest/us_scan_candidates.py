"""扫描564只美股: 找高动量离散候选加入池"""
import numpy as np, pandas as pd
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path('data/storage/stock_data/us')
CURRENT_POOL = {'NVDA','AVGO','AMD','MU','LRCX','LITE','NFLX','GOOGL','NOW','ORCL','SNPS','EOG','NEM','CAT','GE','AMT','PANW','ZS','NET','IONQ','RKLB','SPCX'}

def calc_score(closes):
    if len(closes) < 5: return -999
    x = np.arange(len(closes)); y = np.log(closes)
    mask = ~np.isnan(y) & ~np.isinf(y); x_m = x[mask]; y_m = y[mask]
    if len(x_m) < 5: return -999
    slope = np.polyfit(x_m, y_m, 1)[0]
    ann = np.exp(slope * 250)
    fitted = slope * x_m + np.polyfit(x_m, y_m, 1)[1]
    res = y_m - fitted
    ss_res = np.sum(res**2); ss_tot = np.sum((y_m - np.mean(y_m))**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
    return ann * r2

# Sector mapping (approximate)
TECH = {'AAPL','MSFT','AMZN','META','GOOGL','GOOG','NFLX','CRM','ADBE','ORCL','NOW','SNPS','CDNS','INTU','PANW','ZS','NET','CRWD','DDOG','PLTR','SNOW','MDB','COIN','APP','ARM','AMD','NVDA','AVGO','INTC','QCOM','MRVL','TXN','MU','LRCX','AMAT','KLAC','ADI','ANET','FTNT','WDAY','TEAM','DASH','SQ','SHOP','UBER','ABNB','BKNG','PYPL','ADSK','RBLX','TTD','PINS','SNAP','SPOT','DXCM','IDXX','VRTX','REGN','BIIB','GILD','AMGN','ISRG','BSX','EW','ABT','TMO','DHR','HON','CAT','GE','RTX','LMT','BA','DE','ETN','PH','EMR','ROK','ITW','CMI','PCAR','CPRT','ODFL','UNP','CSX','NSC','FDX','UPS'}
ENERGY = {'XOM','CVX','COP','EOG','PXD','OXY','HES','FANG','DVN','CTRA','HAL','SLB','BKR','MPC','VLO','PSX','WMB','KMI','OKE','TRGP'}
MATERIALS = {'LIN','SHW','APD','ECL','FCX','NEM','GOLD','DOW','DD','NUE','STLD','VMC','MLM','CTVA'}
FINANCE = {'JPM','BAC','WFC','C','GS','MS','BLK','SCHW','BX','KKR','APO','ARES','SPGI','MCO','MSCI','ICE','CME','AXP','V','MA','COF','DFS','AIG','MET','PRU','ALL','TRV','PGR','CB','AON','MMC','AJG','BRO','WTW'}
REAL_ESTATE = {'AMT','CCI','EQIX','DLR','PLD','PSA','O','SPG','WELL','AVB','EQR','VTR','EXR','IRM'}
UTILITIES = {'NEE','DUK','SO','D','AEP','EXC','SRE','XEL','ED','PEG','ETR','AEE','CMS','DTE','WEC','LNT','AWK','ES','FE'}
CONSUMER = {'AMZN','HD','LOW','COST','WMT','TGT','DG','DLTR','TJX','ROST','NKE','LULU','SBUX','MCD','YUM','CMG','DPZ','PEP','KO','PG','CL','EL','MNST','HSY','KDP','MDLZ','KHC','GIS','SYY','KR','CLX','CHD','CAG','CPB','HRL','TSN','ADM','BG','STZ','BFB','TAP','MO','PM'}
HEALTHCARE = {'UNH','ELV','CI','CNC','HUM','CVS','MCK','CAH','COR','ABC','JNJ','PFE','MRK','ABBV','BMY','LLY','NVO','AZN'}
INDUSTRIAL = {'BA','CAT','GE','HON','MMM','RTX','LMT','GD','NOC','UPS','UNP','FDX','DE','ETN','ITW','CMI','PH','EMR','ROK','CPRT','GWW','FAST','URI','PWR','JCI','CARR','OTIS','IR','DOV','AME','HWM','TXT','LHX','TDG','HEIA','AXON'}

def get_sector(sym):
    for sector_name, sector_set in [('科技',TECH),('能源',ENERGY),('材料',MATERIALS),('金融',FINANCE),('地产',REAL_ESTATE),('公用事业',UTILITIES),('消费',CONSUMER),('医疗',HEALTHCARE),('工业',INDUSTRIAL)]:
        if sym in sector_set: return sector_name
    return '其他'

# Scan all CSVs
candidates = []
files = sorted(DATA_DIR.glob('*.csv'))
for fp in files:
    sym = fp.stem
    if sym in CURRENT_POOL: continue
    if len(sym) > 5: continue  # skip ETFs, indices
    # Skip obvious non-stocks
    if sym.startswith('^') or sym.startswith('.'): continue
    
    try:
        df = pd.read_csv(fp)
        df.columns = [c.lower() for c in df.columns]
        if 'date' not in df.columns: continue
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        
        # Must have data through at least 2026
        last_date = df.index.max()
        if last_date < pd.Timestamp('2026-06-01'): continue
        
        # Need at least 1 year of data
        d2025 = df[df.index >= '2025-01-01']
        if len(d2025) < 100: continue
        
        closes = df['close'].values
        if len(closes) < 25: continue
        
        # Score
        score = calc_score(closes[-25:])
        if score < 0.5: continue
        
        # 6-month return
        last6m = df[df.index >= (last_date - pd.Timedelta(days=180))]
        ret6m = (last6m['close'].iloc[-1] / last6m['close'].iloc[0] - 1) * 100 if len(last6m) > 1 else 0
        
        # YTD
        ytd = df[df.index >= '2026-01-01']
        ret_ytd = (ytd['close'].iloc[-1] / ytd['close'].iloc[0] - 1) * 100 if len(ytd) > 1 else 0
        
        # Annualized volatility
        daily_ret = d2025['close'].pct_change().dropna()
        vol = daily_ret.std() * np.sqrt(252) * 100 if len(daily_ret) > 0 else 0
        
        sector = get_sector(sym)
        
        candidates.append({
            'sym': sym, 'score': score, 'ret6m': ret6m, 'ret_ytd': ret_ytd,
            'vol': vol, 'sector': sector, 'rows': len(df)
        })
    except: pass

# Sort by score
candidates.sort(key=lambda x: x['score'], reverse=True)

print(f'扫描 {len(files)} 只美股, 找到 {len(candidates)} 只 score>=0.5 候选')
print()
print(f'{"代码":>6} | {"得分":>8} | {"6月%":>8} | {"YTD%":>8} | {"波动%":>7} | {"板块":<8} | {"数据":>5}')
print('-'*80)

for c in candidates[:30]:
    print(f'{c["sym"]:>6} | {c["score"]:>8.2f} | {c["ret6m"]:>+7.1f} | {c["ret_ytd"]:>+7.1f} | {c["vol"]:>7.1f} | {c["sector"]:<8} | {c["rows"]:>5}')

# Also show sector distribution
print(f'\n板块分布:')
by_sector = defaultdict(list)
for c in candidates:
    by_sector[c['sector']].append(c['sym'])
for s in sorted(by_sector.keys(), key=lambda k: -len(by_sector[k])):
    syms = by_sector[s]
    print(f'  {s}: {len(syms)}只 — {",".join(syms[:8])}')
