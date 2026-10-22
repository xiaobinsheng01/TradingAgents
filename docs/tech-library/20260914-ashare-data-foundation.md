# A 股资讯数据底座

- 日期：2026-09-14
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/news_items.py, tradingagents/dataflows/news_store.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/ashare_sentiment.py, tradingagents/agents/analysts/sentiment_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：扩展 [20260914-ashare-news-aggregation.md](20260914-ashare-news-aggregation.md)，不替代其供应商聚合合同

## 背景

单源 Yahoo 不够之后，仍缺跨渠道去重、按日归档、国内政策多线并行，以及 A 股情绪（StockTwits/Reddit 对 A 股无效）。

## 确认方案

1. 统一 `NewsItem`：跨渠道按链接（否则标题）去重；公告类型写入 `category`；证监会/央行等打政策标记。
2. `news_store.fetch_cached`：`{data_cache_dir}/news/{safe_key}/{as_of}/{channel}.json`。ticker 经 `safe_ticker_component`；全局键 `_global`。历史 as-of 永久复用；当日 TTL 默认 900s。空结果不落盘。
3. akshare `get_news`：东财个股 + 巨潮公告 + 财联社个股相关电报；东财相关推荐必须标题提到代码或简称，正文仅出现简称不够（后来收紧，见 [20260920-ticker-news-relevance.md](20260920-ticker-news-relevance.md)）。`get_global_news`：联播 + 财联社/东财/新浪快讯 + 电报，全部合并而非 first-success。
4. Sentiment Analyst：`a_share_code` 命中则 `fetch_a_share_sentiment`（雪球 HTTP + 股吧/千股千评/e互动，失败降级占位）；其它市场仍 StockTwits + Reddit。不新增分析师、不走 MQ。

## 落地调用链

```
get_news / get_global_news
  → route_to_vendor 聚合 vendor
  → akshare 各 channel → news_store → dedupe_items → markdown
  → yfinance 海外头条

Sentiment (A-share)
  → get_news.func + fetch_a_share_sentiment
Sentiment (other)
  → get_news.func + StockTwits + Reddit
```
