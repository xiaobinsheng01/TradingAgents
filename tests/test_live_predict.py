"""On-demand live prediction CLI: research rating, never an order."""

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from cli.models import AnalystType
from cli.utils import build_live_predict_selections


@pytest.mark.unit
def test_live_predict_selections_skip_fundamentals():
    sel = build_live_predict_selections("600519.SS", analysis_date="2026-01-10")
    assert sel["ticker"] == "600519.SS"
    assert sel["analysis_date"] == "2026-01-10"
    assert sel["output_language"] == "Chinese"
    values = {analyst.value for analyst in sel["analysts"]}
    assert values == {
        AnalystType.MARKET.value,
        AnalystType.SOCIAL.value,
        AnalystType.NEWS.value,
    }
    assert AnalystType.FUNDAMENTALS.value not in values


@pytest.mark.unit
def test_live_predict_selections_reject_future_date():
    with pytest.raises(ValueError, match="future"):
        build_live_predict_selections("600519.SS", analysis_date="2099-01-01")


@pytest.mark.unit
def test_predict_cli_does_not_place_orders(monkeypatch):
    captured: dict = {}

    def fake_run(*, checkpoint, selections, prompt_after):
        captured["selections"] = selections
        captured["prompt_after"] = prompt_after
        captured["checkpoint"] = checkpoint

    monkeypatch.setattr(cli_main, "run_analysis", fake_run)
    monkeypatch.setattr(cli_main, "ensure_api_key", lambda _provider: "ok")
    monkeypatch.setattr(
        "tradingagents.dataflows.news_ingest.ingest_news",
        lambda **_kwargs: [],
    )
    result = CliRunner().invoke(
        cli_main.app, ["predict", "600519.SS", "--date", "2026-01-10"]
    )
    assert result.exit_code == 0, result.output
    assert "never a broker order" in result.output
    assert captured["prompt_after"] is False
    values = {analyst.value for analyst in captured["selections"]["analysts"]}
    assert "fundamentals" not in values


@pytest.mark.unit
def test_predict_cli_can_skip_ingest(monkeypatch):
    called = {"ingest": False}

    def fake_ingest(**_kwargs):
        called["ingest"] = True
        return []

    monkeypatch.setattr(cli_main, "run_analysis", lambda **_k: None)
    monkeypatch.setattr(cli_main, "ensure_api_key", lambda _provider: "ok")
    monkeypatch.setattr("tradingagents.dataflows.news_ingest.ingest_news", fake_ingest)
    result = CliRunner().invoke(
        cli_main.app,
        ["predict", "600519.SS", "--date", "2026-01-10", "--no-ingest"],
    )
    assert result.exit_code == 0, result.output
    assert called["ingest"] is False
