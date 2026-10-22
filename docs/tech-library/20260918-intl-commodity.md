# A 股 tape 外盘商品（LME/COMEX/NYMEX）

- 日期：2026-09-18
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/agents/analysts/market_analyst.py, tradingagents/agents/utils/ashare_market_tools.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260918-ashare-industry-commodity.md](20260918-ashare-industry-commodity.md)；不替代国内沪铜/沪铝，不建布局图谱，不打 Yahoo `HG=F`

## 背景

`601061` 等有色股除受沪铜影响外，还受伦敦/纽约铜价涨跌影响。原先 `match_exposure` 最多两个**国内**连续合约（`CU0`/`AL0`），模型看不到外盘，容易按名称编伦铜。

## 确认方案

1. 静态表增加 `intl_commodities`（最多两个）。铜/有色/工业金属 → LME `CAD` + COMEX `HG`；其它品种见 [20260918-exposure-sector-coverage.md](20260918-exposure-sector-coverage.md)。空合约的板块只挂行业指数。
2. 仍挂 `get_ashare_short_horizon`，不新增分析师、不走 yfinance。
3. 拉取：`futures_foreign_hist`（新浪外盘日线）→ 东财中文名 `futures_global_hist_em`（`LME铜`）。只保留 `date<=as-of`，外盘未收盘也不把未来 K 写进历史 as-of。
4. 空了写 `<unavailable>`，提示禁止编 伦铜 / COMEX。国内两格不变。

## 落地调用链

```
get_ashare_short_horizon
  → match_exposure
  → 国内：futures_zh_daily_sina(CU0) → futures_hist_em
  → 外盘：futures_foreign_hist(CAD/HG) → futures_global_hist_em(LME铜/COMEX铜)
  → kv：commodity_* + intl_commodity_*
```
