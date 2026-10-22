# 操作台改成 A 股行情台配色

- 日期：2026-10-20
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：web/static/index.html, web/static/styles.css, web/static/app.js
- 回写文档：docs/PROJECT.md
- 替代关系：无。筛选表仍在日K上面，见 [20261012-screen-table-above-chart.md](20261012-screen-table-above-chart.md)

## 结论

本机操作台原先是通用深色后台，日K用美股绿涨红跌。A 股阅读习惯是红涨绿跌，涨跌幅也没有方向色，数字不是等宽，页头占掉第一屏。

## 确认方案

1. 日K、量柱、涨跌幅、涨速、5分钟、净买入、指数收益按数值上色：正红、负绿、零为中性灰。买入立场用红，卖出立场用绿。完成态和报错仍用系统绿/红，不跟行情色混用。
2. 页头收成一行，视图改成底边下划线。报价表表头吸顶，数字右对齐、等宽。日K高度保持 360px，表仍在图上。
3. 不改筛选、指数、跑图接口，也不改「研究评级，永不下单」。

## 落地

静态页 `web/static/`。K 线仍是 Lightweight Charts v5：`addSeries(CandlestickSeries)`，颜色常量 `QUOTE_UP` / `QUOTE_DOWN`。
