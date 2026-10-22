"""AKShare news vendor for China A-shares.

Aggregates East Money company news, CLS/East Money/Sina/Tonghuashun/Futu
flashes, exchange filings, CCTV 新闻联播, state-media headlines
(人民日报、新华社财经、中国经济网、中新网财经、央视新闻、中国政府网、
新闻联播 CNTV 栏目、中国人民银行、财政部、国家发改委、国家统计局),
and policy telegraphs into markdown.
AKShare is either a local
AKTools HTTP server (``AKSHARE_BASE_URL``, typically Docker on :8080) or the
optional extra ``pip install '.[akshare]'``. Missing both raises
``AkshareNotConfiguredError`` so the router can skip to yfinance.

Each endpoint is isolated: timeout, empty frames, and exceptions log and
degrade that channel. Dated items go through ``date_window.in_window``.
``get_news`` keeps East Money rows whose title mentions the six-digit
code or company short name (a body-only short-name hit is not enough;
exchange filings are excepted). Market-wide wires belong in
``get_global_news``.
Per-channel JSON is cached under ``data_cache_dir/news``; flashes also
accumulate in the append-only warehouse. Merged output is deduped across
channels and the warehouse lookback window.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from .config import get_config
from .date_window import in_window
from .errors import NoMarketDataError, VendorNotConfiguredError
from .news_items import NewsItem, dedupe_items, is_policy_item, pub_datetime, render_items
from .news_store import GLOBAL_KEY, fetch_cached, is_live_as_of
from .news_warehouse import query_items, upsert_items
from .state_media_news import STATE_MEDIA_CHANNELS, fetch_state_media_channel
from .symbol_utils import a_share_code, a_share_prefixed_symbol

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
DEFAULT_TELEGRAPH_TTL_SECONDS = 120
TELEGRAPH_CHANNELS = frozenset(
    {"cls_alerts", "cls_flash", "em_flash", "sina_flash", "ths_flash", "futu_flash"}
)
# Market wires. Tonghuashun and Futu enter company news only when the row
# mentions the ticker; get_global_news keeps the unfiltered wire.
_WIRE_SPECS: tuple[tuple[str, str, dict, str], ...] = (
    ("cls_flash", "stock_info_global_cls", {"symbol": "全部"}, "财联社"),
    ("em_flash", "stock_info_global_em", {}, "东方财富快讯"),
    ("sina_flash", "stock_info_global_sina", {}, "新浪财经"),
    ("ths_flash", "stock_info_global_ths", {}, "同花顺"),
    ("futu_flash", "stock_info_global_futu", {}, "富途"),
)
_TICKER_WIRE_CHANNELS = frozenset({"ths_flash", "futu_flash"})
_STATE_MEDIA_CHANNELS = frozenset(STATE_MEDIA_CHANNELS)
_FILING_CHANNELS = frozenset({"cninfo"})
_ST_PREFIX = re.compile(r"^\*?ST", re.IGNORECASE)

_TITLE_KEYS = ("新闻标题", "公告标题", "标题", "title")
_BODY_KEYS = ("新闻内容", "公告内容", "内容", "摘要", "content", "summary")
_DATE_KEYS = ("发布时间", "公告时间", "发布日期", "date", "pub_date")
_LINK_KEYS = ("新闻链接", "公告链接", "链接", "link", "url")
_SOURCE_KEYS = ("文章来源", "来源", "publisher", "source")
_TYPE_KEYS = ("公告类型", "category", "类型", "栏目")


class AkshareNotConfiguredError(VendorNotConfiguredError):
    """Raised when akshare is selected but neither the extra nor AKTools HTTP is set."""


def _running_in_docker() -> bool:
    return Path("/.dockerenv").is_file()


def _rewrite_loopback_aktools_url(base_url: str) -> str:
    """Host ``.env`` uses 127.0.0.1; inside Compose that is this container, not AKTools."""
    if not _running_in_docker():
        return base_url
    parsed = urlparse(base_url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return base_url
    host = os.environ.get("AKSHARE_DOCKER_HOST", "aktools").strip() or "aktools"
    port = parsed.port or 8080
    return urlunparse(parsed._replace(netloc=f"{host}:{port}"))


def resolve_akshare_base_url() -> str | None:
    """AKTools HTTP base, e.g. ``http://127.0.0.1:8080``. Empty means use the pip extra."""
    cfg = get_config().get("akshare_base_url")
    text = ""
    if cfg:
        text = str(cfg).strip().rstrip("/")
    if not text:
        for env_name in ("AKSHARE_BASE_URL", "TRADINGAGENTS_AKSHARE_BASE_URL"):
            raw = os.environ.get(env_name)
            if raw and raw.strip():
                text = raw.strip().rstrip("/")
                break
    if not text:
        return None
    return _rewrite_loopback_aktools_url(text)


def _json_to_records(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    err = data.get("error")
    if err:
        raise RuntimeError(str(err))
    detail = data.get("detail")
    if detail and "data" not in data:
        raise RuntimeError(str(detail))
    for key in ("data", "item", "items", "result"):
        inner = data.get(key)
        if isinstance(inner, list):
            return [row for row in inner if isinstance(row, dict)]
    values = list(data.values())
    if data and all(isinstance(v, list) for v in values):
        keys = list(data)
        length = min(len(data[key]) for key in keys)
        return [{key: data[key][i] for key in keys} for i in range(length)]
    if data:
        return [data]
    return []


def _ak_interface_missing(exc: BaseException) -> bool:
    """AKTools 404 when this akshare build has no such ``/api/public/<name>``."""
    return "未找到该接口" in str(exc)


class AktoolsHttpClient:
    """Duck-typed akshare module that calls a local AKTools Docker HTTP API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args, **kwargs):
            if args:
                raise TypeError(
                    f"AKTools HTTP client only accepts keyword arguments for {name}"
                )
            params = {
                key: value
                for key, value in kwargs.items()
                if value is not None
            }
            url = f"{self.base_url}/api/public/{name}"
            try:
                response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                raise RuntimeError(f"AKTools HTTP {name} failed: {e}") from e
            if response.status_code >= 400:
                raise RuntimeError(
                    f"AKTools HTTP {name} returned {response.status_code}: "
                    f"{response.text[:300]}"
                )
            try:
                payload = response.json()
            except ValueError as e:
                raise RuntimeError(f"AKTools HTTP {name} returned non-JSON") from e
            return _json_to_records(payload)

        return _call


def _load_akshare() -> Any:
    """AKTools HTTP (Docker) if configured, otherwise the optional pip extra."""
    base_url = resolve_akshare_base_url()
    if base_url:
        return AktoolsHttpClient(base_url)
    try:
        import akshare as ak
    except ImportError as e:
        raise AkshareNotConfiguredError(
            "akshare is not configured. Set AKSHARE_BASE_URL to a local AKTools "
            "HTTP server (docker compose --profile akshare up -d --build aktools, "
            "e.g. http://127.0.0.1:8080) or pip install '.[akshare]'."
        ) from e
    return ak


def _call_with_timeout(func, *args, timeout: float | None = None, **kwargs):
    """Run an AKShare call with the same 30s cap as FRED / Polymarket.

    ``timeout`` overrides that cap for one call. It is not forwarded to AKShare.
    """
    limit = REQUEST_TIMEOUT if timeout is None else timeout
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=limit)
        except FuturesTimeoutError as e:
            raise TimeoutError(f"akshare call timed out after {limit:g}s") from e


def _as_records(frame: Any) -> list[dict]:
    if frame is None:
        return []
    empty = getattr(frame, "empty", None)
    if empty is True:
        return []
    to_dict = getattr(frame, "to_dict", None)
    if callable(to_dict):
        records = to_dict(orient="records")
        return [row for row in records if isinstance(row, dict)]
    if isinstance(frame, list):
        return [row for row in frame if isinstance(row, dict)]
    return []


def _field(row: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return ""


def _parse_pub_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    for fmt, size in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
        ("%Y%m%d", 8),
    ):
        snippet = text[:size] if len(text) >= size else text
        try:
            return datetime.strptime(snippet, fmt)
        except ValueError:
            continue
    return None


def _iso_or_none(value: Any) -> str | None:
    parsed = _parse_pub_dt(value)
    return parsed.isoformat(sep=" ") if parsed else None


def _name_aliases(name: str) -> tuple[str, ...]:
    text = str(name or "").strip()
    if len(text) < 2:
        return ()
    aliases = [text]
    stripped = _ST_PREFIX.sub("", text).strip()
    if stripped != text and len(stripped) >= 2:
        aliases.append(stripped)
    return tuple(dict.fromkeys(aliases))


def fetch_a_share_profile_rows(ak, code: str) -> list[dict]:
    """East Money profile, then CNINFO, then Xueqiu. Never the full code-name table."""
    prefixed = a_share_prefixed_symbol(code).upper()
    attempts = (
        ("stock_individual_info_em", {"symbol": code}),
        ("stock_profile_cninfo", {"symbol": code}),
        ("stock_individual_basic_info_xq", {"symbol": prefixed}),
    )
    for name, kwargs in attempts:
        fn = getattr(ak, name, None)
        if not callable(fn):
            continue
        try:
            frame = _call_with_timeout(fn, **kwargs)
        except TypeError as e:
            logger.info(
                "akshare profile %s rejected kwargs for %s; skip: %s", name, code, e
            )
            continue
        except Exception as e:
            if _ak_interface_missing(e):
                logger.info("akshare profile %s missing on this AKShare; skip", name)
                continue
            logger.warning("akshare profile %s failed for %s: %s", name, code, e)
            continue
        rows = _as_records(frame)
        if rows:
            return rows
    return []


def _name_from_profile_rows(rows: list[dict], code: str) -> str:
    for row in rows:
        item = _field(row, ("item", "指标"))
        if item in {"股票简称", "名称", "A股简称"}:
            value = _field(row, ("value", "值"))
            if value and value not in {code, "股票代码"}:
                return value
        name = _field(row, ("股票简称", "A股简称", "名称"))
        if name and name not in {code, "股票代码"}:
            return name
    return ""


def _company_name(ak, code: str) -> str:
    """Best-effort 股票简称. Never invent a name; empty means code-only matching."""
    return _name_from_profile_rows(fetch_a_share_profile_rows(ak, code), code)


def _ticker_aliases(ak, code: str) -> tuple[str, ...]:
    return (code, *_name_aliases(_company_name(ak, code)))


def _blob_mentions(title: str, body: str, code: str, aliases: tuple[str, ...]) -> bool:
    blob = f"{title}\n{body}"
    if code and code in blob:
        return True
    return any(alias != code and alias in blob for alias in aliases if alias)


def _is_relevant_em_row(row: dict, code: str, aliases: tuple[str, ...] = ()) -> bool:
    """Keep East Money rows about this listing; keyword==code is not enough.

    ``stock_news_em`` tags every related-feed row with the queried code, and
    article bodies often repeat 相关股票. The title must mention the code or
    short name. A body-only hit counts only when it contains the six-digit
    code, not just the short name.
    """
    title = _field(row, _TITLE_KEYS)
    body = _field(row, _BODY_KEYS)
    etf_without_ticker = (
        "ETF" in title.upper()
        and code not in title
        and not any(alias != code and alias in title for alias in aliases)
    )
    if _blob_mentions(title, "", code, aliases):
        return not etf_without_ticker
    return bool(code and code in body)


def _mentions_ticker(item: NewsItem, code: str, aliases: tuple[str, ...] = ()) -> bool:
    return _blob_mentions(item.title, item.body, code, aliases)


def _keep_ticker_item(item: NewsItem, code: str, aliases: tuple[str, ...]) -> bool:
    if item.channel in _FILING_CHANNELS:
        return True
    if item.channel == "east_money":
        return _is_relevant_em_row(
            {"新闻标题": item.title, "新闻内容": item.body},
            code,
            aliases,
        )
    return _mentions_ticker(item, code, aliases)


def _row_to_item(
    row: dict,
    *,
    channel: str,
    default_source: str,
    category: str = "",
) -> NewsItem | None:
    title = _field(row, _TITLE_KEYS)
    if not title:
        return None
    pub_raw = None
    for name in _DATE_KEYS:
        if row.get(name) is not None:
            pub_raw = row.get(name)
            break
    filing_type = _field(row, _TYPE_KEYS)
    return NewsItem(
        title=title,
        body=_field(row, _BODY_KEYS),
        source=_field(row, _SOURCE_KEYS) or default_source,
        link=_field(row, _LINK_KEYS),
        pub_date=_iso_or_none(pub_raw),
        channel=channel,
        category=category or filing_type,
    )


def _filter_window(
    items: list[NewsItem],
    start_dt: datetime,
    end_dt: datetime,
) -> list[NewsItem]:
    kept: list[NewsItem] = []
    for item in items:
        if in_window(pub_datetime(item) or _parse_pub_dt(item.pub_date), start_dt, end_dt):
            kept.append(item)
    return kept


def _channel_items(name: str, fetcher) -> list[NewsItem]:
    try:
        return fetcher() or []
    except Exception as e:
        logger.warning("akshare channel %s failed: %s", name, e)
        return []


def _call_ak(ak, name: str, **kwargs):
    fn = getattr(ak, name, None)
    if not callable(fn):
        return None
    try:
        return _call_with_timeout(fn, **kwargs) if kwargs else _call_with_timeout(fn)
    except TypeError:
        return _call_with_timeout(fn)


def _fetch_east_money_news(
    ak, code: str, start_dt: datetime, end_dt: datetime, aliases: tuple[str, ...] = ()
) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        frame = _call_ak(ak, "stock_news_em", symbol=code)
    except Exception as e:
        logger.warning("akshare channel stock_news_em failed: %s", e)
        frame = None
    for row in _as_records(frame):
        if not _is_relevant_em_row(row, code, aliases):
            continue
        item = _row_to_item(row, channel="east_money", default_source="东方财富", category="company")
        if item:
            items.append(item)
    filtered = _filter_window(items, start_dt, end_dt)
    if filtered:
        return filtered
    try:
        frame = _call_ak(ak, "stock_gsrl_gsdt_em", symbol=code)
    except Exception as e:
        logger.warning("akshare channel stock_gsrl_gsdt_em failed: %s", e)
        return []
    fallback: list[NewsItem] = []
    for row in _as_records(frame):
        if not _is_relevant_em_row(row, code, aliases):
            continue
        item = _row_to_item(row, channel="east_money", default_source="公司动态", category="company")
        if item:
            fallback.append(item)
    return _filter_window(fallback, start_dt, end_dt)


def _fetch_filings(
    ak, code: str, start_date: str, end_date: str, start_dt: datetime, end_dt: datetime
) -> list[NewsItem]:
    fn = getattr(ak, "stock_zh_a_disclosure_report_cninfo", None)
    if not callable(fn):
        return []
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    # AKShare only accepts 沪深京/港股/三板/… . ``sse`` is not a market and AKTools
    # turns the resulting exception into HTTP 500.
    frame = None
    attempts = (
        {
            "symbol": code,
            "market": "沪深京",
            "keyword": "",
            "category": "",
            "start_date": start,
            "end_date": end,
        },
        {"symbol": code, "market": "沪深京", "start_date": start, "end_date": end},
    )
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            frame = _call_with_timeout(fn, **kwargs)
            break
        except TypeError as e:
            last_error = e
            continue
        except Exception as e:
            last_error = e
            if _ak_interface_missing(e):
                logger.info(
                    "akshare channel stock_zh_a_disclosure_report_cninfo missing; skip"
                )
                return []
            continue
    if frame is None:
        if last_error is not None:
            raise last_error
        return []
    items: list[NewsItem] = []
    for row in _as_records(frame):
        item = _row_to_item(row, channel="cninfo", default_source="巨潮资讯", category=_field(row, _TYPE_KEYS) or "filing")
        if item:
            items.append(item)
    return _filter_window(items, start_dt, end_dt)


def _fetch_cls_alerts(
    ak,
    start_dt: datetime,
    end_dt: datetime,
    code: str | None = None,
    aliases: tuple[str, ...] = (),
) -> list[NewsItem]:
    fn = getattr(ak, "stock_zh_a_alerts_cls", None)
    if not callable(fn):
        return []
    frame = None
    for kwargs in ({}, {"symbol": "全部"}):
        try:
            frame = _call_with_timeout(fn, **kwargs) if kwargs else _call_with_timeout(fn)
            break
        except TypeError:
            continue
        except Exception as e:
            if _ak_interface_missing(e):
                logger.info(
                    "akshare channel stock_zh_a_alerts_cls missing on this AKShare; skip"
                )
                return []
            logger.warning("akshare channel stock_zh_a_alerts_cls failed: %s", e)
            return []
    items: list[NewsItem] = []
    for row in _as_records(frame):
        item = _row_to_item(row, channel="cls_alerts", default_source="财联社电报", category="flash")
        if item:
            items.append(item)
    items = _filter_window(items, start_dt, end_dt)
    if code:
        items = [item for item in items if _mentions_ticker(item, code, aliases)]
    return items


def _fetch_cctv(ak, curr_date: str, start_dt: datetime, end_dt: datetime) -> list[NewsItem]:
    yyyymmdd = curr_date.replace("-", "")
    frame = _call_ak(ak, "news_cctv", date=yyyymmdd)
    items: list[NewsItem] = []
    for row in _as_records(frame):
        row.setdefault("date", curr_date)
        item = _row_to_item(row, channel="cctv", default_source="新闻联播", category="policy")
        if item:
            items.append(item)
    return _filter_window(items, start_dt, end_dt)


def _fetch_named_flash(ak, name: str, kwargs: dict, label: str, channel: str, start_dt, end_dt) -> list[NewsItem]:
    try:
        frame = _call_ak(ak, name, **kwargs)
    except Exception as e:
        logger.warning("akshare channel %s failed: %s", name, e)
        return []
    items: list[NewsItem] = []
    for row in _as_records(frame):
        item = _row_to_item(row, channel=channel, default_source=label, category="flash")
        if item:
            items.append(item)
    return _filter_window(items, start_dt, end_dt)


def _telegraph_ttl(channel: str, as_of: str) -> int | None:
    """Shorter live TTL for wires; historical as-of stays immutable in news_store."""
    if channel not in TELEGRAPH_CHANNELS or not is_live_as_of(as_of):
        return None
    raw = get_config().get("news_telegraph_ttl_seconds", DEFAULT_TELEGRAPH_TTL_SECONDS)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = DEFAULT_TELEGRAPH_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_TELEGRAPH_TTL_SECONDS


def _cached_channel(
    key: str,
    as_of: str,
    channel: str,
    loader: Callable[[], list[NewsItem]],
) -> list[NewsItem]:
    return fetch_cached(
        key,
        as_of,
        channel,
        loader,
        ttl_seconds=_telegraph_ttl(channel, as_of),
    )


def _load_state_media_items(
    cache_key: str,
    as_of: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[NewsItem]:
    """Cached official headlines. One dead page does not drop the other outlets."""
    items: list[NewsItem] = []
    for channel in STATE_MEDIA_CHANNELS:
        items.extend(
            _cached_channel(
                cache_key,
                as_of,
                channel,
                lambda ch=channel: fetch_state_media_channel(ch, start_dt, end_dt),
            )
        )
    return items


def _load_wire_items(
    ak,
    cache_key: str,
    as_of: str,
    start_dt: datetime,
    end_dt: datetime,
    channels: frozenset[str] | None,
) -> list[NewsItem]:
    """Cached market wires. ``channels`` limits which specs are read."""
    items: list[NewsItem] = []
    for channel, name, kwargs, label in _WIRE_SPECS:
        if channels is not None and channel not in channels:
            continue
        items.extend(
            _cached_channel(
                cache_key,
                as_of,
                channel,
                lambda n=name, kw=kwargs, lb=label, ch=channel: _channel_items(
                    n,
                    lambda: _fetch_named_flash(ak, n, kw, lb, ch, start_dt, end_dt),
                ),
            )
        )
    return items


def collect_ticker_news_items(
    code: str, start_date: str, end_date: str
) -> list[NewsItem]:
    """Company news, filings, CLS alerts, ticker wires, and state-media mentions."""
    ak = _load_akshare()
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    aliases = _ticker_aliases(ak, code)
    company = _cached_channel(
        code,
        end_date,
        "east_money",
        lambda: _channel_items(
            "stock_news_em",
            lambda: _fetch_east_money_news(ak, code, start_dt, end_dt, aliases),
        ),
    )
    filings = _cached_channel(
        code,
        end_date,
        "cninfo",
        lambda: _channel_items(
            "cninfo_filings",
            lambda: _fetch_filings(ak, code, start_date, end_date, start_dt, end_dt),
        ),
    )
    flashes = _cached_channel(
        code,
        end_date,
        "cls_alerts",
        lambda: _channel_items(
            "cls_alerts",
            lambda: _fetch_cls_alerts(ak, start_dt, end_dt, code=code, aliases=aliases),
        ),
    )
    wires = _load_wire_items(ak, code, end_date, start_dt, end_dt, _TICKER_WIRE_CHANNELS)
    state_media = _load_state_media_items(code, end_date, start_dt, end_dt)
    kept = [
        item
        for item in (company + filings + flashes + wires + state_media)
        if _keep_ticker_item(item, code, aliases)
    ]
    return kept


def collect_global_news_items(
    curr_date: str, look_back_days: int
) -> list[NewsItem]:
    """CCTV, state media, domestic newswires, and CLS alerts for the as-of date."""
    ak = _load_akshare()
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt
    flash_start = end_dt - timedelta(days=int(look_back_days))
    cctv = _cached_channel(
        GLOBAL_KEY,
        curr_date,
        "cctv",
        lambda: _channel_items(
            "news_cctv", lambda: _fetch_cctv(ak, curr_date, start_dt, end_dt)
        ),
    )
    flash_items = _load_wire_items(ak, GLOBAL_KEY, curr_date, flash_start, end_dt, None)
    alerts = _cached_channel(
        GLOBAL_KEY,
        curr_date,
        "cls_alerts",
        lambda: _channel_items(
            "cls_alerts", lambda: _fetch_cls_alerts(ak, flash_start, end_dt)
        ),
    )
    state_media = _load_state_media_items(GLOBAL_KEY, curr_date, flash_start, end_dt)
    return cctv + state_media + flash_items + alerts


def _split_ticker_sections(
    items: list[NewsItem],
) -> tuple[list[NewsItem], list[NewsItem], list[NewsItem], list[NewsItem]]:
    company: list[NewsItem] = []
    filings: list[NewsItem] = []
    flashes: list[NewsItem] = []
    state_media: list[NewsItem] = []
    for item in items:
        if item.channel == "cninfo":
            filings.append(item)
        elif item.channel in {"cls_alerts", "ths_flash", "futu_flash"}:
            flashes.append(item)
        elif item.channel in _STATE_MEDIA_CHANNELS:
            state_media.append(item)
        else:
            company.append(item)
    return company, filings, flashes, state_media


def _keep_global_item(item: NewsItem, curr_date: str) -> bool:
    """CCTV stays pinned to the as-of day; wires may fill the lookback window."""
    if item.channel != "cctv":
        return True
    pub = pub_datetime(item)
    if pub is not None:
        return pub.strftime("%Y-%m-%d") == curr_date
    return (item.pub_date or "").startswith(curr_date)


def _section(title: str, items: list[NewsItem], limit: int) -> str:
    if not items:
        return ""
    body = render_items(items, limit)
    if not body:
        return ""
    return f"## {title}\n\n{body}"


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Company news + filings + related flashes for an A-share ticker."""
    code = a_share_code(ticker)
    if code is None:
        raise NoMarketDataError(
            ticker, ticker, "not a China A-share symbol; akshare news is A-share only"
        )
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    limit = int(get_config().get("news_article_limit", 20))
    fetched = collect_ticker_news_items(code, start_date, end_date)
    upsert_items(code, fetched)
    aliases = _ticker_aliases(_load_akshare(), code)
    items = [
        item
        for item in query_items(code, start_dt, end_dt)
        if _keep_ticker_item(item, code, aliases)
    ]
    company, filings, flashes, state_media = _split_ticker_sections(items)
    company = dedupe_items(company)
    filings = dedupe_items(filings)
    flashes = dedupe_items(flashes)
    state_media = dedupe_items(state_media)
    sections = [
        _section(f"Company news for {code}", company, limit),
        _section(f"Exchange filings for {code}", filings, limit),
        _section(f"Company-related flashes for {code}", flashes, limit),
        _section(f"State media mentions for {code}", state_media, limit),
    ]
    body = "\n\n".join(part for part in sections if part)
    if not body:
        raise NoMarketDataError(
            ticker, code, "no A-share news or filings in the requested window"
        )
    return (
        f"## {ticker} (A-share {code}) news, from {start_date} to {end_date}:\n\n{body}"
    )


def get_global_news(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """Domestic policy plus every configured China newswire for the as-of date."""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    flash_start = end_dt - timedelta(days=int(look_back_days))
    cap = int(limit)
    fetched = collect_global_news_items(curr_date, int(look_back_days))
    upsert_items(GLOBAL_KEY, fetched)
    stored = query_items(GLOBAL_KEY, flash_start, end_dt)
    merged = [item for item in stored if _keep_global_item(item, curr_date)]
    official = [
        item
        for item in merged
        if item.channel == "cctv" or item.channel in _STATE_MEDIA_CHANNELS
    ]
    official_keys = {(item.title, item.link) for item in official}
    policy = official + [
        item
        for item in merged
        if is_policy_item(item) and (item.title, item.link) not in official_keys
    ]
    policy_keys = {(item.title, item.link) for item in policy}
    other = [item for item in merged if (item.title, item.link) not in policy_keys]

    sections = [
        _section(f"CCTV, state media, and regulator policy ({curr_date})", policy, cap),
        _section(
            "Domestic newswires (CLS / East Money / Sina / Tonghuashun / Futu)",
            other,
            cap,
        ),
    ]
    body = "\n\n".join(part for part in sections if part)
    if not body:
        raise NoMarketDataError(
            "global",
            "global",
            "no China policy or newswire items from akshare",
        )
    return f"## China policy and domestic news, as of {curr_date}:\n\n{body}"
