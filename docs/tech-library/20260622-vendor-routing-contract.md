# 已配置供应商链即解析链

- 日期：2026-06-22
- 状态：done
- 来源：breaking-change
- 原链接：
- 关联模块：tradingagents/dataflows/interface.py, tradingagents/dataflows/errors.py, tradingagents/dataflows/symbol_utils.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md
- 替代关系：无

## 背景

早期路由会在主供应商失败时静默落到用户没选的实现，造成跨供应商数据不一致（`#988` / `#289`）。空结果以自由文本回到代理，模型会编造价格。

## 确认合同（v0.3.0 起）

1. `data_vendors` / `tool_vendors` 里的列表就是解析链；只有 `"default"` 才使用该方法全部已注册供应商。
2. 供应商失败按行为分类：`VendorRateLimitError` / `VendorNotConfiguredError` 试下一个；`NoMarketDataError` 记下来；其它异常记日志后继续，最终抛第一个真实错误。
3. 全部无数据时返回 `NO_DATA_AVAILABLE` 哨兵，并明确禁止估算。
4. `macro_data` 与 `prediction_markets` 为可选类别，失败降级为 `DATA_UNAVAILABLE`，不中止整次分析。
5. 每个 vendor 路径先 `normalize_symbol`；过期或空 OHLCV 用 `NoMarketDataError`，不要塞空字符串。

## 破坏性含义

调用方不能再假设“配了 yfinance 还会自动用 Alpha Vantage 兜底”。需要兜底时必须显式写成 `"yfinance,alpha_vantage"`。

新供应商只抛既有 `VendorError` 子类，不要给 router 增加新的 except 形状。
