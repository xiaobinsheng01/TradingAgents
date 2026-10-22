"""A-share short-horizon tape: limit flags, lagged northbound, events, routing."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

import tradingagents.dataflows.akshare_market as tape
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.news_items import NewsItem
from tradingagents.dataflows.news_warehouse import upsert_items


def _mute_swing_news(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.akshare_news.get_news",
        mock.Mock(side_effect=NoMarketDataError("t", "t", "no news")),
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.akshare_news.get_global_news",
        mock.Mock(side_effect=NoMarketDataError("g", "g", "no news")),
    )


def _hist_frame(end: str, n: int = 25, last_pct: float = 1.2, last_amount: float = 1e8):
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    rows = []
    close = 100.0
    for i in range(n, 0, -1):
        day = (end_dt - timedelta(days=i - 1)).strftime("%Y-%m-%d")
        pct = last_pct if i == 1 else 0.5
        close = round(close * (1 + pct / 100.0), 4)
        rows.append(
            {
                "日期": day,
                "开盘": close * 0.99,
                "最高": close * 1.01,
                "最低": close * 0.98,
                "收盘": close,
                "成交量": 1_000_000 + i,
                "成交额": last_amount if i == 1 else 5e7,
                "振幅": 2.0,
                "涨跌幅": pct,
                "换手率": 1.5 + i / 100.0,
            }
        )
    return pd.DataFrame(rows)


def _index_frame(end: str, n: int = 25):
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    rows = []
    close = 4000.0
    for i in range(n, 0, -1):
        day = (end_dt - timedelta(days=i - 1)).strftime("%Y-%m-%d")
        close *= 1.001
        rows.append(
            {
                "日期": day,
                "开盘": close,
                "最高": close,
                "最低": close,
                "收盘": close,
                "成交额": 1e11,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def cache_dir(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    return tmp_path


def _fake_ak(code="600519", as_of="2026-01-10", last_pct=10.02):
    hist = _hist_frame(as_of, last_pct=last_pct, last_amount=2e8)
    raw = hist.copy()
    raw["成交额"] = raw["成交额"] * 1.1
    return SimpleNamespace(
        stock_zh_a_hist=mock.Mock(
            side_effect=lambda **kwargs: raw if kwargs.get("adjust") == "" else hist
        ),
        stock_zh_index_daily_em=mock.Mock(return_value=_index_frame(as_of)),
        stock_zt_pool_em=mock.Mock(
            return_value=pd.DataFrame([{"代码": "000001", "连板数": 3, "涨跌幅": 10.0}])
        ),
        stock_zt_pool_dtgc_em=mock.Mock(return_value=pd.DataFrame([{"代码": "000002"}])),
        stock_zt_pool_previous_em=mock.Mock(
            return_value=pd.DataFrame([{"代码": "000001", "涨跌幅": 2.5}])
        ),
        stock_hsgt_individual_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "日期": "2026-01-09",
                        "代码": code,
                        "今日持股-增减": 1200.0,
                        "持股占比": 1.2,
                    },
                    {
                        "日期": "2026-01-10",
                        "代码": code,
                        "今日持股-增减": 9999.0,
                        "持股占比": 9.9,
                    },
                ]
            )
        ),
        stock_lhb_detail_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "日期": as_of,
                        "代码": code,
                        "上榜原因": "涨幅偏离值达7%",
                        "机构买入额": 0.35,
                    }
                ]
            )
        ),
        stock_margin_detail_szse=mock.Mock(return_value=pd.DataFrame()),
        stock_restricted_release_queue_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "股票代码": code,
                        "解禁日期": "2026-01-15",
                        "解禁市值": 5000.0,
                    }
                ]
            )
        ),
        stock_individual_info_em=mock.Mock(
            return_value=pd.DataFrame([{"item": "股票简称", "value": "贵州茅台"}])
        ),
        stock_zh_a_hist_min_em=mock.Mock(return_value=pd.DataFrame()),
    )


@pytest.mark.unit
def test_short_horizon_rejects_non_a_share(cache_dir):
    with pytest.raises(NoMarketDataError, match="A-share"):
        tape.get_ashare_short_horizon("AAPL", "2026-01-10")


@pytest.mark.unit
def test_short_horizon_marks_limit_up_and_lags_northbound(cache_dir, monkeypatch):
    fake = _fake_ak(last_pct=10.02)
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "T+1" in out
    assert "limit_up" in out
    assert ",True," in out or "True" in out
    assert "northbound_net_inflow: 1200.0" in out
    assert "northbound_net_inflow: 9999" not in out
    assert "northbound_as_of: 2026-01-09" in out
    assert "dragon_tiger_flag: True" in out
    assert "market_limit_up_count: 1" in out
    assert "## Playbook stance (T+1)" in out
    assert "t1_bias: HOLD" in out
    assert "regime: low" in out
    assert "lift_ban_mv_5d: 5000.0" in out
    assert "ret_5:" in out
    fake.stock_zh_a_hist.assert_called()


@pytest.mark.unit
def test_short_horizon_tags_warehouse_bad_event(cache_dir, monkeypatch):
    upsert_items(
        "600519",
        [
            NewsItem(
                title="控股股东减持计划",
                channel="cninfo",
                pub_date="2026-01-10 18:00:00",
                category="减持",
            )
        ],
    )
    fake = _fake_ak(last_pct=0.5)
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "announce_bad: True" in out
    assert "announce_good: False" in out


@pytest.mark.unit
def test_short_horizon_chinext_uses_20_pct_limit(cache_dir, monkeypatch):
    fake = _fake_ak(code="300750", last_pct=19.99)
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("300750.SZ", "2026-01-10")
    assert "limit_pct: 20.0" in out
    assert "board_type: chinext" in out


@pytest.mark.unit
def test_route_degrades_when_akshare_extra_missing(monkeypatch):
    from tradingagents.dataflows.akshare_news import AkshareNotConfiguredError
    from tradingagents.dataflows.interface import route_to_vendor

    def boom(*args, **kwargs):
        raise AkshareNotConfiguredError("pip install '.[akshare]'")

    with mock.patch.dict(
        "tradingagents.dataflows.interface.VENDOR_METHODS",
        {"get_ashare_short_horizon": {"akshare": boom}},
        clear=False,
    ):
        out = route_to_vendor("get_ashare_short_horizon", "600519.SS", "2026-01-10")
    assert "DATA_UNAVAILABLE" in out
    assert "ashare_tape" in out


@pytest.mark.unit
def test_short_horizon_omits_live_spot_on_historical_as_of(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_bid_ask_em = mock.Mock(
        return_value=pd.DataFrame([{"item": "最新", "value": 1480.0}])
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "Live snapshot" not in out
    fake.stock_bid_ask_em.assert_not_called()


@pytest.mark.unit
def test_short_horizon_attaches_live_spot_on_today(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_bid_ask_em = mock.Mock(
        return_value=pd.DataFrame(
            [
                {"item": "最新", "value": 1480.5},
                {"item": "涨跌幅", "value": 1.25},
                {"item": "时间", "value": "14:32:01"},
            ]
        )
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr(tape, "is_live_as_of", lambda _as_of: True)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "Live snapshot" in out
    assert "last: 1480.5" in out
    assert "never places orders" in out
    fake.stock_bid_ask_em.assert_called()


@pytest.mark.unit
def test_akshare_stock_data_rejects_us_ticker():
    with pytest.raises(NoMarketDataError, match="A-share"):
        tape.get_akshare_stock_data("AAPL", "2026-01-01", "2026-01-10")


@pytest.mark.unit
def test_akshare_stock_data_emits_csv(monkeypatch):
    fake = _fake_ak()
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_akshare_stock_data("601061.SH", "2026-01-01", "2026-01-10")
    assert "# Source: akshare/AKTools" in out
    assert "Date,Open,High,Low,Close,Adj Close,Volume" in out
    assert "2026-01-10" in out
    fake.stock_zh_a_hist.assert_called()


@pytest.mark.unit
def test_akshare_stock_data_falls_back_to_tencent_when_eastmoney_rst(monkeypatch):
    tx_rows = [
        {
            "date": "2026-01-10T00:00:00.000",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1000,
        }
    ]
    fake = SimpleNamespace(
        stock_zh_a_hist=mock.Mock(side_effect=RuntimeError("Connection aborted")),
        stock_zh_a_hist_tx=mock.Mock(return_value=tx_rows),
        stock_zh_a_daily=mock.Mock(side_effect=AssertionError("daily should not run")),
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_akshare_stock_data("601061.SH", "2026-01-01", "2026-01-10")
    assert "# Source: akshare/AKTools" in out
    assert "10.5" in out
    assert fake.stock_zh_a_hist_tx.call_args.kwargs["symbol"] == "sh601061"
    fake.stock_zh_a_daily.assert_not_called()


@pytest.mark.unit
def test_resolve_a_share_identity_uses_name_and_syntactic_board(monkeypatch):
    fake = SimpleNamespace(
        stock_individual_info_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {"item": "股票简称", "value": "中信金属"},
                    {"item": "行业", "value": "有色金属"},
                ]
            )
        ),
        stock_info_a_code_name=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    identity = tape.resolve_a_share_identity("601061.SH")
    assert identity["company_name"] == "中信金属"
    assert identity["industry"] == "有色金属"
    assert identity["exchange"] == "SSE"
    assert identity["board_type"] == "main"
    assert identity["market"] == "China A-share"


@pytest.mark.unit
def test_stock_name_does_not_take_first_row_of_code_table(monkeypatch):
    listing = pd.DataFrame(
        [
            {"代码": "000001", "名称": "平安银行"},
            {"代码": "601061", "名称": "中信金属"},
            {"代码": "600519", "名称": "贵州茅台"},
        ]
    )
    fake = SimpleNamespace(
        stock_individual_info_em=mock.Mock(side_effect=RuntimeError("500")),
        stock_info_a_code_name=mock.Mock(return_value=listing),
    )
    assert tape._stock_name(fake, "601061") == "中信金属"
    assert fake.stock_info_a_code_name.call_args.kwargs.get("symbol") == "601061"


@pytest.mark.unit
def test_index_daily_falls_back_to_tencent_when_eastmoney_empty(monkeypatch):
    tx = [
        {"date": "2026-01-09", "open": 4000, "high": 4010, "low": 3990, "close": 4005},
        {"date": "2026-01-10", "open": 4005, "high": 4020, "low": 4000, "close": 4010},
    ]
    fake = SimpleNamespace(
        stock_zh_index_daily_em=mock.Mock(side_effect=RuntimeError("RST")),
        index_zh_a_hist=mock.Mock(return_value=[]),
        stock_zh_index_daily=mock.Mock(return_value=tx),
        stock_zh_index_daily_tx=mock.Mock(side_effect=AssertionError("tx should not run")),
    )
    rows = tape._fetch_index_daily(fake, "2026-01-10", "2025-12-01", "sh000300")
    assert rows[-1]["close"] == 4010
    fake.stock_zh_index_daily.assert_called()
    fake.stock_zh_index_daily_tx.assert_not_called()


@pytest.mark.unit
def test_minutes_fall_back_to_tencent_when_eastmoney_rst(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_zh_a_hist_min_em = mock.Mock(side_effect=RuntimeError("RST"))
    fake.stock_zh_a_minute = mock.Mock(
        return_value=pd.DataFrame(
            [
                {
                    "时间": "2026-01-10 09:30:00",
                    "收盘": 101.0,
                    "成交额": 1e7,
                },
                {
                    "时间": "2026-01-10 09:45:00",
                    "收盘": 101.5,
                    "成交额": 8e6,
                },
            ]
        )
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "auction_pct:" in out
    assert "unavailable" not in out.split("auction_pct:")[1].splitlines()[0]
    assert fake.stock_zh_a_minute.call_args.kwargs["symbol"] == "sh600519"


@pytest.mark.unit
def test_live_spot_falls_back_to_xueqiu_when_bid_ask_rst(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_bid_ask_em = mock.Mock(side_effect=RuntimeError("RST"))
    fake.stock_individual_spot_xq = mock.Mock(
        return_value=pd.DataFrame(
            [{"代码": "600519", "最新": 1488.0, "涨跌幅": 0.5, "时间": "14:01:00"}]
        )
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr(tape, "is_live_as_of", lambda _as_of: True)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "last: 1488.0" in out
    fake.stock_individual_spot_xq.assert_called()


@pytest.mark.unit
def test_live_breadth_falls_back_to_sina_spot(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_zt_pool_em = mock.Mock(side_effect=RuntimeError("RST"))
    fake.stock_zt_pool_dtgc_em = mock.Mock(return_value=pd.DataFrame())
    fake.stock_zt_pool_zbgc_em = mock.Mock(return_value=pd.DataFrame())
    fake.stock_zh_a_spot = mock.Mock(
        return_value=pd.DataFrame(
            [
                {"代码": "000001", "涨跌幅": 10.0},
                {"代码": "000002", "涨跌幅": 9.9},
                {"代码": "600000", "涨跌幅": -10.0},
                {"代码": "600519", "涨跌幅": 0.5},
            ]
        )
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr(tape, "is_live_as_of", lambda _as_of: True)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "market_limit_up_count: 2" in out
    assert "market_limit_down_count: 1" in out
    assert "market_breadth_source: sina_spot_live_approx" in out


@pytest.mark.unit
def test_historical_as_of_does_not_use_sina_spot_for_breadth(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_zt_pool_em = mock.Mock(side_effect=RuntimeError("RST"))
    fake.stock_zt_pool_dtgc_em = mock.Mock(return_value=pd.DataFrame())
    fake.stock_zh_a_spot = mock.Mock(return_value=pd.DataFrame([{"代码": "000001", "涨跌幅": 10.0}]))
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "market_limit_up_count: 0" in out
    fake.stock_zh_a_spot.assert_not_called()


@pytest.mark.unit
def test_lhb_falls_back_to_sina_when_eastmoney_empty(cache_dir, monkeypatch):
    fake = _fake_ak()
    fake.stock_lhb_detail_em = mock.Mock(side_effect=RuntimeError("RST"))
    fake.stock_lhb_stock_detail_em = mock.Mock(return_value=pd.DataFrame())
    fake.stock_lhb_stock_statistic_em = mock.Mock(return_value=pd.DataFrame())
    fake.stock_lhb_detail_daily_sina = mock.Mock(
        return_value=pd.DataFrame(
            [
                {
                    "日期": "2026-01-10",
                    "代码": "600519",
                    "上榜原因": "换手率达20%",
                    "机构买入额": 0.2,
                }
            ]
        )
    )
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "dragon_tiger_flag: True" in out
    fake.stock_lhb_detail_daily_sina.assert_called()


@pytest.mark.unit
def test_ak_index_symbol_does_not_map_sse_composite_to_sz000001():
    assert tape.ak_index_symbol("000001.SS") == "sh000001"
    assert tape.ak_index_symbol("399001.SZ") == "sz399001"
    assert tape.ak_index_symbol("sh000300") == "sh000300"


@pytest.mark.unit
def test_realized_holding_returns_uses_daily_and_index(monkeypatch):
    monkeypatch.setattr(
        tape,
        "load_close_pairs",
        lambda ticker, start, end: [
            ("2026-01-05", 10.0),
            ("2026-01-06", 10.5),
            ("2026-01-07", 11.0),
            ("2026-01-08", 11.0),
            ("2026-01-09", 11.5),
            ("2026-01-12", 12.0),
        ],
    )
    monkeypatch.setattr(
        tape,
        "load_index_close_pairs",
        lambda symbol, start, end: [
            ("2026-01-05", 100.0),
            ("2026-01-06", 101.0),
            ("2026-01-07", 102.0),
            ("2026-01-08", 103.0),
            ("2026-01-09", 104.0),
            ("2026-01-12", 105.0),
        ],
    )
    raw, alpha, days, resolved = tape.realized_holding_returns(
        "601061.SH", "2026-01-05", 5, "000001.SS"
    )
    assert days == 5
    assert resolved == "2026-01-12"
    assert abs(raw - 0.2) < 1e-9
    assert abs(alpha - (0.2 - 0.05)) < 1e-9


@pytest.mark.unit
def test_match_exposure_maps_you_se_to_copper_and_aluminum():
    rule = tape.match_exposure("有色金属", "中信金属")
    assert rule is not None
    assert rule.industry_name == "有色金属"
    assert rule.index_symbol == "sh000819"
    assert rule.commodities == (("沪铜", "CU0"), ("沪铝", "AL0"))
    assert rule.intl_commodities == (("LME铜", "CAD"), ("COMEX铜", "HG"))


@pytest.mark.unit
def test_match_exposure_copper_keyword_beats_generic_metal():
    rule = tape.match_exposure("铜", "江西铜业")
    assert rule is not None
    assert rule.industry_name == "铜"
    assert rule.commodities == (("沪铜", "CU0"),)
    assert rule.intl_commodities == (("LME铜", "CAD"), ("COMEX铜", "HG"))


@pytest.mark.unit
def test_match_exposure_bank_maps_index_not_silver():
    rule = tape.match_exposure("银行", "招商银行")
    assert rule is not None
    assert rule.industry_name == "银行"
    assert rule.commodities == ()
    assert rule.intl_commodities == ()
    assert tape.match_exposure("", "贵州茅台") is None


@pytest.mark.unit
def test_match_exposure_covers_non_copper_sectors():
    lithium = tape.match_exposure("能源金属", "天齐锂业")
    assert lithium is not None
    assert lithium.industry_name == "锂"
    assert lithium.commodities == (("碳酸锂", "LC0"),)
    assert lithium.intl_commodities == ()

    nickel = tape.match_exposure("有色金属", "青山不锈钢")
    assert nickel is not None
    assert nickel.industry_name == "镍"
    assert nickel.commodities == (("沪镍", "NI0"),)
    assert nickel.intl_commodities == (("LME镍", "NID"),)

    steel = tape.match_exposure("钢铁", "宝钢股份")
    assert steel is not None
    assert steel.commodities[0] == ("铁矿石", "I0")
    assert steel.intl_commodities == (("SGX铁矿", "FEF"),)

    feed = tape.match_exposure("饲料", "海大集团")
    assert feed is not None
    assert feed.commodities == (("豆粕", "M0"),)
    assert feed.intl_commodities == (("CBOT豆粕", "SM"),)

    rubber = tape.match_exposure("橡胶", "海南橡胶")
    assert rubber is not None
    assert rubber.intl_commodities == (("TOCOM橡胶", "TRB"),)

    liquor = tape.match_exposure("白酒", "贵州茅台")
    assert liquor is not None
    assert liquor.industry_name == "白酒"
    assert liquor.commodities == ()
    assert "CU0" not in str(liquor.commodities)

    battery = tape.match_exposure("电池", "宁德时代")
    assert battery is not None
    assert battery.commodities == (("碳酸锂", "LC0"),)


@pytest.mark.unit
def test_short_horizon_attaches_copper_map_for_citic_metal(cache_dir, monkeypatch):
    fake = _fake_ak(code="601061", last_pct=0.5)
    fake.stock_individual_info_em = mock.Mock(
        return_value=pd.DataFrame(
            [
                {"item": "股票简称", "value": "中信金属"},
                {"item": "行业", "value": "有色金属"},
            ]
        )
    )
    fake.futures_zh_daily_sina = mock.Mock(return_value=_index_frame("2026-01-10"))
    fake.futures_foreign_hist = mock.Mock(return_value=_index_frame("2026-01-10"))
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("601061.SH", "2026-01-10")
    assert "industry_map: 有色金属" in out
    assert "industry_index: sh000819" in out
    assert "沪铜 CU0" in out
    assert "沪铝 AL0" in out
    assert "LME铜 CAD" in out
    assert "COMEX铜 HG" in out
    assert "stock_vs_industry_5d:" in out
    assert "do not invent" in out
    fake.futures_zh_daily_sina.assert_called()
    symbols = [call.kwargs.get("symbol") for call in fake.futures_foreign_hist.call_args_list]
    assert "CAD" in symbols
    assert "HG" in symbols


@pytest.mark.unit
def test_short_horizon_unmapped_name_does_not_invent_copper(cache_dir, monkeypatch):
    fake = _fake_ak()
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    out = tape.get_ashare_short_horizon("600519.SS", "2026-01-10")
    assert "沪铜" not in out
    assert "LME铜" not in out
    assert "no static industry/commodity map" in out
    assert "commodity_1: <unavailable>" in out
    assert "intl_commodity_1: <unavailable>" in out


@pytest.mark.unit
def test_futures_daily_drops_bars_after_as_of():
    fake = SimpleNamespace(
        futures_zh_daily_sina=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {"date": "2026-01-09", "close": 100.0},
                    {"date": "2026-01-10", "close": 101.0},
                    {"date": "2026-01-11", "close": 999.0},
                ]
            )
        ),
        futures_main_sina=mock.Mock(side_effect=AssertionError("daily should not run")),
    )
    rows = tape._fetch_futures_daily(fake, "CU0", "2026-01-10")
    assert [row["close"] for row in rows] == [100.0, 101.0]


@pytest.mark.unit
def test_intl_futures_daily_drops_bars_after_as_of():
    fake = SimpleNamespace(
        futures_foreign_hist=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {"date": "2026-01-09", "close": 9000.0},
                    {"date": "2026-01-10", "close": 9100.0},
                    {"date": "2026-01-11", "close": 9999.0},
                ]
            )
        ),
        futures_hf_hist=mock.Mock(side_effect=AssertionError("foreign hist already filled")),
    )
    rows = tape._fetch_intl_futures_daily(fake, "CAD", "2026-01-10")
    assert [row["close"] for row in rows] == [9000.0, 9100.0]


@pytest.mark.unit
def test_intl_futures_falls_back_to_east_money_chinese_name():
    fake = SimpleNamespace(
        futures_foreign_hist=mock.Mock(return_value=pd.DataFrame()),
        futures_hf_hist=mock.Mock(return_value=pd.DataFrame()),
        futures_global_hist_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {"date": "2026-01-09", "close": 80.0},
                    {"date": "2026-01-10", "close": 82.0},
                    {"date": "2026-01-11", "close": 999.0},
                ]
            )
        ),
        futures_foreign_hist_em=mock.Mock(side_effect=AssertionError("em hist already filled")),
    )
    rows = tape._fetch_intl_futures_daily(fake, "CAD", "2026-01-10")
    assert [row["close"] for row in rows] == [80.0, 82.0]
    assert fake.futures_global_hist_em.call_args.kwargs["symbol"] == "LME铜"


@pytest.mark.unit
def test_industry_series_falls_back_to_index_when_board_hist_rst():
    fake = SimpleNamespace(
        stock_board_industry_hist_em=mock.Mock(side_effect=RuntimeError("RST")),
        stock_board_industry_index_ths=mock.Mock(return_value=pd.DataFrame()),
        stock_zh_index_daily_em=mock.Mock(return_value=_index_frame("2026-01-10")),
        index_zh_a_hist=mock.Mock(return_value=pd.DataFrame()),
        stock_zh_index_daily=mock.Mock(side_effect=AssertionError("tencent not needed")),
    )
    rule = tape.match_exposure("有色金属", "")
    rows = tape._fetch_industry_series(fake, "2026-01-10", "2025-12-01", rule)
    assert rows[-1]["date"] == "2026-01-10"
    fake.stock_zh_index_daily_em.assert_called()
    assert fake.stock_zh_index_daily_em.call_args.kwargs["symbol"] == "sh000819"


@pytest.mark.unit
def test_industry_series_retries_unprefixed_csi_symbol():
    def _index(**kwargs):
        if kwargs.get("symbol") == "000819":
            return _index_frame("2026-01-10")
        return pd.DataFrame()

    fake = SimpleNamespace(
        stock_board_industry_hist_em=mock.Mock(return_value=pd.DataFrame()),
        stock_board_industry_index_ths=mock.Mock(return_value=pd.DataFrame()),
        stock_zh_index_daily_em=mock.Mock(side_effect=_index),
        index_zh_a_hist=mock.Mock(return_value=pd.DataFrame()),
        stock_zh_index_daily=mock.Mock(return_value=pd.DataFrame()),
        stock_zh_index_daily_tx=mock.Mock(return_value=pd.DataFrame()),
    )
    rule = tape.match_exposure("有色金属", "")
    rows = tape._fetch_industry_series(fake, "2026-01-10", "2025-12-01", rule)
    assert rows[-1]["date"] == "2026-01-10"
    symbols = [call.kwargs.get("symbol") for call in fake.stock_zh_index_daily_em.call_args_list]
    assert "sh000819" in symbols
    assert "000819" in symbols


@pytest.mark.unit
def test_futures_daily_falls_back_to_east_money_hist():
    fake = SimpleNamespace(
        futures_zh_daily_sina=mock.Mock(return_value=pd.DataFrame()),
        futures_main_sina=mock.Mock(return_value=pd.DataFrame()),
        futures_hist_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {"date": "2026-01-09", "close": 80.0},
                    {"date": "2026-01-10", "close": 82.0},
                    {"date": "2026-01-11", "close": 999.0},
                ]
            )
        ),
        futures_zh_daily=mock.Mock(side_effect=AssertionError("em hist already filled")),
    )
    rows = tape._fetch_futures_daily(fake, "CU0", "2026-01-10")
    assert [row["close"] for row in rows] == [80.0, 82.0]
    assert fake.futures_hist_em.call_args.kwargs["symbol"] == "CU"


@pytest.mark.unit
def test_next_session_raw_return_uses_second_bar_only(monkeypatch):
    monkeypatch.setattr(
        tape,
        "load_close_pairs",
        lambda ticker, start, end: [
            ("2026-01-05", 10.0),
            ("2026-01-06", 10.5),
            ("2026-01-07", 20.0),
        ],
    )
    raw, nxt = tape.next_session_raw_return("601061.SH", "2026-01-05")
    assert nxt == "2026-01-06"
    assert abs(raw - 0.05) < 1e-9


@pytest.mark.unit
def test_next_session_raw_return_none_until_next_bar(monkeypatch):
    monkeypatch.setattr(
        tape,
        "load_close_pairs",
        lambda ticker, start, end: [("2026-01-05", 10.0)],
    )
    assert tape.next_session_raw_return("601061.SH", "2026-01-05") is None


@pytest.mark.unit
def test_event_flags_live_empty_warehouse_ingests_once(cache_dir, monkeypatch):
    called = {}

    def fake_ingest(ticker, curr_date=None, include_global=False):
        called["ticker"] = ticker
        called["curr_date"] = curr_date
        called["include_global"] = include_global
        upsert_items(
            ticker,
            [
                NewsItem(
                    title="控股股东减持计划",
                    channel="cninfo",
                    pub_date="2026-09-18 10:00:00",
                    category="减持",
                )
            ],
        )
        return []

    monkeypatch.setattr(tape, "is_live_as_of", lambda as_of: True)
    monkeypatch.setattr("tradingagents.dataflows.news_ingest.ingest_news", fake_ingest)
    flags = tape._event_flags("601061", "2026-09-18", False)
    assert called == {
        "ticker": "601061",
        "curr_date": "2026-09-18",
        "include_global": True,
    }
    assert flags["announce_bad"] is True
    assert flags["event_item_count"] == 1


@pytest.mark.unit
def test_event_flags_historical_does_not_ingest(cache_dir, monkeypatch):
    monkeypatch.setattr(tape, "is_live_as_of", lambda as_of: False)

    def boom(*args, **kwargs):
        raise AssertionError("historical as-of must not ingest")

    monkeypatch.setattr("tradingagents.dataflows.news_ingest.ingest_news", boom)
    flags = tape._event_flags("601061", "2026-01-10", False)
    assert flags["event_item_count"] == 0
    assert flags["announce_bad"] is False


@pytest.mark.unit
def test_swing_tape_rejects_non_a_share(cache_dir):
    with pytest.raises(NoMarketDataError, match="A-share"):
        tape.get_ashare_swing_tape("AAPL", "2026-01-10", "half_month")


@pytest.mark.unit
def test_swing_tape_rejects_unknown_window(cache_dir):
    with pytest.raises(ValueError, match="half_month"):
        tape.get_ashare_swing_tape("600519.SS", "2026-01-10", "decade")


@pytest.mark.unit
def test_swing_tape_half_month_stats_drop_lookahead(cache_dir, monkeypatch):
    fake = _fake_ak(last_pct=0.5)
    orig = fake.stock_zh_a_hist.side_effect

    def with_future(**kwargs):
        frame = orig(**kwargs)
        leak = frame.iloc[[-1]].copy()
        leak["日期"] = "2026-01-20"
        leak["收盘"] = 999.0
        return pd.concat([frame, leak], ignore_index=True)

    fake.stock_zh_a_hist.side_effect = with_future
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr("tradingagents.dataflows.akshare_flow._load_akshare", lambda: fake)
    _mute_swing_news(monkeypatch)
    out = tape.get_ashare_swing_tape("600519.SS", "2026-01-10", "half_month")
    assert "近半个月" in out
    assert "ret_window:" in out
    assert "avg_volume:" in out
    assert "never places orders" in out.lower()
    assert "2026-01-20" not in out
    assert "999.0" not in out
    assert "NO_DATA_AVAILABLE" in out or "增减持" in out


@pytest.mark.unit
def test_swing_tape_half_year_includes_weekly_bars(cache_dir, monkeypatch):
    fake = _fake_ak(last_pct=0.5)
    long_hist = _hist_frame("2026-01-10", n=200, last_pct=0.5)
    fake.stock_zh_a_hist.side_effect = lambda **kwargs: long_hist
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr("tradingagents.dataflows.akshare_flow._load_akshare", lambda: fake)
    _mute_swing_news(monkeypatch)
    out = tape.get_ashare_swing_tape("600519.SS", "2026-01-10", "half_year")
    assert "近半年" in out
    assert "Weekly last bars" in out
    assert "ret_60:" in out
    assert "ret_120:" in out


@pytest.mark.unit
def test_swing_tape_includes_window_news_for_prediction(cache_dir, monkeypatch):
    fake = _fake_ak(last_pct=0.5)
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr("tradingagents.dataflows.akshare_flow._load_akshare", lambda: fake)

    def fake_news(ticker, start, end):
        assert ticker == "600519.SS"
        assert start == "2025-12-26"
        assert end == "2026-01-10"
        return "## 600519.SS news, from 2025-12-26 to 2026-01-10:\n\n- 公司回购公告"

    def fake_global(curr_date, look_back_days=None, limit=None):
        assert curr_date == "2026-01-10"
        assert look_back_days == 15
        return "## CCTV and regulator policy\n\n- 证监会例会"

    monkeypatch.setattr("tradingagents.dataflows.akshare_news.get_news", fake_news)
    monkeypatch.setattr(
        "tradingagents.dataflows.akshare_news.get_global_news", fake_global
    )
    out = tape.get_ashare_swing_tape("600519.SS", "2026-01-10", "half_month")
    assert "Window news" in out
    assert "公司回购公告" in out
    assert "证监会例会" in out
    assert "Do not invent headlines" in out


@pytest.mark.unit
def test_swing_tape_keeps_prices_when_news_missing(cache_dir, monkeypatch):
    fake = _fake_ak(last_pct=0.5)
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr("tradingagents.dataflows.akshare_flow._load_akshare", lambda: fake)
    _mute_swing_news(monkeypatch)
    out = tape.get_ashare_swing_tape("600519.SS", "2026-01-10", "half_month")
    assert "ret_window:" in out
    assert "Do not invent headlines" in out
    assert "NO_DATA_AVAILABLE" in out


def _zigzag_hist(end: str) -> pd.DataFrame:
    """Enough directional bars for a confirmed 笔/中枢 without lookahead."""
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    pairs = [
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
        (12.5, 11.0),
        (13.0, 11.4),
        (12.6, 10.8),
        (11.2, 9.5),
        (10.0, 8.2),
        (10.8, 9.0),
        (12.0, 10.2),
        (13.5, 11.5),
        (13.0, 11.0),
    ]
    rows = []
    close = 10.0
    for i, (high, low) in enumerate(pairs):
        day = (end_dt - timedelta(days=len(pairs) - 1 - i)).strftime("%Y-%m-%d")
        close = round((high + low) / 2.0, 4)
        rows.append(
            {
                "日期": day,
                "开盘": close,
                "最高": high,
                "最低": low,
                "收盘": close,
                "成交量": 1_000_000,
                "成交额": 5e7,
                "振幅": 2.0,
                "涨跌幅": 0.5,
                "换手率": 1.5,
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.unit
def test_swing_tape_includes_chanlun_structure(cache_dir, monkeypatch):
    fake = _fake_ak(last_pct=0.5)
    hist = _zigzag_hist("2026-01-10")
    fake.stock_zh_a_hist.side_effect = lambda **kwargs: hist
    monkeypatch.setattr(tape, "_load_akshare", lambda: fake)
    monkeypatch.setattr("tradingagents.dataflows.akshare_flow._load_akshare", lambda: fake)
    _mute_swing_news(monkeypatch)
    out = tape.get_ashare_swing_tape("600519.SS", "2026-01-10", "half_month")
    assert "## 缠论 (daily, as-of 2026-01-10)" in out
    assert "Recent 笔" in out
    assert "Do not invent missing 分型" in out or "not an order" in out
    assert "never places orders" in out.lower()
