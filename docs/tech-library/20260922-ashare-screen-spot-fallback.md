# 大盘筛选：东财现货 500 后走新浪，行业板走同花顺

- 日期：2026-09-22
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_screen.py, tradingagents/dataflows/akshare_market.py, web/static/app.js
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260922-ashare-board-screen.md](20260922-ashare-board-screen.md)。筛选范围、不下单、点一行再进全图不变

## 结论

`GET /api/screen` 返回 200，容错摘要仍在，表格却没有主板行。Docker 里东财 `push2` 被 RST，AKTools 把 `stock_zh_a_spot_em` 和 `stock_board_industry_name_em` 记成 HTTP 500。筛选只读这两路，空列表被页面写成「今天没有进入观察区」。全市场 `stock_ggcg_em(symbol=全部)` 再占满 30 秒超时；上交所融资明细 500 只影响融资列。

## 确认方案

1. 现货先东财 `stock_zh_a_spot_em`，空则新浪 `stock_zh_a_spot`。新浪代码 `sh`/`sz`/`bj` 前缀折成六位后再用 `a_share_board_type`。新浪没有涨速、换手、量比，涨速榜留空；振幅用最高、最低和昨收。`quote_source=sina` 写进快照说明。
2. 行业领涨先东财 `stock_board_industry_name_em`，空则同花顺 `stock_board_industry_summary_ths`（`板块` / `领涨股`）。领涨本身不是主板时仍不顺延第二名。
3. 两路现货都空时 `quote_source` 为空，页面写「现货榜没有返回」，不要声称观察区没有前排。
4. 全市场增减持仍是一条 `symbol=全部`，等待上限 8 秒；超时或上交所融资 500 继续写「不可用」，不编造增减持或融资差额。

## 落地调用链

```
GET /api/screen
  → screen_main_board
       stock_zh_a_spot_em → 空则 stock_zh_a_spot
       stock_board_industry_name_em → 空则 stock_board_industry_summary_ths
       增减持最多 8 秒；融资上交所失败仍试深交所
```
