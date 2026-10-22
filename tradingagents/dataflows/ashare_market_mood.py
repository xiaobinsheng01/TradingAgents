"""全市场大盘 + 情绪规则（涨停生态、溢价、容错 regime）。

与单票 playbook / 趋势规则合并：无显著个股利多/利空时，全市场情绪权重更高。
研究评级 only，不是委托。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .ashare_playbook import MIN_ZT_PREMIUM_FOR_BUY

_BIAS_ORDER = {"SELL": 0, "HOLD": 1, "BUY": 2}
_BIAS_ZH = {"BUY": "偏多", "HOLD": "观望", "SELL": "偏空"}

STALE_CALENDAR_DAYS = 12
RANGE_WINDOW = 60
STRETCH_RET_20D = 8.0
WEAK_RET_20D = -8.0
SWING_UP_RET_20D = 3.0
SWING_DOWN_RET_20D = -3.0
RANGE_HIGH = 80.0
RANGE_LOW = 25.0

# Breadth spread thresholds for sentiment-led mood when index day is flat.
SENTIMENT_BUY_SPREAD = 25
SENTIMENT_SELL_SPREAD = -15
SENTIMENT_FLAT_RET_1D_FLOOR = -0.8


def has_material_stock_news(events: dict[str, Any] | None) -> bool:
    """True when warehouse flags explicit good/bad filing keywords for the ticker."""
    if not events:
        return False
    return bool(events.get("announce_bad") or events.get("announce_good"))


def _calendar_gap(last_date: str | None, as_of: str) -> int | None:
    if not last_date:
        return None
    try:
        last = datetime.strptime(last_date, "%Y-%m-%d")
        day = datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError:
        return None
    return (day - last).days


def index_close_range_position(rows: list[dict]) -> float | None:
    """Last close vs recent high-low on index daily rows (0–100)."""
    window = [row for row in rows if row.get("high") is not None and row.get("low") is not None]
    window = window[-RANGE_WINDOW:]
    if not window or window[-1].get("close") is None:
        return None
    high = max(float(row["high"]) for row in window)
    low = min(float(row["low"]) for row in window)
    span = high - low
    if span <= 0:
        return None
    return round((float(window[-1]["close"]) - low) / span * 100.0, 2)


def build_market_bias(
    *,
    as_of: str,
    last_date: str | None,
    regime: str,
    ret_1d: float | None,
    ret_20d: float | None,
    range_pos: float | None,
    limit_up_count: int | None,
    limit_down_count: int | None,
) -> dict[str, Any]:
    """Next-session and 5–20 day **market-wide** research bias."""
    t1_bias, t1_reason = _market_t1_bias(
        as_of=as_of,
        last_date=last_date,
        regime=regime,
        ret_1d=ret_1d,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
    )
    swing_bias, swing_reason = _market_swing_bias(
        as_of=as_of,
        last_date=last_date,
        regime=regime,
        ret_20d=ret_20d,
        range_pos=range_pos,
    )
    return {
        "t1_bias": t1_bias,
        "t1_label": _BIAS_ZH[t1_bias],
        "t1_reason": t1_reason,
        "swing_bias": swing_bias,
        "swing_label": _BIAS_ZH[swing_bias],
        "swing_reason": swing_reason,
    }


def _market_t1_bias(
    *,
    as_of: str,
    last_date: str | None,
    regime: str,
    ret_1d: float | None,
    limit_up_count: int | None,
    limit_down_count: int | None,
) -> tuple[str, str]:
    if ret_1d is None or last_date is None:
        return "HOLD", "当日涨跌不可用，不给次日方向"
    gap = _calendar_gap(last_date, as_of)
    if gap is None or gap < 0 or gap > STALE_CALENDAR_DAYS:
        return "HOLD", f"日线停在 {last_date}，不外推次日方向"
    counts_known = limit_up_count is not None and limit_down_count is not None
    if (
        regime == "high"
        and ret_1d > 0
        and counts_known
        and limit_up_count > limit_down_count
    ):
        return "BUY", "高容错，指数收涨，涨停多于跌停"
    if (
        regime == "low"
        and ret_1d < 0
        and counts_known
        and limit_down_count >= limit_up_count
    ):
        return "SELL", "低容错，指数收跌，跌停不少于涨停"
    if not counts_known:
        return "HOLD", "涨跌停家数不可用，只记录指数涨跌，不给方向"
    return "HOLD", "容错和涨跌没有同时偏向一侧"


def _market_swing_bias(
    *,
    as_of: str,
    last_date: str | None,
    regime: str,
    ret_20d: float | None,
    range_pos: float | None,
) -> tuple[str, str]:
    if ret_20d is None or last_date is None:
        return "HOLD", "20日涨跌不可用，不给5–20日方向"
    gap = _calendar_gap(last_date, as_of)
    if gap is None or gap < 0 or gap > STALE_CALENDAR_DAYS:
        return "HOLD", f"日线停在 {last_date}，不外推5–20日方向"
    if ret_20d >= STRETCH_RET_20D and range_pos is not None and range_pos >= RANGE_HIGH:
        return "HOLD", "近20日涨幅已高，收盘靠近区间上沿，不追"
    if ret_20d <= WEAK_RET_20D and regime == "low":
        return "SELL", "近20日回撤，容错低"
    if (
        ret_20d <= WEAK_RET_20D
        and regime in {"high", "neutral"}
        and range_pos is not None
        and range_pos <= RANGE_LOW
    ):
        return "BUY", "近20日回撤到区间下沿，容错不是低"
    if ret_20d >= SWING_UP_RET_20D and regime == "high" and (
        range_pos is None or range_pos < RANGE_HIGH
    ):
        return "BUY", "近20日上行，容错高"
    if ret_20d <= SWING_DOWN_RET_20D and regime == "low":
        return "SELL", "近20日走弱，容错低"
    return "HOLD", "20日涨跌和容错没有形成单边"


def enhance_mood_t1_with_sentiment(
    base_bias: str,
    base_reason: str,
    *,
    regime: str,
    ret_1d: float | None,
    limit_up_count: int | None,
    limit_down_count: int | None,
    prev_zt_premium: float | None,
) -> tuple[str, str]:
    """When index rules stay HOLD, allow breadth/premium to set mood (情绪主导)."""
    if base_bias != "HOLD":
        return base_bias, base_reason
    if limit_up_count is None or limit_down_count is None:
        return base_bias, base_reason
    spread = limit_up_count - limit_down_count
    premium_ok = (
        prev_zt_premium is not None and prev_zt_premium >= MIN_ZT_PREMIUM_FOR_BUY
    )
    if (
        regime in {"high", "neutral"}
        and spread >= SENTIMENT_BUY_SPREAD
        and premium_ok
        and (ret_1d is None or ret_1d >= SENTIMENT_FLAT_RET_1D_FLOOR)
    ):
        return "BUY", "涨停显著多于跌停且昨日溢价尚可，全市场情绪主导"
    if regime in {"low", "neutral"} and spread <= SENTIMENT_SELL_SPREAD:
        if prev_zt_premium is None or prev_zt_premium < MIN_ZT_PREMIUM_FOR_BUY:
            return "SELL", "跌停显著多于涨停且溢价偏弱，全市场情绪主导"
    if regime == "low" and spread <= -10 and limit_down_count >= 20:
        return "SELL", "低容错且跌停家数偏多，全市场情绪偏空"
    return base_bias, base_reason


def resolve_market_mood(
    *,
    as_of: str,
    hs300_rows: list[dict],
    regime: str,
    limit_up_count: int | None,
    limit_down_count: int | None,
    prev_zt_premium: float | None,
    index_ret_1d: float | None = None,
    index_ret_20d: float | None = None,
) -> dict[str, Any]:
    """Build enhanced market mood from HS300 bars and breadth inputs."""
    from .akshare_market import _index_ret

    if not hs300_rows:
        return {
            "regime": regime,
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
            "prev_zt_premium": prev_zt_premium,
            "hs300_ret_1d": index_ret_1d,
            "hs300_ret_20d": index_ret_20d,
            "mood_t1": "HOLD",
            "mood_t1_reason": "沪深300无日线，不给全市场方向",
            "mood_swing": "HOLD",
            "mood_swing_reason": "沪深300无日线，不给5–20日全市场方向",
        }
    last_date = hs300_rows[-1].get("date") if hs300_rows else None
    ret_1d = index_ret_1d if index_ret_1d is not None else _index_ret(hs300_rows, as_of, 1)
    ret_20d = index_ret_20d if index_ret_20d is not None else _index_ret(hs300_rows, as_of, 20)
    range_pos = index_close_range_position(hs300_rows)
    base = build_market_bias(
        as_of=as_of,
        last_date=last_date,
        regime=regime,
        ret_1d=ret_1d,
        ret_20d=ret_20d,
        range_pos=range_pos,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
    )
    mood_t1, mood_t1_reason = enhance_mood_t1_with_sentiment(
        base["t1_bias"],
        base["t1_reason"],
        regime=regime,
        ret_1d=ret_1d,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        prev_zt_premium=prev_zt_premium,
    )
    return {
        "regime": regime,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "prev_zt_premium": prev_zt_premium,
        "hs300_ret_1d": ret_1d,
        "hs300_ret_20d": ret_20d,
        "mood_t1": mood_t1,
        "mood_t1_reason": mood_t1_reason,
        "mood_swing": base["swing_bias"],
        "mood_swing_reason": base["swing_reason"],
    }


def blend_stock_with_market_mood(
    stock_bias: str,
    mood_bias: str,
    *,
    material_news: bool,
    stock_reason: str,
    mood_reason: str,
) -> tuple[str, str]:
    """Merge single-name bias with market mood; mood leads when no material news."""
    stock = stock_bias.upper()
    mood = mood_bias.upper()
    if material_news:
        if mood == "SELL" and stock == "BUY":
            return "HOLD", f"{stock_reason}；全市场偏空（{mood_reason}），有资讯时不激进做多"
        return stock, stock_reason
    if stock == "HOLD":
        return mood, f"无显著个股利多/利空，跟随全市场与大盘情绪：{mood_reason}"
    if stock == "BUY" and mood == "SELL":
        return "HOLD", f"无个股资讯驱动，全市场情绪偏空：{mood_reason}"
    if stock == "SELL" and mood == "BUY":
        return "HOLD", f"无个股资讯驱动，全市场情绪偏强：{mood_reason}"
    if stock == mood:
        return stock, f"{stock_reason}；与全市场情绪一致：{mood_reason}"
    return stock, stock_reason


def merge_bias_conservative(a: str, b: str) -> str:
    """More bearish of two BUY/HOLD/SELL labels."""
    return min(a.upper(), b.upper(), key=lambda item: _BIAS_ORDER[item])


def load_market_mood_snapshot(as_of: str) -> dict[str, Any]:
    """Fetch breadth/regime once per as-of (cached by callers via ``news_store``)."""
    from datetime import timedelta

    from .akshare_market import (
        _cached,
        _fetch_dt_pool,
        _fetch_index_daily,
        _fetch_prev_zt,
        _fetch_zt_pool,
        _index_ret,
        _last_amount,
        _mean_float,
    )
    from .akshare_news import _load_akshare
    from .ashare_playbook import combine_market_amount, resolve_regime
    from .news_store import GLOBAL_KEY

    ak = _load_akshare()
    start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=280)).strftime("%Y-%m-%d")
    hs300 = _cached(
        GLOBAL_KEY,
        as_of,
        "mood_idx_hs300",
        lambda: _fetch_index_daily(ak, as_of, start, "sh000300"),
    )
    sse = _cached(
        GLOBAL_KEY,
        as_of,
        "mood_idx_sse",
        lambda: _fetch_index_daily(ak, as_of, start, "sh000001"),
    )
    sza = _cached(
        GLOBAL_KEY,
        as_of,
        "mood_idx_sza",
        lambda: _fetch_index_daily(ak, as_of, start, "sz399107"),
    )
    bank = _cached(
        GLOBAL_KEY,
        as_of,
        "mood_idx_bank",
        lambda: _fetch_index_daily(ak, as_of, start, "sz399986"),
    )
    zt = _cached(GLOBAL_KEY, as_of, "mood_zt", lambda: _fetch_zt_pool(ak, as_of))
    dt = _cached(GLOBAL_KEY, as_of, "mood_dt", lambda: _fetch_dt_pool(ak, as_of))
    prev = _cached(GLOBAL_KEY, as_of, "mood_prev_zt", lambda: _fetch_prev_zt(ak, as_of))
    premium = _mean_float(prev, ("涨跌幅", "溢价", "昨收溢价"))
    amount = combine_market_amount(_last_amount(sse), _last_amount(sza))
    regime = resolve_regime(
        market_amount_yuan=amount,
        prev_zt_premium=premium,
        limit_up_count=len(zt),
        limit_down_count=len(dt),
        bank_ret_1d=_index_ret(bank, as_of, 1),
        hs300_ret_1d=_index_ret(hs300, as_of, 1),
    )
    return resolve_market_mood(
        as_of=as_of,
        hs300_rows=hs300,
        regime=regime,
        limit_up_count=len(zt),
        limit_down_count=len(dt),
        prev_zt_premium=premium,
    )
