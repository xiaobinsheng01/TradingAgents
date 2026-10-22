# AGENTS.md

Codex / 跨工具入口。规则正文只在 `docs/agent-rules/`。不要在本文件复制完整规则或易变模块清单。

## Skill

开发实现、修 bug、重构、改 graph / agents / dataflows / llm_clients / CLI 时，使用项目 Skill：

`.agents/skills/project-dev-loop/SKILL.md`

三套工具的 `project-dev-loop` 共用同一 `name`、`description` 和流程。

## 文档入口与优先级

**代码 > [docs/PROJECT.md](docs/PROJECT.md) > [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) > 专题文档 / [docs/tech-library/README.md](docs/tech-library/README.md)**

开始前：扫 Tech Library → 读 PROJECT.md → 加载匹配规则 → 探索复用。

## 文件路径 → canonical rule

先加载语言基线，再加载命中的分层规则。

| 路径 | 读取 |
| --- | --- |
| 任意会话 | `docs/agent-rules/project-context.md` |
| 任意会话 | `docs/agent-rules/docs-maintenance.md` |
| `**/*.py` | `docs/agent-rules/language-conventions.md`（语言基线） |
| `tradingagents/dataflows/**`、`tradingagents/agents/utils/*_tools.py` | `docs/agent-rules/api-layer.md` |
| `tradingagents/graph/**`、`tradingagents/agents/**`、`cli/**` | `docs/agent-rules/service-layer.md` |
| `tradingagents/agents/schemas.py`、`tradingagents/agents/utils/agent_states.py`、`tradingagents/llm_clients/**` | `docs/agent-rules/model-layer.md` |
| `tests/**` | `docs/agent-rules/testing.md` |
| `**/mq/**` 或用户要求新增 consumer/worker/队列 | `docs/agent-rules/mq-consumer.md` |

改 Python 时：语言基线 + 上表命中的分层规则同时加载。

## 闭环与 DoD

按 Skill 十步走。行为变更未补测、文档事实未同步、应沉淀方案未归档时，不得声称完成。

当前是仓库规范、跨工具 Skill、Rules 和代码评审驱动的软闭环。不要在本阶段添加 PR Template、CODEOWNERS 或 Branch Protection。
