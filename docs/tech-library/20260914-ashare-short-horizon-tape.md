# A 股短线 tape（次日 / 5–20 日）

- 日期：2026-09-14
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/agents/utils/ashare_market_tools.py, tradingagents/agents/analysts/market_analyst.py, tradingagents/dataflows/symbol_utils.py, tradingagents/dataflows/interface.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：扩展资讯底座；`get_stock_data` 默认链后来改为 `akshare,yfinance`（见 [20260916-ashare-docker-vendor-llm.md](20260916-ashare-docker-vendor-llm.md)），tape 本身不改；近半个月/近半年价量见 [20260921-ashare-swing-tape.md](20260921-ashare-swing-tape.md)

## 背景

LLM 研报原先只有 Yahoo 日线 + PE 三表 + 中文新闻。A 股短线（明天方向/涨停、5–20 日相对强弱）的主数据应是价量规则、交易限制、资金、板块情绪、事件，而不是估值。

## 确认方案

1. 新方法 `get_ashare_short_horizon`，新类别 `ashare_tape`（默认 `akshare`），走 `route_to_vendor`。不新增分析师，不改 `route_to_vendor` 的 except 形状。
2. 挂在 Market Analyst 的 ToolNode。提示词：A 股先拉 tape，PE/PB **不是** 次日主特征；涨停封板按买不到。
3. 日线：前复权 OHLC 算涨跌，成交额/量/换手优先未复权。`a_share_limit_pct` 区分主板 10%、创业/科创 20%、北交 30%、ST 5%。收盘涨跌幅触板 → `limit_up` / `limit_down`；没有封单额。
4. 点-in-time：日线与涨跌停用 as-of 收盘预测下一可交易日；北向只用 as-of **之前**已公布会话；龙虎榜用 as-of 盘后榜预测次日；解禁看未来 5/20 个日历日。
5. `ashare_tape` 列入 `OPTIONAL_CATEGORIES`：未装 `[akshare]` 时 `DATA_UNAVAILABLE`，美股运行不中止。
6. 明确不做：高频逐笔、完整封单、股东户数周频、分析师一致预期、把 FRED/三表当明天主输入。

## 落地调用链

```
Market Analyst
  → get_stock_data / get_indicators（yfinance，兼容原路径）
  → get_ashare_short_horizon
       → route_to_vendor(ashare_tape / akshare)
       → akshare_market：日线 + 涨停池 + 指数 + 滞后北向 + 龙虎 + 解禁 + warehouse 事件
       → news_store.fetch_cached_records
```
