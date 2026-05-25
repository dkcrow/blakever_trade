import re

# 读取文件
with open('C:/Users/blakehao/.qclaw/workspace/strategy_arena/拉普拉斯_盘中监控_最终版.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 send_email 函数
start = content.find('def send_email(')
if start == -1:
    print('ERROR: Could not find send_email function')
    exit(1)

# 找到函数结束（下一个def或文件结束）
end = content.find('\ndef ', start + 10)
if end == -1:
    end = len(content)

send_email_func = content[start:end]
print(f'Found send_email function: {len(send_email_func)} chars')

# 检查是否有未转义的 } 在 f-string 中
# 找到 f""" 和对应的 """
fstring_start = send_email_func.find('html = f"""')
if fstring_start == -1:
    print('ERROR: Could not find f-string')
    exit(1)

# 找到匹配的结束 """
fstring_end = send_email_func.find('"""', fstring_start + 10)
if fstring_end == -1:
    print('ERROR: Could not find end of f-string')
    exit(1)

fstring = send_email_func[fstring_start:fstring_end+3]
print(f'f-string length: {len(fstring)} chars')

# 检查是否有单独的 }（不在 {{}} 内）
lines = fstring.split('\n')
for i, line in enumerate(lines):
    # 移除 {{}} 转义后的内容，看是否有剩余 }
    # 简单检查：这行是否有 } 且前面不是 {
    if '}' in line:
        # 检查每个 }
        pos = 0
        while True:
            pos = line.find('}', pos)
            if pos == -1:
                break
            # 检查前面是否是 {
            if pos > 0 and line[pos-1] == '{':
                # 这是 }} 的一部分
                pass
            else:
                # 单独的 }
                line_num = content[:start+fstring_start].count('\n') + i + 1
                print(f'Found single }} at line {line_num}: {repr(line)}')
            pos += 1
