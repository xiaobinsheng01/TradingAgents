<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>
<br>
<div align="center">
  <a href="https://github.com/TauricResearch" target="_blank"><img alt="TradingAgents #1 Repository of the Day" src="https://trendshift.io/api/badge/repositories/16192" width="250" height="55"/></a>
</div>
<br>
<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework

## News
- [2026-08] **TradingAgents v0.4.0** released with look-ahead / point-in-time fixes across FRED macro, social sentiment, and the decision-log memory; clearer decision signals; working CLI checkpoint resume; Trader price grounding; and the GPT-5.6 and GLM-5.3 models. See [CHANGELOG.md](CHANGELOG.md) for the full list.
- [2026-07] **TradingAgents v0.3.1** released with correctness and stability fixes: Alpha Vantage look-ahead filtering, graph-router crash-safety, graph-shape-aware checkpoint resume, working crypto sentiment sources, a configurable LLM retry budget, Bedrock API-key auth, and Claude Sonnet 5 / Fable 5 support.
- [2026-06] **TradingAgents v0.3.0** released with a verified data-access contract, an expanded provider registry (NVIDIA, Kimi, Groq, Mistral, Bedrock, and any OpenAI-compatible endpoint), FRED and Polymarket data vendors, a current-generation model catalog, and a CI gate.
- [2026-05] **TradingAgents v0.2.5** released with the grounded Sentiment Analyst, GPT-5.5 etc. model coverage, Qwen/GLM/MiniMax dual-region support, `TRADINGAGENTS_*` env-var configurability with API-key auto-detection, remote Ollama support, non-US alpha benchmarks, and ticker path-traversal hardening.
- [2026-04] **TradingAgents v0.2.4** released with structured-output agents (Research Manager, Trader, Portfolio Manager), LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure provider support, Docker, and a Windows UTF-8 encoding fix.
- [2026-03] **TradingAgents v0.2.3** released with multi-language support, GPT-5.4 family models, unified model catalog, backtesting date fidelity, and proxy support.
- [2026-03] **TradingAgents v0.2.2** released with GPT-5.4/Gemini 3.1/Claude 4.6 model coverage, five-tier rating scale, OpenAI Responses API, Anthropic effort control, and cross-platform stability.
- [2026-02] **TradingAgents v0.2.0** released with multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 🧰 [Developer docs](#developer-docs-and-agent-loop) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents: from fundamental analysts, sentiment experts, and technical analysts, to trader, risk management team, the platform collaboratively evaluates market conditions and informs trading decisions. Moreover, these agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. It produces on-demand predictions (latest public quotes and news at run time) and **does not place broker orders**. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex trading tasks into specialized roles.

### Analyst Team
- Fundamentals Analyst: Evaluates company financials and performance metrics, identifying intrinsic values and potential red flags.
- Sentiment Analyst: Aggregates news headlines, StockTwits, and Reddit chatter into a single sentiment read to gauge short-term market mood.
- News Analyst: Monitors global news and macroeconomic indicators, interpreting the impact of events on market conditions.
- Technical Analyst: Utilizes technical indicators (like MACD and RSI) to detect trading patterns and forecast price movements.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions, determining the timing and magnitude of trades.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. If approved, the order will be sent to the simulated exchange and executed.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.12
conda activate tradingagents
```

Install the package and its dependencies:
```bash
pip install .
```

### Local web console

```bash
pip install -e ".[web]"
tradingagents web   # http://127.0.0.1:8000 — research UI only, never places orders
```

Same console via Docker (one Dockerfile, two services in `docker-compose.yml`):

```bash
cp .env.example .env
docker compose --profile web up    # UI http://127.0.0.1:8000  API http://127.0.0.1:8001
```

`web-ui` and `web-api` can be started together or individually. The page reads LLM keys from `.env` on the API container. It does not upload reports to Tauric announcements. After a run, markdown lives under `~/.tradingagents/logs/reports/` (Docker volume). The UI button **查询最近一次分析** calls `GET /api/runs/latest`. The **价量 Tape** tab analyzes the last half-month or half-year of price/volume, window news, 缠论 structure, plus disclosed 机构出手 (still `POST /api/runs` with the News Analyst, not a market-data API). The **大盘筛选** tab calls `GET /api/screen` for today's Shanghai/Shenzhen main-board gainers, speed list, and sector leaders (ChiNext, STAR, and Beijing are excluded). If East Money spot or industry boards return HTTP 500, the same request falls back to Sina quotes and the Tonghuashun industry summary. Sina has no intraday speed, turnover, or volume ratio, so those columns stay empty; the gainers table still lists main-board names and sits above the daily chart. If Sina spot is also empty, quotes come from Tencent (`stock_zh_a_spot_tx`), which does include speed. Clicking a row loads a Lightweight Charts daily candlestick and volume pane from `GET /api/screen/bars`. **带入全图分析** fills the full-graph form and does not start a run. If dropdowns on `:8000` are empty after recreating `web-api`, refresh the page or `docker compose --profile web restart web-ui` so nginx re-resolves the API.

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
docker compose --profile web up    # local web console (UI + API)
```

First image build downloads a large Python stack (LangChain, pandas, …). On a typical home network, **plan 10–20 minutes** for the first `build`; Docker Desktop may look idle while `pip` runs inside the builder stage. Prefer a terminal with live logs (`docker compose --profile web build --progress=plain`) instead of cancelling early. PyPI uses Aliyun in the Dockerfile; base images `python:3.12-slim` / `nginx:alpine` still come from Docker Hub—if pulls time out, mirror-pull and retag them locally before `build` (see `docs/PROJECT.md` Docker notes). Do not add `--pull` on every build unless you intend to refresh bases.

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export ARK_API_KEY=...             # Doubao — Volcengine Ark (ark.cn-beijing.volces.com)
export DASHSCOPE_API_KEY=...       # Qwen — International (dashscope-intl.aliyuncs.com)
export DASHSCOPE_CN_API_KEY=...    # Qwen — China (dashscope.aliyuncs.com)
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China, open.bigmodel.cn)
export MINIMAX_API_KEY=...         # MiniMax — Global (api.minimax.io)
export MINIMAX_CN_API_KEY=...      # MiniMax — China (api.minimaxi.com)
export OPENROUTER_API_KEY=...      # OpenRouter
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
```

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For AWS Bedrock, install the extra with `pip install ".[bedrock]"`, set `llm_provider: "bedrock"`, configure AWS credentials (environment variables, `~/.aws/credentials`, or an IAM role) and `AWS_DEFAULT_REGION`, and use a Bedrock model ID, e.g. `us.anthropic.claude-opus-4-8-v1:0`.

For China A-share news (East Money, exchange filings, CCTV 新闻联播 / domestic newswire (CLS, East Money, Sina, Tonghuashun, Futu) / state media (People's Daily, Xinhua finance, Economic Daily via ce.cn, chinanews finance, CCTV News, gov.cn, CNTV 新闻联播, PBOC, Ministry of Finance, NDRC, NBS)), fundamentals (`get_fundamentals` / three statements via East Money), and the next-session tape (`get_ashare_short_horizon`: limits, breadth, lagged northbound, static industry/commodity exposure including mapped LME/COMEX), either point `AKSHARE_BASE_URL` at a local AKTools HTTP Docker (`docker compose --profile akshare up -d --build aktools`, `http://127.0.0.1:8080`, not the jupyter image on `:8888` and not frozen `aktools:1.8.95`) or `pip install ".[akshare]"`. No extra API key. Default `news_data` for company news is `akshare,yfinance`. `get_global_news` defaults to `akshare,google`: overseas headlines and public X/YouTube/Meta snippets come from Serper (`SERPER_API_KEY`) or Google News RSS if the key is unset. Probe the sidecar at `/docs` or `/api/public/...`; the homepage `/` scrapes PyPI and can 500.

For Doubao (ByteDance Seed models on Volcengine Ark), set `llm_provider: "doubao"`, `ARK_API_KEY`, deep `doubao-seed-2.1-pro`, and quick `doubao-seed-2.1-turbo`. If the Ark console only issues an inference endpoint, paste the `ep-...` ID as the model name.

For local models, configure Ollama with `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`. Pull models with `ollama pull <name>`, and pick "Custom model ID" in the CLI for any model not listed by default.

For any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, or a custom relay), use `llm_provider: "openai_compatible"` and set the endpoint via `backend_url` (or `TRADINGAGENTS_LLM_BACKEND_URL`), e.g. `http://localhost:8000/v1` for vLLM or `http://localhost:1234/v1` for LM Studio. The model is whatever your server serves. No key is needed for local servers; set `OPENAI_COMPATIBLE_API_KEY` when the endpoint requires one.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

### CLI Usage

Launch the interactive CLI:
```bash
tradingagents          # installed command (interactive analyze)
python -m cli.main     # alternative: run directly from source
tradingagents predict 600519.SS   # on-demand live prediction (today, Chinese reports; does not place orders)
tradingagents score 600519.SS     # T+1 directional hit rate (5-day settled is secondary; research scorecard; not an order)
```
You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more. `predict` skips the menu: Market + News + Sentiment only, no Fundamentals, and never sends orders to a broker.

### Markets and tickers

TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker. Company identity and the alpha benchmark resolve automatically per market.

- US: `AAPL`, `SPY`
- Hong Kong: `0700.HK` · Tokyo: `7203.T` · London: `AZN.L`
- India: `RELIANCE.NS`, `.BO` · Canada: `.TO` · Australia: `.AX`
- China A-shares: Shanghai `.SS` (also `.SH`), Shenzhen `.SZ` (e.g. `600519.SS` for Kweichow Moutai). Point `AKSHARE_BASE_URL` at local AKTools HTTP (`docker compose --profile akshare up -d --build aktools`) or `pip install ".[akshare]"` for East Money news, cninfo filings, CCTV/CLS/East Money/Sina/Tonghuashun/Futu policy wires plus state media (People's Daily, Xinhua finance, Economic Daily, chinanews finance, CCTV News, gov.cn, CNTV 新闻联播, PBOC, Ministry of Finance, NDRC, NBS; ticker news keeps only rows that name the code or short name), Xueqiu sentiment when `XUEQIU_COOKIE` is set, plus East Money Guba posts (no cookie; keyword bull/bear tally on those posts, not the popularity rank), and the Market Analyst short-horizon tape (next session / 5–20 days: amount, turnover, limit flags, breadth, lagged northbound, a deterministic T+1 playbook stance the final rating follows, static industry/commodity map — 沪铜 and LME/COMEX copper, lithium carbonate, iron ore/SGX, soymeal/CBOT, rubber, crude/NYMEX, or a sector index such as liquor/banks). Daily bars, index history, minutes, and dragon-tiger prefer East Money, then Tencent/Sina when East Money RST's from Docker. Live quotes fall back to Xueqiu then Tencent minutes; a live (not historical) run may approximate limit-up/down counts from Sina's spot table. Headlines are deduped, cached by day, and accumulated in a local JSONL warehouse under the data cache directory. Optional `tradingagents ingest-news 600519.SS --global` is a one-shot pull you can schedule yourself — not an in-process worker. A live tape with an empty warehouse also does one ingest for event flags; historical as-of does not. Xueqiu often needs `XUEQIU_COOKIE` (the client also forwards `xq_a_token`). Yahoo is not queried for A-share tickers (it 404s/429s), including realized-return settlement. `tradingagents score` uses next-session (T+1) directional hits as the primary metric and 5-day settled raw as secondary. Without AKTools HTTP or the extra, A-share prices and the tape are unavailable.
- Crypto: `BTC-USD`, `ETH-USD`

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## Developer docs and agent loop

Warehouse facts for contributors and coding agents live under `docs/`. Priority is **code > [docs/PROJECT.md](docs/PROJECT.md) > [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) > [Tech Library](docs/tech-library/README.md)**.

| Doc | Role |
| --- | --- |
| [docs/PROJECT.md](docs/PROJECT.md) | Required read: boundaries, layout, call chain, reuse list, DoD |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Graph, state, vendor routing, LLM factory, extension points |
| [docs/tech-library/README.md](docs/tech-library/README.md) | Confirmed technical decisions and their status |
| [docs/agent-rules/](docs/agent-rules/) | Canonical coding rules (tool adapters only link here) |

**Commands used in development and CI:**

```bash
pip install -e ".[dev]"
tradingagents analyze          # or: python -m cli.main analyze
pytest -q
ruff check .
```

**Cross-tool agent entry** (same `project-dev-loop` skill in all three):

- Cursor: `.cursor/skills/project-dev-loop/SKILL.md`
- Claude Code: `CLAUDE.md` and `.claude/skills/project-dev-loop/SKILL.md`
- Codex: `AGENTS.md` and `.agents/skills/project-dev-loop/SKILL.md`

The current team loop is repository docs, skills, rules, and code review. GitHub Actions already runs tests/lint/install smoke; PR Template, CODEOWNERS, and Branch Protection are not configured in this phase.

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope, international and China endpoints), GLM (Zhipu), MiniMax (global + China), OpenRouter, Ollama for local models, and Azure OpenAI for enterprise.

### Python Usage

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `main.py`, here's also a quick example:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # e.g. openai, google, anthropic, deepseek, doubao, groq, ollama; openai_compatible covers any OpenAI-compatible endpoint (vLLM, LM Studio, llama.cpp, ...)
config["deep_think_llm"] = "gpt-5.6"      # Model for complex reasoning
config["quick_think_llm"] = "gpt-5.6-luna" # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

See `tradingagents/default_config.py` for all configuration options.

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Decision log

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw and alpha vs SPY), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. On a resume run you will see `Resuming from step N for <TICKER> on <date>` in the logs; on a new run you will see `Starting fresh`. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
```

## Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models, not a defect. The variation comes from a few distinct sources, and it helps to separate them.

Language model sampling is non-deterministic. Even at a fixed temperature, providers do not guarantee byte-identical output across calls, and reasoning models (the default GPT-5.x family, and any thinking-mode model) vary the most because their internal reasoning is itself sampled.

Live data moves. News, StockTwits, and Reddit return different content as time passes, so a run today sees different inputs than a run last week even for the same historical trade date. Pin the analysis date to hold the price and indicator window fixed, but the social and news sources still reflect "now".

To reduce variation you can lower the sampling temperature. Set `temperature` in your config (or `TRADINGAGENTS_TEMPERATURE` in `.env`); lower values make models that honor it more repeatable. The current curated models are reasoning-first and largely ignore temperature, so for tighter reproducibility use a non-reasoning model, which you can set explicitly via the Custom model ID option.

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["temperature"] = 0.0
# Reasoning models ignore temperature. For tighter reproducibility, set a
# non-reasoning deep/quick model explicitly (e.g. via the Custom model ID option).
```

What does not vary anymore: the analyzed company identity is resolved deterministically from the ticker before any agent runs, and the market analyst grounds exact price and indicator claims in a verified data snapshot. Earlier reports of "different companies" or fabricated price levels across runs are addressed by these two mechanisms.

Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return.

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
