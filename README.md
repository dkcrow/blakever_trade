# Blakever Trade - 量化投资策略研究与回测系统

[![Python Version](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## 📊 项目简介

Blakever Trade 是一个基于 Python 的量化投资策略研究与回测系统，支持 A股、港股、美股 多市场，集成了多种技术指标策略、多因子选股、策略优化与组合构建等功能。

### 核心功能

- **多市场支持**：A股、港股、美股
- **多种策略类型**：EMA/ADX、MACD、RSI、布林带、SuperTrend、Alpha因子、多因子
- **策略优化**：分步优化、参数优化、权重优化
- **组合构建**：FOF组合、相关性分析、风险平价
- **回测分析**：VectorBT、TA-Lib 回测引擎
- **数据管理**：多数据源支持（JQData、Westock、AKShare、TQSDK）
- **报告生成**：HTML/JSON/CSV 报告、邮件发送

## 📁 目录结构

```
blakever_trade/
├── config/                         # 配置文件中心
│   ├── __init__.py
│   ├── settings.py                 # 全局配置
│   ├── market_config.py            # 市场配置（A股/港股/美股）
│   └── strategy_params.py         # 策略参数配置
│
├── data/                           # 数据层
│   ├── fetchers/                  # 数据获取
│   ├── processors/                # 数据处理
│   ├── storage/                   # 数据存储
│   │   ├── stock_data/            # 股票数据
│   │   └── market_data/          # 市场数据
│   └── __init__.py
│
├── factors/                        # 因子层
│   └── __init__.py
│
├── strategies/                     # 策略层
│   ├── etf/                      # ETF策略
│   └── __init__.py
│
├── backtest/                      # 回测层
│   ├── engines/                  # 回测引擎
│   ├── metrics/                  # 绩效指标
│   ├── analyzers/                # 回测分析
│   ├── results/                  # 回测结果
│   └── __init__.py
│
├── optimization/                   # 优化层
│   ├── correlation/              # 相关性分析
│   ├── weight/                   # 权重优化
│   ├── parameter/                # 参数优化
│   └── __init__.py
│
├── portfolio/                      # 组合层
│   └── __init__.py
│
├── reporting/                      # 报告层
│   ├── results/                  # 报告结果
│   ├── template/                 # 报告模板
│   ├── __init__.py
│   ├── blakever_send_email.py    # 邮件发送
│   ├── risk_alert.py            # 风险预警
│   └── send_*.py                # 各类报告发送脚本
│
├── utils/                         # 工具层
│   └── __init__.py
│
├── scripts/                       # 脚本入口
│   └── __init__.py
│
├── tests/                         # 测试
│   └── __init__.py
│
├── docs/                          # 文档
│   ├── skills/                   # Skills文档
│   ├── __init__.py
│   ├── AGENT_PROMPT.md          # Agent工作规范
│   ├── REFACTOR_SUMMARY.md      # 重构总结
│   └── USAGE_EXAMPLES.py        # 使用示例
│
├── archive/                       # 归档
│   ├── old_versions/            # 旧版本
│   ├── deprecated_scripts/       # 废弃脚本
│   └── __init__.py
│
├── logs/                          # 日志
│
├── main.py                        # 主入口
├── requirements.txt               # 依赖包
├── setup.py                       # 安装脚本
└── README.md                     # 项目说明
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置数据源

编辑 `config/settings.py`，配置数据源参数：

```python
DATA_SOURCES = {
    'jqdata': {
        'enabled': True,
        'username': 'your_username',
        'password': 'your_password',
    },
    # ...
}
```

### 3. 获取数据

```bash
python main.py fetch-data
```

### 4. 运行回测

```bash
python main.py backtest --strategy ema_adx --market a_stock
```

### 5. 生成报告

```bash
python main.py report --format html
```

## ⚙️ 配置说明

### 全局配置 (`config/settings.py`)

- **PATHS**：路径配置
- **DATA_SOURCES**：数据源配置
- **BACKTEST_CONFIG**：回测配置
- **EMAIL_CONFIG**：邮件配置
- **LOG_CONFIG**：日志配置

### 市场配置 (`config/market_config.py`)

- **A_STOCK_CONFIG**：A股配置
- **HK_STOCK_CONFIG**：港股配置
- **US_STOCK_CONFIG**：美股配置
- **ETF_CONFIG**：ETF配置

### 策略参数配置 (`config/strategy_params.py`)

- **EMA_ADX_PARAMS**：EMA + ADX 策略参数
- **MACD_PARAMS**：MACD 策略参数
- **RSI_PARAMS**：RSI 策略参数
- **ALPHA_FACTOR_PARAMS**：Alpha因子策略参数
- **BLAKEVER_PARAMS**：Blakever 策略参数

## 📚 使用指南

### 数据获取

```python
from data.fetchers import JQDataFetcher

fetcher = JQDataFetcher()
data = fetcher.fetch_stock_data('sh600519', start_date='2020-01-01')
```

### ETF策略回测

```python
from strategies.etf import AlphaFactorBacktest
from backtest.engines import VectorBTEngine

strategy = AlphaFactorBacktest()
engine = VectorBTEngine(strategy)
results = engine.run_backtest(data)
```

### 策略优化

```python
from optimization.parameter import GridSearch

optimizer = GridSearch(strategy)
best_params = optimizer.optimize(data, param_grid)
```

### 组合构建

```python
from portfolio import FOFConstructor

fof = FOFConstructor()
weights = fof.optimize_weights(returns, method='risk_parity')
```

## 🧩 模块说明

### config/ - 配置模块

集中管理所有配置参数，包括路径、数据源、回测参数、邮件配置等。

### data/ - 数据层

- **fetchers/**：数据获取，支持多种数据源
- **processors/**：数据处理，包括清洗、验证、转换
- **storage/**：数据存储，支持CSV、数据库

### factors/ - 因子层

多因子选股相关的因子计算，包括价值、质量、成长、动量、波动率、流动性等因子。

### strategies/ - 策略层

- **etf/**：ETF策略（多策略FOF、七星拉普拉斯、七星三马等）

### backtest/ - 回测层

- **engines/**：回测引擎（VectorBT、TA-Lib）
- **metrics/**：绩效指标（收益、风险、夏普比率等）
- **analyzers/**：回测分析（性能分析、报告生成）

### optimization/ - 优化层

- **correlation/**：相关性分析
- **weight/**：权重优化（最大夏普、风险平价、启发式优化）
- **parameter/**：参数优化（网格搜索、贝叶斯优化）

### portfolio/ - 组合层

FOF组合构建、仓位管理、再平衡。

### reporting/ - 报告层

报告生成（HTML、JSON、CSV）、邮件发送、预警系统。

### utils/ - 工具层

装饰器、日志、时间工具、数学工具等通用代码。

## 🧪 测试

运行所有测试：

```bash
pytest tests/
```

运行特定测试：

```bash
pytest tests/test_factors.py
```

## 📝 代码规范

- 遵循 PEP 8 代码规范
- 使用类型注解
- 编写文档字符串
- 编写单元测试

## 🤝 贡献指南

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 LICENSE 文件。

## 📧 联系方式

如有问题或建议，请提交 Issue 或联系项目维护者。

---

**注意**：本系统仅供研究和学习使用，不构成投资建议。投资有风险，入市需谨慎。
