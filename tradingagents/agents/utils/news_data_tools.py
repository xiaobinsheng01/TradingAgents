from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol (company-specific).
    Uses the configured news_data vendor(s). For get_news, every successful
    vendor in the configured list is concatenated (A-share + overseas).
    A-share East Money related-feed rows whose title never mentions this
    code or company name are dropped; use get_global_news for market-wide wires.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve market-wide global/policy news that can affect China A-shares
    (domestic AKTools wires plus Serper Google Search for headlines and public
    X / YouTube / Meta snippets via site: queries). Do not treat this output as news about a single ticker;
    pair with get_news. Historical as-of dates do not hit the live Google index.
    Defaults for look_back_days and limit come from DEFAULT_CONFIG
    (global_news_lookback_days, global_news_article_limit); pass explicit
    values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[
        str | None,
        "As-of date in yyyy-mm-dd; omit to use today. A-share 增减持/龙虎/大宗 are point-in-time.",
    ] = None,
) -> str:
    """
    Retrieve disclosed buy/sell flow for a company.
    A-shares: 董监高/股东增减持, dragon-tiger buy/sell seats, and 大宗交易
    via AKTools, dated on or before curr_date. US listings use Yahoo/Alpha
    Vantage insider forms. Do not invent missing prints; this is not an order.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Optional as-of date
    Returns:
        str: A report of insider / buy-sell flow
    """
    return route_to_vendor("get_insider_transactions", ticker, curr_date)
