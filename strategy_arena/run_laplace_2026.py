#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行原版拉普拉斯回测，将结果输出到文件（避免编码问题）
"""

import sys
import os

# 修改标准输出为utf-8
sys.stdout = open('laplace_2026_original.txt', 'w', encoding='utf-8')
sys.stderr = sys.stdout  # 也重定向stderr

# 直接导入并运行原脚本
# 需要先修改原脚本的 if __name__ == '__main__' 部分
# 这里直接exec原文件

with open(r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\七星拉普拉斯高斯_backtrader.py', encoding='utf-8') as f:
    code = f.read()

# 修改时间范围为2026年
code = code.replace('datetime(2016, 1, 1)', 'datetime(2026, 1, 1)')
code = code.replace('datetime(2026, 5, 1)', 'datetime(2026, 5, 20)')

# 执行修改后的代码
exec(code)

sys.stdout.close()
print("✅ 结果已保存到 laplace_2026_original.txt")
