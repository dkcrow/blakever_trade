"""
重新生成 get_tencent_realtime_prices() 函数
"""
file_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到函数定义和结束位置
start_marker = 'def get_tencent_realtime_prices():'
end_marker = '\ndef get_rankings():'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print("ERROR: Could not find function boundaries")
    exit(1)

# 新的函数实现（正确的缩进）
new_func = '''def get_tencent_realtime_prices():
    """获取腾讯API实时价格，返回 dict: {code: {'price': x, 'yesterday_close': y}}"""
    prices = {}
    # 每次取10只
    batch_size = 10
    for i in range(0, len(ETF_POOL), batch_size):
        batch = ETF_POOL[i:i+batch_size]
        
        # 构造查询字符串
        query = ','.join([
            f'sh{code}' if code.startswith('5') or code.startswith('1') else f'sz{code}'
            for code in batch
        ])
        url = f'http://qt.gtimg.cn/q={query}'
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                data = response.read().decode('gbk')
                # 解析多只ETF数据
                for line in data.strip().split(';'):
                    if '~' in line:
                        parts = line.split('~')
                        if len(parts) > 5:
                            code = parts[2]  # 纯数字代码
                            price = float(parts[3])  # 当前价
                            yesterday_close = float(parts[5])  # 昨收价（Field 5）
                            prices[code] = {
                                'price': price,
                                'yesterday_close': yesterday_close
                            }
        except:
            pass
        time.sleep(0.1)  # 避免请求过快
    return prices

'''

# 替换
new_content = content[:start_idx] + new_func + content[end_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Function get_tencent_realtime_prices() rewritten successfully!")
print("  Now returns dict with 'price' and 'yesterday_close'")
print("  Using Field 5 for yesterday_close")
