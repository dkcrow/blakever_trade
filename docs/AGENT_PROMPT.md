# Agent 工作规范 Prompt

## 🚨 核心原则

**所有功能文件必须放在对应模块目录下，禁止在根目录下堆叠文件！**

---

## 📁 目录使用规范

### 1. 功能文件存放规则

| 文件类型 | 存放目录 | 示例 |
|---------|---------|------|
| 配置文件 | `config/` | `config/settings.py` |
| 数据获取脚本 | `data/fetchers/` | `data/fetchers/jqdata_fetcher.py` |
| 数据处理脚本 | `data/processors/` | `data/processors/data_cleaner.py` |
| 因子计算脚本 | `factors/` | `factors/value_factors.py` |
| ETF策略脚本 | `strategies/etf/` | `strategies/etf/alpha_factor_backtest.py` |
| 策略脚本 | `strategies/` | `strategies/etf/blakever_v65_backtest.py` |
| 回测引擎 | `backtest/engines/` | `backtest/engines/vectorbt_engine.py` |
| 回测分析 | `backtest/analyzers/` | `backtest/analyzers/performance_analyzer.py` |
| 优化脚本 | `optimization/<类型>/` | `optimization/parameter/step_optimizer.py` |
| 组合脚本 | `portfolio/` | `portfolio/fof_constructor.py` |
| 报告脚本 | `reporting/` | `reporting/blakever_send_email.py` |
| 报告模板 | `reporting/template/` | `reporting/template/report_template.html` |
| 工具脚本 | `utils/` | `utils/logger.py` |
| 入口脚本 | `scripts/` | `scripts/run_backtest.py` |
| 测试脚本 | `tests/` | `tests/test_factors.py` |
| 文档文件 | `docs/` | `docs/API.md` |
| 临时/缓存文件 | `cache/` | `cache/temp_data.csv` |
| 归档文件 | `archive/` | `archive/old_versions/v1_backtest.py` |

### 2. 输出文件存放规则

| 输出类型 | 存放目录 | 示例 |
|---------|---------|------|
| 回测结果 | `backtest/results/` | `backtest/results/alpha_factor_report.html` |
| 报告文件 | `reporting/results/` | `reporting/results/us_market_report.md` |
| 日志文件 | `logs/` | `logs/blakever_trade.log` |
| 缓存文件 | `cache/` | `cache/market_data_cache.json` |

### 3. 数据文件存放规则

| 数据类型 | 存放目录 | 示例 |
|---------|---------|------|
| 股票数据 | `data/storage/stock_data/` | `data/storage/stock_data/sh600519.csv` |
| 市场数据 | `data/storage/market_data/` | `data/storage/market_data/index_data.csv` |
| 因子数据 | `data/storage/factor_data/` | `data/storage/factor_data/value_factors.csv` |

---

## 🚫 禁止事项

### ❌ 严格禁止

1. **禁止在根目录下创建功能文件**
   - ❌ `blakever_trade/new_strategy.py`
   - ✅ `blakever_trade/strategies/regime/new_strategy.py`

2. **禁止在根目录下堆叠测试脚本**
   - ❌ `blakever_trade/test_new_feature.py`
   - ✅ `blakever_trade/tests/test_new_feature.py`

3. **禁止在根目录下生成结果文件**
   - ❌ `blakever_trade/backtest_result.html`
   - ✅ `blakever_trade/backtest/results/backtest_result.html`

4. **禁止在根目录下存放数据文件**
   - ❌ `blakever_trade/stock_data.csv`
   - ✅ `blakever_trade/data/storage/stock_data/stock_data.csv`

5. **禁止创建无意义的版本备份文件**
   - ❌ `blakever_trade/strategy_v1.py`, `strategy_v2.py`, `strategy_v3.py`
   - ✅ 使用 Git 管理版本，或放在 `archive/old_versions/`

---

## ✅ 文件命名规范

### 1.  Python 文件命名

- 使用小写字母和下划线
- 描述性名称，反映文件功能
- 示例：
  - ✅ `alpha_factor_backtest.py`
  - ✅ `data_fetcher.py`
  - ❌ `abc.py`
  - ❌ `test1.py`

### 2. 测试结果文件命名

- 包含策略名称、日期、文件类型
- 示例：
  - ✅ `backtest/results/alpha_factor_20260525.html`
  - ✅ `reporting/results/us_market_report_20260525.md`

### 3. 数据文件命名

- 包含股票代码、数据类型、日期
- 示例：
  - ✅ `data/storage/stock_data/sh600519_daily_20200101_20251231.csv`
  - ✅ `data/storage/market_data/index_000001_daily.csv`

---

## 📝 代码规范

### 1. 导入路径规范

**必须使用绝对导入，禁止使用相对导入**

```python
# ✅ 正确 - 绝对导入
from config.settings import PATHS
from data.fetchers import JQDataFetcher
from strategies.alpha import AlphaFactorStrategy

# ❌ 错误 - 相对导入
from ..config import settings
from .data import fetchers
```

### 2. 路径引用规范

**必须使用 `config/settings.py` 中的 `PATHS` 配置**

```python
# ✅ 正确 - 使用 PATHS 配置
from config.settings import PATHS
import os

data_dir = PATHS['data_dir']
stock_data_path = os.path.join(PATHS['stock_data_dir'], 'sh600519.csv')

# ❌ 错误 - 硬编码路径
data_dir = 'c:/Users/blakehao/Desktop/blakever_trade/data'
stock_data_path = 'c:/Users/blakehao/Desktop/blakever_trade/data/storage/stock_data/sh600519.csv'
```

### 3. 日志规范

**必须使用 `utils/logger.py` 中的日志工具**

```python
# ✅ 正确 - 使用统一日志工具
from utils.logger import get_logger

logger = get_logger(__name__)
logger.info("开始回测...")
logger.error("数据获取失败")

# ❌ 错误 - 直接使用 print
print("开始回测...")
```

---

## 🧪 测试规范

### 1. 测试文件存放

- 所有测试文件必须放在 `tests/` 目录下
- 测试文件命名：`test_<功能>.py`

### 2. 测试数据存放

- 测试数据必须放在 `tests/data/` 目录下
- 测试输出必须放在 `tests/output/` 目录下

### 3. 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_factors.py

# 生成覆盖率报告
pytest --cov=./ --cov-report=html
```

---

## 📊 工作流程示例

### 示例1：创建新策略

**任务**：创建一个基于 RSI 的新策略

**错误做法**：
```bash
# ❌ 在根目录下创建文件
touch blakever_trade/rsi_strategy.py
```

**正确做法**：
```bash
# ✅ 在对应模块目录下创建文件
touch blakever_trade/strategies/etf/rsi_strategy.py

# 编辑文件，使用绝对导入
# strategies/etf/rsi_strategy.py
from config.settings import PATHS
from data.fetchers import JQDataFetcher

class RSIStrategy:
    def __init__(self):
        self.data_fetcher = JQDataFetcher()
```

### 示例2：运行回测并生成报告

**任务**：运行 ETF 策略回测，生成 HTML 报告

**错误做法**：
```bash
# ❌ 在根目录下运行，结果也放在根目录
cd blakever_trade
python strategies/etf/alpha_factor_backtest.py
# 结果生成在根目录：blakever_trade/alpha_factor_report.html
```

**正确做法**：
```bash
# ✅ 在对应模块目录下运行，结果放在 results 目录
cd blakever_trade
python strategies/etf/alpha_factor_backtest.py
# 结果生成在：blakever_trade/backtest/results/alpha_factor_report.html
```

### 示例3：数据获取

**任务**：获取股票数据

**错误做法**：
```python
# ❌ 数据保存在根目录
import pandas as pd
df = pd.read_csv('sh600519.csv')  # 从根目录读取
df.to_csv('sh600519.csv')  # 保存到根目录
```

**正确做法**：
```python
# ✅ 数据保存在 data/storage 目录
from config.settings import PATHS
import os
import pandas as pd

data_dir = PATHS['stock_data_dir']
df = pd.read_csv(os.path.join(data_dir, 'sh600519.csv'))  # 从 data/storage/stock_data 读取
df.to_csv(os.path.join(data_dir, 'sh600519.csv'))  # 保存到 data/storage/stock_data
```

### 示例4：创建报告模板

**任务**：创建新的报告模板

**错误做法**：
```bash
# ❌ 在根目录下创建模板文件
touch blakever_trade/report_template.html
```

**正确做法**：
```bash
# ✅ 在 reporting/template/ 目录下创建模板文件
touch blakever_trade/reporting/template/report_template.html

# 编辑文件，使用绝对导入
# reporting/template/report_template.html
from config.settings import PATHS
import os

template_dir = os.path.join(PATHS['report_dir'], 'template')
```

---

## 🔍 检查清单

在完成任何任务后，请检查：

- [ ] 所有功能文件都放在对应模块目录下
- [ ] 没有在根目录下创建任何功能文件
- [ ] 所有输出文件都放在 `results/` 或 `cache/` 目录
- [ ] 所有数据文件都放在 `data/storage/` 目录
- [ ] 所有导入都使用绝对导入
- [ ] 所有路径都使用 `PATHS` 配置
- [ ] 所有日志都使用统一日志工具
- [ ] 测试文件都放在 `tests/` 目录

---

## 📞 违规处理

如果违反上述规范，Agent 应该：

1. **自我纠正**：立即移动文件到正确位置
2. **更新路径**：更新文件中的路径引用
3. **记录问题**：在 `docs/AGENT_PROMPT.md` 中记录常见错误

---

**最后更新**：2026-05-25
**维护者**：Blakever Trade Team
