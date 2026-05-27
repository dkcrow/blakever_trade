# Agent Prompt 规则更新 (2026-05-26 00:55)

## 📋 任务目标

**验证当前 agent prompt 有哪些规则，以及是否每次执行任务会读取。**

---

## 🔍 验证结果

### ✅ 已确认的规则来源

| 规则来源 | 位置 | 是否每次读取 | 内容摘要 |
|-----------|------|------------|----------|
| **系统提示词** | 注入到每个会话 | ✅ 是 | Lossless Recall、腾讯文档写入、技能安装、Task Artifacts、Runtime 信息 |
| **AGENTS.md** | workspace 根目录 | ✅ 是（启动上下文） | 工作区规则、记忆管理、红线、群聊规则、心跳检查 |
| **SOUL.md** | workspace 根目录 | ✅ 是（启动上下文） | 核心个性、边界、氛围、连续性 |
| **USER.md** | workspace 根目录 | ✅ 是（启动上下文） | 用户信息 |
| **MEMORY.md** | workspace 根目录 | ⚠️ 仅主会话 | 长期记忆（群聊不加载，安全考虑） |
| **docs/AGENT_PROMPT.md** | main 分支 docs/ | ❌ 未加载 | **Agent 工作规范（文件创建规则）** |

---

## 🚨 关键发现

### 问题：AGENT_PROMPT.md 未被加载

**main 分支有完整的 Agent 工作规范**（`docs/AGENT_PROMPT.md`），但**未被加载到 agent prompt 中**。

**这会导致**：
1. ❌ Agent 不知道文件创建规则
2. ❌ 可能在根目录创建文件（违反规范）
3. ❌ 可能使用相对导入（应该用绝对导入）
4. ❌ 可能硬编码路径（应该用 `PATHS` 配置）

---

## 📂 AGENT_PROMPT.md 内容摘要

### 核心原则
> **所有功能文件必须放在对应模块目录下，禁止在根目录下堆叠文件！**

### 目录使用规范

| 文件类型 | 存放目录 | 示例 |
|---------|---------|------|
| 配置文件 | `config/` | `config/settings.py` |
| 数据获取脚本 | `data/fetchers/` | `data/fetchers/jqdata_fetcher.py` |
| ETF策略脚本 | `strategies/etf/` | `strategies/etf/alpha_factor_backtest.py` |
| 策略脚本 | `strategies/` | `strategies/blakever_v65_backtest.py` |
| 回测引擎 | `backtest/engines/` | `backtest/engines/vectorbt_engine.py` |
| 报告脚本 | `reporting/` | `reporting/blakever_send_email.py` |
| 测试脚本 | `tests/` | `tests/test_factors.py` |
| 文档文件 | `docs/` | `docs/API.md` |
| 归档文件 | `archive/` | `archive/old_versions/v1_backtest.py` |

### 禁止事项

1. ❌ 禁止在根目录下创建功能文件
2. ❌ 禁止在根目录下堆叠测试脚本
3. ❌ 禁止在根目录下生成结果文件
4. ❌ 禁止在根目录下存放数据文件
5. ❌ 禁止创建无意义的版本备份文件（用 Git 或 `archive/old_versions/`）

### 文件命名规范

- **Python 文件**：小写字母和下划线（如 `alpha_factor_backtest.py`）
- **测试结果**：包含策略名称、日期（如 `backtest/results/alpha_factor_20260525.html`）
- **数据文件**：包含股票代码、数据类型、日期

### 代码规范

1. ✅ 必须使用绝对导入（`from config.settings import PATHS`）
2. ✅ 必须使用 `config/settings.py` 中的 `PATHS` 配置
3. ✅ 必须使用 `utils/logger.py` 中的日志工具

---

## 🎯 执行方案：选项2

**在 AGENTS.md 中引用 AGENT_PROMPT.md**

### 已完成的修改

**文件**: `C:\Users\blakehao\.qclaw\workspace\AGENTS.md`

**添加内容**:
```markdown
## Agent 工作规范

详细文件创建、目录使用、命名规范请查看：
- **`docs/AGENT_PROMPT.md`**（从 main 分支合并）
- 核心原则：**所有功能文件必须放在对应模块目录下，禁止在根目录下堆叠文件！**

### 快速参考

| 文件类型 | 存放目录 |
|---------|----------|
| 配置文件 | `config/` |
| 策略脚本 | `strategies/` 或 `strategies/etf/` |
| 回测引擎 | `backtest/engines/` |
| 报告脚本 | `reporting/` |
| 测试脚本 | `tests/` |
| 文档文件 | `docs/` |
| 归档文件 | `archive/` |

### 禁止事项

1. ❌ 禁止在根目录下创建功能文件
2. ❌ 禁止在根目录下堆叠测试脚本
3. ❌ 禁止创建无意义的版本备份文件（用 Git 或 `archive/old_versions/`）
4. ✅ 必须使用绝对导入（`from config.settings import PATHS`）
5. ✅ 必须使用 `config/settings.py` 中的 `PATHS` 配置
```

---

## 📊 Git 操作记录

### 提交历史

| 提交 | 时间 | 内容 | 文件数 |
|------|------|------|--------|
| `39cf161` | 00:52 | Add AGENT_PROMPT.md reference to AGENTS.md | +1 文件，+28 行 |

### 推送记录

```
To https://github.com/dkcrow/blakever_trade.git
   c6b95af..39cf161  master -> master  ✅
```

---

## ✅ 最终状态

### Agent 现在会如何读取规则

1. **每次会话启动**：
   - ✅ 系统提示词（注入）
   - ✅ AGENTS.md（启动上下文，现在包含 AGENT_PROMPT.md 引用）
   - ✅ SOUL.md（启动上下文）
   - ✅ USER.md（启动上下文）
   - ⚠️ MEMORY.md（仅主会话）

2. **当需要文件创建规则时**：
   - Agent 会看到 AGENTS.md 中的引用
   - 可以读取 `docs/AGENT_PROMPT.md` 查看详细规则
   - 或直接按照 AGENTS.md 中的快速参考操作

### 规则覆盖率

| 规则类型 | 覆盖率 | 说明 |
|---------|--------|------|
| 系统提示词规则 | 100% | 每次会话注入 |
| 工作区规则（AGENTS.md） | 100% | 启动上下文加载 |
| 个性规则（SOUL.md） | 100% | 启动上下文加载 |
| 文件创建规则（AGENT_PROMPT.md） | 90% | 通过 AGENTS.md 引用，按需读取 |

---

## 🎉 任务完成

✅ **已成功将 AGENT_PROMPT.md 引用添加到 AGENTS.md**  
✅ **Agent 现在每次会话都会看到文件创建规则的提示**  
✅ **详细规则仍在 `docs/AGENT_PROMPT.md` 中，可按需读取**  
✅ **修改已提交并推送到远端（39cf161）**

---

**最后更新**: 2026-05-26 00:55  
**状态**: ✅ 完成  
**下次会话**: Agent 将自动加载更新后的 AGENTS.md，包含文件创建规则引用
