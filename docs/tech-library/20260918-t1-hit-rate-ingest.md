# A 股 T+1 命中率、live ingest、雪球 token 与商品符号回退

- 日期：2026-09-18
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/agents/utils/hit_rate.py, cli/main.py, tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/ashare_sentiment.py, tradingagents/dataflows/news_ingest.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260916-ashare-tape-fallbacks-score.md](20260916-ashare-tape-fallbacks-score.md) 的命中率口径与 [20260918-ashare-industry-commodity.md](20260918-ashare-industry-commodity.md) 的拉取回退；不替代 5 日 memory 结算，也不引入 worker / 下单

## 背景

预测目标是下一可交易日（T+1），但 `tradingagents score` 只读 memory 里 5 日持有 raw。指数空时 `realized_holding_returns` 连 T+1 都结不了。live 跑图时仓库常空，事件旗标全假。雪球接口常要 `xq_a_token`。Docker 里行业指数 `sh000819` 与新浪 `CU0` 可能空，tape 上铜价/有色指数变成 `<unavailable>`。

## 确认方案

1. **T+1 主指标**：`next_session_raw_return` 只用股票下一根前复权收盘（`len>=2`），不要指数。`summarize_memory_log` 在有下一根时给 pending 也打 T+1 方向命中。5 日已结算 raw 仍打印，但是辅。Hold 不计。不是成交回报，也不下单。
2. **live ingest**：`_event_flags` 仅在 `is_live_as_of` 且仓库空时一次性 `ingest_news`（含 global）。历史 as-of 禁止，避免前瞻。失败记日志，旗标保持空。
3. **雪球**：把 session cookie / `Cookie` 头里的 `xq_a_token` 带到查询参数；无 token 时再暖 `https://xueqiu.com/S/{SH600519}`。股吧通道加 `stock_new_guba_em`。
4. **行业/商品符号**：CSI 指数 `sh000819` 空再试 `000819`；新浪连续合约空再试东财 `futures_hist_em`（`CU0`→`CU`）。空了写空，禁止编铜价。

## 落地调用链

```
tradingagents score
  → summarize_memory_log(next_session_loader=fetch_next_session_return)
  → next_session_raw_return → load_close_pairs（只要股票下一根）
  → 辅：memory 已结算 5 日 raw

get_ashare_short_horizon live + 空仓库
  → _event_flags → ingest_news → query_items

_fetch_xueqiu
  → homepage / env cookie → xq_a_token query param → 股票页暖会话

_fetch_industry_series / _fetch_futures_daily
  → 东财板 / 新浪期货 first-success → 无前缀指数 / futures_hist_em
```
