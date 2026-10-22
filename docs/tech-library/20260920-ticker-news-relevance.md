# 个股新闻不要把东财相关推荐当本公司新闻

- 日期：2026-09-20
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_news.py, tradingagents/agents/analysts/news_analyst.py, tradingagents/agents/utils/news_data_tools.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：收紧 [20260914-ashare-data-foundation.md](20260914-ashare-data-foundation.md) 的 `get_news` 相关性；不取消 `get_global_news`

## 背景

News Analyst 抓到与当前标的无关的资讯。根因有两层：

1. 东财 `stock_news_em` 给相关推荐里每一行都打上「关键词=查询代码」，旧过滤把 keyword==code 当成命中，行业/ETF/别家公司新闻会进 `get_news`。
2. 分析师提示词要求写「全世界状态」并调用 `get_global_news`（联播/全市场快讯），模型容易把宏观电线当成本公司新闻。

全市场政策仍应走 `get_global_news`，不要塞进个股工具。

## 确认方案

1. `get_news` 东财条目须标题提到六位代码或股票简称；正文仅出现简称不够（相关推荐页脚会重复该标的），正文出现六位代码仍保留。巨潮按代码接口的公告除外。仓库里未提及该标的的电报同样丢掉。
2. 简称来自 `stock_individual_info_em`，没有简称时只靠代码匹配，禁止编造公司名。
3. News Analyst：`get_news` 为主；`get_global_news` 只引用明显影响该代码/简称的条目。

## 落地调用链

```
get_news(ticker)
  → stock_news_em / 巨潮 / CLS
  → 东财：标题含 code/简称，或正文含六位代码（公告除外）
  → warehouse 再滤一遍
  → markdown

get_global_news
  → 仍是联播 + 国内快讯（市场级）
```
