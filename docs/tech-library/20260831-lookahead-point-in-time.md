# 前瞻泄漏与点-in-time 记忆

- 日期：2026-08-31
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/date_window.py, tradingagents/dataflows/fred.py, tradingagents/agents/utils/memory.py, tradingagents/graph/trading_graph.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：无

## 根因

历史/回测运行把“今天”的数据当成交易日当天的观察：

- FRED 宏观用当前 vintage，后期修订漏进回测（`#1275`）
- StockTwits / Reddit 无日期裁剪，当前社媒被当成 as-of 情绪（`#1220`）
- `get_past_context` 注入所有已结算教训，包括交易日之后才知道的结果（`#1251`）
- 持有窗未走完就按部分收益结算反思（`#1169`）

## 确认修复策略

1. 新闻与社媒共用 `dataflows/date_window`：UTC、上界为 `end` 次日零点的半开窗；无日期条目仅当窗口触及现在时保留。
2. FRED 观测与元数据请求把 vintage 钉在 as-of。
3. memory 条目记录 `resolution_date`；历史跑只注入该日及之前已结算的教训；当日实盘跑不启用该过滤。
4. `_fetch_returns` 必须看到完整 holding window，否则保持 pending。

## 后续约束

新数据源只要带发布时间，必须走 `in_window`，不要再写一套 cutoff。新记忆字段若影响回测，必须能按“结果已知日”过滤。
