"""Market-wide mood rules and stock blending."""

from __future__ import annotations

import pytest

from tradingagents.dataflows.ashare_market_mood import (
    blend_stock_with_market_mood,
    enhance_mood_t1_with_sentiment,
    has_material_stock_news,
)


@pytest.mark.unit
def test_has_material_stock_news_from_warehouse_flags():
    assert has_material_stock_news({"announce_bad": True}) is True
    assert has_material_stock_news({"announce_good": True}) is True
    assert has_material_stock_news({"announce_bad": False, "announce_good": False}) is False


@pytest.mark.unit
def test_blend_mood_leads_when_no_material_news():
    bias, reason = blend_stock_with_market_mood(
        "HOLD",
        "BUY",
        material_news=False,
        stock_reason="个股观望",
        mood_reason="情绪偏多",
    )
    assert bias == "BUY"
    assert "无显著个股" in reason


@pytest.mark.unit
def test_blend_keeps_stock_when_material_news():
    bias, reason = blend_stock_with_market_mood(
        "SELL",
        "BUY",
        material_news=True,
        stock_reason="公告偏空",
        mood_reason="情绪偏多",
    )
    assert bias == "SELL"
    assert reason.startswith("公告偏空")


@pytest.mark.unit
def test_blend_blocks_aggressive_buy_under_bad_mood_without_news():
    bias, _ = blend_stock_with_market_mood(
        "BUY",
        "SELL",
        material_news=False,
        stock_reason="形态多",
        mood_reason="跌停多",
    )
    assert bias == "HOLD"


@pytest.mark.unit
def test_sentiment_enhance_upgrades_hold_on_breadth():
    bias, reason = enhance_mood_t1_with_sentiment(
        "HOLD",
        "base",
        regime="high",
        ret_1d=-0.2,
        limit_up_count=80,
        limit_down_count=50,
        prev_zt_premium=0.5,
    )
    assert bias == "BUY"
    assert "情绪" in reason
