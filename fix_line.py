#!/usr/bin/env python3
path = r'c:\Users\blakehao\Desktop\blakever_trade\strategies\etf\seven_star_laplacian.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"File has {len(lines)} lines")
print(f"Line 1282: {repr(lines[1281][:80])}")

# Replace line 1282 (index 1281)
lines[1281] = "                        print('  [%s] REDUCE: %s %s %d@%.3f' % (date, etf, ETF_NAMES.get(etf,''), target_amount, price))\n"

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

# Verify
with open(path, 'r', encoding='utf-8') as f:
    verify = f.readlines()
print(f"After fix, line 1282: {repr(verify[1281][:80])}")
print("FIX APPLIED SUCCESSFULLY")
