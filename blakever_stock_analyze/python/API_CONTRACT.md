# Blakever 策略模块接口契约 v2.0

## 统一GEM策略（贯穿牛熊）
- 模块：`blakever_trade_strategy`
- 函数：`execute_trade_strategy(stock_data: dict, account_equity: float, regime: str = 'Range', regime_confidence: float = 50.0, top_n: int = 5, industry_map: dict = None, market_cap_map: dict = None, beta_map: dict = None, dividend_yield_map: dict = None, avg_volume_map: dict = None) -> list[dict]`
- 说明：GEM双动量轮动策略，根据regime动态调整风险/安全资产配置权重，贯穿牛熊
- 返回：候选标的列表，每个元素包含 symbol, direction, current_price, score, suggested_pct, initial_stop_loss, rationale, regime

### regime参数说明
- `Bull`: 倾向持有高动量风险资产（SPY/VEA），风险权重90%
- `Bear`: 快速切换至安全资产（AGG/SHY），可识别做空机会，安全权重90%
- `Range`: 风险与安全资产均衡轮动，各50%权重
- `Panic`: 全仓安全资产，安全权重100%
