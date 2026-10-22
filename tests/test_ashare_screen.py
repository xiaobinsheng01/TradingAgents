"""Main-board screen: drop ChiNext, keep front-row leaders, label disclosed flow."""

from datetime import datetime, timezone

import pytest

from tradingagents.dataflows.ashare_screen import (
    ScreenNotLiveError,
    build_screen_snapshot,
    screen_main_board,
)


def _spot(
    code: str,
    name: str,
    pct: float,
    *,
    speed: float | None = 1.0,
    amplitude: float = 5.0,
    open_: float = 10.2,
    preclose: float = 10.0,
    last: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> dict:
    close = preclose * (1 + pct / 100.0) if last is None else last
    return {
        "代码": code,
        "名称": name,
        "涨跌幅": pct,
        "涨速": speed,
        "5分钟涨跌": 0.4,
        "换手率": 8.0,
        "量比": 1.6,
        "成交额": 2_000_000_000,
        "振幅": amplitude,
        "流通市值": 20_000_000_000,
        "最新价": close,
        "今开": open_,
        "最高": close if high is None else high,
        "最低": open_ if low is None else low,
        "昨收": preclose,
    }


def _high_regime() -> dict:
    return {
        "regime": "high",
        "market_amount_yuan": 1.4e12,
        "prev_zt_premium": 1.5,
        "limit_up_count": 40,
        "limit_down_count": 5,
        "bank_ret_1d": -0.2,
        "hs300_ret_1d": 0.4,
    }


def _snapshot(**overrides) -> dict:
    body = {
        "as_of": "2026-09-22",
        "spot_rows": [],
        "leader_rows": [],
        "regime": _high_regime(),
        "zt_rows": [],
        "lhb_rows": [],
        "insider_rows": [],
        "margin_rows": [],
        "universe": "main",
        "only_t1_bias": None,
    }
    body.update(overrides)
    return build_screen_snapshot(**body)


def test_screen_drops_chinext_star_and_does_not_promote_second():
    snap = _snapshot(
        spot_rows=[
            _spot("300001", "创业龙", 18.0),
            _spot("688001", "科创甲", 15.0),
            _spot("600001", "主板甲", 9.2),
            _spot("000002", "主板乙", 8.1),
        ],
        leader_rows=[
            {"板块名称": "机器人", "领涨股票": "创业龙", "领涨股票-涨跌幅": 18},
            {"板块名称": "白酒", "领涨股票": "600001", "领涨股票-涨跌幅": 9.2},
        ],
    )
    codes = [row["code"] for row in snap["rows"]]
    assert "300001" not in codes
    assert "688001" not in codes
    leader = next(row for row in snap["rows"] if row["code"] == "600001")
    assert leader["is_sector_leader"] is True
    assert leader["sector"] == "白酒"
    assert "领涨" in leader["sources"]
    follower = next(row for row in snap["rows"] if row["code"] == "000002")
    assert follower["is_sector_leader"] is False
    assert follower["sector"] is None


def test_empty_board_does_not_invent_names():
    snap = _snapshot(spot_rows=[_spot("300750", "宁德时代", 12.0, speed=3)])
    assert snap["rows"] == []
    assert snap["universe"] == "main"


def test_one_word_board_stays_hold():
    snap = _snapshot(
        spot_rows=[
            _spot(
                "600010",
                "一字甲",
                10.0,
                amplitude=0.2,
                open_=11.0,
                last=11.0,
                high=11.0,
                low=10.98,
            )
        ]
    )
    row = snap["rows"][0]
    assert row["board_shape"] == "one_word"
    assert row["t1_bias"] == "HOLD"


def test_turnover_continuation_can_bias_buy():
    snap = _snapshot(
        spot_rows=[_spot("000010", "换手乙", 10.0)],
        zt_rows=[{"代码": "000010", "连板数": "2"}],
    )
    row = snap["rows"][0]
    assert row["ticker"] == "000010.SZ"
    assert row["board_shape"] == "turnover_board"
    assert row["t1_bias"] == "BUY"


def test_first_board_without_history_stays_hold():
    snap = _snapshot(spot_rows=[_spot("600010", "首板甲", 10.0)])
    assert snap["rows"][0]["t1_bias"] == "HOLD"


def test_bars_keep_unique_ascending_days_and_drop_later_dates():
    from tradingagents.dataflows.ashare_screen import bars_from_daily

    rows = [
        {"日期": "2026-09-22", "开盘": 11, "最高": 12, "最低": 10, "收盘": 11.5, "成交量": 100},
        {"日期": "2026-09-21", "开盘": 10, "最高": 11, "最低": 9, "收盘": 10.5, "成交量": 80},
        {"日期": "2026-09-21", "开盘": 10, "最高": 11, "最低": 9.5, "收盘": 10.8, "成交量": 90},
        {"日期": "2026-09-23", "开盘": 12, "最高": 13, "最低": 11, "收盘": 12.5, "成交量": 50},
        {"日期": "2026-09-20", "开盘": None, "最高": 10, "最低": 9, "收盘": 9.5, "成交量": 10},
    ]
    bars = bars_from_daily(rows, "2026-09-22")
    assert [bar["time"] for bar in bars] == ["2026-09-21", "2026-09-22"]
    assert bars[0]["close"] == 10.8
    assert bars[0]["volume"] == 90


def test_screen_bars_reject_chinext_without_vendor():
    from tradingagents.dataflows.ashare_screen import screen_price_bars

    with pytest.raises(ValueError, match="创业板"):
        screen_price_bars("300001")


def test_tomorrow_rise_universe_excludes_chinext_and_buy_filter():
    base = dict(
        spot_rows=[
            _spot("300001", "创业龙", 18.0),
            _spot("688001", "科创甲", 10.0),
            _spot("600010", "换手甲", 10.0),
        ],
        zt_rows=[{"代码": "600010", "连板数": "2"}],
        universe="no_chinext",
    )
    watch = _snapshot(**base, only_t1_bias=None)
    watch_codes = [row["code"] for row in watch["rows"]]
    assert "300001" not in watch_codes
    assert "688001" in watch_codes

    buy_only = _snapshot(**base, only_t1_bias="BUY")
    assert [row["code"] for row in buy_only["rows"]] == ["600010"]
    assert buy_only["universe"] == "no_chinext"
    assert all(row["t1_bias"] == "BUY" for row in buy_only["rows"])


def test_flow_labels_use_disclosed_prints_only():
    snap = _snapshot(
        spot_rows=[_spot("600010", "资金甲", 9.0)],
        lhb_rows=[
            {
                "代码": "600010",
                "上榜日期": "2026-09-22",
                "机构买入净额": -100.0,
                "买方机构数": 1,
                "卖方机构数": 3,
            }
        ],
        insider_rows=[
            {
                "代码": "600010",
                "变动日期": "2026-09-20",
                "变动方向": "减持",
                "变动数量": -1000,
            }
        ],
        margin_rows=[
            {
                "证券代码": "600010",
                "信用交易日期": "2026-09-22",
                "融资余额差额": 50.0,
                "融券余量差额": 10.0,
            }
        ],
    )
    row = snap["rows"][0]
    assert row["seat_side"] == "席位净卖"
    assert row["holder_flow"] == "减持"
    assert row["margin_flow"] == "融资增加"
    assert row["short_flow"] == "融券增加"
    assert "做空" not in row["summary"]


def test_missing_flow_stays_unavailable():
    snap = _snapshot(spot_rows=[_spot("600010", "无资金", 8.0)])
    row = snap["rows"][0]
    assert row["seat_side"] == "不可用"
    assert row["holder_flow"] == "不可用"
    assert row["margin_flow"] == "不可用"
    assert row["short_flow"] == "不可用"


def test_screen_rejects_past_date():
    with pytest.raises(ScreenNotLiveError):
        screen_main_board("2020-01-02")


def test_screen_rejects_malformed_date():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        screen_main_board("09-22")


def test_sina_prefix_keeps_main_board_and_derives_amplitude():
    snap = _snapshot(
        quote_source="sina",
        spot_rows=[
            {
                "代码": "sh600010",
                "名称": "包钢股份",
                "涨跌幅": 9.2,
                "最新价": 2.18,
                "今开": 2.05,
                "最高": 2.20,
                "最低": 2.00,
                "昨收": 2.00,
                "成交额": 1_000_000_000,
            },
            {
                "代码": "sz300001",
                "名称": "创业龙",
                "涨跌幅": 18.0,
                "最新价": 11.8,
                "今开": 10.2,
                "最高": 12.0,
                "最低": 10.0,
                "昨收": 10.0,
            },
        ],
        leader_rows=[{"板块": "钢铁", "领涨股": "包钢股份"}],
    )
    assert [row["code"] for row in snap["rows"]] == ["600010"]
    row = snap["rows"][0]
    assert row["ticker"] == "600010.SH"
    assert row["sector"] == "钢铁"
    assert row["is_sector_leader"] is True
    assert row["speed"] is None
    assert row["amplitude"] == pytest.approx(10.0)
    assert snap["quote_source"] == "sina"
    assert "新浪" in snap["note"]
    assert "涨幅榜仍列出" in snap["note"]


def test_missing_spot_note_says_board_unavailable():
    snap = _snapshot(quote_source="")
    assert snap["rows"] == []
    assert "现货榜没有返回" in snap["note"]


def test_screen_falls_back_to_sina_and_ths_when_eastmoney_is_empty(monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()
    seen: list[tuple[str, float | None]] = []

    def fake_try(ak, names, kwargs_list, **kwargs):
        seen.append((names[0], kwargs.get("timeout")))
        if names == ("stock_zh_a_spot_em",):
            return []
        if names == ("stock_zh_a_spot",):
            return [
                {
                    "代码": "sh600519",
                    "名称": "贵州茅台",
                    "涨跌幅": 9.5,
                    "最新价": 10.95,
                    "今开": 10.4,
                    "最高": 11.0,
                    "最低": 10.2,
                    "昨收": 10.0,
                    "成交额": 2_000_000_000,
                }
            ]
        if names == ("stock_board_industry_name_em",):
            return []
        if names == ("stock_board_industry_summary_ths",):
            return [{"板块": "白酒", "领涨股": "贵州茅台"}]
        return []

    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._try_ak_records",
        fake_try,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._load_akshare",
        lambda: object(),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._load_regime",
        lambda ak, as_of: (_high_regime(), []),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._cached",
        lambda key, as_of, channel, loader, ttl_seconds=None: loader() or [],
    )
    snap = screen_main_board(today)
    assert snap["quote_source"] == "sina"
    assert snap["rows"][0]["ticker"] == "600519.SH"
    assert snap["rows"][0]["sector"] == "白酒"
    assert ("stock_zh_a_spot", None) in seen
    assert ("stock_zh_a_spot_tx", None) not in seen
    assert ("stock_board_industry_summary_ths", None) in seen
    assert ("stock_ggcg_em", 8) in seen


def test_screen_falls_back_to_tencent_when_sina_spot_is_empty(monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()
    seen: list[str] = []

    def fake_try(ak, names, kwargs_list, **kwargs):
        seen.append(names[0])
        if names == ("stock_lhb_jgmmtj_em", "stock_lhb_detail_em"):
            assert kwargs_list == (
                {"start_date": today.replace("-", ""), "end_date": today.replace("-", "")},
            )
            return []
        if names == ("stock_zh_a_spot_tx",):
            return [
                {
                    "code": "sh600519",
                    "name": "贵州茅台",
                    "zdf": "9.5",
                    "speed": "1.2",
                    "hsl": "0.8",
                    "lb": "1.5",
                    "zf": "3.1",
                    "zxj": "1500",
                    "turnover": "200000",
                    "ltsz": "18000",
                },
                {
                    "code": "sz300001",
                    "name": "创业龙",
                    "zdf": "18",
                    "speed": "2",
                    "zxj": "11",
                },
            ]
        return []

    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._try_ak_records",
        fake_try,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._load_akshare",
        lambda: object(),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._load_regime",
        lambda ak, as_of: (_high_regime(), []),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._cached",
        lambda key, as_of, channel, loader, ttl_seconds=None: loader() or [],
    )
    snap = screen_main_board(today)
    assert snap["quote_source"] == "tencent"
    assert [row["ticker"] for row in snap["rows"]] == ["600519.SH"]
    row = snap["rows"][0]
    assert row["speed"] == pytest.approx(1.2)
    assert row["turnover"] == pytest.approx(0.8)
    assert row["amount"] == pytest.approx(2_000_000_000)
    assert row["float_mv"] == pytest.approx(1_800_000_000_000)
    assert row["amplitude"] == pytest.approx(3.1)
    assert "腾讯" in snap["note"]
    assert seen.index("stock_zh_a_spot") < seen.index("stock_zh_a_spot_tx")


def test_screen_today_reads_vendors(monkeypatch):
    today = datetime.now(timezone.utc).date().isoformat()

    class _Ak:
        def stock_zh_a_spot_em(self):
            return None

    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._load_akshare",
        lambda: _Ak(),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._load_regime",
        lambda ak, as_of: (_high_regime(), []),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ashare_screen._live_table",
        lambda ak, as_of, channel, loader: [
            _spot("600519", "贵州茅台", 9.5)
        ]
        if channel == "screen_spot"
        else [],
    )
    snap = screen_main_board(today)
    assert snap["rows"][0]["ticker"] == "600519.SH"
    assert snap["as_of"] == today
