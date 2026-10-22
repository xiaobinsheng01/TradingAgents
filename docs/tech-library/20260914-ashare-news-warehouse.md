# A 股资讯仓库、电报新鲜度与雪球会话

- 日期：2026-09-14
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/news_warehouse.py, tradingagents/dataflows/news_ingest.py, tradingagents/dataflows/news_store.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/ashare_sentiment.py, cli/main.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：扩展 [20260914-ashare-data-foundation.md](20260914-ashare-data-foundation.md)，不替代按日 JSON 缓存或供应商聚合合同

## 背景

数据底座落地后仍缺三件事：雪球常因缺会话 cookie 变成 `<unavailable>`；当日电报被 900s 快照拖住；跨次 ingest 没有累积，只能看这一次 as-of 缓存。

约束：不引入 MQ、cron、daemon。一次性 CLI 可以。

## 确认方案

1. 雪球：`XUEQIU_COOKIE` 或 `TRADINGAGENTS_XUEQIU_COOKIE`；补 `Origin` / `Referer`；无 cookie 时先 GET 首页预热；HTTP 400/401/403 打日志后返回空列表，禁止编造帖子。
2. 本地仓库：`{data_cache_dir}/news/_warehouse/{safe_key}.jsonl`，append-only，`item_identity` 去重，查询走 `in_window`。`get_news` / `get_global_news` 合并 warehouse ∪ 当日拉取。`_warehouse` 与 `_global` 一样是保留键。
3. 电报新鲜度：live as-of 的 CLS/东财/新浪快讯 TTL 为 `news_telegraph_ttl_seconds`（默认 120s）；历史 as-of 仍忽略 TTL。
4. CLI `tradingagents ingest-news [TICKER] [--global] [--date]` 走 `news_ingest.ingest_news`，一次拉取后 upsert。调度由调用方（例如自己的 cron）负责，进程内不常驻。

## 落地调用链

```
ingest-news / get_news / get_global_news
  → collect_*_news_items（news_store，电报短 TTL）
  → upsert_items JSONL
  → query_items + in_window + dedupe
  → markdown

Sentiment (A-share Xueqiu)
  → _xueqiu_session（cookie 或首页预热）
  → 400/401/403 或网络失败 → 空列表
```
