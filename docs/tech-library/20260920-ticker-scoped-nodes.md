# A 股节点：禁止把全市场表当成本票

- 日期：2026-09-20
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_sentiment.py, tradingagents/dataflows/akshare_fundamentals.py, tradingagents/dataflows/akshare_market.py, tradingagents/agents/analysts/news_analyst.py, tradingagents/agents/researchers, tradingagents/agents/risk_mgmt, tradingagents/agents/trader/trader.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：补充 [20260920-ticker-news-relevance.md](20260920-ticker-news-relevance.md) 的同类约束到情绪/基本面/辩论标签

## 结论

个股新闻相关推荐过滤之后，仍会把别的公司写进当前标的的主要是三条路径：

1. Sentiment 的 `stock_comment_em`（千股千评）是全市场表。原先把每一行当成当前票，且 `TypeError` 时无参再调一次。
2. Fundamentals `get_fundamentals` 在个股资料失败时回退 `stock_info_a_code_name`（全 A 代码简称表），kwargs 含 `{}`。Tape `_stock_name` 同样会把全表第一行当成当前简称。
3. Bull / Bear / 风险把 `news_report` 标成 world affairs；News 节点会调 FRED / Polymarket，提示词挡不住模型把美联储写成该 A 股主因。

已落地：千股千评必须带当前六位代码才保留，禁止无参全表；简介只打 `stock_individual_info_em`；FRED/Polymarket 改为可选且仅当明显影响该代码才引用；辩论标签改为个股新闻报告。Trader 在没有 Market 报告时不得编入场价。

## 不做

- 不把 FRED/Polymarket 从 ToolNode 拿掉；只收紧提示词。
- 不做布局画像或知识图谱。

`get_insider_transactions` 的 A 股实现与 bind 见 [20260920-ashare-buy-sell-flow.md](20260920-ashare-buy-sell-flow.md)。
