"""Append-only news warehouse: identity upsert, date window, path safety."""

from datetime import datetime

import pytest

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.news_items import NewsItem
from tradingagents.dataflows.news_warehouse import (
    query_items,
    upsert_items,
    warehouse_path,
)


@pytest.fixture
def warehouse_dir(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


def _item(**kwargs) -> NewsItem:
    defaults = {
        "title": "茅台提价",
        "link": "http://www.cls.cn/a",
        "channel": "cls_alerts",
        "pub_date": "2026-01-07 08:00:00",
    }
    defaults.update(kwargs)
    return NewsItem(**defaults)


@pytest.mark.unit
def test_upsert_items_skips_duplicate_identity(warehouse_dir):
    first = upsert_items("600519", [_item()])
    second = upsert_items(
        "600519",
        [_item(title="转载提价", link="https://www.cls.cn/a")],
    )
    assert first == 1
    assert second == 0
    path = warehouse_path("600519")
    assert path.is_file()
    assert path.read_text(encoding="utf-8").count("\n") == 1


@pytest.mark.unit
def test_query_items_filters_date_window(warehouse_dir):
    upsert_items(
        "600519",
        [
            _item(title="窗内", pub_date="2026-01-07 08:00:00", link="http://cls.cn/in"),
            _item(title="窗外", pub_date="2026-06-01 08:00:00", link="http://cls.cn/out"),
        ],
    )
    found = query_items(
        "600519",
        datetime(2026, 1, 1),
        datetime(2026, 1, 10),
    )
    titles = [item.title for item in found]
    assert titles == ["窗内"]


@pytest.mark.unit
def test_query_items_skips_corrupt_jsonl_line(warehouse_dir):
    path = warehouse_path("600519")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "{not json\n"
        + '{"title": "完好条目", "body": "", "source": "", "link": "http://a", '
        + '"pub_date": "2026-01-07 08:00:00", "channel": "cls_alerts", "category": ""}\n',
        encoding="utf-8",
    )
    found = query_items("600519", datetime(2026, 1, 1), datetime(2026, 1, 10))
    assert [item.title for item in found] == ["完好条目"]


@pytest.mark.unit
def test_warehouse_path_rejects_traversal_key(warehouse_dir):
    with pytest.raises(ValueError):
        warehouse_path("../etc")
