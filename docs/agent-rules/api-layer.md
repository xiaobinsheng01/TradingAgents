# 数据 / 工具层（本仓库的 “API”）

本仓库没有行情数据 HTTP API。这一层是：LangChain `@tool` → `route_to_vendor` → 供应商函数。本机 loopback UI（`web/`）只编排已有跑图，不是这一层。

## 必须走的出口

```python
from tradingagents.dataflows.interface import route_to_vendor

@tool
def get_stock_data(symbol: Annotated[str, "..."], start_date: ..., end_date: ...) -> str:
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)
```

禁止在代理、graph 或 CLI 里直接调用 `y_finance` / `alpha_vantage_*` / `fred` / `polymarket`（测试里 mock 边界除外）。

现行例外：Sentiment Analyst 在 node 内预取 `get_news.func`；A 股再预取 `fetch_a_share_sentiment`（雪球/股吧），其它市场预取 `fetch_stocktwits_messages` / `fetch_reddit_posts`，不走 ToolNode。不要把这个例外扩到新分析师；新数据出口仍登记 `@tool` + `route_to_vendor`。带发布时间的社媒/资讯继续用 `date_window.in_window`。资讯 JSON 缓存走 `news_store.fetch_cached`；结构化行情 dict 走 `fetch_cached_records`；跨次累积走 `news_warehouse.upsert_items` / `query_items`，不要另写一套路径规则。雪球 cookie 只从 `XUEQIU_COOKIE` / `TRADINGAGENTS_XUEQIU_COOKIE` 读取，并把 `xq_a_token` 带到查询参数。全市场表（千股千评、A 股代码简称表、龙虎/大宗）必须按当前六位代码过滤。`stock_comment_em` 文档无参数，只允许这一次无参调用后再按代码过滤；其它接口 `TypeError` 后仍禁止无参全表。股吧旧名 `stock_guba_em` 等当前 AKShare 不存在，人气榜改 `stock_hot_rank_detail_em` / `stock_hot_keyword_em`（`SH`/`SZ`/`BJ` 大写前缀）。股吧帖子正文不恢复这些旧名，直接读东财 `listbystock`，失败再解析列表页 `article_list`；多空计数只来自这些帖子。A 股 `get_insider_transactions` 走 `akshare_flow.py`（增减持 / 龙虎买卖 / 大宗，`date<=as-of`），不是下单。A 股次日/5–20 日主数据走 `get_ashare_short_horizon`，不要把 PE/三表当明天的主特征。近半个月/近半年价量与窗口内机构出手、新闻、缠论结构走 `get_ashare_swing_tape`（`half_month` / `half_year`；缠论用 as-of 前 250 日历日日线，`dataflows/chanlun.py`），不要另开行情 HTTP，空 出手、标题或中枢写 `NO_DATA_AVAILABLE`。行业/商品只用静态关键词表（国内 SHFE/DCE + 映射的 LME/COMEX/NYMEX），不要建布局画像，也不要按公司名编伦铜。当日 live as-of 才允许附加公开最新价；历史运行禁止读该快照。live 且仓库空时事件旗标可一次性 `ingest_news`；历史 as-of 禁止。预测输出不是委托。

## 登记新方法

1. 在 `TOOLS_CATEGORIES` 归类
2. 在 `VENDOR_METHODS` 挂上各供应商实现
3. 新 `@tool` 放 `tradingagents/agents/utils/` 对应 `*_tools.py`，并在 `agent_utils` 再导出
4. 需要进某个分析师 ToolNode 时改 `TradingAgentsGraph._create_tool_nodes`

## 路由合同

- `tool_vendors[method]` 覆盖 `data_vendors[category]`
- 配置列表即链；不要把未选项静默并入
- 新供应商抛 `NoMarketDataError` / `VendorRateLimitError` / `VendorNotConfiguredError`（或薄子类）
- 不要给 `route_to_vendor` 增加新的 except 形状
- 可选类别（宏观、预测市场）失败应降级哨兵，不要中止整次运行
- 无数据返回现有 `NO_DATA_AVAILABLE` / `DATA_UNAVAILABLE` 句式，并禁止编造

## 日期与符号

- 带发布时间的内容用 `date_window.in_window`
- 查行情 / 身份 / 收益前 `normalize_symbol`（Yahoo）或 `a_share_code`（A 股）。CLI/Web 跑图 ticker 用 `run_ticker_symbol`，保留用户输入的 `.SH`。
- 过期或空 OHLCV 用 `NoMarketDataError`，不要当成功空表

## 不要做的

- 新增 Flask/FastAPI 路由充当“数据 API”
- 工具里吞掉异常后返回看起来像行情的自由文本
- 历史运行使用“今天”的社媒或宏观 vintage
