"""A-share disclosed buy/sell flow: 增减持, 龙虎席位, 大宗."""

from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

import tradingagents.dataflows.akshare_flow as flow
from tradingagents.dataflows.errors import NoMarketDataError


def _ak(**overrides):
    base = {
        "stock_ggcg_em": mock.Mock(return_value=pd.DataFrame()),
        "stock_inner_trade_xq": mock.Mock(return_value=pd.DataFrame()),
        "stock_management_change_ths": mock.Mock(return_value=pd.DataFrame()),
        "stock_hold_management_detail_em": mock.Mock(return_value=pd.DataFrame()),
        "stock_share_hold_change_cninfo": mock.Mock(return_value=pd.DataFrame()),
        "stock_changes_em": mock.Mock(return_value=pd.DataFrame()),
        "stock_lhb_stock_detail_em": mock.Mock(return_value=pd.DataFrame()),
        "stock_lhb_detail_em": mock.Mock(return_value=pd.DataFrame()),
        "stock_lhb_stock_statistic_em": mock.Mock(return_value=pd.DataFrame()),
        "stock_lhb_detail_daily_sina": mock.Mock(return_value=pd.DataFrame()),
        "stock_dzjy_mrmx": mock.Mock(return_value=pd.DataFrame()),
        "stock_dzjy_sctj": mock.Mock(return_value=pd.DataFrame()),
        "stock_dzjy_hygtj": mock.Mock(return_value=pd.DataFrame()),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.unit
def test_insider_flow_rejects_non_a_share():
    with pytest.raises(NoMarketDataError, match="A-share"):
        flow.get_insider_transactions("AAPL", "2026-01-10")


@pytest.mark.unit
def test_insider_flow_keeps_this_code_and_drops_others(monkeypatch):
    fake = _ak(
        stock_ggcg_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "代码": "000001",
                        "变动日期": "2026-01-05",
                        "姓名": "张三",
                        "变动方向": "增持",
                        "变动数量": 1000,
                    },
                    {
                        "代码": "601061",
                        "变动日期": "2026-01-08",
                        "姓名": "李四",
                        "变动方向": "减持",
                        "变动数量": -2000,
                    },
                    {
                        "代码": "601061",
                        "变动日期": "2026-06-01",
                        "姓名": "未来",
                        "变动方向": "增持",
                        "变动数量": 9,
                    },
                ]
            )
        )
    )
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    out = flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert "李四" in out
    assert "减持" in out or "sell" in out
    assert "张三" not in out
    assert "未来" not in out
    assert "never an order" in out.lower()


@pytest.mark.unit
def test_insider_flow_lhb_seats_are_buy_and_sell(monkeypatch):
    fake = _ak(
        stock_lhb_stock_detail_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "日期": "2026-01-10",
                        "代码": "601061",
                        "营业部名称": "中信证券上海",
                        "买入金额": 1200,
                        "卖出金额": 100,
                        "上榜原因": "涨幅偏离值达7%",
                    },
                    {
                        "日期": "2026-01-10",
                        "代码": "601061",
                        "营业部名称": "华泰证券深圳",
                        "买入金额": 50,
                        "卖出金额": 800,
                    },
                    {
                        "日期": "2026-01-10",
                        "代码": "000001",
                        "营业部名称": "别人的席位",
                        "买入金额": 9999,
                        "卖出金额": 9999,
                    },
                ]
            )
        )
    )
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    out = flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert "中信证券上海" in out
    assert "华泰证券深圳" in out
    assert "别人的席位" not in out
    assert "龙虎榜" in out


@pytest.mark.unit
def test_insider_flow_empty_is_no_data_not_invented(monkeypatch):
    monkeypatch.setattr(flow, "_load_akshare", lambda: _ak())
    out = flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert out.startswith("NO_DATA_AVAILABLE")
    assert "Do not invent" in out


@pytest.mark.unit
def test_insider_flow_does_not_call_unparameterized(monkeypatch):
    calls: list[dict] = []

    def ggcg(**kwargs):
        calls.append(dict(kwargs))
        if not kwargs:
            raise AssertionError("must not fetch the full 增减持 table")
        return pd.DataFrame()

    fake = _ak(stock_ggcg_em=ggcg)
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert calls
    assert all(call for call in calls)


@pytest.mark.unit
def test_route_insider_uses_akshare_before_yfinance():
    from tradingagents.dataflows import interface

    def fake_ak(ticker, curr_date=None):
        return f"AK-FLOW:{ticker}"

    def fake_yf(ticker, curr_date=None):
        raise AssertionError("yfinance should not run after akshare success")

    with mock.patch.dict(
        interface.VENDOR_METHODS["get_insider_transactions"],
        {"akshare": fake_ak, "yfinance": fake_yf},
        clear=False,
    ):
        out = interface.route_to_vendor("get_insider_transactions", "601061.SH", "2026-01-10")
    assert out == "AK-FLOW:601061.SH"


@pytest.mark.unit
def test_yfinance_skips_a_share_insider():
    from tradingagents.dataflows.y_finance import get_insider_transactions as yf_insider

    with pytest.raises(NoMarketDataError, match="A-share"):
        yf_insider("601061.SH", "2026-01-10")


@pytest.mark.unit
def test_buy_sell_window_keeps_in_range_rows(monkeypatch):
    fake = _ak(
        stock_ggcg_em=mock.Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "代码": "601061",
                        "变动日期": "2025-12-28",
                        "姓名": "窗口内",
                        "变动方向": "增持",
                        "变动数量": 1000,
                    },
                    {
                        "代码": "601061",
                        "变动日期": "2025-06-01",
                        "姓名": "窗口外",
                        "变动方向": "减持",
                        "变动数量": -1,
                    },
                ]
            )
        )
    )
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    out = flow.render_buy_sell_window("601061.SH", "2025-12-26", "2026-01-10")
    assert "窗口内" in out
    assert "窗口外" not in out
    assert "never an order" in out.lower()


@pytest.mark.unit
def test_insider_uses_exchange_code_and_not_pankou_changes(monkeypatch):
    sse_calls: list[dict] = []

    def sse(**kwargs):
        sse_calls.append(dict(kwargs))
        return pd.DataFrame(
            [
                {
                    "公司代码": "601061",
                    "姓名": "交易所披露",
                    "变动数": 1000,
                    "变动原因": "二级市场买卖",
                    "变动日期": "2026-01-08",
                }
            ]
        )

    fake = _ak(stock_share_hold_change_sse=sse)
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    out = flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert sse_calls == [{"symbol": "601061"}]
    assert ".SH" not in str(sse_calls)
    assert fake.stock_ggcg_em.call_count == 0
    assert fake.stock_changes_em.call_count == 0
    assert "交易所披露" in out


@pytest.mark.unit
def test_ggcg_symbol_is_category_not_ticker(monkeypatch):
    calls: list[dict] = []

    def ggcg(**kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("symbol") in {"601061", "sh601061", "SH601061"}:
            raise AssertionError("stock code is not a ggcg symbol")
        return pd.DataFrame(
            [
                {
                    "代码": "601061",
                    "变动日期": "2026-01-08",
                    "股东名称": "类别增持",
                    "持股变动信息-增减": "增持",
                    "持股变动信息-变动数量": 10,
                }
            ]
        )

    fake = _ak(stock_ggcg_em=ggcg)
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    out = flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert calls == [{"symbol": "股东增持"}]
    assert "类别增持" in out


@pytest.mark.unit
def test_lhb_calls_match_documented_signatures(monkeypatch):
    seen: dict[str, list[dict]] = {"list": [], "seats": [], "sina": []}

    def detail_list(**kwargs):
        seen["list"].append(dict(kwargs))
        if "symbol" in kwargs or "date" in kwargs:
            raise AssertionError(kwargs)
        return pd.DataFrame()

    def seats(**kwargs):
        seen["seats"].append(dict(kwargs))
        if set(kwargs) != {"symbol", "date", "flag"}:
            raise AssertionError(kwargs)
        return pd.DataFrame()

    def sina(**kwargs):
        seen["sina"].append(dict(kwargs))
        if set(kwargs) != {"date"}:
            raise AssertionError(kwargs)
        return pd.DataFrame(
            [
                {
                    "股票代码": "601061",
                    "指标": "涨幅偏离值达7%",
                    "成交额": 12,
                }
            ]
        )

    fake = _ak(
        stock_lhb_detail_em=detail_list,
        stock_lhb_stock_detail_em=seats,
        stock_lhb_detail_daily_sina=sina,
    )
    monkeypatch.setattr(flow, "_load_akshare", lambda: fake)
    out = flow.get_insider_transactions("601061.SH", "2026-01-10")
    assert seen["list"] == [{"start_date": "20260110", "end_date": "20260110"}]
    assert {item["flag"] for item in seen["seats"]} == {"买入", "卖出"}
    assert all(item["symbol"] == "601061" and item["date"] == "20260110" for item in seen["seats"])
    assert seen["sina"] == [{"date": "20260110"}]
    assert "涨幅偏离" in out
