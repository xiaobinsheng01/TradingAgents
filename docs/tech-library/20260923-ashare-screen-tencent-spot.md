# 大盘筛选：新浪现货也 500 时走腾讯

- 日期：2026-09-23
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_screen.py, web/static/app.js
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260922-ashare-screen-spot-fallback.md](20260922-ashare-screen-spot-fallback.md)。行业板同花顺回退、不下单、点一行再进全图不变

## 结论

`GET /api/screen` 仍是 200，但东财 `stock_zh_a_spot_em` 和新浪 `stock_zh_a_spot` 在 AKTools 容器里都被对端 RST，现货两路都空，页面写成「现货榜没有返回」。同一次请求里同花顺行业一览 `stock_board_industry_summary_ths` 是 200。腾讯 `stock_zh_a_spot_tx`（`proxy.finance.qq.com`）在同一容器里能返回全市场榜。

News Analyst 的 `OpenAIConnectionError` 是另一次跑图：容器里 `getaddrinfo` 报 `Name or service not known`，豆包默认主机 `ark.cn-beijing.volces.com` 当时解析失败。事后同一容器可以解析该主机。这不是筛选接口的 500。

龙虎日志里的 `stock_lhb_detail_em` 500 有两层：东财 `start_date`/`end_date` 本身 RST，另外把 `date=` 传给不接受该参数的接口，AKTools 记成 TypeError 500。上交所融资明细 500 仍是空表列数不匹配，增减持 8 秒超时仍写不可用。

## 确认方案

1. 现货顺序：东财 `stock_zh_a_spot_em` → 新浪 `stock_zh_a_spot` → 腾讯 `stock_zh_a_spot_tx`。
2. 腾讯 `code` 的 `sh`/`sz`/`bj` 前缀沿用现有六位折算。`turnover` 按万元、`ltsz` 按亿元换成元，再进成交额和流通市值。涨速、换手、量比保留。没有今开、最高、最低、昨收时振幅用 `zf`。`quote_source=tencent`。
3. 三路都空时 `quote_source` 仍为空，页面继续写「现货榜没有返回」。
4. 龙虎只向东财机构净额和明细传 `start_date`/`end_date`，不再传 `date`。

## 落地调用链

```
GET /api/screen
  → screen_main_board
       stock_zh_a_spot_em → 空则 stock_zh_a_spot → 空则 stock_zh_a_spot_tx
       stock_board_industry_name_em → 空则 stock_board_industry_summary_ths
       龙虎 start_date/end_date；增减持最多 8 秒
```
