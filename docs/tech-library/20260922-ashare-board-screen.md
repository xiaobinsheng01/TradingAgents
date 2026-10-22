# 沪深主板筛选页

- 日期：2026-09-22
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/dataflows/ashare_screen.py, web/app.py, web/static/index.html, web/static/app.js
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260922-ashare-t1-playbook.md](20260922-ashare-t1-playbook.md)。单票 tape 仍不扫涨速榜，仍不下单

## 结论

操作台增加「大盘筛选」。系统扫当天涨幅榜、涨速榜和行业板块领涨，只保留沪深主板，用现有 T+1 打法给出研究立场，并贴上龙虎、增减持、融资、融券标签。点一行填入全图分析，不自动跑 LangGraph。

## 确认方案

1. `screen_main_board` 只接受 UTC 当天。历史日期在打供应商之前拒绝，避免把此刻榜单写成过去某一天。
2. 用 `a_share_board_type == main` 过滤。创业板（300/301）、科创板（688/689）、北交所和 ST 不进表。先过滤再取前排。板块领涨若本身不是主板，跳过，不把同板块第二名抬成前排。观察区沿用打法的 7%。
3. `t1_bias` 复用 `build_playbook_stance`。榜单没有近端涨停史，换手首板保持 HOLD；连板数来自当天涨停池。点进全图后，短线 tape 用日线重算并锁定评级。
4. 龙虎机构净额、增减持、融资差额、融券余量差额各拉当天或窗口表，按六位代码贴上。缺数据写「不可用」。席位净买/净卖是龙虎买卖，不是融券做空；减持不是清盘。
5. `GET /api/screen` 只给本机操作台。不挂进 Market Analyst 工具，不自动 `POST /api/runs`，不下单。点一行调用 `GET /api/screen/bars`，用 Lightweight Charts 5 画该股最近日K和成交量；「带入全图分析」才把代码交回现有跑图。

## 落地调用链

```
操作台「大盘筛选」
  → GET /api/screen
  → ashare_screen.screen_main_board
       现货涨幅/涨速 + 行业领涨 + 已有市场容错
       → build_playbook_stance
       → 龙虎机构 / 增减持 / 融资融券
  → 点一行 GET /api/screen/bars（日K，Lightweight Charts）
  → 「带入全图分析」填入代码
  → 用户再 POST /api/runs（现有全图）
```
