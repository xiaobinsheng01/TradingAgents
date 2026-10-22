from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_insider_transactions,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
)


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_news,
            get_global_news,
            get_insider_transactions,
            get_macro_indicators,
            get_prediction_markets,
        ]

        system_message = (
            f"You are a news researcher tasked with analyzing recent news and trends. "
            f"Write a comprehensive report focused on {asset_label}-specific developments that can affect this ticker. "
            f"Cover company-specific news and A-share filings/announcements first. "
            f"If the instrument context names a Swing tape window of half_month, call "
            f"`get_news(ticker, start_date, end_date)` with start_date 15 calendar days before "
            f"today's date and end_date equal to today's date, and call "
            f"`get_global_news(curr_date, look_back_days)` with look_back_days=15. "
            f"If the window is three_months, use 90 calendar days; if half_year, "
            f"use 180 calendar days instead. "
            f"Otherwise cover the past week. "
            f"Use get_news(ticker, start_date, end_date) as the primary source for this {asset_label} "
            f"(Chinese A-share coverage includes East Money news, exchange announcements, "
            f"Tonghuashun/Futu flashes, and state-media headlines that mention this ticker "
            f"when configured; overseas vendors cover English-language headlines). "
            f"get_global_news(curr_date, look_back_days, limit) is domestic China policy "
            f"(新闻联播, 人民日报, 新华社财经, 中国经济网/经济日报, 中新网财经, 央视新闻, 中国政府网, "
            f"中国人民银行, 财政部, 国家发展改革委, 国家统计局) "
            f"plus overseas Serper Google Search (Reuters/Bloomberg-style headlines and public "
            f"X / YouTube / Meta posts found via site: queries) for market conditions "
            f"that can affect A-shares. Cite a global or platform item only when it "
            f"clearly affects this ticker or the China session (Fed, USD/CNY, commodities, "
            f"tariffs, overnight US futures); "
            f"do not treat unrelated company headlines, sector ETFs, or generic wires as news about this stock. "
            f"get_insider_transactions(ticker, curr_date) is disclosed buy/sell flow: "
            f"A-share 董监高/股东增减持, dragon-tiger 买入/卖出席位, and 大宗交易 via AKTools "
            f"(point-in-time on or before curr_date). Call it for mainland listings. "
            f"Cite only this ticker's prints; do not invent 出手/买入. This is research, never an order. "
            f"get_macro_indicators(indicator, curr_date, look_back_days) is optional US FRED "
            f"(e.g. 'cpi', 'fed_funds_rate', '10y_treasury'). Cite a print only when it clearly "
            f"affects this ticker or the China session (USD/CNY, risk-off, commodities); do not "
            f"write a Fed-driven A-share thesis from US CPI alone. Leave the tool unused if it is not relevant. "
            f"get_prediction_markets(topic, limit) is optional Polymarket odds. Cite a contract only "
            f"when the event clearly affects this ticker; skip US-election contracts for unrelated A-shares. "
            f"Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
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
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
