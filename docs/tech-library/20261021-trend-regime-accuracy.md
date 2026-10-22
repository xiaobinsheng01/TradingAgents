# 趋势 regime 收紧 + swing trend_bias 锁定评级

- 日期：2026-10-21
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_trend_bias.py, tradingagents/dataflows/ashare_market_mood.py, tradingagents/dataflows/ashare_trend_predict.py, tradingagents/dataflows/akshare_market.py, tradingagents/agents/utils/rating.py, tradingagents/agents/utils/hit_rate.py
- 回写文档：docs/PROJECT.md
- 替代关系：扩展 20261021-playbook-t1-accuracy-tightening.md（T+1 与趋势分层）

## 结论

阴跌个股仍被「下沿反弹 / 相对强」标多，源于趋势规则缺少 **指数/行业 regime** 与 **下行段 veto**。将趋势逻辑抽到 `ashare_trend_bias.py`，swing tape 与 Web 趋势页共用；LangGraph 读 `trend_bias: SELL` 时 PM 评级不得比 Sell 更偏多。

## 确认方案

1. **趋势 BUY 收紧**：沪深300 20 日或窗口偏空、缠论下行段、近 5/10 日持续弱、行业近 5 日弱且个股仍跌 → 禁止下沿/缠论 BUY，必要时 SELL。
2. **swing tape**：价量块后增加 `Swing trend stance`，含 `trend_bias` / `trend_reason`。
3. **predict 图**：`combine_deterministic_bias(t1, trend)`；仅 `trend_bias: SELL` 时压过更偏多的 `t1_bias`。
4. **记分**：`summarize_memory_log` 增加 `t1_by_rating`；CLI `score` 打印 Buy/Sell 分组 T+1 命中率。

## 落地

`compute_trend_bias` ← `ashare_trend_predict.stock_trend_row`、`get_ashare_swing_tape`；`deterministic_bias_from_text` ← `enforce_t1_bias`。

## 后续（同日前扩）

`ashare_market_mood.py`：`resolve_market_mood` + `blend_stock_with_market_mood`；无 `announce_bad/good` 时全市场情绪可带动 HOLD→方向。短线 tape 写 `Market mood (全市场)` 并与 playbook `t1_bias` 合并；趋势/swing 与 `mood_swing` 合并。
