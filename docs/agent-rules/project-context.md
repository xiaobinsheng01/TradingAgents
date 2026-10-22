# 项目上下文

开始任何实现前：

1. 扫 [docs/tech-library/README.md](../tech-library/README.md)；命中主题读正文。
2. 读 [docs/PROJECT.md](../PROJECT.md)。
3. 需要拓扑、状态或扩展点时再读 [docs/ARCHITECTURE.md](../ARCHITECTURE.md)。
4. 用代码核对：目录、调用链、配置键、复用清单若与文档冲突，以代码为准并回写文档。

## 这是什么项目

进程内 LangGraph 多代理研究框架。入口是 CLI、本机 loopback Web 操作台（`tradingagents web`）和 `TradingAgentsGraph`。不是多用户 SaaS，也不是行情数据 HTTP API。

不要假设本仓库有领域 Service、ORM、MQ 或定时任务。那些层不存在。

## 文档优先级

代码 > PROJECT.md > ARCHITECTURE.md > 专题文档 / Tech Library

## 闭环

走 `project-dev-loop` Skill。行为变更未补测、文档事实未同步、应沉淀方案未归档时，不得声称完成。

## 安全与提交

- 密钥只来自环境变量 / `.env` / `.env.enterprise`
- 不提交 `.env`、虚拟环境、`reports/`、生成缓存
- ticker 写入路径前必须 `safe_ticker_component`

## 硬门禁

当前是文档 + Skill + Rules + 评审的软闭环。不要在本阶段擅自加 PR Template、CODEOWNERS 或 Branch Protection。
