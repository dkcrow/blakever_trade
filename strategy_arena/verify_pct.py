"""
从最近发送的邮件中提取涨跌幅信息（通过查看脚本生成的HTML）
"""
import os

# 由于无法直接读取邮件，我们模拟生成HTML的前5行价格行
# 从脚本中提取关键逻辑验证

# 模拟数据（根据刚才运行的输出）
test_data = [
    {'code': '159967', 'name': '创业板成长ETF华夏', 'price': 0.838, 'yesterday_close': 0.820, 'rank': 1},
    {'code': '159509', 'name': '纳指科技ETF景顺', 'price': 1.456, 'yesterday_close': 1.450, 'rank': 2},
    {'code': '159915', 'name': '创业板ETF易方达', 'price': 4.023, 'yesterday_close': 3.846, 'rank': 3},
]

print("验证涨跌幅计算：")
print("=" * 60)
for r in test_data:
    price = r['price']
    yc = r['yesterday_close']
    pct = ((price - yc) / yc) * 100
    pct_color = '#059669' if pct >= 0 else '#dc2626'
    pct_sign = '+' if pct >= 0 else ''
    print(f"{r['name']}: {price:.3f} ({pct_sign}{pct:.2f}%)")
    print(f"  HTML: <span style=\"color:{pct_color};font-size:11px\">{pct_sign}{pct:.2f}%</span>")

print("\n" + "=" * 60)
print("结论：涨跌幅显示应该正确！")
print("如果邮件中还是显示 0.0%，可能是：")
print("1. 腾讯API返回的昨收价字段不对（要用 parts[4]）")
print("2. pct_html 变量没有正确插入到 rows_html 中")
