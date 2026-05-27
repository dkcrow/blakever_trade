#!/usr/bin/env python3
"""
补全缺失ETF数据 + 诊断数据完整性
"""
import sys, os, subprocess, json, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = r'c:\Users\blakehao\Desktop\blakever_trade\data\storage\stock_data\etf'
WESTOCK = r'C:\Users\blakehao\.codebuddy\skills\westock-data\scripts\index.js'

# 需要检查/补充的ETF
NEED_ETFS = {
    'sh513310': '中韩半导体ETF华泰柏瑞',
}

# 检查现有数据
print('='*60)
print('  数据完整性检查')
print('='*60)

for code, name in NEED_ETFS.items():
    fp = os.path.join(DATA_DIR, code + '.csv')
    if os.path.exists(fp):
        import pandas as pd
        df = pd.read_csv(fp)
        print('  %s (%s) | 已存在 | rows=%d | end=%s' % (name, code, len(df), str(df.iloc[-1]['date'])))
    else:
        print('  %s (%s) | 缺失! 需要下载...' % (name, code))
        
        # 用westock获取K线
        result = subprocess.run(
            ['node', WESTOCK, 'kline', code, 'day', '500'],
            capture_output=True, text=True, encoding='utf-8'
        )
        
        try:
            data = json.loads(result.stdout)
            if data.get('success') and data.get('data', {}).get('nodes'):
                nodes = data['data']['nodes']
                print('    获取到 %d 条K线数据' % len(nodes))
                
                with open(fp, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
                    for n in sorted(nodes, key=lambda x: x['date']):
                        writer.writerow([
                            n['date'][:10],
                            n['open'], n['high'], n['low'],
                            n['last'],  # westock用last作为收盘价
                            n.get('volume', 0),
                            n.get('amount', 0),
                        ])
                print('    已保存: %s' % fp)
            else:
                print('    获取失败: %s' % data.get('error', {}).get('message', result.stderr[:200]))
        except Exception as e:
            print('    解析失败: %s' % e)

# 最终验证
print()
print('='*60)
print('  所有关键ETF最终状态')
print('='*60)

key_etfs = {
    'sz159915': '创业板',
    'sh513100': '纳指',
    'sh513310': '中韩半导体',
    'sz159509': '标普消费',
    'sh518880': '黄金',
    'sz159980': '有色',
}
import pandas as pd

all_ok = True
for code, name in key_etfs.items():
    fp = os.path.join(DATA_DIR, code + '.csv')
    if not os.path.exists(fp):
        print('  [MISS] %s (%s)' % (name, code))
        all_ok = False
    else:
        df = pd.read_csv(fp)
        last = str(df.iloc[-1]['date'])
        ok_mark = '' if '2026-05' in last else ' [OLD]'
        print('  [OK%s] %s (%s) -> %s%s' % (ok_mark, name, code, last, ok_mark))
        if '2026-05' not in last:
            all_ok = False

print()
if all_ok:
    print('所有数据OK! 可以开始回测.')
else:
    print('部分数据需要更新!')
