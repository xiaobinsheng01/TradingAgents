# T+1 预测规则收紧（提高命中率）

- 日期：2026-10-21
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_playbook.py, tradingagents/dataflows/ashare_trend_predict.py, tradingagents/dataflows/ashare_screen.py
- 回写文档：docs/PROJECT.md
- 替代关系：扩展 20260922-ashare-t1-playbook.md 与 20261021-ashare-tomorrow-rise-no-chinext.md

## 结论

在原有「高容错 + 换手板 + 连板 ≤3」框架上，增加**可观测的宏观/情绪门槛**与**龙虎净卖否决**，减少薄溢价、弱指数、涨停家数过少时的 BUY。趋势预测页把缠论三类买卖候选纳入 `_trend_bias`，并抑制区间上沿追涨。

## 确认方案

1. **Playbook BUY 前置**：昨日涨停溢价必须已知且 ≥0.3%；三板及以上溢价 ≥1.0%；涨停家数 ≥15；沪深300 1日 ≤−1% 时不给 BUY；连板（≥2）且龙虎机构净卖为负时 HOLD。
2. **明日上涨列表**：BUY 行按龙虎净买、连板数、涨幅降序排序。
3. **趋势预测**：`三类卖点候选` → SELL；`三类买点候选` 在区间位置/相对300/近5日回撤过滤后 → BUY；强相对300 的 BUY 要求区间位置 <90%。

## 落地

`build_playbook_stance(..., lhb_net_buy=)`；筛选页传入当日龙虎净买。`stock_trend_row` 传入缠论 `buy_sell` 与末段方向。
