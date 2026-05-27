"""
终极修复：对于今天没有成交的 ETF，用 CSV 的昨收价
"""
file_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到需要替换的旧代码块
old = """        # 获取实时价格和昨收价
                    api_data = tencent_prices.get(etf)
                    if api_data and isinstance(api_data, dict):
                        realtime_price = api_data['price']
                        yesterday_close = api_data['yesterday_close']
                    else:
                        realtime_price = df['close'].iloc[-1]
                        yesterday_close = realtime_price"""

# 新代码：如果 API 的 yesterday_close 等于 price，则用 CSV 的昨收价
new = """        # 获取实时价格和昨收价
                    api_data = tencent_prices.get(etf)
                    if api_data and isinstance(api_data, dict):
                        realtime_price = api_data['price']
                        api_yc = api_data['yesterday_close']
                        # 如果 API 的昨收价等于当前价（没成交），则用 CSV 的昨收价
                        if abs(api_yc - realtime_price) < 0.001:  # 两者几乎相等
                            yesterday_close = df['close'].iloc[-2] if len(df) >= 2 else realtime_price
                        else:
                            yesterday_close = api_yc
                    else:
                        realtime_price = df['close'].iloc[-1]
                        yesterday_close = realtime_price"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Ultimate fix #2 applied!")
    print("  For non-trading ETFs, use CSV yesterday_close instead of API")
else:
    print("ERROR: Could not find the old code block")
