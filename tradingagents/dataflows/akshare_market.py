"""A-share short-horizon tape: daily rules, market breadth, lagged flows, events.

Built for next-session and 5–20 trading-day views. Price/volume, limit rules,
breadth, published capital, and binary events are the main features. PE/PB/ROE
are not fetched here.

Point-in-time:
- Daily OHLCV and close-at-limit flags are as-of the requested session (known
  after the close) and predict the *next* tradable day (T+1).
- A live as-of (today) also attaches a public spot print (East Money bid/ask,
  then Xueqiu, then Tencent minutes). Historical as-of never sees that snapshot,
  so today's quote cannot leak into a backtest.
- Northbound uses the last session *strictly before* as-of so an incomplete
  same-day print cannot leak into a same-session label.
- Dragon-tiger lists are as-of (published after the close) for the next day.
- Unlock windows look forward from as-of; they are calendars, not surprises.
- Industry index, at most two domestic contracts, and at most two mapped
  international prints come from a static keyword map on the East Money
  industry string plus stock name. Copper is one row (有色 → 沪铜 + LME/COMEX);
  lithium, nickel, iron ore, soymeal, rubber, crude, liquor, banks, and other
  listed industries have their own rows. Unmapped names and failed fetches stay
  ``<unavailable>``; this is not a 布局 knowledge graph. Name lookup never
  takes the first row of ``stock_info_a_code_name``.

AKShare is the optional extra. A missing install raises
``AkshareNotConfiguredError``. Per-channel failures log and degrade that
section; empty daily history is ``NoMarketDataError``.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Any, NamedTuple

import pandas as pd

from .akshare_news import (
    AkshareNotConfiguredError,
    _ak_interface_missing,
    _as_records,
    _call_with_timeout,
    _field,
    _load_akshare,
    _name_from_profile_rows,
    _parse_pub_dt,
    fetch_a_share_profile_rows,
)
from .ashare_market_mood import (
    blend_stock_with_market_mood,
    has_material_stock_news,
    load_market_mood_snapshot,
    resolve_market_mood,
)
from .ashare_playbook import build_playbook_stance, combine_market_amount
from .ashare_trend_bias import close_range_position, compute_trend_bias
from .chanlun import (
    CHANLUN_CALENDAR_DAYS,
    aggregate_weekly,
    analyze_chanlun,
    render_chanlun_markdown,
)
from .config import get_config
from .errors import VendorError
from .news_store import GLOBAL_KEY, fetch_cached_records, is_live_as_of
from .news_warehouse import query_items
from .symbol_utils import (
    NoMarketDataError,
    a_share_board_type,
    a_share_code,
    a_share_exchange_name,
    a_share_limit_pct,
    a_share_prefixed_symbol,
)

logger = logging.getLogger(__name__)

_LIMIT_EPS = 0.04  # percentage points; East Money rounds 涨跌幅
_ANNOUNCE_BAD = ("减持", "立案", "问询", "处罚", "违规", "预减", "风险警示", "被调查", "亏损")
_ANNOUNCE_GOOD = ("回购", "中标", "增持", "预增", "重组", "股权激励", "签订")

# Calendar windows for the swing tape (近半个月 / 近半年). Trading-day count
# is whatever the vendor printed in that span; do not invent missing sessions.
SWING_WINDOWS: dict[str, dict[str, int | str]] = {
    "half_month": {"calendar_days": 15, "label": "近半个月", "table_bars": 16},
    "three_months": {"calendar_days": 90, "label": "近3个月", "table_bars": 20},
    "half_year": {"calendar_days": 180, "label": "近半年", "table_bars": 16},
}


def _yyyymmdd(as_of: str) -> str:
    return as_of.replace("-", "")


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


def _to_date(value: Any) -> str | None:
    parsed = _parse_pub_dt(value)
    if parsed is None:
        text = str(value or "").strip()
        if len(text) >= 10 and text[4] == "-":
            return text[:10]
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return None
    return parsed.strftime("%Y-%m-%d")


def _cached(
    key: str,
    as_of: str,
    channel: str,
    loader,
    *,
    ttl_seconds: int | None = None,
) -> list[dict]:
    return fetch_cached_records(
        key, as_of, channel, lambda: loader() or [], ttl_seconds=ttl_seconds
    )


def _try_ak_records(
    ak,
    names: tuple[str, ...],
    kwargs_list: tuple[dict, ...],
    *,
    allow_empty_call: bool = True,
    timeout: float | None = None,
    failure_level: int = logging.WARNING,
) -> list[dict]:
    last_error: Exception | None = None
    for name in names:
        fn = getattr(ak, name, None)
        if not callable(fn):
            continue
        for kwargs in kwargs_list:
            try:
                if kwargs:
                    frame = _call_with_timeout(fn, timeout=timeout, **kwargs)
                elif allow_empty_call:
                    frame = _call_with_timeout(fn, timeout=timeout)
                else:
                    continue
            except TypeError as e:
                if not allow_empty_call:
                    last_error = e
                    continue
                try:
                    frame = _call_with_timeout(fn, timeout=timeout)
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
                "akshare market channel %s missing on this AKShare; skip", names[0]
            )
        else:
            logger.log(
                failure_level,
                "akshare market channel %s failed: %s",
                names[0],
                last_error,
            )
    return []


def _is_st_name(name: str) -> bool:
    compact = name.upper().replace("*", "").replace(" ", "")
    return "ST" in compact


def _hist_kwargs(code: str, start: str, end: str, adjust: str) -> tuple[dict, ...]:
    start_n = _yyyymmdd(start)
    end_n = _yyyymmdd(end)
    return (
        {
            "symbol": code,
            "period": "daily",
            "start_date": start_n,
            "end_date": end_n,
            "adjust": adjust,
        },
        {"symbol": code, "start_date": start_n, "end_date": end_n, "adjust": adjust},
        {"symbol": code, "period": "daily", "adjust": adjust},
    )


def _fetch_daily(ak, code: str, start: str, end: str, adjust: str) -> list[dict]:
    """East Money first; Tencent/Sina when Docker RST's ``push2his``."""
    rows = _try_ak_records(
        ak,
        ("stock_zh_a_hist",),
        _hist_kwargs(code, start, end, adjust),
        failure_level=logging.INFO,
    )
    if rows:
        return rows
    logger.info(
        "akshare stock_zh_a_hist empty for %s; trying stock_zh_a_hist_tx / stock_zh_a_daily",
        code,
    )
    prefixed = a_share_prefixed_symbol(code)
    start_n = _yyyymmdd(start)
    end_n = _yyyymmdd(end)
    fallback_kwargs = (
        {
            "symbol": prefixed,
            "start_date": start_n,
            "end_date": end_n,
            "adjust": adjust,
        },
        {"symbol": prefixed, "adjust": adjust},
        {"symbol": prefixed},
    )
    return _try_ak_records(
        ak, ("stock_zh_a_hist_tx", "stock_zh_a_daily"), fallback_kwargs
    )


def _row_ohlc(row: dict) -> dict[str, Any]:
    date = _to_date(_field(row, ("日期", "date", "时间")) or row.get("日期"))
    return {
        "date": date,
        "open": _to_float(_field(row, ("开盘", "开盘价", "open"))),
        "high": _to_float(_field(row, ("最高", "最高价", "high"))),
        "low": _to_float(_field(row, ("最低", "最低价", "low"))),
        "close": _to_float(_field(row, ("收盘", "收盘价", "close"))),
        "volume": _to_float(_field(row, ("成交量", "volume"))),
        "amount": _to_float(_field(row, ("成交额", "amount"))),
        "turnover": _to_float(_field(row, ("换手率", "turnover"))),
        "pct_chg": _to_float(_field(row, ("涨跌幅", "pct_chg", "涨跌幅(%)"))),
        "amplitude": _to_float(_field(row, ("振幅", "amplitude"))),
    }


def _align_amount(qfq_rows: list[dict], raw_rows: list[dict]) -> list[dict]:
    raw_by_date = {row["date"]: row for row in raw_rows if row.get("date")}
    out: list[dict] = []
    for row in qfq_rows:
        date = row.get("date")
        if not date:
            continue
        raw = raw_by_date.get(date, {})
        merged = dict(row)
        if raw.get("amount") is not None:
            merged["amount"] = raw["amount"]
        if raw.get("volume") is not None:
            merged["volume"] = raw["volume"]
        if raw.get("turnover") is not None:
            merged["turnover"] = raw["turnover"]
        out.append(merged)
    return out


def _decorate_daily(
    rows: list[dict],
    code: str,
    as_of: str,
    *,
    is_st: bool,
    index_dates: set[str],
) -> list[dict]:
    kept = [row for row in rows if row.get("date") and row["date"] <= as_of]
    kept.sort(key=lambda row: row["date"])
    limit = a_share_limit_pct(code, as_of, is_st=is_st)
    board = a_share_board_type(code, is_st=is_st)
    decorated: list[dict] = []
    for i, row in enumerate(kept):
        close = row.get("close")
        preclose = kept[i - 1]["close"] if i else None
        pct = row.get("pct_chg")
        if pct is None and close is not None and preclose not in (None, 0):
            pct = (close / preclose - 1.0) * 100.0
        high = row.get("high")
        low = row.get("low")
        amp = row.get("amplitude")
        if amp is None and high is not None and low is not None and preclose not in (None, 0):
            amp = (high - low) / preclose * 100.0
        prior_volumes = [
            item["volume"]
            for item in kept[max(0, i - 5) : i]
            if item.get("volume")
        ]
        volume = row.get("volume")
        volume_ratio = (
            round(volume / (sum(prior_volumes) / len(prior_volumes)), 4)
            if volume and prior_volumes
            else None
        )
        limit_up = bool(pct is not None and pct >= limit - _LIMIT_EPS)
        limit_down = bool(pct is not None and pct <= -(limit - _LIMIT_EPS))
        touched_up = bool(
            limit_up
            or (
                high is not None
                and preclose not in (None, 0)
                and high >= preclose * (1 + (limit - _LIMIT_EPS) / 100.0)
            )
        )
        decorated.append(
            {
                **row,
                "open": None if row.get("open") is None else round(row["open"], 4),
                "high": None if row.get("high") is None else round(row["high"], 4),
                "low": None if row.get("low") is None else round(row["low"], 4),
                "close": None if close is None else round(close, 4),
                "preclose": None if preclose is None else round(preclose, 4),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
                "turnover": row.get("turnover"),
                "pct_chg": None if pct is None else round(pct, 4),
                "amplitude": None if amp is None else round(amp, 4),
                "volume_ratio": volume_ratio,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "touched_limit_up": touched_up,
                "board_type": board,
                "limit_pct": limit,
                "is_paused": False,
            }
        )
    # Pause: as-of is on the index calendar but missing from the stock.
    if index_dates and as_of in index_dates and as_of not in {row["date"] for row in decorated}:
        decorated.append(
            {
                "date": as_of,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "preclose": decorated[-1]["close"] if decorated else None,
                "volume": 0.0,
                "amount": 0.0,
                "turnover": None,
                "pct_chg": None,
                "amplitude": None,
                "volume_ratio": None,
                "limit_up": False,
                "limit_down": False,
                "touched_limit_up": False,
                "board_type": board,
                "limit_pct": limit,
                "is_paused": True,
            }
        )
    return decorated


def _horizon_stats(rows: list[dict]) -> dict[str, float | None]:
    closes = [row["close"] for row in rows if row.get("close") is not None]
    turnovers = [row["turnover"] for row in rows if row.get("turnover") is not None]

    def ret(n: int) -> float | None:
        if len(closes) < n + 1:
            return None
        start, end = closes[-(n + 1)], closes[-1]
        if start in (None, 0):
            return None
        return round((end / start - 1.0) * 100.0, 4)

    vol = None
    if len(closes) >= 6:
        rets = [
            (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))
            if closes[i - 1]
        ]
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((item - mean) ** 2 for item in rets) / len(rets)
            vol = round((var ** 0.5) * (252 ** 0.5) * 100.0, 4)
    peak = None
    max_dd = None
    for close in closes:
        peak = close if peak is None or close > peak else peak
        if peak:
            dd = close / peak - 1.0
            if max_dd is None or dd < max_dd:
                max_dd = dd
    last_turn = turnovers[-1] if turnovers else None
    pctile = None
    if last_turn is not None and turnovers:
        pctile = round(
            sum(1 for item in turnovers if item <= last_turn) / len(turnovers) * 100.0,
            2,
        )
    return {
        "ret_5": ret(5),
        "ret_10": ret(10),
        "ret_20": ret(20),
        "vol_20": vol,
        "max_dd_20": None if max_dd is None else round(max_dd * 100.0, 4),
        "turnover_pctile": pctile,
    }


def resolve_swing_window(window: str | None) -> str:
    raw = (window or "").strip().lower()
    if not raw:
        raw = str(get_config().get("swing_tape_window") or "half_month").strip().lower()
    if raw not in SWING_WINDOWS:
        raise ValueError(
            f"unknown swing tape window {window!r}; "
            "use half_month, three_months, or half_year"
        )
    return raw


def _horizon_ret(rows: list[dict], n: int) -> float | None:
    closes = [row["close"] for row in rows if row.get("close") is not None]
    if len(closes) < n + 1:
        return None
    start, end = closes[-(n + 1)], closes[-1]
    if start in (None, 0):
        return None
    return round((end / start - 1.0) * 100.0, 4)


def _swing_stats(rows: list[dict]) -> dict[str, Any]:
    closes = [row["close"] for row in rows if row.get("close") is not None]
    volumes = [row["volume"] for row in rows if row.get("volume") is not None]
    amounts = [row["amount"] for row in rows if row.get("amount") is not None]
    turnovers = [row["turnover"] for row in rows if row.get("turnover") is not None]
    base = _horizon_stats(rows)
    start_close = closes[0] if closes else None
    end_close = closes[-1] if closes else None
    ret_window = None
    if start_close not in (None, 0) and end_close is not None:
        ret_window = round((end_close / start_close - 1.0) * 100.0, 4)
    high_row = max(rows, key=lambda row: row.get("high") or float("-inf"), default=None)
    low_row = min(rows, key=lambda row: row.get("low") or float("inf"), default=None)
    last_volume = volumes[-1] if volumes else None
    avg_volume = round(sum(volumes) / len(volumes), 4) if volumes else None
    volume_vs_avg = None
    if last_volume and avg_volume:
        volume_vs_avg = round(last_volume / avg_volume, 4)
    last_amount = amounts[-1] if amounts else None
    up_days = sum(1 for row in rows if (row.get("pct_chg") or 0) > 0)
    down_days = sum(1 for row in rows if (row.get("pct_chg") or 0) < 0)
    limit_up_days = sum(1 for row in rows if row.get("limit_up"))
    limit_down_days = sum(1 for row in rows if row.get("limit_down"))
    return {
        **base,
        "bars": len(rows),
        "start_date": rows[0].get("date") if rows else None,
        "end_date": rows[-1].get("date") if rows else None,
        "start_close": start_close,
        "end_close": end_close,
        "ret_window": ret_window,
        "ret_60": _horizon_ret(rows, 60),
        "ret_120": _horizon_ret(rows, 120),
        "high": None if high_row is None else high_row.get("high"),
        "high_date": None if high_row is None else high_row.get("date"),
        "low": None if low_row is None else low_row.get("low"),
        "low_date": None if low_row is None else low_row.get("date"),
        "avg_volume": avg_volume,
        "last_volume": last_volume,
        "volume_vs_avg": volume_vs_avg,
        "sum_amount": None if not amounts else round(sum(amounts), 4),
        "last_amount": last_amount,
        "avg_turnover": (
            None if not turnovers else round(sum(turnovers) / len(turnovers), 4)
        ),
        "up_days": up_days,
        "down_days": down_days,
        "limit_up_days": limit_up_days,
        "limit_down_days": limit_down_days,
    }


def _weekly_last_bars(rows: list[dict]) -> list[dict]:
    by_week: dict[str, dict] = {}
    for row in rows:
        date = row.get("date")
        if not date:
            continue
        week = datetime.strptime(date, "%Y-%m-%d").strftime("%G-W%V")
        by_week[week] = row
    return list(by_week.values())


def _northbound_window(ak, code: str, start: str, as_of: str) -> dict[str, Any]:
    snapshot = _fetch_northbound(ak, code, as_of)
    rows = _try_ak_records(
        ak,
        (
            "stock_hsgt_individual_em",
            "stock_hsgt_hold_stock_em",
            "stock_hsgt_individual_detail_em",
        ),
        ({"symbol": code}, {"stock": code}, {}),
    )
    inflows: list[float] = []
    for row in rows:
        date = _to_date(_field(row, ("日期", "date", "持股日期")))
        if not date or date < start or date >= as_of:
            continue
        inflow = _to_float(
            _field(row, ("今日持股-增减", "持股增减", "净买入额", "北向资金净买入", "净流入"))
        )
        if inflow is not None:
            inflows.append(inflow)
    snapshot["northbound_window_net"] = round(sum(inflows), 4) if inflows else None
    snapshot["northbound_window_sessions"] = len(inflows)
    return snapshot


def _usable_vendor_text(text: str | None) -> str:
    blob = (text or "").strip()
    if not blob:
        return ""
    if blob.startswith(("NO_DATA_AVAILABLE", "DATA_UNAVAILABLE")):
        return ""
    return blob


def _swing_news_markdown(
    ticker: str, start: str, curr_date: str, calendar_days: int
) -> str:
    """Ticker + global news in the swing window. Missing news does not abort the tape."""
    from .akshare_news import (
        get_global_news as get_akshare_global_news,
        get_news as get_akshare_news,
    )

    parts: list[str] = []
    try:
        ticker_news = _usable_vendor_text(get_akshare_news(ticker, start, curr_date))
        if ticker_news:
            parts.append(ticker_news)
    except VendorError as e:
        logger.warning("swing tape ticker news unavailable for %s: %s", ticker, e)
    try:
        global_news = _usable_vendor_text(
            get_akshare_global_news(curr_date, calendar_days)
        )
        if global_news:
            parts.append(global_news)
    except VendorError as e:
        logger.warning("swing tape global news unavailable for %s: %s", ticker, e)
    if parts:
        return (
            f"## Window news ({start} to {curr_date})\n"
            "Use for subsequent-trend research. Do not invent headlines. "
            "Cite only items in this window.\n\n" + "\n\n".join(parts)
        )
    return (
        f"## Window news ({start} to {curr_date})\n\n"
        f"NO_DATA_AVAILABLE: no ticker or domestic policy news for {ticker} "
        f"from {start} to {curr_date}. Do not invent headlines."
    )


def _index_rows_as_of(rows: list[dict], as_of: str) -> list[dict]:
    out = []
    for row in rows:
        item = _row_ohlc(row)
        if item.get("date") and item["date"] <= as_of:
            out.append(item)
    out.sort(key=lambda row: row["date"])
    return out


def _fetch_index_daily(ak, as_of: str, lookback_start: str, symbol: str) -> list[dict]:
    """East Money first; Tencent/Sina ``stock_zh_index_daily`` when Docker RST."""
    rows = _try_ak_records(
        ak,
        ("stock_zh_index_daily_em", "index_zh_a_hist"),
        (
            {"symbol": symbol, "start_date": _yyyymmdd(lookback_start), "end_date": _yyyymmdd(as_of)},
            {"symbol": symbol},
        ),
    )
    if not rows:
        rows = _try_ak_records(
            ak,
            ("stock_zh_index_daily", "stock_zh_index_daily_tx"),
            ({"symbol": symbol}, {"symbol": symbol.lower()}, {"symbol": symbol.upper()}),
        )
    return _index_rows_as_of(rows, as_of)


class ExposureRule(NamedTuple):
    """Static A-share industry → index + domestic/international commodity map.

    Not inferred 布局. ``intl_commodities`` use Sina foreign codes (``CAD`` =
    LME copper, ``HG`` = COMEX copper, ``NID`` = LME nickel, ``FEF`` = SGX
    iron ore). Commodities may be empty when only a sector index is mapped.
    """

    keywords: tuple[str, ...]
    industry_name: str
    index_symbol: str
    board_em: str
    commodities: tuple[tuple[str, str], ...]
    intl_commodities: tuple[tuple[str, str], ...] = ()


# Most specific keywords first. Match against industry + short name.
# Domestic: Sina continuous (``CU0``). International: Sina hf codes. Cap: two each.
# ``金属`` is last among metal rows so 能源金属 / 工业金属 / 贵金属 win first.
_INTL_CU = (("LME铜", "CAD"), ("COMEX铜", "HG"))
_EXPOSURE_RULES: tuple[ExposureRule, ...] = (
    ExposureRule(("铜",), "铜", "sh000819", "有色金属", (("沪铜", "CU0"),), _INTL_CU),
    ExposureRule(("铝",), "铝", "sh000819", "有色金属", (("沪铝", "AL0"),), (("LME铝", "AHD"),)),
    ExposureRule(("锌", "铅锌"), "铅锌", "sh000819", "有色金属", (("沪锌", "ZN0"),), (("LME锌", "ZSD"),)),
    ExposureRule(("镍", "不锈钢"), "镍", "sh000819", "有色金属", (("沪镍", "NI0"),), (("LME镍", "NID"),)),
    ExposureRule(("锡",), "锡", "sh000819", "有色金属", (("沪锡", "SN0"),), (("LME锡", "SND"),)),
    ExposureRule(("铅",), "铅", "sh000819", "有色金属", (("沪铅", "PB0"),), (("LME铅", "PBD"),)),
    ExposureRule(
        ("碳酸锂", "锂矿", "锂电", "锂", "能源金属"),
        "锂",
        "sh000941",
        "能源金属",
        (("碳酸锂", "LC0"),),
    ),
    ExposureRule(("工业硅", "硅料"), "工业硅", "sh000941", "能源金属", (("工业硅", "SI0"),)),
    ExposureRule(("钴", "稀土", "小金属"), "小金属", "sh000819", "有色金属", ()),
    ExposureRule(("黄金", "金矿", "贵金属"), "黄金", "sh000068", "黄金", (("沪金", "AU0"),), (("COMEX黄金", "GC"),)),
    ExposureRule(("白银",), "白银", "sh000068", "黄金", (("沪银", "AG0"),), (("COMEX白银", "SI"),)),
    ExposureRule(("煤炭", "焦煤", "焦炭", "动力煤"), "煤炭", "sz399998", "煤炭行业", (("焦煤", "JM0"), ("焦炭", "J0"))),
    ExposureRule(
        ("铁矿",),
        "铁矿石",
        "sz399440",
        "钢铁行业",
        (("铁矿石", "I0"),),
        (("SGX铁矿", "FEF"),),
    ),
    ExposureRule(
        ("钢铁", "普钢", "特钢"),
        "钢铁",
        "sz399440",
        "钢铁行业",
        (("铁矿石", "I0"), ("螺纹钢", "RB0")),
        (("SGX铁矿", "FEF"),),
    ),
    ExposureRule(
        ("天然气",),
        "天然气",
        "sh000928",
        "石油行业",
        (("原油", "SC0"),),
        (("NYMEX天然气", "NG"), ("NYMEX原油", "CL")),
    ),
    ExposureRule(
        ("石油", "油气", "原油", "炼化", "石化"),
        "油气",
        "sh000928",
        "石油行业",
        (("原油", "SC0"),),
        (("NYMEX原油", "CL"), ("NYMEX天然气", "NG")),
    ),
    ExposureRule(
        ("PTA", "涤纶", "化纤"),
        "化纤",
        "sh000813",
        "化学纤维",
        (("PTA", "TA0"),),
        (("NYMEX原油", "CL"),),
    ),
    ExposureRule(("甲醇", "煤化工"), "甲醇", "sh000813", "化学原料", (("甲醇", "MA0"),)),
    ExposureRule(("橡胶", "轮胎"), "橡胶", "sh000813", "橡胶", (("橡胶", "RU0"),), (("TOCOM橡胶", "TRB"),)),
    ExposureRule(("棉花", "棉纺"), "棉花", "sz399231", "纺织制造", (("棉花", "CF0"),), (("ICE棉花", "CT"),)),
    ExposureRule(("白糖", "制糖", "食糖"), "白糖", "sz399231", "农林牧渔", (("白糖", "SR0"),), (("ICE原糖", "SB"),)),
    ExposureRule(("豆粕", "饲料"), "饲料", "sz399231", "农林牧渔", (("豆粕", "M0"),), (("CBOT豆粕", "SM"),)),
    ExposureRule(
        ("豆油", "棕榈"),
        "油脂",
        "sz399231",
        "农林牧渔",
        (("豆油", "Y0"), ("棕榈油", "P0")),
        (("CBOT豆油", "BO"),),
    ),
    ExposureRule(("玉米",), "玉米", "sz399231", "农林牧渔", (("玉米", "C0"),), (("CBOT玉米", "C"),)),
    ExposureRule(
        ("农业", "种植", "粮食", "农产品"),
        "农业",
        "sz399231",
        "农林牧渔",
        (("豆粕", "M0"), ("玉米", "C0")),
        (("CBOT豆粕", "SM"), ("CBOT玉米", "C")),
    ),
    ExposureRule(("有色", "工业金属"), "有色金属", "sh000819", "有色金属", (("沪铜", "CU0"), ("沪铝", "AL0")), _INTL_CU),
    ExposureRule(("金属",), "有色金属", "sh000819", "有色金属", (("沪铜", "CU0"), ("沪铝", "AL0")), _INTL_CU),
    ExposureRule(("电池",), "电池", "sh000941", "电池", (("碳酸锂", "LC0"),)),
    ExposureRule(("光伏",), "光伏", "sh000941", "光伏设备", ()),
    ExposureRule(("白酒",), "白酒", "sz399997", "白酒", ()),
    ExposureRule(("银行",), "银行", "sz399986", "银行", ()),
    ExposureRule(("证券",), "证券", "sz399975", "证券", ()),
    ExposureRule(("房地产", "地产"), "房地产", "sh000006", "房地产", ()),
    ExposureRule(("医药", "生物制品", "中药"), "医药", "sh000933", "医药生物", ()),
)

# East Money overseas names when Sina ``futures_foreign_hist`` is empty.
_INTL_EM_ALIASES: dict[str, tuple[str, ...]] = {
    "CAD": ("LME铜", "LME铜3个月"),
    "HG": ("COMEX铜",),
    "AHD": ("LME铝", "LME铝3个月"),
    "ZSD": ("LME锌", "LME锌3个月"),
    "NID": ("LME镍", "LME镍3个月"),
    "SND": ("LME锡", "LME锡3个月"),
    "PBD": ("LME铅", "LME铅3个月"),
    "GC": ("COMEX黄金",),
    "SI": ("COMEX白银",),
    "CL": ("NYMEX原油", "WTI原油"),
    "NG": ("NYMEX天然气",),
    "FEF": ("SGX铁矿石", "新加坡铁矿石", "铁矿石"),
    "S": ("CBOT黄豆", "CBOT大豆"),
    "SM": ("CBOT黄豆粉", "CBOT豆粕"),
    "C": ("CBOT玉米",),
    "BO": ("CBOT豆油",),
    "CT": ("NYBOT棉花", "ICE棉花"),
    "SB": ("NYBOT原糖", "ICE原糖"),
    "TRB": ("日本橡胶", "TOCOM橡胶"),
}


def match_exposure(industry: str, name: str) -> ExposureRule | None:
    """Return the first static rule whose keyword appears in industry or name."""
    blob = f"{industry}{name}"
    if not blob.strip():
        return None
    for rule in _EXPOSURE_RULES:
        if any(key in blob for key in rule.keywords):
            return rule
    return None


def _fetch_industry_series(ak, as_of: str, lookback_start: str, rule: ExposureRule) -> list[dict]:
    """East Money industry board hist, then the CSI/Tencent index used for HS300."""
    start_n = _yyyymmdd(lookback_start)
    end_n = _yyyymmdd(as_of)
    rows = _try_ak_records(
        ak,
        ("stock_board_industry_hist_em", "stock_board_industry_index_ths"),
        (
            {
                "symbol": rule.board_em,
                "start_date": start_n,
                "end_date": end_n,
                "period": "daily",
                "adjust": "",
            },
            {"symbol": rule.board_em, "start_date": start_n, "end_date": end_n},
            {"symbol": rule.board_em},
        ),
    )
    if rows:
        return _index_rows_as_of(rows, as_of)
    symbols = (rule.index_symbol,)
    if rule.index_symbol[:2] in {"sh", "sz", "bj"} and len(rule.index_symbol) > 2:
        symbols = (rule.index_symbol, rule.index_symbol[2:])
    for symbol in symbols:
        rows = _fetch_index_daily(ak, as_of, lookback_start, symbol)
        if rows:
            return rows
    return []


def _fetch_futures_daily(ak, symbol: str, as_of: str) -> list[dict]:
    """Sina continuous first; East Money hist when Sina is empty. Never invent."""
    rows = _try_ak_records(
        ak,
        ("futures_zh_daily_sina", "futures_main_sina"),
        (
            {"symbol": symbol},
            {"symbol": symbol.lower()},
            {"symbol": symbol.upper()},
        ),
    )
    if rows:
        return _index_rows_as_of(rows, as_of)
    em_symbol = symbol.upper()[:-1] if symbol.upper().endswith("0") else symbol
    rows = _try_ak_records(
        ak,
        ("futures_hist_em", "futures_zh_daily"),
        (
            {"symbol": em_symbol, "period": "daily"},
            {"symbol": em_symbol},
            {"symbol": symbol},
        ),
    )
    return _index_rows_as_of(rows, as_of)


def _fetch_intl_futures_daily(ak, symbol: str, as_of: str) -> list[dict]:
    """Sina foreign hist (CAD=LME Cu, HG=COMEX Cu); East Money Chinese names next."""
    rows = _try_ak_records(
        ak,
        ("futures_foreign_hist", "futures_hf_hist"),
        (
            {"symbol": symbol},
            {"symbol": symbol.upper()},
            {"symbol": symbol.lower()},
        ),
    )
    if rows:
        return _index_rows_as_of(rows, as_of)
    aliases = _INTL_EM_ALIASES.get(symbol.upper(), ())
    if aliases:
        rows = _try_ak_records(
            ak,
            ("futures_global_hist_em", "futures_foreign_hist_em"),
            tuple({"symbol": name} for name in aliases),
        )
    return _index_rows_as_of(rows, as_of)


def _commodity_rets(
    ak,
    label: str,
    symbol: str,
    as_of: str,
    *,
    international: bool = False,
) -> dict[str, Any]:
    prefix = "fut_intl_" if international else "fut_"
    channel = prefix + symbol.lower()
    loader = _fetch_intl_futures_daily if international else _fetch_futures_daily
    rows = _cached(
        GLOBAL_KEY,
        as_of,
        channel,
        lambda: loader(ak, symbol, as_of),
    )
    last_date = rows[-1]["date"] if rows else None
    return {
        "name": f"{label} {symbol}",
        "ret_1d": _index_ret(rows, as_of, 1),
        "ret_5d": _index_ret(rows, as_of, 5),
        "as_of": last_date,
    }


def _exposure_features(
    ak,
    industry: str,
    name: str,
    as_of: str,
    lookback_start: str,
    stock_ret_5: float | None,
) -> dict[str, Any]:
    """Industry relative strength + mapped commodities. Fail open to unavailable."""
    empty_note = (
        "no static industry/commodity map for this listing; "
        "do not invent sector or metal prices"
    )
    rule = match_exposure(industry, name)
    out: dict[str, Any] = {
        "listed_industry": industry or None,
        "industry_map": None,
        "industry_index": None,
        "industry_ret_1d": None,
        "industry_ret_5d": None,
        "industry_ret_20d": None,
        "stock_vs_industry_5d": None,
        "commodity_1": None,
        "commodity_1_ret_1d": None,
        "commodity_1_ret_5d": None,
        "commodity_1_as_of": None,
        "commodity_2": None,
        "commodity_2_ret_1d": None,
        "commodity_2_ret_5d": None,
        "commodity_2_as_of": None,
        "intl_commodity_1": None,
        "intl_commodity_1_ret_1d": None,
        "intl_commodity_1_ret_5d": None,
        "intl_commodity_1_as_of": None,
        "intl_commodity_2": None,
        "intl_commodity_2_ret_1d": None,
        "intl_commodity_2_ret_5d": None,
        "intl_commodity_2_as_of": None,
        "note": empty_note,
    }
    if rule is None:
        return out
    channel = "idx_" + rule.index_symbol.lower()
    rows = _cached(
        GLOBAL_KEY,
        as_of,
        channel,
        lambda: _fetch_industry_series(ak, as_of, lookback_start, rule),
    )
    ind_5 = _index_ret(rows, as_of, 5)
    rs = None
    if stock_ret_5 is not None and ind_5 is not None:
        rs = round(stock_ret_5 - ind_5, 4)
    out.update(
        {
            "industry_map": rule.industry_name,
            "industry_index": rule.index_symbol,
            "industry_ret_1d": _index_ret(rows, as_of, 1),
            "industry_ret_5d": ind_5,
            "industry_ret_20d": _index_ret(rows, as_of, 20),
            "stock_vs_industry_5d": rs,
            "note": (
                "static keyword map only (not a 布局 graph); "
                "domestic SHFE/DCE plus mapped LME/COMEX/NYMEX; "
                "unavailable prints must not be invented"
            ),
        }
    )
    for i, (label, symbol) in enumerate(rule.commodities[:2], start=1):
        item = _commodity_rets(ak, label, symbol, as_of)
        out[f"commodity_{i}"] = item["name"]
        out[f"commodity_{i}_ret_1d"] = item["ret_1d"]
        out[f"commodity_{i}_ret_5d"] = item["ret_5d"]
        out[f"commodity_{i}_as_of"] = item["as_of"]
    for i, (label, symbol) in enumerate(rule.intl_commodities[:2], start=1):
        item = _commodity_rets(ak, label, symbol, as_of, international=True)
        out[f"intl_commodity_{i}"] = item["name"]
        out[f"intl_commodity_{i}_ret_1d"] = item["ret_1d"]
        out[f"intl_commodity_{i}_ret_5d"] = item["ret_5d"]
        out[f"intl_commodity_{i}_as_of"] = item["as_of"]
    return out


def _last_amount(rows: list[dict]) -> float | None:
    kept = [row for row in rows if row.get("amount") is not None]
    if not kept:
        return None
    return kept[-1]["amount"]


def _index_ret(rows: list[dict], as_of: str, n: int) -> float | None:
    kept = [row for row in rows if row.get("date") and row["date"] <= as_of and row.get("close")]
    if len(kept) < n + 1:
        return None
    start, end = kept[-(n + 1)]["close"], kept[-1]["close"]
    if not start:
        return None
    return round((end / start - 1.0) * 100.0, 4)


def _fetch_zt_pool(ak, as_of: str) -> list[dict]:
    date = _yyyymmdd(as_of)
    return _try_ak_records(
        ak,
        ("stock_zt_pool_em",),
        ({"date": date}, {"date": as_of}),
    )


def _fetch_dt_pool(ak, as_of: str) -> list[dict]:
    date = _yyyymmdd(as_of)
    return _try_ak_records(
        ak,
        ("stock_zt_pool_dtgc_em", "stock_zt_pool_zbgc_em"),
        ({"date": date}, {"date": as_of}),
    )


def _fetch_prev_zt(ak, as_of: str) -> list[dict]:
    date = _yyyymmdd(as_of)
    return _try_ak_records(
        ak,
        ("stock_zt_pool_previous_em",),
        ({"date": date}, {"date": as_of}),
    )


def _breadth_from_spot(rows: list[dict]) -> tuple[int, int]:
    """Approximate limit-up/down counts from a live Sina spot table.

    Only safe for a live as-of: the table is today's print, not a dated pool.
    """
    up = 0
    down = 0
    for row in rows:
        pct = _to_float(_field(row, ("涨跌幅", "涨跌幅(%)", "changepercent")))
        if pct is None:
            continue
        if pct >= 9.5:
            up += 1
        elif pct <= -9.5:
            down += 1
    return up, down


def _lianban_height(rows: list[dict]) -> int | None:
    heights: list[int] = []
    for row in rows:
        raw = _field(row, ("连板数", "连板", "几天几板", "封板天数"))
        if not raw:
            continue
        digits = "".join(ch if ch.isdigit() else " " for ch in raw).split()
        if digits:
            heights.append(int(digits[-1]))
    return max(heights) if heights else None


def _mean_float(rows: list[dict], keys: tuple[str, ...]) -> float | None:
    values = [_to_float(_field(row, keys)) for row in rows]
    values = [item for item in values if item is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _fetch_northbound(ak, code: str, as_of: str) -> dict[str, Any]:
    rows = _try_ak_records(
        ak,
        (
            "stock_hsgt_individual_em",
            "stock_hsgt_hold_stock_em",
            "stock_hsgt_individual_detail_em",
        ),
        ({"symbol": code}, {"stock": code}, {}),
    )
    dated: list[tuple[str, dict]] = []
    for row in rows:
        date = _to_date(_field(row, ("日期", "date", "持股日期")))
        if date and date < as_of:
            dated.append((date, row))
    empty = {
        "northbound_net_inflow": None,
        "northbound_holding_ratio": None,
        "northbound_as_of": None,
        "northbound_market_net_inflow": None,
    }
    if dated:
        dated.sort(key=lambda item: item[0])
        last_date, last = dated[-1]
        inflow = _to_float(
            _field(last, ("今日持股-增减", "持股增减", "净买入额", "北向资金净买入", "净流入"))
        )
        holding = _to_float(_field(last, ("持股占比", "持股数量占A股比例", "持股比例")))
        return {
            "northbound_net_inflow": inflow,
            "northbound_holding_ratio": holding,
            "northbound_as_of": last_date,
            "northbound_market_net_inflow": None,
        }
    market = _try_ak_records(
        ak,
        ("stock_hsgt_hist_em", "stock_hsgt_north_net_flow_in_em"),
        ({"symbol": "北向资金"}, {}),
    )
    dated_m: list[tuple[str, dict]] = []
    for row in market:
        date = _to_date(_field(row, ("日期", "date")))
        if date and date < as_of:
            dated_m.append((date, row))
    if not dated_m:
        return empty
    dated_m.sort(key=lambda item: item[0])
    last_date, last = dated_m[-1]
    market_inflow = _to_float(
        _field(last, ("当日成交净买额", "净买入", "北向资金", "value", "净流入"))
    )
    return {
        **empty,
        "northbound_as_of": last_date,
        "northbound_market_net_inflow": market_inflow,
    }


def _fetch_lhb(ak, code: str, as_of: str) -> dict[str, Any]:
    from .akshare_flow import summarize_lhb

    return summarize_lhb(ak, code, as_of)


def _fetch_margin(ak, code: str, as_of: str) -> dict[str, Any]:
    rows = _try_ak_records(
        ak,
        (
            "stock_margin_detail_szse",
            "stock_margin_detail_sse",
            "stock_margin_sse",
            "stock_margin_underlying_info_szse",
        ),
        ({"date": _yyyymmdd(as_of)}, {"symbol": code}),
        allow_empty_call=False,
    )
    dated = []
    for row in rows:
        date = _to_date(_field(row, ("信用交易日期", "日期", "date")))
        symbol = _field(row, ("证券代码", "代码", "symbol"))
        if date and date <= as_of and (not symbol or code in symbol):
            dated.append((date, row))
    if not dated:
        return {"margin_balance_chg": None}
    dated.sort(key=lambda item: item[0])
    last = dated[-1][1]
    chg = _to_float(_field(last, ("融资余额差额", "融资净买入", "融资余额变化", "融资买入额")))
    return {"margin_balance_chg": chg}


def _fetch_unlock(ak, code: str, as_of: str) -> dict[str, float | None]:
    rows = _try_ak_records(
        ak,
        (
            "stock_restricted_release_queue_em",
            "stock_restricted_release_detail_em",
            "stock_restricted_release_summary_em",
        ),
        ({"symbol": code}, {"date": _yyyymmdd(as_of)}),
        allow_empty_call=False,
    )
    end_5 = datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=5)
    end_20 = datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=20)
    start = datetime.strptime(as_of, "%Y-%m-%d")
    mv_5 = 0.0
    mv_20 = 0.0
    found = False
    for row in rows:
        symbol = _field(row, ("股票代码", "代码", "symbol"))
        if symbol and code not in symbol:
            continue
        date = _to_date(_field(row, ("解禁日期", "日期", "date")))
        if not date:
            continue
        try:
            unlock = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            continue
        if unlock < start:
            continue
        mv = _to_float(_field(row, ("解禁市值", "解禁金额", "预计解禁市值"))) or 0.0
        found = True
        if unlock <= end_5:
            mv_5 += mv
        if unlock <= end_20:
            mv_20 += mv
    if not found:
        return {"lift_ban_mv_5d": None, "lift_ban_mv_20d": None}
    return {"lift_ban_mv_5d": round(mv_5, 2), "lift_ban_mv_20d": round(mv_20, 2)}


def _event_flags(code: str, as_of: str, is_st: bool) -> dict[str, Any]:
    start = datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=2)
    end = datetime.strptime(as_of, "%Y-%m-%d")
    items = query_items(code, start, end)
    if not items and is_live_as_of(as_of):
        # Live predict with an empty warehouse: one-shot ingest, not a worker.
        # Historical as-of must not pull today's wires (lookahead).
        try:
            from .news_ingest import ingest_news

            ingest_news(code, curr_date=as_of, include_global=True)
        except (AkshareNotConfiguredError, ValueError, OSError, RuntimeError) as e:
            # Vendor HTTP / empty extra must not abort the tape; flags stay empty.
            logger.warning("Live news ingest for tape events failed for %s: %s", code, e)
        else:
            items = query_items(code, start, end)
    blob = " ".join(f"{item.title}{item.body}{item.category}" for item in items)
    bad = any(marker in blob for marker in _ANNOUNCE_BAD)
    good = any(marker in blob for marker in _ANNOUNCE_GOOD)
    return {
        "announce_bad": bad,
        "announce_good": good,
        "is_loss_or_st": is_st or ("亏损" in blob) or ("ST" in blob.upper()),
        "event_item_count": len(items),
    }


_SPOT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("last", ("最新", "最新价", "price")),
    ("pct_chg", ("涨跌幅", "涨跌幅(%)")),
    ("change", ("涨跌额",)),
    ("open", ("今开", "开盘")),
    ("high", ("最高", "最高价")),
    ("low", ("最低", "最低价")),
    ("preclose", ("昨收", "昨收价")),
    ("volume", ("成交量",)),
    ("amount", ("成交额",)),
    ("turnover", ("换手率",)),
    ("quote_time", ("时间", "时间戳")),
)


def _map_spot(source: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, names in _SPOT_FIELDS:
        value = _field(source, names)
        if key == "quote_time":
            out[key] = value
        else:
            out[key] = _to_float(value)
    return out


def _spot_from_rows(rows: list[dict], code: str) -> dict[str, Any]:
    if not rows:
        return {}
    first = rows[0]
    if _field(first, ("item", "指标")) and _field(first, ("value", "值")):
        pairs = {
            str(_field(row, ("item", "指标"))): _field(row, ("value", "值"))
            for row in rows
            if _field(row, ("item", "指标"))
        }
        return _map_spot(pairs)
    for row in rows:
        row_code = str(_field(row, ("代码", "code")) or "").zfill(6)
        if row_code == code:
            return _map_spot(row)
    return _map_spot(first)


def _xq_spot_symbol(code: str) -> str:
    if code.startswith(("4", "8")) or code.startswith("920"):
        return f"BJ{code}"
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


def _spot_from_minute_rows(rows: list[dict], as_of: str) -> dict[str, Any]:
    last: dict | None = None
    for row in rows:
        stamp = str(_field(row, ("时间", "datetime", "日期")) or "")
        close = _to_float(_field(row, ("收盘", "close", "最新", "最新价")))
        if close is None:
            continue
        compact = stamp.replace("-", "").replace(":", "").replace(" ", "")
        if as_of.replace("-", "") not in compact and as_of not in stamp:
            last = last or row
            continue
        last = row
    if last is None:
        return {}
    return {
        "last": _to_float(_field(last, ("收盘", "close", "最新", "最新价"))),
        "pct_chg": _to_float(_field(last, ("涨跌幅", "涨跌幅(%)"))),
        "change": None,
        "open": _to_float(_field(last, ("开盘", "open"))),
        "high": _to_float(_field(last, ("最高", "high"))),
        "low": _to_float(_field(last, ("最低", "low"))),
        "preclose": None,
        "volume": _to_float(_field(last, ("成交量", "volume"))),
        "amount": _to_float(_field(last, ("成交额", "amount"))),
        "turnover": _to_float(_field(last, ("换手率",))),
        "quote_time": _field(last, ("时间", "datetime", "日期")),
    }


def _spot_snapshot(ak, code: str, as_of: str) -> dict[str, Any] | None:
    """Latest public print. Historical as-of must not see today's spot (lookahead)."""
    if not is_live_as_of(as_of):
        return None
    ttl = get_config().get("news_telegraph_ttl_seconds", 120)
    try:
        ttl_seconds = int(ttl) if ttl is not None else 120
    except (TypeError, ValueError):
        ttl_seconds = 120

    def _load() -> list[dict]:
        rows = _try_ak_records(ak, ("stock_bid_ask_em",), ({"symbol": code},))
        if rows:
            return rows
        rows = _try_ak_records(
            ak,
            ("stock_individual_spot_xq",),
            ({"symbol": _xq_spot_symbol(code)}, {"symbol": code}),
        )
        if rows:
            return rows
        prefixed = a_share_prefixed_symbol(code)
        return _try_ak_records(
            ak,
            ("stock_zh_a_minute",),
            (
                {"symbol": prefixed, "period": "1", "adjust": ""},
                {"symbol": prefixed, "period": "5", "adjust": ""},
            ),
        )

    rows = _cached(code, as_of, "spot_em", _load, ttl_seconds=ttl_seconds)
    mapped = _spot_from_rows(rows, code)
    if not mapped or mapped.get("last") is None:
        mapped = _spot_from_minute_rows(rows, as_of)
    if not mapped or mapped.get("last") is None:
        return {
            "last": None,
            "pct_chg": None,
            "quote_time": None,
            "note": "live quote unavailable; do not invent a price",
        }
    mapped["note"] = (
        "latest public print for a same-day prediction; not a broker fill; "
        "this framework never places orders"
    )
    return mapped


def _minute_features(ak, code: str, as_of: str, preclose: float | None) -> dict[str, float | None]:
    start = f"{as_of} 09:15:00"
    end = f"{as_of} 10:05:00"
    rows = _try_ak_records(
        ak,
        ("stock_zh_a_hist_min_em",),
        (
            {"symbol": code, "start_date": start, "end_date": end, "period": "15", "adjust": ""},
            {"symbol": code, "period": "15", "adjust": ""},
        ),
    )
    if not rows:
        prefixed = a_share_prefixed_symbol(code)
        rows = _try_ak_records(
            ak,
            ("stock_zh_a_minute",),
            (
                {"symbol": prefixed, "period": "15", "adjust": ""},
                {"symbol": prefixed, "period": "5", "adjust": ""},
            ),
        )
    bars: list[tuple[str, float, float | None]] = []
    for row in rows:
        stamp = str(_field(row, ("时间", "datetime", "日期")) or "")
        if as_of.replace("-", "") not in stamp.replace("-", "") and as_of not in stamp:
            continue
        close = _to_float(_field(row, ("收盘", "close")))
        amount = _to_float(_field(row, ("成交额", "amount")))
        if close is None:
            continue
        bars.append((stamp, close, amount))
    if not bars or preclose in (None, 0):
        return {"auction_pct": None, "ret_15m": None, "ret_30m": None, "amount_share_15m": None}

    def vs_pre(close: float) -> float:
        return round((close / preclose - 1.0) * 100.0, 4)

    first_close = bars[0][1]
    ret_15 = vs_pre(bars[0][1])
    ret_30 = vs_pre(bars[1][1]) if len(bars) > 1 else None
    amt_15 = bars[0][2]
    amt_all = sum(item[2] or 0.0 for item in bars)
    share = round(amt_15 / amt_all, 4) if amt_15 and amt_all else None
    return {
        "auction_pct": vs_pre(first_close),
        "ret_15m": ret_15,
        "ret_30m": ret_30,
        "amount_share_15m": share,
    }


def _csv(rows: list[dict], fields: list[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else row[key] for key in fields})
    return buf.getvalue().strip()


def _kv_block(title: str, mapping: dict[str, Any]) -> str:
    lines = [f"## {title}"]
    for key, value in mapping.items():
        display = "<unavailable>" if value is None or value == "" else value
        lines.append(f"- {key}: {display}")
    return "\n".join(lines)


def _stock_name(ak, code: str) -> str:
    name = _name_from_profile_rows(fetch_a_share_profile_rows(ak, code), code)
    if name:
        return name
    listing = _try_ak_records(
        ak,
        ("stock_info_a_code_name",),
        ({"symbol": code},),
        allow_empty_call=False,
    )
    for row in listing:
        raw = _field(row, ("代码", "code", "symbol", "股票代码"))
        row_code = a_share_code(raw) if raw else None
        if row_code is None and raw:
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            row_code = digits if len(digits) == 6 else None
        if row_code != code:
            continue
        name = _field(row, ("名称", "股票简称", "name"))
        if name:
            return name
    return ""


def _industry_from_info(ak, code: str) -> str:
    for row in fetch_a_share_profile_rows(ak, code):
        item = _field(row, ("item", "指标"))
        if item in {"行业", "所属行业"}:
            value = _field(row, ("value", "值"))
            if value:
                return value
        if item:
            continue
        industry = _field(row, ("所属行业", "行业"))
        if industry:
            return industry
    return ""


def resolve_a_share_identity(ticker: str) -> dict[str, str]:
    """Deterministic A-share card: venue/board always; name/industry best-effort.

    Board and exchange are syntactic from the six-digit code so routing still
    works when AKTools is down. Company name is never invented: missing
    AKTools or a failed lookup omits ``company_name``.
    """
    code = a_share_code(ticker)
    if code is None:
        return {}
    identity: dict[str, str] = {
        "market": "China A-share",
        "board_type": a_share_board_type(code),
        "exchange": a_share_exchange_name(code),
    }
    try:
        ak = _load_akshare()
    except AkshareNotConfiguredError:
        logger.debug("AKTools not configured; A-share identity is syntactic for %s", ticker)
        return identity
    try:
        name = _stock_name(ak, code)
    except Exception as e:
        logger.debug("A-share name lookup failed for %s: %s", ticker, e)
        return identity
    if name:
        identity["company_name"] = name
        if _is_st_name(name):
            identity["board_type"] = a_share_board_type(code, is_st=True)
    try:
        industry = _industry_from_info(ak, code)
    except Exception as e:
        logger.debug("A-share industry lookup failed for %s: %s", ticker, e)
        return identity
    if industry:
        identity["industry"] = industry
    return identity


def get_ashare_short_horizon(ticker: str, curr_date: str, look_back_days: int | None = None) -> str:
    """Markdown tape for next-session / 5–20d A-share features as of ``curr_date``."""
    code = a_share_code(ticker)
    if code is None:
        raise NoMarketDataError(
            ticker, ticker, "not a China A-share symbol; short-horizon tape is A-share only"
        )
    datetime.strptime(curr_date, "%Y-%m-%d")
    if look_back_days is None:
        look_back_days = 40
    start = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=int(look_back_days))).strftime(
        "%Y-%m-%d"
    )
    ak = _load_akshare()

    name = _stock_name(ak, code)
    is_st = _is_st_name(name)

    qfq = [
        _row_ohlc(row)
        for row in _cached(
            code, curr_date, "daily_qfq", lambda: _fetch_daily(ak, code, start, curr_date, "qfq")
        )
    ]
    raw = [
        _row_ohlc(row)
        for row in _cached(
            code, curr_date, "daily_raw", lambda: _fetch_daily(ak, code, start, curr_date, "")
        )
    ]
    merged = _align_amount(qfq, raw) if raw else qfq
    hs300 = _cached(
        GLOBAL_KEY,
        curr_date,
        "idx_hs300",
        lambda: _fetch_index_daily(ak, curr_date, start, "sh000300"),
    )
    index_dates = {row["date"] for row in hs300 if row.get("date")}
    daily = _decorate_daily(merged, code, curr_date, is_st=is_st, index_dates=index_dates)
    daily = [row for row in daily if row.get("date") and row["date"] <= curr_date]
    if not daily:
        raise NoMarketDataError(ticker, code, "no A-share daily bars in the requested window")

    cyb = _cached(
        GLOBAL_KEY,
        curr_date,
        "idx_cyb",
        lambda: _fetch_index_daily(ak, curr_date, start, "sz399006"),
    )
    sse = _cached(
        GLOBAL_KEY,
        curr_date,
        "idx_sse",
        lambda: _fetch_index_daily(ak, curr_date, start, "sh000001"),
    )
    sza = _cached(
        GLOBAL_KEY,
        curr_date,
        "idx_sza",
        lambda: _fetch_index_daily(ak, curr_date, start, "sz399107"),
    )
    bank = _cached(
        GLOBAL_KEY,
        curr_date,
        "idx_bank",
        lambda: _fetch_index_daily(ak, curr_date, start, "sz399986"),
    )

    zt = _cached(GLOBAL_KEY, curr_date, "zt_pool", lambda: _fetch_zt_pool(ak, curr_date))
    dt = _cached(GLOBAL_KEY, curr_date, "dt_pool", lambda: _fetch_dt_pool(ak, curr_date))
    prev_zt = _cached(GLOBAL_KEY, curr_date, "prev_zt", lambda: _fetch_prev_zt(ak, curr_date))
    breadth_source = "east_money_zt_pool"
    if not zt and not dt and is_live_as_of(curr_date):
        ttl = get_config().get("news_telegraph_ttl_seconds", 120)
        try:
            ttl_seconds = int(ttl) if ttl is not None else 120
        except (TypeError, ValueError):
            ttl_seconds = 120
        sina = _cached(
            GLOBAL_KEY,
            curr_date,
            "sina_spot",
            lambda: _try_ak_records(ak, ("stock_zh_a_spot",), ({},)),
            ttl_seconds=ttl_seconds,
        )
        if sina:
            up, down = _breadth_from_spot(sina)
            zt = [{}] * up
            dt = [{}] * down
            breadth_source = "sina_spot_live_approx"

    last = daily[-1]
    preclose = last.get("preclose")
    minutes = _minute_features(ak, code, curr_date, preclose)
    spot = _spot_snapshot(ak, code, curr_date)
    north = _fetch_northbound(ak, code, curr_date)
    lhb = _fetch_lhb(ak, code, curr_date)
    margin = _fetch_margin(ak, code, curr_date)
    unlock = _fetch_unlock(ak, code, curr_date)
    events = _event_flags(code, curr_date, is_st)
    horizon = _horizon_stats(daily[-21:])
    industry = _industry_from_info(ak, code)
    exposure = _exposure_features(
        ak, industry, name, curr_date, start, horizon.get("ret_5")
    )

    daily_fields = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
        "turnover",
        "pct_chg",
        "amplitude",
        "volume_ratio",
        "limit_up",
        "limit_down",
        "touched_limit_up",
        "board_type",
        "is_paused",
    ]
    recent = daily[-21:]
    header = (
        f"# A-share short-horizon tape for {ticker} (code {code}"
        f"{', ' + name if name else ''}) as of {curr_date}\n"
        "Target: next tradable session (T+1) and 5–20 trading days. "
        "Not a valuation model. Limit-up seals are unbuyable until they open.\n"
        "Prices are forward-adjusted; amount/volume/turnover prefer unadjusted prints.\n"
        "Northbound is lagged to the last published session before as-of.\n"
        "Industry/commodity rows are a static keyword map (max two domestic "
        "contracts plus mapped LME/COMEX/NYMEX), not a company 布局 graph; "
        "unavailable means do not invent prices. International bars keep "
        "date<=as-of (no lookahead even if the overseas session is still open).\n"
        "This tape is a prediction input only; the framework never places orders.\n"
    )
    sections = [
        header,
        "## Daily bars (qfq close, raw amount)\n\n" + _csv(recent, daily_fields),
        _kv_block("Intraday structure (best-effort 15m; not tick data)", minutes),
    ]
    if spot is not None:
        sections.append(_kv_block("Live snapshot (latest public print; not an order)", spot))
    hs300_ret_1d = _index_ret(hs300, curr_date, 1)
    prev_premium = _mean_float(prev_zt, ("涨跌幅", "溢价", "昨收溢价"))
    playbook = build_playbook_stance(
        daily_rows=daily,
        as_of=curr_date,
        market_amount_yuan=combine_market_amount(_last_amount(sse), _last_amount(sza)),
        prev_zt_premium=prev_premium,
        limit_up_count=len(zt),
        limit_down_count=len(dt),
        bank_ret_1d=_index_ret(bank, curr_date, 1),
        hs300_ret_1d=hs300_ret_1d,
        announce_bad=bool(events.get("announce_bad")),
        is_st_or_loss=bool(events.get("is_loss_or_st")),
        lift_ban_mv_5d=unlock.get("lift_ban_mv_5d"),
        live_pct=None if spot is None else spot.get("pct_chg"),
    )
    material_news = has_material_stock_news(events)
    mood = resolve_market_mood(
        as_of=curr_date,
        hs300_rows=hs300,
        regime=str(playbook.get("regime") or "unknown"),
        limit_up_count=len(zt),
        limit_down_count=len(dt),
        prev_zt_premium=prev_premium,
        index_ret_1d=hs300_ret_1d,
    )
    stock_t1 = str(playbook.get("t1_bias") or "HOLD")
    stock_t1_reason = str(playbook.get("t1_reason") or "")
    blended_t1, blended_reason = blend_stock_with_market_mood(
        stock_t1,
        str(mood.get("mood_t1") or "HOLD"),
        material_news=material_news,
        stock_reason=stock_t1_reason,
        mood_reason=str(mood.get("mood_t1_reason") or ""),
    )
    playbook = {
        **playbook,
        "stock_t1_before_mood": stock_t1,
        "market_mood_t1": mood.get("mood_t1"),
        "market_mood_swing": mood.get("mood_swing"),
        "material_stock_news": material_news,
        "t1_bias": blended_t1,
        "t1_reason": blended_reason,
    }
    sections.extend(
        [
            _kv_block(
                "Market mood (全市场)",
                {
                    "regime": mood.get("regime"),
                    "market_mood_t1": mood.get("mood_t1"),
                    "mood_t1_reason": mood.get("mood_t1_reason"),
                    "market_mood_swing": mood.get("mood_swing"),
                    "mood_swing_reason": mood.get("mood_swing_reason"),
                    "limit_up_count": mood.get("limit_up_count"),
                    "limit_down_count": mood.get("limit_down_count"),
                    "prev_zt_premium": mood.get("prev_zt_premium"),
                    "hs300_ret_1d": mood.get("hs300_ret_1d"),
                    "material_stock_news": material_news,
                },
            ),
            _kv_block(
                "Market tape (as-of close)",
                {
                    "index_hs300_ret_1d": hs300_ret_1d,
                    "index_hs300_ret_20d": _index_ret(hs300, curr_date, 20),
                    "index_cyb_ret_1d": _index_ret(cyb, curr_date, 1),
                    "index_cyb_ret_20d": _index_ret(cyb, curr_date, 20),
                    "market_limit_up_count": len(zt),
                    "market_limit_down_count": len(dt),
                    "market_breadth_source": breadth_source,
                    "lianban_height": _lianban_height(zt),
                    "prev_zt_premium": prev_premium,
                    "board_type": last.get("board_type"),
                    "limit_pct": last.get("limit_pct"),
                },
            ),
            _kv_block("Playbook stance (T+1)", playbook),
            _kv_block(
                "Capital (published vintage only)",
                {
                    **north,
                    **lhb,
                    **margin,
                },
            ),
            _kv_block("Events (warehouse keywords + unlock calendar)", {**events, **unlock}),
            _kv_block(
                "Industry and commodity exposure (static map; not a 布局 graph)",
                exposure,
            ),
            _kv_block("5–20d continuation features (from daily tape)", horizon),
        ]
    )
    return "\n\n".join(sections)


def get_ashare_swing_tape(
    ticker: str,
    curr_date: str,
    window: str | None = None,
) -> str:
    """Markdown swing price-volume tape (近半个月 / 近3个月 / 近半年), 缠论, flow, news."""
    from .akshare_flow import render_buy_sell_window

    code = a_share_code(ticker)
    if code is None:
        raise NoMarketDataError(
            ticker, ticker, "not a China A-share symbol; swing tape is A-share only"
        )
    datetime.strptime(curr_date, "%Y-%m-%d")
    key = resolve_swing_window(window)
    spec = SWING_WINDOWS[key]
    calendar_days = int(spec["calendar_days"])
    label = str(spec["label"])
    table_bars = int(spec["table_bars"])
    start = (
        datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=calendar_days)
    ).strftime("%Y-%m-%d")
    as_of_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    chanlun_start = (as_of_dt - timedelta(days=CHANLUN_CALENDAR_DAYS)).strftime(
        "%Y-%m-%d"
    )
    fetch_start = min(
        (as_of_dt - timedelta(days=calendar_days + 20)).strftime("%Y-%m-%d"),
        chanlun_start,
    )
    ak = _load_akshare()
    name = _stock_name(ak, code)
    is_st = _is_st_name(name)
    qfq = [
        _row_ohlc(row)
        for row in _cached(
            code,
            curr_date,
            "swing_qfq_chanlun",
            lambda: _fetch_daily(ak, code, fetch_start, curr_date, "qfq"),
        )
    ]
    raw = [
        _row_ohlc(row)
        for row in _cached(
            code,
            curr_date,
            "swing_raw_chanlun",
            lambda: _fetch_daily(ak, code, fetch_start, curr_date, ""),
        )
    ]
    merged = _align_amount(qfq, raw) if raw else qfq
    hs300 = _cached(
        GLOBAL_KEY,
        curr_date,
        "swing_idx_hs300_chanlun",
        lambda: _fetch_index_daily(ak, curr_date, fetch_start, "sh000300"),
    )
    index_dates = {row["date"] for row in hs300 if row.get("date")}
    full_daily = _decorate_daily(
        merged, code, curr_date, is_st=is_st, index_dates=index_dates
    )
    chanlun_daily = [
        row
        for row in full_daily
        if row.get("date") and chanlun_start <= row["date"] <= curr_date
    ]
    daily = [
        row
        for row in full_daily
        if row.get("date") and start <= row["date"] <= curr_date
    ]
    if not daily:
        raise NoMarketDataError(
            ticker, code, f"no A-share daily bars in the {key} window"
        )
    stats = _swing_stats(daily)
    hs300_window = [
        row for row in hs300 if row.get("date") and start <= row["date"] <= curr_date
    ]
    index_ret = None
    hs_closes = [row.get("close") for row in hs300_window if row.get("close")]
    if len(hs_closes) >= 2 and hs_closes[0]:
        index_ret = round((hs_closes[-1] / hs_closes[0] - 1.0) * 100.0, 4)
    relative = None
    if stats.get("ret_window") is not None and index_ret is not None:
        relative = round(stats["ret_window"] - index_ret, 4)
    hs300_ret_20d = _index_ret(hs300, curr_date, 20)
    range_pos = close_range_position(
        [
            {
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
            }
            for row in daily
        ]
    )
    chan_for_bias = [
        {
            "date": row["date"],
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
        }
        for row in daily
        if row.get("close") is not None
    ]
    chan_snap = analyze_chanlun(chan_for_bias)
    chan_segment = chan_snap.segments[-1].direction if chan_snap.segments else None
    industry_ret_5 = None
    try:
        industry = _industry_from_info(ak, code)
        exp_start = (as_of_dt - timedelta(days=120)).strftime("%Y-%m-%d")
        exposure = _exposure_features(
            ak,
            industry,
            name or "",
            curr_date,
            exp_start,
            stats.get("ret_5"),
        )
        raw_ind = exposure.get("industry_ret_5d")
        industry_ret_5 = float(raw_ind) if raw_ind is not None else None
    except Exception as e:
        logger.warning("Swing tape industry context skipped for %s: %s", ticker, e)
    stock_trend, stock_trend_reason = compute_trend_bias(
        ret_window=stats.get("ret_window"),
        ret_5=stats.get("ret_5"),
        ret_10=stats.get("ret_10"),
        range_pos=range_pos,
        vs_index=relative,
        chan_buy_sell=chan_snap.buy_sell,
        chan_segment=chan_segment,
        hs300_ret_20d=hs300_ret_20d,
        hs300_ret_window=index_ret,
        industry_ret_5=industry_ret_5,
    )
    mood = _cached(
        GLOBAL_KEY,
        curr_date,
        "market_mood_v1",
        lambda: load_market_mood_snapshot(curr_date),
    )
    swing_events = _event_flags(code, curr_date, is_st)
    material_news = has_material_stock_news(swing_events)
    trend_bias, trend_reason = blend_stock_with_market_mood(
        stock_trend,
        str(mood.get("mood_swing") or "HOLD"),
        material_news=material_news,
        stock_reason=stock_trend_reason,
        mood_reason=str(mood.get("mood_swing_reason") or ""),
    )
    north = _northbound_window(ak, code, start, curr_date)
    try:
        flow_md = render_buy_sell_window(ticker, start, curr_date)
    except NoMarketDataError as e:
        logger.warning("swing tape flow unavailable for %s: %s", ticker, e)
        flow_md = ""
    daily_fields = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover",
        "pct_chg",
        "volume_ratio",
        "limit_up",
        "limit_down",
    ]
    recent = daily[-table_bars:]
    header = (
        f"# A-share swing tape for {ticker} (code {code}"
        f"{', ' + name if name else ''}) — {label}\n"
        f"Window: {start} to {curr_date} ({calendar_days} calendar days, "
        f"{stats.get('bars')} printed bars). "
        "Input for subsequent-trend research. Not a valuation model and not an order.\n"
        "Prices are forward-adjusted; amount/volume/turnover prefer unadjusted prints.\n"
        "Do not invent missing prices, volume, headlines, 出手/买入, or 缠论 中枢/买卖点. "
        "The team's BUY/HOLD/SELL is a research rating; this framework never places orders.\n"
    )
    sections = [
        header,
        _kv_block(
            "Price and volume (window)",
            {
                "window": key,
                "label": label,
                **{
                    field: stats.get(field)
                    for field in (
                        "bars",
                        "start_date",
                        "end_date",
                        "start_close",
                        "end_close",
                        "ret_window",
                        "ret_5",
                        "ret_10",
                        "ret_20",
                        "ret_60",
                        "ret_120",
                        "vol_20",
                        "max_dd_20",
                        "high",
                        "high_date",
                        "low",
                        "low_date",
                        "avg_volume",
                        "last_volume",
                        "volume_vs_avg",
                        "sum_amount",
                        "last_amount",
                        "avg_turnover",
                        "turnover_pctile",
                        "up_days",
                        "down_days",
                        "limit_up_days",
                        "limit_down_days",
                    )
                },
                "hs300_ret_window": index_ret,
                "hs300_ret_20d": hs300_ret_20d,
                "vs_hs300": relative,
                "range_pos": range_pos,
            },
        ),
        _kv_block(
            "Swing trend stance (research)",
            {
                "stock_trend_before_mood": stock_trend,
                "market_mood_swing": mood.get("mood_swing"),
                "material_stock_news": material_news,
                "trend_bias": trend_bias,
                "trend_reason": trend_reason,
            },
        ),
        "## Daily bars (latest in window)\n\n" + _csv(recent, daily_fields),
        _kv_block("Northbound (lagged; date < as-of)", north),
    ]
    if key == "half_year":
        weekly = _weekly_last_bars(daily)
        sections.insert(
            3,
            "## Weekly last bars\n\n"
            + _csv(weekly, ["date", "open", "high", "low", "close", "volume", "amount"]),
        )
    sections.append(
        render_chanlun_markdown(
            chanlun_daily, as_of=curr_date, ticker=ticker, timeframe="daily"
        )
    )
    weekly_ohlc = aggregate_weekly(chanlun_daily)
    if len(weekly_ohlc) >= 8:
        sections.append(
            render_chanlun_markdown(
                weekly_ohlc, as_of=curr_date, ticker=ticker, timeframe="weekly"
            )
        )
    if flow_md:
        sections.append(flow_md)
    else:
        sections.append(
            "## Disclosed 机构出手\n\n"
            f"NO_DATA_AVAILABLE: no 增减持, 龙虎榜 seats, or 大宗 for {ticker} "
            f"(code {code}) from {start} to {curr_date}. Do not invent 出手/买入."
        )
    sections.append(_swing_news_markdown(ticker, start, curr_date, calendar_days))
    return "\n\n".join(sections)


def get_akshare_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Yahoo-shaped OHLCV CSV from East Money daily bars. A-shares only."""
    code = a_share_code(symbol)
    if code is None:
        raise NoMarketDataError(
            symbol, symbol, "not a China A-share; akshare OHLCV is A-share only"
        )
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    ak = _load_akshare()
    rows = [
        _row_ohlc(row)
        for row in _fetch_daily(ak, code, start_date, end_date, "qfq")
    ]
    rows = [
        row
        for row in rows
        if row.get("date") and start_date <= row["date"] <= end_date
    ]
    if not rows:
        raise NoMarketDataError(
            symbol, code, f"no A-share daily bars between {start_date} and {end_date}"
        )
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"],
    )
    writer.writeheader()
    for row in rows:
        close = row.get("close")
        writer.writerow(
            {
                "Date": row["date"],
                "Open": row.get("open"),
                "High": row.get("high"),
                "Low": row.get("low"),
                "Close": close,
                "Adj Close": close,
                "Volume": row.get("volume"),
            }
        )
    header = (
        f"# Stock data for {code} from {start_date} to {end_date}\n"
        f"# Total records: {len(rows)}\n"
        f"# Source: akshare/AKTools\n\n"
    )
    return header + buf.getvalue()


def get_akshare_indicators(
    symbol: str, indicator: str, curr_date: str, look_back_days: int
) -> str:
    """stockstats indicators from East Money daily bars. A-shares only."""
    from dateutil.relativedelta import relativedelta
    from stockstats import wrap

    code = a_share_code(symbol)
    if code is None:
        raise NoMarketDataError(
            symbol, symbol, "not a China A-share; akshare indicators are A-share only"
        )
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start = (curr_dt - timedelta(days=max(int(look_back_days) + 400, 500))).strftime(
        "%Y-%m-%d"
    )
    ak = _load_akshare()
    rows = [
        _row_ohlc(row) for row in _fetch_daily(ak, code, start, curr_date, "qfq")
    ]
    rows = [row for row in rows if row.get("date") and row["date"] <= curr_date]
    if not rows:
        raise NoMarketDataError(symbol, code, "no A-share daily bars for indicators")
    frame = pd.DataFrame(
        [
            {
                "Date": pd.Timestamp(row["date"]),
                "Open": row.get("open"),
                "High": row.get("high"),
                "Low": row.get("low"),
                "Close": row.get("close"),
                "Volume": row.get("volume") or 0,
            }
            for row in rows
            if row.get("close") is not None
        ]
    )
    if frame.empty:
        raise NoMarketDataError(symbol, code, "no A-share closes for indicators")
    df = wrap(frame)
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    _ = df[indicator]
    values = {
        str(date): row[indicator]
        for date, row in df.set_index("Date")[[indicator]].iterrows()
        if pd.notna(row[indicator])
    }
    before = curr_dt - relativedelta(days=int(look_back_days))
    lines = [
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:",
        "",
    ]
    cursor = curr_dt
    while cursor >= before:
        date_str = cursor.strftime("%Y-%m-%d")
        value = values.get(date_str, "N/A: Not a trading day (weekend or holiday)")
        lines.append(f"{date_str}: {value}")
        cursor = cursor - relativedelta(days=1)
    lines.append("")
    lines.append("Source: akshare/AKTools daily bars.")
    return "\n".join(lines)


_AK_INDEX_SYMBOLS = {
    "000001.SS": "sh000001",
    "399001.SZ": "sz399001",
    "000300.SS": "sh000300",
    "399006.SZ": "sz399006",
}


def ak_index_symbol(yahoo_or_ak: str) -> str:
    """Map Yahoo-style A-share index tickers to AKTools ``sh000001`` form.

    Do not run ``a_share_code`` on ``000001.SS``: that six-digit code is also
    a Shenzhen listing, and the prefix would become ``sz000001``.
    """
    key = yahoo_or_ak.strip().upper()
    mapped = _AK_INDEX_SYMBOLS.get(key)
    if mapped:
        return mapped
    lower = yahoo_or_ak.strip().lower()
    if lower[:2] in {"sh", "sz", "bj"} and len(lower) >= 8:
        return lower
    return lower


def load_close_pairs(ticker: str, start: str, end: str) -> list[tuple[str, float]]:
    """Forward-adjusted close series for an A-share, inclusive of ``end``."""
    code = a_share_code(ticker)
    if code is None:
        raise NoMarketDataError(ticker, ticker, "not a China A-share")
    ak = _load_akshare()
    rows = [_row_ohlc(row) for row in _fetch_daily(ak, code, start, end, "qfq")]
    pairs = [
        (row["date"], float(row["close"]))
        for row in rows
        if row.get("date") and row.get("close") is not None and start <= row["date"] <= end
    ]
    pairs.sort(key=lambda item: item[0])
    return pairs


def load_index_close_pairs(ak_symbol: str, start: str, end: str) -> list[tuple[str, float]]:
    """Index close series from the same East Money → Tencent path as the tape."""
    ak = _load_akshare()
    rows = _fetch_index_daily(ak, end, start, ak_index_symbol(ak_symbol))
    pairs = [
        (row["date"], float(row["close"]))
        for row in rows
        if row.get("date") and row.get("close") is not None and start <= row["date"] <= end
    ]
    pairs.sort(key=lambda item: item[0])
    return pairs


def realized_holding_returns(
    ticker: str,
    trade_date: str,
    holding_days: int,
    benchmark: str,
) -> tuple[float, float, int, str] | None:
    """Raw and alpha over ``holding_days`` A-share sessions, or None if incomplete."""
    end = (
        datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=int(holding_days) + 14)
    ).strftime("%Y-%m-%d")
    stock = [(date, close) for date, close in load_close_pairs(ticker, trade_date, end) if date >= trade_date]
    bench = [
        (date, close)
        for date, close in load_index_close_pairs(benchmark, trade_date, end)
        if date >= trade_date
    ]
    if len(stock) <= holding_days or len(bench) <= holding_days:
        return None
    start_px, start_bench = stock[0][1], bench[0][1]
    if start_px in (0, None) or start_bench in (0, None):
        return None
    raw = (stock[holding_days][1] - start_px) / start_px
    alpha = raw - (bench[holding_days][1] - start_bench) / start_bench
    return raw, alpha, holding_days, stock[holding_days][0]


def next_session_raw_return(ticker: str, trade_date: str) -> tuple[float, str] | None:
    """As-of close to the next session close. None if that bar is not in yet.

    T+1 directional score uses this path only (no index). Incomplete windows
    stay None so a same-day run is not scored against a partial print.
    """
    end = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=14)).strftime("%Y-%m-%d")
    stock = [
        (date, close)
        for date, close in load_close_pairs(ticker, trade_date, end)
        if date >= trade_date
    ]
    if len(stock) < 2:
        return None
    start_px = stock[0][1]
    if start_px in (0, None):
        return None
    nxt_date, nxt_px = stock[1]
    return (nxt_px - start_px) / start_px, nxt_date
