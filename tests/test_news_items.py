"""NewsItem identity, policy tagging, and cross-channel dedupe."""

import pytest

from tradingagents.dataflows.news_items import (
    NewsItem,
    canonical_link,
    dedupe_items,
    is_policy_item,
    item_identity,
    render_items,
)


@pytest.mark.unit
def test_dedupe_items_by_link_keeps_first():
    a = NewsItem(title="茅台年报", link="http://www.example.com/a", source="东财", channel="east_money")
    b = NewsItem(title="茅台年报转载", link="https://www.example.com/a", source="新浪", channel="sina_flash")
    out = dedupe_items([a, b])
    assert [item.source for item in out] == ["东财"]


@pytest.mark.unit
def test_dedupe_items_by_title_when_no_link():
    a = NewsItem(title="央行降准", source="联播", channel="cctv")
    b = NewsItem(title="央行  降准", source="财联社", channel="cls_flash")
    out = dedupe_items([a, b])
    assert len(out) == 1
    assert out[0].source == "联播"


@pytest.mark.unit
def test_is_policy_item_detects_csrc_and_pboc():
    assert is_policy_item(NewsItem(title="证监会发布新规", channel="cls_flash"))
    assert is_policy_item(NewsItem(title="央行公开市场操作", channel="cctv"))
    assert not is_policy_item(NewsItem(title="某白酒经销商开会", channel="east_money"))


@pytest.mark.unit
def test_render_items_prefixes_filing_category():
    item = NewsItem(
        title="2025年年度报告",
        source="巨潮资讯",
        category="年度报告",
        channel="cninfo",
    )
    text = render_items([item], limit=5)
    assert "[年度报告] 2025年年度报告" in text


@pytest.mark.unit
def test_canonical_link_strips_www_and_slash():
    assert canonical_link("https://www.Example.com/a/") == canonical_link("http://example.com/a")


@pytest.mark.unit
def test_item_identity_prefers_link_over_title():
    item = NewsItem(title="转载标题", link="https://www.example.com/a/")
    assert item_identity(item) == ("link", canonical_link(item.link))
    assert item_identity(NewsItem(title="")) is None
