"""Regression tests for swing-window trend bias rules."""

from __future__ import annotations

import pytest

from tradingagents.dataflows.ashare_trend_bias import (
    compute_trend_bias,
    index_bear_regime,
)


@pytest.mark.unit
def test_index_bear_regime_flags_weak_hs300():
    assert index_bear_regime(-4.0, None) is True
    assert index_bear_regime(None, -6.0) is True
    assert index_bear_regime(-1.0, -2.0) is False


@pytest.mark.unit
def test_rebound_buy_blocked_in_bear_regime():
    bias, reason = compute_trend_bias(
        ret_window=-18.0,
        ret_5=-2.0,
        ret_10=-4.0,
        range_pos=20.0,
        vs_index=-1.0,
        chan_buy_sell=None,
        chan_segment="up",
        hs300_ret_20d=-5.0,
        hs300_ret_window=-2.0,
    )
    assert bias == "HOLD"
    assert "偏空" in reason or "下沿" in reason


@pytest.mark.unit
def test_rebound_buy_blocked_on_down_segment():
    bias, _ = compute_trend_bias(
        ret_window=-18.0,
        ret_5=-2.0,
        ret_10=-4.0,
        range_pos=20.0,
        vs_index=0.0,
        chan_buy_sell=None,
        chan_segment="down",
        hs300_ret_20d=1.0,
        hs300_ret_window=1.0,
    )
    assert bias == "HOLD"


@pytest.mark.unit
def test_persistent_weakness_becomes_sell_not_rebound_buy():
    bias, reason = compute_trend_bias(
        ret_window=-18.0,
        ret_5=-4.0,
        ret_10=-6.0,
        range_pos=20.0,
        vs_index=0.0,
        chan_buy_sell=None,
        chan_segment="up",
        hs300_ret_20d=1.0,
        hs300_ret_window=1.0,
    )
    assert bias == "SELL"
    assert "持续" in reason


@pytest.mark.unit
def test_industry_weak_blocks_rebound_buy():
    bias, reason = compute_trend_bias(
        ret_window=-18.0,
        ret_5=-1.0,
        ret_10=-2.0,
        range_pos=22.0,
        vs_index=0.0,
        chan_buy_sell=None,
        chan_segment="up",
        industry_ret_5=-5.0,
    )
    assert bias == "HOLD"
    assert "行业" in reason


@pytest.mark.unit
def test_relative_strength_buy_blocked_when_absolute_still_down():
    bias, reason = compute_trend_bias(
        ret_window=5.0,
        ret_5=-2.0,
        ret_10=1.0,
        range_pos=50.0,
        vs_index=8.0,
        chan_buy_sell=None,
        chan_segment="up",
    )
    assert bias == "HOLD"
    assert "近5日" in reason
