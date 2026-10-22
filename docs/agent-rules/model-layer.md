# 状态 / Schema / 模型目录（本仓库的 “Model”）

本仓库没有 ORM。这里的“模型”是图状态、Pydantic 结构化输出，以及 LLM 能力/目录。

## AgentState

字段定义在 `tradingagents/agents/utils/agent_states.py`。增删字段必须同时改：

- `Propagator.create_initial_state`
- `_log_state` / `write_report_tree` / CLI `REPORT_SECTIONS`（若对用户可见）
- 读取该字段的代理

辩论子状态用 `InvestDebateState` / `RiskDebateState`，不要另起平行 dict 约定。

## 结构化输出

- 新决策字段加到 `agents/schemas.py`，并更新对应 `render_*`，保持下游已依赖的 markdown 标题
- 可选浮点要能把 `"N/A"` / `"None"` 等收成 `None`（现有 `_coerce_optional_float`）
- 评级枚举与 `rating.RATINGS_5_TIER` 用词一致：`Buy` / `Overweight` / `Hold` / `Underweight` / `Sell`
- Trader 仍是 3 档 `Buy` / `Hold` / `Sell`，不要偷偷改成 5 档
- 无法解析的最终评级走 `extract_rating` → `REVIEW`；不要用 `parse_rating` 的静默 Hold 做交易信号

## LLM 目录与能力

- 模型 quirks 进 `capabilities.py` 的表，不要在 client 里加模型名梯子
- CLI 可见模型进 `model_catalog.py`
- 供应商是否要 key 进 `api_key_env.py`

## 记忆条目

`TradingMemoryLog` 是追加型 markdown，分隔符是 `<!-- ENTRY_END -->`。改格式必须保持可解析，并考虑 `as_of` / `resolution_date` 的回测过滤。

## 不要做的

- 引入 SQLAlchemy / Django Model
- 把图状态拆到“数据库实体”却不改 LangGraph state
- 在多个文件复制 5 档评级字符串
