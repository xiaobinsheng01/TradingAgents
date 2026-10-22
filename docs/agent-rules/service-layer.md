# 编排 / 代理层（本仓库的 “Service”）

本仓库没有领域 Service 单例。编排在 `tradingagents/graph/`，角色在 `tradingagents/agents/` 的 `create_*` 工厂，交互壳在 `cli/`。

## Graph

- 用 `GraphSetup.setup_graph` + `ANALYST_NODE_SPECS` 接线，不要手写平行 StateGraph
- 共享 router 的边必须带完整 `DEBATE_PATH_MAP` / `RISK_ANALYSIS_PATH_MAP`
- 新增 `should_continue_*` 时与 spec 的 `tool_node` / `clear_node` 名称一致（`social` 的 clear 是 `Msg Clear Sentiment`）
- checkpoint 生命周期用 `begin_checkpoint` / `end_checkpoint` / `checkpoint_scope`；续跑输入是 `None`
- thread id 必须包含改变图形状的选择（分析师、轮次、asset_type）

## 代理工厂

- 分析师：`create_<role>(quick_thinking_llm)`，工具从 `agent_utils` 取，提示词用 `get_language_instruction` 与 `get_instrument_context_from_state`
- 决策代理（Research Manager / Trader / Portfolio Manager）：`bind_structured` + `invoke_structured_or_freetext` + 对应 `render_*`
- 辩手开场用 `opponent_argument_or_opening`，不要对空对手词做“反驳”
- 新代码不要调用 `create_social_media_analyst`

## CLI

- 新的交互选项放 `cli/utils.py`，命令放 `cli.main` 的 Typer app
- 分析师展示名与 `ANALYST_NODE_SPECS` / `MessageBuffer.ANALYST_MAPPING` 对齐
- 报告落盘只调 `write_report_tree`
- checkpoint 旗标尊重 `TRADINGAGENTS_CHECKPOINT_ENABLED`，除非用户显式 `--checkpoint/--no-checkpoint`
- 本机操作台 `tradingagents web` 共用 `run_graph_with_events`；Docker 前后端拆成 `web-ui`/`web-api` 但只写在同一份 compose/Dockerfile 里。宿主机只绑 loopback；不要在 `web/` 再包一层行情 HTTP。「价量 Tape」页仍 `POST /api/runs`，窗口走 `swing_tape_window`，并强制 News Analyst + ingest；缠论结构挂在同一 tape，不另开接口。

## LLM

- 只通过 `create_llm_client` 建客户端
- deep / quick 分工不要随意对调（judge 类用 deep，工具循环分析师用 quick），除非方案明确改判

## 不要做的

- 在 node 里 new 一个 Chat 客户端或绕过 tool node 拉数
- 把分析师改成隐式并行（`analyst_concurrency_limit` 已删除，并行需独立确认方案）
- 新增后台 worker / MQ 消费冒充“服务层”
- 把 CLI `predict` / 图输出接到券商下单接口
