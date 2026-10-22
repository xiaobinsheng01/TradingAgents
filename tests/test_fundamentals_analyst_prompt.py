"""Fundamentals analyst prompt: filings as-of, not a weekly PE story."""

import inspect

import pytest

import tradingagents.agents.analysts.fundamentals_analyst as fa


@pytest.mark.unit
def test_fundamentals_prompt_uses_filings_not_past_week():
    src = inspect.getsource(fa)
    assert "over the past week" not in src
    assert "quarterly or annual" in src
    assert "do not invent PE" in src
    assert "get_insider_transactions" in src
    assert "增减持" in src
