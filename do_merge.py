import os

# 读取v1.py
with open('blakever_etf_backtest_v1.py', 'r', encoding='utf-8') as f:
    v1 = f.read()

# 读取新的load函数
with open('load_etf_fix.py', 'r', encoding='utf-8') as f:
    fix = f.read()

# 找到v1中的load_etf_data函数并替换
old_start = 'def load_etf_data'
new_start = 'def load_etf_data'

# 在v1中找到旧函数的位置
idx1 = v1.find(old_start)
# 找到旧函数结束的位置（下一个===分隔符）
idx2 = v1.find('# =============================================================\n# 策略1', idx1)

if idx1 != -1 and idx2 != -1:
    # 从fix中提取新的load函数（从def load到文件结束）
    new_func = fix[fix.find(new_start):]
    
    # 替换
    new_content = v1[:idx1] + new_func + v1[idx2:]
    
    with open('blakever_etf_backtest_v2.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print('Success! v2.py created')
    print(f'Old file size: {len(v1)} bytes')
    print(f'New file size: {len(new_content)} bytes')
else:
    print(f'Error: idx1={idx1}, idx2={idx2}')
