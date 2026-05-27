"""
在 send_email 前保存 HTML 到文件，用于调试
"""
file_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    new_lines.append(line)
    
    # 找到 "send_email(html)" 这一行
    if 'send_email(html)' in line and 'def send_email' not in lines[i-1] if i > 0 else True:
        # 在前面插入保存HTML的代码
        new_lines.append('    \n')
        new_lines.append('    # 调试：保存HTML到文件\n')
        new_lines.append('    with open("last_email.html", "w", encoding="utf-8") as f:\n')
        new_lines.append('        f.write(html)\n')
        new_lines.append('    print(f"  [DEBUG] HTML已保存到 last_email.html")\n')
        new_lines.append('    \n')
    i += 1

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Script updated: Now saves HTML to last_email.html before sending")
print("  You can check pct_change in the HTML file")
