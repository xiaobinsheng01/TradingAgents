from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_ashare_short_horizon,
    get_ashare_swing_tape,
    get_indicators,
    get_instrument_context_from_state,
    get_language_instruction,
    get_stock_data,
    get_verified_market_snapshot,
)
from tradingagents.agents.utils.rating import T1_BIAS_INSTRUCTION
from tradingagents.dataflows.ashare_playbook import extract_playbook_section


def _message_text(message) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _with_playbook_section(report: str, messages) -> str:
    """Keep the tape's T+1 stance in the report even if the model paraphrases it."""
    blob = "\n".join(_message_text(message) for message in messages or [])
    section = extract_playbook_section(blob)
    if not section or section in (report or ""):
        return report or ""
    base = (report or "").rstrip()
    if not base:
        return section
    return f"{base}\n\n{section}"


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_stock_data,
            get_ashare_short_horizon,
            get_ashare_swing_tape,
            get_indicators,
            get_verified_market_snapshot,
        ]

        system_message = (
            """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy. Categories and each category's indicators are:

Moving Averages:
- close_50_sma: 50 SMA: A medium-term trend indicator. Usage: Identify trend direction and serve as dynamic support/resistance. Tips: It lags price; combine with faster indicators for timely signals.
- close_200_sma: 200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend and identify golden/death cross setups. Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries.
- close_10_ema: 10 EMA: A responsive short-term average. Usage: Capture quick shifts in momentum and potential entry points. Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals.

MACD Related:
- macd: MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers and divergence as signals of trend changes. Tips: Confirm with other indicators in low-volatility or sideways markets.
- macds: MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with the MACD line to trigger trades. Tips: Should be part of a broader strategy to avoid false positives.
- macdh: MACD Histogram: Shows the gap between the MACD line and its signal. Usage: Visualize momentum strength and spot divergence early. Tips: Can be volatile; complement with additional filters in fast-moving markets.

Momentum Indicators:
- rsi: RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply 70/30 thresholds and watch for divergence to signal reversals. Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis.

Volatility Indicators:
- boll: Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: Acts as a dynamic benchmark for price movement. Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals.
- boll_ub: Bollinger Upper Band: Typically 2 standard deviations above the middle line. Usage: Signals potential overbought conditions and breakout zones. Tips: Confirm signals with other tools; prices may ride the band in strong trends.
- boll_lb: Bollinger Lower Band: Typically 2 standard deviations below the middle line. Usage: Indicates potential oversold conditions. Tips: Use additional analysis to avoid false reversal signals.
- atr: ATR: Averages true range to measure volatility. Usage: Set stop-loss levels and adjust position sizes based on current market volatility. Tips: It's a reactive measure, so use it as part of a broader risk management strategy.

Volume-Based Indicators:
- vwma: VWMA: A moving average weighted by volume. Usage: Confirm trends by integrating price action with volume data. Tips: Watch for skewed results from volume spikes; use in combination with other volume analyses.

- Select indicators that provide diverse and complementary information. Avoid redundancy (e.g., do not select both rsi and stochrsi). Also briefly explain why they are suitable for the given market context. When you tool call, please use the exact name of the indicators provided above as they are defined parameters, otherwise your call will fail. Please make sure to call get_stock_data first to retrieve the CSV that is needed to generate indicators. Then use get_indicators with the specific indicator names. For China A-shares those tools prefer local AKTools (East Money) and only fall back to Yahoo if that path has no data.

For China A-share tickers (six-digit codes, `.SS` / `.SH` / `.SZ` / `.BJ`), also call get_ashare_short_horizon(ticker, curr_date) and treat it as the primary tape for **next-session (T+1)** and **5–20 trading-day** views: daily amount/turnover, limit-up/limit-down flags, board lot (10/20/30%), market breadth, lagged northbound, dragon-tiger **buy/sell seats and amounts**, unlock windows, event flags, and the tape's **industry/commodity exposure** block (sector index relative strength plus any mapped domestic and international prints — 沪铜/LME copper/COMEX copper, 碳酸锂, 铁矿/SGX, 豆粕/CBOT, 橡胶, 原油/NYMEX, liquor or bank index, and similar rows). Use those prints when present. If industry_map or commodity / intl_commodity rows are `<unavailable>`, say so — do **not** invent 铜价, 伦铜, 锂价, 有色指数, or other input prices from the company name. On a same-day (live) run the tape also includes a **Live snapshot** of the latest public print; use it as the current state for the prediction. Do **not** use PE/PB/ROE as the main next-day features. Limit-up seals are unbuyable until they open. The tape's **Playbook stance (T+1)** block is the next-session constraint: quote its `t1_bias` line unchanged. """
            + T1_BIAS_INSTRUCTION
            + """ If the tape returns NO_DATA_AVAILABLE or DATA_UNAVAILABLE, say so and fall back to get_stock_data; do not invent 涨停, 北向, or 龙虎榜 numbers.

Also call get_ashare_swing_tape(ticker, curr_date, window) with window `half_month` (近半个月, 15 calendar days), `three_months` (近3个月, 90 calendar days), or `half_year` (近半年, 180 calendar days) as named in the instrument context (default half_month). Treat that tape as the **price/volume/缠论/机构出手/news** evidence for subsequent-trend research: window return, high/low, volume vs average, turnover, limit days, vs 沪深300, lagged northbound in the window, 缠论 分型/笔/线段/中枢 (from ~250 calendar days of closed bars, date<=as-of), disclosed 增减持 / 龙虎 / 大宗, and window news/filings. Empty 机构出手, news, or 缠论 structure is NO_DATA_AVAILABLE — do not invent 出手/买入, headlines, 中枢, or 买卖点. Use the 缠论 block for subsequent-trend structure (in/above/below 中枢, last 笔/线段); a 三类买点/卖点候选 is a research note, not an order. Quote the swing tape's **`trend_bias`** line unchanged when present; `trend_bias: SELL` caps how bullish the final rating may be. The team's BUY/HOLD/SELL is a research rating for the prediction — this framework never places broker orders.

Before writing the final report, call get_verified_market_snapshot for this ticker and the current date, and treat it as the source of truth for any exact OHLCV, price-level, or indicator-value claim. If another tool's output conflicts with the verified snapshot, flag the discrepancy rather than inventing a reconciled number. Do not claim historical validation, support/resistance bounces, or exact percentage moves unless they are directly supported by tool output with concrete dates and prices.

Write a very detailed and nuanced report of the trends you observe. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = _with_playbook_section(
                _message_text(result),
                list(state["messages"]) + [result],
            )

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
