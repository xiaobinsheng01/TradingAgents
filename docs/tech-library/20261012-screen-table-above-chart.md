# 筛选表格改到日K上面

- 日期：2026-10-12
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：web/static/index.html, web/static/app.js, tradingagents/dataflows/ashare_screen.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260923-ashare-screen-tencent-spot.md](20260923-ashare-screen-tencent-spot.md)。现货降级顺序不变

## 结论

`GET /api/screen` 在东财现货、行业板被对端断开后仍是 200。现货改新浪，行业板改同花顺。新浪全市场里沪深主板涨幅达到观察区的行已经进了 `rows`。页面把 360px 日K放在表格前面，第一屏只剩说明和「点表格中的一只」，看起来像没有可点的股票，全图按钮一直禁用。AKTools 日志里的 `RemoteDisconnected` 是东财行业板那一次请求，不是筛选接口自己崩了。

## 确认方案

1. 涨幅表放在说明下面、日K上面。「带入全图分析」跟扫描按钮放在同一行，点一行后即可用，不必先滚过空图。
2. 摘要写上「主板前排 N 只」。新浪说明改成：涨速、换手、量比三列留空，涨幅榜仍列出沪深主板。
3. 不新增现货源。东财连接失败继续按原顺序降级。

## 落地调用链

```
GET /api/screen
  → 东财现货失败 → 新浪 stock_zh_a_spot → 仍空才腾讯
  → 页面先画 rows，再画日K
  → 点一行 GET /api/screen/bars
  → 「带入全图分析」只填代码，用户再 POST /api/runs
```
