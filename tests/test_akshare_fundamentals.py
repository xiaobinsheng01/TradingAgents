"""A-share fundamentals via AKTools; Yahoo is not the A-share path."""

from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

import tradingagents.dataflows.akshare_fundamentals as fund
from tradingagents.dataflows.errors import NoMarketDataError


def _info_frame():
    return pd.DataFrame(
        [
            {"item": "股票简称", "value": "中信金属"},
            {"item": "行业", "value": "有色金属"},
        ]
    )


def _ratio_frame():
    return pd.DataFrame(
        [
            {"日期": "2025-12-31", "净资产收益率": 8.1, "市盈率": 12.0},
            {"日期": "2026-03-31", "净资产收益率": 9.2, "市盈率": 11.0},
            {"日期": "2026-09-30", "净资产收益率": 99.0, "市盈率": 99.0},
        ]
    )


def _sheet_frame():
    return pd.DataFrame(
        [
            {
                "REPORT_DATE": "2025-12-31",
                "REPORT_TYPE": "年报",
                "货币资金": 100.0,
            },
            {
                "REPORT_DATE": "2026-03-31",
                "REPORT_TYPE": "一季报",
                "货币资金": 110.0,
            },
            {
                "REPORT_DATE": "2026-09-30",
                "REPORT_TYPE": "三季报",
                "货币资金": 999.0,
            },
        ]
    )


@pytest.mark.unit
def test_akshare_fundamentals_rejects_non_a_share():
    with pytest.raises(NoMarketDataError, match="A-share"):
        fund.get_fundamentals("AAPL", "2026-06-01")


@pytest.mark.unit
def test_get_fundamentals_drops_rows_after_as_of(monkeypatch):
    fake = SimpleNamespace(
        stock_individual_info_em=mock.Mock(return_value=_info_frame()),
        stock_financial_analysis_indicator_em=mock.Mock(return_value=_ratio_frame()),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    out = fund.get_fundamentals("601061.SH", "2026-06-01")
    assert "中信金属" in out
    assert "9.2" in out
    assert "99.0" not in out
    assert "2026-09-30" not in out
    assert "do not invent" in out.lower()


@pytest.mark.unit
def test_balance_sheet_keeps_quarterly_on_or_before_as_of(monkeypatch):
    fake = SimpleNamespace(
        stock_balance_sheet_by_report_em=mock.Mock(return_value=_sheet_frame()),
        stock_financial_report_sina=mock.Mock(side_effect=AssertionError("em already filled")),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    out = fund.get_balance_sheet("601061.SH", "quarterly", "2026-06-01")
    assert "110.0" in out
    assert "999.0" not in out
    assert "2026-09-30" not in out


@pytest.mark.unit
def test_income_statement_annual_drops_quarterly_rows(monkeypatch):
    fake = SimpleNamespace(
        stock_profit_sheet_by_report_em=mock.Mock(return_value=_sheet_frame()),
        stock_financial_report_sina=mock.Mock(side_effect=AssertionError("em already filled")),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    out = fund.get_income_statement("601061.SH", "annual", "2026-06-01")
    assert "100.0" in out
    assert "110.0" not in out


@pytest.mark.unit
def test_cashflow_empty_raises(monkeypatch):
    fake = SimpleNamespace(
        stock_cash_flow_sheet_by_report_em=mock.Mock(return_value=pd.DataFrame()),
        stock_cash_flow_sheet_by_yearly_em=mock.Mock(return_value=pd.DataFrame()),
        stock_financial_report_sina=mock.Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    with pytest.raises(NoMarketDataError, match="cash flow"):
        fund.get_cashflow("601061.SH", "quarterly", "2026-06-01")


@pytest.mark.unit
def test_route_fundamentals_uses_akshare_before_yfinance():
    from tradingagents.dataflows import interface

    def fake_ak(ticker, curr_date=None):
        return f"AK:{ticker}"

    def fake_yf(ticker, curr_date=None):
        raise AssertionError("yfinance should not run after akshare success")

    with mock.patch.dict(
        interface.VENDOR_METHODS["get_fundamentals"],
        {"akshare": fake_ak, "yfinance": fake_yf},
        clear=False,
    ):
        out = interface.route_to_vendor("get_fundamentals", "601061.SH", "2026-06-01")
    assert out == "AK:601061.SH"


@pytest.mark.unit
def test_balance_sheet_calls_east_money_with_board_prefix(monkeypatch):
    captured: list[dict] = []

    def fake_em(**kwargs):
        captured.append(kwargs)
        return _sheet_frame()

    fake = SimpleNamespace(stock_balance_sheet_by_report_em=fake_em)
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    fund.get_balance_sheet("601061.SH", "quarterly", "2026-06-01")
    assert captured[0]["symbol"] == "SH601061"


@pytest.mark.unit
def test_get_fundamentals_requests_east_money_secucode(monkeypatch):
    captured: list[dict] = []

    def fake_ratio(**kwargs):
        captured.append(kwargs)
        return _ratio_frame()

    fake = SimpleNamespace(
        stock_individual_info_em=mock.Mock(return_value=_info_frame()),
        stock_financial_analysis_indicator_em=fake_ratio,
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    fund.get_fundamentals("601061.SH", "2026-06-01")
    assert captured[0]["symbol"] == "601061.SH"


@pytest.mark.unit
def test_yfinance_skips_a_share_fundamentals():
    from tradingagents.dataflows.y_finance import get_fundamentals as yf_fundamentals

    with pytest.raises(NoMarketDataError, match="A-share"):
        yf_fundamentals("601061.SH", "2026-06-01")


@pytest.mark.unit
def test_get_fundamentals_does_not_dump_code_name_table(monkeypatch):
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
        stock_financial_analysis_indicator_em=mock.Mock(return_value=_ratio_frame()),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    out = fund.get_fundamentals("601061.SH", "2026-06-01")
    assert fake.stock_info_a_code_name.call_count == 0
    assert "平安银行" not in out
    assert "贵州茅台" not in out
    assert "9.2" in out


@pytest.mark.unit
def test_get_fundamentals_does_not_call_profile_unparameterized(monkeypatch):
    captured: list[dict] = []

    def info(**kwargs):
        captured.append(dict(kwargs))
        if not kwargs:
            raise AssertionError("must not fetch the full A-share code-name table")
        raise TypeError("unexpected keyword")

    fake = SimpleNamespace(
        stock_individual_info_em=info,
        stock_financial_analysis_indicator_em=mock.Mock(return_value=_ratio_frame()),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    out = fund.get_fundamentals("601061.SH", "2026-06-01")
    assert captured
    assert all(call for call in captured)
    assert "9.2" in out


@pytest.mark.unit
def test_profile_falls_back_to_cninfo_when_eastmoney_500(monkeypatch):
    fake = SimpleNamespace(
        stock_individual_info_em=mock.Mock(side_effect=RuntimeError("500")),
        stock_profile_cninfo=mock.Mock(
            return_value=pd.DataFrame(
                [{"A股代码": "601061", "A股简称": "中信金属", "所属行业": "有色金属"}]
            )
        ),
        stock_financial_analysis_indicator_em=mock.Mock(return_value=_ratio_frame()),
    )
    monkeypatch.setattr(fund, "_load_akshare", lambda: fake)
    out = fund.get_fundamentals("601061.SH", "2026-06-01")
    assert fake.stock_profile_cninfo.call_args.kwargs == {"symbol": "601061"}
    assert "中信金属" in out
    assert "有色金属" in out


def test_profile_rows_keep_only_this_listing():
    rows = [
        {"代码": "000001", "名称": "平安银行"},
        {"代码": "601061", "名称": "中信金属"},
        {"代码": "600519", "名称": "贵州茅台"},
    ]
    kept = fund._profile_rows_for_code(rows, "601061")
    assert kept == [{"代码": "601061", "名称": "中信金属"}]


@pytest.mark.unit
def test_try_ak_records_stops_kwargs_when_interface_missing():
    calls: list[dict] = []

    def missing(**kwargs):
        calls.append(dict(kwargs))
        raise RuntimeError(
            'AKTools HTTP stock_changes_em returned 404: {"error":"未找到该接口"}'
        )

    rows = fund._try_ak_records(
        SimpleNamespace(stock_changes_em=missing),
        ("stock_changes_em",),
        ({"symbol": "601061"}, {"symbol": "sh601061"}),
    )
    assert rows == []
    assert calls == [{"symbol": "601061"}]
