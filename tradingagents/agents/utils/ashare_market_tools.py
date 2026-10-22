from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_ashare_short_horizon(
    ticker: Annotated[str, "China A-share ticker, e.g. 601061.SH, 600519.SS or 000001.SZ"],
    curr_date: Annotated[str, "As-of session date in yyyy-mm-dd format (the close you already know)"],
    look_back_days: Annotated[
        int | None,
        "Calendar lookback for daily bars; omit for the vendor default (~40 days)",
    ] = None,
) -> str:
    """
    A-share short-horizon tape for the NEXT tradable session (T+1) and 5–20
    trading days. Daily OHLCV with amount/turnover/limit flags, market breadth,
    lagged northbound, dragon-tiger, unlock calendar, warehouse event flags,
    and a static industry/commodity map (sector index vs the stock, at most two
    domestic futures plus mapped LME/COMEX/CBOT/NYMEX prints when the industry
    has a static row). Same-day runs also attach the latest public spot print. Not a PE/PB
    valuation snapshot and not an order ticket. Limit-up seals are unbuyable
    until they open. Includes a deterministic T+1 playbook stance (`t1_bias`)
    from two-market turnover, board shape, and prior limit-ups. Uses the
    configured ashare_tape vendor (akshare extra).
    """
    return route_to_vendor("get_ashare_short_horizon", ticker, curr_date, look_back_days)


@tool
def get_ashare_swing_tape(
    ticker: Annotated[str, "China A-share ticker, e.g. 601061.SH, 600519.SS or 000001.SZ"],
    curr_date: Annotated[str, "As-of session date in yyyy-mm-dd format"],
    window: Annotated[
        str,
        "half_month (~15 calendar days), three_months (~90), or half_year (~180)",
    ] = "half_month",
) -> str:
    """A-share swing tape: price, volume, 缠论, 机构出手, and window news.

    Windowed OHLCV stats (return, high/low, volume vs average, turnover, limit
    days), lagged northbound in the window, 缠论 分型/笔/线段/中枢 from ~250
    calendar days of closed bars (date<=as-of), disclosed 增减持 / 龙虎 / 大宗,
    and ticker/policy news in the same window. Input for subsequent-trend
    research. Not a PE snapshot and not an order ticket. Uses the configured
    ashare_tape vendor.
    """
    return route_to_vendor("get_ashare_swing_tape", ticker, curr_date, window)
