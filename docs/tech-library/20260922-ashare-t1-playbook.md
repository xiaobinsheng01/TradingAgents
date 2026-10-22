# A 股 T+1 打法立场

- 日期：2026-09-22
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_playbook.py, tradingagents/dataflows/akshare_market.py, tradingagents/agents/utils/rating.py, tradingagents/agents/analysts/market_analyst.py, tradingagents/agents/managers/portfolio_manager.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 20260914-ashare-short-horizon-tape.md 与 20260914-live-predict-no-orders.md，不替代其不下单与点-in-time 约束

## 结论

短线口播里能提高 T+1 方向命中的部分，收成 tape 上的确定性立场，并锁住最终评级。不新增会再发表意见的 LLM 节点，单票路径不扫全市场涨速榜，不把「九个点买入、拿十分钟」写成委托。操作台沪深主板筛选见 [20260922-ashare-board-screen.md](20260922-ashare-board-screen.md)。

## 确认方案

1. `build_playbook_stance` 用已有日线、涨停池、昨日溢价，加上证指数与深证 A 指成交额、中证银行相对沪深300。两市成交额约 1.3 万亿及以上且昨日溢价不为负，才是高容错。
2. 高容错下，仅换手首板（且近端有涨停史）或三板以内的换手连板给 `t1_bias: BUY`。一字、T 字、炸板、盘中 7% 观察区未封板、坏公告、ST/亏损、近 5 日解禁，一律 `HOLD`。容错不足时不给方向，因为这条路径不能判断谁是情绪龙头。
3. Market Analyst 把 `## Playbook stance (T+1)` 保留进 `market_report`。Research Manager、Trader、Portfolio Manager 用 `enforce_t1_bias` 改评级标签；报告里没有 `t1_bias` 时不改。
4. 记分卡仍是 T+1 方向。`HOLD` 不进入命中率，用来去掉薄成交里的首板追击。

## 落地调用链

```
get_ashare_short_horizon
  → ashare_playbook.build_playbook_stance
  → Market Analyst 报告保留该段
  → Portfolio Manager final_trade_decision 的 **Rating** 对齐 t1_bias
```
