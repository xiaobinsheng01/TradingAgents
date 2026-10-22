"""Deterministic swing-window trend bias (价量 + 缠论 + 指数/行业 regime).

Shared by ``ashare_trend_predict`` and ``get_ashare_swing_tape`` so the web
console and LangGraph tape use the same rules. Research only — not an order.
"""

from __future__ import annotations

# Index regime: avoid mean-reversion BUY in broad bear tapes.
HS300_BEAR_RET_20D = -3.0
HS300_BEAR_RET_WINDOW = -5.0
INDUSTRY_WEAK_RET_5D = -4.0


def close_range_position(rows: list[dict]) -> float | None:
    """Where the last close sits in the recent high-low range, 0–100."""
    window = [row for row in rows if row.get("high") is not None and row.get("low") is not None]
    if not window or window[-1].get("close") is None:
        return None
    high = max(float(row["high"]) for row in window)
    low = min(float(row["low"]) for row in window)
    span = high - low
    if span <= 0:
        return None
    return round((float(window[-1]["close"]) - low) / span * 100.0, 2)


def index_bear_regime(
    hs300_ret_20d: float | None,
    hs300_ret_window: float | None,
) -> bool:
    """True when the benchmark looks bearish on 20d or the swing window."""
    if hs300_ret_20d is not None and hs300_ret_20d <= HS300_BEAR_RET_20D:
        return True
    if hs300_ret_window is not None and hs300_ret_window <= HS300_BEAR_RET_WINDOW:
        return True
    return False


def compute_trend_bias(
    *,
    ret_window: float | None,
    ret_5: float | None,
    ret_10: float | None,
    range_pos: float | None,
    vs_index: float | None,
    chan_buy_sell: str | None,
    chan_segment: str | None,
    hs300_ret_20d: float | None = None,
    hs300_ret_window: float | None = None,
    industry_ret_5: float | None = None,
) -> tuple[str, str]:
    """Return ``(BUY|HOLD|SELL, reason)`` for subsequent-session research."""
    if ret_window is None:
        return "HOLD", "窗口涨跌不可用，不给方向"
    if chan_buy_sell == "三类卖点候选":
        return "SELL", "缠论三类卖点候选，偏后续走弱"
    if ret_window >= 12.0 and range_pos is not None and range_pos >= 80.0:
        return "HOLD", "窗口涨幅已高且靠近区间上沿，不追"
    if chan_buy_sell == "三类买点候选":
        if range_pos is not None and range_pos >= 85.0:
            return "HOLD", "缠论买点但收盘靠近区间上沿，不追"
        if vs_index is not None and vs_index < -4.0:
            return "HOLD", "缠论买点但明显弱于沪深300"
        if ret_5 is not None and ret_5 < -6.0:
            return "HOLD", "缠论买点但近5日仍大幅回撤"
        if index_bear_regime(hs300_ret_20d, hs300_ret_window):
            return "HOLD", "指数偏空环境，缠论买点不单独做多"
        if chan_segment == "down":
            return "HOLD", "下行段，缠论买点不单独做多"
        return "BUY", "缠论三类买点候选，价量窗口配合"
    if ret_window <= -15.0 and range_pos is not None and range_pos <= 25.0:
        if index_bear_regime(hs300_ret_20d, hs300_ret_window):
            return "HOLD", "指数偏空环境，不做下沿反弹"
        if chan_segment == "down":
            return "HOLD", "下行段，不做下沿反弹"
        if ret_5 is not None and ret_5 < -3.0 and ret_10 is not None and ret_10 < -5.0:
            return "SELL", "近5/10日持续走弱，下沿反弹信号不足"
        if (
            industry_ret_5 is not None
            and industry_ret_5 <= INDUSTRY_WEAK_RET_5D
            and ret_5 is not None
            and ret_5 < 0
        ):
            return "HOLD", "行业近5日走弱且个股仍跌，不做下沿反弹"
        if chan_segment == "down" and vs_index is not None and vs_index <= -5.0:
            return "HOLD", "下行段且弱于指数，反弹信号不足"
        return "BUY", "窗口回撤大且靠近区间下沿，偏反弹研究"
    if vs_index is not None and vs_index <= -8.0 and ret_5 is not None and ret_5 < 0:
        return "SELL", "窗口弱于沪深300且近5日仍走弱"
    if (
        vs_index is not None
        and vs_index >= 5.0
        and ret_10 is not None
        and ret_10 > 0
        and (range_pos is None or range_pos < 90.0)
    ):
        if ret_5 is not None and ret_5 < 0:
            return "HOLD", "相对指数强但近5日仍跌，不做多"
        if ret_10 is not None and ret_10 < 0:
            return "HOLD", "相对指数强但近10日仍跌，不做多"
        return "BUY", "窗口强于沪深300且近10日仍上行"
    if ret_5 is not None and ret_10 is not None and ret_5 < -5.0 and ret_10 < -8.0:
        return "SELL", "近5日与近10日同步走弱"
    if (
        chan_segment == "down"
        and ret_5 is not None
        and ret_10 is not None
        and ret_5 < -3.0
        and ret_10 < -5.0
    ):
        return "SELL", "下行段且近5/10日仍跌"
    return "HOLD", "价量与相对强弱没有形成单边"
