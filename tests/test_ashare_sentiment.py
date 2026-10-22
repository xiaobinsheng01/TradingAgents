"""A-share retail sentiment: Xueqiu HTTP + akshare Guba/heat, date window."""

from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest
import requests

import tradingagents.dataflows.ashare_sentiment as sent
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.news_items import NewsItem


@pytest.fixture
def sentiment_cache(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


@pytest.fixture(autouse=True)
def _no_live_guba(monkeypatch):
    """Guba posts are a live HTTP call. Tests that need them patch requests.get."""

    def _boom(*args, **kwargs):
        raise requests.RequestException("guba disabled in tests")

    monkeypatch.setattr(sent.requests, "get", _boom)


@pytest.mark.unit
def test_fetch_a_share_sentiment_non_a_share_unavailable():
    out = sent.fetch_a_share_sentiment("AAPL", "2026-01-01", "2026-01-10")
    assert "unavailable" in out
    assert "A-share" in out


@pytest.mark.unit
def test_fetch_a_share_sentiment_merges_xueqiu_and_guba(sentiment_cache, monkeypatch):
    monkeypatch.setattr(
        sent,
        "_fetch_xueqiu",
        lambda code, start, end: [
            NewsItem(
                title="雪球看多茅台",
                source="雪球",
                channel="xueqiu",
                pub_date="2026-01-05 10:00:00",
            )
        ],
    )
    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=mock.Mock(
            return_value=pd.DataFrame(
                [{"标题": "股吧讨论年报", "发布时间": "2026-01-06", "内容": "看好"}]
            )
        ),
        stock_comment_em=mock.Mock(
            return_value=pd.DataFrame(
                [{"代码": "600519", "标题": "关注指数=90", "发布时间": "2026-01-06"}]
            )
        ),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("600519.SS", "2026-01-01", "2026-01-10")
    assert "雪球看多茅台" in out
    assert "股吧讨论年报" in out
    assert "关注指数" in out


def _xueqiu_session_returning(payload):
    session = mock.Mock()
    session.get.return_value = payload
    return session


@pytest.mark.unit
def test_fetch_xueqiu_filters_future_posts(monkeypatch):
    future_ms = int(__import__("datetime").datetime(2026, 6, 1).timestamp() * 1000)
    past_ms = int(__import__("datetime").datetime(2026, 1, 5).timestamp() * 1000)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "list": [
                    {"text": "未来帖", "created_at": future_ms},
                    {"text": "窗口内帖", "created_at": past_ms},
                ]
            }

    monkeypatch.setattr(sent, "_xueqiu_session", lambda: _xueqiu_session_returning(Resp()))
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    items = sent._fetch_xueqiu("600519", start, end)
    titles = [item.title for item in items]
    assert "窗口内帖" in titles
    assert "未来帖" not in titles


@pytest.mark.unit
def test_fetch_xueqiu_network_error_returns_empty(monkeypatch):
    session = mock.Mock()
    session.get.side_effect = requests.ConnectionError("down")
    monkeypatch.setattr(sent, "_xueqiu_session", lambda: session)
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    assert sent._fetch_xueqiu("600519", start, end) == []


@pytest.mark.unit
def test_fetch_xueqiu_passes_token_from_cookie_header(monkeypatch):
    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"list": []}

    session = mock.Mock()
    session.headers = {"Cookie": "xq_a_token=abc"}
    session.cookies = {}
    session.get.return_value = Resp()
    monkeypatch.setattr(sent, "_xueqiu_session", lambda: session)
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    assert sent._fetch_xueqiu("600519", start, end) == []
    kwargs = session.get.call_args.kwargs
    assert kwargs["params"]["symbol"] == "SH600519"
    assert kwargs["params"]["xq_a_token"] == "abc"
    assert session.get.call_count == 1


@pytest.mark.unit
def test_fetch_xueqiu_401_returns_empty(monkeypatch):
    class Resp:
        status_code = 401

        def raise_for_status(self):
            raise requests.HTTPError("unauthorized")

        def json(self):
            raise AssertionError("rejected responses must not be parsed")

    monkeypatch.setattr(sent, "_xueqiu_session", lambda: _xueqiu_session_returning(Resp()))
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    assert sent._fetch_xueqiu("600519", start, end) == []


@pytest.mark.unit
def test_xueqiu_session_attaches_env_cookie(monkeypatch):
    monkeypatch.setenv("XUEQIU_COOKIE", "xq_a_token=abc")
    monkeypatch.delenv("TRADINGAGENTS_XUEQIU_COOKIE", raising=False)

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            raise AssertionError("must not warm the homepage when a cookie is set")

    monkeypatch.setattr(sent.requests, "Session", FakeSession)
    session = sent._xueqiu_session()
    assert session.headers.get("Cookie") == "xq_a_token=abc"
    assert session.headers.get("Origin") == "https://xueqiu.com"


@pytest.mark.unit
def test_xueqiu_session_warms_homepage_without_cookie(monkeypatch):
    monkeypatch.delenv("XUEQIU_COOKIE", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_XUEQIU_COOKIE", raising=False)
    calls = []

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            return mock.Mock(status_code=200)

    monkeypatch.setattr(sent.requests, "Session", FakeSession)
    sent._xueqiu_session()
    assert calls == ["https://xueqiu.com/"]


@pytest.mark.unit
def test_guba_posts_supply_bull_bear_count_without_xueqiu_cookie(
    sentiment_cache, monkeypatch
):
    monkeypatch.delenv("XUEQIU_COOKIE", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_XUEQIU_COOKIE", raising=False)
    monkeypatch.setattr(sent, "_fetch_xueqiu", lambda *args, **kwargs: [])

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "re": [
                    {
                        "post_id": "11",
                        "post_title": "看多突破",
                        "post_content": "准备加仓",
                        "post_publish_time": "2026-01-05 10:00:00",
                        "stockbar_code": "600519",
                    },
                    {
                        "post_id": "12",
                        "post_title": "利空跌停",
                        "post_content": "出货",
                        "post_publish_time": "2026-01-06 11:00:00",
                        "stockbar_code": "600519",
                    },
                    {
                        "post_id": "13",
                        "post_title": "今天复盘",
                        "post_content": "看看量",
                        "post_publish_time": "2026-01-04 09:00:00",
                    },
                    {
                        "post_title": "别的票",
                        "post_publish_time": "2026-01-05 09:00:00",
                        "stockbar_code": "000001",
                    },
                    {
                        "post_title": "窗口外",
                        "post_publish_time": "2025-12-01 09:00:00",
                        "stockbar_code": "600519",
                    },
                ]
            }

    monkeypatch.setattr(sent.requests, "get", lambda *args, **kwargs: Resp())
    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=mock.Mock(
            return_value=pd.DataFrame(
                [{"标题": "人气榜名次", "发布时间": "2026-01-06"}]
            )
        ),
        stock_comment_em=mock.Mock(return_value=pd.DataFrame()),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("600519.SS", "2026-01-01", "2026-01-10")
    assert "看多突破" in out
    assert "利空跌停" in out
    assert "今天复盘" in out
    assert "别的票" not in out
    assert "窗口外" not in out
    assert "看多 1" in out
    assert "看空 1" in out
    assert "未命中 1" in out
    assert "不是投票" in out
    assert "popularity rank" in out
    assert "news,600519,11.html" in out


def test_guba_html_fallback_when_json_list_is_empty(monkeypatch):
    html = (
        'var article_list={"re":[{"post_id":"9","post_title":"看空出货",'
        '"post_publish_time":"2026-01-06 09:00:00"}]};'
    )

    class JsonResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"re": []}

    class HtmlResp:
        text = html

        def raise_for_status(self):
            return None

    def fake_get(url, *args, **kwargs):
        if "listbystock" in str(url):
            return JsonResp()
        return HtmlResp()

    monkeypatch.setattr(sent.requests, "get", fake_get)
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    items = sent._fetch_guba_posts("600519", start, end)
    assert [item.title for item in items] == ["看空出货"]
    assert items[0].link.endswith("news,600519,9.html")


def test_guba_request_error_returns_empty(monkeypatch):
    def _boom(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(sent.requests, "get", _boom)
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    assert sent._fetch_guba_posts("600519", start, end) == []


def test_negated_phrase_is_not_a_bull_hit():
    assert sent._post_side("不是看多") == "quiet"
    assert sent._post_side("看多") == "bull"


def test_fetch_a_share_sentiment_notes_missing_xueqiu_cookie(sentiment_cache, monkeypatch):
    monkeypatch.delenv("XUEQIU_COOKIE", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_XUEQIU_COOKIE", raising=False)
    monkeypatch.setattr(sent, "_fetch_xueqiu", lambda *args, **kwargs: [])
    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=mock.Mock(
            return_value=pd.DataFrame(
                [{"标题": "股吧讨论年报", "发布时间": "2026-01-06", "内容": "看好"}]
            )
        ),
        stock_comment_em=mock.Mock(return_value=pd.DataFrame()),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("600519.SS", "2026-01-01", "2026-01-10")
    assert "XUEQIU_COOKIE" in out
    assert "股吧讨论年报" in out
    assert "Do not invent Xueqiu" in out or "do not invent Xueqiu" in out


@pytest.mark.unit
def test_comment_em_keeps_this_code_and_drops_other_listings(sentiment_cache, monkeypatch):
    monkeypatch.setattr(sent, "_fetch_xueqiu", lambda *args, **kwargs: [])
    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=mock.Mock(return_value=pd.DataFrame()),
        stock_comment_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {"代码": "000001", "标题": "平安银行热度90", "发布时间": "2026-01-06"},
                    {"代码": "600519", "标题": "茅台关注指数88", "发布时间": "2026-01-06"},
                    {"代码": "601061", "标题": "中信金属热度10", "发布时间": "2026-01-06"},
                ]
            )
        ),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("600519.SS", "2026-01-01", "2026-01-10")
    assert "茅台关注指数88" in out
    assert "平安银行" not in out
    assert "中信金属" not in out


@pytest.mark.unit
def test_comment_em_without_code_field_is_dropped(sentiment_cache, monkeypatch):
    monkeypatch.setattr(sent, "_fetch_xueqiu", lambda *args, **kwargs: [])
    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=mock.Mock(return_value=pd.DataFrame()),
        stock_comment_em=mock.Mock(
            return_value=pd.DataFrame(
                [{"标题": "全市场关注榜第一名", "发布时间": "2026-01-06"}]
            )
        ),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("600519.SS", "2026-01-01", "2026-01-10")
    assert "全市场关注榜" not in out
    assert "unavailable" in out


@pytest.mark.unit
def test_comment_em_is_parameterless_and_detail_typeerror_stays_scoped(
    sentiment_cache, monkeypatch
):
    monkeypatch.setattr(sent, "_fetch_xueqiu", lambda *args, **kwargs: [])
    comment_calls: list[dict] = []
    detail_calls: list[dict] = []

    def comment_em(**kwargs):
        comment_calls.append(dict(kwargs))
        if kwargs:
            raise AssertionError("stock_comment_em does not take a symbol")
        return pd.DataFrame(
            [
                {"代码": "600519", "关注指数": 88, "交易日": "2026-01-06"},
                {"代码": "000001", "关注指数": 1, "交易日": "2026-01-06"},
            ]
        )

    def focus(**kwargs):
        detail_calls.append(dict(kwargs))
        if not kwargs:
            raise AssertionError("detail APIs must not be called with no arguments")
        raise TypeError("unexpected keyword")

    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=mock.Mock(return_value=pd.DataFrame()),
        stock_comment_em=comment_em,
        stock_comment_detail_scrd_focus_em=focus,
        stock_comment_detail_zhpj_lspf_em=mock.Mock(return_value=pd.DataFrame()),
        stock_comment_detail_zlkp_jgcyd_em=mock.Mock(return_value=pd.DataFrame()),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("600519.SS", "2026-01-01", "2026-01-10")
    assert comment_calls == [{}]
    assert detail_calls == [{"symbol": "600519"}]
    assert "600519" in out
    assert "000001" not in out


@pytest.mark.unit
def test_hot_rank_uses_uppercase_exchange_prefix(sentiment_cache, monkeypatch):
    monkeypatch.setattr(sent, "_fetch_xueqiu", lambda *args, **kwargs: [])
    captured: list[dict] = []

    def hot(**kwargs):
        captured.append(dict(kwargs))
        return pd.DataFrame(
            [{"标题": "人气上升", "时间": "2026-01-06", "证券代码": "SH601061"}]
        )

    fake_ak = SimpleNamespace(
        stock_hot_rank_detail_em=hot,
        stock_comment_em=mock.Mock(return_value=pd.DataFrame()),
        stock_sns_sseinfo=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(sent, "_load_akshare", lambda: fake_ak)
    out = sent.fetch_a_share_sentiment("601061.SH", "2026-01-01", "2026-01-10")
    assert captured[0]["symbol"] == "SH601061"
    assert "人气上升" in out


@pytest.mark.unit
def test_xueqiu_empty_body_returns_empty(monkeypatch):
    class Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            raise AssertionError("empty body must not be parsed")

    monkeypatch.setattr(sent, "_xueqiu_session", lambda: _xueqiu_session_returning(Resp()))
    start = __import__("datetime").datetime(2026, 1, 1)
    end = __import__("datetime").datetime(2026, 1, 10)
    assert sent._fetch_xueqiu("601061", start, end) == []
