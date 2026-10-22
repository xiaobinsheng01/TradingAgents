"""Market analyst prompt must advertise the A-share short-horizon tool."""

import inspect

import pytest

import tradingagents.agents.analysts.market_analyst as ma
from tradingagents.agents.utils.ashare_market_tools import (
    get_ashare_short_horizon,
    get_ashare_swing_tape,
)


@pytest.mark.unit
def test_get_ashare_short_horizon_takes_ticker_and_curr_date():
    assert {"ticker", "curr_date"} <= set(get_ashare_short_horizon.args.keys())


@pytest.mark.unit
def test_get_ashare_swing_tape_takes_window():
    assert {"ticker", "curr_date", "window"} <= set(get_ashare_swing_tape.args.keys())


@pytest.mark.unit
def test_market_prompt_calls_ashare_tape_not_pe():
    src = inspect.getsource(ma)
    assert "get_ashare_short_horizon(ticker, curr_date)" in src
    assert "get_ashare_swing_tape(ticker, curr_date, window)" in src
    assert "window news" in src
    assert "缠论" in src
    assert "中枢" in src
    assert "do not invent" in src.lower() or "do **not** invent" in src
    assert "half_year" in src
    assert "half_month" in src
    assert "PE/PB/ROE" in src
    assert "T+1" in src
    assert "unbuyable" in src
    assert "never places broker orders" in src
    assert "Live snapshot" in src
    assert "Playbook stance (T+1)" in src
    assert "t1_bias" in src
    assert "沪铜" in src
    assert "LME" in src
    assert "COMEX" in src
    assert "碳酸锂" in src
    assert "do **not** invent" in src or "do not invent" in src
    assert ".SH" in src
    assert "buy/sell seats" in src
