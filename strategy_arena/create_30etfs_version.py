#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remove 513080 and 513730 from 拉普拉斯.py, create 拉普拉斯_30etfs.py
"""

import re

src = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯.py'
dst = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_30etfs.py'

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the two ETFs
new_content = content.replace("    '513080',  # 法国ETF\n", '')
new_content = new_content.replace("    '513730',  # 东南亚ETF\n", '')

# Update ETF_POOL comment
new_content = new_content.replace(
    '# ETF池（聚宽代码映射，需在本地有对应CSV数据）',
    '# ETF池（30只，移除513080/513730因数据缺失）'
)

with open(dst, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"OK: {dst}")
print("Removed: 513080 (法国ETF), 513730 (东南亚ETF)")
print("Total ETFs: 30")
