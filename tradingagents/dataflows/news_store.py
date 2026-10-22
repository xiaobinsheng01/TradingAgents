"""Point-in-time JSON cache for news and A-share sentiment channels.

Historical as-of dates are immutable and reused forever. A live request
(as-of is today) refreshes after ``news_cache_ttl_seconds`` (same idea as
OHLCV same-day TTL in stockstats_utils). Callers may pass ``ttl_seconds``
to ``fetch_cached`` for a shorter live window (telegraph/flash channels).
Empty payloads are never written, so a failed fetch cannot poison later runs.

Paths: ``{data_cache_dir}/news/{safe_key}/{as_of}/{channel}.json``.
Ticker keys go through ``safe_ticker_component``; the global key is ``_global``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

from .config import get_config
from .news_items import NewsItem
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GLOBAL_KEY = "_global"
DEFAULT_TTL_SECONDS = 900


def _ttl_seconds(override: int | None = None) -> int:
    if override is not None:
        try:
            ttl = int(override)
        except (TypeError, ValueError):
            return DEFAULT_TTL_SECONDS
        return ttl if ttl > 0 else DEFAULT_TTL_SECONDS
    raw = get_config().get("news_cache_ttl_seconds", DEFAULT_TTL_SECONDS)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_TTL_SECONDS


def _validate_channel(channel: str) -> str:
    if not isinstance(channel, str) or _CHANNEL_RE.fullmatch(channel) is None:
        raise ValueError(f"invalid news cache channel: {channel!r}")
    return channel


def _validate_as_of(as_of: str) -> str:
    if not isinstance(as_of, str) or _AS_OF_RE.fullmatch(as_of) is None:
        raise ValueError(f"as_of must be yyyy-mm-dd, got {as_of!r}")
    return as_of


def cache_path(key: str, as_of: str, channel: str) -> Path:
    safe_key = safe_ticker_component(key)
    as_of = _validate_as_of(as_of)
    channel = _validate_channel(channel)
    root = Path(get_config()["data_cache_dir"])
    return root / "news" / safe_key / as_of / f"{channel}.json"


def is_live_as_of(as_of: str) -> bool:
    """True when as-of is today (UTC) or later, so the snapshot may still move."""
    today = datetime.now(timezone.utc).date()
    return date.fromisoformat(as_of) >= today


def _is_fresh(path: Path, as_of: str, ttl_seconds: int | None = None) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if not is_live_as_of(as_of):
        return True
    return time.time() - path.stat().st_mtime <= _ttl_seconds(ttl_seconds)


def read_channel(
    key: str,
    as_of: str,
    channel: str,
    *,
    ttl_seconds: int | None = None,
) -> list[NewsItem] | None:
    path = cache_path(key, as_of, channel)
    if not _is_fresh(path, as_of, ttl_seconds):
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Ignoring unreadable news cache %s: %s", path, e)
        return None
    if not isinstance(raw, list) or not raw:
        return None
    items = [NewsItem.from_dict(row) for row in raw if isinstance(row, dict)]
    return items or None


def write_channel(key: str, as_of: str, channel: str, items: list[NewsItem]) -> None:
    if not items:
        return
    path = cache_path(key, as_of, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in items]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_cached(
    key: str,
    as_of: str,
    channel: str,
    loader: Callable[[], list[NewsItem]],
    *,
    ttl_seconds: int | None = None,
) -> list[NewsItem]:
    cached = read_channel(key, as_of, channel, ttl_seconds=ttl_seconds)
    if cached is not None:
        return cached
    items = loader()
    write_channel(key, as_of, channel, items)
    return items


def read_records(
    key: str,
    as_of: str,
    channel: str,
    *,
    ttl_seconds: int | None = None,
) -> list[dict] | None:
    """Same path/TTL rules as ``read_channel``, but rows stay plain dicts."""
    path = cache_path(key, as_of, channel)
    if not _is_fresh(path, as_of, ttl_seconds):
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Ignoring unreadable news cache %s: %s", path, e)
        return None
    if not isinstance(raw, list) or not raw:
        return None
    return [row for row in raw if isinstance(row, dict)] or None


def write_records(key: str, as_of: str, channel: str, rows: list[dict]) -> None:
    if not rows:
        return
    path = cache_path(key, as_of, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_cached_records(
    key: str,
    as_of: str,
    channel: str,
    loader: Callable[[], list[dict]],
    *,
    ttl_seconds: int | None = None,
) -> list[dict]:
    cached = read_records(key, as_of, channel, ttl_seconds=ttl_seconds)
    if cached is not None:
        return cached
    rows = loader()
    write_records(key, as_of, channel, rows)
    return rows
