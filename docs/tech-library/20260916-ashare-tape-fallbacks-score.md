# A 股 tape 东财 RST 回退；结算走 AKTools；memory 命中率

- 日期：2026-09-16
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/ashare_sentiment.py, tradingagents/graph/trading_graph.py, tradingagents/agents/utils/hit_rate.py, cli/main.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260916-ashare-tencent-hist-fallback.md](20260916-ashare-tencent-hist-fallback.md) 与 [20260914-ashare-short-horizon-tape.md](20260914-ashare-short-horizon-tape.md)；不替代 tape 特征集，也不引入封单额/逐笔

## 背景

日线已有腾讯/新浪回退，但短线主特征（指数、涨停池、分钟、盘口、北向、龙虎）仍打东财 `push2`，Docker 里 RST 后整段 `<unavailable>`。A 股 memory 结算继续走 Yahoo，pending 永远结不了，无法知道预测有没有更准。

## 确认方案

1. **Tape 回退（空了写空，禁止编）**
   - 指数：`stock_zh_index_daily_em` → `stock_zh_index_daily` / `_tx`
   - 分钟：`stock_zh_a_hist_min_em` → `stock_zh_a_minute`（`sh`/`sz`/`bj` 前缀）
   - 盘口（仅 live as-of）：`stock_bid_ask_em` → 雪球 `stock_individual_spot_xq` → 腾讯 1/5 分钟末根
   - 涨停/跌停家数：东财池失败且 **live as-of** 才用新浪 `stock_zh_a_spot` 按 ±9.5% 近似；历史 as-of 禁止用今日全市场快照（前瞻）
   - 龙虎：东财失败再 `stock_lhb_detail_daily_sina`
   - 北向个股失败再市场级 `stock_hsgt_hist_em`（仍只用 as-of 之前的会话）
2. **资讯/情绪**：个股新闻东财空时走 `stock_gsrl_gsdt_em`；雪球无 cookie 且无帖时在情绪报告里写明，禁止编帖。
3. **结算**：`_fetch_returns` 对 A 股走 `realized_holding_returns`（与 `get_stock_data` 同一日线 + 指数回退）。`601061.SH` / 北交所按 `a_share_code` 选基准，不再掉到 SPY。
4. **命中率**：`tradingagents score [TICKER]` 读 memory log。BUY/Overweight 在 raw>0 为命中，SELL/Underweight 在 raw<0 为命中；Hold 与 pending 不进方向命中率。不是可交易回测，也不下单。

## 落地调用链

```
get_ashare_short_horizon
  → 日线/指数/分钟/盘口/龙虎：东财 first-success → 腾讯/新浪/雪球
  → 涨停池：东财；live 空则新浪 spot 近似并标记 market_breadth_source

_fetch_returns (A-share)
  → realized_holding_returns → load_close_pairs / load_index_close_pairs

tradingagents score
  → TradingMemoryLog.load_entries → summarize_memory_log
```
