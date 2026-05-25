#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Insert strategy naming rules into qclaw-rules SKILL.md
"""

rule_text = """

---

## 7. 策略命名与引用规则

### 触发条件

当用户提到以下策略简称时，必须映射到对应的具体文件（位于 `strategy_arena/` 目录）：

| 用户说法 | 对应文件 | 策略说明 |
|---------|----------|----------|
| **拉普拉斯** / **拉普拉斯策略** / **七星拉普拉斯** | `拉普拉斯.py` | 七星拉普拉斯高斯策略，32只ETF，含拉普拉斯/高斯双滤波器、震荡期切换、盈利保护 |
| **6+1** / **七星6+1** / **七星高照6+1** | `七星高照6+1.py` | A股ETF 6+1策略，7只ETF（6投资池+1安全池），25日动量 |
| **三马** / **三马美股** / **七星三马** | `七星三马美股版.py` | 美股个股15只，ATR 2x止损，Top3持仓 |

### 执行规则

1. **文件引用**：当用户说"拉普拉斯策略"时，指的一定是 `strategy_arena/拉普拉斯.py`（原 `七星拉普拉斯高斯_backtrader.py`）
2. **成分股记忆**：
   - 拉普拉斯：32只ETF（商品7只+美股ETF 7只+国际ETF 6只+A股ETF 12只+Smart Beta 4只+防御1只）
   - 6+1：7只ETF（159915/513100/159985/518880/501018/161226/511220）
   - 三马美股：15只美股个股（NVDA/AMD/MU/AVGO/TSLA/AAPL/GOOG/AMZN/KO/NEM/XOM/AEP/JPM/GS/BRK-B）
3. **禁止混淆**：不得再将"拉普拉斯"与"6+1"的成分股混为一谈
4. **文件路径**：所有策略文件均在 `C:\\Users\\blakehao\\.qclaw\\workspace\\strategy_arena\\`
"""

marker = "<!--\n## [编号]. [流程名称]"

path = r"D:\Program Files\QClaw\resources\openclaw\config\skills\qclaw-rules\SKILL.md"

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

if marker in content:
    new_content = content.replace(marker, rule_text + "\n" + marker, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("OK: 策略命名规则已插入到 qclaw-rules SKILL.md")
else:
    print("ERROR: 未找到插入点 <!-- ## [编号]. [流程名称] -->")
