# 补新闻联播与部门财经稿

- 日期：2026-10-12
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/state_media_news.py, tradingagents/agents/analysts/news_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260923-state-media-news.md](20260923-state-media-news.md)。不新开供应商，个股过滤不变

## 结论

新闻联播不能只挂在不稳定的 AKShare `news_cctv` 上。国内政策段再直接读央视栏目接口，并补四个部门公开列表：中国人民银行、财政部、国家发展改革委、国家统计局。证监会列表页停在 2021 年静态壳，这次不接。

## 确认方案

1. `news_cctv` 仍只钉 as-of 当天。新频道 `xwlb` 读 CNTV `getVideoListByColumn`（栏目 `TOPC1451528971114112`，最近 40 期）。`brief` 里的「1. …」拆成条目，日期用返回的 `time`，再走 `date_window`。同一期链接不同标题都保留。
2. 央行新闻从路径 `/113469/YYYYMMDD…/index.html` 取日期。财政部、发改委、统计局用文件名 `tYYYYMMDD_`，和中国经济网同一规则。
3. 每个页面独立失败。`get_global_news` 放进政策段。`get_news` 仍只保留点到当前代码或简称的行。

## 落地调用链

```
get_global_news / get_news
  → state_media_news
       原有：people_daily, xinhua_finance, economic_daily,
             chinanews_finance, cctv_news, gov_cn
       新增：xwlb, pbc, mof, ndrc, stats_gov
  → 新闻联播当天稿仍 news_cctv
```
