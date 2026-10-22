"""Same-day A-share index outlook for the local console.

Reads the public daily bars of the major indexes, reuses the cash-market
regime from the T+1 playbook, and attaches 缠论 structure already computed
from those bars. The result is a research rating for the next session and
about 5–20 trading days. It is not a broker order, not a LangGraph run, and
not a quote API. Historical dates are refused so today's print cannot be
labeled as an older session.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from .akshare_market import (
    _breadth_from_spot,
    _cached,
    _fetch_dt_pool,
    _fetch_index_daily,
    _fetch_prev_zt,
    _fetch_zt_pool,
    _index_ret,
    _last_amount,
    _mean_float,
    _try_ak_records,
)
from .akshare_news import _load_akshare
from .ashare_market_mood import (
    build_market_bias,
    index_close_range_position,
    resolve_market_mood,
)
from .ashare_playbook import combine_market_amount, resolve_regime
from .ashare_screen import bars_from_daily
from .chanlun import ChanlunSnapshot, analyze_chanlun
from .config import get_config
from .news_store import GLOBAL_KEY

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 280
STALE_CALENDAR_DAYS = 12
RANGE_WINDOW = 60
STRETCH_RET_20D = 8.0
WEAK_RET_20D = -8.0
SWING_UP_RET_20D = 3.0
SWING_DOWN_RET_20D = -3.0
RANGE_HIGH = 80.0
RANGE_LOW = 25.0

BENCHMARK_SYMBOL = "sh000300"
_SSE_AMOUNT_SYMBOL = "sh000001"
_SZA_AMOUNT_SYMBOL = "sz399107"
_BANK_SYMBOL = "sz399986"

_BIAS_ZH = {"BUY": "偏多", "HOLD": "观望", "SELL": "偏空"}
_REGIME_ZH = {
    "high": "高容错",
    "neutral": "中性",
    "low": "低容错",
    "unknown": "容错未知",
}
_SEGMENT_ZH = {"up": "上行段", "down": "下行段"}
_POSITION_ZH = {
    "above_hub": "中枢上方",
    "below_hub": "中枢下方",
    "in_hub": "中枢内",
    "no_hub": "无中枢",
}
_CACHE_CHANNEL = {
    "sh000001": "idx_sse",
    "sh000300": "idx_hs300",
    "sz399006": "idx_cyb",
    "sz399107": "idx_sza",
    "sz399986": "idx_bank",
}


class IndexSpec(NamedTuple):
    symbol: str
    name: str


DISPLAY_INDEXES: tuple[IndexSpec, ...] = (
    IndexSpec("sh000001", "上证指数"),
    IndexSpec("sz399001", "深证成指"),
    IndexSpec("sz399006", "创业板指"),
    IndexSpec("sh000300", "沪深300"),
    IndexSpec("sh000016", "上证50"),
    IndexSpec("sh000905", "中证500"),
    IndexSpec("sh000688", "科创50"),
)
_FETCH_SYMBOLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [item.symbol for item in DISPLAY_INDEXES] + [_SZA_AMOUNT_SYMBOL, _BANK_SYMBOL]
    )
)
_DISPLAY_BY_SYMBOL = {item.symbol: item for item in DISPLAY_INDEXES}

_NOTE = (
    "研究评级，只覆盖下一交易日和约 5–20 个交易日。"
    "缠论只描述已有日线里的分型、笔、段和中枢；没有结构就不写买卖点。"
    "不自动跑全图，也永不下单。"
)


class IndexOutlookNotLiveError(ValueError):
    """Index outlook uses today's public print only."""


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _coerce_day(as_of: str | None) -> str:
    if as_of is None or not str(as_of).strip():
        return _utc_today()
    text = str(as_of).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("as_of must be YYYY-MM-DD") from e
    return text


def _require_today(day: str) -> None:
    if day != _utc_today():
        raise IndexOutlookNotLiveError(
            "大盘走势只在当天可用。历史日期不能把此刻的指数当成过去某一天的预测。"
        )


def _ttl_seconds() -> int:
    ttl = get_config().get("news_telegraph_ttl_seconds", 120)
    try:
        return int(ttl) if ttl is not None else 120
    except (TypeError, ValueError):
        return 120


def normalize_index_symbol(symbol: str) -> str:
    """Return a whitelisted AKShare index symbol, or raise ``ValueError``."""
    text = str(symbol or "").strip().lower()
    if text not in _DISPLAY_BY_SYMBOL:
        raise ValueError("symbol 必须是走势页里的指数代码")
    return text


def _calendar_gap(last_date: str | None, as_of: str) -> int | None:
    if not last_date:
        return None
    try:
        last = datetime.strptime(last_date, "%Y-%m-%d")
        day = datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError:
        return None
    return (day - last).days


def _usable(last_date: str | None, as_of: str) -> bool:
    gap = _calendar_gap(last_date, as_of)
    return gap is not None and 0 <= gap <= STALE_CALENDAR_DAYS


close_range_position = index_close_range_position


def _structure_text(snap: ChanlunSnapshot) -> str:
    if snap.buy_sell:
        return snap.buy_sell
    segment = snap.segments[-1].direction if snap.segments else None
    if segment is None:
        return "不成段"
    place = _POSITION_ZH.get(snap.position, "无中枢")
    return f"{_SEGMENT_ZH[segment]}，{place}"


def _structure(rows: list[dict]) -> dict[str, str | None]:
    if not rows:
        return {"segment": None, "hub_position": None, "structure": "没有日线"}
    snap = analyze_chanlun(rows)
    segment = snap.segments[-1].direction if snap.segments else None
    return {
        "segment": segment,
        "hub_position": snap.position,
        "structure": _structure_text(snap),
    }


def _load_index(ak: Any, as_of: str, start: str, symbol: str) -> list[dict]:
    channel = _CACHE_CHANNEL.get(symbol, f"idx_{symbol}")
    try:
        rows = _cached(
            GLOBAL_KEY,
            as_of,
            channel,
            lambda: _fetch_index_daily(ak, as_of, start, symbol),
        )
    except TimeoutError as e:
        logger.warning("A-share index %s timed out as of %s: %s", symbol, as_of, e)
        return []
    if not rows:
        level = logging.WARNING if symbol == BENCHMARK_SYMBOL else logging.INFO
        logger.log(level, "A-share index %s has no daily bars as of %s", symbol, as_of)
    return rows


def _breadth(ak: Any, as_of: str) -> tuple[int | None, int | None, str]:
    zt = _cached(GLOBAL_KEY, as_of, "zt_pool", lambda: _fetch_zt_pool(ak, as_of))
    dt = _cached(GLOBAL_KEY, as_of, "dt_pool", lambda: _fetch_dt_pool(ak, as_of))
    if zt or dt:
        return len(zt), len(dt), "east_money_zt_pool"
    sina = _cached(
        GLOBAL_KEY,
        as_of,
        "sina_spot",
        lambda: _try_ak_records(ak, ("stock_zh_a_spot",), ({},)),
        ttl_seconds=_ttl_seconds(),
    )
    if sina:
        up, down = _breadth_from_spot(sina)
        return up, down, "sina_spot_live_approx"
    return None, None, "unavailable"


def _index_row(
    spec: IndexSpec,
    rows: list[dict],
    *,
    as_of: str,
    regime: str,
    limit_up_count: int | None,
    limit_down_count: int | None,
) -> dict[str, Any]:
    last = rows[-1] if rows else {}
    last_date = last.get("date")
    ret_1d = _index_ret(rows, as_of, 1)
    ret_5d = _index_ret(rows, as_of, 5)
    ret_20d = _index_ret(rows, as_of, 20)
    range_pos = close_range_position(rows) if _usable(last_date, as_of) else None
    bias = build_market_bias(
        as_of=as_of,
        last_date=last_date,
        regime=regime,
        ret_1d=ret_1d,
        ret_20d=ret_20d,
        range_pos=range_pos,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
    )
    formed = _structure(rows)
    return {
        "symbol": spec.symbol,
        "name": spec.name,
        "last_date": last_date,
        "close": last.get("close"),
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "amount": _last_amount(rows),
        "range_pos": range_pos,
        **formed,
        **bias,
        "t1_label": _BIAS_ZH[bias["t1_bias"]],
        "swing_label": _BIAS_ZH[bias["swing_bias"]],
    }


def index_outlook(as_of: str | None = None) -> dict[str, Any]:
    """Same-day major-index research snapshot. Not an order."""
    day = _coerce_day(as_of)
    _require_today(day)
    ak = _load_akshare()
    start = (
        datetime.strptime(day, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")
    series = {symbol: _load_index(ak, day, start, symbol) for symbol in _FETCH_SYMBOLS}
    limit_up, limit_down, breadth_source = _breadth(ak, day)
    prev = _cached(GLOBAL_KEY, day, "prev_zt", lambda: _fetch_prev_zt(ak, day))
    premium = _mean_float(prev, ("涨跌幅", "溢价", "昨收溢价"))
    amount = combine_market_amount(
        _last_amount(series.get(_SSE_AMOUNT_SYMBOL) or []),
        _last_amount(series.get(_SZA_AMOUNT_SYMBOL) or []),
    )
    hs300 = series.get(BENCHMARK_SYMBOL) or []
    regime = resolve_regime(
        market_amount_yuan=amount,
        prev_zt_premium=premium,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        bank_ret_1d=_index_ret(series.get(_BANK_SYMBOL) or [], day, 1),
        hs300_ret_1d=_index_ret(hs300, day, 1),
    )
    rows = [
        _index_row(
            spec,
            series.get(spec.symbol) or [],
            as_of=day,
            regime=regime,
            limit_up_count=limit_up,
            limit_down_count=limit_down,
        )
        for spec in DISPLAY_INDEXES
    ]
    benchmark = next((row for row in rows if row["symbol"] == BENCHMARK_SYMBOL), None)
    mood = resolve_market_mood(
        as_of=day,
        hs300_rows=hs300,
        regime=regime,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        prev_zt_premium=premium,
    )
    missing = [row["name"] for row in rows if row["close"] is None]
    if len(missing) == len(rows):
        extra = "指数日线没有返回。"
    elif missing:
        extra = "部分指数没有日线。"
    else:
        extra = ""
    headline = benchmark or {
        "last_date": None,
        "t1_bias": "HOLD",
        "t1_label": "观望",
        "t1_reason": "沪深300没有日线，不给方向",
        "swing_bias": "HOLD",
        "swing_label": "观望",
        "swing_reason": "沪深300没有日线，不给5–20日方向",
    }
    return {
        "as_of": day,
        "session_date": headline.get("last_date"),
        "benchmark": BENCHMARK_SYMBOL,
        "benchmark_name": "沪深300",
        "regime": regime,
        "regime_label": _REGIME_ZH.get(regime, "容错未知"),
        "market_amount_yuan": amount,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "breadth_source": breadth_source,
        "prev_zt_premium": premium,
        "market_mood_t1": mood["mood_t1"],
        "market_mood_swing": mood["mood_swing"],
        "t1_bias": mood["mood_t1"],
        "t1_label": _BIAS_ZH[mood["mood_t1"]],
        "t1_reason": mood["mood_t1_reason"],
        "swing_bias": mood["mood_swing"],
        "swing_label": _BIAS_ZH[mood["mood_swing"]],
        "swing_reason": mood["mood_swing_reason"],
        "rows": rows,
        "note": _NOTE + extra,
    }


def index_outlook_bars(symbol: str, as_of: str | None = None) -> dict[str, Any]:
    """Recent daily bars for one whitelisted index. Research chart, not an order."""
    day = _coerce_day(as_of)
    _require_today(day)
    code = normalize_index_symbol(symbol)
    ak = _load_akshare()
    start = (
        datetime.strptime(day, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")
    rows = _load_index(ak, day, start, code)
    return {
        "symbol": code,
        "name": _DISPLAY_BY_SYMBOL[code].name,
        "as_of": day,
        "bars": bars_from_daily(rows, day),
        "note": "日K用于观察指数，不是委托。",
    }
