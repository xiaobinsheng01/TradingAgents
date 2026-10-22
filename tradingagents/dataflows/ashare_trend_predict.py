"""Deterministic A-share trend snapshots for the local web console.

Reads the same swing-window daily bars as ``get_ashare_swing_tape`` and returns
a research bias for subsequent sessions. Not a broker order and not an LLM run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from .akshare_market import (
    SWING_WINDOWS,
    _align_amount,
    _cached,
    _decorate_daily,
    _event_flags,
    _exposure_features,
    _fetch_daily,
    _fetch_index_daily,
    _index_ret,
    _industry_from_info,
    _is_st_name,
    _row_ohlc,
    _stock_name,
    _swing_stats,
    resolve_swing_window,
)
from .ashare_market_mood import (
    blend_stock_with_market_mood,
    has_material_stock_news,
    load_market_mood_snapshot,
)
from .akshare_news import _load_akshare
from .ashare_trend_bias import close_range_position, compute_trend_bias
from .chanlun import analyze_chanlun
from .news_store import GLOBAL_KEY
from .symbol_utils import a_share_board_type, a_share_code

logger = logging.getLogger(__name__)

_BIAS_ZH = {"BUY": "偏多", "HOLD": "观望", "SELL": "偏空"}
_SEGMENT_ZH = {"up": "上行段", "down": "下行段"}
_POSITION_ZH = {
    "above_hub": "中枢上方",
    "below_hub": "中枢下方",
    "in_hub": "中枢内",
    "no_hub": "无中枢",
}
_NOTE = (
    "研究评级，基于价量窗口与缠论结构，覆盖后续若干交易日方向。"
    "不自动跑全图，也永不下单。"
)

class TrendPredictNotLiveError(ValueError):
    """Trend snapshots refuse historical as-of dates."""


def _utc_today() -> str:
    return datetime.now().date().isoformat()


def _coerce_day(as_of: str | None) -> str:
    if as_of is None or not str(as_of).strip():
        return _utc_today()
    text = str(as_of).strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("as_of must be YYYY-MM-DD") from e
    if parsed.date() > datetime.now().date():
        raise ValueError("as_of cannot be in the future")
    return text


def _require_today(day: str) -> None:
    if day != _utc_today():
        raise TrendPredictNotLiveError(
            "股票趋势预测只在当天可用。历史日期不能把此刻的价量当成过去某一天的预测。"
        )


def _structure_text(snap) -> str:
    if snap.buy_sell:
        return snap.buy_sell
    segment = snap.segments[-1].direction if snap.segments else None
    if segment is None:
        return "不成段"
    place = _POSITION_ZH.get(snap.position, "无中枢")
    return f"{_SEGMENT_ZH.get(segment, segment)}，{place}"


def _load_window_bars(
    ticker: str,
    as_of: str,
    window_key: str,
) -> tuple[str, str, list[dict], list[dict], dict[str, Any]]:
    code = a_share_code(ticker)
    if code is None:
        raise ValueError(f"{ticker} 不是 A 股代码")
    if a_share_board_type(code) == "chinext":
        raise ValueError("创业板不参与趋势预测")
    spec = SWING_WINDOWS[window_key]
    calendar_days = int(spec["calendar_days"])
    label = str(spec["label"])
    start = (
        datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=calendar_days)
    ).strftime("%Y-%m-%d")
    fetch_start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=calendar_days + 20)).strftime(
        "%Y-%m-%d"
    )
    ak = _load_akshare()
    name = _stock_name(ak, code)
    is_st = _is_st_name(name)
    qfq = [
        _row_ohlc(row)
        for row in _cached(
            code,
            as_of,
            f"trend_qfq_{window_key}",
            lambda: _fetch_daily(ak, code, fetch_start, as_of, "qfq"),
        )
    ]
    raw = [
        _row_ohlc(row)
        for row in _cached(
            code,
            as_of,
            f"trend_raw_{window_key}",
            lambda: _fetch_daily(ak, code, fetch_start, as_of, ""),
        )
    ]
    merged = _align_amount(qfq, raw) if raw else qfq
    hs300 = _cached(
        GLOBAL_KEY,
        as_of,
        f"trend_idx_{window_key}",
        lambda: _fetch_index_daily(ak, as_of, fetch_start, "sh000300"),
    )
    index_dates = {row["date"] for row in hs300 if row.get("date")}
    full_daily = _decorate_daily(merged, code, as_of, is_st=is_st, index_dates=index_dates)
    daily = [
        row for row in full_daily if row.get("date") and start <= row["date"] <= as_of
    ]
    if not daily:
        raise ValueError(f"{ticker} 在 {label} 窗口内没有日线")
    return code, name, daily, hs300, spec


def stock_trend_row(
    ticker: str,
    *,
    as_of: str,
    window: str | None = None,
) -> dict[str, Any]:
    """One ticker trend snapshot. Raises ``ValueError`` when data is missing."""
    window_key = resolve_swing_window(window)
    code, name, daily, hs300, spec = _load_window_bars(ticker, as_of, window_key)
    start = daily[0]["date"]
    stats = _swing_stats(daily)
    hs300_window = [
        row
        for row in hs300
        if row.get("date") and start <= row["date"] <= as_of and row.get("close")
    ]
    index_ret = None
    if len(hs300_window) >= 2 and hs300_window[0]["close"]:
        index_ret = round(
            (hs300_window[-1]["close"] / hs300_window[0]["close"] - 1.0) * 100.0,
            4,
        )
    vs_index = None
    if stats.get("ret_window") is not None and index_ret is not None:
        vs_index = round(stats["ret_window"] - index_ret, 4)
    hs300_ret_20d = _index_ret(hs300, as_of, 20)
    industry_ret_5 = None
    try:
        ak = _load_akshare()
        industry = _industry_from_info(ak, code)
        lookback = (
            datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=120)
        ).strftime("%Y-%m-%d")
        exposure = _exposure_features(
            ak,
            industry,
            name or "",
            as_of,
            lookback,
            stats.get("ret_5"),
        )
        raw_ind = exposure.get("industry_ret_5d")
        industry_ret_5 = float(raw_ind) if raw_ind is not None else None
    except Exception as e:
        logger.warning("Trend predict industry context skipped for %s: %s", ticker, e)
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
    chan_rows = [
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
    snap = analyze_chanlun(chan_rows)
    segment = snap.segments[-1].direction if snap.segments else None
    stock_bias, stock_reason = compute_trend_bias(
        ret_window=stats.get("ret_window"),
        ret_5=stats.get("ret_5"),
        ret_10=stats.get("ret_10"),
        range_pos=range_pos,
        vs_index=vs_index,
        chan_buy_sell=snap.buy_sell,
        chan_segment=segment,
        hs300_ret_20d=hs300_ret_20d,
        hs300_ret_window=index_ret,
        industry_ret_5=industry_ret_5,
    )
    mood = _cached(
        GLOBAL_KEY,
        as_of,
        "market_mood_v1",
        lambda: load_market_mood_snapshot(as_of),
    )
    events = _event_flags(code, as_of, _is_st_name(name or ""))
    material_news = has_material_stock_news(events)
    bias, reason = blend_stock_with_market_mood(
        stock_bias,
        str(mood.get("mood_swing") or "HOLD"),
        material_news=material_news,
        stock_reason=stock_reason,
        mood_reason=str(mood.get("mood_swing_reason") or ""),
    )
    last = daily[-1]
    return {
        "ticker": ticker,
        "code": code,
        "name": name or "",
        "window": window_key,
        "window_label": spec["label"],
        "start_date": start,
        "end_date": last.get("date"),
        "close": last.get("close"),
        "ret_window": stats.get("ret_window"),
        "ret_5": stats.get("ret_5"),
        "ret_10": stats.get("ret_10"),
        "vs_hs300": vs_index,
        "hs300_ret_20d": hs300_ret_20d,
        "industry_ret_5d": industry_ret_5,
        "range_pos": range_pos,
        "high": stats.get("high"),
        "low": stats.get("low"),
        "structure": _structure_text(snap),
        "stock_trend_before_mood": stock_bias,
        "market_mood_swing": mood.get("mood_swing"),
        "material_stock_news": material_news,
        "trend_bias": bias,
        "trend_label": _BIAS_ZH[bias],
        "trend_reason": reason,
    }


def stock_trend_predict(
    tickers: list[str],
    *,
    as_of: str | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    """Batch trend snapshots for normalized tickers."""
    day = _coerce_day(as_of)
    _require_today(day)
    window_key = resolve_swing_window(window)
    label = str(SWING_WINDOWS[window_key]["label"])
    symbols = [str(item).strip() for item in tickers if str(item).strip()]
    if not symbols:
        raise ValueError("至少输入一只股票代码")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for symbol in symbols:
        try:
            rows.append(stock_trend_row(symbol, as_of=day, window=window_key))
        except ValueError as e:
            logger.warning("Trend predict skipped %s: %s", symbol, e)
            errors.append({"ticker": symbol, "error": str(e)})
        except Exception as e:
            logger.warning("Trend predict failed %s: %s", symbol, e)
            errors.append({"ticker": symbol, "error": str(e)})
    if not rows and errors:
        raise ValueError(errors[0]["error"])
    return {
        "as_of": day,
        "window": window_key,
        "window_label": label,
        "rows": rows,
        "errors": errors,
        "note": _NOTE,
    }
