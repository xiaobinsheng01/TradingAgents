"""Deterministic A-share T+1 stance from the short-horizon tape.

The rules follow a short-term limit-up playbook: trade turnover boards only
when the cash market is thick enough to pay a next-session premium, and
decline a directional call otherwise. This is a research rating for the
scored T+1 window. It is not a broker order and not an intraday scalp.
"""

from __future__ import annotations

import re
from typing import Any

PLAYBOOK_HEADING = "## Playbook stance (T+1)"

# Two-market turnover in yuan. About 1.3 trillion is a high-tolerance tape;
# about 1.0–1.1 trillion is thin and first boards have not been paying a premium.
HIGH_AMOUNT_YUAN = 1.3e12
LOW_AMOUNT_YUAN = 1.1e12
# Below this the print is not a two-market total (wrong unit or one side missing).
MIN_RELIABLE_AMOUNT_YUAN = 1.0e10
ONE_WORD_AMPLITUDE = 1.0
WATCH_ZONE_LOW = 7.0
# Yesterday limit-up premium must be known and positive before a directional BUY.
MIN_ZT_PREMIUM_FOR_BUY = 0.3
# Third-board continuations need a stronger paid premium.
HIGH_STREAK_MIN_PREMIUM = 1.0
# Broad market headwind: skip next-session long continuation calls.
HS300_HEADWIND_PCT = -1.0
# Too few limit-ups means emotion is thin even if turnover looks ok.
MIN_LIMIT_UP_FOR_BUY = 15

_PLAYBOOK_SECTION_RE = re.compile(
    re.escape(PLAYBOOK_HEADING) + r".*?(?=\n## |\Z)",
    re.DOTALL,
)


def combine_market_amount(
    sse_amount: float | None,
    sz_amount: float | None,
) -> float | None:
    """Shanghai composite plus Shenzhen A-share index amount, in yuan.

    Either side missing, or a total too small to be a two-market print, is
    ``None`` so the regime does not treat a partial sum as a thin tape.
    """
    if sse_amount is None or sz_amount is None:
        return None
    total = sse_amount + sz_amount
    if total < MIN_RELIABLE_AMOUNT_YUAN:
        return None
    return total


def _amplitude(row: dict[str, Any]) -> float | None:
    amp = row.get("amplitude")
    if amp is not None:
        return float(amp)
    high, low, pre = row.get("high"), row.get("low"), row.get("preclose")
    if high is None or low is None or pre in (None, 0):
        return None
    return (float(high) - float(low)) / float(pre) * 100.0


def _open_pct(row: dict[str, Any]) -> float | None:
    open_, pre = row.get("open"), row.get("preclose")
    if open_ is None or pre in (None, 0):
        return None
    return (float(open_) / float(pre) - 1.0) * 100.0


def classify_board_shape(row: dict[str, Any]) -> str:
    """``one_word`` / ``t_board`` / ``turnover_board`` / ``failed_board`` / ``none``."""
    limit_up = bool(row.get("limit_up"))
    touched = bool(row.get("touched_limit_up"))
    limit_pct = float(row.get("limit_pct") or 10.0)
    amp = _amplitude(row)
    opened_at_limit = (_open_pct(row) or -999.0) >= limit_pct - 0.5
    if limit_up and amp is not None and amp <= ONE_WORD_AMPLITUDE:
        return "one_word"
    if limit_up and opened_at_limit:
        return "t_board"
    if limit_up:
        return "turnover_board"
    if touched:
        return "failed_board"
    return "none"


def consecutive_limit_ups(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in reversed(rows):
        if not row.get("limit_up"):
            break
        count += 1
    return count


def prior_limit_ups(rows: list[dict[str, Any]]) -> int:
    if len(rows) < 2:
        return 0
    return sum(1 for row in rows[:-1] if row.get("limit_up"))


def resolve_regime(
    *,
    market_amount_yuan: float | None,
    prev_zt_premium: float | None,
    limit_up_count: int | None,
    limit_down_count: int | None,
    bank_ret_1d: float | None,
    hs300_ret_1d: float | None,
) -> str:
    """``high`` / ``neutral`` / ``low`` / ``unknown`` tolerance for next-day premium."""
    reliable = (
        market_amount_yuan is not None and market_amount_yuan >= MIN_RELIABLE_AMOUNT_YUAN
    )
    if reliable and market_amount_yuan >= HIGH_AMOUNT_YUAN:
        regime = "high"
    elif reliable and market_amount_yuan < LOW_AMOUNT_YUAN:
        regime = "low"
    elif reliable:
        regime = "neutral"
    elif prev_zt_premium is not None and prev_zt_premium > 0 and (limit_up_count or 0) > (
        limit_down_count or 0
    ):
        regime = "high"
    elif prev_zt_premium is not None and prev_zt_premium <= 0:
        regime = "low"
    else:
        regime = "unknown"

    if regime == "high" and prev_zt_premium is not None and prev_zt_premium <= 0:
        regime = "neutral"
    if (
        limit_up_count is not None
        and limit_down_count is not None
        and limit_down_count > limit_up_count
    ):
        if regime == "high":
            regime = "neutral"
        elif regime in {"neutral", "unknown"}:
            regime = "low"
    bank_leading = (
        bank_ret_1d is not None
        and hs300_ret_1d is not None
        and bank_ret_1d > 0
        and bank_ret_1d > hs300_ret_1d + 0.5
        and (not reliable or market_amount_yuan < HIGH_AMOUNT_YUAN)
    )
    if bank_leading and regime != "low":
        regime = "low"
    return regime


def build_playbook_stance(
    *,
    daily_rows: list[dict[str, Any]],
    as_of: str,
    market_amount_yuan: float | None,
    prev_zt_premium: float | None,
    limit_up_count: int | None,
    limit_down_count: int | None,
    bank_ret_1d: float | None,
    hs300_ret_1d: float | None,
    announce_bad: bool,
    is_st_or_loss: bool,
    lift_ban_mv_5d: float | None,
    live_pct: float | None,
    lhb_net_buy: float | None = None,
) -> dict[str, Any]:
    """T+1 research bias for the as-of session. Missing inputs stay explicit."""
    regime = resolve_regime(
        market_amount_yuan=market_amount_yuan,
        prev_zt_premium=prev_zt_premium,
        limit_up_count=limit_up_count,
        limit_down_count=limit_down_count,
        bank_ret_1d=bank_ret_1d,
        hs300_ret_1d=hs300_ret_1d,
    )
    last = daily_rows[-1] if daily_rows else {}
    shape = classify_board_shape(last) if last else "none"
    streak = consecutive_limit_ups(daily_rows)
    prior = prior_limit_ups(daily_rows)
    bar_is_as_of = bool(last.get("date") == as_of)
    limit_pct = float(last.get("limit_pct") or 10.0)
    sealed = bool(last.get("limit_up"))
    in_watch = (
        live_pct is not None
        and not sealed
        and WATCH_ZONE_LOW <= float(live_pct) < limit_pct - 0.5
    )
    bias, reason = _t1_bias(
        regime=regime,
        shape=shape,
        streak=streak,
        prior=prior,
        prev_zt_premium=prev_zt_premium,
        limit_up_count=limit_up_count,
        hs300_ret_1d=hs300_ret_1d,
        bar_is_as_of=bar_is_as_of,
        in_watch=in_watch,
        announce_bad=announce_bad,
        is_st_or_loss=is_st_or_loss,
        lift_ban_mv_5d=lift_ban_mv_5d,
        lhb_net_buy=lhb_net_buy,
    )
    return {
        "regime": regime,
        "market_amount_yuan": market_amount_yuan,
        "market_amount_source": (
            "sh000001+sz399107" if market_amount_yuan is not None else None
        ),
        "bank_index_ret_1d": bank_ret_1d,
        "board_shape": shape,
        "consecutive_limit_ups": streak,
        "prior_limit_ups": prior,
        "prev_zt_premium": prev_zt_premium,
        "bar_is_as_of": bar_is_as_of,
        "t1_bias": bias,
        "t1_reason": reason,
        "note": (
            "research rating for the next session only; not a broker order; "
            "not a 10-minute scalp; sector rank is not scanned"
        ),
    }


def _t1_bias(
    *,
    regime: str,
    shape: str,
    streak: int,
    prior: int,
    prev_zt_premium: float | None,
    limit_up_count: int | None,
    hs300_ret_1d: float | None,
    bar_is_as_of: bool,
    in_watch: bool,
    announce_bad: bool,
    is_st_or_loss: bool,
    lift_ban_mv_5d: float | None,
    lhb_net_buy: float | None,
) -> tuple[str, str]:
    if not bar_is_as_of:
        return (
            "HOLD",
            "closed bar is before as-of; the prior board is not a fresh next-session setup",
        )
    if in_watch:
        return (
            "HOLD",
            "live print is in the 7% watch zone and the limit is not sealed",
        )
    if shape in {"one_word", "t_board"}:
        return (
            "HOLD",
            "one-word or T board: unbuyable, or the next-session gap fails often",
        )
    if shape == "failed_board":
        return (
            "HOLD",
            "limit was touched and not kept; do not assume a next-session premium",
        )
    if hs300_ret_1d is not None and hs300_ret_1d <= HS300_HEADWIND_PCT:
        return (
            "HOLD",
            "沪深300当日走弱，连板次日溢价成功率下降",
        )
    if limit_up_count is not None and limit_up_count < MIN_LIMIT_UP_FOR_BUY:
        return (
            "HOLD",
            "涨停家数偏少，情绪不够厚，不给次日方向",
        )
    if prev_zt_premium is None:
        return (
            "HOLD",
            "昨日涨停溢价不可用，无法确认次日溢价环境",
        )
    if prev_zt_premium < MIN_ZT_PREMIUM_FOR_BUY:
        return (
            "HOLD",
            "昨日涨停溢价偏弱，换手板次日溢价不可靠",
        )
    premium_ok = prev_zt_premium >= MIN_ZT_PREMIUM_FOR_BUY
    if streak >= 3 and prev_zt_premium < HIGH_STREAK_MIN_PREMIUM:
        return (
            "HOLD",
            "三板及以上需要更高的昨日涨停溢价才给方向",
        )
    if streak >= 2 and lhb_net_buy is not None and lhb_net_buy < 0:
        return (
            "HOLD",
            "连板票龙虎机构净卖，次日溢价不可靠",
        )
    turnover_continuation = (
        shape == "turnover_board" and regime == "high" and premium_ok and 1 <= streak <= 3
    )
    first_board_with_history = turnover_continuation and streak == 1 and prior >= 1
    later_board = turnover_continuation and streak >= 2
    if first_board_with_history or later_board:
        if announce_bad or is_st_or_loss or (lift_ban_mv_5d or 0) > 0:
            return (
                "HOLD",
                "turnover board in a high-tolerance tape, vetoed by a bad filing, ST/loss, or a 5-day unlock",
            )
        if streak == 1:
            return (
                "BUY",
                "high-tolerance tape, turnover first board, and the name has prior limit-ups",
            )
        return (
            "BUY",
            "high-tolerance tape and a turnover continuation within three boards",
        )
    if shape == "turnover_board" and streak == 1 and regime == "high" and prior < 1:
        return (
            "HOLD",
            "turnover first board but no prior limit-up history; premium is less reliable",
        )
    if regime != "high":
        return (
            "HOLD",
            "tape is not high-tolerance; first-board premium is unreliable and this path does not rank emotion leaders",
        )
    return (
        "HOLD",
        "no turnover-board setup inside three boards on a high-tolerance tape",
    )


def extract_playbook_section(text: str) -> str:
    """Return the playbook block from a tool transcript, or ``\"\"``."""
    match = _PLAYBOOK_SECTION_RE.search(text or "")
    if not match:
        return ""
    return match.group(0).strip()
