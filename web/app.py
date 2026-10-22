"""FastAPI app for the local research console.

Serves a single-user UI on loopback. Graph runs still go through
``route_to_vendor``. ``GET /api/screen`` is a same-day main-board research
snapshot for this console, not a market-data API and not an order.
``GET /api/index-outlook`` is the same-day major-index research snapshot.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cli.models import AnalystType
from cli.run_engine import run_graph_with_events
from cli.utils import (
    ANALYST_ORDER,
    CRYPTO_SUFFIXES,
    OUTPUT_LANGUAGE_OPTIONS,
    RESEARCH_DEPTH_OPTIONS,
    detect_asset_type,
    filter_analysts_for_asset_type,
    provider_default_url,
    resolve_backend_url,
)
from tradingagents.dataflows.akshare_news import AkshareNotConfiguredError
from tradingagents.dataflows.ashare_index_outlook import (
    IndexOutlookNotLiveError,
    index_outlook,
    index_outlook_bars,
)
from tradingagents.dataflows.ashare_screen import (
    ScreenNotLiveError,
    screen_main_board,
    screen_price_bars,
    screen_tomorrow_rise,
)
from tradingagents.dataflows.ashare_trend_predict import (
    TrendPredictNotLiveError,
    stock_trend_predict,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.reporting import load_latest_run
from web.schemas import RunRequest, TrendPredictRequest, parse_ticker_list

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

_PROVIDER_LABELS: list[tuple[str, str]] = [
    ("openai", "OpenAI"),
    ("google", "Google"),
    ("anthropic", "Anthropic"),
    ("xai", "xAI"),
    ("deepseek", "DeepSeek"),
    ("doubao", "Doubao (Volcengine Ark)"),
    ("qwen", "Qwen (International)"),
    ("qwen-cn", "Qwen (China)"),
    ("glm", "GLM (Z.AI international)"),
    ("glm-cn", "GLM (BigModel China)"),
    ("minimax", "MiniMax (Global)"),
    ("minimax-cn", "MiniMax (China)"),
    ("openrouter", "OpenRouter"),
    ("mistral", "Mistral"),
    ("kimi", "Kimi (Moonshot)"),
    ("groq", "Groq"),
    ("nvidia", "NVIDIA NIM"),
    ("azure", "Azure OpenAI"),
    ("bedrock", "Amazon Bedrock"),
    ("ollama", "Ollama"),
    ("openai_compatible", "OpenAI-compatible"),
]

_REGION_URLS = {
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "qwen-cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://api.z.ai/api/paas/v4/",
    "glm-cn": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax": "https://api.minimax.io/v1",
    "minimax-cn": "https://api.minimaxi.com/v1",
}

RunFn = Callable[..., dict[str, Any]]


def _key_configured(provider: str) -> bool:
    env_name = get_api_key_env(provider)
    if env_name is None:
        return True
    return bool(os.environ.get(env_name))


def console_options() -> dict[str, Any]:
    """Catalog for the form. Never includes secret values."""
    cfg = DEFAULT_CONFIG
    models: dict[str, dict[str, list[dict[str, str]]]] = {}
    for key, _label in _PROVIDER_LABELS:
        models[key] = {}
        for mode in ("quick", "deep"):
            try:
                entries = get_model_options(key, mode)
            except KeyError:
                entries = [("Custom model ID", "custom")]
            models[key][mode] = [
                {"label": label, "id": model_id} for label, model_id in entries
            ]
    providers = []
    for key, label in _PROVIDER_LABELS:
        env_name = get_api_key_env(key)
        providers.append(
            {
                "key": key,
                "label": label,
                "default_url": _REGION_URLS.get(key) or provider_default_url(key),
                "key_env": env_name,
                "key_configured": _key_configured(key),
                "needs_url": key == "openai_compatible",
            }
        )
    return {
        "analysts": [
            {"key": analyst.value, "label": display}
            for display, analyst in ANALYST_ORDER
        ],
        "research_depth": [
            {"label": label, "value": value} for label, value in RESEARCH_DEPTH_OPTIONS
        ],
        "languages": [
            {"label": label, "value": value} for label, value in OUTPUT_LANGUAGE_OPTIONS
            if value != "custom"
        ],
        "providers": providers,
        "models": models,
        "crypto_suffixes": list(CRYPTO_SUFFIXES),
        "defaults": {
            "ticker": "600519.SS",
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "output_language": cfg.get("output_language") or "Chinese",
            "analysts": ["market", "social", "news"],
            "research_depth": cfg.get("max_debate_rounds") or 1,
            "llm_provider": str(cfg.get("llm_provider") or "openai").lower(),
            "shallow_thinker": cfg.get("quick_think_llm"),
            "deep_thinker": cfg.get("deep_think_llm"),
            "backend_url": cfg.get("backend_url"),
            "checkpoint": bool(cfg.get("checkpoint_enabled")),
            "ingest_news": True,
            "swing_tape_window": str(cfg.get("swing_tape_window") or "half_month"),
        },
        "swing_windows": [
            {"key": "half_month", "label": "近半个月（15 个日历日）"},
            {"key": "three_months", "label": "近3个月（90 个日历日）"},
            {"key": "half_year", "label": "近半年（180 个日历日）"},
        ],
        "notice": "研究评级，永不下单。密钥只读本机 .env，不会出现在页面上。",
    }


def selections_from_request(body: RunRequest) -> dict[str, Any]:
    asset_type = detect_asset_type(body.ticker)
    requested = [AnalystType(key) for key in body.analysts]
    analysts = filter_analysts_for_asset_type(requested, asset_type)
    if not analysts:
        raise ValueError("at least one analyst must be selected for this asset type")
    provider = (body.llm_provider or str(DEFAULT_CONFIG["llm_provider"])).lower()
    backend = resolve_backend_url(
        provider,
        menu_url=body.backend_url,
        env_url=DEFAULT_CONFIG.get("backend_url") if not body.backend_url else None,
    )
    if provider == "openai_compatible" and not backend:
        raise ValueError("openai_compatible requires backend_url")
    return {
        "ticker": body.ticker,
        "asset_type": asset_type.value,
        "analysis_date": body.analysis_date or datetime.now().strftime("%Y-%m-%d"),
        "analysts": analysts,
        "research_depth": body.research_depth,
        "llm_provider": provider,
        "backend_url": backend,
        "shallow_thinker": body.shallow_thinker or DEFAULT_CONFIG["quick_think_llm"],
        "deep_thinker": body.deep_thinker or DEFAULT_CONFIG["deep_think_llm"],
        "google_thinking_level": body.google_thinking_level,
        "openai_reasoning_effort": body.openai_reasoning_effort,
        "anthropic_effort": body.anthropic_effort,
        "output_language": body.output_language,
        "swing_tape_window": body.swing_tape_window,
    }


def create_app(
    *,
    run_fn: RunFn = run_graph_with_events,
    serve_frontend: bool = True,
    results_dir: Path | str | None = None,
) -> FastAPI:
    """Build the local UI app. ``run_fn`` is injectable for tests.

    ``serve_frontend=False`` is the compose ``web-api`` mode: JSON/SSE only.
    Static files then come from the ``web-ui`` nginx service.
    """
    app = FastAPI(title="TradingAgents local console", docs_url=None, redoc_url=None)
    run_lock = threading.Lock()
    app.state.run_lock = run_lock
    app.state.results_dir = Path(
        results_dir if results_dir is not None else DEFAULT_CONFIG["results_dir"]
    )

    @app.get("/api/options")
    def get_options():
        return console_options()

    @app.get("/api/screen")
    def get_screen(as_of: str | None = None):
        """Same-day main-board research snapshot. Not a quote API and not an order."""
        try:
            return screen_main_board(as_of)
        except ScreenNotLiveError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AkshareNotConfiguredError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/tomorrow-rise")
    def get_tomorrow_rise(as_of: str | None = None):
        """Same-day T+1 BUY list excluding ChiNext. Not a quote API and not an order."""
        try:
            return screen_tomorrow_rise(as_of)
        except ScreenNotLiveError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AkshareNotConfiguredError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/screen/bars")
    def get_screen_bars(ticker: str, as_of: str | None = None):
        """Daily bars for the screen chart (ChiNext excluded). Not an order."""
        try:
            return screen_price_bars(ticker, as_of)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AkshareNotConfiguredError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/index-outlook")
    def get_index_outlook(as_of: str | None = None):
        """Same-day major-index research snapshot. Not a quote API and not an order."""
        try:
            return index_outlook(as_of)
        except IndexOutlookNotLiveError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AkshareNotConfiguredError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/index-outlook/bars")
    def get_index_outlook_bars(symbol: str, as_of: str | None = None):
        """Daily bars for one whitelisted index. Not an order."""
        try:
            return index_outlook_bars(symbol, as_of)
        except IndexOutlookNotLiveError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AkshareNotConfiguredError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/trend-predict")
    def post_trend_predict(body: TrendPredictRequest):
        """Same-day multi-ticker trend snapshot. Not an order."""
        try:
            tickers = parse_ticker_list(body.tickers)
            return stock_trend_predict(
                tickers,
                as_of=body.as_of,
                window=body.swing_tape_window,
            )
        except TrendPredictNotLiveError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AkshareNotConfiguredError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/runs/latest")
    def get_latest_run(ticker: str | None = None):
        """Newest saved report tree. File lookup, not a database."""
        try:
            payload = load_latest_run(app.state.results_dir, ticker=ticker)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="No saved analysis yet. Run an analysis first.",
            )
        return payload

    @app.post("/api/runs")
    def start_run(body: RunRequest):
        if not run_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="A run is already in progress on this process.",
            )
        try:
            selections = selections_from_request(body)
        except ValueError as e:
            run_lock.release()
            raise HTTPException(status_code=400, detail=str(e)) from e

        provider = selections["llm_provider"]
        if not _key_configured(provider):
            env_name = get_api_key_env(provider)
            run_lock.release()
            raise HTTPException(
                status_code=400,
                detail=f"{env_name} is not set in the environment.",
            )

        queue: Queue = Queue()
        sentinel = object()

        def worker() -> None:
            try:
                def on_event(event: dict[str, Any]) -> None:
                    queue.put(event)

                if body.ingest_news:
                    from tradingagents.dataflows.akshare_news import (
                        AkshareNotConfiguredError,
                    )
                    from tradingagents.dataflows.news_ingest import ingest_news
                    from tradingagents.dataflows.symbol_utils import a_share_code

                    if a_share_code(selections["ticker"]) is not None:
                        try:
                            ingest_news(
                                ticker=selections["ticker"],
                                curr_date=selections["analysis_date"],
                                include_global=True,
                            )
                        except (AkshareNotConfiguredError, ValueError) as e:
                            logger.warning("Skipping news ingest: %s", e)

                run_fn(
                    selections,
                    checkpoint=body.checkpoint,
                    on_event=on_event,
                    save_report=True,
                )
            except Exception as e:
                logger.exception("Web console run failed")
                queue.put({"type": "error", "message": str(e)})
            finally:
                queue.put(sentinel)
                run_lock.release()

        thread = threading.Thread(target=worker, name="tradingagents-web-run", daemon=True)
        thread.start()

        def event_stream():
            while True:
                try:
                    item = queue.get(timeout=1.0)
                except Empty:
                    yield ": keepalive\n\n"
                    continue
                if item is sentinel:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if serve_frontend:
        @app.get("/")
        def index():
            return FileResponse(STATIC_DIR / "index.html")

        if STATIC_DIR.is_dir():
            app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
