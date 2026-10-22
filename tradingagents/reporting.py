"""Reusable report-tree writer shared by the CLI and the programmatic API.

Writes a run's per-section markdown (analysts, research, trading, risk,
portfolio) plus a consolidated ``complete_report.md`` under ``save_path``. The
CLI and ``TradingAgentsGraph.save_reports`` both call this, so a headless / API
run produces the same on-disk report tree a CLI run does.

Lookup of the newest tree is file-based (no ORM). Saved runs live under
``results_dir/reports/<ticker>_<stamp>/``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component

logger = logging.getLogger(__name__)

_RUN_STAMP_RE = re.compile(r"^(?P<ticker>.+)_(?P<stamp>\d{8}_\d{6})$")
_META_NAME = "run_meta.json"
_COMPLETE_NAME = "complete_report.md"

# UI / SSE report keys → files written by write_report_tree.
_SECTION_FILES: tuple[tuple[str, str], ...] = (
    ("swing_tape", "1_analysts/swing_tape.md"),
    ("market_report", "1_analysts/market.md"),
    ("sentiment_report", "1_analysts/sentiment.md"),
    ("news_report", "1_analysts/news.md"),
    ("fundamentals_report", "1_analysts/fundamentals.md"),
    ("investment_plan", "2_research/manager.md"),
    ("trader_investment_plan", "3_trading/trader.md"),
    ("final_trade_decision", "5_portfolio/decision.md"),
)


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """Save a completed run's reports to ``save_path``; return the complete-report path."""
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("swing_tape"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "swing_tape.md").write_text(
            final_state["swing_tape"], encoding="utf-8"
        )
        analyst_parts.append(("Swing Tape", final_state["swing_tape"]))
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Sentiment Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / _COMPLETE_NAME).write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / _COMPLETE_NAME


def reports_root(results_dir) -> Path:
    """Canonical tree: ``results_dir/reports/<ticker>_<stamp>/``."""
    return Path(results_dir) / "reports"


def write_run_meta(
    save_path,
    *,
    ticker: str,
    analysis_date: str | None = None,
) -> Path:
    """Small sidecar so latest-run lookup keeps ticker/date without re-parsing markdown."""
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = save_path / _META_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_report_tree(save_path) -> dict[str, str]:
    """Rebuild the SSE ``reports`` map from a ``write_report_tree`` directory."""
    root = Path(save_path)
    reports: dict[str, str] = {}
    for key, rel in _SECTION_FILES:
        path = root / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                reports[key] = text
    return reports


def _stamp_mtime(folder: Path) -> float:
    complete = folder / _COMPLETE_NAME
    try:
        return complete.stat().st_mtime
    except OSError:
        return folder.stat().st_mtime


def _parse_run_dir_name(name: str) -> tuple[str, str] | None:
    match = _RUN_STAMP_RE.fullmatch(name)
    if match is None:
        return None
    return match.group("ticker"), match.group("stamp")


def _iter_report_dirs(results_dir) -> list[Path]:
    configured = reports_root(results_dir)
    roots = [configured]
    cwd_root = Path.cwd() / "reports"
    try:
        if cwd_root.resolve() != configured.resolve():
            roots.append(cwd_root)
    except OSError:
        roots.append(cwd_root)
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError as e:
            logger.warning("cannot list report dir %s: %s", root, e)
            continue
        for child in children:
            if child.is_dir() and (child / _COMPLETE_NAME).is_file():
                found.append(child)
    return found


def load_latest_run(
    results_dir,
    ticker: str | None = None,
) -> dict[str, Any] | None:
    """Newest complete report tree under ``results_dir/reports`` (and cwd fallback).

    Optional ``ticker`` is validated with ``safe_ticker_component`` then matched
    as a directory-name prefix. Missing runs return ``None``.
    """
    wanted: str | None = None
    if ticker is not None and str(ticker).strip():
        wanted = safe_ticker_component(str(ticker).strip())
    candidates = _iter_report_dirs(results_dir)
    if wanted is not None:
        prefix = f"{wanted}_"
        candidates = [path for path in candidates if path.name.startswith(prefix)]
    if not candidates:
        return None
    folder = max(candidates, key=_stamp_mtime)
    reports = read_report_tree(folder)
    meta: dict[str, Any] = {}
    meta_path = folder / _META_NAME
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("run_meta.json unreadable in %s: %s", folder, e)
        else:
            if isinstance(loaded, dict):
                meta = loaded
    parsed = _parse_run_dir_name(folder.name)
    ticker_out = str(meta.get("ticker") or (parsed[0] if parsed else folder.name))
    analysis_date = meta.get("analysis_date")
    generated_at = meta.get("generated_at")
    complete = folder / _COMPLETE_NAME
    if complete.is_file():
        reports["complete_report"] = complete.read_text(encoding="utf-8")
    return {
        "ticker": ticker_out,
        "analysis_date": analysis_date,
        "generated_at": generated_at,
        "decision": reports.get("final_trade_decision") or "",
        "reports": reports,
        "report_path": str(complete),
        "notice": "Research rating only — this run does not place broker orders.",
    }
