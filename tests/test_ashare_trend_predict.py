"""Deterministic multi-ticker trend snapshots for the web console."""

from __future__ import annotations

from datetime import datetime

import pytest

from tradingagents.dataflows import ashare_trend_predict as trend
from web.schemas import parse_ticker_list


def test_parse_ticker_list_normalizes_and_dedupes():
    out = parse_ticker_list("002487, 002081.SZ\n002487")
    assert out == ["002487.SZ", "002081.SZ"]


def test_resolve_swing_window_accepts_three_months():
    from tradingagents.dataflows.akshare_market import resolve_swing_window

    assert resolve_swing_window("three_months") == "three_months"


def test_stock_trend_predict_requires_today(monkeypatch):
    monkeypatch.setattr(trend, "_utc_today", lambda: "2026-10-20")
    with pytest.raises(trend.TrendPredictNotLiveError):
        trend.stock_trend_predict(["600519.SS"], as_of="2026-10-19", window="half_month")


def test_stock_trend_row_rejects_chinext(monkeypatch):
    as_of = "2026-10-20"
    monkeypatch.setattr(trend, "_utc_today", lambda: as_of)
    with pytest.raises(ValueError, match="创业板"):
        trend.stock_trend_row("300750.SZ", as_of=as_of, window="half_month")


def test_stock_trend_row_uses_window_stats(monkeypatch):
    as_of = "2026-10-16"
    monkeypatch.setattr(trend, "_utc_today", lambda: as_of)
    daily = []
    price = 10.0
    for day in (f"2026-10-{d:02d}" for d in range(1, 13)):
        daily.append(
            {
                "date": day,
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1_000_000,
                "amount": 10_000_000,
                "turnover": 1.0,
                "pct_chg": 0.0,
                "limit_up": False,
                "limit_down": False,
            }
        )
        price += 0.1

    def fake_load(ticker, day, window_key):
        return (
            "600519",
            "贵州茅台",
            daily,
            [{"date": daily[0]["date"], "close": 100.0}, {"date": daily[-1]["date"], "close": 101.0}],
            {"label": "近半个月", "calendar_days": 15},
        )

    monkeypatch.setattr(trend, "_load_window_bars", fake_load)
    def fake_cached(key, day, channel, loader):
        if channel == "market_mood_v1":
            return {"mood_swing": "HOLD", "mood_swing_reason": "test"}
        return loader()

    monkeypatch.setattr(trend, "_cached", fake_cached)
    monkeypatch.setattr(
        trend,
        "_event_flags",
        lambda code, day, is_st: {"announce_bad": False, "announce_good": False},
    )
    row = trend.stock_trend_row("600519.SS", as_of=as_of, window="half_month")
    assert row["ticker"] == "600519.SS"
    assert row["trend_bias"] in {"BUY", "HOLD", "SELL"}
    assert row["structure"]
