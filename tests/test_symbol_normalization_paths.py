"""Symbol normalization must apply on every yfinance path, not just price fetch.

Regression tests for #983 (instrument identity), #984 (reflection returns), and
the news path: a broker symbol like XAUUSD must resolve to the same Yahoo symbol
(GC=F) that the price path uses, so identity, realized-return, and news lookups
hit the right instrument instead of failing/mismatching.
"""
import pandas as pd
import pytest

import tradingagents.agents.utils.agent_utils as au
import tradingagents.dataflows.yfinance_news as ynews
import tradingagents.graph.trading_graph as tg
from tradingagents.dataflows.symbol_utils import NoMarketDataError
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_identity_lookup_normalizes_symbol(monkeypatch):
    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            seen["symbol"] = symbol

        @property
        def info(self):
            return {"longName": "Gold Futures", "quoteType": "FUTURE"}

    monkeypatch.setattr(au.yf, "Ticker", FakeTicker)
    au.resolve_instrument_identity.cache_clear()

    identity = au.resolve_instrument_identity("XAUUSD")

    assert seen["symbol"] == "GC=F"  # normalized, not the raw broker symbol
    assert identity.get("company_name") == "Gold Futures"


def test_fetch_returns_normalizes_symbol(monkeypatch):
    queried = []

    class FakeTicker:
        def __init__(self, symbol):
            queried.append(symbol)

        def history(self, *args, **kwargs):
            prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
            idx = pd.date_range(start="2025-01-02", periods=len(prices), freq="D")
            return pd.DataFrame({"Close": prices}, index=idx)

    monkeypatch.setattr(tg.yf, "Ticker", FakeTicker)

    # _fetch_returns does not use ``self``; call unbound to avoid building the graph.
    raw, alpha, days, resolved = TradingAgentsGraph._fetch_returns(
        None, "XAUUSD", "2025-01-02", holding_days=5, benchmark="SPY"
    )

    assert queried[0] == "GC=F"  # stock symbol normalized (#984)
    assert queried[1] == "SPY"   # benchmark left as the canonical symbol
    assert raw is not None and days is not None
    assert resolved == "2025-01-07"  # resolution date recorded (#1251)


def test_fetch_returns_a_share_skips_yahoo(monkeypatch):
    queried = []

    class FakeTicker:
        def __init__(self, symbol):
            queried.append(symbol)

        def history(self, *args, **kwargs):
            raise AssertionError("A-share returns must not hit Yahoo")

    monkeypatch.setattr(tg.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(
        "tradingagents.dataflows.akshare_market.realized_holding_returns",
        lambda ticker, trade_date, holding_days, benchmark: (
            0.02,
            0.01,
            holding_days,
            "2026-01-12",
        ),
    )
    raw, alpha, days, resolved = TradingAgentsGraph._fetch_returns(
        None, "601061.SH", "2026-01-05", holding_days=5, benchmark="000001.SS"
    )
    assert queried == []
    assert raw == pytest.approx(0.02)
    assert alpha == pytest.approx(0.01)
    assert days == 5
    assert resolved == "2026-01-12"


def test_news_lookup_normalizes_symbol(monkeypatch):
    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            seen["symbol"] = symbol

        def get_news(self, count):
            return []

    monkeypatch.setattr(ynews.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(ynews, "yf_retry", lambda fn: fn())

    out = ynews.get_news_yfinance("XAUUSD", "2025-01-01", "2025-01-10")

    assert seen["symbol"] == "GC=F"   # news queried with the canonical symbol
    assert "XAUUSD" in out            # the user's ticker stays in the report
    assert "GC=F" in out              # provenance noted


def test_news_lookup_skips_yahoo_for_a_share(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("yfinance must not be called for A-shares")

    monkeypatch.setattr(ynews.yf, "Ticker", boom)
    with pytest.raises(NoMarketDataError, match="A-share"):
        ynews.get_news_yfinance("601061.SH", "2026-01-01", "2026-01-10")
