"""
诊断脚本：检查 159509 在邮件中的真实数据
"""
import re
import os

# 1. 先运行主脚本，获取最新数据
print("1. 直接查询腾讯API 159509:")
import urllib.request
url = 'http://qt.gtimg.cn/q=sz159509'
with urllib.request.urlopen(url, timeout=3) as r:
    data = r.read().decode('gbk')
    parts = data.split('~')
    price_api = float(parts[3])
    yc_api = float(parts[4])  # 今开价
    pct_api = ((price_api - yc_api) / yc_api) * 100
    print(f"   API: price={price_api}, yc={yc_api}, pct={pct_api:.2f}%")
    print(f"   期望: price=2.661, pct=-1.55%")
    print()

# 2. 检查 last_email.html
print("2. 检查 last_email.html:")
if os.path.exists('last_email.html'):
    with open('last_email.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找 159509 的行
    idx = content.find('159509')
    if idx != -1:
        snippet = content[idx:idx+500]
        print("   159509 附近的 HTML:")
        print(snippet[:300])
        print()
        
        # 提取价格
        price_match = re.search(r'(\d+\.\d{3})', snippet)
        if price_match:
            price_html = float(price_match.group(1))
            print(f"   HTML中的价格: {price_html}")
        
        # 提取涨跌幅
        pct_match = re.search(r'([+-]\d+\.\d{2})%', snippet)
        if pct_match:
            pct_html = float(pct_match.group(1))
            print(f"   HTML中的涨跌幅: {pct_html}%")
else:
    print("   last_email.html 不存在")

print()
print("3. 结论:")
print(f"   如果 HTML 中 price={price_api:.3f}, pct={pct_api:.2f}% → 正确")
print(f"   如果 HTML 中 price≠{price_api:.3f} → 说明发送的是旧数据")
