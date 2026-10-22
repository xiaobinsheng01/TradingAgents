# A 股多渠道新闻聚合

- 日期：2026-09-14
- 状态：done
- 来源：plan
- 原链接：
- 关联模块：tradingagents/dataflows/interface.py, tradingagents/dataflows/akshare_news.py, tradingagents/dataflows/symbol_utils.py, tradingagents/default_config.py, tradingagents/agents/analysts/news_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：扩展 [20260622-vendor-routing-contract.md](20260622-vendor-routing-contract.md) 的新闻方法行为，不替代价格/基本面 first-success 合同

## 背景

默认新闻供应商只有 Yahoo Finance / Alpha Vantage，对 A 股中文新闻、交易所公告和国内政策覆盖很差。用户需要一次分析同时看到国内多渠道和海外新闻，而不是失败才换下一家。

## 确认方案

1. 可选 extra `[akshare]`（`pip install ".[akshare]"`）。未安装时 `AkshareNotConfiguredError`，路由跳过该源。
2. 新 vendor `akshare` 只实现 `get_news` / `get_global_news`。个股：东方财富 `stock_news_em` + 巨潮 `stock_zh_a_disclosure_report_cninfo`（接口缺失则跳过）。宏观：当天 `news_cctv` + 财联社/东财快讯（先 CLS 后 EM）。各渠道独立超时 30s、失败降级。带发布时间的条目走 `date_window.in_window`。
3. 非 A 股 ticker 对 akshare 立刻 `NoMarketDataError`（`a_share_code`），不发 HTTP。
4. **合同扩展：** `get_news` 与 `get_global_news` 对配置列表做聚合拼接（`## Source: <vendor>`），其它方法仍是 first-success。未列入配置的供应商不会被调用。
5. 默认 `data_vendors.news_data = "akshare,yfinance"`。

## 落地调用链

```
get_news / get_global_news
  → route_to_vendor（AGGREGATE_METHODS）
  → akshare（东财 + 公告 或 联播 + 快讯）
  → yfinance（海外头条）
  → 拼接成功块；全失败则 NO_DATA_AVAILABLE / 抛第一真实错误
```
