# A 股基本面三表走 AKTools，不再空返回

- 日期：2026-09-20
- 状态：done
- 来源：bugfix
- 原链接：
- 关联模块：tradingagents/dataflows/akshare_fundamentals.py, tradingagents/dataflows/interface.py, tradingagents/default_config.py, tradingagents/agents/analysts/fundamentals_analyst.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：纠正 [20260920-preserve-ashare-sh-suffix.md](20260920-preserve-ashare-sh-suffix.md) 第 3 点与 [20260916-ashare-docker-vendor-llm.md](20260916-ashare-docker-vendor-llm.md)「基本面仍 yfinance」；Yahoo 对 A 股仍跳过

## 背景

Fundamentals Analyst 调 `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` 对 `601061.SH` 全部 `NO_DATA_AVAILABLE`。不是 `.SH` vs `.SS`：默认 `fundamental_data` 只有 yfinance，而 `raise_if_a_share_yahoo` 对 A 股立刻失败。路由器没有 akshare 实现可试。

短线 tape 仍不以 PE/三表当 T+1 主特征。三表只给 Fundamentals Analyst。

## 确认方案

1. 新增 `akshare_fundamentals.py`：东财三表用 `SH601061`（不是裸六位）；财务指标用 `601061.SH`。空则 `stock_financial_report_sina(stock=sh601061, symbol=资产负债表|利润表|现金流量表)`，再东财年度表。非 A 股 `NoMarketDataError`，好让 yfinance 接上。
2. 只保留报告日 `<= as-of`；缺行禁止编造。
3. `VENDOR_METHODS` 四工具挂 `akshare`；默认 `fundamental_data = "akshare,yfinance"`。
4. Docker `web-api` 必须 recreate 后才带上新默认链。

## 落地调用链

```
get_fundamentals / 三表
  → route_to_vendor（akshare,yfinance）
  → akshare_fundamentals（AKTools HTTP）
  → 东财 SH/SZ 报告期 → 新浪 stock_financial_report_sina → 东财年度
  → 报告日 <= as-of
  → 非 A 股 / 空表：NoMarketDataError → yfinance（A 股仍立即跳过）
```
