# A 股出手/买入：增减持、龙虎席位、大宗

- 日期：2026-09-20
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_flow.py, tradingagents/agents/utils/news_data_tools.py, tradingagents/agents/analysts/news_analyst.py, tradingagents/agents/analysts/fundamentals_analyst.py, tradingagents/graph/trading_graph.py, tradingagents/dataflows/akshare_market.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：补完 [20260920-ticker-scoped-nodes.md](20260920-ticker-scoped-nodes.md) 中未做的 `get_insider_transactions`

## 结论

遗留的 `get_insider_transactions` 未 bind、也没有 A 股实现。出手/买入分析落在同一条工具上，不另开下单通道。

- A 股供应商：`akshare_flow.get_insider_transactions`（董监高/股东增减持、龙虎买入/卖出席位与金额、大宗）。只保留当前六位代码、日期 `<= as-of`。禁止无参全表。
- 路由：`news_data` first-success，akshare 在 yfinance 前。Yahoo 对 A 股跳过。
- News 与 Fundamentals 的 `bind_tools` 与 ToolNode 对齐。空结果返回 `NO_DATA_AVAILABLE`，禁止编造。
- Market tape 的龙虎块改用同一套席位汇总（买入额/卖出额/净买入/席位名单）。

这是研究输入，不是委托。
