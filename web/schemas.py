"""Request body for a local web console run. Keys stay off this payload."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from cli.models import AnalystType
from cli.utils import is_valid_ticker_input, normalize_ticker_symbol
from tradingagents.dataflows.utils import safe_ticker_component

_SWING_WINDOW_KEYS = frozenset({"half_month", "three_months", "half_year"})
_TICKER_SPLIT = re.compile(r"[\s,，;；]+")
_MAX_TREND_TICKERS = 30


def parse_ticker_list(raw: str, *, max_items: int = _MAX_TREND_TICKERS) -> list[str]:
    """Split comma/space/semicolon separated tickers and normalize."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("至少输入一只股票代码")
    out: list[str] = []
    for part in _TICKER_SPLIT.split(text):
        token = part.strip()
        if not token:
            continue
        if not is_valid_ticker_input(token):
            raise ValueError(f"无效代码: {token}")
        normalized = normalize_ticker_symbol(token)
        safe_ticker_component(normalized)
        if normalized not in out:
            out.append(normalized)
        if len(out) > max_items:
            raise ValueError(f"最多 {max_items} 只股票")
    if not out:
        raise ValueError("至少输入一只股票代码")
    return out


class RunRequest(BaseModel):
    ticker: str
    analysis_date: str | None = None
    output_language: str = "Chinese"
    analysts: list[str] = Field(default_factory=lambda: ["market", "social", "news"])
    research_depth: int = 1
    llm_provider: str | None = None
    shallow_thinker: str | None = None
    deep_thinker: str | None = None
    backend_url: str | None = None
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    checkpoint: bool | None = None
    ingest_news: bool = True
    swing_tape_window: str = "half_month"

    @field_validator("ticker")
    @classmethod
    def ticker_must_be_safe(cls, value: str) -> str:
        text = value.strip()
        if not is_valid_ticker_input(text) or not text:
            raise ValueError("invalid ticker")
        normalized = normalize_ticker_symbol(text)
        safe_ticker_component(normalized)
        return normalized

    @field_validator("analysis_date")
    @classmethod
    def date_must_be_iso_and_not_future(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError("analysis date must be YYYY-MM-DD") from e
        if parsed.date() > datetime.now().date():
            raise ValueError("analysis date cannot be in the future")
        return value

    @field_validator("analysts")
    @classmethod
    def analysts_must_be_known(cls, value: list[str]) -> list[str]:
        allowed = {item.value for item in AnalystType}
        cleaned = []
        for item in value:
            key = str(item).lower()
            if key not in allowed:
                raise ValueError(f"unknown analyst: {item}")
            if key not in cleaned:
                cleaned.append(key)
        if not cleaned:
            raise ValueError("at least one analyst must be selected")
        return cleaned

    @field_validator("research_depth")
    @classmethod
    def depth_must_be_positive(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("research_depth must be between 1 and 5")
        return value

    @field_validator("backend_url")
    @classmethod
    def backend_url_must_be_http(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        text = value.strip()
        if not text.startswith(("http://", "https://")):
            raise ValueError("backend_url must start with http:// or https://")
        return text.rstrip("/")

    @field_validator("swing_tape_window")
    @classmethod
    def swing_window_must_be_known(cls, value: str) -> str:
        key = str(value or "half_month").strip().lower()
        if key not in _SWING_WINDOW_KEYS:
            raise ValueError(
                "swing_tape_window must be half_month, three_months, or half_year"
            )
        return key


class TrendPredictRequest(BaseModel):
    tickers: str = Field(
        ...,
        description="Comma, space, or newline separated A-share tickers",
    )
    as_of: str | None = None
    swing_tape_window: str = "three_months"

    @field_validator("tickers")
    @classmethod
    def tickers_must_parse(cls, value: str) -> str:
        parse_ticker_list(value)
        return value.strip()

    @field_validator("as_of")
    @classmethod
    def trend_date_must_be_iso_and_not_future(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError("as_of must be YYYY-MM-DD") from e
        if parsed.date() > datetime.now().date():
            raise ValueError("as_of cannot be in the future")
        return value

    @field_validator("swing_tape_window")
    @classmethod
    def trend_window_must_be_known(cls, value: str) -> str:
        key = str(value or "three_months").strip().lower()
        if key not in _SWING_WINDOW_KEYS:
            raise ValueError(
                "swing_tape_window must be half_month, three_months, or half_year"
            )
        return key
