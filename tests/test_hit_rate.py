"""Directional hit rate from the memory log — research scorecard only."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tradingagents.agents.utils.hit_rate import parse_logged_pct, summarize_memory_log
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.default_config import DEFAULT_CONFIG


def _log(tmp_path: Path) -> TradingMemoryLog:
    path = tmp_path / "trading_memory.md"
    return TradingMemoryLog({**DEFAULT_CONFIG, "memory_log_path": str(path)})


@pytest.mark.unit
def test_parse_logged_pct_handles_plus_and_minus():
    assert parse_logged_pct("+4.2%") == pytest.approx(0.042)
    assert parse_logged_pct("-1.0%") == pytest.approx(-0.01)
    assert parse_logged_pct("pending") is None


@pytest.mark.unit
def test_summarize_counts_buy_up_and_sell_down_as_hits(tmp_path):
    log = _log(tmp_path)
    log.store_decision("601061.SH", "2026-01-05", "Rating: Buy")
    log.store_decision("601061.SH", "2026-01-06", "Rating: Sell")
    log.store_decision("601061.SH", "2026-01-07", "Rating: Hold")
    log.store_decision("AAPL", "2026-01-05", "Rating: Buy")
    log.update_with_outcome("601061.SH", "2026-01-05", 0.04, 0.01, 5, "up")
    log.update_with_outcome("601061.SH", "2026-01-06", -0.02, -0.01, 5, "down")
    log.update_with_outcome("601061.SH", "2026-01-07", 0.08, 0.05, 5, "hold")
    summary = summarize_memory_log(log, ticker="601061.SH")
    assert summary["pending"] == 0
    assert summary["resolved"] == 3
    assert summary["hold_5d_directional"] == 2
    assert summary["hold_5d_hits"] == 2
    assert summary["hold_5d_hit_rate"] == 1.0
    assert summary["hold_5d_mean_raw"] == pytest.approx((0.04 - 0.02 + 0.08) / 3)
    assert summary["t1_hit_rate"] is None
    assert summary["hit_rate"] is None


@pytest.mark.unit
def test_summarize_excludes_pending_from_hit_rate(tmp_path):
    log = _log(tmp_path)
    log.store_decision("601061.SH", "2026-01-05", "Rating: Buy")
    summary = summarize_memory_log(log)
    assert summary["pending"] == 1
    assert summary["hit_rate"] is None
    assert summary["hold_5d_hit_rate"] is None


@pytest.mark.unit
def test_summarize_t1_scores_pending_when_next_bar_exists(tmp_path):
    log = _log(tmp_path)
    log.store_decision("601061.SH", "2026-01-05", "Rating: Buy")
    summary = summarize_memory_log(
        log,
        next_session_loader=lambda ticker, date: (0.04, "2026-01-06"),
    )
    assert summary["pending"] == 1
    assert summary["t1_hit_rate"] == 1.0
    assert summary["t1_mean_raw"] == pytest.approx(0.04)
    assert summary["hold_5d_hit_rate"] is None
    assert summary["entries"][0]["t1_date"] == "2026-01-06"


@pytest.mark.unit
def test_score_cli_prints_hit_rate(tmp_path, monkeypatch):
    import cli.main as cli_main

    log = _log(tmp_path)
    log.store_decision("601061.SH", "2026-01-05", "Rating: Buy")
    monkeypatch.setattr(
        cli_main,
        "DEFAULT_CONFIG",
        {**DEFAULT_CONFIG, "memory_log_path": str(tmp_path / "trading_memory.md")},
    )
    monkeypatch.setattr(
        "tradingagents.agents.utils.hit_rate.fetch_next_session_return",
        lambda ticker, date: (0.04, "2026-01-06"),
    )
    result = CliRunner().invoke(cli_main.app, ["score", "601061.SH"])
    assert result.exit_code == 0, result.output
    assert "T+1" in result.output
    assert "hit rate" in result.output
    assert "100%" in result.output
    assert "Never a broker order" in result.output
    assert "5d settled" in result.output
