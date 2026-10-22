"""Point-in-time news JSON cache under data_cache_dir."""

from datetime import date, datetime, timedelta, timezone

import pytest

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.news_items import NewsItem
from tradingagents.dataflows.news_store import fetch_cached, read_channel, write_channel
from tradingagents.dataflows.utils import safe_ticker_component


@pytest.fixture
def news_cache_dir(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


@pytest.mark.unit
def test_fetch_cached_writes_and_reuses_historical_as_of(news_cache_dir):
    as_of = "2026-01-10"
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [NewsItem(title="年报", channel="east_money", source="东财")]

    first = fetch_cached("600519", as_of, "east_money", loader)
    second = fetch_cached("600519", as_of, "east_money", loader)
    assert calls["n"] == 1
    assert first[0].title == second[0].title == "年报"
    cached = read_channel("600519", as_of, "east_money")
    assert cached is not None
    assert (news_cache_dir / "news" / "600519" / as_of / "east_money.json").is_file()


@pytest.mark.unit
def test_write_channel_skips_empty_payload(news_cache_dir):
    write_channel("600519", "2026-01-10", "east_money", [])
    assert read_channel("600519", "2026-01-10", "east_money") is None
    assert list(news_cache_dir.rglob("*.json")) == []


@pytest.mark.unit
def test_cache_path_rejects_traversal_ticker(news_cache_dir):
    with pytest.raises(ValueError):
        fetch_cached("../etc", "2026-01-10", "east_money", lambda: [])
    safe_ticker_component("600519")


@pytest.mark.unit
def test_live_as_of_refreshes_after_ttl(news_cache_dir, monkeypatch):
    as_of = datetime.now(timezone.utc).date().isoformat()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [NewsItem(title=f"live-{calls['n']}", channel="cctv")]

    set_config({"news_cache_ttl_seconds": 1})
    fetch_cached("_global", as_of, "cctv", loader)
    real_time = __import__("time").time
    monkeypatch.setattr(
        "tradingagents.dataflows.news_store.time.time",
        lambda: real_time() + 10,
    )
    # Force mtime to look stale relative to patched now: write already happened;
    # _is_fresh uses time.time() - mtime. Patch time.time to future.
    later = fetch_cached("_global", as_of, "cctv", loader)
    assert calls["n"] == 2
    assert later[0].title == "live-2"


@pytest.mark.unit
def test_historical_as_of_never_uses_ttl(news_cache_dir, monkeypatch):
    as_of = (date.today() - timedelta(days=10)).isoformat()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [NewsItem(title="old", channel="cctv")]

    set_config({"news_cache_ttl_seconds": 1})
    fetch_cached("_global", as_of, "cctv", loader)
    real_time = __import__("time").time
    monkeypatch.setattr(
        "tradingagents.dataflows.news_store.time.time",
        lambda: real_time() + 10_000,
    )
    fetch_cached("_global", as_of, "cctv", loader)
    assert calls["n"] == 1


@pytest.mark.unit
def test_live_as_of_honors_ttl_override(news_cache_dir, monkeypatch):
    as_of = datetime.now(timezone.utc).date().isoformat()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [NewsItem(title=f"wire-{calls['n']}", channel="cls_alerts")]

    set_config({"news_cache_ttl_seconds": 900})
    fetch_cached("_global", as_of, "cls_alerts", loader, ttl_seconds=1)
    real_time = __import__("time").time
    monkeypatch.setattr(
        "tradingagents.dataflows.news_store.time.time",
        lambda: real_time() + 10,
    )
    later = fetch_cached("_global", as_of, "cls_alerts", loader, ttl_seconds=1)
    assert calls["n"] == 2
    assert later[0].title == "wire-2"


@pytest.mark.unit
def test_fetch_cached_records_round_trips_dicts(news_cache_dir):
    from tradingagents.dataflows.news_store import fetch_cached_records, read_records

    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return [{"date": "2026-01-10", "close": 10.0}]

    first = fetch_cached_records("600519", "2026-01-10", "daily_qfq", loader)
    second = fetch_cached_records("600519", "2026-01-10", "daily_qfq", loader)
    assert calls["n"] == 1
    assert first == second == [{"date": "2026-01-10", "close": 10.0}]
    assert read_records("600519", "2026-01-10", "daily_qfq")[0]["close"] == 10.0
