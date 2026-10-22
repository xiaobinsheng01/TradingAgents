# A 股价量 Tape 挂缠论结构

- 日期：2026-09-21
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/chanlun.py, tradingagents/dataflows/akshare_market.py, tradingagents/agents/analysts/market_analyst.py, tradingagents/agents/utils/ashare_market_tools.py, web/static/index.html
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260921-ashare-swing-tape.md](20260921-ashare-swing-tape.md)

## 结论

价量 Tape 的后续走势研究需要缠论结构（分型 / 笔 / 线段 / 中枢），但 15 个日历日不够成段。缠论对 **as-of 前 250 个日历日** 的已收盘日线做包含处理，价量/新闻窗口仍是 `half_month` / `half_year`。仍走 `get_ashare_swing_tape`，不新开行情 HTTP，不另加依赖库。

## 确认方案

1. 纯函数 `dataflows/chanlun.py`：包含关系 → 确认分型（右翼必须已收盘）→ 笔（分型核间距 ≥ 2）→ 特征序列线段 → 三笔/三段重叠中枢。无 I/O。
2. 日线不够成笔则 `NO_DATA_AVAILABLE`，禁止编造中枢/买卖点。只输出机械 **三类买卖点候选**（离开中枢后回抽未跌回），一类/二类不做 MACD 背驰猜测。
3. 周线用真正的周 OHLC（不是周内最后一根日线）；周 K ≥ 8 根才附周线缠论。
4. Market Analyst 把缠论当结构证据；三类候选是研究备注，不是委托。Web 价量页文案带「缠论分型/笔/段/中枢」。

```
get_ashare_swing_tape
  → 窗口价量 + 机构出手 + 新闻
  → chanlun.render from date<=as-of 250d daily
  → optional weekly 缠论
  → Market Analyst subsequent-trend
```

禁止：FastAPI 当缠论 API、用未来 K、把买卖点当订单、引入 czsc/第三方缠论包。
