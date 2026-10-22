# 本机 Web 操作台

- 日期：2026-09-15
- 状态：done
- 来源：plan
- 原链接：
- 关联模块：web/app.py, web/server.py, web/nginx.conf.template, Dockerfile, docker-compose.yml, cli/run_engine.py, cli/main.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：无；nginx DNS 502 见 [20260921-web-ui-options-502.md](20260921-web-ui-options-502.md)；价量 Tape 页见 [20260921-ashare-swing-tape.md](20260921-ashare-swing-tape.md)

## 结论

给 TradingAgents 增加**本机单用户**操作台，不是对外 SaaS，也不是行情数据 API。

- 入口：`pip install -e ".[web]"` 后 `tradingagents web` → `http://127.0.0.1:8000`；Docker 用**同一份** `Dockerfile` + `docker-compose.yml`，`web-ui`（静态页）和 `web-api`（FastAPI）两个服务，可一起起也可只起其中一个
- 表单对齐 CLI `analyze` 选项；密钥只读 `.env`，不进浏览器
- 跑图循环抽到 `cli/run_engine.py` 的 `run_graph_with_events`，CLI Live 与 Web SSE 共用
- 宿主机端口绑 `127.0.0.1`；容器内 API 用 `TRADINGAGENTS_WEB_BIND_ALL=1` 听 `0.0.0.0` 只给 compose 网络。进程内互斥（第二跑 409）；SSE 用线程把事件推给请求，不是 MQ / Celery
- 研究评级，永不下单。数据仍走 `route_to_vendor`

## 确认方案

```mermaid
flowchart LR
  page["static/index.html"]
  api["FastAPI local UI"]
  runner["run_graph_with_events"]
  graph["TradingAgentsGraph.stream"]
  vendors["route_to_vendor"]
  llm["create_llm_client"]

  page -->|"POST /api/runs SSE"| api
  page -->|"GET /api/options"| api
  page -->|"GET /api/runs/latest"| api
  api --> runner --> graph
  graph --> vendors
  graph --> llm
```

禁止：券商下单、把 FastAPI 当 AKShare 包装、把 API key 返回给前端、引入 Redis/Celery。SSE 用进程内线程把事件推给请求，不是 MQ。

Docker：一份 `Dockerfile`（`frontend` nginx 阶段 + `backend` Python 阶段），一份 `docker-compose.yml` 的 `web` profile。`web-ui` 反代 `/api` 到 `web-api`；`tradingagents web` 本机仍可单进程同时出页面和接口。
