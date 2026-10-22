"""Append-only JSONL warehouse for news items across ingest runs.

The per-as-of channel JSON in ``news_store`` is a snapshot for one analysis
date. This warehouse accumulates items so a lookback window can include
flashes pulled earlier the same day (or by ``tradingagents ingest-news``).
It is not a database, MQ, or daemon.

Paths: ``{data_cache_dir}/news/_warehouse/{safe_key}.jsonl``.
``_warehouse`` is reserved (like ``_global``) and is never a ticker key.
Query results go through ``date_window.in_window``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .config import get_config
from .date_window import in_window
from .news_items import NewsItem, dedupe_items, item_identity, pub_datetime
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

WAREHOUSE_DIR = "_warehouse"


def warehouse_path(key: str) -> Path:
    safe_key = safe_ticker_component(key)
    root = Path(get_config()["data_cache_dir"])
    return root / "news" / WAREHOUSE_DIR / f"{safe_key}.jsonl"


def _identity_token(item: NewsItem) -> str | None:
    ident = item_identity(item)
    if ident is None:
        return None
    kind, value = ident
    return f"{kind}\0{value}"


def _iter_stored(path: Path) -> list[NewsItem]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    items: list[NewsItem] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Ignoring unreadable news warehouse %s: %s", path, e)
        return []
    for line_no, line in enumerate(text.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(
                "Skipping corrupt warehouse line %s:%s: %s", path, line_no, e
            )
            continue
        if not isinstance(payload, dict):
            logger.warning(
                "Skipping non-object warehouse line %s:%s", path, line_no
            )
            continue
        item = NewsItem.from_dict(payload)
        if item_identity(item) is None:
            continue
        items.append(item)
    return items


def upsert_items(key: str, items: list[NewsItem]) -> int:
    """Append items whose identity is not already stored. Returns count appended."""
    new_items = [item for item in items if _identity_token(item)]
    if not new_items:
        return 0
    path = warehouse_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = {_identity_token(item) for item in _iter_stored(path)}
    appended = 0
    with path.open("a", encoding="utf-8") as handle:
        for item in new_items:
            token = _identity_token(item)
            if token in seen:
                continue
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            seen.add(token)
            appended += 1
    return appended


def query_items(key: str, start_dt: datetime, end_dt: datetime) -> list[NewsItem]:
    """Return warehouse items inside the half-open analysis window."""
    items = _iter_stored(warehouse_path(key))
    kept = [
        item
        for item in items
        if in_window(pub_datetime(item), start_dt, end_dt)
    ]
    return dedupe_items(kept)
