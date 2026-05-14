# strategy_arena 包
"""
量化策略搜索、验证、去重与归档系统
====================================

模块:
  - run_backtest.py: 通用回测引擎（命令行入口）
  - strategy_scheduler.py: 定时调度器（主入口）
  - strategy_searcher.py: 策略搜索模块
  - pine_validator.py: Pine Script验证与转译
  - strategy_dedup.py: 策略去重与指纹
  - strategy_ranker.py: 评分与排行榜

使用方式:
  # 执行完整扫描
  python strategy_scheduler.py run --market us

  # 查看状态
  python strategy_scheduler.py status

  # 单独回测某个策略
  python run_backtest.py --strategy strategies/supertrend.py --market us

  # 设置定时任务（每6小时）
  crontab: 0 */6 * * * cd /data/workspace/strategy_arena && python strategy_scheduler.py run
"""
