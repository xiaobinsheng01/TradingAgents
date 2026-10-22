"""Shared graph runner emits events without placing orders."""

from cli.run_engine import MessageBuffer, apply_stream_chunk, build_run_config


def test_build_run_config_sets_models(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_MAX_RISK_ROUNDS", raising=False)
    cfg = build_run_config(
        {
            "research_depth": 3,
            "shallow_thinker": "quick-x",
            "deep_thinker": "deep-x",
            "backend_url": None,
            "llm_provider": "doubao",
            "output_language": "Chinese",
        },
        checkpoint=False,
        base_config={
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "quick_think_llm": "q",
            "deep_think_llm": "d",
            "backend_url": None,
            "llm_provider": "openai",
            "checkpoint_enabled": True,
            "google_thinking_level": None,
            "openai_reasoning_effort": None,
            "anthropic_effort": None,
            "output_language": "English",
        },
    )
    assert cfg["max_debate_rounds"] == 3
    assert cfg["quick_think_llm"] == "quick-x"
    assert cfg["llm_provider"] == "doubao"
    assert cfg["checkpoint_enabled"] is False
    assert cfg["output_language"] == "Chinese"


def test_build_run_config_sets_swing_tape_window(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_MAX_RISK_ROUNDS", raising=False)
    cfg = build_run_config(
        {
            "research_depth": 1,
            "shallow_thinker": "q",
            "deep_thinker": "d",
            "backend_url": None,
            "llm_provider": "openai",
            "output_language": "Chinese",
            "swing_tape_window": "half_year",
        },
        checkpoint=False,
        base_config={
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "quick_think_llm": "q",
            "deep_think_llm": "d",
            "backend_url": None,
            "llm_provider": "openai",
            "checkpoint_enabled": False,
            "google_thinking_level": None,
            "openai_reasoning_effort": None,
            "anthropic_effort": None,
            "output_language": "English",
            "swing_tape_window": "half_month",
        },
    )
    assert cfg["swing_tape_window"] == "half_year"


def test_apply_stream_chunk_records_market_report():
    buffer = MessageBuffer()
    buffer.init_for_analysis(["market"])
    apply_stream_chunk(buffer, {"market_report": "tape looks firm"})
    assert buffer.report_sections["market_report"] == "tape looks firm"
    assert buffer.agent_status["Market Analyst"] == "completed"
    assert buffer.agent_status["Bull Researcher"] == "in_progress"


def test_update_report_section_swing_tape_does_not_raise():
    buffer = MessageBuffer()
    buffer.init_for_analysis(["market"])
    buffer.update_report_section("swing_tape", "## Tape\nclose 10")
    assert "Swing Tape" in (buffer.current_report or "")
    assert "close 10" in (buffer.current_report or "")
    assert "close 10" in (buffer.final_report or "")
