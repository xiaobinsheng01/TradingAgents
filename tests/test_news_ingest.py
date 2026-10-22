"""One-shot A-share news ingest into the local warehouse."""

from datetime import datetime
from unittest import mock

import pytest
from typer.testing import CliRunner

import cli.main as cli_main
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.news_ingest import ingest_news
from tradingagents.dataflows.news_items import NewsItem
from tradingagents.dataflows.news_store import GLOBAL_KEY
from tradingagents.dataflows.news_warehouse import query_items


@pytest.fixture
def ingest_cache(tmp_path):
    set_config({"data_cache_dir": str(tmp_path), "global_news_lookback_days": 7})
    return tmp_path


@pytest.mark.unit
def test_ingest_news_requires_ticker_or_global(ingest_cache):
    with pytest.raises(ValueError, match="ticker"):
        ingest_news()


@pytest.mark.unit
def test_ingest_news_rejects_non_a_share(ingest_cache):
    with pytest.raises(ValueError, match="A-share"):
        ingest_news("AAPL")


@pytest.mark.unit
def test_ingest_news_upserts_ticker_and_global(ingest_cache, monkeypatch):
    ticker_items = [
        NewsItem(
            title="入库个股电报",
            channel="cls_alerts",
            pub_date="2026-01-09 08:00:00",
            link="http://cls.example/t",
        )
    ]
    global_items = [
        NewsItem(
            title="入库联播",
            channel="cctv",
            pub_date="2026-01-10 19:00:00",
            link="http://cctv.example/g",
        )
    ]
    monkeypatch.setattr(
        "tradingagents.dataflows.news_ingest.collect_ticker_news_items",
        lambda code, start, end: ticker_items,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.news_ingest.collect_global_news_items",
        lambda curr, lookback: global_items,
    )
    results = ingest_news(
        "600519.SS",
        curr_date="2026-01-10",
        include_global=True,
    )
    assert [row.key for row in results] == ["600519", GLOBAL_KEY]
    assert results[0].fetched == 1 and results[0].appended == 1
    assert results[1].fetched == 1 and results[1].appended == 1
    found = query_items("600519", datetime(2026, 1, 1), datetime(2026, 1, 10))
    assert [item.title for item in found] == ["入库个股电报"]


@pytest.mark.unit
def test_ingest_news_cli_writes_counts(ingest_cache, monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.news_ingest.ingest_news",
        lambda **kwargs: [
            mock.Mock(key="600519", fetched=3, appended=1),
        ],
    )
    result = CliRunner().invoke(cli_main.app, ["ingest-news", "600519.SS"])
    assert result.exit_code == 0, result.output
    assert "Warehouse 600519: fetched 3, appended 1" in result.output


@pytest.mark.unit
def test_bare_cli_still_runs_analyze(monkeypatch):
    called = {}

    def fake(*, checkpoint, clear_checkpoints):
        called["ok"] = True

    monkeypatch.setattr(cli_main, "_run_analyze", fake)
    result = CliRunner().invoke(cli_main.app, [])
    assert result.exit_code == 0, result.output
    assert called.get("ok") is True
