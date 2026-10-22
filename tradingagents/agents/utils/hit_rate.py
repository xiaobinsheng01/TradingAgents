"""Directional hit rate from the append-only memory log.

This is a research scorecard, not a backtest of a tradable strategy. BUY /
Overweight count as hits when the return is positive; SELL / Underweight when
it is negative. Hold stays out of the directional rate. The primary window is
the next session (T+1); the 5-day settled raw from memory tags is secondary.
Pending 5-day rows can still be scored on T+1 once that close exists. The
framework never places orders.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.rating import RATINGS_5_TIER

logger = logging.getLogger(__name__)

_BULL = frozenset({"Buy", "Overweight"})
_BEAR = frozenset({"Sell", "Underweight"})

NextSessionLoader = Callable[[str, str], tuple[float, str] | None]


def parse_logged_pct(raw: str | None) -> float | None:
    """Parse memory-log percent fields such as ``+4.2%`` or ``-1.0%``."""
    if not raw or raw == "pending":
        return None
    text = str(raw).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if text.startswith("+"):
        text = text[1:]
    try:
        return float(text) / 100.0
    except ValueError:
        return None


def _directional_hit(rating: str, raw_return: float) -> bool | None:
    if rating in _BULL:
        return raw_return > 0
    if rating in _BEAR:
        return raw_return < 0
    return None


def _horizon_stats(
    rows: list[dict[str, Any]],
    raw_of: Callable[[dict[str, Any]], float | None],
) -> dict[str, Any]:
    directional: list[dict[str, Any]] = []
    hits = 0
    raw_sum = 0.0
    raw_n = 0
    for row in rows:
        raw = raw_of(row)
        if raw is not None:
            raw_sum += raw
            raw_n += 1
        hit = _directional_hit(row.get("rating") or "", raw) if raw is not None else None
        if hit is None:
            continue
        directional.append(row)
        if hit:
            hits += 1
    return {
        "directional": len(directional),
        "hits": hits,
        "hit_rate": (hits / len(directional)) if directional else None,
        "mean_raw": (raw_sum / raw_n) if raw_n else None,
    }


def fetch_next_session_return(ticker: str, trade_date: str) -> tuple[float, str] | None:
    """As-of close → next session close. Fail-open so 5-day stats still print."""
    from tradingagents.dataflows.akshare_market import next_session_raw_return
    from tradingagents.dataflows.akshare_news import AkshareNotConfiguredError
    from tradingagents.dataflows.errors import NoMarketDataError

    try:
        return next_session_raw_return(ticker, trade_date)
    except (AkshareNotConfiguredError, NoMarketDataError, ValueError, OSError) as e:
        logger.warning("T+1 return unavailable for %s %s: %s", ticker, trade_date, e)
        return None


def summarize_memory_log(
    log: TradingMemoryLog,
    *,
    ticker: str | None = None,
    next_session_loader: NextSessionLoader | None = None,
) -> dict:
    """Aggregate pending / resolved / T+1 and 5-day directional rates from ``log``."""
    entries = log.load_entries()
    if ticker:
        entries = [row for row in entries if row.get("ticker") == ticker]
    pending = [row for row in entries if row.get("pending")]
    resolved = [row for row in entries if not row.get("pending")]

    annotated: list[dict[str, Any]] = []
    for row in entries:
        item = dict(row)
        if next_session_loader is not None:
            loaded = next_session_loader(str(row.get("ticker") or ""), str(row.get("date") or ""))
            if loaded is not None:
                item["t1_raw"] = loaded[0]
                item["t1_date"] = loaded[1]
        annotated.append(item)

    t1 = _horizon_stats(
        annotated,
        lambda row: row.get("t1_raw") if isinstance(row.get("t1_raw"), (int, float)) else None,
    )
    hold5 = _horizon_stats(resolved, lambda row: parse_logged_pct(row.get("raw")))
    by_rating: dict[str, dict[str, Any]] = {}
    for label in sorted(_BULL | _BEAR):
        subset = [row for row in annotated if row.get("rating") == label]
        by_rating[label] = _horizon_stats(
            subset,
            lambda row: row.get("t1_raw")
            if isinstance(row.get("t1_raw"), (int, float))
            else None,
        )
    return {
        "ticker": ticker,
        "total": len(entries),
        "pending": len(pending),
        "resolved": len(resolved),
        "t1_directional": t1["directional"],
        "t1_hits": t1["hits"],
        "t1_hit_rate": t1["hit_rate"],
        "t1_mean_raw": t1["mean_raw"],
        "hold_5d_directional": hold5["directional"],
        "hold_5d_hits": hold5["hits"],
        "hold_5d_hit_rate": hold5["hit_rate"],
        "hold_5d_mean_raw": hold5["mean_raw"],
        "directional": t1["directional"],
        "hits": t1["hits"],
        "hit_rate": t1["hit_rate"],
        "mean_raw": t1["mean_raw"],
        "ratings": list(RATINGS_5_TIER),
        "entries": annotated,
        "t1_by_rating": by_rating,
    }
