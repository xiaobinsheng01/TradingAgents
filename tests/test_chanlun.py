"""缠论: inclusion, 分型/笔/中枢 from closed OHLC only."""

from datetime import datetime, timedelta

import pytest

from tradingagents.dataflows.chanlun import (
    analyze_chanlun,
    merge_inclusions,
    render_chanlun_markdown,
)


def _hl_bars(start: str, pairs: list[tuple[float, float]]) -> list[dict]:
    origin = datetime.strptime(start, "%Y-%m-%d")
    rows = []
    for i, (high, low) in enumerate(pairs):
        close = round((high + low) / 2.0, 4)
        rows.append(
            {
                "date": (origin + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
            }
        )
    return rows


def _up_down_up_hub_bars() -> list[dict]:
    """Closed bars that print bottom-top-bottom-top: two up 笔 around one down 笔."""
    return _hl_bars(
        "2025-12-01",
        [
            (10.0, 9.0),
            (9.8, 8.5),
            (10.5, 9.2),
            (12.0, 10.0),
            (11.5, 9.8),
            (10.2, 8.8),
            (9.0, 7.5),
            (9.6, 8.1),
            (11.0, 9.4),
            (12.2, 10.5),
            (11.8, 10.0),
        ],
    )


@pytest.mark.unit
def test_inclusion_merges_contained_bar():
    rows = _hl_bars(
        "2026-01-01",
        [
            (10.0, 8.0),
            (9.5, 8.5),
            (11.0, 9.0),
        ],
    )
    merged = merge_inclusions(rows)
    assert len(merged) == 2
    assert merged[0].high == 10.0
    assert merged[0].low == 8.5
    assert merged[0].src_count == 2


@pytest.mark.unit
def test_analyze_chanlun_builds_up_then_down_strokes():
    snap = analyze_chanlun(_up_down_up_hub_bars())
    confirmed = [item for item in snap.strokes if item.confirmed]
    assert len(confirmed) >= 2
    assert confirmed[0].direction == "up"
    assert confirmed[1].direction == "down"
    assert snap.hub is not None
    assert snap.hub.zg > snap.hub.zd


@pytest.mark.unit
def test_render_chanlun_too_few_bars_is_no_data():
    rows = _hl_bars("2026-01-01", [(10.0, 9.0), (10.2, 9.1)])
    text = render_chanlun_markdown(
        rows, as_of="2026-01-02", ticker="600519.SS", timeframe="daily"
    )
    assert "NO_DATA_AVAILABLE" in text
    assert "Do not invent" in text
    assert "买卖点" in text


@pytest.mark.unit
def test_render_chanlun_uses_closed_structure():
    text = render_chanlun_markdown(
        _up_down_up_hub_bars(),
        as_of="2025-12-11",
        ticker="600519.SS",
        timeframe="daily",
    )
    assert "## 缠论 (daily, as-of 2025-12-11)" in text
    assert "Recent 笔" in text
    assert "not an order" in text


@pytest.mark.unit
def test_chanlun_does_not_see_future_bars():
    rows = _up_down_up_hub_bars()
    as_of = "2025-12-05"
    kept = [row for row in rows if row["date"] <= as_of]
    text = render_chanlun_markdown(
        kept, as_of=as_of, ticker="600519.SS", timeframe="daily"
    )
    assert "2025-12-10" not in text
    assert "2025-12-11" not in text
