"""yfinance treats ``end`` as exclusive; we must request one extra day so the
requested end_date (and the current day) is actually included.

Regressions for #986 (current-day OHLCV excluded) and #987 (requested end_date
row omitted).
"""
import pandas as pd
import pytest

import tradingagents.dataflows.stockstats_utils as su
import tradingagents.dataflows.y_finance as yfin
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


@pytest.mark.unit
def test_get_yfin_requests_inclusive_end(monkeypatch):
    captured = {}

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start, end):
            captured["start"] = start
            captured["end"] = end
            idx = pd.to_datetime(["2025-05-08", "2025-05-09"])
            return pd.DataFrame(
                {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0],
                 "Close": [1.0, 2.0], "Volume": [1, 2]},
                index=idx,
            )

    monkeypatch.setattr(yfin.yf, "Ticker", FakeTicker)
    out = yfin.get_YFin_data_online("AAPL", "2025-05-01", "2025-05-09")

    # end is requested one day past end_date so 2025-05-09 is included (#987).
    assert captured["end"] == "2025-05-10"
    # Header still reflects the requested range, not the internal +1 day.
    assert "to 2025-05-09" in out


@pytest.mark.unit
def test_get_yfin_skips_a_share_without_yahoo(monkeypatch):
    monkeypatch.setattr(
        yfin.yf,
        "Ticker",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Yahoo must not run")),
    )
    with pytest.raises(NoMarketDataError, match="A-share"):
        yfin.get_YFin_data_online("601061.SH", "2025-05-01", "2025-05-09")


@pytest.mark.unit
def test_load_ohlcv_uses_akshare_for_a_share(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    csv = (
        "# Stock data for 601061 from 2021-05-09 to 2026-05-09\n"
        "# Total records: 2\n"
        "# Source: akshare/AKTools\n\n"
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2026-05-08,10.0,11.0,9.5,10.5,10.5,1000\n"
        "2026-05-09,10.5,11.2,10.2,11.0,11.0,1200\n"
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.akshare_market.get_akshare_stock_data",
        lambda *a, **k: csv,
    )

    def boom(*_a, **_k):
        raise AssertionError("Yahoo must not run for A-share OHLCV")

    monkeypatch.setattr(su.yf, "download", boom)
    data = su.load_ohlcv("601061.SH", "2026-05-09")
    assert float(data.iloc[-1]["Close"]) == 11.0
    assert "AK-data" in str(list(tmp_path.iterdir())[0])


@pytest.mark.unit
def test_load_ohlcv_requests_inclusive_end(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    captured = {}

    def fake_download(symbol, start, end, **kwargs):
        captured["end"] = end
        idx = pd.to_datetime([pd.Timestamp.today().normalize()])
        return pd.DataFrame(
            {"Open": [100.0], "High": [100.0], "Low": [100.0],
             "Close": [100.0], "Volume": [1]},
            index=idx,
        )

    monkeypatch.setattr(su.yf, "download", fake_download)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    su.load_ohlcv("AAPL", today)

    expected_end = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    assert captured["end"] == expected_end  # tomorrow -> today's row included (#986)
