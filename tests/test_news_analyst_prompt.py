"""Guard the news analyst prompt against tool-signature drift (#1116).

The prompt used to advertise ``get_news(query, ...)`` while the tool takes a
``ticker``, tricking the LLM into hallucinating free-text query calls.
"""
import inspect

import pytest

import tradingagents.agents.analysts.news_analyst as na
from tradingagents.agents.utils.news_data_tools import get_news


@pytest.mark.unit
def test_get_news_takes_ticker_not_query():
    arg_names = set(get_news.args.keys())
    assert "ticker" in arg_names
    assert "query" not in arg_names


@pytest.mark.unit
def test_news_prompt_matches_get_news_signature():
    src = inspect.getsource(na)
    assert "get_news(ticker, start_date, end_date)" in src
    assert "get_news(query" not in src


@pytest.mark.unit
def test_news_prompt_covers_policy_and_overseas():
    src = inspect.getsource(na)
    assert "A-share filings" in src or "company-specific" in src
    assert "get_global_news" in src
    assert "Google Search" in src
    assert "do not treat unrelated" in src
    assert "get_news(ticker, start_date, end_date)" in src
    assert "Leave the tool unused" in src
    assert "skip US-election" in src
    assert "get_insider_transactions(ticker, curr_date)" in src
    assert "增减持" in src
    assert "half_month" in src
    assert "90 calendar days" in src
    assert "180 calendar days" in src
    assert "Swing tape window" in src
