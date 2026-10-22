"""State-media headlines: official pages, window filter, ticker mentions."""

from datetime import datetime
from types import SimpleNamespace

import pytest
import requests

import tradingagents.dataflows.akshare_news as aknews
import tradingagents.dataflows.state_media_news as state_media


class _Resp:
    def __init__(self, body: str, status: int = 200):
        self.content = body.encode("utf-8")
        self.status_code = status


def _install(monkeypatch, pages: dict[str, str | Exception]):
    def fake_get(url, timeout=30, headers=None):
        body = pages.get(url)
        if isinstance(body, Exception):
            raise body
        if body is None:
            return _Resp("missing", 404)
        return _Resp(body)

    monkeypatch.setattr(state_media.requests, "get", fake_get)


@pytest.fixture
def news_cache_dir(tmp_path):
    from tradingagents.dataflows.config import set_config

    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


_PEOPLE = """
<a href="http://www.people.com.cn/n1/2026/0108/c1002-1.html">人民日报：保持流动性合理充裕</a>
<a href="http://www.people.com.cn/n1/2026/0108/c1002-2.html">人民日报点名600519贵州茅台</a>
<a href="http://www.people.com.cn/n1/2025/0605/c1002-old.html">过期人民日报</a>
<a href="http://www.people.com.cn/">首页</a>
"""

_XINHUA = """
<a href="/fortune/20260108/abc/c.html">新华社财经：买断式逆回购</a>
<a href="/politics/20260108/nope.html">不是财经列表</a>
"""

_CE_OK = """
<a href="./202601/t20260108_9.shtml">中国经济网：工业生产平稳</a>
<a href="http://finance.ce.cn/stock/202601/t20260108_8.shtml">中国经济网提到600519提价</a>
"""


@pytest.mark.unit
def test_people_daily_keeps_dated_homepage_items_in_window(monkeypatch):
    _install(monkeypatch, dict.fromkeys(state_media._PEOPLE_PAGES, _PEOPLE))
    items = state_media.fetch_state_media_channel(
        "people_daily",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    titles = [item.title for item in items]
    assert "人民日报：保持流动性合理充裕" in titles
    assert "人民日报点名600519贵州茅台" in titles
    assert all(item.source == "人民日报" for item in items)
    assert "过期人民日报" not in titles


@pytest.mark.unit
def test_xinhua_finance_resolves_relative_links(monkeypatch):
    _install(monkeypatch, {state_media._XINHUA_PAGE: _XINHUA})
    items = state_media.fetch_state_media_channel(
        "xinhua_finance",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    assert len(items) == 1
    assert items[0].title == "新华社财经：买断式逆回购"
    assert items[0].link == "https://www.news.cn/fortune/20260108/abc/c.html"
    assert items[0].source == "新华社财经"


@pytest.mark.unit
def test_economic_daily_keeps_sibling_page_when_one_url_fails(monkeypatch):
    rolling, finance = state_media._ECONOMIC_PAGES
    _install(
        monkeypatch,
        {
            rolling: requests.ConnectionError("ce.cn down"),
            finance: _CE_OK,
        },
    )
    items = state_media.fetch_state_media_channel(
        "economic_daily",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    assert [item.title for item in items] == [
        "中国经济网：工业生产平稳",
        "中国经济网提到600519提价",
    ]
    assert items[0].link.startswith("http://finance.ce.cn/")
    assert all(item.source == "中国经济网" for item in items)


@pytest.mark.unit
def test_chinanews_rss_uses_publisher_clock(monkeypatch):
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>中新网财经：出口回升</title>
        <link>https://www.chinanews.com.cn/cj/a.shtml</link>
        <pubDate>Thu, 08 Jan 2026 11:09:15 +0800</pubDate>
        <description>&lt;p&gt;摘要&lt;/p&gt;</description>
      </item>
      <item>
        <title>中新网财经：窗口外</title>
        <link>https://www.chinanews.com.cn/cj/b.shtml</link>
        <pubDate>Thu, 01 Jan 2026 11:09:15 +0800</pubDate>
      </item>
    </channel></rss>
    """
    _install(monkeypatch, {state_media._CHINANEWS_RSS: rss})
    items = state_media.fetch_state_media_channel(
        "chinanews_finance",
        datetime(2026, 1, 3),
        datetime(2026, 1, 10),
    )
    assert len(items) == 1
    assert items[0].source == "中新网财经"
    assert items[0].pub_date == "2026-01-08 11:09:15"
    assert items[0].body == "摘要"


@pytest.mark.unit
def test_cctv_news_jsonp_reads_focus_date(monkeypatch):
    payload = (
        'news({"data":{"list":[{'
        '"title":"央视：教育部公布高等教育数据",'
        '"brief":"普及程度居世界前列",'
        '"url":"https://news.cctv.com/2026/01/08/a.shtml",'
        '"focus_date":"2026-01-08 19:00:00"'
        "}]}})"
    )
    _install(monkeypatch, {state_media._CCTV_JSONP: payload})
    items = state_media.fetch_state_media_channel(
        "cctv_news",
        datetime(2026, 1, 8),
        datetime(2026, 1, 8),
    )
    assert len(items) == 1
    assert items[0].source == "央视新闻"
    assert items[0].body == "普及程度居世界前列"
    assert items[0].pub_date.startswith("2026-01-08")


@pytest.mark.unit
def test_gov_cn_reads_yaowen_json(monkeypatch):
    payload = """[
      {"TITLE":"国务院常务会议研究经济形势","URL":"https://www.gov.cn/yaowen/a.htm","DOCRELPUBTIME":"2026-01-08"},
      {"TITLE":"更早的国务院要闻","URL":"https://www.gov.cn/yaowen/b.htm","DOCRELPUBTIME":"2025-12-01"}
    ]"""
    _install(monkeypatch, {state_media._GOV_JSON: payload})
    items = state_media.fetch_state_media_channel(
        "gov_cn",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    assert [item.title for item in items] == ["国务院常务会议研究经济形势"]
    assert items[0].source == "中国政府网"


@pytest.mark.unit
def test_xwlb_splits_episode_brief_inside_window(monkeypatch):
    payload = """{
      "data": {"list": [
        {
          "title": "《新闻联播》 20260108 19:00",
          "url": "https://tv.cctv.com/2026/01/08/VIDEabc.shtml",
          "time": "2026-01-08 19:00:00",
          "brief": "本期节目主要内容：\\n1.国务院部署稳增长；\\n2.提到600519贵州茅台提价；"
        },
        {
          "title": "《新闻联播》 20251201 19:00",
          "url": "https://tv.cctv.com/2025/12/01/VIDEold.shtml",
          "time": "2025-12-01 19:00:00",
          "brief": "1.窗口外的联播"
        }
      ]}
    }"""
    _install(monkeypatch, {state_media._XWLB_API: payload})
    items = state_media.fetch_state_media_channel(
        "xwlb",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    titles = [item.title for item in items]
    assert titles == ["国务院部署稳增长", "提到600519贵州茅台提价"]
    assert all(item.source == "新闻联播" for item in items)
    assert all(item.link.endswith("VIDEabc.shtml") for item in items)
    assert "窗口外的联播" not in titles


@pytest.mark.unit
def test_pbc_reads_date_from_article_path(monkeypatch):
    page = """
    <a href="/goutongjiaoliu/113456/113469/2026010812000000001/index.html">央行开展买断式逆回购</a>
    <a href="/goutongjiaoliu/113456/113469/2025120112000000001/index.html">更早的央行稿</a>
    <a href="/other/20260108/index.html">不是新闻列表</a>
    """
    _install(monkeypatch, {state_media._PBC_PAGE: page})
    items = state_media.fetch_state_media_channel(
        "pbc",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    assert len(items) == 1
    assert items[0].title == "央行开展买断式逆回购"
    assert items[0].source == "中国人民银行"
    assert items[0].link.startswith("https://www.pbc.gov.cn/goutongjiaoliu/")


@pytest.mark.unit
def test_ministry_pages_use_filename_date(monkeypatch):
    mof = '<a href="./202601/t20260108_1.htm">财政部续发国债</a>'
    ndrc = '<a href="./202601/t20260108_2.html">发改委新闻发布会</a>'
    stats = '<a href="./202601/t20260108_3.html">国家统计局发布PMI</a>'
    _install(
        monkeypatch,
        {
            state_media._MOF_PAGE: mof,
            state_media._NDRC_PAGE: ndrc,
            state_media._STATS_PAGE: stats,
        },
    )
    start, end = datetime(2026, 1, 1), datetime(2026, 1, 10)
    mof_items = state_media.fetch_state_media_channel("mof", start, end)
    ndrc_items = state_media.fetch_state_media_channel("ndrc", start, end)
    stats_items = state_media.fetch_state_media_channel("stats_gov", start, end)
    assert mof_items[0].source == "财政部"
    assert mof_items[0].link.startswith("https://www.mof.gov.cn/")
    assert ndrc_items[0].title == "发改委新闻发布会"
    assert ndrc_items[0].source == "国家发展改革委"
    assert stats_items[0].source == "国家统计局"
    assert stats_items[0].pub_date == "2026-01-08"


@pytest.mark.unit
def test_get_global_news_includes_state_media_in_policy_section(
    monkeypatch, news_cache_dir
):
    _install(
        monkeypatch,
        {
            **dict.fromkeys(state_media._PEOPLE_PAGES, _PEOPLE),
            state_media._XINHUA_PAGE: _XINHUA,
            **dict.fromkeys(state_media._ECONOMIC_PAGES, _CE_OK),
            state_media._GOV_JSON: (
                '[{"TITLE":"国务院常务会议","URL":"https://www.gov.cn/yaowen/a.htm",'
                '"DOCRELPUBTIME":"2026-01-08"}]'
            ),
            state_media._XWLB_API: (
                '{"data":{"list":[{"title":"联播","url":"https://tv.cctv.com/a.shtml",'
                '"time":"2026-01-08 19:00:00","brief":"1.新闻联播：保持流动性合理充裕"}]}}'
            ),
            state_media._PBC_PAGE: (
                '<a href="/goutongjiaoliu/113456/113469/2026010812000000001/index.html">'
                "央行公开市场操作</a>"
            ),
        },
    )
    monkeypatch.setattr(aknews, "_load_akshare", lambda: SimpleNamespace())
    out = aknews.get_global_news("2026-01-10", look_back_days=7, limit=10)
    assert "CCTV, state media, and regulator policy" in out
    assert "人民日报：保持流动性合理充裕" in out
    assert "新华社财经：买断式逆回购" in out
    assert "中国经济网：工业生产平稳" in out
    assert "国务院常务会议" in out
    assert "新闻联播：保持流动性合理充裕" in out
    assert "央行公开市场操作" in out
    assert "过期人民日报" not in out


@pytest.mark.unit
def test_get_news_keeps_state_media_rows_that_mention_the_ticker(
    monkeypatch, news_cache_dir
):
    _install(monkeypatch, dict.fromkeys(state_media._PEOPLE_PAGES, _PEOPLE))
    monkeypatch.setattr(aknews, "_load_akshare", lambda: SimpleNamespace())
    out = aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")
    assert "State media mentions for 600519" in out
    assert "人民日报点名600519贵州茅台" in out
    assert "保持流动性合理充裕" not in out
