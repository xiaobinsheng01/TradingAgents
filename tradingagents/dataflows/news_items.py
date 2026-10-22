"""Canonical news/filing/flash items, dedupe, and markdown rendering."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urlparse

_POLICY_MARKERS = (
    "证监会",
    "央行",
    "中国人民银行",
    "国务院",
    "银保监会",
    "国家金融监督管理",
    "财政部",
    "发改委",
    "政治局",
    "CSRC",
    "PBOC",
)


@dataclass(frozen=True)
class NewsItem:
    title: str
    body: str = ""
    source: str = ""
    link: str = ""
    pub_date: str | None = None
    channel: str = ""
    category: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> NewsItem:
        return cls(
            title=str(raw.get("title") or "").strip(),
            body=str(raw.get("body") or "").strip(),
            source=str(raw.get("source") or "").strip(),
            link=str(raw.get("link") or "").strip(),
            pub_date=(str(raw["pub_date"]).strip() if raw.get("pub_date") else None),
            channel=str(raw.get("channel") or "").strip(),
            category=str(raw.get("category") or "").strip(),
        )


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title).casefold()


def canonical_link(link: str) -> str:
    parsed = urlparse(link.strip())
    host = (parsed.netloc or "").casefold().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    return f"{host}{path}"


def item_identity(item: NewsItem) -> tuple[str, str] | None:
    """Stable identity for warehouse upsert and cross-channel dedupe.

    Link wins when present; otherwise the whitespace-folded title. Items
    without a title are unidentifiable and return None.
    """
    if not item.title:
        return None
    link_key = canonical_link(item.link) if item.link else ""
    if link_key:
        return ("link", link_key)
    return ("title", normalize_title(item.title))


def is_policy_item(item: NewsItem) -> bool:
    blob = f"{item.title}{item.body}{item.category}"
    return any(marker in blob for marker in _POLICY_MARKERS)


def dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    """Drop repeats across channels. Link identity wins; else normalized title."""
    seen: set[tuple[str, str]] = set()
    out: list[NewsItem] = []
    for item in items:
        key = item_identity(item)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def pub_datetime(item: NewsItem) -> datetime | None:
    if not item.pub_date:
        return None
    text = item.pub_date.strip()
    for fmt, size in (
        ("%Y-%m-%dT%H:%M:%S", 19),
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


_GENERIC_CATEGORIES = frozenset({"", "company", "flash", "policy", "sentiment", "filing"})


def render_items(items: list[NewsItem], limit: int) -> str:
    lines: list[str] = []
    for item in items[:limit]:
        label = (
            f"[{item.category}] "
            if item.category and item.category not in _GENERIC_CATEGORIES
            else ""
        )
        source = item.source or item.channel or "unknown"
        lines.append(f"### {label}{item.title} (source: {source})")
        if item.body:
            lines.append(item.body)
        if item.link:
            lines.append(f"Link: {item.link}")
        lines.append("")
    return "\n".join(lines).strip()
