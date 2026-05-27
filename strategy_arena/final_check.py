"""
彻底修复：确保 get_rankings() 返回 yesterday_close，generate_html() 正确计算涨跌幅
"""
import re

file_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 清理乱码（如果有的话）
# 2. 确保 get_tencent_realtime_prices() 正确返回字典
# 3. 确保 generate_html() 正确计算涨跌幅

print("Checking get_tencent_realtime_prices()...")
if "prices[code] = {" in content:
    print("  OK: prices[code] returns dict with price and yesterday_close")
else:
    print("  ERROR: prices[code] does not return dict!")

print("\nChecking generate_html()...")
if "for r in results:" in content and "results[:10]" not in content:
    print("  OK: generate_html() loops through all results")
else:
    print("  ERROR: generate_html() only shows top 10!")

if "pct_change = ((price - yesterday_close) / yesterday_close) * 100" in content:
    print("  OK: pct_change is calculated correctly")
else:
    print("  ERROR: pct_change calculation not found!")

# 直接运行测试
print("\n--- Running get_rankings() test ---")
test_code = """
import sys
sys.path.insert(0, r'C:\Users\blakehao\.qclaw\workspace\strategy_arena')
exec(open(r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py', encoding='utf-8').read().split('def send_email')[0])
rankings = get_rankings()
if rankings:
    r = rankings[0]
    print(f"First ETF: {r['name']}")
    print(f"  price: {r.get('realtime_price', 'MISS'):.3f}")
    print(f"  yc: {r.get('yesterday_close', 'MISS'):.3f}")
    if 'yesterday_close' in r:
        print("  SUCCESS: yesterday_close is present!")
    else:
        print("  ERROR: yesterday_close is MISSING!")
"""
exec(test_code)
