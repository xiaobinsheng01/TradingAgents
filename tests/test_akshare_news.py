"""AKShare A-share news vendor: date windows, channel isolation, extra gating."""

from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

import tradingagents.dataflows.akshare_news as aknews
from tradingagents.dataflows.akshare_news import AkshareNotConfiguredError
from tradingagents.dataflows.errors import NoMarketDataError


def _em_frame():
    return pd.DataFrame(
        [
            {
                "关键词": "600519",
                "新闻标题": "贵州茅台发布年度报告 600519",
                "新闻内容": "净利润增长",
                "发布时间": "2026-01-05 10:00:00",
                "文章来源": "东方财富",
                "新闻链接": "http://example.com/a",
            },
            {
                "关键词": "600519",
                "新闻标题": "某白酒 ETF 扩募",
                "新闻内容": "与个股无关的 ETF 资讯",
                "发布时间": "2026-01-05 11:00:00",
                "文章来源": "东方财富",
                "新闻链接": "http://example.com/etf",
            },
            {
                "关键词": "600519",
                "新闻标题": "未来才发生的新闻 600519",
                "新闻内容": "lookahead",
                "发布时间": "2026-06-01 10:00:00",
                "文章来源": "东方财富",
                "新闻链接": "http://example.com/future",
            },
        ]
    )


def _filings_frame():
    return pd.DataFrame(
        [
            {
                "公告标题": "2025年年度报告",
                "公告内容": "经审计净利润",
                "公告时间": "2026-01-06",
                "公告链接": "http://www.cninfo.com.cn/a",
                "公告类型": "年度报告",
            }
        ]
    )


def _info_frame(symbol: str = "600519"):
    names = {
        "600519": "贵州茅台",
        "000001": "平安银行",
        "601061": "中信金属",
    }
    name = names.get(str(symbol), "")
    if not name:
        return pd.DataFrame()
    return pd.DataFrame([{"item": "股票简称", "value": name}])


def _cctv_frame():
    return pd.DataFrame(
        [
            {
                "date": "20260110",
                "title": "央行宣布公开市场操作",
                "content": "保持流动性合理充裕",
            }
        ]
    )


def _cls_frame():
    return pd.DataFrame(
        [
            {
                "标题": "证监会发布资本市场改革意见",
                "内容": "提高上市公司质量",
                "发布日期": "2026-01-09 08:00:00",
                "链接": "http://www.cls.cn/a",
            }
        ]
    )


@pytest.fixture(autouse=True)
def _offline_state_media(monkeypatch):
    """Existing AKShare news tests stay offline; state media has its own file."""
    monkeypatch.setattr(aknews, "fetch_state_media_channel", lambda *args, **kwargs: [])


@pytest.fixture
def news_cache_dir(tmp_path):
    from tradingagents.dataflows.config import set_config

    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


@pytest.fixture
def fake_ak():
    return SimpleNamespace(
        stock_news_em=mock.Mock(return_value=_em_frame()),
        stock_zh_a_disclosure_report_cninfo=mock.Mock(return_value=_filings_frame()),
        news_cctv=mock.Mock(return_value=_cctv_frame()),
        stock_info_global_cls=mock.Mock(return_value=_cls_frame()),
        stock_info_global_em=mock.Mock(
            return_value=pd.DataFrame(
                [{"标题": "东财快讯油价", "发布日期": "2026-01-09 09:00:00"}]
            )
        ),
        stock_info_global_sina=mock.Mock(
            return_value=pd.DataFrame(
                [{"标题": "新浪财经全球市场", "发布日期": "2026-01-09 10:00:00"}]
            )
        ),
        stock_info_global_ths=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "标题": "600519 同花顺提到提价",
                        "内容": "贵州茅台",
                        "发布时间": "2026-01-08 09:00:00",
                    },
                    {
                        "标题": "美股期货走高",
                        "内容": "与个股无关",
                        "发布时间": "2026-01-08 09:10:00",
                    },
                ]
            )
        ),
        stock_info_global_futu=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "标题": "富途：白酒板块异动",
                        "内容": "未点名代码",
                        "发布时间": "2026-01-08 09:20:00",
                    },
                    {
                        "标题": "富途快讯 600519",
                        "内容": "盘中",
                        "发布时间": "2026-01-08 09:30:00",
                    },
                ]
            )
        ),
        stock_zh_a_alerts_cls=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "标题": "600519 茅台提价",
                        "内容": "公司快讯",
                        "发布日期": "2026-01-07 08:00:00",
                    }
                ]
            )
        ),
        stock_individual_info_em=mock.Mock(
            side_effect=lambda **kwargs: _info_frame(str(kwargs.get("symbol") or ""))
        ),
    )


@pytest.mark.unit
def test_get_news_aggregates_east_money_and_filings(monkeypatch, fake_ak, news_cache_dir):
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")
    assert "贵州茅台发布年度报告" in out
    assert "[年度报告] 2025年年度报告" in out
    assert "茅台提价" in out
    assert "白酒 ETF" not in out
    assert "未来才发生的新闻" not in out
    fake_ak.stock_news_em.assert_called_once_with(symbol="600519")
    filing_kwargs = fake_ak.stock_zh_a_disclosure_report_cninfo.call_args.kwargs
    assert filing_kwargs["symbol"] == "600519"
    assert filing_kwargs["market"] == "沪深京"
    # Second call must reuse the JSON cache, not hit East Money again.
    aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")
    fake_ak.stock_news_em.assert_called_once()


@pytest.mark.unit
def test_get_news_us_ticker_is_no_data_without_akshare_import(monkeypatch):
    load = mock.Mock()
    monkeypatch.setattr(aknews, "_load_akshare", load)
    with pytest.raises(NoMarketDataError) as ctx:
        aknews.get_news("AAPL", "2026-01-01", "2026-01-10")
    assert "A-share" in ctx.value.detail
    load.assert_not_called()


@pytest.mark.unit
def test_get_news_missing_extra_raises_not_configured(monkeypatch):
    monkeypatch.setattr(
        aknews,
        "_load_akshare",
        mock.Mock(
            side_effect=AkshareNotConfiguredError(
                "akshare extra not installed; pip install '.[akshare]'"
            )
        ),
    )
    with pytest.raises(AkshareNotConfiguredError, match="pip install"):
        aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")


@pytest.mark.unit
def test_load_akshare_missing_package(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "akshare":
            raise ImportError("No module named akshare")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delenv("AKSHARE_BASE_URL", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_AKSHARE_BASE_URL", raising=False)
    from tradingagents.dataflows.config import set_config

    set_config({"akshare_base_url": None})
    with pytest.raises(AkshareNotConfiguredError, match="AKSHARE_BASE_URL"):
        aknews._load_akshare()


@pytest.mark.unit
def test_get_news_survives_one_channel_failure(monkeypatch, fake_ak, news_cache_dir):
    fake_ak.stock_news_em = mock.Mock(side_effect=RuntimeError("eastmoney 500"))
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("000001.SZ", "2026-01-01", "2026-01-10")
    assert "2025年年度报告" in out
    assert "贵州茅台" not in out


@pytest.mark.unit
def test_get_news_falls_back_to_company_dynamics_when_east_money_rst(
    monkeypatch, fake_ak, news_cache_dir
):
    fake_ak.stock_news_em = mock.Mock(side_effect=RuntimeError("eastmoney 500"))
    fake_ak.stock_gsrl_gsdt_em = mock.Mock(
        return_value=pd.DataFrame(
            [
                {
                    "新闻标题": "中信金属签订供货合同",
                    "新闻内容": "日常经营",
                    "发布时间": "2026-01-08 10:00:00",
                    "文章来源": "公司动态",
                }
            ]
        )
    )
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("601061.SH", "2026-01-01", "2026-01-10")
    assert "中信金属签订供货合同" in out
    fake_ak.stock_gsrl_gsdt_em.assert_called()


@pytest.mark.unit
def test_get_news_drops_east_money_related_feed_without_name_or_code(
    monkeypatch, fake_ak, news_cache_dir
):
    fake_ak.stock_news_em = mock.Mock(
        return_value=pd.DataFrame(
            [
                {
                    "关键词": "601061",
                    "新闻标题": "宁德时代发布电池新技术",
                    "新闻内容": "行业新闻，与中信金属无关",
                    "发布时间": "2026-01-08 10:00:00",
                    "文章来源": "东方财富",
                    "新闻链接": "http://example.com/catl",
                },
                    {
                        "关键词": "601061",
                        "新闻标题": "中信金属签订铜加工合同",
                        "新闻内容": "日常经营",
                        "发布时间": "2026-01-08 11:00:00",
                        "文章来源": "东方财富",
                        "新闻链接": "http://example.com/citic",
                    },
                    {
                        "关键词": "601061",
                        "新闻标题": "有色板块早盘活跃",
                        "新闻内容": "601061 成交放大",
                        "发布时间": "2026-01-08 12:00:00",
                        "文章来源": "东方财富",
                        "新闻链接": "http://example.com/code-in-body",
                    },
                ]
            )
        )
    fake_ak.stock_zh_a_disclosure_report_cninfo = mock.Mock(return_value=pd.DataFrame())
    fake_ak.stock_zh_a_alerts_cls = mock.Mock(return_value=pd.DataFrame())
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("601061.SH", "2026-01-01", "2026-01-10")
    assert "中信金属签订铜加工合同" in out
    assert "有色板块早盘活跃" in out
    assert "宁德时代" not in out


@pytest.mark.unit
def test_get_global_news_merges_cctv_and_all_wires(monkeypatch, fake_ak, news_cache_dir):
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_global_news("2026-01-10", look_back_days=7, limit=10)
    assert "央行宣布公开市场操作" in out
    assert "证监会发布资本市场改革意见" in out
    assert "新浪财经全球市场" in out
    assert "东财快讯油价" in out
    assert "美股期货走高" in out
    assert "富途：白酒板块异动" in out
    fake_ak.news_cctv.assert_called_once_with(date="20260110")
    fake_ak.stock_info_global_cls.assert_called()
    fake_ak.stock_info_global_em.assert_called()
    fake_ak.stock_info_global_sina.assert_called()
    fake_ak.stock_info_global_ths.assert_called()
    fake_ak.stock_info_global_futu.assert_called()


@pytest.mark.unit
def test_get_news_keeps_ths_futu_rows_that_mention_the_ticker(
    monkeypatch, fake_ak, news_cache_dir
):
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")
    assert "600519 同花顺提到提价" in out
    assert "富途快讯 600519" in out
    assert "美股期货走高" not in out
    assert "富途：白酒板块异动" not in out


@pytest.mark.unit
def test_get_news_includes_warehouse_item_in_window(monkeypatch, fake_ak, news_cache_dir):
    from tradingagents.dataflows.news_items import NewsItem
    from tradingagents.dataflows.news_warehouse import upsert_items

    upsert_items(
        "600519",
        [
            NewsItem(
                title="600519 早盘已入库电报",
                channel="cls_alerts",
                source="财联社电报",
                pub_date="2026-01-08 09:00:00",
                link="http://cls.example/early",
            )
        ],
    )
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")
    assert "600519 早盘已入库电报" in out
    assert "茅台提价" in out


@pytest.mark.unit
def test_get_news_drops_unrelated_warehouse_flash(monkeypatch, fake_ak, news_cache_dir):
    from tradingagents.dataflows.news_items import NewsItem
    from tradingagents.dataflows.news_warehouse import upsert_items

    upsert_items(
        "600519",
        [
            NewsItem(
                title="宁德时代涨停解读",
                channel="cls_alerts",
                source="财联社电报",
                pub_date="2026-01-08 09:00:00",
                link="http://cls.example/unrelated",
            )
        ],
    )
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    out = aknews.get_news("600519.SS", "2026-01-01", "2026-01-10")
    assert "宁德时代涨停解读" not in out
    assert "贵州茅台发布年度报告" in out


@pytest.mark.unit
def test_live_cls_alerts_refresh_after_telegraph_ttl(monkeypatch, fake_ak, news_cache_dir):
    from datetime import datetime, timezone

    from tradingagents.dataflows.config import set_config

    today = datetime.now(timezone.utc).date().isoformat()
    set_config(
        {
            "data_cache_dir": str(news_cache_dir),
            "news_telegraph_ttl_seconds": 1,
            "news_cache_ttl_seconds": 900,
        }
    )
    fake_ak.stock_news_em = mock.Mock(return_value=pd.DataFrame())
    fake_ak.stock_zh_a_disclosure_report_cninfo = mock.Mock(return_value=pd.DataFrame())
    fake_ak.stock_zh_a_alerts_cls = mock.Mock(
        return_value=pd.DataFrame(
            [
                {
                    "标题": "600519 live telegraph",
                    "内容": "盘中快讯",
                    "发布日期": f"{today} 08:00:00",
                }
            ]
        )
    )
    monkeypatch.setattr(aknews, "_load_akshare", lambda: fake_ak)
    aknews.get_news("600519.SS", today, today)
    aknews.get_news("600519.SS", today, today)
    assert fake_ak.stock_zh_a_alerts_cls.call_count == 1
    real_time = __import__("time").time
    monkeypatch.setattr(
        "tradingagents.dataflows.news_store.time.time",
        lambda: real_time() + 10,
    )
    aknews.get_news("600519.SS", today, today)
    assert fake_ak.stock_zh_a_alerts_cls.call_count == 2


@pytest.mark.unit
def test_cls_alerts_skips_missing_aktools_interface():
    from datetime import datetime, timezone

    fake = SimpleNamespace(
        stock_zh_a_alerts_cls=mock.Mock(
            side_effect=RuntimeError(
                "AKTools HTTP stock_zh_a_alerts_cls returned 404: "
                '{"error":"未找到该接口，请升级 AKShare 到最新版本"}'
            )
        )
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert aknews._fetch_cls_alerts(fake, start, end, "600519") == []
    assert fake.stock_zh_a_alerts_cls.call_count == 1
