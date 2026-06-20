"""
使用 WeStock Data 下载A股ETF日线数据 (5年)
策略: 先获取ETF列表, 再批量下载K线
"""
import subprocess, json, re, sys, time
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data' / 'storage' / 'stock_data' / 'etf'
DATA_DIR.mkdir(parents=True, exist_ok=True)

NPX = 'npx -y westock-data-clawhub@1.0.4'

def run_cmd(cmd, timeout=60):
    """执行命令并返回stdout"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except:
        return None

def parse_kline_output(output):
    """解析westock kline的markdown表格输出"""
    if not output or len(output) < 50:
        return None
    lines = output.strip().split('\n')
    header = None
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 跳过分隔行
        if re.match(r'^[\|\s\-:]+$', line):
            continue
        if '|' in line:
            cells = [c.strip() for c in line.split('|')]
            cells = [c for c in cells if c]  # 去空
            if not header and any(k in str(cells) for k in ['Date', 'Open', 'Close', 'date']):
                header = cells
            elif header and len(cells) >= 4:
                rows.append(cells)
    if not rows or not header:
        return None
    return header, rows

def get_exchange_prefix(code):
    c = code[0]
    if c in ('5', '6'):
        return 'sh'
    return 'sz'

# ================================================================
print("=" * 70)
print("WeStock Data A股ETF批量下载")
print("=" * 70)
sys.stdout.flush()

# Step 1: 获取热门ETF列表
print("\nStep 1: 获取ETF列表...")
sys.stdout.flush()

# 使用 search 获取ETF, 或直接用已知的ETF代码范围
# A股ETF代码范围 (精准):
# 上海: 510xxx, 511xxx, 512xxx, 513xxx, 515xxx, 516xxx, 517xxx, 518xxx, 560xxx, 562xxx, 563xxx, 588xxx, 520xxx
# 深圳: 159xxx, 161xxx

# 生成所有可能的ETF代码 (精准范围, 不暴力穷举)
etf_codes = set()

# 从本地已有文件获取
for f in DATA_DIR.glob('*.csv'):
    etf_codes.add(f.stem)

# 从之前scan结果获取
scan_json = DATA_DIR.parent / 'etf_172_full_scan.json'
if scan_json.exists():
    with open(scan_json) as f:
        data = json.load(f)
    for item in data.get('rankings', []):
        etf_codes.add(item['code'])

print(f"  已知ETF代码: {len(etf_codes)} 只")

# 用westock search尝试获取更多ETF
print("  通过WeStock搜索补充...")
sys.stdout.flush()
for keyword in ['ETF', '指数', '行业', '主题', '商品', '债券']:
    out = run_cmd(f'{NPX} search {keyword}', timeout=30)
    if out:
        # 从搜索结果中提取6位数字代码
        codes_found = re.findall(r'\b(\d{6})\b', out)
        for c in codes_found:
            if c.startswith(('51', '15', '16', '52', '56', '58')):
                etf_codes.add(c)

print(f"  补充后: {len(etf_codes)} 只")
sys.stdout.flush()

# Step 2: 检查哪些需要更新
need_update = []
up_to_date = 0
for code in sorted(etf_codes):
    fp = DATA_DIR / f'{code}.csv'
    if fp.exists():
        try:
            df = pd.read_csv(fp)
            if 'date' in df.columns and len(df) > 0:
                last = str(df['date'].iloc[-1]).replace('-', '')
                if last >= '20260615':
                    up_to_date += 1
                    continue
        except:
            pass
    need_update.append(code)

print(f"\n  已最新: {up_to_date} | 需更新: {len(need_update)}")
sys.stdout.flush()

# Step 3: 批量下载 (每次1只, 用kline命令)
print(f"\nStep 2: 下载K线数据...")
sys.stdout.flush()

downloaded = 0
failed = 0

for i, code in enumerate(need_update):
    prefix = get_exchange_prefix(code)
    full_code = f'{prefix}{code}'
    
    out = run_cmd(f'{NPX} kline {full_code} --period day --limit 2000 --fq qfq', timeout=45)
    result = parse_kline_output(out) if out else None
    
    if result:
        header, rows = result
        if len(rows) > 30:
            try:
                df = pd.DataFrame(rows, columns=header[:len(rows[0])])
                # 标准化列名
                rename = {}
                for c in df.columns:
                    cl = c.lower()
                    if 'date' in cl or '日期' in cl: rename[c] = 'date'
                    elif 'open' in cl or '开盘' in cl: rename[c] = 'open'
                    elif c == 'last' or 'close' in cl or '收盘' in cl: rename[c] = 'close'
                    elif 'high' in cl or '最高' in cl: rename[c] = 'high'
                    elif 'low' in cl or '最低' in cl: rename[c] = 'low'
                    elif cl == 'volume' or '成交量' in cl: rename[c] = 'volume'
                df = df.rename(columns=rename)
                cols = [c for c in ['date','open','close','high','low','volume'] if c in df.columns]
                if 'date' in cols and 'close' in cols:
                    df = df[cols]
                    for c in ['open','close','high','low','volume']:
                        if c in df.columns:
                            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',',''), errors='coerce')
                    df = df.sort_values('date').reset_index(drop=True)  # WeStock输出倒序, 改为正序
                    df.to_csv(DATA_DIR / f'{code}.csv', index=False)
                    downloaded += 1
                else:
                    failed += 1
            except:
                failed += 1
        else:
            failed += 1  # 数据太少
    else:
        failed += 1
    
    if (i + 1) % 10 == 0:
        print(f"  [{i+1}/{len(need_update)}] 下载 {downloaded} | 失败 {failed}")
        sys.stdout.flush()
    
    time.sleep(0.3)

print(f"\n完成! 下载 {downloaded} | 失败 {failed} | 已最新 {up_to_date}")
total = len(list(DATA_DIR.glob('*.csv')))
print(f"本地ETF总数: {total} 只")
sys.stdout.flush()

# Step 3: 重新运行172贡献度分析
if downloaded > 0:
    print(f"\n重新运行172贡献度分析... (已有 {total} 只ETF)")
    sys.stdout.flush()
