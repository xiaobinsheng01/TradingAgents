# 豆包 / 火山方舟 LLM 供应商

- 日期：2026-09-14
- 状态：done
- 来源：agent-discussion
- 原链接：
- 关联模块：tradingagents/llm_clients/openai_client.py, tradingagents/llm_clients/model_catalog.py, tradingagents/llm_clients/api_key_env.py, cli/utils.py
- 回写文档：docs/PROJECT.md, docs/ARCHITECTURE.md, README.md
- 替代关系：无

## 结论

豆包走火山方舟 OpenAI 兼容口，登记为一等供应商 `doubao`，不走通用 `openai_compatible` 手填 URL。

- Endpoint：`https://ark.cn-beijing.volces.com/api/v3`
- 密钥：`ARK_API_KEY`
- Deep：`doubao-seed-2.1-pro`（Research Manager / Portfolio Manager）
- Quick：`doubao-seed-2.1-turbo`（分析师、辩论、交易员、风控）
- 方舟推理接入点 `ep-...` 与带日期快照 ID 经 CLI「Custom model ID」或环境变量模型字段传入；`validate_model` 接受任意字符串

不改 `DEFAULT_CONFIG` 的 OpenAI 默认。交互 CLI 选 Doubao，或设 `TRADINGAGENTS_LLM_PROVIDER=doubao` 跳过菜单。国际 BytePlus 账号不另开 `doubao-intl`，需要时用 `openai_compatible`。

## 复用

与 `kimi` / `deepseek` 同一条路径：`OPENAI_COMPATIBLE_PROVIDERS` + `PROVIDER_API_KEY_ENV` + `model_catalog.MODEL_OPTIONS` + CLI `_llm_provider_table`。`chat_class` 用默认 `NormalizedChatOpenAI`（Chat Completions，不用 Responses API）。
