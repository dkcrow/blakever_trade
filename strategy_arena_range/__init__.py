# strategy_arena_range 包
"""
震荡市量化策略搜索、验证、去重与归档系统
==========================================

与 strategy_arena（趋势/牛市版）并列的震荡市专用版本。
核心差异:
  - 筛选标准: 回撤≤15%（硬性），胜率≥55%，盈亏比≥1.8
  - 评分权重: 年化15%/夏普25%/回撤25%/胜率20%/盈亏比15%
  - 回测区间: 2021-2023(典型震荡) + 2015-2016(熔断期)
  - 止损检查: 无止损逻辑扣10分
  - 策略类型: 新增震荡区间交易/波动率收缩突破/网格对冲
  - 入榜门槛: 综合得分≥75分
  - 失效判定: 连续2周跑输基准≥2%且至少1周为负

模块:
  - range_searcher.py: 震荡市策略搜索模块
  - range_ranker.py: 震荡市评分与排行榜
  - range_scheduler.py: 定时调度器（主入口）
  - run_backtest_range.py: 震荡市回测引擎（复用VectorBT+TA-Lib）

使用方式:
  # 执行完整扫描
  python range_scheduler.py run --market us

  # 执行完整扫描（美股+港股）
  python range_scheduler.py run --market all

  # 查看状态
  python range_scheduler.py status

依赖:
  - 复用 /data/workspace/strategy_arena/pine_validator.py (Pine Script验证)
  - 复用 /data/workspace/strategy_arena/strategy_dedup.py (去重与指纹)
  - 复用 /data/workspace/back_trader_stocks/ (港美股历史数据)
"""
