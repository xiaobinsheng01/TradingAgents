"""Official China state-media and ministry headlines for domestic news.

AKShare ``news_cctv`` is still the as-of-day 新闻联播 transcript. This module
also reads the CNTV 新闻联播 column directly, so a dead AKTools call does not
drop the broadcast. Other outlets:

- 人民日报 (people.com.cn)
- 新华社财经 (news.cn/fortune)
- 中国经济网，经济日报社 (ce.cn rolling news and finance)
- 中新网财经 (chinanews.com.cn RSS)
- 央视新闻 (news.cctv.com list)
- 中国政府网要闻
- 中国人民银行新闻、财政部财政新闻、国家发改委新闻发布、国家统计局数据发布

Each page is its own channel. A timeout, HTTP error, or parse failure logs
and returns an empty list for that channel. Items carry a civil publish date
and are trimmed with ``date_window.in_window``. Callers cache and warehouse
them; this module does not write files.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests

from .date_window import in_window
from .news_items import NewsItem, pub_datetime

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

STATE_MEDIA_CHANNELS: tuple[str, ...] = (
    "people_daily",
    "xinhua_finance",
    "economic_daily",
    "chinanews_finance",
    "cctv_news",
    "gov_cn",
    "xwlb",
    "pbc",
    "mof",
    "ndrc",
    "stats_gov",
)

_PEOPLE_PAGES = (
    "http://www.people.com.cn/",
    "http://finance.people.com.cn/",
)
_XINHUA_PAGE = "https://www.news.cn/fortune/index.htm"
_ECONOMIC_PAGES = (
    "http://www.ce.cn/xwzx/gnsz/gdxw/",
    "http://finance.ce.cn/",
)
_CHINANEWS_RSS = "https://www.chinanews.com.cn/rss/finance.xml"
_CCTV_JSONP = "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/news_1.jsonp"
_GOV_JSON = "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json"
_XWLB_API = (
    "https://api.cntv.cn/NewVideo/getVideoListByColumn"
    "?id=TOPC1451528971114112&n=40&sort=desc&p=1&mode=0&serviceId=tvcctv"
)
_PBC_PAGE = "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html"
_MOF_PAGE = "https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/index.htm"
_NDRC_PAGE = "https://www.ndrc.gov.cn/xwdt/xwfb/"
_STATS_PAGE = "https://www.stats.gov.cn/sj/zxfb/index.html"
_PBC_RE = re.compile(
    r'href="(/goutongjiaoliu/113456/113469/(20\d{2})(\d{2})(\d{2})[^"]+/index\.html)"'
    r'[^>]*>\s*([^<]{4,160})',
    re.IGNORECASE,
)
_XWLB_HEADLINE_RE = re.compile(r"\d+\.\s*")

_TAG_RE = re.compile(r"<[^>]+>")
_PEOPLE_RE = re.compile(
    r'href="(https?://[^"]+/n1/(\d{4})/(\d{2})(\d{2})/[^"]+\.html)"[^>]*>\s*([^<]{4,160})',
    re.IGNORECASE,
)
_XINHUA_RE = re.compile(
    r'href="(/fortune/(\d{4})(\d{2})(\d{2})/[^"]+/c\.html)"[^>]*>\s*([^<]{4,160})',
    re.IGNORECASE,
)
_CE_HREF_RE = re.compile(
    r'href="([^"]+)"[^>]*>\s*([^<]{4,160})',
    re.IGNORECASE,
)
_CE_DATE_RE = re.compile(r"t(20\d{2})(\d{2})(\d{2})_")


def _plain(text: str) -> str:
    cleaned = _TAG_RE.sub(" ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def _ymd(year: str, month: str, day: str) -> str | None:
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def _civil_stamp(raw: str) -> str | None:
    """Publisher clock time, without shifting China offsets to UTC."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is not None:
        return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    for fmt, size in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
        ("%Y%m%d", 8),
    ):
        snippet = text[:size] if len(text) >= size else text
        try:
            return datetime.strptime(snippet, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _item(
    *,
    title: str,
    link: str,
    source: str,
    channel: str,
    pub_date: str | None,
    body: str = "",
) -> NewsItem | None:
    title = _plain(title)
    if len(title) < 4 or pub_date is None:
        return None
    return NewsItem(
        title=title[:240],
        body=_plain(body)[:500],
        source=source,
        link=link.strip(),
        pub_date=pub_date,
        channel=channel,
        category="policy",
    )


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for item in items:
        key = f"{item.link}|{item.title}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _in_window(items: list[NewsItem], start_dt: datetime, end_dt: datetime) -> list[NewsItem]:
    return [
        item
        for item in items
        if in_window(pub_datetime(item), start_dt, end_dt)
    ]


def _http_text(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": _UA, "Accept": "*/*"},
        )
    except requests.RequestException as e:
        raise RuntimeError(f"state media HTTP failed for {url}: {e}") from e
    if response.status_code >= 400:
        raise RuntimeError(f"state media HTTP {response.status_code} for {url}")
    raw = response.content
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def _parse_people(text: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for link, year, month, day, title in _PEOPLE_RE.findall(text):
        item = _item(
            title=title,
            link=link,
            source="人民日报",
            channel="people_daily",
            pub_date=_ymd(year, month, day),
        )
        if item:
            items.append(item)
    return items


def _parse_xinhua(text: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for path, year, month, day, title in _XINHUA_RE.findall(text):
        item = _item(
            title=title,
            link=urljoin("https://www.news.cn", path),
            source="新华社财经",
            channel="xinhua_finance",
            pub_date=_ymd(year, month, day),
        )
        if item:
            items.append(item)
    return items


def _parse_economic(text: str, page_url: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for href, title in _CE_HREF_RE.findall(text):
        matched = _CE_DATE_RE.search(href)
        if matched is None:
            continue
        pub = _ymd(matched.group(1), matched.group(2), matched.group(3))
        item = _item(
            title=title,
            link=urljoin(page_url, href),
            source="中国经济网",
            channel="economic_daily",
            pub_date=pub,
        )
        if item:
            items.append(item)
    return items


def _parse_chinanews(text: str) -> list[NewsItem]:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise RuntimeError(f"中新网财经 RSS parse failed: {e}") from e
    items: list[NewsItem] = []
    for node in root.iter("item"):
        item = _item(
            title=node.findtext("title") or "",
            link=node.findtext("link") or "",
            source="中新网财经",
            channel="chinanews_finance",
            pub_date=_civil_stamp(node.findtext("pubDate") or ""),
            body=node.findtext("description") or "",
        )
        if item:
            items.append(item)
    return items


def _parse_cctv_news(text: str) -> list[NewsItem]:
    payload = text.strip()
    if payload.startswith("news("):
        payload = payload[len("news(") :]
    if payload.endswith(");"):
        payload = payload[:-2]
    elif payload.endswith(")"):
        payload = payload[:-1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"央视新闻 JSONP parse failed: {e}") from e
    rows = []
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("list"), list):
            rows = inner["list"]
    items: list[NewsItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _item(
            title=str(row.get("title") or ""),
            link=str(row.get("url") or ""),
            source="央视新闻",
            channel="cctv_news",
            pub_date=_civil_stamp(str(row.get("focus_date") or "")),
            body=str(row.get("brief") or ""),
        )
        if item:
            items.append(item)
    return items


def _parse_gov(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"中国政府网要闻 JSON parse failed: {e}") from e
    if not isinstance(data, list):
        raise RuntimeError("中国政府网要闻 JSON was not a list")
    items: list[NewsItem] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        item = _item(
            title=str(row.get("TITLE") or ""),
            link=str(row.get("URL") or ""),
            source="中国政府网",
            channel="gov_cn",
            pub_date=_civil_stamp(str(row.get("DOCRELPUBTIME") or "")),
        )
        if item:
            items.append(item)
    return items


def _xwlb_headlines(brief: str) -> list[str]:
    parts = _XWLB_HEADLINE_RE.split(brief or "")
    headlines: list[str] = []
    for part in parts:
        line = _plain(part).strip(" ；;。")
        if len(line) < 4 or line.startswith("本期节目"):
            continue
        headlines.append(line)
    return headlines


def _parse_xwlb(text: str) -> list[NewsItem]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"新闻联播 JSON parse failed: {e}") from e
    rows = []
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("list"), list):
            rows = inner["list"]
    if not isinstance(rows, list):
        raise RuntimeError("新闻联播 JSON had no episode list")
    items: list[NewsItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pub = _civil_stamp(str(row.get("time") or ""))
        link = str(row.get("url") or "")
        headlines = _xwlb_headlines(str(row.get("brief") or ""))
        if not headlines:
            headlines = [_plain(str(row.get("title") or ""))]
        for headline in headlines:
            item = _item(
                title=headline,
                link=link,
                source="新闻联播",
                channel="xwlb",
                pub_date=pub,
            )
            if item:
                items.append(item)
    return items


def _parse_tdated_links(
    text: str,
    page_url: str,
    *,
    source: str,
    channel: str,
) -> list[NewsItem]:
    items: list[NewsItem] = []
    for href, title in _CE_HREF_RE.findall(text):
        if href.startswith(("javascript:", "#")):
            continue
        matched = _CE_DATE_RE.search(href)
        if matched is None:
            continue
        item = _item(
            title=title,
            link=urljoin(page_url, href),
            source=source,
            channel=channel,
            pub_date=_ymd(matched.group(1), matched.group(2), matched.group(3)),
        )
        if item:
            items.append(item)
    return items


def _parse_pbc(text: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for path, year, month, day, title in _PBC_RE.findall(text):
        item = _item(
            title=title,
            link=urljoin("https://www.pbc.gov.cn", path),
            source="中国人民银行",
            channel="pbc",
            pub_date=_ymd(year, month, day),
        )
        if item:
            items.append(item)
    return items


def _load_urls(
    channel: str,
    pages: list[tuple[str, Callable[[str], list[NewsItem]]]],
) -> list[NewsItem]:
    items: list[NewsItem] = []
    failures = 0
    for url, parser in pages:
        try:
            items.extend(parser(_http_text(url)))
        except RuntimeError as e:
            # One page must not abort the outlet or the other state-media channels.
            failures += 1
            logger.warning("state media channel %s failed for %s: %s", channel, url, e)
            continue
    if not items:
        logger.info(
            "state media channel %s returned no items (%s page failures)",
            channel,
            failures,
        )
    return _dedupe(items)


def fetch_state_media_channel(
    channel: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[NewsItem]:
    """Headlines from one state outlet inside ``[start_dt, end_dt]``."""
    if channel == "people_daily":
        items = _load_urls(
            channel,
            [(url, _parse_people) for url in _PEOPLE_PAGES],
        )
    elif channel == "xinhua_finance":
        items = _load_urls(channel, [(_XINHUA_PAGE, _parse_xinhua)])
    elif channel == "economic_daily":
        items = _load_urls(
            channel,
            [
                (url, lambda text, page=url: _parse_economic(text, page))
                for url in _ECONOMIC_PAGES
            ],
        )
    elif channel == "chinanews_finance":
        items = _load_urls(channel, [(_CHINANEWS_RSS, _parse_chinanews)])
    elif channel == "cctv_news":
        items = _load_urls(channel, [(_CCTV_JSONP, _parse_cctv_news)])
    elif channel == "gov_cn":
        items = _load_urls(channel, [(_GOV_JSON, _parse_gov)])
    elif channel == "xwlb":
        items = _load_urls(channel, [(_XWLB_API, _parse_xwlb)])
    elif channel == "pbc":
        items = _load_urls(channel, [(_PBC_PAGE, _parse_pbc)])
    elif channel == "mof":
        items = _load_urls(
            channel,
            [
                (
                    _MOF_PAGE,
                    lambda text: _parse_tdated_links(
                        text, _MOF_PAGE, source="财政部", channel="mof"
                    ),
                )
            ],
        )
    elif channel == "ndrc":
        items = _load_urls(
            channel,
            [
                (
                    _NDRC_PAGE,
                    lambda text: _parse_tdated_links(
                        text, _NDRC_PAGE, source="国家发展改革委", channel="ndrc"
                    ),
                )
            ],
        )
    elif channel == "stats_gov":
        items = _load_urls(
            channel,
            [
                (
                    _STATS_PAGE,
                    lambda text: _parse_tdated_links(
                        text, _STATS_PAGE, source="国家统计局", channel="stats_gov"
                    ),
                )
            ],
        )
    else:
        logger.warning("state media channel %s is not registered", channel)
        return []
    return _in_window(items, start_dt, end_dt)
