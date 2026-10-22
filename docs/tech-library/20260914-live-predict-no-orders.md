# 按需实时预测（不下单）

- 日期：2026-09-14
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：cli/main.py, cli/utils.py, tradingagents/dataflows/akshare_market.py, tradingagents/agents/analysts/market_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 20260914-ashare-short-horizon-tape.md，不替代其日线 PIT 规则

## 结论

项目要做**股票实时预测**，但**永远不下单**。

实时在本仓库的定义：调用时刻拉最新**公开**行情与资讯，跑一次现有 LangGraph，产出 T+1 / 5–20 日研究评级。不是 tick 流、不是 24h worker、不是券商通道。

## 确认方案

1. CLI `tradingagents predict TICKER`：默认今天、中文、分析师 Market + News + Sentiment，跳过 Fundamentals。默认先 `ingest-news --global`（A 股）；`--no-ingest` 可关。结束后自动落盘，不提示保存。
2. Live as-of（`is_live_as_of`）才请求东财 `stock_bid_ask_em`，写入 tape 的 Live snapshot；TTL 复用 `news_telegraph_ttl_seconds`。历史 as-of **不得**读该快照，避免前瞻泄漏。
3. 提示词与报告标明：BUY/HOLD/SELL 是研究评级，框架不向券商发委托。
4. 不新增 MQ、cron、daemon、HTTP 交易 API。

## 落地调用链

```
tradingagents predict 600519.SS
  → ingest-news（可选，一次拉取）
  → TradingAgentsGraph.propagate（与 analyze 同一张图）
       Market Analyst → get_ashare_short_horizon
            历史日线 +（仅 live）公开最新价
```
