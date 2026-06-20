"""临时调试脚本：检查报告中的总资产列"""
import re

# Check US report
html_path = 'backtest/results_us100/七星美股版_实盘报告_20260619_2117.html'
with open(html_path, encoding='utf-8') as f:
    html = f.read()

# Extract trade section
trade_start = html.find('最近20条交易记录')
if trade_start >= 0:
    trade_html = html[trade_start:trade_start+8000]
    # Find total asset column values (style color:#1F4E79)
    values = re.findall(r'color:#1F4E79[^>]*>([^<]+)', trade_html)
    print(f'US 总资产列值 (前10):')
    for v in values[:10]:
        print(f'  [{v}]')
    
    # Also find all $ values in the last column
    dollar_vals = re.findall(r'#1F4E79;\">\\$([^<]+)<', trade_html.replace('\n',''))
    if dollar_vals:
        print(f'\n美元值 (前10):')
        for v in dollar_vals[:10]:
            print(f'  ${v}')
else:
    print('US: 找不到交易记录区域')

print()

# Check 172 report
html_path_172 = 'backtest/results_172/七星172_回测报告_20260619_2118.html'
import os
if os.path.exists(html_path_172):
    with open(html_path_172, encoding='utf-8') as f:
        html = f.read()
    # Extract key metrics
    annual = re.search(r'年化收益.*?([\d.]+)%', html)
    total = re.search(r'累计收益.*?([\d.+-]+)%', html)
    dd = re.search(r'最大回撤.*?([\d.]+)%', html)
    print(f'172 报告:')
    if annual: print(f'  年化: {annual.group(1)}%')
    if total: print(f'  累计: {total.group(1)}%')
    if dd: print(f'  回撤: {dd.group(1)}%')
    
    # Check trade section for total_value
    trade_start = html.find('最近20条交易记录')
    if trade_start >= 0:
        trade_html = html[trade_start:trade_start+5000]
        vals = re.findall(r'1F4E7[^>]*>([^<]+)', trade_html)
        print(f'  总资产列值 (前5):')
        for v in vals[:5]:
            print(f'    [{v}]')
else:
    print('172 报告文件不存在')
