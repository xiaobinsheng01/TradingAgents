# TradingAgents — 开发必读

文档优先级：**代码 > 本文 > [ARCHITECTURE.md](ARCHITECTURE.md) > 专题文档 / [Tech Library](tech-library/README.md)**。

事实以仓库源码为准。若本文与代码冲突，改代码侧的实现或回写本文，不要沿用过期叙述。

最后更新日期：2026-10-21

## 项目定位与职责边界

TradingAgents 是一个面向**研究与按需实时预测**的多代理 LLM 金融分析框架，用 LangGraph 编排一组角色（分析师、多空研究员、交易员、风险辩论、组合经理），对单个标的 + 交易日产出评级与报告。

**本仓库负责：**

- 交互式 CLI（`cli/`）、本机 Web 操作台（`web/`，`127.0.0.1:8000`）和可编程入口（`TradingAgentsGraph.propagate`）
- 按需实时预测：用截至调用时刻的最新**公开**行情/资讯跑一次图，给出次日（T+1）与 5–20 日研究评级（`tradingagents predict`）
- LangGraph 工作流、代理工厂、结构化输出与信号解析
- 数据供应商路由（yfinance / Alpha Vantage / FRED / Polymarket 等）
- 多 LLM 供应商客户端与能力表
- 决策日志（memory log）与可选 checkpoint 续跑
- 将一次运行写成 markdown 报告树

**本仓库不负责：**

- 实盘下单、券商接入、资金托管、持仓管理
- 对外 SaaS / 多用户 HTTP API、消息队列、定时任务调度器、24 小时行情推送进程
  （本机 loopback Web 操作台不是对外 API，也不是行情数据服务）
- 多用户 SaaS、鉴权、计费
- 把回测收益宣传为可复现策略
- 逐笔/盘口深度作为可成交量（没有封单额，Live snapshot 不是成交回报）

框架明确**不是**投资建议。运行结果受模型采样、数据时效和配置影响，两次同标的运行可以不同。

当前团队闭环是**仓库规范 + 跨工具 Skill / Rules + 代码评审**驱动的软闭环。GitHub Actions 已有测试/lint/安装冒烟，但 **PR Template、CODEOWNERS、Branch Protection 等硬门禁尚未配置**，可作为后续阶段。

## 技术栈、依赖管理与启动入口

| 项 | 事实 |
| --- | --- |
| 语言 | Python `>=3.10`（CI 矩阵 3.10–3.13） |
| 编排 | LangGraph `StateGraph` + `ToolNode` |
| LLM | LangChain 各供应商适配；统一经 `create_llm_client`。豆包（火山方舟）是一等 OpenAI 兼容供应商 `doubao`，密钥 `ARK_API_KEY`，CLI 目录 Deep=`doubao-seed-2.1-pro` / Quick=`doubao-seed-2.1-turbo` |
| 数据 | yfinance、Alpha Vantage、AKShare（本地 AKTools HTTP Docker 或可选 extra `[akshare]`）、FRED、Polymarket、StockTwits、Reddit |
| CLI | Typer + Rich；入口 `tradingagents = cli.main:app` |
| 依赖管理 | `pyproject.toml` + pip / setuptools；**没有** poetry/uv lock |
| 可选 extra | `[dev]`（ruff、pytest、web 测试依赖）、`[bedrock]`（`langchain-aws`）、`[akshare]`（A 股新闻）、`[web]`（FastAPI 本机操作台） |
| 配置 | `DEFAULT_CONFIG` + `TRADINGAGENTS_*` 环境覆盖 + `.env`（`python-dotenv`，`override=False`） |

**安装：**

```bash
pip install .
# 开发
pip install -e ".[dev]"
# Bedrock
pip install ".[bedrock]"
# A 股：优先本地 AKTools HTTP，不必装 Python extra
#   docker compose --profile akshare up -d --build aktools
#   探活用 http://127.0.0.1:8080/docs 或 /api/public/...，不要打开首页 /
#   在 .env 设 AKSHARE_BASE_URL=http://127.0.0.1:8080
# 没有 Docker HTTP 时才：
# pip install ".[akshare]"
# 本机 Web 操作台
# pip install -e ".[web]"
# tradingagents web
```

**启动：**

```bash
tradingagents analyze          # 已安装控制台脚本
tradingagents predict 600519.SS            # 按需实时预测（默认今天 + 中文；不下单）
tradingagents score 600519.SS              # T+1 方向命中率（5 日结算为辅；研究记分卡，不下单）
tradingagents web                          # 本机操作台 http://127.0.0.1:8000（需 pip install -e ".[web]"）
tradingagents ingest-news 600519.SS --global   # 一次性把 A 股资讯写入本地仓库（不是后台 worker）
python -m cli.main analyze     # 源码直接跑
python main.py                 # 可编程示例（默认 NVDA + 日期）
```

Docker：

```bash
cp .env.example .env
docker compose run --rm tradingagents
docker compose --profile ollama run --rm tradingagents-ollama
docker compose --profile web up          # 本机操作台：web-ui :8000 + web-api :8001（同一 compose / Dockerfile）
# 首次 build 的 builder 阶段 pip 装 LangChain/pandas 等，国内家宽常见 10–20 分钟；Docker Desktop 界面长时间无新行属正常，用 `docker compose … build --progress=plain` 看 pip 进度，勿过早取消。
# 主 Dockerfile / aktools 的 pip 走阿里云 PyPI，并设 PIP_DEFAULT_TIMEOUT=600。Docker Hub 拉不到 python/nginx 时，先从镜像站拉取并 tag 成官方名，再 build，不要加 --pull。
# 只 recreate web-api 后：docker compose --profile web restart web-ui（nginx 用 Docker DNS 再解析）
```

密钥只从环境变量或 `.env` / `.env.enterprise` 读取，**不要**写入代码或文档正文。

## 目录结构与架构分层

```
cli/                         # Typer CLI、交互选择、报告展示、run_engine
web/                         # 本机操作台：FastAPI、静态页、nginx 模板
tradingagents/
  default_config.py          # 配置单源 + TRADINGAGENTS_* 覆盖表
  reporting.py               # CLI / 可编程共用的报告树写出
  agents/                    # 代理工厂、状态、schema、工具
  graph/                     # LangGraph 编排、条件边、checkpoint、信号
  dataflows/                 # 供应商实现、路由、日期窗、符号规范化
  llm_clients/               # 供应商工厂、能力表、模型目录
tests/                       # pytest
scripts/                     # 少量冒烟脚本
docker/                      # AKTools HTTP sidecar 镜像（akshare>=1.16）
docs/                        # 本开发文档体系
```

分层（按本仓库真实切分，不是 Web 三层）：

1. **入口层** — `cli/`、`web/`（本机 UI）、`main.py`、`TradingAgentsGraph`
2. **编排层** — `tradingagents/graph/`
3. **代理层** — `tradingagents/agents/`（工厂函数返回 graph node）
4. **工具 / 数据层** — `agents/utils/*_tools.py` → `dataflows.interface.route_to_vendor`
5. **LLM 层** — `llm_clients.create_llm_client`
6. **持久化** — memory log（markdown）、资讯 JSON 缓存与 JSONL 仓库、checkpoint（SQLite）、results JSON、报告树（`results_dir/reports/`；Web `GET /api/runs/latest`）（`results_dir/reports/`，Web 用 `GET /api/runs/latest` 读最近一次）

没有 ORM、没有 MQ consumer。本机 Web 操作台（`tradingagents web`）只编排已有 `run_graph_with_events`，不是行情数据 API，也不是多用户服务。

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 实际调用链

一次分析（CLI、本机 web 或 `propagate`）的主链：

```
入口（CLI / web POST /api/runs / TradingAgentsGraph.propagate）
  → run_graph_with_events（CLI Live 与 Web SSE 共用）
  → DEFAULT_CONFIG / 环境覆盖 / set_config
  → create_llm_client ×2（deep_think_llm, quick_think_llm）
  → GraphSetup.setup_graph(selected_analysts)
  → instrument_identity_for_run（A 股 AKTools + 板型/涨跌停；其它 Yahoo info）+ TradingMemoryLog.get_past_context
  → graph.stream / graph.invoke
      Analyst N ⇄ tools_* ⇄ Msg Clear N   （可多选、顺序执行）
      → Bull ⇄ Bear → Research Manager
      → Trader
      → Aggressive ⇄ Conservative ⇄ Neutral → Portfolio Manager
  → SignalProcessor.process_signal
  → memory_log.store_decision + 可选 write_report_tree（`results_dir/reports/<ticker>_<stamp>/`，Docker 卷在 `~/.tradingagents`）
```

数据工具链：

```
@tool get_*（agents/utils/*_tools.py）
  → route_to_vendor(method, ...)
  → 价格/指标/基本面：默认 `akshare,yfinance` first-success（A 股东财日线与三表；美股跳过 akshare）。A 股 ticker 不再打 Yahoo（避免 404/429）
  → get_news：配置链上成功供应商全部拼接（akshare 中文个股 + yfinance 海外个股）。`get_news` 东财条目须标题提到该代码或简称（正文仅出现简称不够）
  → get_global_news：默认 `tool_vendors.get_global_news = akshare,google`。国内联播/快讯仍 AKTools（财联社、东财、新浪、同花顺、富途；同花顺/富途进个股新闻时须提到代码或简称）。国家机关媒体走 `state_media_news.py`（新闻联播仍有 AKShare `news_cctv`，另直接读 CNTV 栏目最近约 40 期；另有人民日报、新华社财经、中国经济网/经济日报、中新网财经、央视新闻、中国政府网、中国人民银行、财政部、国家发展改革委、国家统计局；单页失败留空；进个股新闻须提到代码或简称）。海外走 Serper Google Search（`SERPER_API_KEY`，无密钥则 News RSS）+ `site:` X/YouTube/Meta，不再默认 Yahoo Search。只引用会影响 A 股/该标的的条目
  → get_ashare_short_horizon：可选类别 `ashare_tape`（akshare），A 股次日/5–20 日 tape
  → get_ashare_swing_tape：同一 `ashare_tape` 类别；近半个月/近半年价量 + 披露增减持/龙虎/大宗 + 窗口新闻 + as-of 前 250 日缠论结构；Web「价量 Tape」页走现有 `POST /api/runs`（含 News Analyst），不是行情 HTTP
  → get_insider_transactions：默认 `news_data` first-success。A 股走 `akshare_flow.py`（增减持 / 龙虎买卖席位 / 大宗，日期 `<= as-of`）；Yahoo 对 A 股跳过
  → VENDOR_METHODS[method][vendor]
  → yfinance / alpha_vantage / akshare / google / fred / polymarket
```

配置覆盖链：

```
default_config.DEFAULT_CONFIG
  ← TRADINGAGENTS_*（_ENV_OVERRIDES，按默认值类型强制转换，非法即失败）
  ← CLI 交互或 --checkpoint / --no-checkpoint
  ← TradingAgentsGraph(config=...) 传入后 set_config（dict 一层 merge）
```

**没有**对外 SaaS 路由、**没有** Service 单例容器、**没有** MQ 消费循环、**没有** 独立定时任务框架。checkpoint 是 LangGraph 节点级续跑，不是后台 worker。`ingest-news` 是一次性 CLI 拉取，进程内不常驻。本机 `tradingagents web` 默认只绑 `127.0.0.1`。Docker 用同一 `Dockerfile` 的 `frontend`/`backend` 阶段和同一 `docker-compose.yml` 的 `web-ui`/`web-api`（profile `web`），宿主机仍发布 `127.0.0.1`。

## 模块索引与新功能落点

| 要做的事 | 落点 | 不要另起炉灶 |
| --- | --- | --- |
| 新分析师角色 | `graph/analyst_execution.py` 的 `ANALYST_NODE_SPECS` + `create_*` + ToolNode + `should_continue_*` | 不要绕开 execution plan 手写边 |
| 新数据工具 | `agents/utils/*_tools.py` 的 `@tool` + `interface.VENDOR_METHODS` / `TOOLS_CATEGORIES` | 不要在代理里直接调某个 vendor |
| 新供应商 | `dataflows/<vendor>.py`，抛 `VendorError` 子类 | 不要加新的 `except` 分支到 router |
| A 股六位代码 | `dataflows/symbol_utils.a_share_code` | 不要在东财/巨潮路径各写一套后缀剥离 |
| 海外全球新闻 | `dataflows/google_news.py`（Serper `SERPER_API_KEY`，无密钥则 News RSS + `site:`） | 不要爬 X/Meta；不要把 Yahoo Search 当默认海外全球源；历史 as-of 禁止打实时 Google 索引 |
| 国家机关媒体 | `dataflows/state_media_news.py`（挂在 akshare `get_global_news` / `get_news`） | 不新开供应商；新闻联播仍有 AKShare `news_cctv`，并直接读 CNTV 栏目；央行/财政部/发改委/统计局走公开列表；单页失败留空；个股只保留点名代码或简称的条目 |
| A 股板型/涨跌幅限 | `a_share_board_type` / `a_share_limit_pct` / `a_share_exchange_name` | 不要在行情模块里再写一套 ST/创业/科创规则 |
| A 股身份卡 | `akshare_market.resolve_a_share_identity` + `instrument_identity_for_run` | 不要对 A 股打 Yahoo `info`；没有公司名时不要编造 |
| 校验快照 OHLCV | `stockstats_utils.load_ohlcv`（A 股走 `get_akshare_stock_data`） | 不要让 `get_verified_market_snapshot` 单独打 Yahoo |
| A 股短线 tape | `dataflows/akshare_market.py` + `dataflows/ashare_playbook.py` + `get_ashare_short_horizon` | 不要用三表估值去打明天；不要另起量化库；行业/商品只用静态关键词表（国内+映射外盘），不要建布局画像；T+1 打法立场写在 tape 里（BUY 需已知昨日涨停溢价≥0.3%、涨停家数≥15、沪深300 1日&gt;−1%；三板溢价≥1%；连板龙虎净卖否决），不要另开选股代理或下单；单票路径不扫涨速榜 |
| 沪深主板筛选 | `dataflows/ashare_screen.py` + 操作台 `GET /api/screen` | 只留 `a_share_board_type == main`；创业板/科创板/北交所不进表，领涨不是主板时不顺延第二名；东财现货失败改新浪，新浪再空改腾讯 `stock_zh_a_spot_tx`；行业板失败改同花顺；只允许当天；不自动跑全图；不是行情 API，不是委托 |
| 明日上涨（排除创业板） | `dataflows/ashare_screen.py` 的 `screen_tomorrow_rise` + 操作台 `GET /api/tomorrow-rise` | 观察区用 `universe=no_chinext`（科创板/北交所在表内）；T+1 打法只留 `t1_bias==BUY`；与筛选共用现货/行业回退；只允许当天；不跑 LangGraph；不是行情 API，不是委托 |
| A 股价量/机构 tape | `dataflows/akshare_market.py` + `get_ashare_swing_tape`（`half_month` / `three_months` / `half_year`）+ `dataflows/chanlun.py` | 不要新开 FastAPI 行情接口；空 机构出手、窗口新闻或缠论写 `NO_DATA_AVAILABLE`，不要编造出手/买入、标题或中枢/买卖点；`date<=as-of` |
| A 股多票趋势快照 | `dataflows/ashare_trend_predict.py` + `ashare_trend_bias.py` + 操作台 `POST /api/trend-predict` | 与 swing tape 共用 `compute_trend_bias`（指数/行业 regime、下行段禁下沿反弹、持续走弱改 SELL）；创业板拒绝；不跑 LangGraph、不是行情 API、不是委托 |
| A 股三表/基本面 | `dataflows/akshare_fundamentals.py` | 不要对 A 股打 Yahoo 三表；报告日 `<= as-of`；缺行不要编 PE/ROE |
| A 股增减持/买卖 | `dataflows/akshare_flow.py` + `get_insider_transactions` | 不要对 A 股打 Yahoo Form 4；交易所增减持用六位代码；`stock_ggcg_em` 只用增减持类别；龙虎/新浪按各自签名传参；全市场表按代码过滤；不要编造出手/买入；不是委托 |
| 资讯条目/去重 | `dataflows/news_items.py` | 不要各渠道各写 markdown 拼装 |
| 资讯按日缓存 | `dataflows/news_store.py`（`data_cache_dir/news`） | 不要另起数据库或 MQ；ticker 先 `safe_ticker_component` |
| 资讯跨次仓库 | `dataflows/news_warehouse.py`（`data_cache_dir/news/_warehouse`） | 不要上 Redis/DB；append-only JSONL + `item_identity` |
| 一次性入仓 | `dataflows/news_ingest.py` + CLI `ingest-news` | 不要加 cron/daemon；调度留给调用方 |
| 按需实时预测 | CLI `predict` + live as-of 的 `get_ashare_short_horizon` 快照 | 不要加券商下单、不要加 24h worker |
| 预测命中率 | `hit_rate.summarize_memory_log` + `next_session_raw_return` + CLI `score` | 不要用 5 日持有当 T+1 主指标；不要另起回测库或把记分卡当成交回报 |
| 本机 Web 操作台 | `web/` + `cli/run_engine.py` + `tradingagents web` + compose `web-ui`/`web-api` | 不要当行情 API、不要把宿主机端口绑 `0.0.0.0`、不要把 key 送给浏览器、不要另起第二份 compose；最近一次分析用 `GET /api/runs/latest` 读报告树，不要上 ORM；nginx 对 `web-api` 必须用变量 `proxy_pass` + `resolver 127.0.0.11`，不要写死容器 IP；「价量 Tape」页仍 `POST /api/runs`，窗口字段 `swing_tape_window`（含近3个月）；「趋势预测」页 `POST /api/trend-predict` 支持多票、不跑 LLM、创业板不参与；「明日上涨」页 `GET /api/tomorrow-rise` 扫 T+1 偏多并排除创业板；「大盘筛选」只 `GET /api/screen` 读当天沪深主板快照，点一行再拉 `GET /api/screen/bars` 画日K（创业板不进日K；Lightweight Charts，A 股红涨绿跌，不是委托），「带入全图分析」才切到 `POST /api/runs`，不自动跑全图预测；`MessageBuffer` live 标题必须覆盖 `REPORT_SECTIONS`（含 `swing_tape`），不要另写一份会 KeyError 的标题表 |
| 本地 AKShare Docker | `AKSHARE_BASE_URL` → AKTools `/api/public/<接口>`（`_load_akshare`） | 不要把 Jupyter `:8888` 当成数据 API；不要在容器里用 `127.0.0.1:8080`（应是 `http://aktools:8080`）；不要用冻结的 `aktools:1.8.95`；不要用首页 `/` 探活；不要在本仓库再起 Flask；sidecar 没有的接口（404「未找到该接口」）跳过该通道，不要当数据失败反复重试 |
| 新 LLM 供应商 | `llm_clients/factory.py` + `api_key_env.py` + 能力表 / 模型目录 + CLI 选择 | 不要在 graph 里 `ChatOpenAI(...)` |
| 新配置项 | `DEFAULT_CONFIG`；若需环境覆盖，加 `_ENV_OVERRIDES` 一行 | 不要在 CLI/`main.py` 再写一套解析 |
| 结构化决策字段 | `agents/schemas.py` + `render_*` + `structured.py` | 不要各代理各写一套 JSON 解析 |
| 5 档评级用词 | `agents/utils/rating.py` | 不要在 signal / memory / schema 各维护一份 |
| 前瞻安全日期窗 | `dataflows/date_window.py` | 不要在 news/reddit/stocktwits 各写 cutoff |
| 标的规范化 | `normalize_symbol`（Yahoo 查询）/ `run_ticker_symbol`（CLI/Web 跑图） | 不要把页面上的 `.SH` 改成 `.SS` 再喂给模型；不要把券商符号直接丢给 yfinance |
| 路径安全 ticker | `dataflows/utils.safe_ticker_component` | 不要把用户/LLM ticker 直接拼进 Path |
| 报告落盘 | `reporting.write_report_tree` | 不要 CLI 与 graph 各写一套目录 |
| 环境密钥名 | `llm_clients/api_key_env.py` | 不要在 CLI 硬编码 key 名 |

分析师 wire key 仍是 `market` / `social` / `news` / `fundamentals`。`social` 是兼容旧配置的键，用户可见名是 Sentiment Analyst。

## 复用清单

**必须先复用：**

- `route_to_vendor` — 唯一数据出口
- `VendorError` / `NoMarketDataError` / `VendorRateLimitError` / `VendorNotConfiguredError`
- `normalize_symbol`、`run_ticker_symbol`、`a_share_code`、`a_share_board_type`、`a_share_limit_pct`、`a_share_exchange_name`、`safe_ticker_component`
- `resolve_a_share_identity` / `instrument_identity_for_run` / `get_instrument_context_from_state`
- `match_exposure`（A 股行业静态表：先具体后宽；国内合约 + 映射外盘；无合约的板块只挂行业指数）
- `NewsItem` / `dedupe_items` / `item_identity` / `news_store.fetch_cached` / `fetch_cached_records`
- `news_warehouse.upsert_items` / `query_items`（跨次 JSONL 仓库）
- `in_window` / `to_utc`（`date_window`）
- `create_llm_client`、`get_capabilities`、`PROVIDER_API_KEY_ENV`
- `create_*` 代理工厂 + `ANALYST_NODE_SPECS`
- `bind_structured` / `invoke_structured_or_freetext` / `NO_EXTERNAL_TOOLS`
- `PortfolioRating` / `TraderAction` / `extract_rating` / `is_review`
- `get_language_instruction`、`opponent_argument_or_opening`
- `TradingMemoryLog`、`begin_checkpoint` / `checkpoint_scope`
- `summarize_memory_log` / `next_session_raw_return`（T+1 主指标，5 日结算为辅）
- `write_report_tree` / `load_latest_run`
- `run_graph_with_events`（CLI 与本机 Web 共用跑图循环）
- `_ENV_OVERRIDES` + `set_config` / `get_config`

**公共工具文件：**

- `agents/utils/core_stock_tools.py`
- `agents/utils/ashare_market_tools.py`
- `agents/utils/technical_indicators_tools.py`
- `agents/utils/fundamental_data_tools.py`
- `agents/utils/news_data_tools.py`
- `agents/utils/macro_data_tools.py`
- `agents/utils/prediction_markets_tools.py`
- `agents/utils/market_data_validation_tools.py`

**已弃用但仍导出：** `create_social_media_analyst`（`create_sentiment_analyst` 的别名）。新代码不要用。

## 禁止事项与遗留架构

**禁止：**

- 把未列入配置的供应商静默加入 fallback / 聚合链（`#988` / `#289`）
- 把研究评级（BUY/HOLD/SELL）当成券商委托或自动下单
- 历史/回测运行读到 as-of 之后的新闻、社媒、宏观修订、memory 教训，或**当日实时快照**
- 在 `NO_DATA_AVAILABLE` / `DATA_UNAVAILABLE` 时编造价格或指标
- 把不可解析的评级静默变成可交易的 `Hold`（应走 `REVIEW` + `extract_rating`）
- 把用户或 LLM 给出的 ticker 不经验证写入 cache / checkpoint / results 路径
- 在代理或 graph 中直接实例化供应商 SDK，绕过 factory / vendor router
- 新引入对外 SaaS / 行情 HTTP API、消息队列、独立 worker，除非 Tech Library 有确认方案
  （本机 loopback 操作台已归档：`docs/tech-library/20260915-local-web-console.md`）
- 提交 `.env`、`.env.enterprise`、密钥、虚拟环境、生成缓存、`reports/`
- 复制其它项目的 Web/MQ/ORM 分层到本仓库

**遗留 / 兼容：**

- `MessageBuffer` live 标题必须覆盖 `REPORT_SECTIONS`（含预取 `swing_tape`），漏登记会在 Web 预取后 `KeyError` 中止跑图。AKTools duck-type 对 sidecar 没有的 `/api/public/<name>` 返回 404「未找到该接口」：该通道跳过（财联社快讯仍走 `stock_info_global_cls`），不要当数据失败反复打。增减持先走交易所 `stock_share_hold_change_sse` / `szse` / `bse`（六位代码，不要 `601061.SH`）。`stock_ggcg_em` 的 symbol 只能是 `股东增持` / `股东减持` / `全部`，不要传股票代码。`stock_changes_em` 是盘口异动，不是增减持。龙虎 `stock_lhb_detail_em` 只传 `start_date`/`end_date`；席位 `stock_lhb_stock_detail_em` 要 `symbol`+`date`+`flag`；新浪 `stock_lhb_detail_daily_sina` 只传 `date`。巨潮公告 `market` 必须是 `沪深京`。东财身份 500 再试 `stock_profile_cninfo`、雪球 `stock_individual_basic_info_xq`（`SH601061`）。东财日线 500 记 info 后走腾讯/新浪，两路都空才 warning。禁止编造价格或新闻。
- 分析师 key `social` 与节点名 `Sentiment Analyst` 并存
- `create_social_media_analyst` 仅兼容旧 import
- `parse_rating` 仍会静默默认 `Hold`，仅给 memory log 等兼容调用方；新逻辑用 `extract_rating`
- `set_config` 对缺失键做一层 merge，测试必须重置全局 `_config`（`tests/conftest.py` 已做）
- `analyst_concurrency_limit` 已删除；分析师仍是**顺序**执行
- `pyproject.toml` 声明了 `redis`，源码中无 `import redis`；它不是消息总线，不要据此新增 consumer
- Sentiment Analyst 绕过 ToolNode / `route_to_vendor` 预取数据；A 股走 `fetch_a_share_sentiment`（雪球 / 东财股吧帖子 / 东财人气榜 `stock_hot_rank_detail_em`+`stock_hot_keyword_em`，symbol 为 `SH601061` 这种大写前缀 / 千股千评），其它市场仍是 StockTwits 与 Reddit（带 `date_window`）；`tools_social` 是遗留空转节点。`stock_comment_em()` 无参数，调用后只保留当前六位代码；`stock_comment_detail_*` 带 `symbol=六位代码`。详情接口 `TypeError` 后禁止无参再调。不再请求不存在的 `stock_guba_em` / `stock_comment_detail_zhpj_lte_em`（正确详情名是 `stock_comment_detail_zhpj_lspf_em`）。股吧帖子不走 AKShare，直接读东财公开列表。雪球空 body 不当 JSON 解析。缓存频道 `comment_em_code` 避免沿用旧的未过滤快照；股吧帖子缓存频道 `guba_posts`
- 雪球 HTTP 读 `XUEQIU_COOKIE` 或 `TRADINGAGENTS_XUEQIU_COOKIE`；未设则先访问首页拿会话 cookie，并把 `xq_a_token` 带到查询参数；仍无 token 再暖股票页；400/401/403 降级为 `<unavailable>`，禁止编造帖子；有其它渠道但雪球空时报告会注明 cookie 未设。雪球空时零售帖子改读东财股吧：`gbapi.eastmoney.com` 的 `listbystock`，空则再读 `guba.eastmoney.com/list,{code}.html` 里的 `article_list`。多空计数只数这些帖子里的看多/看空短语，不是投票，也不用人气榜或千股千评代替
- `get_news` / `get_global_news` 对配置链做聚合拼接。`get_news` 默认仍 `news_data = akshare,yfinance`。`get_global_news` 默认 `tool_vendors = akshare,google`：akshare 是国内联播/快讯（财联社、东财、新浪、同花顺、富途；同花顺/富途进个股新闻须提到代码或简称，接口缺失则该通道空）加上国家机关媒体（`state_media_news.py`：人民日报、新华社财经、中国经济网/经济日报、中新网财经、央视新闻、中国政府网、中国人民银行、财政部、国家发展改革委、国家统计局；新闻联播仍有 `news_cctv`，并直接读 CNTV 栏目最近约 40 期；单页失败留空；进个股新闻须提到代码或简称）；google 是海外 Serper（`SERPER_API_KEY` / `TRADINGAGENTS_SERPER_API_KEY`）走 Google Search，并按 `site:x.com` / `youtube.com` / `facebook.com` / `instagram.com` 补公开帖子摘要；无密钥时退 Google News RSS。本机到 `news.google.com` / `google.serper.dev` 网络不可达或读超时后，这一轮不再重复打剩余查询。不调用 X/Meta 官方 API，也不刮站。Google 索引没有点-in-time vintage，历史 as-of 只读缓存、不打实时搜索。个股新闻过滤不变：东财相关推荐须标题提到代码或简称。巨潮公告按代码接口保留。A 股个股新闻不再请求 Yahoo。FRED / Polymarket 仍可选；News 提示词要求仅当明显影响该代码或 A 股时段才引用。Bull / Bear / 风险把 `news_report` 标成「个股新闻报告」，不再写成 world affairs。价格 / 指标 / 基本面 / `get_insider_transactions` 仍是 first-success。`get_insider_transactions` 默认走 `news_data`：A 股 `akshare_flow.py`（董监高/股东增减持、龙虎买卖席位、大宗，`date<=as-of`，按代码过滤）；空则 `NO_DATA_AVAILABLE`，禁止编造出手/买入。Yahoo 对 A 股立即跳过。News 与 Fundamentals 均 `bind_tools` 该工具，与 ToolNode 对齐。默认 `fundamental_data` 为 `akshare,yfinance`：A 股三表走东财/新浪（`akshare_fundamentals.py`，报告日 `<= as-of`）；`get_fundamentals` 简介先打 `stock_individual_info_em`（带 symbol），500 再试 `stock_profile_cninfo`，再试雪球 `stock_individual_basic_info_xq`（`SH`/`SZ`/`BJ` 大写前缀）；失败写空，不用 `stock_info_a_code_name` 全 A 代码表。Yahoo 对 A 股立即跳过；美股仍 yfinance
- `get_ashare_short_horizon` 是 Market Analyst 的 A 股短线 tape（价量规则、涨跌停、市场广度、滞后北向、龙虎榜买卖席位与金额、解禁、仓库事件旗标、静态行业/商品暴露）。目标是下一可交易日与 5–20 日，不是 PE 估值。收盘 tape 附带确定性 `Playbook stance (T+1)`（`ashare_playbook.py`：两市成交额、板型、近端涨停）。`t1_bias` 为 BUY/HOLD/SELL，已与 `ashare_market_mood` 的全市场 `market_mood_t1` 合并（warehouse 无明确利多/利空时情绪权重更高）。swing tape 另写 `trend_bias`（含与 `mood_swing` 合并）；`trend_bias: SELL` 时最终评级不得比 Sell 更偏多。Research Manager、Trader、Portfolio Manager 经 `enforce_t1_bias` 对齐；无 bias 行时不改。CLI `score` 另打印 Buy/Sell 分组的 T+1 命中率。不是委托，单票 tape 不扫涨速榜，也不做十分钟卖出。`get_ashare_swing_tape` 是同一 `ashare_tape` 上的近半个月（15 日历日）或近半年（180 日历日）价量摘要，并挂窗口内增减持/龙虎/大宗、个股/政策新闻，以及 as-of 前约 250 个日历日的缠论分型/笔/线段/中枢（`dataflows/chanlun.py`，价量窗口不够成段时结构仍用长回看）；Web「价量 Tape」页选 `swing_tape_window` 后仍 `POST /api/runs`（含 News Analyst），跑图前预取写入 `1_analysts/swing_tape.md`，不是行情 HTTP。空机构出手、新闻或缠论 `NO_DATA_AVAILABLE`，禁止编造出手/买入、标题或中枢/买卖点。行业指数与最多两个国内商品合约、最多两个外盘来自 `match_exposure` 关键词表（先具体后宽：能源金属 → 碳酸锂而不是沪铜；有色/工业金属 → 中证有色 `sh000819` + 沪铜 `CU0` + LME `CAD` / COMEX `HG`；钢铁 → 铁矿 `I0` + SGX `FEF`；饲料 → 豆粕 + CBOT `SM`；白酒/银行等只有行业指数）。东财行业板失败再走与沪深300相同的指数日线回退（`sh000819` 空再试 `000819`）；国内新浪期货日线空再试东财 `futures_hist_em`（`CU0`→`CU`）；外盘 `futures_foreign_hist` 空再试东财中文名（`LME铜` / `LME镍` / `SGX铁矿石`），`date<=as-of`。未命中或拉取失败保持 `<unavailable>`，禁止按公司名编铜价。**当日 live as-of** 附加公开最新价（东财盘口 → 雪球 → 腾讯分钟末根，TTL 同电报）；历史 as-of 禁止读该快照。live 且仓库空时事件旗标会一次性 `ingest_news`（不是 worker）；历史 as-of 禁止。指数/分钟/龙虎在东财 RST 后走腾讯或新浪；涨停池仅 live 可用新浪全市场快照近似（`market_breadth_source`），历史禁止。akshare 走本地 AKTools HTTP（`AKSHARE_BASE_URL`，Docker 内必须是 `http://aktools:8080` 而不是宿主机 `127.0.0.1`，compose 构建 `docker/aktools.Dockerfile` / `akshare>=1.16`）或 pip extra；两者都缺时 `ashare_tape` 降级为 `DATA_UNAVAILABLE`，不中止美股运行。北向只用 as-of 之前已公布的会话。封板按买不到处理。没有完整分钟逐笔、没有封单额、没有股东户数周频。`tradingagents predict` 是一次 `propagate`，不是 24h 推送。`tradingagents score` 以 T+1（`next_session_raw_return`，只要股票下一根收盘）为主、memory 已结算 5 日 raw 为辅，不是成交回报。 Jupyter 镜像 `:8888` 不是 HTTP API。官方 `aktools:1.8.95` 会把 `symbol=000001` 判为非法参数。AKTools 探活用 `/docs` 或 `/api/public/...`，不要打开首页 `/`（会刮 PyPI）。默认 `core_stock_apis` / `technical_indicators` / `fundamental_data` 为 `akshare,yfinance`：A 股日线先东财，Docker 内东财 RST 时改腾讯/新浪；三表走东财报告期再新浪再年度表；美股跳过 akshare。A 股 ticker 的 Yahoo 价格/资讯/三表直接跳过。`_fetch_returns` 对 A 股走同一条 AKTools 日线与指数，不打 Yahoo。`resolve_instrument_identity` 对 A 股走 `resolve_a_share_identity`（AKTools 简称 + 句法板型/交易所），不打 Yahoo `info`；涨跌停幅度按 as-of 附到 `instrument_context`。`load_ohlcv` / `get_verified_market_snapshot` 对 A 股与 `get_stock_data` 同一条 AKTools 日线。豆包要 `TRADINGAGENTS_LLM_PROVIDER=doubao`，且 `tradingagents` / `web-api` 镜像必须 `--build --force-recreate` 后才会带上仓库默认链。
- 操作台「大盘筛选」走 `ashare_screen.screen_main_board` 与 `GET /api/screen`：当天涨幅榜、涨速榜、行业领涨，只留沪深主板（`main`）。创业板、科创板、北交所和 ST 不进表；领涨本身不是主板时不把同板块第二名抬成前排。东财 `stock_zh_a_spot_em` 空或 500 时现货改新浪 `stock_zh_a_spot`（`sh`/`sz`/`bj` 前缀折成六位；新浪没有涨速、换手、量比，这三列留空，涨幅榜仍列出沪深主板，振幅用最高、最低和昨收）。新浪也空时改腾讯 `stock_zh_a_spot_tx`：`code` 同样折六位，`turnover` 万元和 `ltsz` 亿元换算成元；涨速、换手、量比保留，没有今开/最高/最低/昨收。东财行业板空时领涨改同花顺 `stock_board_industry_summary_ths`（列名 `板块` / `领涨股`）。三路现货都空时 `quote_source` 为空，页面写「现货榜没有返回」，不要写成观察区没有前排。龙虎只把 `start_date`/`end_date` 传给东财 `stock_lhb_jgmmtj_em` / `stock_lhb_detail_em`，不要再传它们不接受的 `date`。复用 `build_playbook_stance`。龙虎机构净额、增减持、融资差额、融券余量差额缺了就写「不可用」。全市场增减持 `stock_ggcg_em(symbol=全部)` 最多等 8 秒，超时写不可用，避免整页被 30 秒拖住。上交所融资明细 500 仍写不可用，深交所明细照旧另拉。席位净卖不是做空，减持不是清盘。榜单首板没有近端涨停史，保持 HOLD；点一行拉 `GET /api/screen/bars` 画日K，「带入全图分析」才把 `.SH`/`.SZ` 填进全图，由用户再 `POST /api/runs`。历史日期拒绝。不是行情 API，不是委托。
- `SignalProcessor` 仍接收 LLM 参数但实现已忽略（启发式 `extract_rating`）
- `main.py` 底部的 `reflect_and_remember` 示例已注释，现行记忆路径是 memory log + 下次同标的结算
- 辩论/风险 router 必须使用完整 `DEBATE_PATH_MAP` / `RISK_ANALYSIS_PATH_MAP`，防止 path_map 漏边崩溃

## 测试、lint、构建、依赖检查

与 CI（`.github/workflows/ci.yml`）对齐：

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
python -c "import tradingagents, cli.main; print('clean-install import OK')"
```

按改动类型取用：

| 改动 | 最少要跑 |
| --- | --- |
| `tradingagents/` 或 `cli/` 行为 | 相关 `tests/test_*.py` + `ruff check` 触及文件 |
| 供应商路由 / 日期窗 / 符号 | `tests/test_vendor_routing.py`、`test_date_boundaries.py`、`test_symbol_*.py`、`test_akshare_news.py`、`test_akshare_fundamentals.py`、`test_akshare_flow.py` 等 |
| LLM 客户端 | `tests/test_*provider*.py`、`test_capabilities.py`、`test_api_key_env.py` |
| Graph / checkpoint | `tests/test_analyst_execution.py`、`test_checkpoint_*.py`、`test_risk_router_path_map.py` |
| `web/` 操作台 | `tests/test_web_console.py` + `ruff check` 触及文件 |
| 仅文档 / rules / skills | 链接检查 + `git diff --check`；不要为了“跑完全部”而改测试 |

集成测试需要真实外网或密钥时，保持 mock 边界（现有 suite 用 placeholder key + 隔离 config）。不要提交真实密钥。

构建：`pip install .`（setuptools）。没有独立 frontend build。

## 开发闭环、Definition of Done、豁免

跨工具统一走 `project-dev-loop` Skill（Cursor / Codex / Claude Code）。步骤：

0. 扫 [tech-library/README.md](tech-library/README.md)，命中主题读正文
1. 读本文
2. 加载匹配的 [agent-rules/](agent-rules/)
3. 探索类似实现与复用点
4. 复杂任务先确认方案
5. 按现有分层实现
6. 补测并运行上表命令
7. 回写本文、ARCHITECTURE 或专题文档
8. 触发 Tech Library 时归档；Plan 流程图写入仓库或按落地调用链补绘
9. 输出收尾检查

**DoD（缺一不得声称完成）：**

- 行为变更已补测并通过
- 目录、调用链、配置、复用清单等事实已与代码同步
- 应沉淀的确认方案已写入 Tech Library
- 未改动或提交密钥、虚拟环境、生成缓存

**可豁免沉淀：** 纯 typo / 格式、无行为变化的内部重构、无结论排障、未确认中间稿。

**硬门禁说明：** 当前不依赖 PR Template、CODEOWNERS、Branch Protection。已有 CI 作业是参考命令来源，不是本阶段要改的范围。

## 跨工具入口

| 工具 | 入口 |
| --- | --- |
| 任意 Agent | 本文件 + [ARCHITECTURE.md](ARCHITECTURE.md) + [tech-library/](tech-library/README.md) |
| Cursor | `.cursor/skills/project-dev-loop/SKILL.md`，规则适配 `.cursor/rules/*.mdc` |
| Claude Code | `CLAUDE.md` + `.claude/skills/project-dev-loop/SKILL.md`，规则 `.claude/rules/*.md` |
| Codex | `AGENTS.md` + `.agents/skills/project-dev-loop/SKILL.md` |

规则正文只在 `docs/agent-rules/`。工具目录不得复制完整规则。
