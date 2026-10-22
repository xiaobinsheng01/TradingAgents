# A 股身份卡 + 校验快照与 get_stock_data 同源

- 日期：2026-09-16
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/stockstats_utils.py, tradingagents/agents/utils/agent_utils.py, tradingagents/graph/trading_graph.py, tradingagents/dataflows/market_data_validator.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：扩展 [20260916-ashare-tencent-hist-fallback.md](20260916-ashare-tencent-hist-fallback.md)；不替代 tape 方案

## 结论

完整「公司画像库」不做。落地两件事，让采集和分析用同一套公开日线与同一套交易规则：

1. **身份卡**：`resolve_instrument_identity` 对 A 股走 `resolve_a_share_identity`（AKTools 简称/行业，失败不编造公司名）+ 句法 `board_type` / `exchange`。`instrument_identity_for_run` 按 as-of 附上 `limit_pct`。不打 Yahoo `info`。
2. **校验快照同源**：`load_ohlcv` 对 A 股调用 `get_akshare_stock_data`（东财 → 腾讯/新浪），`get_verified_market_snapshot` 不再单独打 Yahoo。

## 确认方案

```
resolve_instrument_context(ticker, asset_type, trade_date)
  → instrument_identity_for_run
       → A 股：resolve_a_share_identity + a_share_limit_pct(as_of)
       → 其它：yfinance info
  → build_instrument_context

get_verified_market_snapshot
  → load_ohlcv
       → A 股：get_akshare_stock_data（与 get_stock_data 相同日线）
       → 其它：yfinance download
```
