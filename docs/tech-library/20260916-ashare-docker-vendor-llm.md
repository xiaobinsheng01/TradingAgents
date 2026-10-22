# A 股日线先走 AKTools；Docker 不要用 127.0.0.1

- 日期：2026-09-16
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：docker-compose.yml, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/akshare_market.py, tradingagents/dataflows/symbol_utils.py, tradingagents/dataflows/interface.py, web/static/app.js
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：修正 [20260914-ashare-short-horizon-tape.md](20260914-ashare-short-horizon-tape.md) 中「get_stock_data 只走 yfinance」；tape 方案本身仍有效

## 结论

AKTools 首页显示 akshare **1.18.94** 已经够用。`latest = offline` 是 sitecustomize，不是版本过低。

A 股分析仍打 Yahoo，是因为：

1. `web-api` 读宿主机 `.env` 的 `AKSHARE_BASE_URL=http://127.0.0.1:8080`，容器里 127.0.0.1 是自己，AKTools 根本连不上，新闻/tape 失败后聚合链落到 yfinance。
2. 默认 `core_stock_apis` / `technical_indicators` 以前只有 yfinance；Market Analyst 先 `get_stock_data`。
3. `601061.SH` 不会被 `normalize_symbol` 改成 Yahoo 的 `.SS`。

豆包：`.env` 已有 `TRADINGAGENTS_LLM_PROVIDER=doubao` 仍可能看起来像 OpenAI，因为 Web 目录里没有快照 ID `doubao-seed-2-1-*-260628`，下拉会退回目录第一项；旧 `web-api` 容器也可能没 recreate。截图里「配置 OpenAI/Anthropic」是 Docker Desktop 旁白，不是本仓库 UI。

## 确认方案

1. `web-api` / `tradingagents` compose 强制 `AKSHARE_BASE_URL=http://aktools:8080`。容器内若仍看到 loopback，`resolve_akshare_base_url` 改写为 `aktools`。
2. 默认链 `"akshare,yfinance"`：A 股东财日线/指标；非 A 股 `NoMarketDataError` 后 yfinance。基本面后来也改成同一条链，见 [20260920-ashare-fundamentals.md](20260920-ashare-fundamentals.md)。
3. `normalize_symbol`：上海 `.SH` / 裸六位 → Yahoo `.SS`（只用于 Yahoo 查询）。CLI/Web 跑图保留用户输入的 `.SH`（`run_ticker_symbol`）。
4. Web 下拉把 `.env` 里的模型 ID 插进 options，避免丢掉方舟快照 ID。
