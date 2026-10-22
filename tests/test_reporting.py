"""Report parity: the shared writer produces the report tree for the CLI and the
programmatic API alike (#1037)."""

from types import SimpleNamespace

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree


def _state():
    return {
        "swing_tape": "SWING",
        "market_report": "MKT",
        "news_report": "NEWS",
        "investment_debate_state": {"judge_decision": "RM PLAN"},
        "trader_investment_plan": "TRADE",
        "risk_debate_state": {"judge_decision": "PM DECISION"},
    }


@pytest.mark.unit
def test_write_report_tree_creates_files(tmp_path):
    out = write_report_tree(_state(), "AAPL", tmp_path)
    assert out.name == "complete_report.md"
    assert (tmp_path / "1_analysts" / "market.md").read_text() == "MKT"
    assert (tmp_path / "1_analysts" / "swing_tape.md").read_text() == "SWING"
    assert (tmp_path / "1_analysts" / "news.md").read_text() == "NEWS"
    assert (tmp_path / "2_research" / "manager.md").read_text() == "RM PLAN"
    assert (tmp_path / "3_trading" / "trader.md").read_text() == "TRADE"
    assert (tmp_path / "5_portfolio" / "decision.md").read_text() == "PM DECISION"
    complete = out.read_text()
    assert "Trading Analysis Report: AAPL" in complete
    assert "MKT" in complete and "PM DECISION" in complete


@pytest.mark.unit
def test_save_reports_explicit_path(tmp_path):
    # Unbound: with an explicit save_path, the method doesn't touch self/config.
    out = TradingAgentsGraph.save_reports(None, _state(), "AAPL", save_path=tmp_path)
    assert (tmp_path / "complete_report.md").exists()
    assert out == tmp_path / "complete_report.md"


@pytest.mark.unit
def test_save_reports_defaults_under_results_dir(tmp_path):
    mock_self = SimpleNamespace(config={"results_dir": str(tmp_path)})
    out = TradingAgentsGraph.save_reports(mock_self, _state(), "AAPL")
    assert out.exists()
    assert out.parent.parent.name == "reports"  # results_dir/reports/AAPL_<stamp>/...
    assert out.parent.name.startswith("AAPL_")


@pytest.mark.unit
def test_load_latest_run_picks_newest_tree(tmp_path, monkeypatch):
    from tradingagents.reporting import (
        load_latest_run,
        write_report_tree,
        write_run_meta,
    )

    monkeypatch.chdir(tmp_path)
    older = tmp_path / "reports" / "AAPL_20260101_010101"
    newer = tmp_path / "reports" / "601061.SH_20260920_140000"
    write_report_tree(_state(), "AAPL", older)
    write_run_meta(older, ticker="AAPL", analysis_date="2026-01-01")
    write_report_tree(_state(), "601061.SH", newer)
    write_run_meta(newer, ticker="601061.SH", analysis_date="2026-09-20")
    payload = load_latest_run(tmp_path)
    assert payload is not None
    assert payload["ticker"] == "601061.SH"
    assert payload["analysis_date"] == "2026-09-20"
    assert payload["reports"]["market_report"] == "MKT"
    assert payload["decision"] == "PM DECISION"
    filtered = load_latest_run(tmp_path, ticker="AAPL")
    assert filtered is not None
    assert filtered["ticker"] == "AAPL"


@pytest.mark.unit
def test_load_latest_run_rejects_path_escape(tmp_path):
    from tradingagents.reporting import load_latest_run

    with pytest.raises(ValueError, match="filesystem path"):
        load_latest_run(tmp_path, ticker="../etc")
