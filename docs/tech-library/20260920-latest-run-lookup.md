# Web 查询最近一次已落盘分析（文件，不是库）

- 日期：2026-09-20
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/reporting.py, cli/run_engine.py, web/app.py, web/static/index.html, web/static/app.js
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260915-local-web-console.md](20260915-local-web-console.md)；不引入 ORM / MQ

## 背景

分析结束后页面刷新就空了。结果其实已经落盘：memory log、`results_dir` 状态 JSON、报告树。Web/CLI Live 以前把完整报告树写到进程 cwd 的 `reports/`，Docker 里那是镜像工作目录，不在 `~/.tradingagents` 卷上。

不要新建数据库。本仓库没有 ORM。

## 确认方案

1. `run_graph_with_events` 的完整树改写到 `results_dir/reports/<ticker>_<stamp>/`（与 `TradingAgentsGraph.save_reports` 同根），并写 `run_meta.json`。
2. `reporting.load_latest_run` 按 `complete_report.md` 的 mtime 取最近一棵；可选 `ticker` 前缀过滤（先 `safe_ticker_component`）。仍扫 cwd `reports/` 以兼容旧本地跑。
3. `GET /api/runs/latest`；页面按钮「查询最近一次分析」。空则 404。研究评级，永不下单。

## 落地调用链

```
开始分析
  → write_report_tree + write_run_meta
  → ~/.tradingagents/logs/reports/<ticker>_<stamp>/   （Docker 卷）

查询最近一次
  → GET /api/runs/latest
  → load_latest_run
  → 页面报告 tabs
```
