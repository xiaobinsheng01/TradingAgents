"""AKTools Docker HTTP client used when AKSHARE_BASE_URL is set."""

from unittest.mock import Mock

import pytest

import tradingagents.dataflows.akshare_news as aknews
from tradingagents.dataflows.config import set_config


@pytest.mark.unit
def test_load_akshare_uses_http_client_when_base_url_set(monkeypatch):
    monkeypatch.delenv("AKSHARE_BASE_URL", raising=False)
    set_config({"akshare_base_url": "http://127.0.0.1:8080"})
    client = aknews._load_akshare()
    assert isinstance(client, aknews.AktoolsHttpClient)
    assert client.base_url == "http://127.0.0.1:8080"


@pytest.mark.unit
def test_http_client_get_passes_query_and_parses_records(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        response = Mock()
        response.status_code = 200
        response.json.return_value = [
            {"日期": "2026-01-10", "收盘": 1480.0, "成交额": 1e8},
        ]
        return response

    monkeypatch.setattr(aknews.requests, "get", fake_get)
    client = aknews.AktoolsHttpClient("http://127.0.0.1:8080/")
    rows = client.stock_zh_a_hist(
        symbol="600519", period="daily", start_date="20260101", adjust=""
    )
    assert captured["url"] == "http://127.0.0.1:8080/api/public/stock_zh_a_hist"
    assert captured["params"]["symbol"] == "600519"
    assert captured["params"]["adjust"] == ""
    assert captured["timeout"] == aknews.REQUEST_TIMEOUT
    assert rows[0]["收盘"] == 1480.0


@pytest.mark.unit
def test_json_error_payload_raises():
    with pytest.raises(RuntimeError, match="请升级"):
        aknews._json_to_records({"error": "请升级 AKShare 到最新版本"})
    rows = aknews._json_to_records({"日期": ["2026-01-10"], "收盘": [10.0]})
    assert rows == [{"日期": "2026-01-10", "收盘": 10.0}]


@pytest.mark.unit
def test_stale_akshare_symbol_error_payload_raises():
    with pytest.raises(RuntimeError, match="000001"):
        aknews._json_to_records(
            {
                "error": (
                    "请输入正确的参数错误 '000001'，请升级 AKShare 到最新版本"
                    "并在文档中确认该接口的使用方式：https://www.akshare.xyz"
                )
            }
        )


@pytest.mark.unit
def test_ak_interface_missing_detects_not_found_payload():
    assert aknews._ak_interface_missing(
        RuntimeError('{"error":"未找到该接口，请升级 AKShare 到最新版本"}')
    )
    assert not aknews._ak_interface_missing(
        RuntimeError("请输入正确的参数错误 '601061.SH'")
    )


@pytest.mark.unit
def test_http_client_raises_on_http_error(monkeypatch):
    response = Mock()
    response.status_code = 404
    response.text = "not found"
    monkeypatch.setattr(aknews.requests, "get", lambda *a, **k: response)
    client = aknews.AktoolsHttpClient("http://127.0.0.1:8080")
    with pytest.raises(RuntimeError, match="404"):
        client.stock_news_em(symbol="600519")


@pytest.mark.unit
def test_loopback_aktools_url_rewritten_inside_docker(monkeypatch):
    monkeypatch.setattr(aknews, "_running_in_docker", lambda: True)
    monkeypatch.delenv("AKSHARE_BASE_URL", raising=False)
    monkeypatch.delenv("AKSHARE_DOCKER_HOST", raising=False)
    set_config({"akshare_base_url": "http://127.0.0.1:8080"})
    assert aknews.resolve_akshare_base_url() == "http://aktools:8080"


@pytest.mark.unit
def test_loopback_aktools_url_unchanged_on_host(monkeypatch):
    monkeypatch.setattr(aknews, "_running_in_docker", lambda: False)
    monkeypatch.delenv("AKSHARE_BASE_URL", raising=False)
    set_config({"akshare_base_url": "http://127.0.0.1:8080"})
    assert aknews.resolve_akshare_base_url() == "http://127.0.0.1:8080"
