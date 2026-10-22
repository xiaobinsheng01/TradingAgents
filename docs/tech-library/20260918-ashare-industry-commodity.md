# A 股行业指数与商品合约暴露（静态表，挂 tape）

- 日期：2026-09-18
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/agents/analysts/market_analyst.py, tradingagents/agents/utils/ashare_market_tools.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260914-ashare-short-horizon-tape.md](20260914-ashare-short-horizon-tape.md)；外盘见 [20260918-intl-commodity.md](20260918-intl-commodity.md)；不替代身份卡，不建布局画像库

## 背景

`601061`（中信金属）股价受铜等原料影响，但采集层原先只有东财「行业」字符串和沪深300/创业板。模型可能按名称编铜价。需要的是点-in-time 的行业相对强弱和少量已映射商品合约，不是知识图谱。

## 确认方案

1. 静态 `match_exposure(industry, name)`：关键词先具体后宽（铜 → 有色 → 金属）。命中则给出行业指数代码（如 `sh000819`）和最多两个新浪连续合约（如 `CU0` / `AL0`）。银行名不含「白银」关键词，避免误伤。
2. 挂在现有 `get_ashare_short_horizon`，不新增分析师、不改 `route_to_vendor` except。
3. 行业序列：东财行业板 hist → 与 HS300 相同的指数日线回退。期货：`futures_zh_daily_sina` / `futures_main_sina`，只保留 `date<=as-of`。
4. 未命中或空数据写 `<unavailable>`，提示禁止编造。不是 布局 图谱，不采概念成分漫游。

## 落地调用链

```
get_ashare_short_horizon
  → _industry_from_info + 简称
  → match_exposure
  → 行业：stock_board_industry_hist_em → _fetch_index_daily(sh000819)
  → 商品：futures_zh_daily_sina(CU0/AL0) 且 date<=as-of
  → kv：industry_ret_* / stock_vs_industry_5d / commodity_*
```
