import os

# 读取v1.py和load_etf_fix.py
with open('blakever_etf_backtest_v1.py', 'r', encoding='utf-8') as f:
    v1_content = f.read()

with open('load_etf_fix.py', 'r', encoding='utf-8') as f:
    fix_content = f.read()

# 找到v1中load_etf_data函数的位置
start_marker = 'def load_etf_data'
end_marker = '# =============================================================\r\n# 策略1'

start_idx = v1_content.find(start_marker)
# 找到start_marker之后的第一个end_marker
temp_idx = v1_content.find(end_marker, start_idx)

if start_idx != -1 and temp_idx != -1:
    # 替换load_etf_data函数
    new_content = v1_content[:start_idx] + fix_content[fix_content.find(start_marker):] + v1_content[temp_idx:]
    
    with open('blakever_etf_backtest_v2.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Success: blakever_etf_backtest_v2.py created')
    print(f'File size: {os.path.getsize("blakever_etf_backtest_v2.py")} bytes')
else:
    print(f'Error: start_idx={start_idx}, temp_idx={temp_idx}')
