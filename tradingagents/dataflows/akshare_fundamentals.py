"""A-share fundamentals from East Money via AKTools.

Yahoo has no usable A-share three-statement coverage here (it is skipped on
purpose). These functions fill ``get_fundamentals`` / balance / cash / income
for mainland listings. Non A-shares raise ``NoMarketDataError`` so the router
can fall through to yfinance.

Only filings with a report date ``<= as-of`` are kept (no lookahead).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from typing import Any

from .akshare_news import (
    _ak_interface_missing,
    _as_records,
    _call_with_timeout,
    _field,
    _load_akshare,
    _parse_pub_dt,
    fetch_a_share_profile_rows,
)
from .symbol_utils import (
    NoMarketDataError,
    a_share_code,
    a_share_prefixed_symbol,
)

logger = logging.getLogger(__name__)

_MAX_PERIODS = 8
_MAX_COLUMNS = 36
_ANNUAL_MARKERS = ("年报", "年度", "年报报告")
_DATE_KEYS = (
    "REPORT_DATE",
    "REPORTDATE",
    "报表日期",
    "报告日",
    "报告期",
    "日期",
    "date",
)
_TYPE_KEYS = ("REPORT_TYPE", "REPORTTYPE", "报表类型", "报告类型")


def _as_of(curr_date: str | None) -> str:
    if curr_date and str(curr_date).strip():
        return str(curr_date).strip()[:10]
    return date.today().isoformat()


def _to_date(value: Any) -> str | None:
    parsed = _parse_pub_dt(value)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


def _try_ak_records(
    ak,
    names: tuple[str, ...],
    kwargs_list: tuple[dict, ...],
    *,
    allow_empty_call: bool = True,
) -> list[dict]:
    last_error: Exception | None = None
    for name in names:
        fn = getattr(ak, name, None)
        if not callable(fn):
            continue
        for kwargs in kwargs_list:
            try:
                if kwargs:
                    frame = _call_with_timeout(fn, **kwargs)
                elif allow_empty_call:
                    frame = _call_with_timeout(fn)
                else:
                    continue
            except TypeError as e:
                if not allow_empty_call:
                    last_error = e
                    continue
                try:
                    frame = _call_with_timeout(fn)
                except Exception as empty_err:
                    last_error = empty_err
                    continue
            except Exception as e:
                last_error = e
                if _ak_interface_missing(e):
                    break
                continue
            rows = _as_records(frame)
            if rows:
                return rows
    if last_error is not None:
        if _ak_interface_missing(last_error):
            logger.info(
                "akshare fundamentals %s missing on this AKShare; skip", names[0]
            )
        else:
            logger.warning("akshare fundamentals %s failed: %s", names[0], last_error)
    return []


def _profile_rows_for_code(rows: list[dict], code: str) -> list[dict]:
    """Keep this listing's profile; never return the full A-share code-name table."""
    if not rows:
        return []
    matched: list[dict] = []
    saw_code_field = False
    for row in rows:
        raw = _field(row, ("代码", "code", "symbol", "股票代码", "证券代码"))
        if not raw:
            continue
        saw_code_field = True
        row_code = a_share_code(raw)
        if row_code is None:
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            row_code = digits if len(digits) == 6 else None
        if row_code == code:
            matched.append(row)
    if saw_code_field:
        return matched
    return rows


def _require_a_share(ticker: str) -> str:
    code = a_share_code(ticker)
    if code is None:
        raise NoMarketDataError(ticker, ticker, "akshare fundamentals are China A-share only")
    return code


def _is_annual_row(row: dict) -> bool | None:
    blob = _field(row, _TYPE_KEYS)
    if not blob:
        return None
    return any(marker in blob for marker in _ANNUAL_MARKERS)


def _filter_freq(rows: list[dict], freq: str) -> list[dict]:
    want_annual = str(freq or "quarterly").lower().startswith("annual")
    typed = [row for row in rows if _is_annual_row(row) is not None]
    if not typed:
        return rows
    return [row for row in rows if _is_annual_row(row) == want_annual]


def _long_rows_as_of(rows: list[dict], as_of: str) -> list[dict]:
    dated: list[tuple[str, dict]] = []
    for row in rows:
        report = _to_date(_field(row, _DATE_KEYS))
        if report is None or report > as_of:
            continue
        dated.append((report, row))
    dated.sort(key=lambda item: item[0])
    return [row for _, row in dated[-_MAX_PERIODS:]]


def _wide_rows_as_of(rows: list[dict], as_of: str) -> list[dict]:
    if not rows:
        return []
    date_cols = [key for key in rows[0] if _to_date(key) is not None and _to_date(key) <= as_of]
    date_cols.sort(key=lambda key: _to_date(key) or "")
    date_cols = date_cols[-_MAX_PERIODS:]
    item_keys = [key for key in rows[0] if _to_date(key) is None]
    out: list[dict] = []
    for row in rows:
        item = {key: row.get(key) for key in item_keys}
        for col in date_cols:
            item[col] = row.get(col)
        out.append(item)
    return out


def _looks_wide(rows: list[dict]) -> bool:
    if not rows:
        return False
    dated = sum(1 for key in rows[0] if _to_date(key) is not None)
    return dated >= 2


def _render_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    keys = list(rows[0].keys())
    if len(keys) > _MAX_COLUMNS:
        date_keys = [key for key in keys if key in _DATE_KEYS or _to_date(key)]
        rest = [key for key in keys if key not in date_keys][: _MAX_COLUMNS - len(date_keys)]
        keys = date_keys + rest
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in keys})
    return buf.getvalue().strip()


_SINA_STATEMENT = {
    "Balance Sheet": "资产负债表",
    "Cash Flow": "现金流量表",
    "Income Statement": "利润表",
}


def _em_board_symbol(code: str) -> str:
    """East Money three-statement ticker, e.g. ``SH601061``."""
    return a_share_prefixed_symbol(code).upper()


def _em_secucode(code: str) -> str:
    """East Money ``SECUCODE``, e.g. ``601061.SH``."""
    return f"{code}.{_em_board_symbol(code)[:2]}"


def _statement(
    ticker: str,
    freq: str,
    curr_date: str | None,
    em_names: tuple[str, ...],
    title: str,
) -> str:
    code = _require_a_share(ticker)
    as_of = _as_of(curr_date)
    ak = _load_akshare()
    em_sym = _em_board_symbol(code)
    prefixed = a_share_prefixed_symbol(code)
    rows = _try_ak_records(ak, em_names, ({"symbol": em_sym}, {"symbol": code}))
    if not rows:
        sina_kind = _SINA_STATEMENT[title]
        rows = _try_ak_records(
            ak,
            ("stock_financial_report_sina",),
            (
                {"stock": prefixed, "symbol": sina_kind},
                {"stock": code, "symbol": sina_kind},
            ),
        )
    if _looks_wide(rows):
        kept = _wide_rows_as_of(rows, as_of)
    else:
        kept = _long_rows_as_of(_filter_freq(rows, freq), as_of)
    csv_text = _render_csv(kept)
    if not csv_text:
        raise NoMarketDataError(ticker, code, f"no {title.lower()} rows on or before {as_of}")
    return (
        f"# {title} for {ticker} (code {code}, {freq})\n"
        f"# Filings with report date <= {as_of} only. Do not invent missing lines.\n\n"
        f"{csv_text}"
    )


def get_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    """Profile + published ratio snapshot for an A-share, as-of ``curr_date``."""
    code = _require_a_share(ticker)
    as_of = _as_of(curr_date)
    ak = _load_akshare()
    info = _profile_rows_for_code(fetch_a_share_profile_rows(ak, code), code)
    start_year = str(max(2000, int(as_of[:4]) - 6))
    secucode = _em_secucode(code)
    ratios = _try_ak_records(
        ak,
        (
            "stock_financial_analysis_indicator_em",
            "stock_financial_analysis_indicator",
            "stock_financial_abstract_ths",
            "stock_financial_abstract",
        ),
        (
            {"symbol": secucode, "indicator": "按报告期"},
            {"symbol": secucode},
            {"symbol": code, "start_year": start_year},
            {"symbol": code, "indicator": "按报告期"},
            {"symbol": code},
        ),
    )
    ratio_kept = _long_rows_as_of(ratios, as_of)
    lines: list[str] = [
        f"# Company Fundamentals for {ticker} (code {code})",
        f"# Published East Money fields with date <= {as_of}. Do not invent PE/ROE.",
        "",
    ]
    wide_keys = ("公司名称", "A股简称", "所属行业", "法人代表", "上市日期", "主营业务")
    for row in info:
        item = _field(row, ("item", "指标", "名称"))
        value = _field(row, ("value", "值"))
        if item and value and item not in {code, "股票代码"}:
            lines.append(f"{item}: {value}")
            continue
        short = _field(row, ("股票简称", "A股简称", "name"))
        if short and short not in {code, "股票代码"}:
            lines.append(f"股票简称: {short}")
        for key in wide_keys:
            if key == "A股简称":
                continue
            wide_value = _field(row, (key,))
            if wide_value and wide_value not in {code, "股票代码", short}:
                lines.append(f"{key}: {wide_value}")
    if ratio_kept:
        lines.append("")
        lines.append("## Financial indicators (latest periods on or before as-of)")
        lines.append(_render_csv(ratio_kept[-4:]))
    body = "\n".join(lines).strip()
    if len(body.splitlines()) <= 3:
        raise NoMarketDataError(ticker, code, f"no A-share fundamental fields on or before {as_of}")
    return body


def get_balance_sheet(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    return _statement(
        ticker,
        freq,
        curr_date,
        (
            "stock_balance_sheet_by_report_em",
            "stock_balance_sheet_by_yearly_em",
        ),
        "Balance Sheet",
    )


def get_cashflow(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    return _statement(
        ticker,
        freq,
        curr_date,
        (
            "stock_cash_flow_sheet_by_report_em",
            "stock_cash_flow_sheet_by_yearly_em",
        ),
        "Cash Flow",
    )


def get_income_statement(
    ticker: str,
    freq: str = "quarterly",
    curr_date: str | None = None,
) -> str:
    return _statement(
        ticker,
        freq,
        curr_date,
        (
            "stock_profit_sheet_by_report_em",
            "stock_profit_sheet_by_yearly_em",
        ),
        "Income Statement",
    )
