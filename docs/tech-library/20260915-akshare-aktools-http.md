# 本地 AKTools HTTP（Docker akshare）

- 日期：2026-09-15
- 状态：done
- 来源：agent-discussion
- 原链接：https://aktools.akfamily.xyz/aktools/
- 关联模块：tradingagents/dataflows/akshare_news.py, tradingagents/default_config.py, docker-compose.yml
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 akshare extra 接入方式，不改 `route_to_vendor`

## 结论

本机 `aktools:jupyter` 容器只提供 Jupyter Lab（`:8888`），**不是**数据 HTTP API。A 股 vendor 要打 AKTools：

`GET {base}/api/public/<akshare接口>?kw=...`

例如 `http://127.0.0.1:8080/api/public/stock_zh_a_hist?symbol=600519`。

## 确认方案

1. `_load_akshare`：若 `akshare_base_url` / `AKSHARE_BASE_URL` / `TRADINGAGENTS_AKSHARE_BASE_URL` 有值，返回 `AktoolsHttpClient`（duck-typed，现有 `ak.stock_*` 调用不用改）。否则再 `import akshare`。两者都没有 → `AkshareNotConfiguredError`。
2. 本仓库不在进程内起 Flask。compose profile `akshare` 构建 [`docker/aktools.Dockerfile`](../../docker/aktools.Dockerfile)（`akshare>=1.16` + 首页 sitecustomize），映射 `:8080`。不要直接跑冻结的官方 `akfamily/aktools:1.8.95`（里面是 akshare 1.8.94，会把 `symbol=000001` 判为非法参数）。
3. Jupyter `:8888` 可继续留给手工探接口，预测跑 HTTP `:8080`。

## 运行时注意

- 官方 `aktools:latest` 是裸 Python 镜像，容器会立刻退出；官方版本标签 `aktools:1.8.95` 冻结在 akshare 1.8.94。compose 改为构建本仓库 sidecar。
- 镜像自带的旧 `aktools` 在 `GET /` 和 `GET /version` 会去刮 `pypi.org` HTML。页面改版或容器出不去网时 `get_latest_version` 抛 `AttributeError: 'NoneType' object has no attribute 'text'`（[akfamily/aktools#179](https://github.com/akfamily/aktools/issues/179)）。这不是数据接口挂了。sidecar 用 `sitecustomize` 把该函数打成 `"offline"`；健康检查打 `/docs`。本机验证用 `GET http://127.0.0.1:8080/docs` 或 `GET http://127.0.0.1:8080/api/public/stock_news_em?symbol=000001`，不要打开首页 `/` 当探活。
- Docker 内访问东财 `push2his` / 部分 `push2` 行情（`stock_zh_a_hist`、`stock_bid_ask_em`、`stock_zh_a_spot_em`）可能被对端 RST，表现为 AKTools `500 Internal Server Error`。新闻类接口仍可用。日线已回退到 `stock_zh_a_hist_tx` / `stock_zh_a_daily`（见 [20260916-ashare-tencent-hist-fallback.md](20260916-ashare-tencent-hist-fallback.md)）。其余东财频道仍会降级。不要把 Jupyter `:8888` 当 API。
