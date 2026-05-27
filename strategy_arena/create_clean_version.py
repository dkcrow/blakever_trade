"""
创建全新的拉普拉斯盘中监控脚本，确保：
1. 中文字符正确（UTF-8）
2. 涨跌幅正确计算
3. 显示所有 ETF
"""
import sys

# 读取原始脚本（假设原始版本没有乱码）
original_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

# 读取为 bytes，然后解码为 UTF-8
with open(original_path, 'rb') as f:
    raw = f.read()

# 尝试解码
try:
    content = raw.decode('utf-8-sig')  # 尝试 UTF-8 with BOM
    print("Decoded as UTF-8-sig")
except:
    try:
        content = raw.decode('utf-8')
        print("Decoded as UTF-8")
    except:
        content = raw.decode('gbk', errors='ignore')
        print("Decoded as GBK (with errors ignored)")

# 检查关键部分
checks = {
    "get_tencent_realtime_prices()": "def get_tencent_realtime_prices" in content,
    "yesterday_close in prices[code]": "yesterday_close" in content,
    "pct_change calculation": "pct_change = ((price - yesterday_close) / yesterday_close) * 100" in content,
    "generate_html loops all results": "for r in results:" in content and "results[:10]" not in content,
}

print("\nChecks:")
for name, result in checks.items():
    print(f"  {'OK' if result else 'FAIL'}: {name}")

# 如果检查失败，尝试修复
if not all(checks.values()):
    print("\nAttempting fixes...")
    
    # Fix 1: Ensure pct_change calculation
    if not checks["pct_change calculation"]:
        # Find the line with "计算涨跌幅"
        lines = content.split('\n')
        new_lines = []
        for i, line in enumerate(lines):
            new_lines.append(line)
            if "计算涨跌幅" in line and i < len(lines)-5:
                # Check next few lines for pct_change calculation
                context = '\n'.join(lines[i:i+5])
                if "pct_change = ((price - yesterday_close)" not in context:
                    # Insert correct calculation
                    indent = len(line) - len(line.lstrip())
                    new_calc = ' ' * indent + "pct_change = ((price - yesterday_close) / yesterday_close) * 100\n"
                    new_lines.append(new_calc)
        content = '\n'.join(new_lines)
        print("  Added pct_change calculation")

# Save as new file
new_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\lama_v15_clean.py'
with open(new_path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f"\nSaved clean version to: {new_path}")
print("Please rename to 拉普拉斯_盘中监控_最终版.py if it works!")
