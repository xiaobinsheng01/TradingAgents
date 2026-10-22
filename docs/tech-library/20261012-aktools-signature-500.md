# AKTools 500/404：按现行 AKShare 签名调用

- 日期：2026-10-12
- 状态：done
- 来源：bugfix
- 原链接：https://akshare.akfamily.xyz
- 关联模块：tradingagents/dataflows/ashare_sentiment.py, tradingagents/dataflows/akshare_flow.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/akshare_fundamentals.py, tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/google_news.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, docs/agent-rules/api-layer.md
- 替代关系：补充 [20260920-ashare-buy-sell-flow.md](20260920-ashare-buy-sell-flow.md)、[20260920-ticker-scoped-nodes.md](20260920-ticker-scoped-nodes.md)。不改 `route_to_vendor`

## 根因

AKTools HTTP 客户端对任意名字都发 `GET /api/public/<name>`。函数不存在是 404「未找到该接口」。函数存在但关键字不是它的参数时，sidecar 里的 `TypeError` 变成 **HTTP 500 Internal Server Error**，调用方看不到 `TypeError`，于是不会走原来的改参分支，而是把股票代码传进不接受它的接口。

对照现行 AKShare 文档，601061 这次日志里对得上的是：

| 日志 | 实际签名 |
| --- | --- |
| `stock_guba_em` / `stock_zh_guba_em` / `stock_new_guba_em` / `stock_comment_detail_zhpj_lte_em` 404 | 这些名字不存在。人气用 `stock_hot_rank_detail_em` / `stock_hot_keyword_em`（`SH601061`）。综合评价历史评分是 `stock_comment_detail_zhpj_lspf_em` |
| `stock_comment_em` 500 | 无参数。`symbol=601061` 非法 |
| `stock_zh_a_disclosure_report_cninfo` 500 | `market` 只能是 `沪深京` 等，不是 `sse` |
| `stock_ggcg_em` 日志落到 `stock_changes_em` 500 | `stock_ggcg_em(symbol=)` 只能是 `全部` / `股东增持` / `股东减持`。`stock_changes_em` 是盘口异动（`大笔买入` 等），不是增减持 |
| `stock_lhb_detail_daily_sina` 500 | 只接受 `date`。席位详情要 `symbol` + `date` + `flag=买入/卖出`。列表 `stock_lhb_detail_em` 只要 `start_date`/`end_date` |
| `stock_individual_info_em` 500 | 东财 push2 不稳定。再试 `stock_profile_cninfo`、雪球 `stock_individual_basic_info_xq` |
| `stock_zh_a_hist` 500 | 东财日线仍会失败。已有腾讯/新浪回退；失败记 info，两路都空才 warning |
| 雪球 `Expecting value` | HTTP 200 但 body 为空，不是 JSON |
| Google / Serper `Network is unreachable` / read timeout | 这台机器到 `news.google.com`、`google.serper.dev` 的网络，不是 AKShare |

## 确认方案

1. 每个接口只传文档上的参数，不再把同一组 kwargs 套到所有名字上。
2. `stock_comment_em()` 无参调用后按六位代码过滤。其它接口 `TypeError` 后仍然禁止无参全表。
3. 增减持优先交易所 `stock_share_hold_change_sse` / `szse` / `bse`。
4. 简介：东财 → 巨潮概况 → 雪球简介。不用全市场代码简称表冒充个股简介。
5. 海外 Google/Serper 一旦网络不可达或读超时，本轮剩余查询不再打。国内 akshare 宏观源不受影响。

## 落地调用链

```
fetch_a_share_sentiment
  雪球 HTTP（空 body 直接空，不 json()）
  stock_hot_rank_detail_em / stock_hot_keyword_em  symbol=SH601061
  stock_comment_em() 再按代码过滤
  stock_comment_detail_*_em(symbol=六位)

get_insider_transactions
  stock_share_hold_change_{sse,szse,bse}(symbol=六位)
  空则 stock_ggcg_em(symbol=股东增持|股东减持)
  龙虎 stock_lhb_detail_em(start_date, end_date)
  空则 stock_lhb_stock_detail_em(symbol, date, flag)
  再空则 stock_lhb_detail_daily_sina(date)

get_news 巨潮
  stock_zh_a_disclosure_report_cninfo(symbol, market=沪深京, start_date, end_date)

get_fundamentals 简介
  stock_individual_info_em → stock_profile_cninfo → stock_individual_basic_info_xq
```
