# 海外全球新闻改走 Google Search，并用 site: 补公开社媒

- 日期：2026-09-20
- 状态：done
- 来源：agent-discussion
- 原链接：https://serper.dev/
- 关联模块：tradingagents/dataflows/google_news.py, tradingagents/dataflows/interface.py, tradingagents/default_config.py, tradingagents/agents/analysts/news_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：海外 `get_global_news` 不再默认 Yahoo Search（[20260914-ashare-news-aggregation.md](20260914-ashare-news-aggregation.md) 的 yfinance 全球头条）；国内联播仍走 akshare。检索客户端定为 Serper，不再用 Google CSE。

## 背景

A 股分析需要海外市场与宏观（美盘、联储、商品、关税）来判断对国内交易时段的影响。原先 `get_global_news` 海外腿是 yfinance Search，覆盖弱，也没有 X / YouTube / Meta 公开讨论。不能爬这些平台的私有 API，也不要把全球电线塞进 `get_news`。

## 确认方案

1. 新 vendor `google` 只实现 `get_global_news`。默认 `tool_vendors.get_global_news = akshare,google`。`get_news` 仍 `akshare,yfinance`。
2. 有 `SERPER_API_KEY`（别名 `TRADINGAGENTS_SERPER_API_KEY`）时走 Serper：头条 `POST https://google.serper.dev/news`，平台帖 `POST https://google.serper.dev/search` + `site:`。无密钥时退 Google News RSS。
3. 查询词偏向「会影响 A 股的海外变量」，不是任意世界新闻。News Analyst 只引用与该标的或中国交易时段相关的条目。
4. Google 索引没有 as-of vintage：历史运行只读缓存，禁止打实时搜索。
5. 不接 X/Meta Graph、不刮站、不加 MQ。不使用 Google CSE JSON。

## 落地调用链

```
get_global_news
  → akshare：联播 + 国内快讯（点-in-time）
  → google：Serper（无密钥则 News RSS）+ site: 平台
  → news_store `_global/<as_of>/google_search.json`
  → 聚合 ## Source: google
```
