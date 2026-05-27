"""
超级简单测试：直接运行脚本，看输出
"""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'],
    capture_output=True,
    text=True,
    encoding='utf-8',
    timeout=40
)

# 搜索输出中包含 "yesterday_close" 或 "yc=" 的行
lines = result.stdout.split('\n')
for line in lines:
    if 'yesterday_close' in line.lower() or 'yc=' in line:
        print("FOUND:", line.strip())
        break
else:
    print("NOT FOUND: No yesterday_close in output")
    
# 打印前30行输出
print("\nFirst 30 lines of output:")
for i, line in enumerate(lines[:30]):
    print(f"{i:2d}: {line}")
