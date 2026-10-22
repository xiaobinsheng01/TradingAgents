"""One-shot A-share news ingest into the local warehouse.

Not a daemon, cron, or MQ consumer. The CLI command is a single pull that
upserts JSONL; operators may schedule it themselves.

Analyze still pulls on demand. Ingest exists so live CLS/newswire items
survive the short telegraph TTL and fill later lookback windows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .akshare_news import collect_global_news_items, collect_ticker_news_items
from .config import get_config
from .news_store import GLOBAL_KEY
from .news_warehouse import upsert_items
from .symbol_utils import a_share_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    key: str
    fetched: int
    appended: int


def ingest_news(
    ticker: str | None = None,
    *,
    curr_date: str | None = None,
    include_global: bool = False,
    look_back_days: int | None = None,
) -> list[IngestResult]:
    """Fetch configured channels and append unseen items to the warehouse."""
    if not ticker and not include_global:
        raise ValueError("pass an A-share ticker and/or include_global=True")
    if curr_date is None:
        curr_date = datetime.now(timezone.utc).date().isoformat()
    try:
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"curr_date must be yyyy-mm-dd, got {curr_date!r}") from e
    if look_back_days is None:
        look_back_days = int(get_config()["global_news_lookback_days"])
    start_date = (end_dt - timedelta(days=int(look_back_days))).strftime("%Y-%m-%d")

    results: list[IngestResult] = []
    if ticker:
        code = a_share_code(ticker)
        if code is None:
            raise ValueError(
                f"{ticker!r} is not a China A-share symbol; ingest-news is A-share only"
            )
        items = collect_ticker_news_items(code, start_date, curr_date)
        appended = upsert_items(code, items)
        logger.info(
            "Ingested ticker news for %s: fetched=%s appended=%s",
            code,
            len(items),
            appended,
        )
        results.append(IngestResult(key=code, fetched=len(items), appended=appended))
    if include_global:
        items = collect_global_news_items(curr_date, int(look_back_days))
        appended = upsert_items(GLOBAL_KEY, items)
        logger.info(
            "Ingested global wires as of %s: fetched=%s appended=%s",
            curr_date,
            len(items),
            appended,
        )
        results.append(
            IngestResult(key=GLOBAL_KEY, fetched=len(items), appended=appended)
        )
    return results
