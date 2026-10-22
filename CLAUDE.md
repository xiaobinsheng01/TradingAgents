# CLAUDE.md

Claude Code 常驻入口。规则正文只在 `docs/agent-rules/`。本文件和 `.claude/rules/` 只引用，不复制完整规则。

## 必读

1. 扫 [docs/tech-library/README.md](docs/tech-library/README.md)
2. 读 [docs/PROJECT.md](docs/PROJECT.md)
3. 需要拓扑时读 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

文档优先级：**代码 > docs/PROJECT.md > docs/ARCHITECTURE.md > 专题文档 / Tech Library**

## Skill

实现、修 bug、重构时使用：

`.claude/skills/project-dev-loop/SKILL.md`

与 Cursor / Codex 的 `project-dev-loop` 同名、同描述、同流程。

## 规则适配

`.claude/rules/` 中**没有 `paths`** 的文件为常驻规则（`project-context`、`docs-maintenance`）。带 `paths` 的按文件命中。每条适配器只要求读取对应的 `docs/agent-rules/<name>.md`。

改 Python 时同时加载语言基线和命中的分层规则。

## 闭环

按 Skill 执行。行为变更未补测、文档事实未同步、应沉淀方案未归档时，不得声称完成。

当前是软闭环（文档、Skill、Rules、评审）。GitHub 硬门禁（PR Template、CODEOWNERS、Branch Protection）不在本阶段范围。
