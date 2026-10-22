# 雪球没 cookie 时用股吧帖子撑多空

- 日期：2026-10-14
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_sentiment.py, tradingagents/agents/analysts/sentiment_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260914-ashare-data-foundation.md](20260914-ashare-data-foundation.md)。不恢复已删除的 `stock_guba_em`

## 结论

雪球帖子在 `XUEQIU_COOKIE` 未设时为空。人气榜和千股千评是分数，不是帖子，报告会把零售多空写成数据缺口。东财股吧列表不需要雪球 cookie。

## 确认方案

1. 帖子先读 `https://gbapi.eastmoney.com/stkpost/api/v1/post/listbystock`。列表空或请求失败，再读 `https://guba.eastmoney.com/list,{code}.html` 里的 `article_list`。单路失败留空，不编造帖子。
2. 只保留窗口内、且股吧代码对得上当前六位代码的帖子。缓存频道 `guba_posts`。
3. 多空计数只扫这些帖子标题和正文里的看多/看空短语。同一帖两边都中算「多空都出现」。否定前缀（不/别/未/没/勿）不算命中。这不是投票，也不替换人气榜。

## 落地调用链

```
Sentiment Analyst
  → fetch_a_share_sentiment
       雪球（cookie 可选）
       东财股吧帖子 listbystock → 空则 article_list
       人气榜 / 千股千评 / e互动
```
