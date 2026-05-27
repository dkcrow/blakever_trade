"""
终极修复：用 parts[31] (涨跌幅) 反推昨收价
昨收价 = 当前价 / (1 + 涨跌幅/100)
"""
file_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到需要替换的旧代码块
old = """                        if len(parts) > 5:
                            code = parts[2]  # 纯数字代码
                            price = float(parts[3])  # 当前价
                            # 昨收价：优先用 parts[5]，如果为0则用 parts[4]（今开）
                            yc5 = float(parts[5])
                            yc4 = float(parts[4])
                            yesterday_close = yc5 if yc5 > 0 else yc4
                            prices[code] = {
                                'price': price,
                                'yesterday_close': yesterday_close
                            }"""

# 新代码：用涨跌幅反推
new = """                        if len(parts) > 31:
                            code = parts[2]  # 纯数字代码
                            price = float(parts[3])  # 当前价
                            # 用涨跌幅（Field 31）反推昨收价
                            try:
                                pct_change = float(parts[31])  # 涨跌幅（百分比）
                                if pct_change != 0:
                                    yesterday_close = price / (1 + pct_change / 100)
                                else:
                                    # 涨跌幅为0，用 parts[5]（昨收）
                                    yc5 = float(parts[5])
                                    yesterday_close = yc5 if yc5 > 0 else price
                            except:
                                yesterday_close = price  # 无法计算，默认用当前价
                            prices[code] = {
                                'price': price,
                                'yesterday_close': yesterday_close
                            }"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Ultimate fix applied!")
    print("  Now uses Field 31 (pct change) to calculate yesterday_close")
    print("  Fallback to Field 5 if pct=0")
else:
    print("ERROR: Could not find the old code block")
