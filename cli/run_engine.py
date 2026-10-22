"""Shared graph runner for the CLI Live display and the local web console.

Emits JSON-serializable events via ``on_event``. Does not place broker orders.
"""

from __future__ import annotations

import datetime
import logging
import os
import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from cli.models import AnalystType
from cli.stats_handler import StatsCallbackHandler
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.analyst_execution import (
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
    sync_analyst_tracker_from_chunk,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import reports_root, write_report_tree, write_run_meta

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]

ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}

_REPORT_EVENT_KEYS = (
    "swing_tape",
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)


class MessageBuffer:
    """In-memory agent/report progress used by CLI and the web console."""

    FIXED_AGENTS = {
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    ANALYST_MAPPING = {
        "market": "Market Analyst",
        "social": "Sentiment Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    REPORT_SECTIONS = {
        "swing_tape": (None, "Swing Tape"),
        "market_report": ("market", "Market Analyst"),
        "sentiment_report": ("social", "Sentiment Analyst"),
        "news_report": ("news", "News Analyst"),
        "fundamentals_report": ("fundamentals", "Fundamentals Analyst"),
        "investment_plan": (None, "Research Manager"),
        "trader_investment_plan": (None, "Trader"),
        "final_trade_decision": (None, "Portfolio Manager"),
    }

    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None
        self.agent_status = {}
        self.current_agent = None
        self.report_sections = {}
        self.selected_analysts = []
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        self.selected_analysts = [a.lower() for a in selected_analysts]
        self.agent_status = {}
        for analyst_key in self.selected_analysts:
            if analyst_key in self.ANALYST_MAPPING:
                self.agent_status[self.ANALYST_MAPPING[analyst_key]] = "pending"
        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"
        self.report_sections = {}
        for section, (analyst_key, _) in self.REPORT_SECTIONS.items():
            if analyst_key is None or analyst_key in self.selected_analysts:
                self.report_sections[section] = None
        self.current_report = None
        self.final_report = None
        self.current_agent = None
        self.messages.clear()
        self.tool_calls.clear()
        self._processed_message_ids.clear()

    def get_completed_reports_count(self):
        count = 0
        for section in self.report_sections:
            if section not in self.REPORT_SECTIONS:
                continue
            _, finalizing_agent = self.REPORT_SECTIONS[section]
            has_content = self.report_sections.get(section) is not None
            agent_done = self.agent_status.get(finalizing_agent) == "completed"
            if has_content and agent_done:
                count += 1
        return count

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        latest_section = None
        latest_content = None
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content
        if latest_section and latest_content:
            section_titles = {
                "swing_tape": "Swing Tape",
                "market_report": "Market Analysis",
                "sentiment_report": "Social Sentiment",
                "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
            }
            title = section_titles.get(latest_section, latest_section)
            self.current_report = f"### {title}\n{latest_content}"
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []
        if self.report_sections.get("swing_tape"):
            report_parts.append("## Swing Tape")
            report_parts.append(self.report_sections["swing_tape"])
        analyst_sections = [
            "market_report",
            "sentiment_report",
            "news_report",
            "fundamentals_report",
        ]
        if any(self.report_sections.get(section) for section in analyst_sections):
            report_parts.append("## Analyst Team Reports")
            if self.report_sections.get("market_report"):
                report_parts.append(
                    f"### Market Analysis\n{self.report_sections['market_report']}"
                )
            if self.report_sections.get("sentiment_report"):
                report_parts.append(
                    f"### Social Sentiment\n{self.report_sections['sentiment_report']}"
                )
            if self.report_sections.get("news_report"):
                report_parts.append(
                    f"### News Analysis\n{self.report_sections['news_report']}"
                )
            if self.report_sections.get("fundamentals_report"):
                report_parts.append(
                    f"### Fundamentals Analysis\n{self.report_sections['fundamentals_report']}"
                )
        if self.report_sections.get("investment_plan"):
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")
        if self.report_sections.get("trader_investment_plan"):
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")
        if self.report_sections.get("final_trade_decision"):
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")
        self.final_report = "\n\n".join(report_parts) if report_parts else None


def extract_content_string(content):
    """Extract string content from various message formats."""
    import ast

    def is_empty(val):
        if val is None or val == "":
            return True
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return True
            try:
                return not bool(ast.literal_eval(s))
            except (ValueError, SyntaxError):
                return False
        return not bool(val)

    if is_empty(content):
        return None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text", "")
        return text.strip() if not is_empty(text) else None
    if isinstance(content, list):
        text_parts = [
            item.get("text", "").strip()
            if isinstance(item, dict) and item.get("type") == "text"
            else (item.strip() if isinstance(item, str) else "")
            for item in content
        ]
        result = " ".join(t for t in text_parts if t and not is_empty(t))
        return result if result else None
    return str(content).strip() if not is_empty(content) else None


def classify_message_type(message) -> tuple[str, str | None]:
    """Classify LangChain message into display type and extract content."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    content = extract_content_string(getattr(message, "content", None))
    if isinstance(message, HumanMessage):
        if content and content.strip() == "Continue":
            return ("Control", content)
        return ("User", content)
    if isinstance(message, ToolMessage):
        return ("Data", content)
    if isinstance(message, AIMessage):
        return ("Agent", content)
    return ("System", content)


def update_research_team_status(buffer: MessageBuffer, status: str) -> None:
    for agent in ("Bull Researcher", "Bear Researcher", "Research Manager"):
        buffer.update_agent_status(agent, status)


def update_analyst_statuses(message_buffer, chunk, wall_time_tracker=None):
    """Update analyst statuses based on accumulated report state."""
    selected = message_buffer.selected_analysts
    found_active = False
    if wall_time_tracker is not None:
        sync_analyst_tracker_from_chunk(wall_time_tracker, chunk)
    for analyst_key in ANALYST_ORDER:
        if analyst_key not in selected:
            continue
        agent_name = ANALYST_AGENT_NAMES[analyst_key]
        report_key = ANALYST_REPORT_MAP[analyst_key]
        if chunk.get(report_key):
            message_buffer.update_report_section(report_key, chunk[report_key])
        has_report = bool(message_buffer.report_sections.get(report_key))
        if has_report:
            message_buffer.update_agent_status(agent_name, "completed")
        elif not found_active:
            message_buffer.update_agent_status(agent_name, "in_progress")
            found_active = True
        else:
            message_buffer.update_agent_status(agent_name, "pending")
    if (
        not found_active
        and selected
        and message_buffer.agent_status.get("Bull Researcher") == "pending"
    ):
        message_buffer.update_agent_status("Bull Researcher", "in_progress")


def build_run_config(
    selections: dict,
    checkpoint: bool | None,
    base_config: dict | None = None,
) -> dict:
    """Assemble the run config from selections, honoring env precedence."""
    config = dict(base_config if base_config is not None else DEFAULT_CONFIG)
    if not os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS"):
        config["max_debate_rounds"] = selections["research_depth"]
    if not os.environ.get("TRADINGAGENTS_MAX_RISK_ROUNDS"):
        config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"] = selections.get("anthropic_effort")
    config["output_language"] = selections.get("output_language", "English")
    window = selections.get("swing_tape_window") or config.get("swing_tape_window")
    if window:
        config["swing_tape_window"] = str(window)
    if checkpoint is not None:
        config["checkpoint_enabled"] = checkpoint
    return config


def _prefetch_swing_tape(ticker: str, analysis_date: str, window: str) -> str:
    from tradingagents.dataflows.symbol_utils import a_share_code

    if a_share_code(ticker) is None:
        return ""
    from tradingagents.dataflows.interface import route_to_vendor

    try:
        text = route_to_vendor(
            "get_ashare_swing_tape", ticker, analysis_date, window
        )
    except Exception as e:
        logger.warning("swing tape prefetch failed for %s: %s", ticker, e)
        return ""
    return str(text or "")


def _analyst_keys(selections: dict) -> list[str]:
    selected_set = set()
    for analyst in selections["analysts"]:
        value = analyst.value if isinstance(analyst, AnalystType) else str(analyst)
        selected_set.add(value)
    return [key for key in ANALYST_ORDER if key in selected_set]


def _emit(on_event: EventCallback | None, payload: dict[str, Any]) -> None:
    if on_event is None:
        return
    on_event(payload)


def apply_stream_chunk(
    buffer: MessageBuffer,
    chunk: dict,
    wall_time_tracker: AnalystWallTimeTracker | None = None,
) -> None:
    """Mutate ``buffer`` from one LangGraph stream chunk."""
    for message in chunk.get("messages", []):
        msg_id = getattr(message, "id", None)
        if msg_id is not None:
            if msg_id in buffer._processed_message_ids:
                continue
            buffer._processed_message_ids.add(msg_id)
        msg_type, content = classify_message_type(message)
        if content and content.strip():
            buffer.add_message(msg_type, content)
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tool_call in message.tool_calls:
                if isinstance(tool_call, dict):
                    buffer.add_tool_call(tool_call["name"], tool_call["args"])
                else:
                    buffer.add_tool_call(tool_call.name, tool_call.args)

    update_analyst_statuses(buffer, chunk, wall_time_tracker=wall_time_tracker)

    if chunk.get("investment_debate_state"):
        debate_state = chunk["investment_debate_state"]
        bull_hist = debate_state.get("bull_history", "").strip()
        bear_hist = debate_state.get("bear_history", "").strip()
        judge = debate_state.get("judge_decision", "").strip()
        if bull_hist or bear_hist:
            update_research_team_status(buffer, "in_progress")
        if bull_hist:
            buffer.update_report_section(
                "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
            )
        if bear_hist:
            buffer.update_report_section(
                "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
            )
        if judge:
            buffer.update_report_section(
                "investment_plan", f"### Research Manager Decision\n{judge}"
            )
            update_research_team_status(buffer, "completed")
            buffer.update_agent_status("Trader", "in_progress")

    if chunk.get("trader_investment_plan"):
        buffer.update_report_section(
            "trader_investment_plan", chunk["trader_investment_plan"]
        )
        if buffer.agent_status.get("Trader") != "completed":
            buffer.update_agent_status("Trader", "completed")
            buffer.update_agent_status("Aggressive Analyst", "in_progress")

    if chunk.get("risk_debate_state"):
        risk_state = chunk["risk_debate_state"]
        agg_hist = risk_state.get("aggressive_history", "").strip()
        con_hist = risk_state.get("conservative_history", "").strip()
        neu_hist = risk_state.get("neutral_history", "").strip()
        judge = risk_state.get("judge_decision", "").strip()
        if agg_hist:
            if buffer.agent_status.get("Aggressive Analyst") != "completed":
                buffer.update_agent_status("Aggressive Analyst", "in_progress")
            buffer.update_report_section(
                "final_trade_decision",
                f"### Aggressive Analyst Analysis\n{agg_hist}",
            )
        if con_hist:
            if buffer.agent_status.get("Conservative Analyst") != "completed":
                buffer.update_agent_status("Conservative Analyst", "in_progress")
            buffer.update_report_section(
                "final_trade_decision",
                f"### Conservative Analyst Analysis\n{con_hist}",
            )
        if neu_hist:
            if buffer.agent_status.get("Neutral Analyst") != "completed":
                buffer.update_agent_status("Neutral Analyst", "in_progress")
            buffer.update_report_section(
                "final_trade_decision",
                f"### Neutral Analyst Analysis\n{neu_hist}",
            )
        if judge and buffer.agent_status.get("Portfolio Manager") != "completed":
            buffer.update_agent_status("Portfolio Manager", "in_progress")
            buffer.update_report_section(
                "final_trade_decision",
                f"### Portfolio Manager Decision\n{judge}",
            )
            buffer.update_agent_status("Aggressive Analyst", "completed")
            buffer.update_agent_status("Conservative Analyst", "completed")
            buffer.update_agent_status("Neutral Analyst", "completed")
            buffer.update_agent_status("Portfolio Manager", "completed")


def run_graph_with_events(
    selections: dict,
    *,
    checkpoint: bool | None = None,
    on_event: EventCallback | None = None,
    message_buffer: MessageBuffer | None = None,
    stats_handler: StatsCallbackHandler | None = None,
    base_config: dict | None = None,
    save_report: bool = True,
) -> dict[str, Any]:
    """Run ``TradingAgentsGraph.stream`` and emit progress events.

    Returns a dict with ``final_state``, ``decision``, ``report_path``, and
    ``wall_time_summary``. Research rating only — never a broker order.
    """
    config = build_run_config(selections, checkpoint, base_config=base_config)
    stats_handler = stats_handler or StatsCallbackHandler()
    buffer = message_buffer or MessageBuffer()
    selected_analyst_keys = _analyst_keys(selections)
    analyst_execution_plan = build_analyst_execution_plan(selected_analyst_keys)
    analyst_wall_time_tracker = AnalystWallTimeTracker(analyst_execution_plan)

    graph = TradingAgentsGraph(
        selected_analyst_keys,
        config=config,
        debug=True,
        callbacks=[stats_handler],
    )
    buffer.init_for_analysis(selected_analyst_keys)

    ticker = safe_ticker_component(str(selections["ticker"]))
    analysis_date = str(selections["analysis_date"])
    asset_type = selections.get("asset_type") or "stock"
    if hasattr(asset_type, "value"):
        asset_type = asset_type.value

    results_dir = Path(config["results_dir"]) / ticker / analysis_date
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    orig_add_message = buffer.add_message
    orig_add_tool = buffer.add_tool_call
    orig_update_report = buffer.update_report_section

    @wraps(orig_add_message)
    def add_message(message_type, content):
        orig_add_message(message_type, content)
        timestamp, logged_type, logged_content = buffer.messages[-1]
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(
                f"{timestamp} [{logged_type}] {str(logged_content).replace(chr(10), ' ')}\n"
            )
        _emit(
            on_event,
            {
                "type": "message",
                "message_type": logged_type,
                "content": str(logged_content),
                "agents": dict(buffer.agent_status),
                "stats": stats_handler.get_stats(),
            },
        )

    @wraps(orig_add_tool)
    def add_tool_call(tool_name, args):
        orig_add_tool(tool_name, args)
        timestamp, name, logged_args = buffer.tool_calls[-1]
        args_str = ", ".join(f"{key}={value}" for key, value in logged_args.items())
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} [Tool Call] {name}({args_str})\n")
        _emit(
            on_event,
            {
                "type": "tool",
                "name": name,
                "args": {str(key): str(value) for key, value in logged_args.items()},
                "agents": dict(buffer.agent_status),
                "stats": stats_handler.get_stats(),
            },
        )

    @wraps(orig_update_report)
    def update_report_section(section_name, content):
        orig_update_report(section_name, content)
        stored = buffer.report_sections.get(section_name)
        if stored:
            text = (
                "\n".join(str(item) for item in stored)
                if isinstance(stored, list)
                else stored
            )
            (report_dir / f"{section_name}.md").write_text(text, encoding="utf-8")
            _emit(
                on_event,
                {
                    "type": "report",
                    "section": section_name,
                    "content": text,
                    "agents": dict(buffer.agent_status),
                    "stats": stats_handler.get_stats(),
                },
            )

    buffer.add_message = add_message
    buffer.add_tool_call = add_tool_call
    buffer.update_report_section = update_report_section

    start_time = time.time()
    _emit(
        on_event,
        {
            "type": "started",
            "ticker": ticker,
            "analysis_date": analysis_date,
            "analysts": selected_analyst_keys,
            "notice": "Research rating only — this run does not place broker orders.",
            "agents": dict(buffer.agent_status),
        },
    )

    buffer.add_message("System", f"Selected ticker: {ticker}")
    if asset_type != "stock":
        buffer.add_message("System", f"Detected asset type: {asset_type}")
    buffer.add_message("System", f"Analysis date: {analysis_date}")
    buffer.add_message(
        "System",
        f"Selected analysts: {', '.join(selected_analyst_keys)}",
    )

    first_analyst = get_initial_analyst_node(analyst_execution_plan)
    buffer.update_agent_status(first_analyst, "in_progress")
    analyst_wall_time_tracker.mark_started(selected_analyst_keys[0])
    _emit(
        on_event,
        {
            "type": "agents",
            "agents": dict(buffer.agent_status),
            "stats": stats_handler.get_stats(),
        },
    )

    instrument_context = graph.resolve_instrument_context(
        ticker, asset_type, analysis_date
    )
    swing_window = str(
        selections.get("swing_tape_window")
        or config.get("swing_tape_window")
        or "half_month"
    )
    swing_tape = _prefetch_swing_tape(ticker, analysis_date, swing_window)
    init_agent_state = graph.propagator.create_initial_state(
        ticker,
        analysis_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    if swing_tape:
        init_agent_state["messages"] = [("human", f"{ticker}\n\n{swing_tape}")]
        buffer.update_report_section("swing_tape", swing_tape)
    args = graph.propagator.get_graph_args(callbacks=[stats_handler])
    checkpoint_tid = graph.begin_checkpoint(ticker, analysis_date, asset_type)
    if checkpoint_tid is not None:
        args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = (
            checkpoint_tid
        )

    trace: list[dict] = []
    try:
        try:
            for chunk in graph.graph.stream(
                graph.checkpoint_input(init_agent_state), **args
            ):
                apply_stream_chunk(
                    buffer, chunk, wall_time_tracker=analyst_wall_time_tracker
                )
                _emit(
                    on_event,
                    {
                        "type": "agents",
                        "agents": dict(buffer.agent_status),
                        "stats": stats_handler.get_stats(),
                        "elapsed_seconds": int(time.time() - start_time),
                    },
                )
                trace.append(chunk)
            graph.clear_checkpoint_on_success(ticker, analysis_date, asset_type)
        finally:
            graph.end_checkpoint()

        final_state: dict[str, Any] = {}
        for chunk in trace:
            final_state.update(chunk)
        if swing_tape:
            final_state.setdefault("swing_tape", swing_tape)
        for agent in buffer.agent_status:
            buffer.update_agent_status(agent, "completed")
        buffer.add_message("System", f"Completed analysis for {analysis_date}")
        buffer.add_message("System", analyst_wall_time_tracker.format_summary())
        for section in buffer.report_sections:
            if section in final_state:
                buffer.update_report_section(section, final_state[section])

        report_path = None
        if save_report:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = reports_root(config["results_dir"]) / f"{ticker}_{stamp}"
            report_file = write_report_tree(final_state, ticker, save_path)
            write_run_meta(save_path, ticker=ticker, analysis_date=analysis_date)
            report_path = str(report_file)

        reports = {
            key: buffer.report_sections.get(key)
            for key in _REPORT_EVENT_KEYS
            if buffer.report_sections.get(key)
        }
        decision = str(final_state.get("final_trade_decision") or "")
        _emit(
            on_event,
            {
                "type": "complete",
                "ticker": ticker,
                "analysis_date": analysis_date,
                "decision": decision,
                "reports": reports,
                "report_path": report_path,
                "agents": dict(buffer.agent_status),
                "stats": stats_handler.get_stats(),
                "wall_time_summary": analyst_wall_time_tracker.format_summary(),
                "notice": "Research rating only — this run does not place broker orders.",
            },
        )
        return {
            "final_state": final_state,
            "decision": decision,
            "report_path": report_path,
            "wall_time_summary": analyst_wall_time_tracker.format_summary(),
            "reports": reports,
        }
    except Exception as exc:
        logger.exception("Graph run failed for %s as-of %s", ticker, analysis_date)
        _emit(on_event, {"type": "error", "message": str(exc)})
        raise
    finally:
        buffer.add_message = orig_add_message
        buffer.add_tool_call = orig_add_tool
        buffer.update_report_section = orig_update_report
