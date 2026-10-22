# 明日上涨扫描（排除创业板）

- 日期：2026-10-21
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_screen.py, tradingagents/dataflows/ashare_trend_predict.py, web/app.py, web/static/
- 回写文档：docs/PROJECT.md
- 替代关系：扩展 20260922-ashare-board-screen.md 与 20260922-ashare-t1-playbook.md，不替代其 T+1 规则

## 结论

操作台需要「预测明天上涨」的批量能力，但**创业板不参与**。沿用当天涨幅/涨速/领涨观察区与 `build_playbook_stance` 的 T+1 BUY，不跑 LangGraph，不下单。

## 确认方案

1. `screen_tomorrow_rise`：`universe=no_chinext`（科创板、北交所在表内），`only_t1_bias=BUY`；现货/行业/容错与 `screen_main_board` 共用 `_load_screen_market_bundle`。
2. 操作台新页「明日上涨」：`GET /api/tomorrow-rise`；日K仍走 `GET /api/screen/bars`，创业板拒绝。
3. 多票趋势预测 `stock_trend_row` 对创业板代码直接 `ValueError`，与批量扫描口径一致。

## 落地调用链

```
GET /api/tomorrow-rise
  → screen_tomorrow_rise
       → _load_screen_market_bundle（与 /api/screen 同源）
       → build_screen_snapshot(universe=no_chinext, only_t1_bias=BUY)
            → select_candidates + build_playbook_stance
```
