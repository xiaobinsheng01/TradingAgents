"""Serper / Google Search vendor for overseas get_global_news."""

from datetime import datetime
from unittest import mock

import pytest
import requests

import tradingagents.dataflows.google_news as gnews
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorRateLimitError

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Fed signal lifts China copper shares</title>
      <link>https://www.reuters.com/markets/china-copper</link>
      <pubDate>Tue, 08 Sep 2026 10:00:00 GMT</pubDate>
      <source>Reuters</source>
      <description>Overnight US futures and copper.</description>
    </item>
    <item>
      <title>China A-shares open watch</title>
      <link>https://x.com/markets/status/1</link>
      <pubDate>Tue, 08 Sep 2026 11:00:00 GMT</pubDate>
      <source>X</source>
      <description>CSI 300 futures.</description>
    </item>
    <item>
      <title>Unrelated celebrity clip</title>
      <link>https://www.youtube.com/watch?v=abc</link>
      <pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate>
      <source>YouTube</source>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def news_cache_dir(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


@pytest.fixture
def live_as_of(monkeypatch):
    monkeypatch.setattr(gnews, "is_live_as_of", lambda _as_of: True)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_SERPER_API_KEY", raising=False)


class _Resp:
    def __init__(self, status_code=200, text="", content=None, payload=None):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.mark.unit
def test_get_global_news_historical_does_not_http(monkeypatch, news_cache_dir):
    get = mock.Mock(side_effect=AssertionError("historical as-of must not hit Google"))
    post = mock.Mock(side_effect=AssertionError("historical as-of must not hit Serper"))
    monkeypatch.setattr(gnews.requests, "get", get)
    monkeypatch.setattr(gnews.requests, "post", post)
    monkeypatch.setattr(gnews, "is_live_as_of", lambda _as_of: False)
    with pytest.raises(NoMarketDataError, match="no live index vintage"):
        gnews.get_global_news("2026-01-10", look_back_days=7, limit=5)
    get.assert_not_called()
    post.assert_not_called()


@pytest.mark.unit
def test_get_global_news_rss_fallback_without_serper_key(
    monkeypatch, news_cache_dir, live_as_of
):
    monkeypatch.setattr(
        gnews.requests,
        "get",
        mock.Mock(return_value=_Resp(text=RSS_XML, content=RSS_XML.encode("utf-8"))),
    )
    post = mock.Mock(side_effect=AssertionError("RSS path must not POST Serper"))
    monkeypatch.setattr(gnews.requests, "post", post)
    out = gnews.get_global_news("2026-09-08", look_back_days=7, limit=10)
    assert "Fed signal lifts China copper shares" in out
    assert "https://www.reuters.com/markets/china-copper" in out
    assert "China A-shares open watch" in out
    assert "source: X" in out
    assert "YouTube" in out
    assert "Overseas headlines" in out
    assert "Overseas platform posts" in out
    post.assert_not_called()


@pytest.mark.unit
def test_get_global_news_uses_serper_when_key_set(
    monkeypatch, news_cache_dir, live_as_of
):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test-key")
    news_payload = {
        "news": [
            {
                "title": "LME copper jumps on China demand",
                "snippet": "Industrial metals",
                "link": "https://www.bloomberg.com/news/copper",
                "source": "Bloomberg",
                "date": "Sep 8, 2026",
            }
        ]
    }
    organic_payload = {
        "organic": [
            {
                "title": "China A-shares open watch",
                "snippet": "CSI 300 futures",
                "link": "https://x.com/markets/status/1",
                "date": "Sep 8, 2026",
            }
        ]
    }

    def _post(url, **kwargs):
        if "google.serper.dev/news" in url:
            return _Resp(payload=news_payload, text="{}")
        return _Resp(payload=organic_payload, text="{}")

    post = mock.Mock(side_effect=_post)
    get = mock.Mock(side_effect=AssertionError("Serper path must not hit RSS"))
    monkeypatch.setattr(gnews.requests, "post", post)
    monkeypatch.setattr(gnews.requests, "get", get)
    out = gnews.get_global_news("2026-09-08", look_back_days=7, limit=5)
    assert "LME copper jumps on China demand" in out
    assert "China A-shares open watch" in out
    assert "source: X" in out
    assert post.call_args.kwargs["headers"]["X-API-KEY"] == "serper-test-key"
    assert "google.serper.dev/" in post.call_args.args[0]
    get.assert_not_called()


@pytest.mark.unit
def test_get_global_news_serper_429_is_rate_limit(
    monkeypatch, news_cache_dir, live_as_of
):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test-key")
    monkeypatch.setattr(
        gnews.requests,
        "post",
        mock.Mock(return_value=_Resp(status_code=429, text="quota")),
    )
    with pytest.raises(VendorRateLimitError, match="rate-limited"):
        gnews.get_global_news("2026-09-08", look_back_days=7, limit=5)


@pytest.mark.unit
def test_get_global_news_rss_429_is_rate_limit(monkeypatch, news_cache_dir, live_as_of):
    monkeypatch.setattr(
        gnews.requests,
        "get",
        mock.Mock(return_value=_Resp(status_code=429, text="quota")),
    )
    with pytest.raises(VendorRateLimitError, match="rate-limited"):
        gnews.get_global_news("2026-09-08", look_back_days=7, limit=5)


@pytest.mark.unit
def test_get_global_news_network_error_is_no_data(
    monkeypatch, news_cache_dir, live_as_of
):
    monkeypatch.setattr(
        gnews.requests,
        "get",
        mock.Mock(side_effect=requests.ConnectionError("down")),
    )
    with pytest.raises(NoMarketDataError):
        gnews.get_global_news("2026-09-08", look_back_days=7, limit=5)


@pytest.mark.unit
def test_unreachable_google_skips_remaining_queries(monkeypatch, news_cache_dir, live_as_of):
    calls = {"n": 0}

    def get(*args, **kwargs):
        calls["n"] += 1
        raise requests.ConnectionError(
            "HTTPSConnection(host='news.google.com', port=443): "
            "Failed to establish a new connection: [Errno 101] Network is unreachable"
        )

    monkeypatch.setattr(gnews.requests, "get", get)
    with pytest.raises(NoMarketDataError):
        gnews.get_global_news("2026-09-08", look_back_days=7, limit=5)
    assert calls["n"] == 1


@pytest.mark.unit
def test_parse_rfc822_and_iso_pub():
    rfc = gnews._parse_pub("Tue, 08 Sep 2026 10:00:00 GMT")
    assert rfc is not None
    assert rfc.day == 8
    iso = gnews._parse_pub("2026-09-08 10:00:00")
    assert iso == datetime(2026, 9, 8, 10, 0, 0)
    named = gnews._parse_pub("Sep 8, 2026")
    assert named == datetime(2026, 9, 8)
