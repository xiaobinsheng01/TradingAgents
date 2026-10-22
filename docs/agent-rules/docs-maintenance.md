# 文档维护

改代码后同步事实，不要把过期分层写进文档。

## 回写落点

| 变化 | 回写 |
| --- | --- |
| 目录、入口、调用链、复用清单、禁止项、命令 | [docs/PROJECT.md](../PROJECT.md) |
| Graph 边、状态字段、供应商路由、LLM 分发、扩展点 | [docs/ARCHITECTURE.md](../ARCHITECTURE.md) |
| 确认方案已落地或明确取消 | [docs/tech-library/](../tech-library/README.md) |
| 用户可见安装/启动 | 根 [README.md](../../README.md)（增量，不拆掉现有研究说明） |

更新 `最后更新日期`。

## Tech Library

文首必须有：日期、状态、来源、原链接（外部方案必填）、关联模块、回写文档、替代关系。

文件名：`YYYYMMDD-<slug>.md`。被替代条目改为 `superseded` 并指向新文件。索引表与文件同步。

Plan 流程图写入方案正文，或把落地调用链补进 ARCHITECTURE。

## 豁免

纯 typo/格式、无行为内部重构、无结论排障、未确认中间稿。

## 禁止

- 在 `.cursor/`、`.claude/`、`.agents/`、`AGENTS.md`、`CLAUDE.md` 复制完整规则或易变模块清单
- 用其它项目的 API/MQ/ORM 叙述覆盖本仓库事实
- 文档里写死密钥、完整 `.env`、或会过期的模型 ID 长名单（指向源码）
