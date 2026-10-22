# 国内快讯补同花顺与富途

- 日期：2026-09-22
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_news.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 20260914-ashare-news-aggregation.md，不替代东财标题过滤

## 结论

国内快讯仍走 AKTools，在财联社、东财、新浪之外补同花顺 `stock_info_global_ths` 和富途 `stock_info_global_futu`。不新开供应商，不把整条快讯塞进个股新闻。

## 确认方案

1. 两条都进 `get_global_news` 的国内快讯，和现有电报一样去重、进仓库，live TTL 仍是 `news_telegraph_ttl_seconds`。
2. `get_news` 只保留标题或正文提到当前六位代码或简称的同花顺、富途行。没点名的板块电报留在全球快讯里。
3. 接口不存在或 404 时该通道为空，不中止其余源。

## 落地调用链

```
get_global_news / get_news
  → akshare_news._load_wire_items
       cls, em, sina, ths, futu
  → get_news 再按代码过滤 ths_flash / futu_flash
```
