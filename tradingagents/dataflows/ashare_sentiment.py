"""A-share retail sentiment: Xueqiu, East Money Guba/千股千评, e互动.

Used by Sentiment Analyst for mainland listings. StockTwits/Reddit stay on
the US/crypto path. Failures degrade to an explicit unavailable placeholder
so the LLM does not invent posts.

Dated rows go through ``date_window.in_window``. Channel payloads are cached
in ``news_store`` under the six-digit A-share code.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import requests

from .akshare_news import (
    AkshareNotConfiguredError,
    _ak_interface_missing,
    _as_records,
    _call_with_timeout,
    _field,
    _load_akshare,
    _parse_pub_dt,
)
from .date_window import in_window
from .news_items import NewsItem, dedupe_items, render_items
from .news_store import fetch_cached
from .symbol_utils import a_share_code, a_share_prefixed_symbol

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
_CODE_KEYS = ("代码", "股票代码", "证券代码", "code", "symbol")
_XUEQIU_URL = "https://xueqiu.com/query/v1/symbol/search/status.json"
_GUBA_POSTS_URL = "https://gbapi.eastmoney.com/stkpost/api/v1/post/listbystock"
_UA = "Mozilla/5.0 (compatible; TradingAgents/0.4; +https://github.com/TauricResearch/TradingAgents)"
_GUBA_POST_CAP = 30
_TAG_RE = re.compile(r"<[^>]+>")
_MD_RE = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$")
# Phrase hits only. Single characters false-trigger (牛 in 牛奶). Negation is
# the one or two characters immediately before the phrase.
_BULL_WORDS = ("看多", "利好", "涨停", "加仓", "抄底", "主升", "突破")
_BEAR_WORDS = ("看空", "利空", "跌停", "减仓", "出货", "破位", "跳水", "暴跌")
_NEGATION = ("不", "别", "未", "没", "勿")

_UNAVAILABLE = (
    "<unavailable: no A-share sentiment source returned posts in the window. "
    "Do not invent Xueqiu or Guba content.>"
)

_XUEQIU_COOKIE_ENV = ("XUEQIU_COOKIE", "TRADINGAGENTS_XUEQIU_COOKIE")
_XUEQIU_REJECTED = (400, 401, 403)


def _xueqiu_cookie() -> str:
    for name in _XUEQIU_COOKIE_ENV:
        raw = os.getenv(name)
        if raw and raw.strip():
            return raw.strip()
    return ""


def _xq_a_token(session: requests.Session) -> str:
    cookies = getattr(session, "cookies", None)
    getter = getattr(cookies, "get", None) if cookies is not None else None
    if callable(getter):
        token = getter("xq_a_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
    headers = getattr(session, "headers", None) or {}
    header = headers.get("Cookie") if hasattr(headers, "get") else ""
    if not isinstance(header, str):
        return ""
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == "xq_a_token" and value.strip():
            return value.strip()
    return ""


def _xueqiu_session() -> requests.Session:
    """Browser-like session. Cookie from env; otherwise warm the homepage once."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": _UA,
            "Referer": "https://xueqiu.com/",
            "Origin": "https://xueqiu.com",
            "Accept": "application/json, text/plain, */*",
        }
    )
    cookie = _xueqiu_cookie()
    if cookie:
        session.headers["Cookie"] = cookie
        return session
    try:
        session.get("https://xueqiu.com/", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logger.warning("Xueqiu homepage warm-up failed: %s", e)
    return session


def _xueqiu_symbol(code: str) -> str:
    if code.startswith(("4", "8")) or code.startswith("920"):
        return f"BJ{code}"
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


def _in_range(pub: datetime | None, start_dt: datetime, end_dt: datetime) -> bool:
    return in_window(pub, start_dt, end_dt)


def _fetch_xueqiu(code: str, start_dt: datetime, end_dt: datetime) -> list[NewsItem]:
    symbol = _xueqiu_symbol(code)
    session = _xueqiu_session()
    if not _xq_a_token(session):
        try:
            session.get(f"https://xueqiu.com/S/{symbol}", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            logger.warning("Xueqiu symbol page warm-up failed for %s: %s", symbol, e)
    params = {
        "count": 30,
        "comment": 0,
        "symbol": symbol,
        "hl": 0,
        "source": "all",
        "sort": "time",
        "page": 1,
    }
    token = _xq_a_token(session)
    if token:
        params["xq_a_token"] = token
    try:
        response = session.get(
            _XUEQIU_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code in _XUEQIU_REJECTED:
            logger.warning(
                "Xueqiu rejected %s with HTTP %s; set XUEQIU_COOKIE or "
                "TRADINGAGENTS_XUEQIU_COOKIE from a logged-in browser session",
                symbol,
                response.status_code,
            )
            return []
        response.raise_for_status()
        raw = getattr(response, "text", None)
        if isinstance(raw, str) and (not raw.strip() or raw.lstrip()[:1] not in "{["):
            logger.warning(
                "Xueqiu sentiment fetch failed for %s: non-JSON body (status %s). "
                "Set XUEQIU_COOKIE or TRADINGAGENTS_XUEQIU_COOKIE from a logged-in "
                "browser session",
                symbol,
                response.status_code,
            )
            return []
        payload = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Xueqiu sentiment fetch failed for %s: %s", symbol, e)
        return []

    rows = payload.get("list") or payload.get("statuses") or []
    items: list[NewsItem] = []
    if not isinstance(rows, list):
        return []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("description") or row.get("text") or "").strip()
        if not title:
            continue
        created = row.get("created_at") or row.get("timeBefore") or row.get("createdAt")
        pub = None
        if isinstance(created, (int, float)):
            # Xueqiu often uses epoch milliseconds.
            ts = created / 1000 if created > 10_000_000_000 else created
            try:
                pub = datetime.fromtimestamp(ts)
            except (OSError, OverflowError, ValueError):
                pub = None
        else:
            pub = _parse_pub_dt(created)
        if not _in_range(pub, start_dt, end_dt):
            continue
        items.append(
            NewsItem(
                title=title[:240],
                body=str(row.get("text") or row.get("description") or "")[:500],
                source="雪球",
                link=str(row.get("target") or row.get("url") or ""),
                pub_date=pub.isoformat(sep=" ") if pub else None,
                channel="xueqiu",
                category="sentiment",
            )
        )
    return items


def _plain(text: str) -> str:
    return _TAG_RE.sub("", text).replace("&nbsp;", " ").strip()


def _guba_row_list(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("re", "list", "posts", "data", "result"):
        inner = payload.get(key)
        if isinstance(inner, list):
            return [row for row in inner if isinstance(row, dict)]
        if isinstance(inner, dict):
            nested = _guba_row_list(inner)
            if nested:
                return nested
    return []


def _guba_stamp(raw: object, end_dt: datetime) -> datetime | None:
    pub = _parse_pub_dt(raw)
    if pub is not None:
        return pub
    match = _MD_RE.match(str(raw or "").strip())
    if match is None:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    hour = int(match.group(3) or 0)
    minute = int(match.group(4) or 0)
    try:
        pub = datetime(end_dt.year, month, day, hour, minute)
    except ValueError:
        return None
    if pub.date() > end_dt.date():
        try:
            pub = pub.replace(year=end_dt.year - 1)
        except ValueError:
            return None
    return pub


def _guba_belongs(row: dict, code: str) -> bool:
    raw = str(row.get("stockbar_code") or row.get("code") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:] == code
    return True


def _guba_rows_to_items(
    rows: list[dict], code: str, start_dt: datetime, end_dt: datetime
) -> list[NewsItem]:
    items: list[NewsItem] = []
    for row in rows:
        if not _guba_belongs(row, code):
            continue
        title = _plain(str(row.get("post_title") or row.get("title") or ""))
        body = _plain(str(row.get("post_content") or row.get("content") or ""))
        if not title:
            title = body[:80]
        if not title:
            continue
        if body == title:
            body = ""
        reads = row.get("post_click_count", row.get("read_count"))
        replies = row.get("post_comment_count", row.get("comment_count"))
        extra = []
        if reads not in (None, ""):
            extra.append(f"阅读 {reads}")
        if replies not in (None, ""):
            extra.append(f"评论 {replies}")
        if extra:
            body = " · ".join(extra) + (f"\n{body}" if body else "")
        created = (
            row.get("post_publish_time")
            or row.get("post_time")
            or row.get("publish_time")
            or row.get("post_display_time")
        )
        pub = _guba_stamp(created, end_dt)
        if not _in_range(pub, start_dt, end_dt):
            continue
        post_id = str(row.get("post_id") or row.get("id") or "").strip()
        link = (
            f"https://guba.eastmoney.com/news,{code},{post_id}.html" if post_id else ""
        )
        items.append(
            NewsItem(
                title=title[:240],
                body=body[:500],
                source="东方财富股吧",
                link=link,
                pub_date=pub.isoformat(sep=" ") if pub else None,
                channel="guba_posts",
                category="sentiment",
            )
        )
        if len(items) >= _GUBA_POST_CAP:
            break
    return items


def _guba_json_rows(code: str) -> list[dict]:
    try:
        response = requests.get(
            _GUBA_POSTS_URL,
            params={
                "stockcode": code,
                "pageindex": 1,
                "pagesize": _GUBA_POST_CAP,
                "sort": "posttime",
                "source": "web",
            },
            headers={
                "User-Agent": _UA,
                "Referer": f"https://guba.eastmoney.com/list,{code}.html",
                "Accept": "application/json, text/plain, */*",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("East Money Guba post list failed for %s: %s", code, e)
        return []
    return _guba_row_list(payload)


def _guba_html_rows(code: str) -> list[dict]:
    try:
        response = requests.get(
            f"https://guba.eastmoney.com/list,{code}.html",
            headers={
                "User-Agent": _UA,
                "Referer": "https://guba.eastmoney.com/",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        text = response.text
    except requests.RequestException as e:
        logger.warning("East Money Guba page failed for %s: %s", code, e)
        return []
    marker = "article_list"
    idx = text.find(marker)
    if idx < 0:
        logger.warning("East Money Guba page for %s has no article_list", code)
        return []
    start = text.find("=", idx)
    if start < 0:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start + 1 :].lstrip())
    except json.JSONDecodeError as e:
        logger.warning("East Money Guba article_list for %s did not parse: %s", code, e)
        return []
    return _guba_row_list(payload)


def _fetch_guba_posts(code: str, start_dt: datetime, end_dt: datetime) -> list[NewsItem]:
    """Public Guba threads. No Xueqiu cookie. JSON list, then the list page."""
    rows = _guba_json_rows(code)
    if not rows:
        rows = _guba_html_rows(code)
    return _guba_rows_to_items(rows, code, start_dt, end_dt)


def _phrase_hit(text: str, words: tuple[str, ...]) -> bool:
    for word in words:
        start = 0
        while True:
            idx = text.find(word, start)
            if idx < 0:
                break
            prefix = text[max(0, idx - 2) : idx]
            if not any(mark in prefix for mark in _NEGATION):
                return True
            start = idx + len(word)
    return False


def _post_side(text: str) -> str:
    bull = _phrase_hit(text, _BULL_WORDS)
    bear = _phrase_hit(text, _BEAR_WORDS)
    if bull and bear:
        return "mixed"
    if bull:
        return "bull"
    if bear:
        return "bear"
    return "quiet"


def _guba_stance_line(items: list[NewsItem]) -> str:
    """Keyword tally of the posts below. Not a poll and not a Xueqiu read."""
    counts = {"bull": 0, "bear": 0, "mixed": 0, "quiet": 0}
    for item in items:
        counts[_post_side(f"{item.title}\n{item.body}")] += 1
    return (
        "股吧帖子关键词计数（不是投票、不是雪球）："
        f"看多 {counts['bull']}，看空 {counts['bear']}，"
        f"多空都出现 {counts['mixed']}，未命中 {counts['quiet']}。"
        "只根据本节帖子标题和正文，不要用人气榜或千股千评代替这个比例。"
    )


def _row_listing_code(row: dict) -> str | None:
    raw = _field(row, _CODE_KEYS)
    if not raw:
        return None
    parsed = a_share_code(raw)
    if parsed:
        return parsed
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) == 6:
        return digits
    return None


def _keep_sentiment_row(row: dict, code: str, *, market_wide: bool) -> bool:
    """Drop other listings. Market-wide tables must name this six-digit code."""
    row_code = _row_listing_code(row)
    if row_code is not None:
        return row_code == code
    return not market_wide


def _em_hot_symbol(code: str) -> str:
    """East Money popularity APIs want ``SH601061``, not ``sh601061`` or ``601061.SH``."""
    return a_share_prefixed_symbol(code).upper()


def _call_sentiment_frame(ak, name: str, kwargs_list: tuple[dict, ...], code: str):
    """Call one AKShare sentiment function with its documented kwargs only.

    AKTools turns an unexpected keyword into HTTP 500, not ``TypeError``.
    Do not invent a no-arg retry here; ``stock_comment_em`` is the one call
    that is intentionally parameterless, and that is passed in as ``{}``.
    """
    fn = getattr(ak, name, None)
    if not callable(fn):
        return None
    saw_type_error = False
    for kwargs in kwargs_list:
        if not kwargs and saw_type_error:
            logger.info(
                "akshare sentiment channel %s type error for %s; skip empty retry",
                name,
                code,
            )
            continue
        try:
            if kwargs:
                return _call_with_timeout(fn, **kwargs)
            return _call_with_timeout(fn)
        except TypeError as e:
            saw_type_error = True
            logger.info(
                "akshare sentiment channel %s rejected kwargs for %s; skip: %s",
                name,
                code,
                e,
            )
            continue
        except Exception as e:
            if _ak_interface_missing(e):
                logger.info(
                    "akshare sentiment channel %s missing on this AKShare; skip", name
                )
                return None
            logger.warning(
                "akshare sentiment channel %s failed for %s: %s", name, code, e
            )
            return None
    return None


def _fetch_ak_sentiment(
    ak,
    attempts: tuple[tuple[str, tuple[dict, ...]], ...],
    code: str,
    start_dt,
    end_dt,
    source: str,
    channel: str,
    *,
    market_wide: bool = False,
) -> list[NewsItem]:
    for name, kwargs_list in attempts:
        frame = _call_sentiment_frame(ak, name, kwargs_list, code)
        if frame is None:
            continue
        items: list[NewsItem] = []
        for row in _as_records(frame):
            if not _keep_sentiment_row(row, code, market_wide=market_wide):
                continue
            title = _field(row, ("标题", "title", "内容", "评语", "text", "帖子"))
            if not title:
                # Snapshot tables (千股千评) — render the row as key=value.
                parts = [
                    f"{k}={v}"
                    for k, v in row.items()
                    if v is not None and str(v).strip() and str(v).lower() != "nan"
                ]
                title = "; ".join(parts[:8])
            if not title:
                continue
            pub = None
            for key in ("发布时间", "时间", "交易日", "date", "pub_date"):
                if row.get(key) is not None:
                    pub = _parse_pub_dt(row.get(key))
                    break
            if pub is not None and not _in_range(pub, start_dt, end_dt):
                continue
            if pub is None and not _in_range(None, start_dt, end_dt):
                continue
            items.append(
                NewsItem(
                    title=title[:240],
                    body=_field(row, ("内容", "摘要", "content", "text")),
                    source=source,
                    link=_field(row, ("链接", "link", "url")),
                    pub_date=pub.isoformat(sep=" ") if pub else None,
                    channel=channel,
                    category="sentiment",
                )
            )
        if items:
            return items
    return []


def fetch_a_share_sentiment(ticker: str, start_date: str, end_date: str) -> str:
    """Return markdown for A-share retail sentiment, or an unavailable sentinel."""
    code = a_share_code(ticker)
    if code is None:
        return (
            "<unavailable: not a China A-share symbol. "
            "Do not invent Xueqiu or Guba content.>"
        )
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    xueqiu = fetch_cached(
        code,
        end_date,
        "xueqiu",
        lambda: _fetch_xueqiu(code, start_dt, end_dt),
    )
    guba_posts = fetch_cached(
        code,
        end_date,
        "guba_posts",
        lambda: _fetch_guba_posts(code, start_dt, end_dt),
    )

    guba: list[NewsItem] = []
    heat: list[NewsItem] = []
    irm: list[NewsItem] = []
    try:
        ak = _load_akshare()
    except AkshareNotConfiguredError:
        logger.warning("akshare extra missing; A-share sentiment is Xueqiu-only")
    else:
        hot_symbol = _em_hot_symbol(code)
        guba = fetch_cached(
            code,
            end_date,
            "guba",
            lambda: _fetch_ak_sentiment(
                ak,
                (
                    ("stock_hot_rank_detail_em", ({"symbol": hot_symbol},)),
                    ("stock_hot_keyword_em", ({"symbol": hot_symbol},)),
                ),
                code,
                start_dt,
                end_dt,
                "东方财富人气榜",
                "guba",
            ),
        )
        heat = fetch_cached(
            code,
            end_date,
            "comment_em_code",
            lambda: _fetch_ak_sentiment(
                ak,
                (("stock_comment_em", ({},)),),
                code,
                start_dt,
                end_dt,
                "东方财富千股千评",
                "comment_em",
                market_wide=True,
            )
            + _fetch_ak_sentiment(
                ak,
                (
                    ("stock_comment_detail_scrd_focus_em", ({"symbol": code},)),
                    ("stock_comment_detail_zhpj_lspf_em", ({"symbol": code},)),
                    ("stock_comment_detail_zlkp_jgcyd_em", ({"symbol": code},)),
                ),
                code,
                start_dt,
                end_dt,
                "东方财富千股千评",
                "comment_em",
            ),
        )
        irm = fetch_cached(
            code,
            end_date,
            "sseinfo",
            lambda: _fetch_ak_sentiment(
                ak,
                (("stock_sns_sseinfo", ({"symbol": code}, {"stock": code})),),
                code,
                start_dt,
                end_dt,
                "上证e互动",
                "sseinfo",
            ),
        )

    sections: list[str] = []
    for heading, rows in (
        ("Xueqiu", xueqiu),
        ("East Money Guba posts", guba_posts),
        ("East Money popularity", guba),
        ("East Money heat / 千股千评", heat),
        ("SSE e-interaction", irm),
    ):
        rows = dedupe_items(rows)
        shown = rows[:20]
        body = render_items(shown, 20)
        if heading == "East Money Guba posts" and shown:
            body = _guba_stance_line(shown) + "\n\n" + body
        if body:
            sections.append(f"## {heading}\n\n{body}")
    if not sections:
        return _UNAVAILABLE
    notes: list[str] = []
    if not xueqiu and not _xueqiu_cookie():
        if guba_posts:
            notes.append(
                "Xueqiu cookie unset (XUEQIU_COOKIE / TRADINGAGENTS_XUEQIU_COOKIE); "
                "do not invent Xueqiu posts. Retail post text and the bull/bear "
                "keyword count are from East Money Guba, not the popularity rank "
                "or 千股千评."
            )
        else:
            notes.append(
                "Xueqiu cookie unset (XUEQIU_COOKIE / TRADINGAGENTS_XUEQIU_COOKIE); "
                "do not invent Xueqiu posts."
            )
    header = (
        f"## {ticker} (A-share {code}) retail sentiment, "
        f"{start_date} to {end_date}:\n\n"
    )
    if notes:
        header += "Note: " + " ".join(notes) + "\n\n"
    return header + "\n\n".join(sections)
