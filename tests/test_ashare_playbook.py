"""T+1 playbook stance: turnover regime, board shape, and rating lock."""

import pytest

from tradingagents.agents.utils.rating import (
    combine_deterministic_bias,
    enforce_t1_bias,
    t1_bias_from_text,
    trend_bias_from_text,
)
from tradingagents.dataflows.ashare_playbook import (
    PLAYBOOK_HEADING,
    build_playbook_stance,
    classify_board_shape,
    combine_market_amount,
    extract_playbook_section,
)


def _bar(
    *,
    date: str = "2026-01-10",
    limit_up: bool = False,
    touched: bool = False,
    amplitude: float = 3.0,
    open_: float = 10.0,
    preclose: float = 10.0,
    limit_pct: float = 10.0,
) -> dict:
    return {
        "date": date,
        "limit_up": limit_up,
        "touched_limit_up": touched or limit_up,
        "amplitude": amplitude,
        "open": open_,
        "preclose": preclose,
        "limit_pct": limit_pct,
        "close": preclose * (1 + limit_pct / 100.0) if limit_up else preclose,
    }


def _stance(**overrides):
    rows = overrides.pop("daily_rows", None)
    if rows is None:
        rows = [
            _bar(date="2026-01-08", limit_up=True, amplitude=4.0),
            _bar(date="2026-01-09", limit_up=False),
            _bar(
                date="2026-01-10",
                limit_up=True,
                amplitude=4.0,
                open_=10.2,
                preclose=11.0,
            ),
        ]
    params = {
        "daily_rows": rows,
        "as_of": "2026-01-10",
        "market_amount_yuan": 1.5e12,
        "prev_zt_premium": 2.0,
        "limit_up_count": 40,
        "limit_down_count": 5,
        "bank_ret_1d": 0.1,
        "hs300_ret_1d": 0.4,
        "announce_bad": False,
        "is_st_or_loss": False,
        "lift_ban_mv_5d": None,
        "live_pct": None,
        "lhb_net_buy": None,
    }
    params.update(overrides)
    return build_playbook_stance(**params)


@pytest.mark.unit
def test_combine_market_amount_rejects_partial_or_tiny_totals():
    assert combine_market_amount(None, 8e11) is None
    assert combine_market_amount(1e6, 1e6) is None
    assert combine_market_amount(8e11, 7e11) == 1.5e12


@pytest.mark.unit
def test_classify_one_word_and_t_board():
    assert classify_board_shape(_bar(limit_up=True, amplitude=0.2)) == "one_word"
    opened = _bar(limit_up=True, amplitude=4.0, open_=11.0, preclose=10.0)
    assert classify_board_shape(opened) == "t_board"
    assert classify_board_shape(_bar(limit_up=False, touched=True)) == "failed_board"


@pytest.mark.unit
def test_high_tolerance_turnover_first_board_is_buy():
    stance = _stance()
    assert stance["regime"] == "high"
    assert stance["board_shape"] == "turnover_board"
    assert stance["t1_bias"] == "BUY"


@pytest.mark.unit
def test_turnover_continuation_is_buy_while_tolerance_is_high():
    rows = [
        _bar(date="2026-01-09", limit_up=True, amplitude=4.0),
        _bar(date="2026-01-10", limit_up=True, amplitude=4.0, open_=10.2, preclose=11.0),
    ]
    stance = _stance(daily_rows=rows)
    assert stance["consecutive_limit_ups"] == 2
    assert stance["t1_bias"] == "BUY"


@pytest.mark.unit
def test_first_board_without_prior_limits_is_hold():
    rows = [_bar(date="2026-01-10", limit_up=True, amplitude=4.0, open_=10.2, preclose=10.0)]
    stance = _stance(daily_rows=rows)
    assert stance["prior_limit_ups"] == 0
    assert stance["t1_bias"] == "HOLD"


@pytest.mark.unit
def test_thin_tape_first_board_is_hold():
    stance = _stance(market_amount_yuan=1.0e12)
    assert stance["regime"] == "low"
    assert stance["t1_bias"] == "HOLD"


@pytest.mark.unit
def test_one_word_board_is_hold_even_in_a_thick_tape():
    rows = [
        _bar(date="2026-01-09", limit_up=True, amplitude=4.0),
        _bar(date="2026-01-10", limit_up=True, amplitude=0.2),
    ]
    stance = _stance(daily_rows=rows)
    assert stance["board_shape"] == "one_word"
    assert stance["t1_bias"] == "HOLD"


@pytest.mark.unit
def test_bad_filing_vetoes_a_buy():
    stance = _stance(announce_bad=True)
    assert stance["t1_bias"] == "HOLD"
    assert "vetoed" in stance["t1_reason"]


@pytest.mark.unit
def test_live_watch_zone_is_hold():
    rows = [_bar(date="2026-01-10", limit_up=False, amplitude=4.0)]
    stance = _stance(daily_rows=rows, live_pct=8.0)
    assert stance["t1_bias"] == "HOLD"
    assert "watch zone" in stance["t1_reason"]


@pytest.mark.unit
def test_stale_bar_is_not_a_fresh_setup():
    rows = [_bar(date="2026-01-09", limit_up=True, amplitude=4.0)]
    stance = _stance(daily_rows=rows, as_of="2026-01-10")
    assert stance["bar_is_as_of"] is False
    assert stance["t1_bias"] == "HOLD"


@pytest.mark.unit
def test_zero_premium_downgrades_a_thick_tape():
    stance = _stance(prev_zt_premium=0.0)
    assert stance["regime"] == "neutral"
    assert stance["t1_bias"] == "HOLD"
    assert "溢价" in stance["t1_reason"]


@pytest.mark.unit
def test_missing_premium_blocks_buy():
    stance = _stance(prev_zt_premium=None)
    assert stance["t1_bias"] == "HOLD"
    assert "溢价不可用" in stance["t1_reason"]


@pytest.mark.unit
def test_hs300_headwind_blocks_buy():
    stance = _stance(hs300_ret_1d=-1.5)
    assert stance["t1_bias"] == "HOLD"
    assert "沪深300" in stance["t1_reason"]


@pytest.mark.unit
def test_thin_limit_up_market_blocks_buy():
    stance = _stance(limit_up_count=10)
    assert stance["t1_bias"] == "HOLD"
    assert "涨停家数" in stance["t1_reason"]


@pytest.mark.unit
def test_third_board_needs_stronger_premium():
    rows = [
        _bar(date="2026-01-08", limit_up=True, amplitude=4.0),
        _bar(date="2026-01-09", limit_up=True, amplitude=4.0),
        _bar(date="2026-01-10", limit_up=True, amplitude=4.0, open_=10.2, preclose=12.1),
    ]
    weak = _stance(daily_rows=rows, prev_zt_premium=0.5)
    assert weak["consecutive_limit_ups"] == 3
    assert weak["t1_bias"] == "HOLD"
    strong = _stance(daily_rows=rows, prev_zt_premium=1.2)
    assert strong["t1_bias"] == "BUY"


@pytest.mark.unit
def test_lhb_net_sell_vetoes_continuation():
    rows = [
        _bar(date="2026-01-09", limit_up=True, amplitude=4.0),
        _bar(date="2026-01-10", limit_up=True, amplitude=4.0, open_=10.2, preclose=11.0),
    ]
    stance = _stance(daily_rows=rows, lhb_net_buy=-5_000_000.0)
    assert stance["t1_bias"] == "HOLD"
    assert "净卖" in stance["t1_reason"]


@pytest.mark.unit
def test_enforce_t1_bias_rewrites_the_labeled_rating_only_when_present():
    report = "notes\n- t1_bias: HOLD\n"
    rewritten = enforce_t1_bias("**Rating**: Overweight\n\n**Investment Thesis**: Buy the dip.", report)
    assert rewritten.startswith("**Rating**: Hold")
    assert "Buy the dip" in rewritten
    untouched = enforce_t1_bias("**Rating**: Buy", "no playbook here")
    assert untouched == "**Rating**: Buy"


@pytest.mark.unit
def test_t1_bias_from_text_uses_the_last_line():
    text = "t1_bias: BUY\n\n" + PLAYBOOK_HEADING + "\n- t1_bias: HOLD\n"
    assert t1_bias_from_text(text) == "HOLD"
    section = extract_playbook_section(text + "\n## Next\n")
    assert section.startswith(PLAYBOOK_HEADING)
    assert "t1_bias: HOLD" in section


@pytest.mark.unit
def test_combine_deterministic_bias_trend_sell_caps_t1_buy():
    assert combine_deterministic_bias("BUY", "SELL") == "SELL"
    assert combine_deterministic_bias("HOLD", "SELL") == "SELL"
    assert combine_deterministic_bias("BUY", "HOLD") == "BUY"
    assert combine_deterministic_bias("BUY", None) == "BUY"


@pytest.mark.unit
def test_enforce_t1_bias_respects_trend_sell_over_t1_buy():
    report = "t1_bias: BUY\ntrend_bias: SELL\n"
    rewritten = enforce_t1_bias("**Rating**: Buy\n", report)
    assert rewritten.startswith("**Rating**: Sell")
    assert trend_bias_from_text(report) == "SELL"
