# A 股日线：东财 RST 后走腾讯/新浪；Yahoo 不再打 A 股

- 日期：2026-09-16
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/symbol_utils.py, tradingagents/dataflows/y_finance.py, tradingagents/dataflows/yfinance_news.py, docker-compose.yml
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：补充 [20260916-ashare-docker-vendor-llm.md](20260916-ashare-docker-vendor-llm.md) 与 [20260915-akshare-aktools-http.md](20260915-akshare-aktools-http.md) 中「Docker 东财 RST 只能改宿主机 pip」的运行时注意

## 结论

`601061.SH` 分析失败不是 AKShare 版本过低（sidecar 已是 1.18.94）。三件事叠在一起：

1. Docker Desktop 跑的 `tradingagents` 镜像仍是旧代码：`core_stock_apis=yfinance`，没有 `get_akshare_stock_data`。行情先打 Yahoo，`.SH` 404，再 429 重试把图拖到 10 分钟以上。旁白里「换成 AAPL / 等 Yahoo」不是本仓库 UI。
2. 东财 `stock_zh_a_hist`（`push2his`）在 Docker 里立刻 `RemoteDisconnected`，AKTools 表现为 HTTP 500。同容器里 `stock_zh_a_hist_tx` / `stock_zh_a_daily`（`symbol=sh601061`）正常。
3. `get_news` 聚合链仍会打 Yahoo；A 股没有英文覆盖，只会 404/429。

## 确认方案

1. `_fetch_daily`：先 `stock_zh_a_hist`（六位），失败再 `stock_zh_a_hist_tx` / `stock_zh_a_daily`（`sh`/`sz`/`bj` 前缀）。
2. A 股 ticker 的 yfinance 价格 / 指标 / 基本面 / 个股新闻立刻 `NoMarketDataError`，不发 HTTP。全球新闻遇到 429 不再指数退避，直接 `VendorRateLimitError`，akshare 块仍保留。
3. 必须 `--build --force-recreate` `tradingagents` / `web-api` / `web-ui`；旧镜像不会读到仓库里的默认链。`web-api` 的 `AKSHARE_BASE_URL` 必须是 `http://aktools:8080`。
