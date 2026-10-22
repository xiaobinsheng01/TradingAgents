# A 股静态暴露覆盖多行业（铜只是一例）

- 日期：2026-09-18
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/agents/analysts/market_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260918-intl-commodity.md](20260918-intl-commodity.md) 与 [20260918-ashare-industry-commodity.md](20260918-ashare-industry-commodity.md)；不建布局图谱；未列入关键词的行业仍 `<unavailable>`

## 背景

外盘铜价是例子，不是唯一路径。`能源金属` 若落到泛化「金属」会误挂沪铜。钢铁、饲料、橡胶、白酒、银行等需要各自的指数/合约行，而不是把所有股票都按 601061 处理。

## 确认方案

1. 仍是 `match_exposure` 静态表，先具体后宽。`能源金属`/`锂`/`锂电` → 碳酸锂 `LC0` + 中证新能源，**不**走沪铜。`工业金属`/`有色` 才是沪铜 + LME/COMEX。
2. 有外盘对照的板块挂国内+国际（镍 `NID`、铁矿 `FEF`、豆粕 `SM`、橡胶 `TRB`、原油/天然气 `CL`/`NG`、棉花 `CT`、原糖 `SB` 等）。没有液体外盘的（稀土、光伏、白酒、银行、证券、地产、医药）只挂行业指数，合约格为空。
3. 银行≠白银。无行业字符串的「贵州茅台」仍不命中；行业为「白酒」才挂白酒指数。
4. 空了写空，禁止按公司名编锂价/矿价。不是每家公司的 布局 爬虫。

## 落地调用链

```
get_ashare_short_horizon
  → 东财行业 + 简称
  → match_exposure（先 锂/镍/铁矿/… 后 有色/金属）
  → 行业指数 + 最多两国内 + 最多两外盘（可为空）
```
