"""Overseas global news via Serper (Google Search API).

``get_global_news`` stays market-wide (not company news). Live runs call
Serper (``SERPER_API_KEY``) for headlines and ``site:`` queries covering
public X / YouTube / Meta posts. This repo does not scrape those networks
or call their private APIs. If the Serper key is unset, Google News RSS is
the last-resort fallback.

Google's index has no point-in-time vintage, so historical as-of dates reuse
cache only and never hit the live index.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests

from .config import get_config
from .date_window import in_window
from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError
from .news_items import NewsItem, dedupe_items, render_items
from .news_store import GLOBAL_KEY, fetch_cached, is_live_as_of

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_NEWS_URL = "https://google.serper.dev/news"
NEWS_RSS_URL = "https://news.google.com/rss/search"
_UA = "Mozilla/5.0 (compatible; TradingAgents/0.4; +https://github.com/TauricResearch/TradingAgents)"

_PLATFORM_HOSTS = {
    "x.com": ("X", "google_x"),
    "twitter.com": ("X", "google_x"),
    "t.co": ("X", "google_x"),
    "youtube.com": ("YouTube", "google_youtube"),
    "m.youtube.com": ("YouTube", "google_youtube"),
    "youtu.be": ("YouTube", "google_youtube"),
    "facebook.com": ("Meta", "google_meta"),
    "m.facebook.com": ("Meta", "google_meta"),
    "instagram.com": ("Meta", "google_meta"),
}

_DEFAULT_NEWS_QUERIES = (
    "China A-share stock market CSI 300 overnight US futures",
    "Federal Reserve interest rates inflation China yuan USD",
    "copper lithium iron ore oil China commodities",
    "geopolitical risk tariffs China trade",
    "ECB BOJ central bank policy emerging markets",
)
_DEFAULT_PLATFORM_TOPICS = ("China stocks OR A-shares OR CSI 300",)
_DEFAULT_SITES = (
    "x.com",
    "twitter.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
)


def _serper_key() -> str | None:
    for name in ("SERPER_API_KEY", "TRADINGAGENTS_SERPER_API_KEY"):
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip()
    return None


def _config_list(key: str, fallback: tuple[str, ...]) -> list[str]:
    raw = get_config().get(key)
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return list(fallback)


def _host(link: str) -> str:
    host = (urlparse(link).hostname or "").casefold()
    return host.removeprefix("www.")


def _platform_meta(link: str) -> tuple[str, str]:
    host = _host(link)
    if host in _PLATFORM_HOSTS:
        return _PLATFORM_HOSTS[host]
    for suffix, meta in _PLATFORM_HOSTS.items():
        if host.endswith("." + suffix):
            return meta
    return (host or "Google", "google_news")


def _parse_pub(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        pass
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass
    padded = text
    bits = text.replace(",", " ").split()
    if len(bits) >= 3 and bits[1].isdigit() and len(bits[1]) == 1:
        padded = f"{bits[0]} 0{bits[1]}, {bits[2]}"
    for candidate in (text, padded):
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    for fmt, size in (
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        snippet = text[:size] if len(text) >= size else text
        try:
            return datetime.strptime(snippet, fmt)
        except ValueError:
            continue
    return None


def _iso_or_none(value: Any) -> str | None:
    parsed = _parse_pub(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(sep=" ", timespec="seconds")


def _item_from_fields(
    *,
    title: str,
    body: str,
    link: str,
    pub_raw: Any,
    default_source: str,
) -> NewsItem | None:
    title = (title or "").strip()
    if not title:
        return None
    source, channel = _platform_meta(link)
    if source == "Google" or channel == "google_news":
        source = default_source or source
    return NewsItem(
        title=title[:240],
        body=(body or "").strip()[:500],
        source=source,
        link=link.strip(),
        pub_date=_iso_or_none(pub_raw),
        channel=channel,
        category="platform" if channel != "google_news" else "news",
    )


def _serper_tbs(look_back_days: int) -> str:
    days = max(1, int(look_back_days))
    if days <= 1:
        return "qdr:d"
    if days <= 7:
        return "qdr:w"
    if days <= 31:
        return "qdr:m"
    return "qdr:y"


def _http_get(url: str, params: dict[str, str] | None = None) -> requests.Response:
    try:
        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "application/rss+xml, */*"},
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Google News RSS HTTP failed: {e}") from e
    if response.status_code == 429:
        raise VendorRateLimitError("Google News RSS rate-limited")
    return response


def _serper_post(url: str, query: str, *, look_back_days: int, num: int) -> dict[str, Any]:
    key = _serper_key()
    if not key:
        return {}
    body = {
        "q": query,
        "num": min(10, max(1, int(num))),
        "gl": "us",
        "hl": "en",
        "tbs": _serper_tbs(look_back_days),
    }
    try:
        response = requests.post(
            url,
            json=body,
            timeout=REQUEST_TIMEOUT,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Serper HTTP failed: {e}") from e
    if response.status_code == 429:
        raise VendorRateLimitError("Serper rate-limited")
    if response.status_code in {401, 403}:
        raise VendorNotConfiguredError(
            f"Serper rejected the API key with HTTP {response.status_code}"
        )
    if response.status_code >= 400:
        logger.warning(
            "Serper returned %s for %r: %s",
            response.status_code,
            query,
            response.text[:200],
        )
        return {}
    try:
        payload = response.json()
    except ValueError as e:
        raise RuntimeError("Serper returned non-JSON") from e
    return payload if isinstance(payload, dict) else {}


def _items_from_serper_rows(rows: Any, default_source: str) -> list[NewsItem]:
    if not isinstance(rows, list):
        return []
    items: list[NewsItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or default_source).strip()
        item = _item_from_fields(
            title=str(row.get("title") or ""),
            body=str(row.get("snippet") or ""),
            link=str(row.get("link") or ""),
            pub_raw=row.get("date") or row.get("dateUtc"),
            default_source=source,
        )
        if item:
            items.append(item)
    return items


def _serper_search(query: str, *, look_back_days: int, num: int) -> list[NewsItem]:
    if "site:" in query:
        payload = _serper_post(
            SERPER_SEARCH_URL, query, look_back_days=look_back_days, num=num
        )
        return _items_from_serper_rows(payload.get("organic"), "Google")
    payload = _serper_post(
        SERPER_NEWS_URL, query, look_back_days=look_back_days, num=num
    )
    return _items_from_serper_rows(payload.get("news"), "Google News")


def _rss_search(query: str) -> list[NewsItem]:
    response = _http_get(
        NEWS_RSS_URL,
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
    )
    if response.status_code >= 400:
        logger.warning(
            "Google News RSS returned %s for %r",
            response.status_code,
            query,
        )
        return []
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.warning("Google News RSS XML parse failed for %r: %s", query, e)
        return []
    items: list[NewsItem] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        source_el = node.find("source")
        source = (
            (source_el.text or "").strip()
            if source_el is not None
            else "Google News"
        )
        item = _item_from_fields(
            title=title,
            body=(node.findtext("description") or "").strip(),
            link=link,
            pub_raw=node.findtext("pubDate"),
            default_source=source or "Google News",
        )
        if item:
            items.append(item)
    return items


def _search_query(query: str, *, look_back_days: int, num: int) -> list[NewsItem]:
    if _serper_key() is not None:
        found = _serper_search(query, look_back_days=look_back_days, num=num)
        if found:
            return found
        logger.info("Serper empty for %r; trying News RSS", query)
    return _rss_search(query)


def _filter_window(
    items: list[NewsItem], start_dt: datetime, end_dt: datetime
) -> list[NewsItem]:
    kept: list[NewsItem] = []
    for item in items:
        if in_window(_parse_pub(item.pub_date), start_dt, end_dt):
            kept.append(item)
    return kept


def _overseas_unreachable(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "network is unreachable",
        "timed out",
        "timeout",
        "failed to establish",
        "name or service not known",
        "nodename nor servname",
        "temporary failure in name resolution",
    )
    return any(marker in text for marker in markers)


def _run_searches(look_back_days: int, limit: int) -> list[NewsItem]:
    news_queries = _config_list("global_news_queries", _DEFAULT_NEWS_QUERIES)
    topics = _config_list("google_platform_queries", _DEFAULT_PLATFORM_TOPICS)
    sites = _config_list("google_platform_sites", _DEFAULT_SITES)
    per_query = min(10, max(3, int(limit)))
    collected: list[NewsItem] = []
    unreachable = False

    def _one(query: str, label: str) -> None:
        nonlocal unreachable
        if unreachable:
            return
        try:
            collected.extend(
                _search_query(query, look_back_days=look_back_days, num=per_query)
            )
        except (VendorRateLimitError, VendorNotConfiguredError):
            raise
        except Exception as e:
            if _overseas_unreachable(e):
                unreachable = True
                logger.warning(
                    "Overseas Google/Serper unreachable (%s); "
                    "skipping the remaining queries this run",
                    e,
                )
                return
            logger.warning("%s %r failed: %s", label, query, e)

    for query in news_queries:
        _one(query, "Google news query")
        if len(collected) >= int(limit) * 3:
            break
    if not unreachable:
        for topic in topics:
            for site in sites:
                _one(f"{topic} site:{site}", "Google platform query")
                if unreachable:
                    break
    return collected


def collect_google_global_items(
    curr_date: str, look_back_days: int, limit: int
) -> list[NewsItem]:
    """Live Serper/Google Search hits, cached per as-of. Historical as-of is cache-only."""

    def _load() -> list[NewsItem]:
        if not is_live_as_of(curr_date):
            return []
        return _run_searches(look_back_days, limit)

    return fetch_cached(GLOBAL_KEY, curr_date, "google_search", _load)


def get_global_news(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """Overseas headlines and public platform snippets via Serper / Google Search."""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=int(look_back_days))
    cap = int(limit)
    fetched = collect_google_global_items(curr_date, int(look_back_days), cap)
    kept = dedupe_items(_filter_window(fetched, start_dt, end_dt))
    news = [item for item in kept if item.channel == "google_news"]
    platforms = [item for item in kept if item.channel != "google_news"]
    sections: list[str] = []
    news_body = render_items(news, cap)
    if news_body:
        sections.append(
            "## Overseas headlines (Serper Google Search, China-market relevant)\n\n"
            + news_body
        )
    platform_body = render_items(platforms, cap)
    if platform_body:
        sections.append(
            "## Overseas platform posts (X / YouTube / Meta via Serper site search)\n\n"
            + platform_body
        )
    body = "\n\n".join(sections)
    if not body:
        raise NoMarketDataError(
            "global",
            "global",
            "no Google Search headlines or platform posts in the window "
            "(historical as-of has no live index vintage; live runs need "
            "SERPER_API_KEY or reachable News RSS)",
        )
    start = start_dt.strftime("%Y-%m-%d")
    return (
        f"## Overseas market news via Serper, from {start} to {curr_date}:\n\n"
        f"{body}"
    )
