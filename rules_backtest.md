# QClaw Rules - 回测框架规范

## 回测框架统一规则

### 1. ETF轮动回测框架（新）
使用 `blakever_etf_backtest_v2.py`（纯 pandas/numpy，不依赖 VectorBT）。

#### 使用方法
```python
import blakever_etf_backtest_v2 as bt

# 加载数据
close_df = bt.load_etf_data(etf_list, subdirs=['etf', 'etf_qixing', 'us'])

# 生成信号（选一个策略）
entries, exits, scores, ranks = bt.strategy_laplace(close_df, top_n=1)
# 或 bt.strategy_qixing(close_df, top_n=1)
# 或 bt.strategy_sanma(close_df, top_n=2)

# 回测
m = bt.run_backtest(close_df, entries, exits)
print(f"年化: {m['annual']:.2f}%, 最大回撤: {m['max_dd']:.2f}%")
```

#### 内置策略
1. **strategy_laplace** - 七星拉普拉斯（38只ETF，动量排名+止损+盈利保护+冷却期）
2. **strategy_qixing** - 七星6+1（7只ETF，EMA动量排名）
3. **strategy_sanma** - 三马七星美股版（15只美股，动量排名+ATR止损）

#### 数据加载说明
- `load_etf_data` 自动尝试 `date`/`Date` 列名，以及 `close`/`Close` 列名
- 数据目录：`back_trader_stocks/etf/`、`etf_qixing/`、`us/`

#### 近2年回测结果汇总（2024-05-25 ~ 2026-05-25）
| 策略 | 总收益率 | 年化收益 | 最大回撤 | 胜率 | 交易次数 | 盈亏比 |
|------|---------|---------|----------|------|---------|--------|
| 七星拉普拉斯（Top1） | 15.75% | 13.16% | -10.28% | 100% | 3 | 5412 |
| 七星6+1（Top1） | 188.26% | 74.14% | -46.24% | 42.86% | 14 | 7.62 |
| 三马七星（Top2） | 99.28% | 43.84% | -37.68% | 52.54% | 59 | 1.71 |

**结论**：
- **三马七星（Top2）最符合目标**（年化43.84%，胜率52.54%，交易频率适中）
- 七星6+1年化最高但回撤过大（-46.24%）
- 七星拉普拉斯信号稀疏（仅3笔），需优化动量周期或降低排名门槛

---

### 2. 港美股分市场回测框架
使用 `blakever_regime_backtest_v4.py`（VectorBT）。

#### 使用方法
```python
import blakever_regime_backtest_v4 as bt

# 回测单个策略
pf = bt.gen_portfolio(close, high, low, strategy='bull')  # 可选: bull/bull_relaxed/sideways/sideways_atr/bear/bear_safe/ema_cross/buyhold
m = bt.get_metrics(pf)
print(f"年化: {m['annual']:.2f}%")
```

#### 注意事项
- VectorBT 依赖 Numba，若初始化失败，需修复 Numba 或 Python 版本
- 若不可用，报告错误，不得使用 Backtrader 或自定义框架

---

### 3. 止损逻辑规范（所有回测脚本必须遵守）
- **止损判断**：用**最低价（low）**判断，不是收盘价
- **止损触发**：盘中价格 ≤ 止损线（entry × 0.92）即触发
- **止损卖出价**：按**止损线价格**卖出，不是收盘价
- **回测与实盘一致**：回测止损逻辑必须和`拉普拉斯_盘中监控_最终版.py`完全一致

---

### 4. 定时任务更新
- **拉普拉斯盘中监控**：已更新为 `拉普拉斯_盘中监控_v14_最终修复版.py`
- 定时任务ID：`qixing-sanma-intraday-monitor`
- 邮件排版：**三马七星同款排版+亮色主题**

---

### 5. 邮件排版规范（强制）
**布局结构**（1:1 复制三马七星）：
- 头部：居中，底部2px灰线，标题20px + 副标题12px
- 前三名栏：白色圆角框+边框，14px加粗，用数字1/2/3替代🥇🥈🥉（避免GBK编码问题）
- 排名变动：字体11px，和说明区一致
- 表格：交易记录表头12px加粗，行12px，当前持仓高亮黄底
- 说明区：11px灰色，居中对齐
- 页脚：10px，顶部1px灰线

---

### 6. 禁止事项
- ❌ 禁止在 `strategy_arena/` 下创建新的自定义回测脚本
- ❌ 禁止使用 `backtest_history*.py` 类型的自定义框架
- ❌ 禁止使用 Backtrader 进行回测（除非显式要求对比）
- ✅ 所有回测必须基于 **VectorBT** 或 **纯 pandas/numpy**（如 `blakever_etf_backtest_v2.py`）

---

### 7. 违规记录
- 2026-05-24：使用自定义框架 `backtest_history_v2.py` 回测拉普拉斯（已废弃）
- 修复：改用 `blakever_etf_backtest_v2.py`（纯 pandas/numpy）
- 2026-05-25：VectorBT + Numba 初始化失败，改用纯 pandas/numpy 实现 ETF 轮动回测框架

---

### 8. 动量得分计算公式（拉普拉斯策略）
**正确公式**（对数回归斜率 × 250，年化）：
```python
y = np.log(prices)  # 对数价格
x = np.arange(len(y))
weights = np.linspace(1, 2, len(y))  # 线性递增权重
slope, _ = np.polyfit(x, y, 1, w=weights)
score = slope * 250  # 年化对数收益率
```

**综合得分**：`短期得分 × 1.0 + 长期得分 × 0.5`

**错误示例**（已修复）：
- ~~`exp()` 指数爆炸：导致得分 23695%~~
- ~~`long = short` 变量覆盖~~
- ~~截断 `max(-2, min(2, combined))` 限制得分范围~~

---

### 9. 文件与路径
- **ETF轮动框架**：`C:\Users\blakehao\.qclaw\workspace\blakever_etf_backtest_v2.py`
- **港美股框架**：`C:\Users\blakehao\.qclaw\workspace\blakever_regime_backtest_v4.py`
- **数据目录**：`C:\Users\blakehao\.qclaw\workspace\back_trader_stocks\`
- **盘中监控**：`C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_v14_最终修复版.py`
- **定时任务配置**：`C:\Users\blakehao\.qclaw\workspace\cron\jobs.json`

---

_最后更新：2026-05-25_
