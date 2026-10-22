"""A-share index outlook: same-day research bias, no invented prices."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.dataflows.ashare_index_outlook import (
    DISPLAY_INDEXES,
    IndexOutlookNotLiveError,
    build_market_bias,
    index_outlook,
    index_outlook_bars,
    normalize_index_symbol,
)

MOD = "tradingagents.dataflows.ashare_index_outlook"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _bars(end: str, n: int, start_close: float, step: float, amount: float | None = None) -> list[dict]:
    day = datetime.strptime(end, "%Y-%m-%d")
    rows = []
    for i in range(n):
        close = start_close + step * i
        rows.append(
            {
                "date": (day - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d"),
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1_000_000,
                "amount": amount,
            }
        )
    return rows


def _series(end: str, *, step: float = 20.0, sse_amount: float = 8e11, sza_amount: float = 6e11) -> dict:
    series = {}
    for spec in DISPLAY_INDEXES:
        amount = sse_amount if spec.symbol == "sh000001" else 1e11
        series[spec.symbol] = _bars(end, 40, 3000, step, amount=amount)
    series["sz399107"] = _bars(end, 40, 8000, step, amount=sza_amount)
    series["sz399986"] = _bars(end, 40, 1000, step, amount=1e11)
    return series


def _install(
    monkeypatch,
    series: dict,
    *,
    zt: list | None = None,
    dt: list | None = None,
    prev: list | None = None,
    sina: list | None = None,
) -> dict:
    seen = {"akshare": 0, "sina": 0}

    def load_ak():
        seen["akshare"] += 1
        return object()

    def cached(key, as_of, channel, loader, ttl_seconds=None):
        return loader() or []

    def fetch_index(ak, as_of, start, symbol):
        return list(series.get(symbol) or [])

    def fetch_zt(ak, as_of):
        return list(zt if zt is not None else [{"涨跌幅": "2.0"}] * 30)

    def fetch_dt(ak, as_of):
        return list(dt if dt is not None else [{"涨跌幅": "-2.0"}] * 5)

    def fetch_prev(ak, as_of):
        return list(prev if prev is not None else [{"涨跌幅": "1.5"}])

    def try_records(ak, names, kwargs_list, **kwargs):
        if names == ("stock_zh_a_spot",):
            seen["sina"] += 1
            return list(sina or [])
        return []

    monkeypatch.setattr(f"{MOD}._load_akshare", load_ak)
    monkeypatch.setattr(f"{MOD}._cached", cached)
    monkeypatch.setattr(f"{MOD}._fetch_index_daily", fetch_index)
    monkeypatch.setattr(f"{MOD}._fetch_zt_pool", fetch_zt)
    monkeypatch.setattr(f"{MOD}._fetch_dt_pool", fetch_dt)
    monkeypatch.setattr(f"{MOD}._fetch_prev_zt", fetch_prev)
    monkeypatch.setattr(f"{MOD}._try_ak_records", try_records)
    return seen


def test_normalize_index_symbol_rejects_stocks():
    assert normalize_index_symbol("SH000300") == "sh000300"
    with pytest.raises(ValueError, match="指数"):
        normalize_index_symbol("600519")
    with pytest.raises(ValueError, match="指数"):
        normalize_index_symbol("sz399107")


def test_build_market_bias_buy_when_tape_is_broad_and_up():
    bias = build_market_bias(
        as_of="2026-10-15",
        last_date="2026-10-15",
        regime="high",
        ret_1d=0.8,
        ret_20d=4.0,
        range_pos=40.0,
        limit_up_count=40,
        limit_down_count=8,
    )
    assert bias["t1_bias"] == "BUY"
    assert bias["t1_label"] == "偏多"
    assert bias["swing_bias"] == "BUY"
    assert "容错高" in bias["swing_reason"]


def test_build_market_bias_holds_a_stretched_advance():
    bias = build_market_bias(
        as_of="2026-10-15",
        last_date="2026-10-15",
        regime="high",
        ret_1d=0.4,
        ret_20d=9.0,
        range_pos=92.0,
        limit_up_count=20,
        limit_down_count=4,
    )
    assert bias["t1_bias"] == "BUY"
    assert bias["swing_bias"] == "HOLD"
    assert "上沿" in bias["swing_reason"]


def test_build_market_bias_sells_a_thin_decline():
    bias = build_market_bias(
        as_of="2026-10-15",
        last_date="2026-10-14",
        regime="low",
        ret_1d=-1.2,
        ret_20d=-9.0,
        range_pos=12.0,
        limit_up_count=6,
        limit_down_count=18,
    )
    assert bias["t1_bias"] == "SELL"
    assert bias["swing_bias"] == "SELL"
    assert bias["swing_label"] == "偏空"


def test_build_market_bias_holds_when_breadth_or_bars_are_missing():
    missing_counts = build_market_bias(
        as_of="2026-10-15",
        last_date="2026-10-15",
        regime="high",
        ret_1d=1.0,
        ret_20d=4.0,
        range_pos=50.0,
        limit_up_count=None,
        limit_down_count=None,
    )
    assert missing_counts["t1_bias"] == "HOLD"
    assert "家数不可用" in missing_counts["t1_reason"]
    stale = build_market_bias(
        as_of="2026-10-15",
        last_date="2026-09-01",
        regime="high",
        ret_1d=1.0,
        ret_20d=4.0,
        range_pos=50.0,
        limit_up_count=10,
        limit_down_count=2,
    )
    assert stale["t1_bias"] == "HOLD"
    assert stale["swing_bias"] == "HOLD"
    assert "不外推" in stale["t1_reason"]


def test_build_market_bias_buys_a_deep_pullback_when_regime_is_not_low():
    bias = build_market_bias(
        as_of="2026-10-15",
        last_date="2026-10-15",
        regime="neutral",
        ret_1d=-0.2,
        ret_20d=-9.5,
        range_pos=10.0,
        limit_up_count=12,
        limit_down_count=12,
    )
    assert bias["t1_bias"] == "HOLD"
    assert bias["swing_bias"] == "BUY"
    assert "下沿" in bias["swing_reason"]


def test_index_outlook_rejects_past_date_before_vendor(monkeypatch):
    def boom():
        raise AssertionError("vendor should not be called")

    monkeypatch.setattr(f"{MOD}._load_akshare", boom)
    with pytest.raises(IndexOutlookNotLiveError, match="当天"):
        index_outlook("2020-01-02")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        index_outlook("2020/01/02")


def test_index_outlook_rates_a_broad_advance_without_inventing_a_missing_index(monkeypatch):
    today = _today()
    series = _series(today, step=20.0)
    series["sh000688"] = []
    seen = _install(monkeypatch, series)
    snap = index_outlook(today)
    assert seen["akshare"] == 1
    assert seen["sina"] == 0
    assert snap["benchmark"] == "sh000300"
    assert snap["regime"] == "high"
    assert snap["t1_bias"] == "BUY"
    assert snap["swing_bias"] == "HOLD"
    assert "上沿" in snap["swing_reason"]
    assert snap["limit_up_count"] == 30
    assert snap["limit_down_count"] == 5
    assert snap["market_amount_yuan"] == pytest.approx(1.4e12)
    names = [row["name"] for row in snap["rows"]]
    assert names == ["上证指数", "深证成指", "创业板指", "沪深300", "上证50", "中证500", "科创50"]
    hs300 = next(row for row in snap["rows"] if row["symbol"] == "sh000300")
    assert hs300["close"] is not None
    assert hs300["t1_label"] == "偏多"
    assert hs300["structure"]
    if "买" in hs300["structure"] or "卖" in hs300["structure"]:
        assert hs300["structure"] in {"三类买点候选", "三类卖点候选"}
    star = next(row for row in snap["rows"] if row["symbol"] == "sh000688")
    assert star["close"] is None
    assert star["t1_bias"] == "HOLD"
    assert star["structure"] == "没有日线"
    assert "部分指数没有日线" in snap["note"]
    assert "不下单" in snap["note"]


def test_index_outlook_uses_sina_breadth_when_pools_are_empty(monkeypatch):
    today = _today()
    _install(
        monkeypatch,
        _series(today, step=-20.0, sse_amount=5e11, sza_amount=5e11),
        zt=[],
        dt=[],
        sina=[{"涨跌幅": 10}] * 3 + [{"涨跌幅": -10}] * 8,
    )
    snap = index_outlook()
    assert snap["breadth_source"] == "sina_spot_live_approx"
    assert snap["limit_up_count"] == 3
    assert snap["limit_down_count"] == 8
    assert snap["regime"] == "low"
    assert snap["t1_bias"] == "SELL"


def test_index_outlook_does_not_invent_prices_when_every_index_is_empty(monkeypatch):
    _install(monkeypatch, {})
    snap = index_outlook()
    assert snap["t1_bias"] == "HOLD"
    assert snap["market_amount_yuan"] is None
    assert all(row["close"] is None for row in snap["rows"])
    assert "指数日线没有返回" in snap["note"]


def test_index_outlook_keeps_direction_on_the_previous_session(monkeypatch):
    today = _today()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    _install(monkeypatch, _series(yesterday, step=20.0))
    snap = index_outlook(today)
    assert snap["session_date"] == yesterday
    assert snap["t1_bias"] == "BUY"
    assert "不外推" not in snap["t1_reason"]


def test_index_bars_reject_unknown_symbols_before_vendor(monkeypatch):
    def boom():
        raise AssertionError("vendor should not be called")

    monkeypatch.setattr(f"{MOD}._load_akshare", boom)
    with pytest.raises(ValueError, match="指数"):
        index_outlook_bars("600519.SH")
    with pytest.raises(IndexOutlookNotLiveError, match="当天"):
        index_outlook_bars("sh000300", "2020-01-02")


def test_index_bars_return_daily_ohlc(monkeypatch):
    today = _today()
    _install(monkeypatch, _series(today))
    payload = index_outlook_bars("sh000300", today)
    assert payload["name"] == "沪深300"
    assert payload["bars"]
    assert payload["bars"][-1]["time"] == today
    assert {"open", "high", "low", "close"} <= set(payload["bars"][-1])
    assert "不是委托" in payload["note"]
