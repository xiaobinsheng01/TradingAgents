# 国家机关媒体进入国内新闻

- 日期：2026-09-23
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/state_media_news.py, tradingagents/dataflows/akshare_news.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260914-ashare-news-aggregation.md](20260914-ashare-news-aggregation.md) 与 [20260922-ths-futu-wires.md](20260922-ths-futu-wires.md)，不替代东财标题过滤，也不新开供应商

## 结论

国内宏观在新闻联播和商业快讯之外，直接读国家机关公开列表。财经稿用经济日报社中国经济网、新华社财经和中新网财经。人民日报、央视新闻、中国政府网要闻一并进入同一政策段。

## 确认方案

1. 新闻联播仍是 AKShare `news_cctv`，只钉 as-of 当天。人民网旧 RSS 停在 2025-06，改读首页和财经频道里带 `/n1/YYYY/MMDD/` 的稿。
2. 其余机关稿走公开列表，不进 AKTools：新华社财经 `news.cn/fortune`、中国经济网滚动与财经、中新网财经 RSS、央视网要闻 JSONP、中国政府网 `YAOWENLIEBIAO.json`。
3. 每个页面独立超时和失败。一页挂了，同渠道另一页和其它机关仍保留。日期走 `date_window.in_window`，按日缓存，并写入现有 JSONL 仓库。
4. `get_global_news` 把这些渠道放在政策段，排在按关键词捞出来的商业快讯之前。`get_news` 只保留标题或正文点到当前六位代码或简称的行。

## 落地调用链

```
get_global_news / get_news
  → akshare_news._load_state_media_items
       people_daily, xinhua_finance, economic_daily,
       chinanews_finance, cctv_news, gov_cn
  → 新闻联播仍 news_cctv
  → get_news 再按代码或简称过滤机关稿
```
