# A 股近半个月 / 近半年价量 Tape

- 日期：2026-09-21
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/akshare_flow.py, tradingagents/dataflows/chanlun.py, tradingagents/agents/utils/ashare_market_tools.py, tradingagents/agents/analysts/market_analyst.py, tradingagents/agents/analysts/news_analyst.py, web/static/index.html, web/static/app.js, cli/run_engine.py, tradingagents/reporting.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260914-ashare-short-horizon-tape.md](20260914-ashare-short-horizon-tape.md)

## 结论

短线 tape（T+1 / 5–20 日）不够覆盖「近半个月 / 近半年」价量、机构出手与新闻。新增 `get_ashare_swing_tape`，仍走 `ashare_tape` / `route_to_vendor`。Web「价量 Tape」页选窗口后 **仍 `POST /api/runs`**（含 News Analyst），不新开行情 HTTP。

## 确认方案

1. 窗口：`half_month` = 15 个日历日；`half_year` = 180 个日历日。只保留 `date<=as-of` 的已打印 K 线，不编造停牌日。
2. 价量：区间涨跌、高低点、均量/量比、成交额、换手分位、涨停/跌停天数、相对沪深300；半年再附周线末根。
3. 机构出手：复用 `akshare_flow.render_buy_sell_window`（增减持 / 龙虎 / 大宗，按六位代码过滤）。空则 `NO_DATA_AVAILABLE`。
4. 窗口新闻：同一 `[start, as-of]` 走 `akshare_news.get_news`（个股/公告）和 `get_global_news`（国内政策/快讯，look_back=窗口日历日）。失败不中止价量。News Analyst 按 `half_month`=15 日 / `half_year`=180 日拉 `get_news`，不再固定「过去一周」。价量页强制包含 news 分析师并 ingest。
5. 缠论：同一 `get_ashare_swing_tape` 对 as-of 前 250 个日历日日线做分型/笔/段/中枢（`dataflows/chanlun.py`）。15 日窗口不够成段，故结构回看长于价量窗口。空则 `NO_DATA_AVAILABLE`。三类买卖点只作候选。永不下单。
6. Market Analyst `bind_tools` + ToolNode 对齐。`run_engine` 对 A 股预取 tape，写入报告树 `1_analysts/swing_tape.md`，再跑图做后续走势研究评级。永不下单。

```
Web 价量 Tape
  → POST /api/runs (swing_tape_window)
  → run_engine prefetch get_ashare_swing_tape
  → Market Analyst + News/Fundamentals
  → 研究评级（不是委托）
```

禁止：把 FastAPI 当 AKShare 包装、编造价格或出手或标题或缠论中枢、把半年窗口当前日 live 快照、News Analyst 在 swing 窗口下仍只拉过去一周。
