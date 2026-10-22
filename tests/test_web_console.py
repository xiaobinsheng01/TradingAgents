"""Local web console: options, validation, mutex, mocked SSE."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cli.main import app as cli_app
from cli.models import AnalystType
from web.app import create_app, selections_from_request
from web.schemas import RunRequest
from web.server import assert_loopback_host


def _payload(**overrides) -> dict:
    body = {
        "ticker": "AAPL",
        "analysis_date": "2026-05-08",
        "output_language": "English",
        "analysts": ["market", "news"],
        "research_depth": 1,
        "llm_provider": "openai",
        "shallow_thinker": "gpt-5.6-luna",
        "deep_thinker": "gpt-5.6",
        "ingest_news": False,
    }
    body.update(overrides)
    return body


def test_options_omits_secrets_and_lists_analysts():
    client = TestClient(create_app())
    response = client.get("/api/options")
    assert response.status_code == 200
    data = response.json()
    assert "market" in {row["key"] for row in data["analysts"]}
    assert data["notice"]
    assert {row["key"] for row in data["swing_windows"]} == {
        "half_month",
        "three_months",
        "half_year",
    }
    assert data["defaults"]["swing_tape_window"] in {
        "half_month",
        "three_months",
        "half_year",
    }
    assert data["defaults"]["output_language"] == "Chinese"
    assert "-USD" in data["crypto_suffixes"]
    blob = json.dumps(data)
    assert "sk-" not in blob
    assert "ARK_API_KEY" in blob  # env var name only
    for provider in data["providers"]:
        assert "key_configured" in provider
        assert provider.get("api_key") is None


def test_index_serves_local_console_copy():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "永不下单" in response.text
    assert "查询最近一次分析" in response.text
    assert "窗口内新闻/公告" in response.text
    assert "缠论分型" in response.text
    assert "大盘筛选" in response.text
    assert "大盘走势" in response.text
    assert "趋势预测" in response.text
    assert "近3个月" in response.text
    assert "读取大盘走势" in response.text
    assert "扫描涨幅与涨速" in response.text
    assert response.text.index('id="index-table"') < response.text.index('id="index-chart"')
    assert "lightweight-charts.standalone.production.js" in response.text
    assert "带入全图分析" in response.text
    assert response.text.index('id="screen-table"') < response.text.index('id="screen-chart"')
    assert "5分钟" in response.text
    assert "sk-" not in response.text


def test_boot_script_reports_options_load_failure():
    js = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "无法加载选项" in js
    assert "web-ui" in js
    assert "开始价量分析" in js
    assert "正在读取当天公开榜单" in js
    assert "主板前排" in js
    assert "现货榜没有返回" in js
    assert "view-screen" in js
    assert "view-index" in js
    assert "/api/index-outlook" in js
    assert "/api/trend-predict" in js
    assert "/api/tomorrow-rise" in js
    assert "view-trend" in js
    assert "view-tomorrow-rise" in js
    assert "正在读取当天指数日线" in js
    assert "swing_tape_window" in js
    assert 'TAPE_ANALYSTS = ["market", "news", "fundamentals"]' in js
    assert "payload.ingest_news = true" in js
    assert 'upColor: QUOTE_UP' in js
    assert 'const QUOTE_UP = "#e5484d"' in js
    assert 'const QUOTE_DOWN = "#16a36a"' in js
    css = Path("web/static/styles.css").read_text(encoding="utf-8")
    assert "--up: #e5484d" in css
    assert "--down: #16a36a" in css
    assert ".bias-buy { color: var(--up);" in css
    page = Path("web/static/index.html").read_text(encoding="utf-8")
    assert "红涨" in page
    assert "绿跌" in page


def test_screen_returns_rows_without_secrets(monkeypatch):
    monkeypatch.setattr(
        "web.app.screen_main_board",
        lambda as_of: {
            "as_of": as_of or "2026-09-22",
            "universe": "main",
            "rows": [{"ticker": "600519.SH", "name": "贵州茅台"}],
            "note": "研究评级，永不下单",
        },
    )
    client = TestClient(create_app())
    response = client.get("/api/screen")
    assert response.status_code == 200
    blob = response.text
    assert "600519.SH" in blob
    assert "sk-" not in blob
    assert "api_key" not in blob


def test_screen_bars_reject_chinext():
    client = TestClient(create_app())
    response = client.get("/api/screen/bars", params={"ticker": "300001"})
    assert response.status_code == 400
    assert "创业板" in response.json()["detail"]


def test_tomorrow_rise_returns_buy_rows_without_secrets(monkeypatch):
    monkeypatch.setattr(
        "web.app.screen_tomorrow_rise",
        lambda as_of: {
            "as_of": as_of or "2026-09-22",
            "universe": "no_chinext",
            "rows": [{"ticker": "688001.SH", "name": "科创甲", "t1_bias": "BUY"}],
            "note": "研究评级，永不下单",
        },
    )
    client = TestClient(create_app())
    response = client.get("/api/tomorrow-rise")
    assert response.status_code == 200
    blob = response.text
    assert "688001.SH" in blob
    assert "sk-" not in blob


def test_screen_rejects_historical_date():
    client = TestClient(create_app())
    response = client.get("/api/screen", params={"as_of": "2020-01-02"})
    assert response.status_code == 400
    assert "当天" in response.json()["detail"]


def test_index_outlook_returns_rows_without_secrets(monkeypatch):
    monkeypatch.setattr(
        "web.app.index_outlook",
        lambda as_of: {
            "as_of": as_of or "2026-10-15",
            "benchmark": "sh000300",
            "rows": [{"symbol": "sh000300", "name": "沪深300", "t1_bias": "HOLD"}],
            "note": "研究评级，永不下单",
        },
    )
    client = TestClient(create_app())
    response = client.get("/api/index-outlook")
    assert response.status_code == 200
    blob = response.text
    assert "sh000300" in blob
    assert "sk-" not in blob
    assert "api_key" not in blob


def test_index_outlook_rejects_historical_date():
    client = TestClient(create_app())
    response = client.get("/api/index-outlook", params={"as_of": "2020-01-02"})
    assert response.status_code == 400
    assert "当天" in response.json()["detail"]


def test_index_bars_reject_a_share_code():
    client = TestClient(create_app())
    response = client.get("/api/index-outlook/bars", params={"symbol": "600519"})
    assert response.status_code == 400
    assert "指数" in response.json()["detail"]


def test_run_request_keeps_shanghai_broker_suffix():
    body = RunRequest(ticker="601061.SH", analysts=["market"])
    assert body.ticker == "601061.SH"


def test_empty_analysts_rejected():
    with pytest.raises(ValueError, match="at least one analyst"):
        RunRequest(ticker="AAPL", analysts=[])


def test_swing_tape_window_must_be_known():
    with pytest.raises(ValueError, match="half_month"):
        RunRequest(ticker="600519.SS", analysts=["market"], swing_tape_window="decade")


def test_trend_predict_endpoint(monkeypatch):
    from web.schemas import TrendPredictRequest

    client = TestClient(create_app())
    monkeypatch.setattr(
        "web.app.stock_trend_predict",
        lambda tickers, as_of=None, window=None: {
            "as_of": datetime.now().strftime("%Y-%m-%d"),
            "window": window or "three_months",
            "window_label": "近3个月",
            "rows": [{"ticker": tickers[0], "trend_bias": "HOLD"}],
            "errors": [],
            "note": "研究评级",
        },
    )
    body = TrendPredictRequest(
        tickers="002487.SZ, 002081.SZ",
        swing_tape_window="three_months",
        as_of=datetime.now().strftime("%Y-%m-%d"),
    )
    response = client.post("/api/trend-predict", json=body.model_dump())
    assert response.status_code == 200
    data = response.json()
    assert data["window"] == "three_months"
    assert len(data["rows"]) == 1


def test_crypto_selections_drop_fundamentals():
    body = RunRequest(
        ticker="BTC-USD",
        analysis_date="2026-01-10",
        analysts=["market", "fundamentals"],
    )
    selections = selections_from_request(body)
    assert AnalystType.FUNDAMENTALS not in selections["analysts"]
    assert AnalystType.MARKET in selections["analysts"]


def test_future_date_rejected():
    with pytest.raises(ValueError, match="future"):
        RunRequest(ticker="AAPL", analysts=["market"], analysis_date="2099-01-01")


def test_missing_key_returns_400(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app(run_fn=lambda **_k: {}))
    response = client.post("/api/runs", json=_payload())
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_second_run_returns_409():
    app = create_app(run_fn=lambda **_k: {})
    assert app.state.run_lock.acquire(blocking=False)
    try:
        client = TestClient(app)
        response = client.post("/api/runs", json=_payload())
        assert response.status_code == 409
    finally:
        app.state.run_lock.release()


def test_sse_emits_started_then_complete(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder")

    def fake_run(selections, **kwargs):
        on_event = kwargs["on_event"]
        on_event({"type": "started", "ticker": selections["ticker"], "agents": {}})
        on_event(
            {
                "type": "complete",
                "decision": "HOLD",
                "reports": {"market_report": "ok"},
                "agents": {"Market Analyst": "completed"},
            }
        )
        return {"final_state": {}, "decision": "HOLD", "reports": {}}

    client = TestClient(create_app(run_fn=fake_run))
    with client.stream("POST", "/api/runs", json=_payload()) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert '"type": "started"' in body
    assert '"type": "complete"' in body
    assert "HOLD" in body


def test_web_refuses_non_loopback_bind():
    with pytest.raises(RuntimeError, match="loopback-only"):
        assert_loopback_host("0.0.0.0")
    assert_loopback_host("127.0.0.1")
    assert_loopback_host("localhost")


def test_bind_all_allows_docker_unspecified(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_WEB_BIND_ALL", "1")
    assert_loopback_host("0.0.0.0")
    with pytest.raises(RuntimeError, match="loopback-only"):
        assert_loopback_host("192.168.1.10")


def test_api_only_skips_frontend():
    client = TestClient(create_app(serve_frontend=False, run_fn=lambda **_k: {}))
    assert client.get("/").status_code == 404
    assert client.get("/api/options").status_code == 200


def test_latest_run_404_when_empty(tmp_path):
    client = TestClient(create_app(results_dir=tmp_path, serve_frontend=False))
    response = client.get("/api/runs/latest")
    assert response.status_code == 404
    assert "No saved analysis" in response.json()["detail"]


def test_latest_run_returns_newest_saved_tree(tmp_path, monkeypatch):
    from tradingagents.reporting import write_report_tree, write_run_meta

    monkeypatch.chdir(tmp_path)
    first = tmp_path / "reports" / "AAPL_20260101_010101"
    second = tmp_path / "reports" / "601061.SH_20260920_150000"
    write_report_tree(
        {
            "market_report": "old market",
            "risk_debate_state": {"judge_decision": "OLD HOLD"},
        },
        "AAPL",
        first,
    )
    write_run_meta(first, ticker="AAPL", analysis_date="2026-01-01")
    write_report_tree(
        {
            "market_report": "new market",
            "fundamentals_report": "filings",
            "risk_debate_state": {"judge_decision": "NEW HOLD"},
        },
        "601061.SH",
        second,
    )
    write_run_meta(second, ticker="601061.SH", analysis_date="2026-09-20")
    client = TestClient(create_app(results_dir=tmp_path, serve_frontend=False))
    response = client.get("/api/runs/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "601061.SH"
    assert data["reports"]["market_report"] == "new market"
    assert data["decision"] == "NEW HOLD"
    by_ticker = client.get("/api/runs/latest", params={"ticker": "AAPL"})
    assert by_ticker.status_code == 200
    assert by_ticker.json()["ticker"] == "AAPL"


def test_latest_run_rejects_unsafe_ticker(tmp_path):
    client = TestClient(create_app(results_dir=tmp_path, serve_frontend=False))
    response = client.get("/api/runs/latest", params={"ticker": "../etc"})
    assert response.status_code == 400


def test_compose_file_defines_split_web_services():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    nginx = Path("web/nginx.conf.template").read_text(encoding="utf-8")
    assert "web-api:" in compose
    assert "web-ui:" in compose
    assert "127.0.0.1:8000:80" in compose
    assert "127.0.0.1:8001:8000" in compose
    assert "AS frontend" in dockerfile
    assert "AS backend" in dockerfile
    assert "proxy_buffering off" in nginx
    assert "${WEB_API_UPSTREAM}" in nginx
    assert "resolver 127.0.0.11" in nginx
    assert "proxy_pass http://$tradingagents_web_api" in nginx
    assert "AKSHARE_BASE_URL: http://aktools:8080" in compose


def test_web_cli_help_is_registered():
    result = CliRunner().invoke(cli_app, ["web", "--help"])
    assert result.exit_code == 0
    assert "127.0.0.1" in result.output
    assert "loopback" in result.output.lower() or "local" in result.output.lower()
    assert "--api-only" in result.output
