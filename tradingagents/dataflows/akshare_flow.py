"""A-share disclosed buy/sell flow via AKTools.

Fills ``get_insider_transactions`` for mainland listings: 董监高/股东增减持,
dragon-tiger buy/sell seats, and 大宗交易. Non A-shares raise
``NoMarketDataError`` so the router can fall through to yfinance.

Only rows dated ``<= as-of`` are kept. Market-wide tables must name this
six-digit code. Empty-argument full-table calls are forbidden.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .akshare_fundamentals import (
    _as_of,
    _render_csv,
    _require_a_share,
    _to_date,
    _try_ak_records,
)
from .akshare_news import _field, _load_akshare
from .symbol_utils import a_share_code

logger = logging.getLogger(__name__)

_LOOKBACK_INSIDER_DAYS = 90
_LOOKBACK_BLOCK_DAYS = 10
_MAX_ROWS = 24
_CODE_KEYS = ("代码", "股票代码", "证券代码", "code", "symbol")
_DATE_KEYS = (
    "变动日期",
    "公告日期",
    "增减持日期",
    "交易日期",
    "上榜日期",
    "上榜日",
    "成交日期",
    "日期",
    "date",
)
_BUY_MARKERS = ("增持", "买入", "竞买")
_SELL_MARKERS = ("减持", "卖出", "出手", "转让")
_BUY_AMT_KEYS = ("买入金额", "买入额", "龙虎榜买入额", "买方机构买入", "买入总计", "buy")
_SELL_AMT_KEYS = ("卖出金额", "卖出额", "龙虎榜卖出额", "卖方机构卖出", "卖出总计", "sell")
_SEAT_KEYS = ("营业部名称", "交易营业部名称", "营业部", "交易营业部", "席位", "name")


def _yyyymmdd(value: str) -> str:
    return value.replace("-", "")[:8]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _row_code(row: dict) -> str | None:
    raw = _field(row, _CODE_KEYS)
    if not raw:
        return None
    parsed = a_share_code(raw)
    if parsed:
        return parsed
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits if len(digits) == 6 else None


def _keep_code(row: dict, code: str, *, require_code: bool) -> bool:
    row_code = _row_code(row)
    if row_code is not None:
        return row_code == code
    return not require_code


def _row_date(row: dict) -> str | None:
    return _to_date(_field(row, _DATE_KEYS))


def _in_window(row: dict, start: str, as_of: str) -> bool:
    stamp = _row_date(row)
    if stamp is None:
        return False
    return start <= stamp <= as_of


def _change_side(row: dict) -> str:
    blob = _field(row, ("变动方向", "增减", "类型", "交易类型", "方向", "操作", "增减持"))
    if any(marker in blob for marker in _BUY_MARKERS):
        return "buy"
    if any(marker in blob for marker in _SELL_MARKERS):
        return "sell"
    qty = _to_float(
        _field(row, ("变动数量", "变动股数", "变动数", "变动股份数量", "增减数量", "持股变动"))
    )
    if qty is not None:
        if qty > 0:
            return "buy"
        if qty < 0:
            return "sell"
    return "unknown"


def _party(row: dict) -> str:
    return (
        _field(
            row,
            ("姓名", "变动人", "股东名称", "董监高姓名", "持股人", "高管姓名", "name"),
        )
        or "unknown"
    )


def _hold_change_interface(code: str) -> str:
    if code.startswith("6"):
        return "stock_share_hold_change_sse"
    if code.startswith("920") or code[0] in "48":
        return "stock_share_hold_change_bse"
    return "stock_share_hold_change_szse"


def _fetch_insider_rows(ak, code: str, start: str, as_of: str) -> list[dict]:
    # Exchange filings take the six-digit code. ``stock_ggcg_em(symbol=)`` is a
    # category (股东增持/股东减持/全部), not a ticker — a code becomes HTTP 500.
    # ``stock_changes_em`` is 盘口异动 and is not an insider print.
    rows = _try_ak_records(
        ak,
        (_hold_change_interface(code),),
        ({"symbol": code},),
        allow_empty_call=False,
    )
    if not rows:
        for kind in ("股东增持", "股东减持"):
            rows = _try_ak_records(
                ak,
                ("stock_ggcg_em",),
                ({"symbol": kind},),
                allow_empty_call=False,
            )
            if rows:
                break
    if not rows:
        rows = _try_ak_records(
            ak,
            ("stock_inner_trade_xq",),
            ({},),
            allow_empty_call=True,
        )
    market_wide = False
    codes = {_row_code(row) for row in rows if _row_code(row)}
    if len(codes) > 1:
        market_wide = True
    kept: list[dict] = []
    for row in rows:
        if not _keep_code(row, code, require_code=market_wide):
            continue
        if not _in_window(row, start, as_of):
            continue
        kept.append(row)
    kept.sort(key=lambda row: _row_date(row) or "", reverse=True)
    return kept[:_MAX_ROWS]


def _render_insider(rows: list[dict]) -> str:
    if not rows:
        return ""
    slim: list[dict] = []
    for row in rows:
        slim.append(
            {
                "date": _row_date(row) or "",
                "party": _party(row),
                "side": _change_side(row),
                "shares": _field(
                    row, ("变动数量", "变动股数", "变动数", "变动股份数量", "增减数量", "持股变动")
                ),
                "avg_price": _field(row, ("成交均价", "均价", "变动价格")),
                "note": _field(row, ("变动原因", "类型", "变动方向")),
            }
        )
    return _render_csv(slim)


def _rows_for_code(rows: list[dict], code: str) -> list[dict]:
    return [
        row
        for row in rows
        if _keep_code(row, code, require_code=bool(_row_code(row)))
    ]


def _stamp_missing_date(rows: list[dict], as_of: str) -> list[dict]:
    stamped: list[dict] = []
    for row in rows:
        if _row_date(row) is None:
            copied = dict(row)
            copied["日期"] = as_of
            stamped.append(copied)
        else:
            stamped.append(row)
    return stamped


def _fetch_lhb_rows(ak, code: str, start: str, as_of: str) -> list[dict]:
    """Dragon-tiger rows with each interface's real signature.

    ``stock_lhb_detail_em`` is start/end only. Seat detail needs symbol, one
    date, and flag 买入/卖出. Sina daily detail takes ``date`` and rejects a
    stock code (AKTools returns that TypeError as HTTP 500). A market-wide
    table that does not name this code is not a hit.
    """
    summary = _rows_for_code(
        _try_ak_records(
            ak,
            ("stock_lhb_detail_em",),
            ({"start_date": _yyyymmdd(start), "end_date": _yyyymmdd(as_of)},),
            allow_empty_call=False,
        ),
        code,
    )
    if summary:
        return summary
    seats: list[dict] = []
    for flag in ("买入", "卖出"):
        seats.extend(
            _try_ak_records(
                ak,
                ("stock_lhb_stock_detail_em",),
                ({"symbol": code, "date": _yyyymmdd(as_of), "flag": flag},),
                allow_empty_call=False,
            )
        )
    seats = _rows_for_code(seats, code)
    if seats:
        return _stamp_missing_date(seats, as_of)
    sina = _rows_for_code(
        _try_ak_records(
            ak,
            ("stock_lhb_detail_daily_sina",),
            ({"date": _yyyymmdd(as_of)},),
            allow_empty_call=False,
        ),
        code,
    )
    return _stamp_missing_date(sina, as_of)


def summarize_lhb(ak, code: str, as_of: str) -> dict[str, Any]:
    """Dragon-tiger buy/sell summary for one listing on ``as_of``."""
    empty = {
        "dragon_tiger_flag": False,
        "inst_buy_ratio": None,
        "lhb_reason": "",
        "lhb_buy_amount": None,
        "lhb_sell_amount": None,
        "lhb_net_buy": None,
        "lhb_top_buy": "",
        "lhb_top_sell": "",
    }
    rows = _fetch_lhb_rows(ak, code, as_of, as_of)
    matched = [
        row
        for row in rows
        if _keep_code(row, code, require_code=bool(_row_code(row)))
        and (_row_date(row) in {None, as_of} or _row_date(row) == as_of)
    ]
    if not matched:
        return empty
    buy_total = 0.0
    sell_total = 0.0
    buy_seats: list[tuple[float, str]] = []
    sell_seats: list[tuple[float, str]] = []
    inst_values: list[float] = []
    reason = ""
    for row in matched:
        if not reason:
            reason = _field(row, ("上榜原因", "原因", "类型", "指标"))
        inst = _to_float(_field(row, ("机构买入额", "买方机构买入", "机构买入占比")))
        if inst is not None:
            inst_values.append(inst)
        buy = _to_float(_field(row, _BUY_AMT_KEYS))
        sell = _to_float(_field(row, _SELL_AMT_KEYS))
        seat = _field(row, _SEAT_KEYS)
        if buy is not None:
            buy_total += buy
            if seat:
                buy_seats.append((buy, seat))
        if sell is not None:
            sell_total += sell
            if seat:
                sell_seats.append((sell, seat))
    buy_seats.sort(reverse=True)
    sell_seats.sort(reverse=True)
    inst_ratio = round(sum(inst_values) / len(inst_values), 4) if inst_values else None
    return {
        "dragon_tiger_flag": True,
        "inst_buy_ratio": inst_ratio,
        "lhb_reason": reason,
        "lhb_buy_amount": round(buy_total, 4) if buy_total else None,
        "lhb_sell_amount": round(sell_total, 4) if sell_total else None,
        "lhb_net_buy": round(buy_total - sell_total, 4) if buy_total or sell_total else None,
        "lhb_top_buy": "; ".join(f"{name} {amt}" for amt, name in buy_seats[:5]),
        "lhb_top_sell": "; ".join(f"{name} {amt}" for amt, name in sell_seats[:5]),
    }


def _render_lhb(summary: dict[str, Any]) -> str:
    if not summary.get("dragon_tiger_flag"):
        return ""
    lines = [
        f"- reason: {summary.get('lhb_reason') or '<unavailable>'}",
        f"- buy_amount: {summary.get('lhb_buy_amount') if summary.get('lhb_buy_amount') is not None else '<unavailable>'}",
        f"- sell_amount: {summary.get('lhb_sell_amount') if summary.get('lhb_sell_amount') is not None else '<unavailable>'}",
        f"- net_buy: {summary.get('lhb_net_buy') if summary.get('lhb_net_buy') is not None else '<unavailable>'}",
        f"- top_buy_seats: {summary.get('lhb_top_buy') or '<unavailable>'}",
        f"- top_sell_seats: {summary.get('lhb_top_sell') or '<unavailable>'}",
    ]
    if summary.get("lhb_days") is not None:
        lines.append(f"- lhb_days: {summary['lhb_days']}")
    return "\n".join(lines)


def summarize_lhb_window(ak, code: str, start: str, as_of: str) -> dict[str, Any]:
    """Dragon-tiger buy/sell in ``[start, as_of]``."""
    rows = _fetch_lhb_rows(ak, code, start, as_of)
    matched = [
        row
        for row in rows
        if _keep_code(row, code, require_code=bool(_row_code(row)))
        and _in_window(row, start, as_of)
    ]
    if not matched:
        return {
            "dragon_tiger_flag": False,
            "inst_buy_ratio": None,
            "lhb_reason": "",
            "lhb_buy_amount": None,
            "lhb_sell_amount": None,
            "lhb_net_buy": None,
            "lhb_top_buy": "",
            "lhb_top_sell": "",
        }
    buy_total = 0.0
    sell_total = 0.0
    buy_seats: list[tuple[float, str]] = []
    sell_seats: list[tuple[float, str]] = []
    inst_values: list[float] = []
    reason = ""
    days = {stamp for stamp in (_row_date(row) for row in matched) if stamp}
    for row in matched:
        if not reason:
            reason = _field(row, ("上榜原因", "原因", "类型", "指标"))
        inst = _to_float(_field(row, ("机构买入额", "买方机构买入", "机构买入占比")))
        if inst is not None:
            inst_values.append(inst)
        buy = _to_float(_field(row, _BUY_AMT_KEYS))
        sell = _to_float(_field(row, _SELL_AMT_KEYS))
        seat = _field(row, _SEAT_KEYS)
        if buy is not None:
            buy_total += buy
            if seat:
                buy_seats.append((buy, seat))
        if sell is not None:
            sell_total += sell
            if seat:
                sell_seats.append((sell, seat))
    buy_seats.sort(reverse=True)
    sell_seats.sort(reverse=True)
    inst_ratio = round(sum(inst_values) / len(inst_values), 4) if inst_values else None
    return {
        "dragon_tiger_flag": True,
        "inst_buy_ratio": inst_ratio,
        "lhb_reason": reason,
        "lhb_buy_amount": round(buy_total, 4) if buy_total else None,
        "lhb_sell_amount": round(sell_total, 4) if sell_total else None,
        "lhb_net_buy": round(buy_total - sell_total, 4) if buy_total or sell_total else None,
        "lhb_top_buy": "; ".join(f"{name} {amt}" for amt, name in buy_seats[:5]),
        "lhb_top_sell": "; ".join(f"{name} {amt}" for amt, name in sell_seats[:5]),
        "lhb_days": len(days),
    }


def _fetch_block_rows(ak, code: str, start: str, as_of: str) -> list[dict]:
    rows = _try_ak_records(
        ak,
        (
            "stock_dzjy_mrmx",
            "stock_dzjy_sctj",
            "stock_dzjy_hygtj",
        ),
        (
            {"start_date": start, "end_date": as_of},
            {"start_date": _yyyymmdd(start), "end_date": _yyyymmdd(as_of)},
            {"date": _yyyymmdd(as_of)},
            {"symbol": code},
        ),
        allow_empty_call=False,
    )
    kept: list[dict] = []
    for row in rows:
        if not _keep_code(row, code, require_code=True):
            continue
        if not _in_window(row, start, as_of):
            continue
        kept.append(row)
    kept.sort(key=lambda row: _row_date(row) or "", reverse=True)
    return kept[:_MAX_ROWS]


def _render_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    slim = [
        {
            "date": _row_date(row) or "",
            "price": _field(row, ("成交价", "价格", "溢价率")),
            "amount": _field(row, ("成交额", "成交量", "成交金额")),
            "buyer": _field(row, ("买方营业部", "买入营业部", "买方")),
            "seller": _field(row, ("卖方营业部", "卖出营业部", "卖方")),
        }
        for row in rows
    ]
    return _render_csv(slim)


def get_insider_transactions(ticker: str, curr_date: str | None = None) -> str:
    """Disclosed A-share buy/sell flow as-of ``curr_date``."""
    code = _require_a_share(ticker)
    as_of = _as_of(curr_date)
    start_insider = (
        datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=_LOOKBACK_INSIDER_DAYS)
    ).strftime("%Y-%m-%d")
    start_block = (
        datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=_LOOKBACK_BLOCK_DAYS)
    ).strftime("%Y-%m-%d")
    ak = _load_akshare()
    insider = _fetch_insider_rows(ak, code, start_insider, as_of)
    lhb = summarize_lhb(ak, code, as_of)
    blocks = _fetch_block_rows(ak, code, start_block, as_of)

    sections: list[str] = []
    insider_csv = _render_insider(insider)
    if insider_csv:
        sections.append(
            f"## 董监高 / 股东增减持 ({start_insider} to {as_of})\n\n{insider_csv}"
        )
    lhb_text = _render_lhb(lhb)
    if lhb_text:
        sections.append(f"## 龙虎榜买卖 (as-of {as_of})\n\n{lhb_text}")
    block_csv = _render_block(blocks)
    if block_csv:
        sections.append(f"## 大宗交易 ({start_block} to {as_of})\n\n{block_csv}")
    if not sections:
        return (
            f"NO_DATA_AVAILABLE: no disclosed A-share 增减持, 龙虎榜 seats, or 大宗 "
            f"for {ticker} (code {code}) on or before {as_of}. "
            "Do not invent 出手/买入 prints."
        )
    header = (
        f"# Buy/sell flow for {ticker} (code {code}) as of {as_of}\n"
        "# Disclosed 增减持, dragon-tiger seats, and 大宗 only. "
        "Do not invent missing prints. This is research, never an order ticket.\n"
    )
    return header + "\n\n".join(sections)


def render_buy_sell_window(ticker: str, start: str, as_of: str) -> str:
    """增减持 / 龙虎 / 大宗 in ``[start, as_of]``. Empty string if none."""
    code = _require_a_share(ticker)
    datetime.strptime(start, "%Y-%m-%d")
    datetime.strptime(as_of, "%Y-%m-%d")
    ak = _load_akshare()
    insider = _fetch_insider_rows(ak, code, start, as_of)
    lhb = summarize_lhb_window(ak, code, start, as_of)
    blocks = _fetch_block_rows(ak, code, start, as_of)
    sections: list[str] = []
    insider_csv = _render_insider(insider)
    if insider_csv:
        sections.append(f"## 董监高 / 股东增减持 ({start} to {as_of})\n\n{insider_csv}")
    lhb_text = _render_lhb(lhb)
    if lhb_text:
        sections.append(f"## 龙虎榜买卖 ({start} to {as_of})\n\n{lhb_text}")
    block_csv = _render_block(blocks)
    if block_csv:
        sections.append(f"## 大宗交易 ({start} to {as_of})\n\n{block_csv}")
    if not sections:
        return ""
    header = (
        f"# Disclosed 机构出手 for {ticker} (code {code}) from {start} to {as_of}\n"
        "# 增减持, dragon-tiger seats, and 大宗 only. Do not invent 出手/买入. "
        "Research input, never an order ticket.\n"
    )
    return header + "\n\n".join(sections)
